"""Tests for the risk-gated login path and the Detection -> Core callback.

Covers:

* ``_pre_token_risk`` - the synchronous gate added to ``POST /auth/login``
  (phương án C). Must hold the token for high/critical verdicts and, just as
  importantly, **fail open** when the Detection Engine is unavailable.
* ``enforce_action_in_core`` - the asynchronous callback that revokes or
  challenges a session after a risky login has already been scored.
* ``rescore_failed_attempts`` - recovery of attempts orphaned by a crash.
"""
from __future__ import annotations

import httpx
import pytest

from app import auth as auth_mod
from app import detection as det_mod
from app.internal_auth import InternalAuthConfigurationError
from app.models import LoginAttempt, User


@pytest.fixture()
def no_gate(monkeypatch):
    """Disable the pre-token gate (the default in unit tests)."""
    monkeypatch.setenv("RUN_PRE_TOKEN_CHECK", "0")
    monkeypatch.setattr(auth_mod, "RUN_PRE_TOKEN_CHECK", "0", raising=False)


def _mock_post(monkeypatch, handler):
    """Replace httpx.AsyncClient with a stub whose post() calls ``handler``."""
    real_client = httpx.AsyncClient

    class _Stub:
        def __init__(self, *a, **kw):
            self._c = real_client(*a, **kw)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            await self._c.aclose()
            return False

        async def post(self, url, **kwargs):
            return handler(url, kwargs)

    monkeypatch.setattr(auth_mod.httpx, "AsyncClient", _Stub)


# =============================================================================
# _pre_token_risk - the gate
# =============================================================================

async def test_gate_holds_token_on_critical(monkeypatch):
    monkeypatch.setattr(auth_mod, "RUN_PRE_TOKEN_CHECK", "1")
    monkeypatch.setattr(auth_mod, "DETECTION_URL", "http://det")

    seen = {}

    def handler(url, kwargs):
        seen["url"] = url
        seen["json"] = kwargs.get("json")
        return httpx.Response(
            200, json={"risk_level": "critical", "decision": "block",
                       "require_mfa": True},
        )

    _mock_post(monkeypatch, handler)

    level = await auth_mod._pre_token_risk(
        User(id="u1", username="alice"), "1.2.3.4", "curl"
    )
    assert level == "critical"
    assert seen["url"].endswith("/api/v1/internal/pre-token-check")
    assert seen["json"]["username"] == "alice"
    assert seen["json"]["ip_address"] == "1.2.3.4"


async def test_gate_holds_token_on_high(monkeypatch):
    monkeypatch.setattr(auth_mod, "RUN_PRE_TOKEN_CHECK", "1")
    monkeypatch.setattr(auth_mod, "DETECTION_URL", "http://det")
    _mock_post(
        monkeypatch,
        lambda u, k: httpx.Response(
            200, json={"risk_level": "high", "decision": "challenge",
                       "require_mfa": True}
        ),
    )
    assert await auth_mod._pre_token_risk(User(id="u1", username="a"), "1.1.1.1", None) == "high"


async def test_gate_passes_through_low_risk(monkeypatch):
    monkeypatch.setattr(auth_mod, "RUN_PRE_TOKEN_CHECK", "1")
    monkeypatch.setattr(auth_mod, "DETECTION_URL", "http://det")
    _mock_post(
        monkeypatch,
        lambda u, k: httpx.Response(
            200, json={"risk_level": "low", "decision": "allow", "require_mfa": False}
        ),
    )
    assert await auth_mod._pre_token_risk(User(id="u1", username="a"), "1.1.1.1", None) is None


async def test_gate_passes_through_medium_even_if_require_mfa(monkeypatch):
    """Only high/critical are gated; medium must not add latency or MFA."""
    monkeypatch.setattr(auth_mod, "RUN_PRE_TOKEN_CHECK", "1")
    monkeypatch.setattr(auth_mod, "DETECTION_URL", "http://det")
    _mock_post(
        monkeypatch,
        lambda u, k: httpx.Response(
            200, json={"risk_level": "medium", "decision": "allow", "require_mfa": True}
        ),
    )
    assert await auth_mod._pre_token_risk(User(id="u1", username="a"), "1.1.1.1", None) is None


# --- fail-open paths: availability must beat strictness -------------------

async def test_gate_fails_open_on_connection_error(monkeypatch):
    monkeypatch.setattr(auth_mod, "RUN_PRE_TOKEN_CHECK", "1")
    monkeypatch.setattr(auth_mod, "DETECTION_URL", "http://det")

    def boom(url, kwargs):
        raise httpx.ConnectError("refused")

    _mock_post(monkeypatch, boom)
    assert await auth_mod._pre_token_risk(User(id="u1", username="a"), "1.1.1.1", None) is None


