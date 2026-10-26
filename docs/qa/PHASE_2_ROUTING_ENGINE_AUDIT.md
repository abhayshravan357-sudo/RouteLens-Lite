# PHASE_2_ROUTING_ENGINE_AUDIT.md

RouteLens Lite — Comprehensive Routing Engine Audit
READ-ONLY audit. No source code, tests, configuration, network state, or commits were modified.

Audit date: 2026-10-25
Project: `/home/abhaysawant/Desktop/cn_project_2`
Branch: `integration/baseline-2026-10-20`
Baseline git status: 5 modified files (none in the routing engine core), 3 untracked entries (`.coverage`, `test_phase1_mocked_unavailable.py`, `docs/qa/`). The routing-engine modules (`routing.py`, `routing_logic.py`, `routing_table.py`, `routing_table_persistence.py`) are UNMODIFIED from HEAD.

---

## Section A — Audit summary

### Overall routing-engine condition

The routing engine's core longest-prefix-match (LPM) lookup is **correct and well-tested**. The packet-journey trace is **largely correct** for multi-hop forwarding when per-router tables are supplied, and it correctly distinguishes "found a route" from "packet delivered". The engine is a pure calculation layer: no packet is transmitted, and every forwarding decision is inferred from a routing table.

The engine is **not production-complete** as a general forwarding engine: it does not validate next-hop reachability, interface availability, or interface/network relationship, and it has no stale-simulation version tracking. These are design gaps rather than crashes, but they mean the engine cannot detect several real-world failure modes (unreachable gateway, wrong interface, dead link).

### Strongest verified capabilities

- Longest-prefix match with metric tiebreaker and deterministic complete-tie rule (`routing_logic.py:56-103`), verified by 12+ tests.
- Default route (`0.0.0.0/0`, `::/0`) matches any IP of the right family (`test_routing.py:335-349`).
- Directly connected delivery (no next hop) detected and reported as `deliver` (`routing_logic.py:391-408`, `test_packet_journey.py:77-88`).
- Multi-hop forwarding where each router uses **its own** table (`routing_logic.py:438-439`, `test_packet_journey.py:106-137, 179-246`).
- Routing-loop detection via a per-trace `visited` set (`routing_logic.py:325-334`, `test_packet_journey.py:313-364`).
- Delivery-vs-found-route distinction: `success` is true only when a `deliver` action occurs (`main.py:459`, `test_packet_journey.py:495-535`).
- No false "loop" when the next router's table is unknown; reported as `unresolved_next_hop` instead (`routing_logic.py:337-349`, `test_packet_journey.py:148-163`).

### Most serious concerns

1. **Max-hop off-by-one** (`routing_logic.py:441-450`): the `hop_number > MAX_HOPS` check runs *after* the packet has already moved to the next router, so up to 31 forwards occur before the drop at MAX_HOPS=30 instead of 30. Confirmed by `test_packet_journey.py:451-473`, which codifies `len(hops) == MAX_HOPS + 2` (31 forwards + 1 drop).
2. **Misleading error message** (`routing_logic.py:129,131`): when neither IPv4 nor IPv6 parsing succeeds, the error reads `"Invalid IPv4 address: <input>"` even for input that is not an IP at all (e.g. `"not-an-ip"`). `test_routing_logic.py:40-43` and `test_routing.py:286-300` assert this string, so they pass but do not catch the defect.
3. **No next-hop reachability / interface validation**: the engine forwards to whatever next hop the route says, without checking that the next hop is on the interface's network or that the interface exists/is up. Unreachable gateways are indistinguishable from "no route" until the trace reaches an unknown router.
4. **No stale-simulation / version tracking**: the persistence layer loads routes from disk on startup with no generation counter or cache-invalidation mechanism. Repeated simulations against a mutated table have no staleness detection (`routing_table_persistence.py`, `routing_table.py`).

### Areas that could not be verified

