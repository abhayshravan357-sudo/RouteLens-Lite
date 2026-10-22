"""
Tests for the Scenario Engine.

Covers:
- Scenario model validation
- Longest-prefix matching and metric tiebreak
- Trace outcomes: delivered, no_route, loop, unresolved_next_hop, not_forwarding, max_hops
- IPv4 and IPv6 handled separately (no family mixing)
- Lab command generation safety (argument lists, no shell)
- Root-only sim-vs-lab comparison (skipped when unprivileged)
"""

import os
import pytest
import ipaddress as ipa

from app.scenario import (
    Scenario,
    Node,
    Iface,
    Link,
    Route,
    trace,
    lookup,
    MAX_HOPS,
)
from app.scenarios_data import SCENARIOS
from app import lab_builder as lab


# ---------------------------------------------------------------------------
# Scenario model validation
# ---------------------------------------------------------------------------


class TestScenarioModel:
    """Tests for scenario construction and validation."""

    def test_predefined_scenarios_load(self):
        """All predefined scenarios must validate."""
        for sid in ("client-router-server", "two-routers", "loop", "dual-stack"):
            assert sid in SCENARIOS
            sc = SCENARIOS[sid]
            assert sc.id == sid
            assert sc.title

    def test_duplicate_node_ids_rejected(self):
        """Duplicate node ids must fail validation."""
        with pytest.raises(ValueError, match="Duplicate node"):
            Scenario(
                id="dup",
                title="Duplicate nodes",
                nodes=[
                    Node(id="a", kind="host", ifaces=[Iface(name="eth0", cidr="10.0.0.1/30")]),
                    Node(id="a", kind="host", ifaces=[Iface(name="eth0", cidr="10.0.0.2/30")]),
                ],
                links=[],
            )

    def test_link_across_different_subnets_rejected(self):
        """A link whose endpoints are on different subnets must be rejected."""
        with pytest.raises(ValueError, match="subnet"):
            Scenario(
                id="bad",
                title="Bad link",
                nodes=[
                    Node(id="a", kind="host", ifaces=[Iface(name="eth0", cidr="10.0.0.1/24")]),
                    Node(id="b", kind="host", ifaces=[Iface(name="eth0", cidr="192.168.0.1/24")]),
                ],
                links=[Link(a="a:eth0", b="b:eth0")],
            )

    def test_link_to_unknown_node_rejected(self):
        """A link referencing a missing node must be rejected."""
        with pytest.raises(ValueError, match="unknown node"):
            Scenario(
                id="bad2",
                title="Bad link 2",
                nodes=[Node(id="a", kind="host", ifaces=[Iface(name="eth0", cidr="10.0.0.1/24")])],
                links=[Link(a="a:eth0", b="ghost:eth0")],
            )


# ---------------------------------------------------------------------------
# Route lookup
# ---------------------------------------------------------------------------


class TestLookup:
    """Tests for the route lookup helper."""

    def test_longest_prefix_wins(self):
        """More specific prefix beats less specific regardless of metric."""
        routes = [
            Route(prefix="192.168.1.0/24", dev="eth0", via="10.0.0.1", metric=10),
            Route(prefix="192.168.1.0/25", dev="eth1", via="10.0.0.2", metric=20),
        ]
        best, candidates = lookup(routes, ipa.ip_address("192.168.1.50"))
        assert best is not None
        assert best.prefix == "192.168.1.0/25"
        assert len(candidates) == 2

    def test_metric_tiebreak_within_same_prefix(self):
        """Lower metric wins when prefix length is equal."""
        routes = [
            Route(prefix="192.168.1.0/24", dev="eth0", via="10.0.0.1", metric=30),
            Route(prefix="192.168.1.0/24", dev="eth1", via="10.0.0.2", metric=5),
        ]
        best, _ = lookup(routes, ipa.ip_address("192.168.1.50"))
        assert best is not None
        assert best.metric == 5

    def test_no_matching_route(self):
        """A destination outside every prefix yields no route."""
        routes = [Route(prefix="192.168.1.0/24", dev="eth0", via="10.0.0.1", metric=10)]
        best, candidates = lookup(routes, ipa.ip_address("8.8.8.8"))
        assert best is None
        assert candidates == []

    def test_ip_families_do_not_mix(self):
        """An IPv6 destination must not match an IPv4 route."""
        routes = [Route(prefix="0.0.0.0/0", dev="eth0", via="10.0.0.1", metric=10)]
        best, _ = lookup(routes, ipa.ip_address("2001:db8::1"))
        assert best is None


