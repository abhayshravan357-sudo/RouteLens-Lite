# RouteLens — Autonomous Run Log

**Branch**: `integration/baseline-2026-10-20`  
**Tag**: `baseline-verified-2026-10-20` (`86c57ff`)  
**Last Updated**: 2026-10-20

---

## Run Summary

| Metric | Value |
|---|---|
| Backend tests | **290 passed, 1 skipped** |
| Frontend build | ✅ passes |
| TypeScript | ✅ clean |
| `git diff --check` | ✅ clean |
| Commits this run | 11 |
| Skipped tests | 1 (root-only simulation-versus-lab) |

---

## Completed Tasks

### TASK-601: Scenario Engine ✅ `08074e2`
- `backend/app/scenario.py` — models, longest-prefix lookup, trace with six outcomes
- `backend/app/scenarios_data.py` — 5 scenarios
- `backend/app/lab_builder.py` — namespace commands, dry-run, root guard, probe
- `backend/app/scenario_routes.py` — `/api/scenarios/*`
- 48 tests

### TASK-602: Diagnostic Security Hardening ✅ `08074e2`
- `backend/app/security.py` — `validate_target()`, `RateLimiter`
- CORS narrowed from `*` to a localhost allowlist
- Rate limiting on all diagnostic endpoints
- `ping` and `traceroute` receive `--` before the target
- 59 tests

### TASK-603: Cleanups ✅ `08074e2`
- `datetime.now(timezone.utc)` replaces deprecated `utcnow()`
- `pytest.ini` sets the asyncio fixture loop scope
- StreamWriter mock no longer leaves an un-awaited coroutine
- Full suite runs with **zero warnings**

### TASK-701: Scenario Picker + Trace UI ✅ `2f6b3dd`
- Step-through journey with start/previous/next/replay controls
- Per-hop route, prefix, next hop, interface, metric, source
- Losing candidates listed so the choice is explainable

### TASK-702: Provenance Badges + Compare-with-Lab ✅ `417c3c7`
- Prediction and reality side by side
- No verdict invented when the lab is unavailable

### TASK-703: Evidence-Based Topology Map ✅ `10a8942`
- Observed host data and simulated scenario data never merged
- Links between observed nodes are inferred, not observed
- Verified live against the real host: `wlp2s0`, gateway `192.168.0.1`, two neighbours

### TASK-704: Route Editing That Changes the Simulation ✅ `930cb53`
- Edits stored in a workspace, not the shared scenario
- Verified live: router switched from `10.0.0.0/24 (connected)` to `10.0.0.2/32 (static, metric 5)`

### TASK-801: Learning Lab Exercises ✅ `182c257`
- 7 guided exercises, each verified by running the real engine
- Six-part teaching pattern: what it is, why it matters, what happens, analogy, try it, check it
- Edit exercises apply a suggested route for real, then re-check
- 19 tests pass

### TASK-901/902: Authorised Host Discovery ✅ `4f1541b`
- Scope validated, previewed and confirmed before any probe
- Rate limited, cancellable, with a full audit trail
- 24 tests pass
- Verified live: found the real gateway at 192.168.0.1

### Fixes
- `/packet-journey` was missing from the Vite proxy, so the older Packet
  Journey UI could not reach the backend in development. Fixed.

---

## Live Verification Performed

| Scenario | Result |
|----------|--------|
| Frontend serves | ✅ `<title>RouteLens Lite</title>` |
| Backend health | ✅ `{"status":"ok","service":"RouteLens Lite API"}` |
| Scenarios through the Vite proxy | ✅ 5 scenarios |
| Multi-router trace | ✅ 4 hops: client → r1 → r2 → server |
| Loop detection | ✅ detected at r1 with an explanation |
| Compare without root | ✅ `agree: null`, honest reason |
| Topology from real host | ✅ 8 nodes, 5 edges, provenance correct |
| Route edit changes the trace | ✅ verified before/after |
| Learning Lab exercises | ✅ 7 exercises, checked via the proxy |
| Discovery guards | ✅ 403 without confirmation, 400 on a wide scope |
| Real discovery | ✅ found the real gateway 192.168.0.1 |
| Full journey through the proxy | ✅ all 8 areas |
| Lab status | 503 "Lab not ready" — honest, namespaces not visible unprivileged |

---

## Skipped Tests

| Test | Reason |
|------|--------|
| `test_simulation_matches_reality` | Needs root to build network namespaces |

---

## Remaining Risks

| Risk | Mitigation |
|------|------------|
| The lab has never been exercised end to end | Needs one `sudo` run of the lab apply/teardown |
| `network_collector.py` is ~1800 lines | Refactor when a second consumer appears |
| No browser-level automation | `docs/e2e-test-plan.md` describes the manual journey |
| The `feature/autonomous-engineering` worktree duplicates main | Archive once its unique parts are extracted |
| `agent/routing-backend` holds a parallel `/trace` implementation | Decide whether to keep one or both |

---

## Next Batch

1. **One privileged lab run** — needs explicit authorization for `sudo ip netns`
2. **Archive the autonomous-engineering worktree** — ORANGE, needs approval
3. **`agent/routing-backend` decision** — its `/trace` endpoint duplicates `/packet-journey`
4. **Browser-level check** — the flows are verified at API level, not in a browser

---

## Checkpoint

**Resume point**: `integration/baseline-2026-10-20` @ `8b64ee7`, working tree clean.

**State**: Phases 0–9 complete. 290 tests pass, build clean, app running and verified
through the Vite proxy. 28 API endpoints registered. `main` untouched at `03f347b`.

**Next action**: Obtain authorization for a privileged lab run, or archive the
duplicate autonomous-engineering worktree.
