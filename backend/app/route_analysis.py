"""
RouteLens Lite - Real Routing Table Analysis

Turns the routing table read out of the running kernel into the teaching
model, then explains what the kernel would do with a destination and why.

Two different things are happening here, and they are not the same claim:

- The routing table itself is OBSERVED. It was read from the kernel.
- The conclusion drawn from it is INFERRED. It is a reading of the table,
  not a packet that was sent.

Nothing in this module transmits anything, touches the network, or changes
a route. It only reads the table that was already collected and reasons
about it with the same longest-prefix-match engine the rest of the project
uses, so that the explanation and the lookup can never disagree.
"""

from ipaddress import (
    IPv4Address,
    IPv4Network,
    IPv6Address,
    IPv6Network,
    collapse_addresses,
)
from typing import Any, Optional, Union

from pydantic import BaseModel, Field

from app.routing import NextHopType, Provenance, RoutingEntry
from app.routing_logic import find_matching_routes, select_best_route
from app.network_collector import InterfaceInfo, RouteInfo


IPNetwork = Union[IPv4Network, IPv6Network]

# The public addresses used to show what the default route stands in for.
# These are only ever used as a lookup key in the local table. No request
# is made to them.
PUBLIC_IPV4 = "1.1.1.1"
PUBLIC_IPV6 = "2606:4700:4700::1111"


# --------------------------------------------------------------------------
# Response models
# --------------------------------------------------------------------------


class RouteCandidate(BaseModel):
    """A route in the table that matched a destination, and how it fared."""

    destination: str
    prefix_length: int
    next_hop: Optional[str] = None
    interface: str
    metric: int
    next_hop_type: str
    selected: bool = False
    outcome: str = "less specific"
    explanation: str = ""


class ShadowFinding(BaseModel):
    """A less specific route that a more specific route takes traffic from."""

    less_specific_destination: str
    more_specific_destinations: list[str] = Field(default_factory=list)
    captured_prefixes: list[str] = Field(default_factory=list)
    explanation: str = ""


class SkippedRoute(BaseModel):
    """A route from the table that the teaching model could not express."""

    destination: str
    reason: str


class DestinationAnalysis(BaseModel):
    """What the kernel's table says would happen to one destination."""

    destination: str
    matched: bool = False
    selected: Optional[RoutingEntry] = None
    candidates: list[RouteCandidate] = Field(default_factory=list)
    beaten: list[RouteCandidate] = Field(default_factory=list)
    explanation: str = ""
    is_default_route: bool = False
    shadowed_by: Optional[ShadowFinding] = None
    provenance: str = Provenance.INFERRED.value
    limitations: list[str] = Field(default_factory=list)


class RouteAnalysisReport(BaseModel):
    """Analysis of a whole routing table."""

    collected_at: str
    command: str
    ip_version: str = "ipv4"
    routes_in_table: int = 0
    routes_analysed: int = 0
    routes_skipped: list[SkippedRoute] = Field(default_factory=list)
    default_routes: list[str] = Field(default_factory=list)
    table_provenance: str = Provenance.OBSERVED.value
    analysis_provenance: str = Provenance.INFERRED.value
    analyses: list[DestinationAnalysis] = Field(default_factory=list)
    shadow_findings: list[ShadowFinding] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------
# Conversion: observed table -> teaching model
# --------------------------------------------------------------------------


def _default_destination(ip_version: str) -> str:
    """The default route in CIDR form for the given address family."""
    return "0.0.0.0/0" if ip_version == "ipv4" else "::/0"


