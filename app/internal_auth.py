"""
Centralised internal service authentication.

Single canonical source for reading and verifying the shared service-to-service
secret.  Replaces the four independent ``internal_secret()`` / ``verify_internal_secret()``
definitions that previously existed in ``app/auth.py``,
``app/detection.py``, ``app/internal_actions.py``, and ``app/ml.py``.

Design
~~~~~~

``get_internal_secret()`` raises ``InternalAuthConfigurationError`` when the
secret is absent, empty, equal to the known-insecure placeholder
``changeme-in-production``, or still carrying a template placeholder prefix
(``change-me``, ``changeme``, ``replace-me``, ``placeholder``, ``your-``,
``secret``, ``password``).  The last rule matters because the repository
ships a template value in ``.env.example``: a copy-paste of that file would
otherwise give the whole deployment a publicly known service secret.
``scripts/deploy_local.sh`` applies the same rule, so the application and
the deployment script agree on what a usable secret is.  Callers that make
**outbound** service-to-service calls (``Auth → Detection``, ``Detection →
ML``, ``Detection → Core``) use ``get_internal_secret()`` to obtain the
header value.  If the secret is not configured they receive the exception
and can decide how to handle it (fail-open for pre-token check; degrade
gracefully for ML / action calls).

``verify_internal_secret()`` raises ``HTTPException(status_code=503)`` when
the secret is not configured and ``HTTPException(status_code=401)`` when the
header is absent or wrong.  This makes the fail-open / fail-secure behaviour
explicit at the call site — the caller does not silently receive a fallback
value and send it over the wire.

``is_internal_auth_configured()`` returns a plain bool for use in health
endpoints that want to surface a configuration status without exposing the
secret value.
"""
from __future__ import annotations

import os
import secrets
from typing import Optional

from fastapi import HTTPException
from starlette import status as http_status

__all__ = [
    "InternalAuthConfigurationError",
    "get_internal_secret",
    "verify_internal_secret",
    "is_internal_auth_configured",
]

#: Known-insecure placeholder that must never be used in production.
_INSECURE_PLACEHOLDER = "changeme-in-production"

#: Prefixes of the placeholder values that ship with the repository or the
#: deployment tooling.  A secret that still carries one of them is a
#: copy-paste of a template, not a generated value, so the service must
#: refuse to start rather than run with a public secret.
#:
#: ``scripts/deploy_local.sh`` applies the same rule, so the application and
#: the deployment script agree on what a usable secret is.
_INSECURE_PLACEHOLDER_PREFIXES = (
    "change-me",
    "changeme",
    "change_me",
    "replace-me",
    "replaceme",
    "replace_me",
    "placeholder",
    "your-",
    "your_",
    "secret",
    "password",
)

#: Minimum acceptable secret length in characters.
_MIN_SECRET_LENGTH = 32


class InternalAuthConfigurationError(Exception):
    """Raised when ``INTERNAL_SECRET`` is absent, empty, or a known insecure value."""

    pass


# ---------------------------------------------------------------------------
# Configuration readers
# ---------------------------------------------------------------------------

def _read_secret() -> Optional[str]:
    """Return the raw value of ``INTERNAL_SECRET``, or None if not set."""
    return os.environ.get("INTERNAL_SECRET")


def get_internal_secret() -> str:
    """Return the validated shared secret.

    Raises
    ------
    InternalAuthConfigurationError
        If the environment variable is unset, empty, equal to the known
        insecure placeholder, or shorter than ``_MIN_SECRET_LENGTH``.
    """
    raw = _read_secret()

    if raw is None:
        raise InternalAuthConfigurationError(
            "INTERNAL_SECRET is not set"
        )

    value = raw.strip()

    if not value:
        raise InternalAuthConfigurationError(
            "INTERNAL_SECRET is empty"
        )

    if value == _INSECURE_PLACEHOLDER:
        raise InternalAuthConfigurationError(
            f"INTERNAL_SECRET is set to the known-insecure placeholder "
            f"{_INSECURE_PLACEHOLDER!r}"
        )

    for prefix in _INSECURE_PLACEHOLDER_PREFIXES:
        if value.lower().startswith(prefix):
            raise InternalAuthConfigurationError(
                "INTERNAL_SECRET still holds a template placeholder value "
                f"(it starts with {prefix!r}). Generate one with: "
                "python3 -c 'import secrets; print(secrets.token_urlsafe(32))'"
            )

    if len(value) < _MIN_SECRET_LENGTH:
        raise InternalAuthConfigurationError(
            f"INTERNAL_SECRET is only {len(value)} characters; "
            f"at least {_MIN_SECRET_LENGTH} are required"
        )

    return value


def is_internal_auth_configured() -> bool:
    """Return True when a valid ``INTERNAL_SECRET`` is configured.

    Use this in health/readiness endpoints to report configuration status
    without exposing the secret value.
    """
    try:
        get_internal_secret()
        return True
    except InternalAuthConfigurationError:
        return False


# ---------------------------------------------------------------------------
# Inbound verification
# ---------------------------------------------------------------------------

def verify_internal_secret(x_internal_secret: Optional[str]) -> None:
    """Verify an inbound ``X-Internal-Secret`` header.

    Raises
    ------
    HTTPException 503
        When ``INTERNAL_SECRET`` is not configured securely (the server operator
        has not set the environment variable or has left it as the placeholder).
    HTTPException 401
        When the header is absent or does not match the configured secret.
    """
    try:
        secret = get_internal_secret()
    except InternalAuthConfigurationError:
        raise HTTPException(
            status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Internal authentication is not configured",
        )

    if not secrets.compare_digest(x_internal_secret or "", secret):
        raise HTTPException(
            status_code=http_status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing X-Internal-Secret",
        )
