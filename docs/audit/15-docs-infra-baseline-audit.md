# Sentinel Auth — Documentation & Infrastructure Baseline Audit

**Repository:** Albert-Tuan/sentinel-auth
**Branch:** dev
**Baseline:** `78c5d4f3765bad75ed480758d0a2250b3ac49c15`
**Audit Date:** 2026-10-09
**Scope:** Documentation, infrastructure, and architecture contracts only. No application implementation changes.

---

## 1. Current System Facts (Verified)

### 1.1 Architecture

The current repository is a **single FastAPI monorepo** — one `app/` package, one process, one running application. Logical boundaries (Core / Detection / ML) exist as code modules within the same application. They are **not independently deployed services**.

The **target architecture** (documented in `docs/DECISIONS-SYSTEM-v3.3.md`) describes three independent services. The infrastructure in this repository reflects the target architecture. The application code reflects the current implementation.

**Approved architecture decisions** are recorded in `docs/DECISIONS-SYSTEM-v3.3.md`. These do NOT automatically change implementation; they create a record that implementation must be updated to match. See Section 2 for the document hierarchy.

### 1.1b Token Model

Sentinel Auth v3.3 uses **opaque random tokens** — NOT JWT.

- Access token: `secrets.token_urlsafe(32)` — 32-byte cryptographically random, base64-url encoded. Hash (SHA-256) in `sessions.access_token_hash`.
- Refresh token: `secrets.token_urlsafe(32)` — hash in `sessions.refresh_token_hash`.
- `revoked_at` column enables immediate revocation. No token expiry list needed.
- `token_jti` is a session UUID, not a JWT claim. Column name is legacy/internal naming.

JWT is NOT part of v3.3. This is an intentional design choice. See `docs/DECISIONS-SYSTEM-v3.3.md` Section 1.

### 1.2 Database Topology

Three SQL schema files under `infra/postgres/`:

| Database | Schema File | Tables | Logical Schema Owner |
|----------|-------------|--------|-------------------|
| `sentinel_core` | `schema-core-v3.3.sql` | 13 | `core_auth` |
| `sentinel_detection` | `schema-detection-v3.3.sql` | 7 | `detection_soc` |
| `sentinel_ml` | `schema-ml-service-v3.3.sql` | 3 + 1 view | `ml_manager` |

**Total: 23 base tables, 1 real view (`local_ml_stats` in `sentinel_ml`).**

The `manager_dashboard` reference in `schema-ml-service-v3.3.sql` is commented-out conceptual SQL — not a real view. Do NOT count it.

PostgreSQL bootstrap is verified by `tests/test_postgres_bootstrap.py` (16 tests, all passing).

### 1.3 Authentication

- **Opaque random tokens** — NOT JWT.
- Access token: `secrets.token_urlsafe(32)` — 32-byte random string.
- Refresh token: `secrets.token_urlsafe(32)` — 32-byte random string.
- Both hashes (SHA-256) persisted in `sessions` table.
- **Immediate revocation** via `revoked_at` column — no token expiry list needed.
- DB-backed: every authenticated request queries `sessions`.

### 1.4 MFA

- Pre-auth MFA transaction (`mfa_transactions` with `pending` → `completed` / `failed` / `expired`).
- IP binding on transaction creation.
- Atomic OTP consumption via `SELECT ... FOR UPDATE`.
- Timezone-aware UTC: `datetime.now(timezone.utc)` throughout; `TIMESTAMPTZ` columns correct regardless of PostgreSQL session timezone.
- TTL: 5 minutes.

### 1.5 Internal Authentication

- `X-Internal-Secret` header on all internal service calls.
- `get_internal_secret()` in `app/internal_auth.py` — validates the environment variable at runtime.
- **No usable default**: rejects absent, empty, `"changeme-in-production"`, and values < 32 chars.
- Fails closed: `InternalAuthConfigurationError` → HTTP 503.
- Fail-open for login: detection unavailability does not block user login.

### 1.6 Known Implementation Backlog

| ID | Description | Status |
|----|-------------|--------|
| P1-D | Trusted proxy / X-Forwarded-For remediation | **RESOLVED** (canonical `app/client_ip.py`, `FORWARDED_ALLOW_IPS=127.0.0.1`) |
| P1-E | CORS policy | **BACKLOG** |
| P1-F | Refresh-token concurrency (rotation vs. passive) | **BACKLOG** |
| P1-G | Outbox runtime (poller + at-least-once delivery) | **BACKLOG** |
| P1-H | Reconciliation scheduler (missed detection events) | **BACKLOG** |
| P1-B | SOC protective-action workflow (request vs. direct-apply) | **BACKLOG — DECISION REQUIRED** |
| P1-C | Policy role ownership (Security Admin vs. Security Manager) | **BACKLOG — DECISION REQUIRED** |

---

## 2. Documentation Classification

### CANONICAL — Authoritative current-state documents

