#!/usr/bin/env python
"""Sentinel Auth v3.3 — the demo-database guard of the M13.2 E2E fixtures.

``scripts/e2e_fixtures.py`` WRITES rows (the alerts, the policies, the
sessions, the MFA gate, the rate-limit counters) and DELETES rows (the
alerts, the policies).  It is the ONLY thing in the browser suite that
writes to a database directly, so it is also the only place where a
mistake could reach a database that must never be touched.

This module is that place's guard.  It answers one question, in one
place, for all three bounded contexts:

    *is this URL a database the E2E suite is allowed to mutate?*

===========================================================================
THE SAFETY MODEL — FAIL-CLOSED, LAYER BY LAYER
===========================================================================

Every layer below REFUSES by default.  The destructive SQL runs only when
ALL of them are satisfied.  The layers are independent, so a bug in one
does not open a hole in the next.

    Layer 1  CONTEXT MATCH   The database name must be one of the two
                             names the CONTEXT owns, and the URL must
                             point at the CONTEXT's own URL variable.  A
                             core URL cannot reach the detection
                             database, and a detection URL cannot reach
                             the core database.

    Layer 2  NAME ALLOWLIST  The name must be EXACTLY one of the four
                             known demo names - the local demo stack's
                             ``*_demo`` names and the CI disposable
                             ``*_ci_demo`` names.  A suffix check alone
                             is not enough: ``sentinel_core_demo_prod``
                             would pass a ``_demo`` suffix check, and it
                             would be a production database.

    Layer 3  NO OVERLAP      The regression suite's ``*_test`` databases
                             and the canonical production databases are
                             refused outright.  They are not "demo
                             databases that happen to be named oddly" -
                             they are a different vocabulary with a
                             different owner.

    Layer 4  LOOPBACK HOST   The server must be on the loopback
                             interface.  A demo database that lives on
                             another host is a shared database, and a
                             shared database is not the suite's to
                             mutate.

    Layer 5  EXPLICIT OPT-IN The run must have declared that it is
                             allowed to write.  The declaration names
                             the EXACT database the helper is about to
                             touch, so it cannot be carried over from
                             another target.

NO SINGLE ENVIRONMENT VARIABLE CAN DISABLE THE PROTECTION.  Layers 1 to 4
are decided by the URL alone, and the allowlists are hard-coded: no
environment variable can widen them.  Layer 5 is a separate input, and it
must name the very database the helper is about to write to - so a
declaration that was made for one target cannot authorise another.

The declaration follows the convention of
``scripts/ci_bootstrap_demo_databases.sh``: it is a space-separated list
of database NAMES, and it is checked against the target the helper
resolved.  A generic "true" authorises nothing, and a declaration made
for one database cannot carry over to another.

===========================================================================
THE DESTINATION MUST BE THE SAME THING ALL THE WAY DOWN
===========================================================================

The layers above decide about a URL.  The layer below makes sure the URL
they decided about is the URL the DRIVER will actually use — because a
PostgreSQL URL can carry a QUERY STRING, and libpq lets the query string
OVERRIDE the parts of the URL:

    postgresql://demo:example@127.0.0.1/sentinel_core_demo?dbname=sentinel_core_test

    dialect.create_connect_args()  ->  {"host": "127.0.0.1",
                                        "dbname": "sentinel_core_test"}

The path still says ``sentinel_core_demo`` and the authority still says
``127.0.0.1``, but the driver is told to open ``sentinel_core_test``.
The guard used to read the path and the authority and then **drop the
query string** before comparing the URL with the context's own variable:

    if configured.split("?", 1)[0] != url.split("?", 1)[0]:

So it approved one destination and the driver reached another.  That is
the hole this module closes.

The rule the code below enforces is therefore:

    **The destination the guard allows must be the destination that
    reaches the driver.**

Concretely:

  * the URL is parsed with SQLAlchemy's OWN parser, so the guard reads
    the same URL the engine will read;
  * the query string is VALIDATED, not discarded: only an explicit
    allowlist of connection parameters is accepted, and every parameter
    that can move the destination (``host``, ``hostaddr``, ``dbname``,
    ``service``, ...) is refused outright;
  * an unknown parameter is REFUSED, never silently ignored — including
    a parameter that the URL's own parser would drop;
  * a repeated parameter is REFUSED, because the driver receives every
    value of it;
  * the libpq environment variables that can move a destination
    (``PGHOSTADDR``, ``PGSERVICE``, ``PGSERVICEFILE``) are refused when
    they are set, because libpq reads them as DEFAULTS for any
    parameter the URL does not set;
  * the guard RETURNS the URL object it validated, and that object is
    what the engine is built from — never a re-parsed string, never a
    truncated one.

===========================================================================
THE ONE DELIBERATE EXCEPTION
===========================================================================

``restore-active-policy`` restores the demo stack's SEEDED active policy.

Every other operation in this helper touches ONLY rows the E2E suite
created: the ids carry the ``m13-e2e-`` marker, and the helper refuses
to write to a row that does not carry it.  Restoring the seeded active
policy is the one operation that deliberately touches a row the suite did
NOT create, and it is a legitimate exception to the "E2E-owned rows
only" rule.

It is legitimate because it is the RESTORE of a state the behaviour under
test changed: activating a policy deactivates the current one - that is
the product behaviour, and the browser scenario has to prove it.  The
side effect is that the seeded ACTIVE policy of the demo stack is no
longer active, so the demo would drift away from its own fixtures.
Putting the demo back the way the scenario found it is therefore a
REQUIRED cleanup, not a way of hiding a defect.

The exception is scoped as tightly as the principle it bends:

  * it restores ONE named policy - the seeded ``m13-demo-active``;
  * it only ever moves the ACTIVE SLOT, so exactly one policy is active
    afterwards, which is the invariant the demo stack maintains;
  * it never deletes a policy, and it never touches the E2E-owned
    policies, which carry the evidence of the scenario;
  * it is still subject to every guard above - a non-demo database is
    refused just the same.

===========================================================================
USAGE
===========================================================================

    from scripts.e2e_fixtures_guard import Context, require_demo_database

    name = require_demo_database(Context.CORE, url, environ=os.environ)

    # ...or, when the engine is about to be built from the URL:

    from scripts.e2e_fixtures_guard import require_demo_database_url

    validated = require_demo_database_url(Context.CORE, url)
    engine = create_engine(validated, pool_pre_ping=True)
"""

