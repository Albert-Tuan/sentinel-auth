"""The pre-token probe must use the HARDENED guard, restore what it owns,
and compare the gate against a backend it controls.

===========================================================================
WHY THIS SUITE EXISTS
===========================================================================

``scripts/demo_pre_token_probe.py`` is the M13 acceptance evidence for the
pre-token detection gate: it runs the SAME risky login twice — once with
the gate ON and once with the gate OFF — and shows that only the gated
run withholds the token.

A probe that measures the gate has to satisfy three properties, and a
review of the probe at ``8229b7f`` found that it satisfied NONE of them:

  1. **THE TARGET GUARD.**  The probe used to check only that the
     database name ended with ``_demo``::

         database = make_url(url).database or ""
         if not database.endswith("_demo"):
             fail(...)

     A suffix check is not a target check.  A PostgreSQL URL carries a
     query string whose keys are libpq connection parameters, and libpq
     lets the query string OVERRIDE the parts of the URL::

         postgresql://demo:example@127.0.0.1/sentinel_core_demo?dbname=sentinel_core_test

         dialect.create_connect_args()  ->  {"host": "127.0.0.1",
                                             "dbname": "sentinel_core_test"}

     The suffix check saw ``sentinel_core_demo`` and approved the URL;
     the DRIVER was told to open ``sentinel_core_test`` — the regression
     suite's database.  The probe also built its engines from the RAW
     URL string, so the URL it validated and the URL it connected to were
     two different objects, and the comparison backend inherited the
     operator's shell, where a stray ``PGHOST`` or ``PGHOSTADDR`` could
     move the destination as well.

  2. **THE STATE RESTORATION.**  The probe activated the demo policy
     and returned ``None`` when there had been NO active policy at all;
     ``_restore_active_policy(None)`` then did nothing, so a policy that
     had NOT been in service before the run was still in service after
     it.  The one-time MFA flag was captured into a variable initialised
     to ``False``, so a failure BEFORE the flag was read still wrote
     ``False`` over a value the probe had never seen.  And the cleanup
     steps ran one after another in a single block, so a failure in the
     first step skipped the rest.

  3. **THE COMPARISON.**  The comparison backend started from
     ``dict(os.environ)`` and overrode only part of the configuration, so
     a stray variable in the operator's shell could change what the
     comparison measured.  The verdict leaned on the inequality of the
     two tokens as an independent proof of causation.

This suite pins the three properties.  It calls the REAL probe module —
no mocking of the guard, no mocking of the probe's own logic — and it
never opens a connection to a database it is not allowed to touch.

===========================================================================
THE SUITE HAS FOUR PARTS
===========================================================================

  * Part 1 — the guard integration: the probe refuses a URL that moves
    the destination, refuses a URL whose context, host or name is
    wrong, refuses a run that has not declared that it may write, and
    never creates an engine or spawns a backend when it refuses;
  * Part 2 — the state restoration: the snapshot/restore round trip for
    the policy slot and the MFA flag, including the "never captured"
    case and the "no policy was in service" case;
  * Part 3 — the cleanup independence: a failing cleanup step does not
    skip the steps that follow it, and a cleanup failure fails the run;
  * Part 4 — the comparison backend: the environment is assembled rather
    than inherited, the backend owns its port, and only the probe's own
    process is stopped.
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest
from sqlalchemy import create_engine, text

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"

#: The demo databases the guard accepts.  The suite never connects to
#: them; the names are here so that the URLs the probe is handed are the
#: ones the guard is supposed to accept.
DEMO_CORE_DB = "sentinel_core_demo"
DEMO_CORE_CI_DB = "sentinel_core_ci_demo"
DEMO_DETECTION_DB = "sentinel_detection_demo"
DEMO_DETECTION_CI_DB = "sentinel_detection_ci_demo"


def _load_script(name: str):
    """Import a script from ``scripts/`` by its file name."""
    path = SCRIPTS_DIR / name
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def probe():
    """The probe module itself, imported from ``scripts/``."""
    return _load_script("demo_pre_token_probe.py")


@pytest.fixture(scope="module")
def guard():
    """The hardened guard the probe is supposed to use."""
    return _load_script("e2e_fixtures_guard.py")


def _url(database: str, host: str = "127.0.0.1", port: int = 5432, query: Optional[Dict[str, str]] = None) -> str:
    """A connection URL for a demo database.

    The query parameters are passed in a DICTIONARY under ``query``, so
    that a parameter that happens to be called ``database`` or ``host``
    cannot collide with the URL's own parts.
    """
    suffix = ""
    if query:
        suffix = "?" + "&".join(f"{key}={value}" for key, value in query.items())
    return f"postgresql://sentinel:secret@{host}:{port}/{database}{suffix}"


def _demo_environment(**overrides: str) -> Dict[str, str]:
    """A demo environment the guard accepts."""
    environment = {
        "CORE_DATABASE_URL": _url(DEMO_CORE_DB),
        "DETECTION_DATABASE_URL": _url(DEMO_DETECTION_DB),
        "ML_DATABASE_URL": _url("sentinel_ml_demo"),
        "E2E_ALLOW_WRITE_TO": f"{DEMO_CORE_DB} {DEMO_DETECTION_DB}",
    }
    environment.update(overrides)
    return environment


# =============================================================================
# Part 1 — the guard integration
# =============================================================================

class TestTheProbeUsesTheHardenedGuard:
    """The probe must refuse a target the hardened guard refuses."""

    @pytest.fixture()
    def environment(self, monkeypatch):
        # The probe reads the write declaration from the process
        # environment, exactly like every other tool in this repository.
        # The test sets it explicitly, so the test does not depend on
        # whatever the shell that started the suite happened to carry.
        monkeypatch.setenv(
            "E2E_ALLOW_WRITE_TO", f"{DEMO_CORE_DB} {DEMO_DETECTION_DB}"
        )
        return _demo_environment()

    # --- the destination cannot be moved --------------------------------

    @pytest.mark.parametrize(
        "query",
        [
            {"dbname": "sentinel_core_test"},
            {"database": "sentinel_core_test"},
            {"host": "10.0.0.5"},
            {"hostaddr": "10.0.0.5"},
            {"service": "production"},
            {"port": "6432"},
        ],
    )
    def test_a_url_whose_query_moves_the_destination_is_refused(
        self, probe, environment, query
    ):
        environment["CORE_DATABASE_URL"] = _url(DEMO_CORE_DB, query=query)
        with pytest.raises(probe.DemoDatabaseRefusal) as refusal:
            probe._validated_urls(environment)
        assert refusal.value.layer in ("query", "context", "destination")

    def test_a_url_with_an_unknown_query_parameter_is_refused(self, probe, environment):
        environment["CORE_DATABASE_URL"] = _url(
            DEMO_CORE_DB, query={"options": "-c search_path=public"}
        )
        with pytest.raises(probe.DemoDatabaseRefusal):
            probe._validated_urls(environment)

    def test_a_repeated_query_parameter_is_refused(self, probe, environment):
        environment["CORE_DATABASE_URL"] = (
            _url(DEMO_CORE_DB) + "?sslmode=require&sslmode=disable"
        )
        with pytest.raises(probe.DemoDatabaseRefusal):
            probe._validated_urls(environment)

    # --- the context, the host and the name -----------------------------

    def test_a_core_url_that_points_at_the_detection_database_is_refused(
        self, probe, environment
    ):
        environment["CORE_DATABASE_URL"] = _url(DEMO_DETECTION_DB)
        with pytest.raises(probe.DemoDatabaseRefusal):
            probe._validated_urls(environment)

    def test_a_database_outside_the_allowlist_is_refused(self, probe, environment):
        # ``sentinel_core_demo_backup`` ends with neither marker, and it
        # would pass a naive suffix check on ``_demo``.
        environment["CORE_DATABASE_URL"] = _url("sentinel_core_demo_backup")
        with pytest.raises(probe.DemoDatabaseRefusal):
            probe._validated_urls(environment)

    def test_a_regression_suite_database_is_refused(self, probe, environment):
        environment["CORE_DATABASE_URL"] = _url("sentinel_core_test")
        with pytest.raises(probe.DemoDatabaseRefusal):
            probe._validated_urls(environment)

    def test_a_production_database_is_refused(self, probe, environment):
        environment["CORE_DATABASE_URL"] = _url("sentinel_core")
        with pytest.raises(probe.DemoDatabaseRefusal):
            probe._validated_urls(environment)

    def test_a_non_loopback_host_is_refused(self, probe, environment):
        environment["CORE_DATABASE_URL"] = _url(DEMO_CORE_DB, host="10.0.0.5")
        with pytest.raises(probe.DemoDatabaseRefusal):
            probe._validated_urls(environment)

    # --- the environment can move the destination ------------------------

    def test_an_overriding_libpq_variable_is_refused(self, probe, environment, monkeypatch):
        monkeypatch.setenv("PGHOSTADDR", "10.0.0.5")
        with pytest.raises(probe.DemoDatabaseRefusal) as refusal:
            probe._validated_urls(environment)
        assert refusal.value.layer == "environment"

    def test_a_defaulting_libpq_variable_is_refused_when_the_url_does_not_pin_it(
        self, probe, environment, monkeypatch
    ):
        """``PGDATABASE`` can move the destination when the URL does not pin it.

        The URL in this case names no database in its path — the
        ``dbname`` comes from the environment instead — so the guard
        cannot prove what the driver would open.
        """
        monkeypatch.setenv("PGDATABASE", "sentinel_core_test")
        environment["CORE_DATABASE_URL"] = "postgresql://sentinel:secret@127.0.0.1:5432"
        with pytest.raises(probe.DemoDatabaseRefusal) as refusal:
            probe._validated_urls(environment)
        assert refusal.value.layer in ("environment", "url", "query")

    def test_a_defaulting_libpq_variable_the_url_pins_is_not_a_refusal(
        self, probe, environment, monkeypatch
    ):
        """The URL pins ``dbname``, so ``PGDATABASE`` cannot move it."""
        monkeypatch.setenv("PGDATABASE", "sentinel_core_test")
        environment["CORE_DATABASE_URL"] = _url(DEMO_CORE_DB)
        validated = probe._validated_urls(environment)
        assert validated["core"].database == DEMO_CORE_DB

    # --- the write declaration is required -------------------------------

    def test_a_run_without_a_write_declaration_is_refused(self, probe, environment, monkeypatch):
        monkeypatch.delenv("E2E_ALLOW_WRITE_TO", raising=False)
        environment.pop("E2E_ALLOW_WRITE_TO", None)
        with pytest.raises(probe.DemoDatabaseRefusal) as refusal:
            probe._validated_urls(environment)
        assert refusal.value.layer == "permission"

    def test_a_declaration_for_another_database_is_refused(self, probe, environment, monkeypatch):
        monkeypatch.setenv("E2E_ALLOW_WRITE_TO", "sentinel_core_ci_demo")
        with pytest.raises(probe.DemoDatabaseRefusal) as refusal:
            probe._validated_urls(environment)
        assert refusal.value.layer == "permission"

    # --- the refusal happens BEFORE anything is opened -------------------

    def test_a_refused_target_never_reaches_create_engine(self, probe, environment, monkeypatch):
        """No engine is built when the guard refuses."""
        environment["CORE_DATABASE_URL"] = _url(
            DEMO_CORE_DB, query={"dbname": "sentinel_core_test"}
        )

        built: List[Any] = []
        original = probe.create_engine

        def spy(url, *args, **kwargs):
            built.append(url)
            return original(url, *args, **kwargs)

        monkeypatch.setattr(probe, "create_engine", spy)
        with pytest.raises(probe.DemoDatabaseRefusal):
            probe._validated_urls(environment)
        assert built == []

    def test_a_refused_target_never_spawns_the_comparison_backend(
        self, probe, environment, monkeypatch
    ):
        """No subprocess is started when the guard refuses."""
        environment["CORE_DATABASE_URL"] = _url(
            DEMO_CORE_DB, query={"dbname": "sentinel_core_test"}
        )

        spawned: List[Any] = []

        class _RefusedPopen:
            def __init__(self, *args, **kwargs):
                spawned.append(args)
                raise AssertionError("the probe must not spawn a backend")

        monkeypatch.setattr(probe.subprocess, "Popen", _RefusedPopen)
        with pytest.raises(probe.DemoDatabaseRefusal):
            probe._validated_urls(environment)
        assert spawned == []

    # --- the valid targets are accepted ---------------------------------

    def test_the_local_demo_databases_are_accepted(self, probe, environment):
        environment["CORE_DATABASE_URL"] = _url(DEMO_CORE_DB)
        environment["DETECTION_DATABASE_URL"] = _url(DEMO_DETECTION_DB)
        validated = probe._validated_urls(environment)
        assert validated["core"].database == DEMO_CORE_DB
        assert validated["detection"].database == DEMO_DETECTION_DB

    def test_the_ci_demo_databases_are_accepted(self, probe):
        environment = _demo_environment(
            CORE_DATABASE_URL=_url(DEMO_CORE_CI_DB),
            DETECTION_DATABASE_URL=_url(DEMO_DETECTION_CI_DB),
            E2E_ALLOW_WRITE_TO=f"{DEMO_CORE_CI_DB} {DEMO_DETECTION_CI_DB}",
        )
        validated = probe._validated_urls(environment)
        assert validated["core"].database == DEMO_CORE_CI_DB
        assert validated["detection"].database == DEMO_DETECTION_CI_DB

    def test_the_engine_is_built_from_the_validated_url_object(self, probe, environment, monkeypatch):
        """The engine receives the very object the guard validated."""
        validated = probe._validated_urls(environment)

        built: List[Any] = []
        original = probe.create_engine

        def spy(url, *args, **kwargs):
            built.append(url)
            return original(url, *args, **kwargs)

        monkeypatch.setattr(probe, "create_engine", spy)
        probe._engine(validated["core"])
        assert built == [validated["core"]]


# =============================================================================
# Part 2 — the state restoration
# =============================================================================

class TestThePolicySnapshot:
    """The three states of the active slot must stay distinguishable."""

    def test_the_demo_policy_already_in_service_owns_nothing(self, probe):
        snapshot = probe.PolicySnapshot("already_active", policy_id="p1")
        assert snapshot.changed is False
        assert snapshot.owns_policy_id is None

    def test_another_policy_in_service_is_owned(self, probe):
        snapshot = probe.PolicySnapshot("other_active", policy_id="p2")
        assert snapshot.changed is True
        assert snapshot.owns_policy_id == "p2"

    def test_no_policy_in_service_is_owned(self, probe):
        """The state a plain ``None`` used to lose."""
        snapshot = probe.PolicySnapshot("none_active")
        assert snapshot.changed is True
        assert snapshot.owns_policy_id is None

    def test_the_three_states_are_distinguishable(self, probe):
        states = {
            probe.PolicySnapshot("already_active", "p1").state,
            probe.PolicySnapshot("other_active", "p2").state,
            probe.PolicySnapshot("none_active").state,
        }
        assert len(states) == 3

    def test_a_snapshot_without_a_state_changes_nothing(self, probe):
        assert probe.PolicySnapshot("already_active", "p1").changed is False


class TestTheMfaSnapshot:
    """``False`` and "never read" must not be the same thing."""

    def test_a_captured_false_is_a_captured_value(self, probe):
        snapshot = probe.MfaSnapshot(captured=True, previous=False)
        assert snapshot.captured is True
        assert snapshot.previous is False
        assert snapshot.changed is True

    def test_a_captured_true_is_a_captured_value(self, probe):
        snapshot = probe.MfaSnapshot(captured=True, previous=True)
        assert snapshot.changed is True

    def test_a_value_that_was_never_read_is_not_a_value(self, probe):
        snapshot = probe.MfaSnapshot(captured=False, previous=None)
        assert snapshot.captured is False
        assert snapshot.changed is False

    def test_no_snapshot_at_all_is_not_a_value(self, probe):
        assert probe.MfaSnapshot(captured=False).changed is False


class TestTheRestoreRefusesToWriteWithoutASnapshot:
    """A restore must not write when it does not know the old value."""

    def test_the_mfa_flag_is_not_written_without_a_snapshot(self, probe, monkeypatch):
        written: List[Any] = []

        class _Engine:
            def connect(self):
                raise AssertionError("no connection may be opened")

            def dispose(self):
                return None

        monkeypatch.setattr(probe, "_engine", lambda url: _Engine())
        monkeypatch.setattr(
            probe.text, "__call__", lambda *a, **k: written.append(a) or None
        )

        probe._restore_one_time_mfa(None, "demo_user", None)
        probe._restore_one_time_mfa(None, "demo_user", probe.MfaSnapshot(captured=False))
        assert written == []

    def test_the_policy_slot_is_not_moved_without_a_snapshot(self, probe, monkeypatch):
        class _Engine:
            def connect(self):
                raise AssertionError("no connection may be opened")

            def dispose(self):
                return None

        monkeypatch.setattr(probe, "_engine", lambda url: _Engine())
        probe._restore_active_policy(None, None)
        probe._restore_active_policy(None, probe.PolicySnapshot("already_active", "p1"))


class TestTheRestoreReachesTheDatabase:
    """Against a real SQLite database, the restore does what it says."""

    @pytest.fixture()
    def engine(self, tmp_path):
        # A FILE-backed SQLite: the restore disposes the engine when it is
        # done, and an in-memory database would be dropped with it.
        eng = create_engine(f"sqlite:///{tmp_path / 'policies.db'}")
        with eng.begin() as connection:
            connection.execute(
                text(
                    "CREATE TABLE policies ("
                    " id TEXT PRIMARY KEY, version TEXT, is_active INTEGER, "
                    " activated_at TEXT, deactivated_at TEXT)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO policies (id, version, is_active, activated_at, "
                    "deactivated_at) VALUES "
                    "('demo', 'm13-demo-active', 0, NULL, NULL), "
                    "('other', 'm13-demo-draft', 0, 'T1', NULL)"
                )
            )
        yield eng
        eng.dispose()

    @staticmethod
    def _activate(engine, policy_id: str) -> None:
        with engine.begin() as connection:
            connection.execute(
                text("UPDATE policies SET is_active = 1 WHERE id = :id"),
                {"id": policy_id},
            )

    def _policy_rows(self, engine):
        with engine.connect() as connection:
            return {
                str(row[0]): (bool(row[1]), row[2], row[3])
                for row in connection.execute(
                    text("SELECT version, is_active, activated_at, deactivated_at "
                         "FROM policies")
                ).fetchall()
            }

    def test_the_other_policy_goes_back_into_service(self, probe, engine, monkeypatch):
        """Case B: the policy that was in service comes back."""
        monkeypatch.setattr(probe, "_engine", lambda url: engine)
        self._activate(engine, "other")
        snapshot = probe.PolicySnapshot(
            "other_active", policy_id="other", activated_at="T1", deactivated_at=None
        )
        probe._restore_active_policy(None, snapshot)
        rows = self._policy_rows(engine)
        assert rows["m13-demo-draft"][0] is True
        assert rows["m13-demo-draft"][1] == "T1"
        assert rows["m13-demo-active"][0] is False

    def test_no_policy_is_left_in_service_when_there_was_none(self, probe, engine, monkeypatch):
        """Case C: the state a plain ``None`` used to lose."""
        monkeypatch.setattr(probe, "_engine", lambda url: engine)
        # The probe activated the demo policy; the restore must undo it.
        self._activate(engine, "demo")
        snapshot = probe.PolicySnapshot("none_active")
        probe._restore_active_policy(None, snapshot)
        rows = self._policy_rows(engine)
        assert rows["m13-demo-active"][0] is False
        with engine.connect() as connection:
            active = connection.execute(
                text("SELECT count(*) FROM policies WHERE is_active = 1")
            ).scalar()
        assert active == 0

    def test_the_restore_does_not_touch_every_active_policy(self, probe, engine, monkeypatch):
        """The restore moves ONE row, not "every policy that is active"."""
        monkeypatch.setattr(probe, "_engine", lambda url: engine)
        self._activate(engine, "other")
        snapshot = probe.PolicySnapshot(
            "other_active", policy_id="other", activated_at="T1", deactivated_at=None
        )
        probe._restore_active_policy(None, snapshot)
        rows = self._policy_rows(engine)
        # The demo policy was deactivated, and only the demo policy.
        assert rows["m13-demo-active"][0] is False


# =============================================================================
# Part 3 — the cleanup independence
# =============================================================================

class TestTheCleanupTriesEveryStep:
    """A failing cleanup step must not skip the steps that follow it."""

    @pytest.fixture()
    def state(self, probe):
        return probe.ProbeState()

    def test_every_step_is_tried_even_when_the_first_one_fails(
        self, probe, state, monkeypatch
    ):
        attempted: List[str] = []

        def failing_history(url, event_ids):
            attempted.append("history")
            raise RuntimeError("the history cleanup failed")

        def working_mfa(url, username, snapshot):
            attempted.append("mfa")

        def working_policy(url, snapshot):
            attempted.append("policy")

        monkeypatch.setattr(probe, "_cleanup_risky_history", failing_history)
        monkeypatch.setattr(probe, "_restore_one_time_mfa", working_mfa)
        monkeypatch.setattr(probe, "_restore_active_policy", working_policy)
        monkeypatch.setattr(probe, "_stop_comparison", lambda s: attempted.append("stop"))

        probe._cleanup(state, None, None, "demo_user")

        assert "history" in attempted
        assert "mfa" in attempted, "the MFA restore was skipped by a failing step"
        assert "policy" in attempted, "the policy restore was skipped by a failing step"

    def test_a_failing_step_is_recorded_without_losing_the_others(
        self, probe, state, monkeypatch
    ):
        monkeypatch.setattr(
            probe,
            "_cleanup_risky_history",
            lambda url, event_ids: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        monkeypatch.setattr(probe, "_restore_one_time_mfa", lambda *a: None)
        monkeypatch.setattr(probe, "_restore_active_policy", lambda *a: None)
        monkeypatch.setattr(probe, "_stop_comparison", lambda s: None)

        probe._cleanup(state, None, None, "demo_user")
        assert len(state.cleanup_errors) == 1
        assert "boom" in state.cleanup_errors[0]

    def test_several_failing_steps_are_all_recorded(self, probe, state, monkeypatch):
        def boom(*args, **kwargs):
            raise RuntimeError("boom")

        monkeypatch.setattr(probe, "_cleanup_risky_history", boom)
        monkeypatch.setattr(probe, "_restore_one_time_mfa", boom)
        monkeypatch.setattr(probe, "_restore_active_policy", boom)
        monkeypatch.setattr(probe, "_stop_comparison", boom)

        probe._cleanup(state, None, None, "demo_user")
        # Every step of the cleanup is tried, and every failure is kept.
        assert len(state.cleanup_errors) == 4

    def test_a_cleanup_error_does_not_contain_a_secret(self, probe, state, monkeypatch):
        def boom(url, event_ids):
            raise RuntimeError("failed for postgresql://sentinel:sup3rs3cret@host/db")

        monkeypatch.setattr(probe, "_cleanup_risky_history", boom)
        monkeypatch.setattr(probe, "_restore_one_time_mfa", lambda *a: None)
        monkeypatch.setattr(probe, "_restore_active_policy", lambda *a: None)
        monkeypatch.setattr(probe, "_stop_comparison", lambda s: None)

        probe._cleanup(state, None, None, "demo_user")
        assert "sup3rs3cret" not in " ".join(state.cleanup_errors)
        assert "<redacted>" in " ".join(state.cleanup_errors)


class TestTheCleanupFailureFailsTheRun:
    """A run that could not clean up after itself is not a clean run."""

    def test_the_probe_returns_a_failure_when_the_cleanup_failed(
        self, probe, monkeypatch, tmp_path
    ):
        """The probe's exit code reflects the cleanup errors."""
        environment = tmp_path / "demo.env"
        environment.write_text(
            "CORE_DATABASE_URL=" + _url(DEMO_CORE_DB) + "\n"
            "DETECTION_DATABASE_URL=" + _url(DEMO_DETECTION_DB) + "\n"
            "INTERNAL_SECRET=verification-only\n"
            "CORE_APP_URL=http://127.0.0.1:58000\n",
            encoding="utf-8",
        )

        monkeypatch.setenv("DEMO_ENV_FILE", str(environment))
        monkeypatch.setenv("E2E_ALLOW_WRITE_TO", f"{DEMO_CORE_DB} {DEMO_DETECTION_DB}")

        # The probe never reaches a database: the account lookup fails
        # first, which sends it down the error path, where the cleanup
        # still has to run and to be reported.
        class _NoRows:
            def execute(self, *args, **kwargs):
                return self

            def fetchone(self):
                return None

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        class _Engine:
            def connect(self):
                return _NoRows()

            def dispose(self):
                return None

        monkeypatch.setattr(probe, "_engine", lambda url: _Engine())

        def failing_cleanup(state, core, det, user):
            state.record_cleanup_error(
                "remove the seeded risky history", RuntimeError("boom")
            )

        monkeypatch.setattr(probe, "_cleanup", failing_cleanup)

        with pytest.raises(SystemExit) as exit_info:
            probe.main()
        assert exit_info.value.code == 1


