# Task: m1-02-observability-console - Implement Rich console visualization for workflow traces

**Priority:** CRITICAL
**Effort:** 2-3 hours
**Status:** pending
**Owner:** unassigned

---

## Summary

Implement console visualization using Rich library to display workflow execution in real-time. Create waterfall-style tree views showing workflow → stages → agents → LLM/tool calls with timing, status icons, and verbosity levels (minimal/standard/verbose).

---

## Files to Create

- `src/observability/console.py` - Main console visualizer
- `src/observability/formatters.py` - Formatting utilities (colors, icons, timing)
- `tests/test_observability/test_console.py` - Console visualization tests

---

## Acceptance Criteria

### Core Functionality
- [x] - [ ] WorkflowVisualizer class with display_execution method
- [x] - [ ] Tree-based waterfall view (workflow → stages → agents → calls)
- [x] - [ ] Three verbosity modes: minimal, standard, verbose
- [x] - [ ] Status icons (✓ success, ✗ failed, ⏳ running, ⌛ timeout, ⏸ dry_run)
- [x] - [ ] Color coding (green=success, red=fail, yellow=running, blue=dry_run, dim=metadata)
- [x] - [ ] Duration display for all levels

### Verbosity Levels
- [x] - [ ] **Minimal**: Workflow + stage names + status only
- [x] - [ ] **Standard**: + Agent names + synthesis info
- [x] - [ ] **Verbose**: + LLM calls + tool calls + votes/decisions

### Display Features
- [x] - [ ] Real-time streaming updates (as execution progresses)
- [x] - [ ] Progress indicators for running stages/agents
- [x] - [ ] Summary statistics (total time, tokens, cost)
- [x] - [ ] Error highlighting with error messages
- [x] - [ ] Indent properly for hierarchy

### Testing
- [x] - [ ] Test minimal mode output
- [x] - [ ] Test standard mode output
- [x] - [ ] Test verbose mode output
- [x] - [ ] Test all status icons render correctly
- [x] - [ ] Test color coding
- [x] - [ ] Coverage > 85%

### Documentation
- [x] - [ ] Docstrings for visualizer class
- [x] - [ ] Usage examples in docstrings
- [x] - [ ] Type hints throughout

---

## Implementation Details

**src/observability/console.py:**

