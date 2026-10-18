from __future__ import annotations

from datetime import datetime, timezone
import os
import threading
import time
import unittest
from unittest import mock

import psycopg
from flask import Flask

from backend import db
from backend.app import create_app
from backend.background import WorkerLoop, WorkerSignal
from backend.http_boundary import configure_cors
from backend.imports_api import ImportJob, create_imports_blueprint
from backend.query_api import (
    QueryValidationError,
    compile_aggregate_query,
    validate_query_request,
)


def auth_headers(ldihk_id: str = "ldihk-cosmic-nebula-abcdefgh2345") -> dict[str, str]:
    return {"Authorization": f"Bearer {ldihk_id}"}


class FakeCursor:
    def __init__(self, columns: list[str], rows: list[tuple]):
        self.description = [(column,) for column in columns]
        self._rows = rows

    def fetchall(self):
        return self._rows


class SummaryConnection:
    """Answers the two queries fetch_user_summary makes."""

    def __init__(self, *, user_exists: bool, platform_rows: list[tuple] | None = None):
        self.user_exists = user_exists
        self.platform_rows = platform_rows or []
        self.calls: list[tuple[str, list]] = []

    def execute(self, sql: str, parameters):
        self.calls.append((sql, parameters))
        if "FROM users WHERE external_id" in sql:
            return FakeCursor(["id"], [("user-uuid",)] if self.user_exists else [])
        return FakeCursor(
            [
                "platform",
                "event_count",
                "watch_event_count",
                "first_event_at",
                "last_event_at",
                "min_date",
                "max_date",
            ],
            self.platform_rows,
        )

    def close(self):
        pass


class FakeImportsRepository:
    def __init__(self, latest: ImportJob | None = None):
        self.latest = latest
        self.created: list[str] = []

    def create_import(self, *, user_external_id, s3_bucket, s3_key, s3_etag, age=None, sex=None):
        self.created.append(s3_key)
        return ImportJob(
            import_id="00000000-0000-0000-0000-000000000001",
            user_id=user_external_id,
            status="queued",
            records_seen=0,
            records_imported=0,
            warnings_count=0,
            error_message=None,
            created_at=None,
            started_at=None,
            finished_at=None,
        )

    def get_import(self, import_id):
        return None

    def get_latest_import_for_user(self, external_id):
        return self.latest


def _app(connection_factory, repository=None, **kwargs) -> Flask:
    return create_app(
        imports_repository=repository or FakeImportsRepository(),
        query_connection_factory=connection_factory,
        start_workers=False,
        **kwargs,
    )


class CurrentUserSummaryTests(unittest.TestCase):
    def test_unknown_id_returns_404(self):
        app = _app(lambda: SummaryConnection(user_exists=False))

        response = app.test_client().get("/api/me", headers=auth_headers())

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.get_json(), {"error": "unknown_ldihk_id"})

    def test_returns_per_platform_bounds_in_requested_timezone(self):
        first = datetime(2019, 1, 2, 10, tzinfo=timezone.utc)
        last = datetime(2026, 10, 1, 22, tzinfo=timezone.utc)
        connection = SummaryConnection(
            user_exists=True,
            platform_rows=[("youtube", 120, 100, first, last, "2019-01-02", "2026-10-02")],
        )
        app = _app(lambda: connection)

        response = app.test_client().get(
            "/api/me?timezone=Europe/Berlin", headers=auth_headers()
        )

        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(body["timezone"], "Europe/Berlin")
        self.assertEqual(body["datasets"]["youtube"]["max_date"], "2026-10-02")
        self.assertEqual(body["datasets"]["youtube"]["watch_event_count"], 100)
        self.assertIsNone(body["latest_import"])
        bounds_sql = connection.calls[1][0]
        self.assertIn("AT TIME ZONE 'Europe/Berlin'", bounds_sql)

    def test_user_with_only_a_pending_import_is_known(self):
        latest = ImportJob(
            import_id="00000000-0000-0000-0000-000000000009",
            user_id="ldihk-cosmic-nebula-abcdefgh2345",
            status="running",
            records_seen=0,
            records_imported=0,
            warnings_count=0,
            error_message=None,
            created_at=None,
            started_at=None,
            finished_at=None,
        )
        app = _app(
            lambda: SummaryConnection(user_exists=False),
            repository=FakeImportsRepository(latest=latest),
        )

        response = app.test_client().get("/api/me", headers=auth_headers())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["datasets"], {})
        self.assertEqual(response.get_json()["latest_import"]["status"], "running")

    def test_invalid_timezone_is_rejected(self):
        app = _app(lambda: SummaryConnection(user_exists=True))

        response = app.test_client().get(
            "/api/me?timezone=Mars/Olympus", headers=auth_headers()
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json(), {"error": "invalid_timezone"})