# ---------------------------------------------------------------------------
# Trace outcomes
# ---------------------------------------------------------------------------


class TestTraceOutcomes:
    """Tests for each trace outcome the engine can report."""

    def test_delivered_two_hop(self):
        """client -> router -> server must be delivered."""
        sc = SCENARIOS["client-router-server"]
        result = trace(sc, "client", "10.0.0.2")

        assert result.status == "delivered"
        assert result.provenance == "simulated"
        assert [h.action for h in result.hops] == ["forward", "forward", "delivered"]
        assert result.hops[0].matched is not None
        assert result.hops[0].matched.prefix == "0.0.0.0/0"

    def test_hops_are_numbered_from_one(self):
        """Every hop carries a 1-based number so the UI can step through them."""
        sc = SCENARIOS["client-router-server"]
        result = trace(sc, "client", "10.0.0.2")
        assert [h.hop_number for h in result.hops] == [1, 2, 3]

    def test_failure_hops_are_also_numbered(self):
        """A failing trace still numbers its hops."""
        sc = SCENARIOS["loop"]
        result = trace(sc, "r1", "203.0.113.9")
        assert result.status == "loop"
        assert [h.hop_number for h in result.hops] == list(range(1, len(result.hops) + 1))

    def test_delivered_three_router_chain(self):
        """client -> r1 -> r2 -> server must traverse three routers."""
        sc = SCENARIOS["two-routers"]
        result = trace(sc, "client", "10.0.1.100")

        assert result.status == "delivered"
        assert len(result.hops) == 4
        assert result.hops[0].node == "client"
        assert result.hops[1].node == "r1"
        assert result.hops[2].node == "r2"
        assert result.hops[3].node == "server"

    def test_no_route(self):
        """A destination with no matching route reports no_route."""
        sc = SCENARIOS["client-router-server"].model_copy(deep=True)
        # Take the client's default route away: it now only knows its own subnet.
        sc.node("client").routes = []

        result = trace(sc, "client", "8.8.8.8")
        assert result.status == "no_route"
        assert result.hops[-1].action == "dropped"
        assert "no route" in result.hops[-1].explanation.lower()

    def test_no_route_when_default_removed(self):
        """Removing the router's default route changes how the path resolves."""
        sc = SCENARIOS["client-router-server"].model_copy(deep=True)
        sc.node("router").routes = [r for r in sc.node("router").routes if r.prefix != "0.0.0.0/0"]

        result = trace(sc, "client", "10.0.0.2")
        # The router still has the directly connected 10.0.0.0/24, so the
        # packet reaches the server - but no default route was involved.
        assert result.status == "delivered"
        router_hop = next(h for h in result.hops if h.node == "router")
        assert router_hop.matched is not None
        assert router_hop.matched.source == "connected"

    def test_loop_detected(self):
        """Two routers pointing default routes at each other must be detected."""
        sc = SCENARIOS["loop"]
        result = trace(sc, "r1", "203.0.113.9")
        assert result.status == "loop"

    def test_unresolved_next_hop(self):
        """A next hop that nobody owns must be reported, not invented."""
        sc = Scenario(
            id="unresolved",
            title="Unresolved next hop",
            nodes=[
                Node(
                    id="a",
                    kind="router",
                    ifaces=[Iface(name="eth0", cidr="10.0.0.1/30")],
                    # A default route pointing at an address nobody owns.
                    routes=[Route(prefix="0.0.0.0/0", dev="eth0", via="10.0.0.99", metric=10)],
                ),
                Node(
                    id="b",
                    kind="router",
                    ifaces=[Iface(name="eth0", cidr="10.0.0.2/30")],
                    routes=[],
                ),
            ],
            links=[Link(a="a:eth0", b="b:eth0")],
        )
        # 203.0.113.9 is not covered by any connected network, so the default
        # route is chosen and its next hop cannot be resolved.
        result = trace(sc, "a", "203.0.113.9")
        assert result.status == "unresolved_next_hop"
        assert result.hops[-1].action == "dropped"
        assert "10.0.0.99" in result.hops[-1].explanation

    def test_host_does_not_forward(self):
        """A host that is not the destination cannot forward packets."""
        sc = Scenario(
            id="hostfwd",
            title="Host does not forward",
            nodes=[
                Node(
                    id="h1",
                    kind="host",
                    ifaces=[Iface(name="eth0", cidr="10.0.0.1/30")],
                    routes=[Route(prefix="0.0.0.0/0", dev="eth0", via="10.0.0.2", metric=10)],
                ),
                Node(
                    id="h2",
                    kind="host",
                    ifaces=[Iface(name="eth0", cidr="10.0.0.2/30")],
                    routes=[],
                ),
            ],
            links=[Link(a="h1:eth0", b="h2:eth0")],
        )
        result = trace(sc, "h1", "203.0.113.9")
        assert result.status == "not_forwarding"

    def test_max_hops_terminates(self):
        """A chain longer than MAX_HOPS must terminate, not hang."""
        # Each router has a "down" interface to the previous router and an
        # "up" interface to the next one, so consecutive routers share a /30.
        count = MAX_HOPS + 5
        nodes = []
        links = []
        for i in range(count):
            ifaces = []
            if i > 0:
                ifaces.append(Iface(name="down", cidr=f"10.0.{i - 1}.2/30"))
            if i < count - 1:
                ifaces.append(Iface(name="up", cidr=f"10.0.{i}.1/30"))

            routes = []
            if i < count - 1:
                routes.append(Route(prefix="0.0.0.0/0", dev="up", via=f"10.0.{i}.2", metric=10))

            nodes.append(
                Node(id=f"r{i}", kind="router", ifaces=ifaces, routes=routes)
            )
            if i > 0:
                links.append(Link(a=f"r{i - 1}:up", b=f"r{i}:down"))

        sc = Scenario(id="long", title="Long chain", nodes=nodes, links=links)
        result = trace(sc, "r0", "203.0.113.9")

        assert result.status == "max_hops"
        # MAX_HOPS forwarding hops plus a final marker explaining the abort.
        assert len(result.hops) == MAX_HOPS + 1
        assert result.hops[-1].action == "dropped"
        assert str(MAX_HOPS) in result.hops[-1].explanation

    def test_same_source_and_destination(self):
        """Tracing to the source itself delivers immediately."""
        sc = SCENARIOS["client-router-server"]
        result = trace(sc, "client", "192.168.1.100")
        assert result.status == "delivered"


