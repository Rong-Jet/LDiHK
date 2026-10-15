"""Shared helpers for Google Takeout "activity" exports (watch/search history).

The HTML exports are a flat list of ``div.outer-cell`` cards.  They are parsed
once with a streaming lxml pull parser; each card is reduced to a small
:class:`ActivityCard` (product, main body text, anchors, caption text) and the
lxml subtree is discarded immediately, so memory stays flat for very large
files and no card is ever re-serialised or re-parsed.

Timestamps in the HTML exports are rendered in the account's language and
time zone ("6 Jun 2026, 08:53:12 CEST", "12.03.2024, 14:22:11 MEZ",
"12 de mar. de 2024, 14:22:11 BRT", "12 mars 2024, 14:22:11 UTC+1", ...).
:func:`parse_text_timestamp` understands the formats of English, German,
Spanish, French, Italian, Portuguese and Dutch exports.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from lxml import etree


DEFAULT_HTML_PARSE_CHUNK_BYTES = 64 * 1024


@dataclass(frozen=True, slots=True)
class ActivityCard:
    """Language-independent summary of one ``div.outer-cell`` activity card."""

    product: str | None
    """Header product text (e.g. "YouTube"), or ``None`` without a header."""

    body: str | None
    """Whitespace-normalised text of the main content cell, ``None`` if absent."""

    anchors: tuple[tuple[str, str], ...]
    """``(href, normalised text)`` for each ``<a href>`` in the main content cell."""

    caption: str
    """Whitespace-normalised text of the caption cells ("Products", "Details")."""


# --------------------------------------------------------------------------
# Streaming JSON arrays
# --------------------------------------------------------------------------

_JSON_WHITESPACE = re.compile(r"[ \t\n\r]*")


def is_json_array(text: str) -> bool:
    """True when the document's top-level value is an array."""
    return text.startswith("[", _JSON_WHITESPACE.match(text, 0).end())


def iter_json_array(text: str) -> Iterator[object]:
    """Yield the items of a top-level JSON array one at a time.

    ``json.loads`` builds every record of a large export as Python objects at
    once (about +314 MB for a 150k-entry watch history, measured), which is
    too much for a 512 MB instance. Decoding item by item keeps only the
    current record alive. Raises ``json.JSONDecodeError`` on malformed input.
    """
    decoder = json.JSONDecoder()
    position = _JSON_WHITESPACE.match(text, 0).end()
    if not text.startswith("[", position):
        raise json.JSONDecodeError("Expecting '['", text, position)
    position = _JSON_WHITESPACE.match(text, position + 1).end()
    if text.startswith("]", position):
        position += 1
    else:
        while True:
            item, position = decoder.raw_decode(text, position)
            yield item
            position = _JSON_WHITESPACE.match(text, position).end()
            if text.startswith(",", position):
                position = _JSON_WHITESPACE.match(text, position + 1).end()
                continue
            if text.startswith("]", position):
                position += 1
                break
            raise json.JSONDecodeError("Expecting ',' delimiter", text, position)
    if _JSON_WHITESPACE.match(text, position).end() != len(text):
        raise json.JSONDecodeError("Extra data", text, position)


# --------------------------------------------------------------------------
# Streaming HTML card iteration
# --------------------------------------------------------------------------


def iter_activity_cards(
    content: bytes,
    *,
    chunk_size: int = DEFAULT_HTML_PARSE_CHUNK_BYTES,
) -> Iterator[ActivityCard]:
    """Yield one :class:`ActivityCard` per ``div.outer-cell`` in document order."""
    # Takeout HTML is always UTF-8; being explicit keeps non-ASCII month names
    # ("März", "février") intact even if libxml2 would guess another charset.
    parser = etree.HTMLPullParser(
        events=("end",),
        tag="div",
        recover=True,
        encoding="utf-8",
    )
    chunk_size = max(1, int(chunk_size))
    for chunk_start in range(0, len(content), chunk_size):
        parser.feed(content[chunk_start : chunk_start + chunk_size])
        yield from _drain_cards(parser)

    parser.close()
    yield from _drain_cards(parser)


