"""
RouteLens Lite - Evidence-Based Topology

Builds a topology graph from two kinds of evidence:

- The scenario definition, whose links are SIMULATED: they describe a
  network the user is exploring, not a measured one.
- The real host, whose interfaces, routes and neighbours are OBSERVED:
  they were read from this machine with `ip`.

Links between observed nodes are INFERRED: a route pointing at a gateway
tells us a next hop exists, and a neighbour entry tells us a device
answered on that link, but neither is a physical cable.

Nodes and edges that cannot be explained are UNKNOWN, and are left
unresolved rather than guessed at.
"""

from __future__ import annotations

import ipaddress
from enum import Enum
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from app.network_collector import get_network_collector
from app.scenario import Scenario


class Provenance(str, Enum):
    """Where a piece of topology information came from."""

    OBSERVED = "observed"
    INFERRED = "inferred"
    SIMULATED = "simulated"
    UNKNOWN = "unknown"


class TopologyNode(BaseModel):
    """A device or interface in the topology."""

    id: str
    kind: Literal["host", "router", "interface", "gateway", "neighbor", "unknown"]
    label: str
    provenance: Provenance
    addresses: List[str] = Field(default_factory=list)
    detail: Optional[str] = None


class TopologyEdge(BaseModel):
    """A relationship between two topology nodes."""

    source: str
    target: str
    kind: str
    provenance: Provenance
    label: str
    detail: Optional[str] = None


class TopologyGraph(BaseModel):
    """The assembled topology."""

    nodes: List[TopologyNode]
    edges: List[TopologyEdge]
    provenance: Provenance
    explanation: str
    observed_at: str


async def build_topology(scenario: Optional[Scenario]) -> TopologyGraph:
    """
    Assemble a topology from the scenario and from the real host.

    The scenario contributes simulated devices and links. The host
    contributes observed interfaces, inferred routes and observed
    neighbours. The two sets are never merged into a single claim about
    the same thing.
    """
    from datetime import datetime, timezone

    collector = get_network_collector()
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    nodes: List[TopologyNode] = []
    edges: List[TopologyEdge] = []
    seen_ids: set[str] = set()

    def add_node(node: TopologyNode) -> None:
        if node.id in seen_ids:
            return
        seen_ids.add(node.id)
        nodes.append(node)

    # --- Observed: the real host's interfaces -----------------------------
    host_data_found = False
    interfaces_result = await collector.collect_interfaces()
    if interfaces_result.success and interfaces_result.data:
        for iface in interfaces_result.data:
            addresses = list(iface.ipv4_addresses) + list(iface.ipv6_addresses)
            host_data_found = True
            add_node(
                TopologyNode(
                    id=f"iface:{iface.name}",
                    kind="interface",
                    label=iface.name,
                    provenance=Provenance.OBSERVED,
                    addresses=addresses,
                    detail=f"state {iface.state}, mtu {iface.mtu}",
                )
            )

    # --- Observed: the real host's neighbours -----------------------------
    # Both families are read. The IPv6 neighbour table is usually empty, and
    # saying so is better than pretending the host has no IPv6 neighbours.
    for family in ("ipv4", "ipv6"):
        neighbors_result = await collector.collect_neighbors(ip_version=family)
        if neighbors_result.success and neighbors_result.data:
            for neighbor in neighbors_result.data:
                node_id = f"neighbor:{neighbor.ip_address}"
                host_data_found = True
                add_node(
                    TopologyNode(
                        id=node_id,
                        kind="neighbor",
                        label=neighbor.ip_address,
                        provenance=Provenance.OBSERVED,
                        addresses=[neighbor.ip_address],
                        detail=(
                            f"{neighbor.state} on {neighbor.interface}"
                            + (f", mac {neighbor.mac_address}" if neighbor.mac_address else "")
                            + (" (router)" if neighbor.is_router else "")
                        ),
                    )
                )
                # A neighbour entry is a device answering on the link: the link
                # itself is inferred, the neighbour record is observed.
                edges.append(
                    TopologyEdge(
                        source=f"iface:{neighbor.interface}",
                        target=node_id,
                        kind="neighbor",
                        provenance=Provenance.INFERRED,
                        label="answers on",
                        detail="The neighbour cache says a device answered here; the link itself was not measured.",
                    )
                )

    # --- Observed: the real host's routes ---------------------------------
    for family in ("ipv4", "ipv6"):
        routes_result = await collector.collect_routes(ip_version=family)
        if not (routes_result.success and routes_result.data):
            continue
        for route in routes_result.data:
            if not route.gateway:
                continue
            gateway_id = f"gateway:{route.gateway}"
            host_data_found = True
            add_node(
                TopologyNode(
                    id=gateway_id,
                    kind="gateway",
                    label=route.gateway,
                    provenance=Provenance.OBSERVED,
                    addresses=[route.gateway],
                    detail=f"next hop for {route.destination}",
                )
            )
            # The route is observed; the hop to the gateway is inferred.
            edges.append(
                TopologyEdge(
                    source=f"iface:{route.interface}" if route.interface else "iface:unknown",
                    target=gateway_id,
                    kind="route",
                    provenance=Provenance.INFERRED,
                    label="next hop",
                    detail=(
                        f"Route {route.destination} via {route.gateway} "
                        f"(metric {route.metric}); the route is observed, "
                        "the link to the gateway is not."
                    ),
                )
            )

    # --- Simulated: the scenario -----------------------------------------
    if scenario is not None:
        for node in scenario.nodes:
            add_node(
                TopologyNode(
                    id=f"sim:{node.id}",
                    kind=node.kind,
                    label=node.id,
                    provenance=Provenance.SIMULATED,
                    addresses=[iface.cidr for iface in node.ifaces],
                    detail=f"{len(node.ifaces)} interface(s), {len(node.routes)} route(s)",
                )
            )

        for link in scenario.links:
            edges.append(
                TopologyEdge(
                    source=f"sim:{link.a.split(':')[0]}",
                    target=f"sim:{link.b.split(':')[0]}",
                    kind="link",
                    provenance=Provenance.SIMULATED,
                    label="link",
                    detail=f"{link.a} <-> {link.b}",
                )
            )

    if host_data_found:
        explanation = (
            f"{len(nodes)} node(s) and {len(edges)} relationship(s). "
            "Interfaces, routes and neighbours came from this machine and are "
            "observed or inferred; the scenario devices and links are simulated."
        )
        provenance = Provenance.OBSERVED
    else:
        explanation = (
            "No host data could be collected, so only the simulated scenario is "
            "shown. Nothing here was measured."
        )
        provenance = Provenance.SIMULATED

    return TopologyGraph(
        nodes=nodes,
        edges=edges,
        provenance=provenance,
        explanation=explanation,
        observed_at=now,
    )
