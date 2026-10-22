# Router discovery

> **Status: skeleton.** This feature is under construction. The sections below
> describe the design and the safety rules it will keep. Where a behaviour has
> not been implemented and verified yet, this document says so rather than
> describing it as if it works. Nothing here should be read as a promise that
> the feature is ready to use.

Route discovery finds the routers reachable from this machine, learns what
each one is connected to, reads the routing table each one holds, and reports
what it finds with the evidence attached.

It is **not** the same as the host sweep in the Network Diagnostics tab. That
one pings a bounded range of addresses and reports which answered. This one
talks to routers' **management planes** — the administrative interface a
router exposes to a network operator — and reads what those routers know.

---

## The management-plane reality

This is the part that surprises people, so it goes first.

**You cannot get a router's routing table by sending it a packet.** There is
no packet you can send a router that will make it reply with its routing
table. A router's forwarding table is not a thing it publishes to the
network. It is the router's own internal state, and the only ways to read it
are through an interface the router offers to an administrator:

- an **API** — for example FRR's REST API, or a vendor's REST or gRPC
  interface;
- **NETCONF** or **gRPC** over a management session;
- **SNMP**, reading a routing-table MIB;
- **SSH** into the router and run a vendor CLI command such as
  `show ip route`.

**Routers never answer with their table.** Asking a router "what is your
routing table" by sending it a datagram does nothing except waste a packet.

