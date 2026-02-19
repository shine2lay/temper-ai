#!/usr/bin/env python3
"""
Multi-Agent Hierarchical Gantt Chart Visualization

Creates an interactive timeline showing:
- Hierarchical structure (workflow → stage → agents → operations)
- Parallel agent execution
- Sequential operations within each agent
- Color-coded by type and status
- Interactive tooltips with metrics
"""
import json
import sys
from datetime import UTC, datetime, timedelta
from typing import Any, Dict, List

# Check if plotly is installed
try:
    import plotly.graph_objects as go
except ImportError as e:
    print("ERROR: Plotly not installed. Install with: pip install plotly")
    print(f"Import error: {e}")
    sys.exit(1)


def generate_sample_multi_agent_trace() -> Dict[str, Any]:
    """
    Generate a sample multi-agent execution trace.

    Simulates 3 agents working in parallel on a market analysis task:
    - research_agent: Gathers competitor data
    - analysis_agent: Analyzes pricing and trends
    - synthesis_agent: Creates final report
    """
    base_time = datetime.now(UTC)

    return {
        "id": "workflow-001",
        "name": "Market Analysis Workflow",
        "type": "workflow",
        "start": base_time.isoformat(),
        "end": (base_time + timedelta(seconds=8)).isoformat(),
        "duration": 8.0,
        "status": "completed",
        "metadata": {
            "total_tokens": 8500,
            "total_cost_usd": 0.017,
            "total_agents": 3,
            "environment": "production"
        },
        "children": [
            {
                "id": "stage-001",
                "parent_id": "workflow-001",
                "name": "Analysis Stage",
                "type": "stage",
                "start": (base_time + timedelta(seconds=0.1)).isoformat(),
                "end": (base_time + timedelta(seconds=7.8)).isoformat(),
                "duration": 7.7,
                "status": "completed",
                "metadata": {
                    "collaboration_rounds": 0,
                    "num_agents": 3
                },
                "children": [
                    # Agent 1: Research (parallel)
                    {
                        "id": "agent-001",
                        "parent_id": "stage-001",
                        "name": "research_agent",
                        "type": "agent",
                        "start": (base_time + timedelta(seconds=0.2)).isoformat(),
                        "end": (base_time + timedelta(seconds=3.5)).isoformat(),
                        "duration": 3.3,
                        "status": "completed",
                        "metadata": {
                            "total_tokens": 2400,
                            "estimated_cost_usd": 0.0048,
                            "num_llm_calls": 2,
                            "num_tool_calls": 1
                        },
                        "children": [
                            {
                                "id": "llm-001",
                                "parent_id": "agent-001",
                                "name": "ollama/llama3.2:3b",
                                "type": "llm",
                                "start": (base_time + timedelta(seconds=0.25)).isoformat(),
                                "end": (base_time + timedelta(seconds=1.8)).isoformat(),
                                "duration": 1.55,
                                "status": "success",
                                "metadata": {
                                    "model": "llama3.2:3b",
                                    "total_tokens": 1200,
                                    "prompt": "Research competitors..."
                                }
                            },
                            {
                                "id": "tool-001",
                                "parent_id": "agent-001",
                                "name": "WebScraper",
                                "type": "tool",
                                "start": (base_time + timedelta(seconds=1.85)).isoformat(),
                                "end": (base_time + timedelta(seconds=2.65)).isoformat(),
                                "duration": 0.8,
                                "status": "success",
                                "metadata": {
                                    "tool_name": "WebScraper",
                                    "url": "https://competitors.com"
                                }
                            },
                            {
                                "id": "llm-002",
                                "parent_id": "agent-001",
                                "name": "ollama/llama3.2:3b",
                                "type": "llm",
                                "start": (base_time + timedelta(seconds=2.7)).isoformat(),
                                "end": (base_time + timedelta(seconds=3.4)).isoformat(),
                                "duration": 0.7,
                                "status": "success",
                                "metadata": {
                                    "model": "llama3.2:3b",
                                    "total_tokens": 1200,
                                    "prompt": "Summarize findings..."
                                }
                            }
                        ]
                    },
                    # Agent 2: Analysis (parallel, starts slightly later)
                    {
                        "id": "agent-002",
                        "parent_id": "stage-001",
                        "name": "analysis_agent",
                        "type": "agent",
                        "start": (base_time + timedelta(seconds=0.5)).isoformat(),
                        "end": (base_time + timedelta(seconds=6.2)).isoformat(),
                        "duration": 5.7,
                        "status": "completed",
                        "metadata": {
                            "total_tokens": 3800,
                            "estimated_cost_usd": 0.0076,
                            "num_llm_calls": 2,
                            "num_tool_calls": 2
                        },
                        "children": [
                            {
                                "id": "llm-003",
                                "parent_id": "agent-002",
                                "name": "ollama/llama3.2:3b",
                                "type": "llm",
                                "start": (base_time + timedelta(seconds=0.55)).isoformat(),
                                "end": (base_time + timedelta(seconds=3.2)).isoformat(),
                                "duration": 2.65,
                                "status": "success",
                                "metadata": {
                                    "model": "llama3.2:3b",
                                    "total_tokens": 2000,
                                    "prompt": "Analyze pricing trends..."
                                }
                            },
                            {
                                "id": "tool-002",
                                "parent_id": "agent-002",
                                "name": "Calculator",
                                "type": "tool",
                                "start": (base_time + timedelta(seconds=3.25)).isoformat(),
                                "end": (base_time + timedelta(seconds=3.25)).isoformat(),
                                "duration": 0.0001,
                                "status": "success",
                                "metadata": {
                                    "tool_name": "Calculator",
                                    "expression": "avg([49, 59, 79, 99])"
                                }
                            },
                            {
                                "id": "tool-003",
                                "parent_id": "agent-002",
                                "name": "Calculator",
                                "type": "tool",
                                "start": (base_time + timedelta(seconds=3.26)).isoformat(),
                                "end": (base_time + timedelta(seconds=3.26)).isoformat(),
                                "duration": 0.0001,
                                "status": "success",
                                "metadata": {
                                    "tool_name": "Calculator",
                                    "expression": "stddev([49, 59, 79, 99])"
                                }
                            },
                            {
                                "id": "llm-004",
                                "parent_id": "agent-002",
                                "name": "ollama/llama3.2:3b",
                                "type": "llm",
                                "start": (base_time + timedelta(seconds=3.3)).isoformat(),
                                "end": (base_time + timedelta(seconds=6.1)).isoformat(),
                                "duration": 2.8,
                                "status": "success",
                                "metadata": {
                                    "model": "llama3.2:3b",
                                    "total_tokens": 1800,
                                    "prompt": "Create pricing analysis..."
                                }
                            }
                        ]
                    },
                    # Agent 3: Synthesis (parallel, starts after some data available)
                    {
                        "id": "agent-003",
                        "parent_id": "stage-001",
                        "name": "synthesis_agent",
                        "type": "agent",
                        "start": (base_time + timedelta(seconds=3.6)).isoformat(),
                        "end": (base_time + timedelta(seconds=7.7)).isoformat(),
                        "duration": 4.1,
                        "status": "completed",
                        "metadata": {
                            "total_tokens": 2300,
                            "estimated_cost_usd": 0.0046,
                            "num_llm_calls": 2,
                            "num_tool_calls": 1
                        },
                        "children": [
                            {
                                "id": "llm-005",
                                "parent_id": "agent-003",
                                "name": "ollama/llama3.2:3b",
                                "type": "llm",
                                "start": (base_time + timedelta(seconds=3.65)).isoformat(),
                                "end": (base_time + timedelta(seconds=5.9)).isoformat(),
                                "duration": 2.25,
                                "status": "success",
                                "metadata": {
                                    "model": "llama3.2:3b",
                                    "total_tokens": 1500,
                                    "prompt": "Synthesize findings..."
                                }
                            },
                            {
                                "id": "tool-004",
                                "parent_id": "agent-003",
                                "name": "FileWriter",
                                "type": "tool",
                                "start": (base_time + timedelta(seconds=5.95)).isoformat(),
                                "end": (base_time + timedelta(seconds=5.96)).isoformat(),
                                "duration": 0.01,
                                "status": "success",
                                "metadata": {
                                    "tool_name": "FileWriter",
                                    "file_path": "market_analysis_report.md"
                                }
                            },
                            {
                                "id": "llm-006",
                                "parent_id": "agent-003",
                                "name": "ollama/llama3.2:3b",
                                "type": "llm",
                                "start": (base_time + timedelta(seconds=6.0)).isoformat(),
                                "end": (base_time + timedelta(seconds=7.6)).isoformat(),
                                "duration": 1.6,
                                "status": "success",
                                "metadata": {
                                    "model": "llama3.2:3b",
                                    "total_tokens": 800,
                                    "prompt": "Generate executive summary..."
                                }
                            }
                        ]
                    }
                ]
            }
        ]
    }


