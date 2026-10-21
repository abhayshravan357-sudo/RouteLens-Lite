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

**Resolution**: fixed. The limitation now says that a VLAN tag is skipped
and the protocol inside it is still read, which is what the code does. A
check in `backend/tests/test_pcap.py` asserts that the wording does not
understate the parser, so it cannot drift back.

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

**Resolution**: fixed. The collector now records a route the kernel printed
without a metric as metric zero, which is what a missing metric means for
`ip route show`. The observed view and the analysis of the same table no
longer disagree about the same route. A check in
`backend/tests/test_network_collector.py` asserts it.

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
4. ~~**QA-09, QA-10** — wording corrections.~~ **Done.**

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

---

## 9. Findings from the repair milestone

These are from the second pass, after the routing, frontend and capture work
had been integrated. They are numbered from QA-11 so they do not collide with
the findings above.

### QA-11 — The report's first limitation was false about its own contents — **High** (fixed here)

- **Was**: `backend/app/report.py:30-31`

  > "Only the routing table shown here is simulated. It is a teaching
  > example, not this machine's real table."

  Six of the twelve evidence items were `simulated`, across **two** sections
  ("The teaching routing table" and "Simulated networks"). "Only" was false
  and "the routing table" understated it.

- **Now**: the limitation names both modelled parts, says that everything
  else was read from the machine, and points at the per-item provenance and
  the section titles. A reader can tell from the limitations alone which
  parts are measured and which are modelled.

- **Fixed in**: `backend/app/report.py` (LIMITATIONS[0]).

### QA-12 — The report showed only the IPv4 routing table — **High** (fixed here)

- **Was**: `backend/app/report.py:186` and `:226` called `collect_routes()` and
  `collect_neighbors()` with the default `ip_version="ipv4"`. This machine's
  IPv6 route (`fe80::/64`) was absent from the export, and nothing said the
  table was IPv4 only, so a reader would conclude the machine has no IPv6
  routes.

- **Now**: both families are collected and reported, and every network
  evidence item carries a `family` field, rendered as `- **Family:** ipv6`
  in the Markdown. The report panel renders the Markdown, so no frontend
  change was needed.

- One detail worth keeping: a table that was **read successfully and is
  empty** is now reported as "no neighbours in this cache" with
  `provenance: observed`, not as "not collected" with `provenance: unknown`.
  This machine has an empty IPv6 neighbour cache, and the old wording told
  the reader the collection had failed.

- **Fixed in**: `backend/app/report.py`, with tests in
  `backend/tests/test_report.py`.

### QA-13 — Building a report threw away the names it had resolved — **Medium** (fixed here)

- **Was**: `backend/app/report.py:226` called `collect_neighbors()` with the
  default `resolve_names=True`, so every report build performed reverse DNS
  queries and then discarded the answers. The evidence dict had no hostname.

- **Now**: the name is kept, together with `name_provenance` and
  `name_error`, so a reader can see that the address is observed and the
  name is inferred. A limitation says so.

- **Fixed in**: `backend/app/report.py`.

### QA-14 — A test in the suite sent real ICMP probes at the network — **Medium** (fixed here)

- **Was**: `backend/tests/test_discovery_api.py::test_running_with_a_matching_confirmation_is_allowed`
  ran a real discovery against `192.168.193.0/29`, emitting up to three
  probes per address, one second each — about 19 seconds of real traffic.

- **Now**: the probe is mocked, so the test exercises the confirmation gate
  without touching the network. It runs in 1.4 seconds instead of 19. The
  probe itself is still covered, by the clearly-labelled
  `TestProbeSafety::test_the_probe_passes_the_address_after_a_double_dash`
  in `backend/tests/test_discovery.py`, which mocks the subprocess.

- **Fixed in**: `backend/tests/test_discovery_api.py`.

### QA-15 — The API contract checker cannot see inside a response — **Medium** (reported, not fixed)

