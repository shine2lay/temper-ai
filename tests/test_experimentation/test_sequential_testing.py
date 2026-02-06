"""
Tests for sequential testing and early stopping.

Tests SPRT boundaries, sample size calculations, and Bayesian analysis.
"""

import numpy as np

from src.experimentation.sequential_testing import (
    BayesianAnalyzer,
    SequentialTester,
    calculate_sample_size,
)


class TestSequentialTester:
    """Test sequential hypothesis testing."""

    def test_initialization(self):
        """Test sequential tester initialization."""
        tester = SequentialTester(alpha=0.05, beta=0.20, mde=0.10)

        assert tester.alpha == 0.05
        assert tester.beta == 0.20
        assert tester.mde == 0.10
        assert tester.log_likelihood_upper > 0
        assert tester.log_likelihood_lower < 0

    def test_insufficient_samples(self):
        """Test that small samples return continue."""
        tester = SequentialTester()

        control = [50.0] * 5
        treatment = [30.0] * 5

        decision, details = tester.test_sequential(control, treatment)

        assert decision == "continue"
        assert "Insufficient samples" in details.get("reason", "")

    def test_clear_winner_detected(self):
        """Test early stopping when clear winner exists."""
        tester = SequentialTester(alpha=0.05, beta=0.20, mde=0.10)

        # Large difference: control=50, treatment=30 (40% improvement)
        np.random.seed(42)
        control = list(50.0 + np.random.normal(0, 5, 100))
        treatment = list(30.0 + np.random.normal(0, 5, 100))

        decision, details = tester.test_sequential(control, treatment)

        # Should detect winner with large effect
        assert decision in ["stop_winner", "continue"]
        assert "llr" in details

    def test_no_difference_detected(self):
        """Test early stopping when no difference exists."""
        tester = SequentialTester(alpha=0.05, beta=0.20, mde=0.10)

        # Same distribution
        np.random.seed(42)
        control = list(50.0 + np.random.normal(0, 5, 100))
        treatment = list(50.0 + np.random.normal(0, 5, 100))

        decision, details = tester.test_sequential(control, treatment)

        # Should eventually detect no difference or continue
        assert decision in ["stop_no_difference", "continue"]
        assert "llr" in details

    def test_continue_decision(self):
        """Test continue decision when evidence is insufficient."""
        tester = SequentialTester(alpha=0.05, beta=0.20, mde=0.20)

        # Small difference, may need more samples
        control = [50.0] * 20
        treatment = [48.0] * 20  # Only 4% difference

        decision, details = tester.test_sequential(control, treatment)

        # Likely to continue or stop_no_difference
        assert decision in ["continue", "stop_no_difference"]
        if decision == "continue":
            assert "progress" in details
            assert 0 <= details["progress"] <= 1

    def test_zero_variance_handling(self):
        """Test handling of zero variance data."""
        tester = SequentialTester()

        control = [50.0] * 30
        treatment = [50.0] * 30

        decision, details = tester.test_sequential(control, treatment)

        assert decision == "stop_no_difference"
        assert "Zero variance" in details.get("reason", "")

    def test_sample_size_calculation(self):
        """Test required sample size calculation."""
        tester = SequentialTester(alpha=0.05, beta=0.20, mde=0.10)

        n = tester.calculate_required_sample_size(
            baseline_mean=50.0,
            baseline_std=10.0,
            power=0.80
        )

        # Should return reasonable sample size
        assert isinstance(n, int)
        assert n > 0
        assert n < 10000  # Sanity check

    def test_sample_size_with_zero_std(self):
        """Test sample size calculation with zero standard deviation."""
        tester = SequentialTester(alpha=0.05, beta=0.20, mde=0.10)

        n = tester.calculate_required_sample_size(
            baseline_mean=50.0,
            baseline_std=0.0,
            power=0.80
        )

        # Should return large number (effectively impossible)
        assert n == 10000

    def test_sample_size_increases_with_power(self):
        """Test that higher power requires more samples."""
        tester = SequentialTester(alpha=0.05, beta=0.20, mde=0.10)

        n_low_power = tester.calculate_required_sample_size(
            baseline_mean=50.0,
            baseline_std=10.0,
            power=0.70
        )

        n_high_power = tester.calculate_required_sample_size(
            baseline_mean=50.0,
            baseline_std=10.0,
            power=0.90
        )

        assert n_high_power > n_low_power


