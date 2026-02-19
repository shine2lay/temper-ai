"""Tests for memory context formatter."""

from temper_ai.memory._schemas import MemoryEntry, MemoryScope, MemorySearchResult
from temper_ai.memory.constants import (
    MEMORY_TYPE_CROSS_SESSION,
    MEMORY_TYPE_EPISODIC,
    MEMORY_TYPE_PROCEDURAL,
)
from temper_ai.memory.formatter import format_memory_context


def _make_entry(content, memory_type=MEMORY_TYPE_EPISODIC, score=0.5):
    return MemoryEntry(
        content=content,
        memory_type=memory_type,
        relevance_score=score,
    )


def _make_result(entries, query="test"):
    return MemorySearchResult(
        entries=entries,
        query=query,
        scope=MemoryScope(),
    )


class TestFormatMemoryContext:
    """Tests for format_memory_context function."""

    def test_format_empty_result(self):
        result = _make_result([])
        output = format_memory_context(result)
        assert output == ""

    def test_format_single_entry(self):
        entries = [_make_entry("some content", score=0.9)]
        result = _make_result(entries)
        output = format_memory_context(result)
        assert "some content" in output
        assert "0.90" in output

    def test_format_multiple_types_grouped(self):
        entries = [
            _make_entry("epi content", MEMORY_TYPE_EPISODIC, 0.8),
            _make_entry("proc content", MEMORY_TYPE_PROCEDURAL, 0.7),
        ]
        result = _make_result(entries)
        output = format_memory_context(result)
        assert "## Episodic" in output
        assert "## Procedural" in output

    def test_format_sorted_by_relevance(self):
        entries = [
            _make_entry("low score", MEMORY_TYPE_EPISODIC, 0.2),
            _make_entry("high score", MEMORY_TYPE_EPISODIC, 0.9),
        ]
        result = _make_result(entries)
        output = format_memory_context(result)
        # High score should appear first
        pos_high = output.index("high score")
        pos_low = output.index("low score")
        assert pos_high < pos_low

    def test_format_truncation(self):
        entries = [_make_entry("x" * 200, score=0.5)]
        result = _make_result(entries)
        output = format_memory_context(result, max_chars=50)
        assert len(output) <= 50
        assert output.endswith("...")

    def test_format_header_present(self):
        entries = [_make_entry("content")]
        result = _make_result(entries)
        output = format_memory_context(result)
        assert output.startswith("# Relevant Memories")

    def test_format_relevance_scores_formatted(self):
        entries = [_make_entry("content", score=0.75)]
        result = _make_result(entries)
        output = format_memory_context(result)
        assert "[0.75]" in output

    def test_format_type_label_formatting(self):
        """Underscore in type name should become title case."""
        entries = [_make_entry("c", MEMORY_TYPE_CROSS_SESSION, 0.5)]
        result = _make_result(entries)
        output = format_memory_context(result)
        assert "## Cross Session" in output

    def test_format_max_chars_respected(self):
        entries = [_make_entry("a" * 100, score=0.5)]
        result = _make_result(entries)
        output = format_memory_context(result, max_chars=80)
        assert len(output) <= 80

    def test_format_all_same_type(self):
        entries = [
            _make_entry("one", MEMORY_TYPE_EPISODIC, 0.9),
            _make_entry("two", MEMORY_TYPE_EPISODIC, 0.8),
        ]
        result = _make_result(entries)
        output = format_memory_context(result)
        # Should have only one type section
        assert output.count("## Episodic") == 1
        assert "one" in output
        assert "two" in output
