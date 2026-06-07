from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


SCHEMA_VERSION = "youtube_usage.temporal.v2"
WATCHED_EVENT_SECONDS = 600
SESSION_GAP_SECONDS = 1800


@dataclass(frozen=True)
class WatchedInterval:
    start: datetime
    end: datetime


@dataclass(frozen=True)
class Session:
    start: datetime
    end: datetime
    event_count: int


def build_temporal_usage(v1_payload: dict[str, object]) -> dict[str, object]:
    intervals = _watched_intervals(v1_payload)
    sessions = _build_sessions(intervals)

    return {
        "person_id": v1_payload.get("person_id", "local_user"),
        "schema_version": SCHEMA_VERSION,
        "source_schema_version": v1_payload.get("schema_version"),
        "duration_strategy": {
            "kind": "fixed_placeholder",
            "watched_event_seconds": WATCHED_EVENT_SECONDS,
            "is_estimate": True,
        },
        "daily": _daily(intervals, sessions),
        "hourly_heatmap": _hourly_heatmap(intervals),
        "sessions": _serialize_sessions(sessions),
    }


def _watched_intervals(v1_payload: dict[str, object]) -> list[WatchedInterval]:
    timezone = _source_timezone(v1_payload)
    events = v1_payload.get("events", [])
    if not isinstance(events, list):
        return []

    intervals: list[WatchedInterval] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        if event.get("product") != "youtube":
            continue
        if event.get("event_type") != "watched":
            continue

        watched_at = event.get("watched_at")
        if not isinstance(watched_at, str):
            continue

        try:
            start = datetime.fromisoformat(watched_at)
        except ValueError:
            continue
        if timezone is not None and start.tzinfo is not None:
            start = start.astimezone(timezone)
        end = start + timedelta(seconds=WATCHED_EVENT_SECONDS)
        intervals.append(WatchedInterval(start=start, end=end))

    return sorted(intervals, key=lambda interval: interval.start)


def _source_timezone(v1_payload: dict[str, object]) -> ZoneInfo | None:
    source = v1_payload.get("source")
    if not isinstance(source, dict):
        return None
    timezone = source.get("timezone")
    if not isinstance(timezone, str):
        return None
    try:
        return ZoneInfo(timezone)
    except ZoneInfoNotFoundError:
        return None


def _daily(
    intervals: list[WatchedInterval], sessions: list[Session]
) -> list[dict[str, object]]:
    if not intervals:
        return []

    dates = _date_range(intervals)
    event_counts = Counter(interval.start.date() for interval in intervals)
    session_counts = Counter(session.start.date() for session in sessions)
    estimated_seconds = _estimated_seconds_by_day(_merge_intervals(intervals))

    return [
        {
            "date": current_date.isoformat(),
            "event_count": event_counts[current_date],
            "estimated_seconds": estimated_seconds[current_date],
            "session_count": session_counts[current_date],
        }
        for current_date in dates
    ]


def _hourly_heatmap(intervals: list[WatchedInterval]) -> list[dict[str, object]]:
    if not intervals:
        return []

    dates = _date_range(intervals)
    event_counts = Counter(
        (interval.start.date(), interval.start.hour) for interval in intervals
    )
    estimated_seconds = _estimated_seconds_by_hour(_merge_intervals(intervals))

    return [
        {
            "date": current_date.isoformat(),
            "hour": hour,
            "event_count": event_counts[(current_date, hour)],
            "estimated_seconds": estimated_seconds[(current_date, hour)],
        }
        for current_date in dates
        for hour in range(24)
    ]


def _date_range(intervals: list[WatchedInterval]) -> list[date]:
    first = min(interval.start.date() for interval in intervals)
    last = max(
        (interval.end - timedelta(microseconds=1)).date() for interval in intervals
    )
    days = (last - first).days
    return [first + timedelta(days=offset) for offset in range(days + 1)]


def _merge_intervals(intervals: list[WatchedInterval]) -> list[WatchedInterval]:
    merged: list[WatchedInterval] = []
    for interval in intervals:
        if not merged or interval.start > merged[-1].end:
            merged.append(interval)
            continue
        if interval.end > merged[-1].end:
            merged[-1] = WatchedInterval(start=merged[-1].start, end=interval.end)
    return merged


def _estimated_seconds_by_day(
    intervals: list[WatchedInterval],
) -> Counter[date]:
    counts: Counter[date] = Counter()
    for interval in intervals:
        cursor = interval.start
        while cursor < interval.end:
            next_day = (cursor + timedelta(days=1)).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            bucket_end = min(interval.end, next_day)
            counts[cursor.date()] += _seconds_between(cursor, bucket_end)
            cursor = bucket_end
    return counts


def _estimated_seconds_by_hour(
    intervals: list[WatchedInterval],
) -> Counter[tuple[date, int]]:
    counts: Counter[tuple[date, int]] = Counter()
    for interval in intervals:
        cursor = interval.start
        while cursor < interval.end:
            next_hour = (cursor + timedelta(hours=1)).replace(
                minute=0, second=0, microsecond=0
            )
            bucket_end = min(interval.end, next_hour)
            counts[(cursor.date(), cursor.hour)] += _seconds_between(
                cursor, bucket_end
            )
            cursor = bucket_end
    return counts


def _build_sessions(intervals: list[WatchedInterval]) -> list[Session]:
    sessions: list[Session] = []
    current: Session | None = None
    gap = timedelta(seconds=SESSION_GAP_SECONDS)

    for interval in intervals:
        if current is None:
            current = Session(start=interval.start, end=interval.end, event_count=1)
            continue

        if interval.start - current.end <= gap:
            current = Session(
                start=current.start,
                end=max(current.end, interval.end),
                event_count=current.event_count + 1,
            )
            continue

        sessions.append(current)
        current = Session(start=interval.start, end=interval.end, event_count=1)

    if current is not None:
        sessions.append(current)
    return sessions


def _serialize_sessions(sessions: list[Session]) -> list[dict[str, object]]:
    serialized: list[dict[str, object]] = []
    for index, session in enumerate(sessions, start=1):
        span_seconds = _seconds_between(session.start, session.end)
        serialized.append(
            {
                "session_id": f"session_{index:06d}",
                "started_at": session.start.isoformat(),
                "ended_at": session.end.isoformat(),
                "observed_span_seconds": span_seconds,
                "event_count": session.event_count,
                "estimated_seconds": span_seconds,
            }
        )
    return serialized


def _seconds_between(start: datetime, end: datetime) -> int:
    return int((end - start).total_seconds())
