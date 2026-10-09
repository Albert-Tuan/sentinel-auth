# Sentinel Auth v3.3 — Infrastructure Baseline Verification

> **Date:** 2026-10-09 (correction pass)
> **Baseline:** `ced4178379cbf0ffe28619d777e20c18bd4ed711`
> **Status:** INFRA_STATIC_VERIFIED_RUNTIME_PENDING

This document records infrastructure baseline verification. Static validation was
performed. Runtime verification requires Docker daemon access.

---

## 1. Static Validation (Completed)

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

## 2. Runtime Verification (Requires Docker Daemon)

The following require a running Docker daemon. Commands are documented for
manual execution.

### 2.1 Bring Up Infrastructure (Isolated Project)

Use an isolated compose project name and temporary ports to avoid conflicts
with any existing local PostgreSQL/Redis:

```bash
POSTGRES_PORT=55432 REDIS_PORT=56379 \
docker compose -p sentinel_auth_infra_test up -d
```

**Why isolated project?** Without explicit volume names, each compose project
gets its own named volume (`sentinel_auth_infra_test_postgres_data`). This
prevents `sentinel_auth_infra_test down -v` from affecting the main
`sentinel-auth` project's data.

**Why temporary ports?** If port 5432 or 6379 is already in use on the
developer machine, temporary ports avoid conflicts.

### 2.2 Health Check

```bash
$ docker compose -p sentinel_auth_infra_test ps
```

**Expected:**
```
NAME      IMAGE             STATUS      PORTS
postgres  postgres:16-alpine  Up (healthy)  127.0.0.1:55432->5432/tcp
redis     redis:7-alpine     Up (healthy)  127.0.0.1:56379->6379/tcp
```

Both services must report `healthy`.

### 2.3 Redis PING

```bash
$ docker compose -p sentinel_auth_infra_test exec redis redis-cli PING
```

**Expected:** `PONG`

### 2.4 Verify AOF Persistence

```bash
$ docker compose -p sentinel_auth_infra_test exec redis redis-cli CONFIG GET appendonly
```

**Expected:** `appendonly yes`

---

## 3. Database Verification

### 3.1 List Databases

```bash
$ docker compose -p sentinel_auth_infra_test exec postgres \
    psql -U sentinel -d postgres -c "\l"
```

**Expected:** `sentinel_core`, `sentinel_detection`, `sentinel_ml` all present.

### 3.2 Base Table Counts (Not Views)

Use `table_type = 'BASE TABLE'` to exclude views.

#### sentinel_core (expected 13)

```bash
$ docker compose -p sentinel_auth_infra_test exec postgres \
    psql -U sentinel -d sentinel_core -c \
    "SELECT count(*) FROM information_schema.tables \
     WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"
```

**Expected:** `13`

#### sentinel_detection (expected 7)

```bash
$ docker compose -p sentinel_auth_infra_test exec postgres \
    psql -U sentinel -d sentinel_detection -c \
    "SELECT count(*) FROM information_schema.tables \
     WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"
```

**Expected:** `7`

#### sentinel_ml (expected 3)

```bash
$ docker compose -p sentinel_auth_infra_test exec postgres \
    psql -U sentinel -d sentinel_ml -c \
    "SELECT count(*) FROM information_schema.tables \
     WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"
```

**Expected:** `3`

### 3.3 Views in sentinel_ml

```bash
$ docker compose -p sentinel_auth_infra_test exec postgres \
    psql -U sentinel -d sentinel_ml -c \
    "SELECT viewname FROM information_schema.views WHERE table_schema = 'public'"
```

**Expected:** `local_ml_stats`

Note: `manager_dashboard` referenced in `schema-ml-service-v3.3.sql` is a
commented-out conceptual reference — not a real view. Do not count it.

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

**Expected:** `0`

### 4.2 sentinel_detection does NOT contain core tables

```bash
$ docker compose -p sentinel_auth_infra_test exec postgres \
    psql -U sentinel -d sentinel_detection -c \
    "SELECT count(*) FROM information_schema.tables \
     WHERE table_schema = 'public' \
       AND table_type = 'BASE TABLE' \
       AND table_name = 'users'"
```

**Expected:** `0`

### 4.3 sentinel_ml does NOT contain core/detection tables

```bash
$ docker compose -p sentinel_auth_infra_test exec postgres \
    psql -U sentinel -d sentinel_ml -c \
    "SELECT count(*) FROM information_schema.tables \
     WHERE table_schema = 'public' \
       AND table_type = 'BASE TABLE' \
       AND table_name IN ('users', 'sessions', 'policies')"
```

**Expected:** `0`

---

## 5. Init Script Summary

The init script (`00-init-databases.sh`) reports counts at completion:

```
[init] sentinel_core:       13 base tables (expected 13)
[init] sentinel_detection:  7 base tables (expected 7)
[init] sentinel_ml:        3 base tables (expected 3)
[init] sentinel_ml views:  1 (expected 1 — local_ml_stats)
[init] All three databases initialized successfully
```

---

## 6. Safe Cleanup

```bash
$ docker compose -p sentinel_auth_infra_test down -v
```

**Why is this safe?**

With explicit `name:` removed from compose volumes, the isolated test project
gets its own named volumes:
- `sentinel_auth_infra_test_postgres_data`
- `sentinel_auth_infra_test_redis_data`

`docker compose -p sentinel_auth_infra_test down -v` only removes those
specific volumes. It does NOT affect `sentinel-auth_postgres_data` (the main
project's volume) or any other Docker project.

---

## 7. Files Verified (Static)

| File | Check | Result |
|------|-------|--------|
| `docker-compose.yml` | `docker compose config` | ✅ PASS |
| `infra/postgres/init/00-init-databases.sh` | `bash -n` | ✅ PASS |
| `.env.example` | Static review | ✅ PASS |
| `docs/DECISIONS-SYSTEM-v3.3.md` | Static review | ✅ PASS |
| `docs/INFRASTRUCTURE-v3.3.md` | Static review | ✅ PASS |
| `Dockerfile` | Static review | ✅ PASS (schema references corrected) |
| `docs/audit/15-docs-infra-baseline-audit.md` | Updated | ✅ PASS |

---

**Status:** INFRA_STATIC_VERIFIED_RUNTIME_PENDING
