-- Sentinel Auth Schema
-- FastAPI single-process: auth + detection + ML inline
-- All tables in public schema (PostgreSQL default)

-- =============================================================================
-- USERS & ROLES
-- =============================================================================

CREATE TABLE IF NOT EXISTS users (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username                TEXT NOT NULL UNIQUE,
    password_hash           TEXT NOT NULL,
    email                   TEXT,
    status                  TEXT NOT NULL DEFAULT 'active'
                                CHECK (status IN ('active', 'suspended', 'locked')),
    admin_mfa_required      BOOLEAN NOT NULL DEFAULT FALSE,
    detection_mfa_once      BOOLEAN NOT NULL DEFAULT FALSE,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_users_username    ON users(username);
CREATE INDEX IF NOT EXISTS idx_users_email       ON users(email);
CREATE INDEX IF NOT EXISTS idx_users_status      ON users(status);

-- Roles: USER is default, others are special (assigned by admin)
CREATE TABLE IF NOT EXISTS roles (
    id    TEXT PRIMARY KEY,   -- 'USER', 'SECURITY_ADMIN', 'SOC_ANALYST', 'SECURITY_MANAGER'
    name  TEXT NOT NULL
);
INSERT INTO roles (id, name) VALUES
    ('USER',              'Người dùng'),
    ('SECURITY_ADMIN',    'Quản trị viên bảo mật'),
    ('SOC_ANALYST',       'Phân tích viên SOC'),
    ('SECURITY_MANAGER',  'Quản lý bảo mật')
ON CONFLICT (id) DO NOTHING;

-- Many-to-many: user has many roles
CREATE TABLE IF NOT EXISTS user_roles (
    user_id    UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role_id    TEXT NOT NULL REFERENCES roles(id),
    assigned_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, role_id)
);

CREATE INDEX IF NOT EXISTS idx_user_roles_user_id ON user_roles(user_id);
CREATE INDEX IF NOT EXISTS idx_user_roles_role_id ON user_roles(role_id);

-- =============================================================================
-- SESSIONS & TOKENS
-- =============================================================================

