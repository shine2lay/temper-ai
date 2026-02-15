#!/usr/bin/env python3
"""
General-purpose hierarchical Gantt chart visualization for execution traces.

Usage:
    # From workflow ID
    python -m src.observability.visualize_trace <workflow-id>

    # From trace JSON file
    python -m src.observability.visualize_trace --file trace.json

    # From latest workflow
    python -m src.observability.visualize_trace --latest

    # Programmatic usage
    from src.observability.visualize_trace import visualize_trace
    fig = visualize_trace(trace_data)
    fig.show()
"""
import argparse
import json
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional

from src.shared.constants.limits import (
    LARGE_ITEM_LIMIT,
)

# Chart display constants
CHART_MARKER_LINE_WIDTH = 0.5  # Width of marker border lines
CHART_TITLE_X_POSITION = 0.5  # Center title horizontally
CHART_TITLE_FONT_SIZE = 20  # Title font size in points
CHART_LEGEND_Y_POSITION = 1.02  # Legend Y position (above chart)
CHART_SEPARATOR_WIDTH = 80  # Width of separator lines in console output

# Chart layout constants
MIN_CHART_HEIGHT = 600  # Minimum chart height in pixels
HEIGHT_PER_ITEM = 35  # Height per item in pixels
TICK_INTERVAL_MS = 1000  # 1 second intervals for X-axis ticks
CHART_LEFT_MARGIN = 300  # More space for long names with tree structure
TIMELINE_BAR_WIDTH = 40  # Width of console timeline bars
MONOSPACE_FONT_SIZE_REDUCTION = 9  # Points to subtract from title size for monospace

try:
    import plotly.graph_objects as go
    PLOTLY_AVAILABLE = True
except ImportError:
    PLOTLY_AVAILABLE = False
    # Plotly is optional - console gantt chart works without it


def create_hierarchical_gantt(
    trace: Dict[str, Any],
    title: Optional[str] = None,
    show_tree_lines: bool = True,
    output_file: Optional[str] = None
) -> Any:
    """
    Create hierarchical Gantt chart from execution trace.

    Args:
        trace: Hierarchical trace dict with structure:
            {
                "id": str,
                "name": str,
                "type": "workflow|stage|agent|llm|tool",
                "start": ISO timestamp,
                "end": ISO timestamp,
                "duration": float (seconds),
                "status": str,
                "metadata": dict,
                "children": [...]
            }
        title: Chart title (defaults to workflow name)
        show_tree_lines: Add tree structure characters (▼ ├─ └─)
        output_file: Path to save HTML file (optional)

    Returns:
        plotly Figure object
    """
    if not PLOTLY_AVAILABLE:
        raise ImportError("Plotly required. Install with: pip install plotly")

    # Flatten trace with tree structure
    flat_data = _flatten_trace_with_tree(trace, show_tree_lines)

    # Create figure with bars
    fig = _create_gantt_chart_bars(flat_data)

    # Configure layout
    if title is None:
        title = trace.get("name", "Execution Trace")
    _configure_gantt_layout(fig, title, len(flat_data))

    # Save to file if requested
    if output_file:
        fig.write_html(output_file)
        print(f"✓ Saved interactive chart to: {output_file}")

    return fig


def _flatten_trace_with_tree(
    trace: Dict[str, Any],
    show_tree_lines: bool = True
) -> List[Dict[str, Any]]:
    """
    Flatten hierarchical trace into list with tree structure visualization.

    Returns list of dicts with:
        - display_name: Name with tree characters (▼ ├─ └─)
        - start_ms: Start time in milliseconds from workflow start
        - duration_ms: Duration in milliseconds
        - type: Node type
        - hover_text: HTML hover tooltip
    """
    workflow_start = datetime.fromisoformat(trace["start"])
    flat = []

    def add_node(
        node: Dict[str, Any],
        depth: int = 0,
        is_last_child: Optional[List[bool]] = None,
        _parent_name: str = ""
    ) -> None:
        """Add node to trace visualization graph."""
        if is_last_child is None:
            is_last_child = []

        # Calculate timing
        start_ms, duration_ms = _calculate_node_timing(node, workflow_start)

        # Build display name with tree structure
        display_name = _build_tree_display_name(node, depth, is_last_child, show_tree_lines)

        # Build hover text
        hover_text = _build_node_hover_text(node)

        flat.append({
            "display_name": display_name,
            "start_ms": start_ms,
            "duration_ms": duration_ms,
            "type": node["type"],
            "hover_text": hover_text,
            "depth": depth,
            "metadata": node.get("metadata", {})
        })

        # Process children
        children = node.get("children", [])
        for i, child in enumerate(children):
            is_last = (i == len(children) - 1)
            add_node(
                child,
                depth + 1,
                is_last_child + [is_last],
                node["name"]
            )

    add_node(trace)
    return flat


