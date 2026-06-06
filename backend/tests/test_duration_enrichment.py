import sqlite3
import unittest
from contextlib import closing

from backend.enrichment.durations import enrich_missing_youtube_durations


class FakeYoutubeClient:
    def __init__(self, videos=None, error=None):
        self.videos = videos or {}
        self.error = error
        self.requests = []

    def list_videos(self, video_ids):
        self.requests.append(list(video_ids))
        if self.error is not None:
            raise self.error
        return [self.videos[video_id] for video_id in video_ids if video_id in self.videos]


class DurationEnrichmentWorkerTests(unittest.TestCase):
    def test_selects_missing_video_ids_batches_at_50_and_upserts_durations(self):
        with closing(_connection()) as connection:
            video_ids = [f"video-{index:02d}" for index in range(51)]
            for video_id in video_ids:
                _insert_usage_event(connection, video_id)
            videos = {
                video_id: {
                    "id": video_id,
                    "contentDetails": {"duration": "PT15M33S"},
                    "status": {"privacyStatus": "public"},
                }
                for video_id in video_ids
            }
            client = FakeYoutubeClient(videos)

            summary = enrich_missing_youtube_durations(connection, client)

            rows = connection.execute(
                """
                SELECT video_id, duration_seconds, duration_source,
                       availability_status, max_duration_applied,
                       attempt_count, last_error
                FROM youtube_videos
                ORDER BY video_id
                """
            ).fetchall()

        self.assertEqual([len(request) for request in client.requests], [50, 1])
        self.assertEqual(summary.requested_video_count, 51)
        self.assertEqual(summary.successful_video_count, 51)
        self.assertEqual(summary.unavailable_video_count, 0)
        self.assertEqual(summary.failed_video_count, 0)
        self.assertEqual(summary.api_call_count, 2)
        self.assertEqual(len(rows), 51)
        self.assertEqual(
            rows[0],
            (
                "video-00",
                933,
                "youtube_data_api",
                "available",
                0,
                1,
                None,
            ),
        )

    def test_tracks_missing_api_results_and_caps_long_durations(self):
        with closing(_connection()) as connection:
            for video_id in ("short", "long", "missing", "cached"):
                _insert_usage_event(connection, video_id)
            connection.execute(
                """
                INSERT INTO youtube_videos (
                    video_id,
                    duration_seconds,
                    duration_source,
                    availability_status,
                    max_duration_applied,
                    attempt_count
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                ("cached", 123, "youtube_data_api", "available", False, 1),
            )
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

            summary = enrich_missing_youtube_durations(
                connection,
                client,
                max_duration_seconds=5400,
            )

            rows = connection.execute(
                """
                SELECT video_id, duration_seconds, availability_status,
                       max_duration_applied, attempt_count, last_error
                FROM youtube_videos
                ORDER BY video_id
                """
            ).fetchall()

        self.assertEqual(client.requests, [["long", "missing", "short"]])
        self.assertEqual(summary.requested_video_count, 3)
        self.assertEqual(summary.successful_video_count, 2)
        self.assertEqual(summary.unavailable_video_count, 1)
        self.assertEqual(summary.failed_video_count, 0)
        self.assertEqual(
            rows,
            [
                ("cached", 123, "available", 0, 1, None),
                ("long", 5400, "available", 1, 1, None),
                ("missing", None, "deleted_or_unavailable", 0, 1, "not_returned"),
                ("short", 3723, "available", 0, 1, None),
            ],
        )

    def test_api_errors_are_tracked_and_retried_on_next_run(self):
        with closing(_connection()) as connection:
            _insert_usage_event(connection, "retry")
            connection.execute(
                """
                INSERT INTO youtube_videos (
                    video_id,
                    duration_source,
                    availability_status,
                    max_duration_applied,
                    attempt_count,
                    last_error
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    "retry",
                    "youtube_data_api",
                    "api_error",
                    False,
                    1,
                    "previous",
                ),
            )
            failing_client = FakeYoutubeClient(error=RuntimeError("quota exceeded"))

            failed_summary = enrich_missing_youtube_durations(connection, failing_client)
            failed_row = connection.execute(
                """
                SELECT availability_status, attempt_count, last_error
                FROM youtube_videos
                WHERE video_id = ?
                """,
                ("retry",),
            ).fetchone()

            successful_client = FakeYoutubeClient(
                {
                    "retry": {
                        "id": "retry",
                        "contentDetails": {"duration": "PT2M"},
                        "status": {"privacyStatus": "public"},
                    }
                }
            )
            successful_summary = enrich_missing_youtube_durations(
                connection, successful_client
            )
            successful_row = connection.execute(
                """
                SELECT duration_seconds, availability_status,
                       attempt_count, last_error
                FROM youtube_videos
                WHERE video_id = ?
                """,
                ("retry",),
            ).fetchone()

        self.assertEqual(failed_summary.requested_video_count, 1)
        self.assertEqual(failed_summary.failed_video_count, 1)
        self.assertEqual(failed_row[0], "api_error")
        self.assertEqual(failed_row[1], 2)
        self.assertEqual(failed_row[2], "RuntimeError: quota exceeded")

        self.assertEqual(successful_summary.requested_video_count, 1)
        self.assertEqual(successful_summary.successful_video_count, 1)
        self.assertEqual(successful_row, (120, "available", 3, None))


def _connection():
    connection = sqlite3.connect(":memory:")
    connection.executescript(
        """
        CREATE TABLE usage_events (
            id TEXT PRIMARY KEY,
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
        """
    )
    return connection


def _insert_usage_event(connection, video_id):
    connection.execute(
        """
        INSERT INTO usage_events (
            id,
            platform,
            product,
            event_type,
            video_id
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        (f"event-{video_id}", "youtube", "youtube", "watch", video_id),
    )


if __name__ == "__main__":
    unittest.main()

