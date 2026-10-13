#!/usr/bin/env python3
from __future__ import annotations

import argparse
import logging
import math
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.background import WorkerLoop, WorkerSignal, make_import_run_once
from backend.db import DatabaseConfigError, get_database_url


def main() -> int:
    load_dotenv()
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(description="Process queued S3 ZIP imports.")
    parser.add_argument("--database-url", help="Defaults to DATABASE_URL.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--once",
        action="store_true",
        help="Process at most one queued import and exit.",
    )
    mode.add_argument(
        "--drain",
        action="store_true",
        help="Process queued imports until the queue is empty, then exit.",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=float(os.environ.get("IMPORT_WORKER_POLL_INTERVAL_SECONDS") or 5.0),
        help="Seconds to wait between empty polls when running continuously.",
    )
    args = parser.parse_args()

    try:
        database_url = args.database_url or get_database_url()
    except DatabaseConfigError as error:
        parser.exit(2, f"{error}\n")

    run_once = make_import_run_once(database_url=database_url)
    if args.once:
        if not run_once():
            print("No queued imports")
        return 0
    if args.drain:
        processed = 0
        while run_once():
            processed += 1
        print(f"Processed {processed} imports; queue is empty")
        return 0

    # A standalone worker polls continuously, so it is always "active".
    WorkerLoop(
        "import",
        run_once,
        signal=WorkerSignal(active_window_seconds=math.inf),
        poll_interval_seconds=args.poll_interval,
    ).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
