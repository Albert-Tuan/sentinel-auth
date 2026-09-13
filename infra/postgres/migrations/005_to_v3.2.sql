-- =============================================================================
-- Migration: v3.1 → v3.2 (Balanced Normalization)
-- =============================================================================
--
-- This migration normalizes the database schema while keeping it simple:
-- 1. Add ip_addresses table for normalized IP tracking
-- 2. Add soc_analysts table for normalized analyst references
-- 3. Add actor_id + actor_type columns for alert_timeline and audit_logs
-- 4. Update FKs to use normalized tables
-- 5. Backfill data from existing TEXT columns
--
-- Version: 3.2.0-migration
-- Date: 2026-09-13
-- =============================================================================

-- =============================================================================
-- MIGRATION: UP (v3.1 → v3.2)
-- =============================================================================

BEGIN;

-- =============================================================================
-- STEP 1: Create ip_addresses table
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
-- STEP 2: Create soc_analysts table
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
-- STEP 3: Add actor_id and actor_type columns
-- =============================================================================

-- Add columns to alert_timeline
ALTER TABLE alert_timeline
    ADD COLUMN actor_id UUID REFERENCES users(id) ON DELETE SET NULL,
    ADD COLUMN actor_type TEXT CHECK (actor_type IN ('user', 'system'));

-- Add columns to audit_logs
ALTER TABLE audit_logs
    ADD COLUMN actor_id UUID REFERENCES users(id) ON DELETE SET NULL,
    ADD COLUMN actor_type TEXT CHECK (actor_type IN ('user', 'system'));

-- =============================================================================
-- STEP 4: Add ip_address_id column to sessions
-- =============================================================================

ALTER TABLE sessions
    ADD COLUMN ip_address_id UUID REFERENCES ip_addresses(id) ON DELETE SET NULL;

-- =============================================================================
-- STEP 5: Add assigned_to_id and resolved_by_id to alerts
-- =============================================================================

ALTER TABLE alerts
    ADD COLUMN assigned_to_id UUID REFERENCES soc_analysts(id) ON DELETE SET NULL,
    ADD COLUMN resolved_by_id UUID REFERENCES soc_analysts(id) ON DELETE SET NULL;

-- =============================================================================
-- STEP 6: Backfill ip_addresses from sessions
-- =============================================================================

INSERT INTO ip_addresses (ip_address, first_seen_at, last_seen_at)
SELECT DISTINCT ip_address, MIN(created_at), MAX(created_at)
FROM sessions
WHERE ip_address IS NOT NULL
GROUP BY ip_address
ON CONFLICT (ip_address) DO NOTHING;

-- =============================================================================
-- STEP 7: Backfill ip_addresses from login_attempts
-- =============================================================================

INSERT INTO ip_addresses (ip_address, first_seen_at, last_seen_at)
SELECT DISTINCT source_ip, MIN(occurred_at), MAX(occurred_at)
FROM login_attempts
WHERE source_ip IS NOT NULL
GROUP BY source_ip
ON CONFLICT (ip_address) DO NOTHING;

-- =============================================================================
-- STEP 8: Backfill sessions.ip_address_id
-- =============================================================================

UPDATE sessions s
SET ip_address_id = (
    SELECT id FROM ip_addresses
    WHERE ip_address = s.ip_address
)
WHERE s.ip_address IS NOT NULL;

-- =============================================================================
-- STEP 9: Backfill soc_analysts from alerts.assigned_to
-- =============================================================================

INSERT INTO soc_analysts (user_id, display_name)
SELECT DISTINCT u.id, u.username
FROM alerts a
JOIN users u ON a.assigned_to = u.username
WHERE a.assigned_to IS NOT NULL
ON CONFLICT (user_id) DO NOTHING;

-- =============================================================================
-- STEP 10: Backfill alerts.assigned_to_id and resolved_by_id
-- =============================================================================

UPDATE alerts a
SET assigned_to_id = (
    SELECT sa.id FROM soc_analysts sa
    JOIN users u ON sa.user_id = u.id
    WHERE u.username = a.assigned_to
)
WHERE a.assigned_to IS NOT NULL;

UPDATE alerts a
SET resolved_by_id = (
    SELECT sa.id FROM soc_analysts sa
    JOIN users u ON sa.user_id = u.id
    WHERE u.username = a.resolved_by
)
WHERE a.resolved_by IS NOT NULL;

-- =============================================================================
-- STEP 11: Backfill alert_timeline.actor_id and actor_type
-- =============================================================================

-- Set actor_type based on actor content
UPDATE alert_timeline
SET actor_type = CASE
    WHEN actor LIKE 'system:%' THEN 'system'
    ELSE 'user'
END;

-- Map actor to user_id
UPDATE alert_timeline
SET actor_id = (
    SELECT id FROM users
    WHERE username = alert_timeline.actor
)
WHERE alert_timeline.actor_type = 'user'
AND alert_timeline.actor IS NOT NULL;

-- =============================================================================
-- STEP 12: Backfill audit_logs.actor_id and actor_type
-- =============================================================================

UPDATE audit_logs
SET actor_type = CASE
    WHEN actor LIKE 'system:%' THEN 'system'
    ELSE 'user'
END;

UPDATE audit_logs
SET actor_id = (
    SELECT id FROM users
    WHERE username = audit_logs.actor
)
WHERE audit_logs.actor_type = 'user'
AND audit_logs.actor IS NOT NULL;

