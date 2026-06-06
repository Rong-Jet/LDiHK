# T10: Duration Enrichment Worker

## Type

AFK.

## Objective

Add asynchronous duration enrichment for watched YouTube videos using YouTube
Data API and cache results in Postgres.

## Parallelization

Start after T01 defines the DB contract. This can be implemented independently
from parser tickets by seeding `usage_events` rows in tests.

Owned files:

- `backend/enrichment/youtube_api.py`
- `backend/enrichment/durations.py`
- `backend/tests/test_duration_enrichment.py`
- `backend/tests/test_youtube_duration_parser.py`

Avoid editing:

- Parser modules.
- Import job API.
- Structured query API except shared duration contract docs if needed.

## What To Build

Implement:

- YouTube Data API client for `videos.list`.
- Batch size up to 50 video IDs.
- ISO 8601 duration parser with day support.
- Cap long durations at `5400` seconds by default.
- Upsert into `youtube_videos`.
- Mark requested IDs not returned as `deleted_or_unavailable`.
- Track `attempt_count`, `last_error`, `availability_status`, and
  `max_duration_applied`.

Do not block import completion on enrichment.

## TDD Plan

1. RED: duration parser handles `PT15M33S`. GREEN: add parser.
2. RED: duration parser handles `PT1H2M3S` and `P1DT2H`. GREEN: add full ISO
   support needed for YouTube.
3. RED: enrichment batches 51 IDs into two API calls. GREEN: add batching.
4. RED: returned API items upsert durations by `video_id`. GREEN: add cache
   write.
5. RED: requested IDs missing from API response are marked unavailable. GREEN:
   add missing handling.
6. RED: long videos are capped. GREEN: add cap.

Use a fake YouTube API client in tests. Do not call the real API in tests.

## Acceptance Criteria

- [ ] Missing video IDs are selected from SQL.
- [ ] API calls are batched at 50 IDs max.
- [ ] Durations are parsed and stored.
- [ ] Missing API results are stored as unavailable.
- [ ] API errors are tracked and retriable.
- [ ] Long videos are capped.
- [ ] No parser or API endpoint depends on enrichment being complete.

## Blocked By

- T01 Postgres schema and DB contract.

## Handoff Notes

Use the `CalcYTWatchTime` repo only as a behavioral reference. Do not copy code
verbatim.

