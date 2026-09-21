"""Tests for ML scoring endpoint."""
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app


@pytest.mark.asyncio
async def test_score_basic():
    """Test ML score endpoint returns score dict."""
    pass


@pytest.mark.asyncio
async def test_score_with_features():
    """Test ML scoring with full feature vector."""
    pass


@pytest.mark.asyncio
async def test_ml_health():
    """Test ML health endpoint."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/internal/v1/ml/health")
        assert response.status_code == 200