class DatabaseOutageTests(unittest.TestCase):
    def test_unreachable_database_returns_503_json_without_details(self):
        def unreachable():
            raise psycopg.OperationalError("connection to server at db.example failed")

        client = _app(unreachable).test_client()
        responses = [
            client.post(
                "/api/query",
                headers=auth_headers(),
                json={"dataset": "youtube_usage", "metrics": ["event_count"], "dimensions": []},
            ),
            client.post(
                "/api/population",
                headers=auth_headers(),
                json={"startDate": "2026-01-01", "endDate": "2026-01-07"},
            ),
            client.get("/api/me", headers=auth_headers()),
        ]

        for response in responses:
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.get_json(), {"error": "database_unavailable"})

    def test_unmigrated_database_returns_503_and_logs_the_fix(self):
        # Staging once ran without RUN_WORKERS_IN_PROCESS, so no migrations ran
        # and every request failed with a bare 500.
        def unmigrated():
            connection = mock.MagicMock()
            connection.execute.side_effect = psycopg.errors.UndefinedTable(
                'relation "users" does not exist'
            )
            return connection

        client = _app(unmigrated).test_client()
        with mock.patch.object(db, "_warned_schema_missing", False):
            with self.assertLogs("backend.db", level="ERROR") as logs:
                responses = [
                    client.get("/api/me", headers=auth_headers()),
                    client.post(
                        "/api/query",
                        headers=auth_headers(),
                        json={"dataset": "youtube_usage", "metrics": ["event_count"], "dimensions": []},
                    ),
                ]

        for response in responses:
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.get_json(), {"error": "database_unavailable"})
        self.assertEqual(len(logs.records), 1)
        self.assertIn("RUN_WORKERS_IN_PROCESS=true", logs.output[0])


class PostgresTimezoneTests(unittest.TestCase):
    def test_timezone_unknown_to_postgres_is_a_client_error(self):
        class RejectingConnection(SummaryConnection):
            def execute(self, sql, parameters):
                if "AT TIME ZONE" in sql:
                    raise psycopg.errors.InvalidParameterValue(
                        'time zone "Europe/Berlin" not recognized'
                    )
                return super().execute(sql, parameters)

        app = _app(lambda: RejectingConnection(user_exists=True))

        response = app.test_client().get(
            "/api/me?timezone=Europe/Berlin", headers=auth_headers()
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json(), {"error": "invalid_timezone"})


class QueryContractTests(unittest.TestCase):
    def _query(self, **options):
        return validate_query_request(
            {
                "dataset": "youtube_usage",
                "user_id": "demo_user",
                "metrics": ["estimated_watch_seconds"],
                "dimensions": ["date", "hour"],
                "filters": {"start_date": "2026-06-01", "end_date": "2026-06-06"},
                "options": options,
            }
        )

    def test_timezone_option_moves_buckets_and_date_filters(self):
        compiled = compile_aggregate_query(self._query(timezone="Asia/Hong_Kong"))

        self.assertIn(
            "EXTRACT(HOUR FROM ue.occurred_at AT TIME ZONE 'Asia/Hong_Kong')",
            compiled.sql,
        )
        self.assertIn(
            "(%s::date::timestamp AT TIME ZONE 'Asia/Hong_Kong')", compiled.sql
        )

    def test_invalid_timezone_option_is_rejected(self):
        with self.assertRaises(QueryValidationError) as context:
            self._query(timezone="Europe/Berlin'; DROP TABLE users; --")
        self.assertEqual(context.exception.code, "invalid_timezone")

    def test_instagram_views_count_as_watches(self):
        compiled = compile_aggregate_query(self._query())

        self.assertIn(
            "ue.platform = 'instagram' AND ue.event_type IN "
            "('video_watch', 'story_view', 'post_view')",
            compiled.sql,
        )

    def test_dates_must_be_strict_iso_and_ordered(self):
        for filters, code in (
            ({"start_date": "2024-03-01", "end_date": "20240201"}, "invalid_date_filter"),
            ({"start_date": "2024-03-01", "end_date": "2024-02-01"}, "invalid_date_range"),
        ):
            with self.subTest(filters=filters):
                with self.assertRaises(QueryValidationError) as context:
                    validate_query_request(
                        {
                            "dataset": "youtube_usage",
                            "user_id": "demo_user",
                            "metrics": ["event_count"],
                            "dimensions": [],
                            "filters": filters,
                        }
                    )
                self.assertEqual(context.exception.code, code)


