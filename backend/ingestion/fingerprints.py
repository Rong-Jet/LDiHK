from __future__ import annotations

import hashlib
import json
from datetime import datetime

from backend.ingestion.models import ParsedEvent


def event_fingerprint(
    event: ParsedEvent,
    *,
    user_id: str,
    source_path: str,
) -> str:
    if event.native_id:
        return _sha256_payload(
            {
                "version": 1,
                "strategy": "native_id",
                "user_id": user_id,
                "event_type": event.event_type,
                "native_id": event.native_id,
            }
        )

    return _sha256_payload(
        {
            "version": 1,
            "strategy": "source_sequence",
            "user_id": user_id,
            "event_type": event.event_type,
            "occurred_at": _datetime_value(event.occurred_at),
            "video_id": event.video_id,
            "channel_id": event.channel_id,
            "source_path": source_path.replace("\\", "/").strip("/"),
            "sequence": event.sequence,
        }
    )


def _datetime_value(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _sha256_payload(payload: dict[str, object]) -> str:
    serialized = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
