"""Stable dedupe keys for parsed usage events.

Version 2 ("content" strategy) identifies an event by *what happened* rather
than *where it sat in a file*: user, platform, event type, the instant (UTC,
whole seconds), video, channel, search query, a normalised title when there is
no video id, and an occurrence counter for identical events inside the same
parse result.  ``source_path`` and ``sequence`` are deliberately excluded:

* Takeout exports are newest-first, so a newer export shifts every record's
  index; keys based on the index would duplicate every event on re-upload.
* The same activity exported as HTML or as JSON, or inside a re-zipped /
  renamed archive, must produce the same key.

Events that carry a ``native_id`` (comment ids, playlist item ids) keep the
native-id strategy.  Its payload is unchanged from version 1 on purpose, so
native-id rows imported before this change still dedupe against re-imports.
"""

from __future__ import annotations

import hashlib
import json
import unicodedata
from collections.abc import Sequence
from datetime import datetime, timezone

from backend.ingestion.models import ParsedEvent

CONTENT_FINGERPRINT_VERSION = 2
NATIVE_ID_FINGERPRINT_VERSION = 1


def event_fingerprints(
    events: Sequence[ParsedEvent],
    *,
    user_id: str,
    source_path: str,
) -> list[str]:
    """Return one fingerprint per event, in the same order as ``events``.

    Identical content tuples within ``events`` are disambiguated by an
    occurrence counter (0 for the first, 1 for the second, ...), so genuinely
    repeated events in one file are all kept while re-imports still collide.
    ``source_path`` is accepted for interface stability but never hashed.
    """
    del source_path
    occurrences: dict[str, int] = {}
    fingerprints: list[str] = []

    for event in events:
        if event.native_id:
            fingerprints.append(_native_id_fingerprint(event, user_id=user_id))
            continue

        content_key = _serialize(_content_payload(event, user_id=user_id))
        occurrence = occurrences.get(content_key, 0)
        occurrences[content_key] = occurrence + 1
        fingerprints.append(_content_fingerprint(content_key, occurrence))

    return fingerprints


def event_fingerprint(
    event: ParsedEvent,
    *,
    user_id: str,
    source_path: str,
) -> str:
    """Fingerprint of a single event, treated as occurrence 0.

    Prefer :func:`event_fingerprints` for a whole parse result so repeated
    identical events in one file receive distinct occurrence counters.
    """
    return event_fingerprints([event], user_id=user_id, source_path=source_path)[0]


def _native_id_fingerprint(event: ParsedEvent, *, user_id: str) -> str:
    return _sha256(
        _serialize(
            {
                "version": NATIVE_ID_FINGERPRINT_VERSION,
                "strategy": "native_id",
                "user_id": user_id,
                "event_type": event.event_type,
                "native_id": event.native_id,
            }
        )
    )


def _content_payload(event: ParsedEvent, *, user_id: str) -> dict[str, object]:
    return {
        "version": CONTENT_FINGERPRINT_VERSION,
        "strategy": "content",
        "user_id": user_id,
        "platform": event.platform,
        "event_type": event.event_type,
        "occurred_at": normalize_occurred_at(event.occurred_at),
        "video_id": event.video_id,
        "channel_id": event.channel_id,
        "title": normalize_title(event.title) if event.video_id is None else None,
        "search_query": _normalize_text(event.search_query),
    }


def _content_fingerprint(content_key: str, occurrence: int) -> str:
    return _sha256(f"{content_key}|occurrence={occurrence}")


def normalize_occurred_at(value: datetime | None) -> str | None:
    """UTC, truncated to whole seconds; naive datetimes are taken as UTC."""
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def normalize_title(value: str | None) -> str | None:
    text = _normalize_text(value)
    if text is None:
        return None
    return unicodedata.normalize("NFKC", text).casefold()


def _normalize_text(value: str | None) -> str | None:
    if value is None:
        return None
    text = " ".join(value.split())
    return text or None


def _serialize(payload: dict[str, object]) -> str:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )


def _sha256(serialized: str) -> str:
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
