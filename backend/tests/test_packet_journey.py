"""
Tests for the packet journey trace.

The trace walks a packet from its source to its destination, one
forwarding decision at a time. Each decision is made by the router that
is holding the packet at that moment, so every router must use its own
routing table. These tests pin that down: a router that forwards using
somebody else's table is the bug that made every journey through a
gateway end in a false "loop".

The fixtures are small, explicit tables, so each test can say exactly
which route should be chosen at each hop and why.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routing import NextHopType, Provenance, RoutingEntry
from app.routing_logic import trace_packet_path

try:
    from app.routing_logic import MAX_HOPS
except ImportError:  # pragma: no cover - the limit had no name before
    MAX_HOPS = 30


def route(
    destination: str,
    next_hop: str = None,
    interface: str = "eth0",
    metric: int = 10,
    next_hop_type: NextHopType = NextHopType.GATEWAY,
) -> RoutingEntry:
    """A routing entry for a test table."""
    return RoutingEntry(
        destination=destination,
        next_hop=next_hop,
        interface=interface,
        metric=metric,
        next_hop_type=next_hop_type,
        provenance=Provenance.SIMULATED,
    )


# ---------------------------------------------------------------------------
# Fixtures
#
# A two-router network:
#
#   host 192.168.10.2  --  Router A 192.168.10.1  --  Router B 192.168.20.1
#                                                          |
#                                                   server 192.168.20.2
#
# Router A's table and Router B's table are deliberately different, so a
# trace that reuses one table for both is caught.
# ---------------------------------------------------------------------------

ROUTER_A_TABLE = [
    route("192.168.10.0/24", None, "eth0", 1, NextHopType.DIRECT),
    route("192.168.20.0/24", "192.168.20.1", "eth1", 10),
]

ROUTER_B_TABLE = [
    route("192.168.20.0/24", None, "eth0", 1, NextHopType.DIRECT),
    route("192.168.10.0/24", "192.168.10.1", "eth1", 10),
]

TWO_ROUTER_TABLES = {
    "192.168.20.1": ROUTER_B_TABLE,
}


class TestDirectlyConnectedDestination:
    """A destination on a network the router is attached to."""

    def test_the_packet_is_delivered_in_one_hop(self):
        """A direct route needs no second router."""
        hops = trace_packet_path("192.168.10.2", "192.168.10.50", ROUTER_A_TABLE)

        assert len(hops) == 1
        assert hops[0].action == "deliver"
        assert hops[0].matched_route_destination == "192.168.10.0/24"
        assert hops[0].matched_route_interface == "eth0"
        assert hops[0].matched_route_next_hop is None
        assert hops[0].next_hop_ip is None
        assert hops[0].egress_interface == "eth0"

    def test_the_hop_is_numbered_one(self):
        """The first hop is hop 1."""
        hops = trace_packet_path("192.168.10.2", "192.168.10.50", ROUTER_A_TABLE)
        assert hops[0].hop_number == 1

    def test_the_explanation_names_the_network_and_interface(self):
        """The student is told which network and which interface."""
        hops = trace_packet_path("192.168.10.2", "192.168.10.50", ROUTER_A_TABLE)
        assert "192.168.10.0/24" in hops[0].explanation
        assert "eth0" in hops[0].explanation


class TestDestinationThroughOneGateway:
    """A destination reached by handing the packet to a gateway."""

    def test_the_gateway_hop_records_the_route_it_matched(self):
        """The forwarding hop names the route that was selected."""
        hops = trace_packet_path("192.168.10.2", "192.168.20.2", ROUTER_A_TABLE)

        assert hops[0].action == "forward"
        assert hops[0].matched_route_destination == "192.168.20.0/24"
        assert hops[0].matched_route_next_hop == "192.168.20.1"
        assert hops[0].matched_route_interface == "eth1"
        assert hops[0].matched_route_metric == 10
        assert hops[0].next_hop_ip == "192.168.20.1"
        assert hops[0].egress_interface == "eth1"

    def test_the_next_router_is_told_which_table_to_use(self):
        """
        The next hop uses its own table, not the first router's.

        This is the heart of the fix. Router B's table sends the packet
        on to 192.168.20.2 directly, while Router A's table would have
        sent it back to 192.168.20.1. Reusing Router A's table would
        produce a router forwarding to itself.
        """
        hops = trace_packet_path(
            "192.168.10.2",
            "192.168.20.2",
            ROUTER_A_TABLE,
            router_tables=TWO_ROUTER_TABLES,
        )

        assert len(hops) == 2
        assert hops[1].action == "deliver"
        assert hops[1].matched_route_destination == "192.168.20.0/24"
        assert hops[1].matched_route_next_hop is None
        assert hops[1].egress_interface == "eth0"

    def test_the_second_hop_is_numbered_two(self):
        """Hops are numbered in order."""
        hops = trace_packet_path(
            "192.168.10.2",
            "192.168.20.2",
            ROUTER_A_TABLE,
            router_tables=TWO_ROUTER_TABLES,
        )
        assert [h.hop_number for h in hops] == [1, 2]

    def test_a_router_with_no_table_stops_the_journey_without_claiming_a_loop(self):
        """
        With only one table, the journey stops honestly.

        The packet was handed to the gateway. We cannot say what the
        gateway would do next, so we say that, rather than inventing a
        loop by re-using the first router's table.
        """
        hops = trace_packet_path("192.168.10.2", "192.168.20.2", ROUTER_A_TABLE)

        assert len(hops) == 2
        assert hops[0].action == "forward"
        assert hops[1].action == "unresolved_next_hop"
        assert not any(h.action == "loop" for h in hops)
        assert "192.168.20.1" in hops[1].explanation

    def test_a_gateway_that_is_the_destination_delivers(self):
        """When the next hop is the destination, the packet arrives."""
        table = [route("192.168.20.0/24", "192.168.20.2", "eth1", 10)]
        hops = trace_packet_path("192.168.10.2", "192.168.20.2", table)

        assert len(hops) == 2
        assert hops[0].action == "forward"
        assert hops[0].next_hop_ip == "192.168.20.2"
        assert hops[1].action == "deliver"
        assert hops[1].hop_number == 2


class TestMultiRouterForwarding:
    """A path that crosses more than one router."""

    def test_each_hop_uses_the_table_of_the_router_it_is_at(self):
        """
        Three routers, three tables, one path.

        Router A sends to Router B, Router B sends to Router C, and
        Router C delivers. Each hop must show the route from that
        router's own table.
        """
        table_a = [route("10.0.0.0/24", "10.0.0.2", "eth0", 10)]
        table_b = [route("10.0.0.0/24", "10.0.0.3", "eth0", 20)]
        table_c = [route("10.0.0.0/24", None, "eth0", 1, NextHopType.DIRECT)]

        hops = trace_packet_path(
            "192.168.1.10",
            "10.0.0.9",
            table_a,
            router_tables={"10.0.0.2": table_b, "10.0.0.3": table_c},
        )

        assert [h.action for h in hops] == ["forward", "forward", "deliver"]
        assert [h.matched_route_metric for h in hops] == [10, 20, 1]
        assert [h.matched_route_next_hop for h in hops] == ["10.0.0.2", "10.0.0.3", None]
        assert [h.next_hop_ip for h in hops] == ["10.0.0.2", "10.0.0.3", None]
        assert [h.hop_number for h in hops] == [1, 2, 3]

    def test_a_router_never_forwards_using_another_routers_table(self):
        """
        The first router's table must not be reused at the second hop.

        Router A's table sends to 10.0.0.2. If the trace wrongly re-used
        it at Router B, the packet would go to 10.0.0.2 again and the
        second hop would show the same metric as the first.
        """
        table_a = [route("10.0.0.0/24", "10.0.0.2", "eth0", 10)]
        table_b = [route("10.0.0.0/24", "10.0.0.3", "eth0", 99)]

        hops = trace_packet_path(
            "192.168.1.10",
            "10.0.0.9",
            table_a,
            router_tables={"10.0.0.2": table_b},
        )

        assert hops[0].matched_route_metric == 10
        assert hops[1].matched_route_metric == 99
        assert hops[1].matched_route_next_hop == "10.0.0.3"

    def test_longest_prefix_still_decides_at_each_hop(self):
        """The prefix and metric rules are unchanged, at every hop."""
        table_a = [
            route("10.0.0.0/8", "10.0.0.2", "eth0", 5),
            route("10.1.0.0/16", "10.0.0.3", "eth0", 50),
        ]
        table_b = [route("10.1.0.0/16", None, "eth0", 1, NextHopType.DIRECT)]

        hops = trace_packet_path(
            "192.168.1.10",
            "10.1.2.3",
            table_a,
            router_tables={"10.0.0.3": table_b},
        )

        # The /16 is more specific than the /8, so it wins despite the
        # higher metric.
        assert hops[0].matched_route_destination == "10.1.0.0/16"
        assert hops[0].next_hop_ip == "10.0.0.3"
        assert hops[1].action == "deliver"


class TestNoMatchingRoute:
    """A router with no route to the destination."""

    def test_the_packet_is_dropped(self):
        """No route means the packet has nowhere to go."""
        table = [route("10.0.0.0/8", "10.0.0.2", "eth0", 10)]
        hops = trace_packet_path("192.168.1.10", "192.168.2.50", table)

        assert len(hops) == 1
        assert hops[0].action == "drop"
        assert "192.168.2.50" in hops[0].explanation

    def test_the_drop_is_distinct_from_an_unresolved_next_hop(self):
        """
        "No route" and "unresolved next hop" are different outcomes.

        A drop means the packet was discarded. An unresolved next hop
        means the packet was handed over successfully and the journey
        simply cannot be followed further.
        """
        table = [route("10.0.0.0/8", "10.0.0.2", "eth0", 10)]

        no_route = trace_packet_path("192.168.1.10", "192.168.2.50", table)
        unresolved = trace_packet_path("192.168.1.10", "10.0.0.9", table)

        assert no_route[0].action == "drop"
        assert unresolved[-1].action == "unresolved_next_hop"
        assert no_route[0].action != unresolved[-1].action

    def test_a_router_without_a_route_drops_the_packet_it_holds(self):
        """The second router's own table decides, and it has no route."""
        table_a = [route("10.0.0.0/8", "10.0.0.2", "eth0", 10)]
        table_b = [route("192.168.99.0/24", "192.168.99.1", "eth9", 5)]

        hops = trace_packet_path(
            "192.168.1.10",
            "10.0.0.9",
            table_a,
            router_tables={"10.0.0.2": table_b},
        )

        assert [h.action for h in hops] == ["forward", "drop"]
        assert "10.0.0.9" in hops[1].explanation

    def test_a_broken_table_is_not_reported_as_no_route(self):
        """
        A table the engine cannot read is a different problem.

        The distinction matters: "no route" means the packet was
        dropped, while a broken table means no routing decision could be
        made at all.
        """
        broken = [route("10.0.0.0/8", "10.0.0.2", "eth0", 10)]
        # Slip a bad entry past the model, the way a table assembled
        # from an external source might be.
        broken[0].destination = "not-a-network"

        hops = trace_packet_path("192.168.1.10", "10.0.0.9", broken)

        assert len(hops) == 1
        assert hops[0].action == "error"
        assert hops[0].action != "drop"
        assert "10.0.0.2" in hops[0].explanation or "routing decision" in hops[0].explanation


