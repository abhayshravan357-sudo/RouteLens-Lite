"""
RouteLens Lite - PacketLab Virtual Router Logic

Implements the virtual router lab operations for packet transmission and capture verification.
Uses the LabAdapter for safe namespace operations.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from ipaddress import IPv4Address, IPv4Network
import re
from typing import Any, Optional

from app.lab_adapter import LabAdapter, get_lab_adapter, LabOperationResult, PingResult, PacketCaptureResult
from app.lab_next_steps import diagnose


class LabState(str, Enum):
    IDLE = "idle"
    READY = "ready"
    SIMULATING = "simulating"
    TRANSMITTING = "transmitting"
    CAPTURING = "capturing"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    ERROR = "error"
    TIMEOUT = "timeout"
    UNAVAILABLE = "unavailable"


# Provenance types following project convention
class VerificationProvenance(str, Enum):
    OBSERVED = "observed"      # Directly measured from packet capture
    INFERRED = "inferred"      # Deduced from successful ping
    SIMULATED = "simulated"    # From routing simulation
    UNKNOWN = "unknown"        # Could not determine


@dataclass
class VerificationField:
    """A verification result with its provenance."""
    value: bool
    provenance: VerificationProvenance
    details: str = ""


@dataclass
class LabStatus:
    available: bool
    state: LabState
    message: str
    router_info: Optional[dict[str, Any]] = None
    error: Optional[str] = None
    #: Which condition the lab is in, so the interface does not have to
    #: work it out from the message.
    condition: Optional[str] = None
    #: The ordered things to do about it, in the order to do them.
    next_steps: list[dict[str, Any]] = field(default_factory=list)
    #: The separate, optional four-router topology. Never a blocker for the
    #: lab in the application, and kept apart so the two are not confused.
    optional_steps: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class SimulateRequest:
    source_ip: str
    destination_ip: str
    protocol: str = "icmp"
    ttl: int = 64
    length: int = 84
    route_matched: Optional[str] = None
    egress_interface: Optional[str] = None
    next_hop: Optional[str] = None


@dataclass
class ForwardingInfo:
    ingress_interface: str
    egress_interface: str
    next_hop: str
    route_matched: str
    action: str = "forward"


@dataclass
class PacketResponse:
    source_ip: str
    destination_ip: str
    protocol: str
    ttl: int
    length: int
    forwarding_info: ForwardingInfo


@dataclass
class VerificationDetails:
    """Verification results with provenance tracking.

    Each field reports whether it was OBSERVED (from packet capture),
    INFERRED (deduced from ping success), SIMULATED (from routing decision),
    or UNKNOWN (could not determine).
    """
    ttl_decremented: VerificationField
    checksum_valid: VerificationField
    route_matched: VerificationField


@dataclass
class SimulateResponse:
    state: LabState
    message: str
    packet: Optional[PacketResponse] = None
    capture_verified: bool = False
    verification_details: Optional[VerificationDetails] = None
    error: Optional[str] = None


# Lab topology constants - only these IPs are supported for simulation
LAB_CLIENT_IP = "192.168.10.2"
LAB_SERVER_IP = "192.168.20.2"
LAB_CLIENT_NETWORK = "192.168.10.0/24"
LAB_SERVER_NETWORK = "192.168.20.0/24"


def _parse_tcpdump_ttl(raw_output: str) -> tuple[Optional[int], VerificationProvenance]:
    """
    Parse tcpdump output to extract TTL values from IP headers.

    The capture runs on the router's EGRESS interface (rlr0s), where BOTH the
    forwarded echo request (TTL decremented by 1) and the echo reply from the
    server (TTL 64) may appear. We prefer the forwarded echo request because
    its TTL tells us whether the router decremented it; the echo reply's TTL
    is the server's original TTL and is not useful for that check.

    Returns (ttl_value, provenance) where ttl_value is the TTL of the first
    forwarded echo request found, falling back to the first TTL on any line,
    or None if not found. Provenance indicates how the value was determined.
    """
    # First pass: prefer the forwarded ICMP echo request (client -> server),
    # whose TTL was decremented by the router.
    echo_request_pattern = re.compile(
        r'ICMP echo request[^,]*,\s*ttl\s+(\d+)',
        re.IGNORECASE,
    )
    echo_matches = echo_request_pattern.findall(raw_output)
    if echo_matches:
        return int(echo_matches[0]), VerificationProvenance.OBSERVED

    # Fallback: first TTL on any line (may be echo reply TTL 64).
    ttl_pattern = re.compile(r'ttl\s+(\d+)')
    matches = ttl_pattern.findall(raw_output)
    if matches:
        return int(matches[0]), VerificationProvenance.OBSERVED
    return None, VerificationProvenance.UNKNOWN


def _parse_tcpdump_checksum(raw_output: str) -> tuple[Optional[bool], VerificationProvenance]:
    """
    Parse tcpdump output to check ICMP checksum.
    
    Returns (checksum_valid, provenance). tcpdump -v shows "checksum 0xXXXX (correct)"
    or "checksum 0xXXXX (incorrect)".
    """
    # tcpdump -v shows: "checksum 0x1234 (correct)" or "checksum 0x1234 (incorrect)"
    checksum_pattern = re.compile(r'checksum\s+0x[0-9a-fA-F]+\s+\((correct|incorrect)\)')
    matches = checksum_pattern.findall(raw_output)
    if matches:
        # Return True if any checksum is marked correct
        return matches[0].lower() == "correct", VerificationProvenance.OBSERVED
    return None, VerificationProvenance.UNKNOWN


class PacketLab:
    """
    PacketLab virtual router controller.

    Manages the isolated Linux virtual router lab (rl260-client, rl260-router, rl260-server).
    Provides controlled packet transmission and capture verification.
    """

    def __init__(self, adapter: Optional[LabAdapter] = None):
        self.adapter = adapter or get_lab_adapter()
        self._current_state = LabState.IDLE

    @property
    def current_state(self) -> LabState:
        return self._current_state

    def _set_state(self, state: LabState):
        self._current_state = state

    async def get_status(self) -> LabStatus:
        """Check lab availability and return router info.

        The report names the condition the lab is in and the ordered steps
        for it, so the reader is told what to do rather than only what is
        true. The condition and the steps come from
        `app.lab_next_steps`, which is also what `lab/README.md` and
        `scripts/lab-up.sh --help` are written from.
        """
        self._set_state(LabState.IDLE)

        readiness = await self.adapter.check_lab_readiness()

        guidance = diagnose(
            missing_tools=readiness.missing_tools,
            privilege_available=readiness.privilege.available,
            privilege_detail=readiness.privilege.detail,
            permission_issues=readiness.permission_issues,
            missing_namespaces=readiness.missing_namespaces,
            topology_issues=readiness.topology_issues,
            containerlab_missing=readiness.containerlab_missing,
        )

        if not readiness.overall_ready:
            self._set_state(LabState.UNAVAILABLE)
            return LabStatus(
                available=False,
                state=LabState.UNAVAILABLE,
                message=guidance.summary,
                error=readiness.summary,
                condition=guidance.condition.value,
                next_steps=[s.as_dict() for s in guidance.steps],
                optional_steps=[s.as_dict() for s in guidance.optional_steps],
            )

        # Build router info from actual lab topology
        router_ns = readiness.namespaces.get("rl260-router")
        client_ns = readiness.namespaces.get("rl260-client")
        server_ns = readiness.namespaces.get("rl260-server")

        interfaces = []
        routing_table = []

        if router_ns and router_ns.accessible:
            for iface in router_ns.interfaces:
                interfaces.append(iface.name)
            for route in router_ns.routes:
                routing_table.append({
                    "destination": route.destination,
                    "next_hop": route.gateway,
                    "interface": route.interface,
                })

        self._set_state(LabState.READY)
        return LabStatus(
            available=True,
            state=LabState.READY,
            message=guidance.summary,
            router_info={
                "interfaces": interfaces,
                "routing_table": routing_table,
                "client_ip": next((i.ipv4_address for i in client_ns.interfaces if i.name == "rlc0"), None) if client_ns else None,
                "server_ip": next((i.ipv4_address for i in server_ns.interfaces if i.name == "rls0"), None) if server_ns else None,
            },
            error=None,
            condition=guidance.condition.value,
            next_steps=[s.as_dict() for s in guidance.steps],
            optional_steps=[s.as_dict() for s in guidance.optional_steps],
        )

    def _validate_request(self, request: SimulateRequest) -> Optional[str]:
        """Validate simulation request. Returns error message if invalid."""
        try:
            IPv4Address(request.source_ip)
        except ValueError:
            return f"Invalid source IP: {request.source_ip}"

        try:
            IPv4Address(request.destination_ip)
        except ValueError:
            return f"Invalid destination IP: {request.destination_ip}"

        # Validate protocol - only ICMP is currently supported
        if request.protocol.lower() != "icmp":
            return f"Unsupported protocol: {request.protocol}. Only 'icmp' is currently supported."

        if request.ttl < 1 or request.ttl > 255:
            return f"TTL out of range (1-255): {request.ttl}"

        if request.length < 28 or request.length > 65535:
            return f"Packet length out of range: {request.length}"

        return None

    async def simulate(self, request: SimulateRequest) -> SimulateResponse:
        """
        Simulate packet transmission through the virtual router.

        Performs the full state machine progression and returns verified results.
        Verification details include provenance (observed/inferred/simulated/unknown)
        for each check so the caller knows what was actually measured vs deduced.
        """
        error = self._validate_request(request)
        if error:
            self._set_state(LabState.ERROR)
            return SimulateResponse(
                state=LabState.ERROR,
                message="Invalid request",
                error=error,
            )

        # Check lab status first
        status = await self.get_status()
        if not status.available:
            self._set_state(LabState.UNAVAILABLE)
            return SimulateResponse(
                state=LabState.UNAVAILABLE,
                message="Lab unavailable",
                error=status.error or "Virtual router not ready",
            )

        # Determine ingress/egress interfaces from our known topology
        ingress_interface = "rlr0c"  # router client-side
        egress_interface = request.egress_interface or "rlr0s"  # router server-side
        next_hop = request.next_hop or "192.168.20.2"  # server IP
        route_matched = request.route_matched or "192.168.20.0/24"

        self._set_state(LabState.SIMULATING)

        # Run ping with capture
        self._set_state(LabState.TRANSMITTING)
        self._set_state(LabState.CAPTURING)

        try:
            result = await self.adapter.run_ping_with_capture(
                source_namespace="rl260-client",
                destination=request.destination_ip,
                capture_interface=egress_interface,
                capture_namespace="rl260-router",
                ping_count=3,
                capture_count=6,
                filter_expr="icmp",
            )
        except Exception as e:
            self._set_state(LabState.ERROR)
            return SimulateResponse(
                state=LabState.ERROR,
                message=f"Transmission failed: {e}",
                error=str(e),
            )

        self._set_state(LabState.VERIFYING)

        # Analyze results
        ping_result = result.data["ping"] if result.data else {}
        capture_result = result.data["capture"] if result.data else {}

        # Verify capture
        packets_captured = capture_result.get("packets_captured", 0)
        capture_verified = packets_captured > 0

        # Ping success/failure
        ping_success = ping_result.get("success", False)

        # Parse tcpdump output for actual verification
        capture_raw = capture_result.get("raw_output", "")
        
        # TTL verification
        observed_ttl, ttl_provenance = _parse_tcpdump_ttl(capture_raw)
        expected_ttl = max(1, request.ttl - 1)  # TTL after one router hop
        ttl_decremented = False
        if observed_ttl is not None:
            ttl_decremented = observed_ttl == expected_ttl
        else:
            # Infer from ping success if we couldn't observe
            ttl_decremented = ping_success
            ttl_provenance = VerificationProvenance.INFERRED

        # Checksum verification
        checksum_valid, checksum_provenance = _parse_tcpdump_checksum(capture_raw)
        if checksum_valid is None:
            # Infer from ping success if we couldn't observe
            checksum_valid = ping_success
            checksum_provenance = VerificationProvenance.INFERRED

        # Route matched if we got packets on the egress interface
        route_matched_verified = packets_captured > 0
        route_provenance = VerificationProvenance.OBSERVED if route_matched_verified else VerificationProvenance.UNKNOWN

        verification = VerificationDetails(
            ttl_decremented=VerificationField(
                value=ttl_decremented,
                provenance=ttl_provenance,
                details=(
                    f"Observed TTL: {observed_ttl} (forwarded ICMP echo request "
                    f"on {egress_interface} via tcpdump -v; fell back to first TTL "
                    f"on any line if no echo request was found); "
                    f"Expected after 1 hop: {expected_ttl}"
                ) if observed_ttl is not None else "Inferred from ping success (no TTL observed in capture)"
            ),
            checksum_valid=VerificationField(
                value=checksum_valid,
                provenance=checksum_provenance,
                details="Parsed from tcpdump -v output (checksum correct/incorrect)" if checksum_provenance == VerificationProvenance.OBSERVED else "Inferred from ping success"
            ),
            route_matched=VerificationField(
                value=route_matched_verified,
                provenance=route_provenance,
                details=f"Captured {packets_captured} packets on egress interface {egress_interface}" if route_matched_verified else "No packets captured on egress interface"
            ),
        )

        # TTL in response should be original - 1 (for router hop)
        response_ttl = max(1, request.ttl - 1)

        packet_response = PacketResponse(
            source_ip=request.source_ip,
            destination_ip=request.destination_ip,
            protocol=request.protocol,
            ttl=response_ttl,
            length=request.length,
            forwarding_info=ForwardingInfo(
                ingress_interface=ingress_interface,
                egress_interface=egress_interface,
                next_hop=next_hop,
                route_matched=route_matched,
            ),
        )

        if result.success and capture_verified:
            self._set_state(LabState.COMPLETED)
            return SimulateResponse(
                state=LabState.COMPLETED,
                message="Packet transmitted and captured",
                packet=packet_response,
                capture_verified=True,
                verification_details=verification,
            )
        elif not ping_success:
            # Ping failed - transmission error
            self._set_state(LabState.ERROR)
            return SimulateResponse(
                state=LabState.ERROR,
                message="Packet transmission failed",
                packet=packet_response,
                capture_verified=False,
                verification_details=verification,
                error=result.error or "Ping failed",
            )
        elif not capture_verified:
            # Ping succeeded but no capture - timeout
            self._set_state(LabState.TIMEOUT)
            return SimulateResponse(
                state=LabState.TIMEOUT,
                message="Capture timeout - no packets captured",
                packet=packet_response,
                capture_verified=False,
                verification_details=verification,
                error="No response within capture window",
            )
        else:
            # Should not reach here, but handle gracefully
            self._set_state(LabState.ERROR)
            return SimulateResponse(
                state=LabState.ERROR,
                message="Unexpected simulation state",
                packet=packet_response,
                capture_verified=False,
                verification_details=verification,
                error="Internal logic error",
            )


# Singleton instance
_packet_lab: Optional[PacketLab] = None


def get_packet_lab() -> PacketLab:
    """Get or create the singleton PacketLab instance."""
    global _packet_lab
    if _packet_lab is None:
        _packet_lab = PacketLab()
    return _packet_lab