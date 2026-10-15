# LDiHK Authoritative API Contract

## Status

Authoritative API shape for the current LDiHK MVP.

This is the single source of truth for request and response shapes shared by the
frontend, backend API, import worker, and deployment smoke tests. If endpoint
shape changes, update this document in the same change.

Non-authoritative implementation plans, historical version notes, and UI-specific
requirements should link here instead of restating endpoint schemas.

Frontend runtime convention:

- Browser calls to backend-owned endpoints should use `PUBLIC_API_URL` as the
  backend origin when configured.
- Astro-only helper routes such as upload URL generation stay same-origin.
- When a backend origin is configured, the frontend upload helper must have
  upload storage credentials through `CUSTOM_AWS_ACCESS_KEY_ID`,
  `CUSTOM_AWS_SECRET_ACCESS_KEY`, the same `S3_BUCKET` value as the backend,
  and either `S3_ENDPOINT_URL` (Cloudflare R2 or another S3-compatible store)
  or `CUSTOM_AWS_REGION` (AWS S3).
- The free-tier backend sleeps when idle. The frontend pings `GET /health` on
  load, shows a "waking the server" state, and gates data requests until it
  answers. Browser requests use a 90-second timeout and retry 5xx/network
  errors.
- `PUBLIC_MOCK_API=true`, `1`, `yes`, or `on` forces local mock API mode and
  ignores backend URLs.
- `PUBLIC_MOCK_API=false` disables silent fallback to local mock routes. Local
  helper routes must return clear errors when live configuration is missing.
- Leaving `PUBLIC_MOCK_API` unset allows legacy local-development implicit mock
  fallback when neither backend nor S3 upload config is present.
- For local Astro development, the frontend origin is usually
  `http://localhost:4321`; include that origin in backend CORS config outside
  development defaults when deploying a non-local frontend.

Endpoint ownership:

- Backend-owned: `GET /health`, `GET /api/me`, `POST /api/imports`,
  `GET /api/imports/{import_id}`, `POST /api/query`, `POST /api/population`.
  The browser calls all of them directly on `PUBLIC_API_URL`.
- Frontend/Astro helper-owned: `GET /api/uploader-info`,
  `POST /api/upload-url`.
- Mock-only frontend routes such as `PUT /api/mock-s3-upload`, local
  `GET /api/me`, `POST /api/query`, `POST /api/population` and
  `POST /api/imports` are development shims, not production backend contract.

## Identity

All user-scoped requests include:

```text
Authorization: Bearer <LDiHKID>
```

`LDiHKID` is the public-facing pseudo-account identifier for the demo. The
backend derives identity from this header and maps it internally to the Postgres
`users` / `user_id` schema.

Do not send `ldihk_id`, `user_id`, or `person_id` in request bodies.

Format: `^[A-Za-z0-9][A-Za-z0-9._-]{2,127}$`; anything else is rejected with
`401 invalid_authorization`. The frontend generates IDs with
`crypto.getRandomValues`: a friendly prefix plus a 12-character base32 suffix
(60 random bits), e.g. `ldihk-cosmic-pegasus-k3j9x2m4q7ab`. The ID is the only
credential, so it must not be guessable.

Example:

```text
Authorization: Bearer ldihk-cosmic-pegasus-k3j9x2m4q7ab
```

Backend behavior:

- `POST /api/imports` finds or creates an internal user for that
  `external_id`. Logging in does not create users: the frontend validates an
  entered ID with `GET /api/me`, which answers `404 unknown_ldihk_id` for IDs
  that never uploaded anything.
- On `POST /api/imports`, optional `age` and `sex` request fields are accepted
  as profile attributes for that user creation path.
- Stores the internal UUID as `user_id` in Postgres.
- Returns `ldihk_id` in public responses where useful.

This is demo identity, not production authentication.

## Platform Scope

Supported user-uploaded export ZIPs are YouTube Takeout (in English, German,
Spanish, French, Italian, Portuguese and Dutch), TikTok and Instagram data
exports (HTML or JSON). The query API also supports seeded synthetic
population rows for these normalized platforms:

Supported datasets:

```text
usage_analytics
youtube_usage
tiktok_usage
instagram_usage
```

Seeded synthetic platforms:

```text
youtube
tiktok
instagram
spotify
linkedin
```

## Upload And Import Flow

1. User selects a supported export ZIP in the frontend: YouTube Takeout or
   TikTok data export.
