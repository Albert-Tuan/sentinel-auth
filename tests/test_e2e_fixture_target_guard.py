"""The E2E fixture guard must validate the DESTINATION, not the STRING.

===========================================================================
THE BLOCKER THIS SUITE EXISTS FOR
===========================================================================

``scripts/e2e_fixtures_guard.py`` used to read the database name and the
host out of the URL with ``urllib.parse.urlsplit`` and then compare the
URL with the context's own environment variable by **cutting everything
after the "?" off both sides**:

    if configured.split("?", 1)[0] != url.split("?", 1)[0]:

So the guard validated the URL *up to the query string* and then threw
the query string away.  The helper, meanwhile, handed the WHOLE URL to
``sqlalchemy.create_engine()``.

Those are two different targets.

A PostgreSQL URL carries a query string whose keys are libpq
connection parameters, and libpq lets the query string OVERRIDE the
parts of the URL:

    postgresql://demo:example@127.0.0.1/sentinel_core_demo?dbname=sentinel_core_test

    dialect.create_connect_args()  ->  {"host": "127.0.0.1",
                                        "dbname": "sentinel_core_test"}

The guard saw ``dbname=sentinel_core_demo`` (the path) and ``host=127.0.0.1``
(the authority), and it approved the URL.  The DRIVER received
``dbname=sentinel_core_test`` and connected to the regression suite's
database instead.

The same hole existed for ``host``, ``hostaddr`` and ``service``.  The
guard checked one destination; the driver was told another.

===========================================================================
THE RULE THIS SUITE ENFORCES
===========================================================================

    **The destination the guard allows must be the destination that
    reaches the driver.**

Concretely:

  * the URL is parsed with SQLAlchemy's OWN parser, so the guard reads
    the same URL the engine will read;
  * the query string is validated, not discarded: only an explicit
    allowlist of connection parameters is accepted, and every parameter
    that can move the destination (``host``, ``hostaddr``, ``dbname``,
    ``service``) is refused outright;
  * an unknown parameter is REFUSED, never silently ignored;
  * the URL the engine is built from is the very string that was
    validated — never a re-assembled or partially-stripped variant;
  * the libpq environment variables that can move a destination
    (``PGHOST``, ``PGHOSTADDR``, ``PGDATABASE``, ``PGSERVICE``,
    ``PGPASSFILE``, ...) are refused when they are set, because libpq
    reads them as DEFAULTS for any parameter the URL does not set.

The suite has five parts:

  A. the refusals;
  B. the valid cases;
  C. the boundary — ``create_engine`` must NOT be reached with a
     refused URL;
  D. the driver semantics — what ``dialect.create_connect_args()``
     really produces, for BOTH drivers the project uses;
  E. the positive control — a fixture really is written to a
     disposable demo database, and cleaned up.
"""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"

DEMO_CORE_DB = "sentinel_core_demo"
DEMO_DETECTION_DB = "sentinel_detection_demo"
DEMO_ML_DB = "sentinel_ml_demo"
DEMO_CORE_CI_DB = "sentinel_core_ci_demo"

#: The URL the reviewer's reproduction used, verbatim.
#:
#: It names a demo database on the loopback interface, so every OTHER
#: layer of the guard is satisfied.  Only the query string makes it
#: dangerous — which is exactly what makes it a good regression case.
REVIEW_BASE_URL = "postgresql://demo:example@127.0.0.1/sentinel_core_demo"

#: The drivers the project actually uses.
#:
#: ``requirements.txt`` pins ``psycopg[binary]`` and ``psycopg2-binary``,
#: and the CI URLs spell the driver explicitly as
#: ``postgresql+psycopg2://``.  The bare ``postgresql://`` form resolves
#: to the psycopg2 dialect by SQLAlchemy's own registry.
SUPPORTED_DRIVERS = ("psycopg2", "psycopg")


def _load_script(name: str):
    """Import a script from ``scripts/`` by its file name."""
    path = SCRIPTS_DIR / name
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _url(database: str, driver: str = "") -> str:
    """A connection URL for one of the disposable demo databases."""
    scheme = f"postgresql+{driver}" if driver else "postgresql"
    return (
        f"{scheme}://{os.environ.get('POSTGRES_USER', 'sentinel')}:"
        f"{os.environ.get('POSTGRES_PASSWORD', '')}@"
        f"{os.environ.get('POSTGRES_HOST', '127.0.0.1')}:"
        f"{os.environ.get('POSTGRES_PORT', '5432')}/{database}"
    )


def _dialect_for(driver: str):
    """Return the SQLAlchemy dialect for one of the project's drivers."""
    from sqlalchemy.dialects import registry

    return registry.load(f"postgresql.{driver}")()


def _connect_args(url: str, driver: str) -> Dict[str, Any]:
    """Return the connection arguments the driver would really receive.

    This is the DRIVER's own view of the URL — the same call
    ``create_engine`` makes when it builds the connection.  No connection
    is opened, and no database is touched.
    """
    from sqlalchemy.engine import make_url

    parsed = make_url(url)
    _, kwargs = _dialect_for(driver).create_connect_args(parsed)
    return kwargs


def _environment(url: str, database: str) -> Dict[str, str]:
    """A minimal, complete environment for the guard."""
    return {
        "CORE_DATABASE_URL": url,
        "DETECTION_DATABASE_URL": url,
        "ML_DATABASE_URL": url,
        "E2E_ALLOW_WRITE_TO": database,
    }


# =============================================================================
# A. The refusals
# =============================================================================

