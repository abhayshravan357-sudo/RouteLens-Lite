"""
Tests for the real routing table analysis.

The fixtures below are verbatim output from the Linux kernel's routing
subsystem, captured with `ip -j route show` and `ip -6 -j route show`. They
are not hand-written. The multi-route table was produced by running a real
network namespace:

    unshare -rn bash -c '
        ip link set lo up
        ip link add veth0 type veth peer name veth1
        ip addr add 10.0.0.1/24 dev veth0
        ip addr add 10.0.1.1/24 dev veth0
        ip link set veth0 up
        ip route add 10.0.0.0/25 dev veth0 proto static metric 100
        ip route add 10.0.0.128/25 dev veth0 proto static metric 100
        ip route add 10.0.1.0/24 dev veth0 proto static metric 200
        ip route add default via 10.0.0.254 dev veth0 proto static metric 600
        ip -j route show'

and the host table in REAL_HOST_IPV4_ROUTES_JSON is the actual table of the
machine these tests were written on.
"""

import json

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.network_collector import InterfaceInfo, RouteInfo
from app.route_analysis import (
    PUBLIC_IPV4,
    ShadowFinding,
    analyse_destination,
    analyse_table,
    choose_interesting_destinations,
    find_shadowing,
    summarise_default_coverage,
    to_teaching_entries,
    to_teaching_entry,
)
from app.routing import Provenance, RoutingEntry
from app.routing_logic import lookup_route


# --------------------------------------------------------------------------
# Real kernel output
# --------------------------------------------------------------------------

# Verbatim `ip -j route show` from a real network namespace with five routes.
# Note that the 10.0.1.0/24 kernel route carries NO metric key at all, which
# is exactly what the kernel does for an automatically-created connected
# route, and that the two adjacent /25s are the kind of pair that CIDR
# aggregation is defined over.
REAL_NAMESPACE_IPV4_ROUTES_JSON = """
[
  {"dst":"default","gateway":"10.0.0.254","dev":"veth0","protocol":"static","metric":600,"flags":["linkdown"]},
  {"dst":"10.0.0.0/25","dev":"veth0","protocol":"static","scope":"link","metric":100,"flags":["linkdown"]},
  {"dst":"10.0.0.0/24","dev":"veth0","protocol":"kernel","scope":"link","prefsrc":"10.0.0.1","flags":["linkdown"]},
  {"dst":"10.0.0.128/25","dev":"veth0","protocol":"static","scope":"link","metric":100,"flags":["linkdown"]},
  {"dst":"10.0.1.0/24","dev":"veth0","protocol":"kernel","scope":"link","prefsrc":"10.0.1.1","flags":["linkdown"]},
  {"dst":"10.0.1.0/24","dev":"veth0","protocol":"static","scope":"link","metric":200,"flags":["linkdown"]}
]
"""

# Verbatim `ip -6 -j route show` from a real network namespace. The default
# route is spelled "default", the same word the IPv4 table uses, which is why
# the family has to be supplied by the caller.
REAL_NAMESPACE_IPV6_ROUTES_JSON = """
[
  {"dst":"2001:db8::/64","dev":"veth0","protocol":"kernel","metric":256,"flags":["linkdown"],"pref":"medium"},
  {"dst":"2001:db8:1::/48","dev":"veth0","protocol":"static","metric":100,"flags":["linkdown"],"pref":"medium"},
  {"dst":"2001:db8:2::/48","dev":"veth0","protocol":"static","metric":100,"flags":["linkdown"],"pref":"medium"},
  {"dst":"default","gateway":"fe80::1","dev":"veth0","protocol":"static","metric":1024,"flags":["linkdown"],"pref":"medium"}
]
"""

# Verbatim `ip -j route show` from the machine these tests were written on.
REAL_HOST_IPV4_ROUTES_JSON = """
[
  {"dst":"default","gateway":"192.168.0.1","dev":"wlp2s0","protocol":"dhcp","prefsrc":"192.168.0.107","metric":600,"flags":[]},
  {"dst":"192.168.0.0/24","dev":"wlp2s0","protocol":"kernel","scope":"link","prefsrc":"192.168.0.107","metric":600,"flags":[]}
]
"""

