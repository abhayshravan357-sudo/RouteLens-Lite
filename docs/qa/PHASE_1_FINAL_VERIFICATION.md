# Phase 1 Final Verification — RouteLens Lite

**QA/TestPilot agent. QA-only verification. No application code was modified. No commits, merges, or pushes. No network namespaces were touched.**

## 1. Individual root cause for each of the five previous browser failures

All five tests were run against the live application (frontend `127.0.0.1:5173`, backend `127.0.0.1:8000`). All five failed. The failures split into two distinct root causes:

### (a) Environment root cause — the lab is `available: true` here (tests #1, #3, #4, #5)

`curl -s http://127.0.0.1:8000/api/lab/status` returns:

```
{"available":true,"state":"ready","message":"The lab is up and ready for packets.",
 "router_info":{"interfaces":["lo","rlr0c","rlr0s"],...,"client_ip":"192.168.10.2","server_ip":"192.168.20.2"},...}
```

The task states the environment reports `available: true` because `rl260-*` namespaces exist; namespaces must not be deleted. Because the lab reports itself as available, the `VirtualLabPanel` renders the **ready** state (`.lab-ready` present, "Send a test packet" and "Tear the lab down" buttons present, no "Build the lab" button). The four unavailable-lab tests therefore cannot pass in this environment without mocking the unavailable state (which would require modifying application code or deleting namespaces — both forbidden).

| Test | Line | Assertion that failed | Why it failed |
|------|------|-----------------------|---------------|
| `test_an_unavailable_lab_says_so_and_says_why` | 2188 | `the lab view did not say the lab is unavailable` | Page renders the ready state (lab `available:true`), so the body contains no "unavailable"/"not ready" wording. |
| `test_the_test_and_teardown_actions_are_not_offered_before_the_lab_is_ready` | 2393 | `the lab claims to be ready without namespaces` (`assert page.locator(".lab-ready").count() == 0`) | Lab is ready → `.lab-ready` count is 1, expected 0. |
| `test_the_build_action_is_enabled_when_a_scenario_is_selected` | 2411 | `there is no 'Build the lab' action` (`assert build.count() == 1`) | Lab is ready → the panel shows test/teardown, not the build button; count is 0. |
| `test_a_refused_build_is_reported_and_the_lab_stays_unavailable` | 2426 | `there is no 'Build the lab' action` (`assert build.count() == 1`) | Same as above — build button not rendered when the lab is ready. |

### (b) Stale-server root cause — backend 8000 is running uncommitted-fix-free HEAD code (test #2)

The backend uvicorn on port 8000 (pid 352525) was started as `root` via `sudo` at 09:30 and loaded the code at HEAD commit `eea5382`. The working tree contains **uncommitted fixes** that were never loaded into that process:

- `backend/app/lab_builder.py` — `probe()` now returns a `reason` field in the timeout / permission_denied / unreachable / default branches.
- `backend/app/lab_adapter.py` — tcpdump capture-statistics parsing fix.
- `backend/app/packet_lab.py` — `capture_count` 10 → 6.
- `frontend/src/components/VirtualLabPanel.tsx` — lifecycle/status handling.

I cannot restart the backend on port 8000: the process is root-owned, I have no passwordless sudo (`sudo -n` requires a password), and port 8000 is bound. Hence the running backend does **not** include the `lab_builder.py` `reason` fix.

`curl -s -X POST http://127.0.0.1:8000/api/scenarios/client-router-server/compare -d '{"src":"client","dst":"10.0.0.2"}'` returned:

```
"lab":{"status":"unreachable","rc":255,"stdout":"","stderr":"Cannot open network namespace \"rl_client\": No such file or directory\n","provenance":"lab"}
```

There is **no `reason` field**.

| Test | Line | Assertion that failed | Why it failed |
|------|------|-----------------------|---------------|
| `test_the_compare_result_has_the_fields_the_interface_reads` | 2287 | `the lab result has no reason to give` (`assert "reason" in lab`) | Stale backend 8000 returns `lab` without `reason`. |

I verified the fix independently by starting a **second backend on port 8001 from the working tree** (fixed `lab_builder.py`, running as my non-root user). The same compare call returned:

```
"lab":{"status":"unavailable","reason":"needs root: network namespaces require CAP_SYS_ADMIN. Run the backend with sudo only for lab use."}
```

So the `reason` fix IS present in the current source and DOES appear once the fixed code is loaded; it is absent only because the port-8000 server is stale and cannot be restarted.

## 2. Frontend and backend server verification