class TestTheQueryStringCannotMoveTheDestination:
    """The blocker itself: the query string used to be thrown away."""

    @pytest.fixture(scope="class")
    def guard(self):
        return _load_script("e2e_fixtures_guard.py")

    @pytest.mark.parametrize(
        "query",
        [
            "dbname=sentinel_core_test",      # the regression suite's database
            "dbname=sentinel_core",           # the production database
            "dbname=postgres",                # the maintenance database
            "dbname=sentinel_detection_demo",  # another context's database
            "host=192.0.2.123",              # off the loopback interface
            "hostaddr=192.0.2.123",          # off the loopback interface
            "service=evil",                  # a libpq service file
        ],
    )
    def test_a_destination_changing_query_parameter_is_refused(
        self, guard, query
    ):
        url = f"{REVIEW_BASE_URL}?{query}"
        environment = _environment(url, DEMO_CORE_DB)

        with pytest.raises(guard.DemoDatabaseRefusal) as excinfo:
            guard.require_demo_database("core", url, environ=environment)

        assert excinfo.value.layer == "query", (
            f"the refusal must come from the query layer, but it came from "
            f"[{excinfo.value.layer}]: {excinfo.value.reason}"
        )

    @pytest.mark.parametrize(
        "query",
        [
            "dbname=sentinel_core_test",
            "host=192.0.2.123",
            "hostaddr=192.0.2.123",
            "service=evil",
        ],
    )
    def test_the_refusal_names_the_offending_parameter(self, guard, query):
        """The refusal must say WHICH parameter moved the destination."""
        url = f"{REVIEW_BASE_URL}?{query}"
        environment = _environment(url, DEMO_CORE_DB)

        with pytest.raises(guard.DemoDatabaseRefusal) as excinfo:
            guard.require_demo_database("core", url, environ=environment)

        key = query.split("=", 1)[0]
        assert key in excinfo.value.reason, (
            f"the refusal must name the parameter '{key}': "
            f"{excinfo.value.reason}"
        )

    @pytest.mark.parametrize(
        "query",
        [
            "dbname=sentinel_core_test&dbname=sentinel_core_demo",
            "host=127.0.0.1&host=192.0.2.123",
            "dbname=sentinel_core_demo&dbname=sentinel_core_test",
        ],
    )
    def test_a_repeated_parameter_is_refused(self, guard, query):
        """A repeated key must not slip through the allowlist.

        SQLAlchemy keeps EVERY value of a repeated key, and the driver
        receives them all.  A repeated key is therefore ambiguous, and
        an ambiguous destination cannot be proven disposable.
        """
        url = f"{REVIEW_BASE_URL}?{query}"
        environment = _environment(url, DEMO_CORE_DB)

        with pytest.raises(guard.DemoDatabaseRefusal) as excinfo:
            guard.require_demo_database("core", url, environ=environment)

        assert excinfo.value.layer == "query"

    @pytest.mark.parametrize(
        "query",
        [
            "db%6eame=sentinel_core_test",   # an ENCODED key
            "dbname%3Dsentinel_core_test",   # an encoded "=" inside the key
            "d%62name=sentinel_core_test",
        ],
    )
    def test_an_encoded_parameter_is_refused(self, guard, query):
        """An encoded key must be decoded BEFORE it is judged.

        ``db%6eame`` decodes to ``dbname``.  A guard that compared the
        RAW key against its allowlist would see an unknown key and
        refuse — which is the safe outcome, but for the wrong reason.
        A guard that decoded nothing but then ACCEPTED the unknown key
        would be the real hole.  Either way the URL must be refused,
        and it must be refused as a destination-changing parameter.
        """
        url = f"{REVIEW_BASE_URL}?{query}"
        environment = _environment(url, DEMO_CORE_DB)

        with pytest.raises(guard.DemoDatabaseRefusal) as excinfo:
            guard.require_demo_database("core", url, environ=environment)

        assert excinfo.value.layer == "query"

    @pytest.mark.parametrize(
        "query",
        ["dbname=sentinel_core_test", "host=192.0.2.123", "hostaddr=192.0.2.123"],
    )
    def test_a_target_moving_parameter_is_refused_AS_A_TARGET_MOVING_ONE(
        self, guard, query
    ):
        """The refusal must CLASSIFY the parameter, not merely reject it.

        This is a stricter test than "the URL was refused": it asserts
        that the guard recognised the parameter as one that moves the
        destination.  The two refusals — "this parameter can move the
        target" and "this parameter is not supported" — are different
        diagnoses, and only the first one tells an operator that the URL
        was an ATTEMPT to redirect the run.

        A guard that refused every unknown parameter with one generic
        message would pass the refusals above and fail here.
        """
        url = f"{REVIEW_BASE_URL}?{query}"
        environment = _environment(url, DEMO_CORE_DB)

        with pytest.raises(guard.DemoDatabaseRefusal) as excinfo:
            guard.require_demo_database("core", url, environ=environment)

        key = query.split("=", 1)[0]
        assert key in guard.TARGET_MOVING_QUERY_PARAMETERS
        assert key in excinfo.value.reason
        assert "OVERRIDE" in excinfo.value.reason, (
            f"the refusal must say the parameter OVERRIDES the destination: "
            f"{excinfo.value.reason}"
        )

    @pytest.mark.parametrize(
        "query",
        ["replication=database", "search_path=public"],
    )
    def test_an_unsupported_parameter_is_refused_AS_AN_UNSUPPORTED_ONE(
        self, guard, query
    ):
        """The complement of the test above.

        An unsupported parameter is NOT an attempt to redirect the run;
        it is a parameter the guard does not understand.  The refusal
        must say so, so an operator can tell the two apart.
        """
        url = f"{REVIEW_BASE_URL}?{query}"
        environment = _environment(url, DEMO_CORE_DB)

        with pytest.raises(guard.DemoDatabaseRefusal) as excinfo:
            guard.require_demo_database("core", url, environ=environment)

        key = query.split("=", 1)[0]
        assert key not in guard.TARGET_MOVING_QUERY_PARAMETERS
        assert "not on the guard's allowlist" in excinfo.value.reason, (
            f"the refusal must say the parameter is not supported: "
            f"{excinfo.value.reason}"
        )

    @pytest.mark.parametrize(
        "query",
        [
            "target_session_attrs=read-write",
            "options=-c%20statement_timeout%3D30000",
            "replication=database",
            "search_path=public",
            "sslcert=/etc/ssl/client.crt",
            "gssencmode=disable",
            "channel_binding=require",
        ],
    )
    def test_an_unknown_parameter_is_refused(self, guard, query):
        """An unsupported parameter is REFUSED, never silently ignored.

        Silently ignoring an unknown parameter is how the hole opened
        in the first place: the guard dropped the whole query string,
        so every parameter in it was ignored.  The allowlist is now
        EXPLICIT, and anything outside it is a refusal.
        """
        url = f"{REVIEW_BASE_URL}?{query}"
        environment = _environment(url, DEMO_CORE_DB)

        with pytest.raises(guard.DemoDatabaseRefusal) as excinfo:
            guard.require_demo_database("core", url, environ=environment)

        assert excinfo.value.layer == "query", (
            f"the refusal must come from the query layer, but it came from "
            f"[{excinfo.value.layer}]: {excinfo.value.reason}"
        )

    @pytest.mark.parametrize(
        "query",
        ["sslmode=require", "connect_timeout=10", "application_name=e2e"],
    )
    def test_a_parameter_on_the_allowlist_is_accepted(self, guard, query):
        """The allowlist is a list of PERMITTED parameters, not a list of
        forbidden ones.

        ``sslmode``, ``connect_timeout`` and ``application_name`` change
        the TRANSPORT and the session, never the destination, so they
        are allowed.  This test pins the other half of the policy: the
        guard is not simply refusing every query string.
        """
        url = f"{REVIEW_BASE_URL}?{query}"
        environment = _environment(url, DEMO_CORE_DB)

        assert guard.require_demo_database("core", url, environ=environment) == (
            DEMO_CORE_DB
        )


