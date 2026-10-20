"""
Tests for the deeper PCAP analysis: transport ports, TCP flags, three-way
handshakes, ICMP types, DNS names, ARP hardware addresses and PCAPNG.

The capture files in this module are built byte by byte, the way a capture
tool writes them. Every builder here was checked against tcpdump, which is
an independent implementation: if these bytes were wrong, tcpdump would
read something different from what the parser reports. A capture that only
this parser agrees with would prove nothing.

The last test class runs tcpdump over the same bytes this module builds and
asserts that the two agree. It is skipped when tcpdump is not installed.
"""

import shutil
import socket
import struct
import subprocess

import pytest

from app.pcap import get_pcap_parser, PcapParser


# --------------------------------------------------------------------------
# Byte builders. These write the bytes a capture tool would write.
# --------------------------------------------------------------------------

MAC_CLIENT = bytes.fromhex("000102030405")
MAC_SERVER = bytes.fromhex("060708090a0b")
MAC_ARP_SENDER = bytes.fromhex("aabbccddeeff")
MAC_ARP_TARGET = bytes.fromhex("112233445566")
BROADCAST_MAC = b"\xff" * 6

ETHERTYPE_IPV4 = 0x0800
ETHERTYPE_ARP = 0x0806

IPPROTO_ICMP = 1
IPPROTO_TCP = 6
IPPROTO_UDP = 17

TCP_FIN = 0x01
TCP_SYN = 0x02
TCP_RST = 0x04
TCP_PSH = 0x08
TCP_ACK = 0x10
TCP_URG = 0x20


def build_ethernet(dst_mac, src_mac, ethertype, payload):
    """An Ethernet II frame: destination, source, then the EtherType."""
    return dst_mac + src_mac + struct.pack(">H", ethertype) + payload


def build_ipv4(src_ip, dst_ip, protocol, payload, ttl=64):
    """An IPv4 header with a 20-byte IHL and no options, plus its payload."""
    total_length = 20 + len(payload)
    return struct.pack(
        ">BBHHHBBH4s4s",
        0x45,                          # version 4, IHL 5
        0x00,                          # DSCP / ECN
        total_length,
        0x0000,                        # identification
        0x0000,                        # flags / fragment offset
        ttl,
        protocol,
        0x0000,                        # header checksum (not verified)
        socket.inet_aton(src_ip),
        socket.inet_aton(dst_ip),
    ) + payload


def build_tcp(src_port, dst_port, flags, seq=0, ack=0, payload=b""):
    """A TCP header with a 20-byte data offset, plus its payload."""
    return struct.pack(
        ">HHIIBBHHH",
        src_port,
        dst_port,
        seq,
        ack,
        5 << 4,                        # data offset, in 32-bit words
        flags,
        0xFFFF,                        # window
        0x0000,                        # checksum
        0x0000,                        # urgent pointer
    ) + payload


def build_udp(src_port, dst_port, payload):
    """A UDP header, plus its payload."""
    return struct.pack(">HHHH", src_port, dst_port, 8 + len(payload), 0x0000) + payload


def build_icmp(icmp_type, code, identifier=0x1234, sequence=1, body=b""):
    """An ICMP header. Echo types carry an identifier and a sequence."""
    return struct.pack(">BBHHH", icmp_type, code, 0x0000, identifier, sequence) + body


def build_icmp_unreachable(code):
    """
    A destination-unreachable message.

    A real one quotes the IP header and the first eight bytes of the
    datagram that could not be delivered, so the body is built that way.
    """
    quoted = build_ipv4("10.0.0.9", "10.0.0.1", IPPROTO_UDP, b"\x00" * 8)
    return build_icmp(3, code, body=quoted)


def build_arp_request(sender_mac, sender_ip, target_mac, target_ip):
    """An ARP request: who has target_ip? tell sender_ip."""
    return struct.pack(
        ">HHBBH",
        1,                              # hardware type: Ethernet
        0x0800,                         # protocol type: IPv4
        6,                              # hardware address length
        4,                              # protocol address length
        1,                              # operation: request
    ) + sender_mac + socket.inet_aton(sender_ip) \
        + target_mac + socket.inet_aton(target_ip)


def build_dns_name(name):
    """A DNS name in label form: length-prefixed labels, then a zero byte."""
    out = b""
    for label in name.split("."):
        out += bytes([len(label)]) + label.encode("ascii")
    return out + b"\x00"


def build_dns_query(query_id, name):
    """A DNS query for one name."""
    header = struct.pack(">HHHHHH", query_id, 0x0100, 1, 0, 0, 0)
    return header + build_dns_name(name) + struct.pack(">HH", 1, 1)


def build_dns_response(query_id, name, address):
    """
    A DNS response carrying one A record.

    The answer's name is a compression pointer back to the question, which
    is what a real resolver sends.
    """
    header = struct.pack(">HHHHHH", query_id, 0x8180, 1, 1, 0, 0)
    question = build_dns_name(name) + struct.pack(">HH", 1, 1)
    answer = b"\xc0\x0c" + struct.pack(">HHIH", 1, 1, 300, 4) + socket.inet_aton(address)
    return header + question + answer


