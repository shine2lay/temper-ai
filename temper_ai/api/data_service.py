"""Data service — reconstructs execution hierarchy from flat events.

The observability module stores flat events (workflow_started, stage_started,
agent_started, etc.). This service reads them and builds the nested hierarchy
that the frontend expects: WorkflowExecution → NodeExecution → AgentExecution.
"""

from __future__ import annotations

import json
import logging
from collections import deque
from collections.abc import Sequence
from datetime import datetime, timedelta

from temper_ai.observability import get_events
from temper_ai.observability.event_types import EventType
from temper_ai.observability.recorder import event_parents
from temper_ai.observability.script_logs import SCRIPT_LOG_PREFIX
from temper_ai.runner import quiet
from temper_ai.stage.gate import APPROVED, REJECTED

logger = logging.getLogger(__name__)

# llm.* and tool.* events are nearly all of a big run's events and nearly all
# of its bytes (a call's start carries its prompt). They only fill in an
# agent's calls, so they stay capped, newest kept. The events that say which
# stages and agents ran are few, and are read in full however long the run:
# under one cap for everything, a run past it lost its newest stages and
# agents, and the page knew them only by id.
_CALL_EVENT_PREFIXES = ("llm.", "tool.")
MAX_CALL_EVENTS = 10000
# Script agents' saved logs (observability/script_logs.py) are no part of a run's record either:
# up to ~10 MB per attempt, read a page at a time through their own endpoint, never with the run.
_NOT_STRUCTURE_PREFIXES = (*_CALL_EVENT_PREFIXES, SCRIPT_LOG_PREFIX)

# A run in one of these can still start or finish agents.
_LIVE_RUN_STATUSES = ("pending", "queued", "running", "waiting", "cancelling")


def _load_run_events(execution_id: str) -> list[dict]:
    """A run's events, oldest first: every structural event, the newest calls."""
    structure = get_events(
        execution_id=execution_id, exclude_type_prefixes=_NOT_STRUCTURE_PREFIXES, limit=None,
    )
    calls = get_events(
        execution_id=execution_id, type_prefixes=_CALL_EVENT_PREFIXES,
        limit=MAX_CALL_EVENTS, newest_first=True,
    )
    seen: set[str] = set()
    events: list[dict] = []
    for e in [*structure, *calls]:
        if e["id"] not in seen:
            seen.add(e["id"])
            events.append(e)
    events.sort(key=lambda e: e.get("timestamp") or "")
    return events


def get_agent_index(execution_id: str) -> list[dict] | None:
    """Every agent a run started, light; None when the run has no events.

    What the run page looks up when output streams in for an agent it does
    not know yet. Reads no llm.*/tool.* events, so it stays cheap on a run
    whose full record takes seconds to build.
    """
    events = get_events(
        execution_id=execution_id, exclude_type_prefixes=_NOT_STRUCTURE_PREFIXES, limit=None,
    )
    if not events:
        return None
    return _agent_index(events)


# The inputs of a tool call that name a file or folder, in the order its paths are listed.
# No other input of a call ever leaves the server (see get_tool_calls).
TOOL_CALL_PATH_KEYS = ("path", "file_path", "notebook_path", "filename", "cwd", "worktree")

_TOOL_CALL_ENDS = {"tool.call.completed": "completed", "tool.call.failed": "failed"}


