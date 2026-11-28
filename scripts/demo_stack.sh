#!/usr/bin/env bash
# Sentinel Auth v3.3 — M13 demo stack orchestration.
#
# Brings up the COMPLETE demo environment from a clean clone with one
# command, and gives it one uniform set of lifecycle commands:
#
#   scripts/demo_stack.sh start     # infra + SMTP sink + API + frontend
#   scripts/demo_stack.sh stop      # stop everything, KEEP the volumes
#   scripts/demo_stack.sh status    # what is running right now
#   scripts/demo_stack.sh logs      # tail the logs of every component
#   scripts/demo_stack.sh restart   # stop + start (the data must survive)
#   scripts/demo_stack.sh verify    # the demo acceptance checks
#   scripts/demo_stack.sh reset     # DESTROY the demo volumes (asks first)
#
# ---------------------------------------------------------------------------
# RELATIONSHIP TO scripts/deploy_local.sh
# ---------------------------------------------------------------------------
# This script does NOT replace `scripts/deploy_local.sh` and does NOT
# modify it.  The canonical deployment keeps reading `.env` and keeps its
# own ports and database names.  The demo stack reads `.env.demo` and uses
# its OWN ports and its OWN database names, so the two deployments can run
# side by side on the same machine without fighting.
#
# The demo stack REUSES `scripts/deploy_local.sh` for the infrastructure
# layer: it calls the same compose file with the same schema bootstrap, so
# there is exactly one definition of "the three-database topology" in the
# repository.
#
# ---------------------------------------------------------------------------
# SAFETY
# ---------------------------------------------------------------------------
# * No secret is ever written to a tracked file.  `.env.demo` is
#   gitignored; `.env.demo.example` holds placeholders only.
# * The demo database names carry the `_demo` marker.  Every fixture
#   script refuses to write into a database without that marker.
# * `stop` NEVER destroys a volume.  Only `reset` does, and it asks for a
#   typed confirmation first.
# * `verify` NEVER drops a database, reloads a schema or deletes a row
#   outside its own fixture scope.
# * The demo stack never touches the canonical deployment's `.env`, its
#   ports or its databases.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

# The CORS origin rule — ONE definition, shared with the canonical
# deployment, so the two can never drift apart.
source "${REPO_ROOT}/scripts/cors_origins.sh"

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------
: "${COMPOSE_CMD:=docker compose}"
: "${COMPOSE_PROJECT_NAME:=sentinel-auth-demo}"
: "${DEMO_ENV_FILE:=${REPO_ROOT}/.env.demo}"
: "${DEMO_STATE_DIR:=${REPO_ROOT}/.ci/demo}"
: "${APP_READY_TIMEOUT:=120}"
: "${FRONTEND_READY_TIMEOUT:=120}"

log()  { printf '\033[1m[demo]\033[0m %s\n' "$*"; }
warn() { printf '\033[33m[demo]\033[0m %s\n' "$*" >&2; }
fail() { printf '\033[31m[demo] ERROR:\033[0m %s\n' "$*" >&2; exit 1; }

# The compose command must be a single word or a path plus arguments.
read -r -a COMPOSE <<< "${COMPOSE_CMD}"
compose() { "${COMPOSE[@]}" "$@"; }

mkdir -p "${DEMO_STATE_DIR}"

# -----------------------------------------------------------------------------
# Environment loading
#
# The demo environment lives in its own file so it can never collide with
# the canonical deployment's `.env`.  Values already present in the shell
# environment win, so a single variable can be overridden for one run.
# -----------------------------------------------------------------------------
load_env() {
    if [ ! -f "${DEMO_ENV_FILE}" ]; then
        fail "the demo environment file '${DEMO_ENV_FILE}' does not exist. Create it with: cp .env.demo.example .env.demo — and then fill in POSTGRES_PASSWORD and INTERNAL_SECRET."
    fi
    log "loading ${DEMO_ENV_FILE##*/}"
    set -a
    # shellcheck disable=SC1090
    . "${DEMO_ENV_FILE}"
    set +a
}