def build_pcap(frames, endian="<", nanoseconds=False, base_ts=1700000000):
    """
    A classic PCAP file.

    The magic number is written in the file's own byte order, and so is
    everything else in the file. The magic *value* is always 0xa1b2c3d4, so
    packing it little-endian puts the bytes on disk as d4 c3 b2 a1, which is
    what a capture taken on a little-endian machine starts with.
    """
    magic = 0xA1B23C4D if nanoseconds else 0xA1B2C3D4
    out = struct.pack(f"{endian}IHHIIII", magic, 2, 4, 0, 0, 65535, 1)
    for index, frame in enumerate(frames):
        out += struct.pack(
            f"{endian}IIII", base_ts + index, 0, len(frame), len(frame)
        ) + frame
    return out


def build_pcapng_block(endian, block_type, body):
    """A PCAPNG block: type, total length, body, then the length again."""
    total_length = 12 + len(body)
    return (
        struct.pack(f"{endian}I", block_type)
        + struct.pack(f"{endian}I", total_length)
        + body
        + struct.pack(f"{endian}I", total_length)
    )


def build_pcapng(frames, endian="<", ts_resolution=6):
    """
    A PCAPNG file with a section header, one interface, and one enhanced
    packet block per frame.

    The byte-order magic lives in the section header and says how to read
    every block in that section.
    """
    if endian == "<":
        byte_order_magic = struct.pack("<I", 0x1A2B3C4D)
    else:
        byte_order_magic = struct.pack(">I", 0x1A2B3C4D)

    shb_body = (
        byte_order_magic
        + struct.pack(f"{endian}HH", 1, 0)
        + struct.pack(f"{endian}q", -1)
    )
    out = build_pcapng_block(endian, 0x0A0D0D0A, shb_body)

    idb_body = struct.pack(f"{endian}HHI", 1, 0, 65535)
    idb_body += struct.pack(f"{endian}HH", 9, 1) + bytes([ts_resolution]) + b"\x00" * 3
    idb_body += struct.pack(f"{endian}HH", 0, 0)
    out += build_pcapng_block(endian, 0x00000001, idb_body)

    for index, frame in enumerate(frames):
        units = (1700000000 * (10 ** ts_resolution)) + index * 1000
        body = struct.pack(
            f"{endian}IIIII",
            0,                                  # interface id
            (units >> 32) & 0xFFFFFFFF,        # timestamp high
            units & 0xFFFFFFFF,                 # timestamp low
            len(frame),
            len(frame),
        )
        body += frame + b"\x00" * ((-len(frame)) % 4)
        out += build_pcapng_block(endian, 0x00000006, body)

    return out


# --------------------------------------------------------------------------
# Ready-made frames
# --------------------------------------------------------------------------

def tcp_syn_frame(src_ip="10.0.0.1", dst_ip="10.0.0.2", src_port=12345, dst_port=80):
    return build_ethernet(
        MAC_SERVER, MAC_CLIENT, ETHERTYPE_IPV4,
        build_ipv4(src_ip, dst_ip, IPPROTO_TCP,
                   build_tcp(src_port, dst_port, TCP_SYN)),
    )


def tcp_syn_ack_frame(src_ip="10.0.0.2", dst_ip="10.0.0.1", src_port=80, dst_port=12345):
    return build_ethernet(
        MAC_CLIENT, MAC_SERVER, ETHERTYPE_IPV4,
        build_ipv4(src_ip, dst_ip, IPPROTO_TCP,
                   build_tcp(src_port, dst_port, TCP_SYN | TCP_ACK)),
    )


def tcp_ack_frame(src_ip="10.0.0.1", dst_ip="10.0.0.2", src_port=12345, dst_port=80):
    return build_ethernet(
        MAC_SERVER, MAC_CLIENT, ETHERTYPE_IPV4,
        build_ipv4(src_ip, dst_ip, IPPROTO_TCP,
                   build_tcp(src_port, dst_port, TCP_ACK)),
    )


def handshake_frames():
    return [tcp_syn_frame(), tcp_syn_ack_frame(), tcp_ack_frame()]


# --------------------------------------------------------------------------
# Tests
# --------------------------------------------------------------------------

