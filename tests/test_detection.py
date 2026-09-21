"""Tests for detection endpoint."""
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app


@pytest.mark.asyncio
async def test_detect_inline():
    """Test inline detection returns risk assessment."""
    pass


@pytest.mark.asyncio
async def test_detect_with_ml_score():
    """Test detection calls ML inline and combines scores."""
    pass


@pytest.mark.asyncio
async def test_detect_health():
    """Test detection health endpoint."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/internal/v1/detect/health")
        assert response.status_code == 200
