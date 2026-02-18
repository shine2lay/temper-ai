"""Tests for StageConvergenceDetector.

Verifies:
- Exact hash comparison (identical and different strings)
- Semantic comparison (high and low similarity)
- ConvergenceConfig validation (iteration bounds, threshold bounds)
"""

import pytest
from pydantic import ValidationError

from src.stage._schemas import ConvergenceConfig
from src.stage.convergence import StageConvergenceDetector


# ── Exact Hash Comparison ──


class TestHashConvergence:
    """Test exact_hash convergence method."""

    def test_identical_strings_converge(self):
        """Identical strings produce matching SHA-256 digests."""
        config = ConvergenceConfig(enabled=True, method="exact_hash")
        detector = StageConvergenceDetector(config)
        assert detector.has_converged("hello world", "hello world") is True

    def test_different_strings_do_not_converge(self):
        """Different strings produce non-matching digests."""
        config = ConvergenceConfig(enabled=True, method="exact_hash")
        detector = StageConvergenceDetector(config)
        assert detector.has_converged("hello", "world") is False

    def test_empty_strings_converge(self):
        """Two empty strings are considered converged."""
        config = ConvergenceConfig(enabled=True, method="exact_hash")
        detector = StageConvergenceDetector(config)
        assert detector.has_converged("", "") is True

    def test_whitespace_difference_does_not_converge(self):
        """Trailing whitespace causes hash mismatch."""
        config = ConvergenceConfig(enabled=True, method="exact_hash")
        detector = StageConvergenceDetector(config)
        assert detector.has_converged("hello", "hello ") is False


# ── Semantic Comparison ──


class TestSemanticConvergence:
    """Test semantic convergence method using SequenceMatcher."""

    def test_high_similarity_converges(self):
        """Strings with minor differences exceed default threshold."""
        config = ConvergenceConfig(
            enabled=True, method="semantic", similarity_threshold=0.8,
        )
        detector = StageConvergenceDetector(config)
        assert detector.has_converged(
            "The analysis shows strong growth in Q4 revenue.",
            "The analysis shows strong growth in Q4 revenues.",
        ) is True

    def test_low_similarity_does_not_converge(self):
        """Completely different strings fall below threshold."""
        config = ConvergenceConfig(
            enabled=True, method="semantic", similarity_threshold=0.8,
        )
        detector = StageConvergenceDetector(config)
        assert detector.has_converged(
            "The weather is sunny today.",
            "Stock markets crashed overnight.",
        ) is False

    def test_identical_strings_converge_semantic(self):
        """Identical strings have ratio 1.0 which exceeds any threshold."""
        config = ConvergenceConfig(
            enabled=True, method="semantic", similarity_threshold=1.0,
        )
        detector = StageConvergenceDetector(config)
        assert detector.has_converged("same text", "same text") is True

    def test_threshold_boundary(self):
        """Ratio exactly at threshold is considered converged (>=)."""
        config = ConvergenceConfig(
            enabled=True, method="semantic", similarity_threshold=0.0,
        )
        detector = StageConvergenceDetector(config)
        # Any two strings should converge with threshold=0.0
        assert detector.has_converged("abc", "xyz") is True


# ── ConvergenceConfig Validation ──


class TestConvergenceConfigValidation:
    """Test Pydantic field validation on ConvergenceConfig."""

    def test_default_values(self):
        """Defaults are sensible: disabled, 5 iterations, 0.95 threshold, exact_hash."""
        config = ConvergenceConfig()
        assert config.enabled is False
        assert config.max_iterations == 5
        assert config.similarity_threshold == 0.95
        assert config.method == "exact_hash"

    def test_min_iterations_enforced(self):
        """max_iterations below 2 is rejected."""
        with pytest.raises(ValidationError):
            ConvergenceConfig(max_iterations=1)

    def test_max_iterations_enforced(self):
        """max_iterations above 20 is rejected."""
        with pytest.raises(ValidationError):
            ConvergenceConfig(max_iterations=21)

    def test_threshold_lower_bound(self):
        """similarity_threshold below 0.0 is rejected."""
        with pytest.raises(ValidationError):
            ConvergenceConfig(similarity_threshold=-0.1)

    def test_threshold_upper_bound(self):
        """similarity_threshold above 1.0 is rejected."""
        with pytest.raises(ValidationError):
            ConvergenceConfig(similarity_threshold=1.1)

    def test_valid_method_semantic(self):
        """'semantic' is an accepted method value."""
        config = ConvergenceConfig(method="semantic")
        assert config.method == "semantic"

    def test_invalid_method_rejected(self):
        """Unknown method strings are rejected."""
        with pytest.raises(ValidationError):
            ConvergenceConfig(method="cosine")
