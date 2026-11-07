#!/usr/bin/env python
"""Sentinel Auth v3.3 — CI test-suite verifier.

Runs the full pytest suite against the disposable PostgreSQL databases and
enforces the CI acceptance policy:

* **zero failures** - a failing test fails the step;
* **zero skips** - a skipped test is a *silent* hole in the coverage, so it
  fails the step as well.  Every PostgreSQL-backed module skips itself when
  its environment variables are missing; in CI the environment is fully
  provisioned, so a skip means the provisioning did not reach that module;
* **the expected test count** - the suite must collect at least
  ``EXPECTED_MIN_TESTS`` tests, so a module that failed to import (and was
  therefore never collected) cannot pass unnoticed;
* **no missing dependency** - the import check below runs first and fails
  with the missing distribution named.

Usage::

    python scripts/ci_verify_tests.py [--pytest-args ...]

The script never prints a secret: it reports *names* of distributions and
environment variables, never their values.
"""
from __future__ import annotations

import argparse
import fcntl
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, List, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent

#: The distributions the repository declares.  They are the same ones the
#: workflow installs from ``requirements.txt``; the check exists to turn a
#: silently missing package into a named error instead of a wall of
#: collection errors.
#:
#: The names are *distribution* names (the PyPI project name), not the
#: import names: the psycopg2 driver is published as ``psycopg2-binary`` but
#: imported as ``psycopg2``.
#:
#: Each entry is a group of mutually interchangeable distributions: at least
#: one member of the group must be installed.  The psycopg2 driver, for
#: instance, is published both as the source-only ``psycopg2`` project and
#: as the prebuilt ``psycopg2-binary`` wheel - both provide the same
#: ``psycopg2`` module, so either one satisfies the requirement.
REQUIRED_DISTRIBUTION_GROUPS: Tuple[Tuple[str, ...], ...] = (
    ("fastapi",),
    ("uvicorn",),
    ("httpx",),
    ("pydantic",),
    ("sqlalchemy",),
    ("psycopg",),
    ("psycopg2-binary", "psycopg2"),
    ("argon2-cffi",),
    ("pytest",),
    ("pytest-asyncio",),
    ("joblib",),
    ("numpy",),
    ("scikit-learn",),
)

#: The environment variables the PostgreSQL-backed modules need.  When one
#: is missing, the corresponding module **skips itself** - which the
#: zero-skip policy would then report as a failure without explaining the
#: cause.  This check runs first so the report names the missing variable.
REQUIRED_ENV_VARS: Tuple[str, ...] = (
    "POSTGRES_HOST",
    "POSTGRES_PORT",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "POSTGRES_DB",
    "CORE_DETECTION_TEST_URL",
    "CORE_ANALYTICS_TEST_URL",
    "DETECTION_TEST_URL",
    "ML_TEST_URL",
)

#: The minimum number of tests the suite must collect.  The M10 baseline is
#: 1,035 tests; a lower number means a module was not collected at all.
EXPECTED_MIN_TESTS = 1035

#: The lock file that serialises the suite against a concurrent run.
#:
#: Several legacy modules rebuild their schema with ``DROP SCHEMA public
#: CASCADE`` followed by a re-apply of the schema files.  Two pytest
#: processes pointed at the *same* PostgreSQL server therefore destroy each
#: other's schema mid-run, which shows up as a burst of unrelated
#: ``UndefinedTable`` / ``InFailedSqlTransaction`` errors.  A file lock
#: makes the second process wait instead of corrupting the first.
LOCK_PATH = REPO_ROOT / ".ci" / "pytest-suite.lock"


def _fail(message: str) -> None:
    print(f"[ci-verify] ERROR: {message}", file=sys.stderr)
    sys.exit(1)


