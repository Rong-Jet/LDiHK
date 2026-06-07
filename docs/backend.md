# Backend Business Requirements

This is the living business contract for what the backend delivers. Historical
implementation details belong in `docs/backend/versions/`.

## Version Map

- v1: local YouTube Takeout processing and full JSON API.
- v2: frontend-ready local temporal chart API.
- v3: local SQLite duration enrichment and structured query API.
- v4: S3/Postgres YouTube Takeout ingestion backend.
- v5: hosted backend workers, Supabase database, Render deployment, and hosted
  smoke testing.

Version documents:

```text
docs/backend/versions/v1-youtube-usage-pipeline-api.md
docs/backend/versions/v2-youtube-temporal-api.md
docs/backend/versions/v3-sql-duration-query-api.md
docs/backend/versions/v4-youtube-takeout-s3-postgres-backend.md
docs/backend/versions/v5-hosted-backend-workers-and-deployment.md
```

Frontend handoff contract:

```text
docs/backend/frontend-api-spec.md
```

## Current Delivery

- The backend exposes a health endpoint.
- The backend accepts frontend-created S3 upload references through
  `POST /api/imports`.
- User-scoped requests derive public `ldihk_id` from
  `Authorization: Bearer <LDiHKID>` and map it internally to the Postgres
  `user_id` schema.
- The backend creates queued import jobs in Postgres.
- The backend exposes import status through `GET /api/imports/{import_id}`.
- The import worker polls Postgres, claims queued imports, downloads ZIP files
  from S3, safely scans ZIP members, dispatches supported YouTube parsers, and
  writes normalized records to Postgres.
- The backend stores normalized usage events for watch history, search history,
  likes, playlist/watch-later adds, comments, live chats, and subscriptions
  where Takeout source files are available and parser support exists.
- The backend stores privacy-minimized fields by default: IDs, timestamps,
  event types, hashed titles, hashed channel titles, hashed search terms, and
  count/sample-hash warnings.
- The backend does not store raw ZIP contents, raw watched titles, raw search
  terms, raw comments, or raw Takeout HTML by default.
- The backend exposes `POST /api/query` for structured, allowlisted,
  parameterized dashboard queries across real YouTube imports and seeded
  synthetic multi-platform population data.
- The frontend must not submit raw SQL.
- Duration enrichment primitives exist for YouTube Data API duration and
  availability lookup, but hosted asynchronous enrichment wiring is a v5
  completion item.
- The existing v1-v3 local JSON/SQLite endpoints may remain available during
  transition, but the backend direction is v4/v5 hosted Postgres.

## Backend-Owned v5 Outcomes

- Supabase Postgres is provisioned, migrated, and used by web and worker
  services.
- Render hosts the backend Docker image as separate web, import worker, and
  enrichment worker services.
- The web service runs with a production WSGI server.
- Import workers enforce the configured S3 bucket and ZIP size limits.
- Duration enrichment runs asynchronously after imports and improves query
  quality without blocking import completion.
- CORS and demo-auth boundaries are explicit so the deployed frontend can call
  backend APIs.
- The query endpoint can power:
  - daily watch counts
  - estimated watch seconds
  - estimated usage seconds across platforms
  - hourly heatmap data
  - event counts by type
  - platform, profile, and synthetic-population comparisons
  - subscription count
  - top channels by event count
  - top videos by event count when identifier dimensions are enabled
- A hosted smoke test proves Render + Supabase + S3 + YouTube API configuration.

## Required API Outcomes

Health:

```text
GET /health
```

Import creation:

```text
POST /api/imports
```

Request:

```json
{
  "s3_bucket": "existing-bucket",
  "s3_key": "uploads/demo-user-123/takeout.zip",
  "s3_etag": "optional-etag",
  "age": 23,
  "sex": "male"
}
```

Response:

```json
{
  "import_id": "uuid",
  "ldihk_id": "demo-user-123",
  "status": "queued"
}
```

Import status:

```text
GET /api/imports/{import_id}
```

Structured query:

```text
POST /api/query
```

Request:

```json
{
  "dataset": "usage_analytics",
  "metrics": ["event_count", "estimated_usage_seconds"],
  "dimensions": ["date", "hour", "platform"],
  "filters": {
    "start_date": "2026-06-01",
    "end_date": "2026-06-07",
    "platform": ["youtube", "tiktok", "instagram", "spotify", "linkedin"]
  },
  "options": {
    "include_zero_buckets": true,
    "limit": 500
  }
}
```

Response includes:

- `schema_version`
- `dataset`
- `ldihk_id`
- `duration_strategy`
- `query`
- `quality`
- `rows`

## Privacy And Safety Requirements

- Do not expose raw source ZIPs through API responses.
- Do not store raw ZIP contents after processing.
- Do not store raw watched titles, raw search terms, or raw comment text by
  default.
- Hash private text fields before persistence.
- Keep frontend query requests structured and allowlisted.
- Parameterize compiled SQL.
- Enforce a maximum query result limit.
- Treat YouTube channel IDs and video IDs as user data. Expose them only when
  the product enables identifier dimensions.
- Keep creator-side YouTube metrics out of scope.

## Deployment Requirements

- Use one Docker image for web and workers.
- Use Supabase Postgres or equivalent hosted Postgres.
- Use an existing S3 bucket for frontend-uploaded Takeout ZIP files.
- Use Render Web Service for the API.
- Use Render Background Workers for import and enrichment loops.
- Run migrations before long-lived services handle traffic.
- Keep backend S3 credentials read-only for uploaded ZIP objects.
- Keep YouTube Data API calls in the enrichment worker path, not in API reads.
- Pass a real hosted smoke test before declaring the backend demo-ready.

## Out Of Scope

- Frontend upload UI.
- Frontend dashboard implementation.
- Browser-to-S3 upload implementation.
- Frontend-submitted raw SQL.
- Creator-side YouTube metrics such as uploads, revenue, channel analytics, or
  studio metrics.
- Instagram, TikTok, and Douyin support.
- Redis, Celery, Kubernetes, Terraform, or a separate analytics warehouse for
  the hackathon MVP.
- AI augmentation.
