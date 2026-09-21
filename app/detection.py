"""
Detection engine - inline risk detection with policy_versions and detection_logs.
Sync with schema-v2.sql definitions.
"""
from datetime import datetime
from typing import Optional, List
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Header, Depends
from pydantic import BaseModel

from app.db import get_db
from app.models import (
    PolicyVersion, LoginAttempt, RiskAssessment, DetectionLog,
    Alert, User, Session, PreAuthTransaction, MfaNotification
)
from app.schemas import (
    DetectionRequest, DetectionResponse, RuleHit,
    MlScoreRequest, MlScoreResponse,
    ActionRequest, ActionResponse,
    RiskLevel,
)

router = APIRouter(prefix="/internal/v1", tags=["detection"])

# Internal secret for internal endpoints
INTERNAL_SECRET = "changeme-in-production"


# =============================================================================
# Request/Response schemas (internal)
# =============================================================================

class InternalHealthResponse(BaseModel):
    status: str = "ok"


# =============================================================================
# Helpers
# =============================================================================

def verify_internal_token(x_internal_token: Optional[str]) -> bool:
    """Verify internal API token."""
    if not x_internal_token:
        return False
    return x_internal_token == INTERNAL_SECRET


def get_active_policy(db) -> Optional[PolicyVersion]:
    """Get the currently active policy version."""
    return db.query(PolicyVersion).filter(
        PolicyVersion.is_active == True
    ).first()


def map_score_to_risk_level(score: float) -> str:
    """Map combined score to risk level."""
    if score < 0.2:
        return "low"
    elif score < 0.5:
        return "medium"
    elif score < 0.8:
        return "high"
    else:
        return "critical"


def get_decision(risk_level: str) -> str:
    """Map risk level to decision."""
    if risk_level == "critical":
        return "block"
    elif risk_level == "high":
        return "block"
    elif risk_level == "medium":
        return "challenge"
    else:
        return "allow"


def evaluate_rules(rules_json: dict, features: dict) -> tuple[float, List[dict]]:
    """
    Evaluate detection rules against features.
    Returns (combined_rule_score, rule_hits).
    """
    if not rules_json or "rules" not in rules_json:
        return 0.0, []

    rules = rules_json.get("rules", [])
    enabled_rules = [r for r in rules if r.get("enabled", True)]

    if not enabled_rules:
        return 0.0, []

    rule_scores = []
    hits = []

    for rule in enabled_rules:
        score = evaluate_single_rule(rule, features)
        if score > 0:
            rule_scores.append(score)
            hits.append({
                "rule_name": rule.get("name", "unknown"),
                "rule_id": rule.get("name"),  # Using name as ID for now
                "score": score,
                "reason": rule.get("description", ""),
            })

    # Combined rule score: max of all hit rules
    combined = max(rule_scores) if rule_scores else 0.0
    return combined, hits


def evaluate_single_rule(rule: dict, features: dict) -> float:
    """
    Evaluate a single rule against features.
    Returns score 0.0-1.0 if rule triggered, 0.0 otherwise.
    """
    rule_name = rule.get("name", "")
    conditions = rule.get("conditions", {})
    base_score = rule.get("score", 0.5)

    # Geo block rule
    if rule_name == "geo_block":
        blocked_countries = conditions.get("countries", [])
        ip_country = features.get("ip_country", "")
        if ip_country in blocked_countries:
            return base_score
        return 0.0

    # New country rule
    if rule_name == "new_country":
        # TODO: Check user's login history for country
        # For now, return 0 (placeholder)
        return 0.0

    # ASN reputation rule
    if rule_name == "asn_reputation":
        min_rep = conditions.get("min_reputation", 0.3)
        asn_rep = features.get("asn_reputation", 1.0)
        if asn_rep < min_rep:
            return base_score
        return 0.0

    # Failed attempts rule
    if rule_name == "failed_attempts":
        threshold = conditions.get("threshold", 3)
        failed_1h = features.get("failed_attempts_1h", 0)
        failed_24h = features.get("failed_attempts_24h", 0)
        if failed_1h >= threshold or failed_24h >= threshold * 2:
            return base_score
        return 0.0

    # Unusual hour rule
    if rule_name == "unusual_hour":
        hour_range = conditions.get("hour_range", [0, 6])
        login_hour = features.get("login_hour", 12)
        if hour_range[0] <= login_hour <= hour_range[1]:
            return base_score
        return 0.0

    # Default: no match
    return 0.0


def ml_score(features: dict) -> tuple[float, str, Optional[str]]:
    """
    Compute ML anomaly score.
    Returns (anomaly_score, ml_status, model_version).
    
    In v1, this is a stub that returns default values.
    Real implementation would call the ML model.
    """
    # Placeholder: in production, this would call the ML model
    # For now, return a dummy score based on features
    ml_status = "unavailable"
    model_version = None

    # Calculate a dummy anomaly score based on features
    # In reality, this would be ML inference
    anomaly_score = 0.1  # Default low score

    # Simple heuristic as placeholder
    if features.get("failed_attempts_1h", 0) > 5:
        anomaly_score = 0.8
    elif features.get("asn_reputation", 1.0) < 0.2:
        anomaly_score = 0.7
    elif features.get("geo_velocity_kmh", 0) > 1000:
        anomaly_score = 0.6

    return anomaly_score, ml_status, model_version


