"""Graph executor — iterates nodes in topological order, evaluates conditions,
handles loops, resolves inputs, and calls node.run(). Independent nodes at
the same topological level run concurrently via ThreadPoolExecutor.
"""

from __future__ import annotations

import logging
import os
import re
import time
import uuid
from collections import defaultdict, deque
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from typing import Any

from temper_ai.observability.event_types import EventType
from temper_ai.observability.recorder import event_parents
from temper_ai.observability.run_totals import attempt_spend
from temper_ai.shared.clock import utcnow
from temper_ai.shared.types import ExecutionContext, NodeResult, Status
from temper_ai.stage.conditions import evaluate_condition, source_value
from temper_ai.stage.exceptions import (
    REPLACED_MARK,
    CancellationError,
    CyclicDependencyError,
    ReplacedByLaterAttempt,
    RunParked,
    WorkflowError,
)
from temper_ai.stage.failure import FailurePolicy, RunStop, is_cleanup, undoes
from temper_ai.stage.gate import (
    APPROVED,
    EMPTY_RESPONSE,
    REPLACED,
    WAITING,
    GateSignal,
    build_gate_context,
    earlier_waits,
    signal_key,
)
from temper_ai.stage.node import Node
from temper_ai.stage.restore import Restore
from temper_ai.stage.step_waits import (
    forget_run,
    forget_step,
    note_unspent_answers,
    park,
    spend_answers,
)

logger = logging.getLogger(__name__)

# How often a node parked at a human gate re-checks cancellation and, for
# runs executed outside the API process, the database for approval.
GATE_POLL_SECONDS = 2.0

def execute_graph_with_state(
    nodes: list[Node],
    input_data: dict,
    context: ExecutionContext,
    graph_name: str = "",
    is_workflow: bool = False,
    initial_outputs: dict[str, NodeResult] | None = None,
    workflow_outputs: dict[str, str] | None = None,
    resume_metadata: dict | None = None,
) -> NodeResult:
    """Execute a graph with pre-populated node_outputs (for resume from checkpoints).

    `resume_metadata` flows through to `execute_graph` so the resumed
    workflow.started event carries the link back to the prior attempt.

    `workflow_outputs` does too, and must: a resumed run is the same workflow as the
    one it resumes, so it owes the same outputs. Without it the run finishes with
    ``workflow_output`` empty, and anything reading the run for what it did -- a
    driver recording the outcome, the dashboard -- sees a run that did nothing.
    """
    return execute_graph(
        nodes, input_data, context,
        graph_name=graph_name, is_workflow=is_workflow,
        initial_outputs=initial_outputs,
        workflow_outputs=workflow_outputs,
        resume_metadata=resume_metadata,
    )


def execute_graph(
    nodes: list[Node],
    input_data: dict,
    context: ExecutionContext,
    graph_name: str = "",
    is_workflow: bool = False,
    initial_outputs: dict[str, NodeResult] | None = None,
    workflow_outputs: dict[str, str] | None = None,
    resume_metadata: dict | None = None,
) -> NodeResult:
    """Execute a graph of nodes in topological order, concurrently where possible.

    When `resume_metadata` is provided (non-None, only meaningful at the
    top-level workflow call), it's merged into the WORKFLOW_STARTED event's
    `data` so the view can identify this attempt as a resume of a prior
    workflow event. Expected keys:
      - `resume_of` (str): id of the prior workflow.started event
      - `restored_node_names` (list[str]): names whose outputs came from
        a checkpoint instead of fresh execution
      - `replayed_dispatches` (list[str], optional): dispatcher names
        whose dispatch state was replayed without re-emitting events
    """
    start_event = EventType.WORKFLOW_STARTED if is_workflow else EventType.STAGE_STARTED
    node_map = {node.name: node for node in nodes}
    batches = topological_sort(nodes)
    # A restore hands over every checkpoint of the run, keyed by node path; this graph takes
    # only the ones that name its own nodes. A stage child's `build.deploy` is not the
    # top-level `deploy`, and a stage's total already holds its children's cost.
    # The rest stay with the run's Restore for the stages to claim when they start, so a stage
    # that was running when the run stopped goes on from its own last finished step
    # (stage/restore.py).
    # An unreadable checkpoint authority is not an empty run. Read once, before any
    # attempt event or batch, and retain its ended results alongside the stop marker.
    state = _resume_state(context) if is_workflow and initial_outputs is not None else {}
    if is_workflow and initial_outputs is not None and not isinstance(getattr(context, "restore", None), Restore):
        context.restore = Restore(initial_outputs, state.get("loops"), state.get("failed") or (),
                                  dispatches=state.get("dispatches"))
    if is_workflow and initial_outputs is not None:
        # A resume (whoever built its Restore): a step may finish from its own record this
        # time without asking, and the answers it took before are still spent when it does.
        # One read of the run's waits per resume, none per step.
        note_unspent_answers(context)
    restore = getattr(context, "restore", None)
    # Where the run stopped, shared by every graph of the run: a failure inside a stage has to
    # stop the batches at the top as well, or the run goes on spending on work it cannot use.
    if is_workflow and not isinstance(getattr(context, "run_stop", None), RunStop):
        context.run_stop = RunStop(policy=context.failure_policy or FailurePolicy())
        # So every stage inherits the workflow's setting and can override it for itself.
        context.failure_policy = context.run_stop.policy
    if is_workflow and initial_outputs is not None:
        # A self-stop is durable, not unfinished work. Close the door before claiming any
        # batches: the stopped Pi may inspect its ended record again, but a skipped branch
        # (even one moved earlier in a revised workflow) must never restart on Resume.
        self_stop = state.get("self_cancelled")
        if isinstance(self_stop, dict) and self_stop.get("path"):
            context.run_stop.note_cancelled(str(self_stop["path"]), self_stop.get("reason"))
            context.run_stop.reopening = True
            context.run_stop.saved_results = state.get("self_cancelled_results") or {}
    if isinstance(restore, Restore):
        # Agents a dispatcher added to this graph during the earlier attempt come back here,
        # in their own stage, before anything is claimed -- they are part of this graph's
        # topology, not the workflow's (see stage/restore.py).
        nodes, node_map, batches, tombstones = _readd_dispatched(
            nodes, node_map, batches, restore, context, graph_name,
        )
    loop_counts: dict[str, int] = defaultdict(int)
    loop_feedback: dict[str, NodeResult] = {}
    if isinstance(restore, Restore):
        prefix = f"{context.node_path}." if context.node_path else ""
        claimed = restore.claim(
            prefix,
            {name: list(node.depends_on) for name, node in node_map.items()},
            _renamed_from(node_map),
        )
        node_outputs, loop_feedback = claimed.outputs, claimed.loop_feedback
        loop_counts.update(claimed.loop_counts)
        node_outputs = {k: v for k, v in node_outputs.items() if k in node_map}
        # What a kept dispatcher took out of the graph last time stays out of it.
        node_outputs.update(tombstones)
        if claimed.reset and context.checkpoint_service is not None:
            for name in claimed.reset:
                context.checkpoint_service.save_node_reset(prefix + name)
        if claimed.reset:
            logger.info("Resume of '%s': %s had finished and run again (a failure at or before them)",
                        graph_name, ", ".join(claimed.reset))
    else:
        old_names = {old: name for name, olds in _renamed_from(node_map).items() for old in olds}
        node_outputs = {old_names[k]: v for k, v in (initial_outputs or {}).items() if k in old_names}
        # a result under the node's own name is the later word
        node_outputs.update({k: v for k, v in (initial_outputs or {}).items() if k in node_map})
    start = time.monotonic()

    start_data: dict = {"name": graph_name, "node_count": len(nodes)}
    if node_outputs and not is_workflow:
        # What this stage kept from before the resume and will not run again. A workflow's
        # are in its resume_metadata.
        start_data["restored_node_names"] = sorted(node_outputs)
    if is_workflow:
        # The request that started the run, so a resume or fork can rebuild
        # the same inputs (before this, resume re-ran nodes with {} inputs)
        # and the API can show what a run was asked to do.
        start_data["input_data"] = input_data
        start_data["workspace_path"] = context.workspace_path
    if is_workflow and resume_metadata:
        start_data.update(resume_metadata)

    graph_event_id = context.event_recorder.record(
        start_event,
        data=start_data,
        parent_id=context.parent_event_id if not is_workflow else None,
        execution_id=context.run_id,
        status="running",
    )

    # Store graph event ID on context so Delegate tool can parent child nodes to the DAG
    context.graph_event_id = graph_event_id

    # Expose live node_outputs to tools that need to introspect run state
    # (e.g. QueryRunState). Shared reference — updates become visible to tools
    # as nodes complete. Only the top-level workflow call seeds this; nested
    # stage executions inherit the existing reference so a sub-stage's tools
    # see the full run, not just their sub-stage's outputs.
    if context.run_state is None:
        context.run_state = node_outputs

    # Attempts discarded by a loop rewind. They are gone from node_outputs but
    # they were paid for, so the run's totals have to keep them.
    retired: list[NodeResult] = []
    # What a resume kept from earlier attempts: paid for there, counted here as at a normal end.
    kept = tuple(node_outputs.values())
    stood_down = False

    try:
        _run_batches(
            batches, node_map, input_data, node_outputs, loop_counts, context, graph_event_id,
            retired, loop_feedback,
        )
        # A stop that lands while a step is running kills that step, which then
        # ends failed. With no batch after it to notice the stop, the run would
        # be reported failed too, when nothing broke and someone stopped it.
        if _stopped_mid_step(context, node_outputs):
            raise CancellationError("Workflow cancelled by user")
        stopped = _settle_run(context, nodes, node_outputs, input_data) if is_workflow else None
        return _build_final_result(
            nodes, node_outputs, input_data, start, graph_event_id, context, workflow_outputs,
            is_workflow=is_workflow, retired=retired, stopped=stopped,
        )

    except RunParked as parked:
        stop = getattr(context, "run_stop", None)
        if not (is_workflow and isinstance(stop, RunStop) and stop.stopped):
            _note_parked(parked, nodes, node_outputs, retired, context, graph_event_id, start,
                         is_workflow=is_workflow)
            raise
        if stop.kind == "cancelled":
            # A sibling stopped itself while this gate was already waiting. Keep the
            # sibling's decision: never turn the stopped run red because a gate parked.
            return _end_graph(
                CancellationError(stop.reason or "the step was stopped"),
                nodes, node_outputs, retired, input_data, context, graph_event_id, start,
                is_workflow=is_workflow,
            )
        # A step failed beside the gate (the same parallel batch): the run stops on that
        # failure, as it would have once the gate was answered. The open wait keeps whatever
        # answer comes for a Resume, as at any stopped run.
        return _end_graph(
            WorkflowError(f"'{stop.path}' failed while '{parked.path}' waited on you: {stop.reason}"),
            nodes, node_outputs, retired, input_data, context, graph_event_id, start,
            is_workflow=is_workflow, kept=kept,
        )

    except ReplacedByLaterAttempt as replaced:
        # A later attempt of this run took over, so this one stands down: only its own graph
        # event is written down. Nothing of the run's is touched -- no settling, no stop, no
        # holds, and the asked answers in memory stay for the newer attempt (SW-84).
        stood_down = True
        _note_replaced(replaced, context, graph_event_id, start,
                       spent=(*node_outputs.values(), *retired))
        raise

    except Exception as exc:
        return _end_graph(exc, nodes, node_outputs, retired, input_data, context, graph_event_id,
                          start, is_workflow=is_workflow, kept=kept)

    finally:
        if is_workflow and not stood_down:
            # This go of the run is over: what its steps asked stays in the run's record only.
            forget_run(context.run_id)


def _note_replaced(replaced: ReplacedByLaterAttempt, context: ExecutionContext, event_id: str,
                   start: float, *, spent: tuple[NodeResult, ...] | None = None) -> None:
    """Write one of this attempt's own events down as stood down for a later attempt.

    ``cancelled`` (every reader knows it), marked ``replaced_by_later_attempt`` so nobody
    takes it for the run being stopped: the webhook sends nothing for it, and the run's
    own status comes from its newest attempt.

    A graph's event also says what the attempt spent (``spent``: its finished steps and the
    ones a loop threw away), summed as a parked or ended graph's is, so per-attempt cost
    stays whole. A step's has nothing to add: the step never finished.

    Best-effort: a write that fails is logged and the caller still raises the stand-down.
    Raised from here, the write's error would take the stand-down's place and the attempt
    would end the run as failed: the later attempt's run (SW-84).
    """
    data = {"error": str(replaced), REPLACED_MARK: True,
            "duration_seconds": time.monotonic() - start}
    if spent is not None:
        data["cost_usd"] = sum(r.cost_usd for r in spent)
        data["total_tokens"] = sum(r.total_tokens for r in spent)
    try:
        context.event_recorder.update_event(event_id, status=Status.CANCELLED.value, data=data)
    except Exception as exc:  # noqa: BLE001 - at worst the event is not marked; it stands down
        logger.warning("Event %s: could not write it down as stood down for a later attempt: %s",
                       event_id, exc)


def _note_parked(
    parked: RunParked,
    nodes: list[Node],
    node_outputs: dict[str, NodeResult],
    retired: list[NodeResult],
    context: ExecutionContext,
    graph_event_id: str,
    start: float,
    *,
    is_workflow: bool,
) -> None:
    """Write a graph down as waiting on the owner, with what carrying it on needs.

    The run's own event (``workflow.started``) gets status ``waiting`` and a ``parked`` note:
    which wait, where, the round, the checkpoint, when, what the attempt cost, and what a
    cancel must hold (no worker is left to work that out then). Nothing is settled: the run
    is not over. A stage's event just says it is waiting. runner/parked.py reads the note.
    """
    duration = time.monotonic() - start
    if not is_workflow:
        context.event_recorder.update_event(
            graph_event_id, status="waiting",
            data={"parked": parked.as_dict(), "duration_seconds": duration},
        )
        return
    note = {
        **parked.as_dict(),
        "at": utcnow().isoformat(),
        "cost_usd": sum(r.cost_usd for r in (*node_outputs.values(), *retired)),
        "total_tokens": sum(r.total_tokens for r in (*node_outputs.values(), *retired)),
        "on_cancel": _parked_on_cancel(context, nodes, node_outputs),
    }
    context.event_recorder.update_event(
        graph_event_id, status="waiting", data={"parked": note, "duration_seconds": duration},
    )


