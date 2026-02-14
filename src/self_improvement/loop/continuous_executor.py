"""
Continuous Execution Module for M5 Self-Improvement Loop.

Manages continuous improvement loops with convergence detection,
signal handling, and budget enforcement.
"""
import logging
import signal
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from src.constants.durations import SECONDS_PER_HOUR, SECONDS_PER_MINUTE
from src.constants.limits import THRESHOLD_SMALL_COUNT

from .config import LoopConfig
from .models import IterationResult

logger = logging.getLogger(__name__)


@dataclass
class ContinuousExecutionStats:
    """Statistics collected during continuous execution."""
    total_iterations: int = 0
    successful_iterations: int = 0
    failed_iterations: int = 0
    total_deployments: int = 0
    total_cost: float = 0.0
    iterations_without_deployment: int = 0
    agents: Dict[str, Dict[str, int]] = field(default_factory=dict)
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    stopped_at: Optional[datetime] = None
    stop_reason: Optional[str] = None


def _build_result_dict(stats: ContinuousExecutionStats) -> Dict[str, Any]:
    """Build the result dictionary from execution stats.

    Args:
        stats: Collected execution statistics.

    Returns:
        Dictionary with execution summary.
    """
    return {
        "total_iterations": stats.total_iterations,
        "successful_iterations": stats.successful_iterations,
        "failed_iterations": stats.failed_iterations,
        "total_deployments": stats.total_deployments,
        "total_cost": stats.total_cost,
        "iterations_without_deployment": stats.iterations_without_deployment,
        "agents": stats.agents,
        "started_at": stats.started_at.isoformat(),
        "stopped_at": stats.stopped_at.isoformat() if stats.stopped_at else None,
        "stop_reason": stats.stop_reason,
    }


