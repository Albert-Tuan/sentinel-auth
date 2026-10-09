# Sentinel Auth v3.3 — Requirements / Use-Case Reconciliation Audit

> **Date:** 2026-10-09 (D3 pass)
> **Baseline:** `e4001f35b88f0ba34ca0586bc2f5239d81fe6891`
> **Authoritative sources:** DECISIONS-SYSTEM-v3.3.md, DECISIONS-DETECTION-v3.3.md, TASK_ASSIGNMENT.md, SQL schemas, app/detection.py

This audit records the D3 requirements/use-case reconciliation against the approved
v3.3 system decisions. It establishes traceability from canonical decisions through
downstream documents and identifies remaining gaps.

---

## 1. Traceability Matrix

### 1.1 Token Model

| Topic | Canonical Decision | Source | Affected Docs |
|-------|-----------------|--------|---------------|
| Authentication mechanism | Opaque random bearer tokens (not JWT) | DECISIONS-SYSTEM-v3.3.md Section 1 | All use-case and requirements docs |
| Token storage | SHA-256 hash in `sessions` table | DECISIONS-SYSTEM-v3.3.md Section 1.2 | `schema-core-v3.3.sql` |
| Session→User→Roles authorization | Bearer token carries session; roles from DB | DECISIONS-SYSTEM-v3.3.md Section 3 | `app/detection.py`, use-case docs |

### 1.2 Actor Model

| Role | Canonical Business Responsibility | Source |
|------|----------------------------------|--------|
| `USER` | Normal system usage (login, MFA, session management) | DECISIONS-SYSTEM-v3.3.md, DECISIONS-DETECTION-v3.3.md |
| `SOC_ANALYST` | Operational security response (primary operational actor for alert handling) | DECISIONS-SYSTEM-v3.3.md Section 9 |
| `SECURITY_ADMIN` | Technical security administration (account/role/policy/audit administration) | DECISIONS-SYSTEM-v3.3.md Section 10 |
| `SECURITY_MANAGER` | Oversight, governance, reporting, supervisory visibility | DECISIONS-SYSTEM-v3.3.md Section 10 |

### 1.3 Protective Action Authorization (P1-B / P1-J)

| Topic | Canonical Decision | Source |
|-------|-----------------|--------|
| Workflow | Direct-apply (no approval queue) | DECISIONS-SYSTEM-v3.3.md Section 9 |
| Primary executor | SOC Analyst | DECISIONS-SYSTEM-v3.3.md Section 9.2 |
| Secondary executor | Security Manager (supervisory capability) | DECISIONS-SYSTEM-v3.3.md Section 9.2 |
| Supported actions | REQUIRE_MFA, REVOKE_SESSIONS, LOCK_USER, FORCE_LOGOUT | DECISIONS-SYSTEM-v3.3.md Section 9.2 |
| Approval workflow | NOT PART OF v3.3 — FUTURE ENHANCEMENT | DECISIONS-SYSTEM-v3.3.md Section 9.1 |
| `APPROVE_ACTION` | STALE — not in v3.3 | DECISIONS-SYSTEM-v3.3.md Section 9.1 |

### 1.4 Policy Management Authorization (P1-C / P1-K)

| Role | View | Create | Edit | Activate |
|------|------|--------|------|----------|
| `SECURITY_ADMIN` | ✅ YES | ✅ YES | ✅ YES | ✅ YES |
| `SECURITY_MANAGER` | ✅ YES (VIEW_POLICIES) | ❌ NO | ❌ NO | ❌ NO |
| `SOC_ANALYST` | ❌ NO | ❌ NO | ❌ NO | ❌ NO |

Source: DECISIONS-SYSTEM-v3.3.md Section 10.1.

### 1.5 Database Topology

| Topic | Canonical Decision | Source |
|-------|-----------------|--------|
| PostgreSQL servers | **one** PostgreSQL server | DECISIONS-SYSTEM-v3.3.md Section 4 |
| Logical databases | three: `sentinel_core`, `sentinel_detection`, `sentinel_ml` | DECISIONS-SYSTEM-v3.3.md Section 4 |
| sentinel_core | 13 base tables | Runtime verified |
| sentinel_detection | 7 base tables | Runtime verified |
| sentinel_ml | 3 base tables + 1 view (`local_ml_stats`) | Runtime verified |
| Cross-database references | Application-level (same UUID); NOT PostgreSQL FK | DECISIONS-SYSTEM-v3.3.md Section 4 |
| Per-service DB credentials | FUTURE HARDENING — not in v3.3 baseline | DECISIONS-SYSTEM-v3.3.md Section 4 |

### 1.6 Redis / Outbox

