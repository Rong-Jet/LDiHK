# T03: S3 ZIP Worker Skeleton

## Type

AFK.

## Objective

Create the background worker skeleton that polls queued imports, downloads ZIPs
from AWS S3, safely iterates relevant ZIP entries, records source files, and
updates import status.

## Parallelization

Start after T01 defines the DB contract. This ticket should not depend on any
specific parser being complete; use a fake parser dispatch in tests.

Owned files:

- `backend/ingestion/s3.py`
- `backend/ingestion/zip_safety.py`
- `backend/ingestion/worker.py`
- `backend/scripts/run_worker.py`
- `backend/tests/test_s3_zip_worker.py`
- `backend/tests/test_zip_safety.py`

Avoid editing:

- Specific parser modules.
- Query API.
- Duration enrichment.

## What To Build

Implement a worker that:

1. Selects one queued import.
2. Marks it `running`.
3. Downloads its ZIP from S3 to a temp path.
4. Iterates ZIP entries safely.
5. Rejects path traversal entries.
6. Hashes relevant source files.
7. Creates `source_files` rows.
8. Calls parser dispatch for matching entries.
9. Updates import counts.
10. Marks the import `completed` or `failed`.

For this ticket, parser dispatch can be a minimal dependency-injected callable.
Specific parser behavior belongs to later tickets.

## TDD Plan

1. RED: worker should move one queued import to `running`, then `completed`.
   GREEN: add polling loop for one job.
2. RED: worker should reject ZIP entries like `../evil`. GREEN: add ZIP safety
   guard.
3. RED: worker should record `source_files` with SHA-256. GREEN: add source
   file recording.
4. RED: parser errors should mark import `failed` with an error message. GREEN:
   add failure handling.

Use fake S3 and fake parser dispatch in tests. Do not call AWS in tests.

## Acceptance Criteria

- [ ] Worker can process one queued import.
- [ ] Worker uses S3 object info from the `imports` row.
- [ ] ZIP path traversal is rejected.
- [ ] Source files are hashed and recorded.
- [ ] Import status reaches `completed` on success.
- [ ] Import status reaches `failed` on worker/parser failure.
- [ ] No raw ZIP contents are persisted after processing.

## Blocked By

- T01 Postgres schema and DB contract.

## Handoff Notes

Use dependency injection for S3 client and parser dispatcher. This keeps the
worker testable and lets parser agents work independently.

