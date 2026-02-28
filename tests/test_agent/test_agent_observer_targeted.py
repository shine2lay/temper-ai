"""Targeted tests for agent/utils/agent_observer.py to improve coverage from 65% to 90%+.

Covers missing lines: 80-110 (emit_stream_chunk method).
"""

from unittest.mock import MagicMock, patch

from temper_ai.agent.utils.agent_observer import AgentObserver


class TestAgentObserverInit:
    def test_init_no_context(self):
        observer = AgentObserver(tracker=None, execution_context=None)
        assert observer._tracker is None
        assert observer._context is None
        assert observer._agent_id is None

    def test_init_with_context_and_agent_id(self):
        ctx = MagicMock()
        ctx.agent_id = "agent-123"
        observer = AgentObserver(tracker=MagicMock(), execution_context=ctx)
        assert observer._agent_id == "agent-123"

    def test_init_context_without_agent_id(self):
        ctx = MagicMock(spec=[])  # no agent_id attr
        observer = AgentObserver(tracker=MagicMock(), execution_context=ctx)
        assert observer._agent_id is None

    def test_active_true_when_tracker_and_agent_id(self):
        ctx = MagicMock()
        ctx.agent_id = "agent-123"
        observer = AgentObserver(tracker=MagicMock(), execution_context=ctx)
        assert observer.active is True

    def test_active_false_when_no_tracker(self):
        ctx = MagicMock()
        ctx.agent_id = "agent-123"
        observer = AgentObserver(tracker=None, execution_context=ctx)
        assert observer.active is False

    def test_active_false_when_no_agent_id(self):
        observer = AgentObserver(tracker=MagicMock(), execution_context=None)
        assert observer.active is False


class TestEmitStreamChunk:
    def test_no_tracker_returns_immediately(self):
        observer = AgentObserver(tracker=None, execution_context=None)
        # Should not raise
        observer.emit_stream_chunk(content="hello", chunk_type="content", done=False)

    def test_no_agent_id_returns_immediately(self):
        observer = AgentObserver(tracker=MagicMock(), execution_context=None)
        # Should not raise
        observer.emit_stream_chunk(content="hello")

    def test_no_event_bus_on_tracker_returns_silently(self):
        ctx = MagicMock()
        ctx.agent_id = "agent-1"
        tracker = MagicMock()
        # tracker has no _event_bus attribute
        del tracker._event_bus

        observer = AgentObserver(tracker=tracker, execution_context=ctx)
        # Should not raise
        observer.emit_stream_chunk(content="hello")

    def test_event_bus_none_returns_silently(self):
        ctx = MagicMock()
        ctx.agent_id = "agent-1"
        tracker = MagicMock()
        tracker._event_bus = None

        observer = AgentObserver(tracker=tracker, execution_context=ctx)
        # Should not raise
        observer.emit_stream_chunk(content="hello")

    def test_emit_stream_chunk_calls_emit_llm_stream_chunk(self):
        ctx = MagicMock()
        ctx.agent_id = "agent-1"
        ctx.workflow_id = "wf-1"
        ctx.stage_id = "stage-1"

        mock_bus = MagicMock()
        tracker = MagicMock()
        tracker._event_bus = mock_bus

        observer = AgentObserver(tracker=tracker, execution_context=ctx)

        mock_stream_chunk_data_cls = MagicMock()
        mock_emit_fn = MagicMock()

        with patch(
            "temper_ai.observability._tracker_helpers.StreamChunkData",
            mock_stream_chunk_data_cls,
        ):
            with patch(
                "temper_ai.observability._tracker_helpers.emit_llm_stream_chunk",
                mock_emit_fn,
            ):
                observer.emit_stream_chunk(
                    content="chunk text",
                    chunk_type="content",
                    done=False,
                    model="gpt-4",
                    prompt_tokens=10,
                    completion_tokens=5,
                )

        mock_emit_fn.assert_called_once()

    def test_emit_stream_chunk_exception_swallowed(self):
        ctx = MagicMock()
        ctx.agent_id = "agent-1"
        ctx.workflow_id = "wf-1"
        ctx.stage_id = None

        mock_bus = MagicMock()
        tracker = MagicMock()
        tracker._event_bus = mock_bus

        observer = AgentObserver(tracker=tracker, execution_context=ctx)

        with patch(
            "temper_ai.observability._tracker_helpers.StreamChunkData",
            side_effect=RuntimeError("data creation failed"),
        ):
            # Exception should be swallowed (best-effort)
            observer.emit_stream_chunk(content="text")

    def test_emit_chunk_with_none_optional_params(self):
        ctx = MagicMock()
        ctx.agent_id = "agent-1"
        ctx.workflow_id = None
        ctx.stage_id = None

        mock_bus = MagicMock()
        tracker = MagicMock()
        tracker._event_bus = mock_bus

        observer = AgentObserver(tracker=tracker, execution_context=ctx)

        mock_emit_fn = MagicMock()
        mock_data_cls = MagicMock()

        with patch(
            "temper_ai.observability._tracker_helpers.StreamChunkData",
            mock_data_cls,
        ):
            with patch(
                "temper_ai.observability._tracker_helpers.emit_llm_stream_chunk",
                mock_emit_fn,
            ):
                observer.emit_stream_chunk(
                    content="text",
                    model=None,
                    prompt_tokens=None,
                    completion_tokens=None,
                )

        mock_emit_fn.assert_called_once()

    def test_emit_done_chunk(self):
        ctx = MagicMock()
        ctx.agent_id = "agent-1"
        ctx.workflow_id = "wf-1"
        ctx.stage_id = "s1"

        mock_bus = MagicMock()
        tracker = MagicMock()
        tracker._event_bus = mock_bus

        observer = AgentObserver(tracker=tracker, execution_context=ctx)

        mock_emit_fn = MagicMock()
        mock_data_cls = MagicMock()

        with patch(
            "temper_ai.observability._tracker_helpers.StreamChunkData",
            mock_data_cls,
        ):
            with patch(
                "temper_ai.observability._tracker_helpers.emit_llm_stream_chunk",
                mock_emit_fn,
            ):
                observer.emit_stream_chunk(
                    content="",
                    chunk_type="done",
                    done=True,
                )

        mock_emit_fn.assert_called_once()


