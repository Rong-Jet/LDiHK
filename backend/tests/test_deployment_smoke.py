from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

from backend.app import create_app
from backend.db import run_migrations
from backend.imports_api import ImportJob as ApiImportJob
from backend.ingestion.s3 import S3ObjectMetadata
from backend.ingestion.worker import (
    IMPORT_STATUS_COMPLETED,
    ImportJob,
    ImportWarningWrite,
    S3ZipImportWorker,
    SubscriptionWrite,
    UsageEventWrite,
)
from backend.scripts import smoke_hosted_youtube_takeout as hosted_smoke


ROOT = Path(__file__).resolve().parents[2]


class DeploymentSmokeTests(unittest.TestCase):
    def test_deployment_files_document_commands_healthcheck_and_env(self):
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        deployment_doc = (ROOT / "docs/backend/deployment.md").read_text(
            encoding="utf-8"
        )
        env_example = (ROOT / ".env.example").read_text(encoding="utf-8")
        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        uv_lock = (ROOT / "uv.lock").read_text(encoding="utf-8")

        self.assertIn('"gunicorn', dockerfile)
        self.assertIn("backend.app:app", dockerfile)
        self.assertIn("HEALTHCHECK", dockerfile)
        self.assertIn('"gunicorn>=', pyproject)
        self.assertIn('name = "gunicorn"', uv_lock)
        self.assertIn("gunicorn -b 0.0.0.0:$PORT backend.app:app", deployment_doc)
        self.assertIn("backend/scripts/run_worker.py", deployment_doc)
        self.assertIn("backend/scripts/run_enrichment_worker.py", deployment_doc)
        self.assertIn("backend/scripts/run_migrations.py", deployment_doc)
        self.assertIn("backend/scripts/smoke_hosted_youtube_takeout.py", deployment_doc)
        self.assertIn("one Docker image", deployment_doc)

        for variable in (
            "PORT",
            "DATABASE_URL",
            "FRONTEND_ALLOWED_ORIGINS",
            "REQUIRE_LDIHK_BEARER",
            "ALLOW_IDENTIFIER_DIMENSIONS",
            "QUERY_BUCKET_TIMEZONE",
            "AWS_ACCESS_KEY_ID",
            "AWS_SECRET_ACCESS_KEY",
            "AWS_SESSION_TOKEN",
            "AWS_REGION",
            "S3_BUCKET",
            "MAX_IMPORT_ZIP_BYTES",
            "IMPORT_WORKER_POLL_INTERVAL_SECONDS",
            "YOUTUBE_API_KEY",
            "YOUTUBE_MAX_DURATION_SECONDS",
            "ENRICHMENT_BATCH_SIZE",
            "ENRICHMENT_POLL_INTERVAL_SECONDS",
            "ENRICHMENT_RETRY_BASE_SECONDS",
            "LOG_LEVEL",
            "TEST_DATABASE_URL",
            "BACKEND_BASE_URL",
            "SMOKE_LDIHK_ID",
            "SMOKE_WRONG_LDIHK_ID",
            "SMOKE_S3_KEY",
            "SMOKE_EXPECTED_EVENT_COUNT",
            "SMOKE_EXPECTED_WATCH_COUNT",
            "SMOKE_IMPORT_TIMEOUT_SECONDS",
            "SMOKE_ENRICHMENT_TIMEOUT_SECONDS",
            "SMOKE_POLL_INTERVAL_SECONDS",
            "SMOKE_HTTP_TIMEOUT_SECONDS",
        ):
            self.assertRegex(env_example, rf"(?m)^{variable}=")

    def test_db_backed_routes_return_stable_unavailable_without_database_url(self):
        app = create_app()
        client = app.test_client()
        auth_headers = {"Authorization": "Bearer smoke_user"}

        with patch.dict(
            "os.environ",
            {"DATABASE_URL": "", "S3_BUCKET": "smoke-bucket"},
            clear=False,
        ):
            health_response = client.get("/health")
            unauthenticated_create_response = client.post(
                "/api/imports",
                json={
                    "s3_bucket": "smoke-bucket",
                    "s3_key": "uploads/smoke_user/takeout.zip",
                },
            )
            unauthenticated_get_response = client.get(
                "/api/imports/00000000-0000-0000-0000-000000000001"
            )
            unauthenticated_query_response = client.post(
                "/api/query",
                json={
                    "dataset": "youtube_usage",
                    "metrics": ["event_count"],
                    "dimensions": ["event_type"],
                    "filters": {},
                },
            )

            authenticated_create_response = client.post(
                "/api/imports",
                headers=auth_headers,
                json={
                    "s3_bucket": "smoke-bucket",
                    "s3_key": "uploads/smoke_user/takeout.zip",
                },
            )
            authenticated_get_response = client.get(
                "/api/imports/00000000-0000-0000-0000-000000000001",
                headers=auth_headers,
            )
            authenticated_query_response = client.post(
                "/api/query",
                headers=auth_headers,
                json={
                    "dataset": "youtube_usage",
                    "metrics": ["event_count"],
                    "dimensions": ["event_type"],
                    "filters": {},
                },
            )

        self.assertEqual(health_response.status_code, 200)
        self.assertEqual(health_response.get_json(), {"status": "ok"})
        for response in (
            unauthenticated_create_response,
            unauthenticated_get_response,
            unauthenticated_query_response,
        ):
            self.assertEqual(response.status_code, 401)
            self.assertEqual(response.get_json(), {"error": "missing_authorization"})
        for response in (
            authenticated_create_response,
            authenticated_get_response,
            authenticated_query_response,
        ):
            self.assertEqual(response.status_code, 503)
            self.assertEqual(
                response.get_json(),
                {
                    "error": "database_unavailable",
                    "message": "DATABASE_URL is required to connect to Postgres",
                },
            )

    def test_provider_setup_docs_cover_render_supabase_s3_and_youtube(self):
        deployment_doc = (ROOT / "docs/backend/deployment.md").read_text(
            encoding="utf-8"
        )
        env_example = (ROOT / ".env.example").read_text(encoding="utf-8")

        for section in (
            "## Supabase Setup",
            "## Render Setup",
            "## AWS S3 Setup",
            "## YouTube Data API Setup",
        ):
            self.assertIn(section, deployment_doc)

        for expected in (
            "Session Pooler",
            "health check path: /health",
            "python backend/scripts/run_migrations.py",
            "python backend/scripts/run_worker.py",
            "python backend/scripts/run_enrichment_worker.py",
            "s3:GetObject",
            "s3:HeadObject",
            "uploads/<LDiHKID>/<filename>.zip",
            "YouTube Data API v3",
            "quota",
            "AWS_SESSION_TOKEN",
            "long-lived IAM access keys",
            "Web, import worker, enrichment worker, migrations",
        ):
            self.assertIn(expected, deployment_doc)

        self.assertIn("long-lived IAM access keys", env_example)

    def test_migration_runner_smoke_applies_pending_migration(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            migrations_dir = Path(tmpdir)
            (migrations_dir / "001_smoke.sql").write_text(
                "CREATE TABLE smoke_events (id TEXT PRIMARY KEY);",
                encoding="utf-8",
            )
            connection = MigrationSmokeConnection()

            applied = run_migrations(connection, migrations_dir=migrations_dir)

        self.assertEqual([migration.name for migration in applied], ["001_smoke.sql"])
        self.assertIn(
            "CREATE TABLE smoke_events (id TEXT PRIMARY KEY);",
            connection.statements,
        )
        self.assertEqual(connection.applied_versions, ["001"])
        self.assertEqual(connection.rollbacks, 0)

    def test_api_smoke_health_import_queue_and_seeded_query(self):
        imports_repository = SmokeApiImportRepository()
        query_connection = SeededStructuredQueryConnection()
        app = create_app(
            imports_repository=imports_repository,
            query_connection_factory=lambda: query_connection,
        )
        client = app.test_client()

        with patch.dict("os.environ", {"S3_BUCKET": "smoke-bucket"}, clear=False):
            health_response = client.get("/health")
            create_response = client.post(
                "/api/imports",
                headers={"Authorization": "Bearer smoke_user"},
                json={
                    "s3_bucket": "smoke-bucket",
                    "s3_key": "uploads/smoke_user/takeout.zip",
                },
            )
            query_response = client.post(
                "/api/query",
                headers={"Authorization": "Bearer smoke_user"},
                json={
                    "dataset": "youtube_usage",
                    "metrics": ["event_count"],
                    "dimensions": ["event_type"],
                    "filters": {},
                    "options": {"limit": 10},
                },
            )

        self.assertEqual(health_response.status_code, 200)
        self.assertEqual(health_response.get_json(), {"status": "ok"})
        self.assertEqual(create_response.status_code, 201)
        self.assertEqual(
            create_response.get_json(),
            {
                "import_id": "smoke-import-1",
                "ldihk_id": "smoke_user",
                "status": "queued",
            },
        )
        self.assertEqual(
            imports_repository.created_s3_keys,
            ["uploads/smoke_user/takeout.zip"],
        )

        self.assertEqual(query_response.status_code, 200)
        self.assertEqual(
            query_response.get_json()["rows"],
            [
                {"event_type": "comment", "event_count": 1},
                {"event_type": "playlist_add", "event_count": 1},
            ],
        )
        self.assertTrue(query_connection.closed)

    def test_worker_smoke_processes_zip_through_comments_live_chat_and_playlists(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source_zip = Path(tmpdir) / "takeout.zip"
            write_zip(
                source_zip,
                {
                    "Takeout/YouTube and YouTube Music/comments/comments.csv": (
                        "Comment ID,Channel ID,Comment Create Timestamp,Price,"
                        "Parent Comment ID,Video ID,Comment Text\n"
                        "comment-1,UCprivate,2026-06-06T06:53:12Z,,"
                        'parent-1,comment-video,"private smoke comment"\n'
                    ).encode("utf-8"),
                    "Takeout/YouTube and YouTube Music/live chats/live chats.csv": (
                        "Live Chat ID,Channel ID,Live Chat Create Timestamp,Price,"
                        "Video ID,Live Chat Text\n"
                        'chat-1,UCprivate,2026-06-06T07:01:02Z,,'
                        'chat-video,"private smoke chat"\n'
                    ).encode("utf-8"),
                    "Takeout/YouTube and YouTube Music/playlists/Favorites.json": (
                        json.dumps(
                            [
                                {
                                    "videoUrl": "https://youtu.be/playlist-video",
                                    "title": "Private playlist title",
                                    "dateAdded": "2026-06-06T08:09:10Z",
                                }
                            ]
                        ).encode("utf-8")
                    ),
                    "Takeout/ignored.txt": b"ignore me",
                },
            )
            repository = SmokeWorkerRepository(
                ImportJob(
                    id="worker-import-1",
                    user_id="smoke_user",
                    s3_bucket="smoke-bucket",
                    s3_key="uploads/smoke_user/takeout.zip",
                )
            )
            s3_client = SmokeS3Client(source_zip)
            worker = S3ZipImportWorker(
                repository=repository,
                s3_client=s3_client,
            )

            result = worker.process_one()

        self.assertEqual(result.status, IMPORT_STATUS_COMPLETED)
        self.assertEqual(result.records_seen, 3)
        self.assertEqual(result.records_imported, 3)
        self.assertEqual(result.source_files, 3)
        self.assertEqual(repository.records_seen, 3)
        self.assertEqual(repository.records_imported, 3)
        self.assertEqual(repository.warnings_count, 0)
        self.assertEqual(
            {source_file.parser_name for source_file in repository.source_files},
            {"comments_live_chat", "likes_playlists"},
        )
        self.assertEqual(
            sorted(
                (event.event_type, event.video_id)
                for event in repository.usage_events
            ),
            [
                ("comment", "comment-video"),
                ("live_chat", "chat-video"),
                ("playlist_add", "playlist-video"),
            ],
        )
        self.assertEqual(
            s3_client.downloads,
            [("smoke-bucket", "uploads/smoke_user/takeout.zip")],
        )

    def test_hosted_smoke_script_fixture_contains_single_watch_record(self):
        fixture_bytes = hosted_smoke.build_smoke_fixture_zip()

        with ZipFile(io.BytesIO(fixture_bytes)) as zip_file:
            names = zip_file.namelist()
            payload = json.loads(zip_file.read(names[0]).decode("utf-8"))

        self.assertEqual(
            names,
            ["Takeout/YouTube and YouTube Music/history/watch-history.json"],
        )
        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]["header"], "YouTube")
        self.assertIn(hosted_smoke.SMOKE_VIDEO_ID, payload[0]["titleUrl"])

    def test_hosted_smoke_script_runs_full_fake_hosted_flow(self):
        http_client = FakeHostedSmokeHttpClient()
        s3_uploader = FakeHostedSmokeS3Uploader()
        commands: list[list[str]] = []
        messages: list[str] = []

        report = hosted_smoke.run_hosted_smoke(
            hosted_smoke.HostedSmokeConfig(
                base_url="https://backend.example.test",
                ldihk_id="smoke_user",
                wrong_ldihk_id="intruder",
                s3_bucket="smoke-bucket",
                upload_fixture=True,
                run_migrations=True,
                run_import_worker_once=True,
                run_enrichment_worker_once=True,
                poll_interval_seconds=0,
            ),
            http_client=http_client,
            s3_uploader=s3_uploader,
            command_runner=lambda command: fake_successful_command(command, commands),
            sleep_fn=lambda _seconds: None,
            emit=messages.append,
        )

        self.assertEqual(
            report.s3_key,
            "uploads/smoke_user/hosted-smoke-youtube-takeout.zip",
        )
        self.assertEqual(report.event_count_total, 1)
        self.assertEqual(report.estimated_watch_seconds, 213)
        self.assertEqual(report.duration_quality["events_with_api_duration"], 1)
        self.assertEqual(report.event_count_after_rerun, 1)
        self.assertEqual(
            report.support_commands,
            ["migrations", "import worker", "enrichment worker", "import worker"],
        )
        self.assertEqual(
            s3_uploader.uploads[0][:2],
            ("smoke-bucket", "uploads/smoke_user/hosted-smoke-youtube-takeout.zip"),
        )
        self.assertGreater(s3_uploader.uploads[0][2], 0)

        request_summary = [
            (request.method, request.path, request.bearer_token)
            for request in http_client.requests
        ]
        self.assertIn(("GET", "/health", None), request_summary)
        self.assertIn(("POST", "/api/imports", "smoke_user"), request_summary)
        self.assertIn(("GET", "/api/imports/import-1", "intruder"), request_summary)
        self.assertIn(("POST", "/api/query", "smoke_user"), request_summary)
        self.assertTrue(any("dedupe ok" in message for message in messages))
        self.assertIn("run_migrations.py", commands[0][1])
        self.assertIn("run_worker.py", commands[1][1])
        self.assertIn("run_enrichment_worker.py", commands[2][1])

    def test_hosted_smoke_script_fails_fast_when_health_check_fails(self):
        http_client = FakeHostedSmokeHttpClient(health_status=503)

        with self.assertRaisesRegex(
            hosted_smoke.SmokeFailure,
            r"GET /health returned HTTP 503",
        ):
            hosted_smoke.run_hosted_smoke(
                hosted_config(),
                http_client=http_client,
                sleep_fn=lambda _seconds: None,
                emit=None,
            )

    def test_hosted_smoke_script_reports_failed_import_status(self):
        http_client = FakeHostedSmokeHttpClient(failed_import_id="import-1")

        with self.assertRaisesRegex(
            hosted_smoke.SmokeFailure,
            r"Import import-1 failed: worker exploded",
        ):
            hosted_smoke.run_hosted_smoke(
                hosted_config(),
                http_client=http_client,
                sleep_fn=lambda _seconds: None,
                emit=None,
            )

    def test_hosted_smoke_script_requires_wrong_bearer_denial(self):
        http_client = FakeHostedSmokeHttpClient(wrong_bearer_status=200)

        with self.assertRaisesRegex(
            hosted_smoke.SmokeFailure,
            "Wrong bearer could read another import status",
        ):
            hosted_smoke.run_hosted_smoke(
                hosted_config(wrong_ldihk_id="intruder"),
                http_client=http_client,
                sleep_fn=lambda _seconds: None,
                emit=None,
            )

    def test_hosted_smoke_script_rejects_duplicate_analytics_after_rerun(self):
        http_client = FakeHostedSmokeHttpClient(rerun_event_count=2)

        with self.assertRaisesRegex(
            hosted_smoke.SmokeFailure,
            "Import rerun changed analytics event count",
        ):
            hosted_smoke.run_hosted_smoke(
                hosted_config(),
                http_client=http_client,
                sleep_fn=lambda _seconds: None,
                emit=None,
            )


