# RouteLens Lite — Task Ledger

**Last Updated**: 2026-10-20T10:30:00Z  
**Project Root**: `/home/abhaysawant/Desktop/cn_project_2`

---

## Task Format
- **ID**: Unique identifier
- **Title**: Brief description
- **Owner**: Responsible agent/role
- **Branch/Worktree**: Where work happens
- **Files**: Files to modify (scope)
- **Depends On**: Prerequisite tasks
- **Acceptance Criteria**: How to verify completion
- **Verification Commands**: Exact commands to run
- **Status**: Pending / In Progress / Done / Blocked

---

## Phase 0: Audit & Baseline

### TASK-001: Read-Only Repository Audit
- **Owner**: Manager
- **Status**: ✅ **Done**
- **Files**: None (read-only)
- **Verification**: 
  - `git status --short`
  - `python -m pytest -q` → 78 passed
  - `npm run build` → ✅ passes
- **Deliverables**: `docs/manager-status.md`, this ledger

---

## Phase 1: Fix PacketLab Critical Issues ✅ **ALL COMPLETED**

### TASK-101: Add Topology Validation for Simulate API
- **Owner**: PacketLab
- **Status**: ✅ **Done**
- **Branch**: Main worktree (changes in `backend/app/packet_lab.py`)
- **Files**: `backend/app/packet_lab.py` (method `_validate_request`)
- **Depends On**: TASK-001
- **Acceptance Criteria**: ✅ Met
  - `/api/lab/simulate` rejects source_ip not in {192.168.10.2}
  - `/api/lab/simulate` rejects destination_ip not in {192.168.20.2}
  - Returns 422 with clear message for invalid topology IPs
  - Existing tests still pass
- **Verification**: ✅ Passed
  ```bash
  cd backend && source .venv/bin/activate && python -m pytest tests/test_packet_lab.py -v
  # All 37 PacketLab tests pass
  ```

### TASK-102: Non-Interactive Privilege Check (Fix pkexec Blocking)
- **Owner**: PacketLab
- **Status**: ✅ **Done**
- **Files**: 
  - `backend/app/lab_adapter.py` (added `_validate_privileges()`, modified `_run_in_namespace()`)
- **Depends On**: TASK-001
- **Acceptance Criteria**: ✅ Met
  - Added `_validate_privileges()` - quick non-interactive check (2s timeout) testing `pkexec true` / `sudo -n true`
  - Modified `_run_in_namespace()` - returns clear error (HTTP 503) instead of hanging on interactive prompt
  - Error message: "Privilege escalation (pkexec/sudo) not available for namespace operations. Configure passwordless sudo for 'ip netns exec' commands or run backend with appropriate capabilities."
  - Tests cover mocked privilege failures
- **Verification**: ✅ Passed
  ```bash
  cd backend && source .venv/bin/activate && python -m pytest tests/test_packet_lab.py -v
  # All 37 PacketLab tests pass including privilege tests
  ```

### TASK-103: Restrict Protocol to ICMP Only; Document Unused Params
- **Owner**: PacketLab
- **Status**: ✅ **Done** (Option A - Remove support for unused protocols)
- **Files**: 
  - `backend/app/packet_lab.py` (enhanced `_validate_request()`)
  - `backend/app/packet_lab_routes.py` (updated `SimulateRequestModel.validate_protocol`)
- **Depends On**: TASK-101, TASK-102
- **Acceptance Criteria**: ✅ Met (Option A - Restrict)
  - Only `icmp` protocol accepted; tcp/udp return 422
  - Pydantic model validation enforces `icmp` only
  - `ttl`/`length` field descriptions updated: "not currently used in packet generation"
- **Verification**: ✅ Passed
  ```bash
  cd backend && source .venv/bin/activate && python -m pytest tests/ -v
  # All 78 tests pass
  ```

### TASK-104: Run Full Backend Test Suite After Fixes
- **Owner**: PacketLab
- **Status**: ✅ **Done**
- **Files**: All backend test files
- **Depends On**: TASK-101, TASK-102, TASK-103
- **Acceptance Criteria**: ✅ Met
  - All 78 tests pass
  - No test regressions
  - Only 4 deprecation warnings (datetime.utcnow - pre-existing)