What *is* discoverable from the network is **neighbour relationships**:
LLDP and CDP are designed to be heard on a link by everyone on it, and they
tell you which devices are directly attached to which. That is a different
fact from a routing table, and this feature keeps the two apart — see
[Observed and inferred](#observed-and-inferred) below.

---

## The methods

Each method needs different things, and the feature can only use the ones
whose prerequisites are met.

| Method | What it reads | What it needs |
|--------|---------------|---------------|
| **LLDP** | neighbours on a link: device identity, interface names, capability and address information | the local machine able to run `lldpcli`; the far end speaking LLDP |
| **CDP** | neighbours on a link, in Cisco's protocol | the local machine able to run a CDP client; the far end speaking CDP |
| **SNMP** | the routing table, via the routing-table MIB | a reachable SNMP agent, a community string or user, and the right MIB |
| **FRR / `vtysh`** | the routing table, and the interfaces, from a software router | `vtysh` present, and a configured `vtysh` socket or session |
| **Vendor CLI over SSH** | the routing table, from a vendor's own command set | SSH access, a host key that is already trusted, and credentials held by the **server**, not by the caller |
| **ARP / the neighbour cache** | who is on this link | nothing extra, but it says only that something is there |

**Credentials never come from the request.** A request carries no password,
no private key, no SNMP community string and no token. If the server holds a
credential for a given device, it refers to it by name and uses the one it
already has. This is a hard rule, not a convention — see
[Safety rules](#safety-rules).

**ARP is not a router.** An ARP entry says that something answered on this
link. It does not say the thing is a router, and it does not say the thing
has a management interface. ARP neighbours are therefore recorded, but they
are not collected from on their own.

---

## Observed and inferred

Everything the feature shows is one of two things, and it always says which.

**Observed** means a management protocol reported it. An LLDP report naming
a router on a link is an observation: two devices, on a link, heard each
other.

**Inferred** means the feature worked it out. A routing table that says
"to reach `10.0.0.0/8`, send it to `192.168.1.1`" is the router's *claim
about a third party*. It is not an observation of a link between
`192.168.1.1` and whatever is at the far end of that next hop.

**A next-hop edge is therefore never observed.** It is inferred, and the
inference records what it was inferred from, so a reader can check the
reasoning rather than take it on trust. Two independent routers naming the
same next hop is stronger evidence than one, and that is exactly what a
provenance field is for.

---

## Safety rules

These are the rules the feature keeps. They are not options.

1. **Read-only.** Every command is checked against an allowlist before it
   runs. Anything that could change a device — `ip route add`, `commit`,
   `configure terminal`, `write memory`, `reload`, `shutdown` — is refused.
   So is anything not on the allowlist at all.

2. **No shell.** A command is run as an argument vector, never through a
   shell. A command that starts with an allowed prefix but carries a shell
   metacharacter, a newline, or a second command is refused outright. A
   refused command never reaches the process runner at all — not "run and
   ignore the result".

3. **A scope, enforced twice.** The set of devices the feature may contact
   is stated in the request, and it is checked both before a collection and
   before a newly discovered neighbour is queued. The second check is the
   important one: a neighbour inside the scope can point outside it, and
   without the second check one hop is enough to walk out of the allowed
   area.

4. **Bounded.** `max_depth` and `max_devices` are limits, not suggestions.
   A run that stops at a limit says it stopped at a limit, so that a small
   result is not mistaken for a complete one.

5. **No credentials in, no credentials out.** Not in a request, not in a
   response, and not in a log. A credential that is not returned can still
   be written to a log file, and a log file outlives the request.

6. **A run is private to whoever started it.** Its progress and its failures
   are not readable by another client.

7. **No packets.** This feature talks to management interfaces. It does not
   send probe packets, and it does not scan.

---

## The API

**Not yet final.** The three compatibility decisions that will settle the
exact shape — the allowlist's surface, the scope's shape, and how a run is
scoped to the client that started it — are still open, so the paths and
fields below are described by intent rather than pinned down.

The prefix is `/api/router-discovery/`, and the module is
`backend/app/router_discovery/`.

| Endpoint | Purpose |
|----------|---------|
| *(a scope preview)* | show what the requested scope covers and what would be contacted, **before** anything is |
| *(start a run)* | begin a discovery within a validated scope |
| *(a run's status)* | what state the run is in, which devices have been collected, which failed and why |
| *(a run's result)* | the devices, the links and the findings, each with its provenance |
| *(a finding's detail)* | the evidence a finding rests on, so it can be checked |

Two things will hold whatever the final shape is:

- A scope is validated **before anything is contacted**. A malformed or
  out-of-policy scope is refused without a single command being run.
- A refusal says what was refused and why. A refusal is not an empty
  result: the difference between "nothing was found" and "you asked for
  something that was not allowed" is the difference between a true negative
  and a false one.

---

## The honest limits

- **It can only see what it can reach.** A router that is not reachable from
  this machine, or that does not answer on the management interface the
  feature tried, is not in the result — and the result says it was not
  reached, rather than pretending the network has no such router.

- **A device that failed to collect is not a device with nothing on it.**
  These are different, and the result keeps them apart.

- **An absent reading is not evidence of absence.** If the routing table of
  one router could not be read, the analysis does not conclude that its
  routes are fine. It says the reading is missing.

- **It does not discover the physical network.** It finds routers it can
  reach a management interface on. It does not map campus cabling, VLANs,
  or what is in a rack.

- **It is not a monitoring tool.** It is a snapshot, taken at a moment, from
  one vantage point.

- **A finding is a claim with its conditions attached.** The analysis states
  what would have to be true for the finding to be raised, and does not
  assert a cause it cannot support.

---

## What has not been verified

This feature is not finished and **nothing about it has been proven against
a real router**. The design and the rules above are a specification. Here is
exactly what is missing, so that a reader can tell the difference between
what is written down and what is known to work.

| Not available here | What that leaves unproven |
|---|---|
| **No router** | the whole feature end to end: finding a device, reading its identity, reading its routing table |
| **No FRR** | reading a real routing table through `vtysh`, and the shape of the output that has to be parsed |
| **No containerlab** | the standard way to build a lab topology: a containerlab definition, a topology file, and a way to bring it up and tear it down |
| **No root** | creating the network namespaces the lab would use, and the privileges the management sessions would need |
| **No SNMP agent** | reading a routing table over SNMP, and the MIB values that have to be interpreted |
| **No LLDP or CDP speaker** | an *observed* edge from a management protocol — the one thing that is genuinely observed rather than inferred |
| **No second management address** | the identity rule in anger: one device, two addresses, collected once |

**What has been done instead.** The contract in
[`docs/router-discovery-test-plan.md`](router-discovery-test-plan.md) is
written out, and the independent tests in
`backend/tests/test_router_discovery_contract.py` are written against it
using a fake collector and a fake runner. Those tests prove what the
behaviour must be; they do not prove that any of it has been implemented
yet, because the module does not exist yet.

**What would be needed to close the gap**, in order of usefulness:

1. **A router.** A containerlab topology with FRR and one vendor image
   would give a routing table to read, an LLDP neighbour to observe, and
   a second address to identify a device by. Docker and containerlab, plus
   root or a user namespace with `ip netns` permitted, are what that needs.
2. **A fixed set of recorded command outputs.** If the outputs of
   `vtysh -c "show ip route"`, `lldpcli show neighbors -f json` and
   `ip -j route show` were captured once from a real router and checked
   in, the parser could be tested against real shapes without a router
   being present. This is the cheapest of the three and would catch most
   of the parsing bugs.
3. **An SNMP agent** and **an LLDP speaker**, each in a container, to cover
   those two methods.

Until at least the first of those exists, any statement that this feature
"works" is a statement about the design, not about the software.

---

## See also

- [`docs/router-discovery-test-plan.md`](router-discovery-test-plan.md) — the
  test plan, written before the module existed.
- [`docs/qa-gap-report.md`](qa-gap-report.md) — the independent review's
  findings across the project.
