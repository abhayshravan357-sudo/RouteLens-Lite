"""
RouteLens Lite - Network Collector

Read-only collection of real local network information from the host system.
Uses `ip -j` JSON output for reliable parsing. No privilege escalation required.
"""

import asyncio
import json
import socket
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from ipaddress import IPv4Address, IPv4Interface, IPv6Address, IPv6Interface
from typing import Any, Optional


@dataclass
class InterfaceInfo:
    """Network interface information."""
    name: str
    index: int
    state: str  # UP, DOWN, UNKNOWN
    mtu: Optional[int] = None
    mac_address: Optional[str] = None
    ipv4_addresses: list[str] = field(default_factory=list)
    ipv4_networks: list[str] = field(default_factory=list)
    ipv6_addresses: list[str] = field(default_factory=list)
    ipv6_networks: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)


@dataclass
class RouteInfo:
    """Routing table entry."""
    destination: str
    gateway: Optional[str] = None
    interface: Optional[str] = None
    metric: Optional[int] = None
    proto: str = "kernel"
    scope: str = "link"
    pref_src: Optional[str] = None


@dataclass
class NeighborInfo:
    """ARP/IPv6 neighbor cache entry."""
    ip_address: str
    interface: str
    mac_address: Optional[str] = None
    state: str = "UNKNOWN"  # REACHABLE, STALE, DELAY, PROBE, FAILED, PERMANENT, NOARP
    is_router: bool = False


@dataclass
class CollectionResult:
    """Result of a network data collection operation."""
    timestamp: str
    success: bool
    data: Optional[Any] = None
    error: Optional[str] = None
    command: str = ""
    duration_ms: float = 0.0


class NetworkCollectorError(Exception):
    """Base exception for network collector errors."""
    pass


class CommandNotFoundError(NetworkCollectorError):
    """Required system command not found."""
    pass


class CommandTimeoutError(NetworkCollectorError):
    """Command execution timed out."""
    pass


class ParseError(NetworkCollectorError):
    """Failed to parse command output."""
    pass


@dataclass
class DnsRecord:
    """DNS record information."""
    hostname: str
    address: str
    record_type: str  # A, AAAA, CNAME, etc.
    ttl: Optional[int] = None


@dataclass
class DnsResolutionResult:
    """Result of DNS resolution."""
    hostname: str
    addresses: list[DnsRecord]
    latency_ms: float
    error: Optional[str] = None

    @property
    def success(self) -> bool:
        """Whether the DNS resolution was successful."""
        return self.error is None and len(self.addresses) > 0


