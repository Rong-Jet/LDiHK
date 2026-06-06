# T08: Search History Parser

## Type

AFK.

## Objective

Parse YouTube-related search history into privacy-minimized search usage events.

## Parallelization

Start after T04 parser contracts exist. This is independent of watch history,
subscriptions, and enrichment.

Owned files:

- `backend/ingestion/parsers/search_history.py`
- `backend/tests/test_search_history_parser.py`
- search fixtures under `backend/tests/fixtures/` if needed

Avoid editing:

- Query API.
- Watch/subscription/likes parsers.

## What To Build

Support YouTube search events from Google/YouTube Takeout activity JSON where
available.

Emit:

- `ParsedEvent(event_type='search')`
- `product = 'youtube'`
- `occurred_at`
- `search_query` for downstream hashing

Search terms are sensitive. The parser can expose `search_query` inside
`ParsedEvent`, but the importer must hash it before SQL storage.

## TDD Plan

1. RED: parser emits a `search` event from a YouTube search activity fixture.
   GREEN: add JSON activity parsing.
2. RED: parser ignores non-YouTube search/activity rows. GREEN: add product/url
   filtering.
3. RED: parser handles missing query text with a warning. GREEN: add warning
   handling.
4. RED: parser does not emit raw non-search content. GREEN: narrow extraction.

## Acceptance Criteria

- [ ] YouTube search activity emits `search` events.
- [ ] Non-YouTube activity is ignored.
- [ ] Missing or malformed query records produce warnings.
- [ ] Parser output is compatible with hashed SQL storage.

## Blocked By

- T04 Parser dispatch and contracts.

## Handoff Notes

This ticket should keep privacy front and center. Do not add raw query storage
to SQL in this ticket.

