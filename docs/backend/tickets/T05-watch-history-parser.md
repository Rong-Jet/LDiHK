# T05: Watch History Parser

## Type

AFK.

## Objective

Parse YouTube Takeout watch history into normalized `watch` usage events for SQL
import.

## Parallelization

Start after T04 parser contracts exist. Can use static fixtures and does not
need the full worker to be complete.

Owned files:

- `backend/ingestion/parsers/watch_history.py`
- `backend/tests/test_watch_history_parser.py`
- watch-history fixtures under `backend/tests/fixtures/` if needed

Avoid editing:

- Worker logic.
- Query API.
- Duration enrichment.
- Subscription/likes/search/comment parsers.

## What To Build

Support:

```text
YouTube and YouTube Music/history/watch-history.html
YouTube and YouTube Music/history/watch-history.json
```

At minimum, parse HTML because the current repo already has
`data/watch-history.html` history around that format.

Emit `ParsedEvent` values:

- `event_type = 'watch'`
- `product = 'youtube'` or `youtube_music`
- `occurred_at`
- `video_id` when present
- `channel_id` when present
- `title` only for hashing by the importer
- `raw_status` for deleted/private/malformed records

Do robust URL parsing with `urllib.parse`, not string splitting.

## TDD Plan

1. RED: parser emits one watch event from a normal HTML activity card. GREEN:
   parse product, timestamp, and video ID.
2. RED: parser handles YouTube Music separately. GREEN: normalize product.
3. RED: parser marks deleted/unavailable/private rows without crashing. GREEN:
   add status handling and warnings.
4. RED: parser extracts video IDs from URLs with extra query parameters. GREEN:
   add robust URL parsing.
5. RED: parser handles JSON watch-history if a fixture exists. GREEN: add JSON
   parser branch.

Each test should call the parser public function and inspect `ParseResult`.

## Acceptance Criteria

- [ ] Normal YouTube watch rows emit `watch` events.
- [ ] YouTube Music rows are distinguishable.
- [ ] Timestamps are parsed into timezone-aware datetimes where possible.
- [ ] Video IDs are extracted robustly.
- [ ] Malformed rows produce warnings instead of full parser failure.
- [ ] Parser does not emit raw HTML.

## Blocked By

- T04 Parser dispatch and contracts.

## Handoff Notes

This parser is the highest-priority usage parser. If time is tight, complete
HTML support before JSON support.

