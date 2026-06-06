from __future__ import annotations

import csv
import re
from collections.abc import Mapping
from datetime import datetime, timezone
from io import StringIO
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from bs4 import BeautifulSoup

from backend.ingestion.models import ParseResult, ParseWarning, ParsedEvent


COMMENT_EVENT_TYPE = "comment"
LIVE_CHAT_EVENT_TYPE = "live_chat"
PRODUCT = "youtube"

COMMENT_ID_FIELDS = (
    "Comment ID",
    "commentId",
    "comment_id",
)
LIVE_CHAT_ID_FIELDS = (
    "Live Chat ID",
    "Live Chat Id",
    "liveChatId",
    "live_chat_id",
)
COMMENT_TIMESTAMP_FIELDS = (
    "Comment Create Timestamp",
    "Comment create timestamp",
    "Comment Created Timestamp",
    "Comment created timestamp",
    "createdAt",
    "created_at",
    "timestamp",
    "time",
)
LIVE_CHAT_TIMESTAMP_FIELDS = (
    "Live Chat Create Timestamp",
    "Live Chat create timestamp",
    "Live Chat Created Timestamp",
    "Live Chat created timestamp",
    "createdAt",
    "created_at",
    "timestamp",
    "time",
)
VIDEO_ID_FIELDS = (
    "Video ID",
    "Video Id",
    "videoId",
    "video_id",
)

HTML_TIMESTAMP_RE = re.compile(
    r"\b\d{4}-\d{2}-\d{2}(?:[ T])\d{2}:\d{2}:\d{2}"
    r"(?:\.\d+)?(?:\s*(?:UTC|Z))?\b",
    re.IGNORECASE,
)


def parse_comments_live_chat(content: bytes, *, source_path: str) -> ParseResult:
    text, warnings = _decode_content(content)
    event_type = _event_type_for_source_path(source_path)

    if source_path.replace("\\", "/").lower().endswith(".html"):
        result = _parse_html_records(text, event_type=event_type)
    else:
        result = _parse_csv_records(text, event_type=event_type)

    return ParseResult(
        events=result.events,
        subscriptions=[],
        warnings=warnings + result.warnings,
        records_seen=result.records_seen,
    )


def _parse_csv_records(text: str, *, event_type: str) -> ParseResult:
    reader = csv.DictReader(StringIO(text))
    if reader.fieldnames is None:
        return ParseResult(
            events=[],
            subscriptions=[],
            warnings=[ParseWarning(code="missing_csv_header", sample=None)],
            records_seen=0,
        )

    events: list[ParsedEvent] = []
    warnings: list[ParseWarning] = []
    records_seen = 0

    for row in reader:
        if _is_empty_row(row):
            continue

        records_seen += 1
        event, row_warnings = _parse_csv_row(
            row,
            event_type=event_type,
            sequence=records_seen,
        )
        warnings.extend(row_warnings)
        if event is not None:
            events.append(event)

    return ParseResult(
        events=events,
        subscriptions=[],
        warnings=warnings,
        records_seen=records_seen,
    )


def _parse_csv_row(
    row: Mapping[str | None, Any],
    *,
    event_type: str,
    sequence: int,
) -> tuple[ParsedEvent | None, list[ParseWarning]]:
    warnings: list[ParseWarning] = []
    sample = _row_sample(sequence)

    if _has_extra_columns(row):
        warnings.append(ParseWarning(code="malformed_csv_row", sample=sample))

    native_id = _csv_native_id(row, event_type=event_type)
    if native_id is None:
        warnings.append(ParseWarning(code="missing_native_id", sample=sample))

    occurred_at, timestamp_warning = _parse_timestamp(
        _csv_timestamp(row, event_type=event_type)
    )
    if timestamp_warning is not None:
        warnings.append(ParseWarning(code=timestamp_warning, sample=sample))

    if occurred_at is None:
        return None, warnings

    video_id = _field_value(row, *VIDEO_ID_FIELDS)
    if video_id is None:
        warnings.append(ParseWarning(code="missing_video_id", sample=sample))

    return (
        ParsedEvent(
            event_type=event_type,
            product=PRODUCT,
            occurred_at=occurred_at,
            video_id=video_id,
            native_id=native_id,
            sequence=sequence,
        ),
        warnings,
    )


def _parse_html_records(text: str, *, event_type: str) -> ParseResult:
    soup = BeautifulSoup(text, "lxml")
    records = soup.select("li")
    events: list[ParsedEvent] = []
    warnings: list[ParseWarning] = []

    for sequence, record in enumerate(records, start=1):
        event, record_warnings = _parse_html_record(
            record,
            event_type=event_type,
            sequence=sequence,
        )
        warnings.extend(record_warnings)
        if event is not None:
            events.append(event)

    return ParseResult(
        events=events,
        subscriptions=[],
        warnings=warnings,
        records_seen=len(records),
    )


def _parse_html_record(
    record: Any,
    *,
    event_type: str,
    sequence: int,
) -> tuple[ParsedEvent | None, list[ParseWarning]]:
    warnings: list[ParseWarning] = []
    sample = _record_sample(sequence)
    raw_text = _normalize_whitespace(record.get_text(" ", strip=True))

    occurred_at, timestamp_warning = _parse_timestamp(_html_timestamp(raw_text))
    if timestamp_warning is not None:
        warnings.append(ParseWarning(code=timestamp_warning, sample=sample))

    if occurred_at is None:
        return None, warnings

    video_id, native_id = _html_references(record)
    if video_id is None:
        warnings.append(ParseWarning(code="missing_video_id", sample=sample))

    return (
        ParsedEvent(
            event_type=event_type,
            product=PRODUCT,
            occurred_at=occurred_at,
            video_id=video_id,
            native_id=native_id,
            sequence=sequence,
        ),
        warnings,
    )


