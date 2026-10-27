"""Shared helpers for the PostgreSQL-dependent test modules.

The PostgreSQL integration tests need a real PostgreSQL server.  When that
server is not configured, they must **skip** with an explicit reason - not
error out during fixture setup.  A missing test database is an absent
capability, not a broken test, and a run without PostgreSQL must still be
able to report a clean result.

This module centralises:

* :func:`postgres_env_configured` - are the required variables present?
* :func:`missing_postgres_env_vars` - which ones are missing?
* :func:`require_postgres_env` - skip the calling module when they are not.
* :func:`assert_disposable_database` - refuse to run against a
  production database name.

The tests that use it do NOT become weaker when PostgreSQL IS configured:
the skip only fires when the environment is genuinely absent.
"""
from __future__ import annotations

import os

#: The environment variables a PostgreSQL-backed test run needs.
#:
#: ``POSTGRES_PORT`` is optional and defaults to 5432, but the others must
#: be set explicitly so that a test run can never silently target an
#: unexpected server.
REQUIRED_POSTGRES_ENV_VARS = (
    "POSTGRES_HOST",
    "POSTGRES_DB",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
)

#: Database names that must never be used as a test target.  The
#: PostgreSQL tests DROP and recreate the ``public`` schema, so pointing
#: them at a production database would destroy it.
PROTECTED_DATABASE_NAMES = frozenset({
    "sentinel",
    "sentinel_auth",
    "sentinel_core",
    "sentinel_detection",
    "sentinel_ml",
})


def missing_postgres_env_vars() -> list:
    """Return the names of the required PostgreSQL variables that are absent."""
    return [
        name for name in REQUIRED_POSTGRES_ENV_VARS
        if not os.environ.get(name)
    ]


def postgres_env_configured() -> bool:
    """Return True when every required PostgreSQL variable is present."""
    return not missing_postgres_env_vars()


def require_postgres_env(module_name: str) -> None:
    """Skip the calling module when PostgreSQL is not configured.

    Raises:
        pytest.skip.Exception: with an explicit, actionable reason.
    """
    import pytest

    missing = missing_postgres_env_vars()
    if not missing:
        return

    pytest.skip(
        f"NOT RUN - PostgreSQL is not configured, so {module_name} was "
        f"skipped. Missing environment variable(s): "
        f"{', '.join(missing)}. Set them to run the PostgreSQL integration "
        f"tests (see tests/conftest.py and .env.example).",
        allow_module_level=True,
    )


def assert_disposable_database(url: str, label: str) -> str:
    """Fail loudly when the URL points at a protected production database.

    The PostgreSQL tests recreate the ``public`` schema, so they must never
    run against a database whose name is one of the canonical production
    databases.
    """
    import pytest

    name = url.rsplit("/", 1)[-1].split("?", 1)[0]
    if name.lower() in PROTECTED_DATABASE_NAMES:
        pytest.fail(
            f"Refusing to run {label} against {name!r}: it is a protected "
            f"production database name and the test recreates the public "
            f"schema. Point POSTGRES_DB at a disposable test database."
        )
    return name
