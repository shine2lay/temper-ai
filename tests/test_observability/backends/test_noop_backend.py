"""
Tests for NoOp observability backend.

Tests cover:
- Backend initialization
- All tracking methods (no-op, no errors)
- Fast execution (no I/O)
- Null object pattern compliance
- Stats retrieval
- Context management
"""

import uuid
from datetime import datetime

import pytest

from temper_ai.observability.backends.noop_backend import NoOpBackend


@pytest.fixture
def noop_backend():
    """Create NoOp backend."""
    return NoOpBackend()


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


def test_init():
    """Test NoOp backend initialization."""
    backend = NoOpBackend()
    stats = backend.get_stats()
    assert stats["backend_type"] == "noop"


# ========== Workflow Tracking Tests ==========


def test_track_workflow_start(noop_backend: NoOpBackend):
    """Test workflow start tracking (no-op)."""
    workflow_id = make_workflow_id()

    # Should not raise any errors and return immediately
    result = noop_backend.track_workflow_start(
        workflow_id=workflow_id,
        workflow_name="test_workflow",
        workflow_config={"workflow": {"version": "1.0"}},
        start_time=datetime.utcnow(),
        trigger_type="manual",
        trigger_data={"user": "test"},
        optimization_target="speed",
        product_type="demo",
        environment="test",
        tags=["test", "demo"],
        extra_metadata={"key": "value"},
    )
    assert result is None


def test_track_workflow_end(noop_backend: NoOpBackend):
    """Test workflow end tracking (no-op)."""
    workflow_id = make_workflow_id()

    # Should not raise any errors
    result = noop_backend.track_workflow_end(
        workflow_id=workflow_id,
        end_time=datetime.utcnow(),
        status="completed",
        error_message=None,
        error_stack_trace=None,
    )
    assert result is None


def test_track_workflow_end_with_error(noop_backend: NoOpBackend):
    """Test workflow end tracking with error (no-op)."""
    workflow_id = make_workflow_id()

    # Should not raise any errors even with error data
    result = noop_backend.track_workflow_end(
        workflow_id=workflow_id,
        end_time=datetime.utcnow(),
        status="failed",
        error_message="Test error",
        error_stack_trace="Traceback...",
    )
    assert result is None


def test_update_workflow_metrics(noop_backend: NoOpBackend):
    """Test workflow metrics update (no-op)."""
    workflow_id = make_workflow_id()

    # Should not raise any errors
    result = noop_backend.update_workflow_metrics(
        workflow_id=workflow_id,
        total_llm_calls=100,
        total_tool_calls=50,
        total_tokens=10000,
        total_cost_usd=1.50,
    )
    assert result is None


# ========== Stage Tracking Tests ==========


def test_track_stage_start(noop_backend: NoOpBackend):
    """Test stage start tracking (no-op)."""
    workflow_id = make_workflow_id()
    stage_id = make_stage_id()

    # Should not raise any errors
    result = noop_backend.track_stage_start(
        stage_id=stage_id,
        workflow_id=workflow_id,
        stage_name="analysis",
        stage_config={"stage": {"version": "1.0"}},
        start_time=datetime.utcnow(),
        input_data={"query": "test"},
    )
    assert result is None


def test_track_stage_end(noop_backend: NoOpBackend):
    """Test stage end tracking (no-op)."""
    stage_id = make_stage_id()

    # Should not raise any errors
    result = noop_backend.track_stage_end(
        stage_id=stage_id,
        end_time=datetime.utcnow(),
        status="completed",
        error_message=None,
        num_agents_executed=3,
        num_agents_succeeded=2,
        num_agents_failed=1,
    )
    assert result is None


def test_set_stage_output(noop_backend: NoOpBackend):
    """Test setting stage output (no-op)."""
    stage_id = make_stage_id()

    # Should not raise any errors
    result = noop_backend.set_stage_output(
        stage_id=stage_id, output_data={"result": "success", "score": 0.95}
    )
    assert result is None


# ========== Agent Tracking Tests ==========


def test_track_agent_start(noop_backend: NoOpBackend):
    """Test agent start tracking (no-op)."""
    stage_id = make_stage_id()
    agent_id = make_agent_id()

    # Should not raise any errors
    result = noop_backend.track_agent_start(
        agent_id=agent_id,
        stage_id=stage_id,
        agent_name="researcher",
        agent_config={"agent": {"version": "1.0"}},
        start_time=datetime.utcnow(),
        input_data={"task": "analyze"},
    )
    assert result is None


