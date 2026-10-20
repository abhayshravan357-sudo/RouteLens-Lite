"""
RouteLens Lite - PCAP Parser

Safe, read-only PCAP parser using only the Python standard library.
No live capture, no privileges required.
"""

import base64
import struct
import socket
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from app.routing import Provenance


@dataclass
class PcapPacket:
    """A single parsed packet from a PCAP file."""
    ts_sec: int
    ts_usec: int
    incl_len: int
    orig_len: int
    data: bytes
    # Timestamp units per second. Classic PCAP is microseconds throughout,
    # but PCAPNG lets each interface choose its own resolution.
    ts_resolution: int = 1_000_000


@dataclass
class PcapPacketDetail:
    """
    Everything extracted from a single frame, down to the transport layer.

    Fields are populated only when the bytes actually carry them. A field
    that is None means "not present in this packet", not "unknown".

    The `provenance` map records, per field, whether the value was read
    directly out of the bytes ("observed") or derived by interpreting or
    correlating them ("inferred").
    """

    index: int
    timestamp: str

    # Link layer - observed
    src_mac: Optional[str] = None
    dst_mac: Optional[str] = None
    ethertype: Optional[int] = None

    # Network layer - observed
    src_ip: Optional[str] = None
    dst_ip: Optional[str] = None
    protocol: Optional[str] = None

    # Transport layer - observed
    src_port: Optional[int] = None
    dst_port: Optional[int] = None
    tcp_flags: list[str] = field(default_factory=list)
    tcp_flags_value: Optional[int] = None

    # ICMP - observed
    icmp_type: Optional[int] = None
    icmp_type_name: Optional[str] = None
    icmp_code: Optional[int] = None
    icmp_code_name: Optional[str] = None

    # DNS - inferred (labels are decoded, pointers are followed)
    dns_query_name: Optional[str] = None
    dns_answers: list[str] = field(default_factory=list)
    dns_is_response: Optional[bool] = None
    dns_response_code: Optional[int] = None

    # ARP - observed
    arp_operation: Optional[int] = None
    arp_operation_name: Optional[str] = None
    arp_sender_mac: Optional[str] = None
    arp_sender_ip: Optional[str] = None
    arp_target_mac: Optional[str] = None
    arp_target_ip: Optional[str] = None

    # Handshake stage - inferred by correlating packets in a flow
    handshake_stage: Optional[str] = None

    provenance: dict[str, str] = field(default_factory=dict)

    # Why this packet could not be taken further, if it could not
    notes: list[str] = field(default_factory=list)
    parsed: bool = True


@dataclass
class PcapHandshake:
    """
    A TCP three-way handshake observed in the capture.

    A handshake is a *pattern* across several packets, so it is inferred
    from observed bytes rather than observed directly.
    """

    client: str
    server: str
    stages: list[str] = field(default_factory=list)
    complete: bool = False
    provenance: str = Provenance.INFERRED.value
    explanation: str = ""


@dataclass
class PcapHost:
    """Host statistics from PCAP analysis."""
    ip: str
    packets: int
    bytes: int
    first_seen: str
    last_seen: str


@dataclass
class PcapConversation:
    """Conversation (flow) statistics from PCAP analysis."""
    src: str
    dst: str
    protocol: str
    packets: int
    bytes: int


@dataclass
class PcapSummary:
    """Summary statistics from PCAP analysis."""
    total_packets: int
    total_bytes: int
    duration_seconds: float
    start_time: str
    end_time: str
    protocols: dict[str, int]
    link_type: int
    # Added by the depth work. Defaults keep older call sites working.
    unparsed_packets: int = 0
    tcp_handshakes: int = 0
    complete_tcp_handshakes: int = 0
    dns_queries: int = 0
    dns_responses: int = 0
    arp_packets: int = 0


@dataclass
class PcapAnalysisResult:
    """Complete PCAP analysis result."""
    filename: str
    size_bytes: int
    format: str
    parsed: bool
    error: Optional[str] = None
    collected_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    summary: Optional[PcapSummary] = None
    hosts: list[PcapHost] = field(default_factory=list)
    conversations: list[PcapConversation] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    # Per-packet detail and derived findings.
    packets: list[PcapPacketDetail] = field(default_factory=list)
    handshakes: list[PcapHandshake] = field(default_factory=list)


# PCAP magic numbers, as the raw bytes they appear as in the file.
#
# The first four bytes of a capture file are a magic number whose bytes
# are written in the file's own byte order. A file written on a
# little-endian machine therefore starts with d4 c3 b2 a1, even though
# reading those four bytes as a big-endian number gives 0xa1b2c3d4. That
# is why these are compared as bytes and not as unpacked integers.
PCAP_MAGIC_BE_BYTES = b"\xa1\xb2\xc3\xd4"     # Big-endian, microseconds
PCAP_MAGIC_LE_BYTES = b"\xd4\xc3\xb2\xa1"     # Little-endian, microseconds
PCAP_MAGIC_BE_NS_BYTES = b"\xa1\xb2\x3c\x4d"  # Big-endian, nanoseconds
PCAP_MAGIC_LE_NS_BYTES = b"\x4d\x3c\xb2\xa1"  # Little-endian, nanoseconds
PCAPNG_MAGIC_BYTES = b"\x0a\x0d\x0d\x0a"      # PCAPNG format

PCAP_GLOBAL_HEADER_SIZE = 24
PCAP_PACKET_HEADER_SIZE = 16

# Link types
LINKTYPE_ETHERNET = 1

# EtherType values
ETHERTYPE_IPV4 = 0x0800
ETHERTYPE_IPV6 = 0x86DD
ETHERTYPE_ARP = 0x0806

# IP protocol numbers
IPPROTO_ICMP = 1
IPPROTO_TCP = 6
IPPROTO_UDP = 17
IPPROTO_ICMPV6 = 58

# TCP flag bits, in the byte that follows the 4-bit data offset.
TCP_FIN = 0x01
TCP_SYN = 0x02
TCP_RST = 0x04
TCP_PSH = 0x08
TCP_ACK = 0x10
TCP_URG = 0x20

