"""
RouteLens Lite - Discovery graph.

Turns a set of device snapshots into the edges between them, and says
how each edge is known.

Two kinds of edge, and the difference matters:

- OBSERVED: the devices said so themselves, over LLDP or CDP. The
  device on the other end of that link named its neighbour.
- INFERRED: we worked it out from routing or addressing. A next hop
  that belongs to a device might cross a switch, and two devices on the
  same subnet might not be on the same link at all. Neither is an
  observation, and both are marked as inferences.
"""

from __future__ import annotations

import ipaddress
from typing import Dict, List, Optional, Set, Tuple

from app.router_discovery.models import DeviceSnapshot, Edge


def _address_index(devices: List[DeviceSnapshot]) -> Dict[str, DeviceSnapshot]:
    """Every address a device owns, mapped to the device."""
    index: Dict[str, DeviceSnapshot] = {}
    for device in devices:
        for interface in device.interfaces:
            for address in interface.addresses:
                text = str(address).split("/")[0].strip()
                try:
                    ipaddress.ip_address(text)
                except ValueError:
                    continue
                index.setdefault(text, device)
    return index


def _name_index(devices: List[DeviceSnapshot]) -> Dict[str, DeviceSnapshot]:
    """Every name a device answers to, mapped to the device."""
    index: Dict[str, DeviceSnapshot] = {}
    for device in devices:
        for name in (device.device_id, device.hostname):
            if name:
                index.setdefault(str(name), device)
    return index


def _shared_networks(device: DeviceSnapshot) -> List[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    """
    The networks a device is attached to.

    A /32, a loopback or a link-local address says nothing about which
    link a device is on, so it is not used to infer one.
    """
    networks = []
    for interface in device.interfaces:
        for address in interface.addresses:
            text = str(address).strip()
            if "/" not in text:
                continue
            try:
                interface_addr = ipaddress.ip_interface(text)
            except ValueError:
                continue
            network = interface_addr.network
            if network.prefixlen >= 32:
                continue
            if interface_addr.ip.is_loopback:
                continue
            if interface_addr.ip.is_link_local:
                continue
            networks.append(network)
    return networks


def build_edges(devices: List[DeviceSnapshot]) -> List[Edge]:
    """
    Build the edges between a set of devices.

    Args:
        devices: The snapshots that were collected

    Returns:
        The edges, each saying how it is known
    """
    by_address = _address_index(devices)
    by_name = _name_index(devices)
    by_id = {device.device_id: device for device in devices}

    edges: List[Edge] = []
    seen: Set[Tuple[str, str, str]] = set()

    def add(a: str, b: str, kind: str, provenance: str, evidence: str) -> None:
        # A device is not linked to itself.
        if not a or not b or a == b:
            return
        # The same pair may have more than one kind of edge. They are
        # different facts, and one does not replace the other.
        key = (a, b, kind)
        if key in seen:
            return
        seen.add(key)
        edges.append(Edge(a=a, b=b, kind=kind, provenance=provenance, evidence=evidence))

    # 1. LLDP and CDP adjacencies. The devices said so themselves.
    for device in devices:
        for neighbor in device.neighbors:
            if neighbor.via not in ("lldp", "cdp"):
                continue
            remote = by_name.get(str(neighbor.remote_name or ""))
            if remote is None or remote.device_id == device.device_id:
                continue
            local_if = neighbor.local_if or "an unknown interface"
            add(
                device.device_id,
                remote.device_id,
                neighbor.via,
                "observed",
                f"{device.device_id} reported {remote.device_id} as a "
                f"{neighbor.via.upper()} neighbour on {local_if}",
            )

    # 2. A route's next hop that belongs to a known device. The next hop
    #    might cross a switch, so this is an inference.
    for device in devices:
        for route in device.routes:
            next_hop = str(route.next_hop or "").strip()
            if not next_hop:
                continue
            remote = by_address.get(next_hop)
            if remote is None or remote.device_id == device.device_id:
                continue
            interface = route.interface or "an unknown interface"
            add(
                device.device_id,
                remote.device_id,
                "l3_next_hop",
                "inferred",
                f"{device.device_id} routes {route.prefix} to {next_hop} on "
                f"{interface}, and {next_hop} is an address of {remote.device_id}",
            )

    # 3. Two devices attached to the same network. They may be on the
    #    same link, or separated by a switch, so this is an inference.
    networks_by_device: Dict[str, List] = {
        device.device_id: _shared_networks(device) for device in devices
    }
    for device in devices:
        for other in devices:
            if other.device_id <= device.device_id:
                continue
            shared = []
            for network in networks_by_device[device.device_id]:
                for other_network in networks_by_device[other.device_id]:
                    if network != other_network:
                        continue
                    if network.version != other_network.version:
                        continue
                    if network not in shared:
                        shared.append(network)
            for network in shared:
                add(
                    device.device_id,
                    other.device_id,
                    "shared_subnet",
                    "inferred",
                    f"{device.device_id} and {other.device_id} both hold an address "
                    f"on {network}",
                )

    return edges


def neighbours_of(device_id: str, edges: List[Edge]) -> List[str]:
    """The devices an edge set links to one device."""
    found: List[str] = []
    for edge in edges:
        if edge.a == device_id and edge.b not in found:
            found.append(edge.b)
        elif edge.b == device_id and edge.a not in found:
            found.append(edge.a)
    return found