class TestForwardingLoop:
    """A genuine forwarding loop."""

    def test_a_loop_is_detected(self):
        """Router A sends to B, B sends back to A, and round it goes."""
        table_a = [route("10.0.0.0/8", "10.0.0.2", "eth0", 10)]
        table_b = [route("10.0.0.0/8", "10.0.0.1", "eth0", 10)]

        hops = trace_packet_path(
            "192.168.1.10",
            "10.0.0.9",
            table_a,
            router_tables={"10.0.0.2": table_b, "10.0.0.1": table_a},
        )

        # A forwards to B, B forwards to A, A forwards to B again, and the
        # packet is back where it has already been.
        assert [h.action for h in hops] == ["forward", "forward", "forward", "loop"]
        assert hops[-1].action == "loop"
        assert "10.0.0.2" in hops[-1].explanation
        assert len(hops) == 4

    def test_a_loop_is_not_reported_when_the_table_is_reused(self):
        """
        The old behaviour called this a loop when it was not one.

        With a single table, the second hop is a router we know nothing
        about, so the journey stops there. It is not a loop, because no
        router forwarded the packet to itself.
        """
        table_a = [route("10.0.0.0/8", "10.0.0.2", "eth0", 10)]

        hops = trace_packet_path("192.168.1.10", "10.0.0.9", table_a)

        assert not any(h.action == "loop" for h in hops)
        assert hops[-1].action == "unresolved_next_hop"

    def test_a_loop_is_still_detected_with_the_real_tables(self):
        """The loop check still works when real tables are supplied."""
        table_a = [route("10.0.0.0/8", "10.0.0.2", "eth0", 10)]
        table_b = [route("10.0.0.0/8", "10.0.0.2", "eth0", 10)]

        # Router B sends the packet back to itself: 10.0.0.2.
        hops = trace_packet_path(
            "192.168.1.10",
            "10.0.0.9",
            table_a,
            router_tables={"10.0.0.2": table_b},
        )

        assert hops[-1].action == "loop"
        assert "10.0.0.2" in hops[-1].explanation


