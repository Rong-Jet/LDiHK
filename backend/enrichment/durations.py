from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, Sequence

from backend.enrichment.youtube_api import MAX_VIDEO_IDS_PER_REQUEST


DEFAULT_MAX_DURATION_SECONDS = 5400
YOUTUBE_DATA_API_SOURCE = "youtube_data_api"

AVAILABLE = "available"
DELETED_OR_UNAVAILABLE = "deleted_or_unavailable"
PRIVATE_OR_RESTRICTED = "private_or_restricted"
API_ERROR = "api_error"
DURATION_PARSE_FAILED = "duration_parse_failed"
RETRIABLE_AVAILABILITY_STATUSES = (API_ERROR,)

_YOUTUBE_DURATION_PATTERN = re.compile(
    r"P"
    r"(?:(?P<weeks>\d+)W)?"
    r"(?:(?P<days>\d+)D)?"
    r"(?:T"
    r"(?:(?P<hours>\d+)H)?"
    r"(?:(?P<minutes>\d+)M)?"
    r"(?:(?P<seconds>\d+)S)?"
    r")?"
)


@dataclass(frozen=True)
class EnrichedYoutubeVideo:
    video_id: str
    channel_id: str | None
    duration_seconds: int | None
    duration_source: str | None
    availability_status: str
    max_duration_applied: bool
    last_error: str | None


@dataclass(frozen=True)
class DurationEnrichmentSummary:
    requested_video_count: int
    successful_video_count: int
    unavailable_video_count: int
    failed_video_count: int
    api_call_count: int


def parse_youtube_duration(duration: str) -> int:
    match = _YOUTUBE_DURATION_PATTERN.fullmatch(duration)
    if match is None:
        raise ValueError(f"unsupported YouTube duration: {duration}")

    parts = {key: int(value or 0) for key, value in match.groupdict().items()}
    if not any(parts.values()) and duration != "PT0S":
        raise ValueError(f"unsupported YouTube duration: {duration}")

    return (
        parts["weeks"] * 7 * 24 * 60 * 60
        + parts["days"] * 24 * 60 * 60
        + parts["hours"] * 60 * 60
        + parts["minutes"] * 60
        + parts["seconds"]
    )


def select_video_ids_to_enrich(
    connection,
    *,
    refresh: bool = False,
    limit: int | None = None,
    event_types: Sequence[str] = ("watch",),
) -> list[str]:
    if not event_types:
        raise ValueError("event_types must contain at least one value")

    placeholder = _placeholder(connection)
    event_type_placeholders = ", ".join([placeholder] * len(event_types))
    parameters: list[object] = ["youtube", "youtube", *event_types]
    cache_clause = ""
    if not refresh:
        retriable_placeholders = ", ".join(
            [placeholder] * len(RETRIABLE_AVAILABILITY_STATUSES)
        )
        cache_clause = (
            "AND (yv.video_id IS NULL "
            f"OR yv.availability_status IN ({retriable_placeholders}))"
        )
        parameters.extend(RETRIABLE_AVAILABILITY_STATUSES)

    limit_clause = ""
    if limit is not None:
        if limit < 1:
            raise ValueError("limit must be positive")
        limit_clause = f"LIMIT {placeholder}"
        parameters.append(limit)

    rows = connection.execute(
        f"""
        SELECT DISTINCT ue.video_id
        FROM usage_events ue
        LEFT JOIN youtube_videos yv
          ON yv.video_id = ue.video_id
        WHERE ue.platform = {placeholder}
          AND ue.product = {placeholder}
          AND ue.event_type IN ({event_type_placeholders})
          AND ue.video_id IS NOT NULL
          {cache_clause}
        ORDER BY ue.video_id
        {limit_clause}
        """,
        tuple(parameters),
    ).fetchall()
    return [row[0] for row in rows]


