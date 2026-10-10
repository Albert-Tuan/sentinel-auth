# Khang — ML Service / Analytics Assignment

**Branch:** `ml-service`
**Bounded Context:** ML / ANALYTICS
**Primary Technical Responsibility:** ML SERVICE
**Primary Business Responsibility:** SECURITY_MANAGER analytics/reporting

---

## 1. Mission

Own and implement the ML Service bounded context and Security Manager analytics/reporting for Sentinel Auth v3.3.

You are responsible for: ML request validation, Isolation Forest inference, score normalization, reason codes, model registry, inference logging, feature statistics, and Security Manager analytics/reporting.

You do NOT own: Core authentication, detection rules, SOC alert lifecycle, or user management.

---

## 2. Branch / Ownership

```
Branch: ml-service
Start from: dev (latest approved baseline)
Primary service: ML / Analytics
Database: sentinel_ml (3 base tables + 1 real view)
```

---

## 3. Required Reading

Read in this order before starting implementation:

1. `docs/DECISIONS-SYSTEM-v3.3.md` — system-level decisions
2. `docs/DECISIONS-DETECTION-v3.3.md` — canonical ML contract decisions
3. `docs/03-bang-yeu-cau-chuc-nang-nghiep-vu-ml-service.md` — ML functional requirements
4. `docs/04-dac-ta-use-case-ml-service.md` — ML use case specifications
5. `docs/05-phan-tich-doi-tuong-su-dung-ml-service.md` — actor analysis
6. `infra/postgres/schema-ml-service-v3.3.sql` — all 3 tables + local_ml_stats view (see Section 6)
7. `docs/workflows.mmd` — WF-6 (ML inference)
8. `docs/diagrams/wf6_ml_inference.uml` — ML inference flow
9. `docs/audit/17-requirements-usecase-reconciliation.md` — requirements reconciliation
10. `docs/assignments/CONTRACT_DETECTION_ML.md` — Detection↔ML contract

---

## 4. Business Responsibilities

### ML Service (Technical Owner)

- Validate ML inference requests from Detection Engine
- Run Isolation Forest model inference
- Normalize anomaly scores to [0, 1]
- Generate reason codes
- Log inference results
- Maintain model registry and versioning
- Monitor feature statistics

### Security Manager Analytics (Implementation Responsibility)

Security Manager does NOT architecturally belong to ML Service. The Manager role is cross-service. However, Khang owns the **implementation** of Manager-facing analytics.

Manager responsibilities:

- Security overview dashboard
- Risk trend visibility
- High/critical incident overview
- SOC effectiveness / KPI reporting
- Alert backlog statistics
- False-positive statistics
- Audit/security activity review
- Policy configuration view-only
- ML/model analytics

**Important:** Manager data comes from **all three services** (Core, Detection, ML). Do NOT attempt to own Manager data sources in `sentinel_ml`. Use service contracts to aggregate.

### NOT Your Responsibility

- SOC alert lifecycle — Tuấn Anh owns
- Detection rules and risk decisions — Tuấn Anh owns
- Core authentication and sessions — Sony owns
- Manager architectural ownership — cross-service

---

## 5. Technical Responsibilities

### ML Contract (with Detection — Tuấn Anh)

#### Request Schema

```json
{
  "request_id": "uuid",
  "features": {
    "hour_of_day": 14,              // integer, 0–23
    "fail_count_24h": 2,           // integer, ≥ 0
    "ip_change_rate_7d": 0.15,     // float, 0–1
    "new_device": true,             // boolean
    "average_login_interval_seconds": 28800,      // integer, ≥ 0
    "deviation_score": 0.3          // float, 0–1
  }
}
```

#### Response Schema

```json
{
  "request_id": "uuid",
  "normalized_anomaly_score": 0.72,   // float, [0, 1]
  "is_anomaly": true,                  // boolean
  "model_version": "v1.0-isolation-forest",
  "reason_codes": ["high_fail_count", "unusual_hour"],
  "model_status": "ready"             // "ready" | "degraded" | "error"
}
```

### Six Canonical Features

These are the ONLY features consumed from Detection. Do NOT accept or generate other features:

