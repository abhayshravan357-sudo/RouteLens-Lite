# PHASE 2 STAGE B2 DESIGN AUDIT — Packet Journey Failure-Code Contract

RouteLens Lite — QA/TestPilot agent. Stage B2 design audit (read-only).

- **Project path:** `/home/abhaysawant/Desktop/cn_project_2`
- **Branch:** `integration/baseline-2026-10-20`
- **Status:** Design report only. No implementation. No application files modified by this agent.
- **Verification baseline:** `backend/tests/test_packet_journey.py` — 46 passed (run with `python3 -m pytest`, read-only).

## Conventions

Findings are labeled **(V)** = verified against source code (exact file + line), or **(R)** = recommendation / proposal, not yet implemented. No claim is made that any test passed unless it was actually run.

---

## 1. Current backend response contract

### 1.1 `PacketJourneyResponse` fields and types

Source: `backend/app/routing.py`, class `PacketJourneyResponse`, lines 270-298.

| Field | Type | Default | Verified location |
|---|---|---|---|
| `source_ip` | `str` | required | routing.py:287 |
| `destination_ip` | `str` | required | routing.py:288 |
| `hops` | `list[PacketHopResponse]` | required | routing.py:289 |
| `success` | `bool` | required | routing.py:290 |
| `error` | `Optional[str]` | `None` | routing.py:291 |
| `provenance` | `str` | `"simulated"` | routing.py:292-298 |

There is **no `failure_code` field** in the current contract. (V)

### 1.2 `PacketHopResponse` fields

Source: `backend/app/routing.py`, class `PacketHopResponse`, lines 225-267.

- `hop_number: int`, `current_device: str`, `destination_ip: str` (lines 245-247)
- `action: str` — one of `PACKET_JOURNEY_ACTIONS` (lines 248-254)
- `explanation: str` (line 255)
- `matched_route: Optional[MatchedRoute]` (lines 256-259)
- `next_hop_ip: Optional[str]` (lines 260-263)
- `egress_interface: Optional[str]` (lines 264-267)

Optional hop fields are omitted from the dataclass when not applicable, but Pydantic serializes `Optional` defaults as `null` in JSON (confirmed by test at test_packet_journey.py:657).

### 1.3 Authorized hop actions

`PACKET_JOURNEY_ACTIONS` tuple, `backend/app/routing.py` lines 175-182:

- `forward`, `deliver`, `drop`, `loop`, `unresolved_next_hop`, `error`

### 1.4 How `success`, `error`, `hops`, `provenance` are populated

Source: `trace_packet_journey`, `backend/app/main.py`, lines 388-478.

1. IP validation, lines 420-425: both `source_ip` and `destination_ip` must parse as `IPv4Address`; otherwise `HTTPException(400, "Invalid IP address: ...")`. **Only IPv4 is accepted at the endpoint**, even though `trace_packet_path` supports IPv6. (V)
2. Trace: `hops = trace_packet_path(...)`, lines 428-433.
3. Hop conversion, lines 436-456: each `PacketHop` → `PacketHopResponse`; `matched_route`, `next_hop_ip`, `egress_interface` set only when present.
4. Success determination, lines 458-466:
   - `success = any(h.action == "deliver" for h in hops)` (line 459)
   - `error` = the explanation of the **first** hop whose `action` is in `("drop", "loop", "error", "unresolved_next_hop")` (lines 463-466). Since every terminal path `break`s, this is the terminal hop's explanation.
5. Return, lines 468-478: `provenance="simulated"`.

### 1.5 Endpoint behavior summary

- Valid request → HTTP 200 + `PacketJourneyResponse` (success may be true or false).
- Invalid IP → HTTP 400 (not a `PacketJourneyResponse`).
- Invalid request body → HTTP 422 via `RequestValidationError` handler (main.py:60-89).
- Unexpected exception → HTTP 500 via `Exception` handler (main.py:92-109).

---

