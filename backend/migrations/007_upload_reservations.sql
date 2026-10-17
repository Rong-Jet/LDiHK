-- Upload budget: every upload URL the backend issues is recorded here, so the
-- backend can refuse new URLs before the storage bucket could leave the free
-- tier (Cloudflare R2 has no spending cap). A row counts against the stored
-- bytes budget until its object has been deleted (deleted_at), and against the
-- monthly upload budget by created_at. Rows of deleted users keep no ID.

CREATE TABLE IF NOT EXISTS upload_reservations (
    id UUID PRIMARY KEY,
    ldihk_id TEXT,
    s3_bucket TEXT NOT NULL,
    s3_key TEXT NOT NULL UNIQUE,
    size_bytes BIGINT NOT NULL CHECK (size_bytes > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL,
    deleted_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_upload_reservations_created
    ON upload_reservations (created_at);

CREATE INDEX IF NOT EXISTS idx_upload_reservations_outstanding
    ON upload_reservations (expires_at)
    WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_upload_reservations_ldihk_id
    ON upload_reservations (ldihk_id)
    WHERE ldihk_id IS NOT NULL;

ALTER TABLE upload_reservations ENABLE ROW LEVEL SECURITY;