def get_tool_calls(execution_id: str, contains: Sequence[str] = ()) -> dict | None:
    """Every tool call of a run and the files it named, never what was in them; None when
    the run has no events.

    For a script that checks, from inside its own run (no database there), which files
    the run's agents went near. Each call says which attempt made it (the agent.started
    id, as the run page and the agent index name it), its agent, node and round (from the
    agent index), the tool, who ran it, its status (from its own end event) and when it
    started. ``paths`` are the values under TOOL_CALL_PATH_KEYS, as the agent wrote them.
    ``hits`` are the strings of ``contains`` found anywhere in the call's inputs: a Bash
    ``cat`` names no path key. Nothing else of a call is returned: no Write content, no
    Edit strings, no Bash command, no output, no result. ``blocked`` lists the tool calls
    the run refused (tool.blocked); their error text names the refused path.

    Every tool event of the run is read, however long the run (the run page keeps a long
    run's newest 10,000 calls), and a model call only for its id and parent, never its
    prompt. Read in Python: some events hold \\u0000, which Postgres cannot turn into text.
    """
    structure = get_events(
        execution_id=execution_id, exclude_type_prefixes=_NOT_STRUCTURE_PREFIXES, limit=None,
    )
    tool_events = get_events(execution_id=execution_id, type_prefixes=("tool.",), limit=None)
    if not structure and not tool_events:
        return None
    parents = {e["id"]: e.get("parent_id") for e in structure}
    parents.update(event_parents(execution_id, ("llm.call.started",)))
    attempts = {entry["id"]: entry for entry in _agent_index(structure)}
    markers = list(dict.fromkeys(contains))

    starts = [e for e in tool_events if e.get("type") == "tool.call.started"]
    ends = _tool_call_ends(starts, [e for e in tool_events if e.get("type") in _TOOL_CALL_ENDS])
    calls: list[dict] = []
    open_until: list[str | None] = []  # when each call ended, for placing a refusal in it
    for start in starts:
        data = start.get("data") or {}
        params = data.get("input_params")
        attempt_id = _attempt_above(start, parents, attempts)
        entry = attempts.get(attempt_id or "")
        end = ends.get(start["id"])
        text = json.dumps(params, ensure_ascii=False, default=str) if markers else ""
        calls.append({
            "call_id": data.get("call_id") or None,
            "attempt_id": attempt_id,
            "agent_name": entry["agent_name"] if entry else data.get("agent_name"),
            "node_name": entry["node_name"] if entry else data.get("node_path"),
            "round": entry["round"] if entry else None,
            "tool_name": data.get("tool_name"),
            "executed_by": data.get("executed_by"),
            "server": data.get("server"),
            "status": _TOOL_CALL_ENDS[end["type"]] if end else "running",
            "start_time": start.get("timestamp"),
            "paths": _named_paths(params),
            "hits": [m for m in markers if m in text],
        })
        open_until.append(end.get("timestamp") if end else None)

    blocked: list[dict] = []
    for event in tool_events:
        if event.get("type") != "tool.blocked":
            continue
        data = event.get("data") or {}
        attempt_id = (_attempt_above(event, parents, attempts)
                      or _attempt_of_the_call_refused(event, calls, open_until))
        entry = attempts.get(attempt_id or "")
        blocked.append({
            "attempt_id": attempt_id,
            "agent_name": entry["agent_name"] if entry else data.get("agent_name"),
            "round": entry["round"] if entry else None,
            "tool_name": data.get("tool_name"),
            "reason": data.get("reason"),
            "error": data.get("error"),
        })
    return {
        "execution_id": execution_id,
        "tool_calls": calls,
        "blocked": blocked,
        "counts": {"tool_calls": len(calls), "blocked": len(blocked)},
    }


def _attempt_above(event: dict, parents: dict[str, str | None], attempts: dict[str, dict]) -> str | None:
    """The agent.started an event hangs under, up its parent_ids (a tool call's parent is its
    model call, whose parent is the agent; a Pi agent's tool hangs right under the agent).
    None when the chain breaks before one."""
    seen: set[str] = set()
    current = event.get("parent_id")
    while current and current not in seen:
        if current in attempts:
            return current
        seen.add(current)
        current = parents.get(current)
    return None


def _tool_call_ends(starts: list[dict], ends: list[dict]) -> dict[str, dict]:
    """Each tool call start's own end event (tool.call.completed or .failed), by start id.

    By call_id when the start has one (a provider's or Pi's call). Temper's own calls have
    none: like the run page, the first end not yet taken of the same tool under the same
    model call, which runs its tools one at a time.
    """
    by_call_id: dict[str, dict] = {}
    by_turn: dict[tuple[str | None, str | None], deque[dict]] = {}
    for end in ends:
        data = end.get("data") or {}
        if data.get("call_id"):
            by_call_id.setdefault(data["call_id"], end)
        else:
            by_turn.setdefault((end.get("parent_id"), data.get("tool_name")), deque()).append(end)
    paired: dict[str, dict] = {}
    for start in starts:
        data = start.get("data") or {}
        own: dict | None
        if data.get("call_id"):
            own = by_call_id.get(data["call_id"])
        else:
            waiting = by_turn.get((start.get("parent_id"), data.get("tool_name")))
            own = waiting.popleft() if waiting else None
        if own is not None:
            paired[start["id"]] = own
    return paired


def _named_paths(params: object) -> list[str]:
    """The strings (or lists of strings) under TOOL_CALL_PATH_KEYS, in that order, once each."""
    if not isinstance(params, dict):
        return []
    paths: list[str] = []
    for key in TOOL_CALL_PATH_KEYS:
        value = params.get(key)
        for item in value if isinstance(value, list) else [value]:
            if isinstance(item, str) and item not in paths:
                paths.append(item)
    return paths


