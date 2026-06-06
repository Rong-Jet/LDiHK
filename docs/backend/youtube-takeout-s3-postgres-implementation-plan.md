# YouTube Takeout S3/Postgres Implementation Plan

## Status

Planning handoff.

This document is intended for another implementation agent. It describes the
MVP architecture for a hosted YouTube Takeout ingestion pipeline where users
upload ZIP exports from the frontend, the ZIPs are stored in AWS S3, and the
backend imports usage analytics into SQL.

## Goal

Build a robust, quick, and easily hostable MVP that extracts YouTube usage data
from user-uploaded YouTube Takeout ZIP files and stores normalized analytics
data in a SQL database.

The pipeline should support more than watch-time metrics. It should import
usage signals such as watch history, search history, likes, comments, live chat
activity, playlist/watch-later activity where available, and subscriptions.
Creator-side data such as uploads, revenue, channel analytics, and creator
studio metrics are out of scope.

## Key Product Decisions

- Users upload ZIP files from the frontend.
- Uploaded ZIP files are stored in an existing AWS S3 bucket.
- The ingestion worker reads ZIPs from S3.
- The SQL database should be hosted Postgres for the MVP.
- The frontend-facing API should expose flexible structured queries over the
  stored tables.
- The frontend must not submit raw SQL.
- YouTube Data API enrichment is allowed.
- Duration enrichment should run asynchronously after import.
- Missing video durations should fall back to the user's average enriched video
  duration.
- The existing v3 SQLite implementation in this repo is experimental and should
  be treated as a reference, not as the final architecture.
- `onfabric/context-use` should remain separate from the analytics schema. If it
  is integrated later, feed it from normalized usage data rather than forcing
  analytics rows into its memory schema.

## Repository Research Summary

### luciopaiva/youtube-takeout-analyzer

Best architectural reference for SQL-friendly YouTube analytics.

Useful ideas:

- Event-oriented watch-history parsing.
- Small models for views, videos, and channels.
- Source hashing/cache idea.
- Analytics that translate directly to SQL: top channels, top videos, monthly
  counts, channel progression, cumulative views.

Do not copy directly:

- Node script structure.
- Local-only workflow.
- Non-SQL cache/output handling.

### zxkeyy/CalcYTWatchTime

Best reference for the duration enrichment primitive.

Useful ideas:

- Batch video IDs.
- Call YouTube Data API `videos.list`.
- Request `part=contentDetails,status`.
- Parse `contentDetails.duration`.
- Cap long videos.
- Track deleted/private/unavailable videos.

Do not copy directly:

- Interactive CLI flow.
- Aggregate-only output.
- Synchronous processing.
- Fragile URL parsing.

### purarue/google_takeout_parser

Best reference for parser dispatch and format coverage.

Useful ideas:

- Ordered file-path dispatch.
- Locale-aware parsing concept.
- Explicit parser error policy.
- Support for both HTML and JSON history where available.
- CSV parsing patterns for comments/live chats.

Limitations for this MVP:

- Works on unpacked Takeout directories, not S3 ZIP ingestion.
- Does not persist SQL rows.
- Ignores subscriptions.
- Cache/idempotency model is not suitable for uploaded S3 objects.

### onfabric/context-use

Useful for semantic personal-memory workflows, not as the primary analytics
backend.

For this project:

- Keep analytics tables separate.
- Optionally emit normalized usage events into `context-use` later.
- Do not use the `context-use` SQLite/vector schema for count, duration, or
  dashboard queries.

## Target Architecture

```text
Frontend
  -> uploads YouTube Takeout ZIP to AWS S3
  -> calls POST /api/imports with S3 object info

API service
  -> creates import job in Postgres
  -> exposes import status
  -> exposes structured query endpoint

Worker service
  -> polls Postgres import jobs
  -> downloads ZIP from S3
  -> safely extracts or streams relevant files
  -> parses YouTube Takeout files
  -> upserts normalized SQL rows
  -> queues enrichment jobs

Enrichment worker
  -> finds missing video IDs
  -> batches YouTube Data API requests
  -> caches video duration and availability metadata

Postgres
  -> stores import provenance
  -> stores normalized usage events
  -> stores subscriptions
  -> stores video/channel metadata
  -> powers frontend query API
```

Use one Docker image with two commands:

