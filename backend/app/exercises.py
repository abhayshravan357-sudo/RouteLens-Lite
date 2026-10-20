"""
RouteLens Lite - Learning Lab Exercises

Guided exercises that teach routing concepts by making the student do
something and then checking the real result.

Every exercise is verified by running the actual routing engine, not by
comparing a string the student typed against an answer key. An exercise
is only complete when the engine's own output satisfies the check.

The teaching pattern for each concept:
  1. What it is
  2. Why it matters
  3. What happens, step by step
  4. A real-life analogy
  5. Try it
  6. Check the result
"""

from __future__ import annotations

import ipaddress
from enum import Enum
from typing import Callable, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from app.scenario import Scenario, trace


class ExerciseKind(str, Enum):
    """What the student has to do to complete the exercise."""

    TRACE = "trace"
    LOOKUP = "lookup"
    EDIT = "edit"


class TableSource(str, Enum):
    """Where the routing table an exercise works against comes from.

    A scenario exercise works against a modelled network. A host exercise
    works against the routing table of the machine the student is sitting
    at, read from the kernel.
    """

    SCENARIO = "scenario"
    HOST = "host"


class ExerciseCheck(BaseModel):
    """One condition that must hold for the exercise to be complete."""

    description: str
    satisfied: bool
    detail: str = ""


class Exercise(BaseModel):
    """A guided exercise."""

    id: str
    title: str
    concept: str
    kind: ExerciseKind

    # Where the routing table comes from. "scenario" for the modelled
    # network exercises, "host" for the ones that read the student's own
    # machine.
    table_source: TableSource = TableSource.SCENARIO

    # The six-part explanation.
    what_it_is: str
    why_it_matters: str
    what_happens: str
    analogy: str

    # What to do.
    instruction: str
    scenario_id: Optional[str] = None
    source: str = ""
    destination: str = ""

    # What the student predicts before checking.
    prediction_prompt: str

    # Where to look, for the "check the result" step.
    result_hint: str

    # Explanation shown once the exercise is complete.
    takeaway: str

    # For a host exercise, what the student could look at instead when
    # their own machine does not have what the exercise needs.
    unavailable_hint: Optional[str] = None

    # An optional route edit the student can make, for edit exercises.
    editable_node: Optional[str] = None
    editable_routes: Optional[List[dict]] = None

    # Check function, set below. Not part of the serialised model.
    check: Optional[Callable[[Scenario, "Exercise"], ExerciseCheck]] = None


def _matched_prefix(trace_result, node_id: str) -> Optional[str]:
    """The prefix the given node selected, if it forwarded."""
    for hop in trace_result.hops:
        if hop.node == node_id and hop.matched is not None:
            return hop.matched.prefix
    return None