- **Verification**: ✅ Passed
  ```bash
  cd backend && source .venv/bin/activate && python -m pytest -q
  # 78 passed, 4 warnings in 0.29s
  ```

---

## Phase 2: Frontend Fixes ✅ **ALL COMPLETED**

### TASK-201: Fix 408 Timeout Handling in API Client
- **Owner**: JourneyUI
- **Status**: ✅ **Done**
- **Files**: `frontend/src/api/routing.ts` (fetchWithTimeout function)
- **Depends On**: TASK-001
- **Acceptance Criteria**: ✅ Met
  - Server-side 408 response throws `TimeoutError` (not `ApiError`)
  - Added `checkLabStatus()` and `simulatePacket()` functions with 30s LAB_TIMEOUT
  - Existing error handling for AbortError still works
- **Verification**: ✅ Passed
  ```bash
  cd frontend && npm run build
  # ✅ Build passes, TypeScript clean
  ```

### TASK-202: Add `transmitted` Field to RouteLookupResult Type
- **Owner**: JourneyUI
- **Status**: ✅ **Done** (Already present in main worktree)
- **Files**: `frontend/src/types/routing.ts`
- **Depends On**: TASK-001
- **Acceptance Criteria**: ✅ Met
  - `RouteLookupResult` interface includes `transmitted: boolean`
  - TypeScript compiles without errors
  - Matches backend Pydantic model exactly
- **Verification**: ✅ Passed
  ```bash
  cd frontend && npx tsc --noEmit
  # ✅ No errors
  ```

### TASK-203: Make Topology Mismatch Warning More Prominent
- **Owner**: JourneyUI
- **Status**: ✅ **Done**
- **Files**: 
  - `frontend/src/App.tsx` (added warning banner in Packet Journey section)
  - `frontend/src/index.css` (added `.topology-warning` styles)
- **Depends On**: TASK-201, TASK-202
- **Acceptance Criteria**: ✅ Met
  - Prominent warning banner shown in Packet Journey section
  - Clear explanation that RouteCore sample networks (192.168.1.0/24, 10.0.0.0/8) differ from Lab networks (192.168.10.0/24, 192.168.20.0/24)
  - States "The simulation below uses the LAB topology, NOT your routing decision."
- **Verification**: ✅ Passed
  ```bash
  cd frontend && npm run build
  # ✅ Build passes
  ```

### TASK-204: Additional Frontend Integration Work
- **Owner**: JourneyUI
- **Status**: ✅ **Done**
- **Files**: 
  - `frontend/src/api/routing.ts` - Added `checkLabStatus()`, `simulatePacket()`, fixed 408→TimeoutError
  - `frontend/src/types/routing.ts` - Complete PacketLab types matching FastAPI models
  - `frontend/src/components/PacketJourney.tsx` - Rewritten to use real API data, removed fake simulation
  - `frontend/src/App.tsx` - Added `checkLabStatus` effect, `handleSimulatePacket` with real API, topology warning
- **Verification**: ✅ Passed
  ```bash
  cd frontend && npm run build && npx tsc --noEmit
  # ✅ Build passes, TypeScript clean
  ```

### TASK-205: Run Frontend Build & Type Check
- **Owner**: JourneyUI
- **Status**: ✅ **Done**
- **Depends On**: TASK-201, TASK-202, TASK-203, TASK-204
- **Acceptance Criteria**: ✅ Met
  - `npm run build` passes
  - `npx tsc --noEmit` passes (no TypeScript errors)
- **Verification**: ✅ Passed
  ```bash
  cd frontend && npm run build && npx tsc --noEmit
  # ✅ Build passes (910ms), TypeScript clean
  ```

---

## Phase 3 (Autonomous Phase 1): Real Network Collection ✅ **ALL COMPLETED**

