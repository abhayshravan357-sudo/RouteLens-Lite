"""
RouteLens Lite - PacketLab Tests

Unit and integration tests for the virtual router lab adapter and API.
"""

import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock, patch, MagicMock
from ipaddress import IPv4Address, IPv4Network

from app.lab_adapter import (
    LabAdapter,
    InterfaceInfo,
    RouteInfo,
    NamespaceStatus,
    LabReadinessReport,
    LabComponent,
    ToolMissingError,
    LabOperationResult,
)
from app.packet_lab import PacketLab, LabState, LabStatus, SimulateRequest, SimulateResponse
from app.packet_lab_routes import (
    SimulateRequestModel,
    LabStatusResponse,
)
from app.main import app


class TestLabAdapter:
    """Tests for the LabAdapter class."""

    def test_tool_check(self):
        """Test that required tools are detected."""
        adapter = LabAdapter()
        available, missing = adapter.check_tools()
        assert "ip" in available
        assert "ping" in available
        assert "tcpdump" in available
        assert "timeout" in available
        assert len(missing) == 0

    def test_parse_ip_addr(self):
        """Test parsing of 'ip addr show' output."""
        adapter = LabAdapter()
        sample_output = """1: lo: <LOOPBACK,UP,LOWER_UP> mtu 65536 qdisc noqueue state UNKNOWN group default qlen 1000
    link/loopback 00:00:00:00:00:00 brd 00:00:00:00:00:00
    inet 127.0.0.1/8 scope host lo
       valid_lft forever preferred_lft forever
4: rlc0@if3: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc noqueue state UP group default qlen 1000
    link/ether 2a:aa:54:7e:54:b0 brd ff:ff:ff:ff:ff:ff link-netns rl260-router
    inet 192.168.10.2/24 scope global rlc0
       valid_lft forever preferred_lft forever"""
        interfaces = adapter._parse_ip_addr(sample_output)
        assert len(interfaces) == 2
        assert interfaces[0].name == "lo"
        assert interfaces[0].ipv4_address == "127.0.0.1"
        assert interfaces[0].ipv4_network == "127.0.0.1/8"
        assert interfaces[1].name == "rlc0"
        assert interfaces[1].ipv4_address == "192.168.10.2"
        assert interfaces[1].ipv4_network == "192.168.10.2/24"
        assert interfaces[1].mac_address == "2a:aa:54:7e:54:b0"
        assert interfaces[1].state == "UP"

    def test_parse_ip_route(self):
        """Test parsing of 'ip route show' output."""
        adapter = LabAdapter()
        sample_output = """default via 192.168.10.1 dev rlc0
192.168.10.0/24 dev rlc0 proto kernel scope link src 192.168.10.2"""
        routes = adapter._parse_ip_route(sample_output)
        assert len(routes) == 2
        assert routes[0].destination == "0.0.0.0/0"
        assert routes[0].gateway == "192.168.10.1"
        assert routes[0].interface == "rlc0"
        assert routes[1].destination == "192.168.10.0/24"
        assert routes[1].gateway is None
        assert routes[1].interface == "rlc0"

    @pytest.mark.asyncio
    async def test_get_namespace_status_not_exists(self):
        """Test getting status of non-existent namespace."""
        adapter = LabAdapter()
        status = await adapter.get_namespace_status("nonexistent-ns")
        assert status.exists is False
        assert status.accessible is False
        assert "does not exist" in status.error

    @pytest.mark.asyncio
    async def test_get_namespace_status_permission_denied(self):
        """Test getting status when permission is denied."""
        adapter = LabAdapter()
        # Mock _run_in_namespace to simulate permission denied
        with patch.object(adapter, '_run_in_namespace', new_callable=AsyncMock) as mock_run:
            mock_run.return_value = (-1, "", "Error executing command as another user: Request dismissed")
            status = await adapter.get_namespace_status("rl260-client")
            assert status.exists is True
            assert status.accessible is False
            assert "Permission denied" in status.error
            assert "Privilege escalation" in status.error

    @pytest.mark.asyncio
    async def test_get_namespace_status_generic_failure(self):
        """Test getting status when command fails for other reasons."""
        adapter = LabAdapter()
        with patch.object(adapter, '_run_in_namespace', new_callable=AsyncMock) as mock_run:
            mock_run.return_value = (-1, "", "Some other error")
            status = await adapter.get_namespace_status("rl260-client")
            assert status.exists is True
            assert status.accessible is False
            assert "Failed to get interfaces" in status.error

    @pytest.mark.asyncio
    async def test_check_lab_readiness_all_ready(self):
        """Test lab readiness when everything is ready."""
        adapter = LabAdapter()
        # Mock get_namespace_status to return ready namespaces
        mock_client = NamespaceStatus(
            name="rl260-client", exists=True, accessible=True,
            interfaces=[InterfaceInfo(name="rlc0", ipv4_network="192.168.10.2/24")],
            routes=[RouteInfo(destination="0.0.0.0/0", gateway="192.168.10.1", interface="rlc0")]
        )
        mock_router = NamespaceStatus(
            name="rl260-router", exists=True, accessible=True,
            interfaces=[
                InterfaceInfo(name="rlr0c", ipv4_network="192.168.10.1/24"),
                InterfaceInfo(name="rlr0s", ipv4_network="192.168.20.1/24"),
            ],
            routes=[
                RouteInfo(destination="192.168.10.0/24", gateway=None, interface="rlr0c"),
                RouteInfo(destination="192.168.20.0/24", gateway=None, interface="rlr0s"),
            ],
            ip_forward_enabled=True
        )
        mock_server = NamespaceStatus(
            name="rl260-server", exists=True, accessible=True,
            interfaces=[InterfaceInfo(name="rls0", ipv4_network="192.168.20.2/24")],
            routes=[
                RouteInfo(destination="0.0.0.0/0", gateway="192.168.20.1", interface="rls0"),
                RouteInfo(destination="192.168.20.0/24", gateway=None, interface="rls0"),
            ]
        )

        with patch.object(adapter, 'get_namespace_status', new_callable=AsyncMock) as mock_get:
            mock_get.side_effect = [mock_client, mock_router, mock_server]
            report = await adapter.check_lab_readiness()

        assert report.overall_ready is True
        assert "fully ready" in report.summary
        assert len(report.permission_issues) == 0
        assert len(report.missing_tools) == 0

    @pytest.mark.asyncio
    async def test_check_lab_readiness_permission_issues(self):
        """Test lab readiness when permission issues exist."""
        adapter = LabAdapter()
        mock_client = NamespaceStatus(
            name="rl260-client", exists=True, accessible=False,
            error="Permission denied accessing rl260-client. Privilege escalation (sudo/pkexec) not configured for web backend."
        )
        mock_router = NamespaceStatus(
            name="rl260-router", exists=True, accessible=False,
            error="Permission denied accessing rl260-router. Privilege escalation (sudo/pkexec) not configured for web backend."
        )
        mock_server = NamespaceStatus(
            name="rl260-server", exists=True, accessible=False,
            error="Permission denied accessing rl260-server. Privilege escalation (sudo/pkexec) not configured for web backend."
        )

        with patch.object(adapter, 'get_namespace_status', new_callable=AsyncMock) as mock_get:
            mock_get.side_effect = [mock_client, mock_router, mock_server]
            report = await adapter.check_lab_readiness()

        assert report.overall_ready is False
        assert len(report.permission_issues) == 3
        assert "Permission issues" in report.summary

    @pytest.mark.asyncio
    async def test_check_lab_readiness_missing_tools(self):
        """Test lab readiness when tools are missing."""
        adapter = LabAdapter()
        mock_client = NamespaceStatus(
            name="rl260-client", exists=True, accessible=True,
            interfaces=[InterfaceInfo(name="rlc0", ipv4_network="192.168.10.2/24")],
            routes=[RouteInfo(destination="0.0.0.0/0", gateway="192.168.10.1", interface="rlc0")]
        )
        mock_router = NamespaceStatus(
            name="rl260-router", exists=True, accessible=True,
            interfaces=[
                InterfaceInfo(name="rlr0c", ipv4_network="192.168.10.1/24"),
                InterfaceInfo(name="rlr0s", ipv4_network="192.168.20.1/24"),
            ],
            routes=[
                RouteInfo(destination="192.168.10.0/24", gateway=None, interface="rlr0c"),
                RouteInfo(destination="192.168.20.0/24", gateway=None, interface="rlr0s"),
            ],
            ip_forward_enabled=True
        )
        mock_server = NamespaceStatus(
            name="rl260-server", exists=True, accessible=True,
            interfaces=[InterfaceInfo(name="rls0", ipv4_network="192.168.20.2/24")],
            routes=[
                RouteInfo(destination="0.0.0.0/0", gateway="192.168.20.1", interface="rls0"),
                RouteInfo(destination="192.168.20.0/24", gateway=None, interface="rls0"),
            ]
        )

        with patch.object(adapter, 'check_tools', return_value=([], ["tcpdump"])):
            with patch.object(adapter, 'get_namespace_status', new_callable=AsyncMock) as mock_get:
                mock_get.side_effect = [mock_client, mock_router, mock_server]
                report = await adapter.check_lab_readiness()

        assert report.overall_ready is False
        assert "tcpdump" in report.missing_tools
        assert "Missing required tools" in report.summary

    @pytest.mark.asyncio
    async def test_check_lab_readiness_topology_issues(self):
        """Test lab readiness when topology is wrong."""
        adapter = LabAdapter()
        mock_client = NamespaceStatus(
            name="rl260-client", exists=True, accessible=True,
            interfaces=[InterfaceInfo(name="rlc0", ipv4_network="192.168.10.2/24")],
            routes=[RouteInfo(destination="0.0.0.0/0", gateway="192.168.10.1", interface="rlc0")]
        )
        mock_router = NamespaceStatus(
            name="rl260-router", exists=True, accessible=True,
            interfaces=[
                InterfaceInfo(name="rlr0c", ipv4_network="192.168.10.1/24"),
                InterfaceInfo(name="rlr0s", ipv4_network="192.168.20.1/24"),
            ],
            routes=[
                RouteInfo(destination="192.168.10.0/24", gateway=None, interface="rlr0c"),
                RouteInfo(destination="192.168.20.0/24", gateway=None, interface="rlr0s"),
            ],
            ip_forward_enabled=False  # Wrong!
        )
        mock_server = NamespaceStatus(
            name="rl260-server", exists=True, accessible=True,
            interfaces=[InterfaceInfo(name="rls0", ipv4_network="192.168.20.2/24")],
            routes=[
                RouteInfo(destination="0.0.0.0/0", gateway="192.168.20.1", interface="rls0"),
                RouteInfo(destination="192.168.20.0/24", gateway=None, interface="rls0"),
            ]
        )

        with patch.object(adapter, 'get_namespace_status', new_callable=AsyncMock) as mock_get:
            mock_get.side_effect = [mock_client, mock_router, mock_server]
            report = await adapter.check_lab_readiness()

        assert report.overall_ready is False
        assert "IP forwarding not enabled" in report.summary


