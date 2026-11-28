# M13 — Full-stack Demo Deployment

> Sentinel Auth v3.3 · Milestone M13.0
> The demo environment of the whole system, brought up with one command.

This document explains how to run the complete Sentinel Auth demo on a
local machine: three PostgreSQL databases, Redis, the FastAPI monolith
and the Vite frontend, plus the SMTP sink that delivers the MFA codes.

The demo is a **separate deployment**. It has its own configuration file,
its own ports and its own database names, so it can run next to an
existing local deployment without either of them interfering with the
other.

---

## 1. What the demo stack is

| Component | What it is | Port |
|---|---|---|
| PostgreSQL | the three-database topology (Core, Detection, ML) | `55432` |
| Redis | the cache and the session store | `56379` |
| SMTP sink | a local SMTP server that captures the MFA OTP | `51025` |
| FastAPI monolith | Core, Detection and ML in one process | `58000` |
| Vite dev server | the React frontend | `55173` |

The three databases are the heart of the system. Each bounded context
owns its own schema, and the application enforces the boundary in the
session dependency rather than in the table definitions:

| Database | Tables | Owns |
|---|---|---|
| `sentinel_core_demo` | 13 | users, roles, sessions, devices, MFA, audit |
| `sentinel_detection_demo` | 7 | login attempts, alerts, policies, risk assessments, detection logs, timelines |
| `sentinel_ml_demo` | 3 | model versions, inference logs, feature statistics |

The names carry the `_demo` marker. **Every M13 fixture script refuses to
run against a database whose name does not carry that marker**, so a
mistake in a script can never write into a production or a test
database.

### The relationship to `scripts/deploy_local.sh`

The demo stack does **not** replace the canonical deployment and does
**not** modify it.

* `scripts/deploy_local.sh` keeps reading `.env`, keeps its own ports
  and keeps its own database names.
* `scripts/demo_stack.sh` reads `.env.demo` and uses its own ports and
  its own database names.

The demo stack reuses `scripts/deploy_local.sh` for the infrastructure
layer — it calls the same compose file with the same schema bootstrap —
so the repository holds exactly **one** definition of "the
three-database topology".

---

## 2. Getting started

### 2.1 Prerequisites

| Requirement | Notes |
|---|---|
| Docker or Podman | Podman works; the rootless mode is supported |
| Python 3.11+ | the application and the scripts |
| Node.js 18+ | the frontend |
| `psql` | optional; the stack reports the database state without it |

### 2.2 Create the environment file

```bash
cp .env.demo.example .env.demo
```

