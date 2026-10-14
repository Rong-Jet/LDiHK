from __future__ import annotations

import fnmatch
import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from bs4 import BeautifulSoup

from backend.ingestion.dispatch import normalize_member_path
from backend.ingestion.models import ParseResult, ParseWarning, ParsedEvent


DEFAULT_INSTAGRAM_INTERACTION_DURATION_SECONDS = 15
INSTAGRAM_EXPORT_TIMEZONE_ENV = "INSTAGRAM_EXPORT_TIMEZONE"
DEFAULT_INSTAGRAM_EXPORT_TIMEZONE = "UTC"

MONTH_TIMESTAMP_RE = re.compile(
    r"\b(?:Jan|January|Feb|February|Mar|March|Apr|April|May|Jun|June|Jul|July|"
    r"Aug|August|Sep|Sept|September|Oct|October|Nov|November|Dec|December)"
    r"\s+\d{1,2},\s+\d{4},?\s+\d{1,2}:\d{2}(?::\d{2})?\s*(?:AM|PM|am|pm)\b"
)
ISO_TIMESTAMP_RE = re.compile(
    r"\b\d{4}-\d{2}-\d{2}(?:[ T])\d{2}:\d{2}:\d{2}"
    r"(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?\b"
)
TIMESTAMP_FORMATS = (
    "%b %d, %Y %I:%M %p",
    "%B %d, %Y %I:%M %p",
    "%b %d, %Y, %I:%M %p",
    "%B %d, %Y, %I:%M %p",
    "%b %d, %Y %I:%M:%S %p",
    "%B %d, %Y %I:%M:%S %p",
    "%b %d, %Y, %I:%M:%S %p",
    "%B %d, %Y, %I:%M:%S %p",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M:%S.%f",
)


@dataclass(frozen=True)
class InstagramSource:
    path_pattern: str
    event_type: str
    product: str
    redact_title: bool = False


INSTAGRAM_SOURCE_REGISTRY: tuple[InstagramSource, ...] = (
    InstagramSource(
        path_pattern="your_instagram_activity/story_interactions/stories_viewed.html",
        event_type="story_view",
        product="stories",
    ),
    InstagramSource(
        path_pattern="your_instagram_activity/story_interactions/story_likes.html",
        event_type="story_like",
        product="stories",
    ),
    InstagramSource(
        path_pattern="your_instagram_activity/likes/liked_posts.html",
        event_type="liked_post",
        product="posts",
    ),
    InstagramSource(
        path_pattern="your_instagram_activity/saved/saved_posts.html",
        event_type="saved_post",
        product="posts",
    ),
    InstagramSource(
        path_pattern="ads_information/ads_and_topics/posts_viewed.html",
        event_type="post_view",
        product="posts",
    ),
    InstagramSource(
        path_pattern="ads_information/ads_and_topics/videos_watched.html",
        event_type="video_watch",
        product="reels",
    ),
    InstagramSource(
        path_pattern="your_instagram_activity/content/posts.html",
        event_type="post_created",
        product="posts",
    ),
    InstagramSource(
        path_pattern="your_instagram_activity/content/posts_*.html",
        event_type="post_created",
        product="posts",
    ),
    InstagramSource(
        path_pattern="your_instagram_activity/content/reels.html",
        event_type="reel_created",
        product="reels",
    ),
    InstagramSource(
        path_pattern="your_instagram_activity/content/stories.html",
        event_type="story_created",
        product="stories",
    ),
    InstagramSource(
        path_pattern=(
            "your_instagram_activity/followers_and_following/"
            "recently_unfollowed_profiles.html"
        ),
        event_type="unfollowed_profile",
        product="connections",
    ),
    InstagramSource(
        path_pattern=(
            "connections/followers_and_following/recently_unfollowed_profiles.html"
        ),
        event_type="unfollowed_profile",
        product="connections",
    ),
    InstagramSource(
        path_pattern="your_instagram_activity/messages/**/*.html",
        event_type="message",
        product="messages",
        redact_title=True,
    ),
)