- Real-network evidence: no packet is ever transmitted; all conclusions are inferred from tables, so no live forwarding behaviour can be confirmed from this code alone.
- Interface availability / link state: the engine has no concept of interface `up/down`, so interface selection correctness relative to actual link state cannot be verified.
- Stale simulation invalidation under concurrent or repeated mutation: no tests exist and no version-tracking code is present.
- IPv6 end-to-end journey through multiple routers: unit tests cover IPv6 lookup and a two-hop IPv6 journey, but no multi-router IPv6 loop or max-hop scenario.

---

## Section B — Architecture map

Execution path for a packet-journey trace (`POST /packet-journey`). Each step lists file, function/class, line numbers, input, output, dependencies, and validation/error handling.

```
API request → validation → routing lookup → route selection → next hop → next router → delivery/failure → API response
```

| Step | File | Function / class | Lines | Input | Output | Dependencies | Validation / error handling |
|------|------|------------------|-------|-------|--------|--------------|------------------------------|
| 1. API request | `backend/app/main.py` | `trace_packet_journey` | 388-478 | `PacketJourneyRequest{source_ip, destination_ip}` | `PacketJourneyResponse` | FastAPI, Pydantic | Request body parsed by Pydantic; missing/invalid body → 422 via `validation_exception_handler` (main.py:60-89) |
| 2. IP validation | `backend/app/main.py` | `trace_packet_journey` | 420-425 | `request.source_ip`, `request.destination_ip` | `IPv4Address`/`IPv6Address` objects | `ipaddress` module | Invalid IP → `HTTPException 400 "Invalid IP address: ..."`. Address-family mismatch is NOT checked here (deferred to engine) |
| 3. Routing table retrieval | `backend/app/main.py` | `trace_packet_journey` | 428-433 | — | list of `RoutingEntry` | `app.routing_table.get_routing_table()` (singleton) | Table loads from persistence on first access; corruption falls back to sample table (`routing_table_persistence.py:162-231`) |
| 4. Routing lookup (entry) | `backend/app/routing_logic.py` | `lookup_route` | 106-171 | `destination_ip` string, `routes` list | `RouteLookupResult{matched, route, explanation, error, transmitted}` | `find_matching_routes`, `select_best_route`, `ipaddress` | Invalid IP → `matched=False, error="Invalid IPv4 address: ..."` (misleading for IPv6/garbage). Invalid route data in table → `matched=False, error="Invalid route data: ..."` |
| 5. Source/destination validation | `backend/app/routing_logic.py` | `trace_packet_path` | 245-295 | `source_ip`, `destination_ip` strings | `IPv4Address`/`IPv6Address`, version labels | `ipaddress` module | Invalid source → single `PacketHop` action `error`. Invalid destination → single `PacketHop` action `error`. Family mismatch → single `PacketHop` action `error` (no address translation) |
| 6. Route matching (LPM candidate set) | `backend/app/routing_logic.py` | `find_matching_routes` | 17-53 | `destination_ip`, `routes` | list of matching `RoutingEntry` | `route.get_ip_version()`, `route.get_network()`, `ip in network` | Skips routes of different IP version. Raises `ValueError "Invalid IPv4 address"` for unparsable destination (message hard-coded to IPv4 even for IPv6 input) |
| 7. Route selection | `backend/app/routing_logic.py` | `select_best_route` | 56-103 | matching routes list | `(best_route, explanation_string)` | `route.get_network().prefixlen`, `route.metric`, `route.interface`, `route.next_hop` | Empty list → `ValueError "No matching routes to select from"`. Tiebreak: longest prefix → lowest metric → interface name asc → next_hop asc (None sorts first) |
| 8. Next-hop determination | `backend/app/routing_logic.py` | `trace_packet_path` | 385-423 | selected `route` | `next_hop_ip`, `egress_interface`, `action="forward"` hop | `route.get_next_hop()`, `route.next_hop_type` | Direct route (`next_hop_type=="direct"` or `next_hop is None`) → `action="deliver"` at current hop (assumes delivery because LPM already confirmed destination in network). Gateway route → `action="forward"` hop recorded |
| 9. Next router handoff | `backend/app/routing_logic.py` | `trace_packet_path` | 426-439 | `next_hop_ip`, `dst_ip`, `router_tables` | `current_ip = next_hop_ip`, `current_table = router_tables.get(current_ip)` | `router_tables` dict keyed by router address | If `next_hop_ip == dst_ip` → extra `deliver` hop at `hop_number+1`. If `current_table is None` at next iteration → `unresolved_next_hop` (honest stop, not a loop) |
| 10. Loop detection | `backend/app/routing_logic.py` | `trace_packet_path` | 301, 325-334 | `current_ip`, `visited` set | `action="loop"` hop on revisit | `visited: set[str]` | Delivery checked *before* loop check (line 314 before 325), so source==destination delivers. Revisit of a router IP → `loop`. Does not track (ip, table) pairs — one table per IP assumed |
| 11. Max-hop enforcement | `backend/app/routing_logic.py` | `trace_packet_path` | 192, 441-450 | `hop_number`, `MAX_HOPS=30` | `action="drop"` hop when exceeded | — | **DEFECT**: check runs after moving to next router; allows 31 forwards before drop. Should be checked at loop top before processing |
| 12. Delivery detection | `backend/app/routing_logic.py` | `trace_packet_path` | 313-322 | `current_ip == dst_ip` | `action="deliver"` hop, break | `device_map` for device name | Delivered only when current router address equals destination; a matched route alone is not a delivery |
| 13. Failure classification | `backend/app/routing_logic.py` | `trace_packet_path` | 337-380, 441-450 | terminal `action` | `drop`/`loop`/`error`/`unresolved_next_hop` hop | — | Each terminal hop carries an `explanation` string; no structured failure code |
| 14. Response serialization | `backend/app/main.py` | `trace_packet_journey` | 436-478 | list of `PacketHop` (routing_logic local dataclass) | `PacketJourneyResponse{source_ip, destination_ip, hops, success, error, provenance}` | `PacketHopResponse`, `MatchedRoute` Pydantic models | `success = any(h.action=="deliver")`. `error` = first terminal-hop explanation among drop/loop/error/unresolved_next_hop. `provenance="simulated"` |
| 15. API response | `backend/app/main.py` | `trace_packet_journey` (FastAPI) | 388-478 | `PacketJourneyResponse` | JSON (200) | `response_model=PacketJourneyResponse` | Unhandled exceptions → 500 `{"detail":"Internal server error","type":...}` via `unhandled_exception_handler` (main.py:92-109) |