# Verbatim `ip -6 -j route show` from the machine these tests were written on.
REAL_HOST_IPV6_ROUTES_JSON = """
[
  {"dst":"fe80::/64","dev":"wlp2s0","protocol":"kernel","metric":1024,"flags":[],"pref":"medium"}
]
"""


def routes_from_json(raw: str) -> list[RouteInfo]:
    """Parse real `ip -j route show` output into RouteInfo objects.

    This mirrors what the collector does, including the kernel's spelling of
    the default route as "default".
    """
    routes = []
    for data in json.loads(raw):
        routes.append(
            RouteInfo(
                destination=data.get("dst", "default"),
                gateway=data.get("gateway"),
                interface=data.get("dev"),
                metric=data.get("metric"),
                proto=data.get("protocol", "kernel"),
                scope=data.get("scope", "link"),
                pref_src=data.get("prefsrc"),
            )
        )
    return routes


@pytest.fixture
def ipv4_routes() -> list[RouteInfo]:
    return routes_from_json(REAL_NAMESPACE_IPV4_ROUTES_JSON)


@pytest.fixture
def ipv6_routes() -> list[RouteInfo]:
    return routes_from_json(REAL_NAMESPACE_IPV6_ROUTES_JSON)


@pytest.fixture
def ipv4_entries(ipv4_routes) -> list[RoutingEntry]:
    entries, skipped = to_teaching_entries(ipv4_routes, ip_version="ipv4")
    assert skipped == [], f"real routes should be expressible, got {skipped}"
    return entries


@pytest.fixture
def ipv6_entries(ipv6_routes) -> list[RoutingEntry]:
    entries, skipped = to_teaching_entries(ipv6_routes, ip_version="ipv6")
    assert skipped == [], f"real routes should be expressible, got {skipped}"
    return entries


# --------------------------------------------------------------------------
# Conversion
# --------------------------------------------------------------------------


class TestConversion:
    """Turning observed routes into teaching-model entries."""

    def test_converts_real_host_table(self):
        routes = routes_from_json(REAL_HOST_IPV4_ROUTES_JSON)
        entries, skipped = to_teaching_entries(routes, ip_version="ipv4")

        assert skipped == []
        assert len(entries) == 2
        assert {e.destination for e in entries} == {"0.0.0.0/0", "192.168.0.0/24"}

    def test_default_route_becomes_ipv4_default(self):
        routes = routes_from_json(REAL_HOST_IPV4_ROUTES_JSON)
        entries, _ = to_teaching_entries(routes, ip_version="ipv4")

        default = [e for e in entries if e.destination == "0.0.0.0/0"]
        assert len(default) == 1
        assert default[0].next_hop == "192.168.0.1"
        assert default[0].next_hop_type.value == "gateway"

    def test_default_route_becomes_ipv6_default(self):
        """The kernel spells the default route "default" in both families."""
        routes = routes_from_json(REAL_NAMESPACE_IPV6_ROUTES_JSON)
        entries, skipped = to_teaching_entries(routes, ip_version="ipv6")

        assert skipped == []
        default = [e for e in entries if e.destination == "::/0"]
        assert len(default) == 1
        assert default[0].next_hop == "fe80::1"

    def test_route_without_metric_uses_kernel_default_of_zero(self):
        """A connected route from the kernel carries no metric key at all.

        The kernel's metric for such a route is zero, so zero is the value
        that belongs on the entry, not a guess.
        """
        routes = routes_from_json(REAL_NAMESPACE_IPV4_ROUTES_JSON)
        entries, _ = to_teaching_entries(routes, ip_version="ipv4")

        kernel_route = [e for e in entries if e.destination == "10.0.1.0/24" and e.metric == 0]
        assert len(kernel_route) == 1
        assert kernel_route[0].next_hop is None
        assert kernel_route[0].next_hop_type.value == "direct"

    def test_observed_routes_keep_observed_provenance(self):
        """The table was read from the kernel, so the entries are observed."""
        routes = routes_from_json(REAL_HOST_IPV4_ROUTES_JSON)
        entries, _ = to_teaching_entries(routes, ip_version="ipv4")

        assert all(e.provenance == Provenance.OBSERVED for e in entries)

    def test_route_without_interface_is_skipped_with_reason(self):
        route = RouteInfo(destination="10.0.0.0/8", gateway="10.0.0.1", metric=10)
        entry, reason = to_teaching_entry(route, ip_version="ipv4")

        assert entry is None
        assert "interface" in reason

    def test_special_next_hop_is_skipped_with_reason(self):
        """A blackhole route is real, but the teaching model cannot say it."""
        route = RouteInfo(
            destination="10.9.0.0/16",
            gateway="unreachable",
            interface="eth0",
            metric=10,
        )
        entry, reason = to_teaching_entry(route, ip_version="ipv4")

        assert entry is None
        assert "special next hop" in reason

    def test_invalid_destination_is_skipped_with_reason(self):
        route = RouteInfo(
            destination="not-an-address",
            gateway="10.0.0.1",
            interface="eth0",
            metric=10,
        )
        entry, reason = to_teaching_entry(route, ip_version="ipv4")

        assert entry is None
        assert "not a valid" in reason

    def test_gateway_of_wrong_family_is_skipped_with_reason(self):
        route = RouteInfo(
            destination="10.0.0.0/8",
            gateway="2001:db8::1",
            interface="eth0",
            metric=10,
        )
        entry, reason = to_teaching_entry(route, ip_version="ipv4")

        assert entry is None
        assert "not a valid ipv4 address" in reason

    def test_skipped_routes_are_reported_not_dropped(self):
        routes = [
            RouteInfo(destination="10.0.0.0/8", gateway="10.0.0.1", metric=10),
            RouteInfo(
                destination="10.1.0.0/16",
                gateway="10.0.0.1",
                interface="eth0",
                metric=10,
            ),
        ]
        entries, skipped = to_teaching_entries(routes, ip_version="ipv4")

        assert len(entries) == 1
        assert len(skipped) == 1
        assert skipped[0].destination == "10.0.0.0/8"


