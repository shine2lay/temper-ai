"""Data service — reconstructs execution hierarchy from flat events.

The observability module stores flat events (workflow_started, stage_started,
agent_started, etc.). This service reads them and builds the nested hierarchy
that the frontend expects: WorkflowExecution → NodeExecution → AgentExecution.
"""

from __future__ import annotations

import logging

from temper_ai.observability import get_events
from temper_ai.observability.event_types import EventType

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

    # Build children index for O(1) lookups (cleared at end of function)
    _set_children_index(events)

    # Find workflow event
    # If the run was resumed, there may be multiple workflow.started events
    # for this execution_id. Pick the most complete one so detail totals
    # stay consistent with the listing (same selection rule as
    # list_workflow_executions' dedup).
    workflow_candidates = [
        e for e in events if e.get("type", "").startswith("workflow.")
    ]
    if not workflow_candidates:
        _clear_children_index()
        return None

    def _completeness(ev: dict) -> tuple:
        d = ev.get("data") or {}
        s = ev.get("status", "")
        return (
            1 if s == "completed" else 0,
            1 if (d.get("cost_usd") or 0) > 0 else 0,
            ev.get("timestamp", ""),
        )
    workflow_event = max(workflow_candidates, key=_completeness)

    # Check for fork metadata — if present, merge source execution's nodes
    fork_meta = next(
        (e for e in events if e.get("type") == "fork.metadata"),
        None,
    )

    # Build node executions across all attempts for this execution_id,
    # filtered by what the engine considers part of the current run state.
    #
    # When a run is interrupted and resumed, each attempt has its own
    # `workflow.started` event. The engine stamps the new event with
    # `data.restored_node_names = [list of names whose outputs came from
    # checkpoint]` — that's the authoritative "still alive" list.
    #
    # We walk children of every workflow event for this execution_id, and
    # for prior-attempt nodes we include only those whose name appears in
    # the latest attempt's restored_names OR latest's own children.
    # Anything else is orphaned (e.g. dispatched siblings from a prior
    # attempt that the new dispatcher didn't recreate).
    #
    # Recursive merge by name: latest wins for the node's own state, but
    # child_nodes / agents are unioned so nested descendants from earlier
    # attempts (e.g. pre-interruption pipelines inside `sprint`) survive
    # the dedupe.
    #
    # Falls back gracefully on pre-metadata events (those without
    # restored_node_names): if the latest event has no metadata, we
    # don't filter — the merge happens unchanged.
    latest_data = workflow_event.get("data") or {}
    restored_names: set[str] = set(latest_data.get("restored_node_names") or [])
    has_resume_signal = bool(restored_names) or bool(latest_data.get("resume_of"))

    latest_children_events = _find_children(events, workflow_event["id"], "stage.")
    latest_nodes = [_build_node_execution(e, events) for e in latest_children_events]
    latest_names = {n.get("name") for n in latest_nodes if n.get("name")}

    by_name: dict[str, dict] = {}
    for n in latest_nodes:
        key = n.get("name") or n.get("id")
        if key:
            by_name[key] = n

    for prior in workflow_candidates:
        if prior["id"] == workflow_event["id"]:
            continue  # already processed as latest
        prior_children_events = _find_children(events, prior["id"], "stage.")
        for ev in prior_children_events:
            built = _build_node_execution(ev, events)
            key = built.get("name") or built.get("id")
            if not key:
                continue
            # Drop orphans on resumed runs: top-level nodes from older
            # attempts that aren't restored AND don't share a name with
            # any latest top-level. On non-resumed (pre-metadata) runs
            # we skip this filter since we don't know what's alive.
            if has_resume_signal and key not in latest_names and key not in restored_names:
                continue
            existing = by_name.get(key)
            if existing is None:
                by_name[key] = built
                continue
            if (built.get("start_time") or "") >= (existing.get("start_time") or ""):
                by_name[key] = _merge_node_recursive(latest=built, older=existing)
            else:
                by_name[key] = _merge_node_recursive(latest=existing, older=built)

    nodes = list(by_name.values())
    nodes.sort(key=lambda n: n.get("start_time") or "")
    current_node_names = {n.get("name") for n in nodes if n.get("name")}

    # Annotate nodes with dispatch relationships. `dispatch.applied` events
    # list each dispatcher's added children + removed targets. Frontend
    # uses these fields to show "dispatcher" badges on parents and
    # "dispatched by X" / "removed by X" badges on children. Must run
    # before `_renest_dispatched_into_containers` so `dispatched_by` is
    # populated on the nodes the renester inspects.
    _annotate_dispatch_relationships(nodes, events)

    # Re-nest top-level dispatched siblings under the container that
    # dispatched them. After resume the engine sometimes promotes a
    # dispatched pipeline (which was originally nested inside `sprint`)
    # to a top-level sibling. Conceptually the pipeline is part of the
    # sprint that fanned it out — restore that structure.
    nodes = _renest_dispatched_into_containers(nodes)

    # For forked runs: fetch restored nodes from the source execution
    if fork_meta:
        fork_data = fork_meta.get("data", {})
        source_id = fork_data.get("source_execution_id")
        restored_names = set(fork_data.get("restored_node_names", []))

        if source_id and restored_names:
            source = get_workflow_execution(source_id)
            if source:
                for src_node in source.get("nodes", []):
                    src_name = src_node.get("name", "")
                    if src_name in restored_names and src_name not in current_node_names:
                        src_node["restored_from_fork"] = True
                        nodes.insert(0, src_node)

    # Calculate aggregates
    total_cost = sum(n.get("cost_usd", 0) for n in nodes)
    total_tokens = sum(n.get("total_tokens", 0) for n in nodes)
    total_llm_calls = sum(n.get("total_llm_calls", 0) for n in nodes)
    total_tool_calls = sum(n.get("total_tool_calls", 0) for n in nodes)

    wf_data = workflow_event.get("data", {})
    result = {
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
        "workflow_output": wf_data.get("workflow_output"),
        "error_message": wf_data.get("error"),
        "fork_source": fork_data.get("source_execution_id") if fork_meta else None,
    }
    _clear_children_index()
    return result


