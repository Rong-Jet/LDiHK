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

from backend.background import WorkerLoop, WorkerSignal, make_enrichment_run_once
from backend.db import DatabaseConfigError, get_database_url
from backend.enrichment.youtube_api import MAX_VIDEO_IDS_PER_REQUEST


def main() -> int:
    load_dotenv()
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(
        description="Process queued YouTube duration enrichment jobs."
    )
    parser.add_argument("--database-url", help="Defaults to DATABASE_URL.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--once",
        action="store_true",
        help="Process at most one enrichment job or repair batch and exit.",
    )
    mode.add_argument(
        "--drain",
        action="store_true",
        help="Process work until there is none left, then exit.",
    )
    parser.add_argument(
        "--repair",
        action="store_true",
        help="Scan watch events for missing or retriable duration rows.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        help="YouTube API videos.list batch size, max 50. "
        "Defaults to ENRICHMENT_BATCH_SIZE or 50.",
    )
    parser.add_argument(
        "--max-duration-seconds",
        type=int,
        help="Cap enriched durations at this many seconds. "
        "Defaults to YOUTUBE_MAX_DURATION_SECONDS or 5400.",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=float(os.environ.get("ENRICHMENT_POLL_INTERVAL_SECONDS") or 30.0),
        help="Seconds to wait between empty polls when running continuously.",
    )
    parser.add_argument(
        "--retry-base-seconds",
        type=int,
        help="Base retry backoff after API failures. "
        "Defaults to ENRICHMENT_RETRY_BASE_SECONDS or 300.",
    )
    args = parser.parse_args()

    if args.batch_size is not None and not 1 <= args.batch_size <= MAX_VIDEO_IDS_PER_REQUEST:
        parser.error("--batch-size must be between 1 and 50")

    environ = dict(os.environ)
    for name, value in (
        ("ENRICHMENT_BATCH_SIZE", args.batch_size),
        ("YOUTUBE_MAX_DURATION_SECONDS", args.max_duration_seconds),
        ("ENRICHMENT_RETRY_BASE_SECONDS", args.retry_base_seconds),
    ):
        if value is not None:
            environ[name] = str(value)

    try:
        database_url = args.database_url or get_database_url()
    except DatabaseConfigError as error:
        parser.exit(2, f"{error}\n")

    run_once = make_enrichment_run_once(
        database_url=database_url,
        repair=args.repair,
        environ=environ,
    )
    if args.once:
        if not run_once():
            print("No enrichment work")
        return 0
    if args.drain:
        processed = 0
        while run_once():
            processed += 1
        print(f"Processed {processed} enrichment batches; nothing left to do")
        return 0

    WorkerLoop(
        "enrichment",
        run_once,
        signal=WorkerSignal(active_window_seconds=math.inf),
        poll_interval_seconds=args.poll_interval,
    ).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
