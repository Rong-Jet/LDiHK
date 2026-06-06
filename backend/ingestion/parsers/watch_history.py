from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from bs4 import BeautifulSoup

from backend.ingestion.models import ParseResult, ParseWarning, ParsedEvent


PRODUCTS = {
    "youtube": "youtube",
    "youtube music": "youtube_music",
}

MONTHS = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}

TIMEZONE_OFFSETS = {
    "UTC": 0,
    "GMT": 0,
    "CET": 1,
    "CEST": 2,
    "WET": 0,
    "WEST": 1,
    "EET": 2,
    "EEST": 3,
    "EST": -5,
    "EDT": -4,
    "CST": -6,
    "CDT": -5,
    "MST": -7,
    "MDT": -6,
    "PST": -8,
    "PDT": -7,
}

DAY_MONTH_TIMESTAMP_RE = re.compile(
    r"\b(?P<day>\d{1,2})\s+"
    r"(?P<month>[A-Za-z]+)\s+"
    r"(?P<year>\d{4}),\s+"
    r"(?P<hour>\d{1,2}):(?P<minute>\d{2}):(?P<second>\d{2})"
    r"(?:\s*(?P<ampm>AM|PM))?\s+"
    r"(?P<zone>(?:UTC|GMT)[+-]\d{1,2}(?::?\d{2})?|[A-Za-z]{2,5})\b",
    re.IGNORECASE,
)
MONTH_DAY_TIMESTAMP_RE = re.compile(
    r"\b(?P<month>[A-Za-z]+)\s+"
    r"(?P<day>\d{1,2}),\s+"
    r"(?P<year>\d{4}),\s+"
    r"(?P<hour>\d{1,2}):(?P<minute>\d{2}):(?P<second>\d{2})"
    r"(?:\s*(?P<ampm>AM|PM))?\s+"
    r"(?P<zone>(?:UTC|GMT)[+-]\d{1,2}(?::?\d{2})?|[A-Za-z]{2,5})\b",
    re.IGNORECASE,
)
ISO_TIMESTAMP_RE = re.compile(
    r"\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})\b"
)
GMT_OFFSET_RE = re.compile(
    r"^(?:UTC|GMT)(?P<sign>[+-])(?P<hour>\d{1,2})(?::?(?P<minute>\d{2}))?$"
)

