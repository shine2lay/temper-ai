"""Lifecycle experimentation via A/B testing.

Wraps ExperimentService to enable A/B testing of lifecycle profiles:
control variant = no adaptation (baseline), treatment = named profile.
"""

import logging
from typing import Any

from temper_ai.lifecycle._schemas import LifecycleProfile

logger = logging.getLogger(__name__)

VARIANT_CONTROL = "control"


class LifecycleExperimenter:
    """A/B testing for lifecycle adaptation profiles.

    Wraps the existing ExperimentService to assign variants
    and track outcomes for lifecycle experiments.
    """

    def __init__(self, experiment_service: Any) -> None:
        self._service = experiment_service

    def _resolve_variant_name(self, experiment_id: str, variant_id: str) -> str:
        """Return the human-readable name for a variant_id.

        Looks up the experiment's variants list to find the matching name.
        Falls back to variant_id if the experiment or variant cannot be loaded.
        """
        try:
            experiment = self._service.get_experiment(experiment_id)
            if experiment is None:
                return variant_id
            for variant in getattr(experiment, "variants", []):
                if variant.id == variant_id:
                    return variant.name
        except Exception:  # noqa: BLE001 -- best-effort lookup
            pass
        return variant_id

    def get_adapted_profile(
        self,
        experiment_id: str,
        workflow_id: str,
        available_profiles: dict[str, LifecycleProfile] | None = None,
    ) -> LifecycleProfile | None:
        """Assign variant and return profile (None = control/baseline).

        Args:
            experiment_id: ID of the experiment.
            workflow_id: Current workflow execution ID.
            available_profiles: Dict of profile_name -> LifecycleProfile.

        Returns:
            LifecycleProfile for the assigned variant, or None for control.
        """
        try:
            assignment = self._service.assign_variant(workflow_id, experiment_id)
            if assignment is None:
                return None

            variant_name = self._resolve_variant_name(
                experiment_id, assignment.variant_id
            )
            if variant_name == VARIANT_CONTROL:
                logger.info(
                    "Experiment %s: assigned control (no adaptation)",
                    experiment_id,
                )
                return None

            if available_profiles and variant_name in available_profiles:
                logger.info(
                    "Experiment %s: assigned variant %s",
                    experiment_id,
                    variant_name,
                )
                return available_profiles[variant_name]

            logger.warning(
                "Experiment %s: variant %s not found in profiles",
                experiment_id,
                variant_name,
            )
            return None
        except Exception:  # noqa: BLE001 -- experiments are optional
            logger.warning(
                "Experiment assignment failed for %s",
                experiment_id,
                exc_info=True,
            )
            return None

    def track_outcome(
        self,
        experiment_id: str,
        workflow_id: str,
        metrics: dict[str, float],
    ) -> None:
        """Record workflow outcome metrics for experiment analysis.

        Args:
            experiment_id: ID of the experiment.
            workflow_id: Workflow execution ID.
            metrics: Dict of metric_name -> value (e.g., duration_seconds).
        """
        try:
            self._service.track_execution_complete(
                workflow_id,
                metrics,
            )
            logger.info(
                "Recorded experiment metrics for %s/%s",
                experiment_id,
                workflow_id,
            )
        except Exception:  # noqa: BLE001 -- tracking is best-effort
            logger.warning(
                "Failed to record experiment metrics",
                exc_info=True,
            )
