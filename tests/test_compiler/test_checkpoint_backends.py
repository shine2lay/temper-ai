"""Tests for checkpoint storage backends.

Tests both FileCheckpointBackend and RedisCheckpointBackend to ensure:
- Correct checkpoint save/load
- Proper serialization/deserialization
- Checkpoint listing and deletion
- Error handling
"""
import pytest
import tempfile
import shutil
from pathlib import Path

from src.compiler.domain_state import WorkflowDomainState
from src.compiler.checkpoint_backends import (
    FileCheckpointBackend,
    CheckpointNotFoundError
)


class TestFileCheckpointBackend:
    """Test file-based checkpoint storage."""

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
    def sample_domain_state(self):
        """Create sample domain state for testing."""
        domain = WorkflowDomainState(
            workflow_id="wf-test-123",
            input="Analyze market trends"
        )
        domain.set_stage_output("research", {"findings": ["trend1", "trend2"]})
        return domain

    def test_backend_initialization(self, temp_dir):
        """Test backend creates checkpoint directory."""
        backend = FileCheckpointBackend(checkpoint_dir=temp_dir)
        assert Path(temp_dir).exists()
        assert Path(temp_dir).is_dir()

    def test_save_checkpoint(self, backend, sample_domain_state):
        """Test saving a checkpoint."""
        checkpoint_id = backend.save_checkpoint(
            "wf-test-123",
            sample_domain_state
        )

        assert checkpoint_id is not None
        assert checkpoint_id.startswith("cp-")

    def test_load_checkpoint(self, backend, sample_domain_state):
        """Test loading a saved checkpoint."""
        # Save checkpoint
        checkpoint_id = backend.save_checkpoint(
            "wf-test-123",
            sample_domain_state
        )

        # Load checkpoint
        loaded_domain = backend.load_checkpoint("wf-test-123", checkpoint_id)

        # Verify restoration
        assert loaded_domain.workflow_id == "wf-test-123"
        assert loaded_domain.input == "Analyze market trends"
        assert loaded_domain.stage_outputs == {"research": {"findings": ["trend1", "trend2"]}}
        assert loaded_domain.current_stage == "research"

    def test_load_latest_checkpoint(self, backend, sample_domain_state):
        """Test loading latest checkpoint without specifying ID."""
        # Save multiple checkpoints
        checkpoint_id_1 = backend.save_checkpoint("wf-test-123", sample_domain_state)

        # Modify state and save again
        sample_domain_state.set_stage_output("analysis", {"insights": ["insight1"]})
        checkpoint_id_2 = backend.save_checkpoint("wf-test-123", sample_domain_state)

        # Load latest (should be checkpoint_id_2)
        loaded_domain = backend.load_checkpoint("wf-test-123")

        assert loaded_domain.current_stage == "analysis"
        assert "analysis" in loaded_domain.stage_outputs

    def test_load_nonexistent_checkpoint(self, backend):
        """Test loading a checkpoint that doesn't exist raises error."""
        with pytest.raises(CheckpointNotFoundError):
            backend.load_checkpoint("wf-nonexistent", "cp-999")

    def test_load_no_checkpoints(self, backend):
        """Test loading from workflow with no checkpoints raises error."""
        with pytest.raises(CheckpointNotFoundError):
            backend.load_checkpoint("wf-no-checkpoints")

    def test_list_checkpoints(self, backend, sample_domain_state):
        """Test listing checkpoints for a workflow."""
        # Save multiple checkpoints
        checkpoint_id_1 = backend.save_checkpoint("wf-test-123", sample_domain_state)

        sample_domain_state.set_stage_output("analysis", {"data": "value"})
        checkpoint_id_2 = backend.save_checkpoint("wf-test-123", sample_domain_state)

        # List checkpoints
        checkpoints = backend.list_checkpoints("wf-test-123")

        assert len(checkpoints) == 2
        # Should be sorted by created_at desc (newest first)
        assert checkpoints[0]["checkpoint_id"] == checkpoint_id_2
        assert checkpoints[1]["checkpoint_id"] == checkpoint_id_1
        assert checkpoints[0]["stage"] == "analysis"
        assert checkpoints[1]["stage"] == "research"

    def test_list_no_checkpoints(self, backend):
        """Test listing checkpoints for workflow with none."""
        checkpoints = backend.list_checkpoints("wf-no-checkpoints")
        assert checkpoints == []

    def test_delete_checkpoint(self, backend, sample_domain_state):
        """Test deleting a checkpoint."""
        # Save checkpoint
        checkpoint_id = backend.save_checkpoint("wf-test-123", sample_domain_state)

        # Delete it
        success = backend.delete_checkpoint("wf-test-123", checkpoint_id)
        assert success is True

        # Verify it's gone
        with pytest.raises(CheckpointNotFoundError):
            backend.load_checkpoint("wf-test-123", checkpoint_id)

    def test_delete_nonexistent_checkpoint(self, backend):
        """Test deleting a checkpoint that doesn't exist."""
        success = backend.delete_checkpoint("wf-test-123", "cp-nonexistent")
        assert success is False

    def test_get_latest_checkpoint(self, backend, sample_domain_state):
        """Test getting latest checkpoint ID."""
        # No checkpoints initially
        latest = backend.get_latest_checkpoint("wf-test-123")
        assert latest is None

        # Save checkpoint
        checkpoint_id = backend.save_checkpoint("wf-test-123", sample_domain_state)

        # Get latest
        latest = backend.get_latest_checkpoint("wf-test-123")
        assert latest == checkpoint_id

    def test_save_with_metadata(self, backend, sample_domain_state):
        """Test saving checkpoint with custom metadata."""
        metadata = {"user": "test-user", "reason": "manual"}

        checkpoint_id = backend.save_checkpoint(
            "wf-test-123",
            sample_domain_state,
            metadata=metadata
        )

        # Verify metadata is stored
        checkpoints = backend.list_checkpoints("wf-test-123")
        assert len(checkpoints) == 1
        assert checkpoints[0]["metadata"] == metadata

    def test_save_with_custom_checkpoint_id(self, backend, sample_domain_state):
        """Test saving checkpoint with custom ID."""
        custom_id = "cp-custom-123"

        checkpoint_id = backend.save_checkpoint(
            "wf-test-123",
            sample_domain_state,
            checkpoint_id=custom_id
        )

        assert checkpoint_id == custom_id

        # Verify it can be loaded
        loaded_domain = backend.load_checkpoint("wf-test-123", custom_id)
        assert loaded_domain.workflow_id == "wf-test-123"

    def test_checkpoint_file_structure(self, temp_dir, backend, sample_domain_state):
        """Test that checkpoint files are created in correct structure."""
        checkpoint_id = backend.save_checkpoint("wf-test-123", sample_domain_state)

        # Check directory structure
        workflow_dir = Path(temp_dir) / "wf-test-123"
        assert workflow_dir.exists()

        # Check checkpoint file
        checkpoint_file = workflow_dir / f"{checkpoint_id}.json"
        assert checkpoint_file.exists()

    def test_checkpoint_serialization_completeness(self, backend, sample_domain_state):
        """Test that all domain state fields are properly serialized."""
        # Add comprehensive data to domain state
        sample_domain_state.topic = "Market Analysis"
        sample_domain_state.depth = "comprehensive"
        sample_domain_state.focus_areas = ["tech", "finance"]
        sample_domain_state.query = "What are the trends?"
        sample_domain_state.metadata = {"custom": "value"}

        # Save and load
        checkpoint_id = backend.save_checkpoint("wf-test-123", sample_domain_state)
        loaded_domain = backend.load_checkpoint("wf-test-123", checkpoint_id)

        # Verify all fields restored
        assert loaded_domain.topic == "Market Analysis"
        assert loaded_domain.depth == "comprehensive"
        assert loaded_domain.focus_areas == ["tech", "finance"]
        assert loaded_domain.query == "What are the trends?"
        assert loaded_domain.metadata == {"custom": "value"}

    def test_multiple_workflows(self, backend):
        """Test checkpointing multiple workflows independently."""
        # Create two different workflows
        domain1 = WorkflowDomainState(workflow_id="wf-1", input="input1")
        domain1.set_stage_output("stage1", {"data": "workflow1"})

        domain2 = WorkflowDomainState(workflow_id="wf-2", input="input2")
        domain2.set_stage_output("stage1", {"data": "workflow2"})

        # Save checkpoints for both
        cp1 = backend.save_checkpoint("wf-1", domain1)
        cp2 = backend.save_checkpoint("wf-2", domain2)

        # Load and verify they're independent
        loaded1 = backend.load_checkpoint("wf-1", cp1)
        loaded2 = backend.load_checkpoint("wf-2", cp2)

        assert loaded1.workflow_id == "wf-1"
        assert loaded2.workflow_id == "wf-2"
        assert loaded1.input == "input1"
        assert loaded2.input == "input2"