def _attempt_of_the_call_refused(block: dict, calls: list[dict], open_until: list[str | None]) -> str | None:
    """The attempt a refusal recorded with no parent came from: that of the call it refused.

    The tool executor is not told which model call asked, so its tool.blocked hangs under
    nothing. It is recorded while the call it refuses is open: a call of that tool (and of
    that agent, when the refusal names one) that had started and not yet ended. None when
    no such call is open, or the open ones belong to different attempts.
    """
    data = block.get("data") or {}
    at = block.get("timestamp") or ""
    agent = data.get("agent_name")
    found = {
        call["attempt_id"]
        for call, ended in zip(calls, open_until, strict=True)
        if call["tool_name"] == data.get("tool_name")
        and (not agent or call["agent_name"] == agent)
        and (call["start_time"] or "") <= at
        and (ended is None or at <= ended)
    }
    return found.pop() if len(found) == 1 else None


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
    events = _load_run_events(execution_id)
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

    workflow_event = max(workflow_candidates, key=_start_completeness)
    # How the run stands now is its newest attempt's to say, not the most complete one's: a
    # failed first attempt that cost something must not show a resumed run as failed while
    # the new attempt runs or waits on a person (shown_status).
    attempt_now = newest_attempt(workflow_candidates) or workflow_event

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
            # Oldest first, so a step's run after its approval comes after the wait.
            by_name[key] = _keep_gate_answer(n, by_name[key]) if key in by_name else n

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

    # Inline same-named passthrough children. When a stage has a child
    # of the same name (the executor's stage-ref expansion creates these),
    # pull the passthrough's children/agents up so the view doesn't show
    # a redundant "stage > stage" double-wrap. Runs before the renester
    # so dispatched siblings dedupe against the inlined contents instead
    # of competing with a passthrough wrapper.
    _inline_passthroughs(nodes)

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
                    if src_name not in restored_names:
                        continue
                    if src_name not in current_node_names:
                        src_node["restored_from_fork"] = True
                        nodes.insert(0, src_node)
                        continue
                    # A stage that went on from its own last finished step: the steps it kept
                    # ran in the source, and show beside the ones this run did.
                    for i, node in enumerate(nodes):
                        if node.get("name") == src_name:
                            nodes[i] = _merge_node_recursive(latest=node, older=src_node)

    # Calculate aggregates. Summing only top-level nodes missed every
    # dynamically dispatched child (they hang under the dispatcher, whose
    # own cost covers just its planning call), so a dispatch-heavy run
    # reported $0.00 / 0 tokens. `_sum_node_metric` walks the tree with the
    # right rule per node type; the workflow event's own totals (computed by
    # the executor over every node, dispatched included) win when present.
    wf_data = workflow_event.get("data", {})
    total_cost = wf_data.get("cost_usd")
    if total_cost is None:
        total_cost = _sum_node_metric(nodes, "cost_usd")
    total_tokens = wf_data.get("total_tokens")
    if total_tokens is None:
        total_tokens = _sum_node_metric(nodes, "total_tokens")
    # The node tree holds one entry per name, so attempts a loop rewind
    # discarded aren't in it. The executor publishes their share separately;
    # add it rather than replace, since these two counts come from different
    # sources (nested llm.*/tool.* events here, AgentResult in the executor).
    total_llm_calls = _sum_node_metric(nodes, "total_llm_calls") + (
        wf_data.get("retired_llm_calls") or 0
    )
    total_tool_calls = _sum_node_metric(nodes, "total_tool_calls") + (
        wf_data.get("retired_tool_calls") or 0
    )

    result = {
        "id": execution_id,
        "workflow_name": wf_data.get("name", ""),
        "status": shown_status(_resolve_status(attempt_now), wait_open=_a_wait_is_open(events)),
        "start_time": workflow_event.get("timestamp"),
        "end_time": _get_end_time(events, workflow_event["id"], "workflow."),
        "duration_seconds": wf_data.get("duration_seconds"),
        "nodes": nodes,
        "total_tokens": total_tokens,
        "total_cost_usd": total_cost,
        "total_llm_calls": total_llm_calls,
        "total_tool_calls": total_tool_calls,
        "input_data": wf_data.get("input_data"),
        "workspace_path": wf_data.get("workspace_path"),
        "output_data": wf_data.get("output_data"),
        "workflow_output": wf_data.get("workflow_output"),
        "error_message": wf_data.get("error"),
        "fork_source": fork_data.get("source_execution_id") if fork_meta else None,
        # The tree above keeps one node per name, so an agent from an earlier
        # loop round or run attempt is not in it; its output still streams to
        # the page. This names every agent the run started.
        "agent_index": _agent_index(events),
        # Where the run stopped and why, when a failure stopped it, with the clean-ups it is
        # keeping back (stage/failure.py). The page says what failed instead of leaving the
        # reader to find it among the nodes.
        "stopped": wf_data.get("stopped"),
        # Every earlier attempt of this run, oldest first, so the page can say a run was
        # resumed -- and whether a person pressed Resume or temper picked it up itself after
        # a crash (runner/pickup.py). The steps of those attempts are merged into the tree
        # above; this is who they were.
        "attempts": _attempts(workflow_candidates, attempt_now),
    }
    result.update(_quiet_fields(execution_id, result, events))
    _clear_children_index()
    return result