def flatten_trace(trace: Dict[str, Any], base_time: datetime = None) -> List[Dict[str, Any]]:
    """Flatten hierarchical trace into list suitable for Gantt chart."""
    if base_time is None:
        base_time = datetime.fromisoformat(trace["start"])

    flat = []

    def add_node(node: Dict[str, Any], depth: int = 0, parent_name: str = ""):
        start = datetime.fromisoformat(node["start"])
        end = datetime.fromisoformat(node["end"]) if node.get("end") else start

        # Create display name with indentation
        indent = "  " * depth
        display_name = f"{indent}{node['name']}"

        # Calculate metrics
        metadata = node.get("metadata", {})

        # Build hover text
        hover_parts = [
            f"<b>{node['name']}</b>",
            f"Type: {node['type']}",
            f"Duration: {node.get('duration', 0):.3f}s",
            f"Status: {node.get('status', 'unknown')}"
        ]

        if node['type'] == 'agent':
            hover_parts.extend([
                f"Tokens: {metadata.get('total_tokens', 0)}",
                f"Cost: ${metadata.get('estimated_cost_usd', 0):.4f}",
                f"LLM Calls: {metadata.get('num_llm_calls', 0)}",
                f"Tool Calls: {metadata.get('num_tool_calls', 0)}"
            ])
        elif node['type'] == 'llm':
            hover_parts.extend([
                f"Model: {metadata.get('model', 'unknown')}",
                f"Tokens: {metadata.get('total_tokens', 0)}"
            ])
        elif node['type'] == 'tool':
            hover_parts.append(f"Tool: {metadata.get('tool_name', 'unknown')}")

        flat.append({
            "Task": display_name,
            "Start": start,
            "Finish": end,
            "Type": node["type"],
            "Depth": depth,
            "Duration": node.get("duration", 0),
            "Status": node.get("status", "unknown"),
            "Parent": parent_name,
            "Hover": "<br>".join(hover_parts),
            "Metadata": metadata
        })

        for child in node.get("children", []):
            add_node(child, depth + 1, node["name"])

    add_node(trace)
    return flat


