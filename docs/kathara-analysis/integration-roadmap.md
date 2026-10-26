# RouteLens Lite × Kathará — Integration Roadmap

**Project:** RouteLens Lite × Kathará analysis
**Author:** MAIN AGENT (Manager and Integration Lead)
**Sources:** Six analysis reports in `docs/kathara-analysis/`:
- `routing-backend.md` (AGENT 1)
- `frontend-integration.md` (AGENT 2)
- `packet-lab.md` (MAIN AGENT)
- `testing-and-validation.md` (AGENT 4)
- `architecture-and-optimization.md` (MAIN AGENT)
- `data-trust-audit.md` (MAIN AGENT)

**Constraint:** READ-ONLY investigation phase complete. No production files modified by this roadmap. Implementation is a separate phase requiring approval.

---

## 1. What Currently Works

| Area | Status | Evidence |
|---|---|---|
| Backend API | Running | `backend/app/main.py:1-986`, `/health` returns 200 |
| Longest-prefix match | Implemented, tested | `backend/app/routing_logic.py:17-452`, `test_routing_logic.py` |
| Editable routing table | Implemented, persisted | `backend/app/routing_table.py:39-279` |
| Simulated packet journey | Implemented | `backend/app/routing_logic.py:208` (`trace_packet_path`) |
| Real host network collection | Implemented (`ip -j`) | `backend/app/network_collector.py:1-1438` |
| Diagnostic endpoints (DNS, connectivity, traceroute) | Implemented, validated, rate-limited | `main.py:680-979`, `security.py` |
| Packet lab (namespaces, veth, ping probe) | Implemented, dry-run safe | `backend/app/lab_builder.py:1-373` |
| Frontend (React/Vite) | Built, type-check clean | `frontend/vite.config.ts`, `tsc --noEmit` passes |
| GitHub Pages base path | Configured | `frontend/vite.config.ts` `base: '/RouteLens-Lite/'` |
| Configurable frontend API URL | Implemented | `frontend/src/api/routing.ts` `VITE_API_URL` |
| Configurable backend CORS | Implemented | `backend/app/main.py` `ROUTELENS_CORS_ORIGINS` |
| CORS tests | Passing | `backend/tests/test_cors.py` — 8 passed |

---

## 2. What Is Genuinely Connected to the Host OS

| Feature | Backend function | System operation | Command |
|---|---|---|---|
| Interfaces | `collect_interfaces()` | `ip -j addr show` | Yes |
| Kernel routes | `collect_routes()` | `ip -j route show` | Yes |
| Neighbors | `collect_neighbors()` | `ip -j neigh show` | Yes |
| DNS resolution | `resolve_dns()` | `asyncio.getaddrinfo()` | Yes |
| Connectivity (ping) | `check_connectivity()` | `ping` / `open_connection` | Yes |
| Traceroute | `trace_route()` | `traceroute` command | Yes |
| Lab apply (namespaces) | `run_all(dry_run=False)` | `ip netns`, `ip link`, `ip addr`, `ip route` | Yes (root) |
| Lab probe | `probe()` | `ip netns exec ping` | Yes (root) |

These are **A. REAL_HOST_DATA** — every result traces to a real system operation.

---

## 3. What Is Simulated

| Feature | Backend function | Data source |
|---|---|---|
| Editable routing table | `RoutingTable` — `routing_table.py:39` | **B** SIMULATED_LAB_DATA (in-memory, JSON-persisted) |
| Route lookup (modelled table) | `lookup_route()` — `routing_logic.py:106` | **C** CALCULATED_DATA from B table |
| Packet journey | `trace_packet_path()` — `routing_logic.py:208` | **C** CALCULATED_DATA from B table |
| Route analysis (modelled) | `analyse_destination()` — `route_analysis.py` | **C** CALCULATED_DATA from B table |
| Scenario trace | `scenario.trace()` — `scenario.py` | **B** SIMULATED_LAB_DATA |
| Packet lab dry-run | `run_all(dry_run=True)` | **B** SIMULATED_LAB_DATA (no commands executed) |

