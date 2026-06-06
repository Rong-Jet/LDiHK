from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import uuid
from contextlib import closing
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import urlopen
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup
from dotenv import load_dotenv

from backend.youtube_usage import (
    DEFAULT_INPUT_PATH,
    DEFAULT_PERSON_ID,
    DEFAULT_TIMEZONE,
    SCHEMA_VERSION as SOURCE_SCHEMA_VERSION,
    parse_card,
)


DEFAULT_SQLITE_PATH = Path("data/processed/users/local_user/youtube_usage.v3.sqlite")
SCHEMA_VERSION = "youtube_usage.sql.v3"
QUERY_SCHEMA_VERSION = "youtube_usage.query.v3"
DEFAULT_MAX_DURATION_SECONDS = 5400
SESSION_GAP_SECONDS = 1800

ALLOWED_METRICS = {
    "event_count",
    "watch_seconds",
    "session_count",
    "events_missing_duration",
}
ALLOWED_DIMENSIONS = {"date", "hour", "weekday", "month"}
ALLOWED_FILTERS = {"person_id", "start_date", "end_date"}
DIMENSION_SQL = {
    "date": "substr(we.watched_at, 1, 10)",
    "hour": "CAST(substr(we.watched_at, 12, 2) AS INTEGER)",
    "weekday": (
        "((CAST(strftime('%w', substr(we.watched_at, 1, 10)) AS INTEGER) + 6) "
        "% 7) + 1"
    ),
    "month": "substr(we.watched_at, 1, 7)",
}
METRIC_SQL = {
    "event_count": "COUNT(*)",
    "watch_seconds": (
        "COALESCE(SUM(CASE WHEN vm.availability_status = 'available' "
        "AND vm.duration_seconds IS NOT NULL THEN vm.duration_seconds ELSE 0 END), 0)"
    ),
    "events_missing_duration": (
        "COALESCE(SUM(CASE WHEN vm.availability_status = 'available' "
        "AND vm.duration_seconds IS NOT NULL THEN 0 ELSE 1 END), 0)"
    ),
}


class QueryValidationError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class ImportSummary:
    database_path: Path
    events_imported: int


@dataclass(frozen=True)
class EnrichmentSummary:
    run_id: str
    requested_video_count: int
    successful_video_count: int
    unavailable_video_count: int
    failed_video_count: int


