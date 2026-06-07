from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any


QUERY_SCHEMA_VERSION = "youtube_usage.structured_query.v1"
DEFAULT_GLOBAL_DURATION_SECONDS = 600
DEFAULT_PLATFORM_DURATION_SECONDS = {
    ("youtube", "shorts"): 60,
    ("youtube", "long"): 600,
    ("youtube", "youtube"): 600,
    ("youtube", "youtube_music"): 600,
    ("tiktok", None): 60,
    ("instagram", None): 60,
    ("spotify", None): 120,
    ("linkedin", None): 120,
}
DEFAULT_RESULT_LIMIT = 500
MAX_RESULT_LIMIT = 1000
ALLOW_IDENTIFIER_DIMENSIONS_ENV = "ALLOW_IDENTIFIER_DIMENSIONS"
QUERY_BUCKET_TIMEZONE_ENV = "QUERY_BUCKET_TIMEZONE"
DEFAULT_QUERY_BUCKET_TIMEZONE = "UTC"
SUPPORTED_DATASETS = {"youtube_usage", "usage_analytics"}

ALLOWED_METRICS = {
    "event_count",
    "estimated_watch_seconds",
    "api_watch_seconds",
    "estimated_event_count",
    "estimated_usage_seconds",
    "subscription_count",
    "unique_video_count",
    "unique_channel_count",
}
BASE_ALLOWED_DIMENSIONS = {
    "date",
    "hour",
    "weekday",
    "month",
    "event_type",
    "platform",
    "product",
    "is_synthetic",
    "age",
    "age_bucket",
    "sex",
    "cohort",
}
IDENTIFIER_DIMENSIONS = {
    "channel_id",
    "video_id",
}
ALLOWED_DIMENSIONS = BASE_ALLOWED_DIMENSIONS | IDENTIFIER_DIMENSIONS
ALLOWED_FILTERS = {
    "user_id",
    "start_date",
    "end_date",
    "event_type",
    "platform",
    "product",
    "is_synthetic",
    "age",
    "age_bucket",
    "sex",
    "cohort",
}
ALLOWED_SORT_DIRECTIONS = {"asc", "desc"}
STRING_VALUE_FILTERS = {"event_type", "platform", "product", "age_bucket", "sex", "cohort"}

EVENT_DIMENSION_SQL = {
    "event_type": "ue.event_type",
    "platform": "ue.platform",
    "product": "ue.product",
    "is_synthetic": "ue.is_synthetic",
    "age": "u.age",
    "age_bucket": "u.age_bucket",
    "sex": "u.sex",
    "cohort": "u.cohort",
    "channel_id": "COALESCE(ue.channel_id, yv.channel_id)",
    "video_id": "ue.video_id",
}
SUBSCRIPTION_DIMENSION_SQL = {
    "event_type": "NULL::text",
    "platform": "'youtube'::text",
    "product": "'youtube'::text",
    "is_synthetic": "false",
    "age": "u.age",
    "age_bucket": "u.age_bucket",
    "sex": "u.sex",
    "cohort": "u.cohort",
    "channel_id": "s.channel_id",
    "video_id": "NULL::text",
}

METRIC_SQL = {
    "event_count": "COUNT(event_id)::bigint AS event_count",
    "estimated_watch_seconds": (
        "COALESCE(ROUND(SUM(estimated_duration_seconds) FILTER "
        "(WHERE metric_event_type = 'watch'))::bigint, 0) "
        "AS estimated_watch_seconds"
    ),
    "api_watch_seconds": (
        "COALESCE((SUM(api_duration_seconds) FILTER "
        "(WHERE metric_event_type = 'watch'))::bigint, 0) AS api_watch_seconds"
    ),
    "estimated_event_count": (
        "COUNT(event_id) FILTER (WHERE metric_event_type = 'watch' "
        "AND api_duration_seconds IS NULL)::bigint "
        "AS estimated_event_count"
    ),
    "estimated_usage_seconds": (
        "COALESCE(ROUND(SUM(estimated_duration_seconds))::bigint, 0) "
        "AS estimated_usage_seconds"
    ),
    "subscription_count": (
        "COUNT(DISTINCT subscription_id)::bigint AS subscription_count"
    ),
    "unique_video_count": "COUNT(DISTINCT video_id)::bigint AS unique_video_count",
    "unique_channel_count": (
        "COUNT(DISTINCT metric_channel_id)::bigint AS unique_channel_count"
    ),
}

