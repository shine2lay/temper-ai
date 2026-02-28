"""Tests for noop_backend.py to cover all uncovered lines."""

from datetime import UTC, datetime

import pytest

from temper_ai.observability.backend import (
    ErrorFingerprintData,
    LLMCallData,
    ToolCallData,
)
from temper_ai.observability.backends.noop_backend import NoOpBackend


@pytest.fixture
def noop():
    return NoOpBackend()


class TestNoOpSyncMethods:
    """Test all sync no-op methods return correctly."""

    def test_track_workflow_start(self, noop):
        now = datetime.now(UTC)
        noop.track_workflow_start("wf-1", "workflow", {}, now)

    def test_track_workflow_end(self, noop):
        now = datetime.now(UTC)
        noop.track_workflow_end("wf-1", now, "completed")

    def test_update_workflow_metrics(self, noop):
        noop.update_workflow_metrics("wf-1", 10, 5, 1000, 0.50)

    def test_track_stage_start(self, noop):
        now = datetime.now(UTC)
        noop.track_stage_start("s-1", "wf-1", "stage", {}, now)

    def test_track_stage_end(self, noop):
        now = datetime.now(UTC)
        noop.track_stage_end("s-1", now, "completed")

    def test_set_stage_output(self, noop):
        noop.set_stage_output("s-1", {"data": "output"})

    def test_track_agent_start(self, noop):
        now = datetime.now(UTC)
        noop.track_agent_start("a-1", "s-1", "agent", {}, now)

    def test_track_agent_end(self, noop):
        now = datetime.now(UTC)
        noop.track_agent_end("a-1", now, "completed")

    def test_set_agent_output(self, noop):
        noop.set_agent_output("a-1", {"data": "output"})

    def test_track_llm_call(self, noop):
        now = datetime.now(UTC)
        noop.track_llm_call("l-1", "a-1", "openai", "gpt-4", now)

    def test_track_tool_call(self, noop):
        now = datetime.now(UTC)
        noop.track_tool_call("t-1", "a-1", "search", now)

    def test_track_safety_violation(self, noop):
        noop.track_safety_violation("HIGH", "violation", "policy")

    def test_track_collaboration_event(self, noop):
        result = noop.track_collaboration_event("s-1", "vote", ["a-1"])
        assert result == ""

    def test_record_error_fingerprint(self, noop):
        data = ErrorFingerprintData(
            fingerprint="abc",
            error_type="ValueError",
            error_code="E001",
            classification="input",
            normalized_message="test",
            sample_message="test",
        )
        result = noop.record_error_fingerprint(data)
        assert result is False

    def test_get_top_errors(self, noop):
        result = noop.get_top_errors()
        assert result == []

    def test_get_session_context(self, noop):
        with noop.get_session_context() as session:
            assert session is None

    def test_cleanup_old_records(self, noop):
        result = noop.cleanup_old_records(30)
        assert result == {}

    def test_get_stats(self, noop):
        result = noop.get_stats()
        assert result == {"backend_type": "noop"}


class TestNoOpAsyncMethods:
    """Test all async no-op methods."""

    @pytest.mark.asyncio
    async def test_atrack_workflow_start(self, noop):
        now = datetime.now(UTC)
        await noop.atrack_workflow_start("wf-1", "workflow", {}, now)

    @pytest.mark.asyncio
    async def test_atrack_workflow_end(self, noop):
        now = datetime.now(UTC)
        await noop.atrack_workflow_end("wf-1", now, "completed")

    @pytest.mark.asyncio
    async def test_aupdate_workflow_metrics(self, noop):
        await noop.aupdate_workflow_metrics("wf-1", 10, 5, 1000, 0.50)

    @pytest.mark.asyncio
    async def test_atrack_stage_start(self, noop):
        now = datetime.now(UTC)
        await noop.atrack_stage_start("s-1", "wf-1", "stage", {}, now)

    @pytest.mark.asyncio
    async def test_atrack_stage_end(self, noop):
        now = datetime.now(UTC)
        await noop.atrack_stage_end("s-1", now, "completed")

    @pytest.mark.asyncio
    async def test_aset_stage_output(self, noop):
        await noop.aset_stage_output("s-1", {"data": "output"})

    @pytest.mark.asyncio
    async def test_atrack_agent_start(self, noop):
        now = datetime.now(UTC)
        await noop.atrack_agent_start("a-1", "s-1", "agent", {}, now)

    @pytest.mark.asyncio
    async def test_atrack_agent_end(self, noop):
        now = datetime.now(UTC)
        await noop.atrack_agent_end("a-1", now, "completed")

    @pytest.mark.asyncio
    async def test_aset_agent_output(self, noop):
        await noop.aset_agent_output("a-1", {"data": "output"})

    @pytest.mark.asyncio
    async def test_atrack_llm_call(self, noop):
        now = datetime.now(UTC)
        data = LLMCallData(
            prompt="test",
            response="resp",
            prompt_tokens=10,
            completion_tokens=20,
            latency_ms=100,
            estimated_cost_usd=0.001,
        )
        await noop.atrack_llm_call("l-1", "a-1", "openai", "gpt-4", now, data)

    @pytest.mark.asyncio
    async def test_atrack_tool_call(self, noop):
        now = datetime.now(UTC)
        data = ToolCallData(
            input_params={},
            output_data={},
            duration_seconds=1.0,
        )
        await noop.atrack_tool_call("t-1", "a-1", "search", now, data)

    @pytest.mark.asyncio
    async def test_atrack_safety_violation(self, noop):
        await noop.atrack_safety_violation("HIGH", "msg", "policy")

    @pytest.mark.asyncio
    async def test_atrack_collaboration_event(self, noop):
        result = await noop.atrack_collaboration_event("s-1", "vote", ["a-1"])
        assert result == ""

    @pytest.mark.asyncio
    async def test_aget_session_context(self, noop):
        async with noop.aget_session_context() as session:
            assert session is None