def list_workflow_executions(
    limit: int = 20,
    offset: int = 0,
    status: str | None = None,
) -> dict:
    """List workflow executions with summary data.

    Returns: {"runs": [...], "total": int}
    """
    # Get all workflow start events
    all_events = get_events(event_type=EventType("workflow.started"), limit=1000)

    # Dedup by execution_id: a resumed run records a NEW workflow.started
    # event with the same execution_id. Keep the event with the most complete
    # data — prefer completed, then the one with a non-zero cost, then the
    # newest by timestamp. This prevents the listing from double-counting
    # resumed runs and keeps totals consistent with the detail endpoint.
    def _completeness(ev: dict) -> tuple:
        d = ev.get("data") or {}
        s = ev.get("status", "")
        return (
            1 if s == "completed" else 0,
            1 if (d.get("cost_usd") or 0) > 0 else 0,
            ev.get("timestamp", ""),
        )
    by_exec: dict[str, dict] = {}
    for ev in all_events:
        eid = ev.get("execution_id", ev["id"])
        if not eid:
            continue
        prev = by_exec.get(eid)
        if prev is None or _completeness(ev) > _completeness(prev):
            by_exec[eid] = ev

    runs = []
    for execution_id, event in by_exec.items():
        data = event.get("data", {})
        # Status comes from the event's own status field (updated in-place
        # by the executor). Whitelist recognized terminal states;
        # "interrupted" signals an orphaned run left by a server restart.
        run_status = event.get("status", "running")
        if run_status not in ("completed", "failed", "running", "cancelled", "interrupted"):
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


