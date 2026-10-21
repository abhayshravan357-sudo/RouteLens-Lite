"""
RouteLens Lite - Routing Table Persistence

Provides durable storage for the editable routing table with atomic writes,
corruption recovery, and honest state reporting.
"""

import json
import os
import shutil
import tempfile
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional

from app.routing import Provenance, RoutingEntry, SAMPLE_ROUTES


class PersistenceState(str, Enum):
    """State of the routing table after loading."""
    SAMPLE = "sample"           # Running on original sample table (no file or fresh start)
    LOADED = "loaded"           # Successfully loaded from persisted file
    RECOVERED = "recovered"     # Recovered from backup after corruption
    FALLBACK = "fallback"       # Fell back to sample due to missing/corrupt file


@dataclass
class PersistenceReport:
    """Report on the persistence state."""
    state: PersistenceState
    message: str
    loaded_at: Optional[str] = None
    saved_at: Optional[str] = None
    file_path: Optional[str] = None
    backup_path: Optional[str] = None
    error: Optional[str] = None


PERSIST_DIR = Path(".routelens")
PERSIST_FILE = PERSIST_DIR / "routing_table.json"
BACKUP_FILE = PERSIST_DIR / "routing_table.json.bak"


class RoutingTablePersistence:
    """
    Handles persistent storage of the routing table.

    Features:
    - Atomic writes via temp file + rename
    - Backup copy for recovery
    - Validation on load (rejects invalid routes)
    - Graceful fallback to sample table
    - Honest state reporting
    """

    def __init__(self, persist_dir: Optional[Path] = None):
        self.persist_dir = persist_dir or PERSIST_DIR
        self.persist_file = self.persist_dir / "routing_table.json"
        self.backup_file = self.persist_dir / "routing_table.json.bak"
        self._lock = threading.RLock()

    def _ensure_dir(self) -> None:
        """Create the persistence directory if it doesn't exist."""
        self.persist_dir.mkdir(parents=True, exist_ok=True)

    def _atomic_write(self, data: dict) -> None:
        """Write data atomically using temp file + rename."""
        self._ensure_dir()
        with tempfile.NamedTemporaryFile(
            mode="w",
            dir=self.persist_dir,
            prefix=".routing_table_",
            suffix=".tmp",
            delete=False,
        ) as tmp:
            json.dump(data, tmp, indent=2, sort_keys=True)
            tmp.flush()
            os.fsync(tmp.fileno())
            tmp_path = Path(tmp.name)

        # Atomic rename
        tmp_path.replace(self.persist_file)

    def _make_backup(self) -> bool:
        """Create a backup of the current file. Returns True if backup created."""
        if self.persist_file.exists():
            try:
                shutil.copy2(self.persist_file, self.backup_file)
                return True
            except Exception:
                return False
        return False

    def _restore_from_backup(self) -> bool:
        """Restore from backup file. Returns True if successful."""
        if self.backup_file.exists():
            try:
                shutil.copy2(self.backup_file, self.persist_file)
                return True
            except Exception:
                return False
        return False

    def _validate_routes(self, routes_data: list) -> list[RoutingEntry]:
        """Validate and convert loaded route data to RoutingEntry objects."""
        routes = []
        for i, route_data in enumerate(routes_data):
            try:
                route = RoutingEntry(**route_data)
                # Additional validation
                route.get_network()  # Validates CIDR
                if route.next_hop:
                    route.get_next_hop()  # Validates next_hop IP
                # A table written before routes carried their provenance
                # still holds the teaching model, and says so now.
                route.provenance = Provenance.SIMULATED
                routes.append(route)
            except Exception as e:
                raise ValueError(f"Route at index {i} is invalid: {e}") from e
        return routes

    def save(self, routes: list[RoutingEntry]) -> PersistenceReport:
        """
        Save the routing table atomically.

        Returns a report on the operation.
        """
        with self._lock:
            # Prepare data
            data = {
                "version": 1,
                "saved_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "routes": [r.model_dump() for r in routes],
            }

            try:
                self._atomic_write(data)
                # Create backup after successful write (for next save's recovery)
                self._make_backup()
                return PersistenceReport(
                    state=PersistenceState.LOADED,
                    message="Routing table saved successfully",
                    saved_at=data["saved_at"],
                    file_path=str(self.persist_file),
                    backup_path=str(self.backup_file),
                )
            except Exception as e:
                # Try to restore from backup on write failure
                self._restore_from_backup()
                return PersistenceReport(
                    state=PersistenceState.FALLBACK,
                    message=f"Save failed, restored from backup: {e}",
                    saved_at=data["saved_at"],
                    error=str(e),
                    file_path=str(self.persist_file),
                    backup_path=str(self.backup_file),
                )

    def load(self) -> tuple[list[RoutingEntry], PersistenceReport]:
        """
        Load the routing table from disk.

        Returns (routes, report) where routes is either the loaded table
        or the sample table (on fallback), and report describes what happened.
        """
        with self._lock:
            # No file -> use sample
            if not self.persist_file.exists():
                return deepcopy(SAMPLE_ROUTES), PersistenceReport(
                    state=PersistenceState.SAMPLE,
                    message="No persisted table found, using original sample table",
                    file_path=str(self.persist_file),
                )

            # Try to load
            try:
                with open(self.persist_file, "r") as f:
                    data = json.load(f)

                # Validate structure
                if not isinstance(data, dict) or "routes" not in data:
                    raise ValueError("Invalid file format: missing 'routes' key")

                routes = self._validate_routes(data["routes"])

                return routes, PersistenceReport(
                    state=PersistenceState.LOADED,
                    message="Routing table loaded from disk",
                    loaded_at=data.get("saved_at"),
                    file_path=str(self.persist_file),
                    backup_path=str(self.backup_file) if self.backup_file.exists() else None,
                )

            except (json.JSONDecodeError, ValueError, KeyError, TypeError) as e:
                # Corrupt or invalid file - try backup
                if self._restore_from_backup():
                    try:
                        with open(self.persist_file, "r") as f:
                            data = json.load(f)
                        routes = self._validate_routes(data["routes"])
                        return routes, PersistenceReport(
                            state=PersistenceState.RECOVERED,
                            message=f"Main file corrupt ({e}), recovered from backup",
                            loaded_at=data.get("saved_at"),
                            file_path=str(self.persist_file),
                            backup_path=str(self.backup_file),
                            error=str(e),
                        )
                    except Exception as e2:
                        # Backup also bad
                        pass

                # Both bad -> fallback to sample
                return deepcopy(SAMPLE_ROUTES), PersistenceReport(
                    state=PersistenceState.FALLBACK,
                    message=f"Persisted table corrupt and no valid backup: {e}. Using sample table.",
                    error=str(e),
                    file_path=str(self.persist_file),
                )

            except Exception as e:
                # Any other error -> fallback
                return deepcopy(SAMPLE_ROUTES), PersistenceReport(
                    state=PersistenceState.FALLBACK,
                    message=f"Failed to load table: {e}. Using sample table.",
                    error=str(e),
                    file_path=str(self.persist_file),
                )

    def reset_to_sample(self) -> PersistenceReport:
        """
        Reset the persisted table to the sample routes.

        This removes the persisted file and backup, so the next load
        will return the sample table.
        """
        with self._lock:
            removed = []
            if self.persist_file.exists():
                self.persist_file.unlink()
                removed.append("main")
            if self.backup_file.exists():
                self.backup_file.unlink()
                removed.append("backup")

            return PersistenceReport(
                state=PersistenceState.SAMPLE,
                message=f"Persisted table reset to sample. Removed: {', '.join(removed) or 'none'}",
                file_path=str(self.persist_file),
            )


# Need deepcopy for the fallback returns
from copy import deepcopy

# Singleton instance
_persistence: Optional[RoutingTablePersistence] = None


def get_persistence() -> RoutingTablePersistence:
    """Get or create the singleton persistence instance."""
    global _persistence
    if _persistence is None:
        _persistence = RoutingTablePersistence()
    return _persistence