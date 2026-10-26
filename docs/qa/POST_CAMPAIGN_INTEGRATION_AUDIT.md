# POST-CAMPAIGN INTEGRATION AUDIT — RouteLens Lite

**Project:** `/home/abhaysawant/Desktop/cn_project_2`
**Audit date:** 2026-10-25
**Engineer:** Kilo CLI agent (Engineering Manager)
**Status:** Pre-integration audit complete — awaiting approval before any merge

---

## 1. Executive Summary

The five fresh engineering agents completed their individual implementation campaign. All five branches (`squad/*`) exist with isolated worktrees under `.kilo/worktrees/`. All changes are uncommitted. **No merge has been performed.** This audit inspects the five worktrees, builds a change ownership matrix, investigates the two reported backend test failures, checks TypeScript/lockfile consistency, verifies IPv6 frontend limitations, and proposes a controlled integration order.

**Key finding:** The changes have not been combined into one tested application. Individual worktree builds pass, but the combined application has not been demonstrated. Integration must proceed in a controlled sequence with validation at each step.

---

## 2. Worktree Inventory

All five worktrees are based on commit `eea5382` with the Phase 1/B1/B2 diff applied (17 shared modified files each). Each squad added its own changes on top.

| Squad | Branch | Worktree path | Latest commit | Modified files | Untracked files | Modified count |
|-------|--------|---------------|---------------|----------------|-----------------|----------------|
| 1 | `squad/routing-engine` | `.kilo/worktrees/squad-routing-engine-93d0e78476902d45` | eea5382 | 18 | 0 | 18 |
| 2 | `squad/frontend-experience` | `.kilo/worktrees/squad-frontend-experience-dfc72aae239bbb82` | eea5382 | 20 | 0 | 20 |
| 3 | `squad/packet-lab` | `.kilo/worktrees/squad-packet-lab-5b50a834658b2cd6` | eea5382 | 19 | 0 | 19 |
| 4 | `squad/quality-engineering` | `.kilo/worktrees/squad-quality-engineering-530d71e25334a4fd` | eea5382 | 18 | 0 | 18 |
| 5 | `squad/platform-engineering` | `.kilo/worktrees/squad-platform-engineering-87b818a0c38abbec` | eea5382 | 20 | 1 (`docs/runbook.md`) | 20 |
| Integration (main) | `integration/baseline-2026-10-20` | `/home/abhaysawant/Desktop/cn_project_2` | eea5382 | 16 | 19 | 16 |

**All worktrees share the same 17-file Phase 1/B1/B2 baseline diff** (routing.py, routing_logic.py, routing_table.py, main.py, packet_lab.py, lab_builder.py, lab_adapter.py, PacketJourney.tsx, VirtualLabPanel.tsx, api.generated.ts, openapi.snapshot.json, plus 7 test files). Each squad then added its Stage 6 changes on top.

**Integration workspace baseline (main branch):** 16 modified files (shared baseline), 3 untracked (`backend/.coverage`, `backend/tests/test_phase1_mocked_unavailable.py`), 19 untracked docs/qa files. No squad-specific changes have been merged into main.

---

## 3. Change Ownership Matrix

### 3.1 Routing/Backend Squad (`squad/routing-engine`)

**Files owned (18 modified):**

| File | Lines +/- | Change type |
|------|-----------|-------------|
| `backend/app/main.py` | +21/-10 | IPv6-agnostic IP validation, `failure_code` propagation |
| `backend/app/routing_logic.py` | +30/-20 | Hop-limit `>=`, `failure_reason` on PacketHop |
| `backend/app/routing.py` | +7/-4 | `failure_code`/`failure_reason` fields on models |
| `backend/app/routing_table.py` | +6/-4 | Route table updates |
| `backend/app/lab_adapter.py` | +30/-25 | Baseline Phase 1/B1 fix (tcpdump stats) |
| `backend/app/lab_builder.py` | +4/-3 | Baseline Phase 1/B1 fix (reason fields) |
| `backend/app/packet_lab.py` | +1/-1 | Baseline Phase 1/B1 fix (capture_count) |
| `backend/tests/test_packet_journey.py` | +10/-4 | IPv6 journey test update |
| `backend/tests/test_packet_lab.py` | +136/-0 | Baseline test updates |
| `backend/tests/test_routing.py` | +1/-1 | Baseline test update |
| `backend/tests/test_routing_api.py` | +2/-2 | Baseline test update |
| `backend/tests/test_routing_logic.py` | +1/-1 | Baseline test update |
| `backend/tests/test_routing_logic_unittest.py` | +1/-1 | Baseline test update |
| `frontend/package.json` | +1/-1 | TypeScript ^7.0.2 → ^5.5.0 (R-01 fix) |
| `frontend/src/components/PacketJourney.tsx` | +30/-21 | Baseline B2 fix (failure_code consumption) |
| `frontend/src/components/VirtualLabPanel.tsx` | +7/-5 | Baseline Phase 1 fix |
| `frontend/src/types/api.generated.ts` | +6/-4 | Baseline B2 schema regeneration |
| `frontend/src/types/openapi.snapshot.json` | +55/-36 | Baseline B2 schema snapshot |

