"""Tests for checkpoint/resume functionality."""

import json
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from temper_ai.stage.executors.state_keys import StateKeys
from temper_ai.workflow.checkpoint import (
    CheckpointManager,
    CheckpointMetadata,
    FileCheckpointStorage,
)
from temper_ai.workflow.domain_state import WorkflowDomainState


class TestCheckpointMetadata:
    """Test CheckpointMetadata class."""

    def test_initialization(self):
        """Test metadata initialization."""
        metadata = CheckpointMetadata(
            workflow_id="wf-123",
            created_at=datetime.now(UTC),
            current_stage="analysis",
            completed_stages=["research", "data_collection"],
        )

        assert metadata.workflow_id == "wf-123"
        assert metadata.current_stage == "analysis"
        assert len(metadata.completed_stages) == 2
        assert metadata.version == "1.0"

    def test_to_dict(self):
        """Test metadata serialization."""
        created_at = datetime.now(UTC)
        metadata = CheckpointMetadata(
            workflow_id="wf-456",
            created_at=created_at,
            current_stage="synthesis",
            completed_stages=["research"],
            file_path="/path/to/checkpoint.json",
            size_bytes=1024,
        )

        data = metadata.to_dict()

        assert data[StateKeys.WORKFLOW_ID] == "wf-456"
        assert data[StateKeys.CURRENT_STAGE] == "synthesis"
        assert data["completed_stages"] == ["research"]
        assert data["file_path"] == "/path/to/checkpoint.json"
        assert data["size_bytes"] == 1024
        assert isinstance(data["created_at"], str)

    def test_from_dict(self):
        """Test metadata deserialization."""
        data = {
            "workflow_id": "wf-789",
            "created_at": "2026-01-27T10:30:00",
            "current_stage": "review",
            "completed_stages": ["draft", "revision"],
            "version": "1.0",
        }

        metadata = CheckpointMetadata.from_dict(data)

        assert metadata.workflow_id == "wf-789"
        assert metadata.current_stage == "review"
        assert len(metadata.completed_stages) == 2
        assert isinstance(metadata.created_at, datetime)