def _quiet_fields(execution_id: str, result: dict, events: list[dict]) -> dict:
    """Whether this run has gone quiet, from the events already in hand.

    The run page asks for a run every few seconds; the newest event is already
    loaded here, so saying "quiet for 2h 14m" costs nothing but the reading.
    """
    status = str(result.get("status") or "")
    newest = max((e for e in events if e.get("timestamp")),
                 key=lambda e: e.get("timestamp") or "", default=None)
    at_a_gate = _a_wait_is_open(events)
    try:
        workflow = str(result.get("workflow_name") or "")
        verdict = quiet.look(
            quiet.Run(
                execution_id=execution_id,
                workflow_name=workflow,
                status=status,
                last_activity_at=quiet.moment(newest.get("timestamp")) if newest else None,
                started_at=quiet.moment(result.get("start_time")),
                at_a_gate=at_a_gate,
                last_step=quiet.last_step_label(
                    str(newest.get("type") or ""), newest.get("data"),
                    str(newest.get("status") or ""),
                ) if newest else "",
                after=quiet.after_for(workflow),
                parked_until=_parked_until(newest),
            ),
        )
    except Exception as exc:  # noqa: BLE001 - never lose a run page over a badge
        logger.warning("could not work out whether %s is quiet: %s", execution_id[:8], exc)
        return {}
    fields = {
        "quiet": verdict.quiet,
        "last_step": verdict.last_step,
        "last_activity": verdict.since.isoformat() if verdict.since else None,
        "waiting_on_you": verdict.state == quiet.WAITING,
    }
    if verdict.state == quiet.WAITING:
        fields["waiting_for"] = verdict.how_long
    if verdict.state == quiet.PARKED:
        fields["parked"] = True
        fields["parked_until"] = (
            verdict.parked_until.isoformat() if verdict.parked_until else None
        )
    if verdict.quiet:
        fields["quiet_since"] = verdict.since.isoformat() if verdict.since else None
        fields["quiet_for"] = verdict.how_long
        fields["quiet_seconds"] = int(verdict.idle.total_seconds()) if verdict.idle else 0
    return fields


def _parked_until(newest: dict | None) -> datetime | None:
    """When the run this event belongs to wakes, if it is parked for the allowance.

    A parked run writes nothing while it waits, so its own park event is the
    newest thing it has done -- the same rule ``quiet.activity_of`` applies to
    a listing row, applied here to the run page's own events.
    """
    if not newest or newest.get("type") != quiet.ALLOWANCE_EVENT:
        return None
    if str(newest.get("status") or "") != "waiting":
        return None
    return quiet.moment((newest.get("data") or {}).get("until"))


def _agent_index(events: list[dict]) -> list[dict]:
    """One light entry per agent.started of the run, oldest first.

    Every loop round and every resumed attempt, which the name-merged tree
    drops. No calls, prompts, inputs or outputs: a big run starts hundreds of
    agents and this rides along on every refresh of the run page. An agent
    still marked running when its attempt was replaced by a resume, or when
    the run is over, was cut off: it says "interrupted", not "running".
    """
    by_id = {e["id"]: e for e in events}
    attempts = [e for e in events if e.get("type") == "workflow.started"]
    newest = max(attempts, key=lambda e: e.get("timestamp") or "", default=None)
    run_live = newest is not None and _resolve_status(newest) in _LIVE_RUN_STATUSES

    ends: dict[str, dict] = {}
    for e in events:
        if e.get("type") in ("agent.completed", "agent.failed") and e.get("parent_id"):
            ends.setdefault(e["parent_id"], e)

    rounds: dict[str, int] = {}
    index: list[dict] = []
    started = [e for e in events if e.get("type") == "agent.started"]
    for ev in sorted(started, key=lambda e: e.get("timestamp") or ""):
        end = ends.get(ev["id"])
        data = {**(ev.get("data") or {}), **((end or {}).get("data") or {})}
        status = (end or {}).get("status") or _resolve_status(ev)
        if status in ("pending", "running"):
            attempt = _attempt_of(ev, by_id)
            if not run_live or (attempt is not None and newest is not None and attempt != newest["id"]):
                status = "interrupted"
        name = data.get("agent_name") or ""
        rounds[name] = rounds.get(name, 0) + 1
        node = by_id.get(ev.get("parent_id") or "")
        index.append({
            "id": ev["id"],
            "agent_name": name,
            "round": rounds[name],
            "status": status,
            "node_id": ev.get("parent_id"),
            "node_name": ((node or {}).get("data") or {}).get("name"),
            "start_time": ev.get("timestamp"),
            "end_time": (end or {}).get("timestamp"),
            "duration_seconds": data.get("duration_seconds"),
            "prompt_tokens": data.get("prompt_tokens", 0),
            "completion_tokens": data.get("completion_tokens", 0),
            "total_tokens": data.get("tokens", 0),
            "estimated_cost_usd": data.get("cost_usd", 0),
            "error_message": data.get("error"),
            "role": data.get("role"),
            # script and jev agents say it at the top; an LLM agent in its config.
            "agent_type": data.get("type") or _config_type(data.get("agent_config")),
            "provider": data.get("provider"),
            "model": data.get("model"),
        })
    return index


def _config_type(config: object) -> str | None:
    """`type` of an agent.started's agent_config, flat or under `agent`."""
    if not isinstance(config, dict):
        return None
    nested = config.get("agent")
    value = config.get("type") or (nested.get("type") if isinstance(nested, dict) else None)
    return value if isinstance(value, str) else None


def _attempt_of(event: dict, by_id: dict[str, dict]) -> str | None:
    """Id of the workflow.started an event hangs under, or None if its chain breaks."""
    seen: set[str] = set()
    current: dict | None = event
    while current is not None and current["id"] not in seen:
        if current.get("type") == "workflow.started":
            return str(current["id"])
        seen.add(current["id"])
        current = by_id.get(current.get("parent_id") or "")
    return None


