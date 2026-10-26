# RouteLens Lite × Kathará: Frontend Integration Analysis

**Agent:** AGENT 2 — Frontend investigator
**Status:** Read-only investigation. No production files modified.
**Kathára source:** `reference-repos/Kathara/Kathara-main/` (GPL-3.0)
**RouteLens frontend:** `frontend/src/` (MIT)

---

## 1. Executive Summary

Kathára is a **CLI-only, Docker-based network emulation system** with no web server, no REST API, and no frontend code. It exposes network scenarios through an in-memory Python object model (`Lab` → `Machine` → `Interface` → `Link`) and a command-line interface (`kathara.py`). Runtime status is obtained from Docker containers via `DockerMachineStats` / `DockerLinkStats`.

RouteLens Lite already has a mature, provenance-aware React frontend consuming a FastAPI backend. The frontend honestly distinguishes observed/inferred/simulated/unknown information across every panel. The primary integration opportunity is **not** rebuilding the frontend, but (a) adding a backend adapter that exposes Kathára's model and runtime stats through RouteLens's existing API contract, and (b) surfacing Kathára's real device/link status where RouteLens currently shows simulated-only data.

**Licence constraint:** Kathára is GPL-3.0. RouteLens is MIT. Any code *derived from* Kathára source (copying, adapting, translating) must be released under GPL-3.0 and would require relicensing or isolation of the RouteLens project. Writing a new adapter that merely *calls* Kathára's CLI or Docker API (process boundary, no source copying) creates a derivative-work question that should be reviewed by counsel; the safest approach is a clean-room adapter that speaks Kathára's CLI/JSON without copying Kathára source.

---

## 2. Kathára Architecture Findings

### 2.1 Topology model — `src/Kathara/model/Lab.py`

| Element | Location | Lines | Notes |
|---|---|---:|---|
| `Lab` class | `Lab.py:21` | 21–516 | Top-level scenario container |
| `Lab.machines` | `Lab.py:65` | 65 | `Dict[str, Machine]` — devices keyed by name |
| `Lab.links` | `Lab.py:66` | 66 | `Dict[str, Link]` — collision domains keyed by name |
| `LAB_METADATA` | `Lab.py:18` | 18 | `["LAB_NAME","LAB_DESCRIPTION","LAB_VERSION","LAB_AUTHOR","LAB_EMAIL","LAB_WEB"]` |
| `Lab.name`/`description`/`version`/`author`/`email`/`web` | `Lab.py:58–64` | 58–64 | Scenario metadata fields |
| `Lab.hash` | `Lab.py:76` | 76 | URL-safe hash from name/path |
| `Lab.connect_machine_to_link()` | `Lab.py:92–116` | 92–116 | Connects device to collision domain via interface |
| `Lab.get_or_new_machine()` | `Lab.py:293–307` | 293–307 | Get-or-create device |
| `Lab.check_integrity()` | `Lab.py:180–193` | 180–193 | Validates sequential interface numbering |
| `Lab.attach_external_links()` | `Lab.py:160–178` | 160–178 | Attaches external collision domains |
| `Lab.apply_dependencies()` | `Lab.py:236–253` | 236–253 | Boot-order dependencies |

### 2.2 Device model — `src/Kathara/model/Machine.py`

| Element | Location | Lines | Notes |
|---|---|---:|---|
| `Machine` class | `Machine.py:31` | 31–843 | Device representation |
| `Machine.interfaces` | `Machine.py:67` | 67 | `OrderedDict[int, Interface]` |
| `Machine.meta` | `Machine.py:69–76` | 69–76 | `exec_commands`, `sysctls`, `envs`, `ports`, `ulimits`, `volumes` |
| `Machine.api_object` | `Machine.py:78` | 78 | Manager API object (Docker Container or K8s Pod) |
| `Machine.fs` | `Machine.py:80–81` | 80–81 | Per-device filesystem (`fs.FS`) |
| `MACHINE_CAPABILITIES` | `Machine.py:27` | 27 | `NET_ADMIN`, `NET_RAW`, `NET_BROADCAST`, `NET_BIND_SERVICE`, `SYS_ADMIN` |
| `Machine.add_interface()` | `Machine.py:85–117` | 85–117 | Add interface to collision domain |
| `Machine.add_meta()` | `Machine.py:144–291` | 144–291 | Meta property setter (privileged, exec, bridged, sysctl, env, ulimit, port, volume) |
| `Machine.check()` | `Machine.py:356–379` | 356–379 | Validates sequential interface numbers |
| `Machine.pack_data()` | `Machine.py:381–418` | 381–418 | Packs device files into tar.gz |
| `Machine.is_privileged()` | `Machine.py:420–427` | 420–427 | Privileged mode check |
| `Machine.get_image()` | `Machine.py:477–484` | 477–484 | Image resolution (global meta → device meta → Setting default) |
| `Machine.get_mem()`/`get_cpu()` | `Machine.py:486–539` | 486–539 | Resource limits |
| `Machine.get_ports()` | `Machine.py:469–475` | 469–475 | Port mappings |

