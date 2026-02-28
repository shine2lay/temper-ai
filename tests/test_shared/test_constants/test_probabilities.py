"""Tests for temper_ai/shared/constants/probabilities.py."""

from temper_ai.shared.constants.probabilities import (
    CONFIDENCE_HIGH,
    CONFIDENCE_LOW,
    CONFIDENCE_MEDIUM,
    FRACTION_HALF,
    FRACTION_QUARTER,
    PROB_CRITICAL,
    PROB_HIGH,
    PROB_LOW,
    PROB_LOW_MEDIUM,
    PROB_MEDIUM,
    PROB_MINIMAL,
    PROB_MODERATE,
    PROB_NEAR_CERTAIN,
    PROB_VERY_HIGH,
    PROB_VERY_HIGH_PLUS,
    PROB_VERY_LOW,
    WEIGHT_LARGE,
    WEIGHT_MEDIUM,
    WEIGHT_MINIMAL,
    WEIGHT_SMALL,
    WEIGHT_VERY_LARGE,
)


class TestProbabilityThresholds:
    def test_all_in_zero_one_range(self):
        probs = [
            PROB_MINIMAL,
            PROB_VERY_LOW,
            PROB_LOW,
            PROB_LOW_MEDIUM,
            PROB_MODERATE,
            PROB_MEDIUM,
            PROB_HIGH,
            PROB_VERY_HIGH,
            PROB_CRITICAL,
            PROB_VERY_HIGH_PLUS,
            PROB_NEAR_CERTAIN,
        ]
        for p in probs:
            assert 0 < p < 1, f"{p} not in (0, 1)"

    def test_ordering(self):
        probs = [
            PROB_MINIMAL,
            PROB_VERY_LOW,
            PROB_LOW,
            PROB_LOW_MEDIUM,
            PROB_MODERATE,
            PROB_MEDIUM,
            PROB_HIGH,
            PROB_VERY_HIGH,
            PROB_CRITICAL,
            PROB_VERY_HIGH_PLUS,
            PROB_NEAR_CERTAIN,
        ]
        assert probs == sorted(probs)

    def test_medium_is_half(self):
        assert PROB_MEDIUM == 0.5


class TestWeights:
    def test_all_in_zero_one_range(self):
        weights = [
            WEIGHT_MINIMAL,
            WEIGHT_SMALL,
            WEIGHT_MEDIUM,
            WEIGHT_LARGE,
            WEIGHT_VERY_LARGE,
        ]
        for w in weights:
            assert 0 < w < 1

    def test_ordering(self):
        weights = [
            WEIGHT_MINIMAL,
            WEIGHT_SMALL,
            WEIGHT_MEDIUM,
            WEIGHT_LARGE,
            WEIGHT_VERY_LARGE,
        ]
        assert weights == sorted(weights)


class TestConfidenceLevels:
    def test_ordering(self):
        assert CONFIDENCE_LOW < CONFIDENCE_MEDIUM < CONFIDENCE_HIGH

    def test_all_in_range(self):
        for c in [CONFIDENCE_LOW, CONFIDENCE_MEDIUM, CONFIDENCE_HIGH]:
            assert 0 < c < 1


class TestFractions:
    def test_quarter(self):
        assert FRACTION_QUARTER == 0.25

    def test_half(self):
        assert FRACTION_HALF == 0.5
