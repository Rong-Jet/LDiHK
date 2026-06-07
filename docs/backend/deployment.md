# Backend Deployment

The v5 backend is packaged as one Docker image. Run that image as separate
Render services for the web API, import worker, enrichment worker, and
migrations. Provider secrets belong in Render environment variables, never in
git.

## Build

```sh
docker build -t ldihk-backend .
```

## Environment

Copy `.env.example` for local smoke runs. In Render, set the same variables on
the services listed below.

| Variable | Required | Used by | Notes |
| --- | --- | --- | --- |
| `PORT` | No | Web | Render injects this for web services. Local default is `8000`. |
| `DATABASE_URL` | Yes | Web, import worker, enrichment worker, migrations | Supabase Postgres URL using `postgres://` or `postgresql://`. Prefer the Session Pooler connection string on Render if direct connectivity is unreliable. |
| `FRONTEND_ALLOWED_ORIGINS` | Yes for browser access | Web | Comma-separated exact deployed frontend origins plus explicit localhost development origins. |
| `REQUIRE_LDIHK_BEARER` | Yes | Web | Set to `true` for hosted v5 so user-scoped routes derive identity from `Authorization: Bearer <LDiHKID>`. |
| `ALLOW_IDENTIFIER_DIMENSIONS` | Yes | Web | Set to `true` for top-channel and top-video dashboard queries. |
| `QUERY_BUCKET_TIMEZONE` | Yes | Web | Set to `UTC` for v5 date/hour buckets. |
| `AWS_ACCESS_KEY_ID` | Import worker if no IAM role | Import worker | S3 credential for reading queued Takeout ZIPs. |
| `AWS_SECRET_ACCESS_KEY` | Import worker if no IAM role | Import worker | S3 credential for reading queued Takeout ZIPs. |
| `AWS_SESSION_TOKEN` | No | Import worker | Optional token for temporary AWS credentials. Leave empty for long-lived IAM access keys. |
| `AWS_REGION` | Yes | Import worker | Region for `S3_BUCKET`. |
| `S3_BUCKET` | Yes | Web, import worker | Existing bucket where clients upload ZIPs. Backend accepts only this bucket. |
| `MAX_IMPORT_ZIP_BYTES` | Yes | Web, import worker | Maximum S3 ZIP object size accepted by hosted imports before download. |
| `IMPORT_WORKER_POLL_INTERVAL_SECONDS` | No | Import worker | Empty-queue polling interval for continuous workers. |
| `YOUTUBE_API_KEY` | Yes for enrichment | Enrichment worker | Google Cloud API key with YouTube Data API v3 enabled. |
| `YOUTUBE_MAX_DURATION_SECONDS` | No | Enrichment worker | Caps unusually long video durations during estimation. |
| `ENRICHMENT_BATCH_SIZE` | No | Enrichment worker | YouTube `videos.list` accepts at most 50 IDs per request. |
| `ENRICHMENT_POLL_INTERVAL_SECONDS` | No | Enrichment worker | Empty-queue polling interval for continuous enrichment workers. |
| `ENRICHMENT_RETRY_BASE_SECONDS` | No | Enrichment worker | Base retry delay after retriable YouTube API failures. |
| `LOG_LEVEL` | No | Web, import worker, enrichment worker, migrations | Runtime logging level. |
| `TEST_DATABASE_URL` | No | Tests | Optional live Postgres target for integration tests only. |

Set `DATABASE_URL` on every backend service. Set S3 variables on the import
worker, and also set `S3_BUCKET` on the web service when bucket validation is
enabled. Set YouTube variables on the enrichment worker, or on all backend
services if a shared Render environment group is simpler. Web, import worker,
enrichment worker, migrations all need the same hosted database URL.

## Supabase Setup

1. Create a Supabase project and store the database password in a password
   manager.
2. In the Supabase dashboard, open the project Connect panel and copy a Postgres
   connection string.
3. Use the direct connection string when Render can reach the project database.
   Supabase direct connections are best for long-lived backend services, but may
   require IPv6 reachability or a paid IPv4 add-on.
4. Prefer the Supabase Session Pooler connection string for Render when direct
   connectivity is unreliable. The Session Pooler runs on port `5432` and is the
   safer default for persistent backend services on IPv4-only networks.
5. Put the chosen URL in `DATABASE_URL` for the web service, import worker,
   enrichment worker, and migration command.
6. Run migrations before starting long-lived processes:

```sh
python backend/scripts/run_migrations.py
```

7. Confirm these tables exist after migration: `schema_migrations`, `users`,
   `imports`, `source_files`, `usage_events`, `subscriptions`,
   `youtube_videos`, and any v5 `enrichment_jobs` table once V5-T05 lands.

Capture the exact connection mode used during hosted smoke. If the direct host
works from Render, record "direct connection"; if it fails because of network
reachability, record "Session Pooler".

## Render Setup

Create one Docker Web Service and two Docker Background Workers from the same
repository and image.

### Web Service

```text
type: Web Service
language: Docker
command: gunicorn -b 0.0.0.0:$PORT backend.app:app
health check path: /health
```

The web service should expose the hosted API routes:

```text
GET /health
POST /api/imports
GET /api/imports/{import_id}
POST /api/query
```

