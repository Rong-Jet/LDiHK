"""Population benchmark for POST /api/population.

Compares the requester's YouTube watch time with other people: other real
users whose history covers the requested days, plus (optionally) the
synthetic population, computed for exactly the requested days by
backend/procedural_population.py. Days and hours are UTC so everyone is
measured on the same clock. Comparisons against fewer than
MIN_POPULATION_SIZE other people are refused, because they would reveal
individual usage.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from decimal import Decimal

import numpy as np

from backend import procedural_population
from backend.demographics import AGE_RANGES, comparable_sex, neighbouring_ranges
from backend.query_api import DEFAULT_PLATFORM_DURATION_SECONDS, WATCH_EVENT_SQL, watch_seconds_sql


POPULATION_SCHEMA_VERSION = "youtube_usage.population.v1"
YOUTUBE_PLATFORM = "youtube"
# Platforms a user's own side can consist of (imported by the backend).
COMPARABLE_PLATFORMS = ("youtube", "instagram", "tiktok")
# "total": the population's total social media time; "matching": the
# population's time on the same platforms as the user's selection.
POPULATION_SOURCES = ("total", "matching")


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
    # "cohort": people of similar age range and sex (if the requester gave
    # them); "everyone": the whole population.
    compare_with: str = "everyone"
    platforms: tuple[str, ...] = (YOUTUBE_PLATFORM,)
    population_source: str = "matching"

    @property
    def comparison_platforms(self) -> tuple[str, ...]:
        """Platforms counted for the other people."""
        if self.population_source == "total":
            return procedural_population.SOCIAL_PLATFORMS
        return self.platforms

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
    if not normalized_platforms <= set(COMPARABLE_PLATFORMS):
        raise PopulationValidationError("unsupported_platform")
    selected = tuple(platform for platform in COMPARABLE_PLATFORMS if platform in normalized_platforms)

    population_source = request_payload.get("populationSource", "matching")
    if population_source not in POPULATION_SOURCES:
        raise PopulationValidationError("invalid_population_source")

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

    compare_with = request_payload.get("compareWith", "everyone")
    if compare_with not in ("cohort", "everyone"):
        raise PopulationValidationError("invalid_compare_with")

    return PopulationRequest(
        start_date=start_date,
        end_date=end_date,
        include_synthetic=include_synthetic,
        custom_percentile=custom_percentile,
        compare_with=compare_with,
        platforms=selected,
        population_source=population_source,
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
    # Real members: their days inside the range. Synthetic: the whole range.
    first_day: date
    last_day: date
    synthetic: bool
    user_id: str = ""
    age_range: str | None = None
    sex: str | None = None
    # Synthetic members: their row in the procedural DaySeries.
    series_row: int = -1


@dataclass(frozen=True)
class _Requester:
    user_id: str
    age_range: str | None
    sex: str | None


# A cohort is widened to neighbouring age ranges until it has this many
# people, so its percentiles are not dominated by a handful of profiles.
COHORT_TARGET_SIZE = 30


def select_comparison_group(
    members: list[_PopulationMember],
    *,
    age_range: str | None,
    sex: str | None,
) -> tuple[list[_PopulationMember], dict[str, object]]:
    """People of the requester's age range and sex, widened as needed.

    Age widens first (neighbouring 5-year ranges), then sex is dropped. A sex
    the studies do not report ("diverse") or no answer compares across sexes.
    """
    sex_filter = comparable_sex(sex)
    if age_range not in AGE_RANGES:
        age_range = None
    if age_range is None and sex_filter is None:
        return members, _group_payload("everyone", None, None, len(members))

    def matching(distance: int | None, by_sex: str | None) -> list[_PopulationMember]:
        ranges = neighbouring_ranges(age_range, distance) if age_range and distance is not None else None
        return [
            member
            for member in members
            if (ranges is None or member.age_range in ranges)
            and (by_sex is None or member.sex == by_sex)
        ]

    for by_sex in ([sex_filter, None] if sex_filter else [None]):
        distances: list[int | None] = list(range(len(AGE_RANGES))) if age_range else [None]
        best: list[_PopulationMember] = []
        for distance in distances:
            best = matching(distance, by_sex)
            if len(best) >= COHORT_TARGET_SIZE:
                break
        if len(best) >= MIN_POPULATION_SIZE and (by_sex is not None or age_range is not None):
            ranges = sorted({m.age_range for m in best if m.age_range}, key=AGE_RANGES.index)
            return best, _group_payload("cohort", ranges, by_sex, len(best))
    return members, _group_payload("everyone", None, None, len(members))


def _group_payload(basis: str, age_ranges: list[str] | None, sex: str | None, size: int) -> dict[str, object]:
    return {
        "basis": basis,
        "ageRanges": [age_ranges[0], age_ranges[-1]] if age_ranges else None,
        "sex": sex,
        "size": size,
    }


def query_youtube_population(
    connection,
    request_payload: object,
    *,
    ldihk_id: str,
) -> dict[str, object]:
    request = validate_population_request(request_payload)

    requester_row = _fetch_requester(connection, ldihk_id)
    requester_id = requester_row.user_id if requester_row else None
    real_profiles = (
        _fetch_usage_profiles(
            connection,
            scope=REAL_USERS_SCOPE,
            start_date=request.start_date,
            end_date=request.end_date,
            marker="population_real_usage",
            platforms=request.platforms,
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

    comparison_platforms = request.comparison_platforms
    coverage = _coverage(connection, request.platforms)
    if comparison_platforms != request.platforms:
        others = _fetch_usage_profiles(
            connection,
            scope=REAL_USERS_SCOPE,
            start_date=request.start_date,
            end_date=request.end_date,
            marker="population_real_usage_comparison",
            platforms=comparison_platforms,
        )
        others.pop(requester_id, None)
        others_coverage = _coverage(connection, comparison_platforms)
    else:
        others, others_coverage = real_profiles, coverage
    members = _real_members(others, others_coverage, request, exclude_user_id=requester_id)
    series = None
    if request.include_synthetic:
        series = procedural_population.day_series(
            request.start_date, request.end_date, platforms=comparison_platforms
        )
        members.extend(_procedural_members(series, request))

    group = _group_payload("everyone", None, None, len(members))
    if request.compare_with == "cohort" and requester_row is not None:
        members = _with_demographics(connection, members)
        members, group = select_comparison_group(
            members, age_range=requester_row.age_range, sex=requester_row.sex
        )

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
    # The user counts only on days inside their own history for these
    # platforms (no line and no zeros before their export starts).
    own_first, own_last = coverage.get(requester_id, (request.start_date, request.end_date))
    own_days = [day for day in days if own_first <= day <= own_last] or days
    user_daily_average = sum(requester.daily_hours.get(day, 0.0) for day in own_days) / len(own_days)
    matrix = _hours_matrix(members, days, series)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        member_averages = [float(value) for value in np.nan_to_num(np.nanmean(matrix, axis=1))]

    return {
        "schema_version": POPULATION_SCHEMA_VERSION,
        "ready": True,
        "dataset": "youtube_usage",
        "platforms": list(request.platforms),
        "populationSource": request.population_source,
        "comparisonPlatforms": list(comparison_platforms),
        "userCoverage": {"startDate": own_days[0].isoformat(), "endDate": own_days[-1].isoformat()},
        "userPercentile": _percentile_rank(user_daily_average, member_averages),
        "userDailyAverageHours": round(user_daily_average, 2),
        "includeSynthetic": request.include_synthetic,
        "customPercentile": request.custom_percentile,
        "populationSize": len(members),
        "comparisonGroup": group,
        # Synthetic profiles now cover the requested days themselves.
        "syntheticBaseline": None,
        "syntheticModel": (
            {"version": procedural_population.MODEL_VERSION, "profiles": len(series.profiles)}
            if series is not None
            else None
        ),
        "distribution": _distribution_payload(member_averages),
        "deciles": _deciles_payload(days, requester, matrix, request.custom_percentile, set(own_days)),
        "hourlyAverages": _hourly_payload(requester, members, request.day_count, series),
    }


def _fetch_requester(connection, ldihk_id: str) -> _Requester | None:
    rows = _fetch_rows(
        connection,
        """
            /* population_requester */
            SELECT id::text AS user_id, age_range, sex
            FROM users
            WHERE external_id = %s
              AND is_synthetic = false
        """,
        [ldihk_id],
    )
    if not rows:
        return None
    row = rows[0]
    return _Requester(
        user_id=str(row["user_id"]),
        age_range=row.get("age_range"),
        sex=row.get("sex"),
    )


def _with_demographics(connection, members: list[_PopulationMember]) -> list[_PopulationMember]:
    """Attach each member's age range and sex (people without them only count
    when the comparison falls back to everyone)."""
    rows = _fetch_rows(
        connection,
        """
            /* population_demographics */
            SELECT id::text AS user_id, age_range, sex
            FROM users
            WHERE age_range IS NOT NULL OR sex IS NOT NULL
        """,
        [],
    )
    by_id = {str(row["user_id"]): row for row in rows}
    return [
        member
        if member.synthetic  # procedural profiles carry their own
        else replace(
            member,
            age_range=(by_id.get(member.user_id) or {}).get("age_range"),
            sex=(by_id.get(member.user_id) or {}).get("sex"),
        )
        for member in members
    ]


def _fetch_usage_profiles(
    connection,
    *,
    scope: str,
    start_date: date,
    end_date: date,
    marker: str,
    platforms: tuple[str, ...] = (YOUTUBE_PLATFORM,),
) -> dict[str, _UsageProfile]:
    """Per-user daily hours and hourly seconds (summed over `platforms`) in one scan."""
    rows = _fetch_rows(
        connection,
        f"""
            /* {marker} */
            WITH {_clipped_events_cte(scope, platforms)},
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