def test_track_agent_end(noop_backend: NoOpBackend):
    """Test agent end tracking (no-op)."""
    agent_id = make_agent_id()

    # Should not raise any errors
    result = noop_backend.track_agent_end(
        agent_id=agent_id,
        end_time=datetime.utcnow(),
        status="completed",
        error_message=None,
    )
    assert result is None


def test_track_agent_end_with_error(noop_backend: NoOpBackend):
    """Test agent end tracking with error (no-op)."""
    agent_id = make_agent_id()

    # Should not raise any errors
    result = noop_backend.track_agent_end(
        agent_id=agent_id,
        end_time=datetime.utcnow(),
        status="failed",
        error_message="Agent failed",
    )
    assert result is None


def test_set_agent_output(noop_backend: NoOpBackend):
    """Test setting agent output (no-op)."""
    agent_id = make_agent_id()

    # Should not raise any errors
    result = noop_backend.set_agent_output(
        agent_id=agent_id,
        output_data={"analysis": "complete"},
        reasoning="Based on data",
        confidence_score=0.9,
        total_tokens=500,
        prompt_tokens=300,
        completion_tokens=200,
        estimated_cost_usd=0.01,
        num_llm_calls=2,
        num_tool_calls=3,
    )
    assert result is None


def test_set_agent_output_minimal(noop_backend: NoOpBackend):
    """Test setting agent output with minimal data (no-op)."""
    agent_id = make_agent_id()

    # Should not raise any errors with minimal data
    result = noop_backend.set_agent_output(agent_id=agent_id, output_data={})
    assert result is None


# ========== LLM Call Tracking Tests ==========


def test_track_llm_call(noop_backend: NoOpBackend):
    """Test LLM call tracking (no-op)."""
    agent_id = make_agent_id()
    llm_call_id = f"llm-{uuid.uuid4().hex[:12]}"

    # Should not raise any errors
    result = noop_backend.track_llm_call(
        llm_call_id=llm_call_id,
        agent_id=agent_id,
        provider="openai",
        model="gpt-4",
        prompt="Analyze this text",
        response="Analysis complete",
        prompt_tokens=100,
        completion_tokens=200,
        latency_ms=1500,
        estimated_cost_usd=0.05,
        start_time=datetime.utcnow(),
        temperature=0.7,
        max_tokens=500,
        status="success",
        error_message=None,
    )
    assert result is None


def test_track_llm_call_with_error(noop_backend: NoOpBackend):
    """Test LLM call tracking with error (no-op)."""
    agent_id = make_agent_id()
    llm_call_id = f"llm-{uuid.uuid4().hex[:12]}"

    # Should not raise any errors
    result = noop_backend.track_llm_call(
        llm_call_id=llm_call_id,
        agent_id=agent_id,
        provider="openai",
        model="gpt-4",
        prompt="Test",
        response="",
        prompt_tokens=10,
        completion_tokens=0,
        latency_ms=500,
        estimated_cost_usd=0.0,
        start_time=datetime.utcnow(),
        status="failed",
        error_message="API timeout",
    )
    assert result is None


# ========== Tool Call Tracking Tests ==========


def test_track_tool_call(noop_backend: NoOpBackend):
    """Test tool call tracking (no-op)."""
    agent_id = make_agent_id()
    tool_id = f"tool-{uuid.uuid4().hex[:12]}"

    # Should not raise any errors
    result = noop_backend.track_tool_call(
        tool_execution_id=tool_id,
        agent_id=agent_id,
        tool_name="web_scraper",
        input_params={"url": "https://example.com"},
        output_data={"content": "scraped data"},
        start_time=datetime.utcnow(),
        duration_seconds=2.5,
        status="success",
        error_message=None,
        safety_checks=["url_validation", "content_filter"],
        approval_required=False,
    )
    assert result is None


def test_track_tool_call_with_error(noop_backend: NoOpBackend):
    """Test tool call tracking with error (no-op)."""
    agent_id = make_agent_id()
    tool_id = f"tool-{uuid.uuid4().hex[:12]}"

    # Should not raise any errors
    result = noop_backend.track_tool_call(
        tool_execution_id=tool_id,
        agent_id=agent_id,
        tool_name="database_query",
        input_params={"query": "SELECT *"},
        output_data={},
        start_time=datetime.utcnow(),
        duration_seconds=1.0,
        status="failed",
        error_message="Connection timeout",
        safety_checks=["sql_injection_check"],
        approval_required=True,
    )
    assert result is None


