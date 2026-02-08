"""
State Coordination Module for M5 Self-Improvement Loop.

Coordinates state management operations across state and metrics.
"""
import logging
from typing import Any, Dict, Optional

from .metrics import MetricsCollector
from .state_manager import LoopStateManager

logger = logging.getLogger(__name__)


class StateCoordinator:
    """
    Coordinate state management operations.

    Provides high-level operations that combine state and metrics management,
    with proper formatting and error handling.
    """

    def __init__(
        self,
        state_manager: LoopStateManager,
        metrics_collector: MetricsCollector,
    ):
        """
        Initialize state coordinator.

        Args:
            state_manager: State manager instance
            metrics_collector: Metrics collector instance
        """
        self.state_manager = state_manager
        self.metrics_collector = metrics_collector

    def get_state_info(self, agent_name: str) -> Optional[Dict[str, Any]]:
        """
        Get formatted state information.

        Args:
            agent_name: Name of agent

        Returns:
            Formatted state dict or None if no state
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

    def reset_state_and_metrics(self, agent_name: str) -> None:
        """
        Reset both state and metrics for agent.

        Args:
            agent_name: Name of agent
        """
        self.state_manager.reset_state(agent_name)
        self.metrics_collector.reset_metrics(agent_name)
        logger.info(f"Reset state and metrics for {agent_name}")

    def pause_execution(self, agent_name: str) -> None:
        """Pause loop for agent."""
        self.state_manager.pause(agent_name)
        logger.info(f"Paused loop for {agent_name}")

    def resume_execution(self, agent_name: str) -> None:
        """Resume paused loop for agent."""
        self.state_manager.resume(agent_name)
        logger.info(f"Resumed loop for {agent_name}")