---

## 4. What Is Mocked or Hardcoded

| Item | Location | Lines | Category |
|---|---|---|---|
| `ScenarioTrace.provenance` | `frontend/src/types/routing.ts` | 405 | Hardcoded literal `'simulated'` |
| `ProvenanceBadge` in ScenarioJourney | `frontend/src/components/ScenarioJourney.tsx` | 527 | Hardcoded `provenance="simulated"` |
| Link `is_up` | `frontend/src/components/ScenarioJourney.tsx` | 1066 | From scenario definition only (`link.is_up ?? true`) |
| `SAMPLE_ROUTES` seed data | `backend/app/routing.py` | — | **E** HARDCODED_OR_UNKNOWN (seed only) |
| `MOCK_IPV4_ROUTES`/`MOCK_IPV6_ROUTES`/`MOCK_IPV4_NEIGHBORS` | `backend/tests/conftest.py` | 14-49 | **D** MOCK_OR_FIXTURE_DATA (test only) |
| `mock_environment_network_if_empty` fixture | `backend/tests/conftest.py` | 50 | **D** injected into test path |

---

## 5. What Is Broken or Misleading

| Issue | Location | Severity |
|---|---|---|
| `ScenarioTrace.provenance` hardcoded `'simulated'` | `types/routing.ts:405` | **High** — misrepresents data source even when compared against real lab |
| `ProvenanceBadge provenance="simulated"` hardcoded | `ScenarioJourney.tsx:527` | **High** — UI always shows simulated badge |
| Link `is_up` from scenario only (not real attachment) | `ScenarioJourney.tsx:1066` | **Medium** — link can show UP while lab is torn down |
| Device list shows no real container/namespace status | `VirtualLabPanel.tsx:871-895` | **Medium** — device can be listed while its namespace is gone |
| Scenarios cached without staleness | `App.tsx:157-170` | **Low** — stale scenario data possible |
| No provenance badge on editable routing table rows | `frontend/src/api/routing.ts` + table components | **Medium** — table looks like real kernel table |
| Test conftest mock can mask empty-output bugs | `conftest.py:50` | **Critical** — report-honesty tests may pass with fabricated data |

---

## 6. What Kathará Can Concretely Improve

Kathará is GPL-3.0, Docker-container-based. **No Kathará source code may be copied into RouteLens (MIT).** Improvements are clean-room reimplementations of ideas, or integration at the process/Docker boundary.

| Improvement | Kathará reference | RouteLens gap it fills | Resource |
|---|---|---|---|
| Topology integrity check (`check_integrity`) | `Lab.py:180-193` | No cross-node sequential interface validation | Low |
| Real per-device status (CPU/mem/net) | `DockerMachineStats.py:44-110` | Device list shows no real status | Medium (needs Docker/kathara) |
| Real link attachment state | `DockerLinkStats.py:49` | `link.is_up` from scenario only | Medium (needs Docker/kathara) |
| `observed_at` freshness timestamps | `LinfoCommand.py:114` (refresh) | No staleness on scenarios/traces | Low |

Kathará cannot provide on this dev machine: Docker daemon is not installed and must not be installed per constraints. All Kathará-dependent improvements are **deferred** until a Docker-capable host is available.

---

## 7. Source Files That Could Be Reused (Licence Conditions)

| Kathará file | Licence | Reuse condition | RouteLens use |
|---|---|---|---|
| `model/Lab.py` | GPL-3.0 | **No direct copy.** Clean-room idea only (topology model, `check_integrity`) | Topology integrity check |
| `model/Machine.py` | GPL-3.0 | **No direct copy.** | None (RouteLens namespace model is sufficient) |
| `model/Interface.py` | GPL-3.0 | **No direct copy.** | None |
| `model/Link.py` | GPL-3.0 | **No direct copy.** | None |
| `DockerMachineStats.py` | GPL-3.0 | **No direct copy.** Process-boundary integration only | Real device status (deferred, needs Docker) |
| `IManager.py` | GPL-3.0 | **No direct copy.** Idea only (manager interface) | Abstract `LabBackend` (deferred, premature) |

