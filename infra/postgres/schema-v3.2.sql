-- =============================================================================
-- Sentinel Auth - Database Schema v3.2
-- Balanced Normalization: 3NF Compliance + Simplicity
--
-- Version: 3.2
-- Date: 2026-09-13
-- Based on: v3.1 with 3NF fixes for transitive dependencies
--
-- Design Decisions:
-- - SOC Analyst là User đặc biệt (1:1 relationship)
-- - Risk Assessment cho mọi Login (1:1 relationship)
-- - IP Address normalized vào bảng riêng
-- - Actor type: user hoặc system
-- - Giữ CHECK constraints cho enums đơn giản
-- =============================================================================

-- =============================================================================
-- EXTENSIONS
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";

-- =============================================================================
-- HELPER FUNCTIONS
-- =============================================================================

-- Auto-update updated_at column
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- =============================================================================
-- ROLES (Reference Table - Seed Data)
-- =============================================================================

CREATE TABLE IF NOT EXISTS roles (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    name_vi         TEXT NOT NULL,
    description     TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO roles (id, name, name_vi, description) VALUES
    ('USER',              'User',              'Người dùng',           'Role mặc định'),
    ('SECURITY_ADMIN',    'Security Admin',    'Quản trị viên bảo mật', 'Quản lý accounts, rules, audit'),
    ('SOC_ANALYST',       'SOC Analyst',       'Phân tích viên SOC',     'Xem, tiếp nhận, giải quyết alerts'),
    ('SECURITY_MANAGER',  'Security Manager',  'Quản lý bảo mật',       'Dashboard, báo cáo')
ON CONFLICT (id) DO NOTHING;

-- =============================================================================
-- USERS (Core Entity)
-- =============================================================================

CREATE TABLE IF NOT EXISTS users (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username                TEXT NOT NULL,
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

    CONSTRAINT uq_users_username UNIQUE (username),
    CONSTRAINT uq_users_email UNIQUE (email),
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

CREATE INDEX idx_users_username ON users(username);
CREATE INDEX idx_users_email ON users(email);
CREATE INDEX idx_users_status ON users(status);

-- =============================================================================
-- USER ROLES (Many-to-Many)
-- =============================================================================

CREATE TABLE IF NOT EXISTS user_roles (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role_id         TEXT NOT NULL REFERENCES roles(id),
    assigned_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    assigned_by     UUID REFERENCES users(id) ON DELETE SET NULL,

    CONSTRAINT uq_user_role UNIQUE (user_id, role_id)
);

CREATE INDEX idx_user_roles_user ON user_roles(user_id);
CREATE INDEX idx_user_roles_role ON user_roles(role_id);
CREATE INDEX idx_user_roles_assigned_by ON user_roles(assigned_by);

-- =============================================================================
-- IP ADDRESSES (Normalized)
-- =============================================================================

CREATE TABLE IF NOT EXISTS ip_addresses (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ip_address      INET NOT NULL,
    country_code    TEXT,
    country_name    TEXT,
    is_proxy        BOOLEAN NOT NULL DEFAULT FALSE,
    is_vpn          BOOLEAN NOT NULL DEFAULT FALSE,
    is_tor          BOOLEAN NOT NULL DEFAULT FALSE,
    first_seen_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_ip_address UNIQUE (ip_address)
);

CREATE INDEX idx_ip_addresses_first_seen ON ip_addresses(first_seen_at);
CREATE INDEX idx_ip_addresses_country ON ip_addresses(country_code);

-- =============================================================================
-- SESSIONS (JWT Token Management)
-- =============================================================================

CREATE TABLE IF NOT EXISTS sessions (
    id                     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id                UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    access_token_hash      TEXT NOT NULL,
    refresh_token_hash     TEXT,
    refresh_token_family   UUID,
    token_jti              TEXT,
    expires_at             TIMESTAMPTZ NOT NULL,
    last_activity_at       TIMESTAMPTZ,
    revoked_at             TIMESTAMPTZ,
    ip_address_id          UUID REFERENCES ip_addresses(id) ON DELETE SET NULL,
    user_agent             TEXT,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_sessions_token_jti UNIQUE (token_jti)
);

CREATE TRIGGER trg_sessions_updated_at
    BEFORE UPDATE ON sessions
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE INDEX idx_sessions_user ON sessions(user_id);
CREATE INDEX idx_sessions_access_hash ON sessions(access_token_hash);
CREATE INDEX idx_sessions_expires ON sessions(expires_at);
CREATE INDEX idx_sessions_token_jti ON sessions(token_jti) WHERE token_jti IS NOT NULL;
CREATE INDEX idx_sessions_refresh_family ON sessions(refresh_token_family) WHERE refresh_token_family IS NOT NULL;
CREATE INDEX idx_sessions_ip ON sessions(ip_address_id);

-- =============================================================================
-- MFA TRANSACTIONS (MFA Challenge)
-- =============================================================================

CREATE TABLE IF NOT EXISTS mfa_transactions (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    mfa_type            TEXT NOT NULL DEFAULT 'one_time'
                           CHECK (mfa_type IN ('one_time', 'persistent')),
    status              TEXT NOT NULL DEFAULT 'pending'
                           CHECK (status IN ('pending', 'completed', 'expired', 'failed')),
    bound_ip            INET,
    notification_id     UUID,
    fail_count          INTEGER NOT NULL DEFAULT 0,
    expires_at          TIMESTAMPTZ NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TRIGGER trg_mfa_transactions_updated_at
    BEFORE UPDATE ON mfa_transactions
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE INDEX idx_mfa_transactions_user ON mfa_transactions(user_id);
CREATE INDEX idx_mfa_transactions_status ON mfa_transactions(status);
CREATE INDEX idx_mfa_transactions_expires ON mfa_transactions(expires_at);
CREATE INDEX idx_mfa_transactions_user_status_expires ON mfa_transactions(user_id, status, expires_at);

-- =============================================================================
-- MFA NOTIFICATIONS (Email OTP Lifecycle)
-- =============================================================================

CREATE TABLE IF NOT EXISTS mfa_notifications (
    id                         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    mfa_transaction_id          UUID NOT NULL REFERENCES mfa_transactions(id) ON DELETE CASCADE,
    channel                    TEXT NOT NULL DEFAULT 'email'
                                  CHECK (channel IN ('email', 'sms', 'totp')),
    recipient                  TEXT NOT NULL,
    mfa_code_hash              TEXT NOT NULL,
    sent_at                    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    delivered_at               TIMESTAMPTZ,
    failed_at                  TIMESTAMPTZ,
    failure_reason             TEXT,
    expires_at                 TIMESTAMPTZ NOT NULL,
    verified_at                TIMESTAMPTZ,
    created_at                 TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_mfa_notifications_transaction ON mfa_notifications(mfa_transaction_id);
CREATE INDEX idx_mfa_notifications_recipient ON mfa_notifications(recipient);
CREATE INDEX idx_mfa_notifications_expires ON mfa_notifications(expires_at);

-- Add FK from mfa_transactions to mfa_notifications
ALTER TABLE mfa_transactions
    ADD CONSTRAINT fk_mfa_transaction_notification
    FOREIGN KEY (notification_id) REFERENCES mfa_notifications(id) ON DELETE SET NULL;

-- =============================================================================
-- POLICY VERSIONS (Detection Rules Versioning)
-- =============================================================================

CREATE TABLE IF NOT EXISTS policy_versions (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    version             TEXT NOT NULL UNIQUE,
    description         TEXT,
    rules_json          JSONB NOT NULL,
    weights_json        JSONB NOT NULL DEFAULT '{"rule": 0.4, "ml": 0.6}',
    thresholds_json     JSONB NOT NULL DEFAULT '{"challenge": 0.3, "block": 0.7}',
    is_active           BOOLEAN NOT NULL DEFAULT FALSE,
    created_by_user_id  UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    activated_at       TIMESTAMPTZ,
    deactivated_at      TIMESTAMPTZ,

    CONSTRAINT chk_single_active_policy
        CHECK (
            NOT (is_active AND EXISTS (
                SELECT 1 FROM policy_versions pv2
                WHERE pv2.is_active = TRUE AND pv2.id != id
            ))
        )
);

CREATE TRIGGER trg_policy_versions_updated_at
    BEFORE UPDATE ON policy_versions
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE INDEX idx_policy_versions_version ON policy_versions(version);
CREATE INDEX idx_policy_versions_active ON policy_versions(is_active) WHERE is_active = TRUE;
CREATE INDEX idx_policy_versions_creator ON policy_versions(created_by_user_id);

-- =============================================================================
-- LOGIN ATTEMPTS (Audit Trail & Detection Source)
-- =============================================================================

CREATE TABLE IF NOT EXISTS login_attempts (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id               UUID REFERENCES users(id) ON DELETE SET NULL,
    username_attempted    TEXT,
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
    request_id            UUID NOT NULL DEFAULT gen_random_uuid(),
    detection_features    JSONB,
    primary_alert_id      UUID,
    risk_level            TEXT CHECK (risk_level IN ('low', 'medium', 'high', 'critical')),
    mfa_used              BOOLEAN NOT NULL DEFAULT FALSE,
    detection_decision    TEXT CHECK (detection_decision IN ('allow', 'challenge', 'block')),
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TRIGGER trg_login_attempts_updated_at
    BEFORE UPDATE ON login_attempts
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE INDEX idx_login_attempts_user ON login_attempts(user_id);
CREATE INDEX idx_login_attempts_occurred ON login_attempts(occurred_at);
CREATE INDEX idx_login_attempts_outcome ON login_attempts(outcome);
CREATE INDEX idx_login_attempts_risk_level ON login_attempts(risk_level);
CREATE INDEX idx_login_attempts_request ON login_attempts(request_id);
CREATE INDEX idx_login_attempts_username ON login_attempts(username_attempted);
CREATE INDEX idx_login_attempts_source_ip ON login_attempts(source_ip);
CREATE INDEX idx_login_attempts_policy ON login_attempts(policy_version_id);

-- =============================================================================
-- RISK ASSESSMENTS (Per Login Attempt - 1:1)
-- =============================================================================

CREATE TABLE IF NOT EXISTS risk_assessments (
    id                     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    login_attempt_id       UUID NOT NULL REFERENCES login_attempts(id) ON DELETE CASCADE,
    policy_version_id      UUID REFERENCES policy_versions(id) ON DELETE SET NULL,
    rule_score             NUMERIC(5,4),
    anomaly_score          NUMERIC(5,4),
    ml_score               NUMERIC(5,4),
    ml_status              TEXT CHECK (ml_status IN ('success', 'unavailable', 'error')),
    ml_model_version       TEXT,
    rule_hits              JSONB,
    ml_features_used       JSONB,
    combined_score         NUMERIC(5,4),
    risk_level             TEXT CHECK (risk_level IN ('low', 'medium', 'high', 'critical')),
    decision               TEXT CHECK (decision IN ('allow', 'challenge', 'block')),
    created_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_risk_assessment_login UNIQUE (login_attempt_id)
);

CREATE INDEX idx_risk_assessments_login ON risk_assessments(login_attempt_id);
CREATE INDEX idx_risk_assessments_risk_level ON risk_assessments(risk_level);
CREATE INDEX idx_risk_assessments_policy ON risk_assessments(policy_version_id);
CREATE INDEX idx_risk_assessments_ml_status ON risk_assessments(ml_status);

-- =============================================================================
-- DETECTION LOGS (Audit Trail for ML/Rule)
-- =============================================================================

CREATE TABLE IF NOT EXISTS detection_logs (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    login_attempt_id UUID REFERENCES login_attempts(id) ON DELETE SET NULL,
    request_id       UUID,
    stage            TEXT NOT NULL CHECK (stage IN ('rule', 'ml', 'combined', 'action')),
    stage_detail     TEXT,
    rule_id          UUID,
    rule_name        TEXT,
    score            NUMERIC(5,4),
    decision         TEXT CHECK (decision IN ('allow', 'challenge', 'block')),
    reason           TEXT,
    details          JSONB,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_detection_logs_login ON detection_logs(login_attempt_id);
CREATE INDEX idx_detection_logs_stage ON detection_logs(stage);
CREATE INDEX idx_detection_logs_request ON detection_logs(request_id);
CREATE INDEX idx_detection_logs_decision ON detection_logs(decision);

-- =============================================================================
-- SOC ANALYSTS (Normalized from alerts.assigned_to/resolved_by)
-- =============================================================================

CREATE TABLE IF NOT EXISTS soc_analysts (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    display_name    TEXT,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    max_alerts      INTEGER NOT NULL DEFAULT 50,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_soc_analyst_user UNIQUE (user_id)
);

CREATE TRIGGER trg_soc_analysts_updated_at
    BEFORE UPDATE ON soc_analysts
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE INDEX idx_soc_analysts_user ON soc_analysts(user_id);
CREATE INDEX idx_soc_analysts_active ON soc_analysts(is_active);

-- =============================================================================
-- ALERTS (SOC Workflow)
-- =============================================================================

CREATE TABLE IF NOT EXISTS alerts (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    login_attempt_id   UUID NOT NULL REFERENCES login_attempts(id) ON DELETE CASCADE,
    policy_version_id  UUID REFERENCES policy_versions(id) ON DELETE SET NULL,
    request_id         UUID,
    status             TEXT NOT NULL DEFAULT 'open'
                         CHECK (status IN ('open', 'acknowledged', 'resolved', 'false_positive')),
    risk_level         TEXT CHECK (risk_level IN ('low', 'medium', 'high', 'critical')),
    detection_reason   TEXT,
    detection_scores   JSONB,
    assigned_to_id     UUID REFERENCES soc_analysts(id) ON DELETE SET NULL,
    resolved_by_id     UUID REFERENCES soc_analysts(id) ON DELETE SET NULL,
    resolved_at        TIMESTAMPTZ,
    notes              TEXT,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TRIGGER trg_alerts_updated_at
    BEFORE UPDATE ON alerts
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE INDEX idx_alerts_login_attempt ON alerts(login_attempt_id);
CREATE INDEX idx_alerts_status ON alerts(status);
CREATE INDEX idx_alerts_risk_level ON alerts(risk_level);
CREATE INDEX idx_alerts_assigned_to ON alerts(assigned_to_id);
CREATE INDEX idx_alerts_resolved_by ON alerts(resolved_by_id);
CREATE INDEX idx_alerts_created ON alerts(created_at);
CREATE INDEX idx_alerts_policy ON alerts(policy_version_id);

-- Add FK from login_attempts to alerts (primary_alert_id)
ALTER TABLE login_attempts
    ADD CONSTRAINT fk_login_attempt_primary_alert
    FOREIGN KEY (primary_alert_id) REFERENCES alerts(id) ON DELETE SET NULL;

-- =============================================================================
-- ALERT TIMELINE (SOC Collaboration Audit Trail)
-- =============================================================================

CREATE TABLE IF NOT EXISTS alert_timeline (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    alert_id        UUID NOT NULL REFERENCES alerts(id) ON DELETE CASCADE,
    event_type      TEXT NOT NULL CHECK (event_type IN (
                    'created', 'assigned', 'unassigned', 'acknowledged',
                    'escalated', 'note_added', 'status_changed', 'resolved'
                )),
    actor_id        UUID REFERENCES users(id) ON DELETE SET NULL,
    actor_type      TEXT NOT NULL CHECK (actor_type IN ('user', 'system')),
    old_value       TEXT,
    new_value       TEXT,
    comment         TEXT,
    ip_address      INET,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_alert_timeline_alert ON alert_timeline(alert_id);
CREATE INDEX idx_alert_timeline_created ON alert_timeline(created_at);
CREATE INDEX idx_alert_timeline_actor ON alert_timeline(actor_id);
CREATE INDEX idx_alert_timeline_event_type ON alert_timeline(event_type);

-- =============================================================================
-- AUDIT LOGS (Immutable Audit Trail)
-- =============================================================================

CREATE TABLE IF NOT EXISTS audit_logs (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    request_id    UUID,
    actor_id      UUID REFERENCES users(id) ON DELETE SET NULL,
    actor_type    TEXT NOT NULL CHECK (actor_type IN ('user', 'system')),
    action        TEXT NOT NULL,
    resource      TEXT NOT NULL,
    resource_id   UUID,
    before_state  JSONB,
    after_state   JSONB,
    change_reason TEXT,
    ip_address    INET,
    user_agent    TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_audit_logs_actor ON audit_logs(actor_id);
CREATE INDEX idx_audit_logs_actor_type ON audit_logs(actor_type);
CREATE INDEX idx_audit_logs_action ON audit_logs(action);
CREATE INDEX idx_audit_logs_resource ON audit_logs(resource);
CREATE INDEX idx_audit_logs_created ON audit_logs(created_at);
CREATE INDEX idx_audit_logs_request ON audit_logs(request_id);

-- =============================================================================
-- USER TRUSTED DEVICES (Remember This Device)
-- =============================================================================

CREATE TABLE IF NOT EXISTS user_trusted_devices (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id              UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    device_fingerprint   TEXT NOT NULL,
    device_name          TEXT,
    last_ip              INET,
    last_user_agent      TEXT,
    last_used_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at           TIMESTAMPTZ,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_trusted_device UNIQUE (user_id, device_fingerprint)
);

CREATE INDEX idx_user_trusted_devices_user ON user_trusted_devices(user_id);
CREATE INDEX idx_user_trusted_devices_fingerprint ON user_trusted_devices(device_fingerprint);
CREATE INDEX idx_user_trusted_devices_user_active ON user_trusted_devices(user_id, expires_at)
    WHERE expires_at IS NULL OR expires_at > NOW();

-- =============================================================================
-- SYSTEM SETTINGS (Dynamic Configuration)
-- =============================================================================

CREATE TABLE IF NOT EXISTS system_settings (
    key             TEXT PRIMARY KEY,
    value           TEXT NOT NULL,
    value_type      TEXT NOT NULL DEFAULT 'string'
                        CHECK (value_type IN ('string', 'integer', 'boolean', 'json')),
    description     TEXT,
    category        TEXT NOT NULL DEFAULT 'general'
                        CHECK (category IN ('auth', 'mfa', 'rate_limit', 'detection', 'notification', 'general')),
    updated_by      UUID REFERENCES users(id) ON DELETE SET NULL,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TRIGGER trg_system_settings_updated_at
    BEFORE UPDATE ON system_settings
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE INDEX idx_system_settings_category ON system_settings(category);
CREATE INDEX idx_system_settings_updated_by ON system_settings(updated_by);

-- =============================================================================
-- OUTBOX EVENTS (Transactional Outbox - ADR-002)
-- =============================================================================

CREATE TABLE IF NOT EXISTS outbox_events (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    aggregate_type  TEXT NOT NULL,
    aggregate_id   UUID NOT NULL,
    event_type     TEXT NOT NULL,
    version        INTEGER NOT NULL DEFAULT 1,
    payload        JSONB NOT NULL,
    headers         JSONB,
    status          TEXT NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'processing', 'published', 'failed')),
    retry_count     INTEGER NOT NULL DEFAULT 0,
    max_retries    INTEGER NOT NULL DEFAULT 3,
    last_error     TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    published_at   TIMESTAMPTZ
);

CREATE INDEX idx_outbox_events_pending ON outbox_events(created_at)
    WHERE status IN ('pending', 'processing');
CREATE INDEX idx_outbox_events_aggregate ON outbox_events(aggregate_type, aggregate_id);
CREATE INDEX idx_outbox_events_event_type ON outbox_events(event_type);
CREATE INDEX idx_outbox_events_status ON outbox_events(status);

-- =============================================================================
-- USER NOTIFICATIONS (In-App Notifications)
-- =============================================================================

CREATE TABLE IF NOT EXISTS user_notifications (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    type        TEXT NOT NULL
                    CHECK (type IN (
                        'mfa_success', 'mfa_failed', 'new_login', 'password_changed',
                        'account_locked', 'account_unlocked', 'alert_resolved', 'system'
                    )),
    title       TEXT NOT NULL,
    body        TEXT NOT NULL,
    link        TEXT,
    priority    TEXT NOT NULL DEFAULT 'normal'
                    CHECK (priority IN ('low', 'normal', 'high', 'urgent')),
    read        BOOLEAN NOT NULL DEFAULT FALSE,
    read_at     TIMESTAMPTZ,
    expires_at  TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_user_notifications_user ON user_notifications(user_id);
CREATE INDEX idx_user_notifications_user_unread ON user_notifications(user_id, created_at)
    WHERE read = FALSE;
CREATE INDEX idx_user_notifications_created ON user_notifications(created_at);
CREATE INDEX idx_user_notifications_expires ON user_notifications(expires_at)
    WHERE expires_at IS NOT NULL;
CREATE INDEX idx_user_notifications_type ON user_notifications(type);
CREATE INDEX idx_user_notifications_priority ON user_notifications(priority);

-- =============================================================================
-- RATE LIMITS (Rate Limiting)
-- =============================================================================

CREATE TABLE IF NOT EXISTS rate_limits (
    ip_address   INET NOT NULL,
    action       TEXT NOT NULL,
    count        INTEGER NOT NULL DEFAULT 1,
    max_count    INTEGER NOT NULL DEFAULT 5,
    window_start TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (ip_address, action),

    CONSTRAINT chk_rate_limits_count CHECK (count >= 0),
    CONSTRAINT chk_rate_limits_max CHECK (max_count > 0)
);

CREATE INDEX idx_rate_limits_window ON rate_limits(window_start);

-- =============================================================================
-- SEED DATA: Default Policy Version
-- =============================================================================

INSERT INTO policy_versions (version, description, rules_json, is_active, created_at) VALUES
    (
        'v1.0',
        'Default detection policy for v1',
        '{
            "rules": [
                {"name": "geo_block", "description": "Block logins from high-risk countries", "conditions": {"countries": ["XX"]}, "score": 0.95, "enabled": true},
                {"name": "new_country", "description": "Login from new country for user", "conditions": {"threshold_days": 90}, "score": 0.6, "enabled": true},
                {"name": "asn_reputation", "description": "Low ASN reputation score", "conditions": {"min_reputation": 0.3}, "score": 0.5, "enabled": true},
                {"name": "failed_attempts", "description": "Multiple failed login attempts", "conditions": {"threshold": 3}, "score": 0.7, "enabled": true},
                {"name": "unusual_hour", "description": "Login outside usual hours", "conditions": {"hour_range": [0, 6]}, "score": 0.3, "enabled": true}
            ]
        }'::jsonb,
        TRUE,
        NOW()
    )
ON CONFLICT (version) DO NOTHING;

-- =============================================================================
-- SEED DATA: Default System Settings
-- =============================================================================

INSERT INTO system_settings (key, value, value_type, description, category) VALUES
    -- MFA Settings
    ('mfa.otp_length', '6', 'integer', 'Số chữ số OTP', 'mfa'),
    ('mfa.otp_ttl_seconds', '300', 'integer', 'Thời gian hết hạn OTP (giây)', 'mfa'),
    ('mfa.max_attempts', '3', 'integer', 'Số lần thử OTP tối đa', 'mfa'),
    ('mfa.code_format', 'numeric', 'string', 'Format OTP: numeric hoặc alphanumeric', 'mfa'),

    -- Rate Limiting
    ('rate_limit.login.max_attempts', '5', 'integer', 'Số lần đăng nhập sai tối đa', 'rate_limit'),
    ('rate_limit.login.window_seconds', '300', 'integer', 'Window cho rate limit (giây)', 'rate_limit'),
    ('rate_limit.api.max_requests', '100', 'integer', 'Số request API tối đa', 'rate_limit'),
    ('rate_limit.api.window_seconds', '60', 'integer', 'Window cho API rate limit (giây)', 'rate_limit'),

    -- Detection
    ('detection.rule_weight', '0.4', 'string', 'Trọng số rule engine', 'detection'),
    ('detection.ml_weight', '0.6', 'string', 'Trọng số ML model', 'detection'),
    ('detection.challenge_threshold', '0.3', 'string', 'Ngưỡng challenge MFA', 'detection'),
    ('detection.block_threshold', '0.7', 'string', 'Ngưỡng block', 'detection'),
    ('detection.mfa_once_threshold', '0.5', 'string', 'Ngưỡng MFA 1 lần', 'detection'),

    -- Session
    ('session.access_token_ttl', '900', 'integer', 'Access token TTL (giây)', 'auth'),
    ('session.refresh_token_ttl', '604800', 'integer', 'Refresh token TTL (giây)', 'auth'),
    ('session.max_sessions_per_user', '5', 'integer', 'Số session tối đa/user', 'auth'),
    ('session.trusted_device_ttl_days', '30', 'integer', 'Trusted device TTL (ngày)', 'auth'),

    -- Notification
    ('notification.enabled', 'true', 'boolean', 'Kích hoạt thông báo', 'notification'),
    ('notification.new_login_enabled', 'true', 'boolean', 'Thông báo đăng nhập mới', 'notification')
ON CONFLICT (key) DO NOTHING;

-- =============================================================================
-- COMMENTS
-- =============================================================================

COMMENT ON TABLE users IS 'Core user accounts with authentication and MFA settings.';
COMMENT ON TABLE roles IS 'Role definitions with i18n support.';
COMMENT ON TABLE user_roles IS 'User-role assignments with audit trail.';
COMMENT ON TABLE ip_addresses IS 'Normalized IP address tracking with geolocation.';
COMMENT ON TABLE sessions IS 'Active user sessions with JWT refresh tokens.';
COMMENT ON TABLE mfa_transactions IS 'MFA challenge transactions.';
COMMENT ON TABLE mfa_notifications IS 'MFA notification lifecycle tracking.';
COMMENT ON TABLE policy_versions IS 'Versioned detection rule sets with weights and thresholds.';
COMMENT ON TABLE login_attempts IS 'All login attempts with outcome and risk metadata.';
COMMENT ON TABLE risk_assessments IS 'Per-attempt risk scoring (rule + ML + combined).';
COMMENT ON TABLE detection_logs IS 'Detailed audit trail of detection engine decisions.';
COMMENT ON TABLE soc_analysts IS 'SOC analyst profiles linked to users.';
COMMENT ON TABLE alerts IS 'SOC alerts created from high-risk login attempts.';
COMMENT ON TABLE alert_timeline IS 'Immutable audit trail for all SOC analyst actions on alerts.';
COMMENT ON TABLE audit_logs IS 'Immutable audit trail of all admin and system actions.';
COMMENT ON TABLE user_trusted_devices IS 'Trusted devices that skip MFA on login.';
COMMENT ON TABLE system_settings IS 'Dynamic system configuration values.';
COMMENT ON TABLE outbox_events IS 'Transactional outbox for reliable event publishing.';
COMMENT ON TABLE user_notifications IS 'In-app notifications for users.';
COMMENT ON TABLE rate_limits IS 'Rate limiting counters per IP and action.';

-- =============================================================================
-- 3NF COMPLIANCE NOTES
-- =============================================================================

-- v3.2 fixes from v3.1:
-- 1. alerts.assigned_to/resolved_by → soc_analysts.id (fixes transitive dependency)
-- 2. alert_timeline.actor → actor_id + actor_type (fixes mixed content)
-- 3. audit_logs.actor → actor_id + actor_type (fixes mixed content)
-- 4. sessions.ip_address → ip_address_id (normalizes repeated IP data)

-- CHECK constraints kept for simple enums (status, risk_level, etc.)
-- Reference tables NOT created for these enums to maintain simplicity