| Feature | Type | Range |
|---------|------|-------|
| `hour_of_day` | integer | 0–23 |
| `fail_count_24h` | integer | ≥ 0 |
| `ip_change_rate_7d` | float | 0–1 |
| `new_device` | boolean | true/false |
| `average_login_interval_seconds` | integer | ≥ 0 |
| `deviation_score` | float | 0–1 |

### What You OWN vs What Detection OWNS

| Concern | Owner |
|---------|-------|
| Feature construction | **Tuấn Anh** (Detection) |
| Feature validation (on ML side) | **Khang** |
| HTTP client | **Tuấn Anh** |
| ML endpoint | **Khang** |
| Timeout (5 seconds) | **Tuấn Anh** |
| ML response within contract | **Khang** |
| Isolation Forest inference | **Khang** |
| Score normalization [0,1] | **Khang** |
| Reason codes | **Khang** |
| Model status | **Khang** |
| Final risk classification | **Tuấn Anh** (Detection — you do NOT calculate this) |
| Model lifecycle / versioning | **Khang** |

---

## 6. Database Ownership

### sentinel_ml — 3 Base Tables + 1 Real View

| # | Table/View | Purpose |
|---|-----------|---------|
| 1 | `model_versions` | Model registry (id, name, version, algorithm: IsolationForest, model_path, config JSONB, status: staged/active/archived/failed, is_production, trained_by, training_date) |
| 2 | `inference_logs` | Optional inference logging (request_id, features JSONB, raw_score, normalized_score [0,1], is_anomaly, reason_codes JSONB, model_status: ready/degraded/error, processing_time_ms) |
| 3 | `feature_statistics` | Feature distribution monitoring (feature_name, count, mean, std, min, max, p25, p50, p75, p95, anomaly_rate) |
| — | `local_ml_stats` | **Real view** aggregating inference_logs (day, total_inferences, anomalies_detected, successful_inferences, avg_processing_ms, avg_anomaly_score) |

### NOT a Real View

> **Do NOT call `manager_dashboard` a real view.** It is a **commented-out conceptual SQL** in `schema-ml-service-v3.3.sql` (lines 200–260) showing what would be needed if all tables were in one database. It is **NOT implemented**.

The actual manager dashboard implementation will use HTTP API calls to Detection and Core services.

### Key Constraints

- No cross-database foreign keys to `sentinel_detection` or `sentinel_core`
- `trained_by` → `sentinel_core.users.id` (logical cross-DB reference, NOT a real FK)
- `inference_logs.model_version_id` → `model_versions.id` (real FK within sentinel_ml)

---

## 7. APIs / Contracts Owned

### ML Inference API (Internal — Detection Consumer)

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/internal/ml/score` | Score anomaly (Detection calls this) |
| GET | `/api/v1/internal/ml/health` | ML service health + model status |
| GET | `/api/v1/internal/ml/features` | Feature contract |

### Manager Analytics API (Public — Manager)

**IMPLEMENTATION_PENDING** — design and implement with lead approval:

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/manager/dashboard` | Security overview dashboard |
| GET | `/api/v1/manager/trends` | Risk trends |
| GET | `/api/v1/manager/alerts` | Alert statistics |
| GET | `/api/v1/manager/soc-kpi` | SOC effectiveness KPIs |
| GET | `/api/v1/manager/ml-stats` | ML model analytics |

---

## 8. Current Source to Inspect

Before refactoring anything, **inspect the current code**:

```
app/ml.py          — existing ML inference endpoint
app/detection.py   — ML contract understanding (Detection's ML client)
app/models.py       — SQLAlchemy models
app/schemas.py      — Pydantic schemas
```

Also inspect relevant tests in `tests/**`:
- `tests/test_ml.py`

**Do NOT rebuild working ML behavior from scratch without understanding current code.**

---

## 9. Explicit Non-Scope

The following are **NOT your responsibility**:

- Detection rules, SOC alert lifecycle — Tuấn Anh owns
- Core authentication, sessions — Sony owns
- Manager architectural ownership — cross-service
- Redis/outbox infrastructure — not yet designed
- Frontend UI

---

## 10. Shared Dependencies

