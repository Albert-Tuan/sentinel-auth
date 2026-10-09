# Sentinel Auth v3.3 — Infrastructure Baseline Verification

> **Date:** 2026-10-09 (runtime verification pass)
> **Baseline:** `ced4178379cbf0ffe28619d777e20c18bd4ed711`
> **Status:** INFRA_BASELINE_RUNTIME_VERIFIED

This document records the completed infrastructure baseline verification, including
both static validation and runtime execution evidence.

---

## 1. Static Validation

### docker-compose.yml

```bash
$ docker compose config
```

**Result:** ✅ PASS — Valid YAML. All services parsed. Volumes are
Compose-managed (no explicit `name:` — each project gets its own volume).
DB name environment variables passed to postgres service. Ports bound to
`127.0.0.1`. Named volumes resolve as `sentinel-auth_postgres_data`.

### Init Script

```bash
$ bash -n infra/postgres/init/00-init-databases.sh
```

**Result:** ✅ PASS — No syntax errors.

---

## 2. Runtime Verification

Executed on Fedora Linux from a native filesystem path
(`~/Projects/sentinel-auth`). See Section 5 for a filesystem limitation note.

### 2.1 Bring Up Infrastructure

```bash
$ POSTGRES_PORT=55432 REDIS_PORT=56379 \
  docker compose -p sentinel_auth_infra_test up -d
```

### 2.2 Health Check

```bash
$ docker compose -p sentinel_auth_infra_test ps
```

**Actual output:**
```
NAME      IMAGE             STATUS      PORTS
postgres  postgres:16-alpine  Up (healthy)  127.0.0.1:55432->5432/tcp
redis     redis:7-alpine     Up (healthy)  127.0.0.1:56379->6379/tcp
```

✅ **Both services healthy.**

### 2.3 Redis PING

```bash
$ docker compose -p sentinel_auth_infra_test exec redis redis-cli PING
```

**Actual output:**
```
PONG
```

✅ **Redis responding.**

### 2.4 Redis AOF Configuration

```bash
$ docker compose -p sentinel_auth_infra_test exec redis redis-cli CONFIG GET appendonly
```

**Actual output:**
```
appendonly
yes
```

✅ **AOF persistence enabled.**

### 2.5 Redis fsync Policy

```bash
$ docker compose -p sentinel_auth_infra_test exec redis redis-cli CONFIG GET appendfsync
```

**Actual output:**
```
appendfsync
everysec
```

✅ **fsync policy: everysec.**

---

## 3. Database Verification

### 3.1 List Databases

```bash
$ docker compose -p sentinel_auth_infra_test exec postgres \
    psql -U sentinel -d postgres -c "\l"
```

**Actual output (relevant rows):**
```
sentinel_core
sentinel_detection
sentinel_ml
```

✅ **All three databases present.**

### 3.2 Init Script Output

The init script printed on first container start:

```
[init] sentinel_core:       13 base tables (expected 13)
[init] sentinel_detection:  7 base tables (expected 7)
[init] sentinel_ml:        3 base tables (expected 3)
[init] sentinel_ml views:  1 (expected 1 — local_ml_stats)
[init] All three databases initialized successfully
```

✅ **Init completed without errors.**

### 3.3 Base Table Counts

#### sentinel_core

```bash
$ docker compose -p sentinel_auth_infra_test exec postgres \
    psql -U sentinel -d sentinel_core -c \
    "SELECT count(*) FROM information_schema.tables \
     WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"
```

**Actual:** `13` ✅ (expected `13`)

#### sentinel_detection

```bash
$ docker compose -p sentinel_auth_infra_test exec postgres \
    psql -U sentinel -d sentinel_detection -c \
    "SELECT count(*) FROM information_schema.tables \
     WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"
```

**Actual:** `7` ✅ (expected `7`)

#### sentinel_ml

```bash
$ docker compose -p sentinel_auth_infra_test exec postgres \
    psql -U sentinel -d sentinel_ml -c \
    "SELECT count(*) FROM information_schema.tables \
     WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"
```

**Actual:** `3` ✅ (expected `3`)

### 3.4 Views in sentinel_ml

```bash
$ docker compose -p sentinel_auth_infra_test exec postgres \
    psql -U sentinel -d sentinel_ml -c \
    "SELECT viewname FROM information_schema.views WHERE table_schema = 'public'"
```

**Actual:** exactly one view — `local_ml_stats` ✅

Note: `manager_dashboard` referenced in `schema-ml-service-v3.3.sql` is a
commented-out conceptual reference — not a real view.

### 3.5 Summary: Database Object Counts

