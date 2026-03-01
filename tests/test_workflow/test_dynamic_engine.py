"""Tests for DynamicExecutionEngine and DynamicCompiledWorkflow.

Tests engine interface compliance, compile/execute lifecycle,
feature detection, cancellation, metadata, and dynamic routing support.
"""

from unittest.mock import MagicMock, patch

import pytest

from temper_ai.workflow.engines.dynamic_engine import (
    DynamicCompiledWorkflow,
    DynamicExecutionEngine,
)
from temper_ai.workflow.execution_engine import (
    ExecutionMode,
    WorkflowCancelledError,
)


class TestDynamicCompiledWorkflow:
    """Test DynamicCompiledWorkflow."""

    def _make_workflow(self, stage_refs=None, run_result=None):
        """Create a DynamicCompiledWorkflow with mock executor."""
        runner = MagicMock()
        runner.run.return_value = run_result or {
            "stage_outputs": {"test": {"status": "ok"}},
            "current_stage": "test",
        }
        config = {"workflow": {"stages": stage_refs or ["stage_a"]}}
        return DynamicCompiledWorkflow(
            workflow_executor=runner,
            workflow_config=config,
            stage_refs=stage_refs or ["stage_a"],
        )

    def test_invoke(self):
        """Test synchronous invocation."""
        wf = self._make_workflow()
        result = wf.invoke({"stage_outputs": {}, "current_stage": ""})
        assert "stage_outputs" in result
        wf.workflow_executor.run.assert_called_once()

    def test_invoke_cancelled(self):
        """Test invoke raises when cancelled."""
        wf = self._make_workflow()
        wf.cancel()
        with pytest.raises(WorkflowCancelledError):
            wf.invoke({})

    @pytest.mark.asyncio
    async def test_ainvoke(self):
        """Test async invocation."""
        wf = self._make_workflow()
        result = await wf.ainvoke({"stage_outputs": {}, "current_stage": ""})
        assert "stage_outputs" in result

    @pytest.mark.asyncio
    async def test_ainvoke_cancelled(self):
        """Test ainvoke raises when cancelled."""
        wf = self._make_workflow()
        wf.cancel()
        with pytest.raises(WorkflowCancelledError):
            await wf.ainvoke({})

    def test_get_metadata(self):
        """Test metadata reports 'dynamic' engine."""
        wf = self._make_workflow(["stage_a", "stage_b"])
        meta = wf.get_metadata()
        assert meta["engine"] == "dynamic"
        assert meta["version"] == "1.0.0"
        assert meta["stages"] == ["stage_a", "stage_b"]

    def test_get_metadata_dict_stages(self):
        """Test metadata with dict stage references."""
        wf = self._make_workflow([{"name": "s1"}, {"name": "s2"}])
        meta = wf.get_metadata()
        assert meta["stages"] == ["s1", "s2"]

    def test_visualize(self):
        """Test Mermaid visualization."""
        wf = self._make_workflow(["A", "B", "C"])
        viz = wf.visualize()
        assert "flowchart TD" in viz
        assert "START" in viz
        assert "A" in viz
        assert "B" in viz
        assert "C" in viz
        assert "END" in viz
        assert "A --> B" in viz
        assert "B --> C" in viz

    def test_cancel_and_is_cancelled(self):
        """Test cancel/is_cancelled lifecycle."""
        wf = self._make_workflow()
        assert wf.is_cancelled() is False
        wf.cancel()
        assert wf.is_cancelled() is True

    def test_cancel_idempotent(self):
        """Test cancel is idempotent."""
        wf = self._make_workflow()
        wf.cancel()
        wf.cancel()
        assert wf.is_cancelled() is True


