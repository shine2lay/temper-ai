"""
Problem detection logic for M5 Phase 3.

Detects performance problems by analyzing PerformanceComparison results
using configurable threshold-based rules.
"""

import logging
from typing import List, Optional

from src.self_improvement.performance_comparison import PerformanceComparison

from .problem_config import ProblemDetectionConfig
from .problem_models import PerformanceProblem, ProblemSeverity, ProblemType

logger = logging.getLogger(__name__)

# Severity ordering for problem sorting
SEVERITY_ORDER_CRITICAL = 0
SEVERITY_ORDER_HIGH = 1
SEVERITY_ORDER_MEDIUM = 2
SEVERITY_ORDER_LOW = 3


class ProblemDetectionError(Exception):
    """Base exception for problem detection errors."""
    pass


class ProblemDetectionDataError(ProblemDetectionError):
    """Raised when insufficient data for reliable detection."""
    pass


class ProblemDetector:
    """
    Detects performance problems from performance comparisons.

    Core responsibilities:
    1. Analyze PerformanceComparison for degradations
    2. Apply configurable thresholds (relative + absolute)
    3. Calculate problem severity
    4. Return prioritized list of problems

    Design Principles:
    - Stateless (no instance state beyond config)
    - Configurable thresholds
    - Multiple detection strategies (quality, cost, speed)
    - Clear, actionable problem descriptions

    Example:
        >>> from src.database import get_session
        >>> from src.self_improvement.performance_analyzer import PerformanceAnalyzer
        >>> from src.self_improvement.performance_comparison import compare_profiles
        >>>
        >>> with get_session() as session:
        ...     analyzer = PerformanceAnalyzer(session)
        ...     baseline = analyzer.get_baseline("code_review_agent")
        ...     current = analyzer.analyze_agent_performance("code_review_agent")
        ...     comparison = compare_profiles(baseline, current)
        ...
        ...     detector = ProblemDetector()
        ...     problems = detector.detect_problems(comparison)
        ...
        ...     for problem in problems:
        ...         print(problem.get_summary())
        ...         # "MEDIUM quality_low: extraction_quality degraded 15.3%"
    """

    def __init__(self, config: Optional[ProblemDetectionConfig] = None):
        """
        Initialize problem detector.

        Args:
            config: Detection configuration (uses defaults if None)
        """
        self.config = config or ProblemDetectionConfig()

    def detect_problems(
        self,
        comparison: PerformanceComparison,
        min_executions: Optional[int] = None
    ) -> List[PerformanceProblem]:
        """
        Detect all performance problems from comparison.

        Args:
            comparison: PerformanceComparison from current vs baseline
            min_executions: Minimum executions required (uses config default if None)

        Returns:
            List of PerformanceProblem, sorted by severity (CRITICAL first)

        Raises:
            ProblemDetectionDataError: If too few executions for reliable detection

        Example:
            >>> problems = detector.detect_problems(comparison)
            >>> if problems:
            ...     print(f"Found {len(problems)} problems:")
            ...     for p in problems:
            ...         print(f"  - {p.get_summary()}")
            ... else:
            ...     print("No problems detected!")
        """
        # Validate data sufficiency
        min_exec = min_executions or self.config.min_executions_for_detection
        if comparison.current_executions < min_exec:
            raise ProblemDetectionDataError(
                f"Insufficient current executions: {comparison.current_executions} "
                f"(minimum {min_exec} required)"
            )
        if comparison.baseline_executions < min_exec:
            raise ProblemDetectionDataError(
                f"Insufficient baseline executions: {comparison.baseline_executions} "
                f"(minimum {min_exec} required)"
            )

        logger.info(
            f"Detecting problems for {comparison.agent_name}: "
            f"current={comparison.current_executions} exec, "
            f"baseline={comparison.baseline_executions} exec"
        )

        problems = []

        # Detect quality problems
        quality_problems = self._detect_quality_problems(comparison)
        problems.extend(quality_problems)

        # Detect cost problems
        cost_problems = self._detect_cost_problems(comparison)
        problems.extend(cost_problems)

        # Detect speed problems
        speed_problems = self._detect_speed_problems(comparison)
        problems.extend(speed_problems)

        # Sort by severity (CRITICAL first, then HIGH, MEDIUM, LOW)
        severity_order = {
            ProblemSeverity.CRITICAL: SEVERITY_ORDER_CRITICAL,
            ProblemSeverity.HIGH: SEVERITY_ORDER_HIGH,
            ProblemSeverity.MEDIUM: SEVERITY_ORDER_MEDIUM,
            ProblemSeverity.LOW: SEVERITY_ORDER_LOW,
        }
        problems.sort(key=lambda p: severity_order[p.severity])

        logger.info(
            f"Problem detection complete: {len(problems)} problems found "
            f"({sum(1 for p in problems if p.severity == ProblemSeverity.CRITICAL)} critical)"
        )

        return problems

    def _detect_quality_problems(
        self,
        comparison: PerformanceComparison
    ) -> List[PerformanceProblem]:
        """
        Detect quality degradation problems.

        Checks metrics where higher is better:
        - success_rate
        - extraction_quality
        - quality_score
        - Any metric with "quality", "accuracy", "precision", "recall" in name

        Returns:
            List of quality problems (may be empty)
        """
        problems = []

        # Quality metrics: higher is better, check for degradation
        quality_metrics = [
            "success_rate",
            "extraction_quality",
            "quality_score",
            "accuracy",
            "precision",
            "recall",
            "f1_score",
        ]

        for change in comparison.metric_changes:
            # Check if this is a quality metric
            is_quality_metric = (
                change.metric_name in quality_metrics or
                any(q in change.metric_name.lower()
                    for q in ["quality", "accuracy", "precision", "recall"])
            )

            if not is_quality_metric:
                continue

            # Check for degradation (negative change)
            if change.absolute_change >= 0:
                continue  # No degradation

            # Calculate relative degradation
            degradation_pct = abs(change.relative_change)

            # Check thresholds (must meet BOTH relative AND absolute)
            relative_exceeds = degradation_pct >= self.config.quality_relative_threshold
            absolute_exceeds = abs(change.absolute_change) >= self.config.quality_absolute_threshold

            if not (relative_exceeds and absolute_exceeds):
                logger.debug(
                    f"Quality change below threshold: {change.metric_name} "
                    f"rel={degradation_pct:.1%} (need {self.config.quality_relative_threshold:.1%}), "
                    f"abs={abs(change.absolute_change):.3f} "
                    f"(need {self.config.quality_absolute_threshold:.3f})"
                )
                continue

            # Determine severity
            severity = self._calculate_severity(degradation_pct)

            # Create problem
            problem = PerformanceProblem(
                problem_type=ProblemType.QUALITY_LOW,
                severity=severity,
                agent_name=comparison.agent_name,
                metric_name=change.metric_name,
                baseline_value=change.baseline_value,
                current_value=change.current_value,
                degradation_pct=-degradation_pct,  # Negative for degradation
                threshold_used=self.config.quality_relative_threshold,
                evidence={
                    "metric_change": {
                        "absolute": change.absolute_change,
                        "relative": change.relative_change,
                    },
                    "baseline_executions": comparison.baseline_executions,
                    "current_executions": comparison.current_executions,
                }
            )
            problems.append(problem)

            logger.warning(f"Quality problem detected: {problem.get_summary()}")

        return problems

    def _detect_cost_problems(
        self,
        comparison: PerformanceComparison
    ) -> List[PerformanceProblem]:
        """
        Detect cost increase problems.

        Checks metrics where lower is better:
        - cost_usd
        - total_cost_usd
        - estimated_cost_usd
        - Any metric with "cost" in name

        Returns:
            List of cost problems (may be empty)
        """
        problems = []

        # Cost metrics: lower is better, check for increase
        cost_metrics = ["cost_usd", "total_cost_usd", "estimated_cost_usd"]

        for change in comparison.metric_changes:
            # Check if this is a cost metric
            is_cost_metric = (
                change.metric_name in cost_metrics or
                "cost" in change.metric_name.lower()
            )

            if not is_cost_metric:
                continue

            # Check for increase (positive change)
            if change.absolute_change <= 0:
                continue  # No increase

            # Calculate relative increase
            increase_pct = abs(change.relative_change)

            # Check thresholds
            relative_exceeds = increase_pct >= self.config.cost_relative_threshold
            absolute_exceeds = abs(change.absolute_change) >= self.config.cost_absolute_threshold

            if not (relative_exceeds and absolute_exceeds):
                logger.debug(
                    f"Cost change below threshold: {change.metric_name} "
                    f"rel={increase_pct:.1%} (need {self.config.cost_relative_threshold:.1%}), "
                    f"abs={abs(change.absolute_change):.3f} "
                    f"(need {self.config.cost_absolute_threshold:.3f})"
                )
                continue

            # Determine severity
            severity = self._calculate_severity(increase_pct)

            # Create problem
            problem = PerformanceProblem(
                problem_type=ProblemType.COST_HIGH,
                severity=severity,
                agent_name=comparison.agent_name,
                metric_name=change.metric_name,
                baseline_value=change.baseline_value,
                current_value=change.current_value,
                degradation_pct=increase_pct,  # Positive for cost increase
                threshold_used=self.config.cost_relative_threshold,
                evidence={
                    "metric_change": {
                        "absolute": change.absolute_change,
                        "relative": change.relative_change,
                    },
                    "baseline_executions": comparison.baseline_executions,
                    "current_executions": comparison.current_executions,
                }
            )
            problems.append(problem)

            logger.warning(f"Cost problem detected: {problem.get_summary()}")

        return problems

    def _detect_speed_problems(
        self,
        comparison: PerformanceComparison
    ) -> List[PerformanceProblem]:
        """
        Detect speed degradation problems.

        Checks metrics where lower is better:
        - duration_seconds
        - latency_seconds
        - response_time_seconds
        - Any metric with "duration", "latency", "time" in name

        Returns:
            List of speed problems (may be empty)
        """
        problems = []

        # Speed metrics: lower is better, check for increase
        speed_metrics = [
            "duration_seconds",
            "latency_seconds",
            "response_time_seconds",
            "execution_time_seconds",
        ]

        for change in comparison.metric_changes:
            # Check if this is a speed metric
            is_speed_metric = (
                change.metric_name in speed_metrics or
                any(s in change.metric_name.lower()
                    for s in ["duration", "latency", "time"])
            )

            if not is_speed_metric:
                continue

            # Exclude total_tokens (not a speed metric)
            if "token" in change.metric_name.lower():
                continue

            # Check for increase (positive change)
            if change.absolute_change <= 0:
                continue  # No increase

            # Calculate relative increase
            increase_pct = abs(change.relative_change)

            # Check thresholds
            relative_exceeds = increase_pct >= self.config.speed_relative_threshold
            absolute_exceeds = abs(change.absolute_change) >= self.config.speed_absolute_threshold

            if not (relative_exceeds and absolute_exceeds):
                logger.debug(
                    f"Speed change below threshold: {change.metric_name} "
                    f"rel={increase_pct:.1%} (need {self.config.speed_relative_threshold:.1%}), "
                    f"abs={abs(change.absolute_change):.3f} "
                    f"(need {self.config.speed_absolute_threshold:.3f})"
                )
                continue

            # Determine severity
            severity = self._calculate_severity(increase_pct)

            # Create problem
            problem = PerformanceProblem(
                problem_type=ProblemType.SPEED_LOW,
                severity=severity,
                agent_name=comparison.agent_name,
                metric_name=change.metric_name,
                baseline_value=change.baseline_value,
                current_value=change.current_value,
                degradation_pct=increase_pct,  # Positive for speed increase
                threshold_used=self.config.speed_relative_threshold,
                evidence={
                    "metric_change": {
                        "absolute": change.absolute_change,
                        "relative": change.relative_change,
                    },
                    "baseline_executions": comparison.baseline_executions,
                    "current_executions": comparison.current_executions,
                }
            )
            problems.append(problem)

            logger.warning(f"Speed problem detected: {problem.get_summary()}")

        return problems

    def _calculate_severity(self, degradation_pct: float) -> ProblemSeverity:
        """
        Calculate problem severity from degradation percentage.

        Args:
            degradation_pct: Absolute degradation percentage (e.g., 0.15 = 15%)

        Returns:
            ProblemSeverity based on threshold bands

        Example:
            >>> detector._calculate_severity(0.60)  # 60% degradation
            ProblemSeverity.CRITICAL
            >>> detector._calculate_severity(0.35)  # 35% degradation
            ProblemSeverity.HIGH
            >>> detector._calculate_severity(0.20)  # 20% degradation
            ProblemSeverity.MEDIUM
            >>> detector._calculate_severity(0.08)  # 8% degradation
            ProblemSeverity.LOW
        """
        if degradation_pct >= self.config.severity_critical_threshold:
            return ProblemSeverity.CRITICAL
        elif degradation_pct >= self.config.severity_high_threshold:
            return ProblemSeverity.HIGH
        elif degradation_pct >= self.config.severity_medium_threshold:
            return ProblemSeverity.MEDIUM
        else:
            return ProblemSeverity.LOW