def print_console_gantt(trace: Dict[str, Any], _max_width: int = LARGE_ITEM_LIMIT) -> None:
    """
    Print a text-based Gantt chart to console.

    Args:
        trace: Hierarchical trace dict
        _max_width: Maximum width for timeline bars
    """
    try:
        from rich.console import Console

        console = Console()
        workflow_duration = trace.get("duration") or 0

        # Print header
        console.print("\n[bold cyan]Console Gantt Chart[/bold cyan]")
        console.print("[dim]Timeline visualization (░ = idle, █ = active)[/dim]\n")

        # Create tree visualization
        workflow_start = datetime.fromisoformat(trace["start"])
        tree = _build_console_tree(trace, None, workflow_start, workflow_duration)

        # Print the tree
        console.print(tree)

        # Print summary
        console.print(f"\n[dim]Total duration: {_format_duration_simple(workflow_duration)}[/dim]")

    except ImportError:
        # Fallback to simple text output if Rich not available
        _print_simple_gantt(trace)


def _calculate_node_timing(node: Dict[str, Any], workflow_start: datetime) -> tuple[float, float]:
    """Calculate start_ms and duration_ms for a node."""
    start = datetime.fromisoformat(node["start"])
    end_str = node.get("end")
    end = datetime.fromisoformat(end_str) if end_str else start

    start_ms = (start - workflow_start).total_seconds() * 1000
    duration_ms = (end - start).total_seconds() * 1000
    return start_ms, duration_ms


def _build_tree_display_name(
    node: Dict[str, Any],
    depth: int,
    is_last_child: List[bool],
    show_tree_lines: bool
) -> str:
    """Build display name with tree structure prefix."""
    if show_tree_lines:
        # Build prefix using list for better performance (avoid repeated string concatenation)
        # String concatenation in loops is O(n²), list joining is O(n)
        prefix_parts = []

        # Add vertical lines for parent levels
        for i, is_last in enumerate(is_last_child[:-1]):
            if is_last:
                prefix_parts.append("    ")  # 4 spaces for cleared level
            else:
                prefix_parts.append("│   ")  # Vertical line + 3 spaces

        # Add branch for current level
        if depth > 0:
            if is_last_child[-1]:
                prefix_parts.append("└─ ")  # Last child
            else:
                prefix_parts.append("├─ ")  # Middle child

        # Add collapse indicator for nodes with children
        if node.get("children"):
            prefix_parts.append("▼ ")

        prefix = "".join(prefix_parts)
        return f"{prefix}{node['name']}"
    else:
        # Simple indentation
        indent = "  " * depth
        return f"{indent}{node['name']}"


