-- =============================================================================
-- Sentinel Auth - ML Service Database Schema v3.3
-- ML Service has its own database for model registry and inference logs
--
-- Version: 3.3
-- Date: 2026-09-13
-- Based on: ML Service documentation
-- Note: ML Service is primarily stateless; this DB is for model registry
--       and optional inference logging
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
-- MODEL VERSIONS (Model Registry)
-- =============================================================================

CREATE TABLE IF NOT EXISTS model_versions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            TEXT NOT NULL,
    version         TEXT NOT NULL UNIQUE,
    algorithm       TEXT NOT NULL DEFAULT 'IsolationForest',
    description     TEXT,
    model_path      TEXT NOT NULL,  -- Path to model file on disk
    config          JSONB NOT NULL DEFAULT '{}',
    /*
    JSONB structure:
    {
        "threshold": 0.5,
        "contamination": 0.1,
        "n_estimators": 100,
        "max_samples": "auto",
        "training_date": "ISO8601",
        "training_features": ["feature1", "feature2"],
        "metrics": {
            "precision": 0.85,
            "recall": 0.78,
            "f1_score": 0.81,
            "auc_roc": 0.92
        }
    }
    */
    status          TEXT NOT NULL DEFAULT 'staged'
                        CHECK (status IN ('staged', 'active', 'archived', 'failed')),
    is_production   BOOLEAN NOT NULL DEFAULT FALSE,
    trained_by      UUID,  -- Reference to users.id in core-db (nullable)
    training_date   TIMESTAMPTZ,
    deployed_at     TIMESTAMPTZ,
    archived_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_model_active_production
        CHECK (
            NOT (is_production AND EXISTS (
                SELECT 1 FROM model_versions mv2
                WHERE mv2.is_production = TRUE AND mv2.id != id AND mv2.status = 'active'
            ))
        )
);

CREATE TRIGGER trg_model_versions_updated_at
    BEFORE UPDATE ON model_versions
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE INDEX idx_model_versions_version ON model_versions(version);
CREATE INDEX idx_model_versions_status ON model_versions(status);
CREATE INDEX idx_model_versions_production ON model_versions(is_production) WHERE is_production = TRUE;
CREATE INDEX idx_model_versions_algorithm ON model_versions(algorithm);

-- =============================================================================
-- INFERENCE LOGS (Optional - for monitoring and debugging)
-- =============================================================================