# --------------------------------------------------------------------------
# Analysis agrees with the engine
# --------------------------------------------------------------------------


class TestAnalysisAgreesWithLookup:
    """The analysis must never disagree with lookup_route."""

    @pytest.mark.parametrize(
        "destination",
        [
            "10.0.0.1",      # in 10.0.0.0/25, the most specific
            "10.0.0.200",    # in 10.0.0.128/25
            "10.0.0.130",    # in 10.0.0.128/25
            "10.0.1.5",      # in 10.0.1.0/24, two routes compete
            "10.0.2.5",      # only the default route matches
            "8.8.8.8",       # only the default route matches
        ],
    )
    def test_selected_route_matches_lookup_route(self, ipv4_entries, destination):
        analysis = analyse_destination(destination, ipv4_entries)
        engine = lookup_route(destination, ipv4_entries)

        assert analysis.matched is True
        assert engine.matched is True
        assert analysis.selected is not None
        assert engine.route is not None
        assert analysis.selected.destination == engine.route.destination
        assert analysis.selected.next_hop == engine.route.next_hop
        assert analysis.selected.interface == engine.route.interface
        assert analysis.selected.metric == engine.route.metric

    def test_longest_prefix_wins_over_default(self, ipv4_entries):
        analysis = analyse_destination("10.0.0.5", ipv4_entries)

        assert analysis.selected.destination == "10.0.0.0/25"
        assert analysis.is_default_route is False

    def test_metric_decides_between_equal_prefix_lengths(self, ipv4_entries):
        """Two 10.0.1.0/24 routes: the kernel one has metric 0, static has 200."""
        analysis = analyse_destination("10.0.1.5", ipv4_entries)

        assert analysis.selected.destination == "10.0.1.0/24"
        assert analysis.selected.metric == 0

        beaten = [c for c in analysis.beaten if c.destination == "10.0.1.0/24"]
        assert len(beaten) == 1
        assert beaten[0].metric == 200
        assert beaten[0].outcome == "higher metric"

    def test_default_route_used_when_nothing_more_specific(self, ipv4_entries):
        analysis = analyse_destination("8.8.8.8", ipv4_entries)

        assert analysis.selected.destination == "0.0.0.0/0"
        assert analysis.is_default_route is True
        assert analysis.selected.next_hop == "10.0.0.254"


