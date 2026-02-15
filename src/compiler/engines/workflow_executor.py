"""Workflow executor — Python-native stage execution loop.

Walks workflow stages as a Python loop respecting DAG order, conditions,
and loops. No compiled graph — just straightforward iteration.

Supports:
- Sequential stage execution (topo order)
- Parallel stage execution (same-depth stages with no mutual dependency)
- Conditional stages (skip_if / condition)
- Loop-back stages (loops_back_to / max_loops / loop_condition)
- Stage-to-stage negotiation (re-run producer on ContextResolutionError)
- Dynamic edge routing (stage declares next stage via _next_stage signal)
"""
import logging
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Dict, List, Optional

from src.compiler.condition_evaluator import (
    ConditionEvaluator,
    get_default_condition,
    get_default_loop_condition,
)
from src.compiler.dag_builder import StageDAG, build_stage_dag, compute_depths
from src.compiler.executors.state_keys import StateKeys
from src.compiler.node_builder import NodeBuilder
from src.compiler.state_manager import StateManager

logger = logging.getLogger(__name__)

# Default limits
DEFAULT_MAX_LOOPS = 2
DEFAULT_MAX_NEGOTIATION_ROUNDS = 2
DEFAULT_MAX_STAGE_PARALLEL_WORKERS = 4
DEFAULT_MAX_DYNAMIC_HOPS = 5


def _ref_attr(ref: Any, attr: str, default: Any = None) -> Any:
    """Get attribute from a stage ref (dict or object)."""
    if isinstance(ref, dict):
        return ref.get(attr, default)
    return getattr(ref, attr, default)


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


def _build_ref_lookup(stage_refs: List[Any]) -> Dict[str, Any]:
    """Build name -> stage reference lookup."""
    lookup: Dict[str, Any] = {}
    for ref in stage_refs:
        if isinstance(ref, str):
            continue
        name = ref.get("name") if isinstance(ref, dict) else getattr(ref, "name", None)
        if name:
            lookup[name] = ref
    return lookup


def _group_by_depth(
    dag: StageDAG, depths: Dict[str, int],
) -> Dict[int, List[str]]:
    """Group stages by their DAG depth for parallel execution."""
    groups: Dict[int, List[str]] = defaultdict(list)
    for stage in dag.topo_order:
        groups[depths[stage]].append(stage)
    return dict(groups)


_NEXT_STAGE_KEY = "_next_stage"