def _build_resume_chain(latest_event: dict, all_workflow_events: list[dict]) -> list[dict]:
    """Walk the resume chain backwards from `latest_event` via the
    `data.resume_of` link the engine stamps on each new workflow.started
    during resume. Returns chain[0] = latest_event, chain[N] = oldest
    ancestor. Stops on missing pointer, missing target, or cycle.

    A chain longer than 1 means this run was interrupted and resumed; a
    chain of length 1 is a fresh run.
    """
    chain = [latest_event]
    seen = {latest_event["id"]}
    by_id = {e["id"]: e for e in all_workflow_events}
    while True:
        prev_id = (chain[-1].get("data") or {}).get("resume_of")
        if not prev_id or prev_id in seen:
            break
        prev = by_id.get(prev_id)
        if prev is None:
            break
        chain.append(prev)
        seen.add(prev_id)
    return chain


def _renest_dispatched_into_containers(nodes: list[dict]) -> list[dict]:
    """Move top-level nodes with `dispatched_by` into the container whose
    agent did the dispatching.

    The engine sometimes places dispatched siblings at the top level after
    resume (the new attempt's dispatcher creates them as workflow-level
    children rather than re-nesting under the originating stage). Users
    expect "this pipeline was part of that sprint" to translate to
    nesting in the view, so we normalize by walking each top-level node's
    name + agent_name index and re-attaching dispatched-by'd siblings
    into the container that owns the dispatcher.

    Handles dedupe: if the destination already has a child with the same
    name (because that container ran in an earlier attempt with a nested
    copy of the same pipeline), the two are merged via
    `_merge_node_recursive` rather than duplicated.
    """
    if not nodes:
        return nodes

    name_to_top: dict[str, dict] = {}

    def index(n: dict, top: dict) -> None:
        nm = n.get("name") or n.get("id")
        if nm:
            name_to_top[nm] = top
        for a in n.get("agents") or []:
            an = a.get("agent_name") or a.get("id")
            if an:
                name_to_top[an] = top
        for c in n.get("child_nodes") or []:
            index(c, top)

    for top in nodes:
        index(top, top)

    keep: list[dict] = []
    for n in nodes:
        dispatcher = n.get("dispatched_by")
        if not dispatcher:
            keep.append(n)
            continue
        ancestor = name_to_top.get(dispatcher)
        if ancestor is None or ancestor is n:
            keep.append(n)
            continue
        kids = ancestor.get("child_nodes") or []
        existing_idx = None
        n_name = n.get("name") or n.get("id")
        for i, k in enumerate(kids):
            if (k.get("name") or k.get("id")) == n_name:
                existing_idx = i
                break
        if existing_idx is not None:
            existing = kids[existing_idx]
            if (n.get("start_time") or "") >= (existing.get("start_time") or ""):
                kids[existing_idx] = _merge_node_recursive(latest=n, older=existing)
            else:
                kids[existing_idx] = _merge_node_recursive(latest=existing, older=n)
        else:
            kids.append(n)
        ancestor["child_nodes"] = kids

    return keep


def _merge_node_recursive(*, latest: dict, older: dict) -> dict:
    """Merge two NodeExecution dicts that share a name across resume attempts.

    The `latest` (more recent start_time) wins for the node's own state —
    status, agents at the leaf, totals, timing. But child_nodes and agents
    are *unioned* by name with recursive merging, so we don't lose nested
    descendants from an earlier attempt when the same stage re-ran with a
    different set of children. Without this, a `sprint` that ran twice
    (each producing different pipelines) would show only the second run's
    pipelines, dropping the first run's completed work from view.
    """
    merged = dict(latest)

    # Merge child_nodes by name, recursively.
    older_kids = older.get("child_nodes") or []
    latest_kids = latest.get("child_nodes") or []
    if older_kids or latest_kids:
        kid_by_name: dict[str, dict] = {}
        for kid in older_kids:
            key = kid.get("name") or kid.get("id")
            if key:
                kid_by_name[key] = kid
        for kid in latest_kids:
            key = kid.get("name") or kid.get("id")
            if not key:
                continue
            existing = kid_by_name.get(key)
            if existing is None:
                kid_by_name[key] = kid
            else:
                if (kid.get("start_time") or "") >= (existing.get("start_time") or ""):
                    kid_by_name[key] = _merge_node_recursive(latest=kid, older=existing)
                else:
                    kid_by_name[key] = _merge_node_recursive(latest=existing, older=kid)
        merged["child_nodes"] = list(kid_by_name.values()) or None

    # Merge leaf agents by agent_name. Latest's data wins per agent.
    older_agents = older.get("agents") or []
    latest_agents = latest.get("agents") or []
    if older_agents and not latest_agents:
        merged["agents"] = older_agents
    elif older_agents and latest_agents:
        agent_by_name: dict[str, dict] = {}
        for a in older_agents:
            key = a.get("agent_name") or a.get("id")
            if key:
                agent_by_name[key] = a
        for a in latest_agents:
            key = a.get("agent_name") or a.get("id")
            if key:
                agent_by_name[key] = a  # latest wins per agent
        merged["agents"] = list(agent_by_name.values())

    return merged


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
        "delegated_by": data.get("delegated_by"),
        "delegate_source": data.get("delegate_source"),
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
        "output_data": data.get("structured_output"),
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
        "thinking": data.get("reasoning"),
        "tool_calls": data.get("tool_calls"),
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


