"""Regression tests for the final active Security Administrator invariant."""

from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Role, RoleCode, User, UserRole, UserStatus
from app.services.admin_guard import (
    LastActiveSecurityAdministratorError,
    lock_user,
    remove_security_admin_role,
    soft_delete_user,
)


Mutation = Callable[[Session, UUID], object]


def _seed_roles(session: Session) -> None:
    session.add_all([Role(code=role_code) for role_code in RoleCode])
    session.flush()


def _create_user(session: Session, username: str, role_codes: tuple[RoleCode, ...]) -> User:
    roles = {role.code: role for role in session.scalars(select(Role))}
    user = User(
        username=username,
        email=f"{username}@example.test",
        password_hash="argon2id-hash",
    )
    session.add(user)
    session.flush()
    session.add_all([UserRole(user_id=user.id, role_id=roles[role_code].id) for role_code in role_codes])
    session.flush()
    return user


def _has_security_admin_role(session: Session, user_id: UUID) -> bool:
    return session.scalar(
        select(UserRole.user_id)
        .join(Role, Role.id == UserRole.role_id)
        .where(UserRole.user_id == user_id, Role.code == RoleCode.SECURITY_ADMIN)
    ) is not None


@pytest.mark.parametrize(
    "mutation",
    [lock_user, soft_delete_user, remove_security_admin_role],
    ids=["lock", "soft-delete", "remove-security-admin-role"],
)
def test_blocks_every_mutation_of_the_final_active_security_admin(database_engine, mutation: Mutation) -> None:
    with Session(database_engine) as session, session.begin():
        _seed_roles(session)
        target = _create_user(session, "only-admin", (RoleCode.USER, RoleCode.SECURITY_ADMIN))
        # A non-active administrator does not satisfy the invariant.
        inactive_admin = _create_user(session, "locked-admin", (RoleCode.USER, RoleCode.SECURITY_ADMIN))
        inactive_admin.status = UserStatus.LOCKED

        with pytest.raises(LastActiveSecurityAdministratorError):
            mutation(session, target.id)

        session.refresh(target)
        assert target.status == UserStatus.ACTIVE
        assert target.deleted_at is None
        assert _has_security_admin_role(session, target.id)


@pytest.mark.parametrize(
    ("mutation", "expected_status", "security_admin_role_remains"),
    [
        (lock_user, UserStatus.LOCKED, True),
        (soft_delete_user, UserStatus.DELETED, True),
        (remove_security_admin_role, UserStatus.ACTIVE, False),
    ],
    ids=["lock", "soft-delete", "remove-security-admin-role"],
)
def test_allows_mutation_when_another_active_security_admin_exists(
    database_engine,
    mutation: Mutation,
    expected_status: UserStatus,
    security_admin_role_remains: bool,
) -> None:
    with Session(database_engine) as session, session.begin():
        _seed_roles(session)
        target = _create_user(session, "target-admin", (RoleCode.USER, RoleCode.SECURITY_ADMIN))
        survivor = _create_user(session, "surviving-admin", (RoleCode.USER, RoleCode.SECURITY_ADMIN))

        mutation(session, target.id)
        session.flush()
        session.refresh(target)

        assert target.status == expected_status
        assert (target.deleted_at is not None) is (expected_status == UserStatus.DELETED)
        assert _has_security_admin_role(session, target.id) is security_admin_role_remains
        assert survivor.status == UserStatus.ACTIVE
        assert _has_security_admin_role(session, survivor.id)