The same `lookup_route`/`select_best_route` machinery also serves `GET /lookup` (main.py:184-214), which returns a `RouteLookupResult` directly (single-hop lookup, no trace).

---

## Section C — Functional correctness matrix

Statuses used: Verified working / Partially working / Defect confirmed / Not implemented / Not tested / Unable to determine

| Area | Status | Evidence | Concern |
|------|--------|----------|---------|
| IP validation | Partially working | `routing_logic.py:245-295` validates IPv4/IPv6 source & destination; family mismatch rejected. `test_packet_journey.py:401-445`. | Error message for unparsable input reads `"Invalid IPv4 address"` even for IPv6/garbage (`routing_logic.py:129,131`). Tests assert this misleading string (`test_routing_logic.py:43`), so they pass but don't catch the defect. |
| Longest-prefix match | Verified working | `routing_logic.py:76-77` picks max prefixlen; `select_best_route` tested in `test_routing.py:107-174, 225-245, 376-399, 456-478` and sample-route tests `test_routing.py:510-537`. | None significant. Ordering independent of input order (max/min + stable tiebreak). |
| Default route | Verified working | `0.0.0.0/0` and `::/0` in `SAMPLE_ROUTES` (`routing.py:335-342, 376-383`); tested `test_routing.py:335-349, 532-537`. | Default route with no next hop would be treated as direct delivery (edge case, not in sample table). |
| Next-hop resolution | Partially working | Direct/gateway handled (`routing_logic.py:391-423`); `next_hop == destination` → deliver (`426-434`). | No reachability check: next hop not verified to be on the egress interface's network or reachable. Invalid next hop on a gateway route is caught at table validation (`routing_table.py:107-110`) but not at trace time for raw routes. |
| Interface selection | Partially working | Interface recorded on every hop (`routing_logic.py:398, 417, 420`); tiebreaker uses interface name (`routing_logic.py:95`). Tested `test_routing.py:152-174`. | No interface existence/availability check; no link-state (up/down) concept; overlapping interfaces not validated. |
| Multi-hop forwarding | Verified working | Each hop uses `router_tables.get(current_ip)` (`routing_logic.py:438-439`); tested 2-router (`test_packet_journey.py:106-137`) and 3-router (`179-246`). Destination IP preserved across hops; hop numbers sequential. | Without `router_tables`, trace stops at `unresolved_next_hop` — by design, but the single-table teaching model cannot complete multi-router journeys. |
| Loop detection | Verified working | `visited` set (`routing_logic.py:301, 325-334`); tested 2-router loop (`test_packet_journey.py:313-333`) and self-loop (`350-364`). False-loop bug fixed (single table → `unresolved_next_hop`, not `loop`, `148-163`). | Tracks IP only, not (ip, table); route-change loops where a router revisits with a different table are not distinguishable (one table per IP assumed). |
| Maximum hops | Defect confirmed | `MAX_HOPS=30` (`routing_logic.py:192`); check at `routing_logic.py:441-450` runs *after* moving to next router, allowing 31 forwards before drop. Test codifies this: `test_packet_journey.py:451-473` expects `len(hops) == MAX_HOPS + 2`. | Off-by-one: documented limit is 30 forwards but 31 occur. Minor because loop detection catches most infinite loops first. |
| Delivery semantics | Verified working | `success = any(h.action=="deliver")` (`main.py:459`); deliver only when `current_ip == dst_ip` (`routing_logic.py:314`) or direct route (`391`) or next-hop==destination (`426`). Tested `test_packet_journey.py:495-535`. | A matched route alone is never reported as delivery — correct by design. |
| Failure reporting | Partially working | Terminal actions: drop/loop/error/unresolved_next_hop, each with `explanation`. Frontend `classifyOutcome` parses explanation strings for "hop count"/"maximum hop" (`frontend/src/components/PacketJourney.tsx:157-161`). | Failure is a free-text `error` string, not a structured code; frontend relies on substring matching of explanations (fragile to wording changes). No `failure_reason` field on the response. |
| Route mutation | Verified working | CRUD: `add_route`/`update_route`/`delete_route`/`replace_routes`/`reset_routes` (`routing_table.py:117-209`); persistence atomic write + backup + recovery (`routing_table_persistence.py`). Tests in `test_routing_table.py`, `test_routing_table_persistence.py`. | `update_route` validates route before checking index range (`routing_table.py:156-162`), so invalid route + bad index returns 400 instead of 404. |
| Stale simulation handling | Not implemented | No generation counter, version, or cache-invalidation on the routing table or trace. Persistence loads from disk on startup (`routing_table.py:48-54`). | Repeated/concurrent simulations against a mutated table have no staleness detection; a stale in-memory table is not flagged. |

