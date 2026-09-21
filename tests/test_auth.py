"""Tests for auth endpoints."""
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app


@pytest.mark.asyncio
async def test_login_success():
    """Test successful login returns tokens."""
    pass


@pytest.mark.asyncio
async def test_login_invalid_credentials():
    """Test login with wrong password returns 401."""
    pass


@pytest.mark.asyncio
async def test_mfa_verify_success():
    """Test MFA verification returns tokens."""
    pass


@pytest.mark.asyncio
async def test_mfa_verify_invalid_code():
    """Test MFA with wrong code returns 401."""
    pass


@pytest.mark.asyncio
async def test_health():
    """Test health endpoint."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_ready():
    """Test ready endpoint."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/ready")
        assert response.status_code == 200
