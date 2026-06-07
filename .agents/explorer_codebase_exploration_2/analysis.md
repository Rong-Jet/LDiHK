# System Architecture Report: LDiHK Backend Exploration

This report provides a detailed, comprehensive analysis of the LDiHK (Life Data Integration & Health Kernel) backend system architecture, database schema, data pipelines, wellness computation engine, and security/authentication protocols, as extracted from the repository codebase.

---

## 1. API Endpoint Inventory (Flask & Astro)

The application utilizes a two-tier API architecture:
1. **Python Flask Backend**: Serves as the database abstraction and analytics processing engine.
2. **Astro SSR Frontend API Routes**: Serves as a gateway, providing mock data or AWS S3 pre-signed URL generation depending on configuration.

### A. Python Flask Backend Endpoints
Implemented primarily in `backend/app.py`, `backend/imports_api.py`, and `backend/query_api.py`.

#### 1. `GET /health`
* **Purpose**: Health check endpoint.
* **Authentication**: None.
* **Payload / Parameters**: None.
* **Response Structure**:
  ```json
  {"status": "ok"}
  ```

#### 2. `POST /api/query`
* **Purpose**: Executes structured analytics queries over the PostgreSQL database for the authenticated user.
* **Authentication**: Required (`require_bearer_identity`). Validates the Bearer Token and extracts the `ldihk_id`.
* **Payload scoping**: If the input payload contains `ldihk_id`, `user_id`, or `person_id`, the endpoint rejects it with a `400 Bad Request` to prevent request tampering.
* **Input Payload (`youtube_usage.structured_query.v1`)**:
  ```json
  {
    "dataset": "youtube_usage",
    "metrics": ["event_count", "estimated_watch_seconds"],
    "dimensions": ["date", "hour"],
    "filters": {
      "start_date": "2026-05-08",
      "end_date": "2026-06-06",
      "event_type": "watch",
      "product": "youtube"
    },
    "options": {
      "include_zero_buckets": true,
      "limit": 1000
    }
  }
  ```
* **Response Structure**:
  ```json
  {
    "schema_version": "youtube_usage.structured_query.v1",
    "dataset": "youtube_usage",
    "ldihk_id": "string",
    "duration_strategy": {
      "kind": "api_user_average_global_default",
      "api_duration_source": "youtube_data_api",
      "user_average_source": "event_weighted_user_average",
      "global_default_seconds": 600
    },
    "query": {
      "metrics": ["string"],
      "dimensions": ["string"],
      "filters": { ... },
      "options": { ... }
    },
    "quality": {
      "events_counted": 240,
      "events_with_api_duration": 180,
      "events_with_user_average_estimate": 40,
      "events_with_global_default_estimate": 20,
      "videos_unavailable": 15,
      "videos_capped": 5
    },
    "rows": [
      {
        "date": "2026-06-01",
        "hour": 14,
        "event_count": 12,
        "estimated_watch_seconds": 7200
      }
    ]
  }
  ```

#### 3. `POST /api/imports`
* **Purpose**: Registers a completed S3 upload for processing.
* **Authentication**: Required (`require_bearer_identity`).
* **Input Payload**:
  ```json
  {
    "s3_bucket": "my-s3-bucket",
    "s3_key": "uploads/<ldihk_id>/takeout-2026.zip",
    "s3_etag": "optional-etag-string"
  }
  ```
* **Validation & Scoping**:
  * Asserts `s3_key` ends in `.zip` (case-insensitive).
  * Asserts `s3_key` begins with `uploads/<ldihk_id>/` to prevent directory traversal and cross-user data access.
  * Asserts `s3_bucket` matches the server's configured environment variable.
* **Response Structure**: Status 201 Created.
  ```json
  {
    "import_id": "uuid-string",
    "ldihk_id": "string",
    "status": "queued"
  }
  ```

