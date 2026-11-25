#!/usr/bin/env bash
# Sentinel Auth v3.3 — CI demo-database bootstrap
#
# Provisions the three DISPOSABLE CI demo databases the M13 fixture tests
# need:
#
#   sentinel_core_ci_demo      <- infra/postgres/schema-core-v3.3.sql
#   sentinel_detection_ci_demo <- infra/postgres/schema-detection-v3.3.sql
#   sentinel_ml_ci_demo        <- infra/postgres/schema-ml-service-v3.3.sql
#
# ============================================================================
# WHY THE CI NAMES ARE DIFFERENT FROM THE LOCAL DEMO NAMES
# ============================================================================
#
# The local demo stack owns the PERSISTENT databases `sentinel_core_demo`,
# `sentinel_detection_demo` and `sentinel_ml_demo`.  They live in a named
# Docker volume, they hold the developer's demo fixtures, and
# `scripts/demo_stack.sh stop` / `restart` MUST NOT lose them.
#
# This script DROPS and RECREATES databases.  If it used the local demo
# names, then running it by hand on a developer machine would silently
# destroy the running demo stack's data — and the developer would have no
# reason to suspect it, because the script is called "bootstrap".
#
# So the CI databases carry a SECOND marker, `_ci_demo`, and the two
# vocabularies are disjoint by construction:
#
#   local demo stack (persistent) : sentinel_core_demo
#   CI disposable                 : sentinel_core_ci_demo
#
# The `_ci_demo` names still END with `_demo`, which is what
# `scripts/demo_seed_demo.py` requires before it writes or deletes a row.
# That is why the ORDER of the markers matters: `_demo` is the suffix the
# seed guard checks, and `_ci_demo` is a strict refinement of it.
#
# ============================================================================
# THE SAFETY MODEL — FAIL-CLOSED, LAYER BY LAYER
# ============================================================================
#
# Every layer below REFUSES by default.  The destructive SQL runs only
# when ALL of them are satisfied.  The layers are independent, so a bug in
# one does not open a hole in the next.
#
#   Layer 1  ALLOWLIST      The three target names are compared against a
#                           hard-coded list.  A name outside the list is
#                           refused.  The list CANNOT be overridden from
#                           the environment.
#
#   Layer 2  MARKER         Every name must end with `_ci_demo`.  That is
#                           the machine-readable marker of a CI-disposable
#                           demo database.
#
#   Layer 3  NO OVERLAP     The local demo stack's database names must NOT
#                           be in the target set.  Even if the allowlist
#                           were edited by mistake, the persistent
#                           databases stay protected.
#
#   Layer 4  SERVER STATE   The script refuses to run against a server
#                           that holds the local demo stack's databases,
#                           whatever the environment claims.  The server
#                           must ALSO be declared disposable.
#
#   Layer 5  ACKNOWLEDGEMENT The acknowledgement must name exactly the
#                           databases the script touches.  A generic "yes"
#                           cannot authorise anything, and a stale
#                           acknowledgement cannot authorise a different
#                           set.  It is checked against the ALLOWLIST, so
#                           the two can never drift apart.
#
# NO SINGLE ENVIRONMENT VARIABLE CAN DISABLE THE PROTECTION.  The
# declaration and the acknowledgement are separate inputs, the
# acknowledgement must match the allowlist exactly, and Layer 4 verifies
# the REAL state of the server regardless of what either of them says.
# Setting `DEMO_CI_DISPOSABLE_SERVER=true` on a server that carries the
# demo stack's data does not get past Layer 4.
#
# ============================================================================
# USAGE
# ============================================================================
#
# In CI (the environment provides both inputs):
#
#   DEMO_CI_DISPOSABLE_SERVER=true \
#   DEMO_CI_ACK="sentinel_core_ci_demo sentinel_detection_ci_demo \
#                 sentinel_ml_ci_demo" \
#   POSTGRES_HOST=127.0.0.1 POSTGRES_PORT=5432 \
#   POSTGRES_USER=sentinel POSTGRES_PASSWORD=... \
#   scripts/ci_bootstrap_demo_databases.sh
#
# By hand (the acknowledgement is asked for interactively):
#
#   scripts/ci_bootstrap_demo_databases.sh
#   ... prints the exact names and asks to type them ...
#
# Secrets: the password is read from the environment and is never echoed.
# Every value printed by this script is either a database name, a table
# count or a refusal reason.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCHEMA_DIR="${REPO_ROOT}/infra/postgres"

