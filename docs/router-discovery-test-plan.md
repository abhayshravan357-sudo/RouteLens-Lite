# Router discovery — test plan

**Status**: written before the module exists. Every case below is written from
the contract, not from an implementation, so that it is a real check rather
than a restatement of the code.

**Module under test**: `backend/app/router_discovery/`
**API prefix**: `/api/router-discovery/`

**This is not `backend/app/discovery.py`.** That module is the authorised ICMP
host sweep: it pings a bounded set of addresses and records confirmations and
refusals in an audit trail. The new module is about *routers* — finding them,
learning what each one is connected to, and reading the routing table each one
holds. The two must not be confused, and the sweep must not be broken by the
new work.

**Three compatibility decisions are not yet on the board.** The cases that
depend on them are marked **[contract-pending]** below, with the question that
has to be answered before they can be written.

---

## 1. The model layer

These are the values the whole feature is built from. If they are wrong,
everything above them is wrong too, and the errors are hard to see.

### 1.1 `RouteEntry`

A single route as one router reports it.

**Must guarantee**
- The destination is a **prefix**, not a host address: `10.0.0.0/8`, never
  `10.0.0.1`.
- The prefix is canonical: `10.0.0.0/8` and `10.0.0.0/8` are the same route
  and must compare equal, and a non-canonical spelling must be rejected or
  normalised, not stored as a second, different route.
- A next hop is either an address, or absent (a directly connected route),
  or a word such as `blackhole`/`unreachable`. Those three cases are
  different and must not be collapsed into one.
- The interface name is a name, not a path and not a full command line.
- The metric is a non-negative integer, and a route with no metric is
  distinguishable from a route with metric zero.
- The provenance is one of a fixed set, and a route read from a router is
  **observed** — it was reported, not inferred.

**Malformed input must produce**
- A single, named validation error naming the offending field, not a
  `KeyError`, `TypeError` or a bare `ValueError` from deep inside
  `ipaddress`.
- No partially built object: a failed construction must not leave an object
  with a valid prefix and a missing next hop.

**Cases**
| # | Input | Expected |
|---|-------|----------|
| M1 | `10.0.0.0/8` | accepted, prefix canonical |
| M2 | `10.0.0.1/8` | normalised to `10.0.0.0/8`, or rejected — never stored as-is |
| M3 | `10.0.0.1` (host, no mask) | rejected, error names the destination |
| M4 | `10.0.0.0/33` | rejected, error names the mask |
| M5 | `10.0.0.0/-1` | rejected |
| M6 | `10.0.0.0/8` with next hop `192.168.1.1` | accepted |
| M7 | same with next hop `None` | accepted, and distinct from a next hop of `0.0.0.0` |
| M8 | same with next hop `blackhole` | accepted, distinct from case M7 |
| M9 | metric `-1` | rejected |
| M10 | metric absent | accepted, and distinguishable from metric `0` |
| M11 | interface `""` | rejected |
| M12 | a provenance outside the fixed set | rejected |
| M13 | a `RouteEntry` built with a non-string destination | a validation error, not a `TypeError` |

### 1.2 `IfaceInfo`

One interface on one device.

**Must guarantee**
- A name, an index, an address and a prefix length, and a flag for whether
  the interface is up.
- The address and the prefix belong together: an address with no prefix is
  incomplete and must be rejected, because a half-known interface is
  dangerous — it will be drawn as if it were complete.
- A link-local IPv6 address is not a usable neighbour address and must be
  distinguishable from a routable one.

**Cases**: M14 `address` without `prefixlen` → rejected. M15 link-local
address → present, and flagged. M16 index negative → rejected.

### 1.3 `Neighbor`

A neighbour as one device reports it.

**Must guarantee**
- An address, a link-layer address, and a state.
- The **link-layer address** and the **network-layer address** are different
  things and must not be swapped. A neighbour with a MAC but no IP, or an IP
  but no MAC, is possible and must be representable without lying.