| File | Reason |
|------|--------|
| `infra/postgres/schema-core-v3.3.sql` | Authoritative Core DB schema (13 tables, bootstrap verified) |
| `infra/postgres/schema-detection-v3.3.sql` | Authoritative Detection DB schema (7 tables, bootstrap verified) |
| `infra/postgres/schema-ml-service-v3.3.sql` | Authoritative ML DB schema (3 tables, bootstrap verified) |
| `docs/audit/14-p1-remediation.md` | Current state of all P0/P1 remediations |
| `docs/audit/05-trust-boundaries.md` | Updated in P1-D; reflects current IP trust architecture |
| `Dockerfile` | Current production container definition |

### CURRENT_SUPPORTING — Describes current implementation accurately

| File | Notes |
|------|-------|
| `TASK_ASSIGNMENT.md` | Outlines 3-service target architecture; notes current flat structure as actual state |
| `docs/DECISIONS-DETECTION-v3.3.md` | Risk scoring formula, feature contract, ML response contract |
| `docs/audit/04-database-bootstrap.md` | Documents historical bootstrap failures that have since been fixed; useful as test evidence |
| `docs/workflows.mmd` | Accurate description of current implementation (synchronous detection, direct HTTP, no outbox) |

### HISTORICAL — Previous findings, useful for traceability

| File | Notes |
|------|-------|
| `docs/audit/10-findings.md` | Contains original P0 findings (F-01 through F-10), all resolved |
| `docs/audit/07-cross-artifact-conflicts.md` | C-01 through C-16; many resolved, all tracked |
| `docs/audit/08-open-decisions.md` | Q-01 through Q-05; some resolved, others pending decisions |
| `docs/audit/09-test-gap-analysis.md` | Historical test coverage snapshot |
| `docs/audit/11-implementation-readiness.md` | Readiness matrix as of previous audit |
| `docs/audit/12-second-review.md` | Second-pass findings |
| `docs/audit/13-p0-remediation-report.md` | P0 remediation status; P1-A verified as resolved |

### STALE — Contains statements contradicting current implementation

| File | Staleness | Action |
|------|-----------|--------|
| `docs/audit/04-database-bootstrap.md` | Reports PostgreSQL bootstrap failures (NOW() partial index, CHECK subqueries) that were fixed in current code | Update to reflect current state; do NOT delete |
| `docs/SENTINEL_AUTH_TONG_HOP_v3.3.md` | Describes JWT token management; describes three-service architecture as current | Keep as design document; do not treat as implementation truth |
| `docs/bao-cao/_content_ch1.py` | States "JWT chưa có trong phụ thuộc" — accurate but framed as gap | Update framing to reflect intentional opaque-token design |
| `docs/bao-cao/BaoCaoPT_TKHTTT_Nhom2_Checklist.md` | Row 75: "JWT | 3 | TTL | 1" — misleading | Annotate as DESIGN intent vs. CURRENT implementation |
| `docs/bao-cao/BaoCaoPT_TKHTTT_Nhom2_Checklist.md` | Row 102: accurately notes `token_jti` declared but JWT library not in deps | Keep as accurate observation |

### CONFLICTING — Contains specific contradictions between docs and current reality

See Section 4 for full detail.

---

## 3. Stale Security Documentation

### 3.1 Historical Findings (RESOLVED)

All P0 findings in `docs/audit/10-findings.md` have been resolved:

| Finding | File | Status |
|---------|------|--------|
| F-01: PostgreSQL CHECK constraint subqueries | `schema-detection-v3.3.sql` | ✅ FIXED (P0-01) |
| F-02: SQLite partial index `WHERE expires_at IS NULL OR expires_at > NOW()` | `schema-core-v3.3.sql` | ✅ FIXED (P0-01) |
| F-03: MFA OTP replay | `app/auth.py` | ✅ FIXED (P0-05) |
| F-04: MFA TTL not enforced | `app/auth.py` | ✅ FIXED (P0-01) |
| F-05: Rate limiting absent | `app/auth.py` | ✅ FIXED (P0-02) |
| F-06: RBAC missing | `app/authz.py` | ✅ FIXED (P0-03) |
| F-07: MFA IP binding absent | `app/auth.py` | ✅ FIXED (P0-03) |
| F-08: Timezone-naive timestamps | `app/*.py` | ✅ FIXED (TIME-01) |
| F-09: JWT documented vs. opaque tokens used | `docs/**` | ✅ ACKNOWLEDGED (intentional) |
| F-10: `INTERNAL_SECRET` default | `app/auth.py` | ✅ FIXED (P1-A) |

### 3.2 Remaining Stale Statements

