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
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as OrmSession

from app.db import get_detection_db
from app.internal_auth import get_internal_secret, InternalAuthConfigurationError, verify_internal_secret
from app import internal_client
from app.models import Alert, AlertTimeline, DetectionLog, LoginAttempt, Policy, RiskAssessment
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
from app.authz import AuthContext, get_current_auth_context, require_roles

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
#: The constant itself lives in :mod:`app.internal_client`, which owns the
#: shared Core action boundary.
ACTION_ENFORCE_TIMEOUT_SECONDS = internal_client.ACTION_ENFORCE_TIMEOUT_SECONDS

#: Risk level -> (decision, action label, create_alert)
DECISION_MATRIX = {
    "low": ("allow", "ALLOW", False),
    "medium": ("allow", "ALLOW_LOG", False),
    "high": ("challenge", "REQUIRE_MFA", True),
    "critical": ("block", "BLOCK_ALERT", True),
}


def ml_service_url() -> str:
    """Base URL of the ML Service, without trailing slash."""
    return os.getenv("ML_SERVICE_URL", "http://localhost:8002").rstrip("/")


def core_app_url() -> str:
    """Base URL of the Core App, without trailing slash.

    Re-exported from :mod:`app.internal_client` so existing importers of
    ``app.detection.core_app_url`` keep working while the implementation
    lives in one place.
    """
    return internal_client.core_app_url()


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

#: How long a device signal stays "known" for the same user.  The 30-day
#: window is the canonical device-history window of the project (it matches
#: the trusted-device TTL) and is documented in
#: docs/DECISIONS-DETECTION-v3.3.md.
DEVICE_HISTORY_WINDOW_DAYS = 30

#: Values of ``device_signal_source``.  This is Detection-side LOGGING
#: metadata only - it is NOT one of the 6 ML features and must never enter
#: the ML feature vector.
DEVICE_SIGNAL_FINGERPRINT = "fingerprint"
DEVICE_SIGNAL_USER_AGENT_PROXY = "user_agent_proxy"
DEVICE_SIGNAL_UNAVAILABLE = "unavailable"


def build_features(db, attempt: LoginAttempt) -> Dict[str, Any]:
    """Derive the 6 features a rule may reference from the login history.

    The returned dictionary contains EXACTLY the 6 canonical ML features, in
    the canonical order.  Device-signal provenance is reported separately by
    :func:`device_signal_source` so that it can be logged without polluting
    the ML feature vector.
    """
    now = attempt.timestamp or datetime.now(timezone.utc)
    utc_now = now.astimezone(timezone.utc) if now.tzinfo is not None else now
    features: Dict[str, Any] = {
        "hour_of_day": utc_now.hour,
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
            LoginAttempt.timestamp < now,
            LoginAttempt.outcome == "failure",
        )
        .count()
    )
    features["fail_count_24h"] = failures

    # Current-IP novelty over prior 7-day history (PROJECT_DEFINED_RBA_ADAPTATION)
    week_attempts = (
        db.query(LoginAttempt)
        .filter(
            LoginAttempt.user_id == attempt.user_id,
            LoginAttempt.timestamp >= week_ago,
            LoginAttempt.timestamp < now,
        )
        .all()
    )
    if week_attempts and attempt.ip_address:
        current_ip_count = sum(a.ip_address == attempt.ip_address for a in week_attempts)
        features["ip_change_rate_7d"] = min(
            1.0, max(0.0, 1.0 - current_ip_count / len(week_attempts))
        )

    # New device: fingerprint-first, User-Agent proxy as fallback.
    features["new_device"] = _compute_new_device(db, attempt, now)

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


