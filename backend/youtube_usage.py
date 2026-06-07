from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup


SCHEMA_VERSION = "youtube_usage.v1"
DEFAULT_PERSON_ID = "local_user"
DEFAULT_TIMEZONE = "Europe/Berlin"
DEFAULT_INPUT_PATH = Path("data/watch-history.html")
DEFAULT_OUTPUT_PATH = Path("data/processed/users/local_user/youtube_usage.v1.json")

PRODUCTS = {
    "YouTube": "youtube",
    "YouTube Music": "youtube_music",
}
EVENT_TYPES = {
    "Watched": "watched",
    "Viewed": "viewed",
}
MONTHS = {
    "Jan": 1,
    "Feb": 2,
    "Mar": 3,
    "Apr": 4,
    "May": 5,
    "Jun": 6,
    "Jul": 7,
    "Aug": 8,
    "Sep": 9,
    "Sept": 9,
    "Oct": 10,
    "Nov": 11,
    "Dec": 12,
}
TIMESTAMP_RE = re.compile(
    r"\b(\d{1,2})\s+([A-Za-z]+)\s+(\d{4}),\s+"
    r"(\d{2}):(\d{2}):(\d{2})\s+([A-Z]+)\b"
)


@dataclass(frozen=True)
class UsageEvent:
    person_id: str
    platform: str
    product: str
    event_type: str
    watched_at: str
    duration_seconds: None

    def to_json(self) -> dict[str, object]:
        return {
            "person_id": self.person_id,
            "platform": self.platform,
            "product": self.product,
            "event_type": self.event_type,
            "watched_at": self.watched_at,
            "duration_seconds": self.duration_seconds,
        }


def process_usage_file(
    input_path: Path | str = DEFAULT_INPUT_PATH,
    output_path: Path | str = DEFAULT_OUTPUT_PATH,
    person_id: str = DEFAULT_PERSON_ID,
    timezone: str = DEFAULT_TIMEZONE,
) -> dict[str, object]:
    input_path = Path(input_path)
    output_path = Path(output_path)
    payload = build_usage_document(
        input_path.read_text(encoding="utf-8"),
        input_path=input_path,
        person_id=person_id,
        timezone=timezone,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return payload


def build_usage_document(
    html: str,
    input_path: Path | str,
    person_id: str = DEFAULT_PERSON_ID,
    timezone: str = DEFAULT_TIMEZONE,
) -> dict[str, object]:
    soup = BeautifulSoup(html, "lxml")
    warnings: Counter[str] = Counter()
    events: list[UsageEvent] = []
    cards = soup.select("div.outer-cell")

    for card in cards:
        event, warning = parse_card(card, person_id=person_id, timezone=timezone)
        if event is None:
            if warning:
                warnings[warning] += 1
            continue
        events.append(event)

    generated_at = datetime.now(ZoneInfo(timezone)).replace(microsecond=0).isoformat()
    warning_list = [
        {"code": code, "count": count} for code, count in sorted(warnings.items())
    ]

    return {
        "schema_version": SCHEMA_VERSION,
        "person_id": person_id,
        "generated_at": generated_at,
        "source": {
            "platform": "youtube",
            "input_path": str(input_path),
            "input_format": "google_takeout_html",
            "timezone": timezone,
        },
        "quality": {
            "records_seen": len(cards),
            "records_emitted": len(events),
            "records_rejected": len(cards) - len(events),
            "warnings": warning_list,
        },
        "events": [event.to_json() for event in events],
        "aggregates": compute_aggregates(events),
        "future_fields": {
            "duration_seconds": "null in v1; reserved for later enrichment or estimation"
        },
    }


def parse_card(card, person_id: str, timezone: str) -> tuple[UsageEvent | None, str | None]:
    header = card.select_one(".header-cell .mdl-typography--title")
    if header is None:
        return None, "missing_product"

    raw_product = header.get_text(" ", strip=True)
    product = PRODUCTS.get(raw_product)
    if product is None:
        return None, "unknown_product"

    body = _main_content_text(card)
    if not body:
        return None, "malformed_card"

    first_word = body.split()[0] if body.split() else ""
    event_type = EVENT_TYPES.get(first_word)
    if event_type is None:
        return None, "unknown_event_type" if first_word else "missing_event_type"

    timestamp_match = TIMESTAMP_RE.search(body)
    if timestamp_match is None:
        return None, "missing_timestamp"

    try:
        watched_at = _parse_timestamp(timestamp_match, timezone).isoformat()
    except ValueError:
        return None, "timestamp_parse_failed"

    return (
        UsageEvent(
            person_id=person_id,
            platform="youtube",
            product=product,
            event_type=event_type,
            watched_at=watched_at,
            duration_seconds=None,
        ),
        None,
    )


def _main_content_text(card) -> str:
    for content in card.select(".content-cell"):
        classes = set(content.get("class", []))
        if "mdl-typography--caption" in classes:
            continue
        if "mdl-typography--text-right" in classes:
            continue
        text = content.get_text("\n", strip=True)
        if text:
            return text
    return ""


def _parse_timestamp(match: re.Match[str], timezone: str) -> datetime:
    day, month_token, year, hour, minute, second, _zone = match.groups()
    month = MONTHS.get(month_token)
    if month is None:
        raise ValueError(f"unknown month: {month_token}")
    local_zone = ZoneInfo(timezone)
    return datetime(
        int(year),
        month,
        int(day),
        int(hour),
        int(minute),
        int(second),
        tzinfo=local_zone,
    )


def compute_aggregates(events: list[UsageEvent]) -> dict[str, list[dict[str, object]]]:
    by_day: Counter[tuple[str, str, str]] = Counter()
    by_hour: Counter[tuple[int, str, str]] = Counter()
    by_weekday: Counter[tuple[int, str, str, str]] = Counter()

    for event in events:
        watched_at = datetime.fromisoformat(event.watched_at)
        by_day[(watched_at.date().isoformat(), event.product, event.event_type)] += 1
        by_hour[(watched_at.hour, event.product, event.event_type)] += 1
        by_weekday[
            (
                watched_at.isoweekday(),
                watched_at.strftime("%A"),
                event.product,
                event.event_type,
            )
        ] += 1

    return {
        "by_day": [
            {
                "date": date,
                "product": product,
                "event_type": event_type,
                "event_count": count,
                "duration_seconds": None,
            }
            for (date, product, event_type), count in sorted(by_day.items())
        ],
        "by_hour_of_day": [
            {
                "hour": hour,
                "product": product,
                "event_type": event_type,
                "event_count": count,
                "duration_seconds": None,
            }
            for (hour, product, event_type), count in sorted(by_hour.items())
        ],
        "by_weekday": [
            {
                "weekday": weekday,
                "weekday_name": weekday_name,
                "product": product,
                "event_type": event_type,
                "event_count": count,
                "duration_seconds": None,
            }
            for (weekday, weekday_name, product, event_type), count in sorted(
                by_weekday.items()
            )
        ],
    }
