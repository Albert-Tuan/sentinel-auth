# M13 — The Browser E2E Report

> Sentinel Auth v3.3 · Milestone M13.2
> Eighteen scenarios, one real Chromium, zero mocks.

This document reports the browser acceptance suite of the milestone:
what it covers, how it is built, what it found, and how to reproduce
it.

Every figure in this document was produced by running the suite against
the live demo stack on **2026-11-26** with **Playwright 1.65.1**.

> **The figures below are the ones of that run.** The regression numbers
> have moved since — the backend suite is 1487 tests now, not 1337 —
> because the M13.2 hardening round added the destination guard and the
> pre-token probe. The CURRENT state is reported in
> [M13-ACCEPTANCE-MATRIX.md](M13-ACCEPTANCE-MATRIX.md), which is the
> document the acceptance decision rests on. This one is the report of
> the suite itself.

---

## 1. The summary

| # | Area | Scenarios | Passed | Duration |
|---|---|---|---|---|
| E2E-01 | The USER journey | 2 | 2 | 3.0s |
| E2E-02 | The SECURITY_ADMIN journey | 1 | 1 | 2.1s |
| E2E-03 | The SOC_ANALYST journey | 1 | 1 | 2.2s |
| E2E-04 | The protective actions | 2 | 2 | 3.8s |
| E2E-05 | Policy Management | 2 | 2 | 4.1s |
| E2E-06 | The SECURITY_MANAGER analytics | 3 | 3 | 8.6s |
| E2E-07 | Role Based Access Control | 3 | 3 | 5.7s |
| E2E-08 | The authentication races | 4 | 4 | 8.6s |
| | **Total** | **18** | **18** | **38.9s** |

```
Running 18 tests using 1 worker
  18 passed (38.9s)
```

Zero failures, zero flakes, zero skips. The zero-skip figure is enforced
by the runner, not by convention: a skipped scenario proves nothing, so
`scripts/e2e_run.sh` reads the JSON results and **fails the run** when a
scenario was skipped.

The suite has found **six** defects in total: four by running it locally
against the demo stack (two in the product, two in the harness — see
section 5), and two more by running it in CI (one in the product, one in
the persistence layer — see section 5.3).

A final safety review of this branch found one more defect in the E2E
**harness** rather than in the suite itself: the fixture helper had no
database guard (defect 21, section 5.3). It is now fail-closed, and the
proof is a 46-test regression suite.

---

## 2. The principle: nothing is mocked

This is the single most important property of the suite, and it is the
reason the milestone needed a browser at all.

There is **no** `page.route()` interception, **no** fixture-swapped HTTP
client, **no** seeded fake response. The browser loads the real Vite dev
server, which proxies `/api` to the real FastAPI monolith, which reads
the real PostgreSQL databases and the real Redis.

Concretely:

* the OTP of the MFA handshake is **read out of the SMTP sink's log
  file** — the code genuinely travels through a real SMTP hop;
* the MFA gate is **proved by behaviour**: after a protective action
  sets `detection_mfa_once` in the Core context, the test lets the
  subject try to log in and observes the challenge;
* the degraded analytics payload is produced by **renaming the ML
  table** for real, so the read fails with a genuine database error;
* the 502 of a protective action is produced by an alert whose subject
  does not exist in the Core database, so the internal boundary
  genuinely fails;
* the expired session is produced by **moving the session's deadline
  into the past**, and the spent refresh token by **spending it** at the
  backend.

The alternative — faking a network failure — would only have proved
that the frontend can render a payload someone handed it. Breaking the
source proves that the facade **classifies** the failure correctly and
that the screen reacts to the classification.

### The fixtures are deterministic and owned by the scenarios

`scripts/e2e_fixtures.py` writes the rows the scenarios need directly
into the demo databases, with deterministic ids. It is the **only**
channel between the test process and the database, and it exists
because the alert lifecycle and the policy lifecycle are TERMINAL: a
resolved alert is immutable, an activated policy is frozen. A scenario
that worked on a *seeded* row would work exactly once, and the second
run of the suite would fail on a state it did not create.

The fixture bridge is idempotent — it re-arms the rows it owns
(`created_at = now()`, the policy removed and re-created, the MFA gate
reset, the rate limits cleared) — so the suite is re-runnable on the
same demo stack for ever.

---

## 3. The architecture

### 3.1 The layout

