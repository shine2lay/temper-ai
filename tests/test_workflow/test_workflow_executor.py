"""Tests for WorkflowExecutor class."""
from unittest.mock import Mock

import pytest
from langgraph.graph import StateGraph

from src.workflow.domain_state import WorkflowDomainState
from src.stage.executors.state_keys import StateKeys
from src.workflow.state_manager import StateManager
from src.workflow.workflow_executor import WorkflowExecutor
from src.observability.tracker import ExecutionTracker


class TestWorkflowExecutorInitialization:
    """Test WorkflowExecutor initialization."""

    def test_init_with_graph(self):
        """Test initialization with compiled graph."""
        mock_graph = Mock(spec=StateGraph)

        executor = WorkflowExecutor(mock_graph)

        assert executor.graph is mock_graph
        assert executor.tracker is None
        assert isinstance(executor.state_manager, StateManager)

    def test_init_with_tracker(self):
        """Test initialization with tracker."""
        mock_graph = Mock(spec=StateGraph)
        mock_tracker = Mock(spec=ExecutionTracker)

        executor = WorkflowExecutor(mock_graph, tracker=mock_tracker)

        assert executor.tracker is mock_tracker

    def test_init_with_custom_state_manager(self):
        """Test initialization with custom state manager."""
        mock_graph = Mock(spec=StateGraph)
        custom_state_manager = Mock(spec=StateManager)

        executor = WorkflowExecutor(mock_graph, state_manager=custom_state_manager)

        assert executor.state_manager is custom_state_manager


class TestExecute:
    """Test synchronous execute method."""

    def test_execute_basic(self):
        """Test basic execution."""
        mock_graph = Mock()
        mock_graph.invoke = Mock(return_value={
            "workflow_id": "wf-123",
            "stage_outputs": {"research": "output"}
        })

        executor = WorkflowExecutor(mock_graph)
        result = executor.execute({"input": "data"})

        # Verify graph was invoked
        mock_graph.invoke.assert_called_once()

        # Verify result
        assert "workflow_id" in result
        assert "stage_outputs" in result

    def test_execute_with_workflow_id(self):
        """Test execution with custom workflow ID."""
        mock_graph = Mock()
        mock_graph.invoke = Mock(return_value={"workflow_id": "custom-123"})

        executor = WorkflowExecutor(mock_graph)
        result = executor.execute(
            input_data={"topic": "AI"},
            workflow_id="custom-123"
        )

        # Verify state manager received workflow_id
        call_args = mock_graph.invoke.call_args[0][0]
        assert "workflow_id" in call_args

    def test_execute_initializes_state(self):
        """Test that execute initializes state via state manager."""
        mock_graph = Mock()
        mock_graph.invoke = Mock(return_value={})

        mock_state_manager = Mock(spec=StateManager)
        mock_state_manager.initialize_state.return_value = WorkflowDomainState(
            workflow_id="wf-456"
        )

        executor = WorkflowExecutor(mock_graph, state_manager=mock_state_manager)
        executor.execute({"input": "data"})

        # Verify state manager was called
        mock_state_manager.initialize_state.assert_called_once()

    def test_execute_passes_tracker(self):
        """Test that execute passes tracker to state initialization."""
        mock_graph = Mock()
        mock_graph.invoke = Mock(return_value={})

        mock_tracker = Mock(spec=ExecutionTracker)
        mock_state_manager = Mock(spec=StateManager)
        mock_state_manager.initialize_state.return_value = WorkflowDomainState()

        executor = WorkflowExecutor(
            mock_graph,
            tracker=mock_tracker,
            state_manager=mock_state_manager
        )
        executor.execute({"input": "data"})

        # Verify tracker was passed to initialize_state
        call_kwargs = mock_state_manager.initialize_state.call_args[1]
        assert call_kwargs["tracker"] is mock_tracker


class TestExecuteAsync:
    """Test asynchronous execute_async method."""

    @pytest.mark.asyncio
    async def test_execute_async_basic(self):
        """Test basic async execution."""
        from unittest.mock import AsyncMock

        mock_graph = Mock()
        mock_graph.ainvoke = AsyncMock(return_value={
            "workflow_id": "wf-async-123",
            "stage_outputs": {"research": "output"}
        })

        executor = WorkflowExecutor(mock_graph)
        result = await executor.execute_async({"input": "data"})

        # Verify async graph was invoked
        mock_graph.ainvoke.assert_called_once()

        # Verify result
        assert "workflow_id" in result
        assert "stage_outputs" in result

    @pytest.mark.asyncio
    async def test_execute_async_with_workflow_id(self):
        """Test async execution with custom workflow ID."""
        from unittest.mock import AsyncMock

        mock_graph = Mock()
        mock_graph.ainvoke = AsyncMock(return_value={"workflow_id": "custom-async"})

        executor = WorkflowExecutor(mock_graph)
        result = await executor.execute_async(
            input_data={"topic": "quantum"},
            workflow_id="custom-async"
        )

        # Verify state was initialized with workflow_id
        call_args = mock_graph.ainvoke.call_args[0][0]
        assert "workflow_id" in call_args

    @pytest.mark.asyncio
    async def test_execute_async_initializes_state(self):
        """Test that execute_async initializes state via state manager."""
        from unittest.mock import AsyncMock

        mock_graph = Mock()
        mock_graph.ainvoke = AsyncMock(return_value={})

        mock_state_manager = Mock(spec=StateManager)
        mock_state_manager.initialize_state.return_value = WorkflowDomainState(
            workflow_id="wf-async-789"
        )

        executor = WorkflowExecutor(mock_graph, state_manager=mock_state_manager)
        await executor.execute_async({"input": "data"})

        # Verify state manager was called
        mock_state_manager.initialize_state.assert_called_once()