def _execution_ids_awaiting_a_human() -> set[str]:
    """Runs with a gate still waiting for an answer.

    A gate is a ``stage.started`` event left in ``waiting`` with ``gate`` set
    on its data; it is cleared in place when the gate is answered, so the
    query is always about the present.
    """
    events = get_events(
        event_type=EventType("stage.started"),
        status="waiting",
        limit=500,
        newest_first=True,
    )
    return {
        eid
        for ev in events
        if (ev.get("data") or {}).get("gate") and (eid := ev.get("execution_id"))
    }


def list_workflow_executions(
    limit: int = 20,
    offset: int = 0,
    status: str | None = None,
) -> dict:
    """List workflow executions with summary data.

    Returns: {"runs": [...], "total": int}
    """
    # Get the most RECENT workflow start events. Without newest_first the query
    # returns the oldest `limit` rows, so once the events table grows past the
    # limit the listing freezes on the earliest runs and never shows new ones.
    all_events = get_events(
        event_type=EventType("workflow.started"), limit=1000, newest_first=True
    )

    by_exec = _one_start_per_run(all_events)
    attempts_now = _newest_start_per_run(all_events)

    # A run parked on a gate is NOT running -- it is waiting for a person,
    # and the listing is where that person looks. Without this the two are
    # indistinguishable in the list ('running', spinner, no affordance), so a
    # run that is blocked on a human sits there until someone thinks to open
    # it. One query covers the whole page.
    awaiting = _execution_ids_awaiting_a_human()

    runs = []
    for execution_id, event in by_exec.items():
        data = event.get("data", {})
        # Totals and times speak for the run (the most complete attempt); the status is how
        # its newest attempt stands.
        run_status = _list_status(execution_id, attempts_now.get(execution_id, event), awaiting)

        if status and run_status != status:
            continue

        # The executor updates the started event in place rather than emitting
        # a completed event, so derive the end from start + duration instead
        # of returning null for every run.
        started = event.get("timestamp")
        duration = data.get("duration_seconds")
        end_time = None
        if started and duration is not None:
            try:
                end_time = (
                    datetime.fromisoformat(started) + timedelta(seconds=float(duration))
                ).isoformat()
            except (TypeError, ValueError):
                end_time = None

        runs.append({
            "id": execution_id,
            "workflow_name": data.get("name", ""),
            "status": run_status,
            "start_time": started,
            "end_time": end_time,
            "duration_seconds": duration,
            "total_cost_usd": data.get("cost_usd", 0),
            "total_tokens": data.get("total_tokens", 0),
        })

    # Sort by start_time descending (most recent first)
    runs.sort(key=lambda r: r.get("start_time", ""), reverse=True)

    total = len(runs)
    runs = runs[offset: offset + limit]
    _mark_the_quiet_ones(runs, awaiting)

    return {"runs": runs, "total": total}


def _start_completeness(ev: dict) -> tuple:
    """Which of a run's workflow.started events speaks for it: a resumed run records a NEW
    one with the same execution_id. Prefer completed, then the one with a non-zero cost,
    then the newest by timestamp, so the listing doesn't double-count resumed runs and its
    totals agree with the detail endpoint."""
    d = ev.get("data") or {}
    s = ev.get("status", "")
    return (
        1 if s == "completed" else 0,
        1 if (d.get("cost_usd") or 0) > 0 else 0,
        ev.get("timestamp", ""),
    )


def _one_start_per_run(events: list[dict]) -> dict[str, dict]:
    """The workflow.started event that speaks for each run, by execution id."""
    by_exec: dict[str, dict] = {}
    for ev in events:
        eid = ev.get("execution_id", ev["id"])
        if not eid:
            continue
        prev = by_exec.get(eid)
        if prev is None or _start_completeness(ev) > _start_completeness(prev):
            by_exec[eid] = ev
    return by_exec


def _newest_start_per_run(events: list[dict]) -> dict[str, dict]:
    """Each run's newest attempt (its latest workflow.started event), by execution id."""
    by_exec: dict[str, dict] = {}
    for ev in events:
        eid = ev.get("execution_id", ev["id"])
        if not eid:
            continue
        prev = by_exec.get(eid)
        if prev is None or str(ev.get("timestamp") or "") > str(prev.get("timestamp") or ""):
            by_exec[eid] = ev
    return by_exec


def newest_attempt(events: Sequence[dict]) -> dict | None:
    """A run's newest attempt: of its ``workflow.started`` events, the latest.

    A resumed run records a new one for each attempt, and the newest says how the run stands
    now. Which attempt's totals speak for the run is another question (``_start_completeness``).
    """
    starts = [e for e in events if e.get("type") == EventType.WORKFLOW_STARTED.value]
    return max(starts, key=lambda e: str(e.get("timestamp") or ""), default=None)


#: How an attempt that is over ended. A run whose newest attempt is over shows how it ended,
#: even with a wait left open: nobody can answer that wait into the attempt any more (a cancel
#: or a crash at a gate leaves it behind), and calling the run waiting would hold it in the
#: list for ever.
_ATTEMPT_OVER = ("completed", "failed", "cancelled", "interrupted")


