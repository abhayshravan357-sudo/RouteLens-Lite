"""
RouteLens Lite - Exercise Verification

Checks whether an exercise has actually been completed by running the
real routing engine and looking at its output.

An exercise is never marked complete because the student opened it, or
because they typed the expected word. The check is always the engine's
own answer.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import BaseModel, Field

from app.exercises import EXERCISES, Exercise, ExerciseCheck
from app.scenario import Scenario, trace


class ExerciseState(BaseModel):
    """The result of checking an exercise."""

    exercise_id: str
    title: str
    concept: str
    complete: bool
    checks: List[ExerciseCheck] = Field(default_factory=list)
    explanation: str = ""
    trace_status: Optional[str] = None
    selected_route: Optional[str] = None
    selected_prefix_length: Optional[int] = None
    matched_route: Optional[str] = None
    hops: List[dict] = Field(default_factory=list)


def _check_longest_prefix(scenario: Scenario, exercise: Exercise) -> List[ExerciseCheck]:
    """The router must have picked the more specific prefix."""
    result = trace(scenario, exercise.source, exercise.destination)

    router_hop = next((h for h in result.hops if h.node == "r1"), None)
    if router_hop is None or router_hop.matched is None:
        return [
            ExerciseCheck(
                description="The second router forwards the packet",
                satisfied=False,
                detail="The trace did not reach the second router.",
            )
        ]

    prefix = router_hop.matched.prefix
    prefixlen = router_hop.matched.net.prefixlen
    chosen_is_more_specific = prefixlen > 8  # more specific than the /8

    return [
        ExerciseCheck(
            description="The second router forwarded the packet",
            satisfied=True,
            detail=f"It chose {prefix}.",
        ),
        ExerciseCheck(
            description="It chose a route more specific than 10.0.0.0/8",
            satisfied=chosen_is_more_specific,
            detail=(
                f"{prefix} is /{prefixlen}, which is more specific than /8."
                if chosen_is_more_specific
                else f"{prefix} is /{prefixlen}. The /8 would have won, which is "
                "not what longest-prefix match should do."
            ),
        ),
    ]


def _check_default_route(scenario: Scenario, exercise: Exercise) -> List[ExerciseCheck]:
    """Both the client and the router must fall back to a default route."""
    result = trace(scenario, exercise.source, exercise.destination)

    first_hop = result.hops[0] if result.hops else None
    used_default = bool(
        first_hop
        and first_hop.matched is not None
        and first_hop.matched.prefix == "0.0.0.0/0"
    )

    router_hop = next((h for h in result.hops if h.node == "router"), None)

    return [
        ExerciseCheck(
            description="The client sent the packet using its default route",
            satisfied=used_default,
            detail=(
                "It used 0.0.0.0/0, which covers every address."
                if used_default
                else "The client did not fall back to a default route."
            ),
        ),
        ExerciseCheck(
            description="The router also fell back to its default route",
            satisfied=bool(
                router_hop
                and router_hop.matched is not None
                and router_hop.matched.prefix == "0.0.0.0/0"
            ),
            detail=(
                f"It used {router_hop.matched.prefix}."
                if router_hop and router_hop.matched
                else "The router did not reach a route decision."
            ),
        ),
    ]


def _check_missing_route(scenario: Scenario, exercise: Exercise) -> List[ExerciseCheck]:
    """The packet must have been dropped, with a reason."""
    result = trace(scenario, exercise.source, exercise.destination)

    dropped = result.status in ("no_route", "unresolved_next_hop", "not_forwarding")
    explained = bool(result.hops and result.hops[-1].explanation)

    return [
        ExerciseCheck(
            description="The packet did not reach the destination",
            satisfied=dropped,
            detail=f"The trace ended with status '{result.status}'.",
        ),
        ExerciseCheck(
            description="The last hop explains why",
            satisfied=explained,
            detail=result.hops[-1].explanation if result.hops else "No explanation given.",
        ),
    ]


def _check_routing_loop(scenario: Scenario, exercise: Exercise) -> List[ExerciseCheck]:
    """The engine must have detected the loop."""
    result = trace(scenario, exercise.source, exercise.destination)

    return [
        ExerciseCheck(
            description="The engine detected a routing loop",
            satisfied=result.status == "loop",
            detail=f"The trace ended with status '{result.status}'.",
        ),
        ExerciseCheck(
            description="The last hop names the router that repeated",
            satisfied=bool(
                result.hops
                and "loop" in result.hops[-1].explanation.lower()
            ),
            detail=result.hops[-1].explanation if result.hops else "No explanation given.",
        ),
    ]


def _check_change_a_route(scenario: Scenario, exercise: Exercise) -> List[ExerciseCheck]:
    """A more specific route must now be chosen."""
    result = trace(scenario, exercise.source, exercise.destination)

    router_hop = next((h for h in result.hops if h.node == "router"), None)
    if router_hop is None or router_hop.matched is None:
        return [
            ExerciseCheck(
                description="The router forwarded the packet",
                satisfied=False,
                detail="The trace did not reach the router.",
            )
        ]

    matched = router_hop.matched
    is_static = matched.source == "static"
    is_specific = matched.net.prefixlen >= 32

    return [
        ExerciseCheck(
            description="The router now uses the route you added",
            satisfied=is_static,
            detail=(
                f"It chose {matched.prefix} ({matched.source})."
                if is_static
                else f"It still chose {matched.prefix} ({matched.source}), "
                "which is a connected network rather than your route."
            ),
        ),
        ExerciseCheck(
            description="That route is more specific than the connected /24",
            satisfied=is_specific,
            detail=(
                f"{matched.prefix} is /{matched.net.prefixlen}."
                if is_specific
                else f"{matched.prefix} is /{matched.net.prefixlen}, which is not "
                "more specific than the connected /24."
            ),
        ),
    ]


def _check_metric_tiebreak(scenario: Scenario, exercise: Exercise) -> List[ExerciseCheck]:
    """The lower metric must win."""
    result = trace(scenario, exercise.source, exercise.destination)

    router_hop = next((h for h in result.hops if h.node == "router"), None)
    if router_hop is None or router_hop.matched is None:
        return [
            ExerciseCheck(
                description="The router forwarded the packet",
                satisfied=False,
                detail="The trace did not reach the router.",
            )
        ]

    matched = router_hop.matched
    low_metric_won = matched.metric == 5

    return [
        ExerciseCheck(
            description="The router used the route with the lower metric",
            satisfied=low_metric_won,
            detail=(
                f"It chose {matched.prefix} with metric {matched.metric}."
                if low_metric_won
                else f"It chose {matched.prefix} with metric {matched.metric}, "
                "but the route with metric 5 should have won."
            ),
        ),
        ExerciseCheck(
            description="The two candidate routes really did tie on prefix length",
            satisfied=len(router_hop.candidates) > 1,
            detail=(
                f"{len(router_hop.candidates)} route(s) matched; the metric "
                "decided between them."
                if len(router_hop.candidates) > 1
                else "Only one route matched, so the metric was not tested."
            ),
        ),
    ]


def _check_ipv6_separate(scenario: Scenario, exercise: Exercise) -> List[ExerciseCheck]:
    """Only IPv6 routes may be selected for an IPv6 destination."""
    result = trace(scenario, exercise.source, exercise.destination)

    router_hop = next((h for h in result.hops if h.node == "router"), None)
    if router_hop is None or router_hop.matched is None:
        return [
            ExerciseCheck(
                description="The router forwarded the packet",
                satisfied=False,
                detail="The trace did not reach the router.",
            )
        ]

    matched = router_hop.matched
    used_v6 = matched.net.version == 6

    return [
        ExerciseCheck(
            description="The router used an IPv6 route",
            satisfied=used_v6,
            detail=(
                f"It chose {matched.prefix}, an IPv6 route."
                if used_v6
                else f"It chose {matched.prefix}, an IPv4 route, for an IPv6 "
                "destination. That should not happen."
            ),
        ),
    ]


#: The check for each exercise, keyed by exercise id.
_CHECKS: Dict[str, Callable[[Scenario, Exercise], List[ExerciseCheck]]] = {
    "longest-prefix": _check_longest_prefix,
    "default-route": _check_default_route,
    "missing-route": _check_missing_route,
    "routing-loop": _check_routing_loop,
    "change-a-route": _check_change_a_route,
    "metric-tiebreak": _check_metric_tiebreak,
    "ipv6-separate": _check_ipv6_separate,
}


def check_exercise(exercise_id: str, scenario: Scenario) -> Optional[ExerciseState]:
    """
    Run the engine and report whether an exercise is complete.

    Returns None if the exercise is unknown.
    """
    exercise = EXERCISES.get(exercise_id)
    if exercise is None:
        return None

    check_fn = _CHECKS.get(exercise_id)
    checks = check_fn(scenario, exercise) if check_fn else []

    result = trace(scenario, exercise.source, exercise.destination)
    router_hop = next(
        (h for h in result.hops if h.node in ("router", "r1")), None
    )

    return ExerciseState(
        exercise_id=exercise.id,
        title=exercise.title,
        concept=exercise.concept,
        complete=bool(checks) and all(c.satisfied for c in checks),
        checks=checks,
        explanation=exercise.takeaway if all(c.satisfied for c in checks) else "",
        trace_status=result.status,
        selected_route=(
            router_hop.matched.prefix if router_hop and router_hop.matched else None
        ),
        selected_prefix_length=(
            router_hop.matched.net.prefixlen
            if router_hop and router_hop.matched
            else None
        ),
        matched_route=(
            router_hop.matched.prefix if router_hop and router_hop.matched else None
        ),
        hops=[
            {
                "hop_number": h.hop_number,
                "node": h.node,
                "action": h.action,
                "explanation": h.explanation,
                "matched_prefix": h.matched.prefix if h.matched else None,
            }
            for h in result.hops
        ],
    )
