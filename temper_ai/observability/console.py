"""Console visualization for workflow execution using Rich."""
import logging
import time
from datetime import datetime, timezone
from threading import Event, Thread
from typing import Any, Optional

from rich import box
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.tree import Tree

logger = logging.getLogger(__name__)

# Refresh rate and poll interval constants
LIVE_DISPLAY_REFRESH_PER_SECOND = 4
STREAMING_POLL_INTERVAL_SECONDS = 0.25
FINAL_STATE_DISPLAY_DURATION_SECONDS = 1.0


class WorkflowVisualizer:
    """Visualizes workflow execution in console using Rich."""

    def __init__(self, verbosity: str = "standard"):
        """Initialize visualizer.

        Args:
            verbosity: Display level - minimal | standard | verbose
        """
        self.console = Console()
        self.verbosity = verbosity
        self.start_time = datetime.now(timezone.utc)

    def display_execution(self, workflow_execution: Any) -> None:
        """Display complete workflow execution tree.

        Args:
            workflow_execution: WorkflowExecution model instance with loaded relationships

        Example:
            >>> from temper_ai.storage.database import get_session
            >>> from sqlmodel import select
            >>> with get_session() as session:
            ...     workflow = session.exec(
            ...         select(WorkflowExecution).where(WorkflowExecution.id == "wf-001")
            ...     ).first()
            ...     visualizer = WorkflowVisualizer(verbosity="standard")
            ...     visualizer.display_execution(workflow)
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

    def display_live(self, workflow_execution: Any) -> Live:
        """Display workflow execution with live updates.

        Use this for streaming real-time progress during execution.

        Args:
            workflow_execution: WorkflowExecution being monitored

        Example:
            >>> visualizer = WorkflowVisualizer(verbosity="verbose")
            >>> with visualizer.display_live(workflow) as live_display:
            ...     # Workflow executes here
            ...     # Display updates automatically
            ...     pass
        """
        with Live(
            self._create_workflow_tree(workflow_execution),
            refresh_per_second=LIVE_DISPLAY_REFRESH_PER_SECOND,
            console=self.console
        ) as live:
            # Update loop would go here (for real-time updates)
            # This is a placeholder for Milestone 2 real-time streaming
            return live

    def _create_workflow_tree(self, workflow_exec: Any) -> Tree:
        """Create tree representation of workflow.

        Args:
            workflow_exec: WorkflowExecution model instance

        Returns:
            Rich Tree object representing the workflow hierarchy
        """
        # Root node
        duration_str = self._format_duration(workflow_exec.duration_seconds)
        tree = Tree(
            f"[bold cyan]Workflow: {workflow_exec.workflow_name}[/] "
            f"[dim]({duration_str})[/] "
            f"{self._status_icon(workflow_exec.status)}"
        )

        # Add stages (always shown in minimal mode)
        for stage in workflow_exec.stages:
            stage_node = self._add_stage_node(tree, stage)
            self._populate_stage_details(stage_node, stage)

        return tree

    def _populate_stage_details(self, stage_node: Tree, stage: Any) -> None:
        """Populate stage node with agents and collaboration info based on verbosity."""
        if self.verbosity in ["standard", "verbose"]:
            # Add agents in standard and verbose modes
            for agent in stage.agents:
                agent_node = self._add_agent_node(stage_node, agent)
                self._populate_agent_details(agent_node, agent)

            # Add synthesis/collaboration info in standard and verbose modes
            if stage.collaboration_events:
                self._add_synthesis_node(stage_node, stage)

    def _populate_agent_details(self, agent_node: Tree, agent: Any) -> None:
        """Populate agent node with LLM and tool calls in verbose mode."""
        if self.verbosity == "verbose":
            # Add LLM calls in verbose mode
            for llm_call in agent.llm_calls:
                self._add_llm_node(agent_node, llm_call)

            # Add tool calls in verbose mode
            for tool_call in agent.tool_executions:
                self._add_tool_node(agent_node, tool_call)

    def _add_stage_node(self, parent_tree: Tree, stage: Any) -> Tree:
        """Add stage node to tree.

        Args:
            parent_tree: Parent Tree to add this stage to
            stage: StageExecution model instance

        Returns:
            Tree node for this stage
        """
        duration_str = self._format_duration(stage.duration_seconds)
        stage_node = parent_tree.add(
            f"[bold yellow]Stage: {stage.stage_name}[/] "
            f"[dim]({duration_str})[/] "
            f"{self._status_icon(stage.status)}"
        )
        return stage_node

    def _add_agent_node(self, parent_tree: Tree, agent: Any) -> Tree:
        """Add agent node to tree.

        Args:
            parent_tree: Parent Tree to add this agent to
            agent: AgentExecution model instance

        Returns:
            Tree node for this agent
        """
        duration_str = self._format_duration(agent.duration_seconds)
        agent_node = parent_tree.add(
            f"[green]Agent: {agent.agent_name}[/] "
            f"[dim]({duration_str})[/] "
            f"{self._status_icon(agent.status)}"
        )
        return agent_node

    def _add_llm_node(self, parent_tree: Tree, llm_call: Any) -> None:
        """Add LLM call node to tree.

        Args:
            parent_tree: Parent Tree to add this LLM call to
            llm_call: LLMCall model instance
        """
        latency_str = f"{llm_call.latency_ms}ms" if llm_call.latency_ms else "N/A"
        tokens_str = f"{llm_call.total_tokens} tokens" if llm_call.total_tokens else ""

        parent_tree.add(
            f"[blue]LLM: {llm_call.model}[/] "
            f"[dim]({latency_str}, {tokens_str})[/] "
            f"{self._status_icon(llm_call.status)}"
        )

    def _add_tool_node(self, parent_tree: Tree, tool_exec: Any) -> None:
        """Add tool execution node to tree.

        Args:
            parent_tree: Parent Tree to add this tool execution to
            tool_exec: ToolExecution model instance
        """
        duration_str = self._format_duration(tool_exec.duration_seconds)
        parent_tree.add(
            f"[magenta]Tool: {tool_exec.tool_name}[/] "
            f"[dim]({duration_str})[/] "
            f"{self._status_icon(tool_exec.status)}"
        )

    def _add_synthesis_node(self, parent_tree: Tree, stage: Any) -> None:
        """Add synthesis/collaboration node.

        Args:
            parent_tree: Parent Tree to add synthesis info to
            stage: StageExecution model instance with collaboration_events
        """
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
        """Return colored status icon.

        Args:
            status: Status string (success, failed, running, etc.)

        Returns:
            Rich formatted status icon
        """
        icons = {
            "success": "[green]✓[/]",
            "completed": "[green]✓[/]",
            "failed": "[red]✗[/]",
            "running": "[yellow]⏳[/]",
            "timeout": "[red]⌛[/]",
            "dry_run": "[blue]⏸[/]",
            "halted": "[yellow]⏸[/]",
        }
        return icons.get(status, "[dim]?[/]")

    def _format_duration(self, seconds: Optional[float]) -> str:
        """Format duration in human-readable form.

        Args:
            seconds: Duration in seconds

        Returns:
            Formatted duration string (e.g., "150ms", "2.5s", "3m 45s")
        """
        if seconds is None:
            return "N/A"
        if seconds < 1:
            return f"{int(seconds * 1000)}ms"
        if seconds < 60:
            return f"{seconds:.1f}s"
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{minutes}m {secs}s"

    def _format_summary(self, workflow_exec: Any) -> str:
        """Format summary statistics.

        Args:
            workflow_exec: WorkflowExecution model instance

        Returns:
            Formatted summary string with metrics
        """
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


def print_workflow_tree(workflow_execution: Any, verbosity: str = "standard") -> None:
    """Convenience function to print workflow execution tree.

    Args:
        workflow_execution: WorkflowExecution model with relationships loaded
        verbosity: Display level - minimal | standard | verbose

    Example:
        >>> from temper_ai.storage.database.models import WorkflowExecution
        >>> from temper_ai.storage.database import get_session
        >>> from sqlmodel import select
        >>> with get_session() as session:
        ...     workflow = session.exec(
        ...         select(WorkflowExecution).where(WorkflowExecution.id == "wf-001")
        ...     ).first()
        ...     print_workflow_tree(workflow, verbosity="verbose")
    """
    visualizer = WorkflowVisualizer(verbosity=verbosity)
    visualizer.display_execution(workflow_execution)


class StreamingVisualizer(WorkflowVisualizer):
    """Real-time streaming visualizer for workflow execution.

    Polls the database for updates and displays progress live as the
    workflow executes. Shows spinners for running tasks and updates
    metrics in real-time.
    """

    def __init__(self, workflow_id: str, verbosity: str = "standard",
                 poll_interval: float = STREAMING_POLL_INTERVAL_SECONDS):
        """Initialize streaming visualizer.

        Args:
            workflow_id: ID of workflow to monitor
            verbosity: Display level - minimal | standard | verbose
            poll_interval: How often to poll database (seconds)
        """
        super().__init__(verbosity=verbosity)
        self.workflow_id = workflow_id
        self.poll_interval = poll_interval
        self.stop_event = Event()
        self.update_thread: Optional[Thread] = None
        self.live: Optional[Live] = None

    def start(self) -> None:
        """Start streaming updates.

        Begins polling the database and updating the display in real-time.

        Example:
            >>> visualizer = StreamingVisualizer("wf-001", verbosity="verbose")
            >>> visualizer.start()
            >>> # Workflow executes...
            >>> visualizer.stop()
        """
        # Get initial state
        from sqlmodel import select

        from temper_ai.storage.database import get_session
        from temper_ai.storage.database.models import WorkflowExecution

        with get_session() as session:
            workflow = session.exec(
                select(WorkflowExecution).where(WorkflowExecution.id == self.workflow_id)
            ).first()

            if not workflow:
                self.console.print(f"[red]Workflow {self.workflow_id} not found[/]")
                return

            # Create initial display while workflow is attached to session
            initial_tree = self._create_workflow_tree(workflow)
            workflow_name = workflow.workflow_name  # Store name before detaching

        # Start live display
        initial_panel = Panel(
            initial_tree,
            title=f"[bold]Workflow Execution: {workflow_name}[/]",
            subtitle="Starting...",
            border_style="blue",
            box=box.ROUNDED
        )

        self.live = Live(
            initial_panel,
            refresh_per_second=LIVE_DISPLAY_REFRESH_PER_SECOND,
            console=self.console
        )
        self.live.start()

        # Start update thread
        self.update_thread = Thread(target=self._update_loop, daemon=True)
        self.update_thread.start()

    def stop(self) -> None:
        """Stop streaming updates and finalize display."""
        if self.stop_event.is_set():
            return  # Already stopped

        self.stop_event.set()

        if self.update_thread and self.update_thread.is_alive():
            self.update_thread.join(timeout=2.0)

        if self.live:
            self.live.stop()

    def _update_loop(self) -> None:
        """Poll database and update display continuously."""
        from sqlmodel import select

        from temper_ai.storage.database import get_session
        from temper_ai.storage.database.models import WorkflowExecution

        while not self.stop_event.is_set():
            try:
                # Query latest execution state
                with get_session() as session:
                    workflow = session.exec(
                        select(WorkflowExecution).where(
                            WorkflowExecution.id == self.workflow_id
                        )
                    ).first()

                    if not workflow:
                        break

                    # Create updated tree
                    tree = self._create_workflow_tree(workflow)

                    # Create panel with updated summary
                    panel = Panel(
                        tree,
                        title=f"[bold]Workflow Execution: {workflow.workflow_name}[/]",
                        subtitle=self._format_summary(workflow),
                        border_style=self._get_border_color(workflow.status),
                        box=box.ROUNDED
                    )

                    # Update display
                    if self.live:
                        self.live.update(panel)

                    # Stop if workflow completed/failed
                    if workflow.status in ["completed", "failed", "timeout", "halted"]:
                        # Wait a bit to show final state
                        time.sleep(FINAL_STATE_DISPLAY_DURATION_SECONDS)  # Intentional blocking: brief pause to display final workflow state in UI thread
                        break

            except Exception as e:
                # OB-08: Log error instead of silently swallowing it.
                logger.debug(f"Error in _update_loop polling: {e}")

            # Wait before next poll
            time.sleep(self.poll_interval)  # Intentional blocking: polling interval for UI update thread

    def _get_border_color(self, status: str) -> str:
        """Get border color based on workflow status.

        Args:
            status: Workflow status

        Returns:
            Rich color name for border
        """
        colors = {
            "running": "blue",
            "completed": "green",
            "failed": "red",
            "timeout": "red",
            "halted": "yellow",
        }
        return colors.get(status, "blue")

    def __enter__(self) -> "StreamingVisualizer":
        """Context manager entry."""
        self.start()
        return self

    def __exit__(self, _exc_type: Any, _exc_val: Any, _exc_tb: Any) -> None:
        """Context manager exit."""
        self.stop()