EVENT_METRICS = ALLOWED_METRICS - {"subscription_count"}


class QueryValidationError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class StructuredQuery:
    dataset: str
    user_id: str
    metrics: list[str]
    dimensions: list[str]
    filters: dict[str, Any]
    include_zero_buckets: bool
    limit: int
    sort_by: str | None = None
    sort_direction: str | None = None
    bucket_timezone: str = DEFAULT_QUERY_BUCKET_TIMEZONE


@dataclass(frozen=True)
class CompiledSql:
    sql: str
    parameters: list[object]


def query_youtube_usage(
    connection,
    request_payload: object,
    *,
    global_duration_seconds: int = DEFAULT_GLOBAL_DURATION_SECONDS,
) -> dict[str, object]:
    if isinstance(request_payload, StructuredQuery):
        query = request_payload
    else:
        query = validate_query_request(request_payload)
    rows = _fetch_rows(
        connection,
        compile_aggregate_query(
            query, global_duration_seconds=global_duration_seconds
        ),
    )
    rows = _zero_fill_rows(rows, query)
    quality = _fetch_one(
        connection,
        compile_quality_query(query, global_duration_seconds=global_duration_seconds),
    )

    return {
        "schema_version": QUERY_SCHEMA_VERSION,
        "dataset": query.dataset,
        "user_id": query.user_id,
        "duration_strategy": {
            "kind": "event_duration_api_user_average_platform_default",
            "api_duration_source": "youtube_data_api",
            "user_average_source": "event_weighted_user_average",
            "global_default_seconds": global_duration_seconds,
            "platform_defaults_seconds": _platform_duration_defaults_payload(),
        },
        "query": {
            "metrics": query.metrics,
            "dimensions": query.dimensions,
            "filters": query.filters,
            "options": _response_options(query),
        },
        "quality": _normalize_quality(quality),
        "rows": rows[: query.limit],
    }


def query_request_for_ldihk_id(
    request_payload: object,
    *,
    ldihk_id: str,
) -> object:
    if not isinstance(request_payload, dict):
        return request_payload

    scoped_payload = dict(request_payload)
    scoped_payload["user_id"] = ldihk_id
    if isinstance(scoped_payload.get("filters"), dict):
        scoped_payload["filters"] = dict(scoped_payload["filters"])
    return scoped_payload


def public_query_response(payload: dict[str, object]) -> dict[str, object]:
    public_payload = dict(payload)
    ldihk_id = public_payload.pop("user_id", None)
    if ldihk_id is not None:
        public_payload["ldihk_id"] = ldihk_id

    query = public_payload.get("query")
    if isinstance(query, dict):
        public_query = dict(query)
        filters = public_query.get("filters")
        if isinstance(filters, dict):
            public_filters = dict(filters)
            public_filters.pop("user_id", None)
            public_query["filters"] = public_filters
        public_payload["query"] = public_query

    return public_payload