# -----------------------------------------------------------------------------
# Configuration validation
# -----------------------------------------------------------------------------
validate_config() {
    log "validating the demo configuration"

    local missing=()
    for name in POSTGRES_USER POSTGRES_PASSWORD \
                CORE_DB DETECTION_DB ML_DB \
                CORE_DATABASE_URL DETECTION_DATABASE_URL ML_DATABASE_URL \
                INTERNAL_SECRET APP_HOST APP_PORT \
                VITE_DEV_PORT POSTGRES_PORT REDIS_PORT MFA_SMTP_PORT \
                CORE_APP_URL DETECTION_URL; do
        if [ -z "${!name:-}" ]; then
            missing+=("${name}")
        fi
    done
    if [ "${#missing[@]}" -gt 0 ]; then
        fail "missing required variable(s): ${missing[*]}. Copy .env.demo.example to .env.demo and fill them in."
    fi

    # --- the internal secret ---------------------------------------------
    if [ "${#INTERNAL_SECRET}" -lt 32 ]; then
        fail "INTERNAL_SECRET is ${#INTERNAL_SECRET} characters; at least 32 are required."
    fi
    case "${INTERNAL_SECRET}" in
        change-me*|changeme*|replace-me*|placeholder*|your-*|secret*|password*)
            fail "INTERNAL_SECRET still holds a placeholder value. Generate one with: python3 -c 'import secrets; print(secrets.token_urlsafe(32))'"
            ;;
    esac
    if [ "${#POSTGRES_PASSWORD}" -lt 8 ]; then
        fail "POSTGRES_PASSWORD is ${#POSTGRES_PASSWORD} characters; at least 8 are required."
    fi
    case "${POSTGRES_PASSWORD}" in
        change-me*|changeme*|replace-me*|placeholder*)
            fail "POSTGRES_PASSWORD still holds a placeholder value. Generate one with: python3 -c 'import secrets; print(secrets.token_urlsafe(16))'"
            ;;
    esac

    # --- the three bounded contexts must be three DIFFERENT databases ---
    local core_db detection_db ml_db
    core_db="$(database_name_of "${CORE_DATABASE_URL}")"
    detection_db="$(database_name_of "${DETECTION_DATABASE_URL}")"
    ml_db="$(database_name_of "${ML_DATABASE_URL}")"
    if [ "${core_db}" = "${detection_db}" ] || [ "${core_db}" = "${ml_db}" ] \
       || [ "${detection_db}" = "${ml_db}" ]; then
        fail "the three bounded contexts must use three DIFFERENT databases, but they resolve to: core='${core_db}', detection='${detection_db}', ml='${ml_db}'."
    fi

    # --- the demo databases must be recognisable as demo databases ------
    #
    # This is the guard that makes a mistake harmless: the fixture scripts
    # and the cleanup refuse to write into a database whose name does not
    # carry the marker, and the stack refuses to start with a configuration
    # that points somewhere else.
    local db
    for db in "${core_db}" "${detection_db}" "${ml_db}"; do
        case "${db}" in
            *_demo) ;;
            *) fail "the database '${db}' does not carry the '_demo' marker. The demo stack must never be pointed at a production or a shared database." ;;
        esac
    done
    for db in "${CORE_DB}" "${DETECTION_DB}" "${ML_DB}"; do
        case "${db}" in
            *_demo) ;;
            *) fail "the database name '${db}' does not carry the '_demo' marker." ;;
        esac
    done

    # --- the URL credentials must match the server's credentials ---------
    local url_user
    url_user="$(url_user_of "${CORE_DATABASE_URL}")"
    if [ "${url_user}" != "${POSTGRES_USER}" ]; then
        fail "CORE_DATABASE_URL uses the user '${url_user}' but POSTGRES_USER is '${POSTGRES_USER}'."
    fi
    if ! url_password_of "${CORE_DATABASE_URL}" | grep -qF -- "${POSTGRES_PASSWORD}"; then
        fail "the password in CORE_DATABASE_URL does not match POSTGRES_PASSWORD."
    fi

    # --- the monolith talks to itself ------------------------------------
    local core_target detection_target core_port detection_port
    core_target="$(url_host_of "${CORE_APP_URL:-}")"
    detection_target="$(url_host_of "${DETECTION_URL:-}")"
    if [ -z "${core_target}" ] || [ -z "${detection_target}" ]; then
        fail "CORE_APP_URL and DETECTION_URL must both be set for this monolith deployment."
    fi
    if [ "${core_target}" != "${detection_target}" ]; then
        fail "CORE_APP_URL and DETECTION_URL must point at the same server in this monolith deployment, but they resolve to '${core_target}' and '${detection_target}'."
    fi
    core_port="$(url_port_of "${CORE_APP_URL}")"
    detection_port="$(url_port_of "${DETECTION_URL}")"
    if [ "${core_port}" != "${APP_PORT}" ] || [ "${detection_port}" != "${APP_PORT}" ]; then
        fail "CORE_APP_URL and DETECTION_URL must use the application's port (${APP_PORT}), but they use '${core_port}' and '${detection_port}'."
    fi

    # --- the trusted proxy list ------------------------------------------
    if [ "${FORWARDED_ALLOW_IPS:-}" = "*" ]; then
        fail "FORWARDED_ALLOW_IPS='*' is forbidden: any remote client could forge X-Forwarded-For and bypass IP-based controls."
    fi

    # --- the CORS allow-list ----------------------------------------------
    # The rule lives in ONE place — scripts/cors_origins.sh — so the demo
    # stack and the canonical deployment can never drift apart.
    if [ -n "${CORS_ALLOWED_ORIGINS:-}" ]; then
        if ! check_cors_allow_list "${CORS_ALLOWED_ORIGINS}"; then
            fail "${CORS_ERROR_MESSAGE}"
        fi
    fi

    # --- the ML artifact --------------------------------------------------
    if [ -n "${ML_MODEL_PATH:-}" ] && [ ! -f "${ML_MODEL_PATH}" ]; then
        fail "ML_MODEL_PATH points at '${ML_MODEL_PATH}', which does not exist."
    fi

    log "the configuration is valid"
}

