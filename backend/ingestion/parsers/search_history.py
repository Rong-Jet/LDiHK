from __future__ import annotations

import json
import re
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from backend.ingestion.models import ParseResult, ParseWarning, ParsedEvent


SEARCH_FIELD_NAMES = (
    "query",
    "searchQuery",
    "search_query",
    "searchTerm",
    "search_term",
)
URL_FIELD_NAMES = (
    "titleUrl",
    "title_url",
    "url",
    "link",
    "pageUrl",
    "page_url",
)
SEARCH_TITLE_RE = re.compile(r"^\s*Searched\s+for\b(?P<query>.*)$", re.IGNORECASE)


def parse_search_history(content: bytes, *, source_path: str) -> ParseResult:
    text, warnings = _decode_content(content)
    result = _parse_json_history(text, source_path=source_path)

    return ParseResult(
        events=result.events,
        subscriptions=[],
        warnings=warnings + result.warnings,
        records_seen=result.records_seen,
    )


def _parse_json_history(text: str, *, source_path: str) -> ParseResult:
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
    source_path_is_youtube = _source_path_is_youtube(source_path)

    for sequence, record in enumerate(records, start=1):
        sample = _sample(sequence)
        if not isinstance(record, Mapping):
            warnings.append(ParseWarning(code="malformed_json_record", sample=sample))
            continue

        event, record_warnings = _parse_json_record(
            record,
            sequence=sequence,
            source_path_is_youtube=source_path_is_youtube,
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


def _parse_json_record(
    record: Mapping[str, Any],
    *,
    sequence: int,
    source_path_is_youtube: bool,
) -> tuple[ParsedEvent | None, list[ParseWarning]]:
    sample = _sample(sequence)
    has_product_marker = _has_product_marker(record)
    has_youtube_product = _has_youtube_product(record)
    has_youtube_url = any(_is_youtube_url(url) for url in _record_urls(record))
    is_youtube = (
        has_youtube_product
        or has_youtube_url
        or (source_path_is_youtube and not has_product_marker)
    )
    if not is_youtube:
        return None, []

    is_search = (
        _has_search_url(record)
        or _has_search_title(record)
        or (source_path_is_youtube and _has_search_field(record))
    )
    if not is_search:
        return None, []

    search_query = _search_query(record)
    if search_query is None:
        return None, [ParseWarning(code="missing_search_query", sample=sample)]

    occurred_at, timestamp_warning = _parse_json_timestamp(record)
    warnings = []
    if timestamp_warning is not None:
        warnings.append(ParseWarning(code=timestamp_warning, sample=sample))

    return (
        ParsedEvent(
            event_type="search",
            product="youtube",
            occurred_at=occurred_at,
            search_query=search_query,
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


def _json_records(payload: Any) -> list[Any] | None:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in (
            "searchHistory",
            "search_history",
            "activities",
            "activity",
            "items",
            "records",
        ):
            value = payload.get(key)
            if isinstance(value, list):
                return value
    return None


def _has_youtube_product(record: Mapping[str, Any]) -> bool:
    for key in ("header", "product"):
        if _is_youtube_product(record.get(key)):
            return True

    products = record.get("products")
    if isinstance(products, list):
        return any(_is_youtube_product(product) for product in products)
    return False


def _has_product_marker(record: Mapping[str, Any]) -> bool:
    for key in ("header", "product"):
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            return True

    products = record.get("products")
    if isinstance(products, list):
        return any(isinstance(product, str) and product.strip() for product in products)
    return False


def _is_youtube_product(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    return _normalize_whitespace(value).lower() in {"youtube", "youtube music"}


def _has_search_url(record: Mapping[str, Any]) -> bool:
    return any(_is_youtube_search_url(url) for url in _record_urls(record))


def _has_search_title(record: Mapping[str, Any]) -> bool:
    title = _first_string(record, "title", "name")
    return bool(title and SEARCH_TITLE_RE.match(title))


def _has_search_field(record: Mapping[str, Any]) -> bool:
    return any(field_name in record for field_name in SEARCH_FIELD_NAMES)


def _search_query(record: Mapping[str, Any]) -> str | None:
    for url in _record_urls(record):
        query = _search_query_from_url(url)
        if query is not None:
            return query

    for field_name in SEARCH_FIELD_NAMES:
        query = _clean_query(record.get(field_name))
        if query is not None:
            return query

    title = _first_string(record, "title", "name")
    if title is None:
        return None

    match = SEARCH_TITLE_RE.match(title)
    if match is None:
        return None
    return _clean_query(match.group("query"))


def _record_urls(record: Mapping[str, Any]) -> list[str]:
    urls: list[str] = []
    for field_name in URL_FIELD_NAMES:
        value = record.get(field_name)
        if isinstance(value, str) and value.strip():
            urls.append(value)
    return urls


def _search_query_from_url(url: str) -> str | None:
    parsed = urlparse(_absolute_url(url))
    if not _is_youtube_host(parsed.netloc.lower()):
        return None
    if not _is_search_path(parsed.path):
        return None

    query_values = parse_qs(parsed.query, keep_blank_values=True)
    for key in ("search_query", "q"):
        values = query_values.get(key)
        if not values:
            continue
        query = _clean_query(values[0])
        if query is not None:
            return query
    return None


def _parse_json_timestamp(record: Mapping[str, Any]) -> tuple[datetime | None, str | None]:
    value = _first_string(record, "time", "timestamp", "activityTime", "activity_time")
    if not value:
        return None, "missing_timestamp"
    return _parse_iso_timestamp(value)


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


def _is_youtube_search_url(url: str) -> bool:
    parsed = urlparse(_absolute_url(url))
    return _is_youtube_host(parsed.netloc.lower()) and _is_search_path(parsed.path)


def _is_youtube_url(url: str) -> bool:
    parsed = urlparse(_absolute_url(url))
    return _is_youtube_host(parsed.netloc.lower())


def _is_youtube_host(host: str) -> bool:
    return host == "youtube.com" or host.endswith(".youtube.com")


def _is_search_path(path: str) -> bool:
    path_parts = [unquote(part).lower() for part in path.split("/") if part]
    return bool(path_parts) and path_parts[0] in {"results", "search"}


def _absolute_url(url: str) -> str:
    if url.startswith("//"):
        return f"https:{url}"
    if url.startswith("/"):
        return f"https://www.youtube.com{url}"
    return url


def _source_path_is_youtube(source_path: str) -> bool:
    normalized_path = source_path.replace("\\", "/").strip("/").lower()
    return "youtube" in normalized_path and (
        normalized_path.endswith("/search-history.json")
        or normalized_path.endswith("/myactivity.json")
        or normalized_path.endswith("/my-activity.json")
    )


def _first_string(record: Mapping[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = record.get(key)
        if isinstance(value, str):
            return value
    return None


def _clean_query(value: Any) -> str | None:
    if not isinstance(value, str):
        return None

    query = _normalize_whitespace(value).strip("'\"")
    if not query:
        return None
    return query


def _normalize_whitespace(value: str | None) -> str:
    if value is None:
        return ""
    return " ".join(value.split())


def _sample(sequence: int) -> str:
    return f"record {sequence}"
