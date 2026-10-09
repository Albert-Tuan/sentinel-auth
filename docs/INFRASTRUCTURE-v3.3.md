# Sentinel Auth v3.3 — Local Infrastructure Guide

> **Status:** APPROVED
> **Version:** 1.0
> **Date:** 2026-10-09

This document describes the local development infrastructure for Sentinel Auth v3.3.
It covers Docker-based local setup, database topology, and service dependencies.

---

## 1. Architecture Overview

```
Docker host
│
├── postgres  (PostgreSQL 16)
│   ├── sentinel_core        (13 tables — Core/Auth service)
│   ├── sentinel_detection  (7 tables — Detection Engine)
│   └── sentinel_ml        (3 tables + 1 view — ML Service)
│
└── redis    (Redis 7 — future outbox transport)
```

### Current Implementation Status

| Component | Status | Notes |
|-----------|--------|-------|
| PostgreSQL (3 databases) | ✅ Ready | Bootstrap verified |
| Redis | ✅ Ready | AOF persistence enabled |
| Application (FastAPI monolith) | ⚠️ Monolith | One process; three-service split is future work |
| Three independent services | 🔜 Future | Not implemented in v3.3 baseline |

The **current application** is a single FastAPI process (`uvicorn app.main:app`).
The infrastructure in this document reflects the **target architecture**: three
logical databases on one PostgreSQL server, plus Redis for future outbox transport.

---

## 2. Prerequisites

- Docker Engine ≥ 24.0
- Docker Compose plugin (v2) or `docker-compose`
- Bash 4+ (for the init script)

---

## 3. Quick Start

### 3.1 Start Infrastructure Only

```bash
docker compose up -d
```

Wait for services to become healthy:

```bash
docker compose ps
```

Expected output:
```
NAME        IMAGE         STATUS          PORTS
postgres    postgres:16   Up (healthy)   0.0.0.0:5432->5432/tcp
redis       redis:7      Up (healthy)   0.0.0.0:6379->6379/tcp
```

### 3.2 Verify Databases

```bash
# List all databases
docker compose exec postgres psql -U sentinel -d postgres -c "\l"

# Verify table counts
docker compose exec postgres psql -U sentinel -d sentinel_core -c \
  "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'"

docker compose exec postgres psql -U sentinel -d sentinel_detection -c \
  "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'"

docker compose exec postgres psql -U sentinel -d sentinel_ml -c \
  "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'"

# Verify the real view in sentinel_ml
docker compose exec postgres psql -U sentinel -d sentinel_ml -c \
  "SELECT viewname FROM information_schema.views WHERE table_schema = 'public'"
```

Expected counts:
- `sentinel_core`: **13 tables**
- `sentinel_detection`: **7 tables**
- `sentinel_ml`: **3 tables**, **1 view (`local_ml_stats`)**

### 3.3 Verify Redis

```bash
docker compose exec redis redis-cli PING
```

Expected: `PONG`

### 3.4 Verify Isolation

```bash
# sentinel_core must NOT contain detection tables
docker compose exec postgres psql -U sentinel -d sentinel_core -c \
  "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'policies'"
# Expected: 0 rows

# sentinel_detection must NOT contain core tables
docker compose exec postgres psql -U sentinel -d sentinel_detection -c \
  "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'users'"
# Expected: 0 rows

# sentinel_ml must NOT contain core or detection tables
docker compose exec postgres psql -U sentinel -d sentinel_ml -c \
  "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' AND table_name IN ('users', 'sessions', 'policies')"
# Expected: 0 rows
```

### 3.5 Stop Infrastructure

```bash
docker compose down
```

### 3.6 Full Reset (Destroy Volumes)

```bash
docker compose down -v
```

⚠️ This destroys all data. Run only when you want a clean slate.

---

## 4. Environment Variables

Copy `.env.example` to `.env` and configure:

```bash
cp .env.example .env
```

Key variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `POSTGRES_USER` | `sentinel` | PostgreSQL username |
| `POSTGRES_PASSWORD` | `sentinel123` | PostgreSQL password |
| `POSTGRES_PORT` | `5432` | Local port for PostgreSQL |
| `REDIS_PORT` | `6379` | Local port for Redis |
| `INTERNAL_SECRET` | *(required)* | At least 32 characters |
| `FORWARDED_ALLOW_IPS` | `127.0.0.1` | Trusted proxy IPs |

**Never commit `.env` to git.** It is gitignored.

---

## 5. Database Details

### 5.1 Three Logical Databases

PostgreSQL runs as a **single container** but creates **three logical databases**:

| Database | Schema File | Tables | Service Owner |
|----------|-------------|--------|--------------|
| `sentinel_core` | `schema-core-v3.3.sql` | 13 | Core/Auth |
| `sentinel_detection` | `schema-detection-v3.3.sql` | 7 | Detection Engine |
| `sentinel_ml` | `schema-ml-service-v3.3.sql` | 3 + 1 view | ML Service |

