# Sentinel Auth v3.3 — System Canonical Decisions

> **Status:** APPROVED
> **Version:** 1.0
> **Date:** 2026-10-09
> **Repository:** Albert-Tuan/sentinel-auth (`dev` branch)

This document is the highest-level system-wide source of truth for Sentinel Auth v3.3.
It captures approved architectural decisions that override any conflicting statements in
older design documents, prototype notes, or historical audits.

The Document Hierarchy (Section 2) takes precedence over all other documents
in this repository. Historical audit documents (Level 6) record past findings but
do not override approved decisions in this document.

---

## 1. Token Model

### 1.1 Current Approved Architecture

Sentinel Auth v3.3 uses **opaque random tokens** for user authentication.

**Access token:**
- Value: `secrets.token_urlsafe(32)` — 32 bytes of cryptographically random data, base64-url encoded.
- Not a JWT. Not signed. Not self-describing.
- Hash (SHA-256) persisted in `sessions.access_token_hash` column.

**Refresh token:**
- Value: `secrets.token_urlsafe(32)` — 32 bytes of cryptographically random data.
- Hash (SHA-256) persisted in `sessions.refresh_token_hash` column.

**Session state:**
- DB-backed: every authenticated request queries `sessions` table.
- `revoked_at` column enables immediate revocation without token expiry lists.
- `expires_at` column gates whether a session is considered active.

**Identity resolution:**
```
Bearer opaque token
  → hash token (SHA-256)
  → query sessions WHERE access_token_hash = hash AND revoked_at IS NULL
  → User (via user_id FK)
  → Roles (via user_roles)
```

### 1.2 Why Not JWT?

JWT was considered but is NOT part of the v3.3 authentication architecture for these reasons:

| Requirement | JWT Impact | Opaque Token Advantage |
|------------|-----------|----------------------|
| `FORCE_LOGOUT` / `REVOKE_SESSIONS` | Requires allowlist or short expiry | Works immediately via `revoked_at` |
| Account locking | Must wait for token expiry or maintain deny-list | Immediate: all sessions point to user |
| SOC protective actions | Must propagate revocation to all services | Works via single session row |
| Immediate session invalidation | Requires either short TTL or distributed state | Works via single DB update |
| Role-change propagation | Must wait for token expiry | Session re-authorized on next request |

### 1.3 Token `token_jti` Column

The `sessions.token_jti` column in `schema-core-v3.3.sql` holds a UUID generated at
session creation. The name is an internal historical artifact from when JWT was
considered. It does NOT mean the token is a JWT.

- `token_jti` is a session identifier, not a JWT claim.
- It is not used in the current implementation's authentication flow.
- **Do NOT rename this column** in v3.3 — that is a future schema migration concern.

### 1.4 Future Token Introspection (Not Implemented)

If a future independently deployed service needs to validate a user's session,
the approved mechanism is **Core token introspection**, not JWT validation:

```
POST /internal/auth/introspect
  Body: { "opaque_token": "<token>" }
  Auth: X-Internal-Secret

Response 200:
  { "active": true, "user_id": "...", "roles": [...], "expires_at": "..." }

Response 404:
  { "active": false }
```

This endpoint is **NOT implemented** in v3.3. Mark it as FUTURE IMPLEMENTATION.

---

## 2. Document Hierarchy

This hierarchy resolves conflicts between documents. Higher levels override lower
levels. Approved decisions at any level do NOT automatically change implementation;
they create a record that implementation must be updated to match.

**Level 1 — System Architecture Decisions (this document)**
- `docs/DECISIONS-SYSTEM-v3.3.md` ← highest authority
- `docs/DECISIONS-DETECTION-v3.3.md` ← risk scoring formula, feature contract

**Level 1B — Governance / Ownership**
- `TASK_ASSIGNMENT.md` ← schema ownership, branch strategy, team responsibilities

**Level 2 — Requirements / Use Cases**
- `docs/01-bang-yeu-cau-chuc-nang-nghiep-vu-*.md`
- `docs/02-dac-ta-use-case-*.md`
- `docs/04-bang-yeu-cau-chuc-nang-nghiep-vu-detection-engine.md`
- `docs/03-*-ml-service.md`