- The protocol that produced it is recorded: `lldp`, `cdp`, `arp` or
  `manual`. This is what decides whether the edge is observed or inferred.
- An ARP neighbour is a *neighbour on a link*, not a router that answered.

**Cases**: M17 an ARP neighbour with a MAC and no IP → accepted, protocol
`arp`. M18 an LLDP neighbour with both → accepted, protocol `lldp`.

### 1.4 `DeviceSnapshot`

Everything known about one device at one moment.

**Must guarantee**
- **Identity is by hostname, not by address.** A device reached at two
  addresses is one device. This is the single most important rule in the
  model, and it is what stops the engine from collecting the same router
  twice.
- The identity key is stable across address changes: the same router with
  a different management address is still the same device.
- If no hostname is known, the device still needs an identity — an address
  is a fallback, but it must be marked as a fallback so that two devices
  with the same hostname are not merged by accident.
- The collection time is recorded, so a reader can tell how old a reading is.
- Partial collection is representable: a device whose interfaces were read
  but whose routes failed must say so, rather than looking like a device
  with no routes.

**Cases**: M19 two snapshots with the same hostname but different addresses →
same device identity. M20 two snapshots with different hostnames but the
same address → **different** devices. M21 a snapshot with an empty route
list and a failed route collection → distinguishable.

### 1.5 `Edge`

A link between two devices.

**Must guarantee**
- It has a source, a target, and a **provenance**.
- The provenance is the whole point: an edge is **observed** when a
  management protocol reported it (LLDP or CDP), and **inferred** when it
  was derived — from a next hop, from a shared subnet, or from the routing
  table's own contents.
- A next-hop edge is never observed. A router's routing table says "to reach
  X, send it to gateway G". That is a *claim by the router about a third
  party*, not an observation of a link between G and X. Drawing it as an
  observed link would be claiming to have seen something nobody saw.
- An inferred edge names **what it was inferred from**, so a reader can
  check the reasoning.

**Cases**: M22 an edge from an LLDP report → provenance `observed`. M23 an
edge from a next hop → provenance `inferred`, with the basis recorded. M24
an edge with an unknown provenance → rejected.

---

## 2. The read-only guard

The feature reads a network's management plane. It must never be able to
change anything, and it must never be talked into running a command the
operator did not ask for.

### 2.1 What must be refused

Any command that is not on the allowlist. In particular:

- **writes** — `ip route add`, `ip route del`, `commit`, `configure
  terminal`, `set`, `delete`, `no `, `write memory`, `copy running-config
  startup-config`, `reload`, `reboot`, `shutdown`, `erase`, `format`;
