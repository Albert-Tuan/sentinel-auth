# M13 — Reproducible Demo Fixtures

> Sentinel Auth v3.3 · Milestone M13.1
> Deterministic, idempotent fixtures for the whole demo.

`scripts/demo_seed_demo.py` creates the data a demo needs: the four demo
accounts, their sessions, their devices, the alerts across every risk
level and status, the policies, and the ML statistics.

The script has three properties that matter more than the data itself:

* **Deterministic.** Every identifier is derived from a UUIDv5, so the
  same seed produces the same rows with the same ids.
* **Idempotent.** Seeding twice leaves the database in the same state.
  The second run replaces the fixture rows; it does not add a second
  copy of them.
* **Safe.** The script refuses to run against a database that is not a
  demo database, and its cleanup only ever removes rows it owns.

---

## 1. Usage

```bash
# create the fixtures
scripts/demo_seed_demo.py --seed

# create the fixtures and write the manifest of their identifiers
scripts/demo_seed_demo.py --seed --manifest-out .ci/demo/fixture-manifest.json

# remove the fixtures again
scripts/demo_seed_demo.py --cleanup

# print the identifiers without touching a database
scripts/demo_seed_demo.py --manifest
```

The script reads three environment variables:

| Variable | The database |
|---|---|
| `CORE_DATABASE_URL` | `sentinel_core_demo` |
| `DETECTION_DATABASE_URL` | `sentinel_detection_demo` |
| `ML_DATABASE_URL` | `sentinel_ml_demo` |

---

## 2. The safety guards

### 2.1 The disposable database marker

Every database name must carry the `_demo` marker. The check happens
**before the engines are created**, so nothing connects and nothing can
be written or deleted until every target has been proven disposable.

```python
core_name = assert_demo_database(core_url)
detection_name = assert_demo_database(detection_url)
ml_name = assert_demo_database(ml_url)
```

A database named `sentinel_core` — the real one — is refused.

### 2.2 The fixture marker

Every fixture row carries the marker `m13-demo-fixture` in a free-text
column. The cleanup finds the rows again through that marker, so it
never has to guess which rows it owns.

### 2.3 No bulk deletes

The cleanup deletes **one row at a time**, and only the rows that carry
the marker. It never issues a `TRUNCATE` and never calls `drop_all`.
`tests/test_demo_fixtures.py` asserts exactly this.

---

## 3. The deterministic identifiers

Every id comes from a UUIDv5 over a fixed namespace:

```python
FIXTURE_NAMESPACE = uuid.UUID("6f9619ff-8b86-d011-b42d-00cf4fc964ff")

def fixture_id(kind: str, key: str) -> str:
    return str(uuid.uuid5(FIXTURE_NAMESPACE, f"{kind}:{key}"))
```

The `kind` is the namespace of the entity:

| `kind` | The row |
|---|---|
| `user` | a demo account |
| `session` | a seeded session |
| `device` | a trusted device |
| `mfa` | an MFA transaction |
| `policy` | a policy |
| `alert` | an alert |
| `login_attempt` | a login attempt |
| `risk_assessment` | a risk assessment |
| `detection_log` | a detection log |
| `alert_timeline` | a timeline event |
| `soc_analyst` | a SOC analyst |
| `inference_log` | an ML inference |
| `feature_statistic` | an ML feature statistic |
| `model_version` | an ML model version |
| `ip_address` | a normalised IP address |

The consequence is that the manifest is **predictable**: a script can
compute the id of a fixture row it wants to work with, without reading
the manifest at all. `scripts/demo_scenarios.py` does exactly this.

---

## 4. The manifest

The manifest records the identifiers of everything the seed created:

```json
{
  "marker": "m13-demo-fixture",
  "core": {
    "users": {
      "admin": {
        "id": "faa67760-a339-542c-992c-ba547113f434",
        "username": "demo_admin",
        "email": "demo_admin@example.test",
        "mfa_required": true,
        "roles": ["SECURITY_ADMIN", "USER"]
      }
    },
    "sessions": [...],
    "devices": [...],
    "ip_ids": {...}
  },
  "detection": {
    "alerts": {
      "critical_open": {
        "id": "c2f96bbc-e917-5306-bb2c-7b8d84c3fcdc",
        "status": "open",
        "risk_level": "critical",
        "subject_user_id": "51da2d47-d7f1-5fbe-8eed-eb48e404ae7d"
      }
    },
    "analysts": [...],
    "policies": {...}
  },
  "ml": {...}
}
```

`scripts/demo_scenarios.py` reads the manifest to find the alerts, the
SOC analysts and the policies it works with.

---

## 5. The demo accounts

| Key | Username | Roles | MFA |
|---|---|---|---|
| `user` | `demo_user` | `USER` | no |
| `analyst` | `demo_analyst` | `SOC_ANALYST`, `USER` | no |
| `admin` | `demo_admin` | `SECURITY_ADMIN`, `USER` | **yes, permanent** |
| `manager` | `demo_manager` | `SECURITY_MANAGER`, `USER` | no |