### 2.3 Interface model — `src/Kathara/model/Interface.py`

| Element | Location | Lines | Notes |
|---|---|---:|---|
| `Interface` class | `Interface.py:11` | 11–34 | Interface object |
| `Interface.machine`/`link`/`num`/`mac_address` | `Interface.py:25–28` | 25–28 | Attributes |
| `MAC_ADDRESS_REGEX` | `Interface.py:8` | 8 | MAC validation regex |

### 2.4 Link model — `src/Kathara/model/Link.py`

| Element | Location | Lines | Notes |
|---|---|---:|---|
| `Link` class | `Link.py:10` | 10–32 | Collision domain |
| `Link.machines` | `Link.py:28` | 28 | `Dict[str, Machine]` — devices attached |
| `Link.external` | `Link.py:27` | 27 | `List[ExternalLink]` |
| `Link.api_object` | `Link.py:29` | 29 | Manager API object (Docker Network) |

### 2.5 CLI entry point — `src/kathara.py`

| Element | Location | Lines | Notes |
|---|---|---:|---|
| `KatharaEntryPoint` | `kathara.py:27` | 27–110 | argparse-based CLI dispatcher |
| Commands | `kathara.py:79` | 79 | `CommandFactory().create_instance()` |
| Commands implemented | `src/Kathara/cli/command/` | — | `vstart`, `vclean`, `vconfig`, `lstart`, `lclean`, `lconfig`, `linfo`, `lrestart`, `connect`, `wipe`, `list`, `settings`, `check`, `exec` |
| `LinfoCommand` (live stats) | `cli/command/LinfoCommand.py` | 17–186 | Watch mode for machine stats and topology |
| `ListCommand` | `cli/command/ListCommand.py` | 14–86 | List running devices |
| `VstartCommand` | `cli/command/VstartCommand.py` | 14–251 | Start devices with image/mem/cpus/privileged options |
| `VconfigCommand` | `cli/command/VconfigCommand.py` | 11–89 | Add/remove interfaces on running devices |

### 2.6 Manager interface — `src/Kathara/foundation/manager/IManager.py`

| Method | Lines | Notes |
|---|---|---:|
| `deploy_machine`/`deploy_link`/`deploy_lab` | 17–59 | Deploy to Docker/K8s |
| `undeploy_machine`/`undeploy_link`/`undeploy_lab`/`wipe` | 99–166 | Teardown |
| `exec`/`exec_obj` | 220–276 | Run command on device |
| `connect_tty` | 169–217 | Interactive shell |
| `get_machines_stats`/`get_machine_stats` | 420–464 | Runtime device stats |
| `get_links_stats`/`get_link_stats` | 486–529 | Runtime link stats |
| `get_lab_from_api`/`update_lab_from_api` | 392–417 | Rebuild Lab from running state |
| `check_image`/`get_release_version` | 549–571 | Image/version queries |

### 2.7 Runtime stats (real status) — Docker manager

| Class | Location | Lines | Key fields |
|---|---|---:|---|
| `DockerMachineStats` | `manager/docker/stats/DockerMachineStats.py` | 11–156 | `status` (running/exited), `pids`, `cpu_usage`, `mem_usage`, `mem_percent`, `net_usage`, `interfaces`, `image`, `container_name`, `lab_hash`, `name`, `user` |
| `DockerLinkStats` | `manager/docker/stats/DockerLinkStats.py` | 10–89 | `name`, `network_name`, `enable_ipv6`, `external`, `containers` |

### 2.8 Web/API/frontend code in Kathára

**None found.** Grep for flask/fastapi/uvicorn/starlette/aiohttp/django returned zero matches in source code. The `webhooks/` directory contains only `DockerHubApi.py` and `GitHubApi.py` (release-check clients, not a web server). Documentation consists solely of ronn man pages in `docs/` — no API reference, no OpenAPI spec, no frontend code. Kathára is **CLI-only**.

### 2.9 Kathára documentation

| Doc | Location | Type |
|---|---|---|
| Man pages | `docs/kathara-*.1.ronn`, `kathara-*.5.ronn`, `kathara-lab-dirs.7.ronn` | roff/man |
| Index | `docs/index.txt` | Man page index |
| No API docs | — | No OpenAPI, no Swagger, no REST reference |