async def test_gate_fails_open_when_internal_secret_not_configured(monkeypatch):
    """When INTERNAL_SECRET is absent, _pre_token_risk must not send 'changeme-in-production'.

    It must return None (fail-open) and raise InternalAuthConfigurationError,
    which is caught by the existing except clause.
    """
    from app.internal_auth import InternalAuthConfigurationError

    monkeypatch.setattr(auth_mod, "RUN_PRE_TOKEN_CHECK", "1")
    monkeypatch.setattr(auth_mod, "DETECTION_URL", "http://det")
    monkeypatch.delenv("INTERNAL_SECRET", raising=False)

    # Patch get_internal_secret to raise, simulating the absent/invalid secret path.
    monkeypatch.setattr(
        auth_mod, "get_internal_secret",
        lambda: (_ for _ in ()).throw(
            InternalAuthConfigurationError("INTERNAL_SECRET is not set")
        ),
    )

    # No HTTP should be attempted at all.
    def boom(url, kwargs):
        raise AssertionError("HTTP must not be called when secret is absent")

    _mock_post(monkeypatch, boom)
    assert await auth_mod._pre_token_risk(User(id="u1", username="a"), "1.1.1.1", None) is None


async def test_gate_sends_correct_secret_header(monkeypatch):
    """The outbound request to Detection must use the configured secret, not a default."""
    monkeypatch.setattr(auth_mod, "RUN_PRE_TOKEN_CHECK", "1")
    monkeypatch.setattr(auth_mod, "DETECTION_URL", "http://det")

    seen_headers = {}

    def handler(url, kwargs):
        seen_headers.update(kwargs.get("headers", {}))
        return httpx.Response(
            200, json={"risk_level": "low", "decision": "allow", "require_mfa": False},
        )

    _mock_post(monkeypatch, handler)

    assert await auth_mod._pre_token_risk(User(id="u1", username="a"), "1.1.1.1", None) is None
    assert "X-Internal-Secret" in seen_headers
    assert seen_headers["X-Internal-Secret"] == "test-internal-secret-at-least-32-characters-long"


async def test_gate_fails_open_on_timeout(monkeypatch):
    monkeypatch.setattr(auth_mod, "RUN_PRE_TOKEN_CHECK", "1")
    monkeypatch.setattr(auth_mod, "DETECTION_URL", "http://det")

    def boom(url, kwargs):
        raise httpx.ReadTimeout("too slow")

    _mock_post(monkeypatch, boom)
    assert await auth_mod._pre_token_risk(User(id="u1", username="a"), "1.1.1.1", None) is None


async def test_gate_fails_open_on_http_error(monkeypatch):
    monkeypatch.setattr(auth_mod, "RUN_PRE_TOKEN_CHECK", "1")
    monkeypatch.setattr(auth_mod, "DETECTION_URL", "http://det")
    _mock_post(monkeypatch, lambda u, k: httpx.Response(500))
    assert await auth_mod._pre_token_risk(User(id="u1", username="a"), "1.1.1.1", None) is None


async def test_gate_fails_open_when_degraded(monkeypatch):
    monkeypatch.setattr(auth_mod, "RUN_PRE_TOKEN_CHECK", "1")
    monkeypatch.setattr(auth_mod, "DETECTION_URL", "http://det")
    _mock_post(
        monkeypatch,
        lambda u, k: httpx.Response(
            200,
            json={"risk_level": "unknown", "decision": "allow",
                  "require_mfa": True, "degraded": True, "reason": "scoring_error"},
        ),
    )
    assert await auth_mod._pre_token_risk(User(id="u1", username="a"), "1.1.1.1", None) is None


async def test_gate_fails_open_on_non_json(monkeypatch):
    monkeypatch.setattr(auth_mod, "RUN_PRE_TOKEN_CHECK", "1")
    monkeypatch.setattr(auth_mod, "DETECTION_URL", "http://det")
    _mock_post(monkeypatch, lambda u, k: httpx.Response(200, text="<html>502</html>"))
    assert await auth_mod._pre_token_risk(User(id="u1", username="a"), "1.1.1.1", None) is None


async def test_gate_disabled_by_env(monkeypatch):
    monkeypatch.setattr(auth_mod, "RUN_PRE_TOKEN_CHECK", "0")

    def explode(url, kwargs):  # must never be called
        raise AssertionError("gate should be disabled")

    _mock_post(monkeypatch, explode)
    assert await auth_mod._pre_token_risk(User(id="u1", username="a"), "1.1.1.1", None) is None


# =============================================================================
# enforce_action_in_core - the async callback (UC-DE-07)
# =============================================================================

def _mock_det_post(monkeypatch, handler):
    real_client = httpx.AsyncClient

    class _Stub:
        def __init__(self, *a, **kw):
            self._c = real_client(*a, **kw)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            await self._c.aclose()
            return False

        async def post(self, url, **kwargs):
            return handler(url, kwargs)

    monkeypatch.setattr(det_mod.httpx, "AsyncClient", _Stub)


