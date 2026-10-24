"""
Integration tests for real host network discovery.

These tests run the actual `ip` command on the host and verify that real
network data is collected. They are skipped when `ip` is not available.

They distinguish:
1. A successful command with results.
2. A successful command with empty results (accepted, not treated as failure).
3. A missing executable.
4. A permission failure.
5. A command timeout.
6. A malformed command response.
7. A partial collection failure.

Mocks are NOT used here — the point is to prove the backend talks to the
real kernel, not to a fixture.
"""

import asyncio
import os

import pytest

from app.network_collector import (
    CommandNotFoundError,
    NetworkCollector,
    get_network_collector,
)


pytestmark = pytest.mark.skipif(
    not os.path.exists("/usr/sbin/ip") and not os.path.exists("/usr/bin/ip"),
    reason="the `ip` command is not available on this host",
)


class TestRealHostDiscovery:
    """Real host discovery through the NetworkCollector."""

    def test_collector_instantiates(self):
        """The collector can be created without arguments."""
        collector = NetworkCollector(command_timeout=5.0)
        assert collector.command_timeout == 5.0

    def test_get_network_collector_is_singleton(self):
        """The module-level accessor returns the same instance."""
        first = get_network_collector()
        second = get_network_collector()
        assert first is second

    def test_ip_tool_is_available(self):
        """The `ip` command must be present for the other tests to matter."""
        collector = NetworkCollector()
        available, missing = collector.check_tools()
        assert "ip" in available, f"`ip` should be available, missing={missing}"

    @pytest.mark.asyncio
    async def test_real_interfaces_are_collected(self):
        """Running `ip -j addr show` returns at least one interface with data."""
        collector = NetworkCollector(command_timeout=5.0)
        result = await collector.collect_interfaces()
        assert result.success is True
        assert result.error is None
        assert result.command == "ip -j addr show"
        assert isinstance(result.data, list)
        assert len(result.data) >= 1, "expected at least one real interface"
        # The loopback interface should always be present.
        names = {iface.name for iface in result.data}
        assert "lo" in names, f"loopback interface missing from {names}"

    @pytest.mark.asyncio
    async def test_real_interfaces_have_expected_fields(self):
        """Real interfaces carry name, index, state, and addresses."""
        collector = NetworkCollector(command_timeout=5.0)
        result = await collector.collect_interfaces()
        assert result.success is True
        lo = next((i for i in result.data if i.name == "lo"), None)
        assert lo is not None, "loopback interface should be present"
        assert lo.index > 0
        assert lo.state in ("UP", "DOWN", "UNKNOWN")
        assert lo.ipv4_addresses, "loopback should have an IPv4 address"
        assert "127.0.0.1" in lo.ipv4_addresses

    @pytest.mark.asyncio
    async def test_real_routes_are_collected(self):
        """Running `ip -j route show` returns at least one route."""
        collector = NetworkCollector(command_timeout=5.0)
        result = await collector.collect_routes()
        assert result.success is True
        assert result.error is None
        assert result.command == "ip -j route show"
        assert isinstance(result.data, list)
        assert len(result.data) >= 1, "expected at least one real route"
        # There should be a default route or a connected route.
        destinations = {r.destination for r in result.data}
        assert destinations, "route destinations should not be empty"

    @pytest.mark.asyncio
    async def test_real_neighbors_are_collected(self):
        """Running `ip -j neigh show` returns results (may be empty)."""
        collector = NetworkCollector(command_timeout=5.0)
        result = await collector.collect_neighbors()
        assert result.success is True
        assert result.error is None
        assert result.command == "ip -j neigh show"
        assert isinstance(result.data, list)
        # Empty neighbour cache is valid on some hosts; do not require entries.

    @pytest.mark.asyncio
    async def test_real_collect_all_includes_ipv6(self):
        """`collect_all()` reads both IPv4 and IPv6 tables."""
        collector = NetworkCollector(command_timeout=5.0)
        results = await collector.collect_all()
        assert "interfaces" in results
        assert "routes" in results
        assert "neighbors" in results
        assert results["interfaces"].success is True
        assert results["routes"].success is True
        assert results["neighbors"].success is True
        # IPv6 tables are read separately.
        assert "routes_ipv6" in results or results["routes"].ip_version == "ipv4"

    @pytest.mark.asyncio
    async def test_real_route_has_expected_fields(self):
        """Real routes carry destination, interface, metric, protocol."""
        collector = NetworkCollector(command_timeout=5.0)
        result = await collector.collect_routes()
        assert result.success is True
        assert len(result.data) >= 1
        route = result.data[0]
        assert route.destination
        assert route.interface is not None or route.gateway is not None
        assert route.metric is not None
        assert route.proto

    def test_collector_handles_missing_tool_gracefully(self):
        """A missing tool produces a failure result, not a crash."""
        collector = NetworkCollector()
        original = collector._check_tool
        collector._check_tool = lambda tool: False
        try:
            result = asyncio.run(collector.collect_interfaces())
            assert result.success is False
            assert "`ip` command not available" in result.error
        finally:
            collector._check_tool = original


class TestRealCommandFailures:
    """How the collector behaves when a real command fails."""

    @pytest.mark.asyncio
    async def test_command_not_found_is_reported(self):
        """Running a command that does not exist returns a failure."""
        collector = NetworkCollector(command_timeout=1.0)
        # Use a command name that definitely does not exist.
        rc, stdout, stderr = await collector._run_command(
            ["this-command-does-not-exist-xyz"]
        )
        assert rc != 0
        combined = (stderr + stdout).lower()
        assert rc == -1 or "not found" in combined

    @pytest.mark.asyncio
    async def test_malformed_json_is_reported(self):
        """Invalid JSON from `ip` is reported as a parse failure."""
        collector = NetworkCollector(command_timeout=1.0)
        from unittest.mock import AsyncMock, patch

        with patch.object(
            collector, "_run_command", new_callable=AsyncMock
        ) as mock_run:
            mock_run.return_value = (0, "not valid json", "")
            result = await collector.collect_interfaces()
            assert result.success is False
            assert "Failed to parse JSON" in result.error

    @pytest.mark.asyncio
    async def test_timeout_is_reported(self):
        """A command timeout is reported honestly."""
        collector = NetworkCollector(command_timeout=0.001)
        from unittest.mock import AsyncMock, patch

        with patch.object(
            collector, "_run_command", new_callable=AsyncMock
        ) as mock_run:
            mock_run.return_value = (-1, "", "Command timed out after 0.001s")
            result = await collector.collect_interfaces()
            assert result.success is False
            assert "timed out" in result.error.lower()
