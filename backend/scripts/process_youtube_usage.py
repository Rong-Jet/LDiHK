#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.youtube_usage import (
    DEFAULT_INPUT_PATH,
    DEFAULT_OUTPUT_PATH,
    DEFAULT_PERSON_ID,
    DEFAULT_TIMEZONE,
    process_usage_file,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Process local Google Takeout YouTube watch history HTML."
    )
    parser.add_argument("--input", default=str(DEFAULT_INPUT_PATH))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_PATH))
    parser.add_argument("--person-id", default=DEFAULT_PERSON_ID)
    parser.add_argument("--timezone", default=DEFAULT_TIMEZONE)
    args = parser.parse_args()

    payload = process_usage_file(
        input_path=Path(args.input),
        output_path=Path(args.output),
        person_id=args.person_id,
        timezone=args.timezone,
    )
    print(
        "Processed "
        f"{payload['quality']['records_emitted']} / "
        f"{payload['quality']['records_seen']} records"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