# Extract the database name from a PostgreSQL URL.
database_name_of() {
    local url="$1"
    printf '%s' "${url}" | sed -E 's#^[a-zA-Z0-9+]+://##; s#^[^/]*/##; s#\?.*$##; s#/+$##'
}

# Extract the user from a PostgreSQL URL.
url_user_of() {
    local url="$1"
    printf '%s' "${url}" | sed -E 's#^[a-zA-Z0-9+]+://##; s#:.*##'
}

# Extract the password from a PostgreSQL URL.
url_password_of() {
    local url="$1"
    printf '%s' "${url}" | sed -E 's#^[a-zA-Z0-9+]+://##; s#^[^:]*:##; s#@.*##'
}

# Extract the host (without the port) from an HTTP URL.
url_host_of() {
    local url="$1"
    printf '%s' "${url}" | sed -E 's#^[a-zA-Z0-9+]+://##; s#:.*##; s#/.*##'
}

# Extract the port from an HTTP URL.
url_port_of() {
    local url="$1"
    local port
    port="$(printf '%s' "${url}" | sed -E 's#^[a-zA-Z0-9+]+://##; s#/.*##; s#^[^:]*:([0-9]+)$#\1#')"
    if [ "${port}" = "${url}" ] || [ -z "${port}" ]; then
        case "${url}" in
            https://*) port=443 ;;
            *)       port=80 ;;
        esac
    fi
    printf '%s' "${port}"
}

# -----------------------------------------------------------------------------
# Port conflict detection
#
# A port conflict is reported with the process that holds it, and the
# stack stops with a clear message instead of starting a half-broken
# environment.  The check is done BEFORE anything is started, so a
# conflict never leaves a running backend behind.
#
# The containers of THIS project are not a conflict: the demo stack owns
# them, and a `start` on an already-running stack is a restart.  Only a
# port held by something else is reported.
# -----------------------------------------------------------------------------
port_owner() {
    local port="$1"
    ss -ltnpH "sport = :${port}" 2>/dev/null \
        | grep -oE 'users:\(\("?[^"]+"?[^)]*\)' \
        | head -1 || true
}

# Return 0 when the port is published by one of this project's own
# containers.
#
# The containers are recognised by their compose project label.  The
# label is the same one every compose implementation writes, so the check
# works with Docker and with Podman.
port_held_by_own_container() {
    local port="$1"
    local names
    names="$(container_names_of_project 2>/dev/null || true)"
    [ -n "${names}" ] || return 1

    local name ports
    for name in ${names}; do
        ports="$(container_ports_of "${name}" 2>/dev/null || true)"
        # The port mapping is printed as "5432/tcp -> 127.0.0.1:55432".
        # The host port is the last colon-separated field of the mapping.
        if printf '%s' "${ports}" \
            | grep -oE '[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+:[0-9]+' \
            | grep -qE ":${port}\$"; then
            return 0
        fi
    done
    return 1
}

# The names of the containers that belong to this compose project.
#
# The compose plugin writes the ``com.docker.compose.project`` label and
# Podman's own compose provider writes ``io.podman.compose.project``.  Both
# are checked, so the check works with every runtime.
container_names_of_project() {
    local found=""

    if command -v podman >/dev/null 2>&1; then
        found="$(podman ps \
            --filter "label=com.docker.compose.project=${COMPOSE_PROJECT_NAME}" \
            --format '{{.Names}}' 2>/dev/null || true)"
        if [ -z "${found}" ]; then
            found="$(podman ps \
                --filter "label=io.podman.compose.project=${COMPOSE_PROJECT_NAME}" \
                --format '{{.Names}}' 2>/dev/null || true)"
        fi
        [ -n "${found}" ] && { printf '%s\n' "${found}"; return 0; }
    fi

    found="$(docker ps \
        --filter "label=com.docker.compose.project=${COMPOSE_PROJECT_NAME}" \
        --format '{{.Names}}' 2>/dev/null || true)"
    [ -n "${found}" ] && { printf '%s\n' "${found}"; return 0; }

    return 0
}

# The published ports of one container.
#
# The Podman branch must NOT short-circuit on the exit status alone: on a
# host where BOTH runtimes are installed but the containers belong to
# Docker, ``podman port`` exits 0 and prints NOTHING.  A bare
# ``podman port "$1" && return 0`` would therefore return an EMPTY result
# and never reach the Docker fallback — and every port of this project's
# own container would be reported as a conflict.
container_ports_of() {
    if command -v podman >/dev/null 2>&1; then
        local podman_ports
        podman_ports="$(podman port "$1" 2>/dev/null || true)"
        if [ -n "${podman_ports}" ]; then
            printf '%s\n' "${podman_ports}"
            return 0
        fi
    fi
    docker port "$1" 2>/dev/null || true
}

