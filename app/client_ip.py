"""Canonical client-IP resolver and proxy-trust configuration validator.

Trust model
===========

All application code derives the client IP from ``request.client.host``
(provided by the ASGI server).  The ASGI server is responsible for
interpreting ``X-Forwarded-For`` and ``X-Forwarded-Proto`` and populating
``scope["client"]`` accordingly — only for connections whose peer address is
on the trusted-proxy allowlist (``FORWARDED_ALLOW_IPS``).

Application code does NOT parse forwarding headers directly.

This design means the application is correct by construction: there is no
second XFF parser that could disagree with the ASGI server's interpretation.

Uvicorn settings
===============

- ``--proxy-headers``: enables ``ProxyHeadersMiddleware`` (default: True).
- ``FORWARDED_ALLOW_IPS``: comma-separated list of trusted IP addresses or CIDR
  blocks that are allowed to supply forwarding information.

  Safe defaults (Uvicorn's built-in defaults when the env var is absent):
  - ``127.0.0.1`` and ``::1`` (loopback only)

  For a deployment with a local nginx/load-balancer:
  - ``FORWARDED_ALLOW_IPS=<proxy-ip>``
  - e.g. ``FORWARDED_ALLOW_IPS=10.10.0.5``

  ``FORWARDED_ALLOW_IPS=*`` is rejected at startup — it would allow any
  remote client to forge forwarding headers.
"""

from __future__ import annotations

import ipaddress
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import Request


class ProxyTrustConfigurationError(ValueError):
    """Raised when ``FORWARDED_ALLOW_IPS`` is explicitly set to ``*``."""


def validate_proxy_trust_config() -> None:
    """Validate ``FORWARDED_ALLOW_IPS`` at application startup.

    Raises
    ------
    ProxyTrustConfigurationError
        If ``FORWARDED_ALLOW_IPS`` is set to ``*``, which would allow any
        remote client to forge forwarding headers and bypass IP-based controls.

    Notes
    -----
    Uvicorn's ``ProxyHeadersMiddleware`` is the single authority for parsing
    ``X-Forwarded-For``.  This validator provides defence-in-depth: an explicit
    wildcard in the environment variable cannot be missed by operators.
    """
    raw = os.environ.get("FORWARDED_ALLOW_IPS", "")

    # Normalise: absent or whitespace-only means "use Uvicorn defaults"
    # (127.0.0.1 and ::1) which are safe.
    stripped = raw.strip()
    if not stripped:
        return

    # Explicit wildcard — never acceptable in Sentinel Auth deployments.
    if stripped == "*" or stripped == '["*"]':
        raise ProxyTrustConfigurationError(
            "FORWARDED_ALLOW_IPS='*' is forbidden: "
            "any remote client could forge X-Forwarded-For headers and bypass "
            "IP-based controls (rate limiting, MFA IP-binding, alert audit). "
            "Set FORWARDED_ALLOW_IPS to the IP address(es) or CIDR block(s) "
            "of your trusted reverse proxy, e.g. FORWARDED_ALLOW_IPS=10.10.0.5"
        )

    # Validate individual tokens (IP address or CIDR notation).
    for token in stripped.split(","):
        token = token.strip()
        if not token:
            continue
        try:
            # Accept IPv4/IPv6 addresses or CIDR networks.
            ipaddress.ip_address(token)  # single host
        except ValueError:
            try:
                ipaddress.ip_network(token, strict=False)  # CIDR block
            except ValueError:
                raise ProxyTrustConfigurationError(
                    f"FORWARDED_ALLOW_IPS contains an invalid value: {token!r}. "
                    f"Expected an IP address (e.g. 127.0.0.1) or CIDR block "
                    f"(e.g. 10.10.0.0/24)."
                ) from None


def get_client_ip(request: "Request") -> str:
    """Return the client's IP address as seen by the application.

    The value is ``request.client.host`` after the ASGI server has applied
    its trusted-proxy policy (Uvicorn's ``ProxyHeadersMiddleware``).

    The application does NOT read ``X-Forwarded-For`` directly.  There is
    exactly one authority for chain parsing: the ASGI server.  This guarantees
    that Sentinel Auth's view of the client IP is consistent with whatever
    trust boundary the operator has configured.

    Parameters
    ----------
    request
        The FastAPI/Starlette request object.

    Returns
    -------
    str
        The client IP address, or ``"unknown"`` if the ASGI server did not
        provide a client address (e.g. in unit tests with no socket).
        Valid IPv4 and IPv6 addresses are returned as strings.
    """
    if request.client is None:
        return "unknown"
    return request.client.host
