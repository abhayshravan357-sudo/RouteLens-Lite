"""
RouteLens Lite - Findings from the collected network.

This module reads what the collectors actually saw and draws conclusions
from it. Three rules run through everything here.

**The router decides, not this module.** A router installs the best
route for each prefix into its forwarding table: for one prefix, the
route with the lowest administrative distance wins, and the metric
breaks a tie. It then looks a destination up by longest prefix over
those prefixes. This module builds that forwarding table and works from
it, so a decision reported here is the decision the device would make
for the routes that were collected.

**Nothing that was not read appears.** A route read from a device is
observed. A link between two devices is inferred unless the device
itself named the neighbour. A device that was not reached is a failure,
and it is reported as a failure rather than as a node with empty
fields.

**A finding that cannot be made is not made.** A topology the scenario
engine cannot represent is reported as not representable, rather than
being reshaped until it fits.
"""

from __future__ import annotations

import ipaddress
import re
from datetime import datetime, timezone
from typing import Dict, List, Optional, Sequence, Tuple

from pydantic import BaseModel, Field

from app.router_discovery.models import DeviceSnapshot, Edge, Neighbor, RouteEntry


#: The names the scenario engine will accept for a node or an
#: interface. Real interface names do not fit, so they are aliased.
SAFE_NAME_RE = re.compile(r"^[a-z][a-z0-9-]{0,15}$")

#: The most hops a next-hop chain may take before it is called a cycle.
MAX_CHAIN_HOPS = 16

#: An administrative distance that was not read. A route whose distance
#: is known is preferred over one whose distance is not, because we know
#: how the device would rank it.
UNKNOWN_ADMIN_DISTANCE = 1 << 30


class Finding(BaseModel):
    """
    One thing worth knowing about the collected network.

    Attributes:
        kind: What sort of finding this is
        severity: How much it matters
        devices: The devices the finding is about
        title: A one-line summary
        detail: The finding in words
        evidence: The observed facts the finding rests on
        provenance: How the finding was arrived at
        representable: False when the topology could not be represented
            and the finding rests on a partial view
    """

    kind: str
    severity: str = "warning"
    devices: List[str] = Field(default_factory=list)
    title: str = ""
    detail: str = ""
    evidence: List[str] = Field(default_factory=list)
    provenance: str = "inferred"
    representable: bool = True

#: What this analysis actually does, said plainly.
#:
#: The scenario engine reports its own provenance as "simulated", and it
#: resolves a next hop only through a point-to-point link. Every real
#: router-to-router link is routed, so over a collected network that
#: engine stops at the first hop and could never find a loop or an
#: asymmetry. This module therefore does not use it, and says here
#: exactly what it does instead.
METHOD_DESCRIPTION = (
    "Each device's forwarding table was rebuilt from the routes that were "
    "collected: one route per prefix, chosen by administrative distance and "
    "then metric, and looked up by longest prefix. That is the order a "
    "router itself uses, so a path reported here is the decision the device "
    "would make for the routes that were collected. It is not a measurement "
    "of traffic, and the device's own forwarding table may hold routes that "
    "were not collected, so its decision for the same destination may differ."
)



class AnalysisReport(BaseModel):
    """
    What the collected network turned out to be like.

    Attributes:
        generated_at: When the analysis ran
        devices_analysed: How many devices were read
        findings: Everything worth knowing
        unreached: The devices that could not be collected, and why
        interface_aliases: The safe name used for each interface, and
            the real name it stands for
        method: What was actually done, in words, so that a reader is
            never left guessing how a path was worked out
        limitations: What this analysis cannot say
        provenance: How the report was arrived at
    """

    generated_at: datetime
    devices_analysed: int
    findings: List[Finding] = Field(default_factory=list)
    unreached: List[dict] = Field(default_factory=list)
    interface_aliases: Dict[str, Dict[str, str]] = Field(default_factory=dict)
    method: str = METHOD_DESCRIPTION
    limitations: List[str] = Field(default_factory=list)
    provenance: str = "inferred"




# ---------------------------------------------------------------------------
# Choosing a route the way a router does
# ---------------------------------------------------------------------------

