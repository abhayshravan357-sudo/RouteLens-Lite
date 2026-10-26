# Packet Lab Implementation Plan

**Project:** RouteLens Lite
**Workstream:** D (Phase 3.2)
**Scope:** Prioritized plan for making Packet Lab genuinely usable
**Constraint:** Plan only — no implementation, no production file changes
**Inputs:** `backend/app/lab_adapter.py`, `backend/app/packet_lab.py`, `backend/app/packet_lab_routes.py`, `docs/packet-lab-privileges.md`, `docs/packetlab-audit-report.md`, `docs/lab-command-audit.md`, `docs/kathara-analysis/packet-lab.md`, frontend `VirtualLabPanel.tsx`, `api/routing.ts`

---

## Summary of Current State

The Packet Lab consists of three backend files providing `GET /api/lab/status` and `POST /api/lab/simulate` over FastAPI, plus a frontend panel (`VirtualLabPanel.tsx`) for lab lifecycle (build/test/teardown). The code is honest — it never fabricates lab data and reports 503 when namespaces or privileges are unavailable. However, **live lab operation is not possible today** because:

1. No non-interactive privilege escalation is configured (pkexec requires a graphical password prompt; sudo is not passwordless for `ip netns exec`).
2. The `rl260-*` namespaces do not exist on the dev host and the backend does not create them.
3. Several API parameters (`protocol`, `ttl`, `length`) are validated and echoed but never used in actual packet transmission.
4. Verification fields (TTL, checksum, route) are inferred from ping success rather than measured from capture when tcpdump output lacks the expected patterns.

The plan below is ordered by priority. Critical blockers must be resolved before any backend or frontend work can produce a usable live lab.

---

## 1. Critical Blockers

These must be resolved before anything else. Without them, every web request to the Packet Lab either hangs or returns 503.

| # | Task | Description | Dependencies | Likely File Ownership | Priority |
|---|------|-------------|--------------|----------------------|----------|
| 1.1 | Configure non-interactive privilege escalation | Set up passwordless sudo for `ip netns exec` on the `rl260-*` namespaces, or grant `CAP_NET_ADMIN`/`CAP_SYS_ADMIN` to the backend binary. Document which option is chosen. The adapter must not block waiting for a password prompt. | `backend/app/lab_adapter.py` (`_build_ns_cmd`, `_validate_privileges`, `_run_in_namespace`); `docs/packet-lab-privileges.md` (Section 4 already documents both options) | Deployment/ops (sysadmin); backend engineer reviews sudoers/capabilities config | Critical |
| 1.2 | Add startup privilege validation | Add a backend startup check that validates privilege escalation works non-interactively before accepting lab requests. Fail fast with a clear message rather than hanging per-request. | `backend/app/lab_adapter.py` (`_validate_privileges`); `backend/app/main.py` (startup event) | Backend engineer | Critical |
| 1.3 | Provision the `rl260-*` lab namespaces | Create the three network namespaces (`rl260-client`, `rl260-router`, `rl260-server`) with veth pairs, IP addressing, IP forwarding on the router, and static routes. This is a one-time host setup, not backend code. | `lab_adapter.py` `EXPECTED_TOPOLOGY` (defines expected names/ips/routes); root access on the host | Sysadmin / devops; verified by backend engineer | Critical |
| 1.4 | Add per-request privilege timeout guard | Ensure `_run_command` cannot block indefinitely on pkexec/sudo. The existing `asyncio.wait_for` timeout exists but pkexec may spawn a graphical agent that never returns. Add a hard kill path and a "privilege unavailable" fast-fail. | `backend/app/lab_adapter.py` (`_run_command`, `_run_in_namespace`) | Backend engineer | Critical |

---

## 2. Backend Changes

Code modifications needed after critical blockers are cleared.