```text
web     -> API server
worker  -> import/enrichment polling loop
```

For the hackathon MVP, avoid Redis/Celery. Use Postgres-backed job tables and a
simple polling loop to reduce setup and deployment risk.

## Deployment Target

Recommended MVP hosting:

- API and worker: Render, Fly, or Railway.
- Database: Neon Postgres or Supabase Postgres.
- ZIP storage: existing AWS S3 bucket.
- Secrets:
  - `DATABASE_URL`
  - `AWS_ACCESS_KEY_ID`
  - `AWS_SECRET_ACCESS_KEY`
  - `AWS_REGION`
  - `S3_BUCKET`
  - `YOUTUBE_API_KEY`

This should support a small demo crowd of roughly 20 users as long as imports
are background jobs and frontend polling is used for progress.

## Suggested Code Layout

Keep the codebase small. Suggested modules:

```text
backend/
  app.py
  db.py
  query_api.py
  ingestion/
    __init__.py
    s3.py
    zip_safety.py
    worker.py
    dispatch.py
    models.py
    parsers/
      watch_history.py
      subscriptions.py
      likes.py
      comments.py
      search_history.py
  enrichment/
    youtube_api.py
    durations.py
  migrations/
    001_youtube_imports.sql
backend/scripts/
  run_worker.py
  run_migrations.py
```

If the existing Flask app stays, preserve it for the API. If FastAPI is easier
for request validation and OpenAPI, switch only if the implementation agent can
do so without slowing down the MVP.

## MVP SQL Schema

Use UUID primary keys where practical. Plain SQL migrations are sufficient for
the MVP.

```sql
CREATE TABLE users (
  id UUID PRIMARY KEY,
  external_id TEXT UNIQUE NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE imports (
  id UUID PRIMARY KEY,
  user_id UUID NOT NULL REFERENCES users(id),
  s3_bucket TEXT NOT NULL,
  s3_key TEXT NOT NULL,
  s3_etag TEXT,
  status TEXT NOT NULL,
  started_at TIMESTAMPTZ,
  finished_at TIMESTAMPTZ,
  records_seen INTEGER NOT NULL DEFAULT 0,
  records_imported INTEGER NOT NULL DEFAULT 0,
  warnings_count INTEGER NOT NULL DEFAULT 0,
  error_message TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE source_files (
  id UUID PRIMARY KEY,
  import_id UUID NOT NULL REFERENCES imports(id),
  path TEXT NOT NULL,
  sha256 TEXT NOT NULL,
  parser_name TEXT,
  status TEXT NOT NULL,
  records_seen INTEGER NOT NULL DEFAULT 0,
  records_imported INTEGER NOT NULL DEFAULT 0,
  warnings_count INTEGER NOT NULL DEFAULT 0,
  UNIQUE(import_id, path)
);

CREATE TABLE usage_events (
  id UUID PRIMARY KEY,
  user_id UUID NOT NULL REFERENCES users(id),
  import_id UUID NOT NULL REFERENCES imports(id),
  source_file_id UUID REFERENCES source_files(id),
  platform TEXT NOT NULL,
  product TEXT NOT NULL,
  event_type TEXT NOT NULL,
  occurred_at TIMESTAMPTZ,
  video_id TEXT,
  channel_id TEXT,
  title_hash TEXT,
  search_query_hash TEXT,
  raw_status TEXT,
  event_fingerprint TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(user_id, event_fingerprint)
);

CREATE TABLE subscriptions (
  id UUID PRIMARY KEY,
  user_id UUID NOT NULL REFERENCES users(id),
  import_id UUID NOT NULL REFERENCES imports(id),
  channel_id TEXT NOT NULL,
  channel_url TEXT,
  channel_title_hash TEXT,
  source_path TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(user_id, channel_id)
);

CREATE TABLE youtube_videos (
  video_id TEXT PRIMARY KEY,
  channel_id TEXT,
  duration_seconds INTEGER,
  duration_source TEXT,
  availability_status TEXT NOT NULL,
  max_duration_applied BOOLEAN NOT NULL DEFAULT false,
  fetched_at TIMESTAMPTZ,
  attempt_count INTEGER NOT NULL DEFAULT 0,
  last_error TEXT
);

CREATE TABLE youtube_channels (
  channel_id TEXT PRIMARY KEY,
  title_hash TEXT,
  fetched_at TIMESTAMPTZ,
  attempt_count INTEGER NOT NULL DEFAULT 0,
  last_error TEXT
);

CREATE TABLE enrichment_jobs (
  id UUID PRIMARY KEY,
  job_type TEXT NOT NULL,
  status TEXT NOT NULL,
  payload_json JSONB NOT NULL,
  attempts INTEGER NOT NULL DEFAULT 0,
  run_after TIMESTAMPTZ NOT NULL DEFAULT now(),
  started_at TIMESTAMPTZ,
  finished_at TIMESTAMPTZ,
  error_message TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE import_warnings (
  id UUID PRIMARY KEY,
  import_id UUID NOT NULL REFERENCES imports(id),
  source_file_id UUID REFERENCES source_files(id),
  code TEXT NOT NULL,
  count INTEGER NOT NULL,
  sample_hash TEXT
);
```

