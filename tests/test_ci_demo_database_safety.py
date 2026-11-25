"""Safety of ``scripts/ci_bootstrap_demo_databases.sh``.

``scripts/ci_bootstrap_demo_databases.sh`` DROPS and RECREATES databases.
That is the most destructive operation in the repository, so the script
carries five independent, fail-closed guards.  This module proves that
each one of them actually refuses.

The first part is a pure unit test: it SOURCES the script and calls the
guards directly, so no destructive SQL is ever executed.  Sourcing works
because the script only runs its main flow when it is EXECUTED.

The second part runs the script for real, against a disposable
PostgreSQL server, and proves two things: that the guards refuse before
any SQL runs, and that a properly authorised run succeeds.
"""
from __future__ import annotations

import importlib.util
import os
import shlex
import shutil
import subprocess
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
BOOTSTRAP = SCRIPTS_DIR / "ci_bootstrap_demo_databases.sh"

#: The three databases the script is allowed to touch.
CI_DATABASES = (
    "sentinel_core_ci_demo",
    "sentinel_detection_ci_demo",
    "sentinel_ml_ci_demo",
)

#: The persistent databases of the local demo stack.  The CI bootstrap
#: must never drop these.
LOCAL_DEMO_DATABASES = (
    "sentinel_core_demo",
    "sentinel_detection_demo",
    "sentinel_ml_demo",
)


#: The two variables the bootstrap script reads as ITS AUTHORISATION.
#: They are stripped from every subprocess environment by default, because
#: the CI job exports them at job level — and a test that inherits them
#: would exercise the AUTHORISED path while claiming to exercise the
#: REFUSAL path.  Each test therefore states the authorisation it wants
#: explicitly, and the harness removes the ambient one.
AUTHORISATION_VARIABLES = ("DEMO_CI_DISPOSABLE_SERVER", "DEMO_CI_ACK")


def _clean_environment(environment: dict | None = None) -> dict:
    """Return a copy of the environment without the authorisation variables.

    The CI workflow exports ``DEMO_CI_DISPOSABLE_SERVER`` and
    ``DEMO_CI_ACK`` for the whole job.  A subprocess would inherit them,
    so a test that is meant to prove the script REFUSES would instead
    observe it proceeding.  The authorisation is therefore always
    explicit: absent by default, set by the test that wants it.
    """
    env = {key: value for key, value in os.environ.items() if key not in AUTHORISATION_VARIABLES}
    env.update(environment or {})
    return env


def _source_script(environment: dict | None = None) -> dict:
    """Source the bootstrap script and return its shell state.

    The script defines its guards as functions and only runs ``main`` when
    it is executed, so sourcing it is side-effect free.
    """
    prelude = "set -uo pipefail\n"
    if environment:
        for key, value in environment.items():
            prelude += f"export {key}={shlex.quote(str(value))}\n"
    # ``BASH_SOURCE[0]`` differs from ``$0`` when the file is sourced, so
    # the main flow is not entered.
    prelude += f"source {BOOTSTRAP}\n"
    # The script sets ``errexit`` for its own main flow.  The guards are
    # meant to RETURN a status, so the errexit is turned off again for
    # the test harness.
    prelude += "set +e\n"

    result = subprocess.run(
        ["bash", "-c", prelude],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=_clean_environment(environment),
    )
    assert result.returncode == 0, result.stderr
    return result


def _run_guard(guard: str, argument: str, environment: dict | None = None) -> subprocess.CompletedProcess:
    """Call one guard of the sourced script and report its exit status."""
    prelude = "set -uo pipefail\n"
    if environment:
        for key, value in environment.items():
            prelude += f"export {key}={shlex.quote(str(value))}\n"
    prelude += f"source {BOOTSTRAP}\n"
    prelude += "set +e\n"
    prelude += f"{guard} {argument}\n"
    prelude += 'echo "GUARD_STATUS=$?"\n'

    return subprocess.run(
        ["bash", "-c", prelude],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=_clean_environment(environment),
    )


def _guard_status(result: subprocess.CompletedProcess) -> int:
    """Extract the guard's exit status from the script's output."""
    for line in result.stdout.splitlines():
        if line.startswith("GUARD_STATUS="):
            return int(line.split("=", 1)[1])
    raise AssertionError(f"the guard did not report a status:\n{result.stdout}\n{result.stderr}")


# =============================================================================
# Layer 1 — the allowlist
# =============================================================================

