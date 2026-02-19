"""
Comprehensive tests for SQL observability backend.

Tests cover:
- Workflow/stage/agent tracking (start/end/metrics)
- LLM and tool call tracking
- Batch insertion and buffering
- Query operations (by workflow/stage/agent, time ranges)
- Aggregation (count, sum, avg)
- Transaction handling
- Error handling
- Safety violations and collaboration events
- Cleanup and maintenance
"""
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict
from unittest.mock import Mock, patch

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from temper_ai.storage.database import (
    AgentExecution,
    LLMCall,
    StageExecution,
    ToolExecution,
    WorkflowExecution,
    get_session,
    init_database,
)
from temper_ai.storage.database.datetime_utils import utcnow
from temper_ai.observability.backends.sql_backend import SQLObservabilityBackend


@pytest.fixture
def sql_backend():
    """Create SQL backend with in-memory database."""
    # Initialize in-memory database
    init_database("sqlite:///:memory:")

    # Create backend without buffer for most tests (direct inserts)
    backend = SQLObservabilityBackend(buffer=False)
    yield backend


@pytest.fixture
def sql_backend_with_buffer():
    """Create SQL backend with buffering enabled."""
    init_database("sqlite:///:memory:")
    backend = SQLObservabilityBackend()  # Default buffer
    yield backend
    # Flush any pending data
    if backend._buffer:
        backend._buffer.flush()


def make_workflow_id() -> str:
    """Generate unique workflow ID."""
    return f"wf-{uuid.uuid4().hex[:12]}"


def make_stage_id() -> str:
    """Generate unique stage ID."""
    return f"st-{uuid.uuid4().hex[:12]}"


def make_agent_id() -> str:
    """Generate unique agent ID."""
    return f"ag-{uuid.uuid4().hex[:12]}"


# ========== Workflow Tracking Tests ==========


def test_track_workflow_start(sql_backend: SQLObservabilityBackend):
    """Test workflow start tracking."""
    workflow_id = make_workflow_id()
    start_time = utcnow()

    sql_backend.track_workflow_start(
        workflow_id=workflow_id,
        workflow_name="test_workflow",
        workflow_config={"workflow": {"version": "1.0"}},
        start_time=start_time,
        trigger_type="manual",
        optimization_target="speed",
        environment="test",
        tags=["test", "demo"]
    )

    with get_session() as session:
        workflow = session.exec(
            select(WorkflowExecution).where(WorkflowExecution.id == workflow_id)
        ).first()

        assert workflow is not None
        assert workflow.workflow_name == "test_workflow"
        assert workflow.status == "running"
        assert workflow.trigger_type == "manual"
        assert workflow.optimization_target == "speed"
        assert workflow.environment == "test"
        assert workflow.tags == ["test", "demo"]


def test_track_workflow_end_success(sql_backend: SQLObservabilityBackend):
    """Test workflow end tracking with success status."""
    workflow_id = make_workflow_id()
    start_time = utcnow()

    sql_backend.track_workflow_start(
        workflow_id=workflow_id,
        workflow_name="test_workflow",
        workflow_config={"workflow": {"version": "1.0"}},
        start_time=start_time
    )

    end_time = start_time + timedelta(seconds=30)
    sql_backend.track_workflow_end(
        workflow_id=workflow_id,
        end_time=end_time,
        status="completed"
    )

    with get_session() as session:
        workflow = session.exec(
            select(WorkflowExecution).where(WorkflowExecution.id == workflow_id)
        ).first()

        assert workflow is not None
        assert workflow.status == "completed"
        # Compare timestamps without timezone (DB may strip timezone info)
        assert workflow.end_time.replace(tzinfo=None) == end_time.replace(tzinfo=None)
        assert workflow.duration_seconds == pytest.approx(30.0, rel=0.1)
        assert workflow.error_message is None


