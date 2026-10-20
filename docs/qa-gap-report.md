# QA Gap Report — RouteLens Lite PacketLab Integration

**Date**: 2026-10-20  
**Auditor**: Agent D (TestPilot)  
**Scope**: PacketLab API (`/api/lab/status`, `/api/lab/simulate`) and frontend integration  
**Backend Tests**: 78/78 passing  
**Frontend Build**: ✅ Successful  

---

## Executive Summary

The PacketLab implementation is **functionally complete** with solid error handling and contract alignment. However, several **gaps exist** in test coverage, topology honesty, and safety verification that should be addressed before production use.

---

## 1. HTTP Error Behavior Verification

### 1.1 Backend Error Responses

| Endpoint | Scenario | Expected Status | Actual Implementation | Verified |
|----------|----------|----------------|----------------------|----------|
| `GET /api/lab/status` | Lab ready | 200 | ✅ Returns `LabStatusResponse` with `available: true` | ✅ Tested |
| `GET /api/lab/status` | Lab unavailable (permission) | 503 | ✅ `HTTPException(503, detail=error)` | ✅ Tested |
| `GET /api/lab/status` | Lab unavailable (missing tools) | 503 | ✅ `HTTPException(503, detail=error)` | ✅ Tested |
| `GET /api/lab/status` | Lab unavailable (topology issues) | 503 | ✅ `HTTPException(503, detail=error)` | ✅ Tested |
| `POST /api/lab/simulate` | Invalid request (validation) | 422 | ✅ FastAPI/Pydantic validation | ✅ Tested |
| `POST /api/lab/simulate` | Lab unavailable | 503 | ✅ Maps `LabState.UNAVAILABLE` → 503 | ✅ Tested |
| `POST /api/lab/simulate` | Capture timeout | 408 | ✅ Maps `LabState.TIMEOUT` → 408 | ✅ Tested |
| `POST /api/lab/simulate` | Transmission error | 400 | ✅ Maps `LabState.ERROR` → 400 | ✅ Tested |
| `POST /api/lab/simulate` | Success | 200 | ✅ Returns `SimulateResponseModel` | ✅ Tested |

**Evidence**: `backend/tests/test_packet_lab.py` lines 509-655 - all 8 route tests pass.

### 1.2 Frontend Error Display

| Error Type | Frontend Handling | User Visible? | Notes |
|------------|------------------|---------------|-------|
| `LabUnavailableError` (503) | Caught in `checkLabAvailability()` → sets `labStatus` with `available: false`, `state: 'unavailable'` | ✅ Shows "Lab Unavailable" banner + disabled button | PacketJourney.tsx:232-236 |
| `TimeoutError` (AbortError) | Caught in `fetchWithTimeout` → throws `TimeoutError` | ✅ Shows "Simulation timed out" in red banner | PacketJourney.tsx:187-192 |
| `ApiError` (400, 408, other) | Caught in `handleSimulatePacket()` → sets `simulateError` | ✅ Shows error message in red banner | App.tsx:182-190 |
| Network error | Caught → `ApiError` with status 0 | ✅ Shows "Network error" | routing.ts:76-80 |

**Gap**: 408 timeout from `/api/lab/simulate` is NOT caught as `TimeoutError` - it's caught as `ApiError` with status 408. The frontend only treats AbortError (client-side timeout) as `TimeoutError`, not server-side 408.

**File**: `frontend/src/api/routing.ts` lines 59-70, 81-83

---

## 2. Contract Alignment

### 2.1 SimulateRequest Comparison

| Field | Backend (Pydantic `SimulateRequestModel`) | Frontend (TS `SimulateRequest`) | Match |
|-------|-------------------------------------------|--------------------------------|-------|
| `source_ip` | `str` (validated IPv4) | `string` | ✅ |
| `destination_ip` | `str` (validated IPv4) | `string` | ✅ |
| `protocol` | `str` (enum: icmp/tcp/udp, lowercase) | `'icmp' \| 'tcp' \| 'udp'` | ✅ |
| `ttl` | `int` (1-255) | `number` | ✅ |
| `length` | `int` (28-65535) | `number` | ✅ |
| `route_matched` | `str \| None` | `string \| null` | ✅ |
| `egress_interface` | `str \| None` | `string \| null` | ✅ |
| `next_hop` | `str \| None` | `string \| null` | ✅ |

