"""
Tests for the NetworkCollector module.
"""

import json
import pytest
import asyncio
import socket
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from app.network_collector import (
    NetworkCollector,
    CollectionResult,
    InterfaceInfo,
    RouteInfo,
    NeighborInfo,
    DnsRecord,
    DnsResolutionResult,
    ConnectivityResult,
    TracerouteHop,
    TracerouteResult,
    get_network_collector,
    CommandNotFoundError,
)


class TestNetworkCollector:
    """Tests for the NetworkCollector class."""

    @pytest.fixture
    def collector(self):
        """Create a NetworkCollector instance."""
        return NetworkCollector(command_timeout=1.0)

    @pytest.fixture
    def mock_interfaces_json(self):
        """Mock JSON output from `ip -j addr show`."""
        return [
            {
                "ifindex": 1,
                "ifname": "lo",
                "flags": ["LOOPBACK", "UP", "LOWER_UP"],
                "mtu": 65536,
                "operstate": "UP",
                "addr_info": [
                    {
                        "family": "inet",
                        "local": "127.0.0.1",
                        "prefixlen": 8,
                        "scope": "host"
                    },
                    {
                        "family": "inet6",
                        "local": "::1",
                        "prefixlen": 128,
                        "scope": "host"
                    }
                ]
            },
            {
                "ifindex": 2,
                "ifname": "eth0",
                "flags": ["BROADCAST", "MULTICAST", "UP", "LOWER_UP"],
                "mtu": 1500,
                "operstate": "UP",
                "address": "aa:bb:cc:dd:ee:ff",
                "addr_info": [
                    {
                        "family": "inet",
                        "local": "192.168.1.100",
                        "prefixlen": 24,
                        "scope": "global"
                    },
                    {
                        "family": "inet6",
                        "local": "fe80::aabb:ccdd:eeff:1234",
                        "prefixlen": 64,
                        "scope": "link"
                    }
                ]
            }
        ]

    @pytest.fixture
    def mock_routes_json(self):
        """Mock JSON output from `ip -j route show`."""
        return [
            {
                "dst": "192.168.1.0/24",
                "dev": "eth0",
                "protocol": "kernel",
                "scope": "link",
                "metric": 100,
                "prefsrc": "192.168.1.100"
            },
            {
                "dst": "default",
                "gateway": "192.168.1.1",
                "dev": "eth0",
                "protocol": "dhcp",
                "scope": "link",
                "metric": 100
            }
        ]

    @pytest.fixture
    def mock_neighbors_json(self):
        """Mock JSON output from `ip -j neigh show`."""
        return [
            {
                "dst": "192.168.1.1",
                "dev": "eth0",
                "lladdr": "aa:bb:cc:dd:ee:00",
                "state": "REACHABLE",
                "router": True
            },
            {
                "dst": "192.168.1.50",
                "dev": "eth0",
                "lladdr": "aa:bb:cc:dd:ee:50",
                "state": "STALE",
                "router": False
            },
            {
                "dst": "fe80::1",
                "dev": "eth0",
                "lladdr": "aa:bb:cc:dd:ee:01",
                "state": "REACHABLE",
                "router": True
            }
        ]

    def test_check_tools(self, collector):
        """Test tool availability checking."""
        available, missing = collector.check_tools()
        assert isinstance(available, list)
        assert isinstance(missing, list)
        assert "ip" in available or "ip" in missing

    def test_check_tools_caching(self, collector):
        """Test that tool checking is cached."""
        available1, missing1 = collector.check_tools()
        available2, missing2 = collector.check_tools()
        assert available1 == available2
        assert missing1 == missing2

    def test_parse_interface(self, collector, mock_interfaces_json):
        """Test parsing interface data from JSON."""
        lo_data = mock_interfaces_json[0]
        lo_iface = collector._parse_interface(lo_data)

        assert lo_iface.name == "lo"
        assert lo_iface.index == 1
        assert lo_iface.state == "UP"
        assert lo_iface.mtu == 65536
        assert "127.0.0.1" in lo_iface.ipv4_addresses
        assert "127.0.0.1/8" in lo_iface.ipv4_networks
        assert "::1" in lo_iface.ipv6_addresses
        assert "::1/128" in lo_iface.ipv6_networks
        assert lo_iface.mac_address is None

        eth0_data = mock_interfaces_json[1]
        eth0_iface = collector._parse_interface(eth0_data)

        assert eth0_iface.name == "eth0"
        assert eth0_iface.index == 2
        assert eth0_iface.state == "UP"
        assert eth0_iface.mtu == 1500
        assert eth0_iface.mac_address == "aa:bb:cc:dd:ee:ff"
        assert "192.168.1.100" in eth0_iface.ipv4_addresses
        assert "192.168.1.100/24" in eth0_iface.ipv4_networks
        assert "fe80::aabb:ccdd:eeff:1234" in eth0_iface.ipv6_addresses
        assert "fe80::aabb:ccdd:eeff:1234/64" in eth0_iface.ipv6_networks

    def test_parse_route(self, collector, mock_routes_json):
        """Test parsing route data from JSON."""
        route1_data = mock_routes_json[0]
        route1 = collector._parse_route(route1_data)

        assert route1.destination == "192.168.1.0/24"
        assert route1.gateway is None
        assert route1.interface == "eth0"
        assert route1.metric == 100
        assert route1.proto == "kernel"
        assert route1.scope == "link"
        assert route1.pref_src == "192.168.1.100"

        route2_data = mock_routes_json[1]
        route2 = collector._parse_route(route2_data)

        assert route2.destination == "0.0.0.0/0"
        assert route2.gateway == "192.168.1.1"
        assert route2.interface == "eth0"
        assert route2.metric == 100
        assert route2.proto == "dhcp"

    def test_parse_route_without_a_metric_records_zero(self, collector):
        """
        A route the kernel printed without a metric has metric zero.

        The kernel leaves the metric out when it is the default, so a
        missing metric is not an unknown one. Recording it as zero keeps
        this view and the analysis of the same table from disagreeing
        about the same route.
        """
        route = collector._parse_route(
            {
                "dst": "192.168.1.0/24",
                "dev": "eth0",
                "protocol": "kernel",
                "scope": "link",
                "prefsrc": "192.168.1.100",
            }
        )

        assert route.metric == 0

    def test_parse_neighbor(self, collector, mock_neighbors_json):
        """Test parsing neighbor data from JSON."""
        neigh1_data = mock_neighbors_json[0]
        neigh1 = collector._parse_neighbor(neigh1_data)

        assert neigh1.ip_address == "192.168.1.1"
        assert neigh1.interface == "eth0"
        assert neigh1.mac_address == "aa:bb:cc:dd:ee:00"
        assert neigh1.state == "REACHABLE"
        assert neigh1.is_router is True

        neigh2_data = mock_neighbors_json[1]
        neigh2 = collector._parse_neighbor(neigh2_data)

        assert neigh2.ip_address == "192.168.1.50"
        assert neigh2.is_router is False

        neigh3_data = mock_neighbors_json[2]
        neigh3 = collector._parse_neighbor(neigh3_data)

        assert neigh3.ip_address == "fe80::1"
        assert neigh3.is_router is True

    @pytest.mark.asyncio
    async def test_collect_interfaces_success(self, collector, mock_interfaces_json):
        """Test successful interface collection."""
        with patch.object(collector, '_run_command', new_callable=AsyncMock) as mock_run:
            mock_run.return_value = (0, json.dumps(mock_interfaces_json), "")

            result = await collector.collect_interfaces()

            assert result.success is True
            assert result.error is None
            assert len(result.data) == 2
            assert all(isinstance(iface, InterfaceInfo) for iface in result.data)
            assert result.data[0].name == "lo"
            assert result.data[1].name == "eth0"
            assert result.command == "ip -j addr show"
            assert result.duration_ms > 0

    @pytest.mark.asyncio
    async def test_collect_interfaces_command_not_found(self, collector):
        """Test interface collection when `ip` command not found."""
        with patch.object(collector, '_check_tool', return_value=False):
            result = await collector.collect_interfaces()

            assert result.success is False
            assert "`ip` command not available" in result.error

    @pytest.mark.asyncio
    async def test_collect_interfaces_command_failed(self, collector):
        """Test interface collection when command fails."""
        with patch.object(collector, '_run_command', new_callable=AsyncMock) as mock_run:
            mock_run.return_value = (1, "", "RTNETLINK answers: Operation not permitted")

            result = await collector.collect_interfaces()

            assert result.success is False
            assert "Command failed" in result.error

    @pytest.mark.asyncio
    async def test_collect_interfaces_invalid_json(self, collector):
        """Test interface collection with invalid JSON output."""
        with patch.object(collector, '_run_command', new_callable=AsyncMock) as mock_run:
            mock_run.return_value = (0, "not valid json", "")

            result = await collector.collect_interfaces()

            assert result.success is False
            assert "Failed to parse JSON" in result.error

    @pytest.mark.asyncio
    async def test_collect_routes_success(self, collector, mock_routes_json):
        """Test successful route collection."""
        with patch.object(collector, '_run_command', new_callable=AsyncMock) as mock_run:
            mock_run.return_value = (0, json.dumps(mock_routes_json), "")

            result = await collector.collect_routes()

            assert result.success is True
            assert result.error is None
            assert len(result.data) == 2
            assert all(isinstance(route, RouteInfo) for route in result.data)
            assert result.data[0].destination == "192.168.1.0/24"
            assert result.data[1].destination == "0.0.0.0/0"
            assert result.command == "ip -j route show"

    @pytest.mark.asyncio
    async def test_collect_neighbors_success(self, collector, mock_neighbors_json):
        """Test successful neighbor collection."""
        with patch.object(collector, '_run_command', new_callable=AsyncMock) as mock_run:
            mock_run.return_value = (0, json.dumps(mock_neighbors_json), "")

            result = await collector.collect_neighbors()

            assert result.success is True
            assert result.error is None
            assert len(result.data) == 3
            assert all(isinstance(neigh, NeighborInfo) for neigh in result.data)
            assert result.data[0].ip_address == "192.168.1.1"
            assert result.data[0].is_router is True
            assert result.data[1].is_router is False
            assert result.command == "ip -j neigh show"

    @pytest.mark.asyncio
    async def test_collect_all(self, collector, mock_interfaces_json, mock_routes_json, mock_neighbors_json):
        """Test collecting all network data in parallel."""
        async def mock_run_command(cmd, timeout=None):
            if "addr" in cmd:
                return (0, json.dumps(mock_interfaces_json), "")
            elif "route" in cmd:
                return (0, json.dumps(mock_routes_json), "")
            elif "neigh" in cmd:
                return (0, json.dumps(mock_neighbors_json), "")
            return (-1, "", "unknown")

        with patch.object(collector, '_run_command', new_callable=AsyncMock) as mock_run:
            mock_run.side_effect = mock_run_command

            results = await collector.collect_all()

            assert "interfaces" in results
            assert "routes" in results
            assert "neighbors" in results
            assert results["interfaces"].success is True
            assert results["routes"].success is True
            assert results["neighbors"].success is True

    def test_collection_result_dataclass(self):
        """Test CollectionResult dataclass."""
        result = CollectionResult(
            timestamp="2024-01-01T00:00:00Z",
            success=True,
            data={"test": "data"},
            command="ip -j addr show",
            duration_ms=10.5,
        )
        assert result.success is True
        assert result.data == {"test": "data"}
        assert result.command == "ip -j addr show"
        assert result.duration_ms == 10.5

        failed = CollectionResult(
            timestamp="2024-01-01T00:00:00Z",
            success=False,
            error="Command failed",
        )
        assert failed.success is False
        assert failed.error == "Command failed"

    def test_interface_info_dataclass(self):
        """Test InterfaceInfo dataclass."""
        iface = InterfaceInfo(
            name="eth0",
            index=2,
            state="UP",
            mtu=1500,
            mac_address="aa:bb:cc:dd:ee:ff",
            ipv4_addresses=["192.168.1.100"],
            ipv4_networks=["192.168.1.100/24"],
            ipv6_addresses=["fe80::1"],
            ipv6_networks=["fe80::1/64"],
            flags=["UP", "BROADCAST"],
        )
        assert iface.name == "eth0"
        assert iface.ipv4_addresses == ["192.168.1.100"]
        assert iface.mac_address == "aa:bb:cc:dd:ee:ff"

    def test_route_info_dataclass(self):
        """Test RouteInfo dataclass."""
        route = RouteInfo(
            destination="192.168.1.0/24",
            gateway="192.168.1.1",
            interface="eth0",
            metric=100,
            proto="kernel",
            scope="link",
            pref_src="192.168.1.100",
        )
        assert route.destination == "192.168.1.0/24"
        assert route.gateway == "192.168.1.1"
        assert route.metric == 100

        default_route = RouteInfo(
            destination="0.0.0.0/0",
            gateway="192.168.1.1",
            interface="eth0",
        )
        assert default_route.destination == "0.0.0.0/0"

    def test_neighbor_info_dataclass(self):
        """Test NeighborInfo dataclass."""
        neigh = NeighborInfo(
            ip_address="192.168.1.1",
            interface="eth0",
            mac_address="aa:bb:cc:dd:ee:ff",
            state="REACHABLE",
            is_router=True,
        )
        assert neigh.ip_address == "192.168.1.1"
        assert neigh.state == "REACHABLE"
        assert neigh.is_router is True

    def test_get_network_collector_singleton(self):
        """Test that get_network_collector returns singleton."""
        collector1 = get_network_collector()
        collector2 = get_network_collector()
        assert collector1 is collector2


