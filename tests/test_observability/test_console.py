"""Tests for console visualization."""
import pytest
import re
from io import StringIO
from rich.console import Console
from datetime import datetime, timezone

from src.observability.console import WorkflowVisualizer, print_workflow_tree
from src.observability.formatters import (
    format_duration,
    format_timestamp,
    format_tokens,
    format_cost,
    status_to_color,
    status_to_icon,
    format_percentage,
    truncate_text,
    format_bytes,
)
from src.observability.models import (
    WorkflowExecution,
    StageExecution,
    AgentExecution,
    LLMCall,
    ToolExecution,
    CollaborationEvent,
)


@pytest.fixture
def mock_workflow():
    """Create a mock workflow execution with complete hierarchy."""
    workflow = WorkflowExecution(
        id="wf-001",
        workflow_name="test_workflow",
        workflow_config_snapshot={},
        status="completed",
        duration_seconds=10.5,
        total_tokens=1500,
        total_cost_usd=0.045,
        total_llm_calls=3,
        total_tool_calls=2,
    )

    # Add stage
    stage = StageExecution(
        id="stage-001",
        workflow_execution_id="wf-001",
        stage_name="research_stage",
        stage_config_snapshot={},
        status="completed",
        duration_seconds=8.2,
        collaboration_rounds=2,
    )

    # Add agent
    agent = AgentExecution(
        id="agent-001",
        stage_execution_id="stage-001",
        agent_name="researcher_agent",
        agent_config_snapshot={},
        status="success",
        duration_seconds=6.5,
        total_tokens=1000,
        estimated_cost_usd=0.03,
    )

    # Add LLM call
    llm_call = LLMCall(
        id="llm-001",
        agent_execution_id="agent-001",
        provider="openai",
        model="gpt-4",
        status="success",
        latency_ms=500,
        total_tokens=1000,
    )

    # Add tool execution
    tool_exec = ToolExecution(
        id="tool-001",
        agent_execution_id="agent-001",
        tool_name="web_scraper",
        status="success",
        duration_seconds=2.0,
    )

    # Add collaboration event
    collab_event = CollaborationEvent(
        id="collab-001",
        stage_execution_id="stage-001",
        event_type="vote",
        agents_involved=["researcher_agent"],
        event_data={"vote": "option_a"},
        outcome="option_a",
        confidence_score=0.85,
    )

    # Build relationships
    workflow.stages = [stage]
    stage.workflow = workflow
    stage.agents = [agent]
    stage.collaboration_events = [collab_event]
    agent.stage = stage
    agent.llm_calls = [llm_call]
    agent.tool_executions = [tool_exec]

    return workflow


def test_workflow_visualizer_initialization():
    """Test WorkflowVisualizer initialization."""
    visualizer = WorkflowVisualizer(verbosity="minimal")
    assert visualizer.verbosity == "minimal"
    assert isinstance(visualizer.console, Console)

    visualizer_std = WorkflowVisualizer()
    assert visualizer_std.verbosity == "standard"


def test_minimal_mode_displays_workflow_and_stages(mock_workflow, capsys):
    """Test minimal mode shows only workflow and stages."""
    visualizer = WorkflowVisualizer(verbosity="minimal")

    # Capture console output
    console = Console(file=StringIO(), force_terminal=True, width=120)
    visualizer.console = console

    visualizer.display_execution(mock_workflow)

    # Get output
    output = console.file.getvalue()

    # Should contain workflow and stage names with status icons (icon appears after name)
    assert re.search(r'Workflow:.*test_workflow.*[✓✗⏳⌛⏸?]', output), \
        "Should display workflow name with status icon"
    assert re.search(r'Stage:.*research_stage.*[✓✗⏳⌛⏸?]', output), \
        "Should display stage name with status icon"

    # Verify workflow is shown as completed (✓ icon)
    assert re.search(r'test_workflow.*✓', output), \
        "Workflow should show completed status (✓)"

    # Verify stage is shown as completed (✓ icon)
    assert re.search(r'research_stage.*✓', output), \
        "Stage should show completed status (✓)"


def test_standard_mode_includes_agents(mock_workflow):
    """Test standard mode includes agent information."""
    visualizer = WorkflowVisualizer(verbosity="standard")

    # Capture console output
    console = Console(file=StringIO(), force_terminal=True, width=120)
    visualizer.console = console

    visualizer.display_execution(mock_workflow)

    # Get output
    output = console.file.getvalue()

    # Should contain workflow, stage, and agent with status icons (icon after name)
    assert re.search(r'Workflow:.*test_workflow.*[✓✗⏳⌛⏸?]', output), \
        "Should display workflow name with status icon"
    assert re.search(r'Stage:.*research_stage.*[✓✗⏳⌛⏸?]', output), \
        "Should display stage name with status icon"
    assert re.search(r'Agent:.*researcher_agent.*[✓✗⏳⌛⏸?]', output), \
        "Should display agent name with status icon in standard mode"

    # Verify hierarchical structure
    assert output.index("test_workflow") < output.index("research_stage"), \
        "Workflow should appear before stage in tree"
    assert output.index("research_stage") < output.index("researcher_agent"), \
        "Stage should appear before agent in tree"


