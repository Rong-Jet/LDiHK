CREATE TABLE IF NOT EXISTS synthetic_seed_runs (
    id UUID PRIMARY KEY,
    name TEXT NOT NULL,
    generator_version TEXT NOT NULL,
    profile_count INTEGER NOT NULL,
    total_days INTEGER NOT NULL,
    config_json JSONB NOT NULL,
    generated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS is_synthetic BOOLEAN NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS age INTEGER,
    ADD COLUMN IF NOT EXISTS sex TEXT,
    ADD COLUMN IF NOT EXISTS age_bucket TEXT,
    ADD COLUMN IF NOT EXISTS cohort TEXT;

UPDATE users
SET
    age = COALESCE(age, 23),
    sex = COALESCE(sex, 'male')
WHERE age IS NULL
   OR sex IS NULL;

UPDATE users
SET
    age_bucket = CASE
        WHEN age < 18 THEN 'adolescent'
        WHEN age < 50 THEN 'adult'
        ELSE 'older'
    END,
    cohort = CASE
        WHEN age < 18 THEN 'adolescent'
        WHEN age < 50 THEN 'adult'
        ELSE 'older'
    END || '_' || sex
WHERE age IS NOT NULL
  AND sex IS NOT NULL
  AND (age_bucket IS NULL OR cohort IS NULL);

ALTER TABLE imports
    ADD COLUMN IF NOT EXISTS data_origin TEXT NOT NULL DEFAULT 'takeout',
    ADD COLUMN IF NOT EXISTS seed_run_id UUID REFERENCES synthetic_seed_runs(id);

ALTER TABLE usage_events
    ADD COLUMN IF NOT EXISTS duration_seconds INTEGER,
    ADD COLUMN IF NOT EXISTS is_synthetic BOOLEAN NOT NULL DEFAULT false;

UPDATE usage_events
SET is_synthetic = users.is_synthetic
FROM users
WHERE usage_events.user_id = users.id;

CREATE INDEX IF NOT EXISTS idx_users_external_id_synthetic
    ON users (external_id, is_synthetic);

CREATE INDEX IF NOT EXISTS idx_users_synthetic_profile
    ON users (is_synthetic, cohort, sex, age_bucket);

CREATE INDEX IF NOT EXISTS idx_imports_seed_run
    ON imports (seed_run_id)
    WHERE seed_run_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_usage_events_user_platform_time
    ON usage_events (user_id, platform, occurred_at);

CREATE INDEX IF NOT EXISTS idx_usage_events_synthetic_platform_time
    ON usage_events (is_synthetic, platform, occurred_at);

CREATE INDEX IF NOT EXISTS idx_usage_events_synthetic_type_time
    ON usage_events (is_synthetic, event_type, occurred_at);
