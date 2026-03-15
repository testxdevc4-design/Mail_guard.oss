-- Migration 004: otp_records
-- One row per OTP request; email stored only as HMAC-SHA256 hash

CREATE TABLE IF NOT EXISTS otp_records (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id       UUID NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
    email_hash       TEXT NOT NULL,
    otp_hash         TEXT NOT NULL,
    purpose          TEXT NOT NULL DEFAULT 'login',
    attempt_count    INTEGER NOT NULL DEFAULT 0,
    otp_max_attempts INTEGER NOT NULL DEFAULT 5,
    is_verified      BOOLEAN NOT NULL DEFAULT FALSE,
    is_invalidated   BOOLEAN NOT NULL DEFAULT FALSE,
    expires_at       TIMESTAMPTZ NOT NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_otp_records_project_email ON otp_records (project_id, email_hash);
CREATE INDEX IF NOT EXISTS idx_otp_records_expires_at ON otp_records (expires_at);