| Topic | Canonical Decision | Source |
|-------|-----------------|--------|
| Redis role | Future asynchronous event transport (Redis Streams) | DECISIONS-SYSTEM-v3.3.md Section 5 |
| PostgreSQL role | Authoritative data store — always | DECISIONS-SYSTEM-v3.3.md Section 5 |
| Outbox pattern | APPROVED DESIGN | DECISIONS-SYSTEM-v3.3.md Section 6 |
| Outbox publisher | NOT IMPLEMENTED — writes direct HTTP | DECISIONS-SYSTEM-v3.3.md Section 6 |
| Redis Streams consumer | NOT IMPLEMENTED | DECISIONS-SYSTEM-v3.3.md Section 6 |
| Login event delivery | Direct HTTP where implemented | DECISIONS-SYSTEM-v3.3.md Section 6 |

### 1.7 Architecture

| Topic | Canonical Decision | Source |
|-------|-----------------|--------|
| Current implementation | single FastAPI monolith | DECISIONS-SYSTEM-v3.3.md Section 7 |
| Target v3.3 architecture | Core/Auth, Detection Engine, ML Service as independently deployable | DECISIONS-SYSTEM-v3.3.md Section 7 |
| Service separation | Logical — not currently deployed as independent services | DECISIONS-SYSTEM-v3.3.md Section 7 |

### 1.8 MFA

| Channel | Status | Source |
|---------|--------|--------|
| Email OTP (one-time via MFA transaction) | CURRENT IMPLEMENTATION | `schema-core-v3.3.sql`, `app/auth.py` |
| Email OTP (persistent/admin) | CURRENT IMPLEMENTATION | `schema-core-v3.3.sql`, `app/auth.py` |
| TOTP (authenticator app) | DESIGN / NOT IMPLEMENTED | Historical design docs |
| SMS OTP | DESIGN / NOT IMPLEMENTED | Historical design docs |
| Push notification | DESIGN / NOT IMPLEMENTED | Historical design docs |

### 1.9 Detection Semantics

| Topic | Canonical Decision | Source |
|-------|-----------------|--------|
| Rule weight | 0.4 | DECISIONS-DETECTION-v3.3.md Section 2 |
| ML weight | 0.6 | DECISIONS-DETECTION-v3.3.md Section 2 |
| High threshold | ≥ 0.50 → REQUIRE_MFA | DECISIONS-DETECTION-v3.3.md Section 2 |
| Critical threshold | ≥ 0.75 → REVOKE_SESSIONS | DECISIONS-DETECTION-v3.3.md Section 2 |
| Pre-token risk call | 3-second timeout, fail open | DECISIONS-DETECTION-v3.3.md Section 10 |
| ML call timeout | 5-second timeout, fail open | DECISIONS-DETECTION-v3.3.md Section 10 |

### 1.10 Trusted Client IP

| Topic | Canonical Decision | Source |
|-------|-----------------|--------|
| IP resolution | `app/client_ip.get_client_ip()` → `request.client.host` | DECISIONS-SYSTEM-v3.3.md Section 3 |
| Proxy headers | Delegated to configured uvicorn `proxy headers` setting | DECISIONS-SYSTEM-v3.3.md Section 3 |
| Unsafe raw XFF trust | NOT part of v3.3 design | P1-D resolved |

---

## 2. Document Changes Summary

| File | Changes Made | Rationale |
|------|-------------|-----------|
| `docs/DECISIONS-SYSTEM-v3.3.md` | Section 10.4 corrected implementation note; Section 10.3 rationale updated | Facts vs. outdated claim |
| `docs/02-dac-ta-use-case-core-app.md` | All "JWT" → "opaque access token" / "bearer token" (11 occurrences); X-Forwarded-For clarified | JWT not part of v3.3 |
| `docs/03-phan-tich-doi-tuong-su-dung-phan-mem-core-app.md` | JWT → opaque bearer token (4 occurrences); outbox → APPROVED DESIGN/IMPLEMENTATION PENDING; flow diagram updated | Corrected token + outbox status |
| `docs/03-bang-yeu-cau-chuc-nang-nghiep-vu-ml-service.md` | JWT → opaque bearer token (1 occurrence) | ML service uses shared secret, not user tokens |
| `docs/DECISIONS-DETECTION-v3.3.md` | JWT → opaque bearer token (2 occurrences); internal header clarified | ML service context clarified |
| `docs/04-bang-yeu-cau-chuc-nang-nghiep-vu-detection-engine.md` | "Action Request to Core" → "Thực hiện hành động bảo vệ" (DE-16) | P1-B reconciliation |
| `docs/05-dac-ta-use-case-detection-engine.md` | UC-DE-13: "Yêu cầu Action" → "Thực hiện hành động bảo vệ"; approval queue → FUTURE ENHANCEMENT; UC-DE-15 role matrix added; SOC_ANALYST policy access → NO | P1-B and P1-C reconciliation |
| `docs/06-phan-tich-doi-tuong-su-dung-detection-engine.md` | `REQUEST_ACTION` → `EXECUTE_ACTION`; `APPROVE_ACTION` → STALE; `MANAGE_POLICIES` → `VIEW_POLICIES`; US-SOC-04 story updated | P1-B and P1-C reconciliation |
| `docs/SENTINEL_AUTH_TONG_HOP_v3.3.md` | JWT → opaque bearer token (SESSIONS); OUTBOX → APPROVED DESIGN/IMPLEMENTATION PENDING; UC-DE-13 name updated; ADR-002 clarified | Multiple reconciliations |