def create_hierarchical_gantt(trace: Dict[str, Any], title: str = "Multi-Agent Execution Timeline"):
    """Create interactive hierarchical Gantt chart."""
    import pandas as pd

    # Flatten trace
    flat_data = flatten_trace(trace)
    df = pd.DataFrame(flat_data)

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
        df_type = df[df["Type"] == type_name]
        if not df_type.empty:
            fig.add_trace(go.Bar(
                name=type_name.capitalize(),
                x=[(finish - start).total_seconds() * 1000
                   for start, finish in zip(df_type["Start"], df_type["Finish"])],
                y=df_type["Task"],
                base=[start.timestamp() * 1000 for start in df_type["Start"]],
                orientation='h',
                marker=dict(color=color),
                text=df_type["Hover"],
                hovertemplate='%{text}<extra></extra>',
                textposition='none'
            ))

    # Update layout
    fig.update_layout(
        title=dict(
            text=title,
            x=0.5,
            xanchor='center',
            font=dict(size=20, color='#2E86AB')
        ),
        xaxis=dict(
            title="Time (seconds from start)",
            tickmode='linear',
            tick0=0,
            dtick=1000,  # 1 second intervals
            tickformat='.1f',
            ticksuffix='s',
            gridcolor='rgba(128,128,128,0.2)'
        ),
        yaxis=dict(
            title="",
            autorange="reversed",  # Top to bottom
            gridcolor='rgba(128,128,128,0.1)'
        ),
        barmode='overlay',
        height=max(600, len(df) * 30),
        hovermode='closest',
        template='plotly_white',
        showlegend=True,
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1
        )
    )

    return fig


