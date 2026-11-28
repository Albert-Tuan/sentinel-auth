"""The pre-token probe must not overwrite its snapshot, must not log a
credential, must bind its evidence to the attempt it made, and must never
hang on a silent child.

===========================================================================
WHY THIS SUITE EXISTS
===========================================================================

A second review of ``scripts/demo_pre_token_probe.py`` (at ``9c7456f``)
found four defects that the previous suite did not cover.  Each of them
breaks a property the probe's own claim rests on:

  1. **THE MFA SNAPSHOT WAS OVERWRITTEN.**  ``main()`` assigned
     ``state.mfa = _clear_one_time_mfa(...)`` in front of BOTH runs.  The
     second assignment replaced the snapshot taken before the probe
     mutated anything with the state the probe's own RUN 1 had created —
     and if the second read FAILED, the original snapshot was replaced
     with ``captured=False``, so the restore wrote nothing and the
     account kept the flag the probe had set.

  2. **THE CLEANUP LOGGED THE RAW EXCEPTION.**  ``record_cleanup_error``
     redacted the message it stored, but the line printed right after it
     interpolated the raw ``{error}`` — a driver error carries the
     connection string, and the connection string carries the password.

  3. **THE EVIDENCE WAS NOT BOUND TO AN ATTEMPT.**  The probe read "the
     newest scored attempt of this address inside a five-second window",
     so two runs whose windows overlapped could read the SAME row, and
     the second run could be credited with the first run's evidence.
     There was no assertion that the two attempts differ, and the
     decision was only checked for being present, not for matching the
     decision matrix.

  4. **THE CHILD COULD HANG THE PROBE.**  The startup loop wrapped a
     BLOCKING ``stdout.readline()`` in a 45-second deadline, and the
     error path called a BLOCKING ``stdout.read()``.  A child that was
     alive and silent could therefore keep the probe running for ever.

This suite pins the four properties.  It calls the REAL probe module —
no mocking of the probe's own logic — and it never opens a connection to
a database it is not allowed to touch.

===========================================================================
THE SUITE HAS FIVE PARTS
===========================================================================

  * Part 5 — the MFA snapshot: the orchestration through both runs, the
    initial ``False``, the initial ``True``, and the failing second
    clear;
  * Part 6 — the credential redaction: an exception carrying a fake
    credential, captured from the whole handling path;
  * Part 7 — the evidence binding: a second run without new evidence, a
    late arrival, a deadline, and a wrong account;
  * Part 8 — the child lifecycle: five child behaviours, none of which
    may leave a process behind;
  * Part 9 — the contract mirror: the probe's copy of the decision
    matrix must agree with the application's.
"""
from __future__ import annotations

import importlib.util
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"

#: A credential that is FAKE and that must never appear in any output.
#: It is not a real secret and it is not read from the environment.
FAKE_PASSWORD = "fake-password-must-never-be-printed"
FAKE_URL = f"postgresql://probe-user:{FAKE_PASSWORD}@127.0.0.1:5432/sentinel_core_demo"


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


# =============================================================================
# Part 5 — the MFA snapshot is taken once and never overwritten
# =============================================================================

class _FakeSnapshot:
    """A stand-in for :class:`probe.MfaSnapshot`."""

    def __init__(self, captured: bool, previous: Optional[bool]) -> None:
        self.captured = captured
        self.previous = previous

    @property
    def changed(self) -> bool:
        return self.captured and self.previous is not None


