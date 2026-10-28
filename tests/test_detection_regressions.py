"""Regression tests for the Detection gaps closed in the final review.

Each test here pins a behaviour that was WRONG or MISSING before this
change set.  The tests are grouped by the gap they cover:

* **A** - the pre-token gate must not persist a second event.
* **B** - a pipeline-created alert must start its own timeline.
* **C** - ``GET /api/v1/login-attempts`` (UC-DE-14) must exist and filter.
* **D** - the ML client must honour ``model_status`` and reject an
  out-of-range score instead of clamping it.
* **E** - the enforcement outcome must be recorded, not only logged.
* **F** - only one policy may be active at a time.
* **G/H** - alert filters and timeline event types must be validated.
* **I** - re-scoring must not duplicate an assessment, an alert or a
  destructive Core action.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import httpx
import pytest

from app import detection as det_mod
from app.models import Alert, AlertTimeline, DetectionLog, LoginAttempt, Policy, RiskAssessment


# =============================================================================
# Helpers
# =============================================================================

def _attempt(db, user_id=None, status="pending", decision=None, risk_level=None,
             outcome="success", timestamp=None, username="alice"):
    attempt = LoginAttempt(
        event_id=uuid4(),
        user_id=user_id,
        username_attempted=username,
        outcome=outcome,
        timestamp=timestamp or datetime.now(timezone.utc),
        status=status,
        detection_decision=decision,
        risk_level=risk_level,
    )
    db.add(attempt)
    db.commit()
    db.refresh(attempt)
    return attempt


def _stub_ml(monkeypatch, outcome):
    """Replace the ML client with a fixed outcome."""
    async def _call(features, request_id, timeout=None):
        return outcome
    monkeypatch.setattr(det_mod, "call_ml_service", _call)


def _ml_ok(score=0.9):
    return det_mod.MlOutcome(
        score=score,
        status="success",
        model_version="v-test",
        reason_codes=["high_fail_count"],
    )


def _stub_core(monkeypatch, recorder):
    """Intercept the Detection -> Core action call."""
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
            recorder.append({"url": url, "json": kwargs.get("json")})
            return httpx.Response(200, json={"status": "applied"})

    monkeypatch.setattr(det_mod.internal_client.httpx, "AsyncClient", _Stub)


# =============================================================================
# A - the pre-token gate must not persist a second event
# =============================================================================

def test_pre_token_check_writes_no_login_attempt(client, db):
    """The gate is a READ of the risk picture, not a second event.

    Core emits the canonical LoginEvent right after the gate answers.  If
    the gate persisted its own attempt, one login would produce two
    ``login_attempts`` rows.
    """
    response = client.post(
        "/api/v1/internal/pre-token-check",
        json={"username": "alice", "user_id": str(uuid4())},
        headers={"X-Internal-Secret": "test-internal-secret-at-least-32-characters-long"},
    )
    assert response.status_code == 200
    # The gate must not degrade: a degraded verdict would silently let the
    # login through instead of answering the question Core asked.
    assert response.json()["degraded"] is False
    assert db.query(LoginAttempt).count() == 0


def test_one_login_produces_one_attempt_one_assessment_one_alert(client, db, policy, monkeypatch):
    """The end-to-end invariant: the gate + the canonical event = one of each.

    This is the regression that matters: a login that is gated and then
    delivered as a LoginEvent must not be scored, alerted on or protected
    twice.
    """
    calls = []
    _stub_core(monkeypatch, calls)
    _stub_ml(monkeypatch, _ml_ok(score=0.99))
    user_id = str(uuid4())

    # 1. Core asks the gate for a verdict.
    gate = client.post(
        "/api/v1/internal/pre-token-check",
        json={"username": "alice", "user_id": user_id},
        headers={"X-Internal-Secret": "test-internal-secret-at-least-32-characters-long"},
    )
    assert gate.status_code == 200
    assert gate.json()["degraded"] is False

    # 2. Core then delivers the canonical LoginEvent for the same login.
    event = client.post(
        "/api/v1/internal/login-events",
        json={
            "event_id": str(uuid4()),
            "user_id": user_id,
            "username_attempted": "alice",
            "outcome": "mfa_required",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
        headers={"X-Internal-Secret": "test-internal-secret-at-least-32-characters-long"},
    )
    assert event.status_code == 202

    # Exactly one of each.
    assert db.query(LoginAttempt).count() == 1
    assert db.query(RiskAssessment).count() == 1
    assert db.query(Alert).count() == 1
    # Exactly one protective action, not two.
    assert len(calls) == 1


def test_pre_token_check_writes_no_risk_assessment(client, db):
    """No assessment may be written by the gate either."""
    client.post(
        "/api/v1/internal/pre-token-check",
        json={"username": "alice", "user_id": str(uuid4())},
        headers={"X-Internal-Secret": "test-internal-secret-at-least-32-characters-long"},
    )
    assert db.query(RiskAssessment).count() == 0


def test_pre_token_check_writes_no_alert(client, db, policy, monkeypatch):
    """A high/critical verdict from the gate must not create an alert.

    The alert belongs to the persisted scoring that follows the gate.  A
    gate-created alert would be a second alert - and a second destructive
    Core action - for the same login.
    """
    _stub_ml(monkeypatch, _ml_ok(score=0.99))

    response = client.post(
        "/api/v1/internal/pre-token-check",
        json={"username": "alice", "user_id": str(uuid4())},
        headers={"X-Internal-Secret": "test-internal-secret-at-least-32-characters-long"},
    )
    assert response.status_code == 200
    assert db.query(Alert).count() == 0
    assert db.query(AlertTimeline).count() == 0


def test_pre_token_check_sends_no_core_action(client, db, policy, monkeypatch):
    """The gate must not ask Core to revoke anything.

    The protective action belongs to the persisted scoring pass; the gate
    only answers "should the token be held back?".
    """
    calls = []
    _stub_core(monkeypatch, calls)
    _stub_ml(monkeypatch, _ml_ok(score=0.99))

    client.post(
        "/api/v1/internal/pre-token-check",
        json={"username": "alice", "user_id": str(uuid4())},
        headers={"X-Internal-Secret": "test-internal-secret-at-least-32-characters-long"},
    )
    assert calls == []


def test_pre_token_check_still_reports_the_verdict(client, db, policy, monkeypatch):
    """The gate must keep answering correctly - it is a read, not a no-op."""
    _stub_ml(monkeypatch, _ml_ok(score=0.99))

    response = client.post(
        "/api/v1/internal/pre-token-check",
        json={"username": "alice", "user_id": str(uuid4())},
        headers={"X-Internal-Secret": "test-internal-secret-at-least-32-characters-long"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["risk_level"] in ("high", "critical")
    assert body["require_mfa"] is True
    assert body["degraded"] is False


def test_pre_token_check_leaves_no_orphan_pending_row(client, db, policy, monkeypatch):
    """No ``status='pending'`` row may be left behind by the gate."""
    _stub_ml(monkeypatch, _ml_ok(score=0.99))

    client.post(
        "/api/v1/internal/pre-token-check",
        json={"username": "alice", "user_id": str(uuid4())},
        headers={"X-Internal-Secret": "test-internal-secret-at-least-32-characters-long"},
    )
    assert db.query(LoginAttempt).filter(LoginAttempt.status == "pending").count() == 0


# =============================================================================
# B - a pipeline-created alert must start its own timeline
# =============================================================================

async def test_pipeline_alert_has_a_created_timeline_event(db, policy, monkeypatch):
    """Detection-created alerts must record the ``created`` event.

    Without it the SOC's first timeline entry claims the analyst opened
    an alert that the Detection Engine opened.
    """
    _stub_ml(monkeypatch, _ml_ok(score=0.99))
    attempt = _attempt(db, user_id=None)

    result = await det_mod.process_attempt(db, attempt, uuid4())
    assert result.alert_id is not None

    events = (
        db.query(AlertTimeline)
        .filter(AlertTimeline.alert_id == result.alert_id)
        .all()
    )
    assert len(events) == 1
    assert events[0].event_type == "created"
    assert events[0].actor_type == "system"


async def test_pipeline_alert_timeline_is_not_duplicated_on_rescore(db, policy, monkeypatch):
    """A re-score must not append a second ``created`` event."""
    _stub_ml(monkeypatch, _ml_ok(score=0.99))
    attempt = _attempt(db, user_id=None)

    first = await det_mod.process_attempt(db, attempt, uuid4())
    second = await det_mod.process_attempt(db, attempt, uuid4())
    assert first.alert_id == second.alert_id

    created = (
        db.query(AlertTimeline)
        .filter(
            AlertTimeline.alert_id == first.alert_id,
            AlertTimeline.event_type == "created",
        )
        .count()
    )
    assert created == 1


# =============================================================================
# I - re-scoring must not duplicate anything
# =============================================================================

async def test_rescore_reuses_the_existing_assessment(db, policy, monkeypatch):
    """``risk_assessments`` is 1:1 with the attempt - a re-score updates it."""
    _stub_ml(monkeypatch, _ml_ok(score=0.99))
    attempt = _attempt(db, user_id=None)

    await det_mod.process_attempt(db, attempt, uuid4())
    await det_mod.process_attempt(db, attempt, uuid4())

    assessments = (
        db.query(RiskAssessment)
        .filter(RiskAssessment.login_attempt_id == attempt.id)
        .all()
    )
    assert len(assessments) == 1


async def test_rescore_does_not_create_a_second_alert(db, policy, monkeypatch):
    """A re-score must not create a second alert for the same attempt."""
    _stub_ml(monkeypatch, _ml_ok(score=0.99))
    attempt = _attempt(db, user_id=None)

    await det_mod.process_attempt(db, attempt, uuid4())
    await det_mod.process_attempt(db, attempt, uuid4())

    alerts = db.query(Alert).filter(Alert.login_attempt_id == attempt.id).all()
    assert len(alerts) == 1


async def test_rescore_sends_only_one_core_action(db, user, policy, monkeypatch):
    """A re-score must not revoke the user's sessions twice.

    The idempotency key is stable per attempt, so Core would deduplicate
    it - but the call itself must not be repeated either.
    """
    calls = []
    _stub_core(monkeypatch, calls)
    _stub_ml(monkeypatch, _ml_ok(score=0.99))
    attempt = _attempt(db, user_id=user.id)

    await det_mod.process_attempt(db, attempt, uuid4())
    await det_mod.enforce_action_in_core(attempt, "critical", None, db=db)
    await det_mod.enforce_action_in_core(attempt, "critical", None, db=db)

    assert len(calls) == 2
    keys = {call["json"]["idempotency_key"] for call in calls}
    assert keys == {f"detection:{attempt.id}:REVOKE_SESSIONS"}


async def test_rescore_sweep_reuses_an_existing_alert(db, policy, monkeypatch):
    """The rescore sweep must not duplicate an alert left by a crashed run."""
    calls = []
    _stub_core(monkeypatch, calls)
    _stub_ml(monkeypatch, _ml_ok(score=0.99))

    attempt = _attempt(db, user_id=None, status="failed")
    # A crashed run already created the alert.
    alert = Alert(login_attempt_id=attempt.id, status="open", risk_level="critical")
    db.add(alert)
    db.commit()

    recovered = await det_mod.rescore_failed_attempts(db)
    assert recovered == 1
    assert db.query(Alert).filter(Alert.login_attempt_id == attempt.id).count() == 1


# =============================================================================
# E - the enforcement outcome must be recorded
# =============================================================================

async def test_action_enforcement_outcome_is_recorded(db, user, policy, monkeypatch):
    """A successful enforcement is recorded in ``detection_logs``."""
    _stub_core(monkeypatch, [])
    attempt = _attempt(db, user_id=user.id)

    await det_mod.enforce_action_in_core(attempt, "critical", None, db=db)

    logs = (
        db.query(DetectionLog)
        .filter(DetectionLog.stage == "action_sent")
        .all()
    )
    assert len(logs) == 1
    assert logs[0].details["enforced"] is True
    assert logs[0].details["action"] == "REVOKE_SESSIONS"


async def test_failed_action_enforcement_is_recorded(db, user, policy, monkeypatch):
    """A FAILED enforcement must be visible too - that is the important case."""
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
            raise httpx.ConnectError("refused")

    monkeypatch.setattr(det_mod.internal_client.httpx, "AsyncClient", _Stub)
    attempt = _attempt(db, user_id=user.id)

    enforced = await det_mod.enforce_action_in_core(attempt, "critical", None, db=db)
    assert enforced is False

    logs = (
        db.query(DetectionLog)
        .filter(DetectionLog.stage == "action_sent")
        .all()
    )
    assert len(logs) == 1
    assert logs[0].details["enforced"] is False
    assert logs[0].reason


# =============================================================================
# D - the ML client contract
# =============================================================================

async def test_ml_model_status_error_falls_back_to_the_rule_score(monkeypatch):
    """``model_status = "error"`` must trigger the rule-only fallback.

    The contract (CONTRACT_DETECTION_ML section H) says a model in error
    state is unavailable.  A score present in the same body must not be
    used.
    """
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
            return httpx.Response(200, json={
                "request_id": str(uuid4()),
                "normalized_anomaly_score": 0.99,
                "is_anomaly": True,
                "model_version": "v-broken",
                "reason_codes": [],
                "model_status": "error",
            })

    monkeypatch.setattr(det_mod.httpx, "AsyncClient", _Stub)
    outcome = await det_mod.call_ml_service(
        {"hour_of_day": 3, "fail_count_24h": 9}, uuid4()
    )
    assert outcome.status == "error"
    assert outcome.score is None


async def test_ml_out_of_range_score_is_rejected_not_clamped(monkeypatch):
    """A score outside [0, 1] breaks the contract.

    Clamping it would hide the fault AND still move the verdict, so the
    call must be treated as an error and fall back to the rule score.
    """
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
            return httpx.Response(200, json={
                "request_id": str(uuid4()),
                "normalized_anomaly_score": 1.7,
                "is_anomaly": True,
                "model_version": "v-broken",
                "reason_codes": [],
                "model_status": "ready",
            })

    monkeypatch.setattr(det_mod.httpx, "AsyncClient", _Stub)
    outcome = await det_mod.call_ml_service(
        {"hour_of_day": 3, "fail_count_24h": 9}, uuid4()
    )
    assert outcome.status == "error"
    assert outcome.score is None
    assert outcome.error == "ml_service_score_out_of_range"


async def test_ml_score_in_range_is_accepted(monkeypatch):
    """The normal path must keep working."""
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
            return httpx.Response(200, json={
                "request_id": str(uuid4()),
                "normalized_anomaly_score": 0.72,
                "is_anomaly": True,
                "model_version": "v1.0",
                "reason_codes": ["high_fail_count"],
                "model_status": "ready",
            })

    monkeypatch.setattr(det_mod.httpx, "AsyncClient", _Stub)
    outcome = await det_mod.call_ml_service(
        {"hour_of_day": 3, "fail_count_24h": 9}, uuid4()
    )
    assert outcome.status == "success"
    assert outcome.score == 0.72


# =============================================================================
# F - only one policy may be active
# =============================================================================

def test_the_database_refuses_two_active_policies(db):
    """The single-active invariant is enforced by the database, not by luck."""
    from sqlalchemy.exc import IntegrityError

    db.add(Policy(version="v-a", rules=[], config={}, is_active=True))
    db.commit()
    db.add(Policy(version="v-b", rules=[], config={}, is_active=True))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_the_database_allows_one_active_policy_at_a_time(db):
    """Deactivating the first one makes room for the second."""
    first = Policy(version="v-a", rules=[], config={}, is_active=True)
    db.add(first)
    db.commit()

    first.is_active = False
    second = Policy(version="v-b", rules=[], config={}, is_active=True)
    db.add(second)
    db.commit()

    active = db.query(Policy).filter(Policy.is_active.is_(True)).all()
    assert len(active) == 1
    assert active[0].version == "v-b"


# =============================================================================
# G/H - input validation
# =============================================================================

def test_alert_list_rejects_an_unknown_status(client, db, user):
    """An unknown status must be a clear 400, not an empty list."""
    from app.authz import get_current_auth_context
    from app.main import app
    from tests.test_alert_actions import _make_auth_override

    app.dependency_overrides[get_current_auth_context] = _make_auth_override(user, db)
    try:
        response = client.get("/api/v1/alerts?status=escalated")
    finally:
        del app.dependency_overrides[get_current_auth_context]

    assert response.status_code == 400
    assert "status" in response.json()["detail"]


def test_alert_list_rejects_an_unknown_risk_level(client, db, user):
    """An unknown risk level must be a clear 400."""
    from app.authz import get_current_auth_context
    from app.main import app
    from tests.test_alert_actions import _make_auth_override

    app.dependency_overrides[get_current_auth_context] = _make_auth_override(user, db)
    try:
        response = client.get("/api/v1/alerts?risk_level=extreme")
    finally:
        del app.dependency_overrides[get_current_auth_context]

    assert response.status_code == 400
    assert "risk_level" in response.json()["detail"]


def test_timeline_rejects_an_unknown_event_type(client, db, user):
    """An unknown timeline event type must be a clear 400."""
    from app.authz import get_current_auth_context
    from app.main import app
    from tests.test_alert_actions import _make_alert, _make_auth_override

    alert, alert_id = _make_alert(db, user.id)
    app.dependency_overrides[get_current_auth_context] = _make_auth_override(user, db)
    try:
        response = client.post(
            f"/api/v1/alerts/{alert_id}/timeline",
            json={"event_type": "teleported", "comment": "nope"},
        )
    finally:
        del app.dependency_overrides[get_current_auth_context]

    assert response.status_code == 400
    assert "event_type" in response.json()["detail"]


# =============================================================================
# C - the login-history endpoint (UC-DE-14)
# =============================================================================

def _login_history_call(client, db, user, **params):
    from app.authz import get_current_auth_context
    from app.main import app
    from tests.test_alert_actions import _make_auth_override

    app.dependency_overrides[get_current_auth_context] = _make_auth_override(user, db)
    try:
        return client.get("/api/v1/login-attempts", params=params)
    finally:
        del app.dependency_overrides[get_current_auth_context]


def test_login_history_endpoint_returns_the_attempts(client, db, user):
    """UC-DE-14: the SOC can search the login history."""
    _attempt(db, user_id=user.id, outcome="success", risk_level="high")
    _attempt(db, user_id=user.id, outcome="failure", risk_level="low")

    response = _login_history_call(client, db, user)
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert len(body["attempts"]) == 2


def test_login_history_filters_by_username(client, db, user):
    """The canonical search criteria are honoured."""
    _attempt(db, user_id=user.id, username="alice")
    _attempt(db, user_id=user.id, username="bob")

    response = _login_history_call(client, db, user, username="bob")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["attempts"][0]["username_attempted"] == "bob"


def test_login_history_filters_by_risk_level(client, db, user):
    """The risk-level filter works."""
    _attempt(db, user_id=user.id, risk_level="critical")
    _attempt(db, user_id=user.id, risk_level="low")

    response = _login_history_call(client, db, user, risk_level="critical")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["attempts"][0]["risk_level"] == "critical"


def test_login_history_filters_by_failure_outcome(client, db, user):
    """The ``failure`` search term also matches an MFA failure."""
    _attempt(db, user_id=user.id, outcome="failure")
    _attempt(db, user_id=user.id, outcome="mfa_failed")
    _attempt(db, user_id=user.id, outcome="success")

    response = _login_history_call(client, db, user, outcome="failure")
    assert response.status_code == 200
    assert response.json()["total"] == 2


def test_login_history_paginates(client, db, user):
    """Pagination is applied to the result set."""
    for _ in range(5):
        _attempt(db, user_id=user.id)

    response = _login_history_call(client, db, user, page=2, limit=2)
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 5
    assert body["page"] == 2
    assert len(body["attempts"]) == 2


def test_login_history_rejects_an_unknown_outcome(client, db, user):
    """An unknown outcome must be a clear 400."""
    response = _login_history_call(client, db, user, outcome="exploded")
    assert response.status_code == 400
    assert "outcome" in response.json()["detail"]


def test_login_history_requires_a_soc_role(client, db, user):
    """A user without a SOC role must not see the login history."""
    from app.authz import get_current_auth_context
    from app.main import app
    from app.authz import AuthContext

    async def _no_roles(request=None):
        return AuthContext(request=request, session=None, user=user, roles=frozenset())

    app.dependency_overrides[get_current_auth_context] = _no_roles
    try:
        response = client.get("/api/v1/login-attempts")
    finally:
        del app.dependency_overrides[get_current_auth_context]

    assert response.status_code == 403


def test_login_history_reads_only_the_detection_database():
    """The endpoint must not reach into the Core schema.

    The subject is described by the Detection-owned columns; no Core
    table is joined.  The check is AST-based so it covers every statement
    in the module, not just the ones a runtime test happens to reach.
    """
    import ast

    from app import login_history

    tree = ast.parse(open(login_history.__file__, encoding="utf-8").read())

    core_owned = {
        "Role", "User", "UserRole", "IpAddress", "Session", "MfaTransaction",
        "MfaNotification", "AuditLog", "UserTrustedDevice", "SystemSetting",
        "OutboxEvent", "UserNotification", "RateLimit",
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "app.models":
            offenders = {alias.name for alias in node.names} & core_owned
            assert not offenders, (
                f"login_history.py imports Core-owned models {sorted(offenders)}"
            )
        if isinstance(node, ast.ImportFrom) and node.module == "app.db":
            names = {alias.name for alias in node.names}
            assert "get_core_db" not in names, (
                "login_history.py must not depend on get_core_db"
            )
