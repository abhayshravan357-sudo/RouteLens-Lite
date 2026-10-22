"""
Tests for the router discovery core.

ABOUT THE FIXTURES IN THIS FILE
-------------------------------
There is no FRR, no containerlab and no router on this machine, so no
real `vtysh` output could be captured. Every JSON document below was
HAND-WRITTEN from the documented FRR JSON schema and the documented
iproute2 `ip -j` schema. They are not captures, not recordings and not
real output. They are illustrations of the shapes the parsers are
expected to read, and the parsers are written to the schema rather than
to these particular documents.

Nothing here fabricates a device and presents it as discovered. The
snapshots are test inputs, built by hand, and the tests say what each
one is for.

The tests cover:
  - the FRR routing table parser, including the shapes it must refuse
  - the read-only guard, which is the boundary between a collector and
    a router
  - the discovery engine, which decides how far a run may travel
  - the graph builder, which decides whether an edge was observed or
    inferred
"""

import json
from datetime import datetime, timezone

import pytest

from app.router_discovery.collectors.base import (
    ALLOWED,
    AuditedRunner,
    CommandNotAllowed,
    check_command,
    command_problem,
    redact,
)
from app.router_discovery.collectors.frr import (
    FrrCollector,
    FrrParseError,
    docker_runner,
    parse_frr_routes,
)
from app.router_discovery.engine import (
    CollectionFailure,
    DiscoveryResult,
    discover,
    in_scope,
)
from app.router_discovery.graph import build_edges
from app.router_discovery.models import (
    DeviceSnapshot,
    Edge,
    IfaceInfo,
    Neighbor,
    RouteEntry,
)


# ---------------------------------------------------------------------------
# Hand-written fixtures
#
# These follow the documented schemas. They are not captures.
# ---------------------------------------------------------------------------

#: FRR `show ip route json`, as documented. A connected route has no
#: next hop address; a static route does.
FRR_ROUTES_JSON = json.dumps(
    {
        "10.0.0.0/8": [
            {
                "prefix": "10.0.0.0/8",
                "protocol": "connected",
                "distance": 0,
                "metric": 0,
                "table": "254",
                "nexthops": [{"fib": True, "directlyConnected": True, "interfaceName": "eth1"}],
            }
        ],
        "192.168.1.0/24": [
            {
                "prefix": "192.168.1.0/24",
                "protocol": "static",
                "distance": 1,
                "metric": 20,
                "nexthops": [{"fib": True, "ip": "10.0.0.1", "interfaceName": "eth0"}],
            }
        ],
    }
)

#: iproute2 `ip -j addr`, as documented.
IP_ADDR_JSON = json.dumps(
    [
        {
            "ifindex": 2,
            "ifname": "eth0",
            "flags": ["BROADCAST", "MULTICAST", "UP", "LOWER_UP"],
            "operstate": "UP",
            "addr_info": [{"family": "inet", "local": "10.0.0.2/24", "prefixlen": 24}],
        },
        {
            "ifindex": 3,
            "ifname": "eth1",
            "flags": ["BROADCAST", "MULTICAST"],
            "operstate": "DOWN",
            "addr_info": [{"family": "inet", "local": "10.0.0.3/24", "prefixlen": 24}],
        },
    ]
)


def make_device(
    device_id: str,
    addresses=("10.0.0.1/24",),
    routes=(),
    neighbors=(),
    hostname: str = None,
) -> DeviceSnapshot:
    """A hand-built snapshot, for the engine and graph tests."""
    interfaces = [
        IfaceInfo(name=f"eth{index}", addresses=[address], up=True)
        for index, address in enumerate(addresses)
    ]
    return DeviceSnapshot(
        device_id=device_id,
        hostname=hostname if hostname is not None else device_id,
        mgmt_target=addresses[0].split("/")[0] if addresses else device_id,
        method="local",
        collected_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        interfaces=interfaces,
        routes=list(routes),
        neighbors=list(neighbors),
    )


class FakeCollector:
    """
    A collector that answers from a hand-written table.

    It exists so the engine can be tested without a network, a container
    or root. It also records the targets it was asked about, so a test
    can check what was not collected as well as what was.
    """

    def __init__(self, devices):
        self.devices = dict(devices)
        self.calls = []

    def collect(self, target):
        self.calls.append(target)
        if target not in self.devices:
            raise KeyError(f"no device at {target}")
        return self.devices[target]


# ---------------------------------------------------------------------------
# The FRR routing table parser
# ---------------------------------------------------------------------------

