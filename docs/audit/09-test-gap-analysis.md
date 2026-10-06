# Sentinel Auth - Test Gap Analysis

## Executive Summary

The test suite has **184 passing tests** but significant gaps exist in:
- PostgreSQL-specific testing
- Integration testing
- Security testing
- Concurrency testing
- Failure injection testing

---

## 1. Test Execution Summary

| Metric | Value |
|--------|-------|
| Total Tests | 184 |
| Passing | 184 (100%) |
| Failing | 0 |
| Skipped | 0 |
| Duration | 1.43s |
| Database | SQLite (in-memory) |

**Note:** All tests run against SQLite, not PostgreSQL.

---

## 2. PostgreSQL-Specific Gaps

### 2.1 Types Not Tested on SQLite

| Feature | PostgreSQL Behavior | SQLite Behavior | Gap |
|---------|-------------------|----------------|-----|
| INET type | Native IP storage | TEXT fallback | Semantic differences |
| JSONB | Native JSONB | JSON | Operator differences |
| Partial indexes | Supported | Not supported | Index coverage unknown |
| UUID | Native | TEXT fallback | Type handling unknown |
| CHECK constraints | Enforced | Not enforced | Constraints not validated |
| Triggers | Supported | Limited | Trigger behavior unknown |
| SKIP LOCKED | Not tested | N/A | Concurrency unknown |
| Advisory locks | Not tested | N/A | Concurrency unknown |

### 2.2 Invalid Constraints Not Detected

The following invalid CHECK constraints exist in the schemas but are not tested:

1. **policies.chk_single_active_policy** - Uses subquery in CHECK
2. **model_versions.uq_model_active_production** - Uses subquery in CHECK

**Evidence:** SQLite doesn't enforce CHECK constraints, so these pass tests.

---

## 3. Authentication Testing Gaps

| Test | Status | Gap |
|------|--------|-----|
| Login success | EMPTY | No assertion |
| Login invalid credentials | EMPTY | No assertion |
| MFA verify success | EMPTY | No assertion |
| MFA verify invalid | EMPTY | No assertion |
| Token refresh | MISSING | Not tested |
| Concurrent refresh | MISSING | Not tested |
| Refresh replay | MISSING | Not tested |
| Token expiration | MISSING | Not tested |
| Account lockout | MISSING | Not tested |
| Auto-unlock | MISSING | Not tested |
| Password change | MISSING | Not implemented |

**Gap Severity:** HIGH - Core auth flows not tested.

---

## 4. MFA Testing Gaps

| Test | Status | Gap |
|------|--------|-----|
| Concurrent OTP verification | MISSING | Race condition untested |
| OTP expired | MISSING | Expiry not validated |
| OTP replay | MISSING | Single-use not verified |
| Wrong OTP limit | MISSING | Lockout not tested |
| IP binding | MISSING | bound_ip not validated |
| Email delivery failure | MISSING | Not tested |
| Multiple pending challenges | MISSING | Not tested |

**Gap Severity:** HIGH - MFA security critical.

---

## 5. Session Testing Gaps

| Test | Status | Gap |
|------|--------|-----|
| Session listing | MISSING | Not tested |
| Session revocation | MISSING | Not tested |
| Revocation + refresh race | MISSING | Not tested |
| Session expiry | MISSING | Not tested |
| Role change → session | MISSING | Not tested |
| Password change → session | MISSING | Not tested |
| Max sessions per user | MISSING | Not enforced |

**Gap Severity:** MEDIUM - Session lifecycle untested.

---

## 6. Detection Engine Testing Gaps

| Test | Status | Gap |
|------|--------|-----|
| Login event endpoint | MISSING | Not tested |
| Pre-token check endpoint | MISSING | Not tested |
| Score endpoint | PARTIAL | ML only, not full flow |
| Alert creation | MISSING | Not tested |
| Policy activation | MISSING | Not tested |
| Threshold boundaries | COVERED | Good |
| ML timeout | COVERED | Good |
| ML failure | COVERED | Good |

**Gap Severity:** MEDIUM - Core detection not tested end-to-end.

---

## 7. SOC Workflow Testing Gaps

| Test | Status | Gap |
|------|--------|-----|
| List alerts | MISSING | Not tested |
| Acknowledge alert | MISSING | Not tested |
| Resolve alert | MISSING | Not tested |
| Assign alert | MISSING | Not tested |
| Alert state transitions | MISSING | Not tested |
| Concurrent alert update | MISSING | Lost update risk |
| Timeline creation | PARTIAL | Via actions only |
| Escalation | MISSING | Not implemented |

**Gap Severity:** MEDIUM - SOC workflow incomplete.

---

## 8. Integration Testing Gaps

| Test | Status | Gap |
|------|--------|-----|
| Core → Detection | MISSING | No HTTP integration |
| Detection → ML | MISSING | No HTTP integration |
| Detection → Core callback | MISSING | No HTTP integration |
| Outbox poller | MISSING | Not implemented |
| Reconciliation | MISSING | Function exists, not called |

**Gap Severity:** HIGH - No service integration tested.

---

## 9. Security Testing Gaps

| Test | Status | Gap |
|------|--------|-----|
| SQL injection | MISSING | Not tested |
| XSS | N/A | No user output |
| CSRF | MISSING | CORS not tested |
| Rate limit bypass | MISSING | Not tested |
| IP spoofing | MISSING | Not tested |
| RBAC enforcement | MISSING | Not implemented |
| Token theft | MISSING | Not tested |
| Session fixation | MISSING | Not tested |

**Gap Severity:** CRITICAL - Security controls not tested.

---