def to_teaching_entry(
    route: RouteInfo, ip_version: str = "ipv4"
) -> tuple[Optional[RoutingEntry], Optional[str]]:
    """Convert one observed route into a teaching-model entry.

    Args:
        route: A route as read from the kernel.
        ip_version: "ipv4" or "ipv6". This matters because the kernel spells
            the default route as the word "default" in both families, so
            only the caller knows which family a route came from.

    Returns:
        (entry, reason). Exactly one of the two is None. When the entry is
        None, the reason says why the route could not be expressed.

    A route is skipped rather than guessed at. The one place a value is
    supplied rather than read is a missing metric: the kernel's metric
    defaults to zero, so zero is what that route actually has.
    """
    destination = (route.destination or "").strip()

    if not destination or destination == "default":
        destination = _default_destination(ip_version)

    # Work out the family of the destination itself.
    try:
        IPv4Network(destination, strict=False)
        family = "ipv4"
    except ValueError:
        try:
            IPv6Network(destination, strict=False)
            family = "ipv6"
        except ValueError:
            return None, f"'{route.destination}' is not a valid IPv4 or IPv6 network"

    # The caller says which family it asked for; the destination may disagree
    # with that if the table mixes families, which the kernel does not do but
    # a mixed hand-written table might.
    if family != ip_version and route.destination.strip() not in ("", "default"):
        return None, (
            f"destination '{route.destination}' is {family} but the table was "
            f"collected as {ip_version}"
        )

    interface = (route.interface or "").strip()
    if not interface:
        return None, "no egress interface recorded for this route"

    metric = route.metric if route.metric is not None else 0

    gateway = (route.gateway or "").strip()
    if gateway and gateway.lower() in ("none", "unreachable", "blackhole", "prohibit"):
        # The kernel marks special next hops by name. They are real routes
        # but they are not "go via this address", and the teaching model has
        # no way to say "drop this".
        return None, f"next hop '{gateway}' is a special next hop the teaching model cannot express"

    next_hop_type = NextHopType.GATEWAY
    if not gateway:
        next_hop_type = NextHopType.DIRECT
    else:
        try:
            if family == "ipv4":
                IPv4Address(gateway)
            else:
                IPv6Address(gateway)
        except ValueError:
            return None, f"next hop '{gateway}' is not a valid {family} address"

    try:
        entry = RoutingEntry(
            destination=destination,
            next_hop=gateway or None,
            interface=interface,
            metric=metric,
            next_hop_type=next_hop_type,
            provenance=Provenance.OBSERVED,
        )
    except Exception as exc:  # pragma: no cover - validation message passthrough
        return None, f"could not be expressed as a routing entry: {exc}"

    return entry, None


def to_teaching_entries(
    routes: list[RouteInfo], ip_version: str = "ipv4"
) -> tuple[list[RoutingEntry], list[SkippedRoute]]:
    """Convert a whole observed table into teaching-model entries.

    Returns:
        (entries, skipped). Routes that could not be expressed are reported
        rather than dropped silently.
    """
    entries: list[RoutingEntry] = []
    skipped: list[SkippedRoute] = []

    for route in routes:
        entry, reason = to_teaching_entry(route, ip_version)
        if entry is not None:
            entries.append(entry)
        else:
            skipped.append(
                SkippedRoute(
                    destination=route.destination or "(empty)",
                    reason=reason or "unknown reason",
                )
            )

    return entries, skipped


# --------------------------------------------------------------------------
# Analysis
# --------------------------------------------------------------------------


def _prefix_length(entry: RoutingEntry) -> int:
    return entry.get_network().prefixlen


def _is_default(entry: RoutingEntry) -> bool:
    return _prefix_length(entry) == 0


def _candidate_outcome(
    candidate: RoutingEntry, selected: RoutingEntry, tied: bool
) -> tuple[str, str]:
    """Why this candidate did or did not win."""
    if candidate is selected:
        return (
            "selected",
            f"Longest prefix match at /{_prefix_length(candidate)}.",
        )

    cand_len = _prefix_length(candidate)
    sel_len = _prefix_length(selected)

    if cand_len < sel_len:
        return (
            "less specific",
            f"Prefix /{cand_len} is shorter than the winning /{sel_len}, so it "
            f"loses longest-prefix match.",
        )

    if cand_len == sel_len:
        if candidate.metric > selected.metric:
            return (
                "higher metric",
                f"Same prefix length /{cand_len}, but metric {candidate.metric} is "
                f"worse than the winning metric {selected.metric}.",
            )
        if tied:
            return (
                "tied",
                f"Same prefix length /{cand_len} and same metric {candidate.metric}; "
                f"lost the deterministic tiebreak on interface then next hop.",
            )
        return (
            "higher metric",
            f"Same prefix length /{cand_len} but a worse metric than the winner.",
        )

    # Cannot happen: the winner always has the longest prefix.
    return "not selected", "Not selected by the routing algorithm."


