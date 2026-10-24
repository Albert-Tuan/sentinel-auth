"""
ML Service - anomaly scoring endpoint.

Serves POST /api/v1/internal/ml/score, called by the Detection Engine
over HTTP (UC-DE-03). Canonical decisions: docs/DECISIONS-DETECTION-v3.3.md

    The feature contract is the 6 features of UC-DE-02, which are exactly the
values a detection rule may reference:

    hour_of_day, fail_count_24h, ip_change_rate_7d, new_device,
    average_login_interval_seconds, deviation_score

The runtime loads a versioned sklearn/joblib bundle selected by the ML model
registry or ``ML_MODEL_PATH``. It never substitutes a handcrafted score.

Routes (Detection Engine calls this service over HTTP):
    POST /api/v1/internal/ml/score     UC-DE-03
    GET  /api/v1/internal/ml/health    liveness + model version
    GET  /api/v1/internal/ml/features  feature contract
"""
from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path
from time import perf_counter
from typing import List, Optional
from uuid import UUID

import joblib
import numpy as np
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.orm import Session

from app.db import get_db
from app.internal_auth import verify_internal_secret
from app.models import FeatureStatistic, InferenceLog, ModelVersion

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/internal", tags=["ml-internal"])

#: The 6 features, in the order the Detection Engine sends them
FEATURE_FIELDS = (
    "hour_of_day",
    "fail_count_24h",
    "ip_change_rate_7d",
    "new_device",
    "average_login_interval_seconds",
    "deviation_score",
)


# =============================================================================
# Request / response contract
# =============================================================================

class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class LoginFeatures(StrictModel):
    hour_of_day: int = Field(ge=0, le=23)
    fail_count_24h: int = Field(ge=0)
    ip_change_rate_7d: float = Field(ge=0.0, le=1.0)
    new_device: bool
    average_login_interval_seconds: int = Field(ge=0)
    deviation_score: float = Field(ge=0.0, le=1.0)


class MlScoreRequest(StrictModel):
    """Body of POST /api/v1/internal/ml/score."""

    request_id: UUID
    features: LoginFeatures


class MlScoreResponse(BaseModel):
    """Response of POST /api/v1/internal/ml/score.

    ``normalized_anomaly_score`` keeps the name from the ML team API
    contract. The Detection Engine stores it as ``ml_score``.
    """

    request_id: UUID
    normalized_anomaly_score: float = Field(..., ge=0.0, le=1.0)
    is_anomaly: bool
    model_version: str
    reason_codes: List[str] = Field(default_factory=list)
    model_status: str = "ready"
    processing_time_ms: Optional[int] = None


# =============================================================================
# Artifact runtime
# =============================================================================

REASON_CODES = (
    "unusual_hour",
    "high_fail_count",
    "new_ip",
    "new_device",
    "behavioral_deviation",
    "multiple_factors",
)


class IsolationForestRuntime:
    """Validated sklearn bundle: estimator + fitted score scaler."""

    def __init__(
        self, model, score_scaler, features: list[str], version: str,
        model_version_id: Optional[UUID] = None,
    ):
        self.model = model
        self.score_scaler = score_scaler
        self.features = features
        self.version = version
        self.model_version_id = model_version_id

    @classmethod
    def load(
        cls, path: Path, model_version_id: Optional[UUID] = None,
    ) -> "IsolationForestRuntime":
        bundle = joblib.load(path)
        if not isinstance(bundle, dict) or set(("model", "score_scaler", "features", "version")) - set(bundle):
            raise ValueError("invalid ML artifact bundle")
        if list(bundle["features"]) != list(FEATURE_FIELDS):
            raise ValueError("artifact feature order does not match canonical contract")
        if not all(hasattr(bundle["model"], method) for method in ("decision_function", "predict")):
            raise ValueError("artifact estimator lacks IsolationForest inference methods")
        if not hasattr(bundle["score_scaler"], "transform"):
            raise ValueError("artifact score scaler is not fitted")
        return cls(
            bundle["model"], bundle["score_scaler"], bundle["features"],
            str(bundle["version"]), model_version_id,
        )

    def normalize(self, oriented_scores: np.ndarray) -> np.ndarray:
        normalized = self.score_scaler.transform(np.asarray(oriented_scores).reshape(-1, 1)).ravel()
        return np.clip(normalized, 0.0, 1.0)

    def score(self, features: LoginFeatures) -> tuple[float, float, bool]:
        values = np.asarray([[getattr(features, name) for name in self.features]], dtype=np.float32)
        raw_decision = float(self.model.decision_function(values)[0])
        normalized = float(self.normalize(np.asarray([-raw_decision]))[0])
        is_anomaly = bool(self.model.predict(values)[0] == -1)
        return raw_decision, normalized, is_anomaly


_runtime: Optional[IsolationForestRuntime] = None
_runtime_path: Optional[Path] = None


def reset_runtime() -> None:
    global _runtime, _runtime_path
    _runtime = None
    _runtime_path = None


def resolve_model_source(db: Session) -> tuple[Path, Optional[UUID]]:
    registered = (
        db.query(ModelVersion)
        .filter(ModelVersion.status == "active", ModelVersion.is_production.is_(True))
        .first()
    )
    path = registered.model_path if registered else os.getenv("ML_MODEL_PATH")
    if not path:
        raise FileNotFoundError("no active ML artifact is configured")
    return Path(path), registered.id if registered else None


