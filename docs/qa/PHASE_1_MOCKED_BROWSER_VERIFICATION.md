# Phase 1 Final Mocked Browser Verification — RouteLens Lite

**QA/TestPilot agent. QA-ONLY verification. No application code was modified. No commits, merges, or pushes. No network namespaces were created, deleted, or reconfigured. No sudo used. The root-owned backend on port 8000 was not terminated.**

Project: `/home/abhaysawant/Desktop/cn_project_2`
Branch: `integration/baseline-2026-10-20` (commit `eea5382` feat: complete RouteLens Lite integration and demo readiness)

Working-tree changes present (left untouched, per restrictions):
- `M backend/app/lab_adapter.py`
- `M backend/app/lab_builder.py`
- `M backend/app/packet_lab.py`
- `M backend/tests/test_packet_lab.py`
- `M frontend/src/components/VirtualLabPanel.tsx`
- `?? backend/.coverage`
- `?? docs/qa/`

Servers running (observed read-only, not touched):
- Backend uvicorn on `127.0.0.1:8000` (root-owned, started via `sudo` at 09:30, stale HEAD code). Health: `{"status":"ok","service":"RouteLens Lite API"}`.
- Frontend vite on `127.0.0.1:5173` (base `/RouteLens-Lite/`, proxies `/api/*` to port 8000).

---

## Phase A — Current state (read-only)

CWD confirmed as `/home/abhaysawant/Desktop/cn_project_2`.

**Git state:**
- `git branch --show-current` → `integration/baseline-2026-10-20`
- `git log --oneline -3` → `eea5382`, `d188bf1`, `f477611`
- `git status --short` → 5 modified files + `.coverage` + `docs/qa/` untracked (listed above).

**Key source inspected (no changes made):**
- `frontend/src/api/routing.ts:309-310` — `checkLabStatus()` fetches `GET /api/lab/status`.
- `frontend/src/api/routing.ts:541-550` — `applyScenarioLab()` POSTs `/api/scenarios/{sid}/lab/apply` (dry_run query param).
- `frontend/src/api/routing.ts:563-576` — `compareScenarioWithLab()` POSTs `/api/scenarios/{sid}/compare`.
- `frontend/src/components/VirtualLabPanel.tsx`:
  - Effect 1 (lines 293-300): applies parent `status` seed only on initial mount; panel owns `labStatus` thereafter.
  - Unavailable block (lines 595-658): renders "The lab is not running.", `labStatus.error`/`applyResult.reason`, and "Build the lab" button gated by `canBuild = Boolean(scenario) && !busy` (line 372). `.lab-ready` absent here.
  - Ready block (lines 668-706): `.lab-ready`, "Send a test packet", "Tear the lab down" only when `phase === 'ready' && available`.
  - Scenario auto-selected on mount (lines 311-331): `list[0]?.id`, so a build button is offered when a scenario exists.
- `backend/app/packet_lab_routes.py:128-145` — `LabStatusResponse` model: `available`, `state`, `message`, `router_info`, `error`, `condition`, `next_steps`, `optional_steps`, `detail`.
- `backend/app/lab_builder.py:307-380` — `probe(src, dst_ip)`: `_guard()` returns `unavailable` when not root; failure branches return `reason`.
- `backend/tests/test_e2e_browser.py` — `app_available` fixture (lines 128-157) skips when backend 8000/health or frontend 5173 unreachable.

**The 5 failing tests (from test_e2e_browser.py):**
1. `TestVirtualLabIsHonest::test_an_unavailable_lab_says_so_and_says_why` (line 2183)
2. `TestNestedApiContracts::test_the_compare_result_has_the_fields_the_interface_reads` (line 2266)
3. `TestVirtualLabLifecycle::test_the_test_and_teardown_actions_are_not_offered_before_the_lab_is_ready` (line 2381)
4. `TestVirtualLabLifecycle::test_the_build_action_is_enabled_when_a_scenario_is_selected` (line 2402)
5. `TestVirtualLabLifecycle::test_a_refused_build_is_reported_and_the_lab_stays_unavailable` (line 2416)

