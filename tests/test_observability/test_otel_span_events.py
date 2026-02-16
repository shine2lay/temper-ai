"""Tests for OTEL span events (log entries on spans).

Verifies that the OTelBackend emits span events at key lifecycle points
so that tools like Jaeger display meaningful log entries per span.
"""
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from src.observability.backend import (
    AgentOutputData,
    CollaborationEventData,
    SafetyViolationData,
    WorkflowStartData,
)


@pytest.fixture
def otel_backend():
    """Create OTelBackend with mocked OTEL SDK."""
    mock_tracer = MagicMock()
    mock_span = MagicMock()
    mock_tracer.start_span.return_value = mock_span

    with patch("src.observability.backends.otel_backend.otel_trace") as mock_trace:
        mock_trace.set_span_in_context.return_value = MagicMock()
        from src.observability.backends.otel_backend import OTelBackend

        backend = OTelBackend.__new__(OTelBackend)
        backend._tracer = mock_tracer
        backend._active_spans = {}

        # Create mock metrics
        for attr in [
            "_workflow_counter", "_llm_call_counter", "_tool_call_counter",
            "_llm_latency_histogram", "_cost_counter", "_tokens_counter",
            "_llm_iteration_counter", "_cache_hit_counter", "_cache_miss_counter",
            "_retry_counter", "_cb_state_change_counter",
            "_dialogue_convergence_histogram", "_stage_cost_counter",
            "_failover_counter",
        ]:
            setattr(backend, attr, MagicMock())

        yield backend, mock_span


NOW = datetime.now(timezone.utc)


class TestWorkflowSpanEvents:
    """Workflow-level span events."""

    def test_workflow_start_emits_event(self, otel_backend):
        backend, span = otel_backend
        backend.track_workflow_start(
            "wf-1", "test_wf",
            {"workflow": {"stages": [{"name": "s1"}, {"name": "s2"}]}},
            NOW,
            data=WorkflowStartData(environment="prod", trigger_type="api", tags=["a", "b"]),
        )
        events = [c for c in span.add_event.call_args_list]
        assert len(events) == 1
        name = events[0][0][0]
        attrs = events[0][1].get("attributes", events[0][0][1] if len(events[0][0]) > 1 else {})
        assert name == "workflow.started"
        assert attrs["stages"] == 2
        assert attrs["environment"] == "prod"
        assert attrs["trigger"] == "api"
        assert attrs["tags"] == "a, b"

    def test_workflow_end_emits_event(self, otel_backend):
        backend, span = otel_backend
        backend.track_workflow_start("wf-1", "test_wf", {}, NOW)
        span.add_event.reset_mock()
        backend.track_workflow_end("wf-1", NOW, "completed")
        events = [c for c in span.add_event.call_args_list]
        assert len(events) == 1
        assert events[0][0][0] == "workflow.completed"

    def test_workflow_end_includes_error(self, otel_backend):
        backend, span = otel_backend
        backend.track_workflow_start("wf-1", "test_wf", {}, NOW)
        span.add_event.reset_mock()
        backend.track_workflow_end("wf-1", NOW, "failed", error_message="boom")
        events = [c for c in span.add_event.call_args_list]
        attrs = events[0][1].get("attributes", events[0][0][1] if len(events[0][0]) > 1 else {})
        assert attrs["error"] == "boom"

    def test_workflow_metrics_emits_event(self, otel_backend):
        backend, span = otel_backend
        backend.track_workflow_start("wf-1", "test_wf", {}, NOW)
        span.add_event.reset_mock()
        backend.update_workflow_metrics("wf-1", 5, 2, 1000, 0.05)
        events = [c for c in span.add_event.call_args_list]
        assert len(events) == 1
        assert events[0][0][0] == "workflow.metrics"
        attrs = events[0][1].get("attributes", events[0][0][1] if len(events[0][0]) > 1 else {})
        assert attrs["llm_calls"] == 5
        assert attrs["tokens"] == 1000


class TestStageSpanEvents:
    """Stage-level span events."""

    def test_stage_start_emits_agents_and_mode(self, otel_backend):
        backend, span = otel_backend
        backend.track_workflow_start("wf-1", "test_wf", {}, NOW)
        span.add_event.reset_mock()
        backend.track_stage_start(
            "s-1", "wf-1", "decision",
            {"stage": {"agents": ["a1", "a2", "a3"], "execution": {"agent_mode": "parallel"}}},
            NOW,
        )
        events = [c for c in span.add_event.call_args_list]
        assert len(events) == 1
        assert events[0][0][0] == "stage.started"
        attrs = events[0][1].get("attributes", events[0][0][1] if len(events[0][0]) > 1 else {})
        assert attrs["agent_count"] == 3
        assert attrs["execution_mode"] == "parallel"
        assert "a1" in attrs["agents"]

    def test_stage_end_emits_agent_counts(self, otel_backend):
        backend, span = otel_backend
        backend.track_workflow_start("wf-1", "test_wf", {}, NOW)
        backend.track_stage_start("s-1", "wf-1", "decision", {}, NOW)
        span.add_event.reset_mock()
        backend.track_stage_end("s-1", NOW, "completed", num_agents_executed=3, num_agents_succeeded=2, num_agents_failed=1)
        events = [c for c in span.add_event.call_args_list]
        assert len(events) == 1
        assert events[0][0][0] == "stage.completed"
        attrs = events[0][1].get("attributes", events[0][0][1] if len(events[0][0]) > 1 else {})
        assert attrs["agents_succeeded"] == 2
        assert attrs["agents_failed"] == 1