# --- Connection settings ----------------------------------------------------
PGHOST="${POSTGRES_HOST:-127.0.0.1}"
PGPORT="${POSTGRES_PORT:-5432}"
PGUSER="${POSTGRES_USER:-sentinel}"
PGPASSWORD="${POSTGRES_PASSWORD:-}"

# --- Layer 1: the allowlist --------------------------------------------------
#: The ONLY databases this script may ever drop or create.  These names are
#: hard-coded on purpose: an environment variable must never be able to
#: widen the set of databases a destructive script touches.
ALLOWED_DATABASES=(
    "sentinel_core_ci_demo"
    "sentinel_detection_ci_demo"
    "sentinel_ml_ci_demo"
)

# --- Layer 2: the marker -----------------------------------------------------
#: Every target name must end with this marker.  It is a strict refinement
#: of the seed script's `_demo` marker: a name ending with `_ci_demo` also
#: ends with `_demo`.
CI_MARKER="_ci_demo"

#: The marker `scripts/demo_seed_demo.py` requires.  Kept here so the
#: relationship between the two markers is asserted in one place.
SEED_MARKER="_demo"

# --- Layer 3: the protected local demo databases -----------------------------
#: The persistent databases of the local demo stack.  They must never
#: appear in the target set.
PROTECTED_LOCAL_DATABASES=(
    "sentinel_core_demo"
    "sentinel_detection_demo"
    "sentinel_ml_demo"
)

export PGHOST PGPORT PGUSER PGPASSWORD

log() { printf '[ci-bootstrap-demo] %s\n' "$*"; }

#: Print a refusal and return 1.  The guards RETURN a status instead of
#: exiting, so the test suite can exercise them directly; the caller
#: decides whether a refusal is fatal.
refuse() {
    printf '[ci-bootstrap-demo] ERROR: %s\n' "$*" >&2
    return 1
}

fail() {
    printf '[ci-bootstrap-demo] ERROR: %s\n' "$*" >&2
    exit 1
}

# =============================================================================
# The guards
# =============================================================================

# --- Layer 1 -----------------------------------------------------------------
#: Refuse a name that is not in the allowlist.
guard_allowlisted() {
    local name="$1"
    local allowed
    for allowed in "${ALLOWED_DATABASES[@]}"; do
        if [ "${name}" = "${allowed}" ]; then
            return 0
        fi
    done
    refuse "refusing to touch '${name}': it is not in the allowlist of CI-disposable demo databases (${ALLOWED_DATABASES[*]}). The allowlist is hard-coded and cannot be overridden from the environment."
}

# --- Layer 2 -----------------------------------------------------------------
#: Refuse a name that does not carry the CI marker, or that would not be
#: accepted by the seed script's own guard.
guard_marked() {
    local name="$1"
    case "${name}" in
        *"${CI_MARKER}") ;;
        *) refuse "refusing to touch '${name}': the name does not carry the '${CI_MARKER}' marker."; return 1 ;;
    esac
    # The refinement must hold: the seed script's guard has to accept the
    # name too, otherwise the fixtures could never be seeded into it.
    case "${name}" in
        *"${SEED_MARKER}") ;;
        *) refuse "refusing to touch '${name}': the name must also end with the seed script's '${SEED_MARKER}' marker."; return 1 ;;
    esac
}

# --- Layer 3 -----------------------------------------------------------------
#: Refuse a name that is one of the local demo stack's persistent
#: databases.
guard_no_local_overlap() {
    local name="$1"
    local protected
    for protected in "${PROTECTED_LOCAL_DATABASES[@]}"; do
        if [ "${name}" = "${protected}" ]; then
            refuse "refusing to touch '${name}': it is one of the local demo stack's persistent databases. The CI bootstrap must never drop those."
            return 1
        fi
    done
}