**Alignment**: ✅ **Perfect match**

### 2.2 SimulateResponse Comparison

| Field | Backend (`SimulateResponseModel`) | Frontend (`SimulateResponse`) | Match |
|-------|-----------------------------------|-------------------------------|-------|
| `state` | `str` (LabState enum value) | `LabState` | ✅ |
| `message` | `str` | `string` | ✅ |
| `packet` | `PacketResponseModel \| None` | `PacketResponse \| null` | ✅ |
| `capture_verified` | `bool` (default False) | `boolean` | ✅ |
| `verification_details` | `VerificationDetailsModel \| None` | `VerificationDetails \| null` | ✅ |
| `error` | `str \| None` | `string \| null` | ✅ |

**PacketResponse nested fields:**

| Field | Backend | Frontend | Match |
|-------|---------|----------|-------|
| `source_ip` | `str` | `string` | ✅ |
| `destination_ip` | `str` | `string` | ✅ |
| `protocol` | `str` | `string` | ✅ |
| `ttl` | `int` | `number` | ✅ |
| `length` | `int` | `number` | ✅ |
| `forwarding_info` | `ForwardingInfoModel` | `ForwardingInfoResponse` | ✅ |

**ForwardingInfo nested fields:**

| Field | Backend | Frontend | Match |
|-------|---------|----------|-------|
| `ingress_interface` | `str` | `string` | ✅ |
| `egress_interface` | `str` | `string` | ✅ |
| `next_hop` | `str` | `string` | ✅ |
| `route_matched` | `str` | `string` | ✅ |
| `action` | `str` (default "forward") | `string` | ✅ |

**VerificationDetails nested fields:**

| Field | Backend | Frontend | Match |
|-------|---------|----------|-------|
| `ttl_decremented` | `bool` | `boolean` | ✅ |
| `checksum_valid` | `bool` | `boolean` | ✅ |
| `route_matched` | `bool` | `boolean` | ✅ |

**Alignment**: ✅ **Perfect match** - Frontend types exactly mirror backend Pydantic models.

### 2.3 LabStatusResponse Comparison

| Field | Backend (`LabStatusResponse`) | Frontend (`LabStatusResponse`) | Match |
|-------|-------------------------------|-------------------------------|-------|
| `available` | `bool` | `boolean` | ✅ |
| `state` | `str` | `LabState` | ✅ |
| `message` | `str` | `string` | ✅ |
| `router_info` | `dict \| None` | `RouterInfo \| null` | ✅ |
| `error` | `str \| None` | `string \| null` | ✅ |

**RouterInfo nested:**

| Field | Backend | Frontend | Match |
|-------|---------|----------|-------|
| `interfaces` | `list[str]` | `string[]` | ✅ |
| `routing_table` | `list[dict]` | `RouterRouteEntry[]` | ✅ |
| `client_ip` | `str \| None` | `string \| null` | ✅ |
| `server_ip` | `str \| None` | `string \| null` | ✅ |

**Alignment**: ✅ **Perfect match**

---

## 3. Missing Failure Scenario Tests

### 3.1 Lab Unavailable - Real (Not Mocked)

| Test Case | Current Coverage | Gap |
|-----------|------------------|-----|
| Namespaces don't exist | Mocked in `test_get_lab_status_unavailable` | ❌ No integration test with real missing namespaces |
| Permission denied (pkexec/sudo failure) | Mocked in `test_get_namespace_status_permission_denied` | ❌ No real permission test |
| Missing tools (tcpdump, ip, ping) | Mocked in `test_check_lab_readiness_missing_tools` | ❌ No real missing tool test |
| Wrong topology (IP forwarding off) | Mocked in `test_check_lab_readiness_topology_issues` | ❌ No real topology test |

