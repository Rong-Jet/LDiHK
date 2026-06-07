from __future__ import annotations

import json
import sqlite3
import unittest
from contextlib import closing
from datetime import datetime, timezone

from backend.enrichment.durations import (
    ENRICHMENT_JOB_STATUS_COMPLETED,
    ENRICHMENT_JOB_STATUS_FAILED,
    ENRICHMENT_JOB_STATUS_RUNNING,
    ENRICHMENT_JOB_TYPE_YOUTUBE_DURATIONS,
    ENRICHMENT_WORKER_STATUS_COMPLETED,
    ENRICHMENT_WORKER_STATUS_FAILED,
    ENRICHMENT_WORKER_STATUS_IDLE,
    PostgresEnrichmentRepository,
    YoutubeDurationEnrichmentWorker,
)
from backend.ingestion.worker import PostgresImportRepository


class FakeYoutubeClient:
    def __init__(self, videos=None, error=None):
        self.videos = videos or {}
        self.error = error
        self.requests = []

    def list_videos(self, video_ids):
        self.requests.append(list(video_ids))
        if self.error is not None:
            raise self.error
        return [
            self.videos[video_id]
            for video_id in video_ids
            if video_id in self.videos
        ]


class EnrichmentWorkerTests(unittest.TestCase):
    def test_claim_next_job_marks_due_job_running(self):
        with closing(_connection()) as connection:
            _insert_enrichment_job(connection, "job-1", ["video-1"])
            repository = PostgresEnrichmentRepository(connection)

            job = repository.claim_next_job()
            row = connection.execute(
                """
                SELECT status, started_at, finished_at, error_message
                FROM enrichment_jobs
                WHERE id = ?
                """,
                ("job-1",),
            ).fetchone()

        self.assertEqual(job.id, "job-1")
        self.assertEqual(job.payload_json["video_ids"], ["video-1"])
        self.assertEqual(row[0], ENRICHMENT_JOB_STATUS_RUNNING)
        self.assertIsNotNone(row[1])
        self.assertIsNone(row[2])
        self.assertIsNone(row[3])

    def test_claim_next_job_uses_row_locking_for_postgres_connections(self):
        connection = CapturingPostgresLikeConnection()
        repository = PostgresEnrichmentRepository(connection)

        job = repository.claim_next_job()

        self.assertIsNone(job)
        self.assertIn("FOR UPDATE SKIP LOCKED", connection.statements[0])
        self.assertEqual(connection.commits, 1)

    def test_process_one_enriches_queued_job_and_completes(self):
        with closing(_connection()) as connection:
            _insert_enrichment_job(connection, "job-1", ["video-1", "video-2"])
            client = FakeYoutubeClient(
                {
                    "video-1": _youtube_video("video-1", "PT2M"),
                    "video-2": _youtube_video("video-2", "PT3M"),
                }
            )
            worker = YoutubeDurationEnrichmentWorker(
                repository=PostgresEnrichmentRepository(connection),
                client=client,
            )

            result = worker.process_one()
            job_row = connection.execute(
                """
                SELECT status, attempts, error_message
                FROM enrichment_jobs
                WHERE id = ?
                """,
                ("job-1",),
            ).fetchone()
            video_rows = connection.execute(
                """
                SELECT video_id, duration_seconds, availability_status
                FROM youtube_videos
                ORDER BY video_id
                """
            ).fetchall()

        self.assertEqual(result.status, ENRICHMENT_WORKER_STATUS_COMPLETED)
        self.assertEqual(client.requests, [["video-1", "video-2"]])
        self.assertEqual(result.summary.requested_video_count, 2)
        self.assertEqual(job_row, (ENRICHMENT_JOB_STATUS_COMPLETED, 0, None))
        self.assertEqual(
            video_rows,
            [
                ("video-1", 120, "available"),
                ("video-2", 180, "available"),
            ],
        )

    def test_api_error_marks_job_failed_with_backoff(self):
        with closing(_connection()) as connection:
            _insert_enrichment_job(connection, "job-1", ["video-1"])
            now = datetime(2026, 6, 6, 12, 0, tzinfo=timezone.utc)
            worker = YoutubeDurationEnrichmentWorker(
                repository=PostgresEnrichmentRepository(connection),
                client=FakeYoutubeClient(error=RuntimeError("quota exceeded")),
                retry_base_seconds=10,
                now_fn=lambda: now,
            )

            result = worker.process_one()
            job_row = connection.execute(
                """
                SELECT status, attempts, run_after, error_message
                FROM enrichment_jobs
                WHERE id = ?
                """,
                ("job-1",),
            ).fetchone()
            video_row = connection.execute(
                """
                SELECT availability_status, attempt_count, last_error
                FROM youtube_videos
                WHERE video_id = ?
                """,
                ("video-1",),
            ).fetchone()

        self.assertEqual(result.status, ENRICHMENT_WORKER_STATUS_FAILED)
        self.assertEqual(result.error_message, "RuntimeError: quota exceeded")
        self.assertEqual(
            job_row,
            (
                ENRICHMENT_JOB_STATUS_FAILED,
                1,
                "2026-06-06T12:00:10+00:00",
                "RuntimeError: quota exceeded",
            ),
        )
        self.assertEqual(
            video_row,
            ("api_error", 1, "RuntimeError: quota exceeded"),
        )

    def test_repair_mode_enriches_missing_watch_video_ids_without_job(self):
        with closing(_connection()) as connection:
            _insert_usage_event(connection, "event-1", "watch", "video-1")
            _insert_usage_event(connection, "event-2", "comment", "comment-video")
            _insert_usage_event(connection, "event-3", "watch", None)
            client = FakeYoutubeClient({"video-1": _youtube_video("video-1", "PT4M")})
            worker = YoutubeDurationEnrichmentWorker(
                repository=PostgresEnrichmentRepository(connection),
                client=client,
            )

            result = worker.repair_once()
            job_count = connection.execute(
                "SELECT COUNT(*) FROM enrichment_jobs"
            ).fetchone()[0]
            video_row = connection.execute(
                """
                SELECT video_id, duration_seconds, availability_status
                FROM youtube_videos
                """
            ).fetchone()

        self.assertEqual(result.status, ENRICHMENT_WORKER_STATUS_COMPLETED)
        self.assertEqual(client.requests, [["video-1"]])
        self.assertEqual(job_count, 0)
        self.assertEqual(video_row, ("video-1", 240, "available"))

    def test_repair_mode_reports_idle_when_no_missing_watch_video_ids(self):
        with closing(_connection()) as connection:
            worker = YoutubeDurationEnrichmentWorker(
                repository=PostgresEnrichmentRepository(connection),
                client=FakeYoutubeClient(),
            )

            result = worker.repair_once()

        self.assertEqual(result.status, ENRICHMENT_WORKER_STATUS_IDLE)
        self.assertEqual(result.summary.requested_video_count, 0)

    def test_import_repository_enqueues_distinct_watch_video_ids(self):
        with closing(_connection()) as connection:
            _insert_usage_event(connection, "event-1", "watch", "video-1")
            _insert_usage_event(connection, "event-2", "watch", "video-1")
            _insert_usage_event(connection, "event-3", "watch", "video-2")
            _insert_usage_event(connection, "event-4", "comment", "comment-video")
            repository = PostgresImportRepository(connection)

            queued_count = repository.enqueue_enrichment_for_import(
                import_id="import-1"
            )
            row = connection.execute(
                """
                SELECT job_type, status, payload_json
                FROM enrichment_jobs
                """
            ).fetchone()

        self.assertEqual(queued_count, 2)
        self.assertEqual(row[0], ENRICHMENT_JOB_TYPE_YOUTUBE_DURATIONS)
        self.assertEqual(row[1], "queued")
        self.assertEqual(
            json.loads(row[2]),
            {"import_id": "import-1", "video_ids": ["video-1", "video-2"]},
        )


