#!/usr/bin/env bash
# Sentinel Auth v3.3 — local simulation of the GitHub Actions CI workflow.
#
# This script mirrors .github/workflows/ci.yml step by step against a local
# PostgreSQL cluster, so the pipeline can be verified without pushing to
# GitHub.  It is a *development* helper and is not executed by the workflow.
#
# Usage:
#   scripts/ci_local_simulation.sh <pg-port> <pg-superuser-password>
#
# The caller is responsible for a running PostgreSQL server that accepts
# password authentication for the ``sentinel`` superuser.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

PORT="${1:-5444}"
PASSWORD="${2:-sentinel_ci_disposable}"

log() { printf '\n=== %s ===\n' "$*"; }

export POSTGRES_HOST=127.0.0.1
export POSTGRES_PORT="${PORT}"
export POSTGRES_USER=sentinel
export POSTGRES_PASSWORD="${PASSWORD}"
# libpq reads the password from ``PGPASSWORD``; without it the ``psql``
# calls in the diagnostics and teardown steps fail with "no password
# supplied" and, because they tolerate failures, the teardown would report
# success while dropping nothing.
export PGPASSWORD="${PASSWORD}"
export CORE_DB=sentinel_core_test
export DETECTION_DB=sentinel_detection_test
export ML_DB=sentinel_ml_test
export POSTGRES_DB=sentinel_legacy_test
export TZ=UTC
export PYTHONHASHSEED=0

# Step 3: generate the test-only internal secret (masked, never committed).
CI_INTERNAL_SECRET="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
[ "${#CI_INTERNAL_SECRET}" -ge 32 ] || {
    echo "the generated internal secret is too short" >&2
    exit 1
}

log "Step 3/9: generate the test-only internal secret"
echo "generated a ${#CI_INTERNAL_SECRET}-character secret (value withheld)"

log "Step 4/9: install the dependencies"
python -m pip install --dry-run -r requirements.txt >/dev/null 2>&1 \
    && echo "requirements.txt resolves cleanly" \
    || echo "NOTE: pip --dry-run could not resolve offline; the installed env is used as-is"
# Only a conflict that involves one of OUR declared distributions is a CI
# failure; the hosted runner ships pre-installed packages whose own
# dependencies may be broken.
python -m pip check > /tmp/pip-check.txt 2>&1 || true
if grep -E '^(fastapi|uvicorn|httpx|pydantic|sqlalchemy|psycopg|psycopg2|psycopg2-binary|argon2-cffi|pytest|pytest-asyncio|joblib|numpy|scikit-learn) ' /tmp/pip-check.txt; then
    echo "a declared dependency of this repository is broken" >&2
    exit 1
fi
echo "the declared dependency tree is consistent"

log "Step 5/9: verify the PostgreSQL service is reachable"
for attempt in $(seq 1 30); do
    if pg_isready -h "${POSTGRES_HOST}" -p "${POSTGRES_PORT}" -U "${POSTGRES_USER}" >/dev/null 2>&1; then
        echo "PostgreSQL is ready"
        break
    fi
    if [ "${attempt}" -eq 30 ]; then
        echo "PostgreSQL did not become ready" >&2
        exit 1
    fi
    sleep 2
done

log "Step 6/9: provision the disposable databases"
bash scripts/ci_bootstrap_postgres.sh

log "Step 7/9: export the disposable connection URLs"
export CORE_DETECTION_TEST_URL="postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@${POSTGRES_HOST}:${POSTGRES_PORT}/${CORE_DB}"
export CORE_ANALYTICS_TEST_URL="${CORE_DETECTION_TEST_URL}"
export DETECTION_TEST_URL="postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@${POSTGRES_HOST}:${POSTGRES_PORT}/${DETECTION_DB}"
export ML_TEST_URL="postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@${POSTGRES_HOST}:${POSTGRES_PORT}/${ML_DB}"
echo "exported (credentials withheld)"

# The pytest step deliberately does NOT receive INTERNAL_SECRET: the suite's
# own conftest installs its session-scoped secret, and an ambient value would
# override it and break the internal-auth assertions.
unset INTERNAL_SECRET CORE_APP_URL DETECTION_URL ML_MODEL_PATH
unset CORE_DATABASE_URL DETECTION_DATABASE_URL ML_DATABASE_URL

log "Step 8/9: run the full pytest suite (zero failures, zero skips)"
python scripts/ci_verify_tests.py

log "Step 9/9: run the M10 real-HTTP smoke script"
INTERNAL_SECRET="${CI_INTERNAL_SECRET}" python scripts/m10_http_smoke.py

log "Step 11/9: collect the failure diagnostics (dry run)"
{
    echo "### Sentinel Auth CI diagnostics"
    echo
    echo "#### Python"
    python --version
    echo
    echo "#### PostgreSQL"
    psql -h "${POSTGRES_HOST}" -p "${POSTGRES_PORT}" -U "${POSTGRES_USER}" \
        -d postgres -Atc "SELECT setting FROM pg_settings WHERE name = 'TimeZone';"
    psql -h "${POSTGRES_HOST}" -p "${POSTGRES_PORT}" -U "${POSTGRES_USER}" \
        -d postgres -Atc "SELECT datname FROM pg_database WHERE datistemplate = false ORDER BY 1;"
    echo
    echo "#### pytest summary"
    grep -oE '<testsuite [^>]*' .ci/pytest-report.xml | head -5 || true
} | head -40

log "Step 12/9: tear down the disposable databases"
failed=0
for db_name in "${CORE_DB}" "${DETECTION_DB}" "${ML_DB}" "${POSTGRES_DB}"; do
    case "${db_name}" in
        *_test) ;;
        *) echo "skipping ${db_name}: not a disposable test database"; continue ;;
    esac
    if ! psql -h "${POSTGRES_HOST}" -p "${POSTGRES_PORT}" -U "${POSTGRES_USER}" \
        -d postgres -c "DROP DATABASE IF EXISTS \"${db_name}\";" 2>&1; then
        echo "ERROR: could not drop ${db_name}" >&2
        failed=1
        continue
    fi
    remaining="$(psql -h "${POSTGRES_HOST}" -p "${POSTGRES_PORT}" -U "${POSTGRES_USER}" \
        -d postgres -Atc "SELECT count(*) FROM pg_database WHERE datname = '${db_name}';" 2>&1)"
    if [ "${remaining}" != "0" ]; then
        echo "ERROR: ${db_name} still exists after the drop (count=${remaining})" >&2
        failed=1
    else
        echo "dropped ${db_name}"
    fi
done
if [ "${failed}" -ne 0 ]; then
    echo "the teardown did not drop every disposable database" >&2
    exit 1
fi
echo "the disposable databases were dropped"

log "CI SIMULATION COMPLETE"