STATUS_PATTERNS = (
    (
        "private",
        re.compile(
            r"\b(private video|video is private|this video is private|has been made private)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "deleted",
        re.compile(
            r"\b(has been deleted|has been removed|video that has been removed|deleted video|removed video)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "unavailable",
        re.compile(r"\b(unavailable|no longer available)\b", re.IGNORECASE),
    ),
)

TITLE_PREFIXES = (
    "Watched ",
    "Viewed ",
    "Visited ",
    "Listened to ",
)


def parse_watch_history(content: bytes, *, source_path: str) -> ParseResult:
    text, warnings = _decode_content(content)
    if _is_json_source(source_path, text):
        result = _parse_json_history(text)
    else:
        result = _parse_html_history(text)

    return ParseResult(
        events=result.events,
        subscriptions=[],
        warnings=warnings + result.warnings,
        records_seen=result.records_seen,
    )


def _parse_html_history(text: str) -> ParseResult:
    soup = BeautifulSoup(text, "lxml")
    cards = soup.select("div.outer-cell")
    events: list[ParsedEvent] = []
    warnings: list[ParseWarning] = []

    for sequence, card in enumerate(cards, start=1):
        event, record_warnings = _parse_html_card(card, sequence=sequence)
        warnings.extend(record_warnings)
        if event is not None:
            events.append(event)

    return ParseResult(
        events=events,
        subscriptions=[],
        warnings=warnings,
        records_seen=len(cards),
    )


def _parse_html_card(
    card: Any, *, sequence: int
) -> tuple[ParsedEvent | None, list[ParseWarning]]:
    warnings: list[ParseWarning] = []
    sample = _sample(sequence)

    header = card.select_one(".header-cell .mdl-typography--title")
    raw_product = header.get_text(" ", strip=True) if header else None
    product = _normalize_product(raw_product)
    if product is None:
        code = "missing_product" if raw_product is None else "unknown_product"
        return None, [ParseWarning(code=code, sample=sample)]

    content = _main_content_cell(card)
    if content is None:
        return None, [ParseWarning(code="malformed_record", sample=sample)]

    body = _normalize_whitespace(content.get_text(" ", strip=True))
    if not body:
        return None, [ParseWarning(code="malformed_record", sample=sample)]

    occurred_at, timestamp_warning = _parse_text_timestamp(body)
    if timestamp_warning is not None:
        warnings.append(ParseWarning(code=timestamp_warning, sample=sample))

    video_id, title = _html_video_reference(content)
    channel_id = _html_channel_id(content)
    raw_status = _raw_status(body)

    if video_id is None:
        if raw_status is None:
            raw_status = "malformed"
            warnings.append(ParseWarning(code="missing_video_id", sample=sample))
        else:
            warnings.append(ParseWarning(code=f"{raw_status}_watch", sample=sample))

    if occurred_at is None:
        raw_status = raw_status or "malformed"

    return (
        ParsedEvent(
            event_type="watch",
            product=product,
            occurred_at=occurred_at,
            video_id=video_id,
            channel_id=channel_id,
            title=title,
            raw_status=raw_status,
            sequence=sequence,
        ),
        warnings,
    )


def _parse_json_history(text: str) -> ParseResult:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return ParseResult(
            events=[],
            subscriptions=[],
            warnings=[ParseWarning(code="json_decode_failed", sample=None)],
            records_seen=0,
        )

    records = _json_records(payload)
    if records is None:
        return ParseResult(
            events=[],
            subscriptions=[],
            warnings=[ParseWarning(code="json_shape_unsupported", sample=None)],
            records_seen=0,
        )

    events: list[ParsedEvent] = []
    warnings: list[ParseWarning] = []

    for sequence, record in enumerate(records, start=1):
        sample = _sample(sequence)
        if not isinstance(record, dict):
            warnings.append(ParseWarning(code="malformed_json_record", sample=sample))
            continue

        event, record_warnings = _parse_json_record(record, sequence=sequence)
        warnings.extend(record_warnings)
        if event is not None:
            events.append(event)

    return ParseResult(
        events=events,
        subscriptions=[],
        warnings=warnings,
        records_seen=len(records),
    )


def _parse_json_record(
    record: dict[str, Any], *, sequence: int
) -> tuple[ParsedEvent | None, list[ParseWarning]]:
    warnings: list[ParseWarning] = []
    sample = _sample(sequence)
    product = _json_product(record)
    if product is None:
        return None, [ParseWarning(code="missing_product", sample=sample)]

    occurred_at, timestamp_warning = _parse_json_timestamp(record)
    if timestamp_warning is not None:
        warnings.append(ParseWarning(code=timestamp_warning, sample=sample))

    title_url = _first_string(record, "titleUrl", "title_url", "url")
    video_id = _extract_video_id(title_url)
    title = _clean_title(_first_string(record, "title", "name"))
    channel_id = _json_channel_id(record)
    raw_status = _raw_status(" ".join(_json_status_texts(record)))

    if video_id is None:
        if raw_status is None:
            raw_status = "malformed"
            warnings.append(ParseWarning(code="missing_video_id", sample=sample))
        else:
            warnings.append(ParseWarning(code=f"{raw_status}_watch", sample=sample))

    if raw_status is not None and video_id is None:
        title = None
    if occurred_at is None:
        raw_status = raw_status or "malformed"

    return (
        ParsedEvent(
            event_type="watch",
            product=product,
            occurred_at=occurred_at,
            video_id=video_id,
            channel_id=channel_id,
            title=title,
            raw_status=raw_status,
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


def _is_json_source(source_path: str, text: str) -> bool:
    if source_path.replace("\\", "/").lower().endswith(".json"):
        return True
    return text.lstrip().startswith(("[", "{"))


def _json_records(payload: Any) -> list[Any] | None:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("watchHistory", "watch_history", "activities", "items"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
    return None


def _json_product(record: dict[str, Any]) -> str | None:
    product = _normalize_product(_first_string(record, "header", "product"))
    if product is not None:
        return product

    products = record.get("products")
    if isinstance(products, list):
        for value in products:
            product = _normalize_product(value if isinstance(value, str) else None)
            if product is not None:
                return product

    return None


def _json_channel_id(record: dict[str, Any]) -> str | None:
    for key in ("channelUrl", "channel_url", "subtitleUrl", "subtitle_url"):
        channel_id = _extract_channel_id(_first_string(record, key))
        if channel_id is not None:
            return channel_id

    subtitles = record.get("subtitles")
    if isinstance(subtitles, list):
        for subtitle in subtitles:
            if not isinstance(subtitle, dict):
                continue
            channel_id = _extract_channel_id(
                _first_string(subtitle, "url", "channelUrl")
            )
            if channel_id is not None:
                return channel_id

    return None


def _json_status_texts(record: dict[str, Any]) -> list[str]:
    texts: list[str] = []
    for key in ("title", "description", "details", "rawStatus", "raw_status"):
        value = _first_string(record, key)
        if value:
            texts.append(value)
    return texts


def _parse_json_timestamp(record: dict[str, Any]) -> tuple[datetime | None, str | None]:
    value = _first_string(record, "time", "timestamp", "activityTime", "activity_time")
    if not value:
        return None, "missing_timestamp"
    return _parse_iso_timestamp(value)


def _main_content_cell(card: Any) -> Any | None:
    for content in card.select(".content-cell"):
        classes = set(content.get("class", []))
        if "mdl-typography--caption" in classes:
            continue
        if "mdl-typography--text-right" in classes:
            continue
        if _normalize_whitespace(content.get_text(" ", strip=True)):
            return content
    return None


def _html_video_reference(content: Any) -> tuple[str | None, str | None]:
    for anchor in content.find_all("a", href=True):
        href = anchor.get("href")
        video_id = _extract_video_id(href)
        if video_id is None:
            continue
        title = _normalize_whitespace(anchor.get_text(" ", strip=True)) or None
        return video_id, title
    return None, None


def _html_channel_id(content: Any) -> str | None:
    for anchor in content.find_all("a", href=True):
        channel_id = _extract_channel_id(anchor.get("href"))
        if channel_id is not None:
            return channel_id
    return None


def _parse_text_timestamp(text: str) -> tuple[datetime | None, str | None]:
    iso_match = ISO_TIMESTAMP_RE.search(text)
    if iso_match is not None:
        return _parse_iso_timestamp(iso_match.group(0))

    normalized = _normalize_whitespace(text)
    for pattern in (DAY_MONTH_TIMESTAMP_RE, MONTH_DAY_TIMESTAMP_RE):
        match = pattern.search(normalized)
        if match is not None:
            return _parse_named_timestamp(match)
    return None, "missing_timestamp"


def _parse_iso_timestamp(value: str) -> tuple[datetime | None, str | None]:
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"

    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None, "timestamp_parse_failed"

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc), "timestamp_missing_timezone"
    return parsed, None


def _parse_named_timestamp(match: re.Match[str]) -> tuple[datetime | None, str | None]:
    parts = match.groupdict()
    month = MONTHS.get(parts["month"].lower())
    if month is None:
        return None, "timestamp_parse_failed"

    hour = int(parts["hour"])
    ampm = parts.get("ampm")
    if ampm:
        ampm = ampm.upper()
        if ampm == "PM" and hour != 12:
            hour += 12
        elif ampm == "AM" and hour == 12:
            hour = 0

    tzinfo = _parse_timezone(parts["zone"])
    if tzinfo is None:
        return None, "timestamp_parse_failed"

    return (
        datetime(
            int(parts["year"]),
            month,
            int(parts["day"]),
            hour,
            int(parts["minute"]),
            int(parts["second"]),
            tzinfo=tzinfo,
        ),
        None,
    )


def _parse_timezone(value: str) -> timezone | None:
    upper_value = value.upper()
    if upper_value in TIMEZONE_OFFSETS:
        return timezone(timedelta(hours=TIMEZONE_OFFSETS[upper_value]), upper_value)

    match = GMT_OFFSET_RE.match(upper_value)
    if match is None:
        return None

    hours = int(match.group("hour"))
    minutes = int(match.group("minute") or "0")
    delta = timedelta(hours=hours, minutes=minutes)
    if match.group("sign") == "-":
        delta = -delta
    return timezone(delta, upper_value)


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


def _extract_channel_id(url: str | None) -> str | None:
    if not url:
        return None

    parsed = urlparse(_absolute_url(url))
    host = parsed.netloc.lower()
    if not _is_youtube_host(host):
        return None

    path_parts = [unquote(part) for part in parsed.path.split("/") if part]
    if len(path_parts) >= 2 and path_parts[0] == "channel" and path_parts[1]:
        return path_parts[1]
    return None


def _is_youtube_video_host(host: str) -> bool:
    return _is_youtube_host(host) or host == "youtu.be" or host.endswith(".youtu.be")


def _is_youtube_host(host: str) -> bool:
    return (
        host == "youtube.com"
        or host.endswith(".youtube.com")
        or host == "youtube-nocookie.com"
        or host.endswith(".youtube-nocookie.com")
    )


def _absolute_url(url: str) -> str:
    if url.startswith("//"):
        return f"https:{url}"
    if url.startswith("/"):
        return f"https://www.youtube.com{url}"
    return url


def _normalize_product(value: str | None) -> str | None:
    if value is None:
        return None
    return PRODUCTS.get(_normalize_whitespace(value).lower())


def _raw_status(text: str) -> str | None:
    for status, pattern in STATUS_PATTERNS:
        if pattern.search(text):
            return status
    return None


def _clean_title(value: str | None) -> str | None:
    title = _normalize_whitespace(value)
    if not title:
        return None

    for prefix in TITLE_PREFIXES:
        if title.startswith(prefix):
            title = title[len(prefix) :]
            break

    if _raw_status(title) is not None:
        return None
    return title or None


def _first_string(record: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = record.get(key)
        if isinstance(value, str):
            return value
    return None


def _normalize_whitespace(value: str | None) -> str:
    if value is None:
        return ""
    return " ".join(value.split())


def _sample(sequence: int) -> str:
    return f"record {sequence}"
