"""
Statistical analysis for A/B testing experiments.

Provides hypothesis testing, confidence intervals, and winner determination
using scipy statistical methods.
"""

from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from scipy import stats  # type: ignore[import-untyped]

from src.constants.limits import PERCENT_50, PERCENT_95, PERCENT_99
from src.constants.probabilities import PROB_MEDIUM, TOLERANCE_TIGHT
from src.experimentation.constants import DEFAULT_CREDIBLE_LEVEL
from src.experimentation.models import (
    ExecutionStatus,
    Experiment,
    RecommendationType,
    Variant,
    VariantAssignment,
)


class StatisticalAnalyzer:
    """
    Statistical analysis engine for experiments.

    Performs hypothesis testing (t-tests), calculates confidence intervals,
    checks guardrails, and recommends experiment actions.

    Example:
        >>> analyzer = StatisticalAnalyzer()
        >>> result = analyzer.analyze_experiment(experiment, assignments)
        >>> if result.recommendation == RecommendationType.STOP_WINNER:
        ...     print(f"Winner: {result.recommended_winner}")
    """

    def __init__(self, confidence_level: float = DEFAULT_CREDIBLE_LEVEL, min_effect_size: float = TOLERANCE_TIGHT):
        """
        Initialize statistical analyzer.

        Args:
            confidence_level: Confidence level for statistical tests (default: 0.95)
            min_effect_size: Minimum effect size (as proportion) to declare winner (default: 0.05 = 5%)
        """
        self.confidence_level = confidence_level
        self.min_effect_size = min_effect_size

    def analyze_experiment(
        self,
        experiment: Experiment,
        assignments: List[VariantAssignment],
        variants: List[Variant]
    ) -> Dict[str, Any]:
        """
        Perform complete statistical analysis on experiment.

        Args:
            experiment: Experiment definition
            assignments: List of variant assignments with metrics
            variants: List of experiment variants

        Returns:
            Analysis results dictionary with metrics, tests, and recommendation
        """
        # Filter to completed executions only
        completed_assignments = [
            a for a in assignments
            if a.execution_status == ExecutionStatus.COMPLETED and a.metrics
        ]

        if not completed_assignments:
            return self._inconclusive_result("No completed executions")

        # Group assignments by variant
        variant_assignments = self._group_by_variant(completed_assignments)

        # Calculate aggregate metrics per variant
        variant_metrics = self._calculate_variant_metrics(
            variant_assignments,
            experiment.primary_metric
        )

        # Check minimum sample size
        min_samples = experiment.min_sample_size_per_variant
        if any(metrics.get("count", 0) < min_samples for metrics in variant_metrics.values()):
            return self._inconclusive_result("Insufficient sample size")

        # Find control variant
        control_variant_id = None
        for variant in variants:
            if variant.is_control:
                control_variant_id = variant.id
                break

        # Run hypothesis tests
        statistical_tests = self._run_hypothesis_tests(
            variant_assignments,
            experiment.primary_metric,
            experiment.confidence_level,
            control_variant_id
        )

        # Check guardrails
        guardrail_violations = self._check_guardrails(
            variant_metrics,
            experiment.guardrail_metrics or []
        )

        # Generate recommendation
        recommendation, recommended_winner, confidence = self._generate_recommendation(
            statistical_tests,
            guardrail_violations,
            experiment.confidence_level
        )

        return {
            "sample_size": len(completed_assignments),
            "variant_metrics": variant_metrics,
            "statistical_tests": statistical_tests,
            "guardrail_violations": guardrail_violations,
            "recommendation": recommendation,
            "recommended_winner": recommended_winner,
            "confidence": confidence,
        }

    def _group_by_variant(
        self,
        assignments: List[VariantAssignment]
    ) -> Dict[str, List[VariantAssignment]]:
        """Group assignments by variant_id."""
        grouped: Dict[str, List[VariantAssignment]] = {}
        for assignment in assignments:
            if assignment.variant_id not in grouped:
                grouped[assignment.variant_id] = []
            grouped[assignment.variant_id].append(assignment)
        return grouped

    def _calculate_variant_metrics(
        self,
        variant_assignments: Dict[str, List[VariantAssignment]],
        primary_metric: str
    ) -> Dict[str, Dict[str, Any]]:
        """Calculate aggregate metrics for each variant."""
        variant_metrics: Dict[str, Dict[str, Any]] = {}

        for variant_id, assignments in variant_assignments.items():
            variant_metrics[variant_id] = {}

            # Collect all unique metric names across assignments
            all_metric_names: set[str] = set()
            for a in assignments:
                if a.metrics:
                    all_metric_names.update(a.metrics.keys())

            # Calculate statistics for each metric
            for metric_name in all_metric_names:
                values = [
                    a.metrics[metric_name]
                    for a in assignments
                    if a.metrics and metric_name in a.metrics
                ]

                if not values:
                    continue

                # For primary metric, calculate full statistics
                if metric_name == primary_metric:
                    variant_metrics[variant_id].update({
                        "count": len(values),
                        "mean": float(np.mean(values)),
                        "median": float(np.median(values)),
                        "std": float(np.std(values, ddof=1)) if len(values) > 1 else 0.0,
                        "min": float(np.min(values)),
                        "max": float(np.max(values)),
                        "p50": float(np.percentile(values, PERCENT_50)),
                        "p95": float(np.percentile(values, PERCENT_95)),
                        "p99": float(np.percentile(values, PERCENT_99)) if len(values) >= 100 else float(np.max(values)),
                    })
                else:
                    # For other metrics (guardrails), calculate basic statistics
                    variant_metrics[variant_id][metric_name] = float(np.mean(values))

        return variant_metrics

    @staticmethod
    def _resolve_control_id(
        variant_assignments: Dict[str, List[VariantAssignment]],
        control_variant_id: Optional[str],
    ) -> Optional[str]:
        """Resolve control variant ID (use provided or default to first)."""
        control_id = control_variant_id
        if not control_id:
            for variant_id in variant_assignments.keys():
                control_id = variant_id
                break
        if not control_id or control_id not in variant_assignments:
            return None
        return control_id

    @staticmethod
    def _extract_metric_values(
        assignments: List[VariantAssignment], metric: str,
    ) -> List[float]:
        """Extract metric values from assignments that have the given metric."""
        return [
            a.metrics[metric] for a in assignments
            if a.metrics and metric in a.metrics
        ]

    def _run_hypothesis_tests(
        self,
        variant_assignments: Dict[str, List[VariantAssignment]],
        primary_metric: str,
        confidence_level: float,
        control_variant_id: Optional[str] = None
    ) -> Dict[str, Dict[str, Any]]:
        """Run t-tests comparing each variant to control."""
        control_id = self._resolve_control_id(variant_assignments, control_variant_id)
        if control_id is None:
            return {}

        control_values = self._extract_metric_values(
            variant_assignments[control_id], primary_metric,
        )
        statistical_tests: Dict[str, Dict[str, Any]] = {}
        for variant_id, assignments in variant_assignments.items():
            if variant_id == control_id:
                continue
            treatment_values = self._extract_metric_values(assignments, primary_metric)
            if len(treatment_values) < 2 or len(control_values) < 2:
                continue
            test_key = f"control_vs_{variant_id}"
            statistical_tests[test_key] = self._t_test(
                control_values, treatment_values, confidence_level,
            )
        return statistical_tests

    def _t_test(
        self,
        control_values: List[float],
        treatment_values: List[float],
        confidence_level: float
    ) -> Dict[str, Any]:
        """
        Perform independent samples t-test.

        Args:
            control_values: Control variant metric values
            treatment_values: Treatment variant metric values
            confidence_level: Confidence level (e.g., 0.95 for 95%)

        Returns:
            Test results dictionary
        """
        # Two-tailed t-test
        t_stat, p_value = stats.ttest_ind(control_values, treatment_values)

        # Calculate means
        control_mean = np.mean(control_values)
        treatment_mean = np.mean(treatment_values)

        # Calculate improvement percentage
        if control_mean != 0:
            improvement = float((treatment_mean - control_mean) / abs(control_mean))
        else:
            improvement = 0.0

        # Statistical significance
        alpha = 1 - confidence_level
        is_significant = p_value < alpha

        # Confidence interval for difference in means
        ci_low, ci_high = self._confidence_interval(
            control_values,
            treatment_values,
            confidence_level
        )

        return {
            "test": "t-test",
            "t_statistic": float(t_stat),
            "p_value": float(p_value),
            "alpha": alpha,
            "statistically_significant": bool(is_significant),
            "control_mean": float(control_mean),
            "treatment_mean": float(treatment_mean),
            "improvement": float(improvement),
            "confidence_interval": [float(ci_low), float(ci_high)],
        }

    def _confidence_interval(
        self,
        control_values: List[float],
        treatment_values: List[float],
        confidence_level: float
    ) -> Tuple[float, float]:
        """Calculate confidence interval for difference in means."""
        control_mean = np.mean(control_values)
        treatment_mean = np.mean(treatment_values)

        control_std = np.std(control_values, ddof=1)
        treatment_std = np.std(treatment_values, ddof=1)

        n1 = len(control_values)
        n2 = len(treatment_values)

        # Standard error of difference
        se_diff = np.sqrt((control_std ** 2 / n1) + (treatment_std ** 2 / n2))

        # Critical value for confidence level
        alpha = 1 - confidence_level
        df = n1 + n2 - 2
        t_critical = stats.t.ppf(1 - alpha / 2, df)

        # Confidence interval (control - treatment for interpretability)
        diff = control_mean - treatment_mean
        margin_of_error = t_critical * se_diff

        return (diff - margin_of_error, diff + margin_of_error)

    def _check_guardrails(
        self,
        variant_metrics: Dict[str, Dict[str, Any]],
        guardrail_metrics: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Check if any variants violate guardrail thresholds."""
        violations: List[Dict[str, Any]] = []

        for guardrail in guardrail_metrics:
            metric_name = guardrail.get("metric")
            max_value = guardrail.get("max_value")

            if not metric_name or max_value is None:
                continue

            for variant_id, metrics in variant_metrics.items():
                if metric_name in metrics and metrics[metric_name] > max_value:
                    violations.append({
                        "variant": variant_id,
                        "metric": metric_name,
                        "value": metrics[metric_name],
                        "threshold": max_value,
                    })

        return violations

    def _generate_recommendation(
        self,
        statistical_tests: Dict[str, Dict[str, Any]],
        guardrail_violations: List[Dict[str, Any]],
        confidence_level: float
    ) -> Tuple[RecommendationType, Optional[str], float]:
        """
        Generate recommendation based on analysis results.

        Returns:
            (recommendation_type, recommended_winner, confidence)
        """
        # Check for guardrail violations first
        if guardrail_violations:
            return (RecommendationType.STOP_GUARDRAIL_VIOLATION, None, 1.0)

        # Check for statistically significant winner
        significant_tests = [
            (test_key, result)
            for test_key, result in statistical_tests.items()
            if result.get("statistically_significant", False)
        ]

        if not significant_tests:
            # No significant difference
            return (RecommendationType.STOP_NO_DIFFERENCE, None, confidence_level)

        # Find best variant (highest absolute improvement)
        # Uses absolute value to handle both "higher is better" and "lower is better" metrics
        # Requires minimum effect size to avoid declaring trivial differences as winners
        best_improvement_abs = 0.0
        best_variant = None
        best_confidence = 0.0

        for test_key, result in significant_tests:
            improvement = result.get("improvement", 0)
            improvement_abs = abs(improvement)
            if improvement_abs > best_improvement_abs:
                best_improvement_abs = improvement_abs
                # Extract variant ID from test_key "control_vs_{variant_id}"
                best_variant = test_key.split("control_vs_")[1] if "_" in test_key else None
                best_confidence = 1 - result.get("p_value", 1.0)

        if best_variant and best_improvement_abs >= self.min_effect_size:
            return (RecommendationType.STOP_WINNER, best_variant, best_confidence)
        else:
            # Significant but effect size too small, or no winner found
            if significant_tests:
                return (RecommendationType.STOP_NO_DIFFERENCE, None, confidence_level)
            return (RecommendationType.CONTINUE, None, PROB_MEDIUM)

    def _inconclusive_result(self, reason: str) -> Dict[str, Any]:
        """Return inconclusive result."""
        return {
            "sample_size": 0,
            "variant_metrics": {},
            "statistical_tests": {},
            "guardrail_violations": [],
            "recommendation": RecommendationType.CONTINUE,
            "recommended_winner": None,
            "confidence": 0.0,
            "reason": reason,
        }