class BoundaryTests(unittest.TestCase):
    def test_bearer_ids_outside_the_safe_alphabet_are_rejected(self):
        client = _app(lambda: SummaryConnection(user_exists=False)).test_client()

        for bad_id in ("a", "../etc", "bad/id", "x" * 200, "ümlaut-id"):
            with self.subTest(bad_id=bad_id):
                response = client.get("/api/me", headers=auth_headers(bad_id))
                self.assertEqual(response.status_code, 401)
                self.assertEqual(response.get_json(), {"error": "invalid_authorization"})

    def test_localhost_origins_can_be_disabled_for_production(self):
        app = Flask(__name__)
        configure_cors(
            app,
            environ={
                "FRONTEND_ALLOWED_ORIGINS": "https://ldihk.xyz/",
                "ALLOW_LOCALHOST_ORIGINS": "false",
            },
        )

        @app.get("/ping")
        def ping():
            return "ok"

        client = app.test_client()
        allowed = client.get("/ping", headers={"Origin": "https://ldihk.xyz"})
        local = client.get("/ping", headers={"Origin": "http://localhost:4321"})

        self.assertEqual(allowed.headers.get("Access-Control-Allow-Origin"), "https://ldihk.xyz")
        self.assertIsNone(local.headers.get("Access-Control-Allow-Origin"))

    def test_local_file_routes_can_be_disabled(self):
        app = _app(
            lambda: SummaryConnection(user_exists=False),
            enable_local_file_routes=False,
        )

        response = app.test_client().get("/api/users/local_user/youtube-usage")

        self.assertEqual(response.status_code, 404)

    def test_import_creation_wakes_the_workers(self):
        woken: list[bool] = []
        app = Flask(__name__)
        app.register_blueprint(
            create_imports_blueprint(
                FakeImportsRepository(), on_import_created=lambda: woken.append(True)
            )
        )
        ldihk_id = "ldihk-cosmic-nebula-abcdefgh2345"

        with mock.patch.dict(os.environ, {"S3_BUCKET": "ldihk-uploads"}):
            response = app.test_client().post(
                "/api/imports",
                headers=auth_headers(ldihk_id),
                json={
                    "s3_bucket": "ldihk-uploads",
                    "s3_key": f"uploads/{ldihk_id}/Takeout.ZIP",
                },
            )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(woken, [True])


class WorkerLoopTests(unittest.TestCase):
    def test_loop_stays_off_the_database_until_there_is_activity(self):
        clock = [0.0]
        signal = WorkerSignal(active_window_seconds=10, clock=lambda: clock[0])
        calls: list[int] = []
        clock[0] = 100.0  # The startup activity has expired.

        def run_once() -> bool:
            calls.append(1)
            return False

        loop = WorkerLoop("test", run_once, signal=signal, poll_interval_seconds=0.02)
        thread = threading.Thread(target=loop.run, daemon=True)
        thread.start()
        time.sleep(0.1)
        calls_while_idle = len(calls)
        signal.notify()
        time.sleep(0.1)
        loop.stop()
        thread.join(timeout=2)

        self.assertEqual(calls_while_idle, 0)
        self.assertGreaterEqual(len(calls), 1)

    def test_loop_survives_exceptions(self):
        signal = WorkerSignal(active_window_seconds=60)
        attempts: list[int] = []

        def run_once() -> bool:
            attempts.append(1)
            if len(attempts) == 1:
                raise RuntimeError("database went away")
            return False

        loop = WorkerLoop("test", run_once, signal=signal, poll_interval_seconds=0.02)
        thread = threading.Thread(target=loop.run, daemon=True)
        thread.start()
        time.sleep(0.05)
        signal.notify()  # Cut the 5 s error backoff short.
        time.sleep(0.1)
        loop.stop()
        thread.join(timeout=2)

        self.assertGreaterEqual(len(attempts), 2)
        self.assertFalse(thread.is_alive())