def _parked_on_cancel(
    context: ExecutionContext,
    nodes: list[Node],
    node_outputs: dict[str, NodeResult],
) -> dict | None:
    """What cancelling the parked run must keep back, worked out while the graph is at hand.

    The same as a cancel during a held wait would leave (``_settle_run``): under a holding
    failure policy every clean-up that has not run is held for a resume.
    """
    if getattr(context, "run_only", None) is not None:
        return None
    stop = getattr(context, "run_stop", None)
    if not isinstance(stop, RunStop):
        return None
    owed = _cleanups_owed(nodes, node_outputs, context.node_path or "") if stop.policy.holds else []
    return {
        "mode": stop.policy.mode,
        "hold_hours": stop.policy.hold_hours,
        "held": [{"path": path, "undoes": list(undone)} for path, undone in owed],
    }


def _end_graph(
    exc: Exception,
    nodes: list[Node],
    node_outputs: dict[str, NodeResult],
    retired: list[NodeResult],
    input_data: dict,
    context: ExecutionContext,
    graph_event_id: str,
    start: float,
    *,
    is_workflow: bool,
    kept: tuple[NodeResult, ...] = (),
) -> NodeResult:
    """End a graph that was thrown out: cancelled by hand, or broken."""
    duration = time.monotonic() - start
    # A user cancel is its own terminal state, not a failure: the run
    # list, the CLI exit code and downstream callers all treat it
    # differently (nothing went wrong; someone stopped it).
    terminal = Status.CANCELLED if isinstance(exc, CancellationError) else Status.FAILED
    error = str(exc)
    stopped = None
    if is_workflow:
        # Stopped by hand, or thrown out by something that broke: either way nothing more
        # ran, so the clean-ups are still owed and the setup is still standing.
        stop = getattr(context, "run_stop", None)
        if isinstance(stop, RunStop):
            stop.note_failure(context.node_path or "the run", error)
            if stop.kind == "cancelled" and not (
                    context.cancel_event is not None and context.cancel_event.is_set()):
                # A gate/exception may leave the batches before they emit the remaining
                # skips. The same door records each unstarted node, and no failure after
                # the decision can replace the stopped run's neutral outcome.
                for node in nodes:
                    if node.name not in node_outputs:
                        # Ending an attempt never retries failed inspection or enters an
                        # enclosing stage: reconcile only from the known snapshot.
                        skipped = _held_or_skipped(node, context, graph_event_id, reconcile=False)
                        if skipped is not None:
                            node_outputs[node.name] = skipped
                            prefix = f"{context.node_path}." if context.node_path else ""
                            _record_outcome(node, skipped, prefix, context, context.checkpoint_service)
                terminal = Status.CANCELLED
                error = stop.reason or "the step was stopped"
        stopped = _settle_run(context, nodes, node_outputs, input_data)
    data: dict = {"error": error, "duration_seconds": duration,
                  **({"stopped": stopped} if stopped else {})}
    if is_workflow:
        # Every way a run ends leaves what it spent, as a completed run's does (queue #65).
        data.update(_ended_run_totals(context, graph_event_id, node_outputs, retired, kept))
    context.event_recorder.update_event(graph_event_id, status=terminal.value, data=data)
    return NodeResult(
        status=terminal,
        error=error,
        agent_results=[r for nr in node_outputs.values() for r in nr.agent_results],
        node_results=node_outputs,
        duration_seconds=duration,
        cost_usd=data.get("cost_usd", sum(r.cost_usd for r in (*node_outputs.values(), *retired))),
        total_tokens=data.get("total_tokens", sum(r.total_tokens for r in (*node_outputs.values(), *retired))),
    )


def _ended_run_totals(
    context: ExecutionContext,
    graph_event_id: str,
    node_outputs: dict[str, NodeResult],
    retired: list[NodeResult],
    kept: tuple[NodeResult, ...] = (),
) -> dict:
    """A thrown-out run's totals for its event, by the completed-run rule plus the step in flight.

    At a normal end (``_build_final_result``) the steps' results say what the run spent: the
    finished steps, what a resume kept from earlier attempts (``kept``) and the attempts a loop
    threw away. A step in flight when the run was thrown out hands no result back, so here
    this attempt's own spend is read from what its agents recorded (observability/run_totals.py:
    every model call under this graph's event, rewound attempts and the step in flight
    included), with what was kept from earlier attempts added. The results' sum is the floor.
    If the events can't be read, the results alone are written: the run still ends.
    """
    spent = (*node_outputs.values(), *retired)
    cost = sum(r.cost_usd for r in spent)
    tokens = sum(r.total_tokens for r in spent)
    try:
        parents = event_parents(context.run_id, ("workflow.", "stage.", "agent."))
        recorded = attempt_spend(context.run_id, graph_event_id, parents)
        cost = max(cost, sum(r.cost_usd for r in kept) + recorded.cost_usd)
        tokens = max(tokens, sum(r.total_tokens for r in kept) + recorded.total_tokens)
    except Exception as exc:  # noqa: BLE001 - the results' share is still right; the end goes on
        logger.warning("Run %s: could not read the spend of the step in flight: %s", context.run_id, exc)
    totals: dict = {"cost_usd": cost, "total_tokens": tokens}
    retired_agents = [a for r in retired for a in r.agent_results]
    if retired_agents:
        totals["retired_llm_calls"] = sum(a.llm_calls for a in retired_agents)
        totals["retired_tool_calls"] = sum(a.tool_calls for a in retired_agents)
    return totals


def _settle_run(
    context: ExecutionContext,
    nodes: list[Node],
    node_outputs: dict[str, NodeResult],
    input_data: dict,
) -> dict | None:
    """What the run leaves behind, worked out once at the very end.

    Writes down the clean-ups it is keeping back -- their own row, which is what survives a
    temper restart and what the deadline is measured against -- and hands back where the run
    stopped for the workflow event, so the page can say what failed and what is being held.
    """
    from temper_ai.runner import holds

    stop = getattr(context, "run_stop", None)
    if not isinstance(stop, RunStop):
        return None
    if not stop.stopped:
        # It finished. Any wait left by an earlier attempt is over: this attempt ran the
        # clean-ups itself, or there were none to run.
        if getattr(context, "run_only", None) is None:
            holds.finish(context.run_id)
        return None

    if stop.kind == "cancelled":
        # Close parked gates without taking an answer or setting the run cancel signal.
        # CAS leaves a concurrently answered gate's result visible and unconsumed; Resume
        # cannot use it because the saved self-stop is restored before any producer runs.
        from temper_ai.observability.recorder import decide_event, gate_events
        from temper_ai.stage.gate import REJECTED
        for event in gate_events(context.run_id):
            if event.get("status") == WAITING:
                decide_event(str(event["id"]), expect=(WAITING,), status=REJECTED,
                             data={"gate_status": REJECTED, "gate_decided_at": utcnow().isoformat()})
        for event_id in stop.unstarted_gate_answers():
            # A blocked start/used-answer write is still preflight. Preserve the approval,
            # but only an admitted producer is allowed to count its answer as consumed.
            decide_event(event_id, expect=(APPROVED,), status=APPROVED,
                         data={"gate_used_at": None})
        # A self-stop admits no further work, including setup release. Those steps have
        # neutral skips, not failure holds: no deadline may start them later or turn this
        # cancelled run failed in a cleanup-only pass. Setup stays for a separate run.
        if getattr(context, "run_only", None) is None:
            holds.finish(context.run_id)
        return stop.as_dict()

    # Anything that never got its turn -- the run was stopped by hand, or thrown out -- is
    # still owed, and the setup it would tear down is still standing.
    if stop.policy.holds:
        for path, undone in _cleanups_owed(nodes, node_outputs, context.node_path or ""):
            stop.hold(path, undone)

    if stop.held and getattr(context, "run_only", None) is None:
        holds.record(
            context.run_id,
            workflow_name=context.workflow_name,
            workspace_path=context.workspace_path,
            inputs=input_data,
            held=[h.as_dict() for h in stop.held],
            deadline=stop.policy.deadline(),
            stopped_at=stop.path,
            stop_reason=stop.reason,
        )
    return stop.as_dict()


def _cleanups_owed(
    nodes: list[Node],
    node_outputs: dict[str, NodeResult],
    prefix: str,
) -> list[tuple[str, list[str]]]:
    """The clean-ups of this run that have not run, by path, with what each undoes.

    Walked over the whole run, stages and all: a run stopped by hand leaves its clean-ups
    wherever they happen to sit, and each of them is still owed.
    """
    owed: list[tuple[str, list[str]]] = []
    for node in nodes:
        path = f"{prefix}.{node.name}" if prefix else node.name
        result = node_outputs.get(node.name)
        done = result is not None and result.status == Status.COMPLETED
        if is_cleanup(node) and not done:
            owed.append((path, undoes(node)))
        children = getattr(node, "child_nodes", None)
        if children and not done:
            inside = (result.node_results if result is not None else None) or {}
            owed.extend(_cleanups_owed(children, inside, path))
    return owed


def _readd_dispatched(
    nodes: list[Node],
    node_map: dict[str, Node],
    batches: list[list[Node]],
    restore: Restore,
    context: ExecutionContext,
    graph_name: str,
) -> tuple[list[Node], dict[str, Node], list[list[Node]], dict[str, NodeResult]]:
    """Put back the agents a dispatcher added to *this* graph during the earlier attempt.

    A dispatched agent belongs to the graph it was added to: one added inside a stage was
    checkpointed as ``build.worker_3``. Putting them all back at the top level -- which is what
    a resume did before -- gave them paths they never had, so their finished results matched
    nothing and every one of them ran again, on every resume; and "re-run from here" after the
    dispatcher lost them altogether, because the graph it re-ran had no idea they existed.

    They go back before anything is claimed, so their results are claimed with everyone else's.
    """
    prefix = f"{context.node_path}." if context.node_path else ""
    deps = {name: list(node.depends_on) for name, node in node_map.items()}
    entries = restore.claim_dispatches(prefix, node_map, restore.reruns(prefix, deps))
    if not entries:
        return nodes, node_map, batches, {}
    loader = getattr(context, "graph_loader", None)
    if loader is None:
        logger.warning("Resume of '%s': %d dispatch(es) cannot be put back -- no graph loader",
                       graph_name, len(entries))
        return nodes, node_map, batches, {}
    from temper_ai.stage.models import NodeConfig

    added: list[Node] = []
    tombstones: dict[str, NodeResult] = {}
    for entry in entries:
        # A dispatch can take a waiting node out as well as add one -- the "replace" shape. A
        # kept dispatcher will not do it again, so its removals are made good here.
        re_added = {d.get("name") for d in entry.get("added_nodes", [])}
        for target in entry.get("removed_targets", []):
            if target not in node_map or target in re_added:
                continue
            node_map.pop(target, None)
            nodes = [n for n in nodes if n.name != target]
            for batch in batches:
                batch[:] = [n for n in batch if n.name != target]
            tombstones[target] = NodeResult(
                status=Status.SKIPPED,
                error=f"removed by dispatch from '{entry.get('dispatcher')}'",
            )
        for node_dict in entry.get("added_nodes", []):
            name = node_dict.get("name")
            if not isinstance(name, str) or name in node_map:
                continue
            try:
                built = loader._resolve_node(NodeConfig.from_dict(node_dict))
            except Exception as exc:  # noqa: BLE001
                logger.error("Resume of '%s': could not build the dispatched node '%s': %s",
                             graph_name, name, exc)
                continue
            node_map[name] = built
            added.append(built)
    if not added:
        return nodes, node_map, batches, tombstones
    nodes = [*nodes, *added]
    # Their own order among themselves is worked out the same way it was when they were
    # dispatched; they hang off nodes that are already in the graph, so they come after it.
    batches = [*batches, *topological_sort(added)]
    logger.info("Resume of '%s': %d agent(s) added last time are back in it: %s",
                graph_name, len(added), ", ".join(n.name for n in added))
    return nodes, node_map, batches, tombstones


def _renamed_from(node_map: dict[str, Node]) -> dict[str, list[str]]:
    """Each renamed node's earlier names (NodeConfig.renamed_from), for what a resume restores."""
    return {
        name: list(olds)
        for name, node in node_map.items()
        if (olds := getattr(getattr(node, "config", None), "renamed_from", None))
    }


def _run_batches(
    batches: list[list[Node]],
    node_map: dict[str, Node],
    input_data: dict,
    node_outputs: dict[str, NodeResult],
    loop_counts: dict[str, int],
    context: ExecutionContext,
    graph_event_id: str,
    retired: list[NodeResult] | None = None,
    loop_feedback: dict[str, NodeResult] | None = None,
) -> None:
    """Iterate through topological batches, handling single-node loops and parallel execution.

    ``loop_feedback`` is what each loop's trigger said when it last sent the graph back; a
    resume hands it over so a pass that was interrupted still reads it.
    """
    batch_idx = 0
    if loop_feedback is None:
        loop_feedback = {}
    cp = context.checkpoint_service  # may be None
    # Checkpoints are keyed by node PATH, not name. A stage's children are checkpointed by
    # this same loop, one level down, with the same service; keyed by bare name, a child called
    # `deploy` was restored on a fork as the top-level `deploy`, which was then "already done"
    # and never ran -- the loop's second gate, skipped without a word. Restore reads only the
    # names of the graph it is restoring (a top-level node has no dot in its path).
    cp_prefix = f"{context.node_path}." if context.node_path else ""

    while batch_idx < len(batches):
        _check_cancelled(context)
        batch = batches[batch_idx]

        # Skip batches where all nodes are already checkpointed (resume/fork path).
        # Events for these nodes are already in the DB — either from the original run
        # (resume) or copied by copy_events_for_fork (fork).
        remaining = [n for n in batch if n.name not in node_outputs]
        if not remaining:
            batch_idx += 1
            continue

        if len(remaining) == 1 and len(batch) == 1:
            node = batch[0]
            result = _execute_single_node(node, input_data, node_outputs, context, graph_event_id, loop_feedback, node_map)
            # Handle dynamic spawning if the node produced _spawn
            node_outputs[node.name] = result
            _record_outcome(node, result, cp_prefix, context, cp)
            _apply_declarative_dispatch(node, result, input_data, node_outputs, node_map, batches, context)
            # A loop that could not read its verdict fails as it stands: no other pass.
            rewind = None if result.metadata.get(NO_LOOP_VERDICT) else _handle_loop(
                node, result, node_outputs, loop_counts, loop_feedback, batches, node_map, cp, input_data, retired,
                checkpoint_prefix=cp_prefix,
            )
            if rewind is not None:
                batch_idx = rewind
                continue
            if result.metadata.get(RAN_OUT_OF_ROUNDS):
                _record_ran_out(node, result, cp_prefix, context, cp)
        else:
            # For parallel batches, only run nodes not already checkpointed
            try:
                results = _execute_parallel_batch(remaining, input_data, node_outputs, context, graph_event_id, loop_feedback, node_map)
            except RunParked as parked:
                # A gate let the worker go: keep what the rest of the batch finished, so the
                # run carries on from there, then go up waiting.
                for node, result in parked.finished:
                    node_outputs[node.name] = result
                    _record_outcome(node, result, cp_prefix, context, cp)
                for node, result in parked.finished:
                    _apply_declarative_dispatch(node, result, input_data, node_outputs, node_map, batches, context)
                raise
            for node, result in results:
                node_outputs[node.name] = result
                _record_outcome(node, result, cp_prefix, context, cp)
            # Dispatch after ALL parallel nodes complete — mutation to batches is
            # safe only once the current batch is done being iterated.
            for node, result in results:
                _apply_declarative_dispatch(node, result, input_data, node_outputs, node_map, batches, context)
        batch_idx += 1


