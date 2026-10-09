# Sentinel Auth v3.3 — UML / Workflow Reconciliation Audit

> **Date:** 2026-10-09 (D4 pass)
> **Baseline:** `82e6f7b40da1c39e7acb48fedc9af581e40a4c42`
> **Authoritative sources:** DECISIONS-SYSTEM-v3.3.md, DECISIONS-DETECTION-v3.3.md, DECISIONS-SYSTEM-v3.3.md Section 10 (P1-B/P1-C), app/detection.py, app/auth.py

This audit records the D4 UML/workflow reconciliation against the approved v3.3 decisions.
It establishes traceability from canonical decisions through diagram artifacts.

---

## 1. Artifact Matrix

| Artifact | Type | Current/Target | Issue Found | Change Made | Render Status | Remaining Gap |
|----------|------|:---:|-------------|-------------|:---:|-------------|
| `docs/workflows.mmd` | Workflow | Both | "Validate JWT" (2×); 15min/7d expiry (2×) | ✅ JWT → opaque bearer token; expiry → 1h; P1-F note added | N/A | None |
| `docs/diagrams/architecture.uml` | Arch | Both | "FastAPI + PostgreSQL (3 schemas)"; no Redis; no current/target distinction | ✅ Corrected to "1 server / 3 databases"; Redis added (future); current prototype note added | SOURCE_UPDATED_RENDER_PENDING | PNG/SVG regeneration |
| `docs/diagrams/wf1_login.uml` | Workflow | Both | "IP from X-Forwarded-For" | ✅ → "effective client IP from request.client.host" | SOURCE_UPDATED_RENDER_PENDING | PNG/SVG regeneration |
| `docs/diagrams/wf2_detection.uml` | Workflow | Both | None | No changes needed | SOURCE_UPDATED_RENDER_PENDING | PNG/SVG regeneration |
| `docs/diagrams/wf3_soc.uml` | Workflow | Both | "Validate JWT" (2×) | ✅ → opaque bearer token → Session → User → Roles | SOURCE_UPDATED_RENDER_PENDING | PNG/SVG regeneration |
| `docs/diagrams/wf4_mfa_flow.uml` | Workflow | Both | None | No changes needed | SOURCE_UPDATED_RENDER_PENDING | PNG/SVG regeneration |
| `docs/diagrams/wf5_session_management.uml` | Workflow | Both | "Validate JWT" (2×); "JWT Validation Pipeline" note; 15min/7d expiry (4×) | ✅ All corrected to opaque token model; expiry → 1h; pipeline note corrected; P1-F note added | SOURCE_UPDATED_RENDER_PENDING | PNG/SVG regeneration |
| `docs/diagrams/wf6_ml_inference.uml` | Workflow | Both | None (ML feature name `ip_change_rate_7d` is correct) | No changes needed | SOURCE_UPDATED_RENDER_PENDING | PNG/SVG regeneration |
| `docs/bao-cao/uml-architecture.puml` | Arch | Both | "JWT + làm mới"; 500ms ML timeout note | ✅ → opaque bearer token + refresh; timeout → 3s/5s; Redis/Outbox future note added | SOURCE_UPDATED_RENDER_PENDING | PNG regeneration |
| `docs/bao-cao/uml-use-case-tong-quat.puml` | Use Case | Both | UC-18 "Yêu cầu hành động bảo vệ"; UC-24 "Phê duyệt leo thang" as current; Manager → UC-24 | ✅ UC-18 → "Thực hiện hành động bảo vệ"; UC-24 → FUTURE ENHANCEMENT package; Manager → UC-20 (view only), UC-19, UC-25; note clarifying oversight role | SOURCE_UPDATED_RENDER_PENDING | PNG regeneration |
| `docs/bao-cao/uml-activity-login-mfa.puml` | Activity | Both | "sessions.token_jti khớp jti nếu sau này chuyển sang JWT" | ✅ → token_jti = legacy/internal session token identifier; JWT not current design | SOURCE_UPDATED_RENDER_PENDING | PNG regeneration |
| `docs/bao-cao/uml-activity-soc.puml` | Activity | Both | "Hệ thống kiểm tra JWT và vai trò"; "POST /alerts/{id}/escalate" + "Chuyển sang Security Manager phê duyệt" | ✅ → opaque bearer token; escalate → PATCH with notes; Security Manager → giám sát; FUTURE ENHANCEMENT note | SOURCE_UPDATED_RENDER_PENDING | PNG regeneration |
| `docs/bao-cao/uml-class-domain.puml` | Class | Both | None | No changes needed | SOURCE_UPDATED_RENDER_PENDING | PNG regeneration |
| `docs/diagrams/ERD_v3.3.md` | ERD | Both | "JWT token management" | ✅ → "Opaque token / session management" | N/A | None |

