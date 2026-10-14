from __future__ import annotations

import json
import unittest

from backend.ingestion.dispatch import parser_name_for_path
from backend.ingestion.parsers.youtube_activity_auto import (
    parse_youtube_activity_auto,
)
from backend.tests.test_watch_history_parser import activity_card, export_html


class LocalizedTakeoutDispatchTests(unittest.TestCase):
    def test_localized_youtube_files_are_routed(self):
        cases = {
            # German names are routed explicitly.
            "Takeout/YouTube und YouTube Music/Verlauf/Wiedergabeverlauf.html": "watch_history",
            "Takeout/YouTube und YouTube Music/Verlauf/Suchverlauf.json": "search_history",
            "Takeout/YouTube und YouTube Music/Abos/Abos.csv": "subscriptions",
            # Other languages fall back to content-based classification.
            "Takeout/YouTube y YouTube Music/historial/historial-de-reproducciones.html": (
                "youtube_activity_auto"
            ),
            "Takeout/YouTube et YouTube Music/historique/historique-des-vidéos-regardées.json": (
                "youtube_activity_auto"
            ),
            "Takeout/YouTube y YouTube Music/suscripciones/suscripciones.csv": "subscriptions",
            "Takeout/YouTube y YouTube Music/listas de reproducción/Me gusta-videos.csv": (
                "likes_playlists"
            ),
            # "My Activity" in another language still only yields searches.
            "Takeout/Mi actividad/YouTube/MiActividad.html": "search_history",
        }

        for source_path, parser_name in cases.items():
            with self.subTest(source_path=source_path):
                self.assertEqual(parser_name_for_path(source_path), parser_name)

    def test_files_outside_youtube_folders_and_media_are_ignored(self):
        for source_path in (
            "Takeout/Chrome/BrowserHistory.json",
            "Takeout/YouTube y YouTube Music/vídeos/mi-video.mp4",
            "Takeout/archive_browser.html",
        ):
            with self.subTest(source_path=source_path):
                self.assertIsNone(parser_name_for_path(source_path))


class YoutubeActivityAutoParserTests(unittest.TestCase):
    def test_spanish_watch_history_html_is_classified_as_watches(self):
        html = export_html(
            activity_card(
                "YouTube",
                """
                Has visto <a href="https://www.youtube.com/watch?v=abc123">Mi vídeo</a><br>
                <a href="https://www.youtube.com/channel/UCabc">Canal</a><br>
                6 jun 2026, 8:53:12 CEST<br>
                """,
            )
            + activity_card(
                "YouTube",
                """
                Has visto un vídeo que se ha eliminado<br>
                5 jun 2026, 22:10:00 CEST<br>
                """,
            )
        )

        result = parse_youtube_activity_auto(
            html,
            source_path="Takeout/YouTube y YouTube Music/historial/historial-de-reproducciones.html",
        )

        self.assertEqual(result.records_seen, 2)
        self.assertEqual([event.event_type for event in result.events], ["watch", "watch"])
        self.assertEqual(result.events[0].video_id, "abc123")
        self.assertEqual(result.events[0].occurred_at.isoformat(), "2026-06-06T08:53:12+02:00")

    def test_search_history_json_is_classified_as_searches(self):
        records = [
            {
                "header": "YouTube",
                "title": "Has buscado recetas de pasta",
                "titleUrl": "https://www.youtube.com/results?search_query=recetas+de+pasta",
                "time": "2026-06-06T08:53:12.123Z",
                "products": ["YouTube"],
            }
        ]

        result = parse_youtube_activity_auto(
            json.dumps(records).encode("utf-8"),
            source_path="Takeout/YouTube y YouTube Music/historial/historial-de-búsqueda.json",
        )

        self.assertEqual([event.event_type for event in result.events], ["search"])
        self.assertEqual(result.events[0].search_query, "recetas de pasta")

    def test_unrelated_youtube_json_yields_no_events(self):
        result = parse_youtube_activity_auto(
            json.dumps([{"channelTitle": "Mi canal"}]).encode("utf-8"),
            source_path="Takeout/YouTube y YouTube Music/canales/canal.json",
        )

        self.assertEqual(result.events, [])
        self.assertIn(
            "youtube_activity_unrecognized",
            [warning.code for warning in result.warnings],
        )


if __name__ == "__main__":
    unittest.main()