from __future__ import annotations

import os
import re
from typing import Any, Dict, FrozenSet, List, Mapping, Optional, Tuple
from urllib.parse import parse_qsl

from sqlalchemy.engine import URL, make_url

#: The environment variable that carries the explicit opt-in.
#:
#: Its value is a space-separated list of database NAMES the helper is
#: allowed to write to.  A generic "true" authorises nothing: the
#: declaration has to name the target, so a declaration made for one
#: database cannot carry over to another.
E2E_WRITE_PERMISSION_VAR = "E2E_ALLOW_WRITE_TO"


class Context:
    """The three bounded contexts of the monolith."""

    CORE = "core"
    DETECTION = "detection"
    ML = "ml"

    ALL = (CORE, DETECTION, ML)


#: The database names each context owns, and the environment variable that
#: carries its URL.
#:
#: Each context owns exactly TWO names: the local demo stack's persistent
#: database and the CI disposable one.  They are disjoint from the
#: regression suite's ``*_test`` databases and from the canonical
#: production names, so a URL that resolves to one of them cannot be
#: mistaken for a demo database.
CONTEXT_DATABASES: Dict[str, FrozenSet[str]] = {
    Context.CORE: frozenset({"sentinel_core_demo", "sentinel_core_ci_demo"}),
    Context.DETECTION: frozenset({"sentinel_detection_demo", "sentinel_detection_ci_demo"}),
    Context.ML: frozenset({"sentinel_ml_demo", "sentinel_ml_ci_demo"}),
}