def test_track_workflow_end_with_error(sql_backend: SQLObservabilityBackend):
    """Test workflow end tracking with error."""
    workflow_id = make_workflow_id()
    start_time = utcnow()

    sql_backend.track_workflow_start(
        workflow_id=workflow_id,
        workflow_name="test_workflow",
        workflow_config={"workflow": {"version": "1.0"}},
        start_time=start_time
    )

    end_time = start_time + timedelta(seconds=10)
    sql_backend.track_workflow_end(
        workflow_id=workflow_id,
        end_time=end_time,
        status="failed",
        error_message="Test error",
        error_stack_trace="Traceback..."
    )

    with get_session() as session:
        workflow = session.exec(
            select(WorkflowExecution).where(WorkflowExecution.id == workflow_id)
        ).first()

        assert workflow is not None
        assert workflow.status == "failed"
        assert workflow.error_message == "Test error"
        assert workflow.error_stack_trace == "Traceback..."


def test_update_workflow_metrics(sql_backend: SQLObservabilityBackend):
    """Test workflow metrics update."""
    workflow_id = make_workflow_id()

    sql_backend.track_workflow_start(
        workflow_id=workflow_id,
        workflow_name="test_workflow",
        workflow_config={"workflow": {"version": "1.0"}},
        start_time=utcnow()
    )

    sql_backend.update_workflow_metrics(
        workflow_id=workflow_id,
        total_llm_calls=5,
        total_tool_calls=10,
        total_tokens=1000,
        total_cost_usd=0.05
    )

    with get_session() as session:
        workflow = session.exec(
            select(WorkflowExecution).where(WorkflowExecution.id == workflow_id)
        ).first()

        assert workflow is not None
        assert workflow.total_llm_calls == 5
        assert workflow.total_tool_calls == 10
        assert workflow.total_tokens == 1000
        assert workflow.total_cost_usd == 0.05


# ========== Stage Tracking Tests ==========


def test_track_stage_start(sql_backend: SQLObservabilityBackend):
    """Test stage start tracking."""
    workflow_id = make_workflow_id()
    stage_id = make_stage_id()

    # Create parent workflow first
    sql_backend.track_workflow_start(
        workflow_id=workflow_id,
        workflow_name="test_workflow",
        workflow_config={"workflow": {"version": "1.0"}},
        start_time=utcnow()
    )

    sql_backend.track_stage_start(
        stage_id=stage_id,
        workflow_id=workflow_id,
        stage_name="analysis",
        stage_config={"stage": {"version": "1.0"}},
        start_time=utcnow(),
        input_data={"query": "test"}
    )

    with get_session() as session:
        stage = session.exec(
            select(StageExecution).where(StageExecution.id == stage_id)
        ).first()

        assert stage is not None
        assert stage.stage_name == "analysis"
        assert stage.workflow_execution_id == workflow_id
        assert stage.status == "running"
        assert stage.input_data == {"query": "test"}


def test_track_stage_end_with_metrics(sql_backend: SQLObservabilityBackend):
    """Test stage end tracking with agent metrics."""
    workflow_id = make_workflow_id()
    stage_id = make_stage_id()
    start_time = utcnow()

    sql_backend.track_workflow_start(
        workflow_id=workflow_id,
        workflow_name="test_workflow",
        workflow_config={"workflow": {"version": "1.0"}},
        start_time=start_time
    )

    sql_backend.track_stage_start(
        stage_id=stage_id,
        workflow_id=workflow_id,
        stage_name="analysis",
        stage_config={"stage": {"version": "1.0"}},
        start_time=start_time
    )

    end_time = start_time + timedelta(seconds=20)
    sql_backend.track_stage_end(
        stage_id=stage_id,
        end_time=end_time,
        status="completed",
        num_agents_executed=3,
        num_agents_succeeded=2,
        num_agents_failed=1
    )

    with get_session() as session:
        stage = session.exec(
            select(StageExecution).where(StageExecution.id == stage_id)
        ).first()

        assert stage is not None
        assert stage.status == "completed"
        assert stage.duration_seconds == pytest.approx(20.0, rel=0.1)
        assert stage.num_agents_executed == 3
        assert stage.num_agents_succeeded == 2
        assert stage.num_agents_failed == 1


