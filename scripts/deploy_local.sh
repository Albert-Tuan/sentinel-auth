#!/usr/bin/env bash
# Sentinel Auth v3.3 — reproducible local/demo deployment.
#
# One command brings up a complete, verifiable local deployment:
#
#   scripts/deploy_local.sh up        # infra + app, then verify
#   scripts/deploy_local.sh status    # what is running right now
#   scripts/deploy_local.sh verify    # run the deployment smoke checks
#   scripts/deploy_local.sh down      # stop, KEEP the database volume
#   scripts/deploy_local.sh reset     # stop and DESTROY the volume
#   scripts/deploy_local.sh logs      # tail the application log
#
# "up" is idempotent: it validates the configuration first, starts the
# infrastructure, waits for it to become healthy, starts the FastAPI
# monolith against it, and then runs the deployment verification.  A
# failure at any step stops the sequence and reports which step failed.
#
# The script never deletes data.  Only the explicit "reset" subcommand
# destroys the PostgreSQL volume, and it prints a warning before doing so.
#
# Secrets
# -------
# The internal shared secret is read from ``INTERNAL_SECRET`` in the
# environment or from the ``.env`` file.  When neither provides a usable
# value, the script generates a throwaway one for this run and reports
# that it did so - it is never written to a tracked file and never
# printed.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------
: "${COMPOSE_CMD:=docker compose}"
: "${APP_HOST:=127.0.0.1}"
: "${APP_PORT:=8000}"
: "${LOG_FILE:=${REPO_ROOT}/.ci/deploy-app.log}"
: "${APP_READY_TIMEOUT:=90}"

log()  { printf '\033[1m[deploy]\033[0m %s\n' "$*"; }
warn() { printf '\033[33m[deploy]\033[0m %s\n' "$*" >&2; }
fail() { printf '\033[31m[deploy] ERROR:\033[0m %s\n' "$*" >&2; exit 1; }

# The compose command must be a single word or a path plus arguments.
read -r -a COMPOSE <<< "${COMPOSE_CMD}"

compose() { "${COMPOSE[@]}" "$@"; }

# -----------------------------------------------------------------------------
# Environment loading
#
# The .env file is read for the values the compose file and the
# application need.  Values already present in the environment win, so an
# operator can override a single variable without editing the file.
# -----------------------------------------------------------------------------
load_env() {
    if [ -f ".env" ]; then
        log "loading .env"
        set -a
        # shellcheck disable=SC1091
        . ./.env
        set +a
    else
        warn ".env not found - using environment variables and compose defaults"
    fi
}

require_env() {
    local missing=()
    for name in "$@"; do
        if [ -z "${!name:-}" ]; then
            missing+=("${name}")
        fi
    done
    if [ "${#missing[@]}" -gt 0 ]; then
        fail "missing required environment variable(s): ${missing[*]}. Copy .env.example to .env and fill them in."
    fi
}