class TestNetworkCollectorEdgeCases:
    """Tests for edge cases and error handling."""

    @pytest.fixture
    def collector(self):
        return NetworkCollector(command_timeout=1.0)

    @pytest.mark.asyncio
    async def test_collect_interfaces_empty_output(self, collector):
        """Test interface collection with empty output."""
        with patch.object(collector, '_run_command', new_callable=AsyncMock) as mock_run:
            mock_run.return_value = (0, "[]", "")

            result = await collector.collect_interfaces()

            assert result.success is True
            assert result.data == []

    @pytest.mark.asyncio
    async def test_collect_routes_empty_output(self, collector):
        """Test route collection with empty output."""
        with patch.object(collector, '_run_command', new_callable=AsyncMock) as mock_run:
            mock_run.return_value = (0, "[]", "")

            result = await collector.collect_routes()

            assert result.success is True
            assert result.data == []

    @pytest.mark.asyncio
    async def test_collect_neighbors_empty_output(self, collector):
        """Test neighbor collection with empty output."""
        with patch.object(collector, '_run_command', new_callable=AsyncMock) as mock_run:
            mock_run.return_value = (0, "[]", "")

            result = await collector.collect_neighbors()

            assert result.success is True
            assert result.data == []

    @pytest.mark.asyncio
    async def test_collect_interfaces_timeout(self, collector):
        """Test interface collection timeout."""
        with patch.object(collector, '_run_command', new_callable=AsyncMock) as mock_run:
            mock_run.return_value = (-1, "", "Command timed out after 1.0s")

            result = await collector.collect_interfaces()

            assert result.success is False
            assert "timed out" in result.error.lower()

    @pytest.mark.asyncio
    async def test_collect_all_partial_failure(self, collector):
        """Test collect_all when one collection fails."""
        async def mock_run_command(cmd, timeout=None):
            if "addr" in cmd:
                return (0, "[]", "")
            elif "route" in cmd:
                return (1, "", "Permission denied")
            elif "neigh" in cmd:
                return (0, "[]", "")
            return (-1, "", "unknown")

        with patch.object(collector, '_run_command', new_callable=AsyncMock) as mock_run:
            mock_run.side_effect = mock_run_command

            results = await collector.collect_all()

            assert results["interfaces"].success is True
            assert results["routes"].success is False
            assert results["neighbors"].success is True