class MigrationSmokeConnection:
    def __init__(self) -> None:
        self.statements: list[str] = []
        self.applied_versions: list[str] = []
        self.commits = 0
        self.rollbacks = 0

    def execute(self, sql: str, params=None):
        compact_sql = " ".join(sql.split())
        self.statements.append(compact_sql)
        if compact_sql.lower().startswith("select version from schema_migrations"):
            return SmokeCursor([(version,) for version in self.applied_versions])
        if compact_sql.lower().startswith("insert into schema_migrations"):
            self.applied_versions.append(params[0])
        return SmokeCursor([])

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


class SmokeCursor:
    def __init__(self, rows: list[tuple[object, ...]]) -> None:
        self._rows = rows
        self.description = []

    def fetchall(self):
        return self._rows


class SmokeApiImportRepository:
    def __init__(self) -> None:
        self.created_s3_keys: list[str] = []

    def create_import(
        self,
        *,
        user_external_id: str,
        s3_bucket: str,
        s3_key: str,
        s3_etag: str | None,
    ) -> ApiImportJob:
        self.created_s3_keys.append(s3_key)
        return ApiImportJob(
            import_id="smoke-import-1",
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

    def get_import(self, import_id: str) -> ApiImportJob | None:
        return None


class SeededStructuredQueryConnection:
    def __init__(self) -> None:
        self.closed = False

    def execute(self, sql: str, parameters: list[object]):
        if "FROM fact_rows" in sql:
            return QueryCursor(
                ["event_type", "event_count"],
                [("comment", 1), ("playlist_add", 1)],
            )
        return QueryCursor(
            [
                "events_counted",
                "events_with_api_duration",
                "events_with_user_average_estimate",
                "events_with_global_default_estimate",
                "videos_unavailable",
                "videos_capped",
            ],
            [(0, 0, 0, 0, 0, 0)],
        )

    def close(self) -> None:
        self.closed = True


class QueryCursor:
    def __init__(self, columns: list[str], rows: list[tuple[object, ...]]) -> None:
        self.description = [(column,) for column in columns]
        self._rows = rows

    def fetchall(self):
        return self._rows


@dataclass
class SmokeSourceFile:
    id: str
    parser_name: str


class SmokeWorkerRepository:
    def __init__(self, job: ImportJob) -> None:
        self.job = job
        self.status = "queued"
        self.source_files: list[SmokeSourceFile] = []
        self.usage_events: list[UsageEventWrite] = []
        self.subscriptions: list[SubscriptionWrite] = []
        self.import_warnings: list[ImportWarningWrite] = []
        self.enrichment_jobs: list[tuple[str, list[str]]] = []
        self.records_seen = 0
        self.records_imported = 0
        self.warnings_count = 0

    def claim_queued_import(self) -> ImportJob | None:
        if self.status != "queued":
            return None
        self.status = "running"
        return self.job

    @contextmanager
    def import_persistence_transaction(self):
        yield

    def record_source_file(
        self,
        *,
        import_id: str,
        path: str,
        sha256: str,
        parser_name: str,
        status: str,
        records_seen: int,
        records_imported: int,
        warnings_count: int,
    ) -> str:
        source_file_id = f"source-{len(self.source_files) + 1}"
        self.source_files.append(
            SmokeSourceFile(id=source_file_id, parser_name=parser_name)
        )
        return source_file_id

    def update_source_file_status(
        self,
        *,
        source_file_id: str,
        status: str,
        records_seen: int,
        records_imported: int,
        warnings_count: int,
    ) -> None:
        return None

    def insert_usage_event(self, event: UsageEventWrite) -> bool:
        self.usage_events.append(event)
        return True

    def upsert_subscription(self, subscription: SubscriptionWrite) -> bool:
        self.subscriptions.append(subscription)
        return True

    def insert_import_warning(self, warning: ImportWarningWrite) -> None:
        self.import_warnings.append(warning)

    def update_import_counts(
        self,
        *,
        import_id: str,
        records_seen: int,
        records_imported: int,
        warnings_count: int,
    ) -> None:
        self.records_seen = records_seen
        self.records_imported = records_imported
        self.warnings_count = warnings_count

    def mark_import_completed(
        self,
        *,
        import_id: str,
        records_seen: int,
        records_imported: int,
        warnings_count: int,
    ) -> None:
        self.status = "completed"
        self.records_seen = records_seen
        self.records_imported = records_imported
        self.warnings_count = warnings_count

    def enqueue_enrichment_for_import(self, *, import_id: str) -> int:
        video_ids = sorted(
            {
                event.video_id
                for event in self.usage_events
                if event.import_id == import_id
                and event.platform == "youtube"
                and event.product == "youtube"
                and event.event_type == "watch"
                and event.video_id is not None
            }
        )
        if video_ids:
            self.enrichment_jobs.append((import_id, video_ids))
        return len(video_ids)

    def mark_import_failed(
        self,
        *,
        import_id: str,
        error_message: str,
        records_seen: int,
        records_imported: int,
        warnings_count: int,
    ) -> None:
        self.status = "failed"


class SmokeS3Client:
    def __init__(self, zip_path: Path) -> None:
        self.zip_path = zip_path
        self.heads: list[tuple[str, str]] = []
        self.downloads: list[tuple[str, str]] = []

    def head_object(self, bucket: str, key: str) -> S3ObjectMetadata:
        self.heads.append((bucket, key))
        return S3ObjectMetadata(content_length=self.zip_path.stat().st_size)

    def download_zip(self, bucket: str, key: str, destination: Path) -> None:
        self.downloads.append((bucket, key))
        destination.write_bytes(self.zip_path.read_bytes())


def write_zip(zip_path: Path, files: dict[str, bytes]) -> None:
    with ZipFile(zip_path, "w") as zip_file:
        for path, content in files.items():
            zip_file.writestr(path, content)


@dataclass(frozen=True)
class HostedSmokeHttpRequest:
    method: str
    path: str
    json_body: object | None
    bearer_token: str | None


class FakeHostedSmokeHttpClient:
    def __init__(
        self,
        *,
        health_status: int = 200,
        failed_import_id: str | None = None,
        wrong_bearer_status: int = 404,
        rerun_event_count: int = 1,
    ) -> None:
        self.health_status = health_status
        self.failed_import_id = failed_import_id
        self.wrong_bearer_status = wrong_bearer_status
        self.rerun_event_count = rerun_event_count
        self.requests: list[HostedSmokeHttpRequest] = []
        self.created_imports: list[str] = []
        self.event_query_count = 0

    def request(
        self,
        method: str,
        path: str,
        *,
        json_body: object | None = None,
        bearer_token: str | None = None,
    ) -> hosted_smoke.HttpResponse:
        self.requests.append(
            HostedSmokeHttpRequest(
                method=method,
                path=path,
                json_body=json_body,
                bearer_token=bearer_token,
            )
        )
        if method == "GET" and path == "/health":
            return hosted_smoke.HttpResponse(
                self.health_status,
                {"status": "ok"} if self.health_status == 200 else {"status": "down"},
            )
        if method == "POST" and path == "/api/imports":
            import_id = f"import-{len(self.created_imports) + 1}"
            self.created_imports.append(import_id)
            return hosted_smoke.HttpResponse(
                201,
                {
                    "import_id": import_id,
                    "ldihk_id": bearer_token,
                    "status": "queued",
                },
            )
        if method == "GET" and path.startswith("/api/imports/"):
            import_id = path.rsplit("/", 1)[-1]
            if bearer_token != "smoke_user":
                return hosted_smoke.HttpResponse(
                    self.wrong_bearer_status,
                    {"error": "import_not_found"},
                )
            if import_id == self.failed_import_id:
                return hosted_smoke.HttpResponse(
                    200,
                    import_status_payload(
                        import_id,
                        status="failed",
                        records_seen=1,
                        records_imported=0,
                        error_message="worker exploded",
                    ),
                )
            imported = 0 if import_id == "import-2" else 1
            return hosted_smoke.HttpResponse(
                200,
                import_status_payload(
                    import_id,
                    status="completed",
                    records_seen=1,
                    records_imported=imported,
                ),
            )
        if method == "POST" and path == "/api/query":
            if not isinstance(json_body, dict):
                return hosted_smoke.HttpResponse(400, {"error": "invalid_request"})
            metrics = json_body.get("metrics")
            if metrics == ["event_count"]:
                self.event_query_count += 1
                count = (
                    self.rerun_event_count
                    if self.event_query_count >= 2
                    else 1
                )
                return hosted_smoke.HttpResponse(
                    200,
                    query_payload(
                        rows=[{"event_type": "watch", "event_count": count}],
                    ),
                )
            if metrics == ["estimated_watch_seconds"]:
                return hosted_smoke.HttpResponse(
                    200,
                    query_payload(
                        rows=[{"estimated_watch_seconds": 213}],
                        quality={
                            "events_counted": 1,
                            "events_with_api_duration": 1,
                            "events_with_user_average_estimate": 0,
                            "events_with_global_default_estimate": 0,
                            "videos_unavailable": 0,
                            "videos_capped": 0,
                        },
                    ),
                )
        raise AssertionError(f"unexpected request: {method} {path}")


class FakeHostedSmokeS3Uploader:
    def __init__(self) -> None:
        self.uploads: list[tuple[str, str, int]] = []

    def upload_zip(self, bucket: str, key: str, body: bytes) -> None:
        self.uploads.append((bucket, key, len(body)))


def hosted_config(**overrides) -> hosted_smoke.HostedSmokeConfig:
    values = {
        "base_url": "https://backend.example.test",
        "ldihk_id": "smoke_user",
        "wrong_ldihk_id": "wrong_user",
        "s3_bucket": "smoke-bucket",
        "poll_interval_seconds": 0,
    }
    values.update(overrides)
    return hosted_smoke.HostedSmokeConfig(**values)


def fake_successful_command(
    command: list[str] | tuple[str, ...],
    commands: list[list[str]],
) -> subprocess.CompletedProcess[str]:
    command_list = list(command)
    commands.append(command_list)
    return subprocess.CompletedProcess(command_list, 0, stdout="ok", stderr="")


def import_status_payload(
    import_id: str,
    *,
    status: str,
    records_seen: int,
    records_imported: int,
    error_message: str | None = None,
) -> dict[str, object]:
    return {
        "import_id": import_id,
        "ldihk_id": "smoke_user",
        "status": status,
        "records_seen": records_seen,
        "records_imported": records_imported,
        "warnings_count": 0,
        "error_message": error_message,
        "created_at": "2026-06-06T08:00:00+00:00",
        "started_at": "2026-06-06T08:00:01+00:00",
        "finished_at": "2026-06-06T08:00:02+00:00",
    }


def query_payload(
    *,
    rows: list[dict[str, object]],
    quality: dict[str, int] | None = None,
) -> dict[str, object]:
    return {
        "schema_version": "youtube_usage.structured_query.v1",
        "dataset": "youtube_usage",
        "ldihk_id": "smoke_user",
        "duration_strategy": {
            "kind": "api_user_average_global_default",
        },
        "query": {},
        "quality": quality
        or {
            "events_counted": 1,
            "events_with_api_duration": 0,
            "events_with_user_average_estimate": 0,
            "events_with_global_default_estimate": 1,
            "videos_unavailable": 1,
            "videos_capped": 0,
        },
        "rows": rows,
    }


if __name__ == "__main__":
    unittest.main()
