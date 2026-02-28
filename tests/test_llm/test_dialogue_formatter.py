"""Tests for temper_ai/llm/prompts/dialogue_formatter.py.

Covers format_dialogue_history and format_stage_agent_outputs
including edge cases, truncation, and non-dict entry handling.
"""

import pytest

from temper_ai.llm.prompts.dialogue_formatter import (
    format_dialogue_history,
    format_stage_agent_outputs,
)


def _make_entry(
    agent: str = "agent1",
    round_num: int = 1,
    output: str = "decision",
    reasoning: str = "because",
    confidence: float = 0.9,
    stance: str = "agree",
) -> dict:
    """Build a valid dialogue history entry."""
    return {
        "agent": agent,
        "round": round_num,
        "output": output,
        "reasoning": reasoning,
        "confidence": confidence,
        "stance": stance,
    }


class TestFormatDialogueHistory:
    """Tests for format_dialogue_history."""

    def test_empty_list_returns_empty_string(self) -> None:
        """Empty history list returns empty string."""
        assert format_dialogue_history([]) == ""

    def test_none_returns_empty_string(self) -> None:
        """None history returns empty string (falsy check)."""
        assert format_dialogue_history(None) == ""  # type: ignore[arg-type]

    def test_single_round_contains_header_and_agent(self) -> None:
        """Single round output contains expected markdown sections."""
        history = [_make_entry(agent="researcher", round_num=1, output="approved")]
        result = format_dialogue_history(history)
        assert "## Prior Dialogue" in result
        assert "### Round 1" in result
        assert "researcher" in result
        assert "approved" in result

    def test_single_round_contains_reasoning_and_confidence(self) -> None:
        """Single round entry includes reasoning, confidence, and stance."""
        history = [
            _make_entry(
                reasoning="strong signal", confidence=0.95, stance="strongly_agree"
            )
        ]
        result = format_dialogue_history(history)
        assert "strong signal" in result
        assert "0.95" in result
        assert "strongly_agree" in result

    def test_multi_round_contains_multiple_round_headers(self) -> None:
        """Multiple rounds produce multiple Round headers."""
        history = [
            _make_entry(agent="agent1", round_num=1),
            _make_entry(agent="agent2", round_num=2),
        ]
        result = format_dialogue_history(history)
        assert "### Round 1" in result
        assert "### Round 2" in result
        assert "agent1" in result
        assert "agent2" in result

    def test_truncation_adds_truncated_marker(self) -> None:
        """When total chars exceed max_chars, truncation marker appears."""
        # Many rounds of long text
        history = [
            _make_entry(
                agent="agent",
                round_num=i,
                output="x" * 500,
                reasoning="y" * 500,
            )
            for i in range(1, 6)
        ]
        result = format_dialogue_history(history, max_chars=800)
        assert "[truncated]" in result or "[Earlier rounds truncated" in result

    def test_max_chars_enforcement(self) -> None:
        """Output length stays within the max_chars bound (with some buffer)."""
        history = [
            _make_entry(agent="agent", round_num=i, output="A" * 300)
            for i in range(1, 10)
        ]
        max_chars = 1000
        result = format_dialogue_history(history, max_chars=max_chars)
        # Allow a small buffer for the truncation message itself
        assert len(result) <= max_chars + 50

    def test_earlier_rounds_truncated_message_for_later_overflow(self) -> None:
        """When a later round overflows with prior parts, adds earlier-truncated header."""
        # First round fits, second overflows → insert "[Earlier rounds truncated..."
        first = _make_entry(agent="a1", round_num=1, output="short")
        # Make second round very long so it triggers the else branch
        second = _make_entry(agent="a2", round_num=2, output="Z" * 2000)
        result = format_dialogue_history([first, second], max_chars=500)
        assert "[Earlier rounds truncated" in result

    def test_non_dict_entries_are_skipped(self) -> None:
        """Non-dict entries in history are ignored."""
        history = [
            "not a dict",
            42,
            None,
            _make_entry(agent="valid_agent", round_num=1),
        ]
        result = format_dialogue_history(history)
        assert "valid_agent" in result
        # Non-dict items should not appear in output
        assert "not a dict" not in result
        assert "42" not in result

    def test_all_non_dict_entries_returns_empty(self) -> None:
        """History with only non-dict entries returns empty string."""
        result = format_dialogue_history(["string1", 42, None])
        assert result == ""


class TestFormatStageAgentOutputs:
    """Tests for format_stage_agent_outputs."""

    def test_empty_dict_returns_empty_string(self) -> None:
        """Empty agents dict returns empty string."""
        assert format_stage_agent_outputs({}) == ""

    def test_none_returns_empty_string(self) -> None:
        """None agents returns empty string (falsy check)."""
        assert format_stage_agent_outputs(None) == ""  # type: ignore[arg-type]

    def test_dict_agent_with_output_key(self) -> None:
        """Agent with dict value uses the 'output' key text."""
        agents = {"agent1": {"output": "my decision", "reasoning": "because"}}
        result = format_stage_agent_outputs(agents)
        assert "agent1" in result
        assert "my decision" in result

    def test_string_agent_value(self) -> None:
        """Agent with string value renders the string directly."""
        agents = {"agent2": "direct output text"}
        result = format_stage_agent_outputs(agents)
        assert "agent2" in result
        assert "direct output text" in result

    def test_multiple_agents_all_appear(self) -> None:
        """Multiple agents all appear in output."""
        agents = {"alpha": "output_a", "beta": {"output": "output_b"}}
        result = format_stage_agent_outputs(agents)
        assert "alpha" in result
        assert "output_a" in result
        assert "beta" in result
        assert "output_b" in result

    def test_max_chars_cutoff_adds_truncated_message(self) -> None:
        """When total exceeds max_chars, truncation message is appended."""
        agents = {f"agent{i}": "X" * 500 for i in range(1, 10)}
        result = format_stage_agent_outputs(agents, max_chars=800)
        assert "[Additional agent outputs truncated]" in result

    def test_output_contains_prior_agent_outputs_header(self) -> None:
        """Result includes the '## Prior Agent Outputs' header."""
        agents = {"a": "text"}
        result = format_stage_agent_outputs(agents)
        assert "## Prior Agent Outputs" in result

    def test_dict_agent_without_output_key_falls_back(self) -> None:
        """Dict agent without 'output' key falls back to str(dict)."""
        agents = {"agent1": {"reasoning": "some reasoning"}}
        result = format_stage_agent_outputs(agents)
        assert "agent1" in result
        # Falls back to str(dict)
        assert "reasoning" in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