class TestUnresolvableNextHop:
    """A next hop we cannot follow."""

    def test_the_journey_stops_at_the_unknown_router(self):
        """The packet was handed over; the journey cannot be followed."""
        table = [route("10.0.0.0/8", "10.0.0.2", "eth0", 10)]
        hops = trace_packet_path("192.168.1.10", "10.0.0.9", table)

        assert len(hops) == 2
        assert hops[0].action == "forward"
        assert hops[0].next_hop_ip == "10.0.0.2"
        assert hops[1].action == "unresolved_next_hop"
        assert hops[1].current_device == "Router B"

    def test_the_forwarding_hop_is_still_recorded_before_it_stops(self):
        """The route that was matched is not lost."""
        table = [route("10.0.0.0/8", "10.0.0.2", "eth0", 10)]
        hops = trace_packet_path("192.168.1.10", "10.0.0.9", table)

        assert hops[0].matched_route_destination == "10.0.0.0/8"
        assert hops[0].matched_route_next_hop == "10.0.0.2"
        assert hops[0].matched_route_interface == "eth0"
        assert hops[0].matched_route_metric == 10

    def test_it_is_not_reported_as_a_drop(self):
        """The packet was not discarded; it was handed to another router."""
        table = [route("10.0.0.0/8", "10.0.0.2", "eth0", 10)]
        hops = trace_packet_path("192.168.1.10", "10.0.0.9", table)

        assert hops[-1].action != "drop"
        assert hops[-1].action != "loop"
        assert hops[-1].action != "error"


