# v3: SQL Duration And Query API

## Status

Completed on 2026-06-06.

## Summary

v3 moves the backend from a custom JSON artifact as the primary data bank to a
SQL-backed usage store. It adds a duration enrichment job that fetches actual
YouTube video durations, stores them in SQL, and exposes a validated query API
that the frontend can use for flexible chart requests.

## User Story

As a frontend developer, I want to request YouTube usage metrics through a
stable backend query API, so that the frontend can build temporal charts without
owning SQL, raw source files, or duration enrichment logic.

## Feature Set

- SQLite is the v3 SQL data bank.
- The v1 processed JSON artifact remains available as a transition API artifact,
  not the primary v3 data bank.
- The v3 SQL import reparses local Takeout HTML to store internal video IDs
  without exposing them through the v1 or v2 API contracts.
- Usage events are stored in SQL with internal YouTube video IDs.
- Video metadata is stored separately and keyed by `video_id`.
- YouTube duration enrichment runs as a backend job, not during API reads.
- Duration enrichment uses YouTube Data API `videos.list` with
  `part=contentDetails,status`.
- Duration results are cached by `video_id`.
- Deleted, private, unavailable, failed, rejected, and duration-parse-failed
  videos are tracked explicitly.
- Long video durations are capped by a configurable maximum duration.
- The frontend submits structured query requests.
- The backend validates query requests and compiles them to parameterized SQL.
- The frontend does not submit raw SQL in v3.
- Existing full JSON and v2 temporal endpoints can remain available during the
  transition.

## Public Contract

SQL database path:

```text
data/processed/users/local_user/youtube_usage.v3.sqlite
```

Recommended setup commands:

```sh
uv run python backend/scripts/import_youtube_usage_sql.py
uv run python backend/scripts/enrich_youtube_durations.py
```

Duration enrichment configuration:

```text
.env
YOUTUBE_API_KEY=<api key>
```

Query endpoint:

```text
POST /api/v3/query
```

Request shape:

```json
{
  "dataset": "youtube_usage",
  "person_id": "local_user",
  "metrics": ["event_count", "watch_seconds", "session_count"],
  "dimensions": ["date", "hour"],
  "filters": {
    "start_date": "2026-06-01",
    "end_date": "2026-06-30"
  },
  "options": {
    "include_zero_buckets": true
  }
}
```

Response shape:

```json
{
  "schema_version": "youtube_usage.query.v3",
  "dataset": "youtube_usage",
  "person_id": "local_user",
  "duration_strategy": {
    "kind": "youtube_data_api",
    "max_duration_seconds": 5400,
    "unknown_duration_policy": "count_event_exclude_duration"
  },
  "query": {
    "metrics": ["event_count", "watch_seconds", "session_count"],
    "dimensions": ["date", "hour"],
    "filters": {
      "start_date": "2026-06-01",
      "end_date": "2026-06-30"
    }
  },
  "quality": {
    "events_counted": 1200,
    "events_with_duration": 1100,
    "events_missing_duration": 100,
    "videos_capped": 4
  },
  "rows": [
    {
      "date": "2026-06-06",
      "hour": 8,
      "event_count": 3,
      "watch_seconds": 1740,
      "session_count": 1
    }
  ]
}
```

Raw SQL is not part of the public contract. The backend may expose generated SQL
only in local debug logs or test fixtures, not in normal frontend responses.

## SQL Model

Recommended tables:

```sql
CREATE TABLE users (
  person_id TEXT PRIMARY KEY,
  created_at TEXT NOT NULL
);

CREATE TABLE watch_events (
  event_id TEXT PRIMARY KEY,
  person_id TEXT NOT NULL,
  platform TEXT NOT NULL,
  product TEXT NOT NULL,
  event_type TEXT NOT NULL,
  watched_at TEXT NOT NULL,
  video_id TEXT,
  source_schema_version TEXT NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY (person_id) REFERENCES users(person_id)
);

CREATE TABLE video_metadata (
  video_id TEXT PRIMARY KEY,
  duration_seconds INTEGER,
  duration_iso8601 TEXT,
  duration_source TEXT NOT NULL,
  availability_status TEXT NOT NULL,
  max_duration_applied INTEGER NOT NULL DEFAULT 0,
  fetched_at TEXT,
  error_code TEXT
);

CREATE TABLE enrichment_runs (
  run_id TEXT PRIMARY KEY,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  requested_video_count INTEGER NOT NULL,
  successful_video_count INTEGER NOT NULL,
  unavailable_video_count INTEGER NOT NULL,
  failed_video_count INTEGER NOT NULL
);
```

Allowed `watch_events` values:

- `platform`: `youtube`
- `product`: `youtube`
- `event_type`: `watched`

Allowed `video_metadata.availability_status` values:

- `available`
- `deleted_or_unavailable`
- `private_or_restricted`
- `api_error`
- `duration_parse_failed`

## Duration Enrichment Adaptation

The supplied watch-time script should be adapted into a backend enrichment job,
not copied as an interactive CLI.

Required changes:

- Remove interactive prompts.
- Load `.env` with `python-dotenv` and read API key from `YOUTUBE_API_KEY`.
- Read video IDs from SQL `watch_events`, not from a standalone
  `watch-history.json`.
- Deduplicate video IDs before API calls.
- Skip video IDs already present in `video_metadata` unless a refresh flag is
  provided.
- Batch IDs for YouTube Data API requests.
- Request `part=contentDetails,status`.
- Parse `contentDetails.duration` into seconds.
- Cap duration at `max_duration_seconds`, default `5400`.
- Store one `video_metadata` row per video ID.
- Track API misses as unavailable rather than silently dropping them.
- Log run-level counts in `enrichment_runs`.

Duration parsing must handle full ISO 8601 duration syntax used by YouTube, not
only `PT#H#M#S`.

Watch-time calculation must use SQL events joined to `video_metadata`.

Unknown-duration policy:

- Count the event in `event_count`.
- Exclude the event from `watch_seconds`.
- Increment `events_missing_duration`.

## Query Semantics

The frontend sends structured requests. The backend validates each field against
allowlists.

Allowed metrics:

- `event_count`
- `watch_seconds`
- `session_count`
- `events_missing_duration`

Allowed dimensions:

- `date`
- `hour`
- `weekday`
- `month`

Allowed filters:

- `person_id`
- `start_date`
- `end_date`

The backend compiles valid requests into parameterized SQL only. Invalid
metrics, dimensions, filters, or date formats return `400 Bad Request`.

SQL query results must not expose titles, URLs, channel names, raw source HTML,
or arbitrary database tables.

## Acceptance Criteria

- [x] A SQLite database is created at
      `data/processed/users/local_user/youtube_usage.v3.sqlite`.
- [x] A SQL import job loads watched YouTube events from local Takeout HTML into
      `watch_events`.
- [x] The SQL import stores internal `video_id` values for duration enrichment.
- [x] YouTube Music events are excluded from v3 usage tables.
- [x] `Viewed` events are excluded from v3 usage tables.
- [x] A duration enrichment job fetches missing video durations using
      YouTube Data API `videos.list`.
- [x] Duration enrichment loads `.env` and reads the API key from
      `YOUTUBE_API_KEY`.
- [x] Duration enrichment caches metadata by `video_id`.
- [x] Duration enrichment tracks unavailable and failed videos.
- [x] Duration enrichment caps long videos at the configured maximum duration.
- [x] `POST /api/v3/query` accepts structured query requests.
- [x] `POST /api/v3/query` rejects raw SQL.
- [x] Query requests are validated against metric, dimension, and filter
      allowlists.
- [x] Valid query requests compile to parameterized SQL.
- [x] Query responses include `duration_strategy`, `quality`, and `rows`.
- [x] Unknown-duration events count toward `event_count` but not
      `watch_seconds`.
- [x] Query responses do not expose titles, URLs, channel names, video IDs, raw
      Takeout HTML, or arbitrary SQL.
- [x] Existing v1 and v2 endpoints remain available during the v3 transition.

## Verification

Automated tests:

```sh
uv --cache-dir .uv-cache run python -m unittest discover -s backend/tests
```

Manual smoke checks:

```text
SQL import creates expected tables.
SQL import inserts only YouTube watched events.
Duration enrichment skips cached videos.
Duration enrichment records unavailable videos.
POST /api/v3/query rejects raw SQL.
POST /api/v3/query returns rows for valid metric/dimension requests.
```

## Out Of Scope

- Letting the frontend submit arbitrary SQL.
- Postgres migration.
- Multi-user ingestion.
- YouTube Music usage metrics.
- `Viewed` activity metrics.
- Content metadata analysis.
- AI augmentation.
- Serving raw source exports.
- Replacing SQL with an analytics warehouse.

## Notes

Official YouTube Data API references:

- [Videos resource](https://developers.google.com/youtube/v3/docs/videos)
- [Videos: list](https://developers.google.com/youtube/v3/docs/videos/list)

The `videos.list` endpoint returns video resources for requested IDs, and the
`contentDetails` part includes duration. The v3 backend should use that metadata
for watch-time calculation, while keeping enrichment writes separate from API
reads.
