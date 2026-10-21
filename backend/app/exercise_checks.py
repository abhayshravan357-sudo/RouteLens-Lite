"""
RouteLens Lite - Exercise Verification

Checks whether an exercise has actually been completed by running the
real routing engine and looking at its output.

An exercise is never marked complete because the student opened it, or
because they typed the expected word. The check is always the engine's
own answer.
"""

from __future__ import annotations

import ipaddress
from typing import Dict, List, Optional

from pydantic import BaseModel, Field

from app.exercises import EXERCISES, HOST_EXERCISES, Exercise, ExerciseCheck
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


# ---------------------------------------------------------------------------
# Exercises that work on the host's own routing table
# ---------------------------------------------------------------------------
#
# The table is read from the kernel with `ip -j route show`. That is
# OBSERVED. The conclusion drawn from it is INFERRED, and the two are
# reported separately here so the student can tell a measurement from a
# deduction.
#
# Nothing in this section changes a route. The collector is read-only.
#
# When the machine's table does not contain what an exercise needs, the
# result says so plainly and points at what the student could look at
# instead. It never falls back to the modelled table, and it never claims
# an exercise was completed when it was not.


class HostExerciseState(BaseModel):
    """The result of checking an exercise against the host's own table."""

    exercise_id: str
    title: str
    concept: str
    complete: bool = False
    checks: List[ExerciseCheck] = Field(default_factory=list)
    explanation: str = ""

    # Whether the machine's table has what this exercise needs.
    available: bool = True
    unavailable_reason: Optional[str] = None

    # What the student could look at instead, when it does not.
    message: str = ""

    # The two claims, kept apart.
    #
    # "observed" means the table was read out of the kernel. "inferred" means
    # a conclusion was drawn from that table. When the table could not be
    # read, neither claim holds, and both are "unknown" rather than being
    # left at their defaults, which would claim a measurement that never
    # happened.
    table_provenance: str = "observed"
    analysis_provenance: str = "inferred"

    # What the analysis found.
    destination: Optional[str] = None
    selected_route: Optional[str] = None
    selected_prefix_length: Optional[int] = None
    selected_next_hop: Optional[str] = None
    selected_interface: Optional[str] = None
    candidates: List[dict] = Field(default_factory=list)
    beaten: List[dict] = Field(default_factory=list)
    shadow: Optional[dict] = None
    default_routes: List[str] = Field(default_factory=list)
    table_routes: List[dict] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)


#: Addresses tried when looking for one that lies outside the host's own
#: networks. They are only ever lookup keys in the local table. No request
#: is made to any of them.
_OUTSIDE_CANDIDATES = ["1.1.1.1", "8.8.8.8", "9.9.9.9", "203.0.113.1"]


def _host_entries(routes, ip_version: str):
    """Turn collected routes into teaching-model entries."""
    from app.route_analysis import to_teaching_entries

    return to_teaching_entries(list(routes or []), ip_version=ip_version)


def _entry_dict(entry) -> dict:
    """A route entry as a plain dict for the response."""
    network = entry.get_network()
    return {
        "destination": entry.destination,
        "prefix_length": network.prefixlen,
        "next_hop": entry.next_hop,
        "interface": entry.interface,
        "metric": entry.metric,
        "next_hop_type": entry.next_hop_type.value,
        "provenance": entry.provenance.value,
    }


def _sample_address_in(network) -> Optional[str]:
    """A usable address inside a network, for use as a destination."""
    if network.num_addresses <= 2:
        return str(network.network_address)
    return str(network.network_address + 1)


def _address_outside_specific_routes(entries) -> Optional[str]:
    """An address that only the default route covers.

    That is what "outside your local networks" means: nothing more
    specific in the table claims it, so the default route is the one that
    would be used.
    """
    specific = []
    for entry in entries:
        network = entry.get_network()
        if network.prefixlen > 0:
            specific.append(network)

    for candidate in _OUTSIDE_CANDIDATES:
        address = ipaddress.ip_address(candidate)
        if not any(address in network for network in specific):
            return candidate
    return None


def _host_addresses(interfaces) -> List[str]:
    """The host's own addresses, IPv4 first."""
    v4: List[str] = []
    v6: List[str] = []
    for interface in interfaces or []:
        v4.extend(interface.ipv4_addresses)
        v6.extend(interface.ipv6_addresses)
    return v4 + v6


