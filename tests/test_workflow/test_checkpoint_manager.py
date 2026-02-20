"""Tests for CheckpointManager.

Tests the high-level checkpoint management functionality including:
- Automatic checkpoint saving
- Checkpoint loading and resume
- Cleanup of old checkpoints
- Different checkpoint strategies
"""
import shutil
import tempfile

import pytest

from temper_ai.workflow.checkpoint_backends import CheckpointNotFoundError, FileCheckpointBackend
from temper_ai.workflow.checkpoint_manager import (
    CheckpointManager,
    CheckpointStrategy,
    create_checkpoint_manager,
)
from temper_ai.workflow.domain_state import WorkflowDomainState


class TestCheckpointManager:
    """Test high-level checkpoint manager."""

    @pytest.fixture
    def temp_dir(self):
        """Create temporary directory for checkpoints."""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir)

    @pytest.fixture
    def backend(self, temp_dir):
        """Create file backend with temp directory."""
        return FileCheckpointBackend(checkpoint_dir=temp_dir)

    @pytest.fixture
    def manager(self, backend):
        """Create checkpoint manager with file backend."""
        return CheckpointManager(backend=backend)

    @pytest.fixture
    def sample_domain_state(self):
        """Create sample domain state for testing."""
        domain = WorkflowDomainState(
            workflow_id="wf-test-123",
            input="Analyze market trends"
        )
        domain.set_stage_output("research", {"findings": ["trend1"]})
        return domain

    def test_manager_initialization(self, manager):
        """Test manager initialization with defaults."""
        assert isinstance(manager.backend, FileCheckpointBackend)
        assert manager.strategy == CheckpointStrategy.EVERY_STAGE
        assert manager.max_checkpoints == 10

    def test_manager_with_custom_strategy(self, backend):
        """Test manager with custom checkpoint strategy."""
        manager = CheckpointManager(
            backend=backend,
            strategy=CheckpointStrategy.MANUAL
        )
        assert manager.strategy == CheckpointStrategy.MANUAL

    def test_save_checkpoint(self, manager, sample_domain_state):
        """Test saving a checkpoint."""
        checkpoint_id = manager.save_checkpoint(sample_domain_state)

        assert checkpoint_id is not None
        assert checkpoint_id.startswith("cp-")

    def test_save_checkpoint_with_metadata(self, manager, sample_domain_state):
        """Test saving checkpoint with custom metadata."""
        metadata = {"user": "test-user"}
        checkpoint_id = manager.save_checkpoint(
            sample_domain_state,
            metadata=metadata
        )

        # Verify metadata is stored
        checkpoints = manager.list_checkpoints("wf-test-123")
        assert len(checkpoints) == 1
        assert "user" in checkpoints[0]["metadata"]

    def test_load_checkpoint(self, manager, sample_domain_state):
        """Test loading a saved checkpoint."""
        # Save checkpoint
        checkpoint_id = manager.save_checkpoint(sample_domain_state)

        # Load it back
        loaded_domain = manager.load_checkpoint("wf-test-123", checkpoint_id)

        assert loaded_domain.workflow_id == "wf-test-123"
        assert loaded_domain.input == "Analyze market trends"
        assert loaded_domain.stage_outputs == {"research": {"findings": ["trend1"]}}

    def test_load_latest_checkpoint(self, manager, sample_domain_state):
        """Test loading latest checkpoint without ID."""
        # Save multiple checkpoints
        manager.save_checkpoint(sample_domain_state)

        sample_domain_state.set_stage_output("analysis", {"insights": ["insight1"]})
        manager.save_checkpoint(sample_domain_state)

        # Load latest
        loaded_domain = manager.load_checkpoint("wf-test-123")

        assert loaded_domain.current_stage == "analysis"
        assert "analysis" in loaded_domain.stage_outputs

    def test_load_nonexistent_checkpoint(self, manager):
        """Test loading nonexistent checkpoint raises error."""
        with pytest.raises(CheckpointNotFoundError):
            manager.load_checkpoint("wf-nonexistent")

    def test_list_checkpoints(self, manager, sample_domain_state):
        """Test listing checkpoints."""
        # Save multiple checkpoints
        manager.save_checkpoint(sample_domain_state)

        sample_domain_state.set_stage_output("analysis", {"data": "value"})
        manager.save_checkpoint(sample_domain_state)

        checkpoints = manager.list_checkpoints("wf-test-123")

        assert len(checkpoints) == 2
        assert checkpoints[0]["stage"] == "analysis"  # Newest first
        assert checkpoints[1]["stage"] == "research"

    def test_delete_checkpoint(self, manager, sample_domain_state):
        """Test deleting a checkpoint."""
        checkpoint_id = manager.save_checkpoint(sample_domain_state)

        success = manager.delete_checkpoint("wf-test-123", checkpoint_id)
        assert success is True

        # Verify it's gone
        with pytest.raises(CheckpointNotFoundError):
            manager.load_checkpoint("wf-test-123", checkpoint_id)

    def test_get_latest_checkpoint_id(self, manager, sample_domain_state):
        """Test getting latest checkpoint ID."""
        # No checkpoints initially
        latest = manager.get_latest_checkpoint_id("wf-test-123")
        assert latest is None

        # Save checkpoint
        checkpoint_id = manager.save_checkpoint(sample_domain_state)

        # Get latest
        latest = manager.get_latest_checkpoint_id("wf-test-123")
        assert latest == checkpoint_id

    def test_has_checkpoint(self, manager, sample_domain_state):
        """Test checking if workflow has checkpoints."""
        # No checkpoints initially
        assert manager.has_checkpoint("wf-test-123") is False

        # Save checkpoint
        manager.save_checkpoint(sample_domain_state)

        # Should have checkpoint now
        assert manager.has_checkpoint("wf-test-123") is True

    def test_should_checkpoint_every_stage(self, manager):
        """Test should_checkpoint with EVERY_STAGE strategy."""
        assert manager.should_checkpoint("research") is True
        assert manager.should_checkpoint("analysis") is True

    def test_should_checkpoint_manual(self, backend):
        """Test should_checkpoint with MANUAL strategy."""
        manager = CheckpointManager(
            backend=backend,
            strategy=CheckpointStrategy.MANUAL
        )

        assert manager.should_checkpoint("research") is False

    def test_should_checkpoint_disabled(self, backend):
        """Test should_checkpoint with DISABLED strategy."""
        manager = CheckpointManager(
            backend=backend,
            strategy=CheckpointStrategy.DISABLED
        )

        assert manager.should_checkpoint("research") is False

    def test_should_checkpoint_periodic(self, backend):
        """Test should_checkpoint with PERIODIC strategy."""
        manager = CheckpointManager(
            backend=backend,
            strategy=CheckpointStrategy.PERIODIC,
            periodic_interval=300  # 5 minutes
        )

        # Not enough time elapsed
        assert manager.should_checkpoint("research", elapsed_time=100) is False

        # Enough time elapsed
        assert manager.should_checkpoint("research", elapsed_time=400) is True

    def test_save_checkpoint_disabled_strategy(self, backend, sample_domain_state):
        """Test that checkpoints are skipped with DISABLED strategy."""
        manager = CheckpointManager(
            backend=backend,
            strategy=CheckpointStrategy.DISABLED
        )

        checkpoint_id = manager.save_checkpoint(sample_domain_state)
        assert checkpoint_id == ""  # Empty string indicates skipped

    def test_save_checkpoint_force_with_disabled(self, backend, sample_domain_state):
        """Test forcing checkpoint save even with DISABLED strategy."""
        manager = CheckpointManager(
            backend=backend,
            strategy=CheckpointStrategy.DISABLED
        )

        checkpoint_id = manager.save_checkpoint(sample_domain_state, force=True)
        assert checkpoint_id != ""  # Should save when forced
        assert checkpoint_id.startswith("cp-")

    def test_cleanup_old_checkpoints(self, manager, sample_domain_state):
        """Test automatic cleanup of old checkpoints."""
        manager.max_checkpoints = 3

        # Save 5 checkpoints
        for i in range(5):
            sample_domain_state.set_stage_output(f"stage{i}", {"data": i})
            manager.save_checkpoint(sample_domain_state)

        # Should only keep 3 most recent
        checkpoints = manager.list_checkpoints("wf-test-123")
        assert len(checkpoints) == 3

        # Verify they're the newest ones
        assert checkpoints[0]["stage"] == "stage4"
        assert checkpoints[1]["stage"] == "stage3"
        assert checkpoints[2]["stage"] == "stage2"

    def test_no_cleanup_with_zero_limit(self, backend, sample_domain_state):
        """Test that cleanup doesn't happen with max_checkpoints=0."""
        manager = CheckpointManager(
            backend=backend,
            max_checkpoints=0  # No limit
        )

        # Save multiple checkpoints
        for i in range(5):
            sample_domain_state.set_stage_output(f"stage{i}", {"data": i})
            manager.save_checkpoint(sample_domain_state)

        # All should be kept
        checkpoints = manager.list_checkpoints("wf-test-123")
        assert len(checkpoints) == 5

    def test_checkpoint_callbacks_on_save(self, manager, sample_domain_state):
        """Test callback hook is called on successful save."""
        callback_called = []

        def on_saved(workflow_id, checkpoint_id):
            callback_called.append((workflow_id, checkpoint_id))

        manager.on_checkpoint_saved = on_saved

        checkpoint_id = manager.save_checkpoint(sample_domain_state)

        assert len(callback_called) == 1
        assert callback_called[0][0] == "wf-test-123"
        assert callback_called[0][1] == checkpoint_id

    def test_checkpoint_callbacks_on_load(self, manager, sample_domain_state):
        """Test callback hook is called on successful load."""
        callback_called = []

        def on_loaded(workflow_id, checkpoint_id):
            callback_called.append((workflow_id, checkpoint_id))

        manager.on_checkpoint_loaded = on_loaded

        checkpoint_id = manager.save_checkpoint(sample_domain_state)
        manager.load_checkpoint("wf-test-123", checkpoint_id)

        assert len(callback_called) == 1
        assert callback_called[0][0] == "wf-test-123"
        assert callback_called[0][1] == checkpoint_id


class TestCheckpointManagerFactory:
    """Test checkpoint manager factory function."""

    @pytest.fixture
    def temp_dir(self):
        """Create temporary directory for checkpoints."""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir)

    def test_create_file_backend_manager(self, temp_dir):
        """Test creating manager with file backend."""
        manager = create_checkpoint_manager(
            backend_type="file",
            checkpoint_dir=temp_dir
        )

        assert isinstance(manager, CheckpointManager)
        assert isinstance(manager.backend, FileCheckpointBackend)

    def test_create_unknown_backend_raises_error(self):
        """Test creating manager with unknown backend raises error."""
        with pytest.raises(ValueError, match="Unknown backend type"):
            create_checkpoint_manager(backend_type="unknown")
