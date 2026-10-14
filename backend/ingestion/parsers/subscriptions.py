from __future__ import annotations

import csv
import json
import re
import unicodedata
from collections.abc import Iterable, Mapping
from io import StringIO
from typing import Any
from urllib.parse import unquote, urlparse

from backend.ingestion.models import ParseResult, ParseWarning, ParsedSubscription


CHANNEL_ID_RE = re.compile(r"^UC[0-9A-Za-z_-]{22}$")

# Normalised (lower-case, accent-free, alphanumeric only) CSV header names.
# Takeout localises the subscriptions.csv header row, e.g. German
# "Kanal-ID,Kanal-URL,Kanaltitel".
CHANNEL_ID_HEADERS = frozenset(
    {
        "channelid",
        "kanalid",  # de
        "iddelcanal",  # es
        "idcanal",
        "iddelachaine",  # fr
        "idchaine",
        "iddelcanale",  # it
        "idcanale",
        "iddocanal",  # pt
        "kanaalid",  # nl
    }
)
CHANNEL_URL_HEADERS = frozenset(
    {
        "channelurl",
        "kanalurl",
        "urldelcanal",
        "urlcanal",
        "urldelachaine",
        "urlchaine",
        "urldelcanale",
        "urlcanale",
        "urldocanal",
        "kanaalurl",
    }
)
CHANNEL_TITLE_HEADERS = frozenset(
    {
        "channeltitle",
        "channelname",
        "title",
        "kanaltitel",
        "kanalname",
        "titulodelcanal",
        "nombredelcanal",
        "titredelachaine",
        "nomdelachaine",
        "titolodelcanale",
        "nomedelcanale",
        "titulodocanal",
        "nomedocanal",
        "kanaaltitel",
        "kanaalnaam",
    }
)


def parse_subscriptions(content: bytes, *, source_path: str) -> ParseResult:
    text = content.decode("utf-8-sig")
    if source_path.lower().endswith(".json"):
        return _parse_json_subscriptions(text)

    reader = csv.DictReader(StringIO(text))
    return _parse_subscription_rows(reader)


def _parse_json_subscriptions(text: str) -> ParseResult:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as error:
        return ParseResult(
            events=[],
            subscriptions=[],
            warnings=[ParseWarning(code="invalid_json", sample=error.msg)],
            records_seen=0,
        )

    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict) and isinstance(payload.get("items"), list):
        rows = payload["items"]
    elif isinstance(payload, dict) and isinstance(payload.get("subscriptions"), list):
        rows = payload["subscriptions"]
    else:
        return ParseResult(
            events=[],
            subscriptions=[],
            warnings=[ParseWarning(code="unsupported_json_shape")],
            records_seen=0,
        )

    return _parse_subscription_rows(rows)


def _parse_subscription_rows(rows: Iterable[Mapping[str, Any] | Any]) -> ParseResult:
    subscriptions: list[ParsedSubscription] = []
    warnings: list[ParseWarning] = []
    seen_channel_ids: set[str] = set()
    records_seen = 0

    for row in rows:
        records_seen += 1
        if not isinstance(row, Mapping):
            warnings.append(
                ParseWarning(
                    code="malformed_subscription_row",
                    sample=f"row {records_seen}",
                )
            )
            continue

        channel_id = _subscription_channel_id(row)
        if not channel_id:
            warnings.append(
                ParseWarning(code="missing_channel_id", sample=f"row {records_seen}")
            )
            continue

        if channel_id in seen_channel_ids:
            continue

        seen_channel_ids.add(channel_id)
        subscriptions.append(
            ParsedSubscription(
                channel_id=channel_id,
                channel_url=_subscription_channel_url(row),
                channel_title=_subscription_channel_title(row),
            )
        )

    return ParseResult(
        events=[],
        subscriptions=subscriptions,
        warnings=warnings,
        records_seen=records_seen,
    )


