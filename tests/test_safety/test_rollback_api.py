"""Tests for rollback API.

Tests the high-level API for manual rollback operations with safety checks.
"""
import pytest
import tempfile
import os
from datetime import datetime, timedelta, UTC
from pathlib import Path

from src.safety.rollback import RollbackManager, RollbackStatus
from src.safety.rollback_api import RollbackAPI


class TestRollbackAPI:
    """Test suite for rollback API."""

    @pytest.fixture
    def rollback_manager(self):
        """Create rollback manager."""
        return RollbackManager()

    @pytest.fixture
    def api(self, rollback_manager):
        """Create rollback API."""
        return RollbackAPI(rollback_manager)

    @pytest.fixture
    def temp_file(self):
        """Create temporary file for testing."""
        with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
            f.write("original content")
            temp_path = f.name

        yield temp_path

        if os.path.exists(temp_path):
            os.unlink(temp_path)

    def test_list_snapshots_no_filter(self, api, rollback_manager):
        """Test listing all snapshots without filters."""
        # Create test snapshots
        snap1 = rollback_manager.create_snapshot(
            action={"tool": "write_file", "path": "/tmp/test1.txt"},
            context={"workflow_id": "wf-1", "agent_id": "agent-1"}
        )
        snap2 = rollback_manager.create_snapshot(
            action={"tool": "write_file", "path": "/tmp/test2.txt"},
            context={"workflow_id": "wf-2", "agent_id": "agent-2"}
        )

        snapshots = api.list_snapshots()

        assert len(snapshots) == 2
        assert snap1.id in [s.id for s in snapshots]
        assert snap2.id in [s.id for s in snapshots]

    def test_list_snapshots_filter_by_workflow(self, api, rollback_manager):
        """Test filtering snapshots by workflow_id."""
        snap1 = rollback_manager.create_snapshot(
            action={"tool": "write_file"},
            context={"workflow_id": "wf-1"}
        )
        snap2 = rollback_manager.create_snapshot(
            action={"tool": "write_file"},
            context={"workflow_id": "wf-2"}
        )

        snapshots = api.list_snapshots(workflow_id="wf-1")

        assert len(snapshots) == 1
        assert snapshots[0].id == snap1.id

    def test_list_snapshots_filter_by_agent(self, api, rollback_manager):
        """Test filtering snapshots by agent_id."""
        snap1 = rollback_manager.create_snapshot(
            action={"tool": "write_file"},
            context={"agent_id": "agent-1"}
        )
        snap2 = rollback_manager.create_snapshot(
            action={"tool": "write_file"},
            context={"agent_id": "agent-2"}
        )

        snapshots = api.list_snapshots(agent_id="agent-1")

        assert len(snapshots) == 1
        assert snapshots[0].id == snap1.id

    def test_list_snapshots_filter_by_time(self, api, rollback_manager):
        """Test filtering snapshots by creation time."""
        # Create snapshot in the past
        snap1 = rollback_manager.create_snapshot(
            action={"tool": "write_file"},
            context={}
        )
        # Manually adjust creation time
        snap1.created_at = datetime.now(UTC) - timedelta(hours=48)

        # Create recent snapshot
        snap2 = rollback_manager.create_snapshot(
            action={"tool": "write_file"},
            context={}
        )

        # Filter for last 24 hours
        since = datetime.now(UTC) - timedelta(hours=24)
        snapshots = api.list_snapshots(since=since)

        assert len(snapshots) == 1
        assert snapshots[0].id == snap2.id

    def test_get_snapshot_details(self, api, rollback_manager, temp_file):
        """Test getting detailed snapshot information."""
        snapshot = rollback_manager.create_snapshot(
            action={"tool": "write_file", "path": temp_file},
            context={"workflow_id": "wf-1"}
        )

        details = api.get_snapshot_details(snapshot.id)

        assert details is not None
        assert details["id"] == snapshot.id
        assert details["action"]["tool"] == "write_file"
        assert "created_at" in details
        assert "age_hours" in details
        assert details["file_count"] >= 0

    def test_get_snapshot_details_not_found(self, api):
        """Test getting details for non-existent snapshot."""
        details = api.get_snapshot_details("non-existent-id")
        assert details is None

    def test_validate_rollback_safety_success(self, api, rollback_manager, temp_file):
        """Test safety validation for valid snapshot."""
        snapshot = rollback_manager.create_snapshot(
            action={"tool": "write_file", "path": temp_file},
            context={}
        )

        is_safe, warnings = api.validate_rollback_safety(snapshot.id)

        assert is_safe
        # May have warnings but should be safe

    def test_validate_rollback_safety_not_found(self, api):
        """Test safety validation for non-existent snapshot."""
        is_safe, warnings = api.validate_rollback_safety("non-existent-id")

        assert not is_safe
        assert "Snapshot not found" in warnings

    def test_validate_rollback_safety_file_modified(self, api, rollback_manager, temp_file):
        """Test safety validation detects file modifications."""
        # Create snapshot
        snapshot = rollback_manager.create_snapshot(
            action={"tool": "write_file", "path": temp_file},
            context={}
        )

        # Modify file after snapshot
        import time
        time.sleep(0.1)  # Ensure timestamp difference
        with open(temp_file, 'w') as f:
            f.write("modified content")

        is_safe, warnings = api.validate_rollback_safety(snapshot.id)

        # Should still be safe but have warning
        assert is_safe  # Not critical warning
        assert any("modified since snapshot" in w for w in warnings)

    def test_execute_manual_rollback_dry_run(self, api, rollback_manager, temp_file):
        """Test dry run rollback (no actual changes)."""
        # Modify file
        with open(temp_file, 'w') as f:
            f.write("modified content")

        # Create snapshot after modification
        snapshot = rollback_manager.create_snapshot(
            action={"tool": "write_file", "path": temp_file},
            context={}
        )

        result = api.execute_manual_rollback(
            snapshot_id=snapshot.id,
            operator="test-user",
            reason="Testing dry run",
            dry_run=True
        )

        assert result.success
        assert result.metadata["dry_run"]
        assert result.metadata["operator"] == "test-user"

        # File should remain unchanged
        with open(temp_file, 'r') as f:
            assert f.read() == "modified content"

    def test_execute_manual_rollback_success(self, api, rollback_manager, temp_file):
        """Test successful manual rollback."""
        # Create snapshot with original content
        snapshot = rollback_manager.create_snapshot(
            action={"tool": "write_file", "path": temp_file},
            context={}
        )

        # Modify file
        with open(temp_file, 'w') as f:
            f.write("modified content")

        # Execute rollback
        result = api.execute_manual_rollback(
            snapshot_id=snapshot.id,
            operator="test-user",
            reason="Manual recovery test"
        )

        assert result.success
        assert result.metadata["manual"]
        assert result.metadata["operator"] == "test-user"
        assert result.metadata["reason"] == "Manual recovery test"

        # File should be restored
        with open(temp_file, 'r') as f:
            assert f.read() == "original content"

    def test_execute_manual_rollback_not_found(self, api):
        """Test rollback with non-existent snapshot."""
        with pytest.raises(ValueError, match="Snapshot not found"):
            api.execute_manual_rollback(
                snapshot_id="non-existent-id",
                operator="test-user",
                reason="Test"
            )

    def test_execute_manual_rollback_force(self, api, rollback_manager, temp_file):
        """Test force rollback bypasses safety checks."""
        # Create expired snapshot
        snapshot = rollback_manager.create_snapshot(
            action={"tool": "write_file", "path": temp_file},
            context={}
        )
        snapshot.expires_at = datetime.now(UTC) - timedelta(hours=1)

        # Modify file
        with open(temp_file, 'w') as f:
            f.write("modified content")

        # Rollback with force should succeed despite expiration
        result = api.execute_manual_rollback(
            snapshot_id=snapshot.id,
            operator="test-user",
            reason="Force rollback test",
            force=True
        )

        assert result.success

        # File should be restored
        with open(temp_file, 'r') as f:
            assert f.read() == "original content"

    def test_get_rollback_history(self, api, rollback_manager, temp_file):
        """Test retrieving rollback history."""
        snapshot = rollback_manager.create_snapshot(
            action={"tool": "write_file", "path": temp_file},
            context={}
        )

        # Execute rollback
        api.execute_manual_rollback(
            snapshot_id=snapshot.id,
            operator="test-user",
            reason="Test"
        )

        history = api.get_rollback_history()

        assert len(history) == 1
        assert history[0].snapshot_id == snapshot.id
        assert history[0].metadata["operator"] == "test-user"

    def test_get_rollback_history_filter_by_snapshot(self, api, rollback_manager, temp_file):
        """Test filtering history by snapshot ID."""
        # Create two snapshots
        snap1 = rollback_manager.create_snapshot(
            action={"tool": "write_file", "path": temp_file},
            context={}
        )
        snap2 = rollback_manager.create_snapshot(
            action={"tool": "write_file", "path": temp_file},
            context={}
        )

        # Execute rollbacks
        api.execute_manual_rollback(snap1.id, "user1", "test1")
        api.execute_manual_rollback(snap2.id, "user2", "test2")

        # Filter by snap1
        history = api.get_rollback_history(snapshot_id=snap1.id)

        assert len(history) == 1
        assert history[0].snapshot_id == snap1.id
