# RouteLens Lite — End-to-End Test Plan

**Version**: 1.0  
**Date**: 2026-10-20  
**Status**: Draft — for review before execution

---

## 1. Purpose

This document describes the end-to-end test scenarios for RouteLens Lite, covering the complete user journey from frontend startup through backend API interactions to packet lab simulation. Tests are categorized by privilege requirements.

---

## 2. Prerequisites & Startup Sequence

### 2.1 Environment Requirements

| Component | Requirement |
|-----------|-------------|
| OS | Linux (tested on Ubuntu 22.04+) |
| Python | 3.11+ with venv |
| Node.js | 18+ with npm |
| Backend port | 8000 (default) |
| Frontend dev port | 5173 (Vite default) |
| Lab namespaces | `rl260-client`, `rl260-router`, `rl260-server` (for PacketLab) |

### 2.2 Startup Procedure

```bash
# Terminal 1: Backend
cd /home/abhaysawant/Desktop/cn_project_2/backend
source .venv/bin/activate
uvicorn app.main:app --port 8000 --reload

# Terminal 2: Frontend
cd /home/abhaysawant/Desktop/cn_project_2/frontend
npm run dev

# Terminal 3: Verify lab namespaces (for PacketLab tests)
ip netns list | grep rl260
```

### 2.3 Verification of Startup

| Check | Command | Expected |
|-------|---------|----------|
| Backend health | `curl http://localhost:8000/health` | `{"status":"ok","service":"RouteLens Lite API"}` |
| Frontend loads | Open http://localhost:5173 | Page renders without console errors |
| Lab status | `curl http://localhost:8000/api/lab/status` | `{"available":true,"state":"ready",...}` or `{"available":false,...}` |

---

## 3. Test Scenarios

### 3.1 Test Categories by Privilege Level

| Category | Tests | Privilege Required |
|----------|-------|-------------------|
| **Tier 0 — No privileges** | Frontend build, TypeScript check, unit tests, backend health, routing lookup, network collection (interfaces/routes/neighbors), DNS resolution, TCP connectivity | None |
| **Tier 1 — User privileges** | ICMP ping (via `ping` binary), traceroute via `tracepath` | Standard user (ping binary has `cap_net_raw=ep`) |
| **Tier 2 — Elevated privileges** | PacketLab simulation (requires `pkexec` for `ip netns exec`), `traceroute` with ICMP/TCP methods, ICMP dgram sockets | `pkexec`/`sudo`, `CAP_NET_RAW`, or `ping_group_range` config |

> **Note**: Tests are designed to run at Tier 0 by default. Tier 1 and 2 tests are marked `[PRIV]` and require specific environment setup.

---

### 3.2 Test Scenarios

#### TC-001: Frontend Startup & Backend Connectivity
| Step | Action | Expected |
|------|--------|----------|
| 1 | Open http://localhost:5173 | Frontend loads without JS errors |
| 2 | Check browser console | No errors, only warnings allowed |
| 3 | Network tab: `/health` request | Returns 200 with `{"status":"ok"}` |
| 3 | Network tab: `/routes` request | Returns 200 with sample routing table |
| 4 | Routing Table component renders | Table shows 5 sample routes |

**Pass Criteria**: All requests return 200, UI renders without errors.

---

#### TC-002: Lab Status Retrieval
| Step | Action | Expected |
|------|--------|----------|
| 1 | Navigate to Packet Journey section | Lab status banner visible |
| 2 | Click "Simulate Packet" (if available) | Status check triggered |
| 3 | Observe Lab Status component | Shows "Lab Ready" / "Lab Unavailable" / "Permission Denied" |

**Expected States**:
- `available: true` → "Lab Ready" badge, "Simulate Packet" enabled
- `available: false` → "Lab Unavailable" badge, reason shown, button disabled
- Network error → "Lab Unavailable" with error message

---

#### TC-003: Valid Packet Simulation (PacketLab)
**Prerequisites**: Lab namespaces exist, `pkexec` configured for `ip netns exec`

| Step | Action | Expected |
|------|--------|----------|
| 1 | Perform route lookup for `192.168.1.50` | Route matched: `192.168.1.0/25` |
| 2 | Click "Simulate Packet" button | Button shows "Simulating..." state |
| 3 | Wait for completion | Result shows `state: "completed"` |
| 4 | Verify response structure | `packet`, `verification_details`, `capture_verified: true` |
| 5 | Check Packet Details panel | Shows source/dest IP, protocol, TTL, forwarding info |