def _build_node_hover_text(node: Dict[str, Any]) -> str:
    """Build hover text with type-specific metadata."""
    metadata = node.get("metadata", {})
    duration = node.get('duration') or 0
    hover_parts = [
        f"<b>{node['name']}</b>",
        f"Type: {node['type']}",
        f"Duration: {duration:.3f}s",
        f"Status: {node.get('status', 'unknown')}"
    ]

    # Add type-specific metadata
    if node['type'] == 'agent':
        cost = metadata.get('estimated_cost_usd') or 0
        hover_parts.extend([
            f"Tokens: {metadata.get('total_tokens', 0):,}",
            f"Cost: ${cost:.4f}",
            f"LLM Calls: {metadata.get('num_llm_calls', 0)}",
            f"Tool Calls: {metadata.get('num_tool_calls', 0)}"
        ])
    elif node['type'] == 'llm':
        hover_parts.extend([
            f"Model: {metadata.get('model', 'unknown')}",
            f"Tokens: {metadata.get('total_tokens', 0):,}",
            f"Prompt: {metadata.get('prompt_tokens', 0):,}",
            f"Completion: {metadata.get('completion_tokens', 0):,}"
        ])
    elif node['type'] == 'tool':
        hover_parts.extend([
            f"Tool: {metadata.get('tool_name', 'unknown')}",
            f"Version: {metadata.get('tool_version', 'N/A')}"
        ])
    elif node['type'] == 'workflow':
        total_cost = metadata.get('total_cost_usd') or 0
        hover_parts.extend([
            f"Total Tokens: {metadata.get('total_tokens', 0):,}",
            f"Total Cost: ${total_cost:.4f}",
            f"Environment: {metadata.get('environment', 'unknown')}"
        ])

    return "<br>".join(hover_parts)


def _create_gantt_chart_bars(flat_data: List[Dict[str, Any]]) -> Any:
    """Create plotly figure with colored bars for each node type."""
    # Define colors for each type
    color_map = {
        "workflow": "#2E86AB",    # Blue
        "stage": "#06A77D",       # Green
        "agent": "#F77F00",       # Orange
        "llm": "#D62828",         # Red
        "tool": "#FCBF49"         # Yellow
    }

    # Create figure
    fig = go.Figure()

    # Add bars for each type
    for type_name, color in color_map.items():
        type_items = [item for item in flat_data if item["type"] == type_name]

        if type_items:
            fig.add_trace(go.Bar(
                name=type_name.capitalize(),
                x=[item["duration_ms"] for item in type_items],
                y=[item["display_name"] for item in type_items],
                base=[item["start_ms"] for item in type_items],
                orientation='h',
                marker=dict(color=color, line=dict(width=CHART_MARKER_LINE_WIDTH, color='white')),
                text=[item["hover_text"] for item in type_items],
                hovertemplate='%{text}<extra></extra>',
                textposition='none'
            ))

    return fig


def _configure_gantt_layout(fig: Any, title: str, num_items: int) -> None:
    """Configure layout for Gantt chart."""
    # Calculate appropriate height
    height = max(MIN_CHART_HEIGHT, num_items * HEIGHT_PER_ITEM)

    fig.update_layout(
        title=dict(
            text=f"{title} - Hierarchical Timeline",
            x=CHART_TITLE_X_POSITION,
            xanchor='center',
            font=dict(size=CHART_TITLE_FONT_SIZE, color='#2E86AB')
        ),
        xaxis=dict(
            title="Time (seconds from start)",
            tickmode='linear',
            tick0=0,
            dtick=TICK_INTERVAL_MS,
            tickformat='.1f',
            ticksuffix='s',
            gridcolor='rgba(128,128,128,0.2)'
        ),
        yaxis=dict(
            title="",
            autorange="reversed",  # Top to bottom
            gridcolor='rgba(128,128,128,0.1)',
            tickfont=dict(family='monospace', size=CHART_TITLE_FONT_SIZE - MONOSPACE_FONT_SIZE_REDUCTION)  # Monospace for tree chars (11pt)
        ),
        barmode='overlay',
        height=height,
        hovermode='closest',
        template='plotly_white',
        showlegend=True,
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=CHART_LEGEND_Y_POSITION,
            xanchor="right",
            x=1
        ),
        margin=dict(l=CHART_LEFT_MARGIN)
    )


def _format_duration_simple(seconds: Optional[float]) -> str:
    """Format duration in human-readable form."""
    if seconds is None:
        return "0.000s"
    if seconds < 1:
        return f"{seconds*1000:.0f}ms"
    return f"{seconds:.3f}s"


