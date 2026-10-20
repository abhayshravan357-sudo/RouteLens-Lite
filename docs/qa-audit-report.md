# QA Audit Report — RouteLens Lite

**Date**: 2026-10-20  
**Auditor**: Agent D (TestPilot)  
**Commit**: ecac8d2 (main branch, merged routing-backend + frontend)  
**Backend Tests**: 41/41 passing  
**Frontend Build**: ✅ Successful  

---

## 1. API Contract Compliance Checklist

### 1.1 `/lookup` Endpoint (GET /lookup?destination=X)

| Requirement | Backend Implementation | Frontend Type | Status |
|-------------|----------------------|---------------|--------|
| Valid destination → 200 with route | ✅ Returns 200 + `RouteLookupResult` | `RouteLookupResult` (missing `transmitted`) | ⚠️ **Mismatch** |
| Invalid IPv4 format → 400 | ✅ `{"detail": "Invalid IPv4 address: ..."}` | Handled via `ApiError` | ✅ |
| Out-of-bounds IP → 400 | ✅ Same as above | Handled via `ApiError` | ✅ |
| No matching route → 404 | ✅ With custom table (no default route) | Handled via `ApiError` | ✅ |
| Missing destination param → 422 | ✅ FastAPI validation error | Handled via `ApiError` | ✅ |
| `transmitted: false` always present | ✅ Field in model, always `false` | ❌ **Missing in frontend type** | ❌ **Gap** |

### 1.2 `/routes` Endpoint (GET /routes)

| Requirement | Backend Implementation | Frontend Type | Status |
|-------------|----------------------|---------------|--------|
| Returns array of `RoutingEntry` | ✅ 5 sample routes | `RoutingEntry[]` | ✅ |
| All required fields present | ✅ destination, next_hop, interface, metric, next_hop_type | Matches backend | ✅ |

### 1.3 `/health` Endpoint (GET /health)

| Requirement | Backend Implementation | Frontend Type | Status |
|-------------|----------------------|---------------|--------|
| Returns `{status: "ok", service: "RouteLens Lite API"}` | ✅ | Handled in `checkHealth()` | ✅ |

---

## 2. Field-by-Field Type Verification

### `RoutingEntry` — ✅ MATCHES

| Backend (Pydantic) | Frontend (TypeScript) | Match |
|-------------------|----------------------|-------|
| `destination: str` | `destination: string` | ✅ |
| `next_hop: Optional[str]` | `next_hop: string \| null` | ✅ |
| `interface: str` | `interface: string` | ✅ |
| `metric: int (ge=0)` | `metric: number` | ✅ |
| `next_hop_type: NextHopType` | `next_hop_type: 'gateway' \| 'direct'` | ✅ |

### `RouteLookupResult` — ❌ MISMATCH

| Backend (Pydantic) | Frontend (TypeScript) | Match |
|-------------------|----------------------|-------|
| `matched: bool` | `matched: boolean` | ✅ |
| `route: Optional[RoutingEntry]` | `route: RoutingEntry \| null` | ✅ |
| `explanation: str` | `explanation: string` | ✅ |
| `error: Optional[str]` | `error: string \| null` | ✅ |
| **`transmitted: bool = False`** | **MISSING** | ❌ |

**Impact**: Frontend will ignore the `transmitted` field from backend responses. TypeScript strict mode would error if backend sends extra field not in interface.

---

## 3. Error Handling Verification

### Tested Error Responses

| Scenario | HTTP Status | Response Body | Honest? |
|----------|------------|---------------|---------|
| `destination=not.an.ip` | 400 | `{"detail": "Invalid IPv4 address: not.an.ip"}` | ✅ |
| `destination=999.999.999.999` | 400 | `{"detail": "Invalid IPv4 address: 999.999.999.999"}` | ✅ |
| Missing `destination` param | 422 | `{"detail": [{"type":"missing","loc":["query","destination"],"msg":"Field required"}]}` | ✅ |
| No matching route (custom table) | 404 | `{"detail": "No route matches destination ..."}` | ✅ |

**No false success claims**: All error paths return appropriate HTTP error codes. The `transmitted: false` field correctly documents that no physical packet transmission occurs.

---

## 4. Frontend-Backend Integration Test Results

### Manual API Testing (Backend Running)

| Test Case | Command | Result |
|-----------|---------|--------|
| Valid overlapping route (192.168.1.50) | `curl /lookup?destination=192.168.1.50` | ✅ 200, returns /25 route, `transmitted: false` |
| Default route (8.8.8.8) | `curl /lookup?destination=8.8.8.8` | ✅ 200, returns 0.0.0.0/0, `transmitted: false` |
| Direct route (10.5.5.5) | `curl /lookup?destination=10.5.5.5` | ✅ 200, returns 10.0.0.0/8 direct, `transmitted: false` |
| Invalid IP | `curl /lookup?destination=not.an.ip` | ✅ 400 |
| Missing param | `curl /lookup` | ✅ 422 |
| List routes | `curl /routes` | ✅ 200, 5 routes |

### Frontend Build & Type Check

```bash
cd frontend && npm run build    # ✅ Success
cd frontend && npm run lint     # ✅ tsc --noEmit passes (no strict extra property check)
```

