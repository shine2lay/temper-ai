"""Picking a run back up from its checkpoints: shared by the server and the run box.

In-process runs resume in a server thread (``POST /api/runs/{id}/resume``);
runs in their own box resume through the queue, and ``temper run-workflow``
restores them here. Both paths use these two helpers, so a resume looks the
same wherever it happens.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def find_latest_workflow_event(execution_id: str) -> dict | None:
    """Return the most recent `workflow.started` event for the given run, or
    None if none exists. Used during resume to stamp the new workflow event
    with `data.resume_of` pointing back to the prior attempt.
    """
    from temper_ai.observability.event_types import EventType
    from temper_ai.observability.recorder import get_events
    # Newest first: oldest-first with a limit stopped at the 100th attempt, and a run that
    # parks at every owner wait can start more than that (runner/attempts.py asks this too).
    candidates = get_events(
        execution_id=execution_id,
        event_type=EventType.WORKFLOW_STARTED,
        limit=1,
        newest_first=True,
    )
    if not candidates:
        return None
    # Latest by timestamp wins.
    return max(candidates, key=lambda e: e.get("timestamp") or "")


def apply_dispatch_history_on_resume(
    checkpoint_svc, graph_loader, nodes, context,
) -> list[str]:
    """Restore DispatchRunState from the saved dispatch_applied events.

    The agents a dispatcher added are *not* put back here. They are put back by the
    graph they were added to, as it starts (``stage/executor.py``,
    ``_readd_dispatched``): an agent added inside a stage belongs to that stage, and
    adding it at the top level -- which is what this used to do -- gave it a path it
    never had. Its finished result, checkpointed as ``build.worker_3``, then matched
    nothing, so every dispatched agent ran again on every resume, and "re-run from
    here" lost them altogether.

    What is restored here is the run-wide bookkeeping the caps are counted from
    (depths, parents, fingerprints, dispatched_count), which is not per graph.

    op=remove targets are already handled by reconstruct() which marks them
    SKIPPED in the restored node_outputs.

    Returns: list of dispatcher names whose state was replayed (for resume
    metadata stamping on the new workflow.started event).
    """
    from temper_ai.stage.dispatch_limits import DispatchRunState, fingerprint_node

    history = checkpoint_svc.reconstruct_dispatch_history()
    if not history:
        return []

    # Seed the state if the context doesn't have one yet — on resume, no
    # dispatch has fired in this executor process, so state starts empty.
    if context.dispatch_state is None:
        context.dispatch_state = DispatchRunState()
    state = context.dispatch_state

    replayed_dispatchers: list[str] = []
    for event in history:
        # Saved as the dispatcher's full path; the caps are counted by bare name.
        dispatcher_name = (event["dispatcher_name"] or "").split(".")[-1]
        # Record dispatcher's own fingerprint + depth so cycle/depth walks
        # work on post-resume dispatches.
        state.fingerprints.setdefault(
            dispatcher_name,
            event["dispatcher_fingerprint"],
        )
        dispatcher_depth = event["dispatcher_depth"]

        for node_dict in event["added_nodes"]:
            name = node_dict.get("name")
            if not isinstance(name, str):
                logger.warning(
                    "dispatch_applied entry for '%s' has a node without a "
                    "name — skipping restore of that node", dispatcher_name,
                )
                continue
            # Rebuild state so future dispatches from this node see correct depth etc.
            new_depth = dispatcher_depth + 1
            state.depths[name] = new_depth
            state.parents[name] = dispatcher_name
            # Compute the restored child's fingerprint identically to how
            # the original run did — see _enforce_caps_and_build.
            agent_ref = node_dict.get("agent") or name
            state.fingerprints[name] = fingerprint_node(
                agent_ref, node_dict.get("input_map") or {},
            )
        state.dispatched_count += event["dispatched_count_delta"]
        if dispatcher_name not in replayed_dispatchers:
            replayed_dispatchers.append(dispatcher_name)

    logger.info(
        "Resume: replayed the state of %d dispatch(es); dispatched_count=%d. The agents "
        "themselves come back with the graph they were added to.",
        len(history), state.dispatched_count,
    )
    return replayed_dispatchers
