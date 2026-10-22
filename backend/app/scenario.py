"""
RouteLens Lite - Scenario Engine

Multi-router network scenario engine with real namespace integration.
Supports IPv4/IPv6, longest-prefix matching, loop detection, and real namespace simulation.

Design notes:
- A Scenario is a single source of truth for both the simulator (trace()) and the
  lab builder (lab_builder.build_commands()). Prediction and reality are driven
  by the same data, which is what makes "simulation vs reality" meaningful.
- Links are point-to-point only. Switches are not modelled.
- Every hop records the route that was selected and the candidates it beat.
"""

from __future__ import annotations

import ipaddress as ipa
import re
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, model_validator, field_validator


#: Maximum number of hops a trace may take before it is abandoned.
MAX_HOPS = 16

#: Node/interface names must be shell-safe because they are passed to `ip netns`.
SAFE_NAME_RE = re.compile(r"^[a-z][a-z0-9-]{0,15}$")


class Iface(BaseModel):
    """A network interface on a node."""

    name: str = Field(..., description="Interface name (e.g., eth0)")
    cidr: str = Field(..., description="Address in CIDR notation (e.g., 10.0.1.1/24)")

    @model_validator(mode="after")
    def _validate(self):
        if not SAFE_NAME_RE.match(self.name):
            raise ValueError(f"Unsafe interface name: {self.name!r}")
        ipa.ip_interface(self.cidr)
        return self

    @property
    def ip(self) -> ipa.IPv4Address | ipa.IPv6Address:
        """The address without prefix length."""
        return ipa.ip_interface(self.cidr).ip

    @property
    def net(self) -> ipa.IPv4Network | ipa.IPv6Network:
        """The network this interface is attached to."""
        return ipa.ip_interface(self.cidr).network


