"""
Comprehensive tests for src/observability/backends/sql_backend.py.

Tests the SQLObservabilityBackend with workflow, stage, agent, LLM, and tool tracking.
"""

from datetime import UTC, datetime
from unittest.mock import Mock, patch

import pytest
from sqlmodel import Session

from temper_ai.observability.backends.sql_backend import SQLObservabilityBackend
from temper_ai.storage.database.models import (
    AgentExecution,
    StageExecution,
    WorkflowExecution,
)

# ========== Fixtures ==========


@pytest.fixture
def mock_buffer():
    """Create mock observability buffer."""
    buffer = Mock()
    buffer.buffer_llm_call = Mock()
    buffer.buffer_tool_call = Mock()
    buffer.set_flush_callback = Mock()
    return buffer


@pytest.fixture
def backend_no_buffer():
    """Create SQL backend without buffering."""
    return SQLObservabilityBackend(buffer=False)


@pytest.fixture
def backend_with_buffer(mock_buffer):
    """Create SQL backend with mock buffer."""
    return SQLObservabilityBackend(buffer=mock_buffer)


@pytest.fixture
def mock_session():
    """Create mock database session."""
    session = Mock(spec=Session)
    session.add = Mock()
    session.commit = Mock()
    session.exec = Mock()
    session.expunge = Mock()
    return session


@pytest.fixture
def sample_workflow_config():
    """Sample workflow configuration."""
    return {
        "workflow": {
            "name": "test_workflow",
            "version": "1.0",
            "description": "Test workflow",
        }
    }


@pytest.fixture
def sample_stage_config():
    """Sample stage configuration."""
    return {
        "stage": {"name": "test_stage", "version": "1.0", "description": "Test stage"}
    }


@pytest.fixture
def sample_agent_config():
    """Sample agent configuration."""
    return {
        "agent": {"name": "test_agent", "version": "1.0", "description": "Test agent"}
    }


# ========== Tests for Backend Initialization ==========


def test_backend_init_with_default_buffer():
    """Test backend initialization with default buffer."""
    backend = SQLObservabilityBackend()

    assert backend._buffer is not None
    # Buffer should have flush callback set
    assert backend._buffer._flush_callback is not None


def test_backend_init_no_buffer():
    """Test backend initialization without buffer."""
    backend = SQLObservabilityBackend(buffer=False)

    assert backend._buffer is None


def test_backend_init_with_custom_buffer(mock_buffer):
    """Test backend initialization with custom buffer."""
    backend = SQLObservabilityBackend(buffer=mock_buffer)

    assert backend._buffer == mock_buffer
    mock_buffer.set_flush_callback.assert_called_once()


# ========== Tests for Workflow Tracking ==========


@patch("temper_ai.observability.backends.sql_backend.get_session")
def test_track_workflow_start(
    mock_get_session, backend_no_buffer, sample_workflow_config
):
    """Test tracking workflow start."""
    mock_session = Mock()
    mock_get_session.return_value.__enter__.return_value = mock_session

    start_time = datetime.now(UTC)
    backend_no_buffer.track_workflow_start(
        workflow_id="wf_123",
        workflow_name="test_workflow",
        workflow_config=sample_workflow_config,
        start_time=start_time,
        trigger_type="cli",
        environment="test",
    )

    mock_session.add.assert_called_once()
    mock_session.commit.assert_called_once()

    # Verify WorkflowExecution was created
    added_obj = mock_session.add.call_args[0][0]
    assert isinstance(added_obj, WorkflowExecution)
    assert added_obj.id == "wf_123"
    assert added_obj.workflow_name == "test_workflow"
    assert added_obj.status == "running"


@patch("temper_ai.observability.backends.sql_backend.get_session")
def test_track_workflow_end(mock_get_session, backend_no_buffer):
    """Test tracking workflow end."""
    mock_workflow = Mock(spec=WorkflowExecution)
    mock_workflow.start_time = datetime.now(UTC)

    mock_result = Mock()
    mock_result.first.return_value = mock_workflow

    mock_session = Mock()
    mock_session.exec.return_value = mock_result
    mock_get_session.return_value.__enter__.return_value = mock_session

    end_time = datetime.now(UTC)
    backend_no_buffer.track_workflow_end(
        workflow_id="wf_123", end_time=end_time, status="completed"
    )

    assert mock_workflow.status == "completed"
    assert mock_workflow.end_time == end_time
    mock_session.commit.assert_called_once()