def _create_timeline_bar(
    start_offset: float,
    duration: float,
    total_duration: float,
    width: int = TIMELINE_BAR_WIDTH
) -> str:
    """Create a visual timeline bar."""
    if total_duration == 0:
        return "░" * width

    # Calculate positions
    start_pos = int((start_offset / total_duration) * width)
    bar_length = max(1, int((duration / total_duration) * width))

    # Build the bar
    bar = "░" * start_pos
    bar += "█" * bar_length
    bar += "░" * (width - start_pos - bar_length)

    return bar[:width]


_CONSOLE_TREE_COLOR_MAP = {
    "workflow": "bold blue",
    "stage": "bold green",
    "agent": "bold yellow",
    "llm": "bold red",
    "tool": "bold cyan",
}


def _get_type_specific_info(
    node_type: str, metadata: Dict[str, Any]
) -> Optional[str]:
    """Return type-specific metadata string for tree label, or None."""
    if node_type == "agent":
        tokens = metadata.get("total_tokens", 0)
        if tokens > 0:
            return f"[dim]({tokens:,} tokens)[/dim]"
    elif node_type == "llm":
        model = metadata.get("model", "")
        if model:
            return f"[dim]({model})[/dim]"
    elif node_type == "tool":
        tool_name = metadata.get("tool_name", "")
        if tool_name:
            return f"[dim]({tool_name})[/dim]"
    return None


def _build_console_tree(
    node: Dict[str, Any],
    parent_tree: Any,
    workflow_start: datetime,
    workflow_duration: float,
) -> Any:
    """Recursively build Rich tree with timeline bars."""
    from rich.tree import Tree

    # Parse timing
    start = datetime.fromisoformat(node["start"])
    duration = node.get("duration") or 0
    start_offset = (start - workflow_start).total_seconds()

    # Create timeline bar
    timeline = _create_timeline_bar(
        start_offset, duration, workflow_duration, width=TIMELINE_BAR_WIDTH
    )

    # Build label
    node_type = node["type"]
    color = _CONSOLE_TREE_COLOR_MAP.get(node_type, "white")
    label_parts = [
        f"[{color}]{node['name']}[/{color}]",
        f"[dim]{_format_duration_simple(duration)}[/dim]",
    ]
    type_info = _get_type_specific_info(node_type, node.get("metadata", {}))
    if type_info:
        label_parts.append(type_info)

    full_label = f"{' '.join(label_parts)}\n[dim]{timeline}[/dim]"

    # Add to tree
    if parent_tree is None:
        tree = Tree(full_label)
        current = tree
    else:
        current = parent_tree.add(full_label)

    # Process children
    for child in node.get("children", []):
        _build_console_tree(child, current, workflow_start, workflow_duration)

    return tree if parent_tree is None else current


def _print_simple_gantt(trace: Dict[str, Any]) -> None:
    """Print simple text-based Gantt chart (fallback when Rich unavailable)."""
    print("\nConsole Gantt Chart:")
    print(f"  {trace['name']} - {trace.get('duration', 0):.3f}s")

    def print_simple(node: Dict[str, Any], indent: int = 0) -> None:
        """Print simplified trace output."""
        prefix = "  " * indent
        duration = node.get('duration') or 0
        print(f"{prefix}├─ {node['name']} ({duration:.3f}s)")
        for child in node.get("children", []):
            print_simple(child, indent + 1)

    for child in trace.get("children", []):
        print_simple(child, 1)


def _load_trace_data(args: Any) -> Optional[Dict[str, Any]]:
    """Load trace data from file or database based on CLI args."""
    if args.file:
        # Load from JSON file
        print(f"Loading trace from: {args.file}")
        with open(args.file) as f:
            data: Dict[str, Any] = json.load(f)
            return data
    else:
        # Load from database
        try:
            from sqlmodel import select

            from examples.export_waterfall import export_waterfall_trace
            from src.storage.database import get_session
            from src.storage.database.models import WorkflowExecution
        except ImportError as e:
            print(f"ERROR: Cannot import observability modules: {e}")
            print("Use --file to load from JSON instead")
            return None

        workflow_id = args.workflow_id

        if args.latest or workflow_id is None:
            # Get latest workflow
            with get_session() as session:
                stmt = select(WorkflowExecution).order_by(
                    WorkflowExecution.start_time.desc()  # type: ignore[attr-defined]
                ).limit(1)
                workflow = session.exec(stmt).first()

                if not workflow:
                    print("ERROR: No workflow executions found in database")
                    return None

                workflow_id = workflow.id
                print(f"Using latest workflow: {workflow_id}")

        print(f"Exporting trace for workflow: {workflow_id}")
        trace = export_waterfall_trace(workflow_id)

        if "error" in trace:
            print(f"ERROR: {trace['error']}")
            return None

        return trace


