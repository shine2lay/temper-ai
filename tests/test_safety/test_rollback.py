"""Tests for rollback mechanism system."""
import pytest
import os
import tempfile
from pathlib import Path
from datetime import datetime, UTC

from src.safety.rollback import (
    RollbackSnapshot,
    RollbackResult,
    RollbackStatus,
    RollbackStrategy,
    FileRollbackStrategy,
    StateRollbackStrategy,
    CompositeRollbackStrategy,
    RollbackManager
)


class TestRollbackSnapshot:
    """Test RollbackSnapshot data class."""

    def test_initialization(self):
        """Test snapshot initialization."""
        snapshot = RollbackSnapshot(
            action={"tool": "write_file", "path": "/tmp/test.txt"},
            context={"agent": "writer"},
            file_snapshots={"/tmp/test.txt": "original content"},
            state_snapshots={"counter": 0}
        )

        assert snapshot.id is not None
        assert snapshot.action == {"tool": "write_file", "path": "/tmp/test.txt"}
        assert snapshot.context == {"agent": "writer"}
        assert snapshot.file_snapshots == {"/tmp/test.txt": "original content"}
        assert snapshot.state_snapshots == {"counter": 0}
        assert isinstance(snapshot.created_at, datetime)

    def test_to_dict(self):
        """Test serialization to dictionary."""
        snapshot = RollbackSnapshot(
            action={"tool": "test"},
            context={"agent": "test"},
            file_snapshots={"file.txt": "content"},
            state_snapshots={"key": "value"}
        )

        data = snapshot.to_dict()

        assert data["id"] == snapshot.id
        assert data["action"] == {"tool": "test"}
        assert data["file_snapshots"] == {"file.txt": "content"}
        assert data["state_snapshots"] == {"key": "value"}


class TestRollbackResult:
    """Test RollbackResult data class."""

    def test_initialization(self):
        """Test result initialization."""
        result = RollbackResult(
            success=True,
            snapshot_id="snap-123",
            status=RollbackStatus.COMPLETED,
            reverted_items=["file1.txt", "file2.txt"],
            failed_items=[],
            errors=[]
        )

        assert result.success is True
        assert result.snapshot_id == "snap-123"
        assert result.status == RollbackStatus.COMPLETED
        assert len(result.reverted_items) == 2
        assert len(result.failed_items) == 0

    def test_to_dict(self):
        """Test serialization to dictionary."""
        result = RollbackResult(
            success=False,
            snapshot_id="snap-123",
            status=RollbackStatus.FAILED,
            reverted_items=[],
            failed_items=["file.txt"],
            errors=["Failed to restore file"]
        )

        data = result.to_dict()

        assert data["success"] is False
        assert data["status"] == "failed"
        assert data["failed_items"] == ["file.txt"]
        assert data["errors"] == ["Failed to restore file"]


