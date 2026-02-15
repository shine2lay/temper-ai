"""Context provider for stage-level input resolution.

Resolves declared stage inputs from workflow state, replacing the legacy
pass-everything approach with selective context injection.

Two resolver implementations:

- ``SourceResolver``: Resolves ``source`` refs from stage input declarations.
  Used when a stage declares inputs with ``source`` fields.
- ``PassthroughResolver``: Legacy behavior — returns full state with
  ``workflow_inputs`` unwrapped to top level. Used when inputs are omitted.
"""
import logging
from typing import Any, Dict, Optional, Protocol, runtime_checkable

from src.workflow.context_schemas import parse_stage_inputs
from src.stage.executors.state_keys import StateKeys
from src.shared.utils.config_helpers import get_nested_value

logger = logging.getLogger(__name__)

# Infrastructure keys that are always copied into resolved context
_INFRASTRUCTURE_KEYS: frozenset[str] = frozenset({
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
})


class ContextResolutionError(Exception):
    """Raised when a required input cannot be resolved."""

    def __init__(self, stage_name: str, input_name: str, source: str) -> None:
        self.stage_name = stage_name
        self.input_name = input_name
        self.source = source
        super().__init__(
            f"Stage '{stage_name}': required input '{input_name}' "
            f"could not be resolved from source '{source}'"
        )


@runtime_checkable
class ContextProvider(Protocol):
    """Protocol for stage context resolution."""

    def resolve(
        self, stage_config: Any, workflow_state: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Resolve stage inputs from workflow state.

        Args:
            stage_config: Stage configuration (dict or Pydantic model).
            workflow_state: Current workflow state dict.

        Returns:
            Dict of resolved inputs to pass to agents.
        """
        ...


def _add_infrastructure_keys(
    resolved: Dict[str, Any], state: Dict[str, Any]
) -> None:
    """Copy infrastructure keys from state into resolved context."""
    for key in _INFRASTRUCTURE_KEYS:
        if key in state:
            resolved[key] = state[key]


def _get_stage_inputs_raw(stage_config: Any) -> Optional[Dict[str, Any]]:
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

    Falls back to ``PassthroughResolver`` when no inputs are declared.
    """

    def __init__(self) -> None:
        self._passthrough = PassthroughResolver()

    def resolve(
        self, stage_config: Any, workflow_state: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Resolve stage inputs from workflow state."""
        raw_inputs = _get_stage_inputs_raw(stage_config)
        parsed = parse_stage_inputs(raw_inputs)

        if parsed is None:
            return self._passthrough.resolve(stage_config, workflow_state)

        stage_name = _get_stage_name(stage_config)
        resolved: Dict[str, Any] = {}
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
        self, source: str, workflow_state: Dict[str, Any]
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
        self, field_path: list[str], workflow_state: Dict[str, Any]
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
    def _get_compartment(stage_data: Dict[str, Any], key: str) -> Optional[Dict[str, Any]]:
        """Return named compartment if it exists and is a dict, else None."""
        value = stage_data.get(key)
        return value if isinstance(value, dict) else None

    def _resolve_stage_source(
        self, stage_name: str, remainder: list[str],
        workflow_state: Dict[str, Any],
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


class PassthroughResolver:
    """Legacy resolver — returns full state with workflow_inputs unwrapped.

    Used when a stage has no input declarations (inputs omitted or no
    source refs). Preserves existing behavior.
    """

    def resolve(
        self, stage_config: Any, workflow_state: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Return full state with workflow_inputs unwrapped to top level."""
        # Reserved keys that must not be overwritten during unwrap
        _reserved = frozenset({
            StateKeys.STAGE_OUTPUTS, StateKeys.CURRENT_STAGE,
            StateKeys.WORKFLOW_ID, StateKeys.TRACKER,
            StateKeys.TOOL_REGISTRY, StateKeys.CONFIG_LOADER,
            StateKeys.VISUALIZER, StateKeys.SHOW_DETAILS,
            StateKeys.DETAIL_CONSOLE, StateKeys.WORKFLOW_INPUTS,
            StateKeys.TOOL_EXECUTOR, StateKeys.STREAM_CALLBACK,
        })

        result = dict(workflow_state)

        # Unwrap workflow_inputs to top level (existing behavior)
        wi = workflow_state.get(StateKeys.WORKFLOW_INPUTS, {})
        if isinstance(wi, dict):
            for k, v in wi.items():
                if k not in _reserved:
                    result[k] = v

        result["_context_meta"] = {"mode": "passthrough"}

        return result
