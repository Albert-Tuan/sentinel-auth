"""Canonical device-fingerprint helpers (pure, no DB, no routers).

This module is the single source of truth for the project's device
fingerprint semantics.  It was extracted from ``app/devices.py`` so that the
Core login flow can attach a fingerprint to the ``LoginEvent`` it sends to
Detection **without** importing ``app.devices`` and creating a circular
import (``devices`` already imports ``app.auth`` for the trusted-device
approval flow).

Semantics (unchanged, deliberately lightweight)
------------------------------------------------
* The fingerprint material is derived from non-invasive request headers only:
  ``User-Agent``, ``Accept-Language`` and ``Accept-Encoding``.  There is no
  canvas/WebGL/audio fingerprinting and no tracking of individuals.
* The material is combined into a single string and **hashed** with SHA-256
  before it is stored or transmitted.  Raw header values never leave the
  process, so the hashed representation is safe to persist in the Core
  database (``user_trusted_devices.device_fingerprint``) and to send to the
  Detection Engine as the ``device_fingerprint`` field of a ``LoginEvent``.

Because the same helper is used on both sides of the Core -> Detection
boundary, Detection can compare the fingerprint of a login attempt against
the fingerprints of the user's prior attempts to decide device novelty
(fingerprint-first, with a User-Agent proxy fallback).
"""
from __future__ import annotations

import hashlib
from typing import Mapping, Optional

__all__ = [
    "fingerprint_material",
    "fingerprint_material_from_headers",
    "hash_fingerprint",
    "fingerprint_from_headers",
    "fingerprint_hash_from_headers",
    "generate_device_fingerprint",
    "fingerprint_from_request",
]


def _get(headers: Mapping[str, str], name: str) -> str:
    """Read a header from a mapping, tolerating a case-insensitive lookup."""
    try:
        value = headers.get(name, "")
    except AttributeError:
        return ""
    return value or ""


def fingerprint_material(
    user_agent: Optional[str] = None,
    accept_language: Optional[str] = None,
    accept_encoding: Optional[str] = None,
) -> str:
    """Return the raw fingerprint material for the given header values.

    The material is the concatenation ``user_agent|accept_language|
    accept_encoding``.  It is NOT a secret and must be hashed before it is
    persisted or transmitted.
    """
    return f"{user_agent or ''}|{accept_language or ''}|{accept_encoding or ''}"


def fingerprint_material_from_headers(headers: Mapping[str, str]) -> str:
    """Return the raw fingerprint material for a header mapping."""
    return fingerprint_material(
        _get(headers, "User-Agent"),
        _get(headers, "Accept-Language"),
        _get(headers, "Accept-Encoding"),
    )


def hash_fingerprint(fingerprint: str) -> str:
    """Return the SHA-256 hex digest of ``fingerprint``.

    This is the canonical *stored / transmitted* representation of a device
    fingerprint.
    """
    return hashlib.sha256(fingerprint.encode()).hexdigest()


def fingerprint_from_headers(
    user_agent: Optional[str] = None,
    accept_language: Optional[str] = None,
    accept_encoding: Optional[str] = None,
) -> str:
    """Return the hashed fingerprint for the given header values."""
    return hash_fingerprint(
        fingerprint_material(user_agent, accept_language, accept_encoding)
    )


def fingerprint_hash_from_headers(headers: Mapping[str, str]) -> str:
    """Return the hashed fingerprint for a header mapping."""
    return hash_fingerprint(fingerprint_material_from_headers(headers))


def generate_device_fingerprint(request) -> str:
    """Derive the raw fingerprint material from a request's headers.

    Kept for backward compatibility with the historical
    ``app.devices.generate_device_fingerprint`` helper: the returned value is
    the *material*, not the hash.
    """
    headers = getattr(request, "headers", {}) or {}
    return fingerprint_material_from_headers(headers)


def fingerprint_from_request(request) -> str:
    """Return the hashed device fingerprint of a request.

    This is the value Core attaches to a ``LoginEvent`` and the value
    Detection stores in ``login_attempts.device_fingerprint``.
    """
    headers = getattr(request, "headers", {}) or {}
    return fingerprint_hash_from_headers(headers)
