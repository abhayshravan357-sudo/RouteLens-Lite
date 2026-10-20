# QA Gap Report — RouteLens Lite

**Date**: 2026-10-20
**Auditor**: Agent 4 (TestPilot)
**Branch**: `feature/audit-new-features` (from `integration/baseline-2026-10-20`)
**Scope**: route table analysis, deeper capture analysis, IPv6 collection, and a
re-check of the four defects found in the previous audit.

> **Status: all five findings are now closed.**
> The findings below are kept as they were written, because the reasoning
> behind each one is still worth reading, with the fix recorded beneath it.
> The fixes landed in the visual redesign and in the integration that
> followed it.

---

## 1. Summary

The backend work that has landed is careful and honest. The provenance split
between what was *read* and what was *concluded* is correct, routes the model
cannot express are listed rather than dropped, and the capture parser refuses
to guess. The four defects from the previous audit are all fixed and I have
added regression checks that lock them in.

The problem was on the other side of the wire. **Two of the three new features
had no user-facing surface at all**: the frontend never called
`/network/routes/analysis`, and the frontend's capture types and panel ignored
everything the new capture parser produced. The third, IPv6 collection, was
wired up in the collector but the endpoint that would expose it dropped the
parameter on the floor.

| Area | State then | State now |
|------|------------|-----------|
| Route table analysis (backend) | Solid, honest, well tested — **no UI** | Solid; the **Kernel Table** view shows the analysis and the shadow findings |
| Deeper capture analysis (backend) | Solid — **no UI, and the frontend type was wrong** | Solid; the types match and the panel shows ports, flags, handshakes, DNS names and ARP |
| IPv6 route collection | Collector supported it; the endpoint did not expose it | The endpoint takes `ip_version` and the collector reads both tables |
| The four earlier defects | All fixed, now covered by regression checks | Still fixed, still covered |

**Two of the three `xfail` checks were hiding a broken test fixture.** The
capture check asserted that a DNS name was shown, but the PCAP the test built
put the question count in the DNS *flags* field, so the message it produced
said it had no questions at all. The backend was right to report no name; the
fixture was wrong. The fixture is fixed, and the DNS name now shows.

---

## 2. Findings

### QA-06 — The route analysis is never shown to the user — **High**

- **Endpoint**: `backend/app/main.py:338` — `@app.get("/network/routes/analysis", ...)`
- **Missing client**: `frontend/src/api/routing.ts` has no function that calls
  `/network/routes/analysis`. A search of the whole of `frontend/src` for
  "analysis" returns only the PCAP panel's local variable
  (`frontend/src/components/PCAPPanel.tsx:60`).
- **Owner**: the frontend agent.

**Reproduction**

```bash
curl -s "http://127.0.0.1:5199/network/routes/analysis" | head -c 200
# -> a full analysis report
```

Then open the app in a browser and look through every tab: the analysis is
nowhere. There is no panel, no tab and no button that reaches it.

**Evidence that it works and is worth showing**

```
ip_version: ipv4
table_provenance: observed
analysis_provenance: inferred
routes_in_table: 2 routes_analysed: 2
--- analysis for 192.168.0.107 matched=True prov=inferred
    selected: 192.168.0.0/24
    cand: 192.168.0.0/24 selected=True  outcome=selected
    cand: 0.0.0.0/0     selected=False outcome=less specific
```

That is exactly the teaching content the feature was built for, and none of it
can be reached.

**What should happen**: a frontend client for `/network/routes/analysis` and a
panel that shows, per destination, the winning route, the candidates it beat
and why each lost, with the *inferred* badge on the conclusion and the
*observed* badge on the table it was read from.

**Check added**: `TestRouteAnalysisIsNotShownToTheUser::test_the_route_analysis_is_visible_somewhere_on_the_page`
(marked `xfail`; it will start failing the day a client appears, which is the
point).

**Resolution**: fixed. The visual redesign added the **Kernel Table** view,
which calls `fetchRouteAnalysis()` and renders the winning route, the
candidates it beat, and the shadow findings — with the *inferred* badge on
the conclusion and the *observed* badge on the table it was read from. The
check is no longer marked `xfail` and passes against the Kernel Table view.

