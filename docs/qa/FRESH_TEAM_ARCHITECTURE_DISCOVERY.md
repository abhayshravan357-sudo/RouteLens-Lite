# FRESH TEAM ARCHITECTURE DISCOVERY — RouteLens Lite

**Project:** `/home/abhaysawant/Desktop/cn_project_2`
**Branch:** `integration/baseline-2026-10-20` (HEAD `eea5382`)
**Discovery date:** 2026-10-25
**Discoverer:** Engineering Manager (Kilo CLI agent)
**Status:** Stage 1 complete

---

## 1. Current architecture

RouteLens Lite is a computer-networks teaching and analysis platform. The backend is a **pure calculation layer**: no packet is ever transmitted, and every forwarding decision is inferred from a routing table. The frontend visualizes those calculated decisions and clearly separates simulated results from real OS diagnostics.

### Tech stack

| Layer | Technology | Location |
|-------|-----------|----------|
| Backend | Python 3.12, FastAPI, Pydantic | `backend/app/` |
| Backend tests | pytest, pytest-asyncio, httpx | `backend/tests/` |
| Frontend | React 18, TypeScript, Vite | `frontend/src/` |
| Frontend tests | Playwright (a11y only) | `frontend/tests/a11y.spec.ts` |
| Browser E2E | Playwright-driven pytest | `backend/tests/test_e2e_browser.py` |
| API types | Generated from OpenAPI (`openapi-typescript@7`) | `frontend/src/types/api.generated.ts` |

### Backend modules (`backend/app/`)

| Module | Responsibility |
|--------|---------------|
| `main.py` | FastAPI app, all HTTP routes, exception handlers, CORS, static frontend serving |
| `routing.py` | Data models (`RoutingEntry`, `PacketJourneyRequest`, `PacketJourneyResponse`, `PacketHopResponse`, `MatchedRoute`, `RouteLookupResult`), `PACKET_JOURNEY_ACTIONS`, sample routing table |
| `routing_logic.py` | `find_matching_routes`, `select_best_route` (LPM + metric + deterministic tiebreak), `lookup_route`, `trace_packet_path` (multi-hop trace, loop detection, hop limit) |
| `routing_table.py` | `RoutingTable` CRUD with persistence, atomic save/backup/recovery |
| `routing_table_persistence.py` | Disk load/save, fallback to sample table on corruption |
| `packet_lab.py` | Virtual lab lifecycle |
| `lab_builder.py` | Namespace build/teardown command generation, probe with `reason` field |
| `lab_adapter.py` | tcpdump capture parsing (stdout+stderr), timeout race fix |
| `lab_next_steps.py` | Lab condition diagnosis and next-step guidance |
| `scenario_routes.py`, `scenario.py` | Multi-router scenario engine, compare endpoint |
| `network_collector.py`, `discovery_routes.py` | Host network discovery (interfaces, routes, neighbours, DNS, connectivity, traceroute) |
| `security.py` | Input validation, rate limiting, CORS |
| `pcap_routes.py`, `pcap.py` | PCAP capture importer |
| `report_routes.py`, `report.py` | Evidence reports |
| `router_discovery_routes.py` + `router_discovery/` | Router discovery (under construction) |
| `exercises.py` | Learning lab exercises |

### Frontend modules (`frontend/src/`)

Pages/components for: dashboard, routing table editor, route analysis, packet journey, network topology, packet lab, virtual lab, learning lab, reports/exports.

Key files:
- `src/types/routing.ts` — generated OpenAPI types, `JourneyOutcome` union
- `src/components/PacketJourney.tsx` — hop timeline, `classifyOutcome` (now uses `success` + `failure_code`)
- `src/components/VirtualLabPanel.tsx` — virtual lab UI state machine (Phase 1 fix applied)

### Contract

