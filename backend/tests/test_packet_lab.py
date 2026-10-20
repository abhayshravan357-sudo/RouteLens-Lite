"""
Tests for the PacketLab virtual router adapter and API.

This module contains tests for the Linux network namespace lab operations,
including lab readiness checks, packet simulation, and capture verification.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.lab_adapter import (
    LabAdapter,
    LabReadinessReport,
    NamespaceStatus,
    InterfaceInfo,
    RouteInfo,
    PingResult,
    PacketCaptureResult,
    LabOperationResult,
    LabComponent,
)
from app.packet_lab import (
    PacketLab,
    LabState,
    LabStatus,
    SimulateRequest,
    SimulateResponse,
    get_packet_lab,
)
from app.packet_lab_routes import router


class TestLabAdapter:
    """Tests for the LabAdapter class."""

    @pytest.fixture
    def adapter(self):
        """Create a LabAdapter with mocked commands."""
        adapter = LabAdapter(use_pkexec=False)
        return adapter

    def test_check_tools(self, adapter):
        """Test tool availability checking."""
        # This will check actual system tools
        available, missing = adapter.check_tools()
        assert isinstance(available, list)
        assert isinstance(missing, list)

    def test_expected_topology_constant(self):
        """Test that EXPECTED_TOPOLOGY has required structure."""
        from app.lab_adapter import EXPECTED_TOPOLOGY

        assert "client" in EXPECTED_TOPOLOGY
        assert "router" in EXPECTED_TOPOLOGY
        assert "server" in EXPECTED_TOPOLOGY
        assert EXPECTED_TOPOLOGY["client"]["namespace"] == "rl260-client"
        assert EXPECTED_TOPOLOGY["router"]["namespace"] == "rl260-router"
        assert EXPECTED_TOPOLOGY["server"]["namespace"] == "rl260-server"

    def test_required_tools_constant(self):
        """Test that REQUIRED_TOOLS includes expected tools."""
        from app.lab_adapter import REQUIRED_TOOLS

        assert "ip" in REQUIRED_TOOLS
        assert "ping" in REQUIRED_TOOLS
        assert "tcpdump" in REQUIRED_TOOLS
        assert "timeout" in REQUIRED_TOOLS


class TestPacketLab:
    """Tests for the PacketLab class."""

    @pytest.fixture
    def mock_adapter(self):
        """Create a mocked LabAdapter."""
        return AsyncMock(spec=LabAdapter)

    @pytest.fixture
    def packet_lab(self, mock_adapter):
        """Create a PacketLab instance with mocked adapter."""
        return PacketLab(adapter=mock_adapter)

    def test_initial_state(self, packet_lab):
        """Test initial state is IDLE."""
        assert packet_lab.current_state == LabState.IDLE

    @pytest.mark.asyncio
    async def test_get_status_lab_ready(self, packet_lab, mock_adapter):
        """Test get_status when lab is ready."""
        # Mock readiness report
        mock_readiness = LabReadinessReport(
            timestamp="2024-01-01T00:00:00Z",
            overall_ready=True,
            namespaces={
                "rl260-client": NamespaceStatus(
                    name="rl260-client",
                    exists=True,
                    accessible=True,
                    interfaces=[
                        InterfaceInfo(name="rlc0", ipv4_address="192.168.10.2", ipv4_network="192.168.10.2/24")
                    ],
                    routes=[
                        RouteInfo(destination="0.0.0.0/0", gateway="192.168.10.1", interface="rlc0")
                    ],
                ),
                "rl260-router": NamespaceStatus(
                    name="rl260-router",
                    exists=True,
                    accessible=True,
                    interfaces=[
                        InterfaceInfo(name="rlr0c", ipv4_address="192.168.10.1", ipv4_network="192.168.10.1/24"),
                        InterfaceInfo(name="rlr0s", ipv4_address="192.168.20.1", ipv4_network="192.168.20.1/24"),
                    ],
                    routes=[],
                    ip_forward_enabled=True,
                ),
                "rl260-server": NamespaceStatus(
                    name="rl260-server",
                    exists=True,
                    accessible=True,
                    interfaces=[
                        InterfaceInfo(name="rls0", ipv4_address="192.168.20.2", ipv4_network="192.168.20.2/24")
                    ],
                    routes=[
                        RouteInfo(destination="0.0.0.0/0", gateway="192.168.20.1", interface="rls0")
                    ],
                ),
            },
            expected_topology={},
            missing_tools=[],
            permission_issues=[],
            summary="Lab is fully ready for packet operations",
        )
        mock_adapter.check_lab_readiness = AsyncMock(return_value=mock_readiness)

        status = await packet_lab.get_status()

        assert status.available is True
        assert status.state == LabState.READY
        assert status.router_info is not None
        assert "interfaces" in status.router_info
        assert "routing_table" in status.router_info

    @pytest.mark.asyncio
    async def test_get_status_lab_unavailable(self, packet_lab, mock_adapter):
        """Test get_status when lab is not ready."""
        mock_readiness = LabReadinessReport(
            timestamp="2024-01-01T00:00:00Z",
            overall_ready=False,
            namespaces={},
            expected_topology={},
            missing_tools=["tcpdump"],
            permission_issues=[],
            summary="Missing required tools: tcpdump",
        )
        mock_adapter.check_lab_readiness = AsyncMock(return_value=mock_readiness)

        status = await packet_lab.get_status()

        assert status.available is False
        assert status.state == LabState.UNAVAILABLE
        assert "tcpdump" in status.error

    @pytest.mark.asyncio
    async def test_simulate_invalid_request(self, packet_lab, mock_adapter):
        """Test simulate with invalid request."""
        # Mock get_status to return available
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

        # Invalid source IP
        request = SimulateRequest(
            source_ip="invalid.ip",
            destination_ip="192.168.20.2",
        )
        response = await packet_lab.simulate(request)

        assert response.state == LabState.ERROR
        assert "Invalid source IP" in response.error

    @pytest.mark.asyncio
    async def test_simulate_lab_unavailable(self, packet_lab, mock_adapter):
        """Test simulate when lab is unavailable."""
        # First call to get_status returns unavailable
        mock_readiness = LabReadinessReport(
            timestamp="2024-01-01T00:00:00Z",
            overall_ready=False,
            namespaces={},
            expected_topology={},
            missing_tools=["tcpdump"],
            permission_issues=[],
            summary="Missing tools",
        )
        mock_adapter.check_lab_readiness = AsyncMock(return_value=mock_readiness)

        request = SimulateRequest(
            source_ip="192.168.10.2",
            destination_ip="192.168.20.2",
        )
        response = await packet_lab.simulate(request)

        assert response.state == LabState.UNAVAILABLE
        assert "unavailable" in response.message.lower()

    @pytest.mark.asyncio
    async def test_simulate_success(self, packet_lab, mock_adapter):
        """Test successful packet simulation."""
        # Mock get_status to return ready
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

        # Mock successful ping with capture
        mock_operation = LabOperationResult(
            operation="ping_with_capture",
            success=True,
            timestamp="2024-01-01T00:00:00Z",
            duration_ms=1000,
            data={
                "ping": {
                    "success": True,
                    "packets_sent": 3,
                    "packets_received": 3,
                    "packet_loss_percent": 0.0,
                },
                "capture": {
                    "packets_captured": 3,
                    "packets_received_by_filter": 3,
                    "packets_dropped": 0,
                },
            },
            error=None,
            warnings=[],
        )
        mock_adapter.run_ping_with_capture = AsyncMock(return_value=mock_operation)

        request = SimulateRequest(
            source_ip="192.168.10.2",
            destination_ip="192.168.20.2",
            route_matched="192.168.20.0/24",
            egress_interface="rlr0s",
            next_hop="192.168.20.2",
        )
        response = await packet_lab.simulate(request)

        assert response.state == LabState.COMPLETED
        assert response.capture_verified is True
        assert response.packet is not None
        assert response.packet.source_ip == "192.168.10.2"
        assert response.packet.destination_ip == "192.168.20.2"
        assert response.verification_details is not None
        assert response.verification_details.ttl_decremented is True

    @pytest.mark.asyncio
    async def test_simulate_timeout(self, packet_lab, mock_adapter):
        """Test simulation with capture timeout."""
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

        request = SimulateRequest(
            source_ip="192.168.10.2",
            destination_ip="192.168.20.2",
        )
        response = await packet_lab.simulate(request)

        assert response.state == LabState.TIMEOUT
        assert response.capture_verified is False

    def test_validate_request_protocol(self, packet_lab):
        """Test protocol validation."""
        request = SimulateRequest(
            source_ip="192.168.10.2",
            destination_ip="192.168.20.2",
            protocol="invalid",
        )
        error = packet_lab._validate_request(request)
        assert error is not None
        assert "Unsupported protocol" in error

    def test_validate_request_ttl_range(self, packet_lab):
        """Test TTL range validation."""
        request = SimulateRequest(
            source_ip="192.168.10.2",
            destination_ip="192.168.20.2",
            ttl=0,
        )
        error = packet_lab._validate_request(request)
        assert error is not None
        assert "TTL out of range" in error

        request.ttl = 300
        error = packet_lab._validate_request(request)
        assert error is not None

    def test_validate_request_length_range(self, packet_lab):
        """Test packet length validation."""
        request = SimulateRequest(
            source_ip="192.168.10.2",
            destination_ip="192.168.20.2",
            length=10,
        )
        error = packet_lab._validate_request(request)
        assert error is not None
        assert "Packet length out of range" in error


class TestPacketLabRoutes:
    """Tests for the PacketLab API routes."""

    @pytest.mark.asyncio
    async def test_get_lab_status_endpoint(self):
        """Test GET /api/lab/status endpoint structure."""
        # Just verify the router is properly configured
        assert router.prefix == "/api/lab"
        assert "PacketLab" in router.tags

        # Check routes exist (with prefix)
        routes = [route.path for route in router.routes]
        assert "/api/lab/status" in routes
        assert "/api/lab/simulate" in routes


class TestPacketLabSingleton:
    """Tests for singleton pattern."""

    def test_get_packet_lab_singleton(self):
        """Test that get_packet_lab returns singleton."""
        lab1 = get_packet_lab()
        lab2 = get_packet_lab()
        assert lab1 is lab2


class TestDataModels:
    """Tests for data model validation."""

    def test_lab_state_enum_values(self):
        """Test LabState enum has all required values."""
        required_states = [
            "idle", "ready", "simulating", "transmitting",
            "capturing", "verifying", "completed", "error",
            "timeout", "unavailable"
        ]
        for state in required_states:
            assert hasattr(LabState, state.upper())
            assert getattr(LabState, state.upper()).value == state

    def test_simulate_request_model_validation(self):
        """Test SimulateRequestModel validation."""
        from app.packet_lab_routes import SimulateRequestModel

        # Valid request
        req = SimulateRequestModel(
            source_ip="192.168.10.2",
            destination_ip="192.168.20.2",
        )
        assert req.source_ip == "192.168.10.2"
        assert req.protocol == "icmp"

        # Invalid IP
        with pytest.raises(ValueError, match="Invalid IPv4 address"):
            SimulateRequestModel(source_ip="invalid", destination_ip="192.168.20.2")

        # Invalid protocol
        with pytest.raises(ValueError, match="Unsupported protocol"):
            SimulateRequestModel(
                source_ip="192.168.10.2",
                destination_ip="192.168.20.2",
                protocol="invalid"
            )

    def test_lab_status_response_model(self):
        """Test LabStatusResponse model."""
        from app.packet_lab_routes import LabStatusResponse

        resp = LabStatusResponse(
            available=True,
            state="ready",
            message="OK",
            router_info={"interfaces": ["rlr0c", "rlr0s"]},
            error=None,
        )
        assert resp.available is True
        assert resp.state == "ready"

        # Unavailable
        resp = LabStatusResponse(
            available=False,
            state="unavailable",
            message="Not ready",
            error="Missing tools",
        )
        assert resp.available is False