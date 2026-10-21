"""
RouteLens Lite - PacketLab Tests

Unit and integration tests for the virtual router lab adapter and API.
"""

import pytest
from pydantic import ValidationError
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock, patch, MagicMock, Mock
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
from app.lab_builder import (
    build_commands,
    run_all,
    run_teardown,
    probe,
    teardown_commands,
    PFX,
)
from app.packet_lab import (
    PacketLab,
    LabState,
    LabStatus,
    SimulateRequest,
    SimulateResponse,
    VerificationProvenance,
    VerificationField,
)
from app.packet_lab_routes import (
    SimulateRequestModel,
    LabStatusResponse,
)
from app.scenarios_data import (
    CLIENT_ROUTER_SERVER,
    TWO_ROUTERS,
    DUAL_STACK,
    IPV6_ONLY,
    LOOP,
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

    @pytest.mark.asyncio
    async def test_the_readiness_reason_names_the_namespace_that_failed(self):
        """
        "Lab not ready" on its own tells the reader nothing.

        The reason is nearly always one specific namespace that is missing
        or one specific permission that was refused, and that is what the
        summary has to say, because the summary is what the interface
        shows the student.
        """
        adapter = LabAdapter()

        missing = NamespaceStatus(
            name="rl260-client",
            exists=False,
            accessible=False,
            error="Namespace rl260-client does not exist",
        )
        refused = NamespaceStatus(
            name="rl260-router",
            exists=True,
            accessible=False,
            error=(
                "Permission denied accessing rl260-router. "
                "Privilege escalation (sudo/pkexec) not configured for web backend."
            ),
        )
        server = NamespaceStatus(
            name="rl260-server", exists=True, accessible=True,
            interfaces=[InterfaceInfo(name="rls0", ipv4_network="192.168.20.2/24")],
        )

        with patch.object(adapter, 'get_namespace_status', new_callable=AsyncMock) as mock_get:
            mock_get.side_effect = [missing, refused, server]
            report = await adapter.check_lab_readiness()

        assert report.overall_ready is False
        assert "rl260-client" in report.summary, report.summary
        assert "does not exist" in report.summary, report.summary
        assert "rl260-router" in report.summary, report.summary
        assert "Permission denied" in report.summary, report.summary
        assert report.summary != "Lab not ready", (
            "the summary fell back to the generic message"
        )


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
                "capture": {"packets_captured": 2, "raw_output": "IP ... ttl 63 ... checksum 0x1234 (correct)"},
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
        # Check new VerificationField structure
        assert response.verification_details.ttl_decremented.value is True
        assert response.verification_details.ttl_decremented.provenance == VerificationProvenance.OBSERVED
        assert response.verification_details.checksum_valid.value is True
        assert response.verification_details.checksum_valid.provenance == VerificationProvenance.OBSERVED
        assert response.verification_details.route_matched.value is True
        assert response.verification_details.route_matched.provenance == VerificationProvenance.OBSERVED

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
                "capture": {"packets_captured": 0, "raw_output": ""},
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
        # Check that verification details still have inferred provenance
        assert response.verification_details is not None
        assert response.verification_details.ttl_decremented.value is True
        assert response.verification_details.ttl_decremented.provenance == VerificationProvenance.INFERRED
        assert response.verification_details.checksum_valid.value is True
        assert response.verification_details.checksum_valid.provenance == VerificationProvenance.INFERRED
        assert response.verification_details.route_matched.value is False
        assert response.verification_details.route_matched.provenance == VerificationProvenance.UNKNOWN

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
                "capture": {"packets_captured": 0, "raw_output": ""},
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
        # Check that verification details have inferred provenance for failed ping
        assert response.verification_details is not None
        assert response.verification_details.ttl_decremented.value is False
        assert response.verification_details.ttl_decremented.provenance == VerificationProvenance.INFERRED
        assert response.verification_details.checksum_valid.value is False
        assert response.verification_details.checksum_valid.provenance == VerificationProvenance.INFERRED
        assert response.verification_details.route_matched.value is False
        assert response.verification_details.route_matched.provenance == VerificationProvenance.UNKNOWN

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


class TestLabBuilder:
    """Tests for the LabBuilder command generation and execution."""

    def test_build_commands_order_phases(self):
        """Test that build_commands produces commands in the correct phase order for all scenarios."""
        scenarios = [
            ("CLIENT_ROUTER_SERVER", CLIENT_ROUTER_SERVER),
            ("TWO_ROUTERS", TWO_ROUTERS),
            ("DUAL_STACK", DUAL_STACK),
            ("IPV6_ONLY", IPV6_ONLY),
            ("LOOP", LOOP),
        ]

        for name, sc in scenarios:
            cmds = build_commands(sc)
            assert len(cmds) > 0, f"{name}: no commands generated"

            # Phase 1: namespace creation (ip netns add) + loopback up
            ns_add_idx = [i for i, cmd in enumerate(cmds) if cmd[0] == "ip" and cmd[1] == "netns" and cmd[2] == "add"]
            ns_lo_idx = [i for i, cmd in enumerate(cmds) if cmd[0] == "ip" and "-n" in cmd and "link" in cmd and "lo" in cmd and "up" in cmd]

            assert len(ns_add_idx) == len(sc.nodes), f"{name}: namespace count mismatch"
            assert len(ns_lo_idx) == len(sc.nodes), f"{name}: loopback up count mismatch"

            # All namespace adds must come before any veth operations
            first_veth_idx = next((i for i, cmd in enumerate(cmds) if cmd[0] == "ip" and cmd[1] == "link" and "add" in cmd and "veth" in cmd), len(cmds))
            assert max(ns_add_idx) < first_veth_idx, f"{name}: namespace not created before veth"

            # Phase 2: veth pairs (create -> move -> rename)
            veth_create_idx = [i for i, cmd in enumerate(cmds) if cmd[0] == "ip" and cmd[1] == "link" and "add" in cmd and "veth" in cmd]
            veth_move_idx = [i for i, cmd in enumerate(cmds) if cmd[0] == "ip" and cmd[1] == "link" and "set" in cmd and "netns" in cmd]
            veth_rename_idx = [i for i, cmd in enumerate(cmds) if cmd[0] == "ip" and "-n" in cmd and "link" in cmd and "set" in cmd and "name" in cmd]

            assert len(veth_create_idx) == len(sc.links), f"{name}: veth create count mismatch"
            assert len(veth_move_idx) == 2 * len(sc.links), f"{name}: veth move count mismatch"
            assert len(veth_rename_idx) == 2 * len(sc.links), f"{name}: veth rename count mismatch"

            # Order: create -> move -> rename for each veth pair
            for i in range(len(sc.links)):
                assert veth_create_idx[i] < veth_move_idx[2*i], f"{name}: veth {i} move before create"
                assert veth_create_idx[i] < veth_move_idx[2*i+1], f"{name}: veth {i} move before create"
                assert veth_move_idx[2*i] < veth_rename_idx[2*i], f"{name}: veth {i} rename before move (a)"
                assert veth_move_idx[2*i+1] < veth_rename_idx[2*i+1], f"{name}: veth {i} rename before move (b)"

            # Phase 3: addresses and link up
            addr_add_idx = [i for i, cmd in enumerate(cmds) if cmd[0] == "ip" and "-n" in cmd and "addr" in cmd and "add" in cmd]
            link_up_idx = [i for i, cmd in enumerate(cmds) if cmd[0] == "ip" and "-n" in cmd and "link" in cmd and "set" in cmd and "up" in cmd and "lo" not in cmd]

            total_ifaces = sum(len(n.ifaces) for n in sc.nodes)
            assert len(addr_add_idx) == total_ifaces, f"{name}: addr add count mismatch"
            assert len(link_up_idx) == total_ifaces, f"{name}: link up count mismatch"

            # Addresses before link up for each interface
            # (they're grouped by node, so check each node's interfaces)
            for node in sc.nodes:
                node_ns = f"rl_{node.id}"
                node_addrs = [i for i, cmd in enumerate(cmds) if cmd[0] == "ip" and "-n" in cmd and node_ns in cmd and "addr" in cmd and "add" in cmd]
                node_ups = [i for i, cmd in enumerate(cmds) if cmd[0] == "ip" and "-n" in cmd and node_ns in cmd and "link" in cmd and "set" in cmd and "up" in cmd and "lo" not in cmd]
                assert len(node_addrs) == len(node.ifaces), f"{name}: {node.id} addr count mismatch"
                assert len(node_ups) == len(node.ifaces), f"{name}: {node.id} up count mismatch"
                for a_idx, u_idx in zip(sorted(node_addrs), sorted(node_ups)):
                    assert a_idx < u_idx, f"{name}: {node.id} link up before addr add"

            # Phase 4: IP forwarding (routers only)
            forwarding_idx = [i for i, cmd in enumerate(cmds) if "sysctl" in cmd and ("ip_forward" in " ".join(cmd) or "forwarding" in " ".join(cmd))]
            router_count = sum(1 for n in sc.nodes if n.kind == "router")
            assert len(forwarding_idx) == 2 * router_count, f"{name}: forwarding count mismatch (IPv4 + IPv6 per router)"

            # Phase 5: static routes
            route_add_idx = [i for i, cmd in enumerate(cmds) if cmd[0] == "ip" and "-n" in cmd and "route" in cmd and "add" in cmd]
            total_routes = sum(len(n.routes) for n in sc.nodes)
            assert len(route_add_idx) == total_routes, f"{name}: route add count mismatch"

            # All routes after all link ups
            assert max(link_up_idx) < min(route_add_idx) if route_add_idx else True, f"{name}: routes before links up"

    def test_build_commands_names_prefixed(self):
        """Test that all namespace and veth names use the PFX prefix."""
        for name, sc in [
            ("CLIENT_ROUTER_SERVER", CLIENT_ROUTER_SERVER),
            ("TWO_ROUTERS", TWO_ROUTERS),
            ("DUAL_STACK", DUAL_STACK),
            ("IPV6_ONLY", IPV6_ONLY),
            ("LOOP", LOOP),
        ]:
            cmds = build_commands(sc)
            for cmd in cmds:
                cmd_str = " ".join(cmd)
                # Check namespace names
                if "netns" in cmd_str:
                    # Extract namespace arguments
                    for i, arg in enumerate(cmd):
                        if arg.startswith("rl_") and ":" not in arg and "@" not in arg:
                            assert arg.startswith(PFX), f"{name}: namespace {arg} missing PFX prefix"
                # Check veth temp names
                for arg in cmd:
                    if arg.startswith("rlv") and ("type" in cmd or "peer" in cmd or "netns" in cmd or "name" in cmd):
                        assert arg.startswith(PFX), f"{name}: veth {arg} missing PFX prefix"

    def test_hosts_never_get_ip_forward(self):
        """Test that only routers get IP forwarding enabled, never hosts."""
        for name, sc in [
            ("CLIENT_ROUTER_SERVER", CLIENT_ROUTER_SERVER),
            ("TWO_ROUTERS", TWO_ROUTERS),
            ("DUAL_STACK", DUAL_STACK),
            ("IPV6_ONLY", IPV6_ONLY),
            ("LOOP", LOOP),
        ]:
            cmds = build_commands(sc)
            forwarding_cmds = [cmd for cmd in cmds if "sysctl" in cmd and "ip_forward" in " ".join(cmd)]
            forwarding_ns = set()
            for cmd in forwarding_cmds:
                # Extract namespace from: ip netns exec rl_xxx sysctl ...
                try:
                    exec_idx = cmd.index("exec")
                    ns_name = cmd[exec_idx + 1]
                    forwarding_ns.add(ns_name)
                except ValueError:
                    pass

            router_ids = [n.id for n in sc.nodes if n.kind == "router"]
            expected_ns = {f"rl_{rid}" for rid in router_ids}
            assert forwarding_ns == expected_ns, f"{name}: forwarding on {forwarding_ns}, expected {expected_ns}"

            # Verify no host gets forwarding
            host_ids = [n.id for n in sc.nodes if n.kind == "host"]
            for hid in host_ids:
                assert f"rl_{hid}" not in forwarding_ns, f"{name}: host {hid} got forwarding"

    def test_route_validation_rejects_bad_via(self):
        """Test that build_commands rejects routes where via is not in interface subnet."""
        # Create a scenario with valid link but invalid route (via not in subnet)
        from app.scenario import Scenario, Node, Iface, Link, Route

        # Link is valid (same subnet), but route via is in a different subnet
        bad_scenario = Scenario(
            id="bad-route",
            title="Bad route test",
            nodes=[
                Node(id="router", kind="router", ifaces=[Iface(name="eth0", cidr="10.0.0.1/24")]),
                Node(id="server", kind="host", ifaces=[Iface(name="eth0", cidr="10.0.0.2/24")]),
            ],
            links=[Link(a="router:eth0", b="server:eth0")],
        )
        # Manually add a route with via in wrong subnet (192.168.1.1 not in 10.0.0.0/24)
        bad_scenario.nodes[0].routes.append(
            Route(prefix="0.0.0.0/0", dev="eth0", via="192.168.1.1", metric=10)
        )

        with pytest.raises(ValueError, match="not reachable"):
            build_commands(bad_scenario)

    def test_run_all_reports_failed_command_index(self):
        """Test that run_all reports the index of the failed command."""
        # Create a command list where the 2nd command fails
        commands = [
            ["true"],  # succeeds
            ["false"],  # fails (exit code 1)
            ["true"],  # would not run if stop_on_error=True
        ]

        # Mock _guard to return None (simulate root)
        with patch("app.lab_builder._guard", return_value=None):
            result = run_all(commands, dry_run=False, stop_on_error=True)

        assert result["status"] == "failed"
        assert "failed_at" in result
        assert result["failed_at"] == 1  # index of 'false'
        assert "error" in result
        assert result["log"][1]["index"] == 1
        assert result["log"][1]["rc"] == 1

    def test_run_all_continues_without_stop_on_error(self):
        """Test that run_all continues past failures when stop_on_error=False."""
        commands = [
            ["true"],
            ["false"],
            ["true"],
        ]

        with patch("app.lab_builder._guard", return_value=None):
            result = run_all(commands, dry_run=False, stop_on_error=False)

        # When stop_on_error=False, run_all completes all commands and returns "ok"
        # even if some commands failed (the log contains the failure details)
        assert result["status"] == "ok"
        assert len(result["log"]) == 3
        assert result["log"][0]["rc"] == 0
        assert result["log"][1]["rc"] == 1
        assert result["log"][2]["rc"] == 0

    def test_teardown_twice_is_safe(self):
        """Test that running teardown twice is safe (idempotent)."""
        cmds = teardown_commands(CLIENT_ROUTER_SERVER)

        # First run - namespaces don't exist, should be treated as success
        result1 = run_teardown(cmds)
        assert result1["status"] in ("ok", "unavailable")  # unavailable if not root

        # Second run - should also succeed
        result2 = run_teardown(cmds)
        assert result2["status"] in ("ok", "unavailable")

    def test_dry_run_executes_nothing(self):
        """Test that dry_run=True executes nothing and returns command list."""
        commands = [["echo", "hello"], ["echo", "world"]]

        result = run_all(commands, dry_run=True)

        assert result["status"] == "dry_run"
        assert "commands" in result
        assert len(result["commands"]) == 2
        assert result["commands"][0] == "echo hello"
        assert result["commands"][1] == "echo world"

    def test_probe_distinguishes_failures(self):
        """Test that probe distinguishes timeout, missing binary, permission denied, unreachable."""
        # Test each failure mode separately with fresh mocks
        # Test timeout
        with patch("subprocess.run") as mock_run, patch("app.lab_builder._guard", return_value=None):
            from subprocess import TimeoutExpired
            mock_run.side_effect = TimeoutExpired("ping", 5)
            result = probe("rl_client", "10.0.0.1")
            assert result["status"] == "timeout"

        # Test missing ping binary
        with patch("subprocess.run") as mock_run, patch("app.lab_builder._guard", return_value=None):
            mock_run.side_effect = FileNotFoundError("ping not found")
            result = probe("rl_client", "10.0.0.1")
            assert result["status"] == "missing_binary"

        # Test permission denied
        with patch("subprocess.run") as mock_run, patch("app.lab_builder._guard", return_value=None):
            mock_run.side_effect = PermissionError("permission denied")
            result = probe("rl_client", "10.0.0.1")
            assert result["status"] == "permission_denied"

        # Test unreachable (ping runs but fails)
        with patch("subprocess.run") as mock_run, patch("app.lab_builder._guard", return_value=None):
            mock_result = Mock()
            mock_result.returncode = 1
            mock_result.stdout = ""
            mock_result.stderr = "connect: Network is unreachable"
            mock_run.return_value = mock_result
            result = probe("rl_client", "10.0.0.1")
            assert result["status"] == "unreachable"

        # Test delivered (success)
        with patch("subprocess.run") as mock_run, patch("app.lab_builder._guard", return_value=None):
            mock_result = Mock()
            mock_result.returncode = 0
            mock_result.stdout = "64 bytes from 10.0.0.1"
            mock_result.stderr = ""
            mock_run.return_value = mock_result
            result = probe("rl_client", "10.0.0.1")
            assert result["status"] == "delivered"


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
                    error="Permission denied",
                    verification_details=None,
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
                    error="No packets captured",
                    verification_details=None,
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
                    error="Destination unreachable",
                    verification_details=None,
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
            router_info={
                "interfaces": ["rlr0c", "rlr0s"],
                "routing_table": [
                    {
                        "destination": "192.168.10.0/24",
                        "next_hop": None,
                        "interface": "rlr0c",
                    }
                ],
                "client_ip": "192.168.10.2",
                "server_ip": "192.168.20.2",
            },
            error=None
        )
        assert resp.available is True
        assert resp.state == "ready"
        assert resp.router_info is not None
        assert resp.router_info.interfaces == ["rlr0c", "rlr0s"]
        assert resp.router_info.routing_table[0].destination == "192.168.10.0/24"
        assert resp.router_info.routing_table[0].next_hop is None
        assert resp.router_info.client_ip == "192.168.10.2"

    def test_the_router_info_is_not_a_free_form_dictionary(self):
        """
        The schema has to say what router_info is.

        It used to be a bare dictionary, so the schema said nothing about
        it and the interface's stricter type was checked against nothing.
        A router_info that does not have the shape is now refused.
        """
        with pytest.raises(ValidationError):
            LabStatusResponse(
                available=True,
                state="ready",
                message="OK",
                router_info={"interfaces": []},
                error=None,
            )


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