class TestFileRollbackStrategy:
    """Test file rollback strategy."""

    def test_create_snapshot_existing_file(self, tmp_path):
        """Test snapshot creation for existing file."""
        # Create test file
        test_file = tmp_path / "test.txt"
        test_file.write_text("original content")

        strategy = FileRollbackStrategy()
        snapshot = strategy.create_snapshot(
            action={"tool": "write_file", "path": str(test_file)},
            context={"agent": "test"}
        )

        assert str(test_file) in snapshot.file_snapshots
        assert snapshot.file_snapshots[str(test_file)] == "original content"
        assert snapshot.metadata[f"{str(test_file)}_existed"] is True

    def test_create_snapshot_nonexistent_file(self, tmp_path):
        """Test snapshot creation for file that doesn't exist."""
        test_file = tmp_path / "new.txt"

        strategy = FileRollbackStrategy()
        snapshot = strategy.create_snapshot(
            action={"tool": "write_file", "path": str(test_file)},
            context={}
        )

        assert str(test_file) not in snapshot.file_snapshots
        assert snapshot.metadata[f"{str(test_file)}_existed"] is False

    def test_rollback_restore_file_content(self, tmp_path):
        """Test rollback restores original file content."""
        # Setup
        test_file = tmp_path / "test.txt"
        test_file.write_text("original content")

        strategy = FileRollbackStrategy()
        snapshot = strategy.create_snapshot(
            action={"path": str(test_file)},
            context={}
        )

        # Modify file
        test_file.write_text("modified content")
        assert test_file.read_text() == "modified content"

        # Rollback
        result = strategy.execute_rollback(snapshot)

        assert result.success is True
        assert result.status == RollbackStatus.COMPLETED
        assert str(test_file) in result.reverted_items
        assert test_file.read_text() == "original content"

    def test_rollback_delete_created_file(self, tmp_path):
        """Test rollback deletes file that was created."""
        test_file = tmp_path / "new.txt"

        strategy = FileRollbackStrategy()
        snapshot = strategy.create_snapshot(
            action={"path": str(test_file)},
            context={}
        )

        # Create file (simulating action)
        test_file.write_text("new content")
        assert test_file.exists()

        # Rollback
        result = strategy.execute_rollback(snapshot)

        assert result.success is True
        assert not test_file.exists()
        assert f"deleted:{str(test_file)}" in result.reverted_items

    def test_rollback_multiple_files(self, tmp_path):
        """Test rollback with multiple files."""
        file1 = tmp_path / "file1.txt"
        file2 = tmp_path / "file2.txt"

        file1.write_text("content1")
        file2.write_text("content2")

        strategy = FileRollbackStrategy()
        snapshot = strategy.create_snapshot(
            action={"files": [str(file1), str(file2)]},
            context={}
        )

        # Modify both files
        file1.write_text("modified1")
        file2.write_text("modified2")

        # Rollback
        result = strategy.execute_rollback(snapshot)

        assert result.success is True
        assert len(result.reverted_items) == 2
        assert file1.read_text() == "content1"
        assert file2.read_text() == "content2"

    def test_rollback_partial_failure(self, tmp_path):
        """Test rollback with partial failure."""
        file1 = tmp_path / "file1.txt"
        # Use a directory path to force write failure
        file2 = tmp_path / "subdir"
        file2.mkdir()  # Create as directory, not file

        file1.write_text("content1")

        strategy = FileRollbackStrategy()
        snapshot = RollbackSnapshot(
            action={},
            context={},
            file_snapshots={
                str(file1): "content1",
                str(file2): "content2"  # This is a directory, write will fail
            },
            metadata={
                f"{str(file1)}_existed": True,
                f"{str(file2)}_existed": True
            }
        )

        # Modify file1
        file1.write_text("modified1")

        # Rollback (file2 will fail because it's a directory)
        result = strategy.execute_rollback(snapshot)

        assert result.success is False
        assert result.status == RollbackStatus.PARTIAL
        assert str(file1) in result.reverted_items
        assert str(file2) in result.failed_items


class TestStateRollbackStrategy:
    """Test state rollback strategy."""

    def test_create_snapshot_with_state_getter(self):
        """Test snapshot creation with state getter."""
        current_state = {"counter": 10, "flag": True}

        strategy = StateRollbackStrategy(
            state_getter=lambda: current_state
        )

        snapshot = strategy.create_snapshot(
            action={"tool": "increment"},
            context={}
        )

        assert snapshot.state_snapshots == {"counter": 10, "flag": True}

    def test_create_snapshot_no_state_getter(self):
        """Test snapshot creation without state getter."""
        strategy = StateRollbackStrategy()

        snapshot = strategy.create_snapshot(
            action={"tool": "test"},
            context={}
        )

        assert snapshot.state_snapshots == {}

    def test_execute_rollback(self):
        """Test state rollback execution."""
        strategy = StateRollbackStrategy()
        snapshot = RollbackSnapshot(
            action={},
            context={},
            state_snapshots={"counter": 5, "flag": False}
        )

        result = strategy.execute_rollback(snapshot)

        assert result.success is True
        assert result.status == RollbackStatus.COMPLETED
        assert "counter" in result.reverted_items
        assert "flag" in result.reverted_items