`GET /health` does not require database connectivity. DB-backed routes return
`503` with `database_unavailable` when `DATABASE_URL` is missing or invalid.

### Import Worker

```text
type: Background Worker
language: Docker
command: python backend/scripts/run_worker.py
```

For one-off smoke checks, run:

```sh
python backend/scripts/run_worker.py --once
```

### Enrichment Worker

```text
type: Background Worker
language: Docker
command: python backend/scripts/run_enrichment_worker.py
```

For one-off smoke checks after V5-T05 lands, run:

```sh
python backend/scripts/run_enrichment_worker.py --once
```

### Migrations

Run migrations before web and workers begin processing hosted traffic:

```text
command: python backend/scripts/run_migrations.py
```

Use a Render pre-deploy command when available, or run it as a one-off job
before starting or redeploying the worker services. Keep provider secrets in
Render environment configuration rather than in the image.

## AWS S3 Setup

The frontend owns browser-to-S3 upload. The backend only validates queued import
requests and the import worker reads the uploaded ZIP.

Required upload key format:

```text
uploads/<LDiHKID>/<filename>.zip
```

The frontend must call `POST /api/imports` with an `s3_bucket` equal to
`S3_BUCKET` and an `s3_key` under the bearer identity prefix. Example:

```json
{
  "s3_bucket": "ldihk-demo-uploads",
  "s3_key": "uploads/demo-user-123/youtube_takeout_2026.zip",
  "s3_etag": "optional-etag"
}
```

Worker object access should be scoped to the upload prefix:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:HeadObject"
      ],
      "Resource": "arn:aws:s3:::YOUR_BUCKET_NAME/uploads/*"
    }
  ]
}
```

`s3:GetObject` is required for downloading ZIPs. `s3:HeadObject` documents the
worker metadata-read path used for object size checks; if AWS rejects it as a
policy action for the selected bucket type, keep `s3:GetObject` and verify the
SDK `head_object` call during smoke because general-purpose S3 HEAD object
metadata access is authorized by object read permission.

Keep frontend upload permissions separate from backend worker read permissions.
If uploads use SSE-KMS, add the needed KMS decrypt permissions to the worker
role or access key policy. `AWS_SESSION_TOKEN` can stay empty for long-lived IAM
access keys; set it only for temporary STS credentials.

## YouTube Data API Setup

1. Create or reuse a Google Cloud project.
2. Enable YouTube Data API v3.
3. Create an API key and restrict it as tightly as practical for this hosted
   deployment.
4. Set `YOUTUBE_API_KEY` on the enrichment worker.
5. Keep `ENRICHMENT_BATCH_SIZE` at or below `50`, because the backend calls
   YouTube `videos.list` in batches of video IDs.
6. Monitor quota during the demo. YouTube API requests consume quota units, and
   the default project quota can change.

Duration enrichment reads video IDs from imported watch events and writes
availability and duration data into Postgres. Private, deleted, unavailable, or
quota-failed videos should not block import completion; they affect query
quality metadata instead.

## Local Docker Commands

Run migrations:

```sh
docker run --rm --env-file .env ldihk-backend \
  python backend/scripts/run_migrations.py
```

Run the web process with the image default command:

```sh
docker run --rm --env-file .env -p 8000:8000 ldihk-backend
```

Run one import worker poll:

```sh
docker run --rm --env-file .env ldihk-backend \
  python backend/scripts/run_worker.py --once
```

Run the continuous import worker:

```sh
docker run --rm --env-file .env ldihk-backend \
  python backend/scripts/run_worker.py
```

Run the continuous enrichment worker after the enrichment worker script is
available:

```sh
docker run --rm --env-file .env ldihk-backend \
  python backend/scripts/run_enrichment_worker.py
```

Provider-neutral process commands:

```text
web:               gunicorn -b 0.0.0.0:$PORT backend.app:app
import-worker:     python backend/scripts/run_worker.py
enrichment-worker: python backend/scripts/run_enrichment_worker.py
migrations:        python backend/scripts/run_migrations.py
```

The web health check is:

```text
GET /health
```

## Smoke Test

The deployment smoke test covers migrations, the health endpoint, import
queueing, structured query responses, documentation contracts, and a ZIP import
fixture routed through the real comments/live-chat and playlist parsers:

```sh
uv run python -m unittest backend.tests.test_deployment_smoke
```

Use hosted smoke after V5-T08 lands to verify Render, Supabase, S3, and YouTube
API configuration end to end.

## Provider References

- Supabase database connections:
  `https://supabase.com/docs/guides/database/connecting-to-postgres`
- Render deploy commands:
  `https://render.com/docs/deploys`
- Render health checks:
  `https://render.com/docs/health-checks`
- AWS S3 `GetObject`:
  `https://docs.aws.amazon.com/AmazonS3/latest/API/API_GetObject.html`
- AWS S3 `HeadObject`:
  `https://docs.aws.amazon.com/AmazonS3/latest/API/API_HeadObject.html`
- YouTube Data API overview:
  `https://developers.google.com/youtube/v3/getting-started`
- YouTube `videos.list`:
  `https://developers.google.com/youtube/v3/docs/videos/list`
