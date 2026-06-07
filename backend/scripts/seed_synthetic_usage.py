#!/usr/bin/env python
from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.db import DatabaseConfigError, connect, run_migrations


GENERATOR_VERSION = "synthetic_usage_raw_events.v1"
DEFAULT_BATCH_SIZE = 1000
SYNTHETIC_BUCKET = "synthetic-seed"


def normalize_weights(weights: list[float]) -> list[float]:
    total = sum(weights)
    return [weight / total for weight in weights]


PLATFORM_WEIGHTS = {
    "tiktok": normalize_weights(
        [0.05, 0.04, 0.02, 0.01, 0.01, 0.01, 0.02, 0.03, 0.03, 0.03, 0.04, 0.04,
         0.05, 0.05, 0.06, 0.07, 0.08, 0.08, 0.09, 0.10, 0.10, 0.10, 0.09, 0.08]
    ),
    "instagram": normalize_weights(
        [0.02, 0.01, 0.01, 0.01, 0.01, 0.02, 0.03, 0.05, 0.07, 0.08, 0.08, 0.09,
         0.10, 0.09, 0.08, 0.07, 0.06, 0.07, 0.08, 0.08, 0.07, 0.06, 0.05, 0.04]
    ),
    "youtube_shorts": normalize_weights(
        [0.02, 0.01, 0.01, 0.01, 0.01, 0.02, 0.04, 0.06, 0.06, 0.05, 0.05, 0.05,
         0.06, 0.06, 0.07, 0.08, 0.09, 0.10, 0.10, 0.09, 0.08, 0.06, 0.05, 0.04]
    ),
    "youtube_long": normalize_weights(
        [0.03, 0.02, 0.01, 0.01, 0.01, 0.01, 0.02, 0.03, 0.04, 0.03, 0.03, 0.04,
         0.04, 0.04, 0.05, 0.06, 0.08, 0.10, 0.12, 0.14, 0.14, 0.12, 0.09, 0.06]
    ),
    "spotify": normalize_weights(
        [0.02, 0.01, 0.01, 0.01, 0.01, 0.02, 0.04, 0.08, 0.10, 0.09, 0.08, 0.07,
         0.07, 0.07, 0.07, 0.08, 0.09, 0.09, 0.06, 0.05, 0.04, 0.03, 0.03, 0.03]
    ),
    "linkedin": normalize_weights(
        [0.005, 0.005, 0.005, 0.005, 0.005, 0.01, 0.03, 0.06, 0.10, 0.12, 0.12,
         0.10, 0.08, 0.08, 0.10, 0.08, 0.06, 0.05, 0.04, 0.03, 0.02, 0.01, 0.01, 0.01]
    ),
}

AFFINITY_MATRIX = {
    "adolescent_female": {
        "tiktok": 0.95,
        "instagram": 0.90,
        "spotify": 0.85,
        "youtube_shorts": 0.70,
        "youtube_long": 0.60,
        "linkedin": 0.00,
    },
    "adolescent_male": {
        "tiktok": 0.75,
        "instagram": 0.60,
        "spotify": 0.80,
        "youtube_shorts": 0.90,
        "youtube_long": 0.95,
        "linkedin": 0.00,
    },
    "adult_female": {
        "tiktok": 0.55,
        "instagram": 0.80,
        "spotify": 0.75,
        "youtube_shorts": 0.50,
        "youtube_long": 0.65,
        "linkedin": 0.55,
    },
    "adult_male": {
        "tiktok": 0.40,
        "instagram": 0.65,
        "spotify": 0.70,
        "youtube_shorts": 0.60,
        "youtube_long": 0.85,
        "linkedin": 0.65,
    },
    "older_female": {
        "tiktok": 0.15,
        "instagram": 0.55,
        "spotify": 0.35,
        "youtube_shorts": 0.20,
        "youtube_long": 0.75,
        "linkedin": 0.30,
    },
    "older_male": {
        "tiktok": 0.10,
        "instagram": 0.35,
        "spotify": 0.30,
        "youtube_shorts": 0.20,
        "youtube_long": 0.85,
        "linkedin": 0.45,
    },
}

DEFAULT_DURATIONS_SECONDS = {
    "youtube_shorts": 60,
    "youtube_long": 600,
    "tiktok": 60,
    "instagram": 60,
    "spotify": 120,
    "linkedin": 120,
}


@dataclass(frozen=True)
class Persona:
    age: int
    sex: str
    age_bucket: str
    cohort: str
    platforms: list[str]
    avg_daily_sessions: dict[str, int]
    usual_times_of_activity: dict[str, list[int]]


@dataclass(frozen=True)
class EventShape:
    platform: str
    product: str
    event_type: str
    duration_seconds: int
    video_id: str | None


