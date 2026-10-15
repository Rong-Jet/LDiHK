from __future__ import annotations

from datetime import datetime, timezone
import json
import unittest
from unittest.mock import patch

import bs4

from backend.ingestion.parsers import takeout_activity, watch_history
from backend.ingestion.parsers.watch_history import parse_watch_history


def export_html(cards: str) -> bytes:
    return f"<html><body>{cards}</body></html>".encode("utf-8")


def activity_card(product: str, body: str, details: str | None = None) -> str:
    caption = ""
    if details is not None:
        caption = f"""
        <div class="content-cell mdl-cell mdl-cell--6-col mdl-typography--body-1 mdl-typography--text-right"></div>
        <div class="content-cell mdl-cell mdl-cell--12-col mdl-typography--caption">
          <b>Products:</b><br>&emsp;{product}<br>
          <b>Details:</b><br>&emsp;{details}<br>
        </div>
        """
    return f"""
    <div class="outer-cell mdl-cell mdl-cell--12-col mdl-shadow--2dp">
      <div class="mdl-grid">
        <div class="header-cell mdl-cell mdl-cell--12-col">
          <p class="mdl-typography--title">{product}<br></p>
        </div>
        <div class="content-cell mdl-cell mdl-cell--6-col mdl-typography--body-1">
          {body}
        </div>
        {caption}
      </div>
    </div>
    """


WATCH_HISTORY_HTML = "Takeout/YouTube and YouTube Music/history/watch-history.html"
WATCH_HISTORY_JSON = "Takeout/YouTube and YouTube Music/history/watch-history.json"


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

    def test_html_parser_parses_document_once_without_reparsing_cards(self):
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
        # The document is parsed exactly once by the streaming lxml parser:
        # cards are neither re-serialised nor re-parsed with BeautifulSoup
        # (the old per-card re-parse made 126 MB exports take ~2 minutes).
        def fail(*args, **kwargs):
            raise AssertionError("cards must not be re-serialised or re-parsed")

        with (
            patch.object(bs4.BeautifulSoup, "__init__", fail),
            patch.object(takeout_activity.etree, "tostring", fail),
        ):
            result = parse_watch_history(
                html,
                source_path=(
                    "Takeout/YouTube and YouTube Music/history/watch-history.html"
                ),
            )

        self.assertEqual(result.records_seen, 2)
        self.assertEqual(
            [event.video_id for event in result.events], ["first123", "second456"]
        )

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


