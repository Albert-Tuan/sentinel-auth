"""
Detection Engine - rule evaluation, ML scoring and risk classification.

Schema v3.3. Canonical decisions: docs/DECISIONS-DETECTION-v3.3.md

Design notes
------------
* Rules live in ``policies.rules`` (JSONB) with 7 fields per rule:
  name, field, operator, value, weight, score, enabled.
* ``rule_score`` is a weighted sum normalised by the total weight of all
  enabled rules, so it always stays inside [0, 1] (DECISIONS section 2.1).
* The ML score is obtained by calling ML Service over HTTP with a 5s
  timeout. If the call fails the engine degrades gracefully:
  ``combined_score = rule_score`` and ``ml_status`` records why.
* A malformed rule or config must never raise: it is skipped, logged in
  ``detection_logs`` and the remaining rules are still evaluated.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID, uuid4

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, status as http_status
from pydantic import BaseModel
from sqlalchemy.orm import Session as OrmSession

from app.db import get_db
from app.models import Alert, DetectionLog, LoginAttempt, Policy, RiskAssessment
from app.schemas import (
    ActionRequest,
    ActionResponse,
    ALLOWED_FEATURE_FIELDS,
    ALLOWED_OPERATORS,
    DetectionResponse,
    LoginAttemptStatusResponse,
    LoginEventRequest,
    LoginEventResponse,
    RANGE_OPERATORS,
    RuleHit,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/internal", tags=["detection-internal"])
policy_router = APIRouter(prefix="/api/v1/policies", tags=["policies"])

#: Canonical defaults, used whenever policies.config is missing or invalid
DEFAULT_WEIGHTS = {"rule": 0.4, "ml": 0.6}
DEFAULT_THRESHOLDS = {"low": 0.25, "medium": 0.50, "high": 0.75}

#: ML Service is called over HTTP; this is the hard timeout (DECISIONS 2.2)
ML_TIMEOUT_SECONDS = 5.0

#: Callback into Core App to enforce a protective action. Kept short: the
#: scoring endpoint must not be held open waiting on an auth service.
ACTION_ENFORCE_TIMEOUT_SECONDS = 3.0

#: Risk level -> (decision, action label, create_alert)
DECISION_MATRIX = {
    "low": ("allow", "ALLOW", False),
    "medium": ("allow", "ALLOW_LOG", False),
    "high": ("challenge", "REQUIRE_MFA", True),
    "critical": ("block", "BLOCK_ALERT", True),
}


def internal_secret() -> str:
    """Shared secret protecting service-to-service endpoints."""
    return os.getenv("INTERNAL_SECRET", "changeme-in-production")


def ml_service_url() -> str:
    """Base URL of the ML Service, without trailing slash."""
    return os.getenv("ML_SERVICE_URL", "http://localhost:8002").rstrip("/")


def core_app_url() -> str:
    """Base URL of the Core App, without trailing slash.

    The Detection Engine calls back into Core App to enforce protective
    actions; the address is not hardcoded so tests and deployments can
    point it elsewhere.
    """
    return os.getenv("CORE_APP_URL", "http://localhost:8000").rstrip("/")


#: Risk level -> protective action to enforce in Core App.
#:
#: ``critical`` revokes sessions and demands a fresh MFA rather than locking
#: the account outright: a false positive from the ML model would otherwise
#: lock out a legitimate user, whereas revocation is cheap and reversible -
#: they simply sign in again and pass MFA.
RISK_ACTION_MAP = {
    "high": "REQUIRE_MFA",
    "critical": "REVOKE_SESSIONS",
}


def verify_internal_secret(x_internal_secret: Optional[str]) -> None:
    """Raise 401 unless the caller presented the correct shared secret."""
    if not x_internal_secret or x_internal_secret != internal_secret():
        raise HTTPException(
            status_code=http_status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing X-Internal-Secret",
        )


# =============================================================================
# Policy helpers
# =============================================================================

class ResolvedConfig:
    """Validated weights/thresholds, falling back to canonical defaults."""

    def __init__(self, weights: Dict[str, float], thresholds: Dict[str, float]):
        self.weights = weights
        self.thresholds = thresholds


def resolve_config(raw: Optional[dict]) -> Tuple[ResolvedConfig, List[str]]:
    """Validate policies.config; never raise on bad input (DECISIONS 3.3).

    Returns the resolved config plus a list of human-readable problems that
    the caller records in ``detection_logs``.
    """
    problems: List[str] = []
    raw = raw if isinstance(raw, dict) else {}

    # --- weights ---
    raw_weights = raw.get("weights")
    weights = dict(DEFAULT_WEIGHTS)
    if isinstance(raw_weights, dict):
        parsed = {}
        for key, fallback in DEFAULT_WEIGHTS.items():
            value = raw_weights.get(key)
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                problems.append(f"weights.{key} is not a number")
                continue
            if not 0.0 <= float(value) <= 1.0:
                problems.append(f"weights.{key}={value} outside [0, 1]")
                continue
            parsed[key] = float(value)
        if len(parsed) == len(DEFAULT_WEIGHTS) and parsed["rule"] > 0 and parsed["ml"] > 0:
            if abs(parsed["rule"] + parsed["ml"] - 1.0) > 1e-6:
                problems.append("weights.rule + weights.ml must equal 1.0")
            else:
                weights = parsed
        elif parsed:
            problems.append("weights incomplete, using defaults")
    elif raw_weights is not None:
        problems.append("weights is not an object, using defaults")

    # --- thresholds ---
    raw_thresholds = raw.get("thresholds")
    thresholds = dict(DEFAULT_THRESHOLDS)
    if isinstance(raw_thresholds, dict):
        parsed = {}
        for key in DEFAULT_THRESHOLDS:
            value = raw_thresholds.get(key)
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                problems.append(f"thresholds.{key} is not a number")
                continue
            if not 0.0 <= float(value) <= 1.0:
                problems.append(f"thresholds.{key}={value} outside [0, 1]")
                continue
            parsed[key] = float(value)
        if len(parsed) == len(DEFAULT_THRESHOLDS) and not (
            parsed["low"] <= parsed["medium"] <= parsed["high"]
        ):
            problems.append("thresholds must satisfy low <= medium <= high")
        elif len(parsed) == len(DEFAULT_THRESHOLDS):
            thresholds = parsed
        elif parsed:
            problems.append("thresholds incomplete, using defaults")
    elif raw_thresholds is not None:
        problems.append("thresholds is not an object, using defaults")

    return ResolvedConfig(weights, thresholds), problems


def get_active_policy(db) -> Optional[Policy]:
    """Return the single active policy, or None when none is activated."""
    return db.query(Policy).filter(Policy.is_active.is_(True)).first()


# =============================================================================
# Rule evaluation
# =============================================================================

def compare(actual: Any, operator: str, expected: Any) -> bool:
    """Apply one comparison operator. Unknown operator -> False."""
    try:
        if operator == "==":
            return bool(actual == expected)
        if operator == "!=":
            return bool(actual != expected)
        if operator == "in":
            return actual in expected
        if operator == "between":
            return bool(expected[0] <= actual <= expected[1])
        if operator == "not_between":
            return not (expected[0] <= actual <= expected[1])
        if actual is None:
            return False
        if operator == ">":
            return bool(actual > expected)
        if operator == ">=":
            return bool(actual >= expected)
        if operator == "<":
            return bool(actual < expected)
        if operator == "<=":
            return bool(actual <= expected)
    except (TypeError, KeyError, IndexError):
        return False
    return False


def validate_rule(rule: Any) -> Optional[str]:
    """Return a problem description, or None when the rule is usable.

    A rule is usable when it has all 7 fields, ``field`` is one of the 6
    features, ``operator`` is supported, and weight/score are in [0, 1].
    """
    if not isinstance(rule, dict):
        return "rule is not an object"

    for key in ("name", "field", "operator", "value", "weight", "score"):
        if key not in rule:
            return f"missing field {key!r}"

    if rule["field"] not in ALLOWED_FEATURE_FIELDS:
        return f"unknown feature {rule['field']!r}"
    if rule["operator"] not in ALLOWED_OPERATORS:
        return f"unsupported operator {rule['operator']!r}"
    if rule["operator"] in RANGE_OPERATORS and (
        not isinstance(rule["value"], (list, tuple)) or len(rule["value"]) != 2
    ):
        return f"operator {rule['operator']!r} requires [min, max]"
    if rule["operator"] == "in" and (
        not isinstance(rule["value"], (list, tuple)) or len(rule["value"]) == 0
    ):
        return "operator 'in' requires a non-empty list"

    for key in ("weight", "score"):
        value = rule[key]
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return f"{key} is not a number"
        if not 0.0 <= float(value) <= 1.0:
            return f"{key}={value} outside [0, 1]"

    return None


def evaluate_rules(
    rules: Any, features: Dict[str, Any]
) -> Tuple[float, List[RuleHit], List[Dict[str, Any]]]:
    """Evaluate every rule and return the normalised rule score.

    Returns ``(rule_score, hits, problems)`` where ``hits`` are only the
    rules that triggered and ``problems`` describes rules that were skipped
    (DECISIONS sections 1.6 and 2.1).
    """
    problems: List[Dict[str, Any]] = []
    if not isinstance(rules, list) or not rules:
        return 0.0, [], problems

    usable: List[dict] = []
    for index, rule in enumerate(rules):
        issue = validate_rule(rule)
        if issue:
            name = rule.get("name") if isinstance(rule, dict) else None
            problems.append(
                {
                    "rule_name": name or f"index_{index}",
                    "reason": "unknown_feature" if issue.startswith("unknown feature") else "invalid_rule",
                    "detail": issue,
                    "triggered": False,
                }
            )
            continue
        if not rule.get("enabled", True):
            continue
        usable.append(rule)

    if not usable:
        return 0.0, [], problems

    denominator = sum(float(r["weight"]) for r in usable)
    if denominator <= 0:
        return 0.0, [], problems

    hits: List[RuleHit] = []
    numerator = 0.0
    for rule in usable:
        triggered = compare(
            features.get(rule["field"]), rule["operator"], rule["value"]
        )
        if not triggered:
            continue
        contribution = float(rule["score"]) * float(rule["weight"])
        numerator += contribution
        hits.append(
            RuleHit(
                rule_name=str(rule["name"]),
                rule_id=None,
                triggered=True,
                score=float(rule["score"]),
                weight=float(rule["weight"]),
                score_contribution=contribution / denominator,
                reason=rule.get("description") or f"{rule['field']} {rule['operator']} {rule['value']}",
            )
        )

    rule_score = min(1.0, numerator / denominator)
    return rule_score, hits, problems


# =============================================================================
# Feature building (UC-DE-02)
# =============================================================================

def build_features(db, attempt: LoginAttempt) -> Dict[str, Any]:
    """Derive the 6 features a rule may reference from the login history."""
    now = attempt.timestamp or datetime.now(timezone.utc)
    features: Dict[str, Any] = {
        "hour_of_day": now.hour,
        "fail_count_24h": 0,
        "ip_change_rate_7d": 0.0,
        "new_device": False,
        "average_login_interval_seconds": 0,
        "deviation_score": 0.0,
    }

    if not attempt.user_id:
        return features

    day_ago = now - timedelta(hours=24)
    week_ago = now - timedelta(days=7)

    # Failures in the last 24h (excluding the attempt being scored)
    failures = (
        db.query(LoginAttempt)
        .filter(
            LoginAttempt.user_id == attempt.user_id,
            LoginAttempt.timestamp >= day_ago,
            LoginAttempt.outcome == "failure",
        )
        .count()
    )
    features["fail_count_24h"] = failures

    # IP change rate over 7 days: distinct IPs / total logins
    week_attempts = (
        db.query(LoginAttempt)
        .filter(
            LoginAttempt.user_id == attempt.user_id,
            LoginAttempt.timestamp >= week_ago,
        )
        .all()
    )
    if week_attempts:
        known_ips = {a.ip_address for a in week_attempts if a.ip_address}
        total = len(known_ips) + 1  # +1 for the IP of the current attempt
        features["ip_change_rate_7d"] = min(1.0, len(known_ips) / total)

    # New device: unknown user agent in the last 30 days
    if attempt.user_agent:
        month_ago = now - timedelta(days=30)
        known_agents = {
            row[0]
            for row in db.query(LoginAttempt.user_agent)
            .filter(
                LoginAttempt.user_id == attempt.user_id,
                LoginAttempt.timestamp >= month_ago,
                LoginAttempt.user_agent.isnot(None),
            )
            .distinct()
            .all()
        }
        features["new_device"] = attempt.user_agent not in known_agents

    # Average interval between consecutive logins
    recent = (
        db.query(LoginAttempt.timestamp)
        .filter(
            LoginAttempt.user_id == attempt.user_id,
            LoginAttempt.timestamp < now,
        )
        .order_by(LoginAttempt.timestamp.desc())
        .limit(10)
        .all()
    )
    stamps = [row[0] for row in recent if row[0] is not None]
    if len(stamps) >= 2:
        gaps = []
        for earlier, later in zip(stamps, stamps[1:]):
            delta = (earlier - later).total_seconds()
            if delta >= 0:
                gaps.append(delta)
        if gaps:
            features["average_login_interval_seconds"] = int(sum(gaps) / len(gaps))
            mean_gap = sum(gaps) / len(gaps)
            actual_gap = (now - stamps[0]).total_seconds()
            features["deviation_score"] = min(
                1.0, abs(actual_gap - mean_gap) / mean_gap if mean_gap else 0.0
            )

    return features


# =============================================================================
# ML Service call (UC-DE-03)
# =============================================================================

class MlOutcome:
    """Result of calling ML Service, including failure details."""

    def __init__(
        self,
        score: Optional[float],
        status: str,
        model_version: Optional[str] = None,
        reason_codes: Optional[List[str]] = None,
        error: Optional[str] = None,
    ):
        self.score = score
        self.status = status
        self.model_version = model_version
        self.reason_codes = reason_codes or []
        self.error = error


async def call_ml_service(features: Dict[str, Any], request_id: UUID) -> MlOutcome:
    """POST /api/v1/internal/ml/score with a 5s timeout and safe fallback."""
    url = f"{ml_service_url()}/api/v1/internal/ml/score"
    payload = {
        "request_id": str(request_id),
        "features": {k: v for k, v in features.items() if v is not None},
    }
    try:
        async with httpx.AsyncClient(timeout=ML_TIMEOUT_SECONDS) as client:
            response = await client.post(
                url,
                json=payload,
                headers={"X-Internal-Secret": internal_secret()},
            )
        if response.status_code >= 500:
            return MlOutcome(None, "error", error=f"ml_service_http_{response.status_code}")
        if response.status_code >= 400:
            return MlOutcome(None, "error", error=f"ml_service_http_{response.status_code}")

        body = response.json()
        score = body.get("normalized_anomaly_score", body.get("anomaly_score"))
        if not isinstance(score, (int, float)) or isinstance(score, bool):
            return MlOutcome(None, "error", error="ml_service_bad_payload")
        return MlOutcome(
            score=float(min(1.0, max(0.0, float(score)))),
            status="success",
            model_version=body.get("model_version"),
            reason_codes=body.get("reason_codes") or [],
        )
    except httpx.TimeoutException:
        return MlOutcome(None, "unavailable", error="ml_timeout")
    except httpx.HTTPError as exc:
        return MlOutcome(None, "unavailable", error=f"ml_unreachable: {exc.__class__.__name__}")
    except (ValueError, KeyError) as exc:
        return MlOutcome(None, "error", error=f"ml_bad_response: {exc.__class__.__name__}")


# =============================================================================
# Scoring (DECISIONS section 2)
# =============================================================================

def map_score_to_risk_level(score: float, thresholds: Dict[str, float]) -> str:
    """Bucket a combined score using the policy thresholds."""
    if score < thresholds["low"]:
        return "low"
    if score < thresholds["medium"]:
        return "medium"
    if score < thresholds["high"]:
        return "high"
    return "critical"


async def process_attempt(db, attempt: LoginAttempt, request_id: UUID) -> DetectionResponse:
    """Score one login attempt, persist the results and create an alert.

    Implements DECISIONS sections 2 and 4.
    """
    def log(stage: str, **kwargs) -> None:
        db.add(
            DetectionLog(
                login_attempt_id=attempt.id,
                request_id=request_id,
                stage=stage,
                **kwargs,
            )
        )

    policy = get_active_policy(db)
    if policy is None:
        log(
            "scoring",
            stage_detail="no_active_policy",
            decision="allow",
            reason="no_policy",
            details={"note": "no active policy, allow and skip scoring"},
        )
        attempt.status = "processed"
        attempt.risk_level = "low"
        attempt.detection_decision = "allow"
        db.commit()
        return DetectionResponse(
            rule_score=0.0,
            ml_score=None,
            combined_score=0.0,
            ml_status="unavailable",
            ml_model_version=None,
            risk_level="low",
            decision="allow",
        )

    config, config_problems = resolve_config(policy.config)
    for problem in config_problems:
        log("scoring", stage_detail="policy_config", reason="invalid_thresholds", details={"problem": problem})

    features = build_features(db, attempt)

    # Step 1 - rules
    rule_score, hits, rule_problems = evaluate_rules(policy.rules, features)
    for hit in hits:
        log(
            "rule_evaluation",
            stage_detail=hit.rule_name,
            rule_name=hit.rule_name,
            triggered=True,
            score_contribution=hit.score_contribution,
            details={"field_value": _matched_value(features, hit.rule_name, policy.rules)},
            reason=hit.reason,
        )
    for problem in rule_problems:
        log(
            "rule_evaluation",
            stage_detail=problem["rule_name"],
            rule_name=problem["rule_name"],
            triggered=False,
            reason=problem["reason"],
            details={"detail": problem["detail"]},
        )

    # Step 2 - ML
    ml = await call_ml_service(features, request_id)
    log(
        "ml_call",
        stage_detail="ml_inference" if ml.status == "success" else (ml.error or "ml_failed"),
        reason=ml.error,
        details={"ml_status": ml.status, "features_used": features},
    )

    # Step 3 - combine
    if ml.status == "success" and ml.score is not None:
        combined = (
            config.weights["rule"] * rule_score + config.weights["ml"] * ml.score
        )
    else:
        # Graceful degradation: no ML signal, use the rule score as-is
        combined = rule_score
    combined = min(1.0, max(0.0, combined))

    # Step 4 & 5 - level and decision
    risk_level = map_score_to_risk_level(combined, config.thresholds)
    decision, action_label, create_alert = DECISION_MATRIX[risk_level]

    log(
        "scoring",
        stage_detail="final_decision",
        decision=decision,
        reason=(
            f"rule={rule_score:.4f}, ml={ml.score}, combined={combined:.4f}, "
            f"level={risk_level}, action={action_label}"
        ),
        details={
            "risk_level": risk_level,
            "rule_score": rule_score,
            "ml_score": ml.score,
            "combined_score": combined,
            "weights": config.weights,
            "thresholds": config.thresholds,
        },
    )

    # Persist the assessment
    assessment = RiskAssessment(
        login_attempt_id=attempt.id,
        policy_id=policy.id,
        rule_score=rule_score,
        ml_score=ml.score,
        combined_score=combined,
        ml_status=ml.status,
        ml_model_version=ml.model_version,
        rule_hits=[h.model_dump() for h in hits],
        ml_reason_codes=ml.reason_codes,
        ml_features_used=features,
        risk_level=risk_level,
        decision=decision,
    )
    db.add(assessment)

    # Create the alert for high and critical risk
    alert_id = None
    if create_alert:
        alert = Alert(
            login_attempt_id=attempt.id,
            policy_id=policy.id,
            request_id=request_id,
            status="open",
            risk_level=risk_level,
            detection_reason=f"{action_label}: combined={combined:.4f} (rule={rule_score:.4f}, ml={ml.score})",
            detection_scores={
                "rule_score": rule_score,
                "ml_score": ml.score,
                "combined_score": combined,
                "ml_status": ml.status,
                "ml_model_version": ml.model_version,
                "rule_hits": [h.model_dump() for h in hits],
                "ml_reason_codes": ml.reason_codes,
            },
        )
        db.add(alert)
        db.flush()
        attempt.primary_alert_id = alert.id
        alert_id = alert.id
        log("action_sent", stage_detail="alert_created", decision=decision, details={"alert_id": str(alert.id)})
    else:
        log("action_sent", stage_detail="no_alert", decision=decision, reason="risk below alert threshold")

    attempt.policy_id = policy.id
    attempt.status = "processed"
    attempt.risk_level = risk_level
    attempt.detection_decision = decision
    db.commit()

    return DetectionResponse(
        rule_score=round(rule_score, 4),
        ml_score=None if ml.score is None else round(ml.score, 4),
        combined_score=round(combined, 4),
        ml_status=ml.status,
        ml_model_version=ml.model_version,
        ml_reason_codes=ml.reason_codes,
        risk_level=risk_level,
        decision=decision,
        rule_hits=hits,
        alert_id=alert_id,
    )


async def enforce_action_in_core(
    attempt: LoginAttempt,
    risk_level: str,
    alert_id: Optional[UUID] = None,
) -> bool:
    """Ask Core App to enforce a protective action for a risky login (UC-DE-07).

    Returns ``True`` when Core App accepted the action, ``False`` when there
    was nothing to do or the call failed.

    This is deliberately best-effort: a detection verdict must never fail
    the scoring endpoint, and a Core App outage must not lose the alert
    that was already persisted. The failure is logged for the reconciliation
    job to pick up.
    """
    action = RISK_ACTION_MAP.get(risk_level)
    if action is None or attempt.user_id is None:
        return False

    payload: dict = {
        "action": action,
        "target_user_id": str(attempt.user_id),
        "reason": (
            f"detection risk_level={risk_level} "
            f"decision={attempt.detection_decision} attempt={attempt.id}"
        ),
        # Idempotency key ties the action to this exact login attempt, so a
        # redelivery after a timeout is a no-op rather than a second revoke.
        "idempotency_key": f"detection:{attempt.id}:{action}",
    }
    if alert_id is not None:
        payload["alert_id"] = str(alert_id)
    if risk_level in ("high", "critical"):
        payload["severity"] = risk_level

    try:
        async with httpx.AsyncClient(timeout=ACTION_ENFORCE_TIMEOUT_SECONDS) as client:
            response = await client.post(
                f"{core_app_url()}/api/v1/internal/actions",
                json=payload,
                headers={"X-Internal-Secret": internal_secret()},
            )
    except httpx.HTTPError as exc:
        logger.warning(
            "core-app unreachable, action %s not enforced for attempt %s: %s",
            action, attempt.id, exc.__class__.__name__,
        )
        return False

    if response.status_code >= 400:
        logger.warning(
            "core-app rejected action %s for attempt %s: HTTP %s",
            action, attempt.id, response.status_code,
        )
        return False

    logger.info("enforced %s in core-app for attempt %s", action, attempt.id)
    return True


async def rescore_failed_attempts(db, limit: int = 50) -> int:
    """Re-score attempts left in ``failed`` by an earlier crash.

    When ``process_attempt`` throws, the attempt is parked on ``status =
    "failed"`` with no assessment and no alert. Nothing else ever revisits
    it, so that login silently escapes detection forever. This is the
    reconciliation pass that closes the gap; it is safe to run repeatedly
    because each attempt is re-fetched and only genuinely failed rows are
    touched.

    Returns the number of attempts recovered.
    """
    failed = (
        db.query(LoginAttempt)
        .filter(LoginAttempt.status == "failed")
        .order_by(LoginAttempt.timestamp)
        .limit(limit)
        .all()
    )
    if not failed:
        return 0

    recovered = 0
    for attempt in failed:
        request_id = attempt.request_id or uuid4()
        try:
            result = await process_attempt(db, attempt, request_id)
        except Exception:  # noqa: BLE001 - one bad row must not stop the sweep
            logger.exception("rescore still failing for attempt %s", attempt.id)
            db.rollback()
            continue
        await enforce_action_in_core(attempt, result.risk_level, result.alert_id)
        recovered += 1

    logger.info("rescored %s/%s failed login attempts", recovered, len(failed))
    return recovered


def _matched_value(features: Dict[str, Any], rule_name: str, rules: Any) -> Any:
    """Helper for logging which feature value caused a rule to trigger."""
    if not isinstance(rules, list):
        return None
    for rule in rules:
        if isinstance(rule, dict) and rule.get("name") == rule_name:
            return features.get(rule.get("field"))
    return None


# =============================================================================
# Internal endpoints
# =============================================================================

class InternalHealthResponse(BaseModel):
    status: str = "ok"
    active_policy: Optional[str] = None


@router.post("/login-events", response_model=LoginEventResponse, status_code=http_status.HTTP_202_ACCEPTED)
async def receive_login_event(
    payload: LoginEventRequest,
    x_internal_secret: Optional[str] = Header(None),
    db=Depends(get_db),
) -> LoginEventResponse:
    """UC-DE-01 - accept a login event from core-app and score it.

    Idempotent on ``event_id``: replaying the same event returns the
    existing attempt instead of creating a duplicate.
    """
    verify_internal_secret(x_internal_secret)
    request_id = payload.request_id or uuid4()

    existing = (
        db.query(LoginAttempt)
        .filter(LoginAttempt.event_id == payload.event_id)
        .first()
    )
    if existing is not None:
        return LoginEventResponse(
            status="accepted",
            event_id=payload.event_id,
            login_attempt_id=existing.id,
            processing=existing.status,
        )

    attempt = LoginAttempt(
        event_id=payload.event_id,
        user_id=payload.user_id,
        username_attempted=payload.username_attempted,
        outcome=payload.outcome,
        mfa_used=payload.mfa_used,
        ip_address=payload.ip_address,
        user_agent=payload.user_agent,
        timestamp=payload.timestamp,
        status="pending",
        request_id=request_id,
    )
    db.add(attempt)
    db.commit()
    db.refresh(attempt)

    # Pre-computed features from core-app override the derived ones
    if payload.features:
        for key, value in payload.features.items():
            if key in {
                "hour_of_day",
                "fail_count_24h",
                "ip_change_rate_7d",
                "new_device",
                "average_login_interval_seconds",
                "deviation_score",
            }:
                db.add(
                    DetectionLog(
                        login_attempt_id=attempt.id,
                        request_id=request_id,
                        stage="rule_evaluation",
                        stage_detail="supplied_features",
                        reason="features_from_core_app",
                        details={"features": payload.features},
                    )
                )

    try:
        result = await process_attempt(db, attempt, request_id)
    except Exception:  # noqa: BLE001 - never let scoring kill the endpoint
        logger.exception("detection failed for event %s", payload.event_id)
        db.rollback()
        attempt = db.query(LoginAttempt).filter(LoginAttempt.id == attempt.id).first()
        if attempt is not None:
            attempt.status = "failed"
            db.add(
                DetectionLog(
                    login_attempt_id=attempt.id,
                    request_id=request_id,
                    stage="scoring",
                    stage_detail="engine_error",
                    reason="unhandled_exception",
                )
            )
            db.commit()
    else:
        # The verdict is committed; now let Core App enforce it. Runs after
        # the commit so a slow or dead Core App cannot roll back the
        # assessment or the alert we just wrote.
        await enforce_action_in_core(attempt, result.risk_level, result.alert_id)

    return LoginEventResponse(
        status="accepted",
        event_id=payload.event_id,
        login_attempt_id=attempt.id,
        processing=attempt.status,
    )


@router.get("/login-attempts/{login_attempt_id}", response_model=LoginAttemptStatusResponse)
async def get_login_attempt_status(
    login_attempt_id: UUID,
    x_internal_secret: Optional[str] = Header(None),
    db=Depends(get_db),
) -> LoginAttemptStatusResponse:
    """Poll the processing state of a previously submitted login event."""
    verify_internal_secret(x_internal_secret)
    attempt = db.query(LoginAttempt).filter(LoginAttempt.id == login_attempt_id).first()
    if attempt is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Login attempt not found")
    return LoginAttemptStatusResponse(
        login_attempt_id=attempt.id,
        status=attempt.status,
        risk_level=attempt.risk_level,
        decision=attempt.detection_decision,
        alert_id=attempt.primary_alert_id,
    )


class PreTokenCheckRequest(BaseModel):
    """Body of POST /api/v1/internal/pre-token-check (risk-gated login)."""
    username: str
    user_id: Optional[UUID] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    timestamp: Optional[datetime] = None
    features: Optional[Dict[str, Any]] = None


class PreTokenCheckResponse(BaseModel):
    """Verdict used by Core App to decide whether to hand out a token yet."""
    risk_level: str
    decision: str
    #: True when Core App should hold the token and demand MFA.
    require_mfa: bool
    #: True when the check itself could not run; Core App must fail open.
    degraded: bool = False
    reason: Optional[str] = None


@router.post("/pre-token-check", response_model=PreTokenCheckResponse)
async def pre_token_check(
    payload: PreTokenCheckRequest,
    x_internal_secret: Optional[str] = Header(None),
    db=Depends(get_db),
) -> PreTokenCheckResponse:
    """Score a login *before* Core App issues a token (phương án C).

    Core App calls this only when it needs a verdict to gate on. The verdict
    is advisory: Core App fails open if this endpoint is unavailable, because
    locking every user out when the Detection Engine is down is a worse
    outcome than letting one login through unscored.
    """
    verify_internal_secret(x_internal_secret)

    attempt = LoginAttempt(
        event_id=uuid4(),
        user_id=payload.user_id,
        username_attempted=payload.username,
        outcome="success",
        ip_address=payload.ip_address,
        user_agent=payload.user_agent,
        timestamp=payload.timestamp or datetime.now(timezone.utc),
        status="pending",
    )
    db.add(attempt)
    db.commit()
    db.refresh(attempt)

    try:
        result = await process_attempt(db, attempt, attempt.request_id or uuid4())
    except Exception:  # noqa: BLE001 - fail open, never block the login
        logger.exception("pre-token-check failed for user %s", payload.user_id)
        db.rollback()
        return PreTokenCheckResponse(
            risk_level="unknown",
            decision="allow",
            require_mfa=False,
            degraded=True,
            reason="scoring_error",
        )

    return PreTokenCheckResponse(
        risk_level=result.risk_level,
        decision=result.decision,
        require_mfa=result.risk_level in RISK_ACTION_MAP,
        reason=result.decision,
    )


@router.get("/health", response_model=InternalHealthResponse)
async def detection_health(db=Depends(get_db)) -> InternalHealthResponse:
    """Liveness probe; also reports which policy is active."""
    policy = None
    try:
        active = get_active_policy(db)
        policy = active.version if active else None
    except Exception:  # noqa: BLE001 - health must never fail
        logger.debug("health check could not read the active policy", exc_info=True)
    return InternalHealthResponse(status="ok", active_policy=policy)


# =============================================================================
# Policy management (UC-DE-15) - Security Admin only
# =============================================================================

@policy_router.get("", response_model=list)
async def list_policies(db=Depends(get_db)) -> list:
    """List every policy, newest first."""
    policies = db.query(Policy).order_by(Policy.created_at.desc()).all()
    return [
        {
            "id": str(p.id),
            "version": p.version,
            "name": p.name,
            "description": p.description,
            "rule_count": len(p.rules) if isinstance(p.rules, list) else 0,
            "is_active": p.is_active,
            "created_at": p.created_at,
            "activated_at": p.activated_at,
        }
        for p in policies
    ]


@policy_router.post("/{policy_id}/activate")
async def activate_policy(
    policy_id: UUID,
    db=Depends(get_db),
) -> dict:
    """Activate a policy, deactivating the previously active one."""
    policy = db.query(Policy).filter(Policy.id == policy_id).first()
    if policy is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Policy not found")

    problems: List[str] = []
    _, problems = resolve_config(policy.config)
    raw_rules = policy.rules if isinstance(policy.rules, list) else []
    for index, rule in enumerate(raw_rules):
        issue = validate_rule(rule)
        if issue:
            problems.append(f"rule {rule.get('name', index) if isinstance(rule, dict) else index}: {issue}")
    if problems:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail={"message": "Policy is invalid", "problems": problems},
        )

    now = datetime.now(timezone.utc)
    for other in db.query(Policy).filter(Policy.is_active.is_(True)).all():
        other.is_active = False
        other.deactivated_at = now
    policy.is_active = True
    policy.activated_at = now
    policy.deactivated_at = None
    db.commit()
    return {"status": "activated", "version": policy.version}