class TestCandidatesBeaten:
    """The candidates that lost are the part that teaches."""

    def test_candidates_are_reported(self, ipv4_entries):
        analysis = analyse_destination("10.0.0.5", ipv4_entries)

        # 10.0.0.0/25, 10.0.0.0/24 and 0.0.0.0/0 all match 10.0.0.5.
        assert len(analysis.candidates) == 3
        assert len(analysis.beaten) == 2

    def test_only_the_winner_is_marked_selected(self, ipv4_entries):
        analysis = analyse_destination("10.0.0.5", ipv4_entries)

        selected = [c for c in analysis.candidates if c.selected]
        assert len(selected) == 1
        assert selected[0].destination == "10.0.0.0/25"

    def test_candidates_are_ordered_most_specific_first(self, ipv4_entries):
        analysis = analyse_destination("10.0.0.5", ipv4_entries)

        prefix_lengths = [c.prefix_length for c in analysis.candidates]
        assert prefix_lengths == sorted(prefix_lengths, reverse=True)
        assert prefix_lengths[0] == 25

    def test_loser_explains_why_it_lost(self, ipv4_entries):
        analysis = analyse_destination("10.0.0.5", ipv4_entries)

        by_destination = {c.destination: c for c in analysis.candidates}

        assert by_destination["10.0.0.0/24"].outcome == "less specific"
        assert "longer than" not in by_destination["10.0.0.0/24"].explanation.lower()
        assert "shorter" in by_destination["10.0.0.0/24"].explanation.lower()

        assert by_destination["0.0.0.0/0"].outcome == "less specific"
        assert "shorter" in by_destination["0.0.0.0/0"].explanation.lower()

    def test_explanation_names_the_candidates_it_beat(self, ipv4_entries):
        analysis = analyse_destination("10.0.0.5", ipv4_entries)

        assert "10.0.0.0/24" in analysis.explanation
        assert "0.0.0.0/0" in analysis.explanation
        assert "2 other route(s) also matched but lost" in analysis.explanation

    def test_unmatched_destination_is_reported_not_guessed(self, ipv4_entries):
        analysis = analyse_destination("2001:db8::1", ipv4_entries)

        assert analysis.matched is False
        assert analysis.selected is None
        assert analysis.candidates == []
        assert "no route" in analysis.explanation.lower()

    def test_host_owned_address_is_flagged_as_delivered_locally(self, ipv4_entries):
        """The main table would forward it; the kernel delivers it locally.

        The main table's default route does match an address this host owns,
        because the default route matches everything. Reporting only that
        would suggest the address leaves the machine.
        """
        analysis = analyse_destination(
            "127.0.0.1",
            ipv4_entries,
            local_addresses={"127.0.0.1"},
        )

        assert analysis.matched is True
        assert analysis.selected.destination == "0.0.0.0/0"
        assert "local table" in analysis.explanation.lower()
        assert "delivers it locally" in analysis.explanation.lower()
        assert "forward it to the default gateway" in analysis.explanation.lower()

    def test_host_owned_address_on_a_connected_route_says_so(self, ipv4_entries):
        """When a connected route matches, the note must not blame the gateway."""
        analysis = analyse_destination(
            "10.0.0.1",
            ipv4_entries,
            local_addresses={"10.0.0.1"},
        )

        assert analysis.selected.destination == "10.0.0.0/25"
        assert "delivers it locally" in analysis.explanation.lower()
        assert "forward it to the default gateway" not in analysis.explanation.lower()
        assert "connected network" in analysis.explanation.lower()

    def test_host_owned_address_without_the_note_when_not_supplied(self, ipv4_entries):
        analysis = analyse_destination("127.0.0.1", ipv4_entries)

        assert "delivers it locally" not in analysis.explanation.lower()

    def test_limitations_name_the_table_that_was_read(self, ipv4_routes):
        report = analyse_table(ipv4_routes, ip_version="ipv4")

        assert any("main routing table" in lim for lim in report.limitations)
        assert any("separate tables" in lim for lim in report.limitations)


