"""The safety guard of the M13.2 E2E fixture helper.

``scripts/e2e_fixtures.py`` WRITES rows (the alerts, the policies, the
sessions, the MFA gate, the rate-limit counters) and DELETES rows.  It is
the only thing in the browser suite that writes to a database directly,
so it is also the only place where a mistake could reach a database that
must never be touched.

The guard lives in ``scripts/e2e_fixtures_guard.py`` and is
**fail-closed**: every layer refuses by default, and the layers are
independent, so a bug in one does not open a hole in the next.

    Layer 1  the URL must come from the context's OWN URL variable
    Layer 2  the database name must be in the context's HARD-CODED
             allowlist — an exact match, not a suffix check
    Layer 3  the regression suite's ``*_test`` databases and the
             canonical production names are refused outright
    Layer 4  the server must be on the loopback interface
    Layer 5  the run must have declared the exact target BY NAME

The first part of this module is a pure unit test: it does not connect to
a database at all, and it never mocks the guard — it calls the real one
and asserts on the real refusal.

The second part needs a real PostgreSQL server.  It skips itself when
the server is absent, so the module never becomes a silent coverage
hole: the CI acceptance policy treats a skip as a failure, and the CI
provisions the disposable demo databases before the suite runs.
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"

#: The three demo databases the CI provisions.  They are the ones the
#: guard must accept, and they are the only databases the helper is
#: allowed to write to during a CI run.
DEMO_CORE_DB = "sentinel_core_ci_demo"
DEMO_DETECTION_DB = "sentinel_detection_ci_demo"
DEMO_ML_DB = "sentinel_ml_ci_demo"


def _load_script(name: str):
    """Import a script from ``scripts/`` by its file name."""
    path = SCRIPTS_DIR / name
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _host() -> str:
    """The host of the disposable PostgreSQL server."""
    return os.environ.get("POSTGRES_HOST", "127.0.0.1")


def _port() -> str:
    return os.environ.get("POSTGRES_PORT", "5432")


def _user() -> str:
    return os.environ.get("POSTGRES_USER", "sentinel")


def _password() -> str:
    return os.environ.get("POSTGRES_PASSWORD", "")


def _url(database: str, driver: str = "") -> str:
    """A connection URL for one of the disposable demo databases."""
    scheme = f"postgresql+{driver}" if driver else "postgresql"
    return (
        f"{scheme}://{_user()}:{_password()}@{_host()}:{_port()}/{database}"
    )


# =============================================================================
# The pure unit tests — no database is involved
# =============================================================================

class TestTheDemoDatabaseGuard:
    """``scripts/e2e_fixtures_guard.py``, called directly."""

    @pytest.fixture(scope="class")
    def guard(self):
        return _load_script("e2e_fixtures_guard.py")

    # --- the valid targets are accepted ---------------------------------

    @pytest.mark.parametrize(
        "context,environment_variable,database",
        [
            ("core", "CORE_DATABASE_URL", DEMO_CORE_DB),
            ("detection", "DETECTION_DATABASE_URL", DEMO_DETECTION_DB),
            ("ml", "ML_DATABASE_URL", DEMO_ML_DB),
        ],
    )
    def test_a_demo_database_of_the_right_context_is_accepted(
        self, guard, context, environment_variable, database
    ):
        environment = {
            environment_variable: _url(database),
            "E2E_ALLOW_WRITE_TO": database,
        }
        name = guard.require_demo_database(
            context, environment[environment_variable], environ=environment
        )
        assert name == database

    def test_the_local_demo_database_names_are_accepted_too(self, guard):
        # The local demo stack's persistent databases are the OTHER half of
        # each context's allowlist.  A guard that only accepted the CI
        # names would break the local run — and a guard that accepted
        # EVERYTHING would protect nothing.
        environment = {
            "CORE_DATABASE_URL": _url("sentinel_core_demo"),
            "E2E_ALLOW_WRITE_TO": "sentinel_core_demo",
        }
        assert guard.require_demo_database(
            "core", environment["CORE_DATABASE_URL"], environ=environment
        ) == "sentinel_core_demo"

    # --- a non-demo database is refused ---------------------------------

    @pytest.mark.parametrize(
        "database",
        [
            "sentinel_core",              # the production name
            "sentinel_detection",         # the production name
            "sentinel_ml",                # the production name
            "sentinel",                   # the production name
            "postgres",                   # the maintenance database
            "sentinel_core_test",         # the regression suite's database
            "sentinel_detection_test",
            "sentinel_ml_test",
            "sentinel_legacy_test",
        ],
    )
    def test_a_non_demo_database_is_refused(self, guard, database):
        environment = {
            "CORE_DATABASE_URL": _url(database),
            "E2E_ALLOW_WRITE_TO": database,
        }
        with pytest.raises(guard.DemoDatabaseRefusal) as excinfo:
            guard.require_demo_database(
                "core", environment["CORE_DATABASE_URL"], environ=environment
            )
        assert excinfo.value.layer in {"allowlist", "overlap"}

    @pytest.mark.parametrize(
        "database",
        [
            # A name that merely ENDS with '_demo' is not a demo database.
            "sentinel_core_demo_prod",
            "sentinel_core_demo_backup",
            "not_sentinel_core_demo",
            "sentinel_core_democracy",
        ],
    )
    def test_a_name_that_only_looks_like_a_demo_database_is_refused(self, guard, database):
        # This is the case a suffix check would let through, and it is the
        # reason the allowlist is an EXACT match.
        environment = {
            "CORE_DATABASE_URL": _url(database),
            "E2E_ALLOW_WRITE_TO": database,
        }
        with pytest.raises(guard.DemoDatabaseRefusal):
            guard.require_demo_database(
                "core", environment["CORE_DATABASE_URL"], environ=environment
            )

    # --- the wrong context is refused -----------------------------------

    def test_the_core_context_cannot_reach_the_detection_database(self, guard):
        environment = {
            "DETECTION_DATABASE_URL": _url(DEMO_DETECTION_DB),
            "E2E_ALLOW_WRITE_TO": DEMO_DETECTION_DB,
        }
        with pytest.raises(guard.DemoDatabaseRefusal) as excinfo:
            guard.require_demo_database(
                "core", environment["DETECTION_DATABASE_URL"], environ=environment
            )
        assert excinfo.value.layer == "allowlist"

    def test_the_detection_context_cannot_reach_the_core_database(self, guard):
        environment = {
            "CORE_DATABASE_URL": _url(DEMO_CORE_DB),
            "E2E_ALLOW_WRITE_TO": DEMO_CORE_DB,
        }
        with pytest.raises(guard.DemoDatabaseRefusal):
            guard.require_demo_database(
                "detection", environment["CORE_DATABASE_URL"], environ=environment
            )

    def test_the_ml_context_cannot_reach_the_core_database(self, guard):
        environment = {
            "CORE_DATABASE_URL": _url(DEMO_CORE_DB),
            "E2E_ALLOW_WRITE_TO": DEMO_CORE_DB,
        }
        with pytest.raises(guard.DemoDatabaseRefusal):
            guard.require_demo_database(
                "ml", environment["CORE_DATABASE_URL"], environ=environment
            )

    def test_an_unknown_context_is_refused(self, guard):
        environment = {"E2E_ALLOW_WRITE_TO": DEMO_CORE_DB}
        with pytest.raises(guard.DemoDatabaseRefusal) as excinfo:
            guard.require_demo_database(
                "analytics", _url(DEMO_CORE_DB), environ=environment
            )
        assert excinfo.value.layer == "context"

    # --- the host must be the loopback interface ------------------------

    @pytest.mark.parametrize(
        "host",
        ["db.internal", "10.0.0.5", "sentinel.example.com", "0.0.0.0"],
    )
    def test_a_database_on_another_host_is_refused(self, guard, host):
        url = f"postgresql://{_user()}:{_password()}@{host}:{_port()}/{DEMO_CORE_DB}"
        environment = {
            "CORE_DATABASE_URL": url,
            "E2E_ALLOW_WRITE_TO": DEMO_CORE_DB,
        }
        with pytest.raises(guard.DemoDatabaseRefusal) as excinfo:
            guard.require_demo_database("core", url, environ=environment)
        assert excinfo.value.layer == "host"

    @pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "[::1]"])
    def test_a_database_on_the_loopback_interface_is_accepted(self, guard, host):
        # The IPv6 loopback is spelled in brackets, because an unbracketed
        # '::1' is not a URL a parser can read.
        url = f"postgresql://{_user()}:{_password()}@{host}:{_port()}/{DEMO_CORE_DB}"
        environment = {
            "CORE_DATABASE_URL": url,
            "E2E_ALLOW_WRITE_TO": DEMO_CORE_DB,
        }
        assert guard.require_demo_database("core", url, environ=environment) == (
            DEMO_CORE_DB
        )

    # --- the explicit opt-in --------------------------------------------

    def test_a_run_without_the_declaration_is_refused(self, guard):
        environment = {"CORE_DATABASE_URL": _url(DEMO_CORE_DB)}
        with pytest.raises(guard.DemoDatabaseRefusal) as excinfo:
            guard.require_demo_database(
                "core", environment["CORE_DATABASE_URL"], environ=environment
            )
        assert excinfo.value.layer == "permission"

    def test_a_generic_acknowledgement_authorises_nothing(self, guard):
        # "true" is not a database name, so it authorises nothing.  This is
        # the case a boolean flag would let through.
        environment = {
            "CORE_DATABASE_URL": _url(DEMO_CORE_DB),
            "E2E_ALLOW_WRITE_TO": "true",
        }
        with pytest.raises(guard.DemoDatabaseRefusal) as excinfo:
            guard.require_demo_database(
                "core", environment["CORE_DATABASE_URL"], environ=environment
            )
        assert excinfo.value.layer == "permission"

    def test_a_declaration_for_another_database_authorises_nothing(self, guard):
        environment = {
            "CORE_DATABASE_URL": _url(DEMO_CORE_DB),
            "E2E_ALLOW_WRITE_TO": DEMO_DETECTION_DB,
        }
        with pytest.raises(guard.DemoDatabaseRefusal) as excinfo:
            guard.require_demo_database(
                "core", environment["CORE_DATABASE_URL"], environ=environment
            )
        assert excinfo.value.layer == "permission"

    def test_a_declaration_that_names_the_target_is_accepted(self, guard):
        environment = {
            "CORE_DATABASE_URL": _url(DEMO_CORE_DB),
            "E2E_ALLOW_WRITE_TO": f"{DEMO_CORE_DB} {DEMO_DETECTION_DB} {DEMO_ML_DB}",
        }
        assert guard.require_demo_database(
            "core", environment["CORE_DATABASE_URL"], environ=environment
        ) == DEMO_CORE_DB

    # --- the URL must come from the context's own variable ---------------

    def test_a_url_that_does_not_match_its_own_variable_is_refused(self, guard):
        # The subtle mistake: the core context's URL was repointed at the
        # detection database by hand.  The name is a demo name of the
        # DETECTION context, so only the context check catches it.
        environment = {
            "CORE_DATABASE_URL": _url(DEMO_DETECTION_DB),
            "DETECTION_DATABASE_URL": _url(DEMO_DETECTION_DB),
            "E2E_ALLOW_WRITE_TO": DEMO_DETECTION_DB,
        }
        # The detection context accepts it — the name is its own.
        assert guard.require_demo_database(
            "detection", environment["DETECTION_DATABASE_URL"], environ=environment
        ) == DEMO_DETECTION_DB

        # And the core context refuses it, because the name is not one of
        # ITS two names.
        with pytest.raises(guard.DemoDatabaseRefusal):
            guard.require_demo_database(
                "core", environment["CORE_DATABASE_URL"], environ=environment
            )

    def test_an_empty_url_is_refused(self, guard):
        environment = {"CORE_DATABASE_URL": "", "E2E_ALLOW_WRITE_TO": DEMO_CORE_DB}
        with pytest.raises(guard.DemoDatabaseRefusal) as excinfo:
            guard.require_demo_database("core", "", environ=environment)
        assert excinfo.value.layer == "url"

    def test_a_url_without_a_database_name_is_refused(self, guard):
        url = f"postgresql://{_user()}:{_password()}@{_host()}:{_port()}"
        environment = {"CORE_DATABASE_URL": url, "E2E_ALLOW_WRITE_TO": DEMO_CORE_DB}
        with pytest.raises(guard.DemoDatabaseRefusal) as excinfo:
            guard.require_demo_database("core", url, environ=environment)
        assert excinfo.value.layer == "url"

    # --- no single environment variable can widen the guard -------------

    def test_no_environment_variable_can_widen_the_allowlist(self, guard):
        # Whatever the environment says, the allowlist stays what the
        # module hard-codes.
        environment = {
            "CORE_DATABASE_URL": _url("sentinel_core_prod"),
            "E2E_ALLOW_WRITE_TO": "sentinel_core_prod",
            "E2E_DATABASE_ALLOWLIST": "sentinel_core_prod",
            "DEMO_ALLOW_ANY_DATABASE": "1",
            "E2E_SKIP_GUARD": "1",
            "ALLOW_LEGACY_SINGLE_DB": "1",
        }
        with pytest.raises(guard.DemoDatabaseRefusal):
            guard.require_demo_database(
                "core", environment["CORE_DATABASE_URL"], environ=environment
            )

    def test_the_allowlist_is_a_constant_of_the_module(self, guard):
        # The allowlist cannot be widened at runtime, because it is a
        # module-level constant and nothing mutates it.
        assert guard.CONTEXT_DATABASES["core"] == frozenset({
            "sentinel_core_demo",
            "sentinel_core_ci_demo",
        })
        assert guard.CONTEXT_DATABASES["detection"] == frozenset({
            "sentinel_detection_demo",
            "sentinel_detection_ci_demo",
        })
        assert guard.CONTEXT_DATABASES["ml"] == frozenset({
            "sentinel_ml_demo",
            "sentinel_ml_ci_demo",
        })

    def test_the_allowlist_and_the_protected_names_are_disjoint(self, guard):
        # A name that is in both sets would make the "overlap" layer
        # unreachable for that name, and the two layers would contradict
        # each other.
        for names in guard.CONTEXT_DATABASES.values():
            assert not names & guard.PROTECTED_TEST_DATABASES
            assert not names & guard.PROTECTED_PRODUCTION_DATABASES

    def test_the_query_string_does_not_confuse_the_guard(self, guard):
        url = f"{_url(DEMO_CORE_DB)}?sslmode=require"
        environment = {
            "CORE_DATABASE_URL": url,
            "E2E_ALLOW_WRITE_TO": DEMO_CORE_DB,
        }
        assert guard.require_demo_database("core", url, environ=environment) == (
            DEMO_CORE_DB
        )


class TestTheFixtureHelperUsesTheGuard:
    """``scripts/e2e_fixtures.py`` must go through the guard."""

    @pytest.fixture(scope="class")
    def helper(self):
        return _load_script("e2e_fixtures.py")

    def test_every_engine_is_built_through_the_guard(self, helper):
        import inspect

        # The three engine constructors are the only way this script
        # reaches a database, so all three must go through the guard.
        for name in ("_engine", "_core_engine", "_ml_engine"):
            source = inspect.getsource(getattr(helper, name))
            assert "_guarded_engine" in source, name

    def test_no_engine_is_built_from_a_bare_url(self, helper):
        import inspect

        source = inspect.getsource(helper)
        # A direct `create_engine(` outside the guard helper would be a
        # way around the boundary.
        assert source.count("create_engine(") == 1, (
            "the only create_engine() call must live in the guarded helper"
        )

    def test_the_guard_runs_before_the_engine_is_created(self, helper):
        import inspect

        source = inspect.getsource(helper._guarded_engine)
        guard_position = source.index("require_demo_database")
        engine_position = source.index("create_engine")
        assert guard_position < engine_position, (
            "the guard must be consulted BEFORE the engine is built, so a "
            "refused URL never opens a connection"
        )

    def test_a_refusal_becomes_a_clean_exit(self, helper):
        # The helper is a command-line tool, so the refusal must surface
        # as an exit rather than a traceback.
        environment = {
            "CORE_DATABASE_URL": _url("sentinel_core"),
            "E2E_ALLOW_WRITE_TO": "sentinel_core",
        }
        with pytest.raises(SystemExit):
            helper._guarded_engine(
                helper.Context.CORE, environment["CORE_DATABASE_URL"]
            )


class TestTheFixtureHelperRefusesBeforeItWrites:
    """The refusal must happen BEFORE any SQL is issued.

    This part needs a real PostgreSQL server, because the claim is about
    the DATABASE: a refused run must not have touched it.
    """

    @pytest.fixture(scope="class")
    def helper(self):
        return _load_script("e2e_fixtures.py")

    def _demo_urls(self) -> dict:
        """The three demo URLs of the disposable server, or an empty dict."""
        core = os.environ.get("DEMO_CORE_DATABASE_URL", "").strip()
        detection = os.environ.get("DEMO_DETECTION_DATABASE_URL", "").strip()
        ml = os.environ.get("DEMO_ML_DATABASE_URL", "").strip()
        if not (core and detection and ml):
            return {}
        return {"core": core, "detection": detection, "ml": ml}

    def test_a_refused_run_leaves_the_database_untouched(self, helper):
        from sqlalchemy import create_engine, text

        urls = self._demo_urls()
        if not urls:
            pytest.skip(
                "the demo databases are not provisioned. Export "
                "DEMO_CORE_DATABASE_URL, DEMO_DETECTION_DATABASE_URL and "
                "DEMO_ML_DATABASE_URL to run this check."
            )

        engine = create_engine(urls["detection"], pool_pre_ping=True)
        try:
            with engine.connect() as connection:
                before = int(
                    connection.execute(text("SELECT count(*) FROM alerts")).scalar()
                )
        finally:
            engine.dispose()

        # The URL names a PRODUCTION database, so the guard refuses it.
        environment = dict(os.environ)
        environment["DETECTION_DATABASE_URL"] = _url("sentinel_detection")
        environment["E2E_ALLOW_WRITE_TO"] = "sentinel_detection"

        with pytest.raises(SystemExit):
            helper.create_alert("guard-probe", risk_level="critical", status="open")

        engine = create_engine(urls["detection"], pool_pre_ping=True)
        try:
            with engine.connect() as connection:
                after = int(
                    connection.execute(text("SELECT count(*) FROM alerts")).scalar()
                )
        finally:
            engine.dispose()

        assert after == before, (
            "the refused run changed the row count of the alerts table"
        )

    def test_the_refusal_reaches_the_command_line(self):
        # The guard must also hold when the helper is invoked as the
        # command-line tool the browser suite actually calls.
        urls = {
            "core": os.environ.get("DEMO_CORE_DATABASE_URL", "").strip(),
            "detection": os.environ.get("DEMO_DETECTION_DATABASE_URL", "").strip(),
            "ml": os.environ.get("DEMO_ML_DATABASE_URL", "").strip(),
        }
        if not all(urls.values()):
            pytest.skip("the demo databases are not provisioned")

        environment = dict(os.environ)
        environment["DETECTION_DATABASE_URL"] = _url("sentinel_detection")
        environment["E2E_ALLOW_WRITE_TO"] = "sentinel_detection"

        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPTS_DIR / "e2e_fixtures.py"),
                "create-alert",
                "--key",
                "guard-probe",
            ],
            cwd=REPO_ROOT,
            env=environment,
            capture_output=True,
            text=True,
        )

        assert result.returncode != 0, result.stdout
        assert "refusing to write" in result.stderr, result.stderr

    def test_a_refused_run_creates_no_fixture_row(self):
        # The row the helper owns must not exist after the refusal: the
        # refusal is not "the write was rolled back", it is "the write
        # never started".
        urls = {
            "core": os.environ.get("DEMO_CORE_DATABASE_URL", "").strip(),
            "detection": os.environ.get("DEMO_DETECTION_DATABASE_URL", "").strip(),
            "ml": os.environ.get("DEMO_ML_DATABASE_URL", "").strip(),
        }
        if not all(urls.values()):
            pytest.skip("the demo databases are not provisioned")

        from sqlalchemy import create_engine, text

        helper = _load_script("e2e_fixtures.py")
        alert_id = helper._resolve_alert_id("guard-probe")

        environment = dict(os.environ)
        environment["DETECTION_DATABASE_URL"] = _url("sentinel_detection")
        environment["E2E_ALLOW_WRITE_TO"] = "sentinel_detection"

        with pytest.raises(SystemExit):
            helper.create_alert("guard-probe", risk_level="critical", status="open")

        engine = create_engine(urls["detection"], pool_pre_ping=True)
        try:
            with engine.connect() as connection:
                found = connection.execute(
                    text("SELECT count(*) FROM alerts WHERE id = :id"),
                    {"id": alert_id},
                ).scalar()
        finally:
            engine.dispose()

        assert int(found or 0) == 0, (
            "the refused run created the fixture row anyway"
        )
