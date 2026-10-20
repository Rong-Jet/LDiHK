from __future__ import annotations

import csv
import json
import re
import unicodedata
from collections.abc import Mapping
from datetime import datetime, timezone
from io import StringIO
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from backend.ingestion.models import ParseResult, ParseWarning, ParsedEvent


PRODUCTS = {
    "youtube": "youtube",
    "youtube music": "youtube_music",
}

TIMESTAMP_FIELDS = (
    "time",
    "timestamp",
    "activityTime",
    "activity_time",
    "addedAt",
    "added_at",
    "dateAdded",
    "date_added",
    "publishedAt",
    "published_at",
)

VIDEO_ID_FIELDS = (
    "videoId",
    "video_id",
)

VIDEO_URL_FIELDS = (
    "titleUrl",
    "title_url",
    "videoUrl",
    "video_url",
    "url",
    "link",
)

TITLE_FIELDS = (
    "title",
    "name",
    "videoTitle",
    "video_title",
)

PLAYLIST_ITEM_ID_FIELDS = (
    "playlistItemId",
    "playlist_item_id",
)

CREATOR_PLAYLIST_FILENAMES = {
    "uploads",
    "uploadedvideos",
    "myuploads",
}
CREATOR_PLAYLIST_PREFIXES = ("uploadsfrom",)

# Accent-folded, alphanumeric-only playlist file stems (after removing the
# "-videos" suffix of current Takeout CSV names) per event type.
LIKED_PLAYLIST_SLUGS = {
    "likes",
    "likedvideos",
    "likedmusic",
    "videosquemegustan",  # es
    "videosjaime",  # fr
    "videopiaciuti",  # it
    "videosmarcadoscomgostei",  # pt
    "videosquecurti",
    "videosdieikleukvind",  # nl
    "positivbewertetevideos",  # de
    "videosdiemirgefallen",
    "magichvideos",
}
WATCH_LATER_PLAYLIST_SLUGS = {
    "watchlater",
    "spateransehen",  # de "Spaeter ansehen"
    "spaeteransehen",
    "vermastarde",  # es "Ver mas tarde"
    "aregarderplustard",  # fr "A regarder plus tard"
    "guardapiutardi",  # it "Guarda piu tardi"
    "assistirmaistarde",  # pt "Assistir mais tarde"
    "verdepois",
    "laterbekijken",  # nl "Later bekijken"
}
PLAYLIST_METADATA_SLUGS = {"playlists", "playlist"}
CSV_VIDEO_SUFFIX_RE = re.compile(r"[-_]v[i\u00ed]deos?$", re.IGNORECASE)
CSV_VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
CSV_VIDEO_ID_HEADERS = {
    "videoid",
    "idvideo",
    "iddelvideo",  # es / it
    "iddevideo",
    "idduvideo",  # fr
    "iddelavideo",
    "iddovideo",  # pt
}
CSV_TIMESTAMP_HEADERS = {
    "playlistvideocreationtimestamp",
    "timeadded",
    "dateadded",
    "addedat",
    "videoaddedtimestamp",
    "videocreationtimestamp",
}


def parse_likes_playlists(content: bytes, *, source_path: str) -> ParseResult:
    if _is_creator_playlist_source(source_path):
        return _empty_result()

    if source_path.replace("\\", "/").lower().endswith(".csv"):
        return _parse_playlist_csv(content, source_path=source_path)

    text, decode_warnings = _decode_content(content)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return ParseResult(
            events=[],
            subscriptions=[],
            warnings=decode_warnings
            + [ParseWarning(code="json_decode_failed", sample=None)],
            records_seen=0,
        )

    records = _json_records(payload)
    if records is None:
        return ParseResult(
            events=[],
            subscriptions=[],
            warnings=decode_warnings
            + [ParseWarning(code="json_shape_unsupported", sample=None)],
            records_seen=0,
        )

    event_type = _event_type_for_source(source_path)
    events: list[ParsedEvent] = []
    warnings: list[ParseWarning] = list(decode_warnings)

    for sequence, record in enumerate(records, start=1):
        sample = _sample(sequence)
        if not isinstance(record, Mapping):
            warnings.append(
                ParseWarning(code="malformed_playlist_entry", sample=sample)
            )
            continue

        event, record_warnings = _parse_playlist_entry(
            record,
            event_type=event_type,
            sequence=sequence,
        )
        warnings.extend(record_warnings)
        if event is not None:
            events.append(event)

    return ParseResult(
        events=events,
        subscriptions=[],
        warnings=warnings,
        records_seen=len(records),
    )