@contextmanager
def _suite_lock() -> Iterator[None]:
    """Serialise the suite against a concurrent run on the same server.

    The legacy PostgreSQL modules rebuild their schema with ``DROP SCHEMA
    public CASCADE``.  Two suites sharing one server would drop each
    other's tables mid-run and report a burst of unrelated errors that has
    nothing to do with the code under test.  The lock makes the second
    process wait for the first instead.
    """
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(LOCK_PATH, "w") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            print(
                "[ci-verify] another suite run holds the lock - waiting for it "
                "to finish (the suite must not share a PostgreSQL server with "
                "another run)"
            )
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _distribution_installed(name: str) -> bool:
    """Return ``True`` when the named distribution is installed."""
    from importlib import metadata

    try:
        metadata.version(name)
    except metadata.PackageNotFoundError:
        return False
    return True


def check_dependencies() -> None:
    """Verify every declared distribution is importable."""
    missing: List[str] = []
    for group in REQUIRED_DISTRIBUTION_GROUPS:
        if not any(_distribution_installed(name) for name in group):
            missing.append(" | ".join(group))

    if missing:
        _fail(
            "missing required distribution(s): "
            + ", ".join(missing)
            + ". Install them with: pip install -r requirements.txt"
        )

    print(
        f"[ci-verify] {len(REQUIRED_DISTRIBUTION_GROUPS)} required distributions present"
    )

    # The SQLAlchemy drivers are imported through the dialect, so a missing
    # psycopg2 only fails at engine creation.  Import both explicitly.
    for module, distribution in (("psycopg", "psycopg"), ("psycopg2", "psycopg2")):
        try:
            __import__(module)
        except ImportError:
            _fail(
                f"the {module} module is not importable (distribution "
                f"{distribution!r}). The PostgreSQL-backed tests use the "
                f"postgresql+psycopg2 dialect, so it must be installed."
            )
    print("[ci-verify] psycopg and psycopg2 are importable")


def check_environment() -> None:
    """Verify every variable the PostgreSQL-backed modules read is set."""
    missing = [name for name in REQUIRED_ENV_VARS if not os.environ.get(name)]
    if missing:
        _fail(
            "missing required environment variable(s): "
            + ", ".join(missing)
            + ". The PostgreSQL-backed modules skip themselves without them, "
              "so the zero-skip policy would fail with an unhelpful message."
        )
    print(f"[ci-verify] {len(REQUIRED_ENV_VARS)} required environment variables present")


def _report_path() -> Path:
    return REPO_ROOT / ".ci" / "pytest-report.xml"


def run_pytest(extra_args: List[str]) -> Tuple[int, Dict[str, Any]]:
    """Run pytest and capture its exit code plus its JUnit XML report.

    The JUnit XML is written by pytest itself, so the policy check needs no
    extra plugin and no extra dependency.

    ``extra_args`` may name a target (a test path or a ``-k`` expression).
    When it does, the default ``tests`` target is not added, so the caller
    can run a subset.
    """
    report = _report_path()
    report.parent.mkdir(parents=True, exist_ok=True)
    if report.exists():
        report.unlink()

    cmd = [sys.executable, "-m", "pytest"]
    if not any(not arg.startswith("-") for arg in extra_args):
        cmd.append("tests")
    cmd.extend([
        "-q",
        "--strict-markers",
        "-ra",
        f"--junitxml={report}",
    ])
    cmd.extend(extra_args)

    print(f"[ci-verify] running: {' '.join(cmd)}")
    with _suite_lock():
        completed = subprocess.run(cmd, cwd=REPO_ROOT)

    if not report.exists():
        _fail(
            "pytest produced no JUnit XML report, so the skip and failure "
            "accounting could not be verified."
        )

    try:
        tree = ET.parse(report)
    except (OSError, ET.ParseError) as exc:
        _fail(f"the pytest JUnit XML report could not be read: {exc}")

    return completed.returncode, _summarise(tree)


