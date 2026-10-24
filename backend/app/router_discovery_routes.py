"""
RouteLens Lite - Router Discovery API Endpoints.

Provides REST API routes for router discovery:
- POST /api/router-discovery/runs: start a discovery run
- GET /api/router-discovery/runs/{run_id}: get run status and results
- POST /api/router-discovery/runs/{run_id}/cancel: cancel a run
- GET /api/router-discovery/audit: audit trail of executed commands
- GET /api/router-discovery/runs/{run_id}/graph: graph visualization
- GET /api/router-discovery/runs/{run_id}/devices/{device_id}: device details
- GET /api/router-discovery/runs/{run_id}/devices/{device_id}/routes: device routes
- GET /api/router-discovery/runs/{run_id}/findings: analysis findings
- POST /api/router-discovery/runs/{run_id}/trace: packet trace
- GET /api/router-discovery/diff: diff two runs
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import re
import socket
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Union

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from pydantic import BaseModel, Field

from app.router_discovery.analysis import analyse, build_fib, _next_hop_chain, _owner_index
from app.router_discovery.collectors.base import (
    CommandNotAllowed,
    MAX_AUDIT_ENTRIES,
    check_command,
    command_problem,
    redact,
)
from app.router_discovery.engine import (
    DEFAULT_MAX_DEPTH,
    DEFAULT_MAX_DEVICES,
    CollectionFailure,
    DiscoveryResult,
    _address_of,
    _candidates,
    in_scope,
)
from app.router_discovery.graph import build_edges
from app.router_discovery.models import (
    DeviceSnapshot,
    Edge,
    IfaceInfo,
    Neighbor,
    RouteEntry,
)
from app.router_discovery.state import AUDIT, CLIENT_RUN_COUNTS, RUNS

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/router-discovery", tags=["Router Discovery"])

MAX_RUNS_PER_CLIENT = 10
FORBIDDEN_CREDENTIAL_KEYS = ("password", "community", "private_key", "token", "secret")


class TraceRequest(BaseModel):
    source: str
    destination: str


def _record_audit(target: str, argv: List[str], outcome: str, error: Optional[str] = None) -> None:
    """Record an executed command in the audit trail."""
    raw_cmd = " ".join(argv)
    redacted_cmd = redact(raw_cmd)
    redacted_error = redact(error) if error else None

    # Never record forbidden credential words
    for kw in FORBIDDEN_CREDENTIAL_KEYS:
        if kw in redacted_cmd.lower():
            redacted_cmd = re.sub(re.escape(kw) + r"\s*[=:]\s*\S+", f"{kw}=***", redacted_cmd, flags=re.I)

    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "target": target,
        "device": target,
        "command": redacted_cmd,
        "outcome": outcome,
        "error": redacted_error,
    }
    AUDIT.append(entry)
    while len(AUDIT) > MAX_AUDIT_ENTRIES:
        AUDIT.pop(0)


def _validate_scope_networks(scope_input: Any) -> List[str]:
    """Parse and validate scope networks, returning a list of valid CIDR strings."""
    if isinstance(scope_input, str):
        raw_list = [scope_input]
    elif isinstance(scope_input, dict):
        raw_list = list(scope_input.get("allowed_networks") or [])
    elif isinstance(scope_input, (list, tuple)):
        raw_list = list(scope_input)
    else:
        raise HTTPException(status_code=400, detail="Invalid scope format")

    if not raw_list:
        raise HTTPException(status_code=400, detail="A scope is required")

    networks = []
    for item in raw_list:
        text = str(item).strip()
        try:
            net = ipaddress.ip_network(text, strict=False)
            networks.append(str(net))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid network in scope {text!r}: {exc}")

    return networks


async def _run_command_async(argv: List[str]) -> tuple[int, bytes, bytes]:
    """Run a subprocess command via asyncio.create_subprocess_exec.

    A missing executable is reported as a non-zero return code with an
    error message, not as an unhandled exception that crashes the request.
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        return -1, b"", f"Command not found: {argv[0]}".encode("utf-8")
    stdout, stderr = await proc.communicate()
    return proc.returncode or 0, stdout, stderr


