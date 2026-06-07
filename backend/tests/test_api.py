import json
import tempfile
import unittest
from pathlib import Path

from backend.app import create_app


class YoutubeUsageApiTests(unittest.TestCase):
    def test_health_returns_ok(self):
        app = create_app(processed_path=Path("does-not-need-to-exist.json"))

        response = app.test_client().get("/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"status": "ok"})

    def test_serves_processed_youtube_usage_json(self):
        payload = {
            "schema_version": "youtube_usage.v1",
            "person_id": "local_user",
            "events": [],
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            processed_path = Path(tmpdir) / "youtube_usage.v1.json"
            processed_path.write_text(json.dumps(payload), encoding="utf-8")
            app = create_app(processed_path=processed_path)

            response = app.test_client().get("/api/users/local_user/youtube-usage")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), payload)

    def test_missing_processed_youtube_usage_returns_service_unavailable(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            processed_path = Path(tmpdir) / "missing.json"
            app = create_app(processed_path=processed_path)

            response = app.test_client().get("/api/users/local_user/youtube-usage")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.get_json(),
            {
                "error": "processed_data_missing",
                "expected_path": str(processed_path),
            },
        )

    def test_missing_processed_youtube_temporal_returns_service_unavailable(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            processed_path = Path(tmpdir) / "missing.json"
            app = create_app(processed_path=processed_path)

            response = app.test_client().get(
                "/api/v2/users/local_user/youtube-usage/temporal"
            )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.get_json(),
            {
                "error": "processed_data_missing",
                "expected_path": str(processed_path),
            },
        )

    def test_serves_empty_youtube_temporal_payload(self):
        payload = {
            "schema_version": "youtube_usage.v1",
            "person_id": "local_user",
            "source": {"timezone": "Europe/Berlin"},
            "events": [],
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            processed_path = Path(tmpdir) / "youtube_usage.v1.json"
            processed_path.write_text(json.dumps(payload), encoding="utf-8")
            app = create_app(processed_path=processed_path)

            response = app.test_client().get(
                "/api/v2/users/local_user/youtube-usage/temporal"
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json(),
            {
                "person_id": "local_user",
                "schema_version": "youtube_usage.temporal.v2",
                "source_schema_version": "youtube_usage.v1",
                "duration_strategy": {
                    "kind": "fixed_placeholder",
                    "watched_event_seconds": 600,
                    "is_estimate": True,
                },
                "daily": [],
                "hourly_heatmap": [],
                "sessions": [],
            },
        )

    def test_temporal_returns_empty_payload_when_no_events_survive_filtering(self):
        payload = {
            "schema_version": "youtube_usage.v1",
            "person_id": "local_user",
            "source": {"timezone": "Europe/Berlin"},
            "events": [
                {
                    "person_id": "local_user",
                    "platform": "youtube",
                    "product": "youtube_music",
                    "event_type": "watched",
                    "watched_at": "2026-06-06T08:00:00+02:00",
                    "duration_seconds": None,
                },
                {
                    "person_id": "local_user",
                    "platform": "youtube",
                    "product": "youtube",
                    "event_type": "viewed",
                    "watched_at": "2026-06-06T09:00:00+02:00",
                    "duration_seconds": None,
                },
            ],
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            processed_path = Path(tmpdir) / "youtube_usage.v1.json"
            processed_path.write_text(json.dumps(payload), encoding="utf-8")
            app = create_app(processed_path=processed_path)

            response = app.test_client().get(
                "/api/v2/users/local_user/youtube-usage/temporal"
            )

        self.assertEqual(response.status_code, 200)
        temporal = response.get_json()
        self.assertEqual(temporal["daily"], [])
        self.assertEqual(temporal["hourly_heatmap"], [])
        self.assertEqual(temporal["sessions"], [])

    def test_temporal_filters_to_watched_youtube_without_raw_event_rows(self):
        payload = {
            "schema_version": "youtube_usage.v1",
            "person_id": "local_user",
            "source": {"timezone": "Europe/Berlin"},
            "events": [
                {
                    "person_id": "local_user",
                    "platform": "youtube",
                    "product": "youtube",
                    "event_type": "watched",
                    "watched_at": "2026-06-06T08:00:00+02:00",
                    "duration_seconds": None,
                    "title": "Private Title",
                    "url": "https://www.youtube.com/watch?v=private",
                    "channel_name": "Private Channel",
                    "video_id": "private",
                },
                {
                    "person_id": "local_user",
                    "platform": "youtube",
                    "product": "youtube_music",
                    "event_type": "watched",
                    "watched_at": "2026-06-06T09:00:00+02:00",
                    "duration_seconds": None,
                },
                {
                    "person_id": "local_user",
                    "platform": "youtube",
                    "product": "youtube",
                    "event_type": "viewed",
                    "watched_at": "2026-06-06T10:00:00+02:00",
                    "duration_seconds": None,
                },
            ],
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            processed_path = Path(tmpdir) / "youtube_usage.v1.json"
            processed_path.write_text(json.dumps(payload), encoding="utf-8")
            app = create_app(processed_path=processed_path)

            response = app.test_client().get(
                "/api/v2/users/local_user/youtube-usage/temporal"
            )

        self.assertEqual(response.status_code, 200)
        temporal = response.get_json()
        self.assertEqual(
            temporal["daily"],
            [
                {
                    "date": "2026-06-06",
                    "event_count": 1,
                    "estimated_seconds": 600,
                    "session_count": 1,
                }
            ],
        )
        self.assertEqual(len(temporal["hourly_heatmap"]), 24)
        self.assertEqual(
            temporal["hourly_heatmap"][8],
            {
                "date": "2026-06-06",
                "hour": 8,
                "event_count": 1,
                "estimated_seconds": 600,
            },
        )
        self.assertEqual(
            temporal["sessions"],
            [
                {
                    "session_id": "session_000001",
                    "started_at": "2026-06-06T08:00:00+02:00",
                    "ended_at": "2026-06-06T08:10:00+02:00",
                    "observed_span_seconds": 600,
                    "event_count": 1,
                    "estimated_seconds": 600,
                }
            ],
        )
        serialized = json.dumps(temporal)
        self.assertNotIn("events", temporal)
        self.assertNotIn("Private Title", serialized)
        self.assertNotIn("private", serialized)
        self.assertNotIn("Private Channel", serialized)
        self.assertNotIn("youtube_music", serialized)
        self.assertNotIn("viewed", serialized)

    def test_temporal_zero_fills_daily_and_hourly_ranges(self):
        payload = {
            "schema_version": "youtube_usage.v1",
            "person_id": "local_user",
            "source": {"timezone": "Europe/Berlin"},
            "events": [
                {
                    "person_id": "local_user",
                    "platform": "youtube",
                    "product": "youtube",
                    "event_type": "watched",
                    "watched_at": "2026-06-06T08:00:00+02:00",
                    "duration_seconds": None,
                },
                {
                    "person_id": "local_user",
                    "platform": "youtube",
                    "product": "youtube",
                    "event_type": "watched",
                    "watched_at": "2026-06-08T09:00:00+02:00",
                    "duration_seconds": None,
                },
            ],
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            processed_path = Path(tmpdir) / "youtube_usage.v1.json"
            processed_path.write_text(json.dumps(payload), encoding="utf-8")
            app = create_app(processed_path=processed_path)

            response = app.test_client().get(
                "/api/v2/users/local_user/youtube-usage/temporal"
            )

        self.assertEqual(response.status_code, 200)
        temporal = response.get_json()
        self.assertEqual(
            temporal["daily"],
            [
                {
                    "date": "2026-06-06",
                    "event_count": 1,
                    "estimated_seconds": 600,
                    "session_count": 1,
                },
                {
                    "date": "2026-06-07",
                    "event_count": 0,
                    "estimated_seconds": 0,
                    "session_count": 0,
                },
                {
                    "date": "2026-06-08",
                    "event_count": 1,
                    "estimated_seconds": 600,
                    "session_count": 1,
                },
            ],
        )
        self.assertEqual(len(temporal["hourly_heatmap"]), 72)
        zero_day = [
            row
            for row in temporal["hourly_heatmap"]
            if row["date"] == "2026-06-07"
        ]
        self.assertEqual(len(zero_day), 24)
        self.assertTrue(
            all(
                row["event_count"] == 0 and row["estimated_seconds"] == 0
                for row in zero_day
            )
        )

    def test_temporal_uses_source_timezone_for_chart_buckets(self):
        payload = {
            "schema_version": "youtube_usage.v1",
            "person_id": "local_user",
            "source": {"timezone": "Europe/Berlin"},
            "events": [
                {
                    "person_id": "local_user",
                    "platform": "youtube",
                    "product": "youtube",
                    "event_type": "watched",
                    "watched_at": "2026-06-06T06:00:00+00:00",
                    "duration_seconds": None,
                }
            ],
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            processed_path = Path(tmpdir) / "youtube_usage.v1.json"
            processed_path.write_text(json.dumps(payload), encoding="utf-8")
            app = create_app(processed_path=processed_path)

            response = app.test_client().get(
                "/api/v2/users/local_user/youtube-usage/temporal"
            )

        self.assertEqual(response.status_code, 200)
        temporal = response.get_json()
        self.assertEqual(temporal["hourly_heatmap"][8]["event_count"], 1)
        self.assertEqual(
            temporal["sessions"][0]["started_at"], "2026-06-06T08:00:00+02:00"
        )

    def test_temporal_merges_overlaps_and_splits_estimates_by_hour(self):
        payload = {
            "schema_version": "youtube_usage.v1",
            "person_id": "local_user",
            "source": {"timezone": "Europe/Berlin"},
            "events": [
                {
                    "person_id": "local_user",
                    "platform": "youtube",
                    "product": "youtube",
                    "event_type": "watched",
                    "watched_at": "2026-06-06T08:55:00+02:00",
                    "duration_seconds": None,
                },
                {
                    "person_id": "local_user",
                    "platform": "youtube",
                    "product": "youtube",
                    "event_type": "watched",
                    "watched_at": "2026-06-06T09:00:00+02:00",
                    "duration_seconds": None,
                },
            ],
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            processed_path = Path(tmpdir) / "youtube_usage.v1.json"
            processed_path.write_text(json.dumps(payload), encoding="utf-8")
            app = create_app(processed_path=processed_path)

            response = app.test_client().get(
                "/api/v2/users/local_user/youtube-usage/temporal"
            )

        self.assertEqual(response.status_code, 200)
        temporal = response.get_json()
        self.assertEqual(
            temporal["daily"],
            [
                {
                    "date": "2026-06-06",
                    "event_count": 2,
                    "estimated_seconds": 900,
                    "session_count": 1,
                }
            ],
        )
        self.assertEqual(
            temporal["hourly_heatmap"][8],
            {
                "date": "2026-06-06",
                "hour": 8,
                "event_count": 1,
                "estimated_seconds": 300,
            },
        )
        self.assertEqual(
            temporal["hourly_heatmap"][9],
            {
                "date": "2026-06-06",
                "hour": 9,
                "event_count": 1,
                "estimated_seconds": 600,
            },
        )

    def test_temporal_splits_estimates_across_day_boundary(self):
        payload = {
            "schema_version": "youtube_usage.v1",
            "person_id": "local_user",
            "source": {"timezone": "Europe/Berlin"},
            "events": [
                {
                    "person_id": "local_user",
                    "platform": "youtube",
                    "product": "youtube",
                    "event_type": "watched",
                    "watched_at": "2026-06-06T23:55:00+02:00",
                    "duration_seconds": None,
                },
            ],
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            processed_path = Path(tmpdir) / "youtube_usage.v1.json"
            processed_path.write_text(json.dumps(payload), encoding="utf-8")
            app = create_app(processed_path=processed_path)

            response = app.test_client().get(
                "/api/v2/users/local_user/youtube-usage/temporal"
            )

        self.assertEqual(response.status_code, 200)
        temporal = response.get_json()
        self.assertEqual(
            temporal["daily"],
            [
                {
                    "date": "2026-06-06",
                    "event_count": 1,
                    "estimated_seconds": 300,
                    "session_count": 1,
                },
                {
                    "date": "2026-06-07",
                    "event_count": 0,
                    "estimated_seconds": 300,
                    "session_count": 0,
                },
            ],
        )
        self.assertEqual(
            temporal["hourly_heatmap"][23],
            {
                "date": "2026-06-06",
                "hour": 23,
                "event_count": 1,
                "estimated_seconds": 300,
            },
        )
        self.assertEqual(
            temporal["hourly_heatmap"][24],
            {
                "date": "2026-06-07",
                "hour": 0,
                "event_count": 0,
                "estimated_seconds": 300,
            },
        )

    def test_temporal_sessions_split_after_more_than_thirty_minute_gap(self):
        payload = {
            "schema_version": "youtube_usage.v1",
            "person_id": "local_user",
            "source": {"timezone": "Europe/Berlin"},
            "events": [
                {
                    "person_id": "local_user",
                    "platform": "youtube",
                    "product": "youtube",
                    "event_type": "watched",
                    "watched_at": "2026-06-06T08:00:00+02:00",
                    "duration_seconds": None,
                },
                {
                    "person_id": "local_user",
                    "platform": "youtube",
                    "product": "youtube",
                    "event_type": "watched",
                    "watched_at": "2026-06-06T08:40:00+02:00",
                    "duration_seconds": None,
                },
                {
                    "person_id": "local_user",
                    "platform": "youtube",
                    "product": "youtube",
                    "event_type": "watched",
                    "watched_at": "2026-06-06T09:21:00+02:00",
                    "duration_seconds": None,
                },
            ],
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            processed_path = Path(tmpdir) / "youtube_usage.v1.json"
            processed_path.write_text(json.dumps(payload), encoding="utf-8")
            app = create_app(processed_path=processed_path)

            response = app.test_client().get(
                "/api/v2/users/local_user/youtube-usage/temporal"
            )

        self.assertEqual(response.status_code, 200)
        temporal = response.get_json()
        self.assertEqual(
            temporal["daily"],
            [
                {
                    "date": "2026-06-06",
                    "event_count": 3,
                    "estimated_seconds": 1800,
                    "session_count": 2,
                }
            ],
        )
        self.assertEqual(
            temporal["sessions"],
            [
                {
                    "session_id": "session_000001",
                    "started_at": "2026-06-06T08:00:00+02:00",
                    "ended_at": "2026-06-06T08:50:00+02:00",
                    "observed_span_seconds": 3000,
                    "event_count": 2,
                    "estimated_seconds": 3000,
                },
                {
                    "session_id": "session_000002",
                    "started_at": "2026-06-06T09:21:00+02:00",
                    "ended_at": "2026-06-06T09:31:00+02:00",
                    "observed_span_seconds": 600,
                    "event_count": 1,
                    "estimated_seconds": 600,
                },
            ],
        )