### Detection ↔ ML Contract

| Dependency | Direction | Contract |
|-----------|-----------|----------|
| ML scoring | Detection calls you | `POST /api/v1/internal/ml/score` — see `CONTRACT_DETECTION_ML.md` |
| Feature contract | Detection calls you | `GET /api/v1/internal/ml/features` |
| Health check | Detection calls you | `GET /api/v1/internal/ml/health` |

### Coordination Required

- **Tuấn Anh (Detection)**: For exact request/response schema, feature names, reason codes, timeout behavior
- **Sony (Core)**: For manager analytics aggregation (data from Core)

---

## 11. Implementation Milestones

### M0 — Sync & Inspect Baseline

```
Inputs:  latest dev branch, current app/ml.py
Outputs: understanding of what already works
Actions: run pytest -q, inspect ml.py, schemas.py, models.py
```

### M1 — ML API Contract

```
Inputs:  CONTRACT_DETECTION_ML.md, schema-ml-service-v3.3.sql
Outputs: ML endpoint schemas matching canonical contract
         Feature validation
         Request/response contracts frozen
Actions: Inspect current schemas.py — extend only if needed
Tests:   test_ml.py (existing)
Acceptance: schemas match canonical contract exactly
```

### M2 — Feature Validation / Preprocessing

```
Inputs:  6 canonical features, request validation
Outputs: Feature type/range validation
         Preprocessing for Isolation Forest
Actions: Implement validation for all 6 features
         Reject unknown features
Tests:   test_ml.py
Acceptance: invalid features rejected; valid features accepted
```

### M3 — Isolation Forest Inference

```
Inputs:  model_versions table, model file on disk
Outputs: Isolation Forest model loading
         predict() call
         raw_score extraction
Actions: Inspect current ml.py — extend only if needed
Tests:   test_ml.py
Acceptance: model loads; inference runs; result generated
```

### M4 — Score Normalization

```
Inputs:  raw Isolation Forest score
Outputs: normalized_anomaly_score in [0, 1]
         is_anomaly boolean
Actions: Implement normalization formula
         Decide threshold for is_anomaly
Tests:   test_ml.py
Acceptance: score normalized to [0,1]
```

### M5 — Reason Codes + Model Status

```
Inputs:  Isolation Forest anomaly factors
Outputs: reason_codes array
         model_status: ready/degraded/error
Actions: Implement reason code generation
         Handle model errors gracefully
Tests:   test_ml.py
Acceptance: reason codes returned; model_status correct
```

### M6 — Model Registry / Versioning

```
Inputs:  model_versions table, model file management
Outputs: Active model lookup
         Model versioning
         Staged/active/archived/failed lifecycle
Actions: Implement model registry
         Single-active production model enforcement
Tests:   test_ml.py
Acceptance: model registry works; versioning correct
```

### M7 — Inference Logs / Statistics

```
Inputs:  inference_logs, feature_statistics tables
Outputs: Inference logging
         Feature statistics
Actions: Log all inferences
         Update feature statistics
Tests:   test_ml.py
Acceptance: logs written; statistics updated
```

### M8 — Detection Contract Tests (with Tuấn Anh)

```
Inputs:  CONTRACT_DETECTION_ML.md
Outputs: Shared contract tests
         Integration with Detection
Actions: Coordinate with Tuấn Anh on exact schema
         Run end-to-end tests
Tests:   test_ml.py + test_detection.py (joint)
Acceptance: Detection can call ML endpoint; response matches contract
```

### M9 — Manager Analytics Design

```
Inputs:  Core, Detection, ML data sources
Outputs: Manager analytics design document
         Data sources from all 3 services
Actions: Design with lead approval
         Do NOT duplicate source-of-truth tables in sentinel_ml
         Use HTTP API aggregation
Tests:   TBD (design first)
Acceptance: design approved by lead
```

### M10 — Manager Reports / Aggregation

```
Inputs:  M9 design
Outputs: Manager analytics endpoints
         Data aggregation from Core + Detection + ML
Actions: Implement aggregation
         Expose manager endpoints
Tests:   TBD
Acceptance: manager can view analytics
```