class TestAddressFamilyMismatch:
    """A packet cannot change address family on its own."""

    def test_an_ipv4_source_with_an_ipv6_destination_is_rejected(self):
        """The two ends must be in the same family."""
        table = [route("10.0.0.0/8", "10.0.0.2", "eth0", 10)]
        hops = trace_packet_path("192.168.1.10", "2001:db8::1", table)

        assert len(hops) == 1
        assert hops[0].action == "error"
        assert "IPv4" in hops[0].explanation
        assert "IPv6" in hops[0].explanation

    def test_an_ipv6_source_with_an_ipv4_destination_is_rejected(self):
        """The other way round is refused as well."""
        table = [route("10.0.0.0/8", "10.0.0.2", "eth0", 10)]
        hops = trace_packet_path("2001:db8::1", "192.168.1.50", table)

        assert len(hops) == 1
        assert hops[0].action == "error"
        assert "IPv6" in hops[0].explanation
        assert "IPv4" in hops[0].explanation

    def test_the_mismatch_is_not_reported_as_a_loop_or_a_drop(self):
        """It is a rejected request, not a routing outcome."""
        table = [route("10.0.0.0/8", "10.0.0.2", "eth0", 10)]
        hops = trace_packet_path("192.168.1.10", "2001:db8::1", table)

        assert hops[0].action not in ("loop", "drop", "forward", "deliver")

    def test_an_ipv6_journey_with_matching_families_still_works(self):
        """IPv6 is not broken by the check."""
        table_a = [route("2001:db8:20::/64", "2001:db8:20::1", "eth1", 10)]
        table_b = [route("2001:db8:20::/64", None, "eth0", 1, NextHopType.DIRECT)]

        hops = trace_packet_path(
            "2001:db8:10::2",
            "2001:db8:20::9",
            table_a,
            router_tables={"2001:db8:20::1": table_b},
        )

        assert [h.action for h in hops] == ["forward", "deliver"]
        assert hops[0].next_hop_ip == "2001:db8:20::1"
        assert hops[1].matched_route_destination == "2001:db8:20::/64"


