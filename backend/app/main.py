"""
RouteLens Lite - FastAPI Backend Application

This module creates the FastAPI application instance and defines the API routes.
It's designed to be beginner-friendly with clear structure and comments.
"""

import re
import socket
from ipaddress import IPv4Address, IPv6Address
from typing import Optional
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.routing import RouteLookupResult, RoutingEntry, SAMPLE_ROUTES, PacketJourneyRequest, PacketJourneyResponse
from app.routing_logic import lookup_route, trace_packet_path
from app.routing_table import get_routing_table, InvalidRouteError, IndexOutOfRangeError
from app.packet_lab_routes import router as packet_lab_router
from app.scenario_routes import router as scenario_router, exercise_router
from app.discovery_routes import router as discovery_router
from app.report_routes import router as report_router
from app.pcap_routes import router as pcap_router
from app.network_collector import get_network_collector
from app.route_analysis import analyse_destination, analyse_table, RouteAnalysisReport
from app.security import (
    TargetValidationError,
    diagnostic_limiter,
    validate_target,
)
from app.network_collector import CollectionResult as NetworkCollectionResult
from app.network_collector import InterfaceInfo, RouteInfo, NeighborInfo
from app.network_collector import DnsResolutionResult, TracerouteResult, TracerouteHop

app = FastAPI(
    title="RouteLens Lite API",
    description="A simple IPv4 routing table analyzer for a college project",
    version="0.1.0",
)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """
    Turn a validation failure into a sentence a student can act on.

    Pydantic's own answer is machine-shaped: a list of objects with a
    "Value error, " prefix on every message, where the interesting part
    is the sentence the app actually wrote. The field name is kept,
    because "which field" is part of the answer.
    """
    messages = []
    for error in exc.errors():
        message = error.get("msg", "")
        # Pydantic wraps a custom validator's message in "Value error, ".
        message = re.sub(r"^Value error,\s*", "", message)

        location = error.get("loc") or ()
        # The last location element is the field name.
        field = str(location[-1]) if location else None

        if message == "Field required" and field:
            message = f"{field.capitalize()} is required."

        if field and message and not message.lower().startswith(field.lower()):
            message = f"{field}: {message}"

        messages.append(message)

    detail = " · ".join(messages) if messages else "The request could not be understood."
    return JSONResponse(status_code=422, content={"detail": detail})

# CORS middleware allows the frontend (running on a different port) to call this API.
#
# Only the local Vite dev servers are allowed. The diagnostic endpoints can run
# ping and traceroute, so an open CORS policy would let any page on the
# machine use this backend as a network proxy.
ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:5174",
    "http://127.0.0.1:5174",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT"],
    allow_headers=["Content-Type"],
)

app.include_router(packet_lab_router, prefix="/api/lab")
app.include_router(scenario_router)
app.include_router(exercise_router)
app.include_router(discovery_router)
app.include_router(report_router)
app.include_router(pcap_router, prefix="/api/pcap")


@app.get("/health", tags=["Health"])
async def health_check():
    """
    Health check endpoint.

    Returns a simple JSON response indicating the service is running.
    This is useful for:
    - Load balancers to check if the service is healthy
    - Monitoring systems
    - Quick verification during development

    Returns:
        dict: A JSON object with status and service name
    """
    return {"status": "ok", "service": "RouteLens Lite API"}


@app.get("/lookup", response_model=RouteLookupResult, tags=["Routing"])
async def route_lookup(
    destination: str = Query(..., description="Destination IPv4 address to look up (e.g., 192.168.1.50)")
):
    """
    Look up the best route for a destination IPv4 address.

    Uses the routing table to find the most specific matching route
    using longest-prefix match, with metric as tiebreaker.

    Args:
        destination: The destination IPv4 address (e.g., "192.168.1.50")

    Returns:
        RouteLookupResult with the matched route and explanation
    """
    routing_table = get_routing_table()
    result = lookup_route(destination, routing_table.get_routes())

    if result.error:
        # Return 400 for invalid input
        if "Invalid" in result.error:
            raise HTTPException(status_code=400, detail=result.error)
        else:
            raise HTTPException(status_code=404, detail=result.explanation)

    if not result.matched:
        # No matching route found
        raise HTTPException(status_code=404, detail=result.explanation)

    return result