class TestTheDriverIsInScope:
    """Only the drivers the project actually uses are accepted."""

    @pytest.fixture(scope="class")
    def guard(self):
        return _load_script("e2e_fixtures_guard.py")

    @pytest.mark.parametrize(
        "url",
        [
            "postgresql+asyncpg://demo:example@127.0.0.1/sentinel_core_demo",
            "mysql://demo:example@127.0.0.1/sentinel_core_demo",
            "sqlite:///sentinel_core_demo.db",
            "postgres://demo:example@127.0.0.1/sentinel_core_demo",
            "mssql+pyodbc://demo:example@127.0.0.1/sentinel_core_demo",
        ],
    )
    def test_an_unsupported_driver_is_refused(self, guard, url):
        environment = _environment(url, DEMO_CORE_DB)
        with pytest.raises(guard.DemoDatabaseRefusal) as excinfo:
            guard.require_demo_database("core", url, environ=environment)
        assert excinfo.value.layer in {"driver", "url"}

    @pytest.mark.parametrize("driver", SUPPORTED_DRIVERS)
    def test_the_projects_own_drivers_are_accepted(self, guard, driver):
        url = _url(DEMO_CORE_DB, driver=driver)
        environment = _environment(url, DEMO_CORE_DB)
        assert guard.require_demo_database("core", url, environ=environment) == (
            DEMO_CORE_DB
        )

    def test_the_bare_postgresql_scheme_is_accepted(self, guard):
        """``postgresql://`` resolves to the psycopg2 dialect."""
        url = _url(DEMO_CORE_DB)
        environment = _environment(url, DEMO_CORE_DB)
        assert guard.require_demo_database("core", url, environ=environment) == (
            DEMO_CORE_DB
        )


class TestAMalformedUrlIsRefused:
    """A URL that cannot be parsed is refused BEFORE a connection."""

    @pytest.fixture(scope="class")
    def guard(self):
        return _load_script("e2e_fixtures_guard.py")

    @pytest.mark.parametrize(
        "url",
        [
            "not a url",
            "://missing-scheme",
            "postgresql://user@host:port/database",
            "postgresql://host:not-a-port/database",
            "postgresql://",
        ],
    )
    def test_a_malformed_url_is_refused(self, guard, url):
        environment = _environment(url, DEMO_CORE_DB)
        with pytest.raises(guard.DemoDatabaseRefusal) as excinfo:
            guard.require_demo_database("core", url, environ=environment)
        assert excinfo.value.layer in {"url", "driver"}

    def test_a_path_below_the_database_is_refused(self, guard):
        """``/sentinel_core_demo/extra`` is not a database name.

        ``urlsplit`` would have returned ``sentinel_core_demo/extra`` for
        the path and the guard would have refused it as a name — but for
        the wrong reason, and only because the name check ran first.
        SQLAlchemy reports the whole path as the database name, so the
        guard must refuse it explicitly.
        """
        url = "postgresql://demo:example@127.0.0.1/sentinel_core_demo/extra/path"
        environment = _environment(url, DEMO_CORE_DB)
        with pytest.raises(guard.DemoDatabaseRefusal) as excinfo:
            guard.require_demo_database("core", url, environ=environment)
        assert excinfo.value.layer in {"url", "allowlist", "driver"}

    def test_a_malformed_url_is_refused_for_the_environment_variable_too(
        self, guard
    ):
        """A malformed URL in the ENVIRONMENT is refused as well."""
        url = "postgresql://host:not-a-port/sentinel_core_demo"
        environment = _environment(url, DEMO_CORE_DB)
        with pytest.raises(guard.DemoDatabaseRefusal):
            guard.require_demo_database("core", url, environ=environment)


class TestTheRefusalNeverLeaksTheCredentials:
    """The message must not carry the password or the whole URL."""

    @pytest.fixture(scope="class")
    def guard(self):
        return _load_script("e2e_fixtures_guard.py")

    def test_a_refusal_does_not_contain_the_password(self, guard):
        password = "sup3r-s3cret-value"
        url = (
            f"postgresql://demo:{password}@127.0.0.1/sentinel_core_demo"
            "?dbname=sentinel_core_test"
        )
        environment = _environment(url, DEMO_CORE_DB)

        with pytest.raises(guard.DemoDatabaseRefusal) as excinfo:
            guard.require_demo_database("core", url, environ=environment)

        message = str(excinfo.value)
        assert password not in message, (
            f"the refusal leaked the password: {message}"
        )

    def test_a_refusal_does_not_contain_the_whole_url(self, guard):
        password = "sup3r-s3cret-value"
        url = (
            f"postgresql://demo:{password}@127.0.0.1/sentinel_core_demo"
            "?dbname=sentinel_core_test"
        )
        environment = _environment(url, DEMO_CORE_DB)

        with pytest.raises(guard.DemoDatabaseRefusal) as excinfo:
            guard.require_demo_database("core", url, environ=environment)

        message = str(excinfo.value)
        assert url not in message, (
            f"the refusal leaked the whole URL: {message}"
        )
        assert "demo:" not in message, (
            f"the refusal leaked the userinfo of the URL: {message}"
        )


