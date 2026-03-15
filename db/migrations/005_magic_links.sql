-- Migration 005: magic_links
-- Single-use passwordless auth tokens; token stored as SHA-256 hash only

CREATE TABLE IF NOT EXISTS magic_links (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id   UUID NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
    email_hash   TEXT NOT NULL,
    token_hash   TEXT NOT NULL UNIQUE,
    purpose      TEXT NOT NULL DEFAULT 'login',
    redirect_url TEXT NOT NULL DEFAULT '',
    is_used      BOOLEAN NOT NULL DEFAULT FALSE,
    expires_at   TIMESTAMPTZ NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_magic_links_token_hash ON magic_links (token_hash);
CREATE INDEX IF NOT EXISTS idx_magic_links_expires_at ON magic_links (expires_at);
