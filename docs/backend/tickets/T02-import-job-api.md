# T02: Import Job API

## Type

AFK.

## Objective

Expose API endpoints for the frontend to create an import job after uploading a
YouTube Takeout ZIP to AWS S3, and to poll import status.

## Parallelization

Start after T01 defines the DB contract. This ticket can be developed with a
fake DB repository if T01 is still in progress, but final merge should align to
T01 tables.

Owned files:

- `backend/app.py`
- `backend/imports_api.py`
- `backend/tests/test_import_api.py`

Avoid editing:

- Worker internals.
- Parser modules.
- Duration enrichment.
- Query API.

## What To Build

Add endpoints:

```text
POST /api/imports
GET /api/imports/{import_id}
```

`POST /api/imports` accepts:

```json
{
  "user_id": "demo_user",
  "s3_bucket": "existing-bucket",
  "s3_key": "uploads/demo_user/takeout.zip",
  "s3_etag": "optional-etag"
}
```

It should:

- Find or create the user.
- Insert an `imports` row with status `queued`.
- Return `import_id` and status.

`GET /api/imports/{import_id}` returns status, counts, timestamps, and error
message if failed.

## TDD Plan

1. RED: `POST /api/imports` with a valid payload should return `201` and a
   queued import. GREEN: add endpoint and DB insert.
2. RED: `GET /api/imports/{id}` should return the created import status.
   GREEN: add status endpoint.
3. RED: invalid payloads should return `400` with stable error codes. GREEN:
   add validation.
4. RED: raw/unsafe S3 keys should be rejected. GREEN: add simple S3 key
   validation.

Tests should hit the Flask/FastAPI test client, not internal helper functions.

## Acceptance Criteria

- [ ] Valid import creation returns `201`.
- [ ] Created imports have `queued` status.
- [ ] Status endpoint returns import status and counters.
- [ ] Invalid payloads are rejected.
- [ ] S3 bucket/key are stored but ZIP contents are not read by the API.
- [ ] Endpoint does not start parsing synchronously.
- [ ] Tests cover success and validation failure paths.

## Blocked By

- T01 Postgres schema and DB contract.

## Handoff Notes

Keep auth simple for the hackathon if no auth layer exists. The important
contract is that the frontend can upload to S3 first, then call this endpoint to
queue ingestion.