#### 4. `GET /api/imports/<import_id>`
* **Purpose**: Polls import job status and metrics.
* **Authentication**: Required (`require_bearer_identity`).
* **Response Structure**:
  ```json
  {
    "import_id": "uuid-string",
    "ldihk_id": "string",
    "status": "completed", // queued, running, completed, failed
    "records_seen": 240,
    "records_imported": 238,
    "warnings_count": 2,
    "error_message": null,
    "created_at": "2026-06-07T05:24:39Z",
    "started_at": "2026-06-07T05:24:41Z",
    "finished_at": "2026-06-07T05:24:44Z"
  }
  ```

#### 5. `GET /api/users/local_user/youtube-usage` & `GET /api/v2/users/local_user/youtube-usage/temporal`
* **Purpose**: Legacy v1/v2 endpoints reading preprocessed SQLite files or JSON output for `local_user`.
* **Authentication**: None.

---

### B. Astro Frontend API Routes
Implemented in `Frontend/src/pages/api/`.

#### 1. `POST /api/upload-url`
* **Purpose**: Generates an S3 pre-signed URL for direct browser-to-S3 ZIP file uploads.
* **Authentication**: Required (checks standard Bearer header).
* **Payload**:
  ```json
  {
    "filename": "takeout.zip",
    "contentType": "application/zip"
  }
  ```
* **Flow**:
  * If AWS credentials (`CUSTOM_AWS_ACCESS_KEY_ID`, `CUSTOM_AWS_SECRET_ACCESS_KEY`, `CUSTOM_AWS_REGION`, and `S3_BUCKET`) are present, generates a valid AWS S3 pre-signed `PUT` URL with a 15-minute expiration.
  * If `PUBLIC_MOCK_API` is set to `true`, returns a fallback mock URL pointing to `/api/mock-s3-upload` with custom metadata headers.

#### 2. `GET /api/uploader-info`
* **Purpose**: Informs the client whether it is running in S3 live upload mode or mock mode.
* **Response**: `{"isMock": true}` or `{"isMock": false}`.

#### 3. `PUT /api/mock-s3-upload`
* **Purpose**: Consumes and drains the request body stream to simulate file upload in mock mode.

#### 4. `POST /api/query` (Mock Mode)
* **Purpose**: Generates deterministic mock timeseries dataset for the requested user when `PUBLIC_MOCK_API=true`.

---

## 2. PostgreSQL Database Schema

The database schema is defined in `backend/migrations/001_youtube_imports.sql` and managed using the custom migrations runner in `backend/db.py`.

```
                  +------------------------+
                  |         users          |
                  +------------------------+
                  | id (UUID) [PK]         |
                  | external_id (TEXT)[UK] |
                  | created_at (TZ)        |
                  +-----------+------------+
                              |
                              | 1
                              |
                              | 0..*
                  +-----------v------------+
                  |        imports         |
                  +------------------------+
                  | id (UUID) [PK]         |
+---------------->| user_id (UUID) [FK]    |
|                 | s3_bucket (TEXT)       |
|                 | s3_key (TEXT)          |
|                 | s3_etag (TEXT)         |
|                 | status (TEXT)          |
|                 | started_at (TZ)        |
|                 | finished_at (TZ)       |
|                 | records_seen (INT)     |
|                 | records_imported (INT) |
|                 | warnings_count (INT)   |
|                 | error_message (TEXT)   |
|                 | created_at (TZ)        |
|                 +-----------+------------+
|                             |
|                             | 1
|                             |
|                             | 0..*
|                 +-----------v------------+
|                 |      source_files      |
|                 +------------------------+
|                 | id (UUID) [PK]         |
|   +------------>| import_id (UUID) [FK]  |
|   |             | path (TEXT)            |
|   |             | sha256 (TEXT)          |
|   |             | parser_name (TEXT)     |
|   |             | status (TEXT)          |
|   |             | records_seen (INT)     |
|   |             | records_imported (INT) |
|   |             | warnings_count (INT)   |
|   |             | UNIQUE (import_id,path)|
|   |             +-----------+------------+
|   |                         |
|   |                         | 1
|   |                         |
|   |                         | 0..*
|   |   +---------------------+-----------------+
|   |   |                                       |
|   |   | 0..*                                  | 0..*
| +-v---v----------------+             +--------v---------------+
| |     usage_events     |             |    import_warnings     |
| +----------------------+             +------------------------+
| | id (UUID) [PK]       |             | id (UUID) [PK]         |
| | user_id (UUID) [FK]  |             | import_id (UUID) [FK]  |
| | import_id (UUID) [FK]|             | source_file_id [FK]    |
| | source_file_id [FK]  |             | code (TEXT)            |
| | platform (TEXT)      |             | count (INT)            |
| | product (TEXT)       |             | sample_hash (TEXT)     |
| | event_type (TEXT)    |             +------------------------+
| | occurred_at (TZ)     |
| | video_id (TEXT)      |
| | channel_id (TEXT)    |
| | title_hash (TEXT)    |
| | search_query_hash    |
| | raw_status (TEXT)    |
| | event_fingerprint    |
| | created_at (TZ)      |
| | UNIQUE(user_id,      |
| |   event_fingerprint) |
| +----------------------+
```

