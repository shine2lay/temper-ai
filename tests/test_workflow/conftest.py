"""Test fixtures for compiler tests."""
from unittest.mock import Mock

import pytest

from src.workflow.checkpoint import CheckpointManager
from src.workflow.domain_state import WorkflowDomainState


@pytest.fixture
def temp_checkpoint_dir(tmp_path):
    """Provide temporary directory for checkpoints."""
    checkpoint_dir = tmp_path / "checkpoints"
    checkpoint_dir.mkdir()
    return checkpoint_dir


@pytest.fixture
def checkpoint_manager(temp_checkpoint_dir):
    """Provide configured checkpoint manager."""
    return CheckpointManager(storage_path=str(temp_checkpoint_dir))


@pytest.fixture
def sample_domain_state():
    """Provide sample domain state for testing."""
    return WorkflowDomainState(
        workflow_id="wf-test-123",
        stage_outputs={"stage1": "result1"},
        current_stage="stage1",
        topic="Test Topic"
    )


@pytest.fixture
def mock_streaming_graph():
    """Provide mock graph with streaming behavior."""
    mock_graph = Mock()
    stage_chunks = [
        {"stage1": {"stage_outputs": {"stage1": "r1"}, "current_stage": "stage1", "workflow_id": "wf-test"}},
        {"stage2": {"stage_outputs": {"stage1": "r1", "stage2": "r2"}, "current_stage": "stage2", "workflow_id": "wf-test"}},
    ]
    mock_graph.stream = Mock(return_value=iter(stage_chunks))

    return mock_graph
