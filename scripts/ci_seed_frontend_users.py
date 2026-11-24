#!/usr/bin/env python
"""Sentinel Auth — seed the frontend real-HTTP integration fixtures.

The frontend's integration suite (``frontend/src/test/integration``) talks to
a **live** FastAPI backend over real HTTP.  It therefore needs real user
accounts with real roles:

======================  ===================================  ================
User                    Roles                                MFA
======================  ===================================  ================
``m12analyst``          ``USER``, ``SOC_ANALYST``             no
``m12admin``            ``USER``, ``SECURITY_ADMIN``          yes (persistent)
``m12manager``          ``USER``, ``SECURITY_MANAGER``        no
``m12plain``            ``USER``                             no
======================  ===================================  ================

``m12admin`` carries ``admin_mfa_required`` so the MFA handshake
(challenge → OTP → verify) can be exercised end to end.

The script is **idempotent**: it creates the accounts when they are missing
and resets their password, roles and MFA flags when they already exist.  That
makes it safe to re-run against the same database.

Usage::

    CORE_DATABASE_URL=postgresql://... python scripts/ci_seed_frontend_users.py

Passwords come from the environment so that no credential is ever written to
the repository:

``M12_USER_PASSWORD``
    Password of ``m12analyst``.
``M12_ADMIN_PASSWORD``
    Password of ``m12admin``.
``M12_MANAGER_PASSWORD``
    Password of ``m12manager``.
``M12_PLAIN_PASSWORD``
    Password of ``m12plain``.

Every password that is not supplied is generated randomly and printed once —
never stored in Git.
"""
from __future__ import annotations

import os
import secrets
import sys
from pathlib import Path
from typing import Dict, List

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

#: The fixtures the frontend integration suite expects.  The username and the
#: role set are part of the contract; only the passwords are configurable.
FIXTURES: List[Dict[str, object]] = [
    {
        "username": "m12analyst",
        "email": "m12analyst@example.com",
        "roles": ("USER", "SOC_ANALYST"),
        "admin_mfa_required": False,
        "password_env": "M12_USER_PASSWORD",
    },
    {
        "username": "m12admin",
        "email": "m12admin@example.com",
        "roles": ("USER", "SECURITY_ADMIN"),
        "admin_mfa_required": True,
        "password_env": "M12_ADMIN_PASSWORD",
    },
    {
        "username": "m12manager",
        "email": "m12manager@example.com",
        "roles": ("USER", "SECURITY_MANAGER"),
        "admin_mfa_required": False,
        "password_env": "M12_MANAGER_PASSWORD",
    },
    {
        "username": "m12plain",
        "email": "m12plain@example.com",
        "roles": ("USER",),
        "admin_mfa_required": False,
        "password_env": "M12_PLAIN_PASSWORD",
    },
]


def resolve_passwords() -> Dict[str, str]:
    """Return the password of every fixture.

    A password that is not supplied through the environment is generated.
    The generated value is printed once so the caller can use it; it is never
    written to a file.
    """
    resolved: Dict[str, str] = {}
    generated: List[str] = []

    for fixture in FIXTURES:
        env_name = str(fixture["password_env"])
        username = str(fixture["username"])
        value = os.environ.get(env_name, "").strip()
        if not value:
            value = secrets.token_urlsafe(18)
            generated.append(username)
        resolved[username] = value

    if generated:
        print(
            "[seed-m12] generated password(s) for: " + ", ".join(generated),
            file=sys.stderr,
        )
        for username in generated:
            print(
                f"[seed-m12] {username} password: {resolved[username]}",
                file=sys.stderr,
            )

    return resolved


def main() -> int:
    from argon2 import PasswordHasher
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.db import resolve_database_url
    from app.models import User, UserRole

    database_url = os.environ.get("CORE_DATABASE_URL") or resolve_database_url("core")
    passwords = resolve_passwords()

    engine = create_engine(database_url, pool_pre_ping=True)
    session = sessionmaker(bind=engine)()
    hasher = PasswordHasher()

    try:
        for fixture in FIXTURES:
            username = str(fixture["username"])
            password = passwords[username]

            user = session.query(User).filter(User.username == username).first()
            if user is None:
                user = User(username=username)
                session.add(user)

            user.email = str(fixture["email"])
            user.status = "active"
            user.password_hash = hasher.hash(password)
            user.admin_mfa_required = bool(fixture["admin_mfa_required"])
            user.detection_mfa_once = False
            user.failed_login_count = 0
            user.locked_at = None
            session.flush()

            wanted = set(str(role) for role in fixture["roles"])  # type: ignore[arg-type]
            current = {
                link.role_id
                for link in session.query(UserRole)
                .filter(UserRole.user_id == user.id)
                .all()
            }
            for role_id in sorted(wanted - current):
                session.add(UserRole(user_id=user.id, role_id=role_id))
            for role_id in sorted(current - wanted):
                link = (
                    session.query(UserRole)
                    .filter(UserRole.user_id == user.id, UserRole.role_id == role_id)
                    .one_or_none()
                )
                if link is not None:
                    session.delete(link)

            print(
                f"[seed-m12] {username}: roles={sorted(wanted)} "
                f"mfa={bool(fixture['admin_mfa_required'])}"
            )

        session.commit()
    except Exception as exc:  # noqa: BLE001 - the CI must fail loudly
        session.rollback()
        print(f"[seed-m12] ERROR: the fixtures could not be seeded: {exc}", file=sys.stderr)
        return 1
    finally:
        session.close()
        engine.dispose()

    print("[seed-m12] the frontend integration fixtures are seeded")
    return 0


if __name__ == "__main__":
    sys.exit(main())