def find_shadowing(
    entries: list[RoutingEntry], destination: str
) -> Optional[ShadowFinding]:
    """Find less specific routes that a more specific route takes traffic from.

    A route such as 0.0.0.0/0 sends every unmatched destination to the
    gateway. Where a more specific prefix also exists, that more specific
    route takes the traffic instead, and the default route is shadowed for
    that part of the address space.

    Args:
        entries: The whole table in teaching-model form.
        destination: A destination to examine.

    Returns:
        A ShadowFinding, or None when nothing shadows anything.
    """
    matching = find_matching_routes(destination, entries)
    if not matching:
        return None

    try:
        selected, _ = select_best_route(matching)
    except ValueError:
        return None

    selected_len = _prefix_length(selected)
    less_specific = [e for e in matching if _prefix_length(e) < selected_len]

    if not less_specific:
        return None

    # The routes that take the traffic. The selected route is the most
    # specific match, so this is the selected route plus any tie at the same
    # prefix length.
    more_specific = [e for e in matching if _prefix_length(e) >= selected_len]

    return ShadowFinding(
        less_specific_destination=less_specific[0].destination,
        more_specific_destinations=sorted({e.destination for e in more_specific}),
        captured_prefixes=[],
        explanation=(
            f"{selected.destination} (/{selected_len}) takes traffic that "
            f"{less_specific[0].destination} (/{_prefix_length(less_specific[0])}) "
            f"would otherwise have sent to "
            f"{less_specific[0].next_hop or 'the attached network'}."
        ),
    )


def summarise_default_coverage(
    entries: list[RoutingEntry], default_entry: RoutingEntry
) -> ShadowFinding:
    """Describe what a default route really stands in for.

    The default route matches every destination, so on its own it says
    nothing. The more specific routes in the table are the parts of the
    address space it actually covers. They are summarised with the standard
    library's CIDR aggregation, so a pair of adjacent halves is reported as
    the single block the two of them form.

    Args:
        entries: The whole table in teaching-model form.
        default_entry: The default route to describe.

    Returns:
        A ShadowFinding describing the covered space.
    """
    default_len = _prefix_length(default_entry)
    family = default_entry.get_ip_version().value

    more_specific = [
        e
        for e in entries
        if e.get_ip_version().value == family
        and _prefix_length(e) > default_len
    ]

    destinations = sorted({e.destination for e in more_specific})

    # collapse_addresses needs one address family at a time.
    covered: list[str] = []
    if more_specific:
        networks = [e.get_network() for e in more_specific]
        try:
            covered = [str(n) for n in collapse_addresses(networks)]
        except (TypeError, ValueError):
            covered = destinations

    if not more_specific:
        explanation = (
            f"{default_entry.destination} matches every destination and there are "
            f"no more specific routes in this table, so it handles all traffic."
        )
    else:
        explanation = (
            f"{default_entry.destination} matches every destination, but "
            f"{len(destinations)} more specific route(s) in this table capture part "
            f"of the address space. Those specific routes are what the default "
            f"route really stands in for; the default route is what is left over."
        )

    return ShadowFinding(
        less_specific_destination=default_entry.destination,
        more_specific_destinations=destinations,
        captured_prefixes=covered,
        explanation=explanation,
    )


