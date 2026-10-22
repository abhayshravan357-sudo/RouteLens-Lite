"""
RouteLens Lite - Routing Logic

Implements the core IPv4/IPv6 routing table lookup algorithm:
1. Longest-prefix match (most specific network wins)
2. Lowest metric as tiebreaker for same prefix length
3. Deterministic rule for complete ties (first by interface name, then by next_hop)
"""

from dataclasses import dataclass
from ipaddress import IPv4Address, IPv4Network, IPv6Address, IPv6Network
from typing import Optional, List, Union

from app.routing import IPVersion, RouteLookupResult, RoutingEntry


def find_matching_routes(destination_ip: str, routes: list[RoutingEntry]) -> list[RoutingEntry]:
    """
    Find all routes that match the given destination IP address.

    A route matches if the destination IP falls within the route's network.

    Args:
        destination_ip: The destination IP address as a string (IPv4 or IPv6)
        routes: List of routing entries to search

    Returns:
        List of matching routes (empty if none match)

    Raises:
        ValueError: If destination_ip is not a valid IP address
    """
    try:
        ip = IPv4Address(destination_ip)
        ip_version = IPVersion.IPV4
    except ValueError:
        try:
            ip = IPv6Address(destination_ip)
            ip_version = IPVersion.IPV6
        except ValueError as e:
            raise ValueError(f"Invalid IPv4 address: {destination_ip}") from e

    matching = []
    for route in routes:
        # Skip routes of different IP version
        if route.get_ip_version() != ip_version:
            continue

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
    Look up the best route for a destination IP address (IPv4 or IPv6).

    This is the main entry point for route lookup. It validates input,
    finds matching routes, selects the best one, and returns a structured result.

    Args:
        destination_ip: The destination IP address to look up (IPv4 or IPv6)
        routes: List of routing table entries

    Returns:
        RouteLookupResult with the selected route and explanation
    """
    # Validate destination IP
    try:
        IPv4Address(destination_ip)
        ip_version = IPVersion.IPV4
    except ValueError:
        try:
            IPv6Address(destination_ip)
            ip_version = IPVersion.IPV6
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

    # Filter routes by IP version
    version_routes = [r for r in routes if r.get_ip_version() == ip_version]

    # Find matching routes
    matching = find_matching_routes(destination_ip, version_routes)

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


@dataclass
class PacketHop:
    """Represents a single hop in the packet journey."""
    hop_number: int
    current_device: str
    destination_ip: str
    matched_route_destination: Optional[str] = None
    matched_route_next_hop: Optional[str] = None
    matched_route_interface: Optional[str] = None
    matched_route_metric: Optional[int] = None
    next_hop_ip: Optional[str] = None
    egress_interface: Optional[str] = None
    # forward, deliver, drop, loop, error, unresolved_next_hop
    action: str = "forward"
    explanation: str = ""


# The most hops a packet may take before the trace gives up.
MAX_HOPS = 30

# Names for the addresses that appear in the sample table, so a trace reads
# as a story about routers rather than a list of numbers.
DEFAULT_DEVICE_NAMES = {
    "10.0.0.1": "Router A",
    "10.0.0.2": "Router B",
    "10.0.0.3": "Router C",
    "10.0.0.254": "Gateway",
    # IPv6 defaults
    "2001:db8::1": "Router A (IPv6)",
    "2001:db8::2": "Router B (IPv6)",
    "2001:db8::ffff": "Gateway (IPv6)",
}


def trace_packet_path(
    source_ip: str,
    destination_ip: str,
    routes: list[RoutingEntry],
    device_names: dict[str, str] = None,
    router_tables: dict[str, list[RoutingEntry]] = None,
) -> list[PacketHop]:
    """
    Trace the path a packet would take from source to destination.

    Each hop is a forwarding decision made by the router that is holding
    the packet at that moment. Every router therefore uses its own table:
    the table passed in belongs to the router the source is attached to,
    and the tables of any other router are given in `router_tables`, keyed
    by that router's address. A router never forwards using another
    router's table, because that would be forwarding a packet with
    somebody else's idea of the network.

    When the packet reaches a router whose table is not available, the
    trace stops there. The packet was handed over successfully; we simply
    cannot work out what that router would do next, and saying so is
    better than inventing an answer.

    The action recorded on each hop is one of the values listed in
    app.routing.PACKET_JOURNEY_ACTIONS, which says what each one means.

    Args:
        source_ip: Source IP address (IPv4 or IPv6)
        destination_ip: Destination IP address (IPv4 or IPv6)
        routes: The routing table of the router the source is attached to
        device_names: Optional mapping of IP addresses to device names
        router_tables: Optional mapping of a router's address to that
            router's own routing table

    Returns:
        List of PacketHop objects representing each hop
    """
    # Validate the source address
    try:
        src_ip = IPv4Address(source_ip)
        src_version = IPVersion.IPV4
    except ValueError:
        try:
            src_ip = IPv6Address(source_ip)
            src_version = IPVersion.IPV6
        except ValueError as e:
            return [PacketHop(
                hop_number=0,
                current_device="error",
                destination_ip=destination_ip,
                action="error",
                explanation=f"Invalid source IP address: {e}"
            )]

    # Validate the destination address
    try:
        dst_ip = IPv4Address(destination_ip)
        dst_version = IPVersion.IPV4
    except ValueError:
        try:
            dst_ip = IPv6Address(destination_ip)
            dst_version = IPVersion.IPV6
        except ValueError as e:
            return [PacketHop(
                hop_number=0,
                current_device="error",
                destination_ip=destination_ip,
                action="error",
                explanation=f"Invalid destination IP address: {e}"
            )]

    # A packet does not change address family on its own. Without an
    # explicit translation mechanism, the two ends must be the same family.
    if src_version != dst_version:
        src_label = "IPv4" if src_version == IPVersion.IPV4 else "IPv6"
        dst_label = "IPv4" if dst_version == IPVersion.IPV4 else "IPv6"
        return [PacketHop(
            hop_number=0,
            current_device="error",
            destination_ip=destination_ip,
            action="error",
            explanation=(
                f"Cannot trace a packet from an {src_label} source "
                f"({source_ip}) to an {dst_label} destination "
                f"({destination_ip}): this model has no address translation, so "
                f"the two ends must be in the same address family."
            )
        )]

    device_map = {**DEFAULT_DEVICE_NAMES, **(device_names or {})}
    router_tables = router_tables or {}

    hops: list[PacketHop] = []
    visited: set[str] = set()
    current_ip = str(src_ip)
    # The table of the router currently holding the packet. The source's
    # table is the one passed in; every other router's table has to be
    # supplied in router_tables.
    current_table: Optional[list[RoutingEntry]] = routes
    hop_number = 0

    while True:
        hop_number += 1
        current_device_name = device_map.get(current_ip, f"Device({current_ip})")

        # Has the packet arrived?
        if current_ip == str(dst_ip):
            hops.append(PacketHop(
                hop_number=hop_number,
                current_device=current_device_name,
                destination_ip=str(dst_ip),
                action="deliver",
                explanation=f"Packet delivered to destination {current_device_name} ({dst_ip})"
            ))
            break

        # Is the packet going round in circles?
        if current_ip in visited:
            hops.append(PacketHop(
                hop_number=hop_number,
                current_device=current_device_name,
                destination_ip=str(dst_ip),
                action="loop",
                explanation=f"Loop detected: packet returned to {current_device_name} ({current_ip})"
            ))
            break
        visited.add(current_ip)

        # Do we know how this router would forward?
        if current_table is None:
            hops.append(PacketHop(
                hop_number=hop_number,
                current_device=current_device_name,
                destination_ip=str(dst_ip),
                action="unresolved_next_hop",
                explanation=(
                    f"The packet is at {current_device_name} ({current_ip}), but no routing "
                    f"table for that router was given, so its forwarding decision cannot be "
                    f"worked out. The packet was handed over; the journey stops here."
                )
            ))
            break

        # Route selection, using the table of the router that holds the packet.
        result = lookup_route(str(dst_ip), current_table)

        if result.error:
            # The table itself is broken, which is not the same as having
            # no route. Say which it is.
            hops.append(PacketHop(
                hop_number=hop_number,
                current_device=current_device_name,
                destination_ip=str(dst_ip),
                action="error",
                explanation=(
                    f"{current_device_name} ({current_ip}) could not make a routing "
                    f"decision: {result.error}"
                )
            ))
            break

        if not result.matched or result.route is None:
            hops.append(PacketHop(
                hop_number=hop_number,
                current_device=current_device_name,
                destination_ip=str(dst_ip),
                action="drop",
                explanation=(
                    f"No route to destination {dst_ip} from {current_device_name} "
                    f"({current_ip}), so the packet has nowhere to go and is dropped."
                )
            ))
            break

        route = result.route
        assert route is not None

        # Determine next hop
        next_hop_ip = route.get_next_hop()
        egress_interface = route.interface

        # Directly connected: the destination is on a network this router
        # is attached to, so the packet arrives without another hop.
        if route.next_hop_type.value == "direct" or next_hop_ip is None:
            hops.append(PacketHop(
                hop_number=hop_number,
                current_device=current_device_name,
                destination_ip=str(dst_ip),
                matched_route_destination=route.destination,
                matched_route_next_hop=route.next_hop,
                matched_route_interface=route.interface,
                matched_route_metric=route.metric,
                next_hop_ip=None,
                egress_interface=egress_interface,
                action="deliver",
                explanation=(
                    f"Direct connection to destination network {route.destination} "
                    f"on {route.interface}"
                )
            ))
            break

        # Record the forwarding decision made by this router.
        hops.append(PacketHop(
            hop_number=hop_number,
            current_device=current_device_name,
            destination_ip=str(dst_ip),
            matched_route_destination=route.destination,
            matched_route_next_hop=route.next_hop,
            matched_route_interface=route.interface,
            matched_route_metric=route.metric,
            next_hop_ip=str(next_hop_ip),
            egress_interface=egress_interface,
            action="forward",
            explanation=f"Matched {route.destination} via {route.next_hop} on {route.interface} (metric {route.metric})"
        ))

        # The next hop may be the destination itself.
        if str(next_hop_ip) == str(dst_ip):
            hops.append(PacketHop(
                hop_number=hop_number + 1,
                current_device=device_map.get(str(dst_ip), f"Destination({dst_ip})"),
                destination_ip=str(dst_ip),
                action="deliver",
                explanation=f"Next hop {next_hop_ip} is the destination"
            ))
            break

        # Move to the next router, and use that router's own table from
        # now on.
        current_ip = str(next_hop_ip)
        current_table = router_tables.get(current_ip)

        # Check for max hops (prevent infinite loops)
        if hop_number > MAX_HOPS:
            hops.append(PacketHop(
                hop_number=hop_number + 1,
                current_device="...",
                destination_ip=str(dst_ip),
                action="drop",
                explanation=f"Maximum hop count exceeded ({MAX_HOPS} hops)"
            ))
            break

    return hops
