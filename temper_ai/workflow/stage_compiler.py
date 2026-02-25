"""Stage compiler for LangGraph workflow graphs.

Handles compilation of stage configurations into executable LangGraph StateGraph.
Supports sequential, conditional, and loop-back stage execution patterns via
LangGraph's native ``add_conditional_edges``.

Canonical location: ``temper_ai.workflow.stage_compiler``
(moved from ``temper_ai.stage.stage_compiler`` to break stage→workflow circular dep).
Re-exported from ``temper_ai.stage.stage_compiler`` for backward compatibility.
"""

import logging
from collections.abc import Hashable
from typing import Any, cast

from langgraph.graph import END, START, StateGraph
from langgraph.pregel import Pregel

from temper_ai.stage.executors.state_keys import StateKeys
from temper_ai.workflow.condition_evaluator import ConditionEvaluator
from temper_ai.workflow.dag_builder import (
    build_stage_dag,
    compute_depths,
    has_dag_dependencies,
)
from temper_ai.workflow.langgraph_state import LangGraphWorkflowState
from temper_ai.workflow.node_builder import NodeBuilder
from temper_ai.workflow.routing_functions import (
    _ref_attr,
    create_conditional_router,
    create_loop_router,
)
from temper_ai.workflow.state_manager import create_init_node

logger = logging.getLogger(__name__)

LOOP_GATE_PREFIX = "_loop_gate_"


def _build_ref_lookup(stage_refs: list[Any]) -> dict[str, Any]:  # noqa: god
    """Build a lookup dict from stage name to stage reference."""
    lookup: dict[str, Any] = {}
    for ref in stage_refs:
        if isinstance(ref, str):
            continue
        name = ref.get("name") if isinstance(ref, dict) else getattr(ref, "name", None)
        if name:
            lookup[name] = ref
    return lookup


