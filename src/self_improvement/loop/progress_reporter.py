"""
Progress Reporting Module for M5 Self-Improvement Loop.

Builds and reports progress information for monitoring and dashboards.
"""
import logging
from typing import Dict, Optional

from .metrics import LoopMetrics
from .models import LoopState, LoopStatus, Phase, PhaseProgress, ProgressReport

logger = logging.getLogger(__name__)


class ProgressReporter:
    """
    Build and report progress information for improvement loops.

    Aggregates state and metrics into a comprehensive progress report
    for monitoring and dashboards.
    """

    def build_progress_report(
        self,
        agent_name: str,
        state: Optional[LoopState],
        metrics: Optional[LoopMetrics],
    ) -> ProgressReport:
        """
        Build progress report from state and metrics.

        Args:
            agent_name: Name of agent
            state: Current loop state (None if not started)
            metrics: Current loop metrics (None if not started)

        Returns:
            ProgressReport with current status
        """
        if not state:
            # No state yet - return not started report
            return ProgressReport(
                agent_name=agent_name,
                current_phase=Phase.DETECT,
                current_iteration=0,
                total_iterations_completed=0,
                phase_progress={},
                health_status="not_started",
            )

        # Build phase progress map
        phase_progress = self._build_phase_progress()

        # Determine health status
        health_status = self._determine_health_status(state)

        return ProgressReport(
            agent_name=agent_name,
            current_phase=state.current_phase,
            current_iteration=state.iteration_number,
            total_iterations_completed=metrics.total_iterations if metrics else 0,
            phase_progress=phase_progress,
            health_status=health_status,
            last_success=metrics.last_iteration_at if metrics else None,
        )

    def _build_phase_progress(self) -> Dict[Phase, PhaseProgress]:
        """Build phase progress for all phases."""
        return {
            phase: PhaseProgress(phase=phase, status="not_started")
            for phase in Phase
        }

    def _determine_health_status(self, state: LoopState) -> str:
        """
        Determine health status from state.

        Args:
            state: Loop state

        Returns:
            Health status string: healthy, degraded, paused, failed
        """
        if state.status == LoopStatus.FAILED:
            return "failed"
        elif state.status == LoopStatus.PAUSED:
            return "paused"
        elif state.last_error:
            return "degraded"
        else:
            return "healthy"
