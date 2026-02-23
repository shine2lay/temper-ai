"""
Tests for Prometheus observability backend (stub).

Tests cover:
- Backend initialization
- All tracking methods (stub logging)
- Stats retrieval
- Context management
- Proper stub behavior (no errors, logs only)
"""

import logging
import uuid
from datetime import datetime
from unittest.mock import patch

import pytest

from temper_ai.observability.backends.prometheus_backend import (
    PrometheusObservabilityBackend,
)


@pytest.fixture
def prometheus_backend():
    """Create Prometheus backend."""
    return PrometheusObservabilityBackend(push_gateway_url="http://localhost:9091")


@pytest.fixture
def prometheus_backend_no_gateway():
    """Create Prometheus backend without gateway."""
    return PrometheusObservabilityBackend()


def make_workflow_id() -> str:
    """Generate unique workflow ID."""
    return f"wf-{uuid.uuid4().hex[:12]}"


def make_stage_id() -> str:
    """Generate unique stage ID."""
    return f"st-{uuid.uuid4().hex[:12]}"


def make_agent_id() -> str:
    """Generate unique agent ID."""
    return f"ag-{uuid.uuid4().hex[:12]}"


# ========== Initialization Tests ==========


def test_init_with_gateway():
    """Test initialization with push gateway URL."""
    backend = PrometheusObservabilityBackend(push_gateway_url="http://localhost:9091")
    assert backend.push_gateway_url == "http://localhost:9091"


def test_init_without_gateway():
    """Test initialization without push gateway URL."""
    backend = PrometheusObservabilityBackend()
    assert backend.push_gateway_url is None


# ========== Workflow Tracking Tests ==========


def test_track_workflow_start(
    prometheus_backend: PrometheusObservabilityBackend, caplog
):
    """Test workflow start tracking (stub)."""
    workflow_id = make_workflow_id()

    with caplog.at_level(logging.DEBUG):
        result = prometheus_backend.track_workflow_start(
            workflow_id=workflow_id,
            workflow_name="test_workflow",
            workflow_config={"workflow": {"version": "1.0"}},
            start_time=datetime.utcnow(),
            trigger_type="manual",
        )

    assert result is None
    assert any("Prometheus STUB" in record.message for record in caplog.records)


def test_track_workflow_end(prometheus_backend: PrometheusObservabilityBackend, caplog):
    """Test workflow end tracking (stub)."""
    workflow_id = make_workflow_id()

    with caplog.at_level(logging.DEBUG):
        result = prometheus_backend.track_workflow_end(
            workflow_id=workflow_id, end_time=datetime.utcnow(), status="completed"
        )

    assert result is None
    assert any("Prometheus STUB" in record.message for record in caplog.records)


def test_update_workflow_metrics(
    prometheus_backend: PrometheusObservabilityBackend, caplog
):
    """Test workflow metrics update (stub)."""
    workflow_id = make_workflow_id()

    with caplog.at_level(logging.DEBUG):
        result = prometheus_backend.update_workflow_metrics(
            workflow_id=workflow_id,
            total_llm_calls=10,
            total_tool_calls=5,
            total_tokens=1000,
            total_cost_usd=0.05,
        )

    assert result is None
    assert any("Prometheus STUB" in record.message for record in caplog.records)


# ========== Stage Tracking Tests ==========


def test_track_stage_start(prometheus_backend: PrometheusObservabilityBackend, caplog):
    """Test stage start tracking (stub)."""
    workflow_id = make_workflow_id()
    stage_id = make_stage_id()

    with caplog.at_level(logging.DEBUG):
        result = prometheus_backend.track_stage_start(
            stage_id=stage_id,
            workflow_id=workflow_id,
            stage_name="analysis",
            stage_config={"stage": {"version": "1.0"}},
            start_time=datetime.utcnow(),
        )

    assert result is None
    assert any("Prometheus STUB" in record.message for record in caplog.records)


