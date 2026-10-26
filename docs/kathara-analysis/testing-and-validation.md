# Kathará Test Architecture Analysis vs RouteLens Lite

**Project:** RouteLens Lite × Kathará analysis
**Author:** AGENT 4 — QA / TestPilot investigator
**Status:** Read-only investigation (no existing tests modified, nothing installed)
**Kathará reference:** `reference-repos/Kathara/Kathara-main/` (GPL-3.0)
**RouteLens:** `/home/abhaysawant/Desktop/cn_project_2` (MIT)
**Deliverable:** `docs/kathara-analysis/testing-and-validation.md`

---

## 1. Executive summary

Kathará is a GPL-3.0 container-based network emulation tool with a pytest-based test suite organised by domain (`tests/model/`, `tests/parser/`, plus CLI/manager/utils). RouteLens Lite is an MIT FastAPI + React app with pytest/pytest-asyncio/httpx/Playwright tests under `backend/tests/` and a single Playwright accessibility spec under `frontend/tests/`.

Key contrast: Kathará's parser tests parse **real fixture files** and assert parsed structure and raised errors; RouteLens relies heavily on **hardcoded mock JSON** injected through `conftest.py` (`mock_environment_network_if_empty`) and `AsyncMock` patching, so several report/collector tests pass with simulated data rather than proving real host discovery.

RouteLens has GitHub Actions CI (`backend`, `frontend`, `browser`, `whitespace` jobs). Kathará has **no CI workflows** (only `FUNDING.yml`, issue/PR templates).

Licence note: Kathará is GPL-3.0; RouteLens is MIT. This document takes **architecture inspiration only** — no test code, fixtures, or assertions are copied, so there is no licence contamination risk.

---

## 2. Kathará test architecture (reference behaviour)

### 2.1 Layout

| Directory | Contents |
|---|---|
| `tests/model/lab_test.py` | Lab creation, machines, links, interfaces, metadata, external links, dependencies |
| `tests/model/machine_test.py` | Machine meta (sysctl/env/port/ulimit/volume), image/mem/cpu, interface add/remove, `check()` |
| `tests/model/interface_test.py` | Interface construction + MAC-address validation errors |
| `tests/model/external_link_test.py` | ExternalLink creation, VLAN truncation, full name |
| `tests/model/filesystem_mixin_test.py` | `fs_type`, `fs_path`, create/update file from string/list/path/stream, `write_line_before/after`, `delete_line` |
| `tests/model/lab_filesystem_mixin_test.py` | Startup/shutdown file creation delegated to FilesystemMixin (mocks the mixin methods) |
| `tests/parser/lab_parser_test.py` | Parses real `tests/parser/labconf/*` fixtures; structure + error cases |
| `tests/parser/dep_parser_test.py` | Parses real `tests/parser/labdep/*` fixtures; dependency loops |
| `tests/parser/ext_parser_test.py` | Parses real `tests/parser/labext/*` fixtures; external links + malformed/IO errors |
| `tests/parser/option_parser_test.py` | Option parsing + syntax errors |
| `tests/parser/folder_parser_test.py` | Parses real `tests/parser/labfolder/*` fixtures; shared-folder ignore |
| `tests/types_test.py`, `tests/utils_test.py` | Small type/utility assertions |
| `tests/cli/`, `tests/manager/`, `tests/webhooks/` | Additional domain test dirs |

### 2.2 Test config

`pyproject.toml` (`reference-repos/Kathara/Kathara-main/pyproject.toml`):
- `[project.optional-dependencies] test = ["pytest"]` — pytest is an optional test extra
- No `[tool.pytest.ini_options]` section
- `setup.cfg` holds metadata only (no pytest config)
- No `pytest.ini`/`conftest.py` at repo root

### 2.3 Test style (Kathará reference patterns)

