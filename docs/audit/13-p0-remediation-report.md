# Sentinel Auth — P0 Remediation Audit Report

**Repository:** Albert-Tuan/sentinel-auth
**Branch:** dev
**Audit Date:** Wednesday Oct 7, 2026
**Auditor:** Automated P0 Audit
**Repository HEAD:** `fee8221f3d6ab996d0dbd6576a16fa9f357ea6cc`
**Parent HEAD:** `d48bc166ae01cb636aec002f8a3962cb46e1588a`
**Commit:** `fee8221` — `fix(auth): make MFA verification atomic`

---

## Repository State

| Item | Value |
|---|---|
| Branch | `dev` |
| HEAD SHA | `fee8221f3d6ab996d0dbd6576a16fa9f357ea6cc` |
| Parent SHA | `d48bc166ae01cb636aec002f8a3962cb46e1588a` |
| Working tree | **CLEAN** (no uncommitted changes) |
| New files | `tests/test_postgres_mfa_concurrency.py` |

---

## P0-01 — PostgreSQL Schema / Bootstrap

**Verdict: VERIFIED ✅**

### Schema Topology

| Schema | Tables | View |
|---|---|---|
| `schema-core-v3.3.sql` | 13 | 0 |
| `schema-detection-v3.3.sql` | 7 | 0 |
| `schema-ml-service-v3.3.sql` | 3 | 1 (`local_ml_stats`) |
| **Total** | **23** | **1** |

### Evidence

1. **Clean bootstrap:** `DROP SCHEMA IF EXISTS public CASCADE` + all three schema files applied sequentially — tested in `test_postgres_bootstrap.py`.
2. **Partial unique index — single active policy:** `CREATE UNIQUE INDEX idx_policies_single_active ON policies ((1)) WHERE is_active = TRUE` — no volatile `NOW()`.
3. **Partial unique index — single production model:** `CREATE UNIQUE INDEX idx_model_versions_single_active_production ON model_versions ((1)) WHERE is_production = TRUE AND status = 'active'` — no volatile `NOW()`.
4. **Partial index — active policies:** `CREATE INDEX idx_policies_active ON policies(is_active) WHERE is_active = TRUE` — no volatile `NOW()`.
5. **Policy `updated_at`:** Both SQL schema (`trg_policies_updated_at` BEFORE UPDATE trigger using `NOW()`) and ORM model (`app/models.py:480` — `DateTime(timezone=True)` with `onupdate=now_utc`) are present and match.
6. **Policy update trigger:** Valid `BEFORE UPDATE ON policies FOR EACH ROW EXECUTE FUNCTION update_updated_at_column()`.
7. **No subquery CHECK constraints:** Verified — no `CHECK` constraint in any schema file contains a `SELECT` subquery.
8. **No volatile `NOW()` in index predicates:** All partial indexes use static `WHERE` clauses (`is_active = TRUE`, `is_production = TRUE AND status = 'active'`).

---

## P0-02 — `_create_session` Undefined `now`

**Verdict: VERIFIED ✅**

### Evidence

- `app/auth.py:457` — `_create_session()` receives `db` from caller.
- Line 471: `now = datetime.now(timezone.utc)` — defined **before** `Session` and `LoginAttempt` construction.
- `expires_at=now + timedelta(hours=1)` — consistent `now` used throughout.
- `timestamp=now` on `LoginAttempt` — same value.
- `last_activity_at=now` on `Session` — same value.
- `db.flush()` used at line 503 to obtain generated IDs; **no `db.commit()`** inside the function.
- Caller (`login()` no-MFA path at line 452) owns the single `db.commit()` boundary.
- `timezone` is imported at line 11, `datetime` at line 10 — no undefined references.

### No P0-05 Regression on No-MFA Path

- `login()` no-MFA path (line 452): `result, _ = await _create_session(...)` + `db.commit()` — exactly one commit.
- `login()` MFA path (line 657): same pattern, single commit at line 671.
- `_create_session()` returns `(LoginResponse, LoginAttempt)` — caller can add additional audit events before committing.

---

## P0-03 — MFA `bound_ip` PostgreSQL / Design Mismatch

**Verdict: VERIFIED ✅**

### Evidence