## 10. Concurrency Testing Gaps

| Scenario | Status | Gap |
|----------|--------|-----|
| Concurrent registration | MISSING | UNIQUE tested by DB |
| Concurrent rate limit | MISSING | Not tested |
| Concurrent MFA verify | MISSING | Race condition |
| Concurrent refresh | MISSING | Race condition |
| Revoke + refresh | MISSING | Race condition |
| Two Detection workers | MISSING | Event processing |
| Two Outbox workers | MISSING | Not implemented |
| Two SOC analysts | MISSING | Lost update |

**Gap Severity:** HIGH - Concurrency not validated.

---

## 11. Failure Injection Gaps

| Failure | Status | Gap |
|---------|--------|-----|
| Database unavailable | MISSING | Not tested |
| Detection unavailable | PARTIAL | Only gate tested |
| ML unavailable | COVERED | Good |
| Core unavailable | MISSING | Callback not tested |
| Network timeout | MISSING | Not tested |
| Malformed response | MISSING | Not tested |
| Partial write | MISSING | Not tested |

**Gap Severity:** MEDIUM - Failure modes not tested.

---

## 12. Schema/Migration Testing Gaps

| Test | Status | Gap |
|------|--------|-----|
| Clean bootstrap | MISSING | Not tested on PostgreSQL |
| Migration up | MISSING | Not implemented |
| Migration down | MISSING | Not implemented |
| FK cascade behavior | MISSING | Not tested |
| Cascade delete safety | MISSING | Not tested |
| Index effectiveness | MISSING | Not measured |

**Gap Severity:** HIGH - PostgreSQL compatibility unknown.

---

## 13. Contract Testing Gaps

| Contract | Status | Gap |
|----------|--------|-----|
| API contracts | MISSING | Not validated |
| Internal API | PARTIAL | Secret tested only |
| Error responses | MISSING | Not validated |
| Response schemas | MISSING | Not validated |

**Gap Severity:** MEDIUM - API contracts not enforced.

---

## 14. Recommended Test Additions

### P0 (Critical)

1. **PostgreSQL Bootstrap Test**
   ```python
   def test_postgresql_clean_bootstrap():
       """Verify all schemas create successfully on PostgreSQL."""
   ```

2. **Concurrent MFA Race Condition**
   ```python
   @pytest.mark.asyncio
   async def test_concurrent_mfa_verification_single_use():
       """Two concurrent requests cannot both succeed."""
   ```

3. **Authorization Enforcement**
   ```python
   def test_unauthenticated_access_denied():
       """Endpoints require valid JWT."""
   ```

4. **RBAC Enforcement**
   ```python
   def test_user_cannot_access_soc_endpoints():
       """USER role cannot access SOC endpoints."""
   ```

### P1 (High)

5. **Token Refresh Race**
   ```python
   @pytest.mark.asyncio
   async def test_concurrent_refresh_rejected():
       """Only one refresh should succeed."""
   ```

6. **Session Revocation Effectiveness**
   ```python
   def test_revoked_session_cannot_refresh():
       """Revoked session cannot refresh."""
   ```

7. **IP Spoofing Resistance**
   ```python
   def test_forwarded_for_not_trusted_direct():
       """When not behind proxy, IP spoofing not possible."""
   ```

8. **Rate Limit Accuracy**
   ```python
   @pytest.mark.asyncio
   async def test_rate_limit_exactly_5():
       """After 5 requests, 6th is rejected."""
   ```

### P2 (Medium)

9. **SOC Concurrent Update**
   ```python
   @pytest.mark.asyncio
   async def test_two_analysts_same_alert():
       """Second update should fail or be rejected."""
   ```

10. **Outbox Event Delivery**
    ```python
    @pytest.mark.asyncio
    async def test_login_event_delivered():
        """Login creates event that Detection receives."""
    ```

11. **ML Timeout Handling**
    ```python
    async def test_ml_timeout_uses_rule_only():
        """When ML times out, combined = rule_score."""
    ```

12. **Alert State Machine**
    ```python
    def test_alert_cannot_skip_acknowledged():
        """Alert must be acknowledged before resolved."""
    ```

### P3 (Low - Nice to Have)

13. **Password Policy Enforcement**
14. **Email Validation**
15. **OTP Format Validation**
16. **Session Listing Pagination**

---

## 15. Test Database Strategy

### Current Strategy
- SQLite in-memory for all tests
- Fast execution (1.43s)
- No PostgreSQL-specific features tested

### Recommended Strategy

**Tier 1: Unit Tests (Fast)**
- SQLite
- Target: All business logic
- Time: < 5s

**Tier 2: Integration Tests (Medium)**
- PostgreSQL (same version as production)
- Target: Schema validation, constraints
- Time: < 30s
- Run: On PR, nightly

**Tier 3: Contract Tests (API)**
- Test against running service
- Target: HTTP endpoints
- Time: < 60s
- Run: On PR

**Tier 4: E2E Tests (Slow)**
- Full stack with Docker
- Target: User flows
- Time: < 5min
- Run: On PR, nightly

---

## 16. CI/CD Integration

### Minimum Requirements for PR Merge

1. ✅ Tier 1 tests (all 184 passing)
2. ⬜ Tier 2 PostgreSQL bootstrap test
3. ⬜ Authorization tests
4. ⬜ Concurrent MFA test
5. ⬜ Security tests (rate limiting, etc.)

### Recommended for Production

6. ⬜ Tier 3 contract tests
7. ⬜ Tier 4 E2E tests
8. ⬜ Performance benchmarks
9. ⬜ Security scan (SQL injection, etc.)
10. ⬜ Dependency audit
