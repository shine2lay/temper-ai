"""Extracted helper functions for WorkflowRuntime.

These are stateless (or near-stateless) helpers that were originally
static methods or simple private methods on WorkflowRuntime.
Moving them here keeps the main class under the 500-line threshold.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Lazy-imported in emit_lifecycle_event to avoid import fan-out
_ObservabilityEvent: type | None = None


def validate_file_size(file_path: Path) -> None:
    """Reject files exceeding CONFIG_SECURITY.MAX_CONFIG_SIZE.

    Args:
        file_path: Path to the file to check.

    Raises:
        ConfigValidationError: If file exceeds maximum allowed size.
    """
    from temper_ai.shared.utils.exceptions import ConfigValidationError
    from temper_ai.workflow.security_limits import CONFIG_SECURITY

    file_size = file_path.stat().st_size
    if file_size > CONFIG_SECURITY.MAX_CONFIG_SIZE:
        raise ConfigValidationError(
            f"Config file too large: {file_size} bytes "
            f"(max: {CONFIG_SECURITY.MAX_CONFIG_SIZE})"
        )


def validate_structure(config: dict[str, Any], file_path: Path) -> None:
    """Check depth, node count, and circular refs.

    Args:
        config: Parsed configuration dict.
        file_path: Path to the source file (for error messages).
    """
    from temper_ai.workflow._config_loader_helpers import (
        validate_config_structure,
    )

    validate_config_structure(config, file_path)


def validate_schema(config: dict[str, Any]) -> None:
    """Validate against the WorkflowConfig Pydantic schema.

    Args:
        config: Parsed configuration dict.

    Raises:
        ConfigValidationError: If schema validation fails.
    """
    from pydantic import ValidationError as PydanticValidationError

    from temper_ai.shared.utils.exceptions import ConfigValidationError
    from temper_ai.workflow._schemas import WorkflowConfig

    try:
        WorkflowConfig(**config)
    except PydanticValidationError as exc:
        raise ConfigValidationError(
            f"Workflow schema validation failed: {exc}",
            validation_errors=exc.errors(),
        ) from exc


def check_required_inputs(
    workflow_config: dict[str, Any],
    inputs: dict[str, Any],
) -> list[str]:
    """Check for missing required inputs.

    Args:
        workflow_config: Parsed workflow configuration dict.
        inputs: Provided input data dict.

    Returns:
        List of missing required input names (empty if all present).
    """
    wf = workflow_config.get("workflow", {})
    required = wf.get("inputs", {}).get("required", [])
    return [r for r in required if r not in inputs]


def resolve_path(workflow_path: str, config_root: str) -> Path:
    """Resolve workflow path, checking config_root if not absolute.

    Args:
        workflow_path: Path to the workflow file (may be relative).
        config_root: Root configuration directory.

    Returns:
        Resolved Path to the workflow file.

    Raises:
        FileNotFoundError: If workflow file cannot be found.
    """
    path = Path(workflow_path)
    if path.is_absolute() and path.exists():
        return path

    config_path = Path(config_root) / workflow_path
    if config_path.exists():
        return config_path

    if path.exists():
        return path

    raise FileNotFoundError(f"Workflow file not found: {workflow_path}")


def create_tracker(
    config_tracker_backend_factory: Any | None,
    event_bus: Any | None = None,
) -> Any:
    """Create ExecutionTracker with optional event bus.

    Args:
        config_tracker_backend_factory: Optional callable that returns a backend.
        event_bus: Optional event bus instance.

    Returns:
        ExecutionTracker instance.
    """
    from temper_ai.observability.tracker import ExecutionTracker

    if config_tracker_backend_factory is not None:
        backend = config_tracker_backend_factory()
        if backend is not None:
            return ExecutionTracker(backend=backend, event_bus=event_bus)
        # Factory returned None -- fall through to default

    if event_bus is not None:
        return ExecutionTracker(event_bus=event_bus)

    return ExecutionTracker()


def emit_lifecycle_event(
    event_bus: Any | None,
    workflow_id: str | None,
    event_type: str,
    data: dict[str, Any],
) -> None:
    """Emit a lifecycle event via the event bus.

    These events cover pre-execution pipeline phases (config loading,
    lifecycle adaptation, compilation) that occur before the tracker
    opens its workflow scope.

    Args:
        event_bus: Event bus instance, or None to skip.
        workflow_id: Workflow execution ID.
        event_type: Event type constant from observability.constants.
        data: Event payload dict.
    """
    if event_bus is None:
        return

    global _ObservabilityEvent  # noqa: PLW0603
    if _ObservabilityEvent is None:
        from temper_ai.observability.event_bus import (
            ObservabilityEvent,
        )

        _ObservabilityEvent = ObservabilityEvent

    event = _ObservabilityEvent(
        event_type=event_type,
        timestamp=datetime.now(UTC),
        data=data,
        workflow_id=workflow_id,
    )
    event_bus.emit(event)


def load_workflow_config(
    workflow_path: str,
    config_root: str,
    event_bus: Any | None,
    workflow_id: str | None,
    input_data: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Load, parse, validate, and return (workflow_config, inputs).

    Applies: file-size check, YAML parse, mapping check, structure
    validation (depth/nodes/circular refs), and Pydantic schema validation.

    Args:
        workflow_path: Path to workflow YAML (absolute or relative to config_root).
        config_root: Root directory for resolving relative paths.
        event_bus: Optional event bus for lifecycle events.
        workflow_id: Workflow execution ID for events.
        input_data: Optional pre-loaded input dict.

    Returns:
        Tuple of (workflow_config, inputs).

    Raises:
        FileNotFoundError: If workflow file does not exist.
        ConfigValidationError: If file too large, structure invalid, or schema fails.
        ValueError: If workflow config is not a YAML mapping.
    """
    import yaml

    from temper_ai.shared.utils.exceptions import ConfigValidationError

    workflow_file = resolve_path(workflow_path, config_root)
    validate_file_size(workflow_file)

    try:
        with open(workflow_file, encoding="utf-8") as f:
            workflow_config: dict[str, Any] = yaml.safe_load(f)
    except yaml.YAMLError as exc:
        raise ConfigValidationError(
            f"YAML parsing failed for {workflow_file}: {exc}"
        ) from exc

    if workflow_config is None:
        raise ConfigValidationError("Empty workflow file")
    if not isinstance(workflow_config, dict):
        raise ValueError(
            f"Workflow config must be a YAML mapping, got {type(workflow_config).__name__}"
        )

    validate_structure(workflow_config, workflow_file)
    validate_schema(workflow_config)

    from temper_ai.observability.constants import EVENT_CONFIG_LOADED

    emit_lifecycle_event(
        event_bus,
        workflow_id,
        EVENT_CONFIG_LOADED,
        {
            "workflow_path": str(workflow_file),
            "stage_count": len(workflow_config.get("workflow", {}).get("stages", [])),
        },
    )

    return workflow_config, dict(input_data) if input_data else {}
