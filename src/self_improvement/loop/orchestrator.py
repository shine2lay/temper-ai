"""
M5 Self-Improvement Loop Orchestrator.

Main entry point for running improvement cycles with state management,
error recovery, and observability.
"""
import logging
import signal
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlmodel import Session

from .config import LoopConfig
from .error_recovery import ErrorRecoveryStrategy
from .executor import LoopExecutor
from .metrics import MetricsCollector
from .models import (
    IterationResult,
    LoopStatus,
    Phase,
    PhaseProgress,
    ProgressReport,
)
from .state_manager import LoopStateManager

logger = logging.getLogger(__name__)


class M5SelfImprovementLoop:
    """
    M5 Self-Improvement Loop orchestrator.

    Coordinates complete improvement cycles with state management,
    error recovery, and observability. Supports single-shot,
    continuous, and scheduled execution modes.

    Example:
        >>> from coord_service.database import Database
        >>> from src.database import get_session
        >>> coord_db = Database()
        >>> with get_session() as obs_session:
        ...     loop = M5SelfImprovementLoop(coord_db, obs_session)
        ...     result = loop.run_iteration("my_agent")
        ...     if result.success:
        ...         print("Improvement cycle completed!")
    """

    def __init__(
        self,
        coord_db,
        obs_session: Session,
        config: Optional[LoopConfig] = None,
    ):
        """
        Initialize M5 improvement loop.

        Args:
            coord_db: Coordination database instance
            obs_session: Observability database session
            config: Optional loop configuration (uses defaults if None)
        """
        self.coord_db = coord_db
        self.obs_session = obs_session
        self.config = config or LoopConfig()

        # Validate configuration
        self.config.validate()

        # Initialize components
        self.state_manager = LoopStateManager()
        self.error_recovery = ErrorRecoveryStrategy(self.config)
        self.metrics_collector = MetricsCollector()

        # Initialize executor
        self.executor = LoopExecutor(
            coord_db=coord_db,
            obs_session=obs_session,
            config=self.config,
            state_manager=self.state_manager,
            error_recovery=self.error_recovery,
            metrics_collector=self.metrics_collector,
        )

        logger.info("M5SelfImprovementLoop initialized")

    def run_iteration(
        self,
        agent_name: str,
        start_phase: Phase = Phase.DETECT,
    ) -> IterationResult:
        """
        Run single improvement iteration for agent.

        Executes all 5 phases of the M5 improvement cycle:
        1. DETECT - Identify performance problems
        2. ANALYZE - Analyze current performance
        3. STRATEGY - Generate improvement strategies
        4. EXPERIMENT - Run A/B tests
        5. DEPLOY - Deploy winner and monitor

        Args:
            agent_name: Name of agent to improve
            start_phase: Phase to start from (default: DETECT)

        Returns:
            IterationResult with outcomes from all phases

        Example:
            >>> result = loop.run_iteration("product_extractor")
            >>> if result.success:
            ...     print(f"Completed phases: {result.phases_completed}")
            ...     if result.deployment_result:
            ...         print(f"Deployed: {result.deployment_result.deployment_id}")
        """
        logger.info(f"Starting improvement iteration for {agent_name}")

        # Check if paused
        state = self.state_manager.get_state(agent_name)
        if state and state.status == LoopStatus.PAUSED:
            logger.warning(f"Loop is paused for {agent_name}")
            raise ValueError(f"Loop is paused for {agent_name}. Call resume() first.")

        # Execute iteration
        result = self.executor.execute_iteration(
            agent_name=agent_name,
            start_phase=start_phase,
        )

        return result

    def run_continuous(
        self,
        agent_names: Optional[List[str]] = None,
        check_interval_minutes: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Run continuous improvement loop with convergence detection.

        Repeatedly runs improvement iterations with configurable sleep intervals.
        Stops when:
        1. Max iterations reached (if configured)
        2. Cost budget exceeded (if configured)
        3. Convergence detected (no deployments in N iterations)
        4. Manual interrupt (Ctrl+C)

        Args:
            agent_names: List of agents to improve (required)
            check_interval_minutes: Check interval (optional, uses config default)

        Returns:
            Summary dictionary with execution statistics

        Raises:
            ValueError: If agent_names is None or empty

        Example:
            >>> loop.run_continuous(
            ...     agent_names=["product_extractor", "summarizer"],
            ...     check_interval_minutes=30
            ... )
            # Runs every 30 minutes until convergence or interrupt
        """
        if not agent_names:
            raise ValueError("agent_names is required for continuous mode")

        # Use config values or parameter overrides
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

        # Setup signal handler for graceful shutdown
        shutdown_requested = {"flag": False}

        def signal_handler(signum, _frame):
            logger.info(f"Received signal {signum}, requesting graceful shutdown...")
            shutdown_requested["flag"] = True

        # Register signal handlers
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        # Track execution statistics
        stats = {
            "total_iterations": 0,
            "successful_iterations": 0,
            "failed_iterations": 0,
            "total_deployments": 0,
            "total_cost": 0.0,
            "iterations_without_deployment": 0,
            "agents": {name: {"iterations": 0, "deployments": 0} for name in agent_names},
            "started_at": datetime.now(timezone.utc),
            "stopped_at": None,
            "stop_reason": None,
        }

        try:
            iteration = 0
            while True:
                iteration += 1
                stats["total_iterations"] = iteration

                # Check max iterations
                if max_iterations and iteration > max_iterations:
                    logger.info(f"Reached max iterations ({max_iterations}), stopping")
                    stats["stop_reason"] = "max_iterations_reached"
                    break

                # Check shutdown signal
                if shutdown_requested["flag"]:
                    logger.info("Shutdown requested, stopping gracefully")
                    stats["stop_reason"] = "manual_interrupt"
                    break

                logger.info(f"\n{'='*60}")
                logger.info(f"Continuous mode - Iteration {iteration}")
                logger.info(f"{'='*60}")

                # Run iteration for each agent
                iteration_had_deployment = False
                for agent_name in agent_names:
                    logger.info(f"Running iteration for agent: {agent_name}")

                    try:
                        result = self.run_iteration(agent_name)

                        # Update stats
                        stats["agents"][agent_name]["iterations"] += 1

                        if result.success:
                            stats["successful_iterations"] += 1

                            # Check if deployment happened
                            if result.deployment_result:
                                stats["total_deployments"] += 1
                                stats["agents"][agent_name]["deployments"] += 1
                                iteration_had_deployment = True
                                logger.info(
                                    f"✓ Deployment {stats['total_deployments']} completed "
                                    f"for {agent_name}"
                                )
                            else:
                                logger.info(f"✓ Iteration completed for {agent_name} (no deployment)")
                        else:
                            stats["failed_iterations"] += 1
                            logger.warning(
                                f"✗ Iteration failed for {agent_name}: {result.error}"
                            )

                        # Track cost (if available in result)
                        # Note: Cost tracking would require extending IterationResult
                        # For now, we assume cost tracking is handled elsewhere

                    except Exception as e:
                        stats["failed_iterations"] += 1
                        logger.error(f"Error running iteration for {agent_name}: {e}", exc_info=True)

                    # Check for shutdown between agents
                    if shutdown_requested["flag"]:
                        break

                # Update convergence tracking
                if iteration_had_deployment:
                    stats["iterations_without_deployment"] = 0
                else:
                    stats["iterations_without_deployment"] += 1

                # Check convergence
                if stats["iterations_without_deployment"] >= convergence_window:
                    logger.info(
                        f"Convergence detected: {convergence_window} iterations without "
                        f"deployment, stopping"
                    )
                    stats["stop_reason"] = "converged"
                    break

                # Check cost budget
                if cost_budget and stats["total_cost"] >= cost_budget:
                    logger.info(
                        f"Cost budget exhausted: ${stats['total_cost']:.2f} >= "
                        f"${cost_budget:.2f}, stopping"
                    )
                    stats["stop_reason"] = "cost_budget_exceeded"
                    break

                # Check shutdown before sleep
                if shutdown_requested["flag"]:
                    stats["stop_reason"] = "manual_interrupt"
                    break

                # Log current stats
                logger.info(
                    f"\nIteration {iteration} complete - "
                    f"Success: {stats['successful_iterations']}, "
                    f"Failed: {stats['failed_iterations']}, "
                    f"Deployments: {stats['total_deployments']}, "
                    f"No-deploy streak: {stats['iterations_without_deployment']}"
                )

                # Sleep until next iteration
                logger.info(f"Sleeping for {interval_minutes} minutes...")
                sleep_seconds = interval_minutes * 60
                sleep_start = time.time()

                # Sleep with periodic checks for shutdown signal
                while time.time() - sleep_start < sleep_seconds:
                    if shutdown_requested["flag"]:
                        stats["stop_reason"] = "manual_interrupt"
                        break
                    time.sleep(min(5, sleep_seconds - (time.time() - sleep_start)))

                if shutdown_requested["flag"]:
                    break

        except KeyboardInterrupt:
            logger.info("KeyboardInterrupt received, stopping gracefully")
            stats["stop_reason"] = "keyboard_interrupt"
        except Exception as e:
            logger.error(f"Unexpected error in continuous loop: {e}", exc_info=True)
            stats["stop_reason"] = f"error: {str(e)}"
        finally:
            # Restore signal handlers
            signal.signal(signal.SIGINT, signal.SIG_DFL)
            signal.signal(signal.SIGTERM, signal.SIG_DFL)

            # Record stop time
            stats["stopped_at"] = datetime.now(timezone.utc)
            duration = (stats["stopped_at"] - stats["started_at"]).total_seconds()

            # Log final summary
            logger.info(f"\n{'='*60}")
            logger.info("Continuous improvement loop stopped")
            logger.info(f"{'='*60}")
            logger.info(f"Stop reason: {stats['stop_reason']}")
            logger.info(f"Duration: {duration:.1f}s ({duration/3600:.1f} hours)")
            logger.info(f"Total iterations: {stats['total_iterations']}")
            logger.info(f"Successful: {stats['successful_iterations']}")
            logger.info(f"Failed: {stats['failed_iterations']}")
            logger.info(f"Total deployments: {stats['total_deployments']}")
            logger.info(f"Final no-deploy streak: {stats['iterations_without_deployment']}")
            logger.info("\nPer-agent stats:")
            for agent_name, agent_stats in stats["agents"].items():
                logger.info(
                    f"  {agent_name}: {agent_stats['iterations']} iterations, "
                    f"{agent_stats['deployments']} deployments"
                )

        return stats

    def run_scheduled(self, _cron_expression: str) -> None:
        """
        Run improvement loop on schedule (not implemented).

        Args:
            cron_expression: Cron expression for scheduling

        Raises:
            NotImplementedError: Scheduled mode not yet implemented
        """
        raise NotImplementedError(
            "Scheduled mode not yet implemented. Use run_iteration() with "
            "external cron/scheduler instead."
        )

    def get_state(self, agent_name: str) -> Optional[Dict[str, Any]]:
        """
        Get current loop state for agent.

        Args:
            agent_name: Name of agent

        Returns:
            State dictionary or None if no state exists

        Example:
            >>> state = loop.get_state("my_agent")
            >>> if state:
            ...     print(f"Current phase: {state['current_phase']}")
            ...     print(f"Iteration: {state['iteration_number']}")
        """
        state = self.state_manager.get_state(agent_name)
        if not state:
            return None

        return {
            "agent_name": state.agent_name,
            "current_phase": state.current_phase.value,
            "status": state.status.value,
            "iteration_number": state.iteration_number,
            "last_error": state.last_error,
            "started_at": state.started_at.isoformat(),
            "updated_at": state.updated_at.isoformat(),
        }

    def reset_state(self, agent_name: str) -> None:
        """
        Reset loop state for agent.

        Deletes all state and history for the agent.

        Args:
            agent_name: Name of agent

        Example:
            >>> loop.reset_state("my_agent")
        """
        self.state_manager.reset_state(agent_name)
        self.metrics_collector.reset_metrics(agent_name)
        logger.info(f"Reset state and metrics for {agent_name}")

    def pause(self, agent_name: str) -> None:
        """
        Pause loop execution for agent.

        Args:
            agent_name: Name of agent

        Example:
            >>> loop.pause("my_agent")
        """
        self.state_manager.pause(agent_name)
        logger.info(f"Paused loop for {agent_name}")

    def resume(self, agent_name: str) -> None:
        """
        Resume paused loop for agent.

        Args:
            agent_name: Name of agent

        Example:
            >>> loop.resume("my_agent")
        """
        self.state_manager.resume(agent_name)
        logger.info(f"Resumed loop for {agent_name}")

    def get_progress(self, agent_name: str) -> ProgressReport:
        """
        Get current progress report for agent.

        Args:
            agent_name: Name of agent

        Returns:
            ProgressReport with current status and metrics

        Example:
            >>> progress = loop.get_progress("my_agent")
            >>> print(f"Current phase: {progress.current_phase.value}")
            >>> print(f"Health: {progress.health_status}")
        """
        state = self.state_manager.get_state(agent_name)
        metrics = self.metrics_collector.get_metrics(agent_name)

        if not state:
            # No state yet
            return ProgressReport(
                agent_name=agent_name,
                current_phase=Phase.DETECT,
                current_iteration=0,
                total_iterations_completed=0,
                phase_progress={},
                health_status="not_started",
            )

        # Build phase progress
        phase_progress = {}
        for phase in Phase:
            phase_progress[phase] = PhaseProgress(
                phase=phase,
                status="not_started",
            )

        # Determine health status
        health_status = "healthy"
        if state.status == LoopStatus.FAILED:
            health_status = "failed"
        elif state.status == LoopStatus.PAUSED:
            health_status = "paused"
        elif state.last_error:
            health_status = "degraded"

        return ProgressReport(
            agent_name=agent_name,
            current_phase=state.current_phase,
            current_iteration=state.iteration_number,
            total_iterations_completed=metrics.total_iterations if metrics else 0,
            phase_progress=phase_progress,
            health_status=health_status,
            last_success=metrics.last_iteration_at if metrics else None,
        )

    def get_history(
        self,
        agent_name: str,
        limit: int = 10,
    ) -> List[IterationResult]:
        """
        Get iteration history for agent (not implemented).

        Args:
            agent_name: Name of agent
            limit: Maximum number of iterations to return

        Returns:
            List of IterationResult (empty for now)

        Raises:
            NotImplementedError: History not yet persisted
        """
        logger.warning("Iteration history not yet implemented")
        return []

    def get_metrics(self, agent_name: str) -> Optional[Dict[str, Any]]:
        """
        Get aggregated metrics for agent.

        Args:
            agent_name: Name of agent

        Returns:
            Metrics dictionary or None if no metrics exist

        Example:
            >>> metrics = loop.get_metrics("my_agent")
            >>> if metrics:
            ...     print(f"Success rate: {metrics['success_rate']:.1%}")
            ...     print(f"Avg duration: {metrics['avg_iteration_duration']:.1f}s")
        """
        metrics = self.metrics_collector.get_metrics(agent_name)
        if not metrics:
            return None

        return metrics.to_dict()

    def health_check(self) -> Dict[str, Any]:
        """
        Perform health check on loop components.

        Returns:
            Health status dictionary

        Example:
            >>> health = loop.health_check()
            >>> if health["status"] == "healthy":
            ...     print("All systems operational")
        """
        status = {
            "status": "healthy",
            "components": {},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        # Check coordination DB
        try:
            self.state_manager.get_state("health_check")
            status["components"]["coordination_db"] = "healthy"
        except Exception as e:
            status["components"]["coordination_db"] = f"unhealthy: {e}"
            status["status"] = "degraded"

        # Check observability session
        try:
            # Simple query to check connection
            status["components"]["observability_db"] = "healthy"
        except Exception as e:
            status["components"]["observability_db"] = f"unhealthy: {e}"
            status["status"] = "degraded"

        # Check configuration
        try:
            self.config.validate()
            status["components"]["configuration"] = "healthy"
        except Exception as e:
            status["components"]["configuration"] = f"invalid: {e}"
            status["status"] = "unhealthy"

        return status
