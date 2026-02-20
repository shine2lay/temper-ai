"""
Tests for S3 observability backend (stub).

Tests cover:
- Backend initialization with bucket/prefix/region
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

from temper_ai.observability.backends.s3_backend import S3ObservabilityBackend


@pytest.fixture
def s3_backend():
    """Create S3 backend with full configuration."""
    return S3ObservabilityBackend(
        bucket_name="test-observability-bucket",
        prefix="observability",
        region="us-west-2"
    )


@pytest.fixture
def s3_backend_minimal():
    """Create S3 backend with minimal configuration."""
    return S3ObservabilityBackend()


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


def test_init_with_full_config():
    """Test initialization with full configuration."""
    backend = S3ObservabilityBackend(
        bucket_name="my-bucket",
        prefix="custom-prefix",
        region="eu-west-1"
    )

    assert backend.bucket_name == "my-bucket"
    assert backend.prefix == "custom-prefix"
    assert backend.region == "eu-west-1"


def test_init_with_defaults():
    """Test initialization with default values."""
    backend = S3ObservabilityBackend()

    assert backend.bucket_name is None
    assert backend.prefix == "observability"
    assert backend.region == "us-east-1"


def test_init_partial_config():
    """Test initialization with partial configuration."""
    backend = S3ObservabilityBackend(bucket_name="test-bucket")

    assert backend.bucket_name == "test-bucket"
    assert backend.prefix == "observability"
    assert backend.region == "us-east-1"


# ========== Workflow Tracking Tests ==========


def test_track_workflow_start(s3_backend: S3ObservabilityBackend, caplog):
    """Test workflow start tracking (stub)."""
    workflow_id = make_workflow_id()

    # Should not raise any errors
    with caplog.at_level(logging.DEBUG):
        result = s3_backend.track_workflow_start(
            workflow_id=workflow_id,
            workflow_name="test_workflow",
            workflow_config={"workflow": {"version": "1.0"}},
            start_time=datetime.utcnow(),
            trigger_type="manual"
        )

    assert result is None
    assert any("S3 STUB" in record.message for record in caplog.records)


def test_track_workflow_end(s3_backend: S3ObservabilityBackend, caplog):
    """Test workflow end tracking (stub)."""
    workflow_id = make_workflow_id()

    # Should not raise any errors
    with caplog.at_level(logging.DEBUG):
        result = s3_backend.track_workflow_end(
            workflow_id=workflow_id,
            end_time=datetime.utcnow(),
            status="completed"
        )

    assert result is None
    assert any("S3 STUB" in record.message for record in caplog.records)


def test_update_workflow_metrics(s3_backend: S3ObservabilityBackend, caplog):
    """Test workflow metrics update (stub)."""
    workflow_id = make_workflow_id()

    # Should not raise any errors
    with caplog.at_level(logging.DEBUG):
        result = s3_backend.update_workflow_metrics(
            workflow_id=workflow_id,
            total_llm_calls=10,
            total_tool_calls=5,
            total_tokens=1000,
            total_cost_usd=0.05
        )

    assert result is None
    assert any("S3 STUB" in record.message for record in caplog.records)


# ========== Stage Tracking Tests ==========


def test_track_stage_start(s3_backend: S3ObservabilityBackend, caplog):
    """Test stage start tracking (stub)."""
    workflow_id = make_workflow_id()
    stage_id = make_stage_id()

    # Should not raise any errors
    with caplog.at_level(logging.DEBUG):
        result = s3_backend.track_stage_start(
            stage_id=stage_id,
            workflow_id=workflow_id,
            stage_name="analysis",
            stage_config={"stage": {"version": "1.0"}},
            start_time=datetime.utcnow()
        )

    assert result is None
    assert any("S3 STUB" in record.message for record in caplog.records)


def test_track_stage_end(s3_backend: S3ObservabilityBackend, caplog):
    """Test stage end tracking (stub)."""
    stage_id = make_stage_id()

    # Should not raise any errors
    with caplog.at_level(logging.DEBUG):
        result = s3_backend.track_stage_end(
            stage_id=stage_id,
            end_time=datetime.utcnow(),
            status="completed"
        )

    assert result is None
    assert any("S3 STUB" in record.message for record in caplog.records)


def test_set_stage_output(s3_backend: S3ObservabilityBackend, caplog):
    """Test setting stage output (stub)."""
    stage_id = make_stage_id()

    # Should not raise any errors
    with caplog.at_level(logging.DEBUG):
        result = s3_backend.set_stage_output(
            stage_id=stage_id,
            output_data={"result": "success"}
        )

    assert result is None
    assert any("S3 STUB" in record.message for record in caplog.records)


# ========== Agent Tracking Tests ==========


def test_track_agent_start(s3_backend: S3ObservabilityBackend, caplog):
    """Test agent start tracking (stub)."""
    stage_id = make_stage_id()
    agent_id = make_agent_id()

    # Should not raise any errors
    with caplog.at_level(logging.DEBUG):
        result = s3_backend.track_agent_start(
            agent_id=agent_id,
            stage_id=stage_id,
            agent_name="researcher",
            agent_config={"agent": {"version": "1.0"}},
            start_time=datetime.utcnow()
        )

    assert result is None
    assert any("S3 STUB" in record.message for record in caplog.records)


def test_track_agent_end(s3_backend: S3ObservabilityBackend, caplog):
    """Test agent end tracking (stub)."""
    agent_id = make_agent_id()

    # Should not raise any errors
    with caplog.at_level(logging.DEBUG):
        result = s3_backend.track_agent_end(
            agent_id=agent_id,
            end_time=datetime.utcnow(),
            status="completed"
        )

    assert result is None
    assert any("S3 STUB" in record.message for record in caplog.records)


def test_set_agent_output(s3_backend: S3ObservabilityBackend, caplog):
    """Test setting agent output (stub)."""
    agent_id = make_agent_id()

    # Should not raise any errors
    with caplog.at_level(logging.DEBUG):
        result = s3_backend.set_agent_output(
            agent_id=agent_id,
            output_data={"analysis": "complete"},
            reasoning="Based on data",
            confidence_score=0.9
        )

    assert result is None
    assert any("S3 STUB" in record.message for record in caplog.records)


# ========== LLM Call Tracking Tests ==========


def test_track_llm_call(s3_backend: S3ObservabilityBackend, caplog):
    """Test LLM call tracking (stub)."""
    agent_id = make_agent_id()
    llm_call_id = f"llm-{uuid.uuid4().hex[:12]}"

    # Should not raise any errors
    with caplog.at_level(logging.DEBUG):
        result = s3_backend.track_llm_call(
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
            start_time=datetime.utcnow()
        )

    assert result is None
    assert any("S3 STUB" in record.message for record in caplog.records)


def test_track_llm_call_with_optional_params(s3_backend: S3ObservabilityBackend, caplog):
    """Test LLM call tracking with optional parameters (stub)."""
    agent_id = make_agent_id()
    llm_call_id = f"llm-{uuid.uuid4().hex[:12]}"

    # Should not raise any errors
    with caplog.at_level(logging.DEBUG):
        result = s3_backend.track_llm_call(
            llm_call_id=llm_call_id,
            agent_id=agent_id,
            provider="anthropic",
            model="claude-3",
            prompt="Test",
            response="Response",
            prompt_tokens=10,
            completion_tokens=20,
            latency_ms=500,
            estimated_cost_usd=0.001,
            start_time=datetime.utcnow(),
            temperature=0.7,
            max_tokens=100
        )

    assert result is None
    assert any("S3 STUB" in record.message for record in caplog.records)


# ========== Tool Call Tracking Tests ==========


def test_track_tool_call(s3_backend: S3ObservabilityBackend, caplog):
    """Test tool call tracking (stub)."""
    agent_id = make_agent_id()
    tool_id = f"tool-{uuid.uuid4().hex[:12]}"

    # Should not raise any errors
    with caplog.at_level(logging.DEBUG):
        result = s3_backend.track_tool_call(
            tool_execution_id=tool_id,
            agent_id=agent_id,
            tool_name="web_scraper",
            input_params={"url": "https://example.com"},
            output_data={"content": "scraped"},
            start_time=datetime.utcnow(),
            duration_seconds=2.5
        )

    assert result is None
    assert any("S3 STUB" in record.message for record in caplog.records)


def test_track_tool_call_with_error(s3_backend: S3ObservabilityBackend, caplog):
    """Test tool call tracking with error (stub)."""
    agent_id = make_agent_id()
    tool_id = f"tool-{uuid.uuid4().hex[:12]}"

    # Should not raise any errors
    with caplog.at_level(logging.DEBUG):
        result = s3_backend.track_tool_call(
            tool_execution_id=tool_id,
            agent_id=agent_id,
            tool_name="database_query",
            input_params={"query": "SELECT *"},
            output_data={},
            start_time=datetime.utcnow(),
            duration_seconds=1.0,
            status="failed",
            error_message="Connection lost"
        )

    assert result is None
    assert any("S3 STUB" in record.message for record in caplog.records)


# ========== Safety and Collaboration Tests ==========


def test_track_safety_violation(s3_backend: S3ObservabilityBackend, caplog):
    """Test safety violation tracking (stub)."""
    # Should not raise any errors
    with caplog.at_level(logging.WARNING):
        result = s3_backend.track_safety_violation(
            workflow_id=make_workflow_id(),
            stage_id=make_stage_id(),
            agent_id=make_agent_id(),
            violation_severity="CRITICAL",
            violation_message="Dangerous action attempted",
            policy_name="security_policy"
        )

    assert result is None
    assert any("S3 STUB" in record.message for record in caplog.records)


def test_track_collaboration_event(s3_backend: S3ObservabilityBackend):
    """Test collaboration event tracking (stub)."""
    stage_id = make_stage_id()
    agent1_id = make_agent_id()
    agent2_id = make_agent_id()

    # Should return stub event ID
    event_id = s3_backend.track_collaboration_event(
        stage_id=stage_id,
        event_type="consensus",
        agents_involved=[agent1_id, agent2_id],
        event_data={"decision": "proceed"}
    )

    assert event_id == "collab-stub-consensus"


# ========== Context Management Tests ==========


def test_get_session_context(s3_backend: S3ObservabilityBackend):
    """Test session context manager (no-op)."""
    with s3_backend.get_session_context() as context:
        assert context is None


# ========== Maintenance Tests ==========


def test_cleanup_old_records(s3_backend: S3ObservabilityBackend):
    """Test cleanup (no-op for S3 - use lifecycle policies)."""
    result = s3_backend.cleanup_old_records(retention_days=30)

    assert isinstance(result, dict)
    assert len(result) == 0


def test_cleanup_old_records_dry_run(s3_backend: S3ObservabilityBackend):
    """Test cleanup dry run (no-op for S3)."""
    result = s3_backend.cleanup_old_records(retention_days=30, dry_run=True)

    assert isinstance(result, dict)
    assert len(result) == 0


def test_get_stats(s3_backend: S3ObservabilityBackend):
    """Test getting backend stats."""
    stats = s3_backend.get_stats()

    assert stats is not None
    assert stats["backend_type"] == "s3"
    assert stats["status"] == "stub"
    assert stats["bucket_name"] == "test-observability-bucket"
    assert stats["prefix"] == "observability"
    assert stats["region"] == "us-west-2"
    assert "note" in stats


def test_get_stats_minimal(s3_backend_minimal: S3ObservabilityBackend):
    """Test getting stats with minimal configuration."""
    stats = s3_backend_minimal.get_stats()

    assert stats is not None
    assert stats["backend_type"] == "s3"
    assert stats["bucket_name"] is None
    assert stats["prefix"] == "observability"
    assert stats["region"] == "us-east-1"


# ========== Logging Tests ==========


@patch("temper_ai.observability.backends.s3_backend.logger")
def test_track_workflow_start_logs(mock_logger, s3_backend: S3ObservabilityBackend):
    """Test that workflow start logs debug message."""
    workflow_id = make_workflow_id()

    s3_backend.track_workflow_start(
        workflow_id=workflow_id,
        workflow_name="test_workflow",
        workflow_config={"workflow": {"version": "1.0"}},
        start_time=datetime.utcnow()
    )

    # Verify logging was called with relevant content
    mock_logger.debug.assert_called()
    log_msg = str(mock_logger.debug.call_args)
    assert "S3" in log_msg or workflow_id in log_msg


@patch("temper_ai.observability.backends.s3_backend.logger")
def test_track_safety_violation_logs_warning(mock_logger, s3_backend: S3ObservabilityBackend):
    """Test that safety violation logs warning."""
    s3_backend.track_safety_violation(
        workflow_id=None,
        stage_id=None,
        agent_id=None,
        violation_severity="HIGH",
        violation_message="Test violation",
        policy_name="test_policy"
    )

    # Verify warning was logged with relevant content
    mock_logger.warning.assert_called()
    warning_msg = str(mock_logger.warning.call_args)
    assert "S3" in warning_msg or "safety" in warning_msg.lower()


# ========== Full Lifecycle Test ==========


def test_full_workflow_lifecycle(s3_backend: S3ObservabilityBackend):
    """Test complete workflow lifecycle (all stubs should work)."""
    workflow_id = make_workflow_id()
    stage_id = make_stage_id()
    agent_id = make_agent_id()

    # All operations should complete without errors
    s3_backend.track_workflow_start(
        workflow_id=workflow_id,
        workflow_name="test",
        workflow_config={},
        start_time=datetime.utcnow()
    )

    s3_backend.track_stage_start(
        stage_id=stage_id,
        workflow_id=workflow_id,
        stage_name="analysis",
        stage_config={},
        start_time=datetime.utcnow()
    )

    s3_backend.track_agent_start(
        agent_id=agent_id,
        stage_id=stage_id,
        agent_name="researcher",
        agent_config={},
        start_time=datetime.utcnow()
    )

    s3_backend.track_llm_call(
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
        start_time=datetime.utcnow()
    )

    s3_backend.track_tool_call(
        tool_execution_id=f"tool-{uuid.uuid4().hex[:12]}",
        agent_id=agent_id,
        tool_name="calculator",
        input_params={},
        output_data={},
        start_time=datetime.utcnow(),
        duration_seconds=0.1
    )

    s3_backend.track_agent_end(
        agent_id=agent_id,
        end_time=datetime.utcnow(),
        status="completed"
    )

    s3_backend.track_stage_end(
        stage_id=stage_id,
        end_time=datetime.utcnow(),
        status="completed"
    )

    s3_backend.track_workflow_end(
        workflow_id=workflow_id,
        end_time=datetime.utcnow(),
        status="completed"
    )

    # Verify backend still reports consistent stats after full lifecycle
    stats = s3_backend.get_stats()
    assert stats["backend_type"] == "s3"


# ========== Region-Specific Tests ==========


def test_different_regions():
    """Test initialization with different AWS regions."""
    regions = ["us-east-1", "us-west-2", "eu-west-1", "ap-southeast-1"]

    for region in regions:
        backend = S3ObservabilityBackend(region=region)
        assert backend.region == region


def test_custom_prefix():
    """Test initialization with custom prefix."""
    backend = S3ObservabilityBackend(prefix="custom/path/observability")
    assert backend.prefix == "custom/path/observability"