class StageCompiler:
    """Compiles stage configurations into LangGraph StateGraph.

    Handles the LangGraph-specific graph construction logic:
    - Creating StateGraph instances
    - Adding initialization nodes
    - Adding stage execution nodes
    - Connecting nodes with edges (sequential, conditional, loop)
    - Setting entry points
    - Compiling graphs

    Example:
        >>> evaluator = ConditionEvaluator()
        >>> stage_compiler = StageCompiler(node_builder, evaluator)
        >>> graph = stage_compiler.compile_stages(stage_names, workflow_config)
    """

    def __init__(
        self,
        node_builder: NodeBuilder,
        condition_evaluator: ConditionEvaluator | None = None,
    ) -> None:
        """Initialize stage compiler.

        Args:
            node_builder: NodeBuilder for creating stage execution nodes
            condition_evaluator: Evaluator for conditional/loop expressions
                               (default: creates new ConditionEvaluator)
        """
        self.node_builder = node_builder
        self.condition_evaluator = condition_evaluator or ConditionEvaluator()

    def compile_stages(
        self,
        stage_names: list[str],
        workflow_config: dict[str, Any],
    ) -> Pregel[Any, Any]:
        """Compile stage names into executable LangGraph StateGraph.

        Args:
            stage_names: List of stage names in execution order
            workflow_config: Full workflow configuration for node creation

        Returns:
            Compiled LangGraph StateGraph ready for execution

        Raises:
            ValueError: If stage_names is empty
        """
        if not stage_names:
            raise ValueError("Cannot compile workflow with no stages")

        graph: StateGraph[Any] = StateGraph(LangGraphWorkflowState)

        # Add initialization node
        init_node = create_init_node()
        graph.add_node("init", init_node)  # type: ignore

        # Build ref lookup for trigger/on_complete detection
        stage_refs = self._get_stage_refs(workflow_config)
        ref_lookup = self._build_ref_lookup(stage_refs)

        # Add execution node for each stage
        for stage_name in stage_names:
            stage_node = self.node_builder.create_stage_node(
                stage_name,
                workflow_config,
            )
            stage_ref = ref_lookup.get(stage_name)
            stage_node = _maybe_wrap_trigger_node(stage_name, stage_node, stage_ref)
            stage_node = _maybe_wrap_on_complete_node(stage_name, stage_node, stage_ref)
            graph.add_node(stage_name, stage_node)  # type: ignore

        # Wire DAG into predecessor resolver for context resolution
        dag = build_stage_dag(stage_names, stage_refs)
        self.node_builder.wire_dag_context(dag)

        # Add edges (conditional-aware), may add loop gate nodes
        self._add_edges(graph, stage_names, stage_refs)

        graph.set_entry_point("init")
        return graph.compile()

    def _get_stage_refs(
        self,
        workflow_config: dict[str, Any],
    ) -> list[Any]:
        """Extract WorkflowStageReference list from workflow config."""
        workflow = workflow_config.get("workflow", workflow_config)
        return cast(list[Any], workflow.get("stages", []))

    def _add_edges(
        self,
        graph: StateGraph[Any],
        stage_names: list[str],
        stage_refs: list[Any],
    ) -> None:
        """Add edges to the graph, dispatching to DAG or sequential mode."""
        if has_dag_dependencies(stage_refs):
            self._add_dag_edges(graph, stage_names, stage_refs)
        else:
            self._add_sequential_edges_v2(graph, stage_names, stage_refs)

    def _add_sequential_edges_v2(
        self,
        graph: StateGraph[Any],
        stage_names: list[str],
        stage_refs: list[Any],
    ) -> None:
        """Add edges sequentially (no depends_on). Original _add_edges logic."""
        ref_lookup = self._build_ref_lookup(stage_refs)

        # START -> init
        graph.add_edge(START, "init")

        # init -> first stage
        self._add_init_edge(graph, stage_names, stage_refs, ref_lookup)

        # Stage-to-stage edges
        for i in range(len(stage_names)):
            current_name = stage_names[i]
            current_ref = ref_lookup.get(current_name)
            next_name = stage_names[i + 1] if i + 1 < len(stage_names) else None
            next_ref = ref_lookup.get(next_name) if next_name else None

            if self._add_loop_edge(graph, current_name, current_ref, next_name):
                continue
            if self._add_conditional_edge(
                graph, current_name, next_name, next_ref, i, stage_names, stage_refs
            ):
                continue

            # Simple sequential edge
            graph.add_edge(current_name, next_name or END)

    def _add_dag_edges(
        self,
        graph: StateGraph[Any],
        stage_names: list[str],
        stage_refs: list[Any],
    ) -> None:
        """Add edges using DAG topology from depends_on declarations.

        Stages with the same predecessors fan out in parallel; stages with
        multiple predecessors fan in.  Barrier nodes are inserted to equalize
        branch depths so LangGraph's Pregel model triggers fan-in correctly.
        """
        dag = build_stage_dag(stage_names, stage_refs)
        ref_lookup = self._build_ref_lookup(stage_refs)
        depths = compute_depths(dag)

        # Collect stages with loops_back_to — barriers from these
        # predecessors are skipped because the loop gate controls routing.
        loop_stages: set = set()
        for name, ref in ref_lookup.items():
            if _ref_attr(ref, "loops_back_to"):
                loop_stages.add(name)

        # Insert barrier nodes for asymmetric fan-in
        barrier_edges = _insert_fan_in_barriers(graph, dag, depths, loop_stages)

        # START -> init
        graph.add_edge(START, "init")

        # init -> root stages (fan-out if multiple roots)
        self._add_init_to_roots(graph, dag, ref_lookup, stage_refs)

        # Traverse topo order, add successor edges for each stage
        for stage in dag.topo_order:
            stage_ref = ref_lookup.get(stage)
            successors = dag.successors.get(stage, [])

            # Loop-back stages get special treatment
            if self._add_loop_edge_dag(
                graph,
                stage,
                stage_ref,
                successors,
                dag,
                barrier_edges=barrier_edges,
            ):
                continue

            # Fan-out to successors (or END for terminals)
            self._add_successor_edges(
                graph,
                stage,
                successors,
                ref_lookup,
                dag,
                stage_refs,
                barrier_edges=barrier_edges,
            )

    def _add_init_to_roots(
        self,
        graph: StateGraph[Any],
        dag: Any,
        ref_lookup: dict[str, Any],
        stage_refs: list[Any],
    ) -> None:
        """Add edges from init to DAG root stages.

        If a root stage is conditional, uses conditional edges.
        Multiple roots fan out in parallel from init.
        """
        for root in dag.roots:
            root_ref = ref_lookup.get(root)
            if root_ref and self._is_conditional(root_ref):
                skip_target = self._resolve_skip_target(root, root_ref, dag)
                router = create_conditional_router(
                    root_ref,
                    skip_target,
                    0,
                    stage_refs,
                    self.condition_evaluator,
                )
                graph.add_conditional_edges(
                    "init",
                    router,
                    cast(dict[Hashable, str], _build_path_map(root, skip_target)),
                )
            else:
                graph.add_edge("init", root)

    def _add_successor_edges(
        self,
        graph: StateGraph[Any],
        stage: str,
        successors: list[str],
        ref_lookup: dict[str, Any],
        dag: Any,
        stage_refs: list[Any],
        barrier_edges: dict | None = None,
    ) -> None:
        """Add fan-out edges from a stage to its DAG successors.

        Skips edges that have been replaced by barrier chains (for
        asymmetric fan-in equalization).  Terminal stages connect to END.
        """
        if not successors:
            graph.add_edge(stage, END)
            return

        for succ in successors:
            # Skip edges replaced by barrier chains
            if barrier_edges and (stage, succ) in barrier_edges:
                continue

            succ_ref = ref_lookup.get(succ)
            if succ_ref and self._is_conditional(succ_ref):
                skip_target = self._resolve_skip_target(succ, succ_ref, dag)
                router = create_conditional_router(
                    succ_ref,
                    skip_target,
                    0,
                    stage_refs,
                    self.condition_evaluator,
                )
                graph.add_conditional_edges(
                    stage,
                    router,
                    cast(dict[Hashable, str], _build_path_map(succ, skip_target)),
                )
            else:
                graph.add_edge(stage, succ)

    def _add_loop_edge_dag(
        self,
        graph: StateGraph[Any],
        stage: str,
        stage_ref: Any,
        successors: list[str],
        dag: Any,
        barrier_edges: dict | None = None,
    ) -> bool:
        """Add loop-back edge for a DAG stage with loops_back_to.

        In DAG mode, when the loop exits it fans out to ALL DAG successors
        (not just the first).  This ensures parallel branches downstream
        of the loop stage all execute on exit.

        When barrier nodes exist for fan-in equalization, exit targets are
        remapped to route through the barrier chain instead of directly
        to the successor.

        Returns True if a loop edge was added.
        """
        loops_back_to = _ref_attr(stage_ref, "loops_back_to") if stage_ref else None
        if not loops_back_to:
            return False

        gate_name = f"{LOOP_GATE_PREFIX}{stage}"
        gate_node = _create_loop_gate_node(stage)
        graph.add_node(gate_name, gate_node)
        graph.add_edge(stage, gate_name)

        raw_targets = _filter_reachable_targets(successors, stage, dag)
        exit_targets = _remap_barrier_targets(raw_targets, stage, barrier_edges)

        router = create_loop_router(
            stage_ref,
            exit_targets,
            self.condition_evaluator,
        )
        path_map = _build_loop_path_map_multi(loops_back_to, exit_targets)
        graph.add_conditional_edges(
            gate_name, router, cast(dict[Hashable, str], path_map)
        )
        return True

    @staticmethod
    def _resolve_skip_target(
        stage: str,
        stage_ref: Any,
        dag: Any,
    ) -> str | None:
        """Resolve skip target for a conditional stage in DAG context.

        Uses explicit skip_to if set. Otherwise, skips to the conditional
        stage's own successors so downstream stages still run.
        Falls back to END for terminals.
        """
        skip_to = _ref_attr(stage_ref, "skip_to")
        if skip_to == "end":
            return None  # None maps to END in routing
        if skip_to:
            return cast(str, skip_to)
        # Default: skip to first successor of the conditional stage
        successors = dag.successors.get(stage, [])
        return successors[0] if successors else None

    def _add_init_edge(
        self,
        graph: StateGraph[Any],
        stage_names: list[str],
        stage_refs: list[Any],
        ref_lookup: dict[str, Any],
    ) -> None:
        """Add edge from init to first stage (may be conditional)."""
        first_ref = ref_lookup.get(stage_names[0])
        if first_ref and self._is_conditional(first_ref):
            next_after = stage_names[1] if len(stage_names) > 1 else None
            router = create_conditional_router(
                first_ref,
                next_after,
                0,
                stage_refs,
                self.condition_evaluator,
            )
            graph.add_conditional_edges(
                "init",
                router,
                cast(dict[Hashable, str], _build_path_map(stage_names[0], next_after)),
            )
        else:
            graph.add_edge("init", stage_names[0])

    def _add_loop_edge(
        self,
        graph: StateGraph[Any],
        current_name: str,
        current_ref: Any,
        next_name: str | None,
    ) -> bool:
        """Add loop-back edge if current stage has loops_back_to.

        Inserts a loop gate node between the stage and the routing decision.
        The gate node increments the loop counter (as a proper LangGraph node
        returning state updates), then the routing function reads the counter.

        Returns True if a loop edge was added.
        """
        loops_back_to = _ref_attr(current_ref, "loops_back_to") if current_ref else None
        if not loops_back_to:
            return False

        # Add loop gate node that increments counter
        gate_name = f"{LOOP_GATE_PREFIX}{current_name}"
        gate_node = _create_loop_gate_node(current_name)
        graph.add_node(gate_name, gate_node)

        # current_stage -> gate_node -> [loop_router] -> target/exit
        graph.add_edge(current_name, gate_name)

        router = create_loop_router(
            current_ref,
            next_name,
            self.condition_evaluator,
        )
        path_map = _build_loop_path_map(loops_back_to, next_name)
        graph.add_conditional_edges(
            gate_name, router, cast(dict[Hashable, str], path_map)
        )
        return True

    def _add_conditional_edge(
        self,
        graph: StateGraph[Any],
        current_name: str,
        next_name: str | None,
        next_ref: Any,
        i: int,
        stage_names: list[str],
        stage_refs: list[Any],
    ) -> bool:
        """Add conditional edge if next stage is conditional.

        Returns True if a conditional edge was added.
        """
        if not (next_ref and self._is_conditional(next_ref)):
            return False

        next_index = i + 1
        # Use skip_to if specified, otherwise default to stage after next
        skip_to = _ref_attr(next_ref, "skip_to") if next_ref else None
        if skip_to == "end":
            after_next = None  # None maps to END in routing
        else:
            after_next = skip_to or (
                stage_names[next_index + 1]
                if next_index + 1 < len(stage_names)
                else None
            )
        router = create_conditional_router(
            next_ref,
            after_next,
            next_index,
            stage_refs,
            self.condition_evaluator,
        )
        # next_name is guaranteed non-None because next_ref is non-None (from guard on line 405)
        if next_name is None:
            raise ValueError("next_name must not be None when next_ref is set")
        graph.add_conditional_edges(
            current_name,
            router,
            cast(dict[Hashable, str], _build_path_map(next_name, after_next)),
        )
        return True

    @staticmethod
    def _build_ref_lookup(stage_refs: list[Any]) -> dict[str, Any]:
        """Build a lookup dict from stage name to stage reference."""
        return _build_ref_lookup(stage_refs)

    @staticmethod
    def _is_conditional(stage_ref: Any) -> bool:
        """Check if a stage reference has conditional execution configured."""
        if isinstance(stage_ref, dict):
            return bool(
                stage_ref.get("conditional")
                or stage_ref.get("condition")
                or stage_ref.get("skip_if")
            )
        return bool(
            getattr(stage_ref, "conditional", False)
            or getattr(stage_ref, "condition", None)
            or getattr(stage_ref, "skip_if", None)
        )

    # Keep _add_sequential_edges for backward compat (used by tests)
    def _add_sequential_edges(
        self,
        graph: StateGraph[Any],
        stage_names: list[str],
    ) -> None:
        """Add sequential edges connecting stages (legacy helper)."""
        graph.add_edge(START, "init")
        graph.add_edge("init", stage_names[0])
        for i in range(len(stage_names) - 1):
            graph.add_edge(stage_names[i], stage_names[i + 1])
        graph.add_edge(stage_names[-1], END)

    def compile_parallel_stages(
        self,
        stage_names: list[str],
        workflow_config: dict[str, Any],
    ) -> Pregel[Any, Any]:
        """Compile stages with parallel execution support (M3+ feature)."""
        return self.compile_stages(stage_names, workflow_config)

    def compile_conditional_stages(
        self,
        stage_names: list[str],
        workflow_config: dict[str, Any],
        _conditions: dict[str, Any],  # noqa: kept for backward compat, unused
    ) -> Pregel[Any, Any]:
        """Compile stages with conditional branching.

        Now delegates to compile_stages which handles conditional edges natively.
        The ``_conditions`` parameter is accepted for backward compatibility but
        is not used — conditional edges are resolved from stage refs in compile_stages.
        """
        return self.compile_stages(stage_names, workflow_config)