class LocalizedWatchHistoryTests(unittest.TestCase):
    def test_localized_html_timestamps_are_parsed(self):
        cases = {
            "de numeric": ("Kanal 12.03.2024, 14:22:11 MEZ", "2024-03-12T14:22:11+01:00"),
            "de named": ("6. Juni 2026, 08:53:12 MESZ", "2026-06-06T08:53:12+02:00"),
            "de umlaut": ("12. März 2024, 14:22:11 MEZ", "2024-03-12T14:22:11+01:00"),
            "es": ("12 mar 2024, 14:22:11 CET", "2024-03-12T14:22:11+01:00"),
            "es long": ("6 de junio de 2026, 8:53:12 CEST", "2026-06-06T08:53:12+02:00"),
            "es 12h": ("6 jun 2026, 8:53:12 p. m. CET", "2026-06-06T20:53:12+01:00"),
            "fr": ("12 mars 2024, 14:22:11 UTC+1", "2024-03-12T14:22:11+01:00"),
            "fr à": ("6 juin 2026 à 08:53:12 UTC+02:00", "2026-06-06T08:53:12+02:00"),
            "fr abbr": ("12 févr. 2024, 14:22:11 UTC−3", "2024-02-12T14:22:11-03:00"),
            "it": ("6 giu 2026, 08:53:12 CEST", "2026-06-06T08:53:12+02:00"),
            "pt": ("12 de mar. de 2024, 14:22:11 BRT", "2024-03-12T14:22:11-03:00"),
            "nl": ("12 mrt 2024, 14:22:11 CET", "2024-03-12T14:22:11+01:00"),
            "nl abbr": ("6 jun. 2026 08:53:12 CEST", "2026-06-06T08:53:12+02:00"),
            "en us": ("Jun 6, 2026, 8:53:12 PM PDT", "2026-06-06T20:53:12-07:00"),
        }

        for name, (timestamp, expected) in cases.items():
            with self.subTest(name=name):
                html = export_html(
                    activity_card(
                        "YouTube",
                        f"""
                        <a href="https://www.youtube.com/watch?v=abc123">Titel 12.03.2020</a> angesehen<br>
                        <a href="https://www.youtube.com/channel/UCabc">Kanal</a><br>
                        {timestamp}<br>
                        """,
                    )
                )

                result = parse_watch_history(
                    html,
                    source_path="Takeout/YouTube und YouTube Music/Verlauf/Wiedergabeverlauf.html",
                )

                self.assertEqual(result.warnings, [])
                self.assertEqual(result.events[0].occurred_at.isoformat(), expected)
                self.assertIsNone(result.events[0].raw_status)

    def test_timezone_abbreviations_and_offsets_are_parsed(self):
        cases = {
            "BST": "+01:00",
            "IST": "+05:30",
            "AEST": "+10:00",
            "AEDT": "+11:00",
            "JST": "+09:00",
            "KST": "+09:00",
            "MSK": "+03:00",
            "CEST": "+02:00",
            "CET": "+01:00",
            "MEZ": "+01:00",
            "MESZ": "+02:00",
            "EEST": "+03:00",
            "EET": "+02:00",
            "WEST": "+01:00",
            "WET": "+00:00",
            "HKT": "+08:00",
            "SGT": "+08:00",
            "NZST": "+12:00",
            "NZDT": "+13:00",
            "BRT": "-03:00",
            "ART": "-03:00",
            "GMT+2": "+02:00",
            "GMT-3": "-03:00",
            "UTC+01:00": "+01:00",
            "GMT+05:30": "+05:30",
        }

        for zone, offset in cases.items():
            with self.subTest(zone=zone):
                html = export_html(
                    activity_card(
                        "YouTube",
                        f"""
                        Watched&nbsp;<a href="https://www.youtube.com/watch?v=abc123">Video</a><br>
                        6 Jun 2026, 08:53:12 {zone}<br>
                        """,
                    )
                )

                result = parse_watch_history(html, source_path=WATCH_HISTORY_HTML)

                self.assertEqual(result.warnings, [])
                self.assertEqual(
                    result.events[0].occurred_at.isoformat(),
                    f"2026-06-06T08:53:12{offset}",
                )

    def test_unknown_timezone_falls_back_to_utc_with_warning(self):
        html = export_html(
            activity_card(
                "YouTube",
                """
                Watched&nbsp;<a href="https://www.youtube.com/watch?v=abc123">Video</a><br>
                6 Jun 2026, 08:53:12 XYZT<br>
                """,
            )
        )

        result = parse_watch_history(html, source_path=WATCH_HISTORY_HTML)

        self.assertEqual(
            [warning.code for warning in result.warnings], ["timestamp_unknown_timezone"]
        )
        self.assertEqual(
            result.events[0].occurred_at,
            datetime(2026, 6, 6, 8, 53, 12, tzinfo=timezone.utc),
        )

    def test_localized_removed_video_is_marked_deleted(self):
        html = export_html(
            activity_card("YouTube", "Ein Video angesehen, das entfernt wurde<br>12.03.2024, 14:22:11 MEZ<br>")
            + activity_card("YouTube", "Has visto un vídeo que se ha eliminado<br>12 mar 2024, 14:22:11 CET<br>")
        )

        result = parse_watch_history(html, source_path=WATCH_HISTORY_HTML)

        self.assertEqual([event.raw_status for event in result.events], ["deleted", "deleted"])
        self.assertEqual(
            [warning.code for warning in result.warnings], ["deleted_watch", "deleted_watch"]
        )

    def test_localized_status_words_in_real_titles_do_not_change_status(self):
        html = export_html(
            activity_card(
                "YouTube",
                """
                <a href="https://www.youtube.com/watch?v=abc123">10 km entfernt – privat gefilmt</a> angesehen<br>
                12.03.2024, 14:22:11 MEZ<br>
                """,
            )
        )

        result = parse_watch_history(html, source_path=WATCH_HISTORY_HTML)

        self.assertIsNone(result.events[0].raw_status)
        self.assertEqual(result.warnings, [])

    def test_localized_json_titles_are_cleaned(self):
        payload = [
            {
                "header": "YouTube",
                "title": "Beispielvideo angesehen",
                "titleUrl": "https://www.youtube.com/watch?v=de123",
                "time": "2024-03-12T13:22:11.123Z",
            },
            {
                "header": "YouTube",
                "title": "Vous avez regardé Exemple",
                "titleUrl": "https://www.youtube.com/watch?v=fr123",
                "time": "2024-03-12T13:22:11Z",
            },
        ]

        result = parse_watch_history(
            json.dumps(payload).encode("utf-8"),
            source_path="Takeout/YouTube und YouTube Music/Verlauf/Wiedergabeverlauf.json",
        )

        self.assertEqual([event.title for event in result.events], ["Beispielvideo", "Exemple"])


