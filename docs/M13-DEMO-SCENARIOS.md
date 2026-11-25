# M13 — The Demo Scenarios

> Sentinel Auth v3.3 · Milestone M13.2
> Six scenarios that exercise the whole system against a live stack.

`scripts/demo_scenarios.py` runs six scenarios against a running demo
stack. Each scenario proves one capability of the system, and each one
prints a line per check.

This document explains what each scenario proves. The script proves it.

---

## 1. Usage

```bash
scripts/demo_scenarios.py --list          # the scenarios and their titles
scripts/demo_scenarios.py --all           # all six (the default)
scripts/demo_scenarios.py --scenario A    # one scenario
scripts/demo_scenarios.py --scenario D --scenario F
scripts/demo_scenarios.py --no-colour     # plain output
```

The script needs a running stack and the seeded fixtures:

```bash
scripts/demo_stack.sh start
scripts/demo_seed_demo.py --seed --manifest-out .ci/demo/fixture-manifest.json
scripts/demo_scenarios.py --all
```

The exit code is `0` when every check passed, `1` otherwise.

### Options

| Option | Default | Meaning |
|---|---|---|
| `--base-url` | `http://127.0.0.1:58000` | the demo API |
| `--manifest` | `.ci/demo/fixture-manifest.json` | the fixture manifest |
| `--otp-log` | the path in `.ci/demo/otp-log.path` | the SMTP sink's log |
| `--otp-timeout` | `30` | how long to wait for an OTP |
| `--login-retry-timeout` | `120` | how long to keep retrying a rate-limited login |
| `--login-retry-wait` | `65` | how long to wait between two login attempts |

---

## 2. The principles

### 2.1 The scenarios are re-runnable

A demo that only works once is not a demo. Every scenario restores the
state it needs before it starts, so the six scenarios can be run in any
order, as often as you like.

The restorations are narrow and explicit:

* an alert that an earlier run acknowledged is put back to the state the
  **seed** created — the fixture set is the reference;
* the one-time MFA gate of an account is re-armed before it is proved;
* the policy that the scenario activated is deactivated again by
  reactivating the seeded active policy.

### 2.2 The scenarios prove behaviour, not internals

Wherever it is possible, a check reads the **observable behaviour**
rather than an internal flag. The MFA gate, for example, is proved by a
login that is held back — not by reading the flag that gates it. The
flag is internal to the core context and deliberately exposed by no
endpoint, so reading it would not prove anything a user could see.

### 2.3 The scenarios never fake a failure

The 502 case is a **real** 502: the scenario creates an alert whose
subject does not exist in the core database, so the internal boundary
genuinely fails and the detection context genuinely answers 502. It is
not a simulated response.

---

## 3. Scenario A — Authentication

*8 checks*

| Check | What it proves |
|---|---|
| `demo_user` logs in | a plain login returns a token |
| the token identifies the account on `/auth/me` | the token is bound to the account |
| the account carries the `USER` role | the roles are read from the database, not from the token |
| the session list shows the sessions | the sessions are visible to their owner |
| `demo_admin` completes the MFA handshake | the permanent MFA flag holds the token back |
| the OTP arrives through a real SMTP hop | the delivery is genuine, not a stub |
| `demo_admin` carries `SECURITY_ADMIN` | the second role is granted correctly |
| the refresh endpoint issues a new token | the refresh flow works |
| the logout accepts the session | the session can be closed |

### The MFA handshake

`demo_admin` carries the **permanent** MFA flag, so its login always
ends in a challenge:

1. `POST /api/v1/auth/login` answers `mfa_required: true` with a
   session id;
2. the OTP is delivered by the API through the SMTP sink;
3. the scenario reads the code from the sink's log and exchanges it at
   `POST /api/v1/auth/mfa/verify` for the tokens.

Other accounts may be challenged too: the Detection context can hold a
token back for **any** account whose login looked risky, through the
very same one-time MFA machinery. The scenario therefore performs the
handshake whenever the API asks for one — it does not assume which
accounts are gated.

### The OTP is read by offset

