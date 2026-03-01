"""Context provider for stage-level input resolution.

Resolves declared stage inputs from workflow state, replacing the legacy
pass-everything approach with selective context injection.

Four resolver implementations:

- ``InputMapResolver``: Primary resolver that handles all input resolution
  modes. Supports workflow-level ``input_map``, dynamic inputs, passthrough,
  and backward-compatible ``source`` refs from stage configs.
- ``SourceResolver``: Resolves ``source`` refs from stage input declarations.
  Used when a stage declares inputs with ``source`` fields.
- ``PredecessorResolver``: DAG-based — stage gets outputs from its DAG
  predecessors only. Opt-in via ``predecessor_injection: true``.
- ``PassthroughResolver``: Legacy behavior — returns full state with
  ``workflow_inputs`` unwrapped to top level. Used when inputs are omitted.
"""

import logging
from typing import Any, Protocol, runtime_checkable

from temper_ai.shared.utils.config_helpers import get_nested_value
from temper_ai.stage.executors.state_keys import StateKeys
from temper_ai.workflow.context_schemas import (
    ContextResolutionError,
    parse_stage_inputs,
)

logger = logging.getLogger(__name__)

# Infrastructure keys that are always copied into resolved context
_INFRASTRUCTURE_KEYS: frozenset[str] = frozenset(
    {
        StateKeys.TRACKER,
        StateKeys.TOOL_REGISTRY,
        StateKeys.CONFIG_LOADER,
        StateKeys.VISUALIZER,
        StateKeys.SHOW_DETAILS,
        StateKeys.DETAIL_CONSOLE,
        StateKeys.TOOL_EXECUTOR,
        StateKeys.STREAM_CALLBACK,
        StateKeys.WORKFLOW_ID,
        StateKeys.STAGE_OUTPUTS,
    }
)


@runtime_checkable
class ContextProvider(Protocol):
    """Protocol for stage context resolution."""

    def resolve(
        self, stage_config: Any, workflow_state: dict[str, Any]
    ) -> dict[str, Any]:
        """Resolve stage inputs from workflow state.

        Args:
            stage_config: Stage configuration (dict or Pydantic model).
            workflow_state: Current workflow state dict.

        Returns:
            Dict of resolved inputs to pass to agents.
        """
        ...


def _add_infrastructure_keys(resolved: dict[str, Any], state: dict[str, Any]) -> None:
    """Copy infrastructure keys from state into resolved context."""
    for key in _INFRASTRUCTURE_KEYS:
        if key in state:
            resolved[key] = state[key]


def _get_stage_inputs_raw(stage_config: Any) -> dict[str, Any] | None:
    """Extract raw inputs dict from stage config (handles dict and Pydantic)."""
    if isinstance(stage_config, dict):
        inner = stage_config.get("stage", stage_config)
        if isinstance(inner, dict):
            return inner.get("inputs")
        return None
    # Pydantic model
    if hasattr(stage_config, "stage"):
        stage_inner = stage_config.stage
        return getattr(stage_inner, "inputs", None)
    return getattr(stage_config, "inputs", None)


def _get_stage_name(stage_config: Any) -> str:
    """Extract stage name from config."""
    if isinstance(stage_config, dict):
        inner = stage_config.get("stage", stage_config)
        if isinstance(inner, dict):
            result: str = inner.get("name", "unknown")
            return result
        return "unknown"
    if hasattr(stage_config, "stage"):
        return str(getattr(stage_config.stage, "name", "unknown"))
    return str(getattr(stage_config, "name", "unknown"))


