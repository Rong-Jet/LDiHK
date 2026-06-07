#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.youtube_sql import DEFAULT_SQLITE_PATH, enrich_youtube_durations


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Enrich v3 YouTube SQLite metadata with YouTube video durations."
    )
    parser.add_argument("--database", default=str(DEFAULT_SQLITE_PATH))
    parser.add_argument("--env-file")
    parser.add_argument("--max-duration-seconds", type=int, default=5400)
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()

    summary = enrich_youtube_durations(
        database_path=Path(args.database),
        env_path=Path(args.env_file) if args.env_file else None,
        max_duration_seconds=args.max_duration_seconds,
        refresh=args.refresh,
    )
    print(
        "Enriched "
        f"{summary.successful_video_count} / "
        f"{summary.requested_video_count} videos"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