**Level 3 — SQL Schemas / API Contracts**
- `infra/postgres/schema-core-v3.3.sql` ← 13 tables, `sentinel_core`
- `infra/postgres/schema-detection-v3.3.sql` ← 7 tables, `sentinel_detection`
- `infra/postgres/schema-ml-service-v3.3.sql` ← 3 tables, `sentinel_ml`
- `docs/workflows.mmd` ← API contracts (accurate for current HTTP endpoints)

**Level 4 — UML / ERD / Workflows**
- `docs/bao-cao/ERD_*.puml` ← accurate entity diagrams
- `docs/bao-cao/uml-state-*.puml` ← accurate state machines
- `docs/workflows.mmd` ← accurate current workflow description

**Level 5 — Implementation**
- `app/**/*.py` ← authoritative for current runtime behavior
- `tests/**/*.py` ← authoritative for verified behavior

**Level 6 — Historical Audits**
- `docs/audit/10-findings.md` through `docs/audit/15-docs-infra-baseline-audit.md`
- These record past findings and do NOT override Level 1 decisions.

**Anti-pattern this hierarchy prevents:** Old design documents (e.g.
`SENTINEL_AUTH_TONG_HOP_v3.3.md`, architecture UML diagrams) claiming JWT or
three-service deployment as "current" must not override the authoritative
implementation at Level 5 or the decisions in this document at Level 1.

**If implementation differs from a Level 1–3 document:** Record an
implementation gap. Do not silently change the document to match a buggy
implementation, and do not change the implementation without a documented decision.

---

## 3. Database Topology

### 3.1 Approved Physical Topology

**One physical PostgreSQL server** (single container/service) containing **three
logical databases** representing service ownership boundaries.

```
PostgreSQL 16 (one server)
│
├── sentinel_core       (13 base tables — Core/Auth service ownership)
├── sentinel_detection  (7 base tables — Detection Engine service ownership)
└── sentinel_ml        (3 base tables + 1 view — ML Service ownership)
```

### 3.2 Rationale

Separate databases (not separate schemas within one database) enforce service
ownership at the connection level. A service's PostgreSQL user can be granted
access only to its own database, preventing accidental cross-service queries at
the infrastructure level.

### 3.3 NOT Approved

- Three separate PostgreSQL containers — adds operational complexity without
  additional security benefit for a university project.
- All three schemas merged into one `public` schema — defeats ownership separation.
- Three separate containers each running the same monolith — this is dishonest
  service separation.

### 3.4 Database Inventory

| Database | Schema File | Base Tables | Real View |
|----------|-------------|-------------|-----------|
| `sentinel_core` | `schema-core-v3.3.sql` | 13 | — |
| `sentinel_detection` | `schema-detection-v3.3.sql` | 7 | — |
| `sentinel_ml` | `schema-ml-service-v3.3.sql` | 3 | `local_ml_stats` |

**Total: 23 base tables, 1 real view.**

`manager_dashboard` referenced in `schema-ml-service-v3.3.sql` is a commented-out
conceptual reference. The canonical ML dashboard view is `local_ml_stats`.

### 3.5 Cross-Database References

Cross-database references use UUID text columns (not FK constraints). For example,
`alerts.login_attempt_id` references `login_attempts.id` in `sentinel_detection`
from `sentinel_detection` itself (intra-database). The `soc_analysts` table
cross-references `users.id` in `sentinel_core` via a UUID text column — this is
an intentional cross-database reference handled at the application layer.

---

## 4. Redis

### 4.1 Approved Role

Redis is approved as an **asynchronous event transport**, specifically **Redis Streams**,
for future outbox-based event delivery.

### 4.2 NOT Approved for v3.3

Redis is NOT approved for:

- Session storage (PostgreSQL is the authoritative session store)
- User data (PostgreSQL is the authoritative user database)
- Token storage (PostgreSQL `sessions` table is authoritative)
- RBAC state caching (PostgreSQL is authoritative)
- Any role that requires durability without PostgreSQL backing

### 4.3 Intended Outbox Flow

```
Application transaction
  → business state changes in PostgreSQL
  → OutboxEvent row written to sentinel_core.outbox_events
  → PostgreSQL transaction commits
  → durable event record exists in PostgreSQL

Future Outbox Publisher (not implemented in v3.3)
  → polls sentinel_core.outbox_events for pending events
  → publishes event to Redis Stream
  → marks event as published in outbox_events

Future Detection Consumer (not implemented in v3.3)
  → reads from Redis Stream
  → idempotent processing (deduplication via event_id)
```

