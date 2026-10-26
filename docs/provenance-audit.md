# Provenance Audit — Workstream C, Phase 3.2

Scope: backend networking endpoints and Packet Lab readiness logic in
`~/Desktop/cn_project_2/backend/app`. All files inspected read-only; no
production files were modified.

## 1. Correct behaviour confirmed

### 1.1 `source_type` default is `"unknown"` (never `"real_host"`)

`backend/app/network_collector.py:140`:
```python
source_type: str = "unknown"
```
The `CollectionResult` dataclass defaults `source_type` to `"unknown"`, so any
construction site that omits the field can never be mistaken for real host data.
Confirmed by test at `backend/tests/test_network_collector.py:362`:
```python
assert result.source_type == "unknown"
```

### 1.2 Actual host observations are labelled `real_host`

All three successful host collection paths set `source_type="real_host"`:

- `network_collector.py:372` — `collect_interfaces` success: `source_type="real_host"`, `source_description="Read from the host using ip -j addr show"`
- `network_collector.py:499` — `collect_routes` success: `source_type="real_host"`
- `network_collector.py:641` — `collect_neighbors` success: `source_type="real_host"`

Confirmed by tests at `test_network_collector.py:490`, `:504`, `:518`.

### 1.3 Failed / unavailable collection does NOT falsely claim `real_host`

Every failure path omits `source_type`, so it falls back to `"unknown"`:

- `network_collector.py:326` — `collect_interfaces`, `ip` command not found (no `source_type`)
- `network_collector.py:339` — `collect_interfaces`, command failed (no `source_type`)
- `network_collector.py:351` — `collect_interfaces`, JSON parse failed (no `source_type`)
- `network_collector.py:435` — `collect_routes`, invalid address family (no `source_type`)
- `network_collector.py:450` — `collect_routes`, `ip` command not found (no `source_type`)
- `network_collector.py:464` — `collect_routes`, command failed (no `source_type`)
- `network_collector.py:477` — `collect_routes`, JSON parse failed (no `source_type`)
- `network_collector.py:567` — `collect_neighbors`, invalid address family (no `source_type`)
- `network_collector.py:582` — `collect_neighbors`, `ip` command not found (no `source_type`)
- `network_collector.py:596` — `collect_neighbors`, command failed (no `source_type`)
- `network_collector.py:609` — `collect_neighbors`, JSON parse failed (no `source_type`)

All 14 construction sites were located via grep; exactly 3 set `source_type="real_host"` (the success paths), and the remaining 11 rely on the `"unknown"` default.

### 1.4 `/network/*` endpoints return correct `source_type`

`backend/app/main.py` endpoints return the `CollectionResult` directly on success:

- `/network/interfaces` — `main.py:479` returns `result` (carries `source_type="real_host"` on success; raises HTTPException on failure, so a failed result is never returned as `real_host`)
- `/network/routes` — `main.py:511` returns `result`
- `/network/neighbors` — `main.py:638` returns `result`
- `/network/all` — `main.py:662` returns the `collect_all()` results dict; each entry is a `CollectionResult` with correct `source_type`

Failed collections raise `HTTPException` (e.g. `main.py:476-477`, `:508-509`, `:635-636`) rather than returning a mislabelled result.

### 1.5 Python route simulations are labelled `simulated`

- `backend/app/routing.py:292-298` — `PacketJourneyResponse.provenance` defaults to `"simulated"`; set explicitly at `main.py:455`.
- `backend/app/routing.py:309,317,326,334,341,350,359,368,375,383` — all `SAMPLE_ROUTES` entries use `provenance=Provenance.SIMULATED`.
- `backend/app/scenario.py:158` — `TraceResult.provenance` defaults to `"simulated"`; all 7 return sites in `trace()` (lines 291, 306, 322, 338, 357, 376, 410) rely on the default.
- `backend/app/report.py:176,197,215` — active experiment evidence items use `provenance="simulated"`.
- `backend/app/report.py:407,434` — teaching table and scenario evidence items use `provenance="simulated"`.

### 1.6 Inferred analysis is distinguishable from observed information

- `backend/app/route_analysis.py:104-105` — `RouteAnalysisReport.table_provenance="observed"`, `analysis_provenance="inferred"`.
- `backend/app/route_analysis.py:90` — `DestinationAnalysis.provenance` defaults to `Provenance.INFERRED.value`.
- `backend/app/route_analysis.py:197` — converted teaching entries use `provenance=Provenance.OBSERVED` (they derive from observed kernel routes).
- `backend/app/main.py:351-352` — `/routes/analysis` returns `table_provenance="simulated"`, `analysis_provenance="inferred"` for the editable teaching table.
- `backend/app/network_collector.py:99-115` — `NameLookupSummary` separates observed neighbour addresses from inferred reverse-DNS names; `NeighborInfo.name_provenance` (line 95) records `"inferred"`, `"not_looked_up"`, or `"unknown"` per name.
- `backend/app/packet_lab.py:32-36` — `VerificationProvenance` enum (`OBSERVED`/`INFERRED`/`SIMULATED`/`UNKNOWN`) and `VerificationField` (line 40-44) carry per-field provenance in Packet Lab verification.

### 1.7 Packet Lab results are NOT presented as verified real observations unless the lab is available

