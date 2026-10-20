# RouteLens Lite — Real Network Capability Audit

**Date**: 2026-10-20T04:30:00Z  
**Auditor**: Engineering Manager  
**Scope**: Assessment of current project vs. real network diagnostics vision

---

## Executive Summary

The current RouteLens Lite project provides:
- ✅ **Simulated routing decisions** (RouteCore) — longest-prefix match on static sample table
- ✅ **Virtual packet lab** (PacketLab) — real ICMP ping through isolated Linux namespaces
- ❌ **Real local network collection** — no actual `ip addr`, `ip route`, `ip neigh` collection
- ❌ **Real diagnostics** — no DNS, connectivity, traceroute from user's laptop
- ❌ **Evidence-based topology** — no OBSERVED/INFERRED/SIMULATED distinction

The project is a **routing algorithm demonstrator + virtual lab**, not a network diagnostics tool.

---

## Current Capabilities vs. Vision

| Vision Item | Current State | Gap Analysis |
|-------------|---------------|--------------|
| **1. Real local interface/IP collection** | ❌ Missing | No `ip addr show` parsing endpoint |
| **2. Real routing table collection** | ❌ Missing | Only static `SAMPLE_ROUTES` (5 entries) |
| **3. ARP/IPv6 neighbor info** | ❌ Missing | No `ip neigh show` endpoint |
| **4. DNS resolution & connectivity** | ❌ Missing | No DNS/ping/tcp connect endpoints |
| **5. Traceroute with L3 hops** | ❌ Missing | No traceroute implementation |
| **6. Authorized subnet discovery** | ❌ Missing | No host discovery, no scope validation |
| **7. Interactive evidence-based topology** | ❌ Missing | Only virtual lab topology, no real evidence |
| **8. PCAP import/analysis** | ❌ Missing | No PCAP support |
| **9. Managed equipment integration** | ❌ Missing | No SNMP/NETCONF/REST clients |
| **10. Exportable reports with evidence** | ❌ Missing | No export, no evidence tracking |
| **11. Automated tests & verification** | ✅ Partial | 78 backend tests (mocked), no real integration tests |

---

## What Currently Exists (Must Preserve)

### RouteCore — Routing Algorithm Engine
```
GET /routes          → 5 static sample routes
GET /lookup?dest=X   → Longest-prefix match with explanation
Response: {matched, route, explanation, transmitted: false}
```
- **Strength**: Correct algorithm, 41 tests, clear separation (`transmitted: false`)
- **Limitation**: Static sample data, no real system routing table

### PacketLab — Virtual Router Lab
```
GET /api/lab/status           → Lab readiness (namespaces, tools, topology)
POST /api/lab/simulate        → Real ping + tcpdump in rl260-* namespaces
```
- **Strength**: Real packet transmission, capture verification, state machine
- **Limitation**: Fixed topology (192.168.10.0/24, 192.168.20.0/24), no topology validation, pkexec blocks web requests

### JourneyUI — Frontend
- React + TypeScript + Vite
- PacketJourney component with real backend integration
- Topology mismatch warning (RouteCore vs Lab networks)
- Lab status banner, error handling, simulation controls

---

## Real Network Data Sources Available on Linux

| Data | Command | Parsing Complexity | Privileges |
|------|---------|-------------------|------------|
| Interfaces & IPs | `ip -j addr show` | Low (JSON output) | None |
| Routing table | `ip -j route show` | Low (JSON output) | None |
| ARP/IPv6 neighbors | `ip -j neigh show` | Low (JSON output) | None |
| DNS resolution | `getent hosts` / `dig +short` | Low | None |
| ICMP ping | `ping -c 3 -W 2 <host>` | Medium | None |
| TCP connect | `nc -z -w 2 <host> <port>` | Low | None |
| Traceroute | `traceroute -n -w 2 -q 1 <host>` | Medium | None (UDP/ICMP) |
| Packet capture | `tcpdump -i <iface> -c 10` | High | **Requires root/capabilities** |

**Key Finding**: Most read-only collection requires **no privileges**. Only packet capture needs elevation.

---

## Safety Assessment of Real Collection

| Operation | Risk | Mitigation |
|-----------|------|------------|
| `ip addr/route/neigh show` | None | Read-only, no privileges |
| `getent hosts` / `dig` | None | Read-only |
| `ping -c 3` | Low (ICMP echo) | Rate limit: max 3 packets, 2s timeout |
| `nc -z` / TCP connect | Low | Rate limit: max 1 attempt, 2s timeout |
| `traceroute` | Low | Max 30 hops, per-hop timeout, no payload |
| `tcpdump` | **High** | **Never auto-run** — require explicit user action, show exact command |