## 2. Complete list of actual success and failure paths

All terminal conditions below are in `trace_packet_path`, `backend/app/routing_logic.py`, lines 208-454, unless noted. `MAX_HOPS = 30` at line 192.

### 2.1 Success paths (action `deliver`)

| # | Condition | File:lines | Action | Explanation | Reachable via API |
|---|------|---|---|---|---|
| S1 | `current_ip == dst_ip` (packet arrived) | routing_logic.py:313-322 | `deliver` | `"Packet delivered to destination {name} ({dst})"` | Yes |
| S2 | Directly connected route (`next_hop_type == "direct"` or `next_hop_ip is None`) | routing_logic.py:391-408 | `deliver` | `"Direct connection to destination network {dest} on {iface}"` | Yes |
| S3 | Next hop IS the destination (`str(next_hop_ip) == str(dst_ip)`) | routing_logic.py:426-434 | `deliver` | `"Next hop {ip} is the destination"` | Yes |

### 2.2 Failure paths

| # | Condition | File:lines | Terminal action | Explanation | Reachable via API | Reliably identifiable without parsing explanation? |
|---|------|---|---|---|---|---|
| F1 | Invalid source IP | routing_logic.py:246-260 | `error` | `"Invalid source IP address: {e}"` | **No** — endpoint rejects first (main.py:420-425 → HTTP 400) | Yes (action `error`), but collides with F6 |
| F2 | Invalid destination IP | routing_logic.py:263-277 | `error` | `"Invalid destination IP address: {e}"` | **No** — HTTP 400 first | Yes (action `error`), but collides with F6 |
| F3 | Address family mismatch (IPv4↔IPv6) | routing_logic.py:281-295 | `error` | family-mismatch sentence | **No** — endpoint requires both IPv4 → HTTP 400 | Yes (action `error`), but collides with F6 |
| F4 | Loop (revisited device) | routing_logic.py:325-334 | `loop` | `"Loop detected: packet returned to {name} ({ip})"` | Yes | Yes |
| F5 | No routing table for current router (`current_table is None`) | routing_logic.py:337-349 | `unresolved_next_hop` | `"The packet is at ..., but no routing table for that router was given..."` | Yes | Yes |
| F6 | Routing table unreadable (`result.error` from `lookup_route`) | routing_logic.py:354-367 | `error` | `"{name} could not make a routing decision: {result.error}"` | Yes | Yes (action `error`), but collides with F1-F3 |
| F7 | No matching route (`not result.matched`) | routing_logic.py:369-380 | `drop` | `"No route to destination {dst} from {name} ({ip}), so the packet has nowhere to go and is dropped."` | Yes | **No** — `drop` is shared with F8; distinguished only by explanation text |
| F8 | Max hop count exceeded (`hop_number >= MAX_HOPS`) | routing_logic.py:441-452 | `drop` | `"Maximum hop count exceeded ({MAX_HOPS} hops)"` | Yes | **No** — `drop` shared with F7; distinguished only by explanation text |

Non-terminal: action `forward`, routing_logic.py:411-423 — journey continues.

### 2.3 Key reliability gap (verified)

The backend **cannot** reliably distinguish `no_route` (F7) from `max_hops_exceeded` (F8) without parsing `explanation` text, because both use terminal action `drop`. Similarly `error` action (F1/F2/F3/F6) collapses distinct causes. The endpoint's `error` string (main.py:460-466) is the only carrier of the distinction. (V)

### 2.4 Max-hop off-by-one note (verified context)

Stage B1 changed the guard from `>` to `>=` at routing_logic.py:444. With `MAX_HOPS = 30`, exactly 30 forwarding decisions are permitted, then a terminal drop hop is appended at `hop_number + 1 = 31`. So `len(hops) == 31` (30 forwards + 1 drop), matching `test_packet_journey.py:473` (`len(hops) == MAX_HOPS + 1`). If the 30th forward's next hop is the destination, delivery occurs before the guard (S3 path). (V)

