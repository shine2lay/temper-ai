"""Tests for abstract execution engine interface.

These tests verify that the interface classes are properly abstract and
cannot be instantiated directly. Concrete implementations should be tested
separately.
"""

import time

import pytest

from src.workflow.execution_engine import (
    CompiledWorkflow,
    ExecutionEngine,
    ExecutionMode,
    WorkflowCancelledError,
)


class TestExecutionEngine:
    """Test ExecutionEngine abstract interface."""

    def test_execution_engine_is_abstract(self):
        """ExecutionEngine cannot be instantiated directly."""
        with pytest.raises(TypeError, match="Can't instantiate abstract class"):
            ExecutionEngine()

    def test_execution_engine_has_compile_method(self):
        """ExecutionEngine defines compile abstract method."""
        assert hasattr(ExecutionEngine, 'compile')
        assert getattr(ExecutionEngine.compile, '__isabstractmethod__', False)

    def test_execution_engine_has_execute_method(self):
        """ExecutionEngine defines execute abstract method."""
        assert hasattr(ExecutionEngine, 'execute')
        assert getattr(ExecutionEngine.execute, '__isabstractmethod__', False)

    def test_execution_engine_has_supports_feature_method(self):
        """ExecutionEngine defines supports_feature abstract method."""
        assert hasattr(ExecutionEngine, 'supports_feature')
        assert getattr(ExecutionEngine.supports_feature, '__isabstractmethod__', False)


class TestCompiledWorkflow:
    """Test CompiledWorkflow abstract interface."""

    def test_compiled_workflow_is_abstract(self):
        """CompiledWorkflow cannot be instantiated directly."""
        with pytest.raises(TypeError, match="Can't instantiate abstract class"):
            CompiledWorkflow()

    def test_compiled_workflow_has_invoke_method(self):
        """CompiledWorkflow defines invoke abstract method."""
        assert hasattr(CompiledWorkflow, 'invoke')
        assert getattr(CompiledWorkflow.invoke, '__isabstractmethod__', False)

    def test_compiled_workflow_has_ainvoke_method(self):
        """CompiledWorkflow defines ainvoke abstract method."""
        assert hasattr(CompiledWorkflow, 'ainvoke')
        assert getattr(CompiledWorkflow.ainvoke, '__isabstractmethod__', False)

    def test_compiled_workflow_has_get_metadata_method(self):
        """CompiledWorkflow defines get_metadata abstract method."""
        assert hasattr(CompiledWorkflow, 'get_metadata')
        assert getattr(CompiledWorkflow.get_metadata, '__isabstractmethod__', False)

    def test_compiled_workflow_has_visualize_method(self):
        """CompiledWorkflow defines visualize abstract method."""
        assert hasattr(CompiledWorkflow, 'visualize')
        assert getattr(CompiledWorkflow.visualize, '__isabstractmethod__', False)

    def test_compiled_workflow_has_cancel_method(self):
        """CompiledWorkflow defines cancel abstract method."""
        assert hasattr(CompiledWorkflow, 'cancel')
        assert getattr(CompiledWorkflow.cancel, '__isabstractmethod__', False)

    def test_compiled_workflow_has_is_cancelled_method(self):
        """CompiledWorkflow defines is_cancelled abstract method."""
        assert hasattr(CompiledWorkflow, 'is_cancelled')
        assert getattr(CompiledWorkflow.is_cancelled, '__isabstractmethod__', False)