---

## 3. RouteLens Frontend Findings

### 3.1 API client — `frontend/src/api/routing.ts`

| Element | Location | Lines | Notes |
|---|---|---:|---|
| `fetchWithTimeout()` | `routing.ts:145–206` | 145–206 | Centralised fetch with abort timeout, `LabUnavailableError` (503), `TimeoutError` (408) |
| `checkHealth()` | `routing.ts:208–210` | 208–210 | `GET /health` |
| `fetchRoutes()` / CRUD | `routing.ts:212–297` | 212–297 | Routing table management |
| `checkLabStatus()` | `routing.ts:309–311` | 309–311 | `GET /api/lab/status` |
| `simulatePacket()` | `routing.ts:335–345` | 335–345 | `POST /api/lab/simulate` |
| `fetchInterfaces()`/`fetchNetworkRoutes()`/`fetchNeighbors()`/`fetchAllNetworkInfo()` | `routing.ts:348–362` | 348–362 | Network collector (`/network/*`) |
| `checkConnectivity()` | `routing.ts:386–439` | 386–439 | Reads `X-RouteLens-Result` header for unreachable targets |
| `runTraceroute()`/`tracePacketJourney()`/`resolveDns()` | `routing.ts:441–463` | 441–463 | Diagnostics |
| Scenario engine | `routing.ts:466–587` | 466–587 | `/api/scenarios/*` |
| Learning lab | `routing.ts:590–657` | 590–657 | `/api/exercises/*`, `/api/host-exercises/*` |
| Discovery | `routing.ts:659–716` | 659–716 | `/api/discovery/*` |
| PCAP analysis | `routing.ts:748–759` | 748–759 | `/api/pcap/analyze` |
| Router discovery | `routing.ts:768–852` | 768–852 | `/api/router-discovery/*` |
| Vite proxy | `frontend/vite.config.ts:16–31` | 16–31 | Proxies `/health`, `/routes`, `/lookup`, `/packet-journey`, `/api/lab`, `/api/pcap`, `/api/scenarios`, `/api/exercises`, `/api/host-exercises`, `/api/discovery`, `/api/report`, `/api/router-discovery`, `/network` to `http://127.0.0.1:8000` |

### 3.2 Data structures — `frontend/src/types/routing.ts`

| Type | Location | Lines | Notes |
|---|---|---:|---|
| `RouteProvenance` | `routing.ts:19` | 19 | `'observed' \| 'inferred' \| 'simulated' \| 'unknown'` |
| `RoutingEntry` | `routing.ts:21–32` | 21–32 | Route with optional `provenance` |
| `CollectionResult<T>` | `routing.ts:199–214` | 199–214 | Wrapper: `timestamp`, `success`, `data`, `error`, `command`, `duration_ms`, `ip_version`, `name_lookup` |
| `NetworkInterface` | `routing.ts:142–153` | 142–153 | Interface with state, MTU, MAC, addresses |
| `NetworkRoute` | `routing.ts:155–163` | 155–163 | Route with proto, scope, pref_src |
| `NetworkNeighbor` | `routing.ts:165–182` | 165–182 | Neighbor with `name_provenance` |
| `LabStatusResponse` | `routing.ts:86–92` | 86–92 | `available`, `state`, `message`, `router_info`, `error` |
| `LabState` | `routing.ts:326–336` | 326–336 | `idle\|ready\|simulating\|transmitting\|capturing\|verifying\|completed\|error\|timeout\|unavailable` |
| `Scenario`/`ScenarioNode`/`ScenarioLink`/`ScenarioIface`/`ScenarioRoute` | `routing.ts:385–390` | 385–390 | Scenario model |
| `ScenarioTrace` | `routing.ts:402–406` | 402–406 | `provenance: 'simulated'` (hardcoded literal) |
| `TopologyGraph`/`TopologyNode`/`TopologyEdge` | `routing.ts:504–510` | 504–510 | `TopologyProvenance` on every node/edge/graph |
| `LabProbeResult` | `routing.ts:464–470` | 464–470 | `status`, `rc`, `output`, `reason`, `provenance?: 'lab'` |
| `ScenarioCompare` | `routing.ts:472–477` | 472–477 | `simulated`, `lab`, `agree`, `note` |

### 3.3 Component structure — `frontend/src/App.tsx`

