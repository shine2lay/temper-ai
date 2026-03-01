"""Dynamic edge routing helpers for WorkflowExecutor.

Extracted from WorkflowExecutor to keep class under 500-line threshold.
These functions handle multi-target dynamic routing (sequential chains
and parallel fan-out) from _next_stage signals.
"""

import logging
from collections.abc import Callable
from typing import Any

from temper_ai.stage.executors.state_keys import StateKeys
from temper_ai.workflow.engines.workflow_executor import (
    DEFAULT_MAX_DYNAMIC_HOPS,
    _build_dynamic_input_wrappers,
    _extract_next_stage_signal,
    _run_parallel_stage_batch,
)

logger = logging.getLogger(__name__)

# Type alias for the negotiation executor callable
NegotiateFn = Callable[
    [str, dict[str, Callable], dict[str, Any], dict[str, Any]],
    dict[str, Any],
]


def follow_dynamic_edges(
    stage_name: str,
    stage_nodes: dict[str, Callable],
    state: dict[str, Any],
    workflow_config: dict[str, Any],
    negotiate_fn: NegotiateFn,
) -> dict[str, Any]:
    """Follow dynamic edge signals after a stage completes.

    Supports single targets, sequential chains (list), and
    parallel fan-out. Chains up to ``DEFAULT_MAX_DYNAMIC_HOPS``.

    Args:
        stage_name: Name of the stage that just completed
        stage_nodes: Pre-built stage node callables
        state: Current workflow state
        workflow_config: Full workflow configuration
        negotiate_fn: Callable for executing a stage with negotiation

    Returns:
        Updated workflow state after following all dynamic edges
    """
    current_stage = stage_name
    hop_count = 0

    while hop_count < DEFAULT_MAX_DYNAMIC_HOPS:
        signal = _extract_next_stage_signal(current_stage, state)
        if signal is None:
            break

        if signal["mode"] == "parallel":
            state, hop_count = _follow_parallel_targets(
                signal,
                stage_nodes,
                state,
                workflow_config,
                hop_count,
                negotiate_fn,
            )
            break  # No further chaining from parallel source

        # Sequential: execute each target in order
        prev_hop_count = hop_count
        state, current_stage, hop_count = _follow_sequential_targets(
            signal["targets"],
            stage_nodes,
            state,
            workflow_config,
            current_stage,
            hop_count,
            negotiate_fn,
        )
        # If no hops were made (all targets skipped/unknown), stop
        if hop_count == prev_hop_count:
            break

    if hop_count >= DEFAULT_MAX_DYNAMIC_HOPS:
        logger.warning(
            "Dynamic edge chain reached max hops (%d) at stage '%s'",
            DEFAULT_MAX_DYNAMIC_HOPS,
            current_stage,
        )

    return state


def _follow_sequential_targets(
    targets: list[dict[str, Any]],
    stage_nodes: dict[str, Callable],
    state: dict[str, Any],
    workflow_config: dict[str, Any],
    current_stage: str,
    hop_count: int,
    negotiate_fn: NegotiateFn,
) -> tuple[dict[str, Any], str, int]:
    """Execute sequential targets in order, counting hops.

    Returns:
        Tuple of (state, last_stage_name, hop_count)
    """
    for target_info in targets:
        if hop_count >= DEFAULT_MAX_DYNAMIC_HOPS:
            break
        target = target_info["name"]
        if target not in stage_nodes:
            logger.warning(
                "Stage '%s' declared _next_stage '%s' but "
                "target not found; skipping",
                current_stage,
                target,
            )
            continue

        hop_count += 1
        logger.info(
            "Dynamic edge: '%s' → '%s' (hop %d/%d)",
            current_stage,
            target,
            hop_count,
            DEFAULT_MAX_DYNAMIC_HOPS,
        )

        if target_info["inputs"]:
            state[StateKeys.DYNAMIC_INPUTS] = target_info["inputs"]

        state = negotiate_fn(target, stage_nodes, state, workflow_config)
        state.pop(StateKeys.DYNAMIC_INPUTS, None)
        current_stage = target

    return state, current_stage, hop_count


