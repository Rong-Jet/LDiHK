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


class PlaylistCsvParserTests(unittest.TestCase):
    def test_current_takeout_playlist_csv_emits_playlist_add_events(self):
        content = (
            "Video ID,Playlist Video Creation Timestamp\n"
            "dQw4w9WgXcQ,2023-01-15T12:34:56+00:00\n"
            "abcdefghijk,2023-01-16T08:00:00+00:00\n"
        ).encode("utf-8")

        result = parse_likes_playlists(
            content,
            source_path="Takeout/YouTube and YouTube Music/playlists/Road trip-videos.csv",
        )

        self.assertEqual(result.records_seen, 2)
        self.assertEqual(result.warnings, [])
        self.assertEqual(
            [event.event_type for event in result.events],
            ["playlist_add", "playlist_add"],
        )
        self.assertEqual(
            [event.video_id for event in result.events], ["dQw4w9WgXcQ", "abcdefghijk"]
        )
        self.assertEqual(
            result.events[0].occurred_at,
            datetime(2023, 1, 15, 12, 34, 56, tzinfo=timezone.utc),
        )
        self.assertEqual([event.product for event in result.events], ["youtube"] * 2)
        self.assertEqual([event.sequence for event in result.events], [1, 2])

    def test_watch_later_and_liked_csv_names_map_to_existing_event_types(self):
        content = (
            "Video ID,Playlist Video Creation Timestamp\n"
            "dQw4w9WgXcQ,2023-01-15T12:34:56+00:00\n"
        ).encode("utf-8")
        cases = {
            "playlists/Watch later-videos.csv": "watch_later_add",
            "Playlists/Später ansehen-Videos.csv": "watch_later_add",
            "playlists/Liked videos-videos.csv": "like",
            "playlists/Favourites-videos.csv": "playlist_add",
        }

        for suffix, event_type in cases.items():
            with self.subTest(suffix=suffix):
                result = parse_likes_playlists(
                    content, source_path=f"Takeout/YouTube and YouTube Music/{suffix}"
                )
                self.assertEqual(
                    [event.event_type for event in result.events], [event_type]
                )

    def test_older_two_block_playlist_csv_is_supported(self):
        content = (
            "Playlist Id,Channel Id,Time Created,Time Updated,Title,Description,Visibility\n"
            "PLabcdefghijklmnopqrstuvwxyz012345,UCabcdefghijklmnopqrstuv,"
            "2020-01-01 10:00:00 UTC,2020-02-01 10:00:00 UTC,Mix,,Private\n"
            "\n"
            "Video Id,Time Added\n"
            "dQw4w9WgXcQ ,2020-01-02 03:04:05 UTC\n"
        ).encode("utf-8")

        result = parse_likes_playlists(
            content, source_path="Takeout/YouTube/playlists/Mix.csv"
        )

        self.assertEqual(result.records_seen, 1)
        self.assertEqual(result.warnings, [])
        self.assertEqual(result.events[0].video_id, "dQw4w9WgXcQ")
        self.assertEqual(
            result.events[0].occurred_at,
            datetime(2020, 1, 2, 3, 4, 5, tzinfo=timezone.utc),
        )

    def test_localized_headers_are_detected_by_values(self):
        content = (
            "Identyfikator filmu,Sygnatura czasowa\n"
            "dQw4w9WgXcQ,2023-01-15T12:34:56+00:00\n"
        ).encode("utf-8")

        result = parse_likes_playlists(
            content, source_path="Takeout/YouTube i YouTube Music/playlisty/Mix-filmy.csv"
        )

        self.assertEqual(result.warnings, [])
        self.assertEqual([event.video_id for event in result.events], ["dQw4w9WgXcQ"])
        self.assertEqual(
            result.events[0].occurred_at,
            datetime(2023, 1, 15, 12, 34, 56, tzinfo=timezone.utc),
        )

    def test_playlist_metadata_and_upload_csvs_are_ignored(self):
        metadata = (
            "Playlist ID,Add new videos to top,Playlist Title (Original),"
            "Playlist Title (Original) Language,Playlist Create Timestamp,"
            "Playlist Update Timestamp,Playlist Video Order,Playlist Visibility\n"
            "PLabcdefghijklmnopqrstuvwxyz012345,False,Mix,,"
            "2023-01-15T12:34:56+00:00,2023-01-15T12:34:56+00:00,Manual,Private\n"
        ).encode("utf-8")
        uploads = (
            "Video ID,Playlist Video Creation Timestamp\n"
            "dQw4w9WgXcQ,2023-01-15T12:34:56+00:00\n"
        ).encode("utf-8")

        metadata_result = parse_likes_playlists(
            metadata, source_path="Takeout/YouTube and YouTube Music/playlists/playlists.csv"
        )
        uploads_result = parse_likes_playlists(
            uploads,
            source_path=(
                "Takeout/YouTube and YouTube Music/playlists/Uploads from Me-videos.csv"
            ),
        )

        for result in (metadata_result, uploads_result):
            self.assertEqual(result.events, [])
            self.assertEqual(result.warnings, [])
            self.assertEqual(result.records_seen, 0)

    def test_csv_rows_without_video_id_or_timestamp_warn(self):
        content = (
            "Video ID,Playlist Video Creation Timestamp\n"
            ",2023-01-15T12:34:56+00:00\n"
            "dQw4w9WgXcQ,\n"
        ).encode("utf-8")

        result = parse_likes_playlists(
            content, source_path="Takeout/YouTube and YouTube Music/playlists/Mix-videos.csv"
        )

        self.assertEqual(result.records_seen, 2)
        self.assertEqual(
            result.warnings,
            [
                ParseWarning(code="missing_video_id", sample="record 1"),
                ParseWarning(code="missing_timestamp", sample="record 2"),
            ],
        )
        self.assertEqual(len(result.events), 1)
        self.assertIsNone(result.events[0].occurred_at)


if __name__ == "__main__":
    unittest.main()
