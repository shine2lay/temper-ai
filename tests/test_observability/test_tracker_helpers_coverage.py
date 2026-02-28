"""Tests for _tracker_helpers.py to cover uncovered lines."""

from unittest.mock import MagicMock

from temper_ai.observability._tracker_helpers import (
    CollaborationEventData,
    DecisionTrackingData,
    StreamChunkData,
    _fill_execution_ids,
    build_extra_metadata,
    emit_llm_stream_chunk,
    handle_agent_error,
    handle_agent_success,
    handle_stage_error,
    sanitize_dict,
    track_decision_outcome,
    update_agent_merit_score,
)


class TestSanitizeDict:
    """Test sanitize_dict edge cases."""

    def test_non_dict_input(self):
        """Test that non-dict input returns empty dict (line 165)."""
        sanitizer = MagicMock()
        # Force non-dict through type ignore path
        result = sanitize_dict(sanitizer, "not a dict")  # type: ignore[arg-type]
        assert result == {}

    def test_max_depth_exceeded(self):
        """Test truncation at max depth (line 169)."""
        sanitizer = MagicMock()
        result = sanitize_dict(sanitizer, {"key": "value"}, _depth=1000)
        assert "__truncated__" in result
        assert result["__truncated__"] == "max depth exceeded"

    def test_nested_dict_recursion(self):
        """Test recursive dict sanitization (line 180)."""
        sanitizer = MagicMock()
        mock_result = MagicMock()
        mock_result.sanitized_text = "safe_value"
        mock_result.was_sanitized = False
        sanitizer.sanitize_text.return_value = mock_result

        data = {"outer": {"inner": "secret"}}
        result = sanitize_dict(sanitizer, data)
        assert "safe_value" in result

    def test_list_with_dicts(self):
        """Test list containing dicts is recursively sanitized."""
        sanitizer = MagicMock()
        mock_result = MagicMock()
        mock_result.sanitized_text = "safe"
        sanitizer.sanitize_text.return_value = mock_result

        data = {"items": [{"nested": "value"}, "plain"]}
        result = sanitize_dict(sanitizer, data)
        assert "safe" in result

    def test_non_serializable_object(self):
        """Test non-serializable value produces warning (lines 206-210)."""
        sanitizer = MagicMock()
        mock_result = MagicMock()
        mock_result.sanitized_text = "key"
        sanitizer.sanitize_text.return_value = mock_result

        class CustomObj:
            pass

        data = {"weird": CustomObj()}
        result = sanitize_dict(sanitizer, data)
        assert "[SANITIZED:CustomObj]" in str(result.values())

    def test_sanitization_exception(self):
        """Test exception during sanitization (lines 211-217)."""
        sanitizer = MagicMock()
        sanitizer.sanitize_text.side_effect = RuntimeError("boom")

        data = {"key": "value"}
        result = sanitize_dict(sanitizer, data)
        assert "[SANITIZATION_ERROR]" in str(result.values())

    def test_none_and_primitive_values(self):
        """Test None, bool, int, float pass through unsanitized (lines 200-202)."""
        sanitizer = MagicMock()
        # Return different keys for each call to avoid overwriting
        call_count = [0]
        keys = ["a", "b", "c", "d"]

        def make_result(text, context=None):
            m = MagicMock()
            if text in keys:
                m.sanitized_text = text
            else:
                m.sanitized_text = f"sanitized_{call_count[0]}"
            call_count[0] += 1
            return m

        sanitizer.sanitize_text.side_effect = make_result

        data = {"a": None, "b": True, "c": 42, "d": 3.14}
        result = sanitize_dict(sanitizer, data)
        assert result.get("a") is None
        assert result.get("b") is True
        assert result.get("c") == 42
        assert result.get("d") == 3.14


class TestFillExecutionIds:
    """Test _fill_execution_ids (lines 553-559)."""

    def test_fill_all_missing_ids(self):
        data = DecisionTrackingData(
            decision_type="test",
            decision_data={},
            outcome="success",
        )
        context = MagicMock()
        context.workflow_id = "wf-1"
        context.stage_id = "s-1"
        context.agent_id = "a-1"

        result = _fill_execution_ids(data, context)
        assert result.workflow_execution_id == "wf-1"
        assert result.stage_execution_id == "s-1"
        assert result.agent_execution_id == "a-1"

    def test_preserves_existing_ids(self):
        data = DecisionTrackingData(
            decision_type="test",
            decision_data={},
            outcome="success",
            workflow_execution_id="existing-wf",
            stage_execution_id="existing-s",
            agent_execution_id="existing-a",
        )
        context = MagicMock()
        context.workflow_id = "new-wf"
        context.stage_id = "new-s"
        context.agent_id = "new-a"

        result = _fill_execution_ids(data, context)
        assert result.workflow_execution_id == "existing-wf"
        assert result.stage_execution_id == "existing-s"
        assert result.agent_execution_id == "existing-a"


