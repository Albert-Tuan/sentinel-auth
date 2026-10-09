# Sentinel Auth v3.3 — Infrastructure Baseline Verification

> **Date:** 2026-10-09
> **Baseline:** `1d9bf9f173a2f09761d9d28d26d165c2bf4d147a`

This document records evidence from infrastructure baseline verification.

---

## Static Validation

### docker-compose.yml

```bash
$ docker compose config
```

**Result:** ✅ PASS — Valid YAML. All services parsed correctly. Named volumes
(`sentinel_postgres_data`, `sentinel_redis_data`) confirmed. Schema mount paths verified:
- `./infra/postgres/init` → `/docker-entrypoint-initdb.d` (read-only)
- `./infra/postgres` → `/schemas` (read-only)

### Init Script Shell Syntax

```bash
$ bash -n infra/postgres/init/00-init-databases.sh
```

**Result:** ✅ PASS — No syntax errors.

---

## Runtime Verification (Requires Docker Daemon)

The following commands require a running Docker daemon. They could not be executed in
this verification environment (Docker daemon not accessible from the build host).

### Bring Up Infrastructure

```bash
$ docker compose -p sentinel_auth_infra_test up -d
```

**Expected:** Both `postgres` and `redis` services start.

### Health Check

```bash
$ docker compose -p sentinel_auth_infra_test ps
```

**Expected:**
```
NAME      IMAGE            STATUS      PORTS
postgres  postgres:16-alpine  Up (healthy)  0.0.0.0:5432->5432/tcp
redis    redis:7-alpine     Up (healthy)  0.0.0.0:6379->6379/tcp
```

**Expected:** Both services report `healthy`.

### Redis PING

```bash
$ docker compose -p sentinel_auth_infra_test exec redis redis-cli PING
```

**Expected:**
```
PONG
```

---

## Database Verification (Requires Running PostgreSQL)

### List Databases

```bash
$ docker compose -p sentinel_auth_infra_test exec postgres \
    psql -U sentinel -d postgres -c "\l"
```

**Expected:** `sentinel_core`, `sentinel_detection`, `sentinel_ml` all listed.

### Table Counts

#### sentinel_core

```bash
$ docker compose -p sentinel_auth_infra_test exec postgres \
    psql -U sentinel -d sentinel_core -c \
    "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'"
```

**Expected:** `13`

#### sentinel_detection

```bash
$ docker compose -p sentinel_auth_infra_test exec postgres \
    psql -U sentinel -d sentinel_detection -c \
    "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'"
```

**Expected:** `7`

#### sentinel_ml

```bash
$ docker compose -p sentinel_auth_infra_test exec postgres \
    psql -U sentinel -d sentinel_ml -c \
    "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'"
```

**Expected:** `3`

### Views in sentinel_ml

```bash
$ docker compose -p sentinel_auth_infra_test exec postgres \
    psql -U sentinel -d sentinel_ml -c \
    "SELECT viewname FROM information_schema.views WHERE table_schema = 'public'"
```

**Expected:** `local_ml_stats` (the `manager_dashboard` in the schema file is a
commented-out conceptual reference, not a real view)

### Database Isolation

#### sentinel_core does NOT contain detection tables

```bash
$ docker compose -p sentinel_auth_infra_test exec postgres \
    psql -U sentinel -d sentinel_core -c \
    "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'policies'"
```

**Expected:** `0`

#### sentinel_detection does NOT contain core tables

```bash
$ docker compose -p sentinel_auth_infra_test exec postgres \
    psql -U sentinel -d sentinel_detection -c \
    "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'users'"
```

**Expected:** `0`

#### sentinel_ml does NOT contain core/detection tables

```bash
$ docker compose -p sentinel_auth_infra_test exec postgres \
    psql -U sentinel -d sentinel_ml -c \
    "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public' AND table_name IN ('users', 'sessions', 'policies')"
```

**Expected:** `0`

---

## Redis Verification

### Persistence Check

```bash
$ docker compose -p sentinel_auth_infra_test exec redis redis-cli CONFIG GET appendonly
```

**Expected:** `appendonly yes`

### AOF fsync Policy

```bash
$ docker compose -p sentinel_auth_infra_test exec redis redis-cli CONFIG GET appendfsync
```

**Expected:** `appendfsync everysec`

---

## Clean Shutdown

After verification is complete:

```bash
$ docker compose -p sentinel_auth_infra_test down -v
```

**Expected:** Containers stopped. Named volumes (`sentinel_postgres_data`,
`sentinel_redis_data`) destroyed. No interference with existing developer data.

---

## Files Verified

| File | Check | Result |
|------|-------|--------|
| `docker-compose.yml` | `docker compose config` | ✅ PASS |
| `infra/postgres/init/00-init-databases.sh` | `bash -n` | ✅ PASS |
| `Dockerfile` | Static review | ✅ PASS (schema references fixed) |
| `.env.example` | Static review | ✅ PASS |
| `docs/DECISIONS-SYSTEM-v3.3.md` | Static review | ✅ PASS |
| `docs/INFRASTRUCTURE-v3.3.md` | Static review | ✅ PASS |
| `docs/audit/15-docs-infra-baseline-audit.md` | Updated | ✅ PASS |

---

**Status:** INFRASTRUCTURE BASELINE VERIFIED (static) — runtime verification
requires Docker daemon access.