| View | Location | Lines | Notes |
|---|---|---:|---|
| `overview` | `App.tsx:403–442` | 403–442 | Host snapshot + last journey |
| `routing` | `App.tsx:444–545` | 444–545 | Route lookup, DecisionChain, Visualization, RoutingTable |
| `kernel` | `App.tsx:547–564` | 547–564 | Real host routing table (`KernelTable`) |
| `journey` | `App.tsx:566–629` | 566–629 | Scenario trace with picker (`ScenarioJourney`) |
| `lab` | `App.tsx:630–691` | 630–691 | Virtual lab lifecycle (`VirtualLabPanel`) + `PacketJourney` |
| `diagnostics` | `App.tsx:693–701` | 693–701 | `NetworkDiagnostics` |
| `discovery` | `App.tsx:703–720` | 703–720 | `RouterDiscoveryPage` (lazy) |
| `learning` | `App.tsx:722–730` | 722–730 | `LearningLab` |
| Health polling | `App.tsx:174–178` | 174–178 | Every 30s |
| Readouts | `App.tsx:350–388` | 350–388 | Routes/IPv4/IPv6/Lab/Match with tone |

### 3.4 Key status-conscious components

| Component | File | Lines | Honesty pattern |
|---|---|---:|---|
| `VirtualLabPanel` | `components/VirtualLabPanel.tsx` | 1–961 | Lab phase state machine, `readTestResult()` distinguishes captured vs calculated, per-check provenance |
| `ScenarioJourney` | `components/ScenarioJourney.tsx` | 1–1161 | `ProvenanceBadge provenance="simulated"` hardcoded, guided challenges, link toggle, route editor, ComparePanel |
| `ComparePanel` | `components/ComparePanel.tsx` | 1–162 | Simulated vs actual comparison, lab unavailable handling |
| `TopologyGraph` | `components/TopologyGraph.tsx` | 1–536 | Provenance-aware nodes/edges, observed_at timestamp |
| `ProvenanceBadge` | `components/ProvenanceBadge.tsx` | 1–73 | Core honesty UI primitive |
| `Overview` | `components/Overview.tsx` | 1–422 | Host facts with provenance badges |
| `PacketJourney` | `components/PacketJourney.tsx` | 1–513 | Calculated vs captured labels |
| `ResultDisplay` | `components/ResultDisplay.tsx` | 1–82 | Route lookup result |
| `ConnectivityPanel` | `components/ConnectivityPanel.tsx` | 1–523 | DNS/connectivity/traceroute |
| `NetworkDiagnostics` | `components/NetworkDiagnostics.tsx` | 1–530 | Interfaces/routes/neighbors from kernel |

---

## 4. Comparison Tables (Required Format)

### Improvement 1: Expose Kathára lab status through RouteLens `/api/lab/status`

| Field | Required information |
|---|---|
| RouteLens location | `frontend/src/api/routing.ts:309–311` (`checkLabStatus`); `frontend/src/components/VirtualLabPanel.tsx:267–304` (phase state machine) |
| Kathára location | `src/Kathara/foundation/manager/IManager.py:420–464` (`get_machines_stats`); `src/Kathara/manager/docker/stats/DockerMachineStats.py:68` (`status` field) |
| Current behaviour | RouteLens `checkLabStatus()` returns `available`/`state`/`message`/`router_info`/`error` from its own FastAPI backend. VirtualLabPanel derives phase from `labStatus.available` only. |
| Reference behaviour | Kathára `DockerMachineStats.status` returns Docker container status (`running`, `exited`, `created`, etc.). `IManager.get_machines_stats()` yields per-device stats including status, CPU, memory, network usage, interfaces. |
| Improvement | Add a RouteLens backend adapter that calls `kathara list` / `get_machines_stats()` (or queries Docker directly) and maps container status to `LabStatusResponse.state` (`ready` when running, `unavailable` when exited/not found). Include CPU/memory/network usage in `router_info`. |
| Compatibility | Fits the existing `LabStatusResponse` contract and `LabState` enum. Vite proxy already routes `/api/lab/status`. |
| Dependencies | None new (backend already uses Docker SDK if it manages namespaces). If calling `kathara` CLI, requires `kathara` binary on PATH. |
| Licence | Calling the `kathara` CLI as an external process is not a derivative work of Kathára source. **Do not copy Kathára Python source.** Low GPL risk if process-boundary only. |
| Risk | Regression: Low (additive endpoint). Security: CLI invocation requires input validation (lab hash/name). Maintenance: Kathára CLI output format could change between versions. |
| Priority | Critical |

### Improvement 2: Surface real per-device status (CPU/memory/network) in VirtualLabPanel

