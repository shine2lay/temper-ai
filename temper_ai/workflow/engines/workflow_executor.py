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
import json
import logging
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Dict, List, Optional

from temper_ai.workflow.condition_evaluator import (
    ConditionEvaluator,
    get_default_condition,
    get_default_loop_condition,
)
from temper_ai.workflow.dag_builder import StageDAG, build_stage_dag, compute_depths
from temper_ai.stage.executors.state_keys import StateKeys
from temper_ai.workflow.node_builder import NodeBuilder
from temper_ai.shared.utils.exceptions import WorkflowStageError

logger = logging.getLogger(__name__)

# Default limits
DEFAULT_MAX_LOOPS = 2
DEFAULT_MAX_NEGOTIATION_ROUNDS = 2
DEFAULT_MAX_STAGE_PARALLEL_WORKERS = 4
DEFAULT_MAX_DYNAMIC_HOPS = 5
DEFAULT_MAX_DYNAMIC_TARGETS = 10


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


def _run_stage_node(
    stage_name: str,
    node_fn: Callable,
    state: Dict[str, Any],
) -> Dict[str, Any]:
    """Run a stage node callable and return its result dict."""
    logger.info("Executing stage '%s'", stage_name)
    result: Dict[str, Any] = node_fn(state)
    return result


def _merge_stage_result(
    state: Dict[str, Any],
    result: Dict[str, Any],
) -> Dict[str, Any]:
    """Merge stage execution result into workflow state."""
    result_outputs = result.get(StateKeys.STAGE_OUTPUTS, {})
    state_outputs = state.get(StateKeys.STAGE_OUTPUTS, {})
    state_outputs.update(result_outputs)
    state[StateKeys.STAGE_OUTPUTS] = state_outputs

    current_stage = result.get(StateKeys.CURRENT_STAGE)
    if current_stage:
        state[StateKeys.CURRENT_STAGE] = current_stage

    return state


def _normalize_next_stage_signal(raw_signal: Any) -> Optional[Dict[str, Any]]:
    """Normalize various _next_stage signal formats into ``{targets, mode}``.

    Supported formats (backward-compatible):
    - Old single dict: ``{"name": "B", "inputs": {...}}``
      → ``{"targets": [{"name": "B", "inputs": {...}}], "mode": "sequential"}``
    - Sequential chain (list): ``[{"name": "B"}, {"name": "C"}]``
      → ``{"targets": [...], "mode": "sequential"}``
    - Parallel fan-out: ``{"mode": "parallel", "targets": [...]}``
      → passed through as-is (with target normalization)

    Returns:
        Normalized dict with ``targets`` and ``mode``, or None.
    """
    if isinstance(raw_signal, list):
        return _normalize_list_signal(raw_signal)
    if isinstance(raw_signal, dict):
        return _normalize_dict_signal(raw_signal)
    return None


def _normalize_list_signal(items: List[Any]) -> Optional[Dict[str, Any]]:
    """Normalize list-format signal (sequential chain)."""
    targets = _extract_target_list(items)
    if not targets:
        return None
    return {"targets": targets, "mode": "sequential"}


