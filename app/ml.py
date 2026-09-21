"""
ML Service integration - score endpoint.
Implements anomaly detection for login attempts.

Feature Contract v2 aligned with:
- DetectionFeatureVector from app/schemas.py
- Bảng Yêu Cầu ML Service v2

Features aligned:
- login_hour, login_day: temporal features
- failed_attempts_1h, failed_attempts_24h: failure patterns
- is_known_device, is_known_ip: device/IP history
- asn_reputation, ip_reputation: reputation scores
- geo_velocity_kmh: travel speed
- login_streak: behavioral pattern
- mfa_used_recently: authentication pattern
"""
from typing import Optional, Dict, Any, List
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Header, Depends
from pydantic import BaseModel, Field

from app.db import get_db

router = APIRouter(prefix="/internal/v1/ml", tags=["ml"])


# =============================================================================
# Request/Response schemas - Aligned with ML Service v2 Document
# =============================================================================

class ScoreRequest(BaseModel):
    """ML Score Request with aligned feature vector."""
    features: Dict[str, Any] = Field(
        ...,
        description="Feature vector matching DetectionFeatureVector schema"
    )


class ScoreResponse(BaseModel):
    """ML Score Response per Feature Contract v2."""
    anomaly_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Normalized anomaly score (0-1). Higher = more anomalous."
    )
    ml_status: str = Field(
        ...,
        description="success | unavailable | error"
    )
    model_version: Optional[str] = Field(
        None,
        description="Version of model used for inference"
    )
    reason_codes: Optional[List[str]] = Field(
        default=None,
        description="Reason codes: unusual_time, new_device, high_velocity, etc."
    )


class FeatureValidationResult(BaseModel):
    """Result of feature validation."""
    valid: bool
    missing_required: List[str] = []
    invalid_type: Dict[str, str] = {}


# =============================================================================
# Feature Contract v2 - Required and Optional Features
# =============================================================================

REQUIRED_FEATURES = [
    "login_hour",
    "failed_attempts_1h",
    "failed_attempts_24h",
    "is_known_device",
]

OPTIONAL_FEATURES = [
    "login_day",
    "ip_country",
    "ip_reputation",
    "user_agent_family",
    "asn_reputation",
    "geo_velocity_kmh",
    "login_streak",
    "is_known_ip",
    "mfa_used_recently",
]

ALL_FEATURES = REQUIRED_FEATURES + OPTIONAL_FEATURES


# =============================================================================
# Feature Validation
# =============================================================================

def validate_features(features: Dict[str, Any]) -> FeatureValidationResult:
    """
    Validate feature vector against Feature Contract v2.
    Returns validation result with missing/invalid fields.
    """
    missing = []
    for feat in REQUIRED_FEATURES:
        if feat not in features:
            missing.append(feat)

    return FeatureValidationResult(
        valid=len(missing) == 0,
        missing_required=missing,
        invalid_type={}
    )


def preprocess_features(features: Dict[str, Any]) -> Dict[str, Any]:
    """
    Preprocess features: fill defaults, normalize ranges.
    Matches DetectionFeatureVector schema defaults.
    """
    processed = features.copy()

    # Fill defaults for optional features
    defaults = {
        "login_day": 0,
        "ip_reputation": 1.0,
        "asn_reputation": 1.0,
        "geo_velocity_kmh": 0.0,
        "login_streak": 0,
        "is_known_ip": True,
        "mfa_used_recently": False,
    }

    for key, default in defaults.items():
        if key not in processed:
            processed[key] = default

    # Ensure boolean conversion
    for key in ["is_known_device", "is_known_ip", "mfa_used_recently"]:
        if key in processed:
            processed[key] = bool(processed[key])

    # Ensure integer conversion for numeric features
    int_features = ["login_hour", "login_day", "failed_attempts_1h", "failed_attempts_24h", "login_streak"]
    for key in int_features:
        if key in processed and processed[key] is not None:
            try:
                processed[key] = int(processed[key])
            except (ValueError, TypeError):
                pass

    return processed


def generate_reason_codes(features: Dict[str, Any], anomaly_score: float) -> List[str]:
    """
    Generate reason codes based on features and score.
    Supports explainability for SOC investigation.
    """
    reasons = []

    # Unusual time check (hours outside 8am-8pm)
    login_hour = features.get("login_hour", 12)
    if login_hour < 6 or login_hour > 22:
        reasons.append("unusual_time")

    # New device
    if not features.get("is_known_device", True):
        reasons.append("new_device")

    # New IP
    if not features.get("is_known_ip", True):
        reasons.append("new_ip")

    # High geo velocity (impossible travel)
    geo_vel = features.get("geo_velocity_kmh", 0)
    if geo_vel > 1000:
        reasons.append("high_velocity")

    # Failed attempts
    failed_1h = features.get("failed_attempts_1h", 0)
    if failed_1h >= 3:
        reasons.append("multiple_failures")

    # Low ASN reputation
    asn_rep = features.get("asn_reputation", 1.0)
    if asn_rep < 0.3:
        reasons.append("low_asn_reputation")

    # Low IP reputation
    ip_rep = features.get("ip_reputation", 1.0)
    if ip_rep < 0.3:
        reasons.append("low_ip_reputation")

    return reasons


# =============================================================================
# ML Model (placeholder - v2)
# =============================================================================

