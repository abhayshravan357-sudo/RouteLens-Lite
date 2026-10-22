# RouteLens — Autonomous Run Log

**Branch**: `integration/baseline-2026-10-20`  
**Tag**: `baseline-verified-2026-10-20` (`86c57ff`)  
**Last Updated**: 2026-10-20

---

## Run Summary

| Metric | Value |
|---|---|
| Backend tests | **356 passed, 2 skipped** |
| Browser tests | **48 passed** (real Chromium) |
| Frontend build | ✅ passes |
| TypeScript | ✅ clean |
| `git diff --check` | ✅ clean |
| API endpoints | 33 |
| Commits this run | 20 |

---

## What the five agents did

Each agent worked in its own worktree on its own branch, cut from the
integration branch. Changes were merged one at a time, with the backend
tests and the frontend build run after each merge.

| Agent | Branch | Outcome |
|---|---|---|
| RouteCore | `feature/routing-table-api` | Editable, authoritative routing table |
| PacketLab | `feature/lab-verification` | Lab command sequence verified, lab hardened |
| Autonomous Eng | `feature/pcap-backend` | PCAP importer backend |
| JourneyUI | `feature/pcap-ui` | PCAP panel, interactive topology graph |
| TestPilot | `feature/browser-e2e-expansion` | 48 browser checks (22 → 48) |

### RouteCore — editable routing table
- `GET /routes` returns the live table; `GET /lookup` uses it
- `POST /routes`, `PUT /routes/{index}`, `DELETE /routes/{index}`, `POST /routes/reset`
- `GET /routes/summary` — counts, longest prefix, lowest metric
- Guarded by a lock; a bulk replace is atomic
- **Verified**: adding a `/32` changed the lookup from `192.168.1.0/25` to
  `192.168.1.50/32`; reset put it back

### PacketLab — lab verification
- The command sequence was verified command by command for all five
  scenarios and written up in `docs/lab-command-audit.md`
- A failing command now reports its index and its stderr
- Teardown is idempotent; a missing namespace is not an error
- The probe distinguishes timeout, missing binary, permission failure and
  unreachable host
- A route whose next hop is off the outgoing network is rejected when the
  commands are built, rather than failing halfway and leaving namespaces
  behind
- Temporary veth names carry the namespace prefix

### Autonomous Engineering — PCAP importer
- Classic PCAP parsed with the standard library only, in memory
- The file is never written to disk
- PCAPNG detected and reported as unsupported rather than mis-parsed
- **A byte-order bug was found during integration and fixed** — see below

### JourneyUI — PCAP panel and topology map
- The file is read and encoded in the browser and sent only to this app's
  own backend; a file over 32 MB is refused before it is encoded
- The result shows the summary, hosts, conversations **and the limitations**
- The topology is a real SVG graph, not a list: observed, inferred,
  simulated and unknown are visually distinct, clickable, and keyboard
  reachable
- A node with no relationships says it has no evidence of connection.
  Nothing is invented to fill a gap

### TestPilot — browser coverage
- 26 new browser checks covering route lookup, DNS, connectivity,
  traceroute, discovery authorisation, the route editor, the learning lab
  verdict, and honest reporting
- The wider coverage found four real defects — see below

### Fixes
- `/packet-journey` was missing from the Vite proxy, so the older Packet
  Journey UI could not reach the backend in development. Fixed.
- `network_collector.py` defined `class NetworkCollector` twice. The second
  definition shadowed the first, so 708 lines of the earlier class were dead
  code that no caller could ever reach, and `_check_tool`/`check_tools` were
  defined twice inside the live class. Removed the shadowed class and the
  duplicate method copies: 1846 → 1109 lines, deletions only, behaviour
  unchanged (307 passed, 2 skipped).
- `main.py` carried a stray `@app.get("/routes")` decorator with no function
  under it, so it attached to the next function and registered
  `get_interfaces` at `/routes` as well. `/routes` still returned routes at
  runtime, but the OpenAPI schema documented it as "Get Interfaces" with the
  wrong response schema. Fixed, and `tests/test_api_integrity.py` now fails
  if a path is ever registered twice or drifts from its documented operation.
- `routing.py` defined `RouteLookupResult` twice (byte-identical); the second
  shadowed the first. `frontend/src/types/routing.ts` declared the three
  traceroute interfaces 2–3 times each — TypeScript merges duplicate
  interfaces, so this was silently type-widening rather than a compile error.
  Both de-duplicated.

### Research: DNS, Traceroute & Connectivity (RQ-001, RQ-002, RQ-006)
- `docs/research/detailed-research.md` now holds the evidence for all three
  questions; `docs/research-index.md` carries the summary tables and the
  RD-006/007/008/009 decision records.
