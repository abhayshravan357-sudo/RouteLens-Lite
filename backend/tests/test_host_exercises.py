"""
Tests for the exercises that run against the host's own routing table.

The routing tables used here are real ones, captured from the Linux
kernel. Two are used.

The first is this machine's own table, read with `ip -j route show`:

    [{"dst":"default","gateway":"192.168.0.1","dev":"wlp2s0","protocol":"dhcp",
      "prefsrc":"192.168.0.107","metric":600,"flags":[]},
     {"dst":"192.168.0.0/24","dev":"wlp2s0","protocol":"kernel","scope":"link",
      "prefsrc":"192.168.0.107","metric":600,"flags":[]}]

The second has no default route at all, produced by a real network
namespace with no default added:

    unshare -rn bash -c '
        ip link set lo up
        ip link add veth0 type veth peer name veth1
        ip addr add 10.0.0.1/24 dev veth0
        ip link set veth0 up
        ip -j route show'

    [{"dst":"10.0.0.0/24","dev":"veth0","protocol":"kernel","scope":"link",
      "prefsrc":"10.0.0.1","flags":["linkdown"]}]

A machine with a connected route and no default route is a real
configuration, not a contrivance, and the exercises have to behave
honestly on it.
"""

import json

import pytest
from unittest.mock import AsyncMock, patch

from app.exercise_checks import (
    HostExerciseState,
    check_host_exercise,
)
from app.exercises import HOST_EXERCISES, host_exercise_list
from app.network_collector import CollectionResult, InterfaceInfo, RouteInfo


# --------------------------------------------------------------------------
# Real kernel output
# --------------------------------------------------------------------------

#: This machine's own routing table.
REAL_HOST_ROUTES_JSON = """
[
  {"dst":"default","gateway":"192.168.0.1","dev":"wlp2s0","protocol":"dhcp",
   "prefsrc":"192.168.0.107","metric":600,"flags":[]},
  {"dst":"192.168.0.0/24","dev":"wlp2s0","protocol":"kernel","scope":"link",
   "prefsrc":"192.168.0.107","metric":600,"flags":[]}
]
"""

#: A real table with a connected route and no default route.
REAL_NO_DEFAULT_ROUTES_JSON = """
[
  {"dst":"10.0.0.0/24","dev":"veth0","protocol":"kernel","scope":"link",
   "prefsrc":"10.0.0.1","flags":["linkdown"]}
]
"""

#: This machine's own interfaces.
REAL_HOST_INTERFACES_JSON = """
[
  {"ifindex":1,"ifname":"lo","flags":["LOOPBACK","UP","LOWER_UP"],"mtu":65536,
   "operstate":"UNKNOWN","address":"00:00:00:00:00:00","broadcast":"00:00:00:00:00:00",
   "addr_info":[
     {"family":"inet","local":"127.0.0.1","prefixlen":8,"scope":"host","label":"lo",
      "valid_life_time":4294967295,"preferred_life_time":4294967295},
     {"family":"inet6","local":"::1","prefixlen":128,"scope":"host","label":"lo",
      "valid_life_time":4294967295,"preferred_life_time":4294967295}]},
  {"ifindex":3,"ifname":"wlp2s0","flags":["BROADCAST","MULTICAST","UP","LOWER_UP"],
   "mtu":1500,"operstate":"UP","address":"e8:65:d4:5c:54:28","broadcast":"ff:ff:ff:ff:ff:ff",
   "addr_info":[
     {"family":"inet","local":"192.168.0.107","prefixlen":24,"scope":"global",
      "valid_life_time":3458,"preferred_life_time":3458},
     {"family":"inet6","local":"fe80::438d:61d3:3744:41f8","prefixlen":64,"scope":"link",
      "valid_life_time":-1,"preferred_life_time":-1}]}
]
"""


def routes_from(raw: str) -> list[RouteInfo]:
    """Parse real `ip -j route show` output into RouteInfo objects."""
    return [
        RouteInfo(
            destination=data.get("dst", "default"),
            gateway=data.get("gateway"),
            interface=data.get("dev"),
            metric=data.get("metric"),
            proto=data.get("protocol", "kernel"),
            scope=data.get("scope", "link"),
            pref_src=data.get("prefsrc"),
        )
        for data in json.loads(raw)
    ]