**Severity**: **High** - All lab readiness tests use mocks. No integration test proves real lab behavior.

### 3.2 Capture Timeout (408)

| Test Case | Current Coverage | Gap |
|-----------|------------------|-----|
| Ping succeeds, zero packets captured | Mocked in `test_simulate_timeout` | ❌ No real timeout test |
| tcpdump filter matches nothing | Not tested | ❌ Missing |
| Capture timeout (5s) expires before packets arrive | Not tested | ❌ Missing |

**Severity**: **Medium** - Logic tested but not with real network conditions.

### 3.3 Permission Denied

| Test Case | Current Coverage | Gap |
|-----------|------------------|-----|
| pkexec not configured for web user | Mocked in `test_get_namespace_status_permission_denied` | ❌ No real permission test |
| sudo -n fails (no passwordless sudo) | Not tested | ❌ Missing |
| Namespace exists but not accessible | Mocked | ❌ Missing |

**Severity**: **High** - Critical for production deployment where web backend may lack privileges.

### 3.4 Invalid Inputs

| Test Case | Current Coverage | Gap |
|-----------|------------------|-----|
| Invalid source IP | ✅ `test_simulate_invalid_request` | - |
| Invalid destination IP | Not explicitly tested (only source) | ❌ Missing |
| Unsupported protocol (e.g., "sctp") | ✅ `test_validate_request_protocol` | - |
| TTL out of range (0, 256) | ✅ `test_validate_request_ttl_range` | - |
| Length out of range (<28, >65535) | ✅ `test_validate_request_length_range` | - |

**Severity**: **Low** - Most covered.

### 3.5 Ping/Capture Discordance

| Test Case | Current Coverage | Gap |
|-----------|------------------|-----|
| Ping fails, capture succeeds | Not tested | ❌ Missing - could indicate routing asymmetry |
| Ping succeeds, capture fails (timeout) | ✅ `test_simulate_timeout` mock | Partially covered |
| Ping succeeds, capture has packets but wrong interface | Not tested | ❌ Missing |
| Capture has packets but checksum invalid | Not tested | ❌ Missing - checksum verification is assumed |

**Severity**: **Medium** - Real-world scenarios not covered.

### 3.6 False Positive `capture_verified=true`

| Test Case | Current Coverage | Gap |
|-----------|------------------|-----|
| `capture_verified=true` without actual capture evidence | Not tested | ❌ Critical gap - could claim verification without proof |

**Evidence**: In `packet_lab.py:238`, `capture_verified = packets_captured > 0`. If tcpdump reports packets captured but they're not the expected packets, this could be misleading.

**Severity**: **Critical** - Trustworthiness of verification.

---

## 4. Safety Verification

### 4.1 Host Network Modification Risk

| Operation | Risk | Mitigation | Test Coverage |
|-----------|------|------------|---------------|
| `ip netns exec` commands | None - runs in isolated namespaces | Namespaces created externally | ✅ No test modifies host routes |
| `ip route show` in namespace | Read-only | No write operations | ✅ Verified in code |
| `ping` from namespace | None - confined to namespace | Network isolation | ✅ Verified in code |
| `tcpdump` on namespace interface | None - passive capture | No packet injection | ✅ Verified in code |
| `cat /proc/sys/net/ipv4/ip_forward` | Read-only | No modification | ✅ Verified in code |

**Finding**: ✅ **No host network modification** - All operations use `ip netns exec` which confines commands to the target namespace. The adapter never runs `ip route add/del`, `sysctl -w`, or similar host-modifying commands.

**Evidence**: `lab_adapter.py` lines 180-218 (`_run_in_namespace`), 246-253 (`_run_in_namespace`), 268-303 (`get_namespace_status`), 473-554 (`ping`), 556-601 (`capture_packets`), 603-655 (`run_ping_with_capture`)

