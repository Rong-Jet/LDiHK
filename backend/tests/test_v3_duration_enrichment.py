import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from backend.youtube_sql import create_schema, enrich_youtube_durations


class FakeYoutubeClient:
    def __init__(self, videos):
        self.videos = videos
        self.requests = []

    def list_videos(self, video_ids):
        self.requests.append(list(video_ids))
        return [self.videos[video_id] for video_id in video_ids if video_id in self.videos]


class YoutubeDurationEnrichmentTests(unittest.TestCase):
    def test_enrichment_loads_youtube_api_key_from_dotenv_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            database_path = tmp / "youtube_usage.v3.sqlite"
            env_path = tmp / ".env"
            env_path.write_text("YOUTUBE_API_KEY=from-dotenv\n", encoding="utf-8")
            with closing(sqlite3.connect(database_path)) as connection:
                create_schema(connection)
                connection.commit()

            with patch.dict("os.environ", {}, clear=True), patch(
                "backend.youtube_sql.YouTubeDataApiClient"
            ) as client_class:
                client_class.return_value.list_videos.return_value = []

                summary = enrich_youtube_durations(
                    database_path=database_path,
                    env_path=env_path,
                )

        client_class.assert_called_once_with("from-dotenv")
        self.assertEqual(summary.requested_video_count, 0)

    def test_enriches_uncached_video_metadata_and_tracks_missing_and_capped_videos(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            database_path = Path(tmpdir) / "youtube_usage.v3.sqlite"
            with closing(sqlite3.connect(database_path)) as connection:
                create_schema(connection)
                connection.execute(
                    "INSERT INTO users (person_id, created_at) VALUES (?, ?)",
                    ("local_user", "2026-06-06T08:00:00+02:00"),
                )
                for event_id, video_id in [
                    ("event-short", "short"),
                    ("event-long", "long"),
                    ("event-missing", "missing"),
                    ("event-cached", "cached"),
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
                            "2026-06-06T08:00:00+02:00",
                            video_id,
                            "youtube_usage.v1",
                            "2026-06-06T08:00:00+02:00",
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
                        "cached",
                        123,
                        "PT2M3S",
                        "youtube_data_api",
                        "available",
                        0,
                        "2026-06-06T08:00:00+02:00",
                        None,
                    ),
                )
                connection.commit()

            client = FakeYoutubeClient(
                {
                    "short": {
                        "id": "short",
                        "contentDetails": {"duration": "PT1H2M3S"},
                        "status": {"privacyStatus": "public"},
                    },
                    "long": {
                        "id": "long",
                        "contentDetails": {"duration": "P1DT2H"},
                        "status": {"privacyStatus": "public"},
                    },
                }
            )

            summary = enrich_youtube_durations(
                database_path=database_path,
                client=client,
                max_duration_seconds=5400,
            )

            with closing(sqlite3.connect(database_path)) as connection:
                rows = connection.execute(
                    """
                    SELECT
                        video_id,
                        duration_seconds,
                        duration_iso8601,
                        availability_status,
                        max_duration_applied,
                        error_code
                    FROM video_metadata
                    ORDER BY video_id
                    """
                ).fetchall()
                run = connection.execute(
                    """
                    SELECT
                        requested_video_count,
                        successful_video_count,
                        unavailable_video_count,
                        failed_video_count
                    FROM enrichment_runs
                    """
                ).fetchone()

        self.assertEqual(client.requests, [["long", "missing", "short"]])
        self.assertEqual(summary.requested_video_count, 3)
        self.assertEqual(summary.successful_video_count, 2)
        self.assertEqual(summary.unavailable_video_count, 1)
        self.assertEqual(summary.failed_video_count, 0)
        self.assertEqual(
            rows,
            [
                ("cached", 123, "PT2M3S", "available", 0, None),
                ("long", 5400, "P1DT2H", "available", 1, None),
                ("missing", None, None, "deleted_or_unavailable", 0, "not_returned"),
                ("short", 3723, "PT1H2M3S", "available", 0, None),
            ],
        )
        self.assertEqual(run, (3, 2, 1, 0))
