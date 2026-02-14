"""Tests for MultiRoundStrategy — unified multi-round communication strategy."""

from unittest.mock import patch

import pytest

from src.strategies.base import AgentOutput, CollaborationStrategy, SynthesisResult
from src.strategies.multi_round import (
    CommunicationHistory,
    CommunicationRound,
    MultiRoundStrategy,
    VALID_MODES,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_outputs(*decisions: str, prefix: str = "agent") -> list[AgentOutput]:
    """Create AgentOutput list from decision strings."""
    return [
        AgentOutput(
            agent_name=f"{prefix}_{i}",
            decision=d,
            reasoning=f"Reasoning for {d}",
            confidence=0.8,
            metadata={},
        )
        for i, d in enumerate(decisions)
    ]


# ---------------------------------------------------------------------------
# Mode configuration defaults
# ---------------------------------------------------------------------------

class TestModeDefaults:
    """Test that mode-specific defaults are applied correctly."""

    def test_dialogue_defaults(self):
        s = MultiRoundStrategy(mode="dialogue")
        assert s.max_rounds == 3
        assert s.min_rounds == 1
        assert s.convergence_threshold == 0.85

    def test_debate_defaults(self):
        s = MultiRoundStrategy(mode="debate")
        assert s.max_rounds == 3
        assert s.min_rounds == 1
        assert s.convergence_threshold == 0.80

    def test_consensus_defaults(self):
        s = MultiRoundStrategy(mode="consensus")
        assert s.max_rounds == 1
        assert s.min_rounds == 1
        assert s.convergence_threshold == 1.0


# ---------------------------------------------------------------------------
# requires_requery
# ---------------------------------------------------------------------------

class TestRequiresRequery:

    def test_debate_requires_requery(self):
        assert MultiRoundStrategy(mode="debate").requires_requery is True

    def test_dialogue_requires_requery(self):
        assert MultiRoundStrategy(mode="dialogue").requires_requery is True

    def test_consensus_no_requery(self):
        assert MultiRoundStrategy(mode="consensus").requires_requery is False


# ---------------------------------------------------------------------------
# Convergence
# ---------------------------------------------------------------------------

class TestConvergence:

    def test_no_previous_outputs(self):
        s = MultiRoundStrategy(mode="debate")
        score = s.calculate_convergence(_make_outputs("A", "B"), [])
        assert score == 0.0

    def test_exact_match_convergence(self):
        s = MultiRoundStrategy(mode="debate", use_semantic_convergence=False)
        prev = _make_outputs("A", "B", "A")
        curr = _make_outputs("A", "B", "A")
        score = s.calculate_convergence(curr, prev)
        assert score == 1.0

    def test_partial_convergence(self):
        s = MultiRoundStrategy(mode="debate", use_semantic_convergence=False)
        prev = _make_outputs("A", "B", "A")
        curr = _make_outputs("A", "C", "A")  # agent_1 changed
        score = s.calculate_convergence(curr, prev)
        assert abs(score - 2 / 3) < 0.01

    def test_convergence_threshold_boundary(self):
        """When convergence score == threshold, it should be considered converged."""
        s = MultiRoundStrategy(mode="debate", convergence_threshold=0.80)
        # 4 agents, 3 unchanged => 0.75 < 0.80 => not converged
        prev = _make_outputs("A", "B", "A", "B")
        curr = _make_outputs("A", "B", "A", "C")  # 3/4 = 0.75
        score = s.calculate_convergence(curr, prev)
        assert score < s.convergence_threshold


# ---------------------------------------------------------------------------
# Context curation
# ---------------------------------------------------------------------------

class TestContextCuration:

    def _build_history(self, n_rounds: int, n_agents: int = 2) -> list:
        history = []
        for r in range(n_rounds):
            for a in range(n_agents):
                history.append({
                    "agent": f"agent_{a}",
                    "round": r,
                    "output": f"output_r{r}_a{a}",
                    "reasoning": f"reason_r{r}_a{a}",
                    "confidence": 0.8,
                })
        return history

    def test_full_strategy_returns_all(self):
        s = MultiRoundStrategy(context_strategy="full")
        history = self._build_history(3)
        curated = s.curate_dialogue_history(history, 3)
        assert curated == history

    def test_recent_strategy_window(self):
        s = MultiRoundStrategy(context_strategy="recent", context_window_size=1)
        history = self._build_history(3, n_agents=2)
        curated = s.curate_dialogue_history(history, 3)
        # Should only have round 2 entries
        assert all(e["round"] == 2 for e in curated)
        assert len(curated) == 2

    def test_relevant_strategy(self):
        s = MultiRoundStrategy(context_strategy="relevant", context_window_size=2)
        history = self._build_history(3, n_agents=2)
        curated = s.curate_dialogue_history(history, 3, agent_name="agent_0")
        # Should include agent_0's entries + latest round
        assert len(curated) > 0

    def test_empty_history(self):
        s = MultiRoundStrategy(context_strategy="full")
        assert s.curate_dialogue_history([], 0) == []


# ---------------------------------------------------------------------------
# get_round_context
# ---------------------------------------------------------------------------

class TestGetRoundContext:

    def test_debate_context(self):
        s = MultiRoundStrategy(mode="debate")
        ctx = s.get_round_context(1, "agent_0")
        assert ctx["interaction_mode"] == "debate"
        assert "DEBATE" in ctx["mode_instruction"]
        assert "Rebut" in ctx["debate_framing"]

    def test_dialogue_context(self):
        s = MultiRoundStrategy(mode="dialogue")
        ctx = s.get_round_context(0)
        assert ctx["interaction_mode"] == "dialogue"
        assert "DIALOGUE" in ctx["mode_instruction"]
        assert "initial perspective" in ctx["debate_framing"]

    def test_consensus_context(self):
        s = MultiRoundStrategy(mode="consensus")
        ctx = s.get_round_context(0)
        assert ctx["interaction_mode"] == "consensus"
        assert "single-round" in ctx["mode_instruction"]


# ---------------------------------------------------------------------------
# Synthesis
# ---------------------------------------------------------------------------

class TestSynthesis:

    def test_consensus_delegation(self):
        s = MultiRoundStrategy(mode="consensus")
        outputs = _make_outputs("A", "A", "B")
        result = s.synthesize(outputs, {})
        assert isinstance(result, SynthesisResult)
        assert result.decision == "A"
        assert result.metadata["mode"] == "consensus"

    def test_debate_synthesis(self):
        s = MultiRoundStrategy(mode="debate")
        outputs = _make_outputs("X", "X", "Y")
        result = s.synthesize(outputs, {})
        assert result.decision == "X"
        assert "debate" in result.metadata["strategy"]

    @patch("src.strategies._dialogue_helpers.get_merit_weights")
    def test_merit_weighted_synthesis(self, mock_weights):
        """Merit-weighted synthesis path (mocked DB)."""
        mock_weights.return_value = {"agent_0": 1.0, "agent_1": 1.0}
        s = MultiRoundStrategy(mode="dialogue", use_merit_weighting=True)
        outputs = _make_outputs("A", "B")
        result = s.synthesize(outputs, {})
        assert isinstance(result, SynthesisResult)
        assert result.metadata["synthesis_method"] == "merit_weighted"

    def test_empty_outputs_raises(self):
        s = MultiRoundStrategy(mode="debate")
        with pytest.raises(ValueError, match="cannot be empty"):
            s.synthesize([], {})


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

class TestValidation:

    def test_invalid_mode(self):
        with pytest.raises(ValueError, match="Invalid mode"):
            MultiRoundStrategy(mode="invalid")

    def test_negative_rounds(self):
        with pytest.raises(ValueError, match="max_rounds must be >= 1"):
            MultiRoundStrategy(mode="debate", max_rounds=0)

    def test_bad_threshold(self):
        with pytest.raises(ValueError, match="convergence_threshold must be in"):
            MultiRoundStrategy(mode="debate", convergence_threshold=1.5)

    def test_invalid_context_strategy(self):
        with pytest.raises(ValueError, match="Invalid context_strategy"):
            MultiRoundStrategy(context_strategy="invalid")


# ---------------------------------------------------------------------------
# Cost budget
# ---------------------------------------------------------------------------

class TestCostBudget:

    def test_budget_stores(self):
        s = MultiRoundStrategy(mode="debate", cost_budget_usd=5.0)
        assert s.cost_budget_usd == 5.0

    def test_no_budget(self):
        s = MultiRoundStrategy(mode="debate")
        assert s.cost_budget_usd is None

    def test_invalid_budget(self):
        with pytest.raises(ValueError, match="cost_budget_usd must be > 0"):
            MultiRoundStrategy(mode="debate", cost_budget_usd=-1.0)


# ---------------------------------------------------------------------------
# Capabilities
# ---------------------------------------------------------------------------

class TestCapabilities:

    def test_debate_capabilities(self):
        caps = MultiRoundStrategy(mode="debate").get_capabilities()
        assert caps["supports_debate"] is True
        assert caps["supports_dialogue"] is False
        assert caps["supports_convergence"] is True
        assert caps["supports_multi_round"] is True

    def test_consensus_capabilities(self):
        caps = MultiRoundStrategy(mode="consensus").get_capabilities()
        assert caps["supports_debate"] is False
        assert caps["supports_convergence"] is False
        assert caps["supports_multi_round"] is False


# ---------------------------------------------------------------------------
# Registry integration
# ---------------------------------------------------------------------------

class TestRegistryIntegration:

    def test_multi_round_registered(self):
        from src.strategies.registry import StrategyRegistry
        registry = StrategyRegistry()
        strategy = registry.get_strategy("multi_round", mode="debate")
        assert isinstance(strategy, MultiRoundStrategy)
        assert strategy.mode == "debate"

    def test_multi_round_with_config(self):
        from src.strategies.registry import get_strategy_from_config
        config = {
            "collaboration": {
                "strategy": "multi_round",
                "config": {"mode": "debate", "max_rounds": 5},
            }
        }
        strategy = get_strategy_from_config(config)
        assert isinstance(strategy, MultiRoundStrategy)
        assert strategy.max_rounds == 5


# ---------------------------------------------------------------------------
# CollaborationStrategy interface
# ---------------------------------------------------------------------------

class TestInterface:

    def test_is_collaboration_strategy(self):
        assert issubclass(MultiRoundStrategy, CollaborationStrategy)

    def test_metadata(self):
        s = MultiRoundStrategy(mode="debate")
        meta = s.get_metadata()
        assert "config_schema" in meta
        assert "mode" in meta["config_schema"]


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

class TestDataClasses:

    def test_communication_round(self):
        r = CommunicationRound(round_number=0, agent_outputs=[])
        assert r.round_number == 0
        assert r.convergence_score == 0.0

    def test_communication_history(self):
        h = CommunicationHistory()
        assert h.total_rounds == 0
        assert h.converged is False
        assert h.convergence_round == -1
