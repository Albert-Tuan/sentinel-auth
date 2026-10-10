# Sony — Core / Auth / IAM Assignment

**Branch:** `core-app`
**Bounded Context:** CORE / AUTH / IAM
**Primary Business Role:** USER
**Secondary Responsibility:** IAM-side Security Admin functions

---

## 1. Mission

Own and implement the Core/Auth/IAM bounded context for Sentinel Auth v3.3.

You are responsible for: user identity, authentication, session management, MFA, trusted devices, rate limiting, Core-side protective-action enforcement, and IAM-side Security Admin functions.

You do NOT own: Detection rules, SOC alerts, ML inference, or Manager analytics.

---

## 2. Branch / Ownership

```
Branch: core-app
Start from: dev (latest approved baseline)
Primary service: Core / Auth / IAM
Database: sentinel_core (13 base tables)
```

---

## 3. Required Reading

Read in this order before starting implementation:

1. `docs/DECISIONS-SYSTEM-v3.3.md` — canonical auth and session decisions
2. `docs/01-bang-yeu-cau-chuc-nang-nghiep-vu-core-app.md` — functional requirements
3. `docs/02-dac-ta-use-case-core-app.md` — use case specifications
4. `docs/03-phan-tich-doi-tuong-su-dung-phan-mem-core-app.md` — actor analysis
5. `infra/postgres/schema-core-v3.3.sql` — all 13 tables (see Section 6)
6. `docs/workflows.mmd` — WF-1 (login), WF-4 (MFA), WF-5 (session)
7. `docs/diagrams/wf1_login.uml` — login flow
8. `docs/diagrams/wf4_mfa_flow.uml` — MFA flow
9. `docs/diagrams/wf5_session_management.uml` — session management
10. Core↔Detection sections in `docs/DECISIONS-DETECTION-v3.3.md` — pre-token check contract
11. `docs/INFRASTRUCTURE-v3.3.md` — infrastructure decisions
12. `docs/assignments/CONTRACT_CORE_DETECTION.md` — Core↔Detection contract

---

## 4. Business Responsibilities

### USER (Primary Actor)

- Register account
- Login with username + password
- Complete MFA challenge (Email OTP — CURRENT; TOTP/SMS/Push — FUTURE)
- Manage own sessions (list, revoke)
- Refresh tokens (without extending session expiry)
- Logout (single, all)
- Manage trusted devices
- View own account info

### IAM-Side Security Admin

- View user accounts
- Create/read/update user accounts
- Manage roles and user-role assignments
- Assign/unassign roles to users
- View audit logs

### NOT Your Responsibility

- SOC alert lifecycle — Tuấn Anh owns
- Detection policies and rules — Tuấn Anh owns
- ML inference — Khang owns
- Manager analytics — Khang owns

---

## 5. Technical Responsibilities

### Authentication

- Opaque access token: `secrets.token_urlsafe(32)` → SHA-256 hash in DB
- Opaque refresh token: `secrets.token_urlsafe(32)` → SHA-256 hash in DB
- **NOT JWT** — do not implement JWT

### Session Rules (CRITICAL — do not change)

```
Session created:
  expires_at = login_time + 1 hour  (FIXED)

Refresh:
  1. Hash incoming refresh token
  2. Find backing session (unrevoked, unexpired)
  3. Rotate access token (new random 32-byte string)
  4. Rotate refresh token (new random 32-byte string)
  5. Update last_activity_at
  6. DO NOT extend expires_at
```

### MFA (CURRENT vs FUTURE)

| Channel | Status |
|---------|--------|
| Email OTP | **CURRENT** — implement now |
| TOTP | FUTURE — design only |
| SMS | FUTURE — design only |
| Push | FUTURE — design only |

### Pre-Token Detection Client

- Call `POST /api/v1/internal/pre-token-check` before granting access
- Timeout: **3 seconds**
- On timeout or failure: **fail open** (allow login, let Detection act later)
- Consume: `risk_level`, `require_mfa`, `degraded` from response

### Protective Action Enforcement

- Expose `POST /api/v1/internal/actions` endpoint
- Consume action requests from Detection Engine
- Supported actions: `REQUIRE_MFA`, `REVOKE_SESSIONS`, `LOCK_USER`, `FORCE_LOGOUT`
- Do NOT make autonomous protective decisions — Detection orchestrates

### Rate Limiting

- IP-based rate limiting on auth endpoints
- Use `rate_limits` table

---

## 6. Database Ownership

### sentinel_core — 13 Base Tables