def enrich_missing_youtube_durations(
    connection,
    client,
    *,
    max_duration_seconds: int = DEFAULT_MAX_DURATION_SECONDS,
    batch_size: int = MAX_VIDEO_IDS_PER_REQUEST,
    limit: int | None = None,
    refresh: bool = False,
    event_types: Sequence[str] = ("watch",),
    commit: bool = True,
) -> DurationEnrichmentSummary:
    video_ids = select_video_ids_to_enrich(
        connection,
        refresh=refresh,
        limit=limit,
        event_types=event_types,
    )
    return enrich_youtube_video_ids(
        connection,
        client,
        video_ids,
        max_duration_seconds=max_duration_seconds,
        batch_size=batch_size,
        commit=commit,
    )


def enrich_youtube_video_ids(
    connection,
    client,
    video_ids: Iterable[str],
    *,
    max_duration_seconds: int = DEFAULT_MAX_DURATION_SECONDS,
    batch_size: int = MAX_VIDEO_IDS_PER_REQUEST,
    commit: bool = True,
) -> DurationEnrichmentSummary:
    if batch_size < 1 or batch_size > MAX_VIDEO_IDS_PER_REQUEST:
        raise ValueError("batch_size must be between 1 and 50")
    if max_duration_seconds < 1:
        raise ValueError("max_duration_seconds must be positive")

    requested_ids = _dedupe_video_ids(video_ids)
    successful = 0
    unavailable = 0
    failed = 0
    api_calls = 0

    for batch in _batches(requested_ids, batch_size):
        api_calls += 1
        fetched_at = _utc_now()
        try:
            returned_items = client.list_videos(batch)
        except Exception as error:
            failed += len(batch)
            last_error = _last_error(error)
            for video_id in batch:
                upsert_youtube_video(
                    connection,
                    EnrichedYoutubeVideo(
                        video_id=video_id,
                        channel_id=None,
                        duration_seconds=None,
                        duration_source=YOUTUBE_DATA_API_SOURCE,
                        availability_status=API_ERROR,
                        max_duration_applied=False,
                        last_error=last_error,
                    ),
                    fetched_at=fetched_at,
                )
            continue

        returned_by_id = {
            str(item["id"]): item
            for item in returned_items
            if isinstance(item.get("id"), str)
        }
        for video_id in batch:
            item = returned_by_id.get(video_id)
            if item is None:
                unavailable += 1
                video = EnrichedYoutubeVideo(
                    video_id=video_id,
                    channel_id=None,
                    duration_seconds=None,
                    duration_source=YOUTUBE_DATA_API_SOURCE,
                    availability_status=DELETED_OR_UNAVAILABLE,
                    max_duration_applied=False,
                    last_error="not_returned",
                )
            else:
                video = enriched_video_from_youtube_item(
                    item,
                    max_duration_seconds=max_duration_seconds,
                    fallback_video_id=video_id,
                )
                if video.availability_status == AVAILABLE:
                    successful += 1
                elif video.availability_status == DURATION_PARSE_FAILED:
                    failed += 1
                elif video.availability_status == API_ERROR:
                    failed += 1
                else:
                    unavailable += 1

            upsert_youtube_video(connection, video, fetched_at=fetched_at)

    if commit:
        connection.commit()

    return DurationEnrichmentSummary(
        requested_video_count=len(requested_ids),
        successful_video_count=successful,
        unavailable_video_count=unavailable,
        failed_video_count=failed,
        api_call_count=api_calls,
    )


