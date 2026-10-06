# Sentinel Auth - PostgreSQL Bootstrap Test

## Executive Summary

**Status:** CRITICAL FAILURES DETECTED

All three database schemas have critical issues preventing clean PostgreSQL bootstrap:

1. **Core Schema:** 1 index fails (partial index with NOW())
2. **Detection Schema:** 7 tables not created due to invalid CHECK constraint
3. **ML Schema:** 2 tables not created due to invalid CHECK constraint

**Minimum Severity:** BLOCKER

---

## 1. Core Schema Bootstrap

### Test Command
```bash
PGPASSWORD=sentinel psql -h localhost -p 5433 -U sentinel -d sentinel -f schema-core-v3.3.sql
```

### Results
| Step | Result | Details |
|------|--------|---------|
| Extensions | ✅ PASS | uuid-ossp, pg_trgm created |
| Function | ✅ PASS | update_updated_at_column created |
| Roles table | ✅ PASS | 4 rows inserted |
| Users table | ✅ PASS | Constraints created |
| User roles | ✅ PASS | Indexes created |
| IP addresses | ✅ PASS | 2 indexes created |
| Sessions | ✅ PASS | 5 indexes created |
| MFA transactions | ✅ PASS | Indexes created |
| MFA notifications | ✅ PASS | FK added |
| Audit logs | ✅ PASS | Indexes created |
| Trusted devices | ✅ PASS | Partial index created |
| System settings | ✅ PASS | Triggers created |
| Outbox events | ✅ PASS | Indexes created |
| User notifications | ✅ PASS | Indexes created |
| **Rate limits** | ❌ **FAIL** | **Partial index with NOW() rejected** |
| Seed data | ✅ PASS | 16 rows inserted |
| Comments | ✅ PASS | All table comments added |

### Failure Details

**File:** `schema-core-v3.3.sql`
**Line:** ~264

```sql
-- FAILING INDEX:
CREATE INDEX idx_user_trusted_devices_user_active 
ON user_trusted_devices(user_id, expires_at)
WHERE expires_at IS NULL OR expires_at > NOW();
```

**Error:**
```
ERROR: functions in index predicate must be marked IMMUTABLE
```

**Impact:** The `user_trusted_devices` partial index filtering by `NOW()` will not be created. This means:
- Active device queries will be slower
- The intended optimization for trusted device checks is missing

**Workaround:** Change `NOW()` to a constant or use application-level filtering.

---

## 2. Detection Schema Bootstrap

### Test Command
```bash
PGPASSWORD=sentinel psql -h localhost -p 5433 -U sentinel -d sentinel -f schema-detection-v3.3.sql
```

### Results
| Step | Result | Details |
|------|--------|---------|
| Extensions | ✅ PASS | uuid-ossp created |
| Function | ✅ PASS | update_updated_at_column created |
| **Policies table** | ❌ **FAIL** | CHECK constraint with subquery rejected |
| Other tables | ❌ **BLOCKED** | Cannot create without policies |
| Alerts | ❌ **BLOCKED** | FK to login_attempts |
| Seed data | ❌ **BLOCKED** | No policies table |

### Failure Details

**File:** `schema-detection-v3.3.sql`
**Line:** 58

```sql
-- FAILING CONSTRAINT:
CONSTRAINT chk_single_active_policy
CHECK (
    NOT (is_active AND EXISTS (
        SELECT 1 FROM policies p2
        WHERE p2.is_active = TRUE AND p2.id != id
    ))
)
```

**Error:**
```
ERROR: cannot use subquery in check constraint
```

**Impact:**
1. **policies** table is NOT created
2. **login_attempts** table is NOT created (policy FK)
3. **risk_assessments** table is NOT created (login_attempts FK)
4. **detection_logs** table is NOT created
5. **alerts** table is NOT created
6. **alert_timeline** table is NOT created
7. **soc_analysts** table is NOT created (partial - table created but subsequent steps failed)

### Missing Tables (7 out of 7 detection tables)

| Table | Status | Notes |
|-------|--------|-------|
| policies | ❌ NOT CREATED | Critical |
| login_attempts | ❌ NOT CREATED | Critical |
| risk_assessments | ❌ NOT CREATED | Critical |
| detection_logs | ❌ NOT CREATED | Critical |
| alerts | ❌ NOT CREATED | Critical |
| alert_timeline | ❌ NOT CREATED | Critical |
| soc_analysts | ⚠️ PARTIAL | Created but FKs fail |

### Root Cause

PostgreSQL does not allow subqueries inside CHECK constraints. The design requires a functional approach.

### Recommended Fix

**Option A: Trigger-Based Approach**
```sql
-- Instead of CHECK, use a trigger
CREATE OR REPLACE FUNCTION ensure_single_active_policy()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.is_active THEN
        UPDATE policies SET is_active = FALSE 
        WHERE is_active = TRUE AND id != NEW.id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_single_active_policy
BEFORE INSERT OR UPDATE ON policies
FOR EACH ROW EXECUTE FOR EACH STATEMENT
EXECUTE FUNCTION ensure_single_active_policy();
```

**Option B: Exclusion Constraint (PostgreSQL specific)**
```sql
-- Use exclusion constraint with array aggregation
ALTER TABLE policies 
ADD CONSTRAINT chk_single_active_policy 
EXCLUDE USING gist (
    int4(1) WITH = 
    coalesce(array_agg(1) FILTER (WHERE is_active), '{}')
) WHERE (is_active);
```
*Note: This is complex and may not work as intended.*

