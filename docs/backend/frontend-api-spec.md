# LDiHK Frontend Backend API Handoff

## Status

Draft for v5 frontend handoff.

This is the API contract the frontend should integrate against for the hosted
YouTube-only demo. It follows the current backend architecture: frontend uploads
the ZIP to S3, tells the backend where the uploaded object is, polls import
status, and queries analytics through a structured query endpoint.

## Identity

All user-scoped requests include:

```text
Authorization: Bearer <LDiHKID>
```

`LDiHKID` is the public-facing pseudo-account identifier for the demo. The
backend derives identity from this header and maps it internally to the Postgres
`users` / `user_id` schema.

Do not send `ldihk_id`, `user_id`, or `person_id` in request bodies.

Example:

```text
Authorization: Bearer demo-user-123
```

Backend behavior:

- Finds or creates an internal user for `external_id = demo-user-123`.
- Stores the internal UUID as `user_id` in Postgres.
- Returns `ldihk_id` in public responses where useful.

This is demo identity, not production authentication.

## Platform Scope

Only YouTube Takeout is supported in v5.

Supported dataset:

```text
youtube_usage
```

Unsupported for now:

```text
instagram_usage
tiktok_usage
twitter_usage
linkedin_usage
```

## Upload And Import Flow

1. User selects a YouTube Takeout ZIP in the frontend.
2. Frontend uploads the ZIP to S3 under `uploads/<LDiHKID>/<filename>.zip`.
3. Frontend calls `POST /api/imports` with S3 object metadata.
4. Backend creates a queued import in Postgres.
5. Worker polls Postgres, downloads the ZIP from S3, parses supported YouTube
   files, and writes normalized rows.
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
  "s3_etag": "optional-etag"
}
```

Fields:

- `s3_bucket`: S3 bucket that received the uploaded ZIP.
- `s3_key`: uploaded object key. Use
  `uploads/<LDiHKID>/<filename>.zip`.
- `s3_etag`: optional S3 object ETag.

Validation:

- `s3_bucket` must match the backend configured bucket.
- `s3_key` must be under `uploads/<LDiHKID>/`.
- `s3_key` must end in `.zip`.

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
  "finished_at": null
}
```

Status values:

- `queued`: import was created and is waiting for a worker.
- `running`: worker claimed the import and is processing it.
- `completed`: import parsing and persistence completed.
- `failed`: import failed. Read `error_message`.

`completed` does not mean duration enrichment is complete. Query responses keep
working before enrichment completes and expose duration confidence through
`quality`.

Polling recommendation: poll every 2-5 seconds while status is `queued` or
`running`; stop on `completed` or `failed`.

### Query YouTube Usage

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
  "dataset": "youtube_usage",
  "metrics": ["event_count", "estimated_watch_seconds"],
  "dimensions": ["date"],
  "filters": {
    "start_date": "2026-06-01",
    "end_date": "2026-06-30",
    "event_type": "watch"
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
  "dataset": "youtube_usage",
  "ldihk_id": "demo-user-123",
  "duration_strategy": {
    "kind": "api_user_average_global_default",
    "api_duration_source": "youtube_data_api",
    "user_average_source": "event_weighted_user_average",
    "global_default_seconds": 600
  },
  "query": {
    "metrics": ["event_count", "estimated_watch_seconds"],
    "dimensions": ["date"],
    "filters": {
      "start_date": "2026-06-01",
      "end_date": "2026-06-30",
      "event_type": "watch"
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
      "event_count": 24,
      "estimated_watch_seconds": 7200
    }
  ]
}
```

## Query Parameters

### `dataset`

Required string. Only `youtube_usage` is supported.

### `metrics`

Required non-empty string array.

Allowed values:

- `event_count`: count of normalized usage events.
- `estimated_watch_seconds`: estimated watch duration for `watch` events. Uses
  YouTube API duration when available, then event-weighted user average, then
  global default of 600 seconds.
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
- `product`: groups by `youtube` or `youtube_music` where distinguishable.
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

### `filters`

Optional object.

Allowed fields:

- `start_date`: inclusive date lower bound in `YYYY-MM-DD`.
- `end_date`: inclusive date upper bound in `YYYY-MM-DD`.
- `event_type`: string or string array of normalized event types.
- `product`: string or string array. Usually `youtube` or `youtube_music`.

Identity filters are not allowed. The backend always scopes results by the
bearer token.

### `options`

Optional object.

Allowed fields:

- `include_zero_buckets`: boolean. Currently applies to hourly heatmaps when
  dimensions are exactly `["date", "hour"]` and both `start_date` and `end_date`
  are present.
- `limit`: positive integer result limit. The backend caps this at its maximum.
- `sort_by`: requested metric name, such as `event_count`.
- `sort_direction`: `asc` or `desc`.

Date and hour buckets use UTC in v5.

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