check_ports_free() {
    log "checking the demo ports"
    local conflicts=0
    local label port

    while IFS='|' read -r label port; do
        [ -n "${port}" ] || continue
        if ss -ltnH "sport = :${port}" 2>/dev/null | grep -q .; then
            # A port this project's own container already publishes is
            # not a conflict.
            if port_held_by_own_container "${port}"; then
                log "  port ${port} (${label}) is published by this project's own container"
                continue
            fi
            local owner
            owner="$(port_owner "${port}")"
            warn "port ${port} (${label}) is already in use${owner:+ by ${owner}}"
            conflicts=$((conflicts + 1))
        fi
    done <<EOF
PostgreSQL|${POSTGRES_PORT}
Redis|${REDIS_PORT}
SMTP sink|${MFA_SMTP_PORT}
API|${APP_PORT}
Frontend|${VITE_DEV_PORT}
EOF

    if [ "${conflicts}" -gt 0 ]; then
        fail "${conflicts} demo port(s) are already in use. The demo stack uses its own ports (see .env.demo.example); free them or change the port in .env.demo. Nothing was started."
    fi
    log "all demo ports are free"
}

# -----------------------------------------------------------------------------
# Schema staging
#
# The canonical compose file bind-mounts `./infra/postgres` into the
# container.  On a host whose filesystem cannot carry SELinux labels (a
# removable or network mount such as `/run/media/...` on Fedora) the mount
# is unreadable inside the container and the PostgreSQL entrypoint aborts
# with "Permission denied" before it applies any schema.
#
# The demo stack therefore stages the canonical schema files into a
# directory on the LOCAL filesystem and mounts THAT instead.  The staged
# copy is verified against the repository's checksums, so the demo
# database is built from the canonical schema and not from a variation.
# -----------------------------------------------------------------------------
DEMO_CACHE_ROOT="${DEMO_CACHE_ROOT:-${HOME}/.cache/sentinel-auth-demo}"
DEMO_POSTGRES_SCHEMA_DIR="${DEMO_CACHE_ROOT}/postgres"
DEMO_POSTGRES_INIT_DIR="${DEMO_POSTGRES_SCHEMA_DIR}/init"

stage_schemas() {
    log "staging the canonical schema files"

    local repo_schema_dir="${REPO_ROOT}/infra/postgres"
    local init_script="${repo_schema_dir}/init/00-init-databases.sh"
    local schemas=(
        "schema-core-v3.3.sql"
        "schema-detection-v3.3.sql"
        "schema-ml-service-v3.3.sql"
    )

    for required in "${init_script}" "${repo_schema_dir}/schema-core-v3.3.sql" \
                     "${repo_schema_dir}/schema-detection-v3.3.sql" \
                     "${repo_schema_dir}/schema-ml-service-v3.3.sql"; do
        [ -f "${required}" ] || fail "the canonical schema file is missing: ${required}"
    done

    mkdir -p "${DEMO_POSTGRES_INIT_DIR}" "${DEMO_POSTGRES_SCHEMA_DIR}"

    # The staged copy is refreshed on every start, so a schema change in
    # the repository is picked up without any manual step.
    cp -f "${init_script}" "${DEMO_POSTGRES_INIT_DIR}/00-init-databases.sh"
    chmod 0755 "${DEMO_POSTGRES_INIT_DIR}/00-init-databases.sh"
    for schema in "${schemas[@]}"; do
        cp -f "${repo_schema_dir}/${schema}" "${DEMO_POSTGRES_SCHEMA_DIR}/${schema}"
        chmod 0644 "${DEMO_POSTGRES_SCHEMA_DIR}/${schema}"
    done

    # The staged files must be byte-identical to the repository's files.
    # A truncated copy would produce a database with a missing table, and
    # the topology check would report a confusing "wrong table count".
    local file staged
    for file in "${init_script}" "${repo_schema_dir}"/schema-*.sql; do
        staged="${DEMO_POSTGRES_SCHEMA_DIR}/$(basename "${file}")"
        [ -f "${staged}" ] || staged="${DEMO_POSTGRES_INIT_DIR}/$(basename "${file}")"
        if ! cmp -s "${file}" "${staged}"; then
            fail "the staged copy of '$(basename "${file}")' does not match the repository's file."
        fi
    done

    log "  the schema files are staged in ${DEMO_POSTGRES_SCHEMA_DIR}"
}

# -----------------------------------------------------------------------------
# Infrastructure
# -----------------------------------------------------------------------------
compose_args() {
    printf '%s\n' --project-name "${COMPOSE_PROJECT_NAME}" "$@"
}

compose_up() {
    DEMO_POSTGRES_INIT_DIR="${DEMO_POSTGRES_INIT_DIR}" \
    DEMO_POSTGRES_SCHEMA_DIR="${DEMO_POSTGRES_SCHEMA_DIR}" \
        compose --project-name "${COMPOSE_PROJECT_NAME}" \
        -f "${REPO_ROOT}/docker-compose.yml" \
        -f "${REPO_ROOT}/docker-compose.demo.yml" \
        up -d "$@"
}