# Unix-time keys used by Instagram JSON exports, in lookup order.
JSON_TIMESTAMP_KEYS = ("timestamp", "creation_timestamp", "taken_at", "timestamp_ms")
JSON_SEARCH_DEPTH = 5


def parse_instagram_activity(content: bytes, *, source_path: str) -> ParseResult:
    text, decode_warnings = _decode_content(content)
    source = source_for_path(source_path)
    if source is None:
        return ParseResult(
            events=[],
            subscriptions=[],
            warnings=decode_warnings
            + [ParseWarning(code="instagram_source_unrecognized", sample=None)],
            records_seen=0,
        )

    if _is_json_source(source_path, text):
        result = _parse_json_activity(text, source=source)
    else:
        result = _parse_timestamped_html(text, source=source)
    return ParseResult(
        events=result.events,
        subscriptions=[],
        warnings=decode_warnings + result.warnings,
        records_seen=result.records_seen,
    )


def source_for_path(source_path: str) -> InstagramSource | None:
    """Match the HTML export path or its JSON twin (same name, ``.json``)."""
    normalized_path = normalize_member_path(source_path)
    for source in INSTAGRAM_SOURCE_REGISTRY:
        normalized_pattern = normalize_member_path(source.path_pattern)
        patterns = [normalized_pattern]
        if normalized_pattern.endswith(".html"):
            patterns.append(f"{normalized_pattern[:-5]}.json")
        for pattern in patterns:
            if fnmatch.fnmatch(normalized_path, pattern) or fnmatch.fnmatch(
                normalized_path, f"*/{pattern}"
            ):
                return source
    return None


def _is_json_source(source_path: str, text: str) -> bool:
    if source_path.replace("\\", "/").lower().endswith(".json"):
        return True
    return text[:64].lstrip().startswith(("[", "{"))


def _parse_json_activity(text: str, *, source: InstagramSource) -> ParseResult:
    """Parse the JSON variant of a supported Instagram export file.

    Instagram JSON files hold one list of records (e.g. ``likes_media_likes``,
    ``saved_saved_media``, ``impressions_history_videos_watched``,
    ``ig_reels_media``, ``messages``) or are a bare list.  Every record yields
    one event at its Unix timestamp (``timestamp``, ``creation_timestamp`` or
    ``timestamp_ms``, possibly nested in ``string_list_data`` /
    ``string_map_data`` / ``media``).  JSON timestamps are UTC, so no
    export-timezone assumption is needed.
    """
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
    if not records:
        return ParseResult(
            events=[],
            subscriptions=[],
            warnings=[ParseWarning(code="no_timestamped_records", sample=None)],
            records_seen=0,
        )

    events: list[ParsedEvent] = []
    warnings: list[ParseWarning] = []
    for sequence, record in enumerate(records, start=1):
        sample = _sample(sequence)
        if not isinstance(record, Mapping):
            warnings.append(ParseWarning(code="malformed_json_record", sample=sample))
            continue

        occurred_at = _json_timestamp(record)
        if occurred_at is None:
            warnings.append(ParseWarning(code="missing_timestamp", sample=sample))
            continue

        events.append(
            ParsedEvent(
                platform="instagram",
                product=source.product,
                event_type=source.event_type,
                occurred_at=occurred_at,
                title=None if source.redact_title else _json_title(record),
                sequence=sequence,
                duration_seconds=DEFAULT_INSTAGRAM_INTERACTION_DURATION_SECONDS,
            )
        )

    return ParseResult(
        events=events,
        subscriptions=[],
        warnings=warnings,
        records_seen=len(records),
    )


def _json_records(payload: Any) -> list[Any] | None:
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, Mapping):
        return None

    record_lists: list[list[Any]] = []
    for value in payload.values():
        if not isinstance(value, list):
            continue
        if any(
            isinstance(item, Mapping) and _json_timestamp(item) is not None
            for item in value[:25]
        ):
            return value
        if any(isinstance(item, Mapping) for item in value):
            record_lists.append(value)
    if len(record_lists) == 1:
        # A single record list without timestamps: parse it so every record
        # reports "missing_timestamp" instead of silently importing nothing.
        return record_lists[0]
    if _json_timestamp(payload) is not None:
        return [payload]
    if any(isinstance(value, list) for value in payload.values()):
        return []
    return None


