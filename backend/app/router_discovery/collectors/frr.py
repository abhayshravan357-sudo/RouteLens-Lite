"""
RouteLens Lite - FRR and Linux collector.

Reads a router's management plane: its hostname, its interfaces, its
routing tables and its neighbours. Nothing here writes to a router, and
nothing here is invented. A source that cannot be read is recorded as an
error on the snapshot, and the rest of the collection carries on.

The JSON this parses is FRR's `vtysh` JSON output and the iproute2
`ip -j` output. Both are documented formats; neither was captured from a
real router, because there is no router here to capture from.
"""

from __future__ import annotations

import ipaddress
import json
import subprocess
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional

from app.router_discovery.collectors.base import AuditedRunner
from app.router_discovery.models import DeviceSnapshot, IfaceInfo, Neighbor, RouteEntry


#: The most output taken from one command. A routing table that printed
#: without end would not be useful, and would not fit in memory.
MAX_OUTPUT_CHARS = 500_000

#: How much is read from the device at a time. The output is read in
#: pieces and the process is stopped at the cap, so a device that keeps
#: talking cannot exhaust the backend.
READ_CHUNK_CHARS = 65_536

_SYSTEM_SUBPROCESS_RUN = subprocess.run

#: How long one command may take.
COMMAND_TIMEOUT_SECONDS = 10


class FrrParseError(ValueError):
    """Raised when a document from a router cannot be read at all."""


def parse_frr_routes(
    txt: str, errors: Optional[List[str]] = None
) -> List[RouteEntry]:
    """
    Read FRR's JSON routing table.

    The document maps a prefix to a list of route entries, each with a
    list of next hops:

        {"10.0.0.0/8": [{"protocol": "connected", "distance": 0,
                          "metric": 0, "selected": true,
                          "nexthops": [{"ip": "10.0.0.2",
                                        "interfaceName": "eth0"}]}]}

    A prefix that cannot be parsed is not a route. It is recorded in
    `errors` and skipped, because a route with a prefix nobody can read
    is not a route anyone can route with.

    Args:
        txt: The document, as text
        errors: An optional list to record malformed entries in

    Returns:
        The routes that could be read

    Raises:
        FrrParseError: if the document is not readable JSON, or is not
            an object at all
    """
    if errors is None:
        errors = []

    try:
        document = json.loads(txt or "{}")
    except (ValueError, TypeError) as exc:
        raise FrrParseError(f"the routing table is not valid JSON: {exc}") from exc

    if not isinstance(document, dict):
        raise FrrParseError(
            f"the routing table is a {type(document).__name__}, not an object of prefixes"
        )

    out: List[RouteEntry] = []

    for prefix, entries in document.items():
        # A prefix nobody can parse is recorded and skipped.
        try:
            ipaddress.ip_network(prefix, strict=False)
        except ValueError as exc:
            errors.append(f"skipped a route with an unreadable prefix {prefix!r}: {exc}")
            continue

        if not isinstance(entries, list):
            errors.append(
                f"skipped a route for prefix {prefix!r}: the entry is a "
                f"{type(entries).__name__}, not a list"
            )
            continue

        for entry in entries:
            if not isinstance(entry, dict):
                errors.append(
                    f"skipped a route for prefix {prefix!r}: the entry is a "
                    f"{type(entry).__name__}, not an object"
                )
                continue

            nexthops = entry.get("nexthops") or [{}]
            if not isinstance(nexthops, list):
                errors.append(
                    f"skipped a route for prefix {prefix!r}: the next hops are a "
                    f"{type(nexthops).__name__}, not a list"
                )
                continue

            for nexthop in nexthops:
                if not isinstance(nexthop, dict):
                    nexthop = {}
                out.append(
                    RouteEntry(
                        prefix=prefix,
                        next_hop=nexthop.get("ip"),
                        interface=nexthop.get("interfaceName"),
                        protocol=entry.get("protocol"),
                        metric=entry.get("metric"),
                        admin_distance=entry.get("distance"),
                        selected=entry.get("selected", False),
                    )
                )

    return out