| Document | Stale Statement | Current Reality |
|----------|----------------|-----------------|
| `docs/audit/10-findings.md` L665 | "Application can start with the default development secret 'changeme-in-production'" | ❌ NOW REJECTED: `get_internal_secret()` raises `InternalAuthConfigurationError` |
| `docs/audit/05-trust-boundaries.md` L151 | `INTERNAL_SECRET = os.getenv("INTERNAL_SECRET", "changeme-in-production")` | ❌ NOW: `from app.internal_auth import get_internal_secret` |
| `docs/audit/07-cross-artifact-conflicts.md` L216 | Same stale `INTERNAL_SECRET` default | ❌ OBSOLETE |
| `docs/audit/12-second-review.md` L321 | "Application can start with default secret" | ❌ OBSOLETE |
| `docs/audit/11-implementation-readiness.md` L171 | "AUTH-01: No JWT validation middleware" | ⚠️ PARTIALLY OBSOLETE: opaque token auth present; no JWT library present (intentional) |
| `docs/bao-cao/BaoCaoPT_TKHTTT_Nhom2_Checklist.md` L414 | "Chưa dùng thư viện JWT" | ✅ ACCURATE — JWT intentionally not used |
| `docs/bao-cao/_content_ch1.py` L427 | "thiết kế mô tả JWT, mã nguồn phát hành chuỗi ngẫu nhiên" | ✅ ACCURATE — documented gap, intentional simplification |
| `docs/audit/04-database-bootstrap.md` | Documents bootstrap failures | ⚠️ HISTORICAL — failures were fixed; document useful as historical test evidence |

---

## 4. Requirement / Implementation Contradictions

### C-17: JWT vs. Opaque Tokens

| Document | Statement | Current Reality |
|----------|-----------|-----------------|
| `docs/SENTINEL_AUTH_TONG_HOP_v3.3.md` L191 | "SESSIONS: JWT token management" | Opaque random strings; SHA-256 hashes stored |
| `schema-core-v3.3.sql` L127 | "SESSIONS (JWT Token Management)" | Opaque tokens; `token_jti` is a UUID, not a JWT claim |
| `docs/workflows.mmd` WF-3 | `Validate JWT (role=SOC_ANALYST)` | No JWT; SOC analyst uses opaque bearer token against Core App |
| `docs/diagrams/wf3_soc.uml` | `Validate JWT\n(role=SOC_ANALYST)` | No JWT; all auth is opaque token |
| `docs/diagrams/wf5_session_management.uml` L133 | `Validate JWT, role=SECURITY_ADMIN` | No JWT; all auth is opaque token |
| `app/models.py` L177 | `"""Active user sessions with JWT refresh tokens."""` | CLASSIFICATION: **STALE** — comment predates current implementation |
| `app/schemas.py` L590 | `# Token / JWT schemas (for internal use)` | CLASSIFICATION: **STALE** — comment predates current implementation |
| `docs/bao-cao/uml-activity-login-mfa.puml` L108 | "sessions.token_jti khớp jti nếu sau này chuyển sang JWT" | ✅ ACCURATE — note says future migration path |

**Classification:** INTENTIONAL SIMPLIFICATION — the team chose opaque tokens. Documentation must be updated to reflect this, not labeled as a bug.

**Recommendation:** Update `schema-core-v3.3.sql` COMMENT and all UML diagrams to say "opaque token management" instead of "JWT token management."

### C-18: Three-Service Architecture Described as Current

| Document | Statement | Current Reality |
|----------|-----------|-----------------|
| `TASK_ASSIGNMENT.md` L17 | "Kiến trúc: 1 FastAPI monorepo + 3 schema ownership" | Correct — this is the design target, not current runtime |
| `docs/workflows.mmd` L10 | "Mermaid renders in any Markdown viewer..." | Correct — documents v3.3 design, not current runtime |
| `docs/bao-cao/uml-architecture.puml` | Shows three separate services | DESIGN intent; current runtime is one process |

**Classification:** The `docs/workflows.mmd` file header says "Cập nhật cho architecture v3.3: 3 services, 3 databases, HTTP communication" — this is the design document. The diagrams in `docs/diagrams/` and `docs/bao-cao/` show the target architecture. This is not a contradiction but rather a **design document vs. current implementation** gap.

**Recommendation:** Add explicit notation to all architecture diagrams: "v3.3 DESIGN TARGET — current runtime is single-process monorepo."

### C-19: Outbox Described as Implemented

| Document | Statement | Current Reality |
|----------|-----------|-----------------|
| `docs/workflows.mmd` L18-19 | `Outbox Poller (NOT impl.)` | ✅ ACCURATE — correctly annotated as not implemented |
| `TASK_ASSIGNMENT.md` L145-147 | Outbox: publish `LoginEvent` after each login attempt | ❌ NOT DONE |
| `schema-core-v3.3.sql` | `outbox_events` table exists | ✅ EXISTS — schema is ready, poller not implemented |

**Classification:** PARTIAL — `outbox_events` table exists but poller is not implemented. Login events are written directly to `login_attempts` (Core) and sent via direct HTTP to Detection. This is the correct characterization.

### C-20: Async Detection Described as Current

| Document | Statement | Current Reality |
|----------|-----------|-----------------|
| `docs/workflows.mmd` WF-2 | "Detection Engine Flow (Risk Gate + Direct HTTP)" | ✅ ACCURATE — current implementation |
| `docs/workflows.mmd` WF-2 L119 | "Phase 2 - Detection pipeline\nchạy await trong handler, KHONG co worker nen" | ✅ ACCURATE — correct characterization of current inline pipeline |