class TestDnsResolution:
    """Tests for DNS resolution functionality."""

    @pytest.fixture
    def collector(self):
        return NetworkCollector(command_timeout=1.0)

    @pytest.mark.asyncio
    async def test_resolve_dns_success_ipv4(self, collector):
        """Test successful DNS resolution for IPv4."""
        # Mock the event loop's getaddrinfo
        mock_addrinfo = [
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, '', ('93.184.216.34', 0)),
        ]
        
        with patch('asyncio.get_running_loop') as mock_get_loop:
            mock_loop = AsyncMock()
            mock_loop.getaddrinfo = AsyncMock(return_value=[
                (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, '', ('93.184.216.34', 0)),
            ])
            mock_get_loop.return_value = mock_loop
            
            result = await collector.resolve_dns("example.com", timeout=5.0)
            
            assert result.success is True
            assert result.hostname == "example.com"
            assert len(result.addresses) == 1
            assert result.addresses[0].address == "93.184.216.34"
            assert result.addresses[0].record_type == "A"
            assert result.latency_ms > 0
            assert result.error is None

    @pytest.mark.asyncio
    async def test_resolve_dns_success_ipv4_and_ipv6(self, collector):
        """Test successful DNS resolution with both IPv4 and IPv6."""
        with patch('asyncio.get_running_loop') as mock_get_loop:
            mock_loop = AsyncMock()
            mock_loop.getaddrinfo = AsyncMock(return_value=[
                (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, '', ('93.184.216.34', 0)),
                (socket.AF_INET6, socket.SOCK_STREAM, socket.IPPROTO_TCP, '', ('2606:2800:220:1:248:1893:25c8:1946', 0)),
            ])
            mock_get_loop.return_value = mock_loop
            
            result = await collector.resolve_dns("example.com", timeout=5.0, family=socket.AF_UNSPEC)
            
            assert result.success is True
            assert len(result.addresses) == 2
            # Should have both A and AAAA records
            record_types = {r.record_type for r in result.addresses}
            assert "A" in record_types
            assert "AAAA" in record_types

    @pytest.mark.asyncio
    async def test_resolve_dns_timeout(self, collector):
        """Test DNS resolution timeout handling."""
        with patch('asyncio.get_running_loop') as mock_get_loop:
            mock_loop = AsyncMock()
            mock_loop.getaddrinfo = AsyncMock(side_effect=asyncio.TimeoutError())
            mock_get_loop.return_value = mock_loop
            
            result = await collector.resolve_dns("example.com", timeout=0.001)
            
            assert result.success is False
            assert result.hostname == "example.com"
            assert len(result.addresses) == 0
            assert "timed out" in result.error.lower()
            assert result.latency_ms > 0

    @pytest.mark.asyncio
    async def test_resolve_dns_nxdomain(self, collector):
        """Test DNS resolution for non-existent domain."""
        with patch('asyncio.get_running_loop') as mock_get_loop:
            mock_loop = AsyncMock()
            mock_loop.getaddrinfo = AsyncMock(
                side_effect=socket.gaierror(socket.EAI_NONAME, "Name or service not known")
            )
            mock_get_loop.return_value = mock_loop
            
            result = await collector.resolve_dns("nonexistent.invalid", timeout=5.0)
            
            assert result.success is False
            assert result.hostname == "nonexistent.invalid"
            assert len(result.addresses) == 0
            assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_resolve_dns_servfail(self, collector):
        """Test DNS resolution with SERVFAIL."""
        with patch('asyncio.get_running_loop') as mock_get_loop:
            mock_loop = AsyncMock()
            mock_loop.getaddrinfo = AsyncMock(
                side_effect=socket.gaierror(socket.EAI_FAIL, "Non-recoverable failure")
            )
            mock_get_loop.return_value = mock_loop
            
            result = await collector.resolve_dns("example.com", timeout=5.0)
            
            assert result.success is False
            assert "failure" in result.error.lower()

    @pytest.mark.asyncio
    async def test_resolve_dns_invalid_hostname(self, collector):
        """Test DNS resolution with invalid/empty hostname."""
        # Test empty string
        result = await collector.resolve_dns("", timeout=5.0)
        assert result.success is False
        assert "invalid" in result.error.lower() or "empty" in result.error.lower()
        
        # Test whitespace only
        result = await collector.resolve_dns("   ", timeout=5.0)
        assert result.success is False
        assert "empty" in result.error.lower() or "invalid" in result.error.lower()
        
        # Test None
        result = await collector.resolve_dns(None, timeout=5.0)
        assert result.success is False
        assert "invalid" in result.error.lower()

    @pytest.mark.asyncio
    async def test_resolve_dns_ipv6_only(self, collector):
        """Test IPv6-only resolution."""
        with patch('asyncio.get_running_loop') as mock_get_loop:
            mock_loop = AsyncMock()
            mock_loop.getaddrinfo = AsyncMock(return_value=[
                (socket.AF_INET6, socket.SOCK_STREAM, socket.IPPROTO_TCP, '', 
                 ('2606:2800:220:1:248:1893:25c8:1946', 0, 0, 0)),
            ])
            mock_get_loop.return_value = mock_loop
            
            result = await collector.resolve_dns("example.com", timeout=5.0, family=socket.AF_INET6)
            
            assert result.success is True
            assert len(result.addresses) == 1
            assert result.addresses[0].record_type == "AAAA"
            assert ":" in result.addresses[0].address

    def test_dns_record_dataclass(self):
        """Test DnsRecord dataclass."""
        record = DnsRecord(
            hostname="example.com",
            address="93.184.216.34",
            record_type="A",
            ttl=3600,
        )
        assert record.hostname == "example.com"
        assert record.address == "93.184.216.34"
        assert record.record_type == "A"
        assert record.ttl == 3600

    def test_dns_resolution_result_dataclass(self):
        """Test DnsResolutionResult dataclass."""
        record = DnsRecord(hostname="example.com", address="93.184.216.34", record_type="A")
        result = DnsResolutionResult(
            hostname="example.com",
            addresses=[record],
            latency_ms=15.5,
        )
        assert result.hostname == "example.com"
        assert len(result.addresses) == 1
        assert result.latency_ms == 15.5
        assert result.error is None

        # Test failed result
        failed = DnsResolutionResult(
            hostname="invalid.com",
            addresses=[],
            latency_ms=5000.0,
            error="DNS resolution timed out after 5.0s",
        )
        assert failed.success is False
        assert failed.error == "DNS resolution timed out after 5.0s"