def resolve_model_path(db: Session) -> Path:
    return resolve_model_source(db)[0]


def get_ml_runtime(db: Session) -> IsolationForestRuntime:
    global _runtime, _runtime_path
    path, model_version_id = resolve_model_source(db)
    if _runtime is None or _runtime_path != path:
        _runtime = IsolationForestRuntime.load(path, model_version_id)
        _runtime_path = path
    else:
        _runtime.model_version_id = model_version_id
    return _runtime


def reason_codes(features: LoginFeatures) -> List[str]:
    """Contract evidence codes; these are not model feature attribution."""
    reasons = []
    if features.hour_of_day < 6 or features.hour_of_day >= 23:
        reasons.append("unusual_hour")
    if features.fail_count_24h >= 5:
        reasons.append("high_fail_count")
    if features.ip_change_rate_7d > 0.5:
        reasons.append("new_ip")
    if features.new_device:
        reasons.append("new_device")
    if features.deviation_score >= 0.7:
        reasons.append("behavioral_deviation")
    if len(reasons) >= 2:
        reasons.append("multiple_factors")
    return reasons


def refresh_feature_statistics(db: Session, since: datetime) -> int:
    """Batch feature summaries; deliberately kept off the inference hot path."""
    rows = (
        db.query(InferenceLog.features, InferenceLog.is_anomaly)
        .filter(InferenceLog.created_at >= since, InferenceLog.model_status == "ready")
        .all()
    )
    if not rows:
        return 0
    anomaly_rate = float(np.mean([row.is_anomaly for row in rows]))
    for name in FEATURE_FIELDS:
        values = np.asarray([row.features[name] for row in rows], dtype=float)
        p25, p50, p75, p95 = np.percentile(values, [25, 50, 75, 95])
        db.add(FeatureStatistic(
            feature_name=name,
            count=len(values),
            mean=float(values.mean()),
            std=float(values.std()),
            min=float(values.min()),
            max=float(values.max()),
            p25=float(p25),
            p50=float(p50),
            p75=float(p75),
            p95=float(p95),
            anomaly_rate=anomaly_rate,
        ))
    db.commit()
    return len(FEATURE_FIELDS)


# =============================================================================
# Endpoints
# =============================================================================

@router.post("/ml/score", response_model=MlScoreResponse)
async def score(
    request: Request,
    x_internal_secret: Optional[str] = Header(None),
    db: Session = Depends(get_db),
) -> MlScoreResponse:
    """UC-DE-03 - score a login event for anomaly likelihood."""
    verify_internal_secret(x_internal_secret)
    try:
        payload = MlScoreRequest.model_validate_json(await request.body())
    except (ValidationError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Invalid ML request") from exc

    started = perf_counter()
    try:
        runtime = get_ml_runtime(db)
        raw_score, score_value, is_anomaly = runtime.score(payload.features)
    except Exception as exc:
        logger.exception("ML artifact unavailable")
        db.add(InferenceLog(
            request_id=payload.request_id,
            model_version_used="unavailable",
            features=payload.features.model_dump(),
            raw_score=None,
            normalized_score=0.0,
            is_anomaly=False,
            reason_codes=[],
            model_status="error",
            processing_time_ms=int((perf_counter() - started) * 1000),
            error_message=str(exc),
        ))
        db.commit()
        raise HTTPException(status_code=503, detail="ML model unavailable") from exc

    elapsed_ms = int((perf_counter() - started) * 1000)
    reasons = reason_codes(payload.features)
    db.add(InferenceLog(
        request_id=payload.request_id,
        model_version_id=runtime.model_version_id,
        model_version_used=runtime.version,
        features=payload.features.model_dump(),
        raw_score=raw_score,
        normalized_score=score_value,
        is_anomaly=is_anomaly,
        reason_codes=reasons,
        model_status="ready",
        processing_time_ms=elapsed_ms,
    ))
    db.commit()

    return MlScoreResponse(
        request_id=payload.request_id,
        normalized_anomaly_score=score_value,
        is_anomaly=is_anomaly,
        model_version=runtime.version,
        reason_codes=reasons,
        model_status="ready",
        processing_time_ms=elapsed_ms,
    )


@router.get("/ml/health")
async def ml_health(db: Session = Depends(get_db)) -> dict:
    """Liveness probe reporting which model is loaded."""
    try:
        runtime = get_ml_runtime(db)
        return {
            "status": "ok",
            "model_version": runtime.version,
            "model_status": "ready",
        }
    except Exception:  # noqa: BLE001 - health must never fail
        logger.exception("ml health check failed")
        return {
            "status": "degraded",
            "model_version": None,
            "model_status": "error",
        }


@router.get("/ml/features")
async def feature_contract() -> dict:
    """Publish the feature contract so the Detection Engine can align."""
    return {
        "version": "3.3",
        "features": list(FEATURE_FIELDS),
        "response_field": "normalized_anomaly_score",
        "description": (
            "UC-DE-02 feature contract. Rules in policies.rules may only "
            "reference these 6 fields."
        ),
    }
