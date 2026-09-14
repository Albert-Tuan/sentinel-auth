"""Persisted core-app enum values."""

from __future__ import annotations

from enum import StrEnum


class RoleCode(StrEnum):
    USER = "USER"
    SECURITY_ADMIN = "SECURITY_ADMIN"
    SOC_ANALYST = "SOC_ANALYST"
    SECURITY_MANAGER = "SECURITY_MANAGER"


class UserStatus(StrEnum):
    ACTIVE = "ACTIVE"
    LOCKED = "LOCKED"
    DELETED = "DELETED"


class LoginOutcome(StrEnum):
    ALLOW = "ALLOW"
    MFA_REQUIRED = "MFA_REQUIRED"
    DENY = "DENY"


class PreAuthStatus(StrEnum):
    ACTIVE = "ACTIVE"
    VERIFIED = "VERIFIED"
    EXPIRED = "EXPIRED"
    INVALIDATED = "INVALIDATED"


class MfaChallengeStatus(StrEnum):
    ACTIVE = "ACTIVE"
    VERIFIED = "VERIFIED"
    EXPIRED = "EXPIRED"
    LOCKED = "LOCKED"
    INVALIDATED = "INVALIDATED"


class OutboxStatus(StrEnum):
    PENDING = "PENDING"
    PUBLISHED = "PUBLISHED"
    DEAD_LETTER = "DEAD_LETTER"


class EnforcementAction(StrEnum):
    REQUIRE_MFA = "REQUIRE_MFA"
    REVOKE_SESSIONS = "REVOKE_SESSIONS"
    LOCK_USER = "LOCK_USER"
    RATE_LIMIT_IP = "RATE_LIMIT_IP"


class EnforcementResult(StrEnum):
    APPLIED = "APPLIED"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    REJECTED = "REJECTED"
    DUPLICATE = "DUPLICATE"