def _print_trace_summary(trace: Dict[str, Any]) -> None:
    """Print execution trace summary."""
    print()
    print("=" * CHART_SEPARATOR_WIDTH)
    print("EXECUTION TRACE SUMMARY")
    print("=" * CHART_SEPARATOR_WIDTH)
    print(f"Workflow: {trace['name']}")
    duration = trace.get('duration') or 0
    print(f"Duration: {duration:.2f}s")
    print(f"Status: {trace['status']}")
    metadata = trace.get('metadata', {})
    print(f"Total Tokens: {metadata.get('total_tokens', 0):,}")
    total_cost = metadata.get('total_cost_usd') or 0
    print(f"Total Cost: ${total_cost:.4f}")
    print()


def _print_usage_tips() -> None:
    """Print usage tips for the visualization."""
    print()
    print("✓ Visualization complete!")
    print()
    print("Features:")
    print("  • Hover over bars to see detailed metrics")
    print("  • Zoom in/out with scroll wheel")
    print("  • Pan by clicking and dragging")
    print("  • Click legend items to show/hide types")
    print("  • Export to PNG using camera icon")
    print()


def visualize_trace(
    trace: Dict[str, Any],
    output_file: Optional[str] = None,
    show_tree_lines: bool = True,
    auto_open: bool = True
) -> Any:
    """
    Visualize execution trace as hierarchical Gantt chart.

    Args:
        trace: Hierarchical trace dict (from export_waterfall_trace or similar)
        output_file: Path to save HTML (optional, defaults to trace name)
        show_tree_lines: Show tree structure characters
        auto_open: Open in browser automatically

    Returns:
        Plotly Figure object
    """
    # Generate default filename if not provided
    if output_file is None:
        trace_name = trace.get("name", "trace").replace(" ", "_").lower()
        output_file = f"{trace_name}_gantt.html"

    # Create visualization
    fig = create_hierarchical_gantt(
        trace,
        show_tree_lines=show_tree_lines,
        output_file=output_file
    )

    # Try to open in browser
    if auto_open:
        try:
            import webbrowser
            webbrowser.open(output_file)
            print(f"✓ Opened in browser: {output_file}")
        except (ImportError, OSError) as e:
            print(f"Could not open browser: {e}")
            print(f"Manually open: {output_file}")

    return fig


def _build_arg_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser for trace visualization."""

    parser = argparse.ArgumentParser(
        description="Visualize execution trace as hierarchical Gantt chart"
    )
    parser.add_argument("workflow_id", nargs="?", help="Workflow ID to visualize")
    parser.add_argument("--file", "-f", help="Load trace from JSON file instead of database")
    parser.add_argument("--latest", "-l", action="store_true", help="Visualize latest workflow execution")
    parser.add_argument("--output", "-o", help="Output HTML file path")
    parser.add_argument("--no-tree", action="store_true", help="Disable tree structure characters")
    parser.add_argument("--no-open", action="store_true", help="Don't auto-open browser")
    return parser


def main() -> int:
    """CLI entry point."""
    args = _build_arg_parser().parse_args()

    trace = _load_trace_data(args)
    if trace is None:
        return 1

    _print_trace_summary(trace)

    print("=" * CHART_SEPARATOR_WIDTH)
    print("Creating hierarchical Gantt chart...")
    print("=" * CHART_SEPARATOR_WIDTH)
    print()

    visualize_trace(
        trace,
        output_file=args.output,
        show_tree_lines=not args.no_tree,
        auto_open=not args.no_open
    )

    _print_usage_tips()

    return 0


if __name__ == "__main__":
    sys.exit(main())