def seed_synthetic_usage(
    *,
    total_profiles: int,
    total_days: int,
    seed_run_name: str,
    random_seed: int | None = None,
    replace_seed_run: bool = False,
    batch_size: int = DEFAULT_BATCH_SIZE,
    run_schema_migrations: bool = True,
) -> str:
    if total_profiles < 1:
        raise ValueError("total_profiles must be positive")
    if total_days < 1:
        raise ValueError("total_days must be positive")
    if batch_size < 1:
        raise ValueError("batch_size must be positive")

    rng = random.Random(random_seed)
    now = datetime.now(timezone.utc)
    seed_run_id = str(uuid4())
    config = {
        "total_profiles": total_profiles,
        "total_days": total_days,
        "random_seed": random_seed,
        "duration_defaults_seconds": DEFAULT_DURATIONS_SECONDS,
        "platform_weights": PLATFORM_WEIGHTS,
        "affinity_matrix": AFFINITY_MATRIX,
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

            connection.execute(
                """
                INSERT INTO users (
                    id,
                    external_id,
                    is_synthetic,
                    age,
                    sex,
                    age_bucket,
                    cohort,
                    created_at
                )
                VALUES (%s, %s, true, %s, %s, %s, %s, %s)
                """,
                (
                    user_id,
                    external_id,
                    persona.age,
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
            print(
                "Seeded "
                f"{external_id}: {len(events)} events "
                f"({clanker_number}/{total_profiles})"
            )

        connection.commit()
        return seed_run_id
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def generate_user_persona(rng: random.Random) -> Persona:
    age, sex, age_bucket, cohort = assign_demographics(rng)
    all_platforms = [
        "tiktok",
        "instagram",
        "youtube_shorts",
        "youtube_long",
        "spotify",
        "linkedin",
    ]
    active_platforms = [
        platform
        for platform in all_platforms
        if rng.random() < AFFINITY_MATRIX[cohort][platform]
    ]
    if not active_platforms:
        active_platforms = ["youtube_long"]

    avg_daily_sessions: dict[str, int] = {}
    usual_times_of_activity: dict[str, list[int]] = {}
    for platform in active_platforms:
        base = _base_sessions(cohort, platform)
        avg_daily_sessions[platform] = max(1, int(rng.gauss(base, base * 0.25)))
        usual_times_of_activity[platform] = rng.sample(
            _valid_hours(age_bucket),
            k=rng.choice([1, 2, 3]),
        )

    return Persona(
        age=age,
        sex=sex,
        age_bucket=age_bucket,
        cohort=cohort,
        platforms=active_platforms,
        avg_daily_sessions=avg_daily_sessions,
        usual_times_of_activity=usual_times_of_activity,
    )


def assign_demographics(rng: random.Random) -> tuple[int, str, str, str]:
    sex = rng.choice(["male", "female"])
    age_group_roll = rng.random()
    if age_group_roll < 0.20:
        age = rng.randint(13, 17)
        age_bucket = "adolescent"
    elif age_group_roll < 0.80:
        age = rng.randint(18, 49)
        age_bucket = "adult"
    else:
        age = rng.randint(50, 75)
        age_bucket = "older"
    return age, sex, age_bucket, f"{age_bucket}_{sex}"


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
    events: list[tuple[object, ...]] = []
    carryover_time: datetime | None = None
    event_sequence = 0

    for day_offset in range(total_days):
        current_day = base_date - timedelta(days=total_days - day_offset)
        is_weekend = current_day.weekday() >= 5
        weekend_mod = _weekend_modifier(persona.age_bucket, is_weekend)
        raw_events: list[dict[str, object]] = []

        for platform in persona.platforms:
            if platform == "linkedin" and is_weekend:
                continue
            daily_variance = rng.gauss(
                0,
                persona.avg_daily_sessions[platform] * 0.15,
            )
            sessions = max(
                0,
                int(
                    (persona.avg_daily_sessions[platform] + daily_variance)
                    * weekend_mod
                ),
            )
            for _ in range(sessions):
                raw_events.append(
                    {
                        "platform": platform,
                        "occurred_at": _event_timestamp(rng, current_day, persona, platform),
                    }
                )

        raw_events.sort(key=lambda event: event["occurred_at"])
        for index, event in enumerate(raw_events):
            min_gap = timedelta(minutes=rng.randint(5, 15))
            occurred_at = event["occurred_at"]
            if not isinstance(occurred_at, datetime):
                continue
            if index == 0:
                if carryover_time and occurred_at < carryover_time + min_gap:
                    event["occurred_at"] = carryover_time + min_gap
            else:
                previous = raw_events[index - 1]["occurred_at"]
                if isinstance(previous, datetime) and occurred_at < previous + min_gap:
                    event["occurred_at"] = previous + min_gap

        if raw_events and isinstance(raw_events[-1]["occurred_at"], datetime):
            carryover_time = raw_events[-1]["occurred_at"]

        for event in raw_events:
            activity_platform = str(event["platform"])
            occurred_at = event["occurred_at"]
            if not isinstance(occurred_at, datetime):
                continue
            event_sequence += 1
            shape = event_shape(activity_platform, rng)
            fingerprint = hashlib.sha256(
                f"{user_id}:{import_id}:{event_sequence}:{occurred_at.isoformat()}".encode(
                    "utf-8"
                )
            ).hexdigest()
            events.append(
                (
                    str(uuid4()),
                    user_id,
                    import_id,
                    None,
                    shape.platform,
                    shape.product,
                    shape.event_type,
                    occurred_at,
                    shape.video_id,
                    None,
                    None,
                    None,
                    "synthetic",
                    fingerprint,
                    created_at,
                    shape.duration_seconds,
                    True,
                )
            )

    return events


def event_shape(activity_platform: str, rng: random.Random) -> EventShape:
    if activity_platform == "youtube_shorts":
        return EventShape(
            platform="youtube",
            product="shorts",
            event_type="watch",
            duration_seconds=DEFAULT_DURATIONS_SECONDS[activity_platform],
            video_id=f"synthetic_youtube_short_{rng.randint(10000, 99999)}",
        )
    if activity_platform == "youtube_long":
        return EventShape(
            platform="youtube",
            product="long",
            event_type="watch",
            duration_seconds=DEFAULT_DURATIONS_SECONDS[activity_platform],
            video_id=f"synthetic_youtube_long_{rng.randint(10000, 99999)}",
        )
    if activity_platform == "tiktok":
        return EventShape(
            platform="tiktok",
            product="shorts",
            event_type="watch",
            duration_seconds=DEFAULT_DURATIONS_SECONDS[activity_platform],
            video_id=f"synthetic_tiktok_{rng.randint(10000, 99999)}",
        )
    if activity_platform == "spotify":
        return EventShape(
            platform="spotify",
            product="audio",
            event_type="listen",
            duration_seconds=DEFAULT_DURATIONS_SECONDS[activity_platform],
            video_id=None,
        )
    if activity_platform == "linkedin":
        return EventShape(
            platform="linkedin",
            product="feed",
            event_type="activity",
            duration_seconds=DEFAULT_DURATIONS_SECONDS[activity_platform],
            video_id=None,
        )
    return EventShape(
        platform="instagram",
        product="feed",
        event_type="activity",
        duration_seconds=DEFAULT_DURATIONS_SECONDS["instagram"],
        video_id=None,
    )


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
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
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


def _base_sessions(cohort: str, platform: str) -> int:
    base_by_cohort = {
        "adolescent_female": {
            "tiktok": 15,
            "instagram": 15,
            "youtube_shorts": 10,
            "youtube_long": 2,
            "spotify": 5,
            "linkedin": 1,
        },
        "adolescent_male": {
            "tiktok": 10,
            "instagram": 8,
            "youtube_shorts": 12,
            "youtube_long": 5,
            "spotify": 5,
            "linkedin": 1,
        },
        "adult_female": {
            "tiktok": 8,
            "instagram": 12,
            "youtube_shorts": 5,
            "youtube_long": 3,
            "spotify": 6,
            "linkedin": 2,
        },
        "adult_male": {
            "tiktok": 6,
            "instagram": 8,
            "youtube_shorts": 6,
            "youtube_long": 4,
            "spotify": 6,
            "linkedin": 3,
        },
        "older_female": {
            "tiktok": 2,
            "instagram": 6,
            "youtube_shorts": 2,
            "youtube_long": 4,
            "spotify": 3,
            "linkedin": 1,
        },
        "older_male": {
            "tiktok": 1,
            "instagram": 3,
            "youtube_shorts": 2,
            "youtube_long": 5,
            "spotify": 3,
            "linkedin": 2,
        },
    }
    return base_by_cohort[cohort][platform]


def _valid_hours(age_bucket: str) -> list[int]:
    if age_bucket == "adolescent":
        return [7, 15, 16, 17, 20, 21, 22, 23]
    if age_bucket == "adult":
        return [7, 8, 12, 17, 18, 20, 21, 22]
    return [6, 7, 8, 12, 18, 19, 20]


def _weekend_modifier(age_bucket: str, is_weekend: bool) -> float:
    if not is_weekend:
        return 1.0
    if age_bucket == "adolescent":
        return 1.6
    if age_bucket == "older":
        return 1.1
    return 1.3


def _event_timestamp(
    rng: random.Random,
    current_day: datetime,
    persona: Persona,
    platform: str,
) -> datetime:
    if rng.random() < 0.80:
        chosen_time = rng.choice(persona.usual_times_of_activity[platform])
        base_ts = current_day.replace(hour=chosen_time, minute=0, second=0, microsecond=0)
        return base_ts + timedelta(
            minutes=rng.gauss(0, 45),
            seconds=rng.randint(-30, 30),
        )
    hour = rng.choices(range(24), weights=PLATFORM_WEIGHTS[platform], k=1)[0]
    return current_day.replace(
        hour=hour,
        minute=rng.randint(0, 59),
        second=rng.randint(0, 59),
        microsecond=0,
    )


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
    args = parser.parse_args()

    try:
        seed_run_id = seed_synthetic_usage(
            total_profiles=args.profiles,
            total_days=args.days,
            seed_run_name=args.seed_run_name,
            random_seed=args.random_seed,
            replace_seed_run=args.replace_seed_run,
            batch_size=args.batch_size,
            run_schema_migrations=not args.skip_migrations,
        )
    except (DatabaseConfigError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 2

    print(f"Seed run complete: {seed_run_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
