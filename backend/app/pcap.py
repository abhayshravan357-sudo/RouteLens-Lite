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


@dataclass
class PcapPacket:
    """A single parsed packet from a PCAP file."""
    ts_sec: int
    ts_usec: int
    incl_len: int
    orig_len: int
    data: bytes


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
            return PcapAnalysisResult(
                filename=filename,
                size_bytes=len(data),
                format="pcapng",
                parsed=False,
                error="PCAPNG format detected but not yet supported",
                collected_at=collected_at,
            )

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

    def _analyze_packets(
        self,
        packets: list[PcapPacket],
        filename: str,
        file_size: int,
        link_type: int,
        collected_at: str,
        ts_resolution: int,
    ) -> PcapAnalysisResult:
        """Analyze parsed packets and build statistics."""
        
        # Track hosts, conversations, protocols
        host_stats: dict[str, dict] = {}
        conversation_stats: dict[tuple[str, str, str], dict] = {}
        protocol_counts: dict[str, int] = {}
        
        start_ts = float('inf')
        end_ts = float('-inf')
        
        for pkt in packets:
            # Convert timestamp
            ts = pkt.ts_sec + (pkt.ts_usec / ts_resolution)
            start_ts = min(start_ts, ts)
            end_ts = max(end_ts, ts)
            
            # Parse Ethernet frame
            eth = self._parse_ethernet(pkt.data)
            if not eth:
                protocol_counts["unknown"] = protocol_counts.get("unknown", 0) + 1
                continue
            
            # Count protocol at Ethernet level
            ethertype = eth.get("ethertype")
            if ethertype == ETHERTYPE_IPV4:
                ipv4 = self._parse_ipv4(eth["payload"])
                if ipv4:
                    src_ip, dst_ip, proto = ipv4["src_ip"], ipv4["dst_ip"], ipv4["protocol"]
                    self._update_stats(
                        src_ip, dst_ip, proto, len(pkt.data), ts,
                        host_stats, conversation_stats, protocol_counts
                    )
            elif ethertype == ETHERTYPE_IPV6:
                ipv6 = self._parse_ipv6(eth["payload"])
                if ipv6:
                    src_ip, dst_ip, proto = ipv6["src_ip"], ipv6["dst_ip"], ipv6["protocol"]
                    self._update_stats(
                        src_ip, dst_ip, proto, len(pkt.data), ts,
                        host_stats, conversation_stats, protocol_counts
                    )
            elif ethertype == ETHERTYPE_ARP:
                protocol_counts["arp"] = protocol_counts.get("arp", 0) + 1
            else:
                protocol_counts["other"] = protocol_counts.get("other", 0) + 1

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
        )

        return PcapAnalysisResult(
            filename=filename,
            size_bytes=file_size,
            format="pcap",
            parsed=True,
            collected_at=collected_at,
            summary=summary,
            hosts=hosts,
            conversations=conversations,
            limitations=[
                "This analysis is based on a single captured file",
                "Only protocols present in the capture are counted",
                "Timestamps come from the capture file, not the system clock",
                "Only Ethernet (link type 1) packets are fully parsed",
                "Fragmented IP packets are not reassembled",
                "VLAN tags (802.1Q) are not parsed",
            ],
        )

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