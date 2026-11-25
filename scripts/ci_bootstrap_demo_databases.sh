#!/usr/bin/env bash
# Sentinel Auth v3.3 — CI demo-database bootstrap
#
# Provisions the three DISPOSABLE DEMO databases the M13 fixture tests
# need:
#
#   sentinel_core_demo      <- infra/postgres/schema-core-v3.3.sql
#   sentinel_detection_demo <- infra/postgres/schema-detection-v3.3.sql
#   sentinel_ml_demo        <- infra/postgres/schema-ml-service-v3.3.sql
#
# Why a separate script
# --------------------
# `scripts/ci_bootstrap_postgres.sh` provisions the `*_test` databases and
# its guard REFUSES to touch anything whose name lacks the `_test` marker.
# The demo fixtures have the opposite requirement: `scripts/demo_seed_demo.py`
# refuses to write to a database whose name lacks the `_demo` marker.
#
# The two guards must never be relaxed into a single rule, because each one
# is a safety boundary for a different destructive operation.  So the demo
# databases get their own bootstrap script, with their own guard, and the
# two marker vocabularies stay disjoint.
#
# The script is idempotent: it drops and recreates the three databases, so a
# rerun always starts from the canonical schema.  It never touches a
# database whose name lacks the `_demo` marker.
#
# Usage:
#   POSTGRES_HOST=127.0.0.1 POSTGRES_PORT=5432 \
#   POSTGRES_USER=sentinel POSTGRES_PASSWORD=... \
#   scripts/ci_bootstrap_demo_databases.sh
#
# Secrets: the password is read from the environment and is never echoed.
# Every value printed by this script is either a database name or a table
# count.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCHEMA_DIR="${REPO_ROOT}/infra/postgres"

# --- Connection settings ----------------------------------------------------
PGHOST="${POSTGRES_HOST:-127.0.0.1}"
PGPORT="${POSTGRES_PORT:-5432}"
PGUSER="${POSTGRES_USER:-sentinel}"
PGPASSWORD="${POSTGRES_PASSWORD:-}"

#: The three disposable demo database names.  The `_demo` marker is what
#: `scripts/demo_seed_demo.py` checks before it writes or deletes a row.
CORE_DB="sentinel_core_demo"
DETECTION_DB="sentinel_detection_demo"
ML_DB="sentinel_ml_demo"

export PGHOST PGPORT PGUSER PGPASSWORD

log() { printf '[ci-bootstrap-demo] %s\n' "$*"; }
fail() { printf '[ci-bootstrap-demo] ERROR: %s\n' "$*" >&2; exit 1; }

# --- Preconditions ---------------------------------------------------------
command -v psql >/dev/null 2>&1 || fail "psql is not on PATH - install the PostgreSQL client"

for schema_file in \
    "schema-core-v3.3.sql" \
    "schema-detection-v3.3.sql" \
    "schema-ml-service-v3.3.sql"
do
    [ -f "${SCHEMA_DIR}/${schema_file}" ] \
        || fail "canonical schema file is missing: ${SCHEMA_DIR}/${schema_file}"
done

# --- Wait for the server ----------------------------------------------------
log "waiting for PostgreSQL at ${PGHOST}:${PGPORT} ..."
for attempt in $(seq 1 60); do
    if pg_isready -h "${PGHOST}" -p "${PGPORT}" -U "${PGUSER}" >/dev/null 2>&1; then
        log "PostgreSQL is accepting connections"
        break
    fi
    if [ "${attempt}" -eq 60 ]; then
        fail "PostgreSQL did not become ready within 60 seconds"
    fi
    sleep 1
done

# --- Drop and recreate the disposable demo databases -------------------------
# The names are hard-coded above, so the guard below can only ever pass.
for db_name in "${CORE_DB}" "${DETECTION_DB}" "${ML_DB}"; do
    case "${db_name}" in
        *_demo) ;;
        *) fail "refusing to touch ${db_name}: the name lacks the _demo marker" ;;
    esac
done

log "recreating the three disposable demo databases"
for db_name in "${CORE_DB}" "${DETECTION_DB}" "${ML_DB}"; do
    # Terminate any lingering session so the DROP cannot block.
    psql -v ON_ERROR_STOP=1 -q -d postgres -c \
        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity
          WHERE datname = '${db_name}' AND pid <> pg_backend_pid();" >/dev/null
    psql -v ON_ERROR_STOP=1 -q -d postgres -c "DROP DATABASE IF EXISTS \"${db_name}\";"
    psql -v ON_ERROR_STOP=1 -q -d postgres -c "CREATE DATABASE \"${db_name}\";"
    log "  created ${db_name}"
done

# --- Load the canonical schemas ---------------------------------------------
count_base_tables() {
    psql -v ON_ERROR_STOP=1 -At -d "$1" -c \
        "SELECT count(*) FROM information_schema.tables
          WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"
}

count_views() {
    psql -v ON_ERROR_STOP=1 -At -d "$1" -c \
        "SELECT count(*) FROM information_schema.views
          WHERE table_schema = 'public'"
}

load_schema() {
    local db_name="$1"
    local schema_file="$2"
    log "  loading ${schema_file} into ${db_name}"
    psql -v ON_ERROR_STOP=1 -q -d "${db_name}" -f "${SCHEMA_DIR}/${schema_file}" \
        >/dev/null
}

load_schema "${CORE_DB}"      "schema-core-v3.3.sql"
load_schema "${DETECTION_DB}" "schema-detection-v3.3.sql"
load_schema "${ML_DB}"        "schema-ml-service-v3.3.sql"

# --- Verify the topology ----------------------------------------------------
core_tables="$(count_base_tables "${CORE_DB}")"
detection_tables="$(count_base_tables "${DETECTION_DB}")"
ml_tables="$(count_base_tables "${ML_DB}")"
ml_views="$(count_views "${ML_DB}")"

log "sentinel_core_demo:      ${core_tables} base tables (expected 13)"
log "sentinel_detection_demo: ${detection_tables} base tables (expected 7)"
log "sentinel_ml_demo:        ${ml_tables} base tables (expected 3), ${ml_views} view(s) (expected 1)"

[ "${core_tables}" -eq 13 ]      || fail "${CORE_DB} has ${core_tables} base tables, expected 13"
[ "${detection_tables}" -eq 7 ]  || fail "${DETECTION_DB} has ${detection_tables} base tables, expected 7"
[ "${ml_tables}" -eq 3 ]         || fail "${ML_DB} has ${ml_tables} base tables, expected 3"
[ "${ml_views}" -ge 1 ]          || fail "${ML_DB} has no view, expected at least the local_ml_stats view"

# --- Prove the bounded contexts stay disjoint --------------------------------
assert_absent() {
    local db_name="$1"
    local table_name="$2"
    local found
    found="$(psql -v ON_ERROR_STOP=1 -At -d "${db_name}" -c \
        "SELECT count(*) FROM information_schema.tables
          WHERE table_schema = 'public' AND table_name = '${table_name}'")"
    [ "${found}" -eq 0 ] \
        || fail "${db_name} unexpectedly owns the table ${table_name}"
}

for table_name in login_attempts inference_logs alerts; do
    assert_absent "${CORE_DB}" "${table_name}"
done
for table_name in users sessions inference_logs; do
    assert_absent "${DETECTION_DB}" "${table_name}"
done
for table_name in users sessions login_attempts alerts; do
    assert_absent "${ML_DB}" "${table_name}"
done
log "cross-context table isolation verified"

log "bootstrap complete"
