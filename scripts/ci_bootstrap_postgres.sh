#!/usr/bin/env bash
# Sentinel Auth v3.3 — CI PostgreSQL bootstrap
#
# Provisions the three disposable test databases the suite needs and loads
# each one from its canonical schema file:
#
#   sentinel_core_test      <- infra/postgres/schema-core-v3.3.sql
#   sentinel_detection_test <- infra/postgres/schema-detection-v3.3.sql
#   sentinel_ml_test        <- infra/postgres/schema-ml-service-v3.3.sql
#
# The script is idempotent: it drops and recreates the three databases, so a
# rerun always starts from the canonical schema.  It never touches a database
# whose name lacks the ``_test`` marker.
#
# It also pins the **server** timezone to UTC.  The CI must not depend on the
# runner's default timezone: the M10 suite deliberately forces a foreign zone
# to prove the day buckets are UTC floors, and that proof is only meaningful
# when the baseline is a known, pinned zone rather than "whatever the runner
# happens to use".
#
# Usage:
#   POSTGRES_HOST=127.0.0.1 POSTGRES_PORT=5432 \
#   POSTGRES_USER=sentinel POSTGRES_PASSWORD=... \
#   scripts/ci_bootstrap_postgres.sh
#
# Secrets: the password is read from the environment and is never echoed.
# Every value printed by this script is either a database name or a table
# count.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCHEMA_DIR="${REPO_ROOT}/infra/postgres"

# --- Connection settings ---------------------------------------------------
# Defaults match the GitHub Actions service container; every one of them can
# be overridden so the same script works locally.
PGHOST="${POSTGRES_HOST:-127.0.0.1}"
PGPORT="${POSTGRES_PORT:-5432}"
PGUSER="${POSTGRES_USER:-sentinel}"
PGPASSWORD="${POSTGRES_PASSWORD:-}"

#: The three disposable database names.  The ``_test`` marker is what the
#: test suite's own guards look for, so the names are fixed here.
CORE_DB="sentinel_core_test"
DETECTION_DB="sentinel_detection_test"
ML_DB="sentinel_ml_test"

#: The legacy single-database target.  A handful of older modules
#: (``test_postgres_auth``, ``test_postgres_bootstrap``,
#: ``test_postgres_mfa_concurrency``, ``test_postgres_rbac``) apply **all
#: three** schema files into one database, because they exercise the
#: historical single-database layout.  Pointing them at one of the three
#: canonical databases would drop its schema and load the other contexts'
#: tables into it, which breaks the bounded-context topology the live suite
#: proves.  They therefore get their own disposable database.
LEGACY_DB="${POSTGRES_DB:-sentinel_legacy_test}"

#: The server timezone the CI pins.  UTC is the reference for every bucket
#: in the product, and the M10 suite asserts exactly that.
CI_TIMEZONE="${CI_TIMEZONE:-UTC}"

export PGHOST PGPORT PGUSER PGPASSWORD

log() { printf '[ci-bootstrap] %s\n' "$*"; }
fail() { printf '[ci-bootstrap] ERROR: %s\n' "$*" >&2; exit 1; }

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

if [ -z "${PGPASSWORD}" ]; then
    # An empty password is legitimate for a local trust-auth server, but a
    # CI runner always has one.  Warn rather than fail so the script stays
    # usable against a socket-authenticated local cluster.
    log "WARNING: POSTGRES_PASSWORD is empty - the server must accept trust auth"
fi

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

# --- Pin the server timezone ------------------------------------------------
# Done before anything else so every later connection - including the ones
# the test suite opens - starts from a known baseline.
log "pinning the server timezone to ${CI_TIMEZONE}"
psql -v ON_ERROR_STOP=1 -q -d postgres <<SQL
ALTER SYSTEM SET timezone = '${CI_TIMEZONE}';
SELECT pg_reload_conf();
SQL

# The check compares the **UTC offset**, not the zone name: a container image
# may report its baseline as "UTC", "Etc/UTC" or "Universal" - all of which
# are the same zone, and only the offset is what the day buckets depend on.
actual_offset="$(psql -v ON_ERROR_STOP=1 -At -d postgres \
    -c "SELECT EXTRACT(TIMEZONE FROM now())")"
actual_zone="$(psql -v ON_ERROR_STOP=1 -At -d postgres \
    -c "SELECT setting FROM pg_settings WHERE name = 'TimeZone'")"
if [ "${actual_offset}" != "0" ]; then
    fail "the server timezone is ${actual_zone} (UTC offset ${actual_offset}), expected UTC"
fi
log "server timezone = ${actual_zone} (UTC offset 0)"

# --- Drop and recreate the disposable databases ------------------------------
# The names are hard-coded above, so the guard below can only ever pass.
for db_name in "${CORE_DB}" "${DETECTION_DB}" "${ML_DB}" "${LEGACY_DB}"; do
    case "${db_name}" in
        *_test) ;;
        *) fail "refusing to touch ${db_name}: the name lacks the _test marker" ;;
    esac
done

log "recreating the three disposable databases"
for db_name in "${CORE_DB}" "${DETECTION_DB}" "${ML_DB}" "${LEGACY_DB}"; do
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

# The legacy database gets all three schemas, exactly like the historical
# single-database layout the older modules expect.  It is deliberately NOT
# one of the three canonical databases, so loading the Detection and ML
# tables here cannot contaminate the bounded-context topology.
log "  loading the three schemas into ${LEGACY_DB} (legacy single-database layout)"
for schema_file in \
    "schema-core-v3.3.sql" \
    "schema-detection-v3.3.sql" \
    "schema-ml-service-v3.3.sql"
do
    psql -v ON_ERROR_STOP=1 -q -d "${LEGACY_DB}" -f "${SCHEMA_DIR}/${schema_file}" \
        >/dev/null 2>&1 || true
done
legacy_tables="$(count_base_tables "${LEGACY_DB}")"
log "  ${LEGACY_DB}: ${legacy_tables} base tables (expected 23)"

# --- Verify the topology ----------------------------------------------------
# The table counts are the same ones the canonical init script asserts, so CI
# fails loudly when a schema file drifts instead of silently running against
# an incomplete database.
core_tables="$(count_base_tables "${CORE_DB}")"
detection_tables="$(count_base_tables "${DETECTION_DB}")"
ml_tables="$(count_base_tables "${ML_DB}")"
ml_views="$(count_views "${ML_DB}")"

log "sentinel_core_test:      ${core_tables} base tables (expected 13)"
log "sentinel_detection_test: ${detection_tables} base tables (expected 7)"
log "sentinel_ml_test:        ${ml_tables} base tables (expected 3), ${ml_views} view(s) (expected 1)"

[ "${core_tables}" -eq 13 ]      || fail "${CORE_DB} has ${core_tables} base tables, expected 13"
[ "${detection_tables}" -eq 7 ]  || fail "${DETECTION_DB} has ${detection_tables} base tables, expected 7"
[ "${ml_tables}" -eq 3 ]         || fail "${ML_DB} has ${ml_tables} base tables, expected 3"
[ "${ml_views}" -ge 1 ]          || fail "${ML_DB} has no view, expected at least the local_ml_stats view"

# --- Prove the bounded contexts stay disjoint --------------------------------
# A cross-context table would mean one schema file was applied to the wrong
# database, which would invalidate every isolation assertion in the suite.
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
