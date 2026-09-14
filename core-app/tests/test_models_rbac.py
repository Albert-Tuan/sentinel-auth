from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import Base, Role, RoleCode, User, UserRole


def test_user_role_associations_support_multi_role_rbac(database_engine) -> None:
    engine = database_engine

    with Session(engine) as session:
        user_role = Role(code=RoleCode.USER)
        analyst_role = Role(code=RoleCode.SOC_ANALYST)
        user = User(username="alice", email="alice@example.test", password_hash="argon2id-hash")
        session.add_all([user_role, analyst_role, user])
        session.flush()
        session.add_all(
            [
                UserRole(user_id=user.id, role_id=user_role.id),
                UserRole(user_id=user.id, role_id=analyst_role.id),
            ]
        )
        session.commit()
        session.refresh(user)

        assert {role.code for role in user.roles} == {RoleCode.USER, RoleCode.SOC_ANALYST}
        assert user.has_role(RoleCode.USER)
        assert user.has_role(RoleCode.SOC_ANALYST)
        assert not user.has_role(RoleCode.SECURITY_ADMIN)