---

## 3. Failure-action-to-code mapping table (recommended stable codes)

All codes in this section are **(R)** proposals, not implemented. Codes apply to `PacketJourneyResponse.failure_code`; `null` means success.

| Failure code | Source condition | File:lines | Terminal action | Backend can identify without parsing explanation? | Notes |
|---|---|---|---|---|---|
| `no_route` | No matching route | routing_logic.py:369-380 | `drop` | **No** (shared `drop`) | Distinguish from `max_hops_exceeded` only via explanation text unless a structural field is added. |
| `loop` | Revisited device | routing_logic.py:325-334 | `loop` | Yes | |
| `unresolved_next_hop` | No table for next router | routing_logic.py:337-349 | `unresolved_next_hop` | Yes | Backend marks success=false + error; frontend currently tones it as info. Semantic mismatch to reconcile. |
| `routing_table_error` | Unreadable table (`result.error`) | routing_logic.py:354-367 | `error` | Yes (action `error`) | Collides with invalid-input `error` actions at action level; distinguishable by context (reachable via API only via corrupt table). |
| `max_hops_exceeded` | Hop limit reached | routing_logic.py:441-452 | `drop` | **No** (shared `drop`) | Distinguish from `no_route` only via explanation text unless a structural field is added. |

### 3.1 Conditions detected by `trace_packet_path` but surfaced as HTTP 400 (not journey responses)

These are **reachable by the function** but **unreachable as a `PacketJourneyResponse` via `/packet-journey`**, because the endpoint validates IPs first and raises HTTP 400 (main.py:420-425):

| Code | Condition | File:lines | Endpoint behavior |
|---|---|---|---|
| `invalid_source_ip` | Invalid source IP | routing_logic.py:246-260 | HTTP 400 before trace |
| `invalid_destination_ip` | Invalid destination IP | routing_logic.py:263-277 | HTTP 400 before trace |
| `address_family_mismatch` | IPv4↔IPv6 mix | routing_logic.py:281-295 | HTTP 400 before trace |

**(R)** Recommendation: keep these as HTTP 400 (request errors), not `failure_code`s, since the endpoint rejects before tracing. Do not propose failure codes for conditions the endpoint never surfaces as a journey response.

---

## 4. API validation and exception-handling findings

Source: `backend/app/main.py`.

### 4.1 Invalid inputs → HTTP 4xx (verified)

- Invalid request body (missing/mistyped fields): `RequestValidationError` handler → HTTP 422 JSON `{"detail": "..."}` (main.py:60-89). **Not** a `PacketJourneyResponse`.
- Invalid IP in `/packet-journey`: explicit `IPv4Address` check → HTTP 400 `{"detail": "Invalid IP address: ..."}` (main.py:420-425). **Not** a `PacketJourneyResponse`.

### 4.2 Does the backend return a failed `PacketJourneyResponse` for invalid input? (verified)

**No.** The endpoint raises `HTTPException` (400/422) before tracing, so the client receives an error response, not a journey response with `success=false`. Direct calls to `trace_packet_path` do return a single `action="error"` hop for invalid IPs (routing_logic.py:246-277), but that path is not exercised by `/packet-journey`.

### 4.3 Unexpected exceptions (verified)

Caught by the generic `Exception` handler → HTTP 500 JSON `{"detail": "Internal server error", "type": "<class name>"}` (main.py:92-109). The full exception is logged. **Not** a `PacketJourneyResponse`.

### 4.4 Cases that should remain HTTP errors rather than packet-journey failure codes (R)

- Invalid request body → 422 (request malformed; not a journey outcome).
- Invalid IP / unsupported family at the endpoint → 400 (request rejected before tracing).
- Unexpected exceptions → 500 (infrastructure failure; not a routing outcome).

These are request- or infrastructure-level failures and should stay as HTTP errors. `failure_code` should describe only routing outcomes produced by a successful trace.