---

## Section D — API contract assessment

### GET /lookup

Expected: request `?destination=<ipv4>`; response `RouteLookupResult{matched, route, explanation, error, transmitted}`.

| Aspect | Actual | Expected / contract | Assessment |
|--------|--------|---------------------|------------|
| Request field | `destination` query param, required | `destination` string | Match |
| Response fields | `matched`, `route`, `explanation`, `error`, `transmitted` | Same 5 fields | Match |
| Route object fields | `destination`, `next_hop`, `interface`, `metric`, `next_hop_type`, `provenance` | Same | Match |
| No-match | HTTP 404 `{"detail": "No route matches ..."}` | 404 with explanation body | Partial: body is `detail` string, not `RouteLookupResult{matched:false}`; client cannot read `matched` from a 404 body |
| Invalid IP | HTTP 400 `{"detail": "Invalid IPv4 address: ..."}` | 400 | Match on status; message hard-coded to IPv4 (see ROUTE-02) |
| Missing param | HTTP 422 (FastAPI validation) | 422 | Match |
| Error envelope | `{"detail": "..."}` for 400/404/422; full model for 200 | Consistent envelope | Partial: success and error use different shapes (full model vs `detail` string) |

### POST /packet-journey

Expected: request `PacketJourneyRequest{source_ip, destination_ip}`; response `PacketJourneyResponse{source_ip, destination_ip, hops, success, error, provenance}`.