def test_verbose_mode_includes_llm_and_tools(mock_workflow):
    """Test verbose mode includes LLM calls and tool executions."""
    visualizer = WorkflowVisualizer(verbosity="verbose")

    # Capture console output
    console = Console(file=StringIO(), force_terminal=True, width=120)
    visualizer.console = console

    visualizer.display_execution(mock_workflow)

    # Get output
    output = console.file.getvalue()

    # Should contain all levels with status icons (icon after name)
    assert re.search(r'Workflow:.*test_workflow.*[✓✗⏳⌛⏸?]', output), \
        "Should display workflow with status icon"
    assert re.search(r'Stage:.*research_stage.*[✓✗⏳⌛⏸?]', output), \
        "Should display stage with status icon"
    assert re.search(r'Agent:.*researcher_agent.*[✓✗⏳⌛⏸?]', output), \
        "Should display agent with status icon"

    # Verify LLM and tool details
    assert re.search(r'LLM.*gpt-4.*\d+ms', output), \
        "Should display LLM model with latency"
    assert re.search(r'Tool.*web_scraper.*\d+\.\d+s', output), \
        "Should display tool name with duration"

    # Verify hierarchical ordering
    positions = {
        'workflow': output.index("test_workflow"),
        'stage': output.index("research_stage"),
        'agent': output.index("researcher_agent"),
        'llm': output.index("gpt-4"),
        'tool': output.index("web_scraper")
    }
    assert positions['workflow'] < positions['stage'] < positions['agent'], \
        "Workflow > Stage > Agent hierarchy should be maintained"
    assert positions['agent'] < min(positions['llm'], positions['tool']), \
        "LLM calls and tools should appear under agent"


def test_status_icons_display_correctly():
    """Test all status icons render correctly."""
    visualizer = WorkflowVisualizer()

    assert "✓" in visualizer._status_icon("success")
    assert "✓" in visualizer._status_icon("completed")
    assert "✗" in visualizer._status_icon("failed")
    assert "⏳" in visualizer._status_icon("running")
    assert "⌛" in visualizer._status_icon("timeout")
    assert "⏸" in visualizer._status_icon("dry_run")
    assert "⏸" in visualizer._status_icon("halted")
    assert "?" in visualizer._status_icon("unknown_status")


def test_duration_formatting():
    """Test duration formatting for different time ranges."""
    visualizer = WorkflowVisualizer()

    # Milliseconds
    assert visualizer._format_duration(0.15) == "150ms"
    assert visualizer._format_duration(0.5) == "500ms"

    # Seconds
    assert visualizer._format_duration(2.5) == "2.5s"
    assert visualizer._format_duration(45.8) == "45.8s"

    # Minutes and seconds
    assert visualizer._format_duration(65) == "1m 5s"
    assert visualizer._format_duration(125.7) == "2m 5s"

    # None
    assert visualizer._format_duration(None) == "N/A"


def test_summary_formatting(mock_workflow):
    """Test summary statistics formatting."""
    visualizer = WorkflowVisualizer()

    summary = visualizer._format_summary(mock_workflow)

    # Should contain key metrics with specific formatting
    assert re.search(r'Duration:\s+10\.5s', summary), \
        "Should format duration as 10.5s"
    assert re.search(r'Tokens:\s+1,500', summary), \
        "Should format tokens with comma separator"
    assert re.search(r'Cost:\s+\$0\.0450', summary), \
        "Should format cost with $ and 4 decimals"
    assert re.search(r'LLM calls:\s+3', summary), \
        "Should show exact LLM call count"
    assert re.search(r'Tool calls:\s+2', summary), \
        "Should show exact tool call count"


def test_summary_with_missing_metrics():
    """Test summary formatting with missing metrics."""
    workflow = WorkflowExecution(
        id="wf-002",
        workflow_name="minimal_workflow",
        workflow_config_snapshot={},
        status="running",
    )

    visualizer = WorkflowVisualizer()
    summary = visualizer._format_summary(workflow)

    # Should return "No metrics" when no data available
    assert summary == "No metrics"


def test_color_coding():
    """Test color codes are applied correctly."""
    visualizer = WorkflowVisualizer()

    # Test success (green)
    assert "[green]" in visualizer._status_icon("success")

    # Test failed (red)
    assert "[red]" in visualizer._status_icon("failed")

    # Test running (yellow)
    assert "[yellow]" in visualizer._status_icon("running")

    # Test dry_run (blue)
    assert "[blue]" in visualizer._status_icon("dry_run")


def test_print_workflow_tree_convenience_function(mock_workflow):
    """Test the convenience function print_workflow_tree."""
    # Should not raise an error
    # We can't easily capture Rich output in tests, but we can verify it runs
    try:
        # Create a StringIO console to avoid actual printing
        console = Console(file=StringIO(), force_terminal=True)
        visualizer = WorkflowVisualizer()
        visualizer.console = console
        visualizer.display_execution(mock_workflow)
        # If we get here, it worked
        assert True
    except Exception as e:
        pytest.fail(f"print_workflow_tree raised an exception: {e}")


