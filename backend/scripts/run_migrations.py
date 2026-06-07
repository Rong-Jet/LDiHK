#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.db import DatabaseConfigError, DEFAULT_MIGRATIONS_DIR, run_migrations


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Postgres schema migrations.")
    parser.add_argument("--database-url", help="Defaults to DATABASE_URL.")
    parser.add_argument("--migrations-dir", default=str(DEFAULT_MIGRATIONS_DIR))
    args = parser.parse_args()

    try:
        applied = run_migrations(
            database_url=args.database_url,
            migrations_dir=Path(args.migrations_dir),
        )
    except DatabaseConfigError as error:
        parser.exit(2, f"{error}\n")

    if applied:
        for migration in applied:
            print(f"Applied {migration.name}")
    else:
        print("No pending migrations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
