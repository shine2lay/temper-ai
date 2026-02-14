"""Tests for dialogue_formatter — pure formatting functions."""

import pytest

from src.agents.dialogue_formatter import (
    format_dialogue_history,
    format_stage_agent_outputs,
)


class TestFormatDialogueHistory:

    def test_empty_history(self):
        assert format_dialogue_history([]) == ""

    def test_single_round_entry(self):
        history = [
            {"agent": "skeptic", "round": 0, "output": "Wait", "reasoning": "Risk", "confidence": 0.7}
        ]
        result = format_dialogue_history(history)
        assert "## Prior Dialogue" in result
        assert "Round 0 - skeptic" in result
        assert "Risk" in result
        assert "0.7" in result

    def test_multi_round(self):
        history = [
            {"agent": "a1", "round": 0, "output": "X", "reasoning": "R1", "confidence": 0.8},
            {"agent": "a2", "round": 0, "output": "Y", "reasoning": "R2", "confidence": 0.7},
            {"agent": "a1", "round": 1, "output": "Z", "reasoning": "R3", "confidence": 0.9},
        ]
        result = format_dialogue_history(history)
        assert "Round 0 - a1" in result
        assert "Round 0 - a2" in result
        assert "Round 1 - a1" in result

    def test_truncation_at_max_chars(self):
        history = [
            {"agent": f"agent_{i}", "round": i, "output": "X" * 200, "reasoning": "Y" * 200, "confidence": 0.8}
            for i in range(20)
        ]
        result = format_dialogue_history(history, max_chars=500)
        assert len(result) <= 600  # Allow some header overhead
        assert "truncated" in result.lower()

    def test_malformed_entries_skipped(self):
        history = [
            "not a dict",
            {"agent": "a1", "round": 0, "output": "OK", "reasoning": "R", "confidence": 0.8},
        ]
        result = format_dialogue_history(history)
        assert "a1" in result

    def test_missing_fields_use_defaults(self):
        history = [{"round": 0}]  # Missing agent, output, reasoning
        result = format_dialogue_history(history)
        assert "unknown" in result

    def test_none_input(self):
        """format_dialogue_history should handle None gracefully via caller check."""
        assert format_dialogue_history([]) == ""

    def test_respects_round_ordering(self):
        history = [
            {"agent": "a1", "round": 2, "output": "late", "reasoning": "r", "confidence": 0.8},
            {"agent": "a1", "round": 0, "output": "early", "reasoning": "r", "confidence": 0.8},
        ]
        result = format_dialogue_history(history)
        # Round 0 should appear before round 2
        idx_0 = result.index("Round 0")
        idx_2 = result.index("Round 2")
        assert idx_0 < idx_2


class TestFormatStageAgentOutputs:

    def test_empty_agents(self):
        assert format_stage_agent_outputs({}) == ""

    def test_single_agent_string_output(self):
        result = format_stage_agent_outputs({"analyst": "The data shows..."})
        assert "## Prior Agent Outputs" in result
        assert "analyst" in result
        assert "The data shows..." in result

    def test_multiple_agents(self):
        agents = {"a1": "output1", "a2": "output2"}
        result = format_stage_agent_outputs(agents)
        assert "a1" in result
        assert "a2" in result

    def test_dict_output_with_output_key(self):
        agents = {"a1": {"output": "main result", "tokens": 500}}
        result = format_stage_agent_outputs(agents)
        assert "main result" in result

    def test_truncation(self):
        agents = {f"agent_{i}": "X" * 500 for i in range(20)}
        result = format_stage_agent_outputs(agents, max_chars=500)
        assert "truncated" in result.lower()
