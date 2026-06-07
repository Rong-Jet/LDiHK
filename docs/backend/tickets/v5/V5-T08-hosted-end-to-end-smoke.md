# V5-T08: Hosted End-To-End Smoke Test

## Type

HITL for hosted credentials and deployed service URLs. AFK for smoke script and
repeatable verification once those values are available.

## Objective

Make hosted readiness observable. A v5 backend is not demo-ready until a smoke
test proves Render web, Render workers, Supabase Postgres, S3 import, bearer
identity, enrichment, and structured queries work together.

## Parallelization

Start after the basics from V5-T01 through V5-T07 exist.

Owned files:

- `backend/scripts/smoke_hosted_youtube_takeout.py`
- `backend/tests/test_deployment_smoke.py`
- `docs/backend/deployment.md`
- Small non-private smoke fixture, if added under tests/fixtures

Avoid editing:

- Parser internals except if a tiny fixture exposes a parser bug.
- Query compiler except if smoke identifies a contract mismatch.
- Worker internals except if smoke identifies a real hosted failure.

## What To Build

Add a smoke script that:

1. Verifies `GET /health`.
2. Optionally runs or verifies migrations.
3. Uploads or assumes a tiny non-private fixture ZIP exists in S3 under
   `uploads/<smoke_ldihk_id>/`.
4. Calls `POST /api/imports` with `Authorization: Bearer <smoke_ldihk_id>`.
5. Polls `GET /api/imports/{import_id}` until `completed` or `failed`.
6. Calls `POST /api/query` for event counts.
7. Runs enrichment once or waits for the enrichment worker.
8. Calls `POST /api/query` for `estimated_watch_seconds`.
9. Re-runs the import or query path to prove dedupe/no duplicate analytics.
10. Tries another bearer identity against the import ID to prove ownership
    enforcement.

## TDD Plan

Follow red-green-refactor with fake HTTP/S3 clients before using hosted services.

1. RED: smoke script unit test fails because `/health` check is missing. GREEN:
   add health step with fake HTTP client.
2. RED: import creation step does not send bearer token. GREEN: add bearer
   header.
3. RED: polling does not stop on `completed`/`failed`. GREEN: add status loop.
4. RED: query step does not verify rows. GREEN: assert event-count response.
5. RED: ownership negative check is missing. GREEN: add wrong-bearer check.
6. RED: script does not summarize failures clearly. GREEN: add actionable
   output.

After local fake-client tests pass, run the script against real hosted services
with environment-provided URL and credentials.

## Acceptance Criteria

- [ ] Smoke script targets a configurable backend base URL.
- [ ] Smoke script sends `Authorization: Bearer <LDiHKID>`.
- [ ] Hosted health check passes.
- [ ] Hosted import queues and completes from a real S3 ZIP.
- [ ] Hosted query returns event-count rows.
- [ ] Hosted enrichment improves or records duration availability.
- [ ] Re-run does not duplicate analytics rows.
- [ ] Wrong bearer cannot read another import status.
- [ ] Smoke output includes import ID, row counts, and clear failure messages.

## Blocked By

- V5-T01 bearer identity and CORS boundary.
- V5-T02 production runtime and config.
- V5-T03 S3 import API hardening.
- V5-T04 import worker progress and transactions.
- V5-T05 enrichment jobs worker.
- V5-T06 dashboard query completion.
- V5-T07 provider setup and deployment docs.

## Handoff Notes

This is the v5 release gate. Do not mark the backend demo-ready until this
passes against real Render, Supabase, S3, and YouTube Data API configuration.

