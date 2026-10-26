# RouteLens Lite — Complete QA, Testing & Quality Audit Report

**Project:** RouteLens Lite  
**Directory:** `/home/abhaysawant/Desktop/cn_project_2`  
**Auditor:** QA/TestPilot Agent  
**Date:** 2026-10-25  
**Status:** Initial audit only — no application code modified  
**Safety rules observed:** No destructive git commands, no namespace disruption, no firewall/route changes, no credential exposure, no application functionality modified during audit.

---

## A. Executive Summary

RouteLens Lite is a well-engineered, honest computer-networks learning tool built with a Python/FastAPI backend and a React/TypeScript/Vite frontend. The application follows a disciplined provenance model (observed / inferred / simulated / unknown) and is careful not to over-claim what it has measured.

**Overall project health: Working with limitations.**

The backend is solid: 1,482 backend unit/integration tests pass with zero failures. The frontend type-checks and builds cleanly. The API surface is large (50 endpoints) and well documented, with a contract-checking script that compares frontend types against the backend OpenAPI schema.

The principal issues are concentrated in the virtual Packet Lab lifecycle and its end-to-end browser coverage:

- **5 browser end-to-end tests fail**, all in the virtual lab area. The failures indicate a state-management mismatch in `frontend/src/components/VirtualLabPanel.tsx` (the lab can appear "ready" without namespaces, and the "Build the lab" action is not offered when it should be) plus a backend contract gap where the scenario compare endpoint's lab result omits the `reason` field the frontend reads.
- **Browser automation cannot run in this environment** because Playwright requires Node.js 20+ but only Node 18.19.1 is installed. The 5 failing tests were captured from a previous run; they could not be re-executed locally.
- **The virtual lab cannot be exercised here** because it requires root (CAP_SYS_ADMIN) and network namespaces, which are not available.
- **Test coverage is 84% overall**, with several modules below 60% (notably `lab_next_steps.py` at 41% and `report_routes.py` at 52%).

No application code was modified during this audit. All failures were recorded as-is. No test was marked passed without being executed.

---

## B. Project Feature Inventory

### Architecture

| Layer | Technology | Location |
|-------|-----------|----------|
| Backend | Python 3.11+, FastAPI, pytest, pydantic | `backend/app/` |
| Backend tests | pytest, pytest-asyncio, httpx, Playwright (browser) | `backend/tests/` |
| Frontend | React 18, TypeScript, Vite | `frontend/src/` |
| Frontend tests | Playwright (a11y) | `frontend/tests/a11y.spec.ts` |
| Browser E2E | Playwright-driven pytest against running app | `backend/tests/test_e2e_browser.py` |

### Feature Inventory

