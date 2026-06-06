# T04: Parser Dispatch And Contracts

## Type

AFK.

## Objective

Define shared parser contracts and file-path dispatch so individual parser
agents can work independently without inventing incompatible shapes.

## Parallelization

Can start immediately. Parser tickets T05 through T09 should use this contract.

Owned files:

- `backend/ingestion/models.py`
- `backend/ingestion/dispatch.py`
- `backend/ingestion/fingerprints.py`
- `backend/tests/test_parser_dispatch.py`
- `backend/tests/test_event_fingerprints.py`

Avoid editing:

- Specific parser modules except tiny fixtures if needed.
- DB schema.
- API routes.

## What To Build

Create parser dataclasses:

- `ParsedEvent`
- `ParsedSubscription`
- `ParseWarning`
- `ParseResult`

Create dispatch logic that maps ZIP member paths to parser names/callables.

Initial dispatch targets:

```text
watch-history.html
watch-history.json
subscriptions.csv
subscriptions.json
likes.json
comments.csv
live chats.csv
my-comments/*.html
my-live-chat-messages/*.html
```

Create a stable fingerprint helper for event deduplication.

## TDD Plan

1. RED: dispatch should route watch-history HTML to the watch parser name.
   GREEN: add dispatch table.
2. RED: unmatched files should be ignored, not fail. GREEN: add ignored result.
3. RED: event fingerprint should be stable for the same event. GREEN: add
   fingerprint helper.
4. RED: native IDs should dominate sequence-based fingerprints where present.
   GREEN: add native-ID handling.

Tests should use parser contracts as public interfaces.

## Acceptance Criteria

- [ ] Shared parser result dataclasses exist.
- [ ] Dispatch matches known YouTube Takeout paths.
- [ ] Dispatch ignores out-of-scope creator files.
- [ ] Fingerprint helper is deterministic.
- [ ] Fingerprint helper supports native IDs where available.
- [ ] Parser modules can be developed independently against this interface.

## Blocked By

None.

## Handoff Notes

Keep the contract small. Do not add fields just because a future parser might
need them. Add only fields required by the current implementation plan.