The backend never claims real transmission; `provenance` is `simulated` for table-driven answers. Observed host data is marked `observed`/`inferred`. Structured failure codes (`no_route`, `max_hops_exceeded`, `loop`, `unresolved_next_hop`, `routing_table_error`, etc.) are emitted on `PacketJourneyResponse.failure_code` and `PacketHopResponse.failure_reason`.

---

## 2. Existing completed functionality

- **Routing table lookup** — LPM, default routes, direct delivery, metric tiebreaking, CRUD, reset, summary, analysis
- **Packet journey trace** — Multi-hop trace with loop detection, hop limit (MAX_HOPS=30), structured `failure_code`
- **Packet Lab API** — `GET /api/lab/status`, `POST /api/lab/simulate` (implemented, unexecutable without root/namespaces)
- **Network discovery** — Interfaces, routes, neighbours, DNS, connectivity, traceroute
- **Authorised host discovery** — Confirmation-based scoping, rate limiting
- **Scenario lab** — Multi-router simulation, compare endpoint with `reason` field
- **Learning lab / exercises** — Exercise listing and checking
- **PCAP importer** — Classic PCAP parsing
- **Evidence reports** — Report generation
- **Security** — Input validation, rate limiting, CORS, no shell injection
- **Health check** — `GET /health`
- **Frontend typecheck + production build** — Pass clean

---

## 3. Incomplete functionality

| Item | Location | Gap |
|------|----------|-----|
| Frontend unit/component tests | `frontend/src/` | None exist; only Playwright a11y spec |
| Frontend code-coverage tooling | `frontend/` | Not configured |
| Traceroute `reached_destination` field | `network_collector.py` | `completed` doesn't distinguish reached vs max-hops |
| Router discovery real device collection | `router_discovery/` | Needs LLDP/CDP/SNMP/SSH |
| Real-network verification | Packet Lab, discovery | Requires root/namespaces, not available |

---

## 4. Known defects

| ID | Defect | Location | Severity | Status |
|----|--------|----------|----------|--------|
| IMP-01 | No next-hop reachability/interface validation | `routing_logic.py` trace | Medium | Suspected |
| IMP-02 | No stale-simulation version tracking | `routing_table.py`, persistence | Medium | Suspected |
| IMP-03 | Duplicate `PacketHop` dataclass | `routing.py` / `routing_logic.py` | Low | Confirmed |
| IMP-04 | `/lookup` 404 returns `detail` string, not `RouteLookupResult` | `main.py` | Low | Confirmed |
| IMP-05 | Low backend coverage: `lab_next_steps.py` (41%), `report_routes.py` (52%) | test coverage | Medium | Confirmed |
| IMP-06 | No frontend unit/component tests; no frontend coverage | `frontend/` | Medium | Confirmed |

---

## 5. Technical risks

- **Frontend/backend contract drift**: `PacketJourneyResponse` is schema-aliased; types were regenerated from a locally-generated OpenAPI snapshot (live :8000 server serves stale schema)
- **Shared file ownership**: `routing_logic.py`, `routing_table.py`, `lab_*.py`, `VirtualLabPanel.tsx` span multiple squad domains
- **Browser E2E cannot be re-verified**: Node 18.19.1 vs Playwright Node 20+ requirement
- **Virtual Lab real execution**: Requires root/CAP_SYS_ADMIN + namespaces + `ip`/`ping`/`tcpdump` — not available

---

## 6. Test coverage and gaps

- **Backend**: 1,486 passed, 6 skipped, 0 failed (`pytest --ignore=tests/test_e2e_browser.py -q`)
- **Browser E2E**: 101 total, 93 pass, 5 fail, 3 skip (recorded prior run; cannot re-run locally)
- **Backend coverage**: 84% on `app/`; low modules: `lab_next_steps.py` (41%), `report_routes.py` (52%), `router_discovery_routes.py` (62%)
- **Frontend**: typecheck + build pass; no unit/component tests, no coverage tooling

---

## 7. Dependencies between modules