async def _collect_device_async(
    target: str,
    methods: List[str],
) -> tuple[Optional[DeviceSnapshot], Optional[str]]:
    """Collect information from a single device target."""
    hostname = ""
    errors: List[str] = []
    interfaces: List[IfaceInfo] = []
    routes: List[RouteEntry] = []
    neighbors: List[Neighbor] = []

    # 1. Read hostname
    argv_hn = ["hostname"]
    code_hn, stdout_hn, stderr_hn = await _run_command_async(argv_hn)
    _record_audit(target, argv_hn, "success" if code_hn == 0 else "error", stderr_hn.decode("utf-8", "replace") if code_hn != 0 else None)
    if code_hn == 0:
        hn_text = stdout_hn.decode("utf-8", "replace").strip()
        if hn_text:
            hostname = hn_text.splitlines()[0].strip()

    # 2. Read LLDP
    argv_lldp = ["lldpcli", "show", "neighbors", "-f", "json"]
    code_lldp, stdout_lldp, stderr_lldp = await _run_command_async(argv_lldp)
    _record_audit(target, argv_lldp, "success" if code_lldp == 0 else "error", stderr_lldp.decode("utf-8", "replace") if code_lldp != 0 else None)
    if code_lldp == 0:
        try:
            lldp_doc = json.loads(stdout_lldp.decode("utf-8", "replace") or "[]")
            if isinstance(lldp_doc, list):
                for item in lldp_doc:
                    if not isinstance(item, dict):
                        continue
                    if "lldp" in item and isinstance(item["lldp"], dict):
                        chassis = item["lldp"].get("chassis") or {}
                        port = item["lldp"].get("port") or {}
                        remote_name = chassis.get("name") or chassis.get("mac")
                        remote_mac = chassis.get("mac")
                        if not hostname and chassis.get("name"):
                            hostname = chassis["name"]
                        neighbors.append(
                            Neighbor(
                                local_if=port.get("ifname") or port.get("id"),
                                remote_name=remote_name,
                                remote_if=port.get("id"),
                                remote_mac=remote_mac,
                                via="lldp",
                            )
                        )
                    else:
                        local_if = item.get("localInterface") or item.get("ifname")
                        for n in item.get("neighbors") or []:
                            if isinstance(n, dict):
                                neighbors.append(
                                    Neighbor(
                                        local_if=local_if,
                                        remote_name=n.get("host") or n.get("systemName"),
                                        remote_if=n.get("port") or n.get("remotePort"),
                                        via="lldp",
                                    )
                                )
        except Exception as exc:
            errors.append(f"Failed to parse LLDP JSON: {exc}")
    else:
        err_msg = stderr_lldp.decode("utf-8", "replace").strip() or "lldp failed"
        errors.append(err_msg)

    # 3. Read routes
    argv_rt = ["ip", "-j", "route"]
    code_rt, stdout_rt, stderr_rt = await _run_command_async(argv_rt)
    _record_audit(target, argv_rt, "success" if code_rt == 0 else "error", stderr_rt.decode("utf-8", "replace") if code_rt != 0 else None)
    if code_rt == 0:
        try:
            rt_doc = json.loads(stdout_rt.decode("utf-8", "replace") or "[]")
            if isinstance(rt_doc, list):
                for item in rt_doc:
                    if isinstance(item, dict):
                        dst = item.get("dst") or "default"
                        prefix = "0.0.0.0/0" if dst == "default" else dst
                        if "/" not in prefix:
                            prefix = f"{prefix}/32"
                        gw = item.get("gateway")
                        routes.append(
                            RouteEntry(
                                prefix=prefix,
                                next_hop=gw,
                                interface=item.get("dev"),
                                metric=item.get("metric", 0),
                                protocol=item.get("protocol", "static"),
                                selected=True,
                            )
                        )
        except Exception as exc:
            errors.append(f"Failed to parse route JSON: {exc}")

    # 4. Read ARP / neighbors
    argv_ng = ["ip", "-j", "neigh"]
    code_ng, stdout_ng, stderr_ng = await _run_command_async(argv_ng)
    _record_audit(target, argv_ng, "success" if code_ng == 0 else "error", stderr_ng.decode("utf-8", "replace") if code_ng != 0 else None)
    if code_ng == 0:
        try:
            ng_doc = json.loads(stdout_ng.decode("utf-8", "replace") or "[]")
            if isinstance(ng_doc, list):
                for item in ng_doc:
                    if isinstance(item, dict):
                        if "arp" in item and isinstance(item["arp"], dict):
                            arp = item["arp"]
                            neighbors.append(
                                Neighbor(
                                    local_if="eth0",
                                    remote_mac=arp.get("remote", {}).get("mac"),
                                    via="arp",
                                )
                            )
                        elif item.get("dst"):
                            neighbors.append(
                                Neighbor(
                                    local_if=item.get("dev"),
                                    remote_ip=item.get("dst"),
                                    remote_mac=item.get("lladdr"),
                                    via="arp",
                                )
                            )
        except Exception as exc:
            errors.append(f"Failed to parse neighbor JSON: {exc}")

    # 5. Read interfaces
    argv_if = ["ip", "-j", "addr"]
    code_if, stdout_if, stderr_if = await _run_command_async(argv_if)
    _record_audit(target, argv_if, "success" if code_if == 0 else "error", stderr_if.decode("utf-8", "replace") if code_if != 0 else None)
    if code_if == 0:
        try:
            if_doc = json.loads(stdout_if.decode("utf-8", "replace") or "[]")
            if isinstance(if_doc, list):
                for item in if_doc:
                    if isinstance(item, dict):
                        addrs = []
                        for addr_info in item.get("addr_info") or []:
                            local = addr_info.get("local")
                            plen = addr_info.get("prefixlen")
                            if local and plen:
                                addrs.append(f"{local}/{plen}")
                        interfaces.append(
                            IfaceInfo(
                                name=item.get("ifname", "eth0"),
                                addresses=addrs,
                                up="UP" in item.get("flags", []),
                            )
                        )
        except Exception:
            pass

    # If the primary discovery method (LLDP) failed with an error, record failure
    if code_lldp != 0 and any("lldp" in m.lower() for m in methods):
        primary_reason = errors[0] if errors else "Collection failed"
        return None, primary_reason

    # If all commands failed
    if code_hn != 0 and code_lldp != 0 and code_rt != 0 and code_ng != 0:
        primary_reason = errors[0] if errors else "Connection failed"
        return None, primary_reason

    dev_id = hostname or str(target)
    snapshot = DeviceSnapshot(
        device_id=dev_id,
        hostname=hostname or dev_id,
        mgmt_target=str(target),
        method="local",
        collected_at=datetime.now(timezone.utc),
        interfaces=interfaces,
        routes=routes,
        neighbors=neighbors,
        errors=errors,
    )
    return snapshot, None


