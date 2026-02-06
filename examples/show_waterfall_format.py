#!/usr/bin/env python3
"""
Show waterfall chart format with example data.

Demonstrates the structure of the observability trace data
and how it can be used to create waterfall/Gantt charts.
"""
import json
from datetime import datetime

# Example trace data structure (what you'd get from the database)
example_trace = {
    "id": "workflow-123",
    "name": "simple_research",
    "type": "workflow",
    "start": "2026-01-26T09:23:33.621949",
    "end": "2026-01-26T09:23:40.229799",
    "duration": 6.608,
    "status": "completed",
    "metadata": {
        "total_tokens": 2906,
        "total_cost_usd": 0.005812,
        "total_llm_calls": 1,
        "total_tool_calls": 5,
        "environment": "demo"
    },
    "children": [
        {
            "id": "stage-456",
            "parent_id": "workflow-123",
            "name": "research",
            "type": "stage",
            "start": "2026-01-26T09:23:33.650840",
            "end": "2026-01-26T09:23:40.121526",
            "duration": 6.471,
            "status": "completed",
            "metadata": {
                "num_agents": 1,
                "collaboration_rounds": 0
            },
            "children": [
                {
                    "id": "agent-789",
                    "parent_id": "stage-456",
                    "name": "simple_researcher",
                    "type": "agent",
                    "start": "2026-01-26T09:23:33.673310",
                    "end": "2026-01-26T09:23:40.112569",
                    "duration": 6.439,
                    "status": "completed",
                    "metadata": {
                        "total_tokens": 2906,
                        "estimated_cost_usd": 0.005812,
                        "num_llm_calls": 1,
                        "num_tool_calls": 5,
                        "llm_duration": 5.2,
                        "tool_duration": 0.0005
                    },
                    "children": [
                        {
                            "id": "llm-001",
                            "parent_id": "agent-789",
                            "name": "ollama/llama3.2:3b",
                            "type": "llm",
                            "start": "2026-01-26T09:23:33.680000",
                            "end": "2026-01-26T09:23:35.920000",
                            "duration": 2.24,
                            "status": "success",
                            "metadata": {
                                "provider": "ollama",
                                "model": "llama3.2:3b",
                                "total_tokens": 580,
                                "prompt_tokens": 120,
                                "completion_tokens": 460,
                                "estimated_cost_usd": 0.00116,
                                "temperature": 0.7
                            }
                        },
                        {
                            "id": "tool-001",
                            "parent_id": "agent-789",
                            "name": "Calculator",
                            "type": "tool",
                            "start": "2026-01-26T09:23:36.000000",
                            "end": "2026-01-26T09:23:36.000100",
                            "duration": 0.0001,
                            "status": "success",
                            "metadata": {
                                "tool_name": "Calculator",
                                "tool_version": "1.0",
                                "input_params": {"expression": "150 * 49"},
                                "safety_checks": ["expression_validation"]
                            }
                        },
                        {
                            "id": "llm-002",
                            "parent_id": "agent-789",
                            "name": "ollama/llama3.2:3b",
                            "type": "llm",
                            "start": "2026-01-26T09:23:36.100000",
                            "end": "2026-01-26T09:23:37.580000",
                            "duration": 1.48,
                            "status": "success",
                            "metadata": {
                                "provider": "ollama",
                                "model": "llama3.2:3b",
                                "total_tokens": 465,
                                "prompt_tokens": 95,
                                "completion_tokens": 370,
                                "estimated_cost_usd": 0.00093,
                                "temperature": 0.7
                            }
                        },
                        {
                            "id": "tool-002",
                            "parent_id": "agent-789",
                            "name": "FileWriter",
                            "type": "tool",
                            "start": "2026-01-26T09:23:37.650000",
                            "end": "2026-01-26T09:23:37.651200",
                            "duration": 0.0012,
                            "status": "success",
                            "metadata": {
                                "tool_name": "FileWriter",
                                "tool_version": "1.0",
                                "input_params": {
                                    "file_path": "results.txt",
                                    "content": "Result: 7350"
                                },
                                "safety_checks": ["path_traversal", "dangerous_paths"]
                            }
                        },
                        {
                            "id": "llm-003",
                            "parent_id": "agent-789",
                            "name": "ollama/llama3.2:3b",
                            "type": "llm",
                            "start": "2026-01-26T09:23:37.700000",
                            "end": "2026-01-26T09:23:39.180000",
                            "duration": 1.48,
                            "status": "success",
                            "metadata": {
                                "provider": "ollama",
                                "model": "llama3.2:3b",
                                "total_tokens": 925,
                                "prompt_tokens": 180,
                                "completion_tokens": 745,
                                "estimated_cost_usd": 0.00185,
                                "temperature": 0.7
                            }
                        }
                    ]
                }
            ]
        }
    ]
}