class YouTubeDataApiClient:
    def __init__(self, api_key: str):
        self.api_key = api_key

    def list_videos(self, video_ids: list[str]) -> list[dict[str, object]]:
        query = urlencode(
            {
                "part": "contentDetails,status",
                "id": ",".join(video_ids),
                "key": self.api_key,
            }
        )
        url = f"https://www.googleapis.com/youtube/v3/videos?{query}"
        with urlopen(url, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
        items = payload.get("items", [])
        if not isinstance(items, list):
            return []
        return [item for item in items if isinstance(item, dict)]


def import_youtube_usage_sql(
    input_path: Path | str = DEFAULT_INPUT_PATH,
    database_path: Path | str = DEFAULT_SQLITE_PATH,
    person_id: str = DEFAULT_PERSON_ID,
    timezone: str = DEFAULT_TIMEZONE,
) -> ImportSummary:
    input_path = Path(input_path)
    database_path = Path(database_path)
    database_path.parent.mkdir(parents=True, exist_ok=True)

    html = input_path.read_text(encoding="utf-8")
    soup = BeautifulSoup(html, "lxml")
    now = _now(timezone)

    with closing(sqlite3.connect(database_path)) as connection:
        with connection:
            create_schema(connection)
            connection.execute(
                """
                INSERT INTO users (person_id, created_at)
                VALUES (?, ?)
                ON CONFLICT(person_id) DO NOTHING
                """,
                (person_id, now),
            )
            connection.execute(
                "DELETE FROM watch_events WHERE person_id = ?", (person_id,)
            )

            events_imported = 0
            for index, card in enumerate(soup.select("div.outer-cell")):
                event, _warning = parse_card(card, person_id=person_id, timezone=timezone)
                if event is None:
                    continue
                if event.product != "youtube":
                    continue
                if event.event_type != "watched":
                    continue

                video_id = _extract_video_id(card)
                connection.execute(
                    """
                    INSERT INTO watch_events (
                        event_id,
                        person_id,
                        platform,
                        product,
                        event_type,
                        watched_at,
                        video_id,
                        source_schema_version,
                        created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        _event_id(person_id, event.watched_at, video_id, index),
                        event.person_id,
                        event.platform,
                        event.product,
                        event.event_type,
                        event.watched_at,
                        video_id,
                        SOURCE_SCHEMA_VERSION,
                        now,
                    ),
                )
                events_imported += 1

    return ImportSummary(database_path=database_path, events_imported=events_imported)


def enrich_youtube_durations(
    database_path: Path | str = DEFAULT_SQLITE_PATH,
    *,
    api_key: str | None = None,
    client: object | None = None,
    env_path: Path | str | None = None,
    max_duration_seconds: int = 5400,
    refresh: bool = False,
    timezone: str = DEFAULT_TIMEZONE,
) -> EnrichmentSummary:
    database_path = Path(database_path)
    if env_path is None:
        load_dotenv()
    else:
        load_dotenv(dotenv_path=Path(env_path))
    api_key = api_key or os.environ.get("YOUTUBE_API_KEY")
    if client is None:
        if not api_key:
            raise RuntimeError("youtube_api_key_missing")
        client = YouTubeDataApiClient(api_key)

    started_at = _now(timezone)
    run_id = uuid.uuid4().hex
    successful = 0
    unavailable = 0
    failed = 0

    with closing(sqlite3.connect(database_path)) as connection:
        with connection:
            create_schema(connection)
            video_ids = _video_ids_to_enrich(connection, refresh=refresh)

            for batch in _batches(video_ids, 50):
                try:
                    returned_items = client.list_videos(batch)
                except Exception as error:  # pragma: no cover - covered by CLI usage
                    failed += len(batch)
                    for video_id in batch:
                        _upsert_video_metadata(
                            connection,
                            video_id=video_id,
                            duration_seconds=None,
                            duration_iso8601=None,
                            availability_status="api_error",
                            max_duration_applied=0,
                            fetched_at=_now(timezone),
                            error_code=error.__class__.__name__,
                        )
                    continue

                returned_by_id = {
                    str(item["id"]): item
                    for item in returned_items
                    if isinstance(item.get("id"), str)
                }
                for video_id in batch:
                    item = returned_by_id.get(video_id)
                    if item is None:
                        unavailable += 1
                        _upsert_video_metadata(
                            connection,
                            video_id=video_id,
                            duration_seconds=None,
                            duration_iso8601=None,
                            availability_status="deleted_or_unavailable",
                            max_duration_applied=0,
                            fetched_at=_now(timezone),
                            error_code="not_returned",
                        )
                        continue

                    metadata = _metadata_from_youtube_item(
                        item,
                        max_duration_seconds=max_duration_seconds,
                        fetched_at=_now(timezone),
                    )
                    if metadata["availability_status"] == "available":
                        successful += 1
                    elif metadata["availability_status"] == "duration_parse_failed":
                        failed += 1
                    else:
                        unavailable += 1
                    _upsert_video_metadata(connection, video_id=video_id, **metadata)

            finished_at = _now(timezone)
            connection.execute(
                """
                INSERT INTO enrichment_runs (
                    run_id,
                    started_at,
                    finished_at,
                    requested_video_count,
                    successful_video_count,
                    unavailable_video_count,
                    failed_video_count
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    started_at,
                    finished_at,
                    len(video_ids),
                    successful,
                    unavailable,
                    failed,
                ),
            )

    return EnrichmentSummary(
        run_id=run_id,
        requested_video_count=len(video_ids),
        successful_video_count=successful,
        unavailable_video_count=unavailable,
        failed_video_count=failed,
    )


def query_youtube_usage(
    database_path: Path | str,
    request_payload: object,
    *,
    max_duration_seconds: int = DEFAULT_MAX_DURATION_SECONDS,
) -> dict[str, object]:
    query = _validate_query_request(request_payload)
    with closing(sqlite3.connect(Path(database_path))) as connection:
        rows = _aggregate_query_rows(connection, query)
        if "session_count" in query["metrics"]:
            _merge_session_counts(connection, query, rows)
        rows = _zero_fill_rows(rows, query)
        quality = _query_quality(connection, query)

    return {
        "schema_version": QUERY_SCHEMA_VERSION,
        "dataset": query["dataset"],
        "person_id": query["person_id"],
        "duration_strategy": {
            "kind": "youtube_data_api",
            "max_duration_seconds": max_duration_seconds,
            "unknown_duration_policy": "count_event_exclude_duration",
        },
        "query": {
            "metrics": query["metrics"],
            "dimensions": query["dimensions"],
            "filters": query["filters"],
        },
        "quality": quality,
        "rows": rows,
    }


def create_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
          person_id TEXT PRIMARY KEY,
          created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS watch_events (
          event_id TEXT PRIMARY KEY,
          person_id TEXT NOT NULL,
          platform TEXT NOT NULL,
          product TEXT NOT NULL,
          event_type TEXT NOT NULL,
          watched_at TEXT NOT NULL,
          video_id TEXT,
          source_schema_version TEXT NOT NULL,
          created_at TEXT NOT NULL,
          FOREIGN KEY (person_id) REFERENCES users(person_id)
        );

        CREATE TABLE IF NOT EXISTS video_metadata (
          video_id TEXT PRIMARY KEY,
          duration_seconds INTEGER,
          duration_iso8601 TEXT,
          duration_source TEXT NOT NULL,
          availability_status TEXT NOT NULL,
          max_duration_applied INTEGER NOT NULL DEFAULT 0,
          fetched_at TEXT,
          error_code TEXT
        );

        CREATE TABLE IF NOT EXISTS enrichment_runs (
          run_id TEXT PRIMARY KEY,
          started_at TEXT NOT NULL,
          finished_at TEXT,
          requested_video_count INTEGER NOT NULL,
          successful_video_count INTEGER NOT NULL,
          unavailable_video_count INTEGER NOT NULL,
          failed_video_count INTEGER NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_watch_events_person_watched_at
          ON watch_events (person_id, watched_at);
        CREATE INDEX IF NOT EXISTS idx_watch_events_video_id
          ON watch_events (video_id);
        """
    )


def parse_youtube_duration(duration: str) -> int:
    match = re.fullmatch(
        r"P"
        r"(?:(?P<weeks>\d+)W)?"
        r"(?:(?P<days>\d+)D)?"
        r"(?:T"
        r"(?:(?P<hours>\d+)H)?"
        r"(?:(?P<minutes>\d+)M)?"
        r"(?:(?P<seconds>\d+)S)?"
        r")?",
        duration,
    )
    if match is None:
        raise ValueError(f"unsupported YouTube duration: {duration}")
    parts = {key: int(value or 0) for key, value in match.groupdict().items()}
    if not any(parts.values()) and duration != "PT0S":
        raise ValueError(f"unsupported YouTube duration: {duration}")
    return (
        parts["weeks"] * 7 * 24 * 60 * 60
        + parts["days"] * 24 * 60 * 60
        + parts["hours"] * 60 * 60
        + parts["minutes"] * 60
        + parts["seconds"]
    )


def _validate_query_request(request_payload: object) -> dict[str, object]:
    if not isinstance(request_payload, dict):
        raise QueryValidationError("invalid_request")
    if "sql" in request_payload:
        raise QueryValidationError("raw_sql_not_allowed")

    dataset = request_payload.get("dataset")
    if dataset != "youtube_usage":
        raise QueryValidationError("invalid_dataset")

    person_id = request_payload.get("person_id")
    if not isinstance(person_id, str) or not person_id:
        raise QueryValidationError("invalid_person_id")

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
    if any(filter_name not in ALLOWED_FILTERS for filter_name in filters):
        raise QueryValidationError("invalid_filter")

    normalized_filters = dict(filters)
    if "person_id" in normalized_filters and normalized_filters["person_id"] != person_id:
        raise QueryValidationError("invalid_person_filter")
    normalized_filters["person_id"] = person_id

    for key in ("start_date", "end_date"):
        if key in normalized_filters:
            value = normalized_filters[key]
            if not isinstance(value, str):
                raise QueryValidationError("invalid_date_filter")
            try:
                date.fromisoformat(value)
            except ValueError as error:
                raise QueryValidationError("invalid_date_filter") from error

    if (
        "start_date" in normalized_filters
        and "end_date" in normalized_filters
        and normalized_filters["start_date"] > normalized_filters["end_date"]
    ):
        raise QueryValidationError("invalid_date_range")

    if "include_zero_buckets" in options and not isinstance(
        options["include_zero_buckets"], bool
    ):
        raise QueryValidationError("invalid_options")

    return {
        "dataset": dataset,
        "person_id": person_id,
        "metrics": metrics,
        "dimensions": dimensions,
        "filters": normalized_filters,
        "options": {"include_zero_buckets": bool(options.get("include_zero_buckets"))},
    }


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


def _aggregate_query_rows(
    connection: sqlite3.Connection, query: dict[str, object]
) -> list[dict[str, object]]:
    dimensions = query["dimensions"]
    metrics = [metric for metric in query["metrics"] if metric != "session_count"]
    select_parts = [f"{DIMENSION_SQL[dimension]} AS {dimension}" for dimension in dimensions]
    select_parts.extend(f"{METRIC_SQL[metric]} AS {metric}" for metric in metrics)
    if not select_parts:
        select_parts.append("0 AS session_count")

    where_sql, parameters = _where_clause(query)
    group_sql = ""
    if dimensions:
        group_sql = " GROUP BY " + ", ".join(DIMENSION_SQL[dimension] for dimension in dimensions)
    order_sql = ""
    if dimensions:
        order_sql = " ORDER BY " + ", ".join(DIMENSION_SQL[dimension] for dimension in dimensions)

    sql = f"""
        SELECT {", ".join(select_parts)}
        FROM watch_events we
        LEFT JOIN video_metadata vm
          ON vm.video_id = we.video_id
        {where_sql}
        {group_sql}
        {order_sql}
    """
    connection.row_factory = sqlite3.Row
    raw_rows = connection.execute(sql, parameters).fetchall()
    rows = [dict(row) for row in raw_rows]
    for row in rows:
        for metric in query["metrics"]:
            row.setdefault(metric, 0)
    return rows


def _merge_session_counts(
    connection: sqlite3.Connection, query: dict[str, object], rows: list[dict[str, object]]
) -> None:
    dimensions = query["dimensions"]
    row_by_key = {_row_key(row, dimensions): row for row in rows}
    for key, count in _session_counts_by_key(connection, query).items():
        if key not in row_by_key:
            row = {
                dimension: value for dimension, value in zip(dimensions, key, strict=True)
            }
            for metric in query["metrics"]:
                row[metric] = 0
            rows.append(row)
            row_by_key[key] = row
        row_by_key[key]["session_count"] = count
    rows.sort(key=lambda row: _row_key(row, dimensions))


def _session_counts_by_key(
    connection: sqlite3.Connection, query: dict[str, object]
) -> dict[tuple[object, ...], int]:
    where_sql, parameters = _where_clause(query)
    connection.row_factory = sqlite3.Row
    events = connection.execute(
        f"""
        SELECT we.watched_at, vm.duration_seconds, vm.availability_status
        FROM watch_events we
        LEFT JOIN video_metadata vm
          ON vm.video_id = we.video_id
        {where_sql}
        ORDER BY we.watched_at
        """,
        parameters,
    ).fetchall()

    sessions: list[tuple[datetime, datetime]] = []
    current_start: datetime | None = None
    current_end: datetime | None = None
    gap = timedelta(seconds=SESSION_GAP_SECONDS)
    for event in events:
        start = datetime.fromisoformat(event["watched_at"])
        duration_seconds = (
            event["duration_seconds"]
            if event["availability_status"] == "available"
            and event["duration_seconds"] is not None
            else 0
        )
        end = start + timedelta(seconds=duration_seconds)
        if current_start is None or current_end is None:
            current_start = start
            current_end = end
            continue
        if start - current_end <= gap:
            current_end = max(current_end, end)
            continue
        sessions.append((current_start, current_end))
        current_start = start
        current_end = end
    if current_start is not None and current_end is not None:
        sessions.append((current_start, current_end))

    counts: dict[tuple[object, ...], int] = {}
    for start, _end in sessions:
        key = tuple(_dimension_value(start, dimension) for dimension in query["dimensions"])
        counts[key] = counts.get(key, 0) + 1
    return counts


def _query_quality(
    connection: sqlite3.Connection, query: dict[str, object]
) -> dict[str, int]:
    where_sql, parameters = _where_clause(query)
    row = connection.execute(
        f"""
        SELECT
            COUNT(*) AS events_counted,
            COALESCE(SUM(CASE WHEN vm.availability_status = 'available'
              AND vm.duration_seconds IS NOT NULL THEN 1 ELSE 0 END), 0)
              AS events_with_duration,
            COALESCE(SUM(CASE WHEN vm.availability_status = 'available'
              AND vm.duration_seconds IS NOT NULL THEN 0 ELSE 1 END), 0)
              AS events_missing_duration,
            COUNT(DISTINCT CASE WHEN vm.max_duration_applied = 1 THEN vm.video_id END)
              AS videos_capped
        FROM watch_events we
        LEFT JOIN video_metadata vm
          ON vm.video_id = we.video_id
        {where_sql}
        """,
        parameters,
    ).fetchone()
    return {
        "events_counted": int(row[0]),
        "events_with_duration": int(row[1]),
        "events_missing_duration": int(row[2]),
        "videos_capped": int(row[3]),
    }


def _where_clause(query: dict[str, object]) -> tuple[str, list[object]]:
    filters = query["filters"]
    clauses = [
        "we.person_id = ?",
        "we.platform = 'youtube'",
        "we.product = 'youtube'",
        "we.event_type = 'watched'",
    ]
    parameters: list[object] = [filters["person_id"]]
    if "start_date" in filters:
        clauses.append("substr(we.watched_at, 1, 10) >= ?")
        parameters.append(filters["start_date"])
    if "end_date" in filters:
        clauses.append("substr(we.watched_at, 1, 10) <= ?")
        parameters.append(filters["end_date"])
    return "WHERE " + " AND ".join(clauses), parameters


def _zero_fill_rows(
    rows: list[dict[str, object]], query: dict[str, object]
) -> list[dict[str, object]]:
    if not query["options"]["include_zero_buckets"]:
        return rows
    dimensions = query["dimensions"]
    if dimensions not in (["date"], ["date", "hour"]):
        return rows

    start_date = _zero_fill_boundary(query, rows, "start_date")
    end_date = _zero_fill_boundary(query, rows, "end_date")
    if start_date is None or end_date is None:
        return rows

    row_by_key = {_row_key(row, dimensions): row for row in rows}
    cursor = start_date
    while cursor <= end_date:
        if dimensions == ["date"]:
            _ensure_zero_row(row_by_key, query, (cursor.isoformat(),))
        else:
            for hour in range(24):
                _ensure_zero_row(row_by_key, query, (cursor.isoformat(), hour))
        cursor += timedelta(days=1)

    return sorted(row_by_key.values(), key=lambda row: _row_key(row, dimensions))


def _zero_fill_boundary(
    query: dict[str, object], rows: list[dict[str, object]], filter_name: str
) -> date | None:
    filters = query["filters"]
    if filter_name in filters:
        return date.fromisoformat(filters[filter_name])
    if not rows:
        return None
    row_dates = [date.fromisoformat(str(row["date"])) for row in rows]
    return min(row_dates) if filter_name == "start_date" else max(row_dates)


def _ensure_zero_row(
    row_by_key: dict[tuple[object, ...], dict[str, object]],
    query: dict[str, object],
    key: tuple[object, ...],
) -> None:
    if key in row_by_key:
        return
    row = {
        dimension: value
        for dimension, value in zip(query["dimensions"], key, strict=True)
    }
    for metric in query["metrics"]:
        row[metric] = 0
    row_by_key[key] = row


def _row_key(row: dict[str, object], dimensions: list[str]) -> tuple[object, ...]:
    return tuple(row[dimension] for dimension in dimensions)


def _dimension_value(value: datetime, dimension: str) -> object:
    if dimension == "date":
        return value.date().isoformat()
    if dimension == "hour":
        return value.hour
    if dimension == "weekday":
        return value.isoweekday()
    if dimension == "month":
        return f"{value.year:04d}-{value.month:02d}"
    raise QueryValidationError("invalid_dimension")


def _video_ids_to_enrich(connection: sqlite3.Connection, *, refresh: bool) -> list[str]:
    if refresh:
        rows = connection.execute(
            """
            SELECT DISTINCT video_id
            FROM watch_events
            WHERE video_id IS NOT NULL
            ORDER BY video_id
            """
        ).fetchall()
    else:
        rows = connection.execute(
            """
            SELECT DISTINCT watch_events.video_id
            FROM watch_events
            LEFT JOIN video_metadata
              ON video_metadata.video_id = watch_events.video_id
            WHERE watch_events.video_id IS NOT NULL
              AND video_metadata.video_id IS NULL
            ORDER BY watch_events.video_id
            """
        ).fetchall()
    return [row[0] for row in rows]


def _metadata_from_youtube_item(
    item: dict[str, object], *, max_duration_seconds: int, fetched_at: str
) -> dict[str, object]:
    status = item.get("status")
    content_details = item.get("contentDetails")
    privacy_status = ""
    upload_status = ""
    if isinstance(status, dict):
        privacy_status = str(status.get("privacyStatus", ""))
        upload_status = str(status.get("uploadStatus", ""))
    if privacy_status == "private":
        return {
            "duration_seconds": None,
            "duration_iso8601": None,
            "duration_source": "youtube_data_api",
            "availability_status": "private_or_restricted",
            "max_duration_applied": 0,
            "fetched_at": fetched_at,
            "error_code": privacy_status,
        }
    if upload_status in {"failed", "rejected"}:
        return {
            "duration_seconds": None,
            "duration_iso8601": None,
            "duration_source": "youtube_data_api",
            "availability_status": "api_error",
            "max_duration_applied": 0,
            "fetched_at": fetched_at,
            "error_code": upload_status,
        }
    if not isinstance(content_details, dict):
        return {
            "duration_seconds": None,
            "duration_iso8601": None,
            "duration_source": "youtube_data_api",
            "availability_status": "deleted_or_unavailable",
            "max_duration_applied": 0,
            "fetched_at": fetched_at,
            "error_code": "missing_content_details",
        }

    duration = content_details.get("duration")
    if not isinstance(duration, str):
        return {
            "duration_seconds": None,
            "duration_iso8601": None,
            "duration_source": "youtube_data_api",
            "availability_status": "duration_parse_failed",
            "max_duration_applied": 0,
            "fetched_at": fetched_at,
            "error_code": "missing_duration",
        }

    try:
        parsed_seconds = parse_youtube_duration(duration)
    except ValueError:
        return {
            "duration_seconds": None,
            "duration_iso8601": duration,
            "duration_source": "youtube_data_api",
            "availability_status": "duration_parse_failed",
            "max_duration_applied": 0,
            "fetched_at": fetched_at,
            "error_code": "duration_parse_failed",
        }

    capped_seconds = min(parsed_seconds, max_duration_seconds)
    return {
        "duration_seconds": capped_seconds,
        "duration_iso8601": duration,
        "duration_source": "youtube_data_api",
        "availability_status": "available",
        "max_duration_applied": 1 if capped_seconds != parsed_seconds else 0,
        "fetched_at": fetched_at,
        "error_code": None,
    }


def _upsert_video_metadata(
    connection: sqlite3.Connection,
    *,
    video_id: str,
    duration_seconds: int | None,
    duration_iso8601: str | None,
    duration_source: str = "youtube_data_api",
    availability_status: str,
    max_duration_applied: int,
    fetched_at: str,
    error_code: str | None,
) -> None:
    connection.execute(
        """
        INSERT INTO video_metadata (
            video_id,
            duration_seconds,
            duration_iso8601,
            duration_source,
            availability_status,
            max_duration_applied,
            fetched_at,
            error_code
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(video_id) DO UPDATE SET
            duration_seconds = excluded.duration_seconds,
            duration_iso8601 = excluded.duration_iso8601,
            duration_source = excluded.duration_source,
            availability_status = excluded.availability_status,
            max_duration_applied = excluded.max_duration_applied,
            fetched_at = excluded.fetched_at,
            error_code = excluded.error_code
        """,
        (
            video_id,
            duration_seconds,
            duration_iso8601,
            duration_source,
            availability_status,
            max_duration_applied,
            fetched_at,
            error_code,
        ),
    )


def _batches(values: list[str], batch_size: int) -> list[list[str]]:
    return [values[index : index + batch_size] for index in range(0, len(values), batch_size)]


def _extract_video_id(card) -> str | None:
    for link in card.select("a[href]"):
        video_id = _video_id_from_url(link["href"])
        if video_id is not None:
            return video_id
    return None


def _video_id_from_url(url: str) -> str | None:
    parsed = urlparse(url)
    hostname = parsed.hostname or ""
    if hostname.endswith("youtube.com") and parsed.path == "/watch":
        values = parse_qs(parsed.query).get("v", [])
        if values and values[0]:
            return values[0]
    if hostname == "youtu.be":
        video_id = parsed.path.strip("/")
        return video_id or None
    return None


def _event_id(
    person_id: str, watched_at: str, video_id: str | None, sequence: int
) -> str:
    raw = f"{person_id}|{watched_at}|{video_id or ''}|{sequence}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _now(timezone: str) -> str:
    return datetime.now(ZoneInfo(timezone)).replace(microsecond=0).isoformat()