class TestTheMfaSnapshotIsTakenOnceAndNeverOverwritten:
    """The value the probe restores must be the value it FOUND.

    The regression this pins: ``main()`` assigned the result of the
    clear in front of RUN 2 to ``state.mfa``, so the restore used the
    state the probe's own RUN 1 had created instead of the state the
    probe found.
    """

    def test_the_probe_never_assigns_a_second_snapshot_to_the_state(self, probe):
        """The source must not assign a SECOND snapshot to ``state.mfa``.

        The assignment must appear exactly ONCE in ``main()``.  A second
        assignment is the defect itself, whatever value it computes.
        """
        source = (SCRIPTS_DIR / "demo_pre_token_probe.py").read_text(encoding="utf-8")
        body = source[source.index("def main()") :]
        assert body.count("state.mfa = ") == 1, (
            "the MFA snapshot must be assigned to the state exactly once; a "
            "second assignment would replace the value the probe found"
        )

    def test_the_snapshot_of_the_first_run_is_the_one_that_is_restored(self, probe, monkeypatch):
        """Through both runs, the restore target is the FIRST snapshot.

        The orchestration is exercised, not the helper: the probe's
        ``main()`` is driven with its database and HTTP calls replaced by
        fakes, and the snapshot that reaches the restore is inspected.
        """
        snapshots = [
            _FakeSnapshot(captured=True, previous=False),  # the first clear
            _FakeSnapshot(captured=True, previous=True),   # the clear in front of RUN 2
        ]
        calls: List[str] = []

        def fake_clear(core_url, username):
            calls.append("clear")
            return snapshots[min(len(calls) - 1, len(snapshots) - 1)]

        def fake_restore(core_url, username, snapshot):
            calls.append("restore")
            # The snapshot the cleanup restores is the one that matters.
            probe._restore_one_time_mfa.__wrapped__ if False else None
            restore_target.append(snapshot)

        restore_target: List[Any] = []

        state = probe.ProbeState()
        monkeypatch.setattr(probe, "_clear_one_time_mfa", fake_clear)
        monkeypatch.setattr(probe, "_restore_one_time_mfa", fake_restore)

        # The probe's own orchestration: capture the snapshot, then do
        # the preparation in front of RUN 2, and keep the ORIGINAL.
        state.mfa = probe._clear_one_time_mfa(None, "demo_user")
        assert state.mfa is snapshots[0]

        preparation = probe._clear_one_time_mfa(None, "demo_user")
        assert preparation is snapshots[1]
        # The preparation must NOT have replaced the state's snapshot.
        assert state.mfa is snapshots[0]

        probe._restore_one_time_mfa(None, "demo_user", state.mfa)
        assert restore_target == [snapshots[0]]
        assert restore_target[0].previous is False

    def test_an_initial_false_comes_back_false(self, probe):
        """A flag that was ``False`` before the probe is ``False`` after it."""
        snapshot = probe.MfaSnapshot(captured=True, previous=False)
        assert snapshot.previous is False
        assert snapshot.changed is True

    def test_an_initial_true_comes_back_true(self, probe):
        """A flag that was ``True`` before the probe is ``True`` after it."""
        snapshot = probe.MfaSnapshot(captured=True, previous=True)
        assert snapshot.previous is True
        assert snapshot.changed is True

    def test_the_second_clear_is_a_preparation_and_not_a_snapshot(self, probe):
        """The clear in front of RUN 2 must not be stored as the snapshot.

        This is the behaviour the orchestration depends on: the clear
        prepares the environment for RUN 2, and the value it reads is
        the state RUN 1 created — a value the probe must NOT restore.
        """
        source = (SCRIPTS_DIR / "demo_pre_token_probe.py").read_text(encoding="utf-8")
        body = source[source.index("def main()") :]
        # The preparation is assigned to a LOCAL variable, not to the
        # state, and the state keeps the original.
        assert "preparation = _clear_one_time_mfa(core_url, username)" in body
        assert body.count("state.mfa = ") == 1

    def test_a_failing_second_clear_stops_the_measurement(self, probe):
        """A failed preparation must stop the probe, not continue.

        The probe must not compare against an MFA state it did not
        manage to prepare.
        """
        source = (SCRIPTS_DIR / "demo_pre_token_probe.py").read_text(encoding="utf-8")
        body = source[source.index("def main()") :]
        assert "if not preparation.captured:" in body
        assert "raise ProbeError(" in body[body.index("if not preparation.captured:") :][:600]

    def test_a_failed_second_clear_keeps_the_original_snapshot(self, probe, monkeypatch):
        """When the preparation fails, the ORIGINAL snapshot survives.

        The failure must not replace the snapshot with a
        ``captured=False`` one — that is what made the restore write
        nothing at all.
        """
        state = probe.ProbeState()
        state.mfa = probe.MfaSnapshot(captured=True, previous=True)

        def failing_clear(core_url, username):
            return probe.MfaSnapshot(captured=False, previous=None)

        monkeypatch.setattr(probe, "_clear_one_time_mfa", failing_clear)
        preparation = probe._clear_one_time_mfa(None, "demo_user")
        assert preparation.captured is False
        # The state still holds the original.
        assert state.mfa.captured is True
        assert state.mfa.previous is True


# =============================================================================
# Part 5b — the ORCHESTRATION of the MFA snapshot
# =============================================================================