class ContinuousExecutor:
    """
    Execute continuous improvement loop with convergence detection.

    Manages the main loop that repeatedly runs improvement iterations,
    detects convergence, enforces budgets, and handles graceful shutdown.
    """

    def __init__(
        self,
        config: LoopConfig,
        run_iteration_fn: Callable[[str], IterationResult],
    ):
        """
        Initialize continuous executor.

        Args:
            config: Loop configuration
            run_iteration_fn: Callable that runs one iteration (signature: (agent_name) -> IterationResult)
        """
        self.config = config
        self.run_iteration_fn = run_iteration_fn

    def _setup_signal_handlers(self, shutdown_requested: Dict[str, bool]) -> None:
        """Setup signal handlers for graceful shutdown."""
        def signal_handler(signum: int, _frame: Any) -> None:
            """Handle interrupt signals for graceful shutdown."""
            logger.info(f"Received signal {signum}, requesting graceful shutdown...")
            shutdown_requested["flag"] = True

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

    def _restore_signal_handlers(self) -> None:
        """Restore default signal handlers."""
        signal.signal(signal.SIGINT, signal.SIG_DFL)
        signal.signal(signal.SIGTERM, signal.SIG_DFL)

    def _run_main_loop(
        self,
        agent_names: List[str],
        stats: ContinuousExecutionStats,
        interval_minutes: int,
        max_iterations: Optional[int],
        cost_budget: Optional[float],
        convergence_window: int,
        shutdown_requested: Dict[str, bool]
    ) -> None:
        """Run the main continuous improvement loop."""
        iteration = 0
        while True:
            iteration += 1
            stats.total_iterations = iteration

            logger.info(f"\n{'='*60}")
            logger.info(f"Continuous mode - Iteration {iteration}")
            logger.info(f"{'='*60}")

            # Execute iteration for each agent
            iteration_had_deployment = self._execute_agent_iterations(
                agent_names, stats, shutdown_requested
            )

            # Update convergence tracking
            stats.iterations_without_deployment = (
                0 if iteration_had_deployment
                else stats.iterations_without_deployment + 1
            )

            # Check stopping conditions
            if self._should_stop(stats, max_iterations, cost_budget,
                                convergence_window, shutdown_requested["flag"]):
                break

            # Log progress
            self._log_iteration_complete(stats, iteration)

            # Sleep with shutdown checks
            if not self._wait_for_next_iteration(interval_minutes, shutdown_requested):
                stats.stop_reason = "manual_interrupt"
                break

    def execute(
        self,
        agent_names: List[str],
        check_interval_minutes: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Execute continuous improvement loop."""
        if not agent_names:
            raise ValueError("agent_names is required for continuous mode")

        # Resolve configuration
        interval_minutes = check_interval_minutes or self.config.continuous_check_interval_minutes
        max_iterations = self.config.continuous_max_iterations
        cost_budget = self.config.continuous_cost_budget
        convergence_window = self.config.continuous_convergence_window

        logger.info(
            f"Starting continuous improvement loop for {len(agent_names)} agent(s): "
            f"{', '.join(agent_names)}"
        )
        logger.info(
            f"Config: interval={interval_minutes}min, max_iterations={max_iterations}, "
            f"cost_budget={cost_budget}, convergence_window={convergence_window}"
        )

        # Initialize stats
        stats = ContinuousExecutionStats(
            agents={name: {"iterations": 0, "deployments": 0} for name in agent_names}
        )

        shutdown_requested = {"flag": False}
        self._setup_signal_handlers(shutdown_requested)

        try:
            self._run_main_loop(
                agent_names, stats, interval_minutes, max_iterations,
                cost_budget, convergence_window, shutdown_requested
            )
        except KeyboardInterrupt:
            logger.info("KeyboardInterrupt received, stopping gracefully")
            stats.stop_reason = "keyboard_interrupt"
        except Exception as e:
            logger.error(f"Unexpected error in continuous loop: {e}", exc_info=True)
            stats.stop_reason = f"error: {str(e)}"
        finally:
            self._restore_signal_handlers()
            stats.stopped_at = datetime.now(timezone.utc)
            self._log_final_summary(stats)

        return _build_result_dict(stats)

    def _should_stop(
        self,
        stats: ContinuousExecutionStats,
        max_iterations: Optional[int],
        cost_budget: Optional[float],
        convergence_window: int,
        shutdown_requested: bool,
    ) -> bool:
        """Check if loop should stop."""
        if max_iterations and stats.total_iterations >= max_iterations:
            logger.info(f"Reached max iterations ({max_iterations}), stopping")
            stats.stop_reason = "max_iterations_reached"
            return True

        if shutdown_requested:
            logger.info("Shutdown requested, stopping gracefully")
            stats.stop_reason = "manual_interrupt"
            return True

        if stats.iterations_without_deployment >= convergence_window:
            logger.info(
                f"Convergence detected: {convergence_window} iterations without "
                f"deployment, stopping"
            )
            stats.stop_reason = "converged"
            return True

        if cost_budget and stats.total_cost >= cost_budget:
            logger.info(
                f"Cost budget exhausted: ${stats.total_cost:.2f} >= "
                f"${cost_budget:.2f}, stopping"
            )
            stats.stop_reason = "cost_budget_exceeded"
            return True

        return False

    def _execute_agent_iterations(
        self,
        agent_names: List[str],
        stats: ContinuousExecutionStats,
        shutdown_requested: Dict[str, bool],
    ) -> bool:
        """Execute one iteration for each agent. Returns True if any deployed."""
        iteration_had_deployment = False

        for agent_name in agent_names:
            logger.info(f"Running iteration for agent: {agent_name}")

            try:
                result = self.run_iteration_fn(agent_name)
                stats.agents[agent_name]["iterations"] += 1

                if result.success:
                    stats.successful_iterations += 1

                    if result.deployment_result:
                        stats.total_deployments += 1
                        stats.agents[agent_name]["deployments"] += 1
                        iteration_had_deployment = True
                        logger.info(
                            f"✓ Deployment {stats.total_deployments} completed "
                            f"for {agent_name}"
                        )
                    else:
                        logger.info(f"✓ Iteration completed for {agent_name} (no deployment)")
                else:
                    stats.failed_iterations += 1
                    logger.warning(f"✗ Iteration failed for {agent_name}: {result.error}")

            except Exception as e:
                stats.failed_iterations += 1
                logger.error(f"Error running iteration for {agent_name}: {e}", exc_info=True)

            # Check for shutdown between agents
            if shutdown_requested["flag"]:
                break

        return iteration_had_deployment

    def _wait_for_next_iteration(
        self,
        interval_minutes: int,
        shutdown_requested: Dict[str, bool],
    ) -> bool:
        """
        Wait for next iteration check, with periodic shutdown checks.

        Returns:
            False if shutdown was requested, True otherwise
        """
        logger.info(f"Sleeping for {interval_minutes} minutes...")
        sleep_seconds = interval_minutes * SECONDS_PER_MINUTE
        sleep_start = time.time()

        while time.time() - sleep_start < sleep_seconds:
            if shutdown_requested["flag"]:
                return False
            time.sleep(min(THRESHOLD_SMALL_COUNT, sleep_seconds - (time.time() - sleep_start)))  # Intentional blocking: interval sleep with periodic shutdown checks in sync continuous loop

        return True

    def _log_iteration_complete(self, stats: ContinuousExecutionStats, iteration: int) -> None:
        """Log iteration completion summary."""
        logger.info(
            f"\nIteration {iteration} complete - "
            f"Success: {stats.successful_iterations}, "
            f"Failed: {stats.failed_iterations}, "
            f"Deployments: {stats.total_deployments}, "
            f"No-deploy streak: {stats.iterations_without_deployment}"
        )

    def _log_final_summary(self, stats: ContinuousExecutionStats) -> None:
        """Log final execution summary."""
        duration = (stats.stopped_at - stats.started_at).total_seconds() if stats.stopped_at and stats.started_at else 0.0

        logger.info(f"\n{'='*60}")
        logger.info("Continuous improvement loop stopped")
        logger.info(f"{'='*60}")
        logger.info(f"Stop reason: {stats.stop_reason}")
        logger.info(f"Duration: {duration:.1f}s ({duration/SECONDS_PER_HOUR:.1f} hours)")
        logger.info(f"Total iterations: {stats.total_iterations}")
        logger.info(f"Successful: {stats.successful_iterations}")
        logger.info(f"Failed: {stats.failed_iterations}")
        logger.info(f"Total deployments: {stats.total_deployments}")
        logger.info(f"Final no-deploy streak: {stats.iterations_without_deployment}")
        logger.info("\nPer-agent stats:")
        for agent_name, agent_stats in stats.agents.items():
            logger.info(
                f"  {agent_name}: {agent_stats['iterations']} iterations, "
                f"{agent_stats['deployments']} deployments"
            )