Recommended indexes:

```sql
CREATE INDEX idx_usage_events_user_time
  ON usage_events(user_id, occurred_at);

CREATE INDEX idx_usage_events_user_type_time
  ON usage_events(user_id, event_type, occurred_at);

CREATE INDEX idx_usage_events_video_id
  ON usage_events(video_id);

CREATE INDEX idx_usage_events_channel_id
  ON usage_events(channel_id);

CREATE INDEX idx_imports_status
  ON imports(status, created_at);

CREATE INDEX idx_enrichment_jobs_status
  ON enrichment_jobs(status, run_after);
```

## Event Types

Normalize usage into `usage_events.event_type`.

Initial allowlist:

```text
watch
search
like
comment
live_chat
playlist_add
watch_later_add
subscription_snapshot
```

Creator metrics are out of scope:

```text
upload
revenue
creator_analytics
studio_metric
```

## Parser Scope

Implement in this order.

### 1. Watch History

Input files:

```text
YouTube and YouTube Music/history/watch-history.html
YouTube and YouTube Music/history/watch-history.json
```

Output:

- `usage_events.event_type = 'watch'`
- `product = 'youtube'` or `youtube_music` where distinguishable
- `occurred_at`
- `video_id`
- `channel_id` when available
- `title_hash`
- `raw_status` for deleted/private/malformed rows

Use robust URL parsing for video IDs. Do not use naive string splitting.

### 2. Subscriptions

Input files:

```text
YouTube and YouTube Music/subscriptions/subscriptions.csv
YouTube and YouTube Music/subscriptions/subscriptions.json
```

Output:

- `subscriptions`
- optional `usage_events.event_type = 'subscription_snapshot'`

Expected CSV columns may include:

```text
Channel Id
Channel Url
Channel Title
```

Treat subscriptions primarily as current/snapshot state unless the Takeout file
contains timestamps.

### 3. Likes

Input files:

```text
YouTube and YouTube Music/playlists/likes.json
```

Output:

- `usage_events.event_type = 'like'`
- `video_id` where available
- `occurred_at` where available

### 4. Search History

Input files vary. Prefer JSON activity files when available.

Output:

- `usage_events.event_type = 'search'`
- `search_query_hash`
- `occurred_at`

Search terms are sensitive. Store hashes by default.

### 5. Comments And Live Chats

Input files may include:

```text
YouTube and YouTube Music/my-comments/*.html
YouTube and YouTube Music/my-live-chat-messages/*.html
Youtube/comments/comments.csv
Youtube/live chats/live chats.csv
```

Output:

- `usage_events.event_type = 'comment'` or `live_chat`
- `video_id` where available
- `occurred_at`
- no raw comment text by default

## Import Worker Flow

1. Select one queued import using row locking.
2. Mark it `running`.
3. Download the S3 object to `/tmp/import-{id}.zip`.
4. Validate ZIP size if available.
5. Iterate ZIP entries.
6. Reject path traversal entries.
7. Match entries with parser dispatch rules.
8. Hash each relevant source file.
9. Insert or update `source_files`.
10. Parse records.
11. Upsert `usage_events` and `subscriptions`.
12. Store count-only warnings.
13. Queue duration enrichment for distinct missing `video_id` values.
14. Mark import `completed`.
15. On failure, mark import `failed` with an error message.

Use transaction boundaries per source file or per batch, not one huge
transaction for the whole ZIP.