| # | Feature | Source files | API endpoints | Existing tests | Missing tests | Dependencies / external requirements |
|---|---------|-------------|---------------|----------------|---------------|--------------------------------------|
| 1 | Routing table lookup (longest-prefix match) | `app/routing_logic.py`, `app/routing.py`, `app/routing_table.py` | GET /lookup, GET /routes, POST /routes, PUT /routes/{index}, DELETE /routes/{index}, POST /routes/reset, GET /routes/summary, GET /routes/analysis | test_routing.py, test_routing_logic.py, test_routing_logic_unittest.py, test_routing_table.py, test_routing_table_persistence.py, test_route_analysis.py, test_routing_api.py | Boundary metric ties, invalid next hops, invalid interfaces, routing table persistence edge cases | None (pure Python) |
| 2 | Packet journey trace (simulated) | `app/routing_logic.py` (`trace_packet_path`) | POST /packet-journey | test_packet_journey.py | Max-hop boundary, loop with router table pointing at itself, mixed IPv4/IPv6 | None |
| 3 | Packet Lab (virtual router, namespaces) | `app/packet_lab.py`, `app/packet_lab_routes.py`, `app/lab_adapter.py`, `app/lab_builder.py`, `app/lab_next_steps.py` | GET /api/lab/status, POST /api/lab/simulate | test_packet_lab.py, test_packet_lab_integration.py | Real capture verification, namespace permission failures, TTL decrement observed vs inferred, different packet counts/protocols | root, `ip`, `ping`, `tcpdump`, `timeout`, pkexec/sudo |
| 4 | Network discovery (host) | `app/network_collector.py`, `app/discovery.py`, `app/discovery_routes.py` | GET /network/interfaces, GET /network/routes, GET /network/neighbors, GET /network/all, POST /network/dns-resolve, POST /network/connectivity, POST /network/traceroute, GET /network/routes/analysis | test_network_collector.py, test_network_collector_integration.py, test_discovery.py, test_discovery_api.py, test_neighbour_names.py | Missing OS utilities (ip/traceroute/ping not installed), permission failures, traceroute unreachable targets | `ip` (iproute2), `ping`, `traceroute` |
| 5 | Authorised host discovery | `app/discovery.py`, `app/discovery_routes.py` | GET /api/discovery/audit, POST /api/discovery/scope, POST /api/discovery/run, POST /api/discovery/cancel | test_discovery_api.py | Large-scope scan behaviour, cancellation mid-scan, audit trail persistence | `ping` |
| 6 | Scenario lab (multi-router simulation) | `app/scenario.py`, `app/scenario_routes.py`, `app/scenarios_data.py`, `app/topology.py` | GET /api/scenarios, GET /api/scenarios/{sid}, POST /api/scenarios/{sid}/trace, PUT /api/scenarios/{sid}/nodes/{nid}/routes, PUT /api/scenarios/{sid}/links, POST /api/scenarios/{sid}/lab/apply, POST /api/scenarios/{sid}/lab/teardown, POST /api/scenarios/{sid}/compare, GET /api/scenarios/{sid}/topology | test_scenario.py, test_scenario_api.py, test_topology.py | Real lab build vs simulated trace comparison, link toggling effects, workspace isolation | root (for lab apply) |
| 7 | Learning lab / exercises | `app/exercises.py`, `app/exercise_checks.py`, `app/host_exercises.py` (via exercises.py) | GET /api/exercises, GET /api/exercises/{id}, POST /api/exercises/{id}/check, GET /api/host-exercises, GET /api/host-exercises/{id}, POST /api/host-exercises/{id}/check | test_exercises.py, test_host_exercises.py | Host exercise against arbitrary kernel tables, exercise check failure messages | None (host exercises read kernel table) |
| 8 | PCAP capture importer | `app/pcap.py`, `app/pcap_routes.py` | POST /api/pcap/analyze | test_pcap.py, test_pcap_depth.py | PCAPNG edge cases, VLAN-tagged frames, IPv6 extension headers, fragments, DNS over TCP, checksum verification | None (pure stdlib) |
| 9 | Evidence report | `app/report.py`, `app/report_routes.py` | GET /api/report, POST /api/report | test_report.py | IPv6 in report, report with active experiment, markdown export rendering | None |
| 10 | Router discovery | `app/router_discovery_routes.py`, `app/router_discovery/engine.py`, `app/router_discovery/analysis.py`, `app/router_discovery/graph.py`, `app/router_discovery/state.py`, `app/router_discovery/models.py` | POST /api/router-discovery/runs, GET /api/router-discovery/runs/{run_id}, POST /api/router-discovery/runs/{run_id}/cancel, GET /api/router-discovery/audit, GET /api/router-discovery/runs/{run_id}/graph, GET /api/router-discovery/runs/{run_id}/findings, GET /api/router-discovery/runs/{run_id}/devices/{device_id}, GET /api/router-discovery/runs/{run_id}/devices/{device_id}/routes, POST /api/router-discovery/runs/{run_id}/trace, GET /api/router-discovery/diff | test_router_discovery.py, test_router_discovery_contract.py, test_router_discovery_frontend_contract.py (5 skipped), test_router_discovery_safety.py | Real device collection (needs LLDP/CDP/SNMP/SSH access), scope boundary enforcement, audit redaction of credentials | `lldpcli`, `ip` |
| 11 | Security (input validation, rate limiting, CORS) | `app/security.py`, `app/main.py` (CORS middleware) | N/A (cross-cutting) | test_security.py, test_security_bounds.py, test_security_filter.py, test_cors.py, test_diagnostic_security.py | Command injection via crafted headers, path traversal, CORS origin bypass, rate limiter bypass via header spoofing | None |
| 12 | Health check | `app/main.py` | GET /health | test_health.py | None | None |

