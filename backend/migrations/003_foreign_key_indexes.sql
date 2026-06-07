CREATE INDEX IF NOT EXISTS idx_imports_user_id
    ON imports (user_id);

CREATE INDEX IF NOT EXISTS idx_usage_events_import_id
    ON usage_events (import_id);

CREATE INDEX IF NOT EXISTS idx_usage_events_source_file_id
    ON usage_events (source_file_id)
    WHERE source_file_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_subscriptions_import_id
    ON subscriptions (import_id);

CREATE INDEX IF NOT EXISTS idx_import_warnings_import_id
    ON import_warnings (import_id);

CREATE INDEX IF NOT EXISTS idx_import_warnings_source_file_id
    ON import_warnings (source_file_id)
    WHERE source_file_id IS NOT NULL;
