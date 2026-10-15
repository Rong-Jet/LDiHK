from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from backend.ingestion.models import ParseResult, ParseWarning, ParsedEvent
from backend.ingestion.parsers.takeout_activity import (
    MONTHS,
    TIMEZONE_OFFSETS,
    ActivityCard,
    is_json_array,
    iter_activity_cards,
    iter_json_array,
    mentions_google_ads,
    parse_iso_timestamp,
    parse_text_timestamp,
    parse_timezone,
)

__all__ = [
    "MONTHS",
    "TIMEZONE_OFFSETS",
    "parse_watch_card",
    "parse_watch_history",
    "parse_watch_json_record",
    "parse_timezone",
]


PRODUCTS = {
    "youtube": "youtube",
    "youtube music": "youtube_music",
}

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

# Localised status phrases (de, es, fr, it, pt, nl).  They are only consulted
# for records without a video link, so words inside real video titles
# ("10 km entfernt") cannot mark a normal watch as deleted.
LOCALIZED_STATUS_PATTERNS = (
    (
        "private",
        re.compile(
            r"\b(privates?|privat|privad[oa]s?|priv[ée]e?s?|privat[oa]|priv[ée])\b",
            re.IGNORECASE,
        ),
    ),
    (
        "deleted",
        re.compile(
            r"\b(entfernt|gel[öo]e?scht|eliminad[oa]s?|borrad[oa]s?|supprim[ée]e?s?|"
            r"retir[ée]e?s?|rimoss[oa]|eliminat[oa]|cancellat[oa]|removid[oa]s?|"
            r"exclu[íi]d[oa]s?|apagad[oa]s?|verwijderd)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "unavailable",
        re.compile(
            r"(nicht\s+(mehr\s+)?verf[üu]gbar|no\s+(est[áa]\s+)?disponible|indisponible|"
            r"non\s+(è\s+più\s+|e\s+piu\s+)?disponibile|indispon[íi]vel|"
            r"niet\s+(meer\s+)?beschikbaar)",
            re.IGNORECASE,
        ),
    ),
)

TITLE_PREFIXES = (
    "Watched ",
    "Viewed ",
    "Visited ",
    "Listened to ",
    # es
    "Has visto ",
    "Has visualizado ",
    "Has escuchado ",
    # fr
    "Vous avez regardé ",
    "Vous avez visionné ",
    "Vous avez écouté ",
    # it
    "Hai guardato ",
    "Hai visto ",
    "Hai ascoltato ",
    # pt
    "Você assistiu a ",
    "Você assistiu ",
    "Assistiu a ",
    "Assistiu ",
    "Assististe a ",
    "Visualizou ",
    "Ouviu ",
    # nl / de
    "Je hebt ",
    "Bekeken: ",
    "Angesehen: ",
)
TITLE_SUFFIXES = (
    " angesehen",
    " angeschaut",
    " angehört",
    " bekeken",
    " gekeken",
    " beluisterd",
)
HTML_PARSE_CHUNK_BYTES = 64 * 1024
GOOGLE_ADS_WARNING = "google_ads_watch_skipped"


def parse_watch_history(content: bytes, *, source_path: str) -> ParseResult:
    if _is_json_source(source_path, content):
        text, warnings = _decode_content(content)
        result = _parse_json_history(text)
    else:
        warnings = []
        result = _parse_html_history(content)

    return ParseResult(
        events=result.events,
        subscriptions=[],
        warnings=warnings + result.warnings,
        records_seen=result.records_seen,
    )


def _parse_html_history(content: bytes) -> ParseResult:
    events: list[ParsedEvent] = []
    warnings: list[ParseWarning] = []
    records_seen = 0

    for card in iter_activity_cards(content, chunk_size=HTML_PARSE_CHUNK_BYTES):
        records_seen += 1
        event, record_warnings = parse_watch_card(card, sequence=records_seen)
        warnings.extend(record_warnings)
        if event is not None:
            events.append(event)

    return ParseResult(
        events=events,
        subscriptions=[],
        warnings=warnings,
        records_seen=records_seen,
    )


def parse_watch_card(
    card: ActivityCard, *, sequence: int
) -> tuple[ParsedEvent | None, list[ParseWarning]]:
    """Turn one HTML activity card into a watch event (or warnings)."""
    warnings: list[ParseWarning] = []
    sample = _sample(sequence)

    product = _normalize_product(card.product)
    if product is None:
        code = "missing_product" if card.product is None else "unknown_product"
        return None, [ParseWarning(code=code, sample=sample)]

    body = card.body
    if not body:
        return None, [ParseWarning(code="malformed_record", sample=sample)]

    if mentions_google_ads(card.caption):
        return None, [ParseWarning(code=GOOGLE_ADS_WARNING, sample=sample)]

    occurred_at, timestamp_warning = parse_text_timestamp(body)
    if timestamp_warning is not None:
        warnings.append(ParseWarning(code=timestamp_warning, sample=sample))

    video_id, title = _html_video_reference(card.anchors)
    channel_id = _html_channel_id(card.anchors)
    raw_status = _raw_status(body, localized=video_id is None)

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
        if is_json_array(text):
            # Takeout's watch-history.json is a top-level array: decode it
            # record by record so a large history fits in a 512 MB instance.
            records: Iterable[object] = iter_json_array(text)
        else:
            payload = json.loads(text)
            records = json_records(payload)
            if records is None:
                return ParseResult(
                    events=[],
                    subscriptions=[],
                    warnings=[ParseWarning(code="json_shape_unsupported", sample=None)],
                    records_seen=0,
                )

        events: list[ParsedEvent] = []
        warnings: list[ParseWarning] = []
        records_seen = 0

        for sequence, record in enumerate(records, start=1):
            records_seen = sequence
            sample = _sample(sequence)
            if not isinstance(record, dict):
                warnings.append(ParseWarning(code="malformed_json_record", sample=sample))
                continue

            event, record_warnings = parse_watch_json_record(record, sequence=sequence)
            warnings.extend(record_warnings)
            if event is not None:
                events.append(event)
    except json.JSONDecodeError:
        return ParseResult(
            events=[],
            subscriptions=[],
            warnings=[ParseWarning(code="json_decode_failed", sample=None)],
            records_seen=0,
        )

    return ParseResult(
        events=events,
        subscriptions=[],
        warnings=warnings,
        records_seen=records_seen,
    )


def parse_watch_json_record(
    record: dict[str, Any], *, sequence: int
) -> tuple[ParsedEvent | None, list[ParseWarning]]:
    """Turn one watch-history JSON record into a watch event (or warnings)."""
    warnings: list[ParseWarning] = []
    sample = _sample(sequence)
    product = _json_product(record)
    if product is None:
        return None, [ParseWarning(code="missing_product", sample=sample)]

    if is_google_ads_json_record(record):
        return None, [ParseWarning(code=GOOGLE_ADS_WARNING, sample=sample)]

    occurred_at, timestamp_warning = _parse_json_timestamp(record)
    if timestamp_warning is not None:
        warnings.append(ParseWarning(code=timestamp_warning, sample=sample))

    title_url = _first_string(record, "titleUrl", "title_url", "url")
    video_id = _extract_video_id(title_url)
    channel_id = _json_channel_id(record)
    raw_status = _raw_status(
        " ".join(_json_status_texts(record)), localized=video_id is None
    )
    # Mirror the HTML export: without a video link there is no title anchor,
    # so the JSON record must not carry a title either (keeps fingerprints of
    # the same watch identical across the two export formats).
    title = _clean_title(_first_string(record, "title", "name")) if video_id else None

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


def is_google_ads_json_record(record: Mapping[str, Any]) -> bool:
    """True for records tagged ``"details": [{"name": "From Google Ads"}]``."""
    details = record.get("details")
    if isinstance(details, str):
        return mentions_google_ads(details)
    if not isinstance(details, list):
        return False
    for detail in details:
        if isinstance(detail, Mapping):
            name = detail.get("name")
            if isinstance(name, str) and mentions_google_ads(name):
                return True
        elif isinstance(detail, str) and mentions_google_ads(detail):
            return True
    return False


def _decode_content(content: bytes) -> tuple[str, list[ParseWarning]]:
    try:
        return content.decode("utf-8-sig"), []
    except UnicodeDecodeError:
        return (
            content.decode("utf-8-sig", errors="replace"),
            [ParseWarning(code="invalid_utf8", sample=None)],
        )


def _is_json_source(source_path: str, content: bytes) -> bool:
    if source_path.replace("\\", "/").lower().endswith(".json"):
        return True
    return content[:64].lstrip(b"\xef\xbb\xbf \t\r\n").startswith((b"[", b"{"))


def json_records(payload: Any) -> list[Any] | None:
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


def _parse_json_timestamp(record: dict[str, Any]):
    value = _first_string(record, "time", "timestamp", "activityTime", "activity_time")
    if not value:
        return None, "missing_timestamp"
    return parse_iso_timestamp(value)


def _html_video_reference(
    anchors: tuple[tuple[str, str], ...],
) -> tuple[str | None, str | None]:
    for href, text in anchors:
        video_id = _extract_video_id(href)
        if video_id is None:
            continue
        return video_id, text or None
    return None, None


def _html_channel_id(anchors: tuple[tuple[str, str], ...]) -> str | None:
    for href, _ in anchors:
        channel_id = _extract_channel_id(href)
        if channel_id is not None:
            return channel_id
    return None


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


def extract_video_id(url: str | None) -> str | None:
    """Public alias used by the format-sniffing YouTube activity parser."""
    return _extract_video_id(url)


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


def _raw_status(text: str, *, localized: bool = False) -> str | None:
    for status, pattern in STATUS_PATTERNS:
        if pattern.search(text):
            return status
    if localized:
        for status, pattern in LOCALIZED_STATUS_PATTERNS:
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
    for suffix in TITLE_SUFFIXES:
        if title.endswith(suffix) and len(title) > len(suffix):
            title = title[: -len(suffix)]
            break

    if _raw_status(title) is not None:
        return None
    return title or None


def _first_string(record: Mapping[str, Any], *keys: str) -> str | None:
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