def _unavailable(
    exercise: Exercise,
    reason: str,
    message: Optional[str] = None,
    table_read: bool = True,
) -> HostExerciseState:
    """A result for a machine whose table cannot answer this exercise.

    Args:
        table_read: Whether the routing table was successfully read. It was
            read in every case except a failed collection, and the two
            provenance claims depend on it: a table that was never read
            cannot be "observed", and nothing was inferred from it.
    """
    return HostExerciseState(
        exercise_id=exercise.id,
        title=exercise.title,
        concept=exercise.concept,
        complete=False,
        available=False,
        unavailable_reason=reason,
        message=message or exercise.unavailable_hint or "",
        table_provenance="observed" if table_read else "unknown",
        analysis_provenance="inferred" if table_read else "unknown",
        checks=[
            ExerciseCheck(
                description="This exercise can be run on this machine",
                satisfied=False,
                detail=reason,
            )
        ],
    )


def _unreadable_table(exercise: Exercise, error: Optional[str]) -> HostExerciseState:
    """The table could not be read at all. No fallback is used."""
    reason = "Your machine's routing table could not be read."
    if error:
        reason = f"{reason} ({error})"
    return _unavailable(exercise, reason, table_read=False)


async def _collect_host_table(ip_version: str = "ipv4"):
    """Read the host's routing table and its interfaces.

    Returns (routes_result, interfaces_result).
    """
    from app.network_collector import get_network_collector

    collector = get_network_collector()
    routes_result = await collector.collect_routes(ip_version)
    interfaces_result = await collector.collect_interfaces()
    return routes_result, interfaces_result


def _check_host_which_route(
    exercise: Exercise,
    entries,
    interfaces,
    destination: Optional[str],
) -> HostExerciseState:
    """Which route would this machine use for this address?"""
    from app.route_analysis import analyse_destination
    from app.routing_logic import find_matching_routes, select_best_route

    if not entries:
        return _unavailable(
            exercise,
            "Your machine's routing table has no routes in it that this "
            "exercise can use.",
        )

    # The student picks an address. With no pick, use one of the host's own.
    if not destination:
        own = _host_addresses(interfaces)
        if not own:
            return _unavailable(
                exercise,
                "Your machine has no addresses of its own to try, so there is "
                "no address to look up.",
            )
        destination = own[0]

    analysis = analyse_destination(destination, entries)

    if not analysis.matched:
        return HostExerciseState(
            exercise_id=exercise.id,
            title=exercise.title,
            concept=exercise.concept,
            complete=False,
            available=True,
            message=(
                f"No route in your machine's table covers {destination}, so "
                f"traffic to it would not be forwarded at all. That is a real "
                f"answer about your machine."
            ),
            destination=destination,
            checks=[
                ExerciseCheck(
                    description="A route was found for this address",
                    satisfied=False,
                    detail=(
                        f"No route in the table covers {destination}. Your "
                        f"machine would not forward traffic to it."
                    ),
                )
            ],
        )

    selected = analysis.selected

    # Verify the answer against the rule rather than trusting the report:
    # the winner must have the longest prefix, and the lowest metric among
    # the routes with that prefix.
    matching = find_matching_routes(destination, entries)
    longest = max(e.get_network().prefixlen for e in matching)
    at_longest = [e for e in matching if e.get_network().prefixlen == longest]
    lowest_metric = min(e.metric for e in at_longest)

    rule_followed = (
        selected is not None
        and selected.get_network().prefixlen == longest
        and selected.metric == lowest_metric
    )

    # Every route that matched but did not win must be listed as having lost.
    accounted = len(analysis.candidates) == len(analysis.beaten) + 1
    beaten_named = all(c.destination for c in analysis.beaten)

    if analysis.beaten:
        beaten_detail = (
            "It beat "
            + ", ".join(
                f"{c.destination} (/{c.prefix_length}, metric {c.metric})"
                for c in analysis.beaten
            )
            + "."
        )
    else:
        beaten_detail = (
            "Nothing else in your table covers this address, so there was no "
            "other candidate to beat. The default route is doing all the work "
            "here, and that is a normal table to have."
        )

    is_default = analysis.is_default_route

    checks = [
        ExerciseCheck(
            description="A route was found for this address",
            satisfied=True,
            detail=(
                f"Your machine would use {selected.destination} "
                f"(/{selected.get_network().prefixlen})"
                + (
                    f" via {selected.next_hop}"
                    if selected.next_hop
                    else " directly, with no next hop"
                )
                + f" out of {selected.interface}."
            ),
        ),
        ExerciseCheck(
            description=(
                "The route named is the one longest-prefix match would choose"
            ),
            satisfied=rule_followed,
            detail=(
                f"{selected.destination} is /{selected.get_network().prefixlen} "
                f"with metric {selected.metric}, which is the longest prefix "
                f"and the lowest metric among the routes that cover "
                f"{destination}."
                if rule_followed
                else f"The reported route {selected.destination} does not "
                f"follow the rule, so the answer is wrong."
            ),
        ),
        ExerciseCheck(
            description="The routes that lost are named",
            satisfied=accounted and beaten_named,
            detail=beaten_detail,
        ),
    ]

    if is_default:
        checks.append(
            ExerciseCheck(
                description=(
                    "The default route was used because nothing more specific "
                    "covers this address"
                ),
                satisfied=True,
                detail=(
                    f"Your table has no route more specific than the default "
                    f"one for {destination}, so the default route is what "
                    f"would be used. That is the honest answer for this "
                    f"machine."
                ),
            )
        )

    complete = all(c.satisfied for c in checks)

    return HostExerciseState(
        exercise_id=exercise.id,
        title=exercise.title,
        concept=exercise.concept,
        complete=complete,
        available=True,
        checks=checks,
        explanation=exercise.takeaway if complete else "",
        destination=destination,
        selected_route=selected.destination,
        selected_prefix_length=selected.get_network().prefixlen,
        selected_next_hop=selected.next_hop,
        selected_interface=selected.interface,
        candidates=[c.model_dump() for c in analysis.candidates],
        beaten=[c.model_dump() for c in analysis.beaten],
        default_routes=[e.destination for e in entries if e.get_network().prefixlen == 0],
        table_routes=[_entry_dict(e) for e in entries],
        limitations=analysis.limitations,
    )