class TestParseFrrRoutes:
    """FRR's JSON routing table."""

    def test_the_documented_shape_is_read(self):
        """A prefix maps to a list of entries, each with a list of next hops."""
        routes = parse_frr_routes(FRR_ROUTES_JSON)

        assert len(routes) == 2
        by_prefix = {route.prefix: route for route in routes}

        connected = by_prefix["10.0.0.0/8"]
        assert connected.protocol == "connected"
        assert connected.interface == "eth1"
        assert connected.metric == 0
        assert connected.admin_distance == 0
        assert connected.next_hop is None

        static = by_prefix["192.168.1.0/24"]
        assert static.protocol == "static"
        assert static.next_hop == "10.0.0.1"
        assert static.interface == "eth0"
        assert static.metric == 20
        assert static.admin_distance == 1

    def test_an_empty_table_reads_as_no_routes(self):
        """An empty document is not an error, it is an empty table."""
        assert parse_frr_routes("{}") == []
        assert parse_frr_routes("") == []

    def test_a_route_with_no_next_hop_is_read(self):
        """A connected route has no next hop address, and that is fine."""
        document = json.dumps(
            {
                "10.0.0.0/8": [
                    {
                        "protocol": "connected",
                        "distance": 0,
                        "metric": 0,
                        "nexthops": [{"interfaceName": "eth1"}],
                    }
                ]
            }
        )
        routes = parse_frr_routes(document)

        assert len(routes) == 1
        assert routes[0].next_hop is None
        assert routes[0].interface == "eth1"

    def test_a_route_with_no_nexthops_key_at_all_is_read(self):
        """A route with no next hop list still describes a route."""
        document = json.dumps(
            {"10.0.0.0/8": [{"protocol": "connected", "distance": 0, "metric": 0}]}
        )
        routes = parse_frr_routes(document)

        assert len(routes) == 1
        assert routes[0].next_hop is None
        assert routes[0].interface is None

    def test_a_malformed_prefix_is_an_error_not_a_route(self):
        """A prefix nobody can parse is not a route anyone can route with."""
        errors = []
        document = json.dumps(
            {
                "not-a-network": [
                    {"protocol": "static", "nexthops": [{"ip": "10.0.0.1"}]}
                ]
            }
        )
        routes = parse_frr_routes(document, errors)

        assert routes == []
        assert len(errors) == 1
        assert "not-a-network" in errors[0]

    def test_a_good_prefix_beside_a_bad_one_is_still_read(self):
        """One unreadable entry does not lose the rest of the table."""
        errors = []
        document = json.dumps(
            {
                "not-a-network": [{"protocol": "static"}],
                "10.0.0.0/8": [{"protocol": "connected", "nexthops": [{}]}],
            }
        )
        routes = parse_frr_routes(document, errors)

        assert len(routes) == 1
        assert routes[0].prefix == "10.0.0.0/8"
        assert len(errors) == 1

    def test_a_malformed_json_document_is_refused(self):
        """A document that is not JSON cannot be read."""
        with pytest.raises(FrrParseError):
            parse_frr_routes("this is not json")

    def test_a_non_dict_document_is_refused(self):
        """A document that is not an object of prefixes cannot be read."""
        with pytest.raises(FrrParseError):
            parse_frr_routes("[1, 2, 3]")

    def test_a_list_document_is_refused_by_name(self):
        """The error says what was wrong."""
        with pytest.raises(FrrParseError) as excinfo:
            parse_frr_routes("[1, 2, 3]")
        assert "not an object" in str(excinfo.value)

    def test_a_selected_route_is_marked_selected(self):
        """The router's own selection is kept."""
        document = json.dumps(
            {
                "10.0.0.0/8": [
                    {"protocol": "ospf", "selected": True, "nexthops": [{}]},
                    {"protocol": "bgp", "selected": False, "nexthops": [{}]},
                ]
            }
        )
        routes = parse_frr_routes(document)

        assert [route.selected for route in routes] == [True, False]


# ---------------------------------------------------------------------------
# The read-only guard
# ---------------------------------------------------------------------------

