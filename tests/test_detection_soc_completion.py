"""Tests for the Detection/SOC gaps closed on the v3.3 integration foundation.

Each test here pins behaviour that was previously missing or wrong:

* the pre-token gate must not create a second attempt, assessment, alert or
  destructive Core action for a login that Core also delivers as a
  canonical LoginEvent;
* a pipeline-created alert must open its own timeline;
* the ML client must honour ``model_status`` and refuse an out-of-range
  score instead of clamping it;
* a failed Core enforcement must be recorded, not silently swallowed;
* a re-score must not duplicate an alert or a protective action;
* the login-history endpoint (UC-DE-14) must filter, paginate and authorise
  correctly;
* alert and timeline filters must reject unknown values instead of silently
  returning an empty list.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import httpx
import pytest

from app import detection as det_mod
from app import internal_client
from app.models import (
    Alert,
    AlertTimeline,
    DetectionLog,
    LoginAttempt,
    RiskAssessment,
    SocAnalyst,
)
from app.schemas import SecurityAction


# =============================================================================
# Helpers
# =============================================================================

def _event_payload(**overrides) -> dict:
    """A canonical LoginEvent body (CONTRACT_CORE_DETECTION section A)."""
    payload = {
        "event_id": str(uuid4()),
        "username_attempted": "alice",
        "outcome": "failure",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    payload.update(overrides)
    return payload


def _make_attempt(db, **overrides) -> LoginAttempt:
    """Create a login attempt row directly."""
    fields = {
        "event_id": uuid4(),
        "username_attempted": "alice",
        "outcome": "failure",
        "timestamp": datetime.now(timezone.utc),
        "status": "pending",
    }
    fields.update(overrides)
    attempt = LoginAttempt(**fields)
    db.add(attempt)
    db.commit()
    db.refresh(attempt)
    return attempt


def _stub_ml(monkeypatch, score=0.0, status="success", model_status="ready"):
    """Stub the ML client so the pipeline is deterministic."""
    async def fake_call(features, request_id, **kwargs):
        return det_mod.MlOutcome(
            score=score if status == "success" else None,
            status=status,
            model_version="v-test",
            reason_codes=[],
        )

    monkeypatch.setattr(det_mod, "call_ml_service", fake_call)


def _stub_core(monkeypatch, *, enforced=True, status_code=200, body=None):
    """Stub the Core action boundary."""
    calls: list = []

    async def fake_call(url, kwargs):
        calls.append(kwargs.get("json"))
        if not enforced:
            raise httpx.ConnectError("refused")
        return httpx.Response(status_code, json=body or {"status": "applied"})

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
            return await fake_call(url, kwargs)

    monkeypatch.setattr(internal_client.httpx, "AsyncClient", _Stub)
    return calls


def _soc_auth_override(user, db):
    """Override the auth context with the given SOC analyst."""
    from app.authz import AuthContext

    async def _ctx(request=None):
        return AuthContext(request=request, session=None, user=user, roles=frozenset({"SOC_ANALYST"}))

    return _ctx


# =============================================================================
# A. Pre-token gate must not duplicate the canonical LoginEvent
# =============================================================================

def test_pre_token_check_writes_nothing(client, db, policy, monkeypatch):
    """The gate scores, but must not persist an attempt or an assessment.

    Core emits the canonical LoginEvent for the same login right after the
    gate, so a persisted gate attempt would duplicate the whole business
    effect of that login.
    """
    _stub_ml(monkeypatch, score=0.0)
    response = client.post(
        "/api/v1/internal/pre-token-check",
        json={"username": "alice", "user_id": str(uuid4())},
        headers={"X-Internal-Secret": "test-internal-secret-at-least-32-characters-long"},
    )
    assert response.status_code == 200
    assert db.query(LoginAttempt).count() == 0
    assert db.query(RiskAssessment).count() == 0
    assert db.query(Alert).count() == 0


def test_pre_token_check_does_not_create_an_alert_for_a_critical_verdict(
    client, db, policy, monkeypatch
):
    """A critical verdict from the gate must not open an alert on its own."""
    _stub_ml(monkeypatch, score=1.0)
    # The seeded policy triggers "unusual_hour" for any hour outside 07-22.
    response = client.post(
        "/api/v1/internal/pre-token-check",
        json={
            "username": "alice",
            "user_id": str(uuid4()),
            "timestamp": "2026-10-04T02:00:00Z",
        },
        headers={"X-Internal-Secret": "test-internal-secret-at-least-32-characters-long"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["risk_level"] in ("high", "critical")
    assert body["require_mfa"] is True
    # Nothing was persisted and no Core action was sent from the gate.
    assert db.query(Alert).count() == 0
    assert db.query(RiskAssessment).count() == 0


def test_pre_token_check_does_not_send_a_core_action(client, db, policy, monkeypatch):
    """The gate must not trigger a destructive Core action on its own.

    The protective action belongs to the persisted ``/login-events``
    delivery, which carries the stable ``detection:{attempt}:{action}``
    idempotency key.
    """
    calls = _stub_core(monkeypatch, enforced=True)
    _stub_ml(monkeypatch, score=1.0)
    client.post(
        "/api/v1/internal/pre-token-check",
        json={
            "username": "alice",
            "user_id": str(uuid4()),
            "timestamp": "2026-10-04T02:00:00Z",
        },
        headers={"X-Internal-Secret": "test-internal-secret-at-least-32-characters-long"},
    )
    assert calls == []


def test_gate_then_login_event_produces_one_attempt_and_one_alert(
    client, db, policy, monkeypatch
):
    """The gate and the canonical event together must have one business effect."""
    _stub_ml(monkeypatch, score=1.0)
    _stub_core(monkeypatch, enforced=True)
    user_id = str(uuid4())
    secret = {"X-Internal-Secret": "test-internal-secret-at-least-32-characters-long"}

    gate = client.post(
        "/api/v1/internal/pre-token-check",
        json={
            "username": "alice",
            "user_id": user_id,
            "timestamp": "2026-10-04T02:00:00Z",
        },
        headers=secret,
    )
    assert gate.status_code == 200
    assert gate.json()["require_mfa"] is True

    event = client.post(
        "/api/v1/internal/login-events",
        json=_event_payload(
            user_id=user_id,
            outcome="success",
            timestamp="2026-10-04T02:00:00Z",
        ),
        headers=secret,
    )
    assert event.status_code == 202

    assert db.query(LoginAttempt).count() == 1
    assert db.query(RiskAssessment).count() == 1
    assert db.query(Alert).count() == 1


# =============================================================================
# B. A pipeline-created alert opens its own timeline
# =============================================================================

def test_pipeline_created_alert_has_a_created_timeline_event(
    client, db, policy, monkeypatch
):
    """The SOC timeline must show that Detection opened the alert."""
    _stub_ml(monkeypatch, score=1.0)
    _stub_core(monkeypatch, enforced=True)
    response = client.post(
        "/api/v1/internal/login-events",
        json=_event_payload(
            user_id=str(uuid4()),
            outcome="success",
            timestamp="2026-10-04T02:00:00Z",
        ),
        headers={"X-Internal-Secret": "test-internal-secret-at-least-32-characters-long"},
    )
    assert response.status_code == 202

    alert = db.query(Alert).first()
    assert alert is not None
    events = db.query(AlertTimeline).filter(AlertTimeline.alert_id == alert.id).all()
    assert [e.event_type for e in events] == ["created"]
    assert events[0].actor_type == "system"


# =============================================================================
# C. Idempotency: the same event twice has one business effect
# =============================================================================

def test_duplicate_login_event_creates_no_second_attempt_or_alert(
    client, db, policy, monkeypatch
):
    """Replaying an event must not duplicate any business effect."""
    _stub_ml(monkeypatch, score=1.0)
    _stub_core(monkeypatch, enforced=True)
    event_id = str(uuid4())
    secret = {"X-Internal-Secret": "test-internal-secret-at-least-32-characters-long"}
    payload = _event_payload(
        event_id=event_id,
        user_id=str(uuid4()),
        outcome="success",
        timestamp="2026-10-04T02:00:00Z",
    )

    first = client.post("/api/v1/internal/login-events", json=payload, headers=secret)
    second = client.post("/api/v1/internal/login-events", json=payload, headers=secret)

    assert first.status_code == 202
    assert second.status_code == 202
    # The second delivery returns the SAME attempt id.
    assert first.json()["login_attempt_id"] == second.json()["login_attempt_id"]
    assert db.query(LoginAttempt).count() == 1
    assert db.query(RiskAssessment).count() == 1
    assert db.query(Alert).count() == 1


def test_duplicate_login_event_does_not_send_a_second_core_action(
    client, db, policy, monkeypatch
):
    """A replayed event must not trigger a second destructive action."""
    calls = _stub_core(monkeypatch, enforced=True)
    _stub_ml(monkeypatch, score=1.0)
    event_id = str(uuid4())
    secret = {"X-Internal-Secret": "test-internal-secret-at-least-32-characters-long"}
    payload = _event_payload(
        event_id=event_id,
        user_id=str(uuid4()),
        outcome="success",
        timestamp="2026-10-04T02:00:00Z",
    )

    client.post("/api/v1/internal/login-events", json=payload, headers=secret)
    client.post("/api/v1/internal/login-events", json=payload, headers=secret)

    assert len(calls) == 1


# =============================================================================
# D. Rescore must not duplicate an alert or a protective action
# =============================================================================

async def test_rescore_reuses_the_existing_alert(db, policy, monkeypatch):
    """A re-score of an already-alerted attempt must not open a second alert."""
    _stub_ml(monkeypatch, score=1.0)
    _stub_core(monkeypatch, enforced=True)
    attempt = _make_attempt(
        db,
        user_id=uuid4(),
        outcome="success",
        status="failed",
        timestamp=datetime.now(timezone.utc) - timedelta(hours=3),
    )

    # First pass creates the alert.
    await det_mod.process_attempt(db, attempt, attempt.request_id)
    assert db.query(Alert).count() == 1

    # Park it again and re-score: the existing alert must be reused.
    attempt.status = "failed"
    db.commit()
    await det_mod.process_attempt(db, attempt, attempt.request_id)
    assert db.query(Alert).count() == 1


async def test_rescore_updates_the_assessment_in_place(db, policy, monkeypatch):
    """``risk_assessments`` is 1:1 with the attempt; a re-score updates it."""
    _stub_ml(monkeypatch, score=0.0)
    attempt = _make_attempt(
        db,
        user_id=uuid4(),
        outcome="success",
        status="failed",
        timestamp=datetime.now(timezone.utc) - timedelta(hours=3),
    )

    await det_mod.process_attempt(db, attempt, attempt.request_id)
    assert db.query(RiskAssessment).count() == 1

    attempt.status = "failed"
    db.commit()
    await det_mod.process_attempt(db, attempt, attempt.request_id)
    assert db.query(RiskAssessment).count() == 1


# =============================================================================
# E. ML client contract handling
# =============================================================================

def _ml_response(monkeypatch, *, status_code=200, json_body=None, raises=None):
    """Stub the ML HTTP call and return the captured request."""
    captured: dict = {}

    async def handler(url, kwargs):
        captured["url"] = url
        captured["json"] = kwargs.get("json")
        captured["headers"] = kwargs.get("headers")
        if raises is not None:
            raise raises
        return httpx.Response(status_code, json=json_body)

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
            return await handler(url, kwargs)

    monkeypatch.setattr(det_mod.httpx, "AsyncClient", _Stub)
    return captured


async def test_ml_model_status_error_falls_back_to_rule_only(monkeypatch):
    """``model_status = "error"`` must degrade to rule-only scoring."""
    _ml_response(
        monkeypatch,
        json_body={
            "normalized_anomaly_score": 0.9,
            "model_status": "error",
            "model_version": "v1",
        },
    )
    outcome = await det_mod.call_ml_service({"hour_of_day": 1}, uuid4())
    assert outcome.status == "error"
    assert outcome.score is None
    assert outcome.error == "ml_model_status_error"


async def test_ml_out_of_range_score_is_rejected_not_clamped(monkeypatch):
    """A score outside [0, 1] is a broken contract, not a score to clamp."""
    _ml_response(
        monkeypatch,
        json_body={"normalized_anomaly_score": 1.7, "model_status": "ready"},
    )
    outcome = await det_mod.call_ml_service({"hour_of_day": 1}, uuid4())
    assert outcome.status == "error"
    assert outcome.score is None
    assert outcome.error == "ml_service_score_out_of_range"


async def test_ml_negative_score_is_rejected(monkeypatch):
    _ml_response(
        monkeypatch,
        json_body={"normalized_anomaly_score": -0.2, "model_status": "ready"},
    )
    outcome = await det_mod.call_ml_service({"hour_of_day": 1}, uuid4())
    assert outcome.status == "error"
    assert outcome.score is None


async def test_ml_non_object_body_is_an_error(monkeypatch):
    _ml_response(monkeypatch, json_body=[1, 2, 3])
    outcome = await det_mod.call_ml_service({"hour_of_day": 1}, uuid4())
    assert outcome.status == "error"
    assert outcome.error == "ml_service_bad_payload"


async def test_ml_success_sends_the_six_features_in_canonical_order(monkeypatch):
    captured = _ml_response(
        monkeypatch,
        json_body={"normalized_anomaly_score": 0.5, "model_status": "ready"},
    )
    features = {
        "hour_of_day": 1,
        "fail_count_24h": 0,
        "ip_change_rate_7d": 0.0,
        "new_device": False,
        "average_login_interval_seconds": 0,
        "deviation_score": 0.0,
    }
    outcome = await det_mod.call_ml_service(features, uuid4())
    assert outcome.status == "success"
    assert outcome.score == 0.5
    assert list(captured["json"]["features"].keys()) == list(features.keys())


# =============================================================================
# F. A failed Core enforcement is recorded, not swallowed
# =============================================================================

def test_failed_core_action_is_recorded_in_detection_logs(client, db, policy, monkeypatch):
    """A dead Core must not erase the verdict, but the failure must be visible."""
    _stub_ml(monkeypatch, score=1.0)
    _stub_core(monkeypatch, enforced=False)
    response = client.post(
        "/api/v1/internal/login-events",
        json=_event_payload(
            user_id=str(uuid4()),
            outcome="success",
            timestamp="2026-10-04T02:00:00Z",
        ),
        headers={"X-Internal-Secret": "test-internal-secret-at-least-32-characters-long"},
    )
    assert response.status_code == 202

    # The verdict and the alert survive the Core outage.
    assert db.query(LoginAttempt).count() == 1
    assert db.query(Alert).count() == 1

    outcome_logs = (
        db.query(DetectionLog)
        .filter(DetectionLog.stage == "action_sent")
        .all()
    )
    assert outcome_logs, "the failed enforcement must be recorded"
    assert outcome_logs[-1].details["enforced"] is False
    assert outcome_logs[-1].reason


def test_successful_core_action_is_recorded_as_enforced(client, db, policy, monkeypatch):
    _stub_ml(monkeypatch, score=1.0)
    _stub_core(monkeypatch, enforced=True)
    client.post(
        "/api/v1/internal/login-events",
        json=_event_payload(
            user_id=str(uuid4()),
            outcome="success",
            timestamp="2026-10-04T02:00:00Z",
        ),
        headers={"X-Internal-Secret": "test-internal-secret-at-least-32-characters-long"},
    )
    outcome_logs = (
        db.query(DetectionLog)
        .filter(DetectionLog.stage == "action_sent")
        .all()
    )
    assert any(log.details.get("enforced") is True for log in outcome_logs)


# =============================================================================
# G. Login history (UC-DE-14)
# =============================================================================

def _seed_history(db) -> None:
    """Seed a small, deterministic login history."""
    base = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
    db.add_all([
        LoginAttempt(
            event_id=uuid4(), user_id=uuid4(), username_attempted="alice",
            outcome="success", ip_address="10.0.0.1", risk_level="low",
            detection_decision="allow", status="processed",
            timestamp=base,
        ),
        LoginAttempt(
            event_id=uuid4(), user_id=uuid4(), username_attempted="alice",
            outcome="failure", ip_address="10.0.0.2", risk_level="high",
            detection_decision="challenge", status="processed",
            timestamp=base + timedelta(hours=1),
        ),
        LoginAttempt(
            event_id=uuid4(), user_id=uuid4(), username_attempted="bob",
            outcome="success", ip_address="10.0.0.3", risk_level="medium",
            detection_decision="allow", status="processed",
            timestamp=base + timedelta(hours=2),
        ),
    ])
    db.commit()


def test_login_history_lists_attempts_newest_first(client, db, user, monkeypatch):
    from app.main import app
    from app.authz import get_current_auth_context

    _seed_history(db)
    app.dependency_overrides[get_current_auth_context] = _soc_auth_override(user, db)
    try:
        response = client.get("/api/v1/login-attempts")
    finally:
        del app.dependency_overrides[get_current_auth_context]

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    timestamps = [a["timestamp"] for a in body["attempts"]]
    assert timestamps == sorted(timestamps, reverse=True)


def test_login_history_filters_by_username(client, db, user, monkeypatch):
    from app.main import app
    from app.authz import get_current_auth_context

    _seed_history(db)
    app.dependency_overrides[get_current_auth_context] = _soc_auth_override(user, db)
    try:
        response = client.get("/api/v1/login-attempts", params={"username": "bob"})
    finally:
        del app.dependency_overrides[get_current_auth_context]

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["attempts"][0]["username_attempted"] == "bob"


def test_login_history_filters_by_outcome(client, db, user, monkeypatch):
    from app.main import app
    from app.authz import get_current_auth_context

    _seed_history(db)
    app.dependency_overrides[get_current_auth_context] = _soc_auth_override(user, db)
    try:
        response = client.get("/api/v1/login-attempts", params={"outcome": "failure"})
    finally:
        del app.dependency_overrides[get_current_auth_context]

    assert response.status_code == 200
    assert response.json()["total"] == 1


def test_login_history_paginates(client, db, user, monkeypatch):
    from app.main import app
    from app.authz import get_current_auth_context

    _seed_history(db)
    app.dependency_overrides[get_current_auth_context] = _soc_auth_override(user, db)
    try:
        response = client.get("/api/v1/login-attempts", params={"page": 1, "limit": 2})
    finally:
        del app.dependency_overrides[get_current_auth_context]

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert len(body["attempts"]) == 2
    assert body["page"] == 1
    assert body["limit"] == 2


def test_login_history_rejects_an_unknown_outcome(client, db, user, monkeypatch):
    from app.main import app
    from app.authz import get_current_auth_context

    app.dependency_overrides[get_current_auth_context] = _soc_auth_override(user, db)
    try:
        response = client.get("/api/v1/login-attempts", params={"outcome": "bogus"})
    finally:
        del app.dependency_overrides[get_current_auth_context]

    assert response.status_code == 400


def test_login_history_requires_a_soc_role(client, db, user, monkeypatch):
    """A plain USER must not read the SOC login history."""
    from app.authz import AuthContext
    from app.main import app
    from app.authz import get_current_auth_context

    async def _ctx(request=None):
        return AuthContext(request=request, session=None, user=user, roles=frozenset({"USER"}))

    app.dependency_overrides[get_current_auth_context] = _ctx
    try:
        response = client.get("/api/v1/login-attempts")
    finally:
        del app.dependency_overrides[get_current_auth_context]

    assert response.status_code == 403


def test_login_history_never_returns_core_secrets(client, db, user, monkeypatch):
    """The history is Detection-owned; it must not leak Core columns."""
    from app.main import app
    from app.authz import get_current_auth_context

    _seed_history(db)
    app.dependency_overrides[get_current_auth_context] = _soc_auth_override(user, db)
    try:
        response = client.get("/api/v1/login-attempts")
    finally:
        del app.dependency_overrides[get_current_auth_context]

    assert response.status_code == 200
    for attempt in response.json()["attempts"]:
        assert set(attempt) == {
            "id", "event_id", "user_id", "username_attempted", "outcome",
            "mfa_used", "ip_address", "user_agent", "device_fingerprint",
            "timestamp", "status", "risk_level", "detection_decision",
            "policy_id", "primary_alert_id", "request_id",
        }


# =============================================================================
# H. Alert list filters reject unknown values
# =============================================================================

def test_alert_list_rejects_an_unknown_status(client, db, user, monkeypatch):
    from app.main import app
    from app.authz import get_current_auth_context

    app.dependency_overrides[get_current_auth_context] = _soc_auth_override(user, db)
    try:
        response = client.get("/api/v1/alerts", params={"status": "escalated"})
    finally:
        del app.dependency_overrides[get_current_auth_context]

    assert response.status_code == 400


def test_alert_list_rejects_an_unknown_risk_level(client, db, user, monkeypatch):
    from app.main import app
    from app.authz import get_current_auth_context

    app.dependency_overrides[get_current_auth_context] = _soc_auth_override(user, db)
    try:
        response = client.get("/api/v1/alerts", params={"risk_level": "extreme"})
    finally:
        del app.dependency_overrides[get_current_auth_context]

    assert response.status_code == 400


def test_alert_list_accepts_every_canonical_status(client, db, user, monkeypatch):
    from app.main import app
    from app.authz import get_current_auth_context

    app.dependency_overrides[get_current_auth_context] = _soc_auth_override(user, db)
    try:
        for status in ("open", "acknowledged", "resolved", "false_positive"):
            response = client.get("/api/v1/alerts", params={"status": status})
            assert response.status_code == 200, status
    finally:
        del app.dependency_overrides[get_current_auth_context]


# =============================================================================
# I. Timeline event_type validation
# =============================================================================

def test_timeline_rejects_an_unknown_event_type(client, db, user, monkeypatch):
    from app.main import app
    from app.authz import get_current_auth_context

    attempt = _make_attempt(db, user_id=uuid4())
    alert = Alert(login_attempt_id=attempt.id, status="open", risk_level="high")
    db.add(alert)
    db.commit()

    app.dependency_overrides[get_current_auth_context] = _soc_auth_override(user, db)
    try:
        response = client.post(
            f"/api/v1/alerts/{alert.id}/timeline",
            json={"event_type": "not_a_real_event"},
        )
    finally:
        del app.dependency_overrides[get_current_auth_context]

    assert response.status_code == 400


def test_timeline_accepts_the_escalation_marker(client, db, user, monkeypatch):
    """Escalation is a timeline event, not a status."""
    from app.main import app
    from app.authz import get_current_auth_context

    attempt = _make_attempt(db, user_id=uuid4())
    alert = Alert(login_attempt_id=attempt.id, status="open", risk_level="high")
    db.add(alert)
    db.commit()

    app.dependency_overrides[get_current_auth_context] = _soc_auth_override(user, db)
    try:
        response = client.post(
            f"/api/v1/alerts/{alert.id}/timeline",
            json={"event_type": "escalated", "comment": "escalated to tier 2"},
        )
    finally:
        del app.dependency_overrides[get_current_auth_context]

    assert response.status_code == 200
    assert response.json()["event_type"] == "escalated"


# =============================================================================
# J. Single active policy
# =============================================================================

def test_only_one_policy_can_be_active(db, policy):
    """The single-active invariant is enforced by the database, not by luck."""
    from app.models import Policy

    second = Policy(
        version="v2.0",
        name="Second",
        rules=[],
        config={},
        is_active=True,
    )
    db.add(second)
    with pytest.raises(Exception):
        db.commit()
    db.rollback()


def test_activating_a_policy_deactivates_the_previous_one(client, db, user, policy, monkeypatch):
    """Activation keeps exactly one active policy."""
    from app.main import app
    from app.authz import AuthContext, get_current_auth_context
    from app.models import Policy

    second = Policy(
        version="v2.0",
        name="Second",
        rules=[{
            "name": "unusual_hour", "field": "hour_of_day",
            "operator": "not_between", "value": [7, 22],
            "weight": 0.3, "score": 0.8, "enabled": True,
        }],
        config={"weights": {"rule": 0.4, "ml": 0.6},
                "thresholds": {"low": 0.25, "medium": 0.5, "high": 0.75}},
        is_active=False,
    )
    db.add(second)
    db.commit()
    db.refresh(second)

    async def _ctx(request=None):
        return AuthContext(
            request=request, session=None, user=user,
            roles=frozenset({"SECURITY_ADMIN"}),
        )

    app.dependency_overrides[get_current_auth_context] = _ctx
    try:
        response = client.post(f"/api/v1/policies/{second.id}/activate")
    finally:
        del app.dependency_overrides[get_current_auth_context]

    assert response.status_code == 200
    db.expire_all()
    assert db.query(Policy).filter(Policy.is_active.is_(True)).count() == 1
    assert db.query(Policy).filter(Policy.id == second.id).first().is_active is True
