"""Population benchmark for POST /api/population.

Compares the requester's YouTube watch time with other people: other real
users whose history covers the requested days, plus (optionally) synthetic
profiles used as a weekday-aligned baseline. Days and hours are UTC so
everyone is measured on the same clock. Comparisons against fewer than
MIN_POPULATION_SIZE other people are refused, because they would reveal
individual usage.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal


POPULATION_SCHEMA_VERSION = "youtube_usage.population.v1"
YOUTUBE_PLATFORM = "youtube"


class PopulationValidationError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class PopulationRequest:
    start_date: date
    end_date: date
    include_synthetic: bool
    custom_percentile: int

    @property
    def day_count(self) -> int:
        return (self.end_date - self.start_date).days + 1


def validate_population_request(request_payload: object) -> PopulationRequest:
    if not isinstance(request_payload, dict):
        raise PopulationValidationError("invalid_request")

    platforms = request_payload.get("platforms", [YOUTUBE_PLATFORM])
    if platforms is None:
        platforms = [YOUTUBE_PLATFORM]
    if (
        not isinstance(platforms, list)
        or not platforms
        or not all(isinstance(platform, str) and platform for platform in platforms)
    ):
        raise PopulationValidationError("invalid_platforms")
    normalized_platforms = {platform.strip().lower() for platform in platforms}
    if normalized_platforms != {YOUTUBE_PLATFORM}:
        raise PopulationValidationError("unsupported_platform")

    start_date = _parse_date(request_payload.get("startDate"))
    end_date = _parse_date(request_payload.get("endDate"))
    if start_date > end_date:
        raise PopulationValidationError("invalid_date_range")

    include_synthetic = request_payload.get("includeSynthetic", True)
    if not isinstance(include_synthetic, bool):
        raise PopulationValidationError("invalid_include_synthetic")

    custom_percentile = request_payload.get("customPercentile", 90)
    if (
        isinstance(custom_percentile, bool)
        or not isinstance(custom_percentile, int)
        or custom_percentile < 1
        or custom_percentile > 99
    ):
        raise PopulationValidationError("invalid_custom_percentile")

    return PopulationRequest(
        start_date=start_date,
        end_date=end_date,
        include_synthetic=include_synthetic,
        custom_percentile=custom_percentile,
    )


def _parse_date(value: object) -> date:
    if not isinstance(value, str):
        raise PopulationValidationError("invalid_date_filter")
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise PopulationValidationError("invalid_date_filter") from error


# ---------------------------------------------------------------------------
# Population computation
# ---------------------------------------------------------------------------

# Never compare against fewer than this many other people: with a smaller
# group, percentiles and distributions would reveal individual usage.
MIN_POPULATION_SIZE = 5
REAL_USERS_SCOPE = "ue.is_synthetic = false AND u.is_synthetic = false"
SYNTHETIC_USERS_SCOPE = "ue.is_synthetic = true"


@dataclass
class _UsageProfile:
    """One person's watch time: hours per UTC day and seconds per UTC hour."""

    daily_hours: dict[date, float] = field(default_factory=dict)
    hourly_seconds: dict[int, float] = field(default_factory=dict)


@dataclass(frozen=True)
class _PopulationMember:
    profile: _UsageProfile
    # Days this member counts on (a zero means "no watching that day").
    covered_days: int
    # Real members: their days inside the range. Synthetic: their window.
    first_day: date
    last_day: date
    synthetic: bool


