#!/usr/bin/env bash
# Sentinel Auth v3.3 — PostgreSQL database initialization
#
# This script runs automatically on first container start (via docker-entrypoint-initdb.d).
# It creates three logical databases and loads the authoritative schema files.
#
# Databases:
#   sentinel_core       — Core/Auth service tables (13 base tables)
#   sentinel_detection  — Detection Engine tables (7 base tables)
#   sentinel_ml        — ML Service tables (3 base tables + 1 view)
#
# Schemas are loaded in strict order with ON_ERROR_STOP=1 so any failure aborts
# the entire initialization.

set -euo pipefail

# Default values; docker-compose environment variables take precedence.
export CORE_DB="${CORE_DB:-sentinel_core}"
export DETECTION_DB="${DETECTION_DB:-sentinel_detection}"
export ML_DB="${ML_DB:-sentinel_ml}"

# Schema files are mounted from the repository at:
#   /docker-entrypoint-initdb.d/../ (sibling to init directory)
SCHEMA_DIR="/schemas"

echo "[init] Sentinel Auth v3.3 PostgreSQL initialization"
echo "[init] Core DB:      $CORE_DB"
echo "[init] Detection DB: $DETECTION_DB"
echo "[init] ML DB:        $ML_DB"

# -----------------------------------------------------------------------------
# Helper
# -----------------------------------------------------------------------------
run_sql() {
    local db="$1"
    local file="$2"
    echo "[init] Loading $file into $db ..."
    psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$db" -f "$file"
    echo "[init] $file → $db: OK"
}

# -----------------------------------------------------------------------------
# Create databases (createdb is not available inside the init container;
# use CREATE DATABASE via psql template1)
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
echo "[init] =============================================="
echo "[init] All three databases initialized successfully"
echo "[init] sentinel_core       — $(psql -t --username "$POSTGRES_USER" --dbname "$CORE_DB" -c "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'") tables"
echo "[init] sentinel_detection  — $(psql -t --username "$POSTGRES_USER" --dbname "$DETECTION_DB" -c "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'") tables"
echo "[init] sentinel_ml        — $(psql -t --username "$POSTGRES_USER" --dbname "$ML_DB" -c "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'") tables"
echo "[init] =============================================="