class TestTheAllowlist:
    """Layer 1: only the three CI-disposable databases may be touched."""

    @pytest.mark.parametrize("name", CI_DATABASES)
    def test_the_ci_databases_are_allowed(self, name):
        result = _run_guard("guard_allowlisted", name)
        assert _guard_status(result) == 0, result.stderr

    @pytest.mark.parametrize(
        "name",
        [
            "sentinel_core_demo",
            "sentinel_detection_demo",
            "sentinel_ml_demo",
            "postgres",
            "sentinel_core_test",
            "sentinel",
            "production",
        ],
    )
    def test_everything_else_is_refused(self, name):
        result = _run_guard("guard_allowlisted", name)
        assert _guard_status(result) != 0
        assert "allowlist" in result.stderr

    def test_the_allowlist_cannot_be_widened_by_the_environment(self):
        # Even if the environment tries to name another database, the
        # allowlist is a hard-coded list in the script.
        result = _run_guard(
            "guard_allowlisted",
            "sentinel_core_demo",
            {"DEMO_CORE_DB": "sentinel_core_demo", "CI_DATABASES": "sentinel_core_demo"},
        )
        assert _guard_status(result) != 0
        assert "allowlist" in result.stderr

    def test_the_allowlist_holds_exactly_three_names(self):
        result = _source_script()
        # The names are printed by the guard's own refusal message, so the
        # allowlist is read back from the script's source instead.
        source = BOOTSTRAP.read_text(encoding="utf-8")
        for name in CI_DATABASES:
            assert f'"{name}"' in source
        # And nothing else is in the allowlist block.
        block = source.split("ALLOWED_DATABASES=(", 1)[1].split(")", 1)[0]
        quoted = [line.strip().strip('"') for line in block.strip().splitlines() if line.strip()]
        assert tuple(quoted) == CI_DATABASES
        assert result.returncode == 0


# =============================================================================
# Layer 2 — the marker
# =============================================================================