### 4.4 Redis Guarantees

| Property | PostgreSQL (Authoritative) | Redis (Transport) |
|----------|--------------------------|-------------------|
| Durability | WAL + fsync | AOF (optional) |
| Source of truth | ✅ Yes | ❌ No |
| Event persistence | `outbox_events` table | Stream (transient if not consumed) |
| Outage behavior | Writes continue | Events queue in PostgreSQL |

Redis being unavailable does NOT lose events — they remain pending in
`outbox_events` until Redis recovers.

### 4.5 Future Stream Names

Stream names are NOT defined in this document. They will be defined when the
outbox publisher runtime (P1-G) is implemented.

---

## 5. Service Architecture

### 5.1 Current Implementation

The current codebase is a **single-process FastAPI monolith**. One `app/`
package, one running Python process, one `uvicorn` command.

```
Current runtime:  single uvicorn process
                  └── app.main:app
                      ├── auth router
                      ├── detection router
                      ├── ml router
                      ├── alerts router
                      ├── devices router
                      ├── internal_actions router
                      └── internal_auth (utility)
```

Logical boundaries (Core / Detection / ML) exist as code modules, not as
independent processes.

**The database boundary is nevertheless enforced at runtime.** Each bounded
context owns its own database and its own session dependency
(`get_core_db`, `get_detection_db`, `get_ml_db`), each with a **separate
engine and connection pool**. A Detection query therefore cannot run
against the Core schema even inside the single process — the ownership
boundary from section 3.2 is real, not merely documentary.

### 5.2 Target Architecture (v3.3 Design)

```
Core/Auth Service       Detection Engine         ML Service
(uvicorn :8000)       (uvicorn :8001)         (uvicorn :8002)
  │                       │                        │
  ▼                       ▼                        ▼
sentinel_core      sentinel_detection         sentinel_ml
```

Each service:
- Owns its database
- Has its own FastAPI application
- Authenticates internal calls via `X-Internal-Secret`
- Communicates via HTTP REST (no message broker in v3.3 baseline)

### 5.3 Distinction

The **current implementation** and the **target architecture** are different.
This document and all infrastructure files reflect the **target architecture**.
Application code (Level 5) is authoritative for the **current implementation**.

Do NOT claim three-service separation is implemented when only one process runs.

### 5.4 Service Authentication

User-facing authentication is provided by the **Core/Auth Service**.

Internal service-to-service authentication uses **shared `INTERNAL_SECRET`**:

```
Header: X-Internal-Secret: <secret>
```

`get_internal_secret()` in `app/internal_auth.py` validates the environment
variable. The secret must be at least 32 characters. The application refuses
to start if the secret is absent, empty, or set to `"changeme-in-production"`.

Detection Engine does NOT directly validate user sessions — it trusts Core's
authentication decision encoded in the `LoginEvent` payload.

---

## 6. Internal Authentication

| Setting | Value | Notes |
|---------|-------|-------|
| Environment variable | `INTERNAL_SECRET` | No default |
| Minimum length | 32 characters | Enforced at startup |
| Placeholder rejection | `"changeme-in-production"` | Rejected at startup |
| Algorithm | `hmac.compare_digest` | Timing-safe comparison |
| Startup failure | `InternalAuthConfigurationError` → 503 | Core refuses to start without valid secret |
| Detection unavailability | Fail-open for login | `require_mfa` defaults to `False` |

---

## 7. Outbox / Event Delivery

### 7.1 Approved Pattern

Transactional outbox pattern for all cross-service events:

1. Business state change + `OutboxEvent` row written in same PostgreSQL transaction.
2. Transaction commits → durable event exists in `outbox_events`.
3. Future background publisher reads pending events, publishes to Redis Streams.
4. Consumer reads from Redis Stream, processes idempotently.

### 7.2 Not Implemented

- Outbox publisher runtime (P1-G)
- Reconciliation scheduler (P1-H)
- Redis Streams consumer

These are implementation backlog items.

### 7.3 Events Intended for Outbox