---

### QA-07 — The frontend capture type does not match the backend, and the new detail is not rendered — **High**

- **Type**: `frontend/src/types/routing.ts:512-549`
- **Panel**: `frontend/src/components/PCAPPanel.tsx`
- **Owner**: the frontend agent.

`PcapAnalysisResult` in the frontend has `filename`, `size_bytes`, `format`,
`parsed`, `error`, `collected_at`, `summary`, `hosts`, `conversations` and
`limitations`. The backend now also returns **`packets`** and **`handshakes`**
(`backend/app/pcap.py:162-163`), and `PcapSummary` now also carries
`unparsed_packets`, `tcp_handshakes`, `complete_tcp_handshakes`, `dns_queries`,
`dns_responses` and `arp_packets` (`backend/app/pcap.py:141-145`).

The comment above the type says:

```
 * PCAP Analysis types - matching the FastAPI backend Pydantic models exactly.
```

They do not match, and the comment is now wrong in a way that will mislead
whoever trusts it.

`PCAPPanel.tsx` renders `result.summary`, `result.hosts` and
`result.conversations` but never `result.packets` or `result.handshakes`, so
the per-packet ports, TCP flags, DNS names, ARP addresses and the three-way
handshake the parser now extracts are computed, returned over the wire, and
then dropped on the floor.

**Reproduction**: upload a capture containing a TCP handshake and a DNS query
and read the panel. The summary appears; no port, no flag, no handshake and no
DNS name does.

**What should happen**: the frontend type gains the missing fields (and the
`PcapPacketDetail` and `PcapHandshake` types), and the panel renders the
per-packet detail and the handshake. Until then the parser work is invisible.

**Check added**: `TestCaptureFilePanel::test_the_capture_panel_shows_ports_flags_and_a_handshake`
(marked `xfail`).

**Resolution**: fixed. `PcapAnalysisResult` in `frontend/src/types/routing.ts`
now carries `packets` and `handshakes`, with `PcapPacketDetail` and
`PcapHandshake` defined alongside it, and `PCAPPanel.tsx` renders both: a
per-packet disclosure with the ports, flags, DNS name and ARP operation of
each packet, and a card per reconstructed handshake.

The check was still failing after the fix, and the reason was worth finding:
**the test's own PCAP fixture was malformed.** It put the DNS question count
in the flags field, so the message said it had zero questions, and the
backend correctly reported no name. The backend was right and the fixture was
wrong. With the fixture corrected the DNS name is parsed and shown, and the
check passes without being marked `xfail`.

---

### QA-08 — `/network/routes` silently ignores the address family — **High**

- **Endpoint**: `backend/app/main.py:313-335`
- **Owner**: the backend/collector agent.

```python
@app.get("/network/routes", tags=["Network"])
async def get_routes():
    collector = get_network_collector()
    result = await collector.collect_routes()      # <-- no ip_version
```

`collect_routes` already takes and validates the family
(`backend/app/network_collector.py:338-356`), and the analysis endpoint uses
it correctly. Only this endpoint drops it.

**Reproduction**

```bash
curl -s "http://127.0.0.1:5199/network/routes?ip_version=ipv6"
# -> 0.0.0.0/0 192.168.0.1 wlp2s0
#    192.168.0.0/24 None wlp2s0
```

Those are IPv4 routes. The same host's IPv6 table, read by the analysis
endpoint, holds `fe80::/64`. A caller asking for the IPv6 table is given the
IPv4 one and is told nothing about it.

**What should happen**: add `ip_version: str = "ipv4"` to the endpoint and
pass it to `collect_routes(ip_version)`. The collector already returns a
400-shaped error for an unsupported family, so the validation is free.

**Check added**: `TestIPv6Collection::test_the_routes_endpoint_honours_the_address_family`
(marked `xfail`).

**Resolution**: fixed. `backend/app/main.py:427` takes `ip_version: str =
"ipv4"` and passes it to `collect_routes(ip_version=ip_version)`. The check is
no longer marked `xfail` and passes: `ip -j -6 route show` is the command the
backend now runs, and the response carries `"ip_version": "ipv6"`.