def _network(route: RouteEntry) -> Optional[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    """The route's network, or None if it cannot be read."""
    try:
        return ipaddress.ip_network(route.prefix, strict=False)
    except ValueError:
        return None


def select_route(
    routes: Sequence[RouteEntry], destination: str
) -> Optional[RouteEntry]:
    """
    Choose the route a router would use for a destination.

    A router's forwarding table holds one route per prefix: the one with
    the lowest administrative distance, and the lowest metric when the
    distances are equal. It then looks the destination up by longest
    prefix over those prefixes.

    Doing it in that order matters. Ranking by metric first would let a
    route with a high administrative distance beat the one the device
    would actually install, and the answer would not be the device's.

    Args:
        routes: The routes to choose from
        destination: The address being looked up

    Returns:
        The route that would be used, or None if none reaches it
    """
    try:
        address = ipaddress.ip_address(str(destination).strip())
    except ValueError:
        return None

    candidates = []
    for route in routes:
        network = _network(route)
        if network is None:
            continue
        if network.version != address.version:
            continue
        if address in network:
            candidates.append((route, network))

    if not candidates:
        return None

    longest = max(network.prefixlen for _route, network in candidates)
    finalists = [
        (route, network)
        for route, network in candidates
        if network.prefixlen == longest
    ]

    def rank(item):
        route, _network = item
        distance = (
            route.admin_distance
            if route.admin_distance is not None
            else UNKNOWN_ADMIN_DISTANCE
        )
        metric = route.metric if route.metric is not None else 0
        # The last two are the same deterministic tie break the routing
        # engine uses, so an equal table always gives the same answer.
        return (distance, metric, route.interface or "", str(route.next_hop or ""))

    return min(finalists, key=rank)[0]


def build_fib(routes: Sequence[RouteEntry]) -> List[RouteEntry]:
    """
    The forwarding table a router would hold for these routes.

    One route per prefix: the best one. This is what a device installs,
    and it is what a longest-prefix lookup over it answers with.
    """
    best: Dict[str, RouteEntry] = {}

    for route in routes:
        network = _network(route)
        if network is None:
            continue
        key = str(network)
        current = best.get(key)
        if current is None:
            best[key] = route
            continue

        def rank(candidate: RouteEntry):
            distance = (
                candidate.admin_distance
                if candidate.admin_distance is not None
                else UNKNOWN_ADMIN_DISTANCE
            )
            metric = candidate.metric if candidate.metric is not None else 0
            return (distance, metric, candidate.interface or "", str(candidate.next_hop or ""))

        if rank(route) < rank(current):
            best[key] = route

    return list(best.values())


# ---------------------------------------------------------------------------
# Names
# ---------------------------------------------------------------------------

def alias_for(name: str, taken: set[str]) -> str:
    """
    A short name the scenario engine will accept.

    Real interface names are things like Gi0/0/1, eth0.100 and
    eth0@if3, and none of them fit the scenario engine's naming rules.
    Each one gets an alias, and the real name is carried alongside it, so
    an alias is never shown as though it were the device's own name.
    """
    base = re.sub(r"[^a-z0-9-]+", "-", str(name).lower()).strip("-")
    if not base:
        base = "n"
    if not base[0].isalpha():
        base = f"n{base}"
    base = base[:16]

    candidate = base
    counter = 1
    while candidate in taken:
        suffix = f"-{counter}"
        candidate = f"{base[: 16 - len(suffix)]}{suffix}"
        counter += 1

    taken.add(candidate)
    return candidate


# ---------------------------------------------------------------------------
# The analysis
# ---------------------------------------------------------------------------

def _owner_index(devices: Sequence[DeviceSnapshot]) -> Dict[str, DeviceSnapshot]:
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


def _arp_addresses(device: DeviceSnapshot) -> set[str]:
    """The addresses this device has in its ARP table."""
    return {
        str(neighbor.remote_ip)
        for neighbor in device.neighbors
        if neighbor.via == "arp" and neighbor.remote_ip
    }


def _forwards(device: DeviceSnapshot, version: int) -> bool:
    """Does the device forward in this address family?"""
    for route in device.routes:
        network = _network(route)
        if network is None or network.version != version:
            continue
        if route.next_hop:
            return True
    return False


def _has_default(device: DeviceSnapshot, version: int) -> bool:
    """Does the device have a default route in this address family?"""
    for route in device.routes:
        network = _network(route)
        if network is None or network.version != version:
            continue
        if network.prefixlen == 0:
            return True
    return False


def _next_hop_chain(
    fib_by_device: Dict[str, List[RouteEntry]],
    owner_by_address: Dict[str, DeviceSnapshot],
    start: DeviceSnapshot,
    target_address: str,
    target_device_id: Optional[str] = None,
) -> Tuple[List[str], bool]:
    """
    Follow the next hops from a device towards an address.

    The walk stops when it reaches `target_device_id`, if one is given:
    arriving at the device is the end of the path, not a step further
    along it.

    Returns the devices the path passes through, and whether the path
    came back to somewhere it had already been.
    """
    chain: List[str] = [start.device_id]
    seen = {start.device_id}
    current = start

    for _ in range(MAX_CHAIN_HOPS):
        fib = fib_by_device.get(current.device_id, [])
        route = select_route(fib, target_address)
        if route is None or not route.next_hop:
            return chain, False
        next_device = owner_by_address.get(str(route.next_hop))
        if next_device is None:
            return chain, False
        if target_device_id is not None and next_device.device_id == target_device_id:
            return chain + [next_device.device_id], False
        if next_device.device_id in seen:
            return chain + [next_device.device_id], True
        seen.add(next_device.device_id)
        chain.append(next_device.device_id)
        current = next_device

    return chain, True


def _first_address_of(device: DeviceSnapshot) -> str:
    """One address of a device, for looking the device up by."""
    addresses = _device_addresses(device)
    return addresses[0] if addresses else device.device_id


def analyse(
    devices: Sequence[DeviceSnapshot],
    unreached: Optional[Sequence[dict]] = None,
    edges: Optional[Sequence[Edge]] = None,
) -> AnalysisReport:
    """
    Draw the findings from what was collected.

    Args:
        devices: The devices that were read
        unreached: The devices that could not be read, and why
        edges: The edges between the devices, if they have been built

    Returns:
        The report
    """
    owner_by_address = _owner_index(devices)
    fib_by_device = {
        device.device_id: build_fib(device.routes) for device in devices
    }

    findings: List[Finding] = []

    # -- blackhole --------------------------------------------------------
    # A next hop that no known device owns, and that is not in the
    # device's own ARP table, is nowhere to send the packet.
    for device in devices:
        arp = _arp_addresses(device)
        for route in device.routes:
            next_hop = str(route.next_hop or "").strip()
            if not next_hop:
                continue
            if next_hop in owner_by_address:
                continue
            if next_hop in arp:
                continue
            findings.append(
                Finding(
                    kind="blackhole",
                    severity="critical",
                    devices=[device.device_id],
                    title=f"{device.device_id} sends traffic to a next hop nothing owns",
                    detail=(
                        f"{device.device_id} routes {route.prefix} to {next_hop} on "
                        f"{route.interface or 'an unknown interface'}, but no collected device "
                        f"holds that address and it is not in {device.device_id}'s ARP table. "
                        f"The traffic has nowhere to go."
                    ),
                    evidence=[
                        f"route {route.prefix} via {next_hop} on {route.interface}",
                        f"{next_hop} is not an address of any collected device",
                        f"{next_hop} is not in {device.device_id}'s ARP table",
                    ],
                    provenance="inferred",
                )
            )

    # -- missing default --------------------------------------------------
    for device in devices:
        for version in (4, 6):
            if not _forwards(device, version):
                continue
            if _has_default(device, version):
                continue
            family = "IPv4" if version == 4 else "IPv6"
            findings.append(
                Finding(
                    kind="missing_default",
                    severity="warning",
                    devices=[device.device_id],
                    title=f"{device.device_id} forwards {family} traffic but has no default route",
                    detail=(
                        f"{device.device_id} forwards {family} traffic, so it has somewhere to "
                        f"send traffic that does not match a more specific route, but its "
                        f"collected table has no default route for {family}."
                    ),
                    evidence=[
                        f"{device.device_id} has {family} routes with a next hop",
                        f"{device.device_id} has no {'0.0.0.0/0' if version == 4 else '::/0'} route",
                    ],
                    provenance="inferred",
                )
            )

    # -- down next hop ----------------------------------------------------
    for device in devices:
        down = {
            interface.name for interface in device.interfaces if not interface.up
        }
        for route in device.routes:
            if not route.interface or route.interface not in down:
                continue
            findings.append(
                Finding(
                    kind="down_next_hop",
                    severity="critical",
                    devices=[device.device_id],
                    title=f"{device.device_id} routes {route.prefix} out of an interface that is down",
                    detail=(
                        f"{device.device_id} routes {route.prefix} via {route.next_hop or 'a gateway'} "
                        f"on {route.interface}, but {route.interface} is not up. The traffic cannot "
                        f"leave."
                    ),
                    evidence=[
                        f"route {route.prefix} via {route.next_hop} on {route.interface}",
                        f"{route.interface} was read as not up",
                    ],
                    provenance="observed",
                )
            )

    # -- overlap ----------------------------------------------------------
    # Two routes for one prefix, to different next hops, with the same
    # administrative distance. The device will pick one of them, and the
    # other is a conflict.
    for device in devices:
        by_prefix: Dict[str, List[RouteEntry]] = {}
        for route in device.routes:
            network = _network(route)
            if network is None:
                continue
            by_prefix.setdefault(str(network), []).append(route)

        for prefix, routes in by_prefix.items():
            for index, left in enumerate(routes):
                for right in routes[index + 1:]:
                    if not left.next_hop or not right.next_hop:
                        continue
                    if left.next_hop == right.next_hop:
                        continue
                    if left.admin_distance != right.admin_distance:
                        continue
                    findings.append(
                        Finding(
                            kind="overlap",
                            severity="warning",
                            devices=[device.device_id],
                            title=f"{device.device_id} has two conflicting routes for {prefix}",
                            detail=(
                                f"{device.device_id} has two routes for {prefix}, one via "
                                f"{left.next_hop} on {left.interface} and one via {right.next_hop} "
                                f"on {right.interface}. Both have administrative distance "
                                f"{left.admin_distance}, so the metric decides between them and "
                                f"the two routes disagree about where the traffic should go."
                            ),
                            evidence=[
                                f"{prefix} via {left.next_hop} on {left.interface}",
                                f"{prefix} via {right.next_hop} on {right.interface}",
                                f"both have administrative distance {left.admin_distance}",
                            ],
                            provenance="inferred",
                        )
                    )

    # -- loop -------------------------------------------------------------
    # A forwarding cycle among the collected tables.
    for device in devices:
        for route in build_fib(device.routes):
            if not route.next_hop:
                continue
            network = _network(route)
            if network is None:
                continue
            # The walk needs an address to look up, not a prefix.
            target = str(network.network_address)
            chain, looped = _next_hop_chain(
                fib_by_device, owner_by_address, device, target
            )
            if not looped or len(chain) < 2:
                continue
            # The same cycle is reached from every device in it, so it is
            # reported once, by the first of them.
            cycle = list(dict.fromkeys(chain))
            if device.device_id != min(cycle):
                continue
            findings.append(
                Finding(
                    kind="loop",
                    severity="critical",
                    devices=cycle,
                    title=f"a forwarding cycle reaches {route.prefix}",
                    detail=(
                        f"The collected forwarding tables send traffic for {route.prefix} round a "
                        f"cycle: {' -> '.join(chain)}. The packet would circulate instead of "
                        f"reaching its destination. This is the decision over the routes that "
                        f"were collected; the device's own table may hold routes that were not."
                    ),
                    evidence=[f"{route.prefix} via {route.next_hop} on {route.interface}"]
                    + [f"{device_id} forwards it onward" for device_id in chain[1:]],
                    provenance="inferred",
                )
            )

    # -- asymmetric path --------------------------------------------------
    # The path one way is not the reverse of the path back.
    for device in devices:
        for other in devices:
            if other.device_id == device.device_id:
                continue
            for address in _device_addresses(other):
                forward, _ = _next_hop_chain(
                    fib_by_device, owner_by_address, device, address,
                    target_device_id=other.device_id,
                )
                backward, _ = _next_hop_chain(
                    fib_by_device, owner_by_address, other,
                    _first_address_of(device),
                    target_device_id=device.device_id,
                )
                if not forward or not backward:
                    continue
                if forward == list(reversed(backward)):
                    continue
                if len(forward) < 2 or len(backward) < 2:
                    continue
                findings.append(
                    Finding(
                        kind="asymmetric_path",
                        severity="info",
                        devices=[device.device_id, other.device_id],
                        title=(
                            f"the path from {device.device_id} to {other.device_id} is not the "
                            f"reverse of the path back"
                        ),
                        detail=(
                            f"Traffic from {device.device_id} to {other.device_id} goes "
                            f"{' -> '.join(forward)}, while traffic back goes "
                            f"{' -> '.join(backward)}. The two paths are not reverses of one "
                            f"another. This is the decision over the routes that were collected; "
                            f"the devices' own tables may hold routes that were not."
                        ),
                        evidence=[
                            f"{device.device_id} to {other.device_id}: {' -> '.join(forward)}",
                            f"{other.device_id} to {device.device_id}: {' -> '.join(backward)}",
                        ],
                        provenance="inferred",
                    )
                )
                break

    scenario, notes, aliases = build_scenario(devices, edges)

    return AnalysisReport(
        generated_at=datetime.now(timezone.utc),
        devices_analysed=len(devices),
        findings=findings,
        unreached=[dict(entry) for entry in (unreached or [])],
        interface_aliases=aliases,
        limitations=[
            "The findings are drawn from the routes that were collected. A route that was "
            "not read is not a route that does not exist.",
            "A device that could not be collected is listed under unreached, not treated as "
            "a device with no routes.",
            "The forwarding tables are built from the collected routes the way a device "
            "builds its own: one route per prefix, chosen by administrative distance and "
            "then metric, and looked up by longest prefix.",
            "An administrative distance that was not read is treated as unknown, so a route "
            "whose distance is known is preferred.",
            "The scenario engine's point-to-point link model cannot follow a routed link, "
            "so the paths here are worked out from the collected forwarding tables rather "
            "than traced through that engine.",
        ]
        + [f"not representable in the scenario engine: {note}" for note in notes],
    )


def _device_addresses(device: DeviceSnapshot) -> List[str]:
    """The addresses a device owns."""
    found: List[str] = []
    for interface in device.interfaces:
        for address in interface.addresses:
            text = str(address).split("/")[0].strip()
            try:
                ipaddress.ip_address(text)
            except ValueError:
                continue
            found.append(text)
    return found


def _first_address(device: DeviceSnapshot) -> str:
    """One address of a device, for looking the device up by."""
    addresses = _device_addresses(device)
    return addresses[0] if addresses else device.device_id


# ---------------------------------------------------------------------------
# The scenario engine
# ---------------------------------------------------------------------------

def build_scenario(
    devices: Sequence[DeviceSnapshot],
    edges: Optional[Sequence[Edge]] = None,
) -> Tuple[Optional[object], List[str], Dict[str, Dict[str, str]]]:
    """
    Build a scenario for the part of the collected topology that fits.

    The scenario engine models a network as point-to-point links between
    interfaces, and it checks that both ends of a link are on the same
    subnet. Real router-to-router links are routed, so they do not fit,
    and reshaping them until they do would be inventing a network.

    So only the links that are representable are built, and the rest are
    reported as not representable. Every name the engine cannot accept
    is given an alias, and the real name is carried alongside so an alias
    is never shown as though it were the device's own.

    Returns:
        The scenario, or None if none could be built; the notes about
        what could not be represented; and the alias map
    """
    from app.scenario import Iface, Link, Node, Route, Scenario

    notes: List[str] = []
    aliases: Dict[str, Dict[str, str]] = {}

    node_names: set[str] = set()
    node_alias: Dict[str, str] = {}
    for device in devices:
        node_alias[device.device_id] = alias_for(device.device_id, node_names)

    iface_alias: Dict[Tuple[str, str], str] = {}
    for device in devices:
        taken: set[str] = set()
        mapping: Dict[str, str] = {}
        for interface in device.interfaces:
            alias = alias_for(interface.name, taken)
            iface_alias[(device.device_id, interface.name)] = alias
            mapping[alias] = interface.name
        aliases[node_alias[device.device_id]] = mapping

    nodes: List[Node] = []
    node_networks: Dict[str, Dict[str, object]] = {}

    for device in devices:
        ifaces: List[Iface] = []
        networks: Dict[str, object] = {}
        for interface in device.interfaces:
            alias = iface_alias[(device.device_id, interface.name)]
            for address in interface.addresses:
                try:
                    cidr = str(ipaddress.ip_interface(str(address).strip()))
                except ValueError:
                    continue
                try:
                    ifaces.append(Iface(name=alias, cidr=cidr))
                except ValueError:
                    notes.append(
                        f"{device.device_id} interface {interface.name} holds {address}, which "
                        f"is not an address the scenario engine can use"
                    )
                    continue
                networks[alias] = ipaddress.ip_interface(cidr).network

        node_networks[node_alias[device.device_id]] = networks
        nodes.append(
            Node(id=node_alias[device.device_id], kind="router", ifaces=ifaces, routes=[])
        )

    # The routes are the forwarding table: one route per prefix, the one
    # the device would have installed.
    for device in devices:
        node = next(n for n in nodes if n.id == node_alias[device.device_id])
        connected = {str(net) for net in node_networks[node.id].values()}

        for route in build_fib(device.routes):
            network = _network(route)
            if network is None:
                continue
            prefix = str(network)
            if prefix in connected:
                # The engine adds a connected route for each interface.
                continue
            if not route.interface:
                notes.append(
                    f"{device.device_id} has a route for {prefix} with no egress interface, "
                    f"which the scenario engine cannot represent"
                )
                continue
            alias = iface_alias.get((device.device_id, route.interface))
            if alias is None:
                notes.append(
                    f"{device.device_id} routes {prefix} out of {route.interface}, which was not "
                    f"collected, so the route cannot be represented"
                )
                continue
            try:
                node.routes.append(
                    Route(
                        prefix=prefix,
                        dev=alias,
                        via=route.next_hop,
                        metric=max(0, route.metric or 0),
                        # The scenario engine's Route.source has only two
                        # values. The protocol is carried by the findings
                        # in this module, so nothing is lost from what is
                        # reported, but the scenario itself calls every
                        # collected route static.
                        source="static",
                    )
                )
            except ValueError as exc:
                notes.append(
                    f"{device.device_id} route {prefix} could not be represented: {exc}"
                )

    # The links are the observed adjacencies, and only the ones whose
    # two ends share a subnet.
    links: List[Link] = []
    if edges:
        for edge in edges:
            if edge.provenance != "observed":
                continue
            if edge.kind not in ("lldp", "cdp"):
                continue
            source = next((d for d in devices if d.device_id == edge.a), None)
            target = next((d for d in devices if d.device_id == edge.b), None)
            if source is None or target is None:
                continue

            local_if = None
            for neighbor in source.neighbors:
                if neighbor.via != edge.kind:
                    continue
                if neighbor.remote_name not in (target.device_id, target.hostname):
                    continue
                local_if = neighbor.local_if
                break
            if not local_if:
                notes.append(
                    f"the {edge.kind} adjacency between {edge.a} and {edge.b} names no local "
                    f"interface on {edge.a}, so the link cannot be represented"
                )
                continue

            source_alias = iface_alias.get((source.device_id, local_if))
            if source_alias is None:
                notes.append(
                    f"the {edge.kind} adjacency between {edge.a} and {edge.b} uses "
                    f"{local_if} on {edge.a}, which was not collected"
                )
                continue

            target_alias = None
            for neighbor in target.neighbors:
                if neighbor.via != edge.kind:
                    continue
                if neighbor.remote_name not in (source.device_id, source.hostname):
                    continue
                for interface in target.interfaces:
                    for address in interface.addresses:
                        if str(address).split("/")[0] == str(neighbor.remote_ip or ""):
                            target_alias = iface_alias.get((target.device_id, interface.name))
                            break
                break
            if target_alias is None:
                notes.append(
                    f"the {edge.kind} adjacency between {edge.a} and {edge.b} names no interface "
                    f"on {edge.b} that holds {edge.b}'s address to {edge.b}"
                )
                continue

            source_net = node_networks[node_alias[source.device_id]].get(source_alias)
            target_net = node_networks[node_alias[target.device_id]].get(target_alias)
            if source_net is None or target_net is None:
                continue
            if source_net != target_net:
                # The engine checks that both ends share a subnet. A
                # routed link does not, and it is reported rather than
                # reshaped to fit.
                notes.append(
                    f"the {edge.kind} adjacency between {edge.a} and {edge.b} is a routed link "
                    f"({source_net} and {target_net}), which the scenario engine cannot represent"
                )
                continue

            links.append(
                Link(
                    a=f"{node_alias[source.device_id]}:{source_alias}",
                    b=f"{node_alias[target.device_id]}:{target_alias}",
                )
            )

    if not nodes:
        return None, notes, aliases

    try:
        scenario = Scenario(
            id="collected",
            title="The network that was collected",
            nodes=nodes,
            links=links,
        )
    except ValueError as exc:
        notes.append(f"the collected topology could not be built as a scenario: {exc}")
        return None, notes, aliases

    return scenario, notes, aliases