- **Fixtures**: `default_scenario`, `temporary_path`, `directory_scenario`, `default_device`, `default_link`; settings mocked via `@mock.patch("src.Kathara.setting.Setting.Setting.get_instance")`.
- **Real-data parsing**: parser tests read actual fixture files (`tests/parser/labconf/one_device`, etc.) and assert parsed machine/link/interface/meta structure — verifying the parser behaves on real input, not just response shape.
- **Error contracts**: `pytest.raises(MachineAlreadyExistsError, MachineCollisionDomainError, InterfaceMacAddressError, SyntaxError, ValueError, ...)` used throughout to pin behaviour.
- **State assertions**: tests assert post-conditions (machines dict length, interface numbering, MAC address, meta contents) rather than only HTTP response structure.
- **In-memory filesystem**: `fs.open_fs("mem://")` used so file-mixin tests run without touching disk.
- **No CI**: `.github/` contains only `FUNDING.yml`, `ISSUE_TEMPLATE/`, `PULL_REQUEST_TEMPLATE.md`; no workflows.

### 2.4 Representative reference behaviours

| Behaviour | Kathará location |
|---|---|
| Parser asserts parsed structure from real fixture files | `tests/parser/lab_parser_test.py:9` (`test_one_device` asserts `lab.machines['pc1'].interfaces[0].link.name == 'A'`) |
| Parser asserts raised error on bad input | `tests/parser/lab_parser_test.py:46` (`test_one_device_same_collision_domain_error` raises `MachineCollisionDomainError`) |
| Machine meta sysctl validation | `tests/model/machine_test.py:161` (`test_add_meta_sysctl_not_net_exception` raises `MachineOptionError`) |
| Interface MAC validation | `tests/model/interface_test.py:62` (`test_iface_mac_address_error_short` raises `InterfaceMacAddressError`) |
| Filesystem mixin in-memory fs | `tests/model/filesystem_mixin_test.py:31` (`test_fs_type_mem` uses `mem://`) |
| Settings mocked for config-dependent tests | `tests/model/lab_test.py:22` (`@mock.patch("src.Kathara.setting.Setting.Setting.get_instance")`) |

---

## 3. RouteLens test architecture (current behaviour)

### 3.1 Layout

| File | Purpose |
|---|---|
| `backend/tests/conftest.py` | Shared fixtures + autouse `mock_environment_network_if_empty` injecting hardcoded MOCK_IPV4_ROUTES/MOCK_IPV6_ROUTES/MOCK_IPV4_NEIGHBORS when real `ip` commands return empty |
| `backend/tests/test_health.py` | `/health` endpoint status + response structure |
| `backend/tests/test_routing_logic.py` | Pure unit tests for `select_best_route`/`find_matching_routes`/`lookup_route` (all `Provenance.SIMULATED`) |
| `backend/tests/test_routing_table.py` | Routing table persistence/lookup |
| `backend/tests/test_packet_journey.py` | Packet journey simulation + provenance |
| `backend/tests/test_network_collector.py` | `NetworkCollector` using mocked `ip addr`/`ip route`/`ip neigh` JSON fixtures |
| `backend/tests/test_report.py` | Report sections, evidence provenance, limitations, markdown rendering |
| `backend/tests/test_diagnostic_security.py` | Diagnostic endpoint injection rejection, rate limiting, CORS |
| `backend/tests/test_security.py` | `validate_target`, `RateLimiter`, shared `diagnostic_limiter` |
| `backend/tests/test_security_filter.py` | Differential testing of `reject_unsafe_target_chars` vs original implementation |
| `backend/tests/test_e2e_browser.py` | Playwright browser tests against live backend + frontend |
| `frontend/tests/a11y.spec.ts` | Single Playwright axe WCAG AA accessibility spec |

### 3.2 Test config

`backend/pytest.ini`:
- `testpaths = tests`, `asyncio_mode = strict`, `filterwarnings` for `pkg_resources` DeprecationWarning
- No `pyproject.toml`/`setup.cfg` in `backend/`

`backend/tests/conftest.py` (key fixture, read-only observation):
- `mock_environment_network_if_empty` (autouse, runs for `test_report`): patches `NetworkCollector._run_command` to return hardcoded `MOCK_IPV4_ROUTES`/`MOCK_IPV6_ROUTES`/`MOCK_IPV4_NEIGHBORS` when real commands return empty output.