---

### QA-09 — The capture limitations understate what the parser does — **Low**

- **Limitation text**: `backend/app/pcap.py:842` — `"VLAN tags (802.1Q) are not parsed"`
- **The code**: `backend/app/pcap.py:1299-1301` — `_parse_ethernet` does
  recognise `0x8100`, reads the inner EtherType and skips the tag.

The limitation is conservative rather than dangerous, but in a teaching tool a
student is told their VLAN-tagged frame will not be understood when in fact
it is. Either the limitation should say the tag is skipped but the inner
protocol is still read, or the code should stop handling it.

**Owner**: the capture/PCAP agent.

**Resolution**: not yet fixed. The wording is still conservative, and still
understates the parser.

---

### QA-10 — A missing metric becomes zero in the teaching model — **Low**

- `backend/app/route_analysis.py:169` — `metric = route.metric if route.metric is not None else 0`
- The observed record keeps `metric = None` (`backend/app/network_collector.py:430`).

The kernel prints no metric when it is zero, so zero is the right value, and
the docstring says so. But the *observed* Routes view shows a blank metric
while the *analysis* shows `0`, so the two views of the same route disagree
on their face. Worth either normalising the observed view or saying in the
limitations that a route the kernel printed without a metric has metric zero.

**Owner**: the route analysis agent.

**Resolution**: not yet fixed. The observed and analysed views still disagree
about a route the kernel printed without a metric.

---

## 3. The four earlier defects, re-checked

| Old finding | State | Evidence |
|--------------|-------|----------|
| `[object Object]` on a failed diagnostic (QA-01) | **Fixed** | `grep -c "model_dump()" backend/app/main.py` → `0`. Every `detail=` is a string now. |
| Route editor unreachable until a packet was sent (QA-04) | **Fixed** | `frontend/src/components/ScenarioJourney.tsx:361` — the editor now sits beside the form, not inside the `{trace && ...}` block. |
| Saving a route showed no confirmation (QA-04) | **Fixed** | `frontend/src/components/RouteEditor.tsx:50,61-66` — a `savingJustNow` ref stops the draft-reload effect from wiping the confirmation. |
| A failed check could read as a success (QA-02) | **Fixed** | The connectivity verdict reads "Unreachable" and the error banner carries a real message. |

Run:

```
ROUTELENS_URL=http://127.0.0.1:5199 ROUTELENS_HEALTH=http://127.0.0.1:8010/health \
  python3 -m pytest tests/test_e2e_browser.py::TestRouteEditor \
           tests/test_e2e_browser.py::TestDnsResolution \
           tests/test_e2e_browser.py::TestTraceroute -v -p no:cacheprovider
```

```
8 passed in 68.02s (0:01:08)
```

**New regression checks added** so these cannot come back quietly:

- `TestErrorContract::test_a_failed_dns_lookup_returns_a_string_detail`
- `TestErrorContract::test_a_failed_connectivity_check_returns_a_string_detail`

These assert on the response the browser actually receives, not on the
rendered text, so they cannot pass by accident.

---

## 4. What the new code gets right

These are worth saying, because they are the parts a reviewer would otherwise
have to hunt for:

- **The provenance split is correct.** `table_provenance` is `observed` and
  `analysis_provenance` is `inferred`, and every per-destination conclusion
  carries `inferred` as well. The distinction the module docstring claims is
  the distinction the code keeps.
- **Unusable routes are reported, not dropped.** `to_teaching_entry` refuses
  to guess at a route with a special next hop, a family mismatch or a missing
  interface, and `routes_skipped` carries the reason. A limitation is added
  when anything was skipped.
- **A missing route is explained, not just reported as missing.** The
  explanation says the main table is the one used for forwarding, and that
  loopback lives in the separate local table.
- **The default route's coverage is computed exactly.** I checked
  `collapse_addresses` against inputs that do not tile, and it never claims
  more space than the routes cover. I had suspected it over-reported; it does
  not, so there is no finding here.
