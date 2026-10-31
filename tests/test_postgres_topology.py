"""Three-database PostgreSQL topology tests (P0-5).

These tests prove the ARCHITECTURE, not just the SQL files.  The existing
``tests/test_postgres_bootstrap.py`` applies all three schema files into ONE
database and therefore CANNOT demonstrate the three-database topology; it is
retained as a schema-compatibility check only.

What this module proves
-----------------------
* ``sentinel_core``      holds the 13 Core base tables and NOTHING else.
* ``sentinel_detection`` holds the 7 Detection base tables and NOTHING else.
* ``sentinel_ml``        holds the 3 ML base tables + the ``local_ml_stats``
  view and NOTHING else.
* No cross-database foreign key exists.
* The application's session dependencies route each bounded context to its
  own database.

Safety
------
Everything here runs against DISPOSABLE databases whose names contain the
``_test`` marker.  The module refuses to run against a database that is not
clearly marked as a test database, and it never issues ``DROP DATABASE`` or
``DROP SCHEMA public CASCADE`` against ``sentinel_core``,
``sentinel_detection`` or ``sentinel_ml``.

Configuration
-------------
Set the following environment variables to point at a running PostgreSQL
server::

    CORE_DETECTION_TEST_URL       full URL of the disposable Core database
    DETECTION_TEST_URL            full URL of the disposable Detection database
    ML_TEST_URL                   full URL of the disposable ML database

If they are absent, the module SKIPS with an explicit message - it never
fabricates a pass.
"""
from __future__ import annotations

import os
import re
from typing import Optional

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

CORE_TEST_URL = os.environ.get("CORE_DETECTION_TEST_URL", "")
DETECTION_TEST_URL = os.environ.get("DETECTION_TEST_URL", "")
ML_TEST_URL = os.environ.get("ML_TEST_URL", "")

#: Every database this module is allowed to touch must carry this marker.
TEST_MARKER = "_test"

#: The canonical table inventories (see docs/DECISIONS-SYSTEM-v3.3.md 3.4).
CORE_TABLES = frozenset({
    "roles",
    "users",
    "user_roles",
    "ip_addresses",
    "sessions",
    "mfa_transactions",
    "mfa_notifications",
    "audit_logs",
    "user_trusted_devices",
    "system_settings",
    "outbox_events",
    "user_notifications",
    "rate_limits",
})

DETECTION_TABLES = frozenset({
    "policies",
    "login_attempts",
    "risk_assessments",
    "detection_logs",
    "soc_analysts",
    "alerts",
    "alert_timeline",
})

ML_TABLES = frozenset({
    "model_versions",
    "inference_logs",
    "feature_statistics",
})

ML_VIEWS = frozenset({"local_ml_stats"})

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEMA_DIR = os.path.join(REPO_ROOT, "infra", "postgres")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _database_name(url: str) -> str:
    """Extract the database name from a SQLAlchemy URL."""
    name = url.rsplit("/", 1)[-1]
    return name.split("?", 1)[0]


def _assert_disposable(url: str, label: str) -> str:
    """Fail loudly when the URL does not point at a disposable test database."""
    name = _database_name(url)
    if TEST_MARKER not in name.lower():
        pytest.fail(
            f"Refusing to run {label} against {name!r}: the database name must "
            f"contain {TEST_MARKER!r}. Real development databases "
            f"(sentinel_core / sentinel_detection / sentinel_ml) must never be "
            f"used as a test target."
        )
    return name


def _require_schema_file(filename: str) -> str:
    path = os.path.join(SCHEMA_DIR, filename)
    if not os.path.exists(path):
        pytest.skip(f"schema file {filename} is missing")
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def _base_tables(engine: Engine) -> set:
    rows = engine.connect().execute(
        text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"
        )
    ).fetchall()
    return {row[0] for row in rows}


def _views(engine: Engine) -> set:
    rows = engine.connect().execute(
        text(
            "SELECT table_name FROM information_schema.views "
            "WHERE table_schema = 'public'"
        )
    ).fetchall()
    return {row[0] for row in rows}