def validate_query_request(request_payload: object) -> StructuredQuery:
    if not isinstance(request_payload, dict):
        raise QueryValidationError("invalid_request")
    if "sql" in request_payload:
        raise QueryValidationError("raw_sql_not_allowed")

    dataset = request_payload.get("dataset")
    if dataset not in SUPPORTED_DATASETS:
        raise QueryValidationError("invalid_dataset")

    user_id = request_payload.get("user_id")
    if not isinstance(user_id, str) or not user_id:
        raise QueryValidationError("invalid_user_id")

    metrics = _validate_string_list(request_payload.get("metrics"), "invalid_metrics")
    dimensions = _validate_string_list(
        request_payload.get("dimensions"), "invalid_dimensions", allow_empty=True
    )
    filters = request_payload.get("filters", {})
    options = request_payload.get("options", {})
    if not isinstance(filters, dict):
        raise QueryValidationError("invalid_filters")
    if not isinstance(options, dict):
        raise QueryValidationError("invalid_options")

    if any(metric not in ALLOWED_METRICS for metric in metrics):
        raise QueryValidationError("invalid_metric")
    if any(dimension not in ALLOWED_DIMENSIONS for dimension in dimensions):
        raise QueryValidationError("invalid_dimension")
    if not _allow_identifier_dimensions() and any(
        dimension in IDENTIFIER_DIMENSIONS for dimension in dimensions
    ):
        raise QueryValidationError("invalid_dimension")
    if any(filter_name not in ALLOWED_FILTERS for filter_name in filters):
        raise QueryValidationError("invalid_filter")

    normalized_filters = dict(filters)
    if "user_id" in normalized_filters and normalized_filters["user_id"] != user_id:
        raise QueryValidationError("invalid_user_filter")
    normalized_filters["user_id"] = user_id
    _validate_date_filters(normalized_filters)
    _validate_value_filters(normalized_filters)

    if "include_zero_buckets" in options and not isinstance(
        options["include_zero_buckets"], bool
    ):
        raise QueryValidationError("invalid_options")
    limit = _validate_limit(options.get("limit", DEFAULT_RESULT_LIMIT))
    sort_by, sort_direction = _validate_sort_options(options, metrics)
    bucket_timezone = _query_bucket_timezone()

    return StructuredQuery(
        dataset=dataset,
        user_id=user_id,
        metrics=metrics,
        dimensions=dimensions,
        filters=normalized_filters,
        include_zero_buckets=bool(options.get("include_zero_buckets")),
        limit=limit,
        sort_by=sort_by,
        sort_direction=sort_direction,
        bucket_timezone=bucket_timezone,
    )


def compile_aggregate_query(
    query: StructuredQuery,
    *,
    global_duration_seconds: int = DEFAULT_GLOBAL_DURATION_SECONDS,
) -> CompiledSql:
    include_event_rows = any(metric in EVENT_METRICS for metric in query.metrics)
    include_subscription_rows = "subscription_count" in query.metrics
    ctes = [_user_duration_stats_cte()]
    fact_sources: list[str] = []
    parameters: list[object] = [query.user_id]

    if include_event_rows:
        event_where, event_parameters = _source_where_clause(query, source="event")
        parameters.append(global_duration_seconds)
        parameters.extend(event_parameters)
        ctes.append(_event_rows_cte(query, event_where))
        fact_sources.append("SELECT * FROM event_rows")

    if include_subscription_rows:
        subscription_where, subscription_parameters = _source_where_clause(
            query, source="subscription"
        )
        parameters.extend(subscription_parameters)
        ctes.append(_subscription_rows_cte(query, subscription_where))
        fact_sources.append("SELECT * FROM subscription_rows")

    ctes.append("fact_rows AS (\n" + "\nUNION ALL\n".join(fact_sources) + "\n)")

    select_parts = [dimension for dimension in query.dimensions]
    select_parts.extend(METRIC_SQL[metric] for metric in query.metrics)
    group_sql = ""
    order_sql = ""
    if query.dimensions:
        group_sql = "GROUP BY " + ", ".join(query.dimensions)
    order_parts: list[str] = []
    if query.sort_by is not None:
        sort_direction = query.sort_direction or "desc"
        order_parts.append(f"{query.sort_by} {sort_direction.upper()}")
    order_parts.extend(query.dimensions)
    if order_parts:
        order_sql = "ORDER BY " + ", ".join(order_parts)

    parameters.append(query.limit)
    sql = f"""
        WITH {", ".join(ctes)}
        SELECT {", ".join(select_parts)}
        FROM fact_rows
        {group_sql}
        {order_sql}
        LIMIT %s
    """
    return CompiledSql(sql=_compact_sql(sql), parameters=parameters)


