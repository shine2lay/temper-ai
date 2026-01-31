"""
Test for SQL backend connection leak fix.

Verifies that standalone sessions (created outside context manager) are properly cleaned up.
"""
import pytest
from datetime import datetime, timezone
from src.observability.backends.sql_backend import SQLObservabilityBackend
from src.observability import init_database


@pytest.fixture
def backend():
    """Create SQL backend with in-memory database."""
    init_database(connection_string="sqlite:///:memory:")
    return SQLObservabilityBackend()


def test_standalone_session_cleanup(backend):
    """Test that standalone sessions are cleaned up after operations."""
    # Initially, no standalone session should exist
    assert backend._standalone_session is None

    # Call tracking method that creates standalone session
    backend.track_workflow_start(
        workflow_id="test-wf-1",
        workflow_name="test_workflow",
        workflow_config={"workflow": {"version": "1.0"}},
        start_time=datetime.now(timezone.utc)
    )

    # After operation, standalone session should be cleaned up
    assert backend._standalone_session is None


def test_multiple_operations_without_context(backend):
    """Test that multiple operations don't leak connections."""
    # Track multiple workflow starts
    for i in range(10):
        backend.track_workflow_start(
            workflow_id=f"test-wf-{i}",
            workflow_name="test_workflow",
            workflow_config={"workflow": {"version": "1.0"}},
            start_time=datetime.now(timezone.utc)
        )
        # Verify cleanup happens after each operation
        assert backend._standalone_session is None


def test_context_manager_no_cleanup(backend):
    """Test that context-managed sessions are not cleaned up prematurely."""
    # Use context manager
    with backend.get_session_context() as session:
        # Session stack should have one session
        assert len(backend._session_stack) == 1

        # Track workflow within context
        backend.track_workflow_start(
            workflow_id="test-wf-ctx",
            workflow_name="test_workflow",
            workflow_config={"workflow": {"version": "1.0"}},
            start_time=datetime.now(timezone.utc)
        )

        # No standalone session should be created
        assert backend._standalone_session is None
        # Session stack should still have the context session
        assert len(backend._session_stack) == 1

    # After context, stack should be empty
    assert len(backend._session_stack) == 0


def test_mixed_context_and_standalone(backend):
    """Test that context-managed and standalone operations don't interfere."""
    # Standalone operation
    backend.track_workflow_start(
        workflow_id="test-wf-standalone",
        workflow_name="test_workflow",
        workflow_config={"workflow": {"version": "1.0"}},
        start_time=datetime.now(timezone.utc)
    )
    assert backend._standalone_session is None

    # Context-managed operation
    with backend.get_session_context():
        backend.track_workflow_start(
            workflow_id="test-wf-context",
            workflow_name="test_workflow",
            workflow_config={"workflow": {"version": "1.0"}},
            start_time=datetime.now(timezone.utc)
        )
        assert backend._standalone_session is None

    # Another standalone operation
    backend.track_workflow_start(
        workflow_id="test-wf-standalone-2",
        workflow_name="test_workflow",
        workflow_config={"workflow": {"version": "1.0"}},
        start_time=datetime.now(timezone.utc)
    )
    assert backend._standalone_session is None


def test_all_tracking_methods_cleanup(backend):
    """Test that all tracking methods properly clean up standalone sessions."""
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
    assert backend._standalone_session is None

    backend.update_workflow_metrics(
        workflow_id=workflow_id,
        total_llm_calls=1,
        total_tool_calls=1,
        total_tokens=100,
        total_cost_usd=0.01
    )
    assert backend._standalone_session is None

    # Stage tracking
    backend.track_stage_start(
        stage_id=stage_id,
        workflow_id=workflow_id,
        stage_name="test_stage",
        stage_config={},
        start_time=datetime.now(timezone.utc)
    )
    assert backend._standalone_session is None

    backend.set_stage_output(
        stage_id=stage_id,
        output_data={"result": "success"}
    )
    assert backend._standalone_session is None

    # Agent tracking
    backend.track_agent_start(
        agent_id=agent_id,
        stage_id=stage_id,
        agent_name="test_agent",
        agent_config={},
        start_time=datetime.now(timezone.utc)
    )
    assert backend._standalone_session is None

    backend.set_agent_output(
        agent_id=agent_id,
        output_data={"result": "success"},
        total_tokens=50
    )
    assert backend._standalone_session is None

    # LLM call tracking
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
    assert backend._standalone_session is None

    # Tool call tracking
    backend.track_tool_call(
        tool_execution_id="tool-1",
        agent_id=agent_id,
        tool_name="test_tool",
        input_params={},
        output_data={},
        start_time=datetime.now(timezone.utc),
        duration_seconds=0.1
    )
    assert backend._standalone_session is None

    # End tracking
    backend.track_agent_end(
        agent_id=agent_id,
        end_time=datetime.now(timezone.utc),
        status="completed"
    )
    assert backend._standalone_session is None

    backend.track_stage_end(
        stage_id=stage_id,
        end_time=datetime.now(timezone.utc),
        status="completed"
    )
    assert backend._standalone_session is None

    backend.track_workflow_end(
        workflow_id=workflow_id,
        end_time=datetime.now(timezone.utc),
        status="completed"
    )
    assert backend._standalone_session is None


def test_cleanup_exception_handling(backend):
    """Test that cleanup handles exceptions gracefully."""
    # Create a standalone session
    backend._standalone_session = backend._get_or_create_session()

    # Mock __exit__ to raise exception
    original_exit = backend._standalone_session.__exit__

    def failing_exit(*args):
        raise RuntimeError("Simulated cleanup failure")

    backend._standalone_session.__exit__ = failing_exit

    # Cleanup should handle exception and still set session to None
    backend._cleanup_standalone_session()
    assert backend._standalone_session is None
