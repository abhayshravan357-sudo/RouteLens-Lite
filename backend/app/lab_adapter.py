"""
RouteLens Lite - Linux Network Lab Adapter

Safe adapter for the isolated Linux virtual-router lab (rl260-client, rl260-router, rl260-server).
Provides controlled operations for checking lab readiness, sending test packets, and capturing evidence.
"""

import asyncio
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from ipaddress import IPv4Address, IPv4Network
from typing import Any, Optional


class LabComponent(str, Enum):
    CLIENT = "rl260-client"
    ROUTER = "rl260-router"
    SERVER = "rl260-server"


class CheckStatus(str, Enum):
    OK = "ok"
    MISSING = "missing"
    ERROR = "error"
    PERMISSION_DENIED = "permission_denied"


@dataclass
class InterfaceInfo:
    name: str
    ipv4_address: Optional[str] = None
    ipv4_network: Optional[str] = None
    mac_address: Optional[str] = None
    state: str = "UNKNOWN"


@dataclass
class RouteInfo:
    destination: str
    gateway: Optional[str] = None
    interface: str = ""
    metric: Optional[int] = None
    proto: str = "kernel"
    scope: str = "link"


@dataclass
class NamespaceStatus:
    name: str
    exists: bool = False
    accessible: bool = False
    interfaces: list[InterfaceInfo] = field(default_factory=list)
    routes: list[RouteInfo] = field(default_factory=list)
    ip_forward_enabled: Optional[bool] = None
    error: Optional[str] = None


@dataclass
class LabReadinessReport:
    timestamp: str
    overall_ready: bool
    namespaces: dict[str, NamespaceStatus]
    expected_topology: dict[str, Any]
    missing_tools: list[str]
    permission_issues: list[str]
    summary: str


@dataclass
class PacketCaptureResult:
    interface: str
    packets_captured: int
    packets_received_by_filter: int
    packets_dropped: int
    raw_output: str
    timestamp: str
    duration_seconds: float


@dataclass
class PingResult:
    destination: str
    source_namespace: str
    packets_sent: int
    packets_received: int
    packet_loss_percent: float
    rtt_min_ms: Optional[float]
    rtt_avg_ms: Optional[float]
    rtt_max_ms: Optional[float]
    rtt_mdev_ms: Optional[float]
    raw_output: str
    timestamp: str
    success: bool


@dataclass
class LabOperationResult:
    operation: str
    success: bool
    timestamp: str
    duration_ms: float
    data: Optional[Any] = None
    error: Optional[str] = None
    warnings: list[str] = field(default_factory=list)


EXPECTED_TOPOLOGY = {
    "client": {
        "namespace": "rl260-client",
        "interface": "rlc0",
        "ipv4": "192.168.10.2/24",
        "gateway": "192.168.10.1",
    },
    "router": {
        "namespace": "rl260-router",
        "interfaces": {
            "client_side": {"name": "rlr0c", "ipv4": "192.168.10.1/24"},
            "server_side": {"name": "rlr0s", "ipv4": "192.168.20.1/24"},
        },
    },
    "server": {
        "namespace": "rl260-server",
        "interface": "rls0",
        "ipv4": "192.168.20.2/24",
        "gateway": "192.168.20.1",
    },
}

REQUIRED_TOOLS = ["ip", "ping", "tcpdump", "timeout"]


class LabAdapterError(Exception):
    """Base exception for lab adapter errors."""

    pass


class PermissionError(LabAdapterError):
    """Permission denied when accessing namespaces."""

    pass


class ToolMissingError(LabAdapterError):
    """Required system tool not available."""

    pass


class NamespaceNotFoundError(LabAdapterError):
    """Network namespace does not exist."""

    pass