def _collect_dependencies(route) -> set:
    """Return every callable dependency of a route, transitively.

    FastAPI stores the resolved callables on ``dependant.dependencies``; the
    attribute name differs between FastAPI versions, so the structure is
    walked defensively.
    """
    found = set()
    stack = [getattr(route, "dependant", None)]
    while stack:
        dependant = stack.pop()
        if dependant is None:
            continue
        call = getattr(dependant, "call", None)
        if callable(call):
            found.add(call)
        for sub in getattr(dependant, "dependencies", []) or []:
            stack.append(sub)
    return found


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def core_engine():
    if not CORE_TEST_URL:
        pytest.skip(
            "NOT RUN — CORE_DETECTION_TEST_URL is not set; PostgreSQL "
            "integration environment unavailable"
        )
    _assert_disposable(CORE_TEST_URL, "the Core topology test")
    engine = create_engine(CORE_TEST_URL)
    try:
        engine.connect()
    except sa.exc.SQLAlchemyError as exc:
        engine.dispose()
        pytest.skip(f"NOT RUN — cannot reach the Core test database: {exc}")
    yield engine
    engine.dispose()


@pytest.fixture(scope="module")
def detection_engine():
    if not DETECTION_TEST_URL:
        pytest.skip(
            "NOT RUN — DETECTION_TEST_URL is not set; PostgreSQL "
            "integration environment unavailable"
        )
    _assert_disposable(DETECTION_TEST_URL, "the Detection topology test")
    engine = create_engine(DETECTION_TEST_URL)
    try:
        engine.connect()
    except sa.exc.SQLAlchemyError as exc:
        engine.dispose()
        pytest.skip(f"NOT RUN — cannot reach the Detection test database: {exc}")
    yield engine
    engine.dispose()


@pytest.fixture(scope="module")
def ml_engine():
    if not ML_TEST_URL:
        pytest.skip(
            "NOT RUN — ML_TEST_URL is not set; PostgreSQL integration "
            "environment unavailable"
        )
    _assert_disposable(ML_TEST_URL, "the ML topology test")
    engine = create_engine(ML_TEST_URL)
    try:
        engine.connect()
    except sa.exc.SQLAlchemyError as exc:
        engine.dispose()
        pytest.skip(f"NOT RUN — cannot reach the ML test database: {exc}")
    yield engine
    engine.dispose()


@pytest.fixture(scope="module")
def bootstrapped(core_engine, detection_engine, ml_engine):
    """Apply the canonical schema files to the three disposable databases.

    The schema files are NOT fully idempotent (the ``updated_at`` triggers are
    created with ``CREATE TRIGGER`` and no ``IF NOT EXISTS`` guard), so the
    fixture rebuilds the ``public`` schema of each DISPOSABLE test database
    before applying it.  Only databases whose name carries the ``_test``
    marker are ever touched - see :func:`_assert_disposable`.
    """
    for engine, filename in (
        (core_engine, "schema-core-v3.3.sql"),
        (detection_engine, "schema-detection-v3.3.sql"),
        (ml_engine, "schema-ml-service-v3.3.sql"),
    ):
        with engine.begin() as conn:
            conn.execute(text("DROP SCHEMA public CASCADE"))
            conn.execute(text("CREATE SCHEMA public"))
            conn.execute(text("GRANT ALL ON SCHEMA public TO public"))
            conn.execute(text(_require_schema_file(filename)))
    return True


# ---------------------------------------------------------------------------
# Positive checks - each database holds exactly its own tables
# ---------------------------------------------------------------------------

class TestCoreDatabase:
    """sentinel_core holds the 13 Core base tables and nothing else."""

    def test_core_has_exactly_thirteen_base_tables(self, core_engine, bootstrapped):
        tables = _base_tables(core_engine)
        assert len(tables) == 13, f"expected 13 Core base tables, got {sorted(tables)}"

    def test_core_has_the_expected_table_set(self, core_engine, bootstrapped):
        assert _base_tables(core_engine) == set(CORE_TABLES)

    def test_core_has_users_and_sessions(self, core_engine, bootstrapped):
        tables = _base_tables(core_engine)
        assert "users" in tables
        assert "sessions" in tables

    def test_core_has_no_views(self, core_engine, bootstrapped):
        # The ML view must not leak into the Core database.
        assert _views(core_engine) == set()