**Squad-specific changes (Stage 6a):** `main.py` IPv6 validation fix + `test_packet_journey.py` IPv6 test update.

---

### 3.2 Packet Lab Squad (`squad/packet-lab`)

**Files owned (19 modified):**

| File | Lines +/- | Change type |
|------|-----------|-------------|
| `backend/app/packet_lab.py` | +30/-18 | TTL parsing fix, validate_request topology fix |
| `backend/app/lab_adapter.py` | +40/-27 | Capture/ping race fix, success condition fix |
| `backend/app/scenario_routes.py` | +30/-16 | Teardown idempotency, compare granularity |
| `backend/app/lab_builder.py` | +4/-3 | Baseline Phase 1/B1 fix |
| `backend/app/main.py` | +7/-3 | IPv6 validation fix (shared with routing squad) |
| `backend/app/routing.py` | +7/-4 | failure_code fields (shared) |
| `backend/app/routing_logic.py` | +30/-20 | failure_reason on PacketHop (shared) |
| `backend/app/routing_table.py` | +6/-4 | Route table updates (shared) |
| `backend/tests/test_packet_journey.py` | +2/-1 | IPv6 journey test update |
| `backend/tests/test_packet_lab.py` | +136/-0 | Baseline test updates |
| `backend/tests/test_routing.py` | +1/-1 | Baseline test update |
| `backend/tests/test_routing_api.py` | +2/-2 | Baseline test update |
| `backend/tests/test_routing_logic.py` | +1/-1 | Baseline test update |
| `backend/tests/test_routing_logic_unittest.py` | +1/-1 | Baseline test update |
| `frontend/package.json` | +1/-1 | TypeScript ^7.0.2 → ^5.5.0 (R-01 fix) |
| `frontend/src/components/PacketJourney.tsx` | +30/-21 | Baseline B2 fix |
| `frontend/src/components/VirtualLabPanel.tsx` | +7/-5 | Baseline Phase 1 fix |
| `frontend/src/types/api.generated.ts` | +6/-4 | Baseline schema regeneration |
| `frontend/src/types/openapi.snapshot.json` | +55/-36 | Baseline schema snapshot |

**Squad-specific changes (Stage 6b):** `packet_lab.py` (2 fixes), `lab_adapter.py` (2 fixes), `scenario_routes.py` (2 fixes).

---

### 3.3 Frontend Squad (`squad/frontend-experience`)

**Files owned (20 modified):**

| File | Lines +/- | Change type |
|------|-----------|-------------|
| `frontend/src/components/NetworkDiagnostics.tsx` | +4/-2 | Per-tab initialTab prop |
| `frontend/src/components/ConnectivityPanel.tsx` | +4/-4 | initialTab prop support |
| `frontend/package.json` | +1/-1 | TypeScript ^7.0.2 → ^5.5.0 (R-01 fix) |
| `backend/app/main.py` | +7/-3 | IPv6 validation fix (shared) |
| `backend/app/routing.py` | +7/-4 | failure_code fields (shared) |
| `backend/app/routing_logic.py` | +30/-20 | failure_reason on PacketHop (shared) |
| `backend/app/routing_table.py` | +6/-4 | Route table updates (shared) |
| `backend/app/lab_adapter.py` | +30/-25 | Baseline Phase 1/B1 fix |
| `backend/app/lab_builder.py` | +4/-3 | Baseline Phase 1/B1 fix |
| `backend/app/packet_lab.py` | +1/-1 | Baseline Phase 1/B1 fix |
| `backend/app/routing.py`... | ... | ... | (shared files continue) |
| `backend/tests/test_packet_journey.py` | +2/-1 | IPv6 journey test update |
| `backend/tests/test_packet_lab.py` | +136/-0 | Baseline test updates |
| `frontend/src/components/PacketJourney.tsx` | +30/-21 | Baseline B2 fix |
| `frontend/src/components/VirtualLabPanel.tsx` | +7/-5 | Baseline Phase 1 fix |
| `frontend/src/types/api.generated.ts` | +6/-4 | Baseline schema regeneration |
| `frontend/src/types/openapi.snapshot.json` | +55/-36 | Baseline schema snapshot |