| Aspect | Actual | Expected / contract | Assessment |
|--------|--------|---------------------|------------|
| Request fields | `source_ip`, `destination_ip` (both required) | Same | Match |
| Response fields | `source_ip`, `destination_ip`, `hops`, `success`, `error`, `provenance` | Same | Match |
| Hop fields | `hop_number`, `current_device`, `destination_ip`, `action`, `explanation`, `matched_route?`, `next_hop_ip?`, `egress_interface?` | Same (OpenAPI-generated frontend types alias the schema) | Match |
| MatchedRoute fields | `destination`, `next_hop`, `interface`, `metric` | Same | Match |
| Optional hop fields omitted when absent | `matched_route`, `next_hop_ip`, `egress_interface` absent (not null) on e.g. `unresolved_next_hop` | "left out of the response entirely, rather than sent as null" (`routing.py:229-232`) | Match — but Pydantic `Optional` defaults to null unless `exclude_none`; the frontend test asserts `.get(...) is None` (`test_packet_journey.py:657-659`), so serialization must be emitting null or the field is absent. Needs confirmation of actual JSON null vs omission. |
| `success` | `true` only when a `deliver` hop exists | Delivered only when reached | Match |
| `error` | first terminal-hop explanation | Why journey did not reach | Match |
| `provenance` | `"simulated"` | Calculated, not transmitted | Match |
| Invalid IP | HTTP 400 `{"detail": "Invalid IP address: ..."}` | 400 | Match |

### General contract issues

- **No `failure_reason` field**: the response uses `error` (a string) rather than a structured failure code. The frontend `JourneyOutcome` type (`frontend/src/types/routing.ts:475-482`) enumerates outcomes but the backend does not emit a matching enum; the frontend infers outcome from action + explanation substring matching (`PacketJourney.tsx:141-169`).
- **Error-format inconsistency**: validation failures use the custom `validation_exception_handler` producing `{"detail": "Field: message"}`; `HTTPException` from the endpoints produces `{"detail": "..."}`. Both are `detail` strings but the wording conventions differ slightly.
- **`transmitted` field**: always `False` (`routing.py:156`), documented as such; frontend `RouteLookupResult` includes it but the UI's use is unclear. Not a defect, just informational.

---

## Section E — Test coverage assessment

### Test inventory (routing area)

| File | Tests | Category focus |
|------|-------|----------------|
| `backend/tests/test_routing.py` | ~15 | LPM, metric tiebreaker, default route, direct route, deterministic tie, edge cases (network/broadcast address match), sample routes, invalid route data (misnamed — uses valid route) |
| `backend/tests/test_routing_logic.py` | 6 | `select_best_route`, `find_matching_routes`, `lookup_route` invalid IP, no match |
| `backend/tests/test_routing_api.py` | 9 | `/lookup` HTTP status codes, response fields, `/routes` listing, missing param, custom-table 404 |
| `backend/tests/test_packet_journey.py` | ~60 | Direct delivery, gateway, multi-hop per-router tables, no route, unresolved next hop, broken table, loops, max hop, delivery vs found-route, invalid input, sample table, endpoint contract |
| `backend/tests/test_routing_table.py` | — | CRUD, validation, summary |
| `backend/tests/test_routing_table_persistence.py` | — | load/save/recovery/fallback |

Execution result: `tests/test_routing.py tests/test_routing_logic.py tests/test_routing_api.py tests/test_packet_journey.py` → **90 passed, 0 failed** (0.68s). All routing tests green.

### Classification against the 13 audit categories