```
frontend/
  playwright.config.ts        the configuration — one worker, four reporters
  tsconfig.e2e.json           a strict typecheck of the suite
  e2e/
    e2e-01-user.spec.ts       the USER journey
    e2e-02-admin.spec.ts      the SECURITY_ADMIN journey
    e2e-03-soc.spec.ts        the SOC_ANALYST journey
    e2e-04-actions.spec.ts    the protective actions
    e2e-05-policy.spec.ts     Policy Management
    e2e-06-manager.spec.ts    the SECURITY_MANAGER analytics
    e2e-07-rbac.spec.ts       Role Based Access Control
    e2e-08-races.spec.ts      the authentication races
    support/
      fixtures.ts             the Playwright fixtures — the manifest
      manifest.ts             the typed reader of the fixture manifest
      login.ts                the login, the MFA handshake, the logout
      otp.ts                  the offset-based reader of the SMTP sink
      navigation.ts           the navigation, the row activation
      sessions.ts             the session list helpers
      api.ts                  the direct API client (for the 401/403/409)
      fixtureBridge.ts        the bridge to scripts/e2e_fixtures.py
scripts/
  e2e_fixtures.py             the database-side fixtures
  e2e_run.sh                  the runner
```

### 3.2 The configuration is strict on purpose

| Setting | Value | Why |
|---|---|---|
| `workers` | `1` | the scenarios **mutate shared state** — they acknowledge and resolve alerts, they activate policies, they revoke sessions. Parallel execution would make the outcome depend on the scheduling order. `workers: 1` is a *correctness* requirement, not a performance choice. |
| `fullyParallel` | `false` | the same reason, at the suite level. |
| `retries` | `1` | a test that needs a second attempt reports as **flaky**, and Playwright marks a flaky run as failed — so the retry can never hide a defect. |
| `timeout` | `90_000` | a hang is reported rather than waited out. |
| `expect.timeout` | `15_000` | a real browser against a real database needs more room than the forbidden 5s default. |
| `actionTimeout` | `15_000` | the budget for ONE interaction — shorter than the test timeout, so a control that never becomes clickable fails fast. |
| `trace` | `retain-on-failure` | the primary evidence for a failure. |
| `screenshot` / `video` | `only-on-failure` / `retain-on-failure` | the visual evidence. |
| `viewport` | `1440×900` | the screenshots stay comparable between runs. |
| `locale` / `timezoneId` | `vi-VN` / `Asia/Ho_Chi_Minh` | the application is in Vietnamese. |
| `baseURL` | the demo stack | read from `.env.demo` — a test that pointed elsewhere would be testing a different application. |

### 3.3 The four reporters

The configuration declares four reporters, and the runner **never**
overrides them — a command-line override would replace the JSON results
that the zero-skip check reads.

| Reporter | Output | Who reads it |
|---|---|---|
| `list` | the console | the developer |
| `junit` | `.ci/e2e/junit.xml` | the CI job publishes it as an artefact |
| `html` | `.ci/e2e/html-report/index.html` | a human |
| `json` | `.ci/e2e/results.json` | the zero-skip check |

---

## 4. The eight scenario groups

### E2E-01 — The USER journey

**What it proves.** The self-service contract, end to end, with the real
backend, the real session table and the real device table.

```
Login → Sessions → Trusted Devices → revoke a session → logout
```

| Step | The assertion |
|---|---|
| Login | the session list is the backend's real answer |
| Sessions | the sessions and the devices are listed |
| Revoke | the revoked session leaves the list |
| Logout | the session ends and the login screen returns |
| Guarded page, signed out | the application redirects to the login screen |

**The subtlety.** The session list is read through TanStack Query with a
30-second `staleTime`. A second visit to `/sessions` inside that window
is answered from the **cache**, not from the backend — so a session
created after the first visit would not show up. The test therefore
creates the second session **before** the first browser opens the list.

### E2E-02 — The SECURITY_ADMIN journey

**What it proves.** A real MFA handshake, the user directory and the
audit log.

```
Login → a REAL MFA handshake through the SMTP sink → User Management → Audit Logs
```

The admin account carries the permanent MFA flag, so the login **never**
returns a session on its own: the backend holds it for a challenge and
sends a six-digit code through a real SMTP hop into the local sink. The
test reads that code out of the sink and types it into the browser.

The test therefore proves three things at once:

1. the challenge screen really appears — the session does not exist
   before the code is verified;
2. the code really travels through SMTP — it is read from the sink's
   log file, not from a mocked response;
3. a **wrong** code is refused — which proves the handshake is really
   verified by the backend and is not a formality.

The IAM mutation the test performs is on `demo_user`: it grants the
`SOC_ANALYST` role and then revokes it again. The base role `USER` is
never touched — the backend refuses to revoke it, and the directory does
not even offer it.

### E2E-03 — The SOC_ANALYST journey

