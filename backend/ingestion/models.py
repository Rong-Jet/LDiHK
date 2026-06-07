from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class ParsedEvent:
    event_type: str
    product: str
    occurred_at: datetime | None
    video_id: str | None = None
    channel_id: str | None = None
    title: str | None = None
    search_query: str | None = None
    raw_status: str | None = None
    native_id: str | None = None
    sequence: int = 0


@dataclass(frozen=True)
class ParsedSubscription:
    channel_id: str
    channel_url: str | None
    channel_title: str | None


@dataclass(frozen=True)
class ParseWarning:
    code: str
    sample: str | None = None


@dataclass(frozen=True)
class ParseResult:
    events: list[ParsedEvent]
    subscriptions: list[ParsedSubscription]
    warnings: list[ParseWarning]
    records_seen: int


class ParserCallable(Protocol):
    def __call__(self, content: bytes, *, source_path: str) -> ParseResult:
        ...
