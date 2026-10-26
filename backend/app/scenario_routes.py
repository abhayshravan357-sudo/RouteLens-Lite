"""
RouteLens Lite - Scenario API Endpoints

FastAPI routes for scenario management, packet tracing, and the
simulation-versus-lab comparison.
"""

import copy
import uuid
from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.scenario import Route, Scenario, TraceResult, trace
from app.topology import TopologyGraph, build_topology
from app.exercise_checks import ExerciseState
from app import lab_builder as lab
from app.scenarios_data import SCENARIOS

router = APIRouter(prefix="/api/scenarios", tags=["scenarios"])


#: Exercises live under their own prefix so they are easy to find.
exercise_router = APIRouter(prefix="/api/exercises", tags=["exercises"])


#: Edited scenarios, kept per workspace so a route change can be traced
#: again without letting one user's edit change everyone's scenario.
#: Bounded so it cannot grow without limit.
_WORKSPACES: Dict[str, Scenario] = {}
_MAX_WORKSPACES = 50


def _store_workspace(scenario: Scenario) -> str:
    """Save an edited scenario and return its workspace id."""
    if len(_WORKSPACES) >= _MAX_WORKSPACES:
        # Drop the oldest entry rather than refusing the edit.
        oldest = next(iter(_WORKSPACES))
        del _WORKSPACES[oldest]
    workspace_id = uuid.uuid4().hex[:12]
    _WORKSPACES[workspace_id] = scenario
    return workspace_id


def _resolve_scenario(sid: str, workspace: Optional[str]) -> Scenario:
    """The scenario to operate on: a workspace copy if given, else the shared one."""
    if workspace:
        edited = _WORKSPACES.get(workspace)
        if edited is None:
            raise HTTPException(status_code=404, detail="Unknown or expired workspace")
        return edited
    return _scenario(sid)


class TraceRequest(BaseModel):
    """Request to trace a packet through a scenario."""

    src: str = Field(..., description="Source node id")
    dst: str = Field(..., description="Destination IP address")
    workspace: Optional[str] = Field(
        None, description="Workspace id returned by a route edit, if any"
    )


class ScenarioSummary(BaseModel):
    """Summary of a scenario."""

    id: str
    title: str


class RouteUpdate(BaseModel):
    """Replacement route list for a node."""

    routes: List[dict] = Field(..., description="Route objects: prefix, dev, via, metric")


class LinkStateUpdate(BaseModel):
    """Request to toggle a link's physical/logical state (UP/DOWN)."""

    link_a: str = Field(..., description="First endpoint as 'node:iface'")
    link_b: str = Field(..., description="Second endpoint as 'node:iface'")
    is_up: bool = Field(..., description="Desired link state (True=UP, False=DOWN)")
    workspace: Optional[str] = Field(
        None, description="Existing workspace id if continuing an experiment"
    )


class ExerciseCheckRequest(BaseModel):
    """Request to check whether an exercise is complete."""

    scenario_id: str = Field(..., description="Scenario the exercise belongs to")
    workspace: Optional[str] = Field(
        None, description="Workspace id returned by a route edit, if any"
    )


class LabResult(BaseModel):
    """Result of a lab command run."""

    status: str
    log: Optional[List[dict]] = None
    commands: Optional[List[str]] = None
    reason: Optional[str] = None
    failed_at: Optional[List[str]] = None


class CompareResult(BaseModel):
    """Simulation compared against the real lab."""

    simulated: dict
    lab: dict
    agree: Optional[bool] = None
    hops_match: Optional[bool] = None
    failure_match: Optional[bool] = None
    note: str


def _scenario(sid: str) -> Scenario:
    """Fetch a scenario or raise 404."""
    if sid not in SCENARIOS:
        raise HTTPException(status_code=404, detail=f"Scenario not found: {sid}")
    return SCENARIOS[sid]


@router.get("", response_model=List[ScenarioSummary])
def list_scenarios():
    """List all available scenarios."""
    return [{"id": s.id, "title": s.title} for s in SCENARIOS.values()]


@router.get("/{sid}")
def get_scenario(sid: str):
    """Full definition of one scenario."""
    return _scenario(sid).model_dump()


@router.post("/{sid}/trace", response_model=TraceResult)
def trace_route(sid: str, req: TraceRequest):
    """
    Trace a packet from a source node to a destination address.

    The trace is produced by the same scenario definition that the lab builder
    uses, so simulation and reality stay comparable.

    Passing a workspace id traces the edited copy, so a route change is
    reflected in the next simulation.
    """
    import ipaddress

    scenario = _resolve_scenario(sid, req.workspace)
    try:
        ipaddress.ip_address(req.dst)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Invalid destination IP: {req.dst}")

    if req.src not in {n.id for n in scenario.nodes}:
        raise HTTPException(status_code=404, detail=f"Unknown source node: {req.src}")

    return trace(scenario, req.src, req.dst)


@router.put("/{sid}/nodes/{nid}/routes")
def set_routes(sid: str, nid: str, update: RouteUpdate):
    """
    Replace the static routes of a node.

    Works on a copy so that a malformed request cannot corrupt the shared
    scenario registry. The updated scenario is returned along with a
    workspace id; pass that id to the trace endpoint to see the effect of
    the edit.
    """
    scenario = _scenario(sid)
    working = scenario.model_copy(deep=True)

    try:
        node = working.node(nid)
    except ValueError:
        raise HTTPException(status_code=404, detail=f"Unknown node: {nid}")

    try:
        node.routes = [Route(**r) for r in update.routes]
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Invalid route data: {exc}")

    # Re-validate the whole scenario so bad edits are rejected up front.
    try:
        working = Scenario.model_validate(working.model_dump())
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Invalid scenario after edit: {exc}")

    workspace_id = _store_workspace(working)
    return {
        "scenario": working.model_dump(),
        "workspace": workspace_id,
    }


