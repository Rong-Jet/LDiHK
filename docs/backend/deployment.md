# Backend Deployment

The backend is packaged as one Docker image. On free hosting it runs as a
single Render free web service: the web API plus the import and enrichment
workers as background threads (`RUN_WORKERS_IN_PROCESS=true`). On paid plans
or a VM, the same image can instead run the workers as separate processes.
Provider secrets belong in the hosting provider's environment settings, never
in git.

| Part | Free provider | Notes |
| --- | --- | --- |
| Web API + workers | Render free web service | 512 MB RAM; sleeps after 15 minutes without traffic, ~1 minute to wake |
| Postgres | Neon free | 1 GB per project; scales to zero after 5 minutes, wakes on connect |
| Upload storage | Cloudflare R2 | 10 GB free, no egress fees, S3-compatible |
| Video durations | YouTube Data API v3 | 10,000 quota units per day |
| Frontend | Netlify free | See `Frontend/README.md` |

## Build

```sh
docker build -t ldihk-backend .
```

## Environment

Copy `.env.example` for local runs. On Render, the `render.yaml` blueprint
declares every variable; secrets are entered in the dashboard.

| Variable | Required | Used by | Notes |
| --- | --- | --- | --- |
| `PORT` | No | Web | Render injects this for web services. Local default is `8000`. |
| `DATABASE_URL` | Yes | Web, workers, migrations | Neon direct connection string (`...neon.tech/...?sslmode=require`, no `-pooler` in the host). The app pools its own connections; a pooled string also works, but poolers reject the per-statement timeout, so it is skipped there. Any `postgres://` or `postgresql://` URL works. |
| `DATABASE_CONNECT_TIMEOUT_SECONDS` | No | All | Default `10`. |
| `DATABASE_STATEMENT_TIMEOUT_MS` | No | Web, workers | Default `60000`; migrations run without a statement timeout. |
| `DATABASE_POOL_SIZE` | No | Web | Default `4` (one per gunicorn thread). Request handlers reuse pooled connections; `0` opens a new connection per request. |
| `DATABASE_POOL_MAX_IDLE_SECONDS` | No | Web | Default `60`. Pooled connections idle this long are closed, so they never keep a scale-to-zero database (Neon) awake. |
| `FRONTEND_ALLOWED_ORIGINS` | Yes for browser access | Web | Comma-separated exact frontend origins, e.g. `https://ldihk.xyz`. |
| `ALLOW_LOCALHOST_ORIGINS` | No | Web | Default `true`. Set `false` in production to drop the localhost dev origins. |
| `ENABLE_LOCAL_FILE_ROUTES` | No | Web | Default `true`. Set `false` in production to remove the unauthenticated local-file routes. |
| `RUN_WORKERS_IN_PROCESS` | Yes on free hosting | Web | `true` starts the import and enrichment threads inside the web process. |
| `WORKER_ACTIVE_WINDOW_SECONDS` | No | Web | Default `120`. In-process workers only poll the database this long after the last API request; import status polling keeps them active during an import. Longer values keep a free Neon database awake longer. |
| `WORKER_POLL_INTERVAL_SECONDS` | No | Web | Default `30`. Poll interval while active; new imports wake the worker immediately. |
| `RATE_LIMITS_ENABLED` | No | Web | Default `true`. In-memory limits: imports 20/hour per ID and 300/hour overall, population 120/hour per ID, failed logins 600/hour overall. Over the limit: `429 rate_limited` with `Retry-After`. |
| `CLIENT_IP_HEADER` | No | Web | Header that carries the real client IP, e.g. `True-Client-IP`. Enables per-IP limits (imports 60/hour, failed logins 30 per 10 minutes). Leave empty unless verified: Render appends to a client-supplied `X-Forwarded-For`, so that header can be spoofed. |
| `ALLOW_IDENTIFIER_DIMENSIONS` | Yes | Web | Set to `true` for top-channel and top-video dashboard queries. |
| `QUERY_BUCKET_TIMEZONE` | No | Web | Default bucket timezone when a query sends no `options.timezone`. Any IANA name; default `UTC`. |
| `UPLOADS_ENABLED` | No | Web | Default `true`. `false` stops issuing upload URLs (kill switch). |
| `UPLOAD_MAX_STORED_BYTES` | No | Web | Default `2147483648` (2 GiB). Archives that may exist in the bucket at once; new upload URLs are refused (`429 upload_storage_full`) beyond it. |
| `UPLOAD_MAX_PER_MONTH` | No | Web | Default `10000`. Upload URLs per calendar month (UTC); then `429 upload_budget_exhausted` until the 1st. |
| `UPLOAD_URL_TTL_SECONDS` | No | Web | Default `120`. How long an upload URL can start an upload. |
| `RUN_MIGRATIONS_ON_START` | No | Web | Default `true`. With `RUN_WORKERS_IN_PROCESS=true`, pending migrations run when the service starts (Render free has no pre-deploy step). |
| `S3_ENDPOINT_URL` | Yes for R2 | Web, import worker, smoke script | `https://<account-id>.r2.cloudflarestorage.com`. Leave empty for AWS S3. |
| `S3_BUCKET` | Yes | Web, import worker | Bucket where clients upload ZIPs. The API only accepts imports from this bucket. |
| `AWS_ACCESS_KEY_ID` | Yes | Web, import worker | R2 (or AWS) key with object read and write on the bucket: the API signs upload URLs, the worker reads and deletes archives. |
| `AWS_SECRET_ACCESS_KEY` | Yes | Import worker | Secret for the key above. |
| `AWS_SESSION_TOKEN` | No | Import worker | Only for temporary AWS STS credentials. Leave empty for long-lived IAM access keys and R2 tokens. |
| `AWS_REGION` | Yes | Import worker | `auto` for R2, the bucket region for AWS. |
| `MAX_IMPORT_ZIP_BYTES` | No | Web, import worker | Default `209715200` (200 MiB). Checked before download. |
| `MAX_IMPORT_MEMBER_BYTES` | No | Import worker | Default `157286400` (150 MiB). Uncompressed size limit for one history file. |
| `IMPORT_STALE_AFTER_SECONDS` | No | Import worker | Default `600`. A running import with an older heartbeat is reclaimed. |
| `IMPORT_MAX_ATTEMPTS` | No | Import worker | Default `3`. Imports are failed after this many attempts. |
| `IMPORT_WORKER_POLL_INTERVAL_SECONDS` | No | Standalone import worker | Empty-queue polling interval for `run_worker.py`. |
| `YOUTUBE_API_KEY` | Yes for enrichment | Enrichment worker | Google Cloud API key with YouTube Data API v3 enabled. Without it, watch time uses estimates. |
| `YOUTUBE_MAX_DURATION_SECONDS` | No | Enrichment worker | Caps unusually long video durations during estimation. |
| `ENRICHMENT_BATCH_SIZE` | No | Enrichment worker | YouTube `videos.list` accepts at most 50 IDs per request. |
| `ENRICHMENT_POLL_INTERVAL_SECONDS` | No | Standalone enrichment worker | Empty-queue polling interval. |
| `ENRICHMENT_RETRY_BASE_SECONDS` | No | Enrichment worker | Base retry delay after YouTube API failures. |
| `WEB_CONCURRENCY` | No | Web | Gunicorn processes, default `1`. Keep `1` on 512 MB. |
| `GUNICORN_THREADS` | No | Web | Request threads per process, default `4`. |
| `GUNICORN_TIMEOUT` | No | Web | Default `120` seconds. |
| `LOG_LEVEL` | No | All | Runtime logging level. |
| `TEST_DATABASE_URL` | No | Tests | Optional live Postgres target for integration tests only. |
| `BACKEND_BASE_URL` | Hosted smoke | Smoke script | Hosted web API base URL, for example `https://ldihk-api.onrender.com`. |
| `SMOKE_LDIHK_ID` | Hosted smoke | Smoke script | Bearer identity used for the end-to-end smoke run. Defaults to a generated `smoke-...` id when omitted. |
| `SMOKE_WRONG_LDIHK_ID` | Hosted smoke | Smoke script | Optional different bearer identity for the ownership negative check. |
| `SMOKE_S3_KEY` | Hosted smoke | Smoke script | Optional existing object key. Defaults to `uploads/<SMOKE_LDIHK_ID>/hosted-smoke-youtube-takeout.zip`. |
| `SMOKE_EXPECTED_EVENT_COUNT` | Hosted smoke | Smoke script | Expected minimum event rows from the tiny fixture. Default `1`. |
| `SMOKE_EXPECTED_WATCH_COUNT` | Hosted smoke | Smoke script | Expected minimum watch rows for duration enrichment. Default `1`. |
| `SMOKE_IMPORT_TIMEOUT_SECONDS` | Hosted smoke | Smoke script | Import status polling timeout. Default `180`. |
| `SMOKE_ENRICHMENT_TIMEOUT_SECONDS` | Hosted smoke | Smoke script | Duration enrichment polling timeout. Default `240`. |
| `SMOKE_POLL_INTERVAL_SECONDS` | Hosted smoke | Smoke script | Poll interval for import and enrichment checks. Default `5`. |
| `SMOKE_HTTP_TIMEOUT_SECONDS` | Hosted smoke | Smoke script | Per-request HTTP timeout. Default `30`. |

