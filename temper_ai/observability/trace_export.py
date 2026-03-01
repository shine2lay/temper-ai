"""
Export execution trace in waterfall chart format.

Provides hierarchical and flat trace representations suitable for
waterfall/Gantt chart visualizations (D3.js, Plotly, Google Charts).
"""

from typing import Any

from sqlmodel import select

from temper_ai.storage.database.manager import get_session
from temper_ai.storage.database.models import (
    AgentExecution,
    LLMCall,
    StageExecution,
    ToolExecution,
    WorkflowExecution,
)


def _build_llm_node(
    llm: Any, agent_id: str
) -> dict[str, Any]:  # noqa: long  # noqa: radon
    """Build a waterfall trace node for a single LLM call."""
    return {
        "id": llm.id,
        "parent_id": agent_id,
        "name": f"{llm.provider}/{llm.model}",
        "type": "llm",
        "start": llm.start_time.isoformat(),
        "end": llm.end_time.isoformat() if llm.end_time else None,
        "duration": (llm.latency_ms / 1000.0 if llm.latency_ms else None),
        "status": llm.status,
        "metadata": {
            "provider": llm.provider,
            "model": llm.model,
            "total_tokens": llm.total_tokens,
            "prompt_tokens": llm.prompt_tokens,
            "completion_tokens": llm.completion_tokens,
            "estimated_cost_usd": llm.estimated_cost_usd,
            "temperature": llm.temperature,
        },
    }


def _build_tool_node(tool: Any, agent_id: str) -> dict[str, Any]:
    """Build a waterfall trace node for a single tool execution."""
    return {
        "id": tool.id,
        "parent_id": agent_id,
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
            "safety_checks": tool.safety_checks_applied,
        },
    }


def _build_agent_node(agent: Any, stage_id: str, session: Any) -> dict[str, Any]:
    """Build a waterfall trace node for a single agent with its leaf children."""
    children: list[dict[str, Any]] = []
    llm_stmt = (
        select(LLMCall)
        .where(LLMCall.agent_execution_id == agent.id)
        .order_by(LLMCall.start_time)  # type: ignore[arg-type]
    )
    for llm in session.exec(llm_stmt).all():
        children.append(_build_llm_node(llm, agent.id))
    tool_stmt = (
        select(ToolExecution)
        .where(ToolExecution.agent_execution_id == agent.id)
        .order_by(ToolExecution.start_time)  # type: ignore[arg-type]
    )
    for tool in session.exec(tool_stmt).all():
        children.append(_build_tool_node(tool, agent.id))
    return {
        "id": agent.id,
        "parent_id": stage_id,
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
            "tool_duration": agent.tool_duration_seconds,
        },
        "children": children,
    }


def _build_stage_node(stage: Any, workflow_id: str, session: Any) -> dict[str, Any]:
    """Build a waterfall trace node for a single stage with its agent children."""
    agent_stmt = (
        select(AgentExecution)
        .where(AgentExecution.stage_execution_id == stage.id)
        .order_by(AgentExecution.start_time)  # type: ignore[arg-type]
    )
    children = [
        _build_agent_node(agent, stage.id, session)
        for agent in session.exec(agent_stmt).all()
    ]
    return {
        "id": stage.id,
        "parent_id": workflow_id,
        "name": stage.stage_name,
        "type": "stage",
        "start": stage.start_time.isoformat(),
        "end": stage.end_time.isoformat() if stage.end_time else None,
        "duration": stage.duration_seconds,
        "status": stage.status,
        "metadata": {
            "num_agents": stage.num_agents_executed,
            "collaboration_rounds": stage.collaboration_rounds,
        },
        "children": children,
    }


def export_waterfall_trace(workflow_id: str) -> dict[str, Any]:
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
    """
    with get_session() as session:
        wf_stmt = select(WorkflowExecution).where(WorkflowExecution.id == workflow_id)
        workflow = session.exec(wf_stmt).first()
        if not workflow:
            return {"error": f"Workflow {workflow_id} not found"}
        stage_stmt = (
            select(StageExecution)
            .where(StageExecution.workflow_execution_id == workflow_id)
            .order_by(StageExecution.start_time)  # type: ignore[arg-type]
        )
        stage_children = [
            _build_stage_node(stage, workflow_id, session)
            for stage in session.exec(stage_stmt).all()
        ]
        return {
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
                "environment": workflow.environment,
            },
            "children": stage_children,
        }
