# M13 — Acceptance Matrix

> Sentinel Auth v3.3 · Milestone M13.0 – M13.2
> Every acceptance criterion of the milestone, and how it was verified.

This matrix lists every criterion of the M13 milestone, the artefact
that satisfies it and the command that proves it.

Every "verified" entry below was run against the live demo stack on
2026-11-25 (Areas A to E) and on 2026-11-26 (Area F — the browser
E2E).  The entries added by the M13.2 hardening round (Area G) were run
on 2026-11-28 against commit `2e3280d`; their evidence is in section 13.
The entries added by the FINAL hardening round (section 14) were run
on 2026-11-28 against the head of `feature/m13-browser-e2e` — the SHA
that section 14.2 names.

---

## 1. The summary

| # | Area | Criteria | Verified | How |
|---|---|---|---|---|
| A | The demo stack | 10 | 10 | `scripts/demo_stack.sh` |
| B | The fixtures | 8 | 8 | `scripts/demo_seed_demo.py` |
| C | The scenarios | 9 | 9 | `scripts/demo_scenarios.py` |
| D | The safety | 24 | 24 | `tests/test_demo_fixtures.py`, `tests/test_ci_demo_database_safety.py`, `tests/test_e2e_fixture_guards.py` |
| E | The regression | 15 | 15 | `pytest tests/` |
| F | The browser E2E | 12 | 12 | `scripts/e2e_run.sh` |
| G | The destination guard | 20 | 20 | `tests/test_e2e_fixture_target_guard.py`, `tests/test_pre_token_probe.py`, `scripts/demo_pre_token_probe.py` |
| | **Total** | **99** | **99** | |

The six demo scenarios contribute **55 individual checks**, all passing,
twice in a row — the second run proves they are re-runnable.

The browser suite contributes **18 scenarios**, all passing, zero
skipped, zero mocked. See
[M13-BROWSER-E2E-REPORT.md](M13-BROWSER-E2E-REPORT.md).

The destination guard contributes **111 tests**; the pre-token probe
contributes **56 guard, restoration and lifecycle tests** plus **43
hardening tests** and its **13 runtime checks**; both are accounted for
in section 13.

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
| D18 | The E2E fixture helper refuses any URL that is not a demo database its context owns | `scripts/e2e_fixtures_guard.py` — a hard-coded, per-context allowlist |
| D19 | The E2E helper refuses before it writes anything | `tests/test_e2e_fixture_guards.py` — the refusal is proved against a real PostgreSQL |
| D20 | The E2E helper refuses a `*_test` or a production database | the guard's overlap layer, tested with all eight protected names |
| D21 | The E2E helper refuses a database on another host | the loopback layer; `db.internal`, `10.0.0.5`, `sentinel.example.com` and `0.0.0.0` are refused |
| D22 | The E2E helper refuses without an explicit, by-name declaration | the opt-in layer; a generic "true" authorises nothing |
| D23 | No single environment variable can widen the E2E guard | the allowlist is a module constant; a test asserts it cannot be overridden |
| D24 | The E2E helper never deletes a row outside its own fixtures | `restore-active-policy` is the ONE documented exception, and it only moves the active slot |

### The E2E database guard

`scripts/e2e_fixtures.py` WRITES rows (the alerts, the policies, the
sessions, the MFA gate, the rate-limit counters) and DELETES rows (the
alerts, the policies). It is the only thing in the browser suite that
writes to a database directly, so it is also the only place where a
mistake could reach a database that must never be touched.

The guard lives in `scripts/e2e_fixtures_guard.py` — its own module, so
the safety boundary can be imported and tested WITHOUT running any
destructive code. It is fail-closed and layered; every layer refuses by
default, and the destructive SQL runs only when all of them are
satisfied.

#### The five original layers — WHICH DATABASE

These five layers decide **which database** the helper may touch. They
were the whole guard when it was first written.

| Layer | The rule | A refused example |
|---|---|---|
| 1 | The database name must be EXACTLY one of the two names the context owns | `sentinel_core_demo_prod`, `sentinel_core_democracy` |
| 2 | The `*_test` and the canonical production names are refused outright | `sentinel_core_test`, `sentinel_core`, `postgres` |
| 3 | The server must be on the loopback interface | `db.internal`, `10.0.0.5`, `0.0.0.0` |
| 4 | The run must have declared — BY NAME — that it may write to that exact database | `E2E_ALLOW_WRITE_TO=true`, or a declaration for another database |
| 5 | The URL must come from the context's OWN variable | a `CORE_DATABASE_URL` pointing at the detection database |

Layers 1 to 4 are decided by the URL alone, and the allowlists are
hard-coded module constants, so **no environment variable can widen
them**. Layer 5 is a separate input and it must name the very database
the helper is about to write to, so a declaration made for one target
cannot carry over to another.

The declaration is derived from the very URLs the run is about to use —
`scripts/e2e_run.sh` computes it, and
`frontend/e2e/support/fixtureBridge.ts` computes it from the demo
environment it hands to the helper — so it can never name a database the
run does not actually reach.

#### The destination hardening — WHICH DESTINATION THE DRIVER REACHES

The five layers above decide about a URL. They did **not** prove that
the URL they decided about is the URL the DRIVER would use, and a
PostgreSQL URL can carry a query string that libpq lets **override** the
parts of the URL:

```
postgresql://demo:example@127.0.0.1/sentinel_core_demo?dbname=sentinel_core_test

    dialect.create_connect_args()  ->  {"host": "127.0.0.1",
                                        "dbname": "sentinel_core_test"}
```

The path still says `sentinel_core_demo` and the authority still says
`127.0.0.1`, so the five layers were satisfied — but the driver was
told to open `sentinel_core_test`. The guard used to compare the URL
with the context's own variable **after dropping everything after the
`?`**, so it approved one destination and the driver reached another.

The hardening that closes this is what Area G verifies. Its rules are
now part of the same module:

| Rule | What it does | A refused example |
|---|---|---|
| SQLAlchemy URL parsing | the URL is read with `make_url()` — the engine's own parser — so the guard reads the same URL the engine will read | a URL SQLAlchemy cannot parse |
| Query allowlist | only `sslmode`, `connect_timeout`, `application_name` and `client_encoding` are accepted | `?options=-c%20statement_timeout%3D30000` |
| Target-moving parameters | `host`, `hostaddr`, `dbname`, `database`, `service`, `port`, `user`, `password`, `passfile` and `target_session_attrs` are refused with a message of their own | `?dbname=sentinel_core_test` |
| Unknown and repeated parameters | an unknown parameter is refused, never ignored; a repeated one is refused because the driver receives every value | `?search_path=public`, `?dbname=a&dbname=b` |
| Encoded parameters | the raw query string is compared against SQLAlchemy's own parse, so a parameter SQLAlchemy would DROP cannot slip between the two | `?db%6eame=sentinel_core_test`, `?dbname%3Dsentinel_core_test` |
| Driver scope | only the dialects the repository uses: `postgresql`, `postgresql+psycopg2`, `postgresql+psycopg` | `?postgresql+asyncpg://`, `mysql://`, `sqlite:///` |
| libpq environment | `PGHOSTADDR`, `PGSERVICE` and `PGSERVICEFILE` are refused outright; `PGHOST`, `PGPORT`, `PGDATABASE` and `PGUSER` are refused when the URL does not pin the matching parameter | `PGHOSTADDR=192.0.2.123` in the environment |
| Driver agreement | `dialect.create_connect_args()` must report the same `host` and `dbname` the guard validated, and must not carry `hostaddr` or `service` | a driver that would report another database |
| The validated URL object | the guard RETURNS the `URL` object it validated, and the engine is built from **that object** — never a re-parsed string | — |
| Context comparison | the comparison with the context's own variable is semantic (driver, host, port, database, user, query parameters) | a URL whose query differs from its variable |