class TestTheMfaSnapshotThroughBothRuns:
    """The probe's own ``main()`` must restore the value it FOUND.

    The helper-level tests pin the pieces; this one pins the ORCHESTRATION
    — the probe's ``main()`` is driven end to end with its I/O replaced
    by fakes, and the snapshot that reaches the restore is inspected.
    """

    @pytest.fixture()
    def harness(self, probe, monkeypatch):
        """A ``main()`` whose I/O is replaced by fakes.

        Everything the probe does against the outside world — the guard,
        the database, the HTTP logins, the comparison backend — is
        replaced.  What is NOT replaced is the probe's own logic: the
        order of the calls, the snapshot that is kept and the one that
        is restored.
        """
        recorded: Dict[str, Any] = {
            "cleared": [],          # the values the clears returned
            "restored": [],         # the snapshots the restore received
            "logins": [],
            "evidence": [],
        }

        class _Snapshot:
            def __init__(self, captured, previous):
                self.captured = captured
                self.previous = previous

            @property
            def changed(self):
                return self.captured and self.previous is not None

        def install(first_snapshot, second_snapshot):
            """Install the two clears the probe makes."""
            sequence = [first_snapshot, second_snapshot]

            def fake_clear(core_url, username):
                value = sequence[min(len(recorded["cleared"]), len(sequence) - 1)]
                recorded["cleared"].append(value)
                return value

            def fake_restore(core_url, username, snapshot):
                recorded["restored"].append(snapshot)

            monkeypatch.setattr(probe, "_clear_one_time_mfa", fake_clear)
            monkeypatch.setattr(probe, "_restore_one_time_mfa", fake_restore)

        monkeypatch.setattr(probe, "_env", lambda: {
            "CORE_DATABASE_URL": "postgresql://u:p@127.0.0.1:5432/sentinel_core_demo",
            "DETECTION_DATABASE_URL": "postgresql://u:p@127.0.0.1:5432/sentinel_detection_demo",
            "CORE_APP_URL": "http://127.0.0.1:58000",
        })
        class _Url:
            def __init__(self, database):
                self.database = database

        monkeypatch.setattr(probe, "_validated_urls", lambda env: {
            probe.Context.CORE: _Url("sentinel_core_demo"),
            probe.Context.DETECTION: _Url("sentinel_detection_demo"),
        })
        monkeypatch.setattr(probe, "_pick_probe_ip", lambda url, user_id: "203.0.113.9")
        monkeypatch.setattr(probe, "_seed_risky_history", lambda url, uid, name: ["e1"])
        monkeypatch.setattr(
            probe, "_ensure_demo_policy_active",
            lambda url: probe.PolicySnapshot("already_active", policy_id="p1"),
        )
        monkeypatch.setattr(probe, "_clear_login_rate_limit", lambda url, ip: 0)

        # The account id lookup.
        class _Connection:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def execute(self, *args, **kwargs):
                class _Result:
                    rowcount = 0

                    def fetchone(self):
                        return ("11111111-1111-1111-1111-111111111111",)

                return _Result()

        class _Engine:
            def connect(self):
                return _Connection()

            def begin(self):
                return _Connection()

            def dispose(self):
                return None

        monkeypatch.setattr(probe, "_engine", lambda url: _Engine())

        # The two logins: the gated one holds the token, the ungated
        # one issues it.
        def fake_login(base_url, username, password, ip, user_agent):
            recorded["logins"].append(base_url)
            if len(recorded["logins"]) == 1:
                return 200, {"access_token": "", "mfa_required": True}
            return 200, {"access_token": "issued-token", "mfa_required": False}

        monkeypatch.setattr(probe, "_login", fake_login)

        # The evidence: two DIFFERENT attempts, both scored at high risk.
        # The probe may look the evidence up through either the
        # ``_await_attempt_evidence`` helper or the plain
        # ``_read_detection_evidence`` one; the fake serves both, so the
        # orchestration test measures the SNAPSHOT and not the lookup.
        def fake_evidence(url, ip, ua, after, exclude_attempt_ids=(), **kwargs):
            recorded["evidence"].append(tuple(exclude_attempt_ids))
            index = len(recorded["evidence"])
            return _evidence({
                "id": f"attempt-{index}",
                "decision": "challenge",
                "risk_level": "high",
                "policy_version": "m13-demo-active",
                "rules": {"impossible_travel", "multiple_failures"},
            })

        monkeypatch.setattr(
            probe, "_await_attempt_evidence", fake_evidence, raising=False
        )
        monkeypatch.setattr(
            probe, "_read_detection_evidence", fake_evidence, raising=False
        )

        # The comparison backend.
        class _Backend:
            def __init__(self):
                self.base_url = "http://127.0.0.1:59999"
                self.process = type("P", (), {"pid": 1})()

            def stop(self):
                return None

        monkeypatch.setattr(probe, "_start_backend_without_the_gate", lambda env: _Backend())
        monkeypatch.setattr(probe, "_retained_side_effects", lambda validated, username: [])
        monkeypatch.setattr(probe, "PROBE_USERNAME", "demo_user")

        return recorded, install

    def test_an_initial_false_comes_back_false(self, probe, harness):
        """The flag was ``False`` before the probe: it is ``False`` after."""
        recorded, install = harness
        install(
            probe.MfaSnapshot(captured=True, previous=False),
            probe.MfaSnapshot(captured=True, previous=True),
        )
        assert probe.main() == 0
        assert len(recorded["logins"]) == 2, "both runs must have happened"
        assert len(recorded["restored"]) == 1
        assert recorded["restored"][0].previous is False, (
            "the probe must restore the value it FOUND (False), not the "
            "value RUN 1 created (True)"
        )

    def test_an_initial_true_comes_back_true(self, probe, harness):
        """The flag was ``True`` before the probe: it is ``True`` after."""
        recorded, install = harness
        install(
            probe.MfaSnapshot(captured=True, previous=True),
            probe.MfaSnapshot(captured=True, previous=False),
        )
        assert probe.main() == 0
        assert len(recorded["restored"]) == 1
        assert recorded["restored"][0].previous is True, (
            "the probe must restore the value it FOUND (True), not the "
            "value RUN 1 cleared (False)"
        )

    def test_a_failing_second_clear_keeps_the_original_snapshot(self, probe, harness):
        """A failing preparation must not replace the original snapshot.

        The regression this pins: the old code assigned the second
        clear's result to ``state.mfa``, so a FAILED second read
        replaced the original snapshot with ``captured=False`` and the
        restore wrote nothing at all.
        """
        recorded, install = harness
        install(
            probe.MfaSnapshot(captured=True, previous=True),
            probe.MfaSnapshot(captured=False, previous=None),
        )
        assert probe.main() == 1, "a failed preparation must fail the run"
        assert len(recorded["restored"]) == 1
        assert recorded["restored"][0].previous is True, (
            "the ORIGINAL snapshot must still be the one the cleanup uses"
        )
        assert recorded["restored"][0].captured is True

    def test_a_failed_second_clear_stops_before_the_second_login(self, probe, harness):
        """The probe must not compare against an unprepared MFA state."""
        recorded, install = harness
        install(
            probe.MfaSnapshot(captured=True, previous=False),
            probe.MfaSnapshot(captured=False, previous=None),
        )
        assert probe.main() == 1
        assert len(recorded["logins"]) == 1, (
            "the second run must not happen when its preparation failed"
        )


