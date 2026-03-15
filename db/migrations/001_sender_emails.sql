-- Migration 001: sender_emails
-- Stores SMTP sender accounts with encrypted credentials

CREATE TABLE IF NOT EXISTS sender_emails (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email_address    TEXT NOT NULL UNIQUE,
    display_name     TEXT NOT NULL DEFAULT '',
    provider         TEXT NOT NULL DEFAULT 'custom',
    smtp_host        TEXT NOT NULL,
    smtp_port        INTEGER NOT NULL DEFAULT 465,
    app_password_enc TEXT NOT NULL,
    daily_limit      INTEGER NOT NULL DEFAULT 500,
    daily_sent       INTEGER NOT NULL DEFAULT 0,
    last_reset_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    is_active        BOOLEAN NOT NULL DEFAULT TRUE,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_sender_emails_is_active ON sender_emails (is_active);