class TestStream:
    """Test stream method."""

    def test_stream_yields_chunks(self):
        """Test that stream yields intermediate states."""
        mock_graph = Mock()

        # Mock stream to yield multiple chunks
        chunks = [
            {"current_stage": "research", "stage_outputs": {}},
            {"current_stage": "analysis", "stage_outputs": {"research": "output1"}},
            {"current_stage": "synthesis", "stage_outputs": {"research": "output1", "analysis": "output2"}},
        ]
        mock_graph.stream = Mock(return_value=iter(chunks))

        executor = WorkflowExecutor(mock_graph)
        results = list(executor.stream({"input": "data"}))

        # Verify all chunks were yielded
        assert len(results) == 3
        assert results[0][StateKeys.CURRENT_STAGE] == "research"
        assert results[1][StateKeys.CURRENT_STAGE] == "analysis"
        assert results[2][StateKeys.CURRENT_STAGE] == "synthesis"

    def test_stream_initializes_state(self):
        """Test that stream initializes state via state manager."""
        mock_graph = Mock()
        mock_graph.stream = Mock(return_value=iter([]))

        mock_state_manager = Mock(spec=StateManager)
        mock_state_manager.initialize_state.return_value = WorkflowDomainState(
            workflow_id="wf-stream-123"
        )

        executor = WorkflowExecutor(mock_graph, state_manager=mock_state_manager)
        list(executor.stream({"input": "data"}))

        # Verify state manager was called
        mock_state_manager.initialize_state.assert_called_once()


class TestBackwardCompatibility:
    """Test backward compatibility with imports."""

    def test_can_import_from_langgraph_compiler(self):
        """Test that WorkflowExecutor can still be imported from langgraph_compiler."""
        from src.workflow.langgraph_compiler import WorkflowExecutor as OldImport
        from src.workflow.workflow_executor import WorkflowExecutor as NewImport

        # Should be the same class
        assert OldImport is NewImport