| Field | Required information |
|---|---|
| RouteLens location | `frontend/src/components/VirtualLabPanel.tsx:861–907` (device list renders `device.id`, `device.kind`, `device.ifaces`, `device.routes` only) |
| Kathára location | `src/Kathara/manager/docker/stats/DockerMachineStats.py:44–110` (`update()` reads `status`, `pids`, `cpu_usage`, `mem_usage`, `mem_percent`, `net_usage`, `interfaces`) |
| Current behaviour | VirtualLabPanel shows scenario-defined devices (name, kind, interfaces, routes) from the `Scenario` type. No real-time resource usage or container status is shown. |
| Reference behaviour | Kathára `DockerMachineStats.to_dict()` (line 115–134) emits `status`, `pids`, `cpu_usage`, `mem_usage`, `mem_percent`, `net_usage`, `interfaces`. |
| Improvement | Extend the scenario device view in VirtualLabPanel (or a new status panel) to show real container status, CPU, memory, and network I/O per device when the lab is running. Add a "real status" provenance badge next to each device. |
| Compatibility | Requires backend to expose per-device stats via API. Fits existing `NetworkInterface`-style result pattern. |
| Dependencies | Backend needs Docker/Kathára stats access. |
| Licence | Process-boundary CLI/Docker API access — low GPL risk if no Kathára source copied. |
| Risk | Regression: Low. Security: exposes host resource info — ensure authz. Maintenance: Docker stats format is stable. |
| Priority | High |

### Improvement 3: Surface real link status in scenario topology

| Field | Required information |
|---|---|
| RouteLens location | `frontend/src/components/ScenarioJourney.tsx:1053–1088` (Link Controls shows `link.is_up ?? true` from scenario definition only); `frontend/src/components/TopologyGraph.tsx:396–434` (edges show `provenance` but no real link state) |
| Kathára location | `src/Kathara/manager/docker/stats/DockerLinkStats.py:49` (`update()` reads attached containers); `src/Kathara/model/Link.py:28` (`machines` dict) |
| Current behaviour | Link state (`is_up`) comes solely from the scenario definition (`ScenarioLink.is_up`). No reflection of actual Docker network/container attachment state. |
| Reference behaviour | Kathára `DockerLinkStats` tracks which containers are attached to a Docker Network. `Link.machines` tracks which devices are connected to a collision domain. |
| Improvement | When the lab is deployed, fetch real link/container attachment state and merge it into the topology edges. Show a "deployed" vs "defined" distinction on links. If a link is defined UP but no containers are attached, flag it as stale. |
| Compatibility | Requires `TopologyEdge.is_up` to be backed by real data. Existing `is_up?: boolean` field supports this. |
| Dependencies | Backend link stats endpoint. |
| Licence | Process-boundary — low GPL risk. |
| Risk | Regression: Medium (link state could confuse users if backend and frontend disagree). Security: Low. Maintenance: Link attachment state changes dynamically — needs polling or event-driven updates. |
| Priority | High |

### Improvement 4: Add `provenance` to `ScenarioTrace` instead of hardcoded `'simulated'`

| Field | Required information |
|---|---|
| RouteLens location | `frontend/src/types/routing.ts:405` (`provenance: 'simulated'` hardcoded in `ScenarioTrace`); `frontend/src/components/ScenarioJourney.tsx:527` (`ProvenanceBadge provenance="simulated"` hardcoded) |
| Kathára location | `src/Kathara/model/Machine.py:78` (`api_object` — the real device); `src/Kathara/foundation/manager/IManager.py:220–276` (`exec` for real packet transmission) |
| Current behaviour | `ScenarioTrace.provenance` is typed as the literal `'simulated'`. The UI always labels scenario traces as simulated, even when compared against a real lab via `ComparePanel`. |
| Reference behaviour | Kathára can exec real commands on real containers (`IManager.exec`). A trace run against a deployed lab is observed, not simulated. |
| Improvement | Change `ScenarioTrace.provenance` from literal `'simulated'` to `RouteProvenance` (`'observed' \| 'inferred' \| 'simulated' \| 'unknown'`). Backend sets it based on whether the trace used a real lab or the scenario engine. Update `ScenarioJourney` to read provenance from the response rather than hardcoding. |
| Compatibility | Breaking type change for `ScenarioTrace.provenance` (literal → union). All consumers (`ScenarioJourney`, `Overview`, `ComparePanel`) must handle non-simulated values. |
| Dependencies | None on frontend; backend must populate provenance. |
| Licence | N/A (frontend-only type change). |
| Risk | Regression: Medium (type change ripples through components). Security: None. Maintenance: Low. |
| Priority | Medium |

### Improvement 5: Add observed_at / freshness timestamp to scenario trace

