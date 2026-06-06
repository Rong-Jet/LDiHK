# T01: Postgres Schema And DB Contract

## Type

AFK.

## Objective

Create the hosted Postgres foundation for the S3 YouTube Takeout ingestion MVP.
This ticket establishes the database schema, indexes, and minimal DB helper
contract that other agents can rely on.

## Parallelization

Can start immediately.

Owned files:

- `backend/db.py`
- `backend/migrations/`
- `backend/scripts/run_migrations.py`
- `backend/tests/test_postgres_schema.py`
- `docs/backend/tickets/T01-postgres-schema-and-db-contract.md` only for notes

Avoid editing:

- Parser modules.
- API route behavior beyond importing the DB helper if absolutely necessary.
- Worker/enrichment/query implementation.

## What To Build

Add a Postgres migration that creates the core MVP tables:

- `users`
- `imports`
- `source_files`
- `usage_events`
- `subscriptions`
- `youtube_videos`
- `youtube_channels`
- `enrichment_jobs`
- `import_warnings`

Add a small DB helper that reads `DATABASE_URL`, opens a connection, and can run
migrations.

Prefer a small dependency footprint. If the repo stays Flask/simple Python,
`psycopg` plus plain SQL migrations is enough.

## TDD Plan

Follow red-green-refactor with behavior tests.

1. RED: a migration smoke test fails because required tables do not exist.
   GREEN: add migration runner and table creation.
2. RED: a schema test fails because required indexes/constraints are missing.
   GREEN: add unique constraints and indexes.
3. RED: a helper test fails because `DATABASE_URL` is missing or invalid.
   GREEN: add clear config validation and error messages.

Use public DB/migration functions, not private implementation details.

## Acceptance Criteria

- [ ] A migration creates all MVP tables listed in the implementation plan.
- [ ] `usage_events` has a uniqueness constraint on `(user_id, event_fingerprint)`.
- [ ] `subscriptions` has a uniqueness constraint on `(user_id, channel_id)`.
- [ ] Import and enrichment status indexes exist.
- [ ] There is a script or callable function to run migrations.
- [ ] Tests verify the schema through actual DB inspection after migration.
- [ ] Existing SQLite v3 files are not removed or rewritten in this ticket.

## Blocked By

None.

## Handoff Notes

If a real Postgres test database is not available in CI/local sandbox, split the
tests into:

- SQL text/contract tests that run everywhere.
- Optional integration tests gated by `TEST_DATABASE_URL`.

