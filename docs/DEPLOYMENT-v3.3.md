# Sentinel Auth v3.3 — Reproducible Deployment

> **Status:** APPROVED (M11.2), updated for M11.3 (Security Hardening)
> **Version:** 1.1
> **Date:** 2026-11-06
> **Baseline:** `origin/dev` @ `6c606bf` (after M11.1 PR #13)
> **M11.3 changes:** the CORS allow-list and the dependency-aware `/ready`
> probe. See Section 8 and `.env.example`.

This document describes the **reproducible local/demo deployment** of
Sentinel Auth v3.3: how to bring the whole system up from a clean clone
with one command, how to verify it, and how to tear it down safely.

It complements [`INFRASTRUCTURE-v3.3.md`](INFRASTRUCTURE-v3.3.md), which
describes the topology and the schema files. This document describes the
**operated** deployment.

---

## 1. What the deployment is

| Component | What it is | Where it runs |
|-----------|-----------|---------------|
| PostgreSQL 16 | One server, **three logical databases** | Docker container |
| Redis 7 | Prepared infrastructure, **not used at runtime** | Docker container |
| FastAPI monolith | One process serving Core, Detection and ML | Host process |

The three logical databases:

| Database | Schema file | Tables | Owner |
|----------|-------------|--------|-------|
| `sentinel_core` | `schema-core-v3.3.sql` | 13 | Core/Auth |
| `sentinel_detection` | `schema-detection-v3.3.sql` | 7 | Detection Engine |
| `sentinel_ml` | `schema-ml-service-v3.3.sql` | 3 + 1 view | ML Service |

The application **never creates tables at runtime**. The bootstrap is owned
by `infra/postgres/init/00-init-databases.sh`, which applies the canonical
schema files to their own database.

### Why the application is not containerised

The compose file starts **infrastructure only**; the FastAPI monolith runs
on the host. This is deliberate:

* the monolith is the thing under test, and running it on the host means
  the verification scripts exercise the same code path a developer uses;
* containerising the app would require pinning the Python dependency set
  into an image, which duplicates the CI's own dependency contract;
* the demo deployment does not need a second isolation boundary - it binds
  to `127.0.0.1` and nothing else is reachable.

A `Dockerfile` already exists for a containerised variant. It is **not** used
by this deployment.

---

## 2. Prerequisites

| Requirement | Version | Why |
|-------------|---------|-----|
| Docker Engine | ≥ 24.0 | The infrastructure containers |
| Docker Compose plugin | v2 (`docker compose`) | The compose file |
| Python | 3.11 or 3.12 | The FastAPI monolith |
| `curl` | any | The readiness probe |

The Python dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

> **Podman works too.** Set `COMPOSE_CMD="podman compose"` if you use it.
> The compose file contains no Docker-specific constructs.
>
> The deployment has been validated against **Docker Engine 29.9.3** (API
> 1.56, `fuse-overlayfs`, rootless) with **Docker Compose v5.4.0**, and
> against a rootless **Podman 5.8.9** daemon. Both ran the full stack:
> a from-scratch rebuild, all 62 deployment checks, the 1035-test
> PostgreSQL regression suite and the 79-check HTTP smoke. See
> [Compatibility](#compatibility).

---

## 3. Quick start

```bash
git clone <repository-url>
cd sentinel-auth

# 1. Create the environment file and give it a real secret.
cp .env.example .env
python3 -c "import secrets; print(secrets.token_urlsafe(32))"   # paste into INTERNAL_SECRET

# 2. Bring the deployment up.
bash scripts/deploy_local.sh up
```

`up` performs, in order:

1. **configuration validation** - it refuses to start on a misconfigured
   deployment (see section 6);
2. **infrastructure start** - `docker compose up -d`;
3. **readiness wait** - PostgreSQL accepts connections;
4. **topology verification** - the three databases exist, hold the
   canonical schema, and own no table from another context;
5. **application start** - the FastAPI monolith;
6. **readiness wait** - `/ready` answers.

Then:

```bash
bash scripts/deploy_local.sh verify    # the deployment checks (section 8)
```

### The commands

| Command | What it does |
|---------|--------------|
| `scripts/deploy_local.sh up` | Validate, start, verify the topology, wait for readiness |
| `scripts/deploy_local.sh status` | Show what is running |
| `scripts/deploy_local.sh verify` | Run the deployment checks against the running deployment |
| `scripts/deploy_local.sh down` | Stop the app and the infrastructure — **the volume is kept** |
| `scripts/deploy_local.sh reset` | Stop and **destroy the volume** — asks for a typed confirmation first |
| `scripts/deploy_local.sh logs` | Tail the application log |

The application log is at `.ci/deploy-app.log`.

---

## 4. Environment variables

`scripts/deploy_local.sh` reads `.env`. Values already present in the shell
environment win, so a single variable can be overridden without editing the
file.

### Required

| Variable | Example | Notes |
|----------|---------|-------|
| `POSTGRES_USER` | `sentinel` | The server's superuser |
| `POSTGRES_PASSWORD` | *(generate)* | Must be non-empty; `trust` auth is never used |
| `CORE_DB` / `DETECTION_DB` / `ML_DB` | `sentinel_core`, … | The database names the init script creates |
| `CORE_DATABASE_URL` | `postgresql://sentinel:…@localhost:5432/sentinel_core` | Must match the user, password and database name above |
| `DETECTION_DATABASE_URL` | … | Same rules, for `sentinel_detection` |
| `ML_DATABASE_URL` | … | Same rules, for `sentinel_ml` |
| `INTERNAL_SECRET` | *(generate)* | At least 32 characters; the placeholder is rejected |
| `CORE_APP_URL` | `http://localhost:8000` | The monolith's own address |
| `DETECTION_URL` | `http://localhost:8000` | The monolith's own address |

### Optional

| Variable | Default | Notes |
|----------|---------|-------|
| `APP_HOST` | `127.0.0.1` | The address the monolith binds to |
| `APP_PORT` | `8000` | The port the monolith binds to |
| `POSTGRES_PORT` | `5432` | The **host** port for PostgreSQL |
| `REDIS_PORT` | `6379` | The host port for Redis |
| `REDIS_URL` | `redis://localhost:6379/0` | Prepared, not used at runtime |
| `ML_MODEL_PATH` | *(empty)* | An optional trained artifact; see section 7 |
| `RUN_PRE_TOKEN_CHECK` | `0` | The pre-token risk gate |
| `RUN_LOGIN_EVENT_DELIVERY` | `1` | Core → Detection event delivery |
| `FORWARDED_ALLOW_IPS` | `127.0.0.1` | `*` is forbidden |
| `APP_ENV` | `development` | |

### Generating the secrets

```bash
# The internal shared secret
python3 -c "import secrets; print(secrets.token_urlsafe(32))"

# The PostgreSQL password
python3 -c "import secrets; print(secrets.token_urlsafe(16))"
```

Both must be written into `.env`, which is **gitignored**. `.env.example`
contains placeholders only and is tracked.

---

## 5. Database bootstrap

The three databases are created by the init script
`infra/postgres/init/00-init-databases.sh`, which the compose file mounts
into `/docker-entrypoint-initdb.d`. It runs **once**, when the volume is
first created.

The script:

1. creates `sentinel_core`, `sentinel_detection` and `sentinel_ml` if they
   do not exist;
2. loads the matching canonical schema file into each database with
   `ON_ERROR_STOP=1`, so a failure aborts the whole bootstrap;
3. prints the table counts and warns if they do not match the expected
   13 / 7 / 3 + 1 view.

To rebuild the databases from the canonical schemas:

```bash
bash scripts/deploy_local.sh reset    # destroys the volume, asks first
bash scripts/deploy_local.sh up       # rebuilds it
```

> **The init script only runs on a fresh volume.** Editing a schema file
> does not change an existing database. Use `reset`, or apply the schema
> manually.

### No automatic data loss

* The application never calls `create_all` at startup — that would put all
  23 tables into one database and destroy the topology.
* `docker compose down` keeps the volume.
* Only `scripts/deploy_local.sh reset` destroys it, and it requires the
  typed word `reset`.
* The verification scripts never drop a database or reload a schema.

### Which command may destroy data

Only one command in the whole deployment can destroy persistent data, and
it is a separate, explicit, confirmed subcommand:

| Command | Destroys the volume? | Destroys rows? |
|---------|----------------------|----------------|
| `up` | No | No |
| `verify` | No | No — it creates a few probe rows and reads everything else |
| `status` | No | No |
| `logs` | No | No |
| `down` | No — the volume is kept | No |
| `reset` | **Yes**, after a typed `reset` confirmation | Yes |

The deployment verification **proves** this rather than asserting it: it
parses `scripts/deploy_local.sh`, extracts the body of each subcommand
function, and fails if any of `up`, `verify`, `status`, `logs` or `down`
contains a volume-destroying command. It also parses
`scripts/deploy_verify.py` with the AST and fails if any SQL statement the
script actually executes is a `DROP`, a `TRUNCATE` or a `DELETE`, and it
parses `app/main.py` to confirm no `create_all` call exists.

The `reset` command prints what it is about to do and asks for the word
`reset`; any other answer aborts with **nothing destroyed**:

```text
[deploy] RESET destroys the PostgreSQL volume: every row in all three databases is deleted.
[deploy] This cannot be undone.
Type "reset" to continue: [deploy] aborted - nothing was destroyed
```

---

## 6. Configuration validation

`up` and `verify` refuse to run against a misconfigured deployment. The
checks are:

| Check | Why it matters |
|-------|----------------|
| Every required variable is set | A missing URL fails later with a confusing "relation does not exist" |
| `INTERNAL_SECRET` ≥ 32 characters and not a placeholder | The application refuses to start otherwise |
| The three URLs resolve to **three different** databases | Pointing two contexts at one database puts one context's tables in another context's schema |
| The URL credentials match `POSTGRES_USER`/`POSTGRES_PASSWORD` | Otherwise the application cannot connect at all |
| `CORE_APP_URL` and `DETECTION_URL` point at the same server, on the application's port | The monolith serves Core, Detection and ML from **one** process. Leaving the split-service defaults (8000/8001) in place would send every login event and every analytics fetch to a port where nothing listens, and the Manager facade would report a false "degraded" state |
| `FORWARDED_ALLOW_IPS != "*"` | A wildcard would let any client forge `X-Forwarded-For` |
| `ML_MODEL_PATH`, if set, exists | A dangling path would fail at inference time, not at startup |

The validation is **read-only**: it inspects the configuration and the
running databases, and changes nothing.

---

## 7. The ML artifact

The canonical schema seeds **one** row in `model_versions`:

| Field | Value |
|-------|-------|
| `name` | `Isolation Forest v1.0` |
| `version` | `v1.0-isolation-forest` |
| `status` | `staged` |
| `is_production` | `FALSE` |
| `model_path` | `/models/isolation-forest-v1.0.joblib` |

That file **does not exist** in a demo deployment. The consequences are
deliberate and observable:

* `GET /api/v1/internal/ml/health` answers
  `{"status": "degraded", "model_version": null, "model_status": "error"}` —
  the artifact state is reported, not hidden;
* `POST /api/v1/internal/ml/score` answers **503** `ML model unavailable`;
* the Detection engine falls back to its rule-only score path.

### A missing artifact is NOT an unavailable database

The two failures are distinct, and the deployment verification proves the
distinction:

| Failure | What the ML endpoint answers | What it means |
|---------|-----------------------------|---------------|
| **Missing artifact** | 503 `ML model unavailable`, `model_status: "error"`, `model_version: null` | The ML database answered the registry query. Only the file is missing. |
| **Unavailable ML database** | The endpoint cannot reach the database at all | The ML context's own store is down. |

The proof is in the data: the scoring endpoint writes an `inference_logs`
row with `model_status = 'error'` **even when it fails**, because the
failure happens *after* the database accepted the write. So:

* a 503 **plus** a new `inference_logs` row with `model_status = 'error'`
  ⇒ the ML database was reachable; the artifact was missing;
* a 503 with **no** such row ⇒ the ML database itself is the problem.

The verification checks both signals explicitly.

**Nothing is auto-promoted.** The registry entry stays `staged` until an
operator changes it. To use a real artifact, you must do both:

1. put the trained bundle on disk;
2. register it in `model_versions` with `status = 'active'` and
   `is_production = TRUE`;
3. optionally point `ML_MODEL_PATH` at it (this alone does **not** change
   which model the registry serves — the registry wins when it has an
   active production entry).

Training is deliberately disabled in `scripts/train_model.py`: the model
must come from the reviewed Kaggle RBA notebook, not from a synthetic
split.

---

## 8. Health, readiness and degradation

The three states are distinct:

| Endpoint | Meaning | Depends on a dependency? |
|----------|---------|--------------------------|
| `GET /health` | **Liveness** — the process is running | No |
| `GET /ready` | **Readiness** — the deployment can serve traffic | Yes — the three databases (read-only) |
| The Manager facade's `sources` map | **Dependency state** — which upstream answered | Yes, per source |

> **`/ready` is dependency-aware (changed in M11.3, Security Hardening).**
> It probes the minimum dependencies the monolith needs — the Core,
> Detection and ML databases — with a bounded, read-only `SELECT 1` per
> context. It writes no rows and runs no inference.
>
> | Situation | Answer |
> |-----------|--------|
> | All three databases reachable | `200` `{"status": "ready", "checks": {...}}` |
> | A database is unreachable | `503` `{"status": "not_ready", "checks": {...}}` |
> | The ML **artifact** file is missing (the database answered) | `200`, `status: "ready"`, `checks.ml_artifact.status: "degraded"` |
> | The ML **registry** could not be queried (timeout, locked table) | `503`, `status: "not_ready"`, `checks.ml_artifact.status: "unavailable"` |
>
> A missing ML *artifact* is deliberately **not** a readiness failure: the
> Detection Engine falls back to a rule-only score, so the service can
> still serve traffic. A missing *database* is, because the requests that
> need that context cannot be answered.
>
> An **unverifiable** artifact state is also a readiness failure. The
> registry query reads the `model_versions` table, so a transaction
> holding a lock on it blocks the query while `SELECT 1` keeps
> answering. When the registry could not be queried, the artifact state is
> unknown — and readiness is **fail-closed**: the probe answers `503`
> rather than assuming the artifact is merely missing.
>
> The registry query shares the probe's deadline: it is skipped entirely
> when the deadline has already been spent, and it runs under a
> server-side `statement_timeout` derived from the remaining budget.
>
> A successful probe is cached for 2 seconds so a tight health-check
> interval does not hammer PostgreSQL. A **failing** probe is never
> cached, so a recovery is reported immediately.
>
> The probe is **bounded**: every engine carries a driver-level
> `connect_timeout` (2 s) and the probe statement runs under a server-side
> `statement_timeout` derived from the remaining budget. A database host
> that drops the packets — rather than refusing them — used to hang the
> probe for more than 60 seconds; it now answers within the budget with
> `status: "not_ready"`.
>
> The probe runs in a **worker thread**, so the database wait never holds
> the event loop: while the probe waits, the service keeps serving its
> other requests.
>
> `/health` stays strictly a liveness probe: it consults no dependency at
> all, so a database outage never makes an orchestrator restart a healthy
> process.

The deployment check suite complements the probe with the checks that
cannot live inside a liveness/readiness pair:

| Check | What it establishes |
|-------|--------------------|
| 1 | All three databases answer and hold the canonical schema |
| 3 | `/health` and `/ready` carry the agreed semantics, the probe writes nothing, and the dependency-aware check reaches the Core database directly |
| 5 | Detection and ML answer over the in-process HTTP hop |
| 6 | The Manager facade reads from all three sources |
| 7 | A dead dependency degrades instead of failing |

A dead upstream is a **degraded source**, not a dead process. The Manager
facade answers **200** with `degraded: true` and names the unreachable
sources:

```json
{
  "degraded": true,
  "sources": {
    "core":      {"status": "unavailable", "detail": "unreachable"},
    "detection": {"status": "unavailable", "detail": "unreachable"},
    "ml":        {"status": "ok", "detail": null}
  }
}
```

The reason codes are a closed vocabulary: `not_configured`, `timeout`,
`unreachable`, `invalid_payload`, `database_error`, `internal_error`, and
`http_<code>`.

Only when **every** source is unusable does the facade answer **503** with
`"detail": "analytics sources unavailable"`.

---

## 9. Verification

```bash
bash scripts/deploy_local.sh verify
```

The checks, in order:

| # | Check |
|---|-------|
| 1 | The three databases exist, hold the canonical schema, and own no table from another context |
| 2 | The application answers; the OpenAPI schema is served |
| 3 | `/health` and `/ready` carry the agreed semantics — `/health` is a liveness probe, `/ready` probes the three databases read-only, distinguishes a missing ML artifact from an unreachable database, and writes nothing |
| 4 | Core authentication works: register, login, `/auth/me`, and a wrong password is refused |
| 5 | Detection and ML communicate: the ML health endpoint names the artifact state, the internal secret is enforced, a login event is accepted and persisted, and the ML database is proven reachable **independently of the missing artifact** |
| 6 | The Manager facade reads from Core, Detection and ML; all five Manager endpoints answer |
| 7 | An unavailable dependency degrades instead of failing |
| 8 | The data survives a restart |
| 9 | Only `reset` can destroy the volume — proved by parsing every subcommand's body and every executed SQL statement |

### The restart check

Check 8 is a **two-phase** check:

```bash
bash scripts/deploy_local.sh verify   # phase 1: records the probe row's id
bash scripts/deploy_local.sh down
bash scripts/deploy_local.sh up
bash scripts/deploy_local.sh verify   # phase 2: compares the id
```

Phase 2 passes only when the probe row has the **same** id it had before
the restart.

The baseline is tied to the **cluster**, not just to the row. The
verification records the PostgreSQL `system_identifier` — the identity of
the data directory — next to the probe id:

| Situation | What the check does |
|-----------|---------------------|
| Same cluster, the row kept its id | **PASS** — the data survived the restart |
| Same cluster, the row has a different id | **FAIL** — real data loss |
| A **different** cluster (the volume was recreated) | The baseline is re-recorded — there was no data to lose |

Without the cluster tie, a baseline file left behind by another cluster
(a different daemon, a recreated volume) would make the check compare two
unrelated probe identities and report a data loss that never happened.

### Rate limiting

The application rate-limits logins to **5 attempts per IP per 5 minutes**.
The verification logs in twice (once for the Core check, once for the
Manager session), so repeated runs inside the window can hit the limit. The
check reports that as what it is — the protective behaviour working — and
tells you to wait for the window. It is **not** a deployment failure.

### The M11.1 test suite

The deployment does not replace the test suite. To run it against the same
PostgreSQL server:

```bash
export POSTGRES_HOST=127.0.0.1 POSTGRES_PORT=5432 POSTGRES_USER=sentinel
export POSTGRES_PASSWORD=... POSTGRES_DB=sentinel_legacy_test CI_TIMEZONE=UTC
export CORE_DETECTION_TEST_URL="postgresql://sentinel:...@127.0.0.1:5432/sentinel_core_test"
export CORE_ANALYTICS_TEST_URL="$CORE_DETECTION_TEST_URL"
export DETECTION_TEST_URL="postgresql://sentinel:...@127.0.0.1:5432/sentinel_detection_test"
export ML_TEST_URL="postgresql://sentinel:...@127.0.0.1:5432/sentinel_ml_test"

bash scripts/ci_bootstrap_postgres.sh
python scripts/ci_verify_tests.py
```

The bootstrap script only ever touches databases whose name ends in
`_test`, so it can never destroy the deployment's own databases.

---

## 10. Security posture of the demo deployment

| Property | How it is enforced |
|----------|-------------------|
| No `trust` authentication | `POSTGRES_INITDB_ARGS` pins `--auth-host=scram-sha-256 --auth-local=scram-sha-256`; the `trust` lines that `initdb` writes by default are removed |
| Password required | Verified: a passwordless TCP connection is refused with `fe_sendauth: no password supplied` |
| No production secrets in Git | `.env` is gitignored; `.env.example` holds placeholders only |
| No wildcard proxy trust | `FORWARDED_ALLOW_IPS="*"` is rejected at startup by the application and by the deployment script |
| The internal boundary is real | `POST /api/v1/internal/ml/score` answers **401** without the secret |
| Only the needed ports are exposed | Both containers bind to `127.0.0.1` only |
| The application is isolated from the database | The Core context's session dependency is bound to `sentinel_core`; it cannot write into the Detection or ML database |

### `POSTGRES_INITDB_ARGS` only affects NEW volumes

This is the single most important caveat about the authentication
configuration.

`initdb` reads `POSTGRES_INITDB_ARGS` **once**, when it initialises a
fresh data directory. It is not a runtime setting and it is not re-read
when the container restarts.

| Situation | Effect of changing `POSTGRES_INITDB_ARGS` |
|-----------|------------------------------------------|
| The volume does not exist yet | The new value applies — the cluster is initialised with it |
| The volume already exists | **Nothing happens.** The existing `pg_hba.conf` and the existing password hashes keep their old configuration |

Consequences:

* A volume that was created **before** this setting was added still has
  the loopback `trust` lines. Changing the compose file does **not**
  change that server.
* The fix for such a volume is to recreate it:

  ```bash
  bash scripts/deploy_local.sh reset   # destroys the data, asks first
  bash scripts/deploy_local.sh up      # re-initialises with SCRAM
  ```

* To check what a running server actually enforces, ask the server
  itself rather than trusting the configuration file:

  ```bash
  docker compose exec -T postgres psql -U sentinel -d postgres -Atc \
    "SELECT type, address, auth_method FROM pg_hba_file_rules ORDER BY line_number;"
  ```

* The **CI** service container always starts with an empty data
  directory, so `POSTGRES_INITDB_ARGS` always takes effect there. The CI
  verifies the resulting configuration explicitly: it proves the correct
  password is accepted, that a connection without a password is rejected,
  that a connection with a wrong password is rejected, that no `host`
  rule uses `trust`, and that the stored password is a SCRAM verifier.
  The same setting is applied in `.github/workflows/ci.yml`, so the CI
  and the demo deployment enforce the identical authentication policy.

---

## 11. Troubleshooting

### "the database does not exist"

The init script only runs on a fresh volume.

```bash
bash scripts/deploy_local.sh reset && bash scripts/deploy_local.sh up
```

### "permission denied for database"

`POSTGRES_USER` / `POSTGRES_PASSWORD` must match between `.env` and the
connection URLs. The deployment script checks this and reports it.

### "CORE_APP_URL and DETECTION_URL must point at the same server"

The `.env` still carries the split-service defaults (8000 / 8001). This
deployment is a **monolith**: set both to the application's own address.

### "the application did not become ready"

```bash
bash scripts/deploy_local.sh logs
```

The usual causes are a PostgreSQL that is not up yet, or a wrong database
URL.

### "the deployment did not start" / no init script output

Some host filesystems — notably those mounted under `/run/media` on
Fedora/Linux — do not propagate regular-file visibility into containers.
The bind-mounted init script and schema files then appear empty inside the
container. The infrastructure design and the init script are correct; the
host filesystem is the limitation.

**Fix:** run the repository from a native Linux filesystem path, for
example `~/Projects/sentinel-auth`.

Do **not** disable SELinux globally as a workaround.

### The verification reports a rate limit

See section 9. Wait for the five-minute window and re-run.

### The Manager facade reports a degraded source

That is the honest answer: the source did not answer. Check the application
log and the upstream address.

---

## 12. Known limitations of the demo deployment

1. **One process.** Core, Detection and ML share a FastAPI process. The
   database boundary is enforced, the *process* boundary is not. The
   three-service split remains future work.
2. **Redis is prepared, not used.** There is no outbox publisher, no
   Redis Streams consumer and no asynchronous event transport. The Core
   → Detection delivery is a synchronous HTTP call.
3. **No ML model.** The registry holds a staged placeholder with no file
   behind it. The scoring endpoint answers 503 and the Detection engine
   uses its rule-only path. This is the honest state, not a defect.
4. **No TLS.** The application and both databases are bound to loopback.
   A deployment exposed to a network needs a reverse proxy and TLS.
5. **No migration tool.** The schema is applied by the init script on a
   fresh volume. There is no Alembic-style incremental migration, so a
   schema change requires a `reset` (which destroys the data).
6. **The data is disposable.** This is a demo deployment. There is no
   backup, no replication and no point-in-time recovery.
7. **The verification writes rows.** It creates a few probe users and login
   events. It never drops a database or reloads a schema.
8. **`docker compose down` does not wait for the app.** The deployment
   script stops the application first; a bare `docker compose down` leaves
   the application running against a stopped database.

---

## 13. Compatibility

The deployment was exercised against **two** container runtimes.

| Runtime | Version | Result |
|---------|---------|--------|
| **Docker Engine** | 29.9.3 (API 1.56), `fuse-overlayfs`, rootless | 62/62 checks, 1035/1035 tests, 79/79 smoke — **all pass** |
| **Podman** | 5.8.9 (rootless) | 62/62 checks, 1035/1035 tests, 79/79 smoke — **all pass** |

On both runtimes the full lifecycle was run: `reset` (volume destroyed) →
`up` (cluster re-initialised, schemas applied, application started) →
`verify` (62 checks) → `restart` of the PostgreSQL container (volume kept,
data proven to survive) → the full 1035-test regression suite → the 79-check
HTTP smoke.

Docker Compose is the **real Compose v2+ plugin** (`docker compose version`
→ `Docker Compose version v5.4.0`), not a shim: the `services`, named
volumes, `healthcheck` and `depends_on: condition: service_healthy`
constructs the compose file uses are all the upstream implementation.

The compose file contains no Docker-specific constructs, so a Podman
deployment behaves the same. Two differences are worth knowing:

* Podman's rootless networking needs `podman system service` running, and
  `DOCKER_HOST` must point at its socket;
* rootless Podman prints a provider notice on every `compose` call.

---

## 14. Related documents

| Document | Content |
|----------|---------|
| [`INFRASTRUCTURE-v3.3.md`](INFRASTRUCTURE-v3.3.md) | The topology, the schema files, the volumes |
| [`../README.md`](../README.md) | The project overview |
| [`../docs/`](../docs) | The design documents |