### 3.3 Test style (RouteLens current patterns)

- **Mocked command output**: `AsyncMock`/`patch.object(collector, "_run_command", ...)` used in `test_network_collector.py`, `test_neighbour_names.py`, `test_packet_lab.py`, `test_router_discovery_contract.py`, `test_router_discovery.py`.
- **Hardcoded fixtures**: `MOCK_IPV4_ROUTES` etc. in `conftest.py`; hand-built snapshot fixtures in `test_router_discovery.py` / `test_router_discovery_contract.py`.
- **Differential/security tests**: `test_security_filter.py` compares against a re-implemented "original" `validate_target` (strong); `test_security.py`/`test_diagnostic_security.py` cover injection, rate limiting, CORS (strong).
- **Simulated routing**: `test_routing_logic.py` explicitly uses `Provenance.SIMULATED` and verifies longest-prefix/metric/interface tiebreakers (appropriate for simulation, clearly marked).
- **Response-structure tests**: `test_health.py` has two tests that largely duplicate each other, checking status/shape only.
- **Browser tests**: `test_e2e_browser.py` spins up backend + frontend; `frontend/tests/a11y.spec.ts` runs axe against `http://localhost:3000`.

### 3.4 CI

`.github/workflows/ci.yml`: `backend` (pytest), `frontend` (npm ci + build), `browser` (Playwright, continue-on-error), `whitespace` (git diff --check). Python 3.12, Node 22.

---

## 4. Comparison table (required format)

Each row maps a RouteLens item to the Kathará reference and proposes a concrete improvement.

| Field | Required information |
|---|---|
| **RouteLens location** | `backend/tests/conftest.py:50` — `mock_environment_network_if_empty` fixture |
| **Kathará location** | `tests/model/filesystem_mixin_test.py:31` — uses `fs.open_fs("mem://")` in-memory fs; no injected mock host data |
| **Current behaviour** | Autouse fixture patches `NetworkCollector._run_command` to return hardcoded `MOCK_IPV4_ROUTES`/`MOCK_IPV6_ROUTES`/`MOCK_IPV4_NEIGHBORS` whenever real `ip` commands return empty, so report honesty tests pass with fabricated host data |
| **Reference behaviour** | Kathará tests use an in-memory filesystem (`mem://`) for file-mixin tests and real fixture files for parser tests; they never inject fake host networking data to make assertions pass |
| **Improvement** | Split the conftest fixture: keep mocking only for *unit* parsing tests; for report honesty, either run against real `ip` output on the host or skip/gracefully degrade when no real interfaces exist, and assert provenance == "observed" only when real command output was used |
| **Compatibility** | Fits pytest + pytest-asyncio stack; no new package |
| **Dependencies** | None (uses existing `ip` command via `NetworkCollector._run_command`) |
| **Licence** | Architecture inspiration only; no code copied from GPL-3.0 Kathará → no MIT contamination |
| **Risk** | Low regression risk if mocking is scoped to unit tests; removing the report mock may surface empty-output handling bugs (intentional — that is the gap being closed) |
| **Priority** | Critical |

| Field | Required information |
|---|---|
| **RouteLens location** | `backend/tests/test_report.py:18`–`90` — `TestReportContent` (sections, evidence provenance, limitations, simulated marking) |
| **Kathará location** | `tests/parser/lab_parser_test.py:9` — parses real fixture files and asserts parsed structure |
| **Current behaviour** | Asserts evidence carries `source`/`collected_at`/provenance and that teaching table/scenarios are `provenance == "simulated"`, but relies on `conftest.py` hardcoded mock data when real commands return empty, so it does not prove displayed host data is real |
| **Reference behaviour** | Kathará parser tests verify behaviour on **real input files**, asserting exact parsed values (`lab.machines['pc1'].interfaces[0].link.name == 'A'`) |
| **Improvement** | Add a "real vs simulated evidence" test: run `build_report()` on a host with real interfaces and assert at least one machine-section evidence item has `provenance == "observed"` with a non-mocked `source`; keep the `simulated` assertions for the teaching/scenario sections |
| **Compatibility** | Fits existing `test_report.py` style |
| **Dependencies** | None |
| **Licence** | Inspiration only (assertion structure), no code reuse |
| **Risk** | Medium — on hosts with no real interfaces the new assertion would be skipped conditionally to avoid CI flakiness |
| **Priority** | Critical |