def _annotate_dispatch_relationships(nodes: list[dict], events: list[dict]) -> None:
    """Stamp each node with dispatch metadata derived from dispatch.applied events.

    Adds (when applicable) to each node:
      - dispatched_by:     dispatcher node name (for nodes ADDED via dispatch)
      - dispatched_children: list[str] names (for dispatcher nodes)
      - removed_children:    list[str] names (targets the dispatcher removed)

    The frontend reads these to render "dispatcher"/"dispatched" badges on
    the DAG and to draw dispatched-edge labels. Removed-child names that
    aren't in `nodes` are still listed on the dispatcher so the timeline
    can show "removed X" even when X never materialized as a node.
    """
    nodes_by_name: dict[str, dict] = {n["name"]: n for n in nodes if n.get("name")}

    for event in events:
        if event.get("type") != "dispatch.applied":
            continue
        data = event.get("data") or {}
        dispatcher = data.get("dispatcher")
        if not isinstance(dispatcher, str):
            continue  # malformed event — skip rather than crash
        added: list[str] = [n for n in (data.get("added") or []) if isinstance(n, str)]
        removed: list[str] = [n for n in (data.get("removed") or []) if isinstance(n, str)]

        dispatcher_node = nodes_by_name.get(dispatcher)
        if dispatcher_node is not None:
            # Accumulate across multiple dispatch events from the same dispatcher
            existing_added = dispatcher_node.setdefault("dispatched_children", [])
            existing_removed = dispatcher_node.setdefault("removed_children", [])
            existing_added.extend(n for n in added if n not in existing_added)
            existing_removed.extend(n for n in removed if n not in existing_removed)

        # Tag each child with its dispatcher so the frontend can render
        # "dispatched by <dispatcher>" on that node.
        for child_name in added:
            child_node = nodes_by_name.get(child_name)
            if child_node is not None:
                child_node["dispatched_by"] = dispatcher


import threading as _threading  # noqa: E402  (below helper defs for locality)

_children_index_local = _threading.local()


def _build_children_index(events: list[dict]) -> dict[str, list[dict]]:
    """Build a parent_id → [children] index for O(1) lookups."""
    index: dict[str, list[dict]] = {}
    for e in events:
        pid = e.get("parent_id")
        if pid:
            index.setdefault(pid, []).append(e)
    return index


def _set_children_index(events: list[dict]) -> None:
    """Build and cache the children index for the current request."""
    _children_index_local.index = _build_children_index(events)


def _clear_children_index() -> None:
    """Clear the cached children index."""
    _children_index_local.index = None


def _find_children(events: list[dict], parent_id: str, type_prefix: str) -> list[dict]:
    """Find events that are children of a given parent and match a type prefix.
    Only returns 'started' events to avoid duplicates.
    Uses thread-local cached index for O(1) lookup instead of O(N) scan.
    """
    index = getattr(_children_index_local, "index", None)
    if index is None:
        # Fallback: build inline (for callers that don't set up the index)
        index = _build_children_index(events)

    candidates = index.get(parent_id, [])
    return [
        e for e in candidates
        if e.get("type", "").startswith(type_prefix)
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
