from __future__ import annotations

import json
import re
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any
from urllib.parse import unquote, urlparse

from backend.ingestion.models import ParseResult, ParseWarning, ParsedEvent


VIDEO_ID_RE = re.compile(r"^\d+$")
DATE_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M:%S.%f",
)
TITLE_FIELDS = (
    "Title",
    "title",
    "VideoTitle",
    "videoTitle",
    "video_title",
)


def parse_tiktok_watch_history(content: bytes, *, source_path: str) -> ParseResult:
    del source_path

    text, decode_warnings = _decode_content(content)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return ParseResult(
            events=[],
            subscriptions=[],
            warnings=decode_warnings
            + [ParseWarning(code="json_decode_failed", sample=None)],
            records_seen=0,
        )

    records = _video_list(payload)
    if records is None:
        return ParseResult(
            events=[],
            subscriptions=[],
            warnings=decode_warnings
            + [ParseWarning(code="json_shape_unsupported", sample=None)],
            records_seen=0,
        )

    events: list[ParsedEvent] = []
    warnings: list[ParseWarning] = list(decode_warnings)

    for sequence, record in enumerate(records, start=1):
        sample = _sample(sequence)
        if not isinstance(record, Mapping):
            warnings.append(ParseWarning(code="malformed_json_record", sample=sample))
            continue

        event, record_warnings = _parse_video_record(record, sequence=sequence)
        warnings.extend(record_warnings)
        if event is not None:
            events.append(event)

    return ParseResult(
        events=events,
        subscriptions=[],
        warnings=warnings,
        records_seen=len(records),
    )


def _parse_video_record(
    record: Mapping[str, Any], *, sequence: int
) -> tuple[ParsedEvent | None, list[ParseWarning]]:
    sample = _sample(sequence)
    warnings: list[ParseWarning] = []

    occurred_at, timestamp_warning = _parse_date(record.get("Date"))
    if timestamp_warning is not None:
        warnings.append(ParseWarning(code=timestamp_warning, sample=sample))

    video_id = _extract_video_id(_first_string(record, "Link", "link", "Url", "url"))
    if video_id is None:
        warnings.append(ParseWarning(code="missing_video_id", sample=sample))

    if occurred_at is None or video_id is None:
        return None, warnings

    return (
        ParsedEvent(
            platform="tiktok",
            product="shorts",
            event_type="watch",
            occurred_at=occurred_at,
            video_id=video_id,
            title=_title(record),
            sequence=sequence,
        ),
        warnings,
    )


def _decode_content(content: bytes) -> tuple[str, list[ParseWarning]]:
    try:
        return content.decode("utf-8"), []
    except UnicodeDecodeError:
        return (
            content.decode("utf-8", errors="replace"),
            [ParseWarning(code="invalid_utf8", sample=None)],
        )


def _video_list(payload: Any) -> list[Any] | None:
    if not isinstance(payload, Mapping):
        return None

    your_activity = payload.get("Your Activity")
    if not isinstance(your_activity, Mapping):
        return None

    watch_history = your_activity.get("Watch History")
    if not isinstance(watch_history, Mapping):
        return None

    video_list = watch_history.get("VideoList")
    if not isinstance(video_list, list):
        return None
    return video_list


def _parse_date(value: object) -> tuple[datetime | None, str | None]:
    if not isinstance(value, str) or not value.strip():
        return None, "missing_timestamp"

    raw_value = value.strip()
    normalized = raw_value[:-1] + "+00:00" if raw_value.endswith("Z") else raw_value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        parsed = None

    if parsed is None:
        for date_format in DATE_FORMATS:
            try:
                parsed = datetime.strptime(raw_value, date_format)
            except ValueError:
                continue
            break

    if parsed is None:
        return None, "timestamp_parse_failed"

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc), None
    return parsed.astimezone(timezone.utc), None


def _extract_video_id(url: str | None) -> str | None:
    if url is None:
        return None

    parsed = urlparse(url)
    path_parts = [unquote(part) for part in parsed.path.split("/") if part]
    for index, part in enumerate(path_parts[:-1]):
        if part != "share" or path_parts[index + 1] != "video":
            continue
        if index + 2 >= len(path_parts):
            return None
        raw_id = path_parts[index + 2]
        if VIDEO_ID_RE.match(raw_id):
            return f"tiktok:{raw_id}"
        return None
    return None


def _title(record: Mapping[str, Any]) -> str | None:
    return _first_string(record, *TITLE_FIELDS)


def _first_string(record: Mapping[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = record.get(key)
        if isinstance(value, str):
            cleaned = " ".join(value.split())
            if cleaned:
                return cleaned
    return None


def _sample(sequence: int) -> str:
    return f"record {sequence}"