class NetworkCollector:
    """
    Safe collector for real local network information.
    
    Uses `ip -j` JSON output for reliable parsing. All operations are read-only
    and require no privilege escalation.
    """

    def __init__(
        self,
        command_timeout: float = 5.0,
        max_output_bytes: int = 1024 * 1024,  # 1MB
    ):
        self.command_timeout = command_timeout
        self.max_output_bytes = max_output_bytes
        self._tool_cache: dict[str, bool] = {}

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
        required = ["ip"]
        available = []
        missing = []
        for tool in required:
            if self._check_tool(tool):
                available.append(tool)
            else:
                missing.append(tool)
        return available, missing

    async def _run_command(
        self,
        cmd: list[str],
        timeout: Optional[float] = None,
    ) -> tuple[int, str, str]:
        """Run a command with timeout and bounded output."""
        timeout = timeout or self.command_timeout
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                return -1, "", f"Command timed out after {timeout}s"
            
            # Check output size
            stdout_bytes = len(stdout) if stdout else 0
            stderr_bytes = len(stderr) if stderr else 0
            if stdout_bytes > self.max_output_bytes or stderr_bytes > self.max_output_bytes:
                return -1, "", "Command output exceeded maximum size"
            
            stdout_str = stdout.decode("utf-8", errors="replace") if stdout else ""
            stderr_str = stderr.decode("utf-8", errors="replace") if stderr else ""
            
            return proc.returncode or 0, stdout_str, stderr_str
        except FileNotFoundError as e:
            return -1, "", f"Command not found: {e}"
        except PermissionError as e:
            return -1, "", f"Permission denied: {e}"
        except Exception as e:
            return -1, "", f"Command execution failed: {e}"

    async def collect_interfaces(self) -> CollectionResult:
        """Collect network interfaces using `ip -j addr show`."""
        start_time = datetime.now()
        command = "ip -j addr show"
        
        if not self._check_tool("ip"):
            return CollectionResult(
                timestamp=start_time.isoformat() + "Z",
                success=False,
                error="`ip` command not available",
                command=command,
            )

        rc, stdout, stderr = await self._run_command(["ip", "-j", "addr", "show"])
        
        duration_ms = (datetime.now() - start_time).total_seconds() * 1000

        if rc != 0:
            return CollectionResult(
                timestamp=start_time.isoformat() + "Z",
                success=False,
                error=f"Command failed (rc={rc}): {stderr}",
                command=command,
                duration_ms=duration_ms,
            )

        try:
            interfaces_data = json.loads(stdout)
        except json.JSONDecodeError as e:
            return CollectionResult(
                timestamp=start_time.isoformat() + "Z",
                success=False,
                error=f"Failed to parse JSON output: {e}",
                command=command,
                duration_ms=duration_ms,
            )

        interfaces = []
        for iface_data in interfaces_data:
            iface = self._parse_interface(iface_data)
            interfaces.append(iface)

        return CollectionResult(
            timestamp=start_time.isoformat() + "Z",
            success=True,
            data=interfaces,
            command=command,
            duration_ms=duration_ms,
        )

    def _parse_interface(self, data: dict) -> InterfaceInfo:
        """Parse interface data from `ip -j addr show` JSON output."""
        name = data.get("ifname", "")
        index = data.get("ifindex", 0)
        state = data.get("operstate", "UNKNOWN").upper()
        mtu = data.get("mtu")
        flags = data.get("flags", [])

        mac_address = None
        if "address" in data:
            mac_address = data["address"]

        ipv4_addresses = []
        ipv4_networks = []
        ipv6_addresses = []
        ipv6_networks = []

        for addr_info in data.get("addr_info", []):
            family = addr_info.get("family", "")
            local = addr_info.get("local", "")
            prefixlen = addr_info.get("prefixlen", 0)

            if family == "inet" and local:
                ipv4_addresses.append(local)
                if prefixlen:
                    ipv4_networks.append(f"{local}/{prefixlen}")
            elif family == "inet6" and local:
                ipv6_addresses.append(local)
                if prefixlen:
                    ipv6_networks.append(f"{local}/{prefixlen}")

        return InterfaceInfo(
            name=name,
            index=index,
            state=state,
            mtu=mtu,
            mac_address=mac_address,
            ipv4_addresses=ipv4_addresses,
            ipv4_networks=ipv4_networks,
            ipv6_addresses=ipv6_addresses,
            ipv6_networks=ipv6_networks,
            flags=flags,
        )

    async def collect_routes(self) -> CollectionResult:
        """Collect routing table using `ip -j route show`."""
        start_time = datetime.now()
        command = "ip -j route show"

        if not self._check_tool("ip"):
            return CollectionResult(
                timestamp=start_time.isoformat() + "Z",
                success=False,
                error="`ip` command not available",
                command=command,
            )

        rc, stdout, stderr = await self._run_command(["ip", "-j", "route", "show"])

        duration_ms = (datetime.now() - start_time).total_seconds() * 1000

        if rc != 0:
            return CollectionResult(
                timestamp=start_time.isoformat() + "Z",
                success=False,
                error=f"Command failed (rc={rc}): {stderr}",
                command=command,
                duration_ms=duration_ms,
            )

        try:
            routes_data = json.loads(stdout)
        except json.JSONDecodeError as e:
            return CollectionResult(
                timestamp=start_time.isoformat() + "Z",
                success=False,
                error=f"Failed to parse JSON output: {e}",
                command=command,
                duration_ms=duration_ms,
            )

        routes = []
        for route_data in routes_data:
            route = self._parse_route(route_data)
            routes.append(route)

        return CollectionResult(
            timestamp=start_time.isoformat() + "Z",
            success=True,
            data=routes,
            command=command,
            duration_ms=duration_ms,
        )

    def _parse_route(self, data: dict) -> RouteInfo:
        """Parse route data from `ip -j route show` JSON output."""
        destination = data.get("dst", "default")
        if destination == "default":
            destination = "0.0.0.0/0"

        gateway = data.get("gateway")
        interface = data.get("dev")
        metric = data.get("metric")
        proto = data.get("protocol", "kernel")
        scope = data.get("scope", "link")
        pref_src = data.get("prefsrc")

        return RouteInfo(
            destination=destination,
            gateway=gateway,
            interface=interface,
            metric=metric,
            proto=proto,
            scope=scope,
            pref_src=pref_src,
        )

    async def collect_neighbors(self) -> CollectionResult:
        """Collect ARP/IPv6 neighbors using `ip -j neigh show`."""
        start_time = datetime.now()
        command = "ip -j neigh show"

        if not self._check_tool("ip"):
            return CollectionResult(
                timestamp=start_time.isoformat() + "Z",
                success=False,
                error="`ip` command not available",
                command=command,
            )

        rc, stdout, stderr = await self._run_command(["ip", "-j", "neigh", "show"])

        duration_ms = (datetime.now() - start_time).total_seconds() * 1000

        if rc != 0:
            return CollectionResult(
                timestamp=start_time.isoformat() + "Z",
                success=False,
                error=f"Command failed (rc={rc}): {stderr}",
                command=command,
                duration_ms=duration_ms,
            )

        try:
            neighbors_data = json.loads(stdout)
        except json.JSONDecodeError as e:
            return CollectionResult(
                timestamp=start_time.isoformat() + "Z",
                success=False,
                error=f"Failed to parse JSON output: {e}",
                command=command,
                duration_ms=duration_ms,
            )

        neighbors = []
        for neigh_data in neighbors_data:
            neighbor = self._parse_neighbor(neigh_data)
            neighbors.append(neighbor)

        return CollectionResult(
            timestamp=start_time.isoformat() + "Z",
            success=True,
            data=neighbors,
            command=command,
            duration_ms=duration_ms,
        )

    def _parse_neighbor(self, data: dict) -> NeighborInfo:
        """Parse neighbor data from `ip -j neigh show` JSON output."""
        ip_address = data.get("dst", "")
        interface = data.get("dev", "")
        mac_address = data.get("lladdr")
        
        # state can be a string or a list of strings in ip -j output
        state_raw = data.get("state", "UNKNOWN")
        if isinstance(state_raw, list):
            state = state_raw[0].upper() if state_raw else "UNKNOWN"
        else:
            state = str(state_raw).upper()
            
        is_router = data.get("router", False)

        return NeighborInfo(
            ip_address=ip_address,
            interface=interface,
            mac_address=mac_address,
            state=state,
            is_router=is_router,
        )

    async def collect_all(self) -> dict[str, CollectionResult]:
        """Collect all network data in parallel."""
        interfaces_task = asyncio.create_task(self.collect_interfaces())
        routes_task = asyncio.create_task(self.collect_routes())
        neighbors_task = asyncio.create_task(self.collect_neighbors())

        interfaces, routes, neighbors = await asyncio.gather(
            interfaces_task,
            routes_task,
            neighbors_task,
        )

        return {
            "interfaces": interfaces,
            "routes": routes,
            "neighbors": neighbors,
        }

    async def resolve_dns(
        self,
        hostname: str,
        timeout: float = 5.0,
        family: int = socket.AF_UNSPEC,
    ) -> DnsResolutionResult:
        """
        Resolve a hostname to IP addresses using asyncio.getaddrinfo().
        
        Uses asyncio's native DNS resolution with configurable timeout.
        Supports both IPv4 and IPv6 resolution.
        
        Args:
            hostname: The hostname to resolve
            timeout: Maximum time to wait for resolution (seconds)
            family: Address family (AF_INET, AF_INET6, or AF_UNSPEC)
            
        Returns:
            DnsResolutionResult with addresses, latency, and any error
        """
        start_time = datetime.now()
        
        # Validate hostname
        if not hostname or not isinstance(hostname, str):
            return DnsResolutionResult(
                hostname=hostname,
                addresses=[],
                latency_ms=0.0,
                error="Invalid hostname",
            )
        
        hostname = hostname.strip()
        if not hostname:
            return DnsResolutionResult(
                hostname=hostname,
                addresses=[],
                latency_ms=0.0,
                error="Empty hostname",
            )
        
        try:
            # Use asyncio's native getaddrinfo with timeout
            loop = asyncio.get_running_loop()
            addrinfo = await asyncio.wait_for(
                loop.getaddrinfo(
                    hostname,
                    0,  # port 0 means any port
                    family=family,
                    type=socket.SOCK_STREAM,
                    proto=socket.IPPROTO_TCP,
                    flags=socket.AI_ADDRCONFIG | socket.AI_V4MAPPED,
                ),
                timeout=timeout,
            )
            
            latency_ms = (datetime.now() - start_time).total_seconds() * 1000
            
            # Parse results
            records = []
            seen_addresses = set()
            
            for info in addrinfo:
                family_type = info[0]
                sockaddr = info[4]
                address = sockaddr[0]
                
                # Deduplicate addresses
                if address in seen_addresses:
                    continue
                seen_addresses.add(address)
                
                record_type = "A" if family_type == socket.AF_INET else "AAAA"
                records.append(DnsRecord(
                    hostname=hostname,
                    address=address,
                    record_type=record_type,
                ))
            
            return DnsResolutionResult(
                hostname=hostname,
                addresses=records,
                latency_ms=latency_ms,
            )
            
        except asyncio.TimeoutError:
            latency_ms = (datetime.now() - start_time).total_seconds() * 1000
            return DnsResolutionResult(
                hostname=hostname,
                addresses=[],
                latency_ms=latency_ms,
                error=f"DNS resolution timed out after {timeout}s",
            )
        except socket.gaierror as e:
            latency_ms = (datetime.now() - start_time).total_seconds() * 1000
            # Map common gaierror codes to readable messages
            error_map = {
                socket.EAI_NONAME: f"Hostname not found: {hostname}",
                socket.EAI_AGAIN: "Temporary DNS failure (retry may succeed)",
                socket.EAI_FAIL: "Non-recoverable DNS failure",
                socket.EAI_NODATA: f"No DNS records found for {hostname}",
                socket.EAI_MEMORY: "Out of memory during DNS resolution",
                socket.EAI_SYSTEM: f"System error: {e}",
            }
            error_msg = error_map.get(e.errno, f"DNS resolution failed: {e}")
            return DnsResolutionResult(
                hostname=hostname,
                addresses=[],
                latency_ms=latency_ms,
                error=error_msg,
            )
        except Exception as e:
            latency_ms = (datetime.now() - start_time).total_seconds() * 1000
            return DnsResolutionResult(
                hostname=hostname,
                addresses=[],
                latency_ms=latency_ms,
                error=f"Unexpected error during DNS resolution: {e}",
            )

    async def check_connectivity(
        self,
        target: str,
        port: Optional[int] = None,
        protocol: str = "tcp",
        timeout: float = 5.0,
        count: int = 3,
        interval: float = 0.2,
    ) -> "ConnectivityResult":
        """
        Check connectivity to a target using ICMP ping or TCP connect.
        
        Args:
            target: Target hostname or IP address
            port: Port number for TCP connect (required for TCP protocol)
            protocol: "icmp" for ICMP ping, "tcp" for TCP connect
            timeout: Per-attempt timeout in seconds
            count: Number of attempts (for ICMP ping)
            interval: Interval between attempts in seconds
            
        Returns:
            ConnectivityResult with reachability, latency, and any error
        """
        start_time = datetime.now()
        
        if protocol.lower() == "icmp":
            return await self._icmp_ping(target, count, interval, timeout)
        elif protocol.lower() == "tcp":
            if port is None:
                return ConnectivityResult(
                    target=target,
                    port=port,
                    protocol="tcp",
                    reachable=False,
                    latency_ms=0.0,
                    error="Port is required for TCP connectivity check",
                )
            return await self._tcp_connect(target, port, timeout)
        else:
            return ConnectivityResult(
                target=target,
                port=port,
                protocol=protocol,
                reachable=False,
                latency_ms=0.0,
                error=f"Unsupported protocol: {protocol}. Use 'icmp' or 'tcp'.",
            )

    async def _icmp_ping(
        self,
        target: str,
        count: int,
        interval: float,
        timeout: float,
    ) -> "ConnectivityResult":
        """Perform ICMP ping using system ping command."""
        start_time = datetime.now()
        
        # Validate target
        try:
            socket.inet_aton(target)  # IPv4
        except socket.error:
            try:
                socket.inet_pton(socket.AF_INET6, target)  # IPv6
            except socket.error:
                # Assume hostname, will be resolved by ping
                pass
        
        # Clamp count and timeout
        count = max(1, min(10, count))
        timeout = max(0.5, min(30.0, timeout))
        interval = max(0.1, min(5.0, interval))
        
        if not self._check_tool("ping"):
            return ConnectivityResult(
                target=target,
                port=None,
                protocol="icmp",
                reachable=False,
                latency_ms=0.0,
                error="`ping` command not available",
            )
        
        cmd = ["ping", "-c", str(count), "-i", str(interval), "-W", str(int(timeout)), target]
        
        rc, stdout, stderr = await self._run_command(cmd, timeout=timeout * count + 5)
        
        latency_ms = (datetime.now() - start_time).total_seconds() * 1000
        
        if rc == 0 and stdout:
            # Parse ping output for statistics
            packets_sent = count
            packets_received = 0
            rtt_min = rtt_avg = rtt_max = rtt_mdev = None
            
            for line in stdout.splitlines():
                if "packets transmitted" in line:
                    parts = line.split(",")
                    for part in parts:
                        part = part.strip()
                        if "packets transmitted" in part:
                            packets_sent = int(part.split()[0])
                        elif "received" in part:
                            packets_received = int(part.split()[0])
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
            
            reachable = packets_received > 0
            avg_latency = rtt_avg if rtt_avg is not None else latency_ms
            
            return ConnectivityResult(
                target=target,
                port=None,
                protocol="icmp",
                reachable=reachable,
                latency_ms=avg_latency,
                packets_sent=packets_sent,
                packets_received=packets_received,
                packet_loss_percent=((packets_sent - packets_received) / packets_sent * 100) if packets_sent > 0 else 100.0,
                rtt_min_ms=rtt_min,
                rtt_avg_ms=rtt_avg,
                rtt_max_ms=rtt_max,
                rtt_mdev_ms=rtt_mdev,
            )
        else:
            return ConnectivityResult(
                target=target,
                port=None,
                protocol="icmp",
                reachable=False,
                latency_ms=latency_ms,
                packets_sent=count,
                packets_received=0,
                packet_loss_percent=100.0,
                error=stderr or "Ping failed",
            )

    async def _tcp_connect(self, target: str, port: int, timeout: float) -> "ConnectivityResult":
        """Perform TCP connect using asyncio.open_connection."""
        start_time = datetime.now()
        
        # Validate port
        if port < 1 or port > 65535:
            return ConnectivityResult(
                target=target,
                port=port,
                protocol="tcp",
                reachable=False,
                latency_ms=0.0,
                error=f"Invalid port: {port}",
            )
        
        # Clamp timeout
        timeout = max(0.5, min(30.0, timeout))
        
        try:
            # Resolve target first
            loop = asyncio.get_running_loop()
            addrinfo = await asyncio.wait_for(
                loop.getaddrinfo(target, port, family=socket.AF_UNSPEC, type=socket.SOCK_STREAM),
                timeout=timeout,
            )
            
            if not addrinfo:
                return ConnectivityResult(
                    target=target,
                    port=port,
                    protocol="tcp",
                    reachable=False,
                    latency_ms=0.0,
                    error=f"Could not resolve target: {target}",
                )
            
            # Try each address until one connects
            last_error = None
            for info in addrinfo:
                family = info[0]
                sockaddr = info[4]
                
                try:
                    reader, writer = await asyncio.wait_for(
                        asyncio.open_connection(sockaddr[0], sockaddr[1], family=family),
                        timeout=timeout,
                    )
                    
                    latency_ms = (datetime.now() - start_time).total_seconds() * 1000
                    
                    writer.close()
                    await writer.wait_closed()
                    
                    return ConnectivityResult(
                        target=target,
                        port=port,
                        protocol="tcp",
                        reachable=True,
                        latency_ms=latency_ms,
                    )
                except (asyncio.TimeoutError, ConnectionRefusedError, OSError) as e:
                    last_error = e
                    continue
            
            latency_ms = (datetime.now() - start_time).total_seconds() * 1000
            return ConnectivityResult(
                target=target,
                port=port,
                protocol="tcp",
                reachable=False,
                latency_ms=latency_ms,
                error=f"Connection failed: {last_error}",
            )
            
        except asyncio.TimeoutError:
            latency_ms = (datetime.now() - start_time).total_seconds() * 1000
            return ConnectivityResult(
                target=target,
                port=port,
                protocol="tcp",
                reachable=False,
                latency_ms=latency_ms,
                error=f"DNS resolution timed out after {timeout}s",
            )
        except socket.gaierror as e:
            latency_ms = (datetime.now() - start_time).total_seconds() * 1000
            return ConnectivityResult(
                target=target,
                port=port,
                protocol="tcp",
                reachable=False,
                latency_ms=latency_ms,
                error=f"Could not resolve target: {target}",
            )
        except Exception as e:
            latency_ms = (datetime.now() - start_time).total_seconds() * 1000
            return ConnectivityResult(
                target=target,
                port=port,
                protocol="tcp",
                reachable=False,
                latency_ms=latency_ms,
                error=f"Unexpected error during TCP connect: {e}",
            )