def query_youtube_population(
    connection,
    request_payload: object,
    *,
    ldihk_id: str,
) -> dict[str, object]:
    request = validate_population_request(request_payload)

    requester_id = _fetch_requester_id(connection, ldihk_id)
    real_profiles = (
        _fetch_usage_profiles(
            connection,
            scope=REAL_USERS_SCOPE,
            start_date=request.start_date,
            end_date=request.end_date,
            marker="population_real_usage",
        )
        if requester_id is not None
        else {}
    )
    requester = real_profiles.pop(requester_id, None) if requester_id else None
    if requester is None or not requester.daily_hours:
        return {
            "schema_version": POPULATION_SCHEMA_VERSION,
            "ready": False,
            "reason": "no_user_data",
            "message": "No YouTube watch history in the selected date range.",
        }

    members = _real_members(connection, real_profiles, request, exclude_user_id=requester_id)
    baseline: tuple[date, date] | None = None
    if request.include_synthetic:
        baseline = _fetch_synthetic_window(connection)
        if baseline is not None:
            members.extend(_synthetic_members(connection, baseline))

    if len(members) < MIN_POPULATION_SIZE:
        return {
            "schema_version": POPULATION_SCHEMA_VERSION,
            "ready": False,
            "reason": "insufficient_population",
            "populationSize": len(members),
            "minPopulationSize": MIN_POPULATION_SIZE,
            "message": (
                f"Fewer than {MIN_POPULATION_SIZE} other people have YouTube data "
                "for this range, so a comparison would reveal individual usage."
                + ("" if request.include_synthetic else " Turn on the synthetic population to compare.")
            ),
        }

    days = [request.start_date + timedelta(days=offset) for offset in range(request.day_count)]
    user_daily_average = sum(requester.daily_hours.get(day, 0.0) for day in days) / request.day_count
    member_averages = [_average_daily_hours(member) for member in members]

    return {
        "schema_version": POPULATION_SCHEMA_VERSION,
        "ready": True,
        "dataset": "youtube_usage",
        "platforms": [YOUTUBE_PLATFORM],
        "userPercentile": _percentile_rank(user_daily_average, member_averages),
        "userDailyAverageHours": round(user_daily_average, 2),
        "includeSynthetic": request.include_synthetic,
        "customPercentile": request.custom_percentile,
        "populationSize": len(members),
        "syntheticBaseline": (
            {"startDate": baseline[0].isoformat(), "endDate": baseline[1].isoformat()}
            if baseline is not None
            else None
        ),
        "distribution": _distribution_payload(member_averages),
        "deciles": _deciles_payload(days, requester, members, baseline, request.custom_percentile),
        "hourlyAverages": _hourly_payload(requester, members, request.day_count),
    }


def _fetch_requester_id(connection, ldihk_id: str) -> str | None:
    rows = _fetch_rows(
        connection,
        """
            /* population_requester */
            SELECT id::text AS user_id
            FROM users
            WHERE external_id = %s
              AND is_synthetic = false
        """,
        [ldihk_id],
    )
    return str(rows[0]["user_id"]) if rows else None


def _fetch_usage_profiles(
    connection,
    *,
    scope: str,
    start_date: date,
    end_date: date,
    marker: str,
) -> dict[str, _UsageProfile]:
    """Per-user daily hours and hourly seconds in one scan of the events."""
    rows = _fetch_rows(
        connection,
        f"""
            /* {marker} */
            WITH {_clipped_events_cte(scope)},
            per_event AS (
                SELECT
                    user_id,
                    (occurred_at AT TIME ZONE 'UTC')::date AS watch_date,
                    EXTRACT(HOUR FROM occurred_at AT TIME ZONE 'UTC')::int AS watch_hour,
                    estimated_watch_seconds
                FROM events_with_duration
            )
            SELECT
                user_id::text AS user_id,
                to_char(watch_date, 'YYYY-MM-DD') AS date,
                watch_hour AS hour,
                COALESCE(SUM(estimated_watch_seconds), 0)::numeric AS seconds
            FROM per_event
            GROUP BY GROUPING SETS ((user_id, watch_date), (user_id, watch_hour))
        """,
        [start_date.isoformat(), end_date.isoformat()],
    )
    profiles: dict[str, _UsageProfile] = {}
    for row in rows:
        profile = profiles.setdefault(str(row["user_id"]), _UsageProfile())
        seconds = _float(row.get("seconds"))
        if row.get("date") is not None:
            profile.daily_hours[date.fromisoformat(str(row["date"]))] = seconds / 3600
        elif row.get("hour") is not None:
            profile.hourly_seconds[_int(row["hour"])] = seconds
    return profiles


def _real_members(
    connection,
    profiles: dict[str, _UsageProfile],
    request: PopulationRequest,
    *,
    exclude_user_id: str,
) -> list[_PopulationMember]:
    """Other real users whose watch history overlaps the requested range.

    Someone counts on a day inside their own history even if they watched
    nothing that day (0 hours), but not on days before their export starts or
    after it ends.
    """
    rows = _fetch_rows(
        connection,
        """
            /* population_real_coverage */
            SELECT
                ue.user_id::text AS user_id,
                to_char(MIN(ue.occurred_at AT TIME ZONE 'UTC')::date, 'YYYY-MM-DD') AS first_date,
                to_char(MAX(ue.occurred_at AT TIME ZONE 'UTC')::date, 'YYYY-MM-DD') AS last_date
            FROM usage_events ue
            JOIN users u ON u.id = ue.user_id
            WHERE ue.is_synthetic = false
              AND u.is_synthetic = false
              AND ue.platform = 'youtube'
              AND ue.event_type = 'watch'
              AND ue.occurred_at IS NOT NULL
            GROUP BY ue.user_id
        """,
        [],
    )
    members: list[_PopulationMember] = []
    for row in rows:
        user_id = str(row["user_id"])
        if user_id == exclude_user_id:
            continue
        first = max(date.fromisoformat(str(row["first_date"])), request.start_date)
        last = min(date.fromisoformat(str(row["last_date"])), request.end_date)
        if first > last:
            continue
        members.append(
            _PopulationMember(
                profile=profiles.get(user_id, _UsageProfile()),
                covered_days=(last - first).days + 1,
                first_day=first,
                last_day=last,
                synthetic=False,
            )
        )
    return members