class TestFileCheckpointStorage:
    """Test file-based checkpoint storage."""

    @pytest.fixture
    def storage_dir(self):
        """Create temporary storage directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    def storage(self, storage_dir):
        """Create file storage instance."""
        return FileCheckpointStorage(storage_dir)

    @pytest.fixture
    def sample_domain_state(self):
        """Create sample domain state."""
        state = WorkflowDomainState(
            workflow_id="wf-test-123",
            input="Analyze market trends",
            topic="Market Analysis",
        )
        state.set_stage_output("research", {"findings": ["trend1", "trend2"]})
        state.set_stage_output("analysis", {"insights": ["insight1"]})
        return state

    def test_save_checkpoint(self, storage, sample_domain_state):
        """Test saving checkpoint."""
        metadata = storage.save("wf-test-123", sample_domain_state)

        assert metadata.workflow_id == "wf-test-123"
        assert metadata.current_stage == "analysis"  # Last stage executed
        assert "research" in metadata.completed_stages
        assert "analysis" in metadata.completed_stages
        assert metadata.file_path is not None
        assert metadata.size_bytes > 0

    def test_load_checkpoint(self, storage, sample_domain_state):
        """Test loading checkpoint."""
        # Save first
        storage.save("wf-test-123", sample_domain_state)

        # Load
        loaded_state = storage.load("wf-test-123")

        assert loaded_state is not None
        assert loaded_state.workflow_id == "wf-test-123"
        assert loaded_state.input == "Analyze market trends"
        assert loaded_state.topic == "Market Analysis"
        assert loaded_state.has_stage_output("research")
        assert loaded_state.has_stage_output("analysis")
        assert loaded_state.get_stage_output("research") == {
            "findings": ["trend1", "trend2"]
        }

    def test_load_nonexistent_checkpoint(self, storage):
        """Test loading checkpoint that doesn't exist."""
        loaded_state = storage.load("wf-nonexistent")

        assert loaded_state is None

    def test_exists(self, storage, sample_domain_state):
        """Test checking checkpoint existence."""
        # Should not exist initially
        assert not storage.exists("wf-test-123")

        # Save checkpoint
        storage.save("wf-test-123", sample_domain_state)

        # Should exist now
        assert storage.exists("wf-test-123")

    def test_delete_checkpoint(self, storage, sample_domain_state):
        """Test deleting checkpoint."""
        # Save checkpoint
        storage.save("wf-test-123", sample_domain_state)
        assert storage.exists("wf-test-123")

        # Delete
        deleted = storage.delete("wf-test-123")

        assert deleted is True
        assert not storage.exists("wf-test-123")

    def test_delete_nonexistent_checkpoint(self, storage):
        """Test deleting checkpoint that doesn't exist."""
        deleted = storage.delete("wf-nonexistent")

        assert deleted is False

    def test_list_checkpoints(self, storage):
        """Test listing all checkpoints."""
        # Create multiple checkpoints
        state1 = WorkflowDomainState(workflow_id="wf-001", input="test1")
        state1.set_stage_output("stage1", {"data": 1})

        state2 = WorkflowDomainState(workflow_id="wf-002", input="test2")
        state2.set_stage_output("stage1", {"data": 2})
        state2.set_stage_output("stage2", {"data": 3})

        storage.save("wf-001", state1)
        storage.save("wf-002", state2)

        # List checkpoints
        checkpoints = storage.list_checkpoints()

        assert len(checkpoints) == 2
        workflow_ids = {cp.workflow_id for cp in checkpoints}
        assert "wf-001" in workflow_ids
        assert "wf-002" in workflow_ids

    def test_checkpoint_file_format(self, storage, sample_domain_state, storage_dir):
        """Test that checkpoint files are valid JSON."""
        storage.save("wf-test-123", sample_domain_state)

        # Read checkpoint file directly (new backend uses workflow subdirectory)
        workflow_dir = Path(storage_dir) / "wf-test-123"
        assert workflow_dir.exists()
        checkpoint_files = list(workflow_dir.glob("*.json"))
        assert len(checkpoint_files) >= 1
        checkpoint_path = checkpoint_files[0]

        with open(checkpoint_path) as f:
            checkpoint_data = json.load(f)

        # Verify it's valid JSON with expected fields
        # New backend wraps domain state with checkpoint metadata and HMAC
        assert "hmac" in checkpoint_data
        assert "data" in checkpoint_data
        data = checkpoint_data["data"]
        assert "workflow_id" in data
        assert data[StateKeys.WORKFLOW_ID] == "wf-test-123"
        assert "domain_state" in data
        assert "stage_outputs" in data["domain_state"]
        assert "current_stage" in data["domain_state"]

    def test_sanitize_workflow_id_in_filename(self, storage):
        """Test that workflow IDs with slashes are sanitized."""
        state = WorkflowDomainState(workflow_id="wf-test/123", input="test")

        metadata = storage.save("wf-test/123", state)

        # File path should have sanitized ID
        assert "/" not in Path(metadata.file_path).name
        assert "\\" not in Path(metadata.file_path).name
        assert storage.exists("wf-test/123")


