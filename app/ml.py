"""
ML Service - anomaly scoring endpoint.

Serves POST /api/v1/internal/ml/score, called by the Detection Engine
over HTTP (UC-DE-03). Canonical decisions: docs/DECISIONS-DETECTION-v3.3.md

    The feature contract is the 6 features of UC-DE-02, which are exactly the
values a detection rule may reference:

    hour_of_day, fail_count_24h, ip_change_rate_7d, new_device,
    average_login_interval_seconds, deviation_score

Until a trained model is available, scoring uses a documented heuristic
baseline. The response shape already matches the production contract so
the Detection Engine needs no change when a real model lands.

Routes (Detection Engine calls this service over HTTP):
    POST /api/v1/internal/ml/score     UC-DE-03
    GET  /api/v1/internal/ml/health    liveness + model version
    GET  /api/v1/internal/ml/features  feature contract
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Header, HTTPException, status as http_status
from pydantic import BaseModel, Field

from app.schemas import DetectionFeatureVector

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/internal", tags=["ml-internal"])

#: Anomaly decision boundary
ANOMALY_THRESHOLD = 0.5

#: The 6 features, in the order the Detection Engine sends them
FEATURE_FIELDS = (
    "hour_of_day",
    "fail_count_24h",
    "ip_change_rate_7d",
    "new_device",
    "average_login_interval_seconds",
    "deviation_score",
)


def internal_secret() -> str:
    return os.getenv("INTERNAL_SECRET", "changeme-in-production")


def verify_internal_secret(x_internal_secret: Optional[str]) -> None:
    if not x_internal_secret or x_internal_secret != internal_secret():
        raise HTTPException(
            status_code=http_status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing X-Internal-Secret",
        )


# =============================================================================
# Request / response contract
# =============================================================================

class MlScoreRequest(BaseModel):
    """Body of POST /api/v1/internal/ml/score."""

    request_id: Optional[UUID] = None
    features: DetectionFeatureVector


class MlScoreResponse(BaseModel):
    """Response of POST /api/v1/internal/ml/score.

    ``normalized_anomaly_score`` keeps the name from the ML team API
    contract. The Detection Engine stores it as ``ml_score``.
    """

    request_id: Optional[UUID] = None
    normalized_anomaly_score: float = Field(..., ge=0.0, le=1.0)
    is_anomaly: bool
    model_version: str
    reason_codes: List[str] = []
    model_status: str = "ready"
    processing_time_ms: Optional[int] = None


# =============================================================================
# Heuristic baseline model
# =============================================================================

class HeuristicAnomalyModel:
    """Documented baseline used until a trained model is registered."""

    MODEL_NAME = "sentinel-heuristic-baseline"
    MODEL_VERSION = "v0.1-heuristic"

    def predict(self, features: Dict[str, Any]) -> tuple[float, List[str]]:
        """Return (normalized_anomaly_score, reason_codes)."""
        score = 0.05
        reasons: List[str] = []

        def bump(candidate: float, reason: str) -> None:
            nonlocal score
            if candidate > score:
                score = candidate
            if reason not in reasons:
                reasons.append(reason)

        hour = features.get("hour_of_day")
        if hour is not None and (hour < 6 or hour >= 23):
            bump(0.45, "unusual_time")

        failures = features.get("fail_count_24h")
        if failures is not None:
            if failures >= 5:
                bump(0.85, "high_fail_count")
            elif failures >= 3:
                bump(0.55, "multiple_failures")

        ip_change = features.get("ip_change_rate_7d")
        if ip_change is not None and ip_change > 0.5:
            bump(0.40, "frequent_ip_change")

        if features.get("new_device"):
            bump(0.30, "new_device")

        interval = features.get("average_login_interval_seconds")
        deviation = features.get("deviation_score")
        if deviation is not None:
            if deviation >= 0.70:
                bump(0.65, "high_deviation")
            elif deviation >= 0.40:
                bump(0.35, "moderate_deviation")
        if interval is not None and interval == 0:
            bump(0.15, "first_login")

        return min(1.0, max(0.0, score)), reasons

    def get_version(self) -> str:
        return self.MODEL_VERSION


_model: Optional[HeuristicAnomalyModel] = None


def get_ml_model() -> HeuristicAnomalyModel:
    global _model
    if _model is None:
        _model = HeuristicAnomalyModel()
    return _model


# =============================================================================
# Endpoints
# =============================================================================

@router.post("/ml/score", response_model=MlScoreResponse)
async def score(
    payload: MlScoreRequest,
    x_internal_secret: Optional[str] = Header(None),
) -> MlScoreResponse:
    """UC-DE-03 - score a login event for anomaly likelihood."""
    verify_internal_secret(x_internal_secret)
    import time

    started = time.perf_counter()
    features = payload.features.model_dump(exclude_none=True)
    score_value, reason_codes = get_ml_model().predict(features)
    elapsed_ms = int((time.perf_counter() - started) * 1000)

    return MlScoreResponse(
        request_id=payload.request_id or uuid4(),
        normalized_anomaly_score=score_value,
        is_anomaly=score_value >= ANOMALY_THRESHOLD,
        model_version=get_ml_model().get_version(),
        reason_codes=reason_codes,
        model_status="ready",
        processing_time_ms=elapsed_ms,
    )


@router.get("/ml/health")
async def ml_health() -> dict:
    """Liveness probe reporting which model is loaded."""
    try:
        model = get_ml_model()
        return {
            "status": "ok",
            "model_name": model.MODEL_NAME,
            "model_version": model.get_version(),
            "anomaly_threshold": ANOMALY_THRESHOLD,
        }
    except Exception:  # noqa: BLE001 - health must never fail
        logger.exception("ml health check failed")
        return {
            "status": "degraded",
            "model_name": None,
            "model_version": None,
            "anomaly_threshold": None,
        }


@router.get("/ml/features")
async def feature_contract() -> dict:
    """Publish the feature contract so the Detection Engine can align."""
    return {
        "version": "3.3",
        "features": list(FEATURE_FIELDS),
        "anomaly_threshold": ANOMALY_THRESHOLD,
        "response_field": "normalized_anomaly_score",
        "description": (
            "UC-DE-02 feature contract. Rules in policies.rules may only "
            "reference these 6 fields."
        ),
    }