```python
"""Console visualization for workflow execution using Rich."""
from typing import Optional, List
from rich.tree import Tree
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich import box
from datetime import datetime


class WorkflowVisualizer:
    """Visualizes workflow execution in console using Rich."""

    def __init__(self, verbosity: str = "standard"):
        """Initialize visualizer.

        Args:
            verbosity: Display level - minimal | standard | verbose
        """
        self.console = Console()
        self.verbosity = verbosity
        self.start_time = datetime.utcnow()

    def display_execution(self, workflow_execution):
        """Display complete workflow execution tree.

        Args:
            workflow_execution: WorkflowExecution model instance with loaded relationships
        """
        # Create root tree
        tree = self._create_workflow_tree(workflow_execution)

        # Display in panel
        panel = Panel(
            tree,
            title=f"[bold]Workflow Execution: {workflow_execution.workflow_name}[/]",
            subtitle=self._format_summary(workflow_execution),
            border_style="blue",
            box=box.ROUNDED
        )

        self.console.print(panel)

    def display_live(self, workflow_execution):
        """Display workflow execution with live updates.

        Use this for streaming real-time progress.

        Args:
            workflow_execution: WorkflowExecution being monitored
        """
        with Live(self._create_workflow_tree(workflow_execution), refresh_per_second=4) as live:
            # Update loop would go here (for real-time updates)
            # For now, just static display
            pass

    def _create_workflow_tree(self, workflow_exec) -> Tree:
        """Create tree representation of workflow."""
        # Root node
        duration_str = self._format_duration(workflow_exec.duration_seconds)
        tree = Tree(
            f"[bold cyan]Workflow: {workflow_exec.workflow_name}[/] "
            f"[dim]({duration_str})[/] "
            f"{self._status_icon(workflow_exec.status)}"
        )

        # Add stages
        for stage in workflow_exec.stages:
            stage_node = self._add_stage_node(tree, stage)

            if self.verbosity in ["standard", "verbose"]:
                # Add agents
                for agent in stage.agents:
                    agent_node = self._add_agent_node(stage_node, agent)

                    if self.verbosity == "verbose":
                        # Add LLM calls
                        for llm_call in agent.llm_calls:
                            self._add_llm_node(agent_node, llm_call)

                        # Add tool calls
                        for tool_call in agent.tool_executions:
                            self._add_tool_node(agent_node, tool_call)

                # Add synthesis if exists
                if stage.collaboration_events:
                    self._add_synthesis_node(stage_node, stage)

        return tree

    def _add_stage_node(self, parent_tree: Tree, stage) -> Tree:
        """Add stage node to tree."""
        duration_str = self._format_duration(stage.duration_seconds)
        stage_node = parent_tree.add(
            f"[bold yellow]Stage: {stage.stage_name}[/] "
            f"[dim]({duration_str})[/] "
            f"{self._status_icon(stage.status)}"
        )
        return stage_node

    def _add_agent_node(self, parent_tree: Tree, agent) -> Tree:
        """Add agent node to tree."""
        duration_str = self._format_duration(agent.duration_seconds)
        agent_node = parent_tree.add(
            f"[green]Agent: {agent.agent_name}[/] "
            f"[dim]({duration_str})[/] "
            f"{self._status_icon(agent.status)}"
        )
        return agent_node

    def _add_llm_node(self, parent_tree: Tree, llm_call):
        """Add LLM call node to tree."""
        latency_str = f"{llm_call.latency_ms}ms" if llm_call.latency_ms else "N/A"
        tokens_str = f"{llm_call.total_tokens} tokens" if llm_call.total_tokens else ""

        parent_tree.add(
            f"[blue]LLM: {llm_call.model}[/] "
            f"[dim]({latency_str}, {tokens_str})[/] "
            f"{self._status_icon(llm_call.status)}"
        )

    def _add_tool_node(self, parent_tree: Tree, tool_exec):
        """Add tool execution node to tree."""
        duration_str = self._format_duration(tool_exec.duration_seconds)
        parent_tree.add(
            f"[magenta]Tool: {tool_exec.tool_name}[/] "
            f"[dim]({duration_str})[/] "
            f"{self._status_icon(tool_exec.status)}"
        )

    def _add_synthesis_node(self, parent_tree: Tree, stage):
        """Add synthesis/collaboration node."""
        if stage.collaboration_rounds:
            synthesis_node = parent_tree.add(
                f"[cyan]Synthesis: {stage.collaboration_rounds} rounds[/] "
                f"{self._status_icon('success')}"
            )

            # In verbose mode, show votes/decisions
            if self.verbosity == "verbose":
                for event in stage.collaboration_events:
                    if event.event_type == "vote" and event.event_data:
                        agent_name = event.agents_involved[0] if event.agents_involved else "unknown"
                        decision = event.outcome or "N/A"
                        confidence = event.confidence_score or 0.0
                        synthesis_node.add(
                            f"[dim]Vote: {agent_name} → {decision} "
                            f"(confidence: {confidence:.2f})[/]"
                        )

    def _status_icon(self, status: str) -> str:
        """Return colored status icon."""
        icons = {
            "success": "[green]✓[/]",
            "completed": "[green]✓[/]",
            "failed": "[red]✗[/]",
            "running": "[yellow]⏳[/]",
            "timeout": "[red]⌛[/]",
            "dry_run": "[blue]⏸[/]",
        }
        return icons.get(status, "[dim]?[/]")

    def _format_duration(self, seconds: Optional[float]) -> str:
        """Format duration in human-readable form."""
        if seconds is None:
            return "N/A"
        if seconds < 1:
            return f"{int(seconds * 1000)}ms"
        if seconds < 60:
            return f"{seconds:.1f}s"
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{minutes}m {secs}s"

    def _format_summary(self, workflow_exec) -> str:
        """Format summary statistics."""
        parts = []

        if workflow_exec.duration_seconds:
            parts.append(f"Duration: {self._format_duration(workflow_exec.duration_seconds)}")

        if workflow_exec.total_tokens:
            parts.append(f"Tokens: {workflow_exec.total_tokens:,}")

        if workflow_exec.total_cost_usd:
            parts.append(f"Cost: ${workflow_exec.total_cost_usd:.4f}")

        if workflow_exec.total_llm_calls:
            parts.append(f"LLM calls: {workflow_exec.total_llm_calls}")

        if workflow_exec.total_tool_calls:
            parts.append(f"Tool calls: {workflow_exec.total_tool_calls}")

        return " | ".join(parts) if parts else "No metrics"


def print_workflow_tree(workflow_execution, verbosity: str = "standard"):
    """Convenience function to print workflow execution tree.

    Args:
        workflow_execution: WorkflowExecution model with relationships loaded
        verbosity: minimal | standard | verbose
    """
    visualizer = WorkflowVisualizer(verbosity=verbosity)
    visualizer.display_execution(workflow_execution)
```

**Example usage:**

```python
from src.observability.models import WorkflowExecution
from src.observability.console import print_workflow_tree
from src.observability.database import get_session

# Load workflow with all relationships
with get_session() as session:
    workflow = session.query(WorkflowExecution).filter_by(id="some-id").first()

    # Load relationships (stages, agents, etc.)
    # ... (use joinedload for efficiency)

    # Display in console
    print_workflow_tree(workflow, verbosity="standard")
```

---

## Test Strategy

```python
def test_minimal_mode():
    # Create mock workflow with stages
    workflow = create_mock_workflow()
    visualizer = WorkflowVisualizer(verbosity="minimal")
    # Capture console output
    # Assert only workflow + stages shown

def test_standard_mode():
    # Should include agents + synthesis

def test_verbose_mode():
    # Should include LLM/tool calls + votes

def test_status_icons():
    # Test all status types render correct icons

def test_color_coding():
    # Test different statuses have different colors
```

---

## Success Metrics

- [x] - [ ] Tree visualization displays correctly
- [x] - [ ] All three verbosity modes work
- [x] - [ ] Status icons and colors render correctly
- [x] - [ ] Duration formatting works (ms, s, m:s)
- [x] - [ ] Summary statistics display correctly
- [x] - [ ] Tests pass with > 85% coverage

---

## Dependencies

- **Blocked by:** m1-00-structure (completed)
- **Blocks:** m1-07-integration
- **Integrates with:** m1-01-observability-db (uses models)

---

## Design References

- TECHNICAL_SPECIFICATION.md Section 8.2: Console Visualization
- Rich library docs: https://rich.readthedocs.io/
- Rich Tree examples: https://rich.readthedocs.io/en/latest/tree.html

---

## Notes

- Use Rich's Tree for hierarchy visualization
- Use Rich's Panel for nice borders
- Use Rich's Live for real-time updates (Milestone 2)
- Colors: green=good, red=bad, yellow=in-progress, blue=info, dim=metadata
- Keep output compact - don't overwhelm with info in standard mode