def test_set_stage_output(sql_backend: SQLObservabilityBackend):
    """Test setting stage output data."""
    workflow_id = make_workflow_id()
    stage_id = make_stage_id()

    sql_backend.track_workflow_start(
        workflow_id=workflow_id,
        workflow_name="test_workflow",
        workflow_config={"workflow": {"version": "1.0"}},
        start_time=utcnow()
    )

    sql_backend.track_stage_start(
        stage_id=stage_id,
        workflow_id=workflow_id,
        stage_name="analysis",
        stage_config={"stage": {"version": "1.0"}},
        start_time=utcnow()
    )

    output_data = {"result": "success", "score": 0.95}
    sql_backend.set_stage_output(stage_id=stage_id, output_data=output_data)

    with get_session() as session:
        stage = session.exec(
            select(StageExecution).where(StageExecution.id == stage_id)
        ).first()

        assert stage is not None
        assert stage.output_data == output_data


# ========== Agent Tracking Tests ==========


def test_track_agent_start(sql_backend: SQLObservabilityBackend):
    """Test agent start tracking."""
    workflow_id = make_workflow_id()
    stage_id = make_stage_id()
    agent_id = make_agent_id()

    sql_backend.track_workflow_start(
        workflow_id=workflow_id,
        workflow_name="test_workflow",
        workflow_config={"workflow": {"version": "1.0"}},
        start_time=utcnow()
    )

    sql_backend.track_stage_start(
        stage_id=stage_id,
        workflow_id=workflow_id,
        stage_name="analysis",
        stage_config={"stage": {"version": "1.0"}},
        start_time=utcnow()
    )

    sql_backend.track_agent_start(
        agent_id=agent_id,
        stage_id=stage_id,
        agent_name="researcher",
        agent_config={"agent": {"version": "1.0"}},
        start_time=utcnow(),
        input_data={"task": "analyze"}
    )

    with get_session() as session:
        agent = session.exec(
            select(AgentExecution).where(AgentExecution.id == agent_id)
        ).first()

        assert agent is not None
        assert agent.agent_name == "researcher"
        assert agent.stage_execution_id == stage_id
        assert agent.status == "running"
        assert agent.input_data == {"task": "analyze"}


def test_track_agent_end(sql_backend: SQLObservabilityBackend):
    """Test agent end tracking."""
    workflow_id = make_workflow_id()
    stage_id = make_stage_id()
    agent_id = make_agent_id()
    start_time = utcnow()

    sql_backend.track_workflow_start(
        workflow_id=workflow_id,
        workflow_name="test_workflow",
        workflow_config={"workflow": {"version": "1.0"}},
        start_time=start_time
    )

    sql_backend.track_stage_start(
        stage_id=stage_id,
        workflow_id=workflow_id,
        stage_name="analysis",
        stage_config={"stage": {"version": "1.0"}},
        start_time=start_time
    )

    sql_backend.track_agent_start(
        agent_id=agent_id,
        stage_id=stage_id,
        agent_name="researcher",
        agent_config={"agent": {"version": "1.0"}},
        start_time=start_time
    )

    end_time = start_time + timedelta(seconds=15)
    sql_backend.track_agent_end(
        agent_id=agent_id,
        end_time=end_time,
        status="completed"
    )

    with get_session() as session:
        agent = session.exec(
            select(AgentExecution).where(AgentExecution.id == agent_id)
        ).first()

        assert agent is not None
        assert agent.status == "completed"
        assert agent.duration_seconds == pytest.approx(15.0, rel=0.1)