class TestCheckpointSupport:
    """Test checkpoint/resume functionality in WorkflowExecutor."""

    def test_init_with_checkpoint_manager(self):
        """Test initialization with checkpoint manager."""
        import tempfile

        from src.workflow.checkpoint import CheckpointManager

        mock_graph = Mock()
        with tempfile.TemporaryDirectory() as tmpdir:
            checkpoint_manager = CheckpointManager(storage_path=tmpdir)

            executor = WorkflowExecutor(
                mock_graph,
                checkpoint_manager=checkpoint_manager,
                enable_checkpoints=True
            )

            assert executor.checkpoint_manager is checkpoint_manager
            assert executor.enable_checkpoints is True

    def test_init_auto_creates_checkpoint_manager(self):
        """Test that checkpoint manager is auto-created when enable_checkpoints=True."""
        mock_graph = Mock()

        executor = WorkflowExecutor(mock_graph, enable_checkpoints=True)

        assert executor.checkpoint_manager is not None
        assert executor.enable_checkpoints is True

    def test_execute_with_checkpoints_basic(self):
        """Test basic execution with checkpointing."""
        import tempfile

        from src.workflow.checkpoint import CheckpointManager

        mock_graph = Mock()
        # Mock stream to return chunks (updated to use streaming)
        stage_chunks = [
            {"stage1": {
                "workflow_id": "wf-checkpoint-test",
                "stage_outputs": {"stage1": "output1"},
                "current_stage": "stage1",
            }}
        ]
        mock_graph.stream = Mock(return_value=iter(stage_chunks))

        with tempfile.TemporaryDirectory() as tmpdir:
            checkpoint_manager = CheckpointManager(storage_path=tmpdir)
            executor = WorkflowExecutor(
                mock_graph,
                checkpoint_manager=checkpoint_manager,
                enable_checkpoints=True
            )

            result = executor.execute_with_checkpoints({"input": "test"})

            # Verify execution completed
            assert "workflow_id" in result
            assert "stage_outputs" in result

            # Verify checkpoint was saved
            assert checkpoint_manager.has_checkpoint("wf-checkpoint-test")

    def test_execute_with_checkpoints_no_manager_raises(self):
        """Test that execute_with_checkpoints raises error without checkpoint manager."""
        mock_graph = Mock()
        executor = WorkflowExecutor(mock_graph)  # No checkpoint manager

        with pytest.raises(RuntimeError, match="Checkpoint manager not configured"):
            executor.execute_with_checkpoints({"input": "test"})

    def test_resume_from_checkpoint_basic(self):
        """Test resuming execution from checkpoint."""
        import tempfile

        from src.workflow.checkpoint import CheckpointManager
        from src.workflow.domain_state import WorkflowDomainState

        # Create and save a checkpoint
        with tempfile.TemporaryDirectory() as tmpdir:
            checkpoint_manager = CheckpointManager(storage_path=tmpdir)

            # Save checkpoint
            domain_state = WorkflowDomainState(
                workflow_id="wf-resume-test",
                input="test input",
            )
            domain_state.set_stage_output("stage1", "output1")
            checkpoint_manager.save_checkpoint("wf-resume-test", domain_state)

            # Create executor and resume
            mock_graph = Mock()
            # Mock stream to return remaining chunks (updated to use streaming)
            remaining_chunks = [
                {"stage2": {
                    "workflow_id": "wf-resume-test",
                    "stage_outputs": {
                        "stage1": "output1",
                        "stage2": "output2"  # New stage completed
                    },
                    "current_stage": "stage2",
                    "input": "test input",
                }}
            ]
            mock_graph.stream = Mock(return_value=iter(remaining_chunks))

            executor = WorkflowExecutor(
                mock_graph,
                checkpoint_manager=checkpoint_manager
            )

            result = executor.resume_from_checkpoint("wf-resume-test")

            # Verify execution completed
            assert result[StateKeys.WORKFLOW_ID] == "wf-resume-test"
            assert "stage2" in result[StateKeys.STAGE_OUTPUTS]

            # Verify graph was streamed with checkpointed state
            mock_graph.stream.assert_called_once()
            call_args = mock_graph.stream.call_args[0][0]
            assert "stage_outputs" in call_args
            assert "stage1" in call_args[StateKeys.STAGE_OUTPUTS]

    def test_resume_from_checkpoint_no_manager_raises(self):
        """Test that resume raises error without checkpoint manager."""
        mock_graph = Mock()
        executor = WorkflowExecutor(mock_graph)  # No checkpoint manager

        with pytest.raises(RuntimeError, match="Checkpoint manager not configured"):
            executor.resume_from_checkpoint("wf-test")

    def test_resume_from_checkpoint_not_found_raises(self):
        """Test that resume raises error if checkpoint not found."""
        import tempfile

        from src.workflow.checkpoint_backends import CheckpointNotFoundError, FileCheckpointBackend
        from src.workflow.checkpoint_manager import CheckpointManager

        with tempfile.TemporaryDirectory() as tmpdir:
            backend = FileCheckpointBackend(checkpoint_dir=tmpdir)
            checkpoint_manager = CheckpointManager(backend=backend)
            mock_graph = Mock()

            executor = WorkflowExecutor(
                mock_graph,
                checkpoint_manager=checkpoint_manager
            )

            with pytest.raises(CheckpointNotFoundError):
                executor.resume_from_checkpoint("wf-nonexistent")

    def test_extract_domain_state(self):
        """Test extracting domain state from workflow state dict."""
        import tempfile

        from src.workflow.checkpoint_backends import FileCheckpointBackend
        from src.workflow.checkpoint_manager import CheckpointManager

        mock_graph = Mock()
        with tempfile.TemporaryDirectory() as tmpdir:
            backend = FileCheckpointBackend(checkpoint_dir=tmpdir)
            checkpoint_manager = CheckpointManager(backend=backend)
            executor = WorkflowExecutor(
                mock_graph,
                checkpoint_manager=checkpoint_manager
            )

            # State dict with both domain and infrastructure fields
            state_dict = {
                "workflow_id": "wf-extract-test",
                "stage_outputs": {"stage1": "output1"},
                "current_stage": "stage1",
                "input": "test",
                "tracker": Mock(),  # Infrastructure - should be excluded
                "tool_registry": Mock(),  # Infrastructure - should be excluded
            }

            domain_state = executor._extract_domain_state(state_dict)

            # Verify only domain fields extracted
            assert domain_state.workflow_id == "wf-extract-test"
            assert domain_state.stage_outputs == {"stage1": "output1"}
            assert domain_state.current_stage == "stage1"
            assert domain_state.input == "test"

            # Verify infrastructure not included
            assert not hasattr(domain_state, "tracker")
            assert not hasattr(domain_state, "tool_registry")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