def _create_loop_gate_node(stage_name: str) -> Any:
    """Create a loop gate node that increments the loop counter.

    LangGraph routing functions cannot mutate state. This node runs between
    the loop stage and the routing decision, incrementing the counter as a
    proper node that returns state updates.

    Args:
        stage_name: Name of the stage this gate tracks

    Returns:
        Callable node function for LangGraph
    """
    key = StateKeys.STAGE_LOOP_COUNTS

    def _gate(state: Any) -> dict[str, Any]:
        if isinstance(state, dict):
            counts = dict(state.get(key, {}))
        elif hasattr(state, key):
            counts = dict(getattr(state, key) or {})
        else:
            counts = {}
        counts[stage_name] = counts.get(stage_name, 0) + 1
        return {key: counts}

    return _gate


def _build_path_map(
    stage_name: str,
    skip_target: str | None,
) -> dict[str, str]:
    """Build path map for conditional edges."""
    path_map = {stage_name: stage_name}
    target = skip_target or END
    path_map[target] = target
    return path_map


def _build_loop_path_map(
    loop_target: str,
    exit_target: str | None,
) -> dict[str, str]:
    """Build path map for loop-back edges (single exit target)."""
    path_map = {loop_target: loop_target}
    target = exit_target or END
    path_map[target] = target
    return path_map