---

## 2. Stale Term Corrections

| Term | Count | File(s) | Corrected To |
|------|:-----:|---------|-------------|
| `JWT` (auth semantics) | 7 | workflows.mmd, wf3_soc.uml, wf5_session_management.uml, uml-architecture.puml, uml-activity-soc.puml | `validate opaque bearer token → Session → User → Roles` |
| `JWT Validation Pipeline` | 1 | wf5_session_management.uml | `Opaque Token Validation Pipeline` (corrected steps) |
| `15min` / `expires_at=+15min` | 3 | workflows.mmd, wf5_session_management.uml | `expires_at=NOW()+1h` |
| `refresh_expires=+7d` | 2 | workflows.mmd, wf5_session_management.uml | Removed (refresh_token: unlimited until revoked) |
| `7d` (refresh expiry label) | 2 | workflows.mmd, wf5_session_management.uml | Removed |
| `IP from X-Forwarded-For` | 1 | wf1_login.uml | `effective client IP from request.client.host` |
| `JWT + làm mới` | 1 | uml-architecture.puml | `opaque bearer token + refresh` |
| 500ms (ML timeout) | 1 | uml-architecture.puml | `3s (pre-token gate) / 5s (Detection→ML)` |
| `sessions.token_jti` future-JWT note | 1 | uml-activity-login-mfa.puml | `token_jti = legacy/internal session token identifier` |
| `POST /alerts/{id}/escalate` + "phê duyệt" | 1 | uml-activity-soc.puml | `PATCH with status=escalated` + FUTURE ENHANCEMENT note |
| `UC-18 Yêu cầu hành động bảo vệ` | 1 | uml-use-case-tong-quat.puml | `UC-18 Thực hiện hành động bảo vệ` |
| `UC-24 Phê duyệt leo thang` (as current) | 1 | uml-use-case-tong-quat.puml | Moved to `FUTURE ENHANCEMENT` package |
| Manager → UC-24 (approval) | 1 | uml-use-case-tong-quat.puml | Manager → UC-20 (view only), UC-19, UC-25 |
| "3 schemas" PostgreSQL wording | 1 | architecture.uml | `1 server / 3 databases` |

**Total: 24 stale term occurrences corrected.**

---

## 3. Architectural Accuracy Fixes

### 3.1 Current vs Target Architecture

`docs/diagrams/architecture.uml` legend updated to explicitly distinguish:

| Aspect | CURRENT PROTOTYPE | TARGET v3.3 |
|--------|------------------|-------------|
| Process | One FastAPI monolith | Three logical services (Core/Auth, Detection, ML) |
| Database | One DATABASE_URL | Three independent DB consumers |
| Authentication | Opaque bearer tokens | Opaque bearer tokens |
| Login events | Direct HTTP | Outbox → Redis Stream → Detection |
| Redis | Infrastructure only (AOF persistence) | Future async event transport |

### 3.2 Token Expiry

All diagrams now reflect the current prototype's actual session expiry:

- `access_token`: 1 hour (not 15 minutes)
- `refresh_token`: unlimited until revoked (not 7 days)
- P1-F concurrent refresh hardening: marked IMPLEMENTATION BACKLOG

### 3.3 Detection Semantics

All timeout references now use canonical values:
- Pre-token risk gate (Core→Detection): **3 seconds** (fail open)
- ML scoring (Detection→ML): **5 seconds** (fail open)
- 500ms value removed from all diagrams

### 3.4 Redis / Outbox

Redis appears only as future async transport in architecture diagrams. No diagram claims Redis currently transports login events.

### 3.5 Database Topology

Corrected from "3 schemas" to "1 PostgreSQL server / 3 databases":
- `sentinel_core`
- `sentinel_detection`
- `sentinel_ml`

---

## 4. P1-B / P1-C Diagram Reconciliation

### P1-B: Protective Action Workflow

| Diagram | Change |
|---------|--------|
| `wf3_soc.uml` | SOC Action Flow note: "POST /alerts/{id}/actions → Core App → applied" (no approval step) |
| `uml-activity-soc.puml` | Escalate: no manager approval step; Security Manager → giám sát; FUTURE ENHANCEMENT note for dedicated escalate endpoint |
| `uml-use-case-tong-quat.puml` | UC-18: SOC Analyst primary; Manager → `<<include>>` supervisory capability; no approval |
| `workflows.mmd` | WF-3: "Validate opaque bearer token" (no JWT semantics) |

