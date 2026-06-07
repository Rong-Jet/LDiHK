# v4: YouTube Takeout S3/Postgres Backend

## Status

In Progress. Pinned on 2026-06-07.

## Summary

v4 moves the backend from local-only SQLite processing toward a hosted
multi-user ingestion backend. The frontend uploads YouTube Takeout ZIP files to
S3 and calls the backend to queue imports; backend workers read from S3, parse
supported YouTube files, store privacy-minimized usage data in hosted Postgres,
and expose a structured query API for dashboard views.

## User Story

As a frontend developer, I want backend APIs and workers that import user-uploaded
YouTube Takeout ZIPs from S3 into Postgres, so that the frontend can show usage
dashboards without owning parsing, persistence, enrichment, or SQL execution.

## Feature Set

- Hosted Postgres is the v4 data bank.
- The frontend owns ZIP upload to an existing S3 bucket.
- The backend accepts S3 object metadata through `POST /api/imports`.
- Import jobs are persisted in Postgres with `queued`, `running`, `completed`,
  and `failed` statuses.
- A worker process polls Postgres, claims queued imports, downloads ZIP files
  from S3, safely scans ZIP members, dispatches parsers, and persists parsed
  data.
- Parsed usage data is normalized into `usage_events`, `subscriptions`,
  `source_files`, and `import_warnings`.
- Supported usage event types include `watch`, `search`, `like`, `comment`,
  `live_chat`, `playlist_add`, `watch_later_add`, and
  `subscription_snapshot` where source files support them.
- Raw watched titles, raw channel titles, raw search terms, raw comments, raw
  Takeout HTML, and raw ZIP contents are not stored by default.
- Duration enrichment primitives can fetch YouTube Data API duration and
  availability metadata into `youtube_videos`.
- The frontend queries data through the constrained structured query endpoint,
  not through raw SQL.
- The existing v1-v3 local endpoints may remain available during transition, but
  they are not the v4 hosted contract.

## Public Contract

Health endpoint:

```text
GET /health
```

Import creation endpoint:

```text
POST /api/imports
```

Request:

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

Import status endpoint:

```text
GET /api/imports/{import_id}
```

Structured query endpoint:

```text
POST /api/query
```

Allowed v4 metrics:

```text
event_count
estimated_watch_seconds
api_watch_seconds
estimated_event_count
subscription_count
unique_video_count
unique_channel_count
```

Allowed v4 dimensions:

```text
date
hour
weekday
month
event_type
product
channel_id
```

Required backend commands:

```text
web:        python backend/scripts/run_web.py
worker:     python backend/scripts/run_worker.py
migrations: python backend/scripts/run_migrations.py
```

Source implementation plan:

```text
docs/backend/youtube-takeout-s3-postgres-implementation-plan.md
```

## Acceptance Criteria

- [x] Postgres migration defines the v4 MVP schema.
- [x] `POST /api/imports` queues an import job.
- [x] `GET /api/imports/{import_id}` returns import status and counters.
- [x] Import worker claims queued jobs from Postgres.
- [x] Import worker downloads ZIP files through an S3 client abstraction.
- [x] ZIP path traversal entries are rejected.
- [x] Watch history files are parsed into `watch` usage events.
- [x] Subscription files are parsed into `subscriptions`.
- [x] Likes, playlist/watch-later adds, search events, comments, and live chats
      have parser coverage where source shapes are straightforward.
- [x] Search terms and private text fields are hashed before persistence.
- [x] Import warnings are stored as count/sample-hash metadata rather than raw
      source content.
- [x] Structured query API rejects raw SQL and unknown metrics, dimensions, and
      filters.
- [x] Estimated watch seconds can fall back from API duration to user average to
      a global default.
- [ ] Duration enrichment is queued and processed asynchronously through hosted
      Postgres worker flow.
- [ ] The hosted web process uses a production WSGI server.
- [ ] A real Supabase/Postgres, S3, Render web, and Render worker smoke test has
      been completed.

## Verification

Current local verification:

```sh
uv run python -m unittest discover backend/tests
```

On 2026-06-06 this passed 104 tests with 1 skipped optional live Postgres
integration test.

Hosted verification remains a v5 requirement.

## Out Of Scope

- Frontend upload UI.
- Frontend dashboard rendering.
- Frontend-authored SQL.
- Creator-side YouTube metrics such as uploads, revenue, studio analytics, or
  channel-owner reports.
- Redis, Celery, Kubernetes, or Terraform.
- Feeding `onfabric/context-use` directly from raw Takeout rows.

## Notes

v4 is a strong backend MVP foundation but is not yet a deployed production-demo
backend. v5 owns hosted operations, production process commands, duration
enrichment wiring, CORS/auth decisions, top-video query support, and real
provider smoke tests.