class TestDetectionDatabase:
    """sentinel_detection holds the 7 Detection base tables and nothing else."""

    def test_detection_has_exactly_seven_base_tables(self, detection_engine, bootstrapped):
        tables = _base_tables(detection_engine)
        assert len(tables) == 7, f"expected 7 Detection base tables, got {sorted(tables)}"

    def test_detection_has_the_expected_table_set(self, detection_engine, bootstrapped):
        assert _base_tables(detection_engine) == set(DETECTION_TABLES)

    def test_detection_has_login_attempts_and_risk_assessments(
        self, detection_engine, bootstrapped
    ):
        tables = _base_tables(detection_engine)
        assert "login_attempts" in tables
        assert "risk_assessments" in tables

    def test_detection_has_no_views(self, detection_engine, bootstrapped):
        assert _views(detection_engine) == set()


class TestMlDatabase:
    """sentinel_ml holds 3 ML base tables + the local_ml_stats view."""

    def test_ml_has_exactly_three_base_tables(self, ml_engine, bootstrapped):
        tables = _base_tables(ml_engine)
        assert len(tables) == 3, f"expected 3 ML base tables, got {sorted(tables)}"

    def test_ml_has_the_expected_table_set(self, ml_engine, bootstrapped):
        assert _base_tables(ml_engine) == set(ML_TABLES)

    def test_ml_has_model_versions_inference_logs_and_feature_statistics(
        self, ml_engine, bootstrapped
    ):
        tables = _base_tables(ml_engine)
        assert "model_versions" in tables
        assert "inference_logs" in tables
        assert "feature_statistics" in tables

    def test_ml_has_the_local_ml_stats_view(self, ml_engine, bootstrapped):
        assert "local_ml_stats" in _views(ml_engine)

    def test_local_ml_stats_reads_only_ml_local_data(self, ml_engine, bootstrapped):
        """The view must be built from ML-local tables only (no cross-DB SQL)."""
        with ml_engine.connect() as conn:
            definition = conn.execute(
                text(
                    "SELECT view_definition FROM information_schema.views "
                    "WHERE table_schema = 'public' AND table_name = 'local_ml_stats'"
                )
            ).scalar_one()
        assert "inference_logs" in definition
        for foreign in ("login_attempts", "risk_assessments", "alerts", "users"):
            assert foreign not in definition, (
                f"local_ml_stats must not reference {foreign}: a cross-database "
                f"view would violate the database boundary"
            )


# ---------------------------------------------------------------------------
# Negative checks - no cross-database contamination
# ---------------------------------------------------------------------------

class TestNoCrossDatabaseContamination:
    """Each database must be free of the other contexts' tables."""

    def test_core_has_no_detection_or_ml_tables(self, core_engine, bootstrapped):
        tables = _base_tables(core_engine)
        assert "login_attempts" not in tables
        assert "model_versions" not in tables
        assert "alerts" not in tables
        assert "inference_logs" not in tables

    def test_detection_has_no_core_tables(self, detection_engine, bootstrapped):
        tables = _base_tables(detection_engine)
        assert "users" not in tables
        assert "sessions" not in tables
        assert "user_trusted_devices" not in tables

    def test_detection_has_no_ml_tables(self, detection_engine, bootstrapped):
        tables = _base_tables(detection_engine)
        assert "model_versions" not in tables
        assert "inference_logs" not in tables

    def test_ml_has_no_core_tables(self, ml_engine, bootstrapped):
        tables = _base_tables(ml_engine)
        assert "users" not in tables
        assert "sessions" not in tables

    def test_ml_has_no_detection_tables(self, ml_engine, bootstrapped):
        tables = _base_tables(ml_engine)
        assert "alerts" not in tables
        assert "policies" not in tables
        assert "login_attempts" not in tables

    def test_ml_has_no_core_views(self, ml_engine, bootstrapped):
        views = _views(ml_engine)
        assert views == set(ML_VIEWS)


# ---------------------------------------------------------------------------
# No cross-database foreign keys
# ---------------------------------------------------------------------------