| Field | Required information |
|---|---|
| **RouteLens location** | `backend/tests/test_network_collector.py:31`–`120` — `mock_interfaces_json`/`mock_routes_json`/`mock_neighbors_json` fixtures |
| **Kathará location** | `tests/model/filesystem_mixin_test.py` — in-memory `mem://` filesystem for deterministic file tests |
| **Current behaviour** | Collector tests parse hardcoded JSON fixtures; verifies parsing logic, not actual `ip addr`/`ip route`/`ip neigh` execution |
| **Reference behaviour** | Kathará uses in-memory fs for file-mixin tests but parser tests read **real fixture files** from disk |
| **Improvement** | Add integration-style tests that run `NetworkCollector` against real `ip -j addr show` / `ip -j route show` / `ip -j neigh show` on the host when available, asserting at least one interface/route/neighbor is returned; keep fixture-based unit tests for malformed-output handling |
| **Compatibility** | Fits pytest stack; requires `ip` (iproute2) on the test host |
| **Dependencies** | System: `iproute2` (`ip` command) — typically present on Linux, absent in minimal containers |
| **Licence** | Inspiration only |
| **Risk** | Low; gate real-command tests behind a `pytest.mark.skipif(shutil.which("ip") is None)` |
| **Priority** | High |

| Field | Required information |
|---|---|
| **RouteLens location** | `backend/tests/test_health.py:14`–`57` — two overlapping health endpoint tests |
| **Kathará location** | `tests/model/lab_test.py:52` — `test_default_scenario_creation` asserts full post-creation state (name, machines, links, hash, fs_type, shared_path) |
| **Current behaviour** | Two tests check `/health` returns 200 and shape `{status, service}`; one is near-duplicate of the other; neither exercises behaviour beyond the endpoint contract |
| **Reference behaviour** | Kathará model tests assert complete object state after construction and mutation, including error cases |
| **Improvement** | Merge the two health tests into one contract test; add behaviour checks (e.g. health reflects `NetworkCollector` readiness, response time header, or dependency status) if such behaviour exists |
| **Compatibility** | Fits httpx ASGITransport pattern |
| **Dependencies** | None |
| **Licence** | Inspiration only |
| **Risk** | Low (removing a redundant test) |
| **Priority** | Medium |

| Field | Required information |
|---|---|
| **RouteLens location** | `backend/tests/test_routing_logic.py:16`–`48` — `select_best_route`/`find_matching_routes`/`lookup_route` unit tests |
| **Kathará location** | `tests/model/lab_test.py` — Lab/Machine/Link construction with state and error assertions |
| **Current behaviour** | Pure unit tests on simulated routing tables, all `Provenance.SIMULATED`; correctly marks simulation and verifies longest-prefix/metric/interface tiebreakers |
| **Reference behaviour** | Kathará has no routing-simulation equivalent (it emulates real containers); its model tests assert constructed object state |
| **Improvement** | Keep as-is for simulation correctness; add a companion test asserting that no `Provenance.OBSERVED` route ever originates from `select_best_route` (simulation/purity boundary test) |
| **Compatibility** | Fits existing unit-test style |
| **Dependencies** | None |
| **Licence** | Inspiration only |
| **Risk** | Low |
| **Priority** | Low |