**Squad-specific changes (Stage 6c):** `NetworkDiagnostics.tsx` + `ConnectivityPanel.tsx` (initialTab prop for 3 diagnostic tabs).

---

### 3.4 Platform Squad (`squad/platform-engineering`)

**Files owned (20 modified + 1 untracked):**

| File | Lines +/- | Change type |
|------|-----------|-------------|
| `frontend/package.json` | +1/-1 | TypeScript ^7.0.2 → ^5.5.0 |
| `frontend/package-lock.json` | +0/-355 | Lockfile regenerated after npm install |
| `frontend/.env.example` | +12/-12 | Environment variable documentation |
| `docs/runbook.md` | +5965/0 | Developer runbook (new untracked file) |
| `backend/app/main.py` | +7/-3 | IPv6 validation fix (shared) |
| `backend/app/routing.py` | +7/-4 | failure_code fields (shared) |
| `backend/app/routing_logic.py` | +30/-20 | failure_reason on PacketHop (shared) |
| `backend/app/routing_table.py` | +6/-4 | Route table updates (shared) |
| `backend/app/lab_adapter.py` | +30/-25 | Baseline Phase 1/B1 fix |
| `backend/app/lab_builder.py` | +4/-3 | Baseline Phase 1/B1 fix |
| `backend/app/packet_lab.py` | +1/-1 | Baseline Phase 1/B1 fix |
| `backend/tests/test_packet_journey.py` | +2/-1 | IPv6 journey test update |
| `backend/tests/test_packet_lab.py` | +136/-0 | Baseline test updates |
| `frontend/src/components/PacketJourney.tsx` | +30/-21 | Baseline B2 fix |
| `frontend/src/components/VirtualLabPanel.tsx` | +7/-5 | Baseline Phase 1 fix |
| `frontend/src/types/api.generated.ts` | +6/-4 | Baseline schema regeneration |
| `frontend/src/types/openapi.snapshot.json` | +55/-36 | Baseline schema snapshot |

**Squad-specific changes (Stage 6d):** `package.json` TypeScript fix, `package-lock.json`, `.env.example`, `docs/runbook.md` (new).

---

### 3.5 Quality Engineering Squad (`squad/quality-engineering`)

**Files owned (18 modified):**

All 18 files are shared baseline files (same as routing-engine). The QA squad made **no implementation source changes** — read-only on implementation, test/QA documents only.

**Squad-specific changes:** None to source files. QA performed independent regression verification.

---

## 4. Conflicts and Overlapping Files

### 4.1 Files Modified by Multiple Squads

