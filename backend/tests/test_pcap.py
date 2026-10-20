"""
Tests for the PCAP parser and API endpoint.
"""

import base64
import socket
import struct
import pytest
from fastapi.testclient import TestClient

from app.pcap import get_pcap_parser, PcapAnalysisResult, PcapParser
from app.main import app


class TestPcapParser:
    """Tests for the PcapParser class."""

    @pytest.fixture
    def parser(self):
        return PcapParser()

    def _build_pcap_global_header(self, endian="<", nanoseconds=False):
        """Build a PCAP global header in the given byte order.

        A real capture file writes the magic number in the file's own byte
        order, and writes everything else in that order too. The magic
        *value* is always 0xa1b2c3d4; packing it little-endian puts the
        bytes on disk as d4 c3 b2 a1, which is what a little-endian
        capture starts with. Building the magic in one order and the rest
        in another produces a file no tool would ever write, and it hides
        byte-order bugs.
        """
        magic = 0xA1B23C4D if nanoseconds else 0xA1B2C3D4
        return struct.pack(
            f"{endian}IHHIIII",
            magic,      # magic, in the file's own byte order
            2,          # version_major
            4,          # version_minor
            0,          # thiszone
            0,          # sigfigs
            65535,      # snaplen
            1,          # network (Ethernet)
        )

    def _build_packet_header(self, ts_sec=0, ts_usec=0, incl_len=0, orig_len=0, endian="<"):
        """Build a PCAP packet header in the given byte order."""
        return struct.pack(f"{endian}IIII", ts_sec, ts_usec, incl_len, orig_len)

    def _build_ethernet_frame(self, src_mac, dst_mac, ethertype, payload):
        """Build an Ethernet frame."""
        frame = dst_mac + src_mac + struct.pack(">H", ethertype)
        frame += payload
        return frame

    def _build_ipv4_packet(self, src_ip, dst_ip, protocol, payload=b""):
        """Build a minimal IPv4 packet."""
        # Version 4, IHL 5 (20 bytes header)
        version_ihl = (4 << 4) | 5
        # DSCP/ECN
        dscp_ecn = 0
        # Total length (header + payload)
        total_len = 20 + len(payload)
        # Identification, flags, fragment offset
        identification = 0
        flags_frag = 0
        # TTL, protocol
        ttl = 64
        # Header checksum (0 for now)
        checksum = 0
        src_bytes = socket.inet_aton(src_ip)
        dst_bytes = socket.inet_aton(dst_ip)
        
        header = struct.pack(
            ">BBHHHBBH4s4s",
            version_ihl, dscp_ecn, total_len, identification,
            flags_frag, ttl, protocol, checksum,
            src_bytes, dst_bytes
        )
        return header + payload

    def test_parse_empty_pcap(self, parser):
        """Test parsing a PCAP with global header but no packets."""
        pcap = self._build_pcap_global_header()
        result = parser.parse(pcap, "empty.pcap")
        assert result.parsed is True
        assert result.format == "pcap"
        assert result.error is None
        assert result.summary.total_packets == 0
        assert result.summary.total_bytes == 0

    def test_parses_a_real_little_endian_file(self, parser):
        """A file as tcpdump writes on x86 must parse.

        The magic bytes of a little-endian capture are d4 c3 b2 a1, and
        everything after them is little-endian too. Reading the magic as
        a little-endian integer gives 0xa1b2c3d4, which is the *value*
        used by a big-endian file, so deriving the byte order from that
        value rather than from the raw bytes swaps every real file.
        """
        frame = self._build_ethernet_frame(
            b"\x00\x11\x22\x33\x44\x55",
            b"\x66\x77\x88\x99\xaa\xbb",
            0x0800,
            self._build_ipv4_packet("10.0.0.1", "10.0.0.2", 1, b"\x08\x00\x00\x00"),
        )
        pcap = self._build_pcap_global_header(endian="<")
        pcap += self._build_packet_header(1000, 0, len(frame), len(frame), endian="<")
        pcap += frame

        result = parser.parse(pcap, "real-le.pcap")
        assert result.parsed is True, result.error
        assert result.summary.total_packets == 1
        assert result.summary.total_bytes == len(frame)
        assert "icmp" in result.summary.protocols

    def test_parses_a_real_big_endian_file(self, parser):
        """A big-endian capture must parse too."""
        frame = self._build_ethernet_frame(
            b"\x00\x11\x22\x33\x44\x55",
            b"\x66\x77\x88\x99\xaa\xbb",
            0x0800,
            self._build_ipv4_packet("10.0.0.1", "10.0.0.2", 1, b"\x08\x00\x00\x00"),
        )
        pcap = self._build_pcap_global_header(endian=">")
        pcap += self._build_packet_header(1000, 0, len(frame), len(frame), endian=">")
        pcap += frame

        result = parser.parse(pcap, "real-be.pcap")
        assert result.parsed is True, result.error
        assert result.summary.total_packets == 1
        assert "icmp" in result.summary.protocols

    def test_parses_a_nanosecond_resolution_file(self, parser):
        """The nanosecond magic variants must parse as well."""
        frame = self._build_ethernet_frame(
            b"\x00\x11\x22\x33\x44\x55",
            b"\x66\x77\x88\x99\xaa\xbb",
            0x0800,
            self._build_ipv4_packet("10.0.0.1", "10.0.0.2", 1, b"\x08\x00\x00\x00"),
        )
        pcap = self._build_pcap_global_header(endian="<", nanoseconds=True)
        pcap += self._build_packet_header(1000, 0, len(frame), len(frame), endian="<")
        pcap += frame

        result = parser.parse(pcap, "ns.pcap")
        assert result.parsed is True, result.error
        assert result.summary.total_packets == 1

    def test_parse_pcapng_detected(self, parser):
        """Test that PCAPNG is detected but not parsed."""
        # PCAPNG magic number
        pcapng = struct.pack("<I", 0x0a0d0d0a) + b"\x00" * 20
        result = parser.parse(pcapng, "test.pcapng")
        assert result.parsed is False
        assert result.format == "pcapng"
        assert "not yet supported" in result.error

    def test_parse_bad_magic(self, parser):
        """Test that unknown magic number gives clear error."""
        bad = struct.pack("<I", 0xdeadbeef) + b"\x00" * 20
        result = parser.parse(bad, "bad.pcap")
        assert result.parsed is False
        assert result.format == "unknown"
        assert "Unknown PCAP magic" in result.error

    def test_parse_truncated_global_header(self, parser):
        """Test truncated global header."""
        truncated = b"\xd4\xc3\xb2"  # Only 3 bytes
        result = parser.parse(truncated, "truncated.pcap")
        assert result.parsed is False
        assert "too small" in result.error or "Failed to parse global header" in result.error

    def test_parse_single_icmp_packet(self, parser):
        """Test parsing a PCAP with one ICMP packet."""
        global_hdr = self._build_pcap_global_header()
        
        # Build ICMP packet
        eth = self._build_ethernet_frame(
            b"\x00\x01\x02\x03\x04\x05",
            b"\x06\x07\x08\x09\x0a\x0b",
            0x0800,  # IPv4
            b""
        )
        
        ipv4 = self._build_ipv4_packet("10.0.0.1", "10.0.0.2", 1)  # ICMP
        # Simple ICMP echo request (type=8, code=0, checksum=0 for test)
        icmp = struct.pack(">BBHH", 8, 0, 0, 0x1234) + b"test"
        packet_data = eth + ipv4 + icmp
        
        pkt_hdr = self._build_packet_header(
            ts_sec=1000, ts_usec=0,
            incl_len=len(packet_data), orig_len=len(packet_data)
        )
        
        pcap = global_hdr + pkt_hdr + packet_data
        result = parser.parse(pcap, "icmp.pcap")
        
        assert result.parsed is True
        assert result.summary.total_packets == 1
        assert "icmp" in result.summary.protocols
        assert len(result.hosts) == 2
        assert result.conversations[0].protocol == "icmp"

    def test_parse_tcp_packet(self, parser):
        """Test parsing a PCAP with a TCP packet."""
        global_hdr = self._build_pcap_global_header()
        
        # TCP payload
        tcp_payload = b"HTTP/1.1 200 OK\r\n\r\n"
        tcp_header = struct.pack(
            ">HHIIBBHHH",
            80,      # src port
            12345,   # dst port
            0,       # seq
            0,       # ack
            (5 << 4), # data offset
            0x18,    # flags: PSH + ACK
            65535,   # window
            0,       # checksum
            0        # urgent
        )
        
        eth = self._build_ethernet_frame(
            b"\x00\x01\x02\x03\x04\x05",
            b"\x06\x07\x08\x09\x0a\x0b",
            0x0800,
            b""
        )
        
        ipv4 = self._build_ipv4_packet("192.168.1.1", "192.168.1.2", 6, tcp_header + b"GET / HTTP/1.1")
        packet_data = eth + ipv4
        
        pkt_hdr = self._build_packet_header(
            ts_sec=2000, ts_usec=500000,
            incl_len=len(packet_data), orig_len=len(packet_data)
        )
        
        pcap = global_hdr + pkt_hdr + packet_data
        result = parser.parse(pcap, "tcp.pcap")
        
        assert result.parsed is True
        assert result.summary.total_packets == 1
        assert "tcp" in result.summary.protocols
        assert len(result.hosts) == 2

    def test_parse_ipv6_packet(self, parser):
        """Test parsing a PCAP with an IPv6 packet."""
        global_hdr = self._build_pcap_global_header()
        
        # IPv6 header (40 bytes fixed)
        ipv6_header = struct.pack(
            ">IHBB16s16s",
            (6 << 28),  # version=6, traffic class=0, flow label=0
            0,          # payload length (0 for now)
            58,         # next header = ICMPv6
            64,         # hop limit
            socket.inet_pton(socket.AF_INET6, "2001:db8::1"),
            socket.inet_pton(socket.AF_INET6, "2001:db8::2"),
        )
        
        # ICMPv6 echo request
        icmpv6 = struct.pack(">BBHH", 128, 0, 0, 0x1234) + b"test"
        
        eth = self._build_ethernet_frame(
            b"\x00\x01\x02\x03\x04\x05",
            b"\x06\x07\x08\x09\x0a\x0b",
            0x86DD,  # IPv6
            ipv6_header + icmpv6
        )
        
        packet_data = eth
        pkt_hdr = self._build_packet_header(
            ts_sec=3000, ts_usec=0,
            incl_len=len(packet_data), orig_len=len(packet_data)
        )
        
        pcap = global_hdr + pkt_hdr + packet_data
        result = parser.parse(pcap, "ipv6.pcap")
        
        assert result.parsed is True
        assert result.summary.total_packets == 1
        assert "icmpv6" in result.summary.protocols or "ip-58" in result.summary.protocols

    def test_parse_truncated_packet(self, parser):
        """Test that truncated packet data gives clear error."""
        global_hdr = self._build_pcap_global_header()
        pkt_hdr = self._build_packet_header(
            ts_sec=1000, ts_usec=0,
            incl_len=100, orig_len=100  # Claims 100 bytes but we provide less
        )
        # Only provide 10 bytes of packet data
        pcap = global_hdr + pkt_hdr + b"short"
        
        result = parser.parse(pcap, "truncated.pcap")
        assert result.parsed is False
        assert "Truncated" in result.error

    def test_parse_oversized_file(self, parser):
        """Test file size limit enforcement."""
        large_data = b"x" * (33 * 1024 * 1024)  # 33 MB
        result = parser.parse(large_data, "large.pcap")
        assert result.parsed is False
        assert "exceeds maximum" in result.error


