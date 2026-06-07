# v5: Hosted Backend Workers And Deployment

## Status

Proposed.

## Summary

v5 finishes the backend-owned hosted demo path for the v4 YouTube Takeout
S3/Postgres backend. It turns the current backend into a Render-hosted API plus
worker system backed by Supabase Postgres, existing S3 storage, and YouTube Data
API enrichment, with enough smoke testing and configuration documentation for a
20-user demo.

## User Story

As the backend owner, I want the API, import worker, enrichment worker, hosted
Postgres database, and deployment configuration to work end-to-end, so that the
frontend can upload ZIPs to S3, queue imports, poll status, and query dashboard
data through backend APIs.

## Feature Set

- Supabase Postgres is provisioned and migrated.
- Render runs one Docker image as separate web, import worker, and enrichment
  worker services.
- The web service uses a production WSGI server.
- The import worker is hardened for hosted ZIP processing, S3 bucket ownership,
  ZIP size limits, and progress visibility.
- Duration enrichment runs asynchronously through a hosted worker process.
- Query API supports all dashboard shapes needed by the frontend, including
  server-sorted top channel and top video queries.
- Browser-facing API calls use explicit CORS and demo bearer-token identity.
- Provider configuration is documented for Supabase, Render, AWS S3, and YouTube
  Data API.
- A hosted smoke test proves migrations, import queueing, worker import,
  enrichment, status polling, and structured query responses.

## Public Contract

The v5 backend keeps the v4 public API routes:

```text
GET /health
POST /api/imports
GET /api/imports/{import_id}
POST /api/query
```

User-scoped routes derive public `ldihk_id` from:

```text
Authorization: Bearer <LDiHKID>
```

Request bodies do not include `ldihk_id`, `user_id`, or `person_id`. The
backend maps bearer `ldihk_id` to the existing Postgres `users` / `user_id`
schema internally.

Recommended Render services:

```text
web:
  type: Web Service
  command: gunicorn -b 0.0.0.0:$PORT backend.app:app
  health check path: /health

import-worker:
  type: Background Worker
  command: python backend/scripts/run_worker.py

enrichment-worker:
  type: Background Worker
  command: python backend/scripts/run_enrichment_worker.py

migrations:
  command: python backend/scripts/run_migrations.py
  run as Render pre-deploy command or one-off job before workers start
```

Recommended Supabase database connection:

```text
DATABASE_URL=<Supabase Session Pooler connection string, or direct connection if
Render can reach it>
```

Use the pooler/session connection string when the direct Supabase host is not
reachable from Render because of IPv4/IPv6 constraints.

## Locked Product And Architecture Decisions

- Public identity is `ldihk_id`, derived only from
  `Authorization: Bearer <LDiHKID>`.
- Database schema keeps internal `user_id`; public responses do not expose it.
- Public request bodies do not accept `ldihk_id`, `user_id`, or `person_id`.
- User-scoped routes return `401` with stable auth errors when the bearer token
  is missing or malformed.
- `POST /api/imports` must reject S3 keys outside `uploads/<LDiHKID>/`.
- `POST /api/imports` must reject buckets that do not match configured
  `S3_BUCKET`.
- The backend does not generate pre-signed upload URLs for v5. The frontend owns
  S3 upload and then calls `POST /api/imports`.
- The backend requires `.zip` object keys and enforces `MAX_IMPORT_ZIP_BYTES`
  using S3 metadata before download.
- Import status remains `queued`, `running`, `completed`, or `failed`.
- `completed` means ZIP parsing and Postgres persistence are done; duration
  enrichment may still be pending.
- There is no public `enriching` import status in v5. Enrichment confidence is
  expressed through query `quality`.
- Import and enrichment run as separate Render background workers.
- Normal duration enrichment uses Postgres `enrichment_jobs`; a repair mode may
  scan missing watch-video IDs.
- Import persistence commits per source file or batch, not one whole-ZIP
  transaction.
- Safety failures fail the import. Malformed records and recoverable parser
  issues should become warnings where possible.
- Re-uploading the same ZIP may create a new import row, but analytics rows must
  dedupe through event fingerprints.
- `GET /api/imports/{import_id}` must verify import ownership by bearer
  `ldihk_id`.
- `POST /api/query` may be called before an import completes; it returns current
  available rows, often empty.
- Query endpoint remains `POST /api/query`; old local `POST /api/v3/query` is
  not the hosted v5 contract.
- The frontend uses `estimated_watch_seconds`, not `watch_seconds`.
- The frontend uses `estimated_event_count` and `quality`, not
  `events_missing_duration`.
- Backend supports `youtube_usage` only in v5.
- Deduplication remains backend-owned through event fingerprints and database
  constraints.
- `channel_id` and `video_id` dimensions are enabled for the demo through
  `ALLOW_IDENTIFIER_DIMENSIONS=true`.
- Top channel/video queries sort server-side through allowlisted `sort_by` and
  `sort_direction`.
- Raw titles, channel names, search terms, comments, and Takeout source contents
  are not stored for v5 dashboard labels.
- Query date/hour buckets use UTC for v5.
- Zero buckets are required for date/hour heatmaps first. Date-only zero fill is
  nice-to-have and not a v5 release gate.