| Event | Source | Destination | Status |
|-------|--------|-------------|--------|
| `LoginEvent` | Core | Detection | INTENDED — not implemented via outbox |
| `MfaAppliedEvent` | Core | Detection | INTENDED — not implemented via outbox |
| `SessionRevokedEvent` | Core | Detection | INTENDED — not implemented via outbox |

Current implementation sends `LoginEvent` via direct HTTP call to Detection.
This is acceptable for v3.3 but must be replaced by outbox for production.

---

## 9. Protective Action Authorization (P1-B / P1-J)

### 9.1 Approved v3.3 Behavior

SOC Analysts may directly execute supported protective actions from an alert.
Security Managers may also execute supported protective actions in a supervisory role.

There is **no mandatory approval workflow** in v3.3:

```
SOC Analyst request → Security Manager approval → apply action
```

This approval-chain pattern is **NOT** part of v3.3. References to `APPROVE_ACTION`,
`pending action requests`, or manager-approval steps in older documents are
**FUTURE ENHANCEMENT**.

### 9.2 Supported Actions

| Action | Executor | Notes |
|--------|----------|-------|
| `REQUIRE_MFA` | SOC Analyst, Security Manager | Forces MFA on next login |
| `REVOKE_SESSIONS` | SOC Analyst, Security Manager | Invalidates all active sessions |
| `LOCK_USER` | SOC Analyst, Security Manager | Prevents login until unlocked |
| `FORCE_LOGOUT` | SOC Analyst, Security Manager | Revokes the current session |

### 9.3 Rationale

- Keeps university-project scope manageable
- Matches existing prototype semantics (direct `POST /internal/detection/actions` call)
- Avoids adding action-request tables and approval state machines
- Preserves Security Manager supervisory capability
- Approval workflow may be introduced in a production-oriented future version

### 9.4 Implementation Gap (Known)

The current prototype's `POST /internal/detection/actions` endpoint performs
no role verification on the calling user. Any authenticated user can trigger any
action. Role-gated action execution is an **implementation gap** to address
during the next implementation phase.

---

## 10. Policy Management Authorization (P1-C / P1-K)

### 10.1 Approved Role Matrix

| Role | View Policy | Create Policy | Edit Policy | Activate Policy |
|------|------------|--------------|------------|----------------|
| `SECURITY_ADMIN` | ✅ YES | ✅ YES | ✅ YES | ✅ YES |
| `SECURITY_MANAGER` | ✅ YES | ❌ NO | ❌ NO | ❌ NO |
| `SOC_ANALYST` | ❌ NO | ❌ NO | ❌ NO | ❌ NO |

### 10.2 Role Descriptions

**SECURITY_ADMIN** — Full policy lifecycle owner. Can create, edit, view, and
activate policies. Owns the Detection Engine's risk-response configuration.

**SECURITY_MANAGER** — May view policies for oversight and review. May not
mutate policy state. The `VIEW_POLICIES` permission (not `MANAGE_POLICIES`)
is the correct terminology. References to `MANAGE_POLICIES` for Security Manager
in older documents are **STALE**.

**SOC_ANALYST** — Does not access policy management. Focused on alert response
and protective actions (Section 9).

### 10.3 Rationale

- Separation of concerns: policy owners (Security Admin) vs. policy consumers (SOC Analyst)
- Security Manager oversight role without mutation prevents self-approval scenarios
- Policy listing and activation are role-gated in the prototype; create/edit are pending

### 10.4 Implementation Status

The current prototype provides partial policy management:

- **Policy listing** (`GET /api/v1/policies`): role-gated — `SECURITY_ADMIN` + `SECURITY_MANAGER` only. **Unchanged.**
- **Policy activation** (`POST /api/v1/policies/{id}/activate`): role-gated — `SECURITY_ADMIN` only. **Unchanged.**
- **Policy create** (`POST /api/v1/policies`): role-gated — `SECURITY_ADMIN` only. **NEW (F-1).**
- **Policy edit** (`PUT /api/v1/policies/{policy_id}`): role-gated — `SECURITY_ADMIN` only. **NEW (F-1).**
- **Policy detail** (`GET /api/v1/policies/{policy_id}`): role-gated — `SECURITY_ADMIN` + `SECURITY_MANAGER` only. **NEW (F-1).**

