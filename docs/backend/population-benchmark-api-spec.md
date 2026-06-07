# LDiHK Population Benchmark Implementation Notes

## Status

Non-authoritative implementation notes for Population Benchmark backend
integration.

Do not duplicate endpoint schemas in this file. Keep this document focused on
database shape, scalability, and query compilation strategy.

This document details schema updates and pre-aggregated caching strategies
required to move the Population Benchmark dashboard from frontend-side mocks to
real-data aggregates. It is optimized to handle a large volume of users
(including synthetically generated profiles in the database) without running
heavy scans on every page load.

---

## 1. Database Schema Updates

To support segmenting real and synthetic populations in the database, add a flag to the `users` table:

```sql
ALTER TABLE users ADD COLUMN is_synthetic BOOLEAN NOT NULL DEFAULT FALSE;
```

* **`is_synthetic`**: Allows the backend to filter aggregates depending on whether the active user toggles the comparison against the general synthetic database population or only local/real profiles.

---

## 2. Scalability & Aggregated Population Datasets

### The Scalability Problem
Calculating daily watch time percentiles (`percentile_cont`) and hourly averages across thousands of users over several months requires scanning millions of events in the `usage_events` table. Running this on every page load causes significant latency and database locks.

### The Solution: Pre-Aggregated Cache Tables
Since population statistics do not need real-time up-to-the-second precision, the backend must use pre-aggregated datasets.

A scheduled background job (or post-import trigger) will pre-compute and store population averages in cache tables. When a user requests their benchmark standing, the API queries their personal data in real-time and maps it against the cached O(1) population values.

#### Cache Table 1: Population Percentiles Cache
Stores daily percentiles (bottom 10%, median, top 10%) per platform, split by synthetic status:

```sql
CREATE TABLE IF NOT EXISTS population_percentiles_cache (
    watch_date DATE NOT NULL,
    is_synthetic BOOLEAN NOT NULL,
    platform TEXT NOT NULL,
    bottom10 NUMERIC NOT NULL,
    median NUMERIC NOT NULL,
    top10 NUMERIC NOT NULL,
    PRIMARY KEY (watch_date, is_synthetic, platform)
);
```

#### Cache Table 2: Population Hourly Averages Cache
Stores average watch hours for each hour of the day (0-23) over rolling timeframes:

```sql
CREATE TABLE IF NOT EXISTS population_hourly_averages_cache (
    hour_of_day INTEGER NOT NULL CHECK (hour_of_day BETWEEN 0 AND 23),
    is_synthetic BOOLEAN NOT NULL,
    platform TEXT NOT NULL,
    avg_watch_hours NUMERIC NOT NULL,
    PRIMARY KEY (hour_of_day, is_synthetic, platform)
);
```

#### Cache Table 3: Population Distribution Cache
Stores the density counts of users grouped by their daily average hours (used for the hourly watch time distribution bar chart):

```sql
CREATE TABLE IF NOT EXISTS population_distribution_cache (
    average_hour_bucket INTEGER NOT NULL CHECK (average_hour_bucket BETWEEN 0 AND 24),
    is_synthetic BOOLEAN NOT NULL,
    platform TEXT NOT NULL,
    user_count INTEGER NOT NULL,
    PRIMARY KEY (average_hour_bucket, is_synthetic, platform)
);
```

---

## 3. API Contract

The `/api/population` endpoint contract is maintained with the frontend
integration contract.

---

## 4. Query Compilation Logic

When `/api/population` is called:
1. **User Standings**: Calculate the active user's daily watch time timeline and average over the requested date range (this query runs in real-time as it is fast for a single user).
2. **Retrieve Cache/Population Aggregates**: Fetch percentile, distribution, and hourly averages for YouTube matching the `includeSynthetic` flag and selected dates. The initial backend may compute these directly from indexed `usage_events`; cache tables remain the scaling target.
3. **Linear Interpolation (Custom Percentile Line)**:
   If `customPercentile` is requested, the backend performs linear interpolation over the cached cohort boundaries:
   - For `customPercentile = 90`, fetch directly from `top10`.
   - For other percentiles, interpolate between `bottom10` (10th), `median` (50th), and `top10` (90th).
4. **Determine Rank**: Calculate the user's percentile standing by comparing the user's daily average against the cached distribution table.

---

## 5. Error Codes

Population endpoint error codes are part of the frontend integration contract.
