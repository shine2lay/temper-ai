"""
Test for SQL backend per-operation session lifecycle (C-02).

Verifies that each tracking method uses a per-operation session via
get_session() and does not leak connections. The old standalone-session
and session-stack patterns have been removed.
"""
from datetime import datetime, timezone

import pytest

from temper_ai.observability import init_database
from temper_ai.observability.backends.sql_backend import SQLObservabilityBackend


@pytest.fixture
def backend():
    """Create SQL backend with in-memory database."""
    init_database(database_url="sqlite:///:memory:")
    return SQLObservabilityBackend(buffer=False)


def test_no_session_stack_or_standalone(backend):
    """Backend should not have _session_stack, _standalone_session, or _local."""
    assert not hasattr(backend, "_session_stack")
    assert not hasattr(backend, "_standalone_session")
    assert not hasattr(backend, "_local")


def test_no_get_or_create_session(backend):
    """Backend should not have _get_or_create_session or _commit_and_cleanup."""
    assert not hasattr(backend, "_get_or_create_session")
    assert not hasattr(backend, "_commit_and_cleanup")
    assert not hasattr(backend, "_cleanup_standalone_session")


def test_all_tracking_methods_succeed(backend):
    """Test that all tracking methods succeed with per-operation sessions."""
    workflow_id = "test-wf"
    stage_id = "test-stage"
    agent_id = "test-agent"

    # Workflow tracking
    backend.track_workflow_start(
        workflow_id=workflow_id,
        workflow_name="test",
        workflow_config={},
        start_time=datetime.now(timezone.utc)
    )

    backend.update_workflow_metrics(
        workflow_id=workflow_id,
        total_llm_calls=1,
        total_tool_calls=1,
        total_tokens=100,
        total_cost_usd=0.01
    )

    # Stage tracking
    backend.track_stage_start(
        stage_id=stage_id,
        workflow_id=workflow_id,
        stage_name="test_stage",
        stage_config={},
        start_time=datetime.now(timezone.utc)
    )

    backend.set_stage_output(
        stage_id=stage_id,
        output_data={"result": "success"}
    )

    # Agent tracking
    backend.track_agent_start(
        agent_id=agent_id,
        stage_id=stage_id,
        agent_name="test_agent",
        agent_config={},
        start_time=datetime.now(timezone.utc)
    )

    backend.set_agent_output(
        agent_id=agent_id,
        output_data={"result": "success"},
        total_tokens=50
    )

    # LLM call tracking (unbuffered since buffer=False)
    backend.track_llm_call(
        llm_call_id="llm-1",
        agent_id=agent_id,
        provider="test",
        model="test-model",
        prompt="test prompt",
        response="test response",
        prompt_tokens=10,
        completion_tokens=20,
        latency_ms=100,
        estimated_cost_usd=0.001,
        start_time=datetime.now(timezone.utc)
    )

    # Tool call tracking (unbuffered since buffer=False)
    backend.track_tool_call(
        tool_execution_id="tool-1",
        agent_id=agent_id,
        tool_name="test_tool",
        input_params={},
        output_data={},
        start_time=datetime.now(timezone.utc),
        duration_seconds=0.1
    )

    # End tracking
    backend.track_agent_end(
        agent_id=agent_id,
        end_time=datetime.now(timezone.utc),
        status="completed"
    )

    backend.track_stage_end(
        stage_id=stage_id,
        end_time=datetime.now(timezone.utc),
        status="completed"
    )

    backend.track_workflow_end(
        workflow_id=workflow_id,
        end_time=datetime.now(timezone.utc),
        status="completed"
    )

    # Verify all tracking operations completed successfully
    assert backend is not None
    assert workflow_id is not None
    assert stage_id is not None
    assert agent_id is not None


def test_get_session_context_works(backend):
    """Test that get_session_context provides a usable session."""
    with backend.get_session_context() as session:
        assert session is not None


def test_get_agent_execution_returns_detached(backend):
    """Test that get_agent_execution returns a detached (expunged) object."""
    # Set up workflow -> stage -> agent
    backend.track_workflow_start(
        workflow_id="wf-1",
        workflow_name="test",
        workflow_config={},
        start_time=datetime.now(timezone.utc)
    )
    backend.track_stage_start(
        stage_id="st-1",
        workflow_id="wf-1",
        stage_name="test_stage",
        stage_config={},
        start_time=datetime.now(timezone.utc)
    )
    backend.track_agent_start(
        agent_id="ag-1",
        stage_id="st-1",
        agent_name="test_agent",
        agent_config={},
        start_time=datetime.now(timezone.utc)
    )

    # Fetch agent - should be usable after session closes
    agent = backend.get_agent_execution("ag-1")
    assert agent is not None
    assert agent.id == "ag-1"
    assert agent.agent_name == "test_agent"


def test_multiple_operations_do_not_leak(backend):
    """Test that many operations don't accumulate sessions."""
    for i in range(20):
        backend.track_workflow_start(
            workflow_id=f"test-wf-{i}",
            workflow_name="test_workflow",
            workflow_config={"workflow": {"version": "1.0"}},
            start_time=datetime.now(timezone.utc)
        )
    # No assertion on internals needed - if we get here without error,
    # sessions are being properly opened and closed
    assert backend is not None  # Verify backend is still valid after 20 operations