### TASK-301: Real Network Interfaces Collector
- **Owner**: Backend
- **Status**: ✅ **Done**
- **Files**: 
  - `backend/app/network_collector.py` (new)
  - `backend/app/main.py` (add router)
  - `backend/tests/test_network_collector.py` (new)
- **Depends On**: TASK-104, TASK-205
- **Acceptance Criteria**: ✅ Met
  - `GET /network/interfaces` returns real `ip -j addr show` output parsed
  - `GET /network/routes` returns real `ip -j route show` output parsed
  - `GET /network/neighbors` returns real `ip -j neigh show` output parsed
  - `GET /network/all` returns parallel collection of all three
  - Read-only, no privilege escalation needed
  - Handles missing commands, empty output, malformed output, timeouts
  - 22 unit tests passing (parsing, errors, edge cases)
- **Verification**: ✅ Passed
  ```bash
  cd backend && source .venv/bin/activate && python -m pytest tests/test_network_collector.py -v
  # 22 passed
  cd backend && source .venv/bin/activate && python -m pytest -q
  # 100 passed
  ```

### TASK-302: Frontend Network Diagnostics Dashboard
- **Owner**: JourneyUI
- **Status**: ✅ **Done**
- **Files**: 
  - `frontend/src/components/NetworkInterfaces.tsx` (new)
  - `frontend/src/components/NetworkRoutes.tsx` (new)
  - `frontend/src/components/NetworkNeighbors.tsx` (new)
  - `frontend/src/components/NetworkDiagnostics.tsx` (new)
  - `frontend/src/components/NetworkDiagnostics.css` (new)
  - `frontend/src/api/routing.ts` (add network API calls)
  - `frontend/src/types/routing.ts` (add network types)
  - `frontend/src/App.tsx` (integrate NetworkDiagnostics)
- **Depends On**: TASK-301
- **Acceptance Criteria**: ✅ Met
  - Tabbed UI: All / Interfaces / Routes / Neighbors
  - Each tab shows real data from backend with loading/error/empty states
  - Tables with sortable columns, proper formatting
  - Collection metadata (timestamp, command, duration)
  - Types matching FastAPI models exactly
  - Frontend builds clean, TypeScript clean
- **Verification**: ✅ Passed
  ```bash
  cd frontend && npm run build && npx tsc --noEmit
  # ✅ Build passes, TypeScript clean
  ```

---

## Phase 4 (Autonomous Phase 2): Connectivity & Path Diagnostics — **IN PROGRESS**

### TASK-401: DNS Resolution Endpoint
- **Owner**: Backend
- **Status**: ✅ **Done**
- **Files**: 
  - `backend/app/network_collector.py` (added `resolve_dns()` method)
  - `backend/app/main.py` (added `POST /network/dns-resolve` endpoint)
  - `backend/tests/test_network_collector.py` (added `TestDnsResolution` with 9 tests)
- **Depends On**: TASK-301, TASK-302
- **Acceptance Criteria**: ✅ Met
  - `POST /network/dns-resolve` with `{hostname}` returns `{addresses: [], latency_ms}`
  - Handles timeouts, NXDOMAIN, SERVFAIL
  - Uses `asyncio.getaddrinfo()` with `asyncio.wait_for()` timeout
  - Supports both IPv4 (A) and IPv6 (AAAA) records via `ipv6` option
  - Returns proper HTTP status codes: 200 (success), 400 (invalid input), 404 (NXDOMAIN), 408 (timeout), 500 (other errors)
- **Verification**: ✅ Passed
  ```bash
  cd backend && source .venv/bin/activate && python -m pytest tests/test_network_collector.py::TestDnsResolution -v
  # 9 passed
  cd backend && source .venv/bin/activate && python -m pytest -q
  # 109 passed
  curl -X POST http://localhost:8000/network/dns-resolve -H "Content-Type: application/json" -d '{"hostname":"google.com"}'
  # Returns addresses, latency_ms, error=null
  curl -X POST http://localhost:8000/network/dns-resolve -H "Content-Type: application/json" -d '{"hostname":"invalid.invalid","timeout":2}'
  # Returns error with NXDOMAIN
  ```

