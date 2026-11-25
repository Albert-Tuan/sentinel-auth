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
| D | The safety | 15 | 15 | `tests/test_demo_fixtures.py`, `tests/test_ci_demo_database_safety.py` |
| E | The regression | 12 | 12 | `pytest tests/` |
| | **Total** | **54** | **54** | |

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
| D10 | The CI bootstrap cannot drop the local demo stack's databases | the CI databases carry a separate `_ci_demo` marker |
| D11 | The CI bootstrap refuses a server that holds the demo stack's data | `guard_disposable_server` verifies the real state |
| D12 | The CI bootstrap refuses without a matching acknowledgement | `guard_acknowledged` compares against the hard-coded allowlist |
| D13 | No single environment variable disables the protection | the declaration and the acknowledgement are separate inputs; the server state is checked regardless |
| D14 | The CI run stays non-interactive | the CI environment supplies the declaration and the acknowledgement |
| D15 | The local demo stack keeps its data across stop/restart | the row counts are identical before and after |
| D16 | The safety suite never skips itself on a runner without the PostgreSQL binaries | the suite falls back to a throwaway container; 51 passed, 0 skipped |
| D17 | The safety suite's own environment cannot authorise a run the test did not authorise | the harness strips `DEMO_CI_DISPOSABLE_SERVER` and `DEMO_CI_ACK` from every subprocess |

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
| E1 | The full test suite passes | `1276 passed`, 0 failed, **0 skipped** |
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
| E12 | The production frontend build succeeds | `vite build` ✓, 1.53s |
| E13 | The CI database safety tests pass | 51 passed, 0 skipped |

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
| Backend regression | ≥ 1199 passed | **1276 passed**, 0 failed, 0 skipped | +77 (26 fixture + 51 safety tests) |
| HTTP smoke | ≥ 79 passed | **79 passed**, 0 failed | — |
| Frontend unit/component | ≥ 265 passed | **265 passed**, 0 failed | — |
| Frontend integration | ≥ 50 passed | **50 passed**, 0 failed | — |
| Deployment verification | pass | **67 passed**, 0 failed | — |
| TypeScript strict | pass | pass | — |
| Lint | pass | pass | — |
| Production build | pass | pass | — |
| Demo scenarios | — | **55 checks**, 2 consecutive runs | — |
| CI database safety | — | **51 passed** | new |
| `git diff --check` | clean | clean | — |
| Secret scan | clean | clean | — |

### E1 in detail

```
collected=1276 passed=1276 failed=0 skipped=0 error=0 xfailed=0
```

(The suite needs its own disposable databases. `scripts/ci_bootstrap_postgres.sh`
creates `sentinel_core_test`, `sentinel_detection_test`,
`sentinel_ml_test` and `sentinel_legacy_test`; the M13 fixture tests
need the three `*_ci_demo` databases instead, which
`scripts/ci_bootstrap_demo_databases.sh` creates.)

The **zero-skip** policy matters here. The M13 fixture tests skip
themselves when the demo databases are absent, and a skip is a silent
hole in the coverage — so CI treats it as a failure. That is exactly
what happened on the first CI run: 12 skips, therefore a red build. The
fix was to provision the demo databases in CI, not to relax the
policy.

### The three database vocabularies

The repository now uses **three disjoint markers**, because three
different operations need three different safety boundaries:

| Script | Marker | Databases | Refuses to touch |
|---|---|---|---|
| `scripts/ci_bootstrap_postgres.sh` | `_test` | `sentinel_core_test`, … | anything without `_test` |
| `scripts/demo_stack.sh` (the local demo stack) | `_demo` | `sentinel_core_demo`, … | anything without `_demo` |
| `scripts/ci_bootstrap_demo_databases.sh` | `_ci_demo` | `sentinel_core_ci_demo`, … | anything without `_ci_demo` |

The third one is the most dangerous script in the repository — it DROPS
and RECREATES its databases — so it carries five independent,
fail-closed guards of its own. See section 7.

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

And one that the safety review surfaced — the most serious of them:

| # | Problem | Symptom | Fix |
|---|---|---|---|
| 10 | The CI bootstrap used the **same database names** as the local demo stack (`sentinel_*_demo`) | running it by hand on a developer machine DROPPED the running demo stack's data | the CI databases were renamed to `sentinel_*_ci_demo`, and the script gained five fail-closed guards |

Defect 10 was not theoretical: the local demo stack's three databases
were actually dropped during the verification of this fix, and they had
to be re-provisioned and re-seeded. The recovery is exactly what the
new guards make impossible in the first place.

And then two more that only the CI run itself surfaced — both of them
holes in the *test harness*, not in the guards:

| # | Problem | Symptom | Fix |
|---|---|---|---|
| 11 | The GitHub Actions runner has the `psql` client but neither `initdb` nor `pg_ctl`, so the throwaway server could not be started and the whole safety module skipped itself | the CI build went red with `skipped=51` — a skip is a silent hole in the coverage | the suite falls back to a throwaway `postgres:16-alpine` container, and the fixture that needs a server is no longer `autouse`, so the pure unit tests can never be skipped |
| 12 | The CI workflow exports `DEMO_CI_DISPOSABLE_SERVER` and `DEMO_CI_ACK` for the whole job, so the subprocesses the safety suite started **inherited** the authorisation | three tests observed the script PROCEEDING while claiming to prove that it refuses — the ambient acknowledgement authorised runs the test never authorised | the harness strips both variables from the environment it hands to the script, so every authorisation is stated explicitly by the test that wants it |