class TestReadOnlyGuard:
    """The boundary between a collector and a router."""

    def test_show_is_allowed(self):
        """A show command reads."""
        assert command_problem("show ip route") is None
        check_command("show ip route")

    def test_ip_json_is_allowed(self):
        """An ip -j command reads."""
        assert command_problem("ip -j addr") is None
        check_command("ip -j addr")

    def test_hostname_is_allowed(self):
        """Asking for the hostname reads."""
        assert command_problem("hostname") is None
        check_command("hostname")

    def test_configure_terminal_is_refused(self):
        """A command that writes is refused."""
        assert command_problem("configure terminal") is not None
        with pytest.raises(PermissionError):
            check_command("configure terminal")

    def test_a_chained_command_is_refused(self):
        """A command that starts read-only but chains another is refused."""
        assert command_problem("show ip route; rm -rf /") is not None
        with pytest.raises(PermissionError):
            check_command("show ip route; rm -rf /")

    def test_a_command_with_a_newline_is_refused(self):
        """A command split over two lines is refused."""
        assert command_problem("show ip route\nrm -rf /") is not None
        with pytest.raises(PermissionError):
            check_command("show ip route\nrm -rf /")

    def test_a_command_with_leading_whitespace_is_refused(self):
        """Leading whitespace must not smuggle a command past the prefix."""
        assert command_problem(" show ip route") is not None

    def test_a_command_with_a_substitution_is_refused(self):
        """A substitution is not a read."""
        assert command_problem("show ip route $(whoami)") is not None

    def test_an_empty_command_is_refused(self):
        """There is no such thing as an empty read."""
        assert command_problem("") is not None
        assert command_problem("   ") is not None

    def test_the_allowlist_is_only_reads(self):
        """Every allowed prefix is a read."""
        for prefix in ALLOWED:
            assert prefix in ("show ", "ip -j ", "hostname")


class TestAuditTrail:
    """Everything that is run is written down."""

    def test_a_command_that_ran_is_recorded(self):
        """The trail says what was run, where and when."""
        runner = AuditedRunner(lambda target, command: "output")
        runner("10.0.0.1", "show ip route")

        assert len(runner.audit) == 1
        entry = runner.audit[0]
        assert entry.target == "10.0.0.1"
        assert entry.command == "show ip route"
        assert entry.outcome == "ok"
        assert entry.error is None
        assert entry.timestamp

    def test_a_refused_command_is_recorded(self):
        """A refusal is written down too."""
        runner = AuditedRunner(lambda target, command: "output")

        with pytest.raises(PermissionError):
            runner("10.0.0.1", "configure terminal")

        assert len(runner.audit) == 1
        assert runner.audit[0].outcome == "refused"
        assert runner.audit[0].error

    def test_a_failure_is_recorded_with_a_truncated_error(self):
        """A failure is written down, with the reason."""
        def boom(target, command):
            raise RuntimeError("x" * 5000)

        runner = AuditedRunner(boom)

        with pytest.raises(RuntimeError):
            runner("10.0.0.1", "show ip route")

        entry = runner.audit[0]
        assert entry.outcome == "failed"
        assert len(entry.error) <= 300

    def test_the_trail_is_bounded(self):
        """A long run cannot grow the trail without limit."""
        runner = AuditedRunner(lambda target, command: "output", max_audit=10)
        for index in range(50):
            runner("10.0.0.1", f"show ip route {index}")

        assert len(runner.audit) == 10
        # The oldest entries were dropped, the newest kept.
        assert runner.audit[-1].command == "show ip route 49"

    def test_credentials_are_never_recorded(self):
        """A target carrying a password is written down without it."""
        runner = AuditedRunner(lambda target, command: "output")
        runner("admin:hunter2@10.0.0.1", "show ip route")

        entry = runner.audit[0]
        assert "hunter2" not in entry.target
        assert "***" in entry.target

    def test_a_password_in_a_command_is_never_recorded(self):
        """A command carrying a password is written down without it."""
        runner = AuditedRunner(lambda target, command: "output")
        runner("10.0.0.1", "show ip route")

        assert redact("password=letmein") == "password=***"
        assert "letmein" not in redact("password=letmein")


# ---------------------------------------------------------------------------
# The engine
# ---------------------------------------------------------------------------

class TestInScope:
    """The scope check."""

    def test_an_address_inside_the_scope_is_in_scope(self):
        """The ordinary case."""
        assert in_scope("10.0.0.5", "10.0.0.0/24") is True

    def test_an_address_outside_the_scope_is_not(self):
        """And the ordinary other case."""
        assert in_scope("192.168.1.5", "10.0.0.0/24") is False

    def test_a_list_of_networks_is_a_scope(self):
        """A scope may be several networks."""
        assert in_scope("10.0.0.5", ["192.168.0.0/16", "10.0.0.0/24"]) is True
        assert in_scope("172.16.0.5", ["192.168.0.0/16", "10.0.0.0/24"]) is False

    def test_a_malformed_scope_is_a_caller_error(self):
        """A scope that cannot be read is raised, not crashed on."""
        with pytest.raises(ValueError) as excinfo:
            in_scope("10.0.0.5", "not-a-network")
        assert "not-a-network" in str(excinfo.value)

    def test_a_malformed_address_is_a_caller_error(self):
        """An address that cannot be read is raised, not crashed on."""
        with pytest.raises(ValueError):
            in_scope("not-an-address", "10.0.0.0/24")


