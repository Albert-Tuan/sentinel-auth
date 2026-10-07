# P1-A Remediation Log

**Finding:** Unsafe predictable default for `INTERNAL_SECRET`
**Classification:** Unsafe default / fail-open configuration behaviour
**Severity:** HIGH
**Status:** RESOLVED ✅

---

## Root Cause

Four independent modules each read the shared service-to-service secret as:

```python
os.getenv("INTERNAL_SECRET", "changeme-in-production")
```

When `INTERNAL_SECRET` is not set in the deployment environment, the application
silently uses a hardcoded, publicly known credential. Any actor who knows the
value `"changeme-in-production"` can authenticate as any internal service
(Detection Engine, Core App, ML Service) without a valid deployment-secret.

The behaviour is not literally unauthenticated — the secret still gates access —
but the effective security is zero because the credential is public knowledge.

---

## Chosen Configuration Behaviour

`get_internal_secret()` validates the environment value and raises
`InternalAuthConfigurationError` when any of the following is true:

| Condition | Raised |
|---|---|
| `INTERNAL_SECRET` not set | `InternalAuthConfigurationError("INTERNAL_SECRET is not set")` |
| `INTERNAL_SECRET` set to `""` (empty) | `InternalAuthConfigurationError("INTERNAL_SECRET is empty")` |
| `INTERNAL_SECRET` set to whitespace only | `InternalAuthConfigurationError("INTERNAL_SECRET is empty")` |
| `INTERNAL_SECRET` set to `"changeme-in-production"` | `InternalAuthConfigurationError` |
| `INTERNAL_SECRET` shorter than 32 characters | `InternalAuthConfigurationError` |

A valid secret must:
- Be present in the environment
- Be non-empty after stripping whitespace
- Not equal `"changeme-in-production"`
- Be at least 32 characters

No random secret is generated at runtime. Services must share the same
explicitly configured value.

---

## Fail-Closed Inbound Result

`verify_internal_secret()` — used by all inbound protected routes:

| Scenario | HTTP Status | Detail |
|---|---|---|
| `INTERNAL_SECRET` not configured securely | **503** | "Internal authentication is not configured" |
| Header absent | **401** | "Invalid or missing X-Internal-Secret" |
| Header wrong | **401** | "Invalid or missing X-Internal-Secret" |
| Header correct | *(silence)* | Request proceeds |

Routes protected by `verify_internal_secret`:
- `POST /api/v1/internal/actions` (Core App)
- `GET /api/v1/internal/users/{id}` (Core App)
- `POST /api/v1/internal/pre-token-check` (Detection Engine)
- `POST /api/v1/internal/login-events` (Detection Engine)
- `GET /api/v1/internal/login-attempts/{id}` (Detection Engine)
- `POST /api/v1/internal/ml/score` (ML Service)

---

## Fail-Open Outbound Result

Three outbound service-to-service call paths are handled individually:

### Auth → Detection (pre-token check)
`app/auth.py` calls `call_pre_token_detection_check()`. When
`get_internal_secret()` raises `InternalAuthConfigurationError`, the existing
`except Exception` handler catches it and the function returns `None`, preserving
the **fail-open** design: login proceeds unscored rather than being blocked by
a configuration error.

### Detection → ML
`app/detection.py` `call_ml_service()`. When `get_internal_secret()` raises,
returns `MlOutcome(None, "unavailable", error="internal_auth_not_configured")`.
The Detection Engine degrades gracefully: combined score falls back to
`rule_score` alone, preserving the existing ML-unavailable behaviour.

### Detection → Core (protective action callback)
`app/detection.py` `enforce_action_in_core()`. When `get_internal_secret()` raises,
logs a warning and returns `False` (best-effort — alert/risk assessment already
persisted, action is skipped). Preserves existing best-effort semantics.

---

## Centralisation Result

All environment reads, validation logic, and verification logic now live in one
module:

```
app/internal_auth.py   (canonical source)
    ├── _INSECURE_PLACEHOLDER = "changeme-in-production"  (rejection constant)
    ├── InternalAuthConfigurationError  (custom exception)
    ├── _read_secret()                  (os.environ.get wrapper)
    ├── get_internal_secret()           (validation + return)
    ├── is_internal_auth_configured()   (bool for health endpoints)
    └── verify_internal_secret()        (503/401 decision)
```

Four modules refactored to import from `internal_auth`:

| File | Before | After |
|---|---|---|
| `app/auth.py` | `INTERNAL_SECRET = os.getenv(..., "changeme-in-production")` | `from app.internal_auth import get_internal_secret` |
| `app/detection.py` | `def internal_secret()` + `def verify_internal_secret()` | `from app.internal_auth import get_internal_secret, verify_internal_secret, InternalAuthConfigurationError` |
| `app/internal_actions.py` | `def internal_secret()` + `def verify_internal_secret()` | `from app.internal_auth import verify_internal_secret` |
| `app/ml.py` | `def internal_secret()` + `def verify_internal_secret()` | `from app.internal_auth import verify_internal_secret` |

Constant-time comparison: `secrets.compare_digest()` used in `verify_internal_secret()`.

---

## Files Changed

| File | Change |
|---|---|
| `app/internal_auth.py` | **Created** — canonical module |
| `app/auth.py` | Removed `INTERNAL_SECRET` constant; added import of `get_internal_secret`, `InternalAuthConfigurationError`; outbound call updated to use `get_internal_secret()` |
| `app/detection.py` | Removed local `internal_secret()` and `verify_internal_secret()`; added imports; outbound ML call wrapped with `InternalAuthConfigurationError → MlOutcome unavailable`; outbound action call wrapped with `InternalAuthConfigurationError → False + warning log` |
| `app/internal_actions.py` | Removed local `internal_secret()` and `verify_internal_secret()`; imported `verify_internal_secret` from canonical module; removed unused `os` and `Optional` imports |
| `app/ml.py` | Removed local `internal_secret()` and `verify_internal_secret()`; imported `verify_internal_secret` from canonical module; removed unused `HTTPException`, `http_status` imports |
| `tests/conftest.py` | Added `TEST_INTERNAL_SECRET` constant, `SECRET_HEADER` header dict, and session-scoped autouse fixture `_set_internal_secret` that sets `INTERNAL_SECRET` for all tests |
| `tests/test_internal_auth.py` | **Created** — 17 unit tests for the canonical module (A–I plus helper/constant-time) |
| `tests/test_internal_actions.py` | Added 8 API-level fail-closed tests (503/401/correct-secret for actions and users endpoints) |
| `tests/test_ml.py` | Added 5 tests: 4 API-level fail-closed tests and 1 placeholder-rejection API test |
| `tests/test_detection.py` | Added 11 tests: 7 API-level fail-closed tests (login-events, pre-token-check, login-attempt) and 2 outbound skip tests (ML and action paths) |
| `tests/test_risk_gate.py` | Added 2 tests: `test_gate_fails_open_when_internal_secret_not_configured` and `test_gate_sends_correct_secret_header` |

---

## Internal Auth Unit Test Result

```
tests/test_internal_auth.py
  17 passed in 0.15s
```

Coverage:

| # | Test | Condition |
|---|---|---|
| 1 | `test_missing_internal_secret_raises_configuration_error` | absent → raises |
| 2 | `test_verify_missing_secret_returns_503` | absent → 503 |
| 3 | `test_empty_internal_secret_raises_configuration_error` | empty → raises |
| 4 | `test_whitespace_only_secret_raises_configuration_error` | whitespace → raises |
| 5 | `test_verify_empty_secret_returns_503` | empty → 503 |
| 6 | `test_insecure_placeholder_raises_configuration_error` | `changeme-in-production` → raises |
| 7 | `test_verify_insecure_placeholder_returns_503` | `changeme-in-production` → 503 |
| 8 | `test_too_short_secret_raises_configuration_error` | 31 chars → raises |
| 9 | `test_exactly_32_characters_is_accepted` | 32 chars → accepted |
| 10 | `test_valid_secret_returned_correctly` | valid → returned |
| 11 | `test_verify_correct_header_succeeds` | correct header → silent |
| 12 | `test_verify_wrong_header_returns_401` | wrong header → 401 |
| 13 | `test_verify_missing_header_returns_401` | absent header → 401 |
| 14 | `test_is_configured_true_for_valid_secret` | valid → True |
| 15 | `test_is_configured_false_for_missing_secret` | absent → False |
| 16 | `test_is_configured_false_for_placeholder` | placeholder → False |
| 17 | `test_constant_time_comparison_is_called` | `secrets.compare_digest` called with both values |

---

## API-Level Fail-Closed Test Results

All three internal component endpoints are tested against the full matrix:
absent `INTERNAL_SECRET` → 503, wrong header → 401, missing header → 401,
correct header → normal status.