**What it proves.** The alert queue, the filters, the investigation, the
acknowledgement and the resolution.

```
Alert Queue → filter → Alert Detail → Evidence → Timeline → Acknowledge → Resolve
```

The scenario works on an alert **it owns** — `scripts/e2e_fixtures.py`
writes it with a deterministic id and re-arms it to `open` before the
test runs. The seeded alerts are never touched, so a defect in the
cleanup of the seeded data would still be visible.

### E2E-04 — The protective actions

**What it proves.** That a protective action really changed the Core
state, and that the UI tells the truth when it did not.

| Test | The assertion |
|---|---|
| The action is applied | the action runs; the subject's next login is **held for an MFA challenge** — the behavioural proof that `detection_mfa_once` was really set in the Core context |
| The 502 | the UI says **"HÀNH ĐỘNG KHÔNG ĐƯỢC ÁP DỤNG"** — the action was NOT applied |

**Why the behavioural proof.** `REQUIRE_MFA` sets
`users.detection_mfa_once` in the **Core** context — a flag no endpoint
exposes. The only honest way to show that the state really changed is
to let the subject try to log in. A test that only asserted "the request
returned 200" would prove nothing about the Core state.

**Why the 502 matters most.** For a security product, the failure mode
that matters most is a user believing they are protected when they are
not. The 502 is produced for real: the alert's subject does not exist
in the Core database, so the internal boundary genuinely fails and the
detection context genuinely answers 502.

### E2E-05 — Policy Management

**What it proves.** The draft lifecycle, the activation, the immutability
and the concurrency control.

| Test | The assertion |
|---|---|
| The lifecycle | a draft is created, edited, activated — and then **frozen**: a later edit is refused |
| The concurrency | a write with a **stale** `expected_updated_at` is refused with 409, and a write with the **fresh** token succeeds |

**The concurrency token.** The backend compares the `updated_at` the
client last read against the row's current value. A test that only
asserted "the save returned 409" would prove nothing — the scenario
must show that the conflict really came from a stale token, and that a
fresh token is accepted.

### E2E-06 — The SECURITY_MANAGER analytics

**What it proves.** All five analytics screens, plus the two contracts
that separate a working screen from a lying one.

| Test | The assertion |
|---|---|
| The five screens | each renders with a readable envelope |
| `null` is not a zero | a `null` metric renders as **"không có dữ liệu"**, never as a `0` |
| The degradation | a source that is down makes the payload **HTTP 200** with the affected section `null`; an endpoint that consumes **one** source answers **503** |

**The failure is a real fault.** The degraded/503 contract is proved by
**renaming the ML table**, so the read fails with a genuine database
error. Nothing is mocked and no application code is touched. The
restore runs in an `afterEach` hook, so a failed scenario never leaves
the demo stack degraded.

### E2E-07 — Role Based Access Control

**What it proves.** The route guards of the frontend **and** the
authorization of the backend, for every role of the demo stack.

| Test | The assertion |
|---|---|
| The route guards | a role that may not enter a section is refused the **URL**, and the forbidden screen is shown — not an empty screen |
| Each privileged role | every role enters its own sections and is refused the others |
| The backend | **401** without a token, **403** with the wrong role |

**Why both layers are tested.** The frontend guard and the backend
authorization are two independent lines of defence, and a test that
only exercises one of them proves nothing about the other:

* the frontend guard decides whether the **screen** is shown;
* the backend decides whether the **data** is served.

A guard that let a user open the URL of a section they may not enter
would show an empty screen and a 403 in the console — the user sees
nothing and cannot tell what happened. A backend that served the data
anyway would leak it.

**Why the 401 case is checked against the real API.** A 401 is the
answer to a request without a valid session. The frontend cannot
produce that request through the UI — it would never make it — so the
check goes to the API directly, with and without a token. A test that
only checked "the browser was sent to the login screen" would never
touch the backend's own answer.

### E2E-08 — The authentication races

**What it proves.** Four races, all of them produced by the real
backend.

| # | The race | The assertion |
|---|---|---|
| 1 | A cross-role transition | the analyst signs in, then the admin signs in; the admin's session **replaces** the analyst's — the previous identity, its navigation and its cached responses are gone, and the analyst's section is refused to the admin |
| 2 | A session that expires | the session's deadline is moved into the past, so the backend refuses both the access token and the refresh token; the application ends the session cleanly and routes to the login screen |
| 3 | A refresh that rotates | the backend rotates the refresh token on every refresh, so the copy the client holds is dead the moment the rotation happened; a client that used the spent token must end its session, and a client whose token is still valid must keep working |
| 4 | A stale 401 | a request that went out under an OLD session comes back with a 401 **after** the session was replaced; the epoch guard has to leave the newer session completely alone |