| Category | Covered by tests | Assessment |
|----------|------------------|------------|
| IP validation | Yes | Invalid IP, out-of-bounds, cross-family mismatch |
| Longest-prefix match | Yes | Extensively |
| Default route | Yes | `0.0.0.0/0` matches any IP |
| Next-hop resolution | Partial | Direct, gateway, next-hop==destination tested; unreachable/wrong-network next hop NOT tested |
| Interface selection | Partial | Tiebreaker tested; existence/availability/link-state NOT tested |
| Multi-hop forwarding | Yes | 2-router and 3-router, per-router tables |
| Loop detection | Yes | 2-router loop, self-loop, false-loop guard |
| Maximum hops | Yes | But codifies the off-by-one defect |
| Delivery semantics | Yes | deliver only on arrival |
| Failure reporting | Partial | drop/loop/unresolved_next_hop/error distinguished; no structured failure code tested |
| Route mutation | Yes | CRUD + persistence in separate test files |
| Stale simulation handling | No | No version/staleness tests |
| API contract | Yes | Status codes, fields, response model |

### Missing scenarios

- No test that an unparsable destination produces a family-agnostic error message (current tests assert the misleading `"Invalid IPv4 address"` string).
- No test for next-hop == source (self next hop) or circular next hop at a single router.
- No test for a next hop not present in any connected network (unreachable gateway) — indistinguishable from "no route" at trace time.
- No interface down/link-down scenario.
- No stale simulation, cache invalidation, or concurrent simulation test.
- No IPv6 multi-router loop or max-hop test.
- No test that `update_route` with an invalid route and out-of-range index returns 404 (currently returns 400 due to validation order).

### Weak assertions

- `test_routing.py:302-315` (`test_invalid_route_data_returns_error`) uses a **valid** route and only asserts `matched=True`; it never exercises invalid route data through `lookup_route`. The test name does not match its body.
- `test_routing_logic.py:40-43` asserts `error.startswith("Invalid IPv4 address")`, which passes because the message is hard-coded to IPv4 — so the test does not detect the misleading-message defect.
- `test_packet_journey.py:509-511` has a loose `or` assertion on `matched_route_destination` rather than a precise value.

---

## Section F — Defect register

Confirmed defects first, then possible improvements.

### ROUTE-01 — Max-hop off-by-one (Confirmed)
- **Severity:** Medium
- **Confidence:** Confirmed
- **File+function:** `backend/app/routing_logic.py`, `trace_packet_path`, lines 441-450
- **Evidence:** The `hop_number > MAX_HOPS` check runs after `current_ip`/`current_table` have already been advanced to the next router (lines 438-439). With `MAX_HOPS=30`, hop 30 forwards, advances, then `30 > 30` is false, so hop 31 runs; the drop is recorded at hop 32. `test_packet_journey.py:451-473` asserts `len(hops) == MAX_HOPS + 2` (31 forwards + 1 drop), codifying the off-by-one.
- **Expected:** No more than `MAX_HOPS` forwarding decisions before a hop-limit drop.
- **Actual:** Up to 31 forwarding decisions before the drop (one extra beyond the documented limit).
- **Impact:** A packet may traverse one more hop than documented before being discarded; in a loop that evades the `visited` check this delays termination by one hop. Loop detection usually catches loops first, so impact is bounded.
- **Correction direction:** Move the max-hop check to the top of the loop (before processing hop `hop_number + 1`) or change the comparison/branching so the limit is enforced before the 31st forward.

### ROUTE-02 — Misleading invalid-IP error message (Confirmed)
- **Severity:** Low
- **Confidence:** Confirmed
- **File+function:** `backend/app/routing_logic.py`, `lookup_route`, lines 129 and 131
- **Evidence:** When both IPv4 and IPv6 parsing of `destination_ip` fail, the returned error is `f"Invalid IPv4 address: {destination_ip}"` regardless of whether the input could be IPv6 or is not an IP at all. Verified by reading source; `test_routing_logic.py:43` and `test_routing.py:300` assert this exact string.
- **Expected:** A family-agnostic message such as `"Invalid IP address: <input>"`.
- **Actual:** Message always names IPv4 even for non-IP input.
- **Impact:** Cosmetic / debugging clarity only. Clients keyed on the substring "Invalid IPv4 address" still work, but the message is technically wrong for IPv6/garbage input.
- **Correction direction:** Change the error text to `"Invalid IP address: ..."` (matching the `/packet-journey` endpoint wording at main.py:425).

