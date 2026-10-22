"""
RouteLens Lite - Router discovery models.

These are the things a discovery run is allowed to say it found.

The rule behind every field here: a value is present because it was
read, not because it was plausible. A field that could not be read is
absent or None. Nothing here is filled in with a guess.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class RouteEntry(BaseModel):
    """
    One entry of a router's routing table, as that router reported it.

    A route with no next hop is a connected route. The prefix is always
    a network the tool could parse; a prefix that could not be read is
    recorded as a collector error instead of appearing here.
    """

    prefix: str
    next_hop: Optional[str] = None
    interface: Optional[str] = None
    protocol: Optional[str] = None
    metric: Optional[int] = None
    admin_distance: Optional[int] = None
    selected: bool = True


class IfaceInfo(BaseModel):
    """
    One interface of a router.

    Addresses are in CIDR notation, as the router reported them.
    """

    name: str
    addresses: List[str] = Field(default_factory=list)
    up: bool = True


class Neighbor(BaseModel):
    """
    One neighbour a router told us about.

    `via` records how the neighbour was learned, which is what makes the
    difference between an observed adjacency and an inferred one. An ARP
    neighbour is a host on the same link, not a router, and is never
    followed as a device.
    """

    local_if: Optional[str] = None
    remote_name: Optional[str] = None
    remote_if: Optional[str] = None
    remote_ip: Optional[str] = None
    via: Literal["lldp", "cdp", "ospf", "bgp", "arp"]


class DeviceSnapshot(BaseModel):
    """
    Everything one collection read from one device.

    `device_id` identifies the device, not the address it was reached on,
    so a router reached by several addresses is one device and is not
    collected twice.

    `errors` lists the optional sources that could not be read. Their
    absence is recorded; their content is never invented.
    """

    device_id: str
    hostname: str
    mgmt_target: str
    method: Literal["ssh", "snmp", "docker", "local"]
    collected_at: datetime
    interfaces: List[IfaceInfo] = Field(default_factory=list)
    routes: List[RouteEntry] = Field(default_factory=list)
    neighbors: List[Neighbor] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
    provenance: Literal["observed"] = "observed"


class Edge(BaseModel):
    """
    A link between two devices in the map.

    `provenance` says how the edge is known:

    - observed: the devices said so themselves, over LLDP or CDP
    - inferred: we worked it out from routing or addressing, which can
      cross a switch and is therefore not an observation

    The same pair of devices may have more than one edge. They are
    different facts, and one does not replace the other.
    """

    a: str
    b: str
    kind: Literal["lldp", "cdp", "l3_next_hop", "shared_subnet"]
    provenance: Literal["observed", "inferred"]
    evidence: str