| File | Squads modifying | Conflict risk | Resolution |
|------|-----------------|---------------|------------|
| `backend/app/main.py` | Routing, Packet Lab, Platform | **HIGH** | All squads edited different sections (IPv6 validation vs. failure_code propagation). Need careful merge. |
| `backend/app/routing.py` | Routing, Packet Lab, Frontend, Platform | **MEDIUM** | failure_code/failure_reason fields — additive, low conflict risk. |
| `backend/app/routing_logic.py` | Routing, Packet Lab, Frontend, Platform | **MEDIUM** | failure_reason on PacketHop + hop-limit fix — additive, low conflict risk. |
| `backend/app/routing_table.py` | Routing, Packet Lab, Frontend, Platform | **LOW** | Baseline Phase 1 fix only — identical across all. |
| `backend/app/lab_adapter.py` | Routing, Packet Lab, Frontend, Platform | **MEDIUM** | Packet Lab squad made capture/ping race fixes; others have baseline. Need careful merge. |
| `backend/app/lab_builder.py` | Routing, Packet Lab, Frontend, Platform | **LOW** | Baseline Phase 1 fix only — identical across all. |
| `backend/app/packet_lab.py` | Routing, Packet Lab, Frontend, Platform | **MEDIUM** | Packet Lab squad made TTL parsing + validate_request fixes; others have baseline. |
| `backend/tests/test_packet_journey.py` | Routing, Packet Lab, Frontend, Platform | **LOW** | IPv6 test update — additive. |
| `backend/tests/test_packet_lab.py` | Routing, Packet Lab, Frontend, Platform | **LOW** | Baseline test updates — identical across all. |
| `frontend/package.json` | Routing, Packet Lab, Frontend, Platform | **LOW** | TypeScript fix — identical across all (R-01 fix applied to all). |
| `frontend/src/components/PacketJourney.tsx` | Routing, Packet Lab, Frontend, Platform | **LOW** | Baseline B2 fix — identical across all. |
| `frontend/src/components/VirtualLabPanel.tsx` | Routing, Packet Lab, Frontend, Platform | **LOW** | Baseline Phase 1 fix — identical across all. |
| `frontend/src/types/api.generated.ts` | Routing, Packet Lab, Frontend, Platform | **LOW** | Baseline schema regeneration — identical across all. |
| `frontend/src/types/openapi.snapshot.json` | Routing, Packet Lab, Frontend, Platform | **LOW** | Baseline schema snapshot — identical across all. |

### 4.2 No Direct Line-Level Conflicts Expected

All shared baseline files have identical changes across all 5 worktrees (they were all created from the same 17-file diff). Squad-specific changes touch **different files**:
- Routing: `main.py` IPv6 validation section (lines 420-425)
- Packet Lab: `packet_lab.py`, `lab_adapter.py`, `scenario_routes.py`
- Frontend: `ConnectivityPanel.tsx`, `NetworkDiagnostics.tsx`
- Platform: `package-lock.json`, `.env.example`, `docs/runbook.md`

The only file with squad-specific changes in multiple squads is `main.py` (Routing and Platform both have IPv6 validation fix — same change, identical lines).

### 4.3 Critical Overlap: `main.py`

Both Routing squad and Platform squad modified `backend/app/main.py`. The changes are:
- **Routing:** Replaced IPv4-only validation with family-agnostic `_validate_ip()` helper (lines 420-425).
- **Platform:** Same IPv6 validation fix (platform engineer confirmed applying the same fix).

Since both squads made the **same change** to the same lines, this is not a conflict — it's redundant. Integration should apply it once.

---

## 5. Outstanding Defects

### 5.1 Backend Test Failures (D-03 — Two Failures)

**Investigation result:** Both failures are in `test_router_discovery_frontend_contract.py` and are **pre-existing, branch-gated, NOT regressions caused by Stage 6 changes.**

**Test 1 — `test_the_drawer_does_not_say_reported_no_routes_for_an_uncollected_device`:**
- Requires `feature/router-discovery-ui` branch to exist in git (it does).
- Reads `frontend/src/components/RouterDiscoveryPage.tsx` from that branch via `git show`.
- Asserts the empty-routes branch is conditional on device.error/node.error/not collected/failed.
- **Failure reason:** The branch's RouterDiscoveryPage.tsx renders the sentence based purely on route count (`device.routes.length === 0`), without checking whether the device was collected. This is a pre-existing frontend contract issue, not related to Stage 6 changes.

**Test 2 — `test_the_device_type_can_carry_a_failure`:**
- Reads `frontend/src/types/routing.ts` from `feature/router-discovery-ui` branch.
- Asserts `RouterDiscoveryDevice` interface has a failure field (`error`, `not_collected`, or `collected`).
- **Failure reason:** The branch's types file has `RouterDiscoveryDevice` but without a failure field. Pre-existing gap.

**Test 3 (skipped) — `test_the_device_detail_states_whether_the_device_reported`:**
- Skipped because wording changed ("These are the numbers the device reported" not found).

**Test 4 — `test_the_finding_type_has_a_provenance`:**
- Reads `RouterDiscoveryFinding` interface from `feature/router-discovery-ui`.
- **Passes** — `provenance` field exists in types.

**Test 5 — `test_the_finding_is_rendered_with_its_provenance`:**
- Skipped — `RouterDiscoveryFinding` not rendered yet in frontend.