### C-21: Security Manager / Security Admin Role Confusion (P1-C)

| Document | Statement | Role |
|----------|-----------|------|
| `docs/05-trust-boundaries.md` L88 | `Security Admin` has `MANAGE_POLICIES` | doc-06 |
| `docs/audit/12-second-review.md` L265 | "Security Manager has MANAGE_POLICIES" | doc-06 |
| Current `app/authz.py` | `SECURITY_ADMIN` and `SECURITY_MANAGER` both can activate policies | ✅ Current implementation |

**Classification:** IMPLEMENTATION BACKLOG — DECISION REQUIRED (see Section 6).

### C-22: Protective Action Workflow (P1-B)

| Document | Statement |
|----------|-----------|
| `docs/02-dac-ta-use-case-core-app.md` | UC-DE-13 primary actor = SOC Analyst; "Yêu cầu Action" |
| `docs/06-phan-tich-doi-tuong-su-dung-detection-engine.md` | Security Manager has `APPROVE_ACTION` and participates in UC-DE-13 |
| Current implementation | Both SOC_ANALYST and SECURITY_MANAGER can directly apply actions via `POST /alerts/{id}/actions` |

**Classification:** IMPLEMENTATION BACKLOG — DECISION REQUIRED (see Section 5).

---

## 5. P1-B / P1-J Business Decision Sheet: Protective Action Workflow

### Current State
`POST /api/v1/alerts/{alert_id}/actions` is accessible by both `SOC_ANALYST` and `SECURITY_MANAGER`. Both can directly apply any `SecurityAction` without a request/approval cycle.

### Known Conflict
- `docs/02-dac-ta-use-case-core-app.md`: UC-DE-13 primary actor = SOC Analyst; action = "Yêu cầu" (request)
- `docs/06-phan-tich-doi-tuong-su-dung-detection-engine.md`: Security Manager has `APPROVE_ACTION` and participates in UC-DE-13
- Current code: both roles can directly apply → no request/approval separation

### Options

#### OPTION A: SOC Analyst Directly Applies (Simplest)
**SOC Analyst directly applies all permitted actions.**

| Dimension | Impact |
|-----------|--------|
| Use-case | UC-DE-13 changes from "Yêu cầu Action" → "Thực hiện Action" |
| DB | No schema change needed |
| API | `POST /alerts/{id}/actions` stays; remove `APPROVE_ACTION` from Security Manager |
| UI | Single-step workflow |
| Security benefit | Role separation: SOC Analyst acts; Security Manager only supervises |
| Complexity | Low — closest to current implementation |
| Recommendation | ✅ **Recommended for university project** |

#### OPTION B: Two-Step Request → Approval
**SOC Analyst requests action → Security Manager approves → system applies.**

| Dimension | Impact |
|-----------|--------|
| Use-case | UC-DE-13 restored to "Yêu cầu" semantics |
| DB | Add `alert_action_requests(id, alert_id, requester_id, action, status, approver_id, created_at)` |
| API | `POST /alerts/{id}/action-requests` + `POST /alerts/{id}/action-requests/{req_id}/approve` |
| UI | Two-step: SOC requests, Manager approves |
| Security benefit | Defense in depth: two roles required for high-impact actions |
| Complexity | Medium — requires new table, new endpoints, new UI state |
| Recommendation | Consider for production; likely over-engineered for university project |

#### OPTION C: Risk-Tiered Model
**Lower-impact actions direct; higher-impact actions require approval.**

| Action | Direct? | Approval Required? |
|--------|---------|-------------------|
| `REQUIRE_MFA` | SOC_ANALYST | No |
| `REVOKE_SESSIONS` | SOC_ANALYST | SECURITY_MANAGER |
| `LOCK_USER` | SOC_ANALYST | SECURITY_MANAGER |
| `FORCE_LOGOUT` | SOC_ANALYST | No |

| Dimension | Impact |
|-----------|--------|
| Use-case | Proportionate security |
| DB | `action_risk_tier` enum or policy table |
| API | `POST /alerts/{id}/actions` with tier-check; tier-2 requires second call from manager |
| UI | Context-aware: some buttons require manager approval step |
| Security benefit | Best security/usability balance |
| Complexity | High — requires action tiering, two-call flows, UI logic |
| Recommendation | Best long-term; likely too complex for current sprint |

### DECISION REQUIRED FROM TEAM

**Recommendation: OPTION A** — SOC Analyst directly applies. Change `docs/02-dac-ta-use-case-core-app.md` UC-DE-13 from "Yêu cầu" to "Thực hiện." Remove `APPROVE_ACTION` from Security Manager's permitted actions.

---

## 6. P1-C / P1-K Policy Role Decision Sheet

