# Tuấn Anh — Detection / SOC / Admin Assignment

**Branch:** `detection-engine`
**Bounded Context:** DETECTION / SOC
**Primary Business Role:** SOC_ANALYST
**Secondary Responsibility:** Detection-side Security Admin functions

---

## 1. Mission

Own and implement the Detection / SOC bounded context for Sentinel Auth v3.3.

You are responsible for: login event ingestion, feature construction, rule evaluation, ML client integration, risk scoring, alert creation/lifecycle, SOC workflow, protective action orchestration, and Detection-side Security Admin functions.

You do NOT own: Core authentication, user sessions, ML inference implementation, or Manager analytics.

---

## 2. Branch / Ownership

```
Branch: detection-engine
Start from: dev (latest approved baseline)
Primary service: Detection / SOC
Database: sentinel_detection (7 base tables)
```

---

## 3. Required Reading

Read in this order before starting implementation:

1. `docs/DECISIONS-SYSTEM-v3.3.md` — system-level decisions
2. `docs/DECISIONS-DETECTION-v3.3.md` — canonical detection decisions
3. `docs/04-bang-yeu-cau-chuc-nang-nghiep-vu-detection-engine.md` — functional requirements
4. `docs/05-dac-ta-use-case-detection-engine.md` — use case specifications
5. `docs/06-phan-tich-doi-tuong-su-dung-detection-engine.md` — actor analysis
6. `infra/postgres/schema-detection-v3.3.sql` — all 7 tables (see Section 6)
7. `docs/workflows.mmd` — WF-2 (Detection), WF-3 (SOC)
8. `docs/diagrams/wf2_detection.uml` — detection flow
9. `docs/diagrams/wf3_soc.uml` — SOC alert workflow
10. `docs/audit/17-requirements-usecase-reconciliation.md` — requirements reconciliation
11. `docs/audit/18-uml-workflow-reconciliation.md` — workflow reconciliation
12. `docs/assignments/CONTRACT_CORE_DETECTION.md` — Core↔Detection contract
13. `docs/assignments/CONTRACT_DETECTION_ML.md` — Detection↔ML contract

---

## 4. Business Responsibilities

### SOC Analyst (Primary Actor)

- View alerts (open, acknowledged, resolved, false_positive)
- View alert evidence (login attempt, risk assessment)
- Acknowledge alert (claim responsibility)
- Investigate (view timeline, add notes)
- Assign alert (transfer to another analyst)
- Resolve alert (with resolution text)
- Mark false positive
- Record timeline events
- View login history for investigation
- Trigger protective action

### Alert Statuses (ONLY these four)

| Status | Description |
|--------|-------------|
| `open` | New alert, no owner |
| `acknowledged` | Analyst claimed it |
| `resolved` | Issue resolved |
| `false_positive` | Not a real threat |

### Escalation (IMPORTANT)

- `ESCALATED` is **NOT** an alert status
- Escalation is recorded as `alert_timeline.event_type = 'escalated'` (supervisory marker)
- There is **no mandatory Manager approval queue**
- Dedicated escalation workflow/endpoint: **IMPLEMENTATION PENDING**

### Detection-Side Security Admin

| Operation | Security Admin | Security Manager | SOC Analyst |
|-----------|--------------|-----------------|-------------|
| View policies | YES | YES | NO |
| Create policy | YES | NO | NO |
| Edit policy | YES | NO | NO |
| Activate policy | YES | NO | NO |

**Note:** Current implementation has View + Activate. Create/Edit are **APPROVED DESIGN / IMPLEMENTATION PENDING**.

---

## 5. Technical Responsibilities

### Risk Scoring Pipeline (Canonical — DO NOT CHANGE without lead approval)