class GoogleAdsWatchTests(unittest.TestCase):
    def test_json_records_from_google_ads_are_not_watch_events(self):
        payload = [
            {
                "header": "YouTube",
                "title": "Watched Some Advert",
                "titleUrl": "https://www.youtube.com/watch?v=ad123",
                "time": "2026-06-06T06:53:12.000Z",
                "details": [{"name": "From Google Ads"}],
                "products": ["YouTube"],
            },
            {
                "header": "YouTube",
                "title": "Watched Real Video",
                "titleUrl": "https://www.youtube.com/watch?v=real123",
                "time": "2026-06-06T06:50:00.000Z",
                "products": ["YouTube"],
            },
            {
                "header": "YouTube",
                "title": "Werbung angesehen",
                "titleUrl": "https://www.youtube.com/watch?v=ad456",
                "time": "2026-06-06T06:40:00.000Z",
                "details": [{"name": "Von Google Ads"}],
            },
        ]

        result = parse_watch_history(
            json.dumps(payload).encode("utf-8"), source_path=WATCH_HISTORY_JSON
        )

        self.assertEqual(result.records_seen, 3)
        self.assertEqual([event.video_id for event in result.events], ["real123"])
        self.assertEqual(
            [(warning.code, warning.sample) for warning in result.warnings],
            [
                ("google_ads_watch_skipped", "record 1"),
                ("google_ads_watch_skipped", "record 3"),
            ],
        )

    def test_html_cards_from_google_ads_are_not_watch_events(self):
        html = export_html(
            activity_card(
                "YouTube",
                """
                Watched&nbsp;<a href="https://www.youtube.com/watch?v=ad123">Advert</a><br>
                6 Jun 2026, 08:53:12 CEST<br>
                """,
                details="From Google Ads",
            )
            + activity_card(
                "YouTube",
                """
                <a href="https://www.youtube.com/watch?v=ad456">Werbung</a> angesehen<br>
                06.06.2026, 08:50:12 MESZ<br>
                """,
                details="Von Google Ads",
            )
            + activity_card(
                "YouTube",
                """
                Has visto&nbsp;<a href="https://www.youtube.com/watch?v=ad789">Anuncio</a><br>
                6 jun 2026, 08:45:12 CEST<br>
                """,
                details="De Google Ads",
            )
            + activity_card(
                "YouTube",
                """
                Watched&nbsp;<a href="https://www.youtube.com/watch?v=real123">How to use Google Ads</a><br>
                6 Jun 2026, 08:40:12 CEST<br>
                """,
            )
        )

        result = parse_watch_history(html, source_path=WATCH_HISTORY_HTML)

        self.assertEqual(result.records_seen, 4)
        self.assertEqual([event.video_id for event in result.events], ["real123"])
        self.assertEqual(
            [warning.code for warning in result.warnings],
            ["google_ads_watch_skipped"] * 3,
        )