compose_down() {
    DEMO_POSTGRES_INIT_DIR="${DEMO_POSTGRES_INIT_DIR}" \
    DEMO_POSTGRES_SCHEMA_DIR="${DEMO_POSTGRES_SCHEMA_DIR}" \
        compose --project-name "${COMPOSE_PROJECT_NAME}" \
        -f "${REPO_ROOT}/docker-compose.yml" \
        -f "${REPO_ROOT}/docker-compose.demo.yml" \
        down "$@"
}

compose_ps() {
    DEMO_POSTGRES_INIT_DIR="${DEMO_POSTGRES_INIT_DIR}" \
    DEMO_POSTGRES_SCHEMA_DIR="${DEMO_POSTGRES_SCHEMA_DIR}" \
        compose --project-name "${COMPOSE_PROJECT_NAME}" \
        -f "${REPO_ROOT}/docker-compose.yml" \
        -f "${REPO_ROOT}/docker-compose.demo.yml" \
        ps "$@" 2>/dev/null || true
}

compose_exec() {
    DEMO_POSTGRES_INIT_DIR="${DEMO_POSTGRES_INIT_DIR}" \
    DEMO_POSTGRES_SCHEMA_DIR="${DEMO_POSTGRES_SCHEMA_DIR}" \
        compose --project-name "${COMPOSE_PROJECT_NAME}" \
        -f "${REPO_ROOT}/docker-compose.yml" \
        -f "${REPO_ROOT}/docker-compose.demo.yml" \
        exec -T "$@"
}

start_infra() {
    log "starting the infrastructure (PostgreSQL + Redis)"
    compose_up
}

wait_for_infra() {
    log "waiting for PostgreSQL to become healthy"
    local deadline=$(( SECONDS + 90 ))
    while [ "${SECONDS}" -lt "${deadline}" ]; do
        if compose_exec -e PGPASSWORD="${POSTGRES_PASSWORD}" postgres \
            pg_isready -U "${POSTGRES_USER}" -d postgres >/dev/null 2>&1; then
            log "PostgreSQL is accepting connections"
            return 0
        fi
        sleep 2
    done
    fail "PostgreSQL did not become ready within 90 seconds. Run 'scripts/demo_stack.sh logs' to see why."
}

# Run a read-only query inside the PostgreSQL container.
psql_in() {
    local db="$1"
    local sql="$2"
    compose_exec -e PGPASSWORD="${POSTGRES_PASSWORD}" postgres \
        psql -v ON_ERROR_STOP=1 -U "${POSTGRES_USER}" -d "${db}" -Atc "${sql}" 2>/dev/null \
        || echo ""
}

# Verify that the three databases exist and hold the canonical schema.
#
# The check is READ-ONLY: it never creates, drops or reloads anything, so
# it is safe to run against a database that already holds data.
verify_topology() {
    log "verifying the three-database topology"

    local db tables expected
    for db in "${CORE_DB}:13" "${DETECTION_DB}:7" "${ML_DB}:3"; do
        local name="${db%%:*}"
        expected="${db##*:}"
        if ! psql_in "${name}" "SELECT 1 FROM pg_database WHERE datname = '${name}';" | grep -q 1; then
            fail "the database '${name}' does not exist. The init script only runs when the volume is first created - run 'scripts/demo_stack.sh reset' to rebuild it from the canonical schemas."
        fi
        tables="$(psql_in "${name}" "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public' AND table_type = 'BASE TABLE';")"
        if [ "${tables}" != "${expected}" ]; then
            fail "the database '${name}' has ${tables} base tables, expected ${expected}. The schema does not match the canonical file."
        fi
        log "  ${name}: ${tables} base tables"
    done

    # Cross-context isolation: a table from another context must be absent.
    local leak
    leak="$(psql_in "${CORE_DB}" "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public' AND table_name IN ('policies','login_attempts','alerts','model_versions');")"
    [ "${leak}" = "0" ] || fail "${CORE_DB} owns ${leak} table(s) from another context. The bounded contexts are not isolated."
    leak="$(psql_in "${DETECTION_DB}" "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public' AND table_name IN ('users','sessions','model_versions');")"
    [ "${leak}" = "0" ] || fail "${DETECTION_DB} owns ${leak} table(s) from another context. The bounded contexts are not isolated."
    leak="$(psql_in "${ML_DB}" "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public' AND table_name IN ('users','sessions','policies','login_attempts','alerts');")"
    [ "${leak}" = "0" ] || fail "${ML_DB} owns ${leak} table(s) from another context. The bounded contexts are not isolated."
    log "  cross-context isolation verified"
}

# -----------------------------------------------------------------------------
# Processes
# -----------------------------------------------------------------------------
# The stack starts four host processes:
#
#   smtp    — the SMTP sink that captures the MFA OTP
#   api     — the FastAPI monolith
#   web     — the Vite dev server
#
# Each one writes its PID into ${DEMO_STATE_DIR}.  A stale PID file from a
# killed run is removed before a start, so a clean start is never blocked.
# -----------------------------------------------------------------------------

pid_file() { printf '%s/%s.pid' "${DEMO_STATE_DIR}" "$1"; }
log_file() { printf '%s/%s.log' "${DEMO_STATE_DIR}" "$1"; }