## Idempotency

Re-uploading the same ZIP must not duplicate records.

Use:

- `imports.s3_etag` for object-level provenance.
- `source_files.sha256` for file-level provenance.
- `usage_events.event_fingerprint` for event-level dedupe.
- Native stable IDs where available, such as comment IDs.

Default fingerprint:

```text
sha256(user_id | event_type | occurred_at | video_id | channel_id | source_path | sequence)
```

If a parser has a better native key, use it.

## Privacy Defaults

Default to privacy-minimized storage.

Store:

- video IDs
- channel IDs
- hashed titles
- hashed channel titles
- hashed search terms
- event timestamps
- event types

Do not store by default:

- raw ZIP contents
- raw watched titles
- raw search terms
- raw comment text
- raw Takeout HTML

If a demo needs top-channel names, make raw names configurable and clearly mark
that mode as less private.

## Duration Enrichment

Duration enrichment should not block import completion.

Worker algorithm:

1. Select distinct missing video IDs from watch events.
2. Batch up to 50 IDs per request.
3. Call YouTube Data API `videos.list`.
4. Request `part=contentDetails,status`.
5. Parse `contentDetails.duration` as ISO 8601.
6. Support day durations such as `P1DT2H`.
7. Cap long durations at `5400` seconds by default.
8. Upsert one `youtube_videos` row per video ID.
9. Mark IDs not returned as `deleted_or_unavailable`.
10. Track errors and attempts.
11. Retry network/API errors with backoff.

Duration source values:

```text
youtube_data_api
user_average_estimate
global_default_estimate
```

Availability statuses:

```text
available
deleted_or_unavailable
private_or_restricted
api_error
duration_parse_failed
```

## Estimated Duration Rule

For watch-time queries:

```sql
COALESCE(
  youtube_videos.duration_seconds,
  user_duration_stats.avg_enriched_duration_seconds,
  600
)
```

The user average should be event-weighted:

```sql
AVG(youtube_videos.duration_seconds)
```

computed over the user's watch events that have available enriched durations.
This means repeated watches influence the fallback, which better matches usage
behavior than averaging distinct videos.

Expose quality counts:

- `events_counted`
- `events_with_api_duration`
- `events_with_user_average_estimate`
- `events_with_global_default_estimate`
- `videos_unavailable`
- `videos_capped`

## Query API

Expose a constrained structured endpoint:

```text
POST /api/query
```

Request:

```json
{
  "dataset": "youtube_usage",
  "user_id": "demo_user",
  "metrics": ["event_count", "estimated_watch_seconds"],
  "dimensions": ["date", "event_type"],
  "filters": {
    "start_date": "2025-01-01",
    "end_date": "2026-06-06"
  },
  "options": {
    "include_zero_buckets": true,
    "limit": 500
  }
}
```

Allowed metrics:

```text
event_count
estimated_watch_seconds
api_watch_seconds
estimated_event_count
subscription_count
unique_video_count
unique_channel_count
```

Allowed dimensions:

```text
date
hour
weekday
month
event_type
product
channel_id
```

Only allow `channel_id` if the frontend/product privacy mode permits it.

Allowed filters:

```text
user_id
start_date
end_date
event_type
product
```

Validation requirements:

- Reject raw SQL.
- Reject unknown metrics.
- Reject unknown dimensions.
- Reject unknown filters.
- Parameterize all compiled SQL.
- Enforce a maximum result limit.

## Import API

Minimum endpoints:

```text
POST /api/imports
GET /api/imports/{import_id}
POST /api/query
GET /health
```

`POST /api/imports` request:

```json
{
  "user_id": "demo_user",
  "s3_bucket": "existing-bucket",
  "s3_key": "uploads/demo_user/takeout.zip",
  "s3_etag": "optional-etag"
}
```

Response:

```json
{
  "import_id": "uuid",
  "status": "queued"
}
```

Status values:

```text
queued
running
completed
failed
```

Optional future values:

```text
extracting
parsing
importing
enriching
```

For MVP, keep status simple and add detailed counts to the import row.

## Implementation Phases

### Phase 1: Postgres Foundation

- Add Postgres dependency.
- Add `DATABASE_URL` config.
- Add migration script.
- Create tables and indexes.
- Add a minimal DB helper.
- Add tests using a temporary Postgres if available, or split pure SQL/query
  builder tests from integration tests.

