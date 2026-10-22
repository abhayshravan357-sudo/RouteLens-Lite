"""
Tests for the validation error handler and the route destination rules.

These check that a student is told what went wrong in words they can
act on, rather than in the shape Pydantic uses internally.
"""

import pytest
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.routing import RoutingEntry, NextHopType


def _client():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


class TestValidationMessages:
    """A validation failure should read as a sentence."""

    @pytest.mark.asyncio
    async def test_an_invalid_cidr_is_reported_in_words(self):
        """The app's own message survives, without the Pydantic wrapper."""
        async with _client() as client:
            response = await client.post(
                "/routes",
                json={
                    "destination": "192.168.1.0/33",
                    "next_hop": "10.0.0.1",
                    "interface": "eth0",
                    "metric": 10,
                },
            )

        assert response.status_code == 422
        detail = response.json()["detail"]
        assert isinstance(detail, str)
        assert "Invalid CIDR notation: 192.168.1.0/33" in detail
        assert "Value error" not in detail

    @pytest.mark.asyncio
    async def test_the_field_is_named(self):
        """Which field was wrong is part of the answer."""
        async with _client() as client:
            response = await client.post(
                "/routes",
                json={
                    "destination": "192.168.1.0/24",
                    "next_hop": "not-an-ip",
                    "interface": "eth0",
                    "metric": 10,
                },
            )

        assert response.status_code == 422
        detail = response.json()["detail"]
        assert "next_hop" in detail
        assert "Invalid next hop IP address" in detail

    @pytest.mark.asyncio
    async def test_a_negative_metric_says_so_in_our_words(self):
        """The custom metric message must reach the student.

        Pydantic's own "Input should be greater than or equal to 0"
        fires before the field validator, so the careful message the app
        wrote never arrived. It does now.
        """
        async with _client() as client:
            response = await client.post(
                "/routes",
                json={
                    "destination": "192.168.1.0/24",
                    "next_hop": "10.0.0.1",
                    "interface": "eth0",
                    "metric": -5,
                },
            )

        assert response.status_code == 422
        detail = response.json()["detail"]
        assert "Metric must be a non-negative integer" in detail

    @pytest.mark.asyncio
    async def test_a_missing_field_is_named_in_words(self):
        """A missing field should not say "Field required"."""
        async with _client() as client:
            response = await client.post(
                "/routes",
                json={"next_hop": "10.0.0.1", "metric": 10},
            )

        assert response.status_code == 422
        detail = response.json()["detail"]
        assert "Destination" in detail
        assert "Field required" not in detail


class TestDestinationRules:
    """A destination must say what it covers."""

    def test_a_bare_address_is_refused(self):
        """A bare address would silently become a /32."""
        with pytest.raises(ValueError, match="prefix length"):
            RoutingEntry(
                destination="192.168.1.7",
                next_hop="10.0.0.1",
                interface="eth0",
                metric=10,
            )

    def test_a_bare_ipv6_address_is_refused(self):
        """The same applies to IPv6."""
        with pytest.raises(ValueError, match="prefix length"):
            RoutingEntry(
                destination="2001:db8::1",
                next_hop="2001:db8::2",
                interface="eth0",
                metric=10,
            )

    def test_host_bits_are_normalised_away(self):
        """192.168.1.5/24 is stored as the network it describes."""
        entry = RoutingEntry(
            destination="192.168.1.5/24",
            next_hop="10.0.0.1",
            interface="eth0",
            metric=10,
        )
        assert entry.destination == "192.168.1.0/24"

    def test_ipv6_host_bits_are_normalised_away(self):
        """The same for IPv6."""
        entry = RoutingEntry(
            destination="2001:db8::5/64",
            next_hop="2001:db8::1",
            interface="eth0",
            metric=10,
        )
        assert entry.destination == "2001:db8::/64"

    def test_a_network_is_left_alone(self):
        """A network in network form is unchanged."""
        entry = RoutingEntry(
            destination="192.168.1.0/24",
            next_hop="10.0.0.1",
            interface="eth0",
            metric=10,
        )
        assert entry.destination == "192.168.1.0/24"

    def test_the_sample_routes_are_all_in_network_form(self):
        """The existing table must not change."""
        from app.routing import SAMPLE_ROUTES

        for route in SAMPLE_ROUTES:
            assert route.destination == route.get_network().__str__()


class TestMainTableAnalysis:
    """The editable table is explained with the same machinery."""

    @pytest.mark.asyncio
    async def test_the_main_table_can_be_analysed(self):
        """GET /routes/analysis explains the editable table."""
        async with _client() as client:
            response = await client.get(
                "/routes/analysis",
                params={"destination": "192.168.1.50"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["table_provenance"] == "simulated"
        assert data["analysis_provenance"] == "inferred"
        assert data["analyses"]
        analysis = data["analyses"][0]
        assert analysis["destination"] == "192.168.1.50"
        assert analysis["matched"] is True
        assert analysis["selected"]["destination"] == "192.168.1.0/25"
        # The candidates that lost are named, with the reason.
        assert analysis["candidates"]
        outcomes = {c["outcome"] for c in analysis["candidates"]}
        assert "selected" in outcomes
        assert "less specific" in outcomes
        # Each loser says why it lost.
        for candidate in analysis["candidates"]:
            if candidate["outcome"] != "selected":
                assert candidate["explanation"]

    @pytest.mark.asyncio
    async def test_an_invalid_destination_is_refused(self):
        """A bad destination is a 400, not a crash."""
        async with _client() as client:
            response = await client.get(
                "/routes/analysis",
                params={"destination": "not-an-address"},
            )

        assert response.status_code == 400
