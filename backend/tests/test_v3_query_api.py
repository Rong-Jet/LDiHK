import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from backend.app import create_app
from backend.youtube_sql import create_schema


class YoutubeUsageV3QueryApiTests(unittest.TestCase):
    def test_query_returns_duration_aware_rows_and_quality_without_private_ids(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            database_path = Path(tmpdir) / "youtube_usage.v3.sqlite"
            with closing(sqlite3.connect(database_path)) as connection:
                create_schema(connection)
                connection.execute(
                    "INSERT INTO users (person_id, created_at) VALUES (?, ?)",
                    ("local_user", "2026-06-06T08:00:00+02:00"),
                )
                for event_id, watched_at, video_id in [
                    ("event-short", "2026-06-06T08:00:00+02:00", "short"),
                    ("event-missing", "2026-06-06T08:10:00+02:00", "unavailable123"),
                    ("event-long", "2026-06-06T09:00:00+02:00", "long"),
                ]:
                    connection.execute(
                        """
                        INSERT INTO watch_events (
                            event_id,
                            person_id,
                            platform,
                            product,
                            event_type,
                            watched_at,
                            video_id,
                            source_schema_version,
                            created_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            event_id,
                            "local_user",
                            "youtube",
                            "youtube",
                            "watched",
                            watched_at,
                            video_id,
                            "youtube_usage.v1",
                            watched_at,
                        ),
                    )
                connection.commit()
                for row in [
                    ("short", 120, "PT2M", "available", 0),
                    ("unavailable123", None, None, "deleted_or_unavailable", 0),
                    ("long", 5400, "P1DT2H", "available", 1),
                ]:
                    connection.execute(
                        """
                        INSERT INTO video_metadata (
                            video_id,
                            duration_seconds,
                            duration_iso8601,
                            duration_source,
                            availability_status,
                            max_duration_applied,
                            fetched_at,
                            error_code
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            row[0],
                            row[1],
                            row[2],
                            "youtube_data_api",
                            row[3],
                            row[4],
                            "2026-06-06T10:00:00+02:00",
                            None,
                        ),
                    )
                connection.commit()

            app = create_app(
                processed_path=Path(tmpdir) / "unused-v1.json",
                sqlite_path=database_path,
            )

            response = app.test_client().post(
                "/api/v3/query",
                json={
                    "dataset": "youtube_usage",
                    "person_id": "local_user",
                    "metrics": [
                        "event_count",
                        "watch_seconds",
                        "events_missing_duration",
                    ],
                    "dimensions": ["date", "hour"],
                    "filters": {
                        "start_date": "2026-06-06",
                        "end_date": "2026-06-06",
                    },
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["schema_version"], "youtube_usage.query.v3")
        self.assertEqual(
            payload["duration_strategy"],
            {
                "kind": "youtube_data_api",
                "max_duration_seconds": 5400,
                "unknown_duration_policy": "count_event_exclude_duration",
            },
        )
        self.assertEqual(
            payload["quality"],
            {
                "events_counted": 3,
                "events_with_duration": 2,
                "events_missing_duration": 1,
                "videos_capped": 1,
            },
        )
        self.assertEqual(
            payload["rows"],
            [
                {
                    "date": "2026-06-06",
                    "hour": 8,
                    "event_count": 2,
                    "watch_seconds": 120,
                    "events_missing_duration": 1,
                },
                {
                    "date": "2026-06-06",
                    "hour": 9,
                    "event_count": 1,
                    "watch_seconds": 5400,
                    "events_missing_duration": 0,
                },
            ],
        )
        serialized = json.dumps(payload)
        self.assertNotIn("short", serialized)
        self.assertNotIn("unavailable123", serialized)
        self.assertNotIn("long", serialized)
        self.assertNotIn("video_id", serialized)

    def test_query_rejects_raw_sql_and_unknown_metrics(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            database_path = Path(tmpdir) / "youtube_usage.v3.sqlite"
            with closing(sqlite3.connect(database_path)) as connection:
                create_schema(connection)
                connection.commit()
            app = create_app(
                processed_path=Path(tmpdir) / "unused-v1.json",
                sqlite_path=database_path,
            )
            client = app.test_client()

            raw_sql_response = client.post(
                "/api/v3/query",
                json={"sql": "SELECT video_id FROM watch_events"},
            )
            unknown_metric_response = client.post(
                "/api/v3/query",
                json={
                    "dataset": "youtube_usage",
                    "person_id": "local_user",
                    "metrics": ["raw_video_ids"],
                    "dimensions": ["date"],
                    "filters": {},
                },
            )

        self.assertEqual(raw_sql_response.status_code, 400)
        self.assertEqual(raw_sql_response.get_json(), {"error": "raw_sql_not_allowed"})
        self.assertEqual(unknown_metric_response.status_code, 400)
        self.assertEqual(unknown_metric_response.get_json(), {"error": "invalid_metric"})

    def test_query_zero_fills_hourly_buckets_and_counts_sessions_by_start_bucket(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            database_path = Path(tmpdir) / "youtube_usage.v3.sqlite"
            with closing(sqlite3.connect(database_path)) as connection:
                create_schema(connection)
                connection.execute(
                    "INSERT INTO users (person_id, created_at) VALUES (?, ?)",
                    ("local_user", "2026-06-06T08:00:00+02:00"),
                )
                for event_id, watched_at, video_id in [
                    ("event-one", "2026-06-06T08:00:00+02:00", "one"),
                    ("event-two", "2026-06-06T08:20:00+02:00", "two"),
                    ("event-three", "2026-06-06T10:00:00+02:00", "three"),
                ]:
                    connection.execute(
                        """
                        INSERT INTO watch_events (
                            event_id,
                            person_id,
                            platform,
                            product,
                            event_type,
                            watched_at,
                            video_id,
                            source_schema_version,
                            created_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            event_id,
                            "local_user",
                            "youtube",
                            "youtube",
                            "watched",
                            watched_at,
                            video_id,
                            "youtube_usage.v1",
                            watched_at,
                        ),
                    )
                    connection.execute(
                        """
                        INSERT INTO video_metadata (
                            video_id,
                            duration_seconds,
                            duration_iso8601,
                            duration_source,
                            availability_status,
                            max_duration_applied,
                            fetched_at,
                            error_code
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            video_id,
                            600,
                            "PT10M",
                            "youtube_data_api",
                            "available",
                            0,
                            watched_at,
                            None,
                        ),
                    )
                connection.commit()

            app = create_app(
                processed_path=Path(tmpdir) / "unused-v1.json",
                sqlite_path=database_path,
            )

            response = app.test_client().post(
                "/api/v3/query",
                json={
                    "dataset": "youtube_usage",
                    "person_id": "local_user",
                    "metrics": ["event_count", "watch_seconds", "session_count"],
                    "dimensions": ["date", "hour"],
                    "filters": {
                        "start_date": "2026-06-06",
                        "end_date": "2026-06-06",
                    },
                    "options": {"include_zero_buckets": True},
                },
            )

        self.assertEqual(response.status_code, 200)
        rows = response.get_json()["rows"]
        self.assertEqual(len(rows), 24)
        self.assertEqual(
            rows[8],
            {
                "date": "2026-06-06",
                "hour": 8,
                "event_count": 2,
                "watch_seconds": 1200,
                "session_count": 1,
            },
        )
        self.assertEqual(
            rows[9],
            {
                "date": "2026-06-06",
                "hour": 9,
                "event_count": 0,
                "watch_seconds": 0,
                "session_count": 0,
            },
        )
        self.assertEqual(
            rows[10],
            {
                "date": "2026-06-06",
                "hour": 10,
                "event_count": 1,
                "watch_seconds": 600,
                "session_count": 1,
            },
        )