### Table Definitions & Constraints

#### 1. `users`
* Represents system users identified by an external LDiHK ID.
* Columns:
  * `id` `UUID` `PRIMARY KEY`
  * `external_id` `TEXT` `UNIQUE` `NOT NULL`
  * `created_at` `TIMESTAMPTZ` `NOT NULL DEFAULT now()`

#### 2. `imports`
* Tracks ZIP archive ingestion lifecycle.
* Columns:
  * `id` `UUID` `PRIMARY KEY`
  * `user_id` `UUID` `NOT NULL` `REFERENCES users(id)`
  * `s3_bucket` `TEXT` `NOT NULL`
  * `s3_key` `TEXT` `NOT NULL`
  * `s3_etag` `TEXT`
  * `status` `TEXT` `NOT NULL` (values: `queued`, `running`, `completed`, `failed`)
  * `started_at` `TIMESTAMPTZ`
  * `finished_at` `TIMESTAMPTZ`
  * `records_seen` `INTEGER` `NOT NULL DEFAULT 0`
  * `records_imported` `INTEGER` `NOT NULL DEFAULT 0`
  * `warnings_count` `INTEGER` `NOT NULL DEFAULT 0`
  * `error_message` `TEXT`
  * `created_at` `TIMESTAMPTZ` `NOT NULL DEFAULT now()`

#### 3. `source_files`
* Represents individual files extracted from the Takeout ZIP.
* Columns:
  * `id` `UUID` `PRIMARY KEY`
  * `import_id` `UUID` `NOT NULL` `REFERENCES imports(id)`
  * `path` `TEXT` `NOT NULL`
  * `sha256` `TEXT` `NOT NULL`
  * `parser_name` `TEXT`
  * `status` `TEXT` `NOT NULL` (values: `running`, `completed`, `failed`)
  * `records_seen` `INTEGER` `NOT NULL DEFAULT 0`
  * `records_imported` `INTEGER` `NOT NULL DEFAULT 0`
  * `warnings_count` `INTEGER` `NOT NULL DEFAULT 0`
  * `UNIQUE (import_id, path)`

#### 4. `usage_events`
* Log entries of user interaction with platforms.
* Columns:
  * `id` `UUID` `PRIMARY KEY`
  * `user_id` `UUID` `NOT NULL` `REFERENCES users(id)`
  * `import_id` `UUID` `NOT NULL` `REFERENCES imports(id)`
  * `source_file_id` `UUID` `REFERENCES source_files(id)`
  * `platform` `TEXT` `NOT NULL` (e.g., `youtube`)
  * `product` `TEXT` `NOT NULL` (e.g., `youtube`, `youtube_music`)
  * `event_type` `TEXT` `NOT NULL` (e.g., `watch`, `search`, `like`, `comment`, `live_chat`)
  * `occurred_at` `TIMESTAMPTZ`
  * `video_id` `TEXT` (11-character YouTube video identifier)
  * `channel_id` `TEXT` (24-character YouTube channel identifier)
  * `title_hash` `TEXT` (SHA256 privacy-hashed video title)
  * `search_query_hash` `TEXT` (SHA256 privacy-hashed search query)
  * `raw_status` `TEXT` (e.g., `private`, `deleted`, `unavailable`, `malformed`)
  * `event_fingerprint` `TEXT` `NOT NULL`
  * `created_at` `TIMESTAMPTZ` `NOT NULL DEFAULT now()`
  * `UNIQUE (user_id, event_fingerprint)`

