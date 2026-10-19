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
- Upload URLs come from the backend (`POST /api/uploads`), which enforces the
  storage budget. The frontend site holds no storage credentials; the Astro
  upload route only serves mock mode.
- The free-tier backend sleeps when idle. The frontend pings `GET /api/ready` on
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

- Backend-owned: `GET /health`, `GET /api/ready`, `GET /api/me`, `DELETE /api/me`,
  `POST /api/uploads`, `POST /api/imports`, `GET /api/imports/{import_id}`,
  `POST /api/query`, `POST /api/population`. The browser calls all of them
  directly on `PUBLIC_API_URL`.
- Frontend/Astro helper-owned: `GET /api/uploader-info`, `GET /api/wake`; in
  mock mode also `POST /api/upload-url`.
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
2. Archives over 20 MB are first trimmed in the browser: videos, photos and
   other media are removed so only history files are uploaded (at most
   200 MB).
3. Frontend asks the backend for an upload URL (`POST /api/uploads`) and
   uploads the ZIP straight to object storage (Cloudflare R2 or S3) under
   `uploads/<LDiHKID>/<random>-<filename>.zip`.
4. Frontend calls `POST /api/imports` with that bucket and key.
5. Backend creates a queued import in Postgres.
6. The import worker (a thread inside the backend web process on free
   hosting) picks up the import, downloads the ZIP, parses supported YouTube,
   TikTok and Instagram files, and writes normalized rows. An archive with no
   supported files fails with `error_message` starting `no_supported_files`.
   When the import ends, the archive is deleted from storage.
7. Frontend polls `GET /api/imports/{import_id}`.
8. Frontend calls `POST /api/query` for dashboard data.

There is no S3 event/Lambda trigger in the v5 backend flow.
The backend rejects import requests where `s3_key` is not under the bearer
identity prefix: `uploads/<LDiHKID>/`.

## Endpoints

### Health

```text
GET /health
GET /api/ready
```