### TASK-402: Connectivity Check Endpoint
- **Owner**: Backend
- **Status**: ✅ **Done**
- **Files**: 
  - `backend/app/network_collector.py` (added `check_connectivity()`, `_icmp_ping()`, `_tcp_connect()` methods, `ConnectivityResult` dataclass)
  - `backend/app/main.py` (added `POST /network/connectivity` endpoint with Pydantic models)
  - `backend/tests/test_network_collector.py` (added `TestConnectivityCheck` with 11 tests)
- **Depends On**: TASK-301, TASK-302
- **Acceptance Criteria**: ✅ Met
  - `POST /network/connectivity` with `{target, port?, protocol?}` returns `{reachable, latency_ms, error?}`
  - Supports ICMP ping (via system `ping` command) and TCP connect (via `asyncio.open_connection`)
  - Configurable timeout (default 5s, min 0.5s, max 30s)
  - ICMP: count (1-10), interval (0.1-5.0s), returns packet stats and RTT
  - TCP: requires port, resolves target, tries each resolved address, returns latency
  - Returns proper HTTP status codes: 200 (success), 400 (invalid input), 408 (timeout), 500 (other errors)
- **Verification**: ✅ Passed
  ```bash
  cd backend && source .venv/bin/activate && python -m pytest tests/test_network_collector.py::TestConnectivityCheck -v
  # 11 passed
  cd backend && source .venv/bin/activate && python -m pytest -q
  # 120 passed
  curl -X POST http://localhost:8000/network/connectivity -H "Content-Type: application/json" -d '{"target":"google.com","protocol":"tcp","port":80}'
  # Returns reachable=true, latency_ms, error=null
  curl -X POST http://localhost:8000/network/connectivity -H "Content-Type: application/json" -d '{"target":"8.8.8.8","protocol":"icmp"}'
  # Returns reachable=true, latency_ms, packets_sent/received, RTT stats
  ```

### TASK-403: Traceroute Endpoint
- **Owner**: Backend
- **Status**: ✅ **Done**
- **Files**: 
  - `backend/app/network_collector.py` (added `trace_route()` method, `TracerouteHop`, `TracerouteResult` dataclasses, `_parse_traceroute_output()`)
  - `backend/app/main.py` (added `POST /network/traceroute` endpoint with Pydantic models)
  - `backend/tests/test_network_collector.py` (added `TestTraceroute` with 9 tests)
- **Depends On**: TASK-301, TASK-302
- **Acceptance Criteria**: ✅ Met
  - `POST /network/traceroute` with `{target, max_hops?, timeout_per_hop?, probes_per_hop?, overall_timeout?}` returns hop list
  - Each hop: `{ttl, address, hostname?, rtt_ms?, error?}`
  - Max 30 hops (configurable up to 64), per-hop timeout (configurable)
  - Probes per hop (1-3), overall timeout (5-300s)
  - Clear label in response: hops are "Responding Layer 3 hops - not necessarily physical devices"
  - Uses `traceroute -n -w timeout -q probes -m max_hops` subprocess (per RD-007)
  - Handles missing binary, timeout, permission errors, malformed output, unreachable destinations
  - Returns partial results when appropriate
  - Labels each hop with evidence; unknown hops not fabricated
- **Verification**: ✅ Passed
  ```bash
  cd backend && source .venv/bin/activate && python -m pytest tests/test_network_collector.py::TestTraceroute -v
  # 9 passed
  cd backend && source .venv/bin/activate && python -m pytest -q
  # 129 passed
  curl -X POST http://localhost:8000/network/traceroute -H "Content-Type: application/json" -d '{"target":"8.8.8.8","max_hops":5}'
  # Returns 503 if traceroute not available, or hop list if available
  ```

### TASK-404: Frontend Connectivity Panel
- **Owner**: JourneyUI
- **Status**: ✅ **Done** (component exists; full UI wiring still pending)
- **Files**: 
  - `frontend/src/components/ConnectivityPanel.tsx` (new)
  - `frontend/src/api/routing.ts` (add connectivity API calls)
  - `frontend/src/components/NetworkDiagnostics.tsx` (integrate)