Web, import worker, enrichment worker, migrations all need the same hosted
database URL. With in-process workers, that is one service.

## Neon Setup

1. Create a Neon project (free plan) in the region closest to your Render
   region (Frankfurt for Render `frankfurt`, US East for `virginia`/`ohio`).
2. In the Neon console, open **Connect**, turn **Connection pooling** off and
   copy the direct connection string (no `-pooler` in the host). It already
   ends in `?sslmode=require`. The backend keeps its own small pool (at most
   `DATABASE_POOL_SIZE` + 2 connections), so Neon's pooler is not needed, and
   only direct connections accept `DATABASE_STATEMENT_TIMEOUT_MS`. A pooled
   string works too: the timeout is then skipped.
3. Put it in `DATABASE_URL` on Render (and locally for scripts).
4. Migrations run when the service starts (`RUN_MIGRATIONS_ON_START`, on by
   default with in-process workers), because Render's free plan has no
   pre-deploy command or one-off jobs. To run them by hand instead:

```sh
python backend/scripts/run_migrations.py
```

5. Nothing to seed: the synthetic comparison population is computed on demand
   for any date range (`backend/procedural_population.py`, calibration in
   `backend/synthetic_population.py`) and takes no database space. Every user
   sees the same population (fixed seed). Older deployments may still hold
   stored synthetic events, which are no longer read; remove them with:

```sh
uv run python backend/scripts/seed_synthetic_usage.py --remove-all
```

6. Confirm these tables exist: `schema_migrations`, `users`, `imports`,
   `source_files`, `usage_events`, `subscriptions`, `youtube_videos`,
   `enrichment_jobs`, `import_warnings`, and `synthetic_seed_runs`.

The in-process workers only touch the database while users are active, so Neon
can scale to zero between visits and stay inside the 100 free compute hours.
A standalone worker polling every few seconds would keep the database awake.

Supabase works as well: use its Session Pooler connection string, and note
that free Supabase projects pause after 7 days of low activity.

## Render Setup

Create the service from the blueprint: Render dashboard -> **New** ->
**Blueprint** -> select this repository. `render.yaml` defines one free Docker
web service:

```text
type: Web Service
language: Docker
plan: free
command: gunicorn -b 0.0.0.0:$PORT backend.app:app (with gthread workers, see Dockerfile)
health check path: /health
RUN_WORKERS_IN_PROCESS=true
```

If you create the web service by hand instead (**New** -> **Web Service**),
nothing from `render.yaml` applies: set its plain values on the service
yourself, and the health check path `/health` under **Settings**. Without
`RUN_WORKERS_IN_PROCESS=true` no upload is imported and the schema is never
created (every DB route answers `503`, and the log names the fix).
`ENABLE_LOCAL_FILE_ROUTES=false` and `ALLOW_LOCALHOST_ORIGINS=false` matter
too: both default to the local-development behaviour.

The web service exposes the hosted API routes:

```text
GET /health
GET /api/ready
GET /api/me
DELETE /api/me
POST /api/uploads
POST /api/imports
GET /api/imports/{import_id}
POST /api/query
POST /api/population
```

`GET /health` and `GET /api/ready` (the same check for browsers, whose ad
blockers often block `/health`) do not touch the database. DB-backed routes return `503` with
`database_unavailable` when the database is missing, unreachable, or not
migrated yet.

Free-plan behaviour to expect:

- The service sleeps after 15 minutes without inbound requests and takes about a
  minute to wake. The frontend pings `/health` and shows a "waking" state.