def _drain_cards(parser: etree.HTMLPullParser) -> Iterator[ActivityCard]:
    for _, element in parser.read_events():
        if not _has_class(element, "outer-cell"):
            continue
        card = _card_from_element(element)
        _release_element(element)
        yield card


def _card_from_element(card: etree._Element) -> ActivityCard:
    header: etree._Element | None = None
    main: etree._Element | None = None
    captions: list[str] = []

    for element in card.iterdescendants():
        if not isinstance(element.tag, str):
            continue
        classes = _classes(element)
        if not classes:
            continue

        if header is None and "header-cell" in classes:
            header = _first_descendant_with_class(element, "mdl-typography--title")

        if "content-cell" not in classes:
            continue
        if "mdl-typography--caption" in classes:
            caption_text = element_text(element)
            if caption_text:
                captions.append(caption_text)
            continue
        if "mdl-typography--text-right" in classes:
            continue
        if main is None and element_text(element):
            main = element

    product = element_text(header) if header is not None else None
    if main is None:
        return ActivityCard(
            product=product,
            body=None,
            anchors=(),
            caption=" ".join(captions),
        )

    anchors = tuple(
        (href, element_text(anchor))
        for anchor in main.iter("a")
        if (href := anchor.get("href")) is not None
    )
    return ActivityCard(
        product=product,
        body=element_text(main),
        anchors=anchors,
        caption=" ".join(captions),
    )


def _first_descendant_with_class(
    element: etree._Element, class_name: str
) -> etree._Element | None:
    for descendant in element.iterdescendants():
        if isinstance(descendant.tag, str) and class_name in _classes(descendant):
            return descendant
    return None


def _release_element(element: etree._Element) -> None:
    element.clear()
    parent = element.getparent()
    if parent is None:
        return
    while element.getprevious() is not None:
        del parent[0]


def _has_class(element: etree._Element, class_name: str) -> bool:
    return class_name in _classes(element)


def _classes(element: etree._Element) -> list[str]:
    value = element.get("class")
    return value.split() if value else []


def element_text(element: etree._Element) -> str:
    """Equivalent of BeautifulSoup ``get_text(" ", strip=True)`` + whitespace collapse."""
    return " ".join(" ".join(element.itertext()).split())


# --------------------------------------------------------------------------
# Localised timestamps
# --------------------------------------------------------------------------

_MONTH_NAMES: dict[int, tuple[str, ...]] = {
    1: ("jan", "january", "januar", "janner", "jaenner", "enero", "ene",
        "janvier", "janv", "gennaio", "gen", "janeiro", "januari"),
    2: ("feb", "february", "februar", "febrero", "fevrier", "fevr", "fev",
        "febbraio", "fevereiro", "februari"),
    3: ("mar", "march", "marz", "maerz", "mrz", "marzo", "mars", "marco",
        "maart", "mrt"),
    4: ("apr", "april", "abril", "abr", "avril", "avr", "aprile"),
    5: ("may", "mai", "mayo", "mag", "maggio", "maio", "mei"),
    6: ("jun", "june", "juni", "junio", "juin", "giugno", "giu", "junho"),
    7: ("jul", "july", "juli", "julio", "juillet", "juil", "luglio", "lug",
        "julho"),
    8: ("aug", "august", "agosto", "ago", "aout", "augustus"),
    9: ("sep", "sept", "september", "septiembre", "setiembre", "septembre",
        "settembre", "set", "setembro"),
    10: ("oct", "october", "oktober", "okt", "octubre", "octobre", "ottobre",
         "ott", "outubro", "out"),
    11: ("nov", "november", "noviembre", "novembre", "novembro"),
    12: ("dec", "december", "dezember", "dez", "diciembre", "dic", "decembre",
         "dicembre", "dezembro"),
}
MONTHS: dict[str, int] = {
    name: month for month, names in _MONTH_NAMES.items() for name in names
}

