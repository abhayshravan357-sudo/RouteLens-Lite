"""
Tests for the routing table API endpoints.

This module contains tests for the mutable routing table API endpoints:
- GET /routes
- POST /routes
- PUT /routes/{index}
- DELETE /routes/{index}
- POST /routes/reset
- GET /lookup (using live table)
- GET /routes/summary
"""

import pytest
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.routing import RoutingEntry, NextHopType, Provenance
from app.routing_table import get_routing_table, InvalidRouteError, IndexOutOfRangeError


class TestRoutingTableService:
    """Tests for the RoutingTable service class."""

    def setup_method(self):
        """Reset the routing table before each test."""
        routing_table = get_routing_table()
        routing_table.reset_routes()

    def test_get_routes_returns_copy(self):
        """Test that get_routes returns a copy, not the internal list."""
        routing_table = get_routing_table()
        routes1 = routing_table.get_routes()
        routes2 = routing_table.get_routes()
        assert routes1 is not routes2
        assert routes1 == routes2

    def test_add_route_success(self):
        """Test adding a valid route."""
        routing_table = get_routing_table()
        initial_count = len(routing_table.get_routes())

        new_route = RoutingEntry(
            provenance=Provenance.OBSERVED,
            destination="172.16.0.0/12",
            next_hop="10.0.0.5",
            interface="eth3",
            metric=15,
            next_hop_type=NextHopType.GATEWAY,
        )
        added = routing_table.add_route(new_route)

        assert added.destination == "172.16.0.0/12"
        assert added.next_hop == "10.0.0.5"
        assert len(routing_table.get_routes()) == initial_count + 1

    def test_every_route_in_the_table_is_simulated(self):
        """
        The table is a model, so every route in it is simulated.

        The sample routes and the ones the reader typed in are both part
        of the teaching model. The provenance is decided by the table
        rather than taken from the caller, so it is the same whichever
        door a route came in by.
        """
        routing_table = get_routing_table()

        for route in routing_table.get_routes():
            assert route.provenance == Provenance.SIMULATED, (
                f"{route.destination} is marked {route.provenance.value}"
            )

        added = routing_table.add_route(
            RoutingEntry(
                provenance=Provenance.OBSERVED,
                destination="172.16.0.0/12",
                next_hop="10.0.0.5",
                interface="eth3",
                metric=15,
                next_hop_type=NextHopType.GATEWAY,
            )
        )
        assert added.provenance == Provenance.SIMULATED, (
            "a route added to the teaching table was not marked as simulated"
        )

        routing_table.reset_routes()

    def test_add_route_gateway_without_next_hop(self):
        """Test that gateway route without next hop is rejected at service level."""
        routing_table = get_routing_table()

        # Create a route that bypasses Pydantic validation for next_hop
        # by using a valid-looking but None next_hop with GATEWAY type
        new_route = RoutingEntry(
            provenance=Provenance.OBSERVED,
            destination="172.16.0.0/12",
            next_hop=None,
            interface="eth3",
            metric=15,
            next_hop_type=NextHopType.GATEWAY,
        )
        with pytest.raises(InvalidRouteError, match="requires a next_hop address"):
            routing_table.add_route(new_route)

    def test_update_route_success(self):
        """Test updating a route."""
        routing_table = get_routing_table()
        routes = routing_table.get_routes()
        initial_count = len(routes)

        updated_route = RoutingEntry(
            provenance=Provenance.OBSERVED,
            destination="192.168.1.0/24",
            next_hop="10.0.0.99",
            interface="eth0",
            metric=50,
            next_hop_type=NextHopType.GATEWAY,
        )
        updated = routing_table.update_route(0, updated_route)

        assert updated.next_hop == "10.0.0.99"
        assert updated.metric == 50
        assert len(routing_table.get_routes()) == initial_count

    def test_update_route_out_of_range(self):
        """Test that updating out of range index fails."""
        routing_table = get_routing_table()
        routes = routing_table.get_routes()

        updated_route = RoutingEntry(
            provenance=Provenance.OBSERVED,
            destination="192.168.1.0/24",
            next_hop="10.0.0.99",
            interface="eth0",
            metric=50,
            next_hop_type=NextHopType.GATEWAY,
        )
        with pytest.raises(IndexOutOfRangeError):
            routing_table.update_route(len(routes), updated_route)
        with pytest.raises(IndexOutOfRangeError):
            routing_table.update_route(-1, updated_route)

    def test_delete_route_success(self):
        """Test deleting a route."""
        routing_table = get_routing_table()
        initial_count = len(routing_table.get_routes())

        routing_table.delete_route(0)

        assert len(routing_table.get_routes()) == initial_count - 1

    def test_delete_route_out_of_range(self):
        """Test that deleting out of range index fails."""
        routing_table = get_routing_table()
        routes = routing_table.get_routes()

        with pytest.raises(IndexOutOfRangeError):
            routing_table.delete_route(len(routes))
        with pytest.raises(IndexOutOfRangeError):
            routing_table.delete_route(-1)

    def test_replace_routes_success(self):
        """Test bulk replacing routes."""
        routing_table = get_routing_table()

        new_routes = [
            RoutingEntry(
                provenance=Provenance.OBSERVED,
                destination="10.10.0.0/16",
                next_hop="10.0.0.10",
                interface="eth4",
                metric=25,
                next_hop_type=NextHopType.GATEWAY,
            ),
            RoutingEntry(
                provenance=Provenance.OBSERVED,
                destination="10.20.0.0/16",
                next_hop=None,
                interface="eth5",
                metric=1,
                next_hop_type=NextHopType.DIRECT,
            ),
        ]
        replaced = routing_table.replace_routes(new_routes)

        assert len(replaced) == 2
        assert replaced[0].destination == "10.10.0.0/16"
        assert replaced[1].destination == "10.20.0.0/16"

    def test_replace_routes_atomic_failure(self):
        """Test that bulk replace is atomic - one bad route leaves table unchanged."""
        routing_table = get_routing_table()
        original_count = len(routing_table.get_routes())
        original_routes = routing_table.get_routes()

        # Create a route with invalid next_hop for GATEWAY type
        new_routes = [
            RoutingEntry(
                provenance=Provenance.OBSERVED,
                destination="10.10.0.0/16",
                next_hop="10.0.0.10",
                interface="eth4",
                metric=25,
                next_hop_type=NextHopType.GATEWAY,
            ),
            RoutingEntry(
                provenance=Provenance.OBSERVED,
                destination="10.20.0.0/16",
                next_hop=None,  # Invalid for GATEWAY
                interface="eth5",
                metric=30,
                next_hop_type=NextHopType.GATEWAY,
            ),
        ]
        with pytest.raises(InvalidRouteError, match="Route at index 1"):
            routing_table.replace_routes(new_routes)

        # Table should be unchanged
        current_routes = routing_table.get_routes()
        assert len(current_routes) == original_count
        assert current_routes == original_routes

    def test_reset_routes(self):
        """Test resetting to original sample routes."""
        routing_table = get_routing_table()

        # Add a route first
        routing_table.add_route(RoutingEntry(
            provenance=Provenance.OBSERVED,
            destination="172.16.0.0/12",
            next_hop="10.0.0.5",
            interface="eth3",
            metric=15,
            next_hop_type=NextHopType.GATEWAY,
        ))
        assert len(routing_table.get_routes()) > 10

        # Reset
        reset_routes = routing_table.reset_routes()

        assert len(reset_routes) == 10  # Original sample has 10 routes
        assert reset_routes[0].destination == "192.168.1.0/24"

    def test_get_summary(self):
        """Test the summary endpoint."""
        routing_table = get_routing_table()
        summary = routing_table.get_summary()

        assert summary["total_routes"] == 10
        assert summary["ipv4_count"] == 5
        assert summary["ipv6_count"] == 5
        assert summary["default_route_count"] == 2
        assert summary["lowest_metric"] == 1
        assert "longest_prefix" in summary