@app.get("/routes", tags=["Routing"])
async def list_routes():
    """
    List all routing table entries (live table).

    Returns:
        List of routing entries
    """
    routing_table = get_routing_table()
    return routing_table.get_routes()


@app.post("/routes", response_model=RoutingEntry, status_code=201, tags=["Routing"])
async def add_route(route: RoutingEntry):
    """
    Add a new route to the routing table.

    Args:
        route: The routing entry to add

    Returns:
        The added routing entry

    Raises:
        HTTPException: 400 if the route is invalid
    """
    routing_table = get_routing_table()
    try:
        return routing_table.add_route(route)
    except InvalidRouteError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.put("/routes/{index}", response_model=RoutingEntry, tags=["Routing"])
async def update_route(index: int, route: RoutingEntry):
    """
    Update a route at the given index.

    Args:
        index: The index of the route to update
        route: The new routing entry data

    Returns:
        The updated routing entry

    Raises:
        HTTPException: 400 if the route is invalid, 404 if index out of range
    """
    routing_table = get_routing_table()
    try:
        return routing_table.update_route(index, route)
    except InvalidRouteError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except IndexOutOfRangeError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.delete("/routes/{index}", status_code=204, tags=["Routing"])
async def delete_route(index: int):
    """
    Delete a route at the given index.

    Args:
        index: The index of the route to delete

    Raises:
        HTTPException: 404 if index out of range
    """
    routing_table = get_routing_table()
    try:
        routing_table.delete_route(index)
    except IndexOutOfRangeError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/routes/reset", tags=["Routing"])
async def reset_routes():
    """
    Reset the routing table to the original sample routes.

    Returns:
        The restored routing table
    """
    routing_table = get_routing_table()
    return routing_table.reset_routes()


@app.get("/routes/summary", tags=["Routing"])
async def routes_summary():
    """
    Get a summary of the current routing table.

    Returns:
        Dictionary with counts and statistics
    """
    routing_table = get_routing_table()
    return routing_table.get_summary()


@app.get("/routes/analysis", tags=["Routing"])
async def analyse_main_table(destination: Optional[str] = None):
    """
    Explain what the editable routing table would do.

    This is the table the Route Lookup works against, not the host's
    kernel table. The same analysis machinery that explains the kernel's
    table is used here, so both are described in the same words.

    Two claims are kept apart:
    - The table is what the student built. It is MODELLED.
    - The explanation is INFERRED from it.

    Args:
        destination: Optional destination address to explain. When omitted,
            the table's own destinations are explained.

    Returns:
        A report with the analysis for each destination, the candidates
        each route beat, any shadowing found, and the limits of the answer.

    Errors:
        - 400: The destination is not a valid IP address
    """
    routing_table = get_routing_table()
    entries = routing_table.get_routes()

    if destination is not None:
        destination = destination.strip()
        if not destination:
            destination = None
        else:
            try:
                IPv4Address(destination)
            except ValueError:
                try:
                    IPv6Address(destination)
                except ValueError:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Invalid destination address: {destination}",
                    )

    if destination:
        targets = [destination]
    else:
        # Explain each distinct destination the table covers, so the
        # student can see what every row is for.
        targets = []
        for entry in entries:
            for candidate in (entry.destination,):
                if candidate not in targets:
                    targets.append(candidate)

    analyses = [analyse_destination(target, entries).model_dump() for target in targets]

    return {
        "table_provenance": "simulated",
        "analysis_provenance": "inferred",
        "table_size": len(entries),
        "analyses": analyses,
        "limitations": [
            "This is the table the Route Lookup works against, not the "
            "host's kernel routing table.",
            "The table is modelled and lives in the backend's memory only. "
            "Restarting the backend puts the original table back.",
            "No packet was transmitted. The explanation is what the table "
            "would do, not something that happened.",
        ],
    }