| # | Task | Description | Dependencies | Likely File Ownership | Priority |
|---|------|-------------|--------------|----------------------|----------|
| 2.1 | Implement topology validation in `_validate_request` | Reject `source_ip`/`destination_ip` that are not in the lab topology (`192.168.10.2` / `192.168.20.2`) at request validation time, before any namespace operation. Currently the source IP is hardcoded to `rl260-client` and destination is passed through unchecked. | `backend/app/packet_lab.py` (`_validate_request`); `backend/app/packet_lab_routes.py` (`SimulateRequestModel`) | Backend engineer | High |
| 2.2 | Wire `protocol`/`ttl`/`length` into packet generation | Currently these parameters are validated and echoed but `run_ping_with_capture` uses hardcoded `filter_expr="icmp"`, ping count=3, no TTL/length. Either implement real parameter support (e.g. `ping -s <length> -t <ttl>`, or scapy/hping3) or remove the parameters from the API contract. | `backend/app/lab_adapter.py` (`ping`, `capture_packets`, `run_ping_with_capture`); `backend/app/packet_lab.py` (`simulate`) | Backend engineer | High |
| 2.3 | Make verification details measured, not inferred | When tcpdump output lacks TTL/checksum patterns, the code falls back to inferring from ping success. Improve tcpdump parsing (e.g. per-packet analysis, correlate with ICMP type) so `ttl_decremented`, `checksum_valid`, `route_matched` are genuinely observed from capture where possible. | `backend/app/packet_lab.py` (`_parse_tcpdump_ttl`, `_parse_tcpdump_checksum`); `backend/app/lab_adapter.py` (`capture_packets`) | Backend engineer | High |
| 2.4 | Add lab build/teardown API endpoints | The backend currently assumes the `rl260-*` lab exists. Add endpoints (or wire the existing scenario lab endpoints) to create and destroy namespaces on demand, so the frontend can drive the full lifecycle. | `backend/app/lab_builder.py` (already has `build_commands`, `run_all`, `run_teardown`, `teardown_commands`); `backend/app/main.py` (router registration) | Backend engineer | High |
| 2.5 | Add authentication/authorization to lab endpoints | Packet Lab endpoints currently have no authentication. The privileges doc warns not to expose the backend publicly without an access gateway. Add at minimum a deployment-time auth requirement. | `backend/app/main.py` (middleware); `backend/app/packet_lab_routes.py` | Backend engineer | Medium |
| 2.6 | Add lab lifecycle state tracking | Persist lab state (built/running/torn-down) across requests so `/status` reflects reality rather than re-probing namespaces every time. | `backend/app/packet_lab.py` (`LabState`); `backend/app/packet_lab_routes.py` (`LabStatusResponse`) | Backend engineer | Medium |
| 2.7 | Refine error categorization in `probe()` | The lab-command-audit notes `probe()` already distinguishes delivered/timeout/unreachable/permission_denied/missing_binary. Ensure `packet_lab.py` maps these to distinct HTTP status codes (e.g. 408 for timeout, 403 for permission denied). | `backend/app/lab_adapter.py`; `backend/app/packet_lab.py` (`simulate`) | Backend engineer | Medium |

---

## 3. Linux Environment and Permission Requirements

Infrastructure setup outside the application code.