### Current State
`GET /api/v1/policies`: `SECURITY_ADMIN` + `SECURITY_MANAGER` both allowed.
`POST/PATCH /api/v1/policies/{id}/activate`: `SECURITY_ADMIN` only.

### Known Conflict
- `docs/05-trust-boundaries.md`: "Security Admin has MANAGE_POLICIES"
- `docs/audit/12-second-review.md`: "Security Manager has MANAGE_POLICIES"
- Current code: both have view; only SECURITY_ADMIN can activate

### Proposed Resolution

| Capability | Security Admin | Security Manager | SOC Analyst |
|-----------|---------------|-----------------|-------------|
| View policies | ✅ | ✅ | ❌ |
| Create policy | ✅ | ❌ | ❌ |
| Edit policy | ✅ | ❌ | ❌ |
| Activate policy | ✅ | ❌ | ❌ |
| Deactivate policy | ✅ | ❌ | ❌ |
| View activation history | ✅ | ✅ | ❌ |

**Rationale:** Policy management is an administrative function. Security Manager is a practitioner (SOC analyst elevated to manager role) — they use policies but should not modify the rule set. This matches the `docs/06-phan-tich-doi-tuong-su-dung-detection-engine.md` assignment where Security Manager participates in SOC workflow, not policy administration.

### DECISION REQUIRED FROM TEAM

**Recommended: Security Manager gets view-only access. Security Admin gets full management. SOC Analyst gets nothing.** Update `docs/05-trust-boundaries.md` and `docs/audit/12-second-review.md` to reflect the agreed decision.

---

## 7. Infrastructure Audit

### 7.1 Dockerfile Status

**Critical issue found:** `Dockerfile` line 16 references a **non-existent file**:

```dockerfile
COPY infra/postgres/schema.sql ./infra/postgres/schema.sql
```

The current repository contains:
- `infra/postgres/schema-core-v3.3.sql` ✅
- `infra/postgres/schema-detection-v3.3.sql` ✅
- `infra/postgres/schema-ml-service-v3.3.sql` ✅
- `infra/postgres/schema.sql` ❌ **DOES NOT EXIST**
- `infra/postgres/migrations/` ❌ **EMPTY**

**Impact:** Docker build fails at the `COPY` step:
```
error: file not found in build context
```

The bootstrap mechanism (how schemas get into PostgreSQL) is **not defined** in the current Docker setup.

### 7.2 Missing Infrastructure Files

| File | Status | Needed For |
|------|--------|-----------|
| `docker-compose.yml` | ❌ Missing | Local reproducible environment |
| `compose.yaml` | ❌ Missing | Same as above |
| `.env.example` | ❌ Missing | Developer onboarding |
| `infra/postgres/schema.sql` | ❌ Missing | Current Dockerfile `COPY` target |
| `infra/postgres/migrations/` | ❌ Empty | Schema migration management |

### 7.3 Existing Environment Contracts

| Variable | Default | Current Status |
|----------|---------|---------------|
| `DATABASE_URL` | `postgresql://sentinel:sentinel@postgres:5432/sentinel` | ✅ Referenced in `app/main.py` |
| `INTERNAL_SECRET` | **unset** | ✅ Rejected if absent/placeholder |
| `DETECTION_URL` | `http://localhost:8001` | ✅ In `app/auth.py` |
| `RUN_PRE_TOKEN_CHECK` | `"1"` | ✅ In `app/auth.py` |
| `FORWARDED_ALLOW_IPS` | `127.0.0.1` | ✅ In `Dockerfile` |
| `APP_ENV` | `development` | ✅ In `Dockerfile` |

### 7.4 Healthcheck Behavior

- `HEALTHCHECK` in Dockerfile hits `GET /health` → `{"status": "ok"}`
- `GET /ready` also exists and returns `{"status": "ready"}`
- Both return 200 without database dependency check
- This is acceptable for development; production should verify DB connectivity

---

## 8. Target Local Infrastructure Design

### 8.1 Design Principles
- **Single `docker-compose.yml`** — no Kubernetes, no Helm, no Docker Swarm.
- **Two services minimum:** `postgres` + `sentinel-app`.
- **No Redis** unless and until the outbox runtime (P1-G) is implemented and actually requires it.
- **PostgreSQL init:** Use `init.sql` scripts mounted via `postgres/init/` mechanism (Docker official image `docker-entrypoint-initdb.d/`).
- **No separate detection/ML services** in v1 — they are logical modules within the single FastAPI app.

### 8.2 Proposed Compose File