# Redis backend tests require a running Redis instance
# These are skipped by default and can be run with: pytest -m redis
@pytest.mark.redis
@pytest.mark.skipif(
    True,  # Skip by default
    reason="Redis tests require running Redis server"
)
class TestRedisCheckpointBackend:
    """Test Redis-based checkpoint storage.

    NOTE: These tests require a running Redis server.
    Run with: pytest -m redis
    """

    @pytest.fixture
    def backend(self):
        """Create Redis backend."""
        try:
            from src.compiler.checkpoint_backends import RedisCheckpointBackend
            backend = RedisCheckpointBackend(redis_url="redis://localhost:6379")
            # Clean up any existing test data
            backend.redis_client.flushdb()
            return backend
        except ImportError:
            pytest.skip("Redis package not installed")

    @pytest.fixture
    def sample_domain_state(self):
        """Create sample domain state for testing."""
        domain = WorkflowDomainState(
            workflow_id="wf-redis-test",
            input="Test input"
        )
        domain.set_stage_output("stage1", {"data": "value"})
        return domain

    def test_redis_save_and_load(self, backend, sample_domain_state):
        """Test Redis save and load."""
        checkpoint_id = backend.save_checkpoint("wf-redis-test", sample_domain_state)
        loaded_domain = backend.load_checkpoint("wf-redis-test", checkpoint_id)

        assert loaded_domain.workflow_id == "wf-redis-test"
        assert loaded_domain.stage_outputs == {"stage1": {"data": "value"}}

    def test_redis_list_checkpoints(self, backend, sample_domain_state):
        """Test Redis checkpoint listing."""
        backend.save_checkpoint("wf-redis-test", sample_domain_state)

        sample_domain_state.set_stage_output("stage2", {"data": "value2"})
        backend.save_checkpoint("wf-redis-test", sample_domain_state)

        checkpoints = backend.list_checkpoints("wf-redis-test")
        assert len(checkpoints) == 2