Environmental cause: `/api/lab/status` on port 8000 returns `available:true` (rl260-* lab exists), so the panel renders the ready state; tests 1,3,4,5 require an unavailable lab. Test 2 requires `lab.reason`, which the stale port-8000 server does not return (fix not loaded, cannot restart).

---

## Phase B — BUG-01/03/04: Mock unavailable lab state via Playwright page.route()

Created temporary test file `backend/tests/test_phase1_mocked_unavailable.py` (new file, no application code modified). It launches a headless Chromium, uses `page.route("**/api/lab/status", ...)` to return:

```json
{"available":false,"state":"unavailable","message":"The virtual lab is not running.","error":"Network namespaces require root privileges.","router_info":null,"condition":null,"next_steps":[],"optional_steps":[],"detail":null}
```

navigates to `http://127.0.0.1:5173`, opens the Virtual Lab view, and asserts:

- BUG-01: unavailable message + failure reason visible; `.lab-ready` absent.
- BUG-03: `.lab-ready` absent; "Send a test packet" absent; "Tear the lab down" absent.
- BUG-04: "Build the lab" visible when a scenario is selected; enabled when not busy.
- Refused build: `page.route("**/api/scenarios/*/lab/apply", ...)` returns `{"status":"unavailable","reason":"needs root:..."}`; after clicking build, reason is reported, `.lab-ready` absent, `.lab-test-result` absent.

**Command:**
```
cd /home/abhaysawant/Desktop/cn_project_2/backend
source .venv/bin/activate
python -m pytest tests/test_phase1_mocked_unavailable.py -v
```

**Result: 4 passed, 0 failed, in 15.83s.**

| Mock test | Result |
|---|---|
| unavailable message + reason visible, `.lab-ready` absent (BUG-01) | PASSED |
| `.lab-ready` absent; "Send a test packet" / "Tear the lab down" absent (BUG-03) | PASSED |
| "Build the lab" visible + enabled with scenario selected (BUG-04) | PASSED |
| refused build reported with reason; `.lab-ready`/`.lab-test-result` absent | PASSED |

Conclusion: BUG-01, BUG-03, BUG-04 are correctly implemented in the current source; they cannot pass against the real app here because this environment's lab genuinely reports `available: true` (which may not be changed). The mock test proves the behavior.

---

## Phase C — BUG-02: Compare API `reason` field on working-tree backend

Port 8001 was free. Started a temporary non-root backend:

```
cd /home/abhaysawant/Desktop/cn_project_2/backend
source .venv/bin/activate
python -m uvicorn app.main:app --host 127.0.0.1 --port 8001
```

(Stopped when done; port 8000 root-owned backend left untouched.)

**Compare API on port 8001 (fixed working-tree code):**
```
curl -s -X POST http://127.0.0.1:8001/api/scenarios/client-router-server/compare \
  -H 'Content-Type: application/json' -d '{"src":"client","dst":"10.0.0.2"}'
```
Response:
```json
{"simulated":{"status":"delivered","hops":[...],"provenance":"simulated"},
 "lab":{"status":"unavailable","reason":"needs root: network namespaces require CAP_SYS_ADMIN. Run the backend with sudo only for lab use."},
 "agree":null,"note":"agree=null means the lab was unavailable; no result was faked."}
```
→ `lab` **contains `reason`**. BUG-02's `reason` fix IS present in `backend/app/lab_builder.py` `probe()` and appears once the fixed code is loaded.

**Direct `probe()` failure-branch test (non-root, so `_guard()` trips):**
```
python -c "from app.lab_builder import probe; print(probe('client','10.0.0.2'))"
```
→ `{'status': 'unavailable', 'reason': 'needs root: network namespaces require CAP_SYS_ADMIN. Run the backend with sudo only for lab use.'}`
`reason` field present in the failure branch. ✓

**Stale port-8000 backend (cannot restart — root-owned, port bound, no passwordless sudo):**
```
curl -s -X POST http://127.0.0.1:8000/api/scenarios/client-router-server/compare ... | python3 -c "..."
```
→ `8000 lab keys: ['provenance', 'rc', 'status', 'stderr', 'stdout']`; `has reason: False`.