**Human approval required** before any Kathará-derived code is integrated, even clean-room, to confirm licence compliance.

---

## 8. Highest-Priority Implementation Sequence

Ranked by: (1) correctness/trustworthiness, (2) real network functionality, (3) routing accuracy, (4) Packet Lab, (5) test coverage, (6) performance/maintainability, (7) UI.

| Rank | Improvement | Files to change | Expected behaviour | Dependencies | Test cases | Risks | Best agent | Human approval? |
|---|---|---|---|---|---|---|---|---|
| 1 | Real host-discovery integration test | `backend/tests/test_network_collector_real.py` (new) | Runs `ip -j addr/route/neigh` on host; asserts real data; skips if `ip` absent | `iproute2` (`ip` command) | `test_real_interfaces`, `test_real_routes`, `test_real_neighbors` | None (skip-gated) | AGENT 4 (QA) | No |
| 2 | Real-vs-simulated evidence test | `backend/tests/test_report.py` (extend) | `build_report()` yields ≥1 observed evidence with real command `source` when interfaces exist | None | `test_report_has_observed_evidence` | May surface empty-output bugs (intentional) | AGENT 4 (QA) | No |
| 3 | Scope conftest mock to unit tests only | `backend/tests/conftest.py:50` | Mock injection removed from report-honesty path | None | Existing `test_report.py` must still pass | Regression on hosts with no interfaces | AGENT 4 (QA) | No |
| 4 | `ScenarioTrace.provenance` as union type | `frontend/src/types/routing.ts:402-406`; `backend/app/scenario_routes.py` trace endpoint | `provenance` is `RouteProvenance` union, backend populates based on real/simulated lab | None | `test_trace_provenance_simulated`, `test_trace_provenance_observed` | Type change ripples through `ScenarioJourney`, `ComparePanel` | AGENT 2 (Frontend) | No |
| 5 | Topology integrity check | `backend/app/scenario.py` + `lab_builder.py` | Flags non-sequential interface numbers per node (clean-room `check_integrity`) | None | `test_non_sequential_interfaces_rejected` | Fail-fast on bad topologies (intentional) | AGENT 1 (Routing) | No |
| 6 | Parser/config round-trip tests | `backend/tests/test_scenario_parser.py` (new) | Parses real scenario config files; asserts structure + errors | None | `test_parse_scenario`, `test_parse_invalid` | None | AGENT 4 (QA) | No |
| 7 | Centralised `Settings` dataclass | `backend/app/config.py` (new) | Reads all env vars in one place with defaults/validation | None | `test_settings_defaults`, `test_settings_from_env` | None | AGENT 5 (Architecture) | No |
| 8 | Structured application logging | `backend/app/main.py` + key modules | Logs lab apply/teardown, diagnostic commands, errors via `logging` | None | `test_logging_on_lab_apply` | None | AGENT 5 (Architecture) | No |
| 9 | Provenance badge on editable routing table | `frontend/src/components/` table component | Table rows show `observed`/`simulated` badge | None | Frontend unit test | None | AGENT 2 (Frontend) | No |
| 10 | Scenario staleness detection | `frontend/src/App.tsx:157-170` + `types/routing.ts` | `observed_at` on scenarios; "stale" badge if older than threshold | None | `test_scenario_staleness_badge` | None | AGENT 2 (Frontend) | No |
| 11 | Domain-specific exception types | `backend/app/security.py` + `network_collector.py` | `CommandNotFound`, `PermissionDenied` exceptions | None | `test_command_not_found`, `test_permission_denied` | None | AGENT 5 (Architecture) | No |
| 12 | Kathára-backed `/api/lab/status` adapter | `backend/app/main.py` + new adapter | Maps Kathára container status to `LabStatusResponse` | `kathara` binary or Docker socket (NOT installed) | `test_lab_status_mapped` | Requires Docker host — deferred | AGENT 2 (Frontend) + AGENT 1 (Routing) | **Yes** (Docker + licence) |
| 13 | Real per-device status panel | `frontend/src/components/VirtualLabPanel.tsx` | Shows container/namespace status, CPU, memory, network per device | Backend stats endpoint | Frontend unit test | None | AGENT 2 (Frontend) | No |
| 14 | Real link attachment state in topology | `frontend/src/components/TopologyGraph.tsx` | Merges real link/container attachment into edges | Backend link stats endpoint | Frontend unit test | Link state disagreement could confuse | AGENT 2 (Frontend) | No |