# ========== Safety and Collaboration Tests ==========


def test_track_safety_violation(noop_backend: NoOpBackend):
    """Test safety violation tracking (no-op)."""
    # Should not raise any errors
    result = noop_backend.track_safety_violation(
        workflow_id=make_workflow_id(),
        stage_id=make_stage_id(),
        agent_id=make_agent_id(),
        violation_severity="CRITICAL",
        violation_message="Dangerous action attempted",
        policy_name="security_policy",
        service_name="action_validator",
        context={"action": "delete_all", "resource": "database"},
        timestamp=datetime.utcnow(),
    )
    assert result is None


def test_track_safety_violation_minimal(noop_backend: NoOpBackend):
    """Test safety violation tracking with minimal data (no-op)."""
    # Should not raise any errors
    result = noop_backend.track_safety_violation(
        workflow_id=None,
        stage_id=None,
        agent_id=None,
        violation_severity="LOW",
        violation_message="Minor issue",
        policy_name="basic_policy",
    )
    assert result is None


def test_track_collaboration_event(noop_backend: NoOpBackend):
    """Test collaboration event tracking (no-op)."""
    stage_id = make_stage_id()
    agent1_id = make_agent_id()
    agent2_id = make_agent_id()

    # Should return empty string
    event_id = noop_backend.track_collaboration_event(
        stage_id=stage_id,
        event_type="vote",
        agents_involved=[agent1_id, agent2_id],
        event_data={"votes": {"option_a": 2}},
        round_number=1,
        resolution_strategy="majority",
        outcome="consensus",
        confidence_score=0.95,
        extra_metadata={"key": "value"},
        timestamp=datetime.utcnow(),
    )

    assert event_id == ""


def test_track_collaboration_event_minimal(noop_backend: NoOpBackend):
    """Test collaboration event tracking with minimal data (no-op)."""
    stage_id = make_stage_id()

    # Should return empty string
    event_id = noop_backend.track_collaboration_event(
        stage_id=stage_id, event_type="conflict", agents_involved=[]
    )

    assert event_id == ""


# ========== Context Management Tests ==========


def test_get_session_context(noop_backend: NoOpBackend):
    """Test session context manager (no-op)."""
    with noop_backend.get_session_context() as context:
        assert context is None


def test_get_session_context_nested(noop_backend: NoOpBackend):
    """Test nested session contexts (no-op)."""
    with noop_backend.get_session_context() as ctx1:
        assert ctx1 is None
        with noop_backend.get_session_context() as ctx2:
            assert ctx2 is None


# ========== Maintenance Tests ==========


def test_cleanup_old_records(noop_backend: NoOpBackend):
    """Test cleanup (no-op, returns empty dict)."""
    result = noop_backend.cleanup_old_records(retention_days=30)

    assert isinstance(result, dict)
    assert len(result) == 0


def test_cleanup_old_records_dry_run(noop_backend: NoOpBackend):
    """Test cleanup dry run (no-op, returns empty dict)."""
    result = noop_backend.cleanup_old_records(retention_days=30, dry_run=True)

    assert isinstance(result, dict)
    assert len(result) == 0


def test_cleanup_old_records_various_retention(noop_backend: NoOpBackend):
    """Test cleanup with various retention periods (all no-op)."""
    for retention in [1, 7, 30, 90, 365]:
        result = noop_backend.cleanup_old_records(retention_days=retention)
        assert isinstance(result, dict)
        assert len(result) == 0


def test_get_stats(noop_backend: NoOpBackend):
    """Test getting backend stats."""
    stats = noop_backend.get_stats()

    assert stats is not None
    assert stats["backend_type"] == "noop"
    assert len(stats) == 1  # Only backend_type


# ========== Performance Tests ==========


def test_high_volume_operations(noop_backend: NoOpBackend):
    """Test that NoOp backend handles high volume without issues."""
    import time

    # Should execute very quickly since it's all no-ops
    start = time.time()
    for i in range(1000):
        workflow_id = f"wf-{i}"
        noop_backend.track_workflow_start(
            workflow_id=workflow_id,
            workflow_name=f"workflow_{i}",
            workflow_config={},
            start_time=datetime.utcnow(),
        )
        noop_backend.track_workflow_end(
            workflow_id=workflow_id, end_time=datetime.utcnow(), status="completed"
        )
    duration = time.time() - start

    # NoOp backend should complete 1000 operations very quickly
    assert duration < 1.0