class SourceResolver:
    """Resolves declared source references from workflow state.

    Resolution rules:
    - ``workflow.<field>`` → ``workflow_state["workflow_inputs"][field]``
    - ``<stage>.<field>`` → tries structured, then raw, then top-level compat
    - ``<stage>.structured.<field>`` → structured compartment only
    - ``<stage>.raw.<field>`` → raw compartment only

    Falls back to ``PassthroughResolver`` (or optional ``fallback`` resolver)
    when no inputs are declared.
    """

    def __init__(
        self,
        fallback: Any | None = None,
    ) -> None:
        self._passthrough = PassthroughResolver()
        self._predecessor: PredecessorResolver | None = (
            fallback if isinstance(fallback, PredecessorResolver) else None
        )
        self._fallback = fallback or self._passthrough

    def resolve(
        self, stage_config: Any, workflow_state: dict[str, Any]
    ) -> dict[str, Any]:
        """Resolve stage inputs from workflow state."""
        raw_inputs = _get_stage_inputs_raw(stage_config)
        parsed = parse_stage_inputs(raw_inputs)

        if parsed is None:
            return self._fallback.resolve(stage_config, workflow_state)

        stage_name = _get_stage_name(stage_config)
        resolved: dict[str, Any] = {}
        defaults_used: list[str] = []

        for input_name, decl in parsed.items():
            value, found = self._resolve_source(decl.source, workflow_state)
            if found:
                resolved[input_name] = value
            elif decl.required:
                raise ContextResolutionError(stage_name, input_name, decl.source)
            else:
                resolved[input_name] = decl.default
                defaults_used.append(input_name)

        resolved["_context_meta"] = {
            "mode": "source-resolved",
            "sources": {name: decl.source for name, decl in parsed.items()},
            "defaults_used": defaults_used,
        }

        _add_infrastructure_keys(resolved, workflow_state)
        return resolved

    def _resolve_source(
        self, source: str, workflow_state: dict[str, Any]
    ) -> tuple[Any, bool]:
        """Resolve a single source reference.

        Returns:
            Tuple of (value, found). found is False if value could not be resolved.
        """
        parts = source.split(".")
        prefix = parts[0]

        if prefix == "workflow":
            return self._resolve_workflow_source(parts[1:], workflow_state)

        # Stage reference: <stage>.<field> or <stage>.structured.<field>
        stage_name = prefix
        remainder = parts[1:]
        return self._resolve_stage_source(stage_name, remainder, workflow_state)

    def _resolve_workflow_source(
        self, field_path: list[str], workflow_state: dict[str, Any]
    ) -> tuple[Any, bool]:
        """Resolve workflow.<field> from workflow_inputs."""
        workflow_inputs = workflow_state.get(StateKeys.WORKFLOW_INPUTS, {})
        if not workflow_inputs:
            return None, False

        # Simple single-field lookup
        if len(field_path) == 1:
            field = field_path[0]
            if field in workflow_inputs:
                return workflow_inputs[field], True
            return None, False

        # Nested path: workflow.some.nested.field
        dot_path = ".".join(field_path)
        value = get_nested_value(workflow_inputs, dot_path)
        return value, value is not None

    @staticmethod
    def _get_compartment(stage_data: dict[str, Any], key: str) -> dict[str, Any] | None:
        """Return named compartment if it exists and is a dict, else None."""
        value = stage_data.get(key)
        return value if isinstance(value, dict) else None

    def _resolve_stage_source(
        self,
        stage_name: str,
        remainder: list[str],
        workflow_state: dict[str, Any],
    ) -> tuple[Any, bool]:
        """Resolve <stage>.<field> from stage_outputs."""
        stage_outputs = workflow_state.get(StateKeys.STAGE_OUTPUTS, {})
        stage_data = stage_outputs.get(stage_name)
        if not isinstance(stage_data, dict) or not remainder:
            return None, False

        # Explicit compartment: <stage>.structured.<field> or <stage>.raw.<field>
        if remainder[0] in ("structured", "raw"):
            compartment = self._get_compartment(stage_data, remainder[0])
            if compartment is None:
                return None, False
            value = get_nested_value(compartment, ".".join(remainder[1:]))
            return value, value is not None

        # Fallback chain: structured → raw → top-level
        field_path = ".".join(remainder)
        for key in ("structured", "raw"):
            compartment = self._get_compartment(stage_data, key)
            if compartment is not None:
                value = get_nested_value(compartment, field_path)
                if value is not None:
                    return value, True

        value = get_nested_value(stage_data, field_path)
        return value, value is not None


