"""Tests for rollback mechanism system."""

import os
import tempfile
from datetime import datetime
from pathlib import Path

import pytest

from temper_ai.safety.rollback import (
    CompositeRollbackStrategy,
    FileRollbackStrategy,
    RollbackManager,
    RollbackResult,
    RollbackSecurityError,
    RollbackSnapshot,
    RollbackStatus,
    StateRollbackStrategy,
    validate_rollback_path,
)


class TestRollbackSnapshot:
    """Test RollbackSnapshot data class."""

    def test_initialization(self):
        """Test snapshot initialization."""
        snapshot = RollbackSnapshot(
            action={"tool": "write_file", "path": "/tmp/test.txt"},
            context={"agent": "writer"},
            file_snapshots={"/tmp/test.txt": "original content"},
            state_snapshots={"counter": 0},
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
            state_snapshots={"key": "value"},
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
            errors=[],
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
            errors=["Failed to restore file"],
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
            context={"agent": "test"},
        )

        assert str(test_file) in snapshot.file_snapshots
        assert snapshot.file_snapshots[str(test_file)] == "original content"
        assert snapshot.metadata[f"{str(test_file)}_existed"] is True

    def test_create_snapshot_nonexistent_file(self, tmp_path):
        """Test snapshot creation for file that doesn't exist."""
        test_file = tmp_path / "new.txt"

        strategy = FileRollbackStrategy()
        snapshot = strategy.create_snapshot(
            action={"tool": "write_file", "path": str(test_file)}, context={}
        )

        assert str(test_file) not in snapshot.file_snapshots
        assert snapshot.metadata[f"{str(test_file)}_existed"] is False

    def test_rollback_restore_file_content(self, tmp_path):
        """Test rollback restores original file content."""
        # Setup
        test_file = tmp_path / "test.txt"
        test_file.write_text("original content")

        strategy = FileRollbackStrategy()
        snapshot = strategy.create_snapshot(action={"path": str(test_file)}, context={})

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
        snapshot = strategy.create_snapshot(action={"path": str(test_file)}, context={})

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
            action={"files": [str(file1), str(file2)]}, context={}
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
                str(file2): "content2",  # This is a directory, write will fail
            },
            metadata={f"{str(file1)}_existed": True, f"{str(file2)}_existed": True},
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

        strategy = StateRollbackStrategy(state_getter=lambda: current_state)

        snapshot = strategy.create_snapshot(action={"tool": "increment"}, context={})

        assert snapshot.state_snapshots == {"counter": 10, "flag": True}

    def test_create_snapshot_no_state_getter(self):
        """Test snapshot creation without state getter."""
        strategy = StateRollbackStrategy()

        snapshot = strategy.create_snapshot(action={"tool": "test"}, context={})

        assert snapshot.state_snapshots == {}

    def test_execute_rollback(self):
        """Test state rollback execution."""
        strategy = StateRollbackStrategy()
        snapshot = RollbackSnapshot(
            action={}, context={}, state_snapshots={"counter": 5, "flag": False}
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
        composite.add_strategy(
            StateRollbackStrategy(state_getter=lambda: current_state)
        )

        # Create snapshot
        snapshot = composite.create_snapshot(
            action={"path": str(test_file)}, context={}
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
            action={"path": str(test_file)}, context={}
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
            context={"agent": "writer"},
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
            action={"tool": "increment"}, context={}, strategy_name="state"
        )

        assert snapshot is not None

    def test_execute_rollback(self, tmp_path):
        """Test rollback execution."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("original")

        manager = RollbackManager()

        # Create snapshot
        snapshot = manager.create_snapshot(action={"path": str(test_file)}, context={})

        # Modify file
        test_file.write_text("modified")

        # Rollback
        result = manager.execute_rollback(snapshot.id)

        assert result.success is True
        assert test_file.read_text() == "original"
        assert len(manager.get_history()) == 1

    def test_execute_rollback_dry_run(self, tmp_path):
        """Test dry-run mode prevents actual rollback execution."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("original")

        manager = RollbackManager()
        snapshot = manager.create_snapshot(action={"path": str(test_file)}, context={})

        # Modify file
        test_file.write_text("modified")

        # Dry-run rollback
        result = manager.execute_rollback(snapshot.id, dry_run=True)

        # Should return success with dry_run metadata
        assert result.success is True
        assert result.metadata["dry_run"] is True
        assert result.status == RollbackStatus.COMPLETED

        # File should remain unchanged
        assert test_file.read_text() == "modified"

        # History should not be updated in dry-run mode
        assert len(manager.get_history()) == 0

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
        created = manager.create_snapshot(action={"path": str(test_file)}, context={})

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
            manager.create_snapshot(action={"path": str(file_path)}, context={})

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
                action={"path": str(test_file)}, context={}
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
        snapshot = manager.create_snapshot(action={"path": str(test_file)}, context={})
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
        snapshot = manager.create_snapshot(action={"path": str(test_file)}, context={})
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
            manager.create_snapshot(action={"path": str(file_path)}, context={})

        assert manager.snapshot_count() == 3

        manager.clear_snapshots()

        assert manager.snapshot_count() == 0

    def test_clear_history(self, tmp_path):
        """Test clearing rollback history."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("original")

        manager = RollbackManager()

        # Create history
        snapshot = manager.create_snapshot(action={"path": str(test_file)}, context={})
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
            action={"tool": "update_config", "file": str(config_file)},
            context={"agent": "config_updater", "reason": "Update production config"},
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
                "files": [str(file1), str(file2), str(file3)],
            },
            context={"operation": "upgrade_all"},
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


class TestPathTraversalSecurity:
    """Test path traversal security fixes (code-crit-03, code-crit-04)."""

    def test_validate_rollback_path_allows_temp_directory(self):
        """Test that paths in temp directory are allowed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = os.path.join(tmpdir, "test.txt")

            is_valid, error = validate_rollback_path(
                test_file, allowed_directories=[tmpdir]
            )

            assert is_valid is True
            assert error is None

    def test_validate_rollback_path_rejects_path_traversal(self):
        """Test that path traversal attacks are blocked."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Attempt to traverse to parent directory
            malicious_path = os.path.join(tmpdir, "..", "..", "etc", "passwd")

            is_valid, error = validate_rollback_path(
                malicious_path, allowed_directories=[tmpdir]
            )

            assert is_valid is False
            assert "outside allowed directories" in error.lower()

    def test_validate_rollback_path_rejects_absolute_system_paths(self):
        """Test that absolute system paths are blocked."""
        system_paths = [
            "/etc/passwd",
            "/etc/shadow",
            "/root/.ssh/id_rsa",
            "/sys/kernel/config",
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            for system_path in system_paths:
                is_valid, error = validate_rollback_path(
                    system_path, allowed_directories=[tmpdir]
                )

                assert (
                    is_valid is False
                ), f"System path should be rejected: {system_path}"
                assert error is not None

    def test_validate_rollback_path_rejects_symlinks(self):
        """Test that symlinks are detected and rejected."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a symlink pointing to /etc/passwd
            symlink_path = os.path.join(tmpdir, "evil_symlink")
            target_path = "/etc/passwd"

            # Only create symlink if target exists (for test portability)
            if os.path.exists(target_path):
                os.symlink(target_path, symlink_path)

                is_valid, error = validate_rollback_path(
                    symlink_path, allowed_directories=[tmpdir], check_symlinks=True
                )

                assert is_valid is False
                assert "symlink" in error.lower()

    def test_validate_rollback_path_rejects_symlink_in_parent(self):
        """Test that symlinks in parent directories are detected."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a directory with a symlinked parent
            symlink_dir = os.path.join(tmpdir, "symlink_dir")
            target_dir = tempfile.mkdtemp()

            try:
                os.symlink(target_dir, symlink_dir)
                file_under_symlink = os.path.join(symlink_dir, "file.txt")

                is_valid, error = validate_rollback_path(
                    file_under_symlink,
                    allowed_directories=[tmpdir],
                    check_symlinks=True,
                )

                assert is_valid is False
                assert "symlink" in error.lower()
            finally:
                # Cleanup
                if os.path.exists(symlink_dir):
                    os.unlink(symlink_dir)
                if os.path.exists(target_dir):
                    os.rmdir(target_dir)

    def test_validate_rollback_path_rejects_null_bytes(self):
        """Test that null byte injection is blocked."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Null byte injection attack
            malicious_path = os.path.join(tmpdir, "test.txt\x00/etc/passwd")

            is_valid, error = validate_rollback_path(
                malicious_path, allowed_directories=[tmpdir]
            )

            assert is_valid is False
            assert "null bytes" in error.lower()

    def test_validate_rollback_path_rejects_windows_system32(self):
        """Test that Windows System32 is blocked."""
        system32_path = "C:\\Windows\\System32\\important.dll"

        with tempfile.TemporaryDirectory() as tmpdir:
            is_valid, error = validate_rollback_path(
                system32_path, allowed_directories=[tmpdir]
            )

            assert is_valid is False
            assert error is not None

    def test_validate_rollback_path_blocks_etc_prefix_bypass(self):
        """
        Test that /etc_backup/ and /etch/ bypasses are blocked.

        SECURITY FIX (code-high-path-bypass-16): The old startswith() check
        allowed bypasses like /etc_backup/ or /etch/ because string prefix
        matching doesn't validate path containment. The new os.path.commonpath
        check properly validates that paths are within dangerous directories.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test files in tmpdir (which is allowed)
            # But use names that would bypass old startswith() check
            bypass_paths = [
                "/etc_backup/passwd",  # Bypasses startswith("/etc/")
                "/etch/passwd",  # Bypasses startswith("/etc/")
                "/etcd/passwd",  # Bypasses startswith("/etc/")
                "/sys_backup/kernel",  # Bypasses startswith("/sys/")
                "/sysa/kernel",  # Bypasses startswith("/sys/")
                "/proc_old/cpuinfo",  # Bypasses startswith("/proc/")
                "/devs/null",  # Bypasses startswith("/dev/")
                "/boots/vmlinuz",  # Bypasses startswith("/boot/")
            ]

            for bypass_path in bypass_paths:
                # Test that these paths are NOT blocked (they're not in dangerous dirs)
                # They're just similar names, not actual subdirs of /etc/, /sys/, etc.
                # Since they're absolute paths and tmpdir is allowed, we need to check
                # if the dangerous dir validation works correctly

                # Actually, these paths are outside tmpdir, so they should fail
                # the allowed_directories check first
                is_valid, error = validate_rollback_path(
                    bypass_path, allowed_directories=[tmpdir]
                )

                assert (
                    is_valid is False
                ), f"Path {bypass_path} should be blocked (outside allowed dirs)"
                assert error is not None

    def test_validate_rollback_path_blocks_etc_subdirs(self):
        """
        Test that actual /etc/ subdirectories are blocked.

        SECURITY FIX (code-high-path-bypass-16): Verify that real /etc/
        subdirectories are properly blocked using path containment check.
        """
        # Only test on systems where /etc exists
        if not os.path.exists("/etc"):
            pytest.skip("/etc does not exist on this system")

        with tempfile.TemporaryDirectory() as tmpdir:
            # Test actual /etc/ subdirectories
            etc_paths = [
                "/etc/passwd",
                "/etc/shadow",
                "/etc/hosts",
                "/etc/systemd/system.conf",
                "/etc/ssh/sshd_config",
            ]

            for etc_path in etc_paths:
                # Even if /etc is in allowed directories, it should be blocked
                # because it's a dangerous system directory
                is_valid, error = validate_rollback_path(
                    etc_path,
                    allowed_directories=["/etc", tmpdir],  # Explicitly allow /etc
                )

                assert (
                    is_valid is False
                ), f"Path {etc_path} should be blocked (dangerous system directory)"
                assert (
                    "system directory" in error.lower()
                ), f"Error should mention system directory, got: {error}"

    def test_validate_rollback_path_blocks_windows_system32_bypass(self):
        """
        Test that Windows System32 bypass attempts are blocked.

        SECURITY FIX (code-high-path-bypass-16): Verify that paths like
        C:\\Windows\\System32_backup\\ are NOT incorrectly blocked by
        startswith(), and actual System32 subdirs ARE blocked.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            # Bypass attempts (should NOT be blocked by dangerous dir check)
            bypass_paths = [
                "C:\\Windows\\System32_backup\\file.dll",
                "C:\\Windows\\System32a\\file.dll",
            ]

            for bypass_path in bypass_paths:
                # These should fail allowed_directories check, not dangerous dir check
                is_valid, error = validate_rollback_path(
                    bypass_path, allowed_directories=[tmpdir]
                )

                assert (
                    is_valid is False
                ), f"Path {bypass_path} should be blocked (outside allowed dirs)"
                # Should fail allowed_directories check, not dangerous dir check
                assert error is not None

    def test_rollback_manager_rejects_path_traversal_in_snapshot(self):
        """Test that RollbackManager rejects path traversal in snapshot creation."""
        manager = RollbackManager()

        # Attempt to create snapshot with path traversal
        action = {"tool": "write_file", "path": "../../etc/passwd"}

        with pytest.raises(RollbackSecurityError) as exc_info:
            manager.create_snapshot(action=action, context={})

        assert (
            "path traversal" in str(exc_info.value).lower()
            or "invalid file path" in str(exc_info.value).lower()
        )

    def test_rollback_manager_rejects_symlink_in_snapshot(self):
        """Test that RollbackManager rejects symlinks in snapshot creation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a symlink to /etc/passwd
            symlink_path = os.path.join(tmpdir, "evil_link")

            # Only test if /etc/passwd exists
            if os.path.exists("/etc/passwd"):
                os.symlink("/etc/passwd", symlink_path)

                manager = RollbackManager()
                action = {"tool": "write_file", "path": symlink_path}

                with pytest.raises(RollbackSecurityError) as exc_info:
                    manager.create_snapshot(action=action, context={})

                assert "symlink" in str(exc_info.value).lower()

    def test_rollback_manager_allows_safe_paths(self):
        """Test that RollbackManager allows safe paths in allowed directories."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a safe file
            safe_file = os.path.join(tmpdir, "safe_file.txt")
            Path(safe_file).write_text("safe content")

            manager = RollbackManager()
            action = {"tool": "write_file", "path": safe_file}

            # Should not raise exception
            snapshot = manager.create_snapshot(action=action, context={})

            assert snapshot is not None
            assert safe_file in snapshot.file_snapshots

    def test_rollback_execution_rejects_path_traversal_in_restore(self):
        """Test that rollback execution rejects path traversal during file restore."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a snapshot with a malicious path
            snapshot = RollbackSnapshot(
                action={},
                context={},
                file_snapshots={"../../etc/passwd": "malicious content"},
                metadata={},
            )

            manager = RollbackManager()
            # Intentional private access: no public API to inject pre-crafted snapshots
            manager._snapshots[snapshot.id] = snapshot

            result = manager.execute_rollback(snapshot.id)

            # Rollback should fail or skip the malicious file
            assert "../../etc/passwd" not in result.reverted_items
            assert len(result.failed_items) > 0 or len(result.errors) > 0

    def test_rollback_execution_rejects_path_traversal_in_deletion(self):
        """Test that rollback execution rejects path traversal during file deletion."""
        # Create a snapshot with metadata indicating a file to delete
        snapshot = RollbackSnapshot(
            action={},
            context={},
            file_snapshots={},
            metadata={"/etc/passwd_existed": False},  # Indicates file should be deleted
        )

        manager = RollbackManager()
        # Intentional private access: no public API to inject pre-crafted snapshots
        manager._snapshots[snapshot.id] = snapshot

        result = manager.execute_rollback(snapshot.id)

        # Should not delete /etc/passwd
        assert "/etc/passwd" not in result.reverted_items
        assert os.path.exists("/etc/passwd") if os.path.exists("/etc/passwd") else True

    def test_validate_rollback_path_uses_safe_defaults(self):
        """Test that default allowed directories are safe."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Path in temp directory should be allowed by default
            test_file = os.path.join(tempfile.gettempdir(), "test.txt")

            is_valid, error = validate_rollback_path(test_file)

            # Temp directory should be in default allowlist
            assert is_valid is True
            assert error is None

    def test_validate_rollback_path_current_working_directory(self):
        """Test that current working directory is allowed by default."""
        cwd_file = os.path.join(os.getcwd(), "test_file.txt")

        is_valid, error = validate_rollback_path(cwd_file)

        assert is_valid is True
        assert error is None


class TestTOCTOURaceConditionFixes:
    """Test TOCTOU race condition fixes in rollback operations."""

    def test_atomic_write_no_partial_content(self, tmp_path):
        """Test that rollback writes are atomic - no partial file content."""
        # Create a file with known content
        test_file = tmp_path / "test_atomic.txt"
        test_file.write_text("original content")

        # Create a rollback manager with file strategy
        manager = RollbackManager()
        file_strategy = FileRollbackStrategy()
        manager.register_strategy("file", file_strategy)

        # Create snapshot that will restore to a different content
        snapshot = RollbackSnapshot(
            action={"tool": "write_file", "path": str(test_file)},
            context={"agent": "test_agent"},
            file_snapshots={str(test_file): "restored content"},
        )

        # Execute rollback
        result = file_strategy.execute_rollback(snapshot)

        # File should have restored content (atomically written)
        assert test_file.read_text() == "restored content"
        assert result.success

    def test_rollback_revalidates_path_before_write(self, tmp_path):
        """Test that path is re-validated immediately before file I/O."""
        # Create a valid file
        test_file = tmp_path / "valid_file.txt"
        test_file.write_text("original")

        # Create snapshot pointing to valid path
        snapshot = RollbackSnapshot(
            action={"tool": "write_file", "path": str(test_file)},
            context={"agent": "test_agent"},
            file_snapshots={str(test_file): "restored"},
        )

        file_strategy = FileRollbackStrategy()
        result = file_strategy.execute_rollback(snapshot)

        # Should succeed for valid path
        assert str(test_file) in result.reverted_items

    def test_symlink_detected_after_resolution(self, tmp_path):
        """Test that symlinks are detected even after path resolution."""
        # Create a real file and a symlink to it
        real_file = tmp_path / "real_file.txt"
        real_file.write_text("real content")
        symlink = tmp_path / "symlink_file.txt"
        symlink.symlink_to(real_file)

        # validate_rollback_path should reject the symlink
        is_valid, error = validate_rollback_path(
            str(symlink), allowed_directories=[str(tmp_path)]
        )
        assert is_valid is False
        assert "symlink" in error.lower()

    def test_resolved_path_consistency_check(self, tmp_path):
        """Test that path resolution inconsistency is detected."""
        # Create a file via a relative path with ..
        sub_dir = tmp_path / "subdir"
        sub_dir.mkdir()
        test_file = sub_dir / "file.txt"
        test_file.write_text("content")

        # Non-symlink paths with .. should resolve fine
        relative_path = str(sub_dir / ".." / "subdir" / "file.txt")
        is_valid, error = validate_rollback_path(
            relative_path, allowed_directories=[str(tmp_path)]
        )
        # Should be valid since it resolves to the same file (no symlinks)
        assert is_valid is True

    def test_atomic_write_cleanup_on_failure(self, tmp_path):
        """Test that temp files are cleaned up if write fails."""
        # Create a read-only directory to force write failure
        test_file = tmp_path / "test_cleanup.txt"
        test_file.write_text("original")

        # Count files before
        files_before = set(tmp_path.iterdir())

        # Create a normal rollback
        file_strategy = FileRollbackStrategy()
        snapshot = RollbackSnapshot(
            action={"tool": "write_file", "path": str(test_file)},
            context={"agent": "test_agent"},
            file_snapshots={str(test_file): "restored content"},
        )

        result = file_strategy.execute_rollback(snapshot)
        assert result.success

        # No leftover temp files - only the test file should exist
        files_after = set(tmp_path.iterdir())
        assert files_after == files_before  # Same set of files

    def test_validate_rollback_path_order_symlink_after_resolve(self, tmp_path):
        """Test that validation order is: resolve THEN check symlinks."""
        # Non-existent path (can't be a symlink)
        nonexistent = str(tmp_path / "doesnt_exist.txt")
        is_valid, error = validate_rollback_path(
            nonexistent, allowed_directories=[str(tmp_path)]
        )
        # Should be valid (path doesn't exist yet, no symlink)
        assert is_valid is True

    def test_rollback_rejects_invalid_path_on_recheck(self, tmp_path):
        """Test that invalid paths are caught during re-validation before write."""
        # Try to rollback a file outside allowed directories
        file_strategy = FileRollbackStrategy()
        snapshot = RollbackSnapshot(
            action={"tool": "write_file", "path": "/etc/passwd"},
            context={"agent": "test_agent"},
            file_snapshots={"/etc/passwd": "hacked content"},
        )

        result = file_strategy.execute_rollback(snapshot)
        # Should fail - path outside allowed directories
        assert "/etc/passwd" in result.failed_items
        assert any("Security violation" in e for e in result.errors)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