def _build_exercises() -> Dict[str, Exercise]:
    exercises: List[Exercise] = []

    # ------------------------------------------------------------------
    # 1. Longest prefix match
    # ------------------------------------------------------------------
    exercises.append(
        Exercise(
            id="longest-prefix",
            title="Which route wins?",
            concept="Longest-prefix match",
            kind="trace",
            what_it_is=(
                "Longest-prefix match is the rule a router uses to pick a route. "
                "It looks at every route whose network contains the destination "
                "address and chooses the one with the most bits in its prefix."
            ),
            why_it_matters=(
                "It is why a specific route beats a general one. A route for "
                "10.0.2.0/24 is more specific than 10.0.0.0/8, so the router "
                "uses the /24 even though the /8 also covers the address."
            ),
            what_happens=(
                "The packet arrives with the address 10.0.1.100. The router "
                "collects the routes that contain it: 10.0.0.0/8, 10.0.1.0/24 "
                "and 0.0.0.0/0 all contain it. The /24 has the most bits, so "
                "it is the one that gets used."
            ),
            analogy=(
                "Postcodes. A full postcode picks one house; a shorter one "
                "picks a whole street; 'anywhere' picks the country. You "
                "always use the most precise one that still fits."
            ),
            instruction=(
                "Trace a packet from client to 10.0.1.100 and look at which "
                "route the second router picked."
            ),
            scenario_id="two-routers",
            source="client",
            destination="10.0.1.100",
            prediction_prompt=(
                "Before you look: do you think the router will use 10.0.0.0/8, "
                "10.0.1.0/24, or 0.0.0.0/0?"
            ),
            result_hint=(
                "Open the second hop and read the Route selected row, then the "
                "Prefix length row."
            ),
            takeaway=(
                "The /24 won because it has more bits. A shorter prefix covers "
                "more addresses but says less about where to send them."
            ),
        )
    )

    # ------------------------------------------------------------------
    # 2. The default route
    # ------------------------------------------------------------------
    exercises.append(
        Exercise(
            id="default-route",
            title="The catch-all route",
            concept="Default route (0.0.0.0/0)",
            kind="trace",
            what_it_is=(
                "A default route is a route for 0.0.0.0/0, which contains "
                "every IPv4 address there is. It is the router's last resort."
            ),
            why_it_matters=(
                "Without a default route a router can only reach the networks "
                "it has specific routes for. Anything else is dropped, and the "
                "packet goes no further."
            ),
            what_happens=(
                "The router looks through its table for a route that covers "
                "the destination. The default route matches everything, so it "
                "is used whenever no more specific route does."
            ),
            analogy=(
                "A receptionist with no particular appointment to offer: you "
                "get passed to whoever is free, rather than being turned away."
            ),
            instruction=(
                "Trace a packet from client to 8.8.8.8, an address that is on "
                "no specific network, and see which route the router falls "
                "back to."
            ),
            scenario_id="client-router-server",
            source="client",
            destination="8.8.8.8",
            prediction_prompt=(
                "There is no route for 8.8.8.8 anywhere. Does the packet "
                "still get sent somewhere?"
            ),
            result_hint=(
                "Look at the first hop. The client uses its own default route "
                "to reach the router; then check the second hop."
            ),
            takeaway=(
                "The default route is what keeps a router useful. It is less "
                "specific than any other route, so it never wins a "
                "longest-prefix contest against one."
            ),
        )
    )

    # ------------------------------------------------------------------
    # 3. Missing route
    # ------------------------------------------------------------------
    exercises.append(
        Exercise(
            id="missing-route",
            title="When there is nowhere to go",
            concept="Unreachable destination",
            kind="trace",
            what_it_is=(
                "An unreachable destination is one the router has no route "
                "for. The packet is dropped rather than forwarded."
            ),
            why_it_matters=(
                "Drops are the most common cause of 'the internet is not "
                "working' for one host. Seeing where a packet dies tells you "
                "which router lacks the route."
            ),
            what_happens=(
                "The router checks every route in its table. None contains the "
                "destination address, and there is no default route to fall "
                "back on, so the packet is dropped right there."
            ),
            analogy=(
                "A courier with no address to go to stands still rather than "
                "guessing a direction."
            ),
            instruction=(
                "Trace a packet to an address that nothing can reach, and find "
                "out exactly where it stopped and why."
            ),
            scenario_id="two-routers",
            source="client",
            destination="203.0.113.99",
            prediction_prompt=(
                "There is a default route on the client. Where exactly does "
                "the packet stop?"
            ),
            result_hint=(
                "Look at the last hop. Its action tells you whether the "
                "packet was dropped, and the explanation says which address "
                "had no route."
            ),
            takeaway=(
                "A drop is a result, not a failure of the tool. The hop that "
                "dropped it is the one missing the route."
            ),
        )
    )

    # ------------------------------------------------------------------
    # 4. Routing loop
    # ------------------------------------------------------------------
    exercises.append(
        Exercise(
            id="routing-loop",
            title="Two routers pointing at each other",
            concept="Routing loop",
            kind="trace",
            what_it_is=(
                "A routing loop happens when each router sends the packet "
                "back to the other, so the packet goes round and round."
            ),
            why_it_matters=(
                "A loop wastes bandwidth and eventually the packet's TTL "
                "reaches zero and it is discarded. Loops are usually caused "
                "by a misconfigured default route."
            ),
            what_happens=(
                "Router 1 sends the packet to Router 2. Router 2's only "
                "matching route sends it back to Router 1. The engine notices "
                "it has seen Router 1 before and stops there."
            ),
            analogy=(
                "Two people each pointing the other at the only door in the "
                "room."
            ),
            instruction=(
                "Trace a packet through the loop scenario and find the hop "
                "where the engine gave up."
            ),
            scenario_id="loop",
            source="r1",
            destination="203.0.113.9",
            prediction_prompt=(
                "Both routers have a default route pointing at the other. "
                "How many hops before the engine stops?"
            ),
            result_hint=(
                "The last hop's action is 'dropped' and its explanation names "
                "the router that appeared twice."
            ),
            takeaway=(
                "The engine stops a loop by remembering where the packet has "
                "been. A real router does the same with the TTL, so the "
                "packet dies on its own."
            ),
        )
    )

    # ------------------------------------------------------------------
    # 5. Changing a route changes the result
    # ------------------------------------------------------------------
    exercises.append(
        Exercise(
            id="change-a-route",
            title="Change a route, change the outcome",
            concept="Editing a routing table",
            kind="edit",
            what_it_is=(
                "Editing a routing table means changing which prefix a router "
                "uses, or where it sends the packet for that prefix."
            ),
            why_it_matters=(
                "This is the connection between a table and behaviour. A "
                "route is not a label; it is an instruction, and changing it "
                "changes what actually happens to the packet."
            ),
            what_happens=(
                "You add a more specific route to the router. The next time a "
                "packet is traced, the engine finds two routes that match, "
                "picks the more specific one, and forwards the packet "
                "differently."
            ),
            analogy=(
                "Changing which exit a driver takes at a junction. The car "
                "still arrives, but it arrives by a different road."
            ),
            instruction=(
                "Add a route for 10.0.0.2/32 to the router, then trace the "
                "packet again and compare which route was chosen."
            ),
            scenario_id="client-router-server",
            source="client",
            destination="10.0.0.2",
            prediction_prompt=(
                "The router currently uses 10.0.0.0/24, its directly "
                "connected network. After you add a /32, which one will it "
                "use and why?"
            ),
            result_hint=(
                "Compare the Route selected row before and after the edit, "
                "and look at the Prefix length row."
            ),
            takeaway=(
                "A /32 is more specific than a /24, so it wins. The engine "
                "did not consult your table in a different order; it applied "
                "the same rule to different data."
            ),
            editable_node="router",
            editable_routes=[
                {
                    "prefix": "10.0.0.2/32",
                    "dev": "eth1",
                    "via": "10.0.0.2",
                    "metric": 5,
                }
            ],
        )
    )

    # ------------------------------------------------------------------
    # 6. Metric tiebreak
    # ------------------------------------------------------------------
    exercises.append(
        Exercise(
            id="metric-tiebreak",
            title="When two routes are equally specific",
            concept="Route metric",
            kind="trace",
            what_it_is=(
                "A metric is a cost attached to a route. When two routes have "
                "the same prefix length, the one with the lower metric is "
                "preferred."
            ),
            why_it_matters=(
                "Prefix length says where to send something. The metric says "
                "which of several equally good ways to get there to take."
            ),
            what_happens=(
                "Both routes cover the destination and both have the same "
                "prefix length, so the router compares their metrics and "
                "takes the smaller one. If the metrics are equal too, the "
                "choice is made deterministically so that every router "
                "picks the same one."
            ),
            analogy=(
                "Two roads of the same length to the same place. The signpost "
                "lists the travel time, and the quicker one wins."
            ),
            instruction=(
                "Add a second route to the router for the same prefix with a "
                "different metric, and watch which one the engine picks."
            ),
            scenario_id="client-router-server",
            source="client",
            destination="10.0.0.2",
            prediction_prompt=(
                "If you give one of the two routes a metric of 5 and the "
                "other 50, which will the router use?"
            ),
            result_hint=(
                "Open the router's hop and read the Metric row."
            ),
            takeaway=(
                "Prefix length is checked first. The metric only matters "
                "when the lengths are equal, and it is what lets an "
                "administrator express a preference."
            ),
            editable_node="router",
            editable_routes=[
                {
                    "prefix": "10.0.0.2/32",
                    "dev": "eth1",
                    "via": "10.0.0.2",
                    "metric": 5,
                },
                {
                    "prefix": "10.0.0.2/32",
                    "dev": "eth1",
                    "via": "10.0.0.2",
                    "metric": 50,
                },
            ],
        )
    )

    # ------------------------------------------------------------------
    # 7. IPv6 is a separate family
    # ------------------------------------------------------------------
    exercises.append(
        Exercise(
            id="ipv6-separate",
            title="IPv6 does not answer to IPv4 routes",
            concept="Address families",
            kind="trace",
            what_it_is=(
                "IPv4 and IPv6 are separate address spaces. A route for one "
                "never matches an address in the other, even when the "
                "prefixes look similar."
            ),
            why_it_matters=(
                "A router that has only IPv4 routes will not forward IPv6 "
                "traffic at all, and the packet is dropped rather than "
                "guessed at."
            ),
            what_happens=(
                "The engine compares the address family of the destination "
                "with the family of each route. Nothing matches, so no route "
                "is selected and the packet is dropped."
            ),
            analogy=(
                "A street address and a postcode. Using the right format for "
                "the wrong one does not get you closer."
            ),
            instruction=(
                "Trace an IPv6 packet in the dual-stack scenario and check "
                "which route family was used."
            ),
            scenario_id="dual-stack",
            source="client",
            destination="2001:db8:2::2",
            prediction_prompt=(
                "The router has both 0.0.0.0/0 and ::/0. Which one applies "
                "to an IPv6 destination?"
            ),
            result_hint=(
                "Open the router's hop. The prefix it selected tells you "
                "which family it used."
            ),
            takeaway=(
                "The families never mix. The IPv6 default route ::/0 is not a "
                "catch-all for IPv4, and 0.0.0.0/0 is not a catch-all for "
                "IPv6."
            ),
        )
    )

    return {ex.id: ex for ex in exercises}


