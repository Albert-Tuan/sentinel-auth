# Sentinel Auth - Security Invariants

## 1. Authentication Invariants

### INV-AUTH-001: No Authenticated Session Before All Conditions Satisfied

**Statement:** No session or access token shall be issued before credentials are verified AND any required MFA is completed.

**Business Reason:** Prevents credential theft from immediately granting access.

**Enforcement:**
- Code: `auth.py` login() requires password verification before session creation
- Code: MFA gate blocks session creation when `user.detection_mfa_once` or `user.admin_mfa_required` is true
- DB: No constraint enforces this (relies on code)

**Test:** None explicitly validates this invariant

**Failure Consequence:** Attacker with stolen credentials gains immediate access without MFA.

**Status:** ENFORCED_BY_CODE_ONLY

### INV-AUTH-002: Revoked Session Cannot Be Refreshed

**Statement:** A session with `revoked_at` set shall not be usable for refresh or access.

**Business Reason:** Enables immediate session termination (password change, compromise, logout).

**Enforcement:**
- Code: `auth.py` refresh() checks `Session.revoked_at IS NULL`
- Code: `auth.py` logout() sets `revoked_at`
- DB: No constraint prevents refresh of revoked sessions

**Test:** Covered by test_internal_actions.py (revocation tests)

**Failure Consequence:** Revoked session remains usable until natural expiry.

**Status:** ENFORCED_BY_CODE_ONLY

### INV-AUTH-003: Privilege Revocation Effect on Tokens

**Statement:** When a user's privileges are revoked or role removed, existing tokens must become invalid.

**Business Reason:** Enables immediate de-provisioning.

**Business Decision Required:** What is the expected behavior?
- A) Tokens remain valid until natural expiry (privilege check on each request)
- B) Tokens are immediately invalidated (requires token blacklist or session revocation)

**Current Behavior:** UNDEFINED - No session revocation occurs on role changes.

**Enforcement:** NONE

**Status:** NOT_DECIDED

## 2. MFA Invariants

### INV-MFA-001: Successful MFA Challenge Consumed Only Once

**Statement:** A valid MFA code shall be usable for at most one session creation.

**Business Reason:** Prevents OTP replay attacks.

**Enforcement:**
- Code: `auth.py` mfa_verify() checks `notification.verified_at` before processing
- Code: After verification, `notification.verified_at` is set
- DB: No UNIQUE constraint on `(mfa_transaction_id, verified_at)` or similar

**Test:** No test verifies single-use property under concurrent requests.

**Failure Consequence:** Same OTP can create multiple sessions.

**Status:** ENFORCED_BY_CODE_ONLY (with race condition potential)

### INV-MFA-002: Expired Challenge Cannot Create Session

**Statement:** An MFA transaction with `expires_at` in the past shall not create a session.

**Business Reason:** Limits OTP validity window.

**Enforcement:**
- Code: `auth.py` mfa_verify() checks `mfa_txn.expires_at > now`
- DB: Partial check via application logic, no DB-level enforcement

**Test:** No explicit test for expired challenge rejection.

**Failure Consequence:** Expired OTP could create session (if clock skew or race).

**Status:** ENFORCED_BY_CODE_ONLY

### INV-MFA-003: Concurrent MFA Verification Cannot Consume OTP Twice

**Statement:** When two concurrent requests verify the same OTP, at most one shall succeed.

**Business Reason:** Prevents race condition in OTP consumption.

**Enforcement:** 
- Code: `mfa_verify()` sets `notification.verified_at` after checking it
- DB: No pessimistic lock or optimistic versioning

**Test:** NOT TESTED - No concurrent test exists.

**Failure Consequence:** Two concurrent requests both see `verified_at=None` and both create sessions.

**Status:** VULNERABLE_TO_RACE_CONDITION

## 3. Detection Invariants

### INV-DET-001: One Login Attempt Receives At Most One Risk Assessment

