from __future__ import annotations

from datetime import datetime, timezone
import json
import unittest

from backend.ingestion.models import ParseWarning
from backend.ingestion.parsers.likes_playlists import parse_likes_playlists


class LikesPlaylistsParserTests(unittest.TestCase):
    def test_likes_json_emits_like_events_with_video_ids(self):
        payload = {
            "items": [
                {
                    "kind": "youtube#playlistItem",
                    "id": "liked-item-1",
                    "snippet": {
                        "publishedAt": "2026-06-06T06:53:12Z",
                        "title": "Liked Video",
                        "resourceId": {
                            "kind": "youtube#video",
                            "videoId": "abc123",
                        },
                    },
                }
            ]
        }

        result = parse_likes_playlists(
            json.dumps(payload).encode("utf-8"),
            source_path="Takeout/YouTube and YouTube Music/playlists/likes.json",
        )

        self.assertEqual(result.records_seen, 1)
        self.assertEqual(result.warnings, [])
        self.assertEqual(result.subscriptions, [])
        self.assertEqual(len(result.events), 1)
        event = result.events[0]
        self.assertEqual(event.event_type, "like")
        self.assertEqual(event.product, "youtube")
        self.assertEqual(event.occurred_at, datetime(2026, 6, 6, 6, 53, 12, tzinfo=timezone.utc))
        self.assertEqual(event.video_id, "abc123")
        self.assertEqual(event.title, "Liked Video")
        self.assertEqual(event.native_id, "liked-item-1")
        self.assertEqual(event.sequence, 1)

    def test_missing_timestamps_do_not_fail_likes(self):
        payload = [
            {
                "title": "Liked Video",
                "titleUrl": "https://www.youtube.com/watch?v=no-time",
            }
        ]

        result = parse_likes_playlists(
            json.dumps(payload).encode("utf-8"),
            source_path="Takeout/YouTube and YouTube Music/playlists/likes.json",
        )

        self.assertEqual(result.records_seen, 1)
        self.assertEqual(result.warnings, [ParseWarning(code="missing_timestamp", sample="record 1")])
        self.assertEqual(len(result.events), 1)
        event = result.events[0]
        self.assertEqual(event.event_type, "like")
        self.assertIsNone(event.occurred_at)
        self.assertEqual(event.video_id, "no-time")
        self.assertEqual(event.sequence, 1)

    def test_watch_later_playlist_emits_watch_later_add_events(self):
        payload = {
            "videos": [
                {
                    "videoId": "later123",
                    "title": "Watch Later Video",
                    "addedAt": "2026-01-05T08:01:02+00:00",
                }
            ]
        }

        result = parse_likes_playlists(
            json.dumps(payload).encode("utf-8"),
            source_path="Takeout/YouTube and YouTube Music/playlists/watch-later.json",
        )

        self.assertEqual(result.records_seen, 1)
        self.assertEqual(result.warnings, [])
        self.assertEqual(len(result.events), 1)
        event = result.events[0]
        self.assertEqual(event.event_type, "watch_later_add")
        self.assertEqual(event.occurred_at, datetime(2026, 1, 5, 8, 1, 2, tzinfo=timezone.utc))
        self.assertEqual(event.video_id, "later123")
        self.assertEqual(event.title, "Watch Later Video")

    def test_simple_playlist_file_emits_playlist_add_events(self):
        payload = [
            {
                "videoUrl": "https://youtu.be/playlist123",
                "title": "Playlist Video",
                "dateAdded": "2026-02-03T04:05:06Z",
            }
        ]

        result = parse_likes_playlists(
            json.dumps(payload).encode("utf-8"),
            source_path="Takeout/YouTube and YouTube Music/playlists/Favorites.json",
        )

        self.assertEqual(result.records_seen, 1)
        self.assertEqual(result.warnings, [])
        self.assertEqual(len(result.events), 1)
        event = result.events[0]
        self.assertEqual(event.event_type, "playlist_add")
        self.assertEqual(event.video_id, "playlist123")
        self.assertEqual(event.title, "Playlist Video")
        self.assertEqual(event.occurred_at, datetime(2026, 2, 3, 4, 5, 6, tzinfo=timezone.utc))

    def test_malformed_entries_emit_warnings_without_raw_content(self):
        payload = [
            {
                "title": "No video URL",
                "time": "2026-06-06T06:53:12Z",
            },
            "not an object",
            {
                "titleUrl": "https://www.youtube.com/watch?v=good123",
                "time": "not a timestamp",
            },
        ]

        result = parse_likes_playlists(
            json.dumps(payload).encode("utf-8"),
            source_path="Takeout/YouTube and YouTube Music/playlists/likes.json",
        )

        self.assertEqual(result.records_seen, 3)
        self.assertEqual([warning.code for warning in result.warnings], [
            "missing_video_id",
            "malformed_playlist_entry",
            "timestamp_parse_failed",
        ])
        self.assertEqual(len(result.events), 1)
        self.assertEqual(result.events[0].video_id, "good123")
        warning_payload = json.dumps([warning.__dict__ for warning in result.warnings])
        self.assertNotIn("No video URL", warning_payload)

    def test_uploads_playlist_metadata_is_ignored(self):
        payload = {
            "kind": "youtube#playlistListResponse",
            "items": [
                {
                    "kind": "youtube#playlist",
                    "id": "UUcreatorUploads",
                    "snippet": {"title": "Uploads"},
                }
            ],
        }

        result = parse_likes_playlists(
            json.dumps(payload).encode("utf-8"),
            source_path="Takeout/YouTube and YouTube Music/playlists/uploads.json",
        )

        self.assertEqual(result.records_seen, 0)
        self.assertEqual(result.events, [])
        self.assertEqual(result.warnings, [])

    def test_playlist_metadata_list_is_ignored(self):
        payload = [
            {
                "kind": "youtube#playlist",
                "id": "PLcreated",
                "snippet": {"title": "Created Playlist"},
            }
        ]

        result = parse_likes_playlists(
            json.dumps(payload).encode("utf-8"),
            source_path="Takeout/YouTube and YouTube Music/playlists/created.json",
        )

        self.assertEqual(result.records_seen, 0)
        self.assertEqual(result.events, [])
        self.assertEqual(result.warnings, [])


if __name__ == "__main__":
    unittest.main()
