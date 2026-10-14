from __future__ import annotations

from datetime import datetime, timezone
import json
import os
import unittest
from unittest.mock import patch

from backend.ingestion.models import ParseWarning
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

    def test_liked_posts_json_emits_liked_post_events_in_utc(self):
        payload = {
            "likes_media_likes": [
                {
                    "title": "creator_one",
                    "string_list_data": [
                        {
                            "href": "https://www.instagram.com/p/example-one/",
                            "value": "ð\u009f\u0091\u008d",
                            "timestamp": 1780672020,
                        }
                    ],
                },
                {
                    "title": "creator_two",
                    "string_list_data": [{"timestamp": 0}],
                },
            ]
        }

        with patch.dict(os.environ, {}, clear=True):
            result = parse_instagram_activity(
                json.dumps(payload).encode("utf-8"),
                source_path="Instagram/your_instagram_activity/likes/liked_posts.json",
            )

        self.assertEqual(result.records_seen, 2)
        self.assertEqual(
            result.warnings, [ParseWarning(code="missing_timestamp", sample="record 2")]
        )
        self.assertEqual(len(result.events), 1)
        event = result.events[0]
        self.assertEqual(event.platform, "instagram")
        self.assertEqual(event.product, "posts")
        self.assertEqual(event.event_type, "liked_post")
        self.assertEqual(event.title, "creator_one")
        self.assertEqual(event.duration_seconds, 15)
        self.assertEqual(
            event.occurred_at, datetime.fromtimestamp(1780672020, tz=timezone.utc)
        )

    def test_json_equivalents_use_the_same_event_types_as_html(self):
        cases = [
            (
                "your_instagram_activity/saved/saved_posts.json",
                {
                    "saved_saved_media": [
                        {
                            "title": "creator",
                            "string_map_data": {
                                "Saved on": {
                                    "href": "https://www.instagram.com/p/x/",
                                    "timestamp": 1780672020,
                                }
                            },
                        }
                    ]
                },
                "saved_post",
                "posts",
            ),
            (
                "ads_information/ads_and_topics/videos_watched.json",
                {
                    "impressions_history_videos_watched": [
                        {
                            "string_map_data": {
                                "Author": {"value": "creator"},
                                "Time": {"timestamp": 1780672020},
                            }
                        }
                    ]
                },
                "video_watch",
                "reels",
            ),
            (
                "ads_information/ads_and_topics/posts_viewed.json",
                {
                    "impressions_history_posts_seen": [
                        {
                            "string_map_data": {
                                "Author": {"value": "creator"},
                                "Time": {"timestamp": 1780672020},
                            }
                        }
                    ]
                },
                "post_view",
                "posts",
            ),
            (
                "your_instagram_activity/story_interactions/story_likes.json",
                {
                    "story_activities_story_likes": [
                        {
                            "title": "creator",
                            "string_list_data": [{"timestamp": 1780672020}],
                        }
                    ]
                },
                "story_like",
                "stories",
            ),
            (
                "your_instagram_activity/content/posts_1.json",
                [
                    {
                        "media": [
                            {
                                "uri": "media/posts/1.jpg",
                                "creation_timestamp": 1780672020,
                                "title": "Holiday",
                            }
                        ]
                    }
                ],
                "post_created",
                "posts",
            ),
            (
                "your_instagram_activity/content/reels.json",
                {
                    "ig_reels_media": [
                        {"media": [{"creation_timestamp": 1780672020, "title": ""}]}
                    ]
                },
                "reel_created",
                "reels",
            ),
            (
                "your_instagram_activity/content/stories.json",
                {"ig_stories": [{"uri": "x.mp4", "creation_timestamp": 1780672020}]},
                "story_created",
                "stories",
            ),
            (
                "connections/followers_and_following/recently_unfollowed_profiles.json",
                {
                    "relationships_unfollowed_users": [
                        {
                            "title": "",
                            "string_list_data": [
                                {"value": "someone", "timestamp": 1780672020}
                            ],
                        }
                    ]
                },
                "unfollowed_profile",
                "connections",
            ),
        ]

        for suffix, payload, event_type, product in cases:
            with self.subTest(suffix=suffix):
                result = parse_instagram_activity(
                    json.dumps(payload).encode("utf-8"),
                    source_path=f"instagram-export/{suffix}",
                )

                self.assertEqual(result.warnings, [])
                self.assertEqual(result.records_seen, 1)
                self.assertEqual(
                    [(event.event_type, event.product) for event in result.events],
                    [(event_type, product)],
                )
                self.assertEqual(
                    result.events[0].occurred_at,
                    datetime.fromtimestamp(1780672020, tz=timezone.utc),
                )

    def test_message_json_emits_redacted_events_per_message(self):
        payload = {
            "participants": [{"name": "Friend"}, {"name": "Me"}],
            "messages": [
                {
                    "sender_name": "Friend",
                    "timestamp_ms": 1780672020123,
                    "content": "Very private message body",
                },
                {"sender_name": "Me", "timestamp_ms": 1780672000000, "content": "hi"},
            ],
            "title": "Friend",
        }

        result = parse_instagram_activity(
            json.dumps(payload).encode("utf-8"),
            source_path=(
                "Instagram/your_instagram_activity/messages/inbox/friend_1/message_1.json"
            ),
        )

        self.assertEqual(result.records_seen, 2)
        self.assertEqual(result.warnings, [])
        self.assertEqual([event.event_type for event in result.events], ["message"] * 2)
        self.assertEqual([event.title for event in result.events], [None, None])
        self.assertNotIn("Very private", json.dumps([e.__dict__ for e in result.events], default=str))

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