class TestDefaultRoute:
    """Identifying the default route and what it stands in for."""

    def test_default_routes_are_listed(self, ipv4_routes):
        report = analyse_table(ipv4_routes, ip_version="ipv4")

        assert report.default_routes == ["0.0.0.0/0"]

    def test_default_route_is_identified_as_such(self, ipv4_entries):
        analysis = analyse_destination("1.1.1.1", ipv4_entries)

        assert analysis.is_default_route is True
        assert "default route" in analysis.explanation.lower()

    def test_default_coverage_lists_more_specific_routes(self, ipv4_entries):
        default_entry = [e for e in ipv4_entries if e.destination == "0.0.0.0/0"][0]
        finding = summarise_default_coverage(ipv4_entries, default_entry)

        assert finding.less_specific_destination == "0.0.0.0/0"
        assert "10.0.0.0/25" in finding.more_specific_destinations
        assert "10.0.1.0/24" in finding.more_specific_destinations

    def test_default_coverage_aggregates_adjacent_prefixes(self, ipv4_entries):
        """The two adjacent /25s are one /24, which is what aggregation means.

        The real table holds 10.0.0.0/25, 10.0.0.128/25, 10.0.0.0/24 and
        10.0.1.0/24. Aggregating the two /25s alone gives 10.0.0.0/24, and
        that /24 together with 10.0.1.0/24 gives 10.0.0.0/23.
        """
        from ipaddress import collapse_addresses

        quarter = [
            e.get_network()
            for e in ipv4_entries
            if e.destination in ("10.0.0.0/25", "10.0.0.128/25")
        ]
        assert [str(n) for n in collapse_addresses(quarter)] == ["10.0.0.0/24"]

        default_entry = [e for e in ipv4_entries if e.destination == "0.0.0.0/0"][0]
        finding = summarise_default_coverage(ipv4_entries, default_entry)

        # The whole covered space aggregates up to 10.0.0.0/23.
        assert "10.0.0.0/23" in finding.captured_prefixes

    def test_default_coverage_does_not_collapse_across_families(self, ipv4_entries, ipv6_entries):
        """Each family is aggregated on its own."""
        default_v4 = [e for e in ipv4_entries if e.destination == "0.0.0.0/0"][0]
        default_v6 = [e for e in ipv6_entries if e.destination == "::/0"][0]

        finding_v4 = summarise_default_coverage(ipv4_entries, default_v4)
        finding_v6 = summarise_default_coverage(ipv6_entries, default_v6)

        assert finding_v4.captured_prefixes
        assert finding_v6.captured_prefixes
        assert not any(":" in p for p in finding_v4.captured_prefixes)
        assert all(":" in p for p in finding_v6.captured_prefixes)
        assert all(":" in p for p in finding_v6.more_specific_destinations)

    def test_public_address_uses_the_default_route(self, ipv4_entries):
        analysis = analyse_destination(PUBLIC_IPV4, ipv4_entries)

        assert analysis.selected.destination == "0.0.0.0/0"
        assert analysis.is_default_route is True


class TestShadowing:
    """A more specific route takes traffic from a less specific one."""

    def test_shadowing_is_detected(self, ipv4_entries):
        shadow = find_shadowing(ipv4_entries, "10.0.0.5")

        assert shadow is not None
        assert shadow.less_specific_destination == "0.0.0.0/0"
        assert "10.0.0.0/25" in shadow.more_specific_destinations

    def test_shadowing_explanation_names_both_routes(self, ipv4_entries):
        shadow = find_shadowing(ipv4_entries, "10.0.0.5")

        assert "10.0.0.0/25" in shadow.explanation
        assert "0.0.0.0/0" in shadow.explanation

    def test_no_shadowing_when_only_the_default_matches(self, ipv4_entries):
        shadow = find_shadowing(ipv4_entries, "8.8.8.8")

        assert shadow is None

    def test_report_collects_shadow_findings(self, ipv4_routes):
        report = analyse_table(ipv4_routes, ip_version="ipv4")

        assert len(report.shadow_findings) > 0
        assert any(
            f.less_specific_destination == "0.0.0.0/0"
            for f in report.shadow_findings
        )