Then fill in the two secrets. The stack refuses to start with the
placeholder values:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"   # INTERNAL_SECRET
python3 -c "import secrets; print(secrets.token_urlsafe(16))"   # POSTGRES_PASSWORD
```

`.env.demo` is gitignored. `.env.demo.example` holds placeholders only.

### 2.3 Start the stack

```bash
scripts/demo_stack.sh start
```

The command brings up the infrastructure, the SMTP sink, the API and the
frontend, and it waits for each of them to become ready before it moves
on. A successful start ends with:

```
[demo] the demo stack is up:
[demo]   frontend  : http://127.0.0.1:55173
[demo]   API       : http://127.0.0.1:58000
[demo]   readiness : http://127.0.0.1:58000/ready
[demo]   liveness  : http://127.0.0.1:58000/health
[demo]   logs      : .../.ci/demo
```

### 2.4 Seed the fixtures

```bash
scripts/demo_seed_demo.py --seed
```

See [M13-DEMO-FIXTURES.md](M13-DEMO-FIXTURES.md) for the details.

### 2.5 Run the scenarios

```bash
scripts/demo_scenarios.py --all
```

See [M13-DEMO-SCENARIOS.md](M13-DEMO-SCENARIOS.md) for the details.

---

## 3. The lifecycle commands

| Command | What it does |
|---|---|
| `start` | start the infrastructure, the SMTP sink, the API and the frontend |
| `stop` | stop everything — **the demo volumes are kept** |
| `restart` | stop and start again; the data must survive |
| `status` | show what is running and the real state of Core, Detection and ML |
| `verify` | run the demo acceptance checks |
| `logs` | tail the API log |
| `logs-all` | show the tail of every component log |
| `reset` | stop and **destroy** the demo volumes — it asks for a typed confirmation first |

`stop` never destroys a volume. Only `reset` does, and it asks first.
The demo stack never touches the canonical deployment's `.env`, its
ports or its databases.

---

## 4. The port conflict check

Before the stack starts, it checks every port it is going to use. A
port that is already taken is a hard failure with a message that names
the process, because a silent collision produces a demo that fails in
confusing ways much later.

The check distinguishes two cases:

* **A foreign process holds the port.** The start fails and names the
  owner.
* **The demo's own container holds the port.** This is not a conflict:
  the stack recognises its own containers by the compose project label
  (`com.docker.compose.project` / `io.podman.compose.project`) and
  carries on.

The demo uses deliberately non-standard ports (55432, 56379, 51025,
58000, 55173) so it can coexist with a default installation.

---

## 5. The schema staging and SELinux

A rootless container on SELinux systems cannot read a bind mount from a
removable or an external path: the mount carries no label the container
is allowed to access, and PostgreSQL's initialisation fails with
`Permission denied`.

The demo stack solves this by **staging** the schema files:

1. the schema files are copied into `~/.cache/sentinel-auth-demo/postgres`;
2. the compose overlay (`docker-compose.demo.yml`) mounts that directory
   with the `:ro,z` options — read-only, and relabelled for the
   container.

The staging directory is outside the repository on purpose: it must not
depend on the repository living on a removable disk.

---

## 6. The process group isolation

The Vite dev server and the background tasks are started under
`setsid`, so each one becomes the leader of its own process group. The
stop command then signals the whole group with `-PID`.

This matters because `npm run dev` wraps Vite: the signal would reach
the wrapper and not the server, the port would stay bound, and the
orphan `esbuild` workers would keep running. The demo stack therefore
starts `./node_modules/.bin/vite` **directly** inside a `setsid`
subshell, and it signals the group rather than the single process.

---

## 7. The logs

Every component writes into `${DEMO_STATE_DIR}` (`.ci/demo` by default):

| File | Content |
|---|---|
| `api.log` | the monolith |
| `web.log` | the Vite dev server |
| `smtp.log` | the SMTP sink |
| `demo-otp.log` | the captured MFA codes |
| `*.pid` | the process id of each component |
| `otp-log.path` | the **resolved** path of the OTP log |

`otp-log.path` is the single source of truth for the OTP log. The stack
writes the resolved, absolute path into it before it starts the sink,
and `scripts/demo_scenarios.py` reads it. A relative path is resolved
against the **repository root**, so the sink and the scenario script
always read the same file no matter which directory either of them was
started from.

---

## 8. The configuration reference

The full template is `.env.demo.example`. The settings that matter most:

### The topology

| Variable | Meaning |
|---|---|
| `POSTGRES_PORT` | the published port of the demo PostgreSQL |
| `CORE_DB`, `DETECTION_DB`, `ML_DB` | the three database names |
| `CORE_DATABASE_URL`, `DETECTION_DATABASE_URL`, `ML_DATABASE_URL` | the three connection URLs |
| `ALLOW_LEGACY_SINGLE_DB` | stays `0`; the demo runs the real topology |

### The monolith

| Variable | Meaning |
|---|---|
| `CORE_APP_URL`, `DETECTION_URL` | both point at the same process — the monolith |
| `APP_HOST`, `APP_PORT` | where the monolith listens |
| `RUN_PRE_TOKEN_CHECK` | the pre-token risk gate; `1` is safe in the demo |
| `RUN_LOGIN_EVENT_DELIVERY` | Core → Detection login-event delivery |
| `E2E_ALLOW_WRITE_TO` | the write DECLARATION for the E2E fixtures and the probe. Its value is a space-separated list of database NAMES. It is not part of the stack's own configuration — it belongs to the RUN, and it is what the hardened guard (`scripts/e2e_fixtures_guard.py`) checks before it opens a connection |
| `ML_MODEL_PATH` | stays **empty**; see below |

### The frontend

| Variable | Meaning |
|---|---|
| `VITE_DEV_PORT` | the port of the dev server |
| `VITE_ORIGIN` | the origin the dev server serves |
| `DEMO_API_MODE` | `proxy` (default) or `direct` |
| `CORS_ALLOWED_ORIGINS` | only needed in `direct` mode; a wildcard is refused |

The demo uses the **proxy mode** by default: the browser makes a
same-origin request and Vite proxies `/api` to the API. It is the mode
the repository documents as recommended, it needs no CORS
configuration, and it survives a change of the API port without touching
the frontend. Set `DEMO_API_MODE=direct` to exercise the cross-origin
path instead.

### The security

| Variable | Meaning |
|---|---|
| `INTERNAL_SECRET` | the shared secret of the internal boundary; at least 32 characters |
| `FORWARDED_ALLOW_IPS` | the trusted proxy list; a wildcard is forbidden |

---

## 9. The honest states of the demo

Two parts of the system are deliberately **not** faked.

### The ML model is not loaded

`ML_MODEL_PATH` is empty. The registry holds a staged placeholder with no
file behind it, the scoring endpoint answers `503`, and the Detection
engine falls back to its rule-only score. The dashboard reports the
model status as an error rather than claiming a production model.

This is the honest state: a deployment that has no artifact must say so.

### The rule-only fallback is visible

The seeded `medium_open_ruleless` alert has no ML score at all — the ML
engine produced nothing, so the score came from the rules alone. The
frontend must show "no data" for the ML score there, never a zero.

---

## 10. Running the demo from a CLEAN CLONE

This section is the whole handover: everything a second team member has
to do, in order, on a machine that has never seen the project.

### 10.1 Which branch or commit to take

While PR #21 and PR #22 are both open, the two branches have to be
taken **in order** — PR #22 is stacked on PR #21, so it does not contain
the demo foundation.

| What you want | What you take |
|---|---|
| the **demo foundation only** | `feature/m13-demo-foundation` (PR #21, head `dd352791807bcd1b9586220269d6b369b24840a3`) |
| the **complete M13**, which is what the demo and the browser E2E need | `feature/m13-browser-e2e` (PR #22, head `7ec6409ed5420451328b82a9a093fc3ec8fe4e42`) |
| the exact state the acceptance matrix reports | commit `7ec6409ed5420451328b82a9a093fc3ec8fe4e42` |

`feature/m13-browser-e2e` already contains everything
`feature/m13-demo-foundation` has — its merge-base with that branch IS
its head — so **taking PR #22's branch alone is enough** for a demo.

```bash
git clone https://github.com/Albert-Tuan/sentinel-auth.git
cd sentinel-auth
git checkout feature/m13-browser-e2e
git log --oneline -1          # expect 7ec6409
```

To reproduce the figures of the acceptance matrix exactly, check the
commit out rather than the branch tip:

```bash
git checkout 7ec6409ed5420451328b82a9a093fc3ec8fe4e42
```

### 10.2 The dependencies that were verified

| Dependency | Verified version | Notes |
|---|---|---|
| Python | 3.11 and 3.12 | CI runs the backend suite on BOTH |
| Node.js | 20 and 24 | CI runs the frontend on 24; the repository's `engines` allows 18+ |
| PostgreSQL | 16 | the compose overlay; `postgres:16-alpine` is the CI image |
| Redis | 7 | the compose overlay |
| SQLAlchemy | `>=2.0.0,<2.1.0` | **pinned on purpose** — see defect 20 in the matrix |
| psycopg2 | from `requirements.txt` | the driver the CI URLs spell explicitly |
| Docker or Podman | any recent | rootless is supported |

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt

cd frontend && npm ci && cd ..
```