> **M11.3 note (Security Hardening, 2026-11-06).** Policy Create/Edit was
> deliberately **NOT** implemented in the M11.3 branch.  Security hardening
> and feature development are kept apart so that the hardening diff stays
> reviewable and no new authorisation surface is introduced while the
> existing one is being verified.  The item is carried in the implementation
> backlog below as **F-1** and is to be implemented as a separate
> feature branch, with the same role matrix the listing/activation
> endpoints already enforce.

> **F-1 note (2026-11-07).** F-1 is implemented on the feature branch
> `feature/f1-policy-crud`. The listing and activation contracts are
> untouched; only the new endpoints were added.

### 10.5 Create/Edit Contract (F-1)

#### 10.5.1 Endpoints

| Method | Path | Role | Success | Errors |
|--------|------|------|---------|--------|
| `GET` | `/api/v1/policies` | `SECURITY_ADMIN` + `SECURITY_MANAGER` | `200 OK` + list of summaries | `401` unauthenticated, `403` wrong role |
| `GET` | `/api/v1/policies/{policy_id}` | `SECURITY_ADMIN` + `SECURITY_MANAGER` | `200 OK` + `PolicyDetail` | `401` unauthenticated, `403` wrong role, `404` unknown policy |
| `POST` | `/api/v1/policies` | `SECURITY_ADMIN` | `201 Created` + `PolicyDetail` | `400` invalid rules/config, `400` client-set server-owned field, `400`/`422` invalid `version` format, `409` duplicate `version`, `401` unauthenticated, `403` wrong role |
| `PUT` | `/api/v1/policies/{policy_id}` | `SECURITY_ADMIN` | `200 OK` + `PolicyDetail` | `400` invalid rules/config, `400` client-set server-owned field, `400`/`422` unknown field, `400`/`422` `version` change attempt, `409` policy immutable, `409` stale concurrency token, `409` duplicate `version`, `409` concurrent insert conflict, `404` unknown policy |

> The listing (`GET /api/v1/policies`) and the activation
> (`POST /api/v1/policies/{id}/activate`) rows are the **pre-existing**
> contracts and are unchanged by F-1.

#### 10.5.2 Lifecycle and immutability rules

- A policy is **mutable only while it is a draft**: `is_active is False` **and**
  `activated_at is None`.
- Once a policy has been activated, `activated_at` is set and **never cleared**.
  Any policy with `is_active is True` **or** `activated_at is not None` is
  **frozen**: an edit attempt returns `409 Conflict` ("Policy is immutable").
- **`version` is immutable once created.** Changing the rules or the config of a
  deployed policy is done by creating a *new* version and activating it. The
  `version` field is rejected on the update endpoint.
- `version` is **unique** across the Detection context.
- This is what protects the history of previously processed login attempts:
  `risk_assessments` and `login_attempts` rows reference the policy that was
  active at the time, and that policy's rules/config never change afterwards.

#### 10.5.3 Create semantics

- The server always creates the policy **inactive** (`is_active=False`,
  `activated_at=None`). The client cannot set `is_active`.
- `created_by` is taken from the authenticated session (`ctx.user.id`); the
  client cannot set it. It is stored as a UUID reference inside the Detection
  context — **no write to the Core or ML database is performed**.
- `created_at` and `updated_at` are set by the server; the client cannot set
  them.
- Rules and config are validated with the canonical `validate_rule()` and
  `resolve_config()` from the Detection engine, so the create endpoint
  accepts exactly the six approved features and the approved operators, and
  rejects invalid weights, thresholds and rule structures.
- Validation failures return `400` with
  `{"detail": {"message": "Policy is invalid", "problems": [...]}}` — the same
  error contract the activation endpoint already uses.
- Server-owned fields that the client tries to set are reported explicitly with
  `400` ("`<field>` is managed by the server and cannot be set by the client");
  an unknown field (a typo) is rejected by the schema with `422`.

#### 10.5.4 Edit semantics and lost-update prevention

- `PUT /api/v1/policies/{policy_id}` requires `expected_updated_at` (the
  `updated_at` the client last read) in the request body.
- The row is locked with `SELECT ... FOR UPDATE`; if the stored `updated_at`
  differs from `expected_updated_at`, the request returns `409 Conflict`
  ("Policy was modified by someone else"). This makes a lost update impossible:
  the second writer of a concurrent pair always sees `409`.
