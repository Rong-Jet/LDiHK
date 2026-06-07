from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

from backend.ingestion.zip_safety import (
    UnsafeZipEntryError,
    iter_safe_zip_members,
    safe_zip_member_path,
)


class ZipSafetyTests(unittest.TestCase):
    def test_normalizes_safe_zip_member_paths(self):
        self.assertEqual(
            safe_zip_member_path(
                r"Takeout\YouTube and YouTube Music\watch-history.html"
            ),
            "Takeout/YouTube and YouTube Music/watch-history.html",
        )
        self.assertEqual(
            safe_zip_member_path("./Takeout//history/watch-history.html"),
            "Takeout/history/watch-history.html",
        )

    def test_rejects_path_traversal_members(self):
        unsafe_paths = [
            "../evil.txt",
            "Takeout/../evil.txt",
            "/absolute/evil.txt",
            r"C:\takeout\evil.txt",
            "Takeout/\x00evil.txt",
        ]

        for unsafe_path in unsafe_paths:
            with self.subTest(unsafe_path=unsafe_path):
                with self.assertRaises(UnsafeZipEntryError):
                    safe_zip_member_path(unsafe_path)

    def test_iterates_files_and_skips_directories(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            zip_path = Path(tmpdir) / "takeout.zip"
            with ZipFile(zip_path, "w") as zip_file:
                zip_file.writestr("Takeout/", "")
                zip_file.writestr("Takeout/watch-history.html", b"history")

            with ZipFile(zip_path) as zip_file:
                members = list(iter_safe_zip_members(zip_file))

        self.assertEqual(
            [member.source_path for member in members],
            ["Takeout/watch-history.html"],
        )


if __name__ == "__main__":
    unittest.main()