---

## 5. Current frontend outcome logic

### 5.1 `JourneyOutcome` type

Source: `frontend/src/types/routing.ts`, lines 475-482:

```ts
export type JourneyOutcome =
  | 'delivered'
  | 'loop'
  | 'hop_limit_exceeded'
  | 'no_route'
  | 'unresolved_next_hop'
  | 'invalid_input'
  | 'in_progress';
```

`PacketJourneyResponse` is aliased from the generated OpenAPI schema (line 358: `components['schemas']['PacketJourneyResponse']`); there is **no `failure_code`** in the frontend type. (V)

### 5.2 How the frontend determines the outcome

`classifyOutcome`, `frontend/src/components/PacketJourney.tsx`, lines 141-169:

1. `hops.length === 0` → `'in_progress'` (line 142)
2. last `action === 'deliver'` → `'delivered'` (line 147)
3. last `action === 'loop'` → `'loop'` (line 148)
4. last `action === 'unresolved_next_hop'` → `'unresolved_next_hop'` (line 149)
5. last `action === 'error'` → `'invalid_input'` (line 150)
6. any hop `action === 'loop'` → `'loop'` (line 151)
7. any hop `action === 'unresolved_next_hop'` → `'unresolved_next_hop'` (lines 152-154)
8. last `action === 'drop'`:
   - explanation includes `'hop count'` / `'maximum hop'` / `'hop limit'` / `'ttl'` → `'hop_limit_exceeded'` (lines 157-161)
   - else → `'no_route'` (line 165)
9. else → `'in_progress'` (line 168)

### 5.3 Explanation-string checks in use (verified)

Lines 157-161 of `PacketJourney.tsx`:

```ts
explanation.includes('hop count') ||
explanation.includes('maximum hop') ||
explanation.includes('hop limit') ||
explanation.includes('ttl')
```

The backend's actual max-hop explanation is `"Maximum hop count exceeded (30 hops)"` (routing_logic.py:450), which matches `'hop count'` / `'maximum hop'`. The `'ttl'` check is **unsupported by the current backend** — `trace_packet_path` never emits `'ttl'` in any drop explanation — so it is a dead check. (V)

### 5.4 Observed mismatches and fragility (V + R)