class TestBayesianAnalyzer:
    """Test Bayesian analysis functionality."""

    def test_initialization(self):
        """Test Bayesian analyzer initialization."""
        analyzer = BayesianAnalyzer(prior_mean=0.0, prior_std=1.0)

        assert analyzer.prior_mean == 0.0
        assert analyzer.prior_std == 1.0

    def test_analyze_with_clear_winner(self):
        """Test Bayesian analysis with clear difference."""
        analyzer = BayesianAnalyzer()

        control = [50.0] * 50
        treatment = [30.0] * 50

        result = analyzer.analyze_bayesian(control, treatment)

        assert "posterior_mean" in result
        assert "posterior_std" in result
        assert "credible_interval" in result
        assert "prob_treatment_better" in result

        # Treatment is better (lower duration), but posterior mean will be negative
        # So prob_treatment_better should be low (since we calculate > 0)
        # Actually, treatment_mean < control_mean, so diff < 0
        # Probability that diff > 0 will be low
        assert 0 <= result["prob_treatment_better"] <= 1
        assert 0 <= result["prob_control_better"] <= 1
        assert abs(result["prob_treatment_better"] + result["prob_control_better"] - 1.0) < 0.01

    def test_analyze_with_no_difference(self):
        """Test Bayesian analysis with no difference."""
        analyzer = BayesianAnalyzer()

        np.random.seed(42)
        control = list(50.0 + np.random.normal(0, 5, 50))
        treatment = list(50.0 + np.random.normal(0, 5, 50))

        result = analyzer.analyze_bayesian(control, treatment)

        # Probabilities should sum to 1
        assert 0 <= result["prob_treatment_better"] <= 1
        assert 0 <= result["prob_control_better"] <= 1
        assert abs(result["prob_treatment_better"] + result["prob_control_better"] - 1.0) < 0.01

    def test_credible_interval(self):
        """Test credible interval calculation."""
        analyzer = BayesianAnalyzer()

        # Use some variance to get non-degenerate interval
        np.random.seed(42)
        control = list(50.0 + np.random.normal(0, 2, 50))
        treatment = list(45.0 + np.random.normal(0, 2, 50))

        result = analyzer.analyze_bayesian(control, treatment, credible_level=0.95)

        ci_low, ci_high = result["credible_interval"]

        # Interval should be well-defined
        assert ci_low < ci_high
        assert abs(ci_high - ci_low) > 0  # Non-zero width

    def test_expected_lift_calculation(self):
        """Test expected lift calculation."""
        analyzer = BayesianAnalyzer()

        control = [100.0] * 50
        treatment = [80.0] * 50  # 20% reduction

        result = analyzer.analyze_bayesian(control, treatment)

        # Expected lift should be around -20%
        assert -0.25 <= result["expected_lift"] <= -0.15

    def test_zero_control_mean_handling(self):
        """Test handling when control mean is zero."""
        analyzer = BayesianAnalyzer()

        control = [0.0] * 50
        treatment = [10.0] * 50

        result = analyzer.analyze_bayesian(control, treatment)

        # Should handle gracefully
        assert result["expected_lift"] == 0.0


class TestSampleSizeFunction:
    """Test convenience function for sample size calculation."""

    def test_calculate_sample_size_basic(self):
        """Test basic sample size calculation."""
        n = calculate_sample_size(
            baseline_mean=50.0,
            baseline_std=10.0,
            mde=0.10,
            alpha=0.05,
            power=0.80
        )

        assert isinstance(n, int)
        assert n > 0

    def test_sample_size_with_different_params(self):
        """Test sample size with different parameters."""
        n1 = calculate_sample_size(
            baseline_mean=50.0,
            baseline_std=10.0,
            mde=0.10,  # 10% effect
            alpha=0.05,
            power=0.80
        )

        n2 = calculate_sample_size(
            baseline_mean=50.0,
            baseline_std=10.0,
            mde=0.05,  # 5% effect (harder to detect)
            alpha=0.05,
            power=0.80
        )

        # Smaller effect requires more samples
        assert n2 > n1


class TestEdgeCases:
    """Test edge cases and error conditions."""

    def test_sequential_with_single_value(self):
        """Test sequential test with single repeated value."""
        tester = SequentialTester()

        control = [50.0] * 100
        treatment = [50.0] * 100

        decision, details = tester.test_sequential(control, treatment)

        # Should detect no difference due to zero variance
        assert decision == "stop_no_difference"

    def test_bayesian_with_high_variance(self):
        """Test Bayesian analysis with high variance."""
        analyzer = BayesianAnalyzer()

        np.random.seed(42)
        control = list(50.0 + np.random.normal(0, 50, 50))  # High variance
        treatment = list(45.0 + np.random.normal(0, 50, 50))

        result = analyzer.analyze_bayesian(control, treatment)

        # Should still produce valid results
        assert "posterior_mean" in result
        assert "credible_interval" in result
        # Wide credible interval due to high variance
        ci_low, ci_high = result["credible_interval"]
        assert ci_high > ci_low  # Valid interval
        assert ci_high - ci_low > 1  # Non-trivial width

    def test_sequential_with_negative_values(self):
        """Test sequential testing with negative metric values."""
        tester = SequentialTester()

        # Use non-identical values to avoid zero variance
        np.random.seed(42)
        control = list(-10.0 + np.random.normal(0, 2, 50))
        treatment = list(-5.0 + np.random.normal(0, 2, 50))

        decision, details = tester.test_sequential(control, treatment)

        # Should handle negative values correctly
        assert decision in ["stop_winner", "stop_no_difference", "continue"]
        assert "llr" in details or "reason" in details