- The **immutability check runs before the concurrency check**, so that a frozen
  policy always reports `409` ("Policy is immutable") rather than a spurious
  concurrency conflict caused by the `updated_at` bump of an activation.
- Fields that the client omits are preserved; `rules` and `config` are replaced
  as a whole when provided.

#### 10.5.5 Bounded-context isolation

All three F-1 endpoints use only the Detection database session. They never
write to the Core context (`users`, `sessions`, `audit_logs`) nor to the ML
context (`model_versions`, `inference_logs`, `feature_statistics`). The detail
endpoint is a **pure read**: it opens no transaction that writes and it does not
touch the scoring path.

#### 10.5.6 The detail endpoint (`GET /api/v1/policies/{policy_id}`)

The detail endpoint is a **supporting endpoint for the edit endpoint**. It does
**not** extend the policy lifecycle.

- **Why it exists.** The listing endpoint returns a *summary* (it deliberately
  does not expose the rules or the config), and the create/edit endpoints
  return the full payload only to the caller that just wrote. A client that
  wants to edit a policy therefore had **no way to read the current state**,
  and hence no way to obtain the `updated_at` token the edit endpoint
  requires. The detail endpoint closes that gap.
- **What it returns.** The existing `PolicyDetail` model — exactly the same
  payload the create and edit endpoints already return: `id`, `version`,
  `name`, `description`, `rules`, `config`, `is_active`, `created_by`,
  `created_at`, `updated_at`, `activated_at`, `deactivated_at`.
- **Authorisation.** `SECURITY_ADMIN` and `SECURITY_MANAGER` only (the same
  matrix the listing endpoint enforces). `SOC_ANALYST` and `USER` get `403`;
  an unauthenticated request gets `401`; an unknown `policy_id` gets `404`.
- **Timestamp precision.** `updated_at` is returned with full microsecond
  precision, so the value can be sent straight back as `expected_updated_at`
  without a lossy round trip. A truncated token would be rejected by the edit
  endpoint for a reason the client cannot see.
- **What it does NOT do.** It never writes, it never activates, it never
  changes how a policy is scored, and it never alters the historical
  `risk_assessments` / `login_attempts` rows. Reading a policy that has
  already been active is a plain read of a frozen row.

---

## 11. Implementation Backlog

The following are NOT part of the v3.3 baseline. They are recorded for
completeness.

| ID | Item | Priority | Notes |
|----|------|---------|-------|
| F-1 | ~~Policy create/edit endpoints~~ | — | ✅ RESOLVED in F-1 (2026-11-07) — `POST /api/v1/policies`, `GET /api/v1/policies/{policy_id}` and `PUT /api/v1/policies/{policy_id}`, with `SECURITY_ADMIN` owning create/edit, `SECURITY_MANAGER` view-only, draft-only mutability, `version` uniqueness and immutability, optimistic concurrency via `expected_updated_at`, and Detection-context-only writes. See Section 10.5. |
| ~~P1-E~~ | ~~CORS policy~~ | — | ✅ RESOLVED in M11.3 — `app/cors_config.py` replaces the wildcard with a configurable allow-list (`CORS_ALLOWED_ORIGINS`); the deployment script and the application refuse a wildcard. |
| ~~P1-F~~ | ~~Refresh-token concurrency~~ | — | ✅ RESOLVED in M11.3 — the refresh endpoint rotates the stored hash inside the session row, so a second use of the same refresh token cannot mint a second live session (verified against real concurrent transactions). |
| P1-G | Outbox publisher runtime | High | Event delivery reliability |
| P1-H | Reconciliation scheduler | Medium | Missed event recovery |
| P1-B | ~~SOC action workflow~~ | — | ✅ RESOLVED — direct-apply (see Section 9) |
| P1-C | ~~Policy management roles~~ | — | ✅ RESOLVED — Security Admin only (see Section 10) |
| — | Role-gated protective actions | High | Enforce executor role on `POST /internal/detection/actions` |
| — | ~~Role-gated policy management~~ | — | ✅ RESOLVED in F-1 — the Security Admin role is enforced on the policy CRUD endpoints (see Section 10.1 / 10.5). |
| — | Token introspection endpoint | Low | Future cross-service auth |
| — | Three independent services | High | Current monolith split |

---

*This document is the Level 1 system architecture authority for Sentinel Auth v3.3.
Approved on 2026-10-09.*
