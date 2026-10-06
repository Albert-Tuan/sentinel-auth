# Sentinel Auth - Findings

## Executive Summary

This document contains all audit findings with evidence, severity, and recommendations.

---

## BLOCKER Findings

### F-01: Invalid PostgreSQL CHECK Constraints

**Finding ID:** F-01
**Severity:** BLOCKER
**Confidence:** CONFIRMED
**Category:** DATABASE_SCHEMA

**Summary:** Two critical database schemas cannot bootstrap on PostgreSQL due to invalid CHECK constraints that use subqueries.

**Expected behavior:** All schemas should create successfully on PostgreSQL 18.

**Actual evidence:**

```
ERROR: cannot use subquery in check constraint

-- schema-detection-v3.3.sql line 58
CONSTRAINT chk_single_active_policy
CHECK (
    NOT (is_active AND EXISTS (
        SELECT 1 FROM policies p2
        WHERE p2.is_active = TRUE AND p2.id != id
    ))
)

-- schema-ml-service-v3.3.sql line 37
CONSTRAINT uq_model_active_production
CHECK (
    NOT (is_production AND EXISTS (
        SELECT 1 FROM model_versions mv2
        WHERE mv2.is_production = TRUE AND mv2.id != id
    ))
)
```

**Evidence 1:**
```
file: infra/postgres/schema-detection-v3.3.sql
section: CREATE TABLE policies
line: 58
```

**Evidence 2:**
```
file: infra/postgres/schema-ml-service-v3.3.sql
section: CREATE TABLE model_versions
line: 37
```

**Why it matters:** The detection and ML schemas fail to create any tables beyond the first table. This means 7 of 7 detection tables and 2 of 3 ML tables are not created.

**Concrete failure/attack scenario:** A production deployment attempting to initialize the database will fail, preventing the system from starting.

**Affected invariant:** INV-ALERT-002 (single active policy) has no DB enforcement.

**Recommended design decision:** Replace subquery CHECK constraints with trigger-based enforcement or application-level enforcement.

**Required files to update:**
- `infra/postgres/schema-detection-v3.3.sql`
- `infra/postgres/schema-ml-service-v3.3.sql`

**Required tests:**
- PostgreSQL bootstrap test
- Single-active policy enforcement test

**Implementation blocker:** YES

---

### F-02: MFA Race Condition - OTP Double Use

**Finding ID:** F-02
**Severity:** CRITICAL
**Confidence:** HIGH_CONFIDENCE
**Category:** AUTHENTICATION

**Summary:** Concurrent MFA verification requests can both succeed because the `verified_at` check and write are not atomic.

**Expected behavior:** An OTP should be usable exactly once. Concurrent requests should result in at most one session creation.

**Actual evidence:**
```python
# app/auth.py line 542-550
if notification.verified_at:
    raise HTTPException(status_code=400, detail="MFA code already used")
# ... verification ...
notification.verified_at = now
```

**Evidence 1:**
```
file: app/auth.py
function: mfa_verify
section: verified_at check
line: 542-550
```

**Evidence 2:**
```
file: app/models.py
class: MfaNotification
section: verified_at column
line: 280
```

**Why it matters:** An attacker who intercepts an OTP could submit it concurrently from two locations, creating two valid sessions before either write commits.

**Concrete failure/attack scenario:**
1. Attacker obtains legitimate OTP via email interception
2. Attacker sends OTP from IP A and IP B simultaneously
3. Both requests read `verified_at = None`
4. Both requests create sessions
5. Attacker has two active sessions

**Affected invariant:** INV-MFA-001 (one-time use), INV-MFA-003 (concurrent verification)

**Recommended design decision:** Use `SELECT FOR UPDATE` to lock the row during verification, or use optimistic locking with a version column.

**Required files to update:**
- `app/auth.py`

**Required tests:**
- Concurrent MFA verification test
- OTP single-use test under race

**Implementation blocker:** YES (for production deployment)

---

### F-03: Authorization Bypass - No RBAC Enforcement

**Finding ID:** F-03
**Severity:** CRITICAL
**Confidence:** CONFIRMED
**Category:** AUTHORIZATION

**Summary:** All endpoints that should require authentication or authorization are accessible without any validation.

**Expected behavior:** SOC endpoints should require SOC_ANALYST or higher role. Admin endpoints should require SECURITY_ADMIN role.

