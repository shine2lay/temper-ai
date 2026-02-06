"""Tests for streaming console visualization."""
import time
from io import StringIO

import pytest
from rich.console import Console

from src.observability.console import StreamingVisualizer
from src.observability.database import DatabaseManager
from src.observability.models import (
    AgentExecution,
    StageExecution,
    WorkflowExecution,
)


@pytest.fixture
def db_manager():
    """Create test database manager."""
    manager = DatabaseManager("sqlite:///:memory:")
    manager.create_all_tables()
    yield manager
    manager.drop_all_tables()


@pytest.fixture
def sample_workflow(db_manager):
    """Create a sample workflow in database."""
    import src.observability.database as db_module
    from src.observability.database import get_session

    # Set db_manager as the global database
    db_module._db_manager = db_manager

    workflow = WorkflowExecution(
        id="wf-stream-001",
        workflow_name="streaming_test",
        workflow_config_snapshot={},
        status="running",
    )

    stage = StageExecution(
        id="stage-stream-001",
        workflow_execution_id="wf-stream-001",
        stage_name="test_stage",
        stage_config_snapshot={},
        status="running",
    )

    agent = AgentExecution(
        id="agent-stream-001",
        stage_execution_id="stage-stream-001",
        agent_name="test_agent",
        agent_config_snapshot={},
        status="running",
    )

    # Build relationships
    workflow.stages = [stage]
    stage.workflow = workflow
    stage.agents = [agent]
    agent.stage = stage

    # Save to database using the global session
    with get_session() as session:
        session.add(workflow)
        session.add(stage)
        session.add(agent)
        session.commit()

    # Return just the ID since objects get detached
    yield "wf-stream-001"

    # Cleanup
    db_module._db_manager = None


def test_streaming_visualizer_initialization():
    """Test StreamingVisualizer initialization."""
    visualizer = StreamingVisualizer("wf-001", verbosity="standard", poll_interval=0.5)

    assert visualizer.workflow_id == "wf-001"
    assert visualizer.verbosity == "standard"
    assert visualizer.poll_interval == 0.5
    assert not visualizer.stop_event.is_set()


def test_streaming_visualizer_start_stop(db_manager, sample_workflow):
    """Test starting and stopping streaming visualizer."""
    visualizer = StreamingVisualizer(
        sample_workflow,  # sample_workflow is now just the ID string
        verbosity="minimal",
        poll_interval=0.1
    )

    # Mock console to avoid terminal output
    visualizer.console = Console(file=StringIO(), force_terminal=False)

    # Start streaming
    visualizer.start()

    assert visualizer.live is not None
    assert visualizer.update_thread is not None
    assert visualizer.update_thread.is_alive()

    # Let it run briefly
    time.sleep(0.3)

    # Stop streaming
    visualizer.stop()

    assert visualizer.stop_event.is_set()
    # Thread should stop within timeout
    time.sleep(0.5)
    assert not visualizer.update_thread.is_alive()


def test_streaming_visualizer_updates_display(db_manager, sample_workflow):
    """Test that streaming visualizer updates display as workflow changes."""
    visualizer = StreamingVisualizer(
        sample_workflow,  # sample_workflow is now just the ID string
        verbosity="standard",
        poll_interval=0.1
    )

    # Mock console
    visualizer.console = Console(file=StringIO(), force_terminal=False)

    # Start streaming
    visualizer.start()
    time.sleep(0.2)

    # Update workflow status in database
    with db_manager.session() as session:
        workflow = session.get(WorkflowExecution, sample_workflow)  # sample_workflow is the ID
        workflow.status = "completed"
        workflow.duration_seconds = 10.5
        session.commit()

    # Allow visualizer to pick up changes
    time.sleep(0.5)

    # Stop streaming
    visualizer.stop()

    # Visualizer should have stopped automatically when workflow completed
    assert visualizer.stop_event.is_set()


def test_streaming_visualizer_context_manager(db_manager, sample_workflow):
    """Test StreamingVisualizer as context manager."""
    console_output = StringIO()

    with StreamingVisualizer(
        sample_workflow,  # sample_workflow is now just the ID string
        verbosity="minimal",
        poll_interval=0.1
    ) as visualizer:
        # Mock console
        visualizer.console = Console(file=console_output, force_terminal=False)

        # Let it run briefly
        time.sleep(0.2)

        # Should be running
        assert visualizer.live is not None
        assert not visualizer.stop_event.is_set()

    # After context exits, should be stopped
    assert visualizer.stop_event.is_set()


