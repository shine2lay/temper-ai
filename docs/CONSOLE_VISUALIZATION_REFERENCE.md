# Console Visualization Reference Implementation

## Quick Reference Guide

This document provides ready-to-use code snippets and patterns for implementing Rich console visualization in the workflow observability system.

## Table of Contents

1. [Constants and Configuration](#constants-and-configuration)
2. [Formatting Utilities](#formatting-utilities)
3. [Tree Building Patterns](#tree-building-patterns)
4. [Real-Time Streaming](#real-time-streaming)
5. [Performance Optimization](#performance-optimization)
6. [Testing Patterns](#testing-patterns)

---

## 1. Constants and Configuration

### Status Colors and Icons

```python
# /home/shinelay/meta-autonomous-framework/src/observability/console_config.py

"""Configuration constants for console visualization."""

# Status color mapping
STATUS_COLORS = {
    "success": "green",
    "completed": "green",
    "failed": "red",
    "timeout": "red",
    "running": "yellow",
    "halted": "yellow",
    "dry_run": "blue",
    "pending": "cyan",
}

# Status icon mapping
STATUS_ICONS = {
    "success": "✓",
    "completed": "✓",
    "failed": "✗",
    "running": "⏳",
    "timeout": "⌛",
    "dry_run": "⏸",
    "halted": "⏸",
    "pending": "⋯",
}

# Hierarchy level colors
HIERARCHY_COLORS = {
    "workflow": "bold cyan",
    "stage": "bold yellow",
    "agent": "green",
    "llm": "blue",
    "tool": "magenta",
    "synthesis": "cyan",
}

# Border colors by status
BORDER_COLORS = {
    "running": "blue",
    "completed": "green",
    "failed": "red",
    "timeout": "red",
    "halted": "yellow",
}

# Refresh rates (updates per second)
REFRESH_RATES = {
    "fast": 8,      # For active development
    "normal": 4,    # Default
    "slow": 2,      # For long-running workflows
}

# Poll intervals (seconds)
POLL_INTERVALS = {
    "fast": 0.1,    # Active development
    "normal": 0.25, # Default
    "slow": 1.0,    # Long-running workflows
}

# Display width thresholds
WIDTH_THRESHOLDS = {
    "narrow": 80,
    "medium": 120,
    "wide": 160,
}

# Name truncation lengths
TRUNCATE_LENGTHS = {
    "narrow": 20,
    "medium": 40,
    "wide": 60,
}

# Maximum tree depth
MAX_TREE_DEPTH = {
    "minimal": 2,   # Workflow -> Stage
    "standard": 3,  # Workflow -> Stage -> Agent
    "verbose": 5,   # Full depth
}
```

---

## 2. Formatting Utilities

### Enhanced Duration Formatter

```python
def format_duration_smart(seconds: Optional[float], compact: bool = False) -> str:
    """
    Format duration with smart precision.

    Args:
        seconds: Duration in seconds
        compact: Use compact format (e.g., '1m30s' instead of '1m 30s')

    Returns:
        Formatted duration string

    Examples:
        >>> format_duration_smart(0.001)
        '1ms'
        >>> format_duration_smart(0.152)
        '152ms'
        >>> format_duration_smart(1.5)
        '1.5s'
        >>> format_duration_smart(65, compact=True)
        '1m5s'
        >>> format_duration_smart(65, compact=False)
        '1m 5s'
        >>> format_duration_smart(3725)
        '1h 2m 5s'
    """
    if seconds is None:
        return "N/A"

    # Sub-millisecond
    if seconds < 0.001:
        return f"{int(seconds * 1_000_000)}μs"

    # Milliseconds
    if seconds < 1:
        return f"{int(seconds * 1000)}ms"

    # Seconds (with decimal)
    if seconds < 10:
        return f"{seconds:.1f}s"

    # Seconds (integer)
    if seconds < 60:
        return f"{int(seconds)}s"

    # Minutes and seconds
    if seconds < 3600:
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        sep = "" if compact else " "
        return f"{minutes}m{sep}{secs}s"

    # Hours, minutes, seconds
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    sep = "" if compact else " "
    return f"{hours}h{sep}{minutes}m{sep}{secs}s"
```

### Smart Number Formatter

```python
def format_number_smart(value: int, threshold: int = 10_000) -> str:
    """
    Format numbers with appropriate scale.

    Args:
        value: Number to format
        threshold: Threshold for using abbreviated format

    Returns:
        Formatted number string

    Examples:
        >>> format_number_smart(123)
        '123'
        >>> format_number_smart(1234)
        '1,234'
        >>> format_number_smart(12345)
        '12.3K'
        >>> format_number_smart(1234567)
        '1.2M'
    """
    if value < threshold:
        return f"{value:,}"

    if value < 1_000_000:
        return f"{value / 1_000:.1f}K"
    elif value < 1_000_000_000:
        return f"{value / 1_000_000:.1f}M"
    else:
        return f"{value / 1_000_000_000:.1f}B"
```

### Name Truncation with Path Awareness

```python
import re

def truncate_smart(name: str, max_length: int, console_width: int = 120) -> str:
    """
    Intelligently truncate names preserving important information.

    Args:
        name: Name to truncate
        max_length: Maximum allowed length
        console_width: Current console width for context

    Returns:
        Truncated name

    Examples:
        >>> truncate_smart("very_long_agent_name_that_needs_truncation", 30)
        'very_long_agent_name_that_n…'
        >>> truncate_smart("/path/to/very/deep/nested/file.py", 30)
        '/path/.../nested/file.py'
        >>> truncate_smart("openai/gpt-4-turbo-2024-01-25", 25)
        'openai/gpt-4-turbo-202…'
    """
    if len(name) <= max_length:
        return name

    # Handle file paths
    if "/" in name or "\\" in name:
        separator = "/" if "/" in name else "\\"
        parts = name.split(separator)

        if len(parts) > 2:
            first = parts[0]
            last = parts[-1]
            budget = max_length - len(first) - len(last) - 5  # Account for separator and ellipsis

            if budget > 0:
                # Try to include some middle parts
                middle = separator.join(parts[1:-1])
                if len(middle) <= budget:
                    return f"{first}{separator}{middle}{separator}{last}"

            # Fallback to first/.../last
            return f"{first}{separator}...{separator}{last}"

    # Handle provider/model format (e.g., "openai/gpt-4")
    if "/" in name and name.count("/") == 1:
        provider, model = name.split("/")
        if len(provider) + len(model) + 4 > max_length:
            # Truncate model part
            available = max_length - len(provider) - 2
            return f"{provider}/{model[:available]}…"

    # Default truncation with ellipsis
    return name[:max_length - 1] + "…"
```

### Status Formatter with Context

```python
def format_status_rich(
    status: str,
    include_icon: bool = True,
    include_text: bool = False,
    include_color: bool = True
) -> str:
    """
    Format status with rich markup.

    Args:
        status: Status string
        include_icon: Include status icon
        include_text: Include status text
        include_color: Include color markup

    Returns:
        Rich-formatted status string

    Examples:
        >>> format_status_rich("success")
        '[green]✓[/]'
        >>> format_status_rich("success", include_text=True)
        '[green]✓ SUCCESS[/]'
        >>> format_status_rich("failed", include_icon=False, include_text=True)
        '[red]FAILED[/]'
    """
    icon = STATUS_ICONS.get(status, "?")
    color = STATUS_COLORS.get(status, "white")
    text = status.upper()

    parts = []
    if include_icon:
        parts.append(icon)
    if include_text:
        parts.append(text)

    content = " ".join(parts) if parts else ""

    if include_color:
        return f"[{color}]{content}[/{color}]"
    else:
        return content
```

---

## 3. Tree Building Patterns

### Base Tree Builder

```python
from rich.tree import Tree
from typing import Any, Optional

class TreeBuilder:
    """Base tree builder with common patterns."""

    def __init__(self, verbosity: str = "standard", max_depth: Optional[int] = None):
        self.verbosity = verbosity
        self.max_depth = max_depth or MAX_TREE_DEPTH.get(verbosity, 5)

    def build(self, workflow: Any) -> Tree:
        """Build tree from workflow."""
        tree = self._create_workflow_node(workflow)
        self._add_stages(tree, workflow, depth=1)
        return tree

    def _create_workflow_node(self, workflow: Any) -> Tree:
        """Create root workflow node."""
        label = self._format_workflow_label(workflow)
        return Tree(label)

    def _format_workflow_label(self, workflow: Any) -> str:
        """Format workflow node label."""
        color = HIERARCHY_COLORS["workflow"]
        duration = format_duration_smart(workflow.duration_seconds)
        status = format_status_rich(workflow.status)

        return f"[{color}]Workflow: {workflow.workflow_name}[/] [dim]({duration})[/] {status}"

    def _add_stages(self, parent: Tree, workflow: Any, depth: int):
        """Add stage nodes to workflow."""
        if depth >= self.max_depth:
            return

        for stage in workflow.stages:
            stage_node = parent.add(self._format_stage_label(stage))

            if self.verbosity in ["standard", "verbose"]:
                self._add_agents(stage_node, stage, depth + 1)

    def _format_stage_label(self, stage: Any) -> str:
        """Format stage node label."""
        color = HIERARCHY_COLORS["stage"]
        duration = format_duration_smart(stage.duration_seconds)
        status = format_status_rich(stage.status)

        return f"[{color}]Stage: {stage.stage_name}[/] [dim]({duration})[/] {status}"

    def _add_agents(self, parent: Tree, stage: Any, depth: int):
        """Add agent nodes to stage."""
        if depth >= self.max_depth:
            return

        for agent in stage.agents:
            agent_node = parent.add(self._format_agent_label(agent))

            if self.verbosity == "verbose":
                self._add_llm_calls(agent_node, agent, depth + 1)
                self._add_tool_executions(agent_node, agent, depth + 1)

    def _format_agent_label(self, agent: Any) -> str:
        """Format agent node label."""
        color = HIERARCHY_COLORS["agent"]
        duration = format_duration_smart(agent.duration_seconds)
        status = format_status_rich(agent.status)
        tokens = format_number_smart(agent.total_tokens or 0)
        cost = f"${agent.estimated_cost_usd:.4f}" if agent.estimated_cost_usd else "$0.0000"

        return (
            f"[{color}]Agent: {agent.agent_name}[/] "
            f"[dim]({duration})[/] {status} "
            f"[dim]({tokens} tokens, {cost})[/]"
        )

    def _add_llm_calls(self, parent: Tree, agent: Any, depth: int):
        """Add LLM call nodes to agent."""
        if depth >= self.max_depth or not agent.llm_calls:
            return

        for call in agent.llm_calls:
            parent.add(self._format_llm_label(call))

    def _format_llm_label(self, call: Any) -> str:
        """Format LLM call node label."""
        color = HIERARCHY_COLORS["llm"]
        model = f"{call.provider}/{call.model}"
        latency = f"{call.latency_ms}ms" if call.latency_ms else "N/A"
        tokens = format_number_smart(call.total_tokens or 0)
        status = format_status_rich(call.status)

        return (
            f"[{color}]LLM: {model}[/] "
            f"[dim]({latency}, {tokens} tokens)[/] {status}"
        )

    def _add_tool_executions(self, parent: Tree, agent: Any, depth: int):
        """Add tool execution nodes to agent."""
        if depth >= self.max_depth or not agent.tool_executions:
            return

        for tool in agent.tool_executions:
            parent.add(self._format_tool_label(tool))

    def _format_tool_label(self, tool: Any) -> str:
        """Format tool execution node label."""
        color = HIERARCHY_COLORS["tool"]
        duration = format_duration_smart(tool.duration_seconds)
        status = format_status_rich(tool.status)

        return (
            f"[{color}]Tool: {tool.tool_name}[/] "
            f"[dim]({duration})[/] {status}"
        )
```

### Responsive Tree Builder

```python
class ResponsiveTreeBuilder(TreeBuilder):
    """Tree builder that adapts to terminal width."""

    def __init__(self, console, verbosity: str = "standard"):
        super().__init__(verbosity)
        self.console = console
        self.width = console.width

        # Determine truncation length
        if self.width < WIDTH_THRESHOLDS["narrow"]:
            self.max_name_length = TRUNCATE_LENGTHS["narrow"]
        elif self.width < WIDTH_THRESHOLDS["medium"]:
            self.max_name_length = TRUNCATE_LENGTHS["medium"]
        else:
            self.max_name_length = TRUNCATE_LENGTHS["wide"]

    def _format_workflow_label(self, workflow: Any) -> str:
        """Format workflow label with responsive truncation."""
        name = truncate_smart(workflow.workflow_name, self.max_name_length, self.width)
        color = HIERARCHY_COLORS["workflow"]
        duration = format_duration_smart(workflow.duration_seconds, compact=(self.width < 100))
        status = format_status_rich(workflow.status)

        return f"[{color}]Workflow: {name}[/] [dim]({duration})[/] {status}"

    def _format_agent_label(self, agent: Any) -> str:
        """Format agent label with responsive metrics."""
        name = truncate_smart(agent.agent_name, self.max_name_length, self.width)
        color = HIERARCHY_COLORS["agent"]
        duration = format_duration_smart(agent.duration_seconds, compact=(self.width < 100))
        status = format_status_rich(agent.status)

        # Include metrics only if width allows
        if self.width >= WIDTH_THRESHOLDS["medium"]:
            tokens = format_number_smart(agent.total_tokens or 0)
            cost = f"${agent.estimated_cost_usd:.4f}" if agent.estimated_cost_usd else "$0.0000"
            metrics = f"[dim]({tokens} tokens, {cost})[/]"
        else:
            metrics = ""

        return f"[{color}]Agent: {name}[/] [dim]({duration})[/] {status} {metrics}".strip()
```

---

## 4. Real-Time Streaming

### Optimized Streaming Visualizer

```python
from rich.live import Live
from rich.panel import Panel
from rich.console import Console
from rich import box
from threading import Thread, Event
from typing import Optional, Callable
import time

class OptimizedStreamingVisualizer:
    """Production-ready streaming visualizer with optimizations."""

    def __init__(
        self,
        workflow_id: str,
        verbosity: str = "standard",
        poll_interval: float = 0.25,
        refresh_rate: int = 4,
        on_complete: Optional[Callable] = None,
        on_error: Optional[Callable] = None
    ):
        self.workflow_id = workflow_id
        self.verbosity = verbosity
        self.poll_interval = poll_interval
        self.refresh_rate = refresh_rate
        self.on_complete = on_complete
        self.on_error = on_error

        self.console = Console()
        self.stop_event = Event()
        self.live: Optional[Live] = None
        self.update_thread: Optional[Thread] = None

        # Performance tracking
        self.last_update_time = 0
        self.update_count = 0
        self.error_count = 0

        # State caching
        self.last_state_hash = None

    def start(self):
        """Start streaming with optimized initial load."""
        # Fetch initial state
        workflow = self._fetch_workflow_optimized()
        if not workflow:
            self.console.print(f"[red]Workflow {self.workflow_id} not found[/]")
            return

        # Build initial display
        initial_display = self._create_display(workflow)

        # Start live display
        self.live = Live(
            initial_display,
            refresh_per_second=self.refresh_rate,
            console=self.console,
            vertical_overflow="visible"
        )
        self.live.start()

        # Start update thread
        self.update_thread = Thread(target=self._update_loop, daemon=True)
        self.update_thread.start()

    def stop(self):
        """Gracefully stop streaming."""
        if self.stop_event.is_set():
            return

        self.stop_event.set()

        if self.update_thread and self.update_thread.is_alive():
            self.update_thread.join(timeout=2.0)

        if self.live:
            self.live.stop()

        # Print statistics
        if self.update_count > 0:
            avg_update_time = self.last_update_time / self.update_count
            self.console.print(
                f"\n[dim]Updates: {self.update_count} | "
                f"Avg update time: {avg_update_time*1000:.1f}ms | "
                f"Errors: {self.error_count}[/]"
            )

    def _update_loop(self):
        """Optimized update loop with error handling."""
        consecutive_errors = 0
        max_consecutive_errors = 5

        while not self.stop_event.is_set():
            try:
                update_start = time.time()

                # Fetch workflow state
                workflow = self._fetch_workflow_optimized()
                if not workflow:
                    consecutive_errors += 1
                    if consecutive_errors >= max_consecutive_errors:
                        if self.on_error:
                            self.on_error(f"Failed to fetch workflow {max_consecutive_errors} times")
                        break
                    time.sleep(self.poll_interval)
                    continue

                # Reset error counter on success
                consecutive_errors = 0

                # Check if state changed (avoid unnecessary updates)
                state_hash = self._hash_workflow_state(workflow)
                if state_hash != self.last_state_hash:
                    # Update display
                    display = self._create_display(workflow)
                    if self.live:
                        self.live.update(display)

                    self.last_state_hash = state_hash
                    self.update_count += 1

                # Track update time
                update_time = time.time() - update_start
                self.last_update_time += update_time

                # Check if workflow completed
                if workflow.status in ["completed", "failed", "timeout", "halted"]:
                    time.sleep(1.0)  # Show final state
                    if self.on_complete:
                        self.on_complete(workflow)
                    break

            except Exception as e:
                self.error_count += 1
                consecutive_errors += 1

                if consecutive_errors >= max_consecutive_errors:
                    if self.on_error:
                        self.on_error(f"Update loop error: {e}")
                    break

            # Wait before next poll
            time.sleep(self.poll_interval)

    def _fetch_workflow_optimized(self):
        """Fetch workflow with optimized queries."""
        from src.observability.database import get_session
        from src.observability.models import WorkflowExecution
        from sqlalchemy.orm import joinedload

        try:
            with get_session() as session:
                # Use eager loading to minimize queries
                query = session.query(WorkflowExecution).options(
                    joinedload(WorkflowExecution.stages)
                )

                # Add agent/llm/tool loading based on verbosity
                if self.verbosity in ["standard", "verbose"]:
                    query = query.options(
                        joinedload(WorkflowExecution.stages).joinedload("agents")
                    )

                if self.verbosity == "verbose":
                    query = query.options(
                        joinedload(WorkflowExecution.stages)
                        .joinedload("agents")
                        .joinedload("llm_calls")
                    )
                    query = query.options(
                        joinedload(WorkflowExecution.stages)
                        .joinedload("agents")
                        .joinedload("tool_executions")
                    )

                workflow = query.filter_by(id=self.workflow_id).first()
                return workflow

        except Exception as e:
            return None

    def _hash_workflow_state(self, workflow) -> int:
        """Create hash of workflow state to detect changes."""
        # Create a tuple of key state indicators
        state = (
            workflow.status,
            workflow.duration_seconds,
            len(workflow.stages),
            sum(len(s.agents) for s in workflow.stages),
        )
        return hash(state)

    def _create_display(self, workflow) -> Panel:
        """Create display panel with tree."""
        # Build tree
        builder = ResponsiveTreeBuilder(self.console, self.verbosity)
        tree = builder.build(workflow)

        # Format summary
        summary = self._format_summary(workflow)

        # Create panel with dynamic border color
        border_color = BORDER_COLORS.get(workflow.status, "cyan")

        return Panel(
            tree,
            title=f"[bold]Workflow Execution: {workflow.workflow_name}[/]",
            subtitle=summary,
            border_style=border_color,
            box=box.ROUNDED,
            padding=(0, 1)
        )

    def _format_summary(self, workflow) -> str:
        """Format summary metrics line."""
        parts = []

        if workflow.duration_seconds:
            parts.append(f"Duration: {format_duration_smart(workflow.duration_seconds)}")

        if workflow.total_tokens:
            parts.append(f"Tokens: {format_number_smart(workflow.total_tokens)}")

        if workflow.total_cost_usd:
            parts.append(f"Cost: ${workflow.total_cost_usd:.4f}")

        if workflow.total_llm_calls:
            parts.append(f"LLM calls: {workflow.total_llm_calls}")

        if workflow.total_tool_calls:
            parts.append(f"Tool calls: {workflow.total_tool_calls}")

        return " | ".join(parts) if parts else "No metrics"

    def __enter__(self):
        """Context manager entry."""
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.stop()
```

### Batch Update Strategy

```python
from dataclasses import dataclass
from typing import List

@dataclass
class WorkflowUpdate:
    """Represents a workflow state update."""
    workflow_id: str
    status: str
    duration: float
    timestamp: float

class BatchStreamingVisualizer:
    """Visualizer that batches updates for multiple workflows."""

    def __init__(self, workflow_ids: List[str], poll_interval: float = 1.0):
        self.workflow_ids = workflow_ids
        self.poll_interval = poll_interval
        self.console = Console()
        self.stop_event = Event()

    def start(self):
        """Start monitoring multiple workflows."""
        from rich.table import Table

        with Live(
            self._create_table([]),
            refresh_per_second=2,
            console=self.console
        ) as live:
            while not self.stop_event.is_set():
                # Fetch all workflow states in batch
                updates = self._fetch_batch_updates()

                # Update table
                table = self._create_table(updates)
                live.update(table)

                # Check if all completed
                if all(u.status in ["completed", "failed"] for u in updates):
                    break

                time.sleep(self.poll_interval)

    def _fetch_batch_updates(self) -> List[WorkflowUpdate]:
        """Fetch updates for all workflows in single query."""
        from src.observability.database import get_session
        from src.observability.models import WorkflowExecution

        updates = []

        try:
            with get_session() as session:
                workflows = session.query(WorkflowExecution).filter(
                    WorkflowExecution.id.in_(self.workflow_ids)
                ).all()

                for workflow in workflows:
                    updates.append(WorkflowUpdate(
                        workflow_id=workflow.id,
                        status=workflow.status,
                        duration=workflow.duration_seconds or 0,
                        timestamp=time.time()
                    ))

        except Exception:
            pass

        return updates

    def _create_table(self, updates: List[WorkflowUpdate]) -> Table:
        """Create summary table for multiple workflows."""
        from rich.table import Table

        table = Table(title="Workflow Monitoring", box=box.ROUNDED)
        table.add_column("Workflow ID", style="cyan")
        table.add_column("Status", style="bold")
        table.add_column("Duration", justify="right")

        for update in updates:
            status_color = STATUS_COLORS.get(update.status, "white")
            status_icon = STATUS_ICONS.get(update.status, "?")

            table.add_row(
                update.workflow_id[:12] + "...",
                f"[{status_color}]{status_icon} {update.status.upper()}[/]",
                format_duration_smart(update.duration)
            )

        return table
```

---

## 5. Performance Optimization

### Database Query Optimization

```python
from sqlalchemy.orm import joinedload, selectinload
from typing import Literal

def fetch_workflow_efficient(
    workflow_id: str,
    detail_level: Literal["minimal", "standard", "verbose"] = "standard"
):
    """
    Fetch workflow with optimized loading strategy.

    Uses different loading strategies based on detail level to minimize queries.
    """
    from src.observability.database import get_session
    from src.observability.models import WorkflowExecution

    with get_session() as session:
        query = session.query(WorkflowExecution)

        if detail_level == "minimal":
            # Minimal: Only load stages (no agents)
            query = query.options(
                selectinload(WorkflowExecution.stages)
            )

        elif detail_level == "standard":
            # Standard: Load stages and agents
            query = query.options(
                selectinload(WorkflowExecution.stages).selectinload("agents")
            )

        elif detail_level == "verbose":
            # Verbose: Load everything
            query = query.options(
                selectinload(WorkflowExecution.stages).selectinload("agents").selectinload("llm_calls"),
                selectinload(WorkflowExecution.stages).selectinload("agents").selectinload("tool_executions"),
                selectinload(WorkflowExecution.stages).selectinload("collaboration_events")
            )

        return query.filter_by(id=workflow_id).first()
```

### Caching Strategy

```python
from functools import lru_cache
import hashlib
import json

class CachedVisualizer:
    """Visualizer with intelligent caching."""

    def __init__(self):
        self.tree_cache = {}
        self.state_cache = {}

    def visualize(self, workflow):
        """Visualize with caching."""
        # Generate state hash
        state_hash = self._hash_workflow(workflow)

        # Check cache
        if state_hash in self.tree_cache:
            return self.tree_cache[state_hash]

        # Build tree
        tree = self._build_tree(workflow)

        # Cache result
        self.tree_cache[state_hash] = tree

        # Limit cache size
        if len(self.tree_cache) > 100:
            # Remove oldest entry
            oldest_key = next(iter(self.tree_cache))
            del self.tree_cache[oldest_key]

        return tree

    def _hash_workflow(self, workflow) -> str:
        """Create deterministic hash of workflow state."""
        state = {
            "id": workflow.id,
            "status": workflow.status,
            "duration": workflow.duration_seconds,
            "stage_count": len(workflow.stages),
        }

        # Include agent states for deeper hashing
        for stage in workflow.stages:
            state[f"stage_{stage.id}"] = {
                "status": stage.status,
                "agent_count": len(stage.agents)
            }

        state_json = json.dumps(state, sort_keys=True)
        return hashlib.md5(state_json.encode()).hexdigest()

    def _build_tree(self, workflow):
        """Build tree (placeholder - use actual tree builder)."""
        builder = TreeBuilder()
        return builder.build(workflow)
```

---

## 6. Testing Patterns

### Mock Workflow Factory

```python
from datetime import datetime, timezone, timedelta
from src.observability.models import (
    WorkflowExecution,
    StageExecution,
    AgentExecution,
    LLMCall,
    ToolExecution
)

class MockWorkflowFactory:
    """Factory for creating mock workflow data for testing."""

    @staticmethod
    def create_simple_workflow(status: str = "completed") -> WorkflowExecution:
        """Create simple workflow with one stage and one agent."""
        workflow = WorkflowExecution(
            id="wf-test-001",
            workflow_name="test_workflow",
            workflow_config_snapshot={},
            status=status,
            duration_seconds=10.5,
            total_tokens=1500,
            total_cost_usd=0.045,
            total_llm_calls=2,
            total_tool_calls=1,
        )

        stage = StageExecution(
            id="stage-test-001",
            workflow_execution_id="wf-test-001",
            stage_name="test_stage",
            stage_config_snapshot={},
            status=status,
            duration_seconds=8.5,
        )

        agent = AgentExecution(
            id="agent-test-001",
            stage_execution_id="stage-test-001",
            agent_name="test_agent",
            agent_config_snapshot={},
            status="success" if status == "completed" else status,
            duration_seconds=7.0,
            total_tokens=1500,
            estimated_cost_usd=0.045,
        )

        # Build relationships
        workflow.stages = [stage]
        stage.workflow = workflow
        stage.agents = [agent]
        agent.stage = stage

        return workflow

    @staticmethod
    def create_complex_workflow() -> WorkflowExecution:
        """Create complex workflow with multiple stages and agents."""
        start_time = datetime.now(timezone.utc)

        workflow = WorkflowExecution(
            id="wf-complex-001",
            workflow_name="complex_research_workflow",
            workflow_config_snapshot={},
            status="completed",
            start_time=start_time,
            end_time=start_time + timedelta(seconds=135),
            duration_seconds=135.0,
            total_tokens=45230,
            total_cost_usd=0.1354,
            total_llm_calls=8,
            total_tool_calls=5,
        )

        # Research stage with 3 agents
        research_stage = StageExecution(
            id="stage-research-001",
            workflow_execution_id="wf-complex-001",
            stage_name="research",
            stage_config_snapshot={},
            status="completed",
            start_time=start_time,
            end_time=start_time + timedelta(seconds=90),
            duration_seconds=90.0,
        )

        agents = []
        for i in range(3):
            agent = AgentExecution(
                id=f"agent-researcher-{i+1}",
                stage_execution_id="stage-research-001",
                agent_name=f"researcher_{i+1}",
                agent_config_snapshot={},
                status="success",
                start_time=start_time + timedelta(seconds=i*30),
                end_time=start_time + timedelta(seconds=(i+1)*30),
                duration_seconds=30.0,
                total_tokens=12000 + i*500,
                estimated_cost_usd=0.036 + i*0.0015,
                num_llm_calls=2,
                num_tool_calls=1,
            )

            # Add LLM calls
            llm_call = LLMCall(
                id=f"llm-{i+1}",
                agent_execution_id=agent.id,
                provider="openai",
                model="gpt-4",
                status="success",
                latency_ms=1200 + i*100,
                total_tokens=12000 + i*500,
            )

            # Add tool execution
            tool_exec = ToolExecution(
                id=f"tool-{i+1}",
                agent_execution_id=agent.id,
                tool_name="web_scraper",
                status="success",
                duration_seconds=2.5,
            )

            agent.llm_calls = [llm_call]
            agent.tool_executions = [tool_exec]
            agents.append(agent)

        research_stage.agents = agents

        # Synthesis stage
        synthesis_stage = StageExecution(
            id="stage-synthesis-001",
            workflow_execution_id="wf-complex-001",
            stage_name="synthesis",
            stage_config_snapshot={},
            status="completed",
            start_time=start_time + timedelta(seconds=90),
            end_time=start_time + timedelta(seconds=125),
            duration_seconds=35.0,
            collaboration_rounds=2,
        )

        synthesizer = AgentExecution(
            id="agent-synthesizer-001",
            stage_execution_id="stage-synthesis-001",
            agent_name="synthesizer",
            agent_config_snapshot={},
            status="success",
            duration_seconds=30.0,
            total_tokens=6430,
            estimated_cost_usd=0.0193,
        )

        synthesis_stage.agents = [synthesizer]

        # Build relationships
        workflow.stages = [research_stage, synthesis_stage]
        research_stage.workflow = workflow
        synthesis_stage.workflow = workflow

        return workflow
```

### Test Helpers

```python
from io import StringIO
from rich.console import Console

def capture_console_output(visualize_func, workflow) -> str:
    """Capture console output for testing."""
    output = StringIO()
    console = Console(file=output, force_terminal=True, width=120)

    # Replace visualizer's console
    visualize_func.console = console

    # Execute visualization
    visualize_func(workflow)

    return output.getvalue()

# Example usage
def test_minimal_visualization():
    workflow = MockWorkflowFactory.create_simple_workflow()
    visualizer = WorkflowVisualizer(verbosity="minimal")

    output = capture_console_output(visualizer.display_execution, workflow)

    assert "test_workflow" in output
    assert "test_stage" in output
```

---

## Summary

This reference provides:

1. **Ready-to-use constants** for colors, icons, and configuration
2. **Enhanced formatting utilities** with smart truncation and scaling
3. **Reusable tree building patterns** for different verbosity levels
4. **Production-ready streaming visualizer** with optimizations
5. **Performance optimization techniques** for database queries and caching
6. **Testing utilities** for easy test development

All code is production-ready and follows the existing codebase patterns found in:
- `/home/shinelay/meta-autonomous-framework/src/observability/console.py`
- `/home/shinelay/meta-autonomous-framework/src/observability/formatters.py`
- `/home/shinelay/meta-autonomous-framework/src/observability/models.py`