@patch("temper_ai.observability.backends.sql_backend.get_session")
def test_track_workflow_end_with_error(mock_get_session, backend_no_buffer):
    """Test tracking workflow end with error."""
    mock_workflow = Mock(spec=WorkflowExecution)
    mock_workflow.start_time = datetime.now(UTC)

    mock_result = Mock()
    mock_result.first.return_value = mock_workflow

    mock_session = Mock()
    mock_session.exec.return_value = mock_result
    mock_get_session.return_value.__enter__.return_value = mock_session

    end_time = datetime.now(UTC)
    backend_no_buffer.track_workflow_end(
        workflow_id="wf_123",
        end_time=end_time,
        status="failed",
        error_message="Test error",
        error_stack_trace="Stack trace",
    )

    assert mock_workflow.status == "failed"
    assert mock_workflow.error_message == "Test error"
    assert mock_workflow.error_stack_trace == "Stack trace"
    mock_session.commit.assert_called_once()


@patch("temper_ai.observability.backends.sql_backend.get_session")
def test_track_workflow_end_not_found(mock_get_session, backend_no_buffer):
    """Test tracking workflow end when workflow not found."""
    mock_result = Mock()
    mock_result.first.return_value = None

    mock_session = Mock()
    mock_session.exec.return_value = mock_result
    mock_get_session.return_value.__enter__.return_value = mock_session

    end_time = datetime.now(UTC)
    backend_no_buffer.track_workflow_end(
        workflow_id="wf_nonexistent", end_time=end_time, status="completed"
    )

    # Should not crash, just not update anything
    mock_session.commit.assert_not_called()


@patch("temper_ai.observability.backends.sql_backend.get_session")
def test_update_workflow_metrics(mock_get_session, backend_no_buffer):
    """Test updating workflow metrics."""
    mock_workflow = Mock(spec=WorkflowExecution)

    mock_result = Mock()
    mock_result.first.return_value = mock_workflow

    mock_session = Mock()
    mock_session.exec.return_value = mock_result
    mock_get_session.return_value.__enter__.return_value = mock_session

    backend_no_buffer.update_workflow_metrics(
        workflow_id="wf_123",
        total_llm_calls=10,
        total_tool_calls=5,
        total_tokens=1000,
        total_cost_usd=0.05,
    )

    assert mock_workflow.total_llm_calls == 10
    assert mock_workflow.total_tool_calls == 5
    assert mock_workflow.total_tokens == 1000
    assert mock_workflow.total_cost_usd == 0.05
    mock_session.commit.assert_called_once()


# ========== Tests for Stage Tracking ==========


@patch("temper_ai.observability.backends.sql_backend.get_session")
def test_track_stage_start(mock_get_session, backend_no_buffer, sample_stage_config):
    """Test tracking stage start."""
    mock_session = Mock()
    mock_get_session.return_value.__enter__.return_value = mock_session

    start_time = datetime.now(UTC)
    backend_no_buffer.track_stage_start(
        stage_id="st_123",
        workflow_id="wf_123",
        stage_name="test_stage",
        stage_config=sample_stage_config,
        start_time=start_time,
        input_data={"key": "value"},
    )

    mock_session.add.assert_called_once()
    mock_session.commit.assert_called_once()

    added_obj = mock_session.add.call_args[0][0]
    assert isinstance(added_obj, StageExecution)
    assert added_obj.id == "st_123"
    assert added_obj.workflow_execution_id == "wf_123"
    assert added_obj.status == "running"


@patch("temper_ai.observability.backends.sql_backend.get_session")
def test_track_stage_end(mock_get_session, backend_no_buffer):
    """Test tracking stage end."""
    mock_stage = Mock(spec=StageExecution)
    mock_stage.start_time = datetime.now(UTC)

    mock_result = Mock()
    mock_result.first.return_value = mock_stage

    mock_session = Mock()
    mock_session.exec.return_value = mock_result
    mock_get_session.return_value.__enter__.return_value = mock_session

    end_time = datetime.now(UTC)
    backend_no_buffer.track_stage_end(
        stage_id="st_123",
        end_time=end_time,
        status="completed",
        num_agents_executed=3,
        num_agents_succeeded=2,
        num_agents_failed=1,
    )

    assert mock_stage.status == "completed"
    assert mock_stage.num_agents_executed == 3
    assert mock_stage.num_agents_succeeded == 2
    assert mock_stage.num_agents_failed == 1
    mock_session.commit.assert_called_once()


