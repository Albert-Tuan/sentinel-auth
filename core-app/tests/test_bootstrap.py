from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.bootstrap import bootstrap_initial_security_admin
from app.core.passwords import verify_password
from app.core.settings import Settings, SettingsError
from app.models import Base, EnforcementAudit, Role, RoleCode, User, UserRole


def settings() -> Settings:
    return Settings(
        app_env="development",
        service_name="core-app",
        database_url="sqlite+pysqlite:///:memory:",
        redis_url="redis://localhost:6379/0",
        jwt_secret="local-test-secret",
        jwt_algorithm="HS256",
        jwt_issuer="sentinel-auth-core",
        jwt_audience="sentinel-auth-browser",
        access_token_ttl_minutes=15,
        refresh_token_ttl_days=7,
        smtp_host="mailpit",
        smtp_port=1025,
        smtp_from="no-reply@sentinel-auth.local",
        initial_security_admin_username="security-admin",
        initial_security_admin_email="security-admin@example.test",
        initial_security_admin_password="not-a-real-password",
    )


def seed_roles(session: Session) -> None:
    session.add_all([Role(code=role_code) for role_code in RoleCode])
    session.flush()


def test_bootstrap_creates_exactly_one_user_with_user_and_security_admin_roles(database_engine) -> None:
    engine = database_engine

    with Session(engine) as session, session.begin():
        seed_roles(session)
        user = bootstrap_initial_security_admin(session, settings())

        assert user is not None
        assert user.username == "security-admin"
        assert verify_password(user.password_hash, "not-a-real-password")
        assigned_codes = set(
            session.scalars(
                select(Role.code).join(UserRole, UserRole.role_id == Role.id).where(UserRole.user_id == user.id)
            )
        )
        assert assigned_codes == {RoleCode.USER, RoleCode.SECURITY_ADMIN}
        assert session.scalar(select(EnforcementAudit).where(EnforcementAudit.actor == "system:bootstrap")) is not None

    with Session(engine) as session, session.begin():
        assert bootstrap_initial_security_admin(session, settings()) is None
        assert session.scalar(select(User).where(User.username == "security-admin")) is not None


def test_bootstrap_rejects_incomplete_environment_on_an_empty_database(database_engine) -> None:
    engine = database_engine
    incomplete_settings = settings().__class__(
        **{**settings().__dict__, "initial_security_admin_password": None}
    )

    with Session(engine) as session, session.begin():
        seed_roles(session)
        with pytest.raises(SettingsError, match="INITIAL_SECURITY_ADMIN"):
            bootstrap_initial_security_admin(session, incomplete_settings)
