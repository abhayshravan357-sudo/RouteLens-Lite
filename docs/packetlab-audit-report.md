# PacketLab Audit Report

**Project**: RouteLens Lite - PacketLab Virtual Router Adapter  
**Date**: 2026-10-20  
**Auditor**: Agent B (PacketLab)  
**Scope**: Read-only audit of `backend/app/lab_adapter.py`, `backend/app/packet_lab.py`, `backend/app/packet_lab_routes.py`, `backend/tests/test_packet_lab.py`

---

## Executive Summary

The PacketLab adapter provides a controlled interface to the isolated Linux virtual-router lab (namespaces `rl260-client`, `rl260-router`, `rl260-server`). While the core infrastructure is solid, **critical gaps exist** in input validation, parameter usage, and privilege safety that must be addressed before production use.

---

## 1. Input Validation: Source/Destination IP Topology Check

**Finding**: ❌ **FAIL** - Accepts arbitrary IPs without topology validation

**Severity**: HIGH

**Evidence**:
- `packet_lab_routes.py:24-41` - `SimulateRequestModel` validates only IPv4 format via Pydantic
- `packet_lab.py:152-173` - `_validate_request()` checks format, protocol, TTL, length bounds only
- `packet_lab.py:213-221` - `simulate()` hardcodes `source_namespace="rl260-client"` but uses `request.destination_ip` directly without verifying it matches the lab's server IP (`192.168.20.2`)

**Impact**: Requests with `source_ip="10.0.0.1", destination_ip="8.8.8.8"` are accepted but will fail at runtime (no route from client namespace). The API should reject IPs not in the lab topology at request validation time.

**Recommendation**: Add topology-aware validation in `_validate_request()` to ensure `source_ip` ∈ {192.168.10.2} and `destination_ip` ∈ {192.168.20.2} (or at minimum verify destination is reachable via lab routes).

---

## 2. Capture Verification: Can `capture_verified=true` Without Evidence?

**Finding**: ✅ **PASS** - Requires actual tcpdump capture evidence

**Severity**: N/A (Working correctly)

**Evidence**:
- `packet_lab.py:236-238` - `capture_verified = packets_captured > 0` where `packets_captured` is parsed from tcpdump stdout
- `packet_lab.py:273-281` - `COMPLETED` state requires both `result.success AND capture_verified`
- `lab_adapter.py:575-581` - `capture_packets()` parses "packets captured" line from tcpdump output

**Note**: Verification details (`ttl_decremented`, `checksum_valid`, `route_matched` at `packet_lab.py:243-248`) are **inferred from ping success**, not from actual packet inspection. This is documented but worth noting.

---

## 3. Error Reporting: HTTP Status Codes & Messages

| Scenario | Expected | Actual | Status | Evidence |
|----------|----------|--------|--------|----------|
| Lab unavailable (namespaces/tools/permission) | 503 | 503 | ✅ PASS | `packet_lab_routes.py:109-114`, `packet_lab.py:112-119` |
| Capture timeout (no packets captured) | 408 | 408 | ✅ PASS | `packet_lab_routes.py:164-168`, `packet_lab.py:293-303` |
| Invalid request (bad IP, bad protocol) | 400 | 422 (validation) / 400 | ⚠️ PARTIAL | `packet_lab_routes.py:34-48` returns 422 for Pydantic validation |
| Transmission failure (ping failed) | 400/500 | 400 | ✅ PASS | `packet_lab_routes.py:169-173`, `packet_lab.py:282-292` |

**Note**: FastAPI returns 422 for request body validation errors (Pydantic), not 400. The contract specifies 400 but 422 is more semantically correct for validation failures.

---

## 4. Privilege Safety: Interactive `pkexec`/`sudo` from Web Request

**Finding**: ❌ **FAIL** - Code path triggers interactive authentication

**Severity**: CRITICAL

**Evidence**:
- `lab_adapter.py:180-185` - `_build_ns_cmd()` uses `["pkexec"]` by default (or `["sudo", "-n"]`)
- `lab_adapter.py:246-253` - `_run_in_namespace()` builds full command with privilege escalation
- `lab_adapter.py:196-202` - `_run_command()` uses `asyncio.create_subprocess_exec()` which **blocks indefinitely** waiting for pkexec/sudo password prompt when no TTY
- `lab_adapter.py:278-285` - Error handling catches "request dismissed" **after** subprocess hangs

**Impact**: Without passwordless sudo configured for specific `ip netns exec` commands, **every web request to `/api/lab/*` will hang indefinitely** at the privilege escalation prompt.

