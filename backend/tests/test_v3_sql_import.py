import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
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


class YoutubeUsageSqlImportTests(unittest.TestCase):
    def test_cli_imports_watched_youtube_events_with_private_video_ids(self):
        html = export_html(
            activity_card(
                "YouTube",
                """
                Watched&nbsp;<a href="https://www.youtube.com/watch?v=abc123">Private title</a><br>
                <a href="https://www.youtube.com/channel/private_channel">Private Channel</a><br>
                6 Jun 2026, 08:53:12 CEST<br>
                """,
            )
            + activity_card(
                "YouTube Music",
                """
                Watched&nbsp;<a href="https://music.youtube.com/watch?v=music123">Private song</a><br>
                6 Jun 2026, 09:00:00 CEST<br>
                """,
            )
            + activity_card(
                "YouTube",
                """
                Viewed&nbsp;<a href="https://www.youtube.com/post/private_post">Private post</a><br>
                6 Jun 2026, 10:00:00 CEST<br>
                """,
            )
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            input_path = tmp / "watch-history.html"
            database_path = tmp / "youtube_usage.v3.sqlite"
            input_path.write_text(html, encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "backend" / "scripts" / "import_youtube_usage_sql.py"),
                    "--input",
                    str(input_path),
                    "--database",
                    str(database_path),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            with closing(sqlite3.connect(database_path)) as connection:
                rows = connection.execute(
                    """
                    SELECT person_id, platform, product, event_type, watched_at, video_id
                    FROM watch_events
                    ORDER BY watched_at
                    """
                ).fetchall()
                video_rows = connection.execute(
                    "SELECT video_id, duration_seconds FROM video_metadata"
                ).fetchall()

        self.assertEqual(
            rows,
            [
                (
                    "local_user",
                    "youtube",
                    "youtube",
                    "watched",
                    "2026-06-06T08:53:12+02:00",
                    "abc123",
                )
            ],
        )
        self.assertEqual(video_rows, [])