class TestConnectivityCheck:
    """Tests for connectivity check functionality."""

    @pytest.fixture
    def collector(self):
        return NetworkCollector(command_timeout=1.0)

    @pytest.mark.asyncio
    async def test_check_connectivity_icmp_success(self, collector):
        """Test successful ICMP ping."""
        with patch.object(collector, '_run_command', new_callable=AsyncMock) as mock_run:
            mock_run.return_value = (0, "3 packets transmitted, 3 received, 0% packet loss, time 2002ms\nrtt min/avg/max/mdev = 10.5/47.0/92.0/32.0 ms", "")
            
            result = await collector.check_connectivity("8.8.8.8", protocol="icmp")
            
            assert result.reachable is True
            assert result.protocol == "icmp"
            assert result.target == "8.8.8.8"
            assert result.packets_sent == 3
            assert result.packets_received == 3
            assert result.packet_loss_percent == 0.0
            assert result.rtt_avg_ms == 47.0
            assert result.error is None

    @pytest.mark.asyncio
    async def test_check_connectivity_icmp_failure(self, collector):
        """Test failed ICMP ping."""
        with patch.object(collector, '_run_command', new_callable=AsyncMock) as mock_run:
            mock_run.return_value = (1, "", "Destination Host Unreachable")
            
            result = await collector.check_connectivity("192.168.99.99", protocol="icmp")
            
            assert result.reachable is False
            assert result.protocol == "icmp"
            assert result.packets_received == 0
            assert result.packet_loss_percent == 100.0

    @pytest.mark.asyncio
    async def test_check_connectivity_tcp_success(self, collector):
        """Test successful TCP connect."""
        with patch('asyncio.get_running_loop') as mock_get_loop:
            mock_loop = AsyncMock()
            mock_loop.getaddrinfo = AsyncMock(return_value=[
                (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, '', ('93.184.216.34', 80)),
            ])
            mock_get_loop.return_value = mock_loop
            
            with patch('asyncio.open_connection', new_callable=AsyncMock) as mock_open:
                mock_reader = AsyncMock()
                # close() is called synchronously by the adapter; wait_closed() is awaited.
                mock_writer = MagicMock()
                mock_writer.close = MagicMock()
                mock_writer.wait_closed = AsyncMock()
                mock_open.return_value = (mock_reader, mock_writer)
                
                result = await collector.check_connectivity("example.com", port=80, protocol="tcp")
                
                assert result.reachable is True
                assert result.protocol == "tcp"
                assert result.target == "example.com"
                assert result.port == 80
                assert result.error is None

    @pytest.mark.asyncio
    async def test_check_connectivity_tcp_refused(self, collector):
        """Test TCP connect refused."""
        with patch('asyncio.get_running_loop') as mock_get_loop:
            mock_loop = AsyncMock()
            mock_loop.getaddrinfo = AsyncMock(return_value=[
                (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, '', ('93.184.216.34', 80)),
            ])
            mock_get_loop.return_value = mock_loop
            
            with patch('asyncio.open_connection', new_callable=AsyncMock) as mock_open:
                mock_open.side_effect = ConnectionRefusedError("Connection refused")
                
                result = await collector.check_connectivity("example.com", port=80, protocol="tcp")
                
                assert result.reachable is False
                assert result.protocol == "tcp"
                assert "refused" in result.error.lower()

    @pytest.mark.asyncio
    async def test_check_connectivity_tcp_timeout(self, collector):
        """Test TCP connect timeout."""
        with patch('asyncio.get_running_loop') as mock_get_loop:
            mock_loop = AsyncMock()
            mock_loop.getaddrinfo = AsyncMock(return_value=[
                (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, '', ('93.184.216.34', 80)),
            ])
            mock_get_loop.return_value = mock_loop
            
            with patch('asyncio.open_connection', new_callable=AsyncMock) as mock_open:
                mock_open.side_effect = asyncio.TimeoutError()
                
                result = await collector.check_connectivity("example.com", port=80, protocol="tcp", timeout=0.001)
                
                assert result.reachable is False
                assert "failed" in result.error.lower() or "timeout" in result.error.lower()

    @pytest.mark.asyncio
    async def test_check_connectivity_tcp_no_port(self, collector):
        """Test TCP connect without port."""
        result = await collector.check_connectivity("example.com", protocol="tcp")
        
        assert result.reachable is False
        assert "port is required" in result.error.lower()

    @pytest.mark.asyncio
    async def test_check_connectivity_invalid_protocol(self, collector):
        """Test invalid protocol."""
        result = await collector.check_connectivity("example.com", protocol="udp")
        
        assert result.reachable is False
        assert "unsupported protocol" in result.error.lower()

    @pytest.mark.asyncio
    async def test_check_connectivity_tcp_no_addrinfo(self, collector):
        """Test TCP connect when getaddrinfo returns no results."""
        with patch('asyncio.get_running_loop') as mock_get_loop:
            mock_loop = AsyncMock()
            mock_loop.getaddrinfo = AsyncMock(return_value=[])
            mock_get_loop.return_value = mock_loop
            
            result = await collector.check_connectivity("example.com", port=80, protocol="tcp")
            
            assert result.reachable is False
            assert "could not resolve" in result.error.lower()

    @pytest.mark.asyncio
    async def test_check_connectivity_tcp_dns_timeout(self, collector):
        """Test TCP connect with DNS timeout."""
        with patch('asyncio.get_running_loop') as mock_get_loop:
            mock_loop = AsyncMock()
            mock_loop.getaddrinfo = AsyncMock(side_effect=asyncio.TimeoutError())
            mock_get_loop.return_value = mock_loop
    
            result = await collector.check_connectivity("example.com", port=80, protocol="tcp", timeout=0.001)
    
            assert result.reachable is False
            assert "timed out" in result.error.lower() or "timeout" in result.error.lower()

    @pytest.mark.asyncio
    async def test_check_connectivity_tcp_invalid_port(self, collector):
        """Test TCP connect with invalid port."""
        result = await collector.check_connectivity("example.com", port=0, protocol="tcp")
        
        assert result.reachable is False
        assert "invalid port" in result.error.lower()
        
        result = await collector.check_connectivity("example.com", port=70000, protocol="tcp")
        assert result.reachable is False
        assert "invalid port" in result.error.lower()

    def test_connectivity_result_dataclass(self):
        """Test ConnectivityResult dataclass."""
        result = ConnectivityResult(
            target="example.com",
            port=80,
            protocol="tcp",
            reachable=True,
            latency_ms=15.5,
        )
        assert result.target == "example.com"
        assert result.port == 80
        assert result.protocol == "tcp"
        assert result.reachable is True
        assert result.latency_ms == 15.5

        # Test ICMP result
        icmp_result = ConnectivityResult(
            target="8.8.8.8",
            port=None,
            protocol="icmp",
            reachable=True,
            latency_ms=47.0,
            packets_sent=3,
            packets_received=3,
            packet_loss_percent=0.0,
            rtt_min_ms=10.5,
            rtt_avg_ms=47.0,
            rtt_max_ms=92.0,
            rtt_mdev_ms=32.0,
        )
        assert icmp_result.target == "8.8.8.8"
        assert icmp_result.port is None
        assert icmp_result.protocol == "icmp"
        assert icmp_result.packets_sent == 3
        assert icmp_result.packet_loss_percent == 0.0


