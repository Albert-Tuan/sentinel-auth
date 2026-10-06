"""PostgreSQL integration tests for P0-01 bootstrap fixes.

These tests require a running PostgreSQL 18 instance and verify:
1. All schemas bootstrap cleanly from scratch.
2. All expected tables, indexes, and triggers exist.
3. Seed data is correctly inserted.
4. Partial unique index enforces single-active policy.
5. Partial unique index enforces single-active production model.
6. The trusted-device index does NOT use volatile NOW().

Run with:
    pytest tests/test_postgres_bootstrap.py -v

Requires environment variables or a matching pytest.ini entry:
    POSTGRES_HOST=localhost
    POSTGRES_PORT=5432
    POSTGRES_DB=sentinel_auth
    POSTGRES_USER=sentinel
    POSTGRES_PASSWORD=sentinel123
"""
from __future__ import annotations

import os
import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

POSTGRES_HOST = os.environ.get("POSTGRES_HOST", "localhost")
POSTGRES_PORT = os.environ.get("POSTGRES_PORT", "5432")
POSTGRES_DB = os.environ.get("POSTGRES_DB", "sentinel_auth")
POSTGRES_USER = os.environ.get("POSTGRES_USER", "sentinel")
POSTGRES_PASSWORD = os.environ.get("POSTGRES_PASSWORD", "sentinel123")


def _pg_url() -> str:
    return f"postgresql+psycopg2://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"


# ---------------------------------------------------------------------------
# Schema paths
# ---------------------------------------------------------------------------

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEMA_CORE = os.path.join(REPO_ROOT, "infra", "postgres", "schema-core-v3.3.sql")
SCHEMA_DETECTION = os.path.join(REPO_ROOT, "infra", "postgres", "schema-detection-v3.3.sql")
SCHEMA_ML = os.path.join(REPO_ROOT, "infra", "postgres", "schema-ml-service-v3.3.sql")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def engine():
    """PostgreSQL engine for the module."""
    eng = create_engine(_pg_url(), isolation_level="AUTOCOMMIT")
    yield eng
    eng.dispose()


def _bootstrap_schemas(conn: Connection) -> None:
    """Drop and recreate schema, apply all SQL schemas."""
    conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
    conn.execute(text("CREATE SCHEMA public"))
    for path in (SCHEMA_CORE, SCHEMA_DETECTION, SCHEMA_ML):
        conn.execute(text(open(path).read()))


@pytest.fixture(scope="module")
def bootstrap_done(engine: sa.Engine):
    """Module-scoped: bootstrap the DB once before any test runs."""
    with engine.connect() as conn:
        _bootstrap_schemas(conn)


@pytest.fixture(autouse=True)
def reset_seed_state(engine: sa.Engine, bootstrap_done):
    """Ensure canonical seed state before every test.

    Creates its own connection directly from the engine to avoid
    fixture ordering issues with the autouse+yield db chain.
    """
    with engine.connect() as conn:
        # Safety net: archive any stale active production models
        conn.execute(
            text(
                "UPDATE model_versions SET status = 'archived' "
                "WHERE is_production = TRUE AND status = 'active' "
                "AND version != 'v1.0-isolation-forest'"
            )
        )
        # Safety net: delete all non-seed model versions
        conn.execute(
            text("DELETE FROM model_versions WHERE version != 'v1.0-isolation-forest'")
        )
        # Restore seed model to active production
        conn.execute(
            text(
                "UPDATE model_versions SET status = 'active', is_production = TRUE "
                "WHERE version = 'v1.0-isolation-forest'"
            )
        )
        # Safety net: deactivate any stale active non-seed policies
        conn.execute(
            text(
                "UPDATE policies SET is_active = FALSE "
                "WHERE is_active = TRUE AND version != 'v1.0'"
            )
        )
        # Safety net: delete all non-seed policies
        conn.execute(text("DELETE FROM policies WHERE version != 'v1.0'"))
        # Restore seed policy to active
        conn.execute(
            text("UPDATE policies SET is_active = TRUE WHERE version = 'v1.0'")
        )