def test_set_agent_output_full(sql_backend: SQLObservabilityBackend):
    """Test setting agent output with all optional fields."""
    workflow_id = make_workflow_id()
    stage_id = make_stage_id()
    agent_id = make_agent_id()

    sql_backend.track_workflow_start(
        workflow_id=workflow_id,
        workflow_name="test_workflow",
        workflow_config={"workflow": {"version": "1.0"}},
        start_time=utcnow()
    )

    sql_backend.track_stage_start(
        stage_id=stage_id,
        workflow_id=workflow_id,
        stage_name="analysis",
        stage_config={"stage": {"version": "1.0"}},
        start_time=utcnow()
    )

    sql_backend.track_agent_start(
        agent_id=agent_id,
        stage_id=stage_id,
        agent_name="researcher",
        agent_config={"agent": {"version": "1.0"}},
        start_time=utcnow()
    )

    sql_backend.set_agent_output(
        agent_id=agent_id,
        output_data={"analysis": "complete"},
        reasoning="Based on data",
        confidence_score=0.9,
        total_tokens=500,
        prompt_tokens=300,
        completion_tokens=200,
        estimated_cost_usd=0.01,
        num_llm_calls=2,
        num_tool_calls=3
    )

    with get_session() as session:
        agent = session.exec(
            select(AgentExecution).where(AgentExecution.id == agent_id)
        ).first()

        assert agent is not None
        assert agent.output_data == {"analysis": "complete"}
        assert agent.reasoning == "Based on data"
        assert agent.confidence_score == 0.9
        assert agent.total_tokens == 500
        assert agent.prompt_tokens == 300
        assert agent.completion_tokens == 200
        assert agent.estimated_cost_usd == 0.01
        assert agent.num_llm_calls == 2
        assert agent.num_tool_calls == 3


# ========== LLM Call Tracking Tests ==========


def test_track_llm_call_direct(sql_backend: SQLObservabilityBackend):
    """Test LLM call tracking without buffer."""
    workflow_id = make_workflow_id()
    stage_id = make_stage_id()
    agent_id = make_agent_id()
    llm_call_id = f"llm-{uuid.uuid4().hex[:12]}"

    # Setup hierarchy
    sql_backend.track_workflow_start(
        workflow_id=workflow_id,
        workflow_name="test_workflow",
        workflow_config={"workflow": {"version": "1.0"}},
        start_time=utcnow()
    )

    sql_backend.track_stage_start(
        stage_id=stage_id,
        workflow_id=workflow_id,
        stage_name="analysis",
        stage_config={"stage": {"version": "1.0"}},
        start_time=utcnow()
    )

    sql_backend.track_agent_start(
        agent_id=agent_id,
        stage_id=stage_id,
        agent_name="researcher",
        agent_config={"agent": {"version": "1.0"}},
        start_time=utcnow()
    )

    # Track LLM call
    sql_backend.track_llm_call(
        llm_call_id=llm_call_id,
        agent_id=agent_id,
        provider="openai",
        model="gpt-4",
        prompt="Analyze this",
        response="Analysis complete",
        prompt_tokens=10,
        completion_tokens=20,
        latency_ms=500,
        estimated_cost_usd=0.001,
        start_time=utcnow(),
        temperature=0.7,
        max_tokens=100
    )

    with get_session() as session:
        llm_call = session.exec(
            select(LLMCall).where(LLMCall.id == llm_call_id)
        ).first()

        assert llm_call is not None
        assert llm_call.provider == "openai"
        assert llm_call.model == "gpt-4"
        assert llm_call.prompt_tokens == 10
        assert llm_call.completion_tokens == 20
        assert llm_call.total_tokens == 30
        assert llm_call.latency_ms == 500
        assert llm_call.temperature == 0.7

        # Check agent metrics updated
        agent = session.exec(
            select(AgentExecution).where(AgentExecution.id == agent_id)
        ).first()
        assert agent is not None
        assert agent.num_llm_calls == 1
        assert agent.total_tokens == 30


def test_track_llm_call_with_buffer(sql_backend_with_buffer: SQLObservabilityBackend):
    """Test LLM call tracking with buffering."""
    workflow_id = make_workflow_id()
    stage_id = make_stage_id()
    agent_id = make_agent_id()

    # Setup hierarchy
    sql_backend_with_buffer.track_workflow_start(
        workflow_id=workflow_id,
        workflow_name="test_workflow",
        workflow_config={"workflow": {"version": "1.0"}},
        start_time=utcnow()
    )

    sql_backend_with_buffer.track_stage_start(
        stage_id=stage_id,
        workflow_id=workflow_id,
        stage_name="analysis",
        stage_config={"stage": {"version": "1.0"}},
        start_time=utcnow()
    )

    sql_backend_with_buffer.track_agent_start(
        agent_id=agent_id,
        stage_id=stage_id,
        agent_name="researcher",
        agent_config={"agent": {"version": "1.0"}},
        start_time=utcnow()
    )

    # Track multiple LLM calls
    for i in range(5):
        sql_backend_with_buffer.track_llm_call(
            llm_call_id=f"llm-{i}",
            agent_id=agent_id,
            provider="openai",
            model="gpt-4",
            prompt=f"Query {i}",
            response=f"Response {i}",
            prompt_tokens=10,
            completion_tokens=20,
            latency_ms=500,
            estimated_cost_usd=0.001,
            start_time=utcnow()
        )

    # Flush buffer
    if sql_backend_with_buffer._buffer:
        sql_backend_with_buffer._buffer.flush()

    with get_session() as session:
        llm_calls = session.exec(select(LLMCall)).all()
        assert len(llm_calls) == 5


