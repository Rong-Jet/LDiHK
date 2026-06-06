# T12: Deployment And Smoke Tests

## Type

AFK.

## Objective

Make the MVP quickly hostable with separate web and worker commands, documented
environment variables, and smoke tests for the import/query path.

## Parallelization

Start after T02, T03, and T11 have basic interfaces. This ticket can begin
earlier by drafting docs and Docker scaffolding, but final smoke tests need the
core endpoints.

Owned files:

- `Dockerfile`
- deployment docs under `docs/backend/`
- `.env.example`
- `backend/tests/test_deployment_smoke.py`
- scripts needed for smoke tests

Avoid editing:

- Parser internals.
- Query compiler internals.
- Migration internals except invoking them.

## What To Build

Add:

- Docker image for API and worker.
- Web command.
- Worker command.
- Environment variable docs.
- Health check.
- Smoke test script or integration test that proves:
  - migrations can run
  - API can start
  - import job can be queued
  - query endpoint responds with seeded data

Deployment targets can be Render, Fly, or Railway. Keep docs provider-neutral
unless one platform has already been chosen.

## TDD Plan

1. RED: smoke test fails because required env vars are undocumented/missing.
   GREEN: add `.env.example` and config validation.
2. RED: health check smoke test fails. GREEN: ensure `/health` works in the
   deployed command.
3. RED: seeded query smoke test fails. GREEN: add script/test to run migrations
   and seed minimal rows.
4. RED: worker command test fails. GREEN: expose a worker entrypoint that can
   run one poll cycle in test mode.

## Acceptance Criteria

- [ ] One Docker image can run the web process.
- [ ] The same image can run the worker process.
- [ ] Required environment variables are documented.
- [ ] Health endpoint works.
- [ ] Smoke test proves DB connectivity.
- [ ] Smoke test proves query endpoint can return seeded data.
- [ ] Docs explain deployment with AWS S3, hosted Postgres, and YouTube API key.

## Blocked By

- T02 Import job API.
- T03 S3 ZIP worker skeleton.
- T11 Structured query API.

## Handoff Notes

Prioritize a deployable demo over perfect production ops. Do not add Kubernetes,
Terraform, Redis, or Celery for this MVP unless the user explicitly asks.