- Requests from the frontend while an import runs (status polling) keep it
  awake. If it sleeps mid-import anyway, the import is reclaimed after
  `IMPORT_STALE_AFTER_SECONDS` once the service wakes again.
- 750 free instance hours per workspace per month. One service running all
  month uses at most 744. An external uptime check (e.g. cron-job.org) calling
  `/health` every 10 minutes keeps it warm without waking the database.

### Alternative: separate worker processes

On paid plans or a VM, run the same image three times instead of using
in-process workers:

```text
web:               gunicorn -b 0.0.0.0:$PORT backend.app:app
import-worker:     python backend/scripts/run_worker.py
enrichment-worker: python backend/scripts/run_enrichment_worker.py
migrations:        python backend/scripts/run_migrations.py
```

Leave `RUN_WORKERS_IN_PROCESS` unset on the web service in that case. Both
worker scripts also accept `--once` (one job) and `--drain` (until the queue is
empty).

## Cloudflare R2 Setup

The backend issues presigned PUT URLs (`POST /api/uploads`), the browser
uploads straight to the bucket, and the import worker reads the ZIP and
deletes it when the import ends. The site on Netlify holds no storage keys.

1. In the Cloudflare dashboard, open **R2**, create a bucket (e.g.
   `ldihk-uploads`), and note the account ID.
2. Create an **R2 API token** with Object Read & Write, scoped to that bucket.
   Use its access key ID and secret for `AWS_ACCESS_KEY_ID` /
   `AWS_SECRET_ACCESS_KEY` on the backend only.
3. Set `S3_ENDPOINT_URL=https://<account-id>.r2.cloudflarestorage.com` and
   `AWS_REGION=auto`.
4. Add a CORS policy to the bucket so browsers can upload:

```json
[
  {
    "AllowedOrigins": ["https://ldihk.xyz", "http://localhost:4321"],
    "AllowedMethods": ["PUT"],
    "AllowedHeaders": ["content-type", "if-none-match"],
    "ExposeHeaders": ["ETag"],
    "MaxAgeSeconds": 3600
  }
]
```

   Add each preview origin you test with (e.g. the Netlify branch deploy).
5. Add an object lifecycle rule that deletes objects under `uploads/` after
   1 day, as a backstop: the backend already deletes each archive when its
   import ends, and deletes unused uploads after their URL expired.

### Staying inside the free tier

R2's free tier per month is 10 GB-month of storage (the average of each
day's peak), 1 million Class A operations (uploads, listings) and 10 million
Class B operations (reads); deletes and egress are free. Cloudflare has no
spending cap, so the backend enforces one:

| Limit | Default | Effect |
| --- | --- | --- |
| `UPLOAD_MAX_STORED_BYTES` | 2 GiB | Storage peak stays at most 2 GB of the 10 GB-month. |
| `UPLOAD_MAX_PER_MONTH` | 10,000 | At most about 10,000 uploads (Class A) a month. |
| Upload URL | single use, exact size, 120 s | A URL creates one object of the signed size; repeats fail with `412`. |
| Deletion | after each import | Archives exist for minutes; deletes are free. |
| `UPLOADS_ENABLED=false` | | Stops all new uploads at once. |

The backend never lists the bucket (a billed operation): deletions use the
keys recorded in Postgres. Reads are two per import (HeadObject, GetObject).
Remaining exposure: someone holding a valid URL can repeat the request until
it expires; those repeats fail with `412`, and Cloudflare does not document
whether failed requests count as operations. Set a budget alert in the
Cloudflare dashboard (Billing, Budget alerts) as a tripwire; revoking the R2
token stops every outstanding URL immediately.

Required upload key format:

```text
uploads/<LDiHKID>/<filename>.zip
```

The frontend must call `POST /api/imports` with an `s3_bucket` equal to
`S3_BUCKET` and an `s3_key` under the bearer identity prefix. Example:

```json
{
  "s3_bucket": "ldihk-uploads",
  "s3_key": "uploads/ldihk-cosmic-nebula-7k3m9x2p4q8r/youtube_takeout_2026.zip",
  "s3_etag": "optional-etag"
}
```