def interfaces_from(raw: str) -> list[InterfaceInfo]:
    """Parse real `ip -j addr show` output into InterfaceInfo objects."""
    interfaces = []
    for data in json.loads(raw):
        v4 = [a["local"] for a in data.get("addr_info", []) if a.get("family") == "inet"]
        v6 = [a["local"] for a in data.get("addr_info", []) if a.get("family") == "inet6"]
        interfaces.append(
            InterfaceInfo(
                name=data.get("ifname", ""),
                index=data.get("ifindex", 0),
                state=data.get("operstate", "UNKNOWN").upper(),
                mtu=data.get("mtu"),
                mac_address=data.get("address"),
                ipv4_addresses=v4,
                ipv6_addresses=v6,
            )
        )
    return interfaces


@pytest.fixture
def host_with_default():
    """The collector returning this machine's real table."""
    routes = routes_from(REAL_HOST_ROUTES_JSON)
    interfaces = interfaces_from(REAL_HOST_INTERFACES_JSON)

    async def fake_collect_routes(self, ip_version="ipv4"):
        return CollectionResult(
            timestamp="2026-10-20T00:00:00Z",
            success=True,
            data=routes,
            command=f"ip -j {'-6 ' if ip_version == 'ipv6' else ''}route show",
            ip_version=ip_version,
        )

    async def fake_collect_interfaces(self):
        return CollectionResult(
            timestamp="2026-10-20T00:00:00Z",
            success=True,
            data=interfaces,
            command="ip -j addr show",
            ip_version="both",
        )

    with patch(
        "app.network_collector.NetworkCollector.collect_routes", new=fake_collect_routes
    ), patch(
        "app.network_collector.NetworkCollector.collect_interfaces",
        new=fake_collect_interfaces,
    ):
        yield


@pytest.fixture
def host_without_default():
    """The collector returning a real table that has no default route."""
    routes = routes_from(REAL_NO_DEFAULT_ROUTES_JSON)
    interfaces = [
        InterfaceInfo(
            name="veth0",
            index=2,
            state="UP",
            ipv4_addresses=["10.0.0.1"],
            ipv4_networks=["10.0.0.1/24"],
        )
    ]

    async def fake_collect_routes(self, ip_version="ipv4"):
        return CollectionResult(
            timestamp="2026-10-20T00:00:00Z",
            success=True,
            data=routes,
            command="ip -j route show",
            ip_version=ip_version,
        )

    async def fake_collect_interfaces(self):
        return CollectionResult(
            timestamp="2026-10-20T00:00:00Z",
            success=True,
            data=interfaces,
            command="ip -j addr show",
            ip_version="both",
        )

    with patch(
        "app.network_collector.NetworkCollector.collect_routes", new=fake_collect_routes
    ), patch(
        "app.network_collector.NetworkCollector.collect_interfaces",
        new=fake_collect_interfaces,
    ):
        yield


@pytest.fixture
def host_unreadable():
    """The collector failing to read the table at all."""

    async def fake_collect_routes(self, ip_version="ipv4"):
        return CollectionResult(
            timestamp="2026-10-20T00:00:00Z",
            success=False,
            error="`ip` command not available",
            command="ip -j route show",
            ip_version=ip_version,
        )

    async def fake_collect_interfaces(self):
        return CollectionResult(
            timestamp="2026-10-20T00:00:00Z",
            success=False,
            error="`ip` command not available",
            command="ip -j addr show",
        )

    with patch(
        "app.network_collector.NetworkCollector.collect_routes", new=fake_collect_routes
    ), patch(
        "app.network_collector.NetworkCollector.collect_interfaces",
        new=fake_collect_interfaces,
    ):
        yield


# --------------------------------------------------------------------------
# The exercises themselves
# --------------------------------------------------------------------------


class TestHostExercisesDefined:
    """The host exercises exist and are described properly."""

    def test_there_are_at_least_three(self):
        assert len(HOST_EXERCISES) >= 3

    def test_they_cover_the_three_topics(self):
        ids = set(HOST_EXERCISES)
        assert "host-which-route" in ids
        assert "host-default-shadowed" in ids
        assert "host-gateway" in ids

    def test_each_has_the_full_explanation(self):
        for exercise in HOST_EXERCISES.values():
            assert exercise.what_it_is
            assert exercise.why_it_matters
            assert exercise.what_happens
            assert exercise.analogy
            assert exercise.instruction
            assert exercise.prediction_prompt
            assert exercise.result_hint
            assert exercise.takeaway

    def test_each_says_which_table_it_works_against(self):
        for exercise in HOST_EXERCISES.values():
            assert exercise.table_source.value == "host"
            assert exercise.source == "host"

    def test_each_says_what_to_look_at_instead(self):
        for exercise in HOST_EXERCISES.values():
            assert exercise.unavailable_hint
            assert "ip route show" in exercise.unavailable_hint

    def test_the_list_names_the_source(self):
        listed = host_exercise_list()
        assert len(listed) == len(HOST_EXERCISES)
        assert all(item["table_source"] == "host" for item in listed)

    def test_the_scenario_exercises_are_untouched(self):
        """The seven modelled exercises are unaffected."""
        from app.exercises import EXERCISES

        assert len(EXERCISES) == 7
        assert all(
            exercise.table_source.value == "scenario" for exercise in EXERCISES.values()
        )
        assert all(exercise.scenario_id for exercise in EXERCISES.values())


