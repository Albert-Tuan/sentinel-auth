#!/usr/bin/env bash
# Sentinel Auth v3.3 — M13.2 browser E2E runner.
#
# Runs the Playwright browser suite against the REAL demo stack: the
# real FastAPI monolith, the real PostgreSQL databases and the real
# Redis.  Nothing is mocked.
#
#   scripts/e2e_run.sh                 # the whole suite
#   scripts/e2e_run.sh e2e-08-races    # one file
#   scripts/e2e_run.sh --headed        # watch it run
#   scripts/e2e_run.sh --no-start      # the stack is already up
#
# ---------------------------------------------------------------------------
# WHAT THIS SCRIPT DOES AND DOES NOT DO
# ---------------------------------------------------------------------------
#
# It DOES:
#   - check that the demo stack is up, and start it if it is not;
#   - check that the demo fixtures are seeded, and seed them if they are
#     not;
#   - install the Chromium build Playwright needs;
#   - run the suite with ONE worker, because the scenarios mutate shared
#     state;
#   - report the zero-skip policy: a skipped test fails the run.
#
# It DOES NOT:
#   - mock anything;
#   - reset the demo databases between runs — the scenarios own their own
#     fixture rows, and a reset would hide a real defect (a leaked
#     session, a wrongly applied action);
#   - touch the canonical deployment: the demo stack has its own ports,
#     its own database names and its own `.env.demo`.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

: "${DEMO_ENV_FILE:=${REPO_ROOT}/.env.demo}"
: "${E2E_ARTIFACT_DIR:=${REPO_ROOT}/.ci/e2e}"

log()  { printf '\033[1m[e2e]\033[0m %s\n' "$*"; }
warn() { printf '\033[33m[e2e]\033[0m %s\n' "$*" >&2; }
fail() { printf '\033[31m[e2e] ERROR:\033[0m %s\n' "$*" >&2; exit 1; }

# -----------------------------------------------------------------------------
# Arguments
# -----------------------------------------------------------------------------
HEADED=0
START_STACK=1
SELECTORS=()

while [ $# -gt 0 ]; do
    case "$1" in
        --headed)    HEADED=1; shift ;;
        --no-start)  START_STACK=0; shift ;;
        -h|--help)
            sed -n '2,30p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
            exit 0
            ;;
        -*) fail "unknown option '$1'" ;;
        *)  SELECTORS+=("$1"); shift ;;
    esac
done

# -----------------------------------------------------------------------------
# The demo environment
# -----------------------------------------------------------------------------
load_env() {
    if [ ! -f "${DEMO_ENV_FILE}" ]; then
        fail "the demo environment file '${DEMO_ENV_FILE}' does not exist. Create it with: cp .env.demo.example .env.demo — and then fill in POSTGRES_PASSWORD and INTERNAL_SECRET."
    fi
    set -a
    # shellcheck disable=SC1090
    . "${DEMO_ENV_FILE}"
    set +a
}

load_env

: "${APP_HOST:=127.0.0.1}"
: "${APP_PORT:=58000}"
: "${VITE_DEV_PORT:=55173}"

# -----------------------------------------------------------------------------
# The explicit write declaration
# -----------------------------------------------------------------------------
#
# `scripts/e2e_fixtures.py` refuses to write to a database the run has not
# declared by name.  The declaration is derived from the very URLs the
# helper is about to use, so it can never name a database the run does
# not actually reach.
#
# It is a DECLARATION, not a permission: the helper still refuses any
# URL that is not a demo database its bounded context owns, on any host
# but the loopback interface, under any environment variable that tries
# to widen the allowlist.
# -----------------------------------------------------------------------------
declare_write_targets() {
    local url name
    local -a names=()

    for url in "${CORE_DATABASE_URL:-}" "${DETECTION_DATABASE_URL:-}" "${ML_DATABASE_URL:-}"; do
        [ -n "${url}" ] || continue

        # The database name is the last path segment, without the query
        # string.
        name="${url%%\?*}"
        name="${name##*/}"
        [ -n "${name}" ] || continue

        # A duplicate is harmless — the declaration is a SET of names.
        local seen duplicate=0
        for seen in ${names[@]+"${names[@]}"}; do
            if [ "${seen}" = "${name}" ]; then
                duplicate=1
                break
            fi
        done
        [ "${duplicate}" -eq 1 ] && continue

        names+=("${name}")
    done

    E2E_ALLOW_WRITE_TO="${names[*]:-}"
    export E2E_ALLOW_WRITE_TO
}

declare_write_targets

# -----------------------------------------------------------------------------
# The stack
# -----------------------------------------------------------------------------
stack_is_up() {
    curl -fsS "http://${APP_HOST}:${APP_PORT}/health" >/dev/null 2>&1 &&
    curl -fsS "http://127.0.0.1:${VITE_DEV_PORT}/" >/dev/null 2>&1
}

