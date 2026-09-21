"""Guards for mutations that could remove the final active Security Administrator."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.models import Role, RoleCode, User, UserRole, UserStatus
from app.models.base import utc_now


# This lock is shared by every mutation that can reduce the active Security
# Administrator population. It makes the count-and-mutate sequence atomic on
# PostgreSQL without introducing a database trigger before phase-2 routes exist.
_LAST_ACTIVE_SECURITY_ADMIN_LOCK = 739187202


class UserNotFoundError(LookupError):
    """The target user does not exist."""


class SecurityAdminRoleNotAssignedError(LookupError):
    """The target user does not hold the Security Administrator role."""


class LastActiveSecurityAdministratorError(ValueError):
    """The requested mutation would leave no active Security Administrator."""


def lock_user(session: Session, user_id: UUID) -> User:
    """Lock a user unless that would lock the final active Security Administrator."""

    user = _locked_user(session, user_id)
    _ensure_active_security_admin_survives(session, user)
    user.status = UserStatus.LOCKED
    return user


def soft_delete_user(session: Session, user_id: UUID) -> User:
    """Soft-delete a user unless that would delete the final active Security Administrator."""

    user = _locked_user(session, user_id)
    _ensure_active_security_admin_survives(session, user)
    user.status = UserStatus.DELETED
    user.deleted_at = utc_now()
    return user


def remove_security_admin_role(session: Session, user_id: UUID) -> None:
    """Remove SECURITY_ADMIN unless it is the final role on an active administrator."""

    user = _locked_user(session, user_id)
    assignment = session.scalar(
        select(UserRole)
        .join(Role, UserRole.role_id == Role.id)
        .where(UserRole.user_id == user.id, Role.code == RoleCode.SECURITY_ADMIN)
        .with_for_update()
    )
    if assignment is None:
        raise SecurityAdminRoleNotAssignedError("Target user does not hold SECURITY_ADMIN")

    _ensure_active_security_admin_survives(session, user)
    session.delete(assignment)


def _locked_user(session: Session, user_id: UUID) -> User:
    _acquire_last_admin_lock(session)
    user = session.scalar(select(User).where(User.id == user_id).with_for_update())
    if user is None:
        raise UserNotFoundError(f"User {user_id} was not found")
    return user


def _ensure_active_security_admin_survives(session: Session, user: User) -> None:
    if user.status != UserStatus.ACTIVE or not _has_security_admin_role(session, user.id):
        return

    active_admin_count = session.scalar(
        select(func.count(User.id))
        .select_from(User)
        .join(UserRole, UserRole.user_id == User.id)
        .join(Role, Role.id == UserRole.role_id)
        .where(User.status == UserStatus.ACTIVE, Role.code == RoleCode.SECURITY_ADMIN)
    )
    if active_admin_count == 1:
        raise LastActiveSecurityAdministratorError(
            "Cannot remove the final ACTIVE user with SECURITY_ADMIN"
        )


def _has_security_admin_role(session: Session, user_id: UUID) -> bool:
    return session.scalar(
        select(UserRole.user_id)
        .join(Role, UserRole.role_id == Role.id)
        .where(UserRole.user_id == user_id, Role.code == RoleCode.SECURITY_ADMIN)
    ) is not None


def _acquire_last_admin_lock(session: Session) -> None:
    if session.bind is not None and session.bind.dialect.name == "postgresql":
        session.execute(text(f"SELECT pg_advisory_xact_lock({_LAST_ACTIVE_SECURITY_ADMIN_LOCK})"))