class TestExecutionMode:
    """Test ExecutionMode enum."""

    def test_execution_mode_has_sync(self):
        """ExecutionMode has SYNC value."""
        assert ExecutionMode.SYNC.value == "sync"

    def test_execution_mode_has_async(self):
        """ExecutionMode has ASYNC value."""
        assert ExecutionMode.ASYNC.value == "async"

    def test_execution_mode_has_stream(self):
        """ExecutionMode has STREAM value."""
        assert ExecutionMode.STREAM.value == "stream"

    def test_execution_mode_comparison(self):
        """ExecutionMode values can be compared."""
        assert ExecutionMode.SYNC == ExecutionMode.SYNC
        assert ExecutionMode.SYNC != ExecutionMode.ASYNC
        assert ExecutionMode.ASYNC != ExecutionMode.STREAM

    def test_execution_mode_membership(self):
        """ExecutionMode can be checked for membership."""
        assert ExecutionMode.SYNC in ExecutionMode
        assert ExecutionMode.ASYNC in ExecutionMode
        assert ExecutionMode.STREAM in ExecutionMode

    def test_execution_mode_serialization(self):
        """ExecutionMode can be serialized to string."""
        assert str(ExecutionMode.SYNC.value) == "sync"
        assert str(ExecutionMode.ASYNC.value) == "async"
        assert str(ExecutionMode.STREAM.value) == "stream"

    def test_execution_mode_iteration(self):
        """ExecutionMode can be iterated."""
        modes = list(ExecutionMode)
        assert len(modes) == 3
        assert ExecutionMode.SYNC in modes
        assert ExecutionMode.ASYNC in modes
        assert ExecutionMode.STREAM in modes


class TestWorkflowCancelledError:
    """Test WorkflowCancelledError exception."""

    def test_workflow_cancelled_error_is_exception(self):
        """WorkflowCancelledError is an Exception."""
        assert issubclass(WorkflowCancelledError, Exception)

    def test_workflow_cancelled_error_can_be_raised(self):
        """WorkflowCancelledError can be raised and caught."""
        with pytest.raises(WorkflowCancelledError):
            raise WorkflowCancelledError("Test cancellation")

    def test_workflow_cancelled_error_has_message(self):
        """WorkflowCancelledError preserves error message."""
        message = "Workflow was cancelled during execution"
        try:
            raise WorkflowCancelledError(message)
        except WorkflowCancelledError as e:
            # Since WorkflowCancelledError now inherits from WorkflowError,
            # the string representation includes the error code prefix
            assert message in str(e)
            assert "[WORKFLOW_EXECUTION_ERROR]" in str(e)