---

## 9. Expected Hardware and Dependency Requirements

**Dev machine:** Pop!_OS, AMD A8-7410, 8GB RAM, HDD.

| Improvement | Resource | Requires Docker? | Requires root? | Works on dev machine? |
|---|---|---|---|---|
| Ranks 1-11 | Low/Medium | No | No (rank 5 needs root only for real lab apply) | **Yes** |
| Ranks 12-14 | Medium/High | **Yes** | Yes | **No** (deferred) |

**Dependencies to NOT add:** `docker`, `kubernetes`, `pyroute2`, `fs`, `libtmux` (all Kathará dependencies, High resource, GPL-3.0).

**Existing dependencies sufficient:** `fastapi`, `pydantic`, `httpx`, `iproute2` (`ip`), `iputils-ping` (`ping`), `traceroute`.

---

## 10. How We Will Prove Each Improvement Works

| Improvement | Proof |
|---|---|
| Real host-discovery test | `pytest backend/tests/test_network_collector_real.py` passes on the dev machine; asserts ≥1 real interface/route/neighbor |
| Real-vs-simulated evidence test | `pytest backend/tests/test_report.py::test_report_has_observed_evidence` passes; provenance == "observed" with real command `source` |
| Conftest mock scoped | `pytest backend/tests/test_report.py` still passes; mock only in unit tests |
| `ScenarioTrace.provenance` union | Frontend type-check passes; trace from real lab shows `observed`, simulated shows `simulated` |
| Topology integrity check | `pytest` rejects non-sequential interface numbers; valid topologies unaffected |
| Parser round-trip tests | Real scenario config files parse to expected structure; invalid files raise errors |
| Centralised `Settings` | Env var overrides respected; defaults applied when unset |
| Structured logging | Log lines emitted for lab apply/teardown and diagnostic commands |
| Provenance badge on table | Table rows display `simulated` badge for modelled routes |
| Scenario staleness | "stale" badge appears when scenario data older than threshold |

---

## 11. Features That Cannot Work Remotely Until a Secure Backend Connection Is Configured

| Feature | Why it needs the backend |
|---|---|
| Route lookup (`/lookup`) | Runs longest-prefix match on backend's routing table |
| Packet journey (`/packet-journey`) | Simulated trace computed on backend |
| Network interfaces/routes/neighbors | Executes `ip -j` on backend host |
| DNS resolution | Runs `getaddrinfo()` on backend host |
| Connectivity / traceroute | Runs `ping`/`traceroute` on backend host |
| Scenario trace | Runs `scenario.trace()` on backend |
| Lab apply/probe | Executes `ip netns`/`ping` on backend host (root) |
| Report generation | Aggregates all above on backend |

The GitHub Pages frontend is static — it cannot execute any of these itself. **The backend computer must remain online** for any of these features to work remotely.

A secure tunnel or access gateway is required because:
- The backend has **no authentication** (CORS is not authentication)
- Diagnostic endpoints execute real system commands (`ping`, `traceroute`)
- The backend must not be exposed directly to the internet

---

## 12. Read-Only Investigation Complete

All six analysis reports are delivered in `docs/kathara-analysis/`. No production files were modified during this investigation. Implementation of any recommendation above requires separate approval and is a distinct phase.

**Next step:** Present this roadmap for review. Upon approval, begin with Rank 1-3 (test improvements) as they are lowest-risk and highest-trustworthiness value.