class PredecessorResolver:
    """DAG-based resolver — stage gets outputs from its predecessors only.

    Resolution rules:
    - Root stages (no predecessors): get ``workflow_inputs``
    - Other stages: get the merged outputs of all DAG predecessors
    - Skipped predecessors are excluded
    - Dynamic convergence predecessors (``_convergence_predecessors``)
      are also included when present

    The DAG must be set via ``set_dag()`` before use.
    """

    def __init__(self) -> None:
        self._dag: Any | None = None  # StageDAG (set later)

    def set_dag(self, dag: Any) -> None:
        """Set the stage DAG for predecessor lookup.

        Args:
            dag: StageDAG from ``build_stage_dag()``.
        """
        self._dag = dag

    def resolve(
        self, stage_config: Any, workflow_state: dict[str, Any]
    ) -> dict[str, Any]:
        """Resolve stage inputs from predecessors in the DAG.

        Args:
            stage_config: Stage configuration (dict or Pydantic model).
            workflow_state: Current workflow state dict.

        Returns:
            Dict with predecessor outputs merged, plus infrastructure keys.
        """
        stage_name = _get_stage_name(stage_config)
        predecessors = self._get_predecessors(stage_name, workflow_state)

        resolved: dict[str, Any] = {}

        if not predecessors:
            # Root stage: use workflow_inputs
            wi = workflow_state.get(StateKeys.WORKFLOW_INPUTS, {})
            if isinstance(wi, dict):
                resolved.update(wi)
        else:
            # Merge outputs from predecessors
            stage_outputs = workflow_state.get(StateKeys.STAGE_OUTPUTS, {})
            for pred in predecessors:
                pred_data = stage_outputs.get(pred)
                if isinstance(pred_data, dict):
                    resolved[pred] = pred_data

        resolved["_context_meta"] = {
            "mode": "predecessor",
            "predecessors": predecessors,
        }

        _add_infrastructure_keys(resolved, workflow_state)
        return resolved

    def _get_predecessors(
        self,
        stage_name: str,
        workflow_state: dict[str, Any],
    ) -> list[str]:
        """Get predecessor stage names for the given stage.

        Checks (in order):
        1. Dynamic convergence predecessors from state
        2. DAG predecessors (reverse edges)
        3. Empty list if no DAG is set
        """
        # Dynamic convergence predecessors (set by fan-out convergence)
        convergence_preds = workflow_state.get("_convergence_predecessors", {})
        if stage_name in convergence_preds:
            preds: list[str] = convergence_preds[stage_name]
            return preds

        if self._dag is None:
            return []

        # DAG predecessors: stages that this stage depends on
        predecessors: list[str] = []
        stage_outputs = workflow_state.get(StateKeys.STAGE_OUTPUTS, {})
        for pred in self._dag.predecessors.get(stage_name, []):
            # Exclude skipped predecessors (no output recorded)
            if pred in stage_outputs:
                predecessors.append(pred)

        return predecessors


class PassthroughResolver:
    """Legacy resolver — returns full state with workflow_inputs unwrapped.

    Used when a stage has no input declarations (inputs omitted or no
    source refs). Preserves existing behavior.
    """

    def resolve(
        self, stage_config: Any, workflow_state: dict[str, Any]
    ) -> dict[str, Any]:
        """Return full state with workflow_inputs unwrapped to top level."""
        # Reserved keys that must not be overwritten during unwrap
        _reserved = frozenset(
            {
                StateKeys.STAGE_OUTPUTS,
                StateKeys.CURRENT_STAGE,
                StateKeys.WORKFLOW_ID,
                StateKeys.TRACKER,
                StateKeys.TOOL_REGISTRY,
                StateKeys.CONFIG_LOADER,
                StateKeys.VISUALIZER,
                StateKeys.SHOW_DETAILS,
                StateKeys.DETAIL_CONSOLE,
                StateKeys.WORKFLOW_INPUTS,
                StateKeys.TOOL_EXECUTOR,
                StateKeys.STREAM_CALLBACK,
            }
        )

        result = dict(workflow_state)

        # Unwrap workflow_inputs to top level (existing behavior)
        wi = workflow_state.get(StateKeys.WORKFLOW_INPUTS, {})
        if isinstance(wi, dict):
            for k, v in wi.items():
                if k not in _reserved:
                    result[k] = v

        result["_context_meta"] = {"mode": "passthrough"}

        return result


# State key used to pass input_map from NodeBuilder into resolver
_STAGE_INPUT_MAP_KEY = "_stage_input_map"


def _is_passthrough(stage_config: Any) -> bool:
    """Check if stage opts into passthrough mode (full state access)."""
    if isinstance(stage_config, dict):
        inner = stage_config.get("stage", stage_config)
        if isinstance(inner, dict):
            return bool(inner.get("passthrough", False))
        return False
    if hasattr(stage_config, "stage"):
        return bool(getattr(stage_config.stage, "passthrough", False))
    return bool(getattr(stage_config, "passthrough", False))


