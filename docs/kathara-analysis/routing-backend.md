# Kathará vs RouteLens — Routing / Backend Analysis

**Investigator:** AGENT 1 — Routing / Backend
**Project:** RouteLens Lite × Kathará
**Source:** Kathará reference extracted at `reference-repos/Kathara/Kathara-main/`
**RouteLens:** `/home/abhaysawant/Desktop/cn_project_2/backend/`
**Constraint:** READ-ONLY — no production files modified, Kathará not installed

---

## 1. Executive Summary

Kathará is a **Docker/Kubernetes container-based network emulation framework** (GPL-3.0). Its Python model layer (`Machine`, `Interface`, `Link`, `Lab`) is a **pure topology description** — devices, collision domains, interfaces, MAC addresses, and container metadata. It does **not** implement IP address configuration, routing tables, longest-prefix match, forwarding logic, or any routing protocol (OSPF/BGP/RIP/static) in Python. Routing and forwarding happen **inside** the Linux containers Kathara launches (via `net.ipv4.ip_forward=1` sysctl and whatever routing software the container image runs).

RouteLens is a **MIT-licensed FastAPI backend** that implements longest-prefix match, routing table management, packet-journey tracing, and real network collection entirely in Python userspace — no Docker, no root required for read-only operations.

**Key licence finding:** Kathará is GPL-3.0 (strong copyleft). RouteLens is MIT. Direct code reuse from Kathará into RouteLens is **not feasible** — GPL-3.0 would force RouteLens to become GPL-3.0. Only clean-room reimplementation of ideas (algorithms, patterns) is safe.

**Key resource finding:** Kathará requires Docker daemon + root privileges + `NET_ADMIN`/`NET_RAW` capabilities (High resource on the Pop!_OS A8-7410 / 8GB / HDD dev machine). RouteLens read-only collection needs only the `ip` binary (Low/Medium resource).

---

## 2. Kathará Source Inventory

| File | Lines | Purpose | Routing relevance |
|---|---|---|---|
| `reference-repos/Kathara/Kathara-main/src/Kathara/model/Machine.py` | 843 | Network device model | Device config (image, mem, cpus, sysctls, ports, volumes); NO IP config, NO routing table |
| `reference-repos/Kathara/Kathara-main/src/Kathara/model/Interface.py` | 34 | Interface model | machine/link/num/mac_address only; NO IP configuration |
| `reference-repos/Kathara/Kathara-main/src/Kathara/model/Link.py` | 32 | Collision domain model | Machines dict; no L2/L3 details |
| `reference-repos/Kathara/Kathara-main/src/Kathara/model/Lab.py` | 516 | Topology container | machines + links dicts; no routing logic |
| `reference-repos/Kathara/Kathara-main/src/Kathara/model/ExternalLink.py` | 46 | Host interface attachment | Interface name + VLAN; no routing |
| `reference-repos/Kathara/Kathara-main/src/Kathara/parser/netkit/LabParser.py` | 94 | lab.conf parser | `key[arg]=value` topology parsing |
| `reference-repos/Kathara/Kathara-main/src/Kathara/parser/netkit/ExtParser.py` | 76 | lab.ext parser | External host-interface links |
| `reference-repos/Kathara/Kathara-main/src/Kathara/parser/netkit/DepParser.py` | 75 | lab.dep parser | Boot dependency ordering |
| `reference-repos/Kathara/Kathara-main/src/Kathara/manager/docker/DockerMachine.py` | ~1116 | Docker container deployment | Sets `net.ipv4.ip_forward=1`, `net.ipv6.conf.all.forwarding=1` sysctls inside containers |
| `reference-repos/Kathara/Kathara-main/src/Kathara/manager/docker/DockerLink.py` | 415 | Docker network deployment | Creates Docker networks as collision domains; bridges host interfaces |
| `reference-repos/Kathara/Kathara-main/src/Kathara/os/Networking.py` | 213 | Host networking via pyroute2 | VLAN/bridge interface management on host |
| `reference-repos/Kathara/Kathara-main/src/Kathara/manager/kubernetes/KubernetesMachine.py` | ~1071 | K8s pod deployment | Removes default gateway; sets IPv4/IPv6 forwarding sysctls |