Defect 12 is worth stating plainly, because it is a subtle failure: a
test that asserts "the script refuses" can silently become a test that
asserts "the script proceeds", and it still passes as long as the
script's *own* behaviour is unchanged. The suite proved the opposite of
what it claimed. The fix makes the authorisation an explicit input of
every test instead of an inherited ambient value.

---

## 8. The safety of the CI bootstrap

`scripts/ci_bootstrap_demo_databases.sh` is the only script in the
repository that DROPs databases. It therefore carries five independent,
fail-closed guards. Each one refuses by default, and a bug in one does
not open a hole in the next.

| Layer | Guard | What it refuses |
|---|---|---|
| 1 | `guard_allowlisted` | a name outside the hard-coded allowlist — the allowlist **cannot** be widened from the environment |
| 2 | `guard_marked` | a name that does not end with `_ci_demo` |
| 3 | `guard_no_local_overlap` | a name that is one of the local demo stack's persistent databases |
| 4 | `guard_disposable_server` | a server that **actually holds** the local demo stack's databases, whatever the environment claims |
| 5 | `guard_acknowledged` | an acknowledgement that does not name exactly the three targets |

### No single environment variable disables the protection

This is the property the guards are designed around, and it is proved
by a test:

```bash
# The declaration alone does NOT get past layer 4.
DEMO_CI_DISPOSABLE_SERVER=true \
DEMO_CI_ACK="sentinel_core_ci_demo sentinel_detection_ci_demo sentinel_ml_ci_demo" \
bash scripts/ci_bootstrap_demo_databases.sh
```

against a server that holds `sentinel_core_demo`:

```
ERROR: refusing to run: the target server holds the local demo stack's
persistent database 'sentinel_core_demo'. ... Nothing was changed.
```

The declaration and the acknowledgement are **separate** inputs, the
acknowledgement must match the allowlist exactly, and layer 4 verifies
the **real state** of the server regardless of what either of them says.

### The CI run stays non-interactive

The CI environment supplies both inputs, so the pipeline never waits
for a human:

```yaml
DEMO_CI_DISPOSABLE_SERVER: "true"
DEMO_CI_ACK: >-
  sentinel_core_ci_demo sentinel_detection_ci_demo sentinel_ml_ci_demo
```

A manual run asks instead, and says exactly what it is about to do:

```
This script DROPS and RECREATES the following databases:
  - sentinel_core_ci_demo
  - sentinel_detection_ci_demo
  - sentinel_ml_ci_demo

Type the three names above, separated by spaces, to proceed:
```

### The regression tests

`tests/test_ci_demo_database_safety.py` — 51 tests:

* every layer refuses, proven by calling the guard directly (the script
  is *sourced*, so no SQL runs);
* an unauthorised run against a real PostgreSQL server creates nothing;
* a wrong acknowledgement leaves an existing database untouched;
* the declaration alone does not bypass the server check;
* an authorised run provisions the three databases with the canonical
  schema, and is idempotent;
* a manual run asks, and a wrong confirmation changes nothing.

Two properties of the harness itself are proven too, because both of
them were violated at some point during this work:

* the suite never skips itself. The pure unit tests need no server at
  all, and the server-backed tests start a throwaway PostgreSQL from
  the local binaries **or** from a `postgres:16-alpine` container,
  whichever the machine has. The GitHub Actions runner has only the
  `psql` client, so the container is what it uses — and 51 passed, 0
  skipped is the figure that proves it.
* the suite never inherits its authorisation. The CI workflow exports
  `DEMO_CI_DISPOSABLE_SERVER` and `DEMO_CI_ACK` for the whole job; the
  harness strips both from the environment it hands to the script, so
  a test can only observe a refusal it provoked itself.

---

## 9. The CI result

Run: <https://github.com/Albert-Tuan/sentinel-auth/actions/runs/45614048186>
(PR [#21](https://github.com/Albert-Tuan/sentinel-auth/pull/21), head
`f6218cb07b24afcead0e0d2dd75067b46841e291`).

```
Test & Smoke (py3.11)             pass
Test & Smoke (py3.12)             pass
Frontend (unit & build)           pass
Frontend (real HTTP integration)  pass

collected=1276 passed=1276 failed=0 skipped=0 error=0 xfailed=0
```

The zero-skip figure is the point of the whole exercise: the safety
suite contributed 51 of those 1276 tests, and every one of them ran on
the runner — none of them skipped itself to make the build green.

---

## 10. How to reproduce the whole matrix

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
pytest tests/test_ci_demo_database_safety.py -q

# 5. the regression
scripts/ci_bootstrap_postgres.sh
scripts/ci_bootstrap_demo_databases.sh
pytest tests/ -q

# 6. the diff
git diff --check
```

---

## 11. Related documents

* [M13-FULLSTACK-DEPLOYMENT.md](M13-FULLSTACK-DEPLOYMENT.md) — the demo stack
* [M13-DEMO-FIXTURES.md](M13-DEMO-FIXTURES.md) — the reproducible fixtures
* [M13-DEMO-SCENARIOS.md](M13-DEMO-SCENARIOS.md) — the six demo scenarios