class InputMapResolver:
    """Primary resolver that handles all input resolution modes.

    Resolution priority:
    1. ``passthrough: true`` on stage → full state (stage takes responsibility)
    2. ``DYNAMIC_INPUTS`` in state → use directly (from ``_next_stage`` signal)
    3. ``input_map`` from workflow config → resolve each mapping against state
    4. ``source`` refs in stage config → backward compat (SourceResolver)
    5. Defaults for optional inputs; error for required inputs without source

    The ``input_map`` is read from ``workflow_state["_stage_input_map"]``,
    which is set by ``NodeBuilder`` before stage execution. This avoids
    changing the ``ContextProvider`` protocol signature.

    Wraps ``SourceResolver`` for backward compatibility: when no ``input_map``
    is present, delegates to ``SourceResolver`` which reads ``source`` from
    stage input declarations.
    """

    def __init__(self, fallback: Any | None = None) -> None:
        self._source_resolver = SourceResolver(fallback=fallback)
        self._passthrough = PassthroughResolver()
        # Expose predecessor for wire_dag_context() in NodeBuilder
        self._predecessor: PredecessorResolver | None = (
            fallback if isinstance(fallback, PredecessorResolver) else None
        )

    def set_dag(self, dag: Any) -> None:
        """Forward DAG to PredecessorResolver if present."""
        if self._predecessor is not None and hasattr(self._predecessor, "set_dag"):
            self._predecessor.set_dag(dag)

    def resolve(
        self, stage_config: Any, workflow_state: dict[str, Any]
    ) -> dict[str, Any]:
        """Resolve stage inputs from workflow state.

        Reads ``_stage_input_map`` from ``workflow_state`` if present (set by
        ``NodeBuilder``). Falls back to ``SourceResolver`` when no input_map.
        """
        # Passthrough: stage gets full state
        if _is_passthrough(stage_config):
            return self._passthrough.resolve(stage_config, workflow_state)

        # Dynamic inputs take priority (set by _next_stage signal)
        dynamic = workflow_state.get(StateKeys.DYNAMIC_INPUTS)
        if dynamic is not None:
            return self._resolve_from_dynamic(dynamic, workflow_state)

        # Workflow-level input_map (set by NodeBuilder)
        input_map = workflow_state.get(_STAGE_INPUT_MAP_KEY)
        if input_map:
            return self._resolve_from_input_map(stage_config, workflow_state, input_map)

        # Backward compat: delegate to SourceResolver (reads source from stage)
        return self._source_resolver.resolve(stage_config, workflow_state)

    @staticmethod
    def _resolve_from_dynamic(
        dynamic: dict[str, Any],
        workflow_state: dict[str, Any],
    ) -> dict[str, Any]:
        """Resolve from dynamic inputs (set by ``_next_stage`` signal)."""
        resolved = dict(dynamic)
        resolved["_context_meta"] = {"mode": "dynamic"}
        _add_infrastructure_keys(resolved, workflow_state)
        return resolved

    def _resolve_from_input_map(
        self,
        stage_config: Any,
        workflow_state: dict[str, Any],
        input_map: dict[str, str],
    ) -> dict[str, Any]:
        """Resolve inputs using workflow-level ``input_map``.

        For each entry in ``input_map``, resolves the source reference
        (``workflow.X`` or ``stage.Y``) against the current workflow state.
        Falls back to stage input defaults for unresolved optional inputs.
        """
        stage_name = _get_stage_name(stage_config)
        raw_inputs = _get_stage_inputs_raw(stage_config) or {}

        resolved: dict[str, Any] = {}
        defaults_used: list[str] = []

        # Resolve each input_map entry
        for input_name, source_ref in input_map.items():
            value, found = self._source_resolver._resolve_source(
                source_ref, workflow_state
            )
            if found:
                resolved[input_name] = value
            else:
                default, required = _get_input_default(raw_inputs, input_name)
                if not required:
                    resolved[input_name] = default
                    defaults_used.append(input_name)
                else:
                    raise ContextResolutionError(stage_name, input_name, source_ref)

        # Apply defaults for declared inputs NOT in input_map
        for input_name, decl in raw_inputs.items():
            if input_name in resolved or input_name in input_map:
                continue
            if not isinstance(decl, dict):
                continue
            required = decl.get("required", True)
            default = decl.get("default")
            if not required or default is not None:
                resolved[input_name] = default
                defaults_used.append(input_name)
            elif required:
                raise ContextResolutionError(
                    stage_name, input_name, "<missing from input_map>"
                )

        resolved["_context_meta"] = {
            "mode": "input-map",
            "input_map": dict(input_map),
            "defaults_used": defaults_used,
        }

        _add_infrastructure_keys(resolved, workflow_state)
        return resolved


def _get_input_default(
    raw_inputs: dict[str, Any],
    input_name: str,
) -> tuple[Any, bool]:
    """Get default value and required flag for an input.

    Returns:
        Tuple of (default_value, is_required).
    """
    if input_name not in raw_inputs:
        return None, True  # unknown input, treat as required
    decl = raw_inputs[input_name]
    if not isinstance(decl, dict):
        return None, True
    required = decl.get("required", True)
    default = decl.get("default")
    return default, required