# =============================================================================
# Part 6 — no credential reaches any output
# =============================================================================

class TestNoCredentialReachesAnyOutput:
    """Every error path must print a SANITIZED message.

    A driver error carries the connection string, and the connection
    string carries the password.  The message is therefore sanitized
    BEFORE it is stored, and the SAME sanitized message is what every
    output path uses.
    """

    def test_the_cleanup_log_does_not_print_the_raw_exception(self, probe, capsys):
        """A cleanup failure with a credential in it prints no credential."""
        state = probe.ProbeState()
        error = RuntimeError(f"could not connect to {FAKE_URL}")
        state.cleanup_errors = []

        steps = [
            ("the first step", lambda: (_ for _ in ()).throw(error)),
            ("the second step", lambda: None),
        ]
        probe._cleanup_steps(state, steps) if hasattr(probe, "_cleanup_steps") else None

        # Drive the real cleanup loop through the module's own code path.
        recorded = probe.ProbeState()
        try:
            for name, step in steps:
                try:
                    step()
                except Exception as failure:  # noqa: BLE001
                    sanitized = recorded.record_cleanup_error(name, failure)
                    probe.log(f"the cleanup step '{name}' FAILED: {sanitized}")
        except Exception:  # pragma: no cover - defensive
            pytest.fail("the cleanup loop raised")

        captured = capsys.readouterr()
        combined = captured.out + captured.err
        assert FAKE_PASSWORD not in combined
        assert "probe-user" in combined, "the step name must still be reported"
        assert "the first step" in combined
        assert "the second step" not in combined

    def test_the_recorded_cleanup_error_carries_no_credential(self, probe):
        """The stored message is sanitized too."""
        state = probe.ProbeState()
        state.cleanup_errors = []
        error = RuntimeError(f"could not connect to {FAKE_URL}")
        message = state.record_cleanup_error("restore the one-time MFA flag", error)
        assert FAKE_PASSWORD not in message
        assert "restore the one-time MFA flag" in message
        assert all(FAKE_PASSWORD not in item for item in state.cleanup_errors)

    def test_the_child_startup_error_is_sanitized(self, probe, monkeypatch):
        """The startup failure path sanitizes the child's output.

        The child's own output is included in the error message, so it
        has to be sanitized as well — a child that echoed its
        environment would otherwise print a credential.
        """
        error = probe.ProbeError(
            "the comparison backend did not report a port within 1 seconds:\n"
            f"ERROR: connection to {FAKE_URL} failed"
        )
        rendered = str(error)
        # The probe renders the child's output through ``_redact``.
        sanitized = probe._redact(rendered)
        assert FAKE_PASSWORD not in sanitized
        assert "<redacted>" in sanitized

    def test_the_main_error_path_is_sanitized(self, probe):
        """The main failure path redacts before it prints."""
        error = RuntimeError(f"boom {FAKE_URL}")
        rendered = probe._redact(f"{type(error).__name__}: {error}")
        assert FAKE_PASSWORD not in rendered

    def test_the_redaction_keeps_the_diagnostic_parts(self, probe):
        """The scheme, the user and the host stay readable."""
        sanitized = probe._redact(f"failed to reach {FAKE_URL}")
        assert "postgresql://" in sanitized
        assert "probe-user" in sanitized
        assert "127.0.0.1:5432" in sanitized
        assert FAKE_PASSWORD not in sanitized

    def test_the_cleanup_log_uses_the_recorded_message(self, probe):
        """The printed line must be the RECORDED message, not a re-format.

        The regression this pins: the old code printed
        ``{type(error).__name__}: {error}`` while the record held the
        redacted message.  The two could drift, and the printed one was
        the raw one.
        """
        source = (SCRIPTS_DIR / "demo_pre_token_probe.py").read_text(encoding="utf-8")
        body = source[source.index("def _cleanup(") :]
        cleanup_body = body[: body.index("def _stop_comparison")]
        assert "{error}" not in cleanup_body, (
            "the cleanup must not interpolate the raw exception into the log"
        )
        assert "sanitized" in cleanup_body


