# M13 — Acceptance Matrix

> Sentinel Auth v3.3 · Milestone M13.0 – M13.2
> Every acceptance criterion of the milestone, and how it was verified.

This matrix lists every criterion of the M13 milestone, the artefact
that satisfies it and the command that proves it.

Every "verified" entry below was run against the live demo stack on
2026-11-25.

---

## 1. The summary

| # | Area | Criteria | Verified | How |
|---|---|---|---|---|
| A | The demo stack | 10 | 10 | `scripts/demo_stack.sh` |
| B | The fixtures | 8 | 8 | `scripts/demo_seed_demo.py` |
| C | The scenarios | 9 | 9 | `scripts/demo_scenarios.py` |
| D | The safety | 9 | 9 | `tests/test_demo_fixtures.py` |
| E | The regression | 12 | 12 | `pytest tests/` |
| | **Total** | **48** | **48** | |

The six demo scenarios contribute **55 individual checks**, all passing,
twice in a row — the second run proves they are re-runnable.

---

## 2. Area A — The demo stack

| # | Criterion | Artefact | Verified by |
|---|---|---|---|
| A1 | One command brings up the whole stack | `scripts/demo_stack.sh start` | the command exits `0` and prints the endpoints |
| A2 | The three logical databases are separate | `docker-compose.demo.yml`, `.env.demo` | `psql \l` shows `sentinel_core_demo`, `sentinel_detection_demo`, `sentinel_ml_demo` |
| A3 | The schema is applied to all three | `scripts/ci_bootstrap_postgres.sh` | 13 + 7 + 3 base tables, cross-context isolation verified |
| A4 | Redis is part of the stack | `docker-compose.demo.yml` | the container reports `healthy` |
| A5 | The SMTP sink delivers the real OTP | `scripts/ci_smtp_sink.py` | the captured message is in `demo-otp.log` with the code |
| A6 | The port conflict is detected before the start | `check_ports_free()` in `demo_stack.sh` | a foreign process on `APP_PORT` fails the start with the owner's name |
| A7 | The stack recognises its own containers | `port_held_by_own_container()` | the compose project label is matched, no false conflict |
| A8 | The logs of every component are separated | `${DEMO_STATE_DIR}` | `api.log`, `web.log`, `smtp.log`, `demo-otp.log` |
| A9 | `stop` keeps the data, `restart` keeps the data | `cmd_stop`, `cmd_restart` | the row counts are **identical** before and after the restart |
| A10 | `reset` is the only destructive command and it asks first | `cmd_reset` | a typed confirmation is required |

### A9 in detail

The row counts before and after `scripts/demo_stack.sh restart`:

| Table | Before | After |
|---|---|---|
| `users` | 4 | 4 |
| `sessions` | 121 | 121 |
| `user_trusted_devices` | 10 | 10 |
| `alerts` | 9 | 9 |
| `login_attempts` | 223 | 223 |
| `policies` | 10 | 10 |
| `inference_logs` | 7 | 7 |
| `model_versions` | 2 | 2 |

---

## 3. Area B — The fixtures

| # | Criterion | Verified by |
|---|---|---|
| B1 | Four accounts with four different roles | `test_the_four_accounts_exist_with_their_roles` |
| B2 | `demo_admin` really carries the permanent MFA flag | `test_the_admin_account_really_requires_mfa` |
| B3 | The identifiers are deterministic (UUIDv5) | `test_the_manifest_is_complete_and_deterministic` |
| B4 | Seeding twice leaves the same state | `test_the_seed_is_idempotent` |
| B5 | Every alert status and risk level is present | `test_every_alert_status_and_risk_level_is_present` |
| B6 | Exactly one policy is active | `test_exactly_one_active_policy` |
| B7 | The cleanup removes only the fixture rows | `test_the_cleanup_removes_the_fixture_rows` |
| B8 | The cleanup leaves the stack usable and the ids come back | `test_the_cleanup_leaves_the_stack_usable` |

### The seeded alerts

| Key | Risk level | Status | What it demonstrates |
|---|---|---|---|
| `critical_open` | critical | open | the alert to work on first |
| `high_acknowledged` | high | acknowledged | an alert that is already owned |
| `medium_open_ruleless` | medium | open | the rule-only fallback — **no ML score** |
| `low_resolved` | low | resolved | a finished alert with its resolution |
| `low_false_positive` | low | false positive | a false positive, correctly labelled |

---

## 4. Area C — The scenarios

| # | Criterion | Scenario | Checks |
|---|---|---|---|
| C1 | The authentication flow, including the MFA handshake over a real SMTP hop | A | 8 |
| C2 | The trusted-device flow, from the request to the completed login | B | 7 |
| C3 | The SOC investigation flow, from the list to the assignment | C | 12 |
| C4 | A protective action, and the honest handling of a failure | D | 9 |
| C5 | The policy lifecycle, including the immutability of an active policy | E | 11 |
| C6 | The manager analytics, and the honest reporting of the ML model state | F | 8 |
| C7 | The scenarios are re-runnable | all | two consecutive full runs, 55/55 both times |
| C8 | The failure case is a real 502, not a simulated one | D | the alert points at a subject Core does not know |
| C9 | The demo does not fake the states it cannot reach | D, F | the 502 says "NOT enforced"; the dashboard reports `model_status: error` |