#### 5. `subscriptions`
* Channels the user is subscribed to.
* Columns:
  * `id` `UUID` `PRIMARY KEY`
  * `user_id` `UUID` `NOT NULL` `REFERENCES users(id)`
  * `import_id` `UUID` `NOT NULL` `REFERENCES imports(id)`
  * `channel_id` `TEXT` `NOT NULL`
  * `channel_url` `TEXT`
  * `channel_title_hash` `TEXT` (SHA256 privacy-hashed channel title)
  * `source_path` `TEXT`
  * `created_at` `TIMESTAMPTZ` `NOT NULL DEFAULT now()`
  * `UNIQUE (user_id, channel_id)`

#### 6. `youtube_videos`
* Cached video metadata and duration fetched from the YouTube Data API.
* Columns:
  * `video_id` `TEXT` `PRIMARY KEY`
  * `channel_id` `TEXT`
  * `duration_seconds` `INTEGER`
  * `duration_source` `TEXT`
  * `availability_status` `TEXT` `NOT NULL` (values: `available`, `deleted_or_unavailable`, `private_or_restricted`, `api_error`, `duration_parse_failed`)
  * `max_duration_applied` `BOOLEAN` `NOT NULL DEFAULT false`
  * `fetched_at` `TIMESTAMPTZ`
  * `attempt_count` `INTEGER` `NOT NULL DEFAULT 0`
  * `last_error` `TEXT`

#### 7. `youtube_channels`
* Cached YouTube channel metadata.
* Columns:
  * `channel_id` `TEXT` `PRIMARY KEY`
  * `title_hash` `TEXT`
  * `fetched_at` `TIMESTAMPTZ`
  * `attempt_count` `INTEGER` `NOT NULL DEFAULT 0`
  * `last_error` `TEXT`

#### 8. `enrichment_jobs`
* Tracks background asynchronous video metadata enrichment tasks.
* Columns:
  * `id` `UUID` `PRIMARY KEY`
  * `job_type` `TEXT` `NOT NULL` (e.g., `youtube_video_durations`)
  * `status` `TEXT` `NOT NULL` (values: `queued`, `running`, `completed`, `failed`)
  * `payload_json` `JSONB` `NOT NULL` (contains lists of `video_ids` to enrich)
  * `attempts` `INTEGER` `NOT NULL DEFAULT 0`
  * `run_after` `TIMESTAMPTZ` `NOT NULL DEFAULT now()`
  * `started_at` `TIMESTAMPTZ`
  * `finished_at` `TIMESTAMPTZ`
  * `error_message` `TEXT`
  * `created_at` `TIMESTAMPTZ` `NOT NULL DEFAULT now()`

#### 9. `import_warnings`
* Log of warnings generated during parser execution.
* Columns:
  * `id` `UUID` `PRIMARY KEY`
  * `import_id` `UUID` `NOT NULL` `REFERENCES imports(id)`
  * `source_file_id` `UUID` `REFERENCES source_files(id)`
  * `code` `TEXT` `NOT NULL`
  * `count` `INTEGER` `NOT NULL`
  * `sample_hash` `TEXT`

### Indexes
* `idx_usage_events_user_time`: on `usage_events(user_id, occurred_at)` (crucial for date-bounded aggregates)
* `idx_usage_events_user_type_time`: on `usage_events(user_id, event_type, occurred_at)` (optimizes filtration on watches/searches)
* `idx_usage_events_video_id` / `idx_usage_events_channel_id`: on `usage_events(video_id)` and `(channel_id)` (optimizes enrichment collection joins)
* `idx_imports_status`: on `imports(status, created_at)`
* `idx_enrichment_jobs_status`: on `enrichment_jobs(status, run_after)`

