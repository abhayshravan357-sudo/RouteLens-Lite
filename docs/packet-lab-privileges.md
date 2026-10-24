# RouteLens Lite — Packet Lab Privilege Requirements

**Project:** RouteLens Lite  
**Document:** Packet Lab privilege requirements and verification status  
**Source:** `backend/app/lab_adapter.py`, `backend/app/packet_lab.py`, `backend/app/packet_lab_routes.py`  
**Machine:** Pop!_OS Linux, UID 1000 (non-root), `pkexec`/`sudo` available but require graphical password prompt

---

## 1. Summary

The Packet Lab is a **read-only inspection tool** for a pre-existing Linux network namespace lab (`rl260-client`, `rl260-router`, `rl260-server`). It does **not** create, modify, or tear down namespaces. It only reads namespace state and sends probe packets through them.

All namespace access requires elevated privileges because entering a network namespace (`ip netns exec`) and capturing packets (`tcpdump`) are privileged operations on Linux.

When the backend cannot escalate privileges non-interactively (the normal case for a web backend running as a non-root user), the lab reports **HTTP 503** with an honest permission-denied message. It does **not** fabricate lab data.

---

## 2. Operations by Privilege Level

### 2.1 Requires elevated privileges (root / pkexec / sudo)

| Operation | Implementation | Why privileged |
|---|---|---|
| Enter namespace to read interfaces | `lab_adapter.py:331` — `ip netns exec <ns> ip addr show` | `ip netns exec` requires `CAP_SYS_ADMIN` or root |
| Enter namespace to read routes | `lab_adapter.py:344` — `ip netns exec <ns> ip route show` | `ip netns exec` requires `CAP_SYS_ADMIN` or root |
| Check IP forwarding on router | `lab_adapter.py:350` — `cat /proc/sys/net/ipv4/ip_forward` | Readable without root, but run inside namespace via `ip netns exec` |
| Send ICMP ping from namespace | `lab_adapter.py:575` — `ip netns exec <ns> ping ...` | `ip netns exec` + `ping` (typically `CAP_NET_RAW`) |
| Packet capture with tcpdump | `lab_adapter.py:636` — `ip netns exec <ns> timeout tcpdump ...` | `ip netns exec` + `tcpdump` (`CAP_NET_RAW` + promiscuous mode) |
| Combined ping + capture | `lab_adapter.py:671` — `run_ping_with_capture()` | Composes the two privileged operations above |
| Any `_run_in_namespace()` call | `lab_adapter.py:287` — `pkexec ip netns exec <ns> ...` | All namespace entry requires privilege escalation |

**All namespace operations go through `_run_in_namespace()`** (`lab_adapter.py:287`), which:
1. Checks that `ip` is available
2. Validates that `pkexec`/`sudo` works non-interactively (`_validate_privileges()`)
3. Builds the command as `pkexec ip netns exec <namespace> <command>` (or `sudo -n`)
4. Runs it with a timeout and bounded output

### 2.2 Does NOT require elevated privileges

| Operation | Implementation | Why |
|---|---|---|
| Check tool availability | `lab_adapter.py:261` — `which <tool>` | Reading PATH, no system calls |
| Check namespace existence | `lab_adapter.py:304` — `ip netns list` | Listing namespaces is unprivileged |
| Parse `ip addr` output | `lab_adapter.py:358` — `_parse_ip_addr()` | Pure string parsing, no system calls |
| Parse `ip route` output | `lab_adapter.py:394` — `_parse_ip_route()` | Pure string parsing, no system calls |
| Validate privilege escalation | `lab_adapter.py:196` — `_validate_privileges()` | Tests if pkexec works, doesn't use it for data |
| Build namespace commands | `lab_adapter.py:189` — `_build_ns_cmd()` | String assembly only |
| Route lookup / packet journey simulation | `backend/app/routing_logic.py` | Pure Python calculation, no system calls |

---

## 3. Current Verification Status

### 3.1 Verified WITHOUT elevated privileges

These were tested on the current machine (UID 1000, no root, pkexec requires graphical prompt):

