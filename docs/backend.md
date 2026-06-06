# Backend Business Requirements

This is the living business contract for what the backend delivers. Historical
implementation details belong in `docs/backend/versions/`.

## Current Delivery

- The backend serves privacy-minimized YouTube usage data for one local user.
- The backend keeps the full processed JSON API available for the frontend.
- The backend serves frontend-ready v2 temporal chart data derived from the
  processed JSON artifact.
- The backend can import watched YouTube events into a v3 SQLite usage store.
- The backend can enrich v3 video metadata with YouTube Data API durations.
- The backend serves structured v3 query responses from SQLite.
- The backend must not expose watched titles, URLs, channel names, video IDs, or
  raw Google Takeout HTML.
- The backend treats `Watched` YouTube activity as usage.
- The backend excludes YouTube Music from delivered v2 usage metrics so the
  product can focus on YouTube video usage first.
- The backend excludes `Viewed` activity from delivered usage metrics because
  post/community views are not relevant to the product's usage analysis.

## v2 Business Requirements

- Add frontend-ready temporal APIs derived from the existing processed JSON.
- Keep the existing full JSON endpoint available.
- Provide daily evolution data for time-series charts.
- Provide day-by-hour data for calendar or heatmap visualizations.
- Include zero-count dates so time-series charts can render continuous ranges.
- Include zero-count day/hour buckets so heatmaps can render complete grids.
- Default temporal outputs to the full local-date range covered by watched
  events.
- Do not require date-range query parameters in v2.
- Return both `event_count` and `estimated_seconds`.
- Include `session_count` in daily output.
- Count daily sessions by the session start date only.
- Count events by their start timestamp.
- Calculate `estimated_seconds` from merged intervals, split into the relevant
  day/hour buckets.
- Return YouTube-only totals.
- Do not include raw event rows in the v2 temporal endpoint.
- Do not return average session length; the frontend can derive averages from
  the session list.
- Use a fixed placeholder duration of `600` seconds for each watched event.
- Label placeholder duration as estimated data.
- Do not call the YouTube API or enrich records with real video duration in v2.
- Define sessions from watched events only.
- Start a new session when the inactivity gap between the current merged
  session end and the next watched-event interval start is more than `30`
  minutes.
- Model each watched event as a `600` second interval.
- Prevent duration overlaps by merging overlapping watched-event intervals.
- Calculate estimated duration from the merged interval span, not from
  `event_count * 600`.
- Use the same merged intervals for daily totals, hourly heatmaps, and sessions.
- Split merged interval duration across day and hour boundaries when needed.

## v3 Business Requirements

- Use SQL as the backend data bank for usage events and video metadata.
- Reparse the local Takeout HTML during v3 SQL import so internal video IDs can
  be stored without weakening the public v1 JSON privacy contract.
- Treat the v1 processed JSON as a public transition artifact, not the long-term
  data bank.
- Preserve privacy at the API boundary: do not expose watched titles, channel
  names, video IDs, raw Takeout HTML, or raw SQL execution.
- Do not allow the frontend to submit arbitrary SQL.
- Let the frontend submit structured query requests that the backend validates
  and compiles into parameterized SQL.
- Store internal YouTube video IDs so durations can be fetched and cached.
- Fetch actual video duration from the YouTube Data API when an API key is
  configured.
- Cache video duration results by `video_id` to avoid repeated API calls.
- Track unavailable, deleted, private, failed, and capped-duration videos.
- Keep duration enrichment separate from query serving so API reads do not call
  external services.

## Required API Outcomes

The full JSON endpoint remains available:

```text
GET /api/users/local_user/youtube-usage
```

v2 adds a temporal endpoint shaped for frontend charts:

```text
GET /api/v2/users/local_user/youtube-usage/temporal
```

The temporal response should include:

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

v3 adds a structured SQL-backed query endpoint:

```text
POST /api/v3/query
```

The frontend sends validated query requests, not raw SQL.

The v3 query response includes `duration_strategy`, `quality`, and aggregate
`rows`. Unknown-duration events count toward `event_count`, are excluded from
`watch_seconds`, and increment `events_missing_duration`.

## Out Of Scope

- Frontend-submitted raw SQL.
- Content metadata analysis beyond duration lookup.
- Instagram, TikTok, and Douyin support.
- Multi-user support.
- Postgres or analytics warehouse migration.
- AI augmentation.
- Serving or exposing raw source exports.
