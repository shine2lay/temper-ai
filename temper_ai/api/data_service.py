"""Data service — reconstructs execution hierarchy from flat events.

The observability module stores flat events (workflow_started, stage_started,
agent_started, etc.). This service reads them and builds the nested hierarchy
that the frontend expects: WorkflowExecution → NodeExecution → AgentExecution.
"""

from __future__ import annotations

import logging
from temper_ai.observability import get_events

logger = logging.getLogger(__name__)


def get_workflow_execution(execution_id: str) -> dict | None:
    """Build the full WorkflowExecution hierarchy for a given execution.

    Reconstructs the tree from flat events using parent_id relationships:
    - workflow.started/completed → top-level
    - stage.started/completed (parent_id = workflow) → nodes
    - agent.started/completed (parent_id = stage) → agents within nodes
    - llm.call.* (parent_id = agent) → LLM calls
    - tool.call.* (parent_id = agent) → tool calls

    Returns dict matching frontend's WorkflowExecution TypeScript interface,
    or None if no events found.
    """
    events = get_events(execution_id=execution_id, limit=10000)
    if not events:
        return None

    # Index events by ID for parent lookups
    # Find workflow event
    workflow_event = _find_event_by_type(events, "workflow.")
    if not workflow_event:
        return None

    # Build node executions (children of workflow event)
    node_events = _find_children(events, workflow_event["id"], "stage.")
    nodes = [_build_node_execution(e, events) for e in node_events]

    # Calculate aggregates
    total_cost = sum(n.get("cost_usd", 0) for n in nodes)
    total_tokens = sum(n.get("total_tokens", 0) for n in nodes)
    total_llm_calls = sum(n.get("total_llm_calls", 0) for n in nodes)
    total_tool_calls = sum(n.get("total_tool_calls", 0) for n in nodes)

    wf_data = workflow_event.get("data", {})
    return {
        "id": execution_id,
        "workflow_name": wf_data.get("name", ""),
        "status": _resolve_status(workflow_event),
        "start_time": workflow_event.get("timestamp"),
        "end_time": _get_end_time(events, workflow_event["id"], "workflow."),
        "duration_seconds": wf_data.get("duration_seconds"),
        "nodes": nodes,
        "total_tokens": total_tokens,
        "total_cost_usd": total_cost,
        "total_llm_calls": total_llm_calls,
        "total_tool_calls": total_tool_calls,
        "input_data": wf_data.get("input_data"),
        "output_data": wf_data.get("output_data"),
        "error_message": wf_data.get("error"),
    }


def list_workflow_executions(
    limit: int = 20,
    offset: int = 0,
    status: str | None = None,
) -> dict:
    """List workflow executions with summary data.

    Returns: {"runs": [...], "total": int}
    """
    # Get all workflow start events
    all_events = get_events(event_type="workflow.started", limit=1000)

    # For each, build a summary
    runs = []
    for event in all_events:
        execution_id = event.get("execution_id", event["id"])
        data = event.get("data", {})

        # Skip runs with no execution_id
        if not execution_id:
            continue

        # Status comes from the event's own status field (updated in-place by executor)
        run_status = event.get("status", "running")
        # Normalize: the executor sets "completed"/"failed" on the start event
        if run_status not in ("completed", "failed", "running", "cancelled"):
            run_status = "running"

        if status and run_status != status:
            continue

        runs.append({
            "id": execution_id,
            "workflow_name": data.get("name", ""),
            "status": run_status,
            "start_time": event.get("timestamp"),
            "end_time": None,  # Updated via data field
            "duration_seconds": data.get("duration_seconds"),
            "total_cost_usd": data.get("cost_usd", 0),
            "total_tokens": data.get("total_tokens", 0),
        })

    # Sort by start_time descending (most recent first)
    runs.sort(key=lambda r: r.get("start_time", ""), reverse=True)

    total = len(runs)
    runs = runs[offset: offset + limit]

    return {"runs": runs, "total": total}


