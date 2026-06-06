from __future__ import annotations

import csv
import json
from collections.abc import Iterable, Mapping
from io import StringIO
from typing import Any

from backend.ingestion.models import ParseResult, ParseWarning, ParsedSubscription


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
    return _field_value(
        row,
        "Channel Id",
        "channelId",
        "channel_id",
    ) or _nested_field_value(
        row,
        ("snippet", "resourceId"),
        "channelId",
        "channel_id",
    )


def _subscription_channel_url(row: Mapping[str, Any]) -> str | None:
    return _field_value(
        row,
        "Channel Url",
        "channelUrl",
        "channel_url",
    )


def _subscription_channel_title(row: Mapping[str, Any]) -> str | None:
    return _field_value(
        row,
        "Channel Title",
        "channelTitle",
        "channel_title",
        "title",
    ) or _nested_field_value(
        row,
        ("snippet",),
        "title",
        "channelTitle",
        "channel_title",
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
