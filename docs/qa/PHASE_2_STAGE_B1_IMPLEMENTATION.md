# PHASE 2 STAGE B1 IMPLEMENTATION REPORT

RouteLens Lite — Routing/Backend Agent
Stage B1: Routing defect fixes (ROUTE-01, ROUTE-02, ROUTE-03)

## A. Baseline

- **Project path:** `/home/abhaysawant/Desktop/cn_project_2`
- **Branch:** `integration/baseline-2026-10-20`
- **Initial Git status:** Working tree contained pre-existing modified files (Phase 1), with no commits, merges, or pushes on the branch:
  - `backend/app/lab_adapter.py`
  - `backend/app/lab_builder.py`
  - `backend/app/packet_lab.py`
  - `backend/tests/test_packet_lab.py`
  - `frontend/src/components/VirtualLabPanel.tsx`
  These Phase 1 modifications were preserved and are untouched by Stage B1.
- **Working tree state before Stage B1:** modified files listed above only; no staged or committed changes.

## B. Changes (per finding)

### ROUTE-01 — Max-hop off-by-one

- **Root cause:** In `trace_packet_path` (`backend/app/routing_logic.py`), the max-hop guard used `if hop_number > MAX_HOPS`. The forwarding decision is recorded at the current `hop_number` before the guard runs, so `>` permitted the loop to continue one hop past the documented limit: after the 30th forward the guard did not fire until `hop_number` reached 31, effectively allowing a 31st forwarding decision path.
- **File/function changed:** `backend/app/routing_logic.py` — `trace_packet_path` (line ~444).
- **What was changed:** `if hop_number > MAX_HOPS:` → `if hop_number >= MAX_HOPS:`, with an added comment explaining that the hop just made counts as a forwarding decision and the loop stops once `hop_number` reaches `MAX_HOPS` rather than making another one.
- **Why it fixes the defect:** With `MAX_HOPS = 30`, the guard now fires immediately after the 30th forwarding decision is recorded, so exactly 30 forwarding decisions are permitted and no 31st forwarding decision can be made. The packet is then dropped (or delivered if the 30th next hop is the destination) instead of forwarding again.

### ROUTE-02 — Invalid-IP error message wording

- **Root cause:** In `lookup_route` (`backend/app/routing_logic.py`), an invalid destination IP produced `error=f"Invalid IPv4 address: {destination_ip}"`, which is misleading because `lookup_route` accepts both IPv4 and IPv6; an IPv6-invalid string was reported as an "IPv4" problem.
- **File/function changed:** `backend/app/routing_logic.py` — `lookup_route` (line ~131).
- **What was changed:** `error=f"Invalid IPv4 address: {destination_ip}"` → `error=f"Invalid IP address: {destination_ip}"`.
- **Why it fixes the defect:** The message now accurately reflects that the address family is generic (IPv4 or IPv6), matching the validation logic and the expectations of callers and tests.

### ROUTE-03 — Validation order in route update

- **Root cause:** In `RoutingTable.update_route` (`backend/app/routing_table.py`), the route was validated before the index range was checked. When an out-of-range index was supplied together with an invalid route, an `InvalidRouteError` was raised instead of `IndexOutOfRangeError`, so callers could not distinguish "bad index" from "bad route".
- **File/function changed:** `backend/app/routing_table.py` — `RoutingTable.update_route`.
- **What was changed:** Moved the index range check (`if index < 0 or index >= len(self._routes)`) ahead of `self._validate_route(route)`, both inside `self._lock`; the redundant post-validation index check was removed.
- **Why it fixes the defect:** An out-of-range index is now reported as `IndexOutOfRangeError` regardless of route validity, matching the documented contract (`IndexOutOfRangeError: If the index is out of range`) and `delete_route`'s behavior.

## C. Max-hop proof

With `MAX_HOPS = 30` and the `>=` guard:

1. **Exactly 30 permitted forwarding decisions.** Each loop iteration that forwards records one `PacketHop` with `action="forward"` at the current 1-based `hop_number`. The guard fires once `hop_number` reaches 30, so forwards are recorded at hop numbers 1 through 30 — exactly 30 forwarding decisions.
2. **No 31st forwarding decision.** After the 30th forward is recorded, the guard `hop_number >= MAX_HOPS` (30 >= 30) is true, so the loop appends a final drop hop (`hop_number + 1 = 31`) and breaks. No further forward is recorded; there is no 31st forwarding decision.
3. **Correct final drop behavior.** The final hop has `action="drop"`, `current_device="..."`, and explanation `"Maximum hop count exceeded (30 hops)"`. The packet is not delivered.
4. **Delivery after 30th forwarding decision context.** If the 30th forward's next hop is the destination itself, delivery (`action="deliver"` at `hop_number + 1 = 31`) occurs before the max-hop guard is reached. In that case there are still exactly 30 forwarding decisions, with delivery immediately after the 30th, and no 31st forwarding decision.

Either way the trace ends with `len(hops) == MAX_HOPS + 1 == 31` hops (30 forwards + 1 terminal drop/deliver), consistent with `test_packet_journey.py` asserting `len(hops) == MAX_HOPS + 1` (changed from `MAX_HOPS + 2`).

## D. Test results

Results as reported by the implementation agent (not independently re-run by this agent):

- **Full backend suite (excluding browser E2E):** 1,486 passed, 6 skipped.
- **Targeted suites:** green (routing, routing logic, routing API, routing logic unittest, packet journey).

Tests passed and failed:
- Passed: full backend suite excluding browser E2E — 1,486 passed, 6 skipped; no failures reported.
- Failed: none reported.

Test files updated for Stage B1:
- `backend/tests/test_packet_journey.py` — `MAX_HOPS + 2` → `MAX_HOPS + 1`
- `backend/tests/test_routing.py` — `"Invalid IPv4 address"` → `"Invalid IP address"`
- `backend/tests/test_routing_api.py` — same message change (two assertions)
- `backend/tests/test_routing_logic.py` — same message change
- `backend/tests/test_routing_logic_unittest.py` — same message change

**Confirmation that Phase 1 work preserved:** Phase 1 files (`backend/app/lab_adapter.py`, `backend/app/lab_builder.py`, `backend/app/packet_lab.py`, `backend/tests/test_packet_lab.py`, `frontend/src/components/VirtualLabPanel.tsx`) remain modified in the working tree exactly as before; none were touched by Stage B1.

## E. Scope verification

- **ROUTE-04, ROUTE-05, ROUTE-06, ROUTE-07/08:** NOT implemented. Out of scope for Stage B1.
- **Frontend / Packet Lab:** No frontend code and no Packet Lab code was modified (the listed Phase 1 files were left untouched).
- **Networking state:** No networking state changed.
- **Existing user modifications:** No existing user modifications discarded; all pre-existing Phase 1 modifications remain in the working tree.

## F. Final Git status

Branch: `integration/baseline-2026-10-20`

Changed files (Stage B1 + pre-existing Phase 1):
- `backend/app/routing_logic.py` (modified) — ROUTE-01, ROUTE-02
- `backend/app/routing_table.py` (modified) — ROUTE-03
- `backend/tests/test_packet_journey.py` (modified)
- `backend/tests/test_routing.py` (modified)
- `backend/tests/test_routing_api.py` (modified)
- `backend/tests/test_routing_logic.py` (modified)
- `backend/tests/test_routing_logic_unittest.py` (modified)
- `backend/app/lab_adapter.py` (modified, pre-existing Phase 1)
- `backend/app/lab_builder.py` (modified, pre-existing Phase 1)
- `backend/app/packet_lab.py` (modified, pre-existing Phase 1)
- `backend/tests/test_packet_lab.py` (modified, pre-existing Phase 1)
- `frontend/src/components/VirtualLabPanel.tsx` (modified, pre-existing Phase 1)

New files:
- `docs/qa/PHASE_2_STAGE_B1_IMPLEMENTATION.md` (this report)

Diff summary: three source fixes (invalid-IP message wording, max-hop comparison `>` → `>=`, update validation order) and five test assertion updates matching the fixes.

Confirmation: no commit, merge, or push was performed. The working tree remains uncommitted.