def _build_loop_path_map_multi(
    loop_target: str,
    exit_targets: list[str | None],
) -> dict[str, str]:
    """Build path map for loop-back edges with multiple exit targets.

    When a loop gate has multiple DAG successors, the exit path
    fans out to all of them.  The router returns a list of targets.

    Args:
        loop_target: Stage to loop back to
        exit_targets: List of successor stages (or [None] for END)

    Returns:
        Path map covering loop target and all exit targets
    """
    path_map: dict[str, str] = {loop_target: loop_target}
    for target in exit_targets:
        resolved = target or END
        path_map[resolved] = resolved
    # Key for the list-return case (LangGraph uses individual entries)
    return path_map


def _filter_reachable_targets(
    successors: list[str],
    stage: str,
    dag: Any,
) -> "list[str | None]":
    """Filter out successors reachable via another exit target to prevent double-fire."""
    raw_targets: list[str | None] = list(successors) if successors else [None]
    if len(raw_targets) <= 1:
        return raw_targets

    target_set = {t for t in raw_targets if t}
    filtered: list[str | None] = []
    for target in raw_targets:
        if target is None:
            filtered.append(target)
            continue
        other_preds = set(dag.predecessors.get(target, []))
        other_preds.discard(stage)
        if other_preds & target_set:
            continue
        filtered.append(target)
    return filtered if filtered else raw_targets