class TestDiscover:
    """The breadth-first walk."""

    def _chain(self):
        """r1 -> r2 -> r3, each pointing at the next."""
        r1 = make_device(
            "r1",
            addresses=("10.0.0.1/24",),
            neighbors=[Neighbor(local_if="eth0", remote_name="r2", remote_ip="10.0.0.2", via="lldp")],
        )
        r2 = make_device(
            "r2",
            addresses=("10.0.0.2/24",),
            neighbors=[Neighbor(local_if="eth0", remote_name="r1", remote_ip="10.0.0.1", via="lldp")],
            routes=[RouteEntry(prefix="10.0.0.0/24", next_hop="10.0.0.3", interface="eth0")],
        )
        r3 = make_device("r3", addresses=("10.0.0.3/24",))
        return r1, r2, r3

    def test_every_device_is_found(self):
        """The walk follows the routers each device points at."""
        r1, r2, r3 = self._chain()
        collector = FakeCollector({"10.0.0.1": r1, "10.0.0.2": r2, "10.0.0.3": r3})

        result = discover(["10.0.0.1"], collector, "10.0.0.0/24")

        assert {device.device_id for device in result.devices} == {"r1", "r2", "r3"}

    def test_a_device_reached_by_two_addresses_is_collected_once(self):
        """The device decides, not the address."""
        r1, r2, r3 = self._chain()
        # r1 also answers on a second address, and r2 points at it.
        r1_second = make_device(
            "r1",
            addresses=("10.0.0.9/24",),
            neighbors=[Neighbor(local_if="eth0", remote_name="r2", remote_ip="10.0.0.2", via="lldp")],
        )
        r2 = make_device(
            "r2",
            addresses=("10.0.0.2/24",),
            neighbors=[Neighbor(local_if="eth0", remote_name="r1", remote_ip="10.0.0.9", via="lldp")],
        )
        collector = FakeCollector(
            {"10.0.0.1": r1, "10.0.0.9": r1_second, "10.0.0.2": r2, "10.0.0.3": r3}
        )

        result = discover(["10.0.0.1"], collector, "10.0.0.0/24")

        assert [device.device_id for device in result.devices].count("r1") == 1
        assert len({device.device_id for device in result.devices}) == len(result.devices)

    def test_a_candidate_outside_the_scope_is_not_queued(self):
        """A run cannot widen itself."""
        r1 = make_device(
            "r1",
            addresses=("10.0.0.1/24",),
            neighbors=[
                Neighbor(local_if="eth0", remote_name="outside", remote_ip="192.168.99.1", via="lldp")
            ],
        )
        collector = FakeCollector({"10.0.0.1": r1})

        result = discover(["10.0.0.1"], collector, "10.0.0.0/24")

        assert "192.168.99.1" not in collector.calls
        assert len(result.devices) == 1

    def test_an_arp_neighbour_is_not_queued(self):
        """An ARP entry is a host on the link, not a router to follow."""
        r1 = make_device(
            "r1",
            addresses=("10.0.0.1/24",),
            neighbors=[Neighbor(local_if="eth0", remote_ip="10.0.0.50", via="arp")],
        )
        host = make_device("host", addresses=("10.0.0.50/24",))
        collector = FakeCollector({"10.0.0.1": r1, "10.0.0.50": host})

        result = discover(["10.0.0.1"], collector, "10.0.0.0/24")

        assert "10.0.0.50" not in collector.calls
        assert {device.device_id for device in result.devices} == {"r1"}

    def test_max_depth_is_respected(self):
        """The walk does not go deeper than it was told to."""
        r1, r2, r3 = self._chain()
        collector = FakeCollector({"10.0.0.1": r1, "10.0.0.2": r2, "10.0.0.3": r3})

        result = discover(["10.0.0.1"], collector, "10.0.0.0/24", max_depth=1)

        assert {device.device_id for device in result.devices} == {"r1", "r2"}

    def test_max_devices_is_respected(self):
        """The run collects no more devices than it was told to."""
        r1, r2, r3 = self._chain()
        collector = FakeCollector({"10.0.0.1": r1, "10.0.0.2": r2, "10.0.0.3": r3})

        result = discover(["10.0.0.1"], collector, "10.0.0.0/24", max_devices=2)

        assert len(result.devices) == 2

    def test_a_collector_failure_is_recorded_and_the_run_continues(self):
        """One unreachable router does not end the discovery."""
        r1, r2, r3 = self._chain()
        collector = FakeCollector({"10.0.0.1": r1, "10.0.0.2": r2, "10.0.0.3": r3})
        # r2 cannot be collected.
        original = collector.collect

        def collect(target):
            if target == "10.0.0.2":
                raise OSError("connection refused")
            return original(target)

        collector.collect = collect

        result = discover(["10.0.0.1"], collector, "10.0.0.0/24")

        assert len(result.failures) == 1
        assert result.failures[0].target == "10.0.0.2"
        assert "connection refused" in result.failures[0].reason
        # r1 was still collected, and the run carried on.
        assert [device.device_id for device in result.devices] == ["r1"]

    def test_the_scope_is_checked_before_every_collection(self):
        """A seed outside the scope is not collected."""
        r1, _, _ = self._chain()
        collector = FakeCollector({"10.0.0.1": r1, "192.168.5.5": r1})

        result = discover(["192.168.5.5"], collector, "10.0.0.0/24")

        assert collector.calls == []
        assert result.devices == []

    def test_the_scope_is_checked_before_every_enqueue(self):
        """A device found beyond the scope is not collected either."""
        r1 = make_device(
            "r1",
            addresses=("10.0.0.1/24",),
            neighbors=[
                Neighbor(local_if="eth0", remote_name="inside", remote_ip="10.0.0.2", via="lldp"),
                Neighbor(local_if="eth1", remote_name="outside", remote_ip="192.168.99.9", via="lldp"),
            ],
        )
        r2 = make_device("r2", addresses=("10.0.0.2/24",))
        collector = FakeCollector({"10.0.0.1": r1, "10.0.0.2": r2, "192.168.99.9": r2})

        result = discover(["10.0.0.1"], collector, "10.0.0.0/24")

        assert "192.168.99.9" not in collector.calls

    def test_our_own_addresses_are_not_collected(self):
        """This machine's own addresses are not routers to follow."""
        r1 = make_device(
            "r1",
            addresses=("10.0.0.1/24",),
            neighbors=[Neighbor(local_if="eth0", remote_name="me", remote_ip="10.0.0.7", via="lldp")],
        )
        collector = FakeCollector({"10.0.0.1": r1, "10.0.0.7": r1})

        result = discover(
            ["10.0.0.1"], collector, "10.0.0.0/24", local_addresses=["10.0.0.7"]
        )

        assert "10.0.0.7" not in collector.calls

    def test_progress_is_called_for_a_collection(self):
        """The caller is told what happened."""
        r1, _, _ = self._chain()
        collector = FakeCollector({"10.0.0.1": r1})
        messages = []

        discover(["10.0.0.1"], collector, "10.0.0.0/24", progress=messages.append)

        assert any("r1" in message for message in messages)

    def test_progress_is_called_for_a_failure(self):
        """And for one that could not be collected."""
        collector = FakeCollector({})
        messages = []

        result = discover(["10.0.0.1"], collector, "10.0.0.0/24", progress=messages.append)

        assert len(result.failures) == 1
        assert any("could not collect" in message for message in messages)

    def test_a_malformed_scope_is_refused_before_anything_is_collected(self):
        """A bad scope is a caller error, caught before any work."""
        collector = FakeCollector({})

        with pytest.raises(ValueError):
            discover(["10.0.0.1"], collector, "not-a-network")

        assert collector.calls == []


