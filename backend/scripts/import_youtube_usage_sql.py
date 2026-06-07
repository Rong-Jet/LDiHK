#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.youtube_sql import DEFAULT_SQLITE_PATH, import_youtube_usage_sql
from backend.youtube_usage import DEFAULT_INPUT_PATH, DEFAULT_PERSON_ID, DEFAULT_TIMEZONE


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Import local Google Takeout YouTube watch history into SQLite."
    )
    parser.add_argument("--input", default=str(DEFAULT_INPUT_PATH))
    parser.add_argument("--database", default=str(DEFAULT_SQLITE_PATH))
    parser.add_argument("--person-id", default=DEFAULT_PERSON_ID)
    parser.add_argument("--timezone", default=DEFAULT_TIMEZONE)
    args = parser.parse_args()

    summary = import_youtube_usage_sql(
        input_path=Path(args.input),
        database_path=Path(args.database),
        person_id=args.person_id,
        timezone=args.timezone,
    )
    print(
        "Imported "
        f"{summary.events_imported} watched YouTube events into "
        f"{summary.database_path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

