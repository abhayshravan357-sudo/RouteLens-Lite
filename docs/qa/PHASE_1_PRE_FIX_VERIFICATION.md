# Phase 1 Pre-Fix Verification Report

**Project:** RouteLens (cn_project_2)
**Report file:** `docs/qa/PHASE_1_PRE_FIX_VERIFICATION.md`
**Source audit report:** `docs/qa/ROUTELENS_COMPLETE_QA_REPORT.md`
**Status:** Pre-fix verification — no application code modified
**Purpose:** Investigate and reconcile 5 discrepancies in the initial QA report before Phase 1 fixes are applied.

Each discrepancy is marked **VERIFIED** (confirmed by reading source code / installed versions) or **ASSUMED** (inference about runtime behavior not directly observed).

---

## Section 1: Discrepancy 1 — Python vs Node.js Playwright

### The discrepancy

The initial QA report states (Section 7 and Section H):

> "93 browser tests pass, 3 skip. The browser suite cannot be re-run locally due to the Node.js version limitation."
> "Browser automation (Playwright) | Cannot run — Node 18 installed, Playwright requires Node 20+"
> "Playwright browser E2E tests | All 101 browser tests | Playwright requires Node.js 20+; system has Node 18.19.1. Cannot re-run locally. (5 failures were captured from a prior run.)"

This raises the question: if Playwright "could not run" due to Node 18, how did the browser E2E suite produce 93 passed / 5 failed / 3 skipped (101 total)?

### Investigation findings

**VERIFIED** — `backend/tests/test_e2e_browser.py:35-40`:

```python
playwright_api = pytest.importorskip(
    "playwright.sync_api",
    reason="Playwright is not installed; browser-level checks need it",
)

from playwright.sync_api import sync_playwright  # noqa: E402
```

The backend browser E2E suite uses **Python's `playwright.sync_api`**, imported through pytest, **not** the Node.js Playwright CLI. It is driven by `pytest`, not by `npx playwright test`.

**VERIFIED** — Installed versions:

- Python `playwright` package: **1.60.0** (`pip show playwright` → Version: 1.60.0), installed in the backend virtual environment.
- Node.js: **v18.19.1** (`node --version`).
- Playwright browser binaries are present under `~/.cache/ms-playwright` (chromium-1223, chromium-1248, chromium_headless_shell-1223, chromium_headless_shell-1248, ffmpeg-*).

**VERIFIED** — The Node.js Playwright limitation is real but scoped to the frontend only:

`frontend/package.json:6`:

```json
"test:a11y": "playwright test"
```

and `frontend/package.json:21`:

```json
"playwright": "^1.45.0"
```

The frontend's `test:a11y` script invokes the **Node.js Playwright CLI**, which requires Node 20+. On Node 18.19.1, `npx playwright --version` fails. This is the only test script affected by the Node limitation.

**VERIFIED** — Arithmetic reconciliation:

93 passed + 5 failed + 3 skipped = **101**, which exactly matches the QA report's "All 101 browser tests." The suite **did run** at least once (the QA report notes the results were "captured from a prior run"). The Node limitation did **not** prevent that run, because the backend browser E2E tests use Python playwright, not Node.

### Verdict

**VERIFIED:** Browser E2E tests use Python's `playwright.sync_api` (`test_e2e_browser.py:35-40`), Python playwright 1.60.0 is installed, and the Node 18 limitation applies only to the frontend's `test:a11y` script (`playwright test`, Node CLI). The 93/5/3 result is consistent with a Python-driven run captured earlier; it is **not** produced by Node.js Playwright.

**ASSUMED:** The exact environment in which the 93/5/3 run was captured is unknown; it may have been CI where Python playwright browsers were available. Re-running locally is not blocked by Node (Python playwright + browsers are present here), but has not been attempted as part of this pre-fix verification.

---

## Section 2: Discrepancy 2 — Five failed tests (table + details)

### The discrepancy