# Set on the result of a clean-up kept back by a failure: it did not run, and the setup it
# would have torn down is still standing for a resume (stage/failure.py).
CLEANUP_HELD = "cleanup_held"


def _record_outcome(
    node: Node,
    result: NodeResult,
    cp_prefix: str,
    context: ExecutionContext,
    cp: Any,
) -> None:
    """Write what became of a node, and tell the run about it.

    Three things can have happened:

    * a clean-up was kept back -- no result to keep, a ``cleanup_held`` note instead, so a
      resume knows the setup is still there and that this step still owes its work;
    * a clean-up ran -- its result is kept like any other, and what it undid is written down,
      so a resume does those steps again before anything that needs what they made;
    * anything else -- its result is kept, and a failure stops the run here.
    """
    path = cp_prefix + node.name
    stop = getattr(context, "run_stop", None)
    undone = undoes(node)
    if result.metadata.get(CLEANUP_HELD):
        if cp is not None:
            cp.save_cleanup_held(path, undone)
        if isinstance(stop, RunStop):
            stop.hold(path, undone)
        return
    _note_self_cancelled(node, result, context)
    if cp is not None:
        cp.save_node_completed(path, result)
    if result.status == Status.FAILED and isinstance(stop, RunStop):
        stop.note_failure(path, result.error)
    elif undone and result.status == Status.COMPLETED:
        # Worth writing down even in a run that goes well: a fork, or "re-run from here",
        # picks up a finished run whose setup has been torn down just the same.
        if cp is not None:
            cp.save_cleanup_ran(path, undone)
        if isinstance(stop, RunStop):
            stop.note_cleanup_ran(path, undone)


def _note_self_cancelled(node: Node, result: NodeResult, context: ExecutionContext) -> None:
    """A node allowed to end its stage cancelled closes the run's one start door.

    Only a self-cancel (signal unset) does this. A hand cancel keeps its existing exception
    path. Called as soon as a result returns, before waiting for any parallel sibling, and
    again when checkpointed; RunStop keeps only the first cancelled path and reason.
    """
    if result.status != Status.CANCELLED:
        return
    if context.cancel_event is not None and context.cancel_event.is_set():
        return
    stop = getattr(context, "run_stop", None)
    if not isinstance(stop, RunStop):
        return
    if getattr(node, "cancelled_ends_stage", False):
        stop.note_cancelled(_step_path(context, node), result.error or result.output)
    if stop.kind == "cancelled":
        # Parents propagate the same marker, never a new stop path. Checkpoint replay opts
        # into this rule only for this marker; older/hand-cancel checkpoints stay unchanged.
        result.metadata["self_cancelled"] = {"path": stop.path, "reason": stop.reason}


def ran_out_reason(count: int, max_loops: int, loop_to: str | None) -> str:
    """Why a step that ran out of rounds failed, in the words the run page shows."""
    back = f" (it still wanted to go back to '{loop_to}')" if loop_to else ""
    return f"ran out of rounds: {count} of {max_loops}{back}"


def _record_ran_out(
    node: Node,
    result: NodeResult,
    cp_prefix: str,
    context: ExecutionContext,
    cp: Any,
) -> None:
    """Store a step that ran out of rounds as failed, with the reason.

    Its run went well and was written down as done (``_record_outcome``) before its loop
    found there was no round left. Written again here: its event turns red with the reason,
    a failed checkpoint follows the completed one (replay drops the step, and a resume runs
    it again with the loop's count kept, so it passes or fails the same way), and the run
    stops here like at any other failure.
    """
    path = cp_prefix + node.name
    event_id = result.metadata.get(NODE_EVENT_ID)
    if event_id:
        try:
            context.event_recorder.update_event(
                event_id,
                status="failed",
                data={"error": result.error, RAN_OUT_OF_ROUNDS: result.metadata.get(RAN_OUT_OF_ROUNDS)},
            )
        except Exception as exc:  # the checkpoint below is what a resume reads; keep going
            logger.warning("Could not mark '%s' failed on its event: %s", path, exc)
    if cp is not None:
        cp.save_node_completed(path, result)
    stop = getattr(context, "run_stop", None)
    if isinstance(stop, RunStop):
        stop.note_failure(path, result.error)


def _held_or_skipped(
    node: Node,
    context: ExecutionContext,
    parent_event_id: str,
    *,
    reconcile: bool = True,
    node_event_id: str | None = None,
) -> NodeResult | None:
    """Why this node does not start at all, or None when it may.

    Reasons about the run as a whole rather than this node's own dependencies:

    * a step ended cancelled by itself. Nothing new starts, not even a report or a
      clean-up. Setup stays standing; there is no automatic failure-release pass.
    * the run has stopped at a failure. Nothing new starts, except the steps that are there
      for exactly this -- ``run_after_failure`` reports and pitches. Steps already running are
      not touched; they finish and keep their results.
    * this is a clean-up (it says what it undoes) and the run is holding its clean-ups, so the
      setup the failed step needs is still there when someone picks the run up again.

    A pass that was told to run only some steps (the held clean-ups, once the hold is over)
    uses the same door: everything else is passed over.
    """
    path = f"{context.node_path}.{node.name}" if context.node_path else node.name
    only = getattr(context, "run_only", None)
    if only is not None and not _wanted(path, only):
        result = NodeResult(
            status=Status.SKIPPED,
            error="not part of this pass: it ran only the clean-ups the run was holding",
        )
        _record_skipped_node(node, context, parent_event_id, result.error or "")
        return result
    stop = getattr(context, "run_stop", None)
    if not isinstance(stop, RunStop) or not stop.stopped:
        return None
    if stop.kind == "cancelled":
        if stop.reopening:
            # Only a real enclosing stage may reconcile its children. Re-enter it even
            # after a prior resume saved its aggregate: every child still hits this door.
            from temper_ai.stage.stage_node import StageNode
            enclosing_stage = str(stop.path).startswith(f"{path}.") and type(node) is StageNode
            if reconcile and enclosing_stage:
                return None
            # Inspect only ended paths; the authoritative snapshot is the fallback, not
            # permission to retry a producer. A diagnostic never replaces the stop/costs.
            cp = context.checkpoint_service
            ended = deepcopy(stop.saved_results.get(path))
            if reconcile and cp is not None and (path == stop.path or ended is not None):
                try:
                    inspected = cp.self_cancelled_result(path)
                except Exception as exc:
                    ended = _cancelled_snapshot_after_inspection_error(path, stop, exc)
                else:
                    if inspected is not None:
                        if ended is not None:
                            inspected.cost_usd, inspected.total_tokens = ended.cost_usd, ended.total_tokens
                        ended = inspected
            from temper_ai.agent import AGENT_TYPES
            from temper_ai.pi_agent.host import PiHost
            from temper_ai.stage.agent_node import AgentNode
            if (reconcile and path == stop.path and type(node) is AgentNode
                    and node.agent_config.get("type") == "pi" and AGENT_TYPES.get("pi") is PiHost):
                # The built-in Pi entry is state-only. Neither throwing inspection nor
                # an ended-record exception may enter _run or overwrite its paid-for state.
                try:
                    reconciled = node.run({}, context)
                except Exception as exc:
                    reconciled = _cancelled_snapshot_after_inspection_error(path, stop, exc)
                if ended is not None:
                    reconciled.cost_usd, reconciled.total_tokens = ended.cost_usd, ended.total_tokens
                    if ended.metadata.get("reconciliation_error"):
                        reconciled.metadata["reconciliation_error"] = ended.metadata["reconciliation_error"]
                reconciled.metadata["self_cancelled"] = {"path": stop.path, "reason": stop.reason}
                _emit_restored_node(node, reconciled, context, parent_event_id)
                return reconciled
            if ended is not None and ended.metadata.get("self_cancelled", {}).get("path") == stop.path:
                _emit_restored_node(node, ended, context, parent_event_id)
                return ended
            if path == stop.path or enclosing_stage:
                ended = NodeResult(status=Status.CANCELLED, error=stop.reason,
                                   metadata={"self_cancelled": {"path": stop.path,
                                                               "reason": stop.reason}})
                _emit_restored_node(node, ended, context, parent_event_id)
                return ended
        reason = f"not started: the run was stopped at '{stop.path}'"
        logger.info("Node '%s' does not start: %s", node.name, reason)
        _record_skipped_node(node, context, parent_event_id, reason, event_id=node_event_id)
        return NodeResult(status=Status.SKIPPED, error=reason)
    policy = context.failure_policy or stop.policy
    if is_cleanup(node) and policy.holds:
        reason = (f"kept back so the run can be picked up where it stopped "
                  f"('{stop.path}' failed); it undoes {', '.join(undoes(node))}")
        logger.info("Clean-up '%s' is held: %s", node.name, reason)
        _record_skipped_node(node, context, parent_event_id, reason, status="held")
        return NodeResult(status=Status.SKIPPED, error=reason, metadata={CLEANUP_HELD: True})
    if is_cleanup(node) or getattr(node.config, "run_after_failure", False):
        # A clean-up in a workflow that cleans up at a failure is exactly the step that has
        # to run now: the whole point of it is to let the setup go. So is a report.
        return None
    reason = f"the run stopped at '{stop.path}', which failed"
    logger.info("Node '%s' does not start: %s", node.name, reason)
    _record_skipped_node(node, context, parent_event_id, reason)
    return NodeResult(status=Status.SKIPPED, error=reason)


def _cancelled_snapshot_after_inspection_error(path: str, stop: RunStop, exc: Exception) -> NodeResult:
    """Keep the original ended state/costs; record inspection failure separately."""
    logger.warning("Could not reconcile stopped node '%s'; retaining its cancellation: %s", path, exc)
    result = deepcopy(stop.saved_results.get(path))
    if result is None:
        # A crash may have saved children but not their enclosing aggregate. Retain the
        # outermost ended records beneath it, never counting both a container and its child.
        descendants = {p[len(path) + 1:]: deepcopy(r) for p, r in stop.saved_results.items()
                       if p.startswith(f"{path}.")}
        kept = {p: r for p, r in descendants.items()
                if not any(p.startswith(f"{parent}.") for parent in descendants)}
        result = NodeResult(status=Status.CANCELLED, error=stop.reason, node_results=kept,
            cost_usd=sum(r.cost_usd for r in kept.values()),
            total_tokens=sum(r.total_tokens for r in kept.values()),
            metadata={"self_cancelled": {"path": stop.path, "reason": stop.reason}})
    result.metadata["reconciliation_error"] = str(exc)
    return result


def _runs_after_a_failure(node: Node, context: ExecutionContext) -> bool:
    """Whether this node still runs when something it depends on failed.

    Two kinds do: a step marked ``run_after_failure`` (a report, a pitch), and a clean-up in a
    run that cleans up at a failure -- letting go of the setup is what it is for. A clean-up in
    a run that *holds* its clean-ups does not: it is kept back for the resume, which
    `_held_or_skipped` has already decided by the time this is asked.
    """
    if getattr(node.config, "run_after_failure", False):
        return True
    if not is_cleanup(node):
        return False
    stop = getattr(context, "run_stop", None)
    policy = context.failure_policy or (stop.policy if isinstance(stop, RunStop) else None)
    return bool(policy and not policy.holds)


def _wanted(path: str, only: Any) -> bool:
    """Whether a pass told to run only certain paths wants this node: it is one of them, or a
    stage that holds one of them."""
    return any(p == path or p.startswith(f"{path}.") for p in only)


def _resume_state(context: ExecutionContext) -> dict[str, Any]:
    """Read authoritative resume state before scheduling; absence is not a read fault.

    An unavailable/malformed reader must refuse the attempt, not erase a durable stop
    and start work in a changed topology. No checkpoint service still means no state.
    """
    admitted = getattr(context, "resume_authority", None)
    if isinstance(admitted, dict):
        # Same trusted snapshot as admission, not a later read turned into empty history.
        # Live claims, waits, answers, cancellation and allowance rows are still read live.
        return deepcopy(admitted)
    read = getattr(context.checkpoint_service, "resume_state", None)
    if read is None:
        return {}
    state = read()
    if not isinstance(state, dict):
        raise WorkflowError("Checkpoint resume state could not be read; no work started")
    return state