# --------------------------------------------------------------------------
# A machine with a default route
# --------------------------------------------------------------------------


class TestOnAMachineWithADefaultRoute:
    """Every host exercise works on a table that has a default route."""

    @pytest.mark.asyncio
    async def test_which_route_completes(self, host_with_default):
        state = await check_host_exercise("host-which-route")

        assert isinstance(state, HostExerciseState)
        assert state.available is True
        assert state.complete is True
        assert state.selected_route is not None

    @pytest.mark.asyncio
    async def test_which_route_names_the_candidates_it_beat(self, host_with_default):
        state = await check_host_exercise("host-which-route")

        # Every candidate that is not the winner is listed as having lost.
        assert len(state.candidates) == len(state.beaten) + 1
        for candidate in state.beaten:
            assert candidate["destination"]
            assert candidate["explanation"]

    @pytest.mark.asyncio
    async def test_which_route_answers_honestly_for_a_default_only_table(self, host_with_default):
        """This machine's table has a default and one connected route.

        The address 127.0.0.1 is not covered by the connected route, so the
        default route wins. The exercise has to say that plainly.
        """
        state = await check_host_exercise("host-which-route", destination="127.0.0.1")

        assert state.complete is True
        assert state.selected_route == "0.0.0.0/0"

        default_check = next(
            c for c in state.checks if "default route was used" in c.description
        )
        assert default_check.satisfied is True
        assert "no route more specific" in default_check.detail
        assert "honest answer" in default_check.detail

    @pytest.mark.asyncio
    async def test_which_route_prefers_the_more_specific_route_when_one_exists(
        self, host_with_default
    ):
        state = await check_host_exercise(
            "host-which-route", destination="192.168.0.55"
        )

        assert state.selected_route == "192.168.0.0/24"
        assert state.selected_prefix_length == 24
        assert state.complete is True

    @pytest.mark.asyncio
    async def test_default_shadowed_completes(self, host_with_default):
        state = await check_host_exercise("host-default-shadowed")

        assert state.available is True
        assert state.complete is True
        assert state.shadow is not None

    @pytest.mark.asyncio
    async def test_default_shadowed_names_the_specific_routes(self, host_with_default):
        state = await check_host_exercise("host-default-shadowed")

        assert "192.168.0.0/24" in state.shadow["more_specific_destinations"]
        assert state.shadow["less_specific_destination"] == "0.0.0.0/0"

    @pytest.mark.asyncio
    async def test_default_shadowed_picks_a_destination_the_specific_route_covers(
        self, host_with_default
    ):
        state = await check_host_exercise("host-default-shadowed")

        assert state.destination
        assert state.selected_prefix_length and state.selected_prefix_length > 0

    @pytest.mark.asyncio
    async def test_gateway_completes_with_the_right_answer(self, host_with_default):
        state = await check_host_exercise("host-gateway", answer="192.168.0.1")

        assert state.available is True
        assert state.complete is True
        assert state.selected_next_hop == "192.168.0.1"

    @pytest.mark.asyncio
    async def test_gateway_is_not_complete_with_the_wrong_answer(self, host_with_default):
        state = await check_host_exercise("host-gateway", answer="10.0.0.1")

        assert state.complete is False
        answer_check = next(
            c for c in state.checks if "identified the next hop" in c.description
        )
        assert answer_check.satisfied is False

    @pytest.mark.asyncio
    async def test_gateway_is_not_complete_with_no_answer(self, host_with_default):
        state = await check_host_exercise("host-gateway")

        assert state.complete is False
        answer_check = next(
            c for c in state.checks if "identified the next hop" in c.description
        )
        assert answer_check.satisfied is False
        assert "not said" in answer_check.detail

    @pytest.mark.asyncio
    async def test_gateway_uses_an_address_outside_the_local_networks(self, host_with_default):
        state = await check_host_exercise("host-gateway", answer="192.168.0.1")

        assert state.destination
        assert state.selected_route == "0.0.0.0/0"

    @pytest.mark.asyncio
    async def test_the_table_is_reported_as_observed(self, host_with_default):
        for exercise_id in HOST_EXERCISES:
            state = await check_host_exercise(exercise_id, answer="192.168.0.1")
            assert state.table_provenance == "observed"

    @pytest.mark.asyncio
    async def test_the_conclusion_is_reported_as_inferred(self, host_with_default):
        for exercise_id in HOST_EXERCISES:
            state = await check_host_exercise(exercise_id, answer="192.168.0.1")
            assert state.analysis_provenance == "inferred"
            assert state.analysis_provenance != state.table_provenance