- CORS allows exact deployed frontend origins plus explicit localhost
  development origins only.
- Hosted smoke against Render, Supabase, S3, and YouTube API configuration is
  the v5 release gate.

## Ticket Plan

Detailed, independently grabbable implementation tickets live in:

```text
docs/backend/tickets/v5/
```

| Ticket | Title |
| --- | --- |
| [V5-T01](../tickets/v5/V5-T01-bearer-identity-and-cors.md) | Bearer identity and CORS boundary |
| [V5-T02](../tickets/v5/V5-T02-production-runtime-and-config.md) | Production runtime and config |
| [V5-T03](../tickets/v5/V5-T03-s3-import-api-hardening.md) | S3 import API hardening |
| [V5-T04](../tickets/v5/V5-T04-import-worker-progress-and-transactions.md) | Import worker progress and transactions |
| [V5-T05](../tickets/v5/V5-T05-enrichment-jobs-worker.md) | Enrichment jobs worker |
| [V5-T06](../tickets/v5/V5-T06-dashboard-query-completion.md) | Dashboard query completion |
| [V5-T07](../tickets/v5/V5-T07-provider-setup-and-deployment-docs.md) | Provider setup and deployment docs |
| [V5-T08](../tickets/v5/V5-T08-hosted-end-to-end-smoke.md) | Hosted end-to-end smoke test |

## Provider Setup Checklist

### Supabase

- Create a Supabase project.
- Save the database password in a password manager.
- Copy a Postgres connection string for backend services.
- Prefer the Session Pooler connection string for Render if direct connection
  reachability is unreliable.
- Set `DATABASE_URL` in every Render backend service.
- Run `python backend/scripts/run_migrations.py`.
- Confirm `schema_migrations`, `imports`, `usage_events`, `subscriptions`, and
  `youtube_videos` exist.

### Render

- Create one Docker Web Service from this repo.
- Set health check path to `/health`.
- Set command to `gunicorn -b 0.0.0.0:$PORT backend.app:app`.
- Add a pre-deploy or one-off migration command:
  `python backend/scripts/run_migrations.py`.
- Create one Background Worker for imports:
  `python backend/scripts/run_worker.py`.
- Create one Background Worker for enrichment:
  `python backend/scripts/run_enrichment_worker.py`.
- Configure the same environment variables on web and workers where needed.
- Use a non-sleeping service tier for demo reliability.

### AWS S3

- Use the existing bucket the frontend uploads to.
- Ensure frontend uploads under `uploads/<LDiHKID>/<filename>.zip`.
- Give backend worker credentials `s3:GetObject` and `s3:HeadObject` on that
  prefix.
- Keep frontend upload permissions separate from backend read permissions.
- Configure frontend-side S3 CORS/upload permissions outside the backend if the
  browser uploads directly.

### YouTube Data API

- Create or reuse a Google Cloud API key with YouTube Data API v3 enabled.
- Restrict the key as tightly as practical for the deployment.
- Set `YOUTUBE_API_KEY` only on the enrichment worker, or on all backend
  services if Render environment grouping is simpler.
- Monitor quota during the demo.

## Acceptance Criteria

- [ ] Render web service serves `/health` with a production WSGI server.
- [ ] Supabase Postgres migration succeeds.
- [ ] Render import worker processes a real S3 ZIP import.
- [ ] Render enrichment worker enriches at least one imported watch video or
      records it as unavailable.
- [ ] Frontend can poll import status through the API.
- [ ] Frontend can query daily watch counts, estimated watch seconds, hourly
      heatmap rows, event counts by type, subscription count, top channels, and
      top videos through `POST /api/query`.
- [ ] Query API uses UTC buckets for date/hour grouping.
- [ ] Raw SQL remains rejected.
- [ ] Raw source text and ZIP contents are not persisted.
- [ ] Hosted smoke test passes for a fixture import and can be rerun.

## Verification

Required local verification:

```sh
uv run python -m unittest discover backend/tests
```

Required hosted verification:

```sh
python backend/scripts/run_migrations.py
python backend/scripts/run_worker.py --once
python backend/scripts/run_enrichment_worker.py --once
python backend/scripts/smoke_hosted_youtube_takeout.py --base-url <render-url>
```

The exact enrichment and hosted smoke scripts are part of the v5 build.

## Out Of Scope

- Building the frontend.
- Owning browser-to-S3 upload implementation.
- Replacing Supabase with a separate analytics warehouse.
- Redis, Celery, Kubernetes, Terraform, or queue infrastructure beyond
  Postgres-backed jobs.
- Creator-side YouTube analytics.
- Raw title/comment/search storage for nicer labels.

## Notes

Supabase and Render setup details can change over time. For v5, prefer official
provider docs during implementation and capture the exact connection mode and
Render service commands used in `docs/backend/deployment.md` after the smoke
test passes.

Provider references checked on 2026-06-07:

- Supabase database connection modes:
  `https://supabase.com/docs/guides/database/connecting-to-postgres`
- Render web services:
  `https://render.com/docs/web-services`
- Render background workers:
  `https://render.com/docs/background-workers`
- Render Docker deployment:
  `https://render.com/docs/docker`
- Render environment variables:
  `https://render.com/docs/configure-environment-variables`