class CapturingPostgresLikeConnection:
    def __init__(self) -> None:
        self.statements: list[str] = []
        self.commits = 0
        self.rollbacks = 0

    def execute(self, sql: str, params=None):
        self.statements.append(sql)
        return Cursor([])

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


class Cursor:
    def __init__(self, rows):
        self.rows = rows

    def fetchone(self):
        if not self.rows:
            return None
        return self.rows[0]

    def fetchall(self):
        return self.rows


def _connection():
    connection = sqlite3.connect(":memory:")
    connection.executescript(
        """
        CREATE TABLE usage_events (
            id TEXT PRIMARY KEY,
            import_id TEXT NOT NULL,
            platform TEXT NOT NULL,
            product TEXT NOT NULL,
            event_type TEXT NOT NULL,
            video_id TEXT
        );

        CREATE TABLE youtube_videos (
            video_id TEXT PRIMARY KEY,
            channel_id TEXT,
            duration_seconds INTEGER,
            duration_source TEXT,
            availability_status TEXT NOT NULL,
            max_duration_applied BOOLEAN NOT NULL DEFAULT false,
            fetched_at TEXT,
            attempt_count INTEGER NOT NULL DEFAULT 0,
            last_error TEXT
        );

        CREATE TABLE enrichment_jobs (
            id TEXT PRIMARY KEY,
            job_type TEXT NOT NULL,
            status TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0,
            run_after TEXT NOT NULL DEFAULT '2000-01-01T00:00:00+00:00',
            started_at TEXT,
            finished_at TEXT,
            error_message TEXT,
            created_at TEXT NOT NULL DEFAULT '2000-01-01T00:00:00+00:00'
        );
        """
    )
    return connection


def _insert_enrichment_job(connection, job_id: str, video_ids: list[str]) -> None:
    connection.execute(
        """
        INSERT INTO enrichment_jobs (
            id,
            job_type,
            status,
            payload_json
        )
        VALUES (?, ?, ?, ?)
        """,
        (
            job_id,
            ENRICHMENT_JOB_TYPE_YOUTUBE_DURATIONS,
            "queued",
            json.dumps({"video_ids": video_ids}),
        ),
    )


def _insert_usage_event(
    connection,
    event_id: str,
    event_type: str,
    video_id: str | None,
) -> None:
    connection.execute(
        """
        INSERT INTO usage_events (
            id,
            import_id,
            platform,
            product,
            event_type,
            video_id
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (event_id, "import-1", "youtube", "youtube", event_type, video_id),
    )


def _youtube_video(video_id: str, duration: str):
    return {
        "id": video_id,
        "contentDetails": {"duration": duration},
        "status": {"privacyStatus": "public"},
    }


if __name__ == "__main__":
    unittest.main()
