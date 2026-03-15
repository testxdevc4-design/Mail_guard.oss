-- Migration 006: webhooks
-- Developer-registered webhook endpoints; secret stored encrypted

CREATE TABLE IF NOT EXISTS webhooks (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id       UUID NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
    url              TEXT NOT NULL,
    secret_enc       TEXT NOT NULL,
    events           TEXT[] NOT NULL DEFAULT '{}',
    is_active        BOOLEAN NOT NULL DEFAULT TRUE,
    failure_count    INTEGER NOT NULL DEFAULT 0,
    last_triggered_at TIMESTAMPTZ,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_webhooks_project_id ON webhooks (project_id);