**Expected Response** (success):
```json
{
  "state": "completed",
  "message": "Packet transmitted and captured",
  "packet": {
    "source_ip": "192.168.10.2",
    "destination_ip": "192.168.20.2",
    "protocol": "icmp",
    "ttl": 63,
    "length": 84,
    "forwarding_info": {
      "ingress_interface": "rlr0c",
      "egress_interface": "rlr0s",
      "next_hop": "192.168.20.2",
      "route_matched": "192.168.20.0/24",
      "action": "forward"
    }
  },
  "capture_verified": true,
  "verification_details": {
    "ttl_decremented": true,
    "checksum_valid": true,
    "route_matched": true
  }
}
```

**Failure Modes to Test**:
| Scenario | Expected UI |
|----------|-------------|
| Lab unavailable (no namespaces) | `state: "unavailable"`, error message, button disabled |
| Permission denied (no pkexec) | `state: "error"`, "Permission denied" message |
| Capture timeout | `state: "timeout"`, "Capture timeout" message |

---

#### TC-004: Topology Mismatch Warning
| Step | Action | Expected |
|------|--------|----------|
| 1 | Perform route lookup for `192.168.1.50` | Route matches `192.168.1.0/25` |
| 2 | Observe Packet Journey section | Yellow warning banner visible |
| 3 | Read warning text | "Topology Mismatch: The routing table above uses sample networks (192.168.1.0/24, 10.0.0.0/8), but the virtual packet lab uses isolated networks (192.168.10.0/24 client↔router, 192.168.20.0/24 router↔server). The simulation below uses the LAB topology, NOT your routing decision." |

**Pass Criteria**: Warning is visible, clearly distinguishes RouteCore vs Lab networks.

---

#### TC-005: Invalid Request Handling
| Scenario | Input | Expected HTTP | UI Feedback |
|----------|-------|---------------|-------------|
| Invalid IP in lookup | `?destination=not-an-ip` | 400 | "Invalid IP address" |
| No route found | `?destination=10.99.99.99` | 404 | "No matching route found" |
| DNS resolve: invalid hostname | `{"hostname": ""}` | 400 | "Hostname is required" |
| DNS: NXDOMAIN | `{"hostname": "invalid.invalid"}` | 404 | "Hostname not found" |
| DNS: timeout | `{"hostname": "slow.invalid", "timeout": 0.001}` | 408 | "DNS resolution timed out" |
| Connectivity: missing target | `{}` | 400 | "Target is required" |
| Connectivity: TCP without port | `{"target":"google.com","protocol":"tcp"}` | 400 | "Port is required for TCP protocol" |
| Connectivity: invalid protocol | `{"target":"8.8.8.8","protocol":"udp"}` | 400 | "Protocol must be 'icmp' or 'tcp'" |
| Traceroute: missing target | `{}` | 400 | "Target is required" |

**UI Expectation**: Error banners appear inline with action, not as generic toasts. Retry button available for transient errors (408, 503).

---

#### TC-006: Backend Unavailable & Request Timeout
| Scenario | Setup | Expected UI |
|----------|-------|-------------|
| Backend down | Stop uvicorn | "Backend Disconnected" status badge, all API calls show "Backend unavailable" |
| Request timeout | Set timeout to 1ms for slow endpoint | "Request timed out" error, retry button shown |
| Lab unavailable | No namespaces or pkexec not configured | Lab status shows "Lab Unavailable", simulation button disabled |

---

#### TC-007: Loading, Success, Failure, Retry States
| Component | Loading | Success | Failure | Retry |
|-----------|---------|---------|---------|-------|
| Routing lookup | Spinner in form | Result card with route | Error banner | "Lookup Again" |
| Lab status | Spinner in badge | "Lab Ready" badge | "Lab Unavailable" badge | Auto-retry on tab focus |
| Packet simulate | "Simulating..." button | Result panels | Error banner | "Try Again" button |
| DNS resolve | "Resolving..." button | Result card with addresses | Error message | Re-submit form |
| Connectivity check | "Checking..." button | Result card | Error message | Re-submit |
| Traceroute | "Tracing..." button | Hop table | Error message | Re-submit |

---

