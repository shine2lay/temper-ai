#!/usr/bin/env python3
"""
Export execution trace in waterfall chart format.

Demonstrates the observability database structure and exports
execution traces in a format suitable for creating waterfall charts.
"""
import json
import sys
from datetime import datetime
from typing import List, Dict, Any

from sqlmodel import select, Session
from src.observability.database import get_session
from src.observability.models import (
    WorkflowExecution,
    StageExecution,
    AgentExecution,
    LLMCall,
    ToolExecution
)


def export_waterfall_trace(workflow_id: str) -> Dict[str, Any]:
    """
    Export execution trace in waterfall chart format.

    Returns a hierarchical structure with:
    - id: unique identifier
    - name: display name
    - start: start timestamp (ISO format or offset in ms)
    - end: end timestamp (ISO format or offset in ms)
    - duration: duration in seconds
    - type: workflow|stage|agent|llm|tool
    - parent_id: parent node ID (for hierarchy)
    - metadata: additional info (tokens, cost, etc.)
    - children: list of child nodes

    This format is compatible with:
    - D3.js waterfall charts
    - Plotly Gantt charts
    - Google Charts Timeline
    - Custom visualization tools
    """
    with get_session() as session:
        # Get workflow
        stmt = select(WorkflowExecution).where(WorkflowExecution.id == workflow_id)
        workflow = session.exec(stmt).first()

        if not workflow:
            return {"error": f"Workflow {workflow_id} not found"}

        # Build hierarchical trace
        trace = {
            "id": workflow.id,
            "name": workflow.workflow_name,
            "type": "workflow",
            "start": workflow.start_time.isoformat(),
            "end": workflow.end_time.isoformat() if workflow.end_time else None,
            "duration": workflow.duration_seconds,
            "status": workflow.status,
            "metadata": {
                "total_tokens": workflow.total_tokens,
                "total_cost_usd": workflow.total_cost_usd,
                "total_llm_calls": workflow.total_llm_calls,
                "total_tool_calls": workflow.total_tool_calls,
                "environment": workflow.environment
            },
            "children": []
        }

        # Get stages
        stmt = select(StageExecution).where(
            StageExecution.workflow_execution_id == workflow_id
        ).order_by(StageExecution.start_time)

        stages = session.exec(stmt).all()

        for stage in stages:
            stage_node = {
                "id": stage.id,
                "parent_id": workflow.id,
                "name": stage.stage_name,
                "type": "stage",
                "start": stage.start_time.isoformat(),
                "end": stage.end_time.isoformat() if stage.end_time else None,
                "duration": stage.duration_seconds,
                "status": stage.status,
                "metadata": {
                    "num_agents": stage.num_agents_executed,
                    "collaboration_rounds": stage.collaboration_rounds
                },
                "children": []
            }

            # Get agents for this stage
            stmt = select(AgentExecution).where(
                AgentExecution.stage_execution_id == stage.id
            ).order_by(AgentExecution.start_time)

            agents = session.exec(stmt).all()

            for agent in agents:
                agent_node = {
                    "id": agent.id,
                    "parent_id": stage.id,
                    "name": agent.agent_name,
                    "type": "agent",
                    "start": agent.start_time.isoformat(),
                    "end": agent.end_time.isoformat() if agent.end_time else None,
                    "duration": agent.duration_seconds,
                    "status": agent.status,
                    "metadata": {
                        "total_tokens": agent.total_tokens,
                        "estimated_cost_usd": agent.estimated_cost_usd,
                        "num_llm_calls": agent.num_llm_calls,
                        "num_tool_calls": agent.num_tool_calls,
                        "llm_duration": agent.llm_duration_seconds,
                        "tool_duration": agent.tool_duration_seconds
                    },
                    "children": []
                }

                # Get LLM calls for this agent
                stmt = select(LLMCall).where(
                    LLMCall.agent_execution_id == agent.id
                ).order_by(LLMCall.start_time)

                llm_calls = session.exec(stmt).all()

                for llm in llm_calls:
                    llm_node = {
                        "id": llm.id,
                        "parent_id": agent.id,
                        "name": f"{llm.provider}/{llm.model}",
                        "type": "llm",
                        "start": llm.start_time.isoformat(),
                        "end": llm.end_time.isoformat() if llm.end_time else None,
                        "duration": llm.latency_ms / 1000.0 if llm.latency_ms else None,
                        "status": llm.status,
                        "metadata": {
                            "provider": llm.provider,
                            "model": llm.model,
                            "total_tokens": llm.total_tokens,
                            "prompt_tokens": llm.prompt_tokens,
                            "completion_tokens": llm.completion_tokens,
                            "estimated_cost_usd": llm.estimated_cost_usd,
                            "temperature": llm.temperature
                        }
                    }
                    agent_node["children"].append(llm_node)

                # Get tool executions for this agent
                stmt = select(ToolExecution).where(
                    ToolExecution.agent_execution_id == agent.id
                ).order_by(ToolExecution.start_time)

                tools = session.exec(stmt).all()

                for tool in tools:
                    tool_node = {
                        "id": tool.id,
                        "parent_id": agent.id,
                        "name": tool.tool_name,
                        "type": "tool",
                        "start": tool.start_time.isoformat(),
                        "end": tool.end_time.isoformat() if tool.end_time else None,
                        "duration": tool.duration_seconds,
                        "status": tool.status,
                        "metadata": {
                            "tool_name": tool.tool_name,
                            "tool_version": tool.tool_version,
                            "input_params": tool.input_params,
                            "safety_checks": tool.safety_checks_applied
                        }
                    }
                    agent_node["children"].append(tool_node)

                stage_node["children"].append(agent_node)

            trace["children"].append(stage_node)

        return trace


