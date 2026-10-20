"""
Tests for the evidence-based topology builder.
"""

import pytest
from unittest.mock import AsyncMock, patch

from app.topology import Provenance, build_topology
from app.network_collector import (
    CollectionResult,
    InterfaceInfo,
    NeighborInfo,
    RouteInfo,
)
from app.scenarios_data import SCENARIOS


def _collection(data, success=True):
    return CollectionResult(
        timestamp="2026-10-20T00:00:00Z",
        success=success,
        data=data,
        error=None if success else "collection failed",
        command="ip -j",
        duration_ms=1.0,
    )


def _interface(name="eth0", address="192.168.1.100"):
    return InterfaceInfo(
        name=name,
        index=2,
        state="UP",
        mtu=1500,
        mac_address=None,
        ipv4_addresses=[address],
        ipv4_networks=[f"{address}/24"],
        ipv6_addresses=[],
        ipv6_networks=[],
        flags=["UP"],
    )


def _neighbor(address="192.168.1.1", interface="eth0", is_router=True):
    return NeighborInfo(
        ip_address=address,
        interface=interface,
        mac_address="aa:bb:cc:dd:ee:00",
        state="REACHABLE",
        is_router=is_router,
    )


def _route(gateway="192.168.1.1", interface="eth0"):
    return RouteInfo(
        destination="0.0.0.0/0",
        gateway=gateway,
        interface=interface,
        metric=100,
        proto="dhcp",
        scope="link",
        pref_src="192.168.1.100",
    )


class _FakeCollector:
    """A collector whose three calls return fixed results.

    The signatures match the real collector, which takes the address
    family so it can read both tables.
    """

    def __init__(self, interfaces, routes, neighbors, routes_ipv6=None, neighbors_ipv6=None):
        self._interfaces = interfaces
        self._routes = routes
        self._neighbors = neighbors
        self._routes_ipv6 = routes_ipv6 or []
        self._neighbors_ipv6 = neighbors_ipv6 or []

    async def collect_interfaces(self):
        return _collection(self._interfaces)

    async def collect_routes(self, ip_version="ipv4"):
        if ip_version == "ipv6":
            return _collection(self._routes_ipv6)
        return _collection(self._routes)

    async def collect_neighbors(self, ip_version="ipv4"):
        if ip_version == "ipv6":
            return _collection(self._neighbors_ipv6)
        return _collection(self._neighbors)


