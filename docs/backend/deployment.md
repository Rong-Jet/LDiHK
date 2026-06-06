# Backend Deployment

The backend is packaged as one Docker image. Run the same image with separate
commands for the web process, import worker, enrichment worker, and migrations.

## Build

```sh
docker build -t ldihk-backend .
```

## Environment

Copy `.env.example` and set provider secrets in the deployment platform:

| Variable | Required | Used by | Notes |
| --- | --- | --- | --- |
| `PORT` | No | Web | Defaults to `8000`. Render injects this for web services. |
| `DATABASE_URL` | Yes | Web, workers, migrations | Postgres URL using `postgres://` or `postgresql://`. For Supabase on Render, prefer the Session Pooler connection string when direct connectivity is unreliable. |
| `FRONTEND_ALLOWED_ORIGINS` | Yes for browser use | Web | Comma-separated exact deployed frontend origins plus explicit localhost development origins. |
| `REQUIRE_LDIHK_BEARER` | Yes | Web | Set to `true` for hosted v5 so user-scoped routes derive identity from `Authorization: Bearer <LDiHKID>`. |
| `ALLOW_IDENTIFIER_DIMENSIONS` | Yes | Web | Set to `true` for the v5 dashboard demo to allow `channel_id` and `video_id` dimensions. |
| `QUERY_BUCKET_TIMEZONE` | Yes | Web | Set to `UTC` for v5 date/hour buckets. |
| `AWS_ACCESS_KEY_ID` | Worker if no IAM role | Import worker | S3 credential for downloading queued Takeout ZIPs. |
| `AWS_SECRET_ACCESS_KEY` | Worker if no IAM role | Import worker | S3 credential for downloading queued Takeout ZIPs. |
| `AWS_SESSION_TOKEN` | No | Import worker | Temporary AWS credential token when required. |
| `AWS_REGION` | Import worker | Import worker | Region for the S3 bucket. |
| `S3_BUCKET` | Yes | Web, import worker | Existing bucket where clients upload ZIPs under `uploads/<LDiHKID>/`. |
| `MAX_IMPORT_ZIP_BYTES` | Yes | Web, import worker | Maximum S3 ZIP object size accepted by hosted imports. |
| `IMPORT_WORKER_POLL_INTERVAL_SECONDS` | No | Import worker | Empty-queue polling interval for continuous workers. |
| `YOUTUBE_API_KEY` | Enrichment worker | Enrichment worker | YouTube Data API key used for duration enrichment jobs. |
| `YOUTUBE_MAX_DURATION_SECONDS` | No | Enrichment worker | Maximum video duration accepted for dashboard estimates. |
| `ENRICHMENT_BATCH_SIZE` | No | Enrichment worker | Number of videos processed per enrichment batch. |
| `ENRICHMENT_POLL_INTERVAL_SECONDS` | No | Enrichment worker | Empty-queue polling interval for continuous enrichment workers. |
| `ENRICHMENT_RETRY_BASE_SECONDS` | No | Enrichment worker | Base retry delay for transient enrichment failures. |
| `LOG_LEVEL` | No | Web, workers | Runtime logging level. |
| `TEST_DATABASE_URL` | No | Tests | Optional live Postgres target for integration tests. |

## Commands

Run migrations before starting long-lived processes:

```sh
docker run --rm --env-file .env ldihk-backend \
  python backend/scripts/run_migrations.py
```

Run the web process with the image default command:

```sh
docker run --rm --env-file .env -p 8000:8000 ldihk-backend
```

Run one worker poll, useful for smoke checks:

```sh
docker run --rm --env-file .env ldihk-backend \
  python backend/scripts/run_worker.py --once
```

Run the continuous worker:

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

`GET /health` does not require database connectivity. DB-backed routes return
`503` with `database_unavailable` when `DATABASE_URL` is missing or invalid.

## Render

Create one Docker Web Service and two Docker Background Workers from the same
image:

```text
web:
  command: gunicorn -b 0.0.0.0:$PORT backend.app:app
  health check path: /health

import-worker:
  command: python backend/scripts/run_worker.py

enrichment-worker:
  command: python backend/scripts/run_enrichment_worker.py
```

Run migrations before long-lived services start, either as a Render pre-deploy
command or as a one-off job:

```text
python backend/scripts/run_migrations.py
```

Use the same image and shared hosted environment values for web, import worker,
enrichment worker, and migrations. Keep provider secrets in Render environment
configuration rather than in the image.

## Smoke Test

The deployment smoke test covers migrations, the health endpoint, import queueing,
structured query responses, and a ZIP import fixture routed through the real
comments/live-chat and playlist parsers:

```sh
uv run python -m unittest backend.tests.test_deployment_smoke
```
