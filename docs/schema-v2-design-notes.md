# Schema v2 Design Notes

## Overview

This document describes the design decisions and changes made in `schema-v2.sql` compared to the original `schema.sql`.

---

## Why Redesign?

### Problems with v1 Schema

1. **Scoring fields misplaced**: `rule_score`, `anomaly_score`, `ml_score` were stored directly in `login_attempts`, but they logically belong to a risk assessment that should be linked to the login attempt.

2. **No MFA lifecycle tracking**: OTP codes were stored as hashes in `pre_auth_transactions` without proper notification lifecycle (sent, delivered, failed).

3. **Rule versioning naming confusion**: `rule_versions` didn't clearly communicate that it contains detection policies (rules + weights + thresholds).

4. **Missing audit context**: `audit_logs` lacked `request_id` for distributed tracing.

5. **No feature storage**: Raw detection features (IP geo, ASN, etc.) weren't stored for debugging/replay.

6. **Rate limit design**: Using UUID as PK for `rate_limits` was inefficient when the natural key is `(ip_address, action)`.

7. **Weak user validation**: No CHECK constraints on username format or email.

---

## Key Design Decisions

### 1. Renamed `rule_versions` to `policy_versions`

**Decision**: Rename the table to better reflect its purpose.

**Rationale**:
- It doesn't just store rules; it stores complete policies with:
  - `rules_json`: the actual detection rules
  - `weights`: how to combine rule_score and ml_score
  - `thresholds`: when to challenge vs block
- "Policy" is a clearer term for "detection policy"

**Impact**:
- No migration needed from v1 data; the table is renamed conceptually
- App code updated to use `PolicyVersion` model instead of `RuleVersion`

### 2. New `mfa_notifications` Table

**Decision**: Separate MFA lifecycle from pre-auth transactions.

**Rationale**:
- One pre-auth transaction can have multiple notification attempts (e.g., email fails to deliver)
- We want to track: sent_at, delivered_at, failed_at, failure_reason
- Ready for multi-channel MFA (SMS, TOTP) in v2

**Structure**:
```
mfa_notifications
├── pre_auth_transaction_id (FK)
├── channel: 'email' | 'sms' | 'totp' (future)
├── recipient: email or phone
├── mfa_code_hash: Argon2id hash
├── sent_at, delivered_at, failed_at
└── verified_at (NULL until verified)
```

**Migration**:
- For existing data, create a single notification per pre_auth_transaction
- Set `notification_id` on pre_auth_transactions after migration

### 3. Moved Scoring to `risk_assessments`

**Decision**: Create a 1:1 `risk_assessments` table for scoring details.

**Rationale**:
- `login_attempts` is the audit log (what happened)
- `risk_assessments` is the risk analysis (why the decision was made)
- Allows storing detailed rule hits, ML features used, etc.
- Cleaner separation of concerns

**Before** (in `login_attempts`):
```sql
rule_score, anomaly_score, ml_score, detection_decision
```

**After** (in `risk_assessments`):
```sql
rule_score, anomaly_score, ml_score, ml_status, ml_model_version
rule_hits (JSONB), ml_features_used (JSONB), combined_score
risk_level, decision
```

**Migration**:
- Copy existing scoring data from `login_attempts` to new `risk_assessments` rows
- Remove scoring columns from `login_attempts`

### 4. Composite PK for `rate_limits`

**Decision**: Use `(ip_address, action)` as composite primary key instead of UUID.

**Rationale**:
- Natural key is unique per IP + action
- Eliminates unnecessary UUID column
- Simplifies UPSERT logic

**Before**:
```sql
id UUID PK, UNIQUE(ip_address, action)
```

**After**:
```sql
PRIMARY KEY (ip_address, action)
```

**Migration**:
- Drop old table and recreate with new PK
- Data is transient (sliding window), no historical data to preserve

### 5. Added Validation Constraints

**Decision**: Add CHECK constraints on `users` table.

**Rationale**:
- Prevent invalid data at database level
- Username: 3-50 chars, alphanumeric + underscore
- Email: basic format validation

