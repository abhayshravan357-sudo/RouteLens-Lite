# RouteLens Lite

RouteLens Lite is a learning tool for computer networks. It answers the
question "which route would the kernel pick for this address, and why?" — and
then lets you change the routes, trace a packet hop by hop, and read the
machine's own network state with the evidence for every claim attached.

Everything it shows is labelled with where it came from: **observed** for
something read out of a running system, **inferred** for a conclusion drawn
from an observation, **simulated** for a path worked out by the routing
engine, and **measured** for something actually sent and received.

## What it is not

It is worth being clear about this, because the name invites the wrong idea.

- **It does not discover physical switches.** It never scans for routers,
  reads LLDP or CDP, or maps the campus. The topology map is built from the
  scenarios you model and from the one machine it runs on.
- **It does not measure the network it is connected to.** The diagnostics tab
  reads *this* machine's interfaces, routing table, neighbour cache and
  resolver. A traceroute run from here describes the path from here. It is
  not a measurement of the network's behaviour under load.
- **A route decision is not a measurement.** When RouteLens says a packet
  would be forwarded via a gateway, that is the routing engine reasoning over
  a table. Nothing was sent. The only thing in this project that can send a
  real packet is the virtual packet lab, and only inside network namespaces
  it creates.

## What it does

- **Routing table analysis with longest-prefix matching** — type an address
  and see which route wins, which candidates it beat, and why each one lost.
- **An editable routing table** — add, change or remove routes and watch the
  lookup answer differently straight away.
- **A packet journey traced hop by hop** through a modelled scenario, with
  each hop's routing decision shown in full.
- **A virtual packet lab** that can send real packets between network
  namespaces and check the capture afterwards. The page drives it: you pick
  a network to build, build the lab, send a test packet and tear it down.
  Every step needs root, and each one says so when it is refused. See
  **Limitations**.
- **Network diagnostics read from the host** — interfaces, routing table,
  neighbour cache, DNS resolution, connectivity checks and traceroute.
- **A capture file importer** that reads a PCAP or PCAPNG and extracts ports,
  TCP flags, three-way handshakes, DNS names, ICMP types and ARP addresses.
- **The machine's own kernel routing table**, read from the kernel rather
  than from a sample, with the analysis of what it would do with an address
  and which route shadows which.
- **An evidence-based topology map** of the scenario and the machine.
- **A learning lab** whose exercises are marked by the routing engine, not by
  a hand-written answer key. Some of them run against the routing table of
  the machine you are sitting at.
- **Authorised host discovery** with a confirmation step and an audit trail of
  what was asked for and what was refused.
- **An exportable report** listing every claim with its source, its time, and
  what could not be established.

## Setup

You need **Python 3.11 or newer** (CI uses 3.12) and **Node.js 18 or newer**
(CI uses 20).

### Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### Frontend

```bash
cd frontend
npm ci
```

`npm ci` installs exactly what `package-lock.json` pins. Use `npm install`
instead if you are changing dependencies on purpose.

### The virtual packet lab (optional)

Everything above works without root. The **virtual lab** is the one feature
that needs it, because it creates real network namespaces:

- **root** (network namespaces need `CAP_SYS_ADMIN`)
- the **`ip`** command from `iproute2`
- the **`ping`** command

Without those, the lab says so, and says which part is missing. Building it
is refused with the reason:

> needs root: network namespaces require CAP_SYS_ADMIN. Run the backend with
> sudo only for lab use.

And the status endpoint names the namespaces it could not find, so the reason
is specific rather than a general "not ready".

Everything else — the routing analysis, the scenario lab, the diagnostics, the
capture importer, the exercises and the report — works without root. Only run
the backend under `sudo` when you actually want the lab.

## Running it

Two processes, in two terminals.

**Backend** (from `backend/`, with the virtual environment activated):

```bash
python -m uvicorn app.main:app --port 8000
```

**Frontend** (from `frontend/`):

```bash
npm run dev
```

Then open **<http://localhost:5173>**.

If 5173 is already taken, Vite quietly moves to the next free port and prints
it — open the URL it shows rather than assuming 5173.

The Vite dev server proxies the API to the backend, so the browser only ever
talks to one origin. The backend also serves its own interactive API docs at
<http://localhost:8000/docs>.

If you need the backend on another port, set `ROUTELENS_BACKEND_URL` when you
start the frontend:

```bash
ROUTELENS_BACKEND_URL=http://127.0.0.1:8010 npm run dev
```

## Testing

**Backend** — the whole suite:

```bash
cd backend
source .venv/bin/activate
python -m pytest -q
```

That run includes the browser checks, which **skip** unless the application
is already running — so on a machine where something else is using port
8000 they will run and the suite will take several minutes instead. To run
just the backend:

```bash
python -m pytest -q --ignore=tests/test_e2e_browser.py
```

The counts move as the work lands, so run the command rather than trusting
a number in this file. When this README was written, the backend suite was
`683 passed, 2 skipped`. Both skips say why: one is a test that needs a
kernel interface this machine does not have, and one needs root to build
network namespaces.

**Frontend** — type check and production build:

```bash
cd frontend
npx tsc --noEmit
npm run build
```

**Browser checks** — these drive a real Chromium against a running backend and
frontend. They need Playwright:

```bash
cd backend
source .venv/bin/activate
pip install playwright
python -m playwright install chromium
```

With the backend on port 8000 and the frontend on port 5173, as above:

```bash
cd backend
ROUTELENS_URL=http://127.0.0.1:5173 \
ROUTELENS_HEALTH=http://127.0.0.1:8000/health \
python -m pytest tests/test_e2e_browser.py -q -p no:cacheprovider
```

When this README was written the browser file was `93 passed`, with no
expected failures. The counts move as the work lands, so run the command
rather than trusting a number in this file.

A check that cannot fail is not a check, so none of these are written as
"skip if the element is missing" — a missing required element is a failure
that says what was missing. The only skips left are for the application not
running at all: if either half is not answering, the whole file is skipped
with a message naming which half is missing, so "the app is not running" can
never be mistaken for "the app is broken".

These checks **skip cleanly** if Playwright is not installed or either half
of the application is not running, so an ordinary `pytest` run is never
blocked by them.

**Everything at once:**

```bash
bash scripts/routelens-check.sh
```

That runs the git whitespace check, the backend suite, the type check and the
build, and writes a report under `.routelens/reports/`. It works in a clone or
in a git worktree.

## How to use it

A sensible first ten minutes:

The application is a set of views down the left-hand side. Only one is open at
a time, so start at the top and work down.

1. **Overview** answers what the app can see and what it cannot.
2. **Routing Analyzer** — enter `192.168.1.50`. Read the explanation: it says
   which prefix won and which one lost, and why. Then edit the table below
   it: add a `203.0.113.0/24` route, look up `203.0.113.9` again and watch
   the answer change. The panel compares the answer before and after your
   edit. This is the same routing engine the exercises use.
3. **Kernel Table** — this one is not a model. It is the routing table the
   machine you are sitting at actually holds, read from the kernel, with the
   analysis of what it would do and which route shadows which.
4. **Packet Journey** — pick *Client → Router → Server* and send a packet.
   Every hop shows the route it picked and the routes it beat.
5. **Learning Lab** — do an exercise. When you get it wrong, the feedback says
   which hop went the wrong way, not just that you were wrong. Three of the
   exercises ask about your own machine's table.
6. **Network Diagnostics** — the interfaces, routes and neighbours of the
   machine you are sitting at, along with DNS, connectivity, traceroute and
   the capture file importer.
7. Finally, build the **report** on the Overview and read its limitations
   section. It tells you what was measured, what was inferred, and what could
   not be established.

## Limitations

The project tries not to claim more than it does, and these are the real ones:

- **The routing decision is inferred, not observed.** It is what the kernel's
  table implies, not a packet that was sent. Only the virtual lab sends real
  packets, and only inside namespaces it creates.
- **The virtual lab needs root, and without it every step is refused.** The
  page can build the lab, send a test packet and tear it down, but each of
  those needs network namespaces and therefore root. Without it the lab says
  it is unavailable, says why, and offers no packet-sending action. Nothing
  in the interface claims a packet was sent.
- **Only the main routing table is read.** The kernel keeps local and
  broadcast routes in separate tables, so an address this host owns may have
  no entry of its own in what you see.
- **The capture panel itemises behind a disclosure.** It parses ports, flags,
  handshakes, DNS names and ARP out of a PCAP, and the panel shows all of it —
  but each packet's facts are collapsed until you open it, so the summary
  looks thinner than the data behind it.
- **The capture importer does not check checksums.** It decodes headers and
  reads ports, flags and names from the bytes; it does not verify that the
  IP or TCP checksum is correct, so a corrupted packet is reported as
  corrupt-looking data rather than as a checksum failure.
- **IPv6 extension headers are not decoded.** An IPv6 packet carrying
  extension headers is read as though the header after the IPv6 one were the
  transport header, so such packets are misread rather than skipped.
- **Fragments, VLAN tags and DNS over TCP are not decoded.** The importer says
  so in its own limitations rather than guessing.
- **The diagnostics are rate limited.** DNS, connectivity and traceroute each
  allow 20 requests a minute; past that they are refused with a 429 and a
  `Retry-After`, and the panel says so.
- **A traceroute that finished is not a traceroute that arrived.** The
  `completed` field means the trace ended, which includes running out of hops
  and the traceroute command simply stopping. There is no separate field
  saying the destination was reached, so you have to read whether the last
  hop is the target yourself.
- **The scenario lab is a model.** Its routes are the ones you gave it, not
  a reading of any real network.
- **Discovery needs authorisation.** It asks for the scope to be confirmed
  and records both confirmations and refusals in an audit trail.

## Further reading

- [`docs/qa-gap-report.md`](docs/qa-gap-report.md) — what the independent
  review found, with severities and the files that should change.
- [`docs/e2e-test-plan.md`](docs/e2e-test-plan.md) — the end-to-end scenarios
  and what each needs.
- [`docs/packet-lab-api-contract.md`](docs/packet-lab-api-contract.md) — the
  contract the virtual lab's API keeps.
- [`docs/real-network-audit.md`](docs/real-network-audit.md) — what was
  actually read from a real machine, and what was not.

## Technology

- **Backend**: Python, FastAPI, pytest
- **Frontend**: React, TypeScript, Vite
- **Browser checks**: Playwright
