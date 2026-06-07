from __future__ import annotations

import fnmatch
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
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
        path_pattern="your_instagram_activity/messages/**/*.html",
        event_type="message",
        product="messages",
        redact_title=True,
    ),
)


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

    result = _parse_timestamped_html(text, source=source)
    return ParseResult(
        events=result.events,
        subscriptions=[],
        warnings=decode_warnings + result.warnings,
        records_seen=result.records_seen,
    )


def source_for_path(source_path: str) -> InstagramSource | None:
    normalized_path = normalize_member_path(source_path)
    for source in INSTAGRAM_SOURCE_REGISTRY:
        normalized_pattern = normalize_member_path(source.path_pattern)
        if fnmatch.fnmatch(normalized_path, normalized_pattern) or fnmatch.fnmatch(
            normalized_path, f"*/{normalized_pattern}"
        ):
            return source
    return None


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
