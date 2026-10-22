"""
RouteLens Lite - Discovery API

Endpoints for authorised host discovery.

Discovery reaches out to other machines, so it is guarded more tightly
than the read-only diagnostics:

- A scope is validated before anything is sent.
- The caller must confirm the scope, quoting it back, before a scan
  runs. This is a deliberate second step, not a formality.
- Every request, including refused ones, is written to the audit trail.
  The trail is bounded, so it cannot grow without limit, but refusals are
  never dropped to make room.
- A run is rate limited per client, because a single run probes up to a
  few hundred addresses with real packets and the endpoint is
  unauthenticated.
"""

from __future__ import annotations

import uuid
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.discovery import (
    AuditOutcome,
    DiscoveryScopeError,
    DiscoveryService,
    discovery_service,
    validate_scope,
)
from app.security import client_key, discovery_limiter

router = APIRouter(prefix="/api/discovery", tags=["discovery"])


class DiscoveryRequest(BaseModel):
    """Request to discover hosts on an authorized network.

    The target must be a CIDR network or a single address that the operator
    has explicitly authorized. The description makes clear this is a network‑
    scoped operation.
    """

    target: str = Field(
        ...,
        description="Network in CIDR notation, or a single address, to scan",
    )
    max_hosts: int = Field(256, ge=1, le=1024, description="Most addresses to probe")
    interval: float = Field(
        0.2, ge=0.05, le=10, description="Seconds to wait between probes"
    )
    timeout: float = Field(1.0, ge=0.1, le=10, description="Seconds to wait for a reply")
    confirmed: bool = Field(
        False,
        description=(
            "Must be true, and the confirmation must quote the target, "
            "before the scan runs"
        ),
    )
    confirmation: Optional[str] = Field(
        None,
        description="The target the operator typed back to confirm the scope",
    )


class DiscoveryResponse(BaseModel):
    """The result of a discovery run."""

    status: str
    hosts: List[dict] = Field(default_factory=list)
    addresses_probed: int = 0
    addresses_total: int = 0
    scope: dict = Field(default_factory=dict)
    duration_seconds: float = 0.0
    cancelled: bool = False
    scan_id: Optional[str] = None
    message: Optional[str] = None


@router.get("/audit")
def get_audit_trail():
    """Every discovery request that has been made, in order."""
    return [entry.to_dict() for entry in discovery_service.audit_trail]


@router.post("/scope", response_model=dict)
def preview_scope(request: DiscoveryRequest, http_request: Request):
    """
    Check a scope and describe it, without probing anything.

    This is the step before confirmation: it shows exactly what would be
    probed so the operator can agree to it.
    """
    discovery_limiter.check(client_key(http_request, "discovery-scope"))

    try:
        scope = validate_scope(
            target=request.target,
            max_hosts=request.max_hosts,
            interval=request.interval,
            timeout=request.timeout,
        )
    except DiscoveryScopeError as exc:
        discovery_service.record(
            target=request.target,
            outcome=AuditOutcome.REFUSED,
            reason=str(exc),
            confirmed=False,
        )
        raise HTTPException(status_code=400, detail=str(exc))

    return {
        "scope": scope.to_dict(),
        "addresses": scope.addresses(),
        "requires_confirmation": True,
    }


@router.post("/run", response_model=DiscoveryResponse)
async def run_discovery(request: DiscoveryRequest, http_request: Request):
    """
    Run an authorised discovery.

    The scope is validated, then the operator's confirmation is checked.
    Without a matching confirmation nothing is probed, and the refusal
    is recorded.

    A run probes real addresses with real packets, so it is rate limited
    per client. The limit is its own, not the diagnostic one, so a burst
    of lookups cannot use up a student's discovery allowance.
    """
    discovery_limiter.check(client_key(http_request, "discovery-run"))

    try:
        scope = validate_scope(
            target=request.target,
            max_hosts=request.max_hosts,
            interval=request.interval,
            timeout=request.timeout,
        )
    except DiscoveryScopeError as exc:
        discovery_service.record(
            target=request.target,
            outcome=AuditOutcome.REFUSED,
            reason=str(exc),
            confirmed=False,
        )
        raise HTTPException(status_code=400, detail=str(exc))

    # The operator must have confirmed the scope by quoting it back.
    if not request.confirmed or request.confirmation != request.target:
        discovery_service.record(
            target=request.target,
            outcome=AuditOutcome.REFUSED,
            reason="scope was not confirmed by the operator",
            confirmed=False,
        )
        raise HTTPException(
            status_code=403,
            detail=(
                "Discovery needs an explicit confirmation. Preview the scope, "
                "then confirm it by sending the same target back."
            ),
        )

    scan_id = uuid.uuid4().hex[:12]
    result = await discovery_service.discover(scope, scan_id)

    return DiscoveryResponse(
        status=result["status"],
        hosts=result["hosts"],
        addresses_probed=result["addresses_probed"],
        addresses_total=result["addresses_total"],
        scope=result["scope"],
        duration_seconds=result["duration_seconds"],
        cancelled=result["cancelled"],
        scan_id=scan_id,
        message=(
            f"{len(result['hosts'])} host(s) answered out of "
            f"{result['addresses_total']} address(es) probed."
        ),
    )


@router.post("/cancel")
def cancel_discovery(scan_id: str):
    """
    Ask a running scan to stop.

    A scan id that is not running is reported as such rather than being
    recorded as cancelled. Claiming a cancellation that never happened
    would be a false account of what the machine did.
    """
    ok = discovery_service.cancel(scan_id)
    if not ok:
        raise HTTPException(
            status_code=404,
            detail=f"No scan is running with that id. There was nothing to cancel.",
        )
    return {"cancelled": ok, "scan_id": scan_id}
