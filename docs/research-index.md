# RouteLens Research Index

**Purpose**: Centralized index of completed research, open questions, and evidence-backed conclusions.

**Last Updated**: 2026-10-20T11:30:00Z

---

## Detailed Research Documents

- [Detailed Research: DNS, Traceroute & Connectivity](research/detailed-research.md) — Comprehensive implementation guides, decision records, verification tests, and references for RQ-001 (DNS Resolution), RQ-002 (Traceroute), and RQ-006 (Connectivity Checks).

---

## Research Categories

### 1. Linux Networking & System Calls
| Topic | Status | Sources | Conclusion |
|---|---|---|---|
| `ip -j` JSON output format stability | ✅ Resolved | `man ip`, kernel source | Stable since kernel 3.6; use `-j` flag for machine-readable output |
| `ip netns exec` privilege requirements | ✅ Resolved | `man ip-netns`, testing | Requires `CAP_SYS_ADMIN` or root; `pkexec`/`sudo -n` for non-interactive |
| ARP/neighbor cache `state` field format | ✅ Resolved | `man ip-neighbour`, testing | Can be string or array of strings in `ip -j neigh show` |

### 2. DNS Resolution
| Topic | Status | Sources | Conclusion |
|---|---|---|---|
| `asyncio.getaddrinfo()` vs `dig` subprocess | ✅ **Resolved** | Python docs, aiohttp resolver, cpython source | **Recommendation: `asyncio.getaddrinfo()` with `asyncio.wait_for()` timeout**. Native async (Python 3.7+), runs in executor by default (thread pool). For true async, `aiodns` library available but adds dependency. `dig` subprocess works but adds tool dependency. aiohttp uses ThreadPoolExecutor pattern. |
| DNS timeout handling | ✅ **Resolved** | Python asyncio docs, superfastpython.com | Use `asyncio.wait_for(loop.getaddrinfo(...), timeout=seconds)` with configurable timeout. Handle `socket.gaierror` for NXDOMAIN/SERVFAIL/timeout. |
| IPv6 support in getaddrinfo | ✅ Resolved | Python socket docs | Use `socket.AF_INET6` or `socket.AF_UNSPEC` for dual-stack. |

### 3. Connectivity & Traceroute
| Topic | Status | Sources | Conclusion |
|---|---|---|---|
| ICMP ping from Python without root | ✅ **Resolved** | `man ping`, `getcap(1)`, kernel docs, testing | **Recommendation: `ping` subprocess**. Verified: `/usr/bin/ping` ships `cap_net_raw=ep`, so it runs unprivileged. All Python raw-socket libs (`aioping`, `asyncping3`, `aio_ping`) create `SOCK_RAW` and need root — verified `PermissionError: [Errno 13]`. Unprivileged in-process alternative is the ICMP *dgram* socket (`SOCK_DGRAM`+`IPPROTO_ICMP`, Linux 3.0+/3.11+), but only if the user's GID is in `net.ipv4.ping_group_range` (this host: `1 0` = disabled). |
| TCP connect for port reachability | ✅ Resolved | Python asyncio docs | `asyncio.open_connection()` with timeout - no root needed |
| Traceroute implementation options | ✅ **Resolved** | `man traceroute`, ipscout, mtrpacket, scapy | **Recommendation: `traceroute` subprocess with bounded hops/timeout**. Raw ICMP sockets need root/CAP_NET_RAW. `ipscout` claims unprivileged on Linux via IP_RECVERR but macOS unsupported. `mtrpacket` needs raw sockets. `scapy` needs root. `traceroute -n -w 2 -q 1` subprocess is simplest, works unprivileged, bounded by `-m max_hops`. |

### 4. Frontend Visualization
| Topic | Status | Sources | Conclusion |
|---|---|---|---|
| Cytoscape.js vs React Flow | 🔄 In Progress | GitHub repos, npm | React Flow more React-native; Cytoscape.js more features |
| WebSocket vs polling for live updates | ✅ Resolved | MDN WebSocket API | WebSocket for real-time; polling simpler for periodic |