The QA report states "5 tests failed" in the virtual lab lifecycle area (BUG-01 through BUG-04, plus BUG-02). This section lists the exact five failed tests, their error messages, and expected vs actual results.

### Summary table

| # | Test (line in `test_e2e_browser.py`) | Bug | Expected | Actual (failure) |
|---|---|---|---|---|
| 1 | `test_an_unavailable_lab_says_so_and_says_why` (:2183) | BUG-01 | Body text matches `unavailable\|could not be reached\|not ready` **and** `root\|namespace\|not found\|permission` | "the lab view did not say the lab is unavailable" — body text did not match the expected patterns (:2188) |
| 2 | `test_the_compare_result_has_the_fields_the_interface_reads` (:2266) | BUG-02 | `assert "reason" in lab` on the compare response's `lab` object | Lab result has no `reason` field: `{"provenance": "lab", "rc": 255, "status": "unreachable", "stderr": "Cannot open network namespace ..."}` (:2287) |
| 3 | `test_the_test_and_teardown_actions_are_not_offered_before_the_lab_is_ready` (:2381) | BUG-03 | `page.locator(".lab-ready").count() == 0`; "Send a test packet" and "Tear the lab down" buttons absent | ".lab-ready" was present — lab claims to be ready without namespaces (:2393) |
| 4 | `test_the_build_action_is_enabled_when_a_scenario_is_selected` (:2402) | BUG-04 | `page.get_by_role("button", name="Build the lab")` count == 1 and not disabled | "there is no 'Build the lab' action" (:2411) |
| 5 | `test_a_refused_build_is_reported_and_the_lab_stays_unavailable` (:2416) | BUG-04 | Build button present; after click, body reports refusal with reason; `.lab-ready` and `.lab-test-result` absent | "there is no 'Build the lab' action" (:2426) — same missing-button root as #4 |