class GermanNonVideoRecordTests(unittest.TestCase):
    """Shapes seen in a real German Takeout (2026): ads and other activity
    that sit in Wiedergabeverlauf.html but are not video watches."""

    def test_german_html_ads_and_non_video_cards_are_not_watch_events(self):
        html = export_html(
            activity_card(
                "YouTube",
                """
                <a href="https://www.youtube.com/watch?v=ad123">Werbespot</a> angesehen<br>
                <a href="https://www.youtube.com/channel/UCad">Werbekanal</a><br>
                06.06.2026, 08:50:12 MESZ<br>
                """,
                details="Von Google Anzeigen",
            )
            + activity_card(
                "YouTube",
                "Hat Anzeigen bei YouTube Shorts angesehen<br>06.06.2026, 08:45:12 MESZ<br>",
            )
            + activity_card(
                "YouTube",
                "Hat Anzeigen auf der YouTube-Startseite angesehen<br>06.06.2026, 08:44:12 MESZ<br>",
            )
            + activity_card(
                "YouTube",
                """
                <a href="https://www.youtube.com/post/UgkxPost">Neues Video ist online</a> angesehen<br>
                <a href="https://www.youtube.com/channel/UCposter">Kanal</a><br>
                06.06.2026, 08:40:12 MESZ<br>
                """,
            )
            + activity_card(
                "YouTube",
                """
                <a href="https://www.google.com/url?q=https://example.com/angebot">example.com</a> aufgerufen<br>
                06.06.2026, 08:35:12 MESZ<br>
                """,
            )
            + activity_card(
                "YouTube",
                "Ein Video angesehen, das entfernt wurde<br>06.06.2026, 08:30:12 MESZ<br>",
            )
            + activity_card(
                "YouTube",
                """
                <a href="https://www.youtube.com/watch?v=real123">Wie man Anzeigen schaltet</a> angesehen<br>
                06.06.2026, 08:20:12 MESZ<br>
                """,
            )
        )

        result = parse_watch_history(
            html, source_path="Takeout/YouTube und YouTube Music/Verlauf/Wiedergabeverlauf.html"
        )

        self.assertEqual(result.records_seen, 7)
        # The removed video still counts; so does a real video about ads.
        self.assertEqual(
            [(event.video_id, event.raw_status) for event in result.events],
            [(None, "deleted"), ("real123", None)],
        )
        self.assertEqual(
            [warning.code for warning in result.warnings],
            [
                "google_ads_watch_skipped",
                "google_ads_watch_skipped",
                "google_ads_watch_skipped",
                "non_video_activity_skipped",
                "non_video_activity_skipped",
                "deleted_watch",
            ],
        )

    def test_german_json_ads_and_non_video_records_are_not_watch_events(self):
        payload = [
            {
                "header": "YouTube",
                "title": "Werbespot angesehen",
                "titleUrl": "https://www.youtube.com/watch?v=ad123",
                "time": "2026-06-06T06:50:12.000Z",
                "details": [{"name": "Von Google Anzeigen"}],
            },
            {
                "header": "YouTube",
                "title": "Hat Anzeigen bei YouTube Shorts angesehen",
                "time": "2026-06-06T06:45:12.000Z",
            },
            {
                "header": "YouTube",
                "title": "Neues Video ist online angesehen",
                "titleUrl": "https://www.youtube.com/post/UgkxPost",
                "time": "2026-06-06T06:40:12.000Z",
            },
            {
                "header": "YouTube",
                "title": "Echtes Video angesehen",
                "titleUrl": "https://www.youtube.com/watch?v=real123",
                "time": "2026-06-06T06:20:12.000Z",
            },
        ]

        result = parse_watch_history(
            json.dumps(payload).encode("utf-8"),
            source_path="Takeout/YouTube und YouTube Music/Verlauf/Wiedergabeverlauf.json",
        )

        self.assertEqual([event.video_id for event in result.events], ["real123"])
        self.assertEqual(
            [warning.code for warning in result.warnings],
            ["google_ads_watch_skipped", "google_ads_watch_skipped", "non_video_activity_skipped"],
        )


if __name__ == "__main__":
    unittest.main()
