"""
RouteLens Lite - Mutable Routing Table Service

Provides a thread-safe, authoritative routing table that can be modified at runtime.
Now with durable persistence so edits survive a restart.
"""

import threading
from copy import deepcopy
from typing import Optional

from app.routing import RoutingEntry, NextHopType, Provenance, SAMPLE_ROUTES
from app.routing_table_persistence import (
    RoutingTablePersistence,
    get_persistence,
    PersistenceReport,
    PersistenceState,
)


class RoutingTableError(Exception):
    """Base exception for routing table errors."""

    pass


class InvalidRouteError(RoutingTableError):
    """Raised when a route fails validation."""

    pass


class IndexOutOfRangeError(RoutingTableError):
    """Raised when an index is out of range."""

    pass


class RoutingTable:
    """
    Thread-safe mutable routing table service.

    Holds the authoritative routing table in memory with support for
    atomic bulk operations and individual route CRUD.
    Now with durable persistence so edits survive a restart.
    """

    def __init__(self, persistence: Optional[RoutingTablePersistence] = None):
        self._lock = threading.RLock()
        self._original_routes = deepcopy(SAMPLE_ROUTES)
        self._persistence = persistence or get_persistence()

        # Load from persistence on startup
        self._routes, self._load_report = self._persistence.load()

    def get_routes(self) -> list[RoutingEntry]:
        """Get a copy of the current routing table."""
        with self._lock:
            return deepcopy(self._routes)

    def get_load_report(self) -> PersistenceReport:
        """Get the report from the last load operation."""
        with self._lock:
            return self._load_report

    def reset_routes(self) -> list[RoutingEntry]:
        """
        Reset the routing table to the original sample routes.

        Also clears the persisted file so the next load returns the sample table.
        """
        with self._lock:
            self._routes = deepcopy(self._original_routes)
            # Clear persisted file so it doesn't get reloaded
            self._persistence.reset_to_sample()
            return deepcopy(self._routes)

    def _validate_route(self, route: RoutingEntry) -> None:
        """
        Validate a single route entry.

        Raises:
            InvalidRouteError: If the route is invalid with a clear message
        """
        # Validate destination (CIDR)
        try:
            route.get_network()
        except ValueError as e:
            raise InvalidRouteError(f"Invalid CIDR notation: {route.destination}") from e

        # Validate next_hop if provided
        if route.next_hop is not None:
            try:
                route.get_next_hop()
            except ValueError as e:
                raise InvalidRouteError(f"Invalid next hop IP address: {route.next_hop}") from e

        # Validate interface
        if not route.interface or not route.interface.strip():
            raise InvalidRouteError("Interface name cannot be empty")

        # Validate metric
        if route.metric < 0:
            raise InvalidRouteError("Metric must be a non-negative integer")

        # Gateway routes must have a next_hop
        if route.next_hop_type == NextHopType.GATEWAY and route.next_hop is None:
            raise InvalidRouteError(
                f"Gateway route {route.destination} requires a next_hop address"
            )

    def _save(self) -> PersistenceReport:
        """Save the current table to persistence."""
        with self._lock:
            return self._persistence.save(self._routes)

    def add_route(self, route: RoutingEntry) -> RoutingEntry:
        """
        Add a route to the table.

        Args:
            route: The route to add

        Returns:
            The added route

        Raises:
            InvalidRouteError: If the route is invalid
        """
        self._validate_route(route)
        # Every route in this table is part of the teaching model, whether
        # the sample one or one the reader typed in. The provenance is
        # decided here rather than taken from the caller, so it is the same
        # whichever door the route came in by.
        route.provenance = Provenance.SIMULATED
        with self._lock:
            self._routes.append(deepcopy(route))
        self._save()
        return deepcopy(route)

    def update_route(self, index: int, route: RoutingEntry) -> RoutingEntry:
        """
        Update a route at the given index.

        Args:
            index: The index of the route to update
            route: The new route data

        Returns:
            The updated route

        Raises:
            InvalidRouteError: If the route is invalid
            IndexOutOfRangeError: If the index is out of range
        """
        with self._lock:
            # The index range is checked before the route is validated, so an
            # out-of-range index is reported even when the supplied route is
            # also invalid.
            if index < 0 or index >= len(self._routes):
                raise IndexOutOfRangeError(f"Route index {index} out of range (0-{len(self._routes) - 1})")
            self._validate_route(route)
        # The same reasoning as in add_route: a route in the teaching table
        # is part of the model.
        route.provenance = Provenance.SIMULATED
        with self._lock:
            self._routes[index] = deepcopy(route)
        self._save()
        return deepcopy(route)

    def delete_route(self, index: int) -> None:
        """
        Delete a route at the given index.

        Args:
            index: The index of the route to delete

        Raises:
            IndexOutOfRangeError: If the index is out of range
        """
        with self._lock:
            if index < 0 or index >= len(self._routes):
                raise IndexOutOfRangeError(f"Route index {index} out of range (0-{len(self._routes) - 1})")
            self._routes.pop(index)
        self._save()

    def replace_routes(self, routes: list[RoutingEntry]) -> list[RoutingEntry]:
        """
        Atomically replace the entire routing table.

        All routes are validated before any changes are made. If any route
        is invalid, the table remains unchanged.

        Args:
            routes: The new routing table

        Returns:
            The new routing table

        Raises:
            InvalidRouteError: If any route is invalid (table unchanged)
        """
        # Validate all routes first (atomic)
        for i, route in enumerate(routes):
            try:
                self._validate_route(route)
            except InvalidRouteError as e:
                raise InvalidRouteError(f"Route at index {i}: {e}") from e

        with self._lock:
            self._routes = deepcopy(routes)
        self._save()
        return deepcopy(self._routes)

    def get_summary(self) -> dict:
        """
        Get a summary of the current routing table.

        Returns:
            Dictionary with counts, statistics, and persistence state
        """
        with self._lock:
            routes = self._routes
            if not routes:
                summary = {
                    "total_routes": 0,
                    "longest_prefix": None,
                    "lowest_metric": None,
                    "default_route_count": 0,
                    "ipv4_count": 0,
                    "ipv6_count": 0,
                }
            else:
                # Find longest prefix
                longest_prefix_route = max(routes, key=lambda r: r.get_network().prefixlen)
                longest_prefix = f"{longest_prefix_route.destination} (/{longest_prefix_route.get_network().prefixlen})"

                # Find lowest metric
                lowest_metric_route = min(routes, key=lambda r: r.metric)
                lowest_metric = lowest_metric_route.metric

                # Count default routes
                default_route_count = sum(
                    1 for r in routes
                    if r.destination in ("0.0.0.0/0", "::/0")
                )

                ipv4_count = sum(1 for r in routes if r.get_ip_version().value == "ipv4")
                ipv6_count = sum(1 for r in routes if r.get_ip_version().value == "ipv6")

                summary = {
                    "total_routes": len(routes),
                    "longest_prefix": longest_prefix,
                    "lowest_metric": lowest_metric,
                    "default_route_count": default_route_count,
                    "ipv4_count": ipv4_count,
                    "ipv6_count": ipv6_count,
                }

            # Add persistence state
            summary["persistence"] = {
                "state": self._load_report.state.value,
                "message": self._load_report.message,
                "loaded_at": self._load_report.loaded_at,
                "file_path": self._load_report.file_path,
                "backup_path": self._load_report.backup_path,
            }
            if self._load_report.error:
                summary["persistence"]["error"] = self._load_report.error

            return summary


# Global singleton instance
_routing_table: Optional[RoutingTable] = None


def get_routing_table() -> RoutingTable:
    """Get or create the singleton routing table instance."""
    global _routing_table
    if _routing_table is None:
        _routing_table = RoutingTable()
    return _routing_table