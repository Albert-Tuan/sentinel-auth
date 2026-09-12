-- =============================================================================
-- Sentinel Auth - Database Schema v4 (3NF Normalized)
-- Single-process FastAPI: auth + detection + ML inline
-- All tables in public schema (PostgreSQL default)
--
-- Version: 4.0 - 3NF Normalized
-- Date: 2026-09-12
--
-- CHANGES FROM v3.1:
-- 1. Extracted ENUM values to reference tables (1NF: atomic values)
-- 2. Normalized actor/assigned_to/resolved_by to separate tables (3NF: no transitive)
-- 3. Separated IP address tracking (2NF: separate concerns)
-- 4. Added proper lookup tables for statuses
-- 5. All indexes optimized for common query patterns
-- =============================================================================

-- =============================================================================
-- EXTENSIONS
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";

-- =============================================================================
-- HELPER: Auto-update updated_at column
-- =============================================================================

CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- =============================================================================
-- HELPER: Generate slugs for reference tables
-- =============================================================================

CREATE OR REPLACE FUNCTION generate_slug(name TEXT)
RETURNS TEXT AS $$
BEGIN
    RETURN lower(regexp_replace(name, '[^a-zA-Z0-9]+', '_', 'g'));
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- =============================================================================
-- REFERENCE TABLES (Lookup Tables - Seed Data Only)
-- =============================================================================

-- =============================================================================
-- REF_ROLES - Role Definitions
-- =============================================================================