def _coverage(connection, platforms: tuple[str, ...]) -> dict[str, tuple[date, date]]:
    """First and last day (UTC) of each real user's watch history on `platforms`."""
    rows = _fetch_rows(
        connection,
        f"""
            /* population_real_coverage */
            SELECT
                ue.user_id::text AS user_id,
                to_char(MIN(ue.occurred_at AT TIME ZONE 'UTC')::date, 'YYYY-MM-DD') AS first_date,
                to_char(MAX(ue.occurred_at AT TIME ZONE 'UTC')::date, 'YYYY-MM-DD') AS last_date
            FROM usage_events ue
            JOIN users u ON u.id = ue.user_id
            WHERE ue.is_synthetic = false
              AND u.is_synthetic = false
              AND {_platform_filter_sql("ue", platforms)}
              AND {WATCH_EVENT_SQL.format(alias="ue")}
              AND ue.occurred_at IS NOT NULL
            GROUP BY ue.user_id
        """,
        [],
    )
    return {
        str(row["user_id"]): (date.fromisoformat(str(row["first_date"])), date.fromisoformat(str(row["last_date"])))
        for row in rows
    }


def _platform_filter_sql(alias: str, platforms: tuple[str, ...]) -> str:
    # Names come from COMPARABLE_PLATFORMS / SOCIAL_PLATFORMS, never from input.
    assert all(platform.isalpha() for platform in platforms)
    return f"{alias}.platform IN ({', '.join(repr(platform) for platform in platforms)})"


