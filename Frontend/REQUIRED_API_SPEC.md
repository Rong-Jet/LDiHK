# LDiHK Digital Wellness Dashboard: Required API Specification

This specification documents the required backend API endpoints and schema contracts for the **Digital Wellness Assessment Dashboard** to transition from Simulated Data to Live API Data. All endpoints are designed to be realistically achievable and compatible with a relational database (e.g. PostgreSQL/Supabase) populated by parsed YouTube Takeout history logs.

---

## 1. Authentication & Session Scope

All queries use bearer tokens generated upon ZIP ingestion. The backend must extract the anonymous token and map it to a user record.

- **Header Format**: `Authorization: Bearer <LDiHKID>`
- **Scope**: The backend must filter all query requests to only return records belonging to the authenticated user's `user_id`.

---

## 2. Required API Endpoints

### 2.1. Ingestion Status Probe
Checks if the user's dataset is processed and returns the range of dates present in the database. Used to automatically configure start/end bounds for the timeline.

- **Endpoint**: `POST /api/query`
- **Request Body**:
```json
{
  "dataset": "youtube_usage",
  "metrics": ["event_count"],
  "dimensions": ["date"],
  "filters": {
    "start_date": "2015-01-01",
    "end_date": "2026-12-31"
  },
  "options": {
    "include_zero_buckets": false
  }
}
```
- **Expected Response (Success)**:
```json
{
  "schema_version": "youtube_usage.structured_query.v1",
  "dataset": "youtube_usage",
  "ldihk_id": "ldihk-cosmic-pegasus-soaring",
  "rows": [
    { "date": "2026-05-08", "event_count": 42 },
    { "date": "2026-05-09", "event_count": 87 },
    "... (sorted dates list)"
  ]
}
```

---

### 2.2. Granular Multi-Dimensional Query (The Wellness Engine)
Fetches watch/stream duration and frequency grouped by both **date** and **hour**. This enables calculation of daily volume, late-night sleep delays, and daily fragmentation cycles.

- **Endpoint**: `POST /api/query`
- **Request Body**:
```json
{
  "dataset": "youtube_usage", // Can be "youtube_usage", "instagram_usage", "tiktok_usage", or "spotify_usage"
  "metrics": ["event_count", "estimated_watch_seconds"], // "estimated_watch_seconds" represents estimated watch/listen time. For Spotify, "event_count" counts song plays.
  "dimensions": ["date", "hour"],
  "filters": {
    "start_date": "2026-05-08",
    "end_date": "2026-06-06"
  },
  "options": {
    "include_zero_buckets": true,
    "limit": 1000
  }
}
```
- **Expected Response (Success)**:
```json
{
  "schema_version": "youtube_usage.structured_query.v1",
  "dataset": "youtube_usage",
  "ldihk_id": "ldihk-cosmic-pegasus-soaring",
  "rows": [
    {
      "date": "2026-05-08",
      "hour": 0,
      "event_count": 4,
      "estimated_watch_seconds": 1200
    },
    {
      "date": "2026-05-08",
      "hour": 1,
      "event_count": 2,
      "estimated_watch_seconds": 600
    },
    {
      "date": "2026-05-08",
      "hour": 23,
      "event_count": 7,
      "estimated_watch_seconds": 2100
    }
  ]
}
```

### 2.3. Hourly Average Averages Query
Fetches total watch duration and frequency grouped by **hour** across the date range. Used for the hourly heatmap average checks in the Personal dashboard.

- **Endpoint**: `POST /api/query`
- **Request Body**:
```json
{
  "dataset": "youtube_usage",
  "metrics": ["event_count", "estimated_watch_seconds"],
  "dimensions": ["hour"],
  "filters": {
    "start_date": "2026-05-08",
    "end_date": "2026-06-06"
  }
}
```
- **Expected Response (Success)**:
```json
{
  "schema_version": "youtube_usage.structured_query.v1",
  "dataset": "youtube_usage",
  "ldihk_id": "ldihk-cosmic-pegasus-soaring",
  "rows": [
    {
      "hour": 0,
      "event_count": 86,
      "estimated_watch_seconds": 25800
    },
    {
      "hour": 23,
      "event_count": 142,
      "estimated_watch_seconds": 42600
    }
  ]
}
```

