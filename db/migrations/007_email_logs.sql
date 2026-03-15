-- Migration 007: email_logs
-- Immutable audit log of every email send attempt; recipient stored as HMAC hash

CREATE TABLE IF NOT EXISTS email_logs (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id     UUID REFERENCES projects (id) ON DELETE SET NULL,
    sender_id      UUID REFERENCES sender_emails (id) ON DELETE SET NULL,
    recipient_hash TEXT NOT NULL,
    purpose        TEXT NOT NULL DEFAULT '',
    type           TEXT NOT NULL CHECK (type IN ('otp', 'magic')),
    status         TEXT NOT NULL CHECK (status IN ('sent', 'failed', 'queued')),
    error_detail   TEXT,
    sent_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_email_logs_project_id ON email_logs (project_id);
CREATE INDEX IF NOT EXISTS idx_email_logs_sent_at ON email_logs (sent_at);
CREATE INDEX IF NOT EXISTS idx_email_logs_status ON email_logs (status);