@pytest.fixture()
def db(engine: sa.Engine):
    """Return a new raw DBAPI connection per test (auto-commit via AUTOCOMMIT isolation)."""
    with engine.connect() as conn:
        yield conn


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestSchemaBootstrap:
    """Verify all schemas apply cleanly from zero."""

    def test_all_expected_tables_exist(self, db: Connection):
        """All 24 expected tables are present in the public schema."""
        result = db.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public' ORDER BY table_name"
            )
        )
        actual = {row[0] for row in result}
        expected = {
            "alert_timeline", "alerts", "audit_logs", "detection_logs",
            "feature_statistics", "inference_logs", "ip_addresses",
            "login_attempts", "local_ml_stats", "mfa_notifications",
            "mfa_transactions", "model_versions", "outbox_events",
            "policies", "rate_limits", "risk_assessments", "roles",
            "sessions", "soc_analysts", "system_settings",
            "user_notifications", "user_roles", "user_trusted_devices",
            "users",
        }
        assert actual == expected, f"Missing: {expected - actual}  Extra: {actual - expected}"

    def test_policies_has_updated_at(self, db: Connection):
        """policies table has updated_at column (required by trigger)."""
        result = db.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'policies' AND column_name = 'updated_at'"
            )
        )
        assert result.fetchone() is not None, "policies.updated_at is missing"

    def test_all_required_triggers_exist(self, db: Connection):
        """All 9 update_at triggers are created."""
        result = db.execute(
            text(
                "SELECT trigger_name, event_object_table "
                "FROM information_schema.triggers "
                "WHERE trigger_schema = 'public' "
                "AND action_timing = 'BEFORE' AND event_manipulation = 'UPDATE'"
            )
        )
        actual = {(row[0], row[1]) for row in result}
        expected = {
            ("trg_alerts_updated_at", "alerts"),
            ("trg_login_attempts_updated_at", "login_attempts"),
            ("trg_mfa_transactions_updated_at", "mfa_transactions"),
            ("trg_model_versions_updated_at", "model_versions"),
            ("trg_policies_updated_at", "policies"),
            ("trg_sessions_updated_at", "sessions"),
            ("trg_soc_analysts_updated_at", "soc_analysts"),
            ("trg_system_settings_updated_at", "system_settings"),
            ("trg_users_updated_at", "users"),
        }
        assert actual == expected, f"Missing triggers: {expected - actual}"

    def test_seed_data_inserted(self, db: Connection):
        """Seed data is present: 4 roles, 1 policy, 1 model_version."""
        roles = db.execute(text("SELECT count(*) FROM roles")).scalar()
        policies = db.execute(text("SELECT count(*) FROM policies")).scalar()
        models = db.execute(text("SELECT count(*) FROM model_versions")).scalar()
        assert roles == 4, f"Expected 4 roles, got {roles}"
        assert policies == 1, f"Expected 1 policy, got {policies}"
        assert models == 1, f"Expected 1 model_version, got {models}"

    def test_seed_policy_is_active(self, db: Connection):
        """The seeded v1.0 policy is marked is_active = TRUE."""
        row = db.execute(
            text("SELECT version, is_active FROM policies WHERE version = 'v1.0'")
        ).fetchone()
        assert row is not None, "Seed policy v1.0 not found"
        assert row[1] is True, f"Seed policy should be active, got is_active={row[1]}"

    def test_seed_model_is_production_active(self, db: Connection):
        """The seeded model is marked is_production=TRUE and status='active'."""
        row = db.execute(
            text(
                "SELECT version, is_production, status FROM model_versions "
                "WHERE version = 'v1.0-isolation-forest'"
            )
        ).fetchone()
        assert row is not None, "Seed model v1.0-isolation-forest not found"
        assert row[1] is True, f"Seed model should be is_production=TRUE, got {row[1]}"
        assert row[2] == "active", f"Seed model should be status='active', got {row[2]}"


class TestIndexes:
    """Verify index structures."""

    def test_policies_partial_unique_index_exists(self, db: Connection):
        """idx_policies_single_active partial UNIQUE index exists."""
        result = db.execute(
            text(
                "SELECT indexdef FROM pg_indexes "
                "WHERE indexname = 'idx_policies_single_active'"
            )
        ).fetchone()
        assert result is not None, "idx_policies_single_active not found"
        indexdef = result[0]
        assert "UNIQUE" in indexdef, "Index should be UNIQUE"
        assert "((1))" in indexdef, "Index should use constant expression (1)"
        assert "WHERE" in indexdef, "Index should be partial"
        assert "is_active" in indexdef, "Index predicate should reference is_active"

    def test_model_versions_partial_unique_index_exists(self, db: Connection):
        """idx_model_versions_single_active_production partial UNIQUE index exists."""
        result = db.execute(
            text(
                "SELECT indexdef FROM pg_indexes "
                "WHERE indexname = 'idx_model_versions_single_active_production'"
            )
        ).fetchone()
        assert result is not None, "idx_model_versions_single_active_production not found"
        indexdef = result[0]
        assert "UNIQUE" in indexdef, "Index should be UNIQUE"
        assert "((1))" in indexdef, "Index should use constant expression (1)"
        assert "WHERE" in indexdef, "Index should be partial"
        assert "is_production" in indexdef, "Index predicate should reference is_production"
        assert "status" in indexdef, "Index predicate should reference status"

    def test_trusted_device_index_is_not_partial_with_now(self, db: Connection):
        """idx_user_trusted_devices_user_expires is a regular composite index.

        The partial index with NOW() was removed because NOW() is not IMMUTABLE.
        This test confirms the replacement index does NOT contain NOW().
        """
        result = db.execute(
            text(
                "SELECT indexdef FROM pg_indexes "
                "WHERE indexname = 'idx_user_trusted_devices_user_expires'"
            )
        ).fetchone()
        assert result is not None, "idx_user_trusted_devices_user_expires not found"
        indexdef = result[0]
        # Must NOT contain NOW() or volatile function
        assert "NOW()" not in indexdef.upper(), "Index must NOT use volatile NOW()"
        assert "user_id" in indexdef, "Index should cover user_id"
        assert "expires_at" in indexdef, "Index should cover expires_at"