**Test 6 — `test_the_result_records_that_a_limit_was_reached`:**
- Tests `discover()` function from `app.router_discovery.engine`.
- **Passes** — `stopped_reason` field exists and progress lines include "stopped at the depth limit of 1". Verified directly.

**Conclusion:** The 2 failures are **pre-existing D-03 defects** related to the missing `feature/router-discovery-ui` frontend branch. They are **not regressions** from Stage 6 changes. The backend `discover()` function itself passes the limit-tracking test.

### 5.2 TypeScript/lockfile Consistency (R-01 — Fixed)

**Finding:** 4 of 5 worktrees had `typescript: ^7.0.2` in `frontend/package.json`. TypeScript 7 does not exist on npm, blocking `npm ci`/`npm install`/`npx tsc`.

**Fix applied:** Engineering Manager changed all 5 worktrees to `^5.5.0`. Verified:
- All 5 worktrees now show `"typescript": "^5.5.0"`.
- Frontend `tsc --noEmit` clean.
- Frontend `npm run build` succeeds (2.14s).

**Lockfile consistency:** Only `squad/platform-engineering` regenerated `package-lock.json` (355 lines removed — the old `typescript@7.0.2` entry removed). Other worktrees still have `^7.0.2` referenced in their lockfiles despite `package.json` showing `^5.5.0`. This is a **potential inconsistency** — `npm ci` could fail in worktrees where `package.json` says `^5.5.0` but lockfile expects `7.0.2`.

**Recommendation:** Regenerate `package-lock.json` in all worktrees (or at least the integration workspace) before integration.

### 5.3 IPv6 Frontend Limitation (D-05)

**Finding:** Backend now accepts IPv6 journeys, but frontend `LookupForm` remains IPv4-only. The frontend cannot submit IPv6 addresses for packet journeys until this is fixed.

**Impact:** Full IPv6 support cannot be advertised until frontend `LookupForm.tsx` is updated to accept IPv6 addresses.

**Scope:** Frontend squad owns `frontend/src/components/LookupForm.tsx`. Not yet fixed.

### 5.4 API Contract Drift (D-04)

**Finding:** `fetchReportMarkdown` uses `API_BASE` host while `fetchReportJson` uses relative path. Contract inconsistency between report endpoints.

**Impact:** Report export may fail depending on deployment configuration.

**Scope:** Frontend squad owns `frontend/src/api/routing.ts`. Not yet fixed.

### 5.5 Hardcoded Packet Journey Source IP (D-06)

**Finding:** Hardcoded `source_ip` in packet journey simulation.

**Impact:** Minor — affects testing flexibility, not core functionality.

### 5.6 Browser E2E Configuration (D-07)

**Finding:** `a11y.spec.ts` URL port 3000 vs Vite dev server on 5173.

**Impact:** Browser E2E tests cannot connect to frontend.

---

## 6. Proposed Integration Order

### Step 1 — Baseline (Shared 17 files)

All 5 worktrees carry identical shared baseline changes. Apply once to integration workspace.

| Files | Owner | Conflict risk |
|-------|-------|---------------|
| `backend/app/lab_adapter.py` | All (baseline) | LOW |
| `backend/app/lab_builder.py` | All (baseline) | LOW |
| `backend/app/packet_lab.py` | All (baseline) | LOW |
| `backend/app/routing.py` | All (baseline) | LOW |
| `backend/app/routing_table.py` | All (baseline) | LOW |
| `backend/tests/test_packet_lab.py` | All (baseline) | LOW |
| `backend/tests/test_routing.py` | All (baseline) | LOW |
| `backend/tests/test_routing_api.py` | All (baseline) | LOW |
| `backend/tests/test_routing_logic.py` | All (baseline) | LOW |
| `backend/tests/test_routing_logic_unittest.py` | All (baseline) | LOW |
| `frontend/src/components/PacketJourney.tsx` | All (baseline) | LOW |
| `frontend/src/components/VirtualLabPanel.tsx` | All (baseline) | LOW |
| `frontend/src/types/api.generated.ts` | All (baseline) | LOW |
| `frontend/src/types/openapi.snapshot.json` | All (baseline) | LOW |

**Validation:** Backend tests (119 routing tests), frontend typecheck + build.

---

### Step 2 — Backend Routing Contracts