# =============================================================================
# Part 4 — the comparison backend
# =============================================================================

class TestTheComparisonEnvironment:
    """The comparison backend's environment is ASSEMBLED, not inherited."""

    @pytest.fixture()
    def environment(self):
        return _demo_environment(
            CORE_APP_URL="http://127.0.0.1:58000",
            DETECTION_URL="http://127.0.0.1:58000",
            INTERNAL_SECRET="verification-only",
            MFA_SMTP_PORT="51025",
            CORS_ALLOWED_ORIGINS="http://127.0.0.1:55173",
            FORWARDED_ALLOW_IPS="127.0.0.1",
        )

    def test_the_gate_is_off_and_the_event_delivery_is_on(self, probe, environment):
        child = probe._comparison_environment(environment)
        assert child["RUN_PRE_TOKEN_CHECK"] == "0"
        assert child["RUN_LOGIN_EVENT_DELIVERY"] == "1"

    def test_the_legacy_single_database_fallback_stays_off(self, probe, environment):
        child = probe._comparison_environment(environment)
        assert child["ALLOW_LEGACY_SINGLE_DB"] == "0"

    def test_a_stray_variable_of_the_shell_is_not_inherited(self, probe, environment, monkeypatch):
        """A stray ``RUN_PRE_TOKEN_CHECK`` in the operator's shell is ignored."""
        monkeypatch.setenv("RUN_PRE_TOKEN_CHECK", "1")
        monkeypatch.setenv("MFA_SMTP_PORT", "10250")
        monkeypatch.setenv("CORE_APP_URL", "http://elsewhere:1")
        monkeypatch.setenv("DATABASE_URL", "postgresql://sentinel:x@evil/db")
        monkeypatch.setenv("PGHOSTADDR", "10.0.0.5")
        monkeypatch.setenv("PGSERVICE", "production")

        child = probe._comparison_environment(environment)

        assert child["RUN_PRE_TOKEN_CHECK"] == "0"
        assert child["MFA_SMTP_PORT"] == "51025"
        assert child["CORE_APP_URL"] == "http://127.0.0.1:58000"
        assert "DATABASE_URL" not in child
        assert "PGHOSTADDR" not in child
        assert "PGSERVICE" not in child

    def test_only_the_allowlisted_variables_are_present(self, probe, environment):
        child = probe._comparison_environment(environment)
        allowed = set(probe.COMPARISON_ENV_ALLOWLIST) | {
            "PATH",
            "HOME",
            "PYTHONUNBUFFERED",
            "RUN_PRE_TOKEN_CHECK",
            "RUN_LOGIN_EVENT_DELIVERY",
            "ALLOW_LEGACY_SINGLE_DB",
        }
        assert set(child) <= allowed

    def test_the_database_urls_of_the_demo_file_are_the_ones_forwarded(
        self, probe, environment
    ):
        child = probe._comparison_environment(environment)
        assert child["CORE_DATABASE_URL"] == environment["CORE_DATABASE_URL"]
        assert child["DETECTION_DATABASE_URL"] == environment["DETECTION_DATABASE_URL"]

    def test_a_missing_variable_is_simply_absent(self, probe, environment):
        environment.pop("CORS_ALLOWED_ORIGINS", None)
        child = probe._comparison_environment(environment)
        assert "CORS_ALLOWED_ORIGINS" not in child