class TestHopLimit:
    """The hop limit is still respected."""

    def test_a_path_longer_than_the_limit_is_cut_off(self):
        """A long chain of routers stops at the hop limit."""
        # A chain of routers, each sending to the next. The destination
        # is deliberately not on the chain, so the packet cannot be
        # delivered before the limit runs out.
        tables = {
            f"10.0.0.{index + 2}": [
                route("10.0.0.0/8", f"10.0.0.{index + 3}", "eth0", 10)
            ]
            for index in range(MAX_HOPS + 10)
        }

        hops = trace_packet_path(
            "192.168.1.10",
            "10.99.99.99",
            [route("10.0.0.0/8", "10.0.0.2", "eth0", 10)],
            router_tables=tables,
        )

        assert hops[-1].action == "drop"
        assert "Maximum hop count" in hops[-1].explanation
        assert not any(h.action == "deliver" for h in hops)
        assert len(hops) == MAX_HOPS + 2

    def test_the_limit_is_thirty_hops(self):
        """The documented limit has not changed."""
        assert MAX_HOPS == 30

    def test_a_path_within_the_limit_is_not_cut_off(self):
        """A short path is not affected by the limit."""
        table_a = [route("10.0.0.0/8", "10.0.0.2", "eth0", 10)]
        table_b = [route("10.0.0.0/8", None, "eth0", 1, NextHopType.DIRECT)]

        hops = trace_packet_path(
            "192.168.1.10",
            "10.0.0.9",
            table_a,
            router_tables={"10.0.0.2": table_b},
        )

        assert hops[-1].action == "deliver"
        assert not any("Maximum hop count" in h.explanation for h in hops)


class TestDeliveryVersusFindingARoute:
    """Finding a route is not the same as the packet arriving."""

    def test_a_matched_route_alone_is_not_a_delivery(self):
        """
        The forward hop is a decision, not an arrival.

        This is the distinction the interface has to keep: hop 1 found a
        route and handed the packet over, but nothing has been delivered.
        """
        table = [route("10.0.0.0/8", "10.0.0.2", "eth0", 10)]
        hops = trace_packet_path("192.168.1.10", "10.0.0.9", table)

        assert hops[0].action == "forward"
        assert hops[0].matched_route_destination == "10.0.0.0/24" or (
            hops[0].matched_route_destination == "10.0.0.0/8"
        )
        assert not any(h.action == "deliver" for h in hops)

    def test_a_delivery_is_reported_only_when_the_packet_arrives(self):
        """The deliver hop is the one that says the packet arrived."""
        table_a = [route("10.0.0.0/8", "10.0.0.2", "eth0", 10)]
        table_b = [route("10.0.0.0/8", None, "eth0", 1, NextHopType.DIRECT)]

        hops = trace_packet_path(
            "192.168.1.10",
            "10.0.0.9",
            table_a,
            router_tables={"10.0.0.2": table_b},
        )

        assert [h.action for h in hops] == ["forward", "deliver"]
        assert hops[-1].action == "deliver"

    def test_the_source_being_the_destination_is_a_delivery(self):
        """A packet to itself does not go anywhere."""
        hops = trace_packet_path("192.168.1.10", "192.168.1.10", ROUTER_A_TABLE)

        assert len(hops) == 1
        assert hops[0].action == "deliver"