@pytest.mark.asyncio
async def test_get_routes_returns_live_table():
    """Test that GET /routes returns the live table."""
    routing_table = get_routing_table()
    routing_table.reset_routes()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/routes")

    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 10


@pytest.mark.asyncio
async def test_post_routes_adds_route():
    """Test that POST /routes adds a route and 201 is returned."""
    routing_table = get_routing_table()
    routing_table.reset_routes()
    initial_count = len(routing_table.get_routes())

    new_route = {
        "provenance": "observed",
        "destination": "172.16.0.0/12",
        "next_hop": "10.0.0.5",
        "interface": "eth3",
        "metric": 15,
        "next_hop_type": "gateway",
    }

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/routes", json=new_route)

    assert response.status_code == 201
    data = response.json()
    assert data["destination"] == "172.16.0.0/12"
    assert data["next_hop"] == "10.0.0.5"
    assert len(routing_table.get_routes()) == initial_count + 1


@pytest.mark.asyncio
async def test_post_routes_invalid_cidr_returns_400():
    """Test that POST /routes with invalid CIDR returns 400/422."""
    routing_table = get_routing_table()
    routing_table.reset_routes()

    new_route = {
        "provenance": "observed",
        "destination": "not.a.cidr",
        "next_hop": "10.0.0.5",
        "interface": "eth3",
        "metric": 15,
        "next_hop_type": "gateway",
    }

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/routes", json=new_route)

    assert response.status_code in (400, 422)
    data = response.json()
    assert "detail" in data
    # Pydantic validation errors are a list
    detail_str = str(data["detail"]).lower()
    assert "cidr" in detail_str