### 5.2 Bootstrap

Databases are initialized automatically on first run via the
`infra/postgres/init/00-init-databases.sh` script mounted into
`/docker-entrypoint-initdb.d/`. This script:

1. Creates `sentinel_core`, `sentinel_detection`, `sentinel_ml` if they don't exist.
2. Loads the corresponding schema file into each database.
3. Fails the container if any schema fails to load (`ON_ERROR_STOP=1`).

Init scripts run **only once** — when the data volume is first created.
To re-run initialization, destroy the volume first:

```bash
docker compose down -v && docker compose up -d
```

### 5.3 Why Three Databases?

Separate databases enforce service ownership at the connection level. Each service
connects to its own database. A misconfigured service cannot accidentally query
another service's tables. This is a security and reliability boundary.

### 5.4 Connection Examples

```bash
# Connect to sentinel_core
docker compose exec postgres psql -U sentinel -d sentinel_core

# Connect to sentinel_detection
docker compose exec postgres psql -U sentinel -d sentinel_detection

# Connect to sentinel_ml
docker compose exec postgres psql -U sentinel -d sentinel_ml
```

---

## 6. Redis

Redis is included for future outbox-based event transport (Redis Streams).
It is NOT currently used by the application.

### 6.1 Configuration

- **Image:** `redis:7-alpine`
- **Persistence:** AOF (append-only file), `everysec` fsync
- **Persistence strategy:** Saves at 900s/1key, 300s/10keys, 60s/10000keys

### 6.2 Redis is NOT the Source of Truth

| What Redis is | What Redis is NOT |
|--------------|------------------|
| Future event transport | Session store |
| Future outbox delivery | User database |
| Redis Streams for async | Token store |
| Stream consumer | RBAC cache |

PostgreSQL is always the authoritative database. If Redis is unavailable,
events remain pending in `outbox_events` (Core database) until Redis recovers.

### 6.3 Future Outbox Flow (Not Implemented)

```
Core transaction → PostgreSQL (state + outbox_events row) → commit
                                                         ↓
                         future: Outbox Publisher reads pending rows
                                                         ↓
                                               Redis Stream
                                                         ↓
                                   future: Detection Consumer reads stream
```

---

## 7. Health Checks

Both services have Docker health checks:

| Service | Check | Threshold |
|---------|-------|----------|
| `postgres` | `pg_isready -U sentinel` | 5 retries, 3s timeout, 10s start period |
| `redis` | `redis-cli PING` | 5 retries, 3s timeout, 5s start period |

Services report `healthy` only after the start period elapses and all checks pass.

---

## 8. Volumes

| Volume | Contents |
|--------|---------|
| `sentinel_postgres_data` | PostgreSQL data directory |
| `sentinel_redis_data` | Redis AOF persistence |

Both volumes are project-scoped with explicit names so they do not conflict
with other Docker projects on the same host.

---

## 9. Current Application Compatibility

The **current FastAPI monolith** connects to ONE database via `DATABASE_URL`
(`app/main.py`). It is designed for `sentinel_core`.

Running the monolith against the infrastructure in this document:

```bash
# Start infrastructure
docker compose up -d

# In another terminal, run the application
export DATABASE_URL="postgresql://sentinel:sentinel123@localhost:5432/sentinel_core"
export INTERNAL_SECRET="a-test-secret-at-least-32-characters-long"
export RUN_PRE_TOKEN_CHECK="0"
unset INTERNAL_SECRET
uvicorn app.main:app --reload --port 8000
```

The application will work against `sentinel_core`. It will NOT automatically
use `sentinel_detection` or `sentinel_ml` — those are for the future
three-service architecture.

---

## 10. Future: Three-Service Split

When the application is split into three independent services, each service
will connect to its own database:

| Service | Database | Port (planned) |
|---------|----------|---------------|
| Core/Auth | `sentinel_core` | 8000 |
| Detection | `sentinel_detection` | 8001 |
| ML | `sentinel_ml` | 8002 |

Each service will use its own `DATABASE_URL` environment variable.
The infrastructure in this document already supports this by creating all
three databases on first run.

---

## 11. Troubleshooting

### "database does not exist"

The init script only runs on first start. If the database was not created:
```bash
docker compose down -v && docker compose up -d
```

### "permission denied for database"

Ensure `POSTGRES_USER` and `POSTGRES_PASSWORD` match between the init script
environment and `docker-compose.yml`.

### Redis not responding

```bash
docker compose exec redis redis-cli PING
# Should return: PONG

# Check Redis logs
docker compose logs redis
```

### Port conflicts

If ports 5432 or 6379 are in use:
```bash
POSTGRES_PORT=5433 REDIS_PORT=6380 docker compose up -d
```
