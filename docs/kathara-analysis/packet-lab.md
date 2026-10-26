# Kathará vs RouteLens — Packet Lab Analysis

**Investigator:** MAIN AGENT (AGENT 3 did not produce a deliverable; Main Agent wrote this)
**Project:** RouteLens Lite × Kathará analysis
**Source:** Kathará reference extracted at `reference-repos/Kathara/Kathara-main/`
**RouteLens:** `/home/abhaysawant/Desktop/cn_project_2/backend/`
**Constraint:** READ-ONLY — no production files modified, Kathará not installed, Docker not installed, no privileged operations

---

## 1. Executive Summary

Kathará is a **Docker-container-based network emulation system** (GPL-3.0). Each network device is a Docker container; virtual links are Docker networks (collision domains); the manager deploys, wires, starts, and tears down labs. Kathará's model layer (`Lab`, `Machine`, `Interface`, `Link`, `ExternalLink`) is a pure topology description — IP config and forwarding live inside containers.

RouteLens Lite's Packet Lab is a **MIT-licensed Linux network namespace lab builder** (`lab_builder.py`) plus FastAPI routes (`packet_lab_routes.py`) that builds real namespaces/veth pairs from a `Scenario` definition, enables IP forwarding on routers, adds static routes, and probes via `ip netns exec ping`. It runs read-only collection without root; real lab apply requires root.

**Key finding:** RouteLens already implements most of what Kathará does at the packet-lab level (namespaces, veth pairs, forwarding, static routes, ping probe), but in pure Python/stdlib with no Docker. Kathará's equivalent needs Docker daemon + root + container images (High resource, unsuitable for the A8-7410/8GB/HDD dev machine).

**Licence:** Kathará GPL-3.0 vs RouteLens MIT — direct code reuse not permitted. Clean-room reimplementation of ideas only.

---

## 2. Kathará Packet Lab Source Inventory

| File | Lines | Purpose | Packet-lab relevance |
|---|---|---|---|
| `src/Kathara/model/Lab.py` | 516 | Topology container (machines + links + fs) | `connect_machine_to_link()` (92-116), `apply_dependencies()` (236-253), `check_integrity()` (180-193), `create_shared_folder()` (398-417) |
| `src/Kathara/model/Machine.py` | 843 | Network device model | `add_interface()` (85-117), `meta` (sysctls, exec_commands, ports, volumes, ulimits), `MACHINE_CAPABILITIES` (NET_ADMIN, NET_RAW, ...) line 27, `add_meta()` (144-291) |
| `src/Kathara/model/Interface.py` | 34 | Interface model | `machine`, `link`, `num`, `mac_address` (lines 25-28); MAC validation (30-31); **no IP address** |
| `src/Kathara/model/Link.py` | 32 | Collision domain model | `machines` dict (devices attached), `external` list, `api_object` (Docker Network) |
| `src/Kathara/model/ExternalLink.py` | 46 | Host interface attachment | `interface`, `vlan` (lines 11-13); `get_name_and_vlan()` (15-32) |
| `src/Kathara/manager/docker/DockerMachine.py` | ~1116 | Docker container deployment | Sets `net.ipv4.ip_forward=1` sysctl (line 274), `net.ipv6.conf.all.forwarding=1` (line 283), rp_filter (line 273) |
| `src/Kathara/manager/docker/DockerLink.py` | 415 | Docker network deployment | Creates Docker networks as collision domains; bridges host interfaces; `_attach_external_interfaces()` (line 317) |
| `src/Kathara/manager/docker/stats/DockerMachineStats.py` | 156 | Runtime device stats | `status`, `pids`, `cpu_usage`, `mem_usage`, `mem_percent`, `net_usage` (rx/tx bytes), `interfaces` (iface:link) |
| `src/Kathara/manager/docker/stats/DockerLinkStats.py` | 89 | Runtime link stats | `containers` attached to a Docker Network, `external`, `enable_ipv6` |
| `src/Kathara/foundation/manager/IManager.py` | — | Manager interface | `deploy_machine`/`deploy_link`/`deploy_lab` (17-59), `undeploy_*`/`wipe` (99-166), `exec`/`exec_obj` (220-276), `get_machines_stats`/`get_links_stats` (420-529) |
| `src/Kathara/cli/command/VstartCommand.py` | 14-251 | Start devices | image/mem/cpus/privileged options |
| `src/Kathara/cli/command/VcleanCommand.py` | — | Teardown devices | `lclean` / `vclean` |