# The flags we report, in a stable order.
TCP_FLAG_NAMES: list[tuple[int, str]] = [
    (TCP_SYN, "SYN"),
    (TCP_ACK, "ACK"),
    (TCP_FIN, "FIN"),
    (TCP_RST, "RST"),
    (TCP_PSH, "PSH"),
    (TCP_URG, "URG"),
]

# ICMP types we name.
ICMP_TYPES = {
    0: "echo-reply",
    3: "destination-unreachable",
    5: "redirect",
    8: "echo-request",
    11: "time-exceeded",
}

# ICMP destination-unreachable codes.
ICMP_UNREACHABLE_CODES = {
    0: "network-unreachable",
    1: "host-unreachable",
    2: "protocol-unreachable",
    3: "port-unreachable",
    4: "fragmentation-needed",
    5: "source-route-failed",
    9: "network-administratively-prohibited",
    10: "host-administratively-prohibited",
    11: "network-unreachable-for-tos",
    12: "host-unreachable-for-tos",
    13: "communication-administratively-prohibited",
}

# ARP operations.
ARP_OPERATIONS = {
    1: "request",
    2: "reply",
}

# DNS record types we can pull an address out of.
DNS_TYPE_A = 1
DNS_TYPE_AAAA = 28
DNS_TYPE_CNAME = 5

# The port a DNS message arrives on or leaves from.
DNS_PORT = 53

# PCAPNG block types.
PCAPNG_BLOCK_SECTION_HEADER = 0x0A0D0D0A
PCAPNG_BLOCK_INTERFACE_DESCRIPTION = 0x00000001
PCAPNG_BLOCK_SIMPLE_PACKET = 0x00000003
PCAPNG_BLOCK_ENHANCED_PACKET = 0x00000006

# PCAPNG byte-order magic, as the raw bytes it appears as on disk.
# 0x1a2b3c4d written little-endian is 4d 3c 2b 1a on the bytes.
PCAPNG_BYTE_ORDER_MAGIC_LE_BYTES = b"\x4d\x3c\x2b\x1a"
PCAPNG_BYTE_ORDER_MAGIC_BE_BYTES = b"\x1a\x2b\x3c\x4d"

# PCAPNG option code for interface timestamp resolution.
PCAPNG_OPTION_IF_TSRESOL = 9


class PcapParseError(Exception):
    """Raised when PCAP parsing fails."""
    pass


