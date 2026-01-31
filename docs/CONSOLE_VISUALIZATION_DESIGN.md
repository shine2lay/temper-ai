# Rich Console Visualization Design - Workflow Traces

## Overview

This document provides comprehensive UI/UX recommendations for implementing console visualization of workflow execution traces using the Rich library. The design supports three verbosity levels, real-time streaming updates, and a clear hierarchical view of workflow execution data.

## Table of Contents

1. [Verbosity Levels](#verbosity-levels)
2. [Color Scheme and Icons](#color-scheme-and-icons)
3. [Layout and Hierarchy](#layout-and-hierarchy)
4. [Real-Time Updates with Rich Live](#real-time-updates-with-rich-live)
5. [Edge Case Handling](#edge-case-handling)
6. [Accessibility Considerations](#accessibility-considerations)
7. [Implementation Examples](#implementation-examples)

---

## 1. Verbosity Levels

### Minimal Mode (`verbosity="minimal"`)

**Purpose**: Quick status overview for monitoring multiple workflows or CI/CD pipelines.

**Display Elements**:
- Workflow name, status, and duration
- Stage names with status and duration
- Summary metrics (total tokens, cost, LLM/tool calls)

**What to Hide**:
- Individual agent executions
- LLM call details
- Tool execution details
- Collaboration events

**Layout Example**:
```
┌─────────────────────────────────────────────────────────────────────────────┐
│ Workflow Execution: complex_research_workflow                              │
│ Duration: 2m 15s | Tokens: 45,230 | Cost: $0.1354 | LLM calls: 12         │
└─────────────────────────────────────────────────────────────────────────────┘

Workflow: complex_research_workflow (2m 15s) ✓
├── Stage: research (1m 30s) ✓
├── Stage: synthesis (35s) ✓
└── Stage: review (10s) ✓
```

**When to Use**:
- Monitoring multiple concurrent workflows
- CI/CD pipeline status checks
- Quick health checks
- Dashboard displays

---

### Standard Mode (`verbosity="standard"`)

**Purpose**: Default mode for interactive development and debugging. Shows agent-level execution without overwhelming detail.

**Display Elements**:
- Workflow, stages, and agents
- Agent-level metrics (tokens, cost, duration)
- Collaboration/synthesis information
- Summary metrics

**What to Hide**:
- Individual LLM call details
- Individual tool execution details
- Request/response payloads

**Layout Example**:
```
┌─────────────────────────────────────────────────────────────────────────────┐
│ Workflow Execution: complex_research_workflow                              │
│ Duration: 2m 15s | Tokens: 45,230 | Cost: $0.1354 | LLM calls: 12         │
└─────────────────────────────────────────────────────────────────────────────┘

Workflow: complex_research_workflow (2m 15s) ✓
├── Stage: research (1m 30s) ✓
│   ├── Agent: researcher_1 (45s) ✓ (12,500 tokens, $0.0375)
│   ├── Agent: researcher_2 (42s) ✓ (11,200 tokens, $0.0336)
│   └── Agent: researcher_3 (48s) ✓ (13,100 tokens, $0.0393)
├── Stage: synthesis (35s) ✓
│   ├── Agent: synthesizer (30s) ✓ (6,430 tokens, $0.0193)
│   └── Synthesis: 2 rounds ✓
└── Stage: review (10s) ✓
    └── Agent: reviewer (10s) ✓ (2,000 tokens, $0.0057)
```

**When to Use**:
- Default interactive development
- Post-execution analysis
- Debugging agent-level issues
- Understanding collaboration patterns

---

### Verbose Mode (`verbosity="verbose"`)

**Purpose**: Complete execution trace for deep debugging and optimization.

**Display Elements**:
- Everything from standard mode
- Individual LLM calls with model, latency, tokens
- Individual tool executions with duration
- Collaboration votes and decisions
- Detailed metadata

**Layout Example**:
```
┌─────────────────────────────────────────────────────────────────────────────┐
│ Workflow Execution: complex_research_workflow                              │
│ Duration: 2m 15s | Tokens: 45,230 | Cost: $0.1354 | LLM calls: 12         │
└─────────────────────────────────────────────────────────────────────────────┘

Workflow: complex_research_workflow (2m 15s) ✓
├── Stage: research (1m 30s) ✓
│   ├── Agent: researcher_1 (45s) ✓ (12,500 tokens, $0.0375)
│   │   ├── LLM: openai/gpt-4 (1,250ms, 8,000 tokens) ✓
│   │   ├── Tool: web_scraper (2.5s) ✓
│   │   ├── LLM: openai/gpt-4 (980ms, 4,500 tokens) ✓
│   │   └── Tool: pdf_parser (1.2s) ✓
│   ├── Agent: researcher_2 (42s) ✓ (11,200 tokens, $0.0336)
│   │   ├── LLM: anthropic/claude-3-sonnet (1,100ms, 7,200 tokens) ✓
│   │   └── Tool: api_client (3.1s) ✓
│   └── Agent: researcher_3 (48s) ✓ (13,100 tokens, $0.0393)
│       ├── LLM: openai/gpt-4-turbo (950ms, 9,500 tokens) ✓
│       ├── Tool: database_query (1.8s) ✓
│       └── LLM: openai/gpt-4-turbo (1,050ms, 3,600 tokens) ✓
├── Stage: synthesis (35s) ✓
│   ├── Agent: synthesizer (30s) ✓ (6,430 tokens, $0.0193)
│   │   ├── LLM: openai/gpt-4 (1,400ms, 6,430 tokens) ✓
│   │   └── Tool: markdown_formatter (500ms) ✓
│   └── Synthesis: 2 rounds ✓
│       ├── Vote: researcher_1 → option_a (confidence: 0.85)
│       ├── Vote: researcher_2 → option_b (confidence: 0.72)
│       └── Vote: researcher_3 → option_a (confidence: 0.91)
└── Stage: review (10s) ✓
    └── Agent: reviewer (10s) ✓ (2,000 tokens, $0.0057)
        └── LLM: openai/gpt-4 (850ms, 2,000 tokens) ✓
```

**When to Use**:
- Performance optimization
- Cost analysis
- LLM provider comparison
- Debugging specific LLM/tool failures
- Understanding exact execution flow

---

## 2. Color Scheme and Icons

### Status Colors

Use semantic colors that work across different terminal themes:

```python
STATUS_COLORS = {
    # Success states
    "success": "green",
    "completed": "green",

    # Error states
    "failed": "red",
    "timeout": "red",

    # Warning/intermediate states
    "running": "yellow",
    "halted": "yellow",

    # Info states
    "dry_run": "blue",
    "pending": "cyan",

    # Default
    "unknown": "white",
}
```

### Status Icons

Use clear, universally recognizable icons:

```python
STATUS_ICONS = {
    # Success
    "success": "✓",      # U+2713 Check Mark
    "completed": "✓",

    # Error
    "failed": "✗",       # U+2717 Ballot X

    # In Progress
    "running": "⏳",      # U+23F3 Hourglass

    # Time-related
    "timeout": "⌛",      # U+231B Hourglass Done

    # Paused/Stopped
    "dry_run": "⏸",      # U+23F8 Pause Button
    "halted": "⏸",

    # Pending
    "pending": "⋯",      # U+22EF Midline Ellipsis

    # Unknown
    "unknown": "?",
}
```

### Hierarchy Colors

Different colors for different levels to aid visual scanning:

```python
HIERARCHY_COLORS = {
    "workflow": "bold cyan",       # Top-level, most important
    "stage": "bold yellow",        # Second level
    "agent": "green",              # Third level
    "llm": "blue",                 # Detail level
    "tool": "magenta",             # Detail level
    "synthesis": "cyan",           # Special collaboration node
}
```

### Metric Colors

Use dim colors for supplementary information:

```python
METRIC_COLORS = {
    "duration": "dim white",
    "tokens": "dim white",
    "cost": "dim yellow",          # Slightly highlighted
    "count": "dim white",
}
```

---

## 3. Layout and Hierarchy

### Tree Structure Visualization

Use Rich's Tree component with careful indentation and visual guides:

**Best Practices**:
1. **Consistent Indentation**: 2-4 spaces per level
2. **Tree Characters**: Use Unicode box-drawing characters
3. **Visual Grouping**: Group related items (LLM calls under agents)
4. **Truncation**: Truncate long names with ellipsis
5. **Alignment**: Align metrics in parentheses

**Example Tree Structure**:
```
Workflow: name (duration) status
├── Stage: name (duration) status
│   ├── Agent: name (duration) status (metrics)
│   │   ├── LLM: model (latency, tokens) status
│   │   └── Tool: name (duration) status
│   └── Synthesis: info status
└── Stage: name (duration) status
    └── Agent: name (duration) status (metrics)
```

### Panel Layout

Wrap the tree in a Rich Panel for clear boundaries:

```python
from rich.panel import Panel
from rich import box

panel = Panel(
    tree,
    title="[bold]Workflow Execution: {workflow_name}[/]",
    subtitle=format_summary(workflow),
    border_style=border_color,  # Dynamic based on status
    box=box.ROUNDED,            # Rounded corners for friendliness
    padding=(0, 1),             # Horizontal padding
)
```

### Summary Line Format

Keep summary metrics concise and scannable:

```
Duration: 2m 15s | Tokens: 45,230 | Cost: $0.1354 | LLM calls: 12 | Tool calls: 8
```

**Ordering Priority** (left to right):
1. Duration (most frequently checked)
2. Tokens (usage metric)
3. Cost (business metric)
4. Call counts (debugging metric)

### Metric Formatting Guidelines

```python
# Duration formatting
< 1s:     "150ms"       # Milliseconds for sub-second
1-60s:    "2.5s"        # Decimal seconds
> 60s:    "2m 15s"      # Minutes and seconds

# Token formatting
"1,234 tokens"          # Thousands separator, always include unit

# Cost formatting
"$0.1234"               # 4 decimal places for precision

# Count formatting
"12"                    # Plain integer, no separators for small counts
"1,234"                 # Use separator for > 1000
```

---

## 4. Real-Time Updates with Rich Live

### Basic Streaming Pattern

Use Rich's Live context manager for smooth updates:

```python
from rich.live import Live
from rich.console import Console
import time

console = Console()

with Live(
    generate_tree(workflow),
    refresh_per_second=4,      # 4 FPS is smooth without flicker
    console=console,
    screen=False,              # Don't clear screen
    vertical_overflow="visible"  # Show scroll for long output
) as live:
    while not workflow_completed:
        # Poll database for updates
        workflow = fetch_workflow_state(workflow_id)

        # Update display
        live.update(generate_tree(workflow))

        # Sleep to control poll rate
        time.sleep(0.25)  # 4 Hz polling
```

### Optimizing Real-Time Performance

**Poll Interval Guidelines**:
- **Fast polling (0.1-0.25s)**: Interactive development, watching active workflow
- **Medium polling (0.5-1s)**: Background monitoring, less critical
- **Slow polling (2-5s)**: Long-running workflows, batch jobs

**Database Query Optimization**:
```python
def fetch_workflow_state(workflow_id: str):
    """Efficiently fetch workflow with minimal queries."""
    with get_session() as session:
        # Use joinedload to fetch all relationships in one query
        from sqlalchemy.orm import joinedload

        workflow = session.query(WorkflowExecution).options(
            joinedload(WorkflowExecution.stages).joinedload(StageExecution.agents).joinedload(AgentExecution.llm_calls),
            joinedload(WorkflowExecution.stages).joinedload(StageExecution.agents).joinedload(AgentExecution.tool_executions),
            joinedload(WorkflowExecution.stages).joinedload(StageExecution.collaboration_events)
        ).filter_by(id=workflow_id).first()

        return workflow
```

### Progressive Loading Strategy

For very large workflows, implement progressive disclosure:

```python
class ProgressiveVisualizer:
    """Visualizer that loads details on demand."""

    def __init__(self):
        self.expanded_nodes = set()  # Track what's expanded

    def generate_tree(self, workflow):
        tree = Tree(format_workflow_node(workflow))

        for stage in workflow.stages:
            stage_node = tree.add(format_stage_node(stage))

            if self.should_expand(stage):
                # Show details for this stage
                for agent in stage.agents:
                    agent_node = stage_node.add(format_agent_node(agent))

                    if self.verbosity == "verbose":
                        for llm_call in agent.llm_calls:
                            agent_node.add(format_llm_node(llm_call))
            else:
                # Show collapsed indicator
                stage_node.add(f"[dim]({len(stage.agents)} agents - click to expand)[/]")

        return tree
```

### Spinner for Running Tasks

Show spinners for in-progress items:

```python
from rich.spinner import Spinner

def format_node_with_spinner(name, status, duration):
    if status == "running":
        return f"{Spinner('dots')} {name} [dim](in progress)[/]"
    else:
        icon = STATUS_ICONS[status]
        color = STATUS_COLORS[status]
        return f"[{color}]{icon}[/] {name} [dim]({duration})[/]"
```

### Update Animation

Highlight recently changed nodes:

```python
class ChangeTracker:
    """Track changes between updates."""

    def __init__(self):
        self.previous_state = {}

    def format_with_highlight(self, node_id, current_value):
        if node_id in self.previous_state:
            if self.previous_state[node_id] != current_value:
                # Highlight changed values
                self.previous_state[node_id] = current_value
                return f"[bold yellow]{current_value}[/]"
        else:
            self.previous_state[node_id] = current_value

        return current_value
```

---

## 5. Edge Case Handling

### Very Long Names

Implement intelligent truncation with tooltips:

```python
def truncate_name(name: str, max_length: int = 40) -> str:
    """Truncate long names while preserving important parts."""
    if len(name) <= max_length:
        return name

    # For paths, show beginning and end
    if "/" in name or "\\" in name:
        parts = name.replace("\\", "/").split("/")
        if len(parts) > 2:
            # Show first and last parts
            first = parts[0]
            last = parts[-1]
            available = max_length - len(first) - len(last) - 5
            if available > 0:
                return f"{first}/.../{last}"

    # For other names, show beginning with ellipsis
    return name[:max_length - 1] + "…"

# Example usage
assert truncate_name("very_long_agent_name_that_exceeds_limit", 30) == "very_long_agent_name_that_ex…"
assert truncate_name("/path/to/very/deep/nested/file.py", 30) == "/path/.../file.py"
```

### Deep Nesting

Limit tree depth and provide drill-down capability:

```python
def create_tree_with_depth_limit(workflow, max_depth: int = 5):
    """Create tree with maximum depth limit."""

    def add_node_recursive(parent, node, current_depth):
        if current_depth >= max_depth:
            parent.add(f"[dim]... ({count_remaining(node)} more items)[/]")
            return

        node_tree = parent.add(format_node(node))

        for child in node.children:
            add_node_recursive(node_tree, child, current_depth + 1)

    tree = Tree(format_workflow(workflow))
    add_node_recursive(tree, workflow, 0)
    return tree
```

### Large Number Formatting

Handle very large numbers gracefully:

```python
def format_large_number(value: int) -> str:
    """Format large numbers with appropriate units."""
    if value < 1_000:
        return str(value)
    elif value < 1_000_000:
        return f"{value / 1_000:.1f}K"
    elif value < 1_000_000_000:
        return f"{value / 1_000_000:.1f}M"
    else:
        return f"{value / 1_000_000_000:.1f}B"

# Example usage
assert format_large_number(123) == "123"
assert format_large_number(12_345) == "12.3K"
assert format_large_number(1_234_567) == "1.2M"
```

### Terminal Width Handling

Adapt to terminal width dynamically:

```python
from rich.console import Console

console = Console()
width = console.width

# Adjust max_length based on available width
if width < 80:
    max_name_length = 20
elif width < 120:
    max_name_length = 40
else:
    max_name_length = 60

# Use responsive layout
if width < 100:
    # Compact layout for narrow terminals
    summary = f"⏱ {duration} | 🪙 {tokens} | 💰 {cost}"
else:
    # Full layout for wide terminals
    summary = f"Duration: {duration} | Tokens: {tokens} | Cost: {cost} | LLM calls: {llm_calls}"
```

### Error State Display

Provide clear error information without cluttering:

```python
def format_error_node(node):
    """Format node with error information."""
    base = f"[red]{STATUS_ICONS['failed']}[/] {node.name} ({node.duration})"

    if node.error_message:
        # Show first line of error
        error_preview = node.error_message.split("\n")[0][:50]
        base += f"\n  [red]Error:[/] {error_preview}"

        if len(node.error_message) > 50:
            base += f" [dim](+{len(node.error_message) - 50} chars)[/]"

    return base
```

### Empty States

Handle workflows with no data gracefully:

```python
def create_tree(workflow):
    """Create tree with empty state handling."""
    tree = Tree(format_workflow(workflow))

    if not workflow.stages:
        tree.add("[dim]No stages executed[/]")
        return tree

    for stage in workflow.stages:
        stage_node = tree.add(format_stage(stage))

        if not stage.agents:
            stage_node.add("[dim]No agents executed[/]")

        # ... rest of tree building

    return tree
```

### Unicode Fallback

Provide ASCII fallback for terminals without Unicode support:

```python
import sys

# Detect Unicode support
UNICODE_SUPPORTED = sys.stdout.encoding.lower() in ['utf-8', 'utf8']

ICONS = {
    "success": "✓" if UNICODE_SUPPORTED else "√",
    "failed": "✗" if UNICODE_SUPPORTED else "X",
    "running": "⏳" if UNICODE_SUPPORTED else "...",
    "timeout": "⌛" if UNICODE_SUPPORTED else "T/O",
}
```

---

## 6. Accessibility Considerations

### Screen Reader Support

Ensure meaningful text without relying solely on colors:

```python
# Bad - relies on color only
f"[red]{node.name}[/]"

# Good - includes status text
f"[red]{STATUS_ICONS['failed']}[/] {node.name} [red](FAILED)[/]"
```

### Color Blindness Support

Use color + icon + text combinations:

```python
def format_status_accessible(status: str) -> str:
    """Format status with multiple visual cues."""
    icon = STATUS_ICONS[status]
    color = STATUS_COLORS[status]
    text = status.upper()

    # Combine icon, color, and text
    return f"[{color}]{icon} {text}[/]"

# Examples:
# "✓ SUCCESS" (green)
# "✗ FAILED" (red)
# "⏳ RUNNING" (yellow)
```

### High Contrast Mode

Support terminals with custom color schemes:

```python
def get_color_scheme():
    """Get color scheme based on environment."""
    if os.getenv("FORCE_COLOR") == "0":
        # High contrast mode - no colors
        return {status: "white" for status in STATUS_COLORS}
    else:
        return STATUS_COLORS
```

### Keyboard Navigation

For interactive modes, support keyboard shortcuts:

```python
# Display keyboard shortcuts
console.print("\n[dim]Keyboard shortcuts:[/]")
console.print("[dim]  ↑/↓  Navigate  │  Enter: Expand/Collapse  │  q: Quit[/]")
```

### Text Alternatives

Provide text-only export for screen readers:

```python
def export_text_trace(workflow):
    """Export plain text trace without formatting."""
    lines = []
    lines.append(f"Workflow: {workflow.name}")
    lines.append(f"Status: {workflow.status}")
    lines.append(f"Duration: {format_duration(workflow.duration)}")

    for stage in workflow.stages:
        lines.append(f"  Stage: {stage.name} ({stage.status})")
        for agent in stage.agents:
            lines.append(f"    Agent: {agent.name} ({agent.status})")

    return "\n".join(lines)
```

---

## 7. Implementation Examples

### Complete Minimal Visualizer

```python
from rich.console import Console
from rich.tree import Tree
from rich.panel import Panel
from rich import box

def visualize_minimal(workflow):
    """Minimal mode visualizer."""
    console = Console()

    # Create tree
    tree = Tree(
        f"[bold cyan]Workflow: {workflow.workflow_name}[/] "
        f"[dim]({format_duration(workflow.duration_seconds)})[/] "
        f"{format_status(workflow.status)}"
    )

    # Add stages only
    for stage in workflow.stages:
        tree.add(
            f"[yellow]Stage: {stage.stage_name}[/] "
            f"[dim]({format_duration(stage.duration_seconds)})[/] "
            f"{format_status(stage.status)}"
        )

    # Wrap in panel with summary
    panel = Panel(
        tree,
        title="[bold]Workflow Execution[/]",
        subtitle=format_summary(workflow),
        border_style="cyan",
        box=box.ROUNDED
    )

    console.print(panel)

def format_summary(workflow):
    """Format summary line."""
    parts = []

    if workflow.duration_seconds:
        parts.append(f"Duration: {format_duration(workflow.duration_seconds)}")
    if workflow.total_tokens:
        parts.append(f"Tokens: {workflow.total_tokens:,}")
    if workflow.total_cost_usd:
        parts.append(f"Cost: ${workflow.total_cost_usd:.4f}")
    if workflow.total_llm_calls:
        parts.append(f"LLM calls: {workflow.total_llm_calls}")

    return " | ".join(parts) if parts else "No metrics"

def format_status(status):
    """Format status with icon and color."""
    icon = STATUS_ICONS.get(status, "?")
    color = STATUS_COLORS.get(status, "white")
    return f"[{color}]{icon}[/]"
```

### Complete Standard Visualizer

```python
def visualize_standard(workflow):
    """Standard mode visualizer."""
    console = Console()

    # Create tree
    tree = Tree(
        f"[bold cyan]Workflow: {workflow.workflow_name}[/] "
        f"[dim]({format_duration(workflow.duration_seconds)})[/] "
        f"{format_status(workflow.status)}"
    )

    # Add stages and agents
    for stage in workflow.stages:
        stage_node = tree.add(
            f"[bold yellow]Stage: {stage.stage_name}[/] "
            f"[dim]({format_duration(stage.duration_seconds)})[/] "
            f"{format_status(stage.status)}"
        )

        # Add agents
        for agent in stage.agents:
            stage_node.add(
                f"[green]Agent: {agent.agent_name}[/] "
                f"[dim]({format_duration(agent.duration_seconds)})[/] "
                f"{format_status(agent.status)} "
                f"[dim]({agent.total_tokens:,} tokens, ${agent.estimated_cost_usd:.4f})[/]"
            )

        # Add synthesis info
        if stage.collaboration_rounds:
            stage_node.add(
                f"[cyan]Synthesis: {stage.collaboration_rounds} rounds[/] "
                f"{format_status('success')}"
            )

    # Wrap in panel
    panel = Panel(
        tree,
        title=f"[bold]Workflow Execution: {workflow.workflow_name}[/]",
        subtitle=format_summary(workflow),
        border_style=get_border_color(workflow.status),
        box=box.ROUNDED
    )

    console.print(panel)

def get_border_color(status):
    """Get border color based on status."""
    return {
        "running": "blue",
        "completed": "green",
        "failed": "red",
        "timeout": "red",
        "halted": "yellow",
    }.get(status, "cyan")
```

### Complete Streaming Visualizer

```python
from rich.live import Live
from threading import Thread, Event
import time

class StreamingVisualizer:
    """Real-time streaming visualizer."""

    def __init__(self, workflow_id: str, verbosity: str = "standard", poll_interval: float = 0.25):
        self.workflow_id = workflow_id
        self.verbosity = verbosity
        self.poll_interval = poll_interval
        self.console = Console()
        self.stop_event = Event()
        self.live = None
        self.update_thread = None

    def start(self):
        """Start streaming updates."""
        # Initial display
        workflow = self.fetch_workflow()
        if not workflow:
            self.console.print(f"[red]Workflow {self.workflow_id} not found[/]")
            return

        # Start live display
        self.live = Live(
            self.create_display(workflow),
            refresh_per_second=4,
            console=self.console
        )
        self.live.start()

        # Start update thread
        self.update_thread = Thread(target=self.update_loop, daemon=True)
        self.update_thread.start()

    def stop(self):
        """Stop streaming updates."""
        if self.stop_event.is_set():
            return

        self.stop_event.set()

        if self.update_thread:
            self.update_thread.join(timeout=2.0)

        if self.live:
            self.live.stop()

    def update_loop(self):
        """Poll database and update display."""
        while not self.stop_event.is_set():
            try:
                workflow = self.fetch_workflow()
                if workflow:
                    self.live.update(self.create_display(workflow))

                    # Stop if workflow completed
                    if workflow.status in ["completed", "failed", "timeout", "halted"]:
                        time.sleep(1.0)  # Show final state
                        break
            except Exception as e:
                # Log error but continue
                pass

            time.sleep(self.poll_interval)

    def fetch_workflow(self):
        """Fetch workflow from database."""
        with get_session() as session:
            return session.query(WorkflowExecution).filter_by(
                id=self.workflow_id
            ).first()

    def create_display(self, workflow):
        """Create display panel."""
        tree = self.create_tree(workflow)

        return Panel(
            tree,
            title=f"[bold]Workflow Execution: {workflow.workflow_name}[/]",
            subtitle=format_summary(workflow),
            border_style=get_border_color(workflow.status),
            box=box.ROUNDED
        )

    def create_tree(self, workflow):
        """Create tree based on verbosity."""
        if self.verbosity == "minimal":
            return create_minimal_tree(workflow)
        elif self.verbosity == "verbose":
            return create_verbose_tree(workflow)
        else:
            return create_standard_tree(workflow)

    def __enter__(self):
        """Context manager entry."""
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.stop()

# Usage
with StreamingVisualizer("wf-001", verbosity="standard") as viz:
    # Workflow executes...
    time.sleep(10)
```

### Responsive Width Adapter

```python
class ResponsiveVisualizer:
    """Visualizer that adapts to terminal width."""

    def __init__(self):
        self.console = Console()

    def visualize(self, workflow):
        """Visualize with responsive layout."""
        width = self.console.width

        # Determine layout strategy
        if width < 80:
            self.visualize_compact(workflow)
        elif width < 120:
            self.visualize_standard(workflow)
        else:
            self.visualize_wide(workflow)

    def visualize_compact(self, workflow):
        """Compact layout for narrow terminals."""
        # Use shorter names, fewer metrics
        tree = Tree(f"⚙ {truncate_name(workflow.workflow_name, 30)}")

        for stage in workflow.stages:
            stage_node = tree.add(
                f"📋 {truncate_name(stage.stage_name, 25)} "
                f"{format_status(stage.status)}"
            )

        self.console.print(Panel(tree, box=box.SIMPLE))

    def visualize_standard(self, workflow):
        """Standard layout for medium terminals."""
        # Normal display
        visualize_standard(workflow)

    def visualize_wide(self, workflow):
        """Wide layout with additional metrics."""
        # Show more detailed metrics in-line
        tree = Tree(
            f"[bold cyan]Workflow: {workflow.workflow_name}[/] "
            f"[dim]({format_duration(workflow.duration_seconds)})[/] "
            f"{format_status(workflow.status)} "
            f"[dim]Tokens: {workflow.total_tokens:,} | "
            f"Cost: ${workflow.total_cost_usd:.4f} | "
            f"LLM: {workflow.total_llm_calls} | "
            f"Tools: {workflow.total_tool_calls}[/]"
        )

        # ... rest of tree building

        self.console.print(Panel(tree, box=box.DOUBLE))
```

---

## Summary

This design provides:

1. **Three clear verbosity levels** that serve different use cases
2. **Consistent color and icon scheme** for quick status recognition
3. **Hierarchical layout** that maintains clarity at any depth
4. **Smooth real-time updates** using Rich's Live feature
5. **Robust edge case handling** for production use
6. **Accessibility support** for diverse users and environments

The implementation leverages Rich's powerful features while maintaining simplicity and usability across different terminal environments.