Auth is not required. Both answer the same. The browser uses `/api/ready`:
ad and privacy blockers block URLs ending in `/health`
(`net::ERR_BLOCKED_BY_CLIENT`). Uptime checks use `/health`.

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
      "max_date": "2026-10-01",
      "watch_min_date": "2019-01-02",
      "watch_max_date": "2026-10-01"
    }
  },
  "profile": { "age_range": "20-24", "sex": "female" },
  "latest_import": null
}
```

`min_date` / `max_date` cover all event types; `watch_min_date` /
`watch_max_date` only views, which can be much narrower (Instagram keeps views
for weeks but likes and messages for years). `profile` is the user's optional
self-reported age range and sex (`null` when not given).

`latest_import` has the shape of `GET /api/imports/{import_id}` or is `null`.
A user whose first import is still queued or running has `datasets: {}` and a
`latest_import`.

Errors: `missing_authorization`, `invalid_authorization`,
`invalid_timezone` (400), `unknown_ldihk_id` (404), `database_unavailable`
(503), `rate_limited` (429, failed lookups are limited).

### Update Profile

```text
PATCH /api/me/profile
```

Sets or clears the optional age range and sex used to compare the user with
people of similar age and sex. Fields left out stay as they are; `null` (or
`"prefer_not_to_say"` for `sex`) clears a field.

```json
{ "age_range": "20-24", "sex": "female" }
```

- `age_range`: `13-14`, `15-19`, `20-24`, ..., `65-69`, `70+` (5-year steps; no
  exact age is ever stored).
- `sex`: `female`, `male`, `diverse`. The studies behind the comparison only
  report female and male; `diverse` and no answer compare across sexes.

Response: `{"profile": {"age_range": "20-24", "sex": "female"}}`. Errors:
`invalid_profile` (400, with `fields`), `unknown_ldihk_id` (404),
`rate_limited` (429, 30 per hour).

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

Owned by the frontend Astro server. Auth is not required. The upload UI uses
it to show whether uploads are live or simulated.

Response:

```json
{
  "isMock": false,
  "uploadConfigured": true,
  "provider": "backend"
}
```

`isMock` is `true` only in mock mode, where uploads go to the local mock
route (`provider: "mock"`). In live mode the backend signs uploads.

### Wake the Backend

```text
GET /api/wake
```

Owned by the frontend Astro server. Auth is not required and it takes no
parameters. While the browser's own `GET /api/ready` gets no answer, console
pages call it at most every 30 seconds. It requests the backend's `/health`
from the server side, which also starts a sleeping free-tier backend, waits up
to 8 seconds, and answers `200 {"status": "ok"}` when the backend is up,
otherwise `202 {"status": "waking"}`. Pages treat `ok` as ready, so a browser
whose direct request is blocked (an extension, a stale cache entry) is not left
waiting forever.

### Create Upload URL

```text
POST /api/uploads
```

Owned by the backend. Returns a presigned PUT URL for one archive, within the
storage budget that keeps the bucket inside Cloudflare R2's free tier (R2 has
no spending cap). The URL:

- is bound to the exact `size` (signed `Content-Length`) and `application/zip`,
- must start uploading within `UPLOAD_URL_TTL_SECONDS` (default 120),
- carries a signed `If-None-Match: *`, so it can create its object only once
  (a repeated upload fails with `412`); the bucket CORS rule must allow the
  `if-none-match` header.

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

`size` is in bytes, at most `MAX_IMPORT_ZIP_BYTES` (200 MB). The file name
must end in `.zip` (any case).

Response (`201`):

```json
{
  "url": "https://<account>.r2.cloudflarestorage.com/ldihk-uploads/uploads/demo-user-123/3f9c2a1b7d4e5f60-takeout.zip?X-Amz-...",
  "method": "PUT",
  "headers": {
    "Content-Type": "application/zip",
    "If-None-Match": "*"
  },
  "s3Bucket": "ldihk-uploads",
  "s3Key": "uploads/demo-user-123/3f9c2a1b7d4e5f60-takeout.zip",
  "expiresAt": "2026-10-18T10:02:00+00:00",
  "isMock": false
}
```

Send the PUT with exactly these headers. Errors (each with a `message` to
show):

- `missing_authorization`, `invalid_authorization` (401)
- `invalid_payload`, `invalid_filename`, `invalid_size`,
  `invalid_content_type` (400); `file_too_large` (413)
- `rate_limited` (429, `Retry-After`): 20 per hour per ID, 300 per hour overall
- `upload_storage_full` (429, `Retry-After: 3600`): archives waiting to be
  processed already fill `UPLOAD_MAX_STORED_BYTES`
- `upload_budget_exhausted` (429, `Retry-After` until the next month):
  `UPLOAD_MAX_PER_MONTH` upload URLs were issued this calendar month (UTC)
- `uploads_disabled` (503): `UPLOADS_ENABLED=false`
- `upload_not_configured` (503), `database_unavailable` (503),
  `upload_signing_failed` (500)

In mock mode the frontend's `POST /api/upload-url` returns the same shape
pointing at `/api/mock-s3-upload` (`"isMock": true`); in live mode that route
answers `410 upload_moved`.

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
  "age_range": "20-24",
  "sex": "female"
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
user is measured on the same clock. Other multi-product population benchmarks
are mock-only.

Who the user is compared with:

- Other real users whose YouTube history overlaps the range. The requesting
  user is never part of their own comparison group. Each person counts on the
  days inside their own history (a day without watching counts as 0 hours),
  but not before their export starts or after it ends.
- With `includeSynthetic: true`, about 1,400 synthetic profiles computed for
  exactly the requested days (seasons, habit drift, holidays, weekday and
  day-to-day variation; the same for every user). `syntheticModel` names the
  model and profile count; `syntheticBaseline` is always `null` now. For very
  long ranges an evenly spread subset of the profiles is used.
- Comparisons against fewer than 5 other people are refused
  (`reason: "insufficient_population"`), because percentiles of such a small
  group would reveal individual usage.
- With `compareWith: "cohort"` and a profile, only people of the same sex and
  age range count. The group widens to neighbouring 5-year ranges until it has
  30 people, then drops the sex if fewer than 5 remain, and falls back to
  everyone. `comparisonGroup` in the response says who was compared:
  `{"basis": "cohort", "ageRanges": ["15-19", "25-29"], "sex": "female", "size": 48}`.

Request body:

```json
{
  "platforms": ["youtube"],
  "startDate": "2026-05-08",
  "endDate": "2026-06-06",
  "includeSynthetic": true,
  "customPercentile": 90,
  "compareWith": "cohort"
}
```

### Risk Reference Values

```text
POST /api/population/reference
```

Same body as the population benchmark. Returns the typical (median) risk-score
inputs of the user's comparison group and of everyone: watch hours per active
day, late-night hours (23:00-04:59, UTC) and fragmentation (share of the day's
hours with at least 5 minutes of watching).

```json
{
  "ready": true,
  "comparisonGroup": { "basis": "cohort", "ageRanges": ["20-24", "20-24"], "sex": "female", "size": 52 },
  "cohort": { "dailyHours": 0.62, "lateNightHours": 0.11, "fragmentation": 0.08 },
  "overall": { "dailyHours": 0.55, "lateNightHours": 0.08, "fragmentation": 0.07 }
}
```

The risk tab measures each input relative to the cohort (see
`src/lib/riskModel.ts`), so a group that typically uses more is not scored
higher for that alone.

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
  "populationSize": 412,
  "syntheticBaseline": { "startDate": "2026-05-01", "endDate": "2026-05-14" },
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

- `populationSize`: number of other people (real and synthetic) in the
  comparison.
- `syntheticBaseline`: the synthetic profiles' window, or `null` when synthetic
  data is off or not seeded.
- `distribution`: number of people per 1-hour bucket of average daily watch
  time (24 means 24 h or more).

Not-ready responses (HTTP 200; show `message` to the user):

```json
{
  "schema_version": "youtube_usage.population.v1",
  "ready": false,
  "reason": "no_user_data",
  "message": "No YouTube watch history in the selected date range."
}
```

```json
{
  "schema_version": "youtube_usage.population.v1",
  "ready": false,
  "reason": "insufficient_population",
  "populationSize": 3,
  "minPopulationSize": 5,
  "message": "Fewer than 5 other people have YouTube data for this range, ..."
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
