from __future__ import annotations

from datetime import datetime, timezone
import json
import unittest

from backend.ingestion.models import ParseWarning
from backend.ingestion.parsers.comments_live_chat import parse_comments_live_chat


class CommentsLiveChatParserTests(unittest.TestCase):
    def test_comment_csv_emits_comment_event_with_native_id(self):
        content = (
            "Comment ID,Channel ID,Comment Create Timestamp,Price,"
            "Parent Comment ID,Video ID,Comment Text\n"
            'comment-123,UCprivate,2026-06-06T06:53:12.000Z,,parent-1,video-123,'
            '"{""takeoutSegments"":[{""text"":""raw private comment""}]}"\n'
        ).encode("utf-8")

        result = parse_comments_live_chat(
            content,
            source_path="Takeout/Youtube/comments/comments.csv",
        )

        self.assertEqual(result.records_seen, 1)
        self.assertEqual(result.warnings, [])
        self.assertEqual(len(result.events), 1)
        event = result.events[0]
        self.assertEqual(event.event_type, "comment")
        self.assertEqual(event.product, "youtube")
        self.assertEqual(
            event.occurred_at,
            datetime(2026, 6, 6, 6, 53, 12, tzinfo=timezone.utc),
        )
        self.assertEqual(event.video_id, "video-123")
        self.assertEqual(event.native_id, "comment-123")
        self.assertEqual(event.sequence, 1)
        self.assertIsNone(event.channel_id)
        self.assertIsNone(event.title)
        self.assertIsNone(event.search_query)

        event_payload = json.dumps(event.__dict__, default=str)
        self.assertNotIn("raw private comment", event_payload)
        self.assertNotIn("takeoutSegments", event_payload)

    def test_live_chat_csv_emits_live_chat_event_with_native_id(self):
        content = (
            "Live Chat ID,Channel ID,Live Chat Create Timestamp,Price,"
            "Video ID,Live Chat Text\n"
            'chat-123,UCprivate,2026-06-06T07:01:02Z,,video-456,'
            '"{""takeoutSegments"":[{""text"":""raw private chat""}]}"\n'
        ).encode("utf-8")

        result = parse_comments_live_chat(
            content,
            source_path="Takeout/Youtube/live chats/live chats.csv",
        )

        self.assertEqual(result.records_seen, 1)
        self.assertEqual(result.warnings, [])
        self.assertEqual(len(result.events), 1)
        event = result.events[0]
        self.assertEqual(event.event_type, "live_chat")
        self.assertEqual(event.product, "youtube")
        self.assertEqual(
            event.occurred_at,
            datetime(2026, 6, 6, 7, 1, 2, tzinfo=timezone.utc),
        )
        self.assertEqual(event.video_id, "video-456")
        self.assertEqual(event.native_id, "chat-123")

        event_payload = json.dumps(event.__dict__, default=str)
        self.assertNotIn("raw private chat", event_payload)
        self.assertNotIn("takeoutSegments", event_payload)

    def test_comment_csv_supports_lowercase_takeout_header_variants(self):
        content = (
            "Comment ID,Channel ID,Comment create timestamp,Price,"
            "Parent comment ID,Video ID,Comment text\n"
            'comment-456,UCprivate,2026-01-02T03:04:05Z,,parent-1,video-789,'
            '"{""takeoutSegments"":[{""text"":""private variant""}]}"\n'
        ).encode("utf-8")

        result = parse_comments_live_chat(
            content,
            source_path="Takeout/Youtube/comments/comments.csv",
        )

        self.assertEqual(result.warnings, [])
        self.assertEqual(result.events[0].native_id, "comment-456")
        self.assertEqual(result.events[0].video_id, "video-789")
        self.assertEqual(
            result.events[0].occurred_at,
            datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc),
        )

    def test_malformed_csv_rows_warn_without_leaking_comment_text(self):
        content = (
            "Comment ID,Channel ID,Comment Create Timestamp,Price,"
            "Parent Comment ID,Video ID,Comment Text\n"
            'comment-bad,UCprivate,,,,video-bad,"do not leak this comment"\n'
            'comment-good,UCprivate,2026-06-06T06:53:12Z,,parent,video-good,'
            '"another private comment"\n'
        ).encode("utf-8")

        result = parse_comments_live_chat(
            content,
            source_path="Takeout/Youtube/comments/comments.csv",
        )

        self.assertEqual(result.records_seen, 2)
        self.assertEqual(
            result.warnings,
            [ParseWarning(code="missing_timestamp", sample="row 1")],
        )
        self.assertEqual(len(result.events), 1)
        self.assertEqual(result.events[0].native_id, "comment-good")

        warning_payload = json.dumps(
            [warning.__dict__ for warning in result.warnings]
        )
        event_payload = json.dumps(
            [event.__dict__ for event in result.events],
            default=str,
        )
        self.assertNotIn("do not leak this comment", warning_payload)
        self.assertNotIn("another private comment", event_payload)

    def test_legacy_html_comment_emits_comment_event_without_raw_text(self):
        content = b"""
        <html><body>
          <ul>
            <li>
              Sent at 2020-04-27 23:18:23 UTC while watching
              <a href="http://www.youtube.com/watch?v=legacy-video&amp;lc=legacy-comment">
                a video
              </a>.
              <br/>
              legacy private comment
            </li>
          </ul>
        </body></html>
        """

        result = parse_comments_live_chat(
            content,
            source_path=(
                "Takeout/YouTube and YouTube Music/my-comments/comment-1.html"
            ),
        )

        self.assertEqual(result.records_seen, 1)
        self.assertEqual(result.warnings, [])
        event = result.events[0]
        self.assertEqual(event.event_type, "comment")
        self.assertEqual(event.video_id, "legacy-video")
        self.assertEqual(event.native_id, "legacy-comment")
        self.assertEqual(
            event.occurred_at,
            datetime(2020, 4, 27, 23, 18, 23, tzinfo=timezone.utc),
        )

        event_payload = json.dumps(event.__dict__, default=str)
        self.assertNotIn("legacy private comment", event_payload)

    def test_legacy_html_live_chat_uses_live_chat_event_type(self):
        content = b"""
        <ul>
          <li>
            Sent at 2020-04-27T23:18:23Z while watching
            <a href="https://youtu.be/live-video">a stream</a>.
            <br/>
            legacy private live chat
          </li>
        </ul>
        """

        result = parse_comments_live_chat(
            content,
            source_path=(
                "Takeout/YouTube and YouTube Music/my-live-chat-messages/chat-1.html"
            ),
        )

        self.assertEqual(result.records_seen, 1)
        self.assertEqual(result.warnings, [])
        event = result.events[0]
        self.assertEqual(event.event_type, "live_chat")
        self.assertEqual(event.video_id, "live-video")
        self.assertIsNone(event.native_id)


if __name__ == "__main__":
    unittest.main()