The sink's log **accumulates** every message it has ever captured. A
code read without an offset may well belong to an *earlier* login, and
a stale code is rejected by the API as "Invalid MFA code".

The reader is therefore **offset-based**: the size of the log is taken
*before* the login is called, and only what was written after that point
is considered.

The path of the log comes from `.ci/demo/otp-log.path`, which the demo
stack writes when it starts the sink. It is the single source of truth:
the sink writes to that path and the scenario script reads from it.

### The refresh rotates the token

The refresh endpoint takes the **refresh token**, and it **rotates** the
session: it issues a new pair of tokens and invalidates the old access
token. The logout therefore uses the **new** token — the old one would
be rejected with a 401 that says nothing about the logout itself.

---

## 4. Scenario B — Device trust

*7 checks*

| Check | What it proves |
|---|---|
| the trusted device list holds the device | the list is per account |
| a pending device request is created | the request flow works |
| the device check answers | the check endpoint works without a token too |
| the account approves its own request | the approval works |
| the approval returns the new device id | the approval created the device |
| the approved request completes the login | the completion hands out a token |
| the device is now trusted | the state changed |

### The rules the flow follows

* **The device list is per account.** The API shows only the devices of
  the account that is logged in.
* **The request is approved by the same account.** The pending request
  is an MFA transaction of the `trusted_device` type; it belongs to the
  account that asked for it, and an existing session of that **same**
  account approves it.
* **The fingerprint comes from the headers.** The API derives the
  device fingerprint from the request headers, so the scenario sends a
  `User-Agent` that is unique to the run. Without that, a second run
  would find the device of the first run already trusted and the
  approval would have nothing to approve. The completion sends the
  **same** headers, because the API refuses a fingerprint mismatch.
* **The one-time MFA gate is cleared first.** The request endpoint
  refuses to run while the account is gated by a one-time MFA
  requirement — it will not let the device flow bypass the challenge.

---

## 5. Scenario C — SOC investigation

*12 checks*

| Check | What it proves |
|---|---|
| the alert list holds the seeded alerts | the list works and is paginated |
| the list shows every status | `open`, `acknowledged`, `resolved`, `false_positive` |
| the list holds a seeded alert | the fixture set is reachable |
| the evidence endpoint returns the alert, the attempt and the assessment | the evidence is assembled |
| the evidence carries the risk assessment | the scoring is visible |
| the evidence carries the detection logs | the pipeline is visible |
| the timeline holds the seeded entries | the history is visible |
| the analyst acknowledges the alert | the workflow moves forward |
| the alert is acknowledged after the call | the change is persisted |
| the manifest carries the id of a SOC analyst | the assignment has a valid target |
| the analyst is assigned to the alert | the assignment works |
| the alert carries the assignee | the change is persisted |

### The assignee is a SOC analyst, not a user

`assigned_to_id` refers to `soc_analysts.id` in the **detection**
context, not to `users.id` in the **core** context. The seed creates one
SOC analyst and the manifest carries its id.

### The scenario owns its alert

The scenario works on the `critical_open` alert; scenario D works on
`medium_open_ruleless`. The two therefore never fight over the same
row, and each one can restore its own alert when an earlier run has
moved it forward.

---

## 6. Scenario D — Protective actions

*9 checks*

| Check | What it proves |
|---|---|
| the alert list holds an open alert with a real subject | the scenario works on a real account |
| the analyst triggers the `REQUIRE_MFA` action | the action is applied |
| the response echoes the action | the answer describes what happened |
| the next login is held for an MFA challenge | **the state really changed** |
| the internal boundary answers for the subject | the contexts are separate |
| a protective action Core cannot enforce answers 502 | the failure is reported honestly |
| the 502 says the action was **not** enforced | the message is honest |
| the failed action is recorded in the timeline | the SOC can see the failure |
| the client keeps working after the failure | the failure does not break the session |

### The boundary is respected

Detection does **not** mutate the Core state directly. It asks Core to
enforce the action through the internal boundary:

```
POST /api/v1/internal/actions
```

The boundary is guarded by the shared secret, not by a bearer token:
there is no human on the other side of the call, and a user token must
not be able to cross the boundary.