def _build_final_result(
    nodes: list[Node],
    node_outputs: dict[str, NodeResult],
    input_data: dict,
    start: float,
    graph_event_id: str,
    context: ExecutionContext,
    workflow_outputs: dict[str, str] | None = None,
    is_workflow: bool = False,
    retired: list[NodeResult] | None = None,
    stopped: dict | None = None,
) -> NodeResult:
    """Assemble the final NodeResult once every batch has run.

    ``stopped``: where the run stopped and what it is holding, when a failure stopped it
    (stage/failure.py). It goes on the workflow event, which is what the page reads.

    A *workflow* whose nodes include a failure is reported as ``failed``
    (with the failed node names in the event), not ``completed``: before
    this, any run in which a node blew up and its dependants were skipped
    still showed a green tick and exited 0, which hid real breakage in
    ~5% of production runs. Stages keep their tolerant semantics — a
    parallel stage with one failed lane still completes so a leader can
    synthesise the rest — so the check is applied at the workflow level
    only, over the whole (nested) result tree.
    """
    # Rebuild from final outputs to avoid duplicates from loop reruns
    all_agent_results = [
        r for node in nodes
        for r in (node_outputs[node.name].agent_results if node.name in node_outputs else [])
    ]

    duration = time.monotonic() - start
    # Every attempt that ran, including the ones a loop rewind threw away.
    # Summing node_outputs alone reports only each node's surviving attempt
    # and silently under-reports the run's real spend.
    accounted = [*node_outputs.values(), *(retired or [])]
    total_cost = sum(r.cost_usd for r in accounted)
    total_tokens = sum(r.total_tokens for r in accounted)
    last_output = _get_final_output(nodes, node_outputs)

    # Resolve workflow-level outputs from node results
    resolved_outputs = None
    if workflow_outputs:
        resolved_outputs = {}
        for key, source in workflow_outputs.items():
            try:
                resolved_outputs[key] = _resolve_single_input(
                    "__workflow__", key, source, input_data, node_outputs,
                )
            except Exception:
                resolved_outputs[key] = None

    event_data: dict = {
        "cost_usd": total_cost,
        "total_tokens": total_tokens,
        "duration_seconds": duration,
    }

    # Call counts are derived by the API from the node tree, which keeps only
    # each node's surviving attempt. Publish just the discarded attempts' share
    # so the API can add it to what it already counts, rather than replacing a
    # figure that is sourced differently (events, not AgentResult).
    retired_agents = [a for r in (retired or []) for a in r.agent_results]
    if retired_agents:
        event_data["retired_llm_calls"] = sum(a.llm_calls for a in retired_agents)
        event_data["retired_tool_calls"] = sum(a.tool_calls for a in retired_agents)
    if resolved_outputs:
        event_data["workflow_output"] = resolved_outputs
    if stopped:
        event_data["stopped"] = stopped

    held_back: list[NodeResult] = []
    if is_workflow:
        failed_nodes = _failed_node_names(node_outputs)
        # A step that ended cancelled by itself, with the run's own cancel signal unset (a
        # cancel that is set never gets here: the run ends "Workflow cancelled by user"): an
        # owner's stop answer to a Pi team, or a Pi conversation another attempt cancelled.
        # Nothing failed, so the run ends cancelled with that step's own reason, never
        # "completed" (M3 E18). Only Pi nodes end cancelled this way today.
        held_back = [r for r in node_outputs.values() if r.status == Status.CANCELLED]
    else:
        # Stages stay tolerant, except where a node's result is its stage's
        # (``Node.fails_stage``): such a stage completes only when that node completed. It
        # fails when the node failed or never ran, and is cancelled or skipped with it when
        # the run was cancelled, or stopped at a failure elsewhere, before the node could
        # finish -- never "completed" over work that was not done.
        own = [n.name for n in nodes if getattr(n, "fails_stage", False)]
        failed_nodes = [name for name in own if name not in node_outputs
                        or node_outputs[name].status == Status.FAILED]
        held_back = [node_outputs[name] for name in own if name in node_outputs
                     and node_outputs[name].status in (Status.CANCELLED, Status.SKIPPED)]
        # A step that may end cancelled by itself (a Pi step whose conversation another
        # attempt ended, ``cancelled_ends_stage``) ends its stage cancelled with its reason,
        # so the run ends cancelled too (M3 E18); its failure stays tolerant as before.
        held_back += [node_outputs[n.name] for n in nodes
                      if getattr(n, "cancelled_ends_stage", False) and n.name not in own
                      and n.name in node_outputs
                      and node_outputs[n.name].status == Status.CANCELLED]
    stop = getattr(context, "run_stop", None)
    if (not is_workflow and isinstance(stop, RunStop) and stop.kind == "cancelled"
            and stop.reopening and str(stop.path).startswith(f"{context.node_path}.")):
        # An ended source's container reconciles as cancelled even if revised child
        # types are tolerant. Never save it completed and lose its child skips on Resume.
        stopped = stop.as_dict()
    self_cancelled = bool(stopped and stopped.get("kind") == "cancelled")
    if self_cancelled:
        # An already-running sibling may have failed. Its own record stays red, but it
        # cannot undo the owner's stop or replace that neutral run-list sentence (E18).
        failed_nodes = []
    if is_workflow and not self_cancelled and not failed_nodes and stopped and stopped.get("path"):
        # The run stopped at a failure, but the failed attempt is no longer among the
        # results: its loop sent it round again, which retired it, and then nothing more
        # started. Nothing after it ran, so the run failed there -- not "completed".
        failed_nodes = [str(stopped["path"])]
    final_status = Status.FAILED if failed_nodes else Status.COMPLETED
    if is_workflow and getattr(context, "run_only", None) is not None:
        # A pass that ran only the held clean-ups, once the wait was over. It says nothing
        # about whether the work succeeded: the run failed, and it still shows as failed, so
        # whatever reads a run's outcome -- the EPD driver, the dashboard -- sees what it saw.
        final_status = Status.FAILED
    error: str | None = None
    if held_back and final_status != Status.FAILED:
        # The run was cancelled, or stopped before the node started: the stage says so, with
        # the node's own reason (a skip's reason ends "... failed", so whatever depends on the
        # stage is skipped for that failure too, never run as after a condition's skip).
        cancelled = [r for r in held_back if r.status == Status.CANCELLED]
        final_status = Status.CANCELLED if cancelled else Status.SKIPPED
        error = (cancelled or held_back)[0].error or final_status.value
        event_data["error"] = error
    if self_cancelled:
        final_status = Status.CANCELLED
        error = str((stopped or {}).get("reason") or "the step was stopped")
        event_data["error"] = error
    if failed_nodes:
        error = f"{len(failed_nodes)} node(s) failed: {', '.join(failed_nodes)}"
        if not is_workflow:
            # Say why, as the failed node said it: the stage row is where it is read.
            why = [f"{name}: {node_outputs[name].error}" if name in node_outputs
                   else f"{name}: it never ran" for name in failed_nodes
                   if name not in node_outputs or node_outputs[name].error]
            if why:
                error = f"{error} ({'; '.join(why)})"
        event_data["error"] = error
        event_data["failed_nodes"] = failed_nodes

    context.event_recorder.update_event(
        graph_event_id,
        status=final_status.value,
        data=event_data,
    )

    # Use workflow outputs as structured_output if available, otherwise fall back to last node
    final_structured = resolved_outputs if resolved_outputs else (
        last_output.structured_output if last_output else None
    )

    return NodeResult(
        status=final_status,
        error=error,
        output=last_output.output if last_output else "",
        structured_output=final_structured,
        agent_results=all_agent_results,
        node_results=node_outputs,
        cost_usd=total_cost,
        total_tokens=total_tokens,
        duration_seconds=duration,
    )

def _emit_restored_node(node: Node, result: NodeResult, context: ExecutionContext, graph_event_id: str) -> None:
    """Emit events for a node restored from checkpoint so the frontend shows prior state.

    Uses update_event on the started event (same pattern as live execution)
    so the data service correctly resolves status from the event's own status field.
    """
    recorder = context.event_recorder
    status_str = result.status.value if result.status != Status.COMPLETED else "completed"

    # Stage event — record started then immediately update to final status
    node_event_id = recorder.record(
        EventType.STAGE_STARTED,
        parent_id=graph_event_id,
        execution_id=context.run_id,
        status=status_str,
        data={
            **_build_node_event_data(node),
            "restored_from_checkpoint": True,
            "duration_seconds": result.duration_seconds,
            "cost_usd": result.cost_usd,
            "total_tokens": result.total_tokens,
            "output": (result.output or "")[:5000],
            "structured_output": result.structured_output,
            "error": result.error,
            **({"reconciliation_error": result.metadata["reconciliation_error"]}
               if result.metadata.get("reconciliation_error") else {}),
        },
    )

    # Emit agent events so the frontend shows agent cards.
    # For StageNodes use child node names; for AgentNodes use node name.
    from temper_ai.stage.stage_node import StageNode
    if isinstance(node, StageNode) and node.child_nodes:
        agent_names = [cn.name for cn in node.child_nodes]
    else:
        agent_names = [node.name]

    for agent_name in agent_names:
        recorder.record(
            EventType.AGENT_STARTED,
            parent_id=node_event_id,
            execution_id=context.run_id,
            status=status_str,
            data={
                "agent_name": agent_name,
                "node_path": node.name,
                "restored_from_checkpoint": True,
                "output": (result.output or "")[:5000],
                "structured_output": result.structured_output,
                "duration_seconds": result.duration_seconds,
                "total_tokens": result.total_tokens,
                "cost_usd": result.cost_usd,
            },
        )


def _execute_single_node(
    node: Node,
    input_data: dict,
    node_outputs: dict[str, NodeResult],
    context: ExecutionContext,
    parent_event_id: str,
    loop_feedback: dict[str, NodeResult] | None = None,
    node_map: dict[str, Node] | None = None,
) -> NodeResult:
    """Execute one node with condition checking and input resolution."""
    stopped = _held_or_skipped(node, context, parent_event_id)
    if stopped is not None:
        return stopped
    stop = getattr(context, "run_stop", None)
    from temper_ai.stage.stage_node import StageNode
    if (isinstance(stop, RunStop) and stop.kind == "cancelled" and stop.reopening
            and str(stop.path).startswith(f"{_step_path(context, node)}.") and type(node) is StageNode):
        # Reconcile only children, bypassing the enclosing stage's revised preflight.
        # In particular no new input/condition/gate can run on the state-only exception.
        event_id = context.event_recorder.record(EventType.STAGE_STARTED,
            data={**_build_node_event_data(node), "restored_from_checkpoint": True},
            parent_id=parent_event_id, execution_id=context.run_id, status=Status.CANCELLED.value)
        result = _run_node_with_events(node, {}, context, event_id, reconcile=True)
        result.metadata[NODE_EVENT_ID] = event_id
        return result
    upstream_failure = _check_dependency_failures(node, node_outputs)
    if upstream_failure is not None and not _runs_after_a_failure(node, context):
        logger.warning("Node '%s' skipped — %s", node.name, upstream_failure.error)
        _record_skipped_node(node, context, parent_event_id, upstream_failure.error or "dependency failed")
        return upstream_failure
    if upstream_failure is not None:
        logger.info("Node '%s' runs after a failure upstream: %s", node.name, upstream_failure.error)

    if node.condition:
        try:
            if not evaluate_condition(node.condition, node_outputs):
                logger.info("Node '%s' skipped — condition not met", node.name)
                if upstream_failure is not None:
                    # It would have run to deal with the failure, and its own
                    # condition said no: the failure goes on down, so a node
                    # after it is not run as if nothing had gone wrong.
                    _record_skipped_node(node, context, parent_event_id,
                                         f"condition not met; {upstream_failure.error}")
                    return upstream_failure
                result = NodeResult(status=Status.SKIPPED)
                _record_skipped_node(node, context, parent_event_id, "condition not met")
                return result
        except Exception as exc:
            logger.warning("Condition evaluation failed for '%s': %s", node.name, exc)
            if upstream_failure is not None:
                _record_skipped_node(node, context, parent_event_id, f"{exc}; {upstream_failure.error}")
                return upstream_failure
            result = NodeResult(status=Status.SKIPPED, error=str(exc))
            _record_skipped_node(node, context, parent_event_id, str(exc))
            return result

    unresolved: list[str] = []
    resolved = _resolve_inputs(node, input_data, node_outputs, loop_feedback, unresolved, node_map)
    resolved = _inject_strategy_context(node, resolved, node_outputs)
    if unresolved:
        # Recorded on the node so it reaches the API and the dashboard: a
        # log line is invisible to whoever is looking at the run.
        logger.warning("Node '%s' has unresolved input_map entries: %s", node.name, unresolved)

    # A sibling may have stopped during input resolution. Recheck the same door before
    # starting any node or opening an approval; failure behaviour stays unchanged.
    stop = getattr(context, "run_stop", None)
    if isinstance(stop, RunStop) and stop.kind == "cancelled":
        stopped = _held_or_skipped(node, context, parent_event_id)
        if stopped is not None:
            return stopped
    # Gate: pause and wait for human approval before executing. Whatever
    # the human said with the approval reaches the node as ``gate``.
    if node.config.gate:
        response = _wait_for_gate(node, context, parent_event_id, node_outputs)
        resolved = {**resolved, "gate": response or dict(EMPTY_RESPONSE)}
        if isinstance(stop, RunStop) and stop.kind == "cancelled":
            stopped = _held_or_skipped(node, context, parent_event_id)
            if stopped is not None:
                return stopped

    node_event_id = context.event_recorder.record(
        EventType.STAGE_STARTED,
        data={
            **_build_node_event_data(node),
            **({"unresolved_inputs": unresolved} if unresolved else {}),
        },
        parent_id=parent_event_id,
        execution_id=context.run_id,
        status=Status.PENDING.value,
    )

    try:
        result = _run_node_with_events(node, resolved, context, node_event_id)
    except RunParked as parked:
        if node.config.gate:
            # Its gate passed, then a wait inside the step let the worker go (one the step
            # asked itself, or the approval of a step inside a stage): the gate's answer
            # stays this go's answer, so carrying the run on does not ask it again. The
            # step's own gate letting go never gets here: that happens before the step runs.
            _keep_gate_answer(context, node, parked)
        raise
    result.metadata[NODE_EVENT_ID] = node_event_id
    no_verdict = _loop_verdict_missing(node, result, {**node_outputs, node.name: result})
    if no_verdict:
        logger.warning("Node '%s' fails: %s", node.name, no_verdict)
        result.status = Status.FAILED
        result.error = no_verdict
        result.metadata[NO_LOOP_VERDICT] = True
        context.event_recorder.update_event(node_event_id, status="failed", data={"error": no_verdict})
    no_file = _required_file_missing(node, result, input_data, {**node_outputs, node.name: result}, node_map)
    if no_file:
        logger.warning("Node '%s' fails: %s", node.name, no_file)
        result.status = Status.FAILED
        result.error = no_file
        context.event_recorder.update_event(node_event_id, status="failed", data={"error": no_file})
    if result.status == Status.COMPLETED:
        # The answers the step was given at its own waits are spent: a later go asks afresh.
        spend_answers(context, _step_path(context, node))
    elif result.status == Status.FAILED:
        # This go of the step is over; its answers stay unspent for the go that carries it on.
        forget_step(context, _step_path(context, node))
    return result