def _parse_playlist_csv(content: bytes, *, source_path: str) -> ParseResult:
    """Parse a Takeout playlist CSV.

    Current Takeout writes one "<Playlist>-videos.csv" per playlist with a
    "Video ID,Playlist Video Creation Timestamp" header; older exports put a
    playlist metadata block ("Playlist Id,...") and a blank line above a
    "Video Id,Time Added" block.  Headers are localised, so the video id
    column is also recognised by its values (11-character YouTube ids).
    "playlists.csv" only describes the playlists and yields no events.
    """
    text, warnings = _decode_content(content)
    rows = [
        [cell.strip() for cell in row]
        for row in csv.reader(StringIO(text))
        if any(cell.strip() for cell in row)
    ]
    del text
    if not rows:
        return _empty_result(warnings)

    layout = _csv_layout(rows)
    if layout is None:
        if _source_stem_slug(source_path) in PLAYLIST_METADATA_SLUGS or any(
            "playlist" in _normalize_header(cell) for cell in rows[0]
        ):
            return _empty_result(warnings)
        warnings.append(ParseWarning(code="csv_shape_unsupported", sample=None))
        return _empty_result(warnings)

    header_index, video_column, timestamp_column, strict = layout
    event_type = _event_type_for_source(source_path)
    events: list[ParsedEvent] = []
    records_seen = 0

    for row in rows[header_index + 1 :]:
        video_id = row[video_column] if video_column < len(row) else ""
        if not strict and not CSV_VIDEO_ID_RE.match(video_id):
            # Value-detected layout: non-id rows are headers / metadata.
            continue

        records_seen += 1
        sample = _sample(records_seen)
        if not video_id:
            warnings.append(ParseWarning(code="missing_video_id", sample=sample))
            continue

        raw_timestamp = (
            row[timestamp_column]
            if timestamp_column is not None and timestamp_column < len(row)
            else ""
        )
        if raw_timestamp:
            occurred_at, timestamp_warning = _parse_csv_timestamp(raw_timestamp)
        else:
            occurred_at, timestamp_warning = None, "missing_timestamp"
        if timestamp_warning is not None:
            warnings.append(ParseWarning(code=timestamp_warning, sample=sample))

        events.append(
            ParsedEvent(
                event_type=event_type,
                product="youtube",
                occurred_at=occurred_at,
                video_id=video_id,
                sequence=records_seen,
            )
        )

    return ParseResult(
        events=events,
        subscriptions=[],
        warnings=warnings,
        records_seen=records_seen,
    )


def _csv_layout(rows: list[list[str]]) -> tuple[int, int, int | None, bool] | None:
    """Return (header row index, video column, timestamp column, strict)."""
    for index, row in enumerate(rows):
        normalized = [_normalize_header(cell) for cell in row]
        for column, header in enumerate(normalized):
            if header in CSV_VIDEO_ID_HEADERS:
                return (
                    index,
                    column,
                    _csv_timestamp_column(normalized, rows[index + 1 :], column),
                    True,
                )

    data_rows = rows[1:]
    if not data_rows:
        return None
    width = max(len(row) for row in data_rows)
    for column in range(width):
        values = [row[column] for row in data_rows if column < len(row) and row[column]]
        matches = sum(1 for value in values if CSV_VIDEO_ID_RE.match(value))
        if matches and matches * 2 > len(data_rows):
            first_match = next(
                index
                for index, row in enumerate(rows)
                if index > 0 and column < len(row) and CSV_VIDEO_ID_RE.match(row[column])
            )
            header = [_normalize_header(cell) for cell in rows[first_match - 1]]
            return (
                first_match - 1,
                column,
                _csv_timestamp_column(header, rows[first_match:], column),
                False,
            )
    return None


def _csv_timestamp_column(
    normalized_header: list[str], data_rows: list[list[str]], video_column: int
) -> int | None:
    for column, header in enumerate(normalized_header):
        if column != video_column and header in CSV_TIMESTAMP_HEADERS:
            return column

    sample_row = data_rows[0] if data_rows else []
    for column, value in enumerate(sample_row):
        if column == video_column or not value:
            continue
        if _parse_csv_timestamp(value)[0] is not None:
            return column
    return None


def _parse_csv_timestamp(value: str) -> tuple[datetime | None, str | None]:
    normalized = value.strip()
    if normalized.upper().endswith(" UTC"):
        normalized = f"{normalized[:-4].strip()}+00:00"
    return _parse_iso_timestamp(normalized)


