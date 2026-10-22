"""
RouteLens Lite - Discovery engine.

Walks out from a set of seed devices, collecting what each one says
about itself, and following the routers it points at.

The rules this module enforces, because a discovery that wanders is a
discovery that reaches machines it was never asked about:

- The scope is checked before every collection and before every enqueue,
  not only at the seed. A run cannot widen itself.
- ARP neighbours are not followed. They are hosts on the same link, and
  following them would sweep every machine on the network.
- A device reached by a second address is not collected twice. The
  device decides, not the address.
- The run is bounded in depth and in the number of devices.
- A device that could not be collected is recorded and the run carries
  on. One unreachable router does not end the discovery.
"""

from __future__ import annotations

import ipaddress
from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Deque, Iterable, List, Optional, Sequence, Set, Union

from app.router_discovery.models import DeviceSnapshot


#: How deep the discovery may go by default.
DEFAULT_MAX_DEPTH = 4

#: How many devices it may collect by default.
DEFAULT_MAX_DEVICES = 50

#: A scope is one CIDR, or several.
Scope = Union[str, Sequence[str]]


@dataclass
class CollectionFailure:
    """A device that could not be collected."""

    target: str
    reason: str
    depth: int


@dataclass
class DiscoveryResult:
    """What a discovery run found."""

    devices: List[DeviceSnapshot] = field(default_factory=list)
    failures: List[CollectionFailure] = field(default_factory=list)


def _as_networks(scope: Scope) -> List[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    """
    Read a scope as a list of networks.

    A scope that cannot be read is the caller's mistake, and is raised
    as a ValueError the caller can turn into a 400. It is not a crash.
    """
    if isinstance(scope, str):
        raw: List[str] = [scope]
    else:
        raw = [str(item) for item in scope]

    networks = []
    for entry in raw:
        try:
            networks.append(ipaddress.ip_network(entry, strict=False))
        except ValueError as exc:
            raise ValueError(
                f"{entry!r} is not a valid network for the scope: {exc}"
            ) from exc
    return networks


def in_scope(ip: str, scope: Scope) -> bool:
    """
    Is an address inside the scope?

    Args:
        ip: The address to test
        scope: A CIDR, or a sequence of CIDRs

    Returns:
        True when the address is in one of the scope's networks

    Raises:
        ValueError: if the scope, or the address, cannot be read
    """
    networks = _as_networks(scope)
    try:
        address = ipaddress.ip_address(str(ip).strip())
    except ValueError as exc:
        raise ValueError(f"{ip!r} is not a valid IP address: {exc}") from exc
    return any(address in network for network in networks)


def _address_of(candidate: Optional[str]) -> Optional[str]:
    """Normalise an address, or None if it is not one."""
    if not candidate:
        return None
    text = str(candidate).strip()
    if not text:
        return None
    try:
        ipaddress.ip_address(text)
    except ValueError:
        return None
    return text


def _device_addresses(device: DeviceSnapshot) -> Set[str]:
    """Every address a device owns."""
    found: Set[str] = set()
    for interface in device.interfaces:
        for address in interface.addresses:
            text = str(address).split("/")[0].strip()
            if _address_of(text):
                found.add(text)
    return found


def discover(
    seeds: Iterable[str],
    collector,
    scope: Scope,
    max_depth: int = DEFAULT_MAX_DEPTH,
    max_devices: int = DEFAULT_MAX_DEVICES,
    progress: Callable[[str], None] = lambda message: None,
    local_addresses: Optional[Iterable[str]] = None,
) -> DiscoveryResult:
    """
    Collect a set of devices, breadth first, inside a scope.

    The candidates for the next hop are the addresses of the non-ARP
    neighbours a device reported and the next hops of its routes. An ARP
    neighbour is a host on the same link, so following it would sweep
    every machine on the network.

    Args:
        seeds: The addresses to start from
        collector: Something with a collect(target) method
        scope: A CIDR, or a sequence of CIDRs, the run may not leave
        max_depth: How many hops from a seed may be followed
        max_devices: How many devices may be collected
        progress: Called with a line for each collection and each failure
        local_addresses: Addresses of this machine, which are never
            collected

    Returns:
        The devices that were collected, and the ones that could not be

    Raises:
        ValueError: if the scope cannot be read
    """
    # Reading the scope up front means a bad scope is a caller error
    # before anything is collected.
    _as_networks(scope)

    result = DiscoveryResult()
    collected: List[DeviceSnapshot] = []
    seen_devices: Set[str] = set()
    seen_addresses: Set[str] = set()
    own_addresses: Set[str] = set()
    for address in local_addresses or ():
        normalised = _address_of(address)
        if normalised:
            own_addresses.add(normalised)

    # A queue of (address, depth). The depth is how far the address is
    # from a seed.
    queue: Deque[tuple[str, int]] = deque()
    for seed in seeds:
        normalised = _address_of(seed)
        if normalised:
            queue.append((normalised, 0))

    while queue:
        address, depth = queue.popleft()

        # The scope is checked before every collection, not only at the
        # seed.
        if not in_scope(address, scope):
            continue

        if depth > max_depth:
            continue

        if len(collected) >= max_devices:
            progress(
                f"stopped at the device limit of {max_devices}; {address} was not collected"
            )
            continue

        if address in seen_addresses or address in own_addresses:
            continue

        seen_addresses.add(address)

        try:
            device = collector.collect(address)
        except Exception as exc:
            reason = f"{type(exc).__name__}: {exc}"
            result.failures.append(
                CollectionFailure(target=address, reason=reason, depth=depth)
            )
            progress(f"could not collect {address}: {reason}")
            continue

        # One router reached by several addresses is one device, and the
        # device decides that, not the address.
        if device.device_id in seen_devices:
            progress(
                f"skipped {address}: it is {device.device_id}, which was already collected"
            )
            continue

        seen_devices.add(device.device_id)
        collected.append(device)
        result.devices.append(device)
        progress(
            f"collected {device.device_id} at {address} "
            f"({len(device.interfaces)} interface(s), {len(device.routes)} route(s))"
        )

        # The addresses this device owns are not candidates either.
        own_addresses.update(_device_addresses(device))

        if depth >= max_depth:
            continue

        for candidate in _candidates(device):
            if candidate in seen_addresses or candidate in own_addresses:
                continue
            # The scope is checked before every enqueue too.
            if not in_scope(candidate, scope):
                continue
            queue.append((candidate, depth + 1))

    return result


def _candidates(device: DeviceSnapshot) -> List[str]:
    """
    The addresses a device points at.

    These are the non-ARP neighbours it reported and the next hops of
    its routes. An ARP neighbour is a host on the same link and is not
    followed.
    """
    candidates: List[str] = []
    seen: Set[str] = set()

    for neighbor in device.neighbors:
        # An ARP entry is a host on this link, not a router to follow.
        if neighbor.via == "arp":
            continue
        address = _address_of(neighbor.remote_ip)
        if address and address not in seen:
            seen.add(address)
            candidates.append(address)

    for route in device.routes:
        address = _address_of(route.next_hop)
        if address and address not in seen:
            seen.add(address)
            candidates.append(address)

    return candidates