def _summarise(tree: "ET.Element") -> Dict[str, Any]:
    """Turn the JUnit XML into the counters the policy needs.

    A JUnit ``testsuite`` reports ``tests``, ``failures``, ``errors`` and
    ``skipped``.  A test that is expected to fail shows up as a
    ``<skipped type="pytest.xfail">`` element, so the xfail count is
    separated from a genuine skip by inspecting that attribute.
    """
    root = tree.getroot()
    suites = root.findall("testsuite") or (
        [root] if root.tag == "testsuite" else []
    )

    totals: Dict[str, Any] = {
        "collected": 0, "passed": 0, "failed": 0,
        "skipped": 0, "error": 0, "xfailed": 0,
    }
    skips: List[Dict[str, str]] = []

    for suite in suites:
        for case in suite.findall("testcase"):
            totals["collected"] += 1

            failure = case.find("failure")
            error = case.find("error")
            skipped = case.find("skipped")

            if failure is not None:
                totals["failed"] += 1
            elif error is not None:
                totals["error"] += 1
            elif skipped is not None:
                if (skipped.get("type") or "") == "pytest.xfail":
                    totals["xfailed"] += 1
                else:
                    totals["skipped"] += 1
                    skips.append({
                        "nodeid": case.get("name") or "<unnamed>",
                        "reason": (skipped.get("message") or "").strip(),
                    })
            else:
                totals["passed"] += 1

    totals["skips"] = skips
    return totals


def analyse(report: Dict[str, Any], expect_full_suite: bool) -> List[str]:
    """Return the list of policy violations.  An empty list means success."""
    problems: List[str] = []

    collected = int(report.get("collected", 0))
    passed = int(report.get("passed", 0))
    failed = int(report.get("failed", 0))
    skipped = int(report.get("skipped", 0))
    errored = int(report.get("error", 0))
    xfailed = int(report.get("xfailed", 0))

    print(
        f"[ci-verify] collected={collected} passed={passed} failed={failed} "
        f"skipped={skipped} error={errored} xfailed={xfailed}"
    )

    if expect_full_suite and collected < EXPECTED_MIN_TESTS:
        problems.append(
            f"the suite collected {collected} tests but at least "
            f"{EXPECTED_MIN_TESTS} are required. A module that failed to "
            f"import is not collected, so this is how a broken import "
            f"would otherwise hide."
        )

    if failed:
        problems.append(f"{failed} test(s) failed")
    if errored:
        problems.append(f"{errored} test(s) errored")
    if skipped:
        reasons = [
            f"{item['nodeid']}: {item['reason'][:200]}"
            for item in report.get("skips", [])
        ]
        problems.append(
            f"{skipped} test(s) were skipped. Every skip is an uncovered "
            f"branch; the CI provisions all three databases, so a skip means "
            f"the provisioning did not reach that module:\n  "
            + "\n  ".join(reasons[:20])
        )
    if xfailed:
        problems.append(
            f"{xfailed} test(s) are marked xfail. The CI policy does not "
            f"accept expected failures."
        )

    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "pytest_args", nargs="*",
        help="extra arguments forwarded to pytest",
    )
    args = parser.parse_args()

    check_dependencies()
    check_environment()

    exit_code, report = run_pytest(args.pytest_args)

    # The minimum-count guard only makes sense for the FULL suite.  A
    # targeted run (a single module, a ``-k`` expression) is expected to
    # collect fewer tests, so the guard would report a false violation.
    expect_full_suite = not any(
        not arg.startswith("-") for arg in args.pytest_args
    )

    problems = analyse(report, expect_full_suite)
    if problems:
        print("\n[ci-verify] the CI acceptance policy was violated:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1

    if exit_code != 0:
        print(
            f"[ci-verify] pytest exited with {exit_code} although the report "
            f"showed no failure - treating the run as failed",
            file=sys.stderr,
        )
        return exit_code

    print("[ci-verify] the suite passed with zero failures and zero skips")
    return 0


if __name__ == "__main__":
    sys.exit(main())
