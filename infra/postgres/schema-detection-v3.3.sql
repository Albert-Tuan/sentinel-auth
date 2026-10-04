-- =============================================================================
-- Sentinel Auth - Detection Engine Database Schema v3.3
-- Detection Engine has its own database
--
-- Version: 3.3
-- Date: 2026-09-13
-- Updated: 2026-10-04 (canonical rules + score aggregation)
-- Based on: v3.2 and Detection Engine documentation
-- Canonical decisions: docs/DECISIONS-DETECTION-v3.3.md
-- =============================================================================

-- =============================================================================
-- EXTENSIONS
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- =============================================================================
-- HELPER FUNCTIONS
-- =============================================================================

CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- =============================================================================
-- POLICIES (Detection Rules with JSONB Storage)
-- =============================================================================

CREATE TABLE IF NOT EXISTS policies (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    version             TEXT NOT NULL UNIQUE,
    name                TEXT,
    description         TEXT,
    rules               JSONB NOT NULL DEFAULT '[]',
    /*
    CANONICAL rule structure - see docs/DECISIONS-DETECTION-v3.3.md section 1
    7 required fields per rule: name, field, operator, value, weight, score, enabled

    [
        {
            "name": "unusual_hour",          // unique within policy
            "field": "hour_of_day",          // one of the 6 features (UC-DE-02)
            "operator": "not_between",       // == != > >= < <= in between not_between
            "value": [7, 22],                // number | bool | [min,max] | [allowed...]
            "weight": 0.30,                  // 0..1, confidence of the rule
            "score": 0.80,                   // 0..1, severity when triggered
            "enabled": true,
            "description": "Login outside 07:00-22:59 local time"
        },
        {
            "name": "multiple_failures",
            "field": "fail_count_24h",
            "operator": ">=",
            "value": 3,
            "weight": 0.40,
            "score": 0.90,
            "enabled": true,
            "description": "3 or more failed attempts in the last 24h"
        }
    ]

    Valid "field" values (exactly these 6):
      hour_of_day, fail_count_24h, ip_change_rate_7d,
      new_device, average_login_interval_seconds, deviation_score

    An unknown "field" must NOT raise: skip the rule, exclude it from the
    normalization denominator, and log reason="unknown_feature".
    */
    config              JSONB NOT NULL DEFAULT '{}',
    /*
    CANONICAL config structure - see docs/DECISIONS-DETECTION-v3.3.md section 3
    {
        "weights": {"rule": 0.4, "ml": 0.6},        // rule + ml must sum to 1.0
        "thresholds": {"low": 0.25, "medium": 0.5, "high": 0.75}  // must be non-decreasing
    }
    Invalid config must NOT raise: log reason="invalid_thresholds" and
    fall back to these defaults.
    */
    is_active           BOOLEAN NOT NULL DEFAULT FALSE,
    created_by          UUID,  -- Reference to users.id in core-db
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    activated_at        TIMESTAMPTZ,
    deactivated_at     TIMESTAMPTZ,

    CONSTRAINT chk_single_active_policy
        CHECK (
            NOT (is_active AND EXISTS (
                SELECT 1 FROM policies p2
                WHERE p2.is_active = TRUE AND p2.id != id
            ))
        )
);

CREATE TRIGGER trg_policies_updated_at
    BEFORE UPDATE ON policies
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE INDEX idx_policies_version ON policies(version);
CREATE INDEX idx_policies_active ON policies(is_active) WHERE is_active = TRUE;
CREATE INDEX idx_policies_created_by ON policies(created_by);

-- =============================================================================
-- LOGIN ATTEMPTS (All login events from core-app)
-- =============================================================================

