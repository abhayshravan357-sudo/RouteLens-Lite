"""
RouteLens Lite - PCAP Analysis API Routes

FastAPI routes for PCAP file analysis.
"""

import base64
from fastapi import APIRouter, HTTPException, Body
from pydantic import BaseModel, Field, field_validator
from typing import Optional

from app.pcap import get_pcap_parser, PcapAnalysisResult, PcapHost, PcapConversation, PcapSummary


router = APIRouter(tags=["PCAP"])


MAX_FILE_SIZE = 32 * 1024 * 1024  # 32 MB


class PcapAnalyzeRequest(BaseModel):
    """Request model for PCAP analysis."""
    filename: str = Field(..., description="Original filename of the capture file")
    data_base64: str = Field(..., description="Base64-encoded raw PCAP file bytes")

    @field_validator("filename")
    @classmethod
    def validate_filename(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Filename is required")
        return v.strip()

    @field_validator("data_base64")
    @classmethod
    def validate_base64(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Base64 data is required")
        try:
            base64.b64decode(v.strip(), validate=True)
        except Exception as e:
            raise ValueError(f"Invalid base64 data: {e}")
        return v.strip()


class PcapHostResponse(BaseModel):
    ip: str
    packets: int
    bytes: int
    first_seen: str
    last_seen: str


class PcapConversationResponse(BaseModel):
    src: str
    dst: str
    protocol: str
    packets: int
    bytes: int


class PcapSummaryResponse(BaseModel):
    total_packets: int
    total_bytes: int
    duration_seconds: float
    start_time: str
    end_time: str
    protocols: dict[str, int]
    link_type: int


class PcapPacketDetailResponse(BaseModel):
    """Everything extracted from one frame, down to the transport layer."""

    index: int
    timestamp: str
    src_mac: Optional[str] = None
    dst_mac: Optional[str] = None
    ethertype: Optional[int] = None
    src_ip: Optional[str] = None
    dst_ip: Optional[str] = None
    protocol: Optional[str] = None
    src_port: Optional[int] = None
    dst_port: Optional[int] = None
    tcp_flags: list[str] = []
    tcp_flags_value: Optional[int] = None
    icmp_type: Optional[int] = None
    icmp_type_name: Optional[str] = None
    icmp_code: Optional[int] = None
    icmp_code_name: Optional[str] = None
    dns_query_name: Optional[str] = None
    dns_answers: list[str] = []
    dns_is_response: Optional[bool] = None
    dns_response_code: Optional[int] = None
    arp_operation: Optional[int] = None
    arp_operation_name: Optional[str] = None
    arp_sender_mac: Optional[str] = None
    arp_sender_ip: Optional[str] = None
    arp_target_mac: Optional[str] = None
    arp_target_ip: Optional[str] = None
    handshake_stage: Optional[str] = None
    provenance: dict[str, str] = {}
    notes: list[str] = []
    parsed: bool = True


class PcapHandshakeResponse(BaseModel):
    """A TCP three-way handshake seen in the capture."""

    client: str
    server: str
    stages: list[str] = []
    complete: bool = False
    provenance: str = "inferred"
    explanation: str = ""


class PcapAnalyzeResponse(BaseModel):
    filename: str
    size_bytes: int
    format: str
    parsed: bool
    error: Optional[str] = None
    collected_at: str
    summary: Optional[PcapSummaryResponse] = None
    hosts: list[PcapHostResponse] = []
    conversations: list[PcapConversationResponse] = []
    limitations: list[str] = []
    # Per-packet detail and the handshakes derived from it.
    packets: list[PcapPacketDetailResponse] = []
    handshakes: list[PcapHandshakeResponse] = []


@router.post(
    "/analyze",
    response_model=PcapAnalyzeResponse,
    summary="Analyze a PCAP capture file",
    responses={
        200: {"description": "Analysis complete (parsed or error)"},
        400: {"description": "Invalid request"},
        413: {"description": "File too large"},
    },
)
async def analyze_pcap(request: PcapAnalyzeRequest) -> PcapAnalyzeResponse:
    """
    Analyze a PCAP capture file.
    
    The file is provided as base64-encoded bytes in the request body.
    No file is written to disk - parsing happens entirely in memory.
    
    Args:
        request: PcapAnalyzeRequest with filename and base64 data
        
    Returns:
        PcapAnalyzeResponse with analysis results or error details
        
    Supported formats:
        - Classic PCAP (link type 1 - Ethernet)
        - PCAPNG (detected but not parsed)
        
    Errors:
        - 400: Invalid base64, missing filename, empty body
        - 413: File exceeds 32 MB limit
        - 200 with parsed=false: Unsupported format, truncated file, invalid magic
    """
    # Decode base64
    try:
        pcap_data = base64.b64decode(request.data_base64)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid base64 data: {e}")

    # Size check (redundant with validator but explicit)
    if len(pcap_data) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"File size {len(pcap_data)} bytes exceeds maximum {MAX_FILE_SIZE} bytes (32 MB)"
        )

    # Parse the PCAP
    parser = get_pcap_parser()
    result: PcapAnalysisResult = parser.parse(pcap_data, request.filename)

    # Build response
    response = PcapAnalyzeResponse(
        filename=result.filename,
        size_bytes=result.size_bytes,
        format=result.format,
        parsed=result.parsed,
        error=result.error,
        collected_at=result.collected_at,
        limitations=result.limitations,
    )

    if result.summary:
        response.summary = PcapSummaryResponse(
            total_packets=result.summary.total_packets,
            total_bytes=result.summary.total_bytes,
            duration_seconds=result.summary.duration_seconds,
            start_time=result.summary.start_time,
            end_time=result.summary.end_time,
            protocols=result.summary.protocols,
            link_type=result.summary.link_type,
        )

    if result.hosts:
        response.hosts = [
            PcapHostResponse(
                ip=h.ip,
                packets=h.packets,
                bytes=h.bytes,
                first_seen=h.first_seen,
                last_seen=h.last_seen,
            )
            for h in result.hosts
        ]

    if result.conversations:
        response.conversations = [
            PcapConversationResponse(
                src=c.src,
                dst=c.dst,
                protocol=c.protocol,
                packets=c.packets,
                bytes=c.bytes,
            )
            for c in result.conversations
        ]

    if result.packets:
        response.packets = [
            PcapPacketDetailResponse(
                index=p.index,
                timestamp=p.timestamp,
                src_mac=p.src_mac,
                dst_mac=p.dst_mac,
                ethertype=p.ethertype,
                src_ip=p.src_ip,
                dst_ip=p.dst_ip,
                protocol=p.protocol,
                src_port=p.src_port,
                dst_port=p.dst_port,
                tcp_flags=list(p.tcp_flags),
                tcp_flags_value=p.tcp_flags_value,
                icmp_type=p.icmp_type,
                icmp_type_name=p.icmp_type_name,
                icmp_code=p.icmp_code,
                icmp_code_name=p.icmp_code_name,
                dns_query_name=p.dns_query_name,
                dns_answers=list(p.dns_answers),
                dns_is_response=p.dns_is_response,
                dns_response_code=p.dns_response_code,
                arp_operation=p.arp_operation,
                arp_operation_name=p.arp_operation_name,
                arp_sender_mac=p.arp_sender_mac,
                arp_sender_ip=p.arp_sender_ip,
                arp_target_mac=p.arp_target_mac,
                arp_target_ip=p.arp_target_ip,
                handshake_stage=p.handshake_stage,
                provenance=dict(p.provenance),
                notes=list(p.notes),
                parsed=p.parsed,
            )
            for p in result.packets
        ]

    if result.handshakes:
        response.handshakes = [
            PcapHandshakeResponse(
                client=h.client,
                server=h.server,
                stages=list(h.stages),
                complete=h.complete,
                provenance=h.provenance,
                explanation=h.explanation,
            )
            for h in result.handshakes
        ]

    return response