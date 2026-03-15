-- Migration 002: projects
-- One project per integration; links to a sender and holds OTP config

CREATE TABLE IF NOT EXISTS projects (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name                    TEXT NOT NULL,
    slug                    TEXT NOT NULL UNIQUE,
    sender_email_id         UUID REFERENCES sender_emails (id) ON DELETE SET NULL,
    otp_length              INTEGER NOT NULL DEFAULT 6,
    otp_expiry_seconds      INTEGER NOT NULL DEFAULT 300,
    otp_max_attempts        INTEGER NOT NULL DEFAULT 5,
    rate_limit_per_hour     INTEGER NOT NULL DEFAULT 10,
    template_subject        TEXT NOT NULL DEFAULT 'Your verification code',
    template_body_text      TEXT NOT NULL DEFAULT 'Your OTP is {{otp_code}}. It expires in {{expiry_minutes}} minutes.',
    template_body_html      TEXT NOT NULL DEFAULT '',
    is_active               BOOLEAN NOT NULL DEFAULT TRUE,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_projects_slug ON projects (slug);
CREATE INDEX IF NOT EXISTS idx_projects_sender_email_id ON projects (sender_email_id);
