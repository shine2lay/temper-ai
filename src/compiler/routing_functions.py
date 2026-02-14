"""Router factories for LangGraph conditional edges.

Creates callable routing functions used with ``graph.add_conditional_edges()``
to implement conditional stage execution and loop-back patterns.

Example:
    >>> router = create_conditional_router(stage_ref, "next_stage", 1, stages, evaluator)
    >>> target = router(state)  # returns "fix" or "next_stage" or "__end__"
"""
import logging
from typing import Any, Callable, Dict, List, Optional, Union, cast

from langgraph.graph import END

from src.compiler.condition_evaluator import (
    ConditionEvaluator,
    get_default_condition,
    get_default_loop_condition,
)
from src.compiler.executors.state_keys import StateKeys

logger = logging.getLogger(__name__)

LOOP_COUNTS_KEY = StateKeys.STAGE_LOOP_COUNTS


def _ref_attr(ref: Any, attr: str, default: Any = None) -> Any:
    """Get attribute from a stage ref (dict or object)."""
    if isinstance(ref, dict):
        return ref.get(attr, default)
    return getattr(ref, attr, default)


def create_conditional_router(
    stage_ref: Any,
    next_stage: Optional[str],
    stage_index: int,
    all_stages: List[Any],
    evaluator: ConditionEvaluator,
) -> Callable[[Dict[str, Any]], str]:
    """Create a router for a conditional stage (skip_if / condition).

    The router decides whether the *next* stage should execute or be skipped.
    It is placed on the edge *before* the conditional stage.

    Args:
        stage_ref: WorkflowStageReference for the conditional stage
        next_stage: Name of the stage after the conditional one (or None for last)
        stage_index: Index of the conditional stage in the stage list
        all_stages: Full list of stage references
        evaluator: ConditionEvaluator instance

    Returns:
        Callable that takes state dict and returns target node name
    """
    target_name = stage_ref if isinstance(stage_ref, str) else _ref_attr(stage_ref, "name")
    skip_target = next_stage or END

    # Determine condition to evaluate
    skip_if = _ref_attr(stage_ref, "skip_if")
    condition = _ref_attr(stage_ref, "condition")

    if skip_if:
        # skip_if: if True, skip the stage
        def _skip_if_router(state: Dict[str, Any]) -> str:
            state_dict = _to_dict(state)
            if evaluator.evaluate(skip_if, state_dict):
                logger.info("Skipping stage %r (skip_if condition met)", target_name)
                return skip_target
            return target_name
        return _skip_if_router

    if condition:
        # condition: if True, execute the stage
        def _condition_router(state: Dict[str, Any]) -> str:
            state_dict = _to_dict(state)
            if evaluator.evaluate(condition, state_dict):
                return target_name
            logger.info("Skipping stage %r (condition not met)", target_name)
            return skip_target
        return _condition_router

    # Default condition: previous stage failed/degraded → execute
    default_cond = get_default_condition(stage_index, all_stages)
    if default_cond:
        def _default_router(state: Dict[str, Any]) -> str:
            state_dict = _to_dict(state)
            if evaluator.evaluate(default_cond, state_dict):
                return target_name
            logger.info(
                "Skipping stage %r (default condition: previous stage succeeded)",
                target_name,
            )
            return skip_target
        return _default_router

    # No condition resolvable — always execute
    def _always_router(_state: Dict[str, Any]) -> str:
        return target_name
    return _always_router


def create_loop_router(
    stage_ref: Any,
    exit_targets: Union[Optional[str], List[Optional[str]]],
    evaluator: ConditionEvaluator,
) -> Callable[[Dict[str, Any]], Any]:
    """Create a router for a stage with loops_back_to.

    Placed on the edge *after* the looping stage. Decides whether to
    loop back to the target stage or proceed to the exit target(s).

    When exit_targets is a list with multiple entries, the exit path
    returns all targets for LangGraph fan-out.

    Args:
        stage_ref: WorkflowStageReference with loops_back_to set
        exit_targets: Single target, list of targets, or None for END
        evaluator: ConditionEvaluator instance

    Returns:
        Callable that takes state dict and returns target(s)
    """
    source_name = _ref_attr(stage_ref, "name") if not isinstance(stage_ref, str) else stage_ref
    loop_target = _ref_attr(stage_ref, "loops_back_to")
    max_loops = _ref_attr(stage_ref, "max_loops", 2)
    condition = _ref_attr(stage_ref, "condition")

    # Normalize exit_targets to a list
    if isinstance(exit_targets, list):
        resolved_exits = [t or END for t in exit_targets]
    else:
        resolved_exits = [exit_targets or END]

    # Determine loop condition
    explicit_loop_cond = _ref_attr(stage_ref, "loop_condition")
    loop_condition = explicit_loop_cond or condition or get_default_loop_condition(source_name)

    def _loop_router(state: Dict[str, Any]) -> Any:
        loop_counts = _get_loop_counts(state)
        current_count = loop_counts.get(source_name, 0)

        if current_count > max_loops:
            logger.info("Stage %r reached max loops (%d), exiting", source_name, max_loops)
            return resolved_exits if len(resolved_exits) > 1 else resolved_exits[0]

        state_dict = _to_dict(state)
        if evaluator.evaluate(loop_condition, state_dict):
            logger.info(
                "Stage %r looping back to %r (iteration %d/%d)",
                source_name, loop_target, current_count, max_loops,
            )
            return loop_target

        logger.info("Stage %r loop condition not met, proceeding", source_name)
        return resolved_exits if len(resolved_exits) > 1 else resolved_exits[0]

    return _loop_router


def _get_loop_counts(state: Any) -> Dict[str, int]:
    """Extract loop counts from state (dict or dataclass)."""
    if isinstance(state, dict):
        return cast(Dict[str, int], state.get(LOOP_COUNTS_KEY, {}))
    if hasattr(state, LOOP_COUNTS_KEY):
        return getattr(state, LOOP_COUNTS_KEY) or {}
    return {}


def _to_dict(state: Any) -> Dict[str, Any]:
    """Convert state to dict if it's a dataclass.

    Args:
        state: LangGraphWorkflowState dataclass or dict

    Returns:
        State as a plain dictionary
    """
    if isinstance(state, dict):
        return state
    if hasattr(state, "to_dict"):
        return cast(Dict[str, Any], state.to_dict())
    if hasattr(state, "__dict__"):
        return cast(Dict[str, Any], state.__dict__)
    return {}