def flatten_for_waterfall(trace, workflow_start=None):
    """Flatten to waterfall format with start offsets."""
    if workflow_start is None:
        workflow_start = datetime.fromisoformat(trace["start"])

    flat = []

    def add_node(node, depth=0):
        start = datetime.fromisoformat(node["start"])
        start_offset_ms = int((start - workflow_start).total_seconds() * 1000)
        duration_ms = int((node.get("duration", 0) or 0) * 1000)

        flat.append({
            "id": node["id"],
            "parent_id": node.get("parent_id"),
            "name": node["name"],
            "type": node["type"],
            "start_offset_ms": start_offset_ms,
            "duration_ms": duration_ms,
            "depth": depth,
            "status": node.get("status"),
            "metadata": node.get("metadata", {})
        })

        for child in node.get("children", []):
            add_node(child, depth + 1)

    add_node(trace)
    return flat


print("=" * 100)
print("OBSERVABILITY TRACE FORMAT FOR WATERFALL CHARTS")
print("=" * 100)
print()

print("📊 HIERARCHICAL FORMAT (Complete Tree)")
print("-" * 100)
print(json.dumps(example_trace, indent=2))
print()

print("=" * 100)
print("📈 FLAT FORMAT FOR WATERFALL/GANTT VISUALIZATION")
print("=" * 100)
print()

flat = flatten_for_waterfall(example_trace)

# Print as table
print(f"{'Type':<12} {'Name':<35} {'Start(ms)':<12} {'Duration(ms)':<15} {'Depth':<6} {'Status'}")
print("-" * 110)

for item in flat:
    indent = "  " * item["depth"]
    name = f"{indent}{item['name']}"
    metadata_str = ""

    if item["type"] == "llm":
        tokens = item["metadata"].get("total_tokens", "")
        metadata_str = f" ({tokens} tok)" if tokens else ""
    elif item["type"] == "tool":
        tool_name = item["metadata"].get("tool_name", "")
        metadata_str = f" ({tool_name})" if tool_name else ""

    full_name = f"{name}{metadata_str}"

    print(f"{item['type']:<12} {full_name:<35} {item['start_offset_ms']:<12} "
          f"{item['duration_ms']:<15} {item['depth']:<6} {item['status']}")

print()
print("=" * 100)
print("📋 JSON EXPORT (Ready for D3.js, Plotly, etc.)")
print("=" * 100)
print()
print(json.dumps(flat, indent=2))

print()
print("=" * 100)
print("✅ KEY FEATURES FOR WATERFALL CHARTS")
print("=" * 100)
print()
print("✓ Hierarchical parent-child relationships (via parent_id)")
print("✓ Precise timing: start_offset_ms + duration_ms")
print("✓ Type differentiation: workflow/stage/agent/llm/tool")
print("✓ Depth levels for visual indentation")
print("✓ Status tracking: completed/failed/running")
print("✓ Rich metadata: tokens, cost, parameters")
print()
print("📚 Compatible with:")
print("  • D3.js (d3-hierarchy, d3-scale)")
print("  • Plotly (px.timeline, go.Bar)")
print("  • Google Charts Timeline")
print("  • Apache ECharts Gantt")
print("  • Custom React/Vue visualizations")
print()
print("📊 You can create:")
print("  • Waterfall charts (time-based)")
print("  • Gantt charts (task-based)")
print("  • Flame graphs (performance)")
print("  • Tree maps (cost/token distribution)")
print("  • Sunburst charts (hierarchical breakdown)")
print()