CREATE TABLE ref_roles (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    name_vi         TEXT NOT NULL,
    description     TEXT,
    sort_order      INTEGER NOT NULL DEFAULT 0,
    is_system       BOOLEAN NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_ref_roles_sort ON ref_roles(sort_order);

INSERT INTO ref_roles (id, name, name_vi, description, sort_order, is_system) VALUES
    ('USER',             'User',             'Người dùng',             'Default role - everyone has it', 1, TRUE),
    ('SECURITY_ADMIN',  'Security Admin',   'Quản trị viên bảo mật',  'Manage accounts, rules, audit logs', 2, FALSE),
    ('SOC_ANALYST',      'SOC Analyst',      'Phân tích viên SOC',       'View, acknowledge, resolve alerts', 3, FALSE),
    ('SECURITY_MANAGER', 'Security Manager', 'Quản lý bảo mật',        'Dashboard, reports', 4, FALSE);

-- =============================================================================
-- REF_USER_STATUS - User Status Values
-- =============================================================================

CREATE TABLE ref_user_status (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    description     TEXT,
    sort_order      INTEGER NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_ref_user_status_sort ON ref_user_status(sort_order);

INSERT INTO ref_user_status (id, name, description, sort_order) VALUES
    ('active',    'Active',    'User can login',    1),
    ('suspended', 'Suspended', 'Temporarily suspended', 2),
    ('locked',    'Locked',   'Account locked due to security', 3);

-- =============================================================================
-- REF_MFA_TYPE - MFA Transaction Types
-- =============================================================================

CREATE TABLE ref_mfa_type (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    description     TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO ref_mfa_type (id, name, description) VALUES
    ('one_time',   'One Time',   'OTP used once then invalidated'),
    ('persistent', 'Persistent', 'TOTP app - persistent verification');

-- =============================================================================
-- REF_MFA_TRANSACTION_STATUS - MFA Transaction Status
-- =============================================================================

CREATE TABLE ref_mfa_transaction_status (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    description     TEXT,
    sort_order      INTEGER NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_ref_mfa_tx_status_sort ON ref_mfa_transaction_status(sort_order);

INSERT INTO ref_mfa_transaction_status (id, name, description, sort_order) VALUES
    ('pending',   'Pending',   'Awaiting OTP verification', 1),
    ('completed', 'Completed', 'Successfully verified', 2),
    ('expired',   'Expired',   'OTP has expired', 3),
    ('failed',    'Failed',    'Max attempts reached', 4);

-- =============================================================================
-- REF_MFA_CHANNEL - MFA Notification Channels
-- =============================================================================

CREATE TABLE ref_mfa_channel (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    description     TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO ref_mfa_channel (id, name, description) VALUES
    ('email',   'Email',   'Email OTP'),
    ('sms',     'SMS',     'SMS OTP'),
    ('totp',    'TOTP',    'Time-based OTP (Authenticator App)');

-- =============================================================================
-- REF_LOGIN_OUTCOME - Login Attempt Outcomes
-- =============================================================================

CREATE TABLE ref_login_outcome (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    name_vi         TEXT NOT NULL,
    is_success      BOOLEAN NOT NULL,
    is_mfa_related  BOOLEAN NOT NULL DEFAULT FALSE,
    sort_order      INTEGER NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_ref_login_outcome_success ON ref_login_outcome(is_success);
CREATE INDEX idx_ref_login_outcome_sort ON ref_login_outcome(sort_order);

INSERT INTO ref_login_outcome (id, name, name_vi, is_success, is_mfa_related, sort_order) VALUES
    ('success',       'Success',           'Thành công',           TRUE,  FALSE, 1),
    ('failure',       'Failure',           'Thất bại',              FALSE, FALSE, 2),
    ('mfa_required',  'MFA Required',      'Yêu cầu MFA',           FALSE, TRUE,  3),
    ('mfa_success',   'MFA Success',       'MFA thành công',        TRUE,  TRUE,  4),
    ('mfa_failed',    'MFA Failed',        'MFA thất bại',          FALSE, TRUE,  5),
    ('blocked',       'Blocked',           'Bị chặn',               FALSE, FALSE, 6),
    ('locked',        'Locked',            'Bị khóa',               FALSE, FALSE, 7),
    ('rate_limited',  'Rate Limited',      'Bị giới hạn rate',       FALSE, FALSE, 8);

-- =============================================================================
-- REF_RISK_LEVEL - Risk Level Values
-- =============================================================================

CREATE TABLE ref_risk_level (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    name_vi         TEXT NOT NULL,
    score_min       NUMERIC(3,2) NOT NULL,
    score_max       NUMERIC(3,2) NOT NULL,
    color_hex       TEXT,
    sort_order      INTEGER NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_ref_risk_level_score ON ref_risk_level(score_min, score_max);
CREATE INDEX idx_ref_risk_level_sort ON ref_risk_level(sort_order);

INSERT INTO ref_risk_level (id, name, name_vi, score_min, score_max, color_hex, sort_order) VALUES
    ('low',      'Low',      'Thấp',      0.00, 0.25, '#10B981', 1),
    ('medium',   'Medium',   'Trung bình', 0.25, 0.50, '#F59E0B', 2),
    ('high',     'High',     'Cao',       0.50, 0.75, '#EF4444', 3),
    ('critical', 'Critical', 'Nguy hiểm', 0.75, 1.00, '#DC2626', 4);

-- =============================================================================
-- REF_DETECTION_DECISION - Detection Decisions
-- =============================================================================

CREATE TABLE ref_detection_decision (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    name_vi         TEXT NOT NULL,
    description     TEXT,
    sort_order      INTEGER NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_ref_detection_decision_sort ON ref_detection_decision(sort_order);

INSERT INTO ref_detection_decision (id, name, name_vi, description, sort_order) VALUES
    ('allow',     'Allow',    'Cho phép',     'Login allowed without challenge', 1),
    ('challenge', 'Challenge','Thách thức',   'MFA challenge required', 2),
    ('block',     'Block',    'Chặn',         'Login blocked', 3);

-- =============================================================================
-- REF_ALERT_STATUS - Alert Status Values
-- =============================================================================

CREATE TABLE ref_alert_status (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    name_vi         TEXT NOT NULL,
    is_open         BOOLEAN NOT NULL,
    is_resolved     BOOLEAN NOT NULL,
    sort_order      INTEGER NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_ref_alert_status_open ON ref_alert_status(is_open);
CREATE INDEX idx_ref_alert_status_sort ON ref_alert_status(sort_order);

INSERT INTO ref_alert_status (id, name, name_vi, is_open, is_resolved, sort_order) VALUES
    ('open',           'Open',           'Mở',            TRUE,  FALSE, 1),
    ('acknowledged',   'Acknowledged',   'Đã tiếp nhận',   TRUE,  FALSE, 2),
    ('resolved',       'Resolved',       'Đã giải quyết',  FALSE, TRUE,  3),
    ('false_positive', 'False Positive', 'Dương tính giả', FALSE, TRUE,  4);

-- =============================================================================
-- REF_ALERT_EVENT_TYPE - Alert Timeline Event Types
-- =============================================================================

CREATE TABLE ref_alert_event_type (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    name_vi         TEXT NOT NULL,
    description     TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO ref_alert_event_type (id, name, name_vi, description) VALUES
    ('created',          'Created',           'Tạo mới',         'Alert được tạo bởi hệ thống'),
    ('assigned',         'Assigned',          'Đã gán',          'Alert được gán cho analyst'),
    ('unassigned',       'Unassigned',        'Bỏ gán',          'Alert bị bỏ gán'),
    ('acknowledged',     'Acknowledged',      'Đã tiếp nhận',     'Analyst tiếp nhận alert'),
    ('escalated',        'Escalated',         'Đã leo thang',     'Alert được leo thang'),
    ('note_added',       'Note Added',        'Đã thêm ghi chú',  'Analyst thêm ghi chú'),
    ('status_changed',   'Status Changed',   'Đổi trạng thái',  'Trạng thái thay đổi'),
    ('resolved',         'Resolved',          'Đã giải quyết',    'Alert được giải quyết');

-- =============================================================================
-- REF_DETECTION_STAGE - Detection Stage Values
-- =============================================================================

CREATE TABLE ref_detection_stage (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    description     TEXT,
    sort_order      INTEGER NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_ref_detection_stage_sort ON ref_detection_stage(sort_order);

INSERT INTO ref_detection_stage (id, name, description, sort_order) VALUES
    ('rule',     'Rule Engine',     'Rule-based detection', 1),
    ('ml',       'ML Model',        'Machine learning detection', 2),
    ('combined', 'Combined Score',  'Combined scoring', 3),
    ('action',   'Security Action', 'Action taken', 4);

-- =============================================================================
-- REF_ML_STATUS - ML Inference Status
-- =============================================================================

CREATE TABLE ref_ml_status (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    description     TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO ref_ml_status (id, name, description) VALUES
    ('success',     'Success',     'ML inference completed successfully'),
    ('unavailable', 'Unavailable', 'ML service is unavailable'),
    ('error',      'Error',       'ML inference encountered an error');

-- =============================================================================
-- REF_NOTIFICATION_TYPE - Notification Types
-- =============================================================================

CREATE TABLE ref_notification_type (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    name_vi         TEXT NOT NULL,
    description     TEXT,
    default_priority TEXT NOT NULL DEFAULT 'normal',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_ref_notification_priority ON ref_notification_type(default_priority);

INSERT INTO ref_notification_type (id, name, name_vi, description, default_priority) VALUES
    ('mfa_success',        'MFA Success',        'MFA thành công',        'MFA verification succeeded', 'normal'),
    ('mfa_failed',         'MFA Failed',         'MFA thất bại',          'MFA verification failed', 'high'),
    ('new_login',          'New Login',          'Đăng nhập mới',         'New login detected', 'normal'),
    ('password_changed',   'Password Changed',   'Đổi mật khẩu',         'Password was changed', 'high'),
    ('account_locked',     'Account Locked',     'Tài khoản bị khóa',     'Account was locked', 'urgent'),
    ('account_unlocked',   'Account Unlocked',   'Tài khoản được mở khóa', 'Account was unlocked', 'high'),
    ('alert_resolved',    'Alert Resolved',     'Alert đã giải quyết',    'Security alert was resolved', 'normal'),
    ('system',            'System',             'Hệ thống',               'System notification', 'low');

-- =============================================================================
-- REF_NOTIFICATION_PRIORITY - Notification Priority Levels
-- =============================================================================

CREATE TABLE ref_notification_priority (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    sort_order      INTEGER NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_ref_notification_prio_sort ON ref_notification_priority(sort_order);

INSERT INTO ref_notification_priority (id, name, sort_order) VALUES
    ('low',    'Low',    1),
    ('normal', 'Normal', 2),
    ('high',   'High',   3),
    ('urgent', 'Urgent', 4);

-- =============================================================================
-- REF_SETTINGS_CATEGORY - System Settings Categories
-- =============================================================================

CREATE TABLE ref_settings_category (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    name_vi         TEXT NOT NULL,
    description     TEXT,
    sort_order      INTEGER NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_ref_settings_cat_sort ON ref_settings_category(sort_order);

INSERT INTO ref_settings_category (id, name, name_vi, description, sort_order) VALUES
    ('auth',        'Authentication', 'Xác thực',        'Session and token settings', 1),
    ('mfa',         'MFA',           'MFA',              'Multi-factor authentication', 2),
    ('rate_limit',  'Rate Limiting', 'Giới hạn rate',    'Rate limiting settings', 3),
    ('detection',   'Detection',     'Phát hiện',        'Detection engine settings', 4),
    ('notification','Notification',  'Thông báo',         'Notification settings', 5),
    ('general',     'General',       'Chung',             'General settings', 6);

-- =============================================================================
-- REF_SETTINGS_VALUE_TYPE - Settings Value Types
-- =============================================================================

CREATE TABLE ref_settings_value_type (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    description     TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO ref_settings_value_type (id, name, description) VALUES
    ('string',  'String',  'Plain text value'),
    ('integer', 'Integer', 'Whole number'),
    ('boolean', 'Boolean', 'True/false value'),
    ('json',    'JSON',    'JSON object or array');

-- =============================================================================
-- REF_OUTBOX_STATUS - Outbox Event Status
-- =============================================================================

CREATE TABLE ref_outbox_status (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    description     TEXT,
    sort_order      INTEGER NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_ref_outbox_status_sort ON ref_outbox_status(sort_order);

INSERT INTO ref_outbox_status (id, name, description, sort_order) VALUES
    ('pending',    'Pending',    'Waiting to be processed', 1),
    ('processing', 'Processing', 'Currently being processed', 2),
    ('published',  'Published', 'Successfully published', 3),
    ('failed',     'Failed',    'Processing failed', 4);

-- =============================================================================
-- CORE TABLES
-- =============================================================================

-- =============================================================================
-- USERS - Core User Entity (Normalized)
-- =============================================================================

CREATE TABLE users (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username                TEXT NOT NULL,
    password_hash           TEXT NOT NULL,
    email                   TEXT,
    full_name               TEXT,
    status_id               TEXT NOT NULL DEFAULT 'active'
                                REFERENCES ref_user_status(id),
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
CREATE INDEX idx_users_status ON users(status_id);

-- =============================================================================
-- USER_ROLES - User Role Assignments (Junction Table)
-- =============================================================================

CREATE TABLE user_roles (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role_id         TEXT NOT NULL REFERENCES ref_roles(id),
    assigned_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    assigned_by     UUID REFERENCES users(id) ON DELETE SET NULL,

    CONSTRAINT uq_user_role UNIQUE (user_id, role_id)
);

CREATE INDEX idx_user_roles_user ON user_roles(user_id);
CREATE INDEX idx_user_roles_role ON user_roles(role_id);
CREATE INDEX idx_user_roles_assigned_by ON user_roles(assigned_by);

-- =============================================================================
-- SESSIONS - JWT Token Management
-- =============================================================================

CREATE TABLE sessions (
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
-- IP_ADDRESSES - Normalized IP Address Tracking
-- =============================================================================

CREATE TABLE ip_addresses (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ip_address      INET NOT NULL,
    country_code    TEXT,
    country_name    TEXT,
    city            TEXT,
    isp             TEXT,
    asn             TEXT,
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
-- MFA_TRANSACTIONS - MFA Challenge (Renamed from pre_auth_transactions)
-- =============================================================================

CREATE TABLE mfa_transactions (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    mfa_type_id         TEXT NOT NULL DEFAULT 'one_time'
                           REFERENCES ref_mfa_type(id),
    status_id           TEXT NOT NULL DEFAULT 'pending'
                           REFERENCES ref_mfa_transaction_status(id),
    bound_ip_id         UUID REFERENCES ip_addresses(id) ON DELETE SET NULL,
    notification_id     UUID,
    fail_count          INTEGER NOT NULL DEFAULT 0,
    expires_at          TIMESTAMPTZ NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TRIGGER trg_mfa_transactions_updated_at
    BEFORE UPDATE ON mfa_transactions
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE INDEX idx_mfa_tx_user ON mfa_transactions(user_id);
CREATE INDEX idx_mfa_tx_status ON mfa_transactions(status_id);
CREATE INDEX idx_mfa_tx_expires ON mfa_transactions(expires_at);
CREATE INDEX idx_mfa_tx_user_status_expires ON mfa_transactions(user_id, status_id, expires_at);
CREATE INDEX idx_mfa_tx_ip ON mfa_transactions(bound_ip_id);

-- =============================================================================
-- MFA_NOTIFICATIONS - MFA Notification Lifecycle
-- =============================================================================

CREATE TABLE mfa_notifications (
    id                         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    mfa_transaction_id          UUID NOT NULL REFERENCES mfa_transactions(id) ON DELETE CASCADE,
    channel_id                 TEXT NOT NULL DEFAULT 'email'
                                  REFERENCES ref_mfa_channel(id),
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

CREATE INDEX idx_mfa_notif_tx ON mfa_notifications(mfa_transaction_id);
CREATE INDEX idx_mfa_notif_recipient ON mfa_notifications(recipient);
CREATE INDEX idx_mfa_notif_expires ON mfa_notifications(expires_at);

-- Add FK from mfa_transactions to mfa_notifications
ALTER TABLE mfa_transactions
    ADD CONSTRAINT fk_mfa_tx_notification
    FOREIGN KEY (notification_id) REFERENCES mfa_notifications(id) ON DELETE SET NULL;

-- =============================================================================
-- RATE_LIMITS - Rate Limiting (Composite PK)
-- =============================================================================

CREATE TABLE rate_limits (
    ip_address_id    UUID NOT NULL REFERENCES ip_addresses(id) ON DELETE CASCADE,
    action           TEXT NOT NULL,
    count            INTEGER NOT NULL DEFAULT 1,
    max_count        INTEGER NOT NULL DEFAULT 5,
    window_start     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (ip_address_id, action),

    CONSTRAINT chk_rate_count CHECK (count >= 0),
    CONSTRAINT chk_rate_max CHECK (max_count > 0)
);

CREATE INDEX idx_rate_limits_window ON rate_limits(window_start);

-- =============================================================================
-- POLICY_VERSIONS - Detection Rules Versioning
-- =============================================================================

CREATE TABLE policy_versions (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    version             TEXT NOT NULL UNIQUE,
    description         TEXT,
    rules_json          JSONB NOT NULL,
    weights_json        JSONB NOT NULL DEFAULT '{"rule": 0.4, "ml": 0.6}',
    thresholds_json     JSONB NOT NULL DEFAULT '{"challenge": 0.3, "block": 0.7}',
    is_active           BOOLEAN NOT NULL DEFAULT FALSE,
    created_by_user_id  UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    activated_at        TIMESTAMPTZ,
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
-- LOGIN_ATTEMPTS - Audit Trail & Detection Source (Normalized)
-- =============================================================================

CREATE TABLE login_attempts (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id               UUID REFERENCES users(id) ON DELETE SET NULL,
    username_attempted    TEXT,
    occurred_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    outcome_id            TEXT NOT NULL REFERENCES ref_login_outcome(id),
    source_ip_id          UUID REFERENCES ip_addresses(id) ON DELETE SET NULL,
    user_agent            TEXT,
    rate_limited          BOOLEAN NOT NULL DEFAULT FALSE,
    policy_version_id     UUID REFERENCES policy_versions(id) ON DELETE SET NULL,
    request_id            UUID NOT NULL DEFAULT gen_random_uuid(),
    detection_features    JSONB,
    primary_alert_id      UUID,
    risk_level_id         TEXT REFERENCES ref_risk_level(id),
    mfa_used              BOOLEAN NOT NULL DEFAULT FALSE,
    detection_decision_id TEXT REFERENCES ref_detection_decision(id),
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TRIGGER trg_login_attempts_updated_at
    BEFORE UPDATE ON login_attempts
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE INDEX idx_login_user ON login_attempts(user_id);
CREATE INDEX idx_login_occurred ON login_attempts(occurred_at);
CREATE INDEX idx_login_outcome ON login_attempts(outcome_id);
CREATE INDEX idx_login_risk_level ON login_attempts(risk_level_id);
CREATE INDEX idx_login_request ON login_attempts(request_id);
CREATE INDEX idx_login_username ON login_attempts(username_attempted);
CREATE INDEX idx_login_source_ip ON login_attempts(source_ip_id);
CREATE INDEX idx_login_policy ON login_attempts(policy_version_id);

-- =============================================================================
-- RISK_ASSESSMENTS - Per Login Attempt (1:1 Relationship)
-- =============================================================================

CREATE TABLE risk_assessments (
    id                     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    login_attempt_id       UUID NOT NULL REFERENCES login_attempts(id) ON DELETE CASCADE,
    policy_version_id      UUID REFERENCES policy_versions(id) ON DELETE SET NULL,
    rule_score             NUMERIC(5,4),
    anomaly_score          NUMERIC(5,4),
    ml_score               NUMERIC(5,4),
    ml_status_id           TEXT REFERENCES ref_ml_status(id),
    ml_model_version       TEXT,
    rule_hits              JSONB,
    ml_features_used       JSONB,
    combined_score         NUMERIC(5,4),
    risk_level_id          TEXT REFERENCES ref_risk_level(id),
    detection_decision_id  TEXT REFERENCES ref_detection_decision(id),
    created_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_risk_assessment_login UNIQUE (login_attempt_id)
);

CREATE INDEX idx_risk_login ON risk_assessments(login_attempt_id);
CREATE INDEX idx_risk_risk_level ON risk_assessments(risk_level_id);
CREATE INDEX idx_risk_policy ON risk_assessments(policy_version_id);
CREATE INDEX idx_risk_ml_status ON risk_assessments(ml_status_id);

-- =============================================================================
-- DETECTION_LOGS - Audit Trail for Detection Engine
-- =============================================================================

CREATE TABLE detection_logs (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    login_attempt_id UUID REFERENCES login_attempts(id) ON DELETE SET NULL,
    request_id       UUID,
    stage_id         TEXT NOT NULL REFERENCES ref_detection_stage(id),
    stage_detail     TEXT,
    rule_id          UUID,
    rule_name        TEXT,
    score            NUMERIC(5,4),
    decision_id      TEXT REFERENCES ref_detection_decision(id),
    reason           TEXT,
    details          JSONB,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_detect_log_login ON detection_logs(login_attempt_id);
CREATE INDEX idx_detect_log_stage ON detection_logs(stage_id);
CREATE INDEX idx_detect_log_request ON detection_logs(request_id);
CREATE INDEX idx_detect_log_decision ON detection_logs(decision_id);

-- =============================================================================
-- SOC_ANALYSTS - SOC Analyst Profiles (Normalized from assigned_to)
-- =============================================================================

CREATE TABLE soc_analysts (
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

CREATE INDEX idx_soc_analyst_user ON soc_analysts(user_id);
CREATE INDEX idx_soc_analyst_active ON soc_analysts(is_active);

-- =============================================================================
-- ALERTS - SOC Workflow (Normalized)
-- =============================================================================

CREATE TABLE alerts (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    login_attempt_id   UUID NOT NULL REFERENCES login_attempts(id) ON DELETE CASCADE,
    policy_version_id  UUID REFERENCES policy_versions(id) ON DELETE SET NULL,
    request_id         UUID,
    status_id          TEXT NOT NULL DEFAULT 'open'
                         REFERENCES ref_alert_status(id),
    risk_level_id      TEXT REFERENCES ref_risk_level(id),
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

CREATE INDEX idx_alerts_login ON alerts(login_attempt_id);
CREATE INDEX idx_alerts_status ON alerts(status_id);
CREATE INDEX idx_alerts_risk_level ON alerts(risk_level_id);
CREATE INDEX idx_alerts_assigned_to ON alerts(assigned_to_id);
CREATE INDEX idx_alerts_resolved_by ON alerts(resolved_by_id);
CREATE INDEX idx_alerts_created ON alerts(created_at);
CREATE INDEX idx_alerts_policy ON alerts(policy_version_id);

-- Add FK from login_attempts to alerts (primary_alert_id)
ALTER TABLE login_attempts
    ADD CONSTRAINT fk_login_primary_alert
    FOREIGN KEY (primary_alert_id) REFERENCES alerts(id) ON DELETE SET NULL;

-- =============================================================================
-- ALERT_TIMELINE - SOC Collaboration Audit Trail
-- =============================================================================

CREATE TABLE alert_timeline (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    alert_id        UUID NOT NULL REFERENCES alerts(id) ON DELETE CASCADE,
    event_type_id   TEXT NOT NULL REFERENCES ref_alert_event_type(id),
    actor_id        UUID REFERENCES users(id) ON DELETE SET NULL,
    actor_type      TEXT NOT NULL CHECK (actor_type IN ('user', 'system')),
    old_value       TEXT,
    new_value       TEXT,
    comment         TEXT,
    ip_address_id   UUID REFERENCES ip_addresses(id) ON DELETE SET NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_timeline_alert ON alert_timeline(alert_id);
CREATE INDEX idx_timeline_created ON alert_timeline(created_at);
CREATE INDEX idx_timeline_actor ON alert_timeline(actor_id);
CREATE INDEX idx_timeline_event_type ON alert_timeline(event_type_id);

-- =============================================================================
-- USER_TRUSTED_DEVICES - Remember This Device
-- =============================================================================

CREATE TABLE user_trusted_devices (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id              UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    device_fingerprint   TEXT NOT NULL,
    device_name          TEXT,
    last_ip_id           UUID REFERENCES ip_addresses(id) ON DELETE SET NULL,
    last_user_agent      TEXT,
    last_used_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at           TIMESTAMPTZ,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_trusted_device UNIQUE (user_id, device_fingerprint)
);

CREATE INDEX idx_trusted_user ON user_trusted_devices(user_id);
CREATE INDEX idx_trusted_fingerprint ON user_trusted_devices(device_fingerprint);
CREATE INDEX idx_trusted_user_active ON user_trusted_devices(user_id, expires_at)
    WHERE expires_at IS NULL OR expires_at > NOW();
CREATE INDEX idx_trusted_ip ON user_trusted_devices(last_ip_id);

-- =============================================================================
-- SYSTEM_SETTINGS - Dynamic Configuration
-- =============================================================================

CREATE TABLE system_settings (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    key             TEXT NOT NULL UNIQUE,
    value           TEXT NOT NULL,
    value_type_id   TEXT NOT NULL DEFAULT 'string'
                        REFERENCES ref_settings_value_type(id),
    description     TEXT,
    category_id     TEXT NOT NULL DEFAULT 'general'
                        REFERENCES ref_settings_category(id),
    updated_by      UUID REFERENCES users(id) ON DELETE SET NULL,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TRIGGER trg_system_settings_updated_at
    BEFORE UPDATE ON system_settings
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE INDEX idx_settings_key ON system_settings(key);
CREATE INDEX idx_settings_category ON system_settings(category_id);
CREATE INDEX idx_settings_updated_by ON system_settings(updated_by);

-- =============================================================================
-- OUTBOX_EVENTS - Transactional Outbox (ADR-002)
-- =============================================================================

CREATE TABLE outbox_events (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    aggregate_type  TEXT NOT NULL,
    aggregate_id   UUID NOT NULL,
    event_type     TEXT NOT NULL,
    version        INTEGER NOT NULL DEFAULT 1,
    payload        JSONB NOT NULL,
    headers         JSONB,
    status_id      TEXT NOT NULL DEFAULT 'pending'
                      REFERENCES ref_outbox_status(id),
    retry_count     INTEGER NOT NULL DEFAULT 0,
    max_retries    INTEGER NOT NULL DEFAULT 3,
    last_error     TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    published_at   TIMESTAMPTZ
);

CREATE INDEX idx_outbox_pending ON outbox_events(created_at)
    WHERE status_id IN ('pending', 'processing');
CREATE INDEX idx_outbox_aggregate ON outbox_events(aggregate_type, aggregate_id);
CREATE INDEX idx_outbox_event_type ON outbox_events(event_type);
CREATE INDEX idx_outbox_status ON outbox_events(status_id);

-- =============================================================================
-- USER_NOTIFICATIONS - In-App Notifications
-- =============================================================================

CREATE TABLE user_notifications (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    type_id     TEXT NOT NULL REFERENCES ref_notification_type(id),
    title       TEXT NOT NULL,
    body        TEXT NOT NULL,
    link        TEXT,
    priority_id TEXT NOT NULL DEFAULT 'normal'
                  REFERENCES ref_notification_priority(id),
    read        BOOLEAN NOT NULL DEFAULT FALSE,
    read_at     TIMESTAMPTZ,
    expires_at  TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_notif_user ON user_notifications(user_id);
CREATE INDEX idx_notif_user_unread ON user_notifications(user_id, created_at)
    WHERE read = FALSE;
CREATE INDEX idx_notif_created ON user_notifications(created_at);
CREATE INDEX idx_notif_expires ON user_notifications(expires_at)
    WHERE expires_at IS NOT NULL;
CREATE INDEX idx_notif_type ON user_notifications(type_id);
CREATE INDEX idx_notif_priority ON user_notifications(priority_id);

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

INSERT INTO system_settings (key, value, description, category_id) VALUES
    -- MFA Settings
    ('mfa.otp_length', '6', 'Số chữ số OTP', 'mfa'),
    ('mfa.otp_ttl_seconds', '300', 'Thời gian hết hạn OTP (giây)', 'mfa'),
    ('mfa.max_attempts', '3', 'Số lần thử OTP tối đa', 'mfa'),
    ('mfa.code_format', 'numeric', 'Format OTP: numeric hoặc alphanumeric', 'mfa'),

    -- Rate Limiting
    ('rate_limit.login.max_attempts', '5', 'Số lần đăng nhập sai tối đa', 'rate_limit'),
    ('rate_limit.login.window_seconds', '300', 'Window cho rate limit (giây)', 'rate_limit'),
    ('rate_limit.api.max_requests', '100', 'Số request API tối đa', 'rate_limit'),
    ('rate_limit.api.window_seconds', '60', 'Window cho API rate limit (giây)', 'rate_limit'),

    -- Detection
    ('detection.rule_weight', '0.4', 'Trọng số rule engine', 'detection'),
    ('detection.ml_weight', '0.6', 'Trọng số ML model', 'detection'),
    ('detection.challenge_threshold', '0.3', 'Ngưỡng challenge MFA', 'detection'),
    ('detection.block_threshold', '0.7', 'Ngưỡng block', 'detection'),
    ('detection.mfa_once_threshold', '0.5', 'Ngưỡng MFA 1 lần', 'detection'),

    -- Session
    ('session.access_token_ttl', '900', 'Access token TTL (giây)', 'auth'),
    ('session.refresh_token_ttl', '604800', 'Refresh token TTL (giây)', 'auth'),
    ('session.max_sessions_per_user', '5', 'Số session tối đa/user', 'auth'),
    ('session.trusted_device_ttl_days', '30', 'Trusted device TTL (ngày)', 'auth'),

    -- Notification
    ('notification.enabled', 'true', 'Kích hoạt thông báo', 'notification'),
    ('notification.new_login_enabled', 'true', 'Thông báo đăng nhập mới', 'notification')
ON CONFLICT (key) DO NOTHING;

-- =============================================================================
-- COMMENTS
-- =============================================================================

COMMENT ON TABLE users IS 'Core user accounts with authentication and MFA settings.';
COMMENT ON TABLE sessions IS 'Active user sessions with JWT refresh tokens.';
COMMENT ON TABLE ip_addresses IS 'Normalized IP address tracking with geolocation.';
COMMENT ON TABLE mfa_transactions IS 'MFA challenge transactions.';
COMMENT ON TABLE mfa_notifications IS 'MFA notification lifecycle tracking.';
COMMENT ON TABLE login_attempts IS 'All login attempts with outcome and risk metadata.';
COMMENT ON TABLE risk_assessments IS 'Per-attempt risk scoring (rule + ML + combined).';
COMMENT ON TABLE policy_versions IS 'Versioned detection rule sets with weights and thresholds.';
COMMENT ON TABLE detection_logs IS 'Detailed audit trail of detection engine decisions.';
COMMENT ON TABLE alerts IS 'SOC alerts created from high-risk login attempts.';
COMMENT ON TABLE alert_timeline IS 'Immutable audit trail for all SOC analyst actions on alerts.';
COMMENT ON TABLE soc_analysts IS 'SOC analyst profiles.';
COMMENT ON TABLE user_trusted_devices IS 'Trusted devices that skip MFA on login.';
COMMENT ON TABLE system_settings IS 'Dynamic system configuration values.';
COMMENT ON TABLE outbox_events IS 'Transactional outbox for reliable event publishing (ADR-002).';
COMMENT ON TABLE user_notifications IS 'In-app notifications for users.';

-- =============================================================================
-- VERIFICATION QUERIES (Run these to verify 3NF compliance)
-- =============================================================================

-- Verify no duplicate column names across tables
-- SELECT column_name, COUNT(*) as cnt FROM information_schema.columns
-- WHERE table_schema = 'public'
-- GROUP BY column_name HAVING COUNT(*) > 1;

-- Verify all foreign keys exist
-- SELECT
--     tc.table_name, kcu.column_name,
--     ccu.table_name AS foreign_table_name,
--     ccu.column_name AS foreign_column_name
-- FROM information_schema.table_constraints AS tc
-- JOIN information_schema.key_column_usage AS kcu
--     ON tc.constraint_name = kcu.constraint_name
-- JOIN information_schema.constraint_column_usage AS ccu
--     ON ccu.constraint_name = tc.constraint_name
-- WHERE tc.constraint_type = 'FOREIGN KEY'
-- AND tc.table_schema = 'public';