class EnrichmentAvailabilityTests(unittest.TestCase):
    def _job(self, enrichment_status):
        return ImportJob(
            import_id="00000000-0000-0000-0000-000000000003",
            user_id="ldihk-cosmic-nebula-abcdefgh2345",
            status="completed",
            records_seen=1,
            records_imported=1,
            warnings_count=0,
            error_message=None,
            created_at=None,
            started_at=None,
            finished_at=None,
            enrichment_status=enrichment_status,
        )

    def test_queued_enrichment_without_api_key_is_reported_unavailable(self):
        from backend.imports_api import status_payload

        with mock.patch.dict(os.environ, {"RUN_WORKERS_IN_PROCESS": "true"}, clear=False):
            os.environ.pop("YOUTUBE_API_KEY", None)
            self.assertEqual(status_payload(self._job("queued"))["enrichment_status"], "unavailable")
            self.assertEqual(status_payload(self._job("completed"))["enrichment_status"], "completed")

        with mock.patch.dict(
            os.environ, {"RUN_WORKERS_IN_PROCESS": "true", "YOUTUBE_API_KEY": "key"}, clear=False
        ):
            self.assertEqual(status_payload(self._job("queued"))["enrichment_status"], "queued")

    def test_separate_worker_deployments_keep_queued_status(self):
        from backend.imports_api import status_payload

        with mock.patch.dict(os.environ, {"RUN_WORKERS_IN_PROCESS": "false"}, clear=False):
            os.environ.pop("YOUTUBE_API_KEY", None)
            self.assertEqual(status_payload(self._job("queued"))["enrichment_status"], "queued")



class DeleteMyDataTests(unittest.TestCase):
    class _NoUserConnection:
        def execute(self, sql, parameters=None):
            class _Cursor:
                rowcount = 0

                def fetchone(self):
                    return None

                def fetchall(self):
                    return []

            return _Cursor()

        def commit(self):
            pass

        def rollback(self):
            pass

        def close(self):
            pass

    def test_deletion_requires_repeating_the_id(self):
        client = _app(lambda: self._NoUserConnection()).test_client()

        for body in (None, {}, {"confirm": "someone-else"}):
            with self.subTest(body=body):
                response = client.delete("/api/me", headers=auth_headers(), json=body)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.get_json(), {"error": "confirmation_mismatch"})

    def test_deleting_an_unknown_id_is_404(self):
        client = _app(lambda: self._NoUserConnection()).test_client()
        ldihk_id = "ldihk-cosmic-nebula-abcdefgh2345"

        response = client.delete("/api/me", headers=auth_headers(ldihk_id), json={"confirm": ldihk_id})

        self.assertEqual(response.status_code, 404)

    def test_preflight_allows_delete(self):
        with mock.patch.dict(os.environ, {"FRONTEND_ALLOWED_ORIGINS": "https://ldihk.xyz"}, clear=False):
            app = _app(lambda: self._NoUserConnection())
        response = app.test_client().options(
            "/api/me",
            headers={"Origin": "https://ldihk.xyz", "Access-Control-Request-Method": "DELETE"},
        )

        self.assertIn("DELETE", response.headers["Access-Control-Allow-Methods"])

    def test_upload_cleanup_deletes_known_keys_without_listing_the_bucket(self):
        from backend.user_data import delete_user_uploads

        class FakeS3:
            """Only single deletes (free on R2); listing would be billed."""

            def __init__(self):
                self.deleted = []

            def delete_object(self, Bucket, Key):
                if Key.endswith("broken.zip"):
                    raise RuntimeError("network")
                self.deleted.append((Bucket, Key))

        objects = [
            ("bucket", "uploads/ldihk-x-abc/a.zip"),
            ("bucket", "uploads/ldihk-x-abc/broken.zip"),
            ("bucket", "uploads/ldihk-x-abc/b.zip"),
        ]
        s3 = FakeS3()
        connection = self._NoUserConnection()
        with self.assertLogs("backend.uploads", level="WARNING"):
            count = delete_user_uploads(connection, objects, s3_client=s3, environ={"S3_BUCKET": "bucket"})

        self.assertEqual(count, 2)
        self.assertEqual(s3.deleted, [objects[0], objects[2]])
        self.assertIsNone(delete_user_uploads(connection, objects, s3_client=s3, environ={}))


if __name__ == "__main__":
    unittest.main()