class TestSingleActivePolicyEnforcement:
    """Verify DB-level single-active policy enforcement via partial unique index."""

    def test_sequential_policy_activation_succeeds(self, db: Connection):
        """Sequential deactivate-then-activate flow works without errors."""
        # Deactivate v1.0
        db.execute(text("UPDATE policies SET is_active = FALSE WHERE version = 'v1.0'"))
        count = db.execute(
            text("SELECT count(*) FROM policies WHERE is_active = TRUE")
        ).scalar()
        assert count == 0

        # Activate v1.1 (new row)
        db.execute(
            text(
                "INSERT INTO policies (version, name, description, rules, config, is_active) "
                "VALUES (:v, :n, 't', '[]'::jsonb, '{}'::jsonb, TRUE)"
            ),
            {"v": "v1.1-test-pg", "n": "Test Policy v1.1"},
        )
        count = db.execute(
            text("SELECT count(*) FROM policies WHERE is_active = TRUE")
        ).scalar()
        assert count == 1

        # Deactivate v1.1
        db.execute(text("UPDATE policies SET is_active = FALSE WHERE version = 'v1.1-test-pg'"))
        count = db.execute(
            text("SELECT count(*) FROM policies WHERE is_active = TRUE")
        ).scalar()
        assert count == 0

        # Restore v1.0
        db.execute(text("UPDATE policies SET is_active = TRUE WHERE version = 'v1.0'"))
        count = db.execute(
            text("SELECT count(*) FROM policies WHERE is_active = TRUE")
        ).scalar()
        assert count == 1
        # Cleanup: autouse fixture restores seed on next test; no explicit cleanup needed.

    def test_concurrent_active_policy_insert_fails(self, db: Connection):
        """Attempting to insert a second active policy raises a DB error.

        Note: This is a functional test (not a true concurrency test) that
        demonstrates the partial unique index rejects the conflicting insert.
        True concurrent stress-testing is done separately with concurrent clients.
        """
        # Deactivate v1.0 so there's room to insert one new active policy
        db.execute(text("UPDATE policies SET is_active = FALSE WHERE version = 'v1.0'"))

        # First insert succeeds
        db.execute(
            text(
                "INSERT INTO policies (version, name, description, rules, config, is_active) "
                "VALUES (:v, :n, 't', '[]'::jsonb, '{}'::jsonb, TRUE)"
            ),
            {"v": "v1.2-test-pg", "n": "Test Policy v1.2"},
        )
        count = db.execute(
            text("SELECT count(*) FROM policies WHERE is_active = TRUE")
        ).scalar()
        assert count == 1

        # Second insert fails with unique violation
        with pytest.raises(Exception) as exc_info:
            db.execute(
                text(
                    "INSERT INTO policies (version, name, description, rules, config, is_active) "
                    "VALUES (:v, :n, 't', '[]'::jsonb, '{}'::jsonb, TRUE)"
                ),
                {"v": "v1.3-test-pg", "n": "Test Policy v1.3"},
            )
        assert "idx_policies_single_active" in str(exc_info.value)
        # Cleanup: autouse fixture restores seed on next test; no explicit cleanup needed.


