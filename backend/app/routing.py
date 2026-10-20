"""
RouteLens Lite - Routing Models

Defines the data models for routing table entries using Pydantic for validation.
"""

from enum import Enum
from ipaddress import IPv4Address, IPv4Network
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class NextHopType(str, Enum):
    """Type of next hop for a routing entry."""

    GATEWAY = "gateway"  # Next hop is a gateway IP address
    DIRECT = "direct"  # Directly connected network (no gateway needed)


class RoutingEntry(BaseModel):
    """
    A single routing table entry.

    Attributes:
        destination: The destination network in CIDR notation (e.g., "192.168.1.0/24")
        next_hop: The next hop IP address (required for gateway type)
        interface: The network interface name (e.g., "eth0")
        metric: Non-negative integer cost metric (lower is better)
        next_hop_type: Whether this is a gateway or direct connection
    """

    destination: str = Field(..., description="Destination network in CIDR notation (e.g., 192.168.1.0/24)")
    next_hop: Optional[str] = Field(None, description="Next hop gateway IP address")
    interface: str = Field(..., description="Network interface name (e.g., eth0)")
    metric: int = Field(..., ge=0, description="Non-negative integer metric (lower is better)")
    next_hop_type: NextHopType = Field(NextHopType.GATEWAY, description="Type of next hop: gateway or direct")

    @field_validator("destination")
    @classmethod
    def validate_destination(cls, v: str) -> str:
        """Validate that destination is a valid IPv4 CIDR network."""
        try:
            IPv4Network(v, strict=False)
        except ValueError as e:
            raise ValueError(f"Invalid CIDR notation: {v}") from e
        return v

    @field_validator("next_hop")
    @classmethod
    def validate_next_hop(cls, v: Optional[str]) -> Optional[str]:
        """Validate that next_hop is a valid IPv4 address if provided."""
        if v is not None:
            try:
                IPv4Address(v)
            except ValueError as e:
                raise ValueError(f"Invalid next hop IP address: {v}") from e
        return v

    @field_validator("interface")
    @classmethod
    def validate_interface(cls, v: str) -> str:
        """Validate that interface is not empty."""
        if not v or not v.strip():
            raise ValueError("Interface name cannot be empty")
        return v.strip()

    @field_validator("metric")
    @classmethod
    def validate_metric(cls, v: int) -> int:
        """Validate that metric is non-negative."""
        if v < 0:
            raise ValueError("Metric must be a non-negative integer")
        return v

    def get_network(self) -> IPv4Network:
        """Return the destination as an IPv4Network object."""
        return IPv4Network(self.destination, strict=False)

    def get_next_hop(self) -> Optional[IPv4Address]:
        """Return the next hop as an IPv4Address object if present."""
        if self.next_hop:
            return IPv4Address(self.next_hop)
        return None


class RouteLookupResult(BaseModel):
    """
    Result of a route lookup operation.

    Attributes:
        matched: Whether a matching route was found
        route: The selected routing entry (None if no match)
        explanation: Human-readable explanation of the selection
        error: Error message if input was invalid (None if successful)
    """

    matched: bool
    route: Optional[RoutingEntry] = None
    explanation: str = ""
    error: Optional[str] = None


# Sample routing table entries for testing and demonstration
SAMPLE_ROUTES = [
    RoutingEntry(
        destination="192.168.1.0/24",
        next_hop="10.0.0.1",
        interface="eth0",
        metric=10,
        next_hop_type=NextHopType.GATEWAY,
    ),
    RoutingEntry(
        destination="192.168.1.0/25",
        next_hop="10.0.0.2",
        interface="eth1",
        metric=20,
        next_hop_type=NextHopType.GATEWAY,
    ),
    RoutingEntry(
        destination="192.168.0.0/16",
        next_hop="10.0.0.3",
        interface="eth0",
        metric=5,
        next_hop_type=NextHopType.GATEWAY,
    ),
    RoutingEntry(
        destination="10.0.0.0/8",
        next_hop=None,
        interface="eth2",
        metric=1,
        next_hop_type=NextHopType.DIRECT,
    ),
    RoutingEntry(
        destination="0.0.0.0/0",
        next_hop="10.0.0.254",
        interface="eth0",
        metric=100,
        next_hop_type=NextHopType.GATEWAY,
    ),
]