**Note**: TypeScript `tsc --noEmit` passes because extra properties in JSON responses are allowed by default. However, strict type safety would require the `transmitted` field in the interface.

---

## 5. Identified Gaps & Issues

### 5.1 Critical: Missing `transmitted` Field in Frontend Types
- **File**: `frontend/src/types/routing.ts:15-20`
- **Fix**: Add `transmitted: boolean;` to `RouteLookupResult` interface
- **Risk**: Type drift; frontend cannot access/document the field

### 5.2 Packet Lab API Not Implemented
- **Contract**: `docs/packet-lab-api-contract.md`
- **Endpoints needed**: `GET /api/lab/status`, `POST /api/lab/simulate`
- **Frontend ready**: `PacketJourney.tsx` component, `LabState` types, API client has `LabUnavailableError`
- **Backend**: No implementation in `backend/app/main.py`
- **Blocker**: PacketLab agent (Agent B) in progress

### 5.3 No E2E/Integration Tests
- No Playwright/Cypress tests for frontend-backend flow
- No contract tests verifying API schema matches types
- Manual testing only

### 5.4 CORS Configuration
- Backend allows all origins (`allow_origins=["*"]`)
- Acceptable for dev, should be restricted for production

---

## 6. Integration Test Plan for PacketLab Completion

### 6.1 Pre-Integration Checklist
- [ ] Backend implements `GET /api/lab/status` per contract
- [ ] Backend implements `POST /api/lab/simulate` per contract
- [ ] Backend returns 503 when lab unavailable, 408 on timeout
- [ ] Virtual router isolated (network namespaces/containers)
- [ ] No host network modification
- [ ] Frontend types updated to match PacketLab responses exactly

### 6.2 Integration Test Scenarios

| ID | Scenario | Steps | Expected |
|----|----------|-------|----------|
| INT-01 | Lab ready flow | 1. GET /api/lab/status → available=true<br>2. POST /api/lab/simulate with valid packet<br>3. Verify state progression | 200 at each step, final state `completed`, `capture_verified: true` |
| INT-02 | Lab unavailable | 1. Stop virtual router<br>2. GET /api/lab/status | 503, `available: false`, `state: "unavailable"` |
| INT-03 | Simulate timeout | 1. Configure slow capture<br>2. POST /api/lab/simulate | 408, `state: "timeout"` |
| INT-04 | Capture verification failed | 1. Corrupt capture logic<br>2. POST /api/lab/simulate | 200, `capture_verified: false`, details in `verification_details` |
| INT-05 | Route lookup → lab simulation | 1. GET /lookup?destination=192.168.1.50<br>2. Use result to POST /api/lab/simulate<br>3. Verify `route_matched` consistency | Both succeed, `route_matched` in simulate request matches lookup result |
| INT-06 | Frontend state machine | 1. Load frontend<br>2. Enter destination → Analyze Route<br>3. Click Simulate Packet<br>4. Observe state progression | UI shows idle→ready→simulating→transmitting→capturing→verifying→completed |
| INT-07 | Error display | 1. Make lab unavailable<br>2. Attempt simulate | UI shows "Lab Unavailable" state with error message |

### 6.3 Contract Test (Automated)
```python
# Example: tests/test_packetlab_contract.py
async def test_lab_status_contract():
    """Verify /api/lab/status matches documented schema."""
    # Check required fields, enum values, nested objects

async def test_simulate_request_validation():
    """Verify required fields, IP format, protocol enum."""
    # Missing source_ip → 422
    # Invalid protocol → 422
    # Valid → 200 or 503/408

async def test_simulate_response_contract():
    """Verify response matches contract exactly."""
    # Check state enum, packet structure, verification_details
```

### 6.4 Safety Verification Tests
- [ ] Confirm no host route table modification (`ip route show` unchanged)
- [ ] Confirm no global `ip_forward` toggle
- [ ] Verify virtual router uses isolated network namespace
- [ ] Verify `transmitted: false` on `/lookup`, `true` only if real packet sent (never in this project)

---

## 7. Recommended Fixes (Priority Order)

1. **Add `transmitted: boolean` to `RouteLookupResult`** in `frontend/src/types/routing.ts`
2. **Implement PacketLab endpoints** per `docs/packet-lab-api-contract.md`
3. **Add contract tests** for PacketLab API
4. **Add E2E tests** (Playwright) for critical user flows
5. **Restrict CORS** for production deployment

---

## 8. Summary

| Area | Status | Notes |
|------|--------|-------|
| Backend routing logic | ✅ Complete | 41 tests pass, correct algorithm |
| Backend `/lookup` API | ✅ Complete | Correct status codes, `transmitted: false` |
| Backend `/routes` API | ✅ Complete | Returns all sample routes |
| Frontend types (routing) | ⚠️ Minor gap | Missing `transmitted` field |
| Frontend build | ✅ Passes | TypeScript + Vite build successful |
| PacketLab API | 🚧 In progress | Contract defined, backend not implemented |
| Integration tests | ❌ Missing | Need E2E + contract tests |

**Overall**: Backend routing API is production-ready. Frontend has minor type gap. PacketLab integration pending Agent B completion.