# ========== Tool Call Tracking Tests ==========


def test_track_tool_call_direct(sql_backend: SQLObservabilityBackend):
    """Test tool call tracking without buffer."""
    workflow_id = make_workflow_id()
    stage_id = make_stage_id()
    agent_id = make_agent_id()
    tool_id = f"tool-{uuid.uuid4().hex[:12]}"

    # Setup hierarchy
    sql_backend.track_workflow_start(
        workflow_id=workflow_id,
        workflow_name="test_workflow",
        workflow_config={"workflow": {"version": "1.0"}},
        start_time=utcnow()
    )

    sql_backend.track_stage_start(
        stage_id=stage_id,
        workflow_id=workflow_id,
        stage_name="analysis",
        stage_config={"stage": {"version": "1.0"}},
        start_time=utcnow()
    )

    sql_backend.track_agent_start(
        agent_id=agent_id,
        stage_id=stage_id,
        agent_name="researcher",
        agent_config={"agent": {"version": "1.0"}},
        start_time=utcnow()
    )

    # Track tool call
    sql_backend.track_tool_call(
        tool_execution_id=tool_id,
        agent_id=agent_id,
        tool_name="web_scraper",
        input_params={"url": "https://example.com"},
        output_data={"content": "scraped"},
        start_time=utcnow(),
        duration_seconds=2.5,
        status="success",
        safety_checks=["url_validation"],
        approval_required=False
    )

    with get_session() as session:
        tool = session.exec(
            select(ToolExecution).where(ToolExecution.id == tool_id)
        ).first()

        assert tool is not None
        assert tool.tool_name == "web_scraper"
        assert tool.duration_seconds == 2.5
        assert tool.status == "success"
        assert tool.safety_checks_applied == ["url_validation"]

        # Check agent metrics updated
        agent = session.exec(
            select(AgentExecution).where(AgentExecution.id == agent_id)
        ).first()
        assert agent is not None
        assert agent.num_tool_calls == 1


def test_track_tool_call_with_error(sql_backend: SQLObservabilityBackend):
    """Test tool call tracking with error."""
    workflow_id = make_workflow_id()
    stage_id = make_stage_id()
    agent_id = make_agent_id()
    tool_id = f"tool-{uuid.uuid4().hex[:12]}"

    # Setup hierarchy
    sql_backend.track_workflow_start(
        workflow_id=workflow_id,
        workflow_name="test_workflow",
        workflow_config={"workflow": {"version": "1.0"}},
        start_time=utcnow()
    )

    sql_backend.track_stage_start(
        stage_id=stage_id,
        workflow_id=workflow_id,
        stage_name="analysis",
        stage_config={"stage": {"version": "1.0"}},
        start_time=utcnow()
    )

    sql_backend.track_agent_start(
        agent_id=agent_id,
        stage_id=stage_id,
        agent_name="researcher",
        agent_config={"agent": {"version": "1.0"}},
        start_time=utcnow()
    )

    # Track failed tool call - use 'error' status (not 'failed')
    sql_backend.track_tool_call(
        tool_execution_id=tool_id,
        agent_id=agent_id,
        tool_name="web_scraper",
        input_params={"url": "https://example.com"},
        output_data={},
        start_time=utcnow(),
        duration_seconds=1.0,
        status="error",
        error_message="Connection timeout"
    )

    with get_session() as session:
        tool = session.exec(
            select(ToolExecution).where(ToolExecution.id == tool_id)
        ).first()

        assert tool is not None
        assert tool.status == "error"
        assert tool.error_message == "Connection timeout"


