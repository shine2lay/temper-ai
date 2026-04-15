"""Graph executor — iterates nodes in topological order, evaluates conditions,
handles loops, resolves inputs, and calls node.run(). Independent nodes at
the same topological level run concurrently via ThreadPoolExecutor.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from temper_ai.observability.event_types import EventType
from temper_ai.shared.types import ExecutionContext, NodeResult, Status
from temper_ai.stage.conditions import evaluate_condition
from temper_ai.stage.exceptions import CancellationError, CyclicDependencyError
from temper_ai.stage.node import Node

logger = logging.getLogger(__name__)

def execute_graph_with_state(
    nodes: list[Node],
    input_data: dict,
    context: ExecutionContext,
    graph_name: str = "",
    is_workflow: bool = False,
    initial_outputs: dict[str, NodeResult] | None = None,
) -> NodeResult:
    """Execute a graph with pre-populated node_outputs (for resume from checkpoints)."""
    return execute_graph(
        nodes, input_data, context,
        graph_name=graph_name, is_workflow=is_workflow,
        initial_outputs=initial_outputs,
    )


def execute_graph(
    nodes: list[Node],
    input_data: dict,
    context: ExecutionContext,
    graph_name: str = "",
    is_workflow: bool = False,
    initial_outputs: dict[str, NodeResult] | None = None,
    workflow_outputs: dict[str, str] | None = None,
) -> NodeResult:
    """Execute a graph of nodes in topological order, concurrently where possible."""
    start_event = EventType.WORKFLOW_STARTED if is_workflow else EventType.STAGE_STARTED
    node_map = {node.name: node for node in nodes}
    batches = topological_sort(nodes)
    node_outputs: dict[str, NodeResult] = dict(initial_outputs) if initial_outputs else {}
    loop_counts: dict[str, int] = defaultdict(int)
    start = time.monotonic()

    graph_event_id = context.event_recorder.record(
        start_event,
        data={"name": graph_name, "node_count": len(nodes)},
        parent_id=context.parent_event_id if not is_workflow else None,
        execution_id=context.run_id,
        status="running",
    )

    # Store graph event ID on context so Delegate tool can parent child nodes to the DAG
    context.graph_event_id = graph_event_id

    try:
        _run_batches(batches, node_map, input_data, node_outputs, loop_counts, context, graph_event_id)
        return _build_final_result(nodes, node_outputs, input_data, start, graph_event_id, context, workflow_outputs)

    except Exception as exc:
        duration = time.monotonic() - start
        context.event_recorder.update_event(
            graph_event_id,
            status="failed",
            data={"error": str(exc), "duration_seconds": duration},
        )
        return NodeResult(
            status=Status.FAILED,
            error=str(exc),
            agent_results=[r for nr in node_outputs.values() for r in nr.agent_results],
            node_results=node_outputs,
            duration_seconds=duration,
        )

def _run_batches(
    batches: list[list[Node]],
    node_map: dict[str, Node],
    input_data: dict,
    node_outputs: dict[str, NodeResult],
    loop_counts: dict[str, int],
    context: ExecutionContext,
    graph_event_id: str,
) -> None:
    """Iterate through topological batches, handling single-node loops and parallel execution."""
    batch_idx = 0
    loop_feedback: dict[str, NodeResult] = {}
    cp = context.checkpoint_service  # may be None

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
            result = _execute_single_node(node, input_data, node_outputs, context, graph_event_id, loop_feedback)
            # Handle dynamic spawning if the node produced _spawn
            node_outputs[node.name] = result
            if cp:
                cp.save_node_completed(node.name, result)
            rewind = _handle_loop(node, result, node_outputs, loop_counts, loop_feedback, batches, node_map, cp)
            if rewind is not None:
                batch_idx = rewind
                continue
        else:
            # For parallel batches, only run nodes not already checkpointed
            results = _execute_parallel_batch(remaining, input_data, node_outputs, context, graph_event_id, loop_feedback)
            for node, result in results:
                node_outputs[node.name] = result
                if cp:
                    cp.save_node_completed(node.name, result)
        batch_idx += 1

def _build_final_result(
    nodes: list[Node],
    node_outputs: dict[str, NodeResult],
    input_data: dict,
    start: float,
    graph_event_id: str,
    context: ExecutionContext,
    workflow_outputs: dict[str, str] | None = None,
) -> NodeResult:
    """Assemble the final NodeResult after all batches complete successfully."""
    # Rebuild from final outputs to avoid duplicates from loop reruns
    all_agent_results = [
        r for node in nodes
        for r in (node_outputs[node.name].agent_results if node.name in node_outputs else [])
    ]

    duration = time.monotonic() - start
    total_cost = sum(r.cost_usd for r in node_outputs.values())
    total_tokens = sum(r.total_tokens for r in node_outputs.values())
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
    if resolved_outputs:
        event_data["workflow_output"] = resolved_outputs

    context.event_recorder.update_event(
        graph_event_id,
        status="completed",
        data=event_data,
    )

    # Use workflow outputs as structured_output if available, otherwise fall back to last node
    final_structured = resolved_outputs if resolved_outputs else (
        last_output.structured_output if last_output else None
    )

    return NodeResult(
        status=Status.COMPLETED,
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
        agent_event_id = recorder.record(
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
) -> NodeResult:
    """Execute one node with condition checking and input resolution."""
    skip = _check_dependency_failures(node, node_outputs)
    if skip is not None:
        _record_skipped_node(node, context, parent_event_id, skip.error or "dependency failed")
        return skip

    if node.condition:
        try:
            if not evaluate_condition(node.condition, node_outputs):
                logger.info("Node '%s' skipped — condition not met", node.name)
                result = NodeResult(status=Status.SKIPPED)
                _record_skipped_node(node, context, parent_event_id, "condition not met")
                return result
        except Exception as exc:
            logger.warning("Condition evaluation failed for '%s': %s", node.name, exc)
            result = NodeResult(status=Status.SKIPPED, error=str(exc))
            _record_skipped_node(node, context, parent_event_id, str(exc))
            return result

    resolved = _resolve_inputs(node, input_data, node_outputs, loop_feedback)
    resolved = _inject_strategy_context(node, resolved, node_outputs)

    # Gate: pause and wait for human approval before executing
    if node.config.gate:
        _wait_for_gate(node, context, parent_event_id)

    node_event_id = context.event_recorder.record(
        EventType.STAGE_STARTED,
        data=_build_node_event_data(node),
        parent_id=parent_event_id,
        execution_id=context.run_id,
        status="running",
    )

    return _run_node_with_events(node, resolved, context, node_event_id)


def _check_dependency_failures(
    node: Node,
    node_outputs: dict[str, NodeResult],
) -> NodeResult | None:
    """Return a SKIPPED NodeResult if any dependency failed or was skipped, else None."""
    for dep_name in node.depends_on:
        dep_result = node_outputs.get(dep_name)
        if dep_result and dep_result.status == Status.FAILED:
            logger.warning("Node '%s' skipped — dependency '%s' failed", node.name, dep_name)
            return NodeResult(status=Status.SKIPPED, error=f"Dependency '{dep_name}' failed")
        if dep_result and dep_result.status == Status.SKIPPED:
            # Don't cascade skip when the dependency (or its ancestor) was
            # intentionally skipped via a condition. Only cascade when the
            # skip was caused by an actual failure upstream.
            skip_reason = dep_result.error or ""
            if "failed" in skip_reason:
                logger.warning("Node '%s' skipped — dependency '%s' was skipped due to failure", node.name, dep_name)
                return NodeResult(status=Status.SKIPPED, error=f"Dependency '{dep_name}' was skipped")
            # Condition-based skip or cascade from condition skip — proceed
            logger.info("Node '%s' — dependency '%s' was conditionally skipped, proceeding", node.name, dep_name)
            continue
    return None


def _record_skipped_node(
    node: Node,
    context: ExecutionContext,
    parent_event_id: str,
    reason: str,
) -> None:
    """Record a stage event for a skipped node so the DAG can show it."""
    context.event_recorder.record(
        EventType.STAGE_STARTED,
        data={**_build_node_event_data(node), "skip_reason": reason},
        parent_id=parent_event_id,
        execution_id=context.run_id,
        status="skipped",
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
) -> NodeResult:
    """Run a node and record completed/failed events around it.

    Enforces per-node timeout if configured via node.config.timeout_seconds.
    """
    from dataclasses import replace as dc_replace
    node_context = dc_replace(
        context,
        parent_event_id=node_event_id,
        skip_policies=node.config.skip_policies,
    )

    timeout = node.config.timeout_seconds
    start = time.monotonic()
    try:
        if timeout:
            result = _run_with_timeout(node, resolved, node_context, timeout)
        else:
            result = node.run(resolved, node_context)
        duration = time.monotonic() - start
        result.duration_seconds = duration
        context.event_recorder.update_event(
            node_event_id,
            status=result.status.value,
            data={"cost_usd": result.cost_usd, "total_tokens": result.total_tokens, "duration_seconds": duration},
        )
        return result

    except Exception as exc:
        duration = time.monotonic() - start
        context.event_recorder.update_event(
            node_event_id,
            status="failed",
            data={"error": str(exc), "duration_seconds": duration},
        )
        return NodeResult(status=Status.FAILED, error=str(exc), duration_seconds=duration)


def _run_with_timeout(node: Node, resolved: dict, context: ExecutionContext, timeout: int) -> NodeResult:
    """Run a node with a wall-clock timeout. Returns FAILED if timeout exceeded."""
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(node.run, resolved, context)
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
) -> list[tuple[Node, NodeResult]]:
    """Execute a batch of independent nodes concurrently."""
    results = []

    with ThreadPoolExecutor(max_workers=len(batch)) as pool:
        future_to_node = {
            pool.submit(
                _execute_single_node, node, input_data, node_outputs,
                context, parent_event_id, loop_feedback
            ): node
            for node in batch
        }
        for future in as_completed(future_to_node):
            node = future_to_node[future]
            try:
                result = future.result()
            except Exception as exc:
                result = NodeResult(status=Status.FAILED, error=str(exc))
            results.append((node, result))

    return results


def _handle_loop(
    node: Node,
    result: NodeResult,
    node_outputs: dict[str, NodeResult],
    loop_counts: dict[str, int],
    loop_feedback: dict[str, NodeResult],
    batches: list[list[Node]],
    node_map: dict[str, Node],
    checkpoint_service: Any = None,
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
        logger.info(
            "Loop %s reached max_loops (%d), stopping",
            loop_key, node.max_loops,
        )
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
                checkpoint_service.save_loop_rewind(
                    trigger_node=node.name,
                    target_node=node.loop_to,
                    cleared_nodes=cleared_nodes,
                    trigger_result=result,
                )
            # Clear outputs for nodes from target onwards (they'll re-run)
            for name in cleared_nodes:
                node_outputs.pop(name, None)
            return idx

    logger.warning("Loop target '%s' not found in graph", node.loop_to)
    return None


def _resolve_inputs(
    node: Node,
    input_data: dict,
    node_outputs: dict[str, NodeResult],
    loop_feedback: dict[str, NodeResult] | None = None,
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

    return {
        local_name: _resolve_single_input(node.name, local_name, source, input_data, effective_outputs)
        for local_name, source in input_map.items()
    }


def _resolve_single_input(
    node_name: str,
    local_name: str,
    source: str,
    input_data: dict,
    node_outputs: dict[str, NodeResult],
) -> Any:
    """Resolve a single input_map entry from its source reference."""
    parts = source.split(".")
    if len(parts) < 2:
        return input_data.get(source)

    source_node = parts[0]
    field = parts[1]

    if source_node in ("workflow", "input"):
        return input_data.get(field)

    if source_node not in node_outputs:
        logger.warning(
            "Node '%s' input_map '%s': source node '%s' has not produced output yet",
            node_name, local_name, source_node,
        )
        return None

    result = node_outputs[source_node]

    if field == "output":
        return result.output
    if field == "status":
        return result.status
    if field == "structured" and len(parts) >= 3:
        if not result.structured_output:
            return None
        value: Any = result.structured_output
        for key in parts[2:]:
            value = value.get(key) if isinstance(value, dict) else None
        return value

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
        "(expected 'output', 'structured', 'status', or a child node name)",
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


def _wait_for_gate(node: Node, context: ExecutionContext, parent_event_id: str) -> None:
    """Pause execution and wait for human approval at a gate node.

    Emits a 'gate.waiting' event, then blocks until the gate is approved
    via the API (which sets the threading.Event) or the workflow is cancelled.
    """
    import threading

    gate_registry = context.gate_registry
    if gate_registry is None:
        logger.warning("Node '%s' has gate=true but no gate_registry on context — skipping gate", node.name)
        return

    gate_key = f"{context.run_id}:{node.name}"
    gate_event = threading.Event()
    gate_registry[gate_key] = gate_event

    # Record waiting event so the UI can show the gate
    context.event_recorder.record(
        EventType.STAGE_STARTED,
        data={**_build_node_event_data(node), "gate": True, "gate_status": "waiting"},
        parent_id=parent_event_id,
        execution_id=context.run_id,
        status="waiting",
    )

    # Save checkpoint before waiting (so the run can resume if server crashes while waiting)
    if context.checkpoint_service:
        from temper_ai.shared.types import NodeResult, Status
        context.checkpoint_service._save(
            event_type="gate_waiting",
            node_name=node.name,
            status="waiting",
        )

    logger.info("Gate: waiting for approval on node '%s' (execution: %s)", node.name, context.run_id)

    # Block until approved or cancelled
    while not gate_event.is_set():
        _check_cancelled(context)
        gate_event.wait(timeout=5.0)  # Check cancellation every 5s

    # Clean up
    gate_registry.pop(gate_key, None)
    logger.info("Gate: node '%s' approved, continuing", node.name)


def _check_cancelled(context: ExecutionContext) -> None:
    """Raise CancellationError if the workflow has been cancelled."""
    if context.cancel_event and context.cancel_event.is_set():
        raise CancellationError("Workflow cancelled by user")


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