def _required_file_missing(
    node: Node,
    result: NodeResult,
    input_data: dict,
    node_outputs: dict[str, NodeResult],
    node_map: dict[str, Node] | None = None,
) -> str | None:
    """Why a completed node fails for a file it had to write and did not; None if it wrote them.

    ``required_files`` lists them: each entry is a source, resolved like an input_map
    entry (``input.tasks_path``, ``plan.structured.plan_path``), or ``{path: <source>,
    when: <condition>}`` for a file owed only in some outcomes (a plan owes its tasks
    only when it did not stop as BLOCKED). b010 on 2026-09-22: the tasks stage completed
    without writing tasks.json, its one output, and the run went on as if it had.
    """
    wanted = getattr(node.config, "required_files", None)
    if not wanted or result.status != Status.COMPLETED:
        return None
    for entry in wanted:
        source, when = (entry.get("path"), entry.get("when")) if isinstance(entry, dict) else (entry, None)
        if when:
            try:
                if not evaluate_condition(when, node_outputs):
                    continue
            except Exception as exc:
                return f"it cannot tell whether it owes {source}: {exc}"
        path = _resolve_single_input(node.name, "required_files", source, input_data, node_outputs,
                                     node_map=node_map)
        if not isinstance(path, str) or not path.strip():
            return f"it completed without saying where {source} is"
        if not os.path.isfile(path.strip()):
            return f"it completed without writing {path.strip()} ({source})"
    return None


# Set on a node that failed because its loop could not read its verdict (see
# _loop_verdict_missing): the loop does not go round again for it.
NO_LOOP_VERDICT = "no_loop_verdict"

# In-memory only (metadata is never stored): the id of the event a node's run was recorded
# under, so a verdict reached after the run -- running out of rounds -- can be written onto it.
NODE_EVENT_ID = "node_event_id"

# Set on a node that completed but ran out of rounds with its loop still asking for another,
# under ``on_max_loops: fail``: {"count", "max", "loop_to"}. _record_ran_out stores the failure.
RAN_OUT_OF_ROUNDS = "ran_out_of_rounds"


# The step a failure started from, at the end of every skip reason this module
# writes for a failure: "Dependency 'plan' failed", "Dependency 'gate' was
# skipped because 'plan' failed".
_ROOT_FAILURE = re.compile(r"'([^']+)' failed$")


def _skipped_for_failure(result: NodeResult) -> bool:
    """A skip caused by a failure upstream, as against one a condition chose.

    Told apart by the reason, the one part of a skip a checkpoint keeps: every
    reason this module writes for a failure ends "... failed", however far down
    the skip is. It used not to past the second step ("Dependency 'b' was
    skipped"), so the third step after a failure took the skip for a
    condition's and ran, on inputs that were never made.
    """
    return result.status == Status.SKIPPED and "failed" in (result.error or "")


def _failure_skip(dep_name: str, dep_result: NodeResult) -> NodeResult:
    """The skip for a node whose dependency failed, or was skipped for a failure."""
    if dep_result.status == Status.FAILED:
        return NodeResult(status=Status.SKIPPED, error=f"Dependency '{dep_name}' failed")
    match = _ROOT_FAILURE.search(dep_result.error or "")
    root = f"'{match.group(1)}'" if match else "a step upstream"
    return NodeResult(status=Status.SKIPPED,
                      error=f"Dependency '{dep_name}' was skipped because {root} failed")


def _check_dependency_failures(
    node: Node,
    node_outputs: dict[str, NodeResult],
) -> NodeResult | None:
    """The SKIPPED result a failure upstream calls for, or None when nothing upstream failed.

    A failure is carried all the way down: a node is skipped when a dependency
    failed, or was itself skipped because of a failure, however many steps up.
    A dependency skipped by its own condition is not a failure, and the node runs.

    The caller decides what to do with it: a node with ``run_after_failure``
    runs anyway (it is there to report or clean up after what happened), and
    passes the failure on down only if its own condition then skips it.
    """
    for dep_name in node.depends_on:
        dep_result = node_outputs.get(dep_name)
        if dep_result is None:
            continue
        if dep_result.status == Status.FAILED or _skipped_for_failure(dep_result):
            return _failure_skip(dep_name, dep_result)
        if dep_result.status == Status.SKIPPED:
            logger.info("Node '%s' — dependency '%s' was conditionally skipped, proceeding", node.name, dep_name)
    return None


def _record_skipped_node(
    node: Node,
    context: ExecutionContext,
    parent_event_id: str,
    reason: str,
    status: str = "skipped",
    *,
    event_id: str | None = None,
) -> None:
    """Record a skip, or convert a provisional preflight event without a second record."""
    if event_id is not None:
        context.event_recorder.update_event(event_id, status=status, data={"skip_reason": reason})
        return
    context.event_recorder.record(
        EventType.STAGE_STARTED,
        data={**_build_node_event_data(node), "skip_reason": reason},
        parent_id=parent_event_id,
        execution_id=context.run_id,
        status=status,
    )


def _build_node_event_data(node: Node) -> dict[str, Any]:
    """Build the event data dict for a node-start event."""
    data: dict[str, Any] = {
        "name": node.name,
        "type": node.config.type,
        "depends_on": node.config.depends_on or [],
        "strategy": node.config.strategy,
    }
    if node.config.loop_to:
        data["loop_to"] = node.config.loop_to
        data["max_loops"] = node.config.max_loops
    return data


def _run_node_with_events(
    node: Node,
    resolved: dict,
    context: ExecutionContext,
    node_event_id: str,
    *,
    reconcile: bool = False,
) -> NodeResult:
    """Run a node after synchronized admission, recording outcomes around it.

    Start recording/context creation happen BEFORE admission; a self-stop winning
    there converts the provisional event to the sole neutral skip. Timeout workers
    use the same entry, rather than receiving permission before being scheduled.
    """
    # The running update is provisional too: it can block, so admission follows it.
    context.event_recorder.update_event(node_event_id, status=Status.RUNNING.value)
    from dataclasses import replace as dc_replace
    node_context = dc_replace(
        context,
        parent_event_id=node_event_id,
        skip_policies=node.config.skip_policies,
        step_path=_step_path(context, node),
    )

    entered = False
    stop = getattr(context, "run_stop", None)
    def enter_producer() -> NodeResult:
        nonlocal entered
        if not reconcile and isinstance(stop, RunStop) and not stop.admit_start(_step_path(context, node)):
            skipped = _held_or_skipped(node, context, node_event_id,
                                      reconcile=False, node_event_id=node_event_id)
            assert skipped is not None  # the synchronized admission lost to a self-stop
            return skipped
        entered = True
        return node.run(resolved, node_context)

    timeout = node.config.timeout_seconds
    start = time.monotonic()
    try:
        if timeout:
            result = _run_with_timeout(node, enter_producer, timeout)
        else:
            result = enter_producer()
        duration = time.monotonic() - start
        result.duration_seconds = duration
        _note_self_cancelled(node, result, context)
        context.event_recorder.update_event(
            node_event_id,
            status=result.status.value,
            data={"cost_usd": result.cost_usd, "total_tokens": result.total_tokens, "duration_seconds": duration},
        )
        return result

    except RunParked:
        # A wait in this step (stage/step_waits.py), or a gate inside this stage, let the
        # worker go: the step is waiting, not failed.
        context.event_recorder.update_event(
            node_event_id, status="waiting", data={"duration_seconds": time.monotonic() - start},
        )
        raise

    except ReplacedByLaterAttempt as replaced:
        # A later attempt of this run took the step over: not a failure of the step. It
        # stands down with its attempt, written down as that attempt's only (SW-84).
        _note_replaced(replaced, context, node_event_id, start)
        raise

    except Exception as exc:
        duration = time.monotonic() - start
        if reconcile and isinstance(stop, RunStop):
            result = _cancelled_snapshot_after_inspection_error(_step_path(context, node), stop, exc)
            context.event_recorder.update_event(node_event_id, status=result.status.value,
                data={"error": result.error, "cost_usd": result.cost_usd,
                      "total_tokens": result.total_tokens, "reconciliation_error": str(exc)})
            return result
        context.event_recorder.update_event(
            node_event_id,
            status="failed",
            data={"error": str(exc), "duration_seconds": duration},
        )
        return NodeResult(status=Status.FAILED, error=str(exc), duration_seconds=duration)

    finally:
        if entered:
            _release_node_tools(node, context)


def _release_node_tools(node: Node, context: ExecutionContext) -> None:
    """Free per-caller tool state when a node ends — an MCP session, its browser.

    Here rather than in each node class because this is where a node's run
    finishes whatever kind it is, success or failure. The key is the one the
    node's own tool calls were bound to (tools/executor.caller_key), so this ends
    that agent's sessions and nobody else's: a sibling running concurrently keeps
    its own. Failure to release is logged, never raised — the node's result does
    not depend on the cleanup.
    """
    from temper_ai.tools.executor import caller_key

    release = getattr(getattr(context, "tool_executor", None), "release_caller", None)
    if release is None:
        return
    path = f"{context.node_path}.{node.name}" if context.node_path else node.name
    try:
        release(caller_key({"execution_id": context.run_id, "node_path": path}))
    except Exception as exc:  # noqa: BLE001 — cleanup must not fail a finished node
        logger.warning("Node '%s': releasing per-caller tool state failed: %s", node.name, exc)


def _run_with_timeout(node: Node, enter_producer: Callable[[], NodeResult], timeout: int) -> NodeResult:
    """Run the synchronized producer entry in its timeout worker, not in its submitter."""
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(enter_producer)
        try:
            return future.result(timeout=timeout)
        except TimeoutError:
            logger.warning("Node '%s' timed out after %ds", node.name, timeout)
            return NodeResult(
                status=Status.FAILED,
                error=f"Node timed out after {timeout}s",
                duration_seconds=float(timeout),
            )


def _execute_parallel_batch(
    batch: list[Node],
    input_data: dict,
    node_outputs: dict[str, NodeResult],
    context: ExecutionContext,
    parent_event_id: str,
    loop_feedback: dict[str, NodeResult] | None = None,
    node_map: dict[str, Node] | None = None,
) -> list[tuple[Node, NodeResult]]:
    """Execute a batch of independent nodes concurrently."""
    results = []

    with ThreadPoolExecutor(max_workers=len(batch)) as pool:
        future_to_node = {
            pool.submit(
                _execute_single_node, node, input_data, node_outputs,
                context, parent_event_id, loop_feedback, node_map
            ): node
            for node in batch
        }
        parked: RunParked | None = None
        replaced: ReplacedByLaterAttempt | None = None
        for future in as_completed(future_to_node):
            node = future_to_node[future]
            try:
                result = future.result()
            except ReplacedByLaterAttempt as exc:
                # A later attempt of this run took a step here over: once the rest of the
                # batch is done this attempt stands down, before any park (SW-84).
                replaced = replaced or exc
                continue
            except RunParked as exc:
                # A gate here let the worker go. The others in the batch finish first, and go
                # up with it so they are kept; a second gate that parked goes up with it too
                # (an answer at either carries the run on, and the resume waits on the other).
                if parked is None:
                    parked = exc
                else:
                    parked.also.extend([{k: v for k, v in exc.as_dict().items() if k != "also"},
                                        *exc.also])
                continue
            except Exception as exc:
                result = NodeResult(status=Status.FAILED, error=str(exc))
            results.append((node, result))

    if replaced is not None:
        raise replaced
    if parked is not None:
        parked.finished = results
        raise parked
    return results