class TestInvalidInput:
    """Bad input is reported, not guessed at."""

    def test_an_invalid_source_address_is_rejected(self):
        """A source that is not an address is refused."""
        hops = trace_packet_path("not-an-ip", "10.0.0.9", ROUTER_A_TABLE)

        assert len(hops) == 1
        assert hops[0].action == "error"
        assert "Invalid source IP address" in hops[0].explanation

    def test_an_invalid_destination_address_is_rejected(self):
        """A destination that is not an address is refused."""
        hops = trace_packet_path("192.168.1.10", "not-an-ip", ROUTER_A_TABLE)

        assert len(hops) == 1
        assert hops[0].action == "error"
        assert "Invalid destination IP address" in hops[0].explanation


class TestShippedSampleTable:
    """
    The table the application actually ships with.

    These are the inputs the interface sends: the source is fixed and the
    destination is the network address of the route that was matched.
    """

    def test_the_journey_no_longer_reports_a_false_loop(self):
        """
        The case that was broken.

        The whole table belonged to one router. Using it again at the
        next hop made the router forward to itself, and the trace
        claimed a loop. It now stops with an honest reason instead.
        """
        from app.routing import SAMPLE_ROUTES

        hops = trace_packet_path("192.168.1.10", "192.168.1.0", SAMPLE_ROUTES)

        assert not any(h.action == "loop" for h in hops)
        assert hops[0].action == "forward"
        assert hops[0].matched_route_destination == "192.168.1.0/25"
        assert hops[0].matched_route_next_hop == "10.0.0.2"
        assert hops[0].matched_route_interface == "eth1"
        assert hops[0].matched_route_metric == 20
        assert hops[-1].action == "unresolved_next_hop"

    def test_the_first_hop_still_uses_longest_prefix_matching(self):
        """The route chosen at the first hop has not changed."""
        from app.routing import SAMPLE_ROUTES

        hops = trace_packet_path("192.168.1.10", "192.168.1.0", SAMPLE_ROUTES)
        assert hops[0].matched_route_destination == "192.168.1.0/25"

    def test_a_directly_connected_destination_is_delivered(self):
        """10.0.0.0/8 is direct, so the packet arrives at the first hop."""
        from app.routing import SAMPLE_ROUTES

        hops = trace_packet_path("192.168.1.10", "10.5.5.5", SAMPLE_ROUTES)

        assert len(hops) == 1
        assert hops[0].action == "deliver"
        assert hops[0].matched_route_destination == "10.0.0.0/8"
        assert hops[0].matched_route_interface == "eth2"