class TestPacketLab:
    """Tests for the PacketLab class."""

    def test_state_machine_initial(self):
        """Test initial state."""
        lab = PacketLab()
        assert lab.current_state == LabState.IDLE

    @pytest.mark.asyncio
    async def test_get_status_lab_ready(self):
        """Test get_status when lab is ready."""
        mock_adapter = AsyncMock()
        mock_readiness = LabReadinessReport(
            timestamp="2024-01-01T00:00:00Z",
            overall_ready=True,
            namespaces={
                "rl260-client": NamespaceStatus(name="rl260-client", exists=True, accessible=True, interfaces=[InterfaceInfo(name="rlc0", ipv4_address="192.168.10.2", ipv4_network="192.168.10.2/24")], routes=[]),
                "rl260-router": NamespaceStatus(name="rl260-router", exists=True, accessible=True, interfaces=[InterfaceInfo(name="rlr0c", ipv4_address="192.168.10.1", ipv4_network="192.168.10.1/24"), InterfaceInfo(name="rlr0s", ipv4_address="192.168.20.1", ipv4_network="192.168.20.1/24")], routes=[RouteInfo(destination="192.168.10.0/24", gateway=None, interface="rlr0c"), RouteInfo(destination="192.168.20.0/24", gateway=None, interface="rlr0s")]),
                "rl260-server": NamespaceStatus(name="rl260-server", exists=True, accessible=True, interfaces=[InterfaceInfo(name="rls0", ipv4_address="192.168.20.2", ipv4_network="192.168.20.2/24")], routes=[]),
            },
            expected_topology={},
            missing_tools=[],
            permission_issues=[],
            summary="OK",
        )
        mock_adapter.check_lab_readiness = AsyncMock(return_value=mock_readiness)

        lab = PacketLab(adapter=mock_adapter)
        status = await lab.get_status()

        assert status.available is True
        assert status.state == LabState.READY
        assert status.router_info is not None
        assert "rlr0c" in status.router_info["interfaces"]
        assert "rlr0s" in status.router_info["interfaces"]

    @pytest.mark.asyncio
    async def test_get_status_lab_unavailable(self):
        """Test get_status when lab is unavailable."""
        mock_adapter = AsyncMock()
        mock_readiness = LabReadinessReport(
            timestamp="2024-01-01T00:00:00Z",
            overall_ready=False,
            namespaces={},
            expected_topology={},
            missing_tools=[],
            permission_issues=["Permission denied"],
            summary="Permission issues: Permission denied",
        )
        mock_adapter.check_lab_readiness = AsyncMock(return_value=mock_readiness)

        lab = PacketLab(adapter=mock_adapter)
        status = await lab.get_status()

        assert status.available is False
        assert status.state == LabState.UNAVAILABLE
        assert "Permission issues" in status.message

    @pytest.mark.asyncio
    async def test_simulate_invalid_request(self):
        """Test simulation with invalid request."""
        lab = PacketLab()
        request = SimulateRequest(
            source_ip="not.an.ip",
            destination_ip="192.168.20.2",
        )
        response = await lab.simulate(request)
        assert response.state == LabState.ERROR
        assert "Invalid source IP" in response.error

    @pytest.mark.asyncio
    async def test_simulate_lab_unavailable(self):
        """Test simulation when lab is unavailable."""
        mock_adapter = AsyncMock()
        mock_readiness = LabReadinessReport(
            timestamp="2024-01-01T00:00:00Z",
            overall_ready=False,
            namespaces={},
            expected_topology={},
            missing_tools=[],
            permission_issues=["Permission denied"],
            summary="Permission issues",
        )
        mock_adapter.check_lab_readiness = AsyncMock(return_value=mock_readiness)

        lab = PacketLab(adapter=mock_adapter)
        request = SimulateRequest(
            source_ip="192.168.10.2",
            destination_ip="192.168.20.2",
        )
        response = await lab.simulate(request)

        assert response.state == LabState.UNAVAILABLE
        assert "Lab unavailable" in response.message

    @pytest.mark.asyncio
    async def test_simulate_success(self):
        """Test successful simulation."""
        mock_adapter = AsyncMock()
        mock_readiness = LabReadinessReport(
            timestamp="2024-01-01T00:00:00Z",
            overall_ready=True,
            namespaces={},
            expected_topology={},
            missing_tools=[],
            permission_issues=[],
            summary="OK",
        )
        mock_adapter.check_lab_readiness = AsyncMock(return_value=mock_readiness)

        mock_operation = LabOperationResult(
            operation="ping_with_capture",
            success=True,
            timestamp="2024-01-01T00:00:00Z",
            duration_ms=100,
            data={
                "ping": {"success": True, "packets_sent": 3, "packets_received": 3},
                "capture": {"packets_captured": 2},
            },
        )
        mock_adapter.run_ping_with_capture = AsyncMock(return_value=mock_operation)

        lab = PacketLab(adapter=mock_adapter)
        request = SimulateRequest(
            source_ip="192.168.10.2",
            destination_ip="192.168.20.2",
        )
        response = await lab.simulate(request)

        assert response.state == LabState.COMPLETED
        assert response.capture_verified is True
        assert response.packet is not None
        assert response.verification_details is not None
        assert response.verification_details.ttl_decremented is True

    @pytest.mark.asyncio
    async def test_simulate_timeout(self):
        """Test simulation with capture timeout."""
        mock_adapter = AsyncMock()
        mock_readiness = LabReadinessReport(
            timestamp="2024-01-01T00:00:00Z",
            overall_ready=True,
            namespaces={},
            expected_topology={},
            missing_tools=[],
            permission_issues=[],
            summary="OK",
        )
        mock_adapter.check_lab_readiness = AsyncMock(return_value=mock_readiness)

        # Mock ping success but no capture
        mock_operation = LabOperationResult(
            operation="ping_with_capture",
            success=False,
            timestamp="2024-01-01T00:00:00Z",
            duration_ms=5000,
            data={
                "ping": {"success": True, "packets_sent": 3, "packets_received": 3},
                "capture": {"packets_captured": 0},
            },
            error="No packets captured",
            warnings=["Verify lab connectivity"],
        )
        mock_adapter.run_ping_with_capture = AsyncMock(return_value=mock_operation)

        lab = PacketLab(adapter=mock_adapter)
        request = SimulateRequest(
            source_ip="192.168.10.2",
            destination_ip="192.168.20.2",
        )
        response = await lab.simulate(request)

        assert response.state == LabState.TIMEOUT
        assert response.capture_verified is False

    @pytest.mark.asyncio
    async def test_simulate_transmission_error(self):
        """Test simulation when ping fails."""
        mock_adapter = AsyncMock()
        mock_readiness = LabReadinessReport(
            timestamp="2024-01-01T00:00:00Z",
            overall_ready=True,
            namespaces={},
            expected_topology={},
            missing_tools=[],
            permission_issues=[],
            summary="OK",
        )
        mock_adapter.check_lab_readiness = AsyncMock(return_value=mock_readiness)

        # Mock ping failure
        mock_operation = LabOperationResult(
            operation="ping_with_capture",
            success=False,
            timestamp="2024-01-01T00:00:00Z",
            duration_ms=5000,
            data={
                "ping": {"success": False, "packets_sent": 3, "packets_received": 0},
                "capture": {"packets_captured": 0},
            },
            error="Destination unreachable",
        )
        mock_adapter.run_ping_with_capture = AsyncMock(return_value=mock_operation)

        lab = PacketLab(adapter=mock_adapter)
        request = SimulateRequest(
            source_ip="192.168.10.2",
            destination_ip="192.168.20.2",
        )
        response = await lab.simulate(request)

        assert response.state == LabState.ERROR
        assert response.capture_verified is False

    def test_validate_request_protocol(self):
        """Test protocol validation."""
        lab = PacketLab()
        # Only icmp should be valid now
        for proto in ["icmp", "ICMP"]:
            request = SimulateRequest(
                source_ip="192.168.10.2",
                destination_ip="192.168.20.2",
                protocol=proto,
            )
            error = lab._validate_request(request)
            assert error is None

        # tcp and udp should be rejected
        for proto in ["tcp", "udp", "TCP", "UDP"]:
            request = SimulateRequest(
                source_ip="192.168.10.2",
                destination_ip="192.168.20.2",
                protocol=proto,
            )
            error = lab._validate_request(request)
            assert error is not None
            assert "Unsupported protocol" in error

    def test_validate_request_ttl_range(self):
        """Test request validation with TTL bounds."""
        lab = PacketLab()
        request = SimulateRequest(
            source_ip="192.168.10.2",
            destination_ip="192.168.20.2",
            ttl=0,
        )
        error = lab._validate_request(request)
        assert error is not None
        assert "TTL out of range" in error

    def test_validate_request_length_range(self):
        """Test request validation with length bounds."""
        lab = PacketLab()
        request = SimulateRequest(
            source_ip="192.168.10.2",
            destination_ip="192.168.20.2",
            length=10,
        )
        error = lab._validate_request(request)
        assert error is not None
        assert "Packet length out of range" in error