- **The capture parser refuses to guess.** A message it cannot read produces
  a note, never a value. An empty but valid capture is reported as parsed
  with zero packets and the limitation "Empty capture file - no packets to
  analyze", which is honest.
- **The capture panel surfaces the parser's limitations** and shows a parse
  error instead of a summary when the file could not be read.

---

## 5. Checks added

All in `backend/tests/test_e2e_browser.py`, which grew from 48 to 68 tests.

| Class | Checks | Covers |
|-------|--------|--------|
| `TestRouteAnalysis` | 8 | the endpoint answers through the proxy; observed vs inferred; the winner is named and each loser says why; shadowing is reported; "no packet was transmitted" is stated; skipped routes are listed; an IPv6 address is analysed against the IPv6 table; the IPv6 report does not carry the IPv4 limitation |
| `TestRouteAnalysisIsNotShownToTheUser` | 1 | the analysis is reachable from the page (QA-06, **now passing**) |
| `TestCaptureFilePanel` | 4 | an unparseable file says so and shows no summary; a real capture is summarised; the deeper detail is shown (QA-07, **now passing**) |
| `TestIPv6Collection` | 1 | the routes endpoint honours the address family (QA-08, **now passing**) |
| `TestErrorContract` | 2 | a failed diagnostic comes back with a string `detail`, not an object |

The capture checks build a real PCAP in the test — a TCP three-way handshake, a
DNS query for `example.com` and an ARP request — rather than mocking one, so
they exercise the parser end to end.

The new checks locate elements by visible text, by role and by the `id`s that
survive a redesign (`#pcap-file-input`, `#route-editor-node`). They do not
depend on a class name for anything that the visual layer might change.

**After the visual redesign landed**, the checks had to be taught the new
layout: the application became a set of views in a sidebar rather than one
scrolling page, so each check now opens the view it needs, the way a person
would. The checks that assert on wording were checked against the new words
rather than relaxed into "contains something": a verdict rendered in capitals
is matched without regard to case, and everything else is matched exactly.

---

## 6. Recommended order of work

1. ~~**QA-06** — give the route analysis a frontend client and a panel.~~ **Done.**
2. ~~**QA-08** — one parameter on `/network/routes` and one argument at the
   call site.~~ **Done.**
3. ~~**QA-07** — extend `PcapAnalysisResult` and render the per-packet detail
   and the handshake.~~ **Done.**
4. **QA-09, QA-10** — wording corrections. **Still open.**

---

## 7. What I could not check

- **The visual layer.** The frontend is being redesigned at the same time. My
  checks assert on text and behaviour; where I had to find an element I used
  a role, a label or an `id` that is referenced by the component itself. A
  redesign that changes the wording of a button will break a check, and that
  is the correct outcome, but it is worth knowing before the next merge.
- **A capture with a VLAN tag, IPv6 traffic, DNS over TCP or fragments.** The
  parser has specific handling for each; I exercised the main paths only.
- **The virtual router and the packet lab.** The lab namespaces do not exist
  on this machine, so `/api/lab/*` still answers 503 and nothing behind that
  line could be driven in a browser.
- **The report's provenance against the new analysis.** The report builder
  does not know about the route analysis, so a report cannot yet mention it.

---

## 8. Commands

```bash
# Backend (worktree code)
cd backend && /home/abhaysawant/Desktop/cn_project_2/backend/.venv/bin/python \
  -m uvicorn app.main:app --host 127.0.0.1 --port 8010

# Frontend (worktree code)
cd frontend && ROUTELENS_BACKEND_URL=http://127.0.0.1:8010 \
  npm run dev -- --host 127.0.0.1 --port 5199

# Checks
cd backend && ROUTELENS_URL=http://127.0.0.1:5199 \
  ROUTELENS_HEALTH=http://127.0.0.1:8010/health \
  python3 -m pytest tests/test_e2e_browser.py -v -p no:cacheprovider
```

The checks skip cleanly when Playwright or the backend is not available, so an
ordinary `pytest tests/` run is never blocked by them.