The default password is `DemoPass!2026`. It can be overridden per
account:

| Account | Variable |
|---|---|
| `demo_user` | `DEMO_USER_PASSWORD` |
| `demo_analyst` | `DEMO_ANALYST_PASSWORD` |
| `demo_admin` | `DEMO_ADMIN_PASSWORD` |
| `demo_manager` | `DEMO_MANAGER_PASSWORD` |

`demo_admin` carries the **permanent** MFA flag, so its login always
ends in a challenge. The other three accounts may also be challenged at
runtime: the Detection context can hold a token back for any account
whose login looked risky, through the very same one-time MFA machinery.

---

## 6. What is seeded

### 6.1 Core

* **4 accounts** with their roles.
* **3 sessions** — one per account, all active.
* **3 device records** — two trusted devices (the analyst's laptop, the
  manager's desktop) and one **pending** request (the user's phone).
* **IP addresses** — the normalised rows the sessions and the attempts
  refer to.

### 6.2 Detection

* **5 alerts**, one per combination that the demo screens have to show:

| Key | Risk level | Status | What it demonstrates |
|---|---|---|---|
| `critical_open` | critical | open | the alert that must be worked on first |
| `high_acknowledged` | high | acknowledged | an alert that is already owned |
| `medium_open_ruleless` | medium | open | the **rule-only fallback** — no ML score |
| `low_resolved` | low | resolved | a finished alert with its resolution |
| `low_false_positive` | low | false positive | a false positive, correctly labelled |

* **2 policies** — a draft (`m13-demo-draft`) and an active one
  (`m13-demo-active`).
* **Risk assessments, detection logs and timeline events** for every
  alert, so the evidence screens are never empty.
* **1 SOC analyst**, so the assignment workflow has a valid target.

### 6.3 ML

* **7 inference logs** across the days of the demo window.
* **6 feature statistics**.
* **1 staged model version** — and **never a promoted one**.

> The ML model is **staged, never promoted**. The registry holds a
> placeholder with no file behind it; the scoring endpoint answers
> `503` and the Detection engine falls back to its rules. The demo
> reports that state honestly instead of pretending a model is loaded.

---

## 7. The problems the seed has to solve

### 7.1 The circular foreign key

`login_attempts.primary_alert_id` refers to `alerts.id`, and
`alerts.login_attempt_id` refers back to `login_attempts.id`. Neither
can be inserted first.

The seed breaks the cycle in three steps:

1. insert the `LoginAttempt` with `primary_alert_id = None`;
2. insert the `Alert`;
3. flush, then set `attempt.primary_alert_id = alert_id`.

### 7.2 The single active policy

The database carries a unique index that allows only **one** active
policy. Inserting a second active policy violates it.

The seed therefore deactivates the existing active policy and **flushes
before** it writes the new one. Without the explicit flush, the
deactivation would still be pending in the session and the unique index
would be evaluated against the old state.

### 7.3 The numeric scale

`feature_statistics` uses `NUMERIC(10, 6)`. A value in **seconds** does
not fit — a login interval of 5 400 seconds overflows the column.

The feature is therefore expressed in **minutes**
(`average_login_interval_minutes`), which is also the unit a reader of
the demo screen expects.

### 7.4 The stale role links

The seed replaces the role links of its own accounts so a re-seed picks
up a change to the role set. It deletes only the `UserRole` rows of the
four fixture accounts — never a bulk delete.

`tests/test_demo_fixtures.py` asserts that a bulk delete (`TRUNCATE`,
`drop_all`) never appears in the seed.

---

## 8. The tests

```bash
pytest tests/test_demo_fixtures.py -q
```

26 tests, in two groups.

### 8.1 The unit tests

They run without a database and cover:

* the disposable database marker is enforced;
* the identifiers are deterministic;
* the manifest is valid and complete;
* the seed never deletes anything but its own rows.

### 8.2 The integration tests

They are marked `requires_demo_databases` and are skipped unless the
three demo URLs are exported:

```bash
export DEMO_CORE_DATABASE_URL=...
export DEMO_DETECTION_DATABASE_URL=...
export DEMO_ML_DATABASE_URL=...
pytest tests/test_demo_fixtures.py -q
```

They seed twice and compare the row counts, which is the idempotency
proof; and they clean up and check that the ML model was never promoted.

---

## 9. Related documents

* [M13-FULLSTACK-DEPLOYMENT.md](M13-FULLSTACK-DEPLOYMENT.md) — the demo stack
* [M13-DEMO-SCENARIOS.md](M13-DEMO-SCENARIOS.md) — the six demo scenarios
* [M13-ACCEPTANCE-MATRIX.md](M13-ACCEPTANCE-MATRIX.md) — the acceptance matrix