**Why the refresh lifecycle is observed in the browser.** The refresh
lifecycle of this application lives in the **axios interceptor** — in a
module-scoped variable, in memory, invisible to the DOM. A test that
only looked at the screen could not tell a successful refresh from a
silent one.

The evidence is therefore taken from two independent sources:

* the **network**: every `POST /auth/refresh` the browser makes is
  observed, and its answer is read. The single-flight mutex, the
  rotation and the replay are all visible there.
* the **backend**: the session table tells whether the token the
  browser holds is the one the server knows.

**The epoch guard.** The client's session carries an **epoch** that
increases with every session boundary. A 401 carries the epoch of the
session that produced it, and the client tears down the session only
when the epoch of the 401 is **not older** than the current one. A
response from an older session must never destroy a newer one — that is
the race the fourth test proves.

---

## 5. The defects the suite found

The suite was written against the running system, and the running system
answered with four defects. Two of them are **product** defects; two
are **harness** defects. All four were found by running the browser, not
by reading the code. (Two more were later found by running the same
suite in CI — they are in section 5.3.)

### 5.1 The product defects

| # | Defect | Symptom | Fix |
|---|---|---|---|
| P1 | The action dialog stayed open when the action **failed** | the failure notice of a protective action lives **below** the dialog in the document, and the dialog draws an 85% opaque curtain over the whole screen. A notice hidden behind that curtain is not a notice: the analyst saw the dialog still open and the action form still filled, with the reason for the refusal unreadable | `onError` now closes the dialog, so the outcome — the "HÀNH ĐỘNG KHÔNG ĐƯỢC ÁP DỤNG" banner — is handed back to the analyst in full view |
| P2 | The action was sent with an **empty reason** | `AlertActionRequest.reason` is `Field(..., min_length=1)`, so an empty reason is refused with a 422 — it never reaches Core, and it is therefore NOT a 502. The dialog let the analyst submit a request the server was bound to reject, and the validation error arrived after the fact | the reason is now `required`, the button is disabled without one, the hint explains that it is recorded in the alert's timeline, and the type says `reason: string` instead of `reason?: string \| null` |

P1 is the more serious of the two, because it hides the one message that
matters most in a security product: the one that says the protection
was **not** applied.

P2 is the more instructive, because the frontend's type was **wrong**
about the backend's contract. A nullable reason here could only ever
produce a request the server was bound to refuse.

The diff:

```diff
--- a/frontend/src/features/alerts/components/AlertActionPanel.tsx
+++ b/frontend/src/features/alerts/components/AlertActionPanel.tsx
-        reason: actionReason.trim() ? actionReason.trim() : null,
+        reason: actionReason.trim(),
     onSuccess: async () => { ... },
+    onError: () => {
+      setActionOpen(false)
+    },
@@
-              label="Lý do (không bắt buộc)"
+              label="Lý do"
+              hint="Bắt buộc — lý do được ghi vào dòng thời gian của cảnh báo."
+              required
@@
+            confirmDisabled={!actionReason.trim()}
```

```diff
--- a/frontend/src/types/api.ts
+++ b/frontend/src/types/api.ts
 export interface AlertActionRequest {
   action: SecurityAction
-  reason?: string | null
+  reason: string
 }
```

### 5.2 The harness defects

These are defects in the **test harness** — and they are worth listing
precisely because a harness defect is a suite that proves less than it
claims to.

| # | Defect | Symptom | Fix |
|---|---|---|---|
| H1 | A coordinate click on an alert row could land on the wrong row | the queue enriches its rows **asynchronously** with the subject metadata, which changes the row height from 34px to 46px. A `row.click()` therefore pressed the mouse on row 10 and released it on row 14 — the DOM event target was `<TBODY>`, the common ancestor, which bypasses React's synthetic row `onClick`. The click silently did nothing | `activateRow(row)` focuses the row and presses `Enter`, which activates the row's own `role="button"` handler with **zero** coordinate dependency |
| H2 | A re-armed fixture sank below the first page | the alert queue is paginated, newest first. The fixture re-armed the row but did not refresh its `created_at`, so as the test logins created background alerts, the scenario's own alert sank deeper than page 25 and the scenario could not find it | the re-arm now sets `created_at = now()`, so the alert is at the top of page 1 again |
| H3 | The unit-test runner picked up the **Playwright** specs | Vitest's default `include` glob is `**/*.{test,spec}.?(c|m)[jt]s?(x)`, which matches `e2e/*.spec.ts`. Playwright's `test.describe()` cannot be called from inside Vitest — it reports *"Playwright Test did not expect test.describe() to be called here"* — so eight spec files failed to load and the unit suite went red for a reason that had nothing to do with the unit suite | `vitest.config.ts` excludes `e2e/**`. The browser suite has its own runner |
| H4 | The linter applied **React** rules to the Playwright suite | `react-hooks/rules-of-hooks` complained about a fixture named `manifest` calling `use()` — but `use` there is **Playwright's** use — and `no-empty-pattern` complained about Playwright's documented `async ({}, use) => …` fixture signature | `eslint.config.js` turns both rules off for `e2e/**`. Renaming the fixtures to satisfy a React rule that does not apply to them would have been dishonest |

