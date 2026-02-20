"""Tests for context window management (R0.5)."""
import pytest

from temper_ai.llm.context_window import (
    _CHARS_PER_TOKEN,
    _sliding_window,
    _summarize,
    _truncate,
    count_tokens,
    trim_to_budget,
)


class TestCountTokens:
    """Tests for count_tokens."""

    def test_approximate_mode(self):
        """Should estimate tokens as len(text) / 4."""
        text = "a" * 100
        result = count_tokens(text, "approximate")
        assert result == 100 // _CHARS_PER_TOKEN

    def test_approximate_empty_string(self):
        """Should return 0 for empty string."""
        assert count_tokens("", "approximate") == 0

    def test_tiktoken_fallback_when_not_installed(self):
        """Should fall back to approximate when tiktoken is not available."""
        text = "Hello world"
        # If tiktoken is installed this tests actual tokenization;
        # if not, it tests the fallback path. Either way it should not error.
        result = count_tokens(text, "tiktoken")
        assert result >= 0

    def test_approximate_long_text(self):
        """Should handle long texts."""
        text = "word " * 10000
        result = count_tokens(text, "approximate")
        assert result == len(text) // _CHARS_PER_TOKEN


class TestTrimToBudget:
    """Tests for trim_to_budget."""

    def test_under_budget_returns_unchanged(self):
        """Should return text as-is when under budget."""
        text = "Short text"
        result = trim_to_budget(text, 10000, 2048, "truncate")
        assert result == text

    def test_over_budget_truncates(self):
        """Should truncate when over budget."""
        text = "a" * 10000
        result = trim_to_budget(text, 500, 100, "truncate")
        assert len(result) < len(text)
        assert "[Content truncated" in result

    def test_sliding_window_strategy(self):
        """Should keep recent content with sliding_window."""
        text = "OLD_CONTENT " * 500 + "RECENT_CONTENT"
        result = trim_to_budget(text, 500, 100, "sliding_window")
        assert "RECENT_CONTENT" in result

    def test_summarize_strategy(self):
        """Should truncate with summary marker."""
        text = "a" * 10000
        result = trim_to_budget(text, 500, 100, "summarize")
        assert "[Content summarized" in result

    def test_zero_budget_returns_text(self):
        """Should return text when budget is zero or negative."""
        text = "Hello"
        result = trim_to_budget(text, 100, 200, "truncate")
        assert result == text

    def test_exact_budget_returns_unchanged(self):
        """Should return text when exactly at budget."""
        # 400 chars = 100 tokens at 4 chars/token
        text = "a" * 400
        result = trim_to_budget(text, 200, 100, "truncate")
        assert result == text


class TestTruncate:
    """Tests for _truncate."""

    def test_short_text_unchanged(self):
        """Should not truncate short text."""
        result = _truncate("Hello", 1000, "approximate")
        assert result == "Hello"

    def test_truncates_long_text(self):
        """Should truncate from the end."""
        text = "a" * 10000
        result = _truncate(text, 100, "approximate")
        assert len(result) <= 100 * _CHARS_PER_TOKEN
        assert result.endswith("[Content truncated to fit context window]")

    def test_preserves_beginning(self):
        """Should preserve content from the beginning."""
        text = "BEGINNING" + "x" * 10000
        result = _truncate(text, 100, "approximate")
        assert result.startswith("BEGINNING")


class TestSlidingWindow:
    """Tests for _sliding_window."""

    def test_short_text_unchanged(self):
        """Should not modify short text."""
        result = _sliding_window("Hello", 1000, "approximate")
        assert result == "Hello"

    def test_keeps_recent_content(self):
        """Should keep the most recent content."""
        text = "x" * 10000 + "RECENT"
        result = _sliding_window(text, 100, "approximate")
        assert "RECENT" in result
        assert result.startswith("[Earlier content omitted]")


class TestSummarize:
    """Tests for _summarize."""

    def test_short_text_unchanged(self):
        """Should not modify short text."""
        result = _summarize("Hello", 1000, "approximate")
        assert result == "Hello"

    def test_truncates_with_marker(self):
        """Should truncate with summary marker."""
        text = "a" * 10000
        result = _summarize(text, 100, "approximate")
        assert "[Content summarized" in result

    def test_preserves_beginning(self):
        """Should preserve content from the beginning."""
        text = "BEGINNING" + "x" * 10000
        result = _summarize(text, 100, "approximate")
        assert result.startswith("BEGINNING")