**Actual evidence:**
```python
# app/alerts.py line 289-330
@router.get("/alerts", response_model=AlertListResponse)
async def list_alerts(
    # ... no authorization check ...
) -> AlertListResponse:
    # Any unauthenticated request can list all alerts
```

**Evidence 1:**
```
file: app/alerts.py
function: list_alerts
section: endpoint definition
line: 289-330
```

**Evidence 2:**
```
file: app/auth.py
function: verify_internal_token
section: only checks shared secret
line: 222-226
```

**Why it matters:** Any user, including unauthenticated actors, can access all alerts, sessions, and administrative functions.

**Concrete failure/attack scenario:**
1. Attacker sends `GET /api/v1/alerts` without any authentication
2. System returns all alerts with user data, IPs, and risk assessments
3. Attacker can also acknowledge, resolve, or take actions on alerts

**Affected invariant:** INV-RBAC-001 (authorization enforcement)

**Recommended design decision:** Implement JWT validation middleware and role-based authorization decorators.

**Required files to update:**
- `app/auth.py` (add JWT validation)
- `app/main.py` (add middleware)
- `app/alerts.py` (add authorization)
- `app/schemas.py` (add auth schemas)

**Required tests:**
- Unauthenticated access test (should fail)
- Role-based access tests

**Implementation blocker:** YES (security model incomplete)

---

## HIGH Findings

### F-04: CORS Misconfiguration

**Finding ID:** F-04
**Severity:** HIGH
**Confidence:** CONFIRMED
**Category:** SECURITY

**Summary:** CORS configuration uses wildcard origins with credentials, which is rejected by browsers and creates security risk.

**Expected behavior:** Production CORS should explicitly list allowed origins.

**Actual evidence:**
```python
# app/main.py line 33-38
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],        # Wildcard
    allow_credentials=True,      # With credentials!
    allow_methods=["*"],
    allow_headers=["*"],
)
```

**Evidence 1:**
```
file: app/main.py
section: CORS middleware
line: 33-38
```

**Why it matters:** Modern browsers reject the combination of `allow_origins=["*"]` with `allow_credentials=True`. Additionally, even if it worked, it would allow any origin to receive credentials.

**Concrete failure/attack scenario:**
1. Attacker hosts malicious page at evil.com
2. Page makes cross-origin request to Sentinel Auth
3. Browser rejects due to wildcard + credentials (in practice)
4. If it worked, attacker would receive cookies/tokens

**Affected invariant:** N/A (configuration issue)

**Recommended design decision:** Configure explicit origins from environment variable for production.

**Required files to update:**
- `app/main.py`

**Implementation blocker:** NO (workaround exists)

---

### F-05: Outbox Pattern Not Implemented

**Finding ID:** F-05
**Severity:** HIGH
**Confidence:** CONFIRMED
**Category:** RELIABILITY

**Summary:** The transactional outbox pattern is documented but not implemented. Login events can be lost if the application crashes.

**Expected behavior:** Login events should be reliably delivered to Detection Engine even if the application crashes after committing to the database.

**Actual evidence:**
```python
# app/auth.py - login() does not write to outbox_events
la = LoginAttempt(...)
db.add(la)
db.commit()
# No outbox write
```

**Evidence 1:**
```
file: app/auth.py
function: login
section: login attempt creation
line: 340-360
```

**Evidence 2:**
```
file: docs/SENTINEL_AUTH_TONG_HOP_v3.3.md
section: ADR-002
note: "2026-10-05: CHƯA HIỆN THỰC"
```

**Why it matters:** If the application crashes after `db.commit()` but before sending the event to Detection, the login succeeds but is never scored.

**Concrete failure/attack scenario:**
1. User logs in successfully
2. App commits login to database
3. App crashes before HTTP call to Detection
4. Login not scored
5. If suspicious, no alert generated

**Affected invariant:** INV-DET-002 (event delivery)

**Recommended design decision:** Implement outbox pattern with background poller, or implement retry mechanism.

**Required files to update:**
- `app/auth.py`
- `app/db.py` (add outbox support)
- Add outbox poller/worker

**Required tests:**
- Event delivery reliability test
- Crash recovery test

**Implementation blocker:** NO (workaround exists via pre-token check)

---

### F-06: Reconcile Function Never Scheduled

**Finding ID:** F-06
**Severity:** HIGH
**Confidence:** CONFIRMED
**Category:** RELIABILITY

**Summary:** The `rescore_failed_attempts()` function exists but is never called, so failed scoring attempts are never recovered.

**Expected behavior:** Failed login attempts should be re-scored by a background process.