class TestTraceroute:
    """Tests for traceroute functionality."""

    @pytest.fixture
    def collector(self):
        return NetworkCollector(command_timeout=1.0)

    @pytest.mark.asyncio
    async def test_trace_route_success(self, collector):
        """Test successful traceroute."""
        mock_output = """traceroute to 8.8.8.8 (8.8.8.8), 30 hops max, 60 byte packets
 1  192.168.1.1  1.234 ms  1.123 ms  1.456 ms
 2  10.0.0.1  2.345 ms  2.234 ms  2.567 ms
 3  8.8.8.8  10.5 ms  11.2 ms  10.8 ms"""
        
        with patch.object(collector, '_check_tool', return_value=True):
            with patch.object(collector, '_run_command', new_callable=AsyncMock) as mock_run:
                mock_run.return_value = (0, mock_output, "")
                
                result = await collector.trace_route("8.8.8.8", max_hops=30, timeout_per_hop=2.0)
                
                assert result.success is True
                assert result.target == "8.8.8.8"
                assert len(result.hops) == 3
                assert result.hops[0].ttl == 1
                assert result.hops[0].address == "192.168.1.1"
                assert result.hops[0].rtt_ms is not None
                assert result.hops[2].address == "8.8.8.8"
                assert result.completed is True

    @pytest.mark.asyncio
    async def test_trace_route_with_timeouts(self, collector):
        """Test traceroute with some hops timing out."""
        mock_output = """traceroute to 8.8.8.8 (8.8.8.8), 30 hops max, 60 byte packets
 1  192.168.1.1  1.234 ms  1.123 ms  1.456 ms
 2  * * *
 3  10.0.0.1  2.345 ms  2.234 ms  2.567 ms"""
        
        with patch.object(collector, '_check_tool', return_value=True):
            with patch.object(collector, '_run_command', new_callable=AsyncMock) as mock_run:
                mock_run.return_value = (0, mock_output, "")
                
                result = await collector.trace_route("8.8.8.8", max_hops=30, timeout_per_hop=2.0)
                
                assert result.success is True
                assert len(result.hops) == 3
                assert result.hops[0].address == "192.168.1.1"
                assert result.hops[1].error == "timeout"
                assert result.hops[2].address == "10.0.0.1"

    @pytest.mark.asyncio
    async def test_trace_route_command_not_found(self, collector):
        """Test traceroute when command not available."""
        with patch.object(collector, '_check_tool', return_value=False):
            result = await collector.trace_route("8.8.8.8")
            
            assert result.success is False
            assert result.error is not None
            assert "not available" in result.error.lower()

    @pytest.mark.asyncio
    async def test_trace_route_command_failed(self, collector):
        """Test traceroute when command fails."""
        with patch.object(collector, '_check_tool', return_value=True):
            with patch.object(collector, '_run_command', new_callable=AsyncMock) as mock_run:
                mock_run.return_value = (1, "", "Network is unreachable")
                
                result = await collector.trace_route("8.8.8.8")
                
                assert result.success is False
                assert result.error is not None
                assert "unreachable" in result.error.lower() or "failed" in result.error.lower()

    @pytest.mark.asyncio
    async def test_trace_route_timeout(self, collector):
        """Test traceroute overall timeout."""
        with patch.object(collector, '_check_tool', return_value=True):
            with patch.object(collector, '_run_command', new_callable=AsyncMock) as mock_run:
                mock_run.return_value = (-1, "", "Command timed out after 60.0s")
                
                result = await collector.trace_route("8.8.8.8", overall_timeout=0.001)
                
                assert result.success is False
                assert "timed out" in result.error.lower()

    @pytest.mark.asyncio
    async def test_trace_route_partial_output(self, collector):
        """Test traceroute with partial output on failure."""
        mock_output = """traceroute to 8.8.8.8 (8.8.8.8), 30 hops max, 60 byte packets
 1  192.168.1.1  1.234 ms  1.123 ms  1.456 ms"""
        
        with patch.object(collector, '_check_tool', return_value=True):
            with patch.object(collector, '_run_command', new_callable=AsyncMock) as mock_run:
                mock_run.return_value = (1, mock_output, "Permission denied")
                
                result = await collector.trace_route("8.8.8.8")
                
                assert result.success is False
                assert len(result.hops) == 1  # Partial output captured
                assert result.hops[0].address == "192.168.1.1"

    @pytest.mark.asyncio
    async def test_trace_route_max_hops_clamped(self, collector):
        """Test that max_hops is clamped to valid range."""
        mock_output = """traceroute to 8.8.8.8 (8.8.8.8), 10 hops max, 60 byte packets
 1  192.168.1.1  1.234 ms"""
        
        with patch.object(collector, '_run_command', new_callable=AsyncMock) as mock_run:
            mock_run.return_value = (0, mock_output, "")
            
            # Test max_hops > 64 gets clamped
            result = await collector.trace_route("8.8.8.8", max_hops=100)
            assert result.max_hops == 64
            
            # Test max_hops < 1 gets clamped
            result = await collector.trace_route("8.8.8.8", max_hops=0)
            assert result.max_hops == 1

    def test_traceroute_hop_dataclass(self):
        """Test TracerouteHop dataclass."""
        hop = TracerouteHop(
            ttl=1,
            address="192.168.1.1",
            hostname="gateway",
            rtt_ms=1.5,
        )
        assert hop.ttl == 1
        assert hop.address == "192.168.1.1"
        assert hop.hostname == "gateway"
        assert hop.rtt_ms == 1.5
        assert hop.error is None

    def test_traceroute_result_dataclass(self):
        """Test TracerouteResult dataclass."""
        hop = TracerouteHop(ttl=1, address="192.168.1.1", rtt_ms=1.5)
        result = TracerouteResult(
            target="8.8.8.8",
            hops=[hop],
            max_hops=30,
            timeout_per_hop=2.0,
            probes_per_hop=1,
            completed=True,
            total_time_ms=150.0,
        )
        assert result.target == "8.8.8.8"
        assert len(result.hops) == 1
        assert result.success is True
        assert result.completed is True

        # Test failed result
        failed = TracerouteResult(
            target="8.8.8.8",
            hops=[],
            max_hops=30,
            timeout_per_hop=2.0,
            probes_per_hop=1,
            completed=False,
            total_time_ms=60000.0,
            error="Command timed out",
        )
        assert failed.success is False
        assert failed.error == "Command timed out"