---

## 3. Data Ingestion Pipeline

### Step 1: ZIP Upload Initiation
1. The frontend `UploadZone.tsx` handles file drop events.
2. The UI sends a `POST /api/upload-url` request containing the filename and content type, scoped under the user's token.
3. The Astro SSR server returns a pre-signed S3 URL pointing to `uploads/<ldihk_id>/<filename>`.
4. The frontend performs a direct HTTP `PUT` upload of the ZIP file to the pre-signed URL.

### Step 2: Import Registration
1. Once S3 upload succeeds, the frontend makes a `POST /api/imports` request to the Flask backend with details: `{ s3_bucket, s3_key, s3_etag }`.
2. The backend creates an import record in the `imports` table with state `queued`.

### Step 3: Background Worker Processing (`backend/ingestion/worker.py`)
1. **Job Claiming**:
   The worker runs in a loop. It executes a database transaction to claim a job:
   ```sql
   SELECT id, user_id, s3_bucket, s3_key, s3_etag
   FROM imports
   WHERE status = 'queued'
   ORDER BY created_at
   FOR UPDATE SKIP LOCKED
   LIMIT 1
   ```
   * *Concurrency Protection*: `FOR UPDATE SKIP LOCKED` guarantees multiple worker processes can query the table concurrently without locking or picking the same job.
   * If a job is returned, the worker updates its status to `running` and commits, releasing the lock.
2. **Download & Safety Extraction**:
   * Downloads the ZIP file into a `TemporaryDirectory` from S3.
   * Safe extraction is enforced by `iter_safe_zip_members` in `zip_safety.py`. Path traversal mitigations include:
     * Raising `UnsafeZipEntryError` if the filename contains null bytes (`\x00`).
     * Rejecting absolute paths (`/`) or drive-qualified paths (`C:`).
     * Normalizing backslashes to forward slashes and splitting parts. If any component is `..`, it throws an error immediately to prevent files from being written outside the temp folder.
3. **Dispatch & Parsing**:
   * Each file path is matched against `DISPATCH_TABLE` (defined in `dispatch.py`) using glob routing patterns.
   * If matched, the appropriate parser module is resolved and called with the file bytes.
   * All extracted titles and search queries are hashed using SHA256 combined with a site-wide salt for privacy shielding. Unique event fingerprints are computed via `event_fingerprint` to prevent duplicate writes (`ON CONFLICT DO NOTHING`).
4. **Persistence**:
   * Results are persisted in transactions: events are inserted into `usage_events`, subscriptions are upserted into `subscriptions`, and warnings are captured in `import_warnings`.
   * Once all members are processed, the import status is marked `completed`, and a metadata enrichment job is automatically queued in `enrichment_jobs`.

### Summary of Parsers

| Parser Name | Glob Path Pattern | Target Table | Hashing / Privacy Measures |
| :--- | :--- | :--- | :--- |
| `watch_history` | `watch-history.html`, `watch-history.json` | `usage_events` (type: `watch`) | SHA256 privacy-hashed video title and search query. |
| `search_history` | `search-history.json`, `my activity/youtube/myactivity.json` | `usage_events` (type: `search`) | SHA256 privacy-hashed query. |
| `subscriptions` | `subscriptions.csv`, `subscriptions.json` | `subscriptions` | SHA256 privacy-hashed channel title. |
| `likes_playlists` | `likes.json`, `playlists/*.json` | `usage_events` (type: `like`, `watch_later_add`, `playlist_add`) | SHA256 privacy-hashed video title. Ignores uploads/creator playlists. |
| `comments_live_chat` | `comments.csv`, `live chats.csv`, `my-comments/*.html`, `my-live-chat-messages/*.html` | `usage_events` (type: `comment`, `live_chat`) | Hashing of comment/chat content. |

---

## 4. Enrichment Pipeline

