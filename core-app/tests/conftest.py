"""Database fixtures for portable unit tests and real PostgreSQL validation."""

from __future__ import annotations

import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.models import Base


@pytest.fixture(scope="session")
def postgres_test_database_url() -> str | None:
    """Create an isolated PostgreSQL database when integration testing is enabled.

    Set CORE_APP_TEST_DATABASE_URL to a PostgreSQL database URL. Its server
    credentials are used only to create and remove a generated test database;
    the configured database itself is never modified by the tests.
    """

    configured_url = os.getenv("CORE_APP_TEST_DATABASE_URL")
    if not configured_url:
        yield None
        return

    application_url = make_url(configured_url)
    if application_url.get_backend_name() != "postgresql":
        raise pytest.UsageError("CORE_APP_TEST_DATABASE_URL must be a PostgreSQL URL")

    test_database = f"core_app_test_{uuid4().hex}"
    admin_url = application_url.set(database="postgres")
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        with admin_engine.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{test_database}"'))
        yield application_url.set(database=test_database).render_as_string(hide_password=False)
    finally:
        with admin_engine.connect() as connection:
            connection.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :database_name AND pid <> pg_backend_pid()"
                ),
                {"database_name": test_database},
            )
            connection.execute(text(f'DROP DATABASE IF EXISTS "{test_database}"'))
        admin_engine.dispose()


@pytest.fixture
def database_url(tmp_path, postgres_test_database_url: str | None) -> str:
    if postgres_test_database_url:
        return postgres_test_database_url
    return f"sqlite+pysqlite:///{tmp_path / 'core-app.db'}"


@pytest.fixture
def database_engine(database_url: str):
    engine = create_engine(database_url)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    try:
        yield engine
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()
