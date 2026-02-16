"""Tests for async tracker context managers and ContextVar isolation."""
import asyncio

import pytest

from src.observability.backends.noop_backend import NoOpBackend
from src.observability.tracker import ExecutionTracker, WorkflowTrackingParams


@pytest.fixture
def tracker():
    return ExecutionTracker(backend=NoOpBackend())


class TestAsyncWorkflow:
    """Test atrack_workflow async context manager."""

    @pytest.mark.asyncio
    async def test_atrack_workflow_yields_id(self, tracker):
        params = WorkflowTrackingParams(workflow_name="test", workflow_config={})
        async with tracker.atrack_workflow(params) as wf_id:
            assert wf_id.startswith("wf-")

    @pytest.mark.asyncio
    async def test_atrack_workflow_sets_context(self, tracker):
        params = WorkflowTrackingParams(workflow_name="test", workflow_config={})
        async with tracker.atrack_workflow(params) as wf_id:
            assert tracker.context.workflow_id == wf_id
        assert tracker.context.workflow_id is None

    @pytest.mark.asyncio
    async def test_atrack_workflow_error_propagates(self, tracker):
        params = WorkflowTrackingParams(workflow_name="test", workflow_config={})
        with pytest.raises(ValueError, match="boom"):
            async with tracker.atrack_workflow(params):
                raise ValueError("boom")


class TestAsyncStage:
    """Test atrack_stage async context manager."""

    @pytest.mark.asyncio
    async def test_atrack_stage_yields_id(self, tracker):
        params = WorkflowTrackingParams(workflow_name="test", workflow_config={})
        async with tracker.atrack_workflow(params) as wf_id:
            async with tracker.atrack_stage("stage1", {}, wf_id) as stage_id:
                assert stage_id is not None
                assert len(stage_id) > 0

    @pytest.mark.asyncio
    async def test_atrack_stage_sets_context(self, tracker):
        params = WorkflowTrackingParams(workflow_name="test", workflow_config={})
        async with tracker.atrack_workflow(params) as wf_id:
            async with tracker.atrack_stage("stage1", {}, wf_id) as stage_id:
                assert tracker.context.stage_id == stage_id
            assert tracker.context.stage_id is None


class TestAsyncAgent:
    """Test atrack_agent async context manager."""

    @pytest.mark.asyncio
    async def test_atrack_agent_yields_id(self, tracker):
        params = WorkflowTrackingParams(workflow_name="test", workflow_config={})
        async with tracker.atrack_workflow(params) as wf_id:
            async with tracker.atrack_stage("stage1", {}, wf_id) as stage_id:
                async with tracker.atrack_agent("agent1", {}, stage_id) as agent_id:
                    assert agent_id is not None

    @pytest.mark.asyncio
    async def test_nested_async_contexts(self, tracker):
        """Test full workflow -> stage -> agent nesting."""
        params = WorkflowTrackingParams(workflow_name="test", workflow_config={})
        async with tracker.atrack_workflow(params) as wf_id:
            assert tracker.context.workflow_id == wf_id
            async with tracker.atrack_stage("s1", {}, wf_id) as s_id:
                assert tracker.context.stage_id == s_id
                async with tracker.atrack_agent("a1", {}, s_id) as a_id:
                    assert tracker.context.agent_id == a_id
                assert tracker.context.agent_id is None
            assert tracker.context.stage_id is None
        assert tracker.context.workflow_id is None


class TestContextVarIsolation:
    """Test ContextVar isolates session stacks between tasks."""

    @pytest.mark.asyncio
    async def test_concurrent_workflows_isolated(self):
        """Two concurrent workflows should complete without errors."""
        tracker = ExecutionTracker(backend=NoOpBackend())
        results = {}

        async def run_workflow(name):
            params = WorkflowTrackingParams(
                workflow_name=name, workflow_config={},
            )
            async with tracker.atrack_workflow(params) as wf_id:
                await asyncio.sleep(0.01)  # intentional: simulate async work
                results[name] = wf_id

        await asyncio.gather(
            run_workflow("wf_a"),
            run_workflow("wf_b"),
        )
        assert "wf_a" in results
        assert "wf_b" in results
        assert results["wf_a"] != results["wf_b"]


class TestAsyncLLMAndToolCalls:
    """Test async LLM and tool call tracking."""

    @pytest.mark.asyncio
    async def test_atrack_llm_call(self, tracker):
        from src.observability._tracker_helpers import LLMCallTrackingData
        data = LLMCallTrackingData(
            agent_id="agent-1", provider="test", model="test-model",
            prompt="hello", response="world",
            prompt_tokens=10, completion_tokens=20,
            latency_ms=100, estimated_cost_usd=0.01,
        )
        result = await tracker.atrack_llm_call(data)
        assert result is not None

    @pytest.mark.asyncio
    async def test_atrack_tool_call(self, tracker):
        from src.observability._tracker_helpers import ToolCallTrackingData
        data = ToolCallTrackingData(
            agent_id="agent-1", tool_name="bash",
            input_params={"cmd": "ls"}, output_data={"stdout": "file.txt"},
            duration_seconds=0.5, status="success",
        )
        result = await tracker.atrack_tool_call(data)
        assert result is not None