# --------------------------------------------------------------------------
# A machine with no default route
# --------------------------------------------------------------------------


class TestOnAMachineWithNoDefaultRoute:
    """A table with a connected route and no default route is a real thing.

    The exercises must report that, not fail, and must not fall back to a
    modelled table.
    """

    @pytest.mark.asyncio
    async def test_which_route_still_works(self, host_without_default):
        """The connected route is enough to answer this one."""
        state = await check_host_exercise("host-which-route", destination="10.0.0.5")

        assert state.available is True
        assert state.selected_route == "10.0.0.0/24"
        assert state.complete is True

    @pytest.mark.asyncio
    async def test_which_route_says_the_default_route_was_not_used(self, host_without_default):
        state = await check_host_exercise("host-which-route", destination="10.0.0.5")

        assert state.selected_route != "0.0.0.0/0"
        assert not any(
            "default route was used" in c.description for c in state.checks
        )

    @pytest.mark.asyncio
    async def test_default_shadowed_reports_that_there_is_no_default_route(
        self, host_without_default
    ):
        state = await check_host_exercise("host-default-shadowed")

        assert state.available is False
        assert state.complete is False
        assert "no default route" in state.unavailable_reason.lower()
        assert state.message
        assert "ip route show" in state.message

    @pytest.mark.asyncio
    async def test_gateway_reports_that_there_is_no_default_route(
        self, host_without_default
    ):
        state = await check_host_exercise("host-gateway", answer="10.0.0.1")

        assert state.available is False
        assert state.complete is False
        assert "no default route" in state.unavailable_reason.lower()
        assert "gateway" in state.unavailable_reason.lower()

    @pytest.mark.asyncio
    async def test_an_unavailable_exercise_never_claims_completion(
        self, host_without_default
    ):
        """Whatever the machine's table is, nothing false is reported.

        The one that can be answered is answered; the two that cannot are
        reported as unavailable. None of them claims a completion that did
        not happen.
        """
        for exercise_id in HOST_EXERCISES:
            state = await check_host_exercise(exercise_id, answer="10.0.0.1")
            if state.available:
                # An available exercise is allowed to be complete.
                continue
            assert state.complete is False
            assert state.unavailable_reason
            assert state.message

    @pytest.mark.asyncio
    async def test_no_modelled_route_is_invented(self, host_without_default):
        """Nothing may come from the sample table."""
        for exercise_id in HOST_EXERCISES:
            state = await check_host_exercise(exercise_id, answer="10.0.0.1")
            for route in state.table_routes:
                assert route["destination"] in ("10.0.0.0/24",)

    @pytest.mark.asyncio
    async def test_the_provenance_still_holds_when_unavailable(self, host_without_default):
        state = await check_host_exercise("host-default-shadowed")

        assert state.table_provenance == "observed"
        assert state.analysis_provenance == "inferred"


# --------------------------------------------------------------------------
# A table that could not be read
# --------------------------------------------------------------------------


class TestWhenTheTableCannotBeRead:
    """A failed collection must be reported, never replaced."""

    @pytest.mark.asyncio
    async def test_it_reports_that_the_table_could_not_be_read(self, host_unreadable):
        state = await check_host_exercise("host-which-route")

        assert state.available is False
        assert state.complete is False
        assert "could not be read" in state.unavailable_reason.lower()
        assert state.message

    @pytest.mark.asyncio
    async def test_it_does_not_fall_back_to_a_modelled_table(self, host_unreadable):
        state = await check_host_exercise("host-which-route")

        assert state.table_routes == []
        assert state.selected_route is None
        assert state.candidates == []

    @pytest.mark.asyncio
    async def test_every_exercise_reports_it(self, host_unreadable):
        for exercise_id in HOST_EXERCISES:
            state = await check_host_exercise(exercise_id, answer="192.168.0.1")
            assert state.available is False
            assert state.complete is False

    @pytest.mark.asyncio
    async def test_it_does_not_claim_the_table_was_observed(self, host_unreadable):
        """A table that was never read cannot be 'observed'.

        The frontend shows a 'table observed, conclusion inferred' badge
        when both claims are made, so claiming them here would put a
        measurement badge above a message saying the measurement failed.
        """
        for exercise_id in HOST_EXERCISES:
            state = await check_host_exercise(exercise_id, answer="192.168.0.1")

            assert state.table_provenance == "unknown"
            assert state.analysis_provenance == "unknown"

    @pytest.mark.asyncio
    async def test_the_badge_condition_does_not_fire(self, host_unreadable):
        """The condition the frontend uses to show the badge."""
        for exercise_id in HOST_EXERCISES:
            state = await check_host_exercise(exercise_id, answer="192.168.0.1")

            badge_would_show = (
                state.table_provenance == "observed"
                and state.analysis_provenance == "inferred"
            )
            assert badge_would_show is False

    @pytest.mark.asyncio
    async def test_a_table_that_was_read_is_still_observed(self, host_without_default):
        """Only the failed collection loses the 'observed' claim.

        A machine with no default route still had its table read, so the
        table is observed and a conclusion was drawn from it.
        """
        state = await check_host_exercise("host-default-shadowed")

        assert state.available is False
        assert state.table_provenance == "observed"
        assert state.analysis_provenance == "inferred"