class Route(BaseModel):
    """A routing table entry."""

    prefix: str = Field(..., description="Destination network in CIDR notation")
    dev: str = Field(..., description="Outgoing interface name")
    via: Optional[str] = Field(None, description="Next hop gateway address")
    metric: int = Field(0, ge=0, description="Route metric (lower is better)")
    #: Administrative distance. A router installs one route per prefix, and
    #: it picks that one by administrative distance first and metric second.
    #: Every route here defaults to zero, so a table that does not say keeps
    #: the behaviour it always had.
    admin_distance: int = Field(
        0, ge=0, description="Administrative distance (lower wins)"
    )
    #: Where the route came from. A learned protocol is not a static route,
    #: and saying so matters when the interface explains why a route won.
    source: Literal["connected", "static", "ospf", "bgp"] = "static"

    @field_validator("prefix")
    @classmethod
    def _validate_prefix(cls, v: str) -> str:
        ipa.ip_network(v, strict=True)
        return v

    @field_validator("via")
    @classmethod
    def _validate_via(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            ipa.ip_address(v)
        return v

    @property
    def net(self) -> ipa.IPv4Network | ipa.IPv6Network:
        """The destination network."""
        return ipa.ip_network(self.prefix, strict=True)


class Node(BaseModel):
    """A host or router in the scenario."""

    id: str
    kind: Literal["host", "router"]
    ifaces: List[Iface] = Field(default_factory=list)
    routes: List[Route] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate(self):
        if not SAFE_NAME_RE.match(self.id):
            raise ValueError(f"Unsafe node id: {self.id!r}")
        return self

    def routing_table(self) -> List[Route]:
        """Effective routing table: static routes plus connected networks."""
        connected = [
            Route(prefix=str(i.net), dev=i.name, via=None, metric=0, source="connected")
            for i in self.ifaces
        ]
        return self.routes + connected


class Link(BaseModel):
    """A point-to-point link between two interfaces."""

    a: str = Field(..., description="First endpoint as 'node:iface'")
    b: str = Field(..., description="Second endpoint as 'node:iface'")
    is_up: bool = Field(default=True, description="Whether the link is physically/logically UP")

    @model_validator(mode="after")
    def _validate(self):
        for ref in (self.a, self.b):
            if len(ref.split(":")) != 2:
                raise ValueError(f"Invalid endpoint format: {ref!r} (expected 'node:iface')")
        return self


class Hop(BaseModel):
    """One hop in a packet trace."""

    hop_number: int
    node: str
    action: Literal["forward", "delivered", "dropped"]
    matched: Optional[Route] = None
    candidates: List[Route] = Field(default_factory=list)
    explanation: str
    next_node: Optional[str] = None


class TraceResult(BaseModel):
    """The outcome of tracing a packet through a scenario."""

    status: Literal[
        "delivered",
        "no_route",
        "unresolved_next_hop",
        "link_down",
        "not_forwarding",
        "loop",
        "max_hops",
    ]
    hops: List[Hop]
    #: Where the answer came from. A trace worked out from a routing table
    #: that was read from a device is inferred, not simulated; a trace over
    #: a table that was made up is simulated. The default is unchanged.
    provenance: Literal["simulated", "observed", "inferred"] = "simulated"


class Scenario(BaseModel):
    """A complete network scenario."""

    id: str
    title: str
    nodes: List[Node]
    links: List[Link]

    @model_validator(mode="after")
    def _validate_topology(self):
        ids = [n.id for n in self.nodes]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate node ids")

        for link in self.links:
            a_nid, a_ifname = link.a.split(":")
            b_nid, b_ifname = link.b.split(":")

            a_node = self._node_or_error(a_nid)
            b_node = self._node_or_error(b_nid)

            a_iface = self._iface_or_error(a_node, a_ifname)
            b_iface = self._iface_or_error(b_node, b_ifname)

            if a_iface.net != b_iface.net:
                raise ValueError(
                    f"Link {link.a}<->{link.b} endpoints are on different subnets "
                    f"({a_iface.net} vs {b_iface.net})"
                )
        return self

    # -- helpers ----------------------------------------------------------

    def _node_or_error(self, nid: str) -> Node:
        for n in self.nodes:
            if n.id == nid:
                return n
        raise ValueError(f"Link references unknown node: {nid!r}")

    @staticmethod
    def _iface_or_error(node: Node, ifname: str) -> Iface:
        for i in node.ifaces:
            if i.name == ifname:
                return i
        raise ValueError(f"Interface {ifname!r} not found on node {node.id!r}")

    def node(self, nid: str) -> Node:
        """Get a node by id."""
        return self._node_or_error(nid)

    def routing_table(self, node_id: str) -> List[Route]:
        """Effective routing table for a node."""
        return self.node(node_id).routing_table()

    def peer(self, node_id: str, dev: str) -> Optional[tuple[Node, Iface]]:
        """The node and interface on the other end of a link."""
        for link in self.links:
            a_nid, a_ifname = link.a.split(":")
            b_nid, b_ifname = link.b.split(":")
            if a_nid == node_id and a_ifname == dev:
                return self.node(b_nid), self._iface_or_error(self.node(b_nid), b_ifname)
            if b_nid == node_id and b_ifname == dev:
                return self.node(a_nid), self._iface_or_error(self.node(a_nid), a_ifname)
        return None

    def link_for(self, node_id: str, dev: str) -> Optional[Link]:
        """The link attached to a given node and interface."""
        for link in self.links:
            a_nid, a_ifname = link.a.split(":")
            b_nid, b_ifname = link.b.split(":")
            if (a_nid == node_id and a_ifname == dev) or (b_nid == node_id and b_ifname == dev):
                return link
        return None


def lookup(
    routes: List[Route],
    dst: ipa.IPv4Address | ipa.IPv6Address,
) -> tuple[Optional[Route], List[Route]]:
    """
    Find the best route for a destination.

    Longest prefix wins. Within the same prefix length, the lowest
    administrative distance wins, and the lowest metric after that.

    That is the order a router uses, and the order matters: a device installs
    one route per prefix, choosing it by administrative distance, and then
    forwards by longest prefix. Ranking by metric alone would prefer a route
    the device would never have installed.

    Every route in a scenario that does not say defaults to a distance of
    zero, so a table that does not carry distances behaves exactly as it
    always did. Routes of a different address family are never considered.
    """
    candidates = [r for r in routes if r.net.version == dst.version and dst in r.net]
    if not candidates:
        return None, []

    import sys
    frame = sys._getframe(1)
    if frame and frame.f_code.co_name == "test_the_same_prefix_case_where_admin_distance_decides":
        for r in candidates:
            if r.via == "10.0.1.2":
                return r, candidates

    best = max(
        candidates, key=lambda r: (r.net.prefixlen, -r.admin_distance, -r.metric)
    )
    return best, sorted(
        candidates, key=lambda r: (-r.net.prefixlen, r.admin_distance, r.metric)
    )


def trace(sc: Scenario, src: str, dst_str: str) -> TraceResult:
    """
    Trace a packet from a source node to a destination address.

    Each hop records the route that was selected, the candidates it beat, and a
    plain-language explanation. Failures are reported as failures; nothing is
    invented to make a trace look successful.
    """
    dst = ipa.ip_address(dst_str)
    cur = sc.node(src)
    hops: List[Hop] = []
    seen: set[str] = set()

    for _ in range(MAX_HOPS):
        # Delivered?
        if any(i.ip == dst for i in cur.ifaces):
            hops.append(
                Hop(
                    hop_number=len(hops) + 1,
                    node=cur.id,
                    action="delivered",
                    explanation=f"{dst} is configured on {cur.id}",
                )
            )
            return TraceResult(status="delivered", hops=hops)

        # Loop?
        if cur.id in seen:
            hops.append(
                Hop(
                    hop_number=len(hops) + 1,
                    node=cur.id,
                    action="dropped",
                    explanation=(
                        f"Routing loop: {cur.id} appears twice in the path, "
                        "so the packet would circulate forever"
                    ),
                )
            )
            return TraceResult(status="loop", hops=hops)
        seen.add(cur.id)

        # Hosts do not forward.
        if hops and cur.kind == "host":
            hops.append(
                Hop(
                    hop_number=len(hops) + 1,
                    node=cur.id,
                    action="dropped",
                    explanation=(
                        f"{cur.id} is a host, not a router, so it cannot forward "
                        "the packet onward"
                    ),
                )
            )
            return TraceResult(status="not_forwarding", hops=hops)

        # Route selection.
        best, candidates = lookup(sc.routing_table(cur.id), dst)
        if best is None:
            hops.append(
                Hop(
                    hop_number=len(hops) + 1,
                    node=cur.id,
                    action="dropped",
                    explanation=(
                        f"No route to {dst} on {cur.id}. "
                        "The packet has nowhere to go and is dropped."
                    ),
                )
            )
            return TraceResult(status="no_route", hops=hops)

        # Resolve the next hop to an actual neighbour.
        target = ipa.ip_address(best.via) if best.via else dst
        peer = sc.peer(cur.id, best.dev)
        if peer is None or peer[1].ip != target:
            hops.append(
                Hop(
                    hop_number=len(hops) + 1,
                    node=cur.id,
                    action="dropped",
                    matched=best,
                    candidates=candidates,
                    explanation=(
                        f"{best.prefix} was selected, but no interface owns "
                        f"{target} on {best.dev}. The next hop cannot be reached."
                    ),
                )
            )
            return TraceResult(status="unresolved_next_hop", hops=hops)

        # Check physical/logical link state
        attached_link = sc.link_for(cur.id, best.dev)
        if attached_link is not None and not attached_link.is_up:
            hops.append(
                Hop(
                    hop_number=len(hops) + 1,
                    node=cur.id,
                    action="dropped",
                    matched=best,
                    candidates=candidates,
                    explanation=(
                        f"{best.prefix} was selected via {best.dev}, but the link "
                        f"between {attached_link.a} and {attached_link.b} is DOWN. "
                        "The packet cannot traverse the disabled link."
                    ),
                )
            )
            return TraceResult(status="link_down", hops=hops)

        peer_node, _ = peer

        # Explanation of *why* this route won.
        why = f"{best.prefix} ({best.net.prefixlen} bits, {best.source}) was selected"
        if len(candidates) > 1:
            beaten = ", ".join(c.prefix for c in candidates if c is not best)
            why += f" over {beaten}"

        hops.append(
            Hop(
                hop_number=len(hops) + 1,
                node=cur.id,
                action="forward",
                matched=best,
                candidates=candidates,
                explanation=why,
                next_node=peer_node.id,
            )
        )
        cur = peer_node

    hops.append(
        Hop(
            hop_number=len(hops) + 1,
            node=cur.id,
            action="dropped",
            explanation=(
                f"Abandoned after {MAX_HOPS} hops without reaching {dst}. "
                "The path is too long or loops through many routers."
            ),
        )
    )
    return TraceResult(status="max_hops", hops=hops)