# =============================================================================
# Endpoints
# =============================================================================

@router.post("/detect", response_model=dict)
async def detect(
    request: DetectionRequest,
    x_internal_token: Optional[str] = Header(None),
    db=Depends(get_db),
) -> dict:
    """
    Perform inline risk detection for a login attempt.

    1. Load active policy version
    2. Evaluate detection rules → rule_score
    3. Call ML scoring → anomaly_score, ml_score
    4. Combine scores with weights → combined_score
    5. Map to risk_level → decision
    6. Create alert if high/critical risk
    7. Log all detection steps to detection_logs
    """
    if not verify_internal_token(x_internal_token):
        raise HTTPException(status_code=401, detail="Invalid internal token")

    request_id = uuid4()
    now = datetime.utcnow()

    # Extract features
    features = request.detection_features or {}
    if not features:
        features = {
            "login_hour": now.hour,
            "login_day": now.weekday(),
            "ip_country": "",  # TODO: resolve from IP
            "ip_reputation": 1.0,
            "user_agent_family": request.user_agent or "",
            "asn_reputation": 1.0,
            "failed_attempts_1h": request.failed_attempts,
            "failed_attempts_24h": request.failed_attempts,
            "geo_velocity_kmh": 0.0,
            "login_streak": 0,
        }

    # 1. Load active policy
    policy = get_active_policy(db)
    if not policy:
        # No policy = allow all
        return {
            "rule_score": 0.0,
            "anomaly_score": 0.0,
            "ml_score": 0.0,
            "ml_status": "unavailable",
            "ml_model_version": None,
            "combined_score": 0.0,
            "risk_level": "low",
            "decision": "allow",
            "rule_hits": [],
            "alert_id": None,
        }

    # 2. Rule evaluation
    rule_score, rule_hits = evaluate_rules(policy.rules_json, features)

    # Log each rule evaluation
    for hit in rule_hits:
        dlog = DetectionLog(
            login_attempt_id=None,  # Will be linked later
            request_id=request_id,
            stage="rule",
            stage_detail=hit["rule_name"],
            rule_name=hit["rule_name"],
            score=hit["score"],
            decision="allow",
            reason=hit.get("reason", ""),
            details={"features": features},
        )
        db.add(dlog)

    # 3. ML scoring
    anomaly_score, ml_status, ml_model_version = ml_score(features)
    ml_score_value = anomaly_score  # Alias

    # Log ML evaluation
    dlog = DetectionLog(
        login_attempt_id=None,
        request_id=request_id,
        stage="ml",
        stage_detail="ml_inference",
        score=anomaly_score,
        decision="allow",
        details={"ml_status": ml_status, "features_used": features},
    )
    db.add(dlog)

    # 4. Combine scores
    weights = policy.weights or {"rule": 0.4, "ml": 0.6}
    w_rule = weights.get("rule", 0.4)
    w_ml = weights.get("ml", 0.6)

    if ml_status == "success":
        combined_score = w_rule * rule_score + w_ml * anomaly_score
    else:
        # ML unavailable: use only rule score
        combined_score = rule_score

    # 5. Map to risk level and decision
    thresholds = policy.thresholds or {"challenge": 0.3, "block": 0.7}
    challenge_threshold = thresholds.get("challenge", 0.3)
    block_threshold = thresholds.get("block", 0.7)

    if combined_score >= block_threshold:
        risk_level = "critical"
        decision = "block"
    elif combined_score >= challenge_threshold:
        risk_level = "high"
        decision = "block"
    else:
        risk_level = map_score_to_risk_level(combined_score)
        decision = get_decision(risk_level)

    # Log combined decision
    dlog = DetectionLog(
        login_attempt_id=None,
        request_id=request_id,
        stage="combined",
        stage_detail="final_decision",
        score=combined_score,
        decision=decision,
        reason=f"rule={rule_score}, ml={anomaly_score}, combined={combined_score}",
        details={
            "risk_level": risk_level,
            "weights": weights,
            "thresholds": thresholds,
            "rule_hits": rule_hits,
        },
    )
    db.add(dlog)

    # 6. Create alert if high/critical
    alert_id = None
    if risk_level in ("high", "critical"):
        alert = Alert(
            login_attempt_id=None,  # Will be linked to login attempt
            policy_version_id=policy.id,
            request_id=request_id,
            status="open",
            risk_level=risk_level,
            detection_reason=f"Risk level: {risk_level}, score: {combined_score:.3f}",
            detection_scores={
                "rule_score": rule_score,
                "anomaly_score": anomaly_score,
                "ml_score": ml_score_value,
                "combined_score": combined_score,
                "rule_hits": rule_hits,
            },
        )
        db.add(alert)
        db.flush()
        alert_id = alert.id

        # Log alert creation
        dlog = DetectionLog(
            login_attempt_id=None,
            request_id=request_id,
            stage="action",
            stage_detail="alert_created",
            decision=decision,
            reason=f"Alert created: {alert.id}",
        )
        db.add(dlog)

    db.commit()

    return {
        "rule_score": rule_score,
        "anomaly_score": anomaly_score,
        "ml_score": ml_score_value,
        "ml_status": ml_status,
        "ml_model_version": ml_model_version,
        "combined_score": combined_score,
        "risk_level": risk_level,
        "decision": decision,
        "rule_hits": [
            RuleHit(
                rule_name=h["rule_name"],
                rule_id=h.get("rule_id"),
                score=h["score"],
                reason=h.get("reason"),
            )
            for h in rule_hits
        ],
        "alert_id": alert_id,
    }