**Constraints**:
```sql
CONSTRAINT chk_username_length CHECK (length(username) BETWEEN 3 AND 50)
CONSTRAINT chk_username_chars CHECK (username ~ '^[a-zA-Z0-9_]+$')
CONSTRAINT chk_email_format CHECK (email IS NULL OR email ~ '^[^(]+@[^(]+$')
```

### 6. Added `request_id` for Tracing

**Decision**: Add `request_id` (UUID) to major tables.

**Rationale**:
- Enables distributed tracing across login_attempts, detection_logs, alerts, audit_logs
- Same `request_id` links all events from a single login flow
- Critical for debugging production issues

**Tables updated**:
- `login_attempts`: has `request_id` (primary tracing ID)
- `detection_logs`: has `request_id` (foreign tracing)
- `alerts`: has `request_id`
- `audit_logs`: has `request_id`

### 7. Auto-Update Trigger for `updated_at`

**Decision**: Standardize `updated_at` auto-update via trigger.

**Rationale**:
- Consistent behavior across all tables with `updated_at`
- Application code doesn't need to manually update timestamps
- More reliable than application-level updates

**Implementation**:
```sql
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_X_updated_at
    BEFORE UPDATE ON X
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
```

---

## Schema v2 Entity-Relationship Diagram

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                           USERS & ROLES                                       │
│                                                                               │
│  ┌─────────────┐     ┌─────────────┐     ┌──────────────────┐               │
│  │    users    │     │    roles    │     │   user_roles     │               │
│  ├─────────────┤     ├─────────────┤     ├──────────────────┤               │
│  │ id (PK)     │────<│ id (PK)     │     │ user_id (FK)     │               │
│  │ username    │     │ name        │     │ role_id (FK)     │               │
│  │ password_hash     │ description │     │ assigned_at      │               │
│  │ email       │     │             │     │ assigned_by (FK)│               │
│  │ full_name   │     └─────────────┘     └──────────────────┘               │
│  │ status      │                                                           │
│  │ admin_mfa_req     │                                                           │
│  │ detection_mfa_once   │                                                           │
│  │ last_login_at  │                                                           │
│  │ failed_login_count   │                                                           │
│  │ locked_at      │                                                           │
│  │ created_at    │                                                           │
│  │ updated_at    │                                                           │
│  └─────────────┘                                                           │
│         │                                                                  │
│         │ 1:N                                                               │
│         ▼                                                                  │
│  ┌─────────────┐     ┌──────────────────────┐     ┌────────────────────┐  │
│  │  sessions   │     │ pre_auth_transactions │     │ mfa_notifications  │  │
│  ├─────────────┤     ├──────────────────────┤     ├────────────────────┤  │
│  │ id (PK)     │────<│ id (PK)              │────<│ pre_auth_id (FK)  │  │
│  │ user_id (FK)│     │ user_id (FK)         │     │ id (PK)           │  │
│  │ access_hash │     │ mfa_type             │     │ channel           │  │
│  │ refresh_hash│     │ expires_at           │     │ recipient         │  │
│  │ token_jti   │     │ status               │     │ mfa_code_hash     │  │
│  │ expires_at  │     │ bound_ip             │     │ sent_at           │  │
│  │ last_activity     │ notification_id (FK) │     │ delivered_at      │  │
│  │ revoked_at  │     │ fail_count           │     │ failed_at         │  │
│  │ ip_address  │     │ created_at           │     │ verified_at       │  │
│  │ user_agent  │     │ updated_at           │     │ expires_at        │  │
│  └─────────────┘     └──────────────────────┘     └────────────────────┘  │
│                                                                               │
├──────────────────────────────────────────────────────────────────────────────┤
│                         LOGIN & RISK DETECTION                                │
│                                                                               │
│  ┌─────────────────────┐    ┌─────────────────────┐                         │
│  │   login_attempts    │───>│  risk_assessments   │                         │
│  ├─────────────────────┤    ├─────────────────────┤                         │
│  │ id (PK)             │ 1:1│ id (PK)             │                         │
│  │ user_id (FK)        │    │ login_attempt_id (FK)│                        │
│  │ username_attempted  │    │ policy_version_id(FK)│                        │
│  │ occurred_at         │    │ rule_score          │                        │
│  │ outcome             │    │ anomaly_score      │                        │
│  │ source_ip           │    │ ml_score           │                        │
│  │ user_agent          │    │ ml_status          │                        │
│  │ rate_limited        │    │ ml_model_version   │                        │
│  │ policy_version_id(FK)   │ rule_hits (JSONB)   │                        │
│  │ request_id (UUID)  │    │ ml_features_used   │                        │
│  │ detection_features │    │ combined_score    │                        │
│  │ primary_alert_id(FK)│    │ risk_level        │                        │
│  │ risk_level          │    │ decision          │                        │
│  │ detection_decision  │    └─────────────────────┘                        │
│  └─────────────────────┘                                                   │
│         │                                                                     │
│         │ 1:N                                              ┌─────────────────┐ │
│         ├────────────────────────────────────────────────>│  alerts          │ │
│         │ 1:N                                              ├─────────────────┤ │
│         ▼                                                  │ id (PK)         │ │
│  ┌─────────────────────┐                                  │ login_attempt_id│ │
│  │  detection_logs     │                                  │ policy_version  │ │
│  ├─────────────────────┤                                  │ request_id      │ │
│  │ id (PK)             │                                  │ status          │ │
│  │ login_attempt_id(FK)│                                  │ risk_level      │ │
│  │ request_id (UUID)   │                                  │ detection_reason│ │
│  │ stage               │                                  │ detection_scores│ │
│  │ stage_detail       │                                  │ assigned_to     │ │
│  │ rule_id (UUID)      │                                  │ resolved_by     │ │
│  │ rule_name           │                                  │ resolved_at     │ │
│  │ score               │                                  │ notes           │ │
│  │ decision            │                                  └─────────────────┘ │
│  │ reason              │                                                     │
│  │ details (JSONB)     │                                                     │
│  └─────────────────────┘                                                     │
│                                                                            │
├─────────────────────────────────────────────────────────────────────────────┤
│                          POLICY VERSIONING                                   │
│                                                                            │
│  ┌─────────────────────┐                                                  │
│  │  policy_versions    │                                                  │
│  ├─────────────────────┤                                                  │
│  │ id (PK)             │                                                  │
│  │ version             │                                                  │
│  │ description         │                                                  │
│  │ rules_json (JSONB)  │                                                  │
│  │ weights (JSONB)     │                                                  │
│  │ thresholds (JSONB)  │                                                  │
│  │ is_active           │                                                  │
│  │ created_by_user_id  │                                                  │
│  │ created_at          │                                                  │
│  │ activated_at        │                                                  │
│  │ deactivated_at      │                                                  │
│  └─────────────────────┘                                                  │
│                                                                            │
├─────────────────────────────────────────────────────────────────────────────┤
│                              OPERATIONAL                                    │
│                                                                            │
│  ┌─────────────────────┐    ┌─────────────────────┐                       │
│  │     rate_limits     │    │     audit_logs      │                       │
│  ├─────────────────────┤    ├─────────────────────┤                       │
│  │ ip_address (PK)     │    │ id (PK)             │                       │
│  │ action (PK)         │    │ request_id (UUID)   │                       │
│  │ count               │    │ actor               │                       │
│  │ max_count           │    │ action              │                       │
│  │ window_start        │    │ resource            │                       │
│  └─────────────────────┘    │ resource_id         │                       │
│                              │ before_state (JSONB)│                       │
│                              │ after_state (JSONB)│                       │
│                              │ change_reason      │                       │
│                              │ ip_address         │                       │
│                              │ user_agent         │                       │
│                              │ created_at         │                       │
│                              └─────────────────────┘                       │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Migration Plan: v1 to v2

