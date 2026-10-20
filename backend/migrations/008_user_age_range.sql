-- Self-reported age range in 5-year steps ("20-24", ..., "70+"), used with sex
-- to compare a user with people of similar age and sex. Users never give an
-- exact age; users.age then holds the middle of the range for older queries.
ALTER TABLE users
    ADD COLUMN IF NOT EXISTS age_range TEXT;

CREATE INDEX IF NOT EXISTS idx_users_synthetic_age_range_sex
    ON users (is_synthetic, age_range, sex);
