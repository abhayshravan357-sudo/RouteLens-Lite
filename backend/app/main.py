"""
RouteLens Lite - FastAPI Backend Application

This module creates the FastAPI application instance and defines the API routes.
It's designed to be beginner-friendly with clear structure and comments.
"""

import socket
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from app.routing import RouteLookupResult, RoutingEntry, SAMPLE_ROUTES, PacketJourneyRequest, PacketJourneyResponse
from app.routing_logic import lookup_route, trace_packet_path
from app.packet_lab_routes import router as packet_lab_router
from app.scenario_routes import router as scenario_router, exercise_router
from app.network_collector import get_network_collector
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
    result = lookup_route(destination, SAMPLE_ROUTES)

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
    List all sample routing table entries.

    Returns:
        List of routing entries
    """
    return SAMPLE_ROUTES


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
        from ipaddress import IPv4Address
        IPv4Address(request.source_ip)
        IPv4Address(request.destination_ip)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid IP address: {e}")

    # Trace the packet path through the routing table
    hops = trace_packet_path(
        source_ip=request.source_ip,
        destination_ip=request.destination_ip,
        routes=SAMPLE_ROUTES,
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


@app.get("/routes", tags=["Routing"])


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


@app.get("/network/neighbors", tags=["Network"])
async def get_neighbors():
    """
    Get real ARP/IPv6 neighbor cache from the host system.

    Uses `ip -j neigh show` to collect neighbor entries including:
    - IP address
    - Interface
    - MAC address (if available)
    - Neighbor state (REACHABLE, STALE, etc.)
    - Router flag

    Returns:
        CollectionResult with list of NeighborInfo objects
    """
    collector = get_network_collector()
    result = await collector.collect_neighbors()

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

    # Return appropriate status code based on result
    if result.error:
        if "timed out" in result.error.lower():
            raise HTTPException(status_code=408, detail=response.model_dump())
        elif "not found" in result.error.lower() or "no dns records" in result.error.lower():
            raise HTTPException(status_code=404, detail=response.model_dump())
        else:
            raise HTTPException(status_code=500, detail=response.model_dump())

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

    # Return appropriate status code based on result
    if result.error:
        if "timed out" in result.error.lower():
            raise HTTPException(status_code=408, detail=response.model_dump())
        else:
            raise HTTPException(status_code=500, detail=response.model_dump())

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

    # Return appropriate status code based on result
    if result.error:
        if "timed out" in result.error.lower() or "timeout" in result.error.lower():
            raise HTTPException(status_code=408, detail=response.model_dump())
        elif "not found" in result.error.lower() or "not available" in result.error.lower():
            raise HTTPException(status_code=503, detail=response.model_dump())
        else:
            raise HTTPException(status_code=500, detail=response.model_dump())

    return response