def _remap_barrier_targets(
    raw_targets: "list[str | None]",
    stage: str,
    barrier_edges: dict | None,
) -> "list[str | None]":
    """Remap targets to barrier entry points for fan-in equalization."""
    exit_targets: list[str | None] = []
    for target in raw_targets:
        if target and barrier_edges and (stage, target) in barrier_edges:
            barrier_entry = f"{BARRIER_PREFIX}{stage}_to_{target}_0"
            exit_targets.append(barrier_entry)
        else:
            exit_targets.append(target)
    return exit_targets


BARRIER_PREFIX = "_barrier_"


def _passthrough_node(_state: Any) -> dict[str, Any]:
    """Barrier node that passes through without state modifications.

    Used to equalize parallel branch depths for correct fan-in.
    """
    return {}


def _insert_fan_in_barriers(
    graph: Any,
    dag: Any,
    depths: dict[str, int],
    loop_stages: set | None = None,
) -> dict:
    """Insert pass-through barrier nodes for asymmetric fan-in.

    LangGraph's Pregel model triggers a node when ANY incoming edge fires.
    For fan-in nodes with predecessors at different depths, the node triggers
    from the shallowest predecessor before deeper ones complete.

    This function inserts barrier chains on shallow edges to equalize depths,
    ensuring all predecessors complete in the same superstep.

    Predecessors that are loop stages are skipped — their loop gate controls
    whether successors fire, so a direct barrier edge would bypass the gate
    and cause double-execution of the fan-in target.

    Args:
        graph: StateGraph being built
        dag: StageDAG with predecessors
        depths: Stage depth map from compute_depths()
        loop_stages: Set of stage names with loops_back_to (skip barriers)

    Returns:
        Dict mapping (pred, target) to True for edges replaced by barriers
    """
    barrier_edges: dict = {}

    for stage in dag.topo_order:
        preds = dag.predecessors.get(stage, [])
        if len(preds) < 2:
            continue

        max_pred_depth = max(depths[p] for p in preds)

        for pred in preds:
            # Skip barriers from loop stages — the loop gate handles
            # routing to successors; a direct barrier edge would fire
            # on every iteration, bypassing the gate.
            if loop_stages and pred in loop_stages:
                continue

            depth_diff = max_pred_depth - depths[pred]
            if depth_diff == 0:
                continue

            # Insert chain of barrier nodes on the short edge
            prev = pred
            for k in range(depth_diff):
                barrier_name = f"{BARRIER_PREFIX}{pred}_to_{stage}_{k}"
                graph.add_node(barrier_name, _passthrough_node)
                graph.add_edge(prev, barrier_name)
                prev = barrier_name

            # Last barrier connects to the fan-in target
            graph.add_edge(prev, stage)
            barrier_edges[(pred, stage)] = True
            logger.debug(
                "Inserted %d barrier(s) on edge %s → %s",
                depth_diff,
                pred,
                stage,
            )

    return barrier_edges