- `frontend/scripts/check-api-contract.mjs:159-178` compares the field
  **names** of a schema against a hand-maintained list and stops there. It
  never looks inside a nested object, and it does not compare nullability,
  required-versus-optional, or the shape of an error response.

  Four backend fields are free-form dictionaries where the frontend expects
  a typed object:

  | Backend field | Frontend type | Frontend reads |
  |---------------|---------------|----------------|
  | `LabStatusResponse.router_info` | `RouterInfo` | `VirtualLabPanel.tsx:156` `info?.interfaces.length`, `:201` `info.routing_table.length` |
  | `CompareResult.simulated` | `ScenarioTrace` | `ComparePanel.tsx:90-95` `.status`, `.hops.map(...)` |
  | `CompareResult.lab` | `LabProbeResult` | `ComparePanel.tsx:48,129-132` `.status`, `.reason` |
  | `DiscoveryResponse.scope` | `DiscoveryScope` | `DiscoveryPanel.tsx:224-226` `.network`, `.host_count` |

  The shapes agree at runtime today — the backend builds exactly the keys
  the frontend reads (`backend/app/packet_lab.py:151-156`) — but nothing
  keeps them agreeing. A backend edit that dropped a key would crash the
  panel on a length of `undefined` rather than show a message.

  `CompareResult` and `DiscoveryResponse` are **not in the checker's list at
  all**, so even their top-level fields can drift unnoticed.

  The checker works around the first case by listing `RouterInfo` and
  `RouterRouteEntry` in `FRONTEND_ONLY_OK` (line 112), which means it does
  not even require them to exist in the backend.

  **Not fixed here**: the backend owns those schemas and the frontend stream
  owns the checker. Two checks in `backend/tests/test_e2e_browser.py` record
  the gap as `xfail` so it cannot be forgotten.

### QA-16 — The page cannot drive the virtual lab — **High** (reported, not fixed)

`frontend/src/api/routing.ts` has `simulatePacket` (line 314),
`applyScenarioLab` (line 489) and `teardownScenarioLab` (line 500), but **no
component imports any of them**. The interface can read the lab's status and
the comparison view asks the lab to run a scenario, but there are no
controls to set the lab up, send a packet, or tear it down.

This is what the lab lifecycle work is for. Until it lands, the README must
not say the lab "sends real packets between network namespaces" as though a
student could do that from the page. The README now says the backend can and
the page cannot yet.

### QA-17 — A test in the suite sent real packets from the discovery test — covered by QA-14

Folded into QA-14 to keep the list short.

### QA-18 — The capture parser does not verify checksums, and does not decode IPv6 extension headers — **Medium** (documented, not fixed)

Neither is mentioned in the parser's own limitations list
(`backend/app/pcap.py:836-846`). A packet with a bad IP or TCP checksum is
reported as ordinary decoded data, and an IPv6 packet carrying extension
headers is read as though the header after the IPv6 one were the transport
header. Both are now stated in the README's limitations; the parser's own
list should say them too. The parser is the capture stream's.

### QA-19 — `pcap_routes.py` says PCAPNG is not parsed, and it is — **Low** (reported, not fixed)

- **Was**: `backend/app/pcap_routes.py:158` — "PCAPNG (detected but not parsed)".
- **Is**: `backend/app/pcap.py:469` implements `_parse_pcapng`, with the block
  types at lines 253-256. PCAPNG is parsed.

The docstring is stale. The file is the capture stream's.

### QA-20 — A traceroute that finished is not one that arrived — **Low** (documented)

`backend/app/network_collector.py:1270-1278` sets `completed = True` when the
last hop is the target, when the hop limit was reached, **and** when the
traceroute command stopped for other reasons. There is no separate field
saying the destination was reached, so a reader has to compare the last hop
with the target themselves. The README now says so. A `reached_destination`
field would be better; the collector owns that.

### QA-21 — The diagnostic rate limit is per endpoint, and the README implied it was shared — **Low** (fixed here)

`backend/app/security.py:129` sets one limiter with 20 requests per 60
seconds, and the endpoints use separate keys (`main.py:644` "dns", `:761`
"connectivity", `:864` "traceroute"), so each has its own budget rather than
sharing one. The README now says "each allow 20 requests a minute".
