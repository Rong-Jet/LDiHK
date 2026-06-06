from __future__ import annotations

from datetime import datetime, timezone
import json
import unittest

from backend.ingestion.models import ParseWarning
from backend.ingestion.parsers.search_history import parse_search_history


class SearchHistoryParserTests(unittest.TestCase):
    def test_youtube_activity_json_emits_search_event(self):
        payload = [
            {
                "header": "YouTube",
                "title": "Searched for private search",
                "titleUrl": (
                    "https://www.youtube.com/results?search_query=private+search"
                ),
                "time": "2026-06-06T06:53:12.000Z",
                "products": ["YouTube"],
            }
        ]

        result = parse_search_history(
            json.dumps(payload).encode("utf-8"),
            source_path="Takeout/My Activity/YouTube/MyActivity.json",
        )

        self.assertEqual(result.records_seen, 1)
        self.assertEqual(result.warnings, [])
        self.assertEqual(len(result.events), 1)
        event = result.events[0]
        self.assertEqual(event.event_type, "search")
        self.assertEqual(event.product, "youtube")
        self.assertEqual(
            event.occurred_at,
            datetime(2026, 6, 6, 6, 53, 12, tzinfo=timezone.utc),
        )
        self.assertEqual(event.search_query, "private search")
        self.assertIsNone(event.video_id)
        self.assertIsNone(event.channel_id)
        self.assertIsNone(event.title)
        self.assertIsNone(event.raw_status)
        self.assertEqual(event.sequence, 1)

    def test_query_only_youtube_search_history_json_emits_search_event(self):
        payload = {
            "searchHistory": [
                {
                    "query": "query-only term",
                    "time": "2026-06-06T06:53:12+00:00",
                }
            ]
        }

        result = parse_search_history(
            json.dumps(payload).encode("utf-8"),
            source_path=(
                "Takeout/YouTube and YouTube Music/history/search-history.json"
            ),
        )

        self.assertEqual(result.records_seen, 1)
        self.assertEqual(result.warnings, [])
        self.assertEqual(len(result.events), 1)
        self.assertEqual(result.events[0].search_query, "query-only term")

    def test_ignores_non_youtube_search_activity_and_youtube_non_search_rows(self):
        payload = [
            {
                "header": "Search",
                "title": "Searched for non-youtube term",
                "titleUrl": "https://www.google.com/search?q=non-youtube+term",
                "time": "2026-06-06T06:53:12.000Z",
                "products": ["Search"],
            },
            {
                "header": "YouTube",
                "title": "Watched a private title",
                "titleUrl": "https://www.youtube.com/watch?v=private_video",
                "time": "2026-06-06T06:53:12.000Z",
                "products": ["YouTube"],
            },
        ]

        result = parse_search_history(
            json.dumps(payload).encode("utf-8"),
            source_path="Takeout/My Activity/YouTube/MyActivity.json",
        )

        self.assertEqual(result.records_seen, 2)
        self.assertEqual(result.events, [])
        self.assertEqual(result.warnings, [])

    def test_missing_query_in_youtube_search_record_emits_warning(self):
        payload = [
            {
                "header": "YouTube",
                "title": "Searched for",
                "titleUrl": "https://www.youtube.com/results?search_query=",
                "time": "2026-06-06T06:53:12.000Z",
                "products": ["YouTube"],
            }
        ]

        result = parse_search_history(
            json.dumps(payload).encode("utf-8"),
            source_path="Takeout/My Activity/YouTube/MyActivity.json",
        )

        self.assertEqual(result.records_seen, 1)
        self.assertEqual(result.events, [])
        self.assertEqual(
            result.warnings,
            [ParseWarning(code="missing_search_query", sample="record 1")],
        )

    def test_search_event_does_not_emit_raw_non_search_content(self):
        payload = [
            {
                "header": "YouTube",
                "title": "Searched for private search",
                "titleUrl": (
                    "https://www.youtube.com/results?search_query=private+search"
                ),
                "subtitles": [{"name": "Private Channel Name"}],
                "details": [{"name": "Private non-search details"}],
                "time": "2026-06-06T06:53:12.000Z",
                "products": ["YouTube"],
            }
        ]

        result = parse_search_history(
            json.dumps(payload).encode("utf-8"),
            source_path="Takeout/My Activity/YouTube/MyActivity.json",
        )

        serialized = json.dumps(result, default=_json_default)
        self.assertIn("private search", serialized)
        self.assertNotIn("Private Channel Name", serialized)
        self.assertNotIn("Private non-search details", serialized)
        self.assertNotIn("results?search_query", serialized)


def _json_default(value: object) -> object:
    if hasattr(value, "__dict__"):
        return value.__dict__
    return str(value)


if __name__ == "__main__":
    unittest.main()