The browser suite needs Chromium as well:

```bash
cd frontend && npx playwright install chromium && cd ..
```

### 10.3 The environment file

```bash
cp .env.demo.example .env.demo
```

Then generate **your own** secrets — never reuse a value from another
machine, and never commit the file:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"   # INTERNAL_SECRET
python3 -c "import secrets; print(secrets.token_urlsafe(16))"   # POSTGRES_PASSWORD
```

`.env.demo` is gitignored; `.env.demo.example` holds placeholders only.
The stack refuses to start if `INTERNAL_SECRET` is shorter than 32
characters or still holds the placeholder.

### 10.4 The whole sequence

```bash
# 1. bring the stack up (PostgreSQL, Redis, the SMTP sink, the API, Vite)
bash scripts/demo_stack.sh start
bash scripts/demo_stack.sh status

# 2. seed the fixtures into the demo databases
python scripts/demo_seed_demo.py --seed --manifest-out .ci/demo/fixture-manifest.json

# 3. the six demonstration scenarios
python scripts/demo_scenarios.py --all

# 4. the pre-token detection gate, on the real stack
#
# The probe WRITES: it seeds a risky history, it activates the demo
# policy and it makes two real logins.  The hardened guard therefore
# refuses to run unless the run DECLARES the exact databases it may
# write to.  The declaration names them BY NAME — a generic "true"
# authorises nothing.
#
#   E2E_ALLOW_WRITE_TO="sentinel_core_demo sentinel_detection_demo"
#
export E2E_ALLOW_WRITE_TO="sentinel_core_demo sentinel_detection_demo"
python scripts/demo_pre_token_probe.py
unset E2E_ALLOW_WRITE_TO

