# Sentinel Auth - System Model

## 1. Architecture Model

### 1.1 Current Runtime Model

**Finding: PROTOTYPE CONSOLIDATION (Architecture Decision Pending)**

The documented architecture describes three independently deployed services:

| Service | Port | Database |
|---------|------|----------|
| Core App | :8000 | core-db |
| Detection Engine | :8001 | detection-db |
| ML Service | :8002 | ml-service-db |

**Actual Implementation:** Single FastAPI application (`app/main.py`) with all routers mounted into one instance:

```python
app.include_router(auth_router)          # /api/v1/auth/*
app.include_router(detection_router)       # /api/v1/internal/*
app.include_router(policy_router)          # /api/v1/policies/*
app.include_router(internal_actions_router) # /api/v1/internal/*
app.include_router(ml_router)             # /api/v1/internal/ml/*
app.include_router(alerts_router)         # /api/v1/alerts/*
app.include_router(devices_router)         # /api/v1/devices/*
```

**Implication:** All logical services share the same FastAPI process, same database connection, and same ORM session. The three-database architecture exists only in documentation, not in runtime.

### 1.2 Single Database Configuration

The application uses a single `DATABASE_URL` environment variable:

```python
database_url = os.getenv("DATABASE_URL", "postgresql://sentinel:sentinel@postgres:5432/sentinel")
```

**Finding:** All tables (core, detection, ML) are expected to coexist in one database or share a connection string. There is no mechanism to select different databases for different services.

### 1.3 Trust Boundaries (Current Implementation)

The "three-service" architecture is enforced through:
1. **Naming conventions** (prefixes like `/internal/`)
2. **Shared secret** (`X-Internal-Secret`)
3. **Code organization** (separate modules)

There is no runtime enforcement of service boundaries.

## 2. Human Actors

### 2.1 Actor Definitions

| Actor | Role ID | Description | Privileged Operations |
|-------|---------|-------------|----------------------|
| **User** | USER | Standard end-user | Login, logout, MFA, manage own sessions, manage own devices |
| **SOC Analyst** | SOC_ANALYST | Security Operations Center analyst | View alerts, acknowledge, investigate, request actions |
| **Security Administrator** | SECURITY_ADMIN | System security administrator | Manage users, roles, MFA policies, rules, audit logs |
| **Security Manager** | SECURITY_MANAGER | Security department manager | View dashboards, generate reports |

### 2.2 Authorization Status

**Finding: AUTHORIZATION NOT ENFORCED**

Current implementation lacks JWT validation and role-based access control:

- All endpoints that claim to require SOC_ANALYST or SECURITY_ADMIN roles accept requests without verification
- `x_internal_token` header is used but only validates against a hardcoded secret
- No user context is extracted from tokens
- Authorization is currently a placeholder for future implementation

### 2.3 Actor Responsibilities

| Actor | Business Responsibility | Data Visibility | Audit Requirements |
|-------|------------------------|-----------------|-------------------|
| User | Use the system securely | Own profile, sessions, devices | Login history |
| SOC Analyst | Investigate alerts, protect users | All alerts, login attempts, risk data | Full audit trail |
| Security Admin | Maintain system security | Users, roles, policies, audit logs | Full audit trail |
| Security Manager | Security oversight | Aggregated stats, reports | Limited detail |

## 3. Services / Components

### 3.1 Core App (Logical)

**Responsibility:** Authentication, session management, MFA, user management

**Owned Data:**
- `users`, `sessions`, `mfa_transactions`, `mfa_notifications`
- `rate_limits`, `ip_addresses`, `audit_logs`
- `user_roles`, `user_trusted_devices`, `user_notifications`
- `outbox_events`

**Interfaces:**
- `POST /api/v1/auth/register`
- `POST /api/v1/auth/login`
- `POST /api/v1/auth/mfa/verify`
- `POST /api/v1/auth/refresh`
- `POST /api/v1/auth/logout`
- `GET /api/v1/auth/sessions`
- `DELETE /api/v1/auth/sessions/{id}`
- `POST /api/v1/internal/actions` (callback from Detection)
- `GET /api/v1/internal/users/{id}` (user lookup)

**Trust Boundary:** External clients (browsers, mobile apps)

**Sync Calls:** Detection Engine (pre-token-check), email/SMS (placeholder)

**Async Calls:** Detection Engine (login events via outbox - NOT IMPLEMENTED)

### 3.2 Detection Engine (Logical)

**Responsibility:** Risk scoring, rule evaluation, alert creation

**Owned Data:**
- `policies`, `login_attempts`, `risk_assessments`
- `detection_logs`, `alerts`, `alert_timeline`
- `soc_analysts`

**Interfaces:**
- `POST /api/v1/internal/login-events` (from Core)
- `POST /api/v1/internal/pre-token-check` (from Core)
- `GET /api/v1/internal/login-attempts/{id}`
- `GET /api/v1/policies`
- `POST /api/v1/policies/{id}/activate`
- `GET /api/v1/alerts` (logical SOC endpoint)
- `GET /api/v1/alerts/{id}`
- `GET /api/v1/alerts/{id}/evidence`
- `POST /api/v1/alerts/{id}/acknowledge`
- `POST /api/v1/alerts/{id}/resolve`
- `POST /api/v1/alerts/{id}/assign`
- `POST /api/v1/alerts/{id}/actions`

**Trust Boundary:** Internal only (Core App)

**Sync Calls:** ML Service (scoring)

**Async Calls:** Core App (actions callback)

### 3.3 ML Service (Logical)

**Responsibility:** Anomaly scoring using heuristic baseline

**Owned Data:**
- `model_versions`, `inference_logs`, `feature_statistics`

**Interfaces:**
- `POST /api/v1/internal/ml/score`
- `GET /api/v1/internal/ml/health`
- `GET /api/v1/internal/ml/features`

**Trust Boundary:** Internal only (Detection Engine)

**Note:** Currently uses heuristic model, not trained ML. Model registry exists but no actual model files are referenced.

## 4. Deployment Model Discrepancy

| Aspect | Documented | Actual | Status |
|--------|------------|--------|--------|
| Core App | Separate :8000 | Single FastAPI :8000 | MISMATCH |
| Detection Engine | Separate :8001 | Same FastAPI :8001 | MISMATCH |
| ML Service | Separate :8002 | Same FastAPI :8002 | MISMATCH |
| Core DB | Separate database | Same DATABASE_URL | MISMATCH |
| Detection DB | Separate database | Same DATABASE_URL | MISMATCH |
| ML DB | Separate database | Same DATABASE_URL | MISMATCH |

**This is NOT necessarily a bug.** Prototype consolidation is a valid approach. However:
1. The three-service architecture must be explicitly documented as future state
2. The current implementation should clearly label this as "logical services in single process"
3. Database table ownership should be clarified when splitting

## 5. Concurrency / Race Conditions

### 5.1 Known Concurrency Scenarios

| Scenario | Protection | Status |
|----------|------------|--------|
| Concurrent registration same username | DB UNIQUE constraint | COVERED |
| Concurrent rate limit update | No explicit lock | **POTENTIAL RACE** |
| Concurrent MFA verification | No explicit lock | **POTENTIAL RACE** |
| Concurrent refresh token use | No family tracking | **MISSING** |
| Concurrent session revocation | No explicit lock | **POTENTIAL RACE** |
| Two Detection workers process same event | Idempotency by event_id | COVERED |
| Two Outbox workers claim same event | No worker exists | **NOT IMPLEMENTED** |
| Two SOC analysts update same alert | No optimistic locking | **POTENTIAL RACE** |
| Concurrent policy activation | DB single-active constraint | COVERED |

## 6. Data Flow Summary

```
Client → Core App → [Credentials Valid?]
                      ↓
               [Pre-token Check?] (if enabled)
                      ↓
               Detection Engine → ML Service
                      ↓
               [Risk Level Returned]
                      ↓
               [HIGH/CRITICAL → MFA Required]
               [LOW/MEDIUM → Session Created]
                      ↓
               [Login Event Sent to Detection]
                      ↓
               Detection → [Score] → [Alert Created?]
                      ↓
               Detection → Core [Action: REVOKE_SESSIONS/REQUIRE_MFA]
                      ↓
               Core → [Sessions Revoked / MFA Required Flag Set]
```

## 7. Open Questions

1. **Q-01:** Is the single-process prototype intended to eventually split into three services?
2. **Q-02:** Will each service eventually have its own database, or will they share?
3. **Q-03:** Is there a timeline or architecture document for the service split?
4. **Q-04:** How should JWT validation be implemented when splitting?
5. **Q-05:** Will there be a service mesh or shared secret for inter-service auth?
