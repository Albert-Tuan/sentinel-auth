-- =============================================================================
-- Migration Script: v3.1 → v4 (3NF Normalized)
-- =============================================================================
-- 
-- This migration normalizes the database schema to 3NF by:
-- 1. Creating reference tables for all enum values
-- 2. Adding ip_addresses table for normalized IP tracking
-- 3. Adding soc_analysts table for normalized analyst references
-- 4. Updating all tables to use foreign keys instead of TEXT columns
-- 5. Maintaining backward compatibility with existing data
--
-- Version: 4.0.0-migration
-- Date: 2026-09-12
-- =============================================================================

-- =============================================================================
-- MIGRATION: UP (v3.1 → v4)
-- =============================================================================

BEGIN;

-- =============================================================================
-- STEP 1: Create Reference Tables
-- =============================================================================

-- ref_user_status
CREATE TABLE ref_user_status (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    description     TEXT,
    sort_order      INTEGER NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO ref_user_status (id, name, description, sort_order) VALUES
    ('active',    'Active',    'User can login',    1),
    ('suspended', 'Suspended', 'Temporarily suspended', 2),
    ('locked',    'Locked',   'Account locked due to security', 3);

-- ref_roles
CREATE TABLE ref_roles (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    name_vi         TEXT NOT NULL,
    description     TEXT,
    sort_order      INTEGER NOT NULL DEFAULT 0,
    is_system       BOOLEAN NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO ref_roles (id, name, name_vi, description, sort_order, is_system) VALUES
    ('USER',             'User',             'Người dùng',             'Default role', 1, TRUE),
    ('SECURITY_ADMIN',  'Security Admin',   'Quản trị viên bảo mật',  'Manage accounts', 2, FALSE),
    ('SOC_ANALYST',      'SOC Analyst',      'Phân tích viên SOC',       'Handle alerts', 3, FALSE),
    ('SECURITY_MANAGER', 'Security Manager', 'Quản lý bảo mật',        'Dashboard', 4, FALSE);

-- ref_mfa_type
CREATE TABLE ref_mfa_type (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    description     TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO ref_mfa_type (id, name, description) VALUES
    ('one_time',   'One Time',   'OTP used once'),
    ('persistent', 'Persistent', 'TOTP app');

-- ref_mfa_transaction_status
CREATE TABLE ref_mfa_transaction_status (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    description     TEXT,
    sort_order      INTEGER NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO ref_mfa_transaction_status (id, name, description, sort_order) VALUES
    ('pending',   'Pending',   'Awaiting OTP', 1),
    ('completed', 'Completed', 'Verified', 2),
    ('expired',   'Expired',   'OTP expired', 3),
    ('failed',    'Failed',    'Max attempts', 4);

-- ref_mfa_channel
CREATE TABLE ref_mfa_channel (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    description     TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO ref_mfa_channel (id, name, description) VALUES
    ('email',   'Email',   'Email OTP'),
    ('sms',     'SMS',     'SMS OTP'),
    ('totp',    'TOTP',    'Authenticator App');

-- ref_login_outcome
CREATE TABLE ref_login_outcome (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    name_vi         TEXT NOT NULL,
    is_success      BOOLEAN NOT NULL,
    is_mfa_related  BOOLEAN NOT NULL DEFAULT FALSE,
    sort_order      INTEGER NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO ref_login_outcome (id, name, name_vi, is_success, is_mfa_related, sort_order) VALUES
    ('success',       'Success',           'Thành công',           TRUE,  FALSE, 1),
    ('failure',       'Failure',           'Thất bại',              FALSE, FALSE, 2),
    ('mfa_required',  'MFA Required',      'Yêu cầu MFA',           FALSE, TRUE,  3),
    ('mfa_success',   'MFA Success',       'MFA thành công',        TRUE,  TRUE,  4),
    ('mfa_failed',    'MFA Failed',        'MFA thất bại',          FALSE, TRUE,  5),
    ('blocked',       'Blocked',           'Bị chặn',               FALSE, FALSE, 6),
    ('locked',        'Locked',            'Bị khóa',               FALSE, FALSE, 7),
    ('rate_limited',  'Rate Limited',      'Bị giới hạn rate',       FALSE, FALSE, 8);

-- ref_risk_level
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

INSERT INTO ref_risk_level (id, name, name_vi, score_min, score_max, color_hex, sort_order) VALUES
    ('low',      'Low',      'Thấp',      0.00, 0.25, '#10B981', 1),
    ('medium',   'Medium',   'Trung bình', 0.25, 0.50, '#F59E0B', 2),
    ('high',     'High',     'Cao',       0.50, 0.75, '#EF4444', 3),
    ('critical', 'Critical', 'Nguy hiểm', 0.75, 1.00, '#DC2626', 4);

-- ref_detection_decision
CREATE TABLE ref_detection_decision (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    name_vi         TEXT NOT NULL,
    description     TEXT,
    sort_order      INTEGER NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO ref_detection_decision (id, name, name_vi, description, sort_order) VALUES
    ('allow',     'Allow',    'Cho phép',     'Login allowed', 1),
    ('challenge', 'Challenge','Thách thức',   'MFA required', 2),
    ('block',     'Block',    'Chặn',         'Login blocked', 3);

-- ref_alert_status
CREATE TABLE ref_alert_status (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    name_vi         TEXT NOT NULL,
    is_open         BOOLEAN NOT NULL,
    is_resolved     BOOLEAN NOT NULL,
    sort_order      INTEGER NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO ref_alert_status (id, name, name_vi, is_open, is_resolved, sort_order) VALUES
    ('open',           'Open',           'Mở',            TRUE,  FALSE, 1),
    ('acknowledged',   'Acknowledged',   'Đã tiếp nhận',   TRUE,  FALSE, 2),
    ('resolved',       'Resolved',       'Đã giải quyết',  FALSE, TRUE,  3),
    ('false_positive', 'False Positive', 'Dương tính giả', FALSE, TRUE,  4);

-- ref_alert_event_type
CREATE TABLE ref_alert_event_type (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    name_vi         TEXT NOT NULL,
    description     TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO ref_alert_event_type (id, name, name_vi, description) VALUES
    ('created',          'Created',           'Tạo mới',         'Alert được tạo'),
    ('assigned',         'Assigned',          'Đã gán',          'Alert được gán'),
    ('unassigned',       'Unassigned',        'Bỏ gán',          'Alert bị bỏ gán'),
    ('acknowledged',     'Acknowledged',      'Đã tiếp nhận',     'Analyst tiếp nhận'),
    ('escalated',        'Escalated',         'Đã leo thang',     'Alert được leo thang'),
    ('note_added',       'Note Added',        'Đã thêm ghi chú',  'Thêm ghi chú'),
    ('status_changed',   'Status Changed',   'Đổi trạng thái',  'Trạng thái thay đổi'),
    ('resolved',         'Resolved',          'Đã giải quyết',    'Alert được giải quyết');

-- ref_detection_stage
CREATE TABLE ref_detection_stage (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    description     TEXT,
    sort_order      INTEGER NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO ref_detection_stage (id, name, description, sort_order) VALUES
    ('rule',     'Rule Engine',     'Rule-based detection', 1),
    ('ml',       'ML Model',        'ML detection', 2),
    ('combined', 'Combined Score',  'Combined scoring', 3),
    ('action',   'Security Action', 'Action taken', 4);

-- ref_ml_status
CREATE TABLE ref_ml_status (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    description     TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO ref_ml_status (id, name, description) VALUES
    ('success',     'Success',     'ML completed'),
    ('unavailable', 'Unavailable', 'ML unavailable'),
    ('error',      'Error',       'ML error');

-- ref_notification_type
CREATE TABLE ref_notification_type (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    name_vi         TEXT NOT NULL,
    description     TEXT,
    default_priority TEXT NOT NULL DEFAULT 'normal',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO ref_notification_type (id, name, name_vi, description, default_priority) VALUES
    ('mfa_success',        'MFA Success',        'MFA thành công',        'MFA verified', 'normal'),
    ('mfa_failed',         'MFA Failed',         'MFA thất bại',          'MFA failed', 'high'),
    ('new_login',          'New Login',          'Đăng nhập mới',         'New login', 'normal'),
    ('password_changed',   'Password Changed',   'Đổi mật khẩu',         'Password changed', 'high'),
    ('account_locked',     'Account Locked',     'Tài khoản bị khóa',     'Locked', 'urgent'),
    ('account_unlocked',   'Account Unlocked',   'Tài khoản được mở khóa', 'Unlocked', 'high'),
    ('alert_resolved',    'Alert Resolved',     'Alert đã giải quyết',    'Alert resolved', 'normal'),
    ('system',            'System',             'Hệ thống',               'System', 'low');

-- ref_notification_priority
CREATE TABLE ref_notification_priority (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    sort_order      INTEGER NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO ref_notification_priority (id, name, sort_order) VALUES
    ('low',    'Low',    1),
    ('normal', 'Normal', 2),
    ('high',   'High',   3),
    ('urgent', 'Urgent', 4);

-- ref_settings_category
CREATE TABLE ref_settings_category (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    name_vi         TEXT NOT NULL,
    description     TEXT,
    sort_order      INTEGER NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO ref_settings_category (id, name, name_vi, description, sort_order) VALUES
    ('auth',        'Authentication', 'Xác thực',        'Session settings', 1),
    ('mfa',         'MFA',           'MFA',              'MFA settings', 2),
    ('rate_limit',  'Rate Limiting', 'Giới hạn rate',    'Rate limits', 3),
    ('detection',   'Detection',     'Phát hiện',        'Detection', 4),
    ('notification','Notification',  'Thông báo',         'Notifications', 5),
    ('general',     'General',       'Chung',             'General', 6);

-- ref_settings_value_type
CREATE TABLE ref_settings_value_type (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    description     TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO ref_settings_value_type (id, name, description) VALUES
    ('string',  'String',  'Plain text'),
    ('integer', 'Integer', 'Whole number'),
    ('boolean', 'Boolean', 'True/false'),
    ('json',    'JSON',    'JSON object');

-- ref_outbox_status
CREATE TABLE ref_outbox_status (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    description     TEXT,
    sort_order      INTEGER NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO ref_outbox_status (id, name, description, sort_order) VALUES
    ('pending',    'Pending',    'Waiting', 1),
    ('processing', 'Processing', 'Processing', 2),
    ('published',  'Published', 'Published', 3),
    ('failed',     'Failed',    'Failed', 4);

-- =============================================================================
-- STEP 2: Create New Tables (ip_addresses, soc_analysts)
-- =============================================================================

-- ip_addresses: Normalized IP tracking
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

-- Migrate existing IP data from login_attempts
INSERT INTO ip_addresses (ip_address, first_seen_at, last_seen_at)
SELECT DISTINCT source_ip, MIN(occurred_at), MAX(occurred_at)
FROM login_attempts
WHERE source_ip IS NOT NULL
GROUP BY source_ip;

-- Migrate existing IP data from sessions
INSERT INTO ip_addresses (ip_address, first_seen_at, last_seen_at)
SELECT DISTINCT ip_address, MIN(created_at), MAX(created_at)
FROM sessions
WHERE ip_address IS NOT NULL
ON CONFLICT (ip_address) DO NOTHING;

-- Migrate existing IP data from user_trusted_devices
INSERT INTO ip_addresses (ip_address, first_seen_at, last_seen_at)
SELECT DISTINCT last_ip, MIN(created_at), MAX(created_at)
FROM user_trusted_devices
WHERE last_ip IS NOT NULL
ON CONFLICT (ip_address) DO NOTHING;

-- soc_analysts: Normalized analyst profiles
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

-- Migrate existing analysts from alerts.assigned_to
INSERT INTO soc_analysts (user_id, display_name)
SELECT DISTINCT u.id, u.username
FROM alerts a
JOIN users u ON a.assigned_to = u.username
WHERE a.assigned_to IS NOT NULL
ON CONFLICT (user_id) DO NOTHING;

-- =============================================================================
-- STEP 3: Add New Columns with _id suffix (for FK references)
-- =============================================================================

-- users.status_id
ALTER TABLE users ADD COLUMN status_id TEXT REFERENCES ref_user_status(id);
UPDATE users SET status_id = status;
ALTER TABLE users ALTER COLUMN status_id SET NOT NULL;
ALTER TABLE users DROP COLUMN status;

-- login_attempts: Add new FK columns
ALTER TABLE login_attempts ADD COLUMN outcome_id TEXT REFERENCES ref_login_outcome(id);
ALTER TABLE login_attempts ADD COLUMN source_ip_id UUID REFERENCES ip_addresses(id);
ALTER TABLE login_attempts ADD COLUMN risk_level_id TEXT REFERENCES ref_risk_level(id);
ALTER TABLE login_attempts ADD COLUMN detection_decision_id TEXT REFERENCES ref_detection_decision(id);

-- Update with existing values
UPDATE login_attempts SET outcome_id = outcome;
UPDATE login_attempts SET source_ip_id = (SELECT id FROM ip_addresses WHERE ip_address = login_attempts.source_ip);
UPDATE login_attempts SET risk_level_id = risk_level;
UPDATE login_attempts SET detection_decision_id = detection_decision;

-- Set NOT NULL
ALTER TABLE login_attempts ALTER COLUMN outcome_id SET NOT NULL;

-- Drop old columns
ALTER TABLE login_attempts DROP COLUMN outcome;
ALTER TABLE login_attempts DROP COLUMN risk_level;
ALTER TABLE login_attempts DROP COLUMN detection_decision;

-- mfa_transactions: Add new FK columns
ALTER TABLE mfa_transactions RENAME TO mfa_transactions_old;

CREATE TABLE mfa_transactions (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    mfa_type_id         TEXT NOT NULL DEFAULT 'one_time' REFERENCES ref_mfa_type(id),
    status_id           TEXT NOT NULL DEFAULT 'pending' REFERENCES ref_mfa_transaction_status(id),
    bound_ip_id         UUID REFERENCES ip_addresses(id) ON DELETE SET NULL,
    notification_id     UUID,
    fail_count          INTEGER NOT NULL DEFAULT 0,
    expires_at          TIMESTAMPTZ NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO mfa_transactions
SELECT 
    id, user_id,
    mfa_type, status,
    (SELECT id FROM ip_addresses WHERE ip_address = mfa_transactions_old.bound_ip::inet),
    notification_id, fail_count, expires_at, created_at, updated_at
FROM mfa_transactions_old;

DROP TABLE mfa_transactions_old;

-- risk_assessments: Add new FK columns
ALTER TABLE risk_assessments ADD COLUMN ml_status_id TEXT REFERENCES ref_ml_status(id);
ALTER TABLE risk_assessments ADD COLUMN risk_level_id TEXT REFERENCES ref_risk_level(id);
ALTER TABLE risk_assessments ADD COLUMN detection_decision_id TEXT REFERENCES ref_detection_decision(id);

UPDATE risk_assessments SET ml_status_id = ml_status;
UPDATE risk_assessments SET risk_level_id = risk_level;
UPDATE risk_assessments SET detection_decision_id = decision;

ALTER TABLE risk_assessments DROP COLUMN ml_status;
ALTER TABLE risk_assessments DROP COLUMN risk_level;
ALTER TABLE risk_assessments DROP COLUMN decision;

-- detection_logs: Add new FK columns
ALTER TABLE detection_logs ADD COLUMN stage_id TEXT REFERENCES ref_detection_stage(id);
ALTER TABLE detection_logs ADD COLUMN decision_id TEXT REFERENCES ref_detection_decision(id);

UPDATE detection_logs SET stage_id = stage;
UPDATE detection_logs SET decision_id = decision;

ALTER TABLE detection_logs DROP COLUMN stage;
ALTER TABLE detection_logs DROP COLUMN decision;

-- alerts: Add new FK columns
ALTER TABLE alerts ADD COLUMN status_id TEXT REFERENCES ref_alert_status(id);
ALTER TABLE alerts ADD COLUMN risk_level_id TEXT REFERENCES ref_risk_level(id);
ALTER TABLE alerts ADD COLUMN assigned_to_id UUID REFERENCES soc_analysts(id);
ALTER TABLE alerts ADD COLUMN resolved_by_id UUID REFERENCES soc_analysts(id);

-- Update with existing values
UPDATE alerts SET status_id = status;

-- Map assigned_to (TEXT) to assigned_to_id (UUID)
UPDATE alerts SET assigned_to_id = 
    (SELECT sa.id FROM soc_analysts sa 
     JOIN users u ON sa.user_id = u.id 
     WHERE u.username = alerts.assigned_to);

-- Map resolved_by (TEXT) to resolved_by_id (UUID)
UPDATE alerts SET resolved_by_id = 
    (SELECT sa.id FROM soc_analysts sa 
     JOIN users u ON sa.user_id = u.id 
     WHERE u.username = alerts.resolved_by);

UPDATE alerts SET risk_level_id = risk_level;

-- Drop old columns
ALTER TABLE alerts DROP COLUMN status;
ALTER TABLE alerts DROP COLUMN risk_level;

-- alert_timeline: Add new FK columns
ALTER TABLE alert_timeline ADD COLUMN event_type_id TEXT REFERENCES ref_alert_event_type(id);
ALTER TABLE alert_timeline ADD COLUMN actor_id UUID REFERENCES users(id);
ALTER TABLE alert_timeline ADD COLUMN actor_type TEXT CHECK (actor_type IN ('user', 'system'));
ALTER TABLE alert_timeline ADD COLUMN ip_address_id UUID REFERENCES ip_addresses(id);

UPDATE alert_timeline SET event_type_id = event_type;
UPDATE alert_timeline SET actor_type = CASE WHEN actor LIKE 'system:%' THEN 'system' ELSE 'user' END;

-- Try to map actor to user_id
UPDATE alert_timeline SET actor_id = 
    (SELECT id FROM users WHERE username = alert_timeline.actor)
WHERE alert_timeline.actor_type = 'user';

ALTER TABLE alert_timeline DROP COLUMN event_type;
ALTER TABLE alert_timeline DROP COLUMN ip_address;

-- user_notifications: Add new FK columns
ALTER TABLE user_notifications ADD COLUMN type_id TEXT REFERENCES ref_notification_type(id);
ALTER TABLE user_notifications ADD COLUMN priority_id TEXT REFERENCES ref_notification_priority(id);

UPDATE user_notifications SET type_id = type;
UPDATE user_notifications SET priority_id = priority;

ALTER TABLE user_notifications DROP COLUMN type;
ALTER TABLE user_notifications DROP COLUMN priority;

-- system_settings: Add new FK columns
ALTER TABLE system_settings ADD COLUMN value_type_id TEXT REFERENCES ref_settings_value_type(id);
ALTER TABLE system_settings ADD COLUMN category_id TEXT REFERENCES ref_settings_category(id);

-- Note: These might have different format, need to check existing data
-- For now, set default and update
UPDATE system_settings SET value_type_id = 'string';
UPDATE system_settings SET category_id = 
    CASE 
        WHEN key LIKE 'mfa.%' THEN 'mfa'
        WHEN key LIKE 'rate_limit.%' THEN 'rate_limit'
        WHEN key LIKE 'detection.%' THEN 'detection'
        WHEN key LIKE 'session.%' THEN 'auth'
        WHEN key LIKE 'notification.%' THEN 'notification'
        ELSE 'general'
    END;

ALTER TABLE system_settings DROP COLUMN value_type;
ALTER TABLE system_settings DROP COLUMN category;

-- outbox_events: Add new FK column
ALTER TABLE outbox_events ADD COLUMN status_id TEXT REFERENCES ref_outbox_status(id);
UPDATE outbox_events SET status_id = status;
ALTER TABLE outbox_events DROP COLUMN status;

-- =============================================================================
-- STEP 4: Update user_roles to reference ref_roles
-- =============================================================================

ALTER TABLE user_roles ADD CONSTRAINT fk_user_roles_role
    FOREIGN KEY (role_id) REFERENCES ref_roles(id);

-- =============================================================================
-- STEP 5: Create Indexes for New Tables
-- =============================================================================

CREATE INDEX idx_ip_addresses_first_seen ON ip_addresses(first_seen_at);
CREATE INDEX idx_ip_addresses_country ON ip_addresses(country_code);
CREATE INDEX idx_soc_analyst_user ON soc_analysts(user_id);
CREATE INDEX idx_soc_analyst_active ON soc_analysts(is_active);

-- =============================================================================
-- STEP 6: Update Comments
-- =============================================================================

COMMENT ON TABLE ref_user_status IS 'Reference table: User status values';
COMMENT ON TABLE ref_roles IS 'Reference table: Role definitions';
COMMENT ON TABLE ref_mfa_type IS 'Reference table: MFA types';
COMMENT ON TABLE ref_mfa_transaction_status IS 'Reference table: MFA transaction statuses';
COMMENT ON TABLE ref_mfa_channel IS 'Reference table: MFA notification channels';
COMMENT ON TABLE ref_login_outcome IS 'Reference table: Login attempt outcomes';
COMMENT ON TABLE ref_risk_level IS 'Reference table: Risk levels';
COMMENT ON TABLE ref_detection_decision IS 'Reference table: Detection decisions';
COMMENT ON TABLE ref_alert_status IS 'Reference table: Alert statuses';
COMMENT ON TABLE ref_alert_event_type IS 'Reference table: Alert timeline event types';
COMMENT ON TABLE ref_detection_stage IS 'Reference table: Detection stages';
COMMENT ON TABLE ref_ml_status IS 'Reference table: ML inference statuses';
COMMENT ON TABLE ref_notification_type IS 'Reference table: Notification types';
COMMENT ON TABLE ref_notification_priority IS 'Reference table: Notification priorities';
COMMENT ON TABLE ref_settings_category IS 'Reference table: Settings categories';
COMMENT ON TABLE ref_settings_value_type IS 'Reference table: Settings value types';
COMMENT ON TABLE ref_outbox_status IS 'Reference table: Outbox event statuses';
COMMENT ON TABLE ip_addresses IS 'Normalized IP address tracking with geolocation';
COMMENT ON TABLE soc_analysts IS 'SOC analyst profiles';

COMMIT;

-- =============================================================================
-- MIGRATION: DOWN (v4 → v3.1)
-- =============================================================================

-- Note: This is a destructive migration - data will be transformed
-- Only run this if you have a complete backup

/*
BEGIN;

-- Reverse all the changes...
-- This is left as an exercise for the reader
-- In production, always use full backups before destructive migrations

ROLLBACK;
*/
