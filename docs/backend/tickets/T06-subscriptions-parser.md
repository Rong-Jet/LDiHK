# T06: Subscriptions Parser

## Type

AFK.

## Objective

Parse YouTube subscriptions from Takeout into normalized subscription snapshot
rows and optional usage events.

## Parallelization

Start after T04 parser contracts exist. Can be implemented independently of
watch history and enrichment.

Owned files:

- `backend/ingestion/parsers/subscriptions.py`
- `backend/tests/test_subscriptions_parser.py`
- subscription fixtures under `backend/tests/fixtures/` if needed

Avoid editing:

- Watch-history parser.
- Query API.
- Duration enrichment.

## What To Build

Support:

```text
YouTube and YouTube Music/subscriptions/subscriptions.csv
YouTube and YouTube Music/subscriptions/subscriptions.json
```

CSV may contain:

```text
Channel Id
Channel Url
Channel Title
```

Emit:

- `ParsedSubscription`
- optionally `ParsedEvent(event_type='subscription_snapshot')`

Treat this as snapshot state unless the export contains timestamps.

## TDD Plan

1. RED: parser emits subscriptions from standard CSV headers. GREEN: add CSV
   parsing.
2. RED: parser tolerates missing optional title/url columns. GREEN: add fallback
   behavior.
3. RED: duplicate channel IDs are deduped within one file. GREEN: add local
   dedupe.
4. RED: malformed rows produce warnings. GREEN: add warning handling.

## Acceptance Criteria

- [ ] Standard `subscriptions.csv` imports channel IDs.
- [ ] Channel URL and title are captured when present.
- [ ] Channel title is not required.
- [ ] Duplicate channel IDs do not produce duplicate parsed subscriptions.
- [ ] Malformed rows produce warnings, not parser failure.

## Blocked By

- T04 Parser dispatch and contracts.

## Handoff Notes

This ticket is important for the product goal because subscriptions are the
clearest usage metric beyond watch history.

