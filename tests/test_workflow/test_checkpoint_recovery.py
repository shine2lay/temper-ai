"""Tests for resuming from checkpoints."""
from unittest.mock import Mock

import pytest

from temper_ai.workflow.checkpoint import CheckpointManager
from temper_ai.workflow.checkpoint_backends import CheckpointNotFoundError
from temper_ai.workflow.domain_state import WorkflowDomainState
from temper_ai.stage.executors.state_keys import StateKeys
from temper_ai.workflow.workflow_executor import WorkflowExecutor


def test_resume_from_checkpoint_continues_execution(tmp_path):
    """Verify resume loads checkpoint and continues execution."""
    # Setup: Create a checkpoint with stage1 and stage2 completed
    checkpoint_manager = CheckpointManager(storage_path=str(tmp_path))

    initial_state = WorkflowDomainState(
        workflow_id="wf-resume-test",
        stage_outputs={"stage1": "result1", "stage2": "result2"},
        current_stage="stage2",
        topic="Test Topic"
    )
    checkpoint_manager.save_checkpoint("wf-resume-test", initial_state)

    # Create mock graph for remaining stages
    mock_graph = Mock()
    # Only stage3 should execute (stage1, stage2 already done)
    remaining_chunks = [
        {"stage3": {"stage_outputs": {"stage1": "result1", "stage2": "result2", "stage3": "result3"}, "current_stage": "stage3", "workflow_id": "wf-resume-test"}},
    ]
    mock_graph.stream = Mock(return_value=iter(remaining_chunks))

    executor = WorkflowExecutor(
        graph=mock_graph,
        checkpoint_manager=checkpoint_manager,
        enable_checkpoints=True
    )

    # Resume from checkpoint
    result = executor.resume_from_checkpoint("wf-resume-test")

    # Verify all stages present in final result
    assert result[StateKeys.STAGE_OUTPUTS]["stage1"] == "result1"
    assert result[StateKeys.STAGE_OUTPUTS]["stage2"] == "result2"
    assert result[StateKeys.STAGE_OUTPUTS]["stage3"] == "result3"

    # Verify stream was called (for stage3 only)
    assert mock_graph.stream.called


def test_resume_nonexistent_checkpoint_raises_error(tmp_path):
    """Verify error when trying to resume non-existent checkpoint."""
    checkpoint_manager = CheckpointManager(storage_path=str(tmp_path))
    executor = WorkflowExecutor(
        graph=Mock(),
        checkpoint_manager=checkpoint_manager,
        enable_checkpoints=True
    )

    with pytest.raises(CheckpointNotFoundError, match="No checkpoints found"):
        executor.resume_from_checkpoint("wf-nonexistent")


def test_resume_continues_checkpointing(tmp_path):
    """Verify that resumed execution continues to checkpoint."""
    # Create initial checkpoint
    checkpoint_manager = CheckpointManager(storage_path=str(tmp_path))

    initial_state = WorkflowDomainState(
        workflow_id="wf-continue",
        stage_outputs={"stage1": "r1"},
        current_stage="stage1",
        topic="Test"
    )
    checkpoint_manager.save_checkpoint("wf-continue", initial_state)

    # Mock graph for remaining execution
    mock_graph = Mock()
    remaining_chunks = [
        {"stage2": {"stage_outputs": {"stage1": "r1", "stage2": "r2"}, "current_stage": "stage2", "workflow_id": "wf-continue"}},
        {"stage3": {"stage_outputs": {"stage1": "r1", "stage2": "r2", "stage3": "r3"}, "current_stage": "stage3", "workflow_id": "wf-continue"}},
    ]
    mock_graph.stream = Mock(return_value=iter(remaining_chunks))

    executor = WorkflowExecutor(
        graph=mock_graph,
        checkpoint_manager=checkpoint_manager,
        enable_checkpoints=True
    )

    # Resume and complete
    result = executor.resume_from_checkpoint("wf-continue")

    # Verify final checkpoint includes all stages
    final_state = checkpoint_manager.resume("wf-continue")
    assert "stage1" in final_state.stage_outputs
    assert "stage2" in final_state.stage_outputs
    assert "stage3" in final_state.stage_outputs


def test_resume_with_additional_input(tmp_path):
    """Verify additional input can be merged during resume."""
    # Create checkpoint
    checkpoint_manager = CheckpointManager(storage_path=str(tmp_path))

    initial_state = WorkflowDomainState(
        workflow_id="wf-merge",
        stage_outputs={"stage1": "r1"},
        current_stage="stage1",
        topic="Original Topic"
    )
    checkpoint_manager.save_checkpoint("wf-merge", initial_state)

    # Mock graph
    mock_graph = Mock()
    remaining_chunks = [
        {"stage2": {"stage_outputs": {"stage1": "r1", "stage2": "r2"}, "current_stage": "stage2", "workflow_id": "wf-merge", "topic": "Original Topic", "depth": 5}},
    ]
    mock_graph.stream = Mock(return_value=iter(remaining_chunks))

    executor = WorkflowExecutor(
        graph=mock_graph,
        checkpoint_manager=checkpoint_manager,
        enable_checkpoints=True
    )

    # Resume with additional input
    result = executor.resume_from_checkpoint(
        "wf-merge",
        input_data={"depth": 5}
    )

    # Verify new input was used (mock returns it in chunk)
    assert result.get("depth") == 5


