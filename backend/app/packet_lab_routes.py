"""
RouteLens Lite - PacketLab API Routes

FastAPI routes for the virtual router lab operations.
"""

from fastapi import APIRouter, HTTPException
from fastapi import status as http_status
from pydantic import BaseModel, Field, field_validator
from ipaddress import IPv4Address

from app.packet_lab import (
    PacketLab,
    get_packet_lab,
    LabStatus,
    SimulateRequest,
    SimulateResponse,
    LabState,
)

router = APIRouter(tags=["PacketLab"])


class SimulateRequestModel(BaseModel):
    source_ip: str = Field(..., description="Source IPv4 address (must be 192.168.10.2)")
    destination_ip: str = Field(..., description="Destination IPv4 address (must be 192.168.20.2)")
    protocol: str = Field("icmp", description="Protocol: only icmp is currently supported")
    ttl: int = Field(64, ge=1, le=255, description="Time to live (not currently used in packet generation)")
    length: int = Field(84, ge=28, le=65535, description="Packet length in bytes (not currently used in packet generation)")
    route_matched: str | None = Field(None, description="Route that was matched")
    egress_interface: str | None = Field(None, description="Expected egress interface")
    next_hop: str | None = Field(None, description="Expected next hop")

    @field_validator("source_ip", "destination_ip")
    @classmethod
    def validate_ip(cls, v: str) -> str:
        try:
            IPv4Address(v)
        except ValueError:
            raise ValueError(f"Invalid IPv4 address: {v}")
        return v

    @field_validator("protocol")
    @classmethod
    def validate_protocol(cls, v: str) -> str:
        if v.lower() != "icmp":
            raise ValueError(f"Unsupported protocol: {v}. Only 'icmp' is currently supported.")
        return v.lower()


class ForwardingInfoModel(BaseModel):
    ingress_interface: str
    egress_interface: str
    next_hop: str
    route_matched: str
    action: str = "forward"


class PacketResponseModel(BaseModel):
    source_ip: str
    destination_ip: str
    protocol: str
    ttl: int
    length: int
    forwarding_info: ForwardingInfoModel


class VerificationDetailsModel(BaseModel):
    ttl_decremented: bool
    checksum_valid: bool
    route_matched: bool


class LabStatusResponse(BaseModel):
    available: bool
    state: str
    message: str
    router_info: dict | None = None
    error: str | None = None


class SimulateResponseModel(BaseModel):
    state: str
    message: str
    packet: PacketResponseModel | None = None
    capture_verified: bool = False
    verification_details: VerificationDetailsModel | None = None
    error: str | None = None


@router.get(
    "/status",
    response_model=LabStatusResponse,
    summary="Check virtual router lab availability",
    responses={
        200: {"description": "Lab is available"},
        503: {"description": "Lab is unavailable"},
    },
)
async def get_lab_status() -> LabStatusResponse:
    """
    Check if the virtual router lab is available and ready.

    Returns lab status, router interfaces, and routing table when available.
    """
    lab = get_packet_lab()
    lab_status: LabStatus = await lab.get_status()

    # Return appropriate HTTP status code
    if not lab_status.available:
        raise HTTPException(
            status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=lab_status.error or "Virtual router not ready",
        )

    return LabStatusResponse(
        available=lab_status.available,
        state=lab_status.state.value,
        message=lab_status.message,
        router_info=lab_status.router_info,
        error=lab_status.error,
    )


@router.post(
    "/simulate",
    response_model=SimulateResponseModel,
    summary="Simulate packet transmission through virtual router",
    responses={
        200: {"description": "Packet transmitted and verified"},
        400: {"description": "Invalid request"},
        408: {"description": "Capture timeout"},
        503: {"description": "Lab unavailable"},
    },
)
async def simulate_packet(request: SimulateRequestModel) -> SimulateResponseModel:
    """
    Simulate a packet transmission through the virtual router.

    Transmits a real packet and captures it for verification.
    Returns verification details including TTL decrement, checksum, and route matching.
    """
    lab = get_packet_lab()

    sim_request = SimulateRequest(
        source_ip=request.source_ip,
        destination_ip=request.destination_ip,
        protocol=request.protocol,
        ttl=request.ttl,
        length=request.length,
        route_matched=request.route_matched,
        egress_interface=request.egress_interface,
        next_hop=request.next_hop,
    )

    response: SimulateResponse = await lab.simulate(sim_request)

    # Map state to HTTP status
    if response.state == LabState.UNAVAILABLE:
        raise HTTPException(
            status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=response.error or "Lab unavailable",
        )
    elif response.state == LabState.TIMEOUT:
        raise HTTPException(
            status_code=http_status.HTTP_408_REQUEST_TIMEOUT,
            detail=response.error or "Capture timeout",
        )
    elif response.state == LabState.ERROR:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail=response.error or "Simulation error",
        )

    # Build forwarding info model
    forwarding_info = None
    if response.packet:
        forwarding_info = ForwardingInfoModel(
            ingress_interface=response.packet.forwarding_info.ingress_interface,
            egress_interface=response.packet.forwarding_info.egress_interface,
            next_hop=response.packet.forwarding_info.next_hop,
            route_matched=response.packet.forwarding_info.route_matched,
            action=response.packet.forwarding_info.action,
        )

    return SimulateResponseModel(
        state=response.state.value,
        message=response.message,
        packet=PacketResponseModel(
            source_ip=response.packet.source_ip,
            destination_ip=response.packet.destination_ip,
            protocol=response.packet.protocol,
            ttl=response.packet.ttl,
            length=response.packet.length,
            forwarding_info=forwarding_info,
        ) if response.packet else None,
        capture_verified=response.capture_verified,
        verification_details=VerificationDetailsModel(
            ttl_decremented=response.verification_details.ttl_decremented,
            checksum_valid=response.verification_details.checksum_valid,
            route_matched=response.verification_details.route_matched,
        ) if response.verification_details else None,
        error=response.error,
    )