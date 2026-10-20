"""
Tests for the Learning Lab exercises.

An exercise must only be marked complete when the routing engine's own
output satisfies the check, so these tests drive the engine rather than
comparing stored answers.
"""

import pytest

from app.exercises import EXERCISES, exercise_list, get_exercise
from app.exercise_checks import check_exercise
from app.scenarios_data import SCENARIOS
from app.scenario import Scenario, Node, Iface, Link, Route


class TestExerciseDefinitions:
    """The exercises themselves must be well formed."""

    def test_exercises_exist(self):
        """There is a set of exercises to work through."""
        assert len(EXERCISES) >= 5
        for ex in EXERCISES.values():
            assert ex.id
            assert ex.title
            assert ex.concept

    def test_every_exercise_explains_the_concept(self):
        """Each exercise fills in the six parts of the teaching pattern."""
        for ex in EXERCISES.values():
            assert ex.what_it_is, f"{ex.id} is missing 'what it is'"
            assert ex.why_it_matters, f"{ex.id} is missing 'why it matters'"
            assert ex.what_happens, f"{ex.id} is missing 'what happens'"
            assert ex.analogy, f"{ex.id} is missing an analogy"
            assert ex.instruction, f"{ex.id} is missing instructions"
            assert ex.takeaway, f"{ex.id} is missing a takeaway"
            assert ex.prediction_prompt, f"{ex.id} is missing a prediction prompt"

    def test_exercise_scenarios_exist(self):
        """Every exercise points at a scenario that exists."""
        for ex in EXERCISES.values():
            assert ex.scenario_id in SCENARIOS, f"{ex.id} names a missing scenario"
            assert ex.source in {n.id for n in SCENARIOS[ex.scenario_id].nodes}
            assert ex.destination

    def test_exercise_list_summaries(self):
        """The list endpoint shape is right."""
        summaries = exercise_list()
        assert len(summaries) == len(EXERCISES)
        for s in summaries:
            assert {"id", "title", "concept", "kind", "scenario_id"} <= set(s)

    def test_get_exercise_unknown(self):
        """An unknown exercise is reported as None."""
        assert get_exercise("nope") is None

    def test_edit_exercises_have_editable_routes(self):
        """Exercises that ask for an edit say which node and what to add."""
        for ex in EXERCISES.values():
            if ex.kind == "edit":
                assert ex.editable_node, f"{ex.id} is an edit exercise but names no node"
                assert ex.editable_routes, f"{ex.id} is an edit exercise but adds nothing"


