# Packet Lab Capability Audit

**Project:** RouteLens Lite (Workstream B, Phase 3.2)  
**Scope:** `~/Desktop/cn_project_2` only  
**Machine:** Pop!_OS Linux, UID 1000 (non-root), `pkexec`/`sudo` present but require interactive password  
**Inspected files:** `backend/app/lab_adapter.py`, `backend/app/packet_lab.py`, `backend/app/packet_lab_routes.py`, `backend/app/main.py`, `backend/app/lab_builder.py`, `backend/app/scenario_routes.py`, `backend/tests/test_packet_lab.py`, `backend/tests/test_packet_lab_integration.py`, `frontend/src/components/VirtualLabPanel.tsx`, `frontend/src/App.tsx`, `docs/packet-lab-privileges.md`

---

## 1. Summary table

| # | Capability | Classification | Evidence | Blocker |
|---|---|---|---|---|
| 1 | Create or detect required network namespaces | Partially implemented | Detection: `lab_adapter.py:304` `check_namespace_exists()` reads `ip netns list` (unprivileged, works). Creation: **absent** from `lab_adapter.py` (read-only adapter). Creation code exists only in `lab_builder.py:88` (`ip netns add`) wired to `/api/scenarios/{sid}/lab/apply` (`scenario_routes.py:234`), not to the Packet Lab (`rl260-*`) adapter. | Packet Lab adapter never creates namespaces; `rl260-*` lab must pre-exist. |
| 2 | Create and connect virtual Ethernet interfaces | Partially implemented | `lab_builder.py:92-101` generates veth create/move/rename commands. `lab_adapter.py` has no veth creation at all. Not wired to Packet Lab routes. | Packet Lab adapter reads only; veth creation is in lab_builder (scenario lab), requires root. |
| 3 | Configure IP addresses and routes | Partially implemented | `lab_builder.py:104-109` (addr add/link up) and `:128-140` (static routes). `lab_adapter.py:331-346` reads `ip addr`/`ip route` but never writes. | Packet Lab adapter is read-only; config lives in lab_builder, requires root. |
| 4 | Enable IP forwarding | Partially implemented | `lab_builder.py:112-125` sets `net.ipv4.ip_forward=1` on routers only. `lab_adapter.py:349-354` only reads `/proc/sys/net/ipv4/ip_forward`, never sets it. | Read-only in Packet Lab; enable code requires root via lab_builder. |
| 5 | Send packets between namespaces (ping) | Implemented but not verified | `lab_adapter.py:540-621` `ping()` runs `ip netns exec <ns> ping ...` with output parsing. Unit-tested only with mocked `_run_in_namespace` (`test_packet_lab.py`). | Requires pkexec/sudo non-interactively — unavailable on this machine (pkexec times out rc=124; `sudo -n` requires password). |
| 6 | Capture packets using available tools (tcpdump) | Implemented but not verified | `lab_adapter.py:623-669` `capture_packets()` runs `tcpdump -v -i <iface> -n -c <count> icmp`. Unit-tested only with mocks. | Same privilege blocker as #5. tcpdump binary present but cannot run inside a namespace. |
| 7 | Display actual packet-capture results in the frontend | Implemented but not verified | `VirtualLabPanel.tsx:152-160` renders `capture_verified` and `readTestResult`; `:192-214` `readVerificationField` shows observed/inferred/unknown provenance; `:752-792` renders verification checks. No real capture has ever fed this path. | Capture never succeeds here, so `capture_verified` is never `true`; nothing "observed on the wire" is ever displayed. |
| 8 | Clean up resources safely after a lab session | Partially implemented | `lab_builder.py:145-298` `teardown_commands`/`run_teardown` (idempotent). Exposed at `/api/scenarios/{sid}/lab/teardown` (`scenario_routes.py:246`). Frontend calls it via `teardownScenarioLab` (`frontend/src/api/routing.ts:552`) defaulting to `dry_run=true` (no deletion). Packet Lab adapter (`rl260-*`) performs **no** teardown at all. | Requires root (`_guard` `lab_builder.py:153-159`); Packet Lab adapter has no cleanup code; frontend dry-runs by default. |

