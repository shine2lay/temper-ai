"""
Metrics collection for M5 Self-Improvement Loop.

Tracks phase execution times, success/failure rates, and iteration metrics.
"""
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional
from dataclasses import dataclass, field

from .models import Phase, IterationResult

logger = logging.getLogger(__name__)


@dataclass
class LoopMetrics:
    """Aggregated metrics for an agent's improvement loop."""
    agent_name: str
    total_iterations: int = 0
    successful_iterations: int = 0
    failed_iterations: int = 0

    # Phase metrics
    phase_executions: Dict[Phase, int] = field(default_factory=dict)
    phase_successes: Dict[Phase, int] = field(default_factory=dict)
    phase_failures: Dict[Phase, int] = field(default_factory=dict)
    phase_durations: Dict[Phase, list] = field(default_factory=dict)

    # Improvement metrics
    total_experiments: int = 0
    successful_deployments: int = 0
    rollbacks: int = 0

    # Timing
    avg_iteration_duration: float = 0.0
    last_iteration_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert metrics to dictionary."""
        return {
            "agent_name": self.agent_name,
            "total_iterations": self.total_iterations,
            "successful_iterations": self.successful_iterations,
            "failed_iterations": self.failed_iterations,
            "success_rate": self.successful_iterations / max(self.total_iterations, 1),
            "phase_executions": {p.value: c for p, c in self.phase_executions.items()},
            "phase_successes": {p.value: c for p, c in self.phase_successes.items()},
            "phase_failures": {p.value: c for p, c in self.phase_failures.items()},
            "phase_success_rates": self._calculate_phase_success_rates(),
            "phase_avg_durations": self._calculate_avg_durations(),
            "total_experiments": self.total_experiments,
            "successful_deployments": self.successful_deployments,
            "rollbacks": self.rollbacks,
            "avg_iteration_duration": self.avg_iteration_duration,
            "last_iteration_at": self.last_iteration_at.isoformat() if self.last_iteration_at else None,
        }

    def _calculate_phase_success_rates(self) -> Dict[str, float]:
        """Calculate success rate for each phase."""
        rates = {}
        for phase in Phase:
            executions = self.phase_executions.get(phase, 0)
            successes = self.phase_successes.get(phase, 0)
            rates[phase.value] = successes / max(executions, 1)
        return rates

    def _calculate_avg_durations(self) -> Dict[str, float]:
        """Calculate average duration for each phase."""
        avgs = {}
        for phase, durations in self.phase_durations.items():
            if durations:
                avgs[phase.value] = sum(durations) / len(durations)
            else:
                avgs[phase.value] = 0.0
        return avgs


class MetricsCollector:
    """
    Collect and aggregate loop execution metrics.

    Tracks phase execution times, success/failure counts, and provides
    aggregated metrics for monitoring and dashboards.
    """

    def __init__(self):
        """Initialize metrics collector."""
        self._metrics: Dict[str, LoopMetrics] = {}
        self._phase_starts: Dict[str, Dict[Phase, datetime]] = {}

    def record_phase_start(self, agent_name: str, phase: Phase) -> None:
        """
        Record phase start time.

        Args:
            agent_name: Name of agent
            phase: Phase being started
        """
        if agent_name not in self._phase_starts:
            self._phase_starts[agent_name] = {}

        self._phase_starts[agent_name][phase] = datetime.now(timezone.utc)

        # Initialize metrics if needed
        if agent_name not in self._metrics:
            self._metrics[agent_name] = LoopMetrics(agent_name=agent_name)

        metrics = self._metrics[agent_name]
        metrics.phase_executions[phase] = metrics.phase_executions.get(phase, 0) + 1

        logger.debug(f"Phase {phase.value} started for {agent_name}")

    def record_phase_complete(
        self,
        agent_name: str,
        phase: Phase,
        duration: Optional[float] = None
    ) -> None:
        """
        Record phase completion.

        Args:
            agent_name: Name of agent
            phase: Phase that completed
            duration: Optional duration override (otherwise calculated from start)
        """
        metrics = self._metrics.get(agent_name)
        if not metrics:
            logger.warning(f"No metrics found for {agent_name}")
            return

        # Calculate duration if not provided
        if duration is None:
            start_time = self._phase_starts.get(agent_name, {}).get(phase)
            if start_time:
                duration = (datetime.now(timezone.utc) - start_time).total_seconds()
            else:
                duration = 0.0

        # Record success
        metrics.phase_successes[phase] = metrics.phase_successes.get(phase, 0) + 1

        # Record duration
        if phase not in metrics.phase_durations:
            metrics.phase_durations[phase] = []
        metrics.phase_durations[phase].append(duration)

        logger.debug(f"Phase {phase.value} completed for {agent_name} in {duration:.1f}s")

    def record_phase_error(
        self,
        agent_name: str,
        phase: Phase,
        error: Exception
    ) -> None:
        """
        Record phase error.

        Args:
            agent_name: Name of agent
            phase: Phase that failed
            error: Exception that occurred
        """
        metrics = self._metrics.get(agent_name)
        if not metrics:
            logger.warning(f"No metrics found for {agent_name}")
            return

        metrics.phase_failures[phase] = metrics.phase_failures.get(phase, 0) + 1

        logger.debug(f"Phase {phase.value} failed for {agent_name}: {error}")

    def record_iteration_complete(
        self,
        agent_name: str,
        result: IterationResult
    ) -> None:
        """
        Record iteration completion.

        Args:
            agent_name: Name of agent
            result: Iteration result
        """
        metrics = self._metrics.get(agent_name)
        if not metrics:
            metrics = LoopMetrics(agent_name=agent_name)
            self._metrics[agent_name] = metrics

        # Update iteration counts
        metrics.total_iterations += 1
        if result.success:
            metrics.successful_iterations += 1
        else:
            metrics.failed_iterations += 1

        # Update timing
        metrics.last_iteration_at = result.timestamp

        # Update average duration
        total_duration = (
            metrics.avg_iteration_duration * (metrics.total_iterations - 1) +
            result.duration_seconds
        )
        metrics.avg_iteration_duration = total_duration / metrics.total_iterations

        # Update specific metrics
        if result.experiment_result:
            metrics.total_experiments += 1

        if result.deployment_result:
            metrics.successful_deployments += 1

        logger.info(
            f"Iteration {result.iteration_number} for {agent_name}: "
            f"{'SUCCESS' if result.success else 'FAILED'} in {result.duration_seconds:.1f}s"
        )

    def record_rollback(self, agent_name: str) -> None:
        """
        Record deployment rollback.

        Args:
            agent_name: Name of agent
        """
        metrics = self._metrics.get(agent_name)
        if not metrics:
            logger.warning(f"No metrics found for {agent_name}")
            return

        metrics.rollbacks += 1
        logger.info(f"Rollback recorded for {agent_name}")

    def get_metrics(self, agent_name: str) -> Optional[LoopMetrics]:
        """
        Get aggregated metrics for agent.

        Args:
            agent_name: Name of agent

        Returns:
            LoopMetrics if available, None otherwise
        """
        return self._metrics.get(agent_name)

    def get_all_metrics(self) -> Dict[str, LoopMetrics]:
        """
        Get metrics for all agents.

        Returns:
            Dictionary mapping agent_name to LoopMetrics
        """
        return self._metrics.copy()

    def reset_metrics(self, agent_name: str) -> None:
        """
        Reset metrics for agent.

        Args:
            agent_name: Name of agent
        """
        if agent_name in self._metrics:
            del self._metrics[agent_name]
        if agent_name in self._phase_starts:
            del self._phase_starts[agent_name]
        logger.info(f"Reset metrics for {agent_name}")

    def export_metrics(self, agent_name: str) -> Dict[str, Any]:
        """
        Export metrics in dictionary format.

        Args:
            agent_name: Name of agent

        Returns:
            Metrics as dictionary
        """
        metrics = self.get_metrics(agent_name)
        if not metrics:
            return {
                "agent_name": agent_name,
                "no_data": True
            }
        return metrics.to_dict()