### ROUTE-03 — update_route validates before index range check (Confirmed, minor)
- **Severity:** Low
- **Confidence:** Confirmed
- **File+function:** `backend/app/routing_table.py`, `update_route`, lines 156-162
- **Evidence:** `self._validate_route(route)` runs at line 156, before the `index < 0 or index >= len(...)` check at line 161. Passing an invalid route with an out-of-range index raises `InvalidRouteError` (HTTP 400) instead of `IndexOutOfRangeError` (HTTP 404).
- **Expected:** Index-out-of-range reported as 404 regardless of route validity, or route validation only after index confirmed in range.
- **Actual:** 400 for an invalid route even when the index is also out of range.
- **Impact:** Clients receive a 400 validation error instead of a 404 not-found for a nonexistent route index when the body is also invalid.
- **Correction direction:** Check index range before validating the route, or report index errors with priority.

### ROUTE-04 — No next-hop reachability / interface validation (Suspected)
- **Severity:** Medium
- **Confidence:** Suspected
- **File+function:** `backend/app/routing_logic.py`, `trace_packet_path`, lines 385-439
- **Evidence:** The engine forwards to `route.get_next_hop()` on `route.interface` without checking that the next hop is on the interface's subnet, that the interface exists, or that the interface is up. No such validation exists in `trace_packet_path` or `lookup_route`.
- **Expected:** An unreachable next hop or mismatched interface/network should be reported as a distinct failure rather than silently forwarded or collapsed into "no route"/"unresolved_next_hop".
- **Actual:** Forwarding proceeds purely from table contents; reachability is not modeled.
- **Impact:** The engine cannot report "gateway unreachable" or "wrong interface" as distinct failure reasons; these are indistinguishable from a missing route until the trace reaches an unknown router.
- **Correction direction:** Add optional interface/network relationship validation at next-hop resolution (without redesigning the model).

### ROUTE-05 — No stale-simulation version tracking (Suspected)
- **Severity:** Medium
- **Confidence:** Suspected
- **File+function:** `backend/app/routing_table.py`, `backend/app/routing_table_persistence.py`; `trace_packet_path` takes a snapshot `routes` list at call time
- **Evidence:** `RoutingTable.__init__` loads from persistence once; there is no generation counter, timestamp, or invalidation mechanism on the table or on traces. `trace_packet_path` receives a `routes` list snapshot with no version token, so callers cannot detect that the table changed mid-simulation.
- **Expected:** Repeated/concurrent simulations against a mutated table should detect staleness (e.g., via a table version or etag).
- **Actual:** No versioning; a stale table is used silently.
- **Impact:** A client could base decisions on a table that has since been mutated, with no way to detect the change.
- **Correction direction:** Add a table version/generation counter returned with lookups and accepted (optionally) by trace requests for staleness detection.

### ROUTE-06 — Failure reported as free-text string, not structured code (Possible improvement)
- **Severity:** Low
- **Confidence:** Confirmed
- **File+function:** `backend/app/main.py`, `trace_packet_journey`, line 460-466; `backend/app/routing.py` `PacketJourneyResponse`
- **Evidence:** `error` is a plain string taken from a hop's `explanation`. The response has no `failure_reason` enum field. The frontend `JourneyOutcome` type (`frontend/src/types/routing.ts:475-482`) enumerates outcomes but the backend does not emit a matching code; the frontend infers outcome by substring-matching explanations (`frontend/src/components/PacketJourney.tsx:157-161`).
- **Expected:** A structured failure reason (e.g. `no_route`, `loop`, `hop_limit_exceeded`, `unresolved_next_hop`, `invalid_input`) alongside the explanation.
- **Actual:** Only `error` string; clients must parse text.
- **Impact:** Fragile client-side parsing; wording changes break outcome classification.
- **Correction direction:** Add a `failure_reason` / status field to `PacketJourneyResponse` mirroring `JourneyOutcome`.

