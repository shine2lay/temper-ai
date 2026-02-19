"""Tests for WorkflowVisualizer and StreamingVisualizer console components."""
import time
from datetime import datetime, timezone
from io import StringIO
from unittest.mock import Mock, patch

import pytest
from rich.console import Console

from temper_ai.observability.console import (
    StreamingVisualizer,
    WorkflowVisualizer,
    print_workflow_tree,
)
from temper_ai.observability.models import (
    AgentExecution,
    CollaborationEvent,
    LLMCall,
    StageExecution,
    ToolExecution,
    WorkflowExecution,
)


@pytest.fixture
def simple_workflow():
    """Create a minimal workflow for testing."""
    workflow = WorkflowExecution(
        id="wf-simple",
        workflow_name="simple_workflow",
        workflow_config_snapshot={},
        status="completed",
        duration_seconds=5.2,
        total_tokens=500,
        total_cost_usd=0.015,
        total_llm_calls=1,
        total_tool_calls=1,
    )
    workflow.stages = []
    return workflow


@pytest.fixture
def complex_workflow():
    """Create a complex workflow with nested hierarchy."""
    workflow = WorkflowExecution(
        id="wf-complex",
        workflow_name="complex_workflow",
        workflow_config_snapshot={},
        status="completed",
        duration_seconds=25.8,
        total_tokens=3000,
        total_cost_usd=0.12,
        total_llm_calls=5,
        total_tool_calls=3,
    )

    # Create two stages
    stage1 = StageExecution(
        id="stage-1",
        workflow_execution_id="wf-complex",
        stage_name="planning",
        stage_config_snapshot={},
        status="completed",
        duration_seconds=12.3,
        collaboration_rounds=1,
    )

    stage2 = StageExecution(
        id="stage-2",
        workflow_execution_id="wf-complex",
        stage_name="execution",
        stage_config_snapshot={},
        status="completed",
        duration_seconds=13.5,
        collaboration_rounds=2,
    )

    # Add agents to stage1
    agent1 = AgentExecution(
        id="agent-1",
        stage_execution_id="stage-1",
        agent_name="planner",
        agent_config_snapshot={},
        status="success",
        duration_seconds=8.0,
        total_tokens=1000,
        estimated_cost_usd=0.04,
    )

    # Add LLM call to agent1
    llm1 = LLMCall(
        id="llm-1",
        agent_execution_id="agent-1",
        provider="anthropic",
        model="claude-3",
        status="success",
        latency_ms=800,
        total_tokens=1000,
    )

    # Add tool to agent1
    tool1 = ToolExecution(
        id="tool-1",
        agent_execution_id="agent-1",
        tool_name="search_tool",
        status="success",
        duration_seconds=2.5,
    )

    # Add collaboration event
    collab1 = CollaborationEvent(
        id="collab-1",
        stage_execution_id="stage-1",
        event_type="vote",
        agents_involved=["planner"],
        event_data={"vote": "proceed"},
        outcome="proceed",
        confidence_score=0.92,
    )

    # Build relationships
    agent1.llm_calls = [llm1]
    agent1.tool_executions = [tool1]
    stage1.agents = [agent1]
    stage1.collaboration_events = [collab1]
    stage2.agents = []
    stage2.collaboration_events = []
    workflow.stages = [stage1, stage2]

    return workflow


@pytest.fixture
def failed_workflow():
    """Create a workflow with failed status."""
    workflow = WorkflowExecution(
        id="wf-failed",
        workflow_name="failed_workflow",
        workflow_config_snapshot={},
        status="failed",
        duration_seconds=3.0,
    )

    stage = StageExecution(
        id="stage-failed",
        workflow_execution_id="wf-failed",
        stage_name="failed_stage",
        stage_config_snapshot={},
        status="failed",
        duration_seconds=2.5,
    )

    agent = AgentExecution(
        id="agent-failed",
        stage_execution_id="stage-failed",
        agent_name="failed_agent",
        agent_config_snapshot={},
        status="failed",
        duration_seconds=2.0,
    )

    stage.agents = [agent]
    workflow.stages = [stage]

    return workflow