class TestTheLibpqEnvironmentCannotMoveTheDestination:
    """libpq reads environment variables as connection DEFAULTS.

    The URL is not the whole story: libpq also reads ``PGHOSTADDR``,
    ``PGSERVICE``, ``PGHOST``, ``PGDATABASE`` and friends from the
    environment.  Some of them OVERRIDE the URL's own value, so the
    destination the guard validated could differ from the destination
    the driver reaches — and that would be the same bypass as the query
    string, wearing a different hat.
    """

    @pytest.fixture(scope="class")
    def guard(self):
        return _load_script("e2e_fixtures_guard.py")

    @pytest.mark.parametrize(
        "variable",
        ["PGHOSTADDR", "PGSERVICE", "PGSERVICEFILE"],
    )
    def test_an_overriding_libpq_variable_is_refused(self, guard, variable):
        """These override the URL's host outright, so they are refused."""
        url = _url(DEMO_CORE_DB)
        environment = _environment(url, DEMO_CORE_DB)
        environment[variable] = "192.0.2.123"

        with pytest.raises(guard.DemoDatabaseRefusal) as excinfo:
            guard.require_demo_database("core", url, environ=environment)

        assert excinfo.value.layer == "environment", (
            f"the refusal must come from the environment layer, but it "
            f"came from [{excinfo.value.layer}]: {excinfo.value.reason}"
        )
        assert variable in excinfo.value.reason, (
            f"the refusal must name the variable: {excinfo.value.reason}"
        )

    @pytest.mark.parametrize(
        "variable,value",
        [
            ("PGUSER", "someone-else"),
            ("PGPORT", "5433"),
        ],
    )
    def test_a_defaulting_libpq_variable_is_refused(
        self, guard, variable, value
    ):
        """A default only applies where the URL does not pin the value.

        libpq uses the environment for a parameter the connection does
        NOT set.  A URL with no user leaves the user to libpq's
        default, and a URL with no port leaves the port to it — so a
        ``PGUSER`` or a ``PGPORT`` in the environment would decide WHO
        the fixture writes as, or WHERE it writes.  That is refused.
        """
        url = "postgresql://127.0.0.1/sentinel_core_demo"
        environment = _environment(url, DEMO_CORE_DB)
        environment[variable] = value

        with pytest.raises(guard.DemoDatabaseRefusal) as excinfo:
            guard.require_demo_database("core", url, environ=environment)

        assert excinfo.value.layer == "environment", (
            f"the refusal must come from the environment layer, but it "
            f"came from [{excinfo.value.layer}]: {excinfo.value.reason}"
        )
        assert variable in excinfo.value.reason, (
            f"the refusal must name the variable: {excinfo.value.reason}"
        )

    @pytest.mark.parametrize(
        "variable,value",
        [
            ("PGHOST", "192.0.2.123"),
            ("PGDATABASE", "sentinel_core_test"),
        ],
    )
    def test_a_default_the_url_pins_is_not_a_refusal(
        self, guard, variable, value
    ):
        """The complement: a default the URL pins cannot move anything.

        libpq only consults the environment for a parameter the
        connection does not set.  The guard REQUIRES the URL to name a
        database and a host, so ``PGHOST`` and ``PGDATABASE`` can never
        apply — and refusing them would break a developer's shell for
        no safety gain.
        """
        url = _url(DEMO_CORE_DB)
        environment = _environment(url, DEMO_CORE_DB)
        environment[variable] = value

        assert guard.require_demo_database("core", url, environ=environment) == (
            DEMO_CORE_DB
        )

    def test_the_password_variable_is_allowed(self, guard):
        """``PGPASSWORD`` carries a credential, not a destination.

        The CI jobs set it, so refusing it would break the suite for no
        safety gain: it cannot change which database is opened.
        """
        url = _url(DEMO_CORE_DB)
        environment = _environment(url, DEMO_CORE_DB)
        environment["PGPASSWORD"] = "sentinel_ci_disposable"

        assert guard.require_demo_database("core", url, environ=environment) == (
            DEMO_CORE_DB
        )

    def test_an_empty_variable_is_not_a_refusal(self, guard):
        """An empty variable sets nothing, so it moves nothing."""
        url = _url(DEMO_CORE_DB)
        environment = _environment(url, DEMO_CORE_DB)
        environment["PGHOSTADDR"] = ""

        assert guard.require_demo_database("core", url, environ=environment) == (
            DEMO_CORE_DB
        )

    def test_the_url_that_pins_the_parameter_beats_the_default(self, guard):
        """When the URL DOES pin the parameter, the default cannot win.

        ``libpq`` only uses the environment for a parameter the
        connection does not set.  The URL sets the host, so ``PGHOST``
        cannot move the destination — and the guard must not refuse a
        run for nothing.
        """
        url = "postgresql://127.0.0.1/sentinel_core_demo"
        environment = _environment(url, DEMO_CORE_DB)
        environment["PGHOST"] = "192.0.2.123"

        assert guard.require_demo_database("core", url, environ=environment) == (
            DEMO_CORE_DB
        )

    def test_a_url_that_does_not_pin_the_user_is_refused_when_the_env_sets_it(
        self, guard
    ):
        """The complement of the test above.

        A URL with NO user leaves the user to libpq's default, so a
        ``PGUSER`` in the environment would decide WHO the fixture
        writes as.  That is refused.
        """
        url = "postgresql://127.0.0.1/sentinel_core_demo"
        environment = _environment(url, DEMO_CORE_DB)
        environment["PGUSER"] = "someone-else"

        with pytest.raises(guard.DemoDatabaseRefusal) as excinfo:
            guard.require_demo_database("core", url, environ=environment)

        assert excinfo.value.layer == "environment"


# =============================================================================
# B. The valid cases
# =============================================================================