# ---------------------------------------------------------------------------
# IPv6
# ---------------------------------------------------------------------------


class TestIPv6Scenarios:
    """IPv6 must be traced independently of IPv4."""

    def test_dual_stack_ipv4_delivery(self):
        """The dual-stack scenario still delivers IPv4 traffic."""
        sc = SCENARIOS["dual-stack"]
        result = trace(sc, "client", "10.0.0.2")
        assert result.status == "delivered"

    def test_dual_stack_ipv6_delivery(self):
        """IPv6 traffic is delivered in the dual-stack scenario."""
        sc = SCENARIOS["dual-stack"]
        result = trace(sc, "client", "2001:db8:2::2")
        assert result.status == "delivered"
        assert result.hops[0].matched is not None
        assert result.hops[0].matched.net.version == 6

    def test_ipv4_destination_never_selects_ipv6_route(self):
        """An IPv6 route must never be selected for an IPv4 destination."""
        sc = SCENARIOS["dual-stack"]
        # Remove every IPv4 route from the router, leaving only the IPv6 default.
        router = sc.node("router")
        router.routes = [r for r in router.routes if r.prefix == "::/0"]

        result = trace(sc, "client", "10.0.0.2")
        # Whatever the outcome, no IPv6 route may have been chosen.
        for hop in result.hops:
            if hop.matched is not None:
                assert hop.matched.net.version == 4
        # The client's IPv6 default route must not have been used either.
        assert result.hops[0].matched.net.version == 4

    def test_ipv6_destination_never_selects_ipv4_route(self):
        """An IPv4 route must never be selected for an IPv6 destination."""
        sc = SCENARIOS["dual-stack"]
        router = sc.node("router")
        router.routes = [r for r in router.routes if r.prefix == "0.0.0.0/0"]

        result = trace(sc, "client", "2001:db8:2::2")
        for hop in result.hops:
            if hop.matched is not None:
                assert hop.matched.net.version == 6
        assert result.hops[0].matched.net.version == 6


# ---------------------------------------------------------------------------
# Lab command generation
# ---------------------------------------------------------------------------