| # | Table | Purpose |
|---|-------|---------|
| 1 | `users` | Core user accounts (id, username, password_hash, email, status, mfa flags, lock state) |
| 2 | `roles` | Role definitions (USER, SECURITY_ADMIN, SOC_ANALYST, SECURITY_MANAGER) |
| 3 | `user_roles` | User-role assignments (many-to-many) |
| 4 | `sessions` | Active sessions (access_token_hash, refresh_token_hash, token_jti, expires_at, last_activity_at, revoked_at) |
| 5 | `mfa_transactions` | MFA challenge lifecycle (user_id, mfa_type, status: pending/completed/expired/failed) |
| 6 | `mfa_notifications` | MFA notification tracking (channel: email/sms/totp, recipient, mfa_code_hash, expires_at) |
| 7 | `audit_logs` | Immutable audit trail (actor_id, action, resource, before_state/after_state JSONB) |
| 8 | `user_trusted_devices` | Remembered devices (user_id, device_fingerprint, expires_at) |
| 9 | `system_settings` | Dynamic config (key/value/type/category) |
| 10 | `outbox_events` | Transactional outbox (aggregate_type, event_type, payload JSONB, status: pending/processing/published/failed) |
| 11 | `user_notifications` | In-app notifications (type, title, body, read/read_at) |
| 12 | `rate_limits` | Rate limiting counters (ip_address, action, count, max_count, window_start) |
| 13 | `ip_addresses` | Normalized IP tracking (ip_address INET, country, proxy/vpn/tor flags) |

### Key Constraints

- No cross-database foreign keys to `sentinel_detection` or `sentinel_ml`
- `soc_analysts` table is in `sentinel_detection`, NOT here
- `users.id` is referenced by `sentinel_detection.soc_analysts.user_id` as a logical cross-DB reference

---

## 7. APIs / Contracts Owned

### Public Auth API

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/auth/register` | User registration |
| POST | `/api/v1/auth/login` | Login with password |
| POST | `/api/v1/auth/mfa/verify` | MFA verification |
| POST | `/api/v1/auth/refresh` | Token refresh |
| POST | `/api/v1/auth/logout` | Single logout |
| GET | `/api/v1/auth/sessions` | List own sessions |
| DELETE | `/api/v1/auth/sessions/{id}` | Revoke own session |

### Internal (Detection Consumer)

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/internal/actions` | Receive protective action from Detection |

