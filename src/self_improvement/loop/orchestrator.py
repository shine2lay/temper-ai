"""
M5 Self-Improvement Loop Orchestrator.

Main entry point for running improvement cycles with state management,
error recovery, and observability.
"""
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta, timezone
from sqlmodel import Session

from .models import (
    Phase,
    IterationResult,
    ProgressReport,
    PhaseProgress,
    LoopStatus,
)
from .config import LoopConfig
from .state_manager import LoopStateManager
from .error_recovery import ErrorRecoveryStrategy
from .metrics import MetricsCollector, LoopMetrics
from .executor import LoopExecutor

logger = logging.getLogger(__name__)


class M5SelfImprovementLoop:
    """
    M5 Self-Improvement Loop orchestrator.

    Coordinates complete improvement cycles with state management,
    error recovery, and observability. Supports single-shot,
    continuous, and scheduled execution modes.

    Example:
        >>> from coord_service.database import Database
        >>> from src.observability.database import get_session
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
        self.state_manager = LoopStateManager(coord_db)
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
    ) -> None:
        """
        Run continuous improvement loop (not implemented - use scheduled).

        Args:
            agent_names: List of agents to monitor (optional)
            check_interval_minutes: Check interval (optional, uses config default)

        Raises:
            NotImplementedError: Continuous mode not yet implemented
        """
        raise NotImplementedError(
            "Continuous mode not yet implemented. Use run_iteration() with "
            "external scheduling instead."
        )

    def run_scheduled(self, cron_expression: str) -> None:
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
