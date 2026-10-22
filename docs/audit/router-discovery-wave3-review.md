# Router Discovery — Wave 3 Review

**Reviewer:** Agent E (independent, read-only)
**Date:** 22 October 2026
**Branch:** `feature/router-discovery-audit`
**Subject:** the integrated result of the router discovery milestone

Every verdict below is **CONFIRMED**, **NOT CONFIRMED**, or **NOT IMPLEMENTED**,
with the evidence. "Run" means I executed something; "read" means I inspected
the source.

---

## What had landed when this review was made

| Branch | Head | What it carries |
|---|---|---|
| `feature/router-discovery-core` | `e9910a6` | models, engine, graph, collectors |
| `feature/router-discovery-ui` | `56fd241` | the map, the page, the types, the client |
| `feature/router-discovery-lab` | `c9ae9e6` | the containerlab FRR lab and its test |
| `feature/router-discovery-tests-docs` | `29a5498` | `docs/router-discovery.md`, the test plan, the README section |

**The analysis and the API routes are not in any branch.** There is no
`analysis.py`, no `select_route`/`build_fib`, and no `/api/router-discovery/`
endpoint anywhere. Agent A's fixes for findings 1, 2 and 5 are in A's
**uncommitted** work, so this review could not see them. The wave-2 proofs
still fail against the committed code; that is expected and is not a
complaint about A.

---

## Area 1 — the frontend

### CONFIRMED CORRECT

**An OBSERVED edge comes from an observation.** `graph.py` builds LLDP and CDP
adjacencies as `observed` and next-hop and shared-subnet adjacencies as
`inferred`. The UI colours by `EDGE_COLORS[edge.provenance]` with an
`unknown` fallback, and labels each edge with its kind — "LLDP", "CDP",
"next hop", "shared subnet".

**An INFERRED edge is not presented as observed.** This is done properly, and
better than colour alone:

```tsx
// An inferred link is dashed, so it reads as a deduction even in
// a print-out or for a reader who cannot rely on colour.
strokeDasharray: edge.provenance === 'inferred' ? '8 5' : undefined,
```

The legend reads, verbatim:

> **Observed** — the device said so (LLDP or CDP). Solid.
> **Inferred** — the backend worked it out (a next hop or a shared subnet). Dashed.
> **Not collected** — the device could not be read.

**A device that was not reached is not an ordinary node.** The node takes
`FAILED_COLOR`, the `failed` class, and a `not collected` badge. The node
type carries `error: string | null` and `provenance: RouterDiscoveryProvenance`,
and that type includes `'unknown'`, so the API can mark such a device
honestly.

**The empty states are right.** A failed run says "The run failed, so there is
no map to draw. What went wrong is listed above." A run that has not happened
says "No discovery has been run yet." A completed run that found nothing says
"That is what the backend reported. Nothing is drawn, because there is nothing
to draw." A refused run is therefore not shown as a run that found nothing.

### FINDING F1 — the drawer can call an uncollected device a real reading

**CONFIRMED. The most visible lie available in this milestone.**

The device drawer renders:

```tsx
{device.routes.length === 0 ? (
  <p className="device-muted">
    This device reported no routes. That is a real reading, not a missing one.
  </p>
) : ( ... )}
```

and, further down:

```tsx
{device.provenance === 'observed'
  ? ' These are the numbers the device reported.'
  : ' These are the backend's reading of the device.'}
```

For a device that was **never collected**, both sentences are false: it
reported nothing, and what it "reported" was not a reading at all.

The drawer cannot tell the difference. `RouterDiscoveryDevice extends
DeviceSnapshot`, and `DeviceSnapshot` has `errors: List[str]` but no
top-level field saying "this device was not collected". The **node** type has
`error: string | null`, so the map knows — but the drawer fetches the
*device*, and the device type cannot carry the failure.

The drawer is safe only if the API **404s** a device that was not collected;
then the fetch's `.catch` sets `deviceError` and the false sentence is never
reached. That is a contract, and it is not fixed, not written down, and not
tested anywhere.

**Smallest fix.** The drawer must branch on the failure state rather than on
the route count: if the selected node carries an `error`, say "this device
could not be collected" and why, and do not say "reported no routes". The
node is already in the page.

**Owner:** UI stream, with the API half.

### FINDING F2 — a finding carries no provenance

**CONFIRMED.**

```ts
export interface RouterDiscoveryFinding {
  device_id: string;
  kind: string;
  severity: string;
  title: string;
  detail: string;
  evidence: string;
}
```

No provenance field, and the rendering shows the title, the severity, the
detail and the evidence with no badge. The map's **edges** are marked as
observed or inferred and the legend explains it; the **findings**, which are
where the analysis conclusions live, are not marked at all.

The rule the milestone set is that a finding which rests on an inference must
say so in the finding itself, not in a separate field a reader has to know to
look at. Right now the only place a reader could learn that a finding is a
deduction is the prose of `detail` or `evidence`, which is not a guarantee.

**Smallest fix.** Add `provenance` to the finding and render
`ProvenanceBadge`, exactly as the edges do. The analysis model has to carry
it.

**Owner:** UI stream, with the analysis model.

---

## Area 2 — the API responses, read as a user

