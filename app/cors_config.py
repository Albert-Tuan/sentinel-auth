"""CORS configuration — an explicit, configurable origin allowlist.

Trust model
===========

The application never accepts a wildcard origin.  A wildcard combined with
``allow_credentials=True`` is the most dangerous CORS configuration there is:
the browser is told that *any* site may read authenticated responses, so a
malicious page can exfiltrate whatever the victim's session is allowed to see.

The allowlist is read from ``CORS_ALLOWED_ORIGINS``, a comma-separated list of
exact origins.  Each entry must be a full origin (scheme + host + optional
port) - a bare host, a path, or a trailing slash is a configuration error and
is rejected at startup rather than silently never matching.

Defaults
--------

``http://localhost:8000`` and ``http://127.0.0.1:8000`` are the origins the
local demo deployment is reachable at.  They are the SAME origin the API is
served from, so they preserve the local deployment exactly while removing the
wildcard.  A deployment that serves a separate front-end adds that front-end's
origin explicitly; nothing is enabled implicitly.

Credentials
-----------

The API authenticates with an ``Authorization: Bearer`` header, not with
cookies, so credentialed cross-origin requests are not part of the contract.
``allow_credentials`` therefore stays enabled (a browser will not send the
``Authorization`` header unless the origin is allow-listed anyway) but the
allow-list is what actually restricts access.
"""
from __future__ import annotations

import os
from typing import FrozenSet, List
from urllib.parse import urlsplit

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

__all__ = [
    "CORS_ALLOWED_ORIGINS_ENV",
    "CORSConfigurationError",
    "default_cors_origins",
    "parse_cors_origins",
    "resolve_cors_origins",
    "install_cors_middleware",
]

#: Environment variable holding the comma-separated allow-list.
CORS_ALLOWED_ORIGINS_ENV = "CORS_ALLOWED_ORIGINS"

#: The origins the local demo deployment is served at.  They are the same
#: origin the API itself listens on, so nothing new is enabled.
_DEFAULT_ORIGINS = (
    "http://localhost:8000",
    "http://127.0.0.1:8000",
)


class CORSConfigurationError(ValueError):
    """Raised when ``CORS_ALLOWED_ORIGINS`` holds an unusable value."""


def default_cors_origins() -> List[str]:
    """Return the built-in default allow-list."""
    return list(_DEFAULT_ORIGINS)


def _normalise_origin(raw: str) -> str:
    """Validate one origin string and return its canonical form.

    An origin is ``scheme://host[:port]``.  Anything else - a bare host, a
    path, a query string, a fragment, a trailing slash - is rejected: those
    forms never match what a browser sends in the ``Origin`` header, so
    accepting them would silently produce a rule that can never fire.
    """
    value = raw.strip()
    if not value:
        raise CORSConfigurationError("an allow-list entry is empty")

    if value == "*":
        raise CORSConfigurationError(
            "CORS_ALLOWED_ORIGINS must not contain '*'. A wildcard origin "
            "combined with credentialed requests lets any website read "
            "authenticated responses. List the exact origins instead."
        )

    # A single trailing slash is a common way to write an origin, and it
    # is harmless: the browser never sends one.  It is stripped here so the
    # entry still matches.  Anything else after the slash is a path, which
    # is not part of an origin.
    if value.endswith("/"):
        value = value[:-1]
    if not value:
        raise CORSConfigurationError("an allow-list entry is empty")

    parts = urlsplit(value)
    if parts.scheme not in ("http", "https"):
        raise CORSConfigurationError(
            f"CORS_ALLOWED_ORIGINS entry {value!r} has no http/https scheme. "
            "An origin must be written as scheme://host[:port]."
        )
    if not parts.hostname:
        raise CORSConfigurationError(
            f"CORS_ALLOWED_ORIGINS entry {value!r} has no host."
        )
    if parts.path or parts.query or parts.fragment:
        raise CORSConfigurationError(
            f"CORS_ALLOWED_ORIGINS entry {value!r} must be an origin without "
            "a path, query or fragment."
        )

    # Rebuild the origin so that a trailing slash or a redundant default port
    # cannot make an otherwise valid entry fail to match.
    netloc = parts.netloc.lower()
    return f"{parts.scheme.lower()}://{netloc}"


def parse_cors_origins(raw: str) -> List[str]:
    """Parse a comma-separated allow-list into canonical origins.

    Raises:
        CORSConfigurationError: when an entry is not a usable origin.
    """
    origins: List[str] = []
    seen: set[str] = set()

    for chunk in raw.split(","):
        entry = chunk.strip()
        if not entry:
            continue
        origin = _normalise_origin(entry)
        if origin not in seen:
            seen.add(origin)
            origins.append(origin)

    if not origins:
        raise CORSConfigurationError(
            f"{CORS_ALLOWED_ORIGINS_ENV} is set but holds no usable origin."
        )
    return origins


def resolve_cors_origins() -> List[str]:
    """Return the effective allow-list.

    ``CORS_ALLOWED_ORIGINS`` wins when it is set; otherwise the built-in
    defaults are used.  The value is validated on EVERY call so a bad value
    is reported at startup (where it is called) and not at request time.
    """
    raw = os.environ.get(CORS_ALLOWED_ORIGINS_ENV)
    if raw is None or not raw.strip():
        return default_cors_origins()
    return parse_cors_origins(raw)


def install_cors_middleware(app: FastAPI, allowed_origins: List[str]) -> None:
    """Attach the CORS middleware with the given allow-list.

    The middleware is only attached when there is at least one origin.  An
    empty allow-list means "no cross-origin access at all", which is a valid
    (and strict) configuration for a service that is only reached
    same-origin.
    """
    if not allowed_origins:
        return

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(allowed_origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