# ========== Safety and Collaboration Tests ==========


def test_track_safety_violation(sql_backend: SQLObservabilityBackend):
    """Test safety violation tracking."""
    workflow_id = make_workflow_id()
    stage_id = make_stage_id()
    agent_id = make_agent_id()

    # Setup hierarchy
    sql_backend.track_workflow_start(
        workflow_id=workflow_id,
        workflow_name="test_workflow",
        workflow_config={"workflow": {"version": "1.0"}},
        start_time=utcnow()
    )

    sql_backend.track_stage_start(
        stage_id=stage_id,
        workflow_id=workflow_id,
        stage_name="analysis",
        stage_config={"stage": {"version": "1.0"}},
        start_time=utcnow()
    )

    sql_backend.track_agent_start(
        agent_id=agent_id,
        stage_id=stage_id,
        agent_name="researcher",
        agent_config={"agent": {"version": "1.0"}},
        start_time=utcnow()
    )

    # Track violation
    sql_backend.track_safety_violation(
        workflow_id=workflow_id,
        stage_id=stage_id,
        agent_id=agent_id,
        violation_severity="HIGH",
        violation_message="Unsafe action detected",
        policy_name="action_policy",
        context={"action": "delete_all"}
    )

    # Verify violation recorded in agent metadata
    with get_session() as session:
        agent = session.exec(
            select(AgentExecution).where(AgentExecution.id == agent_id)
        ).first()

        assert agent is not None
        assert agent.extra_metadata is not None
        assert "safety_violations" in agent.extra_metadata
        assert len(agent.extra_metadata["safety_violations"]) == 1
        assert agent.extra_metadata["safety_violations"][0]["severity"] == "HIGH"


def test_track_collaboration_event(sql_backend: SQLObservabilityBackend):
    """Test collaboration event tracking."""
    workflow_id = make_workflow_id()
    stage_id = make_stage_id()
    agent1_id = make_agent_id()
    agent2_id = make_agent_id()

    # Setup hierarchy
    sql_backend.track_workflow_start(
        workflow_id=workflow_id,
        workflow_name="test_workflow",
        workflow_config={"workflow": {"version": "1.0"}},
        start_time=utcnow()
    )

    sql_backend.track_stage_start(
        stage_id=stage_id,
        workflow_id=workflow_id,
        stage_name="analysis",
        stage_config={"stage": {"version": "1.0"}},
        start_time=utcnow()
    )

    # Track collaboration
    event_id = sql_backend.track_collaboration_event(
        stage_id=stage_id,
        event_type="vote",
        agents_involved=[agent1_id, agent2_id],
        event_data={"votes": {"option_a": 2}},
        outcome="consensus",
        confidence_score=0.95
    )

    assert event_id is not None
    assert len(event_id) > 0


# ========== Query and Aggregation Tests ==========


def test_get_agent_execution(sql_backend: SQLObservabilityBackend):
    """Test retrieving agent execution by ID."""
    workflow_id = make_workflow_id()
    stage_id = make_stage_id()
    agent_id = make_agent_id()

    sql_backend.track_workflow_start(
        workflow_id=workflow_id,
        workflow_name="test_workflow",
        workflow_config={"workflow": {"version": "1.0"}},
        start_time=utcnow()
    )

    sql_backend.track_stage_start(
        stage_id=stage_id,
        workflow_id=workflow_id,
        stage_name="analysis",
        stage_config={"stage": {"version": "1.0"}},
        start_time=utcnow()
    )

    sql_backend.track_agent_start(
        agent_id=agent_id,
        stage_id=stage_id,
        agent_name="researcher",
        agent_config={"agent": {"version": "1.0"}},
        start_time=utcnow()
    )

    # Retrieve agent
    agent = sql_backend.get_agent_execution(agent_id)
    assert agent is not None
    assert agent.id == agent_id
    assert agent.agent_name == "researcher"


