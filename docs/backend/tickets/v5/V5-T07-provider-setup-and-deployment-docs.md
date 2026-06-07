# V5-T07: Provider Setup And Deployment Docs

## Type

HITL for provider credential creation. AFK for documentation and local smoke
contracts once credentials are provided.

## Objective

Document the exact Supabase, Render, AWS S3, and YouTube Data API setup needed
to run the v5 backend. Make the deployment path executable by a backend owner
without relying on implicit tribal knowledge.

## Parallelization

Can start immediately. Final hosted verification depends on V5-T08.

Owned files:

- `docs/backend/deployment.md`
- `.env.example`
- `docs/backend/frontend-api-spec.md` only for provider-facing clarifications
- `backend/tests/test_deployment_smoke.py`

Avoid editing:

- Application behavior unless a deployment smoke contract reveals a missing
  public interface.
- Parser modules.
- Query compiler internals.
- Worker internals.

## What To Build

Document:

- Supabase project setup.
- Supabase connection string choice, preferring Session Pooler for Render when
  direct connectivity is unreliable.
- Render Web Service command:
  `gunicorn -b 0.0.0.0:$PORT backend.app:app`.
- Render import worker command:
  `python backend/scripts/run_worker.py`.
- Render enrichment worker command:
  `python backend/scripts/run_enrichment_worker.py`.
- Migration command:
  `python backend/scripts/run_migrations.py`.
- AWS S3 worker IAM permissions:
  - `s3:GetObject`
  - `s3:HeadObject`
  - scoped to `uploads/*`.
- Frontend upload prefix:
  `uploads/<LDiHKID>/<filename>.zip`.
- YouTube Data API key setup and quota caveats.
- Required env vars and which Render service needs them.
- `AWS_SESSION_TOKEN` can be empty for long-lived IAM access keys.

## TDD Plan

Follow red-green-refactor with docs-contract smoke tests.

1. RED: deployment smoke test fails because Render commands are missing from
   docs. GREEN: document commands.
2. RED: env docs test fails because required v5 env vars are missing. GREEN:
   update `.env.example`.
3. RED: docs test fails because Supabase/Render/S3/YouTube setup sections are
   missing. GREEN: add provider setup sections.
4. RED: docs test fails because AWS session token behavior is unclear. GREEN:
   document it as optional for non-temporary credentials.

These are documentation contract tests, not live provider tests.

## Acceptance Criteria

- [ ] Deployment docs include Supabase setup.
- [ ] Deployment docs include Render web/import/enrichment/migration commands.
- [ ] Deployment docs include S3 IAM permissions and prefix requirements.
- [ ] Deployment docs include YouTube Data API setup.
- [ ] `.env.example` includes all v5 env vars.
- [ ] `AWS_SESSION_TOKEN` is documented as optional.
- [ ] No secrets are committed.

## Blocked By

None.

## Handoff Notes

Use official provider docs during final deployment because provider dashboards
change over time. Capture the exact connection mode used after smoke passes.

