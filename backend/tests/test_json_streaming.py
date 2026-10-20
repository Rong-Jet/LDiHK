from __future__ import annotations

import json
import unittest
from unittest import mock

from backend.ingestion.parsers import search_history, watch_history, youtube_activity_auto
from backend.ingestion.parsers.takeout_activity import is_json_array, iter_json_array


def _watch(index: int) -> dict:
    return {
        "header": "YouTube",
        "title": f"Watched Video {index}",
        "titleUrl": f"https://www.youtube.com/watch?v=vid{index:05d}",
        "time": f"2026-06-0{1 + index % 9}T10:00:0{index % 10}Z",
        "products": ["YouTube"],
    }


class IterJsonArrayTests(unittest.TestCase):
    def test_matches_json_loads_for_arrays(self):
        for document in ("[]", " [ ] ", '[1, {"a": [2, 3]}, "x"]\n', '[{"t": "a,]"}]', "\r\n[ {} ]\r\n"):
            with self.subTest(document=document):
                self.assertTrue(is_json_array(document))
                self.assertEqual(list(iter_json_array(document)), json.loads(document))

    def test_rejects_malformed_arrays(self):
        for document in ("[1 2]", "[1,]", "[1] x", '{"a": 1}', "[1", ""):
            with self.subTest(document=document):
                with self.assertRaises(json.JSONDecodeError):
                    list(iter_json_array(document))


class StreamingParserTests(unittest.TestCase):
    def test_array_histories_are_not_loaded_with_json_loads(self):
        content = json.dumps([_watch(index) for index in range(3)]).encode()

        # A whole-document json.loads is what made large exports run out of
        # memory; array files must be decoded record by record instead.
        with mock.patch.object(json, "loads", side_effect=AssertionError("json.loads used")):
            watch = watch_history.parse_watch_history(content, source_path="watch-history.json")
            auto = youtube_activity_auto.parse_youtube_activity_auto(
                content, source_path="Takeout/YouTube y YouTube Music/historial/historial.json"
            )

        self.assertEqual(len(watch.events), 3)
        self.assertEqual(watch.records_seen, 3)
        self.assertEqual(len(auto.events), 3)

    def test_wrapped_object_histories_still_parse(self):
        content = json.dumps({"watchHistory": [_watch(0), _watch(1)]}).encode()

        result = watch_history.parse_watch_history(content, source_path="watch-history.json")

        self.assertEqual(len(result.events), 2)

    def test_truncated_array_reports_decode_failure_without_partial_events(self):
        content = (json.dumps([_watch(0), _watch(1)])[:-20]).encode()

        for parse in (
            lambda: watch_history.parse_watch_history(content, source_path="watch-history.json"),
            lambda: search_history.parse_search_history(content, source_path="search-history.json"),
            lambda: youtube_activity_auto.parse_youtube_activity_auto(content, source_path="YouTube/x/h.json"),
        ):
            result = parse()
            self.assertEqual(result.events, [])
            self.assertIn("json_decode_failed", [warning.code for warning in result.warnings])


if __name__ == "__main__":
    unittest.main()