**Dependencies:** `docker>=7.0.0`, `kubernetes>=23.3.0`, `pyroute2`, `fs>=2.4.16`, `libtmux` — requires Docker daemon (High resource).

---

## 3. RouteLens Packet Lab Source Inventory

| File | Lines | Purpose |
|---|---|---|
| `backend/app/lab_builder.py` | 373 | Linux namespace builder from `Scenario`: veth pairs, addr assignment, forwarding, static routes, ping probe |
| `backend/app/packet_lab.py` | — | `PacketLab` class, `get_packet_lab()`, `LabStatus`, `SimulateRequest/Response`, `LabState`, `VerificationProvenance` |
| `backend/app/packet_lab_routes.py` | 279 | FastAPI: `/status`, `/simulate` — real packet capture verification (TTL, checksum, route matching) |
| `backend/app/scenario.py` | — | `Scenario`, `Node`, `Route`, `Link` Pydantic models |
| `backend/app/network_collector.py` | 1438 | Read-only `ip -j` collection: interfaces, routes, neighbors, DNS, ping, traceroute |
| `backend/app/security.py` | 264 | Target validation, rate limiting |

### RouteLens `lab_builder.py` capabilities
- `build_commands(sc)` — generates command sequence: namespaces, loopback up, veth pairs (moved+renamed), addresses, link up, forwarding on routers only, static routes with `_validate_route_via()` (line 39-62)
- `run_all(commands, dry_run=True)` — executes commands; dry-run by default; real execution needs root (`_guard()` line 153-162)
- `teardown_commands(scenario)` / `run_teardown()` — idempotent namespace deletion
- `probe(src, dst_ip)` — `ip netns exec ns(src) ping -c1 -W1 dst_ip`; returns `delivered`/`timeout`/`unreachable`/`permission_denied`/`missing_binary`/`unavailable`/`error`; never fabricates success

### RouteLens `packet_lab_routes.py` capabilities
- `GET /status` — lab availability, router interfaces/routing table, requires root, `rl260-*` lab must exist beforehand
- `POST /simulate` — real packet capture verification with provenance per check (TTL decrement, checksum, route matched)

---

## 4. Comparison Tables (Required Format)

### Improvement 1: Namespace-based lab builder (already exceeds Kathará)

| Field | Required information |
|---|---|
| RouteLens location | `backend/app/lab_builder.py` — `build_commands()` (line 65), `run_all()` (line 179), `probe()` (line 301) |
| Kathará location | `src/Kathara/model/Lab.py` (topology), `src/Kathara/manager/docker/DockerMachine.py` (container deploy), `src/Kathara/cli/command/VstartCommand.py` (start devices) |
| Current behaviour | RouteLens builds real Linux namespaces with veth pairs, IP forwarding, static routes, and ping probes — in pure Python/stdlib, dry-run safe, root only for real apply |
| Reference behaviour | Kathará builds Docker containers connected to Docker networks; forwarding via sysctl inside containers; packet forwarding by Linux kernel inside containers |
| Improvement | None needed — RouteLens namespace approach is superior for teaching (zero Docker, explainable, works without root for dry-run). Kathará's container approach is Higher resource and not portable to this dev machine. |
| Compatibility | Fully compatible — RouteLens own stack |
| Dependencies | None new (`ip`, `ping` via subprocess) |
| Licence | MIT — RouteLens own code |
| Risk | Low — established, tested |
| Priority | Low (already implemented) |

### Improvement 2: Real packet probe via `ip netns exec ping`

| Field | Required information |
|---|---|
| RouteLens location | `backend/app/lab_builder.py` — `probe()` (line 301) |
| Kathará location | `src/Kathara/foundation/manager/IManager.py` — `exec`/`exec_obj` (lines 220-276) runs commands inside containers |
| Current behaviour | RouteLens `probe()` runs `ip netns exec ns(src) ping -c1 -W1 dst_ip`, returns structured status (`delivered`/`timeout`/`unreachable`/`permission_denied`/...), never fabricates success |
| Reference behaviour | Kathará `exec` runs arbitrary commands inside Docker containers; no dedicated ping probe abstraction — user runs `ping` manually inside container |
| Improvement | None needed — RouteLens `probe()` is cleaner (structured status, no root for dry-run, explicit error categories). Kathará requires Docker + container exec. |
| Compatibility | Fully compatible |
| Dependencies | None new |
| Licence | MIT — RouteLens own code |
| Risk | Low |
| Priority | Low (already implemented) |

