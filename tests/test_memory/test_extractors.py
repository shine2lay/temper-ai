"""Tests for LLM-based procedural pattern extraction."""

import pytest

from src.memory.extractors import (
    MAX_PATTERN_LENGTH,
    MAX_PATTERNS_PER_EXTRACTION,
    extract_procedural_patterns,
    _parse_patterns,
)


class TestExtraction:
    """Core extraction with mock LLM."""

    def test_extracts_numbered_list(self):
        def mock_llm(prompt):
            return "1. Always validate input\n2. Log errors with context\n3. Use retries for network calls"

        patterns = extract_procedural_patterns("some agent output", mock_llm)
        assert len(patterns) == 3
        assert "Always validate input" in patterns[0]

    def test_extracts_with_parenthesis_format(self):
        def mock_llm(prompt):
            return "1) Cache responses\n2) Retry on failure"

        patterns = extract_procedural_patterns("output text", mock_llm)
        assert len(patterns) == 2

    def test_prompt_contains_text(self):
        captured = {}

        def mock_llm(prompt):
            captured["prompt"] = prompt
            return "NONE"

        extract_procedural_patterns("my agent output data", mock_llm)
        assert "my agent output data" in captured["prompt"]


class TestEmptyOutput:
    """Empty or short text returns no patterns."""

    def test_empty_string(self):
        patterns = extract_procedural_patterns("", lambda p: "1. something")
        assert patterns == []

    def test_whitespace_only(self):
        patterns = extract_procedural_patterns("   ", lambda p: "1. something")
        assert patterns == []

    def test_none_response(self):
        patterns = extract_procedural_patterns("text", lambda p: "NONE")
        assert patterns == []


class TestLLMFailure:
    """LLM error propagates to caller."""

    def test_llm_raises_propagates(self):
        def failing_llm(prompt):
            raise RuntimeError("LLM unavailable")

        with pytest.raises(RuntimeError, match="LLM unavailable"):
            extract_procedural_patterns("text", failing_llm)


class TestPatternTruncation:
    """Long patterns are truncated to MAX_PATTERN_LENGTH."""

    def test_long_pattern_truncated(self):
        long_text = "x" * 1000

        def mock_llm(prompt):
            return f"1. {long_text}"

        patterns = extract_procedural_patterns("output", mock_llm)
        assert len(patterns) == 1
        assert len(patterns[0]) == MAX_PATTERN_LENGTH


class TestParsingEdgeCases:
    """Malformed LLM responses."""

    def test_no_numbered_items(self):
        patterns = _parse_patterns("Here are some thoughts without numbering")
        assert patterns == []

    def test_mixed_content(self):
        response = "Introduction text\n1. First pattern\nSome filler\n2. Second pattern"
        patterns = _parse_patterns(response)
        assert len(patterns) == 2

    def test_max_patterns_enforced(self):
        lines = "\n".join(f"{i+1}. Pattern {i+1}" for i in range(10))
        patterns = _parse_patterns(lines)
        assert len(patterns) == MAX_PATTERNS_PER_EXTRACTION

    def test_empty_numbered_items_skipped(self):
        response = "1.   \n2. Valid pattern\n3.  "
        patterns = _parse_patterns(response)
        assert len(patterns) == 1
        assert patterns[0] == "Valid pattern"

    def test_empty_response(self):
        assert _parse_patterns("") == []
        assert _parse_patterns(None) == []