class TestPcapEndpoint:
    """Tests for the PCAP analysis API endpoint."""

    @pytest.fixture
    def client(self):
        return TestClient(app)

    def _make_pcap_base64(self, packets_data: list[tuple[int, bytes]]) -> str:
        """Create a base64-encoded PCAP from packet data.
        
        packets_data: list of (timestamp_sec, raw_ethernet_frame_bytes)
        """
        global_hdr = struct.pack("<IHHIIII", 0xA1B2C3D4, 2, 4, 0, 0, 65535, 1)
        parts = [global_hdr]

        for ts_sec, frame in packets_data:
            pkt_hdr = struct.pack("<IIII", ts_sec, 0, len(frame), len(frame))
            parts.append(pkt_hdr)
            parts.append(frame)
        
        return base64.b64encode(b"".join(parts)).decode()

    def _build_icmp_frame(self, src_ip, dst_ip):
        """Build an Ethernet frame with IPv4/ICMP."""
        src_mac = b"\x00\x01\x02\x03\x04\x05"
        dst_mac = b"\x06\x07\x08\x09\x0a\x0b"
        
        eth = struct.pack(">6s6sH", dst_mac, src_mac, 0x0800)
        
        ipv4 = struct.pack(
            ">BBHHHBBH4s4s",
            0x45, 0, 20 + 8 + 8,  # version/ihl, dscp, total_len
            0, 0, 64, 1, 0,       # id, flags/frag, ttl, proto=1, checksum
            socket.inet_aton(src_ip), socket.inet_aton(dst_ip)
        )
        
        icmp = struct.pack(">BBHH", 8, 0, 0, 0x1234) + b"test"
        
        return eth + ipv4 + icmp

    def test_analyze_valid_pcap(self, client):
        """Test analyzing a valid PCAP with ICMP packets."""
        frame = self._build_icmp_frame("10.0.0.1", "10.0.0.2")
        b64 = self._make_pcap_base64([(1000, frame)])
        
        response = client.post(
            "/api/pcap/analyze",
            json={"filename": "test.pcap", "data_base64": b64}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["filename"] == "test.pcap"
        assert data["parsed"] is True
        assert data["format"] == "pcap"
        assert data["error"] is None
        assert data["summary"]["total_packets"] == 1
        assert "icmp" in data["summary"]["protocols"]
        assert len(data["hosts"]) == 2
        assert len(data["conversations"]) == 1
        assert data["conversations"][0]["protocol"] == "icmp"

    def test_analyze_pcapng_reported_unsupported(self, client):
        """Test that PCAPNG is reported as unsupported."""
        pcapng_data = struct.pack("<I", 0x0a0d0d0a) + b"\x00" * 100
        b64 = base64.b64encode(pcapng_data).decode()
        
        response = client.post(
            "/api/pcap/analyze",
            json={"filename": "test.pcapng", "data_base64": b64}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["parsed"] is False
        assert data["format"] == "pcapng"
        assert "not yet supported" in data["error"]

    def test_analyze_truncated_pcap(self, client):
        """Test that truncated PCAP gives clear error."""
        global_hdr = struct.pack("<IHHIIII", 0xA1B2C3D4, 2, 4, 0, 0, 65535, 1)
        pkt_hdr = struct.pack("<IIII", 1000, 0, 100, 100)
        pcap = global_hdr + pkt_hdr + b"short"  # Only 5 bytes, claims 100
        b64 = base64.b64encode(pcap).decode()
        
        response = client.post(
            "/api/pcap/analyze",
            json={"filename": "truncated.pcap", "data_base64": b64}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["parsed"] is False
        assert "Truncated" in data["error"]

    def test_reject_invalid_base64(self, client):
        """Test rejection of invalid base64."""
        response = client.post(
            "/api/pcap/analyze",
            json={"filename": "test.pcap", "data_base64": "not valid base64!!!"}
        )

        assert response.status_code == 422
        detail = response.json()["detail"]
        # A validation failure is reported as a sentence, not a list of
        # Pydantic error objects, so a student reads the message the app
        # actually wrote.
        assert isinstance(detail, str)
        assert "Invalid base64" in detail
        assert "Value error" not in detail

    def test_reject_empty_body(self, client):
        """Test rejection of empty request body."""
        response = client.post("/api/pcap/analyze", json={})
        assert response.status_code == 422  # Validation error

    def test_reject_missing_filename(self, client):
        """Test rejection of missing filename."""
        frame = self._build_icmp_frame("10.0.0.1", "10.0.0.2")
        global_hdr = struct.pack("<IHHIIII", 0xA1B2C3D4, 2, 4, 0, 0, 65535, 1)
        pkt_hdr = struct.pack("<IIII", 1000, 0, len(frame), len(frame))
        pcap = global_hdr + pkt_hdr + frame
        b64 = base64.b64encode(pcap).decode()
        
        response = client.post(
            "/api/pcap/analyze",
            json={"data_base64": b64}  # Missing filename
        )
        
        assert response.status_code == 422

    def test_reject_oversized_file(self, client):
        """Test rejection of file over 32 MB."""
        large_data = b"x" * (33 * 1024 * 1024)
        b64 = base64.b64encode(large_data).decode()
        
        response = client.post(
            "/api/pcap/analyze",
            json={"filename": "large.pcap", "data_base64": b64}
        )
        
        assert response.status_code == 413
        assert "exceeds maximum" in response.json()["detail"]

    def test_limitations_included(self, client):
        """Test that limitations are included in response."""
        frame = self._build_icmp_frame("10.0.0.1", "10.0.0.2")
        b64 = self._make_pcap_base64([(1000, frame)])
        
        response = client.post(
            "/api/pcap/analyze",
            json={"filename": "test.pcap", "data_base64": b64}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "limitations" in data
        assert len(data["limitations"]) > 0
        assert any("single captured file" in lim for lim in data["limitations"])

    def test_the_vlan_limitation_says_what_the_parser_actually_does(self, client):
        """
        The limitation must not understate the parser.

        A VLAN tag is skipped and the protocol inside it is still read, so
        saying the tag is "not parsed" would tell a student their
        VLAN-tagged frame would not be understood when in fact it is.
        """
        frame = self._build_icmp_frame("10.0.0.1", "10.0.0.2")
        b64 = self._make_pcap_base64([(1000, frame)])

        response = client.post(
            "/api/pcap/analyze",
            json={"filename": "test.pcap", "data_base64": b64}
        )

        assert response.status_code == 200
        limitations = response.json()["limitations"]
        vlan = [lim for lim in limitations if "VLAN" in lim]
        assert vlan, "the VLAN limitation is not stated at all"
        assert not any("are not parsed" in lim for lim in vlan), (
            f"the VLAN limitation understates the parser: {vlan}"
        )
        assert any("skipped" in lim for lim in vlan), (
            f"the VLAN limitation does not say what happens: {vlan}"
        )

    def test_hosts_and_conversations_structure(self, client):
        """Test that hosts and conversations have correct structure."""
        frame = self._build_icmp_frame("10.0.0.1", "10.0.0.2")
        b64 = self._make_pcap_base64([(1000, frame)])
        
        response = client.post(
            "/api/pcap/analyze",
            json={"filename": "test.pcap", "data_base64": b64}
        )
        
        assert response.status_code == 200
        data = response.json()
        
        # Check hosts
        for host in data["hosts"]:
            assert "ip" in host
            assert "packets" in host
            assert "bytes" in host
            assert "first_seen" in host
            assert "last_seen" in host
            assert isinstance(host["packets"], int)
            assert host["packets"] > 0
        
        # Check conversations
        for conv in data["conversations"]:
            assert "src" in conv
            assert "dst" in conv
            assert "protocol" in conv
            assert "packets" in conv
            assert "bytes" in conv


if __name__ == "__main__":
    pytest.main([__file__, "-v"])