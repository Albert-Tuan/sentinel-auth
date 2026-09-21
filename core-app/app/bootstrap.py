"""One-time, environment-configured first Security Administrator bootstrap."""

from __future__ import annotations

from uuid import uuid4

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.passwords import hash_password
from app.core.settings import Settings, get_settings
from app.database import create_database_engine
from app.models import EnforcementAudit, EnforcementResult, Role, RoleCode, User, UserRole


class BootstrapError(RuntimeError):
    """The initial administrator cannot be bootstrapped safely."""


def bootstrap_initial_security_admin(session: Session, settings: Settings) -> User | None:
    """Seed exactly one initial administrator when no user exists.

    PostgreSQL takes a transaction advisory lock so multiple startup replicas cannot
    seed more than one first account. The function is intentionally safe to call on
    every startup: once any user exists, it is a no-op.
    """

    if session.bind is not None and session.bind.dialect.name == "postgresql":
        session.execute(text("SELECT pg_advisory_xact_lock(739187201)"))

    if session.scalar(select(func.count()).select_from(User)):
        return None

    username, email, password = settings.bootstrap_credentials()
    roles = {
        role.code: role
        for role in session.scalars(select(Role).where(Role.code.in_([RoleCode.USER, RoleCode.SECURITY_ADMIN])))
    }
    missing_roles = {RoleCode.USER, RoleCode.SECURITY_ADMIN}.difference(roles)
    if missing_roles:
        raise BootstrapError(f"Required seeded roles are absent: {', '.join(sorted(missing_roles))}")

    user = User(id=uuid4(), username=username, email=email, password_hash=hash_password(password))
    session.add(user)
    session.flush()
    session.add_all(
        [
            UserRole(user_id=user.id, role_id=roles[RoleCode.USER].id),
            UserRole(user_id=user.id, role_id=roles[RoleCode.SECURITY_ADMIN].id),
        ]
    )
    session.add(
        EnforcementAudit(
            correlation_id=uuid4(),
            actor="system:bootstrap",
            action="BOOTSTRAP_SECURITY_ADMIN",
            resource_type="user",
            resource_id=str(user.id),
            reason="Initial Security Administrator seeded from environment on empty database",
            result_status=EnforcementResult.APPLIED,
            after_state={"status": "ACTIVE", "roles": [RoleCode.USER, RoleCode.SECURITY_ADMIN]},
        )
    )
    return user


def main() -> None:
    settings = get_settings()
    settings.validate_runtime_security()
    engine = create_database_engine(settings)
    with Session(engine) as session:
        with session.begin():
            created = bootstrap_initial_security_admin(session, settings)
    if created is not None:
        print("Initial Security Administrator bootstrapped.")


if __name__ == "__main__":
    main()