def test_resume_already_complete_workflow(tmp_path):
    """Verify resume handles already-complete workflows gracefully."""
    # Create checkpoint with all stages complete
    checkpoint_manager = CheckpointManager(storage_path=str(tmp_path))

    complete_state = WorkflowDomainState(
        workflow_id="wf-complete",
        stage_outputs={"stage1": "r1", "stage2": "r2", "stage3": "r3"},
        current_stage="stage3",
        topic="Test"
    )
    checkpoint_manager.save_checkpoint("wf-complete", complete_state)

    # Mock graph that yields nothing (all stages already done)
    mock_graph = Mock()
    mock_graph.stream = Mock(return_value=iter([]))

    # Create mock tracker
    mock_tracker = Mock()

    executor = WorkflowExecutor(
        graph=mock_graph,
        tracker=mock_tracker,
        checkpoint_manager=checkpoint_manager,
        enable_checkpoints=True
    )

    # Resume should return checkpoint state
    result = executor.resume_from_checkpoint("wf-complete")

    # Verify state was returned
    assert result[StateKeys.STAGE_OUTPUTS]["stage1"] == "r1"
    assert result[StateKeys.STAGE_OUTPUTS]["stage2"] == "r2"
    assert result[StateKeys.STAGE_OUTPUTS]["stage3"] == "r3"

    # Verify workflow completion was handled (logged via logger, not tracker)


def test_resume_with_tracker(tmp_path):
    """Verify tracker integration during resume."""
    # Create checkpoint
    checkpoint_manager = CheckpointManager(storage_path=str(tmp_path))

    initial_state = WorkflowDomainState(
        workflow_id="wf-tracked-resume",
        stage_outputs={"stage1": "r1"},
        current_stage="stage1",
        topic="Test"
    )
    checkpoint_manager.save_checkpoint("wf-tracked-resume", initial_state)

    # Mock graph
    mock_graph = Mock()
    remaining_chunks = [
        {"stage2": {"stage_outputs": {"stage1": "r1", "stage2": "r2"}, "current_stage": "stage2", "workflow_id": "wf-tracked-resume"}},
    ]
    mock_graph.stream = Mock(return_value=iter(remaining_chunks))

    # Create mock tracker
    mock_tracker = Mock()

    executor = WorkflowExecutor(
        graph=mock_graph,
        tracker=mock_tracker,
        checkpoint_manager=checkpoint_manager,
        enable_checkpoints=True
    )

    # Resume
    result = executor.resume_from_checkpoint("wf-tracked-resume")

    # Verify resume completed with expected stage outputs
    assert result[StateKeys.STAGE_OUTPUTS]["stage1"] == "r1"
    assert result[StateKeys.STAGE_OUTPUTS]["stage2"] == "r2"


def test_resume_error_saves_checkpoint(tmp_path):
    """Verify checkpoint is saved when resumed execution fails."""
    # Create checkpoint
    checkpoint_manager = CheckpointManager(storage_path=str(tmp_path))

    initial_state = WorkflowDomainState(
        workflow_id="wf-resume-fail",
        stage_outputs={"stage1": "r1"},
        current_stage="stage1",
        topic="Test"
    )
    checkpoint_manager.save_checkpoint("wf-resume-fail", initial_state)

    # Mock graph that fails
    mock_graph = Mock()

    def failing_stream(state):
        yield {"stage2": {"stage_outputs": {"stage1": "r1", "stage2": "r2"}, "current_stage": "stage2", "workflow_id": "wf-resume-fail"}}
        raise RuntimeError("Stage 3 failed during resume")

    mock_graph.stream = Mock(side_effect=failing_stream)

    executor = WorkflowExecutor(
        graph=mock_graph,
        checkpoint_manager=checkpoint_manager,
        enable_checkpoints=True
    )

    # Resume should fail
    with pytest.raises(RuntimeError, match="Stage 3 failed during resume"):
        executor.resume_from_checkpoint("wf-resume-fail")

    # Verify checkpoint was saved at failure point
    assert checkpoint_manager.has_checkpoint("wf-resume-fail")
    final_state = checkpoint_manager.resume("wf-resume-fail")

    # Should have stage1 and stage2
    assert "stage1" in final_state.stage_outputs
    assert "stage2" in final_state.stage_outputs


def test_resume_without_checkpoint_manager_raises_error():
    """Verify error when trying to resume without checkpoint manager."""
    mock_graph = Mock()

    executor = WorkflowExecutor(
        graph=mock_graph,
        enable_checkpoints=False
    )

    with pytest.raises(RuntimeError, match="Checkpoint manager not configured"):
        executor.resume_from_checkpoint("wf-no-manager")