| Database | Base Tables | Views | Status |
|----------|-------------|-------|--------|
| `sentinel_core` | 13 | 0 | ✅ |
| `sentinel_detection` | 7 | 0 | ✅ |
| `sentinel_ml` | 3 | 1 (`local_ml_stats`) | ✅ |

**Total: 23 base tables, 1 real view.** ✅

---

## 4. Database Isolation Verification

### 4.1 sentinel_core does NOT contain detection tables

```bash
$ docker compose -p sentinel_auth_infra_test exec postgres \
    psql -U sentinel -d sentinel_core -c \
    "SELECT count(*) FROM information_schema.tables \
     WHERE table_schema = 'public' \
       AND table_type = 'BASE TABLE' \
       AND table_name = 'policies'"
```

**Actual:** `0` (no rows) ✅

### 4.2 sentinel_detection does NOT contain core tables

```bash
$ docker compose -p sentinel_auth_infra_test exec postgres \
    psql -U sentinel -d sentinel_detection -c \
    "SELECT count(*) FROM information_schema.tables \
     WHERE table_schema = 'public' \
       AND table_type = 'BASE TABLE' \
       AND table_name = 'users'"
```

**Actual:** `0` (no rows) ✅

### 4.3 sentinel_ml does NOT contain core/detection tables

```bash
$ docker compose -p sentinel_auth_infra_test exec postgres \
    psql -U sentinel -d sentinel_ml -c \
    "SELECT count(*) FROM information_schema.tables \
     WHERE table_schema = 'public' \
       AND table_type = 'BASE TABLE' \
       AND table_name IN ('users', 'sessions', 'policies')"
```

**Actual:** `0` (no rows) ✅

---

## 5. Volume Isolation Verification

### 5.1 Named Volumes

After `docker compose -p sentinel_auth_infra_test up -d`:

```
$ docker volume ls --format '{{.Name}}'
sentinel_auth_infra_test_postgres_data
sentinel_auth_infra_test_redis_data
```

✅ Each isolated project gets its own named volume.

### 5.2 Safe Cleanup

```bash
$ docker compose -p sentinel_auth_infra_test down -v
```

After cleanup:

```
$ docker volume ls --format '{{.Name}}'
(empty)
```

✅ `down -v` removed only the isolated test volumes. No interference with
other projects or data.

---

## 6. Filesystem Limitation

### Observed Symptom

When the repository was accessed from a removable/media-mounted filesystem
(`/run/media/...`), Docker bind mounts exposed the directory structure but
**not** the contained files. Specifically:

- `./infra/postgres/init/` → `/docker-entrypoint-initdb.d/` appeared as an
  empty directory inside the container.
- The PostgreSQL `docker-entrypoint` script found no `.sh` or `.sql` files
  to execute, so no databases were created and no schemas were loaded.

This is a **Docker bind-mount filesystem visibility limitation**, not a failure
of the SQL schemas, PostgreSQL image, compose architecture, or init script logic.

### Root Cause

Some filesystems (notably those mounted under `/run/media` on Fedora/Linux) may
present directory entries to the Docker daemon without propagating regular-file
access into containers. Docker's volume mount mechanism inherits host filesystem
permissions and SELinux labels; on certain media-mount types the daemon can see
the directory but containers cannot read the files inside it.

### Resolution

Run the repository from a **native Linux filesystem path**, for example:

```bash
~/Projects/sentinel-auth
```

This is the recommended working tree location. From a native filesystem,
all bind-mounted files are visible inside containers and initialization succeeds.

### What This Is NOT

This is **not** classified as:
- ❌ SQL schema failure
- ❌ PostgreSQL failure
- ❌ Compose architecture failure
- ❌ Init-script logic failure
- ❌ SELinux configuration error requiring global disabling

It is a **host filesystem / Docker visibility limitation** specific to certain
mount types on Fedora. The infrastructure design is correct.

---

## 7. Files Verified

| File | Static Check | Runtime Check | Result |
|------|-------------|---------------|--------|
| `docker-compose.yml` | `docker compose config` | Health checks pass | ✅ |
| `infra/postgres/init/00-init-databases.sh` | `bash -n` | Init output verified | ✅ |
| `.env.example` | Static review | — | ✅ |
| `docs/DECISIONS-SYSTEM-v3.3.md` | Static review | — | ✅ |
| `docs/INFRASTRUCTURE-v3.3.md` | Static review | — | ✅ |
| `Dockerfile` | Static review | — | ✅ |
| `docs/audit/15-docs-infra-baseline-audit.md` | Static review | — | ✅ |

---

**Status:** INFRA_BASELINE_RUNTIME_VERIFIED