async def _execute_discovery_run(run_id: str) -> None:
    """Execute discovery breadth-first in the background."""
    run = RUNS.get(run_id)
    if not run:
        return

    scope = run["scope_networks"]
    seeds = run["seeds"]
    max_depth = run["max_depth"]
    max_devices = run["max_devices"]
    methods = run["methods"]

    collected: List[DeviceSnapshot] = []
    seen_addresses: Set[str] = set()
    seen_device_ids: Set[str] = set()
    failures: List[Dict[str, Any]] = []
    progress: List[str] = run.setdefault("progress", [])

    from collections import deque
    queue: deque[tuple[str, int]] = deque()

    for s in seeds:
        queue.append((s, 0))

    stopped_reason: Optional[str] = None

    while queue:
        target, depth = queue.popleft()

        if not in_scope(target, scope):
            continue

        if depth > max_depth:
            continue

        if len(collected) >= max_devices:
            stopped_reason = f"stopped at the device limit of {max_devices}"
            progress.append(f"stopped at the device limit of {max_devices}; {target} was not collected")
            break

        if target in seen_addresses:
            continue
        seen_addresses.add(target)

        snapshot, failure_reason = await _collect_device_async(target, methods)
        if failure_reason is not None or snapshot is None:
            reason = failure_reason or "Unknown collection error"
            failures.append({
                "target": target,
                "reason": reason,
                "depth": depth,
            })
            progress.append(f"could not collect {target}: {reason}")
            # Add placeholder device marked as failed
            failed_dev = {
                "id": str(target),
                "device_id": str(target),
                "hostname": str(target),
                "addresses": [str(target)],
                "provenance": "observed",
                "collection_failed": True,
                "failure_reason": reason,
                "routes": None,
                "interfaces": [],
                "depth": depth,
            }
            run.setdefault("devices", []).append(failed_dev)
            continue

        if snapshot.device_id in seen_device_ids:
            progress.append(f"skipped {target}: it is {snapshot.device_id}, which was already collected")
            continue

        seen_device_ids.add(snapshot.device_id)
        collected.append(snapshot)
        progress.append(f"collected {snapshot.device_id} at {target}")

        dev_dict = {
            "id": snapshot.device_id,
            "device_id": snapshot.device_id,
            "hostname": snapshot.hostname or snapshot.device_id,
            "addresses": [str(target)],
            "provenance": "observed",
            "collection_failed": False,
            "failure_reason": None,
            "routes": [r.model_dump() for r in snapshot.routes],
            "interfaces": [i.model_dump() for i in snapshot.interfaces],
            "depth": depth,
        }
        run.setdefault("devices", []).append(dev_dict)

        if depth >= max_depth:
            candidates = _candidates(snapshot)
            has_more = any(c not in seen_addresses and in_scope(c, scope) for c in candidates)
            if has_more:
                stopped_reason = f"stopped at the depth limit of {max_depth}"
                progress.append(f"stopped at the depth limit of {max_depth}")
            continue

        for cand in _candidates(snapshot):
            if cand not in seen_addresses and in_scope(cand, scope):
                queue.append((cand, depth + 1))

    # Build edges
    raw_edges = build_edges(collected)
    edge_dicts = []
    for e in raw_edges:
        edge_dicts.append({
            "a": e.a,
            "b": e.b,
            "source": e.a,
            "target": e.b,
            "kind": e.kind,
            "provenance": e.provenance,
            "evidence": e.evidence,
            "basis": e.evidence,
        })
    run["edges"] = edge_dicts

    # Run analysis for findings
    analysis_report = analyse(collected, unreached=failures, edges=raw_edges)
    run["findings"] = [f.model_dump() for f in analysis_report.findings]

    run["failures"] = failures
    run["stopped_reason"] = stopped_reason
    run["complete"] = stopped_reason is None and len(failures) == 0

    if not collected and failures:
        run["status"] = "failed"
    elif stopped_reason:
        run["status"] = "stopped"
    else:
        run["status"] = "completed"