CREATE TABLE IF NOT EXISTS login_attempts (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id              UUID NOT NULL UNIQUE,  -- Idempotency key from core-app
    user_id               UUID,  -- NULL if login failed
    username_attempted    TEXT,
    outcome               TEXT NOT NULL
                            CHECK (outcome IN (
                                'success', 'failure', 'mfa_required',
                                'mfa_success', 'mfa_failed', 'blocked', 'locked', 'rate_limited'
                            )),
    mfa_used              BOOLEAN NOT NULL DEFAULT FALSE,
    ip_address            INET,
    user_agent            TEXT,
    timestamp             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    status                TEXT NOT NULL DEFAULT 'pending'
                            CHECK (status IN ('pending', 'processed', 'failed')),
    policy_id             UUID REFERENCES policies(id) ON DELETE SET NULL,
    request_id            UUID NOT NULL DEFAULT gen_random_uuid(),
    primary_alert_id      UUID,  -- FK added after alerts table
    risk_level            TEXT CHECK (risk_level IN ('low', 'medium', 'high', 'critical')),
    detection_decision    TEXT CHECK (detection_decision IN ('allow', 'challenge', 'block')),
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TRIGGER trg_login_attempts_updated_at
    BEFORE UPDATE ON login_attempts
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE INDEX idx_login_attempts_event_id ON login_attempts(event_id);
CREATE INDEX idx_login_attempts_user_id ON login_attempts(user_id);
CREATE INDEX idx_login_attempts_timestamp ON login_attempts(timestamp);
CREATE INDEX idx_login_attempts_outcome ON login_attempts(outcome);
CREATE INDEX idx_login_attempts_risk_level ON login_attempts(risk_level);
CREATE INDEX idx_login_attempts_request_id ON login_attempts(request_id);
CREATE INDEX idx_login_attempts_username ON login_attempts(username_attempted);
CREATE INDEX idx_login_attempts_ip ON login_attempts(ip_address);
CREATE INDEX idx_login_attempts_policy ON login_attempts(policy_id);
CREATE INDEX idx_login_attempts_status ON login_attempts(status);

-- =============================================================================
-- RISK ASSESSMENTS (Per Login Attempt - 1:1)
-- =============================================================================

CREATE TABLE IF NOT EXISTS risk_assessments (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    login_attempt_id   UUID NOT NULL REFERENCES login_attempts(id) ON DELETE CASCADE,
    policy_id          UUID REFERENCES policies(id) ON DELETE SET NULL,
    rule_score         NUMERIC(5,4),
    ml_score           NUMERIC(5,4),
    combined_score     NUMERIC(5,4),
    ml_status          TEXT CHECK (ml_status IN ('success', 'unavailable', 'error')),
    ml_model_version  TEXT,
    rule_hits          JSONB,
    ml_reason_codes    JSONB,
    ml_features_used   JSONB,
    risk_level         TEXT CHECK (risk_level IN ('low', 'medium', 'high', 'critical')),
    decision           TEXT CHECK (decision IN ('allow', 'challenge', 'block')),
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_risk_assessment_login UNIQUE (login_attempt_id)
);

CREATE INDEX idx_risk_assessments_login ON risk_assessments(login_attempt_id);
CREATE INDEX idx_risk_assessments_risk_level ON risk_assessments(risk_level);
CREATE INDEX idx_risk_assessments_policy ON risk_assessments(policy_id);
CREATE INDEX idx_risk_assessments_ml_status ON risk_assessments(ml_status);

-- =============================================================================
-- DETECTION LOGS (Detailed Audit Trail)
-- =============================================================================

CREATE TABLE IF NOT EXISTS detection_logs (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    login_attempt_id    UUID REFERENCES login_attempts(id) ON DELETE SET NULL,
    request_id          UUID,
    stage               TEXT NOT NULL
                            CHECK (stage IN ('rule_evaluation', 'ml_call', 'scoring', 'action_sent')),
    stage_detail        TEXT,
    rule_id             UUID,
    rule_name           TEXT,
    triggered           BOOLEAN,
    score_contribution  NUMERIC(5,4),
    decision            TEXT CHECK (decision IN ('allow', 'challenge', 'block')),
    reason              TEXT,
    details             JSONB,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_detection_logs_login ON detection_logs(login_attempt_id);
CREATE INDEX idx_detection_logs_stage ON detection_logs(stage);
CREATE INDEX idx_detection_logs_request ON detection_logs(request_id);
CREATE INDEX idx_detection_logs_decision ON detection_logs(decision);
CREATE INDEX idx_detection_logs_triggered ON detection_logs(triggered) WHERE triggered = TRUE;

-- =============================================================================
-- SOC ANALYSTS (Linked to users in core-db)
-- =============================================================================

CREATE TABLE IF NOT EXISTS soc_analysts (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL UNIQUE,  -- Reference to users.id in core-db
    display_name    TEXT,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    max_alerts      INTEGER NOT NULL DEFAULT 50,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
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
    policy_id          UUID REFERENCES policies(id) ON DELETE SET NULL,
    request_id         UUID,
    status             TEXT NOT NULL DEFAULT 'open'
                        CHECK (status IN ('open', 'acknowledged', 'resolved', 'false_positive')),
    risk_level         TEXT CHECK (risk_level IN ('low', 'medium', 'high', 'critical')),
    detection_reason   TEXT,
    detection_scores   JSONB,
    assigned_to_id     UUID REFERENCES soc_analysts(id) ON DELETE SET NULL,
    resolved_by_id     UUID REFERENCES soc_analysts(id) ON DELETE SET NULL,
    resolved_at        TIMESTAMPTZ,
    resolution         TEXT,
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
CREATE INDEX idx_alerts_policy ON alerts(policy_id);

-- Add FK from login_attempts to alerts (primary_alert_id)
ALTER TABLE login_attempts
    ADD CONSTRAINT fk_login_attempt_primary_alert
    FOREIGN KEY (primary_alert_id) REFERENCES alerts(id) ON DELETE SET NULL;

-- =============================================================================
-- ALERT TIMELINE (SOC Action Audit Trail)
-- =============================================================================

CREATE TABLE IF NOT EXISTS alert_timeline (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    alert_id        UUID NOT NULL REFERENCES alerts(id) ON DELETE CASCADE,
    event_type      TEXT NOT NULL CHECK (event_type IN (
                        'created', 'acknowledged', 'assigned', 'unassigned',
                        'escalated', 'note_added', 'status_changed', 'resolved', 'false_positive'
                    )),
    actor_id        UUID,  -- Reference to users.id in core-db
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
-- SEED DATA: Default Policy v1.0
-- CANONICAL - must match docs/DECISIONS-DETECTION-v3.3.md section 1.5
-- Every rule has all 7 required fields: name, field, operator, value, weight, score, enabled
-- Sum of enabled weights = 0.30 + 0.40 + 0.20 + 0.30 = 1.20 (used as normalization denominator)
-- =============================================================================

INSERT INTO policies (version, name, description, rules, config, is_active, created_at) VALUES
    (
        'v1.0',
        'Default Detection Policy',
        'Default policy for v1.0 with basic rules',
        '[
            {
                "name": "unusual_hour",
                "field": "hour_of_day",
                "operator": "not_between",
                "value": [7, 22],
                "weight": 0.30,
                "score": 0.80,
                "enabled": true,
                "description": "Login outside 07:00-22:59 local time"
            },
            {
                "name": "multiple_failures",
                "field": "fail_count_24h",
                "operator": ">=",
                "value": 3,
                "weight": 0.40,
                "score": 0.90,
                "enabled": true,
                "description": "3 or more failed attempts in the last 24h"
            },
            {
                "name": "new_device",
                "field": "new_device",
                "operator": "==",
                "value": true,
                "weight": 0.20,
                "score": 0.50,
                "enabled": true,
                "description": "Login from a device not seen before"
            },
            {
                "name": "high_deviation",
                "field": "deviation_score",
                "operator": ">=",
                "value": 0.70,
                "weight": 0.30,
                "score": 0.70,
                "enabled": true,
                "description": "Behaviour deviates strongly from the user baseline"
            }
        ]'::jsonb,
        '{
            "weights": {"rule": 0.4, "ml": 0.6},
            "thresholds": {"low": 0.25, "medium": 0.5, "high": 0.75}
        }'::jsonb,
        TRUE,
        NOW()
    )
ON CONFLICT (version) DO NOTHING;

-- =============================================================================
-- COMMENTS
-- =============================================================================

COMMENT ON TABLE policies IS 'Detection policies with JSONB rules and config.';
COMMENT ON TABLE login_attempts IS 'All login events received from core-app via HTTP.';
COMMENT ON TABLE risk_assessments IS 'Per-attempt risk scoring (1:1 with login_attempts).';
COMMENT ON TABLE detection_logs IS 'Detailed audit trail for each detection stage.';
COMMENT ON TABLE soc_analysts IS 'SOC analyst profiles linked to users in core-db.';
COMMENT ON TABLE alerts IS 'SOC alerts (1:N with login_attempts via primary_alert_id).';
COMMENT ON TABLE alert_timeline IS 'Immutable audit trail for SOC analyst actions.';

-- =============================================================================
-- DETECTION LOG STAGES EXPLAINED
-- =============================================================================

-- rule_evaluation: Each rule is evaluated (rule_name, triggered, score_contribution)
--   score_contribution = (rule.score * rule.weight) / SUM(weight of all enabled rules)
--   so contributions sum exactly to rule_score (see DECISIONS section 4.5)
-- ml_call: ML Service is called (success/failed/skipped)
-- scoring: Scores are combined (rule_score, ml_score, combined_score)
-- action_sent: Action is sent to core-app (action_type, target)

-- =============================================================================
-- CANONICAL SCORING FORMULAS
-- See docs/DECISIONS-DETECTION-v3.3.md section 2 for the full specification
-- =============================================================================
--
-- STEP 1 - rule_score (0..1)
--   contribution(rule) = rule.score * rule.weight        for enabled+triggered rules
--   rule_score = min(1.0, SUM(contribution) / SUM(weight of ALL enabled rules))
--   If no rules enabled -> rule_score = 0.0
--
-- STEP 2 - ml_score (0..1, NULL when ML unavailable)
--   ml_score = normalized_anomaly_score from ML Service
--   ml_status = 'success' | 'unavailable' (timeout > 5s) | 'error'
--
-- STEP 3 - combined_score (0..1)
--   if ml_status = 'success':  combined = w_rule * rule_score + w_ml * ml_score
--   otherwise:                 combined = rule_score        (graceful degradation)
--
-- STEP 4 - risk_level from config.thresholds (low/medium/high)
--   combined < low                          -> low
--   low <= combined < medium                -> medium
--   medium <= combined < high               -> high
--   combined >= high                        -> critical
--
-- STEP 5 - decision
--   low, medium  -> 'allow'     (no alert)
--   high         -> 'challenge' (REQUIRE_MFA, alert created)
--   critical     -> 'block'     (LOCK_USER/REVOKE_SESSIONS, alert created)
--
-- Worked example with the seeded v1.0 policy:
--   features: hour=2, fail_24h=5, new_device=true, deviation=0.8
--   contributions: 0.80*0.30=0.240  0.90*0.40=0.360  0.50*0.20=0.100  0.70*0.30=0.210
--   numerator=0.910  denominator=1.20  -> rule_score = 0.7583
--   ml_score=0.72 (success)
--   combined = 0.4*0.7583 + 0.6*0.72 = 0.7353  -> HIGH -> REQUIRE_MFA + alert
--   If ML had timed out: combined = 0.7583 -> CRITICAL (stricter, by design)