class TestDynamicExecutionEngine:
    """Test DynamicExecutionEngine."""

    def _make_engine(self):
        """Create engine with mocked safety stack."""
        with patch(
            "temper_ai.workflow.engines.dynamic_engine.create_safety_stack"
        ) as mock_safety:
            mock_safety.return_value = MagicMock()
            engine = DynamicExecutionEngine()
        return engine

    def test_supports_feature_negotiation(self):
        """Test dynamic engine supports negotiation."""
        engine = self._make_engine()
        assert engine.supports_feature("negotiation") is True
        assert engine.supports_feature("sequential_stages") is True
        assert engine.supports_feature("parallel_stages") is True
        assert engine.supports_feature("conditional_routing") is True

    def test_supports_feature_dynamic_routing(self):
        """Test dynamic engine supports dynamic routing."""
        engine = self._make_engine()
        assert engine.supports_feature("dynamic_routing") is True

    def test_supports_feature_unsupported(self):
        """Test unsupported features return False."""
        engine = self._make_engine()
        assert engine.supports_feature("distributed_execution") is False
        assert engine.supports_feature("streaming_execution") is False

    def test_compile_empty_stages_raises(self):
        """Test compile raises on empty stages."""
        engine = self._make_engine()
        with pytest.raises(ValueError, match="at least one stage"):
            engine.compile({"workflow": {"stages": []}})

    def test_compile_returns_dynamic_workflow(self):
        """Test compile returns DynamicCompiledWorkflow."""
        engine = self._make_engine()

        # Mock config_loader to return valid configs
        engine.config_loader = MagicMock()
        engine.config_loader.load_stage.return_value = {
            "stage": {
                "name": "test_stage",
                "agents": ["test_agent"],
                "execution": {"agent_mode": "sequential"},
            }
        }
        engine.config_loader.load_agent.return_value = {
            "name": "test_agent",
            "system_prompt": "You are a test agent.",
            "inference": {"provider": "ollama", "model": "test"},
        }

        # Re-initialize components with mocked config_loader
        engine._initialize_components()

        config = {"workflow": {"stages": ["test_stage"]}}
        compiled = engine.compile(config)

        assert isinstance(compiled, DynamicCompiledWorkflow)

    def test_execute_wrong_type_raises(self):
        """Test execute raises on wrong compiled workflow type."""
        engine = self._make_engine()
        with pytest.raises(TypeError, match="DynamicCompiledWorkflow"):
            engine.execute(MagicMock(), {})

    def test_execute_stream_raises(self):
        """Test execute raises on STREAM mode."""
        engine = self._make_engine()
        wf = MagicMock(spec=DynamicCompiledWorkflow)
        with pytest.raises(NotImplementedError, match="STREAM"):
            engine.execute(wf, {}, mode=ExecutionMode.STREAM)

    def test_execute_sync(self):
        """Test SYNC execution calls invoke."""
        engine = self._make_engine()

        runner = MagicMock()
        runner.run.return_value = {
            "stage_outputs": {"s": {"status": "ok"}},
            "current_stage": "s",
            "workflow_id": "test",
            "workflow_inputs": {"topic": "test"},
        }
        wf = DynamicCompiledWorkflow(
            workflow_executor=runner,
            workflow_config={"workflow": {"stages": ["s"]}},
            stage_refs=["s"],
        )

        result = engine.execute(wf, {"topic": "test"})
        assert result is not None
        runner.run.assert_called_once()

    @pytest.mark.asyncio
    async def test_async_execute(self):
        """Test async execution."""
        engine = self._make_engine()

        runner = MagicMock()
        runner.run.return_value = {
            "stage_outputs": {"s": {"status": "ok"}},
            "current_stage": "s",
        }
        wf = DynamicCompiledWorkflow(
            workflow_executor=runner,
            workflow_config={"workflow": {"stages": ["s"]}},
            stage_refs=["s"],
        )

        result = await engine.async_execute(wf, {"topic": "test"})
        assert result is not None

    @pytest.mark.asyncio
    async def test_async_execute_wrong_type(self):
        """Test async_execute raises on wrong type."""
        engine = self._make_engine()
        with pytest.raises(TypeError, match="DynamicCompiledWorkflow"):
            await engine.async_execute(MagicMock(), {})

    @pytest.mark.asyncio
    async def test_async_execute_stream_raises(self):
        """Test async_execute raises on STREAM mode."""
        engine = self._make_engine()
        wf = MagicMock(spec=DynamicCompiledWorkflow)
        with pytest.raises(NotImplementedError, match="STREAM"):
            await engine.async_execute(wf, {}, mode=ExecutionMode.STREAM)


class TestEngineRegistration:
    """Test that dynamic engine is registered in EngineRegistry."""

    def test_dynamic_in_registry(self):
        """Test dynamic engine is available via registry."""
        from temper_ai.workflow.engine_registry import EngineRegistry

        registry = EngineRegistry()
        assert "dynamic" in registry.list_engines()

    def test_get_dynamic_engine(self):
        """Test creating dynamic engine via registry."""
        from temper_ai.workflow.engine_registry import EngineRegistry

        registry = EngineRegistry()
        with patch(
            "temper_ai.workflow.engines.dynamic_engine.create_safety_stack"
        ) as mock:
            mock.return_value = MagicMock()
            engine = registry.get_engine("dynamic")
        assert isinstance(engine, DynamicExecutionEngine)

    def test_config_based_selection(self):
        """Test engine selection from workflow config."""
        from temper_ai.workflow.engine_registry import EngineRegistry

        registry = EngineRegistry()
        config = {"workflow": {"engine": "dynamic", "stages": ["s1"]}}

        with patch(
            "temper_ai.workflow.engines.dynamic_engine.create_safety_stack"
        ) as mock:
            mock.return_value = MagicMock()
            engine = registry.get_engine_from_config(config)
        assert isinstance(engine, DynamicExecutionEngine)


class TestBackwardCompatibility:
    """Test that old Native* names still work."""

    def test_native_names_importable(self):
        """Test NativeExecutionEngine and NativeCompiledWorkflow still importable."""
        from temper_ai.workflow.engines.native_engine import (
            NativeCompiledWorkflow,
            NativeExecutionEngine,
        )

        assert NativeExecutionEngine is DynamicExecutionEngine
        assert NativeCompiledWorkflow is DynamicCompiledWorkflow

    def test_native_from_init(self):
        """Test old names from engines __init__."""
        from temper_ai.workflow.engines import (
            NativeCompiledWorkflow,
            NativeExecutionEngine,
        )

        assert NativeExecutionEngine is DynamicExecutionEngine
        assert NativeCompiledWorkflow is DynamicCompiledWorkflow
