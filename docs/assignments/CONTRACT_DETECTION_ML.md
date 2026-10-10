# Contract: Detection Engine ↔ ML Service

**Owners:** Tuấn Anh (Detection) + Khang (ML)
**Reviewer:** Lead

---

## Overview

This contract governs the integration between the Detection Engine service (Tuấn Anh) and the ML Service (Khang).

- **Detection owns risk decision and final classification.** ML owns inference, normalization, and model lifecycle.
- **Neither service writes directly into the other's PostgreSQL database.**
- **Changes to this contract require lead approval** and must update this document.

---

## A. Request Schema

**Direction:** Detection → ML
**Purpose:** Anomaly scoring

### Endpoint
```
POST /api/v1/internal/ml/score
```

### Authentication
- Detection sends `X-Internal-Secret` header
- ML validates shared secret

### Request

```json
{
  "request_id": "550e8400-e29b-41d4-a716-446655440000",
  "features": {
    "hour_of_day": 14,
    "fail_count_24h": 2,
    "ip_change_rate_7d": 0.15,
    "new_device": true,
    "average_login_interval_seconds": 28800,
    "deviation_score": 0.3
  }
}
```

### Field Definitions

| Field | Type | Range | Description |
|-------|------|--------|-------------|
| `hour_of_day` | integer | 0–23 | Hour of day in local time |
| `fail_count_24h` | integer | ≥ 0 | Failed login attempts in last 24 hours |
| `ip_change_rate_7d` | float | 0–1 | Rate of new IPs in last 7 days |
| `new_device` | boolean | true/false | Device fingerprint not seen before |
| `average_login_interval_seconds` | integer | ≥ 0 | Average seconds between logins |
| `deviation_score` | float | 0–1 | Behavioral deviation from baseline |

### Validation Rules

- ML MUST validate all 6 features are present
- ML MUST validate types match (integer for `hour_of_day`, `fail_count_24h`; float for others; boolean for `new_device`)
- ML MUST validate ranges
- Unknown fields: **reject** with `400 Bad Request`
- Missing fields: **reject** with `400 Bad Request`

---

## B. Response Schema

**Direction:** ML → Detection
**Purpose:** Return normalized anomaly score

### Response (Success)

```json
{
  "request_id": "550e8400-e29b-41d4-a716-446655440000",
  "normalized_anomaly_score": 0.72,
  "is_anomaly": true,
  "model_version": "v1.0-isolation-forest",
  "reason_codes": ["high_fail_count", "unusual_hour"],
  "model_status": "ready"
}
```

### Field Definitions

| Field | Type | Range | Description |
|-------|------|--------|-------------|
| `request_id` | uuid | — | Echoed back from request |
| `normalized_anomaly_score` | float | **[0, 1]** | Normalized anomaly score |
| `is_anomaly` | boolean | true/false | Whether score indicates anomaly |
| `model_version` | string | — | Version of model used |
| `reason_codes` | array[string] | — | Codes indicating why anomaly detected |
| `model_status` | string | `ready` \| `degraded` \| `error` | Current model health |

### `model_status` Semantics

| Value | Meaning |
|-------|---------|
| `ready` | Model loaded, inference successful |
| `degraded` | Model partially available (slow response, degraded quality) |
| `error` | Model unavailable or inference failed |

### Response (Timeout / Error)

Detection handles ML failures by falling back to rule-only scoring. ML does not return a special error schema — Detection interprets any non-2xx or timeout as ML unavailable.

---

## C. Feature Contract

### Feature Names

These are the **only** 6 features. No others are accepted or generated:

```
hour_of_day
fail_count_24h
ip_change_rate_7d
new_device
average_login_interval_seconds
deviation_score
```

### Feature Types

| Feature | Type |
|---------|------|
| `hour_of_day` | integer |
| `fail_count_24h` | integer |
| `ip_change_rate_7d` | float |
| `new_device` | boolean |
| `average_login_interval_seconds` | integer |
| `deviation_score` | float |

### Feature Ranges

| Feature | Min | Max |
|---------|-----|-----|
| `hour_of_day` | 0 | 23 |
| `fail_count_24h` | 0 | (unlimited) |
| `ip_change_rate_7d` | 0.0 | 1.0 |
| `new_device` | false | true |
| `average_login_interval_seconds` | 0 | (unlimited) |
| `deviation_score` | 0.0 | 1.0 |

---

## D. Reason Codes

### Standard Reason Codes

| Code | Meaning |
|------|---------|
| `unusual_hour` | `hour_of_day` is outside normal business hours |
| `high_fail_count` | `fail_count_24h` is unusually high |
| `new_ip` | `ip_change_rate_7d` indicates new IPs |
| `new_device` | Login from previously unseen device |
| `behavioral_deviation` | `deviation_score` indicates unusual behavior |
| `multiple_factors` | Multiple risk factors combined |
| `unknown_feature` | (Detection only) Unknown feature in rule evaluation |

### Reason Code Rules

- ML generates `reason_codes` from Isolation Forest anomaly factors
- `reason_codes` is an array (can be empty, can have multiple)
- Detection consumes `reason_codes` for alert evidence
- **Both owners must approve** any change to reason code semantics

---

## E. Authentication

### Header

```
X-Internal-Secret: <shared secret>
```

| Caller | Callee | Secret |
|--------|--------|--------|
| Detection | ML | Shared `X-Internal-Secret` (same as Core↔Detection) |

---

## F. Timeout

| Direction | Timeout | Behavior |
|-----------|---------|----------|
| Detection → ML | **5 seconds** | Detection falls back to rule-only scoring |

