-- =============================================================================
-- Sentinel Auth — Database Schema v2
-- FastAPI single-process: auth + detection + ML inline
-- All tables in public schema (PostgreSQL default)
--
-- CHANGELOG from schema.sql (v1):
--   - Renamed rule_versions → policy_versions (clearer naming)
--   - Added mfa_notifications table (email OTP lifecycle tracking)
--   - Extended login_attempts with username_attempted, policy_version_id,
--     rate_limited, detection_features, request_id
--   - Moved scoring fields from login_attempts → risk_assessments
--   - Extended risk_assessments with policy_version_id, rule_hits, ml_features_used
--   - Extended pre_auth_transactions with mfa_type, notification_id
--   - Removed mfa_code_hash from pre_auth_transactions (now in mfa_notifications)
--   - Improved rate_limits (composite PK, configurable max_count)
--   - Extended detection_logs with request_id, rule_id, stage_detail
--   - Extended alerts with policy_version_id, request_id, detection_scores,
--     detection_reason
--   - Extended users with full_name, last_login_at, failed_login_count, locked_at,
--     added validation CHECK constraints
--   - Extended sessions with last_activity_at, refresh_token_family, token_jti
--   - Extended audit_logs with request_id, change_reason
--   - Added auto-update trigger for updated_at columns
-- =============================================================================

-- =============================================================================
-- EXTENSIONS
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";  -- For fuzzy text search if needed

-- =============================================================================
-- HELPER: Auto-update updated_at trigger
-- =============================================================================

CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- =============================================================================
-- ROLES (reference table — seeded)
-- =============================================================================