@app.post("/packet-journey", tags=["Packet Journey"])
async def trace_packet_journey(request: PacketJourneyRequest):
    """
    Trace the path a packet would take from source to destination through the routing table.

    This endpoint traces the packet's path hop by hop through the routing table,
    showing each routing decision made at each hop.

    Args:
        request: PacketJourneyRequest with source and destination IPs

    Returns:
        PacketJourneyResponse with hop-by-hop trace
    """
    # Validate IPs
    try:
        IPv4Address(request.source_ip)
        IPv4Address(request.destination_ip)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid IP address: {e}")

    # Trace the packet path through the routing table
    routing_table = get_routing_table()
    hops = trace_packet_path(
        source_ip=request.source_ip,
        destination_ip=request.destination_ip,
        routes=routing_table.get_routes(),
    )

    # Convert hops to response format
    hops_data = []
    for hop in hops:
        hop_data = {
            "hop_number": hop.hop_number,
            "current_device": hop.current_device,
            "destination_ip": hop.destination_ip,
            "action": hop.action,
            "explanation": hop.explanation,
        }
        if hop.matched_route_destination:
            hop_data["matched_route"] = {
                "destination": hop.matched_route_destination,
                "next_hop": hop.matched_route_next_hop,
                "interface": hop.matched_route_interface,
                "metric": hop.matched_route_metric,
            }
        if hop.next_hop_ip:
            hop_data["next_hop_ip"] = hop.next_hop_ip
        if hop.egress_interface:
            hop_data["egress_interface"] = hop.egress_interface
        hop_data["action"] = hop.action
        hop_data["explanation"] = hop.explanation
        hops_data.append(hop_data)

    # Determine overall success
    success = any(h.action == "deliver" for h in hops)
    error = None
    if not any(h.action == "deliver" for h in hops):
        # Find the failure reason
        for hop in hops:
            if hop.action in ("drop", "loop", "error"):
                error = hop.explanation
                break

    return PacketJourneyResponse(
        source_ip=hops[0].current_device if hops else "",
        destination_ip=hops[-1].destination_ip if hops else "",
        hops=hops_data,
        success=success,
        error=error,
    )


@app.get("/network/interfaces", tags=["Network"])
async def get_interfaces():
    """
    Get real network interfaces from the host system.

    Uses `ip -j addr show` to collect interface information including:
    - Interface name, index, state, MTU
    - MAC address
    - IPv4 and IPv6 addresses and networks
    - Interface flags

    Returns:
        CollectionResult with list of InterfaceInfo objects
    """
    collector = get_network_collector()
    result = await collector.collect_interfaces()

    if not result.success:
        raise HTTPException(status_code=500, detail=result.error or "Failed to collect interfaces")

    return result


@app.get("/network/routes", tags=["Network"])
async def get_routes():
    """
    Get real routing table from the host system.

    Uses `ip -j route show` to collect routing entries including:
    - Destination prefix
    - Gateway (next hop)
    - Interface
    - Metric
    - Protocol
    - Scope

    Returns:
        CollectionResult with list of RouteInfo objects
    """
    collector = get_network_collector()
    result = await collector.collect_routes()

    if not result.success:
        raise HTTPException(status_code=500, detail=result.error or "Failed to collect routes")

    return result


@app.get("/network/routes/analysis", response_model=RouteAnalysisReport, tags=["Network"])
async def get_routes_analysis(destination: Optional[str] = None, ip_version: str = "ipv4"):
    """
    Analyse the real routing table and explain what it would do.

    Reads the host's routing table with `ip -j route show` (or `ip -j -6
    route show` for IPv6), converts it into the same model the routing
    engine uses, and then explains, for a destination, which route would
    win and which candidates it beat.

    Two different claims are kept apart here:
    - The routing table is OBSERVED. It was read from the kernel.
    - The explanation is INFERRED. It is a reading of the table.

    No packet is transmitted and no route is changed.

    Args:
        destination: Optional destination address to explain. When omitted, a
            set of interesting destinations is chosen: this host's own
            addresses, the default route's gateway, and a public address.
        ip_version: Which routing table to read, "ipv4" or "ipv6". The kernel
            keeps the two separately. When a destination is given, its own
            family decides, because an IPv6 destination says nothing about
            the IPv4 table.

    Returns:
        RouteAnalysisReport with the analysis, the candidates each route beat,
        any shadowing found, and the limits of the analysis.

    Errors:
        - 400: The destination is not a valid IP address, or the family is
          neither ipv4 nor ipv6
        - 500: The routing table could not be read
    """
    collector = get_network_collector()

    if ip_version not in ("ipv4", "ipv6"):
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported address family: {ip_version}. Use 'ipv4' or 'ipv6'.",
        )

    destination_family = None
    if destination is not None:
        destination = destination.strip()
        if not destination:
            destination = None
        else:
            try:
                IPv4Address(destination)
                destination_family = "ipv4"
            except ValueError:
                try:
                    IPv6Address(destination)
                    destination_family = "ipv6"
                except ValueError:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Invalid destination address: {destination}",
                    )

    # An IPv6 destination is answered from the IPv6 table, and an IPv4 one
    # from the IPv4 table. Only when no destination is given does the
    # requested family stand on its own.
    family = destination_family or ip_version

    routes_result = await collector.collect_routes(family)
    if not routes_result.success:
        raise HTTPException(
            status_code=500,
            detail=routes_result.error or "Failed to collect routes",
        )

    interfaces_result = await collector.collect_interfaces()
    interfaces = interfaces_result.data if interfaces_result.success else []

    report = analyse_table(
        routes=list(routes_result.data or []),
        interfaces=list(interfaces or []),
        destinations=[destination] if destination else None,
        collected_at=routes_result.timestamp,
        command=routes_result.command,
        ip_version=family,
    )

    return report