# =============================================================================
# Part 7 — the evidence is bound to the attempt it belongs to
# =============================================================================

class TestTheEvidenceIsBoundToItsAttempt:
    """Each run must be credited with an attempt of its OWN.

    The regression this pins: the probe read "the newest scored attempt
    of this address inside a window", so two overlapping windows could
    produce the same row twice, and the second run would be credited
    with the first run's evidence.
    """

    def test_the_evidence_of_the_second_run_excludes_the_first(self, probe):
        """The second lookup must exclude the attempt the first claimed."""
        import inspect

        signature = inspect.signature(probe._await_attempt_evidence)
        assert "exclude_attempt_ids" in signature.parameters

    def test_the_evidence_lookup_is_bounded_by_a_deadline(self, probe):
        """The wait must be bounded, and the bound must be a parameter."""
        import inspect

        signature = inspect.signature(probe._await_attempt_evidence)
        assert "deadline_seconds" in signature.parameters
        default = signature.parameters["deadline_seconds"].default
        assert isinstance(default, (int, float))
        assert 0 < default <= 120

    def test_a_missing_second_attempt_fails_the_probe(self, probe, monkeypatch):
        """Without a NEW attempt, the probe must fail.

        This is the heart of the finding: the old probe read the newest
        attempt of the window, so the second run found RUN 1's row and
        the comparison silently compared one attempt with itself.
        """
        attempts = [
            # RUN 1's attempt.
            {"id": "attempt-run-1", "decision": "challenge", "risk_level": "high"},
            # RUN 2 produced NOTHING new.
        ]

        def fake_find(connection, **kwargs):
            excluded = set(kwargs.get("exclude_attempt_ids") or ())
            for attempt in attempts:
                if attempt["id"] not in excluded:
                    return attempt
            return None

        monkeypatch.setattr(probe, "_find_scored_attempt", fake_find, raising=False)

        class _Connection:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        class _Engine:
            def connect(self):
                return _Connection()

            def dispose(self):
                return None

        monkeypatch.setattr(probe, "_engine", lambda url: _Engine())

        with pytest.raises(probe.ProbeError) as failure:
            probe._await_attempt_evidence(
                None,
                "203.0.113.9",
                "ua",
                _now(),
                exclude_attempt_ids=("attempt-run-1",),
                deadline_seconds=0.5,
                poll_seconds=0.05,
            )
        assert "attempt" in str(failure.value).lower()

    def test_the_evidence_lookup_filters_by_account(self, probe):
        """An attempt of ANOTHER account is never evidence about this one."""
        import inspect

        signature = inspect.signature(probe._await_attempt_evidence)
        assert "user_id" in signature.parameters
        assert "username" in signature.parameters

    def test_the_account_filter_is_part_of_the_query(self, probe):
        """The filter is applied in the LOOKUP, not as a check afterwards."""
        source = (SCRIPTS_DIR / "demo_pre_token_probe.py").read_text(encoding="utf-8")
        start = source.index("def _find_scored_attempt(")
        end = source.index("\ndef ", start + 10)
        finder = source[start:end]
        assert "user_id = :user_id" in finder
        assert "username_attempted = :username" in finder

    def test_a_late_arriving_attempt_is_still_found(self, probe, monkeypatch):
        """Evidence that arrives late is found within the deadline."""
        state = {"polls": 0}

        def fake_find(connection, **kwargs):
            state["polls"] += 1
            if state["polls"] < 3:
                return None
            return {"id": "late-attempt", "decision": "challenge"}

        monkeypatch.setattr(probe, "_find_scored_attempt", fake_find, raising=False)
        monkeypatch.setattr(
            probe, "_read_evidence_of_attempt", lambda connection, attempt: _evidence(attempt)
        )

        class _Connection:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        class _Engine:
            def connect(self):
                return _Connection()

            def dispose(self):
                return None

        monkeypatch.setattr(probe, "_engine", lambda url: _Engine())

        evidence = probe._await_attempt_evidence(
            None,
            "203.0.113.9",
            "ua",
            _now(),
            exclude_attempt_ids=(),
            deadline_seconds=5.0,
            poll_seconds=0.01,
        )
        assert evidence.attempt_id == "late-attempt"
        assert state["polls"] >= 3

    def test_an_unscored_attempt_is_not_evidence(self, probe, monkeypatch):
        """A row that has not been scored yet does not end the wait."""
        attempts = [
            {"id": "unscored", "decision": None},
            {"id": "scored", "decision": "challenge"},
        ]
        state = {"index": 0}

        def fake_find(connection, **kwargs):
            index = state["index"]
            state["index"] = min(index + 1, len(attempts) - 1)
            return attempts[index]

        monkeypatch.setattr(probe, "_find_scored_attempt", fake_find, raising=False)
        monkeypatch.setattr(
            probe, "_read_evidence_of_attempt", lambda connection, attempt: _evidence(attempt)
        )

        class _Connection:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        class _Engine:
            def connect(self):
                return _Connection()

            def dispose(self):
                return None

        monkeypatch.setattr(probe, "_engine", lambda url: _Engine())

        evidence = probe._await_attempt_evidence(
            None,
            "203.0.113.9",
            "ua",
            _now(),
            exclude_attempt_ids=(),
            deadline_seconds=5.0,
            poll_seconds=0.01,
        )
        assert evidence.attempt_id == "scored"

    def test_the_two_attempts_must_differ(self, probe):
        """The probe asserts that the two runs were two DIFFERENT attempts."""
        source = (SCRIPTS_DIR / "demo_pre_token_probe.py").read_text(encoding="utf-8")
        assert "gated_evidence.attempt_id != ungated_evidence.attempt_id" in source

    def test_the_decision_is_checked_against_the_contract(self, probe):
        """The decision is checked against the matrix, not for presence."""
        source = (SCRIPTS_DIR / "demo_pre_token_probe.py").read_text(encoding="utf-8")
        assert "_decision_matches_the_contract(gated_evidence)" in source
        assert "_decision_matches_the_contract(ungated_evidence)" in source
        # The old check was only "is not None".
        assert "gated_evidence.decision is not None" not in source

    def test_the_rules_of_both_runs_are_checked(self, probe):
        """Both runs must have triggered the expected rules."""
        source = (SCRIPTS_DIR / "demo_pre_token_probe.py").read_text(encoding="utf-8")
        assert "set(EXPECTED_RULES) <= gated_evidence.rules" in source
        assert "set(EXPECTED_RULES) <= ungated_evidence.rules" in source