### 4.2 Global IP Forwarding

| Check | Result |
|-------|--------|
| Does any code enable `net.ipv4.ip_forward` globally? | ❌ No - only reads it in router namespace |
| Does any test enable IP forwarding? | ❌ No - tests mock the status |

**Finding**: ✅ **Safe** - No global IP forwarding changes.

### 4.3 Namespace Creation/Deletion

| Check | Result |
|-------|--------|
| Does any code create namespaces (`ip netns add`)? | ❌ No |
| Does any code delete namespaces (`ip netns del`)? | ❌ No |
| Does any test create/delete namespaces? | ❌ No - all mocked |

**Finding**: ✅ **Safe** - Namespaces are managed externally (expected to exist).

---

## 5. Topology Honesty

### 5.1 Network Mismatch Warning

**RouteCore (Routing Table) Networks:**
- `192.168.1.0/24`, `192.168.1.0/25`, `192.168.0.0/16`, `10.0.0.0/8`, `0.0.0.0/0`

**PacketLab (Virtual Router) Networks:**
- `192.168.10.0/24` (client ↔ router)
- `192.168.20.0/24` (router ↔ server)

**Frontend Handling**: ✅ **Explicit warning displayed**

**File**: `PacketJourney.tsx` lines 117-134

```tsx
{!isTopologyCompatible && (
  <div className="compatibility-notice" style={{...}}>
    <strong>⚠ Topology Mismatch: </strong>
    {compatibilityMessage}
    <br />
    <small>
      The RouteCore routing table uses different networks than the isolated packet lab.
      The lab only supports: Client 192.168.10.2 → Router (rlr0c/rlr0s) → Server 192.168.20.2
    </small>
  </div>
)}
```

### 5.2 Misleading Simulation Risk

**Scenario**: User enters `192.168.1.50` → RouteCore matches `192.168.1.0/25` via `eth1` → User clicks "Simulate Packet"

**Current Behavior**: 
- Frontend uses lab's actual IPs (`192.168.10.2` → `192.168.20.2`) regardless of RouteCore result
- `route_matched` in request is set to RouteCore's route (e.g., `192.168.1.0/25`)
- Lab topology shows `192.168.10.0/24` and `192.168.20.0/24`

**Evidence**: `App.tsx` lines 165-176

```tsx
const request: SimulateRequest = {
  source_ip: labStatus.router_info?.client_ip || '192.168.10.2',
  destination_ip: labStatus.router_info?.server_ip || '192.168.20.2',
  ...
  route_matched: lookupResult.route.destination,  // RouteCore route!
  ...
};
```

**Risk**: **Medium** - The simulation runs in a completely different network topology than the routing decision. User might think the lab validated their specific route when it actually validated a different topology.

**Mitigation**: The warning banner (lines 117-134) explains this, but it's easy to miss.

---

## 6. Additional Gaps Identified

### 6.1 Missing `transmitted` Field in RouteLookupResult

**Backend**: Returns `transmitted: false` always (since `b4abfeb`)
**Frontend Type**: `RouteLookupResult` interface **missing** `transmitted` field

**File**: `frontend/src/types/routing.ts` lines 15-20

```typescript
export interface RouteLookupResult {
  matched: boolean;
  route: RoutingEntry | null;
  explanation: string;
  error: string | null;
  // MISSING: transmitted: boolean;
}
```

**Severity**: **Low** - TypeScript doesn't error on extra properties, but type safety incomplete.

### 6.2 No Contract Tests for API Schema

- No tests that verify OpenAPI schema matches TypeScript types
- No automated schema validation in CI

### 6.3 Deprecation Warning in Tests

```
DeprecationWarning: datetime.datetime.utcnow() is deprecated
```
**File**: `lab_adapter.py:388`
**Fix**: Use `datetime.now(timezone.utc)`

### 6.4 No E2E Tests

