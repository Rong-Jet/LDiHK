-- Job leases: a worker that crashes, is redeployed, or is put to sleep by a
-- free hosting tier leaves its job in 'running'. Workers refresh heartbeat_at
-- while they hold a job, and other workers reclaim 'running' jobs whose
-- heartbeat is stale, up to a maximum number of attempts.

ALTER TABLE imports
    ADD COLUMN IF NOT EXISTS attempts INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS heartbeat_at TIMESTAMPTZ;

ALTER TABLE enrichment_jobs
    ADD COLUMN IF NOT EXISTS heartbeat_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_imports_running_heartbeat
    ON imports (heartbeat_at)
    WHERE status = 'running';

CREATE INDEX IF NOT EXISTS idx_enrichment_jobs_running_heartbeat
    ON enrichment_jobs (heartbeat_at)
    WHERE status = 'running';