def _follow_parallel_targets(
    signal: dict[str, Any],
    stage_nodes: dict[str, Callable],
    state: dict[str, Any],
    workflow_config: dict[str, Any],
    hop_count: int,
    negotiate_fn: NegotiateFn,
) -> tuple[dict[str, Any], int]:
    """Execute parallel targets concurrently, then follow sequential signals.

    Parallel targets run via ``_run_parallel_stage_batch``. After
    completion, each target's ``_next_stage`` signals are followed
    sequentially only (no recursive fan-out). Duplicate targets are
    deduplicated so each stage runs at most once.

    If ``signal`` contains a ``converge`` field (``{"name": "D"}``),
    the convergence stage runs exactly once after all branches complete.
    ``_convergence_predecessors`` is set in state so that
    ``PredecessorResolver`` can determine which branches fed into it.

    Args:
        signal: Normalized parallel signal dict with ``targets``,
            ``mode``, and optional ``converge``.
        stage_nodes: Pre-built stage node callables
        state: Current workflow state
        workflow_config: Full workflow configuration
        hop_count: Current dynamic hop count
        negotiate_fn: Callable for executing a stage with negotiation

    Returns:
        Tuple of (state, hop_count)
    """
    from temper_ai.workflow.engines.workflow_executor import _merge_stage_result

    targets = signal["targets"]
    converge = signal.get("converge")

    runnable = _dedup_targets(targets, stage_nodes)
    if not runnable:
        return state, hop_count

    hop_count += 1  # Parallel batch counts as 1 hop
    runnable_names = [t["name"] for t in runnable]
    logger.info(
        "Dynamic parallel fan-out: %s (hop %d/%d)",
        runnable_names,
        hop_count,
        DEFAULT_MAX_DYNAMIC_HOPS,
    )

    wrapped_nodes = _build_dynamic_input_wrappers(runnable, stage_nodes)
    results = _run_parallel_stage_batch(runnable_names, wrapped_nodes, state)
    for name in runnable_names:
        if name in results:
            state = _merge_stage_result(state, results[name])

    # Follow sequential-only signals from parallel results (dedup)
    followed: set[str] = set()
    for name in runnable_names:
        state, _, hop_count = _follow_sequential_signals_dedup(
            name,
            stage_nodes,
            state,
            workflow_config,
            hop_count,
            negotiate_fn,
            followed,
        )

    # Execute convergence stage once after all branches
    if converge and isinstance(converge, dict):
        state, hop_count = _execute_convergence(
            converge,
            runnable_names,
            stage_nodes,
            state,
            workflow_config,
            hop_count,
            negotiate_fn,
        )

    return state, hop_count


def _dedup_targets(
    targets: list[dict[str, Any]],
    stage_nodes: dict[str, Callable],
) -> list[dict[str, Any]]:
    """Deduplicate targets and filter to available stage nodes."""
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for t in targets:
        name = t["name"]
        if name in stage_nodes and name not in seen:
            seen.add(name)
            deduped.append(t)
    return deduped


def _execute_convergence(
    converge: dict[str, Any],
    branch_names: list[str],
    stage_nodes: dict[str, Callable],
    state: dict[str, Any],
    workflow_config: dict[str, Any],
    hop_count: int,
    negotiate_fn: NegotiateFn,
) -> tuple[dict[str, Any], int]:
    """Execute convergence stage after all parallel branches complete.

    Records ``_convergence_predecessors`` so PredecessorResolver knows
    which branches fed into the convergence stage.

    Returns:
        Tuple of (state, hop_count)
    """
    conv_name = converge["name"]
    if conv_name not in stage_nodes:
        logger.warning(
            "Convergence stage '%s' not found in stage nodes; skipping",
            conv_name,
        )
        return state, hop_count

    if hop_count >= DEFAULT_MAX_DYNAMIC_HOPS:
        return state, hop_count

    hop_count += 1
    logger.info(
        "Dynamic convergence: %s → '%s' (hop %d/%d)",
        branch_names,
        conv_name,
        hop_count,
        DEFAULT_MAX_DYNAMIC_HOPS,
    )

    # Record convergence predecessors for PredecessorResolver
    conv_preds = dict(state.get("_convergence_predecessors", {}))
    conv_preds[conv_name] = list(branch_names)
    state["_convergence_predecessors"] = conv_preds

    # Inject convergence input_map if specified
    conv_input_map = converge.get("input_map")
    if conv_input_map:
        state["_stage_input_map"] = conv_input_map

    state = negotiate_fn(conv_name, stage_nodes, state, workflow_config)

    # Clean up convergence input_map
    state.pop("_stage_input_map", None)

    return state, hop_count


def _follow_sequential_signals_from(
    stage_name: str,
    stage_nodes: dict[str, Callable],
    state: dict[str, Any],
    workflow_config: dict[str, Any],
    hop_count: int,
    negotiate_fn: NegotiateFn,
) -> tuple[dict[str, Any], str, int]:
    """Follow sequential-only signals from a completed stage.

    Used after parallel fan-out to prevent exponential fan-out.

    Returns:
        Tuple of (state, last_stage, hop_count)
    """
    sub_signal = _extract_next_stage_signal(stage_name, state)
    if sub_signal is None or sub_signal["mode"] != "sequential":
        return state, stage_name, hop_count
    return _follow_sequential_targets(
        sub_signal["targets"],
        stage_nodes,
        state,
        workflow_config,
        stage_name,
        hop_count,
        negotiate_fn,
    )


def _follow_sequential_signals_dedup(
    stage_name: str,
    stage_nodes: dict[str, Callable],
    state: dict[str, Any],
    workflow_config: dict[str, Any],
    hop_count: int,
    negotiate_fn: NegotiateFn,
    followed: set,
) -> tuple[dict[str, Any], str, int]:
    """Follow sequential signals with dedup tracking.

    Same as ``_follow_sequential_signals_from`` but skips targets
    already in ``followed`` set, preventing the same convergence
    target from executing multiple times.

    Returns:
        Tuple of (state, last_stage, hop_count)
    """
    sub_signal = _extract_next_stage_signal(stage_name, state)
    if sub_signal is None or sub_signal["mode"] != "sequential":
        return state, stage_name, hop_count

    # Filter out already-followed targets
    deduped = [t for t in sub_signal["targets"] if t["name"] not in followed]
    if not deduped:
        return state, stage_name, hop_count

    for t in deduped:
        followed.add(t["name"])

    return _follow_sequential_targets(
        deduped,
        stage_nodes,
        state,
        workflow_config,
        stage_name,
        hop_count,
        negotiate_fn,
    )