### Backend (port 8000)
- Process: `root 352525 .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000` (started 09:30 via `sudo`; two wrapper `sudo` procs 352523/352524).
- Port 8000: `LISTEN 127.0.0.1:8000`.
- Health: `curl -s http://127.0.0.1:8000/health` → `{"status":"ok","service":"RouteLens Lite API"}` (HTTP 200).
- **Stale:** loaded HEAD code at 09:30; working-tree fixes not loaded. Cannot restart (root-owned, no sudo, port bound).

### Frontend (port 5173)
- Process: `abhaysawant 288797 node .../vite` (`npm run dev`, started Oct 24).
- Port 5173: `LISTEN 127.0.0.1:5173`.
- Vite dev server reads source on each request (HMR), so it reflects the current source including the `VirtualLabPanel.tsx` fix — **not stale**.
- `curl -s -D - http://127.0.0.1:5173/` → HTTP 302 to `/RouteLens-Lite/` (the configured `base`). The app serves.
- Vite proxies `/api/lab`, `/api/scenarios`, etc. to `http://127.0.0.1:8000` (per `frontend/vite.config.ts`), so frontend API calls reach the **stale** backend.

## 3. Comparison API response verification (direct curl)

Directly against the running backend (port 8000, stale):

```
curl -s -X POST http://127.0.0.1:8000/api/scenarios/client-router-server/compare \
  -H 'Content-Type: application/json' -d '{"src":"client","dst":"10.0.0.2"}'
```

Response `lab` object:
```
{"status":"unreachable","rc":255,"stdout":"","stderr":"Cannot open network namespace \"rl_client\": No such file or directory\n","provenance":"lab"}
```
→ `lab` contains `status`, `rc`, `stdout`, `stderr`, `provenance` but **NO `reason`**.

Against the fixed working-tree backend on port 8001:
```
"lab":{"status":"unavailable","reason":"needs root: network namespaces require CAP_SYS_ADMIN. ..."}
```
→ `lab` **does** contain `reason`. This confirms test #2's failure is solely due to the stale port-8000 server, not a missing code fix.

## 4. How unavailable state was simulated (if possible)

**Real unavailable state could not be established.** The task forbids deleting namespaces, modifying network interfaces, and running privileged commands. The environment's lab is genuinely `available: true` (`rl260-*` namespaces exist), and `/api/lab/status` reports ready.

**What IS possible without modifying application code:** a test-only mock of the API boundary.
- The frontend's `checkLabStatus()` (`frontend/src/api/routing.ts:309`) fetches `/api/lab/status`. A temporary test could use Playwright `page.route()` to intercept that call and return `{"available":false, ...}` with a reason, simulating the unavailable condition for the browser tests.
- Alternatively a temporary test could call the backend through a monkeypatched client.
- This would **not** modify any application code; it would be a new throwaway test file. It was not executed because the task is QA-only and the existing five tests assert against the real running app, which reports available.

## 5. Results for all five original tests

Run command (from `/home/abhaysawant/Desktop/cn_project_2/backend`, venv active):
```
python -m pytest tests/test_e2e_browser.py \
  ::TestVirtualLabIsHonest::test_an_unavailable_lab_says_so_and_says_why \
  ::TestNestedApiContracts::test_the_compare_result_has_the_fields_the_interface_reads \
  ::TestVirtualLabLifecycle::test_the_test_and_teardown_actions_are_not_offered_before_the_lab_is_ready \
  ::TestVirtualLabLifecycle::test_the_build_action_is_enabled_when_a_scenario_is_selected \
  ::TestVirtualLabLifecycle::test_a_refused_build_is_reported_and_the_lab_stays_unavailable \
  -q -v
```
Exit code: 1. Result: **5 failed, 0 passed, 0 skipped** (in 25.87s). No test was skipped because `app_available` succeeded (both 8000/health and 5173 respond).

| # | Test | Result | Reason |
|---|------|--------|--------|
| 1 | `test_an_unavailable_lab_says_so_and_says_why` | FAILED | Lab `available:true` in this env → page shows ready, not unavailable. |
| 2 | `test_the_compare_result_has_the_fields_the_interface_reads` | FAILED | Stale backend 8000 `lab` lacks `reason` (fix not loaded). |
| 3 | `test_the_test_and_teardown_actions_are_not_offered_before_the_lab_is_ready` | FAILED | Lab ready → `.lab-ready` present, actions offered (correct behavior for an available lab). |
| 4 | `test_the_build_action_is_enabled_when_a_scenario_is_selected` | FAILED | Lab ready → no "Build the lab" button shown (correct for an available lab). |
| 5 | `test_a_refused_build_is_reported_and_the_lab_stays_unavailable` | FAILED | Lab ready → no "Build the lab" button shown (correct for an available lab). |

## 6. Parent synchronization assessment

**Inspected:** `frontend/src/components/VirtualLabPanel.tsx` Effect 1 (lines 293–300) and `frontend/src/App.tsx` `loadLabStatus()` (lines 129–159).