| # | Task | Description | Dependencies | Likely File Ownership | Priority |
|---|------|-------------|--------------|----------------------|----------|
| 3.1 | Install required system tools | Ensure `ip`, `ping`, `tcpdump`, `timeout` are installed on the backend host. | `lab_adapter.py` `REQUIRED_TOOLS` | Sysadmin | Critical |
| 3.2 | Configure passwordless sudoers rule | Create `/etc/sudoers.d/routelens` allowing the backend user to run `ip netns exec rl260-*` commands without a password. Alternatively configure `sudo -n` in the adapter. | `docs/packet-lab-privileges.md` Section 4 (Option A) | Sysadmin | Critical |
| 3.3 | OR: Grant Linux capabilities | As an alternative to sudo, grant `cap_net_admin,cap_sys_admin+ep` to the backend Python binary so `ip netns exec` works without sudo. | `docs/packet-lab-privileges.md` Section 4 (Option B) | Sysadmin | Critical (alternative to 3.2) |
| 3.4 | Create `rl260-*` namespaces with topology | Build client/router/server namespaces, veth pairs, IP addresses (192.168.10.0/24, 192.168.20.0/24), IP forwarding on router, static routes. Match `EXPECTED_TOPOLOGY` in `lab_adapter.py`. | Root access; `ip` tool | Sysadmin | Critical |
| 3.5 | Document host hardening | Record which ports the backend listens on, CORS origins, and that the backend must not run as root by default. | `docs/packet-lab-privileges.md` Section 5 | Sysadmin / security review | Medium |
| 3.6 | Add environment validation script | A script that checks tools, privileges, namespace existence, and topology before the backend starts, printing actionable remediation steps. | `scripts/` directory; `lab_adapter.py` check methods | Backend engineer | Medium |

---

## 4. Packet Capture Integration

tcpdump capture and result display.

| # | Task | Description | Dependencies | Likely File Ownership | Priority |
|---|------|-------------|--------------|----------------------|----------|
| 4.1 | Verify tcpdump works inside namespaces | Test `ip netns exec rl260-router tcpdump -i rlr0s -c 10 icmp` with the configured privileges. Confirm packet capture output is parseable. | `lab_adapter.py` `capture_packets`; namespaces provisioned (1.3) | Backend engineer (with sysadmin) | High |
| 4.2 | Improve tcpdump output parsing | Current parsing extracts "packets captured/received/dropped" counts and heuristic TTL/checksum via regex. Add more robust parsing for multiple packets, ICMP type correlation, and per-packet TTL. | `backend/app/packet_lab.py` (`_parse_tcpdump_ttl`, `_parse_tcpdump_checksum`); `backend/app/lab_adapter.py` (`capture_packets`) | Backend engineer | High |
| 4.3 | Add capture result persistence | Store capture results (pcap or parsed output) so the frontend can display historical captures, not just the last simulation. | `backend/app/packet_lab.py` (`LabOperationResult`); new storage layer | Backend engineer | Medium |
| 4.4 | Add capture filter configuration | Allow the frontend to specify capture filters (e.g. specific ICMP types, host filters) rather than hardcoded `icmp`. | `backend/app/lab_adapter.py` (`capture_packets`); `backend/app/packet_lab_routes.py` (`SimulateRequestModel`) | Backend engineer | Medium |
| 4.5 | Add pcap export option | Option to download the raw capture as a pcap file for offline analysis with Wireshark/tcpdump. | `backend/app/lab_adapter.py`; `backend/app/packet_lab_routes.py` | Backend engineer | Low |

---

## 5. Frontend Integration

Frontend changes needed to support a usable Packet Lab.

| # | Task | Description | Dependencies | Likely File Ownership | Priority |
|---|------|-------------|--------------|----------------------|----------|
| 5.1 | Verify frontend type alignment | Ensure `frontend/src/types/routing.ts` matches the backend Pydantic models after any backend changes (run `npm run generate:api` or manually sync). | `backend/app/packet_lab_routes.py`; `frontend/src/types/api.generated.ts`; `frontend/src/types/routing.ts` | Frontend engineer | High |
| 5.2 | Add privilege-unavailable UI state | The `VirtualLabPanel` already handles 503/unavailable. Ensure it shows actionable remediation (e.g. "Configure passwordless sudo" or "Build the lab first") rather than a generic error. | `frontend/src/components/VirtualLabPanel.tsx`; `frontend/src/api/routing.ts` (`checkLabStatus`) | Frontend engineer | High |
| 5.3 | Add lab build/teardown buttons | The panel already has Build/Tear down buttons backed by `applyScenarioLab`/`teardownScenarioLab`. Verify they work with the scenario lab endpoints and map to `rl260-*` namespace lifecycle. | `frontend/src/api/routing.ts` (`applyScenarioLab`, `teardownScenarioLab`); backend scenario lab routes | Frontend engineer | High |
| 5.4 | Display capture evidence | Show raw tcpdump output, packet counts, and per-check provenance (observed vs inferred) in the test result view. | `frontend/src/components/VirtualLabPanel.tsx` (verification details already rendered); backend verification_details | Frontend engineer | Medium |
| 5.5 | Add capture export/download | Button to download pcap or capture text for offline analysis. | Backend pcap export endpoint (4.5); frontend download handler | Frontend engineer | Low |
| 5.6 | Add polling for lab status | Poll `/api/lab/status` periodically so the UI reflects lab state changes (built/torn-down by another user or process). | `frontend/src/api/routing.ts` (`checkLabStatus`); `App.tsx` polling pattern | Frontend engineer | Low |