### The run

```
=== Scenario A — Authentication ===        8
=== Scenario B — Device trust ===           7
=== Scenario C — SOC investigation ===     12
=== Scenario D — Protective actions ===     9
=== Scenario E — Policy management ===     11
=== Scenario F — Manager analytics ===      8

OK: all 55 check(s) passed.
```

---

## 5. Area D — The safety

| # | Criterion | Verified by |
|---|---|---|
| D1 | The seed refuses a database without the `_demo` marker | `test_a_url_without_a_database_name_is_refused`, `test_the_demo_marker_is_the_one_the_stack_uses` |
| D2 | The guard runs before anything connects | the guard is called before the engines are created |
| D3 | The seed never issues a bulk delete | `test_the_cleanup_only_touches_the_rows_of_the_fixtures` |
| D4 | The cleanup removes only the fixture rows | `test_the_cleanup_removes_the_fixture_rows` |
| D5 | The ML model is never promoted | `test_the_ml_model_is_never_promoted` |
| D6 | No secret is written to a tracked file | `.env.demo` is gitignored; `.env.demo.example` holds placeholders only |
| D7 | The internal secret is at least 32 characters and not a placeholder | `scripts/demo_stack.sh` refuses to start otherwise |
| D8 | The frontend never reaches the demo database directly | the API owns every database; the browser only calls the API |
| D9 | The wildcard proxy list is refused | `FORWARDED_ALLOW_IPS` is checked |

### D6 in detail

```
$ git check-ignore -v .env.demo
.gitignore:41:.env.*    .env.demo

$ git check-ignore -v .ci/demo/demo-otp.log
.gitignore:22:.ci/    .ci/demo/demo-otp.log
```

The only change to `.gitignore` is one line:

```diff
 .env
 .env.*
 !.env.example
+!.env.demo.example
```

---

## 6. Area E — The regression

| # | Criterion | Result |
|---|---|---|
| E1 | The full test suite passes | `1225 passed`, 0 failed, **0 skipped** |
| E2 | The M13 fixture tests pass | 26 passed |
| E3 | `git diff --check` reports nothing | clean |
| E4 | The new scripts compile | `python3 -m py_compile` clean, `bash -n` clean |
| E5 | The demo stack survives a restart with its data | identical row counts |
| E6 | The frontend type-checks | `tsc -b --noEmit` clean |
| E7 | The frontend lints | `eslint .` clean |
| E8 | The frontend unit tests pass | 18 files, 265 tests passed |
| E9 | The frontend real-HTTP integration tests pass | 3 files, 50 tests passed |
| E10 | The M10 HTTP smoke script passes | 79 passed, 0 failed |
| E11 | The deployment verification passes | 67 passed, 0 failed |
| E12 | The production frontend build succeeds | `vite build` ✓, 1.69s |

### E9 in detail

The integration suite talks to a LIVE backend over real HTTP, so it
needs its own backend, its own SMTP sink and its own fixture users
(`m12analyst`, `m12admin`, `m12manager`, `m12plain`). The demo stack
uses the `demo_*` accounts, so the suite was pointed at a dedicated
instance:

```bash
# the fixtures, in the disposable test databases
CORE_DATABASE_URL=postgresql+psycopg2://…/sentinel_core_test \
  python scripts/ci_seed_frontend_users.py
DETECTION_DATABASE_URL=postgresql+psycopg2://…/sentinel_detection_test \
  python scripts/ci_seed_frontend_alerts.py

# the SMTP sink and the backend
python scripts/ci_smtp_sink.py --host 127.0.0.1 --port 1025 --log /tmp/m13_otp_capture.log
CORE_DATABASE_URL=… DETECTION_DATABASE_URL=… DETECTION_URL="" \
  python -m uvicorn app.main:app --host 127.0.0.1 --port 58001

# the suite
cd frontend
M12_API_ORIGIN=http://127.0.0.1:58001 \
M12_API_ROOT=http://127.0.0.1:58001/api/v1 \
M12_OTP_LOG=/tmp/m13_otp_capture.log \
M12_DATABASE_URL=postgresql://…/sentinel_core_test \
M12_PASSWORD=… M12_MFA_PASSWORD=… M12_MANAGER_PASSWORD=… \
M12_ADMIN_PASSWORD=… M12_PLAIN_PASSWORD=… \
  npm run test:integration
```

`M12_API_ORIGIN` and `M12_API_ROOT` MUST agree — the suite refuses to
run when they disagree, so half the requests can never go to one
backend and the other half to another.

### The full evidence table

| Suite | Baseline required | Result | Delta |
|---|---|---|---|
| Backend regression | ≥ 1199 passed | **1225 passed**, 0 failed, 0 skipped | +26 (the new fixture tests) |
| HTTP smoke | ≥ 79 passed | **79 passed**, 0 failed | — |
| Frontend unit/component | ≥ 265 passed | **265 passed**, 0 failed | — |
| Frontend integration | ≥ 50 passed | **50 passed**, 0 failed | — |
| Deployment verification | pass | **67 passed**, 0 failed | — |
| TypeScript strict | pass | pass | — |
| Lint | pass | pass | — |
| Production build | pass | pass | — |
| Demo scenarios | — | **55 checks**, 2 consecutive runs | — |
| `git diff --check` | clean | clean | — |
| Secret scan | clean | clean | — |

