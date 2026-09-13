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
