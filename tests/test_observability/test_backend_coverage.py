"""Tests for backend.py abstract base to cover uncovered lines."""

from contextlib import contextmanager
from datetime import UTC, datetime

import pytest

from temper_ai.observability.backend import (
    AgentOutputData,
    CollaborationEventData,
    ErrorFingerprintData,
    LLMCallData,
    ObservabilityBackend,
    ReadableBackendMixin,
    SafetyViolationData,
    ToolCallData,
    WorkflowStartData,
)


class ConcreteBackend(ObservabilityBackend):
    """Concrete implementation for testing abstract class."""

    def __init__(self):
        self._calls = []

    def track_workflow_start(
        self,
        workflow_id,
        workflow_name,
        workflow_config,
        start_time,
        data=None,
        **kwargs,
    ):
        self._calls.append(("track_workflow_start", workflow_id))

    def track_workflow_end(
        self, workflow_id, end_time, status, error_message=None, error_stack_trace=None
    ):
        self._calls.append(("track_workflow_end", workflow_id))

    def update_workflow_metrics(
        self,
        workflow_id,
        total_llm_calls,
        total_tool_calls,
        total_tokens,
        total_cost_usd,
    ):
        self._calls.append(("update_workflow_metrics", workflow_id))

    def track_stage_start(
        self,
        stage_id,
        workflow_id,
        stage_name,
        stage_config,
        start_time,
        input_data=None,
    ):
        self._calls.append(("track_stage_start", stage_id))

    def track_stage_end(
        self,
        stage_id,
        end_time,
        status,
        error_message=None,
        num_agents_executed=0,
        num_agents_succeeded=0,
        num_agents_failed=0,
    ):
        self._calls.append(("track_stage_end", stage_id))

    def set_stage_output(self, stage_id, output_data, output_lineage=None):
        self._calls.append(("set_stage_output", stage_id))

    def track_agent_start(
        self, agent_id, stage_id, agent_name, agent_config, start_time, input_data=None
    ):
        self._calls.append(("track_agent_start", agent_id))

    def track_agent_end(self, agent_id, end_time, status, error_message=None):
        self._calls.append(("track_agent_end", agent_id))

    def set_agent_output(self, agent_id, output_data=None, metrics=None, **kwargs):
        self._calls.append(("set_agent_output", agent_id))

    def track_llm_call(
        self,
        llm_call_id,
        agent_id,
        provider,
        model,
        start_time=None,
        data=None,
        **kwargs,
    ):
        self._calls.append(("track_llm_call", llm_call_id))

    def track_tool_call(
        self,
        tool_execution_id,
        agent_id,
        tool_name,
        start_time=None,
        data=None,
        **kwargs,
    ):
        self._calls.append(("track_tool_call", tool_execution_id))

    def track_safety_violation(
        self, violation_severity, violation_message, policy_name, data=None, **kwargs
    ):
        self._calls.append(("track_safety_violation", policy_name))

    def track_collaboration_event(
        self, stage_id, event_type, agents_involved=None, data=None, **kwargs
    ):
        self._calls.append(("track_collaboration_event", stage_id))
        return "evt-1"

    @contextmanager
    def get_session_context(self):
        yield "test-session"

    def cleanup_old_records(self, retention_days, dry_run=False):
        return {"workflows": 0}

    def get_stats(self):
        return {"backend_type": "concrete"}


@pytest.fixture
def backend():
    return ConcreteBackend()