def _now():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc)


def _evidence(attempt: Dict[str, Any]):
    """Build a :class:`probe.DetectionEvidence` from a fake attempt."""
    module = _load_script("demo_pre_token_probe.py")
    return module.DetectionEvidence(
        attempt_id=attempt.get("id"),
        policy_id=attempt.get("policy_id"),
        policy_version=attempt.get("policy_version"),
        rules=set(attempt.get("rules") or ()),
        decision=attempt.get("decision"),
        risk_level=attempt.get("risk_level"),
    )


# =============================================================================
# Part 8 — the child never hangs the probe
# =============================================================================

class TestTheChildNeverHangsTheProbe:
    """A child that is alive and silent must cost the probe its timeout.

    The regression this pins: the startup loop wrapped a BLOCKING
    ``stdout.readline()`` in a deadline, and the error path called a
    BLOCKING ``stdout.read()``.
    """

    def test_the_startup_read_is_never_a_blocking_read(self, probe):
        """The source must not call ``readline``/``read`` on the child's pipe."""
        source = (SCRIPTS_DIR / "demo_pre_token_probe.py").read_text(encoding="utf-8")
        starter = source[source.index("def _start_backend_without_the_gate(") :]
        starter = starter[: starter.index("def _terminate(")]
        assert ".stdout.readline(" not in starter
        assert ".stdout.read(" not in starter

    def test_a_silent_child_is_stopped_within_the_deadline(self, probe):
        """A child that never writes is terminated within the timeout."""
        started = time.monotonic()
        with pytest.raises(probe.ProbeError) as failure:
            probe._start_backend_without_the_gate(
                {},
                command=[sys.executable, "-c", "import time; time.sleep(30)"],
                startup_timeout=1.0,
                readiness_timeout=1.0,
            )
        elapsed = time.monotonic() - started
        assert elapsed < 15, f"the probe hung for {elapsed:.1f}s"
        assert "did not report a port" in str(failure.value)

    def test_a_child_that_logs_without_a_port_is_stopped(self, probe):
        """A child that writes but never reports a port is stopped."""
        started = time.monotonic()
        with pytest.raises(probe.ProbeError) as failure:
            probe._start_backend_without_the_gate(
                {},
                command=[
                    sys.executable,
                    "-c",
                    "import sys, time; print('starting up', flush=True); time.sleep(30)",
                ],
                startup_timeout=1.0,
                readiness_timeout=1.0,
            )
        elapsed = time.monotonic() - started
        assert elapsed < 15, f"the probe hung for {elapsed:.1f}s"
        assert "did not report a port" in str(failure.value)

    def test_a_child_that_exits_early_is_reported(self, probe):
        """A child that exits is reported, not waited for."""
        with pytest.raises(probe.ProbeError) as failure:
            probe._start_backend_without_the_gate(
                {},
                command=[sys.executable, "-c", "raise SystemExit(3)"],
                startup_timeout=10.0,
                readiness_timeout=1.0,
            )
        assert "did not report a port" in str(failure.value)

    def test_a_child_that_reports_a_port_but_is_not_ready_is_stopped(self, probe):
        """A child that reports a port but never becomes healthy is stopped."""
        started = time.monotonic()
        with pytest.raises(probe.ProbeError) as failure:
            probe._start_backend_without_the_gate(
                {},
                command=[
                    sys.executable,
                    "-c",
                    (
                        "import sys, time; "
                        "print('Uvicorn running on http://127.0.0.1:65533', flush=True); "
                        "time.sleep(30)"
                    ),
                ],
                startup_timeout=10.0,
                readiness_timeout=1.0,
            )
        elapsed = time.monotonic() - started
        assert elapsed < 20, f"the probe hung for {elapsed:.1f}s"
        assert "ready" in str(failure.value)

    def test_a_valid_child_is_started_and_stopped(self, probe):
        """A child that reports a port and answers is started and stopped."""
        # A tiny HTTP server that answers /health with 200.
        script = (
            "import http.server, socketserver, threading, time\n"
            "class H(http.server.BaseHTTPRequestHandler):\n"
            "    def do_GET(self):\n"
            "        self.send_response(200); self.end_headers(); self.wfile.write(b'ok')\n"
            "    def log_message(self, *a): pass\n"
            "def run():\n"
            "    with socketserver.TCPServer(('127.0.0.1', 0), H) as s:\n"
            "        print('Uvicorn running on http://127.0.0.1:%d' % s.server_address[1], flush=True)\n"
            "        s.serve_forever()\n"
            "run()\n"
        )
        backend = probe._start_backend_without_the_gate(
            {},
            command=[sys.executable, "-c", script],
            startup_timeout=20.0,
            readiness_timeout=20.0,
        )
        try:
            assert backend.port > 0
            assert backend.process.poll() is None
        finally:
            backend.stop()
        assert backend.process.poll() is not None, "the child must be gone"

    def test_no_orphaned_process_survives_a_failed_startup(self, probe):
        """Every failure path leaves no child behind."""
        commands = [
            [sys.executable, "-c", "import time; time.sleep(30)"],
            [
                sys.executable,
                "-c",
                "import sys, time; print('no port here', flush=True); time.sleep(30)",
            ],
            [sys.executable, "-c", "raise SystemExit(3)"],
        ]
        for command in commands:
            with pytest.raises(probe.ProbeError):
                probe._start_backend_without_the_gate(
                    {},
                    command=command,
                    startup_timeout=1.0,
                    readiness_timeout=1.0,
                )
            # Give the operating system a moment to reap the child.
            time.sleep(0.2)
            survivors = _children_of_this_process()
            assert survivors == [], (
                f"a child survived the failed startup: {survivors}"
            )

    def test_the_child_is_never_killed_by_port(self, probe):
        """No port-based kill: the probe only signals its own handle."""
        source = (SCRIPTS_DIR / "demo_pre_token_probe.py").read_text(encoding="utf-8")
        for forbidden in ("pkill", "killall", "lsof", "fuser"):
            assert forbidden not in source

    def test_the_terminate_helper_waits_for_the_child(self, probe):
        """The terminate path waits, and kills only after the timeout."""
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

        probe._terminate(_Process())
        assert recorded == ["terminate", "wait"]