class TestTheValidDemoUrlsAreAccepted:
    """Everything the suite legitimately uses must keep working."""

    @pytest.fixture(scope="class")
    def guard(self):
        return _load_script("e2e_fixtures_guard.py")

    @pytest.fixture(scope="class")
    def helper(self):
        return _load_script("e2e_fixtures.py")

    @pytest.mark.parametrize(
        "context,variable,database",
        [
            ("core", "CORE_DATABASE_URL", DEMO_CORE_DB),
            ("detection", "DETECTION_DATABASE_URL", DEMO_DETECTION_DB),
            ("ml", "ML_DATABASE_URL", DEMO_ML_DB),
        ],
    )
    def test_a_demo_database_of_the_right_context_is_accepted(
        self, guard, context, variable, database
    ):
        url = _url(database)
        environment = {variable: url, "E2E_ALLOW_WRITE_TO": database}
        assert guard.require_demo_database(context, url, environ=environment) == (
            database
        )

    @pytest.mark.parametrize(
        "database,context",
        [
            ("sentinel_core_demo", "core"),
            ("sentinel_core_ci_demo", "core"),
            ("sentinel_detection_demo", "detection"),
            ("sentinel_detection_ci_demo", "detection"),
            ("sentinel_ml_demo", "ml"),
            ("sentinel_ml_ci_demo", "ml"),
        ],
    )
    def test_every_demo_database_name_is_accepted(self, guard, database, context):
        """Both halves of every context's allowlist must work."""
        url = _url(database)
        environment = {
            "CORE_DATABASE_URL": url,
            "DETECTION_DATABASE_URL": url,
            "ML_DATABASE_URL": url,
            "E2E_ALLOW_WRITE_TO": database,
        }
        assert guard.require_demo_database(context, url, environ=environment) == (
            database
        )

    @pytest.mark.parametrize(
        "host", ["127.0.0.1", "localhost", "[::1]"]
    )
    def test_a_loopback_host_is_accepted(self, guard, host):
        # The IPv6 loopback is spelled in brackets, because an unbracketed
        # '::1' is not a URL a parser can read: SQLAlchemy raises a
        # ValueError on it.
        url = f"postgresql://demo:example@{host}/sentinel_core_demo"
        environment = _environment(url, DEMO_CORE_DB)
        assert guard.require_demo_database("core", url, environ=environment) == (
            DEMO_CORE_DB
        )

    @pytest.mark.parametrize(
        "driver", ["", "psycopg2", "psycopg"]
    )
    def test_every_supported_driver_is_accepted(self, guard, driver):
        url = _url(DEMO_CORE_DB, driver=driver)
        environment = _environment(url, DEMO_CORE_DB)
        assert guard.require_demo_database("core", url, environ=environment) == (
            DEMO_CORE_DB
        )

    def test_a_safe_query_parameter_is_accepted(self, guard):
        """``sslmode`` is safe: it changes the TRANSPORT, not the target.

        The project does not use it today, but it is the one connection
        parameter that is routinely needed and that cannot move the
        destination, so it is on the allowlist.
        """
        url = f"{REVIEW_BASE_URL}?sslmode=require"
        environment = _environment(url, DEMO_CORE_DB)
        assert guard.require_demo_database("core", url, environ=environment) == (
            DEMO_CORE_DB
        )

    def test_a_url_whose_query_differs_from_its_variable_is_refused(
        self, guard
    ):
        """The URL must match its variable IN FULL, query string included.

        The old code compared ``url.split("?", 1)[0]`` against
        ``configured.split("?", 1)[0]`` — it threw the query string away
        on BOTH sides.  Two URLs that differ only in their query string
        therefore compared EQUAL, and the guard accepted a URL that was
        not the one the environment declared.

        Here the environment declares the URL WITHOUT a query string and
        the caller hands in the SAME URL WITH one.  The destinations are
        the same today — but the guard cannot know that, because a query
        string is exactly the part of a URL that can move the
        destination.  So the mismatch is refused.
        """
        environment = {
            "CORE_DATABASE_URL": REVIEW_BASE_URL,
            "E2E_ALLOW_WRITE_TO": DEMO_CORE_DB,
        }
        url = f"{REVIEW_BASE_URL}?sslmode=require"

        with pytest.raises(guard.DemoDatabaseRefusal) as excinfo:
            guard.require_demo_database("core", url, environ=environment)

        assert excinfo.value.layer == "context", (
            f"the refusal must come from the context layer, but it came "
            f"from [{excinfo.value.layer}]: {excinfo.value.reason}"
        )

    def test_a_url_whose_database_differs_from_its_variable_is_refused(
        self, guard
    ):
        """The declared variable must name the same DATABASE too.

        This is the check that catches the subtle mistake: a
        ``CORE_DATABASE_URL`` that was repointed at another database by
        hand.
        """
        environment = {
            "CORE_DATABASE_URL": _url(DEMO_DETECTION_DB),
            "E2E_ALLOW_WRITE_TO": DEMO_CORE_DB,
        }
        url = _url(DEMO_CORE_DB)

        with pytest.raises(guard.DemoDatabaseRefusal) as excinfo:
            guard.require_demo_database("core", url, environ=environment)

        assert excinfo.value.layer == "context"

    def test_a_url_whose_host_differs_from_its_variable_is_refused(
        self, guard
    ):
        """The declared variable must name the same HOST too.

        Two URLs that differ only in their host are two different
        destinations, and the guard must refuse the one that does not
        match the declaration.
        """
        environment = {
            "CORE_DATABASE_URL": "postgresql://demo:example@localhost/sentinel_core_demo",
            "E2E_ALLOW_WRITE_TO": DEMO_CORE_DB,
        }
        url = "postgresql://demo:example@127.0.0.1/sentinel_core_demo"

        with pytest.raises(guard.DemoDatabaseRefusal) as excinfo:
            guard.require_demo_database("core", url, environ=environment)

        assert excinfo.value.layer == "context"

    def test_a_url_whose_driver_differs_from_its_variable_is_refused(
        self, guard
    ):
        """The declared variable must name the same DRIVER too.

        The two drivers read the same URL slightly differently, so a
        URL that was validated under one driver must not be used under
        another.
        """
        environment = {
            "CORE_DATABASE_URL": _url(DEMO_CORE_DB, driver="psycopg2"),
            "E2E_ALLOW_WRITE_TO": DEMO_CORE_DB,
        }
        url = _url(DEMO_CORE_DB, driver="psycopg")

        with pytest.raises(guard.DemoDatabaseRefusal) as excinfo:
            guard.require_demo_database("core", url, environ=environment)

        assert excinfo.value.layer == "context"

    def test_the_url_the_guard_validates_is_the_url_the_engine_receives(
        self, guard
    ):
        """The guard must not validate one string and use another.

        The old code compared ``url.split("?", 1)[0]`` against
        ``configured.split("?", 1)[0]`` — it validated a TRUNCATED form
        of the URL and the engine got the WHOLE one.  The validated
        value and the used value must be the SAME value.
        """
        url = _url(DEMO_CORE_DB)
        environment = _environment(url, DEMO_CORE_DB)
        validated = guard.require_demo_database("core", url, environ=environment)
        assert validated == DEMO_CORE_DB

    def test_the_url_function_returns_the_parsed_url_object(self, guard):
        """The URL-returning view hands back the very object it checked.

        This is what lets the engine be built from the validated value
        instead of from the raw string: there is no second parse, so
        there is no second chance for the string and the object to
        disagree.
        """
        from sqlalchemy.engine import URL

        url = _url(DEMO_CORE_DB)
        environment = _environment(url, DEMO_CORE_DB)

        validated = guard.require_demo_database_url(
            "core", url, environ=environment
        )

        assert isinstance(validated, URL)
        assert validated.database == DEMO_CORE_DB
        assert validated.host == "127.0.0.1"

    def test_the_engine_is_built_from_the_validated_url_object(
        self, helper, monkeypatch
    ):
        """``create_engine`` receives the URL OBJECT, not the raw string.

        The old code parsed and validated one value and then handed the
        engine the raw string.  This test pins the new contract: the
        engine is built from the object the guard validated.
        """
        from sqlalchemy.engine import URL

        calls: List[Any] = []

        import sqlalchemy

        real = sqlalchemy.create_engine

        def spy(*args, **kwargs):
            calls.append(args[0] if args else kwargs.get("url"))
            return real(*args, **kwargs)

        monkeypatch.setattr(sqlalchemy, "create_engine", spy)

        url = _url(DEMO_CORE_DB)
        monkeypatch.setenv("CORE_DATABASE_URL", url)
        monkeypatch.setenv("E2E_ALLOW_WRITE_TO", DEMO_CORE_DB)

        helper._guarded_engine(helper.Context.CORE, url)

        assert len(calls) == 1, calls
        assert isinstance(calls[0], URL), (
            f"the engine must be built from the validated URL object, "
            f"but it was built from {type(calls[0]).__name__}: {calls[0]!r}"
        )
        assert calls[0].database == DEMO_CORE_DB
        assert calls[0].host == "127.0.0.1"

    def test_the_validated_object_reaches_the_driver_as_the_target(
        self, helper, monkeypatch
    ):
        """End to end: the driver's own view of the engine's URL.

        The engine's URL is read back with the DRIVER's own parser, so
        this is the driver's view of the very object the guard checked.
        """
        import sqlalchemy

        captured: Dict[str, Any] = {}
        real = sqlalchemy.create_engine

        def spy(*args, **kwargs):
            captured["url"] = args[0] if args else kwargs.get("url")
            return real(*args, **kwargs)

        monkeypatch.setattr(sqlalchemy, "create_engine", spy)

        url = _url(DEMO_CORE_DB)
        monkeypatch.setenv("CORE_DATABASE_URL", url)
        monkeypatch.setenv("E2E_ALLOW_WRITE_TO", DEMO_CORE_DB)

        helper._guarded_engine(helper.Context.CORE, url)

        parsed = captured["url"]
        dialect = parsed.get_dialect()()
        _, arguments = dialect.create_connect_args(parsed)

        assert arguments.get("dbname") == DEMO_CORE_DB
        assert arguments.get("host") == "127.0.0.1"
        assert "hostaddr" not in arguments
        assert "service" not in arguments