class TestAgentSpanEvents:
    """Agent-level span events."""

    def test_agent_start_emits_model_info(self, otel_backend):
        backend, span = otel_backend
        backend.track_workflow_start("wf-1", "test_wf", {}, NOW)
        backend.track_stage_start("s-1", "wf-1", "decision", {}, NOW)
        span.add_event.reset_mock()
        backend.track_agent_start(
            "a-1", "s-1", "optimist",
            {"agent": {"inference": {"model": "gpt-4", "provider": "openai"}, "type": "standard"}},
            NOW,
        )
        events = [c for c in span.add_event.call_args_list]
        assert len(events) == 1
        assert events[0][0][0] == "agent.started"
        attrs = events[0][1].get("attributes", events[0][0][1] if len(events[0][0]) > 1 else {})
        assert attrs["model"] == "gpt-4"
        assert attrs["provider"] == "openai"
        assert attrs["type"] == "standard"

    def test_agent_output_emits_metrics(self, otel_backend):
        backend, span = otel_backend
        backend.track_workflow_start("wf-1", "test_wf", {}, NOW)
        backend.track_stage_start("s-1", "wf-1", "decision", {}, NOW)
        backend.track_agent_start("a-1", "s-1", "optimist", {}, NOW)
        span.add_event.reset_mock()
        backend.set_agent_output(
            "a-1", {},
            metrics=AgentOutputData(total_tokens=500, estimated_cost_usd=0.01, confidence_score=0.9, num_llm_calls=2),
        )
        events = [c for c in span.add_event.call_args_list]
        assert len(events) == 1
        assert events[0][0][0] == "agent.output"
        attrs = events[0][1].get("attributes", events[0][0][1] if len(events[0][0]) > 1 else {})
        assert attrs["tokens"] == 500
        assert attrs["confidence"] == 0.9

    def test_agent_end_emits_status(self, otel_backend):
        backend, span = otel_backend
        backend.track_workflow_start("wf-1", "test_wf", {}, NOW)
        backend.track_stage_start("s-1", "wf-1", "decision", {}, NOW)
        backend.track_agent_start("a-1", "s-1", "optimist", {}, NOW)
        span.add_event.reset_mock()
        backend.track_agent_end("a-1", NOW, "completed")
        events = [c for c in span.add_event.call_args_list]
        assert len(events) == 1
        assert events[0][0][0] == "agent.completed"


class TestSafetySpanEvents:
    """Safety violation span events."""

    def test_safety_violation_adds_event_to_agent_span(self, otel_backend):
        backend, span = otel_backend
        backend.track_workflow_start("wf-1", "test_wf", {}, NOW)
        backend.track_stage_start("s-1", "wf-1", "decision", {}, NOW)
        backend.track_agent_start("a-1", "s-1", "agent", {}, NOW)
        span.add_event.reset_mock()
        backend.track_safety_violation(
            "HIGH", "unsafe action", "action_policy",
            data=SafetyViolationData(agent_id="a-1"),
        )
        events = [c for c in span.add_event.call_args_list]
        assert len(events) == 1
        assert events[0][0][0] == "safety.violation"
        attrs = events[0][1].get("attributes", events[0][0][1] if len(events[0][0]) > 1 else {})
        assert attrs["severity"] == "HIGH"
        assert attrs["policy"] == "action_policy"

    def test_safety_violation_no_entity_is_noop(self, otel_backend):
        backend, span = otel_backend
        span.add_event.reset_mock()
        backend.track_safety_violation("LOW", "test", "test_policy")
        span.add_event.assert_not_called()


class TestCollaborationSpanEvents:
    """Collaboration event span events."""

    def test_collaboration_event_emits_span_event(self, otel_backend):
        backend, span = otel_backend
        backend.track_workflow_start("wf-1", "test_wf", {}, NOW)
        backend.track_stage_start("s-1", "wf-1", "decision", {}, NOW)
        span.add_event.reset_mock()
        backend.track_collaboration_event(
            "s-1", "synthesis", ["a1", "a2"],
            data=CollaborationEventData(
                resolution_strategy="consensus",
                outcome="agreed",
                confidence_score=0.85,
            ),
        )
        events = [c for c in span.add_event.call_args_list]
        assert len(events) == 1
        assert events[0][0][0] == "collaboration.synthesis"
        attrs = events[0][1].get("attributes", events[0][0][1] if len(events[0][0]) > 1 else {})
        assert attrs["agents"] == "a1, a2"
        assert attrs["strategy"] == "consensus"
        assert attrs["confidence"] == 0.85