### Step 1: Gathering Video IDs
* When an import completes, the worker scans all watch events imported during that run:
  ```sql
  SELECT DISTINCT video_id FROM usage_events
  WHERE import_id = %s AND platform = 'youtube' AND product = 'youtube' AND event_type = 'watch' AND video_id IS NOT NULL
  ```
* These video IDs are wrapped in a JSON payload and queued in `enrichment_jobs` with `job_type = 'youtube_video_durations'`.

### Step 2: Worker Processing (`backend/enrichment/durations.py`)
1. **Job Claiming**:
   Similar to the ingestion worker, `YoutubeDurationEnrichmentWorker` claims jobs using `FOR UPDATE SKIP LOCKED` on the `enrichment_jobs` table.
2. **YouTube Data API Queries**:
   * For each claimed job, the worker queries the YouTube Data API in batches of up to 50 video IDs via `client.list_videos(video_ids)` (utilizing `urllib.request.urlopen` against `https://www.googleapis.com/youtube/v3/videos`).
   * It extracts the ISO 8601 duration string (e.g. `PT2M30S`) and parses it into seconds using a regular expression:
     `P(?:(?P<weeks>\d+)W)?(?:(?P<days>\d+)D)?(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?)?`.
3. **Capping & Database Update**:
   * Valid durations are capped at `DEFAULT_MAX_DURATION_SECONDS` (5400 seconds, or 90 minutes) to prevent outlier views from distorting aggregate scores. If capped, `max_duration_applied` is set to `true`.
   * Video status is updated in the `youtube_videos` table with availability status `available`.
   * If a video is deleted, private, or not returned, it is marked as `deleted_or_unavailable` or `private_or_restricted`.
4. **Retry Mechanism & Backoff**:
   * If the API call fails (e.g., rate limits or network issues), the worker records `api_error` for the batch.
   * The job is failed, and the run schedule `run_after` is set with an exponential backoff time:
     `run_after = now() + retry_base_seconds * (2 ** attempts)`.

---

## 5. Wellness Engine & Biomarkers

The wellness metrics are calculated dynamically over the hourly aggregate results returned by the backend.

### A. Dynamic Duration Estimation Strategy
When watching a video, the watch duration is calculated using a hierarchical fallback strategy:
1. **API Duration**: If the video is available and cached in the `youtube_videos` table, uses the exact `duration_seconds`.
2. **User Average Duration**: If the video is not available, falls back to the user's average watch duration of all their available videos, calculated dynamically via the `user_duration_stats` CTE:
   ```sql
   AVG(youtube_videos.duration_seconds)::numeric AS avg_api_duration_seconds
   ```
3. **Global Default Duration**: If the user has no available videos with durations, falls back to a default parameter (defaults to 600 seconds, or 10 minutes).

This hierarchy is constructed in the `event_rows` CTE:
```sql
CASE
    WHEN yv.availability_status = 'available' AND yv.duration_seconds IS NOT NULL THEN yv.duration_seconds::numeric
    WHEN uds.avg_api_duration_seconds IS NOT NULL THEN uds.avg_api_duration_seconds
    ELSE %s::numeric -- Global default duration (600s)
END AS estimated_duration_seconds
```

---

### B. Mathematical and SQL Definitions of Biomarkers

Let $h$ represent an hourly bucket $(d, h)$ where $d$ is a date, $hour \in \{0, \dots, 23\}$ is the hour of the day, and $e_h$ is the sum of `estimated_duration_seconds` for all watch events during that hour.

#### 1. Volume ($V_t$)
* **Concept**: The total estimated watch time in hours for day $t$.
* **Mathematical Definition**:
  $$V_t = \frac{\sum_{h \in \text{day } t} e_h}{3600}$$
* **PostgreSQL Aggregation Query**:
  ```sql
  SELECT
    to_char(ue.occurred_at AT TIME ZONE 'UTC', 'YYYY-MM-DD') AS date,
    COALESCE(ROUND(SUM(estimated_duration_seconds) FILTER (WHERE metric_event_type = 'watch'))::bigint, 0) AS estimated_watch_seconds
  FROM event_rows
  GROUP BY date;
  ```
  *(The hours are then divided by 3600 in the frontend to compute $V_t$)*.

