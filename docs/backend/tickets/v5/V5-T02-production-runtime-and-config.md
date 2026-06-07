# V5-T02: Production Runtime And Config

## Type

AFK.

## Objective

Make the backend Docker image suitable for hosted Render web and worker
services. The web service must use a production WSGI server, and hosted runtime
configuration must be explicit in `.env.example` and deployment docs.

## Parallelization

Can start immediately.

Owned files:

- `pyproject.toml`
- `uv.lock`
- `Dockerfile`
- `.env.example`
- `backend/scripts/run_web.py`
- `docs/backend/deployment.md`
- `backend/tests/test_deployment_smoke.py`

Avoid editing:

- Parser modules.
- Query compiler behavior.
- Import worker internals.
- Database migrations except smoke invocation docs.

## What To Build

Add or document:

- `gunicorn` dependency.
- Render web command:
  `gunicorn -b 0.0.0.0:$PORT backend.app:app`.
- Render background worker commands:
  - `python backend/scripts/run_worker.py`
  - `python backend/scripts/run_enrichment_worker.py`
- Migration command:
  `python backend/scripts/run_migrations.py`.
- Hosted env vars:
  - `DATABASE_URL`
  - `FRONTEND_ALLOWED_ORIGINS`
  - `REQUIRE_LDIHK_BEARER=true`
  - `ALLOW_IDENTIFIER_DIMENSIONS=true`
  - `QUERY_BUCKET_TIMEZONE=UTC`
  - S3 and YouTube API vars.
- Stable configuration behavior for missing DB config on DB-backed routes.

## TDD Plan

Follow red-green-refactor with deployment smoke tests.

1. RED: deployment smoke test fails because `gunicorn` is not declared or the
   Docker/web command is not documented. GREEN: add dependency and docs.
2. RED: health check under production command expectation is missing. GREEN:
   document and, if needed, adapt web command wiring.
3. RED: env example test fails because v5 env vars are missing. GREEN: add
   required env vars.
4. RED: DB-backed route with missing `DATABASE_URL` must return a stable
   unavailable error rather than crashing. GREEN: keep/extend current error
   behavior.

Use tests that inspect deployable contracts and API behavior. Do not spawn real
Render services in unit tests.

## Acceptance Criteria

- [ ] `gunicorn` is installed in the production image.
- [ ] Docker/deployment docs use Gunicorn for the web process.
- [ ] Import and enrichment worker commands are documented.
- [ ] `.env.example` includes all v5 hosted settings.
- [ ] `/health` works without DB connectivity.
- [ ] DB-backed routes return stable unavailable errors when DB config is
      missing.
- [ ] Docs explain one image running web, import worker, enrichment worker, and
      migrations.

## Blocked By

None.

## Handoff Notes

Do not replace Flask. v5 only needs production hosting around the existing app.