def compile_quality_query(
    query: StructuredQuery,
    *,
    global_duration_seconds: int = DEFAULT_GLOBAL_DURATION_SECONDS,
) -> CompiledSql:
    event_where, event_parameters = _source_where_clause(query, source="event")
    parameters: list[object] = [
        query.user_id,
        global_duration_seconds,
        *event_parameters,
    ]
    sql = f"""
        WITH {_user_duration_stats_cte()}, {_event_rows_cte(query, event_where)}
        SELECT
            COUNT(event_id) FILTER (
                WHERE metric_event_type = 'watch'
            )::bigint AS events_counted,
            COUNT(event_id) FILTER (
                WHERE metric_event_type = 'watch'
                  AND metric_platform = 'youtube'
                  AND api_duration_seconds IS NOT NULL
            )::bigint AS events_with_api_duration,
            COUNT(event_id) FILTER (
                WHERE metric_event_type = 'watch'
                  AND api_duration_seconds IS NULL
                  AND duration_bucket = 'user_average'
            )::bigint AS events_with_user_average_estimate,
            COUNT(event_id) FILTER (
                WHERE metric_event_type = 'watch'
                  AND api_duration_seconds IS NULL
                  AND duration_bucket = 'global_default'
            )::bigint AS events_with_global_default_estimate,
            COUNT(DISTINCT video_id) FILTER (
                WHERE metric_event_type = 'watch'
                  AND metric_platform = 'youtube'
                  AND video_id IS NOT NULL
                  AND api_duration_seconds IS NULL
            )::bigint AS videos_unavailable,
            COUNT(DISTINCT video_id) FILTER (
                WHERE metric_event_type = 'watch'
                  AND metric_platform = 'youtube'
                  AND max_duration_applied IS TRUE
            )::bigint AS videos_capped
        FROM event_rows
    """
    return CompiledSql(sql=_compact_sql(sql), parameters=parameters)


def _validate_string_list(
    value: object, error_code: str, *, allow_empty: bool = False
) -> list[str]:
    if not isinstance(value, list):
        raise QueryValidationError(error_code)
    if not allow_empty and not value:
        raise QueryValidationError(error_code)
    if not all(isinstance(item, str) for item in value):
        raise QueryValidationError(error_code)
    return list(dict.fromkeys(value))


def _validate_date_filters(filters: dict[str, Any]) -> None:
    for key in ("start_date", "end_date"):
        if key not in filters:
            continue
        value = filters[key]
        if not isinstance(value, str):
            raise QueryValidationError("invalid_date_filter")
        try:
            date.fromisoformat(value)
        except ValueError as error:
            raise QueryValidationError("invalid_date_filter") from error

    if (
        "start_date" in filters
        and "end_date" in filters
        and filters["start_date"] > filters["end_date"]
    ):
        raise QueryValidationError("invalid_date_range")


def _validate_value_filters(filters: dict[str, Any]) -> None:
    for key in STRING_VALUE_FILTERS:
        if key not in filters:
            continue
        value = filters[key]
        if isinstance(value, str):
            if not value:
                raise QueryValidationError("invalid_filter_value")
            continue
        if (
            not isinstance(value, list)
            or not value
            or not all(isinstance(item, str) and item for item in value)
        ):
            raise QueryValidationError("invalid_filter_value")

    if "age" in filters:
        value = filters["age"]
        if isinstance(value, bool):
            raise QueryValidationError("invalid_filter_value")
        if isinstance(value, int):
            pass
        elif (
            not isinstance(value, list)
            or not value
            or not all(isinstance(item, int) and not isinstance(item, bool) for item in value)
        ):
            raise QueryValidationError("invalid_filter_value")

    if "is_synthetic" in filters and not isinstance(filters["is_synthetic"], bool):
        raise QueryValidationError("invalid_filter_value")