#: The environment variable that carries each context's URL.
CONTEXT_URL_VARS: Dict[str, str] = {
    Context.CORE: "CORE_DATABASE_URL",
    Context.DETECTION: "DETECTION_DATABASE_URL",
    Context.ML: "ML_DATABASE_URL",
}

#: The regression suite's disposable databases.  They are a different
#: vocabulary with a different owner, and they must never be reachable
#: from the E2E fixture helper.
PROTECTED_TEST_DATABASES: FrozenSet[str] = frozenset({
    "sentinel_core_test",
    "sentinel_detection_test",
    "sentinel_ml_test",
    "sentinel_legacy_test",
})

#: The canonical production database names.  These are what a real
#: deployment of this product uses, so a URL that resolves to one of them
#: is a production URL even if something else about it looks demo-ish.
PROTECTED_PRODUCTION_DATABASES: FrozenSet[str] = frozenset({
    "sentinel_core",
    "sentinel_detection",
    "sentinel_ml",
    "sentinel_auth",
    "sentinel",
    "postgres",
})

#: The hosts a demo database may live on.
#:
#: The local demo stack publishes PostgreSQL on the loopback interface,
#: and so does the CI job's service container.  A database on any other
#: host is a SHARED database, and a shared database is not the suite's to
#: mutate.
#:
#: The IPv6 loopback is listed in both its bare form (``::1``) and its
#: bracketed form (``[::1]``), because the two spellings of the same host
#: must not be a way around the check.
LOOPBACK_HOSTS: FrozenSet[str] = frozenset({
    "localhost",
    "127.0.0.1",
    "::1",
    "[::1]",
})

#: The PostgreSQL DIALECTS the project uses.
#:
#: The bare ``postgresql://`` form is SQLAlchemy's default PostgreSQL
#: dialect, which resolves to the psycopg2 one.
SUPPORTED_DIALECTS: FrozenSet[str] = frozenset({"postgresql"})

#: The PostgreSQL DRIVERS the project uses.
#:
#: ``requirements.txt`` pins ``psycopg[binary]`` and ``psycopg2-binary``,
#: and the CI URLs spell the driver explicitly as
#: ``postgresql+psycopg2://``.  Both dialects read the query string the
#: same way, so both are in scope for the driver-semantics check.
SUPPORTED_DRIVERS: FrozenSet[str] = frozenset({"psycopg2", "psycopg"})

#: The driver the bare ``postgresql://`` form resolves to.
DEFAULT_DRIVER = "psycopg2"

#: The query parameters the guard ALLOWS.
#:
#: Each of them changes the TRANSPORT or the session, never the
#: destination: none of them is a libpq target parameter, so none of them
#: can move the database or the host.  The allowlist is EXPLICIT — a
#: parameter that is not on it is refused, never ignored.
#:
#: ``sslmode`` is on it because it is the one parameter a PostgreSQL
#: deployment routinely needs and because it cannot change which server
#: or which database is reached.
ALLOWED_QUERY_PARAMETERS: FrozenSet[str] = frozenset({
    "sslmode",
    "connect_timeout",
    "application_name",
    "client_encoding",
})

#: The query parameters that can MOVE the destination.
#:
#: They are refused with a message of their own, so the refusal says
#: WHY it refused instead of only saying "unknown parameter".
TARGET_MOVING_QUERY_PARAMETERS: FrozenSet[str] = frozenset({
    "host",
    "hostaddr",
    "dbname",
    "database",
    "service",
    "port",
    "user",
    "password",
    "passfile",
    "target_session_attrs",
})

#: The libpq environment variables that can move the destination EVEN
#: though the URL pins it.
#:
#: ``PGHOSTADDR`` wins over the URL's ``host``, and a service file can
#: carry a ``hostaddr`` of its own — so both are refused outright when
#: they are set.  They are not "defaults" that the URL overrides; they
#: are overrides.
TARGET_MOVING_LIBPQ_ENVIRONMENT_VARIABLES: Tuple[str, ...] = (
    "PGHOSTADDR",
    "PGSERVICE",
    "PGSERVICEFILE",
)