def _real_members(
    profiles: dict[str, _UsageProfile],
    coverage: dict[str, tuple[date, date]],
    request: PopulationRequest,
    *,
    exclude_user_id: str,
) -> list[_PopulationMember]:
    """Other real users whose watch history overlaps the requested range.

    Someone counts on a day inside their own history even if they watched
    nothing that day (0 hours), but not on days before their export starts or
    after it ends.
    """
    rows = [
        {"user_id": user_id, "first_date": first.isoformat(), "last_date": last.isoformat()}
        for user_id, (first, last) in coverage.items()
    ]
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
                user_id=user_id,
            )
        )
    return members












def _percentile(sorted_values: list[float], fraction: float) -> float:
    """Linear interpolation, matching Postgres percentile_cont."""
    if not sorted_values:
        return 0.0
    position = fraction * (len(sorted_values) - 1)
    lower = int(position)
    upper = min(lower + 1, len(sorted_values) - 1)
    weight = position - lower
    return sorted_values[lower] + (sorted_values[upper] - sorted_values[lower]) * weight


def _procedural_members(series, request: PopulationRequest) -> list[_PopulationMember]:
    return [
        _PopulationMember(
            profile=_UsageProfile(),
            covered_days=len(series.days),
            first_day=request.start_date,
            last_day=request.end_date,
            synthetic=True,
            user_id=profile.user_id,
            age_range=profile.age_range,
            sex=profile.sex,
            series_row=row,
        )
        for row, profile in enumerate(series.profiles)
    ]