Classification key:
1. Implemented and verified — code exists AND evidence it works
2. Implemented but not verified — code exists, no real evidence
3. Partially implemented — some pieces present
4. Not implemented — absent entirely
5. Blocked by environment or permissions — code correct but can't run here

---

## 2. Detailed analysis per capability

### Capability 1 — Create or detect required network namespaces

**Classification: Partially implemented**

Detection is implemented and works unprivileged:
- `lab_adapter.py:304-315` `check_namespace_exists()` runs `ip netns list` and substring-matches the namespace name. Verified by `test_packet_lab.py:104-110` (non-existent namespace returns `exists=False`).

Creation is **absent** from the Packet Lab adapter:
- `lab_adapter.py` has no `ip netns add` anywhere. Its docstring (line 166) says it is a "Safe adapter" for a pre-existing lab.
- `docs/packet-lab-privileges.md:12`: "The Packet Lab is a read-only inspection tool... It does not create, modify, or tear down namespaces."
- `packet_lab_routes.py:153,199` docstrings: "The application does not provide a method to create this lab; it must exist beforehand."

Namespace creation code exists elsewhere but is not part of the Packet Lab flow:
- `lab_builder.py:88` `ip netns add <ns>` — part of scenario lab build, exposed via `/api/scenarios/{sid}/lab/apply` (`scenario_routes.py:234`), requires root.

**Environment check on this machine:** `ip netns list` returns empty — no `rl260-client`, `rl260-router`, or `rl260-server` namespaces exist. Even detection finds nothing to inspect.

---

### Capability 2 — Create and connect virtual Ethernet interfaces

**Classification: Partially implemented**

veth creation exists only in the scenario lab builder:
- `lab_builder.py:97` `ip link add <tmp_a> type veth peer name <tmp_b>`
- `lab_builder.py:98-99` move both ends into namespaces
- `lab_builder.py:100-101` rename inside each namespace

The Packet Lab adapter (`lab_adapter.py`) contains **no** veth creation, no `ip link` commands at all. It assumes interfaces (`rlc0`, `rlr0c`, `rlr0s`, `rls0`) already exist inside pre-created namespaces.

Not wired to Packet Lab API routes (`packet_lab_routes.py` exposes only `/status` and `/simulate`).

---

### Capability 3 — Configure IP addresses and routes

**Classification: Partially implemented**

Address/route configuration exists only in `lab_builder.py`:
- `lab_builder.py:106-108` `ip -n <ns> addr add <cidr> dev <iface>`
- `lab_builder.py:109` `ip -n <ns> link set <iface> up`
- `lab_builder.py:136-139` `ip -n <ns> route add <prefix> [via <gw>] dev <iface> metric <m>`

`lab_adapter.py` reads but never writes:
- `lab_adapter.py:331` `ip netns exec <ns> ip addr show` — read only
- `lab_adapter.py:344` `ip netns exec <ns> ip route show` — read only

No endpoint in `packet_lab_routes.py` configures addresses or routes inside the Packet Lab namespaces.

---

### Capability 4 — Enable IP forwarding

**Classification: Partially implemented**

Forwarding enable exists only in `lab_builder.py`:
- `lab_builder.py:114-119` `ip netns exec <ns> sysctl -qw net.ipv4.ip_forward=1` (routers only)
- `lab_builder.py:120-125` IPv6 forwarding too
- `lab_builder.py:717-745` tests assert hosts never get forwarding

`lab_adapter.py` only reads forwarding state:
- `lab_adapter.py:349-354` `cat /proc/sys/net/ipv4/ip_forward` inside the router namespace, stored in `NamespaceStatus.ip_forward_enabled`
- `lab_adapter.py:481-483` readiness check fails if `ip_forward_enabled` is falsy, but never attempts to enable it.

---

### Capability 5 — Send packets between namespaces (ping)

**Classification: Implemented but not verified (blocked at runtime)**

Code:
- `lab_adapter.py:540-621` `ping()` builds `ping -c <n> -i <i> -W <t> <dst>` and runs it via `_run_in_namespace` (line 575), which prefixes with `pkexec ip netns exec <ns>` (line 191).
- `lab_adapter.py:583-606` parses `packets transmitted/received` and `rtt min/avg/max/mdev`.
- `packet_lab.py:309-317` calls `run_ping_with_capture(source_namespace="rl260-client", destination=...)`.