# 5. the browser acceptance suite
bash scripts/e2e_run.sh

# 6. the deployment verification (needs Docker)
python scripts/deploy_verify.py
```

The scripts are invoked through `bash` and `python` because the
repository does not track the executable bit on every file.

### 10.5 Stopping, restarting, and the destructive reset

| Command | Effect | Data |
|---|---|---|
| `bash scripts/demo_stack.sh stop` | stops every process | **kept** |
| `bash scripts/demo_stack.sh restart` | stops and starts again | **kept** — the row counts must be identical before and after |
| `bash scripts/demo_stack.sh status` | shows what runs and the real database state | — |
| `bash scripts/demo_stack.sh reset` | **destroys the demo volumes** | **lost** |

`reset` is the ONLY destructive command, and it asks for a typed
confirmation first:

```
This script DROPS and RECREATES the following databases:
  - sentinel_core_demo
  - sentinel_detection_demo
  - sentinel_ml_demo

Type the three names above, separated by spaces, to proceed:
```

Use it only when the demo's state has drifted and a fresh start is
wanted. It never touches the canonical deployment's `.env`, its ports
or its databases — the demo has its own.

### 10.6 The failure modes that were actually hit

These are the failures that cost time during the M13.2 work. Each one
has a symptom you can recognise and a fix that does not weaken the
protection.

| Symptom | Cause | Fix |
|---|---|---|
| the shell's `INTERNAL_SECRET` differs from the one in `.env.demo`, and the internal boundary answers `401` | an exported variable shadows the file | `scripts/demo_stack.sh` sources `.env.demo` with `set -a`, so the file wins **for the stack**. A script you run BY HAND reads the shell first — run it with the file's values, or `set -a; . ./.env.demo; set +a` before it |
| "No captured OTP found for … in …" | the SMTP sink is not on the port the API sends to, or writes to another file | the port and the log path must agree with `MFA_SMTP_PORT` / `MFA_SMTP_LOG`. `scripts/demo_stack.sh` writes the absolute path into `.ci/demo/otp-log.path`; the API and the reader must both use it |
| the scenario reports "the one-time MFA gate could not be changed" | `CORE_DATABASE_URL` is not exported into the scenario's shell | `set -a; . ./.env.demo; set +a` first |
| the scenario finds no alerts | the fixtures were not seeded into the DETECTION database | `python scripts/demo_seed_demo.py --seed` — the seed writes to all three databases |
| the login answers `429 Too many requests` | the login rate limit is 5 per minute and per IP; the accumulated login attempts of earlier runs fill the window | wait for the window to reopen. `scripts/demo_scenarios.py` retries by itself; a hand-written script has to |
| the login answers `mfa_required: true` for an account that is NOT `demo_admin` | the DETECTION engine scored the login as risky and the pre-token gate held the token — this is the CORRECT behaviour, not a misconfiguration | see section 9. To get a clean run, re-seed the fixtures: `python scripts/demo_seed_demo.py --seed` resets the one-time MFA flag |
| the alerts are seeded but the pipeline does not run | the seeded alerts are for the INTERFACE. A pipeline claim needs a REAL login event | run `python scripts/demo_pre_token_probe.py` — it makes a real risky login and shows the Detection verdict |
| a test answers `401` right after a successful login | the shell is talking to a DIFFERENT backend than the one that issued the token | check the port: the demo API is `58000`, and `M12_API_ORIGIN` / `M12_API_ROOT` must AGREE with each other and with the backend that is actually running |
| `psycopg2.errors.OperationalError: ... connection refused` | the shell's `CORE_DATABASE_URL` points at another stack's PostgreSQL | the demo's PostgreSQL is on `55432`; the canonical deployment uses a different port |
| the run is green but the demo shows old data | the fixtures were seeded before the scenario that changed them | `python scripts/demo_seed_demo.py --seed` is idempotent and re-arms the one-time MFA flag |
| the pre-token probe exits with "the probe refuses to run against this target — [permission]" | the run has not declared that it may write. The guard reads the declaration from `E2E_ALLOW_WRITE_TO`, and the value must NAME the exact databases | `export E2E_ALLOW_WRITE_TO="sentinel_core_demo sentinel_detection_demo"`. A generic `"true"` authorises nothing — see section 10.4 |
| the pre-token probe exits with "the probe refuses to run against this target — [libpq]" | a libpq variable in the shell (`PGHOSTADDR`, `PGSERVICE`, `PGDATABASE`, ...) could move the destination of a connection the guard approved | `unset PGHOSTADDR PGSERVICE PGSERVICEFILE PGHOST PGPORT PGDATABASE PGUSER` before the run. The probe shows the guard the REAL libpq environment on purpose — hiding it would hide it from the driver too |
| the pre-token probe reports `token=ISSUED` for the gated run, while a manual risky login is held | the policy in service is not the demo's own. Only ONE policy may be active, and the browser scenario E2E-05 activates one of its own, which deactivates the demo's | the probe puts the demo policy back in service by itself and restores the previous one afterwards. If you run the scoring by hand, check `SELECT version FROM policies WHERE is_active IS TRUE` |
| the pre-token probe reports `token=ISSUED` for the gated run, and the policy is the demo's own | the login address is not NEW. `impossible_travel` measures the NOVELTY of the address — `1 - (attempts from this IP) / (attempts in the last 7 days)` — so an address the account has used before scores below the threshold | the probe picks a fresh address out of the account's own history and prints it: `the login under test comes from 203.0.113.19 (never used before)`. A different address on every run is the correct behaviour, not a defect |

**Do not work around a failure by disabling the detection.** Turning
`RUN_PRE_TOKEN_CHECK=0` makes the login succeed, and the demo then
shows a system that does not do what it claims to do. The scenarios
that need a quiet login can use an account the policy does not score as
risky.

---

## 11. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `the demo environment file '.env.demo' does not exist` | the file was never created | `cp .env.demo.example .env.demo` and fill in the secrets |
| `INTERNAL_SECRET still holds a placeholder value` | the template was not edited | generate a real secret |
| `port 58000 is already in use` | another process holds the port | stop it, or change `APP_PORT` |
| `the SMTP sink did not start` | the sink could not bind | check `smtp.log` and `MFA_SMTP_PORT` |
| `the API did not become ready` | the monolith failed to boot | check `api.log` |
| `Permission denied` during the PostgreSQL init | a SELinux labelling problem | see section 5; the staging handles it |

---

## 12. Related documents

* [M13-DEMO-FIXTURES.md](M13-DEMO-FIXTURES.md) — the reproducible fixtures
* [M13-DEMO-SCENARIOS.md](M13-DEMO-SCENARIOS.md) — the six demo scenarios
* [M13-ACCEPTANCE-MATRIX.md](M13-ACCEPTANCE-MATRIX.md) — the acceptance matrix
* [DEPLOYMENT-v3.3.md](DEPLOYMENT-v3.3.md) — the canonical deployment
* [INFRASTRUCTURE-v3.3.md](INFRASTRUCTURE-v3.3.md) — the infrastructure