CREATE TABLE IF NOT EXISTS inference_logs (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    request_id              UUID NOT NULL UNIQUE,
    model_version_id        UUID REFERENCES model_versions(id),
    model_version_used      TEXT NOT NULL,
    
    -- Input features (for debugging)
    features                JSONB NOT NULL,
    /*
    JSONB structure:
    {
        "hour_of_day": 14,
        "fail_count_24h": 2,
        "ip_change_rate_7d": 0.15,
        "new_device": true,
        "average_login_interval_seconds": 28800,
        "deviation_score": 0.3
    }
    */
    
    -- Output
    raw_score               NUMERIC(10,6),
    normalized_score        NUMERIC(5,4) NOT NULL,
    is_anomaly              BOOLEAN NOT NULL,
    reason_codes            JSONB DEFAULT '[]',
    model_status            TEXT NOT NULL DEFAULT 'ready'
                                CHECK (model_status IN ('ready', 'degraded', 'error')),
    
    -- Metadata
    processing_time_ms      INTEGER,
    error_message          TEXT,
    ip_address             INET,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_inference_logs_request ON inference_logs(request_id);
CREATE INDEX idx_inference_logs_model ON inference_logs(model_version_id);
CREATE INDEX idx_inference_logs_anomaly ON inference_logs(is_anomaly);
CREATE INDEX idx_inference_logs_created ON inference_logs(created_at);
CREATE INDEX idx_inference_logs_status ON inference_logs(model_status);

-- =============================================================================
-- FEATURE STATISTICS (For feature engineering monitoring)
-- =============================================================================

CREATE TABLE IF NOT EXISTS feature_statistics (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    feature_name        TEXT NOT NULL,
    timestamp           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    count               BIGINT NOT NULL DEFAULT 0,
    mean                NUMERIC(10,6),
    std                 NUMERIC(10,6),
    min                 NUMERIC(10,6),
    max                 NUMERIC(10,6),
    p25                 NUMERIC(10,6),
    p50                 NUMERIC(10,6),
    p75                 NUMERIC(10,6),
    p95                 NUMERIC(10,6),
    anomaly_rate        NUMERIC(5,4),  -- Percentage of anomalies
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_feature_stats_feature ON feature_statistics(feature_name);
CREATE INDEX idx_feature_stats_timestamp ON feature_statistics(timestamp);

-- =============================================================================
-- SEED DATA: Default Model Version
-- =============================================================================

INSERT INTO model_versions (
    name, 
    version, 
    algorithm, 
    description, 
    model_path, 
    config,
    status,
    is_production,
    training_date
) VALUES
    (
        'Isolation Forest v1.0',
        'v1.0-isolation-forest',
        'IsolationForest',
        'Baseline Isolation Forest model for anomaly detection',
        '/models/isolation-forest-v1.0.joblib',
        '{
            "threshold": 0.5,
            "contamination": 0.1,
            "n_estimators": 100,
            "max_samples": "auto",
            "random_state": 42,
            "metrics": {
                "precision": 0.85,
                "recall": 0.78,
                "f1_score": 0.81
            }
        }'::jsonb,
        'active',
        TRUE,
        NOW() - INTERVAL '30 days'
    )
ON CONFLICT (version) DO NOTHING;

-- =============================================================================
-- MANAGER DASHBOARD VIEW (Cross-Database Aggregated View)
-- =============================================================================
-- Note: This view is a DEFERRABLE view placeholder.
-- Since ml-service-db cannot directly query detection-db (different database),
-- the implementation strategy is:
-- 1. ml-service calls detection-engine HTTP API: GET /internal/dashboard/stats
-- 2. detection-engine aggregates from login_attempts, risk_assessments, alerts
-- 3. ml-service caches the result and exposes it as manager dashboard
--
-- Below is the conceptual SQL that would be used if both tables were in
-- the same database (for documentation purposes):
--
-- CREATE OR REPLACE VIEW manager_dashboard AS
-- SELECT
--     -- Time window
--     DATE_TRUNC('day', la.timestamp) AS day,
--
--     -- Alert statistics
--     COUNT(DISTINCT a.id) FILTER (WHERE a.id IS NOT NULL) AS total_alerts,
--     COUNT(DISTINCT a.id) FILTER (WHERE a.status = 'open') AS open_alerts,
--     COUNT(DISTINCT a.id) FILTER (WHERE a.status = 'acknowledged') AS acknowledged_alerts,
--     COUNT(DISTINCT a.id) FILTER (WHERE a.status = 'resolved') AS resolved_alerts,
--     COUNT(DISTINCT a.id) FILTER (WHERE a.status = 'false_positive') AS false_positives,
--
--     -- Risk level breakdown
--     COUNT(DISTINCT la.id) FILTER (WHERE ra.risk_level = 'low') AS low_risk_count,
--     COUNT(DISTINCT la.id) FILTER (WHERE ra.risk_level = 'medium') AS medium_risk_count,
--     COUNT(DISTINCT la.id) FILTER (WHERE ra.risk_level = 'high') AS high_risk_count,
--     COUNT(DISTINCT la.id) FILTER (WHERE ra.risk_level = 'critical') AS critical_risk_count,
--
--     -- Login statistics
--     COUNT(DISTINCT la.id) AS total_logins,
--     COUNT(DISTINCT la.id) FILTER (WHERE la.outcome = 'success') AS successful_logins,
--     COUNT(DISTINCT la.id) FILTER (WHERE la.outcome = 'failure') AS failed_logins,
--     COUNT(DISTINCT la.id) FILTER (WHERE la.outcome = 'blocked') AS blocked_logins,
--     COUNT(DISTINCT la.id) FILTER (WHERE la.outcome IN ('mfa_required', 'mfa_success', 'mfa_failed')) AS mfa_logins,
--
--     -- ML anomaly statistics (from ml-service-db itself)
--     (SELECT COUNT(*) FROM inference_logs il
--      WHERE il.is_anomaly = TRUE
--        AND DATE_TRUNC('day', il.created_at) = DATE_TRUNC('day', la.timestamp)
--     ) AS ml_anomalies_detected,
--
--     -- Average risk score
--     AVG(ra.combined_score) AS avg_risk_score,
--
--     -- Top risk users (would need separate query)
--     NULL::JSONB AS top_risk_users
-- FROM login_attempts la
-- LEFT JOIN alerts a ON a.login_attempt_id = la.id
-- LEFT JOIN risk_assessments ra ON ra.login_attempt_id = la.id
-- GROUP BY DATE_TRUNC('day', la.timestamp);
--
-- In practice, this aggregation happens in the ml-service Python code
-- by calling detection-engine's REST API: GET /internal/dashboard/overview

-- Local fallback view: aggregates only data within ml-service-db
CREATE OR REPLACE VIEW local_ml_stats AS
SELECT
    DATE_TRUNC('day', created_at) AS day,
    COUNT(*) AS total_inferences,
    COUNT(*) FILTER (WHERE is_anomaly = TRUE) AS anomalies_detected,
    COUNT(*) FILTER (WHERE model_status = 'ready') AS successful_inferences,
    COUNT(*) FILTER (WHERE model_status = 'degraded') AS degraded_inferences,
    COUNT(*) FILTER (WHERE model_status = 'error') AS error_inferences,
    AVG(processing_time_ms)::NUMERIC(10,2) AS avg_processing_ms,
    AVG(normalized_score)::NUMERIC(5,4) AS avg_anomaly_score
FROM inference_logs
GROUP BY DATE_TRUNC('day', created_at);

COMMENT ON VIEW local_ml_stats IS 'Local stats from inference_logs only. Cross-DB manager dashboard uses HTTP API.';

-- =============================================================================
-- COMMENTS
-- =============================================================================

COMMENT ON TABLE model_versions IS 'Model registry for versioning ML models.';
COMMENT ON TABLE inference_logs IS 'Optional inference logging for debugging and monitoring.';
COMMENT ON TABLE feature_statistics IS 'Feature distribution statistics for monitoring.';

-- =============================================================================
-- ML SERVICE NOTES
-- =============================================================================

-- ML Service is primarily a stateless inference service.
-- Database is used for:
-- 1. Model registry - track available model versions
-- 2. Inference logs - optional debugging/monitoring
-- 3. Feature statistics - data drift monitoring
-- 
-- The actual ML model runs in memory, loaded from disk.