@patch("temper_ai.observability.backends.sql_backend.get_session")
def test_track_stage_end_compute_metrics(mock_get_session, backend_no_buffer):
    """Test tracking stage end with computed metrics."""
    mock_stage = Mock(spec=StageExecution)
    mock_stage.start_time = datetime.now(UTC)

    # Mock metrics result as tuple (total, succeeded, failed)
    mock_metrics_result = (5, 4, 1)

    mock_result = Mock()
    mock_result.first.return_value = mock_stage

    mock_session = Mock()
    mock_session.exec.side_effect = [
        mock_result,
        Mock(first=lambda: mock_metrics_result),
    ]
    mock_get_session.return_value.__enter__.return_value = mock_session

    end_time = datetime.now(UTC)
    backend_no_buffer.track_stage_end(
        stage_id="st_123", end_time=end_time, status="completed"
    )

    assert mock_stage.num_agents_executed == 5
    assert mock_stage.num_agents_succeeded == 4
    assert mock_stage.num_agents_failed == 1


@patch("temper_ai.observability.backends.sql_backend.get_session")
def test_set_stage_output(mock_get_session, backend_no_buffer):
    """Test setting stage output data."""
    mock_stage = Mock(spec=StageExecution)

    mock_result = Mock()
    mock_result.first.return_value = mock_stage

    mock_session = Mock()
    mock_session.exec.return_value = mock_result
    mock_get_session.return_value.__enter__.return_value = mock_session

    output_data = {"result": "success", "value": 42}
    backend_no_buffer.set_stage_output("st_123", output_data)

    assert mock_stage.output_data == output_data
    mock_session.commit.assert_called_once()


# ========== Tests for Agent Tracking ==========


@patch("temper_ai.observability.backends.sql_backend.get_session")
def test_track_agent_start(mock_get_session, backend_no_buffer, sample_agent_config):
    """Test tracking agent start."""
    mock_session = Mock()
    mock_get_session.return_value.__enter__.return_value = mock_session

    start_time = datetime.now(UTC)
    backend_no_buffer.track_agent_start(
        agent_id="ag_123",
        stage_id="st_123",
        agent_name="test_agent",
        agent_config=sample_agent_config,
        start_time=start_time,
        input_data={"input": "test"},
    )

    mock_session.add.assert_called_once()
    mock_session.commit.assert_called_once()

    added_obj = mock_session.add.call_args[0][0]
    assert isinstance(added_obj, AgentExecution)
    assert added_obj.id == "ag_123"
    assert added_obj.stage_execution_id == "st_123"
    assert added_obj.status == "running"


@patch("temper_ai.observability.backends.sql_backend.get_session")
def test_track_agent_end(mock_get_session, backend_no_buffer):
    """Test tracking agent end."""
    mock_agent = Mock(spec=AgentExecution)
    mock_agent.start_time = datetime.now(UTC)

    mock_result = Mock()
    mock_result.first.return_value = mock_agent

    mock_session = Mock()
    mock_session.exec.return_value = mock_result
    mock_get_session.return_value.__enter__.return_value = mock_session

    end_time = datetime.now(UTC)
    backend_no_buffer.track_agent_end(
        agent_id="ag_123", end_time=end_time, status="completed"
    )

    assert mock_agent.status == "completed"
    assert mock_agent.end_time == end_time
    mock_session.commit.assert_called_once()


@patch("temper_ai.observability.backends.sql_backend.get_session")
def test_set_agent_output(mock_get_session, backend_no_buffer):
    """Test setting agent output data."""
    mock_agent = Mock(spec=AgentExecution)

    mock_result = Mock()
    mock_result.first.return_value = mock_agent

    mock_session = Mock()
    mock_session.exec.return_value = mock_result
    mock_get_session.return_value.__enter__.return_value = mock_session

    output_data = {"answer": "42"}
    backend_no_buffer.set_agent_output(
        agent_id="ag_123",
        output_data=output_data,
        reasoning="Because math",
        confidence_score=0.95,
        total_tokens=100,
        prompt_tokens=60,
        completion_tokens=40,
        estimated_cost_usd=0.001,
        num_llm_calls=1,
        num_tool_calls=0,
    )

    assert mock_agent.output_data == output_data
    assert mock_agent.reasoning == "Because math"
    assert mock_agent.confidence_score == 0.95
    assert mock_agent.total_tokens == 100
    assert mock_agent.prompt_tokens == 60
    assert mock_agent.completion_tokens == 40
    assert mock_agent.estimated_cost_usd == 0.001
    assert mock_agent.num_llm_calls == 1
    assert mock_agent.num_tool_calls == 0
    mock_session.commit.assert_called_once()