### Phase 1: Backup
1. Create backup of existing database
2. Document all custom indexes, views, functions

### Phase 2: Create v2 Schema
1. Create `schema-v2.sql` with all new tables
2. Run in transaction to validate syntax

### Phase 3: Data Migration

#### 3.1 Users
```sql
-- Already have required columns
-- Add new columns with defaults
ALTER TABLE users
  ADD COLUMN IF NOT EXISTS full_name TEXT,
  ADD COLUMN IF NOT EXISTS last_login_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS failed_login_count INTEGER DEFAULT 0,
  ADD COLUMN IF NOT EXISTS locked_at TIMESTAMPTZ;
```

#### 3.2 Rename rule_versions → policy_versions
```sql
ALTER TABLE rule_versions RENAME TO policy_versions;

-- Add new columns
ALTER TABLE policy_versions
  ADD COLUMN IF NOT EXISTS description TEXT,
  ADD COLUMN IF NOT EXISTS weights JSONB DEFAULT '{"rule": 0.4, "ml": 0.6}',
  ADD COLUMN IF NOT EXISTS thresholds JSONB DEFAULT '{"challenge": 0.3, "block": 0.7}';
```

#### 3.3 Create mfa_notifications
```sql
-- Create table
CREATE TABLE mfa_notifications (...);

-- Migrate existing OTP data
INSERT INTO mfa_notifications (id, pre_auth_transaction_id, channel, recipient,
  mfa_code_hash, sent_at, expires_at, created_at)
SELECT
  gen_random_uuid(),
  id,
  'email',
  COALESCE(u.email, 'unknown'),
  mfa_code_hash,
  created_at,
  expires_at,
  created_at
FROM pre_auth_transactions pat
JOIN users u ON u.id = pat.user_id
WHERE mfa_code_hash IS NOT NULL;

-- Link back
UPDATE pre_auth_transactions
SET notification_id = (
  SELECT id FROM mfa_notifications
  WHERE pre_auth_transaction_id = pre_auth_transactions.id
  LIMIT 1
);
```

