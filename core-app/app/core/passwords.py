"""Argon2id password hashing helpers."""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.low_level import Type
from argon2.exceptions import InvalidHashError, VerificationError


_PASSWORD_HASHER = PasswordHasher(type=Type.ID)


def hash_password(password: str) -> str:
    """Return an Argon2id hash; callers must never log the input value."""

    return _PASSWORD_HASHER.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    """Verify a password without leaking verification exceptions to callers."""

    try:
        return _PASSWORD_HASHER.verify(password_hash, password)
    except (InvalidHashError, VerificationError):
        return False
