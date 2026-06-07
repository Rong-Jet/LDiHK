from __future__ import annotations

from datetime import datetime, timezone
import json
import unittest
from unittest.mock import patch

from backend.ingestion.parsers import watch_history
from backend.ingestion.parsers.watch_history import parse_watch_history


def export_html(cards: str) -> bytes:
    return f"<html><body>{cards}</body></html>".encode("utf-8")


def activity_card(product: str, body: str) -> str:
    return f"""
    <div class="outer-cell mdl-cell mdl-cell--12-col mdl-shadow--2dp">
      <div class="mdl-grid">
        <div class="header-cell mdl-cell mdl-cell--12-col">
          <p class="mdl-typography--title">{product}<br></p>
        </div>
        <div class="content-cell mdl-cell mdl-cell--6-col mdl-typography--body-1">
          {body}
        </div>
      </div>
    </div>
    """


class WatchHistoryParserTests(unittest.TestCase):
    def test_html_watch_card_emits_normalized_watch_event(self):
        html = export_html(
            activity_card(
                "YouTube",
                """
                Watched&nbsp;<a href="https://www.youtube.com/watch?v=abc123&feature=share">Example title</a><br>
                <a href="https://www.youtube.com/channel/UCabc123">Example Channel</a><br>
                6 Jun 2026, 08:53:12 CEST<br>
                """,
            )
        )

        result = parse_watch_history(
            html,
            source_path="Takeout/YouTube and YouTube Music/history/watch-history.html",
        )

        self.assertEqual(result.records_seen, 1)
        self.assertEqual(result.warnings, [])
        self.assertEqual(len(result.events), 1)
        event = result.events[0]
        self.assertEqual(event.event_type, "watch")
        self.assertEqual(event.product, "youtube")
        self.assertEqual(event.occurred_at.isoformat(), "2026-06-06T08:53:12+02:00")
        self.assertEqual(event.video_id, "abc123")
        self.assertEqual(event.channel_id, "UCabc123")
        self.assertEqual(event.title, "Example title")
        self.assertIsNone(event.raw_status)
        self.assertEqual(event.sequence, 1)

    def test_html_distinguishes_youtube_music(self):
        html = export_html(
            activity_card(
                "YouTube Music",
                """
                Watched&nbsp;<a href="https://music.youtube.com/watch?list=OLAK5uy&v=music_123">Example song</a><br>
                5 Jan 2026, 09:01:02 CET<br>
                """,
            )
        )

        result = parse_watch_history(
            html,
            source_path="Takeout/YouTube and YouTube Music/history/watch-history.html",
        )

        self.assertEqual(result.records_seen, 1)
        self.assertEqual(result.events[0].product, "youtube_music")
        self.assertEqual(result.events[0].video_id, "music_123")
        self.assertEqual(result.events[0].occurred_at.isoformat(), "2026-01-05T09:01:02+01:00")

    def test_html_marks_deleted_and_malformed_rows_without_raw_content(self):
        html = export_html(
            activity_card(
                "YouTube",
                """
                Watched a video that has been removed<br>
                5 Jan 2026, 09:01:02 CET<br>
                """,
            )
            + activity_card(
                "YouTube",
                """
                Watched&nbsp;<a href="https://www.youtube.com/watch?v=private_missing_timestamp">Private title</a><br>
                """,
            )
        )

        result = parse_watch_history(
            html,
            source_path="Takeout/YouTube and YouTube Music/history/watch-history.html",
        )

        self.assertEqual(result.records_seen, 2)
        self.assertEqual([event.raw_status for event in result.events], ["deleted", "malformed"])
        self.assertIsNone(result.events[0].video_id)
        self.assertIsNone(result.events[1].occurred_at)
        self.assertEqual(
            [warning.code for warning in result.warnings],
            ["deleted_watch", "missing_timestamp"],
        )
        event_payload = json.dumps([event.__dict__ for event in result.events], default=str)
        warning_payload = json.dumps([warning.__dict__ for warning in result.warnings])
        self.assertNotIn("<a", event_payload)
        self.assertNotIn("Private title", warning_payload)
        self.assertNotIn("private_missing_timestamp", warning_payload)

    def test_html_extracts_video_ids_with_robust_url_parsing(self):
        html = export_html(
            activity_card(
                "YouTube",
                """
                Watched&nbsp;<a href="https://www.youtube.com/watch?time_continue=1&v=abc-123_456&feature=emb_title">Query video</a><br>
                6 Jun 2026, 08:53:12 CEST<br>
                """,
            )
            + activity_card(
                "YouTube",
                """
                Watched&nbsp;<a href="https://youtu.be/shortUrl123?t=12">Short URL video</a><br>
                6 Jun 2026, 09:53:12 CEST<br>
                """,
            )
        )

        result = parse_watch_history(
            html,
            source_path="Takeout/YouTube and YouTube Music/history/watch-history.html",
        )

        self.assertEqual([event.video_id for event in result.events], ["abc-123_456", "shortUrl123"])

    def test_html_parser_handles_activity_cards_split_across_chunks(self):
        html = export_html(
            activity_card(
                "YouTube",
                """
                Watched&nbsp;<a href="https://www.youtube.com/watch?v=split123">Split Chunk Video</a><br>
                6 Jun 2026, 08:53:12 CEST<br>
                """,
            )
            + activity_card(
                "YouTube Music",
                """
                Watched&nbsp;<a href="https://music.youtube.com/watch?v=split456">Split Chunk Song</a><br>
                6 Jun 2026, 09:53:12 CEST<br>
                """,
            )
        )

        with patch.object(watch_history, "HTML_PARSE_CHUNK_BYTES", 17):
            result = parse_watch_history(
                html,
                source_path=(
                    "Takeout/YouTube and YouTube Music/history/watch-history.html"
                ),
        )

        self.assertEqual(result.records_seen, 2)
        self.assertEqual(
            [event.video_id for event in result.events],
            ["split123", "split456"],
        )

    def test_html_parser_does_not_build_full_document_beautifulsoup_tree(self):
        html = export_html(
            activity_card(
                "YouTube",
                """
                Watched&nbsp;<a href="https://www.youtube.com/watch?v=first123">First Video</a><br>
                6 Jun 2026, 08:53:12 CEST<br>
                """,
            )
            + activity_card(
                "YouTube",
                """
                Watched&nbsp;<a href="https://www.youtube.com/watch?v=second456">Second Video</a><br>
                6 Jun 2026, 09:53:12 CEST<br>
                """,
            )
        )
        original_beautiful_soup = watch_history.BeautifulSoup
        parsed_markup_sizes: list[int] = []

        def tracking_beautiful_soup(markup, *args, **kwargs):
            parsed_markup_sizes.append(len(markup))
            return original_beautiful_soup(markup, *args, **kwargs)

        with patch.object(watch_history, "BeautifulSoup", tracking_beautiful_soup):
            result = parse_watch_history(
                html,
                source_path=(
                    "Takeout/YouTube and YouTube Music/history/watch-history.html"
                ),
            )

        self.assertEqual(result.records_seen, 2)
        self.assertEqual(len(parsed_markup_sizes), 2)
        self.assertTrue(all(size < len(html) for size in parsed_markup_sizes))

    def test_json_watch_history_is_supported(self):
        payload = [
            {
                "header": "YouTube",
                "title": "Watched JSON Video",
                "titleUrl": "https://www.youtube.com/watch?feature=share&v=json123",
                "subtitles": [
                    {
                        "name": "JSON Channel",
                        "url": "https://www.youtube.com/channel/UCjson123",
                    }
                ],
                "time": "2026-06-06T06:53:12.000Z",
            },
            {
                "header": "YouTube Music",
                "title": "Watched JSON Song",
                "titleUrl": "https://music.youtube.com/watch?v=music-json&list=OLAK5uy",
                "time": "2026-01-05T08:01:02+00:00",
            },
        ]

        result = parse_watch_history(
            json.dumps(payload).encode("utf-8"),
            source_path="Takeout/YouTube and YouTube Music/history/watch-history.json",
        )

        self.assertEqual(result.records_seen, 2)
        self.assertEqual(result.warnings, [])
        self.assertEqual([event.product for event in result.events], ["youtube", "youtube_music"])
        self.assertEqual([event.video_id for event in result.events], ["json123", "music-json"])
        self.assertEqual(result.events[0].channel_id, "UCjson123")
        self.assertEqual(result.events[0].title, "JSON Video")
        self.assertEqual(
            result.events[0].occurred_at,
            datetime(2026, 6, 6, 6, 53, 12, tzinfo=timezone.utc),
        )


if __name__ == "__main__":
    unittest.main()