# --------------------------------------------------------------------------
# IPv6 route and neighbour collection
#
# The fixtures below are verbatim output from the Linux kernel, captured with
# `ip -j -6 route show` and `ip -j -6 neigh show`. They are not hand-written.
#
# The multi-route table came from a real network namespace:
#
#     unshare -rn bash -c '
#         ip link set lo up
#         ip link add veth0 type veth peer name veth1
#         ip -6 addr add 2001:db8::1/64 dev veth0
#         ip link set veth0 up
#         ip -6 route add 2001:db8:1::/48 dev veth0 proto static metric 100
#         ip -6 route add 2001:db8:2::/48 dev veth0 proto static metric 100
#         ip -6 route add default via fe80::1 dev veth0 proto static metric 1024
#         ip -6 -j route show'
#
# The neighbour entry came from the same kind of namespace. INCOMPLETE is a
# real state the kernel records when a neighbour solicitation has not been
# answered; the entry exists either way.
#
# The single-route table is this machine's own IPv6 routing table.
# --------------------------------------------------------------------------


REAL_IPV6_ROUTES_NAMESPACE = [
    {
        "dst": "2001:db8::/64",
        "dev": "veth0",
        "protocol": "kernel",
        "metric": 256,
        "flags": ["linkdown"],
        "pref": "medium",
    },
    {
        "dst": "2001:db8:1::/48",
        "dev": "veth0",
        "protocol": "static",
        "metric": 100,
        "flags": ["linkdown"],
        "pref": "medium",
    },
    {
        "dst": "2001:db8:2::/48",
        "dev": "veth0",
        "protocol": "static",
        "metric": 100,
        "flags": ["linkdown"],
        "pref": "medium",
    },
    {
        "dst": "default",
        "gateway": "fe80::1",
        "dev": "veth0",
        "protocol": "static",
        "metric": 1024,
        "flags": ["linkdown"],
        "pref": "medium",
    },
]