2. Frontend uploads the ZIP to object storage (Cloudflare R2 or S3) under
   `uploads/<LDiHKID>/<filename>.zip` with a presigned PUT URL. Archives over
   20 MB are first slimmed in the browser: videos, photos and other media are
   removed so only history files are uploaded (at most 200 MB).
3. Frontend calls `POST /api/imports` with S3 object metadata.
4. Backend creates a queued import in Postgres.
5. The import worker (a thread inside the backend web process on free
   hosting) picks up the import, downloads the ZIP, parses supported YouTube,
   TikTok and Instagram files, and writes normalized rows. An archive with no
   supported files fails with `error_message` starting `no_supported_files`.
6. Frontend polls `GET /api/imports/{import_id}`.
7. Frontend calls `POST /api/query` for dashboard data.

There is no S3 event/Lambda trigger in the v5 backend flow.
The backend rejects import requests where `s3_key` is not under the bearer
identity prefix: `uploads/<LDiHKID>/`.

## Endpoints

### Health

```text
GET /health
```

Auth is not required.

Response:

```json
{
  "status": "ok"
}
```

### Get Current User

```text
GET /api/me?timezone=<IANA name>
```

Headers:

```text
Authorization: Bearer <LDiHKID>
```

Used for login validation, per-platform date bounds and resuming an import.
`timezone` (default `UTC`) sets the calendar for `min_date` / `max_date`.

Response:

```json
{
  "ldihk_id": "ldihk-cosmic-pegasus-k3j9x2m4q7ab",
  "exists": true,
  "timezone": "Europe/Berlin",
  "datasets": {
    "youtube": {
      "event_count": 52310,
      "watch_event_count": 48800,
      "first_event_at": "2019-01-02T10:00:00+00:00",
      "last_event_at": "2026-10-01T20:00:00+00:00",
      "min_date": "2019-01-02",
      "max_date": "2026-10-01"
    }
  },
  "latest_import": null
}
```

`latest_import` has the shape of `GET /api/imports/{import_id}` or is `null`.
A user whose first import is still queued or running has `datasets: {}` and a
`latest_import`.

Errors: `missing_authorization`, `invalid_authorization`,
`invalid_timezone` (400), `unknown_ldihk_id` (404), `database_unavailable`
(503), `rate_limited` (429, failed lookups are limited).

### Delete Current User

```text
DELETE /api/me
```

Headers: `Authorization: Bearer <LDiHKID>`, `Content-Type: application/json`.

Request body (must repeat the ID):

```json
{ "confirm": "ldihk-cosmic-pegasus-k3j9x2m4q7ab" }
```

Permanently deletes the user's usage events, subscriptions, imports, import
warnings, enrichment jobs and the user row, then removes objects under
`uploads/<LDiHKID>/` from storage (best effort; `uploads_deleted` is `null`
when that was not possible). The shared YouTube video cache is kept.

Response:

```json
{ "deleted": true, "events_deleted": 52310, "imports_deleted": 2, "subscriptions_deleted": 140, "uploads_deleted": 1 }
```

Errors: `confirmation_mismatch` (400), `unknown_ldihk_id` (404),
`rate_limited` (429), `database_unavailable` (503).

### Get Uploader Info

```text
GET /api/uploader-info
```

Owned by the frontend Astro server. Auth is not required. The browser uses this
to display upload capability state before a ZIP is selected.

Response:

```json
{
  "isMock": false,
  "uploadConfigured": true
}
```

Fields:

- `isMock`: `true` only when upload will use the local mock upload route.
- `uploadConfigured`: `true` when upload can proceed. In live mode this means
  the frontend server has S3 credentials and bucket configuration. In explicit
  mock mode this means mock upload is intentionally enabled.

When `PUBLIC_MOCK_API=false`, missing S3 upload config must not be reported as
mock-ready.

### Create Upload URL

```text
POST /api/upload-url
```

Owned by the frontend Astro server. This route creates the browser-to-storage
upload configuration (AWS S3, or Cloudflare R2 via `S3_ENDPOINT_URL`). It must
use the same bucket as the backend import API. Presigned URLs carry no
checksum parameters. The file name must end in `.zip` (any case); the key
always ends in lowercase `.zip`.

Headers:

```text
Authorization: Bearer <LDiHKID>
Content-Type: application/json
```

Request body:

```json
{
  "filename": "takeout.zip",
  "contentType": "application/zip",
  "size": 6264
}
```