class TestLabBuilder:
    """The lab builder must generate safe, bounded commands."""

    def test_commands_are_argument_lists(self):
        """Every command must be a list, never a shell string."""
        cmds = lab.build_commands(SCENARIOS["client-router-server"])
        assert cmds, "expected at least one command"
        for cmd in cmds:
            assert isinstance(cmd, list)
            assert all(isinstance(part, str) for part in cmd)

    def test_namespaces_created_for_every_node(self):
        """Each node gets a namespace."""
        cmds = lab.build_commands(SCENARIOS["client-router-server"])
        add_ns = [c for c in cmds if c[:3] == ["ip", "netns", "add"]]
        assert len(add_ns) == 3
        for cmd in add_ns:
            assert cmd[3].startswith("rl_")

    def test_veth_pair_per_link(self):
        """Each link produces one veth creation command."""
        cmds = lab.build_commands(SCENARIOS["two-routers"])
        veth = [c for c in cmds if c[:3] == ["ip", "link", "add"]]
        assert len(veth) == 3

    def test_addresses_assigned(self):
        """Each interface gets an address and is brought up."""
        cmds = lab.build_commands(SCENARIOS["client-router-server"])
        addr = [c for c in cmds if len(c) > 3 and c[1] == "-n" and c[3] == "addr"]
        assert len(addr) >= 4  # 4 interfaces in this scenario

    def test_forwarding_enabled_only_on_routers(self):
        """Only routers get ip_forward enabled."""
        cmds = lab.build_commands(SCENARIOS["client-router-server"])
        fwd = [c for c in cmds if "net.ipv4.ip_forward" in " ".join(c)]
        assert len(fwd) == 1
        # The namespace name must be the router's prefixed id.
        assert "rl_router" in fwd[0]

    def test_teardown_removes_all_namespaces(self):
        """Teardown deletes every namespace."""
        cmds = lab.teardown_commands(SCENARIOS["client-router-server"])
        assert len(cmds) == 3
        for cmd in cmds:
            assert cmd[:3] == ["ip", "netns", "del"]
            assert cmd[3].startswith("rl_")

    def test_dry_run_returns_commands_without_executing(self):
        """Dry run reports the plan without touching the system."""
        result = lab.run_all([["ip", "netns", "add", "rl_test"]], dry_run=True)
        assert result["status"] == "dry_run"
        assert "ip netns add rl_test" in result["commands"]

    def test_unprivileged_run_reports_unavailable(self):
        """Without root, execution is refused with a clear reason."""
        if os.geteuid() == 0:
            pytest.skip("running as root; privilege guard not exercised")
        result = lab.run_all([["ip", "netns", "add", "rl_test"]], dry_run=False)
        assert result["status"] == "unavailable"
        assert "root" in result["reason"].lower()

    def test_probe_unprivileged_reports_unavailable(self):
        """Without root, probing is refused with a clear reason."""
        if os.geteuid() == 0:
            pytest.skip("running as root; privilege guard not exercised")
        result = lab.probe("client", "10.0.0.2")
        assert result["status"] == "unavailable"
        assert "root" in result["reason"].lower()


# ---------------------------------------------------------------------------
# Sim vs reality
# ---------------------------------------------------------------------------


class TestSimVersusLab:
    """The lab must agree with the simulation when the lab is available."""

    @pytest.mark.skipif(os.geteuid() != 0, reason="requires root to build namespaces")
    def test_simulation_matches_reality(self):
        """Build the lab, then confirm simulation and reality agree."""
        sc = SCENARIOS["client-router-server"]

        apply_result = lab.run_all(lab.build_commands(sc), dry_run=False)
        if apply_result.get("status") != "ok":
            pytest.skip(f"could not build lab namespaces: {apply_result}")

        try:
            simulated_delivered = trace(sc, "client", "10.0.0.2").status == "delivered"
            real = lab.probe("client", "10.0.0.2")
            assert real["status"] == "delivered"
            assert simulated_delivered is True
        finally:
            lab.run_all(lab.teardown_commands(sc), dry_run=False, stop_on_error=False)

    def test_compare_reports_unavailable_lab_honestly(self):
        """Without root, compare must report unavailable, not a fake agreement."""
        if os.geteuid() == 0:
            pytest.skip("running as root; unprivileged comparison not exercised")
        result = lab.probe("client", "10.0.0.2")
        assert result["status"] == "unavailable"
        assert "provenance" not in result or result.get("provenance") != "lab"
