"""Tests for CompositeBackend to cover uncovered lines."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

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
)
from temper_ai.observability.backends.composite_backend import (
    CompositeBackend,
)


def _make_mock_backend(readable: bool = False) -> MagicMock:
    """Create a mock ObservabilityBackend."""
    if readable:
        mock = MagicMock(
            spec=list(set(dir(ObservabilityBackend) + dir(ReadableBackendMixin)))
        )
    else:
        mock = MagicMock(spec=ObservabilityBackend)

    # Set up async mocks
    mock.atrack_workflow_start = AsyncMock()
    mock.atrack_workflow_end = AsyncMock()
    mock.aupdate_workflow_metrics = AsyncMock()
    mock.atrack_stage_start = AsyncMock()
    mock.atrack_stage_end = AsyncMock()
    mock.aset_stage_output = AsyncMock()
    mock.atrack_agent_start = AsyncMock()
    mock.atrack_agent_end = AsyncMock()
    mock.aset_agent_output = AsyncMock()
    mock.atrack_llm_call = AsyncMock()
    mock.atrack_tool_call = AsyncMock()
    mock.atrack_safety_violation = AsyncMock()
    mock.atrack_collaboration_event = AsyncMock(return_value="evt-1")
    mock.aget_session_context = AsyncMock()

    return mock


@pytest.fixture
def composite():
    """Create a CompositeBackend with mock primary and secondary."""
    primary = _make_mock_backend(readable=True)
    secondary = _make_mock_backend()
    backend = CompositeBackend(primary, [secondary])
    return backend, primary, secondary


class TestCompositeInit:
    """Test CompositeBackend initialization."""

    def test_init_with_secondaries(self):
        primary = _make_mock_backend()
        secondary = _make_mock_backend()
        backend = CompositeBackend(primary, [secondary])
        assert backend._primary is primary
        assert len(backend._secondaries) == 1

    def test_init_without_secondaries(self):
        primary = _make_mock_backend()
        backend = CompositeBackend(primary)
        assert backend._primary is primary
        assert len(backend._secondaries) == 0


class TestFanOut:
    """Test sync fan out method."""

    def test_fan_out_success(self, composite):
        backend, primary, secondary = composite
        backend._fan_out("track_workflow_start", "wf-1", "name", {}, datetime.now(UTC))
        secondary.track_workflow_start.assert_called_once()

    def test_fan_out_secondary_error(self, composite):
        backend, primary, secondary = composite
        secondary.track_workflow_start.side_effect = RuntimeError("secondary failed")
        # Should not raise
        backend._fan_out("track_workflow_start", "wf-1", "name", {}, datetime.now(UTC))

    def test_fan_out_no_secondaries(self):
        primary = _make_mock_backend()
        backend = CompositeBackend(primary)
        backend._fan_out("track_workflow_start", "wf-1", "name", {}, datetime.now(UTC))


class TestAsyncFanOut:
    """Test async fan out method."""

    @pytest.mark.asyncio
    async def test_afan_out_success(self, composite):
        backend, primary, secondary = composite
        await backend._afan_out(
            "atrack_workflow_start", "wf-1", "name", {}, datetime.now(UTC)
        )
        secondary.atrack_workflow_start.assert_called_once()

    @pytest.mark.asyncio
    async def test_afan_out_secondary_error(self, composite):
        backend, primary, secondary = composite
        secondary.atrack_workflow_start = AsyncMock(
            side_effect=RuntimeError("secondary failed")
        )
        # Should not raise
        await backend._afan_out(
            "atrack_workflow_start", "wf-1", "name", {}, datetime.now(UTC)
        )

    @pytest.mark.asyncio
    async def test_afan_out_no_secondaries(self):
        primary = _make_mock_backend()
        backend = CompositeBackend(primary)
        await backend._afan_out(
            "atrack_workflow_start", "wf-1", "name", {}, datetime.now(UTC)
        )


class TestWorkflowTracking:
    """Test workflow tracking delegation."""

    def test_track_workflow_start(self, composite):
        backend, primary, secondary = composite
        now = datetime.now(UTC)
        backend.track_workflow_start("wf-1", "workflow", {}, now)
        primary.track_workflow_start.assert_called_once()

    def test_track_workflow_start_with_kwargs(self, composite):
        backend, primary, secondary = composite
        now = datetime.now(UTC)
        backend.track_workflow_start(
            "wf-1", "workflow", {}, now, environment="dev", trigger_type="api"
        )
        primary.track_workflow_start.assert_called_once()

    def test_track_workflow_end(self, composite):
        backend, primary, secondary = composite
        now = datetime.now(UTC)
        backend.track_workflow_end("wf-1", now, "completed", "error", "trace")
        primary.track_workflow_end.assert_called_once()

    def test_update_workflow_metrics(self, composite):
        backend, primary, secondary = composite
        backend.update_workflow_metrics("wf-1", 10, 5, 1000, 0.50)
        primary.update_workflow_metrics.assert_called_once()

    @pytest.mark.asyncio
    async def test_atrack_workflow_start(self, composite):
        backend, primary, secondary = composite
        now = datetime.now(UTC)
        await backend.atrack_workflow_start("wf-1", "workflow", {}, now)
        primary.atrack_workflow_start.assert_called_once()

    @pytest.mark.asyncio
    async def test_atrack_workflow_end(self, composite):
        backend, primary, secondary = composite
        now = datetime.now(UTC)
        await backend.atrack_workflow_end("wf-1", now, "completed")
        primary.atrack_workflow_end.assert_called_once()

    @pytest.mark.asyncio
    async def test_aupdate_workflow_metrics(self, composite):
        backend, primary, secondary = composite
        await backend.aupdate_workflow_metrics("wf-1", 10, 5, 1000, 0.50)
        primary.aupdate_workflow_metrics.assert_called_once()


class TestStageTracking:
    """Test stage tracking delegation."""

    def test_track_stage_start(self, composite):
        backend, primary, secondary = composite
        now = datetime.now(UTC)
        backend.track_stage_start("s-1", "wf-1", "stage", {}, now)
        primary.track_stage_start.assert_called_once()

    def test_track_stage_end(self, composite):
        backend, primary, secondary = composite
        now = datetime.now(UTC)
        backend.track_stage_end("s-1", now, "completed", None, 3, 2, 1)
        primary.track_stage_end.assert_called_once()

    def test_set_stage_output(self, composite):
        backend, primary, secondary = composite
        backend.set_stage_output("s-1", {"data": "output"}, {"lineage": "info"})
        primary.set_stage_output.assert_called_once()

    @pytest.mark.asyncio
    async def test_atrack_stage_start(self, composite):
        backend, primary, secondary = composite
        now = datetime.now(UTC)
        await backend.atrack_stage_start("s-1", "wf-1", "stage", {}, now)
        primary.atrack_stage_start.assert_called_once()

    @pytest.mark.asyncio
    async def test_atrack_stage_end(self, composite):
        backend, primary, secondary = composite
        now = datetime.now(UTC)
        await backend.atrack_stage_end("s-1", now, "completed")
        primary.atrack_stage_end.assert_called_once()

    @pytest.mark.asyncio
    async def test_aset_stage_output(self, composite):
        backend, primary, secondary = composite
        await backend.aset_stage_output("s-1", {"data": "output"})
        primary.aset_stage_output.assert_called_once()


class TestAgentTracking:
    """Test agent tracking delegation."""

    def test_track_agent_start(self, composite):
        backend, primary, secondary = composite
        now = datetime.now(UTC)
        backend.track_agent_start("a-1", "s-1", "agent", {}, now)
        primary.track_agent_start.assert_called_once()

    def test_track_agent_end(self, composite):
        backend, primary, secondary = composite
        now = datetime.now(UTC)
        backend.track_agent_end("a-1", now, "completed", "error")
        primary.track_agent_end.assert_called_once()

    def test_set_agent_output(self, composite):
        backend, primary, secondary = composite
        metrics = AgentOutputData(total_tokens=500)
        backend.set_agent_output("a-1", {"data": "output"}, metrics)
        primary.set_agent_output.assert_called_once()

    @pytest.mark.asyncio
    async def test_atrack_agent_start(self, composite):
        backend, primary, secondary = composite
        now = datetime.now(UTC)
        await backend.atrack_agent_start("a-1", "s-1", "agent", {}, now)
        primary.atrack_agent_start.assert_called_once()

    @pytest.mark.asyncio
    async def test_atrack_agent_end(self, composite):
        backend, primary, secondary = composite
        now = datetime.now(UTC)
        await backend.atrack_agent_end("a-1", now, "completed")
        primary.atrack_agent_end.assert_called_once()

    @pytest.mark.asyncio
    async def test_aset_agent_output(self, composite):
        backend, primary, secondary = composite
        await backend.aset_agent_output("a-1", {"data": "output"})
        primary.aset_agent_output.assert_called_once()


class TestLLMToolTracking:
    """Test LLM and tool call tracking delegation."""

    def test_track_llm_call(self, composite):
        backend, primary, secondary = composite
        now = datetime.now(UTC)
        data = LLMCallData(
            prompt="test",
            response="resp",
            prompt_tokens=10,
            completion_tokens=20,
            latency_ms=100,
            estimated_cost_usd=0.001,
        )
        backend.track_llm_call("l-1", "a-1", "openai", "gpt-4", now, data)
        primary.track_llm_call.assert_called_once()

    def test_track_llm_call_from_kwargs(self, composite):
        backend, primary, secondary = composite
        now = datetime.now(UTC)
        backend.track_llm_call(
            "l-1",
            "a-1",
            "openai",
            "gpt-4",
            now,
            data=None,
            prompt="test",
            response="resp",
            prompt_tokens=10,
            completion_tokens=20,
            latency_ms=100,
            estimated_cost_usd=0.001,
        )
        primary.track_llm_call.assert_called_once()

    def test_track_tool_call(self, composite):
        backend, primary, secondary = composite
        now = datetime.now(UTC)
        data = ToolCallData(
            input_params={},
            output_data={},
            duration_seconds=1.0,
        )
        backend.track_tool_call("t-1", "a-1", "search", now, data)
        primary.track_tool_call.assert_called_once()

    def test_track_tool_call_from_kwargs(self, composite):
        backend, primary, secondary = composite
        now = datetime.now(UTC)
        backend.track_tool_call(
            "t-1",
            "a-1",
            "search",
            now,
            data=None,
            input_params={"q": "test"},
            output_data={"r": "result"},
            duration_seconds=1.0,
        )
        primary.track_tool_call.assert_called_once()

    @pytest.mark.asyncio
    async def test_atrack_llm_call(self, composite):
        backend, primary, secondary = composite
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
        primary.atrack_llm_call.assert_called_once()

    @pytest.mark.asyncio
    async def test_atrack_tool_call(self, composite):
        backend, primary, secondary = composite
        now = datetime.now(UTC)
        data = ToolCallData(
            input_params={},
            output_data={},
            duration_seconds=1.0,
        )
        await backend.atrack_tool_call("t-1", "a-1", "search", now, data)
        primary.atrack_tool_call.assert_called_once()


class TestSafetyAndCollaboration:
    """Test safety and collaboration tracking delegation."""

    def test_track_safety_violation(self, composite):
        backend, primary, secondary = composite
        data = SafetyViolationData(agent_id="a-1")
        backend.track_safety_violation("HIGH", "violation", "policy", data)
        primary.track_safety_violation.assert_called_once()

    def test_track_collaboration_event(self, composite):
        backend, primary, secondary = composite
        primary.track_collaboration_event.return_value = "evt-1"
        data = CollaborationEventData(round_number=1)
        result = backend.track_collaboration_event("s-1", "vote", ["a-1"], data)
        assert result == "evt-1"
        primary.track_collaboration_event.assert_called_once()

    @pytest.mark.asyncio
    async def test_atrack_safety_violation(self, composite):
        backend, primary, secondary = composite
        await backend.atrack_safety_violation("HIGH", "msg", "policy")
        primary.atrack_safety_violation.assert_called_once()

    @pytest.mark.asyncio
    async def test_atrack_collaboration_event(self, composite):
        backend, primary, secondary = composite
        await backend.atrack_collaboration_event("s-1", "vote", ["a-1"])
        primary.atrack_collaboration_event.assert_called_once()


class TestErrorFingerprinting:
    """Test error fingerprinting delegation."""

    def test_record_error_fingerprint(self, composite):
        backend, primary, secondary = composite
        primary.record_error_fingerprint.return_value = True
        data = ErrorFingerprintData(
            fingerprint="abc123",
            error_type="ValueError",
            error_code="E001",
            classification="input_error",
            normalized_message="test error",
            sample_message="test error msg",
        )
        result = backend.record_error_fingerprint(data)
        assert result is True
        primary.record_error_fingerprint.assert_called_once()


class TestReadMixin:
    """Test _CompositeReadMixin methods."""

    def test_get_workflow_readable(self, composite):
        backend, primary, secondary = composite
        # Make primary look like it supports reads
        primary.get_workflow = MagicMock(return_value={"id": "wf-1"})
        # Patch isinstance check
        with patch(
            "temper_ai.observability.backends.composite_backend.isinstance",
            side_effect=lambda obj, cls: True,
        ):
            backend.get_workflow("wf-1")

    def test_list_workflows_readable(self, composite):
        backend, primary, secondary = composite
        primary.list_workflows = MagicMock(return_value=[{"id": "wf-1"}])
        with patch(
            "temper_ai.observability.backends.composite_backend.isinstance",
            side_effect=lambda obj, cls: True,
        ):
            backend.list_workflows(limit=10, offset=0)

    def test_get_top_errors(self, composite):
        backend, primary, secondary = composite
        primary.get_top_errors.return_value = [{"error": "test"}]
        backend.get_top_errors(limit=5)
        primary.get_top_errors.assert_called_once()

    def test_getattr_delegation(self, composite):
        backend, primary, secondary = composite
        primary.aggregate_workflow_metrics = MagicMock(return_value={"key": "value"})
        backend.aggregate_workflow_metrics()
        primary.aggregate_workflow_metrics.assert_called_once()


class TestContextAndMaintenance:
    """Test context management and maintenance methods."""

    def test_get_session_context(self, composite):
        backend, primary, secondary = composite
        mock_cm = MagicMock()
        primary.get_session_context.return_value = mock_cm
        result = backend.get_session_context()
        assert result is mock_cm

    def test_cleanup_old_records(self, composite):
        backend, primary, secondary = composite
        primary.cleanup_old_records.return_value = {"workflows": 10}
        result = backend.cleanup_old_records(30)
        assert result == {"workflows": 10}

    def test_get_stats(self, composite):
        backend, primary, secondary = composite
        primary.get_stats.return_value = {"backend_type": "sql"}
        result = backend.get_stats()
        assert result["composite"] is True
        assert result["num_secondaries"] == 1

    @pytest.mark.asyncio
    async def test_aget_session_context(self, composite):
        backend, primary, secondary = composite
        mock_session = MagicMock()

        async def mock_context():
            yield mock_session

        # Create proper async context manager
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def mock_aget():
            yield mock_session

        primary.aget_session_context = mock_aget
        async with backend.aget_session_context() as session:
            assert session is mock_session
