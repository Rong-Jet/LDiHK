#!/usr/bin/env python3
from __future__ import annotations

import argparse
from contextlib import closing
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.db import DatabaseConfigError, connect
from backend.enrichment.durations import (
    DEFAULT_MAX_DURATION_SECONDS,
    ENRICHMENT_WORKER_STATUS_IDLE,
    PostgresEnrichmentRepository,
    YoutubeDurationEnrichmentWorker,
)
from backend.enrichment.youtube_api import (
    MAX_VIDEO_IDS_PER_REQUEST,
    YouTubeDataApiClient,
)


def main() -> int:
    load_dotenv()

    parser = argparse.ArgumentParser(
        description="Process queued YouTube duration enrichment jobs."
    )
    parser.add_argument("--database-url", help="Defaults to DATABASE_URL.")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Process at most one enrichment job or repair batch and exit.",
    )
    parser.add_argument(
        "--repair",
        action="store_true",
        help="Scan watch events for missing or retriable duration rows.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=_env_int("ENRICHMENT_BATCH_SIZE", MAX_VIDEO_IDS_PER_REQUEST),
        help="YouTube API videos.list batch size, max 50.",
    )
    parser.add_argument(
        "--max-duration-seconds",
        type=int,
        default=_env_int(
            "YOUTUBE_MAX_DURATION_SECONDS",
            DEFAULT_MAX_DURATION_SECONDS,
        ),
        help="Cap enriched durations at this many seconds.",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=_env_float("ENRICHMENT_POLL_INTERVAL_SECONDS", 30.0),
        help="Seconds to wait between empty polls when running continuously.",
    )
    parser.add_argument(
        "--retry-base-seconds",
        type=int,
        default=_env_int("ENRICHMENT_RETRY_BASE_SECONDS", 300),
        help="Base retry backoff after API failures.",
    )
    args = parser.parse_args()

    if args.batch_size < 1 or args.batch_size > MAX_VIDEO_IDS_PER_REQUEST:
        parser.error("--batch-size must be between 1 and 50")

    try:
        with closing(connect(args.database_url)) as connection:
            worker = YoutubeDurationEnrichmentWorker(
                repository=PostgresEnrichmentRepository(connection),
                client=YouTubeDataApiClient.from_env(),
                max_duration_seconds=args.max_duration_seconds,
                batch_size=args.batch_size,
                retry_base_seconds=args.retry_base_seconds,
            )
            while True:
                result = worker.repair_once() if args.repair else worker.process_one()
                if result.status == ENRICHMENT_WORKER_STATUS_IDLE:
                    print("No enrichment work")
                    if args.once:
                        return 0
                    time.sleep(args.poll_interval)
                    continue

                summary = result.summary
                if summary is None:
                    print(
                        f"Enrichment job {result.job_id} {result.status}: "
                        f"{result.error_message}"
                    )
                else:
                    target = (
                        f"job {result.job_id}"
                        if result.job_id is not None
                        else "repair batch"
                    )
                    print(
                        f"Enrichment {target} {result.status}: "
                        f"{summary.successful_video_count} available, "
                        f"{summary.unavailable_video_count} unavailable, "
                        f"{summary.failed_video_count} failed, "
                        f"{summary.api_call_count} API calls"
                    )
                if args.once:
                    return 0
    except DatabaseConfigError as error:
        parser.exit(2, f"{error}\n")


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name, "").strip()
    if not value:
        return default
    return int(value)


def _env_float(name: str, default: float) -> float:
    value = os.environ.get(name, "").strip()
    if not value:
        return default
    return float(value)


if __name__ == "__main__":
    raise SystemExit(main())