# -----------------------------------------------------------------------------
# Configuration validation
#
# Every check here prevents a deployment that starts and then behaves
# incorrectly.  The rules mirror what the application and the PostgreSQL
# container actually enforce, so a failure here is a real misconfiguration
# rather than a stylistic complaint.
# -----------------------------------------------------------------------------
validate_config() {
    log "validating the configuration"

    require_env POSTGRES_USER POSTGRES_PASSWORD \
                CORE_DB DETECTION_DB ML_DB \
                INTERNAL_SECRET CORE_DATABASE_URL DETECTION_DATABASE_URL ML_DATABASE_URL

    # --- the internal secret ---------------------------------------------
    if [ "${#INTERNAL_SECRET}" -lt 32 ]; then
        fail "INTERNAL_SECRET is ${#INTERNAL_SECRET} characters; at least 32 are required."
    fi
    case "${INTERNAL_SECRET}" in
        change-me*|changeme*|secret*|password*)
            fail "INTERNAL_SECRET still holds a placeholder value. Generate one with: python3 -c 'import secrets; print(secrets.token_urlsafe(32))'"
            ;;
    esac

    # --- the three bounded contexts must be three DIFFERENT databases ---
    local core_db detection_db ml_db
    core_db="$(database_name_of "${CORE_DATABASE_URL}")"
    detection_db="$(database_name_of "${DETECTION_DATABASE_URL}")"
    ml_db="$(database_name_of "${ML_DATABASE_URL}")"
    if [ "${core_db}" = "${detection_db}" ] || [ "${core_db}" = "${ml_db}" ] \
       || [ "${detection_db}" = "${ml_db}" ]; then
        fail "the three bounded contexts must use three DIFFERENT databases, but they resolve to: core='${core_db}', detection='${detection_db}', ml='${ml_db}'. Pointing two contexts at one database puts one context's tables in another context's schema."
    fi
    if [ "${core_db}" != "${CORE_DB}" ] || [ "${detection_db}" != "${DETECTION_DB}" ] \
       || [ "${ml_db}" != "${ML_DB}" ]; then
        warn "the URL database names (${core_db}, ${detection_db}, ${ml_db}) differ from the compose database names (${CORE_DB}, ${DETECTION_DB}, ${ML_DB}). The compose names are what the init script creates."
    fi

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
    # CORE_APP_URL and DETECTION_URL address the Detection and Core
    # contexts over HTTP.  In a monolith deployment both are the same
    # process, so both must point at the local server.  Leaving the
    # Detection default (port 8001) in place would silently send every
    # login event and every analytics fetch to a port where nothing
    # listens.
    #
    # The host is compared loosely: "localhost" and "127.0.0.1" are the
    # same machine.  The PORT is compared strictly, because pointing the
    # upstreams at a different port than the server listens on is a real
    # misconfiguration.
    local core_target detection_target
    core_target="$(url_host_of "${CORE_APP_URL:-}")"
    detection_target="$(url_host_of "${DETECTION_URL:-}")"
    if [ -z "${core_target}" ] || [ -z "${detection_target}" ]; then
        fail "CORE_APP_URL and DETECTION_URL must both be set for this monolith deployment (they currently are '${CORE_APP_URL:-<unset>}' and '${DETECTION_URL:-<unset>}')."
    fi
    if [ "${core_target}" != "${detection_target}" ]; then
        fail "CORE_APP_URL and DETECTION_URL must point at the same server in this monolith deployment, but they resolve to '${core_target}' and '${detection_target}'."
    fi
    local core_port detection_port
    core_port="$(url_port_of "${CORE_APP_URL:-}")"
    detection_port="$(url_port_of "${DETECTION_URL:-}")"
    if [ "${core_port}" != "${APP_PORT}" ] || [ "${detection_port}" != "${APP_PORT}" ]; then
        fail "CORE_APP_URL and DETECTION_URL must use the application's port (${APP_PORT}), but they use '${core_port}' and '${detection_port}'. The monolith serves Core, Detection and ML from one process."
    fi

    # --- the trusted proxy list ------------------------------------------
    if [ "${FORWARDED_ALLOW_IPS:-}" = "*" ]; then
        fail "FORWARDED_ALLOW_IPS='*' is forbidden: any remote client could forge X-Forwarded-For and bypass IP-based controls."
    fi

    # --- the CORS allow-list ----------------------------------------------
    # A wildcard origin combined with credentialed requests lets any website
    # read authenticated responses, so it is refused here as well as in the
    # application.  Every entry must be a full origin.
    if [ -n "${CORS_ALLOWED_ORIGINS:-}" ]; then
        local entry
        for entry in $(printf '%s' "${CORS_ALLOWED_ORIGINS}" | tr ',' ' '); do
            entry="$(printf '%s' "${entry}" | tr -d '[:space:]')"
            [ -n "${entry}" ] || continue
            if [ "${entry}" = "*" ]; then
                fail "CORS_ALLOWED_ORIGINS must not contain '*': a wildcard origin lets any website read authenticated responses. List the exact origins instead."
            fi
            case "${entry}" in
                http://*|https://*) ;;
                *) fail "CORS_ALLOWED_ORIGINS entry '${entry}' is not a full origin. Use scheme://host[:port]." ;;
            esac
            case "${entry}" in
                */*/*) fail "CORS_ALLOWED_ORIGINS entry '${entry}' must be an origin without a path." ;;
            esac
        done
    fi

    # --- the ML artifact --------------------------------------------------
    # The ML registry ships a *staged* placeholder whose file does not
    # exist.  The application must not promote it to production; the
    # deployment reports the artifact state instead of silently scoring
    # with nothing.
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
    # A URL without an explicit port uses the scheme's default.
    if [ "${port}" = "${url}" ] || [ -z "${port}" ]; then
        case "${url}" in
            https://*) port=443 ;;
            *)       port=80 ;;
        esac
    fi
    printf '%s' "${port}"
}

# -----------------------------------------------------------------------------
# Infrastructure
# -----------------------------------------------------------------------------
start_infra() {
    log "starting the infrastructure (PostgreSQL + Redis)"
    compose up -d
}

wait_for_infra() {
    log "waiting for PostgreSQL to become healthy"
    local deadline=$(( SECONDS + 90 ))
    while [ "${SECONDS}" -lt "${deadline}" ]; do
        if compose exec -T postgres pg_isready -U "${POSTGRES_USER}" -d postgres >/dev/null 2>&1; then
            log "PostgreSQL is accepting connections"
            return 0
        fi
        sleep 2
    done
    fail "PostgreSQL did not become ready within 90 seconds. Run 'scripts/deploy_local.sh logs' to see why."
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
            fail "the database '${name}' does not exist. The init script only runs when the volume is first created - run 'scripts/deploy_local.sh reset' to rebuild it from the canonical schemas."
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

# Run a read-only query inside the PostgreSQL container.
psql_in() {
    local db="$1"
    local sql="$2"
    compose exec -T -e PGPASSWORD="${POSTGRES_PASSWORD}" postgres \
        psql -v ON_ERROR_STOP=1 -U "${POSTGRES_USER}" -d "${db}" -Atc "${sql}" 2>/dev/null \
        || echo ""
}

# -----------------------------------------------------------------------------
# Application
# -----------------------------------------------------------------------------
start_app() {
    log "starting the FastAPI monolith on ${APP_HOST}:${APP_PORT}"
    mkdir -p "$(dirname "${LOG_FILE}")"

    # A stale PID file from a killed run would block a clean start.
    rm -f "${REPO_ROOT}/.ci/deploy-app.pid"

    # The environment for the application is assembled explicitly rather
    # than inherited, so a stray variable from the operator's shell cannot
    # silently redirect a bounded context to the wrong database.
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
        REDIS_URL="${REDIS_URL:-redis://localhost:6379/0}" \
        FORWARDED_ALLOW_IPS="${FORWARDED_ALLOW_IPS:-127.0.0.1}" \
        ${CORS_ALLOWED_ORIGINS:+CORS_ALLOWED_ORIGINS="${CORS_ALLOWED_ORIGINS}"} \
        RUN_PRE_TOKEN_CHECK="${RUN_PRE_TOKEN_CHECK:-0}" \
        RUN_LOGIN_EVENT_DELIVERY="${RUN_LOGIN_EVENT_DELIVERY:-1}" \
        ${ML_MODEL_PATH:+ML_MODEL_PATH="${ML_MODEL_PATH}"} \
        nohup python3 -m uvicorn app.main:app \
            --host "${APP_HOST}" --port "${APP_PORT}" \
            >> "${LOG_FILE}" 2>&1 &
    echo $! > "${REPO_ROOT}/.ci/deploy-app.pid"
    log "the application was started (pid $(cat "${REPO_ROOT}/.ci/deploy-app.pid")), logging to ${LOG_FILE}"
}

wait_for_app() {
    log "waiting for the application to become ready"
    local deadline=$(( SECONDS + APP_READY_TIMEOUT ))
    while [ "${SECONDS}" -lt "${deadline}" ]; do
        if curl -fsS "http://${APP_HOST}:${APP_PORT}/ready" >/dev/null 2>&1; then
            log "the application is ready"
            return 0
        fi
        sleep 1
    done
    fail "the application did not become ready within ${APP_READY_TIMEOUT} seconds. See ${LOG_FILE}."
}

stop_app() {
    local pid_file="${REPO_ROOT}/.ci/deploy-app.pid"
    if [ -f "${pid_file}" ]; then
        local pid
        pid="$(cat "${pid_file}")"
        if kill -0 "${pid}" 2>/dev/null; then
            log "stopping the application (pid ${pid})"
            kill "${pid}" 2>/dev/null || true
            local deadline=$(( SECONDS + 15 ))
            while kill -0 "${pid}" 2>/dev/null && [ "${SECONDS}" -lt "${deadline}" ]; do
                sleep 1
            done
            kill -9 "${pid}" 2>/dev/null || true
        fi
        rm -f "${pid_file}"
    fi
}

# -----------------------------------------------------------------------------
# Subcommands
# -----------------------------------------------------------------------------
cmd_up() {
    load_env
    validate_config
    start_infra
    wait_for_infra
    verify_topology
    start_app
    wait_for_app
    log ""
    log "the deployment is up:"
    log "  application : http://${APP_HOST}:${APP_PORT}"
    log "  liveness    : http://${APP_HOST}:${APP_PORT}/health"
    log "  readiness   : http://${APP_HOST}:${APP_PORT}/ready"
    log "  logs        : ${LOG_FILE}"
    log ""
    log "run 'scripts/deploy_local.sh verify' for the deployment checks."
}

cmd_down() {
    stop_app
    log "stopping the infrastructure (the database volume is KEPT)"
    compose down
    log "the deployment is stopped; the database volume is intact"
}

cmd_reset() {
    warn "RESET destroys the PostgreSQL volume: every row in all three databases is deleted."
    warn "This cannot be undone."
    printf 'Type "reset" to continue: '
    local answer
    read -r answer
    if [ "${answer}" != "reset" ]; then
        log "aborted - nothing was destroyed"
        return 0
    fi
    stop_app
    log "destroying the volumes"
    compose down -v
    log "the volumes are destroyed; the next 'up' rebuilds the canonical schemas"
}

cmd_status() {
    log "infrastructure:"
    compose ps || true
    local pid_file="${REPO_ROOT}/.ci/deploy-app.pid"
    if [ -f "${pid_file}" ] && kill -0 "$(cat "${pid_file}")" 2>/dev/null; then
        log "application: running (pid $(cat "${pid_file}")) on http://${APP_HOST}:${APP_PORT}"
    else
        log "application: not running"
    fi
}

cmd_logs() {
    [ -f "${LOG_FILE}" ] || fail "no log file at ${LOG_FILE}"
    tail -n 200 -f "${LOG_FILE}"
}

cmd_verify() {
    load_env
    validate_config
    log "running the deployment verification"
    python3 scripts/deploy_verify.py
}

usage() {
    cat <<'EOF'
usage: scripts/deploy_local.sh <command>

  up       start the infrastructure and the application, then verify
  status   show what is running
  verify   run the deployment smoke checks against the running deployment
  down     stop the application and the infrastructure (the volume is kept)
  reset    stop and DESTROY the volume (deletes all data - asks first)
  logs     tail the application log
EOF
}

main() {
    local command="${1:-}"
    case "${command}" in
        up)      cmd_up ;;
        down)    load_env; cmd_down ;;
        reset)   load_env; cmd_reset ;;
        status)  load_env; cmd_status ;;
        verify)  cmd_verify ;;
        logs)    load_env; cmd_logs ;;
        ""|help|-h|--help) usage ;;
        *) usage; fail "unknown command '${command}'" ;;
    esac
}

main "$@"