class TestWorkflowVisualizer:
    """Tests for WorkflowVisualizer class."""

    def test_initialization_defaults(self):
        """Test visualizer initializes with default settings."""
        visualizer = WorkflowVisualizer()
        assert visualizer.verbosity == "standard"
        assert isinstance(visualizer.console, Console)
        assert isinstance(visualizer.start_time, datetime)

    def test_initialization_custom_verbosity(self):
        """Test visualizer initializes with custom verbosity."""
        for verbosity in ["minimal", "standard", "verbose"]:
            visualizer = WorkflowVisualizer(verbosity=verbosity)
            assert visualizer.verbosity == verbosity

    def test_format_duration_milliseconds(self):
        """Test duration formatting for milliseconds."""
        visualizer = WorkflowVisualizer()
        assert visualizer._format_duration(0.001) == "1ms"
        assert visualizer._format_duration(0.123) == "123ms"
        assert visualizer._format_duration(0.999) == "999ms"

    def test_format_duration_seconds(self):
        """Test duration formatting for seconds."""
        visualizer = WorkflowVisualizer()
        assert visualizer._format_duration(1.0) == "1.0s"
        assert visualizer._format_duration(15.5) == "15.5s"
        assert visualizer._format_duration(59.9) == "59.9s"

    def test_format_duration_minutes(self):
        """Test duration formatting for minutes."""
        visualizer = WorkflowVisualizer()
        assert visualizer._format_duration(60) == "1m 0s"
        assert visualizer._format_duration(90) == "1m 30s"
        assert visualizer._format_duration(125.7) == "2m 5s"
        assert visualizer._format_duration(3661) == "61m 1s"

    def test_format_duration_none(self):
        """Test duration formatting with None."""
        visualizer = WorkflowVisualizer()
        assert visualizer._format_duration(None) == "N/A"

    def test_status_icon_success_states(self):
        """Test status icons for success states."""
        visualizer = WorkflowVisualizer()
        assert "✓" in visualizer._status_icon("success")
        assert "✓" in visualizer._status_icon("completed")
        assert "[green]" in visualizer._status_icon("success")

    def test_status_icon_failure_states(self):
        """Test status icons for failure states."""
        visualizer = WorkflowVisualizer()
        assert "✗" in visualizer._status_icon("failed")
        assert "⌛" in visualizer._status_icon("timeout")
        assert "[red]" in visualizer._status_icon("failed")

    def test_status_icon_running_states(self):
        """Test status icons for running/pending states."""
        visualizer = WorkflowVisualizer()
        assert "⏳" in visualizer._status_icon("running")
        assert "[yellow]" in visualizer._status_icon("running")

    def test_status_icon_paused_states(self):
        """Test status icons for paused states."""
        visualizer = WorkflowVisualizer()
        assert "⏸" in visualizer._status_icon("dry_run")
        assert "⏸" in visualizer._status_icon("halted")

    def test_status_icon_unknown(self):
        """Test status icon for unknown status."""
        visualizer = WorkflowVisualizer()
        assert "?" in visualizer._status_icon("unknown_status")
        assert "?" in visualizer._status_icon("invalid")

    def test_format_summary_with_all_metrics(self, complex_workflow):
        """Test summary formatting with all metrics present."""
        visualizer = WorkflowVisualizer()
        summary = visualizer._format_summary(complex_workflow)

        assert "Duration:" in summary
        assert "25.8s" in summary
        assert "Tokens:" in summary
        assert "3,000" in summary
        assert "Cost:" in summary
        assert "$0.1200" in summary
        assert "LLM calls:" in summary
        assert "5" in summary
        assert "Tool calls:" in summary
        assert "3" in summary

    def test_format_summary_with_missing_metrics(self, simple_workflow):
        """Test summary formatting with some metrics missing."""
        # Remove some metrics
        simple_workflow.total_tokens = None
        simple_workflow.total_cost_usd = None

        visualizer = WorkflowVisualizer()
        summary = visualizer._format_summary(simple_workflow)

        assert "Duration:" in summary
        assert "LLM calls:" in summary
        assert "Tokens:" not in summary
        assert "Cost:" not in summary

    def test_format_summary_no_metrics(self):
        """Test summary formatting with no metrics."""
        workflow = WorkflowExecution(
            id="wf-empty",
            workflow_name="empty",
            workflow_config_snapshot={},
            status="running",
        )

        visualizer = WorkflowVisualizer()
        summary = visualizer._format_summary(workflow)

        assert summary == "No metrics"

    def test_display_execution_minimal_mode(self, complex_workflow):
        """Test display_execution in minimal mode shows only stages."""
        visualizer = WorkflowVisualizer(verbosity="minimal")
        console = Console(file=StringIO(), force_terminal=True, width=120)
        visualizer.console = console

        visualizer.display_execution(complex_workflow)
        output = console.file.getvalue()

        # Should show workflow and stages
        assert "complex_workflow" in output
        assert "planning" in output
        assert "execution" in output

        # Should NOT show agents in minimal mode
        assert "planner" not in output

    def test_display_execution_standard_mode(self, complex_workflow):
        """Test display_execution in standard mode shows agents."""
        visualizer = WorkflowVisualizer(verbosity="standard")
        console = Console(file=StringIO(), force_terminal=True, width=120)
        visualizer.console = console

        visualizer.display_execution(complex_workflow)
        output = console.file.getvalue()

        # Should show workflow, stages, and agents
        assert "complex_workflow" in output
        assert "planning" in output
        assert "planner" in output

        # Should NOT show LLM details in standard mode
        assert "claude-3" not in output or "LLM" not in output

    def test_display_execution_verbose_mode(self, complex_workflow):
        """Test display_execution in verbose mode shows all details."""
        visualizer = WorkflowVisualizer(verbosity="verbose")
        console = Console(file=StringIO(), force_terminal=True, width=120)
        visualizer.console = console

        visualizer.display_execution(complex_workflow)
        output = console.file.getvalue()

        # Should show everything
        assert "complex_workflow" in output
        assert "planning" in output
        assert "planner" in output
        assert "claude-3" in output or "LLM" in output
        assert "search_tool" in output or "Tool" in output

    def test_create_workflow_tree_structure(self, complex_workflow):
        """Test _create_workflow_tree builds correct structure."""
        visualizer = WorkflowVisualizer(verbosity="verbose")
        tree = visualizer._create_workflow_tree(complex_workflow)

        assert tree is not None
        assert hasattr(tree, "label")

        # Render and check structure
        console = Console(file=StringIO(), force_terminal=True)
        console.print(tree)
        output = console.file.getvalue()

        assert "complex_workflow" in output

    def test_add_stage_node(self, complex_workflow):
        """Test _add_stage_node adds stage to tree."""
        visualizer = WorkflowVisualizer()
        tree = visualizer._create_workflow_tree(complex_workflow)

        console = Console(file=StringIO(), force_terminal=True)
        console.print(tree)
        output = console.file.getvalue()

        assert "planning" in output
        assert "execution" in output

    def test_add_synthesis_node_with_collaboration(self, complex_workflow):
        """Test _add_synthesis_node shows collaboration info."""
        visualizer = WorkflowVisualizer(verbosity="verbose")
        console = Console(file=StringIO(), force_terminal=True, width=120)
        visualizer.console = console

        visualizer.display_execution(complex_workflow)
        output = console.file.getvalue()

        # Should show synthesis/collaboration info
        assert "Synthesis" in output or "collaboration" in output.lower()

    def test_display_live_returns_context_manager(self, simple_workflow):
        """Test display_live returns Live context manager."""
        visualizer = WorkflowVisualizer()
        console = Console(file=StringIO(), force_terminal=False)
        visualizer.console = console

        live = visualizer.display_live(simple_workflow)

        assert live is not None
        assert hasattr(live, "__enter__")
        assert hasattr(live, "__exit__")

    def test_print_workflow_tree_function(self, simple_workflow):
        """Test convenience function print_workflow_tree."""
        # Should not raise any errors
        with patch("temper_ai.observability.console.WorkflowVisualizer") as mock_viz:
            mock_instance = Mock()
            mock_viz.return_value = mock_instance

            print_workflow_tree(simple_workflow, verbosity="standard")

            mock_viz.assert_called_once_with(verbosity="standard")
            mock_instance.display_execution.assert_called_once_with(simple_workflow)

    def test_failed_workflow_display(self, failed_workflow):
        """Test displaying a failed workflow shows error status."""
        visualizer = WorkflowVisualizer(verbosity="standard")
        console = Console(file=StringIO(), force_terminal=True)
        visualizer.console = console

        visualizer.display_execution(failed_workflow)
        output = console.file.getvalue()

        assert "failed_workflow" in output
        assert "✗" in output  # Failed icon