- **Depends On**: TASK-401, TASK-402, TASK-403

---

## Phase 6: Scenario Engine & Security Hardening — ✅ **COMPLETE**

### TASK-601: Scenario Engine (backend)
- **Owner**: RouteCore
- **Status**: ✅ **Done**
- **Branch**: `integration/baseline-2026-10-20`
- **Files**:
  - `backend/app/scenario.py` (new) — Scenario/Node/Iface/Route/Link/Hop/TraceResult models, `lookup()`, `trace()`
  - `backend/app/scenarios_data.py` (new) — 5 scenarios: client-router-server, two-routers, loop, dual-stack, ipv6-only
  - `backend/app/lab_builder.py` (new) — namespace command generation, dry-run, root guard, probe
  - `backend/app/scenario_routes.py` (new) — `/api/scenarios/*` endpoints
  - `backend/tests/test_scenario.py` (new) — 32 tests
  - `backend/tests/test_scenario_api.py` (new) — 16 API tests
- **Acceptance Criteria**: ✅ Met
  - One Scenario drives both the simulator and the lab builder
  - Longest-prefix match, metric tiebreak, connected routes
  - Outcomes: delivered, no_route, loop, unresolved_next_hop, not_forwarding, max_hops
  - IPv4 and IPv6 never mix
  - Route editing works on a copy; the shared registry is never mutated
  - Lab commands are argument lists, never shell strings
  - `compare` reports `agree: null` when the lab is unavailable; nothing is faked
- **Verification**: ✅ Passed
  ```bash
  cd backend && source .venv/bin/activate && python -m pytest tests/test_scenario.py -v
  # 31 passed, 1 skipped (root-only sim-vs-lab)
  cd backend && source .venv/bin/activate && python -m pytest tests/test_scenario_api.py -v
  # 16 passed
  ```

### TASK-602: Diagnostic Security Hardening (backend)
- **Owner**: PacketLab
- **Status**: ✅ **Done**
- **Files**:
  - `backend/app/security.py` (new) — `validate_target()`, `RateLimiter`
  - `backend/app/main.py` — CORS allowlist, validation + rate limiting on diagnostic endpoints
  - `backend/app/network_collector.py` — `--` separator before ping/traceroute targets
  - `backend/tests/test_security.py` (new) — 42 tests
  - `backend/tests/test_diagnostic_security.py` (new) — 17 tests
  - `backend/pytest.ini` (new) — asyncio fixture loop scope
- **Acceptance Criteria**: ✅ Met
  - Targets that look like options (`-oProxy`) or contain shell metacharacters are rejected with 400
  - Rate limiting returns 429 with `Retry-After`
  - CORS is an explicit localhost allowlist, not `*`
  - `ping` and `traceroute` receive `--` before the target
- **Verification**: ✅ Passed
  ```bash
  cd backend && source .venv/bin/activate && python -m pytest tests/test_security.py tests/test_diagnostic_security.py -v
  # 59 passed
  ```

### TASK-603: Small Cleanups
- **Owner**: QA/TestPilot
- **Status**: ✅ **Done**
- **Files**:
  - `backend/app/lab_adapter.py` — `datetime.now(timezone.utc)` instead of deprecated `utcnow()`
  - `backend/tests/test_network_collector.py` — `MagicMock` for the synchronous `close()` call
  - `backend/pytest.ini` — `asyncio_default_fixture_loop_scope = function`
- **Verification**: ✅ Full suite runs with **zero warnings**

---

## Phase 7: Scenario Frontend — ✅ **COMPLETE**

### TASK-701: Scenario Picker + Trace UI
- **Owner**: JourneyUI
- **Status**: ✅ **Done**
- **Files**: `frontend/src/components/ScenarioJourney.tsx`, `frontend/src/components/ScenarioJourney.css`, `frontend/src/api/routing.ts`, `frontend/src/types/routing.ts`
- **Acceptance Criteria**: ✅ Met
  - Scenario picker loads the network list from `/api/scenarios`
  - Source device and destination IP selection
  - Step forward, step back, start and replay controls
  - Each hop shows the selected route, prefix length, next hop, interface, metric and source
  - Routes that matched but lost are listed, so the choice is explainable
  - Loading, empty and error states handled
