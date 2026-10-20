"""
RouteLens Lite - Routing Logic

Implements the core IPv4 routing table lookup algorithm:
1. Longest-prefix match (most specific network wins)
2. Lowest metric as tiebreaker for same prefix length
3. Deterministic rule for complete ties (first by interface name, then by next_hop)
"""

from ipaddress import IPv4Address, IPv4Network
from typing import Optional

from app.routing import RouteLookupResult, RoutingEntry


def find_matching_routes(destination_ip: str, routes: list[RoutingEntry]) -> list[RoutingEntry]:
    """
    Find all routes that match the given destination IP address.

    A route matches if the destination IP falls within the route's network.

    Args:
        destination_ip: The destination IPv4 address as a string
        routes: List of routing entries to search

    Returns:
        List of matching routes (empty if none match)

    Raises:
        ValueError: If destination_ip is not a valid IPv4 address
    """
    try:
        ip = IPv4Address(destination_ip)
    except ValueError as e:
        raise ValueError(f"Invalid IPv4 address: {destination_ip}") from e

    matching = []
    for route in routes:
        network = route.get_network()
        if ip in network:
            matching.append(route)

    return matching


def select_best_route(matching_routes: list[RoutingEntry]) -> tuple[RoutingEntry, str]:
    """
    Select the best route from matching routes using:
    1. Longest prefix length (most specific)
    2. Lowest metric
    3. Deterministic tiebreaker: interface name, then next_hop IP

    Args:
        matching_routes: List of routes that match the destination

    Returns:
        Tuple of (selected_route, explanation_string)

    Raises:
        ValueError: If matching_routes is empty
    """
    if not matching_routes:
        raise ValueError("No matching routes to select from")

    # Step 1: Find the longest prefix length
    max_prefixlen = max(route.get_network().prefixlen for route in matching_routes)
    candidates = [r for r in matching_routes if r.get_network().prefixlen == max_prefixlen]

    explanation_parts = [
        f"Found {len(matching_routes)} matching route(s).",
        f"Longest prefix length: /{max_prefixlen}.",
        f"{len(candidates)} route(s) have this prefix length.",
    ]

    # Step 2: If multiple with same prefix, pick lowest metric
    if len(candidates) > 1:
        min_metric = min(route.metric for route in candidates)
        candidates = [r for r in candidates if r.metric == min_metric]
        explanation_parts.append(f"Lowest metric: {min_metric}.")
        explanation_parts.append(f"{len(candidates)} route(s) have this metric.")

    # Step 3: Deterministic tiebreaker for complete ties
    if len(candidates) > 1:
        # Sort by interface name, then by next_hop IP (None sorts first)
        candidates.sort(key=lambda r: (r.interface, str(r.next_hop) if r.next_hop else ""))
        explanation_parts.append("Multiple routes tied; selected by interface name then next hop (deterministic).")

    selected = candidates[0]
    explanation_parts.append(
        f"Selected: {selected.destination} via {selected.next_hop or 'direct'} on {selected.interface} (metric {selected.metric})"
    )

    return selected, " ".join(explanation_parts)


def lookup_route(destination_ip: str, routes: list[RoutingEntry]) -> RouteLookupResult:
    """
    Look up the best route for a destination IPv4 address.

    This is the main entry point for route lookup. It validates input,
    finds matching routes, selects the best one, and returns a structured result.

    Args:
        destination_ip: The destination IPv4 address to look up
        routes: List of routing table entries

    Returns:
        RouteLookupResult with the selected route and explanation
    """
    # Validate destination IP
    try:
        IPv4Address(destination_ip)
    except ValueError as e:
        return RouteLookupResult(
            matched=False,
            error=f"Invalid IPv4 address: {destination_ip}",
        )

    # Validate all routes have valid data
    for route in routes:
        try:
            route.get_network()
            if route.next_hop:
                route.get_next_hop()
        except ValueError as e:
            return RouteLookupResult(
                matched=False,
                error=f"Invalid route data: {e}",
            )

    # Find matching routes
    matching = find_matching_routes(destination_ip, routes)

    if not matching:
        return RouteLookupResult(
            matched=False,
            explanation=f"No route matches destination {destination_ip}",
        )

    # Select best route
    try:
        best_route, explanation = select_best_route(matching)
    except ValueError as e:
        return RouteLookupResult(
            matched=False,
            error=str(e),
        )

    return RouteLookupResult(
        matched=True,
        route=best_route,
        explanation=explanation,
    )