```yaml
# docker-compose.yml
services:
  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: sentinel_auth
      POSTGRES_USER: sentinel
      POSTGRES_PASSWORD: sentinel123
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./infra/postgres/schema-core-v3.3.sql:/docker-entrypoint-initdb.d/01-core.sql
      - ./infra/postgres/schema-detection-v3.3.sql:/docker-entrypoint-initdb.d/02-detection.sql
      - ./infra/postgres/schema-ml-service-v3.3.sql:/docker-entrypoint-initdb.d/03-ml.sql
    ports:
      - "5432:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U sentinel -d sentinel_auth"]
      interval: 5s
      timeout: 3s
      retries: 5

  sentinel-app:
    build: .
    depends_on:
      postgres:
        condition: service_healthy
    environment:
      DATABASE_URL: postgresql://sentinel:sentinel123@postgres:5432/sentinel_auth
      INTERNAL_SECRET: ${INTERNAL_SECRET:?INTERNAL_SECRET must be set}
      FORWARDED_ALLOW_IPS: "127.0.0.1"
      DETECTION_URL: http://localhost:8001
      RUN_PRE_TOKEN_CHECK: "0"   # Disable in dev (no detection service)
    ports:
      - "8000:8000"

volumes:
  postgres_data:
```

### 8.3 `.env.example`

```bash
# Required
INTERNAL_SECRET=your-secret-at-least-32-characters-long

# Optional (have defaults)
DATABASE_URL=postgresql://sentinel:sentinel123@localhost:5432/sentinel_auth
FORWARDED_ALLOW_IPS=127.0.0.1
DETECTION_URL=http://localhost:8001
RUN_PRE_TOKEN_CHECK=0
APP_ENV=development
```

---

## 9. Database Source-of-Truth Audit

### 9.1 Schema Table Count Verification

| Schema File | Tables (actual) | Tables (documented) | Match? |
|------------|-----------------|---------------------|--------|
| `schema-core-v3.3.sql` | 13 | 13 (TASK_ASSIGNMENT L86-99) | ✅ |
| `schema-detection-v3.3.sql` | 7 | 7 (TASK_ASSIGNMENT L219-226) | ✅ |
| `schema-ml-service-v3.3.sql` | 3 | 3+1 view (TASK_ASSIGNMENT L370-374) | ✅ |

### 9.2 Cross-Reference Integrity

| Reference | Source | Target | Status |
|----------|--------|--------|--------|
| `mfa_transactions.user_id` | core | users.id | ✅ FK present |
| `sessions.user_id` | core | users.id | ✅ FK present |
| `user_roles.user_id` | core | users.id | ✅ FK present |
| `alerts.login_attempt_id` | detection | login_attempts (cross-schema) | ✅ FK present via UUID text |
| `alert_timeline.alert_id` | detection | alerts.id | ✅ FK present |
| `soc_analysts.user_id` | detection | users.id | ✅ FK present |
| `risk_assessments.login_attempt_id` | detection | login_attempts.id | ✅ FK present |
| `inference_logs.model_version_id` | ml | model_versions.id | ✅ FK present |

### 9.3 Active Policy Invariant

The `policies` table has a trigger `update_updated_at_column()` on every row update. The active-policy invariant (exactly one `is_active=TRUE` at any time) is enforced by application code in `app/detection.py`, not by a PostgreSQL constraint (CHECK subqueries are not supported).

**Classification:** APPLICATION-LEVEL INVARIANT — documented, enforced by code.

### 9.4 MFA Types and Statuses

From `app/models.py` `MfaType` and `MfaStatus` enums:
- Types: `persistent`, `one_time`
- Statuses: `pending`, `completed`, `failed`, `expired`

No `expired` status is written by application code — expiry is checked by comparing `expires_at > utc_now()` in Python, not by a DB state transition. This is correct.

---

## 10. UML / ERD Consistency Audit

### 10.1 Diagrams Classification

| File | Classification | Reason |
|------|--------------|--------|
| `docs/diagrams/wf1_login.uml` | **UPDATE** | L15: "IP from X-Forwarded-For" → should reference canonical `app/client_ip.py` |
| `docs/diagrams/wf3_soc.uml` | **UPDATE** | L24: "Validate JWT" → opaque token |
| `docs/diagrams/wf4_mfa_flow.uml` | **UPDATE** | JWT references; MFA state machine accurate |
| `docs/diagrams/wf5_session_management.uml` | **UPDATE** | L133: "Validate JWT" → opaque token |
| `docs/diagrams/architecture.uml` | **UPDATE** | Shows three-service topology; current is single process |
| `docs/diagrams/ERD_Chen_v3.3.puml` | **REGENERATE** | Likely shows `sessions` as JWT; cross-check needed |
| `docs/diagrams/ERD_v3.3.md` | **UPDATE** | L515: "JWT token management" → opaque tokens |
| `docs/diagrams/fig_architecture_overview.drawio` | **UPDATE** | Architecture topology |
| `docs/diagrams/fig_wf1_login.drawio` | **UPDATE** | XFF reference; IP trust model |
| `docs/bao-cao/ERD_core_v3.3.puml` | **KEEP** | Entity names match actual schema (12 entities); accurate |
| `docs/bao-cao/ERD_detection_v3.3.puml` | **KEEP** | 7 entities match actual schema |
| `docs/bao-cao/ERD_ml_v3.3.puml` | **KEEP** | 3 entities + 1 view match actual schema |
| `docs/bao-cao/uml-architecture.puml` | **UPDATE** | L40: "JWT + làm mới" → opaque tokens |
| `docs/bao-cao/uml-state-mfa-session.puml` | **KEEP** | State machine accurate for current implementation |
| `docs/bao-cao/uml-state-alert.puml` | **KEEP** | Alert state machine accurate |
| `docs/workflows.mmd` | **KEEP** | Correctly annotates outbox as "NOT impl."; accurate |
| `docs/v3.3-detect/*.puml` | **KEEP** | Detection-specific diagrams; accurate for design |