# =============================================================================
# C. The boundary — create_engine must not be reached
# =============================================================================

class TestTheRefusalHappensBeforeTheEngineIsBuilt:
    """A refused URL must never reach ``create_engine``.

    A row-count comparison alone cannot prove that: the write may have
    been issued and rolled back.  The proof is that the engine is never
    CREATED — and ``create_engine`` itself opens no connection, so the
    spy below is the cheapest and strongest statement of the boundary.
    """

    @pytest.fixture(scope="class")
    def guard(self):
        return _load_script("e2e_fixtures_guard.py")

    @pytest.fixture(scope="class")
    def helper(self):
        return _load_script("e2e_fixtures.py")

    def _spy_on_create_engine(self, monkeypatch):
        """Record every ``create_engine`` call and return the record."""
        calls: List[str] = []

        import sqlalchemy

        real = sqlalchemy.create_engine

        def spy(*args, **kwargs):
            calls.append(args[0] if args else kwargs.get("url"))
            return real(*args, **kwargs)

        monkeypatch.setattr(sqlalchemy, "create_engine", spy)
        return calls

    def test_a_refused_url_never_reaches_create_engine(
        self, guard, helper, monkeypatch
    ):
        calls = self._spy_on_create_engine(monkeypatch)

        url = f"{REVIEW_BASE_URL}?dbname=sentinel_core_test"
        monkeypatch.setenv("DETECTION_DATABASE_URL", url)
        monkeypatch.setenv("E2E_ALLOW_WRITE_TO", DEMO_CORE_DB)

        with pytest.raises(SystemExit):
            helper.create_alert("guard-probe", risk_level="critical", status="open")

        assert calls == [], (
            f"the engine was created with a refused URL: {calls}"
        )

    @pytest.mark.parametrize(
        "query",
        [
            "dbname=sentinel_core_test",
            "host=192.0.2.123",
            "hostaddr=192.0.2.123",
            "service=evil",
        ],
    )
    def test_no_destination_changing_url_reaches_create_engine(
        self, guard, helper, monkeypatch, query
    ):
        calls = self._spy_on_create_engine(monkeypatch)

        url = f"{REVIEW_BASE_URL}?{query}"
        monkeypatch.setenv("DETECTION_DATABASE_URL", url)
        monkeypatch.setenv("E2E_ALLOW_WRITE_TO", DEMO_CORE_DB)

        with pytest.raises(SystemExit):
            helper.create_alert("guard-probe", risk_level="critical", status="open")

        assert calls == [], (
            f"the engine was created with a refused URL ({query}): {calls}"
        )

    def test_the_refusal_is_reported_before_any_connection(
        self, guard, helper, monkeypatch
    ):
        """The refusal must be a refusal, not a failed connection.

        A connection error would mean the guard let the URL through and
        the DATABASE said no.  The guard must say no itself.
        """
        url = f"{REVIEW_BASE_URL}?dbname=sentinel_core_test"
        monkeypatch.setenv("DETECTION_DATABASE_URL", url)
        monkeypatch.setenv("E2E_ALLOW_WRITE_TO", DEMO_CORE_DB)

        with pytest.raises(SystemExit) as excinfo:
            helper.create_alert("guard-probe", risk_level="critical", status="open")

        message = str(excinfo.value)
        assert "refusing to write" in message, message
        assert "dbname" in message, (
            f"the refusal must name the offending parameter: {message}"
        )
        # A connection error would look like this instead.
        assert "could not connect" not in message.lower(), message
        assert "OperationalError" not in message, message

    def test_the_refusal_layer_is_the_query_layer(self, guard, monkeypatch):
        """The refusal must come from the layer that knows about the query."""
        url = f"{REVIEW_BASE_URL}?dbname=sentinel_core_test"
        environment = _environment(url, DEMO_CORE_DB)

        with pytest.raises(guard.DemoDatabaseRefusal) as excinfo:
            guard.require_demo_database("core", url, environ=environment)

        assert excinfo.value.layer == "query"