@app.get("/network/neighbors", tags=["Network"])
async def get_neighbors(resolve_names: bool = True):
    """
    Get real ARP/IPv6 neighbor cache from the host system.

    Uses `ip -j neigh show` to collect neighbor entries including:
    - IP address
    - Interface
    - MAC address (if available)
    - Neighbor state (REACHABLE, STALE, etc.)
    - Router flag
    - A reverse DNS name, when one could be looked up

    The name is looked up with a reverse DNS query, which is INFERRED, while
    the address itself is OBSERVED. The two are reported separately. A
    neighbour with no PTR record is reported as having no name, not with
    its own address repeated back as if it were a hostname.

    The lookup is bounded: it has a short timeout, it runs concurrently, and
    only a limited number of neighbours are looked up at all. A neighbour
    list always comes back complete, with names absent if they could not be
    found.

    Args:
        resolve_names: Whether to look up reverse DNS names. Turning this off
            avoids the DNS traffic entirely.

    Returns:
        CollectionResult with list of NeighborInfo objects
    """
    collector = get_network_collector()
    result = await collector.collect_neighbors(resolve_names=resolve_names)

    if not result.success:
        raise HTTPException(status_code=500, detail=result.error or "Failed to collect neighbors")

    return result


@app.get("/network/all", tags=["Network"])
async def get_all_network_info():
    """
    Get all network information in a single request.

    Collects interfaces, routes, and neighbors in parallel.

    Returns:
        Object with interfaces, routes, and neighbors CollectionResults
    """
    collector = get_network_collector()
    results = await collector.collect_all()

    # Check if any collection failed
    for key, result in results.items():
        if not result.success:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to collect {key}: {result.error or 'Unknown error'}"
            )

    return results


class DnsResolveRequest(BaseModel):
    """Request model for DNS resolution."""
    hostname: str = Field(..., description="Hostname to resolve (e.g., google.com)")
    timeout: float = Field(5.0, ge=0.5, le=30.0, description="Timeout in seconds")
    ipv6: bool = Field(False, description="Also resolve IPv6 (AAAA) records")


class DnsResolveResponse(BaseModel):
    """Response model for DNS resolution."""
    hostname: str
    addresses: list[dict]
    latency_ms: float
    error: str | None = None


