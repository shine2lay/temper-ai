"""
Rollback monitoring and automated regression detection for M5.

Monitors agent performance after config deployments and triggers automatic
rollback if performance degrades below acceptable thresholds.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from src.constants.durations import HOURS_PER_DAY
from src.constants.limits import PERCENT_10, PERCENT_20, PERCENT_30
from src.self_improvement.data_models import (
    AgentPerformanceProfile,
    ConfigDeployment,
)
from src.self_improvement.performance_analyzer import PerformanceDataError

logger = logging.getLogger(__name__)

# Rollback monitoring defaults
DEFAULT_MIN_EXECUTIONS_FOR_ROLLBACK = 20  # Minimum samples before checking for regression


class RegressionThresholds:
    """
    Thresholds for detecting performance regressions.

    Used by RollbackMonitor to decide when to trigger automatic rollback.
    """

    def __init__(
        self,
        quality_drop_pct: float = float(PERCENT_10),
        cost_increase_pct: float = float(PERCENT_20),
        speed_increase_pct: float = float(PERCENT_30),
        min_executions: int = DEFAULT_MIN_EXECUTIONS_FOR_ROLLBACK,
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
        performance_analyzer: Any,
        config_deployer: Any,
        thresholds: Optional[RegressionThresholds] = None,
    ) -> None:
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
        window_hours: int = HOURS_PER_DAY,
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
        result: Dict[str, Any] = {
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
        window_start = window_end - timedelta(hours=HOURS_PER_DAY)

        # SI-05: Handle PerformanceDataError gracefully instead of letting
        # it propagate as an unhandled exception.
        try:
            result = self.performance_analyzer.analyze_agent_performance(
                agent_name=agent_name,
                window_start=window_start,
                window_end=window_end,
            )
            return result if isinstance(result, AgentPerformanceProfile) else None
        except PerformanceDataError:
            logger.info(f"Insufficient baseline data for {agent_name}")
            return None

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

        try:
            result = self.performance_analyzer.analyze_agent_performance(
                agent_name=agent_name,
                window_start=window_start,
                window_end=now,
            )
            return result if isinstance(result, AgentPerformanceProfile) else None
        except PerformanceDataError:
            logger.info(f"Insufficient current data for {agent_name}")
            return None

    # Regression check definitions: (metric_key, threshold_attr, direction, label, value_fmt)
    # direction="drop" means baseline > current is bad; "increase" means current > baseline is bad
    # value_fmt is a format template with {v} placeholder
    _REGRESSION_CHECKS: list[tuple[str, str, str, str, str]] = [
        ("quality_score", "quality_drop_pct", "drop", "Quality dropped", "{v:.3f}"),
        ("cost_usd", "cost_increase_pct", "increase", "Cost increased", "${v:.4f}"),
        ("duration_seconds", "speed_increase_pct", "increase", "Speed degraded", "{v:.1f}s"),
    ]

    def _detect_regression(
        self,
        baseline: AgentPerformanceProfile,
        current: AgentPerformanceProfile,
    ) -> Optional[str]:
        """Detect if current performance has regressed from baseline."""
        for metric, threshold_attr, direction, label, value_fmt in self._REGRESSION_CHECKS:
            reason = self._check_metric_regression(
                baseline, current, metric, getattr(self.thresholds, threshold_attr),
                direction, label, value_fmt,
            )
            if reason:
                return reason
        return None

    @staticmethod
    def _check_metric_regression(
        baseline: AgentPerformanceProfile,
        current: AgentPerformanceProfile,
        metric_key: str, threshold_pct: float,
        direction: str, label: str, value_fmt: str,
    ) -> Optional[str]:
        """Check a single metric for regression. Returns reason string or None."""
        b_val = baseline.get_metric(metric_key, "mean")
        c_val = current.get_metric(metric_key, "mean")
        if b_val is None or c_val is None or b_val == 0:
            return None
        if direction == "drop":
            pct = (b_val - c_val) / b_val * 100
        else:
            pct = (c_val - b_val) / b_val * 100
        if pct > threshold_pct:
            b_str = value_fmt.format(v=b_val)
            c_str = value_fmt.format(v=c_val)
            return f"{label} {pct:.1f}% (from {b_str} to {c_str})"
        return None

    def monitor_all_agents(
        self,
        agent_names: list[str],
        window_hours: int = HOURS_PER_DAY,
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