def _build_node_execution(node_event: dict, all_events: list[dict]) -> dict:
    """Build a NodeExecution dict from a stage event and its children."""
    node_id = node_event["id"]
    data = node_event.get("data", {})

    # Find agent events (direct children of this node)
    agent_events = _find_children(all_events, node_id, "agent.")

    # Find nested stage events (children of this node that are stages)
    child_stage_events = _find_children(all_events, node_id, "stage.")
    child_nodes = [_build_node_execution(se, all_events) for se in child_stage_events]

    # For stage-type nodes: also collect agents from nested sub-graphs
    # The inner execute_graph creates its own stage events, and agents link to those
    if not agent_events and child_stage_events:
        # Look for agents in the inner graph's child stage events
        for child_stage in child_stage_events:
            child_agent_events = _find_children(all_events, child_stage["id"], "agent.")
            agent_events.extend(child_agent_events)
            # Also check one more level deep (inner stage → inner node → agent)
            inner_stages = _find_children(all_events, child_stage["id"], "stage.")
            for inner_stage in inner_stages:
                inner_agents = _find_children(all_events, inner_stage["id"], "agent.")
                agent_events.extend(inner_agents)

    agents = [_build_agent_execution(ae, all_events) for ae in agent_events]

    # Determine node type
    node_type = data.get("type", "agent" if agents and not child_nodes else "stage")

    total_cost = sum(a.get("estimated_cost_usd", 0) for a in agents)
    total_tokens = sum(a.get("total_tokens", 0) for a in agents)

    return {
        "id": node_id,
        "name": data.get("name", ""),
        "type": node_type,
        "status": _resolve_status(node_event),
        "start_time": node_event.get("timestamp"),
        "end_time": _get_end_time(all_events, node_id, "stage."),
        "duration_seconds": data.get("duration_seconds"),
        "cost_usd": data.get("cost_usd", total_cost),
        "total_tokens": data.get("total_tokens", total_tokens),
        "total_llm_calls": sum(a.get("total_llm_calls", 0) for a in agents),
        "total_tool_calls": sum(a.get("total_tool_calls", 0) for a in agents),
        "agent": agents[0] if len(agents) == 1 and node_type == "agent" else None,
        "agents": agents if len(agents) != 1 or node_type != "agent" else None,
        "child_nodes": child_nodes if child_nodes else None,
        "strategy": data.get("strategy"),
        "depends_on": data.get("depends_on", []),
        "loop_to": data.get("loop_to"),
        "max_loops": data.get("max_loops"),
        "error_message": data.get("error"),
    }


def _build_agent_execution(agent_event: dict, all_events: list[dict]) -> dict:
    """Build an AgentExecution dict from an agent event and its children.

    Merges data from both agent.started and agent.completed events.
    """
    agent_id = agent_event["id"]
    data = dict(agent_event.get("data", {}))
    agent_status = _resolve_status(agent_event)

    # Find and merge completed/failed event data (has output, tokens, cost)
    for e in all_events:
        if e.get("parent_id") == agent_id and \
           e.get("type", "").startswith("agent.") and \
           (e.get("type", "").endswith(".completed") or e.get("type", "").endswith(".failed")):
            data.update(e.get("data", {}))
            agent_status = e.get("status", agent_status)
            break

    # Find LLM calls (children of this agent)
    llm_events = _find_children(all_events, agent_id, "llm.call.")
    llm_calls = [_build_llm_call(le, all_events) for le in llm_events]

    # Find tool calls — they're children of LLM calls (grandchildren of agent)
    tool_events = _find_children(all_events, agent_id, "tool.call.")
    if not tool_events:
        for llm_event in llm_events:
            tool_events.extend(_find_children(all_events, llm_event["id"], "tool.call."))
    tool_calls = [_build_tool_call(te, all_events) for te in tool_events]

    # Aggregate from completion event data
    total_tokens = data.get("tokens", 0)
    cost = data.get("cost_usd", 0)

    return {
        "id": agent_id,
        "agent_name": data.get("agent_name", ""),
        "status": agent_status,
        "start_time": agent_event.get("timestamp"),
        "end_time": _get_end_time(all_events, agent_id, "agent."),
        "duration_seconds": data.get("duration_seconds"),
        "prompt_tokens": data.get("prompt_tokens", 0),
        "completion_tokens": data.get("completion_tokens", 0),
        "total_tokens": total_tokens,
        "estimated_cost_usd": cost,
        "total_llm_calls": len(llm_calls),
        "total_tool_calls": len(tool_calls),
        "llm_calls": llm_calls,
        "tool_calls": tool_calls,
        "output": data.get("output"),
        "structured_output": data.get("structured_output"),
        "role": data.get("role"),
        "error_message": data.get("error"),
        # Agent config and input data for context engineering visibility
        "input_data": agent_event.get("data", {}).get("input_data"),
        "agent_config_snapshot": _build_agent_config_snapshot(agent_event),
    }