The worker needs `s3:GetObject` (and the metadata read `s3:HeadObject`) on
`uploads/*`. On AWS S3, scope the worker's IAM policy accordingly:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:HeadObject"],
      "Resource": "arn:aws:s3:::YOUR_BUCKET_NAME/uploads/*"
    }
  ]
}
```

`AWS_SESSION_TOKEN` can stay empty for long-lived IAM access keys and R2
tokens; set it only for temporary STS credentials.

## YouTube Data API Setup

1. Create or reuse a Google Cloud project.
2. Enable YouTube Data API v3.
3. Create an API key and restrict it to the YouTube Data API v3.
4. Set `YOUTUBE_API_KEY` on the backend service.
5. Keep `ENRICHMENT_BATCH_SIZE` at or below `50`, because the backend calls
   YouTube `videos.list` in batches of video IDs.
6. Monitor quota. Each `videos.list` call costs 1 unit (up to 50 videos), and
   the default quota is 10,000 units per day.

Duration enrichment reads video IDs from imported watch events and writes
availability and duration data into Postgres. Progress is committed per API
batch, and IDs that are already enriched are skipped on retry. Private,
deleted, unavailable, or quota-failed videos do not block import completion;
they affect query quality metadata instead.

## Local Docker Commands

Run migrations:

```sh
docker run --rm --env-file .env ldihk-backend \
  python backend/scripts/run_migrations.py
```

Run the web process (with in-process workers if `RUN_WORKERS_IN_PROCESS=true`):

```sh
docker run --rm --env-file .env -p 8000:8000 ldihk-backend
```

Run one import worker poll:

```sh
docker run --rm --env-file .env ldihk-backend \
  python backend/scripts/run_worker.py --once
```

Process all queued imports and exit:

```sh
docker run --rm --env-file .env ldihk-backend \
  python backend/scripts/run_worker.py --drain
```

Run the continuous enrichment worker:

```sh
docker run --rm --env-file .env ldihk-backend \
  python backend/scripts/run_enrichment_worker.py
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

The hosted end-to-end smoke script verifies the hosted web API, the workers,
Postgres, bucket import, bearer identity, duration enrichment, structured
queries, dedupe, and ownership enforcement together:

```sh
uv run python backend/scripts/smoke_hosted_youtube_takeout.py \
  --base-url "$BACKEND_BASE_URL" \
  --ldihk-id "$SMOKE_LDIHK_ID" \
  --s3-bucket "$S3_BUCKET" \
  --upload-fixture
```

`--upload-fixture` uploads a tiny non-private Takeout ZIP under
`uploads/<SMOKE_LDIHK_ID>/hosted-smoke-youtube-takeout.zip` using the configured
credentials and `S3_ENDPOINT_URL`. To reuse an existing object instead, omit
`--upload-fixture` and set `SMOKE_S3_KEY` or pass `--s3-key`.

With in-process workers, the hosted service processes the import itself and the
script waits for completion. For a one-off smoke from a machine with
`DATABASE_URL`, bucket credentials, and `YOUTUBE_API_KEY`, the script can run
the worker commands itself:

```sh
uv run python backend/scripts/smoke_hosted_youtube_takeout.py \
  --base-url "$BACKEND_BASE_URL" \
  --ldihk-id "$SMOKE_LDIHK_ID" \
  --s3-bucket "$S3_BUCKET" \
  --upload-fixture \
  --run-migrations \
  --run-import-worker-once \
  --run-enrichment-worker-once
```

Passing smoke output prints each checkpoint and finishes with JSON containing
the import IDs, object key, event-count rows, duration quality, estimated watch
seconds, and the event count after the dedupe rerun. Failures include the
specific route or worker command that failed and the last observed payload.

## Provider References

- Render free instances: `https://render.com/docs/free`
- Render Blueprints: `https://render.com/docs/blueprint-spec`
- Neon plans: `https://neon.com/docs/introduction/plans`
- Neon connection pooling: `https://neon.com/docs/connect/connection-pooling`
- Cloudflare R2 S3 API: `https://developers.cloudflare.com/r2/api/s3/api/`
- Cloudflare R2 CORS: `https://developers.cloudflare.com/r2/buckets/cors/`
- Cloudflare R2 lifecycle rules: `https://developers.cloudflare.com/r2/buckets/object-lifecycles/`
- YouTube Data API overview: `https://developers.google.com/youtube/v3/getting-started`
- YouTube `videos.list`: `https://developers.google.com/youtube/v3/docs/videos/list`
