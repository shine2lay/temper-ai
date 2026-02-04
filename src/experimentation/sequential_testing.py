"""
Sequential testing and early stopping for experiments.

Implements methods for stopping experiments early when sufficient evidence
is gathered, reducing experiment runtime while maintaining statistical rigor.
"""

import numpy as np  # type: ignore[import-not-found]
from typing import Dict, List, Tuple, Optional, Any
from scipy import stats  # type: ignore[import-untyped]


class SequentialTester:
    """
    Sequential hypothesis testing with early stopping.

    Uses sequential probability ratio test (SPRT) to determine when
    enough evidence has been gathered to make a decision.

    Example:
        >>> tester = SequentialTester(alpha=0.05, beta=0.20, mde=0.10)
        >>> decision = tester.test_sequential(control_values, treatment_values)
        >>> if decision == "stop_winner":
        ...     print("Sufficient evidence to declare winner")
    """

    def __init__(
        self,
        alpha: float = 0.05,
        beta: float = 0.20,
        mde: float = 0.10
    ):
        """
        Initialize sequential tester.

        Args:
            alpha: Type I error rate (false positive rate)
            beta: Type II error rate (false negative rate)
            mde: Minimum detectable effect (as proportion)
        """
        self.alpha = alpha
        self.beta = beta
        self.mde = mde

        # Calculate SPRT boundaries
        self.log_likelihood_upper = np.log((1 - beta) / alpha)
        self.log_likelihood_lower = np.log(beta / (1 - alpha))

    def test_sequential(
        self,
        control_values: List[float],
        treatment_values: List[float]
    ) -> Tuple[str, Dict[str, Any]]:
        """
        Perform sequential test to determine if we can stop early.

        Args:
            control_values: Control variant metric values
            treatment_values: Treatment variant metric values

        Returns:
            Tuple of (decision, details) where decision is one of:
            - "continue": Need more data
            - "stop_winner": Sufficient evidence for winner
            - "stop_no_difference": Sufficient evidence of no difference
        """
        if len(control_values) < 10 or len(treatment_values) < 10:
            return ("continue", {"reason": "Insufficient samples for sequential test"})

        # Calculate means and pooled variance
        control_mean = np.mean(control_values)
        treatment_mean = np.mean(treatment_values)

        control_var = np.var(control_values, ddof=1)
        treatment_var = np.var(treatment_values, ddof=1)

        n1 = len(control_values)
        n2 = len(treatment_values)

        # Pooled standard deviation
        pooled_var = ((n1 - 1) * control_var + (n2 - 1) * treatment_var) / (n1 + n2 - 2)
        pooled_std = np.sqrt(pooled_var)

        if pooled_std == 0:
            # No variance - likely all values are identical
            return ("stop_no_difference", {"reason": "Zero variance detected"})

        # Calculate standardized effect size
        observed_effect = (treatment_mean - control_mean) / pooled_std

        # Expected effect under alternative hypothesis
        expected_effect = self.mde * np.sign(treatment_mean - control_mean) if treatment_mean != control_mean else self.mde

        # ST-06: Corrected SPRT log-likelihood ratio for normal distributions.
        # LLR = (observed_effect * expected_effect - expected_effect^2 / 2) * n_eff
        # where n_eff = (n1 * n2) / (n1 + n2)
        n_eff = (n1 * n2) / (n1 + n2)
        llr = (observed_effect * expected_effect - (expected_effect ** 2) / 2) * n_eff

        # Decision based on SPRT boundaries
        if llr >= self.log_likelihood_upper:
            return ("stop_winner", {
                "llr": float(llr),
                "boundary": float(self.log_likelihood_upper),
                "observed_effect": float(observed_effect),
                "samples": n1 + n2
            })
        elif llr <= self.log_likelihood_lower:
            return ("stop_no_difference", {
                "llr": float(llr),
                "boundary": float(self.log_likelihood_lower),
                "observed_effect": float(observed_effect),
                "samples": n1 + n2
            })
        else:
            return ("continue", {
                "llr": float(llr),
                "lower_boundary": float(self.log_likelihood_lower),
                "upper_boundary": float(self.log_likelihood_upper),
                "progress": float((llr - self.log_likelihood_lower) / (self.log_likelihood_upper - self.log_likelihood_lower)),
                "samples": n1 + n2
            })

    def calculate_required_sample_size(
        self,
        baseline_mean: float,
        baseline_std: float,
        power: float = 0.80
    ) -> int:
        """
        Calculate required sample size per variant.

        Args:
            baseline_mean: Expected mean of baseline/control
            baseline_std: Expected standard deviation
            power: Desired statistical power (1 - beta)

        Returns:
            Required sample size per variant
        """
        # Z-scores for alpha and beta
        z_alpha = stats.norm.ppf(1 - self.alpha / 2)
        z_beta = stats.norm.ppf(power)

        # Effect size in standard deviations
        effect_size = self.mde * abs(baseline_mean) / baseline_std if baseline_std > 0 else 0

        if effect_size == 0:
            return 10000  # Large number if effect size is zero

        # Sample size formula for two-sample t-test
        n = 2 * ((z_alpha + z_beta) / effect_size) ** 2

        return int(np.ceil(n))