EXERCISES: Dict[str, Exercise] = _build_exercises()


# --------------------------------------------------------------------------
# Exercises that work on the host's own routing table
# --------------------------------------------------------------------------
#
# The exercises above all run against a modelled network. These three run
# against the routing table of the machine the student is sitting at, which
# is the thing they will actually meet.
#
# The table is read from the kernel and is OBSERVED. The conclusion drawn
# from it is INFERRED, and the two are kept apart. Nothing here changes a
# route: the collector is read-only.
#
# These live in their own registry rather than in EXERCISES so that the
# existing exercise list, and the seven exercises in it, are untouched.


def _build_host_exercises() -> Dict[str, Exercise]:
    exercises: List[Exercise] = []

    # ------------------------------------------------------------------
    # H1. Which route would this machine use?
    # ------------------------------------------------------------------
    exercises.append(
        Exercise(
            id="host-which-route",
            title="Which route would your machine use?",
            concept="Reading your own routing table",
            kind=ExerciseKind.LOOKUP,
            table_source=TableSource.HOST,
            what_it_is=(
                "Your machine has a routing table, and it uses it to decide "
                "where to send every packet it forwards. The rule is the same "
                "longest-prefix match the modelled exercises use: the route "
                "with the most bits that covers the destination wins."
            ),
            why_it_matters=(
                "This is the table you will actually meet. When a packet to "
                "some address does not arrive, the first place to look is "
                "which route your own machine would have used for it, and "
                "which other routes it passed on the way."
            ),
            what_happens=(
                "Your machine's table is read with ip -j route show. The same "
                "routing engine that runs the modelled exercises is then "
                "asked what it would do with the address you picked. It lists "
                "every route that covers the address, picks the most specific "
                "one, and tells you which candidates it beat and why."
            ),
            analogy=(
                "The same signpost post you have been reading about, except "
                "this one is the real post outside your own house."
            ),
            instruction=(
                "Pick one of your machine's own addresses, or one of your "
                "network's addresses, and find out which route your machine "
                "would use for it."
            ),
            source="host",
            prediction_prompt=(
                "Before you look: does your machine have a route more specific "
                "than the default one for this address, or would the default "
                "route take everything?"
            ),
            result_hint=(
                "Read the selected route, then the list of candidates it beat. "
                "If the default route won, that is a real answer about your "
                "machine, not a failure."
            ),
            takeaway=(
                "A table with one default route in it is a real and common "
                "table. Longest-prefix match still applies; it simply has "
                "less to choose from."
            ),
            unavailable_hint=(
                "Your machine's routing table could not be read. Run "
                "`ip route show` in a terminal and read the lines yourself - "
                "that is the same table this exercise would have used."
            ),
        )
    )

    # ------------------------------------------------------------------
    # H2. Is the default route shadowed?
    # ------------------------------------------------------------------
    exercises.append(
        Exercise(
            id="host-default-shadowed",
            title="Is your default route shadowed?",
            concept="Route shadowing",
            kind=ExerciseKind.LOOKUP,
            table_source=TableSource.HOST,
            what_it_is=(
                "A default route matches every address, so on its own it says "
                "very little. The routes that make it meaningful are the more "
                "specific ones beside it. Where a more specific route exists, "
                "it takes the traffic for its own network and the default "
                "route is shadowed for that part of the address space."
            ),
            why_it_matters=(
                "A default route you did not know about, and a specific route "
                "you did not know about, can send the same traffic in "
                "different directions. Reading the table as a whole, rather "
                "than one line at a time, is how you see that."
            ),
            what_happens=(
                "The analysis finds the default route and works out which "
                "more specific routes in the table cover part of the address "
                "space it would otherwise have handled. Those specific "
                "routes are what the default route really stands in for, and "
                "the ones that take its traffic."
            ),
            analogy=(
                "A signpost that says 'city centre, this way' for every "
                "journey, with smaller signs for particular streets hidden "
                "along the way."
            ),
            instruction=(
                "Find a destination that one of your own more specific routes "
                "covers, and see how much of the address space your default "
                "route really handles."
            ),
            source="host",
            prediction_prompt=(
                "How much of the address space does your default route really "
                "handle? All of it, or only what nothing more specific "
                "covers?"
            ),
            result_hint=(
                "Look at the default route finding: it names the more "
                "specific routes that take traffic away from it."
            ),
            takeaway=(
                "A default route is not doing all the work it appears to. "
                "Count the more specific routes beside it and the picture "
                "changes."
            ),
            unavailable_hint=(
                "Your machine's table does not have a default route beside a "
                "more specific one, so there is nothing here to compare. Run "
                "`ip route show` and look at the `default` line and the "
                "network lines around it."
            ),
        )
    )

    # ------------------------------------------------------------------
    # H3. What is the gateway?
    # ------------------------------------------------------------------
    exercises.append(
        Exercise(
            id="host-gateway",
            title="What is your gateway?",
            concept="Default gateway",
            kind=ExerciseKind.LOOKUP,
            table_source=TableSource.HOST,
            what_it_is=(
                "The default gateway is the next hop your machine sends "
                "traffic to when the destination is not on a network it is "
                "attached to. It is the next hop on the default route."
            ),
            why_it_matters=(
                "Most of what people mean by 'the router' is this one "
                "address. It is the first hop out of your machine, and it is "
                "where a traceroute's first line comes from."
            ),
            what_happens=(
                "An address outside your local networks is not covered by any "
                "connected route, so the default route is the one that "
                "matches. Its next hop is your gateway. The analysis reads "
                "both the route and the next hop straight out of your "
                "machine's table."
            ),
            analogy=(
                "The door of the building you are in, before the street. The "
                "address on the other side of it is where everything outside "
                "goes."
            ),
            instruction=(
                "Work out which next hop your machine would use for an "
                "address outside your local networks, then check it against "
                "your table."
            ),
            source="host",
            prediction_prompt=(
                "Your machine has more than one interface. Which one does "
                "traffic to the outside world leave by, and which address "
                "does it hand over to?"
            ),
            result_hint=(
                "Read the selected route and its next hop. If you typed an "
                "answer, it is checked against the table."
            ),
            takeaway=(
                "The gateway is not a setting you configure for its own sake. "
                "It is whatever next hop the default route names, and reading "
                "it out of the table tells you which interface is the way "
                "out."
            ),
            unavailable_hint=(
                "Your machine has no default route, so it has no default "
                "gateway. Run `ip route show` and look for a line starting "
                "with `default` - if there is none, this machine really has "
                "no way out."
            ),
        )
    )

    return {ex.id: ex for ex in exercises}