@pytest.mark.asyncio
async def test_post_routes_invalid_next_hop_returns_400():
    """Test that POST /routes with invalid next hop returns 400/422."""
    routing_table = get_routing_table()
    routing_table.reset_routes()

    new_route = {
        "provenance": "observed",
        "destination": "172.16.0.0/12",
        "next_hop": "not.an.ip",
        "interface": "eth3",
        "metric": 15,
        "next_hop_type": "gateway",
    }

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/routes", json=new_route)

    assert response.status_code in (400, 422)
    data = response.json()
    assert "detail" in data
    detail_str = str(data["detail"]).lower()
    assert "next hop" in detail_str or "next_hop" in detail_str


@pytest.mark.asyncio
async def test_post_routes_empty_interface_returns_400():
    """Test that POST /routes with empty interface returns 400/422."""
    routing_table = get_routing_table()
    routing_table.reset_routes()

    new_route = {
        "provenance": "observed",
        "destination": "172.16.0.0/12",
        "next_hop": "10.0.0.5",
        "interface": "",
        "metric": 15,
        "next_hop_type": "gateway",
    }

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/routes", json=new_route)

    assert response.status_code in (400, 422)
    data = response.json()
    assert "detail" in data


@pytest.mark.asyncio
async def test_post_routes_negative_metric_returns_400():
    """Test that POST /routes with negative metric returns 400/422."""
    routing_table = get_routing_table()
    routing_table.reset_routes()

    new_route = {
        "provenance": "observed",
        "destination": "172.16.0.0/12",
        "next_hop": "10.0.0.5",
        "interface": "eth3",
        "metric": -1,
        "next_hop_type": "gateway",
    }

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/routes", json=new_route)

    assert response.status_code in (400, 422)
    data = response.json()
    assert "detail" in data


@pytest.mark.asyncio
async def test_post_routes_gateway_without_next_hop_returns_400():
    """Test that POST /routes with gateway type but no next hop returns 400."""
    routing_table = get_routing_table()
    routing_table.reset_routes()

    new_route = {
        "provenance": "observed",
        "destination": "172.16.0.0/12",
        "next_hop": None,
        "interface": "eth3",
        "metric": 15,
        "next_hop_type": "gateway",
    }

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/routes", json=new_route)

    assert response.status_code == 400
    data = response.json()
    assert "requires a next_hop address" in data["detail"]


@pytest.mark.asyncio
async def test_put_routes_updates_route():
    """Test that PUT /routes/{index} updates a route."""
    routing_table = get_routing_table()
    routing_table.reset_routes()

    updated_route = {
        "provenance": "observed",
        "destination": "192.168.1.0/24",
        "next_hop": "10.0.0.99",
        "interface": "eth0",
        "metric": 50,
        "next_hop_type": "gateway",
    }

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.put("/routes/0", json=updated_route)

    assert response.status_code == 200
    data = response.json()
    assert data["next_hop"] == "10.0.0.99"
    assert data["metric"] == 50

    # Verify the change persisted
    routes = routing_table.get_routes()
    assert routes[0].next_hop == "10.0.0.99"
    assert routes[0].metric == 50


@pytest.mark.asyncio
async def test_put_routes_out_of_range_returns_404():
    """Test that PUT /routes/{index} with invalid index returns 404."""
    routing_table = get_routing_table()
    routing_table.reset_routes()

    updated_route = {
        "provenance": "observed",
        "destination": "192.168.1.0/24",
        "next_hop": "10.0.0.99",
        "interface": "eth0",
        "metric": 50,
        "next_hop_type": "gateway",
    }

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.put("/routes/999", json=updated_route)

    assert response.status_code == 404
    data = response.json()
    assert "detail" in data


@pytest.mark.asyncio
async def test_delete_routes_removes_route():
    """Test that DELETE /routes/{index} removes a route."""
    routing_table = get_routing_table()
    routing_table.reset_routes()
    initial_count = len(routing_table.get_routes())

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.delete("/routes/0")

    assert response.status_code == 204
    assert len(routing_table.get_routes()) == initial_count - 1