REAL_IPV6_ROUTES_HOST = [
    {
        "dst": "fe80::/64",
        "dev": "wlp2s0",
        "protocol": "kernel",
        "metric": 1024,
        "flags": [],
        "pref": "medium",
    },
]

REAL_IPV6_NEIGHBORS = [
    {
        "dst": "2001:db8::2",
        "dev": "veth1",
        "state": ["INCOMPLETE"],
    },
]


class TestIPv6Collection:
    """The IPv6 routing table and neighbour cache are separate tables.

    The kernel keeps them apart from the IPv4 ones, so they have to be read
    with their own commands. These tests use verbatim kernel output.
    """

    @pytest.fixture
    def collector(self):
        return NetworkCollector(command_timeout=1.0)

    # -- route parsing ---------------------------------------------------

    def test_ipv6_default_route_becomes_ipv6_default(self, collector):
        """The kernel spells the default route "default" in both families.

        Parsing it as the IPv4 default would put an IPv4 route in the IPv6
        table, which is how the IPv6 table used to be wrong.
        """
        route = collector._parse_route(REAL_IPV6_ROUTES_NAMESPACE[3], "ipv6")

        assert route.destination == "::/0"
        assert route.gateway == "fe80::1"
        assert route.interface == "veth0"
        assert route.metric == 1024
        assert route.proto == "static"

    def test_ipv4_default_route_still_becomes_ipv4_default(self, collector):
        """The IPv4 default must not change."""
        route = collector._parse_route(
            {"dst": "default", "gateway": "192.168.0.1", "dev": "wlp2s0", "metric": 600},
            "ipv4",
        )

        assert route.destination == "0.0.0.0/0"
        assert route.gateway == "192.168.0.1"

    def test_parse_route_defaults_to_ipv4(self, collector):
        """Existing callers pass no family and must keep getting IPv4."""
        route = collector._parse_route({"dst": "default", "dev": "eth0"})

        assert route.destination == "0.0.0.0/0"

    def test_ipv6_explicit_prefixes_are_left_alone(self, collector):
        route = collector._parse_route(REAL_IPV6_ROUTES_NAMESPACE[1], "ipv6")

        assert route.destination == "2001:db8:1::/48"
        assert route.metric == 100

    def test_ipv6_host_route_table_parses(self, collector):
        route = collector._parse_route(REAL_IPV6_ROUTES_HOST[0], "ipv6")

        assert route.destination == "fe80::/64"
        assert route.interface == "wlp2s0"
        assert route.metric == 1024

    # -- route collection ------------------------------------------------

    @pytest.mark.asyncio
    async def test_collect_routes_ipv6_uses_the_ipv6_command(self, collector):
        """The IPv6 table is read with `ip -j -6 route show`."""
        with patch.object(collector, '_run_command', new_callable=AsyncMock) as mock_run:
            mock_run.return_value = (0, json.dumps(REAL_IPV6_ROUTES_NAMESPACE), "")

            result = await collector.collect_routes("ipv6")

            assert mock_run.call_args[0][0] == ["ip", "-j", "-6", "route", "show"]
            assert result.success is True
            assert result.ip_version == "ipv6"
            assert result.command == "ip -j -6 route show"
            assert len(result.data) == 4

    @pytest.mark.asyncio
    async def test_collect_routes_ipv4_uses_the_ipv4_command(self, collector):
        with patch.object(collector, '_run_command', new_callable=AsyncMock) as mock_run:
            mock_run.return_value = (0, json.dumps([]), "")

            result = await collector.collect_routes("ipv4")

            assert mock_run.call_args[0][0] == ["ip", "-j", "route", "show"]
            assert result.ip_version == "ipv4"
            assert result.command == "ip -j route show"

    @pytest.mark.asyncio
    async def test_collect_routes_defaults_to_ipv4(self, collector):
        """Existing callers pass no family and must keep reading IPv4."""
        with patch.object(collector, '_run_command', new_callable=AsyncMock) as mock_run:
            mock_run.return_value = (0, json.dumps([]), "")

            result = await collector.collect_routes()

            assert mock_run.call_args[0][0] == ["ip", "-j", "route", "show"]
            assert result.ip_version == "ipv4"

    @pytest.mark.asyncio
    async def test_collect_routes_ipv6_default_is_ipv6(self, collector):
        with patch.object(collector, '_run_command', new_callable=AsyncMock) as mock_run:
            mock_run.return_value = (0, json.dumps(REAL_IPV6_ROUTES_NAMESPACE), "")

            result = await collector.collect_routes("ipv6")

            destinations = [r.destination for r in result.data]
            assert "::/0" in destinations
            assert "0.0.0.0/0" not in destinations

    @pytest.mark.asyncio
    async def test_collect_routes_rejects_an_unknown_family(self, collector):
        with patch.object(collector, '_run_command', new_callable=AsyncMock) as mock_run:
            result = await collector.collect_routes("ipv7")

            assert result.success is False
            assert "Unsupported address family" in result.error
            mock_run.assert_not_called()

    # -- neighbour collection --------------------------------------------

    @pytest.mark.asyncio
    async def test_collect_neighbors_ipv6_uses_the_ipv6_command(self, collector):
        with patch.object(collector, '_run_command', new_callable=AsyncMock) as mock_run:
            mock_run.return_value = (0, json.dumps(REAL_IPV6_NEIGHBORS), "")

            result = await collector.collect_neighbors("ipv6")

            assert mock_run.call_args[0][0] == ["ip", "-j", "-6", "neigh", "show"]
            assert result.success is True
            assert result.ip_version == "ipv6"
            assert result.data[0].ip_address == "2001:db8::2"
            assert result.data[0].state == "INCOMPLETE"

    @pytest.mark.asyncio
    async def test_collect_neighbors_defaults_to_ipv4(self, collector):
        with patch.object(collector, '_run_command', new_callable=AsyncMock) as mock_run:
            mock_run.return_value = (0, json.dumps([]), "")

            result = await collector.collect_neighbors()

            assert mock_run.call_args[0][0] == ["ip", "-j", "neigh", "show"]
            assert result.ip_version == "ipv4"

    @pytest.mark.asyncio
    async def test_collect_neighbors_rejects_an_unknown_family(self, collector):
        with patch.object(collector, '_run_command', new_callable=AsyncMock) as mock_run:
            result = await collector.collect_neighbors("ipv5")

            assert result.success is False
            assert "Unsupported address family" in result.error
            mock_run.assert_not_called()

    # -- interfaces and collect_all --------------------------------------

    @pytest.mark.asyncio
    async def test_interfaces_result_says_it_covers_both_families(self, collector):
        with patch.object(collector, '_run_command', new_callable=AsyncMock) as mock_run:
            mock_run.return_value = (0, json.dumps([]), "")

            result = await collector.collect_interfaces()

            assert result.ip_version == "both"

    @pytest.mark.asyncio
    async def test_collect_all_includes_both_route_tables(self, collector):
        async def mock_run_command(cmd, timeout=None):
            if "route" in cmd and "-6" in cmd:
                return (0, json.dumps(REAL_IPV6_ROUTES_NAMESPACE), "")
            elif "route" in cmd:
                return (0, json.dumps([]), "")
            elif "neigh" in cmd:
                return (0, json.dumps([]), "")
            return (0, json.dumps([]), "")

        with patch.object(collector, '_run_command', new_callable=AsyncMock) as mock_run:
            mock_run.side_effect = mock_run_command

            results = await collector.collect_all()

            assert "routes" in results
            assert "routes_ipv6" in results
            assert "neighbors" in results
            assert "neighbors_ipv6" in results
            assert results["routes"].ip_version == "ipv4"
            assert results["routes_ipv6"].ip_version == "ipv6"
            assert results["neighbors"].ip_version == "ipv4"
            assert results["neighbors_ipv6"].ip_version == "ipv6"

    def test_collection_result_defaults_to_ipv4(self):
        """Existing constructions of CollectionResult keep working."""
        result = CollectionResult(
            timestamp="2024-01-01T00:00:00Z",
            success=True,
            data=[],
        )

        assert result.ip_version == "ipv4"