class BayesianAnalyzer:
    """
    Bayesian analysis for experiments.

    Provides probability-based interpretations and credible intervals
    as an alternative to frequentist p-values.
    """

    def __init__(self, prior_mean: float = 0.0, prior_std: float = 1.0):
        """
        Initialize Bayesian analyzer.

        Args:
            prior_mean: Prior belief about effect size
            prior_std: Uncertainty in prior belief
        """
        self.prior_mean = prior_mean
        self.prior_std = prior_std

    def analyze_bayesian(
        self,
        control_values: List[float],
        treatment_values: List[float],
        credible_level: float = 0.95
    ) -> Dict[str, Any]:
        """
        Perform Bayesian analysis on two variants.

        Args:
            control_values: Control variant metric values
            treatment_values: Treatment variant metric values
            credible_level: Credible interval level (default: 0.95)

        Returns:
            Analysis results with posterior distribution and probabilities
        """
        control_mean = np.mean(control_values)
        treatment_mean = np.mean(treatment_values)

        control_std = np.std(control_values, ddof=1)
        treatment_std = np.std(treatment_values, ddof=1)

        n1 = len(control_values)
        n2 = len(treatment_values)

        # Observed difference
        diff_mean = treatment_mean - control_mean
        diff_se = np.sqrt((control_std ** 2 / n1) + (treatment_std ** 2 / n2))

        # Handle zero variance case
        if diff_se == 0 or np.isnan(diff_se):
            # Zero variance - return deterministic result
            return {
                "posterior_mean": float(diff_mean),
                "posterior_std": 0.0,
                "credible_interval": [float(diff_mean), float(diff_mean)],
                "prob_treatment_better": 1.0 if diff_mean > 0 else 0.0,
                "prob_control_better": 0.0 if diff_mean > 0 else 1.0,
                "expected_lift": float(diff_mean / abs(control_mean)) if control_mean != 0 else 0.0,
            }

        # Posterior using normal-normal conjugate prior
        # Simplified: assuming known variance
        posterior_precision = 1 / self.prior_std ** 2 + 1 / diff_se ** 2
        posterior_mean = (
            self.prior_mean / self.prior_std ** 2 + diff_mean / diff_se ** 2
        ) / posterior_precision
        posterior_std = np.sqrt(1 / posterior_precision)

        # Credible interval
        alpha = 1 - credible_level
        ci_low = stats.norm.ppf(alpha / 2, loc=posterior_mean, scale=posterior_std)
        ci_high = stats.norm.ppf(1 - alpha / 2, loc=posterior_mean, scale=posterior_std)

        # Probability that treatment is better
        prob_treatment_better = 1 - stats.norm.cdf(0, loc=posterior_mean, scale=posterior_std)

        return {
            "posterior_mean": float(posterior_mean),
            "posterior_std": float(posterior_std),
            "credible_interval": [float(ci_low), float(ci_high)],
            "prob_treatment_better": float(prob_treatment_better),
            "prob_control_better": float(1 - prob_treatment_better),
            "expected_lift": float(diff_mean / abs(control_mean)) if control_mean != 0 else 0.0,
        }


def calculate_sample_size(
    baseline_mean: float,
    baseline_std: float,
    mde: float,
    alpha: float = 0.05,
    power: float = 0.80
) -> int:
    """
    Calculate required sample size for experiment.

    Args:
        baseline_mean: Expected baseline metric value
        baseline_std: Expected standard deviation
        mde: Minimum detectable effect (as proportion)
        alpha: Significance level
        power: Statistical power (1 - beta)

    Returns:
        Required sample size per variant
    """
    tester = SequentialTester(alpha=alpha, beta=1-power, mde=mde)
    return tester.calculate_required_sample_size(baseline_mean, baseline_std, power)
