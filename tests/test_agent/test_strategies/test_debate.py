"""Tests for debate-based collaboration strategy (shim over MultiRoundStrategy).

Tests that DebateAndSynthesize:
- Emits deprecation warning
- Inherits from MultiRoundStrategy with mode='debate'
- Still produces correct synthesis results
- Re-exports DebateRound/DebateHistory aliases
"""

import warnings

import pytest

from temper_ai.agent.strategies.base import AgentOutput
from temper_ai.agent.strategies.debate import DebateAndSynthesize, DebateHistory, DebateRound
from temper_ai.agent.strategies.multi_round import (
    CommunicationHistory,
    CommunicationRound,
    MultiRoundStrategy,
)


class TestDebateAndSynthesize:
    """Test suite for DebateAndSynthesize shim."""

    def test_deprecation_warning(self):
        """DebateAndSynthesize emits DeprecationWarning on construction."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            DebateAndSynthesize()
            assert len(w) == 1
            assert issubclass(w[0].category, DeprecationWarning)
            assert "deprecated" in str(w[0].message).lower()

    def test_inherits_multi_round(self):
        """DebateAndSynthesize is a MultiRoundStrategy subclass."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            s = DebateAndSynthesize()
        assert isinstance(s, MultiRoundStrategy)
        assert s.mode == "debate"

    def test_requires_requery(self):
        """Debate mode requires re-invocation (changed from old behavior)."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            s = DebateAndSynthesize()
        assert s.requires_requery is True

    def test_unanimous_debate(self):
        """Test synthesis with unanimous outputs."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            strategy = DebateAndSynthesize()
        outputs = [
            AgentOutput("a1", "Option A", "reason1", 0.9, {}),
            AgentOutput("a2", "Option A", "reason2", 0.8, {}),
            AgentOutput("a3", "Option A", "reason3", 0.85, {}),
        ]
        result = strategy.synthesize(outputs, {})
        assert result.decision == "Option A"
        assert result.confidence > 0.8
        assert result.method == "debate_and_synthesize"

    def test_majority_decision_extraction(self):
        """Test that majority decision wins."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            strategy = DebateAndSynthesize()
        outputs = [
            AgentOutput("a1", "Option A", "reason1", 0.9, {}),
            AgentOutput("a2", "Option A", "reason2", 0.8, {}),
            AgentOutput("a3", "Option B", "reason3", 0.7, {}),
            AgentOutput("a4", "Option C", "reason4", 0.6, {}),
        ]
        result = strategy.synthesize(outputs, {})
        assert result.decision == "Option A"
        assert result.votes["Option A"] == 2

    def test_conflict_detection(self):
        """Test that conflicts are detected."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            strategy = DebateAndSynthesize()
        outputs = [
            AgentOutput("a1", "A", "r", 0.9, {}),
            AgentOutput("a2", "B", "r", 0.9, {}),
            AgentOutput("a3", "C", "r", 0.9, {}),
        ]
        result = strategy.synthesize(outputs, {})
        assert len(result.conflicts) > 0

    def test_validate_inputs(self):
        """Test input validation."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            strategy = DebateAndSynthesize()
        with pytest.raises(ValueError, match="cannot be empty"):
            strategy.synthesize([], {})

    def test_single_agent(self):
        """Test with single agent."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            strategy = DebateAndSynthesize()
        outputs = [AgentOutput("a1", "Option A", "reason", 0.9, {})]
        result = strategy.synthesize(outputs, {})
        assert result.decision == "Option A"
        assert result.confidence > 0

    def test_capabilities(self):
        """Test strategy capabilities include legacy keys."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            strategy = DebateAndSynthesize()
        caps = strategy.get_capabilities()
        assert caps["supports_debate"] is True
        assert caps["supports_convergence"] is True
        assert caps["deterministic"] is False
        assert caps["requires_conflict_resolver"] is True

    def test_metadata(self):
        """Test strategy metadata."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            strategy = DebateAndSynthesize()
        metadata = strategy.get_metadata()
        assert metadata["name"] == "DebateAndSynthesize"
        assert "config_schema" in metadata

    def test_debate_mode_defaults(self):
        """Test debate mode defaults from MultiRoundStrategy."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            strategy = DebateAndSynthesize()
        assert strategy.max_rounds == 3
        assert strategy.convergence_threshold == 0.80
        assert strategy.min_rounds == 1

    def test_convergence_calculation(self):
        """Test convergence inherited from MultiRoundStrategy."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            strategy = DebateAndSynthesize()
        prev = [
            AgentOutput("a1", "A", "r", 0.8, {}),
            AgentOutput("a2", "B", "r", 0.8, {}),
        ]
        curr = [
            AgentOutput("a1", "A", "r", 0.8, {}),
            AgentOutput("a2", "B", "r", 0.8, {}),
        ]
        score = strategy.calculate_convergence(curr, prev)
        assert score == 1.0


class TestDebateRound:
    """Test DebateRound alias (CommunicationRound)."""

    def test_is_communication_round(self):
        assert DebateRound is CommunicationRound

    def test_creation(self):
        outputs = [AgentOutput("a1", "A", "r", 0.8, {})]
        r = DebateRound(round_number=0, agent_outputs=outputs, convergence_score=0.5)
        assert r.round_number == 0
        assert r.convergence_score == 0.5

    def test_default_metadata(self):
        r = DebateRound(round_number=0, agent_outputs=[])
        assert r.metadata == {}


class TestDebateHistory:
    """Test DebateHistory alias (CommunicationHistory)."""

    def test_is_communication_history(self):
        assert DebateHistory is CommunicationHistory

    def test_creation(self):
        h = DebateHistory(total_rounds=3, converged=True, convergence_round=2)
        assert h.total_rounds == 3
        assert h.converged is True
        assert h.convergence_round == 2

    def test_defaults(self):
        h = DebateHistory()
        assert h.total_rounds == 0
        assert h.converged is False
        assert h.convergence_round == -1