---

## 6. Automated Verification

Tests to add. All tests must run without root where possible; integration tests requiring real namespaces are gated.

| # | Task | Description | Dependencies | Likely File Ownership | Priority |
|---|------|-------------|--------------|----------------------|----------|
| 6.1 | Add topology validation unit tests | Test that `_validate_request` rejects out-of-topology source/destination IPs and accepts lab IPs. | `backend/app/packet_lab.py` (`_validate_request`); `backend/tests/test_packet_lab.py` | Backend engineer | High |
| 6.2 | Add parameter usage tests | Test that `protocol`/`ttl`/`length` parameters either affect packet generation or are removed from the contract. No test should pass if they are accepted but ignored. | `backend/app/packet_lab.py` (`simulate`); `backend/app/lab_adapter.py` (`ping`, `capture_packets`); `backend/tests/test_packet_lab.py` | Backend engineer | High |
| 6.3 | Add privilege-unavailable integration test | Test that `/api/lab/status` returns 503 with a clear message when pkexec/sudo is unavailable (already partially covered by `test_packet_lab_integration.py`). | `backend/tests/test_packet_lab_integration.py` | Backend engineer | High |
| 6.4 | Add real-namespace integration test (gated) | End-to-end test: build namespaces, ping, capture, verify TTL/checksum/route. Skip when no root or namespaces absent. | Namespaces provisioned (1.3); `backend/tests/test_packet_lab_integration.py` | Backend engineer | High |
| 6.5 | Add startup privilege check test | Test that the backend refuses to serve lab requests when privilege escalation is not configured non-interactively. | `backend/app/main.py` startup; `backend/app/lab_adapter.py` | Backend engineer | Medium |
| 6.6 | Add error categorization tests | Test that timeout → 408, permission denied → 403/503, invalid request → 400/422, lab unavailable → 503. | `backend/app/packet_lab_routes.py`; `backend/tests/test_packet_lab.py` | Backend engineer | Medium |
| 6.7 | Add frontend contract test | Verify frontend types match backend OpenAPI schema after backend changes. | `frontend/src/types/api.generated.ts`; `frontend/src/types/routing.ts`; `frontend/package.json` (`generate:api` script) | Frontend engineer | Medium |
| 6.8 | Add CI gate for packet lab | CI job that runs packet lab tests and fails on privilege-unavailable regressions. | `.github/workflows/ci.yml` | DevOps / backend engineer | Medium |

---

## 7. Final Acceptance Criteria

How we will know the Packet Lab is genuinely usable.