```
STEP 1 — rule_score (0..1)
  contribution(rule) = rule.score × rule.weight  for enabled+triggered rules
  rule_score = min(1.0, SUM(contribution) / SUM(weight of ALL enabled rules))

STEP 2 — ml_score (0..1, NULL when unavailable)
  ml_score = normalized_anomaly_score from ML Service
  ml_status = 'success' | 'unavailable' (timeout > 5s) | 'error'

STEP 3 — combined_score (0..1)
  if ml_status = 'success':  combined = 0.4 × rule_score + 0.6 × ml_score
  otherwise:                  combined = rule_score  (graceful degradation)

STEP 4 — risk_level from config thresholds
  combined < 0.25  →  low
  0.25 ≤ combined < 0.50  →  medium
  0.50 ≤ combined < 0.75  →  high
  combined ≥ 0.75  →  critical

STEP 5 — decision
  low, medium  →  'allow'     (no alert)
  high         →  'challenge'  (REQUIRE_MFA, alert created)
  critical     →  'block'     (LOCK_USER/REVOKE_SESSIONS, alert created)
```

### ML Timeout
- **5 seconds** — if ML does not respond within 5 seconds, treat as `ml_status = 'unavailable'` and fall back to rule_score only

### Six Canonical Features

These are the ONLY features used for scoring. Do NOT add or remove features without lead approval:

| Feature | Type | Range |
|---------|------|-------|
| `hour_of_day` | integer | 0–23 |
| `fail_count_24h` | integer | ≥ 0 |
| `ip_change_rate_7d` | float | 0–1 |
| `new_device` | boolean | true/false |
| `average_login_interval_seconds` | integer | ≥ 0 |
| `deviation_score` | float | 0–1 |

---

## 6. Database Ownership

### sentinel_detection — 7 Base Tables

| # | Table | Purpose |
|---|-------|---------|
| 1 | `policies` | Detection policies with JSONB rules and config (is_active = single active) |
| 2 | `login_attempts` | All login events from Core (event_id idempotency, status: pending/processed/failed) |
| 3 | `risk_assessments` | Per-attempt risk scoring (1:1 with login_attempts) |
| 4 | `detection_logs` | Detailed audit trail for each detection stage |
| 5 | `soc_analysts` | SOC analyst profiles linked to users.id in core-db |
| 6 | `alerts` | SOC alerts (status: open/acknowledged/resolved/false_positive) |
| 7 | `alert_timeline` | Immutable audit trail for SOC actions (event_type includes: created, acknowledged, assigned, escalated, note_added, status_changed, resolved, false_positive) |

### Key Constraints

- `soc_analysts.user_id` → `sentinel_core.users.id` (logical cross-DB reference, NOT a real FK)
- `policies.created_by` → `sentinel_core.users.id` (logical cross-DB reference, NOT a real FK)
- `alert_timeline.actor_id` → `sentinel_core.users.id` (logical cross-DB reference, NOT a real FK)
- Single active policy enforced by partial unique index on `policies.is_active`
- No cross-database PostgreSQL foreign keys

---

## 7. APIs / Contracts Owned

### Detection API (Public — SOC Analyst + Security Admin)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/alerts` | List alerts (filter by status, risk_level) |
| GET | `/api/v1/alerts/{id}` | Get alert detail + evidence |
| GET | `/api/v1/alerts/{id}/evidence` | Get alert evidence (login attempt + risk assessment) |
| GET | `/api/v1/alerts/{id}/timeline` | Get alert timeline |
| POST | `/api/v1/alerts/{id}/timeline` | Add timeline event |
| POST | `/api/v1/alerts/{id}/acknowledge` | Acknowledge alert |
| POST | `/api/v1/alerts/{id}/resolve` | Resolve alert |
| POST | `/api/v1/alerts/{id}/assign` | Assign alert to analyst |
| POST | `/api/v1/alerts/{id}/actions` | Trigger protective action |

### Internal (Core Consumer)

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/internal/pre-token-check` | Core calls before granting access |
| POST | `/api/v1/internal/login-events` | Core delivers login event |
| POST | `/api/v1/internal/login-attempts/{id}` | Core checks login attempt status |

### Internal (ML Consumer)

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/internal/ml/score` | Score anomaly (your ML client calls this) |
| GET | `/api/v1/internal/ml/health` | Check ML service health |
| GET | `/api/v1/internal/ml/features` | Get feature contract |

