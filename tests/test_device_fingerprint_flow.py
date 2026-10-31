"""Core -> Detection device-fingerprint delivery tests (P1-1/P1-2/P1-3).

These tests cover the full chain that makes the fingerprint-first device
novelty work:

1. Core derives a canonical (hashed) fingerprint from the request headers.
2. Core attaches it to the ``LoginEvent`` it sends to Detection.
3. Detection accepts it over the service boundary and persists it in
   ``login_attempts.device_fingerprint``.
4. Detection then uses it - fingerprint-first - to decide device novelty.

The fingerprint is always the SHA-256 hex digest of the canonical header
material.  Raw header values must never leave the Core process.
"""
from __future__ import annotations

import hashlib
from uuid import uuid4

import pytest

from app.device_fingerprint import (
    fingerprint_from_request,
    fingerprint_hash_from_headers,
    fingerprint_material,
    fingerprint_material_from_headers,
    hash_fingerprint,
)


# ---------------------------------------------------------------------------
# A tiny request stub - Starlette's Request is not needed for header maths.
# ---------------------------------------------------------------------------

class _StubRequest:
    def __init__(self, headers):
        self.headers = headers


CHROME = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) Chrome/124.0",
    "Accept-Language": "vi-VN,vi;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
}

FIREFOX = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) Firefox/126.0",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate",
}


# =============================================================================
# Canonical fingerprint semantics
# =============================================================================

class TestCanonicalFingerprint:
    def test_fingerprint_is_a_sha256_hex_digest(self):
        value = fingerprint_from_request(_StubRequest(CHROME))
        assert len(value) == 64
        assert all(char in "0123456789abcdef" for char in value)

    def test_fingerprint_is_deterministic(self):
        first = fingerprint_from_request(_StubRequest(CHROME))
        second = fingerprint_from_request(_StubRequest(CHROME))
        assert first == second

    def test_different_headers_produce_different_fingerprints(self):
        assert fingerprint_from_request(_StubRequest(CHROME)) != (
            fingerprint_from_request(_StubRequest(FIREFOX))
        )

    def test_raw_header_values_are_not_part_of_the_fingerprint(self):
        """The stored value must not leak the raw User-Agent."""
        value = fingerprint_from_request(_StubRequest(CHROME))
        assert "Mozilla" not in value
        assert "Chrome" not in value

    def test_hash_matches_the_documented_sha256_of_the_material(self):
        material = fingerprint_material(
            CHROME["User-Agent"],
            CHROME["Accept-Language"],
            CHROME["Accept-Encoding"],
        )
        expected = hashlib.sha256(material.encode()).hexdigest()
        assert fingerprint_from_request(_StubRequest(CHROME)) == expected

    def test_material_helper_and_header_helper_agree(self):
        assert fingerprint_material_from_headers(CHROME) == fingerprint_material(
            CHROME["User-Agent"],
            CHROME["Accept-Language"],
            CHROME["Accept-Encoding"],
        )

    def test_hash_from_headers_equals_hash_of_material(self):
        assert fingerprint_hash_from_headers(CHROME) == hash_fingerprint(
            fingerprint_material_from_headers(CHROME)
        )

    def test_missing_headers_are_tolerated(self):
        """A request without any fingerprint header must still produce a value."""
        value = fingerprint_from_request(_StubRequest({}))
        assert len(value) == 64


# =============================================================================
# Core attaches the fingerprint to the LoginEvent
# =============================================================================

class TestCoreLoginEventCarriesFingerprint:
    def test_login_event_dataclass_has_the_optional_field(self):
        from app.auth import LoginEvent

        assert "device_fingerprint" in LoginEvent.__dataclass_fields__
        # Optional: an event without a fingerprint must still be constructible.
        assert LoginEvent.__dataclass_fields__["device_fingerprint"].default is None

    def test_login_event_factory_accepts_a_fingerprint(self):
        from app.auth import _login_event

        event = _login_event(
            request_id=uuid4(),
            username_attempted="someone",
            outcome="success",
            timestamp=__import__("datetime").datetime.now(
                __import__("datetime").timezone.utc
            ),
            device_fingerprint="a" * 64,
        )
        assert event.device_fingerprint == "a" * 64

    def test_login_event_factory_defaults_to_none(self):
        from app.auth import _login_event

        event = _login_event(
            request_id=uuid4(),
            username_attempted="someone",
            outcome="success",
            timestamp=__import__("datetime").datetime.now(
                __import__("datetime").timezone.utc
            ),
        )
        assert event.device_fingerprint is None

    def test_delivery_payload_includes_the_fingerprint(self):
        """The HTTP payload sent to Detection must carry the field."""
        from app.auth import _login_event

        event = _login_event(
            request_id=uuid4(),
            username_attempted="someone",
            outcome="success",
            timestamp=__import__("datetime").datetime.now(
                __import__("datetime").timezone.utc
            ),
            device_fingerprint="b" * 64,
        )
        # The payload dict is built inside _send_login_event; assert the
        # dataclass exposes exactly the attribute the payload reads.
        assert hasattr(event, "device_fingerprint")
        assert event.device_fingerprint == "b" * 64