def _apply_declarative_dispatch(
    node: Node,
    result: NodeResult,
    input_data: dict,
    node_outputs: dict[str, NodeResult],
    node_map: dict[str, Node],
    batches: list[list[Node]],
    context: ExecutionContext,
) -> None:
    """If the node's agent config has a `dispatch:` block, render it and
    apply the resulting ops to the running DAG.

    Tier 1 scope:
      - op=add: build Node instances from rendered dicts, topologically sort
        the new mini-DAG, append batches to `batches` list. The main executor
        loop iterates len(batches) dynamically, so new batches are picked up
        in later iterations.
      - op=remove: mark the target pending node as SKIPPED in node_outputs
        so subsequent batches skip it and downstream cascade via unresolved
        input_map refs (standard engine behavior).

    Silent-no-op when:
      - The node is not an AgentNode (stage-level dispatch is out of v1 scope)
      - The agent config has no `dispatch:` block (common case)
      - The node FAILED (don't dispatch on failure — the agent's output is
        unreliable)

    Errors in the dispatch block bubble up as exceptions and fail the run,
    matching how validation errors surface elsewhere.
    """
    # Imports inside function to avoid circular deps with loader/agent_node
    from temper_ai.stage.agent_node import AgentNode
    from temper_ai.stage.dispatch import DispatchRenderError, render_dispatch
    from temper_ai.stage.dispatch_limits import (
        DispatchCapExceeded,
        DispatchLimits,
        DispatchRunState,
        fingerprint_node,
    )

    if not isinstance(node, AgentNode):
        return
    if result.status == Status.FAILED:
        return
    agent_config = getattr(node, "agent_config", None) or {}

    # Tier 2 (tool-call) dispatch leaves ops on dispatch_state.pending_ops
    # keyed by node_path. Tier 1 (declarative) lives in agent_config["dispatch"].
    # Early-return only if BOTH sources are empty — otherwise we need to run
    # the full path so cap enforcement + graph_loader wiring both execute.
    has_declarative = bool(agent_config.get("dispatch"))
    existing_state = getattr(context, "dispatch_state", None)
    has_tool_call_ops = _has_pending_tool_call_ops(existing_state, context, node)
    if not has_declarative and not has_tool_call_ops:
        return
    loader = getattr(context, "graph_loader", None)
    if loader is None:
        logger.warning(
            "Agent '%s' declared dispatch but ExecutionContext has no graph_loader — "
            "dispatch skipped. Wire context.graph_loader in routes.py / CLI.",
            node.name,
        )
        return

    # Safety caps — lazily seed limits and run-state on first dispatch
    limits: DispatchLimits = getattr(context, "dispatch_limits", None) or DispatchLimits()
    state: DispatchRunState = getattr(context, "dispatch_state", None) or DispatchRunState()
    context.dispatch_limits = limits
    context.dispatch_state = state

    # Gather the agent's produced data to feed the Jinja scope
    agent_result = result.agent_results[0] if result.agent_results else None
    agent_output = agent_result.output if agent_result else (result.output or "")
    agent_structured = (
        agent_result.structured_output if agent_result else result.structured_output
    )

    # Dispatch Jinja scope `input.*` must reflect the node's own resolved
    # input_map (what it actually ran with), not the batch-level workflow
    # input_data. Re-resolve here so dispatch can reference values wired
    # via input_map (e.g. step_uid passed from an upstream capturer).
    dispatch_input_data = _resolve_inputs(node, input_data, node_outputs)

    dispatch_notes: list[str] = []
    try:
        ops = render_dispatch(
            agent_config,
            agent_output=agent_output,
            agent_structured=agent_structured,
            agent_input_data=dispatch_input_data,
            notes=dispatch_notes,
        )
    except DispatchRenderError as exc:
        logger.error("Dispatch render failed for '%s': %s", node.name, exc)
        raise

    # Tier 2: drain any tool-call ops (AddNode / RemoveNode) accumulated
    # during this agent's run. They merge with tier-1 declarative ops and
    # go through the same cap enforcement + validation path below.
    tool_call_ops = _drain_tool_call_ops(state, context, node)
    ops = list(ops) + tool_call_ops

    if dispatch_notes and context.event_recorder:
        # Recorded so the run says what did not happen; the dashboard reads
        # this the same way it reads unresolved inputs.
        logger.warning("Dispatch from '%s' produced nothing: %s", node.name, dispatch_notes)
        context.event_recorder.record(
            EventType.DISPATCH_APPLIED,
            data={"dispatcher": node.name, "added": [], "removed": [],
                  "skipped_reasons": dispatch_notes},
            parent_id=context.parent_event_id,
            execution_id=context.run_id,
            status="skipped",
        )

    if not ops:
        return

    new_nodes: list[Node] = []
    added_node_dicts: list[dict[str, Any]] = []
    removed_targets: list[str] = []
    dispatcher_depth = state.depths.get(node.name, 0)

    try:
        # Per-dispatch fan-out cap — count ADDED nodes across the ops batch
        total_added = sum(len(op.all_added_nodes()) for op in ops)
        if total_added > limits.max_children_per_dispatch:
            raise DispatchCapExceeded(
                f"Dispatch from '{node.name}' emitted {total_added} add-node(s), "
                f"exceeding max_children_per_dispatch={limits.max_children_per_dispatch}"
            )

        # Ensure dispatcher has a fingerprint recorded so cycle walks work even
        # when the dispatcher is an original workflow node.
        if node.name not in state.fingerprints:
            state.fingerprints[node.name] = fingerprint_node(
                agent_config.get("name", node.name),
                input_data,
            )

        # Two-pass: figure out which removed names will be re-added
        # ("replace" pattern) so we can tombstone non-replaced removes while
        # freeing replaced slots completely. This prevents the batches loop
        # from running either the original-being-replaced OR the replacement
        # by making the name's status unambiguous per dispatch.
        add_names: set[str] = set()
        for op in ops:
            if op.op == "add":
                for nd in op.all_added_nodes():
                    name = nd.get("name")
                    if isinstance(name, str) and name:
                        add_names.add(name)

        for op in ops:
            if op.op == "remove":
                target = op.target or ""
                if target in node_outputs and node_outputs[target].status != Status.PENDING:
                    # Already ran (completed/failed) or already tombstoned
                    continue
                # Clear from node_map + batches so the original doesn't run.
                # Nodes are only equal if same instance — filter by name.
                node_map.pop(target, None)
                for batch in batches:
                    batch[:] = [n for n in batch if n.name != target]
                if target in add_names:
                    # Replace path — a subsequent add will take this slot.
                    # Clear any stale output (shouldn't be there, defensive)
                    # so add's _enforce_caps_and_build sees a clean slot.
                    node_outputs.pop(target, None)
                else:
                    # Standalone remove — tombstone so downstream that resolves
                    # `target.output` sees SKIPPED.
                    node_outputs[target] = NodeResult(
                        status=Status.SKIPPED,
                        error=f"removed by dispatch from '{node.name}'",
                    )
                removed_targets.append(target)
                logger.info("Dispatch from '%s' removed pending node %r", node.name, target)
            elif op.op == "add":
                for node_dict in op.all_added_nodes():
                    _enforce_caps_and_build(
                        op_dict=node_dict,
                        dispatcher_name=node.name,
                        dispatcher_depth=dispatcher_depth,
                        loader=loader,
                        limits=limits,
                        state=state,
                        node_map=node_map,
                        node_outputs=node_outputs,
                        new_nodes=new_nodes,
                    )
                    added_node_dicts.append(node_dict)
    except DispatchCapExceeded as exc:
        # Record the cap breach before letting it propagate — the dispatcher's
        # node will fail, but the timeline needs to show WHY.
        recorder = getattr(context, "event_recorder", None)
        if recorder is not None:
            recorder.record(
                EventType.DISPATCH_CAP_EXCEEDED,
                parent_id=getattr(context, "graph_event_id", None),
                execution_id=context.run_id,
                status="failed",
                data={
                    "dispatcher": node.name,
                    "reason": str(exc),
                    "depth": dispatcher_depth,
                    "dispatched_count_total": state.dispatched_count,
                },
            )
        raise

    if new_nodes:
        new_batches = topological_sort(new_nodes)
        batches.extend(new_batches)
        logger.info(
            "Dispatch from '%s' added %d node(s) in %d batch(es): %s",
            node.name, len(new_nodes), len(new_batches),
            [n.name for n in new_nodes],
        )

    # Persist dispatch outcome so resume can rebuild the DAG + RunState.
    # Skip when no actual mutation happened (no adds, no removes) — no need
    # to pollute the checkpoint log.
    if added_node_dicts or removed_targets:
        cp = getattr(context, "checkpoint_service", None)
        if cp is not None:
            graph_path = getattr(context, "node_path", "") or ""
            cp.save_dispatch_applied(
                # By its full path, and with the graph it added to: a resume gives each graph
                # back its own, so an agent added inside a stage comes back inside that stage.
                dispatcher_name=f"{graph_path}.{node.name}" if graph_path else node.name,
                added_nodes=added_node_dicts,
                removed_targets=removed_targets,
                dispatcher_depth=dispatcher_depth,
                dispatcher_fingerprint=state.fingerprints[node.name],
                dispatched_count_delta=len(added_node_dicts),
                graph_path=graph_path,
            )

        # Emit an observability event so the dashboard timeline shows the
        # dispatcher caused these children (or removed the target). Parent
        # event id points at the graph so the event attaches at the workflow
        # level rather than nesting under the dispatcher's own completion.
        recorder = getattr(context, "event_recorder", None)
        if recorder is not None:
            recorder.record(
                EventType.DISPATCH_APPLIED,
                parent_id=getattr(context, "graph_event_id", None),
                execution_id=context.run_id,
                status="completed",
                data={
                    "dispatcher": node.name,
                    "added": [n.get("name") for n in added_node_dicts],
                    "removed": list(removed_targets),
                    "depth": dispatcher_depth,
                    "dispatched_count_total": state.dispatched_count,
                },
            )


def _has_pending_tool_call_ops(state: Any, context: ExecutionContext, node: Node) -> bool:
    """Peek at state.pending_ops without draining — same key-lookup logic as
    _drain_tool_call_ops. Used to decide whether to skip the dispatch path
    entirely when an agent has neither declarative nor tool-call ops."""
    if state is None or not getattr(state, "pending_ops", None):
        return False
    parent_path = getattr(context, "node_path", "") or ""
    agent_path = f"{parent_path}.{node.name}" if parent_path else node.name
    buckets = state.pending_ops
    return bool(buckets.get(agent_path) or buckets.get(node.name))


def _drain_tool_call_ops(state: Any, context: ExecutionContext, node: Node) -> list[Any]:
    """Pop any ops that AddNode/RemoveNode queued during this node's agent run.

    Tier 2 tools write to `state.pending_ops[node_path]`. The path they use
    comes from the agent's CallContext (set by AgentNode.run via
    `replace(context, node_path=f"{parent}.{name}", ...)`). We reconstruct
    the same path here so we drain the right bucket.

    Returns [] when no tools were called — most nodes won't use tier 2.
    """
    if state is None or not getattr(state, "pending_ops", None):
        return []
    parent_path = getattr(context, "node_path", "") or ""
    agent_path = f"{parent_path}.{node.name}" if parent_path else node.name
    # Try the canonical path first; fall back to just node.name for nodes
    # where the CallContext wasn't derived from a parent-path context.
    ops = state.pending_ops.pop(agent_path, None)
    if ops is None:
        ops = state.pending_ops.pop(node.name, [])
    return ops or []


def _enforce_caps_and_build(
    *,
    op_dict: dict[str, Any],
    dispatcher_name: str,
    dispatcher_depth: int,
    loader: Any,
    limits: Any,
    state: Any,
    node_map: dict[str, Node],
    node_outputs: dict[str, NodeResult],
    new_nodes: list[Node],
) -> None:
    """Validate safety caps, build a Node, and append it to `new_nodes`.

    Split from _apply_declarative_dispatch for readability — the caller is
    already carrying 10+ locals. All failures raise (either DispatchCapExceeded
    for policy breaches or DispatchRenderError for structural issues) — caller
    doesn't branch on success/failure.
    """
    from temper_ai.stage.dispatch import DispatchRenderError
    from temper_ai.stage.dispatch_limits import (
        DispatchCapExceeded,
        check_cycle,
        fingerprint_node,
    )
    from temper_ai.stage.models import NodeConfig

    # Depth cap — would-be depth of this new node
    new_depth = dispatcher_depth + 1
    if new_depth > limits.max_dispatch_depth:
        raise DispatchCapExceeded(
            f"Dispatch from '{dispatcher_name}' would create a node at "
            f"depth {new_depth}, exceeding max_dispatch_depth="
            f"{limits.max_dispatch_depth}"
        )

    # Run-wide cap — this add would put us over the total
    if state.dispatched_count + 1 > limits.max_dynamic_nodes:
        raise DispatchCapExceeded(
            f"Dispatch from '{dispatcher_name}' would bring run-wide "
            f"dispatched-node count to {state.dispatched_count + 1}, "
            f"exceeding max_dynamic_nodes={limits.max_dynamic_nodes}"
        )

    # Cycle detection — fingerprint this would-be node and walk ancestors
    agent_ref = op_dict.get("agent") or op_dict.get("name") or ""
    child_fp = fingerprint_node(agent_ref, op_dict.get("input_map") or {})
    if limits.cycle_detection:
        ancestor = check_cycle(state, dispatcher_name, child_fp)
        if ancestor is not None:
            raise DispatchCapExceeded(
                f"Dispatch from '{dispatcher_name}' produces a cycle: node "
                f"with fingerprint {child_fp} matches ancestor "
                f"{ancestor!r}"
            )

    # Build the node
    try:
        nc = NodeConfig.from_dict(op_dict)
        built = loader._resolve_node(nc)
    except Exception as exc:
        raise DispatchRenderError(
            f"dispatch from '{dispatcher_name}' produced node "
            f"{op_dict.get('name', '<unnamed>')!r} that failed to "
            f"build: {exc}"
        ) from exc
    # Name collision. _apply_declarative_dispatch's remove-pass clears
    # node_map + node_outputs for "being replaced" names before adds run,
    # so a genuine collision here means the agent emitted an add that
    # shadows an existing (non-being-removed) node.
    if built.name in node_map or built.name in node_outputs:
        raise DispatchRenderError(
            f"dispatch from '{dispatcher_name}' produced node "
            f"{built.name!r} which already exists in the DAG"
        )

    # All caps satisfied — commit state updates
    node_map[built.name] = built
    new_nodes.append(built)
    state.depths[built.name] = new_depth
    state.parents[built.name] = dispatcher_name
    state.fingerprints[built.name] = child_fp
    state.dispatched_count += 1


def _loop_verdict_missing(
    node: Node, result: NodeResult, node_outputs: dict[str, NodeResult],
) -> str | None:
    """Why a completed node's loop cannot tell whether to go round again; None if it can.

    A loop_condition whose source is missing (or cannot be read at all) used to evaluate
    as "do not loop", so the loop ended as if its verdict had said stop, and the run went
    on to complete. b012 on 2026-09-25: the check's JSON did not parse, its verdict was
    missing, and the write/check loop stopped after one pass. Now the node fails, without
    another pass, and a failure travels down the graph like any other. The `exists`
    operator asks whether the value is there, so a missing value is its answer.
    """
    condition = node.loop_condition
    if not (node.loop_to and condition and result.status == Status.COMPLETED):
        return None
    if condition.get("operator", "equals") == "exists":
        return None
    source = condition.get("source")
    try:
        value = source_value(condition, node_outputs)
    except Exception as exc:
        return f"its loop cannot tell whether to go round again: {exc}"
    if value is None or (isinstance(value, str) and not value.strip()):
        return f"it gave no {source}, so its loop cannot tell whether to go round again"
    return None


def _handle_loop(
    node: Node,
    result: NodeResult,
    node_outputs: dict[str, NodeResult],
    loop_counts: dict[str, int],
    loop_feedback: dict[str, NodeResult],
    batches: list[list[Node]],
    node_map: dict[str, Node],
    checkpoint_service: Any = None,
    input_data: dict | None = None,
    retired: list[NodeResult] | None = None,
    checkpoint_prefix: str = "",
) -> int | None:
    """Handle loop_to logic. Returns batch index to rewind to, or None.

    Triggers a loop rewind when:
    - The node FAILED (original behavior), OR
    - The node COMPLETED but has a loop_condition that evaluates to True
      (e.g., structured.check_result == "FAIL")

    Before clearing node_outputs for the rewind, preserves the triggering
    node's result in loop_feedback so the loop target can access it via
    _loop_feedback_<node_name> in its input_data.
    """
    if not node.loop_to:
        return None

    # Determine if a loop should fire
    should_loop = False

    if result.status == Status.FAILED:
        should_loop = True
    elif node.loop_condition and result.status == Status.COMPLETED:
        try:
            should_loop = evaluate_condition(node.loop_condition, node_outputs)
        except Exception as exc:
            logger.warning(
                "Loop condition evaluation failed for '%s': %s", node.name, exc,
            )

    if not should_loop:
        return None

    loop_key = f"{node.name}->{node.loop_to}"
    loop_counts[loop_key] += 1

    if loop_counts[loop_key] >= node.max_loops:
        policy = node.on_max_loops or "silent"
        logger.warning(
            "Loop %s reached max_loops (%d) — policy=%s",
            loop_key, node.max_loops, policy,
        )
        if policy == "ship_with_open_issues":
            _append_known_issues(node, result, loop_key, loop_counts[loop_key], input_data)
        elif policy == "fail" and result.status != Status.FAILED:
            # The step itself went well, but its loop still wants another round and there is
            # none left: that is this step failing. Its outcome was already written as done, so
            # _record_ran_out writes it again as the failure it is -- event, checkpoint and the
            # run's stop -- or a resume would restore it as done and finish green. A step that
            # failed by itself keeps its own error; it was written as failed already.
            result.status = Status.FAILED
            result.error = ran_out_reason(loop_counts[loop_key], node.max_loops, node.loop_to)
            result.metadata[RAN_OUT_OF_ROUNDS] = {
                "count": loop_counts[loop_key], "max": node.max_loops, "loop_to": node.loop_to,
            }
        # "silent" (default) → legacy behavior: stop looping, continue workflow silently
        return None

    logger.info(
        "Loop %s iteration %d/%d — rewinding to '%s'",
        loop_key, loop_counts[loop_key], node.max_loops, node.loop_to,
    )

    # Preserve the triggering node's output so the loop target can read it
    loop_feedback[node.name] = result

    # Find which batch contains the target node
    for idx, batch in enumerate(batches):
        if any(n.name == node.loop_to for n in batch):
            # Collect names of nodes that will be cleared
            cleared_nodes = [
                n.name
                for subsequent_batch in batches[idx:]
                for n in subsequent_batch
            ]
            # Record the rewind in checkpoint history
            if checkpoint_service:
                # Same keys the completions were saved under, so a replay clears the right ones.
                checkpoint_service.save_loop_rewind(
                    trigger_node=checkpoint_prefix + node.name,
                    target_node=checkpoint_prefix + node.loop_to,
                    cleared_nodes=[checkpoint_prefix + n for n in cleared_nodes],
                    trigger_result=result,
                )
            # Clear outputs for nodes from target onwards (they'll re-run).
            # Retire rather than drop: the attempt is no longer the node's
            # output, but its cost and tokens still belong to the run.
            for name in cleared_nodes:
                discarded = node_outputs.pop(name, None)
                if discarded is not None and retired is not None:
                    retired.append(discarded)
            return idx

    logger.warning("Loop target '%s' not found in graph", node.loop_to)
    return None