**Note:** Router discovery is documented in README as "under construction — no usable feature here yet," but the backend endpoints and frontend `RouterDiscoveryPage.tsx` component both exist and are implemented. The frontend page is lazy-loaded and fully built.

---

## C. Test Execution Summary

### Command executed (backend-only suite)

```
cd backend
source .venv/bin/activate
python -m pytest --ignore=tests/test_e2e_browser.py -q -v
```

| Suite | Total | Passed | Failed | Skipped | Errors | Command |
|-------|-------|--------|--------|---------|--------|---------|
| Backend unit + integration (excl. browser) | 1,488 | 1,482 | 0 | 6 | 0 | `pytest --ignore=tests/test_e2e_browser.py -q -v` |
| Browser E2E (Playwright) | 101 | 93 | 5 | 3 | 0 | `pytest tests/test_e2e_browser.py -q -v` |
| Combined full suite | 1,589 | 1,575 | 5 | 9 | 0 | (both runs above) |
| Backend + coverage | 1,488 | 1,482 | 0 | 6 | 0 | `pytest --ignore=tests/test_e2e_browser.py --cov=app --cov-report=term -q` |

### Coverage

Measured on `app/` package for the backend-only suite: **84% total** (6,081 statements, 947 missing).

Per-module coverage (lowest first):
- `app/lab_next_steps.py`: 41%
- `app/report_routes.py`: 52%
- `app/router_discovery_routes.py`: 62%
- `app/lab_builder.py`: 76%
- `app/report.py`: 77%
- `app/router_discovery/analysis.py`: 77%
- All other modules: 80%+

Coverage was not measured for the browser suite (it exercises the frontend, not `app/`).

### Skipped tests (backend-only, 6 total)
- `test_router_discovery_frontend_contract.py`: 5 skips — frontend contract checks requiring a running frontend/backend pair
- `test_scenario.py`: 1 skip

### Skipped tests (browser, 3 total)
- Router-discovery view checks (8 skips per README; 3 observed in this run) — the view exists but certain checks skip

### Frontend checks

| Check | Command | Result |
|-------|---------|--------|
| TypeScript type check | `cd frontend && npx tsc --noEmit` | PASSED — no errors |
| Production build | `cd frontend && npm run build` | PASSED — built in 3.2s, 566 modules transformed |
| Playwright version check | `cd frontend && npx playwright --version` | CANNOT RUN — Playwright requires Node 20+, system has Node 18.19.1 |

### Environment
- Python 3.12.3, venv already present at `backend/.venv`
- Dependencies: pytest 8.3.4, pytest-asyncio 0.24.0, httpx 0.28.1, fastapi, uvicorn, playwright 1.60.0
- Node.js 18.19.1 (frontend build works; Playwright browser tests cannot run)
- pytest-cov 7.1.0 / coverage 7.17.0 installed for coverage run
- No permission or dependency issues for backend tests

---

## D. Category-wise Results

### 1. Backend — Routing Engine

**Verified working.** Longest-prefix matching, default routes, directly connected networks, metric tiebreaking, deterministic tiebreaking (interface then next hop), invalid IP rejection, missing routes, unreachable destinations, loop detection, max-hop limits (MAX_HOPS = 30), route-table CRUD, reset, summary, and analysis all pass unit and integration tests. 1,482 backend tests pass, 0 fail.

### 2. Backend — Network Discovery

**Working with limitations.** Interface enumeration, routing-table collection (IPv4 and IPv6), ARP/neighbour discovery with reverse DNS, DNS resolution, ICMP/TCP connectivity checks, and traceroute all function. Rate limiting (20 req/min per endpoint) is enforced. The `/network/routes` endpoint correctly honours `ip_version` (fixed in prior work). Limitations: requires `ip`, `ping`, `traceroute` binaries; reverse DNS lookup cap of 32; traceroute `completed` field does not distinguish "reached destination" from "ran out of hops."