---

### 2.4. Population Benchmark Standings Query
Fetches comparative statistics mapping the user's averages against the general cohort for the selected platforms.

- **Endpoint**: `POST /api/population`
- **Request Body**:
```json
{
  "platforms": ["youtube", "instagram", "tiktok", "spotify"],
  "startDate": "2026-05-08",
  "endDate": "2026-06-06",
  "useSyntheticData": true,
  "customPercentile": 90
}
```
- **Expected Response (Success)**:
```json
{
  "ready": true,
  "userPercentile": 73,
  "userDailyAverageHours": 3.12,
  "useSyntheticData": true,
  "customPercentile": 90,
  "distribution": [
    { "hours": 0.0, "density": 15 },
    { "hours": 2.4, "density": 380 }
  ],
  "deciles": [
    {
      "date": "2026-06-01",
      "user": 2.8,
      "median": 2.3,
      "top10": 4.1,
      "bottom10": 0.8,
      "customPercentileHours": 4.1
    }
  ],
  "hourlyAverages": [
    {
      "hour": "00:00",
      "populationAvg": 0.352,
      "userAvg": 0.125
    }
  ]
}
```

---

### 2.5. Upload URL Provisioning
Requests S3 pre-signed upload URL configuration payload.

- **Endpoint**: `POST /api/upload-url`
- **Request Body**:
```json
{
  "filename": "takeout.zip",
  "contentType": "application/zip"
}
```
- **Expected Response (Success)**:
```json
{
  "url": "https://s3-presigned-url-endpoint...",
  "method": "PUT",
  "headers": {
    "Content-Type": "application/zip"
  },
  "isMock": false
}
```

---

### 2.6. Ingest Import Registration
Instructs the backend to queue an import worker task for the uploaded ZIP archive.

- **Endpoint**: `POST /api/imports`
- **Request Body**:
```json
{
  "s3_bucket": "social-dashboard-temp-store-123",
  "s3_key": "uploads/ldihk-cosmic-pegasus-soaring/takeout.zip"
}
```
- **Expected Response (Success)**:
```json
{
  "import_id": "import-job-789-uuid",
  "status": "queued"
}
```

---

### 2.7. Ingest Import Status Check
Polls the extraction progress status for a queued import.

- **Endpoint**: `GET /api/imports/<import_id>`
- **Expected Response (Success)**:
```json
{
  "import_id": "import-job-789-uuid",
  "status": "completed",
  "processed_events": 24050,
  "error": null
}
```

---

### 2.8. Ingest Uploader Info
Retrieves active uploader capabilities configuration.

- **Endpoint**: `GET /api/uploader-info`
- **Expected Response (Success)**:
```json
{
  "isMock": false
}
```

---

## 3. Database Biomarker Mapping (SQL Equivalents)

When the backend executes the structured query above, it must run the following calculations over the relational table schema:

1. **Volume ($V_t$)**: Sum of watch seconds for the day divided by 3600:
   ```sql
   SUM(estimated_watch_seconds) FILTER (WHERE event_type = 'watch') / 3600.0 AS volume_hours
   ```
2. **Sleep Delay ($C_t$)**: Watch hours occurring in the late-night window (23:00 to 05:00 UTC/local depending on tz settings):
   ```sql
   SUM(estimated_watch_seconds) FILTER (WHERE event_type = 'watch' AND hour IN (23, 0, 1, 2, 3, 4)) / 3600.0 AS night_hours
   ```
3. **Fragmentation ($F_t$)**: Fraction of hours in the day with at least 5 minutes (300 seconds) of active screen use:
   ```sql
   COUNT(DISTINCT hour) FILTER (WHERE estimated_watch_seconds >= 300) / 24.0 AS fragmentation_index
   ```