class TestCaptureBuilders:
    """Checks on the bytes the builders produce, before anything parses them."""

    def test_little_endian_pcap_starts_with_the_little_endian_magic(self):
        """A little-endian capture starts with the bytes d4 c3 b2 a1."""
        data = build_pcap([], endian="<")
        assert data[:4] == b"\xd4\xc3\xb2\xa1"

    def test_big_endian_pcap_starts_with_the_big_endian_magic(self):
        """A big-endian capture starts with the bytes a1 b2 c3 d4."""
        data = build_pcap([], endian=">")
        assert data[:4] == b"\xa1\xb2\xc3\xd4"

    def test_pcapng_starts_with_the_section_header_magic(self):
        """A PCAPNG file starts with 0a 0d 0d 0a."""
        data = build_pcapng([])
        assert data[:4] == b"\x0a\x0d\x0d\x0a"

    def test_the_frame_builders_produce_the_expected_lengths(self):
        """A frame is header plus payload, with no slack."""
        tcp_frame = tcp_syn_frame()
        assert len(tcp_frame) == 14 + 20 + 20

        udp_frame = build_ethernet(
            MAC_SERVER, MAC_CLIENT, ETHERTYPE_IPV4,
            build_ipv4("10.0.0.1", "10.0.0.2", IPPROTO_UDP,
                       build_udp(5000, 6000, b"abcd")),
        )
        assert len(udp_frame) == 14 + 20 + 8 + 4

        arp_frame = build_ethernet(
            BROADCAST_MAC, MAC_CLIENT, ETHERTYPE_ARP,
            build_arp_request(MAC_ARP_SENDER, "10.0.0.1",
                              MAC_ARP_TARGET, "10.0.0.2"),
        )
        assert len(arp_frame) == 14 + 28


class TestTransportPorts:
    """Transport layer ports."""

    @pytest.fixture
    def parser(self):
        return PcapParser()

    def test_tcp_ports_are_reported(self, parser):
        """TCP source and destination ports are read from the header."""
        result = parser.parse(build_pcap([tcp_syn_frame()]), "tcp.pcap")
        assert result.parsed is True
        detail = result.packets[0]
        assert detail.src_port == 12345
        assert detail.dst_port == 80
        assert detail.protocol == "tcp"

    def test_udp_ports_are_reported(self, parser):
        """UDP source and destination ports are read from the header."""
        frame = build_ethernet(
            MAC_SERVER, MAC_CLIENT, ETHERTYPE_IPV4,
            build_ipv4("10.0.0.1", "10.0.0.2", IPPROTO_UDP,
                       build_udp(5000, 6000, b"payload")),
        )
        result = parser.parse(build_pcap([frame]), "udp.pcap")
        detail = result.packets[0]
        assert detail.src_port == 5000
        assert detail.dst_port == 6000
        assert detail.protocol == "udp"

    def test_ports_are_marked_as_observed(self, parser):
        """Ports come straight out of the bytes, so they are observed."""
        result = parser.parse(build_pcap([tcp_syn_frame()]), "tcp.pcap")
        detail = result.packets[0]
        assert detail.provenance["src_port"] == "observed"
        assert detail.provenance["dst_port"] == "observed"


class TestTcpFlags:
    """TCP flag bits and the flags they represent."""

    @pytest.fixture
    def parser(self):
        return PcapParser()

    def test_flags_are_reported(self, parser):
        """Each flag bit is named."""
        result = parser.parse(build_pcap([tcp_syn_frame()]), "syn.pcap")
        detail = result.packets[0]
        assert detail.tcp_flags == ["SYN"]
        assert detail.tcp_flags_value == TCP_SYN

    def test_syn_and_ack_are_both_reported(self, parser):
        """A SYN+ACK carries two flags."""
        result = parser.parse(build_pcap([tcp_syn_ack_frame()]), "synack.pcap")
        detail = result.packets[0]
        assert set(detail.tcp_flags) == {"SYN", "ACK"}

    def test_every_named_flag_is_recognised(self, parser):
        """SYN, ACK, FIN, RST, PSH and URG are all reported by name."""
        frame = build_ethernet(
            MAC_SERVER, MAC_CLIENT, ETHERTYPE_IPV4,
            build_ipv4("10.0.0.1", "10.0.0.2", IPPROTO_TCP,
                       build_tcp(12345, 80,
                                 TCP_SYN | TCP_ACK | TCP_FIN | TCP_RST | TCP_PSH | TCP_URG)),
        )
        result = parser.parse(build_pcap([frame]), "all.pcap")
        detail = result.packets[0]
        assert set(detail.tcp_flags) == {"SYN", "ACK", "FIN", "RST", "PSH", "URG"}

    def test_a_plain_ack_has_only_the_ack_flag(self, parser):
        """The final packet of a handshake carries ACK on its own."""
        result = parser.parse(build_pcap([tcp_ack_frame()]), "ack.pcap")
        detail = result.packets[0]
        assert detail.tcp_flags == ["ACK"]

    def test_flags_are_marked_as_observed(self, parser):
        """Flags are read directly from the header, so they are observed."""
        result = parser.parse(build_pcap([tcp_syn_frame()]), "syn.pcap")
        assert result.packets[0].provenance["tcp_flags"] == "observed"