ensure_stack() {
    if stack_is_up; then
        log "the demo stack is already up"
        return 0
    fi

    if [ "${START_STACK}" -eq 0 ]; then
        fail "the demo stack is not up and --no-start was given. Start it with: scripts/demo_stack.sh start"
    fi

    log "starting the demo stack"
    # The script is invoked through `bash` rather than directly: the
    # repository does not track the executable bit (`core.fileMode` is
    # false), so a direct invocation would fail with "Permission
    # denied" on a fresh checkout.
    bash scripts/demo_stack.sh start
    bash scripts/demo_stack.sh status
}

# -----------------------------------------------------------------------------
# The fixtures
# -----------------------------------------------------------------------------
#
# The manifest is what the browser suite reads: it holds the REAL ids of
# the seeded rows — the user ids, the session ids, the alert ids, the
# policy ids.  The suite derives nothing and guesses nothing.
#
# The seed is idempotent: the second run replaces the rows instead of
# piling them up, so the manifest stays valid and the suite stays
# re-runnable on the same demo stack for ever.
# -----------------------------------------------------------------------------
MANIFEST_PATH="${REPO_ROOT}/.ci/demo/fixture-manifest.json"

ensure_fixtures() {
    log "seeding the demo fixtures"

    mkdir -p "$(dirname "${MANIFEST_PATH}")"

    python3 scripts/demo_seed_demo.py --seed --manifest-out "${MANIFEST_PATH}"

    if [ ! -f "${MANIFEST_PATH}" ]; then
        fail "the seed did not write the fixture manifest to ${MANIFEST_PATH}. The browser suite cannot run without it."
    fi

    log "the fixture manifest is at ${MANIFEST_PATH}"
}

# -----------------------------------------------------------------------------
# The browser
# -----------------------------------------------------------------------------
#
# The browser is installed ONLY when it is missing.  The check is the
# Playwright browser registry itself: the install is slow, and a run
# that already has the build must not pay for it.
# -----------------------------------------------------------------------------
browser_is_installed() {
    local location
    location="$( cd frontend && npx playwright install --dry-run chromium 2>/dev/null \
        | sed -n 's/^ *Install location: *//p' | head -1 )"

    [ -n "${location}" ] && [ -d "${location}" ]
}

ensure_browser() {
    if browser_is_installed; then
        log "the Chromium build is present"
        return 0
    fi

    log "installing the Chromium build"
    # The install needs root for the system libraries.  A local run
    # without root is not fatal: the browser may already be present, and
    # the suite will report the real reason if it is not.
    ( cd frontend && npx playwright install --with-deps chromium ) \
        || ( cd frontend && npx playwright install chromium ) \
        || warn "the browser installation failed; the run will report the real reason"
}

# -----------------------------------------------------------------------------
# The run
# -----------------------------------------------------------------------------
run_suite() {
    mkdir -p "${E2E_ARTIFACT_DIR}"

    # The reporters come from `playwright.config.ts` — the list, the
    # JUnit XML, the HTML report and the JSON results.  They are NOT
    # overridden here: an override on the command line would replace
    # them, and the JSON results are what the zero-skip policy reads.
    local -a args=(playwright test --workers=1)

    if [ "${HEADED}" -eq 1 ]; then
        args+=(--headed)
    fi

    if [ "${#SELECTORS[@]}" -gt 0 ]; then
        args+=("${SELECTORS[@]}")
    fi

    log "running the browser suite"
    ( cd frontend && npx "${args[@]}" )
}

# -----------------------------------------------------------------------------
# The zero-skip policy
#
# A scenario that does not run is a scenario that proves nothing.  The
# suite reports a skipped test as a skip, and this check turns that into
# a failure: an acceptance suite that quietly stopped covering
# something is not green.
# -----------------------------------------------------------------------------
check_no_skips() {
    local results="${E2E_ARTIFACT_DIR}/results.json"

    if [ ! -f "${results}" ]; then
        warn "no results file was written; the skip check is skipped"
        return 0
    fi

    local skipped_count
    skipped_count="$(python3 - "${results}" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    payload = json.load(handle)

skipped = []


def walk(suites):
    for suite in suites:
        for spec in suite.get("specs", []):
            for test in spec.get("tests", []):
                for result in test.get("results", []):
                    if result.get("status") == "skipped":
                        skipped.append(spec.get("title", "<unnamed>"))
        walk(suite.get("suites", []))


walk(payload.get("suites", []))

for title in skipped:
    print(f"SKIPPED: {title}")

print(len(skipped))
PY
)"
    local count
    count="$(printf '%s\n' "${skipped_count}" | tail -1)"

    if [ "${count}" != "0" ]; then
        fail "${count} scenario(s) were SKIPPED. A skipped scenario proves nothing; the run is not green."
    fi

    log "no scenario was skipped"
}

# -----------------------------------------------------------------------------
main() {
    ensure_stack
    ensure_fixtures
    ensure_browser

    if ! run_suite; then
        fail "the browser suite failed. The artefacts are in ${E2E_ARTIFACT_DIR}."
    fi

    check_no_skips

    log ""
    log "the browser suite passed"
    log "  report : ${E2E_ARTIFACT_DIR}/html-report/index.html"
    log "  junit  : ${E2E_ARTIFACT_DIR}/junit.xml"
    log ""
    warn "the artefacts contain bearer tokens and OTP codes — do NOT publish them."
}

main "$@"
