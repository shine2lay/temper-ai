"""Tests for streaming execution with checkpointing."""
import pytest
from unittest.mock import Mock, MagicMock
from src.compiler.workflow_executor import WorkflowExecutor
from src.compiler.checkpoint import CheckpointManager


def test_checkpoint_saved_after_each_stage(tmp_path):
    """Verify checkpoint is saved after each stage completes."""
    # Create mock graph that yields stages sequentially
    mock_graph = Mock()
    stage_chunks = [
        {"stage1": {"stage_outputs": {"stage1": "result1"}, "current_stage": "stage1", "workflow_id": "wf-test-123"}},
        {"stage2": {"stage_outputs": {"stage1": "result1", "stage2": "result2"}, "current_stage": "stage2", "workflow_id": "wf-test-123"}},
        {"stage3": {"stage_outputs": {"stage1": "result1", "stage2": "result2", "stage3": "result3"}, "current_stage": "stage3", "workflow_id": "wf-test-123"}},
    ]
    mock_graph.stream = Mock(return_value=iter(stage_chunks))

    checkpoint_manager = CheckpointManager(storage_path=str(tmp_path))
    executor = WorkflowExecutor(
        graph=mock_graph,
        checkpoint_manager=checkpoint_manager,
        enable_checkpoints=True
    )

    # Execute with checkpoints
    result = executor.execute_with_checkpoints(
        input_data={"topic": "test"},
        workflow_id="wf-test-123",
        checkpoint_interval=1  # Checkpoint after every stage
    )

    # Verify all stages completed
    assert result["stage_outputs"]["stage3"] == "result3"

    # Verify checkpoint exists
    assert checkpoint_manager.has_checkpoint("wf-test-123")

    # Verify checkpoint contains all stage outputs
    domain_state = checkpoint_manager.resume("wf-test-123")
    assert "stage1" in domain_state.stage_outputs
    assert "stage2" in domain_state.stage_outputs
    assert "stage3" in domain_state.stage_outputs


def test_checkpoint_interval_respected(tmp_path):
    """Verify checkpoints are saved at specified intervals."""
    # Track checkpoint saves
    save_calls = []

    # Create mock checkpoint manager
    checkpoint_manager = CheckpointManager(storage_path=str(tmp_path))
    original_save = checkpoint_manager.save_checkpoint

    def track_save(workflow_id, domain_state):
        save_calls.append(domain_state.current_stage)
        return original_save(workflow_id, domain_state)

    checkpoint_manager.save_checkpoint = track_save

    # Create mock graph
    mock_graph = Mock()
    stage_chunks = [
        {"stage1": {"stage_outputs": {"stage1": "r1"}, "current_stage": "stage1", "workflow_id": "wf-123"}},
        {"stage2": {"stage_outputs": {"stage1": "r1", "stage2": "r2"}, "current_stage": "stage2", "workflow_id": "wf-123"}},
        {"stage3": {"stage_outputs": {"stage1": "r1", "stage2": "r2", "stage3": "r3"}, "current_stage": "stage3", "workflow_id": "wf-123"}},
        {"stage4": {"stage_outputs": {"stage1": "r1", "stage2": "r2", "stage3": "r3", "stage4": "r4"}, "current_stage": "stage4", "workflow_id": "wf-123"}},
    ]
    mock_graph.stream = Mock(return_value=iter(stage_chunks))

    executor = WorkflowExecutor(
        graph=mock_graph,
        checkpoint_manager=checkpoint_manager,
        enable_checkpoints=True
    )

    # Execute with checkpoint every 2 stages
    result = executor.execute_with_checkpoints(
        input_data={"topic": "test"},
        workflow_id="wf-123",
        checkpoint_interval=2
    )

    # Should checkpoint at: stage2, stage4 (interval 2), plus final
    # Total: 3 checkpoints (stage2, stage4, final=stage4)
    assert len(save_calls) >= 2  # At least interval checkpoints
    assert "stage2" in save_calls  # Checkpointed at interval
    assert "stage4" in save_calls  # Checkpointed at interval and final


def test_checkpoint_on_failure(tmp_path):
    """Verify checkpoint is saved when execution fails."""
    # Create mock graph that fails on stage 3
    mock_graph = Mock()

    def failing_stream(state):
        yield {"stage1": {"stage_outputs": {"stage1": "r1"}, "current_stage": "stage1", "workflow_id": "wf-fail"}}
        yield {"stage2": {"stage_outputs": {"stage1": "r1", "stage2": "r2"}, "current_stage": "stage2", "workflow_id": "wf-fail"}}
        raise RuntimeError("Stage 3 failed")

    mock_graph.stream = Mock(side_effect=failing_stream)

    checkpoint_manager = CheckpointManager(storage_path=str(tmp_path))
    executor = WorkflowExecutor(
        graph=mock_graph,
        checkpoint_manager=checkpoint_manager,
        enable_checkpoints=True
    )

    # Execute should fail
    with pytest.raises(RuntimeError, match="Stage 3 failed"):
        executor.execute_with_checkpoints(
            input_data={"topic": "test"},
            workflow_id="wf-fail",
            checkpoint_interval=1
        )

    # Verify checkpoint was saved before failure
    assert checkpoint_manager.has_checkpoint("wf-fail")
    domain_state = checkpoint_manager.resume("wf-fail")

    # Should have stage1 and stage2 completed
    assert "stage1" in domain_state.stage_outputs
    assert "stage2" in domain_state.stage_outputs
    assert "stage3" not in domain_state.stage_outputs  # Failed before completion