@app.post("/network/dns-resolve", response_model=DnsResolveResponse, tags=["Network"])
async def resolve_dns(request: DnsResolveRequest):
    """
    Resolve a hostname to IP addresses using the system's DNS resolver.

    Uses the system's DNS resolver via asyncio.getaddrinfo() with configurable timeout.
    Supports both IPv4 (A) and IPv6 (AAAA) records.

    Args:
        request: DnsResolveRequest with hostname, timeout, and ipv6 options

    Returns:
        DnsResolveResponse with resolved addresses, latency, and any error

    Raises:
        HTTPException: 400 for invalid hostname, 429 when rate limited, 500 for internal errors
    """
    if not request.hostname or not request.hostname.strip():
        raise HTTPException(status_code=400, detail="Hostname is required")

    diagnostic_limiter.check("dns")

    try:
        hostname = validate_target(request.hostname)
    except TargetValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    collector = get_network_collector()

    # Determine address family
    family = socket.AF_INET
    if request.ipv6:
        family = socket.AF_UNSPEC

    result = await collector.resolve_dns(
        hostname=hostname,
        timeout=request.timeout,
        family=family,
    )

    # Convert to response format
    addresses = [
        {
            "hostname": record.hostname,
            "address": record.address,
            "type": record.record_type,
            "ttl": record.ttl,
        }
        for record in result.addresses
    ]

    response = DnsResolveResponse(
        hostname=result.hostname,
        addresses=addresses,
        latency_ms=result.latency_ms,
        error=result.error,
    )

    # Return appropriate status code based on result. The detail is a
    # readable sentence, because the client shows it to the user; the
    # full result travels alongside it under "result" so nothing is lost.
    if result.error:
        if "timed out" in result.error.lower():
            raise HTTPException(
                status_code=408,
                detail=result.error,
                headers={"X-RouteLens-Result": response.model_dump_json()},
            )
        elif "not found" in result.error.lower() or "no dns records" in result.error.lower():
            raise HTTPException(
                status_code=404,
                detail=result.error,
                headers={"X-RouteLens-Result": response.model_dump_json()},
            )
        else:
            raise HTTPException(
                status_code=500,
                detail=result.error,
                headers={"X-RouteLens-Result": response.model_dump_json()},
            )

    return response


class ConnectivityRequest(BaseModel):
    """Request model for connectivity check."""
    target: str = Field(..., description="Target hostname or IP address")
    port: int | None = Field(None, description="Port number for TCP connect (required for TCP protocol)")
    protocol: str = Field("tcp", description="Protocol: 'icmp' for ping, 'tcp' for TCP connect")
    timeout: float = Field(5.0, ge=0.5, le=30.0, description="Per-attempt timeout in seconds")
    count: int = Field(3, ge=1, le=10, description="Number of attempts (for ICMP ping)")
    interval: float = Field(0.2, ge=0.1, le=5.0, description="Interval between attempts in seconds")


class ConnectivityResponse(BaseModel):
    """Response model for connectivity check."""
    target: str
    port: int | None
    protocol: str
    reachable: bool
    latency_ms: float
    packets_sent: int | None = None
    packets_received: int | None = None
    packet_loss_percent: float | None = None
    rtt_min_ms: float | None = None
    rtt_avg_ms: float | None = None
    rtt_max_ms: float | None = None
    rtt_mdev_ms: float | None = None
    error: str | None = None


@app.post("/network/connectivity", response_model=ConnectivityResponse, tags=["Network"])
async def check_connectivity(request: ConnectivityRequest):
    """
    Check connectivity to a target using ICMP ping or TCP connect.

    Supports both ICMP ping (host reachability) and TCP connect (port reachability).
    Uses system ping command for ICMP and asyncio.open_connection for TCP.

    Args:
        request: ConnectivityRequest with target, protocol, and options

    Returns:
        ConnectivityResponse with reachability, latency, and any error

    Raises:
        HTTPException: 400 for invalid input, 408 for timeout, 429 when rate limited, 500 for internal errors
    """
    if not request.target or not request.target.strip():
        raise HTTPException(status_code=400, detail="Target is required")

    if request.protocol.lower() not in ("icmp", "tcp"):
        raise HTTPException(status_code=400, detail="Protocol must be 'icmp' or 'tcp'")

    if request.protocol.lower() == "tcp" and request.port is None:
        raise HTTPException(status_code=400, detail="Port is required for TCP protocol")

    diagnostic_limiter.check("connectivity")

    try:
        target = validate_target(request.target)
    except TargetValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    collector = get_network_collector()

    result = await collector.check_connectivity(
        target=target,
        port=request.port,
        protocol=request.protocol,
        timeout=request.timeout,
        count=request.count,
        interval=request.interval,
    )

    response = ConnectivityResponse(
        target=result.target,
        port=result.port,
        protocol=result.protocol,
        reachable=result.reachable,
        latency_ms=result.latency_ms,
        packets_sent=result.packets_sent,
        packets_received=result.packets_received,
        packet_loss_percent=result.packet_loss_percent,
        rtt_min_ms=result.rtt_min_ms,
        rtt_avg_ms=result.rtt_avg_ms,
        rtt_max_ms=result.rtt_max_ms,
        rtt_mdev_ms=result.rtt_mdev_ms,
        error=result.error,
    )

    # Return appropriate status code based on result. The detail is a
    # readable sentence, because the client shows it to the user.
    if result.error:
        if "timed out" in result.error.lower():
            raise HTTPException(
                status_code=408,
                detail=result.error,
                headers={"X-RouteLens-Result": response.model_dump_json()},
            )
        else:
            raise HTTPException(
                status_code=500,
                detail=result.error,
                headers={"X-RouteLens-Result": response.model_dump_json()},
            )

    return response


