import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def export_html(cards: str) -> str:
    return f"<html><body>{cards}</body></html>"


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


class YoutubeUsagePipelineTests(unittest.TestCase):
    def test_cli_writes_v1_json_for_takeout_html(self):
        html = export_html(
            activity_card(
                "YouTube",
                """
                Watched&nbsp;<a href="https://www.youtube.com/watch?v=abc123">Example title</a><br>
                <a href="https://www.youtube.com/channel/example">Example Channel</a><br>
                6 Jun 2026, 08:53:12 CEST<br>
                """,
            )
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            input_path = tmp / "watch-history.html"
            output_path = tmp / "youtube_usage.v1.json"
            input_path.write_text(html, encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "backend" / "scripts" / "process_youtube_usage.py"),
                    "--input",
                    str(input_path),
                    "--output",
                    str(output_path),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(payload["schema_version"], "youtube_usage.v1")
        self.assertEqual(payload["person_id"], "local_user")
        self.assertEqual(payload["source"]["input_format"], "google_takeout_html")
        self.assertEqual(payload["quality"]["records_seen"], 1)
        self.assertEqual(payload["quality"]["records_emitted"], 1)
        self.assertEqual(payload["quality"]["records_rejected"], 0)
        self.assertEqual(
            payload["events"],
            [
                {
                    "person_id": "local_user",
                    "platform": "youtube",
                    "product": "youtube",
                    "event_type": "watched",
                    "watched_at": "2026-06-06T08:53:12+02:00",
                    "duration_seconds": None,
                }
            ],
        )

    def test_normalizes_supported_products_events_timestamps_and_strips_content(self):
        html = export_html(
            activity_card(
                "YouTube Music",
                """
                Watched&nbsp;<a href="https://music.youtube.com/watch?v=private_video">Private Song</a><br>
                <a href="https://www.youtube.com/channel/private_channel">Private Artist</a><br>
                7 Sept 2025, 21:05:06 CEST<br>
                """,
            )
            + activity_card(
                "YouTube",
                """
                Viewed&nbsp;<a href="https://www.youtube.com/post/private_post">Private Post</a><br>
                5 Jan 2026, 09:01:02 CET<br>
                """,
            )
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            input_path = tmp / "watch-history.html"
            output_path = tmp / "youtube_usage.v1.json"
            input_path.write_text(html, encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "backend" / "scripts" / "process_youtube_usage.py"),
                    "--input",
                    str(input_path),
                    "--output",
                    str(output_path),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(
            payload["events"],
            [
                {
                    "person_id": "local_user",
                    "platform": "youtube",
                    "product": "youtube_music",
                    "event_type": "watched",
                    "watched_at": "2025-09-07T21:05:06+02:00",
                    "duration_seconds": None,
                },
                {
                    "person_id": "local_user",
                    "platform": "youtube",
                    "product": "youtube",
                    "event_type": "viewed",
                    "watched_at": "2026-01-05T09:01:02+01:00",
                    "duration_seconds": None,
                },
            ],
        )
        serialized = json.dumps(payload["events"])
        self.assertNotIn("Private Song", serialized)
        self.assertNotIn("private_video", serialized)
        self.assertNotIn("Private Artist", serialized)
        self.assertNotIn("private_channel", serialized)
        self.assertNotIn("Private Post", serialized)
        self.assertNotIn("private_post", serialized)

    def test_skips_malformed_records_with_anonymized_quality_warnings(self):
        html = export_html(
            activity_card(
                "YouTube",
                """
                Watched&nbsp;<a href="https://www.youtube.com/watch?v=kept">Kept title</a><br>
                6 Jun 2026, 08:53:12 CEST<br>
                """,
            )
            + activity_card(
                "YouTube",
                """
                Watched&nbsp;<a href="https://www.youtube.com/watch?v=private_missing_video">Missing Timestamp Title</a><br>
                """,
            )
            + activity_card(
                "Google Search",
                """
                Watched&nbsp;<a href="https://www.youtube.com/watch?v=wrong_product">Wrong Product Title</a><br>
                6 Jun 2026, 08:53:12 CEST<br>
                """,
            )
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            input_path = tmp / "watch-history.html"
            output_path = tmp / "youtube_usage.v1.json"
            input_path.write_text(html, encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "backend" / "scripts" / "process_youtube_usage.py"),
                    "--input",
                    str(input_path),
                    "--output",
                    str(output_path),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(payload["quality"]["records_seen"], 3)
        self.assertEqual(payload["quality"]["records_emitted"], 1)
        self.assertEqual(payload["quality"]["records_rejected"], 2)
        self.assertEqual(
            payload["quality"]["warnings"],
            [
                {"code": "missing_timestamp", "count": 1},
                {"code": "unknown_product", "count": 1},
            ],
        )
        serialized_quality = json.dumps(payload["quality"])
        self.assertNotIn("Missing Timestamp Title", serialized_quality)
        self.assertNotIn("private_missing_video", serialized_quality)
        self.assertNotIn("Wrong Product Title", serialized_quality)
        self.assertNotIn("wrong_product", serialized_quality)

    def test_computes_local_time_aggregates_by_product_and_event_type(self):
        html = export_html(
            activity_card(
                "YouTube",
                """
                Watched&nbsp;<a href="https://www.youtube.com/watch?v=one">One</a><br>
                6 Jun 2026, 08:53:12 CEST<br>
                """,
            )
            + activity_card(
                "YouTube",
                """
                Watched&nbsp;<a href="https://www.youtube.com/watch?v=two">Two</a><br>
                6 Jun 2026, 08:12:00 CEST<br>
                """,
            )
            + activity_card(
                "YouTube Music",
                """
                Viewed&nbsp;<a href="https://music.youtube.com/post/three">Three</a><br>
                7 Jun 2026, 23:05:00 CEST<br>
                """,
            )
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            input_path = tmp / "watch-history.html"
            output_path = tmp / "youtube_usage.v1.json"
            input_path.write_text(html, encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "backend" / "scripts" / "process_youtube_usage.py"),
                    "--input",
                    str(input_path),
                    "--output",
                    str(output_path),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(
            payload["aggregates"]["by_day"],
            [
                {
                    "date": "2026-06-06",
                    "product": "youtube",
                    "event_type": "watched",
                    "event_count": 2,
                    "duration_seconds": None,
                },
                {
                    "date": "2026-06-07",
                    "product": "youtube_music",
                    "event_type": "viewed",
                    "event_count": 1,
                    "duration_seconds": None,
                },
            ],
        )
        self.assertEqual(
            payload["aggregates"]["by_hour_of_day"],
            [
                {
                    "hour": 8,
                    "product": "youtube",
                    "event_type": "watched",
                    "event_count": 2,
                    "duration_seconds": None,
                },
                {
                    "hour": 23,
                    "product": "youtube_music",
                    "event_type": "viewed",
                    "event_count": 1,
                    "duration_seconds": None,
                },
            ],
        )
        self.assertEqual(
            payload["aggregates"]["by_weekday"],
            [
                {
                    "weekday": 6,
                    "weekday_name": "Saturday",
                    "product": "youtube",
                    "event_type": "watched",
                    "event_count": 2,
                    "duration_seconds": None,
                },
                {
                    "weekday": 7,
                    "weekday_name": "Sunday",
                    "product": "youtube_music",
                    "event_type": "viewed",
                    "event_count": 1,
                    "duration_seconds": None,
                },
            ],
        )
