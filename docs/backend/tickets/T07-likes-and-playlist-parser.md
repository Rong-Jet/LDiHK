# T07: Likes And Playlist Parser

## Type

AFK.

## Objective

Parse liked videos and simple playlist/watch-later usage signals from YouTube
Takeout into normalized usage events.

## Parallelization

Start after T04 parser contracts exist. This is independent of watch history,
subscriptions, and duration enrichment.

Owned files:

- `backend/ingestion/parsers/likes_playlists.py`
- `backend/tests/test_likes_playlists_parser.py`
- likes/playlist fixtures under `backend/tests/fixtures/` if needed

Avoid editing:

- Watch-history parser.
- Subscription parser.
- Query API.

## What To Build

Support likely files:

```text
YouTube and YouTube Music/playlists/likes.json
YouTube and YouTube Music/playlists/*.json
```

Focus the MVP on:

- liked videos as `event_type = 'like'`
- watch-later/playlist entries as `watch_later_add` or `playlist_add` when the
  file shape is straightforward

Skip complex playlist ownership/creator semantics.

## TDD Plan

1. RED: parser emits a `like` event with video ID from `likes.json`. GREEN: add
   likes parser.
2. RED: parser handles missing timestamps. GREEN: allow `occurred_at = None`
   and stable fingerprint fields.
3. RED: parser emits `watch_later_add` for a simple watch-later fixture. GREEN:
   add playlist branch.
4. RED: malformed entries become warnings. GREEN: add warning handling.

## Acceptance Criteria

- [ ] Likes produce `like` usage events.
- [ ] Video IDs are extracted where available.
- [ ] Missing timestamps do not fail the parser.
- [ ] Simple playlist/watch-later entries produce usage events where available.
- [ ] Parser does not import uploads or creator-side playlist metadata.

## Blocked By

- T04 Parser dispatch and contracts.

## Handoff Notes

If playlist file shapes are too inconsistent, keep the MVP to `likes.json` and
document watch-later as deferred.