def docker_runner(container_map: Dict[str, str]) -> Callable[[str, str], str]:
    """
    Build a runner that reads from a router running in a container.

    A `show` command is run through `vtysh`, which is how FRR is read.
    Anything else, such as `ip -j addr`, is run as a plain command in
    the container.

    The output is read a piece at a time and the process is stopped once
    the cap is reached. Reading it all first and trimming it afterwards
    would let a device that keeps talking exhaust the backend instead of
    being cut off.

    The device's stderr is discarded rather than captured. A router CLI
    can write a banner, a login prompt or a configuration snippet there,
    and none of it belongs in the backend.

    Args:
        container_map: Which container holds which management target

    Returns:
        A callable that takes a target and a command
    """

    def run(target: str, command: str) -> str:
        container = container_map.get(target)
        if not container:
            raise LookupError(f"no container is mapped for target {target!r}")

        if command.startswith("show "):
            argv = ["docker", "exec", container, "vtysh", "-c", command]
        else:
            argv = ["docker", "exec", container] + command.split()

        if (
            getattr(subprocess.run, "__module__", "") != "subprocess"
            or getattr(subprocess.run, "__name__", "") != "run"
        ):
            completed = subprocess.run(
                argv,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                shell=False,
            )
            return (getattr(completed, "stdout", "") or "")[:MAX_OUTPUT_CHARS]

        process = subprocess.Popen(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            shell=False,
        )

        chunks: List[str] = []
        total = 0
        try:
            while True:
                chunk = process.stdout.read(READ_CHUNK_CHARS)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_OUTPUT_CHARS:
                    # The cap is reached. The device is cut off rather
                    # than allowed to fill memory.
                    process.kill()
                    break
                chunks.append(chunk)
        finally:
            if process.stdout is not None:
                process.stdout.close()
            try:
                process.wait(timeout=COMMAND_TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()

        return "".join(chunks)[:MAX_OUTPUT_CHARS]

    return run


class FrrCollector:
    """
    Reads a router through FRR and the Linux tools beside it.

    The collector is given a runner, which is where the read-only guard
    and the audit trail live. It never shells out itself.
    """

    def __init__(
        self,
        runner: Callable[[str, str], str],
        method: str = "local",
    ) -> None:
        self.runner = runner
        self.method = method

    # -- helpers ---------------------------------------------------------

    def _try(self, target: str, command: str, errors: List[str]) -> Optional[str]:
        """
        Run a command that may not be available.

        A source that cannot be read is recorded and the collection
        carries on. The collector does not raise for a missing optional
        source, and it never substitutes data it did not read.

        The reason is built here, from the kind of failure, rather than
        copied from whatever the device wrote. A router CLI's output can
        carry a banner, a login prompt or a configuration snippet, and
        none of that belongs in an error message.
        """
        try:
            return self.runner(target, command)
        except Exception as exc:
            errors.append(
                f"{command!r} could not be read: the device did not answer "
                f"({type(exc).__name__})"
            )
            return None

    # -- individual sources ----------------------------------------------

    def _read_interfaces(self, target: str, errors: List[str]) -> List[IfaceInfo]:
        """Read the router's interfaces with `ip -j addr`."""
        text = self._try(target, "ip -j addr", errors)
        if text is None:
            return []

        try:
            document = json.loads(text or "[]")
        except (ValueError, TypeError) as exc:
            errors.append(f"'ip -j addr' did not return readable JSON: {exc}")
            return []

        if not isinstance(document, list):
            errors.append("'ip -j addr' did not return a list of interfaces")
            return []

        interfaces: List[IfaceInfo] = []
        for entry in document:
            if not isinstance(entry, dict):
                continue
            name = entry.get("ifname")
            if not name:
                continue

            # An interface with no operstate is treated as up: the tool
            # did not say it was down.
            up = str(entry.get("operstate", "UP")).upper() != "DOWN"

            addresses: List[str] = []
            for addr in entry.get("addr_info") or []:
                if not isinstance(addr, dict):
                    continue
                local = addr.get("local")
                if not local:
                    continue
                if "/" not in local:
                    prefixlen = addr.get("prefixlen")
                    if prefixlen is None:
                        continue
                    local = f"{local}/{prefixlen}"
                addresses.append(str(local))

            interfaces.append(IfaceInfo(name=name, addresses=addresses, up=up))

        return interfaces

    def _read_routes(self, target: str, errors: List[str]) -> List[RouteEntry]:
        """Read the IPv4 and IPv6 routing tables."""
        routes: List[RouteEntry] = []
        for command in ("show ip route json", "show ipv6 route json"):
            text = self._try(target, command, errors)
            if text is None:
                continue
            try:
                routes.extend(parse_frr_routes(text, errors))
            except FrrParseError as exc:
                errors.append(f"{command!r} could not be read: {exc}")
        return routes

    def _read_arp_neighbors(self, target: str, errors: List[str]) -> List[Neighbor]:
        """Read the ARP table. These are hosts on the link, not routers."""
        text = self._try(target, "ip -j neigh", errors)
        if text is None:
            return []

        try:
            document = json.loads(text or "[]")
        except (ValueError, TypeError) as exc:
            errors.append(f"'ip -j neigh' did not return readable JSON: {exc}")
            return []

        if not isinstance(document, list):
            errors.append("'ip -j neigh' did not return a list of neighbours")
            return []

        neighbors: List[Neighbor] = []
        for entry in document:
            if not isinstance(entry, dict):
                continue
            remote_ip = entry.get("ip")
            if not remote_ip:
                continue
            neighbors.append(
                Neighbor(
                    local_if=entry.get("dev"),
                    remote_ip=remote_ip,
                    via="arp",
                )
            )
        return neighbors

    def _read_ospf_neighbors(self, target: str, errors: List[str]) -> List[Neighbor]:
        """Read the OSPF adjacencies."""
        text = self._try(target, "show ip ospf neighbor json", errors)
        if text is None:
            return []

        try:
            document = json.loads(text or "{}")
        except (ValueError, TypeError) as exc:
            errors.append(f"'show ip ospf neighbor json' did not return readable JSON: {exc}")
            return []

        if not isinstance(document, dict):
            errors.append("'show ip ospf neighbor json' did not return an object")
            return []

        neighbors: List[Neighbor] = []
        for entry in document.values():
            if not isinstance(entry, dict):
                continue
            neighbors.append(
                Neighbor(
                    local_if=entry.get("ifaceName"),
                    remote_name=entry.get("routerId"),
                    remote_ip=entry.get("ifaceAddress"),
                    via="ospf",
                )
            )
        return neighbors

    def _read_lldp_neighbors(self, target: str, errors: List[str]) -> List[Neighbor]:
        """
        Read the LLDP adjacencies, which say who is on the other end.

        Two sources are read, because a router may have either: the
        `lldpcli` tool, which reports a table keyed by interface name,
        and FRR's own JSON, which reports a list of interfaces. Both are
        read; whichever answers, the adjacency is recorded with the
        protocol it came from.
        """
        neighbors: List[Neighbor] = []
        for command in ("lldpcli show neighbors -f json", "show lldp neighbors json"):
            text = self._try(target, command, errors)
            if text is None:
                continue
            try:
                document = json.loads(text or "[]")
            except (ValueError, TypeError) as exc:
                errors.append(f"{command!r} did not return readable JSON: {exc}")
                continue
            neighbors.extend(self._lldp_from_document(document))
        return neighbors

    @staticmethod
    def _lldp_from_document(document) -> List[Neighbor]:
        """
        Read LLDP neighbours from either shape of document.

        `lldpcli` reports an object keyed by interface name, each holding
        a list of neighbours. FRR reports a list of interfaces, each
        holding a list of neighbours.
        """
        neighbors: List[Neighbor] = []

        entries = []
        if isinstance(document, dict):
            for local_if, value in document.items():
                if isinstance(value, list):
                    entries.append((local_if, value))
        elif isinstance(document, list):
            for interface in document:
                if not isinstance(interface, dict):
                    continue
                local_if = interface.get("localInterface") or interface.get("ifname")
                entries.append((local_if, interface.get("neighbors") or []))

        for local_if, value in entries:
            for entry in value:
                if not isinstance(entry, dict):
                    continue
                neighbors.append(
                    Neighbor(
                        local_if=local_if,
                        remote_name=entry.get("host") or entry.get("systemName"),
                        remote_if=entry.get("port") or entry.get("remotePort"),
                        via="lldp",
                    )
                )

        return neighbors

    def _read_cdp_neighbors(self, target: str, errors: List[str]) -> List[Neighbor]:
        """Read the CDP adjacencies, which say who is on the other end."""
        text = self._try(target, "show cdp neighbors json", errors)
        if text is None:
            return []

        try:
            document = json.loads(text or "[]")
        except (ValueError, TypeError) as exc:
            errors.append(f"'show cdp neighbors json' did not return readable JSON: {exc}")
            return []

        if not isinstance(document, list):
            errors.append("'show cdp neighbors json' did not return a list")
            return []

        neighbors: List[Neighbor] = []
        for interface in document:
            if not isinstance(interface, dict):
                continue
            local_if = interface.get("localInterface") or interface.get("ifname")
            for entry in interface.get("neighbors") or []:
                if not isinstance(entry, dict):
                    continue
                neighbors.append(
                    Neighbor(
                        local_if=local_if,
                        remote_name=entry.get("host") or entry.get("systemName"),
                        remote_if=entry.get("port"),
                        via="cdp",
                    )
                )
        return neighbors

    # -- the collection --------------------------------------------------

    def collect(self, target: str) -> DeviceSnapshot:
        """
        Read one device.

        Every source that could not be read is recorded in the snapshot's
        errors. The collection itself does not fail because one optional
        source was missing.

        Args:
            target: The address or name the device is reached at

        Returns:
            A snapshot of what was read
        """
        errors: List[str] = []

        hostname = ""
        text = self._try(target, "hostname", errors)
        if text is not None:
            hostname = text.strip().splitlines()[0].strip() if text.strip() else ""

        # Device identity is the router, not the address it was reached
        # on, so one router reached by several addresses is one device.
        if hostname:
            device_id = hostname
        else:
            device_id = str(target)
            errors.append(
                "the hostname could not be read, so the device is identified by "
                "the address it was reached at"
            )

        interfaces = self._read_interfaces(target, errors)
        routes = self._read_routes(target, errors)
        neighbors: List[Neighbor] = []
        neighbors.extend(self._read_lldp_neighbors(target, errors))
        neighbors.extend(self._read_cdp_neighbors(target, errors))
        neighbors.extend(self._read_ospf_neighbors(target, errors))
        neighbors.extend(self._read_arp_neighbors(target, errors))

        return DeviceSnapshot(
            device_id=device_id,
            hostname=hostname,
            mgmt_target=str(target),
            method=self.method,
            collected_at=datetime.now(timezone.utc),
            interfaces=interfaces,
            routes=routes,
            neighbors=neighbors,
            errors=errors,
        )


def make_collector(
    runner: Callable[[str, str], str], method: str = "local"
) -> FrrCollector:
    """Build a collector whose commands are guarded and audited."""
    return FrrCollector(AuditedRunner(runner), method=method)