#: The libpq environment variables that are only DEFAULTS: the URL's own
#: value wins.  They can still move the destination when the URL does
#: NOT pin the matching parameter, so the guard refuses that case.
LIBPQ_DEFAULT_ENVIRONMENT_VARIABLES: Dict[str, str] = {
    "PGHOST": "host",
    "PGPORT": "port",
    "PGDATABASE": "dbname",
    "PGUSER": "user",
}

#: The URL pattern of SQLAlchemy's own parser.
#:
#: It is mirrored here — NOT re-implemented — so that the guard can read
#: the RAW query string of a URL it has already parsed, and notice a
#: query string that SQLAlchemy's ``parse_qsl`` would silently DROP
#: (a field with an encoded "=" in its name, for instance).  A dropped
#: parameter is a parameter the guard did not judge, so it is refused.
#:
#: If this pattern ever stops matching a URL SQLAlchemy accepted, the
#: guard refuses the URL — the failure mode is closed, never open.
_SQLALCHEMY_URL_PATTERN = re.compile(
    r"""
        (?P<name>[\w\+]+)://
        (?:
            (?P<username>[^:/]*)
            (?::(?P<password>[^@]*))?
        @)?
        (?:
            (?:
                \[(?P<ipv6host>[^/\?]+)\] |
                (?P<ipv4host>[^/:\?]+)
            )?
            (?::(?P<port>[^/\?]*))?
        )?
        (?:/(?P<database>[^\?]*))?
        (?:\?(?P<query>.*))?
        """,
    re.X,
)


class DemoDatabaseRefusal(Exception):
    """Raised when a URL is not a database the E2E suite may mutate.

    It is a distinct exception type rather than a bare ``SystemExit`` so
    that the refusal can be *tested* as a value: a test asserts that the
    guard refused, and it reads the reason out of the exception.
    """

    def __init__(self, reason: str, layer: str) -> None:
        super().__init__(reason)
        self.reason = reason
        self.layer = layer

    def __str__(self) -> str:  # pragma: no cover - the message is the point
        return f"[{self.layer}] {self.reason}"


def _refuse(layer: str, reason: str) -> "DemoDatabaseRefusal":
    return DemoDatabaseRefusal(reason=reason, layer=layer)


def _parse_url(url: str) -> URL:
    """Parse a URL with SQLAlchemy's OWN parser.

    The guard must read the URL exactly the way the engine will read it,
    so it uses the engine's parser.  A URL SQLAlchemy cannot parse is
    refused: there is no way to prove a target the engine cannot even
    name.

    The refusal message never carries the URL, because a URL carries the
    password.
    """
    try:
        return make_url(url)
    except Exception as error:  # noqa: BLE001 - any parse failure is a refusal
        raise _refuse(
            "url",
            f"the connection URL could not be parsed as a SQLAlchemy URL "
            f"({type(error).__name__}), so the target it names cannot be "
            f"proven disposable.",
        ) from None


def database_name_of(url: str) -> str:
    """Return the database name a connection URL points at.

    An empty string is returned when the URL does not name a database at
    all - which is itself a refusal, because a URL without a database
    cannot be proven disposable.
    """
    try:
        parsed = make_url(url)
    except Exception:  # noqa: BLE001 - an unparsable URL names nothing
        return ""
    return parsed.database or ""


def host_of(url: str) -> str:
    """Return the host a connection URL points at.

    An empty string is returned when the URL names no host.
    """
    try:
        parsed = make_url(url)
    except Exception:  # noqa: BLE001 - an unparsable URL names no host
        return ""
    return parsed.host or ""