1. **SQL `INET` type:** `infra/postgres/schema-core-v3.3.sql:170` — `bound_ip INET` — correct PostgreSQL type for IPv4/IPv6.
2. **ORM `inet_type()`:** `app/models.py:233` — `Column(inet_type(), nullable=True)` where `inet_type()` returns `INET().with_variant(Text(), "sqlite")` — maps correctly to PostgreSQL `INET`.
3. **Raw IP stored (not SHA256):** `app/auth.py:404` — `bound_ip=normalize_ip(client_ip)` — no `hash_ip()` call. Raw canonical IP stored.
4. **`normalize_ip()` uses `ipaddress` module:** `app/auth.py:93-100` — Python stdlib `ipaddress.ip_address()` canonicalizes IPv6 representations.
5. **IP binding enforced in `mfa_verify`:** `app/auth.py:632` — `if normalize_ip(mfa_txn.bound_ip) != normalize_ip(client_ip)` — 403 on mismatch, checked inside row lock.
6. **`hash_ip()` removed:** No `hash_ip()` calls remain anywhere in the Python source.

---

## P0-04 — Privileged Human Authentication + RBAC

**Verdict: VERIFIED ✅**

### Evidence

1. **Stateful bearer tokens:** `app/auth.py:479-489` creates `Session` with `access_token_hash`. `app/authz.py:93-100` validates bearer token against `sessions.access_token_hash` via `hash_token()`.
2. **Session invariant:** `app/authz.py:93-100` checks `SessionModel.revoked_at.is_(None)` AND `SessionModel.expires_at > datetime.utcnow()`. `app/authz.py:111-120` verifies User exists and `user.status == "active"`.
3. **Role lookup from DB on every request:** `app/authz.py:125-130` runs a fresh `db.query(Role)` join on every call to `get_current_auth_context()` — no caching.
4. **Role removal takes immediate effect:** Because role lookup hits DB every request, revocation affects the existing token on the very next request.

### Route Permissions

| Route | Required | Implemented | Result |
|---|---|---|---|
| `GET /api/v1/alerts` | SOC_ANALYST + SECURITY_MANAGER | SOC_ANALYST + SECURITY_MANAGER | ✅ |
| `GET /api/v1/alerts/{id}` | SOC_ANALYST + SECURITY_MANAGER | SOC_ANALYST + SECURITY_MANAGER | ✅ |
| `GET /api/v1/alerts/{id}/evidence` | SOC_ANALYST + SECURITY_MANAGER | SOC_ANALYST + SECURITY_MANAGER | ✅ |
| `GET /api/v1/alerts/{id}/timeline` | SOC_ANALYST + SECURITY_MANAGER | SOC_ANALYST + SECURITY_MANAGER | ✅ |
| `POST /api/v1/alerts` (acknowledge) | SOC_ANALYST + SECURITY_MANAGER | SOC_ANALYST + SECURITY_MANAGER | ✅ |
| `POST /api/v1/alerts/{id}/resolve` | SOC_ANALYST + SECURITY_MANAGER | SOC_ANALYST + SECURITY_MANAGER | ✅ |
| `POST /api/v1/alerts/{id}/assign` | SOC_ANALYST + SECURITY_MANAGER | SOC_ANALYST + SECURITY_MANAGER | ✅ |
| `POST /api/v1/alerts/{id}/actions` | SOC_ANALYST only | SOC_ANALYST + SECURITY_MANAGER | ⚠️ P1 |
| `POST /api/v1/alerts/{id}/timeline` | SOC_ANALYST + SECURITY_MANAGER | SOC_ANALYST + SECURITY_MANAGER | ✅ |
| `GET /api/v1/policies` | SOC_ANALYST + SECURITY_MANAGER | SECURITY_ADMIN + SECURITY_MANAGER | ⚠️ P1 |
| `POST /api/v1/policies/{id}/activate` | SECURITY_ADMIN only | SECURITY_ADMIN only | ✅ |
| Internal (`/api/v1/internal/*`) | X-Internal-Secret | X-Internal-Secret | ✅ |

### `/alerts` Route Count

`app/alerts.py` defines **exactly 9 routes** — CLEAN.

### Internal Service Authentication

`app/internal_actions.py:46`, `app/detection.py:104`, `app/ml.py:56` — all use `verify_internal_secret(x_internal_secret)` checking `X-Internal-Secret` header. Service authentication is separate from human bearer tokens.

### `assigned_to_id` FK Target

`app/models.py:693` — `assigned_to_id` FK references `soc_analysts.id` (UUID PK), not `users.id` — CLEAN.

---

