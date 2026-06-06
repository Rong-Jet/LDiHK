# T11: Structured Query API

## Type

AFK.

## Objective

Expose a frontend-facing constrained query API that compiles allowlisted metrics,
dimensions, and filters into parameterized Postgres SQL.

## Parallelization

Start after T01 defines the DB contract. This can be implemented independently
from import/parser work by inserting seed rows in tests.

Owned files:

- `backend/query_api.py`
- `backend/app.py` only for route registration
- `backend/tests/test_structured_query_api.py`

Avoid editing:

- Parser modules.
- S3 worker.
- Duration enrichment internals.

## What To Build

Endpoint:

```text
POST /api/query
```

Request shape:

```json
{
  "dataset": "youtube_usage",
  "user_id": "demo_user",
  "metrics": ["event_count", "estimated_watch_seconds"],
  "dimensions": ["date", "event_type"],
  "filters": {
    "start_date": "2025-01-01",
    "end_date": "2026-06-06"
  },
  "options": {
    "include_zero_buckets": true,
    "limit": 500
  }
}
```

Allowed metrics:

- `event_count`
- `estimated_watch_seconds`
- `api_watch_seconds`
- `estimated_event_count`
- `subscription_count`
- `unique_video_count`
- `unique_channel_count`

Allowed dimensions:

- `date`
- `hour`
- `weekday`
- `month`
- `event_type`
- `product`
- `channel_id`

Allowed filters:

- `user_id`
- `start_date`
- `end_date`
- `event_type`
- `product`

## TDD Plan

1. RED: valid event-count query returns grouped rows. GREEN: add query compiler
   and endpoint.
2. RED: raw SQL payload is rejected. GREEN: add validation.
3. RED: unknown metric/dimension/filter is rejected. GREEN: add allowlists.
4. RED: estimated watch seconds falls back from API duration to user average to
   `600`. GREEN: add duration expression.
5. RED: hourly heatmap can include zero buckets when requested. GREEN: add
   zero-fill behavior if needed for frontend.

Tests should call the API endpoint and use seeded database rows.

## Acceptance Criteria

- [ ] Frontend can request grouped usage metrics.
- [ ] Raw SQL is rejected.
- [ ] Unknown metrics, dimensions, and filters are rejected.
- [ ] SQL is parameterized.
- [ ] Result limit is enforced.
- [ ] Estimated watch seconds uses API duration, then user average, then `600`.
- [ ] Query responses include quality counts for duration source coverage.

## Blocked By

- T01 Postgres schema and DB contract.

## Handoff Notes

The current experimental `backend/youtube_sql.py` has a useful SQLite query API
shape. Port the concept, not the SQLite-specific SQL.

