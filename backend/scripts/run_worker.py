#!/usr/bin/env python3
from __future__ import annotations

import argparse
from contextlib import closing
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.db import DatabaseConfigError, connect
from backend.ingestion.s3 import Boto3S3Client
from backend.ingestion.worker import (
    IMPORT_STATUS_IDLE,
    PostgresImportRepository,
    S3ZipImportWorker,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Process queued S3 ZIP imports.")
    parser.add_argument("--database-url", help="Defaults to DATABASE_URL.")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Process at most one queued import and exit.",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=5.0,
        help="Seconds to wait between empty polls when running continuously.",
    )
    args = parser.parse_args()

    try:
        with closing(connect(args.database_url)) as connection:
            worker = S3ZipImportWorker(
                repository=PostgresImportRepository(connection),
                s3_client=Boto3S3Client(),
            )
            while True:
                result = worker.process_one()
                if result.status == IMPORT_STATUS_IDLE:
                    print("No queued imports")
                    if args.once:
                        return 0
                    time.sleep(args.poll_interval)
                    continue

                print(
                    f"Import {result.import_id} {result.status}: "
                    f"{result.records_imported}/{result.records_seen} records, "
                    f"{result.warnings_count} warnings"
                )
                if args.once:
                    return 0
    except DatabaseConfigError as error:
        parser.exit(2, f"{error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