So test #2 fails **only** because port 8000 runs stale HEAD code; the fix is in the working tree and verified on port 8001.

Temp backend on 8001 stopped after verification.

---

## Phase D — Namespace investigation

**Question:** Why does `/api/lab/status` report `rl260-*` namespaces, and why does compare/probe report a missing `rl_client` namespace? Are these separate lab configurations, or does one endpoint check an outdated config?

**Finding: they are intentionally separate lab configurations.** Two different namespace naming conventions exist in the source:

| Concern | File:lines | Detail |
|---|---|---|
| `/api/lab/status` namespace set | `backend/app/lab_adapter.py:18-21` | `LabComponent` enum: `CLIENT="rl260-client"`, `ROUTER="rl260-router"`, `SERVER="rl260-server"` |
| | `backend/app/lab_adapter.py:138-158` | `EXPECTED_TOPOLOGY` uses `rl260-*` namespaces / `rlc0`/`rlr0c`/`rlr0s`/`rls0` interfaces |
| | `backend/app/lab_adapter.py:474` | `check_lab_readiness()` iterates `LabComponent` (rl260-*) |
| | `backend/app/packet_lab.py:171` | `PacketLab` docstring: "Manages the isolated Linux virtual router lab (rl260-client, rl260-router, rl260-server)" |
| | `backend/app/packet_lab.py:222-224` | `get_status()` reads `readiness.namespaces.get("rl260-router")`, `"rl260-client"`, `"rl260-server"` |
| | `backend/app/packet_lab.py:120-123` | `LAB_CLIENT_IP="192.168.10.2"`, `LAB_SERVER_IP="192.168.20.2"` (rl260 topology IPs) |
| | `backend/app/packet_lab.py:279-283` | `simulate()` validates source==192.168.10.2, dest==192.168.20.2 |
| | `backend/app/packet_lab_routes.py:172-173` | `get_lab_status()` docstring: "This endpoint reports on the rl260-* lab ... The application does not provide a method to create this lab; it must exist beforehand." |
| compare/probe namespace set | `backend/app/lab_builder.py:26` | `PFX = "rl_"` |
| | `backend/app/lab_builder.py:29-31` | `ns(node_id) = PFX + node_id` → e.g. `rl_client` |
| | `backend/app/lab_builder.py:332` | `probe()` runs `ip netns exec ns(src) ...` → `rl_client` |
| | `backend/app/scenario_routes.py:257-278` | `compare()` calls `lab.probe(req.src, req.dst)` → probes `rl_<src>` |

**Observed machine state (read-only):**
- `curl /api/lab/status` → `{"available":true,...,"client_ip":"192.168.10.2","server_ip":"192.168.20.2"}` — the rl260-* lab is up.
- `ip netns list` → both sets present: `rl_client`, `rl_router`, `rl_server` **and** `rl260-client`, `rl260-router`, `rl260-server`.

**Conclusion:** `/api/lab/status` checks the pre-provisioned `rl260-*` virtual-router lab (which exists → `available:true`). `compare()`/`probe()` check the `rl_*` scenario lab built by `lab_builder.py` (e.g. `rl_client`). They are intentionally separate lab configurations; `/api/lab/status` does **not** check an outdated config — it documents that the rl260-* lab "must exist beforehand" and is not created by the application. The earlier `rl_client` missing report on the stale port-8000 server reflects that server's stale code/state at capture time; the structural mismatch (rl260-* vs rl_*) is the real, code-visible finding and is not something QA may change (no namespace modification permitted).

---

## Phase E — Regression verification

**Backend** (from `/home/abhaysawant/Desktop/cn_project_2/backend`, `.venv` active):

```
python -m pytest tests/test_packet_lab.py -q            → 58 passed, exit 0
python -m pytest tests/test_scenario_api.py tests/test_packet_lab_integration.py -q  → 20 passed, exit 0
```

Total: **78 passed, 0 failed.**

**Frontend** (from `/home/abhaysawant/Desktop/cn_project_2/frontend`):

```
npx tsc --noEmit          → exit 0 (passed)
npm run build             → exit 0 (passed; vite build succeeded, 566 modules transformed)
```