#### 3.4 Create risk_assessments
```sql
-- Create table
CREATE TABLE risk_assessments (...);

-- Migrate scoring data
INSERT INTO risk_assessments (id, login_attempt_id, rule_score, anomaly_score,
  ml_score, risk_level, decision, created_at)
SELECT
  gen_random_uuid(),
  id,
  rule_score,
  anomaly_score,
  ml_score,
  risk_level,
  detection_decision,
  created_at
FROM login_attempts
WHERE rule_score IS NOT NULL OR anomaly_score IS NOT NULL OR ml_score IS NOT NULL;
```

#### 3.5 Add request_id columns
```sql
ALTER TABLE login_attempts ADD COLUMN IF NOT EXISTS request_id UUID DEFAULT gen_random_uuid();
ALTER TABLE detection_logs ADD COLUMN IF NOT EXISTS request_id UUID;
ALTER TABLE alerts ADD COLUMN IF NOT EXISTS request_id UUID;
ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS request_id UUID;
```

#### 3.6 Rate limits refactor
```sql
-- Drop old table (data is transient)
DROP TABLE IF EXISTS rate_limits;

-- Create new with composite PK
CREATE TABLE rate_limits (
  ip_address INET NOT NULL,
  action TEXT NOT NULL,
  count INTEGER NOT NULL DEFAULT 1,
  max_count INTEGER NOT NULL DEFAULT 5,
  window_start TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (ip_address, action)
);
```

### Phase 4: Add Constraints & Triggers
```sql
-- Add CHECK constraints
ALTER TABLE users ADD CONSTRAINT chk_username_length
  CHECK (length(username) BETWEEN 3 AND 50);

ALTER TABLE users ADD CONSTRAINT chk_username_chars
  CHECK (username ~ '^[a-zA-Z0-9_]+$');

-- Add updated_at triggers
CREATE TRIGGER trg_users_updated_at BEFORE UPDATE ON users ...;
```

### Phase 5: Validate
1. Run application tests
2. Check for constraint violations
3. Verify foreign key relationships
4. Test performance with new indexes

---

## Future Extensions (v2+)

### Multi-Channel MFA
- `mfa_notifications.channel` supports: 'email', 'sms', 'totp'
- Add `totp_secrets` table for TOTP setup

### Trusted Devices
- New `trusted_devices` table
- `login_attempts.is_known_device` field

### API Keys (for service accounts)
- New `api_keys` table
- Alternative authentication method

### Audit Log Partitioning
- Partition `audit_logs` by time (monthly)
- Improve query performance for recent logs

### Multi-Tenancy (future)
- Add `tenant_id` to all tables
- Enable Row-Level Security (RLS)
