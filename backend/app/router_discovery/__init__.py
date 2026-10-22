"""
RouteLens Lite - Router discovery.

Reads real routers over the management plane and maps the network they
describe. The map never contains a device, a route, a neighbour, a link
or a finding that was not actually read.

This package is called router_discovery, and is deliberately not called
discovery: the application already has a discovery module for the
authorised host sweep, and a second package with that name would
shadow it.
"""

from app.router_discovery.models import (
    DeviceSnapshot,
    Edge,
    IfaceInfo,
    Neighbor,
    RouteEntry,
)
from app.router_discovery.state import (
    AUDIT,
    CLIENT_RUN_COUNTS,
    CREDENTIALS,
    RUNS,
    run_methods,
)

_runs = RUNS
_audit = AUDIT
runs = RUNS
audit = AUDIT

__all__ = [
    "DeviceSnapshot",
    "Edge",
    "IfaceInfo",
    "Neighbor",
    "RouteEntry",
    "RUNS",
    "AUDIT",
    "_runs",
    "_audit",
    "runs",
    "audit",
    "CREDENTIALS",
    "run_methods",
    "CLIENT_RUN_COUNTS",
]
