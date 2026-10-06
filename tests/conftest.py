"""Test fixtures backed by a real (SQLite) database.

The models declare ``UUID``/``INET`` with a TEXT variant (see
``app/models.py``), so the very same metadata can be created on SQLite.
That lets the tests exercise real SQLAlchemy behaviour - constraints,
cascades, relationships - instead of hand-written mocks.
"""
from __future__ import annotations

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
def client(db):
    """A TestClient whose ``get_db`` dependency returns the SQLite session."""
    from fastapi.testclient import TestClient

    from app.main import app

    from app import alerts as alerts_mod
    from app import auth as auth_mod
    from app import detection as detection_mod
    from app import devices as devices_mod
    from app import internal_actions as internal_actions_mod

    from app import authz as authz_mod

    override = _override_get_db(db)
    # Only the modules that actually import get_db need an override entry
    override_targets = [
        auth_mod,
        detection_mod,
        alerts_mod,
        devices_mod,
        internal_actions_mod,
        authz_mod,
    ]
    app.dependency_overrides = {
        module.get_db: override
        for module in override_targets
        if hasattr(module, "get_db")
    }
    try:
        with TestClient(app) as c:
            yield c
    finally:
        app.dependency_overrides = {}


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