class TestBuildTopology:
    """Tests for build_topology()."""

    @pytest.mark.asyncio
    async def test_observed_interfaces_are_marked_observed(self):
        """Interfaces read from the host are observed, not inferred."""
        fake = _FakeCollector(
            interfaces=[_interface()],
            routes=[],
            neighbors=[],
        )

        with patch("app.topology.get_network_collector", return_value=fake):
            graph = await build_topology(None)

        iface = next(n for n in graph.nodes if n.id == "iface:eth0")
        assert iface.provenance == Provenance.OBSERVED
        assert iface.addresses == ["192.168.1.100"]

    @pytest.mark.asyncio
    async def test_scenario_nodes_are_marked_simulated(self):
        """Scenario devices are simulated, never presented as measured."""
        fake = _FakeCollector(interfaces=[], routes=[], neighbors=[])

        with patch("app.topology.get_network_collector", return_value=fake):
            graph = await build_topology(SCENARIOS["client-router-server"])

        sim_nodes = [n for n in graph.nodes if n.id.startswith("sim:")]
        assert len(sim_nodes) == 3
        for node in sim_nodes:
            assert node.provenance == Provenance.SIMULATED

    @pytest.mark.asyncio
    async def test_scenario_links_are_simulated(self):
        """Scenario links are simulated."""
        fake = _FakeCollector(interfaces=[], routes=[], neighbors=[])

        with patch("app.topology.get_network_collector", return_value=fake):
            graph = await build_topology(SCENARIOS["client-router-server"])

        link_edges = [e for e in graph.edges if e.kind == "link"]
        assert len(link_edges) == 2
        for edge in link_edges:
            assert edge.provenance == Provenance.SIMULATED

    @pytest.mark.asyncio
    async def test_neighbor_edges_are_inferred(self):
        """A neighbour entry proves a device answered, not that a cable exists."""
        fake = _FakeCollector(
            interfaces=[_interface()],
            routes=[],
            neighbors=[_neighbor()],
        )

        with patch("app.topology.get_network_collector", return_value=fake):
            graph = await build_topology(None)

        neighbor_edge = next(e for e in graph.edges if e.kind == "neighbor")
        assert neighbor_edge.provenance == Provenance.INFERRED
        # The neighbour record itself is observed.
        neighbor_node = next(n for n in graph.nodes if n.id == "neighbor:192.168.1.1")
        assert neighbor_node.provenance == Provenance.OBSERVED

    @pytest.mark.asyncio
    async def test_route_edges_are_inferred(self):
        """A route pointing at a gateway does not measure the link."""
        fake = _FakeCollector(
            interfaces=[_interface()],
            routes=[_route()],
            neighbors=[],
        )

        with patch("app.topology.get_network_collector", return_value=fake):
            graph = await build_topology(None)

        route_edge = next(e for e in graph.edges if e.kind == "route")
        assert route_edge.provenance == Provenance.INFERRED
        gateway = next(n for n in graph.nodes if n.id == "gateway:192.168.1.1")
        assert gateway.provenance == Provenance.OBSERVED

    @pytest.mark.asyncio
    async def test_observed_and_simulated_are_not_merged(self):
        """A simulated node and an observed node stay distinct."""
        fake = _FakeCollector(
            interfaces=[_interface()],
            routes=[],
            neighbors=[],
        )

        with patch("app.topology.get_network_collector", return_value=fake):
            graph = await build_topology(SCENARIOS["client-router-server"])

        ids = {n.id for n in graph.nodes}
        # The scenario's "client" is not the host's eth0.
        assert "sim:client" in ids
        assert "iface:eth0" in ids
        assert "sim:client" != "iface:eth0"

    @pytest.mark.asyncio
    async def test_failed_collection_does_not_invent_data(self):
        """When the host cannot be read, only the scenario is shown."""
        fake = _FakeCollector(interfaces=[], routes=[], neighbors=[])
        fake.collect_interfaces = AsyncMock(
            return_value=_collection([], success=False)
        )

        with patch("app.topology.get_network_collector", return_value=fake):
            graph = await build_topology(SCENARIOS["client-router-server"])

        assert all(n.provenance == Provenance.SIMULATED for n in graph.nodes)
        assert graph.provenance == Provenance.SIMULATED
        assert "simulated" in graph.explanation

    @pytest.mark.asyncio
    async def test_graph_has_a_timestamp(self):
        """The graph records when it was observed."""
        fake = _FakeCollector(interfaces=[], routes=[], neighbors=[])

        with patch("app.topology.get_network_collector", return_value=fake):
            graph = await build_topology(None)

        assert graph.observed_at
        assert graph.observed_at.endswith("Z")

    @pytest.mark.asyncio
    async def test_a_connected_route_contributes_no_gateway_node(self):
        """A route with no next hop is directly connected, not a gateway.

        The IPv4 table has one of these too, and it correctly adds
        nothing. The IPv6 table must behave the same way.
        """
        fake = _FakeCollector(
            interfaces=[],
            routes=[],
            neighbors=[],
            routes_ipv6=[_route(gateway=None, interface="wlp2s0")],
        )

        with patch("app.topology.get_network_collector", return_value=fake):
            graph = await build_topology(None)

        assert [n for n in graph.nodes if n.kind == "gateway"] == []

    @pytest.mark.asyncio
    async def test_ipv6_gateways_appear_alongside_ipv4_ones(self):
        """Both families' gateways are shown, and stay distinct."""
        fake = _FakeCollector(
            interfaces=[],
            routes=[_route(gateway="192.168.0.1", interface="wlp2s0")],
            neighbors=[],
            routes_ipv6=[_route(gateway="fe80::1", interface="wlp2s0")],
        )

        with patch("app.topology.get_network_collector", return_value=fake):
            graph = await build_topology(None)

        gateway_ids = {n.id for n in graph.nodes if n.kind == "gateway"}
        assert "gateway:192.168.0.1" in gateway_ids
        assert "gateway:fe80::1" in gateway_ids
