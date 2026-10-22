# Router Discovery — Wave 1 Design Review

**Reviewer:** Agent E (independent, read-only)
**Date:** 21 October 2026
**Branch:** `feature/router-discovery-audit` (off `integration/baseline-2026-10-20`)
**Subject:** `backend/app/router_discovery/` — design review, before the module was written

Every finding below was confirmed by running code against the current tree, not
by reading alone. Where a finding is by inspection only, it says so.

---

## The short version

The module must not reuse `scenario.py`'s trace engine to describe a real
router's path, because that engine cannot represent the two things that decide
a real router's choice: **admin distance** and **route protocol**. A trace
built from collected data can therefore name a path the router would not take,
and it will label itself `"provenance": "simulated"` while doing it.

Fourteen design requirements follow, D1 to D14.

---

## D1 — `TraceResult.provenance` is hardcoded to `"simulated"`

`backend/app/scenario.py:144`

```python
class TraceResult(BaseModel):
    status: Literal[...]
    hops: List[Hop]
    provenance: Literal["simulated"] = "simulated"
```

**Confirmed at runtime.** A `Scenario` built from a real routing table, traced:

```
trace over a Scenario built from a REAL table says provenance = 'simulated'
```

Reusing `trace()` for real router data returns a result that says it was
simulated. The type will not even accept another value.

**Smallest fix.** Do not reuse the result type as-is. A routing table read out
of a device is **observed**; a path computed from it is **inferred**. The
module's own result type should carry that, or `TraceResult.provenance` must
widen to `Literal["simulated", "observed", "inferred"]` and the analysis must
set it deliberately.

**Owner:** scenario.py stream, unless the analysis keeps its own result type.

---

## D2 — the engine cannot express admin distance, so a trace can be wrong

`backend/app/scenario.py:55-62` and `:226`

```python
class Route(BaseModel):
    prefix: str
    dev: str
    via: Optional[str]
    metric: int
    source: Literal["connected", "static"] = "static"
...
best = max(candidates, key=lambda r: (r.net.prefixlen, -r.metric))
```

### What administrative distance actually decides

This needs to be stated precisely, because the distinction is the whole
finding.

A router works in two steps:

1. **Build the FIB.** For each *prefix*, one route is installed — the best
   of the candidates for that prefix, by administrative distance first, then
   metric. So the FIB holds one route for `10.0.0.0/8`, and one for
   `10.0.0.0/24`, and nothing else.
2. **Forward.** Longest prefix match over the FIB.

So:

- **Administrative distance decides between routes for the SAME prefix.** It
  is what the FIB construction compares.
- **Longest prefix match decides between prefixes.** Administrative distance
  is irrelevant there, because the less specific route was never a candidate
  for that destination.

The textbook case everybody knows: a default route `0.0.0.0/0` with
administrative distance 1 and a specific `10.0.0.0/8` with administrative
distance 110. A packet to `10.1.2.3` goes out the `/8`, not the default,
even though the default has the better administrative distance.

### Where the engine is wrong

`lookup()` compares `(prefixlen, -metric)`. It has no protocol and no
administrative distance, so it cannot compare two routes for the same
prefix the way a router does.

**Confirmed at runtime**, on the case where administrative distance really
does decide — the same prefix, two protocols:

```
10.0.0.0/8       via 10.0.1.2  dev eth0  proto bgp   metric 20   admin-distance 20
10.0.0.0/8       via 10.0.2.2  dev eth1  proto ospf  metric 5    admin-distance 110
a REAL router picks : 10.0.0.0/8 via 10.0.1.2 (bgp: admin 20 beats admin 110)
the ENGINE picks    : 10.0.0.0/8 via 10.0.2.2 dev eth1
=> *** DISAGREE ***
```

The engine chose the OSPF route because its metric is lower. A router
installs the BGP route for that prefix because its administrative distance
is lower, and the OSPF route's better metric never comes into it.

### The cases where the engine is right, for completeness

```
10.0.0.0/8   bgp admin 20    vs   10.0.0.0/24  ospf admin 110
   a REAL router picks : 10.0.0.0/24 via 10.0.2.2 (the /24 is more specific)
   the ENGINE picks    : 10.0.0.0/24 via 10.0.2.2
   => AGREE

0.0.0.0/0    static admin 1  vs   10.0.0.0/8   bgp admin 110
   a REAL router picks : 10.0.0.0/8 via 10.0.2.2 (more specific)
   the ENGINE picks    : 10.0.0.0/8 via 10.0.2.2
   => AGREE
```

An earlier version of this review used the different-prefix case as its
example, and was wrong: it claimed a router would prefer the `/8` because
its administrative distance was lower. A router does not do that, because
the `/8` was never a candidate for a destination the `/24` already covers.
The finding stands; the worked example above is the correct one.

### Smallest fix

Do not present such a trace as "the path the packet would take". Either:

- add `admin_distance` and `protocol` to `Route`, and make `lookup()`
  compare administrative distance before metric when the prefix is the
  same, or
- label the result as *the longest-prefix decision over the routes that
  were collected*, and say plainly, when the collected table contains
  routes from more than one protocol for one prefix, that the device's own
  choice between them may differ.