class TestCheckpointManager:
    """Test CheckpointManager high-level operations."""

    @pytest.fixture
    def storage_dir(self):
        """Create temporary storage directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    def manager(self, storage_dir):
        """Create checkpoint manager."""
        return CheckpointManager(storage_path=storage_dir)

    @pytest.fixture
    def sample_domain_state(self):
        """Create sample domain state."""
        state = WorkflowDomainState(
            workflow_id="wf-manager-test",
            input="Test workflow",
        )
        state.set_stage_output("stage1", {"result": "output1"})
        state.set_stage_output("stage2", {"result": "output2"})
        return state

    def test_save_and_resume(self, manager, sample_domain_state):
        """Test saving and resuming workflow."""
        # Save checkpoint
        metadata = manager.save_checkpoint("wf-manager-test", sample_domain_state)

        assert metadata.workflow_id == "wf-manager-test"

        # Resume
        resumed_state = manager.resume("wf-manager-test")

        assert resumed_state.workflow_id == "wf-manager-test"
        assert resumed_state.input == "Test workflow"
        assert resumed_state.has_stage_output("stage1")
        assert resumed_state.has_stage_output("stage2")

    def test_resume_nonexistent_raises_error(self, manager):
        """Test resuming nonexistent workflow raises error."""
        with pytest.raises(FileNotFoundError, match="No checkpoint found"):
            manager.resume("wf-nonexistent")

    def test_has_checkpoint(self, manager, sample_domain_state):
        """Test checking checkpoint existence."""
        assert not manager.has_checkpoint("wf-manager-test")

        manager.save_checkpoint("wf-manager-test", sample_domain_state)

        assert manager.has_checkpoint("wf-manager-test")

    def test_delete_all_checkpoints(self, manager, sample_domain_state):
        """Test deleting all checkpoints for a workflow."""
        manager.save_checkpoint("wf-manager-test", sample_domain_state)
        assert manager.has_checkpoint("wf-manager-test")

        deleted = manager.delete_all_checkpoints("wf-manager-test")

        assert deleted is True
        assert not manager.has_checkpoint("wf-manager-test")

    def test_list_all(self, manager):
        """Test listing all checkpoints."""
        # Create multiple checkpoints
        state1 = WorkflowDomainState(workflow_id="wf-001")
        state2 = WorkflowDomainState(workflow_id="wf-002")

        manager.save_checkpoint("wf-001", state1)
        manager.save_checkpoint("wf-002", state2)

        checkpoints = manager.list_all()

        assert len(checkpoints) == 2
        workflow_ids = {cp.workflow_id for cp in checkpoints}
        assert "wf-001" in workflow_ids
        assert "wf-002" in workflow_ids

    def test_get_completed_stages(self, manager, sample_domain_state):
        """Test getting completed stages from checkpoint."""
        manager.save_checkpoint("wf-manager-test", sample_domain_state)

        completed_stages = manager.get_completed_stages("wf-manager-test")

        assert "stage1" in completed_stages
        assert "stage2" in completed_stages
        assert len(completed_stages) == 2

    def test_should_skip_stage(self, manager, sample_domain_state):
        """Test checking if stage should be skipped."""
        # Before checkpoint: should not skip
        assert not manager.should_skip_stage("wf-manager-test", "stage1")

        # Save checkpoint with completed stages
        manager.save_checkpoint("wf-manager-test", sample_domain_state)

        # Should skip completed stages
        assert manager.should_skip_stage("wf-manager-test", "stage1")
        assert manager.should_skip_stage("wf-manager-test", "stage2")

        # Should not skip uncompleted stages
        assert not manager.should_skip_stage("wf-manager-test", "stage3")


class TestCheckpointResume:
    """Test realistic checkpoint/resume scenarios."""

    @pytest.fixture
    def storage_dir(self):
        """Create temporary storage directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    def manager(self, storage_dir):
        """Create checkpoint manager."""
        return CheckpointManager(storage_path=storage_dir)

    def test_partial_workflow_completion(self, manager):
        """Test resuming partially completed workflow."""
        # Simulate workflow that completed 2 of 4 stages
        state = WorkflowDomainState(
            workflow_id="wf-partial",
            input="Analyze data",
            topic="Data Analysis",
        )
        state.set_stage_output("data_collection", {"rows": 1000})
        state.set_stage_output("preprocessing", {"cleaned_rows": 950})

        # Save checkpoint
        manager.save_checkpoint("wf-partial", state)

        # Resume workflow
        resumed = manager.resume("wf-partial")

        # Verify resumed state
        assert resumed.workflow_id == "wf-partial"
        assert resumed.has_stage_output("data_collection")
        assert resumed.has_stage_output("preprocessing")

        # Check which stages to skip
        assert manager.should_skip_stage("wf-partial", "data_collection")
        assert manager.should_skip_stage("wf-partial", "preprocessing")
        assert not manager.should_skip_stage("wf-partial", "analysis")
        assert not manager.should_skip_stage("wf-partial", "reporting")

    def test_workflow_interruption_and_resume(self, manager):
        """Test workflow interrupted mid-execution and resumed."""
        # Initial execution
        state = WorkflowDomainState(workflow_id="wf-interrupted", input="test")
        state.set_stage_output("stage1", {"data": 1})

        manager.save_checkpoint("wf-interrupted", state)

        # Simulate interruption and resume
        resumed = manager.resume("wf-interrupted")

        # Continue from where we left off
        resumed.set_stage_output("stage2", {"data": 2})
        resumed.set_stage_output("stage3", {"data": 3})

        # Save final checkpoint
        manager.save_checkpoint("wf-interrupted", resumed)

        # Verify final state
        final = manager.resume("wf-interrupted")
        assert final.has_stage_output("stage1")
        assert final.has_stage_output("stage2")
        assert final.has_stage_output("stage3")

    def test_checkpoint_every_stage(self, manager):
        """Test saving checkpoint after each stage."""
        state = WorkflowDomainState(workflow_id="wf-incremental", input="test")

        # Stage 1
        state.set_stage_output("stage1", {"data": 1})
        manager.save_checkpoint("wf-incremental", state)

        # Stage 2
        state.set_stage_output("stage2", {"data": 2})
        manager.save_checkpoint("wf-incremental", state)

        # Stage 3
        state.set_stage_output("stage3", {"data": 3})
        manager.save_checkpoint("wf-incremental", state)

        # Verify final checkpoint has all stages
        final = manager.resume("wf-incremental")
        assert len(final.stage_outputs) == 3
        assert final.current_stage == "stage3"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