def shown_status(attempt_status: str, *, wait_open: bool) -> str:
    """A run's status as the run page, the run list and the Team page show it.

    How its newest attempt stands, except ``waiting`` while that attempt is parked on a
    person's answer (a Pi run lets its worker go) or still going with a person's wait open
    in the run: a gate, a step's question to the owner, a Pi recovery question.
    """
    if attempt_status == "waiting":
        return "waiting"
    if wait_open and attempt_status not in _ATTEMPT_OVER:
        return "waiting"
    return attempt_status


def _a_wait_is_open(events: Sequence[dict]) -> bool:
    """Whether any of these events is a wait still open for a person: a ``stage.started`` left
    in ``waiting`` with ``gate`` set (a gate, or a step's question to the owner). Taken over the
    whole run, not one attempt: a resumed attempt waits on again the wait an earlier one opened.
    """
    return any(
        e.get("type") == "stage.started" and e.get("status") == "waiting"
        and (e.get("data") or {}).get("gate")
        for e in events
    )


def _list_status(execution_id: str, attempt: dict, awaiting: set[str]) -> str:
    """One run's status as the run list shows it, from its newest attempt (``shown_status``)."""
    # Status comes from the attempt's own status field (updated in-place by the executor).
    # Whitelist recognised states: "interrupted" signals an orphaned run left by a server
    # restart, "waiting" a Pi run parked on a person's answer.
    run_status = attempt.get("status", "running")
    if run_status not in ("completed", "failed", "running", "cancelled", "interrupted", "waiting"):
        run_status = "running"
    return shown_status(str(run_status), wait_open=execution_id in awaiting)


def run_detail_status(execution_id: str) -> str | None:
    """The run's status exactly as ``GET /api/workflows/{id}`` gives it, without building the
    whole run (None when there is no such run)."""
    events = get_events(execution_id=execution_id, type_prefixes=("workflow.",), limit=None)
    if not events:
        return None
    attempt = newest_attempt(events) or max(events, key=_start_completeness)
    waits = get_events(execution_id=execution_id, event_type=EventType("stage.started"),
                       status="waiting", limit=None)
    return shown_status(_resolve_status(attempt), wait_open=_a_wait_is_open(waits))


def run_list_statuses(execution_ids: Sequence[str]) -> dict[str, str]:
    """Each of these runs' status exactly as the run list shows it (the Team page's trials
    list puts it beside the team's own decision, M3 E19). A run with no start event yet is
    left out."""
    if not execution_ids:
        return {}
    awaiting = _execution_ids_awaiting_a_human()
    out: dict[str, str] = {}
    for eid in execution_ids:
        starts = get_events(execution_id=eid, event_type=EventType("workflow.started"),
                            limit=None)
        attempt = newest_attempt(starts)
        if attempt is not None:
            out[eid] = _list_status(eid, attempt, awaiting)
    return out


def _mark_the_quiet_ones(runs: list[dict], awaiting: set[str]) -> None:
    """Add ``quiet``/``quiet_for``/``last_step`` to the runs of one page.

    A run still marked running that has written nothing for longer than its
    threshold gets said so here, so the list shows "quiet for 2h 14m" instead
    of a spinner that means nothing. Only the page's own rows are looked up,
    and a run that has ended is not looked up at all.
    """
    if not runs:
        return
    try:
        verdicts = quiet.verdicts_for(runs, gated=awaiting)
    except Exception as exc:  # noqa: BLE001 - a listing must still render
        logger.warning("could not work out which runs are quiet: %s", exc)
        return
    for run in runs:
        verdict = verdicts.get(str(run.get("id")))
        if verdict is None:
            continue
        run["quiet"] = verdict.quiet
        run["last_step"] = verdict.last_step
        run["last_activity"] = verdict.since.isoformat() if verdict.since else None
        # How long it has been waiting for its answer. A gate is healthy, but
        # a gate nobody has answered since this morning is the thing that
        # actually goes unnoticed: "needs you" said the same at two minutes
        # and at ten hours.
        if verdict.state == quiet.WAITING:
            run["waiting_on_you"] = True
            run["waiting_for"] = verdict.how_long
        # Waiting for the model allowance to reopen: a wait with a known end
        # and nothing for anybody to do. Said apart from "needs you" so the
        # two are never confused on the listing.
        if verdict.state == quiet.PARKED:
            run["parked"] = True
            run["parked_until"] = (
                verdict.parked_until.isoformat() if verdict.parked_until else None
            )
        if verdict.quiet:
            run["quiet_since"] = verdict.since.isoformat() if verdict.since else None
            run["quiet_for"] = verdict.how_long
            run["quiet_seconds"] = int(verdict.idle.total_seconds()) if verdict.idle else 0


