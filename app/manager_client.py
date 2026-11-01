"""
Outbound internal HTTP client for Security Manager analytics.

The Manager facade lives in the ML/Analytics context.  It aggregates data
that belongs to the Core and Detection contexts, but it must not reach into
their databases: the three contexts are physically separate databases
(``sentinel_core``, ``sentinel_detection``, ``sentinel_ml``) and each one
owns its data.  Manager therefore reads ML directly (it owns ``sentinel_ml``)
and reaches Core and Detection over the canonical internal service boundary
with the ``X-Internal-Secret`` header.

Design document: ``docs/M9-MANAGER-ANALYTICS-DESIGN.md`` section 6.2.

This module is the single place where those outbound calls happen, so the
timeout, the failure mapping and the payload shape are defined once.  It
mirrors ``app/internal_client.py``, which plays the same role for the
Detection -> Core protective-action boundary.

Failure model
--------------
The client **never raises** for an upstream problem.  Every fetch returns a
``(payload, reason_code)`` pair:

* ``(dict, None)``     - the upstream answered with a usable body;
* ``(None, "code")``   - the upstream failed; ``code`` is one of the closed
  reason codes of design section 6.1.1.

That gives the facade exactly one degradation path to handle, and it keeps
the reason vocabulary closed: a raw exception message, an upstream URL or an
upstream response body never reaches the API response.

The closed reason-code vocabulary
----------------------------------

==========================  ============================================
``not_configured``          ``INTERNAL_SECRET`` is absent or insecure
``timeout``                 no answer within ``MANAGER_FETCH_TIMEOUT_SECONDS``
``unreachable``             the upstream could not be contacted
``http_<code>``             the upstream answered with HTTP >= 400
``invalid_payload``         2xx with a body that is not a usable JSON object
``database_error``          the ML read failed (raised by the caller, not here)
``internal_error``          an unexpected error inside the aggregation step
==========================  ============================================

``http_<code>`` is the only code with a variable suffix.  ``http_401`` in
particular means the Manager sent a secret the internal endpoint rejected -
an operator error that must stay visible instead of being swallowed.

Manager never retries: a retry would multiply load on an upstream that is
already struggling.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, Optional
from urllib.parse import urlencode

import httpx

from app.internal_auth import get_internal_secret, InternalAuthConfigurationError

logger = logging.getLogger(__name__)

#: Per-upstream-call timeout.  A module constant, not an environment
#: variable, matching ``ACTION_ENFORCE_TIMEOUT_SECONDS`` in
#: ``app/internal_client.py``.  A slow source must not serialise the others,
#: so the slowest source bounds the request latency at ~3 s.
MANAGER_FETCH_TIMEOUT_SECONDS = 3.0

#: Path of the Detection-owned analytics endpoint (Tuấn Anh).
DETECTION_ANALYTICS_PATH = "/api/v1/internal/analytics/detection"

#: Path of the Core-owned analytics endpoint (Sony).
CORE_ANALYTICS_PATH = "/api/v1/internal/analytics/core"


# =============================================================================
# Source names - these are the keys of the public ``sources`` map
# =============================================================================

SOURCE_CORE = "core"
SOURCE_DETECTION = "detection"
SOURCE_ML = "ml"


def detection_url() -> str:
    """Base URL of the Detection context, without trailing slash.

    Reuses the existing ``DETECTION_URL`` environment variable - the same one
    ``app/auth.py`` uses to deliver login events - so no new configuration
    is introduced.  In a monolith deployment this points at the single
    server (``http://localhost:8000``); in a split deployment it keeps
    pointing at the Detection service (``http://localhost:8001``).
    """
    return os.getenv("DETECTION_URL", "http://localhost:8001").rstrip("/")


def core_app_url() -> str:
    """Base URL of the Core context, without trailing slash.

    Reuses the existing ``CORE_APP_URL`` environment variable - the same one
    ``app/internal_client.py`` uses to enforce protective actions.
    """
    return os.getenv("CORE_APP_URL", "http://localhost:8000").rstrip("/")


# =============================================================================
# Reason codes (closed vocabulary - design section 6.1.1)
# =============================================================================

REASON_NOT_CONFIGURED = "not_configured"
REASON_TIMEOUT = "timeout"
REASON_UNREACHABLE = "unreachable"
REASON_INVALID_PAYLOAD = "invalid_payload"
REASON_DATABASE_ERROR = "database_error"
REASON_INTERNAL_ERROR = "internal_error"


def http_reason_code(status_code: int) -> str:
    """Return the ``http_<code>`` reason code for an upstream status."""
    return f"http_{status_code}"


# =============================================================================
# Result type
# =============================================================================

class SourceResult:
    """The outcome of one upstream fetch.

    ``payload`` holds the decoded body when the source is healthy, and
    ``reason`` describes why it is not.  Exactly one of the two is set.
    """

    __slots__ = ("payload", "reason")

    def __init__(
        self,
        payload: Optional[Dict[str, Any]] = None,
        reason: Optional[str] = None,
    ):
        self.payload = payload
        self.reason = reason

    @property
    def ok(self) -> bool:
        """True when the upstream answered with a usable body."""
        return self.payload is not None and self.reason is None

    def __bool__(self) -> bool:
        return self.ok

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        if self.ok:
            return "SourceResult(ok)"
        return f"SourceResult(reason={self.reason!r})"


def _failure(reason: str, source: str, detail: str = "") -> SourceResult:
    logger.warning("manager source %s unavailable: %s %s", source, reason, detail)
    return SourceResult(payload=None, reason=reason)


async def fetch_internal_json(
    url: str,
    params: Optional[Dict[str, Any]] = None,
    *,
    source: str,
    timeout: float = MANAGER_FETCH_TIMEOUT_SECONDS,
) -> SourceResult:
    """GET ``url`` with the internal secret and return a :class:`SourceResult`.

    Never raises for an upstream problem - every failure mode is mapped to
    one of the closed reason codes.
    """
    try:
        headers = {"X-Internal-Secret": get_internal_secret()}
    except InternalAuthConfigurationError:
        # The secret is absent or insecure.  The request is not attempted at
        # all, so no placeholder secret ever leaves the process.
        return _failure(REASON_NOT_CONFIGURED, source, "internal secret not configured")

    query = ""
    if params:
        clean = {k: v for k, v in params.items() if v is not None}
        if clean:
            query = "?" + urlencode(clean)

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(f"{url}{query}", headers=headers)
    except httpx.TimeoutException as exc:
        return _failure(REASON_TIMEOUT, source, exc.__class__.__name__)
    except httpx.ConnectError as exc:
        return _failure(REASON_UNREACHABLE, source, exc.__class__.__name__)
    except httpx.TransportError as exc:
        # Any other transport-level failure (DNS, TLS, protocol error).
        return _failure(REASON_UNREACHABLE, source, exc.__class__.__name__)
    except httpx.HTTPError as exc:  # pragma: no cover - defensive
        return _failure(REASON_UNREACHABLE, source, exc.__class__.__name__)

    if response.status_code >= 400:
        return _failure(
            http_reason_code(response.status_code),
            source,
            f"HTTP {response.status_code}",
        )

    try:
        body = response.json()
    except (ValueError, json.JSONDecodeError):
        return _failure(REASON_INVALID_PAYLOAD, source, "response is not JSON")

    if not isinstance(body, dict):
        return _failure(REASON_INVALID_PAYLOAD, source, "response is not a JSON object")

    return SourceResult(payload=body, reason=None)


async def fetch_detection_analytics(
    *,
    from_: str,
    to: str,
    bucket: Optional[str] = None,
    status: Optional[str] = None,
    risk_level: Optional[str] = None,
    timeout: float = MANAGER_FETCH_TIMEOUT_SECONDS,
) -> SourceResult:
    """Fetch the Detection-owned analytics aggregate."""
    return await fetch_internal_json(
        f"{detection_url()}{DETECTION_ANALYTICS_PATH}",
        {"from": from_, "to": to, "bucket": bucket, "status": status,
         "risk_level": risk_level},
        source=SOURCE_DETECTION,
        timeout=timeout,
    )


async def fetch_core_analytics(
    *,
    from_: str,
    to: str,
    bucket: Optional[str] = None,
    timeout: float = MANAGER_FETCH_TIMEOUT_SECONDS,
) -> SourceResult:
    """Fetch the Core-owned analytics aggregate."""
    return await fetch_internal_json(
        f"{core_app_url()}{CORE_ANALYTICS_PATH}",
        {"from": from_, "to": to, "bucket": bucket},
        source=SOURCE_CORE,
        timeout=timeout,
    )


__all__ = [
    "MANAGER_FETCH_TIMEOUT_SECONDS",
    "DETECTION_ANALYTICS_PATH",
    "CORE_ANALYTICS_PATH",
    "SOURCE_CORE",
    "SOURCE_DETECTION",
    "SOURCE_ML",
    "REASON_NOT_CONFIGURED",
    "REASON_TIMEOUT",
    "REASON_UNREACHABLE",
    "REASON_INVALID_PAYLOAD",
    "REASON_DATABASE_ERROR",
    "REASON_INTERNAL_ERROR",
    "SourceResult",
    "detection_url",
    "core_app_url",
    "http_reason_code",
    "fetch_internal_json",
    "fetch_detection_analytics",
    "fetch_core_analytics",
]