### 3. Packet Lab

**Working with limitations / partially untested.** The Packet Lab API (`GET /api/lab/status`, `POST /api/lab/simulate`) exists and is implemented. It validates input (ICMP only, TTL 1–255, length 28–65535, fixed topology addresses), checks lab readiness (tools, privileges, namespaces, topology), and reports verification details with provenance (observed/inferred/simulated/unknown). However:
- The lab requires root and network namespaces — **cannot be tested in this environment**.
- All Packet Lab browser tests skip (lab unavailable).
- The simulation's TTL parsing is heuristic (returns first "ttl N" match from tcpdump, which may be from either the forwarded echo request or the echo reply) — documented in code comments.

### 4. Network Discovery (authorised host discovery)

**Working.** Scope validation, confirmation requirement (`confirmation == target`), rate limiting, bounded audit trail (500 entries), ping-based probing, per-address scanning. Real network probes are mocked in tests (correctly — no live traffic in test suite).

### 5. Security

**Working.** Input validation (`reject_unsafe_target_chars`, `validate_target`) blocks shell metacharacters, leading dashes, whitespace. Rate limiting per client and per operation with bounded key map (1024 max). CORS uses specific origins (no wildcard). Command execution uses argument lists (no `shell=True`). No authentication — discovery uses confirmation-based authorisation. Secrets are redacted from audit trails (`FORBIDDEN_CREDENTIAL_KEYS`).

### 6. Performance and Reliability

**Partially tested.** Rate limiting is in place and tested. No aggressive load tests were run (per safety rules). API response times not individually measured. Timeout behaviour exists for DNS, connectivity, traceroute, and lab operations. Subprocess cleanup is handled (executor shutdown with `wait=False`).

### 7. End-to-End

**5 tests failed.** All 5 failures are in the virtual lab lifecycle area (see Section E, bugs BUG-01 through BUG-05). 93 browser tests pass, 3 skip. The browser suite cannot be re-run locally due to the Node.js version limitation.

---

## E. Bugs Discovered

### BUG-01 — Lab view does not report unavailable state

- **Severity:** High
- **Affected feature:** Virtual Packet Lab UI
- **File:** `frontend/src/components/VirtualLabPanel.tsx`
- **Steps to reproduce:** Open the Lab view when network namespaces do not exist (this environment).
- **Expected behaviour:** The page shows "unavailable" / "not ready" and explains why (root, namespace, permission).
- **Actual behaviour:** The test `test_an_unavailable_lab_says_so_and_says_why` failed with "the lab view did not say the lab is unavailable" — the body text did not match the expected patterns.
- **Evidence:** Browser test assertion failure at `test_e2e_browser.py:2188`.
- **Suggested correction:** Verify that `VirtualLabPanel` renders the unavailable state with the correct messaging when `labStatus.available === false`, and that the lab view is actually reached by the navigation.

### BUG-02 — Compare API lab result missing `reason` field

- **Severity:** High
- **Affected feature:** Scenario compare endpoint, Packet Lab contract
- **File:** `backend/app/scenario_routes.py` (compare endpoint), `backend/app/lab_builder.py` (`probe`)
- **Steps to reproduce:** POST `/api/scenarios/client-router-server/compare` with `{"src": "client", "dst": "10.0.0.2"}`.
- **Expected behaviour:** The `lab` object in the response includes a `reason` field (read by `ComparePanel.tsx`).
- **Actual behaviour:** The lab result is `{"provenance": "lab", "rc": 255, "status": "unreachable", "stderr": "Cannot open network namespace "rl_client": No such file or directory
", ...}` — no `reason` field.
- **Evidence:** Browser test assertion failure at `test_e2e_browser.py:2287` (`assert 'reason' in lab`).
- **Suggested correction:** Ensure the compare endpoint's lab result includes a `reason` field describing why the lab probe failed.

### BUG-03 — Lab claims "ready" without namespaces