`size` (bytes, required) is signed into the URL as `Content-Length`: the
upload must be exactly that size, and at most `MAX_IMPORT_ZIP_BYTES`
(200 MB). Signing is rate-limited per ID and per client address.

Live response:

```json
{
  "url": "https://bucket.s3.region.amazonaws.com/uploads/demo-user-123/takeout.zip?...",
  "method": "PUT",
  "headers": {
    "Content-Type": "application/zip"
  },
  "s3Bucket": "existing-bucket",
  "s3Key": "uploads/demo-user-123/takeout.zip",
  "isMock": false
}
```

Mock response, only when mock mode is enabled or implicit mock fallback is
allowed:

```json
{
  "url": "http://localhost:4321/api/mock-s3-upload",
  "method": "PUT",
  "headers": {
    "Content-Type": "application/zip",
    "x-amz-meta-filename": "takeout.zip",
    "x-amz-meta-ldihkid": "demo-user-123",
    "x-amz-s3-key": "uploads/demo-user-123/takeout.zip"
  },
  "s3Bucket": "local-mock-bucket",
  "s3Key": "uploads/demo-user-123/takeout.zip",
  "isMock": true
}
```

Errors:

- `missing_authorization`
- `invalid_authorization`
- `invalid_filename` (400, not a `.zip`)
- `invalid_size` (400), `file_too_large` (413)
- `rate_limited` (429, with `Retry-After`)
- `upload_not_configured`
- `s3_signature_failure`

When `PUBLIC_MOCK_API=false`, this endpoint must return `503` with
`upload_not_configured` instead of falling back to `/api/mock-s3-upload`.

### Create Import

```text
POST /api/imports
```

Headers:

```text
Authorization: Bearer <LDiHKID>
Content-Type: application/json
```

Request body:

```json
{
  "s3_bucket": "existing-bucket",
  "s3_key": "uploads/demo-user-123/youtube_takeout_2026.zip",
  "s3_etag": "optional-etag",
  "age": 23,
  "sex": "male"
}
```

Fields:

- `s3_bucket`: S3 bucket that received the uploaded ZIP.
- `s3_key`: uploaded object key. Use
  `uploads/<LDiHKID>/<filename>.zip`.
- `s3_etag`: optional S3 object ETag.
- `age`: optional user age for internal user creation. Used to derive
  `age_bucket` and `cohort`.
- `sex`: optional user sex for internal user creation. Stored lowercase and
  used to derive `cohort`.

Validation:

- `s3_bucket` must match the backend configured bucket.
- `s3_key` must be under `uploads/<LDiHKID>/`.
- `s3_key` must end in `.zip`.
- `age`, when present, must be an integer from `0` through `130`.
- `sex`, when present, must be one of `male`, `female`, `nonbinary`,
  `prefer_not_to_say`, or `unknown`. Values are case-normalized before storage.

Response:

```json
{
  "import_id": "9c6533fb-c99d-4ca3-9b3e-3ee8fb3b98de",
  "ldihk_id": "demo-user-123",
  "status": "queued"
}
```

### Get Import Status

```text
GET /api/imports/{import_id}
```

Headers:

```text
Authorization: Bearer <LDiHKID>
```

Response:

```json
{
  "import_id": "9c6533fb-c99d-4ca3-9b3e-3ee8fb3b98de",
  "ldihk_id": "demo-user-123",
  "status": "running",
  "records_seen": 120,
  "records_imported": 118,
  "warnings_count": 2,
  "error_message": null,
  "created_at": "2026-06-07T09:00:00+00:00",
  "started_at": "2026-06-07T09:00:10+00:00",
  "finished_at": null,
  "enrichment_status": "running",
  "enrichment_started_at": "2026-06-07T09:02:00+00:00",
  "enrichment_finished_at": null
}
```

Status values:

- `queued`: import was created and is waiting for a worker.
- `running`: worker claimed the import and is processing it.
- `completed`: import parsing and persistence completed.
- `failed`: import failed. Read `error_message`.

`completed` means ZIP parsing and persistence completed. It does not necessarily
mean duration enrichment is complete. Use `enrichment_status`,
`enrichment_started_at`, and `enrichment_finished_at` to decide whether the UI
should keep polling before showing final watch-time analytics.

Enrichment status values:

- `null`: no enrichment job exists for this import yet, or enrichment is not
  configured for this import.
