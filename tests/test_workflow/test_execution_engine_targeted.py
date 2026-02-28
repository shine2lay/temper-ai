"""Targeted tests for workflow/execution_engine.py to improve coverage from 77% to 90%+.

The module defines abstract ABCs. We test them through concrete subclasses.
"""

import pytest

from temper_ai.shared.utils.exceptions import ErrorCode
from temper_ai.workflow.execution_engine import (
    CompiledWorkflow,
    ExecutionEngine,
    ExecutionMode,
    WorkflowCancelledError,
)

# ---------------------------------------------------------------------------
# Concrete implementations for testing
# ---------------------------------------------------------------------------


class ConcreteCompiledWorkflow(CompiledWorkflow):
    """Minimal concrete implementation for testing abstract class."""

    def __init__(self, return_state: dict = None, should_raise: Exception = None):
        self._state = return_state or {"output": "done"}
        self._should_raise = should_raise
        self._cancelled = False

    def invoke(self, state: dict) -> dict:
        if self._should_raise:
            raise self._should_raise
        return {**state, **self._state}

    async def ainvoke(self, state: dict) -> dict:
        if self._should_raise:
            raise self._should_raise
        return {**state, **self._state}

    def get_metadata(self) -> dict:
        return {"engine": "test", "version": "1.0", "config": {}, "stages": []}

    def visualize(self) -> str:
        return "graph TD\n  A --> B"

    def cancel(self) -> None:
        self._cancelled = True

    def is_cancelled(self) -> bool:
        return self._cancelled


class ConcreteExecutionEngine(ExecutionEngine):
    """Minimal concrete ExecutionEngine for testing."""

    def compile(self, workflow_config: dict) -> CompiledWorkflow:
        return ConcreteCompiledWorkflow()

    def execute(self, compiled_workflow, input_data, mode=ExecutionMode.SYNC):
        if mode == ExecutionMode.SYNC:
            return compiled_workflow.invoke(input_data)
        raise NotImplementedError(f"Mode {mode} not supported in execute()")

    async def async_execute(
        self, compiled_workflow, input_data, mode=ExecutionMode.ASYNC
    ):
        return await compiled_workflow.ainvoke(input_data)

    def supports_feature(self, feature: str) -> bool:
        return feature in {"sequential_stages", "conditional_routing"}


# ---------------------------------------------------------------------------
# WorkflowCancelledError
# ---------------------------------------------------------------------------


class TestWorkflowCancelledError:
    def test_default_message(self):
        err = WorkflowCancelledError()
        assert "cancelled" in str(err).lower()

    def test_custom_message(self):
        err = WorkflowCancelledError("Custom cancel message")
        assert "Custom cancel message" in str(err)

    def test_has_error_code(self):
        err = WorkflowCancelledError()
        assert err.error_code == ErrorCode.WORKFLOW_EXECUTION_ERROR

    def test_is_workflow_error(self):
        from temper_ai.shared.utils.exceptions import WorkflowError

        err = WorkflowCancelledError()
        assert isinstance(err, WorkflowError)


# ---------------------------------------------------------------------------
# ExecutionMode
# ---------------------------------------------------------------------------


class TestExecutionMode:
    def test_sync_value(self):
        assert ExecutionMode.SYNC.value == "sync"

    def test_async_value(self):
        assert ExecutionMode.ASYNC.value == "async"

    def test_stream_value(self):
        assert ExecutionMode.STREAM.value == "stream"

    def test_modes_are_distinct(self):
        modes = [ExecutionMode.SYNC, ExecutionMode.ASYNC, ExecutionMode.STREAM]
        assert len(set(modes)) == 3


# ---------------------------------------------------------------------------
# CompiledWorkflow (concrete)
# ---------------------------------------------------------------------------


class TestConcreteCompiledWorkflow:
    def test_invoke_returns_state(self):
        wf = ConcreteCompiledWorkflow({"result": "hello"})
        result = wf.invoke({"input": "data"})
        assert result["result"] == "hello"
        assert result["input"] == "data"

    @pytest.mark.asyncio
    async def test_ainvoke_returns_state(self):
        wf = ConcreteCompiledWorkflow({"result": "async-done"})
        result = await wf.ainvoke({"input": "data"})
        assert result["result"] == "async-done"

    def test_get_metadata(self):
        wf = ConcreteCompiledWorkflow()
        meta = wf.get_metadata()
        assert "engine" in meta
        assert "stages" in meta

    def test_visualize(self):
        wf = ConcreteCompiledWorkflow()
        vis = wf.visualize()
        assert isinstance(vis, str)

    def test_cancel_sets_flag(self):
        wf = ConcreteCompiledWorkflow()
        assert not wf.is_cancelled()
        wf.cancel()
        assert wf.is_cancelled()

    def test_cancel_is_idempotent(self):
        wf = ConcreteCompiledWorkflow()
        wf.cancel()
        wf.cancel()
        assert wf.is_cancelled()

    def test_invoke_with_raise(self):
        err = RuntimeError("execution failed")
        wf = ConcreteCompiledWorkflow(should_raise=err)
        with pytest.raises(RuntimeError, match="execution failed"):
            wf.invoke({})

    @pytest.mark.asyncio
    async def test_ainvoke_with_raise(self):
        err = ValueError("async fail")
        wf = ConcreteCompiledWorkflow(should_raise=err)
        with pytest.raises(ValueError, match="async fail"):
            await wf.ainvoke({})


# ---------------------------------------------------------------------------
# ExecutionEngine (concrete)
# ---------------------------------------------------------------------------


class TestConcreteExecutionEngine:
    def test_compile_returns_compiled_workflow(self):
        engine = ConcreteExecutionEngine()
        wf = engine.compile({"workflow": {"stages": []}})
        assert isinstance(wf, CompiledWorkflow)

    def test_execute_sync(self):
        engine = ConcreteExecutionEngine()
        compiled = engine.compile({})
        result = engine.execute(compiled, {"input": "data"})
        assert "output" in result

    def test_execute_unsupported_mode_raises(self):
        engine = ConcreteExecutionEngine()
        compiled = engine.compile({})
        with pytest.raises(NotImplementedError):
            engine.execute(compiled, {}, mode=ExecutionMode.STREAM)

    @pytest.mark.asyncio
    async def test_async_execute(self):
        engine = ConcreteExecutionEngine()
        compiled = engine.compile({})
        result = await engine.async_execute(compiled, {"input": "test"})
        assert "output" in result

    def test_supports_feature_true(self):
        engine = ConcreteExecutionEngine()
        assert engine.supports_feature("sequential_stages") is True
        assert engine.supports_feature("conditional_routing") is True

    def test_supports_feature_false(self):
        engine = ConcreteExecutionEngine()
        assert engine.supports_feature("distributed_execution") is False
        assert engine.supports_feature("unknown_feature") is False

    def test_cannot_instantiate_abstract_engine(self):
        with pytest.raises(TypeError):
            ExecutionEngine()  # type: ignore

    def test_cannot_instantiate_abstract_compiled_workflow(self):
        with pytest.raises(TypeError):
            CompiledWorkflow()  # type: ignore
