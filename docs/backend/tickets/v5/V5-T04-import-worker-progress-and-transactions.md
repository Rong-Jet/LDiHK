# V5-T04: Import Worker Progress And Transactions

## Type

AFK.

## Objective

Make import processing more robust for hosted demo users by committing progress
per source file or batch instead of wrapping the whole ZIP in one persistence
transaction.

## Parallelization

Can start immediately, but coordinate with V5-T05 if adding enrichment queueing
inside import completion.

Owned files:

- `backend/ingestion/worker.py`
- `backend/tests/test_s3_zip_worker.py`
- `backend/tests/test_deployment_smoke.py` if smoke expectations change

Avoid editing:

- Parser internals.
- Import API request validation.
- Query compiler.
- Enrichment API client internals.

## What To Build

Change worker persistence semantics:

- Commit successful source-file persistence independently.
- Update import counters after each committed source file.
- Preserve already imported source files if a later supported file fails.
- Keep global safety failures, such as unsafe ZIP traversal, as import failures.
- Keep event dedupe through existing event fingerprints.
- Keep raw ZIP temporary files deleted after processing.
- Keep import status values limited to `queued`, `running`, `completed`,
  `failed`.

## TDD Plan

Follow red-green-refactor with worker behavior tests.

1. RED: two source files where the second parser fails should preserve writes
   from the first source file. GREEN: change transaction boundary.
2. RED: import counters update after first committed source file before a later
   failure. GREEN: update counts per source.
3. RED: unsafe ZIP traversal still fails the import without committing source
   files. GREEN: preserve global safety failure behavior.
4. RED: reprocessing duplicate events does not increase imported count. GREEN:
   keep fingerprint dedupe semantics.
5. RED: completed status is set after parsing/persistence only. GREEN: do not
   wait for enrichment.

Use fake repositories where possible; add a Postgres-like transaction fake only
when it verifies observable behavior.

## Acceptance Criteria

- [ ] Successful source files remain persisted if a later source file fails.
- [ ] Import counters can advance during processing.
- [ ] Unsafe ZIP entries still fail safely.
- [ ] Duplicate events are not duplicated.
- [ ] Import status remains simple and does not add `enriching`.
- [ ] Tests cover rollback/commit behavior through worker public methods.

## Blocked By

None.

## Handoff Notes

Do not expand parser scope in this ticket. Keep the work focused on worker
transaction and progress semantics.