class TestTheComparisonBackendOwnsItsPort:
    """The probe must never talk to a server it did not start."""

    def test_the_backend_is_started_on_an_ephemeral_port(self, probe):
        """``--port 0`` lets the operating system pick a free port.

        A port that was checked to be free can be taken by somebody else
        before the child binds it, and a server that was already
        listening would answer the readiness probe while the probe's own
        child is still starting up.
        """
        source = (SCRIPTS_DIR / "demo_pre_token_probe.py").read_text(encoding="utf-8")
        assert '"--port", "0"' in source
        assert '"--port", str(port)' not in source

    def test_the_reported_port_is_parsed_from_the_child_itself(self, probe):
        match = probe._UVICORN_PORT_PATTERN.search(
            "INFO:     Uvicorn running on http://127.0.0.1:37517 (Press CTRL+C to quit)"
        )
        assert match is not None
        assert match.group(1) == "37517"

    def test_a_port_that_is_not_the_child_own_is_not_accepted(self, probe):
        assert probe._UVICORN_PORT_PATTERN.search("nothing here") is None

    def test_the_backend_stops_only_its_own_process(self, probe):
        """The stop goes through the probe's own handle, never a port."""
        recorded: List[str] = []

        class _Process:
            def poll(self):
                return None

            def terminate(self):
                recorded.append("terminate")

            def wait(self, timeout=None):
                recorded.append("wait")
                return 0

            def kill(self):
                recorded.append("kill")

        backend = probe.ComparisonBackend(_Process(), 12345)
        backend.stop()
        assert recorded == ["terminate", "wait"]

    def test_an_already_stopped_backend_is_not_stopped_twice(self, probe):
        recorded: List[str] = []

        class _Process:
            def poll(self):
                return 0

            def terminate(self):
                recorded.append("terminate")

            def wait(self, timeout=None):
                recorded.append("wait")

        probe.ComparisonBackend(_Process(), 12345).stop()
        assert recorded == []

    def test_the_probe_never_looks_a_process_up_by_port(self, probe):
        """No ``pkill``, no ``lsof``, no port-based kill."""
        source = (SCRIPTS_DIR / "demo_pre_token_probe.py").read_text(encoding="utf-8")
        for forbidden in ("pkill", "killall", "lsof", "fuser"):
            assert forbidden not in source


class TestTheComparisonBackendIsNotSpawnedWhenTheGuardRefuses:
    """The guard runs BEFORE the backend is started."""

    def test_the_guard_runs_before_the_backend_is_started(self, probe):
        source = (SCRIPTS_DIR / "demo_pre_token_probe.py").read_text(encoding="utf-8")
        guard_at = source.index("_validated_urls(env)")
        backend_at = source.index("_start_backend_without_the_gate(env)")
        assert guard_at < backend_at


class TestTheSubprocessLifecycle:
    """The comparison backend is a REAL process, and it is really stopped."""

    def test_a_spawned_backend_is_stopped_by_the_probe(self):
        """A real child process is started and stopped through the handle.

        The child is a harmless ``sleep``, not the API: the test is about
        the LIFECYCLE, and a full API would make the suite slow and
        would need a database.
        """
        module = _load_script("demo_pre_token_probe.py")
        process = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        backend = module.ComparisonBackend(process, 65000)
        assert process.poll() is None
        backend.stop()
        assert process.poll() is not None
        assert process.returncode is not None