class TestIPv6:
    """An IPv6 table is analysed correctly."""

    def test_ipv6_default_route_is_identified(self, ipv6_entries):
        analysis = analyse_destination("2606:4700:4700::1111", ipv6_entries)

        assert analysis.matched is True
        assert analysis.selected.destination == "::/0"
        assert analysis.is_default_route is True
        assert analysis.selected.next_hop == "fe80::1"

    def test_ipv6_longest_prefix_wins(self, ipv6_entries):
        analysis = analyse_destination("2001:db8:1::5", ipv6_entries)

        assert analysis.selected.destination == "2001:db8:1::/48"
        assert analysis.is_default_route is False

    def test_ipv6_analysis_agrees_with_lookup_route(self, ipv6_entries):
        for destination in ["2001:db8:1::5", "2001:db8:2::5", "2001:db8::5"]:
            analysis = analyse_destination(destination, ipv6_entries)
            engine = lookup_route(destination, ipv6_entries)

            assert analysis.matched is True
            assert engine.matched is True
            assert analysis.selected.destination == engine.route.destination

    def test_ipv6_candidates_are_reported(self, ipv6_entries):
        analysis = analyse_destination("2001:db8:1::5", ipv6_entries)

        assert len(analysis.candidates) == 2
        assert len(analysis.beaten) == 1
        assert analysis.beaten[0].destination == "::/0"

    def test_ipv4_routes_are_ignored_for_an_ipv6_destination(self, ipv4_entries):
        analysis = analyse_destination("2001:db8::1", ipv4_entries)

        assert analysis.matched is False


class TestProvenance:
    """The analysis is inferred. The table was observed. They are not the same."""

    def test_analysis_provenance_is_inferred(self, ipv4_routes):
        report = analyse_table(ipv4_routes, ip_version="ipv4")

        assert report.analysis_provenance == "inferred"
        assert report.table_provenance == "observed"

    def test_destination_analysis_provenance_is_inferred(self, ipv4_entries):
        analysis = analyse_destination("10.0.0.5", ipv4_entries)

        assert analysis.provenance == "inferred"
        assert analysis.provenance != "observed"

    def test_entries_keep_observed_provenance(self, ipv4_entries):
        assert all(e.provenance == "observed" for e in ipv4_entries)

    def test_limitations_are_always_present(self, ipv4_routes):
        report = analyse_table(ipv4_routes, ip_version="ipv4")

        assert len(report.limitations) > 0
        assert any("inferred" in lim for lim in report.limitations)
        assert any("no packet was transmitted" in lim.lower() for lim in report.limitations)

    def test_limitations_mention_skipped_routes_when_there_are_any(self):
        routes = [
            RouteInfo(destination="10.0.0.0/8", gateway="10.0.0.1", metric=10),
        ]
        report = analyse_table(routes, ip_version="ipv4")

        assert any("could not be expressed" in lim for lim in report.limitations)


class TestInterestingDestinations:
    """The destinations worth explaining are chosen from real host state."""

    def test_host_addresses_are_included(self, ipv4_entries):
        interfaces = [
            InterfaceInfo(
                name="wlp2s0",
                index=3,
                state="UP",
                ipv4_addresses=["192.168.0.107"],
                ipv4_networks=["192.168.0.107/24"],
            )
        ]
        destinations = choose_interesting_destinations(ipv4_entries, interfaces)

        assert "192.168.0.107" in destinations

    def test_gateway_is_included(self, ipv4_entries):
        interfaces = [
            InterfaceInfo(
                name="wlp2s0",
                index=3,
                state="UP",
                ipv4_addresses=["192.168.0.107"],
            )
        ]
        destinations = choose_interesting_destinations(ipv4_entries, interfaces)

        assert "10.0.0.254" in destinations

    def test_a_public_address_is_included_per_family(self, ipv4_entries, ipv6_entries):
        assert PUBLIC_IPV4 in choose_interesting_destinations(ipv4_entries, [])
        assert "2606:4700:4700::1111" in choose_interesting_destinations(ipv6_entries, [])

    def test_destinations_are_unique(self, ipv4_entries):
        interfaces = [
            InterfaceInfo(
                name="wlp2s0",
                index=3,
                state="UP",
                ipv4_addresses=["10.0.0.254"],
            )
        ]
        destinations = choose_interesting_destinations(ipv4_entries, interfaces)

        assert len(destinations) == len(set(destinations))