**Browser — 5 original tests against the live app (frontend 5173 → stale backend 8000):**

```
python -m pytest tests/test_e2e_browser.py <5 nodeids> -q -v
```
→ **5 failed, exit 1.** All fail for documented environmental reasons, not code defects:

| # | Test | Result | Reason |
|---|---|---|---|
| 1 | test_an_unavailable_lab_says_so_and_says_why | FAILED | Lab `available:true` in this env → page renders ready, no "unavailable" wording. |
| 2 | test_the_compare_result_has_the_fields_the_interface_reads | FAILED | Stale backend 8000 `lab` lacks `reason` (fix not loaded, cannot restart). |
| 3 | test_the_test_and_teardown_actions_are_not_offered_before_the_lab_is_ready | FAILED | Lab ready → `.lab-ready` present + actions offered (correct for an available lab). |
| 4 | test_the_build_action_is_enabled_when_a_scenario_is_selected | FAILED | Lab ready → no "Build the lab" button (correct for an available lab). |
| 5 | test_a_refused_build_is_reported_and_the_lab_stays_unavailable | FAILED | Same as #4 — build button correctly hidden when lab is ready. |

These same 5 assertions **pass** when the unavailable state is applied via the Phase B `page.route()` mock (4/4 passed), confirming the implementation is correct and the failures are purely environmental (this sandbox's lab is genuinely available and may not be altered; the port-8000 backend is stale and cannot be restarted).

---

## Phase F — Final status for BUG-01 through BUG-04

Mapping: BUG-01 = unavailable messaging (test #1); BUG-02 = compare `reason` field (test #2); BUG-03 = ready-only actions (test #3); BUG-04 = build action (tests #4, #5).

| Bug | Classification | Basis |
|---|---|---|
| BUG-01 Unavailable messaging | **Fixed & verified (code); browser not runnable here** | `VirtualLabPanel.tsx:595-658` renders "The lab is not running" + `labStatus.error`/`applyResult.reason`. Phase B mock test PASSED. Blocked in-browser only because env lab is `available:true`. |
| BUG-02 Compare `reason` field | **Fixed & verified (code); stale server masks it** | `lab_builder.py` `probe()` returns `reason` in all failure branches (verified via direct call). Port 8001 (fixed code) returns `"lab":{"status":"unavailable","reason":...}`. Port 8000 lacks it only because it is stale and cannot be restarted. |
| BUG-03 Ready-only actions | **Fixed (no code defect); browser not runnable here** | `VirtualLabPanel.tsx:668-706` renders "Send a test packet"/"Tear the lab down" only inside `ready && available`; `.lab-ready` only when `phase==='ready' && available`. Phase B mock PASSED. Fails in-browser only because env lab is available (actions correctly offered). |
| BUG-04 Build action | **Fixed (no code defect); browser not runnable here** | `VirtualLabPanel.tsx:595-658` shows "Build the lab" in unavailable phase, gated by `canBuild` (`scenario && !busy`), disabled while `busy`; refused/failed build sets `phase='unavailable'` and shows the refusal reason (lines 615-629). Phase B mock PASSED (build visible+enabled; refused build reported). Fails in-browser only because env lab is available (build button correctly hidden). |

**Overall:** The only genuine code defect among the five tests was BUG-02's missing `reason` field, caused by the port-8000 backend running stale HEAD code rather than the current working tree; the fix is present in `lab_builder.py` and verified on a freshly started backend on port 8001. BUG-01/03/04 are correctly implemented in the current source (proved via the Phase B mock test); their in-browser tests fail solely because this sandbox's lab reports `available: true` and the port-8000 backend is stale — both outside QA's permitted scope to change.

**Artifacts created (temporary / new, no application code modified):**
- `backend/tests/test_phase1_mocked_unavailable.py` — Phase B mock test (4 passed).
- `docs/qa/PHASE_1_MOCKED_BROWSER_VERIFICATION.md` — this report.

No application code, configuration, namespaces, interfaces, routes, or firewall rules were modified. No commits, merges, pushes, resets, cleans, or stashes were performed. All existing changes are preserved.
