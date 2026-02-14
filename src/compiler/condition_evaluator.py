"""Jinja2-based condition evaluator for conditional stages and loops.

Evaluates condition expressions from workflow stage references using the same
ImmutableSandboxedEnvironment used for prompt rendering, ensuring SSTI protection.

Example:
    >>> evaluator = ConditionEvaluator()
    >>> evaluator.evaluate("{{ stage_outputs.test.stage_status == 'failed' }}", state)
    True
"""
import logging
from typing import Any, Dict, List, Optional, cast

from jinja2 import Undefined
from jinja2.sandbox import ImmutableSandboxedEnvironment

logger = logging.getLogger(__name__)

# Infrastructure keys filtered from condition context
_INFRASTRUCTURE_KEYS = frozenset({
    "tracker", "tool_registry", "config_loader", "visualizer",
    "show_details", "detail_console", "stream_callback",
    "tool_executor", "_dict_cache", "_dict_cache_exclude_internal",
})


class ConditionEvaluator:
    """Evaluates Jinja2 condition expressions against workflow state.

    Uses ImmutableSandboxedEnvironment for safe template evaluation.
    Template compilation is cached for repeated evaluations.

    Example:
        >>> evaluator = ConditionEvaluator()
        >>> state = {"stage_outputs": {"test": {"stage_status": "failed"}}}
        >>> evaluator.evaluate(
        ...     "{{ stage_outputs.test.get('stage_status') == 'failed' }}",
        ...     state
        ... )
        True
    """

    MAX_CACHE_SIZE = 128

    def __init__(self) -> None:
        self._env = ImmutableSandboxedEnvironment(
            undefined=_SilentUndefined,
        )
        self._template_cache: Dict[str, Any] = {}

    def evaluate(self, condition: str, state: Dict[str, Any]) -> bool:
        """Evaluate a Jinja2 condition expression against workflow state.

        Args:
            condition: Jinja2 template string that renders to a truthy/falsy value
            state: Current workflow state dictionary

        Returns:
            Boolean result of the condition evaluation
        """
        context = self._build_safe_context(state)
        try:
            template = self._get_template(condition)
            rendered = template.render(**context).strip().lower()
            return rendered in ("true", "1", "yes")
        except Exception:
            logger.warning(
                "Condition evaluation failed for %r, defaulting to False",
                condition,
                exc_info=True,
            )
            return False

    def _build_safe_context(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Build a safe context dictionary for template rendering.

        Filters out infrastructure keys (tracker, tool_registry, etc.)
        to prevent accidental access to non-serializable objects.

        Args:
            state: Raw workflow state dictionary

        Returns:
            Filtered context safe for Jinja2 rendering
        """
        return {
            k: v for k, v in state.items()
            if k not in _INFRASTRUCTURE_KEYS
        }

    def _get_template(self, condition: str) -> Any:
        """Get compiled Jinja2 template with instance-level caching.

        Args:
            condition: Jinja2 template string

        Returns:
            Compiled Jinja2 Template object
        """
        cached = self._template_cache.get(condition)
        if cached is not None:
            return cached
        template = self._env.from_string(condition)
        if len(self._template_cache) < self.MAX_CACHE_SIZE:
            self._template_cache[condition] = template
        return template


class _SilentUndefined(Undefined):
    """Jinja2 undefined that returns empty string / falsy for missing keys.

    Prevents TemplateUndefinedError when conditions reference keys
    that don't exist yet (e.g., stage_outputs for a stage that hasn't run).
    """

    def __str__(self) -> str:
        return ""

    def __bool__(self) -> bool:
        return False

    def __iter__(self) -> Any:
        return iter([])

    def __getattr__(self, _name: str) -> "_SilentUndefined":
        return _SilentUndefined()

    def __getitem__(self, _key: Any) -> "_SilentUndefined":  # type: ignore[override]
        return _SilentUndefined()

    def __call__(self, *_args: Any, **_kwargs: Any) -> "_SilentUndefined":  # type: ignore[override]
        return _SilentUndefined()

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, _SilentUndefined):
            return True
        return False

    def __ne__(self, other: Any) -> bool:
        return not self.__eq__(other)


def get_default_condition(
    stage_index: int,
    stages: List[Any],
) -> Optional[str]:
    """Generate default condition for a conditional stage.

    Default: previous stage's status is 'failed' or 'degraded'.

    Args:
        stage_index: Index of the conditional stage in the stage list
        stages: List of WorkflowStageReference objects

    Returns:
        Jinja2 condition string, or None if no previous stage
    """
    if stage_index <= 0:
        return None
    prev_name = _get_stage_name(stages[stage_index - 1])
    return (
        "{{ stage_outputs.get('" + prev_name + "', {}).get('stage_status') "
        "in ['failed', 'degraded'] }}"
    )


def get_default_loop_condition(
    source_stage_name: str,
) -> str:
    """Generate default loop condition for a loops_back_to stage.

    Default: the source stage (current stage) has failures/degraded status,
    meaning the loop should continue.

    Args:
        source_stage_name: Name of the stage that loops back

    Returns:
        Jinja2 condition string
    """
    return (
        "{{ stage_outputs.get('" + source_stage_name + "', {}).get('stage_status') "
        "in ['failed', 'degraded'] }}"
    )


def _get_stage_name(stage_ref: Any) -> str:
    """Extract stage name from a stage reference.

    Handles dict, Pydantic model, and string formats.

    Args:
        stage_ref: Stage reference object

    Returns:
        Stage name string
    """
    if isinstance(stage_ref, str):
        return stage_ref
    if isinstance(stage_ref, dict):
        return cast(str, stage_ref["name"])
    return cast(str, stage_ref.name)
