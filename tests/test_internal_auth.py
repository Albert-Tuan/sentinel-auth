"""Unit tests for ``app.internal_auth`` — the canonical internal service
authentication module.

Tests observable behaviour only: what happens when ``INTERNAL_SECRET`` is
absent, empty, equal to the insecure placeholder, too short, or valid.

Inbound verification (503 on misconfiguration, 401 on bad header) and the use
of ``secrets.compare_digest`` for constant-time comparison are exercised here.
"""
from __future__ import annotations

import os
import secrets

import pytest
from fastapi import HTTPException

from app.internal_auth import (
    InternalAuthConfigurationError,
    get_internal_secret,
    is_internal_auth_configured,
    verify_internal_secret,
)

# ---------------------------------------------------------------------------
# A. INTERNAL_SECRET absent
# ---------------------------------------------------------------------------

def test_missing_internal_secret_raises_configuration_error(monkeypatch):
    """When ``INTERNAL_SECRET`` is not set at all, ``get_internal_secret`` raises."""
    monkeypatch.delenv("INTERNAL_SECRET", raising=False)
    with pytest.raises(InternalAuthConfigurationError) as exc_info:
        get_internal_secret()
    assert "not set" in str(exc_info.value)


def test_verify_missing_secret_returns_503(monkeypatch):
    """Inbound verification with no configured secret returns 503, not 401."""
    monkeypatch.delenv("INTERNAL_SECRET", raising=False)
    with pytest.raises(HTTPException) as exc_info:
        verify_internal_secret("any-value")
    assert exc_info.value.status_code == 503
    assert "not configured" in exc_info.value.detail


# ---------------------------------------------------------------------------
# B. INTERNAL_SECRET empty
# ---------------------------------------------------------------------------

def test_empty_internal_secret_raises_configuration_error(monkeypatch):
    """An empty string is not a valid secret."""
    monkeypatch.setenv("INTERNAL_SECRET", "")
    with pytest.raises(InternalAuthConfigurationError) as exc_info:
        get_internal_secret()
    assert "empty" in str(exc_info.value)


def test_whitespace_only_secret_raises_configuration_error(monkeypatch):
    """A whitespace-only string is not a valid secret."""
    monkeypatch.setenv("INTERNAL_SECRET", "   \t  ")
    with pytest.raises(InternalAuthConfigurationError) as exc_info:
        get_internal_secret()
    assert "empty" in str(exc_info.value)


def test_verify_empty_secret_returns_503(monkeypatch):
    """Inbound with unconfigured empty secret returns 503."""
    monkeypatch.setenv("INTERNAL_SECRET", "")
    with pytest.raises(HTTPException) as exc_info:
        verify_internal_secret("any-value")
    assert exc_info.value.status_code == 503


# ---------------------------------------------------------------------------
# C. INTERNAL_SECRET equal to insecure placeholder
# ---------------------------------------------------------------------------

def test_insecure_placeholder_raises_configuration_error(monkeypatch):
    """``changeme-in-production`` must be rejected unconditionally."""
    monkeypatch.setenv("INTERNAL_SECRET", "changeme-in-production")
    with pytest.raises(InternalAuthConfigurationError) as exc_info:
        get_internal_secret()
    assert "changeme-in-production" in str(exc_info.value)


def test_verify_insecure_placeholder_returns_503(monkeypatch):
    """Inbound verification when placeholder is configured returns 503."""
    monkeypatch.setenv("INTERNAL_SECRET", "changeme-in-production")
    with pytest.raises(HTTPException) as exc_info:
        verify_internal_secret("changeme-in-production")
    assert exc_info.value.status_code == 503
    assert "not configured" in exc_info.value.detail


# ---------------------------------------------------------------------------
# D. Too-short secret
# ---------------------------------------------------------------------------

def test_too_short_secret_raises_configuration_error(monkeypatch):
    """A secret shorter than 32 characters is rejected."""
    # Exactly 31 characters.
    monkeypatch.setenv("INTERNAL_SECRET", "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx")
    with pytest.raises(InternalAuthConfigurationError) as exc_info:
        get_internal_secret()
    assert "31" in str(exc_info.value) and "32" in str(exc_info.value)


def test_exactly_32_characters_is_accepted(monkeypatch):
    """A secret of exactly 32 characters passes."""
    monkeypatch.setenv("INTERNAL_SECRET", "a" * 32)
    assert get_internal_secret() == "a" * 32


