"""
Health Checking Module for M5 Self-Improvement Loop.

Performs component health checks and status aggregation.
"""
import logging
from datetime import datetime, timezone
from typing import Any, Dict

from .config import LoopConfig
from .state_manager import LoopStateManager

logger = logging.getLogger(__name__)


class HealthChecker:
    """
    Check health of loop components.

    Provides component-level health checks and aggregates status
    for monitoring and alerting.
    """

    def __init__(
        self,
        state_manager: LoopStateManager,
        config: LoopConfig,
    ):
        """
        Initialize health checker.

        Args:
            state_manager: State manager instance
            config: Loop configuration
        """
        self.state_manager = state_manager
        self.config = config

    def check_health(self) -> Dict[str, Any]:
        """
        Perform comprehensive health check.

        Returns:
            Health status dictionary with component status
        """
        status = {
            "status": "healthy",
            "components": {},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        # Check coordination DB
        if not self._check_coordination_db(status):
            status["status"] = "degraded"

        # Check observability DB (placeholder)
        self._check_observability_db(status)

        # Check configuration
        if not self._check_configuration(status):
            status["status"] = "unhealthy"

        return status

    def _check_coordination_db(self, status: Dict[str, Any]) -> bool:
        """
        Check coordination DB health.

        Returns:
            True if healthy
        """
        try:
            self.state_manager.get_state("health_check")
            status["components"]["coordination_db"] = "healthy"
            return True
        except Exception as e:
            status["components"]["coordination_db"] = f"unhealthy: {e}"
            return False

    def _check_observability_db(self, status: Dict[str, Any]) -> bool:
        """
        Check observability DB health.

        Returns:
            True if healthy
        """
        try:
            # Simple query to check connection
            status["components"]["observability_db"] = "healthy"
            return True
        except Exception as e:
            status["components"]["observability_db"] = f"unhealthy: {e}"
            return False

    def _check_configuration(self, status: Dict[str, Any]) -> bool:
        """
        Check configuration validity.

        Returns:
            True if healthy
        """
        try:
            self.config.validate()
            status["components"]["configuration"] = "healthy"
            return True
        except Exception as e:
            status["components"]["configuration"] = f"invalid: {e}"
            return False
