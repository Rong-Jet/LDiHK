# Backend Data Processing Pipeline

## Version History

Backend versions are tracked as user-story-style Markdown tickets in
`docs/backend/versions/`.

- [Version story structure](backend/versions/README.md)
- [v1: YouTube Usage Pipeline And Read-Only API](backend/versions/v1-youtube-usage-pipeline-api.md)

## Scope

This document defines the v1 backend pipeline for processing a single person's YouTube usage data from a local Google Takeout export.

v1 is intentionally narrow:

- Platform: YouTube and YouTube Music only.
- Input: local Google Takeout HTML in `data/watch-history.html`.
- User model: one pseudonymous user, default `person_id = "local_user"`.
- Output: one privacy-minimized JSON file for frontend consumption.
- Hosting: Flask serves the processed JSON read-only.
- Duration: not calculated in v1; documented for later enrichment.

Instagram, TikTok, Douyin, multi-person ingestion, SQL persistence, AI enrichment, uploads, and live API ingestion are out of scope for v1.

## Local Source Findings

The current input file is:

```text
data/watch-history.html
```

Observed structure:

- `49,900` activity cards.
- `28,484` `YouTube` records.
- `21,416` `YouTube Music` records.
- `47,862` `Watched` records.
- `2,038` `Viewed` records, mostly YouTube post/community-style usage.
- Every record has a local timestamp in the form `D Mon YYYY, HH:MM:SS TZ`.
- The file uses `CEST`; parsing should still preserve and normalize the timezone rather than assume UTC.
- The month token `Sept` appears, so parsing must not rely only on Python's default `%b` handling.

Reliably extractable fields:

- Product: `YouTube` or `YouTube Music`.
- Event type: `Watched` or `Viewed`.
- Timestamp string and parsed local datetime.
- Primary link/video/post URL when present.
- Channel name/link when present.
- Google activity details link when present.

Fields not present or not reliable in the HTML:

- Actual watch duration.
- Completion percentage.
- Device.
- Location.
- Playlist context.
- Recommendation source.
- Account identity.

## Pipeline Overview

v1 follows the preprocessing portion of the technical diagram, shortened for a single-person local batch pipeline:

```text
data/watch-history.html
  -> parse Google Takeout HTML
  -> normalize privacy-minimized usage events
  -> validate records and collect anonymized quality warnings
  -> compute basic local-time aggregates
  -> write data/processed/users/local_user/youtube_usage.v1.json
  -> serve JSON through read-only Flask endpoint
```

The raw HTML is never served by Flask.

## File Layout

Recommended v1 files:

```text
backend/scripts/process_youtube_usage.py
backend/app.py
data/watch-history.html
data/processed/users/local_user/youtube_usage.v1.json
backend.md
```

The processed JSON is the lightweight per-user database for v1:

```text
data/processed/users/local_user/youtube_usage.v1.json
```

SQL can be introduced later after the frontend contract and metrics stabilize.

## Processing Contract

The batch script should:

1. Read `data/watch-history.html`.
2. Parse cards using an HTML parser, preferably `beautifulsoup4` with `lxml`.
3. Extract event metadata without depending on video titles, channel names, or content-specific text.
4. Normalize products and event types:
   - `YouTube` -> `youtube`
   - `YouTube Music` -> `youtube_music`
   - `Watched` -> `watched`
   - `Viewed` -> `viewed`
5. Parse timestamps in local time using `Europe/Berlin` as the default timezone.
6. Emit ISO timestamps with offsets.
7. Strip title, URL, channel, and video ID from the frontend JSON.
8. Skip malformed records rather than failing the whole run.
9. Record anonymized quality warnings with counts only.
10. Write the v1 JSON artifact.

The parser may temporarily inspect links and titles for validation/classification, but those fields must not be emitted in v1 frontend JSON.

## Event Schema

Each emitted event should follow this shape:

```json
{
  "person_id": "local_user",
  "platform": "youtube",
  "product": "youtube_music",
  "event_type": "watched",
  "watched_at": "2026-06-06T08:53:12+02:00",
  "duration_seconds": null
}
```

Notes:

- `duration_seconds` is always `null` in v1.
- `watched_at` is the normalized event timestamp, even for `viewed` events.
- `product` distinguishes YouTube from YouTube Music.
- `event_type` distinguishes video/music watches from post/community views.

## Top-Level JSON Schema

The generated file should follow this contract:

```json
{
  "schema_version": "youtube_usage.v1",
  "person_id": "local_user",
  "generated_at": "2026-06-06T00:00:00+02:00",
  "source": {
    "platform": "youtube",
    "input_path": "data/watch-history.html",
    "input_format": "google_takeout_html",
    "timezone": "Europe/Berlin"
  },
  "quality": {
    "records_seen": 49900,
    "records_emitted": 49900,
    "records_rejected": 0,
    "warnings": []
  },
  "events": [],
  "aggregates": {
    "by_day": [],
    "by_hour_of_day": [],
    "by_weekday": []
  },
  "future_fields": {
    "duration_seconds": "null in v1; reserved for later enrichment or estimation"
  }
}
```

