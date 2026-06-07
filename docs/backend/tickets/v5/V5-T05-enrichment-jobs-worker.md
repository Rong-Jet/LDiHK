# V5-T05: Enrichment Jobs Worker

## Type

AFK.

## Objective

Turn duration enrichment from library functions into an operational hosted
worker that processes Postgres-backed `enrichment_jobs` asynchronously and can
also repair missing duration rows by scanning watch events.

## Parallelization

Can start immediately using seeded `usage_events` rows in tests. Coordinate with
V5-T04 if import completion queues enrichment jobs.

Owned files:

- `backend/enrichment/durations.py`
- `backend/enrichment/youtube_api.py` only if client config needs adjustment
- `backend/scripts/run_enrichment_worker.py`
- `backend/ingestion/worker.py` only for enqueue-on-import completion
- `backend/tests/test_duration_enrichment.py`
- New enrichment worker tests

Avoid editing:

- Parser modules.
- Query compiler except if test fixtures need duration quality checks.
- Import API validation.

## What To Build

Implement:

- `backend/scripts/run_enrichment_worker.py`.
- `--once` mode and continuous polling mode.
- `enrichment_jobs` claim/complete/fail flow using row locking where possible.
- Queueing enrichment work after successful import for distinct watch video IDs.
- Retry/backoff using `attempts`, `run_after`, and `error_message`.
- Batch YouTube API calls at max 50 IDs.
- Respect:
  - `YOUTUBE_API_KEY`
  - `YOUTUBE_MAX_DURATION_SECONDS`
  - `ENRICHMENT_BATCH_SIZE`
  - `ENRICHMENT_POLL_INTERVAL_SECONDS`
  - `ENRICHMENT_RETRY_BASE_SECONDS`
- Repair mode that scans missing/retriable watch video IDs without requiring a
  queued job.

## TDD Plan

Follow red-green-refactor with fake YouTube clients and fake DB connections.

1. RED: completed import with watch events creates an enrichment job. GREEN:
   add queueing behavior.
2. RED: enrichment worker `--once` claims one queued job and marks it running.
   GREEN: add job claim flow.
3. RED: worker enriches a batch and marks job completed. GREEN: call existing
   enrichment function from worker.
4. RED: API error updates job attempts, `run_after`, and `error_message`.
   GREEN: add backoff failure handling.
5. RED: repair mode enriches missing watch video IDs without a job. GREEN: add
   repair path.
6. RED: import status remains `completed` while enrichment is pending. GREEN:
   keep import/enrichment status separate.

Do not call the real YouTube API in tests.

## Acceptance Criteria

- [ ] Import completion queues enrichment work for watch video IDs.
- [ ] Enrichment worker can run once or continuously.
- [ ] Enrichment jobs are claimed safely.
- [ ] Successful jobs write `youtube_videos` rows and complete.
- [ ] API failures retry with backoff.
- [ ] Repair mode scans missing/retriable watch IDs.
- [ ] Import completion does not wait for enrichment.
- [ ] Tests use fake API clients.

## Blocked By

None, but enqueue-on-import may need coordination with V5-T04.

## Handoff Notes

Keep import and enrichment as separate Render workers. Do not add Redis,
Celery, or external queue infrastructure.