class TestTcpHandshake:
    """The three-way handshake."""

    @pytest.fixture
    def parser(self):
        return PcapParser()

    def test_a_three_way_handshake_is_recognised(self, parser):
        """SYN, then SYN+ACK, then ACK is a complete handshake."""
        result = parser.parse(build_pcap(handshake_frames()), "hs.pcap")
        assert result.parsed is True
        assert len(result.handshakes) == 1
        handshake = result.handshakes[0]
        assert handshake.stages == ["SYN", "SYN-ACK", "ACK"]
        assert handshake.complete is True
        assert handshake.client == "10.0.0.1:12345"
        assert handshake.server == "10.0.0.2:80"

    def test_the_handshake_is_marked_as_inferred(self, parser):
        """A handshake is a pattern across packets, so it is inferred."""
        result = parser.parse(build_pcap(handshake_frames()), "hs.pcap")
        assert result.handshakes[0].provenance == "inferred"

    def test_each_packet_records_its_handshake_stage(self, parser):
        """The packets themselves are labelled with the stage they took."""
        result = parser.parse(build_pcap(handshake_frames()), "hs.pcap")
        stages = [d.handshake_stage for d in result.packets]
        assert stages == ["SYN", "SYN-ACK", "ACK"]
        for detail in result.packets:
            assert detail.provenance["handshake_stage"] == "inferred"

    def test_a_syn_on_its_own_is_a_partial_handshake(self, parser):
        """A capture with only the opening SYN reports a partial handshake."""
        result = parser.parse(build_pcap([tcp_syn_frame()]), "syn.pcap")
        assert len(result.handshakes) == 1
        handshake = result.handshakes[0]
        assert handshake.stages == ["SYN"]
        assert handshake.complete is False

    def test_a_syn_and_ack_without_the_final_ack_is_partial(self, parser):
        """Missing the third packet leaves the handshake incomplete."""
        result = parser.parse(
            build_pcap([tcp_syn_frame(), tcp_syn_ack_frame()]), "partial.pcap"
        )
        handshake = result.handshakes[0]
        assert handshake.stages == ["SYN", "SYN-ACK"]
        assert handshake.complete is False

    def test_the_summary_counts_handshakes(self, parser):
        """The summary reports how many handshakes were seen."""
        result = parser.parse(build_pcap(handshake_frames()), "hs.pcap")
        assert result.summary.tcp_handshakes == 1
        assert result.summary.complete_tcp_handshakes == 1

    def test_a_capture_with_no_handshake_reports_none(self, parser):
        """Traffic that is not a handshake produces no handshake."""
        frame = build_ethernet(
            MAC_SERVER, MAC_CLIENT, ETHERTYPE_IPV4,
            build_ipv4("10.0.0.1", "10.0.0.2", IPPROTO_TCP,
                       build_tcp(12345, 80, TCP_PSH | TCP_ACK)),
        )
        result = parser.parse(build_pcap([frame]), "data.pcap")
        assert result.handshakes == []


class TestIcmpTypes:
    """ICMP types and codes."""

    @pytest.fixture
    def parser(self):
        return PcapParser()

    def _icmp_frame(self, src_ip, dst_ip, payload):
        return build_ethernet(
            MAC_SERVER, MAC_CLIENT, ETHERTYPE_IPV4,
            build_ipv4(src_ip, dst_ip, IPPROTO_ICMP, payload),
        )

    def test_an_echo_request_is_distinguished_from_a_reply(self, parser):
        """Type 8 is a request and type 0 is a reply."""
        frames = [
            self._icmp_frame("10.0.0.1", "10.0.0.2", build_icmp(8, 0)),
            self._icmp_frame("10.0.0.2", "10.0.0.1", build_icmp(0, 0)),
        ]
        result = parser.parse(build_pcap(frames), "icmp.pcap")
        assert result.packets[0].icmp_type == 8
        assert result.packets[0].icmp_type_name == "echo-request"
        assert result.packets[1].icmp_type == 0
        assert result.packets[1].icmp_type_name == "echo-reply"

    def test_an_unreachable_message_reports_its_code(self, parser):
        """A destination-unreachable carries the reason in its code."""
        frame = self._icmp_frame("10.0.0.2", "10.0.0.1", build_icmp_unreachable(3))
        result = parser.parse(build_pcap([frame]), "unreach.pcap")
        detail = result.packets[0]
        assert detail.icmp_type == 3
        assert detail.icmp_type_name == "destination-unreachable"
        assert detail.icmp_code == 3
        assert detail.icmp_code_name == "port-unreachable"

    def test_an_unknown_icmp_type_is_named_without_guessing(self, parser):
        """An unrecognised type is reported as its number, not a guess."""
        frame = self._icmp_frame("10.0.0.1", "10.0.0.2", build_icmp(200, 0))
        result = parser.parse(build_pcap([frame]), "odd.pcap")
        assert result.packets[0].icmp_type == 200
        assert result.packets[0].icmp_type_name == "icmp-type-200"

    def test_icmp_types_are_marked_as_observed(self, parser):
        """The type and code are read straight out of the packet."""
        frame = self._icmp_frame("10.0.0.1", "10.0.0.2", build_icmp(8, 0))
        result = parser.parse(build_pcap([frame]), "icmp.pcap")
        detail = result.packets[0]
        assert detail.provenance["icmp_type"] == "observed"
        assert detail.provenance["icmp_code"] == "observed"


