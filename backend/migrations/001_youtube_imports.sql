CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY,
    external_id TEXT UNIQUE NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS imports (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id),
    s3_bucket TEXT NOT NULL,
    s3_key TEXT NOT NULL,
    s3_etag TEXT,
    status TEXT NOT NULL,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    records_seen INTEGER NOT NULL DEFAULT 0,
    records_imported INTEGER NOT NULL DEFAULT 0,
    warnings_count INTEGER NOT NULL DEFAULT 0,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS source_files (
    id UUID PRIMARY KEY,
    import_id UUID NOT NULL REFERENCES imports(id),
    path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    parser_name TEXT,
    status TEXT NOT NULL,
    records_seen INTEGER NOT NULL DEFAULT 0,
    records_imported INTEGER NOT NULL DEFAULT 0,
    warnings_count INTEGER NOT NULL DEFAULT 0,
    UNIQUE (import_id, path)
);

CREATE TABLE IF NOT EXISTS usage_events (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id),
    import_id UUID NOT NULL REFERENCES imports(id),
    source_file_id UUID REFERENCES source_files(id),
    platform TEXT NOT NULL,
    product TEXT NOT NULL,
    event_type TEXT NOT NULL,
    occurred_at TIMESTAMPTZ,
    video_id TEXT,
    channel_id TEXT,
    title_hash TEXT,
    search_query_hash TEXT,
    raw_status TEXT,
    event_fingerprint TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, event_fingerprint)
);

CREATE TABLE IF NOT EXISTS subscriptions (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id),
    import_id UUID NOT NULL REFERENCES imports(id),
    channel_id TEXT NOT NULL,
    channel_url TEXT,
    channel_title_hash TEXT,
    source_path TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, channel_id)
);

CREATE TABLE IF NOT EXISTS youtube_videos (
    video_id TEXT PRIMARY KEY,
    channel_id TEXT,
    duration_seconds INTEGER,
    duration_source TEXT,
    availability_status TEXT NOT NULL,
    max_duration_applied BOOLEAN NOT NULL DEFAULT false,
    fetched_at TIMESTAMPTZ,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    last_error TEXT
);

CREATE TABLE IF NOT EXISTS youtube_channels (
    channel_id TEXT PRIMARY KEY,
    title_hash TEXT,
    fetched_at TIMESTAMPTZ,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    last_error TEXT
);

CREATE TABLE IF NOT EXISTS enrichment_jobs (
    id UUID PRIMARY KEY,
    job_type TEXT NOT NULL,
    status TEXT NOT NULL,
    payload_json JSONB NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    run_after TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS import_warnings (
    id UUID PRIMARY KEY,
    import_id UUID NOT NULL REFERENCES imports(id),
    source_file_id UUID REFERENCES source_files(id),
    code TEXT NOT NULL,
    count INTEGER NOT NULL,
    sample_hash TEXT
);

CREATE INDEX IF NOT EXISTS idx_usage_events_user_time
    ON usage_events (user_id, occurred_at);

CREATE INDEX IF NOT EXISTS idx_usage_events_user_type_time
    ON usage_events (user_id, event_type, occurred_at);

CREATE INDEX IF NOT EXISTS idx_usage_events_video_id
    ON usage_events (video_id);

CREATE INDEX IF NOT EXISTS idx_usage_events_channel_id
    ON usage_events (channel_id);

CREATE INDEX IF NOT EXISTS idx_imports_status
    ON imports (status, created_at);

CREATE INDEX IF NOT EXISTS idx_enrichment_jobs_status
    ON enrichment_jobs (status, run_after);