Two properties make this more than a list of refusals:

* **The layers are independent.** A test disables the query check and
  proves the driver-agreement check still catches the bypass, so no
  single layer is load-bearing on its own.
* **The engine is built from the validated object.**
  `scripts/e2e_fixtures.py` passes the `URL` instance to
  `create_engine()`, which closes the gap between "the URL that was
  checked" and "the URL the driver receives".

A refusal message never carries the URL, because a URL carries the
password.

#### The one deliberate exception

`restore-active-policy` restores the demo stack's SEEDED active policy.
Every other operation touches only rows the E2E suite created; that one
deliberately touches a row it did NOT create.

It is legitimate because it is the RESTORE of a state the behaviour under
test changed: activating a policy deactivates the current one — that is
the product behaviour, and the browser scenario has to prove it — so the
seeded ACTIVE policy of the demo stack is no longer active and the demo
would drift away from its own fixtures. Putting the demo back the way the
scenario found it is a REQUIRED cleanup, not a way of hiding a defect.

The exception is scoped as tightly as the principle it bends: it restores
ONE named policy, it only ever moves the ACTIVE SLOT, it never deletes a
policy, it never touches the E2E-owned policies, and it is still subject
to every guard above.

### D18 to D24 in detail

```
collected=47 passed=47 failed=0 skipped=0
```

The suite that proves the guard is `tests/test_e2e_fixture_guards.py` —
47 tests across three groups:

* `TestTheDemoDatabaseGuard` — the layers themselves: the accepted
  names, the refused names, the wrong-context URLs, the non-loopback
  hosts, the missing or generic declaration, and the proof that no
  environment variable can widen the allowlist.
* `TestTheFixtureHelperUsesTheGuard` — the helper itself: every engine is
  built through the guarded helper, the guard is consulted BEFORE
  `create_engine`, and a refusal becomes a clean exit.
* `TestTheFixtureHelperRefusesBeforeItWrites` — the claim that matters,
  proved against a REAL PostgreSQL: a refused run leaves the row count
  of the `alerts` table unchanged, and no fixture row is created. The
  claim is about the DATABASE, so it is not proved with a mock.

---

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
| E1 | The full test suite passes | `1586 passed`, 0 failed, **0 skipped** (the `1543` baseline plus the 43 final-hardening tests) |
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
| E14 | The E2E database-guard tests pass | 47 passed, 0 skipped |
| E16 | The E2E destination-guard tests pass | 111 passed, 0 skipped |
| E15 | The INET cross-driver parity tests pass | 15 passed, 0 skipped |

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
| Backend regression | ≥ 1199 passed | **1586 passed**, 0 failed, 0 skipped | +387 (26 fixture + 51 safety + 47 guard + 15 parity + 111 destination guard + 56 probe guard/restore/lifecycle + 43 probe final hardening + 38 the other M13 work) |
| HTTP smoke | ≥ 79 passed | **79 passed**, 0 failed | — |
| Frontend unit/component | ≥ 265 passed | **265 passed**, 0 failed | — |
| Frontend integration | ≥ 50 passed | **50 passed**, 0 failed | — |
| Deployment verification | pass | **67 passed**, 0 failed | — |
| TypeScript strict | pass | pass | — |
| Lint | pass | pass | — |
| Production build | pass | pass | — |
| Demo scenarios | — | **55 checks**, 2 consecutive runs | — |
| Browser E2E | — | **18 scenarios**, 0 skipped, 0 mocked | new |
| Browser E2E typecheck | pass | pass (`tsc -p tsconfig.e2e.json`) | new |
| E2E database guard | — | **47 passed**, 0 skipped | new |
| E2E destination guard | — | **111 passed**, 0 skipped | new |
| Pre-token probe guard, restoration and lifecycle | — | **56 passed**, 0 skipped | new |
| Pre-token probe final hardening (snapshot, redaction, evidence binding, child lifecycle) | — | **43 passed**, 0 skipped | new |
| Pre-token detection probe | — | **13 checks passed**, 0 failed | new |
| INET driver parity | — | **15 passed**, 0 skipped | new |
| CI database safety | — | **51 passed** | new |
| `git diff --check` | clean | clean | — |
| Secret scan | clean | clean | — |

### E1 in detail

```
collected=1586 passed=1586 failed=0 skipped=0 error=0 xfailed=0
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
fail-closed guards of its own. See section 9.

---

## 7. Area F — The browser E2E

| # | Criterion | Result |
|---|---|---|
| F1 | A real Chromium drives the real application | Playwright 1.65.1, `workers: 1`, the demo stack — **18 passed**, 0 failed, 0 skipped |
| F2 | Nothing is mocked | no `page.route()`, no fixture-swapped client; the OTP comes from the SMTP sink, the 502 from a real Core miss, the degraded payload from a renamed ML table |
| F3 | The suite is re-runnable | the scenarios own their fixtures; two consecutive clean runs, 18/18 both times |
| F4 | A skipped scenario fails the run | `scripts/e2e_run.sh` reads `results.json` and fails on any skip |
| F5 | Every role's journey is covered | USER (2), SECURITY_ADMIN (1), SOC_ANALYST (1), SECURITY_MANAGER (3) |
| F6 | The authorization is covered at both layers | the frontend route guards **and** the backend's 401/403 |
| F7 | The concurrency control is covered | a stale `expected_updated_at` is refused with 409, a fresh token is accepted |
| F8 | The session races are covered | the cross-role replacement, the expiry, the rotation, the stale-401 epoch guard |
| F9 | The failure modes are honest | the UI reports "HÀNH ĐỘNG KHÔNG ĐƯỢC ÁP DỤNG" for a 502; a `null` metric renders as "không có dữ liệu", never as a `0` |
| F10 | The artefacts never leak a secret | the traces stay under the gitignored `.ci/`; CI publishes only the JUnit XML |
| F11 | The suite is typechecked | `tsconfig.e2e.json`, strict — `tsc -p tsconfig.e2e.json` clean |
| F12 | The suite runs in CI | the `browser-e2e` job of `.github/workflows/ci.yml`, on the three disposable `_ci_demo` databases |

### F1 in detail

```
Running 18 tests using 1 worker
  18 passed (38.9s)