def _check_host_default_shadowed(
    exercise: Exercise,
    entries,
    interfaces,
    destination: Optional[str],
) -> HostExerciseState:
    """Is the default route shadowed by a more specific route?"""
    from app.route_analysis import analyse_destination, summarise_default_coverage

    default_entries = [e for e in entries if e.get_network().prefixlen == 0]
    if not default_entries:
        return _unavailable(
            exercise,
            "Your machine has no default route, so there is no default route "
            "to be shadowed.",
        )

    specific = [e for e in entries if e.get_network().prefixlen > 0]
    if not specific:
        return _unavailable(
            exercise,
            "Your machine's default route is the only route in the table, so "
            "nothing is shadowing it. It covers the whole address space on "
            "its own.",
        )

    default_entry = default_entries[0]

    # The student picks a destination their own more specific route covers.
    if not destination:
        for entry in specific:
            sample = _sample_address_in(entry.get_network())
            if sample:
                destination = sample
                break

    if not destination:
        return _unavailable(
            exercise,
            "Your machine's more specific routes do not contain an address "
            "that can be used as a destination.",
        )

    analysis = analyse_destination(destination, entries)
    finding = summarise_default_coverage(entries, default_entry)

    # The destination must be claimed by a more specific route, not the
    # default one.
    covered_by_specific = analysis.selected is not None and (
        analysis.selected.get_network().prefixlen > 0
    )

    # The finding must name routes that really are in the table.
    table_destinations = {e.destination for e in entries}
    named = list(finding.more_specific_destinations)
    all_real = all(d in table_destinations for d in named)

    shadowed = bool(named)

    checks = [
        ExerciseCheck(
            description="The default route is reported as covering only part of the address space",
            satisfied=shadowed,
            detail=finding.explanation,
        ),
        ExerciseCheck(
            description="The more specific routes that take its traffic are named",
            satisfied=shadowed and all_real,
            detail=(
                "It named "
                + ", ".join(named)
                + ", and every one of them is in your table."
                if shadowed and all_real
                else (
                    "It named routes that are not in your table, so the "
                    "finding is wrong."
                    if shadowed
                    else "It named no more specific routes, so nothing is "
                    "taking traffic away from the default route."
                )
            ),
        ),
        ExerciseCheck(
            description="The destination is covered by the more specific route, not the default one",
            satisfied=covered_by_specific,
            detail=(
                f"{destination} is matched by "
                f"{analysis.selected.destination} "
                f"(/{analysis.selected.get_network().prefixlen}), which is more "
                f"specific than the default route."
                if covered_by_specific
                else f"{destination} would be handled by the default route, so "
                f"it is not an address that shows the shadowing."
            ),
        ),
    ]

    complete = all(c.satisfied for c in checks)

    return HostExerciseState(
        exercise_id=exercise.id,
        title=exercise.title,
        concept=exercise.concept,
        complete=complete,
        available=True,
        checks=checks,
        explanation=exercise.takeaway if complete else "",
        destination=destination,
        selected_route=analysis.selected.destination if analysis.selected else None,
        selected_prefix_length=(
            analysis.selected.get_network().prefixlen if analysis.selected else None
        ),
        selected_next_hop=analysis.selected.next_hop if analysis.selected else None,
        selected_interface=analysis.selected.interface if analysis.selected else None,
        candidates=[c.model_dump() for c in analysis.candidates],
        beaten=[c.model_dump() for c in analysis.beaten],
        shadow=finding.model_dump(),
        default_routes=[e.destination for e in default_entries],
        table_routes=[_entry_dict(e) for e in entries],
        limitations=analysis.limitations,
    )