@router.post("/ml/score", response_model=MlScoreResponse)
async def ml_score_endpoint(
    request: MlScoreRequest,
    x_internal_token: Optional[str] = Header(None),
    db=Depends(get_db),
) -> MlScoreResponse:
    """
    Compute ML risk score for login features.

    This endpoint mirrors ml-service scoring.
    In v1, this is a stub that returns default values.
    """
    if not verify_internal_token(x_internal_token):
        raise HTTPException(status_code=401, detail="Invalid internal token")

    features = request.features.model_dump() if hasattr(request.features, 'model_dump') else request.features

    anomaly_score, ml_status, model_version = ml_score(features)

    return MlScoreResponse(
        anomaly_score=anomaly_score,
        ml_status=ml_status,
        model_version=model_version,
    )


@router.post("/actions", response_model=ActionResponse)
async def enforce_action(
    request: ActionRequest,
    x_internal_token: Optional[str] = Header(None),
    db=Depends(get_db),
) -> ActionResponse:
    """
    Enforce security action from detection engine.

    Actions:
    - REQUIRE_MFA: Set detection_mfa_once=True for target user
    - REVOKE_SESSIONS: Revoke all sessions for target user
    - LOCK_USER: Set user status to locked
    """
    if not verify_internal_token(x_internal_token):
        raise HTTPException(status_code=401, detail="Invalid internal token")

    action = request.action
    target_user_id = request.target_user_id
    reason = request.reason
    now = datetime.utcnow()

    # Find target user
    user = db.query(User).filter(User.id == target_user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if action == "REQUIRE_MFA":
        # Require MFA on next login
        user.detection_mfa_once = True
        user.admin_mfa_required = True  # Ensure MFA is required
        db.commit()

        # Log action
        dlog = DetectionLog(
            login_attempt_id=None,
            request_id=uuid4(),
            stage="action",
            stage_detail="require_mfa",
            decision="challenge",
            reason=reason,
            details={"target_user_id": str(target_user_id)},
        )
        db.add(dlog)
        db.commit()

        return ActionResponse(
            status="applied",
            action=action,
            target_user_id=target_user_id,
            details={"mfa_enabled": True},
        )

    elif action == "REVOKE_SESSIONS":
        # Revoke all sessions for target user
        revoked_count = db.query(Session).filter(
            Session.user_id == target_user_id,
            Session.revoked_at.is_(None),
        ).update({"revoked_at": now})

        db.commit()

        # Log action
        dlog = DetectionLog(
            login_attempt_id=None,
            request_id=uuid4(),
            stage="action",
            stage_detail="revoke_sessions",
            decision="block",
            reason=reason,
            details={"target_user_id": str(target_user_id), "revoked_count": revoked_count},
        )
        db.add(dlog)
        db.commit()

        return ActionResponse(
            status="applied",
            action=action,
            target_user_id=target_user_id,
            details={"revoked_sessions": revoked_count},
        )

    elif action == "LOCK_USER":
        # Lock the user account
        user.status = "locked"
        user.locked_at = now

        # Revoke all sessions
        db.query(Session).filter(
            Session.user_id == target_user_id,
            Session.revoked_at.is_(None),
        ).update({"revoked_at": now})

        db.commit()

        # Log action
        dlog = DetectionLog(
            login_attempt_id=None,
            request_id=uuid4(),
            stage="action",
            stage_detail="lock_user",
            decision="block",
            reason=reason,
            details={"target_user_id": str(target_user_id)},
        )
        db.add(dlog)
        db.commit()

        return ActionResponse(
            status="applied",
            action=action,
            target_user_id=target_user_id,
            details={"status": "locked"},
        )

    else:
        raise HTTPException(status_code=400, detail=f"Unsupported action: {action}")


@router.get("/health", response_model=InternalHealthResponse)
async def detection_health() -> InternalHealthResponse:
    """Health check for detection endpoint."""
    return InternalHealthResponse(status="ok")
