"""
Rollback monitoring and automated regression detection for M5.

Monitors agent performance after config deployments and triggers automatic
rollback if performance degrades below acceptable thresholds.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any

from src.self_improvement.data_models import (
    AgentPerformanceProfile,
    ConfigDeployment,
)

logger = logging.getLogger(__name__)


class RegressionThresholds:
    """
    Thresholds for detecting performance regressions.

    Used by RollbackMonitor to decide when to trigger automatic rollback.
    """

    def __init__(
        self,
        quality_drop_pct: float = 10.0,
        cost_increase_pct: float = 20.0,
        speed_increase_pct: float = 30.0,
        min_executions: int = 20,
    ):
        """
        Initialize regression thresholds.

        Args:
            quality_drop_pct: Max acceptable quality drop (%) before rollback
            cost_increase_pct: Max acceptable cost increase (%) before rollback
            speed_increase_pct: Max acceptable speed increase (%) before rollback
            min_executions: Min executions needed before checking regressions
        """
        self.quality_drop_pct = quality_drop_pct
        self.cost_increase_pct = cost_increase_pct
        self.speed_increase_pct = speed_increase_pct
        self.min_executions = min_executions


class RollbackMonitor:
    """
    Monitor deployments for performance regressions and trigger rollback.

    Tracks agent performance after config deployments using PerformanceAnalyzer
    to compare current metrics against baseline. Automatically rolls back
    if performance degrades beyond acceptable thresholds.

    For M5 MVP (Phase 5): Simple threshold-based detection.
    Future (Phase 16): Real-time streaming detection with alerts.
    """

    def __init__(
        self,
        performance_analyzer,
        config_deployer,
        thresholds: Optional[RegressionThresholds] = None,
    ):
        """
        Initialize rollback monitor.

        Args:
            performance_analyzer: PerformanceAnalyzer instance for metrics
            config_deployer: ConfigDeployer instance for rollback
            thresholds: Regression detection thresholds (uses defaults if None)
        """
        self.performance_analyzer = performance_analyzer
        self.config_deployer = config_deployer
        self.thresholds = thresholds or RegressionThresholds()

    def check_for_regression(
        self,
        agent_name: str,
        window_hours: int = 24,
    ) -> Dict[str, Any]:
        """
        Check if agent has regressed after recent deployment.

        Compares current performance (last window_hours) to baseline
        performance before deployment. If regression detected beyond
        thresholds, triggers automatic rollback.

        Args:
            agent_name: Name of agent to monitor
            window_hours: Hours to analyze for current performance

        Returns:
            Dictionary with monitoring results:
            {
                "regression_detected": bool,
                "rolled_back": bool,
                "reason": str or None,
                "current_metrics": dict,
                "baseline_metrics": dict,
            }
        """
        result = {
            "regression_detected": False,
            "rolled_back": False,
            "reason": None,
            "current_metrics": {},
            "baseline_metrics": {},
        }

        # Get last deployment
        last_deployment = self.config_deployer.get_last_deployment(agent_name)
        if not last_deployment:
            logger.info(f"No deployment history for {agent_name}, skipping check")
            return result

        # Skip if already rolled back
        if last_deployment.is_rolled_back():
            logger.info(f"Deployment already rolled back for {agent_name}")
            return result

        # Get baseline (performance before deployment)
        baseline = self._get_baseline_performance(agent_name, last_deployment)
        if not baseline:
            logger.warning(f"No baseline performance for {agent_name}")
            return result

        # Get current performance (after deployment)
        current = self._get_current_performance(agent_name, window_hours)
        if not current:
            logger.info(f"Insufficient current data for {agent_name}")
            return result

        # Check if enough executions
        if current.total_executions < self.thresholds.min_executions:
            logger.info(
                f"Not enough executions ({current.total_executions} < {self.thresholds.min_executions}) for {agent_name}"
            )
            return result

        result["current_metrics"] = current.metrics
        result["baseline_metrics"] = baseline.metrics

        # Check for regressions
        regression_reason = self._detect_regression(baseline, current)
        if regression_reason:
            result["regression_detected"] = True
            result["reason"] = regression_reason

            logger.warning(
                f"Regression detected for {agent_name}: {regression_reason}"
            )

            # Trigger rollback
            try:
                self.config_deployer.rollback(
                    agent_name=agent_name,
                    rollback_reason=f"Automatic rollback: {regression_reason}",
                )
                result["rolled_back"] = True
                logger.info(f"Successfully rolled back {agent_name}")
            except Exception as e:
                logger.error(f"Failed to rollback {agent_name}: {e}")
                result["rollback_error"] = str(e)

        return result

    def _get_baseline_performance(
        self,
        agent_name: str,
        deployment: ConfigDeployment,
    ) -> Optional[AgentPerformanceProfile]:
        """
        Get baseline performance before deployment.

        Uses 24 hours of data ending at deployment time.
        """
        window_end = deployment.deployed_at
        window_start = window_end - timedelta(hours=24)

        return self.performance_analyzer.analyze_agent_performance(
            agent_name=agent_name,
            window_start=window_start,
            window_end=window_end,
        )

    def _get_current_performance(
        self,
        agent_name: str,
        window_hours: int,
    ) -> Optional[AgentPerformanceProfile]:
        """
        Get current performance after deployment.

        Uses last window_hours of data.
        """
        now = datetime.now(timezone.utc)
        window_start = now - timedelta(hours=window_hours)

        return self.performance_analyzer.analyze_agent_performance(
            agent_name=agent_name,
            window_start=window_start,
            window_end=now,
        )

    def _detect_regression(
        self,
        baseline: AgentPerformanceProfile,
        current: AgentPerformanceProfile,
    ) -> Optional[str]:
        """
        Detect if current performance has regressed from baseline.

        Returns:
            Reason string if regression detected, None otherwise
        """
        # Check quality regression
        baseline_quality = baseline.get_metric("quality_score", "mean")
        current_quality = current.get_metric("quality_score", "mean")

        if baseline_quality is not None and current_quality is not None:
            quality_drop_pct = (
                (baseline_quality - current_quality) / baseline_quality * 100
            )
            if quality_drop_pct > self.thresholds.quality_drop_pct:
                return f"Quality dropped {quality_drop_pct:.1f}% (from {baseline_quality:.3f} to {current_quality:.3f})"

        # Check cost regression
        baseline_cost = baseline.get_metric("cost_usd", "mean")
        current_cost = current.get_metric("cost_usd", "mean")

        if baseline_cost is not None and current_cost is not None and baseline_cost > 0:
            cost_increase_pct = (
                (current_cost - baseline_cost) / baseline_cost * 100
            )
            if cost_increase_pct > self.thresholds.cost_increase_pct:
                return f"Cost increased {cost_increase_pct:.1f}% (from ${baseline_cost:.4f} to ${current_cost:.4f})"

        # Check speed regression
        baseline_speed = baseline.get_metric("duration_seconds", "mean")
        current_speed = current.get_metric("duration_seconds", "mean")

        if baseline_speed is not None and current_speed is not None and baseline_speed > 0:
            speed_increase_pct = (
                (current_speed - baseline_speed) / baseline_speed * 100
            )
            if speed_increase_pct > self.thresholds.speed_increase_pct:
                return f"Speed degraded {speed_increase_pct:.1f}% (from {baseline_speed:.1f}s to {current_speed:.1f}s)"

        # No regression detected
        return None

    def monitor_all_agents(
        self,
        agent_names: list[str],
        window_hours: int = 24,
    ) -> Dict[str, Dict[str, Any]]:
        """
        Monitor multiple agents for regressions.

        Args:
            agent_names: List of agent names to monitor
            window_hours: Hours to analyze for current performance

        Returns:
            Dictionary mapping agent_name to monitoring results
        """
        results = {}
        for agent_name in agent_names:
            try:
                results[agent_name] = self.check_for_regression(
                    agent_name=agent_name,
                    window_hours=window_hours,
                )
            except Exception as e:
                logger.error(f"Error monitoring {agent_name}: {e}")
                results[agent_name] = {
                    "error": str(e),
                    "regression_detected": False,
                    "rolled_back": False,
                }

        return results
