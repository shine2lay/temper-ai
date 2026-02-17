"""Lifecycle experimentation via A/B testing.

Wraps ExperimentService to enable A/B testing of lifecycle profiles:
control variant = no adaptation (baseline), treatment = named profile.
"""

import logging
from typing import Any, Dict, Optional

from src.lifecycle._schemas import LifecycleProfile

logger = logging.getLogger(__name__)


class LifecycleExperimenter:
    """A/B testing for lifecycle adaptation profiles.

    Wraps the existing ExperimentService to assign variants
    and track outcomes for lifecycle experiments.
    """

    def __init__(self, experiment_service: Any) -> None:
        self._service = experiment_service

    def get_adapted_profile(
        self,
        experiment_id: str,
        workflow_id: str,
        available_profiles: Optional[Dict[str, LifecycleProfile]] = None,
    ) -> Optional[LifecycleProfile]:
        """Assign variant and return profile (None = control/baseline).

        Args:
            experiment_id: ID of the experiment.
            workflow_id: Current workflow execution ID.
            available_profiles: Dict of profile_name -> LifecycleProfile.

        Returns:
            LifecycleProfile for the assigned variant, or None for control.
        """
        try:
            assignment = self._service.assign_variant(
                workflow_id, experiment_id
            )
            if assignment is None:
                return None

            variant_name = assignment.variant_name
            if variant_name == "control":
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
        metrics: Dict[str, float],
    ) -> None:
        """Record workflow outcome metrics for experiment analysis.

        Args:
            experiment_id: ID of the experiment.
            workflow_id: Workflow execution ID.
            metrics: Dict of metric_name -> value (e.g., duration_seconds).
        """
        try:
            self._service.record_metric(
                workflow_id,
                experiment_id,
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