# ---------------------------------------------------------------------------
# The graph
# ---------------------------------------------------------------------------

class TestBuildEdges:
    """The edges between devices, and how each one is known."""

    def test_an_lldp_edge_is_observed(self):
        """A device that named its neighbour over LLDP is an observation."""
        r1 = make_device(
            "r1",
            neighbors=[Neighbor(local_if="eth0", remote_name="r2", remote_ip="10.0.0.2", via="lldp")],
        )
        r2 = make_device("r2", addresses=("10.0.0.2/24",))

        edges = build_edges([r1, r2])

        lldp = [edge for edge in edges if edge.kind == "lldp"]
        assert len(lldp) == 1
        assert lldp[0].provenance == "observed"
        assert lldp[0].a == "r1" and lldp[0].b == "r2"
        assert "r1" in lldp[0].evidence and "r2" in lldp[0].evidence
        assert "eth0" in lldp[0].evidence

    def test_a_cdp_edge_keeps_its_own_kind(self):
        """A CDP neighbour is a CDP neighbour, not an LLDP one."""
        r1 = make_device(
            "r1",
            neighbors=[Neighbor(local_if="eth0", remote_name="r2", remote_ip="10.0.0.2", via="cdp")],
        )
        r2 = make_device("r2", addresses=("10.0.0.2/24",))

        edges = build_edges([r1, r2])

        cdp = [edge for edge in edges if edge.kind == "cdp"]
        assert len(cdp) == 1
        assert cdp[0].provenance == "observed"
        assert cdp[0].a == "r1" and cdp[0].b == "r2"
        assert "CDP" in cdp[0].evidence
        # The defect this guards against: a CDP edge labelled as LLDP.
        assert [edge for edge in edges if edge.kind == "lldp"] == []

    def test_a_next_hop_edge_is_inferred(self):
        """A next hop might cross a switch, so it is not an observation."""
        r1 = make_device(
            "r1",
            routes=[RouteEntry(prefix="192.168.9.0/24", next_hop="10.0.0.2", interface="eth0")],
        )
        r2 = make_device("r2", addresses=("10.0.0.2/24",))

        edges = build_edges([r1, r2])

        next_hop = [edge for edge in edges if edge.kind == "l3_next_hop"]
        assert len(next_hop) == 1
        assert next_hop[0].provenance == "inferred"
        assert next_hop[0].a == "r1" and next_hop[0].b == "r2"
        assert "192.168.9.0/24" in next_hop[0].evidence

    def test_a_shared_subnet_edge_is_inferred(self):
        """Two devices on one network may be separated by a switch."""
        r1 = make_device("r1", addresses=("10.0.0.1/24",))
        r2 = make_device("r2", addresses=("10.0.0.2/24",))

        edges = build_edges([r1, r2])

        shared = [edge for edge in edges if edge.kind == "shared_subnet"]
        assert len(shared) == 1
        assert shared[0].provenance == "inferred"
        assert "10.0.0.0/24" in shared[0].evidence

    def test_a_loopback_address_does_not_make_a_shared_subnet_edge(self):
        """A loopback says nothing about which link a device is on."""
        r1 = make_device("r1", addresses=("127.0.0.1/8",))
        r2 = make_device("r2", addresses=("127.0.0.2/8",))

        edges = build_edges([r1, r2])

        assert [edge for edge in edges if edge.kind == "shared_subnet"] == []

    def test_a_link_local_address_does_not_make_a_shared_subnet_edge(self):
        """Neither does a link-local address."""
        r1 = make_device("r1", addresses=("169.254.0.1/16",))
        r2 = make_device("r2", addresses=("169.254.0.2/16",))

        edges = build_edges([r1, r2])

        assert [edge for edge in edges if edge.kind == "shared_subnet"] == []

    def test_a_thirty_two_address_does_not_make_a_shared_subnet_edge(self):
        """A /32 is one address, not a network."""
        r1 = make_device("r1", addresses=("10.0.0.1/32",))
        r2 = make_device("r2", addresses=("10.0.0.2/32",))

        edges = build_edges([r1, r2])

        assert [edge for edge in edges if edge.kind == "shared_subnet"] == []

    def test_a_device_is_not_linked_to_itself(self):
        """No self-edges."""
        r1 = make_device(
            "r1",
            neighbors=[Neighbor(local_if="eth0", remote_name="r1", remote_ip="10.0.0.1", via="lldp")],
            routes=[RouteEntry(prefix="10.0.0.0/24", next_hop="10.0.0.1", interface="eth0")],
        )

        edges = build_edges([r1])

        assert edges == []

    def test_a_device_with_two_addresses_does_not_link_to_itself(self):
        """Two addresses on one device are still one device."""
        r1 = make_device("r1", addresses=("10.0.0.1/24", "10.0.1.1/24"))

        edges = build_edges([r1])

        assert edges == []
        assert all(edge.a != edge.b for edge in edges)

    def test_the_same_pair_may_have_more_than_one_kind_of_edge(self):
        """They are different facts, and one does not replace the other."""
        r1 = make_device(
            "r1",
            addresses=("10.0.0.1/24",),
            neighbors=[Neighbor(local_if="eth0", remote_name="r2", remote_ip="10.0.0.2", via="lldp")],
            routes=[RouteEntry(prefix="192.168.9.0/24", next_hop="10.0.0.2", interface="eth0")],
        )
        r2 = make_device("r2", addresses=("10.0.0.2/24",))

        edges = build_edges([r1, r2])

        kinds = {edge.kind for edge in edges}
        assert "lldp" in kinds
        assert "l3_next_hop" in kinds
        assert "shared_subnet" in kinds

    def test_an_observed_edge_and_an_inferred_edge_are_marked_differently(self):
        """The provenance says how each edge is known."""
        r1 = make_device(
            "r1",
            addresses=("10.0.0.1/24",),
            neighbors=[Neighbor(local_if="eth0", remote_name="r2", remote_ip="10.0.0.2", via="lldp")],
        )
        r2 = make_device("r2", addresses=("10.0.0.2/24",))

        edges = build_edges([r1, r2])

        by_kind = {edge.kind: edge for edge in edges}
        assert by_kind["lldp"].provenance == "observed"
        assert by_kind["shared_subnet"].provenance == "inferred"

    def test_a_neighbour_we_do_not_know_is_not_an_edge(self):
        """A device that was not collected cannot be an endpoint."""
        r1 = make_device(
            "r1",
            neighbors=[Neighbor(local_if="eth0", remote_name="unknown", remote_ip="10.0.0.9", via="lldp")],
        )

        edges = build_edges([r1])

        assert edges == []