`generated_at` should be the actual pipeline run time.

## Aggregates

Aggregates are convenience output for the frontend. Raw content-free events remain canonical.

Aggregates use local time and are split by `product` and `event_type`.

```json
{
  "by_day": [
    {
      "date": "2026-06-06",
      "product": "youtube_music",
      "event_type": "watched",
      "event_count": 42,
      "duration_seconds": null
    }
  ],
  "by_hour_of_day": [
    {
      "hour": 8,
      "product": "youtube",
      "event_type": "viewed",
      "event_count": 3,
      "duration_seconds": null
    }
  ],
  "by_weekday": [
    {
      "weekday": 6,
      "weekday_name": "Saturday",
      "product": "youtube",
      "event_type": "watched",
      "event_count": 120,
      "duration_seconds": null
    }
  ]
}
```

Weekday numbering should use ISO weekday semantics:

- `1` = Monday
- `7` = Sunday

## Validation And Quality Reporting

The pipeline should fail soft per malformed record.

Example quality block:

```json
{
  "quality": {
    "records_seen": 49900,
    "records_emitted": 49894,
    "records_rejected": 6,
    "warnings": [
      {
        "code": "missing_timestamp",
        "count": 6
      }
    ]
  }
}
```

Warnings must not include titles, URLs, channel names, or any other content-specific personal data.

Suggested warning codes:

- `missing_product`
- `unknown_product`
- `missing_event_type`
- `unknown_event_type`
- `missing_timestamp`
- `timestamp_parse_failed`
- `malformed_card`

## Flask Hosting

Flask is read-only in v1.

Recommended endpoints:

```text
GET /health
GET /api/users/local_user/youtube-usage
```

`GET /api/users/local_user/youtube-usage` reads only:

```text
data/processed/users/local_user/youtube_usage.v1.json
```

Flask must never read raw exports such as:

```text
data/watch-history.html
```

If the processed JSON is missing, Flask should return a clear error:

```json
{
  "error": "processed_data_missing",
  "expected_path": "data/processed/users/local_user/youtube_usage.v1.json"
}
```

Recommended status code: `503 Service Unavailable`, because the API exists but the batch artifact has not been generated.

## Duration Strategy

Duration is out of scope for v1 because Google Takeout `watch-history.html` records event timestamps, not actual seconds watched.

Future options:

1. `video_duration_seconds`
   - Enrich video IDs through YouTube Data API or `yt-dlp`.
   - Represents full video length.
   - Does not prove the user watched the full video.

2. `estimated_session_seconds`
   - Infer usage duration from gaps between consecutive events.
   - Requires a cap such as 30 minutes to avoid counting long absences.
   - Useful for temporal usage estimates, but must be labeled as estimated.

3. `event_duration_seconds`
   - True per-event watch duration.
   - Not available from the current HTML export.
   - Should remain `null` unless a future source provides it directly.

Future schema can evolve from:

```json
{
  "duration_seconds": null
}
```

to:

```json
{
  "event_duration_seconds": null,
  "video_duration_seconds": 620,
  "estimated_session_seconds": 300
}
```

## Prior Art

Relevant public implementations and takeaways:

- [purarue/google_takeout_parser](https://github.com/purarue/google_takeout_parser)
  - General Google Takeout parser.
  - Useful references: event model, parser abstraction, caching, merging, deduplication, locale handling.

- [Jessime/youtube_history](https://github.com/Jessime/youtube_history)
  - Parses YouTube Takeout history and enriches metadata with `yt-dlp`.
  - Useful reference: keep watch events separate from video metadata.

- [menggatot/youtube-watch-history-to-csv](https://github.com/menggatot/youtube-watch-history-to-csv)
  - Converts YouTube Takeout HTML to CSV for scrobbling.
  - Useful reference: resumable enrichment/progress pattern.
  - Caveat: avoid hard-coded locale/timezone assumptions.

- [Health OS YouTube History integration](https://health-os.app/en/integrations/youtube/)
  - Accepts Takeout HTML/JSON and enriches duration/category later.
  - Useful reference: staged import plus later metadata enrichment.

## Future Expansion

After v1:

- Support `watch-history.json` alongside HTML.
- Add multi-user input and output paths.
- Add SQL persistence once the JSON contract is proven.
- Add YouTube metadata enrichment as a separate cached job.
- Add duration estimates with explicit confidence/limitations.
- Add Instagram, TikTok, and Douyin adapters behind the same normalized usage-event contract.
- Add frontend cache headers and schema-version checks.
- Add tests with anonymized fixture cards for normal, missing-link, missing-channel, `Sept`, `Watched`, and `Viewed` cases.