def analyse_destination(
    destination: str,
    entries: list[RoutingEntry],
    limitations: Optional[list[str]] = None,
    local_addresses: Optional[set[str]] = None,
) -> DestinationAnalysis:
    """Explain what the table would do with one destination.

    Args:
        destination: The destination address to look up.
        entries: The table in teaching-model form.
        limitations: Extra limitations to carry into the result.
        local_addresses: Addresses this host owns. The kernel's main table alone would
            forward traffic to one of these to the default gateway, but the
            kernel delivers it locally using the separate local table. Saying
            so is more honest than implying the address leaves the machine.

    Returns:
        A DestinationAnalysis.
    """
    limits = list(limitations or [])
    owned = local_addresses or set()

    matching = find_matching_routes(destination, entries)
    if not matching:
        return DestinationAnalysis(
            destination=destination,
            matched=False,
            explanation=(
                f"No route in the kernel's main table matches {destination}. The kernel's main table "
                f"is the one the kernel uses to decide what to forward, so traffic "
                f"to this address would not be forwarded by this host. Addresses the "
                f"kernel delivers locally, such as loopback, live in the separate "
                f"local table and are not part of this one."
            ),
            provenance=Provenance.INFERRED.value,
            limitations=limits,
        )

    selected, engine_explanation = select_best_route(matching)

    # The engine picks among routes of equal prefix length. Everything with
    # a shorter prefix was already excluded by longest-prefix match, so the
    # "beaten" list is the full set of routes that matched but did not win.
    max_len = _prefix_length(selected)
    tied = [e for e in matching if _prefix_length(e) == max_len]

    candidates: list[RouteCandidate] = []
    beaten: list[RouteCandidate] = []

    for entry in sorted(matching, key=lambda e: (-_prefix_length(e), e.metric, e.interface)):
        outcome, explanation = _candidate_outcome(
            entry, selected, tied=len(tied) > 1
        )
        candidate = RouteCandidate(
            destination=entry.destination,
            prefix_length=_prefix_length(entry),
            next_hop=entry.next_hop,
            interface=entry.interface,
            metric=entry.metric,
            next_hop_type=entry.next_hop_type.value,
            selected=(entry is selected),
            outcome=outcome,
            explanation=explanation,
        )
        candidates.append(candidate)
        if not candidate.selected:
            beaten.append(candidate)

    is_default = _is_default(selected)

    shadow = find_shadowing(entries, destination)

    parts = [engine_explanation]
    if is_default:
        parts.append(
            "This is the default route, so it matches every destination that no "
            "other route covers."
        )
    if beaten:
        parts.append(
            f"{len(beaten)} other route(s) also matched but lost: "
            + "; ".join(
                f"{c.destination} (/{c.prefix_length}, metric {c.metric})"
                for c in beaten
            )
            + "."
        )
    parts.append(
        "This is the routing decision the kernel's table implies. No packet was "
        "sent, and no route was changed."
    )
    if destination in owned:
        if is_default:
            parts.append(
                f"Note: {destination} is an address of this host. The kernel's main table "
                f"alone would forward it to the default gateway, but the kernel "
                f"delivers it locally using the separate local table, which is not "
                f"part of this analysis."
            )
        else:
            parts.append(
                f"Note: {destination} is an address of this host. The kernel "
                f"delivers it locally; the route shown is the kernel's main table's entry "
                f"for the connected network, and the separate local table is not "
                f"part of this analysis."
            )

    return DestinationAnalysis(
        destination=destination,
        matched=True,
        selected=selected,
        candidates=candidates,
        beaten=beaten,
        explanation=" ".join(parts),
        is_default_route=is_default,
        shadowed_by=shadow,
        provenance=Provenance.INFERRED.value,
        limitations=limits,
    )