**Actual evidence:**
```python
# app/detection.py line 721-756
async def rescore_failed_attempts(db, limit: int = 50) -> int:
    """Re-score attempts left in 'failed' by an earlier crash."""
    # Function exists but is never invoked from any endpoint
```

**Evidence 1:**
```
file: app/detection.py
function: rescore_failed_attempts
line: 721
```

**Evidence 2:**
```
file: app/main.py
# No scheduler or background task configured
```

**Why it matters:** If `process_attempt()` throws an exception, the attempt is marked "failed" and never revisited. The fail-open design depends on reconciliation to close this gap.

**Concrete failure/attack scenario:**
1. Login succeeds, session created
2. Detection scoring throws exception
3. Attempt marked "failed", no alert
4. Reconciliation never runs (not scheduled)
5. Gap between login and alert remains forever

**Affected invariant:** N/A (reliability issue)

**Recommended design decision:** Schedule reconciliation worker via cron or background thread.

**Required files to update:**
- `app/main.py` (add scheduler)
- Add background task for reconciliation

**Required tests:**
- Reconciliation trigger test

**Implementation blocker:** NO (degraded mode exists)

---

### F-07: IP Spoofing Vulnerability

**Finding ID:** F-07
**Severity:** HIGH
**Confidence:** HIGH_CONFIDENCE
**Category:** SECURITY

**Summary:** The system trusts X-Forwarded-For header without verifying the deployment context, allowing IP spoofing.

**Expected behavior:** Rate limiting and detection should use the actual client IP, not a spoofable header.

**Actual evidence:**
```python
# app/auth.py line 70-76
def get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
```

**Evidence 1:**
```
file: app/auth.py
function: get_client_ip
line: 70-76
```

**Evidence 2:**
```
file: app/detection.py
section: ip_address feature
# Uses get_client_ip
```

**Why it matters:** If the application is directly exposed to the internet, attackers can spoof IP addresses to bypass rate limiting and detection.

**Concrete failure/attack scenario:**
1. Attacker sends request with `X-Forwarded-For: 1.2.3.4`
2. System treats request as from 1.2.3.4
3. Rate limit per-IP is bypassed
4. Detection IP-based features ineffective

**Affected invariant:** N/A (deployment-dependent)

**Recommended design decision:** Either reject X-Forwarded-For entirely (if directly exposed) or configure trusted proxy list (if behind proxy).

**Required files to update:**
- `app/auth.py`
- Add configuration for trusted proxies

**Required tests:**
- IP spoofing resistance test

**Implementation blocker:** NO (depends on deployment)

---

### F-08: Refresh Token Replay

**Finding ID:** F-08
**Severity:** HIGH
**Confidence:** HIGH_CONFIDENCE
**Category:** AUTHENTICATION

**Summary:** Refresh tokens can be replayed after legitimate refresh because there's no family tracking or reuse detection.

**Expected behavior:** If a refresh token is used after a newer token was issued, the entire token family should be invalidated.

**Actual evidence:**
```python
# app/auth.py line 610-650
# refresh() only checks if token hash matches
session = db.query(Session).filter(
    Session.refresh_token_hash == refresh_hash,
    Session.revoked_at.is_(None),
).first()
# No check: is this the LATEST refresh token?
# No family invalidation
```

**Evidence 1:**
```
file: app/auth.py
function: refresh_token
line: 610-650
```

**Evidence 2:**
```
file: app/models.py
class: Session
section: refresh_token_family column
# Column exists but unused
line: 470
```

**Why it matters:** An attacker with a stolen refresh token can continue using it even after the legitimate user has refreshed.

**Concrete failure/attack scenario:**
1. User logs in, gets access + refresh tokens
2. User refreshes, gets new tokens
3. Attacker uses old refresh token
4. Both work until old token expires
5. Attacker has persistent access

**Affected invariant:** INV-AUTH-002 (session revocation)

**Recommended design decision:** Implement token family tracking with reuse detection.

**Required files to update:**
- `app/auth.py`

**Required tests:**
- Token replay test
- Family invalidation test

**Implementation blocker:** NO (workaround: shorter token TTL)

---

## MEDIUM Findings

### F-09: Token vs. Documented JWT

**Finding ID:** F-09
**Severity:** MEDIUM
**Confidence:** CONFIRMED
**Category:** DOCUMENTATION

**Summary:** Documentation describes "JWT token management" but implementation uses opaque random strings stored in database.

**Expected behavior:** Documentation should match implementation.

