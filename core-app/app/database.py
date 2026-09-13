"""SQLAlchemy engine and session factory helpers."""

from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.settings import Settings, get_settings


def create_database_engine(settings: Settings | None = None) -> Engine:
    active_settings = settings or get_settings()
    active_settings.validate_runtime_security()
    return create_engine(active_settings.database_url, pool_pre_ping=True)


def create_session_factory(settings: Settings | None = None) -> sessionmaker[Session]:
    return sessionmaker(bind=create_database_engine(settings), autoflush=False, expire_on_commit=False)


def get_db_session() -> Generator[Session, None, None]:
    """Dependency placeholder for a later router phase."""

    session = create_session_factory()()
    try:
        yield session
    finally:
        session.close()
