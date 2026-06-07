from __future__ import annotations

from dataclasses import dataclass
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


def query_youtube_population(
    connection,
    request_payload: object,
    *,
    ldihk_id: str,
) -> dict[str, object]:
    request = validate_population_request(request_payload)

    user_daily_rows = _fetch_user_daily_hours(connection, request, ldihk_id=ldihk_id)
    user_daily_hours = {
        str(row["date"]): _float(row.get("watch_hours", 0))
        for row in user_daily_rows
    }
    if not user_daily_hours:
        return {
            "schema_version": POPULATION_SCHEMA_VERSION,
            "ready": False,
            "message": "Dataset not ready. Please ingest YouTube data first.",
        }

    user_hourly_rows = _fetch_user_hourly_hours(connection, request, ldihk_id=ldihk_id)
    population_decile_rows = _fetch_population_daily_percentiles(connection, request)
    population_hourly_rows = _fetch_population_hourly_averages(connection, request)
    distribution_rows = _fetch_population_distribution(connection, request)
    population_average_rows = _fetch_population_average_hours(connection, request)

    all_dates = _date_range(request.start_date, request.end_date)
    user_total_hours = sum(user_daily_hours.values())
    user_daily_average_hours = user_total_hours / request.day_count
    user_percentile = _percentile_rank(
        user_daily_average_hours,
        [_float(row.get("average_hours", 0)) for row in population_average_rows],
    )

    return {
        "schema_version": POPULATION_SCHEMA_VERSION,
        "ready": True,
        "dataset": "youtube_usage",
        "platforms": [YOUTUBE_PLATFORM],
        "userPercentile": user_percentile,
        "userDailyAverageHours": round(user_daily_average_hours, 2),
        "includeSynthetic": request.include_synthetic,
        "customPercentile": request.custom_percentile,
        "distribution": _distribution_payload(distribution_rows),
        "deciles": _deciles_payload(
            all_dates,
            user_daily_hours,
            population_decile_rows,
        ),
        "hourlyAverages": _hourly_payload(
            user_hourly_rows,
            population_hourly_rows,
        ),
    }


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


def _fetch_user_daily_hours(
    connection,
    request: PopulationRequest,
    *,
    ldihk_id: str,
) -> list[dict[str, object]]:
    from backend.query_api import query_youtube_usage
    payload = {
        "dataset": "youtube_usage",
        "user_id": ldihk_id,
        "metrics": ["estimated_watch_seconds"],
        "dimensions": ["date"],
        "filters": {
            "start_date": request.start_date.isoformat(),
            "end_date": request.end_date.isoformat(),
        },
        "options": {
            "include_zero_buckets": True,
            "limit": request.day_count,
        }
    }
    res = query_youtube_usage(connection, payload)
    rows = res.get("rows", [])
    return [
        {
            "date": row["date"],
            "watch_hours": float(row.get("estimated_watch_seconds", 0)) / 3600.0
        }
        for row in rows
    ]