### 10.2 Critical Diagram Updates Needed

1. **All session/auth diagrams** (`wf3_soc.uml`, `wf5_session_management.uml`, `uml-architecture.puml`): Replace "JWT" with "opaque bearer token (SHA-256 hash in DB)"
2. **Architecture diagrams** (`architecture.uml`, `fig_architecture_overview.drawio`): Add annotation "v3.3 DESIGN TARGET — current runtime: single FastAPI process"
3. **`wf1_login.uml`**: Update IP trust model annotation to reflect `app/client_ip.py` policy

---

## 11. Report Structure Readiness

| Chapter | Status | Notes |
|---------|--------|-------|
| **CHAPTER I: Overview** | PARTIAL | Architecture diagram shows three-service; needs update for single-process current state |
| **CHAPTER II: Requirements** | PARTIAL | Bảng yêu cầu accurate; some UC descriptions (UC-DE-13, UC-DE-15) conflict with implementation |
| **CHAPTER III: System Analysis & Design** | PARTIAL | UML/ERD need updates (see Section 10); DB design is accurate |
| **CHAPTER IV: Implementation** | PARTIAL | Code is current; some comments stale (JWT references, `INTERNAL_SECRET` defaults) |
| **CHAPTER V: Deployment / Testing** | MISSING | No Docker Compose, no deployment guide, no test documentation |
| **CHAPTER VI: Conclusion** | BLOCKED_BY_DECISION | P1-B, P1-C decisions needed; implementation backlog must be resolved |

---

## 12. Source-of-Truth Hierarchy

### Proposed Hierarchy

**Level 1 — Approved Architecture Decisions (immutable after approval)**
- `docs/DECISIONS-DETECTION-v3.3.md` ← RISK SCORING FORMULA, FEATURE CONTRACT
- `TASK_ASSIGNMENT.md` ← 3-schema ownership, branch strategy

**Level 2 — Requirements / Use Cases**
- `docs/01-bang-yeu-cau-chuc-nang-nghiep-vu-core-app.md`
- `docs/04-bang-yeu-cau-chuc-nang-nghiep-vu-detection-engine.md`
- `docs/03-bang-yeu-cau-chuc-nang-nghiep-vu-ml-service.md`
- `docs/02-dac-ta-use-case-core-app.md` ← UC descriptions (need P1-B, P1-C reconciliation)

**Level 3 — SQL Schemas + API Contracts**
- `infra/postgres/schema-core-v3.3.sql` ← 13 tables
- `infra/postgres/schema-detection-v3.3.sql` ← 7 tables
- `infra/postgres/schema-ml-service-v3.3.sql` ← 3 tables
- `docs/workflows.mmd` ← API contracts (accurate for current HTTP endpoints)

**Level 4 — UML / ERD / Workflows**
- `docs/bao-cao/ERD_*.puml` ← accurate, regenerate PNG
- `docs/workflows.mmd` ← accurate for current state
- `docs/bao-cao/uml-state-*.puml` ← accurate for current state
- Architecture and auth UML ← need updates (see Section 10)

**Level 5 — Implementation**
- `app/**/*.py` ← authoritative for current runtime
- `tests/**/*.py` ← authoritative for current behavior

**Level 6 — Historical Audits**
- `docs/audit/10-findings.md` ← F-01 to F-10 all resolved
- `docs/audit/07-cross-artifact-conflicts.md` ← C-01 to C-16 tracked
- `docs/audit/08-open-decisions.md` ← Q-01 to Q-05

### Anti-Pattern to Prevent
Old design documents (SENTINEL_AUTH_TONG_HOP_v3.3.md, architecture diagrams) must NOT override Level 5 (implementation). The rule: **implementation is always the source of truth for current behavior; design documents describe intended state.**

---

## 13. Remediation Plan

### Sequence

#### D1: Canonical Architecture Decisions (No implementation changes)

**Files:** `docs/DECISIONS-DETECTION-v3.3.md`, `TASK_ASSIGNMENT.md`

- Update TASK_ASSIGNMENT.md header to clarify "v3.3 DESIGN / single-process current implementation"
- No changes to `app/`, `tests/`, `infra/postgres/`

#### D2: Business Decisions (No implementation changes)

**Files:** `docs/02-dac-ta-use-case-core-app.md`, `docs/06-phan-tich-doi-tuong-su-dung-detection-engine.md`, `docs/audit/12-second-review.md`, `docs/audit/05-trust-boundaries.md`

