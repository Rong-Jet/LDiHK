"""End-to-end checks against a real Postgres (set TEST_DATABASE_URL).

The other tests use fake connections, so none of the SQL runs there. These
tests create a throwaway database next to TEST_DATABASE_URL (the role needs
CREATEDB), run all migrations, drive the API, the import worker with the real
parsers, and the enrichment worker, then drop the database again.
"""

from __future__ import annotations

from contextlib import closing
from datetime import datetime, timedelta, timezone
import gzip
import io
import json
import os
import unittest
import uuid
import zipfile
from unittest import mock
from urllib.parse import urlsplit, urlunsplit

from backend.ingestion.s3 import S3ObjectMetadata

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "").strip()
BUCKET = "ldihk-uploads"


def _watch_records(count: int, *, newest_hours_ago: int = 2, prefix: str = "v") -> list[dict]:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    records = []
    for index in range(count):
        when = now - timedelta(hours=newest_hours_ago) - timedelta(minutes=37 * index)
        records.append(
            {
                "header": "YouTube",
                "title": f"Watched Test video {index}",
                "titleUrl": f"https://www.youtube.com/watch?v={prefix}{index:08d}",
                "subtitles": [{"name": f"Channel {index % 7}", "url": f"https://www.youtube.com/channel/UC{index % 7:06d}"}],
                "time": when.isoformat().replace("+00:00", "Z"),
                "products": ["YouTube"],
            }
        )
    return records


def _takeout_zip(records: list[dict]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "Takeout/YouTube and YouTube Music/history/watch-history.json",
            json.dumps(records),
        )
    return buffer.getvalue()


class _BytesS3:
    def __init__(self, payloads: dict[str, bytes]):
        self.payloads = payloads

    def head_object(self, bucket, key):
        return S3ObjectMetadata(content_length=len(self.payloads[key]))

    def download_zip(self, bucket, key, destination):
        destination.write_bytes(self.payloads[key])


class _FakeYoutube:
    def __init__(self):
        self.requests: list[list[str]] = []

    def list_videos(self, ids):
        self.requests.append(list(ids))
        return [
            {"id": video_id, "contentDetails": {"duration": "PT4M"}, "status": {"privacyStatus": "public"}}
            for video_id in ids
        ]


