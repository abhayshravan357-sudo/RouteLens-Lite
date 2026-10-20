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
from app import lab_builder as lab
from app.scenarios_data import SCENARIOS

router = APIRouter(prefix="/api/scenarios", tags=["scenarios"])


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


@router.post("/{sid}/lab/apply", response_model=LabResult)
def apply_lab(sid: str, dry_run: bool = True):
    """
    Create the namespaces for a scenario.

    Defaults to a dry run that only reports the commands. Executing for real
    requires root and is refused otherwise.
    """
    scenario = _scenario(sid)
    return lab.run_all(lab.build_commands(scenario), dry_run=dry_run)


@router.post("/{sid}/lab/teardown", response_model=LabResult)
def teardown_lab(sid: str, dry_run: bool = True):
    """Remove the namespaces for a scenario."""
    scenario = _scenario(sid)
    return lab.run_all(lab.teardown_commands(scenario), dry_run=dry_run, stop_on_error=False)


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
    if real.get("status") != "unavailable":
        agree = (simulated.status == "delivered") == (real.get("status") == "delivered")

    return {
        "simulated": simulated.model_dump(),
        "lab": real,
        "agree": agree,
        "note": "agree=null means the lab was unavailable; no result was faked.",
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
