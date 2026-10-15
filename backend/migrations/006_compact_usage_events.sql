-- Storage diet for free Postgres tiers (Neon free: 1 GB per project).
-- Measured before this migration: 805 bytes per usage_events row including
-- indexes, of which the heap is only 229 bytes.

-- 1. Drop indexes that are covered by ones we keep:
--    * idx_usage_events_user_time and idx_usage_events_user_type_time are
--      served by idx_usage_events_user_platform_time (user_id, platform,
--      occurred_at): every user-scoped query, including the "next watch"
--      lookup, filters by user and platform.
--    * idx_usage_events_synthetic_type_time duplicates
--      idx_usage_events_synthetic_platform_time for the population queries,
--      which always filter platform = 'youtube' together with the event type.
DROP INDEX IF EXISTS idx_usage_events_user_time;
DROP INDEX IF EXISTS idx_usage_events_user_type_time;
DROP INDEX IF EXISTS idx_usage_events_synthetic_type_time;

-- 2. Store SHA-256 values as 32 raw bytes instead of 64 hex characters.
--    Writers keep passing hex strings and wrap them in decode(%s, 'hex').
--    Any legacy value that is not a SHA-256 hex digest is hashed, so the
--    conversion never fails and stays unique per original value.
ALTER TABLE usage_events
    ALTER COLUMN event_fingerprint TYPE bytea USING (
        CASE
            WHEN event_fingerprint ~ '^[0-9a-f]{64}$'
            THEN decode(event_fingerprint, 'hex')
            ELSE sha256(convert_to(event_fingerprint, 'UTF8'))
        END
    ),
    ALTER COLUMN title_hash TYPE bytea USING (
        CASE
            WHEN title_hash ~ '^[0-9a-f]{64}$'
            THEN decode(title_hash, 'hex')
            ELSE sha256(convert_to(title_hash, 'UTF8'))
        END
    ),
    ALTER COLUMN search_query_hash TYPE bytea USING (
        CASE
            WHEN search_query_hash ~ '^[0-9a-f]{64}$'
            THEN decode(search_query_hash, 'hex')
            ELSE sha256(convert_to(search_query_hash, 'UTF8'))
        END
    );