def _resolve_inputs(
    node: Node,
    input_data: dict,
    node_outputs: dict[str, NodeResult],
    loop_feedback: dict[str, NodeResult] | None = None,
    unresolved: list[str] | None = None,
    node_map: dict[str, Node] | None = None,
) -> dict:
    """Resolve input_map for a node.

    If no input_map, node receives full input_data from the graph,
    plus auto-injected dependency outputs as `other_agents` (formatted
    text from all completed predecessors).

    Source references (when input_map IS defined):
    - "workflow.field" or "input.field" → input_data[field]
    - "node_name.output" → node_outputs[node_name].output
    - "node_name.structured.field" → node_outputs[node_name].structured_output[field]

    Loop feedback: when a node triggered a loop rewind, its result is
    preserved in loop_feedback. Source references can resolve from
    loop_feedback when the node is not in node_outputs (cleared by rewind).
    """
    # Merge node_outputs with loop_feedback — node_outputs takes priority
    effective_outputs = dict(loop_feedback) if loop_feedback else {}
    effective_outputs.update(node_outputs)

    input_map = node.config.input_map
    if not input_map:
        resolved = dict(input_data)
        deps = node.config.depends_on or []
        dep_outputs = [
            f"[{dep_name}]:\n{effective_outputs[dep_name].output}"
            for dep_name in deps
            if dep_name in effective_outputs and effective_outputs[dep_name].output
        ]
        if dep_outputs:
            resolved["other_agents"] = "\n\n".join(dep_outputs)
        return resolved

    resolved = {
        local_name: _resolve_single_input(
            node.name, local_name, source, input_data, effective_outputs, unresolved, node_map,
        )
        for local_name, source in input_map.items()
    }
    if logger.isEnabledFor(logging.DEBUG):
        for local_name, value in resolved.items():
            val_len = len(str(value)) if value else 0
            logger.debug("input_map resolved: %s.%s = %s (%d chars)", node.name, local_name, input_map[local_name], val_len)
    return resolved


def _unserved_reason(node_name: str, source_node: str, node_map: dict[str, Node] | None) -> str | None:
    """Why a source node has no output to give, or None when that is by design.

    Three cases the dashboard used to show as one "(no such node)":
      * the name is not in the graph: a typo in the wiring; the run should say so;
      * the node is in the graph and runs *after* this one, i.e. depends on it
        (directly or through others): a loop-back, which by construction has
        nothing to give on the first pass and is served from loop feedback on a
        rewind. Nothing is wrong; listing it made every first pass of the epd
        implementer show five unresolved inputs;
      * the node is in the graph and not downstream, yet has not run: it is
        neither a dependency nor a loop-back, so the wiring is missing a
        ``depends_on``, and the run should say that too.
    Without the graph the first wording stands, as before.
    """
    if node_map is None:
        return "no such node"
    if source_node not in node_map:
        return "no such node in this graph"
    if source_node == node_name:
        # A node that loops to itself reads its own previous round this way
        # (the rewind preserves it as loop feedback); on the first round there
        # is none, by design. Any other self-reference is a wiring mistake.
        if node_map[node_name].config.loop_to == node_name:
            return None
        return "a node cannot read its own output unless it loops to itself"
    seen: set[str] = set()
    frontier = [source_node]
    while frontier:
        name = frontier.pop()
        if name in seen:
            continue
        seen.add(name)
        deps = (node_map[name].config.depends_on or []) if name in node_map else []
        if node_name in deps:
            return None
        frontier.extend(deps)
    return f"`{source_node}` has not run yet; is it missing from depends_on?"


_NODE_REF_HEAD = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _looks_like_node_ref(source: str) -> bool:
    """True if `source` parses as a node-ref path `node.field[.sub...]`.

    Node refs must lead with a Python-identifier-shaped segment (matches the
    pattern of legal YAML agent/node names) followed by a dot. Strings that
    don't fit this shape — most notably Jinja-rendered literals like
    "Research hiking trails in Japan" — are treated as literal values so
    the resolver doesn't spuriously warn and return None.
    """
    head = source.split(".", 1)[0]
    return bool(_NODE_REF_HEAD.match(head))


def _resolve_single_input(
    node_name: str,
    local_name: str,
    source: Any,
    input_data: dict,
    node_outputs: dict[str, NodeResult],
    unresolved: list[str] | None = None,
    node_map: dict[str, Node] | None = None,
) -> Any:
    """Resolve a single input_map entry from its source reference.

    Source shapes supported (in order of precedence):
      node.output / node.structured.path / node.status  — node ref
      workflow.field / input.field                       — workflow input
      any other string                                   — literal passed through

    Non-string sources (numbers, bools, lists) are literals by definition.

    ``unresolved`` collects what could not be served, with a reason; given the
    graph (``node_map``) the reason is exact, and a source that feeds this node
    only on a loop rewind is not listed at all on the first pass (see
    ``_unserved_reason``).
    """
    if not isinstance(source, str):
        return source
    parts = source.split(".")
    if len(parts) < 2:
        # Bare identifier — resolve against workflow inputs if present,
        # else treat as a literal. Literal fallback lets dispatched
        # input_maps with Jinja-rendered scalars ("Tokyo") work.
        if source in input_data:
            return input_data[source]
        return source

    source_node = parts[0]
    field = parts[1]

    # Strings whose head doesn't parse as a node identifier (spaces,
    # punctuation, sentence text) are literals — not refs that failed to
    # resolve. Skip the node-outputs lookup and return as-is.
    if not _looks_like_node_ref(source):
        return source

    if source_node in ("workflow", "input"):
        # Support nested paths (input.foo.bar.0.baz) walking dicts + lists,
        # consistent with how .structured. paths work below.
        value: Any = input_data.get(field)
        for key in parts[2:]:
            if isinstance(value, dict):
                value = value.get(key)
            elif isinstance(value, list):
                try:
                    value = value[int(key)]
                except (ValueError, IndexError):
                    return None
            else:
                return None
        return value

    if source_node not in node_outputs:
        reason = _unserved_reason(node_name, source_node, node_map)
        if reason is None:
            logger.debug(
                "Node '%s' input_map '%s': '%s' feeds it only on a loop rewind; first pass",
                node_name, local_name, source_node,
            )
        else:
            logger.warning("Node '%s' input_map '%s' \u2190 %s: %s", node_name, local_name, source, reason)
            if unresolved is not None:
                unresolved.append(f"{local_name} \u2190 {source} ({reason})")
        return None

    result = node_outputs[source_node]

    if field == "output":
        return result.output
    if field == "status":
        return result.status
    if field == "error":
        # Why the node failed or was skipped (None when it did not): what a
        # run_after_failure node reports.
        return result.error
    if field == "failure":
        # What actually went wrong, when .error only names the step (a stage's
        # is "1 node(s) failed: worktree", and a script's "Command exited with
        # code 1"). None when nothing under the node failed.
        return _failure_reason(result)
    if field == "structured" and len(parts) >= 3:
        if not result.structured_output:
            # A node its own condition skipped has nothing to give, by design, like a loop-back
            # on the first pass: a step that reads an optional one (epd_task's `final` reads the
            # last pass, which runs only after some builds) would otherwise show it on every run.
            # A skip for a failure, or for a condition that could not be evaluated, carries an
            # error and is still listed.
            skipped_by_condition = result.status == Status.SKIPPED and not result.error
            if unresolved is not None and not skipped_by_condition:
                unresolved.append(f"{local_name} \u2190 {source} (node produced no structured output)")
            return None
        structured_value: Any = result.structured_output
        for key in parts[2:]:
            structured_value = structured_value.get(key) if isinstance(structured_value, dict) else None
        if structured_value is None and unresolved is not None:
            # A typo in a wiring path otherwise passes null to the agent and
            # the run finishes green, which is indistinguishable from work
            # that was genuinely done.
            unresolved.append(f"{local_name} \u2190 {source} (field not found)")
        return structured_value

    # Child node reference: "stage.child_node.output" or "stage.child_node.structured.field"
    if result.node_results and field in result.node_results:
        child = result.node_results[field]
        if len(parts) < 3:
            return child.output
        child_field = parts[2]
        if child_field == "output":
            return child.output
        if child_field == "status":
            return child.status
        if child_field == "structured" and len(parts) >= 4:
            if not child.structured_output:
                return None
            value = child.structured_output
            for key in parts[3:]:
                value = value.get(key) if isinstance(value, dict) else None
            return value
        return child.output

    logger.warning(
        "Node '%s' input_map '%s': unknown field '%s' on source '%s' "
        "(expected 'output', 'structured', 'status', 'error', 'failure', or a child node name)",
        node_name, local_name, field, source_node,
    )
    return None


def _inject_strategy_context(
    node: Node,
    input_data: dict,
    node_outputs: dict[str, NodeResult],
) -> dict:
    """For leader pattern: inject all dependency outputs as _strategy_context.

    If the agent config has _receives_strategy_context=True (set by leader
    topology generator), combine all dependency outputs into a formatted string.
    """
    # Check if this node's agent config requests strategy context
    agent_config = getattr(node, "agent_config", {})
    if not agent_config.get("_receives_strategy_context"):
        return input_data

    # Build strategy context from dependencies
    dep_outputs = []
    for dep_name in node.depends_on:
        if dep_name in node_outputs:
            dep_result = node_outputs[dep_name]
            if dep_result.output:
                dep_outputs.append(f"[{dep_name}]:\n{dep_result.output}")

    if dep_outputs:
        input_data = {**input_data, "_strategy_context": "\n\n".join(dep_outputs)}

    return input_data


def topological_sort(nodes: list[Node]) -> list[list[Node]]:
    """Kahn's algorithm — returns batches of parallelizable nodes.

    Raises:
        CyclicDependencyError: If graph has circular dependencies.
    """
    node_map = {node.name: node for node in nodes}
    in_degree: dict[str, int] = {node.name: 0 for node in nodes}
    dependents: dict[str, list[str]] = defaultdict(list)

    for node in nodes:
        for dep in node.depends_on:
            if dep in node_map:
                in_degree[node.name] += 1
                dependents[dep].append(node.name)

    queue: deque[str] = deque(name for name, deg in in_degree.items() if deg == 0)
    batches: list[list[Node]] = []
    processed = 0

    while queue:
        batch, next_queue, processed = _drain_batch(queue, node_map, dependents, in_degree, processed)
        batches.append(batch)
        queue = next_queue

    if processed != len(nodes):
        remaining = [n for n in node_map if in_degree.get(n, 0) > 0]
        raise CyclicDependencyError(f"Cyclic dependency detected involving nodes: {remaining}")

    return batches


def _drain_batch(
    queue: deque[str],
    node_map: dict[str, Node],
    dependents: dict[str, list[str]],
    in_degree: dict[str, int],
    processed: int,
) -> tuple[list[Node], deque[str], int]:
    """Drain the current queue into a batch, returning (batch, next_queue, processed_count)."""
    batch: list[Node] = []
    next_queue: deque[str] = deque()
    while queue:
        name = queue.popleft()
        batch.append(node_map[name])
        processed += 1
        for dependent in dependents[name]:
            in_degree[dependent] -= 1
            if in_degree[dependent] == 0:
                next_queue.append(dependent)
    return batch, next_queue, processed


def _park_at_gate(
    context: ExecutionContext,
    node: Node,
    event_id: str,
    path: str,
    gate_round: int,
) -> RunParked | None:
    """Save where a Pi run waits at a gate, under the wait's own id, so it can let its worker go.

    The one parking path, shared with a step's own waits (stage/step_waits.py ``park``), told
    on this module's logger as before. Returns the RunParked to raise, or None when the
    checkpoint could not be saved: then the gate holds its worker and waits as any other gate
    does, rather than letting go of a run nothing would know how to carry on.
    """
    return park(context, event_id=event_id, node=node.name, path=path, round=gate_round,
                log=logger)