CREATE TABLE IF NOT EXISTS roles (
    id    TEXT PRIMARY KEY,   -- 'USER', 'SECURITY_ADMIN', 'SOC_ANALYST', 'SECURITY_MANAGER'
    name  TEXT NOT NULL,
    description TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO roles (id, name, description) VALUES
    ('USER',              'Người dùng',            'Role nền mặc định. Ai cũng có. Không bị gỡ trong v1.'),
    ('SECURITY_ADMIN',    'Quản trị viên bảo mật', 'Quản lý account, rule versioning, audit logs.'),
    ('SOC_ANALYST',       'Phân tích viên SOC',     'Xem, acknowledge, resolve alerts.'),
    ('SECURITY_MANAGER',  'Quản lý bảo mật',       'Quản lý account + rule. Không xem audit logs.')
ON CONFLICT (id) DO NOTHING;

-- =============================================================================
-- USERS
-- =============================================================================

CREATE TABLE IF NOT EXISTS users (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username                TEXT NOT NULL UNIQUE,
    password_hash           TEXT NOT NULL,
    email                   TEXT,
    full_name               TEXT,
    status                  TEXT NOT NULL DEFAULT 'active'
                                CHECK (status IN ('active', 'suspended', 'locked')),
    admin_mfa_required      BOOLEAN NOT NULL DEFAULT FALSE,
    detection_mfa_once      BOOLEAN NOT NULL DEFAULT FALSE,
    last_login_at          TIMESTAMPTZ,
    failed_login_count     INTEGER NOT NULL DEFAULT 0,
    locked_at              TIMESTAMPTZ,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Validation constraints
    CONSTRAINT chk_username_length CHECK (length(username) BETWEEN 3 AND 50),
    CONSTRAINT chk_username_chars CHECK (username ~ '^[a-zA-Z0-9_]+$'),
    CONSTRAINT chk_email_format CHECK (
        email IS NULL OR
        (length(email) BETWEEN 5 AND 254 AND email ~ '^[^(]+@[^(]+$')
    )
);

CREATE TRIGGER trg_users_updated_at
    BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE INDEX IF NOT EXISTS idx_users_username    ON users(username);
CREATE INDEX IF NOT EXISTS idx_users_email       ON users(email);
CREATE INDEX IF NOT EXISTS idx_users_status      ON users(status);

-- =============================================================================
-- USER ROLES (many-to-many)
-- =============================================================================

CREATE TABLE IF NOT EXISTS user_roles (
    user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role_id     TEXT NOT NULL REFERENCES roles(id),
    assigned_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    assigned_by UUID REFERENCES users(id) ON DELETE SET NULL,
    PRIMARY KEY (user_id, role_id)
);

CREATE INDEX IF NOT EXISTS idx_user_roles_user_id ON user_roles(user_id);
CREATE INDEX IF NOT EXISTS idx_user_roles_role_id ON user_roles(role_id);

-- =============================================================================
-- SESSIONS
-- =============================================================================

CREATE TABLE IF NOT EXISTS sessions (
    id                     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id                UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    access_token_hash       TEXT NOT NULL,
    refresh_token_hash      TEXT,
    refresh_token_family    UUID,                      -- For refresh token rotation tracking
    token_jti              TEXT UNIQUE,               -- JWT ID for individual token revoke
    expires_at              TIMESTAMPTZ NOT NULL,
    last_activity_at        TIMESTAMPTZ,
    revoked_at              TIMESTAMPTZ,
    ip_address              INET,
    user_agent              TEXT,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TRIGGER trg_sessions_updated_at
    BEFORE UPDATE ON sessions
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE INDEX IF NOT EXISTS idx_sessions_user_id        ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_access_hash    ON sessions(access_token_hash);
CREATE INDEX IF NOT EXISTS idx_sessions_expires_at     ON sessions(expires_at);
CREATE INDEX IF NOT EXISTS idx_sessions_token_jti      ON sessions(token_jti) WHERE token_jti IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_sessions_refresh_family ON sessions(refresh_token_family) WHERE refresh_token_family IS NOT NULL;

-- =============================================================================
-- PRE-AUTH TRANSACTIONS (MFA)
-- OTP: 6 digits, 5 minutes validity, max 3 attempts
-- =============================================================================

CREATE TABLE IF NOT EXISTS pre_auth_transactions (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    mfa_type            TEXT NOT NULL DEFAULT 'one_time'
                           CHECK (mfa_type IN ('persistent', 'one_time')),
    expires_at          TIMESTAMPTZ NOT NULL,
    status              TEXT NOT NULL DEFAULT 'pending'
                          CHECK (status IN ('pending', 'completed', 'expired', 'failed')),
    bound_ip            TEXT,                           -- Hashed IP for binding check
    notification_id     UUID,                           -- FK to mfa_notifications
    fail_count          INTEGER NOT NULL DEFAULT 0,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TRIGGER trg_pre_auth_updated_at
    BEFORE UPDATE ON pre_auth_transactions
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE INDEX IF NOT EXISTS idx_pre_auth_user_id              ON pre_auth_transactions(user_id);
CREATE INDEX IF NOT EXISTS idx_pre_auth_status                ON pre_auth_transactions(status);
CREATE INDEX IF NOT EXISTS idx_pre_auth_expires               ON pre_auth_transactions(expires_at);
CREATE INDEX IF NOT EXISTS idx_pre_auth_user_status_expires   ON pre_auth_transactions(user_id, status, expires_at);

-- =============================================================================
-- MFA NOTIFICATIONS (email OTP lifecycle tracking)
-- Separated from pre_auth_transactions for multi-channel extensibility
-- =============================================================================

CREATE TABLE IF NOT EXISTS mfa_notifications (
    id                         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pre_auth_transaction_id    UUID NOT NULL REFERENCES pre_auth_transactions(id) ON DELETE CASCADE,
    channel                    TEXT NOT NULL DEFAULT 'email'
                                  CHECK (channel IN ('email')),
    recipient                  TEXT NOT NULL,              -- Email address or phone number
    mfa_code_hash              TEXT NOT NULL,              -- Argon2id hash of 6-digit OTP
    sent_at                    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    delivered_at               TIMESTAMPTZ,
    failed_at                  TIMESTAMPTZ,
    failure_reason             TEXT,
    expires_at                 TIMESTAMPTZ NOT NULL,
    verified_at                TIMESTAMPTZ,
    created_at                 TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_mfa_notif_transaction_id ON mfa_notifications(pre_auth_transaction_id);
CREATE INDEX IF NOT EXISTS idx_mfa_notif_recipient     ON mfa_notifications(recipient);
CREATE INDEX IF NOT EXISTS idx_mfa_notif_expires       ON mfa_notifications(expires_at);

-- Add FK from pre_auth_transactions to mfa_notifications
-- (requires both tables to exist, so done after mfa_notifications creation)
ALTER TABLE pre_auth_transactions
    ADD CONSTRAINT fk_pre_auth_notification
    FOREIGN KEY (notification_id) REFERENCES mfa_notifications(id) ON DELETE SET NULL;

-- =============================================================================
-- RATE LIMITING
-- Composite PK: (ip_address, action)
-- =============================================================================

CREATE TABLE IF NOT EXISTS rate_limits (
    ip_address  INET NOT NULL,
    action      TEXT NOT NULL,
    count       INTEGER NOT NULL DEFAULT 1,
    max_count   INTEGER NOT NULL DEFAULT 5,
    window_start TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (ip_address, action),

    CONSTRAINT chk_rate_count  CHECK (count >= 0),
    CONSTRAINT chk_rate_max    CHECK (max_count > 0)
);

CREATE INDEX IF NOT EXISTS idx_rate_limits_window ON rate_limits(window_start);

-- =============================================================================
-- POLICY VERSIONS (renamed from rule_versions)
-- Detection rule versioning with full rule set as JSONB
-- =============================================================================

CREATE TABLE IF NOT EXISTS policy_versions (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    version             TEXT NOT NULL UNIQUE,        -- e.g. 'v1.0', 'v2.1'
    description         TEXT,
    rules_json          JSONB NOT NULL,
    weights             JSONB NOT NULL DEFAULT '{"rule": 0.4, "ml": 0.6}',
    thresholds          JSONB NOT NULL DEFAULT '{"challenge": 0.3, "block": 0.7}',
    is_active           BOOLEAN NOT NULL DEFAULT FALSE,
    created_by_user_id  UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    activated_at        TIMESTAMPTZ,
    deactivated_at      TIMESTAMPTZ,

    -- Only one active version at a time
    CONSTRAINT chk_single_active_version
        CHECK (
            NOT (is_active AND EXISTS (
                SELECT 1 FROM policy_versions pv2
                WHERE pv2.is_active = TRUE AND pv2.id != id
            ))
        )
);

CREATE TRIGGER trg_policy_updated_at
    BEFORE UPDATE ON policy_versions
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE INDEX IF NOT EXISTS idx_policy_versions_version    ON policy_versions(version);
CREATE INDEX IF NOT EXISTS idx_policy_versions_is_active  ON policy_versions(is_active) WHERE is_active = TRUE;

-- =============================================================================
-- LOGIN ATTEMPTS
-- Core audit + detection source table
-- =============================================================================

CREATE TABLE IF NOT EXISTS login_attempts (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id               UUID REFERENCES users(id) ON DELETE SET NULL,
    username_attempted    TEXT,                      -- Username tried (for failed logins without user_id)
    occurred_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    outcome               TEXT NOT NULL
                            CHECK (outcome IN (
                                'success', 'failure', 'mfa_required',
                                'mfa_success', 'mfa_failed', 'blocked', 'locked', 'rate_limited'
                            )),
    source_ip             INET,
    user_agent            TEXT,
    rate_limited          BOOLEAN NOT NULL DEFAULT FALSE,
    policy_version_id     UUID REFERENCES policy_versions(id) ON DELETE SET NULL,
    request_id            UUID NOT NULL DEFAULT gen_random_uuid(),  -- Distributed tracing
    detection_features    JSONB,                     -- Raw features vector for debugging
    primary_alert_id      UUID,                     -- First alert created from this attempt
    risk_level            TEXT CHECK (risk_level IN ('low', 'medium', 'high', 'critical')),
    mfa_used              BOOLEAN NOT NULL DEFAULT FALSE,
    detection_decision    TEXT CHECK (detection_decision IN ('allow', 'challenge', 'block')),
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TRIGGER trg_login_attempts_updated_at
    BEFORE UPDATE ON login_attempts
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE INDEX IF NOT EXISTS idx_login_attempts_user_id           ON login_attempts(user_id);
CREATE INDEX IF NOT EXISTS idx_login_attempts_occurred          ON login_attempts(occurred_at);
CREATE INDEX IF NOT EXISTS idx_login_attempts_outcome           ON login_attempts(outcome);
CREATE INDEX IF NOT EXISTS idx_login_attempts_risk_level        ON login_attempts(risk_level);
CREATE INDEX IF NOT EXISTS idx_login_attempts_request_id        ON login_attempts(request_id);
CREATE INDEX IF NOT EXISTS idx_login_attempts_username_attempted ON login_attempts(username_attempted);

-- =============================================================================
-- RISK ASSESSMENTS (per login attempt — 1:1 relationship)
-- Contains all scoring details; login_attempts no longer stores scores
-- =============================================================================

CREATE TABLE IF NOT EXISTS risk_assessments (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    login_attempt_id   UUID NOT NULL REFERENCES login_attempts(id) ON DELETE CASCADE,
    policy_version_id   UUID REFERENCES policy_versions(id) ON DELETE SET NULL,
    rule_score         NUMERIC(5,4),
    anomaly_score      NUMERIC(5,4),
    ml_score           NUMERIC(5,4),
    ml_status          TEXT CHECK (ml_status IN ('success', 'unavailable', 'error')),
    ml_model_version   TEXT,
    rule_hits          JSONB,                     -- Array of rule names that triggered
    ml_features_used   JSONB,                     -- Features actually used for ML
    combined_score     NUMERIC(5,4),              -- Weighted combination: w1*rule + w2*ml
    risk_level         TEXT CHECK (risk_level IN ('low', 'medium', 'high', 'critical')),
    decision           TEXT CHECK (decision IN ('allow', 'challenge', 'block')),
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Exactly one risk assessment per login attempt
    CONSTRAINT uq_risk_assessment_login_attempt UNIQUE (login_attempt_id)
);

CREATE INDEX IF NOT EXISTS idx_risk_login_attempt_id ON risk_assessments(login_attempt_id);
CREATE INDEX IF NOT EXISTS idx_risk_risk_level       ON risk_assessments(risk_level);

-- =============================================================================
-- DETECTION LOGS (audit trail for ML/rule decisions)
-- Multiple logs per login_attempt (one per rule evaluated)
-- =============================================================================

CREATE TABLE IF NOT EXISTS detection_logs (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    login_attempt_id UUID REFERENCES login_attempts(id) ON DELETE SET NULL,
    request_id       UUID,                     -- Distributed tracing
    stage            TEXT NOT NULL CHECK (stage IN ('rule', 'ml', 'combined', 'action')),
    stage_detail     TEXT,                     -- e.g. 'geo_block', 'asn_reputation', 'ml_inference'
    rule_id          UUID,                     -- Reference to rule in policy_version.rules_json
    rule_name        TEXT,                     -- Human-readable rule name
    score            NUMERIC(5,4),
    decision         TEXT CHECK (decision IN ('allow', 'challenge', 'block')),
    reason           TEXT,
    details          JSONB,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_detection_logs_login_id  ON detection_logs(login_attempt_id);
CREATE INDEX IF NOT EXISTS idx_detection_logs_stage    ON detection_logs(stage);
CREATE INDEX IF NOT EXISTS idx_detection_logs_request_id ON detection_logs(request_id);

-- =============================================================================
-- ALERTS (SOC workflow)
-- =============================================================================

CREATE TABLE IF NOT EXISTS alerts (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    login_attempt_id   UUID NOT NULL REFERENCES login_attempts(id) ON DELETE CASCADE,
    policy_version_id  UUID REFERENCES policy_versions(id) ON DELETE SET NULL,
    request_id         UUID,
    status             TEXT NOT NULL DEFAULT 'open'
                         CHECK (status IN ('open', 'acknowledged', 'resolved', 'false_positive')),
    risk_level         TEXT CHECK (risk_level IN ('low', 'medium', 'high', 'critical')),
    detection_reason   TEXT,                    -- Short reason why alert was created
    detection_scores   JSONB,                  -- Snapshot of scores at creation time
    assigned_to        TEXT,
    resolved_by        TEXT,
    resolved_at        TIMESTAMPTZ,
    notes              TEXT,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TRIGGER trg_alerts_updated_at
    BEFORE UPDATE ON alerts
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE INDEX IF NOT EXISTS idx_alerts_login_attempt_id  ON alerts(login_attempt_id);
CREATE INDEX IF NOT EXISTS idx_alerts_status            ON alerts(status);
CREATE INDEX IF NOT EXISTS idx_alerts_risk_level        ON alerts(risk_level);
CREATE INDEX IF NOT EXISTS idx_alerts_assigned_to       ON alerts(assigned_to);
CREATE INDEX IF NOT EXISTS idx_alerts_created_at        ON alerts(created_at);

-- Add FK from login_attempts to alerts (after alerts table exists)
ALTER TABLE login_attempts
    ADD CONSTRAINT fk_login_attempt_primary_alert
    FOREIGN KEY (primary_alert_id) REFERENCES alerts(id) ON DELETE SET NULL;

-- =============================================================================
-- AUDIT LOGS (all admin + system actions)
-- Never stores: password, OTP, JWT, plaintext email
-- =============================================================================

CREATE TABLE IF NOT EXISTS audit_logs (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    request_id    UUID,                     -- Distributed tracing
    actor         TEXT NOT NULL,            -- user_id or 'system:detection-engine'
    action        TEXT NOT NULL,            -- 'role_assigned', 'user_locked', 'session_revoked', 'alert_resolved', ...
    resource      TEXT NOT NULL,            -- 'user', 'session', 'role', 'alert', 'policy_version', ...
    resource_id   UUID,
    before_state  JSONB,
    after_state   JSONB,
    change_reason TEXT,                     -- Why the change was made
    ip_address    INET,
    user_agent    TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_audit_logs_actor       ON audit_logs(actor);
CREATE INDEX IF NOT EXISTS idx_audit_logs_action      ON audit_logs(action);
CREATE INDEX IF NOT EXISTS idx_audit_logs_resource    ON audit_logs(resource);
CREATE INDEX IF NOT EXISTS idx_audit_logs_created_at  ON audit_logs(created_at);
CREATE INDEX IF NOT EXISTS idx_audit_logs_request_id  ON audit_logs(request_id);

-- =============================================================================
-- SEED DATA: Default policy version
-- =============================================================================

INSERT INTO policy_versions (version, description, rules_json, is_active, created_at) VALUES
    (
        'v1.0',
        'Default detection policy for v1',
        '{
            "rules": [
                {
                    "name": "geo_block",
                    "description": "Block logins from high-risk countries",
                    "conditions": {"countries": ["XX"]},
                    "score": 0.95,
                    "enabled": true
                },
                {
                    "name": "new_country",
                    "description": "Login from new country for user",
                    "conditions": {"threshold_days": 90},
                    "score": 0.6,
                    "enabled": true
                },
                {
                    "name": "asn_reputation",
                    "description": "Low ASN reputation score",
                    "conditions": {"min_reputation": 0.3},
                    "score": 0.5,
                    "enabled": true
                },
                {
                    "name": "failed_attempts",
                    "description": "Multiple failed login attempts",
                    "conditions": {"threshold": 3},
                    "score": 0.7,
                    "enabled": true
                },
                {
                    "name": "unusual_hour",
                    "description": "Login outside usual hours",
                    "conditions": {"hour_range": [0, 6]},
                    "score": 0.3,
                    "enabled": true
                }
            ],
            "weights": {"rule": 0.4, "ml": 0.6},
            "thresholds": {"challenge": 0.3, "block": 0.7}
        }'::jsonb,
        TRUE,
        NOW()
    )
ON CONFLICT (version) DO NOTHING;

-- =============================================================================
-- SECURITY: Row-Level Security (RLS) - optional, for multi-tenant future
-- =============================================================================

-- Note: RLS is commented out for v1 (single-tenant). Enable if needed for v2.
-- ALTER TABLE users ENABLE ROW LEVEL SECURITY;
-- ALTER TABLE sessions ENABLE ROW LEVEL SECURITY;
-- ALTER TABLE audit_logs ENABLE ROW LEVEL SECURITY;

COMMENT ON TABLE users IS 'Core user accounts with authentication and MFA settings.';
COMMENT ON TABLE sessions IS 'Active user sessions with JWT refresh tokens.';
COMMENT ON TABLE pre_auth_transactions IS 'Pending MFA challenges before session creation.';
COMMENT ON TABLE mfa_notifications IS 'Email/SMS OTP notification lifecycle tracking.';
COMMENT ON TABLE login_attempts IS 'All login attempts with outcome and risk metadata.';
COMMENT ON TABLE risk_assessments IS 'Per-attempt risk scoring (rule + ML + combined).';
COMMENT ON TABLE policy_versions IS 'Versioned detection rule sets with weights and thresholds.';
COMMENT ON TABLE alerts IS 'SOC alerts created from high-risk login attempts.';
COMMENT ON TABLE detection_logs IS 'Detailed audit trail of detection engine decisions.';
COMMENT ON TABLE audit_logs IS 'Immutable audit trail of all admin and system actions.';