# ---------------------------------------------------------------------------
# E. Valid configured secret
# ---------------------------------------------------------------------------

def test_valid_secret_returned_correctly(monkeypatch):
    """A valid, long-enough secret is returned unchanged."""
    monkeypatch.setenv("INTERNAL_SECRET", "this-is-a-valid-test-secret-at-least-32-chars")
    assert get_internal_secret() == "this-is-a-valid-test-secret-at-least-32-chars"


# ---------------------------------------------------------------------------
# F. verify — correct header
# ---------------------------------------------------------------------------

def test_verify_correct_header_succeeds(monkeypatch):
    """The correct secret in the header passes verification silently."""
    monkeypatch.setenv("INTERNAL_SECRET", "correct-secret-value-at-least-32-chars-long")
    # Should not raise.
    verify_internal_secret("correct-secret-value-at-least-32-chars-long")


# ---------------------------------------------------------------------------
# G. verify — wrong header
# ---------------------------------------------------------------------------

def test_verify_wrong_header_returns_401(monkeypatch):
    """A wrong secret returns 401, not 503."""
    monkeypatch.setenv("INTERNAL_SECRET", "correct-secret-value-at-least-32-chars-long")
    with pytest.raises(HTTPException) as exc_info:
        verify_internal_secret("wrong-secret-value-here")
    assert exc_info.value.status_code == 401
    assert "Invalid or missing" in exc_info.value.detail


# ---------------------------------------------------------------------------
# H. verify — missing header
# ---------------------------------------------------------------------------

def test_verify_missing_header_returns_401(monkeypatch):
    """An absent header returns 401."""
    monkeypatch.setenv("INTERNAL_SECRET", "correct-secret-value-at-least-32-chars-long")
    with pytest.raises(HTTPException) as exc_info:
        verify_internal_secret(None)
    assert exc_info.value.status_code == 401
    assert "Invalid or missing" in exc_info.value.detail


# ---------------------------------------------------------------------------
# I. is_internal_auth_configured helper
# ---------------------------------------------------------------------------

def test_is_configured_true_for_valid_secret(monkeypatch):
    """Returns True when a valid secret is configured."""
    monkeypatch.setenv("INTERNAL_SECRET", "valid-secret-at-least-32-characters-long")
    assert is_internal_auth_configured() is True


def test_is_configured_false_for_missing_secret(monkeypatch):
    """Returns False when the secret is absent."""
    monkeypatch.delenv("INTERNAL_SECRET", raising=False)
    assert is_internal_auth_configured() is False


def test_is_configured_false_for_placeholder(monkeypatch):
    """Returns False when the placeholder is set."""
    monkeypatch.setenv("INTERNAL_SECRET", "changeme-in-production")
    assert is_internal_auth_configured() is False


# ---------------------------------------------------------------------------
# Constant-time comparison
# ---------------------------------------------------------------------------

def test_constant_time_comparison_is_called(monkeypatch):
    """``secrets.compare_digest`` is called during verification.

    Patches ``get_internal_secret`` with a known test value, then patches
    ``secrets.compare_digest`` to capture its arguments.  Verifies both the
    correct-secret path (no exception) and the wrong-secret path (401) call
    ``compare_digest`` with the expected values.
    """
    from app.internal_auth import verify_internal_secret, InternalAuthConfigurationError
    import app.internal_auth as ia

    test_secret = "a" * 32
    monkeypatch.setenv("INTERNAL_SECRET", test_secret)

    # Replace get_internal_secret so it returns the known test value.
    # This avoids the reload trick — the patched function is called at call time.
    monkeypatch.setattr(ia, "get_internal_secret", lambda: test_secret)

    call_args = {}
    original_compare = ia.secrets.compare_digest

    def _spy(a, b):
        call_args["a"] = a
        call_args["b"] = b
        return original_compare(a, b)

    monkeypatch.setattr(ia.secrets, "compare_digest", _spy)

    # Correct secret — compare_digest is called; no exception.
    verify_internal_secret(test_secret)
    assert call_args["a"] == test_secret
    assert call_args["b"] == test_secret

    call_args.clear()

    # Wrong secret — compare_digest is called with both values; 401 raised.
    try:
        verify_internal_secret("wrong-secret-value-here")
    except ia.HTTPException as exc:
        assert exc.status_code == 401

    assert call_args["a"] == "wrong-secret-value-here"
    assert call_args["b"] == test_secret