- `backend/app/lab_adapter.py:498-503` — `check_lab_readiness()` sets `overall_ready` only when topology is correct, all namespaces exist and are accessible, no tools are missing, and no permission issues exist.
- `backend/app/packet_lab.py:183-190` — `PacketLab.get_status()` returns `available=False`, `state=LabState.UNAVAILABLE` when `readiness.overall_ready` is false, with `error=readiness.summary`.
- `backend/app/packet_lab.py:226` — `available=readiness.overall_ready` (not hardcoded true).
- `backend/app/packet_lab_routes.py:159-163` — `get_lab_status` raises HTTP 503 when `not lab_status.available`; never returns `available=true` for a missing lab.
- `backend/app/packet_lab_routes.py:217-221` — `simulate_packet` raises HTTP 503 when the lab is unavailable; does not fabricate capture results.
- `backend/app/packet_lab.py:288-294` — `simulate()` returns `state=LabState.UNAVAILABLE` with an error when `status.available` is false.
- Confirmed by `backend/tests/test_packet_lab_integration.py:44,73` (expects 503) and `:48-53` (detail honestly names the unavailability reason).

### 1.8 Error responses explain why an operation is unavailable

- `backend/app/lab_adapter.py:505-528` — `check_lab_readiness()` builds a `summary` that names every blocker: topology issues, missing tools, permission issues, and per-namespace errors.
- `backend/app/packet_lab.py:189` — propagates `readiness.summary` as the `error` message.
- `backend/app/packet_lab_routes.py:162` — passes `lab_status.error` as the HTTP 503 `detail`.

## 2. Remaining defects

No provenance defects were found. Every construction site, default, and endpoint
behaves correctly with respect to the seven verification criteria.

Two minor observations (not defects, but worth noting for consumers):

**2.1 Neighbour EvidenceItem top-level provenance vs. inferred hostname**
`backend/app/report.py:349` sets `provenance="observed"` on the neighbour
EvidenceItem, but the `value` dict includes `hostname` (inferred via reverse
DNS) together with `name_provenance` (which records `"inferred"` /
`"not_looked_up"` / `"unknown"`). The neighbour entry fields themselves are
observed from the kernel, so the top-level `"observed"` is correct for them;
the name's provenance is tracked separately inside `value.name_provenance`.
A strict consumer reading only the top-level `provenance` field could
overstate certainty about the hostname. No change is required, but consumers
should check `value.name_provenance` before trusting a neighbour hostname.

**2.2 Traceroute carries no `source_type`**
`backend/app/network_collector.py:1224` `trace_route()` returns a
`TracerouteResult`, not a `CollectionResult`, and `TracerouteResult` has no
`source_type` field. The `/network/traceroute` endpoint
(`main.py:900-979`) returns `TracerouteResponse`, which also has no
`source_type`. Traceroute is a real host observation but is not labelled
`real_host`. This is outside the `CollectionResult` provenance scheme; if
`source_type` labelling is desired for traceroute, a field would need to be
added to `TracerouteResult`/`TracerouteResponse`.

## 3. Provenance fallback chain analysis

The fallback chain is uniform and safe across all collection code:

```
Construction site
  ├─ explicit source_type="real_host"  (success paths only: lines 372, 499, 641)
  └─ no source_type specified
        └─ CollectionResult default: source_type="unknown"  (line 140)
```

For `TraceResult`:
```
Construction site (trace(), 7 sites)
  └─ no provenance specified
        └─ TraceResult default: provenance="simulated"  (scenario.py:158)
```

For `EvidenceItem`:
```
Construction site (report.py)
  └─ provenance is a required Pydantic field (report.py:59), no default
        └─ every call site supplies an explicit literal:
             "observed"  (host interfaces/routes/neighbours)
             "simulated" (teaching table, scenarios, active experiment)
             "unknown"   (collection failures/exceptions)
```
Because `provenance` has no default on `EvidenceItem`, a missing value is a
construction error rather than a silent wrong assumption.

For Packet Lab verification:
```
VerificationProvenance enum (packet_lab.py:32-36)
  └─ per-field VerificationField.provenance (packet_lab.py:43)
       ├─ OBSERVED   — parsed from tcpdump capture output
       ├─ INFERRED   — deduced from ping success when capture lacks the datum
       ├─ SIMULATED  — (available, not currently emitted by this code path)
       └─ UNKNOWN    — datum could not be determined at all
```
The `PacketLab.simulate()` method (lines 343-358) explicitly downgrades to
`INFERRED` when tcpdump output is absent, rather than claiming `OBSERVED`.

`LabStatus.available` is the master switch for the Packet Lab: it is set from
`readiness.overall_ready` (lab_adapter.py:498-503), never hardcoded true, and
the `/api/lab/status` endpoint (packet_lab_routes.py:159-163) refuses with 503
when it is false.

## 4. Could missing metadata ever be presented as real host data?

**No.** The `source_type` default is `"unknown"` (network_collector.py:140),
and every failure path omits `source_type`, so it can never silently resolve to
`"real_host"`. The only sites that set `source_type="real_host"` are the three
successful host collection paths (lines 372, 499, 641), all of which require
`success=True` and data read from the host via `ip -j`. Failed collections are
either returned with `source_type="unknown"` (if returned at all) or cause the
endpoint to raise `HTTPException` (main.py:476-477, 508-509, 635-636), so no
failed/unavailable collection reaches a client labelled `real_host`.

`EvidenceItem.provenance` is required with no default (report.py:59), so missing
metadata there is a construction failure, not a silent `"observed"` or
`"real_host"` assumption. `TraceResult.provenance` defaults to `"simulated"`
(scenario.py:158), never to an observed/real value. `PacketJourneyResponse.provenance`
defaults to `"simulated"` (routing.py:292-293).

Therefore missing metadata can never be presented as real host data anywhere in
the audited code.