#### TC-008: Network Diagnostics Tab (Tier 0)
| Tab | Test | Expected |
|-----|------|----------|
| **All** | Click "All" tab | All three sections show summaries |
| **Interfaces** | Click Interfaces tab | Table with Name, State, MTU, MAC, IPv4/IPv6, Flags |
| **Routes** | Click Routes tab | Table with Destination, Gateway, Interface, Protocol, Metric |
| **Neighbors** | Click Neighbors tab | Table with IP, Interface, MAC, State, Router flag |
| **Refresh** | Click Refresh button | Spinner → data reloads, timestamp updates |

---

#### TC-009: ConnectivityPanel (Autonomous Branch Only) — [PRIV for ICMP]
| Tab | Test | Expected |
|-----|------|----------|
| **DNS** | Resolve `google.com` with timeout 5s | Shows latency, IPv4 and IPv6 addresses |
| **DNS Error** | Resolve `invalid.invalid` | Error message "Hostname not found" |
| **Connectivity (ICMP)** | Ping `8.8.8.8` count=3 | Shows reachable, latency, packet stats |
| **Connectivity (TCP)** | Connect `google.com:443` | Shows reachable, latency |
| **Connectivity Error** | TCP to closed port | "Connection refused" |
| **Traceroute** | Trace `8.8.8.8` max_hops=5 | Hop table with TTL, address, RTT |
| **Traceroute Note** | Any trace | Note: "Only shows responding Layer 3 hops..." |

> **Note**: ConnectivityPanel exists only in `feature/autonomous-engineering` branch. Not in `main`.

---

#### TC-010: Routing Analysis Features (Preserved)
| Feature | Test | Expected |
|---------|------|----------|
| Routing Table | Load page | 5 sample routes displayed |
| Lookup | Enter `192.168.1.50` | Matches `192.168.1.0/25 via 10.0.0.2` |
| Lookup | Enter `10.99.99.99` | 404 "No matching route" |
| Visualization | After lookup | Diagram shows decision path |
| Transmitted flag | Any lookup result | `transmitted: false` in result |

---

### 3.3 API Contract Verification (TypeScript ↔ FastAPI)

| Endpoint | Request Type | Response Type | Status |
|----------|--------------|---------------|--------|
| `GET /health` | — | `{status, service}` | ✅ |
| `GET /routes` | — | `RoutingEntry[]` | ✅ |
| `GET /lookup` | `destination` (query) | `RouteLookupResult` | ✅ |
| `GET /api/lab/status` | — | `LabStatusResponse` | ✅ |
| `POST /api/lab/simulate` | `SimulateRequest` | `SimulateResponse` | ✅ |
| `GET /network/interfaces` | — | `InterfacesResult` | ✅ |
| `GET /network/routes` | — | `RoutesResult` | ✅ |
| `GET /network/neighbors` | — | `NeighborsResult` | ✅ |
| `POST /network/dns-resolve` | `DnsResolveRequest` | `DnsResolveResponse` | ⚠️ Type mismatch* |
| `POST /network/connectivity` | `ConnectivityCheckRequest` | `ConnectivityCheckResponse` | ⚠️ Type mismatch* |
| `POST /network/traceroute` | `TracerouteRequest` | `TracerouteResponse` | ⚠️ Type mismatch* |

> **Type Mismatches** (from autonomous branch):
> - DNS Response: Main has `addresses: list[dict]` with `type`/`ttl`; Frontend expects `ipv4_addresses[]` + `ipv6_addresses[]`
> - Connectivity Response: Main has `packets_sent`, `rtt_min/avg/max/mdev_ms`; Frontend expects only `reachable`, `latency_ms`, `error`
> - Traceroute Request: Main has `timeout_per_hop`, `probes_per_hop`, `overall_timeout`; Frontend has `max_hops`, `timeout`

---

## 4. Test Execution Matrix

| Test ID | Tier | Automated | Manual | Duration | Notes |
|---------|------|-----------|--------|----------|-------|
| TC-001 | 0 | ✅ (playwright) | ✅ | 2 min | Core smoke test |
| TC-002 | 0/1 | ✅ (playwright) | ✅ | 1 min | Depends on lab |
| TC-003 | 2 | ❌ | ✅ | 5 min | Requires pkexec + namespaces |
| TC-004 | 0 | ✅ (playwright) | ✅ | 30 sec | Visual check |
| TC-005 | 0 | ✅ (playwright) | ✅ | 5 min | API contract tests |
| TC-006 | 0/1 | ❌ | ✅ | 2 min | Requires backend restart |
| TC-007 | 0 | ✅ (playwright) | ✅ | 5 min | State machine testing |
| TC-008 | 0 | ✅ (playwright) | ✅ | 2 min | Read-only |
| TC-009 | 1/2 | ❌ | ✅ | 5 min | Autonomous branch only |
| TC-010 | 0 | ✅ (playwright) | ✅ | 2 min | Preserved features |

