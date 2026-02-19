"""Tests for async hooks (decorators and ExecutionHook)."""
import pytest

from temper_ai.observability.backends.noop_backend import NoOpBackend
from temper_ai.observability.hooks import (
    ExecutionHook,
    LLMCallParams,
    atrack_agent,
    atrack_stage,
    atrack_workflow,
    set_tracker,
    reset_tracker,
)
from temper_ai.observability.tracker import ExecutionTracker, WorkflowTrackingParams


@pytest.fixture
def tracker():
    t = ExecutionTracker(backend=NoOpBackend())
    set_tracker(t)
    yield t
    reset_tracker()


class TestAsyncDecorators:
    """Test async tracking decorators."""

    @pytest.mark.asyncio
    async def test_atrack_workflow_decorator(self, tracker):
        @atrack_workflow("test_wf")
        async def my_workflow(workflow_id=None):
            assert workflow_id is not None
            assert workflow_id.startswith("wf-")
            return "done"

        result = await my_workflow()
        assert result == "done"

    @pytest.mark.asyncio
    async def test_atrack_stage_decorator(self, tracker):
        async with tracker.atrack_workflow(
            WorkflowTrackingParams(workflow_name="test", workflow_config={})
        ) as wf_id:

            @atrack_stage("test_stage")
            async def my_stage(config, workflow_id, stage_id=None):
                assert stage_id is not None
                return "stage_done"

            result = await my_stage({}, wf_id)
            assert result == "stage_done"

    @pytest.mark.asyncio
    async def test_atrack_agent_decorator(self, tracker):
        async with tracker.atrack_workflow(
            WorkflowTrackingParams(workflow_name="test", workflow_config={})
        ) as wf_id:
            async with tracker.atrack_stage("s", {}, wf_id) as s_id:

                @atrack_agent("test_agent")
                async def my_agent(config, stage_id, agent_id=None):
                    assert agent_id is not None
                    return "agent_done"

                result = await my_agent({}, s_id)
                assert result == "agent_done"

    @pytest.mark.asyncio
    async def test_atrack_workflow_uses_func_name(self, tracker):
        @atrack_workflow()
        async def my_custom_workflow(workflow_id=None):
            return workflow_id

        result = await my_custom_workflow()
        assert result is not None


class TestAsyncExecutionHook:
    """Test async ExecutionHook methods."""

    @pytest.mark.asyncio
    async def test_async_workflow_lifecycle(self, tracker):
        hook = ExecutionHook(tracker)
        wf_id = await hook.astart_workflow("test", {})
        assert wf_id.startswith("wf-")
        await hook.aend_workflow(wf_id)
        assert wf_id not in hook._active_contexts

    @pytest.mark.asyncio
    async def test_async_stage_lifecycle(self, tracker):
        hook = ExecutionHook(tracker)
        wf_id = await hook.astart_workflow("test", {})
        stage_id = await hook.astart_stage("stage1", {}, wf_id)
        assert stage_id is not None
        await hook.aend_stage(stage_id)
        await hook.aend_workflow(wf_id)
        assert stage_id not in hook._active_contexts

    @pytest.mark.asyncio
    async def test_async_agent_lifecycle(self, tracker):
        hook = ExecutionHook(tracker)
        wf_id = await hook.astart_workflow("test", {})
        s_id = await hook.astart_stage("stage1", {}, wf_id)
        a_id = await hook.astart_agent("agent1", {}, s_id)
        assert a_id is not None
        await hook.aend_agent(a_id)
        await hook.aend_stage(s_id)
        await hook.aend_workflow(wf_id)

    @pytest.mark.asyncio
    async def test_async_workflow_error_handling(self, tracker):
        hook = ExecutionHook(tracker)
        wf_id = await hook.astart_workflow("test", {})
        error = ValueError("workflow failed")
        await hook.aend_workflow(wf_id, error=error)
        assert wf_id not in hook._active_contexts

    @pytest.mark.asyncio
    async def test_async_end_nonexistent_is_noop(self, tracker):
        hook = ExecutionHook(tracker)
        await hook.aend_workflow("nonexistent")  # Should not raise
        await hook.aend_stage("nonexistent")
        await hook.aend_agent("nonexistent")
        assert len(hook._active_contexts) == 0

    @pytest.mark.asyncio
    async def test_async_llm_call(self, tracker):
        hook = ExecutionHook(tracker)
        wf_id = await hook.astart_workflow("test", {})
        s_id = await hook.astart_stage("s", {}, wf_id)
        a_id = await hook.astart_agent("a", {}, s_id)
        result = await hook.alog_llm_call(LLMCallParams(
            agent_id=a_id, provider="test", model="test-model",
            prompt="hi", response="hello",
            prompt_tokens=5, completion_tokens=10,
            latency_ms=50, cost=0.001,
        ))
        assert result is not None
        await hook.aend_agent(a_id)
        await hook.aend_stage(s_id)
        await hook.aend_workflow(wf_id)

    @pytest.mark.asyncio
    async def test_async_tool_call(self, tracker):
        hook = ExecutionHook(tracker)
        wf_id = await hook.astart_workflow("test", {})
        s_id = await hook.astart_stage("s", {}, wf_id)
        a_id = await hook.astart_agent("a", {}, s_id)
        result = await hook.alog_tool_call(
            a_id, "bash", {"cmd": "ls"}, {"out": "files"}, 0.1,
        )
        assert result is not None
        await hook.aend_agent(a_id)
        await hook.aend_stage(s_id)
        await hook.aend_workflow(wf_id)