### E1 in detail

```
collected=1225 passed=1225 failed=0 skipped=0 error=0 xfailed=0
```

(The suite needs its own disposable databases. `scripts/ci_bootstrap_postgres.sh`
creates `sentinel_core_test`, `sentinel_detection_test`,
`sentinel_ml_test` and `sentinel_legacy_test`; the M13 fixture tests
need the three `*_demo` databases instead, which
`scripts/ci_bootstrap_demo_databases.sh` creates.)

The **zero-skip** policy matters here. The M13 fixture tests skip
themselves when the demo databases are absent, and a skip is a silent
hole in the coverage — so CI treats it as a failure. That is exactly
what happened on the first CI run: 12 skips, therefore a red build. The
fix was to provision the demo databases in CI, not to relax the
policy.

The two bootstrap scripts carry **opposite** guards on purpose:

| Script | Marker | Refuses to touch |
|---|---|---|
| `scripts/ci_bootstrap_postgres.sh` | `_test` | any database without `_test` |
| `scripts/ci_bootstrap_demo_databases.sh` | `_demo` | any database without `_demo` |

The demo seed also refuses to write to a database without the `_demo`
marker, and the CI bootstrap refuses to touch a database without the
`_test` marker. Neither guard was weakened to accommodate the other.

---

## 7. The problems that were found and fixed

The milestone surfaced five defects. Each one was found by running the
system, not by reading it.

| # | Problem | Symptom | Fix |
|---|---|---|---|
| 1 | The CORS origin glob `*/*/*` matched a port that was empty | the browser was refused | the pattern became `*///*` |
| 2 | A rootless container could not read a bind mount from a removable path | `Permission denied` during the PostgreSQL init | the schema is staged into `~/.cache/sentinel-auth-demo/postgres` and mounted `:ro,z` |
| 3 | `npm run dev` wrapped Vite, so the signal never reached it | the port stayed bound, orphan `esbuild` workers | the stack starts `./node_modules/.bin/vite` directly under `setsid` and signals the group |
| 4 | The unique index of the single active policy was evaluated against the pending state | `idx_policies_single_active` was violated | the existing active policy is deactivated and **flushed** before the new one is written |
| 5 | The circular foreign key between `login_attempts` and `alerts` | the insert failed | the attempt is inserted with `primary_alert_id = None`, then the alert, then the link |

And three more that the scenario work surfaced:

| # | Problem | Symptom | Fix |
|---|---|---|---|
| 6 | The OTP log path was relative, so the sink and the scenario script read different files | "no OTP arrived" although the code was in the log | the path is resolved against the repository root and written to `otp-log.path` |
| 7 | The OTP was read from the whole log, so a stale code could be used | `Invalid MFA code` | the reader is offset-based: the size is taken before the login |
| 8 | The login rate limit (5 per minute) tripped the scenario | `429 Too many requests` | the scenario retries and says so |

And one that only the CI run surfaced:

| # | Problem | Symptom | Fix |
|---|---|---|---|
| 9 | The M13 fixture tests skipped themselves when the demo databases were absent | the CI build went red with `skipped=12` — a skip is a silent hole in the coverage | `scripts/ci_bootstrap_demo_databases.sh` provisions the three demo databases in CI, with its own `_demo` guard |

Defect 9 was **not** fixed by relaxing the zero-skip policy. The policy
stayed; the infrastructure was fixed.

---

## 8. The CI result

```
Test & Smoke (py3.11)             pass
Test & Smoke (py3.12)             pass
Frontend (unit & build)           pass
Frontend (real HTTP integration)  pass

collected=1225 passed=1225 failed=0 skipped=0 error=0 xfailed=0
```

---

## 9. How to reproduce the whole matrix

```bash
# 1. the stack
cp .env.demo.example .env.demo
#    fill in POSTGRES_PASSWORD and INTERNAL_SECRET
scripts/demo_stack.sh start
scripts/demo_stack.sh status

# 2. the fixtures
scripts/demo_seed_demo.py --seed --manifest-out .ci/demo/fixture-manifest.json

# 3. the scenarios
scripts/demo_scenarios.py --all

# 4. the safety
pytest tests/test_demo_fixtures.py -q

# 5. the regression
scripts/ci_bootstrap_postgres.sh
scripts/ci_bootstrap_demo_databases.sh
pytest tests/ -q

# 6. the diff
git diff --check
```

---

## 10. Related documents

* [M13-FULLSTACK-DEPLOYMENT.md](M13-FULLSTACK-DEPLOYMENT.md) — the demo stack
* [M13-DEMO-FIXTURES.md](M13-DEMO-FIXTURES.md) — the reproducible fixtures
* [M13-DEMO-SCENARIOS.md](M13-DEMO-SCENARIOS.md) — the six demo scenarios
