"""Experiment-workflow integration — variant assignment and config merging."""

import logging
from typing import Any

logger = logging.getLogger(__name__)


def assign_and_merge(
    experiment_id: str,
    workflow_id: str,
    workflow_config: dict[str, Any],
) -> tuple[dict[str, Any], str | None]:
    """Assign variant and merge config overrides into workflow config.

    Args:
        experiment_id: Experiment to assign from.
        workflow_id: Current workflow execution ID.
        workflow_config: Base workflow configuration dict.

    Returns:
        (merged_config, variant_id) tuple. If assignment fails or has no
        overrides, returns (original_config, variant_id).
    """
    from temper_ai.experimentation.config_manager import ConfigManager
    from temper_ai.experimentation.service import ExperimentService

    service = ExperimentService()
    assignment = service.assign_variant(workflow_id, experiment_id)
    if assignment is None:
        return workflow_config, None

    variant_id = assignment.variant_id

    experiment = service.get_experiment(experiment_id)
    if experiment is None:
        return workflow_config, variant_id

    overrides = _extract_variant_overrides(experiment, variant_id)
    if not overrides:
        return workflow_config, variant_id

    manager = ConfigManager()
    merged = manager.apply_overrides_safely(workflow_config, overrides)
    return merged, variant_id


def _extract_variant_overrides(
    experiment: Any,
    variant_id: str,
) -> dict[str, Any]:
    """Extract config_overrides from the matching variant."""
    for variant in getattr(experiment, "variants", []):
        if str(variant.id) == str(variant_id):
            overrides = getattr(variant, "config_overrides", None)
            if overrides and isinstance(overrides, dict):
                return overrides
    return {}


def track_experiment_completion(
    experiment_id: str,
    workflow_id: str,
    result: dict[str, Any],
    duration_seconds: float,
) -> None:
    """Track workflow completion metrics for experiment analysis.

    Args:
        experiment_id: Experiment being tracked.
        workflow_id: Workflow execution ID.
        result: Workflow result dict.
        duration_seconds: Total workflow duration.
    """
    from temper_ai.experimentation.service import ExperimentService

    service = ExperimentService()
    metrics: dict[str, float] = {
        "duration_seconds": duration_seconds,
    }

    if isinstance(result, dict):
        for key in ("total_tokens", "total_cost"):
            if key in result:
                metrics[key] = float(result[key])

    service.track_execution_complete(
        workflow_id=workflow_id,
        metrics=metrics,
    )
    logger.info(
        "Tracked experiment completion: experiment=%s workflow=%s",
        experiment_id,
        workflow_id,
    )