def _compute_new_device(db, attempt: LoginAttempt, now: datetime) -> bool:
    """Decide device novelty for one attempt (fingerprint-first).

    Resolution order:

    1. No user -> not a new device (there is no device history to compare).
    2. A device fingerprint is present -> the fingerprint is compared against
       the user's prior fingerprints in the device-history window.  The
       attempt is a new device when that fingerprint was never seen before.
    3. No fingerprint but a User-Agent is present -> the exact User-Agent is
       used as a PROXY for the device identity.
    4. Neither -> the signal is unavailable and the attempt is not new.

    In every case the history window is ``[now - 30 days, now)`` and the
    current event is excluded from the history.
    """
    if not attempt.user_id:
        return False

    window_start = now - timedelta(days=DEVICE_HISTORY_WINDOW_DAYS)

    if attempt.device_fingerprint:
        known_fingerprints = {
            row[0]
            for row in db.query(LoginAttempt.device_fingerprint)
            .filter(
                LoginAttempt.user_id == attempt.user_id,
                LoginAttempt.timestamp >= window_start,
                LoginAttempt.timestamp < now,
                LoginAttempt.device_fingerprint.isnot(None),
            )
            .distinct()
            .all()
        }
        return attempt.device_fingerprint not in known_fingerprints

    if attempt.user_agent:
        known_agents = {
            row[0]
            for row in db.query(LoginAttempt.user_agent)
            .filter(
                LoginAttempt.user_id == attempt.user_id,
                LoginAttempt.timestamp >= window_start,
                LoginAttempt.timestamp < now,
                LoginAttempt.user_agent.isnot(None),
            )
            .distinct()
            .all()
        }
        return attempt.user_agent not in known_agents

    return False


def device_signal_source(attempt: LoginAttempt) -> str:
    """Report which device signal produced ``new_device``.

    This is Detection-side contextual evidence for logging.  It is NOT an ML
    feature and is never part of the 6-feature vector sent to the ML Service.
    """
    if not attempt.user_id:
        return DEVICE_SIGNAL_UNAVAILABLE
    if attempt.device_fingerprint:
        return DEVICE_SIGNAL_FINGERPRINT
    if attempt.user_agent:
        return DEVICE_SIGNAL_USER_AGENT_PROXY
    return DEVICE_SIGNAL_UNAVAILABLE


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