def _subscription_channel_id(row: Mapping[str, Any]) -> str | None:
    channel_id = (
        _field_value(row, "Channel Id", "channelId", "channel_id")
        or _header_value(row, CHANNEL_ID_HEADERS)
        or _nested_field_value(
            row,
            ("snippet", "resourceId"),
            "channelId",
            "channel_id",
        )
    )
    if channel_id:
        return channel_id
    if _has_known_header(row, CHANNEL_ID_HEADERS):
        # A recognised (but empty) channel id column is a malformed row; do
        # not guess the id from other columns.
        return None

    # Unknown header language: recognise the id by its value ("UC" + 22
    # chars), either directly or inside a /channel/<id> URL.
    for value in _string_values(row):
        if CHANNEL_ID_RE.match(value):
            return value
    for value in _string_values(row):
        channel_id = _channel_id_from_url(value)
        if channel_id is not None:
            return channel_id
    return None


def _subscription_channel_url(row: Mapping[str, Any]) -> str | None:
    url = _field_value(
        row,
        "Channel Url",
        "channelUrl",
        "channel_url",
    ) or _header_value(row, CHANNEL_URL_HEADERS)
    if url or _has_known_header(row, CHANNEL_URL_HEADERS):
        return url

    for value in _string_values(row):
        if value.lower().startswith(("http://", "https://")):
            return value
    return None


def _subscription_channel_title(row: Mapping[str, Any]) -> str | None:
    title = (
        _field_value(
            row,
            "Channel Title",
            "channelTitle",
            "channel_title",
            "title",
        )
        or _header_value(row, CHANNEL_TITLE_HEADERS)
        or _nested_field_value(
            row,
            ("snippet",),
            "title",
            "channelTitle",
            "channel_title",
        )
    )
    if title or _has_known_header(row, CHANNEL_TITLE_HEADERS):
        return title
    if not all(isinstance(key, str) for key in row.keys()):
        return None
    if _has_known_header(row, CHANNEL_ID_HEADERS):
        return None

    # Unknown header language: the title is the remaining non-id, non-URL cell.
    for value in _string_values(row):
        if CHANNEL_ID_RE.match(value):
            continue
        if value.lower().startswith(("http://", "https://")):
            continue
        return value
    return None


def _channel_id_from_url(value: str) -> str | None:
    if not value.lower().startswith(("http://", "https://")):
        return None
    path_parts = [unquote(part) for part in urlparse(value).path.split("/") if part]
    if len(path_parts) >= 2 and path_parts[0] == "channel":
        if CHANNEL_ID_RE.match(path_parts[1]):
            return path_parts[1]
    return None


def _header_value(row: Mapping[str, Any], headers: frozenset[str]) -> str | None:
    for key, value in row.items():
        if not isinstance(key, str) or _normalize_header(key) not in headers:
            continue
        if value is None:
            continue
        normalized = str(value).strip()
        if normalized:
            return normalized
    return None


def _has_known_header(row: Mapping[str, Any], headers: frozenset[str]) -> bool:
    return any(
        isinstance(key, str) and _normalize_header(key) in headers for key in row.keys()
    )


def _string_values(row: Mapping[str, Any]) -> list[str]:
    values: list[str] = []
    for key, value in row.items():
        if key is None or not isinstance(value, str):
            continue
        normalized = value.strip()
        if normalized:
            values.append(normalized)
    return values


def _normalize_header(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    return "".join(
        character
        for character in decomposed
        if character.isalnum() and not unicodedata.combining(character)
    )


def _nested_field_value(
    row: Mapping[str, Any],
    path: tuple[str, ...],
    *field_names: str,
) -> str | None:
    current: Any = row
    for field_name in path:
        if not isinstance(current, Mapping):
            return None
        current = current.get(field_name)

    if not isinstance(current, Mapping):
        return None

    return _field_value(current, *field_names)


def _field_value(row: Mapping[str, Any], *field_names: str) -> str | None:
    for field_name in field_names:
        value = row.get(field_name)
        if value is None:
            continue

        value = str(value).strip()
        if value:
            return value

    return None
