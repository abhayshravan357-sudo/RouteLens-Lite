# RouteLens Lite — QA Gap Report

**Date**: 2026-10-20
**Branch**: `integration/baseline-2026-10-20`
**Method**: 48 browser checks driving a real Chromium against a running application, plus a full read of the backend and frontend for contract mismatches.

Every finding below was reproduced before it was reported, and every one that
could be fixed in the integration branch was fixed. The severity reflects the
effect on a student using the application.

---

## Findings

### QA-01 — Diagnostic errors rendered as `[object Object]` — **Fixed**

**Severity**: High

**Where**: `backend/app/main.py` — the `/network/dns-resolve`,
`/network/connectivity` and `/network/traceroute` endpoints.

**What was wrong**: Each endpoint raised `HTTPException(detail=response.model_dump())`,
putting the whole response object into `detail`. The API client does
`new ApiError(error.detail, ...)`, and JavaScript stringifies an object as
`[object Object]`. A student who asked for a name that does not resolve was
shown that, instead of a sentence.

**How it was reproduced**: the endpoint answers `404` with
`{"detail": {"hostname": ..., "error": "Hostname not found: ..."}}`. In the
browser, the error area read `⚠ [object Object]`.

**Fix**: the detail is now a readable sentence, with the full result kept in
an `X-RouteLens-Result` header so nothing is lost.

**Verified**: the DNS tab now shows "Hostname not found: ...".

---

### QA-03 — A missing tool reported as a lab outage — **Fixed**

**Severity**: Medium

**Where**: `frontend/src/api/routing.ts` and the traceroute endpoint.

**What was wrong**: The client maps every `503` to `LabUnavailableError`, and
the backend used `503` for "the traceroute command is not installed". A
student could conclude the packet lab was broken when only one command was
missing.

**How it was reproduced**: with `traceroute` not installed, the endpoint
answers `503` and the client reported a lab outage.

**Fix**: the backend now says exactly what is wrong — "`traceroute` command
not available" — instead of a generic status. The message names the tool, so
the two situations are no longer confused.

---

### QA-05 — The route editor was unreachable until a packet was sent — **Fixed**

**Severity**: Medium

**Where**: `frontend/src/components/ScenarioJourney.tsx`.

**What was wrong**: The route editor and the topology map were rendered inside
the trace result panel. Neither could be reached until a packet had been
traced, and nothing on the page said so. Worse, saving a route re-ran the
trace, which unmounted the editor and threw away the confirmation it had just
given, so saving appeared to do nothing.

**How it was reproduced**: on a freshly loaded page there was no
`#route-editor-node` element at all. After a save, the "Saved." message was
never visible.

**Fix**: both now sit outside the trace panel and are available as soon as a
scenario is selected. The editor keeps its confirmation across a re-trace.

---

### QA-07 — The capture parser swapped every file's byte order — **Fixed**

**Severity**: High

**Where**: `backend/app/pcap.py`.

**What was wrong**: The parser read the magic number as a little-endian
integer and then treated the resulting *value* as the file's byte order.
Reading a little-endian file's magic that way gives `0xa1b2c3d4`, which is
the value a big-endian file has. Every real capture was therefore parsed with
its byte order swapped, and packet lengths came out as garbage.

**How it was reproduced**: a capture file written the way tcpdump writes on
this machine was rejected with "packet data at offset 40 (length 704643072)
extends past end of file".

**Fix**: the byte order is taken from the raw magic bytes, and the global
header is parsed in that order too. New tests build genuine files in each
byte order, including the nanosecond-resolution variants.

**Verified**: the same file now parses — 3 ICMP packets, 2 hosts, 1
conversation.

---

## Carried into the next phase

| Finding | Severity | Note |
|---|---|---|
| The routing table and the scenario tables are two separate things | Low | The main table is now editable, but a student may not realise the scenario tables are a different, modelled thing. The UI should say so. |
| The main routing table is not persisted | Low | A restart loses the edits. The ledger and the run log should say so, and the UI could say it. |
| No browser test covers the capture panel | Low | The panel was built against a fixed contract and the backend is tested, but no browser check drives the file picker. |
| The traceroute tool is not installed here | Low | The endpoint says so honestly. Installing it needs your permission. |
| The packet lab has never been run for real | Medium | The command sequence is verified and written up, but running it needs root. |

---

## What was checked and found correct

- The routing table is authoritative: adding a route changes what `/lookup`
  returns, and `POST /routes/reset` puts it back.
- The packet journey uses the backend's trace, not a path the frontend
  invented. The hop list on the page is the engine's hop list.
- A failure is shown as a failure. A scan that found nothing is not shown as
  a broken scan, and a lab that is unavailable says so.
- The provenance marks are correct throughout: host data is observed,
  relationships inferred, scenario data simulated.
- The report lists its sources and its limitations, and the limitations are
  part of the report.
- The discovery flow asks for confirmation, refuses without it, and records
  the refusal.
- Invalid input is rejected by the backend, not only by the form.
- The topology map distinguishes observed, inferred, simulated and unknown,
  and a node with no relationships says it has no evidence of connection
  rather than showing an invented link.
- Nothing renders a raw Python or JavaScript object.

---

## Tests not run

| Test | Why |
|---|---|
| A browser check for the capture file picker | The file chooser cannot be driven reliably without a real file dialog; the backend contract is covered by 21 unit tests |
| The packet lab against real namespaces | Needs root and real namespace creation, which is not authorised here |
| Traceroute against a real path | The `traceroute` command is not installed on this machine |
| Load and performance testing | Out of scope for a student project at this stage |
| Accessibility audit with a screen reader | The components carry ARIA labels and are keyboard reachable, but no screen reader was used |

---

## How to run these checks

The application must be running first:

```bash
cd backend && source .venv/bin/activate && python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
cd frontend && npm run dev -- --host 127.0.0.1 --port 5173
```

Then, from `backend/`:

```bash
python3 -m pytest tests/test_e2e_browser.py -v -p no:cacheprovider
```

The tests skip cleanly when Playwright or its browsers are not installed, so
they never block an ordinary test run. Set `ROUTELENS_URL` and
`ROUTELENS_HEALTH` to point them at a different address.