| Field | Required information |
|---|---|
| **RouteLens location** | `backend/tests/test_e2e_browser.py` — Playwright browser tests against live backend + frontend |
| **Kathará location** | None (Kathará has no browser/e2e UI tests in `tests/`) |
| **Current behaviour** | End-to-end browser checks; `continue-on-error: true` in CI |
| **Reference behaviour** | N/A — Kathará is a backend emulation tool with no web UI |
| **Improvement** | Keep browser tests; make them non-`continue-on-error` once stable, and add frontend unit/contract tests (currently only `frontend/tests/a11y.spec.ts`) |
| **Compatibility** | Requires Chromium + Playwright in CI (already configured) |
| **Dependencies** | Playwright, Chromium with deps |
| **Licence** | N/A |
| **Risk** | Medium (browser tests are slow/flaky on 8GB RAM HDD) |
| **Priority** | Medium |

| Field | Required information |
|---|---|
| **RouteLens location** | `frontend/tests/a11y.spec.ts` — sole frontend test |
| **Kathará location** | None (no frontend) |
| **Current behaviour** | One Playwright axe WCAG AA accessibility spec against `http://localhost:3000` |
| **Reference behaviour** | N/A |
| **Improvement** | Add frontend component/API contract tests (Vitest or Playwright component) mirroring backend contract coverage |
| **Compatibility** | Fits Vite + Playwright frontend stack |
| **Dependencies** | Possibly `@vitejs/plugin-react` + testing-library (already has Playwright) |
| **Licence** | N/A |
| **Risk** | Low |
| **Priority** | Medium |

| Field | Required information |
|---|---|
| **RouteLens location** | `backend/tests/` overall — no parser/config round-trip tests |
| **Kathará location** | `tests/parser/lab_parser_test.py`, `dep_parser_test.py`, `ext_parser_test.py`, `option_parser_test.py`, `folder_parser_test.py` — parse real fixture files and assert structure + errors |
| **Current behaviour** | RouteLens has no equivalent parser test suite for any config/scenario file format it consumes |
| **Reference behaviour** | Kathará parser tests read real fixture files (`tests/parser/labconf/*`, `labdep/*`, `labext/*`, `labfolder/*`) and assert exact parsed structure and raised `SyntaxError`/`MachineCollisionDomainError`/`InterfaceMacAddressError` |
| **Improvement** | Add parser tests for RouteLens scenario/routing config ingestion using real sample files, asserting parsed structure and error cases |
| **Compatibility** | Fits pytest stack |
| **Dependencies** | None |
| **Licence** | Inspiration only (fixture-driven parser testing pattern), no code copied |
| **Risk** | Low |
| **Priority** | High |

| Field | Required information |
|---|---|
| **RouteLens location** | `.github/workflows/ci.yml` — RouteLens has CI; Kathará reference has none |
| **Kathará location** | `.github/` contains only `FUNDING.yml`, `ISSUE_TEMPLATE/`, `PULL_REQUEST_TEMPLATE.md`; no workflows |
| **Current behaviour** | RouteLens CI runs backend/frontend/browser/whitespace jobs; Kathará reference project runs no automated CI tests |
| **Reference behaviour** | N/A (Kathará has no CI to copy); the comparison direction is RouteLens → Kathará for CI |
| **Improvement** | (Not applicable to RouteLens; noted for completeness) RouteLens CI already exists and covers the test suite |
| **Compatibility** | N/A |
| **Dependencies** | N/A |
| **Licence** | N/A |
| **Risk** | N/A |
| **Priority** | Low |

---

## 5. Missing tests in RouteLens

1. **Parser/config round-trip tests** — Kathará has five parser test modules parsing real fixture files; RouteLens has none for any config/scenario format it reads. (High)
2. **Real host-discovery integration tests** — no test runs `ip addr`/`ip route`/`ip neigh` on the host and asserts real interfaces/routes/neighbors appear; collector tests use hardcoded JSON fixtures. (Critical)
3. **Real-vs-simulated evidence test** — no test proves that displayed machine data carries `provenance == "observed"` from real commands versus `simulated` for the teaching table. (Critical)
4. **Model-layer unit tests with fixtures** — Kathará-style Lab/Machine/Interface fixtures with state and error-contract assertions; RouteLens tests focus on API responses and mocked collectors. (High)
5. **Frontend unit/component tests** — only `frontend/tests/a11y.spec.ts` exists. (Medium)
6. **CI for the Kathará reference** — not a RouteLens gap; noted because the reference has no workflows while RouteLens does. (Low)

