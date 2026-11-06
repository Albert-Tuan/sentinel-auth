"""Test fixtures backed by a real (SQLite) database.

The models declare ``UUID``/``INET`` with a TEXT variant (see
``app/models.py``), so the very same metadata can be created on SQLite.
That lets the tests exercise real SQLAlchemy behaviour - constraints,
cascades, relationships - instead of hand-written mocks.
"""
from __future__ import annotations

import json
from typing import Iterator

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session as OrmSession, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import (
    Alert,
    Policy,
    Role,
    Session,
    User,
    UserRole,
)


@pytest.fixture()
def engine():
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(eng, "connect")
    def _enable_fk(dbapi_conn, _record):  # noqa: ARG001
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    Base.metadata.create_all(eng)
    # The engine is torn down with the fixture; no explicit DROP needed since
    # every test gets a fresh in-memory database.
    yield eng


@pytest.fixture()
def db(engine) -> Iterator[OrmSession]:
    maker = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = maker()
    try:
        yield session
    finally:
        session.close()


def _override_get_db(session: OrmSession):
    def _get_db():
        return session

    return _get_db


@pytest.fixture()
def app():
    """The FastAPI application instance (for route-table inspection)."""
    from app.main import app as fastapi_app
    return fastapi_app


#: The bounded-context DB dependencies that the routers declare.  Every
#: module is listed with the context it owns, so the SQLite test session
#: replaces the real PostgreSQL sessions regardless of which URL the
#: environment happens to configure.
CONTEXT_DEPENDENCIES = (
    ("core", "get_core_db"),
    ("detection", "get_detection_db"),
    ("ml", "get_ml_db"),
    # The Manager facade reads the ML context through a tolerant wrapper
    # so that an unresolvable ML database degrades the ML source instead
    # of failing the request.  It must be overridden too, otherwise the
    # Manager routes would open a real session.
    ("ml", "get_optional_ml_db"),
)


@pytest.fixture()
def client(db):
    """A TestClient whose DB dependencies return the SQLite session.

    The monolith declares three session dependencies - one per bounded
    context (``get_core_db``, ``get_detection_db``, ``get_ml_db``).  The unit
    tests run on a single in-memory SQLite database, so all three are
    overridden with the same session.
    """
    from fastapi.testclient import TestClient

    from app.main import app

    override = _override_get_db(db)
    app.dependency_overrides = {}
    for module in _all_route_modules():
        for _context, attribute in CONTEXT_DEPENDENCIES:
            dependency = getattr(module, attribute, None)
            if dependency is not None:
                app.dependency_overrides[dependency] = override
    try:
        with TestClient(app) as c:
            yield c
    finally:
        app.dependency_overrides = {}


#: The URL the Core context is reachable at inside the tests.  The
#: ``core_receiver`` fixture mounts the ASGI transport on this host.
CORE_TEST_URL = "http://core.test"


@pytest.fixture()
def core_receiver(monkeypatch):
    """Route Core-bound internal calls into the same FastAPI application.

    The Detection context enforces protective actions by calling Core over
    the canonical service boundary (``POST /api/v1/internal/actions``).
    A test that exercises that path needs a receiver that actually accepts
    the call - otherwise the delivery is a ``ConnectError`` and the
    enforcement can never be observed.

    This fixture installs an ``httpx.AsyncClient`` that mounts an ASGI
    transport on the Core host, so the real Core router, the real
    ``X-Internal-Secret`` verification and the real Core database write all
    run.  The HTTP boundary is exercised end-to-end; only the socket is
    replaced.

    It returns a recorder that captures the requests that were made, so a
    test can assert on the method, the path and the call count.
    """
    import httpx

    from app.main import app
    from app import internal_client
    calls: list = []

    class _RecordingTransport(httpx.AsyncBaseTransport):
        """ASGI transport that records every request it dispatches."""

        def __init__(self, inner):
            self._inner = inner

        async def handle_async_request(self, request):
            body = None
            try:
                body = json.loads(request.content.decode() or "null")
            except (ValueError, UnicodeDecodeError):
                body = None
            calls.append(
                {
                    "method": request.method,
                    "path": request.url.path,
                    "url": str(request.url),
                    "headers": dict(request.headers),
                    "json": body,
                }
            )
            return await self._inner.handle_async_request(request)

    transport = _RecordingTransport(httpx.ASGITransport(app=app))
    original_init = httpx.AsyncClient.__init__

    def _asgi_init(self, *args, **kwargs):
        """Give the client a routing mount for the Core host.

        ``httpx`` resolves the transport per request URL, so mounting the
        ASGI transport on the Core host intercepts exactly the calls that
        target Core and leaves every other request alone.
        """
        kwargs.setdefault("mounts", {CORE_TEST_URL: transport})
        return original_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", _asgi_init)
    monkeypatch.setattr(internal_client, "core_app_url", lambda: CORE_TEST_URL)

    class _Recorder:
        """Records the Core-bound requests that were actually made."""

        @property
        def calls(self) -> list:
            return calls

        @property
        def count(self) -> int:
            return len(calls)

        @property
        def methods(self) -> list:
            return [call["method"] for call in calls]

        @property
        def paths(self) -> list:
            return [call["path"] for call in calls]

        def last(self) -> dict:
            assert calls, "no Core-bound request was made"
            return calls[-1]

        def assert_only_actions(self, expected_count: int = 1) -> None:
            """Assert the Core-bound calls were exactly N POSTs to /actions.

            This pins the contract of the Detection -> Core action boundary:
            the method, the path and the number of calls.
            """
            assert len(calls) == expected_count, (
                f"expected {expected_count} Core call(s), got {len(calls)}: "
                f"{[(c['method'], c['path']) for c in calls]}"
            )
            for call in calls:
                assert call["method"] == "POST", (
                    f"expected POST, got {call['method']} for {call['path']}"
                )
                assert call["path"] == "/api/v1/internal/actions", (
                    f"expected the internal actions endpoint, got {call['path']}"
                )

    yield _Recorder()