**Dependencies** (`src/requirements.txt`, `pyproject.toml`):
- `docker>=7.0.0`, `kubernetes>=23.3.0`, `pyroute2`, `fs>=2.4.16`, `libtmux`, `rich`, `requests`, `binaryornot`, `chardet`
- License: GPL-3.0
- Python >= 3.10
- **Requires Docker daemon** (High resource)

---

## 3. RouteLens Source Inventory

| File | Lines | Purpose |
|---|---|---|
| `backend/app/routing.py` | 381 | RoutingEntry, Provenance, NextHopType, IPVersion, RouteLookupResult, PacketHop, PacketJourneyRequest/Response, SAMPLE_ROUTES |
| `backend/app/routing_logic.py` | 452 | Longest-prefix match, metric tiebreaker, deterministic tiebreaker, `trace_packet_path()` |
| `backend/app/routing_table.py` | 279 | Thread-safe mutable routing table with persistence |
| `backend/app/main.py` | 986 | FastAPI app: /lookup, /routes, /packet-journey, /network/* endpoints |
| `backend/app/packet_lab_routes.py` | 279 | Virtual router lab status/simulate (requires root) |
| `backend/app/scenario_routes.py` | 338 | Scenario CRUD, trace, route updates, link state, lab apply/teardown, compare |
| `backend/app/network_collector.py` | 1438 | Read-only `ip -j` collection: interfaces, routes, neighbors, DNS, ping, traceroute |
| `backend/app/security.py` | 264 | Target validation (no shell metachars), per-client/operation rate limiting |
| `backend/app/lab_builder.py` | 373 | Linux network namespace builder from scenarios |

---

## 4. Comparison Tables (Required Format)

### Improvement 1: Longest-Prefix Match Algorithm

| Field | Required information |
|---|---|
| RouteLens location | `backend/app/routing_logic.py` — `find_matching_routes()` (line 17), `select_best_route()` (line 56), `lookup_route()` (line 106) |
| Kathará location | None in Python model. Forwarding done by Linux kernel inside containers. `DockerMachine.py` line 274 sets `net.ipv4.ip_forward=1` sysctl |
| Current behaviour | RouteLens implements longest-prefix match in pure Python: finds all routes whose network contains the destination IP, picks longest prefixlen, then lowest metric, then deterministic tiebreaker (interface name, then next_hop). Returns `RouteLookupResult` with explanation string. |
| Reference behaviour | Kathará has no longest-prefix match in Python. The Linux kernel inside each container performs forwarding using its own routing table (populated by the container OS or routing software). Kathara only enables forwarding via sysctl. |
| Improvement | Port Kathará's "forwarding is a kernel/sysctl concern" insight: RouteLens already implements longest-prefix match in Python, which is superior for a teaching tool because it is inspectable and explainable. No change needed to the algorithm itself; consider adding kernel-table comparison (observed vs simulated) which RouteLens already does via `/network/routes/analysis`. |
| Compatibility | Fully compatible — Pure Python, no new deps. |
| Dependencies | None (uses `ipaddress` stdlib). |
| Licence | RouteLens code is MIT — no reuse concern. Kathará's kernel-delegation approach is an idea, not code — safe to observe. |
| Risk | Low — existing algorithm is well-tested; adding observed-vs-simulated comparison is additive. |
| Priority | Low (already implemented well) |

---

### Improvement 2: Routing Table CRUD + Persistence

| Field | Required information |
|---|---|
| RouteLens location | `backend/app/routing_table.py` — `RoutingTable` class (line 39): `add_route()` (117), `update_route()` (141), `delete_route()` (167), `replace_routes()` (183), `get_summary()` (211), with `threading.RLock` and persistence via `routing_table_persistence.py` |
| Kathará location | None. Kathará's `Machine` model (`model/Machine.py`) holds meta (image, mem, cpus, sysctls, ports, volumes) but no routing table. Routes live inside containers only. |
| Current behaviour | RouteLens maintains a thread-safe in-memory routing table with atomic bulk replace, per-route validation (CIDR, next_hop, interface, metric, gateway-next_hop requirement), durability via JSON persistence, and summary statistics. |
| Reference behaviour | Kathará has no routing table abstraction. Machine sysctls (`net.ipv4.ip_forward=1`) enable kernel forwarding; routes are configured inside containers via `ip route` commands in startup scripts, not via Kathara's Python API. |
| Improvement | RouteLens already exceeds Kathará here: a programmable, validated, persisted routing table is strictly better for teaching than opaque container-internal routes. Consider adding per-route "shadowing" detection (a longer prefix shadowing a shorter one) — RouteLens `route_analysis.py` already does this. |
| Compatibility | Fully compatible — Pure Python, threading, file persistence. |
| Dependencies | None new. |
| Licence | MIT — RouteLens own code. No GPL exposure. |
| Risk | Low — persistence and locking are established patterns. |
| Priority | Low (already implemented) |

---

### Improvement 3: Packet Journey / Hop-by-Hop Tracing

| Field | Required information |
|---|---|
| RouteLens location | `backend/app/routing_logic.py` — `trace_packet_path()` (line 208), `PacketHop` dataclass (line 175). `main.py` `/packet-journey` endpoint (line 366). `scenario_routes.py` `trace_route()` (line 138) calls `app.scenario.trace()`. |
| Kathará location | None in Python. Packet tracing inside Kathará requires executing `tcpdump`/`traceroute` inside containers via the Manager API — not part of the model layer. |
| Current behaviour | RouteLens simulates a packet hop-by-hop using per-router tables (`router_tables` dict keyed by router IP). Actions: forward, deliver, drop, loop, unresolved_next_hop, error. Max 30 hops. Loop detection via visited set. Provenance marked "simulated". |
| Reference behaviour | Kathará does not trace packets in Python. Real packet traces require Docker containers, root, and in-container capture tools. |
| Improvement | RouteLens already exceeds Kathará for a teaching tool: simulated tracing is zero-resource, works without Docker/root, and produces explainable output. Consider adding optional "real lab compare" (already in `scenario_routes.py` `/compare`) which Kathará-style tools do natively but at High resource cost. |
| Compatibility | Fully compatible — Pure Python. |
| Dependencies | None new. |
| Licence | MIT — RouteLens own code. |
| Risk | Low. |
| Priority | Low (already implemented) |

---

### Improvement 4: Interface/IP Address Modeling

| Field | Required information |
|---|---|
| RouteLens location | `backend/app/routing.py` — `RoutingEntry.interface` is a string (line 53). `network_collector.py` `InterfaceInfo` dataclass (line 58) models real interfaces with name, index, state, MTU, MAC, IPv4/IPv6 addresses and networks. |
| Kathará location | `model/Interface.py` (line 11): `Interface` has `machine`, `link`, `num`, `mac_address` — **no IP address, no prefix, no state, no MTU**. `Machine.py` `add_interface()` (line 85) attaches a link but assigns no IP. |
| Current behaviour | RouteLens models interfaces as name strings in routing entries; real interfaces are collected read-only via `ip -j addr show`. Kathará's Interface is a pure topology object with no IP config. |
| Reference behaviour | Kathará delegates IP configuration to container startup scripts (`.startup` files executed inside containers). The Python model never stores IP addresses. |
| Improvement | RouteLens already models IPs better (InterfaceInfo has full address info). Kathará's approach (IPs inside containers) is not portable to RouteLens without Docker. No change recommended; RouteLens separation of modelled vs observed interfaces is cleaner for teaching. |
| Compatibility | Fully compatible. |
| Dependencies | None new. |
| Licence | MIT — RouteLens own code. |
| Risk | Low. |
| Priority | Low |

---

### Improvement 5: Topology Parsing from Config Files

| Field | Required information |
|---|---|
| RouteLens location | `backend/app/scenarios_data.py` — `SCENARIOS` dict (hardcoded Python). `backend/app/scenario.py` — `Scenario`, `Node`, `Route`, `Link` Pydantic models. `lab_builder.py` builds namespaces from scenarios. |
| Kathará location | `parser/netkit/LabParser.py` (line 10) — parses `lab.conf` with regex `key[arg]=value`. `ExtParser.py` parses `lab.ext`. `DepParser.py` parses `lab.dep` for boot ordering. |
| Current behaviour | RouteLens scenarios are hardcoded Python data structures edited via API (`/api/scenarios/{sid}/nodes/{nid}/routes`). Kathará parses text config files (`lab.conf`, `lab.ext`, `lab.dep`) using mmap + regex. |
| Reference behaviour | Kathará's file-based topology parsing is familiar to networking students (netkit-style lab.conf). RouteLens scenarios are in-memory Python objects with workspace isolation for edits. |
| Improvement | RouteLens could add file import/export (lab.conf-style) to let students load/save topologies as text files. This is additive and Low resource. Kathará's regex parser pattern could be reimplemented (clean room) but is not a routing improvement per se. |
| Compatibility | Compatible — Pure Python file parsing. |
| Dependencies | None new (stdlib `re`, `mmap`). |
| Licence | Idea only — GPL-3.0 code not reused. Clean-room reimplementation if adopting the regex pattern. |
| Risk | Low — additive feature. |
| Priority | Medium |

---

### Improvement 6: IP Forwarding Sysctl (Router Mode)

| Field | Required information |
|---|---|
| RouteLens location | `backend/app/lab_builder.py` — creates Linux namespaces with veth pairs. Does not set `net.ipv4.ip_forward`. `network_collector.py` reads routes read-only. |
| Kathará location | `manager/docker/DockerMachine.py` line 274: `sysctl_parameters["net.ipv4.ip_forward"] = 1`. Line 283: `net.ipv6.conf.all.forwarding = 1`. Line 273: rp_filter set to 0 for all/default/lo. |
| Current behaviour | RouteLens lab_builder creates namespaces but does not enable IP forwarding inside them. Kathará enables forwarding by default in every container (router mode). |
| Reference behaviour | Kathará treats every machine as a potential router (`ip_forward=1`). RouteLens treats namespaces as hosts unless forwarding is explicitly enabled. |
| Improvement | Add optional `net.ipv4.ip_forward=1` (and IPv6 equivalent) to `lab_builder.py` namespace setup so RouteLens real labs behave like Kathará containers (routers by default). Requires root (already required for lab apply). |
| Compatibility | Compatible with RouteLens stack (Linux namespaces). Requires root — already documented for `/lab/apply`. |
| Dependencies | None new (uses `ip`/`sysctl` via subprocess). |
| Licence | Idea observation only — GPL-3.0 code not copied. |
| Risk | Medium — enabling forwarding changes host network behavior; requires root; must be opt-in and clearly documented. |
| Priority | Medium |

---

### Improvement 7: External Connectivity / Host Bridging

| Field | Required information |
|---|---|
| RouteLens location | `backend/app/network_collector.py` — read-only `ip -j addr show`, `ip -j route show`, `ip -j neigh show`. No host interface modification. `main.py` `/network/*` endpoints are read-only. |
| Kathará location | `model/ExternalLink.py` (line 6) — host interface + VLAN. `manager/docker/DockerLink.py` `_attach_external_interfaces()` (line 317) — attaches host interfaces to Docker networks via bridge/VLAN. Requires root (`utils.is_admin()` line 337). `os/Networking.py` uses pyroute2 for link operations. |
| Current behaviour | RouteLens never modifies host interfaces — pure read-only collection. Kathará modifies host networking (bridges, VLANs, external links) requiring root. |
| Reference behaviour | Kathará can bridge container networks to physical host interfaces. RouteLens cannot (by design — security). |
| Improvement | Do NOT implement host interface modification in RouteLens. The security model (read-only, no root) is a feature for a teaching tool on a shared dev machine. Kathará's external link model is High resource and High risk. |
| Compatibility | Not recommended — would violate RouteLens security model. |
| Dependencies | Would require `pyroute2`, root, Docker — High resource. |
| Licence | GPL-3.0 code not reusable. Clean-room only if ever adopted. |
| Risk | High — host network modification, root required, Docker dependency. |
| Priority | Low (explicitly rejected) |

---

### Improvement 8: Security / Input Validation / Rate Limiting

| Field | Required information |
|---|---|
| RouteLens location | `backend/app/security.py` — `validate_target()` (line 104), `reject_unsafe_target_chars()` (line 54), `RateLimiter` class (line 142), `client_key()` (line 229). `main.py` uses these on `/network/dns-resolve`, `/network/connectivity`, `/network/traceroute`. |
| Kathará location | None. Kathará is a local CLI tool with no network-exposed API, no authentication, no rate limiting. `auth/` directory exists but is for Manager auth, not input validation. |
| Current behaviour | RouteLens validates targets (no shell metacharacters, no leading dash, IP or hostname shape), rate limits per client+operation (sliding window, bounded key map), and never trusts X-Forwarded-For. |
| Reference behaviour | Kathará has no security layer — it assumes a trusted local user with Docker/root access. |
| Improvement | RouteLens already exceeds Kathará. No change needed. Kathará's trust model is inappropriate for a web-exposed backend. |
| Compatibility | Fully compatible. |
| Dependencies | None new. |
| Licence | MIT — RouteLens own code. |
| Risk | Low. |
| Priority | Low |

---

## 5. Kathará Routing/Forwarding Code: What Does NOT Exist

A grep across `src/Kathara/model/` for `route|forward|ospf|bgp|rip|static` returned **zero matches** related to routing protocols or forwarding tables. Confirmed:

- **No IP address configuration** on `Interface` — only `mac_address` (model/Interface.py:28)
- **No routing table** on `Machine` or `Lab` — only meta dict (Machine.py:69-76)
- **No longest-prefix match** — forwarding is delegated to the Linux kernel inside containers
- **No routing protocol implementation** (OSPF, BGP, RIP, static) — expected to run inside container images
- **No packet capture/tracing** in Python — requires in-container tools

Kathará's routing-related actions are all **infrastructure**, not algorithms:
- `DockerMachine.py:274` — `net.ipv4.ip_forward = 1` sysctl
- `DockerMachine.py:283` — `net.ipv6.conf.all.forwarding = 1` sysctl
- `KubernetesMachine.py:113` — `ip route del default dev eth0`
- `DockerLink.py` — creates Docker networks as collision domains
- `os/Networking.py` — pyroute2 host interface management

---

## 6. Dependency & Resource Comparison

| Aspect | Kathará | RouteLens |
|---|---|---|
| Runtime | Docker daemon + containers | Python + FastAPI + uvicorn |
| Privileges | Root (`NET_ADMIN`, `NET_RAW`, `SYS_ADMIN`) | None for read-only; root for lab apply |
| Memory | High (Docker + multiple containers) | Low (~50-100MB Python process) |
| Disk | High (container images) | Low |
| CPU | Moderate-High | Low |
| Suitable for A8-7410/8GB/HDD | No (High resource) | Yes (Low/Medium) |
| Key Python deps | `docker`, `kubernetes`, `pyroute2`, `fs`, `libtmux` | `fastapi`, `pydantic` |
| System deps | Docker, iptables, vde, bridge utils | `ip` (iproute2), `ping`, `traceroute` |

---

## 7. Licence Analysis

| Aspect | Kathará | RouteLens |
|---|---|---|
| Licence | GPL-3.0 (pyproject.toml:7) | MIT (LICENSE) |
| Copyleft | Strong — derivative works must be GPL-3.0 | Permissive — no copyleft |
| Direct code reuse into RouteLens | **Not permitted** — would force RouteLens to GPL-3.0 | N/A |
| Clean-room reimplementation of ideas | Permitted (algorithms, patterns, not code) | N/A |
| Observation of behaviour | Permitted | N/A |

**Conclusion:** No Kathará source code may be copied into RouteLens. All RouteLens improvements must be clean-room reimplementations in MIT-licensed code, using only observed behaviour and algorithmic ideas from Kathará.

---

## 8. Recommendations Ranked by Priority

| Priority | Improvement | Feasibility | Resource | Licence | Risk |
|---|---|---|---|---|---|
| Low | Longest-prefix match — already implemented, exceeds Kathará | Already done | Low | MIT | Low |
| Low | Routing table CRUD + persistence — already implemented, exceeds Kathará | Already done | Low | MIT | Low |
| Low | Packet journey tracing — already implemented, exceeds Kathará | Already done | Low | MIT | Low |
| Low | Interface/IP modeling — RouteLens already models IPs better | Already done | Low | MIT | Low |
| Low | External connectivity / host bridging — explicitly rejected | Not feasible (Docker+root) | High | GPL-3.0 blocked | High |
| Medium | Topology file import/export (lab.conf-style) | Additive, pure Python | Low | Clean-room idea only | Low |
| Medium | IP forwarding sysctl in lab_builder (router mode) | Requires root for lab apply | Medium | Idea observation only | Medium |

### Feasible vs Requiring Docker/System Permissions

**Feasible without Docker/root (Low/Medium resource):**
- All routing algorithm improvements (already implemented in RouteLens)
- Topology file import/export
- Observed-vs-simulated route comparison (already in `/network/routes/analysis`)

**Requires Docker + root (High resource — not recommended for this dev machine):**
- Real container-based labs (Kathará's core model)
- Host interface bridging/VLANs
- In-container packet capture

---

## 9. Source File References

### Kathará (GPL-3.0 — do not copy code)
- `reference-repos/Kathara/Kathara-main/src/Kathara/model/Machine.py` — device model, meta properties, sysctl config (lines 27-28 capabilities, 69-76 meta dict, 420-427 is_privileged, 445-451 get_sysctls)
- `reference-repos/Kathara/Kathara-main/src/Kathara/model/Interface.py` — interface model, no IP config (lines 11-34)
- `reference-repos/Kathara/Kathara-main/src/Kathara/model/Link.py` — collision domain model (lines 10-32)
- `reference-repos/Kathara/Kathara-main/src/Kathara/model/Lab.py` — topology container (lines 21-516)
- `reference-repos/Kathara/Kathara-main/src/Kathara/model/ExternalLink.py` — host interface attachment (lines 6-46)
- `reference-repos/Kathara/Kathara-main/src/Kathara/parser/netkit/LabParser.py` — lab.conf parser (lines 10-94)
- `reference-repos/Kathara/Kathara-main/src/Kathara/manager/docker/DockerMachine.py` — container deployment, `net.ipv4.ip_forward=1` (line 274)
- `reference-repos/Kathara/Kathara-main/src/Kathara/manager/docker/DockerLink.py` — Docker network deployment (lines 25-415)
- `reference-repos/Kathara/Kathara-main/src/Kathara/os/Networking.py` — pyroute2 host networking (lines 9-213)
- `reference-repos/Kathara/Kathara-main/src/requirements.txt` — dependencies
- `reference-repos/Kathara/Kathara-main/pyproject.toml` — GPL-3.0 licence, Python >= 3.10

### RouteLens (MIT — safe to modify)
- `backend/app/routing_logic.py` — longest-prefix match, packet journey (lines 17-452)
- `backend/app/routing_table.py` — thread-safe routing table with persistence (lines 39-279)
- `backend/app/routing.py` — routing data models, SAMPLE_ROUTES (lines 1-381)
- `backend/app/main.py` — FastAPI app, all endpoints (lines 1-986)
- `backend/app/packet_lab_routes.py` — virtual router lab API (lines 1-279)
- `backend/app/scenario_routes.py` — scenario CRUD, trace, compare (lines 1-338)
- `backend/app/network_collector.py` — read-only network collection (lines 1-1438)
- `backend/app/security.py` — target validation, rate limiting (lines 1-264)
- `backend/app/lab_builder.py` — Linux namespace builder (lines 1-373)

---

## 10. Final Statement

RouteLens already implements, in pure Python and under MIT licence, everything Kathará does at the routing/forwarding algorithm level: longest-prefix match, metric tiebreaker, deterministic tiebreaking, per-router packet journey tracing, thread-safe routing table with persistence, and read-only real network collection. Kathará's equivalent functionality lives inside Docker containers (Linux kernel forwarding, `ip route` in startup scripts), not in its Python codebase. Direct code reuse is blocked by GPL-3.0 vs MIT licence incompatibility. The only additive improvements worth considering are topology file import/export and optional IP forwarding in namespace labs; host bridging and external connectivity are rejected due to High resource requirements and security model conflicts.