@patch("temper_ai.observability.backends.sql_backend.get_session")
def test_set_agent_output_partial_update(mock_get_session, backend_no_buffer):
    """Test setting agent output with partial fields."""
    mock_agent = Mock(spec=AgentExecution)
    mock_agent.total_tokens = 50
    mock_agent.num_llm_calls = 0

    mock_result = Mock()
    mock_result.first.return_value = mock_agent

    mock_session = Mock()
    mock_session.exec.return_value = mock_result
    mock_get_session.return_value.__enter__.return_value = mock_session

    backend_no_buffer.set_agent_output(
        agent_id="ag_123",
        output_data={"result": "ok"},
        total_tokens=100,  # Only update tokens
    )

    assert mock_agent.total_tokens == 100
    # Other fields should not be set
    mock_session.commit.assert_called_once()


# ========== Tests for LLM Call Tracking ==========


@patch("temper_ai.observability.backends.sql_backend.get_session")
def test_track_llm_call_no_buffer(mock_get_session, backend_no_buffer):
    """Test tracking LLM call without buffering."""
    mock_agent = Mock(spec=AgentExecution)
    mock_agent.num_llm_calls = 0
    mock_agent.total_tokens = 0
    mock_agent.prompt_tokens = 0
    mock_agent.completion_tokens = 0
    mock_agent.estimated_cost_usd = 0.0

    mock_result = Mock()
    mock_result.first.return_value = mock_agent

    mock_session = Mock()
    mock_session.exec.return_value = mock_result
    mock_get_session.return_value.__enter__.return_value = mock_session

    start_time = datetime.now(UTC)
    backend_no_buffer.track_llm_call(
        llm_call_id="llm_123",
        agent_id="ag_123",
        provider="openai",
        model="gpt-4",
        prompt="Test prompt",
        response="Test response",
        prompt_tokens=50,
        completion_tokens=30,
        latency_ms=1000,
        estimated_cost_usd=0.002,
        start_time=start_time,
        temperature=0.7,
        max_tokens=100,
    )

    # Should add LLMCall and update agent metrics
    assert mock_session.add.call_count == 1
    assert mock_agent.num_llm_calls == 1
    assert mock_agent.total_tokens == 80
    assert mock_agent.prompt_tokens == 50
    assert mock_agent.completion_tokens == 30
    mock_session.commit.assert_called_once()


def test_track_llm_call_with_buffer(backend_with_buffer, mock_buffer):
    """Test tracking LLM call with buffering."""
    start_time = datetime.now(UTC)
    backend_with_buffer.track_llm_call(
        llm_call_id="llm_123",
        agent_id="ag_123",
        provider="openai",
        model="gpt-4",
        prompt="Test prompt",
        response="Test response",
        prompt_tokens=50,
        completion_tokens=30,
        latency_ms=1000,
        estimated_cost_usd=0.002,
        start_time=start_time,
    )

    # Should use buffer instead of direct insert
    mock_buffer.buffer_llm_call.assert_called_once()
    call_kwargs = mock_buffer.buffer_llm_call.call_args[1]
    assert call_kwargs["llm_call_id"] == "llm_123"
    assert call_kwargs["agent_id"] == "ag_123"
    assert call_kwargs["prompt_tokens"] == 50