- **anything not on the allowlist at all**, even if it is harmless;
- **a shell metacharacter** — `;`, `&&`, `||`, `|`, `` ` ``, `$(`, `>`,
  `<`, `&`, newline;
- **an argument that is itself a command** — `--`, a leading `-`, a path
  that escapes the expected directory.

### 2.2 What must be allowed

Only the read-only commands the feature needs, which is expected to be
along the lines of:

- `ip route show` (and `ip -j route show` for machine-readable output)
- `ip -6 route show`
- `ip neigh show` / `ip -j neigh show`
- `ip link show`
- `ip addr show`
- `lldpcli show neighbors -f json`
- `cisco-discovery-protocol` / `cdp` neighbour listings
- `snmpwalk` against a router's routing table OID
- `vtysh -c "show ip route"` and `show ipv6 route` against FRR
- `show ip route` / `show ip route vrf all` against a vendor CLI
- `netconf`/`ssh` **only** with an explicit, already-configured credential
  reference — never a credential in the request

### 2.3 The interesting cases

These are the ones a naive allowlist gets wrong, and they are the reason the
guard is worth testing.

| # | Input | Why it matters |
|---|-------|----------------|
| G1 | `ip route show; rm -rf /` | starts with an allowed prefix, carries a shell metacharacter |
| G2 | `ip route show\nrm -rf /` | carries a newline — many "strip whitespace" checks miss a trailing newline, and `sh -c` does not |
| G3 | `ip route show && curl http://elsewhere` | a second command |
| G4 | `ip route show$(whoami)` | command substitution |
| G5 | ``ip route show `id` `` | backtick substitution |
| G6 | `ip route show > /etc/passwd` | a redirect |
| G7 | `ip route show \| tee /tmp/x` | a pipe |
| G8 | `ip route add 10.0.0.0/8 via 1.2.3.4` | a write |
| G9 | `commit` | a write on a vendor CLI |
| G10 | `ip route show` with an argument containing `;` | the *argument* carries the metacharacter, not the command |
| G11 | `ip route show\n` (trailing newline only) | a trailing newline must not turn a good command into a bad one — and must not be silently trimmed into one that was not |
| G12 | `ip route show` | allowed |
| G13 | `ip -j route show` | allowed |
| G14 | `lldpcli show neighbors -f json` | allowed |
| G15 | an empty command | refused, not an empty execution |
| G16 | a command that is only whitespace | refused |

### 2.4 The refusal must be a refusal

This is the property that is easy to lose and hard to notice.

- A refused command must **raise a named error**, and must never reach the
  process runner. The test must be able to assert that the runner was
  **not called at all** — not that it was called and its result was
  ignored. A silent no-op is the failure mode that matters, because it lets
  a caller believe the command ran.
- The error must name the command and the reason.
- A refusal must not be catchable-and-ignorable by accident: it must not
  be a subclass of something the collector treats as "command failed, carry
  on", or the refusal becomes a silently skipped device.
- A refused command must not appear in any output, log, or audit trail as
  though it had been attempted.

---

## 3. The engine

### 3.1 Traversal order

- The engine is a **breadth-first search** from the seed devices. A device
  at distance 1 is collected before a device at distance 2, and a device at
  distance 2 before a device at distance 3.
- The BFS must be **deterministic**: the same input must produce the same
  collection order, every time. If two devices are at the same depth, they
  are collected in a stable order — by identity, not by dictionary
  iteration order, which is not stable across runs.
- The result must be reproducible for a test to be able to assert on it.

### 3.2 Device identity

- Identity is by **hostname**, not by address. A device reached at
  `192.168.1.1` and `10.0.0.1` with the same hostname is **one** device.
- The second address of a known device is **not contacted again**. It is
  recorded as another address of the device already collected.
- Two different hostnames at the same address are two devices.
- The engine must not collect a device twice, and must not report it twice
  in the result.

### 3.3 The scope allowlist

The allowlist is the boundary that decides what the feature is allowed to
touch. It must be enforced in **two** places, and the second is the one
that gets forgotten:

1. **Before every collection.** A device outside the allowlist is never
   contacted — no command is run against it.
2. **Before every enqueue.** A neighbour discovered *inside* the allowed
   scope may point *outside* it. The engine must check the allowlist again
   when it decides to queue that neighbour, not only when it collected it.
   Without the second check, one hop out of scope is enough to walk the
   whole internet.

The test must assert that the runner was **never called** with a
disallowed target — counting calls, not checking the output.

### 3.4 ARP neighbours are not auto-queued

- An ARP neighbour says "something is on this link". It does not say the
  thing is a router, and it does not say it has a management plane.
- An ARP neighbour may be **recorded** as a neighbour of the device, but it
  must **not** be queued for collection on its own.
- Only neighbours that came from a management protocol (LLDP, CDP) or that
  were named in the scope may be collected.
- The consequence to test: a device whose only inbound neighbour is an ARP
  neighbour contributes exactly one device to the result, not two.

### 3.5 Bounds

- `max_depth` is honoured: no device beyond that depth is collected.
- `max_devices` is honoured: the run stops at that many devices.
- Both are hard limits, not warnings. A run that would exceed them stops.
- The limit that stopped the run is recorded in the result, so a reader can
  tell a small result from a truncated one.

### 3.6 Failure handling

- A collector that **fails** (the command returns non-zero, times out, or
  the tool is missing) is recorded as a failure **with its reason** — the
  device, the command, and why it failed.
- The run **continues**. One unreachable router must not end the run.
- The failed device is not silently dropped: it appears in the result as a
  failure, and it does **not** appear as a successfully collected device.
- A failure must not be reported as an empty result. "This router's routing
  table could not be read" and "this router has no routes" are different
  and must be distinguishable.

---

## 4. The graph

- An edge is **observed** when a management protocol reported it: LLDP, CDP,
  or SNMP-adjacency.
- An edge is **inferred** when it was derived: from a next hop, from a
  shared subnet, from a route's interface and next-hop pair.
- A **next-hop edge is never observed.** A routing table says "to reach X,
  send it to G". That is the router's claim about a third party, not an
  observation of a link between G and X. Two independent routers naming the
  same next hop is stronger evidence, and that strength is what the
  provenance field is for.
- An inferred edge records **what it was inferred from**, so a reader can
  check the reasoning rather than take it on trust.
- The graph must not contain an edge the backend did not report. Every edge
  on the graph traces back to a specific piece of evidence.

---

## 5. The API

### 5.1 What a run says

- A run has a **status** that says what happened: it finished, it is still
  going, it failed, or it stopped because a limit was reached.
- A run's status must distinguish **finished** from **finished early** — a
  run that stopped at `max_devices` did not complete the exploration, and
  saying "complete" would be a lie about coverage.
- Progress is visible: which devices have been collected, which are in
  flight, which failed.
- Failures are visible, with their reasons, to whoever started the run.

### 5.2 What a refusal says

- A refused request — a command outside the allowlist, a scope outside the
  allowlist, a credential in the request — is refused with a status and a
  message that says **what was refused and why**.
- A refusal is not an empty result. The difference between "nothing was
  found" and "you asked for something that was not allowed" is the
  difference between a true negative and a false one.

### 5.3 Scope is validated before anything is contacted

- A malformed or out-of-policy scope is rejected **before** any command
  runs, any device is contacted, or any state is created.
- The test must be able to assert that the runner was **never called**.

### 5.4 Credentials

- A request must **never** carry a credential — no password, no private
  key, no SNMP community string, no token, in any field, in any header, or
  in a URL query string.
- A response must **never** return one.
- A **log** must never contain one. The log check matters as much as the
  response check: a credential that is not returned can still be written to
  a log file, which is worse, because the log outlives the request.
- A credential, if the design needs one at all, comes from the server's own
  configuration and is referenced by name.

### 5.5 Run isolation

- A run's progress and failures are visible to the client that started it.
- They are **not** readable by another client. A second client must not be
  able to fetch another client's run, its devices, its failures, or
  anything that might carry a credential from it.
- This is the same property the ICMP sweep has, and the new module must not
  be weaker.

**[contract-pending]** — the exact isolation mechanism (a per-run token, or
per-process state) is one of the three decisions.

---

## 6. The analysis

Each finding must state what would have to be true for it to be raised, so
that a finding is a claim with its conditions attached rather than a
verdict. At minimum:

| Finding | Raised when |
|---------|-------------|
| A device appears to forward between two subnets | the same device is observed with interfaces in both subnets, and it is a router (not a host) |
| A subnet is reachable through more than one path | two distinct next hops are observed for the same prefix, from the same device |
| A next hop cannot be resolved | a route names a next hop that no collected device claims, and the next hop is not within a directly connected prefix |
| A default route exists alongside specific routes | the routing table contains `0.0.0.0/0` or `::/0` |
| A device is reachable by more than one address | two addresses resolve to the same hostname, and the addresses are in different subnets |
| A metric conflict exists | two routes to the same prefix differ only in metric |
| A routing table was not fully read | the collection for that device was partial or failed |

Rules for every finding:
- It names the device(s) and the evidence it rests on.
- It is **not** raised when the evidence is missing — absence of a reading
  is not evidence of absence of a problem.
- It does not state a cause it cannot support. "These two subnets are
  reachable through the same device" is supportable. "This is a
  misconfiguration" is not, unless the analysis can say what the correct
  configuration would be.
- It carries a severity that reflects the evidence, and never claims to be
  measured when it is inferred.

---

## 7. The browser

The new view has to be honest about five different situations, and the
browser checks are the only place that is proved.

| Situation | What the view must show |
|-----------|-------------------------|
| **No run yet** | that no run has been made, and how to start one — not an empty graph that looks like a network with nothing in it |
| **A run in progress** | that it is running, which devices have been collected so far, and that the picture is incomplete |
| **A run that failed** | that it failed, and why — not an empty result presented as a finding |
| **A device that failed to collect** | the device, and the reason it failed, marked as failed and distinguished from a device with nothing on it |
| **The backend is not reachable** | that the backend could not be reached — not an empty graph, and not a crash |

Rules for the browser checks:
- The view **never** shows a device, a link or a finding the backend did not
  report. The test must feed a known set through the API and assert the
  view shows exactly that set — no more.
- The view **never** says a packet was sent. This feature is a
  management-plane read; nothing is sent to any device except the read
  commands themselves.
- The view **distinguishes an observed edge from an inferred one**, and the
  distinction is visible in the text, not only in a colour or a shape.
- A missing **application** skips with a reason; a missing **feature**
  fails.

---

## 8. What cannot be tested on this machine

Named, with what would be needed.

| Not available | What it blocks | What is needed |
|---|---|---|
| **No router** | the whole feature end to end | a lab router: a containerlab topology, a GNS3/EVE-NG node, a Cisco CML container, or a real device |
| **No FRR** | reading a real routing table through `vtysh` | FRR in a container, or a FRR image for containerlab |
| **No containerlab / docker** | the standard way to build a lab topology | a Docker daemon, the containerlab package, and a topology file |
| **No root** | creating network namespaces to build a lab in | root, or a user namespace with `ip netns` permitted |
| **No SNMP server** | reading a routing table over SNMP | an SNMP agent, e.g. `snmpd` in a container, with the routing-table MIB |
| **No LLDP/CDP speaker** | observing edges from a management protocol | `lldpd` in a container, or a switch emulator |
| **No second management address** | the identity-by-hostname rule in anger | a router with two addresses, or a fake collector that reports one |

**None of these block the contract tests.** Every case in sections 1 to 6
is written against a **fake collector and a fake runner**: no network, no
docker, no root, no privilege. That is deliberate — the contract tests
should be the fast, always-green ones, and they should be able to assert the
things that are hard to see in a real lab: that a command was never run, that
a refusal was a refusal, that a device was collected once.

**What the fake runner must provide**
- It records every command it was asked to run, in order.
- It returns a scripted result per command.
- It can be told to fail, to time out, or to hang.
- It never runs anything.

Because the runner records what it was asked to do, the "was never called"
assertions in sections 2.4, 3.3 and 5.3 are checkable: the test asserts the
record is empty, not that the output looks right.

**What the fake collector must provide**
- It returns scripted snapshots per device.
- It can raise, to simulate a collection failure.
- It can return a device with the same hostname at two addresses, to
  exercise the identity rule.
- It can return an LLDP neighbour, a CDP neighbour and an ARP neighbour, so
  the observed/inferred distinction and the ARP rule can both be tested.

---

## 9. Where the tests will live

| Area | File | Notes |
|------|------|-------|
| The whole contract | `backend/tests/test_router_discovery_contract.py` | independent, written from this plan, using fakes only |
| The new view | `backend/tests/test_e2e_browser.py` | added to the existing file, using the existing `app_available` fixture |
| The ICMP sweep | `backend/tests/test_discovery_api.py` and `test_discovery.py` | **untouched** — the new module must not break them, and the existing suite is the regression check |