class DummyMLModel:
    """
    Placeholder ML model for v1.
    Algorithm: Heuristic-based scoring (Isolation Forest baseline).

    In production, this would load a real model from model_registry.
    """
    MODEL_NAME = "sentinel-anomaly-v1"
    MODEL_VERSION = "1.0.0"

    # Default threshold for is_anomaly (from ML Service v2 doc)
    DEFAULT_THRESHOLD = 0.5

    def predict(self, features: Dict[str, Any]) -> tuple[float, str, List[str]]:
        """
        Predict anomaly score from features.
        Returns (anomaly_score, status, reason_codes).

        Score semantics (per ML Service v2 doc):
        - 0.0-0.2: Normal behavior (low risk)
        - 0.2-0.5: Slight anomaly (medium risk)
        - 0.5-0.8: Significant anomaly (high risk)
        - 0.8-1.0: Very anomalous (critical risk)
        """
        score = 0.1  # Default low score
        reasons = []

        # Failed attempts heuristic (strong signal)
        failed_1h = features.get("failed_attempts_1h", 0)
        if failed_1h >= 5:
            score = max(score, 0.85)
            reasons.append("multiple_failures")
        elif failed_1h >= 3:
            score = max(score, 0.55)

        # ASN reputation heuristic
        asn_rep = features.get("asn_reputation", 1.0)
        if asn_rep < 0.2:
            score = max(score, 0.75)
            reasons.append("low_asn_reputation")
        elif asn_rep < 0.5:
            score = max(score, 0.35)

        # Geo velocity heuristic (impossible travel)
        geo_vel = features.get("geo_velocity_kmh", 0)
        if geo_vel > 1000:
            score = max(score, 0.7)
            reasons.append("high_velocity")
        elif geo_vel > 500:
            score = max(score, 0.4)

        # New device
        if not features.get("is_known_device", True):
            score = max(score, 0.25)
            reasons.append("new_device")

        # New IP
        if not features.get("is_known_ip", True):
            score = max(score, 0.2)
            reasons.append("new_ip")

        # Unusual hour
        login_hour = features.get("login_hour", 12)
        if login_hour < 3 or login_hour > 23:
            if login_hour < 2 or login_hour > 24:
                score = max(score, 0.3)
                reasons.append("unusual_time")

        # IP reputation
        ip_rep = features.get("ip_reputation", 1.0)
        if ip_rep < 0.3:
            score = max(score, 0.65)

        # Low login streak (irregular pattern)
        streak = features.get("login_streak", 0)
        if streak == 0 and features.get("is_known_device", False):
            score = max(score, 0.15)

        # Ensure score is in 0-1 range
        score = min(1.0, max(0.0, score))

        return score, "success", reasons

    def is_anomaly(self, score: float) -> bool:
        """Determine if score indicates anomaly based on threshold."""
        return score >= self.DEFAULT_THRESHOLD

    def get_version(self) -> str:
        return self.MODEL_VERSION


# Global model instance
_ml_model: Optional[DummyMLModel] = None


def get_ml_model() -> DummyMLModel:
    """Get or create ML model instance."""
    global _ml_model
    if _ml_model is None:
        _ml_model = DummyMLModel()
    return _ml_model


# =============================================================================
# Endpoints - ML Service v2 aligned
# =============================================================================

@router.post("/score", response_model=ScoreResponse)
async def score(
    request: ScoreRequest,
    x_internal_token: Optional[str] = Header(None),
    db=Depends(get_db),
) -> ScoreResponse:
    """
    Compute ML anomaly score for login features.

    Implements Feature Contract v2:
    1. Validate feature vector
    2. Preprocess features
    3. Run inference
    4. Generate reason codes
    5. Return aligned response

    Feature Contract v2 aligned with:
    - 13 features total (4 required, 9 optional)
    - Returns anomaly_score, ml_status, model_version, reason_codes
    """
    # Verify internal token
    internal_secret = "changeme-in-production"
    if not x_internal_token or x_internal_token != internal_secret:
        raise HTTPException(status_code=401, detail="Invalid internal token")

    features = request.features

    # Step 1: Validate features
    validation = validate_features(features)
    if not validation.valid:
        # Still process with defaults filled, but log warning
        pass  # Continue processing with defaults

    # Step 2: Preprocess features
    processed_features = preprocess_features(features)

    try:
        model = get_ml_model()

        # Step 3: Run inference
        anomaly_score, status, reasons = model.predict(processed_features)

        # Step 4: Generate reason codes (enhance with model output)
        reason_codes = generate_reason_codes(processed_features, anomaly_score)

        # Step 5: Return aligned response
        return ScoreResponse(
            anomaly_score=anomaly_score,
            ml_status=status,
            model_version=model.get_version(),
            reason_codes=reason_codes if reason_codes else None,
        )

    except Exception as e:
        return ScoreResponse(
            anomaly_score=0.0,
            ml_status="error",
            model_version=None,
            reason_codes=None,
        )


@router.get("/health", response_model=dict)
async def ml_health() -> dict:
    """
    Health check for ML endpoint.
    Returns model status for Detection Engine monitoring.
    """
    try:
        model = get_ml_model()
        return {
            "status": "ok",
            "model_name": model.MODEL_NAME,
            "model_version": model.get_version(),
            "threshold": model.DEFAULT_THRESHOLD,
        }
    except Exception:
        return {
            "status": "degraded",
            "model_name": None,
            "model_version": None,
            "threshold": None,
        }


@router.get("/features", response_model=dict)
async def get_feature_contract() -> dict:
    """
    Get ML Feature Contract definition.
    Useful for Feature Builder alignment.
    """
    return {
        "version": "2.0",
        "required_features": REQUIRED_FEATURES,
        "optional_features": OPTIONAL_FEATURES,
        "all_features": ALL_FEATURES,
        "description": "Feature Contract v2 - Aligned with DetectionFeatureVector"
    }
