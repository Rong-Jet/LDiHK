# Backend Deployment

The backend is packaged as one Docker image. Run the same image with separate
commands for the web process, import worker, and migrations.

## Build

```sh
docker build -t ldihk-backend .
```

## Environment

Copy `.env.example` and set provider secrets in the deployment platform:

| Variable | Required | Used by | Notes |
| --- | --- | --- | --- |
| `PORT` | No | Web | Defaults to `8000`. Most hosts inject this. |
| `DATABASE_URL` | Yes | Web, worker, migrations | Postgres URL using `postgres://` or `postgresql://`. |
| `AWS_ACCESS_KEY_ID` | Worker if no IAM role | Worker | S3 credential for downloading queued Takeout ZIPs. |
| `AWS_SECRET_ACCESS_KEY` | Worker if no IAM role | Worker | S3 credential for downloading queued Takeout ZIPs. |
| `AWS_SESSION_TOKEN` | No | Worker | Temporary AWS credential token when required. |
| `AWS_REGION` | Worker | Worker | Region for the S3 bucket. |
| `S3_BUCKET` | Upload/API clients | Upload flow | Bucket clients should place ZIPs under `uploads/<user_id>/`. |
| `YOUTUBE_API_KEY` | Enrichment only | Duration enrichment | Required when running duration enrichment jobs. |
| `TEST_DATABASE_URL` | No | Tests | Optional live Postgres target for integration tests. |

## Commands

Run migrations before starting long-lived processes:

```sh
docker run --rm --env-file .env ldihk-backend \
  python backend/scripts/run_migrations.py
```

Run the web process:

```sh
docker run --rm --env-file .env -p 8000:8000 ldihk-backend \
  python backend/scripts/run_web.py
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

Provider-neutral process commands:

```text
web:     python backend/scripts/run_web.py
worker:  python backend/scripts/run_worker.py
release: python backend/scripts/run_migrations.py
```

The web health check is:

```text
GET /health
```

## Smoke Test

The deployment smoke test covers migrations, the health endpoint, import queueing,
structured query responses, and a ZIP import fixture routed through the real
comments/live-chat and playlist parsers:

```sh
uv run python -m unittest backend.tests.test_deployment_smoke
```