### Devices API

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/devices` | List trusted devices |
| POST | `/api/v1/devices` | Add trusted device |
| POST | `/api/v1/devices/check` | Check if device trusted |
| DELETE | `/api/v1/devices/{id}` | Remove trusted device |
| DELETE | `/api/v1/devices/all` | Remove all trusted devices |

### NOT Owned (Tuấn Anh)

- Alert endpoints: `/api/v1/alerts/**` — Tuấn Anh owns
- Policy endpoints: `/api/v1/policies/**` — Tuấn Anh owns
- ML endpoint: `/api/v1/internal/ml/**` — Khang owns

---

## 8. Current Source to Inspect

Before refactoring anything, **inspect the current code**:

```
app/auth.py          — existing auth logic, token generation, login, MFA verify
app/authz.py         — existing authorization decorators
app/devices.py       — trusted device management
app/client_ip.py     — IP extraction from X-Forwarded-For
app/internal_actions.py — protective action enforcement endpoint
app/models.py        — SQLAlchemy models
app/schemas.py       — Pydantic request/response schemas
app/db.py            — database session management
app/main.py          — FastAPI app, router mounting, middleware
```

Also inspect relevant tests in `tests/**`:
- `tests/test_auth.py`
- `tests/test_risk_gate.py` (pre-token client)
- `tests/test_devices.py`
- `tests/test_internal_actions.py`
- `tests/test_ml.py`

**Do NOT rebuild working behavior from scratch without understanding current code.**

---

## 9. Explicit Non-Scope

The following are **NOT your responsibility** in the Core/Auth bounded context:

- SOC alert lifecycle (view, acknowledge, resolve, false positive)
- Detection rules, policies, rule evaluation
- ML inference, model registry, score normalization
- Manager dashboard / analytics / reporting
- Protective action **orchestration** (Detection decides, you enforce)
- Redis Streams or outbox publisher (table exists; publisher NOT implemented)
- TOTP/SMS/Push MFA channels (FUTURE — design only)

---

## 10. Shared Dependencies

### Core → Detection

| Dependency | Direction | Contract |
|-----------|-----------|----------|
| Pre-token risk check | You call Detection | `POST /api/v1/internal/pre-token-check` — see `CONTRACT_CORE_DETECTION.md` |
| Login event delivery | You call Detection | `POST /api/v1/internal/login-events` |

### Core ← Detection

| Dependency | Direction | Contract |
|-----------|-----------|----------|
| Protective actions | Detection calls you | `POST /api/v1/internal/actions` — see `CONTRACT_CORE_DETECTION.md` |

### Coordination Required

- **Tuấn Anh (Detection)**: For pre-token check contract and protective action API
- **Khang (ML)**: For ML health check (optional — used in pre-token path)

---

## 11. Implementation Order

### S0 — Sync & Inspect Baseline

```
Inputs:  latest dev branch, current app/auth.py, app/models.py
Outputs: understanding of what already works
Actions: run pytest -q, inspect auth.py, db.py, main.py
```

### S1 — Core IAM Base

```
Inputs:  schema-core-v3.3.sql, models.py
Outputs: User, Role, UserRole SQLAlchemy models
         password hashing helper
         opaque token helper (secrets.token_urlsafe + SHA-256)
         auth context dependency
Actions: Inspect current models.py — extend only if needed
Tests:   test_auth.py (existing)
Acceptance: models map correctly to 13 tables; no breaking changes
```

### S2 — Registration + Login

```
Inputs:  S1 models, existing auth.py
Outputs: POST /register, POST /login endpoints
         pre-token check integration
         login_attempts event delivery to Detection (see below)
Actions: Do NOT change session semantics (1h fixed, no JWT)
Tests:   test_auth.py, test_risk_gate.py
Acceptance: login works, pre-token check integrated
```

### S2b — Login Event Delivery to Detection  [IMPLEMENTATION PENDING]

```
Inputs:  Detection receiver endpoint (already implemented by Tuấn Anh)
Outputs: Core producer: POST /api/v1/internal/login-events after each login attempt
         Retry behavior (implementation decision)
Actions: Inspect detection.py receive_login_event endpoint first
         Implement httpx producer in auth.py after login_attempt is committed
         Coordinate with Tuấn Anh on contract tests
         NOTE: Detection receiver is implemented; Core producer is NOT YET IMPLEMENTED
Tests:   Core↔Detection contract tests (joint with Tuấn Anh)
Acceptance: Detection receives login events from Core; idempotency via event_id works
```

**Evidence from source:**
- Detection receiver: `app/detection.py:779` (`receive_login_event`)
- Detection tests: `tests/test_detection.py:365-379`
- Core producer: **NOT FOUND** in `app/auth.py` — no httpx call to `/login-events`
- Login events are written to `sentinel_core.login_attempts` only; not sent to Detection


### S3 — Pre-Token Detection Integration

```
Inputs:  Detection contract (CONTRACT_CORE_DETECTION.md)
Outputs: Core client for POST /api/v1/internal/pre-token-check
         3-second timeout
         fail-open behavior
Actions: Implement in auth.py before granting access
Tests:   test_risk_gate.py
Acceptance: high/critical triggers MFA challenge; timeout fails open
```

### S4 — Email OTP MFA

```
Inputs:  mfa_transactions, mfa_notifications tables
Outputs: POST /mfa/verify endpoint
         Email OTP generation + delivery
         MFA transaction lifecycle
Actions: Implement email OTP only (TOTP/SMS/Push are FUTURE)
Tests:   test_risk_gate.py (mfa branch), test_ml.py (concurrent MFA if any)
Acceptance: MFA challenge completes, session created after valid OTP
```

### S5 — Sessions (Refresh, Logout)

```
Inputs:  sessions table, opaque token helper
Outputs: POST /refresh (rotate tokens, NO expires_at extension)
         POST /logout, DELETE /sessions/{id}
         GET /sessions
Actions: Inspect existing session logic first
Tests:   test_auth.py (existing session tests)
Acceptance: refresh rotates tokens; logout revokes; 1h expiry fixed
```

### S6 — Trusted Devices + Rate Limiting

```
Inputs:  user_trusted_devices, rate_limits tables
Outputs: device fingerprinting
         trusted device storage
         IP-based rate limiting on login
Tests:   test_devices.py
Acceptance: devices stored; rate limits enforced
```

### S7 — IAM-Side Security Admin

```
Inputs:  users, roles, user_roles, audit_logs tables
Outputs: Admin endpoints for user/account lifecycle
         Role assignment endpoints
         Audit log viewing
Actions: Design only for now (create/edit endpoints IMPLEMENTATION PENDING)
         Implement view/read operations first
Tests:   test_postgres_auth.py, test_postgres_rbac.py
Acceptance: admin can view users, assign roles
```

### S8 — Protective-Action Executor

```
Inputs:  CONTRACT_CORE_DETECTION.md
Outputs: POST /api/v1/internal/actions endpoint
         REQUIRE_MFA, REVOKE_SESSIONS, LOCK_USER, FORCE_LOGOUT handlers
         Idempotency key handling
Tests:   test_internal_actions.py
Acceptance: Detection can send action; action enforced; audit logged
```

### S9 — Tests / Cleanup

```
Inputs:  all milestones
Outputs: Full test coverage
         Documentation update
Actions: Run pytest -q; fix failures; update API docs if contract changed
```

---

## 12. Required Tests

| Area | Test File(s) | Minimum Coverage |
|------|-------------|-----------------|
| Auth | `tests/test_auth.py` | Login, register, logout, session list |
| MFA | `tests/test_risk_gate.py`, `tests/test_postgres_mfa_concurrency.py` | OTP flow, MFA required, rate limit |
| Session | `tests/test_auth.py` | Refresh (no expiry extension), revoke |
| Trusted Devices | `tests/test_devices.py` | Add, check, remove |
| Rate Limiting | `tests/test_client_ip.py` | IP extraction, rate limit enforcement |
| Pre-token Client | `tests/test_risk_gate.py` | 3s timeout, fail-open, high/critical → MFA |
| Internal Actions | `tests/test_internal_actions.py` | All 4 action types, idempotency |
| RBAC / IAM | `tests/test_postgres_auth.py`, `tests/test_postgres_rbac.py` | Role assignment, permission checks |
| Schema Consistency | `tests/test_schema_consistency.py` | 13 tables match schema |

---

## 13. Acceptance Criteria

- [ ] Registration creates user in `users` table
- [ ] Login validates credentials; wrong password returns 401
- [ ] Pre-token check called before granting session (3s timeout, fail-open)
- [ ] High/critical risk from Detection triggers MFA challenge
- [ ] Email OTP completes MFA flow; session created after valid OTP
- [ ] Session `expires_at` = login_time + 1h (fixed — NEVER extended by refresh)
- [ ] Refresh rotates both tokens; does NOT extend `expires_at`
- [ ] Logout revokes session (sets `revoked_at`)
- [ ] `POST /api/v1/internal/actions` enforces `REQUIRE_MFA`, `REVOKE_SESSIONS`, `LOCK_USER`, `FORCE_LOGOUT`
- [ ] Trusted devices skip MFA challenge
- [ ] Rate limiting blocks repeated failed login attempts
- [ ] IAM admin can view users and assign roles
- [ ] Audit logs written for all sensitive operations
- [ ] `pytest -q` passes (358+ tests)
- [ ] No JWT library introduced

---

## 14. Definition of Done

Your task is DONE when ALL of the following are true:

1. **Your acceptance criteria pass** (see Section 13)
2. **Your tests pass** (`pytest tests/test_auth.py tests/test_risk_gate.py tests/test_internal_actions.py tests/test_devices.py -q`)
3. **Shared contract tests pass** — Core↔Detection contract integration works
4. **No canonical decision violated** — session semantics unchanged, no JWT, no expiry extension
5. **No unauthorized database access** — you did not read/write sentinel_detection or sentinel_ml tables directly
6. **Documentation updated** — if you changed the internal actions contract, `CONTRACT_CORE_DETECTION.md` is updated
7. **Branch cleanly merges into dev** — no conflicts
8. **Integration does not break other service tests** — Tuấn Anh's and Khang's tests still pass

---

## 15. Stop / Ask Lead Conditions

**STOP and ask the lead before:**

- Changing session expiry semantics (1h fixed is canonical)
- Implementing JWT or any signed token
- Extending `expires_at` on refresh
- Changing the pre-token timeout (3 seconds is canonical)
- Changing fail-open to fail-closed on pre-token
- Adding new action types beyond `REQUIRE_MFA`, `REVOKE_SESSIONS`, `LOCK_USER`, `FORCE_LOGOUT`
- Implementing TOTP/SMS/Push MFA (mark as FUTURE)
- Changing user password hashing algorithm
- Modifying `app/main.py` shared entrypoint (requires lead)
- Adding cross-database FK references
- Changing the opaque token architecture
- Introducing Redis/outbox publisher logic (not your scope)
- Deleting existing working behavior

---

## 16. Handoff Checklist

Before marking your milestone complete:

- [ ] All source files inspected (not just reading requirements)
- [ ] Current baseline tests pass (`pytest -q`)
- [ ] Session semantics verified: 1h fixed, refresh does NOT extend `expires_at`
- [ ] No JWT introduced
- [ ] Pre-token client uses 3s timeout and fails open
- [ ] Protective action executor handles all 4 action types
- [ ] `outbox_events` table not modified (schema is canonical)
- [ ] Cross-DB access prohibited (no direct sentinel_detection/sentinel_ml queries)
- [ ] Tests written for new behavior
- [ ] Contract document updated if internal API changed
- [ ] Branch merges cleanly into dev