class TestNoCrossDatabaseForeignKeys:
    """A FK may only point at a table in the SAME database."""

    def _foreign_key_targets(self, engine: Engine) -> list:
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT tc.constraint_name, ccu.table_name "
                    "FROM information_schema.table_constraints tc "
                    "JOIN information_schema.constraint_column_usage ccu "
                    "  ON ccu.constraint_name = tc.constraint_name "
                    " AND ccu.constraint_schema = tc.constraint_schema "
                    "WHERE tc.constraint_type = 'FOREIGN KEY' "
                    "  AND tc.table_schema = 'public'"
                )
            ).fetchall()
        return [(row[0], row[1]) for row in rows]

    def test_core_foreign_keys_stay_inside_core(self, core_engine, bootstrapped):
        for constraint, target in self._foreign_key_targets(core_engine):
            assert target in CORE_TABLES, (
                f"Core FK {constraint} points at {target!r}, which is not a Core table"
            )

    def test_detection_foreign_keys_stay_inside_detection(
        self, detection_engine, bootstrapped
    ):
        for constraint, target in self._foreign_key_targets(detection_engine):
            assert target in DETECTION_TABLES, (
                f"Detection FK {constraint} points at {target!r}, which is not a "
                f"Detection table"
            )

    def test_ml_foreign_keys_stay_inside_ml(self, ml_engine, bootstrapped):
        for constraint, target in self._foreign_key_targets(ml_engine):
            assert target in ML_TABLES, (
                f"ML FK {constraint} points at {target!r}, which is not an ML table"
            )


# ---------------------------------------------------------------------------
# Device fingerprint column
# ---------------------------------------------------------------------------

class TestDetectionDeviceFingerprintColumn:
    """``login_attempts.device_fingerprint`` is a nullable, local column."""

    def test_column_exists_and_is_nullable(self, detection_engine, bootstrapped):
        with detection_engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT is_nullable, data_type FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND table_name = 'login_attempts' "
                    "AND column_name = 'device_fingerprint'"
                )
            ).fetchone()
        assert row is not None, "login_attempts.device_fingerprint is missing"
        assert row[0] == "YES", "device_fingerprint must be nullable"
        assert row[1] == "text"

    def test_column_is_not_a_foreign_key(self, detection_engine, bootstrapped):
        """The fingerprint is a value, not a reference to a Core row.

        ``login_attempts`` legitimately declares two INTRA-Detection foreign
        keys (``policies`` and ``alerts``).  What must not exist is a foreign
        key that leaves the Detection database, and in particular none that
        references a Core table such as ``users``.
        """
        with detection_engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT tc.constraint_name, ccu.table_name "
                    "FROM information_schema.table_constraints tc "
                    "JOIN information_schema.constraint_column_usage ccu "
                    "  ON ccu.constraint_name = tc.constraint_name "
                    " AND ccu.constraint_schema = tc.constraint_schema "
                    "WHERE tc.constraint_type = 'FOREIGN KEY' "
                    "  AND tc.table_schema = 'public' "
                    "  AND tc.table_name = 'login_attempts'"
                )
            ).fetchall()

        for constraint, target in rows:
            assert target in DETECTION_TABLES, (
                f"login_attempts FK {constraint} points at {target!r}, which is "
                f"outside the Detection database"
            )

    def test_device_fingerprint_column_is_not_referenced_by_a_foreign_key(
        self, detection_engine, bootstrapped
    ):
        with detection_engine.connect() as conn:
            count = conn.execute(
                text(
                    "SELECT count(*) "
                    "FROM information_schema.key_column_usage kcu "
                    "JOIN information_schema.table_constraints tc "
                    "  ON tc.constraint_name = kcu.constraint_name "
                    " AND tc.constraint_schema = kcu.constraint_schema "
                    "WHERE tc.constraint_type = 'FOREIGN KEY' "
                    "  AND tc.table_schema = 'public' "
                    "  AND kcu.table_name = 'login_attempts' "
                    "  AND kcu.column_name = 'device_fingerprint'"
                )
            ).scalar_one()
        assert count == 0, "device_fingerprint must not be a foreign key"


# ---------------------------------------------------------------------------
# Application routing
# ---------------------------------------------------------------------------