---

## 5. Evidence Collection & Reporting

### 5.1 Per-Test Evidence
For each test, collect:
- Screenshot of UI state (pass/fail)
- Backend logs (`backend/logs/` or console)
- Network tab HAR file (for API calls)
- Browser console logs

### 5.2 Test Report Template
```markdown
## Test Run: YYYY-MM-DD HH:MM

| Test ID | Result | Duration | Evidence | Notes |
|---------|--------|----------|----------|-------|
| TC-001  | PASS   | 45s      | screenshots/TC-001.png | |
| TC-003  | SKIP   | —        | —        | Lab namespaces not available |
```

---

## 6. Troubleshooting Guide

| Symptom | Likely Cause | Resolution |
|---------|--------------|------------|
| Frontend shows "Backend Disconnected" | Backend not running or wrong port | Start backend on port 8000 |
| CORS errors in console | Vite proxy misconfigured | Check `vite.config.ts` proxy config |
| "Lab Unavailable" always | Namespaces missing or no pkexec | Create namespaces, configure pkexec |
| "Simulation timed out" | Lab overloaded or network issue | Increase timeout, check lab health |
| TypeScript errors on build | Type mismatches | Update frontend types to match backend |
| `getcap /usr/bin/ping` shows no caps | Ping binary lacks capabilities | `sudo setcap cap_net_raw=ep /usr/bin/ping` |

---

## 6. Safety & Cleanup

### 6.1 Post-Test Cleanup
```bash
# Stop frontend
pkill -f "vite"

# Stop backend
pkill -f "uvicorn app.main:app"

# Verify no leftover processes
ps aux | grep -E "(uvicorn|vite)"
```

### 6.2 Lab Namespace Cleanup (if created for testing)
```bash
# Only if you created namespaces for testing
ip netns del rl260-client 2>/dev/null || true
ip netns del rl260-router 2>/dev/null || true
ip netns del rl260-server 2>/dev/null || true
```

> **Do not delete** the standard lab namespaces (`rl260-client`, `rl260-router`, `rl260-server`) unless you created them specifically for testing.

---

## 7. Limitations & Unverified Areas

| Area | Status | Notes |
|------|--------|-------|
| Full integration (frontend+backend+lab) | **Unverified** | Requires privileged environment |
| Packet capture verification | **Partial** | Depends on `tcpdump` access |
| Traceroute with ICMP/TCP methods | **Unverified** | Requires root/CAP_NET_RAW |
| Concurrent user testing | Not tested | Single-user design |
| Mobile/responsive layout | Partial | Tested at 768px, 1024px, 1920px |
| Accessibility (a11y) | Partial | ARIA labels present, not fully audited |
| High latency / packet loss simulation | Not tested | Requires network emulation (tc/netem) |

---

## 8. Approval & Sign-off

| Role | Name | Signature | Date |
|------|------|-----------|------|
| Lead Engineer | | | |
| QA Lead | | | |
| Security Review | | | |

---

## Appendix A: Quick Reference Commands

```bash
# Quick health check
curl -s http://localhost:8000/health | jq .
curl -s http://localhost:8000/routes | jq 'length'
curl -s http://localhost:8000/lookup?destination=192.168.1.50 | jq .
curl -s http://localhost:8000/api/lab/status | jq .
curl -s -X POST http://localhost:8000/network/dns-resolve \
  -H "Content-Type: application/json" \
  -d '{"hostname":"google.com"}' | jq .
curl -s -X POST http://localhost:8000/network/connectivity \
  -H "Content-Type: application/json" \
  -d '{"target":"8.8.8.8","protocol":"icmp"}' | jq .
curl -s -X POST http://localhost:8000/network/traceroute \
  -H "Content-Type: application/json" \
  -d '{"target":"8.8.8.8","max_hops":5}' | jq .
```

---

*End of End-to-End Test Plan*