---

## 3. Known Implementation Gaps

These are not D3 decisions — they are recorded for the next implementation phase.

| Gap | Description | Canonical Source |
|-----|-------------|-----------------|
| Role-gated protective actions | `POST /internal/detection/actions` has no role verification on executor | DECISIONS-SYSTEM-v3.3.md Section 9.4 |
| Policy create/edit endpoints | No dedicated create or edit endpoints for policies | DECISIONS-SYSTEM-v3.3.md Section 10.4 |
| Outbox publisher | No poller reads outbox_events; events may be lost | DECISIONS-SYSTEM-v3.3.md Section 11 |
| Redis Streams consumer | Detection does not consume Redis Streams | DECISIONS-SYSTEM-v3.3.md Section 11 |
| Three independent services | Core, Detection, ML not yet independently deployable | DECISIONS-SYSTEM-v3.3.md Section 11 |
| TOTP/SMS/Push MFA | Email OTP only in current implementation | Design docs / schema |

---

## 4. Documents NOT Modified (Correctly Excluded)

These are not modified in D3. They belong to D4 (diagrams) or R1 (report):

- `docs/workflows.mmd` — Workflows (D4)
- `docs/diagrams/*.uml`, `*.drawio`, `*.puml` — Diagrams (D4)
- `docs/bao-cao/` — Report artifacts (R1)
- `docs/01-bang-yeu-cau-chuc-nang-nghiep-vu-core-app.md` — No stale terms found
- `docs/04-dac-ta-use-case-ml-service.md` — No stale terms found
- `docs/05-phan-tich-doi-tuong-su-dung-ml-service.md` — No stale terms found

---

## 5. Remaining Stale References (Known, Not Modified in D3)

These files contain stale JWT references but are either:
- Historical audit documents (Level 6 — do not override Level 1 decisions)
- Application code comments (application FROZEN)
- Diagram sources (D4 pass)
- Report artifacts (R1 pass)

| File | Reference | Classification | Next Pass |
|------|-----------|----------------|-----------|
| `app/models.py` | `"""Active user sessions with JWT refresh tokens."""` | STALE (application FROZEN) | Application phase |
| `app/schemas.py` | `# Token / JWT schemas (for internal use)` | STALE (application FROZEN) | Application phase |
| `schema-core-v3.3.sql` | `SESSIONS (JWT Token Management)` COMMENT | STALE | D4 or R1 |
| `docs/bao-cao/uml-architecture.puml` | JWT references | STALE | D4 |
| `docs/diagrams/wf3_soc.uml` | `Validate JWT (role=SOC_ANALYST)` | STALE | D4 |
| `docs/diagrams/wf5_session_management.uml` | `Validate JWT` | STALE | D4 |
| `docs/workflows.mmd` WF-3 | `Validate JWT (role=SOC_ANALYST)` | STALE | D4 |
| `docs/audit/10-findings.md` – `docs/audit/14-p1-remediation.md` | Historical audit records (Level 6) | Historical | None — do not rewrite |
| `docs/bao-cao/BaoCaoPT_TKHTTT_Nhom2_Checklist.md` | Row 75: JWT TTL | STALE | R1 |
| `docs/bao-cao/ERD_Chen_v3.3.puml` | Likely JWT reference | STALE | D4 |
| `docs/diagrams/ERD_v3.3.md` | `JWT token management` | STALE | D4 |
| `docs/GUIDE-DETECTION-ENGINE.md` | `Authorization: Bearer {JWT}` | STALE | D4 |

---

## 6. Source-of-Truth Confirmation

This D3 pass confirms:

1. **DECISIONS-SYSTEM-v3.3.md** is the Level 1 authority for all system-wide decisions.
2. No document modified in D3 contradicts a Level 1 decision.
3. Implementation gaps are recorded accurately (not papered over).
4. Historical audit documents (Level 6) are not modified — they record findings.
5. Application code (app/**) is FROZEN — stale comments are recorded for a future application phase.
6. Diagram/report artifacts (D4/R1) are correctly excluded from D3 scope.

---

**Status:** D3_REQUIREMENTS_USECASES_RECONCILED