### Detection-Side Timeout Behavior

```
1. Send POST /api/v1/internal/ml/score
2. Wait up to 5 seconds
3. If response received:
     - Parse normalized_anomaly_score
     - Continue with 0.4*rule + 0.6*ml fusion
4. If timeout:
     - Log ml_status = 'unavailable'
     - Fall back to rule_score only
     - Continue pipeline
5. If error response:
     - Log ml_status = 'error'
     - Fall back to rule_score only
     - Continue pipeline
```

**The 5-second timeout is on Detection's side (ML client). ML must respond within 5 seconds.**

---

## G. Fallback Behavior

### Detection-Side Fallback

When ML is unavailable (timeout, error, or `model_status = error`):

```
if ml_status == 'success':
    combined_score = 0.4 * rule_score + 0.6 * ml_score
else:
    combined_score = rule_score   # graceful degradation

# After fallback, decision:
if combined_score >= 0.75:
    decision = 'block'
    action = REVOKE_SESSIONS
    alert = created
elif combined_score >= 0.50:
    decision = 'challenge'
    action = REQUIRE_MFA
    alert = created
else:
    decision = 'allow'
    action = none
    alert = not_created
```

**Note:** When ML is unavailable, the fallback to rule-only scoring is **stricter by design** because rule_score alone cannot benefit from ML's anomaly detection.

---

## H. Model Lifecycle

### Model Status Values

| Status | Meaning | Detection Behavior |
|--------|---------|------------------|
| `ready` | Model loaded and healthy | Use `normalized_anomaly_score` normally |
| `degraded` | Model slow or degraded | Use score; log degraded status |
| `error` | Model unavailable | Fall back to rule-only |

### Versioning

- ML exposes current `model_version` in response
- Detection logs `model_version_used` in `risk_assessments.ml_model_version`
- Both owners must agree before changing active model version
- Model version changes should be tested in staging before production

---

## I. Inference Logging

### ML Service

ML writes to `sentinel_ml.inference_logs`:

```json
{
  "request_id": "...",
  "features": { ... },
  "raw_score": 0.85,
  "normalized_score": 0.72,
  "is_anomaly": true,
  "reason_codes": [...],
  "model_status": "ready",
  "processing_time_ms": 42
}
```

### Detection Engine

Detection writes to `sentinel_detection.risk_assessments`:

```
rule_score, ml_score, combined_score, ml_status, ml_model_version, rule_hits, ml_reason_codes, ml_features_used
```

---

## J. Contract Tests

Both Tuấn Anh and Khang are responsible for writing contract tests.

### Detection-Side Tests (Tuấn Anh)

| Test | Description |
|------|-------------|
| ML available → 0.4*rule + 0.6*ml | Combined score uses ML contribution |
| ML timeout (5s) → rule fallback | Falls back to rule_score |
| ML error → rule fallback | Falls back to rule_score |
| ML response missing → rule fallback | Falls back to rule_score |
| Invalid features → 400 rejected | ML rejects invalid request |
| Unknown feature → 400 rejected | ML rejects unknown features |
| ML 5s timeout behavior | Detection logs ml_status = 'unavailable' |

### ML-Side Tests (Khang)

| Test | Description |
|------|-------------|
| Valid 6 features → success | All features valid, inference runs |
| Missing feature → 400 | Request rejected |
| Unknown feature → 400 | Request rejected |
| Type mismatch → 400 | Request rejected |
| Score in [0,1] | normalized_anomaly_score is 0–1 |
| is_anomaly boolean | Correctly set based on threshold |
| model_status: ready | Returns ready when healthy |
| model_status: degraded | Returns degraded on slow inference |
| model_status: error | Returns error on failure |
| request_id echoed | request_id matches request |
| model_version returned | Version string in response |
| reason_codes array | Returned even if empty |
| Respects 5s window | Inference completes within 5 seconds |

### Joint Tests

| Test | Description |
|------|-------------|
| End-to-end scoring | Detection sends features → ML returns score → Detection fuses |
| Feature contract | All 6 canonical features accepted; unknown rejected |
| Timeout contract | Detection times out at 5s if ML does not respond |

---

## K. Change Control

### Approval Required For

Both owners must approve before implementation:

- Adding or removing any of the 6 features
- Changing feature types or ranges
- Changing `normalized_anomaly_score` range
- Changing `model_status` values
- Changing `reason_codes` semantics or adding new codes
- Changing service authentication
- Changing timeout value (5 seconds is canonical)
- Changing request/response schemas
- Adding new persisted entities

### Lead Approval Required For

- Changing the 0.4/0.6 weighting formula
- Changing risk thresholds (low < 0.25, medium < 0.50, high < 0.75)
- Changing Isolation Forest to a different algorithm
- Adding a new service to the ML pipeline

---

## L. Responsibility Matrix

| Concern | Tuấn Anh (Detection) | Khang (ML) |
|---------|----------------------|------------|
| Feature construction | **Owner** | Consumer |
| Feature validation (basic) | Producer-side basic check | **Owner** |
| HTTP client | **Owner** | — |
| Endpoint availability | — | **Owner** |
| Timeout (5 seconds) | **Owner** | Must respond within 5s |
| Inference | — | **Owner** |
| Score normalization [0,1] | Consumer | **Owner** |
| Reason code generation | Consumer | **Owner** |
| Model lifecycle | — | **Owner** |
| Model versioning | — | **Owner** |
| Fallback behavior | **Owner** | — |
| Final risk classification | **Owner** | — |

---

## M. Versioning

```
Contract Version: 1.0
Last Updated: 2026-10-10
```
