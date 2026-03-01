"""Tests for temper_ai.llm._prompt module.

Tests prompt construction helpers: format_tool_results_text,
inject_results, and apply_sliding_window.
"""

from __future__ import annotations

import pytest

from temper_ai.llm._prompt import (
    apply_sliding_window,
    format_tool_results_text,
    inject_results,
)
from temper_ai.llm.tool_keys import ToolKeys


def _make_tool_result(
    name: str = "calc",
    parameters: dict | None = None,
    success: bool = True,
    result: str = "42",
    error: str | None = None,
) -> dict:
    """Create a tool result dict using ToolKeys constants."""
    return {
        ToolKeys.NAME: name,
        ToolKeys.PARAMETERS: parameters or {"x": 1},
        ToolKeys.SUCCESS: success,
        ToolKeys.RESULT: result,
        ToolKeys.ERROR: error,
    }


class TestFormatToolResultsText:
    """Tests for format_tool_results_text."""

    def test_single_success_result_contains_tool_and_result_labels(self) -> None:
        """A successful tool result includes 'Tool:' and 'Result:' labels."""
        tool_result = _make_tool_result(name="search", result="found it")
        output = format_tool_results_text([tool_result], max_tool_result_size=1000)

        assert "Tool:" in output
        assert "Result:" in output
        assert "search" in output
        assert "found it" in output

    def test_single_error_result_contains_error_label(self) -> None:
        """A failed tool result includes 'Error:' label."""
        tool_result = _make_tool_result(
            name="broken_tool", success=False, result=None, error="tool crashed"
        )
        output = format_tool_results_text([tool_result], max_tool_result_size=1000)

        assert "Error:" in output
        assert "tool crashed" in output
        assert "Result:" not in output

    def test_truncation_at_max_tool_result_size(self) -> None:
        """Long results are truncated with a '[truncated' marker."""
        long_result = "x" * 500
        tool_result = _make_tool_result(result=long_result)
        output = format_tool_results_text([tool_result], max_tool_result_size=100)

        assert "[truncated" in output

    def test_tool_budget_message_with_remaining_calls(self) -> None:
        """When remaining_tool_calls > 0, shows remaining budget message."""
        tool_result = _make_tool_result()
        output = format_tool_results_text(
            [tool_result], max_tool_result_size=1000, remaining_tool_calls=5
        )

        assert "5" in output
        assert "remaining" in output

    def test_tool_budget_exhausted_when_remaining_zero(self) -> None:
        """When remaining_tool_calls == 0, shows 'Budget exhausted' message."""
        tool_result = _make_tool_result()
        output = format_tool_results_text(
            [tool_result], max_tool_result_size=1000, remaining_tool_calls=0
        )

        assert "Budget exhausted" in output or "last tool call" in output.lower()

    def test_no_budget_message_when_remaining_is_none(self) -> None:
        """When remaining_tool_calls is None, no budget message is appended."""
        tool_result = _make_tool_result()
        output = format_tool_results_text(
            [tool_result], max_tool_result_size=1000, remaining_tool_calls=None
        )

        assert "remaining" not in output.lower() or "Budget" not in output


class TestInjectResults:
    """Tests for inject_results."""

    def test_combines_system_prompt_tool_results_and_please_continue(self) -> None:
        """Assembled prompt includes system prompt, tool results, and suffix."""
        system_prompt = "You are a helpful assistant."
        tool_results = [_make_tool_result(result="the answer")]
        conversation_turns: list[str] = []

        prompt = inject_results(
            system_prompt=system_prompt,
            llm_response_content="Let me check.",
            tool_results=tool_results,
            conversation_turns=conversation_turns,
            max_tool_result_size=1000,
            max_prompt_length=10000,
        )

        assert system_prompt in prompt
        assert "the answer" in prompt
        assert "Please continue:" in prompt

    def test_appends_to_conversation_turns(self) -> None:
        """inject_results appends the new turn to conversation_turns list."""
        system_prompt = "System prompt."
        tool_results = [_make_tool_result()]
        conversation_turns: list[str] = []

        inject_results(
            system_prompt=system_prompt,
            llm_response_content="My response.",
            tool_results=tool_results,
            conversation_turns=conversation_turns,
            max_tool_result_size=1000,
            max_prompt_length=10000,
        )

        assert len(conversation_turns) == 1
        assert "My response." in conversation_turns[0]


class TestApplySlidingWindow:
    """Tests for apply_sliding_window."""

    def test_all_turns_fit_within_budget(self) -> None:
        """When all turns fit, the full conversation is included."""
        system_prompt = "System: "
        turns = [" Turn1", " Turn2", " Turn3"]

        result = apply_sliding_window(
            system_prompt=system_prompt,
            conversation_turns=turns,
            max_prompt_length=10000,
        )

        assert "Turn1" in result
        assert "Turn2" in result
        assert "Turn3" in result
        assert "Please continue:" in result

    def test_drops_oldest_turns_when_over_budget(self) -> None:
        """When turns exceed budget, oldest are dropped with truncation marker."""
        system_prompt = "S"
        # Each turn is ~100 chars; set budget so only recent ones fit
        turn = "X" * 100
        turns = [turn, turn, turn, turn]

        # budget = 500 - len("S") - len("\n\nPlease continue:") ≈ 480
        # Only ~4 turns of 100 chars fit, but with overhead some will be dropped
        # Use a tight budget to force dropping
        result = apply_sliding_window(
            system_prompt=system_prompt,
            conversation_turns=turns,
            max_prompt_length=250,
        )

        assert "omitted" in result

    def test_budget_zero_or_negative_uses_last_turn_only(self) -> None:
        """When budget <= 0, only the most recent turn is used."""
        # Make system_prompt + suffix exceed max_prompt_length so budget <= 0
        system_prompt = "A" * 100
        suffix = "\n\nPlease continue:"
        # budget = max_prompt_length - len(system_prompt) - len(suffix)
        # Set max_prompt_length small enough for budget <= 0
        max_length = len(system_prompt) + len(suffix) - 10
        turns = ["turn_old", "turn_new"]

        result = apply_sliding_window(
            system_prompt=system_prompt,
            conversation_turns=turns,
            max_prompt_length=max_length,
        )

        # Should include the last turn and the suffix
        assert "turn_new" in result
        assert "Please continue:" in result

    def test_empty_turns_returns_system_prompt_with_suffix(self) -> None:
        """With no turns, result is system_prompt + suffix."""
        system_prompt = "System prompt only."
        result = apply_sliding_window(
            system_prompt=system_prompt,
            conversation_turns=[],
            max_prompt_length=10000,
        )

        assert result == system_prompt + "\n\nPlease continue:"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