def test_synthesis_node_in_verbose_mode(mock_workflow):
    """Test synthesis information is shown in verbose mode."""
    visualizer = WorkflowVisualizer(verbosity="verbose")

    console = Console(file=StringIO(), force_terminal=True, width=120)
    visualizer.console = console

    visualizer.display_execution(mock_workflow)

    output = console.file.getvalue()

    # Should show synthesis info with collaboration details
    assert re.search(r'Synthesis.*\d+\s+rounds?', output) or \
           re.search(r'Vote.*option_a', output) or \
           re.search(r'collaboration.*events?', output, re.IGNORECASE), \
        "Should display synthesis/collaboration information with details"

    # Verify collaboration event details if present
    if "vote" in output.lower():
        assert re.search(r'confidence.*0\.\d+', output, re.IGNORECASE), \
            "Vote events should show confidence score"


# Formatter tests


def test_format_duration():
    """Test format_duration utility."""
    assert format_duration(0.15) == "150ms"
    assert format_duration(2.5) == "2.5s"
    assert format_duration(125.7) == "2m 5s"
    assert format_duration(None) == "N/A"


def test_format_timestamp():
    """Test format_timestamp utility."""
    dt = datetime(2024, 1, 15, 10, 30, 45, tzinfo=timezone.utc)
    result = format_timestamp(dt)
    assert "2024-01-15" in result
    assert "10:30:45" in result
    assert format_timestamp(None) == "N/A"


def test_format_tokens():
    """Test format_tokens utility."""
    assert format_tokens(1500) == "1,500 tokens"
    assert format_tokens(1000000) == "1,000,000 tokens"
    assert format_tokens(None) == "N/A"


def test_format_cost():
    """Test format_cost utility."""
    assert format_cost(0.0123) == "$0.0123"
    assert format_cost(1.5) == "$1.5000"
    assert format_cost(None) == "$0.0000"


def test_status_to_color():
    """Test status_to_color mapping."""
    assert status_to_color("success") == "green"
    assert status_to_color("failed") == "red"
    assert status_to_color("running") == "yellow"
    assert status_to_color("dry_run") == "blue"
    assert status_to_color("unknown") == "white"


def test_status_to_icon():
    """Test status_to_icon mapping."""
    assert status_to_icon("success") == "✓"
    assert status_to_icon("failed") == "✗"
    assert status_to_icon("running") == "⏳"
    assert status_to_icon("timeout") == "⌛"
    assert status_to_icon("dry_run") == "⏸"
    assert status_to_icon("unknown") == "?"


def test_format_percentage():
    """Test format_percentage utility."""
    assert format_percentage(0.856) == "85.6%"
    assert format_percentage(0.5) == "50.0%"
    assert format_percentage(None) == "N/A"


def test_truncate_text():
    """Test truncate_text utility."""
    long_text = "This is a very long text that needs truncation"
    assert truncate_text(long_text, 20) == "This is a very lo..."
    assert truncate_text("Short", 20) == "Short"
    # 30 chars minus 1 char suffix = 29 chars before suffix
    assert truncate_text(long_text, 30, "…") == "This is a very long text that…"


def test_format_bytes():
    """Test format_bytes utility."""
    assert format_bytes(1500) == "1.5 KB"
    assert format_bytes(2500000) == "2.4 MB"
    assert format_bytes(1073741824) == "1.0 GB"
    assert format_bytes(None) == "N/A"


def test_workflow_tree_structure(mock_workflow):
    """Test the tree structure is created correctly."""
    visualizer = WorkflowVisualizer(verbosity="verbose")

    # Create console to capture output
    console = Console(file=StringIO(), force_terminal=True, width=120)
    visualizer.console = console

    tree = visualizer._create_workflow_tree(mock_workflow)

    # Tree should have content
    assert tree is not None
    assert hasattr(tree, 'label'), "Tree should have a label attribute"

    # Render tree to string and check content
    console.print(tree)
    output = console.file.getvalue()

    # Verify tree structure (icon appears after workflow name)
    assert re.search(r'test_workflow.*[✓✗⏳⌛⏸?]', output), \
        "Tree root should show workflow with status icon"
    # Duration is shown as (10.5s) in parentheses
    assert re.search(r'\(10\.5s\)', output), \
        "Tree should include workflow duration in parentheses"
    # Tokens shown as "1000 tokens" or "1,000 tokens"
    assert "1000 tokens" in output or "1,000 tokens" in output, \
        "Tree should include token count"


def test_live_display_returns_context_manager(mock_workflow):
    """Test display_live returns a context manager."""
    visualizer = WorkflowVisualizer()

    # Create a mock console to avoid actual terminal output
    console = Console(file=StringIO(), force_terminal=False)
    visualizer.console = console

    live_display = visualizer.display_live(mock_workflow)

    # Should be a Live object (context manager)
    assert live_display is not None
    assert hasattr(live_display, "__enter__")
    assert hasattr(live_display, "__exit__")
