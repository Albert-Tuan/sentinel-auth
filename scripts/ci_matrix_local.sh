#!/usr/bin/env bash
# Local reproduction of the GitHub Actions CI matrix (Python 3.11 / 3.12)
# against the disposable PostgreSQL 16 container.
#
# Usage: scripts/ci_matrix_local.sh 3.11
set -euo pipefail

PYVER="${1:?usage: ci_matrix_local.sh <python-version>}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# NOTE: the variable is deliberately NOT called ``PGPORT``: libpq reads
# ``PGPORT`` from the environment, and a developer's shell often has it set
# to an unrelated server.  Reusing it would silently point the whole run at
# the wrong PostgreSQL.
CI_PGPORT="${CI_PGPORT:-55432}"
PGUSER="sentinel"
PGPASS="sentinel_ci_disposable"
IMAGE="docker.io/library/python:${PYVER}-slim"

echo "=== CI matrix job: Python ${PYVER} (PostgreSQL on 127.0.0.1:${CI_PGPORT}) ==="

podman run --rm --network host \
    -v "${REPO_ROOT}:/work" -w /work \
    -e TZ=UTC -e PYTHONHASHSEED=0 \
    -e POSTGRES_HOST=127.0.0.1 -e POSTGRES_PORT="${CI_PGPORT}" \
    -e POSTGRES_USER="${PGUSER}" -e POSTGRES_PASSWORD="${PGPASS}" \
    -e PGPASSWORD="${PGPASS}" \
    -e PGHOST=127.0.0.1 -e PGPORT="${CI_PGPORT}" \
    -e PGUSER="${PGUSER}" \
    -e CORE_DETECTION_TEST_URL="postgresql://${PGUSER}:${PGPASS}@127.0.0.1:${CI_PGPORT}/sentinel_core_test" \
    -e CORE_ANALYTICS_TEST_URL="postgresql://${PGUSER}:${PGPASS}@127.0.0.1:${CI_PGPORT}/sentinel_core_test" \
    -e DETECTION_TEST_URL="postgresql://${PGUSER}:${PGPASS}@127.0.0.1:${CI_PGPORT}/sentinel_detection_test" \
    -e ML_TEST_URL="postgresql://${PGUSER}:${PGPASS}@127.0.0.1:${CI_PGPORT}/sentinel_ml_test" \
    -e POSTGRES_DB=sentinel_legacy_test \
    "${IMAGE}" \
    bash -c "set -euo pipefail
        apt-get update -qq >/dev/null 2>&1
        apt-get install -y -qq --no-install-recommends libpq-dev gcc >/dev/null 2>&1
        python -m pip install --upgrade pip >/dev/null
        python -m pip install -r requirements.txt >/dev/null
        python --version
        python scripts/ci_verify_tests.py
        secret=\"\$(python -c 'import secrets; print(secrets.token_urlsafe(32))')\"
        INTERNAL_SECRET=\"\${secret}\" python scripts/m10_http_smoke.py
    "
echo "=== Python ${PYVER}: OK ==="
