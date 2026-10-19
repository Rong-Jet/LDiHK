#!/usr/bin/env python
"""Seed synthetic comparison profiles (see backend/synthetic_population.py).

Every row is marked synthetic (users/usage_events.is_synthetic, imports.
seed_run_id, one synthetic_seed_runs row per run) and never mixes with real
users. `--remove-all` deletes all of it.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from collections.abc import Collection
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend import synthetic_population as model
from backend.db import DatabaseConfigError, connect, run_migrations
from backend.synthetic_population import Persona


GENERATOR_VERSION = "synthetic_usage_sessions.v2"
DEFAULT_BATCH_SIZE = 1000
SYNTHETIC_BUCKET = "synthetic-seed"
SYNTHETIC_PLATFORMS = model.PLATFORMS
# Position of the platform in the event tuples built by generate_user_telemetry.
EVENT_PLATFORM_INDEX = 4

def seed_synthetic_usage(
    *,
    total_profiles: int,
    total_days: int,
    seed_run_name: str,
    random_seed: int | None = None,
    replace_seed_run: bool = False,
    batch_size: int = DEFAULT_BATCH_SIZE,
    run_schema_migrations: bool = True,
    platforms: Collection[str] | None = None,
) -> str:
    """Seed synthetic profiles; ``platforms`` keeps only those platforms' events.

    Profiles are generated the same way either way, so a YouTube-only seed has
    the same YouTube events as a full seed with the same random seed.
    """
    if total_profiles < 1:
        raise ValueError("total_profiles must be positive")
    if total_days < 1:
        raise ValueError("total_days must be positive")
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    if platforms is not None:
        platforms = frozenset(platforms)
        unknown = platforms - set(SYNTHETIC_PLATFORMS)
        if not platforms or unknown:
            raise ValueError(
                f"platforms must be some of {', '.join(SYNTHETIC_PLATFORMS)}"
            )

    rng = random.Random(random_seed)
    now = datetime.now(timezone.utc)
    seed_run_id = str(uuid4())
    config = {
        "total_profiles": total_profiles,
        "total_days": total_days,
        "random_seed": random_seed,
        "calibration": {
            "total_minutes_median": model.TOTAL_MINUTES_MEDIAN,
            "platform_share": model.PLATFORM_SHARE,
            "weekday_factors": model.WEEKDAY_FACTORS,
            "sessions_per_day": model.SESSIONS_PER_DAY,
        },
        "platforms": sorted(platforms) if platforms is not None else None,
    }

    connection = connect()
    try:
        if run_schema_migrations:
            run_migrations(connection)
        if replace_seed_run:
            _delete_seed_runs_by_name(connection, seed_run_name)
        connection.execute(
            """
            INSERT INTO synthetic_seed_runs (
                id,
                name,
                generator_version,
                profile_count,
                total_days,
                config_json,
                generated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s)
            """,
            (
                seed_run_id,
                seed_run_name,
                GENERATOR_VERSION,
                total_profiles,
                total_days,
                json.dumps(config, sort_keys=True),
                now,
            ),
        )

        seeded_events = 0
        for profile_index in range(total_profiles):
            clanker_number = profile_index + 1
            user_id = str(uuid4())
            import_id = str(uuid4())
            persona = generate_user_persona(rng)
            external_id = (
                f"synthetic-clanker-{seed_run_id[:8]}-{clanker_number:06d}"
            )
            created_at = now - timedelta(days=total_days + 1)
            events = generate_user_telemetry(
                rng,
                user_id=user_id,
                import_id=import_id,
                total_days=total_days,
                base_date=now,
                persona=persona,
                created_at=now,
            )
            if platforms is not None:
                events = [
                    event for event in events if event[EVENT_PLATFORM_INDEX] in platforms
                ]

            connection.execute(
                """
                INSERT INTO users (
                    id,
                    external_id,
                    is_synthetic,
                    age,
                    age_range,
                    sex,
                    age_bucket,
                    cohort,
                    created_at
                )
                VALUES (%s, %s, true, %s, %s, %s, %s, %s, %s)
                """,
                (
                    user_id,
                    external_id,
                    persona.age,
                    persona.age_range,
                    persona.sex,
                    persona.age_bucket,
                    persona.cohort,
                    created_at,
                ),
            )
            connection.execute(
                """
                INSERT INTO imports (
                    id,
                    user_id,
                    s3_bucket,
                    s3_key,
                    status,
                    started_at,
                    finished_at,
                    records_seen,
                    records_imported,
                    warnings_count,
                    created_at,
                    data_origin,
                    seed_run_id
                )
                VALUES (%s, %s, %s, %s, 'completed', %s, %s, %s, %s, 0, %s,
                        'synthetic_seed', %s)
                """,
                (
                    import_id,
                    user_id,
                    SYNTHETIC_BUCKET,
                    f"synthetic/{seed_run_name}/{external_id}.json",
                    now,
                    now,
                    len(events),
                    len(events),
                    now,
                    seed_run_id,
                ),
            )
            _insert_usage_events(connection, events, batch_size=batch_size)
            seeded_events += len(events)
            if clanker_number % 100 == 0 or clanker_number == total_profiles:
                print(f"Seeded {clanker_number}/{total_profiles} profiles, {seeded_events} events")

        connection.commit()
        return seed_run_id
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

def generate_user_persona(rng: random.Random) -> Persona:
    return model.generate_persona(rng)


def generate_user_telemetry(
    rng: random.Random,
    *,
    user_id: str,
    import_id: str,
    total_days: int,
    base_date: datetime,
    persona: Persona,
    created_at: datetime,
) -> list[tuple[object, ...]]:
    """usage_events rows for the `total_days` days before `base_date`.

    Times are generated as local clock times and stored as UTC, the clock the
    population benchmark compares on. Each row's duration_seconds is the time
    actually watched; the next item starts right after it.
    """
    first_day = (base_date - timedelta(days=total_days)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    items = model.generate_days(rng, persona, first_day=first_day, total_days=total_days)
    events: list[tuple[object, ...]] = []
    for sequence, item in enumerate(items, start=1):
        fingerprint = hashlib.sha256(
            f"{user_id}:{import_id}:{sequence}:{item.occurred_at.isoformat()}".encode("utf-8")
        ).hexdigest()
        events.append(
            (
                str(uuid4()),
                user_id,
                import_id,
                None,
                item.platform,
                item.product,
                item.event_type,
                item.occurred_at,
                item.video_id,
                None,
                None,
                None,
                "synthetic",
                fingerprint,
                created_at,
                item.watched_seconds,
                True,
            )
        )
    return events


def _insert_usage_events(
    connection,
    events: list[tuple[object, ...]],
    *,
    batch_size: int,
) -> None:
    if not events:
        return
    sql = """
        INSERT INTO usage_events (
            id,
            user_id,
            import_id,
            source_file_id,
            platform,
            product,
            event_type,
            occurred_at,
            video_id,
            channel_id,
            title_hash,
            search_query_hash,
            raw_status,
            event_fingerprint,
            created_at,
            duration_seconds,
            is_synthetic
        )
        VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
            decode(%s, 'hex'), decode(%s, 'hex'), %s, decode(%s, 'hex'),
            %s, %s, %s
        )
        ON CONFLICT (user_id, event_fingerprint) DO NOTHING
    """
    with connection.cursor() as cursor:
        for start in range(0, len(events), batch_size):
            cursor.executemany(sql, events[start : start + batch_size])


def _delete_seed_runs_by_name(connection, seed_run_name: str) -> None:
    rows = connection.execute(
        "SELECT id FROM synthetic_seed_runs WHERE name = %s",
        (seed_run_name,),
    ).fetchall()
    for row in rows:
        seed_run_id = row[0]
        user_rows = connection.execute(
            "SELECT user_id FROM imports WHERE seed_run_id = %s",
            (seed_run_id,),
        ).fetchall()
        user_ids = [user_row[0] for user_row in user_rows]
        connection.execute(
            """
            DELETE FROM usage_events
            WHERE import_id IN (
                SELECT id FROM imports WHERE seed_run_id = %s
            )
            """,
            (seed_run_id,),
        )
        connection.execute(
            "DELETE FROM imports WHERE seed_run_id = %s",
            (seed_run_id,),
        )
        for user_id in user_ids:
            connection.execute(
                "DELETE FROM users WHERE id = %s AND is_synthetic = true",
                (user_id,),
            )
        connection.execute(
            "DELETE FROM synthetic_seed_runs WHERE id = %s",
            (seed_run_id,),
        )


def remove_synthetic_usage(connection) -> dict[str, int]:
    """Delete every synthetic row (all seed runs); real data is never touched.

    Real users, imports and events always have is_synthetic = false and no
    seed_run_id, so these filters cannot match them.
    """
    deleted = {}
    for table, sql in (
        ("usage_events", "DELETE FROM usage_events WHERE is_synthetic = true"),
        ("imports", "DELETE FROM imports WHERE seed_run_id IS NOT NULL"),
        ("users", "DELETE FROM users WHERE is_synthetic = true"),
        ("synthetic_seed_runs", "DELETE FROM synthetic_seed_runs"),
    ):
        deleted[table] = connection.execute(sql).rowcount
    connection.commit()
    return deleted

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Seed raw synthetic multi-platform usage events into Postgres."
    )
    parser.add_argument("--profiles", type=int, default=5)
    parser.add_argument("--days", type=int, default=14)
    parser.add_argument("--seed-run-name", default="synthetic-population")
    parser.add_argument("--random-seed", type=int)
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument(
        "--replace-seed-run",
        action="store_true",
        help="Delete existing synthetic data for --seed-run-name before seeding.",
    )
    parser.add_argument(
        "--skip-migrations",
        action="store_true",
        help="Do not run pending migrations before seeding.",
    )
    parser.add_argument(
        "--platforms",
        help=(
            "Comma-separated platforms to keep, e.g. youtube (the population "
            f"page only reads YouTube). Default: all of {','.join(SYNTHETIC_PLATFORMS)}."
        ),
    )
    parser.add_argument(
        "--remove-all",
        action="store_true",
        help="Delete all synthetic data (every seed run) and exit without seeding.",
    )
    args = parser.parse_args()

    if args.remove_all:
        try:
            connection = connect()
        except DatabaseConfigError as error:
            print(str(error), file=sys.stderr)
            return 2
        try:
            deleted = remove_synthetic_usage(connection)
        finally:
            connection.close()
        print("Removed synthetic data: " + ", ".join(f"{table} {count}" for table, count in deleted.items()))
        return 0

    platforms = None
    if args.platforms:
        platforms = [name.strip().lower() for name in args.platforms.split(",") if name.strip()]

    try:
        seed_run_id = seed_synthetic_usage(
            total_profiles=args.profiles,
            total_days=args.days,
            seed_run_name=args.seed_run_name,
            random_seed=args.random_seed,
            replace_seed_run=args.replace_seed_run,
            batch_size=args.batch_size,
            run_schema_migrations=not args.skip_migrations,
            platforms=platforms,
        )
    except (DatabaseConfigError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 2

    print(f"Seed run complete: {seed_run_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