---

## Implementation Feasibility

### Phase 1: Read-Only Collection (Week 1-2)
**Effort**: Low-Medium  
**Risk**: None  
**Approach**: 
- Add `network_collector.py` with async subprocess wrappers
- Use `ip -j` JSON output for reliable parsing
- Expose REST endpoints under `/network/*`
- Frontend: New "Network Diagnostics" tab

### Phase 2: Active Diagnostics (Week 2-3)
**Effort**: Medium  
**Risk**: Low (with rate limits)  
**Approach**:
- DNS: `asyncio.getaddrinfo()` or `dig` subprocess
- Ping: `ping -c 3 -W 2` with asyncio subprocess
- TCP: `asyncio.open_connection()` with timeout
- Traceroute: `traceroute -n -w 2 -q 1` or raw socket implementation
- All with configurable timeouts, cancellation, rate limits

### Phase 3: Evidence-Based Topology (Week 3-4)
**Effort**: Medium-High  
**Risk**: Medium (complexity)  
**Approach**:
- Evidence model: `{source, timestamp, method, data, label}`
- Labels: OBSERVED (direct), INFERRED (derived), SIMULATED (lab), UNKNOWN
- Build graph from: interfaces → routes → neighbors → DNS → traceroute hops
- Frontend: Cytoscape.js or React Flow interactive graph

### Phase 4: PCAP & Equipment (Future)
**Effort**: High  
**Risk**: High (privileges, protocols)  
**Approach**:
- PCAP: Drag-drop upload, parse with `pyshark`/`scapy`, show in timeline
- Equipment: Read-only SNMP/NETCONF clients, explicit credential entry, scope validation

---

## Evidence Labeling Requirements

Every topology claim must carry:

```typescript
interface Evidence {
  source: string;           // e.g., "ip route show", "traceroute", "packet-lab"
  timestamp: string;        // ISO 8601
  method: string;           // "direct_command", "derived", "simulated"
  data: any;                // Raw or processed data
  label: 'OBSERVED' | 'INFERRED' | 'SIMULATED' | 'UNKNOWN';
  limitations?: string[];   // e.g., ["single vantage point", "ICMP only"]
}
```

**Examples**:
- `ip route show` → `OBSERVED` (direct command output)
- Traceroute hop → `OBSERVED` (responding L3 hop), not "physical router"
- RouteCore decision → `SIMULATED` (algorithm on static table)
- PacketLab capture → `SIMULATED` (virtual lab, not production network)
- ARP entry for gateway → `INFERRED` (neighbor exists, link assumed)

---

## Required Documentation Updates

1. **`docs/real-network-audit.md`** — This document
2. **`docs/lab-setup.md`** — Namespace creation, sudoers rules, verification
3. **`docs/api-reference.md`** — All endpoints with request/response examples
4. **`docs/evidence-model.md`** — Evidence types, labels, limitations
5. **`docs/safety-guidelines.md`** — Rate limits, scope validation, privilege rules

---

## Test Strategy for Real Collection

| Test Type | Approach |
|-----------|----------|
| Unit (parsing) | Mock `ip -j` JSON output, test parsing functions |
| Unit (errors) | Mock missing commands, timeouts, malformed output |
| Integration | Run against real system (CI: mock; Local: real) |
| Safety | Verify no write commands, no privilege escalation |
| Contract | OpenAPI schema matches TypeScript types |

---

## Limitations to Document Honestly

1. **Single vantage point** — Laptop sees only its local network
2. **No campus visibility** — Cannot discover VLANs, switches beyond gateway
3. **ICMP/TCP only** — No UDP service discovery, no passive monitoring
4. **Traceroute ≠ physical path** — Responding L3 hops only
5. **ARP/NDP only local segment** — No cross-subnet neighbor discovery
6. **No wireless analysis** — No 802.11 frame capture/analysis
7. **Virtual lab isolated** — rl260-* namespaces unrelated to host network

---

## Next Steps Priority

1. **Fix PacketLab critical issues** (topology validation, pkexec, unused params)
2. **Fix frontend 408 handling** and add `transmitted` field
3. **Implement Phase 1 read-only collection** (`/network/interfaces`, `/network/routes`, `/network/neighbors`)
4. **Add frontend Network Diagnostics tab**
5. **Implement Phase 2 active diagnostics** (DNS, ping, TCP, traceroute)
6. **Build evidence-based topology model and graph**
7. **Document all limitations honestly**

---

## Audit Complete

**Status**: Baseline established, gaps identified, implementation roadmap defined  
**Next**: Proceed with Phase 1 fixes (PacketLab + JourneyUI) before new features