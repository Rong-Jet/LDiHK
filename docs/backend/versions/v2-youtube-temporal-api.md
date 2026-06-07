# v2: YouTube Temporal API

## Status

Completed on 2026-06-06.

## Summary

v2 adds a frontend-ready temporal API for YouTube usage charts. It keeps the
existing full JSON API available, derives chart projections from the processed
v1 JSON artifact, and introduces estimated usage time without calling external
metadata or duration APIs.

## User Story

As a dashboard user, I want daily, hourly, and session-based YouTube usage
metrics, so that the frontend can show temporal evolution graphs, calendar
heatmaps, and usage sessions without processing raw event rows.

## Feature Set

- API-only upgrade derived from the existing processed JSON artifact.
- Existing full JSON endpoint remains available.
- New temporal endpoint for frontend chart data.
- YouTube-only usage metrics.
- `Watched` events only; `Viewed` events are excluded.
- YouTube Music is excluded from v2 delivered usage metrics.
- Fixed placeholder duration of `600` seconds per watched event.
- Overlapping watched-event intervals are merged before duration totals are
  calculated.
- Daily time-series output includes zero-count dates across the full watched
  event date range.
- Hourly heatmap output includes zero-count day/hour buckets across the full
  watched event date range.
- Sessions are included inside the temporal payload.
- No raw event rows are included in the temporal payload.

## Public Contract

Existing full JSON endpoint:

```text
GET /api/users/local_user/youtube-usage
```

New temporal endpoint:

```text
GET /api/v2/users/local_user/youtube-usage/temporal
```

Response shape:

```json
{
  "person_id": "local_user",
  "schema_version": "youtube_usage.temporal.v2",
  "source_schema_version": "youtube_usage.v1",
  "duration_strategy": {
    "kind": "fixed_placeholder",
    "watched_event_seconds": 600,
    "is_estimate": true
  },
  "daily": [
    {
      "date": "2026-06-06",
      "event_count": 42,
      "estimated_seconds": 25200,
      "session_count": 5
    }
  ],
  "hourly_heatmap": [
    {
      "date": "2026-06-06",
      "hour": 8,
      "event_count": 3,
      "estimated_seconds": 1800
    }
  ],
  "sessions": [
    {
      "session_id": "session_000001",
      "started_at": "2026-06-06T08:12:00+02:00",
      "ended_at": "2026-06-06T09:03:12+02:00",
      "observed_span_seconds": 3072,
      "event_count": 5,
      "estimated_seconds": 3072
    }
  ]
}
```

Temporal semantics:

- Input events are filtered to `product: "youtube"` and
  `event_type: "watched"`.
- Each watched event creates a `600` second interval starting at `watched_at`.
- Overlapping intervals are merged before `estimated_seconds` is calculated.
- `event_count` is counted by event start timestamp.
- `estimated_seconds` is calculated from merged intervals and split across
  local day/hour boundaries when needed.
- The temporal date range defaults to the full local-date range covered by
  watched YouTube events.
- Daily `session_count` counts sessions by session start date only.
- Sessions start from watched intervals and split when the inactivity gap
  between the current merged session end and the next interval start is more
  than `30` minutes.
- Session `ended_at` is the merged session end, including the final event's
  placeholder duration.
- Session `observed_span_seconds` is `ended_at - started_at`.
- Session `estimated_seconds` equals `observed_span_seconds`, including short
  gaps inside one session.

## Acceptance Criteria

- [x] `GET /api/users/local_user/youtube-usage` continues to return the full
      processed v1 JSON artifact.
- [x] `GET /api/v2/users/local_user/youtube-usage/temporal` returns a successful
      temporal payload when the processed v1 artifact exists.
- [x] The temporal payload uses `schema_version:
      "youtube_usage.temporal.v2"`.
- [x] The temporal payload includes `source_schema_version:
      "youtube_usage.v1"`.
- [x] The temporal endpoint includes only chart aggregates and sessions, not raw
      event rows.
- [x] The temporal endpoint filters out YouTube Music events.
- [x] The temporal endpoint filters out `viewed` events.
- [x] Duration strategy is reported as fixed placeholder estimated duration with
      `watched_event_seconds: 600`.
- [x] Daily output includes `date`, `event_count`, `estimated_seconds`, and
      `session_count`.
- [x] Daily output includes zero-count dates across the full watched YouTube
      date range.
- [x] Hourly heatmap output includes `date`, `hour`, `event_count`, and
      `estimated_seconds`.
- [x] Hourly heatmap output includes zero-count day/hour buckets across the full
      watched YouTube date range.
- [x] `event_count` is counted by watched event start timestamp.
- [x] `estimated_seconds` is calculated from merged non-overlapping intervals.
- [x] Merged interval duration is split across day and hour boundaries.
- [x] Sessions are grouped from watched intervals using a `30` minute inactivity
      gap.
- [x] Session `ended_at` includes the final watched event's placeholder
      duration.
- [x] Daily `session_count` counts sessions by session start date only.
- [x] Missing processed JSON preserves the existing
      `processed_data_missing` behavior.
- [x] Temporal responses do not expose watched titles, URLs, channel names,
      video IDs, or raw Takeout HTML.

## Verification

Automated tests:

```sh
uv --cache-dir .uv-cache run python -m unittest discover -s backend/tests
```

Manual smoke checks:

```text
GET /health -> 200
GET /api/users/local_user/youtube-usage -> 200
GET /api/v2/users/local_user/youtube-usage/temporal -> 200
```

## Out Of Scope

- YouTube API calls.
- `yt-dlp` metadata enrichment.
- Real video duration.
- Content metadata analysis.
- YouTube Music usage metrics.
- `Viewed` activity metrics.
- Instagram, TikTok, and Douyin support.
- Multi-user support.
- SQL persistence.
- AI augmentation.
- Raw event rows in the temporal endpoint.
- Separate `/sessions` endpoint.
- Date-range query parameters.
- Backend-provided average session length.

## Notes

The temporal endpoint is a projection over the existing v1 artifact, not a new
ingestion pipeline. v3 can replace placeholder duration with enriched metadata
or a better estimation model once the frontend chart contract is proven.