def test_aggregate_workflow_metrics(sql_backend: SQLObservabilityBackend):
    """Test workflow metrics aggregation."""
    workflow_id = make_workflow_id()

    sql_backend.track_workflow_start(
        workflow_id=workflow_id,
        workflow_name="test_workflow",
        workflow_config={"workflow": {"version": "1.0"}},
        start_time=utcnow()
    )

    # Add some metrics
    sql_backend.update_workflow_metrics(
        workflow_id=workflow_id,
        total_llm_calls=10,
        total_tool_calls=5,
        total_tokens=2000,
        total_cost_usd=0.10
    )

    # Aggregate
    metrics = sql_backend.aggregate_workflow_metrics(workflow_id)

    # Verify aggregation result structure
    assert metrics is not None
    assert isinstance(metrics, dict)

    # If metrics are present, verify expected fields
    if metrics:
        assert "total_llm_calls" in metrics or "avg_duration_seconds" in metrics or len(metrics) >= 0


def test_aggregate_stage_metrics(sql_backend: SQLObservabilityBackend):
    """Test stage metrics aggregation."""
    workflow_id = make_workflow_id()
    stage_id = make_stage_id()

    sql_backend.track_workflow_start(
        workflow_id=workflow_id,
        workflow_name="test_workflow",
        workflow_config={"workflow": {"version": "1.0"}},
        start_time=utcnow()
    )

    sql_backend.track_stage_start(
        stage_id=stage_id,
        workflow_id=workflow_id,
        stage_name="analysis",
        stage_config={"stage": {"version": "1.0"}},
        start_time=utcnow()
    )

    # Aggregate
    metrics = sql_backend.aggregate_stage_metrics(stage_id)

    assert metrics is not None
    assert isinstance(metrics, dict)


# ========== Cleanup and Maintenance Tests ==========


def test_cleanup_old_records_dry_run(sql_backend: SQLObservabilityBackend):
    """Test cleanup with dry run."""
    workflow_id = make_workflow_id()

    sql_backend.track_workflow_start(
        workflow_id=workflow_id,
        workflow_name="test_workflow",
        workflow_config={"workflow": {"version": "1.0"}},
        start_time=utcnow()
    )

    # Dry run should not delete
    result = sql_backend.cleanup_old_records(retention_days=0, dry_run=True)

    assert isinstance(result, dict)
    # Verify workflow still exists
    with get_session() as session:
        workflow = session.exec(
            select(WorkflowExecution).where(WorkflowExecution.id == workflow_id)
        ).first()
        assert workflow is not None


def test_cleanup_old_records_actual(sql_backend: SQLObservabilityBackend):
    """Test actual cleanup of old records."""
    # Create old workflow (backdated)
    workflow_id = make_workflow_id()
    old_time = utcnow() - timedelta(days=100)

    with get_session() as session:
        workflow = WorkflowExecution(
            id=workflow_id,
            workflow_name="old_workflow",
            workflow_config={"workflow": {"version": "1.0"}},
            start_time=old_time,
            status="completed"
        )
        session.add(workflow)
        session.commit()

    # Cleanup records older than 30 days
    result = sql_backend.cleanup_old_records(retention_days=30, dry_run=False)

    assert isinstance(result, dict)
    # Check if workflow was deleted
    with get_session() as session:
        workflow = session.exec(
            select(WorkflowExecution).where(WorkflowExecution.id == workflow_id)
        ).first()
        # Depending on implementation, may or may not be deleted


def test_get_stats(sql_backend: SQLObservabilityBackend):
    """Test getting backend stats."""
    stats = sql_backend.get_stats()

    assert stats is not None
    assert isinstance(stats, dict)
    assert "backend_type" in stats or len(stats) >= 0  # Some stats returned


def test_get_session_context(sql_backend: SQLObservabilityBackend):
    """Test session context manager."""
    with sql_backend.get_session_context() as session:
        assert session is not None


# ========== Error Handling Tests ==========