| Dependent | Dependency | Interface |
|-----------|-----------|-----------|
| Frontend | Backend | `failure_code`, `failure_reason`, `reason` fields; OpenAPI schema |
| Packet Lab | Backend | `lab_builder.probe` returns `reason`; lab status contract |
| QA → All | Independent verification | Must not modify other agents' files without coordination |
| Platform → All | Runbook, startup, environment | Documentation and config |

---

## 8. Recommended team structure (five new specialized agents)

| Squad | Identity | Branch | Primary focus | File ownership |
|-------|----------|--------|--------------|----------------|
| 1 | `routelens-routing-architect` | `squad/routing-engine` | Backend routing engine correctness | `routing.py`, `routing_logic.py`, `routing_table.py`, `main.py` (routing routes), backend tests |
| 2 | `routelens-frontend-engineer` | `squad/frontend-experience` | Frontend UI, interactions, API integration | `frontend/src/components/*`, `frontend/src/types/*`, frontend build |
| 3 | `routelens-packet-lab-engineer` | `squad/packet-lab` | Packet simulation, virtual lab | `packet_lab.py`, `lab_builder.py`, `lab_adapter.py`, `lab_next_steps.py`, scenario routes |
| 4 | `routelens-quality-engineer` | `squad/quality-engineering` | Independent QA, test automation | Test files (all), test matrix, defect register (read-only on source) |
| 5 | `routelens-platform-engineer` | `squad/platform-engineering` | Startup, config, docs, runbook | `README.md`, CI config, startup scripts, environment config |

### Subagent plans per primary agent

- **Routing architect**: routing algorithm audit, routing API/schema audit, edge-case testing, backend reliability
- **Frontend engineer**: dashboard/navigation, packet journey/topology, learning lab/reports, UI consistency/accessibility
- **Packet Lab engineer**: simulation lifecycle, scenario engine, virtual lab availability, frontend integration
- **QA engineer**: backend test coverage, frontend/browser testing, API contract verification, security/regression E2E
- **Platform engineer**: startup/configuration, developer tooling/automation, documentation/runbooks, reliability/observability

---

## 9. Branch and worktree preparation requirement

Five new `squad/*` branches must be created:
- `squad/routing-engine`
- `squad/frontend-experience`
- `squad/packet-lab`
- `squad/quality-engineering`
- `squad/platform-engineering`

None of these branches exist yet. Each needs a dedicated isolated worktree.

### Dirty working tree constraint

The integration workspace (`/home/abhaysawant/Desktop/cn_project_2`) has 17 uncommitted modified files (Phase 1/B1/B2 fixes). New worktrees created from `eea5382` will NOT contain these changes automatically.

**Safe approach**: The existing `team/*` worktrees already have the full diff applied. New `squad/*` worktrees need the same diff applied non-destructively (via `git apply`, not checkout/reset/stash).

---

## 10. Agent platform capability assessment

| Capability | Available | Evidence |
|------------|-----------|----------|
| `agent_manager` function tool | Yes | Successfully called `action: "list"` and `action: "start"` (mode: worktree) |
| `agent_manager_models` function tool | Yes | Called, returned empty model list |
| Create Agent Manager sessions | Yes | `mode: "worktree"` creates sessions on new branches |
| Target existing branch/worktree | No | Git prevents same branch in two worktrees; `agent_manager` auto-creates branches |
| Register existing worktrees | No | No tool available |
| Specify exact worktree path | No | `agent_manager` manages worktree paths |
| Spawn local subagents | Unknown | No evidence available from CLI |
| Create persistent agent profiles | No | No tool available from CLI |

**Bottom line**: Agent deployment via `agent_manager` function tool is possible for new `squad/*` branches (they don't exist yet, so no branch conflict). However:
- Worktree paths are managed by Agent Manager, not controllable
- Model list is empty — sessions may fail without a model
- Subagent deployment cannot be verified from CLI
- No persistent agent profile creation available

All findings below are reported honestly; nothing is simulated.