def _decode_content(content: bytes) -> tuple[str, list[ParseWarning]]:
    try:
        return content.decode("utf-8-sig"), []
    except UnicodeDecodeError:
        return (
            content.decode("utf-8-sig", errors="replace"),
            [ParseWarning(code="invalid_utf8", sample=None)],
        )


def _event_type_for_source_path(source_path: str) -> str:
    normalized = source_path.replace("\\", "/").lower()
    if "live chat" in normalized or "live-chat" in normalized:
        return LIVE_CHAT_EVENT_TYPE
    return COMMENT_EVENT_TYPE


def _csv_native_id(row: Mapping[str | None, Any], *, event_type: str) -> str | None:
    if event_type == LIVE_CHAT_EVENT_TYPE:
        return _field_value(row, *LIVE_CHAT_ID_FIELDS)
    return _field_value(row, *COMMENT_ID_FIELDS)


def _csv_timestamp(row: Mapping[str | None, Any], *, event_type: str) -> str | None:
    if event_type == LIVE_CHAT_EVENT_TYPE:
        return _field_value(row, *LIVE_CHAT_TIMESTAMP_FIELDS)
    return _field_value(row, *COMMENT_TIMESTAMP_FIELDS)


def _field_value(row: Mapping[str | None, Any], *field_names: str) -> str | None:
    normalized_names = {_normalize_field_name(field_name) for field_name in field_names}
    for key, value in row.items():
        if key is None or _normalize_field_name(str(key)) not in normalized_names:
            continue
        if value is None:
            continue

        normalized_value = str(value).strip()
        if normalized_value:
            return normalized_value

    return None


def _parse_timestamp(value: str | None) -> tuple[datetime | None, str | None]:
    if value is None:
        return None, "missing_timestamp"

    normalized = value.strip()
    if not normalized:
        return None, "missing_timestamp"

    upper_normalized = normalized.upper()
    if upper_normalized.endswith("UTC"):
        normalized = f"{normalized[:-3].strip()}+00:00"
    elif normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"

    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None, "timestamp_parse_failed"

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc), "timestamp_missing_timezone"
    return parsed, None


def _html_timestamp(text: str) -> str | None:
    match = HTML_TIMESTAMP_RE.search(text)
    if match is None:
        return None
    return match.group(0)


def _html_references(record: Any) -> tuple[str | None, str | None]:
    video_id: str | None = None
    native_id: str | None = None

    for anchor in record.find_all("a", href=True):
        href = anchor.get("href")
        if video_id is None:
            video_id = _extract_video_id(href)
        if native_id is None:
            native_id = _extract_native_id(href)
        if video_id is not None and native_id is not None:
            break

    return video_id, native_id


def _extract_video_id(url: str | None) -> str | None:
    if not url:
        return None

    parsed = urlparse(_absolute_url(url))
    host = parsed.netloc.lower()
    if not _is_youtube_video_host(host):
        return None

    path_parts = [unquote(part) for part in parsed.path.split("/") if part]
    if host.endswith("youtu.be") and path_parts:
        return path_parts[0]

    query_values = parse_qs(parsed.query).get("v")
    if query_values and query_values[0]:
        return query_values[0]

    if _is_youtube_host(host) and len(path_parts) >= 2:
        if path_parts[0] in {"embed", "shorts", "v"} and path_parts[1]:
            return path_parts[1]

    return None


def _extract_native_id(url: str | None) -> str | None:
    if not url:
        return None

    parsed = urlparse(_absolute_url(url))
    for query in (parsed.query, parsed.fragment):
        values = parse_qs(query)
        for key, key_values in values.items():
            if _normalize_field_name(key) not in {
                "lc",
                "commentid",
                "livechatid",
            }:
                continue
            for value in key_values:
                if value:
                    return value

    return None


def _absolute_url(url: str) -> str:
    if url.startswith("//"):
        return f"https:{url}"
    if url.startswith("/"):
        return f"https://www.youtube.com{url}"
    return url


def _is_youtube_video_host(host: str) -> bool:
    return _is_youtube_host(host) or host == "youtu.be" or host.endswith(".youtu.be")


def _is_youtube_host(host: str) -> bool:
    return (
        host == "youtube.com"
        or host.endswith(".youtube.com")
        or host == "youtube-nocookie.com"
        or host.endswith(".youtube-nocookie.com")
    )


def _has_extra_columns(row: Mapping[str | None, Any]) -> bool:
    extra_columns = row.get(None)
    if extra_columns is None:
        return False
    if isinstance(extra_columns, list):
        return any(_normalize_whitespace(str(value)) for value in extra_columns)
    return bool(_normalize_whitespace(str(extra_columns)))


def _is_empty_row(row: Mapping[str | None, Any]) -> bool:
    for value in row.values():
        if isinstance(value, list):
            if any(_normalize_whitespace(str(item)) for item in value):
                return False
            continue
        if value is not None and _normalize_whitespace(str(value)):
            return False
    return True


def _normalize_field_name(value: str) -> str:
    return "".join(character for character in value.lower() if character.isalnum())


def _normalize_whitespace(value: str | None) -> str:
    if value is None:
        return ""
    return " ".join(value.split())


def _row_sample(sequence: int) -> str:
    return f"row {sequence}"


def _record_sample(sequence: int) -> str:
    return f"record {sequence}"