def test_track_stage_end(prometheus_backend: PrometheusObservabilityBackend, caplog):
    """Test stage end tracking (stub)."""
    stage_id = make_stage_id()

    with caplog.at_level(logging.DEBUG):
        result = prometheus_backend.track_stage_end(
            stage_id=stage_id, end_time=datetime.utcnow(), status="completed"
        )

    assert result is None
    assert any("Prometheus STUB" in record.message for record in caplog.records)


def test_set_stage_output(prometheus_backend: PrometheusObservabilityBackend, caplog):
    """Test setting stage output (stub)."""
    stage_id = make_stage_id()

    with caplog.at_level(logging.DEBUG):
        result = prometheus_backend.set_stage_output(
            stage_id=stage_id, output_data={"result": "success"}
        )

    assert result is None
    assert any("Prometheus STUB" in record.message for record in caplog.records)


# ========== Agent Tracking Tests ==========


def test_track_agent_start(prometheus_backend: PrometheusObservabilityBackend, caplog):
    """Test agent start tracking (stub)."""
    stage_id = make_stage_id()
    agent_id = make_agent_id()

    with caplog.at_level(logging.DEBUG):
        result = prometheus_backend.track_agent_start(
            agent_id=agent_id,
            stage_id=stage_id,
            agent_name="researcher",
            agent_config={"agent": {"version": "1.0"}},
            start_time=datetime.utcnow(),
        )

    assert result is None
    assert any("Prometheus STUB" in record.message for record in caplog.records)


def test_track_agent_end(prometheus_backend: PrometheusObservabilityBackend, caplog):
    """Test agent end tracking (stub)."""
    agent_id = make_agent_id()

    with caplog.at_level(logging.DEBUG):
        result = prometheus_backend.track_agent_end(
            agent_id=agent_id, end_time=datetime.utcnow(), status="completed"
        )

    assert result is None
    assert any("Prometheus STUB" in record.message for record in caplog.records)


def test_set_agent_output(prometheus_backend: PrometheusObservabilityBackend, caplog):
    """Test setting agent output (stub)."""
    agent_id = make_agent_id()

    with caplog.at_level(logging.DEBUG):
        result = prometheus_backend.set_agent_output(
            agent_id=agent_id,
            output_data={"analysis": "complete"},
            reasoning="Based on data",
            confidence_score=0.9,
        )

    assert result is None
    assert any("Prometheus STUB" in record.message for record in caplog.records)


# ========== LLM Call Tracking Tests ==========


def test_track_llm_call(prometheus_backend: PrometheusObservabilityBackend, caplog):
    """Test LLM call tracking (stub)."""
    agent_id = make_agent_id()
    llm_call_id = f"llm-{uuid.uuid4().hex[:12]}"

    with caplog.at_level(logging.DEBUG):
        result = prometheus_backend.track_llm_call(
            llm_call_id=llm_call_id,
            agent_id=agent_id,
            provider="openai",
            model="gpt-4",
            prompt="Test prompt",
            response="Test response",
            prompt_tokens=10,
            completion_tokens=20,
            latency_ms=500,
            estimated_cost_usd=0.001,
            start_time=datetime.utcnow(),
        )

    assert result is None
    assert any("Prometheus STUB" in record.message for record in caplog.records)


def test_track_llm_call_with_optional_params(
    prometheus_backend: PrometheusObservabilityBackend, caplog
):
    """Test LLM call tracking with optional parameters (stub)."""
    agent_id = make_agent_id()
    llm_call_id = f"llm-{uuid.uuid4().hex[:12]}"

    with caplog.at_level(logging.DEBUG):
        result = prometheus_backend.track_llm_call(
            llm_call_id=llm_call_id,
            agent_id=agent_id,
            provider="openai",
            model="gpt-4",
            prompt="Test",
            response="Response",
            prompt_tokens=10,
            completion_tokens=20,
            latency_ms=500,
            estimated_cost_usd=0.001,
            start_time=datetime.utcnow(),
            temperature=0.7,
            max_tokens=100,
            status="success",
        )

    assert result is None
    assert any("Prometheus STUB" in record.message for record in caplog.records)