---

## 6. Weak tests (structure-only, not behaviour)

- `backend/tests/test_health.py`: two tests that duplicate each other, asserting only HTTP 200 and JSON shape `{status, service}`; no behaviour beyond the contract.
- `backend/tests/conftest.py:50` `mock_environment_network_if_empty`: injects hardcoded routes/neighbors so report tests pass even when the host has no real network data — the test validates structure, not that data came from real `ip` commands.
- `backend/tests/test_network_collector.py`: fixture-based parsing tests (mock_interfaces_json, etc.) verify parsing logic, not actual command execution.

---

## 7. Tests that do not verify actual network behaviour

| Test | What it actually verifies |
|---|---|
| `test_network_collector.py` (fixture tests) | JSON parsing of hardcoded `mock_interfaces_json`/`mock_routes_json`/`mock_neighbors_json`, not real `ip` output |
| `test_report.py` (report honesty) | Provenance field values and limitations presence, but evidence may come from `conftest.py` hardcoded mocks |
| `test_health.py` | Endpoint status and response shape only |
| `test_routing_logic.py` | Simulated-routing tiebreakers (correctly marked `Provenance.SIMULATED`, so this is intentional, not a weakness) |

---

## 8. Hardcoded data that can make tests pass incorrectly

`backend/tests/conftest.py:14–49` defines:
- `MOCK_IPV4_ROUTES` — default via `192.168.1.1` dev `eth0`
- `MOCK_IPV6_ROUTES` — `fe80::/64` dev `eth0`
- `MOCK_IPV4_NEIGHBORS` — `192.168.1.1` lladdr `00:11:22:33:44:55`

The autouse fixture `mock_environment_network_if_empty` (`conftest.py:50`) returns these whenever `NetworkCollector._run_command` returns empty stdout for `ip -j route show`, `ip -j -6 route show`, `ip -j neigh show`. This means `test_report.py` honesty tests can pass with entirely fabricated host data on a host with no real interfaces, masking empty-output handling bugs.

---

## 9. Do RouteLens tests prove displayed data is real vs simulated?

**No.** Current RouteLens tests assert the `provenance` field (e.g. teaching table == "simulated", machine section in `("observed", "unknown")`) but do not verify that `observed` data actually originated from real `ip addr`/`ip route`/`ip neigh` execution. The `conftest.py` mock injects fake data when real commands return empty, so a test can pass with `provenance == "observed"` while the underlying data is hardcoded. A test must run real commands (or skip when unavailable) and assert `source` references a real command to prove data is real.

---

## 10. Test strategy: separating real, simulated, mocked, external

Four categories with explicit boundaries:

### 10.1 Real host discovery (from `ip addr`, `ip route`, `ip neigh`, DNS)
- **Owner:** `NetworkCollector` (`app/network_collector.py`)
- **Test location:** new `backend/tests/test_network_collector_real.py` (or extend existing with gating)
- **Approach:** run `ip -j addr show`, `ip -j route show`, `ip -j neigh show` on the host when `shutil.which("ip")` exists; assert at least one interface/route/neighbor is parsed and `source` names the command; `pytest.mark.skipif` when `ip` is absent (containers/minimal hosts)
- **Provenance:** must be `observed` with non-empty `source`

### 10.2 Simulated network behaviour (RouteLens routing simulation)
- **Owner:** `app/routing_logic.py` (`select_best_route`, `find_matching_routes`, `lookup_route`)
- **Test location:** `backend/tests/test_routing_logic.py` (existing)
- **Approach:** unit tests with hand-built `RoutingEntry` tables, all `Provenance.SIMULATED`; assert longest-prefix/metric/interface tiebreakers; add a purity test asserting simulated selection never returns `Provenance.OBSERVED`
- **Provenance:** `simulated`

