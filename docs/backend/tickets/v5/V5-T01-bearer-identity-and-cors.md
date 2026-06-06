# V5-T01: Bearer Identity And CORS Boundary

## Type

AFK.

## Objective

Make public `ldihk_id` identity explicit for all user-scoped backend APIs. The
backend derives `ldihk_id` from `Authorization: Bearer <LDiHKID>`, maps it to
the existing internal `user_id` schema, and prevents request-body identity
spoofing.

## Parallelization

Can start immediately.

Owned files:

- `backend/app.py`
- `backend/imports_api.py`
- `backend/query_api.py` only for public identity request/response adaptation
- `backend/tests/test_import_api.py`
- `backend/tests/test_structured_query_api.py`
- New auth/CORS helper module and tests, if useful

Avoid editing:

- Parser modules.
- Worker persistence internals.
- Migration schema unless absolutely required.
- Enrichment logic.

## What To Build

Add a public request boundary that:

- Requires `Authorization: Bearer <LDiHKID>` for:
  - `POST /api/imports`
  - `GET /api/imports/{import_id}`
  - `POST /api/query`
- Allows `/health` without auth.
- Derives public `ldihk_id` from the bearer token.
- Rejects malformed or missing bearer tokens with `401`.
- Rejects request bodies containing `ldihk_id`, `user_id`, or `person_id`.
- Maps `ldihk_id` to the existing internal user lookup path.
- Returns `ldihk_id` in public responses where identity is included.
- Enforces ownership on import status responses.
- Adds explicit CORS support for `FRONTEND_ALLOWED_ORIGINS`.

## TDD Plan

Follow red-green-refactor with public API tests.

1. RED: `POST /api/imports` without `Authorization` returns
   `missing_authorization`. GREEN: add bearer-token requirement.
2. RED: malformed `Authorization` returns `invalid_authorization`. GREEN: parse
   only `Bearer <non-empty-token>`.
3. RED: `POST /api/imports` with body `user_id`, `person_id`, or `ldihk_id`
   returns an identity-field validation error. GREEN: reject body identity.
4. RED: valid bearer import queues an import for that `ldihk_id` and response
   includes `ldihk_id`. GREEN: wire bearer identity into the repository call.
5. RED: `GET /api/imports/{id}` for another bearer identity returns not found or
   unauthorized. GREEN: enforce import ownership.
6. RED: `POST /api/query` scopes results by bearer identity and rejects body
   identity. GREEN: inject `ldihk_id` into query validation internally.
7. RED: CORS preflight from an unlisted origin fails while configured frontend
   origin succeeds. GREEN: add CORS policy.

Use in-memory repositories/fake query connections for API tests where possible.

## Acceptance Criteria

- [ ] `/health` remains unauthenticated.
- [ ] User-scoped endpoints require `Authorization: Bearer <LDiHKID>`.
- [ ] Missing bearer token returns `401` with `missing_authorization`.
- [ ] Malformed bearer token returns `401` with `invalid_authorization`.
- [ ] Request body identity fields are rejected.
- [ ] Public responses use `ldihk_id`, not internal `user_id`.
- [ ] Import status ownership is enforced by bearer identity.
- [ ] Query results are scoped by bearer identity.
- [ ] CORS allows only configured origins plus explicit dev origins.

## Blocked By

None.

## Handoff Notes

Keep the internal database schema named `user_id`. This ticket changes the
public API boundary, not the data model.