class TestCompositeRollbackStrategy:
    """Test composite rollback strategy."""

    def test_initialization(self):
        """Test composite strategy initialization."""
        file_strategy = FileRollbackStrategy()
        state_strategy = StateRollbackStrategy()

        composite = CompositeRollbackStrategy(
            strategies=[file_strategy, state_strategy]
        )

        assert len(composite.strategies) == 2

    def test_add_strategy(self):
        """Test adding strategy to composite."""
        composite = CompositeRollbackStrategy()
        strategy = FileRollbackStrategy()

        composite.add_strategy(strategy)

        assert len(composite.strategies) == 1

    def test_create_snapshot_combines_strategies(self, tmp_path):
        """Test composite snapshot combines multiple strategies."""
        # Setup file
        test_file = tmp_path / "test.txt"
        test_file.write_text("content")

        # Setup state
        current_state = {"counter": 5}

        # Create composite
        composite = CompositeRollbackStrategy()
        composite.add_strategy(FileRollbackStrategy())
        composite.add_strategy(StateRollbackStrategy(
            state_getter=lambda: current_state
        ))

        # Create snapshot
        snapshot = composite.create_snapshot(
            action={"path": str(test_file)},
            context={}
        )

        # Should have both file and state snapshots
        assert str(test_file) in snapshot.file_snapshots
        assert snapshot.state_snapshots == {"counter": 5}
        assert snapshot.metadata["strategy_file_rollback"] is True
        assert snapshot.metadata["strategy_state_rollback"] is True

    def test_execute_rollback_all_strategies(self, tmp_path):
        """Test composite rollback executes all strategies."""
        # Setup
        test_file = tmp_path / "test.txt"
        test_file.write_text("original")

        composite = CompositeRollbackStrategy()
        composite.add_strategy(FileRollbackStrategy())
        composite.add_strategy(StateRollbackStrategy())

        snapshot = composite.create_snapshot(
            action={"path": str(test_file)},
            context={}
        )

        # Modify file
        test_file.write_text("modified")

        # Rollback
        result = composite.execute_rollback(snapshot)

        assert result.success is True
        assert result.status == RollbackStatus.COMPLETED
        assert len(result.reverted_items) > 0


class TestRollbackManager:
    """Test rollback manager."""

    def test_initialization(self):
        """Test manager initialization."""
        manager = RollbackManager()

        assert manager.snapshot_count() == 0
        assert manager.default_strategy is not None

    def test_register_strategy(self):
        """Test registering custom strategy."""
        manager = RollbackManager()
        strategy = FileRollbackStrategy()

        manager.register_strategy("file", strategy)

        # Strategy should be registered
        assert "file" in manager._strategies

    def test_create_snapshot(self, tmp_path):
        """Test snapshot creation."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("content")

        manager = RollbackManager()
        snapshot = manager.create_snapshot(
            action={"tool": "write_file", "path": str(test_file)},
            context={"agent": "writer"}
        )

        assert snapshot is not None
        assert snapshot.id is not None
        assert manager.snapshot_count() == 1

    def test_create_snapshot_with_specific_strategy(self, tmp_path):
        """Test snapshot creation with specific strategy."""
        manager = RollbackManager()
        state_strategy = StateRollbackStrategy()
        manager.register_strategy("state", state_strategy)

        snapshot = manager.create_snapshot(
            action={"tool": "increment"},
            context={},
            strategy_name="state"
        )

        assert snapshot is not None

    def test_execute_rollback(self, tmp_path):
        """Test rollback execution."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("original")

        manager = RollbackManager()

        # Create snapshot
        snapshot = manager.create_snapshot(
            action={"path": str(test_file)},
            context={}
        )

        # Modify file
        test_file.write_text("modified")

        # Rollback
        result = manager.execute_rollback(snapshot.id)

        assert result.success is True
        assert test_file.read_text() == "original"
        assert len(manager.get_history()) == 1

    def test_execute_rollback_nonexistent_snapshot(self):
        """Test rollback with nonexistent snapshot."""
        manager = RollbackManager()

        with pytest.raises(ValueError, match="Snapshot .* not found"):
            manager.execute_rollback("nonexistent-id")

    def test_get_snapshot(self, tmp_path):
        """Test getting snapshot by ID."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("content")

        manager = RollbackManager()
        created = manager.create_snapshot(
            action={"path": str(test_file)},
            context={}
        )

        retrieved = manager.get_snapshot(created.id)

        assert retrieved is created
        assert retrieved.id == created.id

    def test_get_nonexistent_snapshot(self):
        """Test getting snapshot that doesn't exist."""
        manager = RollbackManager()

        snapshot = manager.get_snapshot("nonexistent-id")

        assert snapshot is None

    def test_list_snapshots(self, tmp_path):
        """Test listing all snapshots."""
        manager = RollbackManager()

        # Create multiple snapshots
        for i in range(3):
            file_path = tmp_path / f"file{i}.txt"
            file_path.write_text(f"content{i}")
            manager.create_snapshot(
                action={"path": str(file_path)},
                context={}
            )

        snapshots = manager.list_snapshots()

        assert len(snapshots) == 3

    def test_get_history(self, tmp_path):
        """Test getting rollback history."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("original")

        manager = RollbackManager()

        # Create and rollback multiple snapshots
        for i in range(3):
            snapshot = manager.create_snapshot(
                action={"path": str(test_file)},
                context={}
            )
            test_file.write_text(f"modified{i}")
            manager.execute_rollback(snapshot.id)

        history = manager.get_history()

        assert len(history) == 3

    def test_on_rollback_callback(self, tmp_path):
        """Test rollback callback."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("original")

        manager = RollbackManager()
        callback_called = []

        def on_rollback(result: RollbackResult):
            callback_called.append(result.snapshot_id)

        manager.on_rollback(on_rollback)

        # Create and rollback
        snapshot = manager.create_snapshot(
            action={"path": str(test_file)},
            context={}
        )
        test_file.write_text("modified")
        manager.execute_rollback(snapshot.id)

        assert len(callback_called) == 1
        assert callback_called[0] == snapshot.id

    def test_callback_exception_doesnt_break_rollback(self, tmp_path):
        """Test that callback exceptions don't break rollback."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("original")

        manager = RollbackManager()

        def failing_callback(result):
            raise RuntimeError("Callback failed")

        manager.on_rollback(failing_callback)

        # Create and rollback
        snapshot = manager.create_snapshot(
            action={"path": str(test_file)},
            context={}
        )
        test_file.write_text("modified")

        # Should not raise exception
        result = manager.execute_rollback(snapshot.id)

        assert result.success is True
        assert test_file.read_text() == "original"

    def test_clear_snapshots(self, tmp_path):
        """Test clearing all snapshots."""
        manager = RollbackManager()

        for i in range(3):
            file_path = tmp_path / f"file{i}.txt"
            file_path.write_text(f"content{i}")
            manager.create_snapshot(
                action={"path": str(file_path)},
                context={}
            )

        assert manager.snapshot_count() == 3

        manager.clear_snapshots()

        assert manager.snapshot_count() == 0

    def test_clear_history(self, tmp_path):
        """Test clearing rollback history."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("original")

        manager = RollbackManager()

        # Create history
        snapshot = manager.create_snapshot(
            action={"path": str(test_file)},
            context={}
        )
        manager.execute_rollback(snapshot.id)

        assert len(manager.get_history()) == 1

        manager.clear_history()

        assert len(manager.get_history()) == 0

    def test_repr(self):
        """Test string representation."""
        manager = RollbackManager()

        repr_str = repr(manager)

        assert "RollbackManager" in repr_str
        assert "snapshots=0" in repr_str