def choose_interesting_destinations(
    entries: list[RoutingEntry], interfaces: Optional[list[InterfaceInfo]] = None
) -> list[str]:
    """Pick destinations worth explaining.

    These are the addresses a person looking at this machine would ask about:
    the machine's own addresses, the gateway the default route points at, and
    a public address so the default route can be seen doing its job.

    Only addresses of the family in this table are chosen. Listing an IPv4
    address against an IPv6 table would report "no route" for every one of
    them, which is noise rather than information.

    Args:
        entries: The table in teaching-model form.
        interfaces: The host's interfaces, used for its own addresses.

    Returns:
        A list of destination strings, in a stable order.
    """
    destinations: list[str] = []
    seen: set[str] = set()

    families = {e.get_ip_version().value for e in entries}

    def add(value: Optional[str], family: str) -> None:
        if value and family in families and value not in seen:
            seen.add(value)
            destinations.append(value)

    for interface in interfaces or []:
        for address in interface.ipv4_addresses:
            add(address, "ipv4")
        for address in interface.ipv6_addresses:
            add(address, "ipv6")

    for entry in entries:
        if _is_default(entry) and entry.next_hop:
            add(entry.next_hop, entry.get_ip_version().value)

    # One public address per family present, so the default route is exercised.
    if "ipv4" in families:
        add(PUBLIC_IPV4, "ipv4")
    if "ipv6" in families:
        add(PUBLIC_IPV6, "ipv6")

    return destinations


def analyse_table(
    routes: list[RouteInfo],
    interfaces: Optional[list[InterfaceInfo]] = None,
    destinations: Optional[list[str]] = None,
    collected_at: str = "",
    command: str = "ip -j route show",
    ip_version: str = "ipv4",
) -> RouteAnalysisReport:
    """Analyse a whole observed routing table.

    Args:
        routes: The routes as read from the kernel.
        interfaces: The host's interfaces, used to pick destinations.
        destinations: Destinations to explain. If omitted, a set of
            interesting ones is chosen.
        collected_at: When the table was read.
        command: The command that read it.
        ip_version: "ipv4" or "ipv6".

    Returns:
        A RouteAnalysisReport.
    """
    entries, skipped = to_teaching_entries(routes, ip_version=ip_version)

    limitations = [
        "The routing table was observed on this machine; the explanation of what "
        "it would do is inferred from that table.",
        "No packet was transmitted. This is a routing decision, not an observation "
        "of traffic.",
        "Only the kernel's main routing table was read. The kernel keeps local and "
        "broadcast routes in separate tables, so an address this host owns may "
        "have no entry of its own here, even though the kernel delivers it "
        "locally.",
        "Only the routes present in the table at the moment it was read are shown. "
        "A route added or removed since then is not reflected.",
    ]
    if skipped:
        limitations.append(
            f"{len(skipped)} route(s) in the table could not be expressed in the "
            f"teaching model and are listed under routes_skipped. They were not "
            f"guessed at."
        )
    if ip_version == "ipv4" and not any(
        e.get_ip_version().value == "ipv6" for e in entries
    ):
        limitations.append(
            "This table was read with the IPv4 route command. IPv6 routes are a "
            "separate table and are not included."
        )

    default_entries = [e for e in entries if _is_default(e)]

    if destinations is None:
        destinations = choose_interesting_destinations(entries, interfaces)

    analyses: list[DestinationAnalysis] = []
    shadow_findings: list[ShadowFinding] = []

    local_addresses: set[str] = set()
    for interface in interfaces or []:
        local_addresses.update(interface.ipv4_addresses)
        local_addresses.update(interface.ipv6_addresses)

    for destination in destinations:
        analysis = analyse_destination(
            destination, entries, limitations, local_addresses=local_addresses
        )
        analyses.append(analysis)
        if analysis.shadowed_by is not None:
            shadow_findings.append(analysis.shadowed_by)

    for default_entry in default_entries:
        shadow_findings.append(summarise_default_coverage(entries, default_entry))

    return RouteAnalysisReport(
        collected_at=collected_at,
        command=command,
        ip_version=ip_version,
        routes_in_table=len(routes),
        routes_analysed=len(entries),
        routes_skipped=skipped,
        default_routes=[e.destination for e in default_entries],
        table_provenance=Provenance.OBSERVED.value,
        analysis_provenance=Provenance.INFERRED.value,
        analyses=analyses,
        shadow_findings=shadow_findings,
        limitations=limitations,
    )