def _json_timestamp(value: Any, depth: int = 0) -> datetime | None:
    if isinstance(value, Mapping):
        for key in JSON_TIMESTAMP_KEYS:
            parsed = _unix_timestamp(value.get(key), milliseconds=key.endswith("_ms"))
            if parsed is not None:
                return parsed
        if depth >= JSON_SEARCH_DEPTH:
            return None
        for nested in value.values():
            if isinstance(nested, (Mapping, list)):
                parsed = _json_timestamp(nested, depth + 1)
                if parsed is not None:
                    return parsed
    elif isinstance(value, list) and depth < JSON_SEARCH_DEPTH:
        for item in value[:25]:
            parsed = _json_timestamp(item, depth + 1)
            if parsed is not None:
                return parsed
    return None


def _unix_timestamp(value: Any, *, milliseconds: bool) -> datetime | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, str) and value.strip().isdigit():
        value = int(value.strip())
    if not isinstance(value, (int, float)) or value <= 0:
        return None
    seconds = value / 1000 if milliseconds or value > 100_000_000_000 else value
    try:
        return datetime.fromtimestamp(seconds, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def _json_title(record: Mapping[str, Any]) -> str | None:
    candidates: list[Any] = [record.get("title")]

    string_list = record.get("string_list_data")
    if isinstance(string_list, list):
        for item in string_list:
            if isinstance(item, Mapping):
                candidates.extend([item.get("value"), item.get("href")])

    string_map = record.get("string_map_data")
    if isinstance(string_map, Mapping):
        for item in string_map.values():
            if isinstance(item, Mapping):
                candidates.append(item.get("value"))

    media = record.get("media")
    if isinstance(media, list):
        for item in media:
            if isinstance(item, Mapping):
                candidates.append(item.get("title"))

    label_values = record.get("label_values")
    if isinstance(label_values, list):
        for item in label_values:
            if isinstance(item, Mapping):
                candidates.append(item.get("value"))

    for candidate in candidates:
        if isinstance(candidate, str):
            text = _normalize_whitespace(_fix_mojibake(candidate))
            if text:
                return text[:500]
    return None


def _fix_mojibake(value: str) -> str:
    """Instagram JSON escapes UTF-8 bytes as Latin-1 code points; undo that."""
    try:
        return value.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return value


def _parse_timestamped_html(text: str, *, source: InstagramSource) -> ParseResult:
    soup = BeautifulSoup(text, "lxml")
    candidates = _timestamp_candidates(soup)
    if not candidates:
        return ParseResult(
            events=[],
            subscriptions=[],
            warnings=[ParseWarning(code="no_timestamped_records", sample=None)],
            records_seen=0,
        )

    events: list[ParsedEvent] = []
    warnings: list[ParseWarning] = []

    for sequence, (timestamp_node, raw_timestamp) in enumerate(candidates, start=1):
        sample = _sample(sequence)
        occurred_at, timestamp_warnings = _parse_timestamp(raw_timestamp)
        warnings.extend(
            ParseWarning(code=warning_code, sample=sample)
            for warning_code in timestamp_warnings
        )
        if occurred_at is None:
            continue

        events.append(
            ParsedEvent(
                platform="instagram",
                product=source.product,
                event_type=source.event_type,
                occurred_at=occurred_at,
                title=None
                if source.redact_title
                else _record_title(timestamp_node, raw_timestamp),
                sequence=sequence,
                duration_seconds=DEFAULT_INSTAGRAM_INTERACTION_DURATION_SECONDS,
            )
        )

    return ParseResult(
        events=events,
        subscriptions=[],
        warnings=warnings,
        records_seen=len(candidates),
    )


def _timestamp_candidates(soup: BeautifulSoup) -> list[tuple[object, str]]:
    candidates: list[tuple[object, str]] = []
    seen_timestamps: set[tuple[int, str]] = set()

    for node in soup.find_all(True):
        classes = _class_names(node.get("class"))
        if not any(class_name in {"_3-94", "_a6-o"} for class_name in classes):
            continue
        timestamp = _timestamp_in_text(node.get_text(" ", strip=True))
        if timestamp is None:
            continue
        key = (id(node), timestamp)
        if key not in seen_timestamps:
            seen_timestamps.add(key)
            candidates.append((node, timestamp))

    if candidates:
        return candidates

    for text_node in soup.find_all(string=True):
        timestamp = _timestamp_in_text(str(text_node))
        if timestamp is None:
            continue
        key = (id(text_node), timestamp)
        if key not in seen_timestamps:
            seen_timestamps.add(key)
            candidates.append((text_node, timestamp))

    return candidates


def _timestamp_in_text(value: str) -> str | None:
    text = _normalize_whitespace(value)
    if not text:
        return None

    month_match = MONTH_TIMESTAMP_RE.search(text)
    if month_match is not None:
        return _normalize_timestamp_text(month_match.group(0))

    iso_match = ISO_TIMESTAMP_RE.search(text)
    if iso_match is not None:
        return _normalize_timestamp_text(iso_match.group(0))

    return None


def _parse_timestamp(raw_value: str) -> tuple[datetime | None, list[str]]:
    warnings: list[str] = []
    value = _normalize_timestamp_text(raw_value)
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    if re.search(r"[+-]\d{2}:?\d{2}$", normalized):
        normalized = _normalize_offset(normalized)

    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        parsed = None

    if parsed is None:
        for date_format in TIMESTAMP_FORMATS:
            try:
                parsed = datetime.strptime(value, date_format)
            except ValueError:
                continue
            break

    if parsed is None:
        return None, ["timestamp_parse_failed"]

    if parsed.tzinfo is not None:
        return parsed.astimezone(timezone.utc), warnings

    zone, timezone_warnings = _configured_timezone()
    warnings.extend(timezone_warnings)
    return parsed.replace(tzinfo=zone).astimezone(timezone.utc), warnings


def _configured_timezone() -> tuple[ZoneInfo, list[str]]:
    timezone_name = os.environ.get(INSTAGRAM_EXPORT_TIMEZONE_ENV)
    if not timezone_name:
        return ZoneInfo(DEFAULT_INSTAGRAM_EXPORT_TIMEZONE), ["timezone_assumed_utc"]

    try:
        return ZoneInfo(timezone_name), []
    except ZoneInfoNotFoundError:
        return ZoneInfo(DEFAULT_INSTAGRAM_EXPORT_TIMEZONE), [
            "invalid_timezone_assumed_utc"
        ]


def _record_title(timestamp_node: object, raw_timestamp: str) -> str | None:
    container = _record_container(timestamp_node)
    if not hasattr(container, "get_text"):
        return None

    text = _normalize_whitespace(container.get_text(" ", strip=True))
    text = _normalize_whitespace(text.replace(raw_timestamp, " "))
    return text[:500] if text else None


def _record_container(timestamp_node: object) -> object:
    current = getattr(timestamp_node, "parent", None)
    best = current if current is not None else timestamp_node
    for _ in range(6):
        parent = getattr(current, "parent", None)
        if parent is None:
            break
        current = parent
        if getattr(current, "name", None) not in {"div", "li"}:
            continue
        text = _normalize_whitespace(current.get_text(" ", strip=True))
        if len(text) > 40:
            best = current
            break
        best = current
    return best


def _decode_content(content: bytes) -> tuple[str, list[ParseWarning]]:
    try:
        return content.decode("utf-8-sig"), []
    except UnicodeDecodeError:
        return (
            content.decode("utf-8-sig", errors="replace"),
            [ParseWarning(code="invalid_utf8", sample=None)],
        )


def _normalize_timestamp_text(value: str) -> str:
    return _normalize_whitespace(value)


def _class_names(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, str):
        return value.split()
    return []


def _normalize_offset(value: str) -> str:
    if re.search(r"[+-]\d{2}:\d{2}$", value):
        return value
    return f"{value[:-2]}:{value[-2:]}"


def _normalize_whitespace(value: str) -> str:
    return " ".join(value.replace("\xa0", " ").replace("\u202f", " ").split())


def _sample(sequence: int) -> str:
    return f"record {sequence}"
