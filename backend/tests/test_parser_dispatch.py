from __future__ import annotations

from datetime import datetime, timezone
import unittest

from backend.ingestion.dispatch import dispatch_member_path, parser_name_for_path
from backend.ingestion.models import (
    ParseResult,
    ParseWarning,
    ParsedEvent,
    ParsedSubscription,
)


class ParserContractTests(unittest.TestCase):
    def test_parser_dataclasses_are_public_contracts(self):
        event = ParsedEvent(
            event_type="watch",
            product="youtube",
            occurred_at=datetime(2026, 6, 6, 8, 53, tzinfo=timezone.utc),
            video_id="abc123",
            sequence=4,
        )
        subscription = ParsedSubscription(
            channel_id="UC123",
            channel_url="https://www.youtube.com/channel/UC123",
            channel_title="Example Channel",
        )
        warning = ParseWarning(code="missing_timestamp", sample="row 12")
        result = ParseResult(
            events=[event],
            subscriptions=[subscription],
            warnings=[warning],
            records_seen=2,
        )

        self.assertEqual(result.events, [event])
        self.assertEqual(result.subscriptions, [subscription])
        self.assertEqual(result.warnings, [warning])
        self.assertEqual(result.records_seen, 2)


class ParserDispatchTests(unittest.TestCase):
    def test_routes_watch_history_html_to_watch_parser(self):
        result = dispatch_member_path(
            "Takeout/YouTube and YouTube Music/history/watch-history.html"
        )

        self.assertFalse(result.ignored)
        self.assertEqual(result.parser_name, "watch_history")
        self.assertEqual(
            result.callable_path,
            "backend.ingestion.parsers.watch_history:parse_watch_history",
        )

    def test_routes_known_youtube_takeout_paths(self):
        cases = {
            "watch-history.html": "watch_history",
            "watch-history.json": "watch_history",
            "subscriptions/subscriptions.csv": "subscriptions",
            "subscriptions/subscriptions.json": "subscriptions",
            "playlists/likes.json": "likes_playlists",
            "comments/comments.csv": "comments_live_chat",
            "live chats/live chats.csv": "comments_live_chat",
            "my-comments/comment-1.html": "comments_live_chat",
            "my-live-chat-messages/chat-1.html": "comments_live_chat",
        }

        for suffix, parser_name in cases.items():
            with self.subTest(suffix=suffix):
                source_path = f"Takeout/YouTube and YouTube Music/{suffix}"
                self.assertEqual(parser_name_for_path(source_path), parser_name)

    def test_unmatched_files_are_ignored(self):
        result = dispatch_member_path(
            "Takeout/YouTube and YouTube Music/history/not-watch-history.txt"
        )

        self.assertTrue(result.ignored)
        self.assertIsNone(result.parser_name)
        self.assertIsNone(result.callable_path)
        self.assertEqual(result.reason, "no_parser")

    def test_out_of_scope_creator_files_are_ignored(self):
        creator_paths = [
            "Takeout/YouTube and YouTube Music/channel/videos.csv",
            "Takeout/YouTube and YouTube Music/analytics/revenue.csv",
            "Takeout/YouTube and YouTube Music/creator-studio/dashboard.csv",
        ]

        for source_path in creator_paths:
            with self.subTest(source_path=source_path):
                result = dispatch_member_path(source_path)
                self.assertTrue(result.ignored)
                self.assertIsNone(result.parser_name)

    def test_path_matching_is_case_insensitive_and_zip_style(self):
        result = dispatch_member_path(
            r"Takeout\YouTube and YouTube Music\History\WATCH-HISTORY.JSON"
        )

        self.assertFalse(result.ignored)
        self.assertEqual(result.parser_name, "watch_history")


if __name__ == "__main__":
    unittest.main()