# --- Layer 4 -----------------------------------------------------------------
#: Refuse a server that carries the local demo stack's databases, whatever
#: the environment claims.  The server must also be declared disposable.
#
# This is the layer that protects a RUNNING demo stack: the names differ,
# so the CI databases could be dropped there without harm, but the refusal
# is what stops the situation from being "accidentally acceptable" and
# therefore from drifting into a "the names are different, so it is fine"
# assumption.
guard_disposable_server() {
    local listing="$1"
    local protected
    for protected in "${PROTECTED_LOCAL_DATABASES[@]}"; do
        if database_exists "${listing}" "${protected}"; then
            refuse "refusing to run: the target server holds the local demo stack's persistent database '${protected}'. Point the script at a disposable CI server that does not carry the demo stack's data. Nothing was changed."
            return 1
        fi
    done

    # The server is free of the local demo stack's databases.  It still has
    # to be DECLARED disposable, so that a run against an unrelated shared
    # server is refused rather than silently dropping the CI databases on
    # it.
    if [ "${DEMO_CI_DISPOSABLE_SERVER:-}" != "true" ]; then
        refuse "refusing to run: the target server was not declared disposable. Set DEMO_CI_DISPOSABLE_SERVER=true when the server is a disposable CI server. Nothing was changed."
        return 1
    fi
}

# --- Layer 5 -----------------------------------------------------------------
#: Refuse an acknowledgement that does not name exactly the databases the
#: script touches.
#
#: When no acknowledgement is supplied, the caller is asked interactively.
#: The comparison is against the ALLOWLIST, so the two cannot drift apart.
guard_acknowledged() {
    local ack="${DEMO_CI_ACK:-}"
    local expected actual

    expected="$(printf '%s\n' "${ALLOWED_DATABASES[@]}" | sort | tr '\n' ' ')"
    actual="$(printf '%s\n' ${ack} | sort | tr '\n' ' ')"

    # The CI environment supplies the acknowledgement, so the CI run stays
    # fully non-interactive.
    if [ -n "${ack}" ]; then
        if [ "${expected}" != "${actual}" ]; then
            refuse "refusing to run: the acknowledgement does not name exactly the databases this script touches. Expected '${expected}', got '${actual}'. Nothing was changed."
            return 1
        fi
        log "the acknowledgement names all three CI-disposable demo databases"
        return 0
    fi

    # A manual run asks for it, and says exactly what it is about to do.
    printf '\n'
    log "This script DROPS and RECREATES the following databases:"
    for name in "${ALLOWED_DATABASES[@]}"; do
        log "  - ${name}"
    done
    printf '\n'
    printf 'Type the three names above, separated by spaces, to proceed: '

    local typed
    read -r typed || typed=""
    actual="$(printf '%s\n' ${typed} | sort | tr '\n' ' ')"
    if [ "${expected}" != "${actual}" ]; then
        refuse "the confirmation did not match. Nothing was changed."
        return 1
    fi
    log "the confirmation matched"
}

#: Run every guard against a single target name.
guard_target_name() {
    local name="$1"
    guard_allowlisted "${name}" || return 1
    guard_marked "${name}" || return 1
    guard_no_local_overlap "${name}" || return 1
}

# =============================================================================
# The helpers
# =============================================================================

#: List the non-template databases of the target server.
list_databases() {
    psql -v ON_ERROR_STOP=1 -At -d postgres -c \
        "SELECT datname FROM pg_database WHERE datistemplate = false ORDER BY 1;" 2>/dev/null || true
}

#: Test whether a database name is present in a listing.
database_exists() {
    local listing="$1"
    local name="$2"
    printf '%s\n' "${listing}" | grep -qxF -- "${name}"
}

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

# =============================================================================
# The main flow
# =============================================================================