| Field | Required information |
|---|---|
| RouteLens location | `frontend/src/types/routing.ts:402–406` (`ScenarioTrace` has no timestamp); `frontend/src/components/ScenarioJourney.tsx:370–372` (hops displayed without collection time) |
| Kathára location | `src/Kathara/manager/docker/stats/DockerMachineStats.py:55` (`update()` called on construction); `src/Kathara/cli/command/LinfoCommand.py:123–131` (live watch mode refreshes every 12.5/s → 1s) |
| Current behaviour | `ScenarioTrace` has no `observed_at` or `collected_at`. The user cannot tell how old a trace result is. |
| Reference behaviour | Kathára stats objects call `update()` to refresh from Docker. `LinfoCommand` watch mode refreshes continuously. `TopologyGraph.observed_at` (RouteLens `types/routing.ts:509`) already has this pattern. |
| Improvement | Add `observed_at: string` to `ScenarioTrace` and `LabProbeResult`. Display "traced at <time>" in ScenarioJourney. Stale traces (older than a threshold) get a warning. |
| Compatibility | Additive field. Backend populates it. |
| Dependencies | None. |
| Licence | N/A. |
| Risk | Regression: Low. Security: None. Maintenance: Low. |
| Priority | Medium |

### Improvement 6: Add link-level stats to topology edges (bytes, packets)

| Field | Required information |
|---|---|
| RouteLens location | `frontend/src/components/TopologyGraph.tsx:396–434` (edges show `label`, `kind`, `provenance`, `detail` only); `frontend/src/types/routing.ts:494–502` (`TopologyEdge` has no traffic stats) |
| Kathára location | `src/Kathara/manager/docker/stats/DockerMachineStats.py:107–111` (`net_usage`: rx_bytes/tx_bytes); `src/Kathara/manager/docker/stats/DockerLinkStats.py` (link-level container attachment) |
| Current behaviour | Topology edges show relationship kind and provenance but no traffic volume or interface counters. |
| Reference behaviour | Kathára `DockerMachineStats.net_usage` aggregates rx/tx bytes per container. `DockerLinkStats` tracks attached containers per network. |
| Improvement | Add optional `rx_bytes`/`tx_bytes`/`packet_count` to `TopologyEdge`. Show throughput on the topology graph when lab is deployed. |
| Compatibility | Additive fields on `TopologyEdge`. Backend must expose per-interface or per-link counters. |
| Dependencies | Backend stats endpoint. |
| Licence | Process-boundary — low GPL risk. |
| Risk | Regression: Low. Security: None. Maintenance: Polling overhead for counters. |
| Priority | Low |

### Improvement 7: Add interface MAC address and admin/oper status to network interfaces view

| Field | Required information |
|---|---|
| RouteLens location | `frontend/src/types/routing.ts:142–153` (`NetworkInterface` has `mac_address`, `state`, `flags`); `frontend/src/components/NetworkInterfaces.tsx` (renders interface table) |
| Kathára location | `src/Kathara/model/Interface.py:27` (`mac_address`); `src/Kathara/manager/docker/stats/DockerMachineStats.py:87–90` (`interfaces` string like `"eth0:cd1, eth1:cd2"`); `src/Kathara/model/Link.py:28` (`machines` attachment) |
| Current behaviour | RouteLens `NetworkInterface` already has `mac_address` and `state` from the kernel (`ip -j`). No Kathára-specific interface data is integrated. |
| Reference behaviour | Kathára `Interface.mac_address` is validated against `MAC_ADDRESS_REGEX` (`Interface.py:30–31`). Docker stats build an `interfaces` string mapping iface→collision-domain. |
| Improvement | When a Kathára lab is deployed, add a tab or panel showing Kathára interfaces (MAC, collision domain, attached device) distinct from host kernel interfaces. Distinguish provenance: host interfaces = observed, Kathára interfaces = observed (from Docker labels) or simulated (from scenario definition). |
| Compatibility | Fits existing `NetworkInterface` type. New endpoint or tab. |
| Dependencies | Backend access to Kathára lab/Docker labels. |
| Licence | Process-boundary — low GPL risk. |
| Risk | Regression: Low. Security: MAC addresses are identifiable — handle per privacy policy. Maintenance: Low. |
| Priority | Low |

### Improvement 8: Show stale-data warning on scenario data

