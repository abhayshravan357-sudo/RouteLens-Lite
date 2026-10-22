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

__all__ = [
    "DeviceSnapshot",
    "Edge",
    "IfaceInfo",
    "Neighbor",
    "RouteEntry",
]