class TestDns:
    """DNS names and addresses."""

    @pytest.fixture
    def parser(self):
        return PcapParser()

    def _dns_frame(self, src_ip, dst_ip, src_port, dst_port, message):
        return build_ethernet(
            MAC_SERVER, MAC_CLIENT, ETHERTYPE_IPV4,
            build_ipv4(src_ip, dst_ip, IPPROTO_UDP,
                       build_udp(src_port, dst_port, message)),
        )

    def test_a_query_yields_the_name(self, parser):
        """A DNS query on port 53 gives up the name it is asking for."""
        frame = self._dns_frame(
            "10.0.0.1", "10.0.0.2", 53000, 53,
            build_dns_query(0x1234, "www.example.com"),
        )
        result = parser.parse(build_pcap([frame]), "query.pcap")
        detail = result.packets[0]
        assert detail.dns_query_name == "www.example.com"
        assert detail.dns_is_response is False
        assert detail.dns_answers == []

    def test_a_response_yields_the_name_and_the_addresses(self, parser):
        """A DNS response gives up the name and the address it points at."""
        frame = self._dns_frame(
            "10.0.0.2", "10.0.0.1", 53, 53000,
            build_dns_response(0x1234, "www.example.com", "93.184.216.34"),
        )
        result = parser.parse(build_pcap([frame]), "response.pcap")
        detail = result.packets[0]
        assert detail.dns_query_name == "www.example.com"
        assert detail.dns_is_response is True
        assert detail.dns_answers == ["93.184.216.34"]

    def test_a_multi_label_name_is_read_in_full(self, parser):
        """Every label of a name is read, not just the first."""
        frame = self._dns_frame(
            "10.0.0.1", "10.0.0.2", 53000, 53,
            build_dns_query(1, "a.b.c.example.org"),
        )
        result = parser.parse(build_pcap([frame]), "multi.pcap")
        assert result.packets[0].dns_query_name == "a.b.c.example.org"

    def test_a_dns_name_is_marked_as_inferred(self, parser):
        """A name is decoded from labels, so it is inferred, not observed."""
        frame = self._dns_frame(
            "10.0.0.1", "10.0.0.2", 53000, 53,
            build_dns_query(1, "www.example.com"),
        )
        result = parser.parse(build_pcap([frame]), "query.pcap")
        assert result.packets[0].provenance["dns_query_name"] == "inferred"

    def test_a_dns_packet_that_cannot_be_parsed_says_so(self, parser):
        """A truncated DNS message is reported, not guessed at."""
        truncated = build_dns_query(1, "www.example.com")[:8]
        frame = self._dns_frame("10.0.0.1", "10.0.0.2", 53000, 53, truncated)
        result = parser.parse(build_pcap([frame]), "broken.pcap")
        detail = result.packets[0]
        assert detail.dns_query_name is None
        assert detail.notes, "a DNS packet that could not be parsed must carry a reason"
        assert any("DNS" in note for note in detail.notes)

    def test_a_dns_message_on_a_bad_port_is_not_treated_as_dns(self, parser):
        """Only traffic on port 53 is read as DNS."""
        frame = self._dns_frame(
            "10.0.0.1", "10.0.0.2", 5000, 6000,
            build_dns_query(1, "www.example.com"),
        )
        result = parser.parse(build_pcap([frame]), "notdns.pcap")
        assert result.packets[0].dns_query_name is None

    def test_dns_over_tcp_is_reported_rather_than_decoded(self, parser):
        """DNS over TCP carries a length prefix, so it is flagged."""
        frame = build_ethernet(
            MAC_SERVER, MAC_CLIENT, ETHERTYPE_IPV4,
            build_ipv4("10.0.0.1", "10.0.0.2", IPPROTO_TCP,
                       build_tcp(53000, 53, TCP_ACK | TCP_PSH,
                                 payload=build_dns_query(1, "www.example.com"))),
        )
        result = parser.parse(build_pcap([frame]), "dnstcp.pcap")
        detail = result.packets[0]
        assert detail.src_port == 53000
        assert detail.dst_port == 53
        assert any("DNS over TCP" in note for note in detail.notes)
        assert detail.dns_query_name is None

    def test_the_summary_counts_dns_queries_and_responses(self, parser):
        """The summary separates queries from responses."""
        frames = [
            self._dns_frame("10.0.0.1", "10.0.0.2", 53000, 53,
                            build_dns_query(1, "www.example.com")),
            self._dns_frame("10.0.0.2", "10.0.0.1", 53, 53000,
                            build_dns_response(1, "www.example.com", "93.184.216.34")),
        ]
        result = parser.parse(build_pcap(frames), "dns.pcap")
        assert result.summary.dns_queries == 1
        assert result.summary.dns_responses == 1