def _normalize_dict_signal(signal: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Normalize dict-format signal (old single or parallel).

    Parallel signals may include a ``converge`` field specifying a stage
    to run exactly once after all parallel branches complete::

        {"mode": "parallel", "targets": [...], "converge": {"name": "D"}}
    """
    if signal.get("mode") == "parallel" and isinstance(signal.get("targets"), list):
        targets = _extract_target_list(signal["targets"])
        if not targets:
            return None
        result: Dict[str, Any] = {"targets": targets, "mode": "parallel"}
        converge = signal.get("converge")
        if isinstance(converge, dict) and converge.get("name"):
            result["converge"] = {"name": converge["name"]}
        return result
    if signal.get("name"):
        return {
            "targets": [{"name": signal["name"], "inputs": signal.get("inputs", {})}],
            "mode": "sequential",
        }
    return None


def _extract_target_list(items: List[Any]) -> List[Dict[str, Any]]:
    """Extract and cap target list from raw items."""
    targets: List[Dict[str, Any]] = []
    for item in items[:DEFAULT_MAX_DYNAMIC_TARGETS]:
        if isinstance(item, dict) and item.get("name"):
            targets.append({"name": item["name"], "inputs": item.get("inputs", {})})
    if len(items) > DEFAULT_MAX_DYNAMIC_TARGETS:
        logger.warning(
            "Dynamic targets truncated from %d to %d",
            len(items), DEFAULT_MAX_DYNAMIC_TARGETS,
        )
    return targets


def _extract_next_stage_signal(
    stage_name: str,
    state: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Extract _next_stage signal from a stage's output.

    Checks three sources in priority order:
    1. Top-level ``_next_stage`` in stage output
    2. ``structured`` compartment
    3. Raw ``output`` text parsed as JSON (fallback)

    Returns:
        Normalized dict with ``targets`` (list of {name, inputs}) and
        ``mode`` ("sequential" or "parallel"), or None.
    """
    stage_data = state.get(StateKeys.STAGE_OUTPUTS, {}).get(stage_name, {})
    if not isinstance(stage_data, dict):
        return None

    signal = stage_data.get(_NEXT_STAGE_KEY)
    if signal is not None:
        normalized = _normalize_next_stage_signal(signal)
        if normalized is not None:
            return normalized

    structured = stage_data.get("structured", {})
    if isinstance(structured, dict):
        signal = structured.get(_NEXT_STAGE_KEY)
        if signal is not None:
            normalized = _normalize_next_stage_signal(signal)
            if normalized is not None:
                return normalized

    raw_output = stage_data.get("output")
    if isinstance(raw_output, str):
        return _parse_next_stage_from_text(raw_output)

    return None


def _parse_next_stage_from_text(text: str) -> Optional[Dict[str, Any]]:
    """Try to extract _next_stage from raw output text.

    Handles two cases:
    1. Entire output is a JSON object containing ``_next_stage``
    2. Output contains an embedded JSON object with ``_next_stage``

    Returns:
        Normalized dict with ``targets`` and ``mode``, or None.
    """
    parsed = _try_parse_json(text.strip())
    signal = _extract_signal_from_parsed(parsed)
    if signal is not None:
        return signal

    # Try extracting embedded JSON: find first '{' and last '}'
    first_brace = text.find("{")
    last_brace = text.rfind("}")
    if first_brace >= 0 and last_brace > first_brace:
        substring = text[first_brace:last_brace + 1]
        parsed = _try_parse_json(substring)
        return _extract_signal_from_parsed(parsed)

    return None


def _extract_signal_from_parsed(parsed: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Extract and normalize _next_stage signal from parsed JSON dict."""
    if parsed is None:
        return None
    signal = parsed.get(_NEXT_STAGE_KEY)
    if signal is not None:
        return _normalize_next_stage_signal(signal)
    return None


def _try_parse_json(text: str) -> Optional[Dict[str, Any]]:
    """Attempt to parse text as JSON dict. Returns None on failure."""
    try:
        result = json.loads(text)
        if isinstance(result, dict):
            return result
    except (json.JSONDecodeError, TypeError, ValueError):
        pass
    return None


def _run_parallel_stage_batch(
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
                _run_stage_node, name, stage_nodes[name], dict(state),
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


def _build_dynamic_input_wrappers(
    targets: List[Dict[str, Any]],
    stage_nodes: Dict[str, Callable],
) -> Dict[str, Callable]:
    """Build wrapper nodes that inject per-target DYNAMIC_INPUTS.

    For parallel fan-out, each target may have its own inputs that need
    to be injected before the stage node runs.
    """
    wrapped: Dict[str, Callable] = {}
    for target_info in targets:
        name = target_info["name"]
        node_fn = stage_nodes[name]
        inputs = target_info.get("inputs", {})
        if inputs:
            wrapped[name] = _make_input_wrapper(node_fn, inputs)
        else:
            wrapped[name] = node_fn
    return wrapped


def _make_input_wrapper(
    node_fn: Callable, inputs: Dict[str, Any],
) -> Callable:
    """Create a wrapper that sets DYNAMIC_INPUTS before calling node_fn."""
    def wrapper(state: Dict[str, Any]) -> Dict[str, Any]:
        """Inject dynamic inputs, run node, then clean up."""
        state[StateKeys.DYNAMIC_INPUTS] = inputs
        result: Dict[str, Any] = node_fn(state)
        state.pop(StateKeys.DYNAMIC_INPUTS, None)
        return result
    return wrapper


class WorkflowExecutor:
    """Walks workflow stages as a Python loop — no compiled graph.

    The core execution loop that replaces LangGraph's Pregel model for the
    native engine. Walks stages respecting DAG order, evaluates conditions
    and loops, and supports stage-to-stage negotiation.

    Args:
        node_builder: NodeBuilder for creating stage execution callables
        condition_evaluator: ConditionEvaluator for conditional/loop expressions
        negotiation_config: Optional negotiation configuration dict
    """

    def __init__(
        self,
        node_builder: NodeBuilder,
        condition_evaluator: ConditionEvaluator,
        negotiation_config: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.node_builder = node_builder
        self.condition_evaluator = condition_evaluator
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

        # Wire DAG into predecessor resolver for context resolution
        self.node_builder.wire_dag_context(dag)

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
            try:
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
            except WorkflowStageError as exc:
                logger.error("Stage failed, halting workflow: %s", exc)
                state[StateKeys.SKIP_TO_END] = exc.stage_name
                break

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

        results = _run_parallel_stage_batch(runnable, stage_nodes, state)

        for name in runnable:
            if name in results:
                state = _merge_stage_result(state, results[name])

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
        max_loops, re-runs the loop target stage and any intermediate
        stages between the target and this stage.
        """
        loop_cfg = self._build_loop_config(stage_ref, stage_name)
        intermediate = self._find_intermediate_stages(
            loop_cfg["target"], stage_name, stage_refs, stage_nodes,
        )
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

            for mid_name in intermediate:
                logger.info(
                    "Re-running intermediate stage '%s' in loop", mid_name,
                )
                state = self._execute_with_negotiation(
                    mid_name, stage_nodes, state, workflow_config,
                )

        return state

    @staticmethod
    def _find_intermediate_stages(
        target: str, source: str,
        stage_refs: List[Any], stage_nodes: Dict[str, Callable],
    ) -> list[str]:
        """Find stages between loop target and source in DAG order.

        Returns stage names that sit between the loop target and the
        looping stage, so they can be re-executed during loop iterations.
        """
        names = [_ref_attr(ref, "name") for ref in stage_refs]
        try:
            t_idx = names.index(target)
            s_idx = names.index(source)
        except ValueError:
            return []
        if t_idx >= s_idx:
            return []
        return [n for n in names[t_idx + 1:s_idx] if n in stage_nodes]

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
        from temper_ai.workflow.context_provider import ContextResolutionError

        negotiation_enabled = self._negotiation_config.get("enabled", False)
        max_rounds = self._negotiation_config.get(
            "max_stage_rounds", DEFAULT_MAX_NEGOTIATION_ROUNDS,
        )

        last_error: Optional[ContextResolutionError] = None
        for attempt in range(max_rounds + 1):
            try:
                result = _run_stage_node(
                    stage_name, stage_nodes[stage_name], state,
                )
                return _merge_stage_result(state, result)
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
        producer_result = _run_stage_node(
            producer, stage_nodes[producer], state,
        )
        state = _merge_stage_result(state, producer_result)
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

    def _follow_dynamic_edges(
        self,
        stage_name: str,
        stage_nodes: Dict[str, Callable],
        state: Dict[str, Any],
        workflow_config: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Follow dynamic edge signals after a stage completes.

        Delegates to ``_dynamic_edge_helpers.follow_dynamic_edges``.
        """
        from temper_ai.workflow.engines._dynamic_edge_helpers import follow_dynamic_edges

        return follow_dynamic_edges(
            stage_name, stage_nodes, state, workflow_config,
            self._execute_with_negotiation,
        )