@router.put("/{sid}/links")
def set_link_state(sid: str, update: LinkStateUpdate):
    """
    Toggle a link between UP and DOWN in an isolated workspace.

    Identifies the link by its endpoints (a and b in either direction),
    updates only a copy of the scenario in a workspace, and returns the
    updated workspace id. The shared scenario definition is never corrupted.
    """
    base_scenario = _resolve_scenario(sid, update.workspace)
    working = base_scenario.model_copy(deep=True)

    link_found = False
    for link in working.links:
        endpoints = {link.a, link.b}
        if endpoints == {update.link_a, update.link_b}:
            link.is_up = update.is_up
            link_found = True
            break

    if not link_found:
        raise HTTPException(
            status_code=404,
            detail=f"Link {update.link_a} <-> {update.link_b} not found in scenario {sid}",
        )

    workspace_id = _store_workspace(working)
    return {
        "scenario": working.model_dump(),
        "workspace": workspace_id,
        "link_a": update.link_a,
        "link_b": update.link_b,
        "is_up": update.is_up,
    }


@router.post("/{sid}/lab/apply", response_model=LabResult)
def apply_lab(sid: str, dry_run: bool = True):
    """
    Create the namespaces for a scenario.

    Defaults to a dry run that only reports the commands. Executing for real
    requires root and is refused otherwise.
    """
    scenario = _scenario(sid)
    try:
        commands = lab.build_commands(scenario)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Invalid scenario: {exc}")
    return lab.run_all(commands, dry_run=dry_run)


@router.post("/{sid}/lab/teardown", response_model=LabResult)
def teardown_lab(sid: str, dry_run: bool = True):
    """Remove the namespaces for a scenario.

    Uses run_teardown so that missing namespaces (already torn down) are
    treated as an idempotent success rather than a failure.
    """
    scenario = _scenario(sid)
    return lab.run_teardown(lab.teardown_commands(scenario), dry_run=dry_run)


@router.post("/{sid}/compare", response_model=CompareResult)
def compare(sid: str, req: TraceRequest):
    """
    Compare the simulated trace with a real probe from the lab.

    When the lab is unavailable the agreement field is null; no result is
    invented to make the comparison look conclusive.
    """
    scenario = _resolve_scenario(sid, req.workspace)
    simulated = trace(scenario, req.src, req.dst)
    real = lab.probe(req.src, req.dst)

    agree: Optional[bool] = None
    hops_match: Optional[bool] = None
    failure_match: Optional[bool] = None
    if real.get("status") != "unavailable":
        agree = (simulated.status == "delivered") == (real.get("status") == "delivered")
        hops_match = None
        if not agree:
            def _failure_category(status: str) -> str:
                if status == "delivered":
                    return "delivered"
                if status in (
                    "no_route",
                    "unresolved_next_hop",
                    "link_down",
                    "not_forwarding",
                    "unreachable",
                ):
                    return "unreachable"
                if status in ("loop", "max_hops", "timeout"):
                    return "loop_or_timeout"
                if status == "permission_denied":
                    return "permission"
                return "other"

            sim_cat = _failure_category(simulated.status)
            real_cat = _failure_category(real.get("status", ""))
            failure_match = sim_cat == real_cat

    return {
        "simulated": simulated.model_dump(),
        "lab": real,
        "agree": agree,
        "hops_match": hops_match,
        "failure_match": failure_match,
        "note": (
            "agree=null means the lab was unavailable; no result was faked. "
            "hops_match=null because a single-packet probe reports no hop count. "
            "failure_match compares broad failure categories when both sides fail."
        ),
    }


@router.get("/{sid}/topology", response_model=TopologyGraph)
async def get_topology(sid: str, workspace: Optional[str] = None):
    """
    Build a topology graph for a scenario from two kinds of evidence.

    The scenario contributes simulated devices and links. The real host
    contributes observed interfaces, routes and neighbours, plus the
    relationships inferred between them.

    Every node and edge carries its own provenance so the client can
    colour them differently and the user can tell measured from modelled.
    """
    scenario = _resolve_scenario(sid, workspace)
    return await build_topology(scenario)


# ---------------------------------------------------------------------------
# Learning Lab exercises
# ---------------------------------------------------------------------------


@exercise_router.get("")
def list_exercises():
    """List the guided exercises."""
    from app.exercises import exercise_list
    return exercise_list()


@exercise_router.get("/{exercise_id}")
def get_exercise(exercise_id: str):
    """The full explanation and instructions for one exercise."""
    from app.exercises import get_exercise as _get

    exercise = _get(exercise_id)
    if exercise is None:
        raise HTTPException(status_code=404, detail=f"Unknown exercise: {exercise_id}")

    return exercise.model_dump()


@exercise_router.post("/{exercise_id}/check", response_model=ExerciseState)
async def check_exercise(exercise_id: str, body: ExerciseCheckRequest):
    """
    Check whether an exercise has been completed.

    The check runs the real routing engine against the scenario, so an
    exercise is only complete when the engine's own output satisfies it.

    A workspace may be supplied so the student's route edits are the
    ones that get checked.
    """
    from app.exercise_checks import check_exercise as _check
    from app.exercises import get_exercise as _get

    if _get(exercise_id) is None:
        raise HTTPException(status_code=404, detail=f"Unknown exercise: {exercise_id}")

    scenario = _resolve_scenario(body.scenario_id, body.workspace)
    state = _check(exercise_id, scenario)
    if state is None:
        raise HTTPException(status_code=404, detail=f"Unknown exercise: {exercise_id}")
    return state
