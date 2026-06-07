from __future__ import annotations

from datetime import datetime, timezone
import os
import unittest
from unittest.mock import patch

from backend.ingestion.parsers.instagram_activity import parse_instagram_activity


class InstagramActivityParserTests(unittest.TestCase):
    def test_liked_posts_emit_one_15_second_interaction_per_timestamped_record(self):
        html = """
        <html>
          <body>
            <ul>
              <li>
                <div class="_a6-p">
                  <a href="https://www.instagram.com/p/example-one/">creator_one</a>
                  <div class="_3-94 _a6-o">Jun 05, 2026 3:27 PM</div>
                </div>
              </li>
              <li>
                <div class="_a6-p">
                  <a href="https://www.instagram.com/p/example-two/">creator_two</a>
                  <div class="_3-94 _a6-o">Jun 05, 2026 3:27 PM</div>
                </div>
              </li>
            </ul>
          </body>
        </html>
        """

        with patch.dict(os.environ, {"INSTAGRAM_EXPORT_TIMEZONE": "Europe/Berlin"}):
            result = parse_instagram_activity(
                html.encode("utf-8"),
                source_path=(
                    "Instagram/your_instagram_activity/likes/liked_posts.html"
                ),
            )

        self.assertEqual(result.records_seen, 2)
        self.assertEqual(result.warnings, [])
        self.assertEqual(len(result.events), 2)
        self.assertEqual([event.sequence for event in result.events], [1, 2])
        self.assertEqual([event.platform for event in result.events], ["instagram"] * 2)
        self.assertEqual([event.product for event in result.events], ["posts"] * 2)
        self.assertEqual([event.event_type for event in result.events], ["liked_post"] * 2)
        self.assertEqual(
            [event.duration_seconds for event in result.events],
            [15, 15],
        )
        self.assertEqual(
            [event.occurred_at for event in result.events],
            [
                datetime(2026, 6, 5, 13, 27, tzinfo=timezone.utc),
                datetime(2026, 6, 5, 13, 27, tzinfo=timezone.utc),
            ],
        )

    def test_messages_emit_timestamped_events_without_private_body_text(self):
        html = """
        <html>
          <body>
            <div class="message">
              <div>Very private message body</div>
              <div class="_3-94 _a6-o">Jun 05, 2026 9:01 AM</div>
            </div>
          </body>
        </html>
        """

        with patch.dict(os.environ, {"INSTAGRAM_EXPORT_TIMEZONE": "UTC"}):
            result = parse_instagram_activity(
                html.encode("utf-8"),
                source_path=(
                    "Instagram/your_instagram_activity/messages/inbox/thread_1/"
                    "message_1.html"
                ),
            )

        self.assertEqual(result.records_seen, 1)
        self.assertEqual(result.warnings, [])
        self.assertEqual(len(result.events), 1)
        event = result.events[0]
        self.assertEqual(event.platform, "instagram")
        self.assertEqual(event.product, "messages")
        self.assertEqual(event.event_type, "message")
        self.assertEqual(event.duration_seconds, 15)
        self.assertIsNone(event.title)

    def test_naive_export_timestamp_warns_when_timezone_is_not_configured(self):
        html = """
        <html>
          <body>
            <div class="_a6-p">
              <div>story owner</div>
              <div class="_3-94 _a6-o">Jun 05, 2026 3:27 PM</div>
            </div>
          </body>
        </html>
        """

        with patch.dict(os.environ, {}, clear=True):
            result = parse_instagram_activity(
                html.encode("utf-8"),
                source_path=(
                    "Instagram/your_instagram_activity/story_interactions/"
                    "stories_viewed.html"
                ),
            )

        self.assertEqual(len(result.events), 1)
        self.assertEqual(
            result.events[0].occurred_at,
            datetime(2026, 6, 5, 15, 27, tzinfo=timezone.utc),
        )
        self.assertEqual([warning.code for warning in result.warnings], ["timezone_assumed_utc"])

    def test_unrecognized_source_path_is_not_parsed(self):
        result = parse_instagram_activity(
            b"<html><body>Jun 05, 2026 3:27 PM</body></html>",
            source_path="Instagram/personal_information.html",
        )

        self.assertEqual(result.records_seen, 0)
        self.assertEqual(result.events, [])
        self.assertEqual(
            [warning.code for warning in result.warnings],
            ["instagram_source_unrecognized"],
        )


if __name__ == "__main__":
    unittest.main()