class TestArp:
    """ARP hardware addresses."""

    @pytest.fixture
    def parser(self):
        return PcapParser()

    def test_an_arp_request_yields_the_hardware_addresses(self, parser):
        """The sender and target hardware addresses are read."""
        frame = build_ethernet(
            BROADCAST_MAC, MAC_CLIENT, ETHERTYPE_ARP,
            build_arp_request(MAC_ARP_SENDER, "10.0.0.1",
                              MAC_ARP_TARGET, "10.0.0.2"),
        )
        result = parser.parse(build_pcap([frame]), "arp.pcap")
        detail = result.packets[0]
        assert detail.protocol == "arp"
        assert detail.arp_operation == 1
        assert detail.arp_operation_name == "request"
        assert detail.arp_sender_mac == "aa:bb:cc:dd:ee:ff"
        assert detail.arp_target_mac == "11:22:33:44:55:66"
        assert detail.arp_sender_ip == "10.0.0.1"
        assert detail.arp_target_ip == "10.0.0.2"

    def test_an_arp_reply_is_named_as_a_reply(self, parser):
        """Operation 2 is a reply."""
        frame = build_ethernet(
            MAC_CLIENT, MAC_SERVER, ETHERTYPE_ARP,
            struct.pack(">HHBBH", 1, 0x0800, 6, 4, 2)
            + MAC_ARP_SENDER + socket.inet_aton("10.0.0.2")
            + MAC_CLIENT + socket.inet_aton("10.0.0.1"),
        )
        result = parser.parse(build_pcap([frame]), "arp-reply.pcap")
        assert result.packets[0].arp_operation_name == "reply"

    def test_arp_addresses_are_marked_as_observed(self, parser):
        """The hardware addresses are read straight out of the packet."""
        frame = build_ethernet(
            BROADCAST_MAC, MAC_CLIENT, ETHERTYPE_ARP,
            build_arp_request(MAC_ARP_SENDER, "10.0.0.1",
                              MAC_ARP_TARGET, "10.0.0.2"),
        )
        result = parser.parse(build_pcap([frame]), "arp.pcap")
        detail = result.packets[0]
        assert detail.provenance["arp_sender_mac"] == "observed"
        assert detail.provenance["arp_target_mac"] == "observed"

    def test_a_truncated_arp_packet_is_counted_with_a_reason(self, parser):
        """An ARP packet cut short is still counted, and says why."""
        frame = build_ethernet(
            BROADCAST_MAC, MAC_CLIENT, ETHERTYPE_ARP, b"\x00\x01\x00\x08"
        )
        result = parser.parse(build_pcap([frame]), "short-arp.pcap")
        assert result.parsed is True
        assert result.summary.total_packets == 1
        detail = result.packets[0]
        assert detail.parsed is False
        assert any("ARP" in note for note in detail.notes)
        assert result.summary.unparsed_packets == 1


class TestUnparseablePackets:
    """A packet that cannot be read further is still counted, with a reason."""

    @pytest.fixture
    def parser(self):
        return PcapParser()

    def test_a_frame_shorter_than_an_ethernet_header_is_counted(self, parser):
        """A runt frame is counted, and the reason is recorded."""
        result = parser.parse(build_pcap([b"\x00" * 10]), "runt.pcap")
        assert result.parsed is True
        assert result.summary.total_packets == 1
        detail = result.packets[0]
        assert detail.parsed is False
        assert detail.notes
        assert "Ethernet" in detail.notes[0]

    def test_a_truncated_tcp_header_is_counted_with_a_reason(self, parser):
        """A TCP header cut short is counted, and the reason is recorded."""
        frame = build_ethernet(
            MAC_SERVER, MAC_CLIENT, ETHERTYPE_IPV4,
            build_ipv4("10.0.0.1", "10.0.0.2", IPPROTO_TCP, b"\x00" * 10),
        )
        result = parser.parse(build_pcap([frame]), "short-tcp.pcap")
        assert result.parsed is True
        assert result.summary.total_packets == 1
        detail = result.packets[0]
        assert detail.parsed is False
        assert any("TCP" in note for note in detail.notes)
        assert result.summary.unparsed_packets == 1

    def test_an_unreadable_packet_does_not_stop_the_others(self, parser):
        """One bad packet does not hide the good ones."""
        frames = [
            b"\x00" * 10,
            tcp_syn_frame(),
        ]
        result = parser.parse(build_pcap(frames), "mixed.pcap")
        assert result.parsed is True
        assert result.summary.total_packets == 2
        assert result.packets[0].parsed is False
        assert result.packets[1].parsed is True
        assert result.packets[1].src_port == 12345

    def test_the_summary_counts_unparsed_packets(self, parser):
        """The summary says how many packets could not be read."""
        frames = [b"\x00" * 10, tcp_syn_frame(), tcp_syn_ack_frame()]
        result = parser.parse(build_pcap(frames), "mixed.pcap")
        assert result.summary.unparsed_packets == 1