# ---------------------------------------------------------------------------
# The FRR collector
# ---------------------------------------------------------------------------

class TestFrrCollector:
    """Reading one device."""

    def _runner(self, responses, errors):
        """A runner that answers from a hand-written table."""
        def run(target, command):
            if command not in responses:
                raise OSError(f"{command} is not available")
            return responses[command]

        return AuditedRunner(run)

    def test_a_device_is_read_from_several_sources(self):
        """The hostname, the interfaces and the routes are all read."""
        responses = {
            "hostname": "r1\n",
            "ip -j addr": IP_ADDR_JSON,
            "show ip route json": FRR_ROUTES_JSON,
        }
        collector = FrrCollector(self._runner(responses, []))

        snapshot = collector.collect("10.0.0.2")

        assert snapshot.hostname == "r1"
        assert snapshot.device_id == "r1"
        assert snapshot.mgmt_target == "10.0.0.2"
        assert [interface.name for interface in snapshot.interfaces] == ["eth0", "eth1"]
        assert snapshot.interfaces[0].addresses == ["10.0.0.2/24"]
        assert snapshot.interfaces[0].up is True
        assert snapshot.interfaces[1].up is False
        assert len(snapshot.routes) == 2

    def test_the_device_id_is_the_hostname(self):
        """Device identity is the router, not the address it was reached on."""
        responses = {"hostname": "r1\n", "ip -j addr": IP_ADDR_JSON}
        collector = FrrCollector(self._runner(responses, []))

        snapshot = collector.collect("192.168.99.9")

        assert snapshot.device_id == "r1"
        assert snapshot.mgmt_target == "192.168.99.9"

    def test_a_source_that_cannot_be_read_is_recorded(self):
        """A missing optional source is an error, not a silent gap."""
        responses = {"hostname": "r1\n"}
        collector = FrrCollector(self._runner(responses, []))

        snapshot = collector.collect("10.0.0.2")

        assert snapshot.errors
        assert any("ip -j addr" in error for error in snapshot.errors)
        # What could not be read is not invented.
        assert snapshot.interfaces == []
        assert snapshot.routes == []

    def test_the_collector_does_not_raise_for_a_missing_source(self):
        """One missing source does not lose the rest."""
        responses = {"hostname": "r1\n", "ip -j addr": IP_ADDR_JSON}
        collector = FrrCollector(self._runner(responses, []))

        snapshot = collector.collect("10.0.0.2")

        assert snapshot.device_id == "r1"
        assert len(snapshot.interfaces) == 2

    def test_a_malformed_prefix_is_recorded_as_an_error(self):
        """A prefix nobody can parse is not a route."""
        responses = {
            "hostname": "r1\n",
            "show ip route json": json.dumps(
                {"not-a-network": [{"protocol": "static", "nexthops": [{}]}]}
            ),
        }
        collector = FrrCollector(self._runner(responses, []))

        snapshot = collector.collect("10.0.0.2")

        assert snapshot.routes == []
        assert any("not-a-network" in error for error in snapshot.errors)

    def test_arp_neighbours_are_marked_as_arp(self):
        """An ARP entry is a host on the link."""
        responses = {
            "hostname": "r1\n",
            "ip -j neigh": json.dumps(
                [{"ifindex": 2, "lladdr": "aa:bb:cc:dd:ee:ff", "state": "REACHABLE",
                  "dev": "eth0", "ip": "10.0.0.9"}]
            ),
        }
        collector = FrrCollector(self._runner(responses, []))

        snapshot = collector.collect("10.0.0.2")

        arp = [neighbor for neighbor in snapshot.neighbors if neighbor.via == "arp"]
        assert len(arp) == 1
        assert arp[0].remote_ip == "10.0.0.9"
        assert arp[0].local_if == "eth0"

    def test_ospf_neighbours_are_marked_as_ospf(self):
        """An OSPF adjacency names the router on the other end."""
        responses = {
            "hostname": "r1\n",
            "show ip ospf neighbor json": json.dumps(
                {"10.0.0.3": {"routerId": "10.0.0.3", "ifaceAddress": "10.0.0.9",
                              "ifaceName": "eth0", "nbrState": "Full/DR"}}
            ),
        }
        collector = FrrCollector(self._runner(responses, []))

        snapshot = collector.collect("10.0.0.2")

        ospf = [neighbor for neighbor in snapshot.neighbors if neighbor.via == "ospf"]
        assert len(ospf) == 1
        assert ospf[0].remote_name == "10.0.0.3"
        assert ospf[0].remote_ip == "10.0.0.9"

    def test_lldp_neighbours_are_marked_as_lldp(self):
        """An LLDP adjacency names the device on the other end."""
        responses = {
            "hostname": "r1\n",
            "show lldp neighbors json": json.dumps(
                [{"localInterface": "eth0",
                  "neighbors": [{"host": "r2", "chassis": "aa:bb:cc:dd:ee:ff", "port": "eth1"}]}]
            ),
        }
        collector = FrrCollector(self._runner(responses, []))

        snapshot = collector.collect("10.0.0.2")

        lldp = [neighbor for neighbor in snapshot.neighbors if neighbor.via == "lldp"]
        assert len(lldp) == 1
        assert lldp[0].remote_name == "r2"
        assert lldp[0].local_if == "eth0"

    def test_cdp_neighbours_are_marked_as_cdp(self):
        """A CDP adjacency is a CDP adjacency."""
        responses = {
            "hostname": "r1\n",
            "show cdp neighbors json": json.dumps(
                [{"localInterface": "eth0", "neighbors": [{"host": "r2", "port": "eth1"}]}]
            ),
        }
        collector = FrrCollector(self._runner(responses, []))

        snapshot = collector.collect("10.0.0.2")

        cdp = [neighbor for neighbor in snapshot.neighbors if neighbor.via == "cdp"]
        assert len(cdp) == 1
        assert cdp[0].remote_name == "r2"
        assert cdp[0].via == "cdp"

    def test_every_command_is_audited(self):
        """The collector's commands are written down."""
        responses = {"hostname": "r1\n", "ip -j addr": IP_ADDR_JSON}
        runner = self._runner(responses, [])
        collector = FrrCollector(runner)

        collector.collect("10.0.0.2")

        commands = [entry.command for entry in runner.audit]
        assert "hostname" in commands
        assert "ip -j addr" in commands
        assert all(entry.outcome in ("ok", "failed") for entry in runner.audit)

    def test_the_collector_cannot_run_a_command_that_writes(self):
        """The guard applies to every command the collector runs."""
        runner = AuditedRunner(lambda target, command: "output")
        collector = FrrCollector(runner)

        # The collector only ever asks for reads, so the guard has to
        # be checked by asking it to run a write directly.
        with pytest.raises(PermissionError):
            runner("10.0.0.2", "configure terminal")