@patch("temper_ai.observability.backends.sql_backend.get_session")
def test_track_llm_call_with_error(mock_get_session, backend_no_buffer):
    """Test tracking failed LLM call."""
    mock_agent = Mock(spec=AgentExecution)
    mock_agent.num_llm_calls = 0
    mock_agent.total_tokens = 0
    mock_agent.prompt_tokens = 0
    mock_agent.completion_tokens = 0
    mock_agent.estimated_cost_usd = 0.0

    mock_result = Mock()
    mock_result.first.return_value = mock_agent

    mock_session = Mock()
    mock_session.exec.return_value = mock_result
    mock_get_session.return_value.__enter__.return_value = mock_session

    start_time = datetime.now(UTC)
    backend_no_buffer.track_llm_call(
        llm_call_id="llm_123",
        agent_id="ag_123",
        provider="openai",
        model="gpt-4",
        prompt="Test prompt",
        response="",
        prompt_tokens=50,
        completion_tokens=0,
        latency_ms=500,
        estimated_cost_usd=0.001,
        start_time=start_time,
        status="failed",
        error_message="API error",
    )

    # Should still record the call
    mock_session.add.assert_called_once()
    added_obj = mock_session.add.call_args[0][0]
    assert added_obj.status == "failed"
    assert added_obj.error_message == "API error"


# ========== Tests for Tool Call Tracking ==========


@patch("temper_ai.observability.backends.sql_backend.get_session")
def test_track_tool_call_no_buffer(mock_get_session, backend_no_buffer):
    """Test tracking tool call without buffering."""
    mock_agent = Mock(spec=AgentExecution)
    mock_agent.num_tool_calls = 0

    mock_result = Mock()
    mock_result.first.return_value = mock_agent

    mock_session = Mock()
    mock_session.exec.return_value = mock_result
    mock_get_session.return_value.__enter__.return_value = mock_session

    start_time = datetime.now(UTC)
    backend_no_buffer.track_tool_call(
        tool_execution_id="tool_123",
        agent_id="ag_123",
        tool_name="calculator",
        input_params={"operation": "add", "a": 1, "b": 2},
        output_data={"result": 3},
        start_time=start_time,
        duration_seconds=0.5,
        safety_checks=["input_validation"],
        approval_required=False,
    )

    mock_session.add.assert_called_once()
    assert mock_agent.num_tool_calls == 1
    mock_session.commit.assert_called_once()


def test_track_tool_call_with_buffer(backend_with_buffer, mock_buffer):
    """Test tracking tool call with buffering."""
    start_time = datetime.now(UTC)
    backend_with_buffer.track_tool_call(
        tool_execution_id="tool_123",
        agent_id="ag_123",
        tool_name="calculator",
        input_params={"operation": "add"},
        output_data={"result": 3},
        start_time=start_time,
        duration_seconds=0.5,
    )

    mock_buffer.buffer_tool_call.assert_called_once()
    call_kwargs = mock_buffer.buffer_tool_call.call_args[1]
    assert call_kwargs["tool_execution_id"] == "tool_123"
    assert call_kwargs["tool_name"] == "calculator"


@patch("temper_ai.observability.backends.sql_backend.get_session")
def test_track_tool_call_with_error(mock_get_session, backend_no_buffer):
    """Test tracking failed tool call."""
    mock_agent = Mock(spec=AgentExecution)
    mock_agent.num_tool_calls = 0

    mock_result = Mock()
    mock_result.first.return_value = mock_agent

    mock_session = Mock()
    mock_session.exec.return_value = mock_result
    mock_get_session.return_value.__enter__.return_value = mock_session

    start_time = datetime.now(UTC)
    backend_no_buffer.track_tool_call(
        tool_execution_id="tool_123",
        agent_id="ag_123",
        tool_name="calculator",
        input_params={"operation": "divide", "a": 1, "b": 0},
        output_data={},
        start_time=start_time,
        duration_seconds=0.1,
        status="failed",
        error_message="Division by zero",
    )

    mock_session.add.assert_called_once()
    added_obj = mock_session.add.call_args[0][0]
    assert added_obj.status == "failed"
    assert added_obj.error_message == "Division by zero"


# ========== Tests for Session Context ==========


@patch("temper_ai.observability.backends.sql_backend.get_session")
def test_get_session_context(mock_get_session, backend_no_buffer):
    """Test getting session context."""
    mock_session = Mock()
    mock_get_session.return_value.__enter__.return_value = mock_session
    mock_get_session.return_value.__exit__.return_value = None

    with backend_no_buffer.get_session_context() as session:
        assert session == mock_session


# ========== Tests for Get Agent Execution ==========