def _fetch_synthetic_window(connection) -> tuple[date, date] | None:
    rows = _fetch_rows(
        connection,
        """
            /* population_synthetic_window */
            SELECT
                to_char(MIN(occurred_at AT TIME ZONE 'UTC')::date, 'YYYY-MM-DD') AS first_date,
                to_char(MAX(occurred_at AT TIME ZONE 'UTC')::date, 'YYYY-MM-DD') AS last_date
            FROM usage_events
            WHERE is_synthetic = true
              AND platform = 'youtube'
              AND event_type = 'watch'
        """,
        [],
    )
    if not rows or rows[0].get("first_date") is None:
        return None
    return (
        date.fromisoformat(str(rows[0]["first_date"])),
        date.fromisoformat(str(rows[0]["last_date"])),
    )


def _synthetic_members(connection, window: tuple[date, date]) -> list[_PopulationMember]:
    """Synthetic profiles over their whole seeded window.

    The seed only covers the days around when it ran. Treating it as a
    weekday-aligned baseline (see _baseline_day) lets it serve any requested
    date range instead of only that window.
    """
    profiles = _fetch_usage_profiles(
        connection,
        scope=SYNTHETIC_USERS_SCOPE,
        start_date=window[0],
        end_date=window[1],
        marker="population_synthetic_usage",
    )
    covered_days = (window[1] - window[0]).days + 1
    return [
        _PopulationMember(
            profile=profile,
            covered_days=covered_days,
            first_day=window[0],
            last_day=window[1],
            synthetic=True,
        )
        for profile in profiles.values()
    ]


def _baseline_day(day: date, window: tuple[date, date]) -> date:
    """Map a date onto the synthetic window, keeping the weekday if possible."""
    start, end = window
    if start <= day <= end:
        return day
    length = (end - start).days + 1
    cycle = length - length % 7 if length >= 7 else length
    cycle_start = end - timedelta(days=cycle - 1)
    return cycle_start + timedelta(days=(day - cycle_start).days % cycle)


def _member_hours_on(member: _PopulationMember, day: date, baseline: tuple[date, date] | None) -> float | None:
    if member.synthetic:
        if baseline is None:
            return None
        return member.profile.daily_hours.get(_baseline_day(day, baseline), 0.0)
    if member.first_day <= day <= member.last_day:
        return member.profile.daily_hours.get(day, 0.0)
    return None


def _average_daily_hours(member: _PopulationMember) -> float:
    total = sum(
        hours
        for day, hours in member.profile.daily_hours.items()
        if member.first_day <= day <= member.last_day
    )
    return total / max(1, member.covered_days)


def _percentile(sorted_values: list[float], fraction: float) -> float:
    """Linear interpolation, matching Postgres percentile_cont."""
    if not sorted_values:
        return 0.0
    position = fraction * (len(sorted_values) - 1)
    lower = int(position)
    upper = min(lower + 1, len(sorted_values) - 1)
    weight = position - lower
    return sorted_values[lower] + (sorted_values[upper] - sorted_values[lower]) * weight


def _deciles_payload(
    days: list[date],
    requester: _UsageProfile,
    members: list[_PopulationMember],
    baseline: tuple[date, date] | None,
    custom_percentile: int,
) -> list[dict[str, object]]:
    payload: list[dict[str, object]] = []
    for day in days:
        values = sorted(
            hours
            for member in members
            if (hours := _member_hours_on(member, day, baseline)) is not None
        )
        payload.append(
            {
                "date": day.isoformat(),
                "user": round(requester.daily_hours.get(day, 0.0), 2),
                "median": round(_percentile(values, 0.5), 2),
                "top10": round(_percentile(values, 0.9), 2),
                "bottom10": round(_percentile(values, 0.1), 2),
                "customPercentileHours": round(_percentile(values, custom_percentile / 100), 2),
            }
        )
    return payload


