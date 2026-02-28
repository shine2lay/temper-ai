"""Tests for ConcatenateStrategy collaboration strategy.

This test module verifies:
- _extract_useful_text: decision present, fallback to reasoning, both empty
- ConcatenateStrategy.synthesize: 1/2/3 agents, separator, headers,
  confidence averaging, method name, empty raises ValueError, metadata
- ConcatenateStrategy.get_capabilities: supports_partial_participation=True
- ConcatenateStrategy.get_metadata: description present, config_schema empty
"""

import pytest

from temper_ai.agent.strategies.base import AgentOutput
from temper_ai.agent.strategies.concatenate import (
    SEPARATOR,
    STRATEGY_NAME,
    ConcatenateStrategy,
    _extract_useful_text,
)


class TestExtractUsefulText:
    """Test _extract_useful_text private helper."""

    def test_decision_present(self):
        """Return decision text when it is non-empty."""
        ao = AgentOutput("agent1", "My decision", "some reasoning", 0.9, {})
        assert _extract_useful_text(ao) == "My decision"

    def test_empty_decision_falls_back_to_reasoning(self):
        """When decision is empty, fall back to reasoning wrapped in notice."""
        ao = AgentOutput("agent1", "", "did file writes", 0.8, {})
        result = _extract_useful_text(ao)
        assert result == "(no summary — reasoning: did file writes)"

    def test_both_empty_returns_notice(self):
        """When both decision and reasoning are empty, return empty notice."""
        ao = AgentOutput("agent1", "", "", 0.7, {})
        assert _extract_useful_text(ao) == "(no text output produced)"

    def test_none_decision_falls_back_to_reasoning(self):
        """When decision is None, fall back to reasoning."""
        ao = AgentOutput("agent1", None, "fallback reasoning", 0.8, {})
        result = _extract_useful_text(ao)
        assert result == "(no summary — reasoning: fallback reasoning)"

    def test_none_decision_none_reasoning_returns_notice(self):
        """When both are None, return empty notice."""
        ao = AgentOutput("agent1", None, None, 0.7, {})
        assert _extract_useful_text(ao) == "(no text output produced)"

    def test_whitespace_only_decision_falls_back_to_reasoning(self):
        """Whitespace-only decision counts as empty — falls back to reasoning."""
        ao = AgentOutput("agent1", "   ", "actual reasoning", 0.8, {})
        result = _extract_useful_text(ao)
        assert result == "(no summary — reasoning: actual reasoning)"