@router.post("/runs")
async def start_run(request: Request, background_tasks: BackgroundTasks):
    """Start a new router discovery run."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Body must be an object")

    # Refuse credentials in request
    for key in FORBIDDEN_CREDENTIAL_KEYS:
        if key in body:
            raise HTTPException(status_code=400, detail=f"The API never accepts credentials in a request: {key!r}")

    # Check client concurrent runs
    client_id = request.headers.get("x-client-id") or (request.client.host if request.client else "unknown")
    count = CLIENT_RUN_COUNTS.get(client_id, 0)
    if count >= MAX_RUNS_PER_CLIENT:
        raise HTTPException(status_code=429, detail="Too many concurrent runs for this client")
    CLIENT_RUN_COUNTS[client_id] = count + 1

    # Scope validation
    if "scope" not in body:
        raise HTTPException(status_code=400, detail="A scope is required")

    scope_networks = _validate_scope_networks(body["scope"])

    # Methods validation & command guard
    raw_methods = body.get("methods") or ["lldp"]
    if not isinstance(raw_methods, list):
        raise HTTPException(status_code=400, detail="Methods must be a list")

    for m in raw_methods:
        text = str(m).strip()
        if text.lower() in ("lldp", "cdp", "frr", "snmp", "local"):
            continue
        problem = command_problem(text)
        if problem:
            raise HTTPException(status_code=400, detail=f"Refusing command {text!r}: {problem}")

    # Seeds validation
    raw_seeds = body.get("seeds") or []
    if not isinstance(raw_seeds, list) or not raw_seeds:
        raise HTTPException(status_code=400, detail="Seeds are required")

    resolved_seeds: List[str] = []
    for s in raw_seeds:
        text = str(s).strip()
        if not text:
            continue
        # Try as IP address first
        try:
            ipaddress.ip_address(text)
            resolved_ip = text
        except ValueError:
            # Hostname: resolve via socket.getaddrinfo
            try:
                addrinfo = socket.getaddrinfo(text, None)
                resolved_ip = addrinfo[0][4][0]
            except Exception as exc:
                raise HTTPException(status_code=400, detail=f"Could not resolve seed hostname {text!r}: {exc}")

        # Check in scope
        if not in_scope(resolved_ip, scope_networks):
            raise HTTPException(
                status_code=400,
                detail=f"Seed {text} (resolved to {resolved_ip}) is outside the scope",
            )
        resolved_seeds.append(resolved_ip)

    max_depth = int(body.get("max_depth", DEFAULT_MAX_DEPTH))
    max_devices = int(body.get("max_devices", DEFAULT_MAX_DEVICES))

    run_id = f"run-{uuid.uuid4().hex[:12]}"
    run_entry: Dict[str, Any] = {
        "run_id": run_id,
        "client_id": client_id,
        "status": "running",
        "complete": False,
        "scope_networks": scope_networks,
        "seeds": resolved_seeds,
        "max_depth": max_depth,
        "max_devices": max_devices,
        "methods": raw_methods,
        "devices": [],
        "edges": [],
        "findings": [],
        "failures": [],
        "progress": [],
        "stopped_reason": None,
    }
    RUNS[run_id] = run_entry

    background_tasks.add_task(_execute_discovery_run, run_id)

    return {
        "run_id": run_id,
        "status": "running",
        "complete": False,
        "devices": [],
        "edges": [],
        "findings": [],
        "failures": [],
        "audit": [],
        "progress": [],
        "stopped_reason": None,
    }


def _check_owner(run: Dict[str, Any], request: Request) -> None:
    client_id = request.headers.get("x-client-id") or (request.client.host if request.client else "unknown")
    if run.get("client_id") != client_id:
        raise HTTPException(status_code=403, detail="Forbidden: access denied to this run")


@router.get("/runs/{run_id}")
async def get_run(run_id: str, request: Request):
    """Get the status, devices, edges, and findings of a run."""
    run = RUNS.get(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    _check_owner(run, request)

    # Return response adhering to contract
    return {
        "run_id": run.get("run_id"),
        "status": run.get("status"),
        "complete": run.get("complete", False),
        "devices": run.get("devices", []),
        "edges": run.get("edges", []),
        "findings": run.get("findings", []),
        "failures": run.get("failures", []),
        "audit": [a for a in AUDIT if any(s in a.get("target", "") for s in run.get("seeds", []))],
        "stopped_reason": run.get("stopped_reason"),
        "progress": run.get("progress", []),
    }


@router.post("/runs/{run_id}/cancel")
async def cancel_run(run_id: str, request: Request):
    """Cancel an active discovery run."""
    run = RUNS.get(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    _check_owner(run, request)

    run["status"] = "cancelled"
    run["complete"] = False
    run["stopped_reason"] = "cancelled by user"
    return {"status": "cancelled", "run_id": run_id}


@router.get("/audit")
async def get_audit():
    """Get the audit trail of executed commands."""
    return {"entries": list(AUDIT)}


@router.get("/runs/{run_id}/graph")
async def get_run_graph(run_id: str, request: Request):
    """Get graph visualization nodes and edges for a run."""
    run = RUNS.get(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    _check_owner(run, request)
    return {
        "nodes": run.get("devices", []),
        "edges": run.get("edges", []),
    }


@router.get("/runs/{run_id}/findings")
async def get_run_findings(run_id: str, request: Request):
    """Get findings for a run."""
    run = RUNS.get(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    _check_owner(run, request)
    return {"findings": run.get("findings", [])}


@router.get("/runs/{run_id}/devices/{device_id}")
async def get_run_device(run_id: str, device_id: str, request: Request):
    """Get a single device from a run."""
    run = RUNS.get(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    _check_owner(run, request)
    for d in run.get("devices", []):
        if d.get("id") == device_id or d.get("device_id") == device_id or d.get("hostname") == device_id:
            return d
    raise HTTPException(status_code=404, detail=f"Device {device_id} not found")


@router.get("/runs/{run_id}/devices/{device_id}/routes")
async def get_run_device_routes(run_id: str, device_id: str, request: Request):
    """Get routes of a device from a run."""
    run = RUNS.get(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    _check_owner(run, request)
    for d in run.get("devices", []):
        if d.get("id") == device_id or d.get("device_id") == device_id:
            return {"routes": d.get("routes") or []}
    raise HTTPException(status_code=404, detail=f"Device {device_id} not found")


def _snapshot_from_run_device(device_dict: dict) -> DeviceSnapshot:
    """Rebuild a DeviceSnapshot from a run's stored device dict."""
    interfaces = [
        IfaceInfo(
            name=str(item.get("name", "eth0")),
            addresses=[str(a) for a in (item.get("addresses") or [])],
            up=bool(item.get("up", True)),
        )
        for item in (device_dict.get("interfaces") or [])
    ]
    routes = [
        RouteEntry(
            prefix=str(item.get("prefix", "")),
            next_hop=item.get("next_hop"),
            interface=item.get("interface"),
            metric=item.get("metric"),
            protocol=item.get("protocol", "static"),
            admin_distance=item.get("admin_distance"),
            selected=bool(item.get("selected", True)),
        )
        for item in (device_dict.get("routes") or [])
    ]
    addresses = device_dict.get("addresses") or []
    mgmt_target = str(addresses[0]).split("/")[0] if addresses else str(
        device_dict.get("device_id") or device_dict.get("id") or ""
    )
    return DeviceSnapshot(
        device_id=str(device_dict.get("device_id") or device_dict.get("id") or ""),
        hostname=str(device_dict.get("hostname") or device_dict.get("device_id") or ""),
        mgmt_target=mgmt_target,
        method="local",
        collected_at=datetime.now(timezone.utc),
        interfaces=interfaces,
        routes=routes,
        neighbors=[],
        errors=[],
        provenance="observed",
    )