main() {
    # --- Preconditions ----------------------------------------------------
    command -v psql >/dev/null 2>&1 \
        || fail "psql is not on PATH - install the PostgreSQL client"

    local schema_file
    for schema_file in \
        "schema-core-v3.3.sql" \
        "schema-detection-v3.3.sql" \
        "schema-ml-service-v3.3.sql"
    do
        [ -f "${SCHEMA_DIR}/${schema_file}" ] \
            || fail "canonical schema file is missing: ${SCHEMA_DIR}/${schema_file}"
    done

    # --- Layers 1, 2 and 3, applied to every target ----------------------
    local db_name
    for db_name in "${ALLOWED_DATABASES[@]}"; do
        guard_target_name "${db_name}" \
            || fail "the target '${db_name}' failed a safety guard. Nothing was changed."
    done
    log "every target passed the allowlist, the marker and the overlap checks"

    # --- Wait for the server ----------------------------------------------
    log "waiting for PostgreSQL at ${PGHOST}:${PGPORT} ..."
    local attempt
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

    # --- Layer 4 -----------------------------------------------------------
    local listing
    listing="$(list_databases)"
    guard_disposable_server "${listing}" \
        || fail "the target server failed a safety guard. Nothing was changed."
    log "the target server carries none of the local demo stack's databases"

    # --- Layer 5 -----------------------------------------------------------
    guard_acknowledged || fail "the acknowledgement was refused. Nothing was changed."

    # --- Drop and recreate the disposable CI demo databases ----------------
    log "recreating the three disposable CI demo databases"
    for db_name in "${ALLOWED_DATABASES[@]}"; do
        # The guards are re-applied immediately before the destructive SQL.
        # Nothing between the guard and the statement may widen the target
        # set.
        guard_target_name "${db_name}" \
            || fail "the target '${db_name}' failed a safety guard. Nothing was changed."

        # Terminate any lingering session so the DROP cannot block.
        psql -v ON_ERROR_STOP=1 -q -d postgres -c \
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity
              WHERE datname = '${db_name}' AND pid <> pg_backend_pid();" >/dev/null
        psql -v ON_ERROR_STOP=1 -q -d postgres -c "DROP DATABASE IF EXISTS \"${db_name}\";"
        psql -v ON_ERROR_STOP=1 -q -d postgres -c "CREATE DATABASE \"${db_name}\";"
        log "  created ${db_name}"
    done

    # --- Load the canonical schemas ---------------------------------------
    load_schema "sentinel_core_ci_demo"      "schema-core-v3.3.sql"
    load_schema "sentinel_detection_ci_demo" "schema-detection-v3.3.sql"
    load_schema "sentinel_ml_ci_demo"        "schema-ml-service-v3.3.sql"

    # --- Verify the topology ----------------------------------------------
    local core_tables detection_tables ml_tables ml_views
    core_tables="$(count_base_tables "sentinel_core_ci_demo")"
    detection_tables="$(count_base_tables "sentinel_detection_ci_demo")"
    ml_tables="$(count_base_tables "sentinel_ml_ci_demo")"
    ml_views="$(count_views "sentinel_ml_ci_demo")"

    log "sentinel_core_ci_demo:      ${core_tables} base tables (expected 13)"
    log "sentinel_detection_ci_demo: ${detection_tables} base tables (expected 7)"
    log "sentinel_ml_ci_demo:        ${ml_tables} base tables (expected 3), ${ml_views} view(s) (expected 1)"

    [ "${core_tables}" -eq 13 ] \
        || fail "sentinel_core_ci_demo has ${core_tables} base tables, expected 13"
    [ "${detection_tables}" -eq 7 ] \
        || fail "sentinel_detection_ci_demo has ${detection_tables} base tables, expected 7"
    [ "${ml_tables}" -eq 3 ] \
        || fail "sentinel_ml_ci_demo has ${ml_tables} base tables, expected 3"
    [ "${ml_views}" -ge 1 ] \
        || fail "sentinel_ml_ci_demo has no view, expected at least the local_ml_stats view"

    # --- Prove the bounded contexts stay disjoint --------------------------
    assert_absent() {
        local db="$1"
        local table="$2"
        local found
        found="$(psql -v ON_ERROR_STOP=1 -At -d "${db}" -c \
            "SELECT count(*) FROM information_schema.tables
              WHERE table_schema = 'public' AND table_name = '${table}'")"
        [ "${found}" -eq 0 ] \
            || fail "${db} unexpectedly owns the table ${table}"
    }

    for table in login_attempts inference_logs alerts; do
        assert_absent "sentinel_core_ci_demo" "${table}"
    done
    for table in users sessions inference_logs; do
        assert_absent "sentinel_detection_ci_demo" "${table}"
    done
    for table in users sessions login_attempts alerts; do
        assert_absent "sentinel_ml_ci_demo" "${table}"
    done
    log "cross-context table isolation verified"

    log "bootstrap complete"
}

# The script runs its main flow when it is EXECUTED, and only defines the
# functions when it is SOURCED.  That is what lets the test suite exercise
# every guard directly without running any destructive SQL.
if [ "${BASH_SOURCE[0]}" = "${0}" ]; then
    main
fi