class TestExerciseChecks:
    """The checks must reflect what the engine actually does."""

    def test_longest_prefix_is_complete_when_engine_picks_it(self):
        """The longest-prefix exercise passes on the real scenario."""
        state = check_exercise("longest-prefix", SCENARIOS["two-routers"])
        assert state is not None
        assert state.complete is True
        assert state.selected_route == "10.0.1.0/24"
        assert state.selected_prefix_length == 24
        assert state.trace_status == "delivered"
        assert all(c.satisfied for c in state.checks)

    def test_longest_prefix_fails_when_only_a_default_route_exists(self):
        """With only a default route, the exercise is not complete."""
        scenario = Scenario(
            id="default-only",
            title="Default only",
            nodes=[
                Node(
                    id="client",
                    kind="host",
                    ifaces=[Iface(name="eth0", cidr="192.168.1.100/24")],
                    routes=[Route(prefix="0.0.0.0/0", dev="eth0", via="192.168.1.1", metric=100)],
                ),
                Node(
                    id="r1",
                    kind="router",
                    ifaces=[
                        Iface(name="eth0", cidr="192.168.1.1/24"),
                        Iface(name="eth1", cidr="10.0.0.1/30"),
                    ],
                    routes=[Route(prefix="0.0.0.0/0", dev="eth1", via="10.0.0.2", metric=10)],
                ),
            ],
            links=[Link(a="client:eth0", b="r1:eth0")],
        )
        state = check_exercise("longest-prefix", scenario)
        assert state is not None
        assert state.complete is False
        assert any(not c.satisfied for c in state.checks)

    def test_default_route_is_complete(self):
        """The default-route exercise passes on the real scenario."""
        state = check_exercise("default-route", SCENARIOS["client-router-server"])
        assert state is not None
        assert state.complete is True
        assert state.selected_route == "0.0.0.0/0"

    def test_missing_route_is_complete(self):
        """The missing-route exercise passes when the packet is dropped."""
        state = check_exercise("missing-route", SCENARIOS["two-routers"])
        assert state is not None
        assert state.complete is True
        assert state.trace_status in ("no_route", "unresolved_next_hop", "not_forwarding")
        assert state.checks[-1].detail

    def test_routing_loop_is_complete(self):
        """The loop exercise passes on the loop scenario."""
        state = check_exercise("routing-loop", SCENARIOS["loop"])
        assert state is not None
        assert state.complete is True
        assert state.trace_status == "loop"

    def test_change_a_route_needs_the_edit(self):
        """The edit exercise is not complete before the route is added."""
        state = check_exercise("change-a-route", SCENARIOS["client-router-server"])
        assert state is not None
        # The unmodified scenario still uses the connected route.
        assert state.complete is False
        assert state.selected_route == "10.0.0.0/24"

    def test_change_a_route_is_complete_after_the_edit(self):
        """Once the more specific route exists, the exercise is complete."""
        scenario = SCENARIOS["client-router-server"].model_copy(deep=True)
        router = scenario.node("router")
        router.routes = [
            Route(prefix="10.0.0.2/32", dev="eth1", via="10.0.0.2", metric=5)
        ]

        state = check_exercise("change-a-route", scenario)
        assert state is not None
        assert state.complete is True
        assert state.selected_route == "10.0.0.2/32"
        assert state.selected_prefix_length == 32

    def test_metric_tiebreak_is_complete_with_lower_metric(self):
        """The metric exercise passes when the lower metric is chosen."""
        scenario = SCENARIOS["client-router-server"].model_copy(deep=True)
        router = scenario.node("router")
        router.routes = [
            Route(prefix="10.0.0.2/32", dev="eth1", via="10.0.0.2", metric=5),
            Route(prefix="10.0.0.2/32", dev="eth1", via="10.0.0.2", metric=50),
        ]

        state = check_exercise("metric-tiebreak", scenario)
        assert state is not None
        assert state.complete is True
        assert state.selected_route == "10.0.0.2/32"

    def test_metric_tiebreak_fails_without_a_tie(self):
        """With only one route the metric was never tested."""
        state = check_exercise("metric-tiebreak", SCENARIOS["client-router-server"])
        assert state is not None
        assert state.complete is False

    def test_ipv6_separate_is_complete(self):
        """The IPv6 exercise passes on the dual-stack scenario."""
        state = check_exercise("ipv6-separate", SCENARIOS["dual-stack"])
        assert state is not None
        assert state.complete is True
        # The router used its directly connected IPv6 network, which is an
        # IPv6 route, not the IPv4 default.
        assert state.selected_route == "2001:db8:2::/64"
        assert state.selected_prefix_length == 64

    def test_ipv6_separate_rejects_an_ipv4_route(self):
        """A router with only IPv4 routes cannot forward IPv6 traffic."""
        scenario = Scenario(
            id="v4-only",
            title="IPv4 only router",
            nodes=[
                Node(
                    id="client",
                    kind="host",
                    ifaces=[Iface(name="eth0", cidr="2001:db8:1::100/64")],
                    routes=[Route(prefix="::/0", dev="eth0", via="2001:db8:1::1", metric=100)],
                ),
                Node(
                    id="router",
                    kind="router",
                    ifaces=[
                        Iface(name="eth0", cidr="2001:db8:1::1/64"),
                        Iface(name="eth1", cidr="192.168.1.1/24"),
                    ],
                    routes=[
                        Route(prefix="0.0.0.0/0", dev="eth1", via="192.168.1.254", metric=10)
                    ],
                ),
            ],
            links=[Link(a="client:eth0", b="router:eth0")],
        )
        state = check_exercise("ipv6-separate", scenario)
        assert state is not None
        assert state.complete is False
        assert state.trace_status != "delivered"

    def test_unknown_exercise_returns_none(self):
        """Checking an exercise that does not exist returns nothing."""
        assert check_exercise("nope", SCENARIOS["two-routers"]) is None

    def test_every_exercise_has_a_check(self):
        """Every exercise is actually verifiable."""
        for ex_id in EXERCISES:
            state = check_exercise(ex_id, SCENARIOS[EXERCISES[ex_id].scenario_id])
            assert state is not None, f"{ex_id} has no check"
            assert state.checks, f"{ex_id} produced no checks"