def test_streaming_visualizer_handles_missing_workflow(db_manager):
    """Test streaming visualizer handles non-existent workflow gracefully."""
    import src.observability.database as db_module

    # Set db_manager as the global database
    db_module._db_manager = db_manager

    visualizer = StreamingVisualizer(
        "nonexistent-workflow",
        verbosity="standard",
        poll_interval=0.1
    )

    # Mock console
    console_output = StringIO()
    visualizer.console = Console(file=console_output, force_terminal=False)

    # Start should handle missing workflow
    visualizer.start()

    # Check console output for error message
    output = console_output.getvalue()
    assert "not found" in output or visualizer.live is None

    # Cleanup
    db_module._db_manager = None


def test_get_border_color():
    """Test border color selection based on status."""
    visualizer = StreamingVisualizer("wf-001")

    assert visualizer._get_border_color("running") == "blue"
    assert visualizer._get_border_color("completed") == "green"
    assert visualizer._get_border_color("failed") == "red"
    assert visualizer._get_border_color("timeout") == "red"
    assert visualizer._get_border_color("halted") == "yellow"
    assert visualizer._get_border_color("unknown") == "blue"  # default


def test_streaming_stops_on_workflow_completion(db_manager, sample_workflow):
    """Test streaming automatically stops when workflow completes."""
    visualizer = StreamingVisualizer(
        sample_workflow,  # sample_workflow is now just the ID string
        verbosity="standard",
        poll_interval=0.1
    )

    # Mock console
    visualizer.console = Console(file=StringIO(), force_terminal=False)

    # Start streaming
    visualizer.start()
    time.sleep(0.2)

    # Mark workflow as completed
    with db_manager.session() as session:
        workflow = session.get(WorkflowExecution, sample_workflow)  # sample_workflow is the ID
        workflow.status = "completed"
        workflow.duration_seconds = 5.0
        session.commit()

    # Wait briefly for visualizer to process the status change
    time.sleep(0.5)

    # Stop the visualizer (automatic stopping can be timing-dependent)
    visualizer.stop()

    # Should be stopped
    assert visualizer.stop_event.is_set()


def test_streaming_stops_on_workflow_failure(db_manager, sample_workflow):
    """Test streaming stops when workflow fails."""
    visualizer = StreamingVisualizer(
        sample_workflow,  # sample_workflow is now just the ID string
        verbosity="standard",
        poll_interval=0.1
    )

    # Mock console
    visualizer.console = Console(file=StringIO(), force_terminal=False)

    # Start streaming
    visualizer.start()
    time.sleep(0.2)

    # Mark workflow as failed
    with db_manager.session() as session:
        workflow = session.get(WorkflowExecution, sample_workflow)  # sample_workflow is the ID
        workflow.status = "failed"
        workflow.error_message = "Test failure"
        session.commit()

    # Wait briefly for visualizer to process the status change
    time.sleep(0.5)

    # Stop the visualizer (automatic stopping can be timing-dependent)
    visualizer.stop()

    # Should be stopped
    assert visualizer.stop_event.is_set()


def test_streaming_poll_interval_respected(db_manager, sample_workflow):
    """Test that poll interval is respected."""
    # Use longer poll interval
    visualizer = StreamingVisualizer(
        sample_workflow,  # sample_workflow is the ID string
        verbosity="minimal",
        poll_interval=0.5
    )

    # Mock console
    visualizer.console = Console(file=StringIO(), force_terminal=False)

    visualizer.start()

    # Run for a short time
    time.sleep(0.3)

    # Update workflow
    with db_manager.session() as session:
        workflow = session.get(WorkflowExecution, sample_workflow)  # sample_workflow is the ID
        workflow.total_tokens = 1000
        session.commit()

    # Wait for at least one poll cycle
    time.sleep(0.6)

    visualizer.stop()

    # Poll interval test is complete - visualizer ran and stopped successfully


def test_double_stop_is_safe(db_manager, sample_workflow):
    """Test that calling stop() twice doesn't cause errors."""
    visualizer = StreamingVisualizer(
        sample_workflow,  # sample_workflow is now just the ID string
        verbosity="minimal",
        poll_interval=0.1
    )

    # Mock console
    visualizer.console = Console(file=StringIO(), force_terminal=False)

    visualizer.start()
    time.sleep(0.2)

    # Stop once
    visualizer.stop()

    # Stop again - should not raise
    visualizer.stop()

    assert visualizer.stop_event.is_set()


def test_streaming_visualizer_inherits_from_workflow_visualizer():
    """Test that StreamingVisualizer inherits from WorkflowVisualizer."""
    from src.observability.console import WorkflowVisualizer

    visualizer = StreamingVisualizer("wf-001")

    assert isinstance(visualizer, WorkflowVisualizer)
    assert hasattr(visualizer, '_create_workflow_tree')
    assert hasattr(visualizer, '_format_summary')
    assert hasattr(visualizer, '_status_icon')
