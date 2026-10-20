"""
RouteLens Lite - Predefined Network Scenarios

Scenarios are the single source of truth for both the simulator and the lab
builder. A scenario describes nodes, their interfaces, their routing tables,
and the point-to-point links between them.
"""

from typing import Dict, List

from app.scenario import Scenario, Node, Iface, Link, Route


# =============================================================================
# 1. Client -> Router -> Server (IPv4)
# =============================================================================
CLIENT_ROUTER_SERVER = Scenario(
    id="client-router-server",
    title="Client → Router → Server (IPv4)",
    nodes=[
        Node(
            id="client",
            kind="host",
            ifaces=[Iface(name="eth0", cidr="192.168.1.100/24")],
            routes=[
                # The client only knows its directly connected network,
                # so everything else goes via its gateway.
                Route(prefix="0.0.0.0/0", dev="eth0", via="192.168.1.1", metric=100),
            ],
        ),
        Node(
            id="router",
            kind="router",
            ifaces=[
                Iface(name="eth0", cidr="192.168.1.1/24"),
                Iface(name="eth1", cidr="10.0.0.1/24"),
            ],
            routes=[
                Route(prefix="0.0.0.0/0", dev="eth1", via="10.0.0.2", metric=10),
            ],
        ),
        Node(
            id="server",
            kind="host",
            ifaces=[Iface(name="eth0", cidr="10.0.0.2/24")],
        ),
    ],
    links=[
        Link(a="client:eth0", b="router:eth0"),
        Link(a="router:eth1", b="server:eth0"),
    ],
)


# =============================================================================
# 2. Client -> R1 -> R2 -> Server (IPv4, static routes)
# =============================================================================
TWO_ROUTERS = Scenario(
    id="two-routers",
    title="Client → Router 1 → Router 2 → Server (IPv4, static routes)",
    nodes=[
        Node(
            id="client",
            kind="host",
            ifaces=[Iface(name="eth0", cidr="192.168.1.100/24")],
            routes=[
                Route(prefix="0.0.0.0/0", dev="eth0", via="192.168.1.1", metric=100),
            ],
        ),
        Node(
            id="r1",
            kind="router",
            ifaces=[
                Iface(name="eth0", cidr="192.168.1.1/24"),
                Iface(name="eth1", cidr="10.0.0.1/30"),
            ],
            routes=[
                # r1 knows the server network is behind r2.
                Route(prefix="10.0.1.0/24", dev="eth1", via="10.0.0.2", metric=10),
            ],
        ),
        Node(
            id="r2",
            kind="router",
            ifaces=[
                Iface(name="eth0", cidr="10.0.0.2/30"),
                Iface(name="eth1", cidr="10.0.1.1/24"),
            ],
            routes=[
                # r2 knows how to get back to the client network.
                Route(prefix="192.168.1.0/24", dev="eth0", via="10.0.0.1", metric=10),
            ],
        ),
        Node(
            id="server",
            kind="host",
            ifaces=[Iface(name="eth0", cidr="10.0.1.100/24")],
        ),
    ],
    links=[
        Link(a="client:eth0", b="r1:eth0"),
        Link(a="r1:eth1", b="r2:eth0"),
        Link(a="r2:eth1", b="server:eth0"),
    ],
)


# =============================================================================
# 3. Routing loop (r1 and r2 point their default routes at each other)
# =============================================================================
LOOP = Scenario(
    id="loop",
    title="Routing loop (Router 1 and Router 2 point at each other)",
    nodes=[
        Node(
            id="r1",
            kind="router",
            ifaces=[Iface(name="eth0", cidr="10.0.0.1/30")],
            routes=[
                Route(prefix="0.0.0.0/0", dev="eth0", via="10.0.0.2", metric=10),
            ],
        ),
        Node(
            id="r2",
            kind="router",
            ifaces=[Iface(name="eth0", cidr="10.0.0.2/30")],
            routes=[
                Route(prefix="0.0.0.0/0", dev="eth0", via="10.0.0.1", metric=10),
            ],
        ),
    ],
    links=[Link(a="r1:eth0", b="r2:eth0")],
)


# =============================================================================
# 4. Dual stack (IPv4 and IPv6 on separate interfaces)
# =============================================================================
DUAL_STACK = Scenario(
    id="dual-stack",
    title="Dual stack: Client → Router → Server (IPv4 and IPv6)",
    nodes=[
        Node(
            id="client",
            kind="host",
            ifaces=[
                Iface(name="eth0", cidr="192.168.1.100/24"),
                Iface(name="eth1", cidr="2001:db8:1::100/64"),
            ],
            routes=[
                Route(prefix="0.0.0.0/0", dev="eth0", via="192.168.1.1", metric=100),
                Route(prefix="::/0", dev="eth1", via="2001:db8:1::1", metric=100),
            ],
        ),
        Node(
            id="router",
            kind="router",
            ifaces=[
                Iface(name="eth0", cidr="192.168.1.1/24"),
                Iface(name="eth1", cidr="10.0.0.1/24"),
                Iface(name="eth2", cidr="2001:db8:1::1/64"),
                Iface(name="eth3", cidr="2001:db8:2::1/64"),
            ],
            routes=[
                Route(prefix="0.0.0.0/0", dev="eth1", via="10.0.0.2", metric=10),
                Route(prefix="::/0", dev="eth3", via="2001:db8:2::2", metric=10),
            ],
        ),
        Node(
            id="server",
            kind="host",
            ifaces=[
                Iface(name="eth0", cidr="10.0.0.2/24"),
                Iface(name="eth1", cidr="2001:db8:2::2/64"),
            ],
        ),
    ],
    links=[
        Link(a="client:eth0", b="router:eth0"),
        Link(a="client:eth1", b="router:eth2"),
        Link(a="router:eth1", b="server:eth0"),
        Link(a="router:eth3", b="server:eth1"),
    ],
)


# =============================================================================
# 5. IPv6 only
# =============================================================================
IPV6_ONLY = Scenario(
    id="ipv6-only",
    title="IPv6 only: Client → Router → Server",
    nodes=[
        Node(
            id="client",
            kind="host",
            ifaces=[Iface(name="eth0", cidr="2001:db8:1::100/64")],
            routes=[
                Route(prefix="::/0", dev="eth0", via="2001:db8:1::1", metric=100),
            ],
        ),
        Node(
            id="router",
            kind="router",
            ifaces=[
                Iface(name="eth0", cidr="2001:db8:1::1/64"),
                Iface(name="eth1", cidr="2001:db8:2::1/64"),
            ],
            routes=[
                Route(prefix="2001:db8:2::/64", dev="eth1", via="2001:db8:2::2", metric=10),
            ],
        ),
        Node(
            id="server",
            kind="host",
            ifaces=[Iface(name="eth0", cidr="2001:db8:2::2/64")],
        ),
    ],
    links=[
        Link(a="client:eth0", b="router:eth0"),
        Link(a="router:eth1", b="server:eth0"),
    ],
)


# =============================================================================
# Registry
# =============================================================================
SCENARIOS: Dict[str, Scenario] = {
    s.id: s
    for s in (
        CLIENT_ROUTER_SERVER,
        TWO_ROUTERS,
        LOOP,
        DUAL_STACK,
        IPV6_ONLY,
    )
}


def get_scenario(sid: str) -> Scenario:
    """Get a scenario by id."""
    if sid not in SCENARIOS:
        raise KeyError(f"Unknown scenario: {sid}")
    return SCENARIOS[sid]


def list_scenarios() -> List[dict]:
    """Summaries of all available scenarios."""
    return [{"id": s.id, "title": s.title} for s in SCENARIOS.values()]