class TestPcapng:
    """PCAPNG parsing."""

    @pytest.fixture
    def parser(self):
        return PcapParser()

    def test_a_pcapng_file_is_parsed(self, parser):
        """A PCAPNG file with a section, an interface and packets is read."""
        data = build_pcapng(handshake_frames())
        result = parser.parse(data, "capture.pcapng")
        assert result.parsed is True, result.error
        assert result.error is None
        assert result.format == "pcapng"
        assert result.summary.total_packets == 3
        assert result.summary.protocols == {"tcp": 3}
        assert result.summary.link_type == 1

    def test_the_packets_in_a_pcapng_file_are_read_to_the_same_depth(self, parser):
        """A PCAPNG packet gives up its ports and flags like any other."""
        result = parser.parse(build_pcapng(handshake_frames()), "capture.pcapng")
        assert result.packets[0].src_port == 12345
        assert result.packets[0].tcp_flags == ["SYN"]
        assert len(result.handshakes) == 1
        assert result.handshakes[0].complete is True

    def test_a_big_endian_pcapng_file_is_parsed(self, parser):
        """The byte-order magic in the section header decides the order."""
        data = build_pcapng(handshake_frames(), endian=">")
        result = parser.parse(data, "capture.pcapng")
        assert result.parsed is True, result.error
        assert result.summary.total_packets == 3
        assert result.packets[0].src_port == 12345

    def test_a_nanosecond_resolution_pcapng_file_is_parsed(self, parser):
        """A file that says its timestamps are nanoseconds is read."""
        data = build_pcapng(handshake_frames(), ts_resolution=9)
        result = parser.parse(data, "capture.pcapng")
        assert result.parsed is True, result.error
        assert result.summary.total_packets == 3
        # The builder spaces the packets 1000 units apart. At nanosecond
        # resolution that is one microsecond, so the timestamps must be a
        # microsecond apart. Read as microseconds they would have been a
        # millisecond apart, so this is what shows the resolution was used.
        stamps = [detail.timestamp for detail in result.packets]
        assert stamps[0] == "2023-11-14T22:13:20+00:00"
        assert stamps[1] == "2023-11-14T22:13:20.000001+00:00"
        assert stamps[2] == "2023-11-14T22:13:20.000002+00:00"

    def test_a_microsecond_resolution_pcapng_file_is_parsed(self, parser):
        """The same file at microsecond resolution spans milliseconds."""
        data = build_pcapng(handshake_frames(), ts_resolution=6)
        result = parser.parse(data, "capture.pcapng")
        assert result.parsed is True, result.error
        assert result.summary.duration_seconds == 0.002

    def test_a_pcapng_file_with_a_broken_byte_order_magic_is_not_guessed(self, parser):
        """A file whose byte-order magic is wrong is reported, not guessed."""
        data = bytearray(build_pcapng(handshake_frames()))
        data[8:12] = b"\x00\x00\x00\x00"
        result = parser.parse(bytes(data), "broken.pcapng")
        assert result.parsed is False
        assert result.format == "pcapng"
        assert "not yet supported" in result.error
        assert "byte-order magic" in result.error

    def test_a_pcapng_file_with_a_bad_block_length_is_reported(self, parser):
        """A block whose length is impossible is reported, not guessed."""
        data = bytearray(build_pcapng(handshake_frames()))
        # The interface description block starts at offset 28; its length
        # field is the next four bytes. A length that is not a multiple of
        # four cannot describe a PCAPNG block.
        data[32:36] = struct.pack("<I", 13)
        result = parser.parse(bytes(data), "badlen.pcapng")
        assert result.parsed is False
        assert result.format == "pcapng"
        assert "not yet supported" in result.error
        assert "invalid block length" in result.error

    def test_a_file_that_does_not_start_with_the_pcapng_magic_is_not_called_pcapng(self, parser):
        """A file without the PCAPNG magic is reported as an unknown format."""
        data = build_pcapng(handshake_frames())
        # Drop the section header block, so the file no longer starts with
        # the PCAPNG magic.
        result = parser.parse(data[28:], "nosection.pcapng")
        assert result.parsed is False
        assert result.format == "unknown"
        assert "Unknown PCAP magic" in result.error

    def test_a_truncated_pcapng_file_is_reported(self, parser):
        """A PCAPNG file cut short is reported."""
        data = build_pcapng(handshake_frames())
        result = parser.parse(data[:len(data) - 20], "cut.pcapng")
        assert result.parsed is False
        assert result.format == "pcapng"
        assert "not yet supported" in result.error