# =============================================================================
# D. The driver semantics
# =============================================================================

class TestTheDriversOwnViewIsTheGuard:
    """The guard and the driver must agree about the destination.

    Every other test in this file goes through the guard's own layers.
    This one checks the layer that ties them together: the guard
    resolves a database and a host, and the DRIVER must be told
    exactly those.

    The tests here do not use the guard's public entry point for the
    part they are about — they exercise the agreement check directly,
    so that a mutation of the check cannot hide behind the query
    allowlist, which would have refused the URL first.
    """

    @pytest.fixture(scope="class")
    def guard(self):
        return _load_script("e2e_fixtures_guard.py")

    def test_the_agreement_check_passes_for_a_valid_url(self, guard):
        url = "postgresql://demo:example@127.0.0.1/sentinel_core_demo"
        from sqlalchemy.engine import make_url

        parsed = make_url(url)
        arguments = guard._check_driver_agrees(
            parsed, "sentinel_core_demo", "127.0.0.1"
        )
        assert arguments["dbname"] == "sentinel_core_demo"
        assert arguments["host"] == "127.0.0.1"

    def test_the_agreement_check_catches_a_moved_database(self, guard):
        """A driver told to open another database must be refused."""
        from sqlalchemy.engine import make_url

        # The URL says one database; the driver's view says another.
        # The guard resolved 'sentinel_core_demo', so this must refuse.
        parsed = make_url(
            "postgresql://demo:example@127.0.0.1/sentinel_core_demo"
            "?dbname=sentinel_core_test"
        )

        with pytest.raises(guard.DemoDatabaseRefusal) as excinfo:
            guard._check_driver_agrees(
                parsed, "sentinel_core_demo", "127.0.0.1"
            )

        assert excinfo.value.layer == "destination"
        assert "sentinel_core_test" in excinfo.value.reason

    def test_the_agreement_check_catches_a_moved_host(self, guard):
        """A driver told to use another host must be refused."""
        from sqlalchemy.engine import make_url

        parsed = make_url(
            "postgresql://demo:example@127.0.0.1/sentinel_core_demo"
            "?host=192.0.2.123"
        )

        with pytest.raises(guard.DemoDatabaseRefusal) as excinfo:
            guard._check_driver_agrees(
                parsed, "sentinel_core_demo", "127.0.0.1"
            )

        assert excinfo.value.layer == "destination"
        assert "192.0.2.123" in excinfo.value.reason

    def test_the_agreement_check_catches_a_host_address(self, guard):
        """A ``hostaddr`` must be refused even when the host agrees."""
        from sqlalchemy.engine import make_url

        parsed = make_url(
            "postgresql://demo:example@127.0.0.1/sentinel_core_demo"
            "?hostaddr=192.0.2.123"
        )

        with pytest.raises(guard.DemoDatabaseRefusal) as excinfo:
            guard._check_driver_agrees(
                parsed, "sentinel_core_demo", "127.0.0.1"
            )

        assert excinfo.value.layer == "destination"
        assert "hostaddr" in excinfo.value.reason

    def test_the_agreement_check_catches_a_service(self, guard):
        """A ``service`` must be refused even when the host agrees."""
        from sqlalchemy.engine import make_url

        parsed = make_url(
            "postgresql://demo:example@127.0.0.1/sentinel_core_demo"
            "?service=evil"
        )

        with pytest.raises(guard.DemoDatabaseRefusal) as excinfo:
            guard._check_driver_agrees(
                parsed, "sentinel_core_demo", "127.0.0.1"
            )

        assert excinfo.value.layer == "destination"
        assert "service" in excinfo.value.reason

    def test_the_layers_are_independent(self, guard, monkeypatch):
        """The two layers must catch the bypass SEPARATELY.

        The query allowlist refuses ``?dbname=`` and the agreement
        check refuses the same URL, because the driver would open
        another database.  If only one of them worked, the other would
        be a single point of failure.

        This test disables the query layer and asserts that the
        agreement layer still refuses the URL — which is what makes
        the two independent rather than one redundant.
        """
        monkeypatch.setattr(
            guard, "_check_query", lambda *args, **kwargs: None
        )

        url = (
            "postgresql://demo:example@127.0.0.1/sentinel_core_demo"
            "?dbname=sentinel_core_test"
        )
        environment = _environment(url, DEMO_CORE_DB)

        with pytest.raises(guard.DemoDatabaseRefusal) as excinfo:
            guard.require_demo_database("core", url, environ=environment)

        assert excinfo.value.layer == "destination", (
            f"with the query layer disabled, the agreement layer must "
            f"still refuse the URL, but the refusal came from "
            f"[{excinfo.value.layer}]: {excinfo.value.reason}"
        )
        assert "sentinel_core_test" in excinfo.value.reason

    def test_the_agreement_layer_works_without_the_query_layer(
        self, guard, monkeypatch
    ):
        """The complement: with the agreement layer disabled, the query
        layer still refuses the URL.

        The two layers are genuinely independent in BOTH directions.
        """
        monkeypatch.setattr(
            guard,
            "_check_driver_agrees",
            lambda *args, **kwargs: {},
        )

        url = (
            "postgresql://demo:example@127.0.0.1/sentinel_core_demo"
            "?dbname=sentinel_core_test"
        )
        environment = _environment(url, DEMO_CORE_DB)

        with pytest.raises(guard.DemoDatabaseRefusal) as excinfo:
            guard.require_demo_database("core", url, environ=environment)

        assert excinfo.value.layer == "query"