- The headline finding for RQ-006: `/usr/bin/ping` ships `cap_net_raw=ep`, so
  the `ping` subprocess runs ICMP **unprivileged**. Every Python raw-socket
  alternative (`aioping`, `asyncping3`, `aio_ping`) was installed and tried
  and failed with `PermissionError: [Errno 13]`. This is why the existing
  TASK-402 implementation is the right shape.
- The in-process unprivileged alternative — the ICMP *dgram* socket — needs the
  user's GID inside `net.ipv4.ping_group_range`; on this host that range is
  `1 0`, i.e. empty, so the socket is refused.

### TASK-903: Overview Dashboard ✅ `af1c420`
- Answers the five questions a student would otherwise hunt for
- Real machine facts, real neighbour counts, real last-outcome
- 4 browser checks

### TASK-904: Exportable Report ✅ `b3b8b33`
- Every claim records value, provenance, source and collection time
- Limitations are part of the report, not an afterthought
- Markdown for a file, JSON for processing
- 8 backend tests, 3 browser checks

### Browser-level tests ✅ `5801636`
- 22 checks drive a real Chromium against the running app
- Found two faults the API tests could not see: invalid DOM nesting in
  Visualization.tsx, and a missing Vite proxy entry
- Skip cleanly when Playwright is unavailable

---

## Defects found and fixed

| # | Defect | Severity | Who found it |
|---|---|---|---|
| 1 | Diagnostic errors rendered as `[object Object]` | High | TestPilot |
| 2 | A missing `traceroute` tool reported as a packet lab outage | Medium | TestPilot |
| 3 | The route editor unreachable until a packet was sent; saving appeared to do nothing | Medium | TestPilot |
| 4 | The capture parser swapped the byte order of every real file | High | Integration review |

**On defect 4**: the agent's own tests built a file with big-endian magic
bytes and a little-endian body — a file no tool produces — so its tests
agreed with its code while every real capture failed. The tests now build
genuine files in each byte order, and there are new tests for real
little-endian, real big-endian and nanosecond-resolution files.

**On the agent's own report**: the PacketLab agent reported that the lab's
route commands would fail because `10.0.0.1/24` and `10.0.0.2/24` are
"different networks". They are both in `10.0.0.0/24`. Its *code* was right
and its *report* was wrong. It was checked before acting on, sent back with
the correction, and the audit now says all commands are OK.

---

## Verified user journey

Every item below was exercised against the running application, through
the Vite proxy.

```
routing analysis   → 192.168.1.0/25 via 10.0.0.2 dev eth1
editable table     → after edit: 172.16.0.0/12 ; reset ok
scenario journey   → delivered in 4 hops
learning lab       → complete=True route=10.0.1.0/24
diagnostics        → 2 interfaces ; 1 dns address
capture import     → parsed=True packets=3 hosts=2
report             → 180 lines, with sources and limitations
discovery guard    → no confirmation -> HTTP 403
browser rendering  → 48 checks, zero console errors
```

---

## What was not verified

| Thing | Why |
|---|---|
| The packet lab against real namespaces | Needs root and namespace creation, not authorised here |
| Traceroute against a real path | The `traceroute` command is not installed on this machine |
| A browser check of the capture file picker | The file chooser cannot be driven without a real dialog |
| Persistence of routing-table edits | Not implemented; a restart loses them |
| A screen reader pass | ARIA labels and keyboard support are in place, but no screen reader was used |

---

## Documentation

| Document | Covers |
|---|---|
| `docs/manager-status.md` | Current verified state |
| `docs/task-ledger.md` | Every task, with decisions and evidence |
| `docs/real-network-audit.md` | What the tool can and cannot see |
| `docs/integration-log.md` | Integration history |
| `docs/qa-gap-report.md` | The four defects, what was checked, what was not |
| `docs/lab-command-audit.md` | The lab's command sequence, verified |
| `docs/e2e-test-plan.md` | How to exercise the application by hand |
| `docs/research/detailed-research.md` | DNS, traceroute and connectivity research |

---

## Checkpoint

**Resume point**: `integration/baseline-2026-10-20` @ `fdb609d`, working tree clean.

**State**: The application is complete and verified. Routing analysis,
editable routing tables, hop-by-hop packet journeys, a learning lab
driven by the real engine, network diagnostics, capture file import, an
evidence-based topology map, authorised host discovery, and an exportable
report are all working and tested.

**Next action**: The operator's decisions —
1. merge this branch into `main`
2. authorise one privileged lab run (`sudo ip netns`) to exercise the
   packet lab for real
3. decide whether the packet lab's three stale agent branches are worth
   keeping