class TestAsyncDefaults:
    """Test that async defaults delegate to sync methods."""

    @pytest.mark.asyncio
    async def test_atrack_workflow_start(self, backend):
        now = datetime.now(UTC)
        await backend.atrack_workflow_start("wf-1", "workflow", {}, now)
        assert ("track_workflow_start", "wf-1") in backend._calls

    @pytest.mark.asyncio
    async def test_atrack_workflow_end(self, backend):
        now = datetime.now(UTC)
        await backend.atrack_workflow_end("wf-1", now, "completed")
        assert ("track_workflow_end", "wf-1") in backend._calls

    @pytest.mark.asyncio
    async def test_aupdate_workflow_metrics(self, backend):
        await backend.aupdate_workflow_metrics("wf-1", 10, 5, 1000, 0.50)
        assert ("update_workflow_metrics", "wf-1") in backend._calls

    @pytest.mark.asyncio
    async def test_atrack_stage_start(self, backend):
        now = datetime.now(UTC)
        await backend.atrack_stage_start("s-1", "wf-1", "stage", {}, now)
        assert ("track_stage_start", "s-1") in backend._calls

    @pytest.mark.asyncio
    async def test_atrack_stage_end(self, backend):
        now = datetime.now(UTC)
        await backend.atrack_stage_end("s-1", now, "completed")
        assert ("track_stage_end", "s-1") in backend._calls

    @pytest.mark.asyncio
    async def test_aset_stage_output(self, backend):
        await backend.aset_stage_output("s-1", {"data": "output"})
        assert ("set_stage_output", "s-1") in backend._calls

    @pytest.mark.asyncio
    async def test_atrack_agent_start(self, backend):
        now = datetime.now(UTC)
        await backend.atrack_agent_start("a-1", "s-1", "agent", {}, now)
        assert ("track_agent_start", "a-1") in backend._calls

    @pytest.mark.asyncio
    async def test_atrack_agent_end(self, backend):
        now = datetime.now(UTC)
        await backend.atrack_agent_end("a-1", now, "completed")
        assert ("track_agent_end", "a-1") in backend._calls

    @pytest.mark.asyncio
    async def test_aset_agent_output(self, backend):
        await backend.aset_agent_output("a-1", {"data": "output"})
        assert ("set_agent_output", "a-1") in backend._calls

    @pytest.mark.asyncio
    async def test_atrack_llm_call(self, backend):
        now = datetime.now(UTC)
        data = LLMCallData(
            prompt="test",
            response="resp",
            prompt_tokens=10,
            completion_tokens=20,
            latency_ms=100,
            estimated_cost_usd=0.001,
        )
        await backend.atrack_llm_call("l-1", "a-1", "openai", "gpt-4", now, data)
        assert ("track_llm_call", "l-1") in backend._calls

    @pytest.mark.asyncio
    async def test_atrack_tool_call(self, backend):
        now = datetime.now(UTC)
        data = ToolCallData(
            input_params={},
            output_data={},
            duration_seconds=1.0,
        )
        await backend.atrack_tool_call("t-1", "a-1", "search", now, data)
        assert ("track_tool_call", "t-1") in backend._calls

    @pytest.mark.asyncio
    async def test_atrack_safety_violation(self, backend):
        await backend.atrack_safety_violation("HIGH", "msg", "policy")
        assert ("track_safety_violation", "policy") in backend._calls

    @pytest.mark.asyncio
    async def test_atrack_collaboration_event(self, backend):
        result = await backend.atrack_collaboration_event("s-1", "vote", ["a-1"])
        assert result == "evt-1"
        assert ("track_collaboration_event", "s-1") in backend._calls

    @pytest.mark.asyncio
    async def test_aget_session_context(self, backend):
        async with backend.aget_session_context() as session:
            assert session == "test-session"

    @pytest.mark.asyncio
    async def test_aget_session_context_exception(self, backend):
        """Test aget_session_context propagates exceptions."""

        class ErrorBackend(ConcreteBackend):
            @contextmanager
            def get_session_context(self):
                yield "session"

        error_backend = ErrorBackend()
        with pytest.raises(ValueError, match="test error"):
            async with error_backend.aget_session_context():
                raise ValueError("test error")


class TestReadableBackendMixin:
    """Test ReadableBackendMixin default implementations."""

    def test_get_workflow(self):
        mixin = ReadableBackendMixin()
        assert mixin.get_workflow("wf-1") is None

    def test_list_workflows(self):
        mixin = ReadableBackendMixin()
        assert mixin.list_workflows() == []

    def test_get_stage(self):
        mixin = ReadableBackendMixin()
        assert mixin.get_stage("s-1") is None

    def test_get_agent(self):
        mixin = ReadableBackendMixin()
        assert mixin.get_agent("a-1") is None

    def test_get_llm_call(self):
        mixin = ReadableBackendMixin()
        assert mixin.get_llm_call("l-1") is None

    def test_get_tool_call(self):
        mixin = ReadableBackendMixin()
        assert mixin.get_tool_call("t-1") is None


class TestObservabilityBackendDefaults:
    """Test ObservabilityBackend default method implementations."""

    def test_record_error_fingerprint_default(self, backend):
        data = ErrorFingerprintData(
            fingerprint="abc",
            error_type="ValueError",
            error_code="E001",
            classification="input",
            normalized_message="test",
            sample_message="test",
        )
        result = backend.record_error_fingerprint(data)
        assert result is False

    def test_get_top_errors_default(self, backend):
        result = backend.get_top_errors()
        assert result == []


class TestDataclasses:
    """Test parameter bundle dataclasses."""

    def test_workflow_start_data(self):
        data = WorkflowStartData(
            trigger_type="api",
            environment="prod",
            tags=["tag1"],
            cost_attribution_tags={"team": "ml"},
        )
        assert data.trigger_type == "api"

    def test_agent_output_data(self):
        data = AgentOutputData(
            total_tokens=500,
            estimated_cost_usd=0.05,
            confidence_score=0.9,
        )
        assert data.total_tokens == 500

    def test_llm_call_data(self):
        data = LLMCallData(
            prompt="test",
            response="resp",
            prompt_tokens=10,
            completion_tokens=20,
            latency_ms=100,
            estimated_cost_usd=0.001,
            failover_from_provider="openai",
            failover_sequence=["openai", "anthropic"],
        )
        assert data.prompt_tokens == 10
        assert data.failover_from_provider == "openai"

    def test_tool_call_data(self):
        data = ToolCallData(
            input_params={"q": "test"},
            output_data={"r": "result"},
            duration_seconds=1.0,
            safety_checks=["check1"],
        )
        assert data.duration_seconds == 1.0

    def test_safety_violation_data(self):
        data = SafetyViolationData(
            workflow_id="wf-1",
            agent_id="a-1",
        )
        assert data.workflow_id == "wf-1"

    def test_collaboration_event_data(self):
        data = CollaborationEventData(
            round_number=1,
            resolution_strategy="vote",
            outcome="consensus",
        )
        assert data.round_number == 1

    def test_error_fingerprint_data(self):
        data = ErrorFingerprintData(
            fingerprint="abc",
            error_type="ValueError",
            error_code="E001",
            classification="input",
            normalized_message="test",
            sample_message="test",
            workflow_id="wf-1",
        )
        assert data.fingerprint == "abc"
        assert data.workflow_id == "wf-1"