### NOT Owned (Sony)

- Auth endpoints: `/api/v1/auth/**` — Sony owns
- Session endpoints: `/api/v1/auth/sessions` — Sony owns
- Internal actions: `/api/v1/internal/actions` — Sony owns

---

## 8. Current Source to Inspect

Before refactoring anything, **inspect the current code**:

```
app/detection.py    — existing detection pipeline, ML client, login events
app/alerts.py       — existing alert lifecycle
app/internal_actions.py — (Detection's side — orchestration)
app/authz.py        — existing authorization decorators
app/models.py       — SQLAlchemy models
app/schemas.py      — Pydantic schemas
```

Also inspect relevant tests in `tests/**`:
- `tests/test_detection.py`
- `tests/test_alert_actions.py`
- `tests/test_internal_actions.py`
- `tests/test_risk_gate.py`

**Do NOT rebuild working detection behavior from scratch without understanding current code.**

---

## 9. Explicit Non-Scope

The following are **NOT your responsibility**:

- Core authentication (Sony owns)
- User sessions (Sony owns)
- User/Role/RBAC persistence (Sony owns)
- ML inference implementation (Khang owns)
- ML model lifecycle and training (Khang owns)
- Manager reporting/analytics (Khang owns)
- Redis/outbox infrastructure (not yet implemented)
- Frontend UI
- TOTP/SMS/Push MFA (Sony's FUTURE work)

---

## 10. Shared Dependencies

### Detection → Core

| Dependency | Direction | Contract |
|-----------|-----------|----------|
| Pre-token risk check | You expose | `POST /api/v1/internal/pre-token-check` — Core calls you |
| Protective action | You call Core | `POST /api/v1/internal/actions` — see `CONTRACT_CORE_DETECTION.md` |

### Detection → ML

| Dependency | Direction | Contract |
|-----------|-----------|----------|
| ML scoring | You call ML | `POST /api/v1/internal/ml/score` — see `CONTRACT_DETECTION_ML.md` |
| ML health check | You call ML | `GET /api/v1/internal/ml/health` |

### Coordination Required

- **Sony (Core)**: For pre-token check contract and protective action enforcement API
- **Khang (ML)**: For ML contract, feature names, response schema, timeout

---

## 11. Implementation Milestones

### D0 — Sync & Inspect Baseline

```
Inputs:  latest dev branch, current app/detection.py, app/alerts.py
Outputs: understanding of what already works
Actions: run pytest -q, inspect detection.py, models.py, main.py
```

### D1 — Detection API Contracts

```
Inputs:  schema-detection-v3.3.sql, app/schemas.py
Outputs: Internal endpoint schemas for pre-token check and login events
         External alert API schemas
Actions: Inspect current schemas.py — extend only if needed
Tests:   test_detection.py (existing)
Acceptance: schemas match canonical decisions
```

### D2 — Login Event + Pre-Token Ingestion

```
Inputs:  CONTRACT_CORE_DETECTION.md, existing detection.py
Outputs: POST /api/v1/internal/login-events endpoint
         POST /api/v1/internal/pre-token-check endpoint
         Event deduplication (event_id idempotency)
Actions: Detection receiver `POST /api/v1/internal/login-events` is IMPLEMENTED.
         Core producer side is NOT YET IMPLEMENTED (Sony's responsibility).
         Do NOT claim end-to-end delivery is working.
Tests:   test_detection.py
Acceptance: events ingested, idempotency works, pre-token returns risk level
```

### D3 — Feature Builder

```
Inputs:  6 canonical features (see Section 5), login_attempts table
Outputs: Feature construction from login attempt data
         IP reputation data
         Time-based features (hour_of_day)
         Device features (new_device)
         Behavioral features (fail_count_24h, ip_change_rate_7d, average_login_interval_seconds, deviation_score)
Tests:   test_detection.py
Acceptance: all 6 features constructed correctly
```

### D4 — Rule Engine

```
Inputs:  policies table, active policy JSONB rules
Outputs: Rule evaluation against features
         rule_score calculation
         Canonical formula: contribution = rule.score × rule.weight
Tests:   test_detection.py
Acceptance: rule_score matches canonical formula exactly
```

### D5 — ML Client (with Khang)

```
Inputs:  CONTRACT_DETECTION_ML.md, Khang's ML endpoint
Outputs: HTTP client for POST /api/v1/internal/ml/score
         5-second timeout (NOT 3s)
         Graceful fallback on timeout/error
         model_status handling
Actions: Coordinate with Khang on exact request/response schema
Tests:   test_detection.py (ML client tests)
Acceptance: ML called correctly; timeout falls back to rule_score
```

### D6 — Risk Fusion / Classification

```
Inputs:  rule_score, ml_score, config weights
Outputs: Combined score: 0.4 × rule + 0.6 × ML
         Risk level classification (low/medium/high/critical)
         Decision (allow/challenge/block)
Actions: Implement canonical formula exactly
Tests:   test_detection.py
Acceptance: scores match canonical formulas; thresholds correct
```

### D7 — Alert Creation + Evidence

```
Inputs:  risk level, detection decision
Outputs: Alert creation for high/critical decisions
         Alert evidence: login attempt + risk assessment
Actions: Inspect existing alert creation logic first
Tests:   test_alert_actions.py
Acceptance: alerts created for high/critical; evidence retrievable
```

### D8 — SOC Workflow

```
Inputs:  alerts, alert_timeline tables
Outputs: Alert list API (filter by status, risk_level)
         Alert detail + evidence API
         Acknowledge, resolve, false_positive
         Timeline recording
         Assign alert
         Add note
Actions: Implement alert status machine: open → acknowledged → resolved/false_positive
         ESCALATED is a timeline event, NOT a status
Tests:   test_alert_actions.py
Acceptance: status transitions work; timeline recorded; no ESCALATED status
```

### D9 — Protective Actions (with Sony)

```
Inputs:  CONTRACT_CORE_DETECTION.md
Outputs: Alert action endpoint: POST /alerts/{id}/actions
         Protective action orchestration
         Call to Core: POST /api/v1/internal/actions
         Supported: REQUIRE_MFA, REVOKE_SESSIONS, LOCK_USER, FORCE_LOGOUT
         Timeline recording + audit log
Actions: Coordinate with Sony on Core's /internal/actions endpoint
Tests:   test_internal_actions.py
Acceptance: action sent to Core; timeline recorded; idempotency works
```

### D10 — Detection Policy / Security Admin

```
Inputs:  policies table
Outputs: GET /policies (list all policies)
         POST /policies/{id}/activate (activate policy)
         Create/Edit policy: APPROVED DESIGN / IMPLEMENTATION PENDING
Actions: Implement View + Activate now
         Note Create/Edit as future milestone
Tests:   test_detection.py
Acceptance: View lists policies; single-active enforced; activation works
```

### D11 — Tests

```
Inputs:  all milestones
Outputs: Full test coverage
Actions: Run pytest -q; fix failures
         Contract tests with Sony (Core↔Detection) and Khang (Detection↔ML)
```

---

## 12. Required Tests

| Area | Test File(s) | Minimum Coverage |
|------|-------------|-----------------|
| Detection pipeline | `tests/test_detection.py` | Features, rule_score, ML fallback, risk fusion |
| Login events | `tests/test_detection.py` | Ingestion, deduplication |
| Pre-token check | `tests/test_detection.py` | Risk level, require_mfa, degraded |
| Alert lifecycle | `tests/test_alert_actions.py` | Status transitions, timeline |
| SOC workflow | `tests/test_alert_actions.py` | Acknowledge, resolve, false positive |
| Protective actions | `tests/test_internal_actions.py` | All 4 action types |
| Policy activation | `tests/test_detection.py` | Single-active enforcement |
| ML client | `tests/test_detection.py` | Timeout, fallback, model_status |
| Schema consistency | `tests/test_schema_consistency.py` | 7 tables match schema |

### Shared Contract Tests (with Sony and Khang)

- Core↔Detection contract tests
- Detection↔ML contract tests

---

## 13. Acceptance Criteria

- [ ] Pre-token check returns `risk_level`, `require_mfa`, `degraded` to Core
- [ ] Login events ingested with idempotency (event_id)
- [ ] All 6 features constructed correctly from login attempt data
- [ ] rule_score matches canonical formula
- [ ] ML client calls ML service with 5-second timeout
- [ ] ML unavailable → fallback to rule_score (not block)
- [ ] Combined score: `0.4 × rule + 0.6 × ML` when ML available
- [ ] Risk thresholds correct: low < 0.25, medium < 0.50, high < 0.75, critical >= 0.75
- [ ] Alerts created for high and critical decisions
- [ ] Alert statuses: `open`, `acknowledged`, `resolved`, `false_positive` only
- [ ] `ESCALATED` is a timeline event_type, NOT a status
- [ ] Protective actions sent to Core via `/internal/actions`
- [ ] Timeline recorded for all SOC actions
- [ ] Policy single-active enforced (partial unique index)
- [ ] `pytest -q` passes (358+ tests)
- [ ] No unauthorized cross-database access

---

## 14. Definition of Done

Your task is DONE when ALL of the following are true:

1. **Your acceptance criteria pass** (see Section 13)
2. **Your tests pass** (`pytest tests/test_detection.py tests/test_alert_actions.py tests/test_internal_actions.py -q`)
3. **Shared contract tests pass** — Core↔Detection contract works with Sony, Detection↔ML contract works with Khang
4. **No canonical decision violated** — risk formula unchanged (0.4/0.6), thresholds unchanged, features unchanged
5. **No unauthorized database access** — you did not read/write sentinel_core or sentinel_ml tables directly
6. **Documentation updated** — if you changed any contract, `CONTRACT_CORE_DETECTION.md` or `CONTRACT_DETECTION_ML.md` is updated
7. **Branch cleanly merges into dev** — no conflicts
8. **Integration does not break other service tests** — Sony's and Khang's tests still pass

---

## 15. Stop / Ask Lead Conditions

**STOP and ask the lead before:**

- Changing the risk formula (0.4 × rule + 0.6 × ML is canonical)
- Changing risk thresholds (low < 0.25, medium < 0.50, high < 0.75, critical >= 0.75)
- Changing ML timeout (5 seconds is canonical)
- Adding or removing any of the 6 canonical features
- Changing shared ML request/response schemas
- Changing reason-code semantics
- Changing model_status semantics
- Adding `ESCALATED` as an alert status
- Implementing mandatory Manager approval queue
- Changing fail-open to fail-closed on pre-token check
- Implementing async Redis/outbox flow (not yet designed)
- Directly accessing `sentinel_core` tables for enforcement logic
- Directly accessing `sentinel_ml` tables
- Modifying `app/main.py` shared entrypoint (requires lead)
- Deleting existing working detection behavior

---

## 16. Handoff Checklist

Before marking your milestone complete:

- [ ] All source files inspected (not just reading requirements)
- [ ] Current baseline tests pass (`pytest -q`)
- [ ] Risk formula verified: 0.4 × rule + 0.6 × ML when ML available; rule_score alone when unavailable
- [ ] ML timeout verified: 5 seconds (not 3s)
- [ ] Risk thresholds verified: low < 0.25, medium < 0.50, high < 0.75, critical >= 0.75
- [ ] All 6 features present and correct
- [ ] Alert statuses: only open/acknowledged/resolved/false_positive; no ESCALATED status
- [ ] ESCALATED is a timeline event_type (not status)
- [ ] Protective actions use `/internal/actions` (not direct DB writes)
- [ ] Cross-DB access prohibited (no direct sentinel_core/sentinel_ml queries)
- [ ] Single-active policy enforced
- [ ] Tests written for new behavior
- [ ] Contract documents updated if any API changed
- [ ] Branch merges cleanly into dev