@unittest.skipUnless(TEST_DATABASE_URL, "set TEST_DATABASE_URL to run Postgres integration tests")
class PostgresIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import psycopg

        from backend import db

        cls.database_name = f"ldihk_it_{uuid.uuid4().hex[:10]}"
        with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as admin:
            admin.execute(f'CREATE DATABASE "{cls.database_name}"')
        cls.database_url = urlunsplit(urlsplit(TEST_DATABASE_URL)._replace(path=f"/{cls.database_name}"))
        cls.env = mock.patch.dict(
            os.environ,
            {
                "DATABASE_URL": cls.database_url,
                "S3_BUCKET": BUCKET,
                "RATE_LIMITS_ENABLED": "false",
                "RUN_WORKERS_IN_PROCESS": "false",
            },
            clear=False,
        )
        cls.env.start()
        db.run_migrations()

        from backend.app import create_app

        cls.client = create_app(start_workers=False, enable_local_file_routes=False).test_client()
        cls.payloads: dict[str, bytes] = {}

    @classmethod
    def tearDownClass(cls):
        import psycopg

        cls.env.stop()
        with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as admin:
            admin.execute(f'DROP DATABASE IF EXISTS "{cls.database_name}" WITH (FORCE)')

    # -- helpers ------------------------------------------------------------

    def _connect(self):
        from backend import db

        return db.connect()

    def _new_id(self) -> str:
        return f"ldihk-it-{uuid.uuid4().hex[:16]}"

    def _upload_and_import(self, ldihk_id: str, name: str, records: list[dict]) -> dict:
        from backend.ingestion.worker import PostgresImportRepository, S3ZipImportWorker

        key = f"uploads/{ldihk_id}/{name}"
        self.payloads[key] = _takeout_zip(records)  # the worker downloads this exact key
        response = self.client.post(
            "/api/imports",
            headers={"Authorization": f"Bearer {ldihk_id}"},
            json={"s3_bucket": BUCKET, "s3_key": key},
        )
        self.assertEqual(response.status_code, 201, response.get_json())
        with closing(self._connect()) as connection:
            result = S3ZipImportWorker(
                repository=PostgresImportRepository(connection),
                s3_client=_BytesS3(self.payloads),
            ).process_one()
        self.assertEqual(result.status, "completed", result)
        return response.get_json()

    def _count(self, sql: str, *params) -> int:
        with closing(self._connect()) as connection:
            return connection.execute(sql, params).fetchone()[0]

    # -- tests --------------------------------------------------------------

    def test_import_dedupe_queries_and_population(self):
        ldihk_id = self._new_id()
        auth = {"Authorization": f"Bearer {ldihk_id}"}
        self.assertEqual(self.client.get("/api/me", headers=auth).status_code, 404)

        records = _watch_records(60, prefix=ldihk_id[-6:])
        self._upload_and_import(ldihk_id, "Takeout.ZIP", records[10:])
        self._upload_and_import(ldihk_id, "newer.zip", records)  # newer export: 10 more

        watches = self._count(
            "SELECT count(*) FROM usage_events ue JOIN users u ON u.id = ue.user_id "
            "WHERE u.external_id = %s AND ue.event_type = 'watch'",
            ldihk_id,
        )
        self.assertEqual(watches, 60, "re-uploading a newer export must not duplicate events")

        me = self.client.get("/api/me?timezone=Asia/Hong_Kong", headers=auth).get_json()
        self.assertEqual(me["datasets"]["youtube"]["event_count"], 60)
        self.assertEqual(me["timezone"], "Asia/Hong_Kong")

        today = datetime.now(timezone.utc).date()
        filters = {"start_date": (today - timedelta(days=6)).isoformat(), "end_date": today.isoformat()}
        for zone in ("UTC", "Europe/Berlin", "America/Los_Angeles"):
            response = self.client.post(
                "/api/query",
                headers={**auth, "Accept-Encoding": "gzip"},
                json={
                    "dataset": "youtube_usage",
                    "metrics": ["event_count", "estimated_watch_seconds"],
                    "dimensions": ["date", "hour"],
                    "filters": filters,
                    "options": {"timezone": zone, "include_zero_buckets": True, "limit": 10000},
                },
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers.get("Content-Encoding"), "gzip")
            rows = json.loads(gzip.decompress(response.data))["rows"]
            self.assertEqual(len(rows), 7 * 24, zone)
            self.assertGreater(sum(row["event_count"] for row in rows), 0, zone)

        population = self.client.post(
            "/api/population",
            headers=auth,
            json={"platforms": ["youtube"], "startDate": filters["start_date"], "endDate": filters["end_date"], "includeSynthetic": True},
        )
        self.assertEqual(population.status_code, 200)
        self.assertIn("ready", population.get_json())

    def test_stale_imports_are_reclaimed_and_exhausted_ones_fail(self):
        from backend.ingestion.worker import PostgresImportRepository

        ldihk_id = self._new_id()
        self._upload_and_import(ldihk_id, "base.zip", _watch_records(3, prefix=ldihk_id[-6:]))
        stale_id, dead_id = uuid.uuid4(), uuid.uuid4()
        with closing(self._connect()) as connection:
            user_id = connection.execute("SELECT id FROM users WHERE external_id = %s", (ldihk_id,)).fetchone()[0]
            for job_id, attempts, age_minutes in ((stale_id, 0, 180), (dead_id, 3, 170)):
                connection.execute(
                    """
                    INSERT INTO imports (id, user_id, s3_bucket, s3_key, status, attempts,
                                         started_at, heartbeat_at, created_at)
                    VALUES (%s, %s, %s, %s, 'running', %s,
                            now() - interval '2 hours', now() - interval '2 hours',
                            now() - make_interval(mins => %s))
                    """,
                    (job_id, user_id, BUCKET, f"uploads/{ldihk_id}/{job_id}.zip", attempts, age_minutes),
                )
            connection.commit()
            repository = PostgresImportRepository(connection, stale_after_seconds=600, max_attempts=3)
            claimed = repository.claim_queued_import()
            self.assertEqual(claimed.id, str(stale_id))
            self.assertIsNone(repository.claim_queued_import())
            dead = connection.execute("SELECT status, error_message FROM imports WHERE id = %s", (dead_id,)).fetchone()
            stale = connection.execute("SELECT attempts FROM imports WHERE id = %s", (stale_id,)).fetchone()
            connection.execute("UPDATE imports SET status = 'failed' WHERE id = %s", (stale_id,))
            connection.commit()
        self.assertEqual(dead[0], "failed")
        self.assertTrue(dead[1].startswith("import_abandoned"))
        self.assertEqual(stale[0], 1)

    def test_enrichment_reclaims_stale_jobs_and_skips_enriched_videos(self):
        from backend.enrichment.durations import (
            PostgresEnrichmentRepository,
            YoutubeDurationEnrichmentWorker,
        )

        ldihk_id = self._new_id()
        records = _watch_records(20, prefix=ldihk_id[-6:])
        self._upload_and_import(ldihk_id, "a.zip", records[5:])
        self._upload_and_import(ldihk_id, "b.zip", records)
        with closing(self._connect()) as connection:
            connection.execute(
                """
                UPDATE enrichment_jobs
                SET status = 'running', started_at = now() - interval '1 hour', heartbeat_at = NULL
                WHERE id = (
                    SELECT id FROM enrichment_jobs
                    WHERE payload_json -> 'video_ids' ? %s
                    ORDER BY created_at LIMIT 1
                )
                """,
                (f"{ldihk_id[-6:]}{5:08d}",),
            )
            connection.commit()
            youtube = _FakeYoutube()
            worker = YoutubeDurationEnrichmentWorker(
                repository=PostgresEnrichmentRepository(connection, stale_after_seconds=60),
                client=youtube,
            )
            while worker.process_one().status != "idle":
                pass
        requested = [video_id for batch in youtube.requests for video_id in batch]
        self.assertEqual(len(requested), len(set(requested)), "no video may be looked up twice")
        mine = [video_id for video_id in requested if video_id.startswith(ldihk_id[-6:])]
        self.assertEqual(len(mine), 20)
        self.assertEqual(
            self._count("SELECT count(*) FROM enrichment_jobs WHERE status NOT IN ('completed', 'abandoned')"),
            0,
        )

    def test_instagram_views_count_as_watch_time(self):
        ldihk_id = self._new_id()
        self._upload_and_import(ldihk_id, "base.zip", _watch_records(1, prefix=ldihk_id[-6:]))
        now = datetime.now(timezone.utc)
        with closing(self._connect()) as connection:
            user_id, import_id = connection.execute(
                "SELECT u.id, i.id FROM users u JOIN imports i ON i.user_id = u.id WHERE u.external_id = %s",
                (ldihk_id,),
            ).fetchone()
            for index, event_type in enumerate(["video_watch", "story_view", "post_view", "liked_post"]):
                connection.execute(
                    """
                    INSERT INTO usage_events (id, user_id, import_id, platform, product, event_type,
                                              occurred_at, event_fingerprint, duration_seconds)
                    VALUES (%s, %s, %s, 'instagram', 'instagram', %s, %s, decode(%s, 'hex'), 20)
                    """,
                    (uuid.uuid4(), user_id, import_id, event_type, now - timedelta(hours=1, minutes=10 * index), uuid.uuid4().hex * 2),
                )
            connection.commit()
        response = self.client.post(
            "/api/query",
            headers={"Authorization": f"Bearer {ldihk_id}"},
            json={
                "dataset": "instagram_usage",
                "metrics": ["estimated_watch_seconds"],
                "dimensions": [],
                "filters": {"start_date": (now - timedelta(days=1)).date().isoformat(), "end_date": now.date().isoformat()},
            },
        )
        self.assertEqual(response.get_json()["rows"][0]["estimated_watch_seconds"], 60)

    def test_population_needs_five_others_and_maps_synthetic_baseline(self):
        from backend.population_api import MIN_POPULATION_SIZE
        from backend.scripts.seed_synthetic_usage import seed_synthetic_usage

        # Real users ~500 days back: nobody from the other tests overlaps, and
        # the synthetic seed (the last 14 days) lies outside the range.
        requester, *others = [self._new_id() for _ in range(3)]
        for ldihk_id in (requester, *others):
            records = _watch_records(5, newest_hours_ago=500 * 24, prefix=ldihk_id[-6:])
            self._upload_and_import(ldihk_id, "old.zip", records)
        watch_day = (datetime.now(timezone.utc) - timedelta(hours=500 * 24)).date()
        request = {
            "platforms": ["youtube"],
            "startDate": (watch_day - timedelta(days=3)).isoformat(),
            "endDate": (watch_day + timedelta(days=3)).isoformat(),
            "customPercentile": 90,
        }
        auth = {"Authorization": f"Bearer {requester}"}

        real_only = self.client.post("/api/population", headers=auth, json={**request, "includeSynthetic": False})
        self.assertEqual(real_only.status_code, 200)
        self.assertEqual(
            {key: real_only.get_json()[key] for key in ("ready", "reason", "populationSize")},
            {"ready": False, "reason": "insufficient_population", "populationSize": len(others)},
        )

        seed_synthetic_usage(
            total_profiles=12,
            total_days=14,
            seed_run_name=f"it-{uuid.uuid4().hex[:8]}",
            random_seed=7,
            run_schema_migrations=False,
        )
        response = self.client.post("/api/population", headers=auth, json={**request, "includeSynthetic": True})
        payload = response.get_json()
        self.assertTrue(payload["ready"], payload)
        self.assertGreaterEqual(payload["populationSize"], MIN_POPULATION_SIZE)
        baseline_end = datetime.fromisoformat(payload["syntheticBaseline"]["endDate"]).date()
        self.assertLessEqual(abs((baseline_end - datetime.now(timezone.utc).date()).days), 1)
        self.assertEqual(len(payload["deciles"]), 7)
        self.assertTrue(all(day["top10"] > 0 for day in payload["deciles"]), payload["deciles"])
        self.assertGreater(payload["userDailyAverageHours"], 0)

    def test_delete_my_data_erases_only_that_user(self):
        keep_id, delete_id = self._new_id(), self._new_id()
        self._upload_and_import(keep_id, "keep.zip", _watch_records(4, prefix=keep_id[-6:]))
        self._upload_and_import(delete_id, "gone.zip", _watch_records(6, prefix=delete_id[-6:]))
        auth = {"Authorization": f"Bearer {delete_id}"}

        mismatch = self.client.delete("/api/me", headers=auth, json={"confirm": keep_id})
        response = self.client.delete("/api/me", headers=auth, json={"confirm": delete_id})

        self.assertEqual(mismatch.status_code, 400)
        self.assertEqual(response.status_code, 200, response.get_json())
        body = response.get_json()
        self.assertEqual((body["events_deleted"], body["imports_deleted"]), (6, 1))
        self.assertEqual(self.client.get("/api/me", headers=auth).status_code, 404)
        self.assertEqual(self._count("SELECT count(*) FROM users WHERE external_id = %s", delete_id), 0)
        self.assertEqual(
            self._count(
                "SELECT count(*) FROM imports i JOIN users u ON u.id = i.user_id WHERE u.external_id = %s",
                keep_id,
            ),
            1,
        )
        keep = self.client.get("/api/me", headers={"Authorization": f"Bearer {keep_id}"}).get_json()
        self.assertEqual(keep["datasets"]["youtube"]["event_count"], 4)


if __name__ == "__main__":
    unittest.main()
