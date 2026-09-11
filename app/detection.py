"""Detection engine - inline risk detection."""
from fastapi import APIRouter, HTTPException, Header
from typing import Optional

router = APIRouter(prefix="/internal/v1", tags=["detection"])


class DetectionRequest:
    """Placeholder for detection request schema."""
    pass


class DetectionResponse:
    """Placeholder for detection response schema."""
    pass


@router.post("/detect", response_model=dict)
async def detect(
    request: dict,
    x_internal_token: Optional[str] = Header(None),
) -> dict:
    """
    Perform inline risk detection for a login attempt.

    Calls ML scoring inline within the request (no background tasks).
    Applies rule-based scoring and returns combined risk assessment.
    """
    pass
    return {}


@router.get("/health")
async def detection_health() -> dict:
    """Health check for detection endpoint."""
    pass
    return {"status": "ok"}