class TestPacketLabRoutes:
    """Tests for the PacketLab API routes."""

    @pytest.mark.asyncio
    async def test_get_lab_status_endpoint(self):
        """Test GET /api/lab/status endpoint structure."""
        from app.packet_lab_routes import router
        # Just verify the router is properly configured
        # Prefix is now applied at app level via include_router
        assert "PacketLab" in router.tags

        # Check routes exist (full paths including prefix)
        routes = [route.path for route in router.routes]
        assert "/status" in routes
        assert "/simulate" in routes

    @pytest.mark.asyncio
    async def test_get_lab_status_available(self):
        """Test GET /api/lab/status when lab is available."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # Mock the packet lab
            with patch("app.packet_lab_routes.get_packet_lab") as mock_get_lab:
                mock_lab = AsyncMock()
                mock_status = LabStatus(
                    available=True,
                    state=LabState.READY,
                    message="Lab ready",
                    router_info={"interfaces": ["rlr0c", "rlr0s"], "routing_table": []}
                )
                mock_lab.get_status = AsyncMock(return_value=mock_status)
                mock_get_lab.return_value = mock_lab

                response = await client.get("/api/lab/status")

            assert response.status_code == 200
            data = response.json()
            assert data["available"] is True
            assert data["state"] == "ready"

    @pytest.mark.asyncio
    async def test_get_lab_status_unavailable(self):
        """Test GET /api/lab/status when lab is unavailable."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            with patch("app.packet_lab_routes.get_packet_lab") as mock_get_lab:
                mock_lab = AsyncMock()
                mock_status = LabStatus(
                    available=False,
                    state=LabState.UNAVAILABLE,
                    message="Permission denied",
                    error="Permission denied accessing rl260-client"
                )
                mock_lab.get_status = AsyncMock(return_value=mock_status)
                mock_get_lab.return_value = mock_lab

                response = await client.get("/api/lab/status")

            assert response.status_code == 503
            data = response.json()
            assert "detail" in data
            assert "Permission denied" in data["detail"]

    @pytest.mark.asyncio
    async def test_simulate_invalid_request(self):
        """Test POST /api/lab/simulate with invalid request."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/api/lab/simulate", json={
                "source_ip": "invalid",
                "destination_ip": "192.168.20.2",
                "protocol": "icmp",
                "ttl": 64,
                "length": 84,
            })
        assert response.status_code == 422  # Validation error

    @pytest.mark.asyncio
    async def test_simulate_lab_unavailable(self):
        """Test POST /api/lab/simulate when lab is unavailable."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            with patch("app.packet_lab_routes.get_packet_lab") as mock_get_lab:
                mock_lab = AsyncMock()
                mock_response = SimulateResponse(
                    state=LabState.UNAVAILABLE,
                    message="Lab unavailable",
                    error="Permission denied"
                )
                mock_lab.simulate = AsyncMock(return_value=mock_response)
                mock_get_lab.return_value = mock_lab

                response = await client.post("/api/lab/simulate", json={
                    "source_ip": "192.168.10.2",
                    "destination_ip": "192.168.20.2",
                    "protocol": "icmp",
                    "ttl": 64,
                    "length": 84,
                })

        assert response.status_code == 503

    @pytest.mark.asyncio
    async def test_simulate_timeout(self):
        """Test POST /api/lab/simulate with timeout."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            with patch("app.packet_lab_routes.get_packet_lab") as mock_get_lab:
                mock_lab = AsyncMock()
                mock_response = SimulateResponse(
                    state=LabState.TIMEOUT,
                    message="Capture timeout",
                    error="No packets captured"
                )
                mock_lab.simulate = AsyncMock(return_value=mock_response)
                mock_get_lab.return_value = mock_lab

                response = await client.post("/api/lab/simulate", json={
                    "source_ip": "192.168.10.2",
                    "destination_ip": "192.168.20.2",
                    "protocol": "icmp",
                    "ttl": 64,
                    "length": 84,
                })

        assert response.status_code == 408

    @pytest.mark.asyncio
    async def test_simulate_error(self):
        """Test POST /api/lab/simulate with error."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            with patch("app.packet_lab_routes.get_packet_lab") as mock_get_lab:
                mock_lab = AsyncMock()
                mock_response = SimulateResponse(
                    state=LabState.ERROR,
                    message="Transmission failed",
                    error="Destination unreachable"
                )
                mock_lab.simulate = AsyncMock(return_value=mock_response)
                mock_get_lab.return_value = mock_lab

                response = await client.post("/api/lab/simulate", json={
                    "source_ip": "192.168.10.2",
                    "destination_ip": "192.168.20.2",
                    "protocol": "icmp",
                    "ttl": 64,
                    "length": 84,
                })

        assert response.status_code == 400


