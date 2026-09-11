-- Sentinel Auth Schema
-- All tables in public schema (PostgreSQL default)
-- Supports 3 workflows: MFA pre-auth, async detection, SOC investigation

-- =============================================================================
-- USERS
-- =============================================================================
CREATE TABLE IF NOT EXISTS users (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username    TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    email       TEXT,
    status      TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'suspended', 'locked')),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
CREATE INDEX IF NOT EXISTS idx_users_email    ON users(email);
CREATE INDEX IF NOT EXISTS idx_users_status    ON users(status);

-- =============================================================================
-- SESSIONS
-- =============================================================================
CREATE TABLE IF NOT EXISTS sessions (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id            UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    access_token_hash  TEXT NOT NULL,
    refresh_token_hash TEXT,
    expires_at         TIMESTAMPTZ NOT NULL,
    revoked_at         TIMESTAMPTZ,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sessions_user_id      ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_access_hash  ON sessions(access_token_hash);
CREATE INDEX IF NOT EXISTS idx_sessions_expires_at   ON sessions(expires_at);

-- =============================================================================
-- PRE-AUTH TRANSACTIONS (MFA)
-- =============================================================================
CREATE TABLE IF NOT EXISTS pre_auth_transactions (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id      UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at   TIMESTAMPTZ NOT NULL,
    status       TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'completed', 'expired', 'failed')),
    bound_ip_hash TEXT,
    mfa_code_hash TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_pre_auth_user_id   ON pre_auth_transactions(user_id);
CREATE INDEX IF NOT EXISTS idx_pre_auth_status   ON pre_auth_transactions(status);
CREATE INDEX IF NOT EXISTS idx_pre_auth_expires  ON pre_auth_transactions(expires_at);

-- =============================================================================
-- LOGIN ATTEMPTS
-- =============================================================================
CREATE TABLE IF NOT EXISTS login_attempts (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID REFERENCES users(id) ON DELETE SET NULL,
    occurred_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    outcome         TEXT NOT NULL CHECK (outcome IN ('success', 'failure', 'mfa_required', 'mfa_success', 'mfa_failed', 'blocked')),
    source_ip       INET,
    policy_version  TEXT,
    detected        BOOLEAN NOT NULL DEFAULT FALSE,
    request_id      UUID,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_login_attempts_user_id    ON login_attempts(user_id);
CREATE INDEX IF NOT EXISTS idx_login_attempts_occurred  ON login_attempts(occurred_at);
CREATE INDEX IF NOT EXISTS idx_login_attempts_outcome    ON login_attempts(outcome);
CREATE INDEX IF NOT EXISTS idx_login_attempts_detected   ON login_attempts(detected);

-- =============================================================================
-- RISK ASSESSMENTS
-- =============================================================================
CREATE TABLE IF NOT EXISTS risk_assessments (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    login_attempt_id UUID NOT NULL REFERENCES login_attempts(id) ON DELETE CASCADE,
    rule_score       NUMERIC(5,4),
    anomaly_score    NUMERIC(5,4),
    ml_score         NUMERIC(5,4),
    ml_status        TEXT CHECK (ml_status IN ('success', 'unavailable', 'error')),
    risk_level       TEXT CHECK (risk_level IN ('low', 'medium', 'high', 'critical')),
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_risk_login_attempt_id ON risk_assessments(login_attempt_id);
CREATE INDEX IF NOT EXISTS idx_risk_risk_level       ON risk_assessments(risk_level);

-- =============================================================================
-- ALERTS
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
CREATE INDEX IF NOT EXISTS idx_alerts_status           ON alerts(status);
CREATE INDEX IF NOT EXISTS idx_alerts_risk_level       ON alerts(risk_level);

-- =============================================================================
-- RULE VERSIONS (for audit and versioning of detection rules)
-- =============================================================================
CREATE TABLE IF NOT EXISTS rule_versions (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    version    TEXT NOT NULL UNIQUE,
    rules_json JSONB NOT NULL,
    created_by TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_rule_versions_version ON rule_versions(version);

-- =============================================================================
-- DETECTION LOGS (for audit trail / replay)
-- =============================================================================
CREATE TABLE IF NOT EXISTS detection_logs (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    login_attempt_id UUID REFERENCES login_attempts(id) ON DELETE SET NULL,
    stage      TEXT NOT NULL CHECK (stage IN ('rule', 'ml', 'combined')),
    score      NUMERIC(5,4),
    decision   TEXT CHECK (decision IN ('allow', 'challenge', 'block')),
    reason     TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_detection_logs_login_id ON detection_logs(login_attempt_id);
CREATE INDEX IF NOT EXISTS idx_detection_logs_stage   ON detection_logs(stage);