### 5. Network Discovery & Security
| Topic | Status | Sources | Conclusion |
|---|---|---|---|
| ARP scan scope limitations | ✅ Resolved | RFC 826, Linux `arp-scan` | Single broadcast domain only; no cross-subnet |
| Passive vs active discovery | ✅ Resolved | Network monitoring best practices | Default to passive; active requires explicit authorization |
| Rate limiting for discovery | ✅ Resolved | Network scanning ethics | Conservative: 1 packet/host/2s, max 50 concurrent |

---

## Open Research Questions

| ID | Question | Priority | Assigned To | Target Date | Status |
|---|---|---|---|---|---|
| RQ-001 | Best async DNS resolution approach for Python 3.12? | High | Lead Engineer | 2026-10-21 | ✅ **Resolved** - Use `asyncio.getaddrinfo()` with `asyncio.wait_for()` timeout |
| RQ-002 | Traceroute: subprocess vs raw socket tradeoffs? | High | Lead Engineer | 2026-10-21 | ✅ **Resolved** - Use `traceroute` subprocess with bounded hops/timeout |
| RQ-003 | React Flow vs Cytoscape.js for topology graph? | Medium | Research Specialist | 2026-10-22 | 🔄 In Progress |
| RQ-004 | Safe ARP neighbor discovery without root? | Medium | Research Specialist | 2026-10-22 | 🔄 In Progress |
| RQ-005 | WebSocket vs Server-Sent Events for live topology? | Low | Research Specialist | 2026-10-23 | ⏳ Pending |
| RQ-006 | Best async ICMP ping + TCP connect in Python 3.12 without root? | High | Research Specialist | 2026-10-21 | ✅ **Resolved** - Use `ping` subprocess (binary has `cap_net_raw=ep`) for ICMP + `asyncio.open_connection()` for TCP |

---

## Completed Research Decisions

| ID | Decision | Evidence | Date |
|---|---|---|---|
| RD-001 | Use `ip -j` JSON output for network collection | Kernel stable API since 3.6; structured parsing | 2026-10-20 |
| RD-002 | Use `asyncio.create_subprocess_exec` for system commands | Native async, proper timeout handling | 2026-10-20 |
| RD-003 | Restrict PacketLab to ICMP only; document unused params | tcp/udp need raw sockets or scapy (extra deps) | 2026-10-20 |
| RD-004 | Non-interactive privilege check before namespace ops | Prevents pkexec GUI hangs on web requests | 2026-10-20 |
| RD-005 | Tabbed UI for Network Diagnostics (All/Interfaces/Routes/Neighbors) | Progressive disclosure; matches data domains | 2026-10-20 |
| RD-006 | **DNS Resolution**: Use `asyncio.getaddrinfo()` with `asyncio.wait_for()` timeout | Native async (3.7+), runs in executor; `aiodns` for true async | 2026-10-20 |
| RD-007 | **Traceroute**: Use `traceroute` subprocess with `-m max_hops -w timeout -q 1` | Raw sockets need root; subprocess unprivileged, bounded, standard | 2026-10-20 |
| RD-008 | **ICMP ping**: Use `ping` subprocess (`-c count -i interval -W deadline`) | `/usr/bin/ping` has `cap_net_raw=ep` → unprivileged; raw-socket Python libs all need root; in-process ICMP dgram needs `ping_group_range` | 2026-10-20 |
| RD-009 | **TCP connect**: Use `asyncio.open_connection()` with `asyncio.wait_for()` | Standard TCP sockets, no privileges, ~20 ms latency, precise error types | 2026-10-20 |

---

## Research Methodology

1. **Primary Sources**: Official documentation (man pages, RFCs, Python docs, kernel docs)
2. **Secondary Sources**: GitHub issues, Stack Overflow (verified), technical blogs
3. **Verification**: Always test in project environment before concluding
4. **Documentation**: Record source URLs, version numbers, test commands, limitations
5. **Review**: Lead engineer validates before implementation

---

## Research Request Template

When requesting research, provide:
- **Precise Question**: One specific technical question
- **Context**: Why this matters for RouteLens
- **Acceptance Criteria**: What would constitute a complete answer
- **Constraints**: Time, dependencies, compatibility requirements
- **Proposed Verification**: How to test the conclusion