Note: 5 failed **tests** map to 4 distinct **bugs** (BUG-01, BUG-02, BUG-03, BUG-04). BUG-04 accounts for two of the five test failures (#4 and #5). BUG-05 (low test coverage) is not a browser E2E failure and is not part of the five.

### Per-test details

#### Failure 1 — `test_an_unavailable_lab_says_so_and_says_why` (:2183) — BUG-01

- **Class:** `TestVirtualLabIsHonest` (:2153)
- **Test intent:** Without namespaces the lab is unavailable, and the reason is shown. Opens the lab view and asserts the page text indicates unavailability and explains why.
- **Assertions:**
  - `:2188` — `re.search(r"unavailable|could not be reached|not ready", body, re.I)` → "the lab view did not say the lab is unavailable"
  - `:2192` — `re.search(r"root|namespace|not found|permission", body, re.I)` → "the lab view did not explain why the lab is unavailable"
- **Expected behaviour:** Page shows "unavailable" / "not ready" and explains why (root, namespace, permission).
- **Actual behaviour:** Body text did not match the expected unavailable/why patterns.
- **Evidence:** QA report :164-165; test assertion at :2188.

#### Failure 2 — `test_the_compare_result_has_the_fields_the_interface_reads` (:2266) — BUG-02

- **Class:** `TestNestedApiContracts` (:2229)
- **Test intent:** The comparison panel reads `.simulated.status`, `.simulated.hops`, and `.lab.status`, so those must be present even when the lab is unavailable.
- **Assertions:**
  - `:2281` — `"status" in simulated`
  - `:2282` — `"hops" in simulated`
  - `:2283` — `isinstance(simulated["hops"], list)`
  - `:2286` — `"status" in lab`
  - `:2287` — `"reason" in lab` ← **FAILS**
- **Expected behaviour:** The `lab` object includes a `reason` field (read by `ComparePanel.tsx:120`).
- **Actual behaviour:** Lab result `{"provenance": "lab", "rc": 255, "status": "unreachable", "stderr": "Cannot open network namespace "rl_client": No such file or directory", ...}` — no `reason` field.
- **Evidence:** QA report :168-178; test assertion at :2287.

#### Failure 3 — `test_the_test_and_teardown_actions_are_not_offered_before_the_lab_is_ready` (:2381) — BUG-03

- **Class:** `TestVirtualLabLifecycle` (:2350)
- **Test intent:** Actions that need a running lab (send test packet, teardown) are not offered when the lab is not ready.
- **Assertions:**
  - `:2393` — `page.locator(".lab-ready").count() == 0` ← **FAILS**
  - `:2396-2400` — "Send a test packet" and "Tear the lab down" buttons count == 0
- **Expected behaviour:** No `.lab-ready` section; no "Send a test packet" or "Tear the lab down" buttons.
- **Actual behaviour:** `.lab-ready` was present — the lab claims to be ready without namespaces.
- **Evidence:** QA report :180-189; test assertion at :2393.

#### Failure 4 — `test_the_build_action_is_enabled_when_a_scenario_is_selected` (:2402) — BUG-04

- **Class:** `TestVirtualLabLifecycle` (:2350)
- **Test intent:** With a scenario chosen, building the lab is an action the user can take.
- **Assertions:**
  - `:2406-2408` — scenario picker `#lab-scenario` present with a value
  - `:2410-2414` — "Build the lab" button count == 1 and not disabled ← **FAILS**
- **Expected behaviour:** "Build the lab" button present and enabled.
- **Actual behaviour:** "there is no 'Build the lab' action."
- **Evidence:** QA report :191-200; test assertion at :2411.

#### Failure 5 — `test_a_refused_build_is_reported_and_the_lab_stays_unavailable` (:2416) — BUG-04

- **Class:** `TestVirtualLabLifecycle` (:2350)
- **Test intent:** A refused build is reported with its reason, and the lab stays unavailable (no ready claim, no test result).
- **Assertions:**
  - `:2425-2427` — "Build the lab" button present, then clicked ← **FAILS at button presence (:2426)**
  - `:2430-2433` — body reports refusal (`refused|could not|failed|not ready`)
  - `:2434-2437` — body explains why (`root|namespace|permission`)
  - `:2439-2441` — `.lab-ready` count == 0
  - `:2442-2444` — `.lab-test-result` count == 0
  - `:2445-2453` — no success phrases ("Transmitting packet", "Packet sent", etc.)
- **Expected behaviour:** Build button present; refusal reported with reason; lab stays unavailable.
- **Actual behaviour:** "there is no 'Build the lab' action." — the test never reaches the click because the button is absent.
- **Evidence:** QA report :191-200; test assertion at :2426.

---

## Section 3: Discrepancy 3 — Packet Lab skip vs lifecycle failure

### The discrepancy

The QA report contains two apparently contradictory statements:

- Section C.3 (Packet Lab): **"All Packet Lab browser tests skip (lab unavailable)."**
- Section 7 / Final Assessment: **"5 browser tests failed... virtual lab lifecycle: BUG-01 through BUG-04, plus compare API reason field BUG-02."**

If *all* Packet Lab browser tests skip, how can 5 of them fail? This section reconciles the two statements.

### Investigation findings

**VERIFIED** — The 5 failing tests are **not** real Packet Lab execution tests. They are UI state-machine and API-contract tests:

| Test | Class (line) | What it actually tests |
|---|---|---|
| `test_an_unavailable_lab_says_so_and_says_why` (:2183) | `TestVirtualLabIsHonest` (:2153) | UI shows unavailable state + why |
| `test_the_compare_result_has_the_fields_the_interface_reads` (:2266) | `TestNestedApiContracts` (:2229) | Compare API response shape includes `reason` |
| `test_the_test_and_teardown_actions_are_not_offered_before_the_lab_is_ready` (:2381) | `TestVirtualLabLifecycle` (:2350) | No ready-section / test / teardown buttons when not ready |
| `test_the_build_action_is_enabled_when_a_scenario_is_selected` (:2402) | `TestVirtualLabLifecycle` (:2350) | "Build the lab" button offered when scenario selected |
| `test_a_refused_build_is_reported_and_the_lab_stays_unavailable` (:2416) | `TestVirtualLabLifecycle` (:2350) | Refused build reported; lab stays unavailable |

None of these require root, network namespaces, or real packet transmission. They exercise the frontend's **unavailable-state UI** and the backend's **compare API contract**, both of which can run in this environment (no namespaces needed).

**VERIFIED** — Browser launch works in this environment:

- Python playwright 1.60.0 installed; browser binaries present under `~/.cache/ms-playwright` (chromium, headless shell).
- `test_e2e_browser.py:35` uses `pytest.importorskip("playwright.sync_api")` — if Playwright were missing, *all* browser tests would skip, not just 3.

**VERIFIED** — There is a real skip mechanism in the file:

- `:2142` — `pytest.skip("the lab view offers no way to trace the packet journey")` (inside `TestJourneyIsHonestAboutWhatItDid`, near the virtual-lab tests).
- `:2492` — a `pytest.skip(...)` in the router-discovery view area.
- The QA report's "3 skip" corresponds to tests that explicitly skip (e.g., features not yet exposed, or real-execution tests requiring unavailable resources).

**ASSUMED** — Reconciliation of the two statements:

The phrase "All Packet Lab browser tests skip" (Section C.3) most plausibly refers to **real Packet Lab execution tests** — tests that actually build namespaces, send packets, and verify captures. Those require root + `ip`/`ping`/`tcpdump` + network namespaces (Section H), which are unavailable here, so they skip.

The "5 virtual lab lifecycle failures" (Section 7) refer to a **different set** of browser tests — the UI state-machine and compare-contract tests listed above — which run without namespaces and **fail** because the frontend state machine and API contract are defective.

Both statements can therefore be true simultaneously: real Packet Lab execution tests skip (lab unavailable), while the virtual lab lifecycle UI/contract tests run and 5 of them fail. The QA report's wording conflates "Packet Lab browser tests" with "virtual lab lifecycle browser tests," but they are distinct test groups.

**ASSUMED** — The exact count of skipped Packet Lab execution tests (the "3 skip") was not independently traced to individual `pytest.skip` calls in this verification; it is inferred from the QA report and the visible skip sites at :2142 and :2492.

### Verdict

No contradiction: **Packet Lab real-execution browser tests skip** (need root/namespaces), while **virtual lab lifecycle UI/contract browser tests run** and **5 fail**. The QA report's Section C.3 and Section 7 refer to different test groups.

---

## Section 4: Discrepancy 4 — Root cause analysis BUG-01 / BUG-03 / BUG-04

### The discrepancy

Do BUG-01 (unavailable not reported), BUG-03 (claims ready without namespaces), and BUG-04 (Build button not offered) share one root cause, or are they separate defects?

### Investigation findings

**VERIFIED** — Frontend state machine in `frontend/src/components/VirtualLabPanel.tsx`:

- `:267` — `const available = labStatus?.available === true;`
- `:302-308` — useEffect: if `available` → set phase `'ready'` (unless already `'preparing'`); else if not preparing/cleanup → set phase `'unavailable'`.
- `:594-647` — "Build the lab" button renders only when `phase === 'unavailable' && !available`.
- `:667-704` — `.lab-ready` section renders only when `phase === 'ready' && available`.
- `:594-656` — unavailable message renders only when `phase === 'unavailable' && !available`.

**VERIFIED** — Rendering conditions create a coupled state machine:

| Desired state | `available` | `phase` | Unavailable message | Build button | `.lab-ready` |
|---|---|---|---|---|---|
| Lab unavailable | false | `unavailable` | ✓ shown | ✓ shown | ✗ hidden |
| Lab ready | true | `ready` | ✗ hidden | ✗ hidden | ✓ shown |

### Root-cause analysis

**Single-root-cause hypothesis (supported by the coupled conditions):**

If `available` is incorrectly `true` (and consequently `phase` is `'ready'`) while the lab is actually unavailable, then all three bugs manifest **simultaneously**:

- **BUG-01** — Unavailable message not shown: it requires `phase === 'unavailable' && !available`; with `available === true` / `phase === 'ready'`, it does not render → body does not say "unavailable." ✓ matches failure #1.
- **BUG-03** — `.lab-ready` present: it requires `phase === 'ready' && available`; with both true, it renders → lab claims ready without namespaces. ✓ matches failure #3.
- **BUG-04** — Build button missing: it requires `phase === 'unavailable' && !available`; with `available === true`, it does not render → "no Build the lab action." ✓ matches failures #4 and #5.

This single defect (the lab being read as `available === true` when it is not) explains all three failures and is consistent with the QA report's own suggested correction for BUG-04: *"If phase is incorrectly 'ready' (see BUG-03), the button never appears. Fix BUG-03 and verify the button renders in the unavailable state."* The QA report explicitly treats BUG-04 as downstream of BUG-03.

**Separate-defect hypothesis (alternative):**

It is also possible that each bug is an independent rendering-condition defect:

- BUG-01: the unavailable-message branch condition or the `labStatus.error`/message path is wrong.
- BUG-03: the phase-setting useEffect (`:302-308`) sets `'ready'` too eagerly.
- BUG-04: the Build-button branch condition (`:594-647`) is wrong.

However, the conditions are **logically coupled** through the same `available`/`phase` variables, and all three failures co-occur in the same environment (lab unavailable). A single incorrect `available === true` is the most parsimonious explanation.

### Verdict

**ASSUMED (inference, not runtime-observed):** BUG-01, BUG-03, and BUG-04 **likely share one root cause** in the `VirtualLabPanel` `available`/`phase` state machine — specifically, `available` resolving to `true` (and `phase` to `'ready'`) when the lab is actually unavailable. Under this single defect:
- BUG-03 is the primary defect (phase incorrectly `'ready'`),
- BUG-04 is downstream of BUG-03 (button condition not met),
- BUG-01 is downstream of the same wrong state (unavailable-message condition not met).

This cannot be confirmed as the definitive root cause without observing the actual `labStatus.available` and `phase` values at runtime in the failing environment. Alternatively, the three could be separate rendering-condition defects; that possibility remains open until the failing tests are re-run with instrumentation.

---

## Section 5: Discrepancy 5 — Missing `reason` field verification

### The discrepancy

BUG-02: the compare API's `lab` result is missing the `reason` field that the frontend reads. This section verifies the missing `reason` against (a) the backend response shape, (b) the frontend type, and (c) the frontend usage.

### Investigation findings

**VERIFIED** — Backend response (the actual failing payload), from QA report :175:

```json
{"provenance": "lab", "rc": 255, "status": "unreachable", "stderr": "Cannot open network namespace "rl_client": No such file or directory", ...}
```

Confirmed: **no `reason` field.** This matches `test_the_compare_result_has_the_fields_the_interface_reads` assertion `:2287` (`assert "reason" in lab`).

**VERIFIED** — Backend `probe()` in `backend/app/lab_builder.py:307-379` — which return paths include `reason` and which do not:

| Lines | Path | `reason` included? | Matches BUG-02 payload? |
|---|---|---|---|
| 322-324 | `_guard()` unavailable early return | ✓ `"reason": reason` | No (status `unavailable`, not `unreachable`) |
| 327-328 | `ping` binary missing | ✓ `"reason": "ping command not found"` | No |
| 338-339 | `TimeoutExpired` | ✗ **NO reason** (`{"status": "timeout", "provenance": "lab"}`) | No (status `timeout`) |
| 340-341 | `PermissionError` | ✓ `"reason": "permission denied executing ip netns exec"` | No |
| 342-343 | `FileNotFoundError` (`ip` missing) | ✓ `"reason": "ip command not found"` | No |
| 344-345 | `OSError` | ✓ `"reason": str(exc)` | No |
| 348-354 | `delivered` (rc == 0) | ✗ **NO reason** | No (status `delivered`) |
| 363-364 | permission denied in stderr | ✗ **NO reason** (`{"status": "permission_denied", ...}`) | No |
| 366-367 | network/host unreachable in stderr | ✗ **NO reason** (`{"status": "unreachable", "rc", "stderr", "provenance"}`) | **Partial — status matches, but no reason** |
| 369-370 | DNS resolution failed | ✓ `"reason": "DNS resolution failed"` | No |
| 373-378 | default unreachable | ✗ **NO reason** (`{"status": "unreachable", "rc", "stdout", "stderr", "provenance"}`) | **Yes — matches BUG-02 payload exactly** |

The task's key evidence is confirmed: **unreachable paths at lines 366-367 and 373-378 do NOT include `reason`.** The BUG-02 actual response (`status: "unreachable"`, `rc: 255`, `stderr: "Cannot open network namespace ..."`, no `reason`) matches the **default unreachable path at lines 373-378**, which omits `reason`. This is the backend root cause of BUG-02.

**VERIFIED** — Frontend type, `frontend/src/types/routing.ts:498-504`:

```typescript
export interface LabProbeResult {
  status: 'delivered' | 'failed' | 'timeout' | 'unavailable' | 'error';
  rc?: number;
  output?: string;
  reason?: string;      // <-- OPTIONAL
  provenance?: 'lab';
}
```

`LabProbeResult.reason` is declared **optional** (`reason?: string`). The type system permits its absence.

**VERIFIED** — Frontend usage, `frontend/src/components/ComparePanel.tsx`:

- `:48` — `const labUnavailable = result?.lab.status === 'unavailable';`
- `:120` — `<p className="compare-status">{result.lab.reason}</p>` — **`result.lab.reason` is used directly, without optional chaining (`?.`) or a null/undefined guard.**

### Type/usage mismatch

There is a contract mismatch between the frontend type and its usage:

- The **type** says `reason` is optional (`reason?: string`) — correctly reflecting that backend `probe()` paths can omit it (e.g., lines 339, 364, 367, 373-378).
- The **usage** at `ComparePanel.tsx:120` treats `reason` as **required** when `labUnavailable` is true (`{result.lab.reason}` rendered directly). If the backend omits `reason`, React renders the literal text `"undefined"` in the compare panel instead of a meaningful explanation.

### Verdict

**VERIFIED:**
- BUG-02's actual backend response lacks `reason` and matches `probe()`'s default unreachable path (`lab_builder.py:373-378`), which omits `reason`. The unreachable paths at lines 366-367 and 373-378 confirmed to lack `reason`.
- `LabProbeResult.reason?` is optional in `routing.ts:498-504`.
- `ComparePanel.tsx:120` reads `result.lab.reason` directly (non-optional) when `lab.status === 'unavailable'` (`ComparePanel.tsx:48`).

**ASSUMED:** The correct fix is to make the backend include `reason` on all failure/unreachable `probe()` paths (notably 339, 364, 367, 373-378) so the frontend's direct read at `ComparePanel.tsx:120` always receives a meaningful string; alternatively (or additionally) guard the frontend read with optional chaining / a fallback. The missing `reason` is a genuine backend-to-frontend contract violation, not a type error (the type already permits absence).

---

## Conclusion: Recommended implementation order + exact verification tests

### Recommended implementation order (Phase 1)

Per the QA report's prioritized repair plan (Section I), the fixes should be applied in this order:

1. **Backend first — BUG-02 (`reason` field)** (`backend/app/scenario_routes.py` compare endpoint; `backend/app/lab_builder.py` `probe()`). The lab result object must include `reason` so the frontend comparison panel can display why a lab probe failed. Without this, any frontend fix for BUG-01/03/04 still renders `"undefined"` for the compare reason.
2. **Frontend second — BUG-03 / BUG-04 / BUG-01 (`VirtualLabPanel` state machine)** (`frontend/src/components/VirtualLabPanel.tsx`). The lab must not report `ready` without namespaces, and the "Build the lab" action must appear in the unavailable state when a scenario is selected. Fix BUG-03 (phase/available) first, since BUG-04 is downstream of it per the QA report's suggested correction; then verify BUG-01's unavailable messaging renders.

Rationale: BUG-02 is a pure backend contract fix with no dependency on the frontend state machine. BUG-04 depends on BUG-03 (button renders only when phase is correctly `'unavailable'`). BUG-01 shares the same state machine as BUG-03, so fixing the state machine addresses both.

### Exact verification tests to re-run after fixes

All five are in `backend/tests/test_e2e_browser.py` (Python `playwright.sync_api`, **not** Node):

| # | Test | Line | Bug | Success criterion |
|---|---|---|---|---|
| 1 | `test_an_unavailable_lab_says_so_and_says_why` | :2183 | BUG-01 | Body matches `unavailable\|could not be reached\|not ready` **and** `root\|namespace\|not found\|permission` |
| 2 | `test_the_compare_result_has_the_fields_the_interface_reads` | :2266 | BUG-02 | `assert "reason" in lab` passes on compare response |
| 3 | `test_the_test_and_teardown_actions_are_not_offered_before_the_lab_is_ready` | :2381 | BUG-03 | `.lab-ready` count == 0; no "Send a test packet" / "Tear the lab down" buttons |
| 4 | `test_the_build_action_is_enabled_when_a_scenario_is_selected` | :2402 | BUG-04 | "Build the lab" button count == 1 and not disabled |
| 5 | `test_a_refused_build_is_reported_and_the_lab_stays_unavailable` | :2416 | BUG-04 | Build button present; refusal + reason reported; `.lab-ready` and `.lab-test-result` absent |

**Re-run command** (from `backend/` with venv activated):

```bash
cd /home/abhaysawant/Desktop/cn_project_2/backend
source .venv/bin/activate
python -m pytest tests/test_e2e_browser.py -q -v
```

**Note:** These tests use Python playwright (playwright 1.60.0 installed; browsers present under `~/.cache/ms-playwright`), so they are **not** blocked by the Node 18 limitation. The Node limitation affects only the frontend `test:a11y` script (`playwright test`, Node CLI, `frontend/package.json:6`).

---

## Discrepancy summary

| # | Discrepancy | VERIFIED | ASSUMED |
|---|---|---|---|
| 1 | Python vs Node Playwright | Backend E2E uses Python `playwright.sync_api` (`test_e2e_browser.py:35-40`); playwright 1.60.0 installed; Node limitation only affects frontend `test:a11y` (`package.json:6`) | Exact capture environment of the 93/5/3 run unknown |
| 2 | Five failed tests | All 5 tests, lines, assertions, expected vs actual verified against source + QA report | None needed for this discrepancy |
| 3 | Packet Lab skip vs lifecycle failure | 5 failing tests are UI/contract tests (not real execution); browsers present; skip mechanism exists (`pytest.skip` at :2142, :2492) | "3 skip" count not traced to individual skips; real-execution skip grouping inferred |
| 4 | BUG-01/03/04 root cause | Coupled `available`/`phase` state machine conditions verified (`VirtualLabPanel.tsx:267`, `:302-308`, `:594-647`, `:667-704`); QA report treats BUG-04 as downstream of BUG-03 | Single vs separate root cause not runtime-confirmed; actual `labStatus.available`/`phase` values not observed |
| 5 | Missing `reason` field | Backend `probe()` unreachable paths (366-367, 373-378) lack `reason`; matches BUG-02 payload; `LabProbeResult.reason?` optional (`routing.ts:498-504`); `ComparePanel.tsx:120` reads `reason` directly | Optimal fix location (backend vs frontend guard) not yet decided |

**End of report.**