class TestTheMarker:
    """Layer 2: every target must carry the `_ci_demo` marker."""

    @pytest.mark.parametrize("name", CI_DATABASES)
    def test_the_ci_databases_carry_the_marker(self, name):
        result = _run_guard("guard_marked", name)
        assert _guard_status(result) == 0, result.stderr

    @pytest.mark.parametrize(
        "name",
        [
            "sentinel_core_demo",
            "sentinel_core_test",
            "sentinel_core_ci",
            "ci_demo_sentinel_core",
            "sentinel_core",
        ],
    )
    def test_a_name_without_the_marker_is_refused(self, name):
        result = _run_guard("guard_marked", name)
        assert _guard_status(result) != 0
        assert "_ci_demo" in result.stderr

    def test_the_marker_is_a_refinement_of_the_seed_marker(self):
        # The seed script refuses to write to a database whose name lacks
        # `_demo`.  The CI marker must be a strict refinement, so a CI
        # database is also acceptable to the seed.
        source = BOOTSTRAP.read_text(encoding="utf-8")
        assert 'CI_MARKER="_ci_demo"' in source
        assert 'SEED_MARKER="_demo"' in source
        for name in CI_DATABASES:
            assert name.endswith("_ci_demo")
            assert name.endswith("_demo")

    def test_the_seed_guard_accepts_the_ci_database_names(self):
        # The seed script's own guard is the real contract.  A CI database
        # must pass it, otherwise the fixtures could never be seeded.
        spec = importlib.util.spec_from_file_location(
            "demo_seed_demo", SCRIPTS_DIR / "demo_seed_demo.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        for name in CI_DATABASES:
            url = f"postgresql://sentinel:secret@127.0.0.1:5432/{name}"
            assert module.assert_demo_database(url) == name


# =============================================================================
# Layer 3 — no overlap with the local demo stack
# =============================================================================

class TestTheOverlapGuard:
    """Layer 3: the persistent local demo databases are never targets."""

    @pytest.mark.parametrize("name", LOCAL_DEMO_DATABASES)
    def test_the_local_demo_databases_are_refused(self, name):
        result = _run_guard("guard_no_local_overlap", name)
        assert _guard_status(result) != 0
        assert "persistent" in result.stderr

    @pytest.mark.parametrize("name", CI_DATABASES)
    def test_the_ci_databases_are_accepted(self, name):
        result = _run_guard("guard_no_local_overlap", name)
        assert _guard_status(result) == 0, result.stderr


# =============================================================================
# Layer 4 — the state of the server
# =============================================================================

class TestTheServerGuard:
    """Layer 4: a server carrying the demo stack's data is refused."""

    def test_a_server_without_the_local_demo_databases_is_accepted(self):
        listing = "postgres\nsentinel\n"
        result = _run_guard(
            "guard_disposable_server",
            '"$listing"',
            {"DEMO_CI_DISPOSABLE_SERVER": "true", "listing": listing},
        )
        assert _guard_status(result) == 0, result.stderr

    @pytest.mark.parametrize("name", LOCAL_DEMO_DATABASES)
    def test_a_server_carrying_a_local_demo_database_is_refused(self, name):
        listing = f"postgres\n{name}\n"
        result = _run_guard(
            "guard_disposable_server",
            '"$listing"',
            {"DEMO_CI_DISPOSABLE_SERVER": "true", "listing": listing},
        )
        assert _guard_status(result) != 0
        assert name in result.stderr

    def test_the_declaration_alone_does_not_bypass_the_server_check(self):
        # This is the core of the requirement: NO SINGLE ENVIRONMENT
        # VARIABLE may disable the protection.  Declaring the server
        # disposable must not get past the check of the real state.
        listing = "postgres\nsentinel_core_demo\n"
        result = _run_guard(
            "guard_disposable_server",
            '"$listing"',
            {"DEMO_CI_DISPOSABLE_SERVER": "true", "listing": listing},
        )
        assert _guard_status(result) != 0
        assert "sentinel_core_demo" in result.stderr

    def test_an_undeclared_server_is_refused(self):
        # A server that is free of the demo databases still has to be
        # declared disposable.
        listing = "postgres\nsentinel\n"
        result = _run_guard(
            "guard_disposable_server",
            '"$listing"',
            {"DEMO_CI_DISPOSABLE_SERVER": "", "listing": listing},
        )
        assert _guard_status(result) != 0
        assert "disposable" in result.stderr


# =============================================================================
# Layer 5 — the acknowledgement
# =============================================================================

class TestTheAcknowledgement:
    """Layer 5: the acknowledgement must name exactly the targets."""

    def test_the_correct_acknowledgement_is_accepted(self):
        result = _run_guard(
            "guard_acknowledged",
            "",
            {"DEMO_CI_ACK": " ".join(CI_DATABASES)},
        )
        assert _guard_status(result) == 0, result.stderr

    def test_the_acknowledgement_is_order_independent(self):
        result = _run_guard(
            "guard_acknowledged",
            "",
            {"DEMO_CI_ACK": " ".join(reversed(CI_DATABASES))},
        )
        assert _guard_status(result) == 0, result.stderr

    @pytest.mark.parametrize(
        "ack",
        [
            "yes",
            "true",
            "y",
            "1",
            "sentinel_core_ci_demo",
            "sentinel_core_ci_demo sentinel_detection_ci_demo",
            "sentinel_core_ci_demo sentinel_detection_ci_demo sentinel_ml_ci_demo extra",
        ],
    )
    def test_a_wrong_acknowledgement_is_refused(self, ack):
        result = _run_guard("guard_acknowledged", "", {"DEMO_CI_ACK": ack})
        assert _guard_status(result) != 0
        assert "acknowledgement" in result.stderr

    def test_an_acknowledgement_naming_the_local_demo_databases_is_refused(self):
        ack = "sentinel_core_demo sentinel_detection_demo sentinel_ml_demo"
        result = _run_guard("guard_acknowledged", "", {"DEMO_CI_ACK": ack})
        assert _guard_status(result) != 0


# =============================================================================
# The full script, against a real disposable server
# =============================================================================

def _postgres_binaries() -> tuple[str, str, str] | None:
    """Return the paths of the PostgreSQL binaries, or None.

    The binaries are the preferred way to start a throwaway server, because
    they need no container runtime.  When they are missing, the tests fall
    back to a container — see `_start_container_postgres`.
    """
    missing = [name for name in ("initdb", "pg_ctl", "psql") if shutil.which(name) is None]
    if missing:
        return None
    return shutil.which("initdb"), shutil.which("pg_ctl"), shutil.which("psql")


def _container_runtime() -> str | None:
    """Return the available container runtime, or None."""
    for runtime in ("docker", "podman"):
        if shutil.which(runtime) is None:
            continue
        probe = subprocess.run(
            [runtime, "info"], capture_output=True, text=True
        )
        if probe.returncode == 0:
            return runtime
    return None


@pytest.fixture(scope="module")
def disposable_postgres(tmp_path_factory):
    """Start a throwaway PostgreSQL server and return its coordinates.

    The server is started either from the local PostgreSQL binaries or from
    a container, whichever is available.  The test is skipped ONLY when
    neither is — the CI runner has a container runtime, so the suite
    never turns into a silent coverage hole there.
    """
    binaries = _postgres_binaries()
    runtime = _container_runtime()

    if binaries is None and runtime is None:
        pytest.skip(
            "no throwaway PostgreSQL is available: neither the PostgreSQL "
            "binaries (initdb, pg_ctl) nor a container runtime (docker, podman) "
            "were found"
        )

    root = tmp_path_factory.mktemp("pg")
    port = _free_port()

    if binaries is not None:
        initdb, pg_ctl, _ = binaries
        data_dir = root / "data"
        subprocess.run(
            [initdb, "-D", str(data_dir), "-U", "sentinel", "--auth=trust"],
            capture_output=True,
            text=True,
            check=True,
        )
        result = subprocess.run(
            [pg_ctl, "-D", str(data_dir), "-o", f"-p {port} -k {root}", "-l", str(root / "pg.log"), "start"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            pytest.skip(f"the throwaway PostgreSQL server did not start: {result.stderr}")
        try:
            yield {"port": str(port), "root": str(root)}
        finally:
            subprocess.run([pg_ctl, "-D", str(data_dir), "stop"], capture_output=True, text=True)
        return

    # The container fallback.  The container is removed when the fixture
    # ends, so it never leaves anything behind.
    container = f"sentinel-m13-safety-{os.getpid()}"
    subprocess.run(
        [
            runtime,
            "run",
            "-d",
            "--rm",
            "--name",
            container,
            "-e",
            "POSTGRES_HOST_AUTH_METHOD=trust",
            "-e",
            "POSTGRES_USER=sentinel",
            "-p",
            f"{port}:5432",
            "postgres:16-alpine",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    try:
        deadline = time.time() + 60
        while time.time() < deadline:
            probe = subprocess.run(
                [
                    "psql",
                    "-h",
                    "127.0.0.1",
                    "-p",
                    str(port),
                    "-U",
                    "sentinel",
                    "-d",
                    "postgres",
                    "-Atc",
                    "SELECT 1;",
                ],
                capture_output=True,
                text=True,
            )
            if probe.returncode == 0:
                break
            time.sleep(1)
        else:
            pytest.skip("the throwaway PostgreSQL container did not become ready")
        yield {"port": str(port), "root": str(root)}
    finally:
        subprocess.run([runtime, "rm", "-f", container], capture_output=True, text=True)


@pytest.fixture
def clean_server(disposable_postgres):
    """Leave the throwaway server free of any leftover database.

    The server itself is module-scoped, so a database created by one test
    would otherwise be visible to the next one.  Each test therefore starts
    from a server that holds nothing but the default databases, which
    makes the tests independent of their order.

    The fixture is NOT autouse: it must not drag the pure unit tests into
    the server's lifecycle.  A unit test that needs no server must never
    be skipped because a server could not be started — that would turn a
    coverage hole into a silent one.
    """
    port = disposable_postgres["port"]
    leftovers = _psql(
        port,
        "SELECT datname FROM pg_database "
        "WHERE datistemplate = false AND datname <> 'postgres';",
    )
    for name in [line.strip() for line in leftovers.splitlines() if line.strip()]:
        _psql(port, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')
    yield


def _free_port() -> int:
    """Find a free TCP port."""
    import socket

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _psql(port: str, sql: str, database: str = "postgres") -> str:
    """Run one statement against the throwaway server."""
    result = subprocess.run(
        [
            "psql",
            "-h",
            "127.0.0.1",
            "-p",
            port,
            "-U",
            "sentinel",
            "-d",
            database,
            "-Atc",
            sql,
        ],
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _run_script(port: str, environment: dict | None = None, stdin: str = "") -> subprocess.CompletedProcess:
    """Run the bootstrap script against the throwaway server."""
    env = {
        **_clean_environment(),
        "POSTGRES_HOST": "127.0.0.1",
        "POSTGRES_PORT": port,
        "POSTGRES_USER": "sentinel",
        "POSTGRES_PASSWORD": "",
        "PGPASSWORD": "",
        **(environment or {}),
    }
    return subprocess.run(
        ["bash", str(BOOTSTRAP)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=env,
        input=stdin,
        timeout=300,
    )


@pytest.mark.usefixtures("clean_server")
class TestTheScriptAgainstARealServer:
    """The script as a whole, against a real PostgreSQL server."""

    def test_an_unauthorised_run_changes_nothing(self, disposable_postgres):
        port = disposable_postgres["port"]

        # The server is NOT declared disposable, and there is no
        # acknowledgement.  The script must refuse.
        result = _run_script(port)
        assert result.returncode != 0
        assert "disposable" in result.stderr

        # Nothing was created.
        listing = _psql(port, "SELECT count(*) FROM pg_database WHERE datname LIKE '%_ci_demo';")
        assert listing == "0"

    def test_an_unauthorised_run_never_executes_destructive_sql(self, disposable_postgres):
        port = disposable_postgres["port"]
        _psql(port, "CREATE DATABASE sentinel_core_ci_demo;")

        # A wrong acknowledgement must be refused, and the existing
        # database must survive untouched.
        result = _run_script(
            port,
            {"DEMO_CI_DISPOSABLE_SERVER": "true", "DEMO_CI_ACK": "yes"},
        )
        assert result.returncode != 0

        listing = _psql(
            port,
            "SELECT count(*) FROM pg_database WHERE datname = 'sentinel_core_ci_demo';",
        )
        assert listing == "1", "the refused run dropped a database anyway"

    def test_the_server_state_is_verified_not_trusted(self, disposable_postgres):
        port = disposable_postgres["port"]

        # The server carries a persistent local demo database.  The
        # environment claims the server is disposable — the script must
        # still refuse.
        _psql(port, "CREATE DATABASE sentinel_core_demo;")

        result = _run_script(
            port,
            {
                "DEMO_CI_DISPOSABLE_SERVER": "true",
                "DEMO_CI_ACK": " ".join(CI_DATABASES),
            },
        )
        assert result.returncode != 0
        assert "sentinel_core_demo" in result.stderr

        # The persistent database is untouched.
        listing = _psql(
            port,
            "SELECT count(*) FROM pg_database WHERE datname = 'sentinel_core_demo';",
        )
        assert listing == "1"

    def test_an_authorised_run_provisions_the_databases(self, disposable_postgres):
        port = disposable_postgres["port"]

        result = _run_script(
            port,
            {
                "DEMO_CI_DISPOSABLE_SERVER": "true",
                "DEMO_CI_ACK": " ".join(CI_DATABASES),
            },
        )
        assert result.returncode == 0, result.stdout + result.stderr

        for name in CI_DATABASES:
            listing = _psql(
                port, f"SELECT count(*) FROM pg_database WHERE datname = '{name}';"
            )
            assert listing == "1", f"{name} was not provisioned"

        # The canonical schema was applied.
        core_tables = _psql(
            port,
            "SELECT count(*) FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_type = 'BASE TABLE';",
            database="sentinel_core_ci_demo",
        )
        assert core_tables == "13"

    def test_an_authorised_run_is_idempotent(self, disposable_postgres):
        port = disposable_postgres["port"]
        environment = {
            "DEMO_CI_DISPOSABLE_SERVER": "true",
            "DEMO_CI_ACK": " ".join(CI_DATABASES),
        }

        assert _run_script(port, environment).returncode == 0
        assert _run_script(port, environment).returncode == 0

        for name in CI_DATABASES:
            listing = _psql(
                port, f"SELECT count(*) FROM pg_database WHERE datname = '{name}';"
            )
            assert listing == "1", f"{name} was duplicated"

    def test_a_manual_run_asks_for_the_confirmation(self, disposable_postgres):
        port = disposable_postgres["port"]

        # The server is declared disposable, but there is no
        # acknowledgement in the environment, so the script asks.
        result = _run_script(
            port,
            {"DEMO_CI_DISPOSABLE_SERVER": "true"},
            stdin=" ".join(CI_DATABASES) + "\n",
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert "DROPS and RECREATES" in result.stdout

        listing = _psql(
            port,
            "SELECT count(*) FROM pg_database WHERE datname = 'sentinel_core_ci_demo';",
        )
        assert listing == "1"

    def test_a_wrong_manual_confirmation_changes_nothing(self, disposable_postgres):
        port = disposable_postgres["port"]

        result = _run_script(
            port,
            {"DEMO_CI_DISPOSABLE_SERVER": "true"},
            stdin="yes\n",
        )
        assert result.returncode != 0
        assert "confirmation did not match" in result.stderr

        listing = _psql(
            port,
            "SELECT count(*) FROM pg_database WHERE datname LIKE '%_ci_demo';",
        )
        assert listing == "0"
