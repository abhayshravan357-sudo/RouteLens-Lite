import unittest
from app.routing_logic import find_matching_routes, select_best_route, lookup_route
from app.routing import RoutingEntry, NextHopType, Provenance


def make_route(dest: str, metric: int = 0, interface: str = "eth0", next_hop: str | None = None) -> RoutingEntry:
    return RoutingEntry(
        destination=dest,
        next_hop=next_hop,
        interface=interface,
        metric=metric,
        next_hop_type=NextHopType.GATEWAY if next_hop else NextHopType.DIRECT,
        provenance=Provenance.SIMULATED,
    )

class TestRoutingLogic(unittest.TestCase):
    def test_longest_prefix_match(self):
        routes = [
            make_route("10.0.0.0/24", metric=10),
            make_route("10.0.0.0/16", metric=5),
        ]
        matching = find_matching_routes("10.0.0.42", routes)
        best, _ = select_best_route(matching)
        self.assertEqual(best.destination, "10.0.0.0/24")

    def test_metric_tiebreaker(self):
        routes = [
            make_route("10.0.0.0/24", metric=20),
            make_route("10.0.0.0/24", metric=10),
        ]
        matching = find_matching_routes("10.0.0.5", routes)
        best, _ = select_best_route(matching)
        self.assertEqual(best.metric, 10)

    def test_interface_tiebreaker(self):
        routes = [
            make_route("10.0.0.0/24", metric=0, interface="ethB"),
            make_route("10.0.0.0/24", metric=0, interface="ethA"),
        ]
        matching = find_matching_routes("10.0.0.1", routes)
        best, _ = select_best_route(matching)
        self.assertEqual(best.interface, "ethA")

    def test_lookup_invalid_ip(self):
        result = lookup_route("not-an-ip", [])
        self.assertFalse(result.matched)
        self.assertTrue(result.error.startswith("Invalid IP address"))

    def test_lookup_no_match(self):
        routes = [make_route("192.168.1.0/24")]
        result = lookup_route("10.0.0.1", routes)
        self.assertFalse(result.matched)
        self.assertIn("No route matches", result.explanation)

if __name__ == "__main__":
    unittest.main()