# ========== Tool Call Tracking Tests ==========


def test_track_tool_call(prometheus_backend: PrometheusObservabilityBackend, caplog):
    """Test tool call tracking (stub)."""
    agent_id = make_agent_id()
    tool_id = f"tool-{uuid.uuid4().hex[:12]}"

    with caplog.at_level(logging.DEBUG):
        result = prometheus_backend.track_tool_call(
            tool_execution_id=tool_id,
            agent_id=agent_id,
            tool_name="web_scraper",
            input_params={"url": "https://example.com"},
            output_data={"content": "scraped"},
            start_time=datetime.utcnow(),
            duration_seconds=2.5,
            status="success",
        )

    assert result is None
    assert any("Prometheus STUB" in record.message for record in caplog.records)


def test_track_tool_call_with_error(
    prometheus_backend: PrometheusObservabilityBackend, caplog
):
    """Test tool call tracking with error (stub)."""
    agent_id = make_agent_id()
    tool_id = f"tool-{uuid.uuid4().hex[:12]}"

    with caplog.at_level(logging.DEBUG):
        result = prometheus_backend.track_tool_call(
            tool_execution_id=tool_id,
            agent_id=agent_id,
            tool_name="web_scraper",
            input_params={"url": "https://example.com"},
            output_data={},
            start_time=datetime.utcnow(),
            duration_seconds=1.0,
            status="failed",
            error_message="Timeout",
        )

    assert result is None
    assert any("Prometheus STUB" in record.message for record in caplog.records)


# ========== Safety and Collaboration Tests ==========


def test_track_safety_violation(
    prometheus_backend: PrometheusObservabilityBackend, caplog
):
    """Test safety violation tracking (stub)."""
    with caplog.at_level(logging.WARNING):
        result = prometheus_backend.track_safety_violation(
            workflow_id=make_workflow_id(),
            stage_id=make_stage_id(),
            agent_id=make_agent_id(),
            violation_severity="HIGH",
            violation_message="Unsafe action",
            policy_name="action_policy",
        )

    assert result is None
    assert any("Prometheus STUB" in record.message for record in caplog.records)


def test_track_collaboration_event(prometheus_backend: PrometheusObservabilityBackend):
    """Test collaboration event tracking (stub)."""
    stage_id = make_stage_id()
    agent1_id = make_agent_id()
    agent2_id = make_agent_id()

    # Should return stub event ID
    event_id = prometheus_backend.track_collaboration_event(
        stage_id=stage_id,
        event_type="vote",
        agents_involved=[agent1_id, agent2_id],
        event_data={"votes": {"option_a": 2}},
    )

    assert event_id == "collab-stub-vote"


# ========== Context Management Tests ==========


def test_get_session_context(prometheus_backend: PrometheusObservabilityBackend):
    """Test session context manager (no-op)."""
    with prometheus_backend.get_session_context() as context:
        assert context is None


# ========== Maintenance Tests ==========


def test_cleanup_old_records(prometheus_backend: PrometheusObservabilityBackend):
    """Test cleanup (no-op for Prometheus)."""
    result = prometheus_backend.cleanup_old_records(retention_days=30)

    assert isinstance(result, dict)
    assert len(result) == 0


def test_cleanup_old_records_dry_run(
    prometheus_backend: PrometheusObservabilityBackend,
):
    """Test cleanup dry run (no-op for Prometheus)."""
    result = prometheus_backend.cleanup_old_records(retention_days=30, dry_run=True)

    assert isinstance(result, dict)
    assert len(result) == 0


def test_get_stats(prometheus_backend: PrometheusObservabilityBackend):
    """Test getting backend stats."""
    stats = prometheus_backend.get_stats()

    assert stats is not None
    assert stats["backend_type"] == "prometheus"
    assert stats["status"] == "stub"
    assert stats["push_gateway_url"] == "http://localhost:9091"
    assert "note" in stats


