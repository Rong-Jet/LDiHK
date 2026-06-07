from __future__ import annotations

from datetime import datetime, timezone
import json
import unittest

from backend.ingestion.parsers.tiktok_watch_history import parse_tiktok_watch_history


class TikTokWatchHistoryParserTests(unittest.TestCase):
    def test_video_list_shape_emits_tiktok_watch_events_and_warnings(self):
        payload = {
            "Your Activity": {
                "Watch History": {
                    "VideoList": [
                        {
                            "Date": "2026-06-06 08:53:12",
                            "Link": "https://www.tiktokv.com/share/video/7345678901234567890/",
                            "Title": " Example TikTok ",
                        },
                        {
                            "Date": "not-a-date",
                            "Link": "https://www.tiktokv.com/share/video/7345678901234567891/",
                        },
                        {
                            "Date": "2026-06-06 08:55:12",
                            "Link": "https://www.tiktok.com/@creator/video/7345678901234567892",
                        },
                        "malformed",
                    ]
                }
            }
        }

        result = parse_tiktok_watch_history(
            json.dumps(payload).encode("utf-8"),
            source_path="TikTok/user_data_tiktok.json",
        )

        self.assertEqual(result.records_seen, 4)
        self.assertEqual(len(result.events), 1)
        event = result.events[0]
        self.assertEqual(event.platform, "tiktok")
        self.assertEqual(event.product, "shorts")
        self.assertEqual(event.event_type, "watch")
        self.assertEqual(event.video_id, "tiktok:7345678901234567890")
        self.assertEqual(event.title, "Example TikTok")
        self.assertEqual(event.duration_seconds, 60)
        self.assertEqual(
            event.occurred_at,
            datetime(2026, 6, 6, 8, 53, 12, tzinfo=timezone.utc),
        )
        self.assertEqual(event.sequence, 1)
        self.assertEqual(
            [warning.code for warning in result.warnings],
            [
                "timestamp_parse_failed",
                "missing_video_id",
                "malformed_json_record",
            ],
        )

    def test_empty_title_is_not_preserved(self):
        payload = {
            "Your Activity": {
                "Watch History": {
                    "VideoList": [
                        {
                            "Date": "2026-06-06T08:53:12Z",
                            "Link": "https://www.tiktokv.com/share/video/7345678901234567890/",
                            "Title": "   ",
                        }
                    ]
                }
            }
        }

        result = parse_tiktok_watch_history(
            json.dumps(payload).encode("utf-8"),
            source_path="user_data_tiktok.json",
        )

        self.assertEqual(result.warnings, [])
        self.assertIsNone(result.events[0].title)

    def test_watch_durations_are_clipped_to_next_watch_start(self):
        payload = {
            "Your Activity": {
                "Watch History": {
                    "VideoList": [
                        {
                            "Date": "2026-06-06 08:53:12",
                            "Link": "https://www.tiktokv.com/share/video/7345678901234567890/",
                        },
                        {
                            "Date": "2026-06-06 08:53:12",
                            "Link": "https://www.tiktokv.com/share/video/7345678901234567891/",
                        },
                        {
                            "Date": "2026-06-06 08:53:42",
                            "Link": "https://www.tiktokv.com/share/video/7345678901234567892/",
                        },
                    ]
                }
            }
        }

        result = parse_tiktok_watch_history(
            json.dumps(payload).encode("utf-8"),
            source_path="user_data_tiktok.json",
        )

        self.assertEqual(result.warnings, [])
        self.assertEqual(
            [event.duration_seconds for event in result.events],
            [0, 30, 60],
        )


if __name__ == "__main__":
    unittest.main()