### ROUTE-07 — Duplicate PacketHop dataclass (Possible improvement, cosmetic)
- **Severity:** Low
- **Confidence:** Confirmed
- **File+function:** `backend/app/routing.py` line 185 and `backend/app/routing_logic.py` line 175 both define `PacketHop`
- **Evidence:** Two near-identical dataclass definitions of `PacketHop` exist. `trace_packet_path` uses the local one in `routing_logic.py`; `routing.py`'s is the "authoritative" one referenced in docstrings.
- **Expected:** Single source of truth.
- **Actual:** Duplicate definition; risk of divergence.
- **Impact:** Maintenance risk only; no functional defect observed.
- **Correction direction:** Import/reuse one definition.

### ROUTE-08 — Duplicate PacketHop dataclass (Possible improvement, cosmetic)
- **Severity:** Low
- **Confidence:** Confirmed
- **File+function:** `backend/app/routing.py` line 185 and `backend/app/routing_logic.py` line 175 both define `PacketHop`
- **Evidence:** Two near-identical dataclass definitions of `PacketHop` exist. `trace_packet_path` uses the local one in `routing_logic.py`; `routing.py`'s is the "authoritative" one referenced in docstrings.
- **Expected:** Single source of truth.
- **Actual:** Duplicate definition; risk of divergence.
- **Impact:** Maintenance risk only; no functional defect observed.
- **Correction direction:** Import/reuse one definition.

### Possible improvements (non-defect)
- The `/lookup` 404 (no match) returns `{"detail": "..."}` rather than a `RouteLookupResult{matched:false}` body; clients cannot read `matched` from a 404. Consider returning 200 with `matched:false` or a consistent error envelope.
- `lookup_route` validates all routes in the table on every lookup (lines 134-144), an O(n) cost per lookup; acceptable for a teaching table but worth noting.
- IPv6 error message hard-coded to IPv4 is subsumed by ROUTE-02.

---

## Section G — Recommended implementation order

Prioritizing correctness and dependencies. No cosmetic changes first.

1. **Fix ROUTE-01 (max-hop off-by-one).** Dependency: none. Correctness-critical for the documented hop limit; move the check to the top of the trace loop before processing each hop.
2. **Fix ROUTE-02 (misleading IPv4 error message).** Dependency: none. One-line message change; aligns `/lookup` wording with `/packet-journey`.
3. **Fix ROUTE-03 (update_route validation order).** Dependency: none. Reorder index check before route validation so out-of-range returns 404.
4. **Add ROUTE-06 structured failure_reason.** Dependency: ROUTE-01/02 first (stable hop actions). Adds a structured outcome field so the frontend need not substring-match explanations.
5. **Add ROUTE-04 next-hop reachability validation.** Dependency: none, but scope-creep into interface/network modeling; do after the hop-limit correctness fixes.
6. **Add ROUTE-05 stale-simulation version tracking.** Dependency: none; orthogonal. Add a table generation counter exposed via `/routes/summary` and accepted by trace requests.
7. **Address ROUTE-07/08 duplicate PacketHop.** Cosmetic; do last, only when touching `routing_logic.py`/`routing.py` for another reason.

Do not make cosmetic changes (duplicate dataclass, comments) ahead of the correctness fixes.

---

## Section H — Safety and Git status

Confirmed read-only:

- No source code modified. `git diff --stat` shows modifications only to `lab_adapter.py`, `lab_builder.py`, `packet_lab.py`, `test_packet_lab.py`, `VirtualLabPanel.tsx` — none are routing-engine core modules (`routing.py`, `routing_logic.py`, `routing_table.py`, `routing_table_persistence.py` are unchanged from HEAD `eea5382`).
- No changes discarded; no `git reset`, `checkout`, or `stash` performed.
- No networking changed; no `ip`, `ifconfig`, `route`, or socket-altering commands run; the network collector was not invoked.
- No commits, merges, or pushes performed.
- No dependencies installed; tests run with the existing `.venv`.
- No tests or configuration modified.
- The deliverable `/home/abhaysawant/Desktop/cn_project_2/docs/qa/PHASE_2_ROUTING_ENGINE_AUDIT.md` was created (it did not previously exist); no existing file was overwritten.

Baseline (read-only): branch `integration/baseline-2026-10-20`, HEAD `eea5382 feat: complete RouteLens Lite integration and demo readiness`. Working tree has 5 modified non-routing files and 3 untracked entries, all pre-existing before this audit.
