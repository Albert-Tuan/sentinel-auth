"""ML Service integration - score endpoint."""
from fastapi import APIRouter, HTTPException, Header
from typing import Optional

router = APIRouter(prefix="/internal/v1/ml", tags=["ml"])


class ScoreRequest:
    """Placeholder for score request schema."""
    pass


class ScoreResponse:
    """Placeholder for score response schema."""
    pass


@router.post("/score", response_model=dict)
async def score(
    request: dict,
    x_internal_token: Optional[str] = Header(None),
) -> dict:
    """
    Compute ML risk score for login features.

    This endpoint mirrors the ml-service /score endpoint.
    Features are passed directly; no background tasks.
    """
    pass
    return {}


@router.get("/health")
async def ml_health() -> dict:
    """Health check for ML endpoint."""
    pass
    return {"status": "ok"}