**Option C: Application-Level Enforcement**
- Drop the DB constraint entirely
- Enforce in application code (current `activate_policy()` does this)
- Document that single-active is an application invariant, not a DB constraint

---

## 3. ML Service Schema Bootstrap

### Test Command
```bash
PGPASSWORD=sentinel psql -h localhost -p 5433 -U sentinel -d sentinel -f schema-ml-service-v3.3.sql
```

### Results
| Step | Result | Details |
|------|--------|---------|
| Extensions | ✅ PASS | uuid-ossp created |
| Function | ✅ PASS | update_updated_at_column created |
| **model_versions table** | ❌ **FAIL** | CHECK constraint with subquery rejected |
| inference_logs | ❌ **BLOCKED** | FK to model_versions |
| feature_statistics | ✅ PASS | Table created successfully |
| Seed data | ❌ **BLOCKED** | No model_versions table |
| View | ❌ **BLOCKED** | No inference_logs table |

### Failure Details

**File:** `schema-ml-service-v3.3.sql`
**Line:** 37

```sql
-- FAILING CONSTRAINT:
CONSTRAINT uq_model_active_production
CHECK (
    NOT (is_production AND EXISTS (
        SELECT 1 FROM model_versions mv2
        WHERE mv2.is_production = TRUE AND mv2.id != id AND mv2.status = 'active'
    ))
)
```

**Error:**
```
ERROR: cannot use subquery in check constraint
```

### Impact

| Table | Status | Notes |
|-------|--------|-------|
| model_versions | ❌ NOT CREATED | Critical |
| inference_logs | ❌ NOT CREATED | FK fails |
| feature_statistics | ✅ CREATED | Independent table |
| Seed data | ❌ NOT INSERTED | model_versions missing |
| local_ml_stats view | ❌ NOT CREATED | inference_logs missing |

---

## 4. Combined Schema Bootstrap (All Three)

### Test Scenario
```bash
# Drop and recreate database
PGPASSWORD=sentinel psql -h localhost -p 5433 -U sentinel -d postgres -c "DROP DATABASE IF EXISTS sentinel"
PGPASSWORD=sentinel psql -h localhost -p 5433 -U sentinel -d postgres -c "CREATE DATABASE sentinel"
# Apply schemas
PGPASSWORD=sentinel psql -h localhost -p 5433 -U sentinel -d sentinel -f schema-core-v3.3.sql 2>&1 | grep -E "(ERROR|PASS|FAIL|CREATE)"
PGPASSWORD=sentinel psentinel psql -h localhost -p 5433 -U sentinel -d sentinel -f schema-detection-v3.3.sql 2>&1 | grep -E "(ERROR|PASS|FAIL|CREATE)"
PGPASSWORD=sentinel psql -h localhost -p 5433 -U sentinel -d sentinel -f schema-ml-service-v3.3.sql 2>&1 | grep -E "(ERROR|PASS|FAIL|CREATE)"
```

### Summary

| Schema | Tables Created | Tables Failed | Critical Issues |
|--------|---------------|---------------|-----------------|
| core | 12 | 1 (rate_limits partial index) | 1 LOW |
| detection | 0 | 7 | 1 CRITICAL (CHECK constraint) |
| ml-service | 1 | 2 | 1 CRITICAL (CHECK constraint) |
| **Total** | **13** | **10** | **2 CRITICAL** |

---

## 5. ORM Compatibility Note

The ORM models (`app/models.py`) define all tables including the ones that fail to create in PostgreSQL. The test suite runs against SQLite which is more permissive.

**Implication:** Code that works in tests may fail in production PostgreSQL.

---

## 6. Recommendations

### Immediate Actions Required

1. **Detection Schema (CRITICAL)**
   - Remove subquery CHECK constraint from policies table
   - Implement trigger-based single-active enforcement
   - Verify all 7 tables can be created

2. **ML Schema (CRITICAL)**
   - Remove subquery CHECK constraint from model_versions table
   - Implement trigger-based single-active-prod enforcement
   - Verify all 3 tables can be created

3. **Core Schema (LOW)**
   - Change partial index to use a constant or application-level filtering
   - Or document that `NOW()` in partial index is a known limitation

### Testing Requirements

1. Add PostgreSQL integration tests to CI/CD pipeline
2. Use real PostgreSQL for schema bootstrap verification
3. Add schema migration tests (up/down)

### Documentation Requirements

1. Document which DB constraints are PostgreSQL-specific
2. Document the alternative enforcement mechanisms
3. Add schema compatibility notes to README

---

## 7. Verification Commands

After fixes are applied, verify with:

```bash
# Verify core schema (13 tables + partial index)
PGPASSWORD=sentinel psql -h localhost -p 5433 -U sentinel -d sentinel -c \
  "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'public';"
# Expected: 13 (if partial index issue fixed) or 12 (if partial index skipped)

# Verify detection schema (7 tables)
PGPASSWORD=sentinel psql -h localhost -p 5433 -U sentinel -d sentinel -c \
  "SELECT table_name FROM information_schema.tables WHERE table_name LIKE '%attempt%' OR table_name LIKE '%policy%' OR table_name LIKE '%alert%';"
# Expected: policies, login_attempts, risk_assessments, detection_logs, alerts, alert_timeline, soc_analysts

# Verify ML schema (3 tables)
PGPASSWORD=sentinel psql -h localhost -p 5433 -U sentinel -d sentinel -c \
  "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' AND table_name LIKE '%model%' OR table_name LIKE '%inference%' OR table_name LIKE '%feature%';"
# Expected: model_versions, inference_logs, feature_statistics
```