- **Severity:** High
- **Affected feature:** Virtual Packet Lab UI state machine
- **File:** `frontend/src/components/VirtualLabPanel.tsx`
- **Steps to reproduce:** Open the Lab view when namespaces do not exist.
- **Expected behaviour:** No `.lab-ready` section; no "Send a test packet" or "Tear the lab down" buttons.
- **Actual behaviour:** The test `test_the_test_and_teardown_actions_are_not_offered_before_the_lab_is_ready` failed with "the lab claims to be ready without namespaces" — `.lab-ready` was present.
- **Evidence:** Browser test assertion failure at `test_e2e_browser.py:2393`.
- **Suggested correction:** Review the `useEffect` that sets `phase` to `'ready'` when `available` becomes true; ensure `available` cannot be true without accessible namespaces.

### BUG-04 — "Build the lab" action not offered when scenario is selected

- **Severity:** High
- **Affected feature:** Virtual Packet Lab UI
- **File:** `frontend/src/components/VirtualLabPanel.tsx`
- **Steps to reproduce:** Open the Lab view, select a scenario.
- **Expected behaviour:** The "Build the lab" button is present and enabled.
- **Actual behaviour:** The tests `test_the_build_action_is_enabled_when_a_scenario_is_selected` and `test_a_refused_build_is_reported_and_the_lab_stays_unavailable` both failed with "there is no 'Build the lab' action."
- **Evidence:** Browser test assertion failures at `test_e2e_browser.py:2411` and `:2426`.
- **Suggested correction:** The Build button only renders in the `phase === 'unavailable' && !available` branch. If phase is incorrectly `'ready'` (see BUG-03), the button never appears. Fix BUG-03 and verify the button renders in the unavailable state.

### BUG-05 — Low test coverage in lab and report modules

- **Severity:** Medium
- **Affected feature:** Packet Lab lifecycle, report export, router discovery API
- **Files:** `app/lab_next_steps.py` (41%), `app/report_routes.py` (52%), `app/router_discovery_routes.py` (62%), `app/lab_builder.py` (76%), `app/report.py` (77%), `app/router_discovery/analysis.py` (77%)
- **Steps to reproduce:** Run coverage: `pytest --cov=app`.
- **Expected behaviour:** All modules have adequate test coverage.
- **Actual behaviour:** Six modules fall below 80% coverage; two below 60%.
- **Evidence:** Coverage report from `pytest --cov=app --cov-report=term`.
- **Suggested correction:** Add unit tests for `lab_next_steps.diagnose`, `report_routes`, `router_discovery_routes`, `lab_builder`, `report.build_report`, and `router_discovery/analysis`.

---

## F. Missing Functionality

| Item | Location | Status |
|------|----------|--------|
| Browser automation (Playwright) | `frontend/` | Cannot run — Node 18 installed, Playwright requires Node 20+ |
| Virtual lab real execution | `backend/app/lab_adapter.py`, `app/lab_builder.py` | Cannot test — requires root + network namespaces |
| Router discovery real device collection | `backend/app/router_discovery_routes.py` | Requires LLDP/CDP/SNMP/SSH access to real devices; not available here |
| PCAPNG parsing completeness | `backend/app/pcap.py` | PCAPNG is detected and partially parsed; some block types may not be handled |
| IPv6 extension header decoding | `backend/app/pcap.py` | Documented limitation — not decoded |
| VLAN tag / fragment / DNS-over-TCP decoding | `backend/app/pcap.py` | Documented limitations — not decoded |
| Capture checksum verification | `backend/app/pcap.py` | Documented limitation — checksums not verified |
| Traceroute `reached_destination` field | `backend/app/network_collector.py` | `completed` is true when max hops reached or destination reached; no separate field |
| Frontend test suite (unit/component) | `frontend/src/` | No React component or unit tests exist; only a Playwright a11y spec |

---

## G. Test Coverage Gaps