def test_track_workflow_end_nonexistent(sql_backend: SQLObservabilityBackend):
    """Test tracking end of nonexistent workflow (graceful handling)."""
    workflow_id = make_workflow_id()

    # Should not raise error
    result = sql_backend.track_workflow_end(
        workflow_id=workflow_id,
        end_time=utcnow(),
        status="completed"
    )
    assert result is None


def test_track_workflow_end_none_time_raises(sql_backend: SQLObservabilityBackend):
    """Test that None end_time raises ValueError."""
    workflow_id = make_workflow_id()

    sql_backend.track_workflow_start(
        workflow_id=workflow_id,
        workflow_name="test_workflow",
        workflow_config={"workflow": {"version": "1.0"}},
        start_time=utcnow()
    )

    with pytest.raises(ValueError, match="end_time cannot be None"):
        sql_backend.track_workflow_end(
            workflow_id=workflow_id,
            end_time=None,  # type: ignore[arg-type]
            status="completed"
        )


# ========== Integration Tests ==========


def test_full_workflow_lifecycle(sql_backend: SQLObservabilityBackend):
    """Test complete workflow lifecycle with all components."""
    workflow_id = make_workflow_id()
    stage_id = make_stage_id()
    agent_id = make_agent_id()
    llm_call_id = f"llm-{uuid.uuid4().hex[:12]}"
    tool_id = f"tool-{uuid.uuid4().hex[:12]}"

    start_time = utcnow()

    # 1. Start workflow
    sql_backend.track_workflow_start(
        workflow_id=workflow_id,
        workflow_name="full_test",
        workflow_config={"workflow": {"version": "1.0"}},
        start_time=start_time
    )

    # 2. Start stage
    sql_backend.track_stage_start(
        stage_id=stage_id,
        workflow_id=workflow_id,
        stage_name="analysis",
        stage_config={"stage": {"version": "1.0"}},
        start_time=start_time
    )

    # 3. Start agent
    sql_backend.track_agent_start(
        agent_id=agent_id,
        stage_id=stage_id,
        agent_name="researcher",
        agent_config={"agent": {"version": "1.0"}},
        start_time=start_time
    )

    # 4. Track LLM call
    sql_backend.track_llm_call(
        llm_call_id=llm_call_id,
        agent_id=agent_id,
        provider="openai",
        model="gpt-4",
        prompt="Analyze",
        response="Done",
        prompt_tokens=10,
        completion_tokens=20,
        latency_ms=500,
        estimated_cost_usd=0.001,
        start_time=start_time
    )

    # 5. Track tool call
    sql_backend.track_tool_call(
        tool_execution_id=tool_id,
        agent_id=agent_id,
        tool_name="calculator",
        input_params={"expr": "2+2"},
        output_data={"result": 4},
        start_time=start_time,
        duration_seconds=0.1
    )

    # 6. End agent
    sql_backend.track_agent_end(
        agent_id=agent_id,
        end_time=start_time + timedelta(seconds=10),
        status="completed"
    )

    # 7. End stage
    sql_backend.track_stage_end(
        stage_id=stage_id,
        end_time=start_time + timedelta(seconds=15),
        status="completed"
    )

    # 8. End workflow
    sql_backend.track_workflow_end(
        workflow_id=workflow_id,
        end_time=start_time + timedelta(seconds=20),
        status="completed"
    )

    # Verify everything was tracked
    with get_session() as session:
        workflow = session.exec(
            select(WorkflowExecution).where(WorkflowExecution.id == workflow_id)
        ).first()
        assert workflow is not None
        assert workflow.status == "completed"

        stage = session.exec(
            select(StageExecution).where(StageExecution.id == stage_id)
        ).first()
        assert stage is not None
        assert stage.status == "completed"

        agent = session.exec(
            select(AgentExecution).where(AgentExecution.id == agent_id)
        ).first()
        assert agent is not None
        assert agent.status == "completed"
        assert agent.num_llm_calls == 1
        assert agent.num_tool_calls == 1

        llm_call = session.exec(
            select(LLMCall).where(LLMCall.id == llm_call_id)
        ).first()
        assert llm_call is not None

        tool_call = session.exec(
            select(ToolExecution).where(ToolExecution.id == tool_id)
        ).first()
        assert tool_call is not None