**Also in D2:** `Route.source` is only `"connected"` or `"static"`.
Labelling a BGP route `"static"` is a provenance lie in the same field the
teaching model uses to explain *why* a route won. If the analysis cannot
say what protocol a route came from, it must say that it does not know,
rather than assert "static".

**Owner:** scenario.py stream, or the analysis stream if it keeps its own
route model.

---

## D3 — `Scenario` rejects realistic router links

`backend/app/scenario.py:171-175`

```python
if a_iface.net != b_iface.net:
    raise ValueError(f"Link {link.a}<->{link.b} endpoints are on different subnets ...")
```

**Confirmed at runtime:**

```
Link r1:eth0<->bgppeer:eth0 endpoints are on different subnets
(10.0.1.0/24 vs 10.1.1.0/24)  [type=value_error]
```

Real router-to-router links are routed — the two ends are on different
subnets — or are point-to-point `/31`s. The `Scenario` model was built for the
lab's namespaces, where both ends of a link share a subnet.

**Smallest fix.** The analysis must not build a `Scenario` for real topology.
If it does, it may include only same-subnet links, and must report the rest as
**not representable** — never by inventing a subnet so the validator passes.

**Owner:** analysis stream (it decides not to use `Scenario`), or scenario.py
stream if the model is to be extended.

---

## D4 — `SAFE_NAME_RE` rejects real interface names

`backend/app/scenario.py:28`, enforced at `:37-41` (interface names) and
`:92-95` (node ids)

```python
SAFE_NAME_RE = re.compile(r"^[a-z][a-z0-9-]{0,15}$")
```

**Confirmed at runtime:**

| name | result |
|---|---|
| `eth0`, `enp0s31f6`, `br-lan`, `vlan100` | PASS |
| `clab-rl-r1` | PASS |
| `Ethernet0` | REJECT |
| `Gi0/0/1` | REJECT |
| `xe-0/0/0` | REJECT |
| `tenGigE0/0/0.100` | REJECT |
| `eth0.100` | REJECT |
| `eth0@if3` | REJECT |
| `clab-routelens-lab-router-1` | REJECT (over 16 characters) |

**Smallest fix.** The analysis keeps a per-device map from the real name to a
safe alias, and uses the alias consistently in `route.dev`, `iface.name` and
both ends of every link. **The original name must be carried alongside.**
Showing an alias as though it were the device's interface name is a fabricated
name presented as observed.

**Owner:** analysis stream.

---

## D5 — `validate_target` handles names, but the module needs a *scope* validator

`backend/app/security.py:39-79`

**Confirmed at runtime:**

| target | result |
|---|---|
| `clab-rl-r1` | ACCEPTED |
| `clab-rl-r1.example.net` | ACCEPTED |
| `router1.lab.example.com` | ACCEPTED |
| `r1` | ACCEPTED |
| `10.0.0.1`, `2001:db8::1` | ACCEPTED |
| `show ip route` | REJECTED (whitespace) |
| `show ip route \| sh` | REJECTED (whitespace, metacharacters) |

So the container-name problem is **already handled**: `clab-rl-r1` is a single
label and matches `HOSTNAME_RE`.

But `validate_target` validates **one target**. The new module needs a **CIDR
allowlist**, which is a different thing.

**Smallest fix, and the answer to the manager's question.** The scope check
must be applied to the **resolved address**, not to the name:

1. The target is accepted either as a literal address (which is checked
   against the allowlist directly) or as a name (which passes
   `validate_target`).
2. A name is resolved, and **the resolved address** is then checked against
   the allowlist. A name that resolves outside the allowlist is refused, and
   the refusal says so.
3. The allowlist is a set of networks, checked with `ipaddress`, and it is
   checked **before every connection and before every enqueue** — not once at
   the start of a run.

This is not weaker than checking the name, because a name is not an address:
it is a hint about one. Checking the name would let a name that resolves
anywhere pass a check that is supposed to say where connections may go.

**Owner:** analysis stream.

---

## D6 — the "show" command must be a closed allowlist

`validate_target` filters whitespace and shell metacharacters, but it
validates **targets**, not the command that is sent to a device.

**Smallest fix.** The module holds a fixed table of supported read-only
commands (`show ip route`, `show ip interface brief`, and so on) and never
builds a command by concatenating user input. If "what to show" is
user-selectable it must be an **enum key into that table**, never free text.
A command such as `show ip route` must not be constructible as
`"show ip route" + anything`.

**Owner:** analysis stream.

---

## D7 — the limiter's shape is right for run creation, and cannot cap concurrency

`backend/app/security.py:129`

`RateLimiter.check(key)` counts requests in a sliding window and raises 429.
It is the right tool for counting **run creations**: one `check()` per run, at
the moment the run is created. It is the wrong tool for counting
per-device connections — a single run that contacts 50 devices would take 50
slots and trip the limit part way through the run.

**The gap the limiter cannot cover is concurrency.** Ten runs a minute, each
allowed to run for up to 300 seconds, means up to ten concurrent long-running
runs per client, each contacting up to N devices. The existing
`backend/app/discovery.py` has **no concurrent-run cap** — verified: there is
no `MAX_CONCURRENT` constant in it, and nothing limits how many runs may be in
flight.