def _raw_query_of(url: str) -> Optional[str]:
    """Return the RAW query string of a URL.

    ``None`` means "the URL has no query string at all", which is the
    ordinary case and needs no parameter validation.  An empty string
    means "the URL has a query string that is empty" — which also needs
    no validation, but is a different thing from "no query string".
    """
    match = _SQLALCHEMY_URL_PATTERN.match(url)
    if match is None:
        raise _refuse(
            "url",
            "the connection URL does not have the shape of a SQLAlchemy "
            "URL, so its query string cannot be validated.",
        )
    return match.group("query")


def _query_parameters(parsed: URL, raw: str) -> Dict[str, List[str]]:
    """Return the query parameters as the DRIVER will receive them.

    Two reads are compared:

      * the parameters SQLAlchemy parsed into ``parsed.query`` — these
        are the ones the dialect hands to the driver;
      * the parameters the RAW query string holds — read with
        ``keep_blank_values=True`` so that a field SQLAlchemy would
        DROP is still visible.

    When the two reads disagree, the query string cannot be read
    unambiguously, and the guard refuses it rather than guessing which
    reading the driver will use.  That is what stops an encoded
    variant — ``dbname%3Dsentinel_core_test`` — from slipping between
    the two.
    """
    parsed_parameters: Dict[str, List[str]] = {}
    for key, value in parsed.query.items():
        if isinstance(value, (tuple, list)):
            parsed_parameters[key] = [str(item) for item in value]
        else:
            parsed_parameters[key] = [str(value)]

    raw_parameters: Dict[str, List[str]] = {}
    for key, value in parse_qsl(raw, keep_blank_values=True):
        raw_parameters.setdefault(key, []).append(value)

    if parsed_parameters != raw_parameters:
        raise _refuse(
            "query",
            "the query string of the connection URL cannot be read "
            "unambiguously: it does not parse to the same parameters the "
            "driver would receive. A query string that means two things "
            "cannot be proven harmless, so it is refused.",
        )

    return parsed_parameters


def _check_driver(parsed: URL) -> str:
    """Refuse a URL whose dialect or driver the project does not use.

    Only the PostgreSQL dialects the project actually uses are in
    scope.  Another driver's URL is a different target model entirely,
    and its query string may mean something else again — so it is
    refused rather than interpreted.
    """
    drivername = parsed.drivername or ""
    if "+" in drivername:
        dialect_name, driver = drivername.split("+", 1)
    else:
        dialect_name, driver = drivername, ""

    if dialect_name not in SUPPORTED_DIALECTS:
        raise _refuse(
            "driver",
            f"the connection URL asks for the '{dialect_name}' database, "
            f"which this suite does not use. Only "
            f"{', '.join(sorted(SUPPORTED_DIALECTS))} is in scope.",
        )

    if driver and driver not in SUPPORTED_DRIVERS:
        raise _refuse(
            "driver",
            f"the connection URL asks for the '{driver}' driver, which "
            f"this suite does not use. The drivers in scope are: "
            f"{', '.join(sorted(SUPPORTED_DRIVERS))}.",
        )

    return driver or DEFAULT_DRIVER


def _check_query(parsed: URL, raw: str) -> None:
    """Refuse a query string that can move the destination.

    The query string is NOT a free-form extra: it is a set of libpq
    connection parameters, and libpq lets them override the parts of the
    URL.  So:

      * a parameter that can move the destination is refused outright;
      * a parameter that is not on the allowlist is refused — never
        ignored, because an ignored parameter is an unjudged one;
      * a REPEATED parameter is refused, because the driver receives
        every value of it.
    """
    parameters = _query_parameters(parsed, raw)

    for key in sorted(parameters):
        values = parameters[key]

        if key in TARGET_MOVING_QUERY_PARAMETERS:
            raise _refuse(
                "query",
                f"the connection URL carries the query parameter '{key}', "
                f"which libpq would use to OVERRIDE the database or the "
                f"host of the URL. The guard checks one destination and "
                f"the driver would connect to another, so '{key}' is "
                f"refused.",
            )

        if key not in ALLOWED_QUERY_PARAMETERS:
            raise _refuse(
                "query",
                f"the connection URL carries the query parameter '{key}', "
                f"which is not on the guard's allowlist. A parameter that "
                f"is not understood cannot be proven harmless, so it is "
                f"refused. The parameters in scope are: "
                f"{', '.join(sorted(ALLOWED_QUERY_PARAMETERS))}.",
            )

        if len(values) > 1:
            raise _refuse(
                "query",
                f"the connection URL repeats the query parameter '{key}', "
                f"so the driver would receive more than one value for it. "
                f"An ambiguous parameter cannot be proven harmless, so it "
                f"is refused.",
            )