- `App.tsx` calls `loadLabStatus()` once when `backendConnected === true` (and on manual refresh), then passes the resulting `LabStatusResponse` down as the `status` prop to `VirtualLabPanel` (line 647: `status={labStatus}`).
- `VirtualLabPanel` Effect 1 (lines 293–300) applies the parent's `status` **only on initial mount**: `if (labStatus !== null) return;`. After mount the panel owns `labStatus` and re-reads it from the backend via `refreshStatus()` (`checkLabStatus()`) whenever the lab may have changed (after build/teardown/test).
- Conclusion: parent status updates after mount are **intentionally ignored** by design — the panel is the source of truth for the lab lifecycle, and the parent only seeds the initial reading. This is safe for the current architecture because every lab-mutating action (build/teardown/test) re-reads status from the backend. External parent updates after mount are **not required**. No component change is needed.

## 7. Remaining limitations

1. **Backend on port 8000 cannot be restarted.** It is root-owned, started with sudo, and port 8000 is bound. I have no passwordless sudo. Therefore the fixed `lab_builder.py` (and other working-tree fixes) cannot be loaded into the running port-8000 server. Verification of the fix was instead done by starting a temporary backend on port 8001 from the working tree, then stopping it.
2. **Unavailable-lab browser tests cannot pass in this environment.** The lab is genuinely `available: true` (`rl260-*` namespaces), which must not be deleted. Tests #1, #3, #4, #5 require an unavailable lab; they can only be exercised here via a test-only API-boundary mock (Playwright route interception of `/api/lab/status`), which was not run.
3. **Browser tests were run against the stale backend.** Test #2's failure would disappear once the port-8000 backend is restarted with the fixed code.
4. No application code was modified, committed, or pushed, per the task constraints. All regression evidence below is from the current working tree.

## 8. Final status for BUG-01 through BUG-04

Mapping: BUG-01 = unavailable messaging (test #1); BUG-02 = compare `reason` field (test #2); BUG-03 = ready-only actions (test #3); BUG-04 = build action (tests #4, #5).

| Bug | Classification | Basis |
|-----|----------------|-------|
| BUG-01 Unavailable messaging | **Fixed and verified** (code/API); browser not runnable here | `VirtualLabPanel.tsx` renders "The lab is not running" + `labStatus.error`/`applyResult.reason` in the unavailable phase. Fixed backend (8001) returns `available:false` with a detailed reason (verified via curl). Browser test blocked because this env's lab is `available:true`. |
| BUG-02 Compare result `reason` field | **Fixed and verified** | `backend/app/lab_builder.py` `probe()` returns `reason` in all failure branches (verified in source). Port 8001 (fixed code) returns `"lab":{"status":"unavailable","reason":...}`. Port 8000 lacks it only because it is stale and cannot be restarted. |
| BUG-03 Ready-only actions | **Fixed** (no code defect); browser not runnable here | `VirtualLabPanel.tsx` renders "Send a test packet"/"Tear the lab down" only inside the `ready && available` block, and `.lab-ready` only when `phase === 'ready' && available`. Test #3 fails here only because the env lab is available (actions are correctly offered). |
| BUG-04 Build action | **Fixed** (no code defect); browser not runnable here | `VirtualLabPanel.tsx` shows "Build the lab" in the unavailable phase, gated by `canBuild` (`scenario && !busy`), disabled while `busy`, and a refused/failed build sets `phase='unavailable'` and shows the refusal reason. Test #4/#5 fail here only because the env lab is available (build button correctly hidden). |

**Overall:** The only genuine code defect among the five tests was BUG-02's missing `reason` field, caused by the port-8000 backend running stale HEAD code rather than the current working tree; the fix is present in `lab_builder.py` and verified on a freshly started backend. BUG-01/03/04 are correctly implemented in the current source; their tests fail solely because this sandbox's lab reports `available: true`, which the task forbids me from changing. No application code was modified, and no commits, merges, or pushes were made.

## Regression test results (Phase 7)

Run from `/home/abhaysawant/Desktop/cn_project_2/backend` with `.venv` activated:

```
python -m pytest tests/test_packet_lab.py -q -v          -> 58 passed, exit 0
python -m pytest tests/test_scenario_api.py tests/test_packet_lab_integration.py -q -v  -> 20 passed, exit 0
```

Frontend (from `/home/abhaysawant/Desktop/cn_project_2/frontend`):

```
npx tsc --noEmit                                          -> exit 0 (passed)
npm run build                                             -> exit 0 (passed; vite build succeeded)
```

Browser:

```
python -m pytest tests/test_e2e_browser.py <5 target tests> -q -v  -> 5 failed, exit 1 (reasons documented above)
```