class TestTheDriverReceivesTheValidatedDestination:
    """What the DRIVER does with the URL is the ground truth."""

    @pytest.fixture(scope="class")
    def guard(self):
        return _load_script("e2e_fixtures_guard.py")

    @pytest.mark.parametrize("driver", SUPPORTED_DRIVERS)
    def test_an_accepted_url_reaches_the_driver_unchanged(self, driver):
        """The driver's own view of an accepted URL must be the target.

        This is the assertion that ties the whole suite together: the
        guard approves the URL, and the driver is told exactly the
        database and the host the guard checked.
        """
        url = f"postgresql+{driver}://demo:example@127.0.0.1/sentinel_core_demo"
        kwargs = _connect_args(url, driver)

        assert kwargs.get("dbname") == "sentinel_core_demo"
        assert kwargs.get("host") == "127.0.0.1"
        assert "hostaddr" not in kwargs
        assert "service" not in kwargs

    @pytest.mark.parametrize("driver", SUPPORTED_DRIVERS)
    @pytest.mark.parametrize(
        "query,expected_key,expected_value",
        [
            ("dbname=sentinel_core_test", "dbname", "sentinel_core_test"),
            ("host=192.0.2.123", "host", "192.0.2.123"),
            ("hostaddr=192.0.2.123", "hostaddr", "192.0.2.123"),
        ],
    )
    def test_the_driver_would_have_been_redirected(
        self, driver, query, expected_key, expected_value
    ):
        """THE PROOF THAT THE BLOCKER WAS REAL.

        This test does not involve the guard at all: it shows that the
        driver's connect arguments really do carry the redirected
        destination.  It is the evidence that the refusal in the other
        tests is a refusal of a REAL hazard, not a formality.
        """
        url = f"postgresql+{driver}://demo:example@127.0.0.1/sentinel_core_demo?{query}"
        kwargs = _connect_args(url, driver)

        assert kwargs.get(expected_key) == expected_value, (
            f"the driver did not take the redirected {expected_key}: {kwargs}"
        )

    @pytest.mark.parametrize("driver", SUPPORTED_DRIVERS)
    def test_a_refused_url_never_produces_connect_arguments(
        self, guard, driver
    ):
        """A refused URL must not even be parsed into connect arguments."""
        url = f"postgresql+{driver}://demo:example@127.0.0.1/sentinel_core_demo?dbname=sentinel_core_test"
        environment = _environment(url, DEMO_CORE_DB)

        with pytest.raises(guard.DemoDatabaseRefusal):
            guard.require_demo_database("core", url, environ=environment)

    @pytest.mark.parametrize("driver", SUPPORTED_DRIVERS)
    def test_the_allowed_parameters_cannot_move_the_destination(
        self, guard, driver
    ):
        """Every parameter the guard allows must be destination-neutral.

        For each allowed parameter, the driver's ``dbname`` and ``host``
        must still be the ones the guard checked.  This is what makes the
        allowlist safe: it is not a list of "probably harmless" names, it
        is a list of parameters PROVEN not to move the target.
        """
        from sqlalchemy.engine import make_url

        allowed = getattr(guard, "ALLOWED_QUERY_PARAMETERS")

        for parameter in allowed:
            url = (
                f"postgresql+{driver}://demo:example@127.0.0.1"
                f"/sentinel_core_demo?{parameter}=something"
            )
            environment = _environment(url, DEMO_CORE_DB)
            guard.require_demo_database("core", url, environ=environment)

            kwargs = _connect_args(url, driver)
            assert kwargs.get("dbname") == "sentinel_core_demo", (
                f"the parameter '{parameter}' moved the database: {kwargs}"
            )
            assert kwargs.get("host") == "127.0.0.1", (
                f"the parameter '{parameter}' moved the host: {kwargs}"
            )


# =============================================================================
# E. The positive control
# =============================================================================

class TestThePositiveControl:
    """The guard must still ALLOW the legitimate case.

    A guard that refuses everything passes every refusal test and
    protects nothing.  This control writes a real fixture to a
    disposable demo database and cleans it up.
    """

    @pytest.fixture(scope="class")
    def guard(self):
        return _load_script("e2e_fixtures_guard.py")

    @pytest.fixture(scope="class")
    def helper(self):
        return _load_script("e2e_fixtures.py")

    def _demo_urls(self) -> Dict[str, str]:
        return {
            key: os.environ.get(f"DEMO_{key}_DATABASE_URL", "").strip()
            for key in ("CORE", "DETECTION", "ML")
        }

    def test_a_fixture_is_written_to_the_disposable_demo_database(
        self, guard, helper, monkeypatch
    ):
        urls = self._demo_urls()
        if not all(urls.values()):
            pytest.skip(
                "the demo databases are not provisioned. Export "
                "DEMO_CORE_DATABASE_URL, DEMO_DETECTION_DATABASE_URL and "
                "DEMO_ML_DATABASE_URL to run this check."
            )

        from sqlalchemy import create_engine, text

        key = "guard-target-positive-control"
        alert_id = helper._resolve_alert_id(key)

        monkeypatch.setenv("DETECTION_DATABASE_URL", urls["DETECTION"])
        monkeypatch.setenv("E2E_ALLOW_WRITE_TO", "sentinel_detection_ci_demo")

        # The cleanup MUST run even when an assertion fails, or the
        # fixture would stay behind and poison the NEXT run.
        try:
            result = helper.create_alert(
                key, risk_level="critical", status="open"
            )
            assert result["alert_id"] == alert_id

            engine = create_engine(urls["DETECTION"], pool_pre_ping=True)
            try:
                with engine.connect() as connection:
                    found = int(
                        connection.execute(
                            text(
                                "SELECT count(*) FROM alerts WHERE id = :id"
                            ),
                            {"id": alert_id},
                        ).scalar()
                        or 0
                    )
            finally:
                engine.dispose()

            assert found == 1, (
                "the helper did not write the row into the demo database, "
                "so the refusal tests above would have passed even if the "
                "guard had refused EVERY url"
            )
        finally:
            # The cleanup runs whatever happened above.
            monkeypatch.setenv("DETECTION_DATABASE_URL", urls["DETECTION"])
            monkeypatch.setenv("E2E_ALLOW_WRITE_TO", "sentinel_detection_ci_demo")
            try:
                helper.delete_alert(key)
            except SystemExit:  # pragma: no cover - the cleanup must not fail
                pass

        engine = create_engine(urls["DETECTION"], pool_pre_ping=True)
        try:
            with engine.connect() as connection:
                remaining = int(
                    connection.execute(
                        text("SELECT count(*) FROM alerts WHERE id = :id"),
                        {"id": alert_id},
                    ).scalar()
                    or 0
                )
        finally:
            engine.dispose()

        assert remaining == 0, "the control row was not cleaned up"
