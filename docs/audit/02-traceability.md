# Sentinel Auth - Traceability Matrix

## Coverage Status Legend

- **COVERED:** Implementation exists and matches requirement
- **PARTIAL:** Some implementation exists but incomplete
- **MISSING:** No implementation found
- **CONFLICT:** Implementation contradicts requirement
- **UNVERIFIED:** Cannot determine from evidence

## 1. Authentication Capabilities

| Capability | Requirement | Actor | Use Case | API | Test | Status |
|------------|-------------|-------|----------|-----|------|--------|
| Registration | U-01 | User | UC-01 | POST /auth/register | test_auth.py | PARTIAL |
| Login with credentials | U-01 | User | UC-01 | POST /auth/login | test_auth.py | PARTIAL |
| Password validation | U-01 | User | UC-01 | POST /auth/login | - | PARTIAL |
| Rate limiting | U-01 | User | UC-01 | - | - | PARTIAL |
| Failed login tracking | U-01 | User | UC-01 | - | - | PARTIAL |
| Account lockout | U-01 | User | UC-01 | - | - | MISSING |
| MFA verification | U-02 | User | UC-02 | POST /auth/mfa/verify | test_auth.py | PARTIAL |
| Session creation | U-03 | User | UC-03 | POST /auth/login | - | PARTIAL |
| Session listing | U-03 | User | UC-03 | GET /auth/sessions | - | PARTIAL |
| Session revocation | U-03 | User | UC-03 | DELETE /auth/sessions/{id} | - | PARTIAL |
| Token refresh | U-03 | User | UC-03 | POST /auth/refresh | - | MISSING |
| Trusted devices | U-05 | User | UC-05 | /api/v1/devices/* | - | PARTIAL |

## 2. Detection Engine Capabilities

| Capability | Requirement | Use Case | API | Test | Status |
|------------|-------------|----------|-----|------|--------|
| LoginEvent reception | DE-01 | UC-DE-01 | POST /internal/login-events | - | PARTIAL |
| Pre-token check | DE-01 | UC-DE-01 | POST /internal/pre-token-check | test_risk_gate.py | PARTIAL |
| Feature building | DE-02 | UC-DE-02 | - | test_detection.py | PARTIAL |
| Rule evaluation | DE-04 | UC-DE-04 | - | test_detection.py | COVERED |
| ML Service call | DE-03 | UC-DE-03 | POST /internal/ml/score | test_ml.py | PARTIAL |
| Risk scoring | DE-05 | UC-DE-05 | - | test_detection.py | COVERED |
| Alert creation | DE-06 | UC-DE-06 | - | - | PARTIAL |
| Action enforcement | DE-07 | UC-DE-07 | POST /internal/actions | test_risk_gate.py | COVERED |
| Policy management | DE-12 | UC-DE-15 | /api/v1/policies | test_detection.py | PARTIAL |
| Reconcile failed | DE-07 | UC-DE-07 | - (function exists) | test_risk_gate.py | PARTIAL |

## 3. SOC Workflow Capabilities

| Capability | Requirement | Use Case | API | Test | Status |
|------------|-------------|----------|-----|------|--------|
| List alerts | S-01 | UC-06 | GET /alerts | - | PARTIAL |
| Alert details | S-03 | UC-08 | GET /alerts/{id}/evidence | - | PARTIAL |
| Acknowledge alert | S-04 | UC-09 | POST /alerts/{id}/acknowledge | - | PARTIAL |
| Resolve alert | S-05 | UC-10 | POST /alerts/{id}/resolve | - | PARTIAL |
| Assign alert | S-04 | UC-09 | POST /alerts/{id}/assign | - | PARTIAL |
| Request action | S-06 | UC-11 | POST /alerts/{id}/actions | test_alert_actions.py | COVERED |
| Alert timeline | S-04 | UC-09 | GET /alerts/{id}/timeline | - | PARTIAL |

## 4. Security Invariants

| Invariant | Code Location | DB Constraint | Test | Status |
|-----------|--------------|----------------|------|--------|
| INV-AUTH-001 | auth.py login() | - | - | UNVERIFIED |
| INV-AUTH-002 | auth.py refresh() | - | - | MISSING |
| INV-AUTH-003 | - | - | - | MISSING |
| INV-MFA-001 | auth.py mfa_verify() | - | - | UNVERIFIED |
| INV-MFA-002 | auth.py mfa_verify() | CHECK expiry | - | PARTIAL |
| INV-MFA-003 | auth.py mfa_verify() | - | - | UNVERIFIED |
| INV-DET-001 | detection.py process_attempt() | UNIQUE login_attempt_id | - | PARTIAL |
| INV-DET-002 | detection.py receive_login_event() | UNIQUE event_id | - | PARTIAL |
| INV-ALERT-001 | alerts.py | CHECK status | - | PARTIAL |
| INV-RBAC-001 | - | - | - | MISSING |
| INV-AUDIT-001 | - | - | - | MISSING |

## 5. Database Entities

| Entity | Schema | ORM Model | Test | Bootstrap | Status |
|--------|--------|-----------|------|-----------|--------|
| users | core | User | - | PARTIAL | CONFLICT |
| roles | core | Role | - | PARTIAL | OK |
| user_roles | core | UserRole | - | - | OK |
| sessions | core | Session | - | - | OK |
| mfa_transactions | core | MfaTransaction | - | - | PARTIAL |
| mfa_notifications | core | MfaNotification | - | - | PARTIAL |
| ip_addresses | core | IpAddress | - | - | OK |
| rate_limits | core | RateLimit | - | - | PARTIAL |
| audit_logs | core | AuditLog | - | - | PARTIAL |
| outbox_events | core | OutboxEvent | - | - | DESIGNED_NOT_IMPLEMENTED |
| policies | detection | Policy | test_detection.py | FAIL | CONFLICT |
| login_attempts | detection | LoginAttempt | - | FAIL | CONFLICT |
| risk_assessments | detection | RiskAssessment | - | FAIL | CONFLICT |
| detection_logs | detection | DetectionLog | - | FAIL | CONFLICT |
| alerts | detection | Alert | test_alert_actions.py | FAIL | CONFLICT |
| alert_timeline | detection | AlertTimeline | - | FAIL | CONFLICT |
| soc_analysts | detection | SocAnalyst | - | FAIL | CONFLICT |
| model_versions | ml | ModelVersion | - | FAIL | CONFLICT |
| inference_logs | ml | InferenceLog | - | FAIL | CONFLICT |
| feature_statistics | ml | FeatureStatistic | - | FAIL | CONFLICT |

## 6. Orphan Artifacts

### 6.1 Orphan Requirements (in docs but no implementation)
- Account unlock mechanism
- Password reset flow
- Password change flow
- SOC analyst creation/management
- Security manager dashboard (API)
- Report generation API
- Trust/block list management
- Notification channel configuration

### 6.2 Orphan Code (implemented but not documented)
- `app/devices.py` - trusted devices (mentioned in UC-05 but minimal docs)

### 6.3 Orphan Database Tables
- None identified - all tables have ORM models

### 6.4 Missing Critical Features
1. **JWT Validation Middleware** - No authentication middleware validates access tokens
2. **Authorization Middleware** - No RBAC enforcement on any endpoint
3. **Outbox Poller** - Table exists, no worker
4. **Reconnaissance Worker** - `rescore_failed_attempts()` exists but never called
5. **ML Model** - Registry exists, no actual model file

## 7. Security Controls

| Control | Implemented | Tested | Documented | Status |
|---------|-------------|--------|------------|--------|
| INTERNAL_SECRET verification | Yes | test_internal_actions.py | PARTIAL | COVERED |
| Rate limiting | Partial | - | PARTIAL | PARTIAL |
| MFA code hashing | Yes | - | PARTIAL | PARTIAL |
| Password hashing (Argon2) | Yes | - | PARTIAL | PARTIAL |
| Session revocation | Yes | test_internal_actions.py | PARTIAL | COVERED |
| Token hashing | Yes | - | PARTIAL | PARTIAL |
| IP hashing | Yes | - | PARTIAL | PARTIAL |
| MFA IP binding | Implemented (not verified) | - | PARTIAL | PARTIAL |

## 8. Workflow to Implementation Trace

| Workflow | UML | Implementation | Status |
|----------|-----|----------------|--------|
| WF-1 Login | WF-1_Login.uml | auth.py | PARTIAL |
| WF-2 Detection | WF-2_Detection.uml | detection.py | PARTIAL |
| WF-3 SOC | WF-3_SOC.uml | alerts.py | PARTIAL |
| WF-4 MFA | WF-4_MFA.uml | auth.py | PARTIAL |
| WF-5 Sessions | WF-5_Sessions.uml | auth.py | PARTIAL |
| WF-6 ML | WF-6_ML.uml | ml.py | PARTIAL |

## 9. Test Coverage by Feature

| Feature | Tests | Coverage |
|---------|-------|----------|
| Detection scoring formula | 50+ tests | HIGH |
| Risk gate | 15 tests | HIGH |
| Protective actions | 10 tests | HIGH |
| Internal endpoints | 20 tests | HIGH |
| Auth endpoints | 6 tests (all empty) | NONE |
| ML scoring | 10 tests | MEDIUM |
| Schema consistency | 50+ tests | HIGH |
