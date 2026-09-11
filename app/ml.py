"""
ML Service integration - score endpoint.
Stub implementation for v1. Real ML model would be loaded here.
Sync with schema-v2.sql definitions.
"""
from typing import Optional, Dict, Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Header, Depends
from pydantic import BaseModel

from app.db import get_db

router = APIRouter(prefix="/internal/v1/ml", tags=["ml"])


# =============================================================================
# Request/Response schemas
# =============================================================================

class ScoreRequest(BaseModel):
    features: Dict[str, Any]


class ScoreResponse(BaseModel):
    anomaly_score: float
    ml_status: str  # 'success' | 'unavailable' | 'error'
    model_version: Optional[str] = None


# =============================================================================
# ML Model (placeholder)
# =============================================================================

class DummyMLModel:
    """
    Placeholder ML model for v1.
    In production, this would load a real model from model_registry.
    """
    MODEL_NAME = "sentinel-anomaly-v1"
    MODEL_VERSION = "1.0.0"

    def predict(self, features: Dict[str, Any]) -> tuple[float, str]:
        """
        Predict anomaly score from features.
        Returns (anomaly_score, status).
        """
        # Placeholder: simple heuristic-based scoring
        score = 0.1  # Default low score

        # Failed attempts heuristic
        if features.get("failed_attempts_1h", 0) > 5:
            score = max(score, 0.8)
        elif features.get("failed_attempts_1h", 0) > 3:
            score = max(score, 0.5)

        # ASN reputation heuristic
        if features.get("asn_reputation", 1.0) < 0.2:
            score = max(score, 0.7)
        elif features.get("asn_reputation", 1.0) < 0.5:
            score = max(score, 0.3)

        # Geo velocity heuristic
        if features.get("geo_velocity_kmh", 0) > 1000:
            score = max(score, 0.6)

        # New device
        if not features.get("is_known_device", True):
            score = max(score, 0.2)

        return score, "success"

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
# Endpoints
# =============================================================================

@router.post("/score", response_model=ScoreResponse)
async def score(
    request: ScoreRequest,
    x_internal_token: Optional[str] = Header(None),
    db=Depends(get_db),
) -> ScoreResponse:
    """
    Compute ML anomaly score for login features.

    In v1, this uses a placeholder model.
    Real implementation would:
    1. Normalize features
    2. Load model from model_registry
    3. Run inference
    4. Return anomaly_score
    """
    # Verify internal token
    internal_secret = "changeme-in-production"
    if not x_internal_token or x_internal_token != internal_secret:
        raise HTTPException(status_code=401, detail="Invalid internal token")

    features = request.features

    try:
        model = get_ml_model()
        anomaly_score, status = model.predict(features)

        return ScoreResponse(
            anomaly_score=anomaly_score,
            ml_status=status,
            model_version=model.get_version(),
        )

    except Exception as e:
        return ScoreResponse(
            anomaly_score=0.0,
            ml_status="error",
            model_version=None,
        )


@router.get("/health", response_model=dict)
async def ml_health() -> dict:
    """Health check for ML endpoint."""
    try:
        model = get_ml_model()
        return {
            "status": "ok",
            "model_name": model.MODEL_NAME,
            "model_version": model.get_version(),
        }
    except Exception:
        return {
            "status": "degraded",
            "model_name": None,
            "model_version": None,
        }