@patch("temper_ai.observability.backends.sql_backend.get_session")
def test_get_agent_execution_found(mock_get_session, backend_no_buffer):
    """Test getting agent execution when found."""
    mock_agent = Mock(spec=AgentExecution)
    mock_agent.id = "ag_123"

    mock_result = Mock()
    mock_result.first.return_value = mock_agent

    mock_session = Mock()
    mock_session.exec.return_value = mock_result
    mock_get_session.return_value.__enter__.return_value = mock_session

    agent = backend_no_buffer.get_agent_execution("ag_123")

    assert agent == mock_agent
    mock_session.expunge.assert_called_once_with(mock_agent)


@patch("temper_ai.observability.backends.sql_backend.get_session")
def test_get_agent_execution_not_found(mock_get_session, backend_no_buffer):
    """Test getting agent execution when not found."""
    mock_result = Mock()
    mock_result.first.return_value = None

    mock_session = Mock()
    mock_session.exec.return_value = mock_result
    mock_get_session.return_value.__enter__.return_value = mock_session

    agent = backend_no_buffer.get_agent_execution("ag_nonexistent")

    assert agent is None


# ========== Tests for Stats and Indexes ==========


@patch("temper_ai.observability.backends._sql_backend_helpers.get_backend_stats")
def test_get_stats(mock_get_stats, backend_no_buffer):
    """Test getting backend stats."""
    expected_stats = {"workflows": 10, "agents": 50}
    mock_get_stats.return_value = expected_stats

    stats = backend_no_buffer.get_stats()

    assert stats == expected_stats
    mock_get_stats.assert_called_once()


def test_create_indexes(backend_no_buffer):
    """Test creating database indexes."""
    # create_indexes is a static method that just logs
    # It doesn't raise, so call it
    backend_no_buffer.create_indexes()

    # Method should complete without error
    assert True


# ========== Tests for Delegated Methods ==========


@patch("temper_ai.observability.backends._sql_backend_helpers.track_safety_violation")
def test_track_safety_violation(mock_track, backend_no_buffer):
    """Test tracking safety violation."""
    backend_no_buffer.track_safety_violation(
        workflow_id="wf_123",
        stage_id="st_123",
        agent_id="ag_123",
        violation_severity="high",
        violation_message="Unsafe operation",
        policy_name="test_policy",
    )

    mock_track.assert_called_once()


@patch(
    "temper_ai.observability.backends._sql_backend_helpers.track_collaboration_event"
)
def test_track_collaboration_event(mock_track, backend_no_buffer):
    """Test tracking collaboration event."""
    mock_track.return_value = "collab_123"

    event_id = backend_no_buffer.track_collaboration_event(
        stage_id="st_123",
        event_type="negotiation",
        agents_involved=["agent1", "agent2"],
        event_data={"topic": "consensus"},
    )

    assert event_id == "collab_123"
    mock_track.assert_called_once()


@patch("temper_ai.observability.backends._sql_backend_helpers.cleanup_old_records")
def test_cleanup_old_records(mock_cleanup, backend_no_buffer):
    """Test cleaning up old records."""
    mock_cleanup.return_value = {"workflows": 5, "stages": 10}

    result = backend_no_buffer.cleanup_old_records(retention_days=30, dry_run=True)

    assert result == {"workflows": 5, "stages": 10}
    mock_cleanup.assert_called_once_with(30, True)


@patch(
    "temper_ai.observability.backends._sql_backend_helpers.aggregate_workflow_metrics"
)
def test_aggregate_workflow_metrics(mock_aggregate, backend_no_buffer):
    """Test aggregating workflow metrics."""
    mock_aggregate.return_value = {
        "total_llm_calls": 100,
        "total_tool_calls": 50,
        "total_tokens": 10000,
    }

    metrics = backend_no_buffer.aggregate_workflow_metrics("wf_123")

    assert metrics["total_llm_calls"] == 100
    assert metrics["total_tool_calls"] == 50
    mock_aggregate.assert_called_once_with("wf_123")


@patch("temper_ai.observability.backends._sql_backend_helpers.aggregate_stage_metrics")
def test_aggregate_stage_metrics(mock_aggregate, backend_no_buffer):
    """Test aggregating stage metrics."""
    mock_aggregate.return_value = {"num_agents": 5, "total_duration": 120.5}

    metrics = backend_no_buffer.aggregate_stage_metrics("st_123")

    assert metrics["num_agents"] == 5
    assert metrics["total_duration"] == 120.5
    mock_aggregate.assert_called_once_with("st_123")