**NOT IMPLEMENTED. There is no API to review.**

No `/api/router-discovery/` route exists on any branch, so no response can
be read as a user would read it. What can be stated is the contract the
frontend already implies, and that contract is itself the finding:

1. **A device that was not collected must not come back as a device with no
   routes.** The frontend's drawer assumes the API 404s it (F1). That must
   be written down and tested, or the drawer will say the false thing.
2. **A device that was not collected must be a node with `error` set and
   `provenance: 'unknown'`,** so the map can mark it. The type supports it;
   the API must do it.
3. **A refused seed must appear in `run.failures`,** which the frontend
   renders as "What could not be collected". The frontend's
   `failures: Record<string, unknown>` is deliberately open, so the shape is
   the API's to choose — but the *presence* of the entry is not.
4. **A finding must carry its provenance** (F2), and it must carry it in the
   finding, not beside it.
5. **A device reached by a second address must not be collected twice, and
   the run must not present it as two devices.** The engine does this
   already — `seen_devices` — and the frontend renders the map from the
   backend's node list, so it follows.
6. **A limit that truncated the run must be visible in the result** — see
   D1 below.

---

## Area 3 — the claims in the documentation

### CONFIRMED CORRECT

The documentation is unusually honest, and the honesty is load-bearing.

`docs/router-discovery.md` opens:

> **Status: skeleton.** This feature is under construction. ... Nothing here
> should be read as a promise that the feature is ready to use.

The README says:

> **Under construction. There is no usable feature here yet.**

**There is no claim anywhere that the module was tested against a real
router, and no claim that the lab was deployed.** I grepped the README, the
feature document and the test plan for "real router", "tested against",
"verified against", "deployed" and "production-ready": the only hits are
the design discussion of what a management plane is, and the document's own
status banner. That is exactly right — no router was contacted and the lab
was never deployed.

**"No packets" holds.** The engine never probes. The lab branch's
integration test contains no ping, no icmp, no nmap and no scapy. And
`scripts/lab-up.sh` takes sudo only as an explicit `--sudo` flag — never
silently — and states that it installs neither docker nor containerlab. The
lab test skips unless docker **and** containerlab **and** a deployed lab are
all present, which is the right guard.

**"A run is private to whoever started it" is a rule with no implementation
yet**, and the document says so: the "three compatibility decisions that
will settle the exact shape — the allowlist's surface, the scope's shape, and
how a run is scoped to the client that started it — are still open".

### FINDING D1 — "a run that stops at a limit says it stopped at a limit" is not true

**CONFIRMED. Run against the committed code.**

The document claims:

> **Bounded.** `max_depth` and `max_devices` are limits, not suggestions. A
> run that stops at a limit says it stopped at a limit, so that a small
> result is not mistaken for a complete one.

What actually happens, with `max_depth=1`:

```
progress lines the run produced:
    collected d1 at 10.0.0.1 (0 interface(s), 1 route(s))
    collected d2 at 10.0.0.2 (0 interface(s), 1 route(s))

devices collected: 2 | failures recorded: 0
does the RESULT record that it stopped at the depth limit?
   DiscoveryResult fields: ['devices', 'failures']
```

The depth limit says **nothing at all** — not a progress line, and nothing
in the result. `max_devices` does emit a progress line, but neither limit is
recorded in `DiscoveryResult`, which has only `devices` and `failures`. So a
run that was truncated is indistinguishable from a complete one, both in the
result and in the log the user reads.

**Smallest fix.** The engine must record that a limit was reached and the
result must carry it — a `stopped_at_limit` field, or a failure entry for
the limit — so the "bounded" rule is true as written.

**Owner:** core stream.

### FINDING D2 — "no credentials in a log" is not true yet

**CONFIRMED.** The document's rule 5 is:

> **No credentials in, no credentials out.** Not in a request, not in a
> response, and not in a log. A credential that is not returned can still be
> written to a log file, and a log file outlives the request.

`redact()`'s userinfo pattern requires a trailing `@`, so
`"login failed for admin:letmein"` is written to the audit trail verbatim.
The keyword pattern covers only `password`, `secret`, `token` and
`api[-_]?key`. This is wave-2 finding 6, and it is the one I would fix
first: it is the only place where the code contradicts a safety rule the
document states as absolute.

**Owner:** core stream.

### FINDING D3 — "a device that failed to collect is not a device with nothing on it" is true in the model, not yet in the API

**CONFIRMED as a gap.** The model keeps them apart — `DeviceSnapshot.errors`
for a partial failure, `CollectionFailure` for a device that could not be
collected. But the API does not exist, and the drawer's empty-routes sentence
contradicts the rule unless the API 404s (F1).

**Owner:** API stream, with the UI stream.

---

## What was verified at runtime, and what was not

**Run against the code:**

- the depth-limit claim (D1) — the run, its progress lines and the result's
  fields
- the eight wave-2 proofs, still failing against the committed core

**Read, not run:** every verdict about the frontend (F1, F2, the empty
states, the legend, the dash), the API contract items, and the documentation
claims. The API does not exist to run against.

**Not done, deliberately:** no privileged operation, no sudo, no host
networking change, no lab deploy, no scan, no device contacted, no package
installed, and no change to any file owned by another stream.