def _get_trigger_config(stage_ref: Any) -> Any:
    """Extract trigger config from a stage reference (dict or Pydantic model)."""
    if stage_ref is None:
        return None
    if isinstance(stage_ref, dict):
        return stage_ref.get("trigger")
    return getattr(stage_ref, "trigger", None)


def _get_on_complete_config(stage_ref: Any) -> Any:
    """Extract on_complete config from a stage reference."""
    if stage_ref is None:
        return None
    if isinstance(stage_ref, dict):
        return stage_ref.get("on_complete")
    return getattr(stage_ref, "on_complete", None)


def _get_event_bus_from_workflow(workflow_config: dict[str, Any]) -> Any:
    """Extract event bus from workflow config options, if enabled."""
    wf = workflow_config.get("workflow", {})
    config = wf.get("config", {}) if isinstance(wf, dict) else {}
    if isinstance(config, dict):
        event_bus_cfg = config.get("event_bus")
    else:
        event_bus_cfg = getattr(config, "event_bus", None)
    if event_bus_cfg is None:
        return None
    enabled = (
        event_bus_cfg.get("enabled", False)
        if isinstance(event_bus_cfg, dict)
        else getattr(event_bus_cfg, "enabled", False)
    )
    if not enabled:
        return None
    persist = (
        event_bus_cfg.get("persist_events", True)
        if isinstance(event_bus_cfg, dict)
        else getattr(event_bus_cfg, "persist_events", True)
    )
    from temper_ai.events.event_bus import TemperEventBus

    return TemperEventBus(persist=persist)


def _maybe_wrap_trigger_node(
    stage_name: str,
    node_fn: Any,
    stage_ref: Any,
) -> Any:
    """Wrap node_fn with event trigger if the stage has a trigger config."""
    trigger_config = _get_trigger_config(stage_ref)
    if trigger_config is None:
        return node_fn

    from temper_ai.workflow.node_builder import create_event_triggered_node

    def _node_with_event_bus(state: Any) -> Any:
        event_bus = state.get("event_bus") if isinstance(state, dict) else None
        wrapped = create_event_triggered_node(
            stage_name=stage_name,
            inner_node_fn=node_fn,
            event_bus=event_bus,
            trigger_config=trigger_config,
        )
        return wrapped(state)

    return _node_with_event_bus


def _maybe_wrap_on_complete_node(
    stage_name: str,
    node_fn: Any,
    stage_ref: Any,
) -> Any:
    """Wrap node_fn to emit an event on completion if on_complete is configured."""
    on_complete_config = _get_on_complete_config(stage_ref)
    if on_complete_config is None:
        return node_fn

    def _node_with_on_complete(state: Any) -> Any:
        result = node_fn(state)
        event_bus = (result.get("event_bus") if isinstance(result, dict) else None) or (
            state.get("event_bus") if isinstance(state, dict) else None
        )
        if event_bus is None:
            return result

        event_type = (
            on_complete_config.get("event_type")
            if isinstance(on_complete_config, dict)
            else getattr(on_complete_config, "event_type", None)
        )
        include_output = (
            on_complete_config.get("include_output", False)
            if isinstance(on_complete_config, dict)
            else getattr(on_complete_config, "include_output", False)
        )
        payload: dict[str, Any] = {"stage_name": stage_name}
        if include_output and isinstance(result, dict):
            stage_outputs = result.get("stage_outputs", {})
            payload["output"] = stage_outputs.get(stage_name)

        workflow_id = state.get("workflow_id") if isinstance(state, dict) else None
        try:
            event_bus.emit(
                event_type=event_type,
                payload=payload,
                source_workflow_id=workflow_id,
                source_stage_name=stage_name,
            )
        except Exception as exc:
            logger.warning(
                "on_complete event emit failed for stage '%s': %s", stage_name, exc
            )
        return result

    return _node_with_on_complete