CREATE TABLE IF NOT EXISTS sessions (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id            UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    access_token_hash  TEXT NOT NULL,
    refresh_token_hash  TEXT,
    expires_at         TIMESTAMPTZ NOT NULL,
    revoked_at         TIMESTAMPTZ,
    ip_address         INET,
    user_agent          TEXT,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sessions_user_id      ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_access_hash  ON sessions(access_token_hash);
CREATE INDEX IF NOT EXISTS idx_sessions_expires_at  ON sessions(expires_at);

-- =============================================================================
-- PRE-AUTH TRANSACTIONS (MFA)
-- OTP: 6 digits, 5 minutes validity, max 3 attempts
-- =============================================================================

CREATE TABLE IF NOT EXISTS pre_auth_transactions (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id        UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at     TIMESTAMPTZ NOT NULL,
    status         TEXT NOT NULL DEFAULT 'pending'
                      CHECK (status IN ('pending', 'completed', 'expired', 'failed')),
    bound_ip_hash  TEXT,
    mfa_code_hash  TEXT NOT NULL,        -- Argon2id hash of 6-digit OTP
    fail_count     INTEGER NOT NULL DEFAULT 0,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_pre_auth_user_id   ON pre_auth_transactions(user_id);
CREATE INDEX IF NOT EXISTS idx_pre_auth_status   ON pre_auth_transactions(status);
CREATE INDEX IF NOT EXISTS idx_pre_auth_expires  ON pre_auth_transactions(expires_at);

-- =============================================================================
-- RATE LIMITING (login per IP)
-- Max 5 requests per minute per IP
-- =============================================================================

CREATE TABLE IF NOT EXISTS rate_limits (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ip_address INET NOT NULL,
    action     TEXT NOT NULL,             -- 'login', 'mfa_challenge', ...
    count      INTEGER NOT NULL DEFAULT 1,
    window_start TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (ip_address, action)
);

CREATE INDEX IF NOT EXISTS idx_rate_limits_ip     ON rate_limits(ip_address);
CREATE INDEX IF NOT EXISTS idx_rate_limits_window ON rate_limits(window_start);

-- =============================================================================
-- LOGIN ATTEMPTS (audit + detection source)
-- =============================================================================

CREATE TABLE IF NOT EXISTS login_attempts (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID REFERENCES users(id) ON DELETE SET NULL,
    occurred_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    outcome         TEXT NOT NULL
                      CHECK (outcome IN (
                          'success', 'failure', 'mfa_required',
                          'mfa_success', 'mfa_failed', 'blocked', 'locked'
                      )),
    source_ip       INET,
    user_agent      TEXT,
    risk_level      TEXT CHECK (risk_level IN ('low', 'medium', 'high', 'critical')),
    mfa_used        BOOLEAN NOT NULL DEFAULT FALSE,
    rule_score      NUMERIC(5,4),
    anomaly_score   NUMERIC(5,4),
    ml_score        NUMERIC(5,4),
    detection_decision TEXT CHECK (detection_decision IN ('allow', 'challenge', 'block')),
    alert_id        UUID,
    request_id      UUID,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_login_attempts_user_id   ON login_attempts(user_id);
CREATE INDEX IF NOT EXISTS idx_login_attempts_occurred  ON login_attempts(occurred_at);
CREATE INDEX IF NOT EXISTS idx_login_attempts_outcome   ON login_attempts(outcome);
CREATE INDEX IF NOT EXISTS idx_login_attempts_risk_level ON login_attempts(risk_level);

-- =============================================================================
-- RISK ASSESSMENTS (per login attempt)
-- =============================================================================

CREATE TABLE IF NOT EXISTS risk_assessments (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    login_attempt_id UUID NOT NULL REFERENCES login_attempts(id) ON DELETE CASCADE,
    rule_score       NUMERIC(5,4),
    anomaly_score    NUMERIC(5,4),
    ml_score         NUMERIC(5,4),
    ml_status        TEXT CHECK (ml_status IN ('success', 'unavailable', 'error')),
    ml_model_version TEXT,
    risk_level       TEXT CHECK (risk_level IN ('low', 'medium', 'high', 'critical')),
    decision         TEXT CHECK (decision IN ('allow', 'challenge', 'block')),
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_risk_login_attempt_id ON risk_assessments(login_attempt_id);
CREATE INDEX IF NOT EXISTS idx_risk_risk_level       ON risk_assessments(risk_level);

-- =============================================================================
-- ALERTS (SOC workflow)
-- =============================================================================

CREATE TABLE IF NOT EXISTS alerts (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    login_attempt_id UUID NOT NULL REFERENCES login_attempts(id) ON DELETE CASCADE,
    status           TEXT NOT NULL DEFAULT 'open'
                       CHECK (status IN ('open', 'acknowledged', 'resolved', 'false_positive')),
    risk_level       TEXT CHECK (risk_level IN ('low', 'medium', 'high', 'critical')),
    assigned_to      TEXT,
    resolved_by      TEXT,
    resolved_at      TIMESTAMPTZ,
    notes            TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_alerts_login_attempt_id ON alerts(login_attempt_id);
CREATE INDEX IF NOT EXISTS idx_alerts_status          ON alerts(status);
CREATE INDEX IF NOT EXISTS idx_alerts_risk_level      ON alerts(risk_level);
CREATE INDEX IF NOT EXISTS idx_alerts_assigned_to     ON alerts(assigned_to);

-- =============================================================================
-- RULE VERSIONS (detection rule versioning)
-- =============================================================================

CREATE TABLE IF NOT EXISTS rule_versions (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    version    TEXT NOT NULL UNIQUE,        -- e.g. 'v1.0', 'v2.1'
    rules_json JSONB NOT NULL,               -- Full rule set as JSON
    is_active  BOOLEAN NOT NULL DEFAULT FALSE,
    created_by TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    activated_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_rule_versions_version  ON rule_versions(version);
CREATE INDEX IF NOT EXISTS idx_rule_versions_is_active ON rule_versions(is_active);

-- =============================================================================
-- DETECTION LOGS (audit trail for ML/rule decisions)
-- =============================================================================

CREATE TABLE IF NOT EXISTS detection_logs (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    login_attempt_id UUID REFERENCES login_attempts(id) ON DELETE SET NULL,
    stage            TEXT NOT NULL CHECK (stage IN ('rule', 'ml', 'combined', 'action')),
    rule_name        TEXT,                          -- which rule was evaluated
    score            NUMERIC(5,4),
    decision         TEXT CHECK (decision IN ('allow', 'challenge', 'block')),
    reason           TEXT,
    details          JSONB,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_detection_logs_login_id ON detection_logs(login_attempt_id);
CREATE INDEX IF NOT EXISTS idx_detection_logs_stage   ON detection_logs(stage);

-- =============================================================================
-- AUDIT LOGS (all admin + system actions)
-- Never stores: password, OTP, JWT, plaintext email
-- =============================================================================

CREATE TABLE IF NOT EXISTS audit_logs (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    actor         TEXT NOT NULL,          -- user_id or 'system:detection-engine'
    action        TEXT NOT NULL,          -- 'role_assigned', 'user_locked', 'session_revoked', 'alert_resolved', ...
    resource      TEXT NOT NULL,          -- 'user', 'session', 'role', 'alert', 'rule_version', ...
    resource_id   UUID,
    before_state  JSONB,
    after_state   JSONB,
    reason        TEXT,
    ip_address    INET,
    user_agent    TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_audit_logs_actor       ON audit_logs(actor);
CREATE INDEX IF NOT EXISTS idx_audit_logs_action      ON audit_logs(action);
CREATE INDEX IF NOT EXISTS idx_audit_logs_resource    ON audit_logs(resource);
CREATE INDEX IF NOT EXISTS idx_audit_logs_created_at ON audit_logs(created_at);
