#!/usr/bin/env bash
# Sentinel Auth v3.3 — PostgreSQL database initialization
#
# This script runs automatically on first container start (via docker-entrypoint-initdb.d).
# It creates three logical databases and loads the authoritative schema files.
#
# Databases (default names; overridden by docker-compose environment):
#   sentinel_core       — Core/Auth service tables (13 base tables)
#   sentinel_detection  — Detection Engine tables (7 base tables)
#   sentinel_ml        — ML Service tables (3 base tables + 1 view)
#
# Database names are passed as environment variables from docker-compose.yml:
#   CORE_DB, DETECTION_DB, ML_DB
#
# Schemas are loaded in strict order with ON_ERROR_STOP=1 so any failure aborts
# the entire initialization.

set -euo pipefail

# Default values (docker-compose overrides these via environment).
export CORE_DB="${CORE_DB:-sentinel_core}"
export DETECTION_DB="${DETECTION_DB:-sentinel_detection}"
export ML_DB="${ML_DB:-sentinel_ml}"

# Schema files are mounted from the repository at /schemas (read-only).
SCHEMA_DIR="/schemas"

echo "[init] Sentinel Auth v3.3 PostgreSQL initialization"
echo "[init] Core DB:      $CORE_DB"
echo "[init] Detection DB: $DETECTION_DB"
echo "[init] ML DB:        $ML_DB"
echo "[init] Schema dir:   $SCHEMA_DIR"

# -----------------------------------------------------------------------------
# Helper: run SQL file against a named database with ON_ERROR_STOP=1
# -----------------------------------------------------------------------------
run_sql() {
    local db="$1"
    local file="$2"
    echo "[init] Loading $file into $db ..."
    psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$db" -f "$file"
    echo "[init] $file → $db: OK"
}

# -----------------------------------------------------------------------------
# Helper: create database if it does not exist
# -----------------------------------------------------------------------------
create_db_if_missing() {
    local db="$1"
    if psql -t --username "$POSTGRES_USER" --dbname postgres -c \
        "SELECT 1 FROM pg_database WHERE datname = '$db'" | grep -q 1; then
        echo "[init] Database '$db' already exists — skipping CREATE DATABASE"
    else
        echo "[init] Creating database: $db"
        psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres \
            -c "CREATE DATABASE \"$db\""
        echo "[init] Database '$db' created"
    fi
}

# -----------------------------------------------------------------------------
# Helper: count base tables in a database (excludes views)
# -----------------------------------------------------------------------------
count_base_tables() {
    local db="$1"
    psql -t --username "$POSTGRES_USER" --dbname "$db" -c \
        "SELECT count(*)::int FROM information_schema.tables \
         WHERE table_schema = 'public' AND table_type = 'BASE TABLE'" \
        | tr -d '[:space:]'
}

# -----------------------------------------------------------------------------
# Helper: count views in a database
# -----------------------------------------------------------------------------
count_views() {
    local db="$1"
    psql -t --username "$POSTGRES_USER" --dbname "$db" -c \
        "SELECT count(*)::int FROM information_schema.views \
         WHERE table_schema = 'public'" \
        | tr -d '[:space:]'
}

# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------
create_db_if_missing "$CORE_DB"
create_db_if_missing "$DETECTION_DB"
create_db_if_missing "$ML_DB"

echo ""
echo "[init] Loading schemas..."

run_sql "$CORE_DB"      "$SCHEMA_DIR/schema-core-v3.3.sql"
run_sql "$DETECTION_DB" "$SCHEMA_DIR/schema-detection-v3.3.sql"
run_sql "$ML_DB"       "$SCHEMA_DIR/schema-ml-service-v3.3.sql"

echo ""
echo "[init] Verification summary"
echo "[init] ====================="

core_tables=$(count_base_tables "$CORE_DB")
detection_tables=$(count_base_tables "$DETECTION_DB")
ml_tables=$(count_base_tables "$ML_DB")
ml_views=$(count_views "$ML_DB")

echo "[init] sentinel_core:       $core_tables base tables (expected 13)"
echo "[init] sentinel_detection:  $detection_tables base tables (expected 7)"
echo "[init] sentinel_ml:        $ml_tables base tables (expected 3)"
echo "[init] sentinel_ml views:  $ml_views (expected 1 — local_ml_stats)"

if [[ "$core_tables" -eq 13 ]] && \
   [[ "$detection_tables" -eq 7 ]] && \
   [[ "$ml_tables" -eq 3 ]] && \
   [[ "$ml_views" -ge 1 ]]; then
    echo "[init] ====================="
    echo "[init] All three databases initialized successfully"
else
    echo "[init] ====================="
    echo "[init] WARNING: Table/view counts do not match expected values"
    echo "[init] Verify schema files and initialization manually"
fi