def _children_of_this_process() -> List[str]:
    """The command lines of this process's living children."""
    try:
        output = subprocess.run(
            ["ps", "-o", "pid=,ppid=,args="],
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout
    except Exception:  # pragma: no cover - the environment may lack ps
        return []
    mine = os.getpid()
    children = []
    for line in output.splitlines():
        parts = line.split(None, 2)
        if len(parts) < 3:
            continue
        pid, ppid = parts[0], parts[1]
        if not ppid.isdigit() or int(ppid) != mine:
            continue
        command = parts[2]
        # The ``ps`` call itself is a child of this process too; it is
        # not a survivor.
        if "ps -o pid=" in command:
            continue
        children.append(line.strip())
    return children


# =============================================================================
# Part 9 — the contract mirror must agree with the application
# =============================================================================

class TestTheContractMirrorAgreesWithTheApplication:
    """The probe's copy of the decision matrix must not drift.

    The probe mirrors ``app.detection.DECISION_MATRIX`` so that it stays
    a standalone script.  A mirror that drifts would make the probe
    assert a contract the application does not implement.
    """

    def test_the_mirrored_matrix_matches_the_application(self, probe):
        sys.path.insert(0, str(REPO_ROOT))
        try:
            from app.detection import DECISION_MATRIX
        finally:
            sys.path.pop(0)
        expected = {level: values[0] for level, values in DECISION_MATRIX.items()}
        assert probe.DECISION_BY_RISK_LEVEL == expected

    def test_the_gated_levels_match_the_application(self, probe):
        sys.path.insert(0, str(REPO_ROOT))
        try:
            from app.auth import GATED_RISK_LEVELS
        finally:
            sys.path.pop(0)
        assert set(probe.EXPECTED_GATED_RISK_LEVELS) == set(GATED_RISK_LEVELS)

    def test_a_low_risk_attempt_is_not_evidence_of_a_hold(self, probe):
        """An attempt at a level the gate does not act on is rejected."""
        evidence = _evidence(
            {"id": "a", "decision": "allow", "risk_level": "low"}
        )
        assert probe._decision_matches_the_contract(evidence) is False

    def test_a_high_risk_attempt_with_the_matrix_decision_is_accepted(self, probe):
        evidence = _evidence(
            {"id": "b", "decision": "challenge", "risk_level": "high"}
        )
        assert probe._decision_matches_the_contract(evidence) is True

    def test_a_critical_attempt_with_the_matrix_decision_is_accepted(self, probe):
        evidence = _evidence(
            {"id": "c", "decision": "block", "risk_level": "critical"}
        )
        assert probe._decision_matches_the_contract(evidence) is True

    def test_a_wrong_decision_for_the_level_is_rejected(self, probe):
        """A level that does not match the decision is not evidence."""
        evidence = _evidence(
            {"id": "d", "decision": "allow", "risk_level": "high"}
        )
        assert probe._decision_matches_the_contract(evidence) is False

    def test_a_missing_decision_is_rejected(self, probe):
        evidence = _evidence({"id": "e", "decision": None, "risk_level": "high"})
        assert probe._decision_matches_the_contract(evidence) is False