def _connect_arguments(parsed: URL) -> Dict[str, Any]:
    """Return the connection arguments the DRIVER would really receive.

    This is the driver's own view of the URL — the same call
    ``create_engine`` makes when it builds a connection.  No connection is
    opened, and no database is touched.
    """
    dialect = parsed.get_dialect()()
    _, arguments = dialect.create_connect_args(parsed)
    return dict(arguments)


def _check_driver_agrees(
    parsed: URL, name: str, host: str
) -> Dict[str, Any]:
    """Refuse a URL whose driver's view differs from the guard's.

    This is the check that ties the whole module together: the guard
    decided about a database and a host, so the driver must be told
    exactly those.
    """
    arguments = _connect_arguments(parsed)

    driver_host = str(arguments.get("host") or "").lower()
    if driver_host != host:
        raise _refuse(
            "destination",
            f"the guard resolved the host '{host}', but the driver would "
            f"connect to '{driver_host or 'no host at all'}'. The "
            f"destination the guard allows must be the destination that "
            f"reaches the driver.",
        )

    driver_database = str(arguments.get("dbname") or "")
    if driver_database != name:
        raise _refuse(
            "destination",
            f"the guard resolved the database '{name}', but the driver "
            f"would connect to '{driver_database or 'no database at all'}'. "
            f"The destination the guard allows must be the destination "
            f"that reaches the driver.",
        )

    for parameter in ("hostaddr", "service"):
        if parameter in arguments:
            raise _refuse(
                "destination",
                f"the driver would receive the connection parameter "
                f"'{parameter}', which can point the connection somewhere "
                f"else. The destination the guard allows must be the "
                f"destination that reaches the driver.",
            )

    return arguments


def _check_libpq_environment(
    environ: Mapping[str, str], arguments: Mapping[str, Any]
) -> None:
    """Refuse a run whose environment can move the destination.

    libpq reads a set of environment variables as DEFAULTS for the
    connection parameters, and some of them can point the connection
    somewhere the URL does not name.  Two groups are refused:

      * ``PGHOSTADDR``, ``PGSERVICE`` and ``PGSERVICEFILE`` — these
        OVERRIDE the URL's own ``host``, so they are refused outright;
      * ``PGHOST``, ``PGPORT``, ``PGDATABASE`` and ``PGUSER`` — these
        are only defaults, so the URL wins whenever the URL pins the
        matching parameter.  When the URL does NOT pin it, the
        environment could move the destination, and the run is refused.

    ``PGPASSWORD`` is deliberately NOT in either group: it carries a
    credential, not a destination, and the CI jobs set it.
    """
    for variable in TARGET_MOVING_LIBPQ_ENVIRONMENT_VARIABLES:
        if (environ.get(variable) or "").strip():
            raise _refuse(
                "environment",
                f"the environment variable {variable} is set. libpq would "
                f"let it override the host of the connection URL, so the "
                f"destination the guard validates could differ from the "
                f"destination the driver reaches. Unset {variable} before "
                f"running the E2E fixtures.",
            )

    for variable, parameter in sorted(LIBPQ_DEFAULT_ENVIRONMENT_VARIABLES.items()):
        if not (environ.get(variable) or "").strip():
            continue
        if parameter in arguments:
            # The URL pins this parameter, so the environment cannot
            # move it.
            continue
        raise _refuse(
            "environment",
            f"the environment variable {variable} is set and the "
            f"connection URL does not pin the '{parameter}' it would "
            f"default to. libpq would fill the gap and the destination "
            f"could differ from the validated one. Unset {variable} "
            f"before running the E2E fixtures.",
        )