def _hours_matrix(members: list[_PopulationMember], days: list[date], series) -> np.ndarray:
    """Hours per member (rows) and day (columns); NaN where a member does not count."""
    matrix = np.full((len(members), len(days)), np.nan)
    synthetic = [(row, member.series_row) for row, member in enumerate(members) if member.series_row >= 0]
    if synthetic:
        rows, series_rows = zip(*synthetic)
        matrix[list(rows)] = series.hours[list(series_rows)]
    index = {day: column for column, day in enumerate(days)}
    for row, member in enumerate(members):
        if member.series_row >= 0:
            continue
        first, last = index[member.first_day], index[member.last_day]
        matrix[row, first : last + 1] = 0.0
        for day, hours in member.profile.daily_hours.items():
            column = index.get(day)
            if column is not None and first <= column <= last:
                matrix[row, column] = hours
    return matrix


def _deciles_payload(
    days: list[date],
    requester: _UsageProfile,
    matrix: np.ndarray,
    custom_percentile: int,
    own_days: set[date] | None = None,
) -> list[dict[str, object]]:
    """Per day, over the members counting that day (linear, like percentile_cont).

    `user` is null on days outside the user's own history, so charts draw no
    line there.
    """
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        median, top10, bottom10, custom = np.nan_to_num(
            np.nanpercentile(matrix, [50, 90, 10, custom_percentile], axis=0)
        )
    return [
        {
            "date": day.isoformat(),
            "user": round(requester.daily_hours.get(day, 0.0), 2) if own_days is None or day in own_days else None,
            "median": round(float(median[column]), 2),
            "top10": round(float(top10[column]), 2),
            "bottom10": round(float(bottom10[column]), 2),
            "customPercentileHours": round(float(custom[column]), 2),
        }
        for column, day in enumerate(days)
    ]


def _hourly_payload(
    requester: _UsageProfile,
    members: list[_PopulationMember],
    day_count: int,
    series=None,
) -> list[dict[str, object]]:
    """Average hours per day in each hour of the day, per member, then averaged."""
    rates = np.zeros(24)
    for member in members:
        days = max(1, member.covered_days)
        if member.series_row >= 0:
            rates += series.hourly_seconds[member.series_row] / days / 3600
        else:
            rates += np.array([member.profile.hourly_seconds.get(hour, 0.0) for hour in range(24)]) / days / 3600
    payload: list[dict[str, object]] = []
    for hour in range(24):
        population_avg = float(rates[hour]) / len(members) if members else 0.0
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