async def call_ml_service(
    features: Dict[str, Any],
    request_id: UUID,
    timeout: float = ML_TIMEOUT_SECONDS,
) -> MlOutcome:
    """POST /api/v1/internal/ml/score with a 5s timeout and safe fallback.

    ``timeout`` defaults to the canonical 5 seconds.  The pre-token gate
    passes a smaller budget because Core abandons the gate after 3 seconds
    (DECISIONS section 10.6); 5 seconds remains the ceiling.

    Failure handling follows the contract (CONTRACT_DETECTION_ML section F):

    * timeout or unreachable  -> ``ml_status = "unavailable"``
    * HTTP >= 400, a malformed body, an out-of-range score or
      ``model_status = "error"`` -> ``ml_status = "error"``

    In every failure case the caller falls back to ``combined_score =
    rule_score``, so the login pipeline is never blocked by a dead ML.
    """
    url = f"{ml_service_url()}/api/v1/internal/ml/score"
    payload = {
        "request_id": str(request_id),
        "features": {k: v for k, v in features.items() if v is not None},
    }
    try:
        headers = {"X-Internal-Secret": get_internal_secret()}
    except InternalAuthConfigurationError:
        return MlOutcome(None, "unavailable", error="internal_auth_not_configured")
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                url,
                json=payload,
                headers=headers,
            )
        if response.status_code >= 500:
            return MlOutcome(None, "error", error=f"ml_service_http_{response.status_code}")
        if response.status_code >= 400:
            return MlOutcome(None, "error", error=f"ml_service_http_{response.status_code}")

        body = response.json()
        if not isinstance(body, dict):
            return MlOutcome(None, "error", error="ml_service_bad_payload")

        # ``model_status = "error"`` means the model itself is unavailable.
        # The contract (section H) requires a rule-only fallback in that
        # case, even when a score happens to be present in the body.
        model_status = body.get("model_status")
        if model_status == "error":
            return MlOutcome(None, "error", error="ml_model_status_error")

        score = body.get("normalized_anomaly_score", body.get("anomaly_score"))
        if not isinstance(score, (int, float)) or isinstance(score, bool):
            return MlOutcome(None, "error", error="ml_service_bad_payload")
        score = float(score)
        if not 0.0 <= score <= 1.0:
            # The contract pins the score to [0, 1].  A value outside that
            # range is a broken contract, not a score to silently clamp:
            # clamping would hide the fault and still move the verdict.
            return MlOutcome(None, "error", error="ml_service_score_out_of_range")

        return MlOutcome(
            score=score,
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


async def process_attempt(
    db,
    attempt: LoginAttempt,
    request_id: UUID,
    *,
    persist: bool = True,
) -> DetectionResponse:
    """Score one login attempt, persist the results and create an alert.

    Implements DECISIONS sections 2 and 4.

    ``persist=False`` scores the attempt WITHOUT writing an assessment, an
    alert or a lifecycle change.  That mode exists for the pre-token gate
    (section 10): Core asks for a verdict *before* it emits the canonical
    LoginEvent, so the gate must not create a second
    ``login_attempts`` row, a second ``risk_assessments`` row or a second
    alert for the same login.  The later ``/login-events`` delivery performs
    the real, persisted scoring exactly once.

    The function is idempotent for a given attempt: the assessment is
    updated in place (it is 1:1 with the attempt) and an existing alert is
    reused instead of duplicated.  Re-scoring an attempt therefore never
    produces a second alert or a second destructive Core action.
    """
    def log(stage: str, **kwargs) -> None:
        if not persist:
            return
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
        if persist:
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
    # Detection-side logging metadata.  NOT part of the 6-feature ML vector:
    # it only records which device signal produced ``new_device``.
    signal_source = device_signal_source(attempt)

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
        details={
            "ml_status": ml.status,
            "features_used": features,
            "device_signal_source": signal_source,
        },
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

    # Persist the assessment.  ``risk_assessments`` is 1:1 with
    # ``login_attempts`` (uq_risk_assessment_login), so a re-score updates
    # the existing row instead of violating the constraint.  That keeps the
    # "one attempt -> exactly one assessment" invariant even when the rescore
    # sweep revisits an attempt that was partially processed.
    #
    # A non-persisted run (the pre-token gate) writes nothing at all: the
    # attempt is transient, so an assessment pointing at it would violate
    # the foreign key.
    if persist:
        existing_assessment = (
            db.query(RiskAssessment)
            .filter(RiskAssessment.login_attempt_id == attempt.id)
            .first()
        )
        if existing_assessment is None:
            existing_assessment = RiskAssessment(
                login_attempt_id=attempt.id,
                policy_id=policy.id,
            )
            db.add(existing_assessment)
        existing_assessment.policy_id = policy.id
        existing_assessment.rule_score = rule_score
        existing_assessment.ml_score = ml.score
        existing_assessment.combined_score = combined
        existing_assessment.ml_status = ml.status
        existing_assessment.ml_model_version = ml.model_version
        existing_assessment.rule_hits = [h.model_dump() for h in hits]
        existing_assessment.ml_reason_codes = ml.reason_codes
        existing_assessment.ml_features_used = features
        existing_assessment.risk_level = risk_level
        existing_assessment.decision = decision

    # Create the alert for high and critical risk.
    #
    # The alert is created only when the attempt does not already have one.
    # The re-score sweep revisits attempts that a previous run may have
    # alerted on before it crashed; without this check a re-score would
    # produce a second alert - and a second destructive Core action - for
    # a single login.
    alert_id = None
    existing_alert = (
        db.query(Alert)
        .filter(Alert.login_attempt_id == attempt.id)
        .first()
    )
    if existing_alert is not None:
        alert_id = existing_alert.id
        attempt.primary_alert_id = existing_alert.id
        log(
            "action_sent",
            stage_detail="no_alert",
            decision=decision,
            reason="alert_already_exists",
            details={"alert_id": str(existing_alert.id)},
        )
    elif create_alert and persist:
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
        # The alert timeline is the SOC's audit trail.  A pipeline-created
        # alert must start its own trail, otherwise the first timeline
        # entry claims the analyst opened an alert that Detection opened.
        db.add(
            AlertTimeline(
                alert_id=alert.id,
                event_type="created",
                actor_type="system",
                new_value="open",
                comment=(
                    f"Alert created automatically by the Detection Engine "
                    f"(risk_level={risk_level}, combined={combined:.4f})."
                ),
            )
        )
        log("action_sent", stage_detail="alert_created", decision=decision, details={"alert_id": str(alert.id)})
    elif not create_alert:
        log("action_sent", stage_detail="no_alert", decision=decision, reason="risk below alert threshold")

    if persist:
        attempt.policy_id = policy.id
        attempt.status = "processed"
        attempt.risk_level = risk_level
        attempt.detection_decision = decision
        db.commit()
    else:
        # Nothing was written: the assessment, the alert and the lifecycle
        # change are all skipped in a non-persisted run.  Roll back so the
        # session is clean for the caller's next use.
        db.rollback()

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
    db=None,
) -> bool:
    """Ask Core App to enforce a protective action for a risky login (UC-DE-07).

    Returns ``True`` when Core App accepted the action, ``False`` when there
    was nothing to do or the call failed.

    This is deliberately best-effort: a detection verdict must never fail
    the scoring endpoint, and a Core App outage must not lose the alert
    that was already persisted. The failure is logged for the reconciliation
    job to pick up.

    The HTTP call itself lives in :mod:`app.internal_client`, which is
    shared with the SOC alert workflow so both Detection entry points use
    exactly one implementation of the Core action boundary.

    When ``db`` is given, the outcome is recorded in ``detection_logs``
    (stage ``action_sent``) so that a failed enforcement is observable
    instead of only appearing in the application log.
    """
    action = RISK_ACTION_MAP.get(risk_level)
    if action is None or attempt.user_id is None:
        return False

    # Idempotency key ties the action to this exact login attempt, so a
    # redelivery after a timeout is a no-op rather than a second revoke.
    idempotency_key = f"detection:{attempt.id}:{action}"
    reason = (
        f"detection risk_level={risk_level} "
        f"decision={attempt.detection_decision} attempt={attempt.id}"
    )
    severity = risk_level if risk_level in ("high", "critical") else None

    outcome = await internal_client.enforce_action_in_core_detailed(
        action,
        attempt.user_id,
        reason,
        idempotency_key=idempotency_key,
        alert_id=alert_id,
        severity=severity,
        detected_at=attempt.timestamp,
    )

    if db is not None:
        _record_action_outcome(
            db,
            attempt=attempt,
            request_id=attempt.request_id,
            action=action,
            risk_level=risk_level,
            enforced=outcome.enforced,
            error=outcome.error,
            alert_id=alert_id,
        )

    return outcome.enforced