class TestIntegration:
    """Integration tests for rollback system."""

    def test_full_workflow(self, tmp_path):
        """Test complete rollback workflow."""
        # Setup
        config_file = tmp_path / "config.yaml"
        config_file.write_text("version: 1.0\nmode: production")

        manager = RollbackManager()

        # Phase 1: Create snapshot before risky operation
        snapshot = manager.create_snapshot(
            action={
                "tool": "update_config",
                "file": str(config_file)
            },
            context={
                "agent": "config_updater",
                "reason": "Update production config"
            }
        )

        # Phase 2: Execute risky operation
        config_file.write_text("version: 2.0\nmode: experimental\ndebug: true")

        # Verify change
        assert "experimental" in config_file.read_text()

        # Phase 3: Rollback (operation failed)
        result = manager.execute_rollback(snapshot.id)

        # Verify rollback
        assert result.success is True
        assert result.status == RollbackStatus.COMPLETED
        content = config_file.read_text()
        assert "version: 1.0" in content
        assert "production" in content
        assert "experimental" not in content

    def test_multiple_file_transaction(self, tmp_path):
        """Test rollback of multi-file transaction."""
        # Setup multiple files
        file1 = tmp_path / "service1.yaml"
        file2 = tmp_path / "service2.yaml"
        file3 = tmp_path / "service3.yaml"

        file1.write_text("service1: running")
        file2.write_text("service2: running")
        file3.write_text("service3: running")

        manager = RollbackManager()

        # Snapshot before batch update
        snapshot = manager.create_snapshot(
            action={
                "tool": "batch_update",
                "files": [str(file1), str(file2), str(file3)]
            },
            context={"operation": "upgrade_all"}
        )

        # Update all files
        file1.write_text("service1: upgrading")
        file2.write_text("service2: upgrading")
        file3.write_text("service3: upgrading")

        # Rollback entire transaction
        result = manager.execute_rollback(snapshot.id)

        # All files should be restored
        assert result.success is True
        assert file1.read_text() == "service1: running"
        assert file2.read_text() == "service2: running"
        assert file3.read_text() == "service3: running"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