class TestSingleActiveModelEnforcement:
    """Verify DB-level single-active-production model enforcement."""

    def test_sequential_model_activation_succeeds(self, db: Connection):
        """Sequential deactivate-then-activate flow works without errors."""
        # Archive the seeded production model
        db.execute(
            text(
                "UPDATE model_versions SET status = 'archived' "
                "WHERE version = 'v1.0-isolation-forest'"
            )
        )

        # Insert new production model
        db.execute(
            text(
                "INSERT INTO model_versions "
                "(name, version, algorithm, model_path, config, status, is_production) "
                "VALUES (:n, :v, 'TestAlgo', '/tmp/model.joblib', '{}'::jsonb, 'active', TRUE)"
            ),
            {"n": "Test Model", "v": "v1.1-test-pg-ml"},
        )
        count = db.execute(
            text(
                "SELECT count(*) FROM model_versions "
                "WHERE is_production = TRUE AND status = 'active'"
            )
        ).scalar()
        assert count == 1

        # Archive and activate another
        db.execute(
            text(
                "UPDATE model_versions SET status = 'archived' "
                "WHERE version = 'v1.1-test-pg-ml'"
            )
        )
        db.execute(
            text(
                "INSERT INTO model_versions "
                "(name, version, algorithm, model_path, config, status, is_production) "
                "VALUES (:n, :v, 'TestAlgo2', '/tmp/model2.joblib', '{}'::jsonb, 'active', TRUE)"
            ),
            {"n": "Test Model 2", "v": "v1.2-test-pg-ml"},
        )
        count = db.execute(
            text(
                "SELECT count(*) FROM model_versions "
                "WHERE is_production = TRUE AND status = 'active'"
            )
        ).scalar()
        assert count == 1

        # Cleanup: autouse fixture restores seed on next test; no explicit cleanup needed.

    def test_concurrent_active_model_insert_fails(self, db: Connection):
        """Attempting to insert a second active production model raises a DB error."""
        # Ensure seeded model is active
        db.execute(
            text(
                "UPDATE model_versions SET status = 'active', is_production = TRUE "
                "WHERE version = 'v1.0-isolation-forest'"
            )
        )

        # Second insert fails with unique violation
        with pytest.raises(Exception) as exc_info:
            db.execute(
                text(
                    "INSERT INTO model_versions "
                    "(name, version, algorithm, model_path, config, status, is_production) "
                    "VALUES (:n, :v, 'TestAlgo', '/tmp/model.joblib', '{}'::jsonb, 'active', TRUE)"
                ),
                {"n": "Concurrent Model", "v": "v1.3-test-pg-ml"},
            )
        assert "idx_model_versions_single_active_production" in str(exc_info.value)

        # Cleanup: just delete the failed insert attempt (it never succeeded)
        db.execute(
            text("DELETE FROM model_versions WHERE version = 'v1.3-test-pg-ml'")
        )


class TestPostgresSpecificBehaviors:
    """Verify PostgreSQL-specific features work correctly."""

    def test_inet_column_accepts_ip_addresses(self, db: Connection):
        """INET columns accept valid IPv4/IPv6 addresses."""
        # Insert an IP address
        db.execute(
            text(
                "INSERT INTO ip_addresses (ip_address, is_proxy, is_vpn, is_tor) "
                "VALUES ('192.168.1.100'::inet, FALSE, FALSE, FALSE)"
            )
        )
        row = db.execute(
            text("SELECT ip_address FROM ip_addresses WHERE ip_address = '192.168.1.100'::inet")
        ).fetchone()
        assert row is not None

        # Cleanup
        db.execute(text("DELETE FROM ip_addresses WHERE ip_address = '192.168.1.100'::inet"))

    def test_uuid_primary_keys_work(self, db: Connection):
        """UUID primary keys are generated automatically."""
        user_id = db.execute(
            text(
                "INSERT INTO users (username, email, password_hash, status) "
                "VALUES (:u, :e, 'hash', 'active') RETURNING id"
            ),
            {"u": "pgtestuser", "e": "pgtest@example.com"},
        ).scalar()
        assert user_id is not None
        # Verify it's a valid UUID
        uuid.UUID(str(user_id))

        # Cleanup
        db.execute(text("DELETE FROM users WHERE username = 'pgtestuser'"))

    def test_jsonb_columns_store_and_query_json(self, db: Connection):
        """JSONB columns store and filter JSON data correctly."""
        db.execute(
            text(
                "INSERT INTO policies (version, name, description, rules, config, is_active) "
                "VALUES (:v, 'JSONB Test', 't', '{\"test\": true}'::jsonb, '{}'::jsonb, FALSE)"
            ),
            {"v": "v99-jsonb-test"},
        )
        row = db.execute(
            text("SELECT rules FROM policies WHERE version = 'v99-jsonb-test'")
        ).fetchone()
        assert row is not None
        assert row[0] == {"test": True}

        # Cleanup
        db.execute(text("DELETE FROM policies WHERE version = 'v99-jsonb-test'"))