- No Playwright/Cypress tests for full user flow
- No test that route lookup → lab status → simulate works end-to-end

---

## 7. Gap Summary Table

| ID | Area | Severity | Description | File/Line | Fix Effort |
|----|------|----------|-------------|-----------|------------|
| GAP-01 | Error Handling | High | 408 timeout not caught as `TimeoutError` in frontend | `routing.ts:59-70,81-83` | Low |
| GAP-02 | Testing | High | All lab readiness tests mocked - no real integration tests | `test_packet_lab.py` | High |
| GAP-03 | Testing | High | No real permission denied test (pkexec/sudo) | `test_packet_lab.py:89-99` | High |
| GAP-04 | Testing | Medium | No real capture timeout test | `test_packet_lab.py:390-428` | Medium |
| GAP-05 | Testing | Medium | No ping/capture discordance tests | `test_packet_lab.py` | Medium |
| GAP-06 | Safety | Critical | `capture_verified=true` without packet content verification | `packet_lab.py:238` | Medium |
| GAP-07 | Topology | Medium | User may think lab validates their RouteCore route | `App.tsx:165-176, PacketJourney.tsx:117-134` | Low |
| GAP-08 | Types | Low | Frontend `RouteLookupResult` missing `transmitted` field | `types/routing.ts:15-20` | Low |
| GAP-09 | Code Quality | Low | `datetime.utcnow()` deprecation warning | `lab_adapter.py:388` | Low |
| GAP-10 | Testing | Medium | No E2E/integration tests for full flow | N/A | High |

---

## 8. Recommended Fixes (Priority Order)

### Critical (Do First)
1. **GAP-06**: Add packet content verification to `capture_verified` logic - verify ICMP type/code, TTL, source/dest IP in captured packets
2. **GAP-02, GAP-03**: Add real integration tests with actual namespaces (or document that mocks are the only feasible CI approach)

### High
3. **GAP-01**: Fix frontend to treat 408 as `TimeoutError` - update `fetchWithTimeout` to check `response.status === 408`
4. **GAP-04**: Add real capture timeout test (or document limitation)
5. **GAP-05**: Add tests for ping/capture discordance scenarios

### Medium
6. **GAP-07**: Make topology mismatch warning more prominent (modal dialog on first simulate attempt)
7. **GAP-10**: Add Playwright E2E tests for critical paths

### Low
8. **GAP-08**: Add `transmitted: boolean` to `RouteLookupResult` interface
9. **GAP-09**: Fix `datetime.utcnow()` → `datetime.now(timezone.utc)`

---

## 9. Verification Commands Used

```bash
# Backend tests
cd /home/abhaysawant/Desktop/cn_project_2/backend
source .venv/bin/activate
pytest tests/ -v
# Result: 78 passed

# Frontend build
cd /home/abhaysawant/Desktop/cn_project_2/.kilo/worktrees/agent-frontend-d524da8858032942/frontend
npm run build
# Result: ✅ Success

# Manual API verification (backend running)
curl http://127.0.0.1:8000/api/lab/status
curl -X POST http://127.0.0.1:8000/api/lab/simulate -H "Content-Type: application/json" -d '{"source_ip":"192.168.10.2","destination_ip":"192.168.20.2"}'
```

---

## 10. Conclusion

The PacketLab integration is **well-structured** with:
- ✅ Correct HTTP error codes (400, 408, 503)
- ✅ Perfect contract alignment between backend Pydantic and frontend TypeScript
- ✅ Comprehensive mocked unit tests (38 PacketLab tests)
- ✅ Safe architecture (no host network modification)
- ✅ Clear topology mismatch warning

**Primary concerns**:
1. **Zero real integration tests** - all lab tests use mocks
2. **Verification trustworthiness** - `capture_verified` based only on packet count, not content
3. **408 handling gap** in frontend error classification

**Recommendation**: Address GAP-06 (verification integrity) and GAP-02/03 (real integration tests) before considering this production-ready.