class TestPacketLabSingleton:
    """Tests for singleton pattern."""

    def test_get_packet_lab_singleton(self):
        """Test that get_packet_lab returns singleton."""
        from app.packet_lab import get_packet_lab
        lab1 = get_packet_lab()
        lab2 = get_packet_lab()
        assert lab1 is lab2

    def test_get_lab_adapter_singleton(self):
        """Test that get_lab_adapter returns singleton."""
        from app.lab_adapter import get_lab_adapter
        adapter1 = get_lab_adapter()
        adapter2 = get_lab_adapter()
        assert adapter1 is adapter2


class TestDataModels:
    """Tests for data models."""

    def test_lab_state_enum_values(self):
        """Test LabState enum has expected values."""
        expected = {"idle", "ready", "simulating", "transmitting", "capturing", "verifying", "completed", "error", "timeout", "unavailable"}
        actual = {state.value for state in LabState}
        assert actual == expected

    def test_simulate_request_model_validation(self):
        """Test SimulateRequestModel validation."""
        # Valid request
        req = SimulateRequestModel(
            source_ip="192.168.10.2",
            destination_ip="192.168.20.2",
        )
        assert req.source_ip == "192.168.10.2"

        # Invalid IP
        with pytest.raises(ValueError, match="Invalid IPv4 address"):
            SimulateRequestModel(source_ip="invalid", destination_ip="192.168.20.2")

        # Invalid protocol
        with pytest.raises(ValueError, match="Unsupported protocol"):
            SimulateRequestModel(source_ip="192.168.10.2", destination_ip="192.168.20.2", protocol="invalid")

    def test_lab_status_response_model(self):
        """Test LabStatusResponse model."""
        resp = LabStatusResponse(
            available=True,
            state="ready",
            message="OK",
            router_info={"interfaces": []},
            error=None
        )
        assert resp.available is True
        assert resp.state == "ready"


class TestNamespaceStatus:
    """Tests for namespace status dataclasses."""

    def test_interface_info(self):
        iface = InterfaceInfo(name="eth0", ipv4_address="192.168.1.1", ipv4_network="192.168.1.1/24", state="UP")
        assert iface.name == "eth0"
        assert iface.ipv4_address == "192.168.1.1"

    def test_route_info(self):
        route = RouteInfo(destination="192.168.1.0/24", gateway="192.168.1.1", interface="eth0")
        assert route.destination == "192.168.1.0/24"
        assert route.gateway == "192.168.1.1"

    def test_namespace_status(self):
        ns = NamespaceStatus(name="test-ns", exists=True, accessible=True)
        assert ns.name == "test-ns"
        assert ns.exists is True

    def test_lab_readiness_report(self):
        report = LabReadinessReport(
            timestamp="2024-01-01T00:00:00Z",
            overall_ready=True,
            namespaces={},
            expected_topology={},
            missing_tools=[],
            permission_issues=[],
            summary="Ready",
        )
        assert report.overall_ready is True