def _all_route_modules():
    """Return the modules that declare DB dependencies."""
    from app import alerts as alerts_mod
    from app import auth as auth_mod
    from app import authz as authz_mod
    from app import detection as detection_mod
    from app import devices as devices_mod
    from app import iam as iam_mod
    from app import internal_actions as internal_actions_mod
    from app import manager as manager_mod
    from app import ml as ml_mod

    return (
        auth_mod,
        iam_mod,
        detection_mod,
        devices_mod,
        internal_actions_mod,
        ml_mod,
        alerts_mod,
        authz_mod,
        manager_mod,
    )


@pytest.fixture()
def user(db) -> User:
    """An active user carrying the USER and SOC_ANALYST roles."""
    db.add_all(
        [
            Role(id="USER", name="User", name_vi="Người dùng"),
            Role(id="SOC_ANALYST", name="SOC Analyst", name_vi="Phân tích viên SOC"),
        ]
    )
    u = User(
        username="alice",
        password_hash="argon2-hash",
        email="alice@example.com",
        status="active",
    )
    db.add(u)
    db.flush()
    db.add_all(
        [
            UserRole(user_id=u.id, role_id="USER"),
            UserRole(user_id=u.id, role_id="SOC_ANALYST"),
        ]
    )
    db.commit()
    db.refresh(u)
    return u


@pytest.fixture()
def policy(db) -> Policy:
    """The canonical v1.0 policy, trimmed to a single rule."""
    p = Policy(
        version="v1.0",
        name="Default Detection Policy",
        rules=[
            {
                "name": "unusual_hour",
                "field": "hour_of_day",
                "operator": "not_between",
                "value": [7, 22],
                "weight": 0.30,
                "score": 0.80,
                "enabled": True,
            }
        ],
        config={
            "weights": {"rule": 0.4, "ml": 0.6},
            "thresholds": {"low": 0.25, "medium": 0.5, "high": 0.75},
        },
        is_active=True,
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


# ---------------------------------------------------------------------------
# Internal-service authentication
# ---------------------------------------------------------------------------

import os

#: Must be at least 32 characters to pass ``get_internal_secret`` validation.
TEST_INTERNAL_SECRET = "test-internal-secret-at-least-32-characters-long"

#: Header dict used by tests that exercise internal endpoints.
#: Must match the value that ``_set_internal_secret`` writes into the environment.
SECRET_HEADER = {"X-Internal-Secret": TEST_INTERNAL_SECRET}


@pytest.fixture(autouse=True, scope="session")
def _set_internal_secret():
    """Ensure ``INTERNAL_SECRET`` is set for every test session.

    Uses session scope so the environment variable is set once before any test
    runs and cleaned up after the session ends.  Individual test functions do
    not need to manage the variable.
    """
    os.environ.setdefault("INTERNAL_SECRET", TEST_INTERNAL_SECRET)
    yield
    os.environ.pop("INTERNAL_SECRET", None)