## P0-05 — Concurrent MFA OTP Consumption

**Verdict: VERIFIED ✅**

### Evidence

1. **Row lock acquired first:** `app/auth.py:543-550` — `db.query(MfaTransaction).filter(MfaTransaction.id == request.session_id).with_for_update().first()` — lock obtained **before** any state inspection.
2. **State inspected after lock:** Steps 2-5 all occur while holding the row lock:
   - `completed` → 409 (line 560)
   - `failed` → 409 (line 563)
   - `expired` → 401 (line 566)
   - `expires_at <= now` → set `expired`, 401 (line 570)
3. **Wrong OTP serialised:** Lines 599-615 — `mfa_txn.fail_count += 1` while holding lock, commit on each failure, `status = failed` when `fail_count >= 3`.
4. **`_create_session()` does not commit:** Line 503 — `db.flush()` only; callers own `db.commit()`.
5. **Atomic success commit:** Lines 644-671 — single `db.commit()` at line 671 atomically includes:
   - `mfa_txn.status = "completed"`
   - `notification.verified_at = now`
   - `user.detection_mfa_once = False` (if `mfa_type == "one_time"`)
   - Session creation via `_create_session()`
   - `LoginAttempt(outcome="mfa_success")`
6. **IP binding inside lock:** Lines 620-640 — P0-03 check preserved inside the locked section.
7. **Row-scoped only:** Locked by `MfaTransaction.id == request.session_id` — independent transactions do not block each other.

### Concurrency Test Quality

`tests/test_postgres_mfa_concurrency.py` uses:
- `ThreadPoolExecutor` with 2-3 concurrent workers
- `threading.Barrier` to synchronize simultaneous start
- Independent `sqlalchemy.Engine` and `sessionmaker` per thread (no shared session)
- `contextvars.ContextVar` for thread-safe IP/OTP injection (avoids module-level lambda patching contamination)

**Test C (concurrent correct OTP):** `ThreadPoolExecutor(2)` + `threading.Barrier(2)` — same `txn_id`, same OTP, concurrent execution. Expected: exactly 1 × 200, 1 × 409, 1 session.

**Test D (concurrent wrong OTP):** `ThreadPoolExecutor(3)` + `threading.Barrier(3)` — same `txn_id`, different wrong OTPs. Expected: 3 × 401, `fail_count == 3`, `status == failed`, 0 sessions.

**Test H (independent transactions):** Two separate `txn_id`s on two users with different IPs. Expected: 2 × 200, no cross-blocking.

---

## PostgreSQL Test Matrix

| Test File | Collected | Passed | Skipped | Failed |
|---|---|---|---|---|
| `test_postgres_bootstrap.py` | 16 | 16 | 0 | 0 |
| `test_postgres_auth.py` | 13 | 13 | 0 | 0 |
| `test_postgres_rbac.py` | 25 | 25 | 0 | 0 |
| `test_postgres_mfa_concurrency.py` | 8 | 8 | 0 | 0 |
| **Total** | **62** | **62** | **0** | **0** |

*Note: earlier audit runs showed `test_postgres_rbac.py` skipped because `POSTGRES_HOST`, `POSTGRES_DB`, `POSTGRES_USER`, or `POSTGRES_PASSWORD` was unset. With all four environment variables set, all 62 PostgreSQL tests pass.*

---

## Full Suite Results

| Suite | Collected | Passed | Skipped | Failed |
|---|---|---|---|---|
| `pytest -q` (all tests) | 305 | 305 | 0 | 0 |

**Total: 305 passed, 0 skipped, 0 failed.**

---

## Residual P0 Regression Searches

| Search | Result |
|---|---|
| `hash_ip()` | CLEAN — not found anywhere |
| `x_internal_token` on human SOC routes | CLEAN — not found |
| Unauthenticated `/alerts` routes | CLEAN — all 9 routes require authentication |
| Duplicate `hash_token` definitions | CLEAN — one definition in `app/authz.py` |
| `bound_ip` hash storage | CLEAN — raw canonical IP via `normalize_ip()` |
| `_create_session` internal `commit` | CLEAN — `db.flush()` only, caller commits |
| MFA query filtering `pending` before lock | CLEAN — query by `id` only, state checked after lock |
| `User.id` written into `SocAnalyst` FK fields | CLEAN — `assigned_to_id` references `soc_analysts.id`, not `users.id` |
| `SECURITY_ADMIN` on SOC alert routes | CLEAN — not found |
| Volatile `NOW()` in index predicates | CLEAN — all partial indexes use static `WHERE` |
| Subquery `CHECK` constraints | CLEAN — no `CHECK` constraints contain `SELECT` subqueries |