| Criterion | How to verify |
|-----------|---------------|
| **C1** — `/api/lab/status` returns 200 with `available: true` when namespaces exist and privileges are configured | Call the endpoint on a host with `rl260-*` namespaces and passwordless sudo/capabilities configured |
| **C2** — `/api/lab/status` returns 503 with an honest, actionable error when privileges or namespaces are missing | Call the endpoint on a host without privileges; error names the specific problem (not a generic "unavailable") |
| **C3** — `/api/lab/simulate` with `192.168.10.2` → `192.168.20.2` returns `capture_verified: true` and `state: completed` | Run simulation against live namespaces; tcpdump captures packets on router egress interface |
| **C4** — `/api/lab/simulate` with out-of-topology IPs returns 400/422 immediately without touching namespaces | Send request with `source_ip=8.8.8.8`; verify rejection before any namespace operation |
| **C5** — No request hangs indefinitely due to interactive pkexec/sudo | Every namespace operation completes within the configured timeout or returns "privilege unavailable" |
| **C6** — Verification fields report provenance | `ttl_decremented`, `checksum_valid`, `route_matched` each carry `provenance` of `observed` (from capture) or `inferred` (from ping) — never fabricated |
| **C7** — Frontend builds/tears down lab and runs a test packet end-to-end | `VirtualLabPanel` can build a scenario lab, send a packet, and display capture results |
| **C8** — All packet lab tests pass in CI without root | Unit tests pass; integration tests requiring root are skipped gracefully |
| **C9** — Backend does not run as root by default | Verify process runs as non-root user; privileges escalated only per-command via sudo/capabilities |
| **C10** — Documentation reflects the chosen privilege option | `docs/packet-lab-privileges.md` updated to record which option (sudoers or capabilities) was implemented |

---

## Dependency Ordering

```
Critical blockers (1.1–1.4) → Backend changes (2.1–2.7) → Environment (3.1–3.6)
                                          ↓
                              Packet capture (4.1–4.5) → Frontend (5.1–5.6)
                                          ↓
                              Automated verification (6.1–6.8)
                                          ↓
                              Final acceptance (C1–C10)
```

Critical blockers must be complete before any live-lab testing. Backend changes 2.1–2.4 are prerequisites for meaningful simulation. Frontend work can proceed in parallel with backend changes 2.5–2.7 and capture integration 4.1–4.5, but frontend integration testing requires a live backend.

---

## File Ownership Summary

| File | Owner | Role |
|------|-------|------|
| `backend/app/lab_adapter.py` | Backend engineer | Privileged namespace operations (pkexec/sudo, ip netns exec, ping, tcpdump) |
| `backend/app/packet_lab.py` | Backend engineer | Packet lab controller, state machine, verification with provenance |
| `backend/app/packet_lab_routes.py` | Backend engineer | FastAPI endpoints: `/api/lab/status`, `/api/lab/simulate` |
| `backend/app/lab_builder.py` | Backend engineer | Namespace build/teardown command generation and execution |
| `backend/app/main.py` | Backend engineer | FastAPI app, middleware, startup, router registration |
| `backend/app/security.py` | Backend engineer | Target validation, rate limiting |
| `backend/tests/test_packet_lab.py` | Backend engineer | Unit tests for adapter, controller, routes |
| `backend/tests/test_packet_lab_integration.py` | Backend engineer | Integration tests (no-fabrication guarantee) |
| `docs/packet-lab-privileges.md` | Backend engineer / sysadmin | Privilege requirements documentation |
| `frontend/src/components/VirtualLabPanel.tsx` | Frontend engineer | Lab lifecycle UI (build/test/teardown/display) |
| `frontend/src/api/routing.ts` | Frontend engineer | API client: `checkLabStatus`, `simulatePacket`, `applyScenarioLab`, `teardownScenarioLab` |
| `frontend/src/types/routing.ts` | Frontend engineer | TypeScript types synced to backend OpenAPI |
| `frontend/src/types/api.generated.ts` | Frontend engineer | Generated OpenAPI types |
| `frontend/vite.config.ts` | Frontend engineer | Dev server proxy to backend |
| `.github/workflows/ci.yml` | DevOps | CI pipeline for tests |
| `/etc/sudoers.d/routelens` | Sysadmin | Passwordless sudo rule for `ip netns exec` |
| Host namespaces `rl260-*` | Sysadmin | Provisioned lab environment |
