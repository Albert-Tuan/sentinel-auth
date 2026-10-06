# Sentinel Auth Implementation Readiness Audit

## Reviewed Commit

- **Branch:** dev
- **Commit SHA:** 9dcbd80b3b214b4665d8b25840eb26fb30f6ac29
- **Audit Date:** 2026-10-06
- **Audit Duration:** Comprehensive multi-day review

---

## Final Verdict

**NOT_READY_ARCHITECTURE_REWORK_REQUIRED**

The repository contains significant architectural, security, and database issues that must be resolved before meaningful implementation can continue. While the detection engine logic is well-tested and documented, the following critical issues prevent safe production deployment:

1. Database schemas cannot bootstrap on PostgreSQL
2. Authorization is completely missing
3. Concurrency vulnerabilities exist in MFA handling

---

## P0 Blockers (Must Fix Before Any Implementation)

### P0-01: PostgreSQL Schema Bootstrap Failure
**Severity:** BLOCKER
**Files:** `infra/postgres/schema-detection-v3.3.sql`, `infra/postgres/schema-ml-service-v3.3.sql`

Two schemas fail to create any tables due to invalid PostgreSQL CHECK constraints using subqueries:
- Detection schema: 7 of 7 tables not created
- ML schema: 2 of 3 tables not created

**Impact:** Production deployment impossible.

**Required Fix:**
1. Remove subquery CHECK constraints from `policies` and `model_versions` tables
2. Implement trigger-based single-active enforcement
3. Verify all tables create successfully on PostgreSQL

---

### P0-02: Complete Authorization Bypass
**Severity:** CRITICAL
**Files:** `app/main.py`, `app/auth.py`, `app/alerts.py`, `app/detection.py`

All endpoints are accessible without authentication. No JWT validation exists. Any user can:
- List and manipulate all alerts
- Access all user sessions
- Trigger protective actions
- View all audit data

**Impact:** System is completely insecure.

**Required Fix:**
1. Implement JWT validation middleware
2. Add role-based access control decorators
3. Validate authorization on all protected endpoints
4. Write authorization tests

---

### P0-03: MFA Race Condition
**Severity:** CRITICAL
**Files:** `app/auth.py`

Concurrent OTP verification can create multiple sessions because `verified_at` check and write are not atomic.

**Impact:** OTP replay vulnerability.

**Required Fix:**
1. Use `SELECT FOR UPDATE` during MFA verification
2. Or implement optimistic locking with version column
3. Write concurrent MFA test

---

## P1 Issues (Fix Before Implementing Affected Subsystem)

### P1-01: IP Spoofing Vulnerability
**Severity:** HIGH
**Files:** `app/auth.py`, `app/detection.py`

X-Forwarded-For is accepted from any source without deployment validation.

**Decision Required:** Define trusted proxy configuration or reject header entirely.

---

### P1-02: Outbox Pattern Not Implemented
**Severity:** HIGH
**Files:** `app/auth.py`

Login events can be lost if app crashes after commit.

**Decision Required:** Implement outbox pattern or document acceptable risk.

---

### P1-03: Reconciliation Not Scheduled
**Severity:** HIGH
**Files:** `app/detection.py`

`rescore_failed_attempts()` function exists but is never invoked.

**Decision Required:** Schedule via cron/background worker or remove function.

---

### P1-04: CORS Misconfiguration
**Severity:** HIGH
**Files:** `app/main.py`

`allow_origins=["*"]` with `allow_credentials=True` is rejected by browsers.

**Required Fix:** Configure explicit origins from environment variable.

---

### P1-05: Refresh Token Replay
**Severity:** HIGH
**Files:** `app/auth.py`

Stolen refresh tokens remain valid after legitimate refresh.

**Decision Required:** Implement token family tracking with reuse detection.

---

## Security Findings

| ID | Finding | Severity | Confidence |
|----|---------|----------|------------|
| SEC-01 | No authorization enforcement | CRITICAL | CONFIRMED |
| SEC-02 | MFA race condition | CRITICAL | HIGH |
| SEC-03 | IP spoofing vulnerability | HIGH | HIGH |
| SEC-04 | CORS misconfiguration | HIGH | CONFIRMED |
| SEC-05 | Refresh token replay | HIGH | HIGH |
| SEC-06 | Rate limit per-IP only | MEDIUM | HIGH |
| SEC-07 | MFA IP binding unused | MEDIUM | CONFIRMED |
| SEC-08 | Default INTERNAL_SECRET | LOW | CONFIRMED |

---

## Architecture Contradictions

