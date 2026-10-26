"""
Tests for the routing API endpoints.

This module contains tests for the /lookup and /routes API endpoints,
verifying HTTP status codes, response structure, and the transmitted field.
"""

import pytest
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.routing import RoutingEntry


@pytest.mark.asyncio
async def test_lookup_valid_destination_returns_200():
    """Test that a valid destination returns 200 with route details."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/lookup?destination=192.168.1.50")

    assert response.status_code == 200
    data = response.json()
    assert data["matched"] is True
    assert data["route"] is not None
    assert data["route"]["destination"] == "192.168.1.0/25"
    assert data["transmitted"] is False
    assert "explanation" in data
    assert data["error"] is None


@pytest.mark.asyncio
async def test_lookup_invalid_destination_returns_400():
    """Test that an invalid IPv4 address returns 400 Bad Request."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/lookup?destination=not.an.ip")

    assert response.status_code == 400
    data = response.json()
    assert "detail" in data
    assert "Invalid IP address" in data["detail"]


@pytest.mark.asyncio
async def test_lookup_out_of_bounds_ip_returns_400():
    """Test that an out-of-bounds IPv4 address returns 400 Bad Request."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/lookup?destination=999.999.999.999")

    assert response.status_code == 400
    data = response.json()
    assert "Invalid IP address" in data["detail"]


@pytest.mark.asyncio
async def test_lookup_default_route_returns_200():
    """Test that an IP matching the default route returns 200."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/lookup?destination=8.8.8.8")

    assert response.status_code == 200
    data = response.json()
    assert data["matched"] is True
    assert data["route"]["destination"] == "0.0.0.0/0"
    assert data["transmitted"] is False


@pytest.mark.asyncio
async def test_lookup_direct_route_returns_200():
    """Test that an IP matching a direct route returns 200."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/lookup?destination=10.5.5.5")

    assert response.status_code == 200
    data = response.json()
    assert data["matched"] is True
    assert data["route"]["destination"] == "10.0.0.0/8"
    assert data["route"]["next_hop_type"] == "direct"
    assert data["route"]["next_hop"] is None
    assert data["transmitted"] is False


@pytest.mark.asyncio
async def test_lookup_response_includes_all_fields():
    """Test that the response includes all documented fields."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/lookup?destination=192.168.1.50")

    assert response.status_code == 200
    data = response.json()
    # Required fields per API contract
    assert "matched" in data
    assert "route" in data
    assert "explanation" in data
    assert "error" in data
    assert "transmitted" in data
    # Route object fields
    route = data["route"]
    assert route is not None
    assert "destination" in route
    assert "next_hop" in route
    assert "interface" in route
    assert "metric" in route
    assert "next_hop_type" in route


@pytest.mark.asyncio
async def test_routes_endpoint_returns_all_samples():
    """Test that /routes returns all sample routing entries."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/routes")

    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 10
    for route in data:
        assert "destination" in route
        assert "next_hop" in route
        assert "interface" in route
        assert "metric" in route
        assert "next_hop_type" in route


@pytest.mark.asyncio
async def test_lookup_missing_destination_parameter():
    """Test that missing destination parameter returns 422."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/lookup")

    assert response.status_code == 422  # FastAPI validation error


class TestCustomRoutingTable:
    """Tests using a custom routing table without default route."""

    @pytest.fixture
    def custom_app(self):
        """Create a test app with a custom routing table (no default route)."""
        from fastapi import FastAPI, HTTPException, Query
        from fastapi.middleware.cors import CORSMiddleware
        from app.routing_logic import lookup_route
        from app.routing import RouteLookupResult

        test_app = FastAPI()
        test_app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

        TEST_ROUTES = [
            RoutingEntry(
                destination="192.168.1.0/24",
                next_hop="10.0.0.1",
                interface="eth0",
                metric=10,
            ),
        ]

        @test_app.get("/lookup", response_model=RouteLookupResult)
        async def route_lookup(destination: str = Query(...)):
            result = lookup_route(destination, TEST_ROUTES)
            if result.error:
                if "Invalid" in result.error:
                    raise HTTPException(status_code=400, detail=result.error)
                else:
                    raise HTTPException(status_code=404, detail=result.explanation)
            if not result.matched:
                raise HTTPException(status_code=404, detail=result.explanation)
            return result

        return test_app

    @pytest.mark.asyncio
    async def test_lookup_no_matching_route_returns_404(self, custom_app):
        """Test that no matching route returns 404 (when no default route)."""
        transport = ASGITransport(app=custom_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/lookup?destination=10.10.10.10")

        assert response.status_code == 404
        data = response.json()
        assert "detail" in data
        assert "No route matches" in data["detail"]