def _attempt(db, user_id, status="processed", decision="block"):
    from datetime import datetime, timezone
    from uuid import uuid4

    a = LoginAttempt(
        event_id=uuid4(),
        user_id=user_id,
        username_attempted="alice",
        outcome="success",
        timestamp=datetime.now(timezone.utc),
        status=status,
        detection_decision=decision,
    )
    db.add(a)
    db.commit()
    db.refresh(a)
    return a


async def test_callback_sends_revoke_on_critical(monkeypatch, db, user):
    captured = {}

    def handler(url, kwargs):
        captured["url"] = url
        captured["json"] = kwargs.get("json")
        return httpx.Response(200, json={"status": "applied"})

    _mock_det_post(monkeypatch, handler)
    a = _attempt(db, user.id)

    ok = await det_mod.enforce_action_in_core(a, "critical", alert_id=None)
    assert ok is True
    assert captured["url"].endswith("/api/v1/internal/actions")
    body = captured["json"]
    assert body["action"] == "REVOKE_SESSIONS"
    assert body["target_user_id"] == str(user.id)
    assert body["severity"] == "critical"
    # Idempotency key must be stable per attempt so a retry is a no-op.
    assert body["idempotency_key"] == f"detection:{a.id}:REVOKE_SESSIONS"


async def test_callback_sends_require_mfa_on_high(monkeypatch, db, user):
    captured = {}

    def handler(url, kwargs):
        captured.update(kwargs.get("json"))
        return httpx.Response(200, json={"status": "applied"})

    _mock_det_post(monkeypatch, handler)
    a = _attempt(db, user.id)
    assert await det_mod.enforce_action_in_core(a, "high") is True
    assert captured["action"] == "REQUIRE_MFA"


@pytest.mark.parametrize("level", ["low", "medium"])
async def test_callback_is_silent_for_safe_levels(monkeypatch, db, user, level):
    def explode(url, kwargs):  # must never be called
        raise AssertionError("no action should be sent")

    _mock_det_post(monkeypatch, explode)
    a = _attempt(db, user.id)
    assert await det_mod.enforce_action_in_core(a, level) is False


async def test_callback_survives_core_app_being_down(monkeypatch, db, user):
    def boom(url, kwargs):
        raise httpx.ConnectError("refused")

    _mock_det_post(monkeypatch, boom)
    a = _attempt(db, user.id)
    # Must return False, not raise: a dead Core App must not fail scoring.
    assert await det_mod.enforce_action_in_core(a, "critical") is False


async def test_callback_treats_4xx_as_not_enforced(monkeypatch, db, user):
    _mock_det_post(monkeypatch, lambda u, k: httpx.Response(404, json={}))
    a = _attempt(db, user.id)
    assert await det_mod.enforce_action_in_core(a, "critical") is False


async def test_callback_skips_anonymous_attempt(monkeypatch, db):
    def explode(url, kwargs):
        raise AssertionError("no user, no action")

    _mock_det_post(monkeypatch, explode)
    a = _attempt(db, user_id=None)
    assert await det_mod.enforce_action_in_core(a, "critical") is False


# =============================================================================
# rescore_failed_attempts - recovery after a crash
# =============================================================================

async def test_rescore_recovers_failed_attempts(monkeypatch, db, user, policy):
    a = _attempt(db, user.id, status="failed")
    seen = []

    async def fake_process(db_, attempt, request_id):
        seen.append(attempt.id)
        return det_mod.DetectionResponse(
            rule_score=0.0, ml_score=None, combined_score=0.0,
            ml_status="unavailable", risk_level="low", decision="allow",
        )

    monkeypatch.setattr(det_mod, "process_attempt", fake_process)
    n = await det_mod.rescore_failed_attempts(db)
    assert n == 1
    assert seen == [a.id]
    db.expire_all()
    # The stub does not flip the status, so the row is still failed here;
    # the real process_attempt sets it to "processed".
    assert a.id is not None


async def test_rescore_is_a_noop_when_nothing_failed(monkeypatch, db, user, policy):
    _attempt(db, user.id, status="processed")

    async def explode(*a, **kw):
        raise AssertionError("nothing to rescore")

    monkeypatch.setattr(det_mod, "process_attempt", explode)
    assert await det_mod.rescore_failed_attempts(db) == 0


async def test_rescore_keeps_going_after_a_bad_row(monkeypatch, db, user, policy):
    bad = _attempt(db, user.id, status="failed")
    good = _attempt(db, user.id, status="failed")

    async def flaky(db_, attempt, request_id):
        if attempt.id == bad.id:
            raise RuntimeError("scoring exploded")
        return det_mod.DetectionResponse(
            rule_score=0.0, ml_score=None, combined_score=0.0,
            ml_status="unavailable", risk_level="low", decision="allow",
        )

    monkeypatch.setattr(det_mod, "process_attempt", flaky)
    # One good row is still recovered even though the first one blew up.
    assert await det_mod.rescore_failed_attempts(db) == 1