Tests are all mocked — `test_packet_lab.py` never invokes a real `ip netns exec` or `ping`; it patches `_run_in_namespace` with `AsyncMock` (e.g. lines 119, 135, 177).

**Runtime blocker:** `_run_in_namespace` (line 295) calls `_validate_privileges()` (line 196), which runs `pkexec true` (line 208). On this machine `pkexec true` times out (rc=124, graphical password prompt) and `sudo -n true` fails ("a password is required", rc=1). So `_validate_privileges()` returns False and every namespace operation short-circuits with a permission error (line 296-299). Real ping between namespaces cannot execute here.

---

### Capability 6 — Capture packets using available tools (tcpdump)

**Classification: Implemented but not verified (blocked at runtime)**

Code:
- `lab_adapter.py:623-669` `capture_packets()` runs `timeout <t> tcpdump -v -i <interface> -n -c <count> icmp` inside the namespace (line 636), via `_run_in_namespace` (line 637).
- `lab_adapter.py:643-659` parses `packets captured`, `packets received by filter`, `packets dropped` from tcpdump output.
- `packet_lab.py:309-317` invokes capture on `rl260-router` egress interface `rlr0s` during `run_ping_with_capture`.
- `packet_lab.py:117-139` `_parse_tcpdump_ttl` and `:142-155` `_parse_tcpdump_checksum` parse tcpdump `-v` output, with explicit heuristics documented (first `ttl N` match may be echo request or reply).

`tcpdump` binary is present (`/usr/bin/tcpdump`), but capture requires entering the namespace (privileged) and raw-socket/promiscuous access. Same privilege blocker as capability #5 — never runs on this machine.

Tests mock `_run_in_namespace`; no real capture evidence exists (`test_packet_lab.py` uses hardcoded `raw_output` strings like `"IP ... ttl 63 ... checksum 0x1234 (correct)"` at line 450).

---

### Capability 7 — Display actual packet-capture results in the frontend

**Classification: Implemented but not verified (unreachable path here)**

Frontend rendering code exists and is well-structured:
- `frontend/src/components/VirtualLabPanel.tsx:122-170` `readTestResult()` — returns `outcome: 'captured'` only when `response.capture_verified` is true; otherwise reports timeout/unavailable/failed/not-verified.
- `:192-214` `readVerificationField()` — accepts boolean (provenance 'unknown') or object `{value, provenance, details}`.
- `:244-246` `reads labStatus?.router_info?.client_ip / server_ip` for test addresses.
- `:710-794` renders test outcome, packet fields, and per-check verification list with provenance badges (observed/inferred/unknown) and a legend explaining the distinction (`:786-790`).
- `frontend/src/App.tsx:82-87,129-155` holds `labStatus`/`labState` state and loads it via `checkLabStatus()` (`/api/lab/status`).