def _first_address_of_snapshot(device: DeviceSnapshot) -> str:
    """The first owned address of a device, or its device id."""
    for interface in device.interfaces:
        for address in interface.addresses:
            text = str(address).split("/")[0].strip()
            try:
                ipaddress.ip_address(text)
                return text
            except ValueError:
                continue
    return device.device_id


def _find_device_in_run(run: Dict[str, Any], identifier: str) -> Optional[dict]:
    """Find a stored device dict by device id, hostname, or owned address."""
    for d in run.get("devices", []):
        if (
            d.get("device_id") == identifier
            or d.get("id") == identifier
            or d.get("hostname") == identifier
        ):
            return d
    for d in run.get("devices", []):
        for address in d.get("addresses") or []:
            if str(address).split("/")[0].strip() == identifier:
                return d
    return None


@router.post("/runs/{run_id}/trace")
async def trace_run(run_id: str, request: Request):
    """Trace the forwarding path from a source to a destination within a run."""
    run = RUNS.get(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    _check_owner(run, request)

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Body must be an object")

    source = str(body.get("source", "")).strip()
    destination = str(body.get("destination", "")).strip()
    if not source or not destination:
        raise HTTPException(status_code=400, detail="source and destination are required")

    devices = [_snapshot_from_run_device(d) for d in run.get("devices", [])]
    if not devices:
        raise HTTPException(status_code=404, detail="No devices in run")

    owner_by_address = _owner_index(devices)
    by_id = {d.device_id: d for d in devices}

    start = by_id.get(source) or next(
        (d for d in devices if d.hostname == source), None
    )
    if start is None:
        start = owner_by_address.get(source)
    if start is None:
        raise HTTPException(
            status_code=404, detail=f"Source {source!r} not found in run"
        )

    target_device = by_id.get(destination) or next(
        (d for d in devices if d.hostname == destination), None
    )
    if target_device is not None:
        target_address = _first_address_of_snapshot(target_device)
        target_device_id = target_device.device_id
    else:
        target_address = destination
        target_device_id = owner_by_address.get(destination)
        target_device_id = target_device_id.device_id if target_device_id else None

    fib_by_device = {d.device_id: build_fib(d.routes) for d in devices}
    chain, looped = _next_hop_chain(
        fib_by_device,
        owner_by_address,
        start,
        target_address,
        target_device_id=target_device_id,
    )

    reached_target = (
        target_device_id is not None
        and chain
        and chain[-1] == target_device_id
    )

    return {
        "run_id": run_id,
        "source": source,
        "destination": destination,
        "path": chain,
        "complete": not looped,
        "looped": looped,
        "reached_target": reached_target,
        "hops": max(0, len(chain) - 1),
    }


@router.get("/diff")
async def diff_runs(request: Request):
    """Diff two runs: devices, edges, and findings."""
    run_a_id = request.query_params.get("a") or request.query_params.get("run_a")
    run_b_id = request.query_params.get("b") or request.query_params.get("run_b")
    if not run_a_id or not run_b_id:
        raise HTTPException(
            status_code=400, detail="run_a and run_b query parameters are required"
        )

    run_a = RUNS.get(run_a_id)
    run_b = RUNS.get(run_b_id)
    if not run_a:
        raise HTTPException(status_code=404, detail=f"Run {run_a_id} not found")
    if not run_b:
        raise HTTPException(status_code=404, detail=f"Run {run_b_id} not found")
    _check_owner(run_a, request)
    _check_owner(run_b, request)

    devices_a = {
        d.get("device_id") or d.get("id"): d for d in run_a.get("devices", [])
    }
    devices_b = {
        d.get("device_id") or d.get("id"): d for d in run_b.get("devices", [])
    }

    added_devices = [devices_b[k] for k in devices_b if k not in devices_a]
    removed_devices = [devices_a[k] for k in devices_a if k not in devices_b]
    changed_devices = [
        {"device_id": k, "run_a": devices_a[k], "run_b": devices_b[k]}
        for k in devices_a
        if k in devices_b and devices_a[k] != devices_b[k]
    ]

    edges_a = run_a.get("edges", [])
    edges_b = run_b.get("edges", [])
    key_a = {(e.get("a"), e.get("b"), e.get("kind")): e for e in edges_a}
    key_b = {(e.get("a"), e.get("b"), e.get("kind")): e for e in edges_b}
    added_edges = [key_b[k] for k in key_b if k not in key_a]
    removed_edges = [key_a[k] for k in key_a if k not in key_b]

    def finding_key(finding: dict) -> tuple:
        return (
            finding.get("kind"),
            finding.get("title"),
            tuple(sorted(str(d) for d in (finding.get("devices") or []))),
        )

    findings_a = run_a.get("findings", [])
    findings_b = run_b.get("findings", [])
    fkey_a = {finding_key(f): f for f in findings_a}
    fkey_b = {finding_key(f): f for f in findings_b}
    added_findings = [fkey_b[k] for k in fkey_b if k not in fkey_a]
    removed_findings = [fkey_a[k] for k in fkey_a if k not in fkey_b]

    identical = (
        not added_devices
        and not removed_devices
        and not changed_devices
        and not added_edges
        and not removed_edges
        and not added_findings
        and not removed_findings
    )

    return {
        "run_a": run_a_id,
        "run_b": run_b_id,
        "identical": identical,
        "devices": {
            "added": added_devices,
            "removed": removed_devices,
            "changed": changed_devices,
            "common": len(set(devices_a) & set(devices_b)),
        },
        "edges": {
            "added": added_edges,
            "removed": removed_edges,
            "common": len(set(key_a) & set(key_b)),
        },
        "findings": {
            "added": added_findings,
            "removed": removed_findings,
            "common": len(set(fkey_a) & set(fkey_b)),
        },
    }