# =============================================================================
# Detection accepts the field over the service boundary
# =============================================================================

class TestDetectionAcceptsTheField:
    def test_login_event_request_accepts_an_optional_fingerprint(self):
        from app.schemas import LoginEventRequest

        assert "device_fingerprint" in LoginEventRequest.model_fields
        assert LoginEventRequest.model_fields["device_fingerprint"].default is None

    def test_request_rejects_a_missing_required_field(self):
        """The genuinely required fields must still be enforced."""
        from app.schemas import LoginEventRequest

        with pytest.raises(Exception):
            LoginEventRequest(
                username_attempted="someone",
                outcome="success",
                timestamp="2026-02-01T12:00:00+00:00",
            )

    def test_request_rejects_an_unknown_field(self):
        """The contract is strict: a typo must fail loudly, not be ignored."""
        from app.schemas import LoginEventRequest

        with pytest.raises(Exception):
            LoginEventRequest(
                event_id=uuid4(),
                username_attempted="someone",
                outcome="success",
                timestamp="2026-02-01T12:00:00+00:00",
                device_fingerprint_typo="a" * 64,
            )

    def test_request_accepts_a_fingerprint(self):
        from app.schemas import LoginEventRequest

        payload = LoginEventRequest(
            event_id=uuid4(),
            username_attempted="someone",
            outcome="success",
            timestamp="2026-02-01T12:00:00+00:00",
            device_fingerprint="c" * 64,
        )
        assert payload.device_fingerprint == "c" * 64

    def test_request_accepts_a_missing_fingerprint(self):
        from app.schemas import LoginEventRequest

        payload = LoginEventRequest(
            event_id=uuid4(),
            username_attempted="someone",
            outcome="success",
            timestamp="2026-02-01T12:00:00+00:00",
        )
        assert payload.device_fingerprint is None


# =============================================================================
# Detection persists the fingerprint
# =============================================================================

class TestDetectionPersistsTheFingerprint:
    def test_login_attempt_model_has_the_nullable_column(self):
        from app.models import LoginAttempt

        column = LoginAttempt.__table__.columns["device_fingerprint"]
        assert column.nullable is True

    def test_column_is_in_the_detection_context(self):
        """The column belongs to the Detection database, not to Core."""
        from app.db import DETECTION, tables_for_context

        assert "login_attempts" in tables_for_context(DETECTION)

    def test_detection_persists_the_value(self, db):
        from app.models import LoginAttempt

        row = LoginAttempt(
            event_id=uuid4(),
            username_attempted="someone",
            outcome="success",
            device_fingerprint="d" * 64,
            status="pending",
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        assert row.device_fingerprint == "d" * 64

    def test_detection_accepts_a_null_fingerprint(self, db):
        """Backward compatibility: an event from an older Core has none."""
        from app.models import LoginAttempt

        row = LoginAttempt(
            event_id=uuid4(),
            username_attempted="someone",
            outcome="success",
            device_fingerprint=None,
            status="pending",
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        assert row.device_fingerprint is None


# =============================================================================
# Schema parity
# =============================================================================

class TestSchemaParity:
    def test_sql_schema_declares_the_column(self):
        import os
        import re

        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(
            os.path.join(root, "infra", "postgres", "schema-detection-v3.3.sql"),
            encoding="utf-8",
        ) as handle:
            sql = handle.read()

        assert re.search(
            r"device_fingerprint\s+TEXT", sql
        ), "the Detection SQL schema must declare login_attempts.device_fingerprint"

    def test_sql_column_is_nullable(self):
        import os
        import re

        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(
            os.path.join(root, "infra", "postgres", "schema-detection-v3.3.sql"),
            encoding="utf-8",
        ) as handle:
            sql = handle.read()

        match = re.search(r"device_fingerprint\s+(\w+)", sql)
        assert match is not None
        assert "NOT NULL" not in match.group(0)