def _fetch_user_hourly_hours(
    connection,
    request: PopulationRequest,
    *,
    ldihk_id: str,
) -> list[dict[str, object]]:
    from backend.query_api import query_youtube_usage
    payload = {
        "dataset": "youtube_usage",
        "user_id": ldihk_id,
        "metrics": ["estimated_watch_seconds"],
        "dimensions": ["hour"],
        "filters": {
            "start_date": request.start_date.isoformat(),
            "end_date": request.end_date.isoformat(),
        },
        "options": {
            "include_zero_buckets": False,
            "limit": 24,
        }
    }
    res = query_youtube_usage(connection, payload)
    rows = res.get("rows", [])
    return [
        {
            "hour": row["hour"],
            "watch_hours": float(row.get("estimated_watch_seconds", 0)) / request.day_count / 3600.0
        }
        for row in rows
    ]


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
                LEAD(ue.occurred_at) OVER (
                    PARTITION BY ue.user_id, ue.platform, ue.event_type
                    ORDER BY ue.occurred_at
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


def _fetch_population_daily_percentiles(
    connection,
    request: PopulationRequest,
) -> list[dict[str, object]]:
    population_scope = _population_scope_sql(request.include_synthetic)
    return _fetch_rows(
        connection,
        f"""
            /* population_daily_percentiles */
            WITH {_clipped_events_cte(population_scope)},
            daily AS (
                SELECT
                    (occurred_at AT TIME ZONE 'UTC')::date AS watch_date,
                    user_id AS population_user_id,
                    COALESCE(SUM(estimated_watch_seconds), 0)::numeric
                        / 3600 AS watch_hours
                FROM events_with_duration
                GROUP BY 1, 2
            )
            SELECT
                to_char(watch_date, 'YYYY-MM-DD') AS date,
                percentile_cont(0.1) WITHIN GROUP (
                    ORDER BY watch_hours
                ) AS bottom10,
                percentile_cont(0.5) WITHIN GROUP (
                    ORDER BY watch_hours
                ) AS median,
                percentile_cont(0.9) WITHIN GROUP (
                    ORDER BY watch_hours
                ) AS top10,
                percentile_cont(%s) WITHIN GROUP (
                    ORDER BY watch_hours
                ) AS custom_percentile_hours
            FROM daily
            GROUP BY watch_date
            ORDER BY watch_date
        """,
        [
            request.start_date.isoformat(),
            request.end_date.isoformat(),
            request.custom_percentile / 100,
        ],
    )


def _fetch_population_hourly_averages(
    connection,
    request: PopulationRequest,
) -> list[dict[str, object]]:
    population_scope = _population_scope_sql(request.include_synthetic)
    return _fetch_rows(
        connection,
        f"""
            /* population_hourly_averages */
            WITH {_clipped_events_cte(population_scope)},
            population_users AS (
                SELECT DISTINCT user_id AS population_user_id
                FROM events_with_duration
            ),
            hourly_seconds AS (
                SELECT
                    user_id AS population_user_id,
                    EXTRACT(HOUR FROM occurred_at AT TIME ZONE 'UTC')::int
                        AS hour,
                    COALESCE(SUM(estimated_watch_seconds), 0)::numeric
                        AS watch_seconds
                FROM events_with_duration
                GROUP BY 1, 2
            ),
            hours AS (
                SELECT generate_series(0, 23) AS hour
            )
            SELECT
                hours.hour,
                COALESCE(
                    AVG(COALESCE(hourly_seconds.watch_seconds, 0)::numeric
                        / %s / 3600),
                    0
                ) AS population_avg
            FROM hours
            CROSS JOIN population_users
            LEFT JOIN hourly_seconds
              ON hourly_seconds.hour = hours.hour
             AND hourly_seconds.population_user_id = population_users.population_user_id
            GROUP BY hours.hour
            ORDER BY hours.hour
        """,
        [
            request.start_date.isoformat(),
            request.end_date.isoformat(),
            request.day_count,
        ],
    )


def _fetch_population_distribution(
    connection,
    request: PopulationRequest,
) -> list[dict[str, object]]:
    population_scope = _population_scope_sql(request.include_synthetic)
    return _fetch_rows(
        connection,
        f"""
            /* population_distribution */
            WITH {_clipped_events_cte(population_scope)},
            population_averages AS (
                SELECT
                    user_id AS population_user_id,
                    COALESCE(SUM(estimated_watch_seconds), 0)::numeric
                        / %s / 3600 AS average_hours
                FROM events_with_duration
                GROUP BY 1
            )
            SELECT
                FLOOR(LEAST(24, GREATEST(0, average_hours)))::int AS hours,
                COUNT(*)::bigint AS density
            FROM population_averages
            GROUP BY 1
            ORDER BY 1
        """,
        [
            request.start_date.isoformat(),
            request.end_date.isoformat(),
            request.day_count,
        ],
    )


def _fetch_population_average_hours(
    connection,
    request: PopulationRequest,
) -> list[dict[str, object]]:
    population_scope = _population_scope_sql(request.include_synthetic)
    return _fetch_rows(
        connection,
        f"""
            /* population_average_hours */
            WITH {_clipped_events_cte(population_scope)}
            SELECT
                COALESCE(SUM(estimated_watch_seconds), 0)::numeric
                    / %s / 3600 AS average_hours
            FROM events_with_duration
            GROUP BY user_id
            ORDER BY average_hours
        """,
        [
            request.start_date.isoformat(),
            request.end_date.isoformat(),
            request.day_count,
        ],
    )


def _estimated_watch_seconds_sql() -> str:
    return """
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
        )
    """


def _population_scope_sql(include_synthetic: bool) -> str:
    if include_synthetic:
        return "(ue.is_synthetic = true OR u.is_synthetic = false)"
    return "ue.is_synthetic = false AND u.is_synthetic = false"


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


def _date_range(start_date: date, end_date: date) -> list[str]:
    current = start_date
    dates: list[str] = []
    while current <= end_date:
        dates.append(current.isoformat())
        current += timedelta(days=1)
    return dates


def _percentile_rank(user_average: float, population_averages: list[float]) -> int:
    if not population_averages:
        return 100
    lower_or_equal = sum(1 for value in population_averages if value <= user_average)
    return round((lower_or_equal / len(population_averages)) * 100)


def _distribution_payload(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    row_by_hour = {_int(row.get("hours")): _int(row.get("density")) for row in rows}
    return [
        {"hours": float(hour), "density": row_by_hour.get(hour, 0)}
        for hour in range(25)
    ]


def _deciles_payload(
    all_dates: list[str],
    user_daily_hours: dict[str, float],
    population_rows: list[dict[str, object]],
) -> list[dict[str, object]]:
    population_by_date = {str(row["date"]): row for row in population_rows}
    payload: list[dict[str, object]] = []
    for date_key in all_dates:
        population = population_by_date.get(date_key, {})
        payload.append(
            {
                "date": date_key,
                "user": round(user_daily_hours.get(date_key, 0), 2),
                "median": round(_float(population.get("median", 0)), 2),
                "top10": round(_float(population.get("top10", 0)), 2),
                "bottom10": round(_float(population.get("bottom10", 0)), 2),
                "customPercentileHours": round(
                    _float(population.get("custom_percentile_hours", 0)),
                    2,
                ),
            }
        )
    return payload


def _hourly_payload(
    user_rows: list[dict[str, object]],
    population_rows: list[dict[str, object]],
) -> list[dict[str, object]]:
    user_by_hour = {
        _int(row.get("hour")): _float(row.get("watch_hours", 0)) for row in user_rows
    }
    population_by_hour = {
        _int(row.get("hour")): _float(row.get("population_avg", 0))
        for row in population_rows
    }
    return [
        {
            "hour": f"{hour:02d}:00",
            "populationAvg": round(population_by_hour.get(hour, 0), 3),
            "userAvg": round(user_by_hour.get(hour, 0), 3),
        }
        for hour in range(24)
    ]


def _compact_sql(sql: str) -> str:
    return " ".join(sql.split())
