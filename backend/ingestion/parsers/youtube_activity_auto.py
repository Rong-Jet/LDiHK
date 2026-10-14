"""Language-independent parser for YouTube history files with unknown names.

Google localises Takeout folder and file names ("Verlauf/Wiedergabeverlauf.html",
"historial/...", ...), so the dispatcher cannot always tell from the path
whether a YouTube ``.json``/``.html`` file is the watch or the search history.
This parser classifies every record by its link instead:

* ``youtube.com/watch?v=...`` / ``youtu.be/...``      -> watch event
* ``youtube.com/results?search_query=...``           -> search event

Records without any link (e.g. "Watched a video that has been removed", in any
language) are treated as watches when the file is predominantly a watch
history, exactly like the English ``watch-history`` parser does.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from backend.ingestion.models import ParseResult, ParseWarning, ParsedEvent
from backend.ingestion.parsers import search_history, watch_history
from backend.ingestion.parsers.takeout_activity import iter_activity_cards

WATCH = "watch"
SEARCH = "search"
HTML_PARSE_CHUNK_BYTES = 64 * 1024
_URL_FIELDS = ("titleUrl", "title_url", "url", "link")


def parse_youtube_activity_auto(content: bytes, *, source_path: str) -> ParseResult:
    if _is_json_source(source_path, content):
        return _parse_json(content)
    return _parse_html(content)


# --------------------------------------------------------------------------
# JSON
# --------------------------------------------------------------------------


def _parse_json(content: bytes) -> ParseResult:
    warnings: list[ParseWarning] = []
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = content.decode("utf-8-sig", errors="replace")
        warnings.append(ParseWarning(code="invalid_utf8", sample=None))

    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return _result([], warnings + [ParseWarning(code="json_decode_failed")], 0)
    del text

    records = _json_records(payload)
    if records is None:
        return _result([], warnings + [ParseWarning(code="json_shape_unsupported")], 0)

    kinds = [_classify_json_record(record) for record in records]
    file_kind = _file_kind(kinds)
    events: list[ParsedEvent] = []

    for sequence, (record, kind) in enumerate(zip(records, kinds), start=1):
        if not isinstance(record, dict):
            warnings.append(
                ParseWarning(code="malformed_json_record", sample=_sample(sequence))
            )
            continue

        effective_kind = kind or (WATCH if file_kind == WATCH else None)
        if effective_kind == SEARCH:
            event, record_warnings = search_history.parse_search_json_record(
                record, sequence=sequence
            )
        elif effective_kind == WATCH:
            event, record_warnings = watch_history.parse_watch_json_record(
                record, sequence=sequence
            )
        else:
            continue

        warnings.extend(record_warnings)
        if event is not None:
            events.append(event)

    if file_kind is None and records:
        warnings.append(ParseWarning(code="youtube_activity_unrecognized"))
    return _result(events, warnings, len(records))


def _json_records(payload: Any) -> list[Any] | None:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in (
            "watchHistory",
            "watch_history",
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


def _classify_json_record(record: Any) -> str | None:
    if not isinstance(record, Mapping):
        return None
    urls = [
        value
        for key in _URL_FIELDS
        if isinstance(value := record.get(key), str) and value.strip()
    ]
    return _classify_urls(urls)


# --------------------------------------------------------------------------
# HTML
# --------------------------------------------------------------------------


def _parse_html(content: bytes) -> ParseResult:
    # One streaming pass.  Cards that carry a link are converted immediately;
    # link-less cards are kept (as small ActivityCard objects) until the file's
    # dominant kind is known, then emitted in their original position.
    entries: list[tuple[str | None, Any]] = []
    kinds: list[str | None] = []
    records_seen = 0

    for card in iter_activity_cards(content, chunk_size=HTML_PARSE_CHUNK_BYTES):
        records_seen += 1
        kind = _classify_urls([href for href, _ in card.anchors])
        kinds.append(kind)
        if kind == SEARCH:
            entries.append(
                (kind, search_history.parse_search_card(card, sequence=records_seen))
            )
        elif kind == WATCH:
            entries.append(
                (kind, watch_history.parse_watch_card(card, sequence=records_seen))
            )
        else:
            entries.append((None, (records_seen, card)))

    file_kind = _file_kind(kinds)
    events: list[ParsedEvent] = []
    warnings: list[ParseWarning] = []
    for kind, payload in entries:
        if kind is None:
            if file_kind != WATCH:
                continue
            sequence, card = payload
            payload = watch_history.parse_watch_card(card, sequence=sequence)
        event, record_warnings = payload
        warnings.extend(record_warnings)
        if event is not None:
            events.append(event)

    if file_kind is None and records_seen:
        warnings.append(ParseWarning(code="youtube_activity_unrecognized"))
    return _result(events, warnings, records_seen)


# --------------------------------------------------------------------------
# Shared
# --------------------------------------------------------------------------


def _classify_urls(urls: list[str]) -> str | None:
    if any(search_history.is_youtube_search_url(url) for url in urls):
        return SEARCH
    if any(watch_history.extract_video_id(url) is not None for url in urls):
        return WATCH
    return None


def _file_kind(kinds: list[str | None]) -> str | None:
    watches = sum(1 for kind in kinds if kind == WATCH)
    searches = sum(1 for kind in kinds if kind == SEARCH)
    if watches and watches >= searches:
        return WATCH
    if searches:
        return SEARCH
    return None


def _is_json_source(source_path: str, content: bytes) -> bool:
    normalized = source_path.replace("\\", "/").lower()
    if normalized.endswith(".json"):
        return True
    if normalized.endswith((".html", ".htm")):
        return False
    return content[:64].lstrip(b"\xef\xbb\xbf \t\r\n").startswith((b"[", b"{"))


def _result(
    events: list[ParsedEvent], warnings: list[ParseWarning], records_seen: int
) -> ParseResult:
    return ParseResult(
        events=events,
        subscriptions=[],
        warnings=warnings,
        records_seen=records_seen,
    )


def _sample(sequence: int) -> str:
    return f"record {sequence}"


__all__ = ["parse_youtube_activity_auto"]