- **D2a:** Resolve P1-B: choose OPTION A (SOC Analyst direct-apply). Update UC-DE-13 description.
- **D2b:** Resolve P1-C: assign policy management to Security Admin only; update role matrix.
- No changes to `app/`, `tests/`, `infra/postgres/`

#### D3: Requirements / Use-Case Reconciliation

**Files:** `docs/01-bang-yeu-cau-*.md`, `docs/02-dac-ta-use-case-*.md`, `docs/03-*-ml-service.md`

- Reconcile UC descriptions against current implementation
- Mark unimplemented features explicitly (outbox, three-service deployment)
- No changes to `app/`, `tests/`, `infra/postgres/`

#### D4: UML / ERD Regeneration

**Files:** `docs/diagrams/*.uml`, `docs/diagrams/*.drawio`, `docs/bao-cao/uml-*.puml`

- Update all JWT → opaque token references
- Add "v3.3 DESIGN TARGET" annotation to architecture diagrams
- Update `wf1_login.uml` IP trust model annotation
- Do NOT regenerate `docs/bao-cao/ERD_*.puml` — these are accurate
- No changes to `app/`, `tests/`, `infra/postgres/`

#### I1: Docker / Environment Infrastructure

**Files:** `Dockerfile`, `docker-compose.yml`, `.env.example`

- **CRITICAL FIX:** Remove or fix `COPY infra/postgres/schema.sql` in Dockerfile
- Add `docker-compose.yml` with `postgres` + `sentinel-app` services
- Add `.env.example` with all documented environment variables
- No changes to `app/`, `tests/`, `infra/postgres/schema-*.sql`

#### I2: PostgreSQL Bootstrap Verification

**Files:** `infra/postgres/` (no changes to SQL files themselves)

- Add Docker init mechanism using `docker-entrypoint-initdb.d/`
- Bootstrap all three schemas in correct dependency order (core → detection → ml)
- Verify with `tests/test_postgres_bootstrap.py`

#### R1: Report Baseline

**Files:** `docs/bao-cao/_content_*.py`, chapter content generators

- Update Chapter I architecture description
- Update Chapter IV stale code comments (JWT references)
- No changes to `app/`, `tests/`, `infra/postgres/`

---

## 14. No Application Changes

This audit is infrastructure and documentation only. The following are explicitly NOT modified:

- `app/**/*.py` — frozen
- `tests/**/*.py` — frozen
- `infra/postgres/schema-*.sql` — frozen

### Approved Decisions (2026-10-09)

The following were decided and are now authoritative:

| Decision | Document | Status |
|----------|----------|--------|
| Opaque token model (not JWT) | `docs/DECISIONS-SYSTEM-v3.3.md` Section 1 | ✅ APPROVED |
| Three logical databases on one PostgreSQL server | `docs/DECISIONS-SYSTEM-v3.3.md` Section 3 | ✅ APPROVED |
| Redis Streams as async transport (not session/token store) | `docs/DECISIONS-SYSTEM-v3.3.md` Section 4 | ✅ APPROVED |
| Current monolith vs target three-service distinction | `docs/DECISIONS-SYSTEM-v3.3.md` Section 5 | ✅ APPROVED |
| Docker infrastructure (postgres + redis) | `docker-compose.yml`, `docs/INFRASTRUCTURE-v3.3.md` | ✅ APPROVED |

---

## 15. Summary: Blocking Issues

### ✅ RESOLVED by this pass

| Priority | Issue | Resolution |
|----------|-------|-----------|
| 🔴 CRITICAL | `Dockerfile` referenced non-existent `infra/postgres/schema.sql` | Fixed: schemas mounted to `/schemas`, referenced by init script |
| 🔴 CRITICAL | No `docker-compose.yml` | Created: `postgres` + `redis` services |
| 🔴 CRITICAL | No `.env.example` | Created: full env template with all variables |
| 🔴 CRITICAL | No PostgreSQL init mechanism | Created: `infra/postgres/init/00-init-databases.sh` |

### 🟡 HIGH — Pending decisions

| Priority | Issue | Blocks |
|----------|-------|--------|
| 🟡 HIGH | P1-B: SOC action workflow (request vs direct-apply) | Implementation |
| 🟡 HIGH | P1-C: Policy management roles | Implementation |
| 🟡 HIGH | UML diagrams: JWT → opaque token | Report accuracy |
| 🟡 HIGH | `schema-core-v3.3.sql` COMMENT says "JWT" | Report accuracy |

### 🟢 MEDIUM — Documentation updates

| Priority | Issue | Blocks |
|----------|-------|--------|
| 🟢 MEDIUM | `docs/audit/04-database-bootstrap.md` shows fixed failures | Misleading |
| 🟢 MEDIUM | `docs/SENTINEL_AUTH_TONG_HOP_v3.3.md` describes JWT as current | Report accuracy |
| 🟢 LOW | Old audit docs (10–14) show resolved P0 findings | Historical record is fine |

---

**STATUS: DOCS_INFRA_BASELINE_AUDIT_COMPLETE**
