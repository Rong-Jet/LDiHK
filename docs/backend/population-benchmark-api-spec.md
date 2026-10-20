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

Current implementation (`backend/population_api.py`, no cache tables yet):

1. **Requester**: look up the bearer's real user. Without YouTube watch rows in
   the range the response is `reason: "no_user_data"`.
2. **Real usage, one scan**: per-user daily hours and per-user hourly seconds
   for all real users in the range, using `GROUPING SETS` over the clipped
   watch events (watch time capped at the next watch start). The requester's
   own profile is taken out of this result.
3. **Coverage**: each other real user's first and last watch date. A member
   counts on the days of the range inside that span, with 0 hours on days
   without watching, and is left out when the span misses the range.
4. **Synthetic baseline** (`includeSynthetic`): the synthetic profiles are
   read over their own seeded window. A requested day outside the window maps
   to the same weekday inside it (`_baseline_day`), so the seed serves any
   date range instead of only the days around when it ran.
5. **Privacy guard**: with fewer than `MIN_POPULATION_SIZE` (5) other people
   the response is `reason: "insufficient_population"` and carries no
   aggregates.
6. **Aggregates in Python**: per-day percentiles (linear interpolation, same
   as Postgres `percentile_cont`) for bottom 10 %, median, top 10 % and the
   custom percentile; the distribution of members' average daily hours; hourly
   averages per covered day; the requester's percentile rank.

This is 3 to 5 queries per request, each scanning the range once. The cache
tables above remain the scaling target if the real population grows into
the thousands.

---

## 5. Error Codes

Population endpoint error codes are part of the frontend integration contract.