class WorkflowExecutor:
    """Walks workflow stages as a Python loop — no compiled graph.

    The core execution loop that replaces LangGraph's Pregel model for the
    native engine. Walks stages respecting DAG order, evaluates conditions
    and loops, and supports stage-to-stage negotiation.

    Args:
        node_builder: NodeBuilder for creating stage execution callables
        condition_evaluator: ConditionEvaluator for conditional/loop expressions
        state_manager: StateManager for state operations
        negotiation_config: Optional negotiation configuration dict
    """

    def __init__(
        self,
        node_builder: NodeBuilder,
        condition_evaluator: ConditionEvaluator,
        state_manager: StateManager,
        negotiation_config: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.node_builder = node_builder
        self.condition_evaluator = condition_evaluator
        self.state_manager = state_manager
        self._negotiation_config = negotiation_config or {}

    def run(
        self,
        stage_refs: List[Any],
        workflow_config: Dict[str, Any],
        state: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Execute all stages, returning final state.

        1. Build DAG from depends_on declarations
        2. Group stages by depth
        3. Walk depth groups:
           - Single stage at depth: execute directly
           - Multiple stages at depth: execute in parallel
        4. Evaluate conditions, loops, and negotiation at each stage
        5. Return final state

        Args:
            stage_refs: List of stage references from workflow config
            workflow_config: Full workflow configuration
            state: Initial workflow state

        Returns:
            Final workflow state with all stage outputs
        """
        stage_names = [
            self.node_builder.extract_stage_name(ref) for ref in stage_refs
        ]

        # Build DAG and compute depths
        dag = build_stage_dag(stage_names, stage_refs)
        depths = compute_depths(dag)
        depth_groups = _group_by_depth(dag, depths)
        ref_lookup = _build_ref_lookup(stage_refs)

        # Pre-build stage node callables
        stage_nodes: Dict[str, Callable] = {}
        for name in stage_names:
            stage_nodes[name] = self.node_builder.create_stage_node(
                name, workflow_config,
            )

        # Walk depth groups in order
        for depth in sorted(depth_groups):
            if state.get(StateKeys.SKIP_TO_END):
                logger.info(
                    "Workflow halted (skip_to=end from stage '%s'), "
                    "skipping remaining stages",
                    state[StateKeys.SKIP_TO_END],
                )
                break

            stages_at_depth = depth_groups[depth]
            if len(stages_at_depth) == 1:
                state = self._execute_single_stage(
                    stages_at_depth[0], stage_nodes, ref_lookup,
                    stage_refs, state, workflow_config,
                )
            else:
                state = self._execute_parallel_stages(
                    stages_at_depth, stage_nodes, ref_lookup,
                    stage_refs, state, workflow_config,
                )

        return state

    def _execute_single_stage(
        self,
        stage_name: str,
        stage_nodes: Dict[str, Callable],
        ref_lookup: Dict[str, Any],
        stage_refs: List[Any],
        state: Dict[str, Any],
        workflow_config: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Execute a single stage with condition/loop/negotiation support."""
        stage_ref = ref_lookup.get(stage_name)

        # Check skip_if / condition
        if self._should_skip(stage_name, stage_ref, stage_refs, state):
            skip_to = _ref_attr(stage_ref, "skip_to")
            if skip_to == "end":
                logger.info(
                    "Stage '%s' condition not met → skip_to=end, "
                    "halting workflow", stage_name,
                )
                state[StateKeys.SKIP_TO_END] = stage_name
            else:
                logger.info(
                    "Skipping stage '%s' (condition not met)", stage_name,
                )
            return state

        # Execute with loop support
        loops_back_to = _ref_attr(stage_ref, "loops_back_to") if stage_ref else None
        if loops_back_to:
            return self._execute_with_loop(
                stage_name, stage_ref, stage_nodes, ref_lookup,
                stage_refs, state, workflow_config,
            )

        # Execute with dynamic edge routing
        state = self._execute_with_negotiation(
            stage_name, stage_nodes, state, workflow_config,
        )
        return self._follow_dynamic_edges(
            stage_name, stage_nodes, state, workflow_config,
        )

    def _execute_parallel_stages(
        self,
        stage_names: List[str],
        stage_nodes: Dict[str, Callable],
        ref_lookup: Dict[str, Any],
        stage_refs: List[Any],
        state: Dict[str, Any],
        workflow_config: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Execute multiple stages at the same depth in parallel.

        Stages at the same depth with no mutual dependency run concurrently.
        No barrier nodes needed — we explicitly wait for all stages at a depth
        to complete before moving to the next depth.
        """
        # Filter out skipped stages
        runnable = []
        for name in stage_names:
            stage_ref = ref_lookup.get(name)
            if self._should_skip(name, stage_ref, stage_refs, state):
                skip_to = _ref_attr(stage_ref, "skip_to")
                if skip_to == "end":
                    logger.info(
                        "Stage '%s' condition not met → skip_to=end, "
                        "halting workflow", name,
                    )
                    state[StateKeys.SKIP_TO_END] = name
                    return state
                logger.info(
                    "Skipping stage '%s' (condition not met)", name,
                )
                continue
            runnable.append(name)

        if not runnable:
            return state

        if len(runnable) == 1:
            return self._execute_with_negotiation(
                runnable[0], stage_nodes, state, workflow_config,
            )

        results = self._run_parallel_stage_batch(runnable, stage_nodes, state)

        for name in runnable:
            if name in results:
                state = self._merge_stage_result(state, results[name])

        # Process dynamic edges from each parallel stage sequentially
        for name in runnable:
            state = self._follow_dynamic_edges(
                name, stage_nodes, state, workflow_config,
            )

        return state

    def _execute_with_loop(
        self,
        stage_name: str,
        stage_ref: Any,
        stage_nodes: Dict[str, Callable],
        ref_lookup: Dict[str, Any],
        stage_refs: List[Any],
        state: Dict[str, Any],
        workflow_config: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Execute a stage with loop-back support.

        Runs the stage, then checks the loop condition. If met and under
        max_loops, re-runs the loop target stage.
        """
        loop_cfg = self._build_loop_config(stage_ref, stage_name)
        loop_count = 0

        while True:
            state = self._execute_with_negotiation(
                stage_name, stage_nodes, state, workflow_config,
            )
            loop_count += 1
            state = self._update_loop_count(state, stage_name, loop_count)

            should_continue = self._check_loop_continue(
                stage_name, loop_count, loop_cfg, state,
            )
            if not should_continue:
                break

            logger.info(
                "Stage '%s' looping back to '%s' (iteration %d/%d)",
                stage_name, loop_cfg["target"], loop_count, loop_cfg["max"],
            )
            if loop_cfg["target"] in stage_nodes:
                state = self._execute_with_negotiation(
                    loop_cfg["target"], stage_nodes, state, workflow_config,
                )

        return state

    @staticmethod
    def _build_loop_config(stage_ref: Any, stage_name: str) -> Dict[str, Any]:
        """Extract loop configuration from stage reference."""
        return {
            "max": _ref_attr(stage_ref, "max_loops", DEFAULT_MAX_LOOPS),
            "target": _ref_attr(stage_ref, "loops_back_to"),
            "condition": (
                _ref_attr(stage_ref, "loop_condition")
                or _ref_attr(stage_ref, "condition")
                or get_default_loop_condition(stage_name)
            ),
        }

    @staticmethod
    def _update_loop_count(
        state: Dict[str, Any], stage_name: str, count: int,
    ) -> Dict[str, Any]:
        """Update loop count in state."""
        loop_counts = dict(state.get(StateKeys.STAGE_LOOP_COUNTS, {}))
        loop_counts[stage_name] = count
        state[StateKeys.STAGE_LOOP_COUNTS] = loop_counts
        return state

    def _check_loop_continue(
        self, stage_name: str, loop_count: int,
        loop_cfg: Dict[str, Any], state: Dict[str, Any],
    ) -> bool:
        """Check if loop should continue. Returns False to exit."""
        if loop_count > loop_cfg["max"]:
            logger.info(
                "Stage '%s' reached max loops (%d), exiting",
                stage_name, loop_cfg["max"],
            )
            return False
        if not self.condition_evaluator.evaluate(loop_cfg["condition"], state):
            logger.info("Stage '%s' loop condition not met, proceeding", stage_name)
            return False
        return True

    def _execute_with_negotiation(
        self,
        stage_name: str,
        stage_nodes: Dict[str, Callable],
        state: Dict[str, Any],
        workflow_config: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Execute a stage with negotiation support.

        When ContextResolutionError is raised for a required input,
        identifies the producer stage and re-runs it with feedback context.
        """
        from src.compiler.context_provider import ContextResolutionError

        negotiation_enabled = self._negotiation_config.get("enabled", False)
        max_rounds = self._negotiation_config.get(
            "max_stage_rounds", DEFAULT_MAX_NEGOTIATION_ROUNDS,
        )

        last_error: Optional[ContextResolutionError] = None
        for attempt in range(max_rounds + 1):
            try:
                result = self._run_stage_node(
                    stage_name, stage_nodes[stage_name], state,
                )
                return self._merge_stage_result(state, result)
            except ContextResolutionError as exc:
                if not negotiation_enabled or attempt >= max_rounds:
                    raise
                last_error = exc
                state = self._negotiate_with_producer(
                    exc, stage_name, stage_nodes, state,
                )

        # Exhausted all negotiation rounds without success
        if last_error is not None:
            raise last_error
        return state

    def _negotiate_with_producer(
        self,
        exc: Any,
        stage_name: str,
        stage_nodes: Dict[str, Callable],
        state: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Re-run producer stage with feedback after ContextResolutionError."""
        # Source format: "producer_stage.field_name"
        producer = exc.source.split(".")[0]
        logger.info(
            "Negotiation: stage '%s' missing input '%s' from producer '%s'",
            stage_name, exc.input_name, producer,
        )

        if producer not in stage_nodes:
            logger.warning(
                "Negotiation: producer '%s' not found in stage nodes", producer,
            )
            return state

        feedback = {
            "consumer_stage": stage_name,
            "missing_input": exc.input_name,
            "consumer_output": state.get(StateKeys.STAGE_OUTPUTS, {}).get(stage_name),
        }
        state["_negotiation_feedback"] = feedback
        producer_result = self._run_stage_node(
            producer, stage_nodes[producer], state,
        )
        state = self._merge_stage_result(state, producer_result)
        state.pop("_negotiation_feedback", None)
        return state

    def _should_skip(
        self,
        stage_name: str,
        stage_ref: Any,
        stage_refs: List[Any],
        state: Dict[str, Any],
    ) -> bool:
        """Check if a stage should be skipped based on conditions."""
        if not stage_ref or not _is_conditional(stage_ref):
            return False

        skip_if = _ref_attr(stage_ref, "skip_if")
        condition = _ref_attr(stage_ref, "condition")

        if skip_if:
            return self.condition_evaluator.evaluate(skip_if, state)

        if condition:
            return not self.condition_evaluator.evaluate(condition, state)

        # Default condition: previous stage failed/degraded → execute
        stage_names = [
            self.node_builder.extract_stage_name(ref) for ref in stage_refs
        ]
        try:
            stage_index = stage_names.index(stage_name)
        except ValueError:
            return False

        default_cond = get_default_condition(stage_index, stage_refs)
        if default_cond:
            return not self.condition_evaluator.evaluate(default_cond, state)

        return False

    @staticmethod
    def _extract_next_stage_signal(
        stage_name: str,
        state: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """Extract _next_stage signal from a stage's output.

        Checks two sources in priority order:
        1. Top-level ``_next_stage`` dict in stage output
        2. ``structured`` compartment

        Returns:
            Dict with ``name`` (str) and ``inputs`` (dict), or None.
        """
        stage_data = state.get(StateKeys.STAGE_OUTPUTS, {}).get(
            stage_name, {},
        )
        if not isinstance(stage_data, dict):
            return None

        # 1. Top-level dict signal
        signal = stage_data.get(_NEXT_STAGE_KEY)
        if isinstance(signal, dict) and signal.get("name"):
            return {"name": signal["name"], "inputs": signal.get("inputs", {})}

        # 2. Structured compartment
        structured = stage_data.get("structured", {})
        if isinstance(structured, dict):
            signal = structured.get(_NEXT_STAGE_KEY)
            if isinstance(signal, dict) and signal.get("name"):
                return {"name": signal["name"], "inputs": signal.get("inputs", {})}

        return None

    def _follow_dynamic_edges(
        self,
        stage_name: str,
        stage_nodes: Dict[str, Callable],
        state: Dict[str, Any],
        workflow_config: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Follow dynamic edge signals after a stage completes.

        If the completed stage declared ``_next_stage``, run the target
        stage with optional injected inputs. Supports chaining up to
        ``DEFAULT_MAX_DYNAMIC_HOPS``.
        """
        current_stage = stage_name

        for hop in range(DEFAULT_MAX_DYNAMIC_HOPS):
            signal = self._extract_next_stage_signal(current_stage, state)
            if signal is None:
                break

            target = signal["name"]
            if target not in stage_nodes:
                logger.warning(
                    "Stage '%s' declared _next_stage '%s' but "
                    "target not found; ignoring",
                    current_stage, target,
                )
                break

            logger.info(
                "Dynamic edge: '%s' → '%s' (hop %d/%d)",
                current_stage, target, hop + 1, DEFAULT_MAX_DYNAMIC_HOPS,
            )

            # Inject dynamic inputs if provided
            if signal["inputs"]:
                state[StateKeys.DYNAMIC_INPUTS] = signal["inputs"]

            state = self._execute_with_negotiation(
                target, stage_nodes, state, workflow_config,
            )

            # Clean up dynamic inputs
            state.pop(StateKeys.DYNAMIC_INPUTS, None)

            current_stage = target
        else:
            logger.warning(
                "Dynamic edge chain reached max hops (%d) at stage '%s'",
                DEFAULT_MAX_DYNAMIC_HOPS, current_stage,
            )

        return state

    def _run_parallel_stage_batch(
        self,
        runnable: List[str],
        stage_nodes: Dict[str, Callable],
        state: Dict[str, Any],
    ) -> Dict[str, Dict[str, Any]]:
        """Execute stages in parallel using ThreadPoolExecutor."""
        max_workers = min(DEFAULT_MAX_STAGE_PARALLEL_WORKERS, len(runnable))
        results: Dict[str, Dict[str, Any]] = {}

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_name = {
                executor.submit(
                    self._run_stage_node, name, stage_nodes[name], state,
                ): name
                for name in runnable
            }

            for future in as_completed(future_to_name):
                name = future_to_name[future]
                try:
                    results[name] = future.result()
                except Exception:
                    logger.exception("Stage '%s' failed in parallel execution", name)
                    results[name] = {
                        "stage_outputs": {
                            name: {"stage_status": "failed", "error": "execution_error"}
                        },
                        "current_stage": name,
                    }

        return results

    @staticmethod
    def _run_stage_node(
        stage_name: str,
        node_fn: Callable,
        state: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Run a stage node callable and return its result dict.

        The node callable expects state and returns a dict update with
        stage_outputs and current_stage keys.
        """
        logger.info("Executing stage '%s'", stage_name)
        result: Dict[str, Any] = node_fn(state)
        return result

    @staticmethod
    def _merge_stage_result(
        state: Dict[str, Any],
        result: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Merge stage execution result into workflow state.

        The result contains stage_outputs (dict to merge) and current_stage.
        """
        result_outputs = result.get(StateKeys.STAGE_OUTPUTS, {})
        state_outputs = state.get(StateKeys.STAGE_OUTPUTS, {})
        state_outputs.update(result_outputs)
        state[StateKeys.STAGE_OUTPUTS] = state_outputs

        current_stage = result.get(StateKeys.CURRENT_STAGE)
        if current_stage:
            state[StateKeys.CURRENT_STAGE] = current_stage

        return state
