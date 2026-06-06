# T09: Comments And Live Chat Parser

## Type

AFK.

## Objective

Parse YouTube comments and live chat activity from Takeout into privacy-minimized
usage events.

## Parallelization

Start after T04 parser contracts exist. This is independent of watch history,
subscriptions, and duration enrichment.

Owned files:

- `backend/ingestion/parsers/comments_live_chat.py`
- `backend/tests/test_comments_live_chat_parser.py`
- comment/live-chat fixtures under `backend/tests/fixtures/` if needed

Avoid editing:

- Query API.
- Other parser modules.
- DB schema unless a native comment ID column is explicitly needed.

## What To Build

Support likely files:

```text
YouTube and YouTube Music/my-comments/*.html
YouTube and YouTube Music/my-live-chat-messages/*.html
Youtube/comments/comments.csv
Youtube/live chats/live chats.csv
```

Emit:

- `ParsedEvent(event_type='comment')`
- `ParsedEvent(event_type='live_chat')`
- `video_id` when available
- `occurred_at`
- `native_id` when comment/live-chat ID is available

Do not store raw comment text by default.

## TDD Plan

1. RED: parser emits a `comment` event from a CSV fixture. GREEN: add comments
   CSV parsing.
2. RED: parser emits a `live_chat` event from a CSV fixture. GREEN: add live
   chat CSV parsing.
3. RED: native comment IDs are preserved for fingerprinting. GREEN: add
   `native_id`.
4. RED: raw comment text is not required for parsed output. GREEN: omit or keep
   only a hash-ready sample outside persisted SQL.
5. RED: malformed rows produce warnings. GREEN: add warning handling.

## Acceptance Criteria

- [ ] Comment CSV rows emit `comment` events.
- [ ] Live chat CSV rows emit `live_chat` events.
- [ ] Native IDs are used when available.
- [ ] Raw comment/live chat text is not persisted by this parser.
- [ ] Malformed records produce warnings.

## Blocked By

- T04 Parser dispatch and contracts.

## Handoff Notes

The `google_takeout_parser` repo has useful reference behavior for old/new CSV
comment formats. Borrow the behavior, not the entire dependency, unless the
team explicitly chooses to vendor it.