| Test | Result | Evidence |
|---|---|---|
| `check_tools()` — `ip`, `ping`, `tcpdump`, `timeout` availability | ✅ Passed | `tests/test_network_collector.py` |
| `get_namespace_status()` — returns permission-denied error when pkexec unavailable | ✅ Passed | `tests/test_packet_lab.py` (48 tests) |
| `/api/lab/status` — returns HTTP 503 with honest error | ✅ Passed | `tests/test_packet_lab_integration.py` |
| `/api/lab/simulate` — returns HTTP 503 when lab unavailable | ✅ Passed | `tests/test_packet_lab_integration.py` |
| Packet journey simulation (pure Python, no namespace) | ✅ Passed | `tests/test_packet_journey.py` (46 tests) |
| Backend provenance fields (`source_type`, `source_description`) | ✅ Passed | `tests/test_network_collector.py` |

### 3.2 NOT verified — requires elevated privileges

The following operations **could not be validated** because non-interactive privilege escalation was unavailable:

| Operation | Why unverified |
|---|---|
| Actual namespace creation | The backend does not create namespaces; the `rl260-*` lab must exist beforehand |
| Actual `ip netns exec` to enter namespaces | Requires root or passwordless `pkexec`/`sudo` |
| Actual interface inspection inside namespaces | Blocked by privilege escalation failure |
| Actual route table inspection inside namespaces | Blocked by privilege escalation failure |
| Actual ICMP ping between namespaces | Blocked by privilege escalation failure |
| Actual packet capture with tcpdump | Blocked by privilege escalation failure |
| Actual end-to-end namespace connectivity | Blocked by privilege escalation failure |
| Actual namespace teardown/cleanup | The backend does not tear down namespaces |
| IP forwarding state inside router namespace | Blocked by privilege escalation failure |

**These remain explicitly unverified.** No mocked or dry-run test is presented as proof of actual Packet Lab forwarding.

---

## 4. Required System Configuration for Live Lab Access

To make the Packet Lab operational, the backend host needs one of:

### Option A: Passwordless sudo for `ip netns exec`

```bash
# /etc/sudoers.d/routelens
# Allow the backend user to run ip netns exec without password
<backend-user> ALL=(ALL) NOPASSWD: /usr/sbin/ip netns exec *
<backend-user> ALL=(ALL) NOPASSWD: /usr/bin/ip netns exec *
```

Then configure the adapter to use `sudo -n` instead of `pkexec`:
```python
LabAdapter(use_pkexec=False)
```

### Option B: Linux capabilities

```bash
# Grant CAP_NET_ADMIN and CAP_SYS_ADMIN to the backend binary
sudo setcap cap_net_admin,cap_sys_admin+ep /usr/bin/python3
```

**Note:** The project does **not** configure either of these. They are deployment-time decisions for the administrator. The backend must never be configured to run as root by default.

---

## 5. Security Boundaries

- **No host network modification**: The adapter only reads namespace state. It never changes host interfaces, routes, or firewall rules.
- **No namespace lifecycle management**: The backend does not create or delete namespaces. The `rl260-*` lab must be provisioned separately.
- **Input validation**: All namespace commands use validated, fixed command lists — no shell interpolation, no user-supplied commands.
- **Output bounding**: tcpdump output is capped at 100 lines (`max_output_lines`).
- **Timeouts**: All commands have timeouts (default 10s, capture 5s) to prevent hanging.
- **No authentication on endpoints**: The Packet Lab endpoints have no authentication. CORS controls which origins may call them. Do not expose the backend publicly without an access gateway.

---

## 6. Files Involved

| File | Role |
|---|---|
| `backend/app/lab_adapter.py` | Privileged namespace operations (pkexec/sudo, `ip netns exec`, ping, tcpdump) |
| `backend/app/packet_lab.py` | Packet lab controller, state machine, verification with provenance |
| `backend/app/packet_lab_routes.py` | FastAPI endpoints: `/api/lab/status`, `/api/lab/simulate` |
| `backend/app/security.py` | Target validation, rate limiting (applies to all endpoints) |

---

## 7. Verification Checklist

| Check | Status | Method |
|---|---|---|
| Lab reports 503 when privileges unavailable | ✅ | Integration test (`test_packet_lab_integration.py`) |
| Error message names the permission problem | ✅ | Integration test |
| Error message names affected namespaces | ✅ | Integration test |
| No fake success when lab unavailable | ✅ | Code review — all paths return error, never fabricate |
| Real namespace interface inspection | ❌ | Requires root/passwordless sudo |
| Real inter-namespace ping | ❌ | Requires root/passwordless sudo |
| Real packet capture | ❌ | Requires root/passwordless sudo |
| Real namespace teardown | N/A | Backend does not perform teardown |