class TestTrackDecisionOutcome:
    """Test track_decision_outcome (lines 581-610)."""

    def test_with_session_stack(self):
        """Test tracking with existing session stack."""
        tracker = MagicMock()
        tracker.track.return_value = "decision-1"
        backend = MagicMock()
        context = MagicMock()
        context.workflow_id = "wf-1"
        context.stage_id = "s-1"
        context.agent_id = "a-1"
        session = MagicMock()

        data = DecisionTrackingData(
            decision_type="test",
            decision_data={"key": "value"},
            outcome="success",
        )

        result = track_decision_outcome(tracker, backend, context, [session], data)
        assert result == "decision-1"
        tracker.track.assert_called_once()

    def test_without_session_stack(self):
        """Test tracking creates new session from backend."""
        tracker = MagicMock()
        tracker.track.return_value = "decision-2"
        backend = MagicMock()
        mock_session = MagicMock()
        backend.get_session_context.return_value.__enter__ = MagicMock(
            return_value=mock_session
        )
        backend.get_session_context.return_value.__exit__ = MagicMock(
            return_value=False
        )
        context = MagicMock()
        context.workflow_id = "wf-1"
        context.stage_id = "s-1"
        context.agent_id = "a-1"

        data = DecisionTrackingData(
            decision_type="test",
            decision_data={},
            outcome="failure",
        )

        result = track_decision_outcome(tracker, backend, context, [], data)
        assert result == "decision-2"


class TestUpdateAgentMeritScore:
    """Test update_agent_merit_score (lines 633-654)."""

    def test_with_session_stack(self):
        tracker = MagicMock()
        backend = MagicMock()
        session = MagicMock()

        update_agent_merit_score(
            tracker, backend, [session], "agent-1", "analysis", "success", 0.9
        )

        tracker._merit_service.update.assert_called_once_with(
            session=session,
            agent_name="agent-1",
            domain="analysis",
            decision_outcome="success",
            confidence=0.9,
        )
        session.commit.assert_called_once()

    def test_without_session_stack(self):
        tracker = MagicMock()
        backend = MagicMock()
        mock_session = MagicMock()
        backend.get_session_context.return_value.__enter__ = MagicMock(
            return_value=mock_session
        )
        backend.get_session_context.return_value.__exit__ = MagicMock(
            return_value=False
        )

        update_agent_merit_score(tracker, backend, [], "agent-1", "analysis", "failure")

        tracker._merit_service.update.assert_called_once()
        mock_session.commit.assert_called_once()

    def test_exception_is_logged(self):
        tracker = MagicMock()
        tracker._merit_service.update.side_effect = RuntimeError("db error")
        backend = MagicMock()
        session = MagicMock()

        # Should not raise
        update_agent_merit_score(
            tracker, backend, [session], "agent-1", "analysis", "success"
        )


class TestBuildExtraMetadata:
    """Test build_extra_metadata (lines 714-722)."""

    def test_all_fields_set(self):
        result = build_extra_metadata(
            experiment_id="exp-1",
            variant_id="var-1",
            assignment_strategy="random",
            assignment_context={"user": "test"},
            custom_metrics={"accuracy": 0.95},
        )
        assert result is not None
        assert result["experiment_id"] == "exp-1"
        assert result["variant_id"] == "var-1"
        assert result["assignment_strategy"] == "random"
        assert result["assignment_context"] == {"user": "test"}
        assert result["custom_metrics"] == {"accuracy": 0.95}

    def test_no_fields_returns_none(self):
        result = build_extra_metadata(None, None, None, None, None)
        assert result is None

    def test_partial_fields(self):
        result = build_extra_metadata("exp-1", None, None, None, None)
        assert result is not None
        assert result["experiment_id"] == "exp-1"
        assert "variant_id" not in result