def enriched_video_from_youtube_item(
    item: dict[str, object],
    *,
    max_duration_seconds: int = DEFAULT_MAX_DURATION_SECONDS,
    fallback_video_id: str | None = None,
) -> EnrichedYoutubeVideo:
    video_id = item.get("id")
    if not isinstance(video_id, str):
        if fallback_video_id is None:
            raise ValueError("YouTube item is missing id")
        video_id = fallback_video_id

    status = item.get("status")
    content_details = item.get("contentDetails")
    privacy_status = ""
    upload_status = ""
    if isinstance(status, dict):
        privacy_status = str(status.get("privacyStatus", ""))
        upload_status = str(status.get("uploadStatus", ""))

    if privacy_status == "private":
        return _unavailable_video(video_id, PRIVATE_OR_RESTRICTED, privacy_status)
    if upload_status in {"failed", "rejected"}:
        return _unavailable_video(video_id, API_ERROR, upload_status)
    if not isinstance(content_details, dict):
        return _unavailable_video(
            video_id, DELETED_OR_UNAVAILABLE, "missing_content_details"
        )

    duration = content_details.get("duration")
    if not isinstance(duration, str):
        return _unavailable_video(video_id, DURATION_PARSE_FAILED, "missing_duration")

    try:
        parsed_seconds = parse_youtube_duration(duration)
    except ValueError:
        return _unavailable_video(
            video_id, DURATION_PARSE_FAILED, "duration_parse_failed"
        )

    capped_seconds = min(parsed_seconds, max_duration_seconds)
    return EnrichedYoutubeVideo(
        video_id=video_id,
        channel_id=_channel_id_from_item(item),
        duration_seconds=capped_seconds,
        duration_source=YOUTUBE_DATA_API_SOURCE,
        availability_status=AVAILABLE,
        max_duration_applied=capped_seconds != parsed_seconds,
        last_error=None,
    )


def upsert_youtube_video(
    connection,
    video: EnrichedYoutubeVideo,
    *,
    fetched_at: datetime | None = None,
) -> None:
    placeholder = _placeholder(connection)
    fetched_at = _utc_now() if fetched_at is None else fetched_at
    fetched_at_value: object = fetched_at
    if _uses_sqlite_placeholders(connection):
        fetched_at_value = fetched_at.isoformat()
    connection.execute(
        f"""
        INSERT INTO youtube_videos (
            video_id,
            channel_id,
            duration_seconds,
            duration_source,
            availability_status,
            max_duration_applied,
            fetched_at,
            attempt_count,
            last_error
        )
        VALUES (
            {placeholder},
            {placeholder},
            {placeholder},
            {placeholder},
            {placeholder},
            {placeholder},
            {placeholder},
            1,
            {placeholder}
        )
        ON CONFLICT (video_id) DO UPDATE SET
            channel_id = COALESCE(excluded.channel_id, youtube_videos.channel_id),
            duration_seconds = excluded.duration_seconds,
            duration_source = excluded.duration_source,
            availability_status = excluded.availability_status,
            max_duration_applied = excluded.max_duration_applied,
            fetched_at = excluded.fetched_at,
            attempt_count = youtube_videos.attempt_count + 1,
            last_error = excluded.last_error
        """,
        (
            video.video_id,
            video.channel_id,
            video.duration_seconds,
            video.duration_source,
            video.availability_status,
            video.max_duration_applied,
            fetched_at_value,
            video.last_error,
        ),
    )


def _unavailable_video(
    video_id: str, availability_status: str, last_error: str
) -> EnrichedYoutubeVideo:
    return EnrichedYoutubeVideo(
        video_id=video_id,
        channel_id=None,
        duration_seconds=None,
        duration_source=YOUTUBE_DATA_API_SOURCE,
        availability_status=availability_status,
        max_duration_applied=False,
        last_error=last_error,
    )


def _channel_id_from_item(item: dict[str, object]) -> str | None:
    snippet = item.get("snippet")
    if isinstance(snippet, dict) and isinstance(snippet.get("channelId"), str):
        return str(snippet["channelId"])
    channel_id = item.get("channelId")
    if isinstance(channel_id, str):
        return channel_id
    return None


def _dedupe_video_ids(video_ids: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(video_id for video_id in video_ids if video_id))


def _batches(values: Sequence[str], batch_size: int) -> list[list[str]]:
    return [
        list(values[index : index + batch_size])
        for index in range(0, len(values), batch_size)
    ]


def _placeholder(connection) -> str:
    if _uses_sqlite_placeholders(connection):
        return "?"
    return "%s"


def _uses_sqlite_placeholders(connection) -> bool:
    return type(connection).__module__.startswith("sqlite3")


def _last_error(error: Exception) -> str:
    message = str(error).strip()
    if not message:
        return error.__class__.__name__
    return f"{error.__class__.__name__}: {message}"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)