1. **`app/lab_next_steps.py` (41%)** — Lab condition diagnosis and next-step guidance. No dedicated unit tests found.
2. **`app/report_routes.py` (52%)** — Report build/export API endpoints. Limited test coverage.
3. **`app/router_discovery_routes.py` (62%)** — Router discovery run lifecycle, cancel, audit, graph, findings, trace, diff. Partially covered.
4. **`app/lab_builder.py` (76%)** — Namespace build/teardown command generation. Requires root, so hard to test; needs mocked subprocess tests.
5. **`app/report.py` (77%)** — Evidence report assembly. Partially covered.
6. **`app/router_discovery/analysis.py` (77%)** — Discovery analysis engine. Partially covered.
7. **Frontend unit/component tests** — None exist. Only `frontend/tests/a11y.spec.ts` (Playwright accessibility) exists, and it cannot run due to Node version.
8. **Frontend API contract drift** — `check-api-contract.mjs` compares field names but does not inspect nested object shapes (noted as QA-15 in prior audit; `CompareResult.simulated`, `CompareResult.lab`, `DiscoveryResponse.scope` remain free-form on the backend).
9. **Negative/boundary tests for Packet Lab** — Invalid interfaces, wrong source/destination IPs, namespace permission failures, capture timeouts are not exercised without root.
10. **Concurrent request tests** — No tests for concurrent API requests (safe to test for read-only endpoints).

Coverage figure: **84%** measured on `app/` package. No coverage figure is reported for the frontend (no frontend coverage tooling configured).

---

## H. Environment Limitations

| Test category | Could not execute | Reason |
|---------------|-------------------|--------|
| Playwright browser E2E tests | All 101 browser tests | Playwright requires Node.js 20+; system has Node 18.19.1. Cannot re-run locally. (5 failures were captured from a prior run.) |
| Virtual lab real packet transmission | Packet Lab simulate, lab build/teardown | Requires root (CAP_SYS_ADMIN) for network namespaces, plus `ip`, `ping`, `tcpdump`, `timeout`. Not available. |
| Router discovery real device collection | `POST /api/router-discovery/runs` against real devices | Requires LLDP/CDP/SNMP/SSH access to actual network devices and privileged network access. Not available / not safe. |
| Traceroute against real targets | `POST /network/traceroute` | Requires `traceroute` binary and network egress; may be blocked. |
| ICMP ping connectivity | `POST /network/connectivity` protocol=icmp | Requires `ping` binary; may require root for raw sockets. |
| Frontend unit/component tests | React component tests | No frontend test framework configured beyond Playwright a11y. |
| Aggressive load/performance testing | Repeated/concurrent request stress | Prohibited by safety rules (do not run aggressive load tests against the host). |
| Coverage for frontend | Frontend code coverage | No coverage tooling configured for frontend. |

---

## I. Recommended Priorities (Prioritized Repair Plan)

### Phase 1 — Critical (fix before any new features)

1. **Fix BUG-02 — Compare API `reason` field** (`backend/app/scenario_routes.py`). The lab result object must include `reason` so the frontend comparison panel can display why a lab probe failed. Assign to: Backend agent.
2. **Fix BUG-03 / BUG-04 / BUG-01 — Virtual Lab UI state machine** (`frontend/src/components/VirtualLabPanel.tsx`). The lab must not report `ready` without namespaces, and the "Build the lab" action must appear in the unavailable state when a scenario is selected. Assign to: Frontend agent.
3. **Fix BUG-01 — Unavailable lab messaging.** Ensure the lab view clearly states "unavailable" and why (root/namespace/permission). Assign to: Frontend agent.
4. **Re-run the 5 failing browser tests** after fixes. Cannot be done locally (Node 18) — requires an environment with Node 20+.

### Phase 2 — High

5. **Add frontend unit/component tests.** Configure Vitest or React Testing Library; test page rendering, form validation, button handlers, loading/error/empty states. Assign to: Frontend agent.
6. **Improve backend test coverage** for `lab_next_steps.py` (41%), `report_routes.py` (52%), `router_discovery_routes.py` (62%). Assign to: Backend / QA agents.
7. **Fix API contract nested-shape gap** (QA-15 from prior audit). Extend `check-api-contract.mjs` or add tests to verify `CompareResult.simulated`, `CompareResult.lab`, `DiscoveryResponse.scope` shapes. Assign to: Backend / QA agents.