H1 is a good example of a defect that only a **real browser** can
surface. A component test renders a row and clicks it in a stable
layout; the real queue reflows under the pointer, and the event is
delivered to the wrong element. The diagnosis was made by capturing the
live `mousedown` / `mouseup` / `click` targets inside the page.

H3 and H4 are worth stating together, because they are the same class
of defect: a suite that owns its own runner and its own framework has
to be **excluded** from the frameworks that own the other suites. A
missing exclusion is not a cosmetic problem — it is a false signal in
the unit-test result, and a false signal in the lint result.

### 5.3 The defects the CI run surfaced

The four defects above were all found by running the suite locally
against the demo stack. The CI run of the same suite found two more,
and neither could have been found locally — one needed the CI's
dependency resolution, the other needed a production driver.

#### P3 — The alert timeline was not invalidated when a protective action failed

**Defect 19.**

| | |
|---|---|
| **Symptom** | the backend recorded "Security action `<ACTION>` was NOT enforced by Core" in the alert's timeline, but the panel never re-fetched it. The scenario asserted on the timeline and found the refusal note missing |
| **Cause** | `AlertActionPanel.tsx` invalidated the `['alerts']` query on **success** only. The `onError` path closed the dialog and set the banner, but left the query cache stale |
| **Why it matters** | this is a truthfulness defect: the system knew the protection had **not** been applied, and the interface refused to say so. The analyst reads a refusal as an applied action |
| **Fix** | `onError` awaits `invalidateAlerts()`, so the timeline re-fetches and the refusal note is rendered |

The diff:

```diff
--- a/frontend/src/features/alerts/components/AlertActionPanel.tsx
+++ b/frontend/src/features/alerts/components/AlertActionPanel.tsx
     onError: async () => {
       setActionOpen(false)
+      await invalidateAlerts()
     },
```