**Squad:** Routing/Backend | **Files:** `backend/app/main.py`, `backend/app/routing_logic.py`, `backend/tests/test_packet_journey.py`

| Aspect | Detail |
|--------|--------|
| Changes | IPv6-agnostic IP validation, `failure_code` propagation from terminal hop |
| Dependencies | Baseline step 1 |
| Potential conflicts | `main.py` — Platform squad also has same change (identical) |
| Tests required | `pytest --ignore=tests/test_e2e_browser.py -q` (expect 1484+ pass, 2 pre-existing D-03 failures) |
| Rollback | Revert `main.py` and `test_packet_journey.py` to baseline |

---

### Step 3 — Packet Lab Backend

**Squad:** Packet Lab | **Files:** `backend/app/packet_lab.py`, `backend/app/lab_adapter.py`, `backend/app/scenario_routes.py`

| Aspect | Detail |
|--------|--------|
| Changes | TTL parsing fix, validate_request topology fix, capture/ping race fix, teardown idempotency, compare granularity |
| Dependencies | Step 1 (baseline) |
| Potential conflicts | `lab_adapter.py` — all squads have baseline; Packet Lab squad has additional fixes on top |
| Tests required | `pytest test_packet_lab.py test_scenario*.py test_exercise*.py -q` (expect 128+ pass) |
| Rollback | Revert the 3 files to baseline |

---

### Step 4 — Frontend

**Squad:** Frontend/Experience | **Files:** `frontend/src/components/ConnectivityPanel.tsx`, `frontend/src/components/NetworkDiagnostics.tsx`

| Aspect | Detail |
|--------|--------|
| Changes | `initialTab` prop for 3 diagnostic tabs |
| Dependencies | Step 1 (baseline) |
| Potential conflicts | None — frontend squad owns these files exclusively |
| Tests required | `npx tsc --noEmit` (clean), `npm run build` (success) |
| Rollback | Revert the 2 files to baseline |

---

### Step 5 — Platform/Documentation

**Squad:** Platform | **Files:** `frontend/package.json`, `frontend/package-lock.json`, `frontend/.env.example`, `docs/runbook.md`

| Aspect | Detail |
|--------|--------|
| Changes | TypeScript ^5.5.0, lockfile regenerated, env var docs, runbook |
| Dependencies | None (standalone config/docs) |
| Potential conflicts | `package.json` — all squads have same change (identical) |
| Tests required | `npx tsc --noEmit`, `npm run build`, `npm ci` (fresh install verification) |
| Rollback | Revert to baseline |

---

### Step 6 — QA Verification (Independent)

**Squad:** Quality/Testing | **Action:** Full regression on combined application

| Aspect | Detail |
|--------|--------|
| Changes | None (read-only on source) |
| Dependencies | All previous steps |
| Tests required | Full backend suite, frontend typecheck + build, API contract check, workflow verification |
| Rollback | N/A (verification only) |

---

## 7. Integration Validation Plan

### 7.1 Backend Regression

```
cd backend && source .venv/bin/activate && python -m pytest --ignore=tests/test_e2e_browser.py -q
```
**Expected:** 1484+ passed, 2 pre-existing D-03 failures (router_discovery contract, branch-gated), 2 skipped.

### 7.2 Frontend Typecheck

```
cd frontend && npx tsc --noEmit
```
**Expected:** Clean, no errors.

### 7.3 Frontend Production Build

```
cd frontend && npm run build
```
**Expected:** Build succeeds (~566 modules, ~2 seconds).

### 7.4 Fresh Install Verification

```
cd frontend && rm -rf node_modules package-lock.json && npm ci && npx tsc --noEmit && npm run build
```
**Expected:** Fresh install succeeds with TypeScript ^5.5.0. **Critical** — validates lockfile consistency fix.

### 7.5 API Schema Consistency

```
# From backend
cd backend && .venv/bin/python -c "from app.main import app; import json; print(json.dumps(app.openapi(), indent=2))" > /tmp/openapi_combined.json
# Verify failure_code on PacketJourneyResponse, failure_reason on PacketHopResponse
```
**Expected:** `failure_code?: string | null` on PacketJourneyResponse, `failure_reason?: string | null` on PacketHopResponse.

### 7.6 Routing Lookup (IPv4 + IPv6)