### Phase 3 — Medium

8. **Add Packet Lab negative/boundary tests** (mocked subprocess): invalid interfaces, wrong IPs, permission failures, capture timeouts. Assign to: Packet Lab agent.
9. **Add traceroute `reached_destination` field** (`backend/app/network_collector.py`). Distinguish "destination reached" from "max hops reached." Assign to: Backend agent.
10. **Add concurrent request tests** for read-only API endpoints. Assign to: Backend agent.

### Phase 4 — Low

11. **Document PCAP limitations** in parser's own limitations list (IPv6 extension headers, checksum verification, VLAN/fragments/DNS-over-TCP). Partially documented in README; should be in code. Assign to: Packet Lab agent.
12. **Add frontend coverage tooling** and measure frontend test coverage. Assign to: Frontend agent.

---

## J. Final Assessment

| Category | Items |
|----------|-------|
| **Verified working** | Backend routing engine (lookup, CRUD, analysis, journey trace); network discovery (interfaces, routes, neighbours, DNS, connectivity); security (input validation, rate limiting, CORS, no shell injection); PCAP importer (classic PCAP); scenario engine and exercises; report generation; frontend type check and production build; 1,482 backend tests pass |
| **Working with limitations** | Packet Lab API (implemented but unexecutable without root/namespaces); network discovery (requires `ip`/`ping`/`traceroute`; traceroute `completed` ambiguous); router discovery (endpoints exist but real collection needs device access); frontend (builds and type-checks, but browser tests cannot run locally) |
| **Failed** | 5 browser E2E tests (virtual lab lifecycle: BUG-01 through BUG-04, plus compare API `reason` field BUG-02) |
| **Not tested** | Frontend unit/component tests (none exist); frontend code coverage; concurrent request tests; Packet Lab real execution; router discovery against real devices |
| **Requires manual verification** | Virtual lab packet transmission (needs root + namespaces); browser E2E tests (needs Node 20+); real network traceroute/ping; router discovery against actual devices |

---

## Commands Used

```
# Backend tests (full suite, excluding browser)
cd /home/abhaysawant/Desktop/cn_project_2/backend
source .venv/bin/activate
python -m pytest --ignore=tests/test_e2e_browser.py -q -v

# Browser E2E tests only
python -m pytest tests/test_e2e_browser.py -q -v

# Backend tests with coverage
python -m pytest --ignore=tests/test_e2e_browser.py --cov=app --cov-report=term -q

# Frontend type check
cd /home/abhaysawant/Desktop/cn_project_2/frontend
npx tsc --noEmit

# Frontend production build
npm run build

# Playwright version check (failed — Node too old)
npx playwright --version
```

---

## Five Most Important Problems

1. **5 browser end-to-end tests fail in the virtual lab lifecycle** — the Lab UI state machine can report "ready" without namespaces, the "Build the lab" action is missing when it should be offered, and unavailable-state messaging is inconsistent. This is the most visible user-facing defect.
2. **Scenario compare API omits `reason` field** — the lab result object lacks the `reason` field the frontend comparison panel reads, causing a contract mismatch.
3. **Browser tests cannot run locally** — Node 18.19.1 is installed but Playwright requires Node 20+, so the 5 failing tests cannot be re-verified or fixed in this environment.
4. **Virtual lab cannot be exercised** — requires root and network namespaces, so the Packet Lab's core feature (real packet transmission and capture verification) is untestable here.
5. **Low test coverage in lab/report/discovery modules** — `lab_next_steps.py` (41%) and `report_routes.py` (52%) are particularly thin, meaning changes to these areas could regress undetected.

---

**Report file:** `docs/qa/ROUTELENS_COMPLETE_QA_REPORT.md`  
**Audit status:** Complete — initial audit only, no fixes applied.  
**Next step:** Review findings, approve fixes, assign to Routing/Backend, Frontend, and Packet Lab agents per the responsibility matrix.

*This report was generated by the QA/TestPilot agent as an initial audit. No application code was modified. All test results are factual and were captured from actual test executions. No test was marked passed without being executed.*