-- =============================================================================
-- STEP 13: Set NOT NULL constraints after backfill
-- =============================================================================

-- actor_type should be NOT NULL
ALTER TABLE alert_timeline
    ALTER COLUMN actor_type SET NOT NULL;

ALTER TABLE audit_logs
    ALTER COLUMN actor_type SET NOT NULL;

-- =============================================================================
-- STEP 14: Update policy_versions weights_json column name
-- =============================================================================

-- v3.1 had "weights" column, v3.2 has "weights_json"
-- Check if weights column exists and rename
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'policy_versions'
        AND column_name = 'weights'
    ) THEN
        ALTER TABLE policy_versions
            RENAME COLUMN weights TO weights_json;
    END IF;
END $$;

-- Check if thresholds column exists and rename
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'policy_versions'
        AND column_name = 'thresholds'
    ) THEN
        ALTER TABLE policy_versions
            RENAME COLUMN thresholds TO thresholds_json;
    END IF;
END $$;

-- =============================================================================
-- STEP 15: Add rate_limits table if not exists
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
-- STEP 16: Add comments for new tables
-- =============================================================================

COMMENT ON TABLE ip_addresses IS 'Normalized IP address tracking with geolocation.';
COMMENT ON TABLE soc_analysts IS 'SOC analyst profiles linked to users.';
COMMENT ON COLUMN sessions.ip_address_id IS 'FK to normalized ip_addresses table.';
COMMENT ON COLUMN alerts.assigned_to_id IS 'FK to soc_analysts (normalized from assigned_to TEXT).';
COMMENT ON COLUMN alerts.resolved_by_id IS 'FK to soc_analysts (normalized from resolved_by TEXT).';
COMMENT ON COLUMN alert_timeline.actor_id IS 'FK to users (normalized from actor TEXT).';
COMMENT ON COLUMN alert_timeline.actor_type IS 'Type of actor: user or system.';
COMMENT ON COLUMN audit_logs.actor_id IS 'FK to users (normalized from actor TEXT).';
COMMENT ON COLUMN audit_logs.actor_type IS 'Type of actor: user or system.';

COMMIT;

-- =============================================================================
-- MIGRATION: DOWN (v3.2 → v3.1)
-- =============================================================================

/*
BEGIN;

-- Drop FK constraints
ALTER TABLE sessions DROP CONSTRAINT IF EXISTS sessions_ip_address_id_fkey;
ALTER TABLE alerts DROP CONSTRAINT IF EXISTS alerts_assigned_to_id_fkey;
ALTER TABLE alerts DROP CONSTRAINT IF EXISTS alerts_resolved_by_id_fkey;
ALTER TABLE alert_timeline DROP CONSTRAINT IF EXISTS alert_timeline_actor_id_fkey;
ALTER TABLE audit_logs DROP CONSTRAINT IF EXISTS audit_logs_actor_id_fkey;

-- Drop new columns
ALTER TABLE sessions DROP COLUMN IF EXISTS ip_address_id;
ALTER TABLE alerts DROP COLUMN IF EXISTS assigned_to_id;
ALTER TABLE alerts DROP COLUMN IF EXISTS resolved_by_id;
ALTER TABLE alert_timeline DROP COLUMN IF EXISTS actor_id;
ALTER TABLE alert_timeline DROP COLUMN IF EXISTS actor_type;
ALTER TABLE audit_logs DROP COLUMN IF EXISTS actor_id;
ALTER TABLE audit_logs DROP COLUMN IF EXISTS actor_type;

-- Restore assigned_to/resolved_by from soc_analysts
UPDATE alerts a
SET assigned_to = (
    SELECT u.username FROM soc_analysts sa
    JOIN users u ON sa.user_id = u.id
    WHERE sa.id = a.assigned_to_id
)
WHERE a.assigned_to_id IS NOT NULL;

-- Drop new tables
DROP TABLE IF EXISTS soc_analysts;
DROP TABLE IF EXISTS ip_addresses;

-- Restore policy_versions column names
ALTER TABLE policy_versions RENAME COLUMN weights_json TO weights;
ALTER TABLE policy_versions RENAME COLUMN thresholds_json TO thresholds;

ROLLBACK;
*/

-- =============================================================================
-- VERIFICATION QUERIES (Run after migration)
-- =============================================================================

-- 1. Check ip_addresses populated
-- SELECT COUNT(*) FROM ip_addresses;

-- 2. Check soc_analysts populated
-- SELECT COUNT(*) FROM soc_analysts;

-- 3. Check actor columns populated
-- SELECT 
--     COUNT(*) as total,
--     SUM(CASE WHEN actor_id IS NOT NULL THEN 1 ELSE 0 END) as with_actor_id,
--     SUM(CASE WHEN actor_type IS NOT NULL THEN 1 ELSE 0 END) as with_actor_type
-- FROM alert_timeline;

-- 4. Check all FK constraints
-- SELECT 
--     tc.table_name, 
--     kcu.column_name,
--     ccu.table_name AS foreign_table_name,
--     ccu.column_name AS foreign_column_name
-- FROM information_schema.table_constraints AS tc
-- JOIN information_schema.key_column_usage AS kcu
--     ON tc.constraint_name = kcu.constraint_name
-- JOIN information_schema.constraint_column_usage AS ccu
--     ON ccu.constraint_name = tc.constraint_name
-- WHERE tc.constraint_type = 'FOREIGN KEY'
-- AND tc.table_schema = 'public';