def _check_host_gateway(
    exercise: Exercise,
    entries,
    interfaces,
    destination: Optional[str],
    answer: Optional[str],
) -> HostExerciseState:
    """What next hop would this machine use for an address outside its networks?"""
    from app.route_analysis import analyse_destination

    default_entries = [e for e in entries if e.get_network().prefixlen == 0]
    if not default_entries:
        return _unavailable(
            exercise,
            "Your machine has no default route, so it has no default gateway.",
        )

    default_entry = default_entries[0]
    if not default_entry.next_hop:
        return _unavailable(
            exercise,
            "Your default route sends traffic directly rather than through a "
            "next hop, so there is no gateway address to find.",
        )

    if not destination:
        destination = _address_outside_specific_routes(entries)
    if not destination:
        return _unavailable(
            exercise,
            "Every address in your table is claimed by a more specific "
            "route, so there is no way out of your local networks to test.",
        )

    analysis = analyse_destination(destination, entries)
    selected = analysis.selected

    used_default = selected is not None and selected.get_network().prefixlen == 0
    gateway = selected.next_hop if selected else None

    if answer is None:
        answer_check = ExerciseCheck(
            description="You identified the next hop your machine would use",
            satisfied=False,
            detail=(
                "You have not said which next hop you think your machine "
                "would use. Look at the `default` line of `ip route show` and "
                "type the address it hands traffic to."
            ),
        )
    else:
        answer_check = ExerciseCheck(
            description="You identified the next hop your machine would use",
            satisfied=bool(gateway) and answer.strip() == gateway,
            detail=(
                f"You said {answer}, and that is the next hop on the default "
                f"route."
                if gateway and answer.strip() == gateway
                else f"You said {answer}, but the default route hands traffic "
                f"to {gateway}."
            ),
        )

    checks = [
        ExerciseCheck(
            description="The default route is the one your machine would use",
            satisfied=used_default,
            detail=(
                f"{destination} is outside your local networks, so the "
                f"default route {selected.destination} is what would be used."
                if used_default
                else f"{destination} is claimed by a more specific route, so "
                f"it is not an address outside your local networks."
            ),
        ),
        ExerciseCheck(
            description="That route has a next hop",
            satisfied=bool(gateway),
            detail=(
                f"The next hop is {gateway}."
                if gateway
                else "The default route has no next hop."
            ),
        ),
        answer_check,
    ]

    complete = all(c.satisfied for c in checks)

    return HostExerciseState(
        exercise_id=exercise.id,
        title=exercise.title,
        concept=exercise.concept,
        complete=complete,
        available=True,
        checks=checks,
        explanation=exercise.takeaway if complete else "",
        destination=destination,
        selected_route=selected.destination if selected else None,
        selected_prefix_length=(
            selected.get_network().prefixlen if selected else None
        ),
        selected_next_hop=gateway,
        selected_interface=selected.interface if selected else None,
        candidates=[c.model_dump() for c in analysis.candidates],
        beaten=[c.model_dump() for c in analysis.beaten],
        default_routes=[e.destination for e in default_entries],
        table_routes=[_entry_dict(e) for e in entries],
        limitations=analysis.limitations,
    )


#: The check for each host exercise, keyed by exercise id.
_HOST_CHECKS = {
    "host-which-route": _check_host_which_route,
    "host-default-shadowed": _check_host_default_shadowed,
    "host-gateway": _check_host_gateway,
}


async def check_host_exercise(
    exercise_id: str,
    destination: Optional[str] = None,
    answer: Optional[str] = None,
) -> Optional[HostExerciseState]:
    """
    Run an exercise against the host's own routing table.

    Args:
        exercise_id: Which host exercise to check.
        destination: The address to work with. When omitted, the exercise
            picks one from the host's own table.
        answer: What the student thinks the answer is.

    Returns:
        A HostExerciseState, or None if the exercise id is unknown.
    """
    exercise = HOST_EXERCISES.get(exercise_id)
    if exercise is None:
        return None

    check_fn = _HOST_CHECKS.get(exercise_id)
    if check_fn is None:
        return None

    # Work out which address family to read. An IPv6 destination is answered
    # from the IPv6 table, and an IPv4 one from the IPv4 table.
    ip_version = "ipv4"
    if destination:
        try:
            address = ipaddress.ip_address(destination.strip())
        except ValueError:
            address = None
        if address is not None and address.version == 6:
            ip_version = "ipv6"

    routes_result, interfaces_result = await _collect_host_table(ip_version)

    if not routes_result.success:
        return _unreadable_table(exercise, routes_result.error)

    interfaces = interfaces_result.data if interfaces_result.success else []

    entries, _skipped = _host_entries(routes_result.data, ip_version)

    if check_fn is _check_host_gateway:
        return check_fn(exercise, entries, interfaces, destination, answer)
    return check_fn(exercise, entries, interfaces, destination)
