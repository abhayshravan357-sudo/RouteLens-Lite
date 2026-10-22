"""
Tests for the health check endpoint.

This module contains tests for the /health endpoint to ensure it returns
the expected response.
"""

import pytest
from httpx import AsyncClient, ASGITransport

from app.main import app


@pytest.mark.asyncio
async def test_health_endpoint_returns_ok():
    """
    Test that the /health endpoint returns a 200 OK with the expected JSON.

    This test uses httpx's AsyncClient with ASGITransport to make a real HTTP
    request to the FastAPI app without starting a server (using the test client pattern).
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")

    # Assert the response status code is 200 (OK)
    assert response.status_code == 200

    # Assert the response body matches our expected format
    data = response.json()
    assert data == {"status": "ok", "service": "RouteLens Lite API"}


@pytest.mark.asyncio
async def test_health_endpoint_response_structure():
    """
    Test that the health endpoint response has the correct structure.

    This is a more focused test checking only the structure, not exact values.
    Useful when you want to ensure the shape is correct but values may vary.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    data = response.json()

    # Check that required fields exist
    assert "status" in data
    assert "service" in data

    # Check that status is a string and service is a string
    assert isinstance(data["status"], str)
    assert isinstance(data["service"], str)

    # Check that status indicates success
    assert data["status"] == "ok"