class PcapParser:
    """
    PCAP file parser using only Python standard library.
    
    Parses classic PCAP format (not PCAPNG).
    """

    def __init__(self, max_file_size: int = 32 * 1024 * 1024):
        self.max_file_size = max_file_size

    def parse(self, data: bytes, filename: str) -> PcapAnalysisResult:
        """
        Parse a PCAP file from bytes.
        
        Args:
            data: Raw PCAP file bytes
            filename: Original filename for reporting
            
        Returns:
            PcapAnalysisResult with parsed data or error information
        """
        collected_at = datetime.now(timezone.utc).isoformat()
        
        if len(data) > self.max_file_size:
            return PcapAnalysisResult(
                filename=filename,
                size_bytes=len(data),
                format="pcap",
                parsed=False,
                error=f"File size {len(data)} bytes exceeds maximum {self.max_file_size} bytes",
                collected_at=collected_at,
            )

        if len(data) < PCAP_GLOBAL_HEADER_SIZE:
            return PcapAnalysisResult(
                filename=filename,
                size_bytes=len(data),
                format="unknown",
                parsed=False,
                error="File too small to be a valid PCAP (less than 24 bytes)",
                collected_at=collected_at,
            )

        # Check for PCAPNG magic number first
        magic_bytes = data[:4]
        if magic_bytes == PCAPNG_MAGIC_BYTES:
            return self._parse_pcapng(data, filename, collected_at)

        # Determine endianness and timestamp resolution from the raw bytes.
        if magic_bytes == PCAP_MAGIC_BE_BYTES:
            endian = ">"
            ts_resolution = 1_000_000  # microseconds
        elif magic_bytes == PCAP_MAGIC_LE_BYTES:
            endian = "<"
            ts_resolution = 1_000_000  # microseconds
        elif magic_bytes == PCAP_MAGIC_BE_NS_BYTES:
            endian = ">"
            ts_resolution = 1_000_000_000  # nanoseconds
        elif magic_bytes == PCAP_MAGIC_LE_NS_BYTES:
            endian = "<"
            ts_resolution = 1_000_000_000  # nanoseconds
        else:
            return PcapAnalysisResult(
                filename=filename,
                size_bytes=len(data),
                format="unknown",
                parsed=False,
                error=f"Unknown PCAP magic number: {magic_bytes.hex()}",
                collected_at=collected_at,
            )

        # Parse the global header in the file's own byte order.
        try:
            magic, version_major, version_minor, thiszone, sigfigs, snaplen, network = \
                struct.unpack(f"{endian}IHHIIII", data[:PCAP_GLOBAL_HEADER_SIZE])
        except struct.error as e:
            return PcapAnalysisResult(
                filename=filename,
                size_bytes=len(data),
                format="unknown",
                parsed=False,
                error=f"Failed to parse global header: {e}",
                collected_at=collected_at,
            )

        if network != LINKTYPE_ETHERNET:
            # We only support Ethernet (link type 1) for full parsing
            return PcapAnalysisResult(
                filename=filename,
                size_bytes=len(data),
                format="pcap",
                parsed=False,
                error=f"Unsupported link type {network}. Only Ethernet (type 1) is supported for full parsing.",
                collected_at=collected_at,
            )

        # Parse packets
        offset = PCAP_GLOBAL_HEADER_SIZE
        packets: list[PcapPacket] = []
        
        while offset < len(data):
            # Check if we have enough bytes for packet header
            if offset + PCAP_PACKET_HEADER_SIZE > len(data):
                # Truncated file
                return PcapAnalysisResult(
                    filename=filename,
                    size_bytes=len(data),
                    format="pcap",
                    parsed=False,
                    error=f"Truncated file: packet header at offset {offset} extends past end of file",
                    collected_at=collected_at,
                )

            try:
                ts_sec, ts_usec, incl_len, orig_len = struct.unpack(
                    f"{endian}IIII", data[offset:offset + PCAP_PACKET_HEADER_SIZE]
                )
            except struct.error as e:
                return PcapAnalysisResult(
                    filename=filename,
                    size_bytes=len(data),
                    format="pcap",
                    parsed=False,
                    error=f"Failed to parse packet header at offset {offset}: {e}",
                    collected_at=collected_at,
                )

            offset += PCAP_PACKET_HEADER_SIZE

            # Check if we have enough bytes for packet data
            if offset + incl_len > len(data):
                return PcapAnalysisResult(
                    filename=filename,
                    size_bytes=len(data),
                    format="pcap",
                    parsed=False,
                    error=f"Truncated file: packet data at offset {offset} (length {incl_len}) extends past end of file",
                    collected_at=collected_at,
                )

            packet_data = data[offset:offset + incl_len]
            offset += incl_len

            packets.append(PcapPacket(
                ts_sec=ts_sec,
                ts_usec=ts_usec,
                incl_len=incl_len,
                orig_len=orig_len,
                data=packet_data,
            ))

        # Analyze packets
        if not packets:
            return PcapAnalysisResult(
                filename=filename,
                size_bytes=len(data),
                format="pcap",
                parsed=True,
                collected_at=collected_at,
                summary=PcapSummary(
                    total_packets=0,
                    total_bytes=0,
                    duration_seconds=0.0,
                    start_time="",
                    end_time="",
                    protocols={},
                    link_type=network,
                ),
                hosts=[],
                conversations=[],
                limitations=[
                    "Empty capture file - no packets to analyze",
                    "Only protocols present in the capture are counted",
                    "Timestamps come from the capture file, not the system clock",
                ],
            )

        return self._analyze_packets(packets, filename, len(data), network, collected_at, ts_resolution)

    def _pcapng_unsupported(self, filename: str, size: int, collected_at: str, reason: str) -> PcapAnalysisResult:
        """
        Build the "not yet supported" result for a PCAPNG file we cannot read.

        The wording is kept from the original implementation so that callers
        checking for it keep working, and the specific reason is appended so
        the user learns *why* this particular file could not be read.
        """
        return PcapAnalysisResult(
            filename=filename,
            size_bytes=size,
            format="pcapng",
            parsed=False,
            error=f"PCAPNG format detected but not yet supported for this file: {reason}",
            collected_at=collected_at,
        )

    def _parse_pcapng(self, data: bytes, filename: str, collected_at: str) -> PcapAnalysisResult:
        """
        Parse a PCAPNG file.

        PCAPNG is a series of blocks. Each block starts with its type and
        its total length, and ends with a copy of the total length. The
        first block of a section is the Section Header Block, which carries
        the byte-order magic that tells us how to read everything after it.

        A file we cannot make sense of is reported with the "not yet
        supported" wording rather than being guessed at.
        """
        offset = 0
        section_endian: Optional[str] = None
        # One entry per interface: (link_type, timestamp_resolution)
        interfaces: list[tuple[int, int]] = []
        packets: list[PcapPacket] = []
        link_type = LINKTYPE_ETHERNET
        saw_section = False

        while offset < len(data):
            if offset + 8 > len(data):
                return self._pcapng_unsupported(
                    filename, len(data), collected_at,
                    f"truncated block header at offset {offset}",
                )

            block_type_bytes = data[offset:offset + 4]

            if block_type_bytes == b"\x0a\x0d\x0d\x0a":
                # Section Header Block. Its byte-order magic is at a fixed
                # offset inside the block, and it is written in the section's
                # own order, so we compare the raw bytes rather than reading
                # them as a number first.
                if offset + 12 > len(data):
                    return self._pcapng_unsupported(
                        filename, len(data), collected_at,
                        f"truncated section header block at offset {offset}",
                    )
                bom = data[offset + 8:offset + 12]
                if bom == PCAPNG_BYTE_ORDER_MAGIC_LE_BYTES:
                    endian = "<"
                elif bom == PCAPNG_BYTE_ORDER_MAGIC_BE_BYTES:
                    endian = ">"
                else:
                    return self._pcapng_unsupported(
                        filename, len(data), collected_at,
                        f"unrecognised byte-order magic {bom.hex()} in section header block",
                    )
                block_type = PCAPNG_BLOCK_SECTION_HEADER
                section_endian = endian
                saw_section = True
                # A new section starts a new set of interfaces.
                interfaces = []
            else:
                if section_endian is None:
                    return self._pcapng_unsupported(
                        filename, len(data), collected_at,
                        "first block is not a section header block",
                    )
                endian = section_endian
                block_type = struct.unpack_from(f"{endian}I", data, offset)[0]

            total_len = struct.unpack_from(f"{endian}I", data, offset + 4)[0]
            if total_len < 12 or total_len % 4 != 0:
                return self._pcapng_unsupported(
                    filename, len(data), collected_at,
                    f"invalid block length {total_len} at offset {offset}",
                )
            if offset + total_len > len(data):
                return self._pcapng_unsupported(
                    filename, len(data), collected_at,
                    f"block at offset {offset} claims {total_len} bytes but the file ends first",
                )

            # Body sits between the 8-byte header and the 4-byte trailing
            # copy of the length.
            body = data[offset + 8:offset + total_len - 4]

            if block_type == PCAPNG_BLOCK_INTERFACE_DESCRIPTION:
                if len(body) < 8:
                    return self._pcapng_unsupported(
                        filename, len(data), collected_at,
                        f"truncated interface description block at offset {offset}",
                    )
                iface_link_type = struct.unpack_from(f"{endian}H", body, 0)[0]
                snaplen = struct.unpack_from(f"{endian}I", body, 4)[0]
                resolution = self._pcapng_ts_resolution(endian, body[8:])
                interfaces.append((iface_link_type, resolution))
                if not interfaces[:-1]:
                    link_type = iface_link_type
            elif block_type == PCAPNG_BLOCK_ENHANCED_PACKET:
                if len(body) < 20:
                    return self._pcapng_unsupported(
                        filename, len(data), collected_at,
                        f"truncated enhanced packet block at offset {offset}",
                    )
                iface_id, ts_high, ts_low, cap_len, orig_len = struct.unpack_from(
                    f"{endian}IIIII", body, 0
                )
                packet_bytes = body[20:20 + cap_len]
                if len(packet_bytes) < cap_len:
                    return self._pcapng_unsupported(
                        filename, len(data), collected_at,
                        f"enhanced packet block at offset {offset} claims {cap_len} bytes of packet data but has fewer",
                    )
                if iface_id >= len(interfaces):
                    return self._pcapng_unsupported(
                        filename, len(data), collected_at,
                        f"enhanced packet block references interface {iface_id} which was never described",
                    )
                resolution = interfaces[iface_id][1]
                total_ts = (ts_high << 32) | ts_low
                ts_sec = total_ts // resolution
                ts_frac = total_ts % resolution
                packets.append(PcapPacket(
                    ts_sec=ts_sec,
                    ts_usec=ts_frac,
                    incl_len=cap_len,
                    orig_len=orig_len,
                    data=packet_bytes,
                    ts_resolution=resolution,
                ))
            elif block_type == PCAPNG_BLOCK_SIMPLE_PACKET:
                if len(body) < 4:
                    return self._pcapng_unsupported(
                        filename, len(data), collected_at,
                        f"truncated simple packet block at offset {offset}",
                    )
                orig_len = struct.unpack_from(f"{endian}I", body, 0)[0]
                # A simple packet block has no captured-length field: the
                # packet data is the rest of the block, padded to 4 bytes.
                cap_len = min(orig_len, len(body) - 4)
                packet_bytes = body[4:4 + cap_len]
                resolution = interfaces[0][1] if interfaces else 1_000_000
                packets.append(PcapPacket(
                    ts_sec=0,
                    ts_usec=0,
                    incl_len=len(packet_bytes),
                    orig_len=orig_len,
                    data=packet_bytes,
                    ts_resolution=resolution,
                ))
            # Any other block type (name resolution, statistics, custom)
            # is simply skipped: it carries no packet data.

            offset += total_len

        if not saw_section:
            return self._pcapng_unsupported(
                filename, len(data), collected_at,
                "no section header block found",
            )

        if not packets:
            return PcapAnalysisResult(
                filename=filename,
                size_bytes=len(data),
                format="pcapng",
                parsed=True,
                collected_at=collected_at,
                summary=PcapSummary(
                    total_packets=0,
                    total_bytes=0,
                    duration_seconds=0.0,
                    start_time="",
                    end_time="",
                    protocols={},
                    link_type=link_type,
                ),
                hosts=[],
                conversations=[],
                limitations=[
                    "Empty capture file - no packets to analyze",
                    "Only protocols present in the capture are counted",
                    "Timestamps come from the capture file, not the system clock",
                ],
            )

        return self._analyze_packets(
            packets, filename, len(data), link_type, collected_at, 1_000_000,
            file_format="pcapng",
        )

    def _pcapng_ts_resolution(self, endian: str, options: bytes) -> int:
        """
        Read the if_tsresol option from an interface description block.

        Returns the number of timestamp units per second. The default is
        microseconds, as the specification requires.
        """
        offset = 0
        while offset + 4 <= len(options):
            code, length = struct.unpack_from(f"{endian}HH", options, offset)
            offset += 4
            if code == 0:  # end of options
                break
            value = options[offset:offset + length]
            offset += length + ((4 - length % 4) % 4)  # options are padded to 4 bytes
            if code == PCAPNG_OPTION_IF_TSRESOL and len(value) >= 1:
                raw = value[0]
                if raw & 0x80:
                    return 2 ** (raw & 0x7F)
                return 10 ** raw
        return 1_000_000

    def _analyze_packets(
        self,
        packets: list[PcapPacket],
        filename: str,
        file_size: int,
        link_type: int,
        collected_at: str,
        ts_resolution: int,
        file_format: str = "pcap",
    ) -> PcapAnalysisResult:
        """Analyze parsed packets and build statistics."""

        # Track hosts, conversations, protocols
        host_stats: dict[str, dict] = {}
        conversation_stats: dict[tuple[str, str, str], dict] = {}
        protocol_counts: dict[str, int] = {}
        details: list[PcapPacketDetail] = []

        start_ts = float('inf')
        end_ts = float('-inf')

        for index, pkt in enumerate(packets):
            # Convert timestamp. Each packet carries its own resolution,
            # because PCAPNG lets every interface choose one.
            resolution = pkt.ts_resolution or ts_resolution
            ts = pkt.ts_sec + (pkt.ts_usec / resolution)
            start_ts = min(start_ts, ts)
            end_ts = max(end_ts, ts)

            detail = PcapPacketDetail(
                index=index,
                timestamp=datetime.fromtimestamp(ts, timezone.utc).isoformat(),
            )

            # Parse Ethernet frame
            eth = self._parse_ethernet(pkt.data)
            if not eth:
                protocol_counts["unknown"] = protocol_counts.get("unknown", 0) + 1
                detail.parsed = False
                detail.notes.append(
                    f"Frame is shorter than an Ethernet header ({len(pkt.data)} bytes, need 14)"
                )
                details.append(detail)
                continue

            detail.dst_mac = self._format_mac(eth["dst_mac"])
            detail.src_mac = self._format_mac(eth["src_mac"])
            detail.ethertype = eth.get("ethertype")
            detail.provenance["src_mac"] = Provenance.OBSERVED.value
            detail.provenance["dst_mac"] = Provenance.OBSERVED.value
            detail.provenance["ethertype"] = Provenance.OBSERVED.value

            # Count protocol at Ethernet level
            ethertype = eth.get("ethertype")
            if ethertype == ETHERTYPE_IPV4:
                ipv4 = self._parse_ipv4(eth["payload"])
                if ipv4:
                    src_ip, dst_ip, proto = ipv4["src_ip"], ipv4["dst_ip"], ipv4["protocol"]
                    detail.src_ip = src_ip
                    detail.dst_ip = dst_ip
                    detail.protocol = self._protocol_name(proto)
                    detail.provenance["src_ip"] = Provenance.OBSERVED.value
                    detail.provenance["dst_ip"] = Provenance.OBSERVED.value
                    self._parse_transport(detail, proto, ipv4["payload"])
                    self._update_stats(
                        src_ip, dst_ip, proto, len(pkt.data), ts,
                        host_stats, conversation_stats, protocol_counts
                    )
                else:
                    protocol_counts["unknown"] = protocol_counts.get("unknown", 0) + 1
                    detail.parsed = False
                    detail.notes.append("IPv4 header could not be parsed")
            elif ethertype == ETHERTYPE_IPV6:
                ipv6 = self._parse_ipv6(eth["payload"])
                if ipv6:
                    src_ip, dst_ip, proto = ipv6["src_ip"], ipv6["dst_ip"], ipv6["protocol"]
                    detail.src_ip = src_ip
                    detail.dst_ip = dst_ip
                    detail.protocol = self._protocol_name(proto)
                    detail.provenance["src_ip"] = Provenance.OBSERVED.value
                    detail.provenance["dst_ip"] = Provenance.OBSERVED.value
                    self._parse_transport(detail, proto, ipv6["payload"])
                    self._update_stats(
                        src_ip, dst_ip, proto, len(pkt.data), ts,
                        host_stats, conversation_stats, protocol_counts
                    )
                else:
                    protocol_counts["unknown"] = protocol_counts.get("unknown", 0) + 1
                    detail.parsed = False
                    detail.notes.append("IPv6 header could not be parsed")
            elif ethertype == ETHERTYPE_ARP:
                protocol_counts["arp"] = protocol_counts.get("arp", 0) + 1
                detail.protocol = "arp"
                self._parse_arp(detail, eth["payload"])
            else:
                protocol_counts["other"] = protocol_counts.get("other", 0) + 1
                detail.protocol = "other"

            details.append(detail)

        # Build host list
        hosts = []
        for ip, stats in host_stats.items():
            hosts.append(PcapHost(
                ip=ip,
                packets=stats["packets"],
                bytes=stats["bytes"],
                first_seen=datetime.fromtimestamp(stats["first_seen"], timezone.utc).isoformat(),
                last_seen=datetime.fromtimestamp(stats["last_seen"], timezone.utc).isoformat(),
            ))

        # Build conversation list
        conversations = []
        for (src, dst, proto), stats in conversation_stats.items():
            conversations.append(PcapConversation(
                src=src,
                dst=dst,
                protocol=proto,
                packets=stats["packets"],
                bytes=stats["bytes"],
            ))

        # Sort by packet count descending
        hosts.sort(key=lambda h: h.packets, reverse=True)
        conversations.sort(key=lambda c: c.packets, reverse=True)

        # Correlate packets into TCP three-way handshakes.
        handshakes = self._detect_handshakes(details)

        # Build summary
        total_packets = len(packets)
        total_bytes = sum(p.incl_len for p in packets)
        duration = end_ts - start_ts if total_packets > 0 else 0.0

        summary = PcapSummary(
            total_packets=total_packets,
            total_bytes=total_bytes,
            duration_seconds=round(duration, 3),
            start_time=datetime.fromtimestamp(start_ts, timezone.utc).isoformat() if total_packets > 0 else "",
            end_time=datetime.fromtimestamp(end_ts, timezone.utc).isoformat() if total_packets > 0 else "",
            protocols=protocol_counts,
            link_type=link_type,
            unparsed_packets=sum(1 for d in details if not d.parsed),
            tcp_handshakes=len(handshakes),
            complete_tcp_handshakes=sum(1 for h in handshakes if h.complete),
            dns_queries=sum(1 for d in details if d.dns_query_name and d.dns_is_response is False),
            dns_responses=sum(1 for d in details if d.dns_is_response),
            arp_packets=sum(1 for d in details if d.protocol == "arp" and d.parsed),
        )

        return PcapAnalysisResult(
            filename=filename,
            size_bytes=file_size,
            format=file_format,
            parsed=True,
            collected_at=collected_at,
            summary=summary,
            hosts=hosts,
            conversations=conversations,
            packets=details,
            handshakes=handshakes,
            limitations=[
                "This analysis is based on a single captured file",
                "Only protocols present in the capture are counted",
                "Timestamps come from the capture file, not the system clock",
                "Only Ethernet (link type 1) packets are fully parsed",
                "Fragmented IP packets are not reassembled",
                "VLAN tags (802.1Q) are not parsed",
                "DNS is parsed for UDP only; DNS over TCP carries a two-byte length prefix and is reported, not decoded",
                "A TCP flow reports at most one handshake, so repeated connection attempts in one flow are not all listed",
                "DNS names and TCP handshakes are inferred from observed bytes, not observed directly",
            ],
        )

    def _protocol_name(self, proto_num: int) -> str:
        """Map an IP protocol number to its name."""
        proto_map = {
            IPPROTO_ICMP: "icmp",
            IPPROTO_TCP: "tcp",
            IPPROTO_UDP: "udp",
            IPPROTO_ICMPV6: "icmpv6",
        }
        return proto_map.get(proto_num, f"ip-{proto_num}")

    def _format_mac(self, raw: bytes) -> str:
        """Format a hardware address as colon-separated hex."""
        return ":".join(f"{b:02x}" for b in raw)

    def _parse_transport(self, detail: PcapPacketDetail, proto_num: int, payload: bytes) -> None:
        """
        Parse the transport layer of an IP packet into the detail record.

        Everything here reads bytes that are in network byte order, whatever
        the byte order of the capture file itself.
        """
        if proto_num == IPPROTO_TCP:
            self._parse_tcp(detail, payload)
        elif proto_num == IPPROTO_UDP:
            self._parse_udp(detail, payload)
        elif proto_num == IPPROTO_ICMP or proto_num == IPPROTO_ICMPV6:
            self._parse_icmp(detail, payload, proto_num == IPPROTO_ICMPV6)

    def _parse_tcp(self, detail: PcapPacketDetail, payload: bytes) -> None:
        """Parse a TCP header: ports, flags and data offset."""
        if len(payload) < 20:
            detail.parsed = False
            detail.notes.append(
                f"TCP header is truncated ({len(payload)} bytes, need 20)"
            )
            return

        src_port, dst_port = struct.unpack_from(">HH", payload, 0)
        detail.src_port = src_port
        detail.dst_port = dst_port
        detail.provenance["src_port"] = Provenance.OBSERVED.value
        detail.provenance["dst_port"] = Provenance.OBSERVED.value

        # Byte 12 holds the data offset in its high nibble; byte 13 holds
        # the flags.
        data_offset = (payload[12] >> 4) * 4
        flags_value = payload[13]
        detail.tcp_flags_value = flags_value
        detail.tcp_flags = [
            name for bit, name in TCP_FLAG_NAMES if flags_value & bit
        ]
        detail.provenance["tcp_flags"] = Provenance.OBSERVED.value

        if data_offset < 20:
            detail.parsed = False
            detail.notes.append(
                f"TCP data offset {data_offset} is smaller than the 20-byte minimum header"
            )
            return
        if len(payload) < data_offset:
            detail.parsed = False
            detail.notes.append(
                f"TCP header claims {data_offset} bytes but only {len(payload)} are present"
            )
            return

        # DNS over TCP carries a two-byte length prefix in front of the
        # message. We say so rather than decoding it as if it were UDP.
        if DNS_PORT in (src_port, dst_port):
            detail.notes.append(
                "DNS over TCP detected; it carries a two-byte length prefix and is reported, not decoded"
            )

    def _parse_udp(self, detail: PcapPacketDetail, payload: bytes) -> None:
        """Parse a UDP header and, for port 53, the DNS message."""
        if len(payload) < 8:
            detail.parsed = False
            detail.notes.append(
                f"UDP header is truncated ({len(payload)} bytes, need 8)"
            )
            return

        src_port, dst_port = struct.unpack_from(">HH", payload, 0)
        detail.src_port = src_port
        detail.dst_port = dst_port
        detail.provenance["src_port"] = Provenance.OBSERVED.value
        detail.provenance["dst_port"] = Provenance.OBSERVED.value

        if DNS_PORT in (src_port, dst_port):
            dns = self._parse_dns(payload[8:])
            detail.dns_query_name = dns["query_name"]
            detail.dns_answers = dns["answers"]
            detail.dns_is_response = dns["is_response"]
            detail.dns_response_code = dns["response_code"]
            if dns["query_name"] is not None or dns["answers"]:
                detail.provenance["dns_query_name"] = Provenance.INFERRED.value
                detail.provenance["dns_answers"] = Provenance.INFERRED.value
            for note in dns["notes"]:
                detail.notes.append(note)
                detail.parsed = False

    def _parse_icmp(self, detail: PcapPacketDetail, payload: bytes, is_v6: bool) -> None:
        """Parse an ICMP or ICMPv6 header: type and code."""
        if len(payload) < 4:
            detail.parsed = False
            detail.notes.append(
                f"ICMP header is truncated ({len(payload)} bytes, need 4)"
            )
            return

        icmp_type, icmp_code = payload[0], payload[1]
        detail.icmp_type = icmp_type
        detail.icmp_code = icmp_code
        detail.provenance["icmp_type"] = Provenance.OBSERVED.value
        detail.provenance["icmp_code"] = Provenance.OBSERVED.value

        if is_v6:
            # ICMPv6 uses its own type numbers: 128 echo request,
            # 129 echo reply, 1 destination unreachable.
            detail.icmp_type_name = {
                1: "destination-unreachable",
                128: "echo-request",
                129: "echo-reply",
                135: "neighbor-solicitation",
                136: "neighbor-advertisement",
            }.get(icmp_type, f"icmpv6-type-{icmp_type}")
        else:
            detail.icmp_type_name = ICMP_TYPES.get(icmp_type, f"icmp-type-{icmp_type}")

        if icmp_type == 3:
            detail.icmp_code_name = ICMP_UNREACHABLE_CODES.get(
                icmp_code, f"unreachable-code-{icmp_code}"
            )

    def _parse_arp(self, detail: PcapPacketDetail, payload: bytes) -> None:
        """Parse an ARP packet: the sender and target hardware addresses."""
        if len(payload) < 28:
            detail.parsed = False
            detail.notes.append(
                f"ARP packet is truncated ({len(payload)} bytes, need 28)"
            )
            return

        htype, ptype, hlen, plen, oper = struct.unpack_from(">HHBBH", payload, 0)
        if htype != 1 or hlen != 6 or plen != 4:
            detail.notes.append(
                f"ARP for hardware type {htype} and address sizes {hlen}/{plen} is not Ethernet/IPv4; fields left blank"
            )
            return

        detail.arp_operation = oper
        detail.arp_operation_name = ARP_OPERATIONS.get(oper, f"arp-operation-{oper}")
        detail.arp_sender_mac = self._format_mac(payload[8:14])
        detail.arp_sender_ip = socket.inet_ntoa(payload[14:18])
        detail.arp_target_mac = self._format_mac(payload[18:24])
        detail.arp_target_ip = socket.inet_ntoa(payload[24:28])
        for name in ("arp_operation", "arp_sender_mac", "arp_sender_ip",
                     "arp_target_mac", "arp_target_ip"):
            detail.provenance[name] = Provenance.OBSERVED.value

    def _parse_dns(self, payload: bytes) -> dict:
        """
        Parse a DNS message carried over UDP.

        Returns a dict with the query name, any answer addresses, whether
        this is a response, the response code, and any notes explaining
        why something could not be read. A message that cannot be read
        produces a note, never a guess.
        """
        result: dict[str, Any] = {
            "query_name": None,
            "answers": [],
            "is_response": None,
            "response_code": None,
            "notes": [],
        }

        if len(payload) < 12:
            result["notes"].append(
                f"DNS message is too short to hold a header ({len(payload)} bytes, need 12)"
            )
            return result

        _msg_id, flags, qdcount, ancount, _nscount, _arcount = struct.unpack_from(
            ">HHHHHH", payload, 0
        )
        result["is_response"] = bool(flags >> 15)
        result["response_code"] = flags & 0x0F

        offset = 12

        # Questions
        for index in range(qdcount):
            name, offset, ok = self._read_dns_name(payload, offset)
            if not ok:
                result["notes"].append(
                    "DNS question name could not be parsed; the message may be truncated or use an unsupported encoding"
                )
                return result
            if offset + 4 > len(payload):
                result["notes"].append(
                    "DNS question is truncated before its type and class"
                )
                return result
            offset += 4  # QTYPE and QCLASS
            if index == 0:
                result["query_name"] = name

        # Answers
        for _ in range(ancount):
            name, offset, ok = self._read_dns_name(payload, offset)
            if not ok:
                result["notes"].append(
                    "DNS answer name could not be parsed; remaining answers were not read"
                )
                return result
            if offset + 10 > len(payload):
                result["notes"].append(
                    "DNS answer is truncated before its type, class, TTL and length"
                )
                return result
            rtype, _rclass, _ttl, rdlength = struct.unpack_from(">HHIH", payload, offset)
            offset += 10
            if offset + rdlength > len(payload):
                result["notes"].append(
                    f"DNS answer claims {rdlength} bytes of data but the message ends first"
                )
                return result
            rdata = payload[offset:offset + rdlength]
            offset += rdlength

            if rtype == DNS_TYPE_A and rdlength == 4:
                result["answers"].append(socket.inet_ntoa(rdata))
            elif rtype == DNS_TYPE_AAAA and rdlength == 16:
                result["answers"].append(socket.inet_ntop(socket.AF_INET6, rdata))
            elif rtype == DNS_TYPE_CNAME:
                cname, _cname_end, cname_ok = self._read_dns_name(payload, offset - rdlength)
                if cname_ok:
                    result["answers"].append(cname)

        return result

    def _read_dns_name(self, data: bytes, offset: int) -> tuple[Optional[str], int, bool]:
        """
        Read a DNS name starting at offset.

        Handles the label sequence and the 0xC0 compression pointer form.
        Returns (name, offset_after_the_name, ok). When the name cannot be
        read, ok is False and the name is None.
        """
        labels: list[str] = []
        cursor = offset
        next_offset: Optional[int] = None
        hops = 0

        while True:
            if cursor >= len(data):
                return None, offset, False
            length = data[cursor]

            if length == 0:
                cursor += 1
                if next_offset is None:
                    next_offset = cursor
                break

            if (length & 0xC0) == 0xC0:
                # Compression pointer: two bytes, the low 14 bits are an
                # offset back into the message.
                if cursor + 1 >= len(data):
                    return None, offset, False
                pointer = ((length & 0x3F) << 8) | data[cursor + 1]
                cursor += 2
                if next_offset is None:
                    next_offset = cursor
                hops += 1
                if hops > 16:
                    # A pointer chain this long is a loop, not a name.
                    return None, offset, False
                cursor = pointer
                continue

            if length > 63:
                return None, offset, False

            if cursor + 1 + length > len(data):
                return None, offset, False

            labels.append(data[cursor + 1:cursor + 1 + length].decode("ascii", errors="replace"))
            cursor += 1 + length

        if next_offset is None:
            next_offset = cursor
        return (".".join(labels) if labels else "."), next_offset, True

    def _detect_handshakes(self, details: list[PcapPacketDetail]) -> list[PcapHandshake]:
        """
        Find TCP three-way handshakes among the parsed packets.

        A handshake is a pattern across three packets, so it is inferred
        from observed bytes rather than observed directly.
        """
        flows: dict[tuple, list[PcapPacketDetail]] = {}

        for detail in details:
            if detail.protocol != "tcp":
                continue
            if detail.src_port is None or detail.dst_port is None:
                continue
            if detail.src_ip is None or detail.dst_ip is None:
                continue
            forward = (detail.src_ip, detail.src_port, detail.dst_ip, detail.dst_port)
            reverse = (detail.dst_ip, detail.dst_port, detail.src_ip, detail.src_port)
            key = min(forward, reverse)
            flows.setdefault(key, []).append(detail)

        handshakes: list[PcapHandshake] = []

        for key, flow_packets in flows.items():
            flow_packets.sort(key=lambda d: d.index)
            stages: list[str] = []
            stage_packets: list[PcapPacketDetail] = []
            client: Optional[tuple[str, int]] = None
            server: Optional[tuple[str, int]] = None

            # Stage 1: a SYN on its own starts the handshake.
            for detail in flow_packets:
                if "SYN" in detail.tcp_flags and "ACK" not in detail.tcp_flags:
                    client = (detail.src_ip, detail.src_port)
                    server = (detail.dst_ip, detail.dst_port)
                    stages.append("SYN")
                    stage_packets.append(detail)
                    break

            if client is None:
                # No plain SYN. A lone SYN+ACK still tells us the roles.
                for detail in flow_packets:
                    if "SYN" in detail.tcp_flags and "ACK" in detail.tcp_flags:
                        server = (detail.src_ip, detail.src_port)
                        client = (detail.dst_ip, detail.dst_port)
                        stages.append("SYN-ACK")
                        stage_packets.append(detail)
                        break
                if not stages:
                    continue
            else:
                # Stage 2: the server answers with SYN+ACK.
                for detail in flow_packets:
                    if detail.index <= stage_packets[-1].index:
                        continue
                    if "SYN" in detail.tcp_flags and "ACK" in detail.tcp_flags:
                        if (detail.src_ip, detail.src_port) == server:
                            stages.append("SYN-ACK")
                            stage_packets.append(detail)
                            break

                # Stage 3: the client acknowledges with a bare ACK.
                if len(stages) >= 2:
                    for detail in flow_packets:
                        if detail.index <= stage_packets[-1].index:
                            continue
                        if set(detail.tcp_flags) == {"ACK"}:
                            if (detail.src_ip, detail.src_port) == client:
                                stages.append("ACK")
                                stage_packets.append(detail)
                                break

            if client is None or server is None:
                continue

            for detail, stage in zip(stage_packets, stages):
                detail.handshake_stage = stage
                detail.provenance["handshake_stage"] = Provenance.INFERRED.value

            complete = len(stages) == 3
            if complete:
                explanation = (
                    f"Three-way handshake observed: {client[0]}:{client[1]} opened the "
                    f"connection to {server[0]}:{server[1]}"
                )
            else:
                explanation = (
                    f"Partial TCP handshake: saw {' then '.join(stages)} between "
                    f"{client[0]}:{client[1]} and {server[0]}:{server[1]}"
                )

            handshakes.append(PcapHandshake(
                client=f"{client[0]}:{client[1]}",
                server=f"{server[0]}:{server[1]}",
                stages=stages,
                complete=complete,
                provenance=Provenance.INFERRED.value,
                explanation=explanation,
            ))

        handshakes.sort(key=lambda h: (h.client, h.server))
        return handshakes

    def _update_stats(
        self,
        src_ip: str,
        dst_ip: str,
        proto_num: int,
        packet_len: int,
        ts: float,
        host_stats: dict,
        conversation_stats: dict,
        protocol_counts: dict,
    ):
        """Update statistics dictionaries with a packet."""
        
        # Protocol name
        proto_map = {
            IPPROTO_ICMP: "icmp",
            IPPROTO_TCP: "tcp",
            IPPROTO_UDP: "udp",
            IPPROTO_ICMPV6: "icmpv6",
        }
        proto_name = proto_map.get(proto_num, f"ip-{proto_num}")
        
        protocol_counts[proto_name] = protocol_counts.get(proto_name, 0) + 1
        
        # Host stats
        for ip in (src_ip, dst_ip):
            if ip not in host_stats:
                host_stats[ip] = {"packets": 0, "bytes": 0, "first_seen": ts, "last_seen": ts}
            host_stats[ip]["packets"] += 1
            host_stats[ip]["bytes"] += packet_len
            host_stats[ip]["first_seen"] = min(host_stats[ip]["first_seen"], ts)
            host_stats[ip]["last_seen"] = max(host_stats[ip]["last_seen"], ts)
        
        # Conversation stats (bidirectional - normalize direction)
        # Use tuple with sorted IPs to group bidirectional flows
        conv_key = (src_ip, dst_ip, proto_name)
        if conv_key not in conversation_stats:
            conversation_stats[conv_key] = {"packets": 0, "bytes": 0}
        conversation_stats[conv_key]["packets"] += 1
        conversation_stats[conv_key]["bytes"] += packet_len

    def _parse_ethernet(self, data: bytes) -> Optional[dict]:
        """Parse Ethernet frame header. Returns dict with ethertype and payload, or None."""
        if len(data) < 14:
            return None
        
        dst_mac = data[0:6]
        src_mac = data[6:12]
        ethertype = struct.unpack(">H", data[12:14])[0]
        
        # Handle VLAN tagging (802.1Q) - ethertype would be 0x8100
        payload_offset = 14
        if ethertype == 0x8100 and len(data) >= 18:
            ethertype = struct.unpack(">H", data[14:16])[0]
            payload_offset = 18
        
        return {
            "dst_mac": dst_mac,
            "src_mac": src_mac,
            "ethertype": ethertype,
            "payload": data[payload_offset:],
        }

    def _parse_ipv4(self, data: bytes) -> Optional[dict]:
        """Parse IPv4 header. Returns dict with src_ip, dst_ip, protocol, payload, or None."""
        if len(data) < 20:
            return None
        
        version_ihl = data[0]
        version = version_ihl >> 4
        if version != 4:
            return None
        
        ihl = version_ihl & 0x0F
        header_len = ihl * 4
        
        if len(data) < header_len:
            return None
        
        # Protocol is at offset 9, src/dst at offsets 12-19
        protocol = data[9]
        src_ip = socket.inet_ntoa(data[12:16])
        dst_ip = socket.inet_ntoa(data[16:20])
        
        return {
            "src_ip": src_ip,
            "dst_ip": dst_ip,
            "protocol": protocol,
            "payload": data[header_len:],
        }

    def _parse_ipv6(self, data: bytes) -> Optional[dict]:
        """Parse IPv6 header. Returns dict with src_ip, dst_ip, protocol, or None."""
        if len(data) < 40:
            return None
        
        # IPv6 fixed header is 40 bytes
        # Next header is at offset 6, src at 8-23, dst at 24-39
        protocol = data[6]
        src_ip = socket.inet_ntop(socket.AF_INET6, data[8:24])
        dst_ip = socket.inet_ntop(socket.AF_INET6, data[24:40])
        
        return {
            "src_ip": src_ip,
            "dst_ip": dst_ip,
            "protocol": protocol,
            "payload": data[40:],
        }


# Module-level singleton
_pcap_parser: Optional[PcapParser] = None


def get_pcap_parser() -> PcapParser:
    """Get or create the singleton PCAP parser instance."""
    global _pcap_parser
    if _pcap_parser is None:
        _pcap_parser = PcapParser()
    return _pcap_parser