# Offsets in minutes.  Ambiguous abbreviations follow the most common Takeout
# usage: CST/CDT = US Central, IST = India, AST = Atlantic, BST = British.
TIMEZONE_OFFSET_MINUTES: dict[str, int] = {
    "UTC": 0, "GMT": 0, "UT": 0, "Z": 0,
    "WET": 0, "WEZ": 0, "WEST": 60, "WESZ": 60, "BST": 60,
    "CET": 60, "MEZ": 60, "MET": 60, "WAT": 60,
    "CEST": 120, "MESZ": 120, "MEST": 120,
    "EET": 120, "OEZ": 120, "SAST": 120, "CAT": 120,
    "EEST": 180, "OESZ": 180, "MSK": 180, "TRT": 180, "EAT": 180, "IDT": 180,
    "GST": 240, "PKT": 300, "IST": 330, "NPT": 345,
    "ICT": 420, "WIB": 420,
    "HKT": 480, "SGT": 480, "PHT": 480, "AWST": 480,
    "JST": 540, "KST": 540,
    "ACST": 570, "AEST": 600, "ACDT": 630, "AEDT": 660,
    "NZST": 720, "NZDT": 780,
    "HST": -600, "AKST": -540, "AKDT": -480,
    "PST": -480, "PDT": -420, "MST": -420, "MDT": -360,
    "CST": -360, "CDT": -300, "EST": -300, "EDT": -240,
    "AST": -240, "ADT": -180, "NST": -210, "NDT": -150,
    "BRT": -180, "BRST": -120, "ART": -180, "UYT": -180,
    "CLT": -240, "CLST": -180, "VET": -240, "BOT": -240,
    "COT": -300, "PET": -300,
    # French (Canada) abbreviations.
    "HNA": -240, "HAA": -180, "HNE": -300, "HAE": -240, "HNC": -360,
    "HAC": -300, "HNR": -420, "HAR": -360, "HNP": -480, "HAP": -420,
    "HNT": -210, "HAT": -150,
}
# Kept for backwards compatibility with code that imported the old table.
TIMEZONE_OFFSETS: dict[str, float] = {
    name: minutes / 60 for name, minutes in TIMEZONE_OFFSET_MINUTES.items()
}

_GMT_OFFSET_RE = re.compile(
    r"^(?:UTC|GMT)\s?(?P<sign>[+\-−])\s?(?P<hour>\d{1,2})(?::?(?P<minute>\d{2}))?$",
    re.IGNORECASE,
)

ISO_TIMESTAMP_RE = re.compile(
    r"\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})\b"
)

_CONNECTOR = (
    r"(?:\s*,\s*|\s+)"
    r"(?:(?:à|a\s+las|a\s+la|às|as|alle|um|om|at|kl\.?)\s+)?"
)
_TIME = (
    r"(?P<hour>\d{1,2}):(?P<minute>\d{2})(?::(?P<second>\d{2}))?"
    r"(?:\s*(?P<ampm>[ap]\.?\s?m\.?)(?![^\W\d_]))?"
)
_ZONE = (
    r"(?:\s*\(?(?P<zone>(?:UTC|GMT)\s?[+\-−]\s?\d{1,2}(?::?\d{2})?"
    r"|[A-Za-z]{1,6})(?![^\W\d_])\)?)?"
)
_MONTH_WORD = r"(?P<month>[^\W\d_]{3,})\.?"

_TIMESTAMP_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        # 6 Jun 2026 | 6. Juni 2026 | 6 de junio de 2026 | 12 de mar. de 2024
        "named",
        re.compile(
            r"(?<!\d)(?P<day>\d{1,2})\.?\s+(?:de\s+)?" + _MONTH_WORD
            + r"\s+(?:de\s+)?(?P<year>\d{4})(?!\d)" + _CONNECTOR + _TIME + _ZONE,
            re.IGNORECASE,
        ),
    ),
    (
        # Jun 6, 2026
        "named",
        re.compile(
            _MONTH_WORD + r"\s+(?P<day>\d{1,2}),?\s+(?P<year>\d{4})(?!\d)"
            + _CONNECTOR + _TIME + _ZONE,
            re.IGNORECASE,
        ),
    ),
    (
        # 12.03.2024 | 12/03/2024 | 12-03-2024 (day first in all supported locales)
        "numeric",
        re.compile(
            r"(?<!\d)(?P<day>\d{1,2})[./-](?P<month>\d{1,2})[./-](?P<year>\d{4})(?!\d)"
            + _CONNECTOR + _TIME + _ZONE,
            re.IGNORECASE,
        ),
    ),
    (
        # 2024-03-12 | 2024/03/12
        "numeric",
        re.compile(
            r"(?<!\d)(?P<year>\d{4})[./-](?P<month>\d{1,2})[./-](?P<day>\d{1,2})(?!\d)\.?"
            + _CONNECTOR + _TIME + _ZONE,
            re.IGNORECASE,
        ),
    ),
)