class TracerouteRequest(BaseModel):
    """Request model for traceroute."""
    target: str = Field(..., description="Target hostname or IP address")
    max_hops: int = Field(30, ge=1, le=64, description="Maximum number of hops")
    timeout_per_hop: float = Field(2.0, ge=0.5, le=10.0, description="Timeout per hop in seconds")
    probes_per_hop: int = Field(1, ge=1, le=3, description="Number of probes per hop")
    overall_timeout: float = Field(60.0, ge=5.0, le=300.0, description="Overall timeout in seconds")


class TracerouteHopResponse(BaseModel):
    """Response model for a single traceroute hop."""
    ttl: int
    address: str | None = None
    hostname: str | None = None
    rtt_ms: float | None = None
    error: str | None = None


class TracerouteResponse(BaseModel):
    """Response model for traceroute."""
    target: str
    hops: list[TracerouteHopResponse]
    max_hops: int
    timeout_per_hop: float
    probes_per_hop: int
    completed: bool
    total_time_ms: float
    error: str | None = None


@app.post("/network/traceroute", response_model=TracerouteResponse, tags=["Network"])
async def trace_route(request: TracerouteRequest):
    """
    Perform traceroute to a target using the system traceroute command.

    Traces the path packets take to reach a destination by sending packets
    with incrementing TTL values and collecting ICMP time-exceeded responses.

    Args:
        request: TracerouteRequest with target and options

    Returns:
        TracerouteResponse with list of hops, each containing TTL, address, hostname, RTT

    Raises:
        HTTPException: 400 for invalid input, 408 for timeout, 429 when rate limited, 500 for internal errors
    """
    if not request.target or not request.target.strip():
        raise HTTPException(status_code=400, detail="Target is required")

    diagnostic_limiter.check("traceroute")

    try:
        target = validate_target(request.target)
    except TargetValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    collector = get_network_collector()

    result = await collector.trace_route(
        target=target,
        max_hops=request.max_hops,
        timeout_per_hop=request.timeout_per_hop,
        probes_per_hop=request.probes_per_hop,
        overall_timeout=request.overall_timeout,
    )

    response = TracerouteResponse(
        target=result.target,
        hops=[
            TracerouteHopResponse(
                ttl=hop.ttl,
                address=hop.address,
                hostname=hop.hostname,
                rtt_ms=hop.rtt_ms,
                error=hop.error,
            )
            for hop in result.hops
        ],
        max_hops=result.max_hops,
        timeout_per_hop=result.timeout_per_hop,
        probes_per_hop=result.probes_per_hop,
        completed=result.completed,
        total_time_ms=result.total_time_ms,
        error=result.error,
    )

    # Return appropriate status code based on result. The detail is a
    # readable sentence, because the client shows it to the user.
    if result.error:
        if "timed out" in result.error.lower() or "timeout" in result.error.lower():
            raise HTTPException(
                status_code=408,
                detail=result.error,
                headers={"X-RouteLens-Result": response.model_dump_json()},
            )
        elif "not found" in result.error.lower() or "not available" in result.error.lower():
            raise HTTPException(
                status_code=503,
                detail=result.error,
                headers={"X-RouteLens-Result": response.model_dump_json()},
            )
        else:
            raise HTTPException(
                status_code=500,
                detail=result.error,
                headers={"X-RouteLens-Result": response.model_dump_json()},
            )

    return response