def _record_action_outcome(
    db,
    *,
    attempt: LoginAttempt,
    request_id,
    action: str,
    risk_level: str,
    enforced: bool,
    error: Optional[str],
    alert_id: Optional[UUID],
) -> None:
    """Record whether Core enforced the protective action.

    The verdict and the alert are already committed at this point, so a
    failure here must be recorded rather than raised: the Detection verdict
    stands and the SOC picks the alert up manually.  Writing the failure
    into ``detection_logs`` is what makes "the action was NOT enforced"
    visible to a SOC analyst reading the evidence.
    """
    try:
        db.add(
            DetectionLog(
                login_attempt_id=attempt.id,
                request_id=request_id,
                stage="action_sent",
                stage_detail=action,
                decision=attempt.detection_decision,
                reason=None if enforced else (error or "action_not_enforced"),
                details={
                    "action": action,
                    "enforced": enforced,
                    "risk_level": risk_level,
                    "alert_id": str(alert_id) if alert_id else None,
                },
            )
        )
        db.commit()
    except Exception:  # noqa: BLE001 - observability must not break scoring
        logger.exception("could not record the action outcome for attempt %s", attempt.id)
        db.rollback()


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
        await enforce_action_in_core(attempt, result.risk_level, result.alert_id, db=db)
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
    db=Depends(get_detection_db),
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
        device_fingerprint=payload.device_fingerprint,
        timestamp=payload.timestamp,
        status="pending",
        request_id=request_id,
    )
    db.add(attempt)
    try:
        db.commit()
    except IntegrityError:
        # Two deliveries of the same event raced each other.  The unique
        # constraint on ``event_id`` is the final arbiter: the loser of the
        # race reads the winner's row and returns it, so the business effect
        # stays exactly-once.
        db.rollback()
        existing = (
            db.query(LoginAttempt)
            .filter(LoginAttempt.event_id == payload.event_id)
            .first()
        )
        if existing is None:
            raise
        return LoginEventResponse(
            status="accepted",
            event_id=payload.event_id,
            login_attempt_id=existing.id,
            processing=existing.status,
        )
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
        await enforce_action_in_core(attempt, result.risk_level, result.alert_id, db=db)

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
    db=Depends(get_detection_db),
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
    db=Depends(get_detection_db),
) -> PreTokenCheckResponse:
    """Score a login *before* Core App issues a token (phương án C).

    Core App calls this only when it needs a verdict to gate on. The verdict
    is advisory: Core App fails open if this endpoint is unavailable, because
    locking every user out when the Detection Engine is down is a worse
    outcome than letting one login through unscored.

    The gate is a READ of the risk picture, not a second event.  Core emits
    the canonical LoginEvent for the same login right afterwards, through
    ``POST /api/v1/internal/login-events``, and THAT delivery is the one
    that persists the attempt, the assessment, the alert and the protective
    action.  If the gate persisted its own attempt, one login would produce
    two ``login_attempts`` rows, two ``risk_assessments`` rows and - for a
    high/critical verdict - two alerts and two destructive Core actions.

    Therefore the gate scores against a transient, in-memory attempt: the
    feature builder reads the user's real history from the Detection
    database, but nothing about the gate's own attempt is written.
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

    try:
        result = await process_attempt(
            db,
            attempt,
            attempt.request_id or uuid4(),
            persist=False,
        )
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
async def detection_health(db=Depends(get_detection_db)) -> InternalHealthResponse:
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
async def list_policies(
    ctx: AuthContext = Depends(require_roles("SECURITY_ADMIN", "SECURITY_MANAGER")),
    db=Depends(get_detection_db),
) -> list:
    """List every policy, newest first. SECURITY_ADMIN or SECURITY_MANAGER only."""
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
    ctx: AuthContext = Depends(require_roles("SECURITY_ADMIN")),
    db=Depends(get_detection_db),
) -> dict:
    """Activate a policy. SECURITY_ADMIN only.

    Only ONE policy may be active at a time.  The canonical schema enforces
    that with the partial unique index ``idx_policies_single_active``.  This
    handler additionally takes a row lock on the policy being activated and
    deactivates the current one inside the same transaction, so two
    concurrent activations cannot both believe they succeeded.
    """
    policy = (
        db.query(Policy)
        .filter(Policy.id == policy_id)
        .with_for_update()
        .first()
    )
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
    others = [
        other
        for other in db.query(Policy).filter(Policy.is_active.is_(True)).all()
        if other.id != policy.id
    ]
    for other in others:
        other.is_active = False
        other.deactivated_at = now
    if others:
        # Flush the deactivations BEFORE claiming the active slot.  The
        # partial unique index allows exactly one active policy, so the
        # UPDATE that releases the slot has to reach the database first.
        # Without this flush the ORM may order the two UPDATEs the other way
        # round and the constraint would reject the activation.
        db.flush()
    policy.is_active = True
    policy.activated_at = now
    policy.deactivated_at = None
    db.commit()
    return {"status": "activated", "version": policy.version}