### The 502 case is real

The scenario creates an alert whose `login_attempt` points at a user
that was never created in the core database. The boundary call
therefore genuinely fails, and the detection context genuinely answers:

```json
{
  "detail": "Core did not apply the REQUIRE_MFA action. The protective action was NOT enforced."
}
```

Three things are proved at once:

1. the answer is a **502**, not a 200 that pretends the action worked;
2. the message says the action was **not** enforced;
3. the failure is **recorded in the timeline**, so the SOC can see that
   the action was requested and did not take effect.

The client survives the failure: the next call still works.

---

## 7. Scenario E — Policy management

*11 checks*

| Check | What it proves |
|---|---|
| the policy list holds the draft and the active policy | the list works |
| exactly one policy is active | the single-active-policy rule holds |
| a draft policy is created | the creation works |
| the draft is readable and is not active | a draft has no effect |
| the draft is edited | the update works |
| a stale update is rejected with 409 | the compare-and-swap works |
| the draft is activated | the activation works |
| the activated policy cannot be edited — 409 | an active policy is immutable |
| the client cannot deactivate by setting `is_active` | the activation is server-side |
| the original active policy is activated again | the stack is restored |
| the deactivated policy kept its content | the content survives the deactivation |

### The scenario creates its own draft

A policy that has been activated becomes **immutable** — the historical
risk assessments reference it — so the seeded draft can only be edited
once. The scenario creates a **fresh** draft instead, which keeps it
re-runnable and exercises the same lifecycle a real operator goes
through.

The version has a strict format (`v` followed by numbers separated by
dots), so the run stamp is reduced to its numeric part.

### The compare-and-swap

The update carries the `updated_at` the client read. A stale value is
rejected with a 409 that says exactly why:

```json
{
  "detail": {
    "message": "Policy was modified by someone else",
    "problems": ["expected_updated_at does not match the current policy; re-read the policy and retry"]
  }
}
```

### The two refusals are different

* **Editing an active policy** → `409`, "Policy is immutable".
* **Setting `is_active` by hand** → `400`, "`is_active` is managed by the
  server and cannot be set by the client".

The first is a state rule; the second is a request rule.

---

## 8. Scenario F — Manager analytics

*8 checks*

| Check | What it proves |
|---|---|
| the dashboard returns the core and the detection sections | the dashboard is assembled from both contexts |
| the dashboard counts the demo accounts | the core section is real |
| the dashboard counts the login attempts | the detection section is real |
| the dashboard counts the alerts | the alert counters are real |
| the trends endpoint returns a series | the trend is computed |
| the SOC KPI endpoint returns its counters | the KPI is computed |
| the ML statistics endpoint returns the model state | the ML section is real |
| the dashboard does not claim a production model | **the demo tells the truth** |

### The last check is the important one

The ML artifact is not loaded. The registry holds a staged placeholder
with no file behind it, the scoring endpoint answers `503`, and the
Detection engine falls back to its rule-only score.

The dashboard reports `model_status: error` and
`active_model_version: null`. It does **not** claim a production model,
and it does **not** show a zero where there is no data.

---

## 9. The login rate limit

The API allows five login attempts per minute and per IP. The scenarios
log several accounts in, so a run that is repeated quickly trips the
limit.

That is the API behaving **correctly**, not a failure of the demo. The
scenario therefore retries a `429` instead of failing on it, and it says
so:

```
the login rate limit answered 429; retrying 'demo_admin' in 65s
the login of 'demo_admin' succeeded on attempt 2 after the rate limit expired
```

---

## 10. The result

A complete run of the six scenarios is **55 checks**:

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

## 11. Related documents

* [M13-FULLSTACK-DEPLOYMENT.md](M13-FULLSTACK-DEPLOYMENT.md) — the demo stack
* [M13-DEMO-FIXTURES.md](M13-DEMO-FIXTURES.md) — the reproducible fixtures
* [M13-ACCEPTANCE-MATRIX.md](M13-ACCEPTANCE-MATRIX.md) — the acceptance matrix