def parse_text_timestamp(text: str) -> tuple[datetime | None, str | None]:
    """Parse the activity timestamp contained in a card's body text.

    Returns ``(datetime, warning_code_or_None)``.  When several candidates
    exist (e.g. a video title that contains a date) the last one wins,
    because Takeout always renders the timestamp after title and channel.
    """
    iso_match = ISO_TIMESTAMP_RE.search(text)
    if iso_match is not None:
        return parse_iso_timestamp(iso_match.group(0))

    normalized = " ".join(text.split())
    best: tuple[int, datetime | None, str | None] | None = None
    for kind, pattern in _TIMESTAMP_PATTERNS:
        for match in pattern.finditer(normalized):
            parsed = _timestamp_from_match(match, numeric_month=kind == "numeric")
            if parsed is None:
                continue
            if best is None or match.start() > best[0]:
                best = (match.start(), parsed[0], parsed[1])

    if best is None:
        return None, "missing_timestamp"
    return best[1], best[2]


def parse_iso_timestamp(value: str) -> tuple[datetime | None, str | None]:
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"

    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None, "timestamp_parse_failed"

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc), "timestamp_missing_timezone"
    return parsed, None


def _timestamp_from_match(
    match: re.Match[str], *, numeric_month: bool
) -> tuple[datetime | None, str | None] | None:
    """Return ``None`` when the match is not a timestamp (unknown month word)."""
    parts = match.groupdict()
    if numeric_month:
        month = int(parts["month"])
    else:
        month = month_number(parts["month"])
        if month is None:
            return None

    hour = int(parts["hour"])
    ampm = (parts.get("ampm") or "").replace(".", "").replace(" ", "").upper()
    if ampm == "PM" and hour < 12:
        hour += 12
    elif ampm == "AM" and hour == 12:
        hour = 0

    warning: str | None = None
    zone = parts.get("zone")
    if zone:
        tzinfo = parse_timezone(zone)
        if tzinfo is None:
            tzinfo = timezone.utc
            warning = "timestamp_unknown_timezone"
    else:
        tzinfo = timezone.utc
        warning = "timestamp_missing_timezone"

    try:
        value = datetime(
            int(parts["year"]),
            month,
            int(parts["day"]),
            hour,
            int(parts["minute"]),
            int(parts["second"] or 0),
            tzinfo=tzinfo,
        )
    except ValueError:
        return None, "timestamp_parse_failed"
    return value, warning


def month_number(value: str) -> int | None:
    return MONTHS.get(fold_text(value).strip(".").replace(".", ""))


def parse_timezone(value: str) -> timezone | None:
    compact = " ".join(value.split()).upper()
    minutes = TIMEZONE_OFFSET_MINUTES.get(compact)
    if minutes is not None:
        return timezone(timedelta(minutes=minutes), compact)

    match = _GMT_OFFSET_RE.match(compact)
    if match is None:
        return None

    hours = int(match.group("hour"))
    offset_minutes = int(match.group("minute") or "0")
    if hours > 14 or offset_minutes >= 60:
        return None
    delta = timedelta(hours=hours, minutes=offset_minutes)
    if match.group("sign") != "+":
        delta = -delta
    return timezone(delta, compact.replace(" ", "").replace("−", "-"))


def fold_text(value: str) -> str:
    """Lower-case and strip accents ("Février" -> "fevrier", "März" -> "marz")."""
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


# --------------------------------------------------------------------------
# Google Ads markers
# --------------------------------------------------------------------------

GOOGLE_ADS_RE = re.compile(
    r"\bgoogle\s*(?:ads|adwords)\b|google\s*広告|google\s*광고",
    re.IGNORECASE,
)


def mentions_google_ads(text: str | None) -> bool:
    """True for "From Google Ads", "Von Google Ads", "De Google Ads", ..."""
    return bool(text) and GOOGLE_ADS_RE.search(text) is not None