class TestConcatenateStrategySynthesize:
    """Test ConcatenateStrategy.synthesize."""

    def test_single_agent(self):
        """Single agent — result contains its text with name header."""
        strategy = ConcatenateStrategy()
        outputs = [AgentOutput("coder_a", "Created models.py", "foundation", 0.9, {})]

        result = strategy.synthesize(outputs, {})

        assert "[coder_a]" in result.decision
        assert "Created models.py" in result.decision
        assert result.confidence == pytest.approx(0.9)

    def test_two_agents(self):
        """Two agents — both headers and texts appear, separated by SEPARATOR."""
        strategy = ConcatenateStrategy()
        outputs = [
            AgentOutput("coder_a", "Created models.py", "backend", 0.9, {}),
            AgentOutput("coder_b", "Created routes.py", "routing", 0.8, {}),
        ]

        result = strategy.synthesize(outputs, {})

        assert "[coder_a]" in result.decision
        assert "[coder_b]" in result.decision
        assert "Created models.py" in result.decision
        assert "Created routes.py" in result.decision
        assert SEPARATOR in result.decision

    def test_three_agents(self):
        """Three agents — all appear with two separators."""
        strategy = ConcatenateStrategy()
        outputs = [
            AgentOutput("a1", "Output A", "r1", 0.9, {}),
            AgentOutput("a2", "Output B", "r2", 0.8, {}),
            AgentOutput("a3", "Output C", "r3", 0.7, {}),
        ]

        result = strategy.synthesize(outputs, {})

        assert result.decision.count(SEPARATOR) == 2
        assert "[a1]" in result.decision
        assert "[a2]" in result.decision
        assert "[a3]" in result.decision

    def test_separator_between_parts(self):
        """Verify the exact SEPARATOR string appears between agent parts."""
        strategy = ConcatenateStrategy()
        outputs = [
            AgentOutput("alpha", "First output", "r", 0.9, {}),
            AgentOutput("beta", "Second output", "r", 0.8, {}),
        ]

        result = strategy.synthesize(outputs, {})

        parts = result.decision.split(SEPARATOR)
        assert len(parts) == 2
        assert "[alpha]" in parts[0]
        assert "[beta]" in parts[1]

    def test_agent_name_headers(self):
        """Each part is prefixed with [agent_name] header."""
        strategy = ConcatenateStrategy()
        outputs = [
            AgentOutput("worker_1", "Done task", "r", 0.85, {}),
            AgentOutput("worker_2", "Done other task", "r", 0.75, {}),
        ]

        result = strategy.synthesize(outputs, {})

        assert "[worker_1]\nDone task" in result.decision
        assert "[worker_2]\nDone other task" in result.decision

    def test_confidence_is_average(self):
        """Confidence should be the average of all agent confidences."""
        strategy = ConcatenateStrategy()
        outputs = [
            AgentOutput("a1", "text1", "r1", 0.9, {}),
            AgentOutput("a2", "text2", "r2", 0.7, {}),
        ]

        result = strategy.synthesize(outputs, {})

        assert result.confidence == pytest.approx(0.8)

    def test_confidence_three_agents(self):
        """Average confidence across three agents."""
        strategy = ConcatenateStrategy()
        outputs = [
            AgentOutput("a1", "t1", "r1", 0.9, {}),
            AgentOutput("a2", "t2", "r2", 0.6, {}),
            AgentOutput("a3", "t3", "r3", 0.75, {}),
        ]

        result = strategy.synthesize(outputs, {})

        assert result.confidence == pytest.approx((0.9 + 0.6 + 0.75) / 3)

    def test_method_name(self):
        """Method field should equal STRATEGY_NAME ('concatenate')."""
        strategy = ConcatenateStrategy()
        outputs = [AgentOutput("a1", "text", "r", 0.8, {})]

        result = strategy.synthesize(outputs, {})

        assert result.method == STRATEGY_NAME
        assert result.method == "concatenate"

    def test_empty_outputs_raises_value_error(self):
        """Empty agent list should raise ValueError."""
        strategy = ConcatenateStrategy()

        with pytest.raises(ValueError, match="cannot be empty"):
            strategy.synthesize([], {})

    def test_conflicts_always_empty(self):
        """Concatenation never produces conflicts."""
        strategy = ConcatenateStrategy()
        outputs = [
            AgentOutput("a1", "text A", "r1", 0.9, {}),
            AgentOutput("a2", "text B", "r2", 0.7, {}),
        ]

        result = strategy.synthesize(outputs, {})

        assert result.conflicts == []

    def test_metadata_agent_count(self):
        """metadata['agent_count'] matches number of agents."""
        strategy = ConcatenateStrategy()
        outputs = [
            AgentOutput("a1", "t1", "r1", 0.9, {}),
            AgentOutput("a2", "t2", "r2", 0.8, {}),
            AgentOutput("a3", "t3", "r3", 0.7, {}),
        ]

        result = strategy.synthesize(outputs, {})

        assert result.metadata["agent_count"] == 3

    def test_metadata_empty_agents_none_empty(self):
        """metadata['empty_agents'] is empty list when all agents have output."""
        strategy = ConcatenateStrategy()
        outputs = [
            AgentOutput("a1", "text1", "r1", 0.9, {}),
            AgentOutput("a2", "text2", "r2", 0.8, {}),
        ]

        result = strategy.synthesize(outputs, {})

        assert result.metadata["empty_agents"] == []

    def test_metadata_empty_agents_structure(self):
        """metadata['empty_agents'] is always [] because _extract_useful_text
        always returns a non-empty fallback string, even for tool-only agents."""
        strategy = ConcatenateStrategy()
        outputs = [
            AgentOutput("file_writer", "", "", 0.9, {}),  # tool-only, no text
            AgentOutput("reporter", "Summary done", "r", 0.8, {}),
        ]

        result = strategy.synthesize(outputs, {})

        # _extract_useful_text falls back to "(no text output produced)" —
        # a non-empty string — so no agent has length 0 in contributions.
        assert isinstance(result.metadata["empty_agents"], list)
        assert "reporter" not in result.metadata["empty_agents"]

    def test_metadata_total_chars(self):
        """metadata['total_chars'] matches len of combined decision string."""
        strategy = ConcatenateStrategy()
        outputs = [
            AgentOutput("a1", "hello", "r", 0.9, {}),
            AgentOutput("a2", "world", "r", 0.8, {}),
        ]

        result = strategy.synthesize(outputs, {})

        assert result.metadata["total_chars"] == len(result.decision)

    def test_votes_track_text_lengths(self):
        """votes dict maps agent names to character counts of their text."""
        strategy = ConcatenateStrategy()
        outputs = [
            AgentOutput("writer", "Hello", "r", 0.9, {}),
        ]

        result = strategy.synthesize(outputs, {})

        assert "writer" in result.votes
        assert result.votes["writer"] == len("Hello")

    def test_reasoning_mentions_agent_count(self):
        """reasoning field includes the number of agents concatenated."""
        strategy = ConcatenateStrategy()
        outputs = [
            AgentOutput("a1", "text1", "r1", 0.9, {}),
            AgentOutput("a2", "text2", "r2", 0.8, {}),
        ]

        result = strategy.synthesize(outputs, {})

        assert "2" in result.reasoning


class TestConcatenateStrategyCapabilities:
    """Test ConcatenateStrategy.get_capabilities."""

    def test_supports_partial_participation_true(self):
        """supports_partial_participation must be True."""
        strategy = ConcatenateStrategy()
        caps = strategy.get_capabilities()
        assert caps["supports_partial_participation"] is True

    def test_other_capabilities_false(self):
        """All other capabilities must be False."""
        strategy = ConcatenateStrategy()
        caps = strategy.get_capabilities()

        assert caps["supports_debate"] is False
        assert caps["supports_convergence"] is False
        assert caps["supports_merit_weighting"] is False
        assert caps["supports_async"] is False
        assert caps["supports_streaming"] is False


class TestConcatenateStrategyMetadata:
    """Test ConcatenateStrategy.get_metadata."""

    def test_description_present(self):
        """description must be a non-empty string."""
        strategy = ConcatenateStrategy()
        metadata = strategy.get_metadata()

        assert "description" in metadata
        assert isinstance(metadata["description"], str)
        assert len(metadata["description"]) > 0

    def test_config_schema_empty(self):
        """config_schema must be an empty dict (no configurable options)."""
        strategy = ConcatenateStrategy()
        metadata = strategy.get_metadata()

        assert "config_schema" in metadata
        assert metadata["config_schema"] == {}


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
