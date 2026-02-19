"""Rollout manager — gradual rollout of configuration changes via experimentation."""

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from src.autonomy.constants import DEFAULT_ROLLOUT_PHASES

logger = logging.getLogger(__name__)

STATUS_ROLLING_OUT = "rolling_out"
STATUS_COMPLETED = "completed"
STATUS_ROLLED_BACK = "rolled_back"
STATUS_PENDING = "pending"
STATUS_ACTIVE = "active"

UUID_HEX_LEN = 12
DEFAULT_VARIANT_TRAFFIC = 0.5


@dataclass
class RolloutPhase:
    """A single phase in a gradual rollout."""

    phase_index: int
    traffic_percent: int
    status: str = STATUS_PENDING  # pending, active, completed


@dataclass
class RolloutRecord:
    """Tracks a gradual rollout across multiple phases."""

    id: str
    change_id: str
    config_path: str
    phases: List[RolloutPhase] = field(default_factory=list)
    current_phase_index: int = 0
    status: str = STATUS_ROLLING_OUT  # rolling_out, completed, rolled_back
    experiment_id: Optional[str] = None


class RolloutManager:
    """Manages gradual rollout of configuration changes.

    Wraps ExperimentService to create backing experiments for
    each rollout, track phases, and check guardrails before advancing.
    """

    def __init__(self, experiment_service: Any) -> None:
        self._experiment_service = experiment_service

    def create_rollout(
        self,
        change_id: str,
        config_path: str,
        baseline_config: Dict[str, Any],
        candidate_config: Dict[str, Any],
        phases: Optional[List[int]] = None,
    ) -> RolloutRecord:
        """Create a new rollout with backing experiment.

        Args:
            change_id: Identifier for the config change being rolled out.
            config_path: Path to the configuration file.
            baseline_config: Current (control) configuration.
            candidate_config: New (candidate) configuration.
            phases: Traffic percentages per phase. Defaults to DEFAULT_ROLLOUT_PHASES.

        Returns:
            A new RolloutRecord with an associated experiment.
        """
        phase_percents = phases or list(DEFAULT_ROLLOUT_PHASES)
        rollout_phases = [
            RolloutPhase(phase_index=i, traffic_percent=pct)
            for i, pct in enumerate(phase_percents)
        ]

        rollout_id = f"rollout-{uuid.uuid4().hex[:UUID_HEX_LEN]}"

        experiment_id = self._create_backing_experiment(
            rollout_id, baseline_config, candidate_config,
        )

        record = RolloutRecord(
            id=rollout_id,
            change_id=change_id,
            config_path=config_path,
            phases=rollout_phases,
            experiment_id=experiment_id,
        )
        # Activate the first phase
        record.phases[0].status = STATUS_ACTIVE
        record.status = STATUS_ROLLING_OUT
        logger.info("Created rollout %s for change %s", rollout_id, change_id)
        return record

    def _create_backing_experiment(
        self,
        rollout_id: str,
        baseline_config: Dict[str, Any],
        candidate_config: Dict[str, Any],
    ) -> Optional[str]:
        """Create an experiment to back the rollout."""
        try:
            result: Optional[str] = self._experiment_service.create_experiment(
                name=f"rollout-{rollout_id}",
                description=f"Backing experiment for rollout {rollout_id}",
                variants=[
                    {"name": "baseline", "is_control": True, "traffic": DEFAULT_VARIANT_TRAFFIC, "config": baseline_config},
                    {"name": "candidate", "traffic": DEFAULT_VARIANT_TRAFFIC, "config": candidate_config},
                ],
            )
            return result
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to create backing experiment: %s", exc)
            return None

    def advance_phase(self, rollout: RolloutRecord) -> RolloutPhase:
        """Advance the rollout to the next phase.

        Marks the current phase as completed and activates the next.

        Returns:
            The newly activated RolloutPhase.

        Raises:
            ValueError: If rollout is already on the last phase.
        """
        current = rollout.current_phase_index
        if current >= len(rollout.phases) - 1:
            raise ValueError("Already on the final phase; use complete_rollout instead")

        rollout.phases[current].status = STATUS_COMPLETED
        next_index = current + 1
        rollout.current_phase_index = next_index
        rollout.phases[next_index].status = STATUS_ACTIVE
        logger.info(
            "Rollout %s advanced to phase %d (%d%% traffic)",
            rollout.id,
            next_index,
            rollout.phases[next_index].traffic_percent,
        )
        return rollout.phases[next_index]

    def check_guardrails(self, rollout: RolloutRecord) -> bool:
        """Check whether it is safe to continue the rollout.

        Delegates to the experiment service's early stopping check
        when a backing experiment exists.

        Returns:
            True if safe to continue, False if guardrails triggered.
        """
        if rollout.experiment_id is None:
            return True
        try:
            result = self._experiment_service.check_early_stopping(
                rollout.experiment_id,
            )
            return not result.get("should_stop", False)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Guardrail check failed for %s: %s", rollout.id, exc)
            return False

    def complete_rollout(self, rollout: RolloutRecord) -> None:
        """Mark the rollout as completed and stop the backing experiment."""
        rollout.status = STATUS_COMPLETED
        for phase in rollout.phases:
            if phase.status != STATUS_COMPLETED:
                phase.status = STATUS_COMPLETED
        self._stop_experiment(rollout)
        logger.info("Rollout %s completed", rollout.id)

    def rollback_rollout(self, rollout: RolloutRecord) -> None:
        """Roll back the rollout and stop the backing experiment."""
        rollout.status = STATUS_ROLLED_BACK
        self._stop_experiment(rollout)
        logger.info("Rollout %s rolled back", rollout.id)

    def _stop_experiment(self, rollout: RolloutRecord) -> None:
        """Stop the backing experiment if one exists."""
        if rollout.experiment_id is None:
            return
        try:
            self._experiment_service.stop_experiment(rollout.experiment_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Failed to stop experiment for rollout %s: %s",
                rollout.id,
                exc,
            )