| Field | Required information |
|---|---|
| RouteLens location | `frontend/src/App.tsx:157–170` (`loadScenarios` fetches once on connect, no refresh); `frontend/src/components/ScenarioJourney.tsx:260–280` (scenario loaded once, no staleness check) |
| Kathára location | `src/Kathara/foundation/manager/IManager.py:392–417` (`get_lab_from_api` rebuilds Lab from running API objects); `src/Kathara/cli/command/LinfoCommand.py:114` (`update_lab_from_api` before topology display) |
| Current behaviour | RouteLens loads scenarios once and caches them. If the backend's scenario store changes (lab deployed/undeployed, routes edited externally), the frontend shows stale data. No `observed_at` on scenarios. |
| Reference behaviour | Kathára `update_lab_from_api()` refreshes a Lab object from the manager's current API objects before displaying topology (`LinfoCommand:114`). |
| Improvement | Add `observed_at` to `ScenarioSummary`/`Scenario`. Add a refresh button or auto-revalidate on scenario switch. Show "stale" badge if data is older than a threshold. |
| Compatibility | Additive fields. Backend populates timestamp. |
| Dependencies | None. |
| Licence | N/A. |
| Risk | Regression: Low. Security: None. Maintenance: Low. |
| Priority | Low |

---

## 5. Where RouteLens Frontend May Display Misleading / Stale / Incomplete Information

| Issue | Location | Why it is misleading/stale/incomplete | Kathára reference |
|---|---|---|---|
| Scenario trace always labelled "simulated" | `types/routing.ts:405`; `ScenarioJourney.tsx:527` | `provenance: 'simulated'` is a hardcoded literal. Even when `ComparePanel` runs against a real lab, the trace itself keeps the simulated badge. | Kathára `IManager.exec` runs real commands on real containers — a trace against a deployed lab is observed. |
| No freshness timestamp on traces | `types/routing.ts:402–406` | Users cannot tell if a trace was computed 5 seconds or 5 minutes ago. Scenario may have changed since. | Kathára stats call `update()` to refresh from Docker; `LinfoCommand` watch mode refreshes continuously. |
| Link `is_up` from scenario definition only | `ScenarioJourney.tsx:1066` (`link.is_up ?? true`) | The link status badge reflects the scenario file, not whether containers are actually attached to the Docker network. A link can show "UP" while the lab is torn down. | Kathára `DockerLinkStats.containers` shows real attachment; `Link.machines` tracks connected devices. |
| Device list shows no real status | `VirtualLabPanel.tsx:871–895` | Devices render name/kind/interfaces/routes from the scenario, with no CPU/memory/container-status info. A device can be listed while its container is `exited`. | Kathára `DockerMachineStats.status` (`running`/`exited`), `cpu_usage`, `mem_usage`, `net_usage`. |
| Scenarios cached without staleness | `App.tsx:157–170` | `loadScenarios()` runs once on backend connect. No revalidation. Deleted/modified scenarios remain visible. | Kathára `get_lab_from_api()` rebuilds from current state (`IManager.py:393`). |
| No real link/interface traffic in topology | `TopologyGraph.tsx:396–434` | Edges show relationship kind but no bytes/packets. Topology looks static even when traffic flows. | Kathára `DockerMachineStats.net_usage` aggregates rx/tx bytes. |
| Packet journey provenance inferred from field absence | `PacketJourney.tsx:220–225` | If `provenance` is missing, defaults to `'calculated'`. A backend that omits the field is treated as calculated, which may over-claim. | Kathára has no equivalent field (no web API); all Kathára-driven results would be observed. |
| ComparePanel lab status binary | `ComparePanel.tsx:48` (`labUnavailable = result?.lab.status === 'unavailable'`) | Only distinguishes available vs unavailable. No granularity for `running`/`exited`/`error` container states. | Kathára `DockerMachineStats.status` has multiple Docker statuses. |

---

## 6. Recommendations Ranked by Priority

### Critical

**1. Kathára-backed `/api/lab/status` adapter** — Map Kathára Docker container status to `LabStatusResponse` so RouteLens shows real lab availability (Critical, table in §4 Improvement 1).

### High

**2. Real per-device status in VirtualLabPanel** — Show container status/CPU/memory/network per device with provenance badge (High, §4 Improvement 2).

**3. Real link attachment state in topology** — Merge Kathára link/container attachment into topology edges; flag defined-but-unattached links (High, §4 Improvement 3).

### Medium

**4. `ScenarioTrace.provenance` as union type** — Replace hardcoded `'simulated'` literal with `RouteProvenance` union; backend populates (Medium, §4 Improvement 4).

**5. `observed_at` on traces and probe results** — Add freshness timestamps; warn on stale traces (Medium, §4 Improvement 5).

### Low

**6. Link/interface traffic counters in topology** — Add `rx_bytes`/`tx_bytes` to edges (Low, §4 Improvement 6).

**7. Kathára interfaces tab** — Separate panel for Kathára MAC/collision-domain interfaces with provenance (Low, §4 Improvement 7).

**8. Scenario staleness detection** — Add `observed_at` to scenarios; revalidate on switch (Low, §4 Improvement 8).

---

## 7. Licence Analysis for Every Reuse Proposal

