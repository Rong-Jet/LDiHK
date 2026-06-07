# v1: YouTube Usage Pipeline And Read-Only API

## Status

Completed on 2026-06-06.

## Summary

v1 implements the first local backend pipeline for a single person's YouTube
usage data. It parses a local Google Takeout HTML export, writes a
privacy-minimized JSON artifact for frontend consumption, and serves that
artifact through a read-only Flask API.

## User Story

As a local dashboard user, I want my YouTube and YouTube Music history converted
into a privacy-minimized structured backend artifact, so that a frontend can
show usage patterns without exposing watched titles, URLs, channels, or video
IDs.

## Feature Set

- Local `uv` Python project with a project `.venv`.
- Batch CLI for processing `data/watch-history.html`.
- HTML parsing for Google Takeout activity cards using Beautiful Soup and lxml.
- Product normalization for YouTube and YouTube Music.
- Event normalization for watched and viewed activity.
- Europe/Berlin local-time timestamp parsing, including `Sept`.
- Privacy-minimized event output with no title, URL, channel, or video ID fields.
- Count-only quality warnings for malformed records.
- Local-time aggregates by day, hour of day, and ISO weekday.
- Read-only Flask endpoint for serving the processed JSON artifact.
- Health endpoint for service checks.

## Public Contract

CLI:

```sh
uv run python backend/scripts/process_youtube_usage.py
```

Default input:

```text
data/watch-history.html
```

Default output:

```text
data/processed/users/local_user/youtube_usage.v1.json
```

Schema version:

```text
youtube_usage.v1
```

API routes:

```text
GET /health
GET /api/users/local_user/youtube-usage
```

Missing processed-data response:

```json
{
  "error": "processed_data_missing",
  "expected_path": "data/processed/users/local_user/youtube_usage.v1.json"
}
```

The usage API returns `503 Service Unavailable` when the processed artifact has
not been generated yet.

## Acceptance Criteria

- [x] The pipeline reads `data/watch-history.html` by default.
- [x] The pipeline writes `data/processed/users/local_user/youtube_usage.v1.json`.
- [x] The output top-level schema includes `schema_version`, `person_id`,
      `generated_at`, `source`, `quality`, `events`, `aggregates`, and
      `future_fields`.
- [x] Every emitted event includes only `person_id`, `platform`, `product`,
      `event_type`, `watched_at`, and `duration_seconds`.
- [x] `duration_seconds` is always `null` in v1.
- [x] YouTube records normalize to `product: "youtube"`.
- [x] YouTube Music records normalize to `product: "youtube_music"`.
- [x] Watched records normalize to `event_type: "watched"`.
- [x] Viewed records normalize to `event_type: "viewed"`.
- [x] Timestamps are emitted as ISO datetimes with local UTC offsets.
- [x] `Sept` timestamps parse successfully.
- [x] Malformed records are skipped without failing the full run.
- [x] Quality warnings contain only anonymized warning codes and counts.
- [x] Output does not include watched titles, URLs, channel names, or video IDs.
- [x] Aggregates are split by `product` and `event_type`.
- [x] Weekday aggregates use ISO weekday numbering, where Monday is `1` and
      Sunday is `7`.
- [x] `GET /health` returns a successful health response.
- [x] `GET /api/users/local_user/youtube-usage` serves only the processed JSON.
- [x] Flask does not serve or read the raw Takeout HTML for API responses.
- [x] Missing processed JSON returns `503` with `processed_data_missing`.

## Verification

Automated tests:

```sh
uv --cache-dir .uv-cache run python -m unittest discover -s backend/tests
```

Pipeline smoke test:

```sh
uv --cache-dir .uv-cache run python backend/scripts/process_youtube_usage.py
```

JSON validation:

```sh
uv --cache-dir .uv-cache run python -m json.tool data/processed/users/local_user/youtube_usage.v1.json /private/tmp/youtube_usage.validated.json
```

API smoke test:

```sh
uv --cache-dir .uv-cache run flask --app backend.app run --port 5055
```

Verified API responses:

```text
GET /health -> 200
GET /api/users/local_user/youtube-usage -> 200
```

Verified real export counts:

```text
records_seen: 49900
records_emitted: 49900
records_rejected: 0
youtube: 28484
youtube_music: 21416
watched: 47862
viewed: 2038
```

## Out Of Scope

- Instagram, TikTok, and Douyin ingestion.
- Multi-person ingestion.
- Uploads or live API ingestion.
- SQL persistence.
- AI enrichment.
- YouTube metadata enrichment.
- Actual watch-duration calculation.
- Session-duration estimation.
- Frontend implementation.

## Notes

The processed JSON is the v1 lightweight database. SQL or additional enrichment
should be introduced only after the frontend contract and metrics stabilize.