class LabAdapter:
    """
    Safe adapter for the isolated Linux virtual-router lab.

    Uses pkexec for privileged namespace operations with strict input validation,
    timeouts, bounded output, and clear error handling.
    """

    def __init__(
        self,
        command_timeout: float = 10.0,
        capture_timeout: float = 5.0,
        max_output_lines: int = 100,
        use_pkexec: bool = True,
        privilege_check_timeout: float = 2.0,
    ):
        self.command_timeout = command_timeout
        self.capture_timeout = capture_timeout
        self.max_output_lines = max_output_lines
        self.use_pkexec = use_pkexec
        self.privilege_check_timeout = privilege_check_timeout
        self._tool_cache: dict[str, bool] = {}
        self._privilege_validated: bool = False
        self._privilege_available: bool = False

    def _build_ns_cmd(self, namespace: str, command: list[str]) -> list[str]:
        """Build a command to run in a network namespace."""
        base = ["pkexec"] if self.use_pkexec else ["sudo", "-n"]
        base.extend(["ip", "netns", "exec", namespace])
        base.extend(command)
        return base

    async def _validate_privileges(self) -> bool:
        """Quick non-interactive check if privilege escalation works.

        Returns True if pkexec/sudo works non-interactively, False otherwise.
        Uses a short timeout to avoid blocking on graphical prompts.
        """
        if self._privilege_validated:
            return self._privilege_available

        self._privilege_validated = True

        # Use a simple, fast command to test privilege escalation
        test_cmd = ["pkexec", "true"] if self.use_pkexec else ["sudo", "-n", "true"]

        try:
            proc = await asyncio.create_subprocess_exec(
                *test_cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            try:
                await asyncio.wait_for(proc.wait(), timeout=self.privilege_check_timeout)
                self._privilege_available = proc.returncode == 0
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                self._privilege_available = False
        except (FileNotFoundError, PermissionError, OSError):
            self._privilege_available = False

        return self._privilege_available

    async def _run_command(
        self,
        cmd: list[str],
        timeout: Optional[float] = None,
        capture_output: bool = True,
    ) -> tuple[int, str, str]:
        """Run a command with timeout and bounded output."""
        timeout = timeout or self.command_timeout
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE if capture_output else asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE if capture_output else asyncio.subprocess.DEVNULL,
            )
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                return -1, "", f"Command timed out after {timeout}s"
            stdout_str = stdout.decode("utf-8", errors="replace") if stdout else ""
            stderr_str = stderr.decode("utf-8", errors="replace") if stderr else ""
            if capture_output and len(stdout_str.splitlines()) > self.max_output_lines:
                stdout_str = "\n".join(stdout_str.splitlines()[: self.max_output_lines]) + "\n[output truncated]"

            return proc.returncode or 0, stdout_str, stderr_str
        except FileNotFoundError as e:
            return -1, "", f"Command not found: {e}"
        except PermissionError as e:
            return -1, "", f"Permission denied: {e}"
        except Exception as e:
            return -1, "", f"Command execution failed: {e}"

    def _check_tool(self, tool: str) -> bool:
        """Check if a tool is available (cached)."""
        if tool not in self._tool_cache:
            try:
                subprocess.run(
                    ["which", tool],
                    capture_output=True,
                    check=True,
                    timeout=2,
                )
                self._tool_cache[tool] = True
            except subprocess.CalledProcessError:
                self._tool_cache[tool] = False
        return self._tool_cache[tool]

    def check_tools(self) -> tuple[list[str], list[str]]:
        """Check which required tools are available."""
        available = []
        missing = []
        for tool in REQUIRED_TOOLS:
            if self._check_tool(tool):
                available.append(tool)
            else:
                missing.append(tool)
        return available, missing

    async def _run_in_namespace(
        self, namespace: str, command: list[str], timeout: Optional[float] = None
    ) -> tuple[int, str, str]:
        """Run a command in a network namespace."""
        if not self._check_tool("ip"):
            raise ToolMissingError("ip command not available")

        # Check privileges before attempting namespace operations
        if not await self._validate_privileges():
            return -1, "", (
                f"Privilege escalation (pkexec/sudo) not available for namespace operations. "
                f"Configure passwordless sudo for 'ip netns exec' commands or run backend with appropriate capabilities."
            )

        full_cmd = self._build_ns_cmd(namespace, command)
        return await self._run_command(full_cmd, timeout=timeout)

    async def check_namespace_exists(self, namespace: str) -> bool:
        """Check if a network namespace exists."""
        try:
            result = subprocess.run(
                ["ip", "netns", "list"],
                capture_output=True,
                text=True,
                timeout=2,
            )
            return namespace in result.stdout
        except Exception:
            return False

    async def get_namespace_status(self, namespace: str) -> NamespaceStatus:
        """Get comprehensive status of a network namespace."""
        status = NamespaceStatus(name=namespace)
        status.exists = await self.check_namespace_exists(namespace)

        if not status.exists:
            status.error = f"Namespace {namespace} does not exist"
            return status

        # Check accessibility and get interfaces
        rc, stdout, stderr = await self._run_in_namespace(namespace, ["ip", "addr", "show"])
        if rc != 0:
            combined = (stdout + stderr).lower()
            if "permission" in combined or "operation not permitted" in combined or "request dismissed" in combined or "error executing command as another user" in combined:
                status.error = f"Permission denied accessing {namespace}. Privilege escalation (sudo/pkexec) not configured for web backend."
                return status
            status.error = f"Failed to get interfaces: {stderr}"
            return status

        status.accessible = True
        status.interfaces = self._parse_ip_addr(stdout)

        # Get routes
        rc, stdout, stderr = await self._run_in_namespace(namespace, ["ip", "route", "show"])
        if rc == 0:
            status.routes = self._parse_ip_route(stdout)

        # Check IP forwarding (only relevant for router)
        if namespace == LabComponent.ROUTER:
            rc, stdout, stderr = await self._run_in_namespace(
                namespace, ["cat", "/proc/sys/net/ipv4/ip_forward"]
            )
            if rc == 0:
                status.ip_forward_enabled = stdout.strip() == "1"

        return status

    def _parse_ip_addr(self, output: str) -> list[InterfaceInfo]:
        """Parse 'ip addr show' output."""
        interfaces = []
        current_iface: Optional[InterfaceInfo] = None

        for line in output.splitlines():
            line = line.strip()
            if not line:
                continue

            # New interface line: "4: rlc0@if3: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 ..."
            if line[0].isdigit() and ": " in line:
                if current_iface:
                    interfaces.append(current_iface)
                parts = line.split(": ", 1)[1].split()
                name = parts[0].split("@")[0].rstrip(":")
                state = "DOWN"
                if "<" in line and ">" in line:
                    flags = line[line.index("<") + 1 : line.index(">")]
                    state = "UP" if "UP" in flags else "DOWN"
                current_iface = InterfaceInfo(name=name, state=state)
                continue

            if current_iface:
                if line.startswith("link/ether"):
                    current_iface.mac_address = line.split()[1]
                elif line.startswith("inet "):
                    parts = line.split()
                    current_iface.ipv4_address = parts[1].split("/")[0]
                    current_iface.ipv4_network = parts[1]

        if current_iface:
            interfaces.append(current_iface)

        return interfaces

    def _parse_ip_route(self, output: str) -> list[RouteInfo]:
        """Parse 'ip route show' output."""
        routes = []
        for line in output.splitlines():
            line = line.strip()
            if not line:
                continue

            parts = line.split()
            route = RouteInfo(destination="", interface="")

            i = 0
            if parts[i] == "default":
                route.destination = "0.0.0.0/0"
                i += 1
            else:
                route.destination = parts[i]
                i += 1

            while i < len(parts):
                if parts[i] == "via":
                    route.gateway = parts[i + 1]
                    i += 2
                elif parts[i] == "dev":
                    route.interface = parts[i + 1]
                    i += 2
                elif parts[i] == "proto":
                    route.proto = parts[i + 1]
                    i += 2
                elif parts[i] == "scope":
                    route.scope = parts[i + 1]
                    i += 2
                elif parts[i] == "metric":
                    try:
                        route.metric = int(parts[i + 1])
                    except (ValueError, IndexError):
                        pass
                    i += 2
                else:
                    i += 1

            routes.append(route)

        return routes

    async def check_lab_readiness(self) -> LabReadinessReport:
        """Comprehensive lab readiness check."""
        timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        available_tools, missing_tools = self.check_tools()
        permission_issues = []

        namespaces = {}
        for component in LabComponent:
            ns_status = await self.get_namespace_status(component)
            namespaces[component] = ns_status
            if ns_status.error and "permission" in ns_status.error.lower():
                permission_issues.append(f"{component}: {ns_status.error}")

        # Validate expected topology (only if accessible)
        topology_ok = True
        expected = EXPECTED_TOPOLOGY
        issues = []

        # Check client
        client_ns = namespaces.get(LabComponent.CLIENT)
        if client_ns and client_ns.accessible:
            client_iface = next((i for i in client_ns.interfaces if i.name == "rlc0"), None)
            if not client_iface or client_iface.ipv4_network != "192.168.10.2/24":
                topology_ok = False
                issues.append("Client interface rlc0 missing or wrong IP")
            # Check default route
            default_route = next((r for r in client_ns.routes if r.destination == "0.0.0.0/0"), None)
            if not default_route or default_route.gateway != "192.168.10.1":
                topology_ok = False
                issues.append("Client missing default route via 192.168.10.1")

        # Check router
        router_ns = namespaces.get(LabComponent.ROUTER)
        if router_ns and router_ns.accessible:
            client_iface = next((i for i in router_ns.interfaces if i.name == "rlr0c"), None)
            server_iface = next((i for i in router_ns.interfaces if i.name == "rlr0s"), None)
            if not client_iface or client_iface.ipv4_network != "192.168.10.1/24":
                topology_ok = False
                issues.append("Router client-side interface rlr0c missing or wrong IP")
            if not server_iface or server_iface.ipv4_network != "192.168.20.1/24":
                topology_ok = False
                issues.append("Router server-side interface rlr0s missing or wrong IP")
            if not router_ns.ip_forward_enabled:
                topology_ok = False
                issues.append("IP forwarding not enabled on router")

        # Check server
        server_ns = namespaces.get(LabComponent.SERVER)
        if server_ns and server_ns.accessible:
            server_iface = next((i for i in server_ns.interfaces if i.name == "rls0"), None)
            if not server_iface or server_iface.ipv4_network != "192.168.20.2/24":
                topology_ok = False
                issues.append("Server interface rls0 missing or wrong IP")
            default_route = next((r for r in server_ns.routes if r.destination == "0.0.0.0/0"), None)
            if not default_route or default_route.gateway != "192.168.20.1":
                topology_ok = False
                issues.append("Server missing default route via 192.168.20.1")

        # Lab is ready if topology is correct, all namespaces accessible, tools available, no permission issues
        overall_ready = (
            topology_ok
            and all(ns.exists and ns.accessible for ns in namespaces.values())
            and len(missing_tools) == 0
            and len(permission_issues) == 0
        )

        if overall_ready:
            summary = "Lab is fully ready for packet operations"
        elif not topology_ok:
            summary = f"Lab topology issues: {'; '.join(issues)}"
        elif missing_tools:
            summary = f"Missing required tools: {', '.join(missing_tools)}"
        elif permission_issues:
            summary = f"Permission issues: {'; '.join(permission_issues)}"
        else:
            summary = "Lab not ready"

        return LabReadinessReport(
            timestamp=timestamp,
            overall_ready=overall_ready,
            namespaces=namespaces,
            expected_topology=expected,
            missing_tools=missing_tools,
            permission_issues=permission_issues,
            summary=summary,
        )

    async def ping(
        self,
        source_namespace: str,
        destination: str,
        count: int = 3,
        interval: float = 0.2,
        timeout: float = 2.0,
    ) -> PingResult:
        """Send ICMP ping from a namespace to a destination."""
        start_time = time.time()
        timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

        # Validate inputs
        try:
            IPv4Address(destination)
        except ValueError:
            return PingResult(
                destination=destination,
                source_namespace=source_namespace,
                packets_sent=0,
                packets_received=0,
                packet_loss_percent=100.0,
                rtt_min_ms=None,
                rtt_avg_ms=None,
                rtt_max_ms=None,
                rtt_mdev_ms=None,
                raw_output="",
                timestamp=timestamp,
                success=False,
            )

        if count < 1 or count > 20:
            count = max(1, min(20, count))

        cmd = ["ping", "-c", str(count), "-i", str(interval), "-W", str(int(timeout)), destination]
        rc, stdout, stderr = await self._run_in_namespace(source_namespace, cmd, timeout=timeout * count + 5)

        success = rc == 0
        packets_sent = count
        packets_received = 0
        packet_loss = 100.0
        rtt_min = rtt_avg = rtt_max = rtt_mdev = None

        if stdout:
            # Parse ping output
            for line in stdout.splitlines():
                if "packets transmitted" in line:
                    parts = line.split(",")
                    for part in parts:
                        part = part.strip()
                        if "packets transmitted" in part:
                            packets_sent = int(part.split()[0])
                        elif "received" in part:
                            packets_received = int(part.split()[0])
                        elif "packet loss" in part:
                            packet_loss = float(part.split("%")[0].split()[-1])
                elif "rtt min/avg/max/mdev" in line or "round-trip" in line:
                    try:
                        rtt_part = line.split("=")[1].split("ms")[0].strip()
                        rtt_values = rtt_part.split("/")
                        if len(rtt_values) >= 4:
                            rtt_min = float(rtt_values[0])
                            rtt_avg = float(rtt_values[1])
                            rtt_max = float(rtt_values[2])
                            rtt_mdev = float(rtt_values[3])
                    except (ValueError, IndexError):
                        pass

        return PingResult(
            destination=destination,
            source_namespace=source_namespace,
            packets_sent=packets_sent,
            packets_received=packets_received,
            packet_loss_percent=packet_loss,
            rtt_min_ms=rtt_min,
            rtt_avg_ms=rtt_avg,
            rtt_max_ms=rtt_max,
            rtt_mdev_ms=rtt_mdev,
            raw_output=stdout + ("\n" + stderr if stderr else ""),
            timestamp=timestamp,
            success=success,
        )

    async def capture_packets(
        self,
        namespace: str,
        interface: str,
        filter_expr: str = "icmp",
        count: int = 10,
        duration: Optional[float] = None,
    ) -> PacketCaptureResult:
        """Capture packets on a namespace interface with verbose output for verification."""
        start_time = time.time()
        timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

        # Use -v for verbose output including TTL and checksum
        cmd = ["timeout", str(int(self.capture_timeout)), "tcpdump", "-v", "-i", interface, "-n", "-c", str(count), filter_expr]
        rc, stdout, stderr = await self._run_in_namespace(namespace, cmd, timeout=self.capture_timeout + 2)

        packets_captured = 0
        packets_received = 0
        packets_dropped = 0

        if stdout:
            for line in stdout.splitlines():
                if "packets captured" in line:
                    try:
                        packets_captured = int(line.split()[0])
                    except (ValueError, IndexError):
                        pass
                elif "packets received by filter" in line:
                    try:
                        packets_received = int(line.split()[0])
                    except (ValueError, IndexError):
                        pass
                elif "packets dropped" in line:
                    try:
                        packets_dropped = int(line.split()[0])
                    except (ValueError, IndexError):
                        pass

        return PacketCaptureResult(
            interface=interface,
            packets_captured=packets_captured,
            packets_received_by_filter=packets_received,
            packets_dropped=packets_dropped,
            raw_output=stdout + ("\n" + stderr if stderr else ""),
            timestamp=timestamp,
            duration_seconds=time.time() - start_time,
        )

    async def run_ping_with_capture(
        self,
        source_namespace: str,
        destination: str,
        capture_interface: str,
        capture_namespace: str,
        ping_count: int = 3,
        capture_count: int = 10,
        filter_expr: str = "icmp",
    ) -> LabOperationResult:
        """Run ping and capture packets simultaneously."""
        start_time = time.time()
        timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

        # Start capture in background
        capture_task = asyncio.create_task(
            self.capture_packets(
                namespace=capture_namespace,
                interface=capture_interface,
                filter_expr=filter_expr,
                count=capture_count,
            )
        )

        # Small delay to let capture start
        await asyncio.sleep(0.5)

        # Run ping
        ping_result = await self.ping(
            source_namespace=source_namespace,
            destination=destination,
            count=ping_count,
        )

        # Wait for capture to complete
        capture_result = await capture_task

        duration_ms = (time.time() - start_time) * 1000

        success = ping_result.success and capture_result.packets_captured > 0

        return LabOperationResult(
            operation="ping_with_capture",
            success=success,
            timestamp=timestamp,
            duration_ms=duration_ms,
            data={
                "ping": ping_result.__dict__,
                "capture": capture_result.__dict__,
            },
            error=None if success else "Ping failed or no packets captured",
            warnings=[] if success else ["Verify lab connectivity and capture filter"],
        )


# Singleton instance for the application
_lab_adapter: Optional[LabAdapter] = None


def get_lab_adapter() -> LabAdapter:
    """Get or create the singleton lab adapter instance."""
    global _lab_adapter
    if _lab_adapter is None:
        _lab_adapter = LabAdapter()
    return _lab_adapter