class TestStreamingVisualizer:
    """Tests for StreamingVisualizer class."""

    def test_initialization(self):
        """Test StreamingVisualizer initialization."""
        visualizer = StreamingVisualizer(
            workflow_id="wf-123",
            verbosity="standard",
            poll_interval=0.5
        )

        assert visualizer.workflow_id == "wf-123"
        assert visualizer.verbosity == "standard"
        assert visualizer.poll_interval == 0.5
        assert visualizer.stop_event is not None
        assert visualizer.live is None

    def test_initialization_defaults(self):
        """Test StreamingVisualizer with default values."""
        visualizer = StreamingVisualizer(workflow_id="wf-456")

        assert visualizer.workflow_id == "wf-456"
        assert visualizer.verbosity == "standard"
        assert visualizer.poll_interval == 0.25

    @patch("temper_ai.storage.database.get_session")
    def test_start_workflow_not_found(self, mock_session):
        """Test start method when workflow not found."""
        # Mock session to return None
        mock_exec = Mock()
        mock_exec.first.return_value = None
        mock_session.return_value.__enter__.return_value.exec.return_value = mock_exec

        visualizer = StreamingVisualizer(workflow_id="wf-nonexistent")
        console = Console(file=StringIO(), force_terminal=False)
        visualizer.console = console

        visualizer.start()

        output = console.file.getvalue()
        assert "not found" in output

    def test_stop_when_not_started(self):
        """Test stop method when not started."""
        visualizer = StreamingVisualizer(workflow_id="wf-123")

        # Should not raise error
        visualizer.stop()
        assert visualizer.stop_event.is_set()

    def test_stop_idempotent(self):
        """Test stop method is idempotent."""
        visualizer = StreamingVisualizer(workflow_id="wf-123")

        visualizer.stop()
        visualizer.stop()  # Should not raise error

        assert visualizer.stop_event.is_set()

    def test_get_border_color_mapping(self):
        """Test _get_border_color returns correct colors."""
        visualizer = StreamingVisualizer(workflow_id="wf-123")

        assert visualizer._get_border_color("running") == "blue"
        assert visualizer._get_border_color("completed") == "green"
        assert visualizer._get_border_color("failed") == "red"
        assert visualizer._get_border_color("timeout") == "red"
        assert visualizer._get_border_color("halted") == "yellow"
        assert visualizer._get_border_color("unknown") == "blue"

    def test_context_manager_entry(self):
        """Test StreamingVisualizer as context manager."""
        visualizer = StreamingVisualizer(workflow_id="wf-123")

        with patch.object(visualizer, "start") as mock_start:
            with patch.object(visualizer, "stop") as mock_stop:
                with visualizer as viz:
                    assert viz is visualizer
                    mock_start.assert_called_once()

                mock_stop.assert_called_once()

    def test_context_manager_exit_on_exception(self):
        """Test StreamingVisualizer stops on exception."""
        visualizer = StreamingVisualizer(workflow_id="wf-123")

        with patch.object(visualizer, "start"):
            with patch.object(visualizer, "stop") as mock_stop:
                try:
                    with visualizer:
                        raise ValueError("Test error")
                except ValueError:
                    pass

                mock_stop.assert_called_once()

    @patch("temper_ai.storage.database.get_session")
    @patch("temper_ai.observability.console.Thread")
    def test_start_creates_update_thread(self, mock_thread, mock_session):
        """Test start method creates update thread."""
        # Mock workflow retrieval
        mock_workflow = Mock()
        mock_workflow.workflow_name = "test_workflow"
        mock_workflow.status = "running"

        mock_exec = Mock()
        mock_exec.first.return_value = mock_workflow
        mock_session.return_value.__enter__.return_value.exec.return_value = mock_exec

        visualizer = StreamingVisualizer(workflow_id="wf-123")
        console = Console(file=StringIO(), force_terminal=False)
        visualizer.console = console

        with patch.object(visualizer, "_create_workflow_tree"):
            visualizer.start()

        # Check thread was created
        mock_thread.assert_called_once()
        call_kwargs = mock_thread.call_args[1]
        assert call_kwargs["daemon"] is True