- `no_route` vs `hop_limit_exceeded` are distinguished **only by parsing `explanation`**, which is fragile and depends on exact wording (routing_logic.py:376 vs 450). (V)
- `error` action maps to `'invalid_input'`, but the endpoint never returns a journey response for invalid input (it's HTTP 400), so this branch is effectively unreachable via the API. (V)
- `unresolved_next_hop`: backend sets `success=false` + `error` (main.py:461-466), but the frontend tones it as `'info'` and does not treat it as a failure. Semantic mismatch. (V)
- The frontend reads `simulationResponse.error` for display (lines 356-360) but has no machine-readable failure code. (V)

### 5.5 Minimum frontend changes required (R)

- Add `failure_code: string | null` to the journey response type (regenerate from OpenAPI or add manually, then run `npm run generate:api`).
- Derive outcome from `success` + `failure_code` instead of parsing `explanation`.
- Remove/reduce explanation-string checks (drop the unsupported `'ttl'` check).
- Keep `error` as human-readable text shown alongside.

---

## 6. Proposed response contract with JSON examples

**(R)** Design: add `failure_code: string | null` to `PacketJourneyResponse`. Preserve `success`, `error`, `hops`, `provenance`. `failure_code: null` on success; stable code on each supported failure. `error` remains human-readable text.

### 6.1 Type sketch

```ts
failure_code: string | null;   // null on success; one of the stable codes below
```

### 6.2 JSON examples

Success (direct delivery):
```json
{
  "source_ip": "192.168.1.10",
  "destination_ip": "10.5.5.5",
  "hops": [{"hop_number":1,"current_device":"Device(192.168.1.10)","destination_ip":"10.5.5.5","action":"deliver","explanation":"Direct connection to destination network 10.0.0.0/8 on eth2","matched_route":{...},"next_hop_ip":null,"egress_interface":"eth2"}],
  "success": true,
  "error": null,
  "failure_code": null,
  "provenance": "simulated"
}
```

Failure — no route:
```json
{
  "source_ip": "192.168.1.10",
  "destination_ip": "192.168.2.50",
  "hops": [{"hop_number":1,"current_device":"Device(192.168.1.10)","destination_ip":"192.168.2.50","action":"drop","explanation":"No route to destination 192.168.2.50 from Device(192.168.1.10) (192.168.1.10), so the packet has nowhere to go and is dropped."}],
  "success": false,
  "error": "No route to destination ...",
  "failure_code": "no_route",
  "provenance": "simulated"
}
```

Failure — max hops exceeded:
```json
{
  ...,
  "hops": [{...,"action":"drop","explanation":"Maximum hop count exceeded (30 hops)",...}],
  "success": false,
  "error": "Maximum hop count exceeded (30 hops)",
  "failure_code": "max_hops_exceeded",
  "provenance": "simulated"
}
```

Failure — loop:
```json
{
  ...,
  "hops": [{...,"action":"forward",...},{...,"action":"loop","explanation":"Loop detected: ...",...}],
  "success": false,
  "error": "Loop detected: ...",
  "failure_code": "loop",
  "provenance": "simulated"
}
```

Invalid input (not a journey response — HTTP 400):
```http
HTTP/1.1 400 Bad Request
{"detail": "Invalid IP address: ..."}
```

---

## 7. Backward-compatibility considerations

**(R)**

- Adding `failure_code: Optional[str] = None` is additive; existing clients that ignore it continue to work. Old responses lacking the field deserialize to `None` (Pydantic default), so deserialization is safe.
- OpenAPI schema gains one property; existing schema-based clients are unaffected.
- The existing response-schema test uses a superset assertion (`set(properties) >= {...}`, test_packet_journey.py:735-742), so adding `failure_code` does not break it.
- Hop field-set assertions (test_packet_journey.py:769-778) concern hops, not the response, and are unaffected.
- `success` semantics unchanged; `error` remains human-readable. During transition the frontend can use both `failure_code` (machine) and `error` (human).
- Frontend type is currently schema-aliased; manual addition of `failure_code` would drift unless `npm run generate:api` is run after the backend change.

---

## 8. Recommended tests for a future implementation

**(R)** Build on the existing suite `backend/tests/test_packet_journey.py` (46 passed, verified by running it).

Backend:
- Unit tests on `trace_packet_path` asserting terminal `action` + expected `failure_code` for each condition: S1/S2/S3 (deliver), F4 (loop), F5 (unresolved_next_hop), F6 (routing_table_error via corrupt table), F7 (no_route), F8 (max_hops_exceeded).
- Endpoint tests asserting `failure_code` appears in HTTP 200 responses for each failure, and that `success=true ⟺ failure_code=null`.
- Endpoint tests asserting invalid IP → HTTP 400 (not a journey response) — partially covered by `test_a_cross_family_destination` (test_packet_journey.py:677-685).
- Test that `drop` is disambiguated: `no_route` vs `max_hops_exceeded` (requires a structural field or explanation check).
- OpenAPI test asserting `failure_code` present in `PacketJourneyResponse` properties.

Frontend:
- Unit tests for `classifyOutcome` driven by `success` + `failure_code`, not explanation strings.
- Snapshot/rendering tests for each `failure_code` outcome tone and label.

---

## 9. Files that would need modification in a later implementation

**(R)** This audit is read-only; none of these were modified.

| File | Change |
|---|---|
| `backend/app/routing.py` | Add `failure_code: Optional[str] = None` to `PacketJourneyResponse` (line ~291 area); optionally a failure-code enum/constant set. |
| `backend/app/main.py` | `trace_packet_journey` sets `failure_code` from terminal hop action (lines 458-466). |
| `backend/app/routing_logic.py` | Optionally expose the failure reason structurally on `PacketHop`/return so the endpoint can map action→code without parsing explanation (needed to disambiguate F7 vs F8). |
| `frontend/src/types/routing.ts` | Add `failure_code: string | null` to the journey response type (line ~358); regenerate via `npm run generate:api`. |
| `frontend/src/components/PacketJourney.tsx` | `classifyOutcome` (lines 141-169) to use `success` + `failure_code`; remove explanation-string checks (lines 157-161). |
| Tests | `backend/tests/test_packet_journey.py`; frontend outcome tests. |

---

## 10. Open questions and risks

**(R)** Unresolved items for the implementation team:

1. **`invalid_*` / `address_family_mismatch`**: detected by `trace_packet_path` but surfaced as HTTP 400 by the endpoint (main.py:420-425). Recommend keeping them as HTTP 400, not `failure_code`s. Confirm this is the intended split between request errors and journey outcomes.
2. **`drop` ambiguity**: `no_route` (F7) and `max_hops_exceeded` (F8) both use action `drop`. A `failure_code` for each requires either parsing `explanation` (fragile) or adding a structural failure reason to `PacketHop`/the trace return.
3. **`error` action collision**: used for invalid input (F1-F3, unreachable via API) and routing-table-error (F6, reachable). A single `failure_code` from action `error` would conflate them unless disambiguated by context/explanation.
4. **`unresolved_next_hop` semantics**: backend reports `success=false` + `error`; frontend tones it as `info` and does not treat it as failure. Decide whether it is a failure code or a non-error outcome.
5. **Frontend type drift**: `PacketJourneyResponse` is schema-aliased (routing.ts:358). Manual `failure_code` addition drifts unless `npm run generate:api` is run.
6. **Working-tree state**: the tree already contained pre-existing modifications (Phase 1 + Stage B1: `backend/app/lab_adapter.py`, `lab_builder.py`, `packet_lab.py`, `routing_logic.py`, `routing_table.py`, and several test files + `frontend/src/components/VirtualLabPanel.tsx`). This audit is read-only and touched none of them. See final git status below.
7. `MAX_HOPS` off-by-one was fixed in Stage B1 (`>=` at routing_logic.py:444); 30 forwards + terminal drop = 31 hops. Any new max-hop test must assert `len(hops) == MAX_HOPS + 1`.

---

## Verification

- Every finding above is tied to exact source locations (verified by reading `backend/app/routing.py`, `backend/app/main.py`, `backend/app/routing_logic.py`, `frontend/src/types/routing.ts`, `frontend/src/components/PacketJourney.tsx`).
- Ran `backend/tests/test_packet_journey.py`: **46 passed** (read-only). No other test suite was run; no claim is made about it.
- This task is read-only. **No application code, tests, configuration, or frontend files were modified by this agent.** No commit, merge, push, reset, clean, or stash was performed.

Final git status (working tree contains pre-existing Phase 1 + Stage B1 modifications unrelated to this audit):

```
M backend/app/lab_adapter.py
M backend/app/lab_builder.py
M backend/app/packet_lab.py
M backend/app/routing_logic.py
M backend/app/routing_table.py
M backend/tests/test_packet_journey.py
M backend/tests/test_packet_lab.py
M backend/tests/test_routing.py
M backend/tests/test_routing_api.py
M backend/tests/test_routing_logic.py
M backend/tests/test_routing_logic_unittest.py
M frontend/src/components/VirtualLabPanel.tsx
?? backend/.coverage
?? backend/tests/test_phase1_mocked_unavailable.py
?? docs/qa/
```

Report path: `docs/qa/PHASE_2_STAGE_B2_DESIGN_AUDIT.md`

This audit ends here. Stage B2 is not implemented; all other agents remain idle.
