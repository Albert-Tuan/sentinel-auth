"""
Shared internal-service HTTP client.

The Detection context calls back into the Core context over the canonical
service boundary documented in
``docs/assignments/CONTRACT_CORE_DETECTION.md`` section C:

    POST /api/v1/internal/actions

Detection must NOT reach into the Core database directly.  ``login_attempts``
and ``alerts`` live in ``sentinel_detection``; the enforced state
(``users.detection_mfa_once``, ``users.status``, revoked ``sessions``) lives
in ``sentinel_core``.  When the monolith runs both contexts in one process
it is still tempting to shortcut the boundary with a second database
session - that would reintroduce exactly the cross-database coupling this
architecture is built to prevent, and it would break the moment Detection is
split into its own service.

This module is the single place where that call is made, so the timeout,
error handling and payload shape are defined once.

Error semantics (preserved from the previous in-module implementation)
----------------------------------------------------------------------
* A missing/unconfigured internal secret -> the action is NOT enforced and
  the failure is logged.
* A transport error (Core unreachable) -> the action is NOT enforced and
  the failure is logged.
* A rejected action (HTTP >= 400) -> the action is NOT enforced and the
  rejection is logged.
* A successful call -> the action IS enforced.

In every failure case the caller is told the action was not enforced, so it
can record that fact instead of pretending the enforcement happened.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any, Dict, Optional
from uuid import UUID

import httpx

from app.internal_auth import get_internal_secret, InternalAuthConfigurationError

logger = logging.getLogger(__name__)

#: Callback into Core App to enforce a protective action. Kept short: the
#: scoring endpoint must not be held open waiting on an auth service.
ACTION_ENFORCE_TIMEOUT_SECONDS = 3.0


class ActionOutcome:
    """The full result of a Core action call.

    ``response`` holds the decoded Core body when the action WAS enforced.
    ``error`` describes why it was not, and is ``None`` on success.  The
    boolean ``enforced`` is the single question callers usually need.
    """

    def __init__(
        self,
        response: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
        status_code: Optional[int] = None,
    ):
        self.response = response
        self.error = error
        self.status_code = status_code

    @property
    def enforced(self) -> bool:
        """True when Core accepted and applied the action."""
        return self.response is not None

    def __bool__(self) -> bool:
        return self.enforced


def core_app_url() -> str:
    """Base URL of the Core App, without trailing slash.

    The Detection Engine calls back into Core App to enforce protective
    actions; the address is not hardcoded so tests and deployments can
    point it elsewhere.
    """
    return os.getenv("CORE_APP_URL", "http://localhost:8000").rstrip("/")


async def enforce_action_in_core_detailed(
    action: str,
    target_user_id: UUID,
    reason: str,
    *,
    idempotency_key: Optional[str] = None,
    alert_id: Optional[UUID] = None,
    severity: Optional[str] = None,
    detected_at: Optional[datetime] = None,
    timeout: float = ACTION_ENFORCE_TIMEOUT_SECONDS,
) -> ActionOutcome:
    """Ask the Core context to enforce a protective action.

    Returns an :class:`ActionOutcome` that says whether the action was
    enforced and, when it was not, why.

    The idempotency key is what makes a retry safe: Core records it in its
    audit log, so re-delivering the same key reports ``already_applied``
    instead of executing the action twice.
    """
    payload: Dict[str, Any] = {
        "action": action,
        "target_user_id": str(target_user_id),
        "reason": reason,
    }
    if idempotency_key is not None:
        payload["idempotency_key"] = idempotency_key
    if alert_id is not None:
        payload["alert_id"] = str(alert_id)
    if severity is not None:
        payload["severity"] = severity
    if detected_at is not None:
        payload["detected_at"] = detected_at.isoformat()

    try:
        headers = {"X-Internal-Secret": get_internal_secret()}
    except InternalAuthConfigurationError:
        logger.warning(
            "internal secret not configured, action %s not enforced for user %s",
            action, target_user_id,
        )
        return ActionOutcome(error="internal_auth_not_configured")

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                f"{core_app_url()}/api/v1/internal/actions",
                json=payload,
                headers=headers,
            )
    except httpx.HTTPError as exc:
        logger.warning(
            "core-app unreachable, action %s not enforced for user %s: %s",
            action, target_user_id, exc.__class__.__name__,
        )
        return ActionOutcome(error=f"core_unreachable:{exc.__class__.__name__}")

    if response.status_code >= 400:
        logger.warning(
            "core-app rejected action %s for user %s: HTTP %s",
            action, target_user_id, response.status_code,
        )
        return ActionOutcome(
            error=f"core_http_{response.status_code}",
            status_code=response.status_code,
        )

    try:
        body = response.json()
    except ValueError:
        body = {}

    if not isinstance(body, dict):
        body = {}

    logger.info("enforced %s in core-app for user %s", action, target_user_id)
    return ActionOutcome(response=body, status_code=response.status_code)


async def enforce_action_in_core(
    action: str,
    target_user_id: UUID,
    reason: str,
    *,
    idempotency_key: Optional[str] = None,
    alert_id: Optional[UUID] = None,
    severity: Optional[str] = None,
    detected_at: Optional[datetime] = None,
    timeout: float = ACTION_ENFORCE_TIMEOUT_SECONDS,
) -> Optional[Dict[str, Any]]:
    """Ask the Core context to enforce a protective action.

    Returns the decoded Core response on success, or ``None`` when the
    action was not enforced (secret missing, Core unreachable, or Core
    rejected the request).
    """
    outcome = await enforce_action_in_core_detailed(
        action,
        target_user_id,
        reason,
        idempotency_key=idempotency_key,
        alert_id=alert_id,
        severity=severity,
        detected_at=detected_at,
        timeout=timeout,
    )
    return outcome.response