def _build_agent_config_snapshot(agent_event: dict) -> dict | None:
    """Extract agent config from the started event data."""
    data = agent_event.get("data", {})
    config = data.get("agent_config")
    if config:
        return {"agent": config}
    # Fallback: build minimal config from available fields
    if data.get("provider") or data.get("model"):
        return {
            "agent": {
                "provider": data.get("provider"),
                "model": data.get("model"),
                "type": data.get("type", "llm"),
            }
        }
    return None


def _build_llm_call(event: dict, all_events: list[dict]) -> dict:
    """Build an LLM call dict from a started event, merging completed data.

    The LLM service records separate started and completed events (both children
    of the agent event). We match them by parent_id + iteration number.
    """
    data = dict(event.get("data", {}))
    status = _resolve_status(event)
    end_time = None

    # Find corresponding completed/failed event
    parent_id = event.get("parent_id")
    iteration = data.get("iteration")
    for e in all_events:
        etype = e.get("type", "")
        if (e.get("parent_id") == parent_id
                and etype.startswith("llm.call.")
                and (etype.endswith(".completed") or etype.endswith(".failed"))
                and e.get("data", {}).get("iteration") == iteration):
            data.update(e.get("data", {}))
            status = "completed" if etype.endswith(".completed") else "failed"
            end_time = e.get("timestamp")
            break

    return {
        "id": event["id"],
        "provider": data.get("provider"),
        "model": data.get("model"),
        "status": status,
        "start_time": event.get("timestamp"),
        "end_time": end_time,
        "duration_seconds": data.get("duration_seconds"),
        "prompt_tokens": data.get("prompt_tokens", 0),
        "completion_tokens": data.get("completion_tokens", 0),
        "total_tokens": data.get("total_tokens", 0),
        "estimated_cost_usd": data.get("cost_usd", 0),
        "prompt": data.get("messages"),
        "response": data.get("response_content"),
        "error_message": data.get("error"),
    }


def _build_tool_call(event: dict, all_events: list[dict] | None = None) -> dict:
    """Build a tool call dict from a started event, merging completed/failed data."""
    data = dict(event.get("data", {}))
    status = _resolve_status(event)
    end_time = None
    tool_name = data.get("tool_name", "")

    # Find the corresponding completed/failed event by matching tool_name
    # Tool completed/failed events share the same parent_id (the LLM call)
    if all_events and status == "running":
        start_id = event["id"]
        parent_id = event.get("parent_id")
        for e in all_events:
            e_type = e.get("type", "")
            e_data = e.get("data", {})
            # Match by: same parent, same tool_name, completed/failed type
            if (e_type.startswith("tool") and
                (e_type.endswith(".completed") or e_type.endswith(".failed")) and
                e_data.get("tool_name") == tool_name and
                (e.get("parent_id") == parent_id or e.get("parent_id") == start_id)):
                status = e.get("status", status)
                end_time = e.get("timestamp")
                data.update(e_data)
                break

    duration_ms = data.get("duration_ms")
    duration_seconds = duration_ms / 1000.0 if duration_ms else data.get("duration_seconds")

    return {
        "id": event["id"],
        "tool_name": tool_name,
        "status": status,
        "start_time": event.get("timestamp"),
        "end_time": end_time,
        "duration_seconds": duration_seconds,
        "input_data": data.get("input_params") or data.get("params"),
        "output_data": data.get("output") or data.get("result"),
        "error_message": data.get("error"),
    }


# --- Helpers ---

def _find_event_by_type(events: list[dict], type_prefix: str) -> dict | None:
    """Find first event matching a type prefix."""
    for e in events:
        if e.get("type", "").startswith(type_prefix):
            return e
    return None


def _find_children(events: list[dict], parent_id: str, type_prefix: str) -> list[dict]:
    """Find events that are children of a given parent and match a type prefix.
    Only returns 'started' events to avoid duplicates.
    """
    return [
        e for e in events
        if e.get("parent_id") == parent_id
        and e.get("type", "").startswith(type_prefix)
        and e.get("type", "").endswith(".started")
    ]


def _resolve_status(event: dict) -> str:
    """Resolve the status from an event."""
    return event.get("status", "pending")


def _get_end_time(events: list[dict], start_event_id: str, type_prefix: str) -> str | None:
    """Find the end time for a started event by looking for its completed/failed counterpart."""
    for e in events:
        if (e.get("parent_id") == start_event_id or e.get("id") == start_event_id) and \
           e.get("type", "").startswith(type_prefix) and \
           (e.get("type", "").endswith(".completed") or e.get("type", "").endswith(".failed")):
            return e.get("timestamp")
    return None