- `queued`: enrichment was queued.
- `running`: enrichment is fetching video metadata.
- `completed`: enrichment finished.
- `failed`: enrichment failed. Query responses still work, but duration quality
  may be lower.

Polling recommendation: poll every 1-5 seconds while import status is `queued`
or `running`, or while import status is `completed` and enrichment status is
`queued` or `running`; stop on import `failed` or on import `completed` with no
pending enrichment.

### Query Usage Analytics

```text
POST /api/query
```

Headers:

```text
Authorization: Bearer <LDiHKID>
Content-Type: application/json
```

Request body:

```json
{
  "dataset": "usage_analytics",
  "metrics": ["event_count", "estimated_usage_seconds"],
  "dimensions": ["date", "platform"],
  "filters": {
    "start_date": "2026-06-01",
    "end_date": "2026-06-30",
    "platform": ["youtube", "tiktok", "instagram", "spotify", "linkedin"]
  },
  "options": {
    "include_zero_buckets": true,
    "limit": 500
  }
}
```

Response:

```json
{
  "schema_version": "youtube_usage.structured_query.v1",
  "dataset": "usage_analytics",
  "ldihk_id": "demo-user-123",
  "duration_strategy": {
    "kind": "event_duration_api_user_average_platform_default",
    "api_duration_source": "youtube_data_api",
    "user_average_source": "event_weighted_user_average",
    "global_default_seconds": 600,
    "platform_defaults_seconds": {
      "youtube_long": 600,
      "youtube_shorts": 60,
      "tiktok": 60,
      "instagram": 60,
      "spotify": 120,
      "linkedin": 120
    }
  },
  "query": {
    "metrics": ["event_count", "estimated_usage_seconds"],
    "dimensions": ["date", "platform"],
    "filters": {
      "start_date": "2026-06-01",
      "end_date": "2026-06-30",
      "platform": ["youtube", "tiktok", "instagram", "spotify", "linkedin"]
    },
    "options": {
      "include_zero_buckets": true,
      "limit": 500
    }
  },
  "quality": {
    "events_counted": 100,
    "events_with_api_duration": 80,
    "events_with_user_average_estimate": 15,
    "events_with_global_default_estimate": 5,
    "videos_unavailable": 5,
    "videos_capped": 1
  },
  "rows": [
    {
      "date": "2026-06-01",
      "platform": "tiktok",
      "event_count": 24,
      "estimated_usage_seconds": 1440
    }
  ]
}
```

### Query Population Benchmark

```text
POST /api/population
```

Headers:

```text
Authorization: Bearer <LDiHKID>
Content-Type: application/json
```

The browser calls this endpoint directly on the backend. The live population
benchmark compares YouTube watch time only (`platforms: ["youtube"]`; anything
else is `400 unsupported_platform`), and its days and hours are UTC so every
user is measured on the same clock. When the user has no YouTube watch history
in the range the response is `{"ready": false, "message": ...}`. Other
multi-product population benchmarks are mock-only.

Request body:

```json
{
  "platforms": ["youtube"],
  "startDate": "2026-05-08",
  "endDate": "2026-06-06",
  "includeSynthetic": true,
  "customPercentile": 90
}
```

Fields:

- `platforms`: optional array. Must be omitted or exactly `["youtube"]` for
  live-backed requests.
- `startDate`: inclusive date lower bound in `YYYY-MM-DD`.
- `endDate`: inclusive date upper bound in `YYYY-MM-DD`.
- `includeSynthetic`: boolean. Defaults to `true`.
- `customPercentile`: integer from `1` through `99`. Defaults to `90`.

Ready response:

```json
{
  "schema_version": "youtube_usage.population.v1",
  "ready": true,
  "dataset": "youtube_usage",
  "platforms": ["youtube"],
  "userPercentile": 73,
  "userDailyAverageHours": 3.12,
  "includeSynthetic": true,
  "customPercentile": 90,
  "distribution": [
    { "hours": 0, "density": 15 },
    { "hours": 1, "density": 85 },
    { "hours": 2, "density": 245 }
  ],
  "deciles": [
    {
      "date": "2026-06-01",
      "user": 2.8,
      "median": 2.3,
      "top10": 4.1,
      "bottom10": 0.8,
      "customPercentileHours": 4.1
    }
  ],
  "hourlyAverages": [
    {
      "hour": "00:00",
      "populationAvg": 0.352,
      "userAvg": 0.125
    }
  ]
}
```

Not-ready response:

```json
{
  "schema_version": "youtube_usage.population.v1",
  "ready": false,
  "message": "Dataset not ready. Please ingest YouTube data first."
}
```

Errors:

- `missing_authorization`
- `invalid_authorization`
- `invalid_request`
- `invalid_platforms`
- `unsupported_platform`
- `invalid_date_filter`
- `invalid_date_range`
- `invalid_include_synthetic`
- `invalid_custom_percentile`
- `database_unavailable`

## Query Parameters

### `dataset`

Required string. Supported values:

- `usage_analytics`: multi-platform usage analytics.
- `youtube_usage`: legacy alias retained for existing frontend callers.

### `metrics`

Required non-empty string array.

Allowed values:

- `event_count`: count of normalized usage events.
- `estimated_watch_seconds`: estimated watch duration for `watch` events. Uses
  explicit event duration when present, YouTube API duration when available,
  event-weighted user average for real YouTube rows, then platform defaults.
  For `/api/query`, watch duration is capped at the next watch event start for
  the same user and platform, so overlapping video durations cannot stack as
  simultaneous watch time.
- `estimated_usage_seconds`: estimated duration across all matching event types.
  Uses explicit event duration when present, then the same fallback strategy as
  `estimated_watch_seconds`.
- `api_watch_seconds`: watch duration using only API-enriched durations.
- `estimated_event_count`: count of watch events using estimated duration rather
  than API duration.
- `subscription_count`: count of distinct imported subscriptions.
- `unique_video_count`: count of distinct video IDs in matching usage events.
- `unique_channel_count`: count of distinct channel IDs in matching usage
  events.

Frontend naming notes:

- Use `estimated_watch_seconds`, not `watch_seconds`.
- Use `estimated_event_count` plus `quality`, not `events_missing_duration`.

### `dimensions`

Optional string array. Use an empty array for a single aggregate row.

Allowed values:

- `date`: groups by `YYYY-MM-DD`.
- `hour`: groups by hour of day, `0` through `23`.
- `weekday`: groups by ISO weekday, `1` Monday through `7` Sunday.
- `month`: groups by `YYYY-MM`.
- `event_type`: groups by normalized event type.
- `platform`: groups by normalized platform, such as `youtube`, `tiktok`,
  `instagram`, `spotify`, or `linkedin`.
- `product`: groups by product/surface, such as `long`, `shorts`, `feed`,
  `audio`, `youtube`, or `youtube_music`.
- `is_synthetic`: groups real bearer-scoped data against the synthetic
  population. Synthetic user IDs are never returned.
- `age`: groups by stored user age.
- `age_bucket`: groups by derived user age bucket: `adolescent`, `adult`, or
  `older`.
- `sex`: groups by stored user sex.
- `cohort`: groups by derived age-bucket/sex cohort, such as `adult_male`.
- `channel_id`: groups by YouTube channel ID when identifier dimensions are
  enabled.
- `video_id`: groups by YouTube video ID when identifier dimensions are enabled.

For the v5 demo, identifier dimensions are enabled so top-channel and top-video
queries can be rendered.

Supported event types:

- `watch`
- `search`
- `like`
- `comment`
- `live_chat`
- `playlist_add`
- `watch_later_add`
- `subscription_snapshot`
- `listen`
- `activity`

### `filters`

Optional object.

Allowed fields:

- `start_date`: inclusive date lower bound in `YYYY-MM-DD`.
- `end_date`: inclusive date upper bound in `YYYY-MM-DD`.
- `event_type`: string or string array of normalized event types.
- `platform`: string or string array of normalized platforms.
- `product`: string or string array.
- `is_synthetic`: boolean. `false` or omitted scopes to the bearer user's real
  data. `true` queries the synthetic population. If `is_synthetic` is used as a
  dimension without this filter, the response compares bearer data against the
  synthetic population.
- `age`: integer or integer array.
- `age_bucket`: string or string array.
- `sex`: string or string array.
- `cohort`: string or string array.

Identity filters are not allowed. Real-user results are always scoped by the
bearer token; synthetic population results are aggregate-only and never expose
individual synthetic profiles.

### `options`

Optional object.

Allowed fields:

- `include_zero_buckets`: boolean. Currently applies to hourly heatmaps when
  dimensions are exactly `["date", "hour"]` and both `start_date` and `end_date`
  are present.
- `limit`: positive integer result limit (default 500). The backend caps it at
  10000. Rows are ordered ascending by dimensions, so always request enough
  rows for the range, or use coarser dimensions (`month`, `weekday`, `hour`)
  for long ranges.