def _url_fingerprint(parsed: URL) -> Tuple[Any, ...]:
    """Return the parts of a URL that decide its destination.

    Two URLs are the same destination when their driver, their host,
    their port, their database, their user and their query parameters
    are the same.  The password is NOT part of the fingerprint: it is a
    credential, not a destination, and comparing it would put a secret
    into an error path.
    """
    query = parsed.query or {}
    return (
        parsed.drivername,
        parsed.username,
        parsed.host,
        parsed.port,
        parsed.database,
        tuple(
            sorted(
                (key, tuple(value) if isinstance(value, (tuple, list)) else (value,))
                for key, value in query.items()
            )
        ),
    )


def require_demo_database_url(
    context: str,
    url: str,
    environ: Optional[Mapping[str, str]] = None,
    allow_write_to: Optional[str] = None,
) -> URL:
    """Refuse to continue unless ``url`` is a database this suite may mutate.

    :param context: the bounded context that owns the database - one of
        :data:`Context.CORE`, :data:`Context.DETECTION`,
        :data:`Context.ML`.
    :param url: the connection URL the helper is about to use.
    :param environ: the environment the declarations are read from.
        Defaults to ``os.environ``.
    :param allow_write_to: the database name the caller has declared it
        is allowed to write to.  Defaults to the value of the
        ``E2E_ALLOW_WRITE_TO`` environment variable.
    :return: the validated URL object — the very object the engine must
        be built from.
    :raises DemoDatabaseRefusal: when the URL is not an allowed demo
        database for this context.
    """
    env = os.environ if environ is None else environ

    if context not in CONTEXT_DATABASES:
        raise _refuse(
            "context",
            f"'{context}' is not a bounded context of the monolith. "
            f"The known contexts are: {', '.join(Context.ALL)}.",
        )

    if not url or not url.strip():
        raise _refuse(
            "url",
            f"{CONTEXT_URL_VARS[context]} is empty, so there is no target to "
            f"prove disposable.",
        )

    parsed = _parse_url(url)
    _check_driver(parsed)

    # --- the query string ------------------------------------------------
    # It is read BEFORE the name and the host, because a query string
    # can REPLACE both: the path of the URL may say "sentinel_core_demo"
    # while the driver is told to open "sentinel_core_test".
    raw_query = _raw_query_of(url)
    if raw_query:
        _check_query(parsed, raw_query)

    name = parsed.database or ""
    if not name:
        raise _refuse(
            "url",
            "the connection URL does not name a database, so it cannot be "
            "proven disposable.",
        )

    # --- Layer 2: the name allowlist ------------------------------------
    # The check is an EXACT match against the two names the context
    # owns.  A suffix check would be too weak: 'sentinel_core_demo_prod'
    # ends with neither '_demo' nor '_ci_demo' in the right place, and
    # 'sentinel_core_demo_backup' would pass a naive '_demo' check.
    allowed = CONTEXT_DATABASES[context]
    if name not in allowed:
        raise _refuse(
            "allowlist",
            f"the database '{name}' is not a demo database of the "
            f"'{context}' context. The '{context}' context may only ever "
            f"touch: {', '.join(sorted(allowed))}.",
        )

    # --- Layer 3: no overlap with the other vocabularies ----------------
    if name in PROTECTED_TEST_DATABASES:
        raise _refuse(
            "overlap",
            f"the database '{name}' belongs to the regression suite. The "
            f"E2E fixture helper must never reach a '*_test' database.",
        )

    if name in PROTECTED_PRODUCTION_DATABASES:
        raise _refuse(
            "overlap",
            f"the database '{name}' is a production database name. The E2E "
            f"fixture helper must never reach a production database.",
        )

    # --- Layer 4: the loopback host -------------------------------------
    host = (parsed.host or "").lower()
    if not host:
        raise _refuse(
            "host",
            "the connection URL names no host, so the target cannot be "
            "proven to be a local, throwaway server.",
        )

    if host not in LOOPBACK_HOSTS:
        raise _refuse(
            "host",
            f"the connection URL points at the host '{host}'. A demo "
            f"database must live on the loopback interface "
            f"({', '.join(sorted(LOOPBACK_HOSTS))}); a database on another "
            f"host is a SHARED database and is not the suite's to mutate.",
        )

    # --- the driver's view must agree with the guard's ------------------
    arguments = _check_driver_agrees(parsed, name, host)

    # --- the libpq environment must not move the destination ------------
    _check_libpq_environment(env, arguments)

    # --- Layer 5: the explicit opt-in -----------------------------------
    # The declaration must name the very database that is about to be
    # written to.  A generic acknowledgement authorises nothing, and a
    # declaration made for another target cannot carry over.
    declared = allow_write_to if allow_write_to is not None else env.get(
        E2E_WRITE_PERMISSION_VAR, ""
    )
    declared_names = {
        part for part in (declared or "").split() if part
    }

    if not declared_names:
        raise _refuse(
            "permission",
            f"the run has not declared that it may write to a demo "
            f"database. Set {E2E_WRITE_PERMISSION_VAR}={name} — naming the "
            f"exact database — before the E2E fixtures may write. The "
            f"helper refuses to mutate a database that nobody authorised.",
        )

    if name not in declared_names:
        raise _refuse(
            "permission",
            f"the run declared {E2E_WRITE_PERMISSION_VAR}="
            f"{' '.join(sorted(declared_names))!r}, but the helper is about "
            f"to write to '{name}'. The declaration must name the exact "
            f"target, so an authorisation for one database cannot carry "
            f"over to another.",
        )

    # --- Layer 1: the URL variable must belong to this context -----------
    # This is checked LAST, because it is the layer that catches the most
    # subtle mistake: a CORE_DATABASE_URL that was accidentally pointed at
    # the detection database.  The name check above already refused any
    # name the context does not own, so reaching this point means the
    # name IS one of the context's own - and this layer asserts that the
    # variable the URL came from is the context's own variable too.
    expected_var = CONTEXT_URL_VARS[context]
    configured = (env.get(expected_var, "") or "").strip()
    if not configured:
        raise _refuse(
            "context",
            f"{expected_var} is not set, so the '{context}' context has no "
            f"declared target.",
        )

    configured_parsed = _parse_url(configured)
    _check_driver(configured_parsed)

    if _url_fingerprint(configured_parsed) != _url_fingerprint(parsed):
        raise _refuse(
            "context",
            f"the URL the '{context}' context is about to use does not match "
            f"the {expected_var} it was taken from. The three bounded "
            f"contexts must each reach their OWN database.",
        )

    return parsed


def require_demo_database(
    context: str,
    url: str,
    environ: Optional[Mapping[str, str]] = None,
    allow_write_to: Optional[str] = None,
) -> str:
    """Refuse to continue unless ``url`` is a database this suite may mutate.

    This is the name-only view of :func:`require_demo_database_url`.  A
    caller that goes on to build an engine should use that function
    instead, because it returns the very URL object the guard validated.

    :param context: the bounded context that owns the database - one of
        :data:`Context.CORE`, :data:`Context.DETECTION`,
        :data:`Context.ML`.
    :param url: the connection URL the helper is about to use.
    :param environ: the environment the declarations are read from.
        Defaults to ``os.environ``.
    :param allow_write_to: the database name the caller has declared it
        is allowed to write to.  Defaults to the value of the
        ``E2E_ALLOW_WRITE_TO`` environment variable.
    :return: the validated database name.
    :raises DemoDatabaseRefusal: when the URL is not an allowed demo
        database for this context.
    """
    parsed = require_demo_database_url(
        context,
        url,
        environ=environ,
        allow_write_to=allow_write_to,
    )
    return parsed.database or ""