**Statement:** Each `login_attempts` row shall have at most one `risk_assessments` row.

**Business Reason:** Prevents duplicate risk scoring from affecting decisions.

**Enforcement:**
- Code: `process_attempt()` creates one RiskAssessment
- DB: UNIQUE constraint on `login_attempt_id` in risk_assessments

**Test:** Not explicitly tested for idempotency.

**Failure Consequence:** Duplicate assessments could be created.

**Status:** COVERED

### INV-DET-002: Duplicate Delivery Does Not Create Duplicate Side Effects

**Statement:** Re-delivery of the same LoginEvent (same `event_id`) shall not create duplicate alerts or actions.

**Business Reason:** Event systems can deliver at-least-once; system must handle duplicates.

**Enforcement:**
- Code: `receive_login_event()` checks for existing `event_id` before processing
- DB: UNIQUE constraint on `event_id` in login_attempts

**Test:** Not explicitly tested.

**Failure Consequence:** Duplicate LoginEvent could create duplicate alerts.

**Status:** ENFORCED_BY_CODE_AND_CONSTRAINT

## 4. Alert/SOC Invariants

### INV-ALERT-001: Alert State Transitions Must Be Authorized and Audited

**Statement:** Every alert status change shall be recorded in `alert_timeline`.

**Business Reason:** Complete audit trail for SOC actions.

**Enforcement:**
- Code: `alerts.py` creates timeline entries for acknowledge, resolve, assign
- DB: No constraint - application-level only

**Test:** test_alert_actions.py verifies timeline entries are created.

**Failure Consequence:** Unaudited state changes possible.

**Status:** PARTIALLY_COVERED

### INV-ALERT-002: Only One Active Policy at a Time

**Statement:** At most one policy shall have `is_active = true` at any time.

**Business Reason:** Prevents conflicting rules from simultaneous enforcement.

**Enforcement:**
- DB: CHECK constraint `chk_single_active_policy` using subquery (INVALID - PostgreSQL prohibits subqueries in CHECK)
- Code: `activate_policy()` deactivates old policy before activating new

**Test:** Not explicitly tested.

**Failure Consequence:** Two active policies could exist if DB constraint fails.

**Status:** DB_CONSTRAINT_INVALID

## 5. Rate Limiting Invariants

### INV-RATE-001: Rate Limit Counter Must Not Overflow

**Statement:** Rate limit `count` shall never exceed reasonable bounds.

**Business Reason:** Prevents integer overflow or counter manipulation.

**Enforcement:**
- DB: CHECK constraint `count >= 0`
- DB: CHECK constraint `max_count > 0`
- Code: Increments atomically (but read-modify-write is not atomic)

**Test:** Not tested.

**Failure Consequence:** Counter could go negative or overflow.

**Status:** PARTIAL_COVERAGE

## 6. Session Invariants

### INV-SESSION-001: Session Expiry Must Be Enforced

**Statement:** Expired sessions (`expires_at < now`) shall not grant access.

**Business Reason:** Token expiry is a security boundary.

**Enforcement:**
- Code: `verify_user_token()` in devices.py checks `expires_at > now`
- Code: refresh() checks `expires_at` before allowing refresh
- DB: No constraint

**Test:** Not explicitly tested.

**Failure Consequence:** Expired token could continue working.

**Status:** ENFORCED_BY_CODE_ONLY

## 7. Audit Invariants

### INV-AUDIT-001: Security-Sensitive Changes Must Leave Immutable Trail

**Statement:** Audit log entries shall not be modifiable or deletable after creation.

**Business Reason:** Non-repudiation of security actions.

**Enforcement:**
- DB: No immutability constraint (no trigger preventing UPDATE/DELETE)
- DB: Cascade on `actor_id` FK could delete audit entries
- Code: No enforcement