class TestEmitLlmStreamChunk:
    """Test emit_llm_stream_chunk (lines 1096-1120)."""

    def test_emit_with_event_bus(self):
        event_bus = MagicMock()
        data = StreamChunkData(
            agent_id="a-1",
            content="Hello",
            chunk_type="content",
            done=False,
            model="gpt-4",
            prompt_tokens=10,
            completion_tokens=5,
            workflow_id="wf-1",
            stage_id="s-1",
        )
        emit_llm_stream_chunk(event_bus, data)
        event_bus.emit.assert_called_once()

    def test_emit_with_none_event_bus(self):
        """Test early return when event_bus is None (line 1096-1097)."""
        data = StreamChunkData(agent_id="a-1", content="Hello")
        # Should not raise
        emit_llm_stream_chunk(None, data)

    def test_emit_exception_swallowed(self):
        """Test exception from event_bus.emit is swallowed (line 1119-1120)."""
        event_bus = MagicMock()
        event_bus.emit.side_effect = RuntimeError("bus error")
        data = StreamChunkData(agent_id="a-1", content="Hello")
        # Should not raise
        emit_llm_stream_chunk(event_bus, data)


class TestHandleAgentSuccess:
    """Test handle_agent_success (lines 1027-1036)."""

    def test_handle_success(self):
        backend = MagicMock()
        emit_fn = MagicMock()
        collect_fn = MagicMock()
        handle_agent_success(backend, emit_fn, collect_fn, "agent-1")
        backend.track_agent_end.assert_called_once()
        emit_fn.assert_called_once()
        collect_fn.assert_called_once_with("agent-1")


class TestHandleAgentError:
    """Test handle_agent_error (lines 1050-1079)."""

    def test_handle_error_with_alert(self):
        backend = MagicMock()
        backend.record_error_fingerprint.return_value = True
        emit_fn = MagicMock()
        alert_manager = MagicMock()

        handle_agent_error(
            backend,
            emit_fn,
            "agent-1",
            ValueError("test"),
            workflow_id="wf-1",
            agent_name="researcher",
            alert_manager=alert_manager,
        )
        backend.track_agent_end.assert_called_once()
        emit_fn.assert_called_once()

    def test_handle_error_no_alert(self):
        backend = MagicMock()
        backend.record_error_fingerprint.return_value = False
        emit_fn = MagicMock()

        handle_agent_error(backend, emit_fn, "agent-1", RuntimeError("fail"))
        backend.track_agent_end.assert_called_once()


class TestHandleStageError:
    """Test handle_stage_error."""

    def test_handle_stage_error_with_alert(self):
        backend = MagicMock()
        backend.record_error_fingerprint.return_value = True
        emit_fn = MagicMock()
        alert_manager = MagicMock()

        handle_stage_error(
            backend,
            emit_fn,
            "stage-1",
            ValueError("test"),
            workflow_id="wf-1",
            alert_manager=alert_manager,
        )
        backend.track_stage_end.assert_called_once()
        emit_fn.assert_called_once()


class TestTrackerCollaborationMixin:
    """Test TrackerCollaborationMixin.update_agent_merit_score (line 1215)."""

    def test_mixin_update_merit_score(self):
        from temper_ai.observability._tracker_helpers import TrackerCollaborationMixin

        mixin = TrackerCollaborationMixin.__new__(TrackerCollaborationMixin)
        mixin._decision_tracker = MagicMock()
        mixin._decision_tracker._merit_service = MagicMock()
        mixin.backend = MagicMock()
        mock_session = MagicMock()
        mixin.backend.get_session_context.return_value.__enter__ = MagicMock(
            return_value=mock_session
        )
        mixin.backend.get_session_context.return_value.__exit__ = MagicMock(
            return_value=False
        )

        mixin.update_agent_merit_score("agent-1", "analysis", "success", 0.9)
        mixin._decision_tracker._merit_service.update.assert_called_once()

    def test_mixin_session_stack_property(self):
        from temper_ai.observability._tracker_helpers import TrackerCollaborationMixin

        mixin = TrackerCollaborationMixin.__new__(TrackerCollaborationMixin)
        assert mixin._session_stack == []


class TestDataclasses:
    """Test dataclass constructors for full coverage."""

    def test_stream_chunk_data(self):
        data = StreamChunkData(
            agent_id="a-1",
            content="test",
            chunk_type="content",
            done=True,
            model="gpt-4",
            prompt_tokens=10,
            completion_tokens=5,
            workflow_id="wf-1",
            stage_id="s-1",
        )
        assert data.agent_id == "a-1"
        assert data.done is True

    def test_collaboration_event_data(self):
        data = CollaborationEventData(
            event_type="vote",
            stage_id="s-1",
            agents_involved=["a-1", "a-2"],
            round_number=1,
            resolution_strategy="majority",
            outcome="consensus",
            confidence_score=0.95,
        )
        assert data.event_type == "vote"
        assert data.round_number == 1