#### 2. Sleep Delay / Late-Night Watch ($C_t$)
* **Concept**: The total watch time in hours occurring during late-night hours (23:00 to 04:59 UTC/local).
* **Mathematical Definition**:
  $$C_t = \frac{\sum_{h \in \text{day } t, \text{ hour} \in \{23, 0, 1, 2, 3, 4\}} e_h}{3600}$$
* **PostgreSQL / Frontend Definition**:
  The backend aggregates watch seconds per hour. The frontend filters and aggregates late-night hours:
  ```javascript
  let ytLateNightSeconds = 0;
  hoursData.forEach(h => {
    if (h.hour >= 23 || h.hour <= 4) {
      ytLateNightSeconds += h.estimated_watch_seconds;
    }
  });
  const ytLateNightHours = ytLateNightSeconds / 3600;
  ```

#### 3. Fragmentation ($F_t$)
* **Concept**: The proportion of active hours in a 24-hour day. An hour is considered active if estimated watch time is $\geq 5\text{ minutes}$ (300 seconds).
* **Mathematical Definition**:
  $$F_t = \frac{\sum_{h \in \text{day } t} \mathbb{I}(e_h \geq 300)}{24}$$
  *(where $\mathbb{I}(\cdot)$ is the indicator function)*.
* **PostgreSQL / Frontend Definition**:
  The backend returns hourly aggregates. The frontend counts active hours:
  ```javascript
  let activeHoursCount = 0;
  hoursData.forEach(h => {
    if (h.estimated_watch_seconds >= 300) {
      activeHoursCount++;
    }
  });
  const fragmentationIndex = activeHoursCount / 24;
  ```

---

### C. Backend to Frontend Risk Integration

1. **API Handshake**:
   The frontend component `RiskDashboardContainer.tsx` calls `POST /api/query` requesting metrics `['event_count', 'estimated_watch_seconds']` and dimensions `['date', 'hour']` over a given date range.
2. **Hourly-Daily Alignment**:
   * Because `include_zero_buckets: true` is requested, the backend fills missing hourly records so that every day in the sequence has exactly 24 records (one for each hour, 0 to 23).
   * This is done by the backend's `_zero_fill_rows` helper.
3. **Risk Probability (Z-Score)**:
   The frontend aggregates the hourly records to calculate daily $V_t, C_t, F_t$. It then calculates a Z-score risk factor:
   $$z = -2.1 + (0.35 \times V_t) + (0.80 \times F_t) + (1.20 \times C_t)$$
   The risk probability is computed using a logistic sigmoid function:
   $$P(\text{risk}) = \sigma(z) = \frac{1}{1 + e^{-z}}$$
   This logic is implemented in `RiskDashboardContainer.tsx` at line 428.
4. **Visual Mapping**:
   * The calculated risk percentage (`riskScorePercent = riskProbability * 100`) is mapped to risk categories (e.g. Low, Moderate, High, Severe) on the dashboard charts and widgets.
   * Trend classifications (e.g., Strongly Upward, Weakly Downward, Stable) are evaluated by comparing the average risk of the current 7-day period against the previous 7-day period.

---

## 6. Authentication & Request Scoping

1. **Bearer Token Validation**:
   * The HTTP boundary `backend/http_boundary.py` implements the helper decorator `@require_bearer_identity`.
   * It expects an `Authorization: Bearer <LDiHKID>` header.
   * The token is directly treated as the unique `ldihk_id` representing the user.
2. **User Data Scoping**:
   * To prevent Cross-User Data Access (IDOR), the backend overrides any user filter parameter in request payloads with the validated `ldihk_id` via `query_request_for_ldihk_id`.
   * In SQL, queries filter strictly by `u.external_id = %s`, where the parameter is the verified Bearer token (`ldihk_id`):
     ```sql
     WHERE u.external_id = %s
     ```
   * S3 import operations validate that `s3_key` prefix matches the user's `uploads/<ldihk_id>/` folder. This guarantees that a user cannot register or process files uploaded by other users.