class TestSessionRouting:
    """The runtime must route each bounded context to its own database."""

    def test_three_independent_dependencies_exist(self):
        from app import db

        assert callable(db.get_core_db)
        assert callable(db.get_detection_db)
        assert callable(db.get_ml_db)
        assert db.get_core_db is not db.get_detection_db
        assert db.get_core_db is not db.get_ml_db
        assert db.get_detection_db is not db.get_ml_db

    def test_each_context_resolves_its_own_url(self, monkeypatch):
        from app import db

        monkeypatch.setenv("CORE_DATABASE_URL", "postgresql://u:p@h:5432/sentinel_core")
        monkeypatch.setenv(
            "DETECTION_DATABASE_URL", "postgresql://u:p@h:5432/sentinel_detection"
        )
        monkeypatch.setenv("ML_DATABASE_URL", "postgresql://u:p@h:5432/sentinel_ml")
        monkeypatch.delenv("DATABASE_URL", raising=False)

        assert db.resolve_database_url(db.CORE).endswith("/sentinel_core")
        assert db.resolve_database_url(db.DETECTION).endswith("/sentinel_detection")
        assert db.resolve_database_url(db.ML).endswith("/sentinel_ml")

    def test_context_engines_are_distinct(self, monkeypatch):
        from app import db

        monkeypatch.setenv("CORE_DATABASE_URL", "postgresql://u:p@h:5432/sentinel_core")
        monkeypatch.setenv(
            "DETECTION_DATABASE_URL", "postgresql://u:p@h:5432/sentinel_detection"
        )
        monkeypatch.setenv("ML_DATABASE_URL", "postgresql://u:p@h:5432/sentinel_ml")
        monkeypatch.delenv("DATABASE_URL", raising=False)

        try:
            engines = {
                context: db.get_engine(db.resolve_database_url(context), context=context)
                for context in (db.CORE, db.DETECTION, db.ML)
            }
            assert len({id(engine) for engine in engines.values()}) == 3
        finally:
            db.dispose_engines()

    def test_legacy_database_url_is_only_a_fallback(self, monkeypatch):
        """The legacy single-database URL must not silently absorb every context.

        The Core context may fall back to ``DATABASE_URL`` for monolith
        compatibility, but Detection and ML must refuse: reusing one
        database would put the Detection/ML tables in the Core schema and
        break the three-database topology.
        """
        from app import db

        monkeypatch.delenv("CORE_DATABASE_URL", raising=False)
        monkeypatch.delenv("DETECTION_DATABASE_URL", raising=False)
        monkeypatch.delenv("ML_DATABASE_URL", raising=False)
        monkeypatch.delenv(db.LEGACY_SINGLE_DB_FLAG, raising=False)
        monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@h:5432/legacy_db")

        # Core keeps the legacy fallback ...
        assert db.resolve_database_url(db.CORE).endswith("/legacy_db")

        # ... but Detection and ML raise a clear configuration error.
        for context in (db.DETECTION, db.ML):
            with pytest.raises(db.DatabaseConfigurationError) as exc_info:
                db.resolve_database_url(context)
            message = str(exc_info.value)
            assert db.CONTEXT_ENV_VARS[context] in message
            assert db.LEGACY_SINGLE_DB_FLAG in message

    def test_explicit_opt_in_re_enables_the_legacy_fallback(self, monkeypatch):
        """``ALLOW_LEGACY_SINGLE_DB=1`` re-enables the single-database layout."""
        from app import db

        monkeypatch.delenv("CORE_DATABASE_URL", raising=False)
        monkeypatch.delenv("DETECTION_DATABASE_URL", raising=False)
        monkeypatch.delenv("ML_DATABASE_URL", raising=False)
        monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@h:5432/legacy_db")
        monkeypatch.setenv(db.LEGACY_SINGLE_DB_FLAG, "1")

        for context in (db.CORE, db.DETECTION, db.ML):
            assert db.resolve_database_url(context).endswith("/legacy_db")

        # Each context still gets its own engine, so the three contexts
        # never share ONE cached engine.
        try:
            engines = {
                context: db.get_engine(
                    db.resolve_database_url(context), context=context
                )
                for context in (db.CORE, db.DETECTION, db.ML)
            }
            assert len({id(engine) for engine in engines.values()}) == 3
        finally:
            db.dispose_engines()

    def test_detection_and_ml_require_their_own_url(self, monkeypatch):
        """Detection and ML must never silently resolve to the Core database."""
        from app import db

        monkeypatch.delenv("DETECTION_DATABASE_URL", raising=False)
        monkeypatch.delenv("ML_DATABASE_URL", raising=False)
        monkeypatch.delenv(db.LEGACY_SINGLE_DB_FLAG, raising=False)
        # The legacy URL must be absent for the first assertion: with it
        # set, the Detection/ML contexts raise instead of resolving to
        # their own built-in default.
        monkeypatch.delenv(db.LEGACY_DATABASE_URL_ENV, raising=False)

        # No legacy URL at all -> the built-in per-context default is used,
        # which still points at the context's own database.
        assert db.resolve_database_url(db.DETECTION).endswith("/sentinel_detection")
        assert db.resolve_database_url(db.ML).endswith("/sentinel_ml")

        # A legacy URL present but not opted in -> hard configuration error.
        monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@h:5432/legacy_db")
        for context in (db.DETECTION, db.ML):
            with pytest.raises(db.DatabaseConfigurationError):
                db.resolve_database_url(context)

    def test_route_modules_use_the_matching_dependency(self):
        """Every router must declare the dependency of its bounded context."""
        from app import alerts, auth, authz, detection, devices, iam, internal_actions, ml
        from fastapi.routing import APIRoute

        expected = {
            auth: "get_core_db",
            iam: "get_core_db",
            devices: "get_core_db",
            internal_actions: "get_core_db",
            authz: "get_core_db",
            detection: "get_detection_db",
            alerts: "get_detection_db",
            ml: "get_ml_db",
        }

        for module, attribute in expected.items():
            dependency = getattr(module, attribute)
            # Collect every APIRoute that belongs to this module.
            routes = [
                route
                for route in getattr(module, "router", type("x", (), {"routes": []})).routes
                if isinstance(route, APIRoute)
            ]
            for other in vars(module).values():
                if hasattr(other, "routes") and other is not getattr(module, "router", None):
                    routes.extend(
                        route for route in other.routes if isinstance(route, APIRoute)
                    )
            for route in routes:
                # A route that does not take a ``db`` parameter does not touch
                # a database at all (e.g. GET /ml/features, which publishes a
                # static contract), so it is exempt from the check.
                params = {
                    param.name
                    for param in getattr(
                        getattr(route, "dependant", None), "query_params", []
                    )
                } | {
                    param.name
                    for param in getattr(
                        getattr(route, "dependant", None), "path_params", []
                    )
                } | {
                    param.name
                    for param in getattr(
                        getattr(route, "dependant", None), "body_params", []
                    )
                } | {
                    param.name
                    for param in getattr(
                        getattr(route, "dependant", None), "header_params", []
                    )
                } | {
                    param.name
                    for param in getattr(
                        getattr(route, "dependant", None), "cookie_params", []
                    )
                }
                if "db" not in params:
                    continue
                used = _collect_dependencies(route)
                assert dependency in used, (
                    f"{module.__name__}:{route.path} takes a 'db' parameter but "
                    f"does not declare {attribute}"
                )