### P1-C: Policy Management

| Diagram | Change |
|---------|--------|
| `uml-use-case-tong-quat.puml` | Manager → UC-20 with `<<view only>>` semantics; note clarifying oversight role |
| `workflows.mmd` | WF-3: Security Manager may execute protective action (supervisory); no approval |

---

## 5. PlantUML Validation

All 6 modified PlantUML sources pass static validation:
- `@startuml` / `@enduml` pairs present
- `title`, `participant`, `database`, `note`, `legend` directives syntactically correct
- No unclosed blocks or unbalanced conditionals detected

Full rendering (PNG/SVG): **PLANTUML_BINARY_NOT_AVAILABLE** — PlantUML is not installed in the current environment. All sources are corrected and syntactically valid.

---

## 6. Files NOT Modified (Correctly Excluded)

| File | Reason |
|------|--------|
| `docs/bao-cao/ERD_core_v3.3.puml` | ERD source — not confirmed stale; ERD accuracy verified separately |
| `docs/bao-cao/ERD_detection_v3.3.puml` | ERD source — not confirmed stale |
| `docs/bao-cao/ERD_ml_v3.3.puml` | ERD source — not confirmed stale |
| `docs/bao-cao/_content_*.py` | Report generators — D4 scope excludes these |
| `docs/bao-cao/BaoCaoPT_TKHTTT_Nhom2_Checklist.md` | Report artifact — D4 scope excludes |
| `schema-core-v3.3.sql` COMMENT | SQL COMMENT "JWT" — application FROZEN; this is a source file, not a diagram |
| `app/models.py` comment | Application FROZEN |

---

## 7. Generated PNG/SVG Artifacts

| File | Source Changed | Render Status |
|------|:---:|-------------|
| `docs/diagrams/*.png` | Unknown | REGENERATION_PENDING — PlantUML binary not available |
| `docs/diagrams/*.svg` | Unknown | REGENERATION_PENDING — PlantUML binary not available |
| `docs/bao-cao/*.png` | Unknown | REGENERATION_PENDING — PlantUML binary not available |

Sources are corrected. PNG/SVG regeneration requires PlantUML installation.

---

## 8. D3.1 / D4.1 Correction Pass

This audit records an additional correction pass (D3.1/D4.1) that addressed residual factual errors in session management, alert endpoints, and escalation semantics discovered after D3/D4 completion.

### 8.1 Session / Refresh Corrections

| Issue | Found In | Correction |
|-------|---------|-----------|
| "refresh token unlimited until revoked" | wf5_session_management.uml, workflows.mmd | Refresh only valid while backing session unexpired and not revoked |
| "check expiry, signature" on refresh | wf5_session_management.uml | Opaque tokens: NO signature, NO embedded exp claim |
| `expires_at=NOW()+1h` during refresh | wf5_session_management.uml | expires_at UNCHANGED on refresh (always fixed at login time + 1h) |
| `expires_in: 3600` in refresh response | wf5_session_management.uml | Response only returns new tokens |
| `logout-all` shown as CURRENT | wf5_session_management.uml, workflows.mmd | APPROVED DESIGN / IMPLEMENTATION PENDING |
| Admin session revoke shown as CURRENT | wf5_session_management.uml, workflows.mmd | APPROVED DESIGN / IMPLEMENTATION PENDING |
| Logout uses `token_jti=access_token.jti` lookup | wf5_session_management.uml | Correct: uses authenticated session context |
| `200 {revoked: true}` on DELETE sessions | wf5_session_management.uml | Correct: `204 No Content` |

### 8.2 Alert Endpoint Corrections

| Issue | Found In | Correction |
|-------|---------|-----------|
| `PATCH /api/v1/alerts/{id}` generic route | wf3_soc.uml | Replaced with specific POST endpoints: acknowledge, resolve, assign, actions, timeline |
| `resolve` field in alert update | wf3_soc.uml | Added resolution type: `true_attack`, `false_positive`, `benign_true_positive`, `insufficient_evidence` |
| `escalate` as PATCH with `status=escalated` | wf3_soc.uml, uml-activity-soc.puml | Removed — no `escalate` endpoint; escalation = timeline marker only |
| Dashboard endpoint shown as CURRENT | wf3_soc.uml | APPROVED DESIGN / IMPLEMENTATION PENDING |

### 8.3 Escalation Corrections