The code does **not** simulate or fabricate capture results — `readTestResult` explicitly refuses to claim a capture unless `capture_verified` is true. But since capture cannot run on this machine (capability #6), `capture_verified` is never true, so the frontend never displays an observed packet. The "captured" branch is dead code on this host.

---

### Capability 8 — Clean up resources safely after a lab session

**Classification: Partially implemented (blocked at runtime)**

Teardown code exists:
- `lab_builder.py:145-150` `teardown_commands()` — `ip netns del <ns>` per node, idempotent (missing namespaces not an error).
- `lab_builder.py:245-298` `run_teardown()` — executes with `_guard` root check, treats "namespace does not exist" as success.
- Exposed via `/api/scenarios/{sid}/lab/teardown` (`scenario_routes.py:246-250`), default `dry_run=true`.
- Frontend calls `teardownScenarioLab` (`frontend/src/api/routing.ts:552-561`), default `dryRun=true` — no actual deletion unless overridden.
- `VirtualLabPanel.tsx:447-474` `handleTeardown()` calls it and refreshes status.

**Critical gap for the Packet Lab (`rl260-*`):** `lab_adapter.py` has **no** teardown/cleanup method at all. The Packet Lab is explicitly read-only (`docs/packet-lab-privileges.md:121`: "No namespace lifecycle management: The backend does not create or delete namespaces."). The teardown endpoints belong to the separate scenario lab (`rl_*` prefix, `lab_builder.py:26`), not the `rl260-*` Packet Lab.

Runtime blocker: `run_teardown` calls `_guard()` (`lab_builder.py:153-159`) which returns "needs root: network namespaces require CAP_SYS_ADMIN" when `os.geteuid() != 0`. On this machine (UID 1000) teardown returns `{"status": "unavailable", ...}` unless run as root.

---

## 3. What actually prevents real verification on this machine

Three independent, compounding blockers:

1. **No namespaces exist.** `ip netns list` returns empty. The `rl260-client`, `rl260-router`, `rl260-server` namespaces that `lab_adapter.py` expects (`EXPECTED_TOPOLOGY`, `lab_adapter.py:110-130`) were never created on this host, and the Packet Lab adapter deliberately does not create them. Detection (`check_namespace_exists`) correctly reports them missing, so `check_lab_readiness()` returns `overall_ready=False`.

2. **No non-interactive privilege escalation.** Even if namespaces existed, every read/write operation inside them goes through `_run_in_namespace` (`lab_adapter.py:287`), which requires `pkexec` (default) or `sudo -n` (`use_pkexec=False`). On this machine:
   - `pkexec true` → times out (rc=124) waiting for a graphical password prompt.
   - `sudo -n true` → "a password is required" (rc=1).
   
   `_validate_privileges()` (`lab_adapter.py:196-226`) therefore returns `False`, and every namespace operation short-circuits with the permission-denied message at `lab_adapter.py:296-299`. The integration test (`test_packet_lab_integration.py`) confirms the API honestly returns HTTP 503 rather than fabricating results.

3. **The Packet Lab adapter is read-only by design.** `lab_adapter.py` creates nothing, configures nothing, enables no forwarding, and tears nothing down. It assumes an externally provisioned lab. The code that *can* create/configure/teardown (`lab_builder.py`) is gated behind root (`_guard`, `lab_builder.py:153-159`) and is exposed only under `/api/scenarios/{sid}/lab/apply|teardown`, not under the Packet Lab routes (`/api/lab/*`).

Because of 1–3, capabilities 5 (ping), 6 (tcpdump capture), and 7 (displayed capture results) can never reach their real code path on this host. All test evidence for them is mocked (`test_packet_lab.py`) or honesty-tested (503 responses, `test_packet_lab_integration.py`).

---

## 4. Whether any code changes are needed

**Read-only finding: no implementation in this phase.**

The codebase already does the honest thing everywhere it matters:
- `lab_adapter.py` never fabricates success; every privileged path returns an error when `pkexec`/`sudo` is unavailable.
- `packet_lab.py` reports `capture_verified=false` and falls back to `INFERRED`/`UNKNOWN` provenance when capture fails, rather than claiming observation.
- `packet_lab_routes.py` returns HTTP 503 when the lab is unavailable.
- `VirtualLabPanel.tsx` never renders "observed on the wire" unless `capture_verified` is true.
- `test_packet_lab_integration.py` asserts the API honestly reports unavailability.

No production file should be modified to "make the lab work" on this machine without first resolving the deployment prerequisites (passwordless `sudo`/`pkexec` for `ip netns exec`, or `CAP_NET_ADMIN`/`CAP_SYS_ADMIN` capabilities, plus pre-provisioned namespaces). Those are operator/configuration decisions documented in `docs/packet-lab-privileges.md:89-114`, not code changes.

If the team later wants the Packet Lab to be self-provisioning (create its own namespaces instead of requiring a pre-existing `rl260-*` lab), that would require wiring `lab_builder.py` build/teardown into the Packet Lab adapter and exposing build/teardown endpoints under `/api/lab/*` — but that is a new feature, not a fix, and it remains blocked by the root requirement on this host.

**Conclusion:** The Packet Lab implementation is correct and honest, but real namespace forwarding and packet capture cannot be verified on this machine because (a) the `rl260-*` namespaces do not exist, (b) the adapter does not create them, and (c) non-interactive privilege escalation (`pkexec`/`sudo`) is unavailable. All capture/ping paths are implemented but unverified here; nothing in the frontend simulates capture results.