| Proposal | Kath artefact used | Reuse mode | Licence implication | Risk level |
|---|---|---|---|---|
| `/api/lab/status` adapter | `kathara` CLI / Docker socket | Process boundary (CLI invocation or Docker API) | Not a derivative work of Kathára source if no source copied. GPL-3.0 does not apply to a separate process that merely executes `kathara`. | Low |
| Per-device status panel | `DockerMachineStats` fields (status, CPU, mem, net) | Reading Docker container metadata via Docker SDK | Facts from Docker API are not copyrightable. Low risk. | Low |
| Link attachment state | `DockerLinkStats.containers`, `Link.machines` | Reading Docker network attachments | Same as above. | Low |
| `ScenarioTrace.provenance` type change | None (frontend type only) | Frontend-only | N/A — RouteLens MIT code. | None |
| `observed_at` timestamps | None | Frontend/backend data model | N/A. | None |
| Any adaptation of Kathára Python source | `Lab.py`, `Machine.py`, `Interface.py`, `Link.py`, `IManager.py` | Copying/translating into TypeScript | **GPL-3.0 applies.** Derivative work must be GPL-3.0, incompatible with RouteLens MIT unless relicensed or cleanly isolated (separate executable, AGPL-style separation). **Do not copy Kathára source into RouteLens.** | High — avoid |

**Bottom line:** Integrate with Kathára at the process/Docker boundary (CLI, Docker socket, or `kathara` Python API invoked as a subprocess). Do not copy, translate, or derive from Kathára source files. Any Kathára-derived code must remain GPL-3.0 and should be shipped as a separate service, not linked into the MIT RouteLens frontend.

---

## 8. Resource Constraint Notes

Target: Pop!_OS, AMD A8-7410, 8GB RAM, HDD. Prefer Low/Medium improvements.

- All Critical/High proposals are backend-side additions with no new frontend dependencies.
- No new npm packages required; existing `fetchWithTimeout` pattern suffices.
- Polling for real device/link status should use the existing 30s health-poll interval or on-demand refresh, not high-frequency polling, to suit HDD/8GB constraints.

---

## 9. Source File Index

**Kathára (reference, read-only):**
- `reference-repos/Kathara/Kathara-main/src/kathara.py` — CLI entry point
- `reference-repos/Kathara/Kathara-main/src/Kathara/model/Lab.py` — topology scenario model
- `reference-repos/Kathara/Kathara-main/src/Kathara/model/Machine.py` — device model
- `reference-repos/Kathara/Kathara-main/src/Kathara/model/Interface.py` — interface model
- `reference-repos/Kathara/Kathara-main/src/Kathara/model/Link.py` — collision domain model
- `reference-repos/Kathara/Kathara-main/src/Kathara/foundation/manager/IManager.py` — manager interface (stats, deploy, exec)
- `reference-repos/Kathara/Kathara-main/src/Kathara/manager/docker/stats/DockerMachineStats.py` — real device stats
- `reference-repos/Kathara/Kathara-main/src/Kathara/manager/docker/stats/DockerLinkStats.py` — real link stats
- `reference-repos/Kathara/Kathara-main/src/Kathara/cli/command/LinfoCommand.py` — live stats display
- `reference-repos/Kathara/Kathara-main/src/Kathara/cli/command/ListCommand.py` — list running devices
- `reference-repos/Kathara/Kathara-main/src/Kathara/cli/command/VstartCommand.py` — start devices
- `reference-repos/Kathara/Kathara-main/src/Kathara/cli/command/VconfigCommand.py` — add/remove interfaces
- `reference-repos/Kathara/Kathara-main/docs/` — man pages only, no API docs

**RouteLens (production, do not modify):**
- `frontend/src/api/routing.ts` — API client
- `frontend/src/types/routing.ts` — data structures
- `frontend/src/App.tsx` — component structure
- `frontend/src/components/VirtualLabPanel.tsx` — lab lifecycle
- `frontend/src/components/ScenarioJourney.tsx` — scenario trace
- `frontend/src/components/ComparePanel.tsx` — simulated vs actual comparison
- `frontend/src/components/TopologyGraph.tsx` — provenance-aware topology
- `frontend/src/components/ProvenanceBadge.tsx` — provenance UI primitive
- `frontend/src/components/Overview.tsx` — host snapshot
- `frontend/src/components/PacketJourney.tsx` — calculated vs captured journey
- `frontend/src/components/NetworkInterfaces.tsx` — interface table
- `frontend/src/components/ConnectivityPanel.tsx` — diagnostics
- `frontend/src/components/NetworkDiagnostics.tsx` — diagnostics container
- `frontend/vite.config.ts` — dev proxy config