def print_trace_summary(trace: Dict[str, Any]):
    """Print a text summary of the trace."""
    print("\n" + "=" * 100)
    print("MULTI-AGENT EXECUTION SUMMARY")
    print("=" * 100)
    print()

    metadata = trace.get("metadata", {})
    print(f"Workflow: {trace['name']}")
    print(f"Duration: {trace['duration']:.2f}s")
    print(f"Status: {trace['status']}")
    print(f"Total Agents: {metadata.get('total_agents', 0)}")
    print(f"Total Tokens: {metadata.get('total_tokens', 0):,}")
    print(f"Total Cost: ${metadata.get('total_cost_usd', 0):.4f}")
    print()

    # List agents
    stage = trace["children"][0]
    agents = stage["children"]

    print("=" * 100)
    print("AGENT EXECUTION (Parallel)")
    print("=" * 100)
    print()

    for agent in agents:
        agent_meta = agent.get("metadata", {})
        print(f"Agent: {agent['name']}")
        print(f"  Duration: {agent['duration']:.2f}s")
        print(f"  Start: {agent['start']}")
        print(f"  Status: {agent['status']}")
        print(f"  Tokens: {agent_meta.get('total_tokens', 0):,}")
        print(f"  Cost: ${agent_meta.get('estimated_cost_usd', 0):.4f}")
        print(f"  LLM Calls: {agent_meta.get('num_llm_calls', 0)}")
        print(f"  Tool Calls: {agent_meta.get('num_tool_calls', 0)}")
        print()

    # Calculate parallelism benefit
    total_agent_time = sum(agent['duration'] for agent in agents)
    workflow_time = trace['duration']
    speedup = total_agent_time / workflow_time if workflow_time > 0 else 1

    print("=" * 100)
    print("PARALLELISM ANALYSIS")
    print("=" * 100)
    print()
    print(f"Total Agent Time (sequential): {total_agent_time:.2f}s")
    print(f"Actual Workflow Time (parallel): {workflow_time:.2f}s")
    print(f"Speedup: {speedup:.2f}x")
    print(f"Time Saved: {total_agent_time - workflow_time:.2f}s ({((speedup - 1) / speedup * 100):.1f}% faster)")
    print()


def main():
    """Generate and visualize multi-agent execution trace."""
    print()
    print("=" * 100)
    print("MULTI-AGENT HIERARCHICAL GANTT CHART")
    print("=" * 100)
    print()
    print("Generating sample multi-agent execution trace...")
    print("This simulates 3 agents working in parallel:")
    print("  • research_agent: Gathers competitor data")
    print("  • analysis_agent: Analyzes pricing trends")
    print("  • synthesis_agent: Creates final report")
    print()

    # Generate sample trace
    trace = generate_sample_multi_agent_trace()

    # Print summary
    print_trace_summary(trace)

    # Save trace to file
    trace_file = "sample_multi_agent_trace.json"
    with open(trace_file, 'w') as f:
        json.dump(trace, f, indent=2, default=str)
    print(f"✓ Saved trace data to: {trace_file}")
    print()

    # Create visualization using the general-purpose visualizer
    print("=" * 100)
    print("Creating interactive Gantt chart...")
    print("=" * 100)
    print()

    try:
        # Use the new general-purpose visualizer
        from temper_ai.observability.visualize_trace import visualize_trace

        output_file = "multi_agent_gantt.html"
        visualize_trace(trace, output_file=output_file, show_tree_lines=True, auto_open=True)

        print()
        print("Features:")
        print("  • Hierarchical tree structure with ▼ ├─ └─ characters")
        print("  • Hover over bars to see detailed metrics")
        print("  • Zoom in/out with scroll wheel")
        print("  • Pan by clicking and dragging")
        print("  • Click legend items to show/hide types")
        print("  • Export to PNG using camera icon")
        print()

    except ImportError:
        print("ERROR: Visualization module not available")
        print("Falling back to old visualization...")
        print()
        fig = create_hierarchical_gantt(trace)
        output_file = "multi_agent_gantt.html"
        fig.write_html(output_file)
        print(f"✓ Saved interactive chart to: {output_file}")

    print()
    print("=" * 100)
    print("NEXT STEPS")
    print("=" * 100)
    print()
    print("To visualize YOUR actual execution traces:")
    print()
    print("1. Use the general-purpose visualizer:")
    print("   python -m temper_ai.observability.visualize_trace <workflow-id>")
    print()
    print("2. Or get latest workflow:")
    print("   python -m temper_ai.observability.visualize_trace --latest")
    print()
    print("3. Or from JSON file:")
    print("   python -m temper_ai.observability.visualize_trace --file trace.json")
    print()


if __name__ == "__main__":
    main()