### M11 — Tests

```
Inputs:  all milestones
Outputs: Full test coverage
Actions: Run pytest -q; fix failures
```

---

## 12. Required Tests

| Area | Test File(s) | Minimum Coverage |
|------|-------------|-----------------|
| Feature validation | `tests/test_ml.py` | All 6 features validated; invalid rejected |
| Inference | `tests/test_ml.py` | Isolation Forest runs; result generated |
| Score normalization | `tests/test_ml.py` | Score in [0, 1]; is_anomaly boolean |
| Reason codes | `tests/test_ml.py` | Codes returned; error handling |
| Model registry | `tests/test_ml.py` | Model lookup; versioning |
| Inference logging | `tests/test_ml.py` | Logs written |
| Contract tests | `tests/test_ml.py` | Response matches canonical schema |
| Schema consistency | `tests/test_schema_consistency.py` | 3 tables match schema |

### Shared Contract Tests (with Tuấn Anh)

- Detection↔ML contract tests

---

## 13. Acceptance Criteria

- [ ] ML endpoint accepts requests matching canonical contract
- [ ] All 6 features validated (invalid features rejected)
- [ ] Isolation Forest inference runs and returns raw score
- [ ] `normalized_anomaly_score` is in range [0, 1]
- [ ] `is_anomaly` boolean correctly set
- [ ] `reason_codes` returned
- [ ] `model_status`: `ready` / `degraded` / `error` correctly set
- [ ] `request_id` echoed back in response
- [ ] `model_version` returned
- [ ] Model registry manages versioning correctly
- [ ] Inference logs written to `inference_logs` table
- [ ] `local_ml_stats` view aggregates correctly
- [ ] ML service responds within 5-second contract window
- [ ] Manager analytics design document created
- [ ] `pytest -q` passes (358+ tests)
- [ ] No unauthorized cross-database access

---

## 14. Definition of Done

Your task is DONE when ALL of the following are true:

1. **Your acceptance criteria pass** (see Section 13)
2. **Your tests pass** (`pytest tests/test_ml.py -q`)
3. **Shared contract tests pass** — Detection↔ML contract works with Tuấn Anh
4. **No canonical decision violated** — features unchanged, response schema unchanged
5. **No unauthorized database access** — you did not read/write `sentinel_detection` or `sentinel_core` tables directly
6. **No Manager data duplication** — you do not own users, alerts, or policies tables
7. **Documentation updated** — if you changed the ML contract, `CONTRACT_DETECTION_ML.md` is updated
8. **Branch cleanly merges into dev** — no conflicts
9. **Integration does not break other service tests** — Tuấn Anh's and Sony's tests still pass

---

## 15. Stop / Ask Lead Conditions

**STOP and ask the lead before:**

- Changing the 6 canonical features (add or remove)
- Changing feature types or ranges
- Changing ML request/response schemas
- Changing reason-code semantics
- Changing model_status semantics
- Changing normalization formula
- Changing the Isolation Forest algorithm
- Adding new persistent entities in sentinel_ml
- Directly querying `sentinel_detection` tables for Manager reporting (use HTTP API)
- Directly querying `sentinel_core` tables for Manager reporting (use HTTP API)
- Implementing Manager analytics before design is approved
- Modifying `app/main.py` shared entrypoint (requires lead)
- Changing service authentication (X-Internal-Secret)
- Deleting existing working ML behavior

---

## 16. Handoff Checklist

Before marking your milestone complete:

- [ ] All source files inspected (not just reading requirements)
- [ ] Current baseline tests pass (`pytest -q`)
- [ ] ML response schema matches canonical contract exactly
- [ ] All 6 features validated (no extra features accepted)
- [ ] Score normalized to [0, 1]
- [ ] `model_dashboard` is NOT a real view — only `local_ml_stats` exists
- [ ] Manager reporting uses HTTP API aggregation (no direct cross-DB queries)
- [ ] Cross-DB access prohibited (no direct sentinel_detection/sentinel_core queries)
- [ ] Model registry versioning works correctly
- [ ] Tests written for new behavior
- [ ] Contract document updated if schema changed
- [ ] Branch merges cleanly into dev