def test_no_checkpoint_manager_raises_error(tmp_path):
    """Verify error when checkpoint manager not configured."""
    mock_graph = Mock()

    # Create executor without checkpoint manager
    executor = WorkflowExecutor(
        graph=mock_graph,
        enable_checkpoints=False
    )

    # Should raise error
    with pytest.raises(RuntimeError, match="Checkpoint manager not configured"):
        executor.execute_with_checkpoints(
            input_data={"topic": "test"},
            workflow_id="wf-no-checkpoint"
        )


def test_empty_workflow_raises_error(tmp_path):
    """Verify error when workflow produces no output."""
    # Create mock graph that yields nothing
    mock_graph = Mock()
    mock_graph.stream = Mock(return_value=iter([]))

    checkpoint_manager = CheckpointManager(storage_path=str(tmp_path))
    executor = WorkflowExecutor(
        graph=mock_graph,
        checkpoint_manager=checkpoint_manager,
        enable_checkpoints=True
    )

    # Should raise error
    with pytest.raises(RuntimeError, match="Workflow execution produced no output"):
        executor.execute_with_checkpoints(
            input_data={"topic": "test"},
            workflow_id="wf-empty"
        )


def test_checkpoint_with_tracker(tmp_path):
    """Verify tracker integration during checkpointing."""
    # Create mock tracker
    mock_tracker = Mock()

    # Create mock graph
    mock_graph = Mock()
    stage_chunks = [
        {"stage1": {"stage_outputs": {"stage1": "r1"}, "current_stage": "stage1", "workflow_id": "wf-tracked"}},
        {"stage2": {"stage_outputs": {"stage1": "r1", "stage2": "r2"}, "current_stage": "stage2", "workflow_id": "wf-tracked"}},
    ]
    mock_graph.stream = Mock(return_value=iter(stage_chunks))

    checkpoint_manager = CheckpointManager(storage_path=str(tmp_path))
    executor = WorkflowExecutor(
        graph=mock_graph,
        tracker=mock_tracker,
        checkpoint_manager=checkpoint_manager,
        enable_checkpoints=True
    )

    # Execute with checkpoints
    result = executor.execute_with_checkpoints(
        input_data={"topic": "test"},
        workflow_id="wf-tracked",
        checkpoint_interval=1
    )

    # Verify tracker was called for checkpoint events
    assert mock_tracker.log_event.called
    log_calls = [call[0][0] for call in mock_tracker.log_event.call_args_list]
    assert "checkpoint_saved" in log_calls


def test_checkpoint_error_handling_doesnt_mask_original_error(tmp_path):
    """Verify checkpoint save errors don't mask original workflow errors."""
    # Create mock graph that fails
    mock_graph = Mock()

    def failing_stream(state):
        yield {"stage1": {"stage_outputs": {"stage1": "r1"}, "current_stage": "stage1", "workflow_id": "wf-error"}}
        raise ValueError("Original workflow error")

    mock_graph.stream = Mock(side_effect=failing_stream)

    # Create checkpoint manager that fails on save DURING error handling (not during interval save)
    checkpoint_manager = CheckpointManager(storage_path=str(tmp_path))
    original_save = checkpoint_manager.save_checkpoint

    call_count = [0]

    def failing_save(workflow_id, domain_state):
        call_count[0] += 1
        # First call (interval checkpoint) succeeds
        if call_count[0] == 1:
            return original_save(workflow_id, domain_state)
        # Second call (error handling checkpoint) fails
        else:
            raise IOError("Checkpoint save failed during error handling")

    checkpoint_manager.save_checkpoint = failing_save

    # Create mock tracker to verify error logging
    mock_tracker = Mock()

    # Create executor
    executor = WorkflowExecutor(
        graph=mock_graph,
        tracker=mock_tracker,
        checkpoint_manager=checkpoint_manager,
        enable_checkpoints=True
    )

    # Should raise original error, not checkpoint save error
    with pytest.raises(ValueError, match="Original workflow error"):
        executor.execute_with_checkpoints(
            input_data={"topic": "test"},
            workflow_id="wf-error",
            checkpoint_interval=1
        )

    # Verify checkpoint save failure was logged
    log_calls = [call[0][0] for call in mock_tracker.log_event.call_args_list]
    assert "checkpoint_save_failed" in log_calls
