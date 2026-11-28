"""Safety and behaviour of the M13 demo fixture scripts.

``scripts/demo_seed_demo.py`` WRITES rows (the seed) and DELETES rows (the
cleanup).  Both operations must never reach a database that is not a demo
database, and the cleanup must never touch a row the fixture set did not
create.

The guard is tested here because it is the last line of defence before a
row is written or deleted.  The first part of this module is a pure unit
test: it does not connect to a database at all.

The second part needs the three disposable demo databases.  It skips
itself when they are absent, so the module never turns into a silent
coverage hole: the CI acceptance policy treats a skip as a failure, and
the demo databases are provisioned by ``scripts/demo_stack.sh``, not by the
CI's own bootstrap.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"


def _load_script(name: str):
    """Import a script from ``scripts/`` by its file name."""
    path = SCRIPTS_DIR / name
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestDemoSeedDatabaseGuard:
    """The guard of ``scripts/demo_seed_demo.py``."""

    @pytest.fixture(scope="class")
    def module(self):
        return _load_script("demo_seed_demo.py")

    def test_a_demo_database_is_accepted(self, module):
        name = module.assert_demo_database(
            "postgresql://sentinel:secret@127.0.0.1:55432/sentinel_core_demo"
        )
        assert name == "sentinel_core_demo"

    def test_the_demo_marker_is_the_one_the_stack_uses(self, module):
        # The demo stack refuses to start with a database name that lacks
        # the marker; the seed uses the very same marker.
        assert module.DISPOSABLE_DB_MARKER == "_demo"

    @pytest.mark.parametrize(
        "url",
        [
            "postgresql://sentinel:secret@127.0.0.1:5432/sentinel_core",
            "postgresql://sentinel:secret@127.0.0.1:5432/sentinel_detection",
            "postgresql://sentinel:secret@127.0.0.1:5432/postgres",
            "postgresql://sentinel:secret@127.0.0.1:5432/sentinel_core_prod",
            "postgresql://sentinel:secret@127.0.0.1:5432/sentinel_core_test",
        ],
    )
    def test_a_non_demo_database_is_refused(self, module, url):
        with pytest.raises(SystemExit) as excinfo:
            module.assert_demo_database(url)
        assert excinfo.value.code == 2

    def test_a_url_without_a_database_name_is_refused(self, module):
        with pytest.raises(SystemExit) as excinfo:
            module.assert_demo_database("postgresql://sentinel:secret@127.0.0.1:5432")
        assert excinfo.value.code == 2

    def test_the_query_string_does_not_confuse_the_guard(self, module):
        name = module.assert_demo_database(
            "postgresql://sentinel:secret@127.0.0.1:55432/"
            "sentinel_ml_demo?sslmode=require"
        )
        assert name == "sentinel_ml_demo"

    def test_the_fixture_ids_are_deterministic(self, module):
        # The same key must always produce the same id, on any machine and
        # in any order.  That is what makes the seed idempotent and what
        # lets an E2E test find exactly the record it created.
        first = module.fixture_id(module.NS_USER, "demo_user")
        second = module.fixture_id(module.NS_USER, "demo_user")
        assert first == second
        # And two different keys must not collide.
        assert first != module.fixture_id(module.NS_USER, "demo_admin")

    def test_the_manifest_is_complete_and_deterministic(self, module, capsys):
        module.print_manifest()
        payload = json.loads(capsys.readouterr().out)

        # The four demo roles are all present.
        assert set(payload["users"]) == {"user", "analyst", "admin", "manager"}
        assert payload["users"]["admin"]["mfa_required"] is True
        assert payload["users"]["user"]["mfa_required"] is False
        assert payload["users"]["analyst"]["roles"] == ["SOC_ANALYST", "USER"]
        assert payload["users"]["manager"]["roles"] == ["SECURITY_MANAGER", "USER"]

        # Every alert carries a status and a risk level.
        assert payload["alerts"]
        for key, alert in payload["alerts"].items():
            assert alert["status"] in (
                "open",
                "acknowledged",
                "resolved",
                "false_positive",
            ), key
            assert alert["risk_level"] in ("low", "medium", "high", "critical"), key

        # The policy set is one draft and one active.
        assert payload["policies"]["active"]["is_active"] is True
        assert payload["policies"]["draft"]["is_active"] is False

        # The ML model is never promoted.
        assert payload["ml_model"]["status"] == "staged"
        assert payload["ml_model"]["is_production"] is False

    def test_the_cleanup_only_touches_the_rows_of_the_fixtures(self, module):
        import inspect

        for cleaner in (module.cleanup_core, module.cleanup_detection, module.cleanup_ml):
            source = inspect.getsource(cleaner)
            # Every deletion is scoped to an explicit id list.
            assert "model.id.in_(ids)" in source
            # And nothing truncates or drops anything.
            for forbidden in ("truncate", "TRUNCATE", "drop_all", "DROP TABLE"):
                assert forbidden not in source

    def test_the_seed_never_deletes_a_row_outside_the_fixture_set(self, module):
        import inspect

        # The seed MAY delete a row it owns: the role link is written
        # with an UPSERT-like pattern, and the link table has a unique
        # constraint on (user_id, role_id).  What it must never do is
        # delete a row that belongs to somebody else, and it must never
        # issue a bulk delete.
        for seeder in (module.seed_core, module.seed_detection, module.seed_ml):
            source = inspect.getsource(seeder)
            # No bulk delete and no schema-level destruction.
            for forbidden in ("truncate", "TRUNCATE", "drop_all", "DROP TABLE"):
                assert forbidden not in source, seeder.__name__
            # Every single-row delete is scoped to a fixture-owned row.
            for line in source.splitlines():
                if "session.delete(" not in line:
                    continue
                assert "link" in line or "fixture_id" in line, (seeder.__name__, line)

    def test_the_seed_never_promotes_an_ml_model(self, module):
        import inspect

        source = inspect.getsource(module.seed_ml)
        # The registry row stays staged and is not a production model.
        assert 'model.status = "staged"' in source
        assert "model.is_production = False" in source
        # And the fixture never claims the artifact was loaded.
        assert "ML_MODEL_PATH" not in source


# =============================================================================
# The behaviour against the three disposable demo databases
# =============================================================================

def _demo_database_urls() -> dict:
    """Return the three demo connection URLs, or an empty dict."""
    core = os.environ.get("DEMO_CORE_DATABASE_URL", "").strip()
    detection = os.environ.get("DEMO_DETECTION_DATABASE_URL", "").strip()
    ml = os.environ.get("DEMO_ML_DATABASE_URL", "").strip()
    if not (core and detection and ml):
        return {}
    return {"core": core, "detection": detection, "ml": ml}


DEMO_URLS = _demo_database_urls()

requires_demo_databases = pytest.mark.skipif(
    not DEMO_URLS,
    reason=(
        "the demo databases are not provisioned. Start the demo stack with "
        "'scripts/demo_stack.sh start' and export DEMO_CORE_DATABASE_URL, "
        "DEMO_DETECTION_DATABASE_URL and DEMO_ML_DATABASE_URL."
    ),
)


def _run_seed(*args: str) -> subprocess.CompletedProcess:
    """Run the seed script against the demo databases.

    The seed reads the demo environment FILE, and the file wins over the
    shell — that is the rule that keeps a stale exported variable from
    sending the fixtures into another stack's databases.  The harness
    therefore writes the three URLs into a throw-away environment file
    and points the seed at it, rather than relying on exported
    variables alone.
    """
    env = dict(os.environ)
    env["CORE_DATABASE_URL"] = DEMO_URLS["core"]
    env["DETECTION_DATABASE_URL"] = DEMO_URLS["detection"]
    env["ML_DATABASE_URL"] = DEMO_URLS["ml"]

    env_file = REPO_ROOT / ".ci" / "test-demo-fixtures.env"
    env_file.parent.mkdir(parents=True, exist_ok=True)
    env_file.write_text(
        f"CORE_DATABASE_URL={DEMO_URLS['core']}\n"
        f"DETECTION_DATABASE_URL={DEMO_URLS['detection']}\n"
        f"ML_DATABASE_URL={DEMO_URLS['ml']}\n",
        encoding="utf-8",
    )
    env["DEMO_ENV_FILE"] = str(env_file)

    return subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "demo_seed_demo.py"), *args],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )


def _count(url: str, sql: str) -> int:
    """Run a counting query against one database."""
    from sqlalchemy import create_engine, text

    engine = create_engine(url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            return int(connection.execute(text(sql)).scalar() or 0)
    finally:
        engine.dispose()


def _count_in(url: str, table: str, column: str, ids: list) -> int:
    """Count the rows of a table whose id is in ``ids``.

    The ids are bound as individual parameters with an explicit ``uuid``
    cast, because PostgreSQL will not compare a ``uuid`` column with a
    ``text`` array.
    """
    from sqlalchemy import create_engine, text

    ids = list(ids)
    if not ids:
        return 0

    engine = create_engine(url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            placeholders = ", ".join(f":id{index}" for index in range(len(ids)))
            parameters = {f"id{index}": value for index, value in enumerate(ids)}
            return int(
                connection.execute(
                    text(
                        f"SELECT count(*) FROM {table} "
                        f"WHERE {column} IN ({placeholders})"
                    ),
                    parameters,
                ).scalar()
                or 0
            )
    finally:
        engine.dispose()


@requires_demo_databases
class TestDemoSeedAgainstTheDemoDatabases:
    """The seed and the cleanup against the real demo databases."""

    @pytest.fixture(scope="class")
    def seeded(self):
        """Seed the demo databases and leave them seeded for the class."""
        result = _run_seed("--seed")
        assert result.returncode == 0, result.stderr
        return result

    def test_the_seed_succeeds(self, seeded):
        assert "the demo fixtures are seeded" in seeded.stdout

    def test_the_four_accounts_exist_with_their_roles(self, seeded):
        from sqlalchemy import create_engine, text

        engine = create_engine(DEMO_URLS["core"], pool_pre_ping=True)
        try:
            with engine.connect() as connection:
                rows = connection.execute(
                    text(
                        "SELECT u.username, r.role_id FROM users u "
                        "JOIN user_roles r ON r.user_id = u.id ORDER BY u.username, r.role_id"
                    )
                ).all()
        finally:
            engine.dispose()

        by_user: dict = {}
        for username, role_id in rows:
            by_user.setdefault(username, []).append(role_id)

        assert by_user["demo_user"] == ["USER"]
        assert by_user["demo_analyst"] == ["SOC_ANALYST", "USER"]
        assert by_user["demo_admin"] == ["SECURITY_ADMIN", "USER"]
        assert by_user["demo_manager"] == ["SECURITY_MANAGER", "USER"]

    def test_the_admin_account_really_requires_mfa(self, seeded):
        from sqlalchemy import create_engine, text

        engine = create_engine(DEMO_URLS["core"], pool_pre_ping=True)
        try:
            with engine.connect() as connection:
                value = connection.execute(
                    text(
                        "SELECT admin_mfa_required FROM users WHERE username = 'demo_admin'"
                    )
                ).scalar()
        finally:
            engine.dispose()
        assert value is True

    def test_every_alert_status_and_risk_level_is_present(self, seeded):
        from sqlalchemy import create_engine, text

        engine = create_engine(DEMO_URLS["detection"], pool_pre_ping=True)
        try:
            with engine.connect() as connection:
                rows = connection.execute(
                    text("SELECT status, risk_level FROM alerts")
                ).all()
        finally:
            engine.dispose()

        statuses = {row[0] for row in rows}
        risk_levels = {row[1] for row in rows}
        assert {"open", "acknowledged", "resolved", "false_positive"} <= statuses
        assert {"low", "medium", "high", "critical"} <= risk_levels

    def test_the_rule_only_alert_has_a_null_ml_score(self, seeded):
        # The rule-only fallback must carry a NULL ml_score — never a
        # zero.  A zero would be indistinguishable from "the model said
        # zero", which is a different statement.
        from sqlalchemy import create_engine, text

        engine = create_engine(DEMO_URLS["detection"], pool_pre_ping=True)
        try:
            with engine.connect() as connection:
                value = connection.execute(
                    text(
                        "SELECT ra.ml_score FROM risk_assessments ra "
                        "JOIN login_attempts la ON la.id = ra.login_attempt_id "
                        "WHERE la.username_attempted = 'demo_user' "
                        "  AND ra.ml_status = 'unavailable'"
                    )
                ).scalar()
        finally:
            engine.dispose()
        assert value is None

    def test_exactly_one_policy_is_active(self, seeded):
        count = _count(
            DEMO_URLS["detection"],
            "SELECT count(*) FROM policies WHERE is_active = TRUE",
        )
        assert count == 1

    def test_the_draft_policy_is_not_active(self, seeded):
        count = _count(
            DEMO_URLS["detection"],
            "SELECT count(*) FROM policies WHERE version = 'm13-demo-draft' AND is_active = FALSE",
        )
        assert count == 1

    def test_the_ml_model_is_never_promoted(self, seeded):
        count = _count(
            DEMO_URLS["ml"],
            "SELECT count(*) FROM model_versions WHERE is_production = TRUE",
        )
        assert count == 0

    def test_a_second_seed_does_not_duplicate_a_row(self, seeded):
        before = {
            "users": _count(DEMO_URLS["core"], "SELECT count(*) FROM users"),
            "sessions": _count(DEMO_URLS["core"], "SELECT count(*) FROM sessions"),
            "alerts": _count(DEMO_URLS["detection"], "SELECT count(*) FROM alerts"),
            "attempts": _count(
                DEMO_URLS["detection"], "SELECT count(*) FROM login_attempts"
            ),
            "timeline": _count(
                DEMO_URLS["detection"], "SELECT count(*) FROM alert_timeline"
            ),
            "policies": _count(DEMO_URLS["detection"], "SELECT count(*) FROM policies"),
            "inference": _count(DEMO_URLS["ml"], "SELECT count(*) FROM inference_logs"),
        }

        result = _run_seed("--seed")
        assert result.returncode == 0, result.stderr

        after = {
            "users": _count(DEMO_URLS["core"], "SELECT count(*) FROM users"),
            "sessions": _count(DEMO_URLS["core"], "SELECT count(*) FROM sessions"),
            "alerts": _count(DEMO_URLS["detection"], "SELECT count(*) FROM alerts"),
            "attempts": _count(
                DEMO_URLS["detection"], "SELECT count(*) FROM login_attempts"
            ),
            "timeline": _count(
                DEMO_URLS["detection"], "SELECT count(*) FROM alert_timeline"
            ),
            "policies": _count(DEMO_URLS["detection"], "SELECT count(*) FROM policies"),
            "inference": _count(DEMO_URLS["ml"], "SELECT count(*) FROM inference_logs"),
        }

        assert before == after

    def test_the_cleanup_does_not_touch_a_row_outside_the_fixtures(self, seeded):
        from sqlalchemy import create_engine, text

        # A row the fixture set did NOT create: it carries the demo
        # database's own default policy, which the seed never created.
        engine = create_engine(DEMO_URLS["detection"], pool_pre_ping=True)
        try:
            with engine.connect() as connection:
                before = connection.execute(
                    text("SELECT count(*) FROM policies WHERE version = 'v1.0'")
                ).scalar()
        finally:
            engine.dispose()

        # And a row in a table the cleanup does not own.
        core_engine = create_engine(DEMO_URLS["core"], pool_pre_ping=True)
        try:
            with core_engine.connect() as core_connection:
                roles_before = core_connection.execute(
                    text("SELECT count(*) FROM roles")
                ).scalar()
        finally:
            core_engine.dispose()

        assert int(before) >= 1

        result = _run_seed("--cleanup")
        assert result.returncode == 0, result.stderr

        engine = create_engine(DEMO_URLS["detection"], pool_pre_ping=True)
        try:
            with engine.connect() as connection:
                after = connection.execute(
                    text("SELECT count(*) FROM policies WHERE version = 'v1.0'")
                ).scalar()
        finally:
            engine.dispose()

        core_engine = create_engine(DEMO_URLS["core"], pool_pre_ping=True)
        try:
            with core_engine.connect() as core_connection:
                roles_after = core_connection.execute(
                    text("SELECT count(*) FROM roles")
                ).scalar()
        finally:
            core_engine.dispose()

        # The policy the demo did not create survived the cleanup.
        assert int(after) == int(before)
        # The roles survived too: they are not the fixture's to delete.
        assert int(roles_after) == int(roles_before)

    def test_the_cleanup_removes_the_fixture_rows(self, seeded):
        result = _run_seed("--cleanup")
        assert result.returncode == 0, result.stderr

        # The cleanup removes the rows of the FIXTURE SET — the rows whose
        # ids the seed derived from its UUIDv5 namespace.  It does not
        # remove every row of the table: the demo stack may hold rows
        # that the running application created (the alerts of the login
        # events, for instance), and those rows are not the fixture's to
        # delete.  Removing them would be the very bug the guard exists
        # to prevent.
        module = _load_script("demo_seed_demo.py")

        def fixture_ids(kind: str, keys) -> list:
            return [module.fixture_id(kind, key) for key in keys]

        alert_keys = [str(spec["key"]) for spec in module.DEMO_ALERTS]
        attempt_keys = [str(spec["key"]) for spec in module.DEMO_ALERTS]

        assert _count(DEMO_URLS["core"], "SELECT count(*) FROM users") == 0
        assert (
            _count_in(
                DEMO_URLS["detection"],
                "alerts",
                "id",
                fixture_ids(module.NS_ALERT, alert_keys),
            )
            == 0
        )
        assert (
            _count_in(
                DEMO_URLS["detection"],
                "login_attempts",
                "id",
                fixture_ids(module.NS_ATTEMPT, attempt_keys),
            )
            == 0
        )
        assert (
            _count_in(
                DEMO_URLS["ml"],
                "inference_logs",
                "id",
                fixture_ids(
                    module.NS_INFERENCE, [f"ok:{index}" for index in range(7)]
                ),
            )
            == 0
        )

    def test_the_cleanup_leaves_the_stack_usable(self, seeded):
        # After the cleanup the seed must be able to run again, and the
        # rows must come back with the SAME ids.
        _run_seed("--cleanup")
        result = _run_seed("--seed")
        assert result.returncode == 0, result.stderr

        module = _load_script("demo_seed_demo.py")
        expected = module.fixture_id(module.NS_USER, "demo_user")

        from sqlalchemy import create_engine, text

        engine = create_engine(DEMO_URLS["core"], pool_pre_ping=True)
        try:
            with engine.connect() as connection:
                value = connection.execute(
                    text("SELECT id FROM users WHERE username = 'demo_user'")
                ).scalar()
        finally:
            engine.dispose()

        assert str(value) == expected