def _clipped_events_cte(population_scope: str, platforms: tuple[str, ...] = (YOUTUBE_PLATFORM,)) -> str:
    defaults = DEFAULT_PLATFORM_DURATION_SECONDS
    return f"""
        clipped_events AS (
            SELECT
                ue.user_id,
                ue.occurred_at,
                ue.platform,
                ue.product,
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
                        WHEN ue.platform = 'youtube' AND ue.product = 'shorts'
                        THEN {defaults[("youtube", "shorts")]}::numeric
                        WHEN ue.platform = 'youtube' THEN {defaults[("youtube", "long")]}::numeric
                        WHEN ue.platform = 'tiktok' THEN {defaults[("tiktok", None)]}::numeric
                        WHEN ue.platform = 'instagram' AND ue.product = 'stories'
                        THEN {defaults[("instagram", "stories")]}::numeric
                        WHEN ue.platform = 'instagram' THEN {defaults[("instagram", None)]}::numeric
                        ELSE {defaults[("linkedin", None)]}::numeric
                    END
                ) AS base_duration,
                (
                    SELECT MIN(next_ue.occurred_at)
                    FROM usage_events next_ue
                    WHERE next_ue.user_id = ue.user_id
                      AND next_ue.platform = ue.platform
                      AND {WATCH_EVENT_SQL.format(alias="next_ue")}
                      AND next_ue.occurred_at IS NOT NULL
                      AND ue.occurred_at IS NOT NULL
                      AND next_ue.occurred_at > ue.occurred_at
                ) AS next_occurred_at
            FROM usage_events ue
            JOIN users u ON u.id = ue.user_id
            LEFT JOIN youtube_videos yv ON yv.video_id = ue.video_id
            WHERE {population_scope}
              AND {_platform_filter_sql("ue", platforms)}
              AND {WATCH_EVENT_SQL.format(alias="ue")}
              AND ue.occurred_at >= (%s::date::timestamp AT TIME ZONE 'UTC')
              AND ue.occurred_at < ((%s::date + INTERVAL '1 day')::timestamp AT TIME ZONE 'UTC')
        ),
        events_with_duration AS (
            SELECT
                user_id,
                occurred_at,
                platform,
                event_type,
                {watch_seconds_sql("base_duration", platform="platform", product="product", occurred_at="occurred_at", next_started_at="next_occurred_at")}
                  AS estimated_watch_seconds
            FROM clipped_events
        )
    """


# ---------------------------------------------------------------------------
# Reference values for the risk score (POST /api/population/reference)
# ---------------------------------------------------------------------------

# Same definitions as the risk tab: late night is 23:00-04:59, an hour counts
# as active with at least 5 minutes of watching, metrics are per active day.
LATE_NIGHT_HOURS = frozenset({23, 0, 1, 2, 3, 4})
ACTIVE_HOUR_SECONDS = 300
REFERENCE_METRICS = ("dailyHours", "lateNightHours", "fragmentation")