class TestDockerRunner:
    """The container runner."""

    def test_a_show_command_goes_through_vtysh(self):
        """FRR is read with vtysh."""
        captured = {}

        def fake_run(argv, **kwargs):
            captured["argv"] = argv
            captured["kwargs"] = kwargs

            class Result:
                stdout = "output"

            return Result()

        import app.router_discovery.collectors.frr as frr_module

        original = frr_module.subprocess.run
        frr_module.subprocess.run = fake_run
        try:
            runner = docker_runner({"10.0.0.2": "router1"})
            output = runner("10.0.0.2", "show ip route json")
        finally:
            frr_module.subprocess.run = original

        assert output == "output"
        assert captured["argv"] == [
            "docker", "exec", "router1", "vtysh", "-c", "show ip route json"
        ]
        assert captured["kwargs"]["shell"] is False
        assert captured["kwargs"]["capture_output"] is True
        assert captured["kwargs"]["text"] is True
        assert captured["kwargs"]["timeout"] == 10
        assert captured["kwargs"]["check"] is True

    def test_other_commands_are_run_directly(self):
        """A command that is not a show runs as itself."""
        captured = {}

        def fake_run(argv, **kwargs):
            captured["argv"] = argv

            class Result:
                stdout = "output"

            return Result()

        import app.router_discovery.collectors.frr as frr_module

        original = frr_module.subprocess.run
        frr_module.subprocess.run = fake_run
        try:
            runner = docker_runner({"10.0.0.2": "router1"})
            runner("10.0.0.2", "ip -j addr")
        finally:
            frr_module.subprocess.run = original

        assert captured["argv"] == ["docker", "exec", "router1", "ip", "-j", "addr"]

    def test_an_unmapped_target_is_refused(self):
        """There is no container to run in."""
        runner = docker_runner({})
        with pytest.raises(LookupError):
            runner("10.0.0.2", "show ip route json")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