class TestTrackLLMCall:
    def test_no_op_when_inactive(self):
        observer = AgentObserver(tracker=None, execution_context=None)
        # Should not raise
        observer.track_llm_call(provider="ollama", model="llama2")

    def test_tracks_when_active(self):
        ctx = MagicMock()
        ctx.agent_id = "agent-1"
        tracker = MagicMock()
        observer = AgentObserver(tracker=tracker, execution_context=ctx)

        mock_data = MagicMock()
        with patch(
            "temper_ai.observability._tracker_helpers.LLMCallTrackingData",
            return_value=mock_data,
        ):
            observer.track_llm_call(provider="ollama", model="llama2", tokens=100)

        tracker.track_llm_call.assert_called_once_with(mock_data)

    def test_attribute_error_logged_not_raised(self):
        ctx = MagicMock()
        ctx.agent_id = "agent-1"
        tracker = MagicMock()
        observer = AgentObserver(tracker=tracker, execution_context=ctx)

        with patch(
            "temper_ai.observability._tracker_helpers.LLMCallTrackingData",
            side_effect=AttributeError("bad attr"),
        ):
            # Should not raise
            observer.track_llm_call(provider="test")


class TestTrackToolCall:
    def test_no_op_when_inactive(self):
        observer = AgentObserver(tracker=None, execution_context=None)
        observer.track_tool_call(tool_name="bash", duration_ms=100)

    def test_tracks_when_active(self):
        ctx = MagicMock()
        ctx.agent_id = "agent-1"
        tracker = MagicMock()
        observer = AgentObserver(tracker=tracker, execution_context=ctx)

        mock_data = MagicMock()
        with patch(
            "temper_ai.observability._tracker_helpers.ToolCallTrackingData",
            return_value=mock_data,
        ):
            observer.track_tool_call(tool_name="bash", duration_ms=50)

        tracker.track_tool_call.assert_called_once_with(mock_data)

    def test_type_error_logged_not_raised(self):
        ctx = MagicMock()
        ctx.agent_id = "agent-1"
        tracker = MagicMock()
        observer = AgentObserver(tracker=tracker, execution_context=ctx)

        with patch(
            "temper_ai.observability._tracker_helpers.ToolCallTrackingData",
            side_effect=TypeError("bad type"),
        ):
            # Should not raise
            observer.track_tool_call(tool_name="test")