**Actual evidence:**
```python
# app/auth.py - opaque tokens, not JWT
access_token = secrets.token_urlsafe(32)  # Random 256-bit string
# Stored as SHA256 hash
session.access_token_hash = hash_token(access_token)
```

**Evidence 1:**
```
file: app/auth.py
function: _create_session
line: 465-470
```

**Evidence 2:**
```
file: docs/SENTINEL_AUTH_TONG_HOP_v3.3.md
section: Sessions
description: "JWT Token Management"
```

**Why it matters:** Documentation sets incorrect expectations for integrators.

**Recommended design decision:** Update documentation to clarify opaque token architecture, or implement true JWT.

**Required files to update:**
- `docs/SENTINEL_AUTH_TONG_HOP_v3.3.md`
- `docs/DECISIONS-DETECTION-v3.3.md`

**Implementation blocker:** NO

---

### F-10: MFA IP Binding Not Validated

**Finding ID:** F-10
**Severity:** MEDIUM
**Confidence:** CONFIRMED
**Category:** SECURITY

**Summary:** The `bound_ip` field stores hashed IP but verification never validates the client's IP against it.

**Expected behavior:** If IP binding is intended, verification should check that the verifying IP matches the bound IP.

**Actual evidence:**
```python
# app/auth.py - stores hashed IP
mfa_txn = MfaTransaction(
    bound_ip=hash_ip(client_ip),
    ...
)

# app/auth.py - never validates bound_ip
# mfa_verify() does NOT check client's IP
```

**Evidence 1:**
```
file: app/auth.py
function: login (MFA creation)
line: 402
```

**Evidence 2:**
```
file: app/auth.py
function: mfa_verify
# No bound_ip validation
```

**Why it matters:** The bound_ip feature provides no actual protection since it's never checked.

**Recommended design decision:** Either implement IP binding validation or remove the bound_ip field.

**Required files to update:**
- `app/auth.py`

**Implementation blocker:** NO

---

### F-11: Partial Index with NOW() Fails

**Finding ID:** F-11
**Severity:** MEDIUM
**Confidence:** CONFIRMED
**Category:** DATABASE_SCHEMA

**Summary:** A partial index uses `NOW()` which is not IMMUTABLE, causing PostgreSQL to reject it.

**Expected behavior:** Partial indexes should use immutable expressions.

**Actual evidence:**
```sql
-- schema-core-v3.3.sql
CREATE INDEX idx_user_trusted_devices_user_active 
ON user_trusted_devices(user_id, expires_at)
WHERE expires_at IS NULL OR expires_at > NOW();
```

**Evidence 1:**
```
file: infra/postgres/schema-core-v3.3.sql
section: trusted devices indexes
line: ~264
```

**Why it matters:** The index for active device queries is not created, potentially causing performance issues.

**Recommended design decision:** Change `NOW()` to a specific timestamp or use application-level filtering.

**Implementation blocker:** NO (functional without index)

---

### F-12: Rate Limit Not Per-Account

**Finding ID:** F-12
**Severity:** MEDIUM
**Confidence:** HIGH_CONFIDENCE
**Category:** SECURITY

**Summary:** Rate limiting is per-IP only, allowing distributed brute force attacks against a single account.

**Expected behavior:** Rate limiting should consider both IP and account to prevent distributed attacks.

**Actual evidence:**
```python
# app/auth.py line 290-295
rate = db.query(RateLimit).filter(
    RateLimit.ip_address == client_ip,  # Only per-IP
    RateLimit.action == "login",
    ...
)
```

**Evidence 1:**
```
file: app/auth.py
function: login
line: 290-295
```

**Why it matters:** An attacker with multiple IPs can try passwords without triggering rate limits.

**Recommended design decision:** Add per-account rate limiting in addition to per-IP.

**Implementation blocker:** NO

---

## LOW Findings

### F-13: Default INTERNAL_SECRET in Production

**Finding ID:** F-13
**Severity:** LOW
**Confidence:** CONFIRMED
**Category:** SECURITY

**Summary:** Application can start with the default development secret "changeme-in-production".

**Expected behavior:** Production should reject the default secret.

**Actual evidence:**
```python
INTERNAL_SECRET = os.getenv("INTERNAL_SECRET", "changeme-in-production")
```

**Evidence 1:**
```
file: app/auth.py
line: 48
```

**Recommended design decision:** Add startup validation that fails if secret is not set.

**Implementation blocker:** NO

---

### F-14: Audit Log Not Immutable