| ID | Conflict | Classification | Severity |
|----|-----------|----------------|----------|
| ARC-01 | Three services vs single FastAPI app | DOCUMENTATION | MEDIUM |
| ARC-02 | Outbox pattern documented but not implemented | DOCUMENTATION | HIGH |
| ARC-03 | JWT documented vs opaque tokens used | DOCUMENTATION | MEDIUM |
| ARC-04 | CRITICAL → LOCK_USER vs REVOKE_SESSIONS | OBSOLETE | LOW |

---

## Database Findings

| ID | Finding | Severity |
|----|---------|----------|
| DB-01 | Invalid CHECK constraints (2 schemas) | BLOCKER |
| DB-02 | Partial index with NOW() fails | MEDIUM |
| DB-03 | Audit logs not immutable | LOW |
| DB-04 | MFA IP binding semantic mismatch | MEDIUM |

---

## Authentication / MFA Findings

| ID | Finding | Severity |
|----|---------|----------|
| AUTH-01 | No JWT validation middleware | CRITICAL |
| AUTH-02 | MFA race condition | CRITICAL |
| AUTH-03 | Token family tracking not implemented | HIGH |
| AUTH-04 | MFA IP binding unused | MEDIUM |
| AUTH-05 | Auto-lock not implemented | INFO |
| AUTH-06 | Token expiry not enforced at request time | MEDIUM |

---

## Detection / ML Findings

| ID | Finding | Severity |
|----|---------|----------|
| DET-01 | Reconcile function never scheduled | HIGH |
| DET-02 | Outbox not implemented | HIGH |
| DET-03 | Heuristic model instead of trained ML | INFO |
| DET-04 | Model registry with no actual model files | INFO |

---

## SOC Workflow Findings

| ID | Finding | Severity |
|----|---------|----------|
| SOC-01 | No authorization for SOC endpoints | CRITICAL |
| SOC-02 | Escalation not implemented | INFO |
| SOC-03 | Concurrent alert updates not protected | MEDIUM |

---

## Concurrency Findings

| ID | Finding | Severity |
|----|---------|----------|
| CON-01 | MFA verification race | CRITICAL |
| CON-02 | Rate limit read-modify-write | MEDIUM |
| CON-03 | Session activity update | LOW |
| CON-04 | SOC alert concurrent modification | MEDIUM |

---

## Failure Recovery Findings

| ID | Finding | Severity |
|----|---------|----------|
| REC-01 | Reconcile not scheduled | HIGH |
| REC-02 | Outbox not implemented | HIGH |
| REC-03 | No dead-letter queue for outbox | MEDIUM |

---

## Documentation Drift

| ID | Finding | Classification |
|----|---------|----------------|
| DOC-01 | Three-service architecture vs. single app | DOCUMENTATION |
| DOC-02 | JWT tokens vs. opaque tokens | DOCUMENTATION |
| DOC-03 | Outbox "implemented" (acknowledged) | DOCUMENTATION |
| DOC-04 | Old diagrams with LOCK_USER | OBSOLETE |

---

## Test Gaps

| Category | Coverage |
|----------|----------|
| Authentication | EMPTY (stubs only) |
| MFA | PARTIAL (no concurrent tests) |
| Session management | MISSING |
| SOC workflow | PARTIAL |
| Integration | NONE |
| Security | NONE |
| PostgreSQL | NONE |
| Concurrency | NONE |

---

## Readiness Gates

| Gate | Status | Notes |
|------|--------|-------|
| G01 Business requirements | PARTIAL | Some features undocumented |
| G02 Actor/RBAC model | FAIL | Authorization not enforced |
| G03 Use cases | COVERED | Well documented |
| G04 Workflow completeness | PARTIAL | Some workflows incomplete |
| G05 Authentication lifecycle | PARTIAL | No JWT validation |
| G06 MFA lifecycle | PARTIAL | Race condition exists |
| G07 Session lifecycle | PARTIAL | Core logic exists |
| G08 Risk-gate semantics | COVERED | Well tested |
| G09 Detection rules | COVERED | Well tested |
| G10 ML contract | COVERED | Schema matches |
| G11 Alert/SOC lifecycle | PARTIAL | Authorization missing |
| G12 Protective actions | COVERED | Well tested |
| G13 Service boundaries | FAIL | Single-process vs. three-service |
| G14 API contracts | PARTIAL | No validation tests |
| G15 Database schema | FAIL | Cannot bootstrap |
| G16 Transaction boundaries | PARTIAL | Outbox not implemented |
| G17 Idempotency | COVERED | Good coverage |
| G18 Concurrency | FAIL | Race conditions exist |
| G19 Failure recovery | FAIL | Reconciliation not scheduled |
| G20 Service-to-service security | PARTIAL | Secret exists but no rotation |
| G21 Auditability | PARTIAL | Not immutable |
| G22 Privacy/retention | MISSING | No retention policy |
| G23 Threat model | PARTIAL | Document exists but gaps |
| G24 PostgreSQL bootstrap | FAIL | Schema errors |
| G25 Test coverage | PARTIAL | Good for detection, weak for auth |
| G26 Documentation/code consistency | FAIL | Multiple conflicts |
| G27 Deployment model | FAIL | Architecture undefined |