### Improvement 3: Interface/MAC modeling gap

| Field | Required information |
|---|---|
| RouteLens location | `backend/app/routing.py` — `RoutingEntry.interface` is a string; `network_collector.py` `InterfaceInfo` (line 58) models real interfaces with MAC, state, MTU, addresses |
| Kathará location | `src/Kathara/model/Interface.py` — `machine`, `link`, `num`, `mac_address` (lines 25-28); **no IP address, no prefix, no state, no MTU** |
| Current behaviour | RouteLens models interfaces as name strings in routing entries; real interfaces collected read-only via `ip -j addr show`. Kathará's Interface is pure topology (MAC only), IP config delegated to container startup scripts |
| Reference behaviour | Kathará delegates IP configuration to container startup (`.startup` files executed inside containers); Python model never stores IPs |
| Improvement | RouteLens already models IPs better (`InterfaceInfo` has full address info). Kathará's IP-ins-container approach not portable without Docker. No change recommended. |
| Compatibility | Fully compatible |
| Dependencies | None new |
| Licence | MIT — RouteLens own code |
| Risk | Low |
| Priority | Low |

### Improvement 4: Topology integrity checking (adopt Kathará's `check_integrity`)

| Field | Required information |
|---|---|
| RouteLens location | `backend/app/scenario.py` — `Scenario` validation; `lab_builder.py` `_validate_route_via()` (line 39-62) validates route via-reachability |
| Kathará location | `src/Kathara/model/Lab.py` — `check_integrity()` (lines 180-193) validates sequential interface numbering across all machines; `Machine.check()` (Machine.py:356-379) |
| Current behaviour | RouteLens validates route via-reachability and interface existence per-node (`_validate_route_via`). No cross-node sequential interface numbering check. |
| Reference behaviour | Kathará `check_integrity()` raises `NonSequentialMachineInterfaceError` if any device has missing interface numbers (non-sequential). |
| Improvement | Add a lightweight topology-integrity check to `Scenario` validation (or `lab_builder.build_commands`) that flags non-sequential interface numbers per node, matching Kathará's `check_integrity` pattern (clean-room reimplementation). Low resource, pure Python. |
| Compatibility | Compatible — additive validation on `Scenario` model |
| Dependencies | None new |
| Licence | Idea observation only — GPL-3.0 code not copied |
| Risk | Low — additive validation, fail-fast on bad topologies |
| Priority | Medium |

### Improvement 5: External link / host bridging (rejected)

| Field | Required information |
|---|---|
| RouteLens location | `backend/app/network_collector.py` — read-only `ip -j addr show`/`route show`/`neigh show`; no host interface modification |
| Kathará location | `src/Kathara/model/ExternalLink.py` (host interface + VLAN); `src/Kathara/manager/docker/DockerLink.py` `_attach_external_interfaces()` (line 317) — bridges host interfaces to Docker networks; requires root (`utils.is_admin()`) |
| Current behaviour | RouteLens never modifies host interfaces — pure read-only collection |
| Reference behaviour | Kathará can bridge container networks to physical host interfaces (ExternalLink), requires root |
| Improvement | Do NOT implement host interface modification. Read-only security model is a feature. Kathará's external link is High resource + High risk. |
| Compatibility | Not recommended — violates RouteLens security model |
| Dependencies | Would require `pyroute2`, root, Docker — High resource |
| Licence | GPL-3.0 code not reusable |
| Risk | High — host network modification |
| Priority | Low (explicitly rejected) |

---

## 5. Capability Comparison

| Capability | RouteLens | Kathará | Resource (RouteLens) |
|---|---|---|---|
| Virtual network devices | Linux namespaces (`lab_builder.py`) | Docker containers | Low (namespaces) |
| Virtual links | veth pairs | Docker networks | Low (veth) |
| IP address assignment | `ip addr add` in namespace | Container startup scripts | Low |
| IP forwarding | `sysctl net.ipv4.ip_forward=1` on routers | Same sysctl inside containers | Low |
| Static routes | `ip route add` with `_validate_route_via` | Inside containers via startup | Low |
| Ping probe | `ip netns exec ping` (`probe()`) | `exec` ping inside container | Low |
| Real packet capture | `packet_lab_routes.py` `/simulate` (pcap/verification) | In-container `tcpdump` | Medium (pcap needs root) |
| Topology integrity | Per-node route validation only | `check_integrity()` sequential ifaces | Low |
| Host bridging | None (read-only security model) | `ExternalLink` + bridge | High (rejected) |
| Multi-device communication | Real namespace forwarding | Real container forwarding | Low |