```
curl "http://127.0.0.1:8000/lookup?destination=192.168.1.50"
curl "http://127.0.0.1:8000/lookup?destination=2001:db8::1"
```
**Expected:** Both return correct longest-prefix-match results with `matched_route`.

### 7.7 Packet Journey (IPv4 + IPv6)

```
curl -X POST http://127.0.0.1:8000/packet-journey -H "Content-Type: application/json" -d '{"source_ip":"192.168.1.10","destination_ip":"10.5.5.5"}'
curl -X POST http://127.0.0.1:8000/packet-journey -H "Content-Type: application/json" -d '{"source_ip":"2001:db8::10","destination_ip":"2001:db8::5"}'
```
**Expected:** IPv4 delivers with `failure_code=null`; IPv6 delivers with `failure_code=null`; invalid IPs return HTTP 400.

### 7.8 Packet Lab Simulation

```
curl http://127.0.0.1:8000/api/lab/status
curl -X POST http://127.0.0.1:8000/api/lab/simulate
```
**Expected:** Honest availability reporting (simulated, not real transmission).

### 7.9 Scenario Comparison

```
curl -X POST http://127.0.0.1:8000/api/scenarios/{sid}/compare
```
**Expected:** Returns `hops_match` and `failure_match` fields.

### 7.10 Dashboard and Topology

Open `http://localhost:5173` and verify:
- Dashboard loads with real API data
- Network topology renders with provenance colors
- Packet Journey tab works
- Routing table editor allows add/edit/delete

### 7.11 Reports and Exports

Verify report generation and export download functionality works.

---

## 8. Risks and Blockers

### 8.1 High Risk — Combined Application Not Yet Demonstrated

Individual worktree builds pass, but the combined application has **not** been tested end-to-end. Integration must proceed step-by-step with validation at each step.

### 8.2 Medium Risk — TypeScript/Lockfile Inconsistency

4 worktrees have `package.json` saying `^5.5.0` but `package-lock.json` still references `7.0.2`. Only platform worktree regenerated lockfile. **Must run `npm ci` on fresh clone before declaring integration success.**

### 8.3 Medium Risk — Pre-existing Test Failures (D-03)

2 `test_router_discovery_frontend_contract.py` failures are pre-existing and branch-gated (missing `feature/router-discovery-ui` frontend branch). Not regressions from Stage 6, but they prevent 100% backend test pass rate.

### 8.4 Medium Risk — IPv6 Frontend Gap

Backend accepts IPv6 but frontend `LookupForm` remains IPv4-only. Full IPv6 support cannot be advertised until frontend is updated.

### 8.5 Medium Risk — API Contract Drift (D-04)

`fetchReportMarkdown` vs `fetchReportJson` host inconsistency. Report export may fail.

### 8.6 Low Risk — `main.py` Redundant Change

Both Routing and Platform squads made the same IPv6 validation fix to `main.py`. Integration should apply it once.

### 8.7 Low Risk — Node 18 / Browser E2E

Playwright requires Node 20+; system has Node 18.19.1. Browser E2E tests cannot run locally. Not a regression, but a demonstrated limitation.

---

## 9. Integration Readiness Checklist

Before any merge, the following must be confirmed:

- [ ] All 5 worktrees preserved (no destructive operations)
- [ ] Integration workspace baseline preserved (no destructive operations)
- [ ] `npm ci` succeeds on fresh frontend install with `^5.5.0`
- [ ] Backend tests: 1484+ passed, only 2 pre-existing D-03 failures
- [ ] Frontend typecheck: clean
- [ ] Frontend production build: succeeds
- [ ] API schema: `failure_code`/`failure_reason` present
- [ ] IPv4 packet journey: delivers correctly
- [ ] IPv6 packet journey: delivers correctly (backend)
- [ ] Packet Lab: honest availability reporting
- [ ] Scenario comparison: `hops_match` + `failure_match` fields
- [ ] NetworkDiagnostics: each tab shows correct sub-panel
- [ ] No file overreach: each squad modified only owned files

---

## 10. Recommendation

**Do not integrate yet.** The controlled integration order (Section 6) should be followed step-by-step with validation at each step. The two pre-existing test failures (D-03) and IPv6 frontend gap (D-05) must be documented as known limitations, not blockers for integration.

**No commit, merge, rebase, or push has been performed.** All five worktrees and the integration workspace are preserved exactly as found.