- `sort_by`: requested metric name, such as `event_count`.
- `sort_direction`: `asc` or `desc`.
- `timezone`: IANA timezone name, e.g. `Europe/Berlin`, applied to `date`,
  `hour`, `weekday` and `month` buckets and to `start_date` / `end_date`.
  Defaults to the backend's `QUERY_BUCKET_TIMEZONE` (`UTC`). The frontend sends
  the browser timezone.

## Example Queries

### Daily Watch Counts

```json
{
  "dataset": "youtube_usage",
  "metrics": ["event_count"],
  "dimensions": ["date"],
  "filters": {
    "event_type": "watch",
    "start_date": "2026-06-01",
    "end_date": "2026-06-30"
  },
  "options": {
    "limit": 500
  }
}
```

### Estimated Watch Seconds By Date

```json
{
  "dataset": "youtube_usage",
  "metrics": ["estimated_watch_seconds"],
  "dimensions": ["date"],
  "filters": {
    "event_type": "watch",
    "start_date": "2026-06-01",
    "end_date": "2026-06-30"
  },
  "options": {
    "limit": 500
  }
}
```

### Hourly Heatmap

```json
{
  "dataset": "youtube_usage",
  "metrics": ["event_count", "estimated_watch_seconds"],
  "dimensions": ["date", "hour"],
  "filters": {
    "event_type": "watch",
    "start_date": "2026-06-01",
    "end_date": "2026-06-07"
  },
  "options": {
    "include_zero_buckets": true,
    "limit": 1000
  }
}
```

### Event Counts By Type

```json
{
  "dataset": "youtube_usage",
  "metrics": ["event_count"],
  "dimensions": ["event_type"],
  "filters": {
    "start_date": "2026-06-01",
    "end_date": "2026-06-30"
  },
  "options": {
    "limit": 100
  }
}
```

### Subscription Count

```json
{
  "dataset": "youtube_usage",
  "metrics": ["subscription_count"],
  "dimensions": [],
  "filters": {},
  "options": {
    "limit": 1
  }
}
```

### Top Channels By Event Count

```json
{
  "dataset": "youtube_usage",
  "metrics": ["event_count"],
  "dimensions": ["channel_id"],
  "filters": {
    "start_date": "2026-06-01",
    "end_date": "2026-06-30"
  },
  "options": {
    "limit": 25,
    "sort_by": "event_count",
    "sort_direction": "desc"
  }
}
```

### Top Videos By Event Count

```json
{
  "dataset": "youtube_usage",
  "metrics": ["event_count"],
  "dimensions": ["video_id"],
  "filters": {
    "event_type": "watch",
    "start_date": "2026-06-01",
    "end_date": "2026-06-30"
  },
  "options": {
    "limit": 25,
    "sort_by": "event_count",
    "sort_direction": "desc"
  }
}
```

## Error Codes

Expected response shape:

```json
{
  "error": "invalid_metric"
}
```

Expected codes:

- `missing_authorization`
- `invalid_authorization`
- `invalid_payload`
- `import_not_found`
- `database_unavailable`
- `raw_sql_not_allowed`
- `invalid_dataset`
- `invalid_metrics`
- `invalid_metric`
- `invalid_dimensions`
- `invalid_dimension`
- `invalid_filters`
- `invalid_filter`
- `invalid_date_filter`
- `invalid_date_range`
- `invalid_limit`
- `invalid_sort`
- `invalid_timezone`
- `invalid_filename`
- `invalid_size`
- `file_too_large`
- `rate_limited` (429, `Retry-After` header and `retry_after` seconds)
- `confirmation_mismatch`
- `unknown_ldihk_id`
- `unsupported_platform`
- `unauthorized_import`

## Compatibility Notes

- Use `POST /api/query`, not old local `POST /api/v3/query`.
- Use `estimated_watch_seconds`, not `watch_seconds`.
- Use `estimated_event_count` and `quality`, not `events_missing_duration`.
- Send `LDiHKID` only in `Authorization: Bearer <LDiHKID>`, not in JSON bodies.
- The backend database schema still uses `user_id`; this is not a frontend
  concern.
- Deduplication uses backend-generated event fingerprints and unique database
  constraints. The frontend does not send dedupe keys.
- `POST /api/query` may be called before an import completes; it returns current
  available rows, often empty.