# --------------------------------------------------------------------------
# Endpoints
# --------------------------------------------------------------------------


class TestHostExerciseEndpoints:
    """The HTTP surface of the host exercises."""

    @pytest.fixture
    def client(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from app.exercises import host_exercise_router

        app = FastAPI()
        app.include_router(host_exercise_router)
        return TestClient(app)

    def test_list(self, client):
        response = client.get("/api/host-exercises")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == len(HOST_EXERCISES)
        assert all(item["table_source"] == "host" for item in data)

    def test_detail(self, client):
        response = client.get("/api/host-exercises/host-gateway")

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == "host-gateway"
        assert data["table_source"] == "host"
        assert data["what_it_is"]
        assert data["unavailable_hint"]

    def test_detail_for_an_unknown_exercise(self, client):
        response = client.get("/api/host-exercises/nope")

        assert response.status_code == 404

    def test_check(self, client, host_with_default):
        response = client.post(
            "/api/host-exercises/host-gateway/check", json={"answer": "192.168.0.1"}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["complete"] is True
        assert data["table_provenance"] == "observed"
        assert data["analysis_provenance"] == "inferred"

    def test_check_without_a_destination(self, client, host_with_default):
        response = client.post("/api/host-exercises/host-which-route/check", json={})

        assert response.status_code == 200
        data = response.json()
        assert data["destination"]
        assert data["complete"] is True

    def test_check_for_an_unknown_exercise(self, client, host_with_default):
        response = client.post("/api/host-exercises/nope/check", json={})

        assert response.status_code == 404


# --------------------------------------------------------------------------
# The modelled exercises are unaffected
# --------------------------------------------------------------------------


class TestScenarioExercisesUnaffected:
    """The seven modelled exercises still pass exactly as they did."""

    def test_the_longest_prefix_exercise_still_completes(self):
        from app.exercise_checks import check_exercise
        from app.scenarios_data import SCENARIOS

        state = check_exercise("longest-prefix", SCENARIOS["two-routers"])
        assert state is not None
        assert state.complete is True

    def test_the_default_route_exercise_still_completes(self):
        from app.exercise_checks import check_exercise
        from app.scenarios_data import SCENARIOS

        state = check_exercise("default-route", SCENARIOS["client-router-server"])
        assert state is not None
        assert state.complete is True

    def test_the_missing_route_exercise_still_completes(self):
        from app.exercise_checks import check_exercise
        from app.scenarios_data import SCENARIOS

        state = check_exercise("missing-route", SCENARIOS["two-routers"])
        assert state is not None
        assert state.complete is True

    def test_the_routing_loop_exercise_still_completes(self):
        from app.exercise_checks import check_exercise
        from app.scenarios_data import SCENARIOS

        state = check_exercise("routing-loop", SCENARIOS["loop"])
        assert state is not None
        assert state.complete is True

    def test_the_ipv6_exercise_still_completes(self):
        from app.exercise_checks import check_exercise
        from app.scenarios_data import SCENARIOS

        state = check_exercise("ipv6-separate", SCENARIOS["dual-stack"])
        assert state is not None
        assert state.complete is True

    def test_a_host_exercise_id_is_not_a_scenario_exercise(self):
        """The two registries do not overlap."""
        from app.exercise_checks import check_exercise
        from app.scenarios_data import SCENARIOS

        state = check_exercise("host-gateway", SCENARIOS["dual-stack"])
        assert state is None

    @pytest.mark.asyncio
    @pytest.mark.asyncio
    async def test_an_unknown_host_exercise_is_none(self):
        state = await check_host_exercise("not-an-exercise")
        assert state is None