def test_concurrent_operations(noop_backend: NoOpBackend):
    """Test multiple operations without any state issues."""
    import time

    # Since it's stateless, all operations should be independent
    workflow_ids = [make_workflow_id() for _ in range(10)]

    start = time.time()
    for wf_id in workflow_ids:
        noop_backend.track_workflow_start(
            workflow_id=wf_id,
            workflow_name="test",
            workflow_config={},
            start_time=datetime.utcnow(),
        )

    for wf_id in workflow_ids:
        noop_backend.track_workflow_end(
            workflow_id=wf_id, end_time=datetime.utcnow(), status="completed"
        )
    duration = time.time() - start

    # NoOp backend should complete all concurrent operations very quickly
    assert duration < 1.0


# ========== Full Lifecycle Test ==========


def test_full_workflow_lifecycle(noop_backend: NoOpBackend):
    """Test complete workflow lifecycle (all no-ops should work)."""
    workflow_id = make_workflow_id()
    stage_id = make_stage_id()
    agent_id = make_agent_id()
    llm_call_id = f"llm-{uuid.uuid4().hex[:12]}"
    tool_id = f"tool-{uuid.uuid4().hex[:12]}"

    # All operations should complete without errors
    noop_backend.track_workflow_start(
        workflow_id=workflow_id,
        workflow_name="full_test",
        workflow_config={},
        start_time=datetime.utcnow(),
    )

    noop_backend.track_stage_start(
        stage_id=stage_id,
        workflow_id=workflow_id,
        stage_name="analysis",
        stage_config={},
        start_time=datetime.utcnow(),
    )

    noop_backend.track_agent_start(
        agent_id=agent_id,
        stage_id=stage_id,
        agent_name="researcher",
        agent_config={},
        start_time=datetime.utcnow(),
    )

    noop_backend.track_llm_call(
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
    )

    noop_backend.track_tool_call(
        tool_execution_id=tool_id,
        agent_id=agent_id,
        tool_name="calculator",
        input_params={},
        output_data={},
        start_time=datetime.utcnow(),
        duration_seconds=0.1,
    )

    noop_backend.set_agent_output(agent_id=agent_id, output_data={"result": "done"})

    noop_backend.track_agent_end(
        agent_id=agent_id, end_time=datetime.utcnow(), status="completed"
    )

    noop_backend.set_stage_output(
        stage_id=stage_id, output_data={"stage_result": "done"}
    )

    noop_backend.track_stage_end(
        stage_id=stage_id, end_time=datetime.utcnow(), status="completed"
    )

    noop_backend.update_workflow_metrics(
        workflow_id=workflow_id,
        total_llm_calls=1,
        total_tool_calls=1,
        total_tokens=30,
        total_cost_usd=0.001,
    )

    noop_backend.track_workflow_end(
        workflow_id=workflow_id, end_time=datetime.utcnow(), status="completed"
    )

    # Verify backend still reports consistent stats after full lifecycle
    stats = noop_backend.get_stats()
    assert stats["backend_type"] == "noop"


# ========== Null Object Pattern Compliance ==========


def test_null_object_pattern_no_exceptions():
    """Test that NoOp backend never raises exceptions."""
    backend = NoOpBackend()

    # Try to cause errors with invalid data
    backend.track_workflow_start(
        workflow_id="",
        workflow_name="",
        workflow_config={},
        start_time=datetime.utcnow(),
    )

    backend.track_workflow_end(
        workflow_id="nonexistent", end_time=datetime.utcnow(), status="completed"
    )

    # Verify stats still work after invalid data (null object contract)
    stats = backend.get_stats()
    assert stats["backend_type"] == "noop"


def test_idempotency():
    """Test that repeated operations are idempotent."""
    backend = NoOpBackend()
    workflow_id = make_workflow_id()

    stats_before = backend.get_stats()

    # Call the same operation multiple times
    for _ in range(5):
        backend.track_workflow_start(
            workflow_id=workflow_id,
            workflow_name="test",
            workflow_config={},
            start_time=datetime.utcnow(),
        )

    # Stats should remain stable after repeated calls
    stats_after = backend.get_stats()
    assert stats_before == stats_after