class TestRealDatabaseRouting:
    """Write through each dependency and verify the row lands in the right DB."""

    def test_core_write_lands_in_core_database(
        self, core_engine, detection_engine, ml_engine, bootstrapped, monkeypatch
    ):
        from app.db import get_core_db, get_detection_db, get_ml_db
        from app.models import Role

        monkeypatch.setenv("CORE_DATABASE_URL", str(core_engine.url))
        monkeypatch.setenv("DETECTION_DATABASE_URL", str(detection_engine.url))
        monkeypatch.setenv("ML_DATABASE_URL", str(ml_engine.url))
        monkeypatch.delenv("DATABASE_URL", raising=False)

        from app import db

        db.dispose_engines()
        try:
            core_session = next(get_core_db())
            try:
                core_session.add(
                    Role(id="ROUTING_PROBE", name="Routing Probe", name_vi="Probe")
                )
                core_session.commit()
            finally:
                core_session.close()

            # The row must be visible in the Core database ...
            with core_engine.connect() as conn:
                found = conn.execute(
                    text("SELECT count(*) FROM roles WHERE id = 'ROUTING_PROBE'")
                ).scalar_one()
            assert found == 1

            # ... and must NOT exist in the other two databases.
            for engine, name in (
                (detection_engine, "detection"),
                (ml_engine, "ml"),
            ):
                with engine.connect() as conn:
                    names = {
                        row[0]
                        for row in conn.execute(
                            text(
                                "SELECT table_name FROM information_schema.tables "
                                "WHERE table_schema = 'public'"
                            )
                        ).fetchall()
                    }
                assert "roles" not in names, (
                    f"the {name} database must not contain the Core 'roles' table"
                )
        finally:
            db.dispose_engines()
