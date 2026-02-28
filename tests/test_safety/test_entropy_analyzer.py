"""Tests for temper_ai/safety/entropy_analyzer.py."""

import pytest

from temper_ai.safety.entropy_analyzer import EntropyAnalyzer


class TestEntropyAnalyzerCalculate:
    def test_empty_string_returns_zero(self):
        assert EntropyAnalyzer.calculate("") == 0.0

    def test_single_char_repeated_returns_zero(self):
        assert EntropyAnalyzer.calculate("aaaa") == 0.0

    def test_two_distinct_chars_equal_freq(self):
        # "ab" — 2 chars, each with p=0.5 → entropy = 1.0
        result = EntropyAnalyzer.calculate("ab")
        assert result == pytest.approx(1.0)

    def test_higher_entropy_with_more_chars(self):
        # "abcdefgh" has 8 distinct chars → higher entropy than "aabb" (2 distinct)
        entropy_high = EntropyAnalyzer.calculate("abcdefgh")
        entropy_low = EntropyAnalyzer.calculate("aabb")
        assert entropy_high > entropy_low

    def test_single_char_returns_zero(self):
        assert EntropyAnalyzer.calculate("a") == 0.0

    def test_high_entropy_random_string(self):
        # A diverse string with many distinct characters should have entropy > 3.0
        random_like = "aB3#xQ9!mZ7$kR2@"
        result = EntropyAnalyzer.calculate(random_like)
        assert result > 3.0


class TestIsHighEntropy:
    def test_above_threshold(self):
        # High-diversity string should be above a low threshold
        high_entropy_text = "aB3#xQ9!mZ7$kR2@nP5%"
        assert EntropyAnalyzer.is_high_entropy(high_entropy_text, threshold=3.0) is True

    def test_below_threshold(self):
        # Repetitive string entropy (0.0) is not above any positive threshold
        assert EntropyAnalyzer.is_high_entropy("aaaa", threshold=0.5) is False

    def test_equal_to_threshold(self):
        # "ab" has exactly 1.0 entropy — is_high_entropy uses strictly >, so threshold=1.0 → False
        result = EntropyAnalyzer.is_high_entropy("ab", threshold=1.0)
        assert result is False