def _validate_limit(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise QueryValidationError("invalid_limit")
    if value <= 0:
        raise QueryValidationError("invalid_limit")
    return min(value, MAX_RESULT_LIMIT)


def _validate_sort_options(
    options: dict[str, object],
    metrics: list[str],
) -> tuple[str | None, str | None]:
    if "sort_by" not in options:
        if "sort_direction" in options:
            raise QueryValidationError("invalid_sort")
        return None, None

    sort_by = options["sort_by"]
    sort_direction = options.get("sort_direction", "desc")
    if isinstance(sort_direction, str):
        sort_direction = sort_direction.lower()
    if (
        not isinstance(sort_by, str)
        or sort_by not in ALLOWED_METRICS
        or sort_by not in metrics
    ):
        raise QueryValidationError("invalid_sort")
    if (
        not isinstance(sort_direction, str)
        or sort_direction not in ALLOWED_SORT_DIRECTIONS
    ):
        raise QueryValidationError("invalid_sort")
    return sort_by, sort_direction


def _allow_identifier_dimensions() -> bool:
    raw_value = os.environ.get(ALLOW_IDENTIFIER_DIMENSIONS_ENV)
    if raw_value is None:
        return True
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


def _query_bucket_timezone() -> str:
    raw_value = os.environ.get(QUERY_BUCKET_TIMEZONE_ENV, DEFAULT_QUERY_BUCKET_TIMEZONE)
    value = (
        raw_value.strip().upper()
        if raw_value.strip()
        else DEFAULT_QUERY_BUCKET_TIMEZONE
    )
    if value != "UTC":
        raise QueryValidationError("invalid_options")
    return value


def _user_duration_stats_cte() -> str:
    return """
        user_duration_stats AS (
            SELECT AVG(youtube_videos.duration_seconds)::numeric
              AS avg_api_duration_seconds
            FROM users
            JOIN usage_events
              ON usage_events.user_id = users.id
            JOIN youtube_videos
              ON youtube_videos.video_id = usage_events.video_id
            WHERE users.external_id = %s
              AND usage_events.is_synthetic = false
              AND usage_events.platform = 'youtube'
              AND usage_events.event_type = 'watch'
              AND youtube_videos.availability_status = 'available'
              AND youtube_videos.duration_seconds IS NOT NULL
        )
    """


def _default_duration_seconds_sql(event_alias: str) -> str:
    return f"""
        CASE
            WHEN {event_alias}.platform = 'youtube'
             AND {event_alias}.product = 'shorts'
            THEN {DEFAULT_PLATFORM_DURATION_SECONDS[("youtube", "shorts")]}::numeric
            WHEN {event_alias}.platform = 'youtube'
            THEN {DEFAULT_PLATFORM_DURATION_SECONDS[("youtube", "long")]}::numeric
            WHEN {event_alias}.platform = 'tiktok'
            THEN {DEFAULT_PLATFORM_DURATION_SECONDS[("tiktok", None)]}::numeric
            WHEN {event_alias}.platform = 'instagram'
            THEN {DEFAULT_PLATFORM_DURATION_SECONDS[("instagram", None)]}::numeric
            WHEN {event_alias}.platform = 'spotify'
            THEN {DEFAULT_PLATFORM_DURATION_SECONDS[("spotify", None)]}::numeric
            WHEN {event_alias}.platform = 'linkedin'
            THEN {DEFAULT_PLATFORM_DURATION_SECONDS[("linkedin", None)]}::numeric
            ELSE %s::numeric
        END
    """


def _event_rows_cte(query: StructuredQuery, where_sql: str) -> str:
    dimensions = _dimension_select_parts(
        query,
        _dimension_sql_by_name(
            EVENT_DIMENSION_SQL,
            timestamp_sql="ue.occurred_at",
            bucket_timezone=query.bucket_timezone,
        ),
    )
    default_duration_sql = _default_duration_seconds_sql("ue")
    clipped_api_duration_sql = _clipped_duration_seconds_sql(
        "raw_api_duration_seconds"
    )
    clipped_estimated_duration_sql = _clipped_duration_seconds_sql(
        "base_estimated_duration_seconds"
    )
    return f"""
        event_base_rows AS (
            SELECT
                {dimensions},
                ue.id AS event_id,
                ue.occurred_at,
                ue.video_id,
                COALESCE(ue.channel_id, yv.channel_id) AS metric_channel_id,
                NULL::uuid AS subscription_id,
                ue.event_type AS metric_event_type,
                ue.platform AS metric_platform,
                CASE
                    WHEN yv.availability_status = 'available'
                     AND yv.duration_seconds IS NOT NULL
                    THEN yv.duration_seconds::numeric
                    ELSE NULL::numeric
                END AS raw_api_duration_seconds,
                CASE
                    WHEN ue.duration_seconds IS NOT NULL
                    THEN ue.duration_seconds::numeric
                    WHEN yv.availability_status = 'available'
                     AND yv.duration_seconds IS NOT NULL
                    THEN yv.duration_seconds::numeric
                    WHEN ue.is_synthetic = false
                     AND ue.platform = 'youtube'
                     AND uds.avg_api_duration_seconds IS NOT NULL
                    THEN uds.avg_api_duration_seconds
                    ELSE {default_duration_sql}
                END AS base_estimated_duration_seconds,
                CASE
                    WHEN ue.duration_seconds IS NOT NULL
                    THEN 'event_duration'
                    WHEN yv.availability_status = 'available'
                     AND yv.duration_seconds IS NOT NULL
                    THEN 'api'
                    WHEN ue.is_synthetic = false
                     AND ue.platform = 'youtube'
                     AND uds.avg_api_duration_seconds IS NOT NULL
                    THEN 'user_average'
                    ELSE 'global_default'
                END AS duration_bucket,
                yv.availability_status,
                COALESCE(yv.max_duration_applied, false) AS max_duration_applied,
                (
                    SELECT MIN(next_ue.occurred_at)
                    FROM usage_events next_ue
                    WHERE next_ue.user_id = ue.user_id
                      AND next_ue.platform = ue.platform
                      AND next_ue.event_type = 'watch'
                      AND next_ue.occurred_at IS NOT NULL
                      AND ue.occurred_at IS NOT NULL
                      AND next_ue.occurred_at > ue.occurred_at
                ) AS next_watch_started_at
            FROM usage_events ue
            JOIN users u
              ON u.id = ue.user_id
            LEFT JOIN youtube_videos yv
              ON yv.video_id = ue.video_id
            CROSS JOIN user_duration_stats uds
            {where_sql}
        ),
        event_rows AS (
            SELECT
                {", ".join(query.dimensions) if query.dimensions else "1 AS __all_rows"},
                event_id,
                video_id,
                metric_channel_id,
                subscription_id,
                metric_event_type,
                metric_platform,
                {clipped_api_duration_sql} AS api_duration_seconds,
                {clipped_estimated_duration_sql} AS estimated_duration_seconds,
                duration_bucket,
                availability_status,
                max_duration_applied
            FROM event_base_rows
        )
    """


def _clipped_duration_seconds_sql(duration_column: str) -> str:
    return f"""
        CASE
            WHEN {duration_column} IS NOT NULL
             AND metric_event_type = 'watch'
             AND occurred_at IS NOT NULL
             AND next_watch_started_at IS NOT NULL
            THEN LEAST(
                {duration_column},
                GREATEST(
                    0::numeric,
                    EXTRACT(EPOCH FROM next_watch_started_at - occurred_at)::numeric
                )
            )
            ELSE {duration_column}
        END
    """


def _subscription_rows_cte(query: StructuredQuery, where_sql: str) -> str:
    dimensions = _dimension_select_parts(
        query,
        _dimension_sql_by_name(
            SUBSCRIPTION_DIMENSION_SQL,
            timestamp_sql="s.created_at",
            bucket_timezone=query.bucket_timezone,
        ),
    )
    return f"""
        subscription_rows AS (
            SELECT
                {dimensions},
                NULL::uuid AS event_id,
                NULL::text AS video_id,
                s.channel_id AS metric_channel_id,
                s.id AS subscription_id,
                NULL::text AS metric_event_type,
                'youtube'::text AS metric_platform,
                NULL::numeric AS api_duration_seconds,
                NULL::numeric AS estimated_duration_seconds,
                NULL::text AS duration_bucket,
                NULL::text AS availability_status,
                false AS max_duration_applied
            FROM subscriptions s
            JOIN users u
              ON u.id = s.user_id
            {where_sql}
        )
    """


def _dimension_select_parts(
    query: StructuredQuery, dimension_sql_by_name: dict[str, str]
) -> str:
    if not query.dimensions:
        return "1 AS __all_rows"
    return ", ".join(
        f"{dimension_sql_by_name[dimension]} AS {dimension}"
        for dimension in query.dimensions
    )


def _dimension_sql_by_name(
    static_dimension_sql: dict[str, str],
    *,
    timestamp_sql: str,
    bucket_timezone: str,
) -> dict[str, str]:
    bucket_timestamp_sql = _bucket_timestamp_sql(
        timestamp_sql,
        bucket_timezone=bucket_timezone,
    )
    return {
        "date": f"to_char({bucket_timestamp_sql}, 'YYYY-MM-DD')",
        "hour": f"EXTRACT(HOUR FROM {bucket_timestamp_sql})::int",
        "weekday": f"EXTRACT(ISODOW FROM {bucket_timestamp_sql})::int",
        "month": f"to_char({bucket_timestamp_sql}, 'YYYY-MM')",
        **static_dimension_sql,
    }


def _bucket_timestamp_sql(timestamp_sql: str, *, bucket_timezone: str) -> str:
    if bucket_timezone != "UTC":
        raise QueryValidationError("invalid_options")
    return f"{timestamp_sql} AT TIME ZONE 'UTC'"


def _source_where_clause(
    query: StructuredQuery, *, source: str
) -> tuple[str, list[object]]:
    filters = query.filters
    clauses, parameters = _population_scope_clause(query, source=source)
    if source == "event":
        timestamp_sql = "ue.occurred_at"
        filter_columns = {
            "event_type": "ue.event_type",
            "platform": "ue.platform",
            "product": "ue.product",
            "age": "u.age",
            "age_bucket": "u.age_bucket",
            "sex": "u.sex",
            "cohort": "u.cohort",
        }
    else:
        timestamp_sql = "s.created_at"
        filter_columns = {
            "event_type": "NULL::text",
            "platform": "'youtube'::text",
            "product": "'youtube'::text",
            "age": "u.age",
            "age_bucket": "u.age_bucket",
            "sex": "u.sex",
            "cohort": "u.cohort",
        }

    if "start_date" in filters:
        clauses.append(
            f"{timestamp_sql} >= "
            f"{_utc_date_filter_boundary_sql(end_of_day=False)}"
        )
        parameters.append(filters["start_date"])
    if "end_date" in filters:
        clauses.append(
            f"{timestamp_sql} < "
            f"{_utc_date_filter_boundary_sql(end_of_day=True)}"
        )
        parameters.append(filters["end_date"])
    for name, column_sql in filter_columns.items():
        if name not in filters:
            continue
        value = filters[name]
        if isinstance(value, list):
            clauses.append(f"{column_sql} = ANY(%s)")
        else:
            clauses.append(f"{column_sql} = %s")
        parameters.append(value)

    return "WHERE " + " AND ".join(clauses), parameters


def _population_scope_clause(
    query: StructuredQuery, *, source: str
) -> tuple[list[str], list[object]]:
    synthetic_filter = query.filters.get("is_synthetic")
    if source == "event":
        if synthetic_filter is True:
            return ["ue.is_synthetic = true"], []
        if synthetic_filter is False:
            return ["u.external_id = %s", "ue.is_synthetic = false"], [query.user_id]
        if "is_synthetic" in query.dimensions:
            return ["(u.external_id = %s OR ue.is_synthetic = true)"], [query.user_id]
        return ["u.external_id = %s", "ue.is_synthetic = false"], [query.user_id]

    if synthetic_filter is True:
        return ["false"], []
    return ["u.external_id = %s"], [query.user_id]


def _utc_date_filter_boundary_sql(*, end_of_day: bool) -> str:
    if end_of_day:
        return "((%s::date + INTERVAL '1 day')::timestamp AT TIME ZONE 'UTC')"
    return "(%s::date::timestamp AT TIME ZONE 'UTC')"


def _response_options(query: StructuredQuery) -> dict[str, object]:
    options: dict[str, object] = {
        "include_zero_buckets": query.include_zero_buckets,
        "limit": query.limit,
    }
    if query.sort_by is not None:
        options["sort_by"] = query.sort_by
        options["sort_direction"] = query.sort_direction
    return options


def _platform_duration_defaults_payload() -> dict[str, int]:
    return {
        "youtube_long": DEFAULT_PLATFORM_DURATION_SECONDS[("youtube", "long")],
        "youtube_shorts": DEFAULT_PLATFORM_DURATION_SECONDS[("youtube", "shorts")],
        "tiktok": DEFAULT_PLATFORM_DURATION_SECONDS[("tiktok", None)],
        "instagram": DEFAULT_PLATFORM_DURATION_SECONDS[("instagram", None)],
        "spotify": DEFAULT_PLATFORM_DURATION_SECONDS[("spotify", None)],
        "linkedin": DEFAULT_PLATFORM_DURATION_SECONDS[("linkedin", None)],
    }


def _fetch_rows(connection, compiled: CompiledSql) -> list[dict[str, object]]:
    cursor = connection.execute(compiled.sql, compiled.parameters)
    return _cursor_rows(cursor)


def _fetch_one(connection, compiled: CompiledSql) -> dict[str, object]:
    rows = _fetch_rows(connection, compiled)
    if not rows:
        return {}
    return rows[0]


def _cursor_rows(cursor) -> list[dict[str, object]]:
    raw_rows = cursor.fetchall()
    if not raw_rows:
        return []
    if isinstance(raw_rows[0], dict):
        return [_normalize_values(dict(row)) for row in raw_rows]

    columns = [_column_name(column) for column in cursor.description]
    return [_normalize_values(dict(zip(columns, row, strict=True))) for row in raw_rows]


def _column_name(column: object) -> str:
    name = getattr(column, "name", None)
    if name is not None:
        return str(name)
    return str(column[0])


def _normalize_values(row: dict[str, object]) -> dict[str, object]:
    normalized: dict[str, object] = {}
    for key, value in row.items():
        if isinstance(value, Decimal):
            normalized[key] = int(value) if value == value.to_integral_value() else float(value)
        else:
            normalized[key] = value
    return normalized


def _normalize_quality(row: dict[str, object]) -> dict[str, int]:
    return {
        "events_counted": int(row.get("events_counted", 0) or 0),
        "events_with_api_duration": int(
            row.get("events_with_api_duration", 0) or 0
        ),
        "events_with_user_average_estimate": int(
            row.get("events_with_user_average_estimate", 0) or 0
        ),
        "events_with_global_default_estimate": int(
            row.get("events_with_global_default_estimate", 0) or 0
        ),
        "videos_unavailable": int(row.get("videos_unavailable", 0) or 0),
        "videos_capped": int(row.get("videos_capped", 0) or 0),
    }


def _zero_fill_rows(
    rows: list[dict[str, object]], query: StructuredQuery
) -> list[dict[str, object]]:
    if not _should_zero_fill_hourly(query):
        return rows

    row_by_key = {
        (str(row.get("date")), int(row.get("hour"))): row
        for row in rows
        if row.get("date") is not None and row.get("hour") is not None
    }
    start_date = date.fromisoformat(str(query.filters["start_date"]))
    end_date = date.fromisoformat(str(query.filters["end_date"]))
    filled: list[dict[str, object]] = []
    current = start_date
    while current <= end_date and len(filled) < query.limit:
        date_key = current.isoformat()
        for hour in range(24):
            row = row_by_key.get((date_key, hour))
            if row is None:
                row = {"date": date_key, "hour": hour}
                for metric in query.metrics:
                    row[metric] = 0
            filled.append(row)
            if len(filled) >= query.limit:
                break
        current += timedelta(days=1)
    return filled


def _should_zero_fill_hourly(query: StructuredQuery) -> bool:
    return (
        query.include_zero_buckets
        and set(query.dimensions) == {"date", "hour"}
        and "start_date" in query.filters
        and "end_date" in query.filters
    )


def _compact_sql(sql: str) -> str:
    return " ".join(sql.split())