- **Verification**: ✅ Verified live through the Vite proxy

### TASK-702: Provenance Badges + Compare-with-Lab Panel
- **Owner**: JourneyUI
- **Status**: ✅ **Done**
- **Files**: `frontend/src/components/ProvenanceBadge.tsx`, `frontend/src/components/ComparePanel.tsx`, `frontend/src/components/ComparePanel.css`
- **Acceptance Criteria**: ✅ Met
  - Provenance badge on every result, with an explanation of each label
  - Prediction and reality shown side by side
  - When the lab is unavailable, no agreement verdict is invented
  - A disagreement is called out as worth investigating
- **Verification**: ✅ Verified live; `agree: null` with an honest reason when the lab is unprivileged

### TASK-703: Evidence-Based Topology Map
- **Owner**: JourneyUI
- **Status**: ✅ **Done**
- **Files**: `backend/app/topology.py`, `backend/tests/test_topology.py`, `frontend/src/components/TopologyGraph.tsx`, `frontend/src/components/TopologyGraph.css`
- **Acceptance Criteria**: ✅ Met
  - Observed host data and simulated scenario data are never merged
  - Interfaces, routes and neighbours are observed; links between them are inferred
  - Scenario devices and links are simulated
  - Every node and edge carries its own provenance
  - No devices or links invented to fill gaps
- **Verification**: ✅ 8 tests pass; verified live against real host data

### TASK-704: Route Editing That Changes the Simulation
- **Owner**: RouteCore + JourneyUI
- **Status**: ✅ **Done**
- **Files**: `backend/app/scenario_routes.py`, `backend/tests/test_scenario_api.py`, `frontend/src/components/RouteEditor.tsx`, `frontend/src/components/RouteEditor.css`, `frontend/src/App.tsx`
- **Acceptance Criteria**: ✅ Met
  - Routes can be listed, changed, added and removed
  - A saved edit is kept in a workspace, not written into the shared scenario
  - The next trace uses the edited routes
  - The shared scenario is unchanged
  - Invalid edits are rejected with a clear message
- **Verification**: ✅ Verified live: the router switched from `10.0.0.0/24 (connected)` to `10.0.0.2/32 (static, metric 5)` after the edit

---

## Phase 8: Learning Lab — ✅ **COMPLETE**

### TASK-801: Guided Exercises
- **Owner**: JourneyUI + RouteCore
- **Status**: ✅ **Done**
- **Files**: `backend/app/exercises.py`, `backend/app/exercise_checks.py`, `backend/tests/test_exercises.py`, `frontend/src/components/LearningLab.tsx`, `frontend/src/components/LearningLab.css`
- **Acceptance Criteria**: ✅ Met
  - 7 exercises, each following the six-part teaching pattern
  - Longest-prefix, default route, missing route, routing loop, changing a route, metric tiebreak, IPv6 separation
  - Each exercise is verified by running the real engine, not by comparing typed text
  - The edit exercises apply a suggested route for real and re-check
  - The engine's traced hops are shown so the answer is inspectable
- **Verification**: ✅ 19 tests pass; verified live through the Vite proxy

---

## Phase 9: Authorized Host Discovery — ✅ **COMPLETE**

### TASK-901: Scoped Discovery
- **Owner**: Backend + JourneyUI
- **Status**: ✅ **Done**
- **Files**: `backend/app/discovery.py`, `backend/app/discovery_routes.py`, `backend/tests/test_discovery.py`, `backend/tests/test_discovery_api.py`, `frontend/src/components/DiscoveryPanel.tsx`, `frontend/src/components/DiscoveryPanel.css`
- **Acceptance Criteria**: ✅ Met
  - Scope is validated before anything is sent; a network over 1024 addresses is refused
  - The operator previews the exact address list, then types the target back to confirm
  - Without a matching confirmation the scan is refused with 403 and nothing is probed
  - Probes are rate limited, bounded in count, and cancellable
  - Every request including refusals is written to an audit trail shown in the UI
  - A scan where nothing answers reports zero hosts, which is a real result
  - The address is passed after `--` so it cannot be read as a command option