class TestPacketJourneyEndpoint:
    """
    The HTTP endpoint, not just the function.

    The false loop survived for so long because nothing tested the
    endpoint itself. These tests go through the API so the contract is
    protected, not just the algorithm behind it.
    """

    @pytest.fixture
    def client(self):
        """A test client for the application."""
        return TestClient(app)

    def test_a_gateway_destination_no_longer_reports_a_false_loop(self, client):
        """
        The case that used to be broken, through the API.

        A journey through a gateway used to end in a loop, because the
        second hop reused the first router's table.
        """
        response = client.post(
            "/packet-journey",
            json={"source_ip": "192.168.1.10", "destination_ip": "192.168.1.0"},
        )

        assert response.status_code == 200
        data = response.json()

        actions = [hop["action"] for hop in data["hops"]]
        assert "loop" not in actions
        assert actions == ["forward", "unresolved_next_hop"]

        first = data["hops"][0]
        assert first["hop_number"] == 1
        assert first["current_device"] == "Device(192.168.1.10)"
        assert first["destination_ip"] == "192.168.1.0"
        assert first["matched_route"] == {
            "destination": "192.168.1.0/25",
            "next_hop": "10.0.0.2",
            "interface": "eth1",
            "metric": 20,
        }
        assert first["next_hop_ip"] == "10.0.0.2"
        assert first["egress_interface"] == "eth1"

        second = data["hops"][1]
        assert second["hop_number"] == 2
        assert second["action"] == "unresolved_next_hop"
        assert "10.0.0.2" in second["explanation"]
        # A hop that matched no route has no route to report.
        assert "matched_route" not in second
        assert "next_hop_ip" not in second
        assert "egress_interface" not in second

    def test_a_directly_connected_destination_is_delivered(self, client):
        """A destination on a connected network arrives at the first hop."""
        response = client.post(
            "/packet-journey",
            json={"source_ip": "192.168.1.10", "destination_ip": "10.5.5.5"},
        )

        assert response.status_code == 200
        data = response.json()

        assert data["success"] is True
        assert data["error"] is None
        assert [hop["action"] for hop in data["hops"]] == ["deliver"]
        assert data["hops"][0]["matched_route"]["destination"] == "10.0.0.0/8"
        assert data["hops"][0]["matched_route"]["interface"] == "eth2"

    def test_a_cross_family_destination_is_rejected(self, client):
        """The endpoint refuses an address it cannot use."""
        response = client.post(
            "/packet-journey",
            json={"source_ip": "192.168.1.10", "destination_ip": "2001:db8::1"},
        )

        assert response.status_code == 400
        assert "Invalid IP address" in response.json()["detail"]

    def test_the_response_carries_the_addresses_not_the_device_names(self, client):
        """source_ip is an address, not a label such as Device(192.168.1.10)."""
        response = client.post(
            "/packet-journey",
            json={"source_ip": "192.168.1.10", "destination_ip": "192.168.1.0"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["source_ip"] == "192.168.1.10"
        assert data["destination_ip"] == "192.168.1.0"

    def test_the_response_says_how_it_was_worked_out(self, client):
        """The journey is calculated from a table, and says so."""
        response = client.post(
            "/packet-journey",
            json={"source_ip": "192.168.1.10", "destination_ip": "10.5.5.5"},
        )

        assert response.status_code == 200
        assert response.json()["provenance"] == "simulated"

    def test_the_error_field_explains_why_the_journey_stopped(self, client):
        """A journey that did not arrive says why."""
        response = client.post(
            "/packet-journey",
            json={"source_ip": "192.168.1.10", "destination_ip": "192.168.1.0"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert data["error"] is not None
        assert "10.0.0.2" in data["error"]

    def test_the_response_model_is_declared(self, client):
        """The endpoint's schema is not empty, so the contract can be checked."""
        schema = client.get("/openapi.json").json()
        response_schema = schema["paths"]["/packet-journey"]["post"]["responses"][
            "200"
        ]["content"]["application/json"]["schema"]

        reference = response_schema.get("$ref", "")
        assert reference, "the 200 response must reference a declared model"
        name = reference.rsplit("/", 1)[-1]
        assert name == "PacketJourneyResponse"

        properties = schema["components"]["schemas"][name]["properties"]
        assert set(properties) >= {
            "source_ip",
            "destination_ip",
            "hops",
            "success",
            "error",
            "provenance",
        }

    def test_the_hop_model_lists_the_actions_it_can_carry(self, client):
        """The action set is stated in the schema, not only in prose."""
        schema = client.get("/openapi.json").json()
        hop_schema = schema["components"]["schemas"]["PacketHopResponse"]
        actions = hop_schema["properties"]["action"]["description"]

        for action in (
            "forward",
            "deliver",
            "drop",
            "loop",
            "unresolved_next_hop",
            "error",
        ):
            assert action in actions

    def test_the_hop_field_names_are_unchanged(self, client):
        """The interface renders these names, so they must not move."""
        response = client.post(
            "/packet-journey",
            json={"source_ip": "192.168.1.10", "destination_ip": "10.5.5.5"},
        )

        data = response.json()
        hop = data["hops"][0]
        assert set(hop) == {
            "hop_number",
            "current_device",
            "destination_ip",
            "action",
            "explanation",
            "matched_route",
            "egress_interface",
        }
        assert set(hop["matched_route"]) == {
            "destination",
            "next_hop",
            "interface",
            "metric",
        }

    def test_a_gateway_hop_carries_the_next_hop_and_egress(self, client):
        """A forwarding hop names the address and the interface used."""
        response = client.post(
            "/packet-journey",
            json={"source_ip": "192.168.1.10", "destination_ip": "192.168.1.0"},
        )

        hop = response.json()["hops"][0]
        assert hop["next_hop_ip"] == "10.0.0.2"
        assert hop["egress_interface"] == "eth1"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