---

## 6. What Works on the Dev Machine (A8-7410, 8GB, HDD)

**Works (Low resource, no Docker):**
- All RouteLens namespace lab operations (dry-run always; real apply needs root)
- `ip`, `ping` commands (iproute2, iputils-ping)
- Read-only network collection (`ip -j`)

**Does NOT work / not recommended (High resource):**
- Docker daemon (Kathará's core) — not installed, not to be installed per constraints
- Container-based labs — High memory, High disk
- Host interface bridging — root + security risk

---

## 7. Licence Analysis

| Aspect | Kathará | RouteLens |
|---|---|---|
| Licence | GPL-3.0 | MIT |
| Copyleft | Strong | Permissive |
| Direct code reuse into RouteLens | **Not permitted** (would force GPL-3.0) | N/A |
| Clean-room reimplementation of ideas | Permitted | N/A |

**Conclusion:** No Kathará source code may be copied into RouteLens. All packet-lab improvements must be clean-room reimplementations in MIT-licensed code. Integration with Kathará (if ever desired) should be at the process/Docker boundary only, not source copying.

---

## 8. Recommendations Ranked by Priority

| Priority | Improvement | Feasibility | Resource | Licence | Risk |
|---|---|---|---|---|---|
| Low | Namespace lab builder — already implemented, exceeds Kathará | Already done | Low | MIT | Low |
| Low | Real ping probe — already implemented | Already done | Low | MIT | Low |
| Low | Interface/IP modeling — RouteLens already better | Already done | Low | MIT | Low |
| Low | External bridging — explicitly rejected | Not feasible | High | GPL blocked | High |
| Medium | Topology integrity check (`check_integrity` pattern) | Additive, pure Python | Low | Idea only | Low |

---

## 9. Source File References

**Kathará (reference, GPL-3.0 — do not copy code):**
- `reference-repos/Kathara/Kathara-main/src/Kathara/model/Lab.py` — topology, `check_integrity()` (180-193), `connect_machine_to_link()` (92-116)
- `reference-repos/Kathara/Kathara-main/src/Kathara/model/Machine.py` — device model, `MACHINE_CAPABILITIES` (27), `add_interface()` (85-117)
- `reference-repos/Kathara/Kathara-main/src/Kathara/model/Interface.py` — interface model, no IP (11-34)
- `reference-repos/Kathara/Kathara-main/src/Kathara/model/Link.py` — collision domain (10-32)
- `reference-repos/Kathara/Kathara-main/src/Kathara/model/ExternalLink.py` — host interface attachment (6-46)
- `reference-repos/Kathara/Kathara-main/src/Kathara/manager/docker/DockerMachine.py` — container deploy, forwarding sysctl (274)
- `reference-repos/Kathara/Kathara-main/src/Kathara/manager/docker/DockerLink.py` — Docker network deployment (25-415)

**RouteLens (MIT — safe to modify):**
- `backend/app/lab_builder.py` — namespace builder, `build_commands()` (65), `run_all()` (179), `probe()` (301)
- `backend/app/packet_lab_routes.py` — `/status`, `/simulate` API (1-279)
- `backend/app/scenario.py` — `Scenario`, `Node`, `Route`, `Link` models
- `backend/app/network_collector.py` — read-only network collection

---

## 10. Final Statement

RouteLens already implements, in pure Python under MIT licence, everything Kathará does at the packet-lab level: virtual devices (namespaces vs containers), virtual links (veth vs Docker networks), IP forwarding, static routes, and ping probing. RouteLens's approach is lower-resource, works without Docker/root for dry-run, and is more explainable for teaching. Kathará's container model requires Docker + root + images (High resource, unsuitable for this dev machine). The only additive improvement worth considering is a topology-integrity check modeled on Kathará's `check_integrity()`. Host bridging and external connectivity are rejected due to High resource requirements and security model conflicts.