class TestWorkflowCancellation:
    """Test workflow cancellation functionality.

    These tests use LangGraphExecutionEngine to test the concrete
    implementation of cancellation in LangGraphCompiledWorkflow.
    """

    @pytest.fixture
    def minimal_workflow_config(self):
        """Minimal workflow configuration for testing."""
        return {
            "workflow": {
                "name": "test_workflow",
                "version": "1.0",
                "stages": [
                    {
                        "name": "test_stage",
                        "agent_config": "configs/agents/simple_agent.yaml"
                    }
                ]
            }
        }

    @pytest.fixture
    def engine(self):
        """Create LangGraphExecutionEngine instance."""
        from src.workflow.langgraph_engine import LangGraphExecutionEngine
        return LangGraphExecutionEngine()

    def test_compiled_workflow_is_not_cancelled_initially(self, engine, minimal_workflow_config):
        """Newly compiled workflows are not cancelled."""
        from unittest.mock import MagicMock, Mock

        # Mock the compiler to return a simple graph
        engine.compiler = Mock()
        mock_graph = MagicMock()
        engine.compiler.compile.return_value = mock_graph

        compiled = engine.compile(minimal_workflow_config)

        assert compiled.is_cancelled() is False

    def test_cancel_sets_cancelled_flag(self, engine, minimal_workflow_config):
        """Calling cancel() sets the cancelled flag."""
        from unittest.mock import MagicMock, Mock

        # Mock the compiler
        engine.compiler = Mock()
        mock_graph = MagicMock()
        engine.compiler.compile.return_value = mock_graph

        compiled = engine.compile(minimal_workflow_config)

        # Initially not cancelled
        assert compiled.is_cancelled() is False

        # Cancel the workflow
        compiled.cancel()

        # Now it should be cancelled
        assert compiled.is_cancelled() is True

    def test_cancel_is_idempotent(self, engine, minimal_workflow_config):
        """Calling cancel() multiple times is safe."""
        from unittest.mock import MagicMock, Mock

        # Mock the compiler
        engine.compiler = Mock()
        mock_graph = MagicMock()
        engine.compiler.compile.return_value = mock_graph

        compiled = engine.compile(minimal_workflow_config)

        # Cancel multiple times
        compiled.cancel()
        compiled.cancel()
        compiled.cancel()

        # Should still be cancelled (no errors)
        assert compiled.is_cancelled() is True

    def test_invoke_raises_error_after_cancellation(self, engine, minimal_workflow_config):
        """invoke() raises WorkflowCancelledError after cancel()."""
        from unittest.mock import MagicMock, Mock

        # Mock the compiler
        engine.compiler = Mock()
        mock_graph = MagicMock()
        engine.compiler.compile.return_value = mock_graph

        compiled = engine.compile(minimal_workflow_config)

        # Cancel the workflow
        compiled.cancel()

        # Attempting to invoke should raise error
        with pytest.raises(WorkflowCancelledError, match="Workflow execution cancelled"):
            compiled.invoke({"input": "test"})

    @pytest.mark.asyncio
    async def test_ainvoke_raises_error_after_cancellation(self, engine, minimal_workflow_config):
        """ainvoke() raises WorkflowCancelledError after cancel()."""
        from unittest.mock import MagicMock, Mock

        # Mock the compiler
        engine.compiler = Mock()
        mock_graph = MagicMock()
        engine.compiler.compile.return_value = mock_graph

        compiled = engine.compile(minimal_workflow_config)

        # Cancel the workflow
        compiled.cancel()

        # Attempting to async invoke should raise error
        with pytest.raises(WorkflowCancelledError, match="Workflow execution cancelled"):
            await compiled.ainvoke({"input": "test"})

    def test_cancellation_during_background_execution(self, engine, minimal_workflow_config):
        """Test cancelling workflow during background execution."""
        import threading
        from unittest.mock import MagicMock, Mock

        # Mock the compiler with a slow execution
        engine.compiler = Mock()
        mock_graph = MagicMock()

        # Make invoke take some time
        def slow_invoke(state):
            time.sleep(2)  # Simulate long-running workflow
            return {"output": "completed"}

        mock_graph.invoke = slow_invoke
        engine.compiler.compile.return_value = mock_graph

        compiled = engine.compile(minimal_workflow_config)

        # Start execution in background thread
        result = {}
        error = {}

        def run_workflow():
            try:
                result['output'] = compiled.invoke({"input": "test"})
            except Exception as e:
                error['exception'] = e

        thread = threading.Thread(target=run_workflow)
        thread.start()

        # Give it a moment to start
        time.sleep(0.2)

        # Cancel the workflow (note: current running execution will complete)
        compiled.cancel()

        # Wait for thread to finish
        thread.join(timeout=5)

        # Verify cancellation flag is set
        assert compiled.is_cancelled() is True

        # Note: The already-running execution will complete,
        # but subsequent calls will fail
        with pytest.raises(WorkflowCancelledError):
            compiled.invoke({"input": "test2"})

    def test_cancellation_between_stages(self, engine, minimal_workflow_config):
        """Test that cancellation prevents next stage from executing."""
        from unittest.mock import MagicMock, Mock

        # Mock the compiler
        engine.compiler = Mock()
        mock_graph = MagicMock()
        mock_graph.invoke.return_value = {"stage1": "completed"}
        engine.compiler.compile.return_value = mock_graph

        compiled = engine.compile(minimal_workflow_config)

        # First execution succeeds
        result1 = compiled.invoke({"input": "test"})
        assert "stage1" in result1

        # Cancel before second execution
        compiled.cancel()

        # Second execution fails with cancellation error
        with pytest.raises(WorkflowCancelledError):
            compiled.invoke({"input": "test2"})