def _inline_passthroughs(nodes: list[dict]) -> None:
    """Walk the tree and collapse same-named "stage-ref passthrough"
    wrappers. When a stage `S` has a child stage also named `S`, pull
    that child's child_nodes and agents up to be siblings of S's other
    children. Mutates nodes in place.

    The executor creates these passthroughs when expanding YAML `ref:`
    entries — visually they're a redundant outer wrapper. The frontend's
    own unwrap only handles the case where the passthrough is the ONLY
    child; this server-side pass handles it even when sibling children
    exist (e.g. after the recursive resume merge or the renester adds
    dispatched siblings alongside the passthrough).

    On collisions during inlining (passthrough's child has same name as a
    sibling already at parent level), the existing sibling is kept and
    the passthrough's version is dropped. The recursive merge already ran
    upstream so the existing sibling is the up-to-date one.
    """
    for node in nodes:
        kids = node.get("child_nodes") or []
        if not kids:
            continue
        node_name = node.get("name") or node.get("id")
        # First, recurse so deeply-nested passthroughs get inlined too —
        # important for pipeline_t1 > pipeline_t1 chains.
        _inline_passthroughs(kids)

        # Then check this level for any same-named child to inline.
        rebuilt: list[dict] = []
        existing_names = {
            (k.get("name") or k.get("id"))
            for k in kids
            if k.get("name") or k.get("id")
        }
        for kid in kids:
            kid_name = kid.get("name") or kid.get("id")
            is_passthrough = (
                kid.get("type") == "stage"
                and kid_name == node_name
                and (kid.get("child_nodes") or kid.get("agents"))
            )
            if not is_passthrough:
                rebuilt.append(kid)
                continue
            # Inline: pull passthrough's children up, dropping any whose
            # name already exists at this level (sibling wins).
            for grandkid in kid.get("child_nodes") or []:
                gk_name = grandkid.get("name") or grandkid.get("id")
                if gk_name in existing_names:
                    continue
                rebuilt.append(grandkid)
                if gk_name:
                    existing_names.add(gk_name)
            # Merge passthrough's agents into parent's agents.
            parent_agents = node.get("agents") or []
            kid_agents = kid.get("agents") or []
            if kid_agents:
                by_agent_name = {
                    (a.get("agent_name") or a.get("id")): a
                    for a in parent_agents
                    if a.get("agent_name") or a.get("id")
                }
                for a in kid_agents:
                    n = a.get("agent_name") or a.get("id")
                    if n and n not in by_agent_name:
                        by_agent_name[n] = a
                node["agents"] = list(by_agent_name.values())
        node["child_nodes"] = rebuilt


def _attempts(workflow_events: list[dict], latest: dict) -> list[dict]:
    """One entry per attempt of this run, oldest first.

    A run cut off by a crash and started again keeps its execution id and gets
    a second ``workflow.started``; the entries say when each attempt ran, how
    it ended, and which of them temper picked back up by itself "" the stamp
    ``runner/pickup.py`` leaves on the attempt it resumed.

    A single entry means a run that ran once: the page shows nothing.
    """
    starts = [e for e in workflow_events if e.get("type") == "workflow.started"]
    if len(starts) < 2:
        return []
    starts.sort(key=lambda e: e.get("timestamp") or "")
    out = []
    for i, event in enumerate(starts, start=1):
        data = event.get("data") or {}
        stamp = data.get("auto_resumed") or {}
        out.append({
            "attempt": i,
            "event_id": event.get("id"),
            "start_time": event.get("timestamp"),
            "status": _resolve_status(event),
            "error": data.get("error"),
            "is_current": event.get("id") == latest.get("id"),
            # This attempt was the one temper picked up again by itself; the next
            # attempt in the list is what came of it.
            "picked_up_by_temper": bool(stamp),
            "picked_up_at": stamp.get("at") if isinstance(stamp, dict) else None,
        })
    return out


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
    merged = _keep_gate_answer(dict(latest), older)

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

    # A Pi step's turns: every attempt's turns stay, each its own agent, oldest first. An
    # owner wait between two turns lets the worker go, so the next turn runs in a new attempt
    # (docs/pi-agent.md), and the turns share the step's name.
    older_turns, latest_turns = _pi_turns(older), _pi_turns(latest)
    if older_turns:
        by_id = {a["id"]: a for a in older_turns + latest_turns}  # latest wins per turn
        turns = sorted(by_id.values(), key=lambda a: a.get("start_time") or "")
        merged["agent"], merged["agents"] = (turns[0], None) if len(turns) == 1 else (None, turns)
        return merged

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


#: A wait's answer and who gave it, kept on its step's node (see ``_keep_gate_answer``).
_GATE_ANSWER_FIELDS = ("gate", "gate_status", "gate_decided_by", "gate_decided_at", "gate_caller")


def _keep_gate_answer(node: dict, earlier: dict) -> dict:
    """``node`` with the answer to ``earlier``'s wait, when ``node`` has no wait of its own.

    A step with a wait in front of it is two stage events under one name: the wait (``gate``,
    its answer, who gave it, api/caller.py) and, once approved, the step's own run, which
    knows nothing of the wait. The run page shows the answer and "decided by" from the node
    (frontend bigview/shape.ts), so without this they vanish the moment the step starts.
    Only an answer is carried: a wait still open, or one replaced by a later ask, is not one.
    """
    if node.get("gate") or not earlier.get("gate"):
        return node
    if earlier.get("gate_status") not in (APPROVED, REJECTED):
        return node
    return {**node, **{field: earlier.get(field) for field in _GATE_ANSWER_FIELDS}}