```

| Group | Scenarios | What it covers |
|---|---|---|
| E2E-01 | 2 | the USER journey — sessions, devices, revocation, logout |
| E2E-02 | 1 | the SECURITY_ADMIN journey — a real MFA handshake over SMTP, the directory, the audit log |
| E2E-03 | 1 | the SOC_ANALYST journey — the queue, the filters, the investigation, the acknowledgement, the resolution |
| E2E-04 | 2 | the protective actions — the behavioural proof that Core changed, and the honest 502 |
| E2E-05 | 2 | the policy lifecycle — the draft, the activation, the freeze, the 409 concurrency |
| E2E-06 | 3 | the analytics — the five screens, `null` versus `0`, the 200/503 degradation |
| E2E-07 | 3 | the RBAC — the route guards, the per-role access, the 401/403 |
| E2E-08 | 4 | the races — the cross-role swap, the expiry, the rotation, the stale 401 |

### The four defects the browser suite found

Two of them are **product** defects and two are **harness** defects.
They are listed as defects 13 to 16 in section 8, and the full account
is in [M13-BROWSER-E2E-REPORT.md](M13-BROWSER-E2E-REPORT.md), section 5.

| # | Kind | What it was |
|---|---|---|
| 13 | product | the action dialog stayed open when the action failed — the refusal was hidden behind the curtain |
| 14 | product | the action was sent with an empty reason — a request the server was bound to refuse |
| 15 | harness | a coordinate click on an alert row could land on the wrong row, because the queue reflows under the pointer |
| 16 | harness | a re-armed fixture sank below the first page of the queue |

Defects 13 and 14 are the reason the browser suite was worth writing:
both are invisible to a component test, and both would have left a user
misinformed about their own protection.

Two more harness defects (17 and 18) appeared when the new suite was
added to a repository that already had a unit-test runner and a linter:
Vitest picked up the Playwright specs, and ESLint applied React's hook
rules to them. Both are listed in section 8.

And two more that the **CI** run of the browser suite surfaced — one in
the product (defect 19) and one in the persistence layer (defect 20).
Both are listed in section 8 and accounted for in full in
[M13-BROWSER-E2E-REPORT.md](M13-BROWSER-E2E-REPORT.md), section 5.

---

## 8. The problems that were found and fixed

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

And finally the four that only the **browser** could find — two in the
product and two in the harness:

| # | Problem | Symptom | Fix |
|---|---|---|---|
| 13 | The action dialog stayed open when the action **failed** | the failure notice lives below the dialog, behind an 85% opaque curtain — the analyst saw the dialog still open and the refusal unreadable | `onError` closes the dialog, so the "HÀNH ĐỘNG KHÔNG ĐƯỢC ÁP DỤNG" banner is in full view |
| 14 | The action was sent with an **empty reason** | `reason` is `Field(..., min_length=1)`, so the request was refused with a 422 before it ever reached Core | the reason is `required`, the button is disabled without one, and the type is `reason: string` |
| 15 | A coordinate click on an alert row could land on the wrong row | the queue enriches its rows asynchronously, so the row height changes from 34px to 46px mid-click — the DOM event target became `<TBODY>` and React's synthetic `onClick` never fired | `activateRow(row)` focuses the row and presses `Enter` — zero coordinate dependency |
| 16 | A re-armed fixture sank below the first page of the queue | the re-arm did not refresh `created_at`, so the scenario's own alert drifted past page 25 | the re-arm sets `created_at = now()`, so the alert is at the top of page 1 |
| 17 | The **unit-test** runner picked up the Playwright specs | Vitest's default `include` glob matches `e2e/*.spec.ts`, and Playwright's `test.describe()` cannot be called from inside Vitest — eight spec files failed to load and the unit suite went red for an unrelated reason | `vitest.config.ts` excludes `e2e/**`; the browser suite has its own runner |
| 18 | The **linter** applied React rules to the Playwright suite | `react-hooks/rules-of-hooks` complained about a fixture calling Playwright's `use()`, and `no-empty-pattern` complained about Playwright's documented `async ({}, use) => …` signature | `eslint.config.js` turns both rules off for `e2e/**` |

Defects 13 and 14 are the reason the browser suite was worth writing:
both are invisible to a component test, and both would have left a user
misinformed about their own protection.

Defect 15 is the clearest argument for a real browser at all. A
component test renders a row and clicks it in a stable layout; the real
queue reflows under the pointer, and the event is delivered to the
wrong element. The diagnosis was made by capturing the live
`mousedown` / `mouseup` / `click` targets inside the page.

And finally the two that the **CI** run of the browser suite surfaced —
one in the product and one in the persistence layer. Both appeared only
in CI, because only CI runs the new dependency range and the
production `psycopg3` driver:

| # | Problem | Symptom | Fix |
|---|---|---|---|
| 19 | The alert timeline was not invalidated when a protective action **failed** | the backend recorded "Security action <ACTION> was NOT enforced by Core" in the timeline, but the panel's `onError` path never invalidated the `['alerts']` query, so the UI kept showing the stale timeline and the analyst never saw the refusal | `onError` awaits `invalidateAlerts()`, so the timeline re-fetches and the refusal note is rendered |
| 20 | PostgreSQL `INET` columns were returned as `ipaddress.IPv4Address` objects, not `str` | `GET /api/v1/devices` failed with a 500: Pydantic raised a `ValidationError` on `TrustedDeviceItem.last_ip: Optional[str]`. SQLAlchemy 2.1 changed the default driver for a bare `postgresql://` URL from `psycopg2` to `psycopg` (psycopg 3), and psycopg3 maps `INET` to `ipaddress` objects | `app/models.py` defines a `StrINET(INET)` type whose `result_processor` normalises every value to `str` on every driver and every SQLAlchemy version; `app/devices.py` also casts defensively; `requirements.txt` pins `sqlalchemy>=2.0.0,<2.1.0` |

Defect 19 is the smaller of the two, but it is a **truthfulness**
defect of exactly the kind the milestone cares about: the system knew
the action had not been enforced, and the interface refused to show
it. The analyst would have read "the action was applied" when Core
had, in fact, refused it.

Defect 20 is a supply-chain defect rather than a logic defect. The
code was always correct under `psycopg2`; it became incorrect the
moment a dependency resolved to psycopg 3. The pin in
`requirements.txt` restores the previous behaviour, and the
`StrINET` type makes the behaviour **correct by construction** rather
than by luck, so the next driver change cannot silently break it
again.

### The final safety review

The last review of this branch looked at the E2E fixture helper — the
one place in the browser suite that writes to a database — and found
that it had **no guard at all**: its engine constructors accepted any
URL the environment happened to carry. That is defect 21.

| # | Problem | Symptom | Fix |
|---|---|---|---|
| 21 | `scripts/e2e_fixtures.py` built its engines from **whatever URL the environment carried** | a mistyped `CORE_DATABASE_URL`, or an environment left over from another stack, would have made the browser suite DELETE rows in a database it was never meant to touch | `scripts/e2e_fixtures_guard.py` — a fail-closed, five-layer guard with a hard-coded per-context allowlist, a loopback-host rule and an explicit by-name declaration; every engine is built through it, and the guard runs BEFORE `create_engine` |

Defect 21 was never exploited, and no production database was harmed.
But the helper's own docstring claimed "every fixture script refuses to
write into a database without the `_demo` marker", and that claim was
TRUE for `scripts/demo_seed_demo.py` and **FALSE** for
`scripts/e2e_fixtures.py`. The fix makes the claim true of both.

The review also hardened the proof of the `INET` contract. The CI step
that checked it ran a raw `SELECT '127.0.0.1'::inet` — which proves
that the **database** returns a string, not that the **column type the
application declares** returns one, and the column type is the thing
that actually broke. The step now goes through the ORM under BOTH
drivers, and it also proves that the two drivers really do read a PLAIN
`INET` column differently — so the parity assertion cannot pass by
accident on whichever driver happens to be the forgiving one.

---

## 9. The safety of the CI bootstrap

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

## 10. The CI result

### The current run — PR #22, head `2e3280d`

Run: <https://github.com/Albert-Tuan/sentinel-auth/actions/runs/46149270445>
(PR [#22](https://github.com/Albert-Tuan/sentinel-auth/pull/22), head
`2e3280d`, started 2026-11-28
13:22:09 UTC).

```
Test & Smoke (py3.11)             success
Test & Smoke (py3.12)             success
Frontend (unit & build)           success
Frontend (real HTTP integration)  success
Browser E2E (real Chromium)       success
```

What each job reported, read out of the job log:

| Job | Command | Result |
|---|---|---|
| Test & Smoke (py3.11) | `pytest tests/` | `collected=1543 passed=1543 failed=0 skipped=0 error=0 xfailed=0` |
| Test & Smoke (py3.12) | `pytest tests/` | `collected=1543 passed=1543 failed=0 skipped=0 error=0 xfailed=0` |
| Test & Smoke (py3.11 / py3.12) | `scripts/m10_http_smoke.py` | `HTTP SMOKE: 79 passed, 0 failed` |
| Frontend (unit & build) | `npm run test` | `Test Files 18 passed (18)` · `Tests 265 passed (265)` |
| Frontend (real HTTP integration) | `npm run test:integration` | `Test Files 3 passed (3)` · `Tests 50 passed (50)` |
| Browser E2E (real Chromium) | `python scripts/demo_pre_token_probe.py` | `PRE-TOKEN PROBE: 10 passed, 0 failed` |
| Browser E2E (real Chromium) | `bash scripts/e2e_run.sh --no-start` | `18 passed (49.5s)` · *pre-token probe: 10 checks passed, 0 failed* |

Those are the figures of **CI run `46149270445`**, the run of the
`2e3280d` commit.  They are the HISTORICAL figures and they are left
here unchanged on purpose: the final hardening round adds 43 tests and
3 runtime checks, and its own figures are in section 14.  The two
tables must not be read as one — a later run does not retroactively
change what an earlier run reported.

The zero-skip figure is the point of the whole exercise: the safety
suite contributed 51 of those 1543 tests, and every one of them ran on
the runner — none of them skipped itself to make the build green.

**What CI does NOT run.** Two of the numbers in this matrix are not CI
numbers, and they are labelled as such everywhere they appear:

| Suite | Where it runs | Why it is not in CI |
|---|---|---|
| `scripts/demo_scenarios.py` (55 checks) | locally, against the demo stack | it is a DEMONSTRATION script; it drives the demo stack's own ports and its own database names, which the CI jobs do not provide |
| `scripts/deploy_verify.py` (67 checks) | locally, against a disposable stack | it verifies the DEPLOYMENT scripts (`docker compose`, the volume lifecycle), which the CI runner does not execute |
| `scripts/demo_pre_token_probe.py` (13 checks) | **both** — locally and in the `browser-e2e` job | it was added to CI in the M13.2 hardening round; see sections 13 and 14 |

The `browser-e2e` job added the pre-token probe after the browser suite,
so a regression in the gate fails the build even though no browser
scenario depends on it.

### The earlier run — PR #21

Run: <https://github.com/Albert-Tuan/sentinel-auth/actions/runs/45614884041>
(PR [#21](https://github.com/Albert-Tuan/sentinel-auth/pull/21), head
`56c24802d273d2313ac2a3e07479a404e02975e4`).

```
Test & Smoke (py3.11)             pass
Test & Smoke (py3.12)             pass
Frontend (unit & build)           pass
Frontend (real HTTP integration)  pass

collected=1276 passed=1276 failed=0 skipped=0 error=0 xfailed=0
```

This is the HISTORICAL figure of the M13.0/M13.1 foundation. It is
kept because PR #21 is still open and its own head carries that number;
it is not the current state of the branch.

### The browser E2E job

The `browser-e2e` job was added in this milestone. It provisions the
three disposable `_ci_demo` databases, starts the SMTP sink, the API
and the Vite dev server, seeds the fixtures and runs the browser suite
through the same `scripts/e2e_run.sh` a developer runs:

```yaml
- name: Run the browser suite
  run: bash scripts/e2e_run.sh --no-start
```

The job enforces the same zero-skip policy on the browser suite: a
skipped scenario fails the build, for the same reason a skipped backend
test does — a scenario that does not run proves nothing.

The local run that this section reports:

```
Running 18 tests using 1 worker
  18 passed (38.9s)
```

The JUnit report is published as the artefact `browser-e2e-junit`. The
HTML report and the traces are **not** published: they carry bearer
tokens and OTP codes.

---

## 11. Area G — The destination guard and the pre-token gate

| # | Criterion | Artefact | Verified by |
|---|---|---|---|
| G1 | A URL whose query string MOVES the destination is refused | `scripts/e2e_fixtures_guard.py` | `test_a_destination_changing_query_parameter_is_refused` (7 cases) |
| G2 | The refusal names the offending parameter | the same | `test_the_refusal_names_the_offending_parameter` (4 cases) |
| G3 | A repeated parameter is refused | the same | `test_a_repeated_parameter_is_refused` (3 cases) |
| G4 | An encoded parameter is refused | the same | `test_an_encoded_parameter_is_refused` (3 cases) |
| G5 | An unknown parameter is refused | the same | `test_an_unknown_parameter_is_refused` (7 cases) |
| G6 | Only the allowlisted parameters are accepted | the same | `test_a_parameter_on_the_allowlist_is_accepted` (3 cases) |
| G7 | Only the project's own drivers are in scope | the same | `test_an_unsupported_driver_is_refused` (5 cases), `test_the_projects_own_drivers_are_accepted` (3 cases) |
| G8 | The libpq environment cannot move the destination | the same | `test_an_overriding_libpq_variable_is_refused` (3), `test_a_defaulting_libpq_variable_is_refused` (2), `test_a_default_the_url_pins_is_not_a_refusal` (2) |
| G9 | A refusal never reaches `create_engine` | `scripts/e2e_fixtures.py` | `test_a_refused_url_never_reaches_create_engine`, `test_no_destination_changing_url_reaches_create_engine` (4 cases) |
| G10 | The engine is built from the validated URL OBJECT | the same | `test_the_url_function_returns_the_parsed_url_object`, `test_the_engine_is_built_from_the_validated_url_object` |
| G11 | The driver agrees with the guard about the destination | `scripts/e2e_fixtures_guard.py` | `test_the_agreement_check_catches_a_moved_database`, `..._a_moved_host`, `..._a_host_address`, `..._a_service` |
| G12 | The pre-token gate really decides the login, on the real stack | `scripts/demo_pre_token_probe.py` | the A/B comparison: the same risky login, the same databases, the same policy, the gate on and the gate off |
| G13 | The probe refuses a target the hardened guard refuses | the same | `tests/test_pre_token_probe.py` — the query-move, the context, the host, the name and the write-declaration cases |
| G14 | A refused target never reaches an engine, a backend or a row | the same | `test_a_refused_target_never_reaches_create_engine`, `test_a_refused_target_never_spawns_the_comparison_backend` |
| G15 | The probe restores the ACTIVE SLOT it found — including "no policy" | the same | `test_the_other_policy_goes_back_into_service`, `test_no_policy_is_left_in_service_when_there_was_none`, `test_the_restore_does_not_touch_every_active_policy` |
| G16 | A value the probe never read is never written | the same | `test_a_value_that_was_never_read_is_not_a_value`, `test_the_mfa_flag_is_not_written_without_a_snapshot` |
| G17 | Every cleanup step is tried, and a cleanup failure fails the run | the same | `test_every_step_is_tried_even_when_the_first_one_fails`, `test_the_probe_returns_a_failure_when_the_cleanup_failed` |
| G18 | The comparison backend's environment is assembled, not inherited | the same | `test_a_stray_variable_of_the_shell_is_not_inherited`, `test_only_the_allowlisted_variables_are_present` |
| G19 | The comparison backend owns its port and its process | the same | `test_the_backend_is_started_on_an_ephemeral_port`, `test_the_backend_stops_only_its_own_process`, `test_the_probe_never_looks_a_process_up_by_port` |
| G20 | The gated attempt really was scored by the demo policy | the same | the probe's own runtime checks: the policy version, the rules `impossible_travel` and `multiple_failures`, and the recorded decision |
| G21 | The MFA snapshot the probe restores is the one it FOUND, not the one it created | `tests/test_pre_token_probe_hardening.py` | `TestTheMfaSnapshotThroughBothRuns` — 4 orchestration tests over both runs |
| G22 | No output of the probe carries a credential | the same | `TestNoCredentialReachesAnyOutput` — 6 tests over the main, the cleanup and the child-startup paths |
| G23 | Each of the two runs is bound to its OWN attempt | the same | `TestTheEvidenceIsBoundToItsAttempt` — 9 tests |
| G24 | A silent child cannot hang the probe | the same | `TestTheChildNeverHangsTheProbe` — 9 tests |

The suite that proves G1 to G11 is
`tests/test_e2e_fixture_target_guard.py` — **111 tests**. It is
independent of the five original layers in Area D: it proves that the
layers agree with the DRIVER, not with each other.

The suite that proves G13 to G19 is
`tests/test_pre_token_probe.py` — **56 tests**. It calls the REAL probe
module and the REAL guard; it never mocks either, and it never opens a
connection to a database it is not allowed to touch.

The suite that proves G21 to G24 is
`tests/test_pre_token_probe_hardening.py` — **43 tests**. It was
written against the OLD code first: on `9c7456f` it reported **35
failed, 8 passed**, and on the fixed code it reports **43 passed**.
See section 14.

G12 and G20 are proved by `scripts/demo_pre_token_probe.py` itself. G12
is the only check that answers the question the demo actually needs
answered — see section 13.2.

---

## 12. How to reproduce the whole matrix

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
pytest tests/test_e2e_fixture_guards.py -q
pytest tests/test_e2e_fixture_target_guard.py -q
pytest tests/test_pre_token_probe.py -q
pytest tests/test_pre_token_probe_hardening.py -q

# 5. the regression
scripts/ci_bootstrap_postgres.sh
scripts/ci_bootstrap_demo_databases.sh
pytest tests/ -q
pytest tests/test_inet_driver_parity.py -q

# 6. the browser E2E
scripts/e2e_run.sh
cd frontend && npx tsc -p tsconfig.e2e.json && cd ..

# 7. the pre-token detection gate, on the real stack
python scripts/demo_pre_token_probe.py

# 8. the deployment verification
python scripts/deploy_verify.py

# 9. the diff
git diff --check
```

The scripts are invoked through `bash` or `python` because the
repository does not track the executable bit on every file. The full
setup guide — including the failure modes and how to recognise them —
is in [M13-DEMO-FIXTURES.md](M13-DEMO-FIXTURES.md).

---

## 13. The evidence of the M13.2 hardening round

Every figure in this section was produced on **2026-11-28** against
commit **`2e3280d`** (branch
`feature/m13-browser-e2e`, PR #22).

### 13.1 The destination guard

| Item | Value |
|---|---|
| Source SHA | `2e3280d` |
| Date run | 2026-11-28 |
| Command | `python -m pytest tests/test_e2e_fixture_target_guard.py -q` |
| Profile | the fixture-guard unit suite; no database of its own, except the positive control |
| Result | **111 passed**, 0 failed, 0 skipped |
| Evidence | CI run `46149270445`, job `Test & Smoke (py3.11)` and `(py3.12)` — the suite is part of `pytest tests/`, which reported `collected=1543 passed=1543 skipped=0` |

The five mutations of the guard were each checked to be caught:

| Mutation | Tests that fail |
|---|---|
| the query check is disabled | 29 |
| the target-moving check is disabled | 3 |
| the truncated comparison is restored | 1 |
| the driver-agreement check is disabled | 1 |
| the libpq environment check is disabled | 6 |

### 13.2 The pre-token detection gate

The question: **does the Detection Engine decide the login outcome, or
does the token simply happen to be withheld?**

The answer is proved by an A/B comparison on the running demo stack —
same databases, same active policy, same seeded risky history, same
account. The ONLY variable is `RUN_PRE_TOKEN_CHECK`.

| Item | Value |
|---|---|
| Source SHA | the head of `feature/m13-browser-e2e` — see the delivery report |
| Date run | 2026-11-28 |
| Command | `python scripts/demo_pre_token_probe.py` |
| Profile | the **local demo stack** (`.env.demo`, the `_demo` databases), the monolith with `DETECTION_URL` pointing at itself and `RUN_PRE_TOKEN_CHECK=1` |
| Result | **10 checks passed**, 0 failed (the count of the `2e3280d` run; the final round raised it to 13 — section 14) |
| Evidence | the CI `browser-e2e` job runs the same probe against the `_ci_demo` databases, on the same stack the browser suite drives |

What the two runs showed:

```
RUN 1 (the gate ON):  status=200 token=HELD   mfa_required=True
RUN 2 (the gate OFF): status=200 token=ISSUED mfa_required=False
```

and the Core audit log recorded the protective action the Detection
Engine asked for:

```
protective_action:REVOKE_SESSIONS | system
   reason: detection risk_level=RiskLevel.CRITICAL decision=block
```

#### How the probe is guarded

The probe uses **the same hardened guard** as the browser suite —
`scripts/e2e_fixtures_guard.py` — and it does not write a guard of its
own. Every database URL is validated **before** a connection is opened
and **before** anything is mutated, and every engine is built from the
URL *object* the guard returned, so the destination the guard approves
is the destination the driver reaches.

The five layers apply unchanged:

| Layer | What the probe inherits |
|---|---|
| 1 — context | the URL must come from the context's OWN variable |
| 2 — name allowlist | an EXACT match against `sentinel_*_demo` and `sentinel_*_ci_demo` — not a `_demo` suffix check |
| 3 — no overlap | the `*_test` and the production names are refused outright |
| 4 — loopback host | the server must be on `127.0.0.1`/`localhost`/`::1` |
| 5 — explicit opt-in | the run must declare `E2E_ALLOW_WRITE_TO=<the exact database>` |

A refusal is fatal and happens before anything else: **no engine is
built, no backend is spawned and no row is written.** The refusal
message never carries the password.

The comparison backend receives the **validated** database URLs, and its
environment is **assembled, not inherited**: it starts from a clean
slate and takes only the variables on an explicit allowlist, from the
demo environment file. A stray `RUN_PRE_TOKEN_CHECK`, `PGHOST`,
`PGHOSTADDR`, `PGSERVICE` or `MFA_SMTP_PORT` in the operator's shell
therefore cannot change what the comparison measures.

#### What the probe owns, and what it restores

| The probe owns | The probe restores it to |
|---|---|
| the seeded risky `login_attempts` rows | the rows it wrote are deleted, by `event_id` |
| the one-time MFA flag of `demo_user` | the value it found — and **only** when it actually read it |
| the ACTIVE SLOT of the policy table | the policy that was in service — **or** "no policy in service", when there was none |

Two details matter:

  * the ACTIVE SLOT is restored by moving **one** row, never by a
    blanket `UPDATE policies SET is_active = FALSE WHERE is_active IS TRUE`;
  * a value the probe never read is never written. The MFA flag
    snapshot distinguishes "the flag was `False`" from "the flag was
    never read", and the policy snapshot distinguishes "the demo policy
    was in service" from "another policy was" from "**no** policy was".

Every cleanup step runs in its own `try`, so a step that fails does not
skip the steps that follow it. A cleanup failure is reported — with the
credential redacted — and it makes the **overall run fail**.  Since the
final hardening round the **sanitized** message is the one that is
printed: the step that failed still names itself, but the credential
never reaches stdout or stderr (section 14.1, F2).

#### What the probe does NOT restore

The probe does not claim to leave the stack untouched. The two logins
are **real traffic**, and they leave real rows behind: the demo
account's sessions, its MFA transactions, the `login_attempts` rows and
the DETECTION alerts the two attempts raised all **remain**. The probe
reports what it leaves behind, so the claim is never wider than the
evidence.

One of those side effects is a **protective action**, and it is worth
naming precisely, because it is not a leak: the two attempts score
`critical`, and the application's own risk-action map sends
`REVOKE_SESSIONS` for that level, so the DETECTION service marks the
demo account's active sessions as revoked.  That is the product doing
what a risky login is supposed to make it do.  The probe does **not**
undo it, and section 14.4 measures what it does undo.

#### The scope of the A/B evidence

The probe proves that the **pre-token gate** — the synchronous
`POST /api/v1/internal/pre-token-check` call that happens BEFORE a
token is issued — withholds the token on the real stack, with the real
policy and the real HTTP boundary.

It proves this by **reading the DETECTION evidence of both attempts**,
not by the difference of the two responses alone: the probe checks that
the gated attempt was scored by the demo policy, that the rules
`impossible_travel` and `multiple_failures` fired, that a decision was
recorded — and that the ungated attempt was scored by the **same**
policy.  Since the final hardening round the evidence is also bound to
**its own attempt** — the two runs are two different attempt ids, and
each attempt's verdict is checked against the application's own
contract (section 14.3).

Two limits are stated precisely:

  * the risky history is **seeded** by the probe. The probe proves that
    the gate holds a token back for an attempt whose history looks like
    that. It does **not** claim that the history was produced by real
    failed logins;
  * the probe does **not** prove that a browser scenario does the same.
    The browser suite never creates a risky login, so it exercises the
    UI and the session mechanics, not the gate.

#### What the CI run found — the probe was measuring the wrong thing

The probe's first two CI runs **failed**, and the failures were real
evidence rather than flakes. Neither failure was a defect of the
application: both were the probe measuring something other than the
gate. The local run had passed in both cases, and the local run was
simply not the CI condition.

**Run `46140815516` — the gate issued the token.**

```
RUN 1 (the gate ON):  status=200 token=ISSUED mfa_required=False
```

Only one policy may be active at a time, by a partial unique index. The
browser scenario **E2E-05 activates a policy of its own**, and by that
index that DEACTIVATES the demo's policy. Its rules are milder, so the
risky login scored below the `high` threshold and the gate correctly
issued the token — a true statement about that policy, and a useless
statement about the gate. The probe now puts the demo's own policy back
in service before it scores anything, and restores the previous one
afterwards.

**Run `46141561690` — the gate still issued the token.**

The policy was already the demo's own. The remaining cause was the
FEATURE. `impossible_travel` reads `ip_change_rate_7d`, which is

```
1 - (attempts from this IP) / (attempts in the last 7 days)
```

so it measures the **novelty** of the address. The probe was logging in
from `203.0.113.77` — the same address the E2E fixtures write their
attempts under, and the address the probe itself writes its risky
history under. Every attempt the probe added therefore LOWERED the
novelty of the address it was trying to prove was new. With the browser
suite's loopback traffic in the history, the value landed below 0.8, the
rule did not trigger, and the gate issued the token.

The probe now writes its risky history under `203.0.113.77` — the
attacker — and logs in from an address it **picks from the account's own
history**: one the account has never used, drawn from the RFC 5737
documentation range so it can never be a real client. The pick is
deterministic — it is seeded from the account's id — so the same
history always yields the same candidate, and it skips every address the
account has already used.

That last property is what makes the probe **repeatable**. With a fixed
address, the second run would have failed: the first run's own attempt
had made the address known. The probe now runs over and over again,
each run from a different fresh address.

**Run `46149270445` — the gate held the token, in CI, on the stack the
browser suite drives.**

```
[pre-token-probe] the login under test comes from 203.0.113.19 (never used before)
[pre-token-probe] RUN 1 (the gate ON):  status=200 token=HELD   mfa_required=True
[pre-token-probe] RUN 2 (the gate OFF): status=200 token=ISSUED mfa_required=False
PRE-TOKEN PROBE: 10 passed, 0 failed
```

The probe also clears the login rate-limit counter of its own address.
The browser suite logs in from the same loopback address and leaves the
counter past its limit; a rate-limited probe would measure the limiter
instead of the gate.

#### The conditions that CI hit and a local run did not

The two CI failures above were **not** reproducible on a local run as it
stood, because the local stack did not carry the state CI carries: the
browser suite had already activated a policy of its own, and the
account's login history already held the loopback traffic. Those
conditions **can** be reproduced locally — by activating another policy
before the probe runs, and by letting the browser suite run first.

The probe now covers both explicitly: the policy snapshot restores
"another policy was in service" **and** "no policy was in service", and
the address is picked from the account's real history, so a history that
already knows the address does not fool the `impossible_travel` rule.

#### What this does and does not prove

It proves that the **pre-token gate** — the synchronous
`POST /api/v1/internal/pre-token-check` call that happens BEFORE a
token is issued — withholds the token on the real stack, with the real
policy and the real HTTP boundary.

It does **not** prove that a browser scenario does the same: the
browser suite never creates a risky login, so it exercises the UI and
the session mechanics, not the gate.

### 13.3 The probe's guard, restoration and lifecycle

The probe is the one script in the repository that writes to a demo
database **and** starts a process. Both of those are now covered by a
suite of their own.

| Item | Value |
|---|---|
| Source SHA | the head of `feature/m13-browser-e2e` — see the delivery report |
| Date run | 2026-11-28 |
| Command | `python -m pytest tests/test_pre_token_probe.py -q` |
| Profile | the fixture-guard unit suite; the REAL probe module and the REAL guard, never a mock of either |
| Result | **56 passed**, 0 failed, 0 skipped |

The four aspects it covers:

| Aspect | What it proves |
|---|---|
| the guard integration | a target the hardened guard refuses — a query string that moves the database, a foreign host, a foreign context, a non-demo name, a missing write declaration — is refused **before** an engine is built, **before** a backend is spawned and **before** a row is touched |
| the state restoration | the ACTIVE SLOT is restored in all three of its states, a value the probe never read is never written, and the restore moves **one** row instead of a blanket `UPDATE` |
| the cleanup independence | every cleanup step is tried even when an earlier one fails, a cleanup failure fails the **overall** run, and the credential in the error is redacted |
| the comparison backend's isolation | the environment is assembled from an allowlist rather than inherited, the backend owns an ephemeral port, and only the probe's **own** PID is ever stopped |

(The final hardening round added a **second** probe suite — 43 tests —
for the snapshot, the redaction, the evidence binding and the child's
lifecycle.  Section 14 describes it.)

The last one deserves a word, because it was the sharpest of the four.
The old probe compared the gate against a second backend started on a
**hard-coded port**, with `dict(os.environ)` as its environment. Two
defects follow from that, and both are now closed:

  * the hard-coded port could already be taken by something else, and
    the probe could then have measured **that** server's `/health` as if
    it were its own. The comparison backend is now started with
    `--port 0`, so the operating system assigns an ephemeral port, and
    the probe reads the **actual** port back from the Uvicorn startup
    log. There is no window in which the port can change hands.
  * the inherited environment carried whatever the operator's shell
    happened to hold — a `RUN_PRE_TOKEN_CHECK=0` from a previous
    experiment, a `MFA_SMTP_PORT` from another stack, a `PG*` variable
    that moved the destination. The comparison environment is now
    assembled explicitly: the allowlisted variables, the values from the
    authorised configuration file, `RUN_PRE_TOKEN_CHECK=0` and
    `RUN_LOGIN_EVENT_DELIVERY=1` forced, and **every** `PG*` variable
    removed.

### 13.4 The other suites, and where they run

| Suite | Command | Result | Where it ran | Evidence |
|---|---|---|---|---|
| Backend regression | `pytest tests/` | 1543 passed, 0 skipped | CI + local | CI `46149270445` |
| Destination guard | `pytest tests/test_e2e_fixture_target_guard.py -q` | 111 passed | CI + local | CI `46149270445` |
| Full-system E2E (pre-token ON) | `pytest tests/test_full_system_e2e.py -q` | 6 passed | local (needs the `*_test` databases) | part of `pytest tests/` in CI |
| Risk gate unit tests | `pytest tests/test_risk_gate.py -q` | 22 passed | local | part of `pytest tests/` in CI |
| Frontend unit | `npm run test` | 265 passed | CI | CI `46149270445` |
| Frontend real-HTTP integration | `npm run test:integration` | 50 passed | CI | CI `46149270445` |
| Browser E2E | `bash scripts/e2e_run.sh --no-start` | 18 passed | CI | CI `46149270445` |
| HTTP smoke | `scripts/m10_http_smoke.py` | 79 passed | CI | CI `46149270445` |
| Demo scenarios | `python scripts/demo_scenarios.py --all` | 55 checks | **local only** | the script drives the demo stack's own ports and database names |
| Deployment verification | `python scripts/deploy_verify.py` | 67 passed | **local only** | it verifies the `docker compose` deployment scripts, which CI does not execute |
| Pre-token probe | `python scripts/demo_pre_token_probe.py` | 10 checks (13 after the final round) | local + CI (`browser-e2e`) | see 13.2 and 14 |

---

## 14. The final hardening round — the probe's four remaining defects

A source review of `scripts/demo_pre_token_probe.py` at commit `9c7456f`
found four defects that the M13.2 round had not closed.  All four are
closed now, and the closing is proved by a suite that was written
against the OLD code first.

### 14.1 The four findings

| # | Finding | What was wrong | The fix | The test that proves it |
|---|---|---|---|---|
| F1 | The MFA snapshot was **overwritten** | `state.mfa = _clear_one_time_mfa(...)` ran before BOTH runs, so the second assignment replaced the snapshot the cleanup restores with the state the probe itself had produced | the snapshot is taken **once**, before RUN 1.  The clear in front of RUN 2 is a local `preparation` variable that never touches `state.mfa`; if it fails, the probe raises and the ORIGINAL snapshot is what the cleanup restores | `TestTheMfaSnapshotThroughBothRuns` — 4 orchestration tests over both runs |
| F2 | A cleanup error was logged **unredacted** | `record_cleanup_error()` redacted the message, but the very next line printed the raw `{error}` — so the credential reached stdout | `record_cleanup_error()` now **returns** the sanitized string and `_cleanup()` prints THAT.  The same sanitized string is what the summary prints | `TestNoCredentialReachesAnyOutput` — 6 tests over the main, the cleanup and the child-startup paths |
| F3 | The A/B evidence was **not bound** to its attempt | the evidence was found by IP + user agent + a 5-second lookback, so the second run could re-read the FIRST run's row.  The gated run's decision was only checked for "not None" | each run polls for an attempt that is **new** — the earlier run's attempt id is excluded — and the attempt must belong to the account under test.  The decision is checked against the contract: a gated risk level (`high`, `critical`) and the decision the matrix gives for it | `TestTheEvidenceIsBoundToItsAttempt` — 9 tests |
| F4 | A silent child could **hang** the probe | the port-wait loop called the **blocking** `stdout.readline()` under a deadline that the blocking read could never reach, and the error path called `stdout.read()` — another blocking read — before stopping the child | the child's output is read by a daemon thread into a queue; the caller polls the queue under its own deadline, and the error path drains the queue instead of reading the pipe | `TestTheChildNeverHangsTheProbe` — 9 tests |

### 14.2 The figures

| Item | Value |
|---|---|
| Code SHA under test | **`0e4147d`** — `fix(m13): close the four remaining defects of the pre-token probe`, on `feature/m13-browser-e2e` |
| Date run | 2026-11-28 |
| Command | `python -m pytest tests/test_pre_token_probe_hardening.py -q` |
| Result on the OLD code (`9c7456f`, in a separate worktree) | **35 failed, 8 passed** |
| Result on the NEW code | **43 passed**, 0 failed, 0 skipped |
| Command | `python -m pytest tests/ -q` |
| Result | **1586 passed**, 0 failed, 0 skipped |
| Command | `python scripts/demo_pre_token_probe.py` (the `_ci_demo` stack) | **13 checks passed**, 0 failed |
| Command | `bash scripts/e2e_run.sh --no-start` | **18 passed**, 0 skipped |
| Command | `browser → probe → browser → probe`, twice, one stack, no reset | 18 + 18 browser scenarios and 13 + 13 probe checks, **0 flaky / 0 retry** |
| CI run | [`46154841968`](https://github.com/Albert-Tuan/sentinel-auth/actions/runs/46154841968) | **5 of 5 jobs green**, head `0e4147d` — `collected=1586 passed=1586 failed=0 skipped=0`, HTTP smoke **79 passed**, frontend **265 + 50 passed**, browser E2E **18 passed**, pre-token probe **13 checks passed, 0 failed** |

The suite that proves the contract mirrors the application's own
constants is `TestTheContractMirrorAgreesWithTheApplication` — 7 tests
that compare the probe's `DECISION_BY_RISK_LEVEL` and
`EXPECTED_GATED_RISK_LEVELS` with `app.detection.DECISION_MATRIX` and
`app.auth.GATED_RISK_LEVELS`, so the mirror cannot drift silently.

### 14.3 What the evidence binding actually asserts

The probe asserts the CONTRACT, not a single pinned value:

  * the gated attempt's risk level is one the gate acts on — `high` or
    `critical` — because an attempt at any other level could not have
    held a token back;
  * the decision is the one `app.detection.DECISION_MATRIX` gives for
    that level — `high → challenge`, `critical → block`;
  * the same holds for the ungated attempt;
  * the two attempts have **different ids**.

The risk level itself is deliberately **not** pinned to one value.  The
combined score depends on whether the ML service answered, so a
degraded ML run scores on the rules alone.  Pinning the level would
have measured the ML service's availability rather than the gate.

### 14.4 The order question — what the probe really leaves behind

An earlier report claimed that `probe → browser` was noisy while
`browser → probe` was green, and attributed the difference to the
order alone.  That attribution was **not** a proven cause, so the
question was re-investigated by measurement.

The measurement is this: the probe's two logins are REAL traffic, and
at the level the scoring reaches they are `critical`.  The
`critical` level maps to `REVOKE_SESSIONS` in the application's own
risk-action map, so the DETECTION service calls back into Core and
marks every **active** session of `demo_user` as revoked.  That is a
legitimate consequence of a risky login — it is the protective action
the product is supposed to take, and the probe deliberately does NOT
undo it.

The **leak** was a different thing, and it was the F1 defect: on the
old code the overwritten snapshot left `detection_mfa_once = TRUE` on
`demo_user`, so the NEXT login was held for an MFA challenge that
nothing had asked for.  With F1 fixed, the flag is restored exactly:

```
demo_user|f
```

A second candidate cause was investigated and **excluded**: the probe
accumulates `open critical` alerts, and the alert queue is paginated at
20 rows per page with a bounded search of 25 pages, so an accumulation
could in principle push the E2E-03 fixture out of reach.  483
synthetic alerts were inserted into the disposable detection database
and E2E-03 was re-run: it still passed.  The reason is that the
fixture is **re-armed** with `created_at = now()` immediately before
the scenario, so it always sits on the first page.  The accumulation is
therefore real but harmless for the browser suite.

### 14.5 The repeat cycle that was verified

On one disposable stack (the `_ci_demo` databases on port 55450, its
own API on 58110, its own frontend on 55190, its own SMTP sink on
51140), with **no database reset in between**:

| Step | Result |
|---|---|
| browser suite | 18 passed, 0 skipped |
| probe | 13 checks passed, 0 failed |
| browser suite | 18 passed, 0 skipped |
| probe | 13 checks passed, 0 failed |

`results.json` reported **0 flaky and 0 retry** across all four
browser runs.

The order `probe → browser` was also run — the full browser suite
immediately after a probe run: **18 passed, 0 skipped**, with
`detection_mfa_once` restored to `false` and the probe's own cleanup
completing without an error.

### 14.6 The event-loop test

`tests/test_postgres_security.py::TestRegistryQueryIsBounded::test_the_endpoint_does_not_block_the_event_loop_while_locked`
was run **10 consecutive times** against `sentinel_legacy_test` (the
database that carries all three schemas, because the test needs the
`model_versions` table):

```
1 passed in 2.74s
1 passed in 2.77s
1 passed in 2.77s
1 passed in 2.77s
1 passed in 2.74s
1 passed in 2.76s
1 passed in 2.74s
1 passed in 2.76s
1 passed in 2.75s
1 passed in 2.78s
```

10/10 passed, the worst gap well inside the 0.5 s budget.  No retry was
added and the 0.5 s threshold was not changed.  This is a **local**
observation on this machine at this time; it is not a claim that the
test can never fail, and the earlier recorded failure-and-rerun is
kept as history rather than explained away.  No root cause was
confirmed for that earlier failure — see section 14.7.

### 14.7 What this round did NOT prove

  * The earlier intermittent failure of the event-loop test was **not**
    reproduced in this round (10/10 green), so its root cause is
    **still unconfirmed**.  It is recorded as an *intermittent failure,
    root cause not confirmed* — not as "a load artefact" and not as
    "harmless", because neither was demonstrated.
  * Nothing here proves that the browser suite is **free** of flaky
    tests.  The claim is only that the four runs of this cycle reported
    zero retries and zero flaky results.
  * The 13 probe checks are not a proof that the gate is *correct* in
    general — they are a proof that the gate held the token on the
    measured stack, with the recorded evidence bound to the attempt
    that was made.
  * The E2E-03 pagination investigation shows the fixture stays
    reachable **with the fixture re-arm in place**.  It does not prove
    the queue is unbounded in size.

---

## 15. Related documents

* [M13-FULLSTACK-DEPLOYMENT.md](M13-FULLSTACK-DEPLOYMENT.md) — the demo stack
* [M13-DEMO-FIXTURES.md](M13-DEMO-FIXTURES.md) — the reproducible fixtures
* [M13-DEMO-SCENARIOS.md](M13-DEMO-SCENARIOS.md) — the six demo scenarios
* [M13-BROWSER-E2E-REPORT.md](M13-BROWSER-E2E-REPORT.md) — the browser E2E suite