**Evidence:**
```sql
audit_logs: audit_logs
    actor_id UUID REFERENCES users(id) ON DELETE SET NULL
    -- DELETE on users cascades to NULL actor_id, not deletion
    -- But DELETE on audit_logs directly is unrestricted
```

**Test:** None verify immutability.

**Failure Consequence:** Audit entries could be modified or deleted.

**Status:** NOT_ENFORCED

### INV-AUDIT-002: Forensic Evidence Must Not Be Deleted

**Statement:** Login attempts and detection logs shall not be deleted without explicit policy.

**Business Reason:** Forensic preservation.

**Enforcement:**
- `login_attempts` has CASCADE FK from `risk_assessments`, `detection_logs`, `alerts`
- `login_attempts` has no explicit DELETE prevention
- `audit_logs` can be deleted

**Evidence:**
```sql
-- risk_assessments has ON DELETE CASCADE
login_attempt_id UUID REFERENCES login_attempts(id) ON DELETE CASCADE
-- alerts has ON DELETE CASCADE  
login_attempt_id UUID REFERENCES login_attempts(id) ON DELETE CASCADE
```

**Test:** None verify preservation behavior.

**Failure Consequence:** Deleting a login attempt removes all associated forensic evidence.

**Status:** NOT_ENFORCED

## 8. Token Invariants

### INV-TOKEN-001: Access Token Hash Cannot Be Recovered

**Statement:** The original access token shall not be recoverable from storage.

**Business Reason:** Prevents token theft if DB is compromised.

**Enforcement:**
- Code: `hash_token()` uses SHA256 before storage
- Code: Token generated using `secrets.token_urlsafe(32)` (128 bits of entropy)
- DB: No constraint

**Test:** Not tested.

**Failure Consequence:** Weak tokens could be brute-forced.

**Status:** COVERED

## 9. Invariant Enforcement Summary

| Invariant | DB Constraint | App Code | Test | Status |
|-----------|---------------|----------|------|--------|
| INV-AUTH-001 | ❌ | ✅ | ❌ | WEAK |
| INV-AUTH-002 | ❌ | ✅ | ✅ | MODERATE |
| INV-AUTH-003 | ❌ | ❌ | ❌ | MISSING |
| INV-MFA-001 | ❌ | ✅ | ❌ | WEAK |
| INV-MFA-002 | ❌ | ✅ | ❌ | WEAK |
| INV-MFA-003 | ❌ | ✅ | ❌ | VULNERABLE |
| INV-DET-001 | ✅ | ✅ | ❌ | STRONG |
| INV-DET-002 | ✅ | ✅ | ❌ | STRONG |
| INV-ALERT-001 | ❌ | ✅ | ✅ | MODERATE |
| INV-ALERT-002 | ❌ (invalid) | ✅ | ❌ | INVALID |
| INV-RATE-001 | ✅ | ❌ | ❌ | MODERATE |
| INV-SESSION-001 | ❌ | ✅ | ❌ | WEAK |
| INV-AUDIT-001 | ❌ | ❌ | ❌ | MISSING |
| INV-AUDIT-002 | ❌ | ❌ | ❌ | MISSING |
| INV-TOKEN-001 | ❌ | ✅ | ❌ | MODERATE |

## 10. Recommendations

### P0 (Critical - Must Fix)
1. **Fix INVALID DB constraints** (policies single-active, model_versions production)
2. **Implement MFA concurrency protection** (INV-MFA-003)
3. **Decide INV-AUTH-003** (token validity after privilege change)

### P1 (High - Should Fix)
1. Add DB-level immutability for audit_logs (INV-AUDIT-001)
2. Add DB-level protection for forensic evidence (INV-AUDIT-002)
3. Add optimistic locking for SOC alert updates (concurrent modification)
4. Add DB-level protection for MFA one-time use (INV-MFA-001)

### P2 (Medium - Nice to Have)
1. Add explicit tests for all invariants
2. Document which invariants are enforced vs. conventional
3. Add database-level constraints where code-only enforcement is insufficient