- **Verification**: ✅ 24 tests pass; verified live — a local /29 scan found the real gateway at 192.168.0.1

### TASK-902: Discovery UI
- **Owner**: JourneyUI
- **Status**: ✅ **Done**
- **Acceptance Criteria**: ✅ Met
  - Authorization notice before the form
  - Scope preview listing the addresses that would be probed
  - Confirmation step that must quote the target back
  - Results table, an honest empty state, and the audit trail
  - The host's own network offered as a starting point
- **Depends On**: TASK-901

---

## Phase 5 (Autonomous Phase 3): Authorized Host Discovery — **PENDING**

### TASK-501: Subnet Host Discovery
- **Owner**: Backend
- **Status**: ⏳ **Pending**
- **Files**: `backend/app/network_collector.py`, `backend/app/main.py`

### TASK-502: Scope Validation & Authorization UI
- **Owner**: JourneyUI
- **Status**: ⏳ **Pending**

---

## Phase 6 (Autonomous Phase 4): Evidence-Based Topology Map — **PENDING**

### TASK-601: Evidence Model & API
- **Owner**: Backend
- **Status**: ⏳ **Pending**

### TASK-602: Interactive Topology Graph
- **Owner**: JourneyUI
- **Status**: ⏳ **Pending**

---

## Phase 7 (Autonomous Phase 5): PCAP & Equipment — **PENDING**

---

## Phase 8 (Autonomous Phase 6): Final Verification — **PENDING**

---

## Current Blockers — **NONE**

---

## Next Immediate Actions

**Phase 4 (Connectivity & Path Diagnostics) - TASK-401 & TASK-402 Complete:**

**Ready for TASK-403 (Traceroute Endpoint):**
1. TASK-403: Traceroute Endpoint
2. TASK-404: Frontend Connectivity Panel
---

## Phase 10: Five-Agent Parallel Round — ✅ **COMPLETE**

Distributed across the five existing agents, each in its own worktree and
branch, merged one at a time with the checks run after each merge.

| Task ID | Agent | Branch | Outcome |
|---------|-------|--------|---------|
| TASK-1001 | RouteCore | `feature/routing-table-api` | ✅ Editable, authoritative routing table |
| TASK-1002 | PacketLab | `feature/lab-verification` | ✅ Lab command sequence verified, hardened |
| TASK-1003 | Autonomous Eng | `feature/pcap-backend` | ✅ PCAP importer backend |
| TASK-1004 | JourneyUI | `feature/pcap-ui` | ✅ PCAP panel, interactive topology graph |
| TASK-1005 | TestPilot | `feature/browser-e2e-expansion` | ✅ Wider browser coverage |

### TASK-1001: Editable Routing Table ✅
- `GET /routes` returns the live table; `GET /lookup` uses it
- `POST /routes`, `PUT /routes/{index}`, `DELETE /routes/{index}`, `POST /routes/reset`
- `GET /routes/summary` — counts, longest prefix, lowest metric
- Validated: an added route changes the lookup result; reset restores it
- Guarded by a lock; bulk replace is atomic

### TASK-1002: Packet Lab Verification ✅
- Command sequence verified command by command for all five scenarios
- A failing command now reports its index and stderr
- Teardown is idempotent; a missing namespace is not an error
- The probe distinguishes timeout, missing binary, permission failure and unreachable host
- A route whose next hop is off the outgoing network is rejected when the commands are built
- Audit written up in `docs/lab-command-audit.md`

### TASK-1003: PCAP Importer Backend ✅
- Classic PCAP parsed with the standard library only, in memory
- **Byte-order bug found and fixed during integration**: the parser read the
  magic as a little-endian integer and treated the value as the byte order,
  which swaps every real file. Now detected from the raw bytes.
