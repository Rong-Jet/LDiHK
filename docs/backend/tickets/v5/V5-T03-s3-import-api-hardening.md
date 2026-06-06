# V5-T03: S3 Import API Hardening

## Type

AFK.

## Objective

Constrain import creation to the configured S3 bucket and bearer-owned upload
prefix. The frontend uploads ZIPs to S3, then calls `POST /api/imports`; the
backend validates that the object belongs to the bearer `ldihk_id` and is safe
for the worker to process.

## Parallelization

Start after V5-T01 establishes the bearer identity contract.

Owned files:

- `backend/imports_api.py`
- `backend/ingestion/s3.py`
- `backend/ingestion/worker.py` only for ZIP size/head-object use if needed
- `backend/tests/test_import_api.py`
- `backend/tests/test_s3_zip_worker.py`
- `.env.example` only if config names need adjustment

Avoid editing:

- Parser modules.
- Query compiler.
- Enrichment worker logic.
- Deployment docs except short handoff notes if needed.

## What To Build

Implement:

- Reject `POST /api/imports` when `s3_bucket` does not match configured
  `S3_BUCKET`.
- Reject `s3_key` outside `uploads/<LDiHKID>/`.
- Reject non-`.zip` object keys.
- Keep path traversal and empty path protections.
- Add `MAX_IMPORT_ZIP_BYTES` enforcement using S3 object metadata before
  download.
- Add S3 `HeadObject` helper abstraction.
- Keep `s3_etag` optional.

## TDD Plan

Follow red-green-refactor with API and worker-facing tests.

1. RED: import creation with wrong `s3_bucket` fails. GREEN: enforce
   `S3_BUCKET`.
2. RED: import creation with `uploads/other-user/takeout.zip` fails for bearer
   `demo-user`. GREEN: enforce bearer-owned prefix.
3. RED: import creation with non-`.zip` key fails. GREEN: add suffix validation.
4. RED: worker refuses an S3 object whose metadata size exceeds
   `MAX_IMPORT_ZIP_BYTES`. GREEN: add S3 head-object size check.
5. RED: import with missing `s3_etag` still queues successfully. GREEN: preserve
   optional ETag behavior.

Use fake S3 clients in tests. Do not call real AWS in tests.

## Acceptance Criteria

- [ ] Wrong configured bucket is rejected.
- [ ] S3 keys outside `uploads/<LDiHKID>/` are rejected.
- [ ] Non-ZIP keys are rejected.
- [ ] Oversized ZIPs fail with a clear import error.
- [ ] Valid bearer-owned ZIP keys still queue imports.
- [ ] `s3_etag` remains optional.
- [ ] Tests use fake S3 clients and do not require AWS.

## Blocked By

- V5-T01 bearer identity contract.

## Handoff Notes

The frontend owns S3 upload. Do not add pre-signed URL generation in this
ticket.