---

## Open Non-P0 Findings

These are **NOT** remediated in this audit. Listed for completeness.

### P1 — High

| # | Finding | Location | Classification |
|---|---|---|---|
| ~~P1-A~~ ✅ | `INTERNAL_SECRET` falls back to `"changeme-in-production"` when env var unset → **RESOLVED** | `app/auth.py`, `app/detection.py`, `app/internal_actions.py`, `app/ml.py` → now `app/internal_auth.py` | Centralised in `app/internal_auth.py`; `get_internal_secret()` raises `InternalAuthConfigurationError` on missing/empty/placeholder/short values; `verify_internal_secret()` returns 503 on misconfiguration; `secrets.compare_digest()` used; see `docs/audit/14-p1-remediation.md` |
| P1-B | Protective-action authorization / approval workflow unresolved | `app/alerts.py:641` | docs/05 UC-DE-13 names SOC Analyst as primary actor; docs/06 grants SECURITY_MANAGER `APPROVE_ACTION` and lists them as a UC-DE-13 participant; implementation allows both SOC_ANALYST and SECURITY_MANAGER to directly apply actions via `POST /alerts/{id}/actions` — the distinction between requesting an action, approving it, and directly applying it is not enforced |
| P1-C | Documentation / role-boundary conflict on policy view permissions | `app/detection.py:985` | docs/05 UC-DE-15 assigns primary actor = Security Admin; docs/06 grants SECURITY_MANAGER `MANAGE_POLICIES`/UC-DE-15; Core docs assign rule versioning to Security Administrator; implementation allows SECURITY_ADMIN + SECURITY_MANAGER on GET /policies; SOC_ANALYST has no UC-DE-15 permission in any canonical doc; conflict is between documented role assignments and implementation rather than a missing SOC_ANALYST permission |
| P1-D | X-Forwarded-For / trusted proxy handling | `app/auth.py:64-66` | No validation of XFF chain; IP spoofing possible behind untrusted proxy |

### P1 — Medium

| # | Finding | Location | Classification |
|---|---|---|---|
| P1-E | CORS configuration uses `"*"` with `allow_credentials=True` | `app/main.py` | `Access-Control-Allow-Origin: "*"` with `allow_credentials=True` is rejected by browsers per the Fetch standard; the combination is self-contradicting |
| P1-F | Concurrent refresh-token rotation not synchronised | `app/auth.py` (refresh endpoint) | Two concurrent refresh requests for the same token family may both succeed, creating fork |
| P1-G | Outbox runtime not implemented | `app/main.py` / startup | Outbox table exists but no background worker processes it |
| P1-H | Reconciliation function not scheduled | `app/main.py` / startup | `reconcile_session_state()` exists but never called |

### P1 — Low / Documentation

| # | Finding | Location | Classification |
|---|---|---|---|
| P1-I | LoginAttempt semantic redundancy: MFA login creates 3 audit rows (`mfa_required` → `success` → `mfa_success`) | `app/auth.py` | Semantic over-auditing; not a security defect |
| P1-J | SOC "request-action" vs implementation directly applying action | `app/alerts.py` | `POST /alerts/{id}/actions` named `request_security_action` but applies action directly |
| P1-K | Policy management documentation conflict | `docs/` | Documentation may reference old RBAC model |

---

## Implementation Readiness

| Criterion | Status |
|---|---|
| All 5 canonical P0 blockers verified | ✅ |
| Zero P0 regressions in source | ✅ |
| Full test suite green | ✅ (305/305 passed, 0 skipped, 0 failed) |
| PostgreSQL concurrency invariants proven | ✅ (8/8 concurrency tests) |
| Working tree clean | ✅ |
| No unverified production behavior changes | ✅ |

---

## Final Verdict

**P0_REMEDIATION_VERIFIED ✅**

All five P0 canonical blockers are independently verified as resolved on HEAD `fee8221`. The implementation is production-ready with respect to P0 scope.

P1-A (unsafe default INTERNAL_SECRET) has been remediated: see `docs/audit/14-p1-remediation.md`. The remaining P1 findings (P1-B through P1-K) are outside P0 scope and listed for post-audit prioritisation.