---

## Open Decisions

| ID | Decision | Priority | Blocks |
|----|----------|----------|--------|
| DEC-001 | Service architecture (3 vs. 1) | HIGH | YES |
| DEC-002 | Role change → session invalidation | HIGH | YES |
| DEC-003 | IP spoofing prevention | HIGH | YES |
| DEC-004 | Outbox implementation | HIGH | YES |
| DEC-005 | Authorization enforcement | CRITICAL | YES |
| DEC-006 | Account auto-lock | MEDIUM | NO |
| DEC-007 | Refresh token family | MEDIUM | NO |
| DEC-008 | MFA IP binding | MEDIUM | NO |
| DEC-009 | Reconciliation scheduling | HIGH | YES |
| DEC-010 | Token expiry enforcement | LOW | NO |

---

## Recommended Fix Order

### Phase 1: Database Bootstrap (Week 1)
1. Fix invalid CHECK constraints in detection schema
2. Fix invalid CHECK constraints in ML schema
3. Fix partial index with NOW() in core schema
4. Add PostgreSQL integration tests to CI
5. Verify all 23 tables create successfully

### Phase 2: Authorization (Week 1-2)
6. Implement JWT validation middleware
7. Add role-based access control
8. Protect all SOC/admin endpoints
9. Write authorization tests
10. Document authorization model

### Phase 3: Security Fixes (Week 2)
11. Fix MFA race condition with SELECT FOR UPDATE
12. Configure CORS properly
13. Implement IP spoofing protection
14. Implement refresh token family tracking

### Phase 4: Reliability (Week 2-3)
15. Implement outbox pattern
16. Schedule reconciliation worker
17. Add failure injection tests

### Phase 5: Documentation (Week 3)
18. Document single-process architecture
19. Update JWT vs. opaque token documentation
20. Clarify escalation as timeline event
21. Update old diagrams

---

## What Can Safely Be Implemented Now

1. **Detection engine logic** - Already well-tested and documented
2. **Rule evaluation formula** - Already validated
3. **ML service endpoint** - Basic structure exists
4. **Schema ORM mapping** - Mostly correct (needs fixes above)
5. **Test infrastructure** - pytest setup works
6. **Documentation structure** - Comprehensive docs exist

---

## What Must NOT Be Implemented Yet

1. **SOC workflow endpoints** - No authorization protection
2. **Session management endpoints** - No authorization protection
3. **User management** - Authorization not enforced
4. **Production deployment** - Database won't bootstrap
5. **Integration testing** - Core security missing
6. **Feature development beyond detection** - Build on secure foundation first

---

## Audit Output Files

| File | Description |
|------|-------------|
| `00-review-context.md` | Audit scope, environment, test results |
| `01-system-model.md` | Architecture, actors, components |
| `02-traceability.md` | Requirements to implementation mapping |
| `03-invariants.md` | Security invariants and enforcement |
| `04-database-bootstrap.md` | PostgreSQL bootstrap test results |
| `05-trust-boundaries.md` | Trust model and security boundaries |
| `06-threat-model.md` | Threat analysis and mitigations |
| `07-cross-artifact-conflicts.md` | Documentation contradictions |
| `08-open-decisions.md` | Design decisions required |
| `09-test-gap-analysis.md` | Test coverage analysis |
| `10-findings.md` | All findings with evidence |
| `11-implementation-readiness.md` | This document |

---

## Summary Statistics

| Metric | Count |
|--------|-------|
| Total Findings | 17 |
| Blockers (P0) | 3 |
| High Priority (P1) | 5 |
| Medium Priority (P2) | 6 |
| Low Priority (P3) | 3 |
| Critical/High Security | 8 |
| Architecture Contradictions | 4 |
| Database Issues | 4 |
| Missing Features | 4 |
| Test Gaps | 9 categories |

---

## Final Statement

**Resolve P0 findings before continuing implementation.**

The detection engine is well-architected and thoroughly tested. However, critical infrastructure issues prevent safe expansion:

1. **Database**: 9 of 23 tables cannot be created
2. **Security**: Complete authorization bypass
3. **Concurrency**: MFA race condition

These issues must be resolved before implementing user-facing features or deploying to any environment beyond local development.

---

**Reviewed by:** Architecture Review Board
**Review Date:** 2026-10-06
**Next Review:** After P0 fixes are implemented