Note the ordering: the dialog is closed **first** (so the banner is in
view), and the cache is invalidated **afterwards** (so the re-fetch
cannot race the banner's render).

#### P4 — PostgreSQL `INET` columns were not strings

**Defect 20.**

| | |
|---|---|
| **Symptom** | `GET /api/v1/devices` returned **500**. Pydantic raised a `ValidationError` on `TrustedDeviceItem.last_ip: Optional[str]` — the value was an `ipaddress.IPv4Address`, not a `str` |
| **Cause** | SQLAlchemy 2.1 changed the default driver of a bare `postgresql://` URL from `psycopg2` to `psycopg` (psycopg 3). psycopg3 maps the PostgreSQL `INET` type to Python's `ipaddress` objects, where psycopg2 mapped it to `str` |
| **Why CI only** | the local environment had `psycopg2` installed, so the code was correct locally and wrong in CI, where the fresh install resolved psycopg 3 |
| **Fix** | three layers — a `StrINET` column type, a defensive cast in the response serialiser, and a pin on SQLAlchemy |

The pin restores the previous behaviour, but the pin is not the fix —
it is the *proof* that the behaviour had changed. The real fix is the
column type, which makes the behaviour correct **by construction**:

```python
class StrINET(INET):
    """An ``INET`` column that always yields ``str``.

    SQLAlchemy 2.1 switched the default driver of a bare
    ``postgresql://`` URL to psycopg 3, which maps PostgreSQL's
    ``INET`` type to ``ipaddress`` objects instead of ``str``.
    """

    def result_processor(self, dialect, coltype):
        super_processor = super().result_processor(dialect, coltype)

        def process(value):
            if value is None:
                return None
            if isinstance(value, str):
                return value
            try:
                return str(value)
            except Exception:
                return None

        if super_processor is None:
            return process
        return lambda value: process(super_processor(value))
```

and, on the model:

```python
def inet_type() -> INET:
    return StrINET().with_variant(Text(), "sqlite")
```

The defence is layered on purpose:

| Layer | Protects against |
|---|---|
| `StrINET` in `app/models.py` | the **column** returning a non-`str` under any driver or SQLAlchemy version |
| the explicit `str()` cast in `app/devices.py` | a value that reached the response builder by some other path |
| `sqlalchemy>=2.0.0,<2.1.0` in `requirements.txt` | the *known-bad* configuration, so CI fails loudly on a new driver instead of silently changing the semantics of every `INET` column in the schema |

The third layer is a pin, not a fix, and it is there on purpose: the
next driver change should be a **visible** event, not a silent one.

#### P5 — The E2E fixture helper had no database guard

**Defect 21.**

| | |
|---|---|
| **Symptom** | `scripts/e2e_fixtures.py` — the ONLY component of the browser suite that writes to a database directly — built its three engines from whatever URL the environment happened to carry. There was no check of any kind |
| **Cause** | the guard that protects `scripts/demo_seed_demo.py` was never applied to the E2E helper, and the helper's own docstring made a claim ("every fixture script refuses to write into a database without the `_demo` marker") that was true of the seed script and **false** of the helper |
| **Why it matters** | the helper DELETES rows (the alerts, the policies). A mistyped `CORE_DATABASE_URL`, or an environment left over from another stack, would have made the browser suite delete rows in a database it was never meant to touch. No production database was harmed, but the safety net was absent |
| **Fix** | `scripts/e2e_fixtures_guard.py` — a fail-closed, five-layer guard with a hard-coded per-context allowlist, a loopback-host rule and an explicit by-name declaration; every engine is built through it, and the guard runs BEFORE `create_engine`, so a refused URL never opens a connection |

The five layers, each of which refuses by default:

| Layer | The rule | A refused example |
|---|---|---|
| 1 | The database name must be EXACTLY one of the two names the context owns | `sentinel_core_demo_prod`, `sentinel_core_democracy` |
| 2 | The `*_test` and the canonical production names are refused outright | `sentinel_core_test`, `sentinel_core`, `postgres` |
| 3 | The server must be on the loopback interface | `db.internal`, `10.0.0.5`, `0.0.0.0` |
| 4 | The run must have declared — BY NAME — that it may write to that exact database | `E2E_ALLOW_WRITE_TO=true`, or a declaration for another database |
| 5 | The URL must come from the context's OWN variable | a `CORE_DATABASE_URL` pointing at the detection database |

Layers 1 to 4 are decided by the URL alone and the allowlists are
hard-coded module constants, so **no environment variable can widen
them**. Layer 5 is a separate input, and it must name the very database
the helper is about to write to, so a declaration made for one target
cannot carry over to another.

The declaration itself is derived from the very URLs the run is about to
use — `scripts/e2e_run.sh` computes it, and
`frontend/e2e/support/fixtureBridge.ts` computes it from the demo
environment it hands to the helper — so it can never name a database the
run does not actually reach.

The guard is proved by `tests/test_e2e_fixture_guards.py` (46 tests).
The claims that need a database are proved against a REAL PostgreSQL,
not with a mock: a refused run leaves the row count of the `alerts`
table unchanged, and no fixture row is created.

##### The one deliberate exception

`restore-active-policy` restores the demo stack's SEEDED active policy.
Every other operation touches only rows the E2E suite created; that one
deliberately touches a row it did NOT create.

It is legitimate because it is the RESTORE of a state the behaviour under
test changed: activating a policy deactivates the current one — that is
the product behaviour, and the browser scenario has to prove it — so the
seeded ACTIVE policy of the demo stack is no longer active and the demo
would drift away from its own fixtures. Putting the demo back the way
the scenario found it is a REQUIRED cleanup, not a way of hiding a
defect.

The exception is scoped as tightly as the principle it bends: it restores
ONE named policy, it only ever moves the ACTIVE SLOT, it never deletes a
policy, it never touches the E2E-owned policies, and it is still subject
to every guard above.

---

## 6. The CI integration

The `browser-e2e` job in `.github/workflows/ci.yml` runs the same suite
against the same script a developer runs.

### 6.1 The shape of the job

```yaml
browser-e2e:
  name: Browser E2E (real Chromium)
  runs-on: ubuntu-latest
  timeout-minutes: 40
```

| Stage | What it does |
|---|---|
| `services.postgres` | a disposable `postgres:16-alpine` with `scram-sha-256` |
| `services.redis` | a disposable `redis:7-alpine` on port 56379 |
| `Set up Node.js` / `Set up Python` | Node 22, Python 3.12 |
| `Install the Chromium build` | `npx playwright install --with-deps chromium` |
| `Bootstrap the demo databases` | `scripts/ci_bootstrap_demo_databases.sh` — the three `_ci_demo` databases |
| `Start the SMTP sink` | `scripts/ci_smtp_sink.py` — the real OTP hop |
| `Start the API` | the FastAPI monolith on 58000 |
| `Start the frontend` | the Vite dev server on 55173 |
| `Seed the fixtures` | `scripts/demo_seed_demo.py --seed --manifest-out …` |
| `Run the browser suite` | `scripts/e2e_run.sh --no-start` |
| `Publish the JUnit report` | `.ci/e2e/junit.xml`, 14-day retention |
| `Publish the failure diagnostics` | on failure only: the API, frontend and SMTP logs, plus the suite summary |

### 6.2 The database names are a safety boundary, not a convention

The CI job uses the three `_ci_demo` databases — a marker that is
**disjoint** from both the local demo stack's `_demo` databases and the
regression suite's `_test` databases:

| Marker | Databases | Owner |
|---|---|---|
| `_test` | `sentinel_core_test`, … | the regression suite |
| `_demo` | `sentinel_core_demo`, … | the local demo stack — **persistent** |
| `_ci_demo` | `sentinel_core_ci_demo`, … | the CI job — **disposable** |

The demo seed refuses to write to anything that does not carry `_demo`,
so the CI databases are named to satisfy that guard while never being
reachable from a local run. The CI bootstrap is the only script in the
repository that DROPs databases, and it carries five fail-closed
guards of its own — see
[M13-ACCEPTANCE-MATRIX.md](M13-ACCEPTANCE-MATRIX.md), section 8.

### 6.3 The same code path

The job does not reimplement the stack. It writes its own
`.env.demo`-shaped file at `DEMO_ENV_FILE: /tmp/e2e-demo.env` and then
calls the same `scripts/demo_stack.sh` and `scripts/e2e_run.sh` a
developer calls. The CI run and the local run therefore exercise the
**same** code path — which is the only way the local result means
anything for the CI result.

### 6.4 The artefacts are private

The Playwright trace records **everything**: DOM snapshots, network
traffic and console output — and the traffic carries bearer tokens,
passwords and OTP codes. The artefact directory therefore lives under
`.ci/`, which is gitignored, and the CI job publishes **only** the
JUnit XML. The HTML report, the traces and the videos are never
published as public artefacts.

### 6.5 The write declaration is part of the job

The fixture helper refuses to write to a database the run has not
declared **by name** (section 5.3, defect 21). The declaration is
derived from the very URLs the run is about to use:

* `scripts/e2e_run.sh` computes `E2E_ALLOW_WRITE_TO` from
  `CORE_DATABASE_URL`, `DETECTION_DATABASE_URL` and `ML_DATABASE_URL`;
* `frontend/e2e/support/fixtureBridge.ts` computes it from the demo
  environment it hands to the helper.

So the declaration can never name a database the run does not actually
reach, and it cannot widen the guard: the helper still checks the name
against a hard-coded allowlist, the host, and the fact that the URL came
from the context's own variable. The declaration says "this run meant to
write to this database" — it is not itself permission.

---

## 7. How to reproduce

### 7.1 Locally

```bash
# 1. the stack
cp .env.demo.example .env.demo
#    fill in POSTGRES_PASSWORD and INTERNAL_SECRET
scripts/demo_stack.sh start

# 2. the suite — it seeds the fixtures and installs Chromium itself
scripts/e2e_run.sh
```

The runner starts the stack if it is not up, seeds the fixtures, installs
the Chromium build when it is missing, and enforces the zero-skip
policy.

```bash
scripts/e2e_run.sh --headed        # watch it run
scripts/e2e_run.sh --no-start      # the stack is already up
scripts/e2e_run.sh e2e-08-races    # one file
```

### 7.2 The artefacts

| Artefact | Path |
|---|---|
| The HTML report | `.ci/e2e/html-report/index.html` |
| The JUnit XML | `.ci/e2e/junit.xml` |
| The JSON results | `.ci/e2e/results.json` |
| The traces, screenshots and videos | `.ci/e2e/output/` |

> **The artefacts contain bearer tokens and OTP codes. Do NOT publish
> them.**

### 7.3 The typecheck

The suite is typechecked separately from the application, under the same
strictness:

```bash
cd frontend
npx tsc -p tsconfig.e2e.json
```

`tsconfig.e2e.json` covers `e2e/` and `playwright.config.ts` with
`strict`, `noUnusedLocals`, `noUnusedParameters`, `noImplicitReturns`
and `erasableSyntaxOnly`.

---

## 8. The full regression

The browser suite is one suite among several. Adding it must not break
any of the others, so the whole regression was run after the suite was
finished.

| Suite | Command | Result |
|---|---|---|
| Backend regression | `python scripts/ci_verify_tests.py` | **1337 passed**, 0 failed, **0 skipped** |
| HTTP smoke | `python scripts/m10_http_smoke.py` | **79 passed**, 0 failed |
| Frontend unit/component | `npm run test` | **265 passed**, 0 failed, 18 files |
| Frontend integration | `npm run test:integration` | **50 passed**, 0 failed, 3 files |
| Deployment verification | `python scripts/deploy_verify.py` | **67 passed**, 0 failed |
| TypeScript (the app) | `npx tsc -b --force` | clean |
| TypeScript (the suite) | `npx tsc -p tsconfig.e2e.json` | clean |
| Lint | `npm run lint` | clean |
| Production build | `npm run build` | ✓ 1.74s |
| Demo scenarios | `python scripts/demo_scenarios.py --all` | **55 checks**, 2 consecutive runs |
| Browser E2E | `scripts/e2e_run.sh` | **18 scenarios**, 0 skipped, 2 consecutive runs |
| E2E database guard | `pytest tests/test_e2e_fixture_guards.py` | **46 passed**, 0 skipped |
| INET driver parity | `pytest tests/test_inet_driver_parity.py` | **15 passed**, 0 skipped |
| The diff | `git diff --check` | clean |

```
collected=1337 passed=1337 failed=0 skipped=0 error=0 xfailed=0
[ci-verify] the suite passed with zero failures and zero skips
```

The zero-skip figure is the point of the whole exercise — in the
backend suite as much as in the browser suite. A skipped scenario proves
nothing, and a scenario that quietly stopped running is not a suite
that is passing; it is a suite that stopped covering something.

---

## 9. The result

```
Running 18 tests using 1 worker

  ✓  1 E2E-01 — USER › logs in, reads the sessions and the devices, revokes a session and logs out (2.7s)
  ✓  2 E2E-01 — USER › refuses to reach a guarded page while signed out (300ms)
  ✓  3 E2E-02 — SECURITY_ADMIN › completes a real MFA handshake, reaches the user directory and the audit log (2.1s)
  ✓  4 E2E-03 — SOC_ANALYST › filters the queue, investigates an alert, acknowledges and resolves it (2.2s)
  ✓  5 E2E-04 — Protective actions › applies a protective action and proves the Core state really changed (2.2s)
  ✓  6 E2E-04 — Protective actions › reports a 502 as "the action was NOT applied" (1.6s)
  ✓  7 E2E-05 — Policy Management › creates a draft policy, edits it, activates it and proves it is frozen (3.0s)
  ✓  8 E2E-05 — Policy Management › refuses a stale write with 409 and accepts the fresh token (1.1s)
  ✓  9 E2E-06 — SECURITY_MANAGER analytics › shows all five analytics screens with a readable envelope (2.0s)
  ✓ 10 E2E-06 — SECURITY_MANAGER analytics › renders a null metric as "no data" and never as a zero (1.8s)
  ✓ 11 E2E-06 — SECURITY_MANAGER analytics › degrades to a 200 payload when a source is down, and answers 503 when every source is (4.8s)
  ✓ 12 E2E-07 — RBAC › hides the sections a role may not enter and shows the forbidden screen (1.2s)
  ✓ 13 E2E-07 — RBAC › lets each privileged role into its own sections and refuses the others (3.7s)
  ✓ 14 E2E-07 — RBAC › answers 401 without a token and 403 with the wrong role (824ms)
  ✓ 15 E2E-08 — Authentication races › replaces the analyst session with the admin one (2.8s)
  ✓ 16 E2E-08 — Authentication races › ends the session and returns to the login screen when it expires (1.4s)
  ✓ 17 E2E-08 — Authentication races › ends the session when the refresh token has already been spent (2.6s)
  ✓ 18 E2E-08 — Authentication races › does not tear down a newer session when a stale request answers 401 (1.8s)

  18 passed (38.9s)
```

The suite is **re-runnable**: the scenarios own their fixtures, the
fixture bridge re-arms them, and the second run proves it — a suite
that only works once is not a suite.

---

## 10. Related documents

* [M13-ACCEPTANCE-MATRIX.md](M13-ACCEPTANCE-MATRIX.md) — every criterion of the milestone and how it was verified
* [M13-FULLSTACK-DEPLOYMENT.md](M13-FULLSTACK-DEPLOYMENT.md) — the demo stack
* [M13-DEMO-FIXTURES.md](M13-DEMO-FIXTURES.md) — the reproducible fixtures
* [M13-DEMO-SCENARIOS.md](M13-DEMO-SCENARIOS.md) — the six API-level demo scenarios