def _wait_for_gate(
    node: Node,
    context: ExecutionContext,
    parent_event_id: str,
    node_outputs: dict[str, NodeResult] | None = None,
) -> dict[str, Any] | None:
    """Pause execution and wait for human approval at a gate node.

    Records a ``stage.started`` event with status ``waiting`` (the UI and
    ``GET /api/runs/{id}/gates`` read it) carrying ``gate_context`` — the
    upstream outputs and the questions they asked — then blocks until the
    gate is approved or the workflow is cancelled. Approval arrives one of
    two ways:

    - in-process runs: ``POST /approve`` sets the ``GateSignal`` in the
      shared ``gate_registry`` (its ``response`` carries the answer);
    - subprocess/external runs (worker in another process or container):
      the API cannot reach that registry, so it flips the waiting event's
      status to ``approved`` in the database — with ``gate_response`` in
      its data — and the worker polls for it.

    Each wait is one event, and an approval names it (or names the step, when only one wait
    is open there): see :mod:`temper_ai.stage.gate` for which wait is which. A run picked up
    again does not ask twice: an approval given while it was down is used as the answer, a
    wait still open from before is waited on again (the buttons already sent keep working),
    and any other open wait at the step is closed as replaced.

    Returns the human's response (see :mod:`temper_ai.stage.gate`) or None
    for a plain approval.
    """
    gate_registry = context.gate_registry
    if gate_registry is None:
        gate_registry = {}
        logger.info("Node '%s' has gate=true and no in-process gate registry; approval via the database only", node.name)
    recorder = context.event_recorder
    path = f"{context.node_path}.{node.name}" if context.node_path else node.name

    # Waits someone in this process is still waiting on (the same step running twice at once)
    # are theirs: neither taken over nor closed here.
    history = [ev for ev in _gate_history(recorder, node.name)
               if signal_key(context.run_id, str(ev.get("id"))) not in gate_registry]
    earlier = earlier_waits(history, path, node.name)
    new_id = str(uuid.uuid4())
    answer, adopt = earlier.answer, earlier.adopt
    for ev in earlier.retire:
        approved_meanwhile = _retire_wait(recorder, ev, (answer or adopt or {}).get("id") or new_id)
        if approved_meanwhile and answer is None:
            answer = approved_meanwhile
    stop = getattr(context, "run_stop", None)
    if isinstance(stop, RunStop) and stop.kind == "cancelled":
        # Return to the same start door without spending an old answer or opening a wait.
        return None
    if answer is not None:
        if adopt is not None:
            _retire_wait(recorder, adopt, str(answer.get("id")))
        if isinstance(stop, RunStop):
            stop.note_preflight_gate_answer(path, str(answer["id"]))
        return _use_earlier_answer(recorder, answer, path)

    if adopt is not None:
        waiting_event_id = str(adopt["id"])
        gate_round = (adopt.get("data") or {}).get("gate_round") or earlier.round
        logger.info("Gate: '%s' is still waiting for the approval it asked for before the run "
                    "stopped (event %s); waiting on it again", path, waiting_event_id)
    else:
        waiting_event_id, gate_round = new_id, earlier.round
    if adopt is None:
        # Record waiting event so the UI can show the gate — and what it is about. Recorded
        # before the in-process signal is registered: an approval, however fast it comes,
        # then finds the wait itself and is written on it with its request id and who sent
        # it, so the same request sent again gets its first answer back. (Registered first,
        # an approval in between found the signal alone and was answered there, unrecorded.)
        recorder.record(
            EventType.STAGE_STARTED,
            data={
                **_build_node_event_data(node),
                "gate": True,
                "gate_status": WAITING,
                "gate_path": path,
                "gate_round": gate_round,
                "gate_context": build_gate_context(node.config.depends_on or [], node_outputs or {}),
            },
            parent_id=parent_event_id,
            execution_id=context.run_id,
            status=WAITING,
            event_id=waiting_event_id,
        )
    gate_event = GateSignal(waiting_event_id, node.name, path, gate_round)
    key = signal_key(context.run_id, waiting_event_id)
    gate_registry[key] = gate_event
    try:
        # A Pi workflow does not hold its worker while it waits: it saves where it is, under
        # the wait's own id, and lets the worker go (docs/gates.md, runner/parked.py).
        if getattr(context, "park_at_gates", False):
            parked = _park_at_gate(context, node, waiting_event_id, path, gate_round)
            if parked is not None:
                raise parked

        # Save checkpoint before waiting (so the run can resume if server crashes while waiting)
        if context.checkpoint_service:
            context.checkpoint_service._save(
                event_type="gate_waiting",
                node_name=path,
                status="waiting",
            )

        logger.info("Gate: waiting for approval on '%s', round %s (execution: %s, event %s)",
                    path, gate_round, context.run_id, waiting_event_id)
        _wait_for_approval(gate_event, recorder, context, waiting_event_id, path)
    finally:
        gate_registry.pop(key, None)

    # The response came either with the in-process signal or with the
    # database approval — read the event for the latter.
    response = gate_event.response
    if response is None:
        try:
            persisted = recorder.event_data(waiting_event_id) or {}
        except Exception as exc:  # the approval already got through; the answer is best-effort
            logger.warning("Gate: could not read the response for '%s': %s", path, exc)
            persisted = {}
        if isinstance(persisted.get("gate_response"), dict):
            response = persisted["gate_response"]
    if isinstance(stop, RunStop) and stop.kind == "cancelled":
        # An already-waiting gate is over too; keep any concurrent answer unconsumed.
        return None
    # Provisional use until producer admission. If a self-stop wins during this write
    # or later start recording, settlement keeps the approval visible and unconsumed.
    if isinstance(stop, RunStop):
        stop.note_preflight_gate_answer(path, waiting_event_id)
    recorder.update_event(
        waiting_event_id,
        status=APPROVED,
        data={"gate_status": APPROVED, "gate_used_at": utcnow().isoformat(),
              **({"gate_response": response} if response else {})},
    )
    logger.info("Gate: '%s' approved%s, continuing", path, " with a response" if response else "")
    return response


def _wait_for_approval(
    gate_event: GateSignal,
    recorder: Any,
    context: ExecutionContext,
    event_id: str,
    path: str,
) -> None:
    """Block until this wait is approved (in memory or in the database) or the run is stopped."""
    while not gate_event.is_set():
        _check_cancelled(context)
        stop = getattr(context, "run_stop", None)
        if isinstance(stop, RunStop) and stop.kind == "cancelled":
            return
        if gate_event.wait(timeout=GATE_POLL_SECONDS):
            return
        try:
            status = recorder.event_status(event_id)
        except Exception as exc:  # DB hiccup: keep waiting, the in-memory path still works
            logger.warning("Gate: could not read approval state for '%s': %s", path, exc)
            continue
        if status == APPROVED:
            return
        if status == REPLACED:
            # Another attempt of this run took this wait over: this one is not the run any more.
            # It stands down (never retried, never ending anything of the newer attempt's).
            raise ReplacedByLaterAttempt(
                f"The approval at '{path}' was taken over by a later attempt of this run")


def _step_path(context: ExecutionContext, node: Node) -> str:
    """A step's own path in the run: ``review.security_check`` inside stage ``review``."""
    return f"{context.node_path}.{node.name}" if context.node_path else node.name


def _keep_gate_answer(context: ExecutionContext, node: Node, parked: RunParked) -> None:
    """Keep the answer a gated step went on with, for when the run carries the step on.

    Its gate marked the answer used as the step started; then a wait inside the step let its
    worker go (a wait the step asked itself, stage/step_waits.py, or the approval of a step
    inside a gated stage), and the step will run again from the start. Without this its gate
    would ask the owner a second time for the same go.
    """
    path = _step_path(context, node)
    recorder = context.event_recorder
    for ev in reversed(_gate_history(recorder, node.name)):
        data = ev.get("data") or {}
        if data.get("gate_path") != path or ev.get("status") != APPROVED:
            continue
        if data.get("gate_used_at"):
            try:
                recorder.update_event(str(ev["id"]), status=APPROVED,
                                      data={"gate_used_at": None, "gate_kept_at": utcnow().isoformat(),
                                            "gate_kept_while": parked.event_id})
            except Exception as exc:  # noqa: BLE001 - at worst the gate asks again
                logger.warning("Gate: could not keep the answer of '%s' for when it carries on: %s",
                               path, exc)
        return


def _gate_history(recorder: Any, name: str) -> list[dict[str, Any]]:
    """This run's earlier waits at steps called ``name``; none when the run keeps no events."""
    try:
        found = recorder.gate_events(name)
    except Exception as exc:  # cannot look: ask afresh, as before waits could be found
        logger.warning("Gate: could not read the earlier approvals for '%s': %s", name, exc)
        return []
    return found if isinstance(found, list) else []


def _retire_wait(recorder: Any, ev: dict[str, Any], took_over_by: str) -> dict[str, Any] | None:
    """Close an open wait nobody waits on any more, as replaced by ``took_over_by``.

    Its messages and buttons then say it was replaced. Returns the wait when someone approved
    it just before it could be closed: that approval is the answer.
    """
    won, after = recorder.decide(
        str(ev["id"]),
        expect=(WAITING,),
        status=REPLACED,
        data={"gate_status": REPLACED, "gate_replaced_at": utcnow().isoformat(),
              "gate_replaced_by": took_over_by},
    )
    if won:
        logger.info("Gate: closed the approval %s at '%s' as replaced", ev.get("id"),
                    (ev.get("data") or {}).get("gate_path") or (ev.get("data") or {}).get("name"))
        return None
    if after and after.get("status") == APPROVED and not (after.get("data") or {}).get("gate_used_at"):
        return after
    return None


def _use_earlier_answer(recorder: Any, answer: dict[str, Any], path: str) -> dict[str, Any] | None:
    """Go on with an approval given while nothing was waiting on it, without asking again."""
    data = answer.get("data") or {}
    response = data.get("gate_response") if isinstance(data.get("gate_response"), dict) else None
    recorder.update_event(
        str(answer["id"]),
        status=APPROVED,
        data={"gate_status": APPROVED, "gate_used_at": utcnow().isoformat()},
    )
    who = f" by {data['gate_decided_by']}" if data.get("gate_decided_by") else ""
    logger.info("Gate: '%s' was approved%s at %s while the run was stopped; going on with that answer "
                "without asking again", path, who, data.get("gate_decided_at") or "an earlier moment")
    return response


def _check_cancelled(context: ExecutionContext) -> None:
    """Raise CancellationError if the workflow has been cancelled."""
    if context.cancel_event and context.cancel_event.is_set():
        raise CancellationError("Workflow cancelled by user")


def _stopped_mid_step(context: ExecutionContext, node_outputs: dict[str, NodeResult]) -> bool:
    """The run was stopped and a step did not complete: the stop, not the
    step, is why the run is over."""
    if not (context.cancel_event and context.cancel_event.is_set()):
        return False
    return any(r.status in (Status.FAILED, Status.CANCELLED) for r in node_outputs.values())


FAILURE_TAIL_LINES = 3
FAILURE_MAX_CHARS = 600


def _failure_reason(result: NodeResult, path: str = "") -> str | None:
    """The first step that failed under a node: its path, its error and the last lines it printed.

    A stage's own error only names the failed steps, and a script's only gives its exit code; the
    reason (git's "Could not resolve host", a test's assertion) is at the end of the output. For a
    node that has to tell a person what went wrong. None when nothing under the node failed.
    """
    for name, child in (result.node_results or {}).items():
        found = _failure_reason(child, f"{path}/{name}" if path else name)
        if found:
            return found
    if result.status != Status.FAILED:
        return None
    lines = [ln.strip() for ln in (result.output or "").splitlines() if ln.strip()]
    tail = [ln for ln in lines if ln not in ("STDOUT:", "STDERR:")][-FAILURE_TAIL_LINES:]
    reason = ": ".join(p for p in (path, result.error or "failed") if p)
    if tail:
        reason += " -- " + " | ".join(tail)
    return reason if len(reason) <= FAILURE_MAX_CHARS else reason[: FAILURE_MAX_CHARS - 3] + "..."


def _failed_node_names(node_outputs: dict[str, NodeResult], prefix: str = "") -> list[str]:
    """Names of every node that ended FAILED, recursing into stage children.

    A node that failed and was then re-run by a loop shows up with its
    latest result only (node_outputs holds the last attempt), so a retried
    and passed node does not count.
    """
    failed: list[str] = []
    for name, result in node_outputs.items():
        path = f"{prefix}{name}"
        if result.status == Status.FAILED:
            failed.append(path)
        if result.node_results:
            failed.extend(_failed_node_names(result.node_results, prefix=f"{path}/"))
    return failed


def _get_final_output(
    nodes: list[Node],
    node_outputs: dict[str, NodeResult],
) -> NodeResult | None:
    """Get the graph output from completed nodes.

    Sequential: returns the last node's output (pipeline result).
    Parallel (all nodes in one batch / no deps): combines all outputs
    so downstream nodes see work from every agent.
    """
    completed = [
        (node, node_outputs[node.name])
        for node in nodes
        if node.name in node_outputs
        and node_outputs[node.name].status != Status.SKIPPED
    ]
    if not completed:
        return None

    # If only one node produced output, return it directly
    if len(completed) == 1:
        return completed[0][1]

    # Check if this is effectively parallel (no inter-node dependencies)
    has_internal_deps = any(
        dep in node_outputs for node in nodes for dep in node.depends_on
    )

    if has_internal_deps:
        # Sequential / DAG — return the last node's result
        return completed[-1][1]

    # Parallel — combine all outputs into one
    combined_parts = []
    for node, result in completed:
        if result.output:
            combined_parts.append(f"[{node.name}]:\n{result.output}")

    last = completed[-1][1]
    if combined_parts:
        from dataclasses import replace as dc_replace
        return dc_replace(last, output="\n\n".join(combined_parts))
    return last


def _append_known_issues(
    node: Node,
    result: NodeResult,
    loop_key: str,
    iterations: int,
    input_data: dict | None,
) -> None:
    """Append the last triggering-node review output to .context/KNOWN_ISSUES.md
    so downstream planners see what was left unresolved.

    Called when max_loops is exhausted under policy=ship_with_open_issues.
    The workflow continues, but the unresolved verdict is no longer silent.
    """
    workspace_path = (input_data or {}).get("workspace_path")
    if not workspace_path:
        logger.warning(
            "_append_known_issues: no workspace_path in input_data; "
            "skipping KNOWN_ISSUES.md write for loop %s", loop_key,
        )
        return
    from datetime import UTC, datetime
    from pathlib import Path
    ctx_dir = Path(workspace_path) / ".context"
    ctx_dir.mkdir(parents=True, exist_ok=True)
    known_path = ctx_dir / "KNOWN_ISSUES.md"
    review_path = ctx_dir / "REVIEW.md"
    review_excerpt = ""
    if review_path.exists():
        try:
            review_excerpt = review_path.read_text()[:4000]
        except Exception:
            review_excerpt = "(could not read REVIEW.md)"
    now = datetime.now(UTC).isoformat(timespec="seconds")
    header = "# Known Issues (shipped with open items)\n\n" if not known_path.exists() else ""
    entry = (
        f"## {now} — loop {loop_key} exhausted after {iterations} iterations\n\n"
        f"Triggering node: `{node.name}`\n"
        f"Policy: ship_with_open_issues\n"
        f"Last verdict output captured below. Downstream planners: treat these as TODO.\n\n"
        f"### Last REVIEW.md at exhaustion\n\n"
        f"```\n{review_excerpt.strip()}\n```\n\n"
        f"---\n\n"
    )
    try:
        with open(known_path, "a") as f:
            if header:
                f.write(header)
            f.write(entry)
        logger.warning(
            "Appended unresolved loop %s to %s (review excerpt %d chars)",
            loop_key, known_path, len(review_excerpt),
        )
    except Exception as exc:
        logger.error("Failed to write KNOWN_ISSUES.md: %s", exc)
