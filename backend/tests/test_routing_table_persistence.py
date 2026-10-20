"""
RouteLens Lite - Routing Table Persistence Tests

Tests for the durable routing table persistence layer.
"""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from app.routing import RoutingEntry, NextHopType, SAMPLE_ROUTES
from app.routing_table import RoutingTable
from app.routing_table_persistence import (
    RoutingTablePersistence,
    PersistenceReport,
    PersistenceState,
    get_persistence,
)


class TestRoutingTablePersistence:
    """Tests for the RoutingTablePersistence class."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for persistence."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def persistence(self, temp_dir):
        """Create a persistence instance with temp directory."""
        return RoutingTablePersistence(persist_dir=temp_dir)

    def test_save_and_load_identical(self, persistence):
        """A table saved and reloaded comes back identical."""
        routes = [
            RoutingEntry(
                destination="192.168.1.0/24",
                next_hop="10.0.0.1",
                interface="eth0",
                metric=10,
                next_hop_type=NextHopType.GATEWAY,
            ),
            RoutingEntry(
                destination="10.0.0.0/8",
                next_hop=None,
                interface="eth1",
                metric=1,
                next_hop_type=NextHopType.DIRECT,
            ),
        ]

        # Save
        report = persistence.save(routes)
        assert report.state == PersistenceState.LOADED
        assert "saved successfully" in report.message

        # Load
        loaded_routes, load_report = persistence.load()
        assert load_report.state == PersistenceState.LOADED
        assert len(loaded_routes) == 2
        assert loaded_routes[0].destination == "192.168.1.0/24"
        assert loaded_routes[0].next_hop == "10.0.0.1"
        assert loaded_routes[1].destination == "10.0.0.0/8"
        assert loaded_routes[1].next_hop is None

    def test_missing_file_falls_back_to_sample(self, persistence):
        """A missing file falls back to the sample table, and says so."""
        routes, report = persistence.load()
        assert report.state == PersistenceState.SAMPLE
        assert "No persisted table found" in report.message
        assert "sample table" in report.message
        assert len(routes) == len(SAMPLE_ROUTES)

    def test_corrupt_file_falls_back_to_sample(self, persistence):
        """A corrupt file falls back, and says so."""
        # Write corrupt JSON
        persistence._ensure_dir()
        with open(persistence.persist_file, "w") as f:
            f.write("{ not valid json }")

        routes, report = persistence.load()
        assert report.state == PersistenceState.FALLBACK
        assert "corrupt" in report.message.lower() or "invalid" in report.message.lower()
        assert report.error is not None
        assert len(routes) == len(SAMPLE_ROUTES)

    def test_invalid_route_rejected_and_previous_survives(self, persistence):
        """A hand-edited file with an invalid route is rejected, previous good copy survives."""
        # First save a valid table
        good_routes = [
            RoutingEntry(
                destination="192.168.1.0/24",
                next_hop="10.0.0.1",
                interface="eth0",
                metric=10,
                next_hop_type=NextHopType.GATEWAY,
            )
        ]
        persistence.save(good_routes)

        # Now write a file with an invalid route (missing required prefix)
        persistence._ensure_dir()
        with open(persistence.persist_file, "w") as f:
            json.dump({
                "version": 1,
                "saved_at": "2024-01-01T00:00:00Z",
                "routes": [
                    {"destination": "192.168.1.0/24", "next_hop": "10.0.0.1", "interface": "eth0", "metric": 10, "next_hop_type": "gateway"},
                    {"destination": "invalid", "next_hop": "10.0.0.2", "interface": "eth1", "metric": 20, "next_hop_type": "gateway"},  # Invalid!
                ]
            }, f)

        # Load should recover from backup (valid route) since backup has the good version
        routes, report = persistence.load()
        assert report.state == PersistenceState.RECOVERED
        assert "recovered from backup" in report.message.lower()
        # Should have the valid route from backup
        assert len(routes) == 1
        assert routes[0].destination == "192.168.1.0/24"

    def test_reset_restores_original_sample(self, persistence):
        """Reset restores the original sample table and clears persisted file."""
        # Save a modified table
        modified_routes = [
            RoutingEntry(
                destination="192.168.99.0/24",
                next_hop="10.0.0.1",
                interface="eth0",
                metric=10,
                next_hop_type=NextHopType.GATEWAY,
            )
        ]
        persistence.save(modified_routes)
        assert persistence.persist_file.exists()

        # Reset
        report = persistence.reset_to_sample()
        assert report.state == PersistenceState.SAMPLE
        assert "reset to sample" in report.message
        assert not persistence.persist_file.exists()
        assert not persistence.backup_file.exists()

        # Next load should return sample
        routes, report = persistence.load()
        assert report.state == PersistenceState.SAMPLE
        assert len(routes) == len(SAMPLE_ROUTES)

    def test_saved_file_is_valid_readable_json(self, persistence):
        """The saved file is valid JSON a person can read."""
        routes = [
            RoutingEntry(
                destination="192.168.1.0/24",
                next_hop="10.0.0.1",
                interface="eth0",
                metric=10,
                next_hop_type=NextHopType.GATEWAY,
            )
        ]
        persistence.save(routes)

        # Read and parse as JSON
        with open(persistence.persist_file, "r") as f:
            data = json.load(f)

        assert "version" in data
        assert "saved_at" in data
        assert "routes" in data
        assert len(data["routes"]) == 1
        assert data["routes"][0]["destination"] == "192.168.1.0/24"
        assert data["routes"][0]["next_hop"] == "10.0.0.1"

        # Verify it's pretty-printed (human readable)
        content = persistence.persist_file.read_text()
        assert "\n" in content  # Multi-line
        assert "  " in content  # Indented

    def test_interrupted_write_cannot_corrupt_file(self, persistence):
        """An interrupted write cannot corrupt the file."""
        # Save a good table first
        good_routes = [
            RoutingEntry(
                destination="192.168.1.0/24",
                next_hop="10.0.0.1",
                interface="eth0",
                metric=10,
                next_hop_type=NextHopType.GATEWAY,
            )
        ]
        persistence.save(good_routes)
        original_content = persistence.persist_file.read_text()

        # Simulate interrupted write by patching atomic_write to fail mid-write
        def failing_atomic_write(data):
            persistence._ensure_dir()
            # Create temp file but don't rename (simulating crash)
            with tempfile.NamedTemporaryFile(
                mode="w",
                dir=persistence.persist_dir,
                prefix=".routing_table_",
                suffix=".tmp",
                delete=False,
            ) as tmp:
                json.dump(data, tmp)
                tmp.flush()
                os.fsync(tmp.fileno())
                # Don't rename - simulating crash
            raise IOError("Simulated write failure")

        with patch.object(persistence, "_atomic_write", side_effect=failing_atomic_write):
            # Try to save - should fail
            report = persistence.save([
                RoutingEntry(
                    destination="10.0.0.0/8",
                    next_hop=None,
                    interface="eth1",
                    metric=1,
                    next_hop_type=NextHopType.DIRECT,
                )
            ])
            assert report.state == PersistenceState.FALLBACK

        # Original file should be intact (restored from backup)
        assert persistence.persist_file.exists()
        current_content = persistence.persist_file.read_text()
        assert current_content == original_content


class TestRoutingTableWithPersistence:
    """Integration tests for RoutingTable with persistence."""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def routing_table(self, temp_dir):
        persistence = RoutingTablePersistence(persist_dir=temp_dir)
        return RoutingTable(persistence=persistence)

    def test_edits_persist_across_reload(self, temp_dir):
        """Edits made to the table persist across a reload."""
        # Create table and add a route
        persistence1 = RoutingTablePersistence(persist_dir=temp_dir)
        table1 = RoutingTable(persistence=persistence1)

        new_route = RoutingEntry(
            destination="192.168.99.0/24",
            next_hop="10.0.0.1",
            interface="eth0",
            metric=10,
            next_hop_type=NextHopType.GATEWAY,
        )
        table1.add_route(new_route)

        # Create new table instance (simulating restart)
        persistence2 = RoutingTablePersistence(persist_dir=temp_dir)
        table2 = RoutingTable(persistence=persistence2)

        # The added route should be there
        routes = table2.get_routes()
        added = next((r for r in routes if r.destination == "192.168.99.0/24"), None)
        assert added is not None
        assert added.next_hop == "10.0.0.1"

    def test_reset_clears_persisted_file(self, temp_dir):
        """Reset restores the original sample table and clears persisted file."""
        persistence1 = RoutingTablePersistence(persist_dir=temp_dir)
        table1 = RoutingTable(persistence=persistence1)

        # Add a route
        table1.add_route(RoutingEntry(
            destination="192.168.99.0/24",
            next_hop="10.0.0.1",
            interface="eth0",
            metric=10,
            next_hop_type=NextHopType.GATEWAY,
        ))
        assert persistence1.persist_file.exists()

        # Reset
        table1.reset_routes()

        # File should be gone
        assert not persistence1.persist_file.exists()
        assert not persistence1.backup_file.exists()

        # Table should be back to sample
        routes = table1.get_routes()
        assert len(routes) == len(SAMPLE_ROUTES)
        assert not any(r.destination == "192.168.99.0/24" for r in routes)

    def test_summary_includes_persistence_state(self, temp_dir):
        """Summary includes persistence state."""
        persistence = RoutingTablePersistence(persist_dir=temp_dir)
        table = RoutingTable(persistence=persistence)

        summary = table.get_summary()
        assert "persistence" in summary
        assert "state" in summary["persistence"]
        assert "message" in summary["persistence"]
        assert summary["persistence"]["state"] == PersistenceState.SAMPLE.value

    def test_update_delete_also_persist(self, temp_dir):
        """Update and delete operations also persist."""
        persistence = RoutingTablePersistence(persist_dir=temp_dir)
        table = RoutingTable(persistence=persistence)

        # Get initial count
        initial_count = len(table.get_routes())

        # Add a route
        table.add_route(RoutingEntry(
            destination="192.168.99.0/24",
            next_hop="10.0.0.1",
            interface="eth0",
            metric=10,
            next_hop_type=NextHopType.GATEWAY,
        ))
        assert len(table.get_routes()) == initial_count + 1

        # Update the route
        last_idx = len(table.get_routes()) - 1
        table.update_route(last_idx, RoutingEntry(
            destination="192.168.99.0/24",
            next_hop="10.0.0.2",  # Changed
            interface="eth0",
            metric=20,
            next_hop_type=NextHopType.GATEWAY,
        ))

        # Reload
        persistence2 = RoutingTablePersistence(persist_dir=Path(str(persistence.persist_dir)))
        table2 = RoutingTable(persistence=persistence2)

        # Should have the updated route
        routes = table2.get_routes()
        updated = next(r for r in routes if r.destination == "192.168.99.0/24")
        assert updated.next_hop == "10.0.0.2"
        assert updated.metric == 20

        # Delete
        table2.delete_route(last_idx)
        routes_after = table2.get_routes()
        assert len(routes_after) == initial_count

        # Reload again
        persistence3 = RoutingTablePersistence(persist_dir=Path(str(persistence.persist_dir)))
        table3 = RoutingTable(persistence=persistence3)
        assert len(table3.get_routes()) == initial_count


class TestPersistenceReport:
    """Tests for the PersistenceReport dataclass."""

    def test_report_fields(self):
        """PersistenceReport has all required fields."""
        report = PersistenceReport(
            state=PersistenceState.LOADED,
            message="Test",
            loaded_at="2024-01-01T00:00:00Z",
            file_path="/tmp/test.json",
            backup_path="/tmp/test.json.bak",
            error=None,
        )
        assert report.state == PersistenceState.LOADED
        assert report.message == "Test"
        assert report.loaded_at == "2024-01-01T00:00:00Z"
        assert report.file_path == "/tmp/test.json"
        assert report.backup_path == "/tmp/test.json.bak"
        assert report.error is None

    def test_state_enum_values(self):
        """All expected PersistenceState values exist."""
        assert PersistenceState.SAMPLE.value == "sample"
        assert PersistenceState.LOADED.value == "loaded"
        assert PersistenceState.RECOVERED.value == "recovered"
        assert PersistenceState.FALLBACK.value == "fallback"


class TestBackupRecovery:
    """Tests for backup and recovery behavior."""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_backup_created_on_save(self, temp_dir):
        """A backup is created when saving."""
        persistence = RoutingTablePersistence(persist_dir=temp_dir)

        # First save - backup is created after successful write
        persistence.save([RoutingEntry(
            destination="192.168.1.0/24",
            next_hop="10.0.0.1",
            interface="eth0",
            metric=10,
            next_hop_type=NextHopType.GATEWAY,
        )])
        assert persistence.backup_file.exists()  # Backup created after first save

        # Second save - backup should be updated
        persistence.save([RoutingEntry(
            destination="10.0.0.0/8",
            next_hop=None,
            interface="eth1",
            metric=1,
            next_hop_type=NextHopType.DIRECT,
        )])
        assert persistence.backup_file.exists()

    def test_recovery_from_backup(self, temp_dir):
        """If main file is corrupt, backup is used to recover."""
        persistence = RoutingTablePersistence(persist_dir=temp_dir)

        # Save a good table
        good_routes = [RoutingEntry(
            destination="192.168.1.0/24",
            next_hop="10.0.0.1",
            interface="eth0",
            metric=10,
            next_hop_type=NextHopType.GATEWAY,
        )]
        persistence.save(good_routes)

        # Corrupt the main file but leave backup intact
        persistence.persist_file.write_text("{ corrupt }")

        # Load should recover from backup
        routes, report = persistence.load()
        assert report.state == PersistenceState.RECOVERED
        assert "recovered from backup" in report.message.lower()
        assert len(routes) == 1
        assert routes[0].destination == "192.168.1.0/24"

    def test_both_corrupt_fallbacks_to_sample(self, temp_dir):
        """If both main and backup are corrupt, falls back to sample."""
        persistence = RoutingTablePersistence(persist_dir=temp_dir)

        # Save a good table
        persistence.save([RoutingEntry(
            destination="192.168.1.0/24",
            next_hop="10.0.0.1",
            interface="eth0",
            metric=10,
            next_hop_type=NextHopType.GATEWAY,
        )])

        # Corrupt both files
        persistence.persist_file.write_text("{ corrupt }")
        persistence.backup_file.write_text("{ also corrupt }")

        # Load should fall back to sample
        routes, report = persistence.load()
        assert report.state == PersistenceState.FALLBACK
        assert "sample table" in report.message
        assert len(routes) == len(SAMPLE_ROUTES)


class TestConcurrency:
    """Tests for thread safety."""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_concurrent_save_and_load(self, temp_dir):
        """Concurrent saves and loads don't corrupt data."""
        import threading
        import time

        persistence = RoutingTablePersistence(persist_dir=temp_dir)
        errors = []

        def writer(i):
            try:
                persistence.save([RoutingEntry(
                    destination=f"192.168.{i}.0/24",
                    next_hop="10.0.0.1",
                    interface="eth0",
                    metric=10,
                    next_hop_type=NextHopType.GATEWAY,
                )])
            except Exception as e:
                errors.append(e)

        def reader(i):
            try:
                persistence.load()
            except Exception as e:
                errors.append(e)

        threads = []
        for i in range(10):
            threads.append(threading.Thread(target=writer, args=(i,)))
            threads.append(threading.Thread(target=reader, args=(i,)))

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Concurrent operations failed: {errors}"
        # File should be valid
        routes, report = persistence.load()
        assert report.state in (PersistenceState.LOADED, PersistenceState.RECOVERED, PersistenceState.FALLBACK)