HOST_EXERCISES: Dict[str, Exercise] = _build_host_exercises()


def exercise_list() -> List[dict]:
    """Summaries of every exercise."""
    return [
        {
            "id": ex.id,
            "title": ex.title,
            "concept": ex.concept,
            "kind": ex.kind,
            "scenario_id": ex.scenario_id,
            "source": ex.source,
            "destination": ex.destination,
        }
        for ex in EXERCISES.values()
    ]


def host_exercise_list() -> List[dict]:
    """Summaries of the exercises that work on the host's own table."""
    return [
        {
            "id": ex.id,
            "title": ex.title,
            "concept": ex.concept,
            "kind": ex.kind,
            "table_source": ex.table_source.value,
            "source": ex.source,
        }
        for ex in HOST_EXERCISES.values()
    ]


def get_host_exercise(exercise_id: str) -> Optional[Exercise]:
    """One host exercise by id."""
    return HOST_EXERCISES.get(exercise_id)


def get_exercise(exercise_id: str) -> Optional[Exercise]:
    """One exercise by id."""
    return EXERCISES.get(exercise_id)


# --------------------------------------------------------------------------
# HTTP endpoints for the host-table exercises
# --------------------------------------------------------------------------
#
# These live in their own router so the existing /api/exercises list, and
# the seven exercises in it, are left exactly as they were.
#
# Register the router in main.py with:
#     from app.exercises import host_exercise_router
#     app.include_router(host_exercise_router)

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