class TestRealHostTable:
    """The table of the machine these tests were written on."""

    def test_real_host_table_analyses(self):
        routes = routes_from_json(REAL_HOST_IPV4_ROUTES_JSON)
        report = analyse_table(
            routes,
            interfaces=[
                InterfaceInfo(
                    name="wlp2s0",
                    index=3,
                    state="UP",
                    ipv4_addresses=["192.168.0.107"],
                    ipv4_networks=["192.168.0.107/24"],
                )
            ],
            ip_version="ipv4",
        )

        assert report.routes_in_table == 2
        assert report.routes_analysed == 2
        assert report.routes_skipped == []
        assert report.default_routes == ["0.0.0.0/0"]

    def test_real_host_local_traffic_uses_the_link_route(self):
        routes = routes_from_json(REAL_HOST_IPV4_ROUTES_JSON)
        entries, _ = to_teaching_entries(routes, ip_version="ipv4")

        analysis = analyse_destination("192.168.0.55", entries)

        assert analysis.selected.destination == "192.168.0.0/24"
        assert analysis.selected.next_hop is None
        assert analysis.selected.next_hop_type.value == "direct"

    def test_real_host_internet_traffic_uses_the_default_route(self):
        routes = routes_from_json(REAL_HOST_IPV4_ROUTES_JSON)
        entries, _ = to_teaching_entries(routes, ip_version="ipv4")

        analysis = analyse_destination("1.1.1.1", entries)

        assert analysis.selected.destination == "0.0.0.0/0"
        assert analysis.selected.next_hop == "192.168.0.1"

    def test_real_host_ipv6_table_analyses(self):
        routes = routes_from_json(REAL_HOST_IPV6_ROUTES_JSON)
        entries, skipped = to_teaching_entries(routes, ip_version="ipv6")

        assert skipped == []
        assert len(entries) == 1
        assert entries[0].destination == "fe80::/64"

        analysis = analyse_destination("fe80::1", entries)
        assert analysis.matched is True
        assert analysis.selected.destination == "fe80::/64"


# --------------------------------------------------------------------------
# API endpoint
# --------------------------------------------------------------------------


class TestAnalysisEndpoint:
    """GET /network/routes/analysis"""

    @pytest.fixture
    def client(self):
        return TestClient(app)

    def test_endpoint_returns_a_report(self, client):
        response = client.get("/network/routes/analysis")

        assert response.status_code == 200
        data = response.json()

        assert data["table_provenance"] == "observed"
        assert data["analysis_provenance"] == "inferred"
        assert "routes_in_table" in data
        assert "analyses" in data
        assert "limitations" in data

    def test_endpoint_accepts_a_destination(self, client):
        response = client.get("/network/routes/analysis", params={"destination": "1.1.1.1"})

        assert response.status_code == 200
        data = response.json()

        assert len(data["analyses"]) == 1
        assert data["analyses"][0]["destination"] == "1.1.1.1"
        assert data["analyses"][0]["provenance"] == "inferred"

    def test_endpoint_rejects_an_invalid_destination(self, client):
        response = client.get(
            "/network/routes/analysis", params={"destination": "not-an-address"}
        )

        assert response.status_code == 400
        assert "invalid" in response.json()["detail"].lower()

    def test_endpoint_never_claims_to_have_transmitted(self, client):
        response = client.get("/network/routes/analysis", params={"destination": "1.1.1.1"})

        assert response.status_code == 200
        body = response.text.lower()

        assert "transmitted" not in body or "no packet was transmitted" in body


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