def query_risk_reference(
    connection,
    request_payload: object,
    *,
    ldihk_id: str,
) -> dict[str, object]:
    """Typical risk-score inputs of the requester's cohort and of everyone.

    The risk tab measures a user against people of the same age range and sex
    (synthetic profiles plus other real users), so cohorts that typically use
    more or less do not shift the score by that alone.
    """
    request = validate_population_request(request_payload)
    requester = _fetch_requester(connection, ldihk_id)
    if requester is None:
        return {"ready": False, "reason": "no_user_data"}

    comparison_platforms = request.comparison_platforms
    per_member = _fetch_member_day_metrics(
        connection,
        scope=REAL_USERS_SCOPE,
        start_date=request.start_date,
        end_date=request.end_date,
        marker="reference_real_usage",
        platforms=comparison_platforms,
    )
    per_member.pop(requester.user_id, None)
    members = _with_demographics(
        connection,
        [
            _PopulationMember(
                profile=_UsageProfile(),
                covered_days=0,
                first_day=request.start_date,
                last_day=request.end_date,
                synthetic=False,
                user_id=user_id,
            )
            for user_id in per_member
        ],
    )
    if request.include_synthetic:
        series = procedural_population.day_series(
            request.start_date, request.end_date, platforms=comparison_platforms
        )
        synthetic_metrics = _procedural_day_metrics(series)
        per_member.update(synthetic_metrics)
        members.extend(
            member
            for member in _procedural_members(series, request)
            if member.user_id in synthetic_metrics
        )
    if len(members) < MIN_POPULATION_SIZE:
        return {
            "ready": False,
            "reason": "insufficient_population",
            "populationSize": len(members),
            "minPopulationSize": MIN_POPULATION_SIZE,
        }
    group_members, group = (
        select_comparison_group(members, age_range=requester.age_range, sex=requester.sex)
        if request.compare_with == "cohort"
        else (members, _group_payload("everyone", None, None, len(members)))
    )
    return {
        "ready": True,
        "comparisonGroup": group,
        "populationSource": request.population_source,
        "comparisonPlatforms": list(comparison_platforms),
        "profile": {"age_range": requester.age_range, "sex": requester.sex},
        "cohort": _median_metrics([per_member[m.user_id] for m in group_members]),
        "overall": _median_metrics([per_member[m.user_id] for m in members]),
    }


def _fetch_member_day_metrics(
    connection,
    *,
    scope: str,
    start_date: date,
    end_date: date,
    marker: str,
    platforms: tuple[str, ...] = (YOUTUBE_PLATFORM,),
) -> dict[str, dict[str, float]]:
    """Per user: average watch hours, late-night hours and fragmentation per active day."""
    rows = _fetch_rows(
        connection,
        f"""
            /* {marker} */
            WITH {_clipped_events_cte(scope, platforms)}
            SELECT
                user_id::text AS user_id,
                to_char((occurred_at AT TIME ZONE 'UTC')::date, 'YYYY-MM-DD') AS date,
                EXTRACT(HOUR FROM occurred_at AT TIME ZONE 'UTC')::int AS hour,
                COALESCE(SUM(estimated_watch_seconds), 0)::numeric AS seconds
            FROM events_with_duration
            GROUP BY 1, 2, 3
        """,
        [start_date.isoformat(), end_date.isoformat()],
    )
    days: dict[str, dict[str, list[float]]] = {}
    for row in rows:
        seconds = _float(row.get("seconds"))
        day = days.setdefault(str(row["user_id"]), {}).setdefault(str(row["date"]), [0.0, 0.0, 0.0])
        day[0] += seconds
        if _int(row.get("hour")) in LATE_NIGHT_HOURS:
            day[1] += seconds
        if seconds >= ACTIVE_HOUR_SECONDS:
            day[2] += 1
    metrics: dict[str, dict[str, float]] = {}
    for user_id, by_day in days.items():
        count = len(by_day)
        metrics[user_id] = {
            "dailyHours": sum(d[0] for d in by_day.values()) / 3600 / count,
            "lateNightHours": sum(d[1] for d in by_day.values()) / 3600 / count,
            "fragmentation": sum(d[2] for d in by_day.values()) / 24 / count,
        }
    return metrics


def _procedural_day_metrics(series) -> dict[str, dict[str, float]]:
    """Same metrics as _fetch_member_day_metrics, per synthetic profile."""
    metrics: dict[str, dict[str, float]] = {}
    for row, profile in enumerate(series.profiles):
        active = series.hours[row] > 0
        if not active.any():
            continue
        metrics[profile.user_id] = {
            "dailyHours": float(series.hours[row][active].mean()),
            "lateNightHours": float(series.late_night_hours[row][active].mean()),
            "fragmentation": float(series.fragmentation[row][active].mean()),
        }
    return metrics


def _median_metrics(values: list[dict[str, float]]) -> dict[str, float]:
    return {
        metric: round(_percentile(sorted(v[metric] for v in values), 0.5), 3)
        for metric in REFERENCE_METRICS
    }


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