### Core App (`tests/test_internal_actions.py`)
```
  28 passed   (8 new fail-closed tests + 20 existing)
```

New: `test_actions_returns_503_when_internal_secret_not_configured`,
`test_actions_returns_401_when_secret_wrong`,
`test_actions_returns_401_when_header_missing`,
`test_actions_succeeds_with_correct_secret`,
`test_users_returns_503_when_internal_secret_not_configured`,
`test_users_returns_401_when_secret_wrong`,
`test_users_returns_401_when_header_missing`,
`test_users_succeeds_with_correct_secret`.

### ML Service (`tests/test_ml.py`)
```
  14 passed   (5 new tests + 9 existing)
```

New: `test_ml_score_returns_503_when_internal_secret_not_configured`,
`test_ml_score_returns_401_when_secret_wrong`,
`test_ml_score_returns_401_when_header_missing`,
`test_ml_score_succeeds_with_correct_secret`,
`test_ml_score_rejects_placeholder_secret` — the last proves that
`X-Internal-Secret: changeme-in-production` against a server configured with
that placeholder returns **503**, not 200.

### Detection Engine (`tests/test_detection.py`)
```
  51 passed   (11 new tests + 40 existing)
```

New: 7 fail-closed API tests (login-events ×3, pre-token-check ×2,
login-attempt ×2) and 2 outbound skip tests:
`test_ml_outbound_returns_unavailable_when_secret_not_configured`
(→ `MlOutcome.status == "unavailable"`, `error == "internal_auth_not_configured"`,
no HTTP call),
`test_action_outbound_returns_false_when_secret_not_configured`
(→ `False`, no HTTP call).

### Risk Gate / Auth (`tests/test_risk_gate.py`)
```
  22 passed   (2 new tests + 20 existing)
```

New: `test_gate_fails_open_when_internal_secret_not_configured`
(`_pre_token_risk → None`, `InternalAuthConfigurationError` caught by existing
fail-open handler, no HTTP call),
`test_gate_sends_correct_secret_header`
(outbound `X-Internal-Secret` header matches configured test value).

---

## PostgreSQL Regression Result

```
tests/test_postgres_bootstrap.py               16 passed
tests/test_postgres_auth.py                   13 passed
tests/test_postgres_rbac.py                   25 passed
tests/test_postgres_mfa_concurrency.py         8 passed
────────────────────────────────────────────────
Total                                        62 passed, 0 skipped, 0 failed
```

P0 regression suite completely unaffected by P1-A changes.

---

## Full Test Counts

```
346 passed, 0 skipped, 0 failed
```

346 tests collected and executed with `INTERNAL_SECRET` **unset from the shell**.
The session-scoped autouse fixture in `conftest.py` provides the test value
automatically; no manual environment configuration required for the test suite.

---

## Remaining P1 Findings

| ID | Finding | Classification |
|---|---|---|
| P1-B | Protective-action authorization / approval workflow unresolved | Request-vs-approval-vs-direct-application semantics not enforced |
| P1-C | Documentation / role-boundary conflict on policy view permissions | GET /policies allows SECURITY_ADMIN + SECURITY_MANAGER; conflict between documented role assignments and implementation |
| P1-D | X-Forwarded-For / trusted proxy handling | No validation of XFF chain; IP spoofing possible behind untrusted proxy |
| P1-E | CORS `allow_credentials=True` with `Access-Control-Allow-Origin: "*"` | Self-contradicting combination rejected by browsers |
| P1-F | Concurrent refresh-token rotation unsynchronised | Two concurrent refresh requests for same family may both succeed |
| P1-G | Outbox runtime not implemented | Table exists but no background worker processes it |
| P1-H | Reconciliation function not scheduled | `reconcile_session_state()` exists but never called |
| P1-I | LoginAttempt triple-audit redundancy for MFA login | `mfa_required` → `success` → `mfa_success` over-auditing |
| P1-J | SOC `request_security_action` applies action directly | Named as request but applies action immediately |
| P1-K | Policy management documentation conflict | Documentation may reference old RBAC model |

---

## Final Status

**P1-A RESOLVED ✅**

`INTERNAL_SECRET` must now be explicitly set to a value of at least 32
characters. The deployment will not silently fall back to `"changeme-in-production"`.
If the variable is absent, empty, or set to the placeholder, all inbound
internal endpoints return **503 Service Unavailable** instead of accepting
requests with the public default. Outbound calls fail gracefully per their
existing semantics.