def _pi_turns(node: dict) -> list[dict]:
    """The Pi turns on one attempt's node, whether one (``agent``) or several (``agents``)."""
    agents = node.get("agents") or ([node["agent"]] if node.get("agent") else [])
    return [a for a in agents
            if ((a.get("agent_config_snapshot") or {}).get("agent") or {}).get("type") == "pi"]


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
        # input_map entries that pointed at something that did not exist.
        # The agent ran with nulls in their place, so the run can be green
        # and still wrong; surfacing this is the only way to notice.
        "unresolved_inputs": data.get("unresolved_inputs"),
        "depends_on": data.get("depends_on", []),
        "loop_to": data.get("loop_to"),
        "max_loops": data.get("max_loops"),
        # A node parked at (or released from) a human gate; the dashboard
        # opens the gate modal instead of the stage detail for a waiting one.
        "gate": data.get("gate"),
        "gate_status": data.get("gate_status"),
        # Who answered the wait and when: the person (or what they answered through) and the
        # caller that sent it, a named key, slack:<id>... (api/caller.py). None before it was kept.
        "gate_decided_by": data.get("gate_decided_by"),
        "gate_decided_at": data.get("gate_decided_at"),
        "gate_caller": data.get("gate_caller"),
        # A Pi team's story (messages, reviews, owner waits, decision): the stage view's
        # Collaboration fold. Set only by a team node (temper_ai/pi_agent/team_leader.py).
        "collaboration_events": data.get("collaboration_events"),
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
        # A script agent's saved log, in figures only (rows, bytes saved, limit, truncated,
        # complete): the log itself is read page by page (GET /api/runs/<id>/agents/<id>/log).
        "log": data.get("log"),
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


def _claimed_completions() -> set:
    """Completion events already paired with a start, for this request.

    Lives on the same thread-local as the children index so it resets with
    it; without this, name-based pairing hands the first completion to every
    same-named start.
    """
    claimed = getattr(_children_index_local, "claimed_completions", None)
    if claimed is None:
        claimed = set()
        _children_index_local.claimed_completions = claimed
    return claimed


def _build_tool_call(event: dict, all_events: list[dict] | None = None) -> dict:
    """Build a tool call dict from a started event, merging completed/failed data."""
    data = dict(event.get("data", {}))
    status = _resolve_status(event)
    end_time = None
    tool_name = data.get("tool_name", "")

    # Find the corresponding completed/failed event. Prefer the call_id both
    # sides carry: matching by tool_name alone paired the *first* completion
    # with every same-named start, so an agent that called browser_extract
    # twice under one LLM call showed both with the first result. Fall back
    # to name + parent for events recorded before call ids existed.
    if all_events and status == "running":
        start_id = event["id"]
        parent_id = event.get("parent_id")
        call_id = data.get("call_id")
        claimed = _claimed_completions()
        for e in all_events:
            e_type = e.get("type", "")
            e_data = e.get("data", {})
            if not (e_type.startswith("tool") and
                    (e_type.endswith(".completed") or e_type.endswith(".failed"))):
                continue
            if call_id:
                matched = e_data.get("call_id") == call_id
            else:
                matched = (
                    e_data.get("tool_name") == tool_name
                    and (e.get("parent_id") == parent_id or e.get("parent_id") == start_id)
                    and e["id"] not in claimed
                )
            if matched:
                claimed.add(e["id"])
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
        # Which side ran it and where it went: "mcp" over a named server, or
        # a "builtin" of whoever executed it ("temper", or a provider name).
        "transport": data.get("transport"),
        "server": data.get("server"),
        "executed_by": data.get("executed_by"),
        "call_id": data.get("call_id"),
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
    _children_index_local.claimed_completions = set()


def _clear_children_index() -> None:
    """Clear the cached children index."""
    _children_index_local.index = None
    _children_index_local.claimed_completions = None


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
    """End time for a started event.

    Prefers an explicit ``*.completed`` / ``*.failed`` counterpart. The
    executor does not emit one for workflows and stages — it updates the
    started event in place — so fall back to start + duration, which is why
    every run used to report ``end_time: null``.
    """
    for e in events:
        if (e.get("parent_id") == start_event_id or e.get("id") == start_event_id) and \
           e.get("type", "").startswith(type_prefix) and \
           (e.get("type", "").endswith(".completed") or e.get("type", "").endswith(".failed")):
            return e.get("timestamp")

    for e in events:
        if e.get("id") != start_event_id:
            continue
        duration = (e.get("data") or {}).get("duration_seconds")
        started = e.get("timestamp")
        if duration is None or not started:
            return None
        try:
            return (datetime.fromisoformat(started) + timedelta(seconds=float(duration))).isoformat()
        except (TypeError, ValueError):
            return None
    return None


def _sum_node_metric(nodes: list[dict], key: str) -> float:
    """Total of `key` over a node tree.

    A ``stage`` node's own figure is already the sum of its children, so only
    the children are counted. An ``agent`` node counts itself plus any nodes
    it dispatched at runtime (those are separate executions nested under it).
    """
    total: float = 0
    for node in nodes:
        children = node.get("child_nodes") or []
        if node.get("type") == "stage":
            total += _sum_node_metric(children, key)
        else:
            total += node.get(key) or 0
            total += _sum_node_metric(children, key)
    return total