is_running() {
    local file
    file="$(pid_file "$1")"
    [ -f "${file}" ] && kill -0 "$(cat "${file}")" 2>/dev/null
}

process_pid() {
    local file
    file="$(pid_file "$1")"
    [ -f "${file}" ] && cat "${file}" || echo ""
}

start_smtp_sink() {
    log "starting the SMTP sink on 127.0.0.1:${MFA_SMTP_PORT}"
    rm -f "$(pid_file smtp)"

    local sink_log
    sink_log="$(log_file smtp)"
    # The OTP log path is made ABSOLUTE on purpose: the sink is started
    # from the repository root, but a relative path would silently
    # resolve against whatever directory the process happens to inherit,
    # and the scenario script would then read a log that does not exist.
    #
    # A relative path is resolved against the REPOSITORY ROOT, so the
    # sink and the scenario script always read the same file.
    local otp_log
    otp_log="${MFA_SMTP_LOG:-${DEMO_STATE_DIR}/demo-otp.log}"
    case "${otp_log}" in
        /*) ;;
        *) otp_log="${REPO_ROOT}/${otp_log}" ;;
    esac
    mkdir -p "$(dirname "${otp_log}")"
    nohup python3 scripts/ci_smtp_sink.py \
        --host 127.0.0.1 --port "${MFA_SMTP_PORT}" \
        --log "${otp_log}" \
        >> "${sink_log}" 2>&1 &
    echo $! > "$(pid_file smtp)"

    # The RESOLVED path is written next to the PID files.  It is the
    # single source of truth for the sink and the scenario script: both
    # read this file, so they can never disagree about which log holds
    # the captured OTPs.
    printf '%s\n' "${otp_log}" > "${DEMO_STATE_DIR}/otp-log.path"
    local deadline=$(( SECONDS + 20 ))
    while [ "${SECONDS}" -lt "${deadline}" ]; do
        if python3 -c "import socket,sys; s=socket.socket(); s.settimeout(1); s.connect(('127.0.0.1',${MFA_SMTP_PORT})); s.close()" 2>/dev/null; then
            log "  the SMTP sink is listening (pid $(process_pid smtp))"
            return 0
        fi
        sleep 1
    done
    fail "the SMTP sink did not start. See ${sink_log}."
}

start_api() {
    log "starting the FastAPI monolith on ${APP_HOST}:${APP_PORT}"
    rm -f "$(pid_file api)"

    local api_log
    api_log="$(log_file api)"

    # The environment is assembled explicitly rather than inherited, so a
    # stray variable from the operator's shell cannot silently redirect a
    # bounded context to the wrong database.
    env -i \
        PATH="${PATH}" \
        HOME="${HOME}" \
        PYTHONUNBUFFERED=1 \
        TZ=UTC \
        APP_ENV="${APP_ENV:-development}" \
        POSTGRES_USER="${POSTGRES_USER}" \
        POSTGRES_PASSWORD="${POSTGRES_PASSWORD}" \
        CORE_DB="${CORE_DB}" \
        DETECTION_DB="${DETECTION_DB}" \
        ML_DB="${ML_DB}" \
        CORE_DATABASE_URL="${CORE_DATABASE_URL}" \
        DETECTION_DATABASE_URL="${DETECTION_DATABASE_URL}" \
        ML_DATABASE_URL="${ML_DATABASE_URL}" \
        INTERNAL_SECRET="${INTERNAL_SECRET}" \
        CORE_APP_URL="${CORE_APP_URL}" \
        DETECTION_URL="${DETECTION_URL}" \
        REDIS_URL="${REDIS_URL:-redis://localhost:${REDIS_PORT}/0}" \
        FORWARDED_ALLOW_IPS="${FORWARDED_ALLOW_IPS:-127.0.0.1}" \
        ${CORS_ALLOWED_ORIGINS:+CORS_ALLOWED_ORIGINS="${CORS_ALLOWED_ORIGINS}"} \
        RUN_PRE_TOKEN_CHECK="${RUN_PRE_TOKEN_CHECK:-1}" \
        RUN_LOGIN_EVENT_DELIVERY="${RUN_LOGIN_EVENT_DELIVERY:-1}" \
        ${ML_MODEL_PATH:+ML_MODEL_PATH="${ML_MODEL_PATH}"} \
        MFA_SMTP_HOST="${MFA_SMTP_HOST:-127.0.0.1}" \
        MFA_SMTP_PORT="${MFA_SMTP_PORT}" \
        nohup python3 -m uvicorn app.main:app \
            --host "${APP_HOST}" --port "${APP_PORT}" \
            >> "${api_log}" 2>&1 &
    echo $! > "$(pid_file api)"
    log "  the API was started (pid $(process_pid api)), logging to ${api_log}"
}

wait_for_api() {
    log "waiting for the API to become ready"
    local deadline=$(( SECONDS + APP_READY_TIMEOUT ))
    while [ "${SECONDS}" -lt "${deadline}" ]; do
        if curl -fsS "http://${APP_HOST}:${APP_PORT}/health" >/dev/null 2>&1; then
            log "  the API is answering"
            return 0
        fi
        sleep 1
    done
    fail "the API did not become ready within ${APP_READY_TIMEOUT} seconds. See $(log_file api)."
}

start_frontend() {
    log "starting the Vite dev server on 127.0.0.1:${VITE_DEV_PORT}"
    rm -f "$(pid_file web)"

    local web_log
    web_log="$(log_file web)"

    # The frontend reads its own configuration from the environment.  The
    # demo stack supports BOTH development modes the repository documents:
    #
    #   proxy  — VITE_API_BASE_URL is empty, so the browser makes a
    #            same-origin request and Vite proxies /api to the API.
    #   direct — VITE_API_BASE_URL points at the API, so the browser makes
    #            a cross-origin request and CORS applies.
    #
    # The mode is chosen by DEMO_API_MODE.  The proxy mode is the default
    # because it is the mode the repository recommends and it needs no
    # CORS configuration.
    local api_base_url=""
    if [ "${DEMO_API_MODE:-proxy}" = "direct" ]; then
        api_base_url="http://${APP_HOST}:${APP_PORT}"
        log "  the frontend runs in DIRECT-CORS mode (VITE_API_BASE_URL=${api_base_url})"
    else
        log "  the frontend runs in PROXY mode (the browser makes a same-origin request)"
    fi

    # Vite is started DIRECTLY rather than through ``npm run dev``.
    #
    # ``npm run dev`` adds a wrapper process between the script and Vite:
    # killing the wrapper leaves the Vite server running as an orphan, so
    # the next ``start`` would fail with a port conflict and ``stop`` would
    # not really stop anything.  Starting the binary directly makes the
    # recorded PID the PID of the server that actually holds the port.
    #
    # The process runs in its own session (``setsid``) so that the whole
    # process group can be signalled when the stack stops.
    (
        cd frontend || exit 1
        env -i \
            PATH="${PATH}" \
            HOME="${HOME}" \
            VITE_DEV_PORT="${VITE_DEV_PORT}" \
            VITE_DEV_API_TARGET="http://${APP_HOST}:${APP_PORT}" \
            VITE_API_BASE_URL="${api_base_url}" \
            setsid ./node_modules/.bin/vite \
                --host 127.0.0.1 --port "${VITE_DEV_PORT}" \
                >> "${web_log}" 2>&1 &
        echo $! > "$(pid_file web)"
    )
    log "  the frontend was started (pid $(process_pid web))"
}

wait_for_frontend() {
    log "waiting for the frontend to become ready"
    local deadline=$(( SECONDS + FRONTEND_READY_TIMEOUT ))
    while [ "${SECONDS}" -lt "${deadline}" ]; do
        if curl -fsS "http://127.0.0.1:${VITE_DEV_PORT}/" >/dev/null 2>&1; then
            log "  the frontend is serving"
            return 0
        fi
        sleep 1
    done
    fail "the frontend did not become ready within ${FRONTEND_READY_TIMEOUT} seconds. See $(log_file web)."
}

stop_process() {
    local name="$1"
    local pid
    pid="$(process_pid "${name}")"
    if [ -z "${pid}" ]; then
        return 0
    fi
    if kill -0 "${pid}" 2>/dev/null; then
        log "stopping ${name} (pid ${pid})"
        # The process was started in its own session, so the negative PID
        # signals the WHOLE process group.  That reaches a child that
        # forked away from the recorded PID (Vite's esbuild worker, for
        # example), which a plain ``kill`` would leave behind.
        kill -TERM -- "-${pid}" 2>/dev/null || kill "${pid}" 2>/dev/null || true
        local deadline=$(( SECONDS + 15 ))
        while kill -0 "${pid}" 2>/dev/null && [ "${SECONDS}" -lt "${deadline}" ]; do
            sleep 1
        done
        if kill -0 "${pid}" 2>/dev/null; then
            kill -KILL -- "-${pid}" 2>/dev/null || kill -9 "${pid}" 2>/dev/null || true
        fi
    fi
    rm -f "$(pid_file "${name}")"
}

stop_all_processes() {
    stop_process web
    stop_process api
    stop_process smtp
}

# -----------------------------------------------------------------------------
# Subcommands
# -----------------------------------------------------------------------------
cmd_start() {
    load_env
    validate_config

    # The port check runs BEFORE anything is started, so a conflict never
    # leaves a half-started stack behind.
    check_ports_free

    stage_schemas
    start_infra
    wait_for_infra
    verify_topology

    start_smtp_sink
    start_api
    wait_for_api
    start_frontend
    wait_for_frontend

    log ""
    log "the demo stack is up:"
    log "  frontend  : http://127.0.0.1:${VITE_DEV_PORT}"
    log "  API       : http://${APP_HOST}:${APP_PORT}"
    log "  readiness : http://${APP_HOST}:${APP_PORT}/ready"
    log "  liveness  : http://${APP_HOST}:${APP_PORT}/health"
    log "  logs      : ${DEMO_STATE_DIR}"
    log ""
    log "seed the demo fixtures with: scripts/demo_seed_demo.py --seed"
    log "run the demo scenarios with:   scripts/demo_scenarios.py --all"
}

cmd_stop() {
    load_env
    stop_all_processes
    log "stopping the infrastructure (the demo volumes are KEPT)"
    compose_down
    log "the demo stack is stopped; the demo volumes are intact"
}

cmd_restart() {
    load_env
    validate_config
    stop_all_processes
    log "restarting the stack (the data must survive)"
    stage_schemas
    start_infra
    wait_for_infra
    verify_topology
    start_smtp_sink
    start_api
    wait_for_api
    start_frontend
    wait_for_frontend
    log "the demo stack was restarted"
}

cmd_reset() {
    load_env
    warn "RESET destroys the demo volumes: every row in the three demo databases is deleted."
    warn "This cannot be undone."
    printf 'Type "reset" to continue: '
    local answer
    read -r answer
    if [ "${answer}" != "reset" ]; then
        log "aborted - nothing was destroyed"
        return 0
    fi
    stop_all_processes
    log "destroying the demo volumes"
    compose_down -v
    log "the demo volumes are destroyed; the next 'start' rebuilds the canonical schemas"
}

cmd_status() {
    load_env

    log "infrastructure:"
    compose_ps

    local component label
    for component in smtp api web; do
        case "${component}" in
            smtp) label="SMTP sink " ;;
            api)  label="API       " ;;
            web)  label="frontend  " ;;
        esac
        if is_running "${component}"; then
            log "${label}: running (pid $(process_pid "${component}"))"
        else
            log "${label}: not running"
        fi
    done

    echo
    log "dependency state:"
    local ready
    ready="$(curl -fsS "http://${APP_HOST}:${APP_PORT}/ready" 2>/dev/null || echo "")"
    if [ -z "${ready}" ]; then
        warn "  the API is not answering - the readiness state is unknown"
    else
        printf '%s\n' "${ready}" | python3 -c "
import json, sys
try:
    payload = json.load(sys.stdin)
except Exception:
    print('  the readiness payload could not be parsed')
    raise SystemExit(0)
checks = payload.get('checks') or {}
for name in ('core', 'detection', 'ml', 'ml_artifact'):
    entry = checks.get(name)
    if isinstance(entry, dict):
        detail = entry.get('detail')
        state = entry.get('status', 'unknown')
        print(f'  {name:<12} {state}' + (f'  ({detail})' if detail else ''))
print(f\"  overall      {payload.get('status', 'unknown')}  degraded={payload.get('degraded')}\")
"
    fi
}

cmd_logs() {
    load_env
    echo "--- api ---"
    tail -n 100 -f "$(log_file api)" 2>/dev/null || echo "no API log"
}

cmd_logs_all() {
    load_env
    for component in api smtp web; do
        echo "--- ${component} ---"
        tail -n 50 "$(log_file "${component}")" 2>/dev/null || echo "no ${component} log"
    done
}

cmd_verify() {
    load_env
    validate_config
    log "running the demo acceptance checks"

    # The acceptance checks are the demo SCENARIOS: they drive the demo
    # stack's own API over HTTP and read the demo stack's own databases.
    #
    # They are exported into the environment here, because the scenario
    # script reads the shell — and a shell that still carries another
    # stack's variables would otherwise send the checks to the WRONG
    # stack.  `CORE_APP_URL` is the authority for the API address, so the
    # checks can never drift onto a hard-coded port.
    CORE_APP_URL="${CORE_APP_URL:-http://${APP_HOST}:${APP_PORT}}"
    export CORE_APP_URL
    export CORE_DATABASE_URL DETECTION_DATABASE_URL ML_DATABASE_URL
    export DEMO_API_BASE_URL="${CORE_APP_URL}"

    python3 scripts/demo_scenarios.py --all
}

usage() {
    cat <<'EOF'
usage: scripts/demo_stack.sh <command>

  start     start the infrastructure, the SMTP sink, the API and the frontend
  stop      stop everything (the demo volumes are KEPT)
  restart   stop and start again (the data must survive)
  status    show what is running and the real state of Core, Detection and ML
  verify    run the demo acceptance checks (the demo scenarios)
  logs      tail the API log
  logs-all  show the tail of every component log
  reset     stop and DESTROY the demo volumes (deletes all demo data - asks first)

The demo stack reads `.env.demo`; `scripts/deploy_local.sh` keeps reading
`.env`.  The two deployments have their own ports and their own databases.
EOF
}

main() {
    local command="${1:-}"
    case "${command}" in
        start)    cmd_start ;;
        stop)     load_env; cmd_stop ;;
        restart)  cmd_restart ;;
        reset)    cmd_reset ;;
        status)   cmd_status ;;
        verify)   cmd_verify ;;
        logs)     cmd_logs ;;
        logs-all) cmd_logs_all ;;
        ""|help|-h|--help) usage ;;
        *) usage; fail "unknown command '${command}'" ;;
    esac
}

main "$@"