def test_get_stats_no_gateway(
    prometheus_backend_no_gateway: PrometheusObservabilityBackend,
):
    """Test getting stats without gateway configured."""
    stats = prometheus_backend_no_gateway.get_stats()

    assert stats is not None
    assert stats["backend_type"] == "prometheus"
    assert stats["push_gateway_url"] is None


# ========== Logging Tests ==========


@patch("temper_ai.observability.backends.prometheus_backend.logger")
def test_track_workflow_start_logs(
    mock_logger, prometheus_backend: PrometheusObservabilityBackend
):
    """Test that workflow start logs debug message."""
    workflow_id = make_workflow_id()

    prometheus_backend.track_workflow_start(
        workflow_id=workflow_id,
        workflow_name="test_workflow",
        workflow_config={"workflow": {"version": "1.0"}},
        start_time=datetime.utcnow(),
    )

    # Verify logging was called with relevant content
    mock_logger.debug.assert_called()
    log_msg = str(mock_logger.debug.call_args)
    assert "Prometheus" in log_msg or workflow_id in log_msg


@patch("temper_ai.observability.backends.prometheus_backend.logger")
def test_track_safety_violation_logs_warning(
    mock_logger, prometheus_backend: PrometheusObservabilityBackend
):
    """Test that safety violation logs warning."""
    prometheus_backend.track_safety_violation(
        workflow_id=None,
        stage_id=None,
        agent_id=None,
        violation_severity="HIGH",
        violation_message="Test violation",
        policy_name="test_policy",
    )

    # Verify warning was logged with relevant content
    mock_logger.warning.assert_called()
    warning_msg = str(mock_logger.warning.call_args)
    assert "Prometheus" in warning_msg or "safety" in warning_msg.lower()


# ========== Full Lifecycle Test ==========


def test_full_workflow_lifecycle(prometheus_backend: PrometheusObservabilityBackend):
    """Test complete workflow lifecycle (all stubs should work)."""
    workflow_id = make_workflow_id()
    stage_id = make_stage_id()
    agent_id = make_agent_id()

    # All operations should complete without errors
    prometheus_backend.track_workflow_start(
        workflow_id=workflow_id,
        workflow_name="test",
        workflow_config={},
        start_time=datetime.utcnow(),
    )

    prometheus_backend.track_stage_start(
        stage_id=stage_id,
        workflow_id=workflow_id,
        stage_name="analysis",
        stage_config={},
        start_time=datetime.utcnow(),
    )

    prometheus_backend.track_agent_start(
        agent_id=agent_id,
        stage_id=stage_id,
        agent_name="researcher",
        agent_config={},
        start_time=datetime.utcnow(),
    )

    prometheus_backend.track_llm_call(
        llm_call_id=f"llm-{uuid.uuid4().hex[:12]}",
        agent_id=agent_id,
        provider="openai",
        model="gpt-4",
        prompt="Test",
        response="Response",
        prompt_tokens=10,
        completion_tokens=20,
        latency_ms=500,
        estimated_cost_usd=0.001,
        start_time=datetime.utcnow(),
    )

    prometheus_backend.track_tool_call(
        tool_execution_id=f"tool-{uuid.uuid4().hex[:12]}",
        agent_id=agent_id,
        tool_name="calculator",
        input_params={},
        output_data={},
        start_time=datetime.utcnow(),
        duration_seconds=0.1,
    )

    prometheus_backend.track_agent_end(
        agent_id=agent_id, end_time=datetime.utcnow(), status="completed"
    )

    prometheus_backend.track_stage_end(
        stage_id=stage_id, end_time=datetime.utcnow(), status="completed"
    )

    prometheus_backend.track_workflow_end(
        workflow_id=workflow_id, end_time=datetime.utcnow(), status="completed"
    )

    # Verify backend still reports consistent stats after full lifecycle
    stats = prometheus_backend.get_stats()
    assert stats["backend_type"] == "prometheus"