def _hourly_payload(
    requester: _UsageProfile,
    members: list[_PopulationMember],
    day_count: int,
) -> list[dict[str, object]]:
    payload: list[dict[str, object]] = []
    for hour in range(24):
        member_rates = [
            member.profile.hourly_seconds.get(hour, 0.0) / max(1, member.covered_days) / 3600
            for member in members
        ]
        population_avg = sum(member_rates) / len(member_rates) if member_rates else 0.0
        payload.append(
            {
                "hour": f"{hour:02d}:00",
                "populationAvg": round(population_avg, 3),
                "userAvg": round(requester.hourly_seconds.get(hour, 0.0) / day_count / 3600, 3),
            }
        )
    return payload


def _distribution_payload(member_averages: list[float]) -> list[dict[str, object]]:
    density = [0] * 25
    for average in member_averages:
        density[int(min(24, max(0, average)))] += 1
    return [{"hours": float(hour), "density": density[hour]} for hour in range(25)]


def _clipped_events_cte(population_scope: str) -> str:
    return f"""
        clipped_events AS (
            SELECT
                ue.user_id,
                ue.occurred_at,
                ue.platform,
                ue.event_type,
                COALESCE(
                    ue.duration_seconds::numeric,
                    CASE
                        WHEN yv.availability_status = 'available'
                         AND yv.duration_seconds IS NOT NULL
                        THEN yv.duration_seconds::numeric
                        ELSE NULL::numeric
                    END,
                    CASE
                        WHEN ue.product = 'shorts' THEN 60::numeric
                        ELSE 600::numeric
                    END
                ) AS base_duration,
                (
                    SELECT MIN(next_ue.occurred_at)
                    FROM usage_events next_ue
                    WHERE next_ue.user_id = ue.user_id
                      AND next_ue.platform = ue.platform
                      AND next_ue.event_type = 'watch'
                      AND next_ue.occurred_at IS NOT NULL
                      AND ue.occurred_at IS NOT NULL
                      AND next_ue.occurred_at > ue.occurred_at
                ) AS next_occurred_at
            FROM usage_events ue
            JOIN users u ON u.id = ue.user_id
            LEFT JOIN youtube_videos yv ON yv.video_id = ue.video_id
            WHERE {population_scope}
              AND ue.platform = 'youtube'
              AND ue.event_type = 'watch'
              AND ue.occurred_at >= (%s::date::timestamp AT TIME ZONE 'UTC')
              AND ue.occurred_at < ((%s::date + INTERVAL '1 day')::timestamp AT TIME ZONE 'UTC')
        ),
        events_with_duration AS (
            SELECT
                user_id,
                occurred_at,
                platform,
                event_type,
                CASE
                    WHEN base_duration IS NOT NULL
                     AND event_type = 'watch'
                     AND occurred_at IS NOT NULL
                     AND next_occurred_at IS NOT NULL
                    THEN LEAST(
                        base_duration,
                        GREATEST(
                            0::numeric,
                            EXTRACT(EPOCH FROM next_occurred_at - occurred_at)::numeric
                        )
                    )
                    ELSE base_duration
                END AS estimated_watch_seconds
            FROM clipped_events
        )
    """


def _percentile_rank(user_average: float, population_averages: list[float]) -> int:
    if not population_averages:
        return 100
    lower_or_equal = sum(1 for value in population_averages if value <= user_average)
    return round((lower_or_equal / len(population_averages)) * 100)


def _fetch_rows(connection, sql: str, parameters: list[object]) -> list[dict[str, object]]:
    cursor = connection.execute(_compact_sql(sql), parameters)
    return _cursor_rows(cursor)


def _cursor_rows(cursor) -> list[dict[str, object]]:
    raw_rows = cursor.fetchall()
    if not raw_rows:
        return []
    if isinstance(raw_rows[0], dict):
        return [_normalize_row(dict(row)) for row in raw_rows]

    columns = [_column_name(column) for column in cursor.description]
    return [_normalize_row(dict(zip(columns, row, strict=True))) for row in raw_rows]


def _column_name(column: object) -> str:
    name = getattr(column, "name", None)
    if name is not None:
        return str(name)
    return str(column[0])


def _normalize_row(row: dict[str, object]) -> dict[str, object]:
    return {key: _normalize_value(value) for key, value in row.items()}


def _normalize_value(value: object) -> object:
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    return value


def _float(value: object) -> float:
    if value is None:
        return 0.0
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, int | float):
        return float(value)
    return float(str(value))


def _int(value: object) -> int:
    if value is None:
        return 0
    if isinstance(value, Decimal):
        return int(value)
    if isinstance(value, int):
        return value
    return int(str(value))


def _compact_sql(sql: str) -> str:
    return " ".join(sql.split())