def flatten_for_waterfall(trace: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Flatten hierarchical trace into flat list for waterfall charts.

    Each entry has:
    - id: unique identifier
    - parent_id: parent for hierarchy
    - name: display name
    - start_offset_ms: milliseconds from workflow start
    - duration_ms: duration in milliseconds
    - type: node type
    - depth: nesting depth (for visual indentation)
    """
    workflow_start = datetime.fromisoformat(trace["start"])
    flat = []

    def add_node(node: Dict[str, Any], depth: int = 0):
        start = datetime.fromisoformat(node["start"])
        start_offset_ms = int((start - workflow_start).total_seconds() * 1000)
        duration_ms = int((node["duration"] or 0) * 1000)

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


def main():
    """Export workflow trace in waterfall format."""
    if len(sys.argv) > 1:
        workflow_id = sys.argv[1]
    else:
        # Get latest workflow
        with get_session() as session:
            stmt = select(WorkflowExecution).order_by(
                WorkflowExecution.start_time.desc()
            ).limit(1)
            workflow = session.exec(stmt).first()

            if not workflow:
                print("No workflow executions found")
                return

            workflow_id = workflow.id

    print(f"Exporting workflow: {workflow_id}\n")

    # Export hierarchical format
    trace = export_waterfall_trace(workflow_id)

    if "error" in trace:
        print(f"Error: {trace['error']}")
        return

    print("=" * 80)
    print("HIERARCHICAL FORMAT (for nested visualizations)")
    print("=" * 80)
    print(json.dumps(trace, indent=2, default=str))

    print("\n" + "=" * 80)
    print("FLAT FORMAT (for waterfall/Gantt charts)")
    print("=" * 80)

    flat = flatten_for_waterfall(trace)

    # Print table
    print(f"{'Type':<12} {'Name':<30} {'Start(ms)':<12} {'Duration(ms)':<15} {'Depth'}")
    print("-" * 90)
    for item in flat:
        indent = "  " * item["depth"]
        name = f"{indent}{item['name']}"
        print(f"{item['type']:<12} {name:<30} {item['start_offset_ms']:<12} "
              f"{item['duration_ms']:<15} {item['depth']}")

    print("\n" + "=" * 80)
    print("JSON EXPORT (flat format)")
    print("=" * 80)
    print(json.dumps(flat, indent=2, default=str))


if __name__ == "__main__":
    main()
