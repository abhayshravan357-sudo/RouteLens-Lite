import pytest
from app.routing import RoutingEntry, NextHopType, Provenance
from app.routing_logic import select_best_route, find_matching_routes, lookup_route
from ipaddress import IPv4Network

def make_route(dest: str, metric: int = 0, interface: str = "eth0", next_hop: str | None = None) -> RoutingEntry:
    return RoutingEntry(
        destination=dest,
        next_hop=next_hop,
        interface=interface,
        metric=metric,
        next_hop_type=NextHopType.GATEWAY if next_hop else NextHopType.DIRECT,
        provenance=Provenance.SIMULATED,
    )

def test_longest_prefix_match():
    routes = [
        make_route("10.0.0.0/24", metric=10),
        make_route("10.0.0.0/16", metric=5),
    ]
    best, _ = select_best_route(find_matching_routes("10.0.0.42", routes))
    assert best.destination == "10.0.0.0/24"

def test_metric_tiebreaker():
    routes = [
        make_route("10.0.0.0/24", metric=20),
        make_route("10.0.0.0/24", metric=10),  # lower metric should win
    ]
    best, _ = select_best_route(find_matching_routes("10.0.0.5", routes))
    assert best.metric == 10

def test_interface_tiebreaker():
    routes = [
        make_route("10.0.0.0/24", metric=0, interface="ethB"),
        make_route("10.0.0.0/24", metric=0, interface="ethA"),  # alphabetical wins
    ]
    best, _ = select_best_route(find_matching_routes("10.0.0.1", routes))
    assert best.interface == "ethA"

def test_lookup_route_invalid_ip():
    result = lookup_route("not-an-ip", [])
    assert not result.matched
    assert result.error.startswith("Invalid IPv4 address")

def test_lookup_route_no_match():
    routes = [make_route("192.168.1.0/24")]
    result = lookup_route("10.0.0.1", routes)
    assert not result.matched
    assert "No route matches" in result.explanation