def _normalize_header(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", _fold(value))


def _fold(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def _parse_playlist_entry(
    record: Mapping[str, Any],
    *,
    event_type: str,
    sequence: int,
) -> tuple[ParsedEvent | None, list[ParseWarning]]:
    sample = _sample(sequence)
    video_id = _record_video_id(record)
    if video_id is None:
        return None, [ParseWarning(code="missing_video_id", sample=sample)]

    occurred_at, timestamp_warning = _parse_record_timestamp(record)
    warnings = []
    if timestamp_warning is not None:
        warnings.append(ParseWarning(code=timestamp_warning, sample=sample))

    return (
        ParsedEvent(
            event_type=event_type,
            product=_record_product(record),
            occurred_at=occurred_at,
            video_id=video_id,
            channel_id=_record_channel_id(record),
            title=_record_title(record),
            native_id=_record_native_id(record),
            sequence=sequence,
        ),
        warnings,
    )


def _decode_content(content: bytes) -> tuple[str, list[ParseWarning]]:
    try:
        return content.decode("utf-8-sig"), []
    except UnicodeDecodeError:
        return (
            content.decode("utf-8-sig", errors="replace"),
            [ParseWarning(code="invalid_utf8", sample=None)],
        )


def _json_records(payload: Any) -> list[Any] | None:
    if isinstance(payload, list):
        if _is_playlist_metadata_records(payload):
            return []
        return _flatten_playlist_containers(payload)

    if not isinstance(payload, Mapping):
        return None

    if _is_playlist_metadata_payload(payload):
        return []

    for key in ("items", "videos", "playlistItems", "playlist_items", "entries"):
        value = payload.get(key)
        if isinstance(value, list):
            return _flatten_playlist_containers(value)

    return None


def _flatten_playlist_containers(records: list[Any]) -> list[Any]:
    flattened: list[Any] = []
    for record in records:
        if isinstance(record, Mapping):
            nested_records = _nested_playlist_records(record)
            if nested_records is not None:
                flattened.extend(nested_records)
                continue
        flattened.append(record)
    return flattened


def _nested_playlist_records(record: Mapping[str, Any]) -> list[Any] | None:
    if _record_video_id(record) is not None:
        return None

    for key in ("items", "videos", "playlistItems", "playlist_items", "entries"):
        value = record.get(key)
        if isinstance(value, list):
            return _flatten_playlist_containers(value)
    return None


def _is_playlist_metadata_payload(payload: Mapping[str, Any]) -> bool:
    kind = _first_string(payload, "kind")
    if kind == "youtube#playlistListResponse":
        return True

    items = payload.get("items")
    return isinstance(items, list) and _is_playlist_metadata_records(items)


def _is_playlist_metadata_records(records: list[Any]) -> bool:
    if not records:
        return False

    has_playlist_metadata = False
    for item in records:
        if not isinstance(item, Mapping):
            return False
        if _record_video_id(item) is not None:
            return False
        item_kind = _first_string(item, "kind")
        if item_kind == "youtube#playlist":
            has_playlist_metadata = True

    return has_playlist_metadata


def _event_type_for_source(source_path: str) -> str:
    source_slug = _source_stem_slug(source_path)
    if source_slug in LIKED_PLAYLIST_SLUGS:
        return "like"
    if source_slug in WATCH_LATER_PLAYLIST_SLUGS:
        return "watch_later_add"
    return "playlist_add"


def _is_creator_playlist_source(source_path: str) -> bool:
    source_slug = _source_stem_slug(source_path)
    return source_slug in CREATOR_PLAYLIST_FILENAMES or source_slug.startswith(
        CREATOR_PLAYLIST_PREFIXES
    )


def _source_stem_slug(source_path: str) -> str:
    normalized_path = source_path.replace("\\", "/").strip("/")
    path = PurePosixPath(normalized_path)
    stem = path.stem
    if path.suffix.lower() == ".csv":
        # Current Takeout names playlist CSVs "<Playlist title>-videos.csv".
        stem = CSV_VIDEO_SUFFIX_RE.sub("", stem)
    return re.sub(r"[^a-z0-9]+", "", _fold(stem))


def _record_video_id(record: Mapping[str, Any]) -> str | None:
    video_id = _first_string(record, *VIDEO_ID_FIELDS)
    if video_id is not None:
        return video_id

    for path in (
        ("contentDetails",),
        ("content_details",),
        ("resourceId",),
        ("resource_id",),
        ("snippet", "resourceId"),
        ("snippet", "resource_id"),
        ("video",),
    ):
        nested = _nested_mapping(record, *path)
        if nested is None:
            continue
        video_id = _first_string(nested, *VIDEO_ID_FIELDS)
        if video_id is not None:
            return video_id

    kind = _first_string(record, "kind")
    if kind == "youtube#video":
        video_id = _first_string(record, "id")
        if video_id is not None:
            return video_id

    for url in _record_urls(record):
        video_id = _extract_video_id(url)
        if video_id is not None:
            return video_id

    return None


def _record_urls(record: Mapping[str, Any]) -> list[str]:
    urls: list[str] = []
    for value in _field_strings(record, *VIDEO_URL_FIELDS):
        urls.append(value)

    snippet = _nested_mapping(record, "snippet")
    if snippet is not None:
        for value in _field_strings(snippet, *VIDEO_URL_FIELDS):
            urls.append(value)

    return urls


def _record_product(record: Mapping[str, Any]) -> str:
    product = _normalize_product(_first_string(record, "header", "product"))
    if product is not None:
        return product

    products = record.get("products")
    if isinstance(products, list):
        for value in products:
            product = _normalize_product(value if isinstance(value, str) else None)
            if product is not None:
                return product

    for url in _record_urls(record):
        host = urlparse(_absolute_url(url)).netloc.lower()
        if host == "music.youtube.com":
            return "youtube_music"

    return "youtube"


def _record_channel_id(record: Mapping[str, Any]) -> str | None:
    channel_id = _first_string(
        record,
        "videoOwnerChannelId",
        "video_owner_channel_id",
        "channelId",
        "channel_id",
    )
    if channel_id is not None:
        return channel_id

    snippet = _nested_mapping(record, "snippet")
    if snippet is not None:
        return _first_string(
            snippet,
            "videoOwnerChannelId",
            "video_owner_channel_id",
        )

    return None


def _record_title(record: Mapping[str, Any]) -> str | None:
    title = _first_string(record, *TITLE_FIELDS)
    if title is not None:
        return title

    snippet = _nested_mapping(record, "snippet")
    if snippet is not None:
        return _first_string(snippet, *TITLE_FIELDS)

    return None


def _record_native_id(record: Mapping[str, Any]) -> str | None:
    native_id = _first_string(record, *PLAYLIST_ITEM_ID_FIELDS)
    if native_id is not None:
        return native_id

    kind = _first_string(record, "kind")
    if kind == "youtube#playlistItem":
        return _first_string(record, "id")

    return None


def _parse_record_timestamp(
    record: Mapping[str, Any],
) -> tuple[datetime | None, str | None]:
    value = _first_string(record, *TIMESTAMP_FIELDS)
    if value is None:
        snippet = _nested_mapping(record, "snippet")
        if snippet is not None:
            value = _first_string(snippet, *TIMESTAMP_FIELDS)

    if value is None:
        return None, "missing_timestamp"
    return _parse_iso_timestamp(value)


def _parse_iso_timestamp(value: str) -> tuple[datetime | None, str | None]:
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


def _extract_video_id(url: str | None) -> str | None:
    if not url:
        return None

    parsed = urlparse(_absolute_url(url))
    host = parsed.netloc.lower()
    if not _is_youtube_video_host(host):
        return None

    path_parts = [unquote(part) for part in parsed.path.split("/") if part]

    if host.endswith("youtu.be") and path_parts:
        return path_parts[0]

    query_values = parse_qs(parsed.query).get("v")
    if query_values and query_values[0]:
        return query_values[0]

    if _is_youtube_host(host) and len(path_parts) >= 2:
        if path_parts[0] in {"embed", "shorts", "v"} and path_parts[1]:
            return path_parts[1]

    return None


def _is_youtube_video_host(host: str) -> bool:
    return _is_youtube_host(host) or host == "youtu.be" or host.endswith(".youtu.be")


def _is_youtube_host(host: str) -> bool:
    return (
        host == "youtube.com"
        or host.endswith(".youtube.com")
        or host == "youtube-nocookie.com"
        or host.endswith(".youtube-nocookie.com")
    )


def _absolute_url(url: str) -> str:
    if url.startswith("//"):
        return f"https:{url}"
    if url.startswith("/"):
        return f"https://www.youtube.com{url}"
    return url


def _normalize_product(value: str | None) -> str | None:
    if value is None:
        return None
    return PRODUCTS.get(_normalize_whitespace(value).lower())


def _nested_mapping(record: Mapping[str, Any], *path: str) -> Mapping[str, Any] | None:
    current: Any = record
    for key in path:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)

    if not isinstance(current, Mapping):
        return None
    return current


def _first_string(record: Mapping[str, Any], *keys: str) -> str | None:
    for value in _field_strings(record, *keys):
        return value
    return None


def _field_strings(record: Mapping[str, Any], *keys: str) -> list[str]:
    values: list[str] = []
    for key in keys:
        value = record.get(key)
        if not isinstance(value, str):
            continue
        normalized = _normalize_whitespace(value)
        if normalized:
            values.append(normalized)
    return values


def _normalize_whitespace(value: str | None) -> str:
    if value is None:
        return ""
    return " ".join(value.split())


def _sample(sequence: int) -> str:
    return f"record {sequence}"


def _empty_result(warnings: list[ParseWarning] | None = None) -> ParseResult:
    return ParseResult(
        events=[],
        subscriptions=[],
        warnings=list(warnings or []),
        records_seen=0,
    )