@pytest.mark.asyncio
async def test_delete_routes_out_of_range_returns_404():
    """Test that DELETE /routes/{index} with invalid index returns 404."""
    routing_table = get_routing_table()
    routing_table.reset_routes()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.delete("/routes/999")

    assert response.status_code == 404
    data = response.json()
    assert "detail" in data


@pytest.mark.asyncio
async def test_post_routes_reset_restores_original():
    """Test that POST /routes/reset restores the original table."""
    routing_table = get_routing_table()
    routing_table.reset_routes()

    # Add a route
    new_route = {
        "provenance": "observed",
        "destination": "172.16.0.0/12",
        "next_hop": "10.0.0.5",
        "interface": "eth3",
        "metric": 15,
        "next_hop_type": "gateway",
    }
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.post("/routes", json=new_route)
        assert len(routing_table.get_routes()) == 11

        # Reset
        response = await client.post("/routes/reset")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 10
        assert data[0]["destination"] == "192.168.1.0/24"


@pytest.mark.asyncio
async def test_get_lookup_uses_live_table():
    """Test that GET /lookup uses the live table, not static sample."""
    routing_table = get_routing_table()
    routing_table.reset_routes()

    # Initially 192.168.1.50 matches /25
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/lookup?destination=192.168.1.50")
        assert response.status_code == 200
        assert response.json()["route"]["destination"] == "192.168.1.0/25"

    # Add a more specific route /26
    new_route = {
        "provenance": "observed",
        "destination": "192.168.1.0/26",
        "next_hop": "10.0.0.100",
        "interface": "eth4",
        "metric": 5,
        "next_hop_type": "gateway",
    }
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.post("/routes", json=new_route)

        # Now lookup should match the new /26 route
        response = await client.get("/lookup?destination=192.168.1.50")
        assert response.status_code == 200
        assert response.json()["route"]["destination"] == "192.168.1.0/26"


@pytest.mark.asyncio
async def test_delete_route_changes_lookup_fallback():
    """Test that removing a route makes destination fall back to less specific."""
    routing_table = get_routing_table()
    routing_table.reset_routes()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Initially 192.168.1.50 matches /25 (index 1)
        response = await client.get("/lookup?destination=192.168.1.50")
        assert response.json()["route"]["destination"] == "192.168.1.0/25"

        # Delete the /25 route (index 1)
        await client.delete("/routes/1")

        # Now should fall back to /24
        response = await client.get("/lookup?destination=192.168.1.50")
        assert response.status_code == 200
        assert response.json()["route"]["destination"] == "192.168.1.0/24"


@pytest.mark.asyncio
async def test_reset_restores_original_behavior():
    """Test that reset restores the original behavior."""
    routing_table = get_routing_table()
    routing_table.reset_routes()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Add a route
        await client.post("/routes", json={
            "provenance": "observed",
            "destination": "172.16.0.0/12",
            "next_hop": "10.0.0.5",
            "interface": "eth3",
            "metric": 15,
            "next_hop_type": "gateway",
        })

        # Reset
        await client.post("/routes/reset")

        # Should be back to original 10 routes
        response = await client.get("/routes")
        assert len(response.json()) == 10

        # Lookup should work as before
        response = await client.get("/lookup?destination=192.168.1.50")
        assert response.json()["route"]["destination"] == "192.168.1.0/25"


@pytest.mark.asyncio
async def test_bulk_replace_atomic():
    """Test that bulk replace is atomic via service."""
    routing_table = get_routing_table()
    routing_table.reset_routes()
    original_routes = routing_table.get_routes()

    from app.routing_table import InvalidRouteError
    with pytest.raises(InvalidRouteError):
        routing_table.replace_routes([
            RoutingEntry(provenance=Provenance.OBSERVED, destination="10.10.0.0/16", next_hop="10.0.0.10", interface="eth4", metric=25, next_hop_type=NextHopType.GATEWAY),
            RoutingEntry(provenance=Provenance.OBSERVED, destination="10.20.0.0/16", next_hop=None, interface="eth5", metric=30, next_hop_type=NextHopType.GATEWAY),  # GATEWAY without next_hop
        ])

    # Table should be unchanged
    assert routing_table.get_routes() == original_routes


@pytest.mark.asyncio
async def test_routes_summary_counts():
    """Test that /routes/summary returns correct counts."""
    routing_table = get_routing_table()
    routing_table.reset_routes()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/routes/summary")

    assert response.status_code == 200
    data = response.json()
    assert data["total_routes"] == 10
    assert data["ipv4_count"] == 5
    assert data["ipv6_count"] == 5
    assert data["default_route_count"] == 2
    assert data["lowest_metric"] == 1
    assert "longest_prefix" in data