### 10.3 Mocked test data
- **Owner:** unit/parsing tests for malformed output, error contracts, security filters
- **Test location:** `backend/tests/test_network_collector.py` (fixtures), `test_security_filter.py`, `test_security.py`, `test_diagnostic_security.py`
- **Approach:** hardcoded JSON fixtures and `AsyncMock` patching of `_run_command`/`subprocess.Popen`; acceptable for parsing logic and injection/rate-limit/CORS contracts
- **Boundary:** mocks must never be used in report-honesty tests that claim data is real

### 10.4 External network diagnostics (ping, traceroute, DNS)
- **Owner:** diagnostic endpoints (`app/network_collector.py` connectivity/traceroute/dns-resolve)
- **Test location:** `backend/tests/test_diagnostic_security.py` (existing, security-focused)
- **Approach:** security tests already cover injection rejection, rate limiting, CORS. Add behaviour tests with mocked `subprocess` returning known ping/traceroute/DNS output, asserting parsing and provenance; do **not** perform real network probes in CI (external dependency, flaky, sandbox-restricted)
- **Provenance:** `observed` when real command ran, `unknown`/error otherwise

### 10.5 Test isolation rules
- Mocks in `conftest.py` must be scoped to unit/parsing tests, **not** report-honesty tests
- Any test asserting `provenance == "observed"` must be gated on real command availability
- `test_report.py` "simulated" assertions for teaching table/scenarios are correct and should be retained

---

## 11. License analysis

| Item | Licence | Reuse implication for RouteLens (MIT) |
|---|---|---|
| Kathará source/tests | GPL-3.0 | Strong copyleft; **no Kathará test code, fixtures, or assertions are copied** into RouteLens |
| This document's recommendations | — | Architecture/pattern inspiration only (fixture-driven parser tests, in-memory fs, pytest fixtures, error contracts); pattern ideas are not copyrightable expression |
| RouteLens code/tests | MIT | Permissive; adding new RouteLens tests inspired by Kathará patterns carries no GPL obligation |

**Conclusion:** Zero licence contamination risk. We borrow *architecture* (how tests are organised, what they assert), not *code*. No GPL-3.0 code enters the MIT RouteLens codebase.

---

## 12. Risk summary

| Area | Risk | Mitigation |
|---|---|---|
| Regression | Removing/altering `conftest.py` mock may break `test_report.py` on hosts with no real interfaces | Gate new real-command tests with `skipif`; keep existing mock only for unit tests |
| Security | Diagnostic endpoints invoke `ping`/`traceroute`/`dig` | Existing validation/rate-limit/CORS tests cover this; keep them, do not run real probes in CI |
| Maintenance | Browser tests slow/flaky on 8GB RAM HDD | Keep `continue-on-error` until stable; run browser job on push/PR only |
| Licence | Accidental GPL code copy | Do not copy Kathará code/fixtures; pattern inspiration only |
| Environment | `ip` command absent in minimal containers | `skipif(shutil.which("ip") is None)` on real-discovery tests |

---

## 13. Priority ranking

| Priority | Items |
|---|---|
| Critical | Real host-discovery integration test (run `ip` commands, assert real data, gate on availability); real-vs-simulated evidence test for `build_report()`; remove hardcoded mock injection from report-honesty path |
| High | Parser/config round-trip tests with real fixture files; model-layer unit tests with fixtures + error contracts |
| Medium | Merge duplicate `test_health.py` tests; add behaviour assertions to health; frontend component/API contract tests; stabilise browser tests (remove `continue-on-error`) |
| Low | Simulation-purity test for `test_routing_logic.py`; Kathará-side CI (out of scope for RouteLens) |

---

## 14. Recommended next steps (read-only investigation complete)

1. Create `backend/tests/test_network_collector_real.py` with `skipif`-gated real `ip addr`/`ip route`/`ip neigh` tests.
2. Add a `build_report()` real-vs-simulated evidence test asserting at least one observed evidence item with a real command `source` when interfaces exist.
3. Scope `conftest.py` `mock_environment_network_if_empty` to unit/parsing tests only (remove from report-honesty path).
4. Add parser tests for RouteLens config/scenario ingestion using real sample files.
5. Do **not** modify existing tests during this investigation (per constraints); implement new tests in a follow-up task.