**Smallest fix.** The new module needs a per-client **concurrent-run cap** in
addition to the per-minute limiter. The limiter bounds frequency; only a
separate counter bounds concurrency.

**Owner:** analysis stream.

---

## D8 — the output cap is post-hoc, so a large response still exhausts memory

`backend/app/network_collector.py:246-262`

```python
stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
...
if stdout_bytes > self.max_output_bytes or stderr_bytes > self.max_output_bytes:
    return -1, "", "Command output exceeded maximum size"
```

The **entire** output is read into memory first; the cap is checked
afterwards. `max_output_bytes` is 1 MB (`network_collector.py:231`).

**Confirmed at runtime**, with a command producing 3.4 MB:

```
produced 0 bytes; cap is 1048576
rc=-1 error='Command output exceeded maximum size'
peak RSS grew 6.6 MB during the call -> the whole output was in memory BEFORE the cap rejected it
```

This is fine for `ip -j route show` on a host, where the output is bounded by
the host's own routing table. It is **not** fine for a device that can be
sent unlimited data.

**Smallest fix.** Read incrementally with a running total, and kill the process
as soon as the cap is passed.

**Owner:** analysis stream.

---

## D9 — raw device stderr flows into error messages

`backend/app/network_collector.py:327`

```python
error=f"Command failed (rc={rc}): {stderr}",
```

A router CLI's stderr can carry a hostname banner, a login prompt, or a
configuration snippet.

**Smallest fix.** Never put raw device stderr into an API response or the
audit trail. Record "the device refused" plus a bounded, redacted form.

**Owner:** analysis stream.

---

## D10 — do not copy `discovery.py`'s CIDR branch; it is safe only by accident

`backend/app/discovery.py:176`

```python
if "/" in target and not any(ch.isspace() for ch in target) and not target.startswith("-"):
```

That is much weaker than `validate_target`'s metacharacter filter. It happens
to be safe because `ip_network()` then rejects the string — **confirmed**:
`10.0.0.0/24;id` and `10.0.0.0/24$(id)` are both refused — but it is a
fragile pattern to copy into a module whose targets reach a device.

**Smallest fix.** Reject metacharacters **first** (reuse `validate_target`'s
filter, or extract that filter into a shared helper in `security.py`), then
parse the network. Do not rely on the network parser to catch a shell
metacharacter.

**Owner:** analysis stream. (If the filter is extracted, `security.py` is
mine — say the word.)

---

## D11 — credentials

Never hardcoded, never logged, never in an API request, never in an API
response, never in the audit trail, never in a traceback the user sees.

Two paths would leak one today, and both are live in the code the module will
copy: D9 (stderr into error strings) and `discovery.py`'s free-text audit
`reason` (`discovery.py:235-247`). A credential echoed back by a device would
flow into both.

**Smallest fix.** The audit entry's `reason` must be **built by the collector**,
never taken raw from the device.

**Owner:** analysis stream.

---

## D12 — isolation between clients

One client must not read or interfere with another's run.

`backend/app/discovery.py` takes a bare `scan_id` in `POST /cancel` and has
**no per-client ownership check** — anyone who learns or guesses an id can
cancel that run. The new module must bind each run to the client that created
it and refuse a cancel from a different client.

A run id must not be guessable. `uuid.uuid4().hex[:12]` (48 bits) is fine; a
counter or a short sequential value is not.

**Owner:** analysis stream.

---

## D13 — provenance, per node and per edge

The project already has the vocabulary: `Provenance` with `observed`,
`inferred`, `simulated`, `unknown` in `routing.py`, applied by `topology.py`
to **every node and every edge**.

The new module must do the same:

- a route read out of a device is **observed**
- a link between two devices is **inferred** unless it was observed
- a device that was **not reached** is **unknown**, and must not appear as a
  node with empty fields
- a device that refused, timed out, or returned something unparseable must be
  **reported as such** — not as an empty success, and not omitted

**Owner:** analysis stream.

---

## D14 — the map is where a provenance lie would be most visible

`topology.py` and `NetworkNeighbors.tsx` already colour by provenance, and
`LearningLab.tsx:380-381` shows a "table observed, conclusion inferred" badge.
Whatever map the new module produces must carry provenance **per node and per
edge** all the way to the badge, exactly as `topology.py` does.

**Owner:** analysis stream and the frontend stream together.

---

## What was verified at runtime, and what was not

**Run against the current tree:**

- D1 trace provenance on a real-data Scenario
- D2 admin-distance divergence
- D3 the same-subnet link rejection
- D4 the name table above
- D5 the `validate_target` table above
- D8 the 3.4 MB output and its 6.6 MB RSS growth
- D10 the CIDR branch accepting and rejecting

**Read, not run:** D6, D7 (the absence of a concurrent-run cap was checked by
grep), D9, D11, D12, D13, D14.

**Not done, and why:** no device was contacted, nothing was scanned, no
privileged operation was run, and no package was installed.