class TestByteOrderAcrossFormats:
    """The capture file's byte order never changes the packet bytes."""

    @pytest.fixture
    def parser(self):
        return PcapParser()

    def test_a_big_endian_capture_reads_the_same_ports_and_flags(self, parser):
        """A big-endian file yields the same detail as a little-endian one."""
        little = parser.parse(build_pcap(handshake_frames(), endian="<"), "le.pcap")
        big = parser.parse(build_pcap(handshake_frames(), endian=">"), "be.pcap")

        assert little.parsed is True
        assert big.parsed is True
        assert big.summary.total_packets == little.summary.total_packets
        assert big.packets[0].src_port == little.packets[0].src_port
        assert big.packets[0].dst_port == little.packets[0].dst_port
        assert big.packets[0].tcp_flags == little.packets[0].tcp_flags
        assert big.handshakes[0].stages == little.handshakes[0].stages

    def test_a_nanosecond_capture_reads_the_same_detail(self, parser):
        """The nanosecond magic variant is only a different resolution."""
        micro = parser.parse(build_pcap(handshake_frames(), endian="<"), "us.pcap")
        nano = parser.parse(
            build_pcap(handshake_frames(), endian="<", nanoseconds=True), "ns.pcap"
        )
        assert nano.parsed is True
        assert nano.packets[0].src_port == micro.packets[0].src_port
        assert nano.packets[0].tcp_flags == micro.packets[0].tcp_flags


class TestTcpdumpAgreement:
    """
    Check this parser against tcpdump, which is an independent implementation.

    These tests are the reason the capture files in this module can be
    trusted: the same bytes are read by both, and both must say the same
    thing. They are skipped when tcpdump is not installed.
    """

    @pytest.fixture(autouse=True)
    def require_tcpdump(self):
        if shutil.which("tcpdump") is None:
            pytest.skip("tcpdump is not installed")

    def _read_with_tcpdump(self, data, tmp_path):
        path = tmp_path / "capture.pcap"
        path.write_bytes(data)
        result = subprocess.run(
            ["tcpdump", "-r", str(path), "-nn", "-v"],
            capture_output=True, text=True, timeout=30,
        )
        return result.stdout + result.stderr

    def test_tcpdump_reads_the_same_ports_and_flags(self, tmp_path):
        """tcpdump sees the same handshake this parser reports."""
        data = build_pcap(handshake_frames())
        output = self._read_with_tcpdump(data, tmp_path)
        assert "10.0.0.1.12345 > 10.0.0.2.80" in output
        assert "Flags [S]" in output
        assert "Flags [S.]" in output
        assert "Flags [.]" in output

    def test_tcpdump_reads_the_same_dns_name(self, tmp_path):
        """tcpdump decodes the same DNS name this parser reports."""
        frame = build_ethernet(
            MAC_SERVER, MAC_CLIENT, ETHERTYPE_IPV4,
            build_ipv4("10.0.0.1", "10.0.0.2", IPPROTO_UDP,
                       build_udp(53000, 53,
                                 build_dns_query(0x1234, "www.example.com"))),
        )
        output = self._read_with_tcpdump(build_pcap([frame]), tmp_path)
        assert "www.example.com" in output

    def test_tcpdump_reads_the_same_arp_addresses(self, tmp_path):
        """tcpdump sees the same ARP request this parser reports."""
        frame = build_ethernet(
            BROADCAST_MAC, MAC_CLIENT, ETHERTYPE_ARP,
            build_arp_request(MAC_ARP_SENDER, "10.0.0.1",
                              MAC_ARP_TARGET, "10.0.0.2"),
        )
        output = self._read_with_tcpdump(build_pcap([frame]), tmp_path)
        # tcpdump writes the target hardware address in brackets when it is
        # not all zeroes, so the two halves are checked separately.
        assert "Request who-has 10.0.0.2" in output
        assert "tell 10.0.0.1" in output
        assert "11:22:33:44:55:66" in output

    def test_tcpdump_reads_the_same_icmp_types(self, tmp_path):
        """tcpdump tells the echo request and the echo reply apart."""
        frames = [
            build_ethernet(
                MAC_SERVER, MAC_CLIENT, ETHERTYPE_IPV4,
                build_ipv4("10.0.0.1", "10.0.0.2", IPPROTO_ICMP, build_icmp(8, 0)),
            ),
            build_ethernet(
                MAC_CLIENT, MAC_SERVER, ETHERTYPE_IPV4,
                build_ipv4("10.0.0.2", "10.0.0.1", IPPROTO_ICMP, build_icmp(0, 0)),
            ),
        ]
        output = self._read_with_tcpdump(build_pcap(frames), tmp_path)
        assert "ICMP echo request" in output
        assert "ICMP echo reply" in output

    def test_tcpdump_reads_the_pcapng_file(self, tmp_path):
        """tcpdump reads the PCAPNG file this parser reads."""
        data = build_pcapng(handshake_frames())
        path = tmp_path / "capture.pcapng"
        path.write_bytes(data)
        result = subprocess.run(
            ["tcpdump", "-r", str(path), "-nn", "-v"],
            capture_output=True, text=True, timeout=30,
        )
        output = result.stdout + result.stderr
        assert "Flags [S]" in output
        assert "Flags [S.]" in output
        assert "Flags [.]" in output

    def test_tcpdump_reads_the_big_endian_capture(self, tmp_path):
        """tcpdump reads a big-endian capture written the same way."""
        data = build_pcap(handshake_frames(), endian=">")
        output = self._read_with_tcpdump(data, tmp_path)
        assert "10.0.0.1.12345 > 10.0.0.2.80" in output
        assert "Flags [S]" in output


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
