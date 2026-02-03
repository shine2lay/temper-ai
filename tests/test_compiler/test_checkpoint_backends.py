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

        assert checkpoint_id.startswith("cp-"), \
            f"Checkpoint ID must start with 'cp-', got: {checkpoint_id}"
        assert len(checkpoint_id) >= 15, \
            f"Checkpoint ID too short (needs timestamp + counter + random): {checkpoint_id}"

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

    def test_checkpoint_id_entropy(self, backend):
        """Test that checkpoint IDs have sufficient entropy to prevent enumeration attacks.

        Security requirement: Checkpoint IDs must be unpredictable to prevent:
        - Enumeration attacks (guessing valid checkpoint IDs)
        - Collision attacks (creating conflicting checkpoints)
        - Timing attacks (predicting when checkpoints were created)
        """
        # Generate multiple checkpoint IDs
        checkpoint_ids = set()
        for i in range(100):
            checkpoint_id = backend._generate_checkpoint_id()
            checkpoint_ids.add(checkpoint_id)

        # Verify all IDs are unique (no collisions)
        assert len(checkpoint_ids) == 100, "Checkpoint IDs must be unique"

        # Verify format: cp-{timestamp}-{counter}-{random_hex}
        for checkpoint_id in checkpoint_ids:
            parts = checkpoint_id.split("-")
            assert len(parts) == 4, f"Expected 4 parts, got {len(parts)}: {checkpoint_id}"
            assert parts[0] == "cp", "Must start with 'cp'"
            assert parts[1].isdigit(), "Timestamp must be numeric"
            assert parts[2].isdigit(), "Counter must be numeric"
            assert len(parts[3]) == 12, "Random suffix must be 12 hex chars (48 bits entropy)"
            # Verify it's valid hex
            int(parts[3], 16)

        # Verify random suffixes are different (high entropy)
        random_suffixes = [checkpoint_id.split("-")[3] for checkpoint_id in checkpoint_ids]
        unique_suffixes = set(random_suffixes)
        assert len(unique_suffixes) == 100, "Random suffixes must be unique (high entropy)"

    def test_checkpoint_id_not_predictable(self, backend):
        """Test that consecutive checkpoint IDs are not predictable.

        Even with the same timestamp, the random component should make IDs unpredictable.
        """
        id1 = backend._generate_checkpoint_id()
        id2 = backend._generate_checkpoint_id()

        # Extract random suffixes
        suffix1 = id1.split("-")[3]
        suffix2 = id2.split("-")[3]

        # Random suffixes should be completely different (not sequential)
        assert suffix1 != suffix2, "Random suffixes must be different"

        # They should not differ by just 1 (not a simple counter)
        # Convert hex to int to check
        val1 = int(suffix1, 16)
        val2 = int(suffix2, 16)
        assert abs(val1 - val2) > 1, "Random values must not be sequential"

    # --- Path Traversal Security Tests ---

    def test_workflow_id_traversal_blocked(self, temp_dir, backend, sample_domain_state):
        """Path traversal via workflow_id must be sanitized and contained."""
        cp_id = backend.save_checkpoint("../../tmp/evil", sample_domain_state)
        # Verify all created files stay inside checkpoint_dir
        resolved_base = Path(temp_dir).resolve()
        for f in Path(temp_dir).rglob("*.json"):
            assert str(f.resolve()).startswith(str(resolved_base))
        loaded = backend.load_checkpoint("../../tmp/evil", cp_id)
        assert loaded.workflow_id == sample_domain_state.workflow_id

    def test_checkpoint_id_traversal_blocked(self, temp_dir, backend, sample_domain_state):
        """Path traversal via checkpoint_id must be sanitized and contained."""
        cp_id = backend.save_checkpoint(
            "wf-test-123", sample_domain_state,
            checkpoint_id="../../etc/passwd"
        )
        # Verify all created files stay inside checkpoint_dir
        resolved_base = Path(temp_dir).resolve()
        for f in Path(temp_dir).rglob("*.json"):
            assert str(f.resolve()).startswith(str(resolved_base))
        loaded = backend.load_checkpoint("wf-test-123", cp_id)
        assert loaded.workflow_id == sample_domain_state.workflow_id

    def test_null_byte_in_workflow_id(self, backend, sample_domain_state):
        """Null bytes in workflow_id must be rejected."""
        with pytest.raises(ValueError, match="null bytes"):
            backend.save_checkpoint("wf\x00evil", sample_domain_state)

    def test_null_byte_in_checkpoint_id(self, backend, sample_domain_state):
        """Null bytes in checkpoint_id must be rejected."""
        with pytest.raises(ValueError, match="null bytes"):
            backend.save_checkpoint(
                "wf-test-123", sample_domain_state,
                checkpoint_id="cp\x00evil"
            )

    def test_empty_workflow_id(self, backend, sample_domain_state):
        """Empty workflow_id must be rejected."""
        with pytest.raises(ValueError, match="non-empty string"):
            backend.save_checkpoint("", sample_domain_state)

    def test_empty_checkpoint_id(self, backend, sample_domain_state):
        """Empty checkpoint_id must be rejected."""
        with pytest.raises(ValueError, match="non-empty string"):
            backend.save_checkpoint(
                "wf-test-123", sample_domain_state,
                checkpoint_id=""
            )

    def test_long_workflow_id(self, backend, sample_domain_state):
        """Workflow IDs exceeding 255 chars must be rejected."""
        with pytest.raises(ValueError, match="maximum length"):
            backend.save_checkpoint("a" * 256, sample_domain_state)

    def test_sanitization_replaces_special_chars(self, temp_dir, backend, sample_domain_state):
        """Special characters in IDs are replaced with underscores."""
        cp_id = backend.save_checkpoint("wf/test@123", sample_domain_state)
        # Verify sanitized directory name
        sanitized_dir = Path(temp_dir).resolve() / "wf_test_123"
        assert sanitized_dir.exists(), f"Expected sanitized dir {sanitized_dir}"
        loaded = backend.load_checkpoint("wf/test@123", cp_id)
        assert loaded.workflow_id == sample_domain_state.workflow_id

    def test_valid_workflow_ids_accepted(self, backend, sample_domain_state):
        """Valid workflow IDs with allowed characters pass through."""
        for wf_id in ["wf-123", "test_workflow", "ABC-def-456", "simple"]:
            cp_id = backend.save_checkpoint(wf_id, sample_domain_state)
            loaded = backend.load_checkpoint(wf_id, cp_id)
            assert loaded.workflow_id == sample_domain_state.workflow_id

    def test_resolved_path_stays_in_checkpoint_dir(self, temp_dir, sample_domain_state):
        """Resolved paths must stay within the checkpoint directory."""
        backend = FileCheckpointBackend(checkpoint_dir=temp_dir)
        cp_id = backend.save_checkpoint("../../escape", sample_domain_state)
        # The file must be inside temp_dir, not outside it
        workflow_dir = Path(temp_dir).resolve() / "______escape"
        assert workflow_dir.exists()
        checkpoint_files = list(workflow_dir.glob("*.json"))
        assert len(checkpoint_files) == 1

    def test_sanitize_id_static_method(self):
        """_sanitize_id works correctly as a standalone method."""
        assert FileCheckpointBackend._sanitize_id("hello-world_123", "test") == "hello-world_123"
        assert FileCheckpointBackend._sanitize_id("../evil", "test") == "___evil"
        assert FileCheckpointBackend._sanitize_id("a/b/c", "test") == "a_b_c"


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