**Finding ID:** F-14
**Severity:** LOW
**Confidence:** CONFIRMED
**Category:** DATABASE_SCHEMA

**Summary:** Audit logs can be modified or deleted because there's no DB-level immutability.

**Expected behavior:** Audit logs should be immutable once created.

**Actual evidence:**
```sql
-- schema-core-v3.3.sql
CREATE TABLE audit_logs (
    -- No immutability constraint
);
```

**Evidence 1:**
```
file: infra/postgres/schema-core-v3.3.sql
section: audit_logs table
```

**Recommended design decision:** Add trigger to prevent UPDATE/DELETE, or document as application-level invariant.

**Implementation blocker:** NO

---

### F-15: Concurrent Session Updates

**Finding ID:** F-15
**Severity:** LOW
**Confidence:** PROBABLE
**Category:** CONCURRENCY

**Summary:** Session updates (activity timestamp, etc.) use read-modify-write without explicit locking.

**Expected behavior:** Concurrent updates should be handled safely.

**Actual evidence:**
```python
# app/auth.py - activity update
session.last_activity_at = datetime.utcnow()
```

**Evidence 1:**
```
file: app/auth.py
function: refresh_token
line: 640
```

**Recommended design decision:** Use optimistic locking or accept eventual consistency for activity timestamps.

**Implementation blocker:** NO

---

## INFO Findings

### F-16: Auto-Lock Not Implemented

**Finding ID:** F-16
**Severity:** INFO
**Confidence:** CONFIRMED
**Category:** FEATURE

**Summary:** The `failed_login_count` field exists but never triggers account lockout.

**Evidence:**
```python
# app/auth.py line 345
user.failed_login_count += 1
# Never checked against threshold
```

**Recommended design decision:** Implement auto-lock or remove the counter.

---

### F-17: Escalation Not Implemented

**Finding ID:** F-17
**Severity:** INFO
**Confidence:** CONFIRMED
**Category:** FEATURE

**Summary:** Alert timeline has "escalated" event type but no endpoint to trigger it.

**Evidence:**
```python
# app/schemas.py
class TimelineEventType(str, Enum):
    ESCALATED = "escalated"  # Exists but never used
```

---

## Summary by Severity

| ID | Finding | Severity | Category | Blocker |
|----|---------|----------|----------|---------|
| F-01 | Invalid CHECK constraints | BLOCKER | DATABASE | YES |
| F-02 | MFA race condition | CRITICAL | AUTHENTICATION | YES |
| F-03 | No RBAC enforcement | CRITICAL | AUTHORIZATION | YES |
| F-04 | CORS misconfiguration | HIGH | SECURITY | NO |
| F-05 | Outbox not implemented | HIGH | RELIABILITY | NO |
| F-06 | Reconciliation not scheduled | HIGH | RELIABILITY | NO |
| F-07 | IP spoofing | HIGH | SECURITY | NO |
| F-08 | Refresh token replay | HIGH | AUTHENTICATION | NO |
| F-09 | JWT vs opaque tokens | MEDIUM | DOCUMENTATION | NO |
| F-10 | MFA IP binding unused | MEDIUM | SECURITY | NO |
| F-11 | NOW() in partial index | MEDIUM | DATABASE | NO |
| F-12 | Rate limit per-IP only | MEDIUM | SECURITY | NO |
| F-13 | Default secret | LOW | SECURITY | NO |
| F-14 | Audit not immutable | LOW | DATABASE | NO |
| F-15 | Session update race | LOW | CONCURRENCY | NO |
| F-16 | Auto-lock not implemented | INFO | FEATURE | NO |
| F-17 | Escalation not implemented | INFO | FEATURE | NO |

---

## Top 10 Issues

1. **Invalid PostgreSQL CHECK constraints** - 7 detection tables and 2 ML tables cannot be created
2. **No authorization enforcement** - All endpoints accessible without authentication
3. **MFA race condition** - Concurrent OTP verification can create multiple sessions
4. **IP spoofing** - X-Forwarded-For trust allows bypass of rate limiting
5. **Outbox not implemented** - Events can be lost on crash
6. **Reconciliation not scheduled** - Failed attempts never re-processed
7. **Refresh token replay** - Stolen tokens remain valid after legitimate refresh
8. **CORS misconfiguration** - Wildcard with credentials rejected by browsers
9. **JWT vs opaque token mismatch** - Documentation contradicts implementation
10. **MFA IP binding unused** - Feature stored but never validated