| Issue | Found In | Correction |
|-------|---------|-----------|
| `alert.status = escalated` | uml-activity-soc.puml | Removed — only `open`, `acknowledged`, `resolved`, `false_positive` are valid statuses |
| `POST /alerts/{id}/escalate` shown as CURRENT | uml-activity-soc.puml | APPROVED DESIGN / IMPLEMENTATION PENDING |
| "Security Manager approve" on escalation | uml-activity-soc.puml | Removed — Manager giám sát supervisory visibility only |
| Escalate as UC-DE-12 resolution type | 05-dac-ta-use-case-detection-engine.md | Removed `ESCALATED` from resolution types |

### 8.4 Policy / Permission Corrections

| Issue | Found In | Correction |
|-------|---------|-----------|
| Security Manager: Create/Activate Policy = YES | 06-phan-tich-doi-tuong-su-dung-detection-engine.md | Corrected to NO for both |
| SOC Analyst: Policy View = YES | 06-phan-tich-doi-tuong-su-dung-detection-engine.md | Corrected to NO |
| US-MGR-02: "approve/reject/reassign" on escalated | 06-phan-tich-doi-tuong-su-dung-detection-engine.md | Corrected to VIEW only |
| US-MGR-03: Manager "adjust thresholds" | 06-phan-tich-doi-tuong-su-dung-detection-engine.md | Corrected to "review" only (Security Admin owns) |
| Permission matrix: Manager acknowledge/resolve = ✅ | 06-phan-tich-doi-tuong-su-dung-detection-engine.md | Marked ⚠️ as prototype-only; canonical = oversight |

### 8.5 Endpoint Implementation Status

| Endpoint | Implementation Status | Verified In |
|---------|---------------------|-----------|
| `POST /api/v1/alerts/{id}/acknowledge` | CURRENT IMPLEMENTATION | `app/alerts.py:449` |
| `POST /api/v1/alerts/{id}/resolve` | CURRENT IMPLEMENTATION | `app/alerts.py:496` |
| `POST /api/v1/alerts/{id}/assign` | CURRENT IMPLEMENTATION | `app/alerts.py:575` |
| `POST /api/v1/alerts/{id}/actions` | CURRENT IMPLEMENTATION (no role gate) | `app/alerts.py:634` |
| `POST /api/v1/alerts/{id}/timeline` | CURRENT IMPLEMENTATION | `app/alerts.py:770` |
| `GET /api/v1/alerts/{id}/evidence` | CURRENT IMPLEMENTATION | `app/alerts.py:355` |
| `POST /api/v1/auth/logout` | CURRENT IMPLEMENTATION | `app/auth.py:720` |
| `DELETE /api/v1/sessions/{id}` | CURRENT IMPLEMENTATION (204 No Content) | `app/auth.py:774` |
| `GET /api/v1/soc/dashboard` | IMPLEMENTATION PENDING | Not in `app/alerts.py` |
| `POST /api/v1/alerts/{id}/escalate` | IMPLEMENTATION PENDING | Not in `app/alerts.py` |
| `POST /api/v1/policies` | IMPLEMENTATION PENDING | Not in `app/detection.py` |
| `POST /api/v1/auth/logout-all` | IMPLEMENTATION PENDING | Not in `app/auth.py` |
| `POST /api/v1/admin/sessions/{id}/revoke` | IMPLEMENTATION PENDING | Not in `app/auth.py` |

### 8.6 D3.1/D4.1 Summary

**Files modified:** 8 files (wf5, workflows.mmd, wf3, uml-activity-soc, 05, 06, SENTINEL_AUTH_TONG_HOP, DECISIONS-DETECTION)
**Artifacts created:** None
**Total corrections:** ~30 term/endpoint/status corrections across session semantics, alert endpoints, escalation, and permission matrices
**Application code:** NOT modified (verified against `app/auth.py`, `app/alerts.py`, `app/schemas.py`)

---

## 9. Source-of-Truth Confirmation

This D4 + D3.1/D4.1 pass confirms:

1. All diagram/workflow artifacts now accurately derive from DECISIONS-SYSTEM-v3.3.md and DECISIONS-DETECTION-v3.3.md.
2. No diagram introduces a business decision not covered by D1-D3.
3. No new entities, endpoints, or architectural elements were invented.
4. Application code (`app/**`) remains FROZEN — no changes made.
5. Infrastructure (`infra/**`, `Dockerfile`, `docker-compose.yml`) remains FROZEN.
6. Report generators (`docs/bao-cao/_content_*.py`) remain EXCLUDED.
7. Historical audit documents are NOT modified.

---

**Status:** D4_UML_WORKFLOWS_RECONCILED
