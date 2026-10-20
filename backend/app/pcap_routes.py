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

    return response