### Phase 2: Import Job API

- Add `POST /api/imports`.
- Add `GET /api/imports/{id}`.
- Insert/import job rows.
- Validate S3 key ownership/path shape.
- Keep auth simple for demo if auth is not already in place.

### Phase 3: S3 And ZIP Worker

- Add S3 download helper.
- Add safe ZIP traversal.
- Add worker polling loop.
- Mark imports `running`, `completed`, and `failed`.
- Record import counts.

### Phase 4: Parser Dispatch

- Add dispatch table keyed by ZIP member path regex.
- Add parser result dataclasses.
- Add source file hashing.
- Add warning aggregation.

### Phase 5: Watch History Parser

- Support `watch-history.html`.
- Support `watch-history.json` if file shape is available.
- Extract timestamps, video IDs, channel IDs when available, product, and status.
- Upsert watch events.
- Add tests for deleted/private/malformed rows.

### Phase 6: Subscriptions Parser

- Support `subscriptions.csv`.
- Support JSON if straightforward.
- Upsert `subscriptions`.
- Add tests for expected CSV columns.

### Phase 7: Additional Usage Parsers

Add in this order:

1. Likes.
2. Search history.
3. Comments.
4. Live chats.
5. Watch later or playlist add events.

Each parser should be independently testable.

### Phase 8: Duration Enrichment

- Add YouTube Data API client.
- Add ISO 8601 duration parser.
- Add enrichment job loop.
- Add video cache upserts.
- Add unavailable/error tracking.
- Add user-average fallback logic in query layer.

### Phase 9: Structured Query API

- Port the current v3 query API idea from SQLite to Postgres.
- Compile allowlisted metrics/dimensions to parameterized SQL.
- Add quality metadata.
- Add zero-bucket support for date/hour queries if frontend needs heatmaps.

### Phase 10: Deployment

- Add Dockerfile.
- Add web and worker commands.
- Add deployment env var docs.
- Add a smoke-test command.
- Add a small demo import fixture or local S3 mock path only if it does not
  slow down the hosted path.

## Test Plan

Required tests:

- ZIP path traversal is rejected.
- Re-uploading the same source does not duplicate `usage_events`.
- Missing/malformed records create warnings, not full import failure.
- `subscriptions.csv` imports channel IDs.
- Watch history parser extracts video ID, timestamp, and event type.
- Query API rejects raw SQL.
- Query API rejects unknown metrics/dimensions/filters.
- Enrichment batches 50 IDs per YouTube API call.
- Enrichment marks requested-but-not-returned IDs unavailable.
- ISO 8601 duration parser handles `PT15M33S`, `PT1H2M3S`, and `P1DT2H`.
- Estimated duration falls back to event-weighted user average.
- If no user average exists, estimated duration falls back to `600`.

## Acceptance Criteria

- Frontend can upload a ZIP to S3 and create an import job.
- Worker imports at least watch history and subscriptions from the ZIP.
- SQL stores multiple YouTube usage metrics, not only watch time.
- Duration enrichment runs asynchronously.
- Query API can return:
  - daily watch event count
  - estimated watch seconds
  - hourly heatmap data
  - top channels by event count, if channel IDs are available
  - subscription count
  - event counts by type
- The demo remains useful before enrichment completes because average-duration
  estimates fill missing durations.
- Raw SQL is not accepted from the frontend.
- Raw ZIP contents are not persisted after processing.
- Around 20 demo users can interact without shared-state conflicts.

## Known Risks

- YouTube Takeout file names and formats vary over time.
- HTML history parsing is slower and more brittle than JSON.
- Subscriptions exports may be incomplete for some users.
- Deleted/private videos are common in historical watch data.
- YouTube API quota can delay enrichment.
- Long livestreams can skew duration totals unless capped.
- Search terms and comments are highly sensitive; hash or drop raw content by
  default.

## Recommended MVP Cut Line

If time is tight, implement only:

1. S3 import job creation.
2. Postgres schema.
3. Worker download and safe ZIP traversal.
4. Watch history parser.
5. Subscriptions parser.
6. Duration enrichment for watch events.
7. Structured query API for date/hour/event-type metrics.

Defer comments, live chats, playlists, materialized views, and context-use
integration until after the core demo works.