- PCAPNG detected and reported as unsupported rather than mis-parsed

### TASK-1004: PCAP Panel and Interactive Topology ✅
- File read and encoded in the browser, sent only to this app's backend
- 32 MB limit enforced before encoding
- The limitations are shown with the result
- The topology is an SVG graph with observed, inferred, simulated and
  unknown visually distinct, clickable and keyboard reachable

### TASK-1006: Real Routing Table Analysis
- **Owner**: Autonomous Engineering
- **Branch**: `feature/real-route-analysis`
- **Status**: 🔄 In progress
- **Objective**: apply the existing, already-tested `routing_logic.lookup_route()` to the
  *real* host routing table, so the measured data teaches something. Report the route
  that would win and the candidates it beat, flag shadowing, use
  `ipaddress.collapse_addresses()` to show what a default route stands in for, and
  mark the conclusion as **inferred**, never observed.

### TASK-1007: Deeper Capture Analysis
- **Owner**: RouteCore
- **Branch**: `feature/pcap-depth`
- **Status**: 🔄 In progress
- **Objective**: extract transport ports, TCP flags and the three-way handshake, ICMP
  type, DNS query names and answers, and ARP hardware addresses. Optionally parse
  PCAPNG. Everything derived stays marked **inferred**.

---

## Decisions Taken

### DEC-001: The `agent/routing-backend` trace implementation is superseded
- **Context**: `agent/routing-backend` holds commit `f370273`, an earlier
  implementation of packet tracing as `GET /trace` with `TraceHop` and
  `PacketTraceResult`.
- **Finding**: It has the same capabilities as the current
  `POST /packet-journey`: longest-prefix selection, loop detection, and a
  `max_hops` limit. The current implementation supersedes it and adds
  multi-router scenarios, IPv6, route editing, an evidence-based topology,
  and engine-verified exercises.
- **Decision**: Keep the branch as it is; do not merge it. It is superseded,
  not lost. Merging it would duplicate the feature and add a second,
  inconsistent trace endpoint.
- **Action**: The branch may be archived once the operator approves.

### DEC-005: Two more defects found by agent review, both fixed
- **Context**: the Autonomous Engineering agent audited the merged code and
  reported an orphaned `@app.get("/routes")` decorator with no function under it,
  and a duplicated `ipaddress` import.
- **Finding**: both confirmed before acting. The orphan decorator bound the
  interfaces handler a second time at `/routes`; the first registration still won
  at runtime, but the OpenAPI schema advertised `GET /routes` as "Get
  Interfaces". The duplication was in `routing.py` as well as `routing_logic.py`.
- **Decision**: both fixed. The OpenAPI now correctly reports `list_routes`.

### DEC-003: A wrong agent finding is checked, not obeyed
- **Context**: The PacketLab agent reported that the lab's route commands
  would fail because `10.0.0.1/24` and `10.0.0.2/24` are "different
  networks". They are both in `10.0.0.0/24`.
- **Finding**: The agent's *code* was right; its *report* was wrong. The
  scenario data was fine and changing it would have broken the lab.
- **Decision**: Checked the claim before acting, sent it back with the
  correction, and the audit now says all commands are OK.

### DEC-004: The PCAP byte order was fixed during integration, not by the agent
- **Context**: The agent's own tests built a file with big-endian magic
  bytes and a little-endian body — a file no tool produces — so their
  tests agreed with their code while every real capture failed.
- **Finding**: A real capture written by tcpdump on this machine did not
  parse. The magic was read as a little-endian integer and the resulting
  value was treated as the byte order, which inverts it for every file.
- **Decision**: Fixed in integration, with the agent's test helper
  corrected to build genuine files in each byte order, and three new
  tests covering real little-endian, real big-endian and nanosecond files.

### DEC-002: `main` stays protected
- **Context**: All work since the baseline is on
  `integration/baseline-2026-10-20`.
- **Decision**: `main` remains at `03f347b` until the operator approves
  the integration branch.