**Recommendation**: 
1. Document required sudoers rule: `abhaysawant ALL=(ALL) NOPASSWD: /usr/sbin/ip netns exec rl260-* ip addr show, /usr/sbin/ip netns exec rl260-* ip route show, /usr/sbin/ip netns exec rl260-* cat /proc/sys/net/ipv4/ip_forward, /usr/bin/ping, /usr/sbin/tcpdump`
2. Add startup check that validates privilege escalation works non-interactively
3. Consider running the backend with appropriate capabilities instead of pkexec/sudo

---

## 5. Parameter Usage: `protocol`, `ttl`, `length` in Packet Generation

**Finding**: ❌ **FAIL** - Parameters accepted, validated, echoed, but **NOT USED**

**Severity**: HIGH

**Evidence**:
- `packet_lab.py:152-173` - `_validate_request()` validates `protocol` ∈ {icmp,tcp,udp}, `ttl` ∈ [1,255], `length` ∈ [28,65535]
- `packet_lab.py:213-221` - `run_ping_with_capture()` called with hardcoded `filter_expr="icmp"`, ping count=3
- `lab_adapter.py:507` - `ping()` builds `["ping", "-c", str(count), ...]` - **no TTL, length, or protocol parameters**
- `lab_adapter.py:568` - `capture_packets()` uses hardcoded `filter_expr="icmp"`
- `packet_lab.py:259-270` - Response echoes `request.protocol`, `request.ttl - 1`, `request.length` but these never hit the wire

**Result**: Only ICMP ping with default size (64 bytes payload + 20 IP + 8 ICMP = 84 bytes) is ever transmitted, regardless of request.

**Recommendation**: Either implement protocol/TTL/length support (using `scapy` or `hping3`) or remove these parameters from the API contract and request model.

---

## 6. Test Coverage

**Total**: 37 tests collected

### Test Categories Covered

| Category | Tests |
|----------|-------|
| **Permission failures** | `test_get_namespace_status_permission_denied`, `test_check_lab_readiness_permission_issues`, `test_get_lab_status_unavailable`, `test_simulate_lab_unavailable` |
| **Missing tools** | `test_check_lab_readiness_missing_tools` |
| **Topology issues** | `test_check_lab_readiness_topology_issues` |
| **Capture timeout** | `test_simulate_timeout` (unit + routes) |
| **Unavailable lab** | `test_check_lab_readiness_permission_issues`, `test_get_status_lab_unavailable`, `test_simulate_lab_unavailable`, `test_get_lab_status_unavailable`, `test_simulate_lab_unavailable` |
| **Transmission error** | `test_simulate_transmission_error`, `test_simulate_error` |
| **Invalid request** | `test_simulate_invalid_request` (unit + routes) |
| **Success path** | `test_simulate_success`, `test_get_status_lab_ready`, `test_get_lab_status_available` |
| **Parameter validation** | `test_validate_request_protocol`, `test_validate_request_ttl_range`, `test_validate_request_length_range` |
| **Singleton pattern** | `test_get_packet_lab_singleton`, `test_get_lab_adapter_singleton` |
| **Data models** | `test_lab_state_enum_values`, `test_simulate_request_model_validation`, `test_lab_status_response_model` |
| **Namespace status** | `test_interface_info`, `test_route_info`, `test_namespace_status`, `test_lab_readiness_report` |

### Gaps
- No test verifies that `protocol`/`ttl`/`length` parameters are actually used in packet generation (they aren't)
- No test for topology validation of source/destination IPs (doesn't exist)
- No integration test with real namespaces (all mocked)

---

## Summary of Critical Issues

| # | Issue | Severity | File:Line |
|---|-------|----------|-----------|
| 1 | No topology validation for source/destination IPs | HIGH | `packet_lab.py:152-173` |
| 2 | Interactive pkexec/sudo blocks web requests | CRITICAL | `lab_adapter.py:180-202` |
| 3 | `protocol`/`ttl`/`length` not used in packet generation | HIGH | `packet_lab.py:213-221`, `lab_adapter.py:507` |
| 4 | Verification details inferred, not measured | MEDIUM | `packet_lab.py:243-248` |

---

## Files Changed in This Worktree (Uncommitted)

```
backend/app/lab_adapter.py       | 12 +-
backend/app/packet_lab_routes.py | 28 +-
backend/tests/test_packet_lab.py | 715 ++++++++++++++++++++++++++++-----------
```

**Note**: This audit was read-only. No application files were modified during the audit.