host_exercise_router = APIRouter(prefix="/api/host-exercises", tags=["exercises"])


class HostExerciseCheckRequest(BaseModel):
    """Request to check a host exercise."""

    destination: Optional[str] = Field(
        None,
        description=(
            "The address to work with. When omitted, the exercise picks one "
            "from the host's own table."
        ),
    )
    answer: Optional[str] = Field(
        None,
        description="What the student thinks the answer is, if they are answering.",
    )


@host_exercise_router.get("")
def list_host_exercises():
    """List the exercises that work on the host's own routing table."""
    return host_exercise_list()


@host_exercise_router.get("/{exercise_id}")
def get_host_exercise_detail(exercise_id: str):
    """The full explanation and instructions for one host exercise."""
    exercise = get_host_exercise(exercise_id)
    if exercise is None:
        raise HTTPException(status_code=404, detail=f"Unknown exercise: {exercise_id}")
    return exercise.model_dump()


@host_exercise_router.post("/{exercise_id}/check")
async def check_host_exercise(exercise_id: str, body: HostExerciseCheckRequest):
    """
    Check a host exercise against the student's own routing table.

    The table is read from the kernel with `ip -j route show` and is
    OBSERVED. The conclusion drawn from it is INFERRED. The two are reported
    separately and never merged.

    When the machine's table does not have what the exercise needs, the
    result says so plainly and points at what the student could look at
    instead. It does not fall back to a modelled table, and it does not
    pretend the exercise succeeded.
    """
    from app.exercise_checks import check_host_exercise as _check

    if get_host_exercise(exercise_id) is None:
        raise HTTPException(status_code=404, detail=f"Unknown exercise: {exercise_id}")

    state = await _check(
        exercise_id,
        destination=body.destination,
        answer=body.answer,
    )
    if state is None:
        raise HTTPException(status_code=404, detail=f"Unknown exercise: {exercise_id}")
    return state.model_dump()