@dataclass
class ConnectivityResult:
    """Result of connectivity check."""
    target: str
    port: Optional[int]
    protocol: str
    reachable: bool
    latency_ms: float
    packets_sent: Optional[int] = None
    packets_received: Optional[int] = None
    packet_loss_percent: Optional[float] = None
    rtt_min_ms: Optional[float] = None
    rtt_avg_ms: Optional[float] = None
    rtt_max_ms: Optional[float] = None
    rtt_mdev_ms: Optional[float] = None
    error: Optional[str] = None


@dataclass
class TracerouteHop:
    """Single hop in a traceroute."""
    ttl: int
    address: Optional[str] = None
    hostname: Optional[str] = None
    rtt_ms: Optional[float] = None
    error: Optional[str] = None


@dataclass
class TracerouteResult:
    """Result of a traceroute operation."""
    target: str
    hops: list[TracerouteHop]
    max_hops: int
    timeout_per_hop: float
    probes_per_hop: int
    completed: bool
    total_time_ms: float
    error: Optional[str] = None

    @property
    def success(self) -> bool:
        """Whether traceroute completed (reached destination or max hops)."""
        return self.completed and self.error is None


class NetworkCollector:
    """
    Safe collector for real local network information.
    
    Uses `ip -j` JSON output for reliable parsing. All operations are read-only
    and require no privilege escalation.
    """

    def __init__(
        self,
        command_timeout: float = 5.0,
        max_output_bytes: int = 1024 * 1024,  # 1MB
    ):
        self.command_timeout = command_timeout
        self.max_output_bytes = max_output_bytes
        self._tool_cache: dict[str, bool] = {}

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
        required = ["ip"]
        available = []
        missing = []
        for tool in required:
            if self._check_tool(tool):
                available.append(tool)
            else:
                missing.append(tool)
        return available, missing

    async def _run_command(
        self,
        cmd: list[str],
        timeout: Optional[float] = None,
    ) -> tuple[int, str, str]:
        """Run a command with timeout and bounded output."""
        timeout = timeout or self.command_timeout
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                return -1, "", f"Command timed out after {timeout}s"
            
            # Check output size
            stdout_bytes = len(stdout) if stdout else 0
            stderr_bytes = len(stderr) if stderr else 0
            if stdout_bytes > self.max_output_bytes or stderr_bytes > self.max_output_bytes:
                return -1, "", "Command output exceeded maximum size"
            
            stdout_str = stdout.decode("utf-8", errors="replace") if stdout else ""
            stderr_str = stderr.decode("utf-8", errors="replace") if stderr else ""
            
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
        required = ["ip"]
        available = []
        missing = []
        for tool in required:
            if self._check_tool(tool):
                available.append(tool)
            else:
                missing.append(tool)
        return available, missing

    async def collect_interfaces(self) -> CollectionResult:
        """Collect network interfaces using `ip -j addr show`."""
        start_time = datetime.now()
        command = "ip -j addr show"
        
        if not self._check_tool("ip"):
            return CollectionResult(
                timestamp=start_time.isoformat() + "Z",
                success=False,
                error="`ip` command not available",
                command=command,
            )

        rc, stdout, stderr = await self._run_command(["ip", "-j", "addr", "show"])
        
        duration_ms = (datetime.now() - start_time).total_seconds() * 1000

        if rc != 0:
            return CollectionResult(
                timestamp=start_time.isoformat() + "Z",
                success=False,
                error=f"Command failed (rc={rc}): {stderr}",
                command=command,
                duration_ms=duration_ms,
            )

        try:
            interfaces_data = json.loads(stdout)
        except json.JSONDecodeError as e:
            return CollectionResult(
                timestamp=start_time.isoformat() + "Z",
                success=False,
                error=f"Failed to parse JSON output: {e}",
                command=command,
                duration_ms=duration_ms,
            )

        interfaces = []
        for iface_data in interfaces_data:
            iface = self._parse_interface(iface_data)
            interfaces.append(iface)

        return CollectionResult(
            timestamp=start_time.isoformat() + "Z",
            success=True,
            data=interfaces,
            command=command,
            duration_ms=duration_ms,
        )

    def _parse_interface(self, data: dict) -> InterfaceInfo:
        """Parse interface data from `ip -j addr show` JSON output."""
        name = data.get("ifname", "")
        index = data.get("ifindex", 0)
        state = data.get("operstate", "UNKNOWN").upper()
        mtu = data.get("mtu")
        flags = data.get("flags", [])

        mac_address = None
        if "address" in data:
            mac_address = data["address"]

        ipv4_addresses = []
        ipv4_networks = []
        ipv6_addresses = []
        ipv6_networks = []

        for addr_info in data.get("addr_info", []):
            family = addr_info.get("family", "")
            local = addr_info.get("local", "")
            prefixlen = addr_info.get("prefixlen", 0)

            if family == "inet" and local:
                ipv4_addresses.append(local)
                if prefixlen:
                    ipv4_networks.append(f"{local}/{prefixlen}")
            elif family == "inet6" and local:
                ipv6_addresses.append(local)
                if prefixlen:
                    ipv6_networks.append(f"{local}/{prefixlen}")

        return InterfaceInfo(
            name=name,
            index=index,
            state=state,
            mtu=mtu,
            mac_address=mac_address,
            ipv4_addresses=ipv4_addresses,
            ipv4_networks=ipv4_networks,
            ipv6_addresses=ipv6_addresses,
            ipv6_networks=ipv6_networks,
            flags=flags,
        )

    async def collect_routes(self) -> CollectionResult:
        """Collect routing table using `ip -j route show`."""
        start_time = datetime.now()
        command = "ip -j route show"

        if not self._check_tool("ip"):
            return CollectionResult(
                timestamp=start_time.isoformat() + "Z",
                success=False,
                error="`ip` command not available",
                command=command,
            )

        rc, stdout, stderr = await self._run_command(["ip", "-j", "route", "show"])

        duration_ms = (datetime.now() - start_time).total_seconds() * 1000

        if rc != 0:
            return CollectionResult(
                timestamp=start_time.isoformat() + "Z",
                success=False,
                error=f"Command failed (rc={rc}): {stderr}",
                command=command,
                duration_ms=duration_ms,
            )

        try:
            routes_data = json.loads(stdout)
        except json.JSONDecodeError as e:
            return CollectionResult(
                timestamp=start_time.isoformat() + "Z",
                success=False,
                error=f"Failed to parse JSON output: {e}",
                command=command,
                duration_ms=duration_ms,
            )

        routes = []
        for route_data in routes_data:
            route = self._parse_route(route_data)
            routes.append(route)

        return CollectionResult(
            timestamp=start_time.isoformat() + "Z",
            success=True,
            data=routes,
            command=command,
            duration_ms=duration_ms,
        )

    def _parse_route(self, data: dict) -> RouteInfo:
        """Parse route data from `ip -j route show` JSON output."""
        destination = data.get("dst", "default")
        if destination == "default":
            destination = "0.0.0.0/0"

        gateway = data.get("gateway")
        interface = data.get("dev")
        metric = data.get("metric")
        proto = data.get("protocol", "kernel")
        scope = data.get("scope", "link")
        pref_src = data.get("prefsrc")

        return RouteInfo(
            destination=destination,
            gateway=gateway,
            interface=interface,
            metric=metric,
            proto=proto,
            scope=scope,
            pref_src=pref_src,
        )

    async def collect_neighbors(self) -> CollectionResult:
        """Collect ARP/IPv6 neighbors using `ip -j neigh show`."""
        start_time = datetime.now()
        command = "ip -j neigh show"

        if not self._check_tool("ip"):
            return CollectionResult(
                timestamp=start_time.isoformat() + "Z",
                success=False,
                error="`ip` command not available",
                command=command,
            )

        rc, stdout, stderr = await self._run_command(["ip", "-j", "neigh", "show"])

        duration_ms = (datetime.now() - start_time).total_seconds() * 1000

        if rc != 0:
            return CollectionResult(
                timestamp=start_time.isoformat() + "Z",
                success=False,
                error=f"Command failed (rc={rc}): {stderr}",
                command=command,
                duration_ms=duration_ms,
            )

        try:
            neighbors_data = json.loads(stdout)
        except json.JSONDecodeError as e:
            return CollectionResult(
                timestamp=start_time.isoformat() + "Z",
                success=False,
                error=f"Failed to parse JSON output: {e}",
                command=command,
                duration_ms=duration_ms,
            )

        neighbors = []
        for neigh_data in neighbors_data:
            neighbor = self._parse_neighbor(neigh_data)
            neighbors.append(neighbor)

        return CollectionResult(
            timestamp=start_time.isoformat() + "Z",
            success=True,
            data=neighbors,
            command=command,
            duration_ms=duration_ms,
        )

    def _parse_neighbor(self, data: dict) -> NeighborInfo:
        """Parse neighbor data from `ip -j neigh show` JSON output."""
        ip_address = data.get("dst", "")
        interface = data.get("dev", "")
        mac_address = data.get("lladdr")
        
        # state can be a string or a list of strings in ip -j output
        state_raw = data.get("state", "UNKNOWN")
        if isinstance(state_raw, list):
            state = state_raw[0].upper() if state_raw else "UNKNOWN"
        else:
            state = str(state_raw).upper()
            
        is_router = data.get("router", False)

        return NeighborInfo(
            ip_address=ip_address,
            interface=interface,
            mac_address=mac_address,
            state=state,
            is_router=is_router,
        )

    async def collect_all(self) -> dict[str, CollectionResult]:
        """Collect all network data in parallel."""
        interfaces_task = asyncio.create_task(self.collect_interfaces())
        routes_task = asyncio.create_task(self.collect_routes())
        neighbors_task = asyncio.create_task(self.collect_neighbors())

        interfaces, routes, neighbors = await asyncio.gather(
            interfaces_task,
            routes_task,
            neighbors_task,
        )

        return {
            "interfaces": interfaces,
            "routes": routes,
            "neighbors": neighbors,
        }

    async def resolve_dns(
        self,
        hostname: str,
        timeout: float = 5.0,
        family: int = socket.AF_UNSPEC,
    ) -> DnsResolutionResult:
        """
        Resolve a hostname to IP addresses using asyncio.getaddrinfo().
        
        Uses asyncio's native DNS resolution with configurable timeout.
        Supports both IPv4 and IPv6 resolution.
        
        Args:
            hostname: The hostname to resolve
            timeout: Maximum time to wait for resolution (seconds)
            family: Address family (AF_INET, AF_INET6, or AF_UNSPEC)
            
        Returns:
            DnsResolutionResult with addresses, latency, and any error
        """
        start_time = datetime.now()
        
        # Validate hostname
        if not hostname or not isinstance(hostname, str):
            return DnsResolutionResult(
                hostname=hostname,
                addresses=[],
                latency_ms=0.0,
                error="Invalid hostname",
            )
        
        hostname = hostname.strip()
        if not hostname:
            return DnsResolutionResult(
                hostname=hostname,
                addresses=[],
                latency_ms=0.0,
                error="Empty hostname",
            )
        
        try:
            # Use asyncio's native getaddrinfo with timeout
            loop = asyncio.get_running_loop()
            addrinfo = await asyncio.wait_for(
                loop.getaddrinfo(
                    hostname,
                    0,  # port 0 means any port
                    family=family,
                    type=socket.SOCK_STREAM,
                    proto=socket.IPPROTO_TCP,
                    flags=socket.AI_ADDRCONFIG | socket.AI_V4MAPPED,
                ),
                timeout=timeout,
            )
            
            latency_ms = (datetime.now() - start_time).total_seconds() * 1000
            
            # Parse results
            records = []
            seen_addresses = set()
            
            for info in addrinfo:
                family_type = info[0]
                sockaddr = info[4]
                address = sockaddr[0]
                
                # Deduplicate addresses
                if address in seen_addresses:
                    continue
                seen_addresses.add(address)
                
                record_type = "A" if family_type == socket.AF_INET else "AAAA"
                records.append(DnsRecord(
                    hostname=hostname,
                    address=address,
                    record_type=record_type,
                ))
            
            return DnsResolutionResult(
                hostname=hostname,
                addresses=records,
                latency_ms=latency_ms,
            )
            
        except asyncio.TimeoutError:
            latency_ms = (datetime.now() - start_time).total_seconds() * 1000
            return DnsResolutionResult(
                hostname=hostname,
                addresses=[],
                latency_ms=latency_ms,
                error=f"DNS resolution timed out after {timeout}s",
            )
        except socket.gaierror as e:
            latency_ms = (datetime.now() - start_time).total_seconds() * 1000
            # Map common gaierror codes to readable messages
            error_map = {
                socket.EAI_NONAME: f"Hostname not found: {hostname}",
                socket.EAI_AGAIN: "Temporary DNS failure (retry may succeed)",
                socket.EAI_FAIL: "Non-recoverable DNS failure",
                socket.EAI_NODATA: f"No DNS records found for {hostname}",
                socket.EAI_MEMORY: "Out of memory during DNS resolution",
                socket.EAI_SYSTEM: f"System error: {e}",
            }
            error_msg = error_map.get(e.errno, f"DNS resolution failed: {e}")
            return DnsResolutionResult(
                hostname=hostname,
                addresses=[],
                latency_ms=latency_ms,
                error=error_msg,
            )
        except Exception as e:
            latency_ms = (datetime.now() - start_time).total_seconds() * 1000
            return DnsResolutionResult(
                hostname=hostname,
                addresses=[],
                latency_ms=latency_ms,
                error=f"Unexpected error during DNS resolution: {e}",
            )

    async def check_connectivity(
        self,
        target: str,
        port: Optional[int] = None,
        protocol: str = "tcp",
        timeout: float = 5.0,
        count: int = 3,
        interval: float = 0.2,
    ) -> "ConnectivityResult":
        """
        Check connectivity to a target using ICMP ping or TCP connect.
        
        Args:
            target: Target hostname or IP address
            port: Port number for TCP connect (required for TCP protocol)
            protocol: "icmp" for ICMP ping, "tcp" for TCP connect
            timeout: Per-attempt timeout in seconds
            count: Number of attempts (for ICMP ping)
            interval: Interval between attempts in seconds
            
        Returns:
            ConnectivityResult with reachability, latency, and any error
        """
        start_time = datetime.now()
        
        if protocol.lower() == "icmp":
            return await self._icmp_ping(target, count, interval, timeout)
        elif protocol.lower() == "tcp":
            if port is None:
                return ConnectivityResult(
                    target=target,
                    port=port,
                    protocol="tcp",
                    reachable=False,
                    latency_ms=0.0,
                    error="Port is required for TCP connectivity check",
                )
            return await self._tcp_connect(target, port, timeout)
        else:
            return ConnectivityResult(
                target=target,
                port=port,
                protocol=protocol,
                reachable=False,
                latency_ms=0.0,
                error=f"Unsupported protocol: {protocol}. Use 'icmp' or 'tcp'.",
            )

    async def _icmp_ping(
        self,
        target: str,
        count: int,
        interval: float,
        timeout: float,
    ) -> "ConnectivityResult":
        """Perform ICMP ping using system ping command."""
        start_time = datetime.now()
        
        # Validate target
        try:
            socket.inet_aton(target)  # IPv4
        except socket.error:
            try:
                socket.inet_pton(socket.AF_INET6, target)  # IPv6
            except socket.error:
                # Assume hostname, will be resolved by ping
                pass
        
        # Clamp count and timeout
        count = max(1, min(10, count))
        timeout = max(0.5, min(30.0, timeout))
        interval = max(0.1, min(5.0, interval))
        
        if not self._check_tool("ping"):
            return ConnectivityResult(
                target=target,
                port=None,
                protocol="icmp",
                reachable=False,
                latency_ms=0.0,
                error="`ping` command not available",
            )
        
        cmd = ["ping", "-c", str(count), "-i", str(interval), "-W", str(int(timeout)), target]
        
        rc, stdout, stderr = await self._run_command(cmd, timeout=timeout * count + 5)
        
        latency_ms = (datetime.now() - start_time).total_seconds() * 1000
        
        if rc == 0 and stdout:
            # Parse ping output for statistics
            packets_sent = count
            packets_received = 0
            rtt_min = rtt_avg = rtt_max = rtt_mdev = None
            
            for line in stdout.splitlines():
                if "packets transmitted" in line:
                    parts = line.split(",")
                    for part in parts:
                        part = part.strip()
                        if "packets transmitted" in part:
                            packets_sent = int(part.split()[0])
                        elif "received" in part:
                            packets_received = int(part.split()[0])
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
            
            reachable = packets_received > 0
            avg_latency = rtt_avg if rtt_avg is not None else latency_ms
            
            return ConnectivityResult(
                target=target,
                port=None,
                protocol="icmp",
                reachable=reachable,
                latency_ms=avg_latency,
                packets_sent=packets_sent,
                packets_received=packets_received,
                packet_loss_percent=((packets_sent - packets_received) / packets_sent * 100) if packets_sent > 0 else 100.0,
                rtt_min_ms=rtt_min,
                rtt_avg_ms=rtt_avg,
                rtt_max_ms=rtt_max,
                rtt_mdev_ms=rtt_mdev,
            )
        else:
            return ConnectivityResult(
                target=target,
                port=None,
                protocol="icmp",
                reachable=False,
                latency_ms=latency_ms,
                packets_sent=count,
                packets_received=0,
                packet_loss_percent=100.0,
                error=stderr or "Ping failed",
            )

    async def _tcp_connect(self, target: str, port: int, timeout: float) -> "ConnectivityResult":
        """Perform TCP connect using asyncio.open_connection."""
        start_time = datetime.now()
        
        # Validate port
        if port < 1 or port > 65535:
            return ConnectivityResult(
                target=target,
                port=port,
                protocol="tcp",
                reachable=False,
                latency_ms=0.0,
                error=f"Invalid port: {port}",
            )
        
        # Clamp timeout
        timeout = max(0.5, min(30.0, timeout))
        
        try:
            # Resolve target first
            loop = asyncio.get_running_loop()
            addrinfo = await asyncio.wait_for(
                loop.getaddrinfo(target, port, family=socket.AF_UNSPEC, type=socket.SOCK_STREAM),
                timeout=timeout,
            )
            
            if not addrinfo:
                return ConnectivityResult(
                    target=target,
                    port=port,
                    protocol="tcp",
                    reachable=False,
                    latency_ms=0.0,
                    error=f"Could not resolve target: {target}",
                )
            
            # Try each address until one connects
            last_error = None
            for info in addrinfo:
                family = info[0]
                sockaddr = info[4]
                
                try:
                    reader, writer = await asyncio.wait_for(
                        asyncio.open_connection(sockaddr[0], sockaddr[1], family=family),
                        timeout=timeout,
                    )
                    
                    latency_ms = (datetime.now() - start_time).total_seconds() * 1000
                    
                    writer.close()
                    await writer.wait_closed()
                    
                    return ConnectivityResult(
                        target=target,
                        port=port,
                        protocol="tcp",
                        reachable=True,
                        latency_ms=latency_ms,
                    )
                except (asyncio.TimeoutError, ConnectionRefusedError, OSError) as e:
                    last_error = e
                    continue
            
            latency_ms = (datetime.now() - start_time).total_seconds() * 1000
            return ConnectivityResult(
                target=target,
                port=port,
                protocol="tcp",
                reachable=False,
                latency_ms=latency_ms,
                error=f"Connection failed: {last_error}",
            )
            
        except asyncio.TimeoutError:
            latency_ms = (datetime.now() - start_time).total_seconds() * 1000
            return ConnectivityResult(
                target=target,
                port=port,
                protocol="tcp",
                reachable=False,
                latency_ms=latency_ms,
                error=f"DNS resolution timed out after {timeout}s",
            )
        except socket.gaierror as e:
            latency_ms = (datetime.now() - start_time).total_seconds() * 1000
            return ConnectivityResult(
                target=target,
                port=port,
                protocol="tcp",
                reachable=False,
                latency_ms=latency_ms,
                error=f"Could not resolve target: {target}",
            )
        except Exception as e:
            latency_ms = (datetime.now() - start_time).total_seconds() * 1000
            return ConnectivityResult(
                target=target,
                port=port,
                protocol="tcp",
                reachable=False,
                latency_ms=latency_ms,
                error=f"Unexpected error during TCP connect: {e}",
            )

    async def trace_route(
        self,
        target: str,
        max_hops: int = 30,
        timeout_per_hop: float = 2.0,
        probes_per_hop: int = 1,
        overall_timeout: float = 60.0,
    ) -> TracerouteResult:
        """
        Perform traceroute to a target using the system traceroute command.
        
        Args:
            target: Target hostname or IP address
            max_hops: Maximum number of hops (1-64)
            timeout_per_hop: Timeout per hop in seconds
            probes_per_hop: Number of probes per hop (1-3)
            overall_timeout: Maximum total time for the operation
            
        Returns:
            TracerouteResult with list of hops
        """
        start_time = datetime.now()
        
        # Validate target
        try:
            socket.inet_aton(target)  # IPv4
        except socket.error:
            try:
                socket.inet_pton(socket.AF_INET6, target)  # IPv6
            except socket.error:
                # Assume hostname, will be resolved by traceroute
                pass
        
        # Validate and clamp parameters
        max_hops = max(1, min(64, max_hops))
        timeout_per_hop = max(0.5, min(10.0, timeout_per_hop))
        probes_per_hop = max(1, min(3, probes_per_hop))
        overall_timeout = max(5.0, min(300.0, overall_timeout))
        
        # Check if traceroute tool is available
        if not self._check_tool("traceroute"):
            return TracerouteResult(
                target=target,
                hops=[],
                max_hops=max_hops,
                timeout_per_hop=timeout_per_hop,
                probes_per_hop=probes_per_hop,
                completed=False,
                total_time_ms=0.0,
                error="`traceroute` command not available",
            )
        
        # Build traceroute command
        # -n: don't resolve hostnames (faster, we can resolve separately if needed)
        # -w: timeout per hop in seconds
        # -q: number of probes per hop
        # -m: max hops
        # target: the destination
        cmd = [
            "traceroute",
            "-n",                    # Don't resolve hostnames
            "-w", str(int(timeout_per_hop)),  # Wait time per hop
            "-q", str(probes_per_hop),        # Probes per hop
            "-m", str(max_hops),              # Max hops
            target,
        ]
        
        # Run with overall timeout
        rc, stdout, stderr = await self._run_command(cmd, timeout=overall_timeout)
        
        total_time_ms = (datetime.now() - start_time).total_seconds() * 1000
        
        hops = []
        completed = False
        
        if rc == 0 and stdout:
            hops = self._parse_traceroute_output(stdout, max_hops)
            # Check if we reached the destination (last hop is the target)
            if hops and hops[-1].address == target:
                completed = True
            elif len(hops) >= max_hops:
                completed = True  # Reached max hops
            else:
                completed = True  # Completed for other reasons (e.g., destination reached)
        else:
            # Command failed - may still have partial output
            if stdout:
                hops = self._parse_traceroute_output(stdout, max_hops)
            error_msg = stderr or f"traceroute failed with exit code {rc}"
            return TracerouteResult(
                target=target,
                hops=hops,
                max_hops=max_hops,
                timeout_per_hop=timeout_per_hop,
                probes_per_hop=probes_per_hop,
                completed=False,
                total_time_ms=(datetime.now() - start_time).total_seconds() * 1000,
                error=error_msg,
            )
        
        return TracerouteResult(
            target=target,
            hops=hops,
            max_hops=max_hops,
            timeout_per_hop=timeout_per_hop,
            probes_per_hop=probes_per_hop,
            completed=completed,
            total_time_ms=(datetime.now() - start_time).total_seconds() * 1000,
            error=None,
        )
    
    def _parse_traceroute_output(self, output: str, max_hops: int) -> list[TracerouteHop]:
        """
        Parse traceroute command output.
        
        Expected format (traceroute -n):
        1  192.168.1.1  1.234 ms  1.123 ms  1.456 ms
        2  10.0.0.1     2.345 ms  2.234 ms  2.567 ms
        3  * * *
        ...
        
        Or with hostname resolution (without -n):
        1  gateway (192.168.1.1)  1.234 ms  1.123 ms  1.456 ms
        """
        hops = []
        lines = output.strip().split('\n')
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            # Skip header lines
            if line.startswith("traceroute to") or line.startswith("traceroute: "):
                continue
            
            parts = line.split()
            if len(parts) < 2:
                continue
            
            # First part should be the TTL/hop number
            try:
                ttl = int(parts[0])
            except (ValueError, IndexError):
                continue
            
            if ttl > max_hops:
                break
            
            hop = TracerouteHop(ttl=ttl)
            
            # Parse the rest of the line
            # Format varies:
            # With -n: "1  192.168.1.1  1.234 ms  1.123 ms  1.456 ms"
            # Without -n: "1  gateway (192.168.1.1)  1.234 ms  1.123 ms  1.456 ms"
            # Timeout: "2  * * *"
            
            remaining = parts[1:]
            
            if not remaining or remaining[0] == '*':
                # Timeout - no response
                hop.error = "timeout"
                hops.append(hop)
                continue
            
            # For traceroute with -n flag (our default), the address is the first token
            # For traceroute without -n, it could be "hostname (IP)" format
            address_found = False
            
            # Check if the first token is an IP address (for -n format)
            if self._is_ip_address(remaining[0]):
                hop.address = remaining[0].strip('()')
                address_found = True
            # Check for "hostname (IP)" format
            elif len(remaining) >= 2 and remaining[0].endswith('(') and self._is_ip_address(remaining[1].rstrip(')')):
                hop.hostname = remaining[0].rstrip('(')
                hop.address = remaining[1].rstrip(')')
                address_found = True
            elif self._is_ip_address(remaining[0].strip('()')):
                # Handle case where IP might have parentheses
                hop.address = remaining[0].strip('()')
                address_found = True
            elif remaining[0] == '*':
                hop.error = "timeout"
                hops.append(hop)
                continue
            else:
                # First token is not an IP - treat as hostname
                hop.hostname = remaining[0]
                # Look for IP in subsequent tokens (parenthesized)
                for i in range(1, len(remaining)):
                    if self._is_ip_address(remaining[i].strip('()')):
                        hop.address = remaining[i].strip('()')
                        address_found = True
                        break
            
            if not address_found and remaining[0] != '*':
                # No address found, but not a timeout
                hop.error = "no_address"
            
            # Parse RTT values - they appear as "X.XXX ms" which splits into ["X.XXX", "ms"]
            # So we look for "ms" tokens and take the previous token as the value
            rtt_values = []
            for i, part in enumerate(remaining):
                if part == 'ms' and i > 0:
                    try:
                        rtt_values.append(float(remaining[i - 1]))
                    except ValueError:
                        pass
            
            if rtt_values:
                hop.rtt_ms = sum(rtt_values) / len(rtt_values)
            
            hops.append(hop)
            
            if len(hops) >= max_hops:
                break
        
        return hops
    
    def _is_ip_address(self, s: str) -> bool:
        """Check if string is an IPv4 or IPv6 address (possibly with parentheses)."""
        s = s.strip('()')
        try:
            socket.inet_aton(s)
            return True
        except socket.error:
            try:
                socket.inet_pton(socket.AF_INET6, s)
                return True
            except socket.error:
                return False


# Singleton instance
_network_collector: Optional[NetworkCollector] = None


def get_network_collector() -> NetworkCollector:
    """Get or create the singleton network collector instance."""
    global _network_collector
    if _network_collector is None:
        _network_collector = NetworkCollector()
    return _network_collector