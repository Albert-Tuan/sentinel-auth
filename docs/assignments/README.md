# Sentinel Auth v3.3 — Team Ownership & Handoff

**Repository:** Albert-Tuan/sentinel-auth
**Branch:** dev
**Status:** TEAM_IMPLEMENTATION_HANDOFF_READY

---

## IMPORTANT PRINCIPLE

> **"Actor ownership does not override service boundary."**
>
> A business role (e.g., Security Manager) may span multiple services.
> A team member's responsibility is bounded by their service ownership.
> Do not implement a feature in another service's codebase without a contract.

---

## WARNING — LEGACY REFERENCE

> **TASK_ASSIGNMENT.md contains historical planning and stale terminology.**
> Do NOT use it as architecture authority.
> It may reference JWT, old role ownership, or superseded design decisions.
> Always refer to the canonical docs listed in Section 2.

---

## 1. Architecture Summary

### Current Prototype
- Single FastAPI application
- One PostgreSQL server (3 logical databases)
- Redis verified healthy (AOF, appendfsync everysec)
- Outbox publisher: **NOT IMPLEMENTED**
- Redis Streams consumer: **NOT IMPLEMENTED**

### Target v3.3 Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      User Browser                            │
└──────────────┬──────────────────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────────────┐
│                  Core / Auth (port 8000)                     │
│  Sony owns                                                   │
│  ───────────────────                                        │
│  users · sessions · auth · MFA · trusted devices · RBAC     │
│  protective-action executor · pre-token Detection client     │
│  Detection ← Core: POST /api/v1/internal/login-events                │
│  Core ← Detection: POST /api/v1/internal/actions                   │
└──────────────┬──────────────────────────┬──────────────────┘
               │                          │
               │ direct HTTP               │ direct HTTP
               ▼                          ▼
┌─────────────────────────────────────────────────────────────┐
│            Detection Engine (port 8001)                      │
│  Tuấn Anh owns                                             │
│  ───────────────────                                        │
│  login events · feature builder · rule engine · ML client    │
│  risk fusion · alert lifecycle · SOC workflow               │
│  Detection policy/rule administration                       │
│  Core ← Detection: POST /api/v1/internal/pre-token-check           │
└──────────────┬──────────────────────────┬──────────────────┘
               │                          │
               │ HTTP POST /ml/score      │
               ▼                          │
┌─────────────────────────────────────────────────────────────┐
│              ML Service (port 8002)                         │
│  Khang owns                                                │
│  ───────────────────                                        │
│  feature validation · Isolation Forest · score normalization  │
│  reason codes · model registry · inference logs              │
│  Security Manager analytics / reporting                      │
└─────────────────────────────────────────────────────────────┘
```

### Database Topology

```
ONE PostgreSQL server (verified healthy)

├── sentinel_core      (Sony)
│   └── 13 base tables: users, roles, user_roles, sessions,
│       mfa_transactions, mfa_notifications, audit_logs,
│       user_trusted_devices, system_settings, outbox_events,
│       user_notifications, rate_limits, ip_addresses
│
├── sentinel_detection (Tuấn Anh)
│   └── 7 base tables: policies, login_attempts, risk_assessments,
│       detection_logs, soc_analysts, alerts, alert_timeline
│
└── sentinel_ml       (Khang)
    └── 3 base tables + 1 real view: model_versions,
        inference_logs, feature_statistics + local_ml_stats
```

### Redis
- Role: future asynchronous event transport using Redis Streams
- Status: verified healthy (PONG, AOF enabled, appendfsync everysec)
- **NOT YET USED** for event transport

### Authentication
- Opaque access token: `secrets.token_urlsafe(32)` → SHA-256 hash in DB
- Opaque refresh token: `secrets.token_urlsafe(32)` → SHA-256 hash in DB
- **NOT JWT**

---

## 2. Team Ownership Summary

| Member | Branch | Primary Service | Main Business Role | Database |
|--------|--------|-----------------|--------------------|----------|
| Sony | `core-app` | Core / Auth / IAM | USER + IAM-side Security Admin | `sentinel_core` |
| Tuấn Anh | `detection-engine` | Detection / SOC | SOC Analyst + Detection-side Security Admin | `sentinel_detection` |
| Khang | `ml-service` | ML / Analytics | ML Service + Security Manager analytics | `sentinel_ml` |

---

## 3. Branch Workflow

### Before Starting Any Work

```bash
git fetch origin
git checkout dev
git pull origin dev
# Create or update your feature branch
git checkout -b core-app      # Sony
git checkout -b detection-engine  # Tuấn Anh
git checkout -b ml-service     # Khang
```

### Implementation Flow

```
feature branch
  → implement
  → write tests
  → run: pytest -q
  → push to origin
  → open PR into dev
  → lead reviews
  → merge
  → integration test
```

### Rules
- **DO NOT force push** to any shared branch
- **DO NOT merge directly to `main`**
- **DO NOT begin implementation from a stale branch** — always `git fetch && git pull` first
- Feature branches should incorporate the latest approved `dev` baseline before starting work

---

## 4. Service Boundary Rules

### Cross-Service Database Access — PROHIBITED

> **No member may solve an integration problem by directly querying another service's PostgreSQL database.**

| Forbidden | Reason |
|-----------|--------|
| Khang queries `sentinel_detection` tables directly | Must use Detection HTTP API |
| Tuấn Anh writes directly to `sentinel_core.sessions` | Must use Core `/internal/actions` endpoint |
| Sony reads `sentinel_detection` tables for risk decisions | Detection is responsible for risk |

**Exception:** Prototype/local reporting behavior must be explicitly approved by the lead.

### Service Ownership

| Service | Owner | May Modify |
|---------|-------|-----------|
| `app/auth.py`, `app/sessions`, `app/models.py` | Sony | Sony + Lead (shared infrastructure) |
| `app/detection.py`, `app/alerts.py` | Tuấn Anh | Tuấn Anh + Lead |
| `app/ml.py` | Khang | Khang + Lead |
| `app/main.py` (entrypoint changes) | Lead | Lead only |
| `app/client_ip.py`, `app/devices.py` | Sony | Sony |
| `app/internal_actions.py` | Sony | Sony (enforcement) + Tuấn Anh (consumption) |

---

## 5. Business Role Mapping

| Business Role | Primary Service | Primary Owner | Notes |
|---------------|-----------------|--------------|-------|
| USER | Core/Auth | Sony | Normal system usage |
| SOC_ANALYST | Detection/SOC | Tuấn Anh | Alert handling, protective action |
| SECURITY_ADMIN (IAM) | Core/Auth | Sony | Users, accounts, roles, RBAC |
| SECURITY_ADMIN (Detection) | Detection | Tuấn Anh | Policies, rules, policy activation |
| SECURITY_MANAGER | ML/Analytics | Khang | Reporting, analytics, oversight |

### Security Manager Boundary

Security Manager data may come from **all three services** (Core, Detection, ML).
Khang owns **implementation** of Manager-facing analytics, but is NOT the architecturally designated owner of the Manager role.
Manager does NOT: operate SOC, own policies, or approve protective actions.

---

## 6. Shared Contract Ownership

| Contract | Owners | Reviewer |
|----------|--------|----------|
| Core ↔ Detection | Sony + Tuấn Anh | Lead |
| Detection ↔ ML | Tuấn Anh + Khang | Lead |

Both owners must approve any change to shared request/response schemas, feature names/types/ranges, reason-code semantics, and model_status semantics.

---

## 7. Security Admin Split

SECURITY_ADMIN is split by bounded context:

| Function | Owner |
|----------|-------|
| IAM: users, accounts, roles, user-role assignment | Sony |
| Detection: policies, rules, policy activation | Tuấn Anh |

Neither member should access the other's database directly to implement administrative functions.
Cross-boundary functionality must use an API/service contract.

---

## 8. Document Hierarchy (Source of Truth)

**Highest authority first:**

1. `docs/DECISIONS-SYSTEM-v3.3.md`
2. `docs/DECISIONS-DETECTION-v3.3.md`
3. `docs/01-*.md` through `docs/06-*.md`
4. `docs/audit/17-requirements-usecase-reconciliation.md`
5. `docs/audit/18-uml-workflow-reconciliation.md`
6. `docs/audit/19-report-content-reconciliation.md`
7. `docs/INFRASTRUCTURE-v3.3.md`
8. `docs/audit/16-infra-baseline-verification.md`
9. `infra/postgres/schema-*.sql`
10. `app/**` (current implementation)
11. `tests/**`

---

## 9. Definition of Done

A personal task is **NOT DONE** merely because unit tests pass. Done requires:

- [ ] Owned acceptance criteria pass
- [ ] Owned tests pass (`pytest -q`)
- [ ] Shared contract tests pass (where applicable)
- [ ] No canonical decision violated
- [ ] No unauthorized cross-database access
- [ ] Documentation updated if public contract changes
- [ ] Branch cleanly merges into `dev`
- [ ] Integration does not break other service tests

---

## 10. Stop / Ask Lead Conditions

**STOP and ask the lead before:**

- Changing canonical role permissions
- Changing risk formula (0.4 rule / 0.6 ML weights)
- Changing risk thresholds (low < 0.25, medium < 0.50, high < 0.75, critical >= 0.75)
- Adding/removing ML features (the 6 canonical features are fixed)
- Changing shared request/response schemas
- Adding/removing cross-database foreign keys
- Directly accessing another service's database
- Changing opaque-token architecture or switching to JWT
- Changing session expiry semantics (1-hour fixed)
- Introducing new persistent entities
- Changing Redis/outbox architecture
- Changing service boundary
- Changing `app/main.py` shared infrastructure
- Deleting existing working behavior
- Any decision not covered by your bounded context

---

## 11. Files in This Directory

| File | Purpose |
|------|---------|
| `README.md` | This file — team ownership overview |
| `SONY_CORE_IAM_USER.md` | Sony's full assignment |
| `TUANANH_DETECTION_SOC_ADMIN.md` | Tuấn Anh's full assignment |
| `KHANG_ML_MANAGER_ANALYTICS.md` | Khang's full assignment |
| `CONTRACT_CORE_DETECTION.md` | Core ↔ Detection contract |
| `CONTRACT_DETECTION_ML.md` | Detection ↔ ML contract |

---

## 12. Quick Reference — Who Owns What

| What | Owner |
|------|-------|
| Users, sessions, auth, MFA | Sony |
| Detection rules, alerts, SOC workflow | Tuấn Anh |
| ML inference, model registry, analytics | Khang |
| Pre-token risk check (Detection side) | Tuấn Anh |
| Pre-token risk check (Core client) | Sony |
| Protective action enforcement | Sony |
| Protective action orchestration | Tuấn Anh |
| ML client + timeout + fallback | Tuấn Anh |
| ML endpoint + inference | Khang |
| Core ↔ Detection contract | Sony + Tuấn Anh |
| Detection ↔ ML contract | Tuấn Anh + Khang |
| IAM Security Admin | Sony |
| Detection Security Admin | Tuấn Anh |
| Manager analytics/reporting | Khang (implementation) |
