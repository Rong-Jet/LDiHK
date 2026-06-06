# V5-T06: Dashboard Query Completion

## Type

AFK.

## Objective

Complete the structured query API so the frontend can power all v5 dashboard
views with the backend's current query contract: estimated watch seconds,
estimated event count, duration quality, UTC buckets, identifier dimensions,
and server-side top-list sorting.

## Parallelization

Start after V5-T01 establishes bearer identity injection into query requests.

Owned files:

- `backend/query_api.py`
- `backend/app.py` only for query route adaptation if needed
- `backend/tests/test_structured_query_api.py`
- `docs/backend/frontend-api-spec.md` only for contract corrections

Avoid editing:

- Import API.
- Worker internals.
- Parser modules.
- Enrichment worker implementation.

## What To Build

Implement:

- `video_id` dimension.
- `ALLOW_IDENTIFIER_DIMENSIONS` gate for `channel_id` and `video_id`, default
  enabled for v5 demo.
- `options.sort_by` and `options.sort_direction`.
- Server-side sorting for top channel/video queries.
- UTC date/hour bucketing via `QUERY_BUCKET_TIMEZONE=UTC`.
- Keep existing metric names:
  - `estimated_watch_seconds`
  - `estimated_event_count`
  - `api_watch_seconds`
  - `quality`
- Keep raw SQL rejected.
- Keep YouTube-only `dataset = youtube_usage`.
- Keep date/hour heatmap zero buckets.

## TDD Plan

Follow red-green-refactor with query compiler and route tests.

1. RED: request with `dimensions: ["video_id"]` is rejected. GREEN: add
   `video_id` dimension behind identifier gate.
2. RED: identifier dimensions are rejected when
   `ALLOW_IDENTIFIER_DIMENSIONS=false`. GREEN: add env/config gate.
3. RED: top channel query with `sort_by: "event_count"` and
   `sort_direction: "desc"` does not compile order correctly. GREEN: add
   allowlisted sorting.
4. RED: unknown `sort_by` or invalid `sort_direction` returns `invalid_sort`.
   GREEN: validate sort options.
5. RED: date/hour query documents or compiles UTC bucketing behavior. GREEN:
   add UTC bucketing path.
6. RED: raw SQL and unknown metrics remain rejected after sort/dimension
   additions. GREEN: preserve validation.

Use compiled SQL/parameter tests plus API route tests. Avoid tests coupled to
private helpers unless public compiler functions are already the contract.

## Acceptance Criteria

- [ ] `video_id` is an allowed gated dimension.
- [ ] `channel_id` and `video_id` are controlled by
      `ALLOW_IDENTIFIER_DIMENSIONS`.
- [ ] Top channel/video queries sort server-side.
- [ ] Unknown sort options are rejected.
- [ ] Date/hour buckets use UTC.
- [ ] Date/hour heatmap zero buckets still work.
- [ ] Raw SQL remains rejected.
- [ ] Existing allowed metrics still work.
- [ ] Query responses use `ldihk_id` publicly and never expose internal
      `user_id`.

## Blocked By

- V5-T01 bearer identity contract.

## Handoff Notes

Do not add `watch_seconds` or `events_missing_duration` aliases. The frontend
handoff uses backend metric names.

