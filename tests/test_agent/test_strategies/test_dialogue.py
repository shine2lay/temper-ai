"""Tests for DialogueOrchestrator collaboration strategy (shim over MultiRoundStrategy).

Tests that DialogueOrchestrator:
- Emits deprecation warning
- Inherits from MultiRoundStrategy with mode='dialogue'
- Accepts original constructor parameters
- Produces correct synthesis results
- Re-exports DialogueRound/DialogueHistory aliases

Note: Multi-round dialogue execution logic is tested via executor integration
tests in test_executors/test_sequential.py and test_executors/test_parallel.py
"""

import warnings
from unittest.mock import patch

import pytest

from temper_ai.agent.strategies.base import AgentOutput
from temper_ai.agent.strategies.dialogue import DialogueHistory, DialogueOrchestrator, DialogueRound
from temper_ai.agent.strategies.multi_round import (
    CommunicationHistory,
    CommunicationRound,
    MultiRoundStrategy,
)


class TestDialogueOrchestratorShim:
    """Test DialogueOrchestrator shim behavior."""

    def test_deprecation_warning(self):
        """DialogueOrchestrator emits DeprecationWarning on construction."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            DialogueOrchestrator()
            assert len(w) == 1
            assert issubclass(w[0].category, DeprecationWarning)
            assert "deprecated" in str(w[0].message).lower()

    def test_inherits_multi_round(self):
        """DialogueOrchestrator is a MultiRoundStrategy subclass."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            s = DialogueOrchestrator()
        assert isinstance(s, MultiRoundStrategy)
        assert s.mode == "dialogue"

    def test_requires_requery(self):
        """Dialogue mode requires re-invocation."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            s = DialogueOrchestrator()
        assert s.requires_requery is True

    def test_requires_requery_is_property(self):
        """requires_requery is a read-only property."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            s = DialogueOrchestrator()
        assert isinstance(getattr(type(s), "requires_requery"), property)


class TestDialogueOrchestratorInitialization:
    """Test DialogueOrchestrator initialization and configuration."""

    def test_default_initialization(self):
        """Test initialization with default parameters."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            strategy = DialogueOrchestrator()

        assert strategy.max_rounds == 3
        assert strategy.convergence_threshold == 0.85
        assert strategy.cost_budget_usd is None
        assert strategy.min_rounds == 1

    def test_custom_initialization(self):
        """Test initialization with custom parameters."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            strategy = DialogueOrchestrator(
                max_rounds=5,
                convergence_threshold=0.90,
                cost_budget_usd=20.0,
                min_rounds=2,
            )

        assert strategy.max_rounds == 5
        assert strategy.convergence_threshold == 0.90
        assert strategy.cost_budget_usd == 20.0
        assert strategy.min_rounds == 2

    def test_invalid_max_rounds_raises(self):
        """Test that max_rounds < 1 raises ValueError."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            with pytest.raises(ValueError, match="max_rounds must be >= 1"):
                DialogueOrchestrator(max_rounds=0)
            with pytest.raises(ValueError, match="max_rounds must be >= 1"):
                DialogueOrchestrator(max_rounds=-1)

    def test_invalid_min_rounds_raises(self):
        """Test that min_rounds < 1 raises ValueError."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            with pytest.raises(ValueError, match="min_rounds must be >= 1"):
                DialogueOrchestrator(min_rounds=0)
            with pytest.raises(ValueError, match="min_rounds must be >= 1"):
                DialogueOrchestrator(min_rounds=-1)

    def test_invalid_convergence_threshold_too_high(self):
        """Test that convergence_threshold > 1.0 raises ValueError."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            with pytest.raises(ValueError, match="convergence_threshold must be in"):
                DialogueOrchestrator(convergence_threshold=1.5)

    def test_invalid_convergence_threshold_negative(self):
        """Test that negative convergence_threshold raises ValueError."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            with pytest.raises(ValueError, match="convergence_threshold must be in"):
                DialogueOrchestrator(convergence_threshold=-0.1)

    def test_valid_convergence_threshold_boundaries(self):
        """Test that convergence_threshold boundaries (0.0, 1.0) are valid."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            strategy_zero = DialogueOrchestrator(convergence_threshold=0.0)
            assert strategy_zero.convergence_threshold == 0.0

            strategy_one = DialogueOrchestrator(convergence_threshold=1.0)
            assert strategy_one.convergence_threshold == 1.0

    def test_invalid_cost_budget_negative(self):
        """Test that negative cost_budget_usd raises ValueError."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            with pytest.raises(ValueError, match="cost_budget_usd must be > 0"):
                DialogueOrchestrator(cost_budget_usd=-10.0)

    def test_invalid_cost_budget_zero(self):
        """Test that zero cost_budget_usd raises ValueError."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            with pytest.raises(ValueError, match="cost_budget_usd must be > 0"):
                DialogueOrchestrator(cost_budget_usd=0.0)

    def test_none_cost_budget_allowed(self):
        """Test that None cost_budget_usd is valid (unlimited)."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            strategy = DialogueOrchestrator(cost_budget_usd=None)
        assert strategy.cost_budget_usd is None

    def test_semantic_convergence_flag(self):
        """Test initialization accepts use_semantic_convergence parameter."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            strategy = DialogueOrchestrator(
                max_rounds=5,
                convergence_threshold=0.90,
                use_semantic_convergence=True,
            )
        assert strategy.max_rounds == 5
        assert strategy.convergence_threshold == 0.90
        assert strategy.use_semantic_convergence is True

    def test_context_strategy_parameter(self):
        """Test initialization accepts context_strategy parameter."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            s_full = DialogueOrchestrator(context_strategy="full")
            s_recent = DialogueOrchestrator(context_strategy="recent")
            s_relevant = DialogueOrchestrator(context_strategy="relevant")
        assert s_full.context_strategy == "full"
        assert s_recent.context_strategy == "recent"
        assert s_relevant.context_strategy == "relevant"

    def test_invalid_context_strategy_raises(self):
        """Test that invalid context_strategy raises ValueError."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            with pytest.raises(ValueError, match="Invalid context_strategy"):
                DialogueOrchestrator(context_strategy="invalid")

    def test_context_window_size_validation(self):
        """Test context_window_size validation."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            with pytest.raises(ValueError, match="context_window_size must be >= 1"):
                DialogueOrchestrator(context_window_size=0)
            strategy = DialogueOrchestrator(context_window_size=3)
        assert strategy.context_window_size == 3

    def test_merit_weighting_parameters(self):
        """Test merit weighting initialization parameters."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            s_enabled = DialogueOrchestrator(use_merit_weighting=True)
            s_disabled = DialogueOrchestrator(use_merit_weighting=False)
        assert s_enabled.use_merit_weighting is True
        assert s_disabled.use_merit_weighting is False

    def test_merit_domain_parameter(self):
        """Test merit_domain parameter."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            strategy = DialogueOrchestrator(
                use_merit_weighting=True,
                merit_domain="architecture_decisions",
            )
        assert strategy.merit_domain == "architecture_decisions"


class TestDialogueOrchestratorSynthesize:
    """Test DialogueOrchestrator synthesize() method."""

    def test_synthesize_unanimous_decision(self):
        """Test synthesis with unanimous agent agreement."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            strategy = DialogueOrchestrator()
        outputs = [
            AgentOutput("agent1", "Option A", "reason1", 0.9, {}),
            AgentOutput("agent2", "Option A", "reason2", 0.8, {}),
            AgentOutput("agent3", "Option A", "reason3", 0.85, {}),
        ]
        result = strategy.synthesize(outputs, {})
        assert result.decision == "Option A"
        assert result.confidence > 0.8
        assert result.votes["Option A"] == 3

    def test_synthesize_majority_decision(self):
        """Test synthesis with majority decision (2/3 agree)."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            strategy = DialogueOrchestrator()
        outputs = [
            AgentOutput("agent1", "Option A", "reason1", 0.9, {}),
            AgentOutput("agent2", "Option A", "reason2", 0.8, {}),
            AgentOutput("agent3", "Option B", "reason3", 0.7, {}),
        ]
        result = strategy.synthesize(outputs, {})
        assert result.decision == "Option A"
        assert result.votes == {"Option A": 2, "Option B": 1}

    def test_synthesize_delegates_to_consensus(self):
        """Test that synthesize uses consensus strategy."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            strategy = DialogueOrchestrator()
        outputs = [
            AgentOutput("agent1", "Option A", "reason1", 0.9, {}),
            AgentOutput("agent2", "Option A", "reason2", 0.8, {}),
        ]
        result = strategy.synthesize(outputs, {})
        assert result.method == "consensus"
        assert result.metadata["synthesis_method"] == "consensus_from_final_round"
        assert result.metadata["mode"] == "dialogue"

    def test_synthesize_with_single_agent(self):
        """Test synthesis with single agent (edge case)."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            strategy = DialogueOrchestrator()
        outputs = [AgentOutput("agent1", "Option A", "reason", 0.9, {})]
        result = strategy.synthesize(outputs, {})
        assert result.decision == "Option A"
        assert result.confidence > 0

    def test_synthesize_empty_outputs_raises(self):
        """Test that empty outputs raises ValueError."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            strategy = DialogueOrchestrator()
        with pytest.raises(ValueError, match="cannot be empty"):
            strategy.synthesize([], {})

    def test_synthesize_passes_config_to_consensus(self):
        """Test that config is passed to consensus strategy."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            strategy = DialogueOrchestrator()
        outputs = [
            AgentOutput("agent1", "Option A", "reason1", 0.9, {}),
            AgentOutput("agent2", "Option A", "reason2", 0.8, {}),
            AgentOutput("agent3", "Option B", "reason3", 0.7, {}),
            AgentOutput("agent4", "Option C", "reason4", 0.6, {}),
        ]
        result = strategy.synthesize(outputs, {"min_consensus": 0.75})
        # Should use weak consensus since 2/4 = 50% < 75%
        assert result.method == "consensus_weak"
        assert result.metadata["needs_conflict_resolution"] is True

    def test_synthesize_with_conflicting_agents(self):
        """Test synthesis with complete disagreement."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            strategy = DialogueOrchestrator()
        outputs = [
            AgentOutput("agent1", "A", "r1", 0.8, {}),
            AgentOutput("agent2", "B", "r2", 0.8, {}),
            AgentOutput("agent3", "C", "r3", 0.8, {}),
        ]
        result = strategy.synthesize(outputs, {})
        assert result.decision in ["A", "B", "C"]
        assert result.method in ["consensus_weak", "consensus"]

    def test_synthesize_with_different_decision_types(self):
        """Test synthesis with different decision types (int, str, etc.)."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            strategy = DialogueOrchestrator()
        outputs = [
            AgentOutput("agent1", 1, "reason1", 0.9, {}),
            AgentOutput("agent2", 1, "reason2", 0.8, {}),
            AgentOutput("agent3", 2, "reason3", 0.7, {}),
        ]
        result = strategy.synthesize(outputs, {})
        assert result.decision == 1
        assert isinstance(result.decision, int)
        assert result.votes == {1: 2, 2: 1}

    @patch("temper_ai.agent.strategies._dialogue_helpers.get_merit_weights")
    def test_merit_weighted_synthesis(self, mock_get_weights):
        """Test merit-weighted synthesis with mocked DB."""
        mock_get_weights.return_value = {"a1": 1.0, "a2": 1.0, "a3": 1.0}
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            strategy = DialogueOrchestrator(use_merit_weighting=True)
        outputs = [
            AgentOutput("a1", "Option A", "r1", 0.9, {}),
            AgentOutput("a2", "Option A", "r2", 0.8, {}),
            AgentOutput("a3", "Option B", "r3", 0.7, {}),
        ]
        result = strategy.synthesize(outputs, {})
        assert result.decision == "Option A"
        assert result.method == "merit_weighted"
        assert result.metadata["synthesis_method"] == "merit_weighted"

    def test_disabled_merit_weighting_uses_consensus(self):
        """Test that disabling merit weighting uses consensus strategy."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            strategy = DialogueOrchestrator(use_merit_weighting=False)
        outputs = [
            AgentOutput("a1", "Option A", "r1", 0.9, {}),
            AgentOutput("a2", "Option A", "r2", 0.8, {}),
        ]
        result = strategy.synthesize(outputs, {})
        assert result.method == "consensus"
        assert result.metadata["synthesis_method"] == "consensus_from_final_round"

    @patch("temper_ai.agent.strategies._dialogue_helpers.get_merit_weights")
    def test_merit_weighting_with_single_agent(self, mock_get_weights):
        """Test merit weighting with single agent."""
        mock_get_weights.return_value = {"a1": 1.0}
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            strategy = DialogueOrchestrator(use_merit_weighting=True)
        outputs = [AgentOutput("a1", "Option A", "reason", 0.9, {})]
        result = strategy.synthesize(outputs, {})
        assert result.decision == "Option A"
        assert result.method == "merit_weighted"

    @patch("temper_ai.agent.strategies._dialogue_helpers.get_merit_weights")
    def test_merit_weighting_with_tie(self, mock_get_weights):
        """Test merit weighting breaks ties by weight."""
        mock_get_weights.return_value = {"a1": 1.0, "a2": 1.0}
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            strategy = DialogueOrchestrator(use_merit_weighting=True)
        outputs = [
            AgentOutput("a1", "Option A", "r1", 0.8, {}),
            AgentOutput("a2", "Option B", "r2", 0.8, {}),
        ]
        result = strategy.synthesize(outputs, {})
        assert result.decision in ["Option A", "Option B"]
        assert result.method == "merit_weighted"


class TestDialogueOrchestratorCapabilities:
    """Test DialogueOrchestrator get_capabilities() method."""

    def test_get_capabilities(self):
        """Test that capabilities are correctly reported."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            strategy = DialogueOrchestrator()
        caps = strategy.get_capabilities()
        assert caps["supports_dialogue"] is True
        assert caps["supports_convergence"] is True
        assert caps["supports_multi_round"] is True
        assert caps["supports_async"] is False

    def test_capabilities_are_consistent(self):
        """Test that capabilities match implementation."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            strategy = DialogueOrchestrator()
        caps = strategy.get_capabilities()
        assert caps["supports_dialogue"] is True
        assert strategy.requires_requery is True

    def test_capabilities_independent_of_config(self):
        """Test that capabilities don't change with configuration."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            strategy_default = DialogueOrchestrator()
            strategy_custom = DialogueOrchestrator(
                max_rounds=10, convergence_threshold=0.95, cost_budget_usd=50.0
            )
        assert strategy_default.get_capabilities() == strategy_custom.get_capabilities()

    def test_capabilities_report_merit_weighting(self):
        """Test capabilities with merit weighting enabled."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            strategy = DialogueOrchestrator(use_merit_weighting=True)
        caps = strategy.get_capabilities()
        assert caps["supports_merit_weighting"] is True

    def test_metadata(self):
        """Test strategy metadata."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            strategy = DialogueOrchestrator()
        metadata = strategy.get_metadata()
        assert metadata["name"] == "DialogueOrchestrator"
        assert "config_schema" in metadata


class TestDialogueRound:
    """Test DialogueRound alias (CommunicationRound)."""

    def test_is_communication_round(self):
        assert DialogueRound is CommunicationRound

    def test_creation(self):
        outputs = [AgentOutput("a1", "A", "r", 0.8, {})]
        r = DialogueRound(round_number=0, agent_outputs=outputs, convergence_score=0.5)
        assert r.round_number == 0
        assert r.convergence_score == 0.5

    def test_default_metadata(self):
        r = DialogueRound(round_number=0, agent_outputs=[])
        assert r.metadata == {}

    def test_multiple_agents(self):
        outputs = [
            AgentOutput("a1", "A", "r1", 0.9, {}),
            AgentOutput("a2", "A", "r2", 0.8, {}),
            AgentOutput("a3", "B", "r3", 0.7, {}),
        ]
        r = DialogueRound(round_number=0, agent_outputs=outputs)
        assert len(r.agent_outputs) == 3
        assert r.agent_outputs[0].agent_name == "a1"
        assert r.agent_outputs[2].agent_name == "a3"


class TestDialogueHistory:
    """Test DialogueHistory alias (CommunicationHistory)."""

    def test_is_communication_history(self):
        assert DialogueHistory is CommunicationHistory

    def test_creation(self):
        h = DialogueHistory(total_rounds=3, converged=True, convergence_round=2)
        assert h.total_rounds == 3
        assert h.converged is True
        assert h.convergence_round == 2

    def test_defaults(self):
        h = DialogueHistory()
        assert h.total_rounds == 0
        assert h.converged is False
        assert h.convergence_round == -1

    def test_early_stop_reasons(self):
        """Test different early stop reasons."""
        h_conv = DialogueHistory(
            total_rounds=2, converged=True, convergence_round=1,
            early_stop_reason="convergence",
        )
        assert h_conv.early_stop_reason == "convergence"

        h_budget = DialogueHistory(
            total_rounds=1, converged=False, early_stop_reason="budget",
        )
        assert h_budget.early_stop_reason == "budget"

        h_max = DialogueHistory(
            total_rounds=3, converged=False, early_stop_reason="max_rounds",
        )
        assert h_max.early_stop_reason == "max_rounds"

    def test_no_convergence(self):
        """Test history when dialogue doesn't converge."""
        h = DialogueHistory(
            total_rounds=3, converged=False, convergence_round=0,
            early_stop_reason="max_rounds",
        )
        assert h.converged is False
        assert h.convergence_round == 0
        assert h.early_stop_reason == "max_rounds"

    def test_with_rounds(self):
        """Test history with round objects."""
        outputs = [AgentOutput("a1", "A", "r", 0.8, {})]
        r1 = DialogueRound(round_number=0, agent_outputs=outputs)
        r2 = DialogueRound(round_number=1, agent_outputs=outputs, convergence_score=1.0)
        h = DialogueHistory(
            rounds=[r1, r2], total_rounds=2, converged=True, convergence_round=1,
            total_cost_usd=2.0,
        )
        assert len(h.rounds) == 2
        assert h.total_cost_usd == 2.0
        assert h.rounds[1].convergence_score == 1.0


class TestDialogueOrchestratorConvergence:
    """Test convergence detection functionality."""

    def test_exact_match_convergence_all_unchanged(self):
        """Test exact match convergence when all agents unchanged."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            strategy = DialogueOrchestrator(use_semantic_convergence=False)
        current = [
            AgentOutput("a1", "Option A", "r", 0.8, {}),
            AgentOutput("a2", "Option B", "r", 0.8, {}),
        ]
        previous = [
            AgentOutput("a1", "Option A", "r", 0.7, {}),
            AgentOutput("a2", "Option B", "r", 0.7, {}),
        ]
        convergence = strategy.calculate_convergence(current, previous)
        assert convergence == 1.0

    def test_exact_match_convergence_half_changed(self):
        """Test exact match convergence when half changed."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            strategy = DialogueOrchestrator(use_semantic_convergence=False)
        current = [
            AgentOutput("a1", "Option A", "r", 0.8, {}),
            AgentOutput("a2", "Option A", "r", 0.8, {}),
        ]
        previous = [
            AgentOutput("a1", "Option A", "r", 0.7, {}),
            AgentOutput("a2", "Option B", "r", 0.7, {}),
        ]
        convergence = strategy.calculate_convergence(current, previous)
        assert convergence == 0.5

    def test_exact_match_convergence_all_changed(self):
        """Test exact match convergence when all changed."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            strategy = DialogueOrchestrator(use_semantic_convergence=False)
        current = [
            AgentOutput("a1", "Option B", "r", 0.8, {}),
            AgentOutput("a2", "Option A", "r", 0.8, {}),
        ]
        previous = [
            AgentOutput("a1", "Option A", "r", 0.7, {}),
            AgentOutput("a2", "Option B", "r", 0.7, {}),
        ]
        convergence = strategy.calculate_convergence(current, previous)
        assert convergence == 0.0

    def test_exact_match_convergence_first_round(self):
        """Test convergence on first round returns 0.0."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            strategy = DialogueOrchestrator(use_semantic_convergence=False)
        current = [AgentOutput("a1", "Option A", "r", 0.8, {})]
        convergence = strategy.calculate_convergence(current, [])
        assert convergence == 0.0

    def test_use_semantic_convergence_flag(self):
        """Test use_semantic_convergence flag in initialization."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            s_semantic = DialogueOrchestrator(use_semantic_convergence=True)
            s_exact = DialogueOrchestrator(use_semantic_convergence=False)
        assert s_semantic.use_semantic_convergence is True
        assert s_exact.use_semantic_convergence is False

    def test_semantic_convergence_with_similar_phrasing(self):
        """Test semantic convergence detects similar phrasing (if embeddings available)."""
        try:
            import sentence_transformers  # noqa: F401
        except ImportError:
            pytest.skip("sentence-transformers not available")

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            strategy = DialogueOrchestrator(use_semantic_convergence=True)
        current = [AgentOutput("a1", "Use microservices architecture", "r", 0.8, {})]
        previous = [AgentOutput("a1", "Adopt microservices approach", "r", 0.7, {})]
        convergence = strategy.calculate_convergence(current, previous)
        assert convergence > 0.5

    def test_semantic_convergence_fallback_to_exact(self):
        """Test fallback to exact match when embeddings unavailable."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            strategy = DialogueOrchestrator(use_semantic_convergence=True)
        strategy._embeddings_available = False
        current = [AgentOutput("a1", "Use microservices", "r", 0.8, {})]
        previous = [AgentOutput("a1", "Adopt microservices", "r", 0.7, {})]
        convergence = strategy.calculate_convergence(current, previous)
        assert convergence == 0.0

    def test_convergence_with_integer_decisions(self):
        """Test convergence works with non-string decisions."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            strategy = DialogueOrchestrator(use_semantic_convergence=False)
        current = [
            AgentOutput("a1", 1, "r", 0.8, {}),
            AgentOutput("a2", 2, "r", 0.8, {}),
        ]
        previous = [
            AgentOutput("a1", 1, "r", 0.7, {}),
            AgentOutput("a2", 2, "r", 0.7, {}),
        ]
        convergence = strategy.calculate_convergence(current, previous)
        assert convergence == 1.0

    def test_convergence_with_missing_agents(self):
        """Test convergence when agent sets differ."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            strategy = DialogueOrchestrator(use_semantic_convergence=False)
        current = [
            AgentOutput("a1", "A", "r", 0.8, {}),
            AgentOutput("a2", "B", "r", 0.8, {}),
        ]
        previous = [
            AgentOutput("a1", "A", "r", 0.7, {}),
            AgentOutput("a3", "C", "r", 0.7, {}),
        ]
        convergence = strategy.calculate_convergence(current, previous)
        assert convergence == 1.0  # Only a1 is common, unchanged

    def test_convergence_with_no_common_agents(self):
        """Test convergence when no agents in common."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            strategy = DialogueOrchestrator(use_semantic_convergence=False)
        current = [AgentOutput("a1", "A", "r", 0.8, {})]
        previous = [AgentOutput("a2", "B", "r", 0.7, {})]
        convergence = strategy.calculate_convergence(current, previous)
        assert convergence == 0.0

    def test_check_embeddings_available(self):
        """Test embeddings availability check."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            strategy = DialogueOrchestrator(use_semantic_convergence=True)
        first_check = strategy._check_embeddings_available()
        second_check = strategy._check_embeddings_available()
        assert isinstance(first_check, bool)
        assert first_check == second_check  # Cached

    def test_convergence_with_empty_previous(self):
        """Test convergence handles empty previous outputs gracefully."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            strategy = DialogueOrchestrator(use_semantic_convergence=True)
        current = [AgentOutput("a1", "A", "r", 0.8, {})]
        convergence = strategy.calculate_convergence(current, [])
        assert convergence == 0.0


class TestDialogueOrchestratorContextCuration:
    """Test context curation enhancements."""

    def test_curate_full_strategy(self):
        """Test 'full' strategy returns all history."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            strategy = DialogueOrchestrator(context_strategy="full")
        history = [
            {"agent": "a1", "round": 0, "output": "A", "reasoning": "r1", "confidence": 0.8},
            {"agent": "a2", "round": 0, "output": "B", "reasoning": "r2", "confidence": 0.8},
            {"agent": "a1", "round": 1, "output": "A", "reasoning": "r3", "confidence": 0.9},
            {"agent": "a2", "round": 1, "output": "A", "reasoning": "r4", "confidence": 0.85},
        ]
        curated = strategy.curate_dialogue_history(history, current_round=2)
        assert len(curated) == 4

    def test_curate_recent_strategy(self):
        """Test 'recent' strategy returns only recent rounds."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            strategy = DialogueOrchestrator(context_strategy="recent", context_window_size=1)
        history = [
            {"agent": "a1", "round": 0, "output": "A", "reasoning": "r1", "confidence": 0.8},
            {"agent": "a2", "round": 0, "output": "B", "reasoning": "r2", "confidence": 0.8},
            {"agent": "a1", "round": 2, "output": "A", "reasoning": "r5", "confidence": 0.95},
            {"agent": "a2", "round": 2, "output": "A", "reasoning": "r6", "confidence": 0.90},
        ]
        curated = strategy.curate_dialogue_history(history, current_round=3)
        assert len(curated) == 2
        assert all(entry["round"] == 2 for entry in curated)

    def test_curate_recent_with_window_size_2(self):
        """Test 'recent' strategy with window size 2."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            strategy = DialogueOrchestrator(context_strategy="recent", context_window_size=2)
        history = [
            {"agent": "a1", "round": 0, "output": "A", "reasoning": "r1", "confidence": 0.8},
            {"agent": "a1", "round": 1, "output": "A", "reasoning": "r2", "confidence": 0.9},
            {"agent": "a1", "round": 2, "output": "A", "reasoning": "r3", "confidence": 0.95},
        ]
        curated = strategy.curate_dialogue_history(history, current_round=3)
        assert len(curated) == 2
        assert {entry["round"] for entry in curated} == {1, 2}

    def test_curate_relevant_strategy_with_agent_name(self):
        """Test 'relevant' strategy filters by agent relevance."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            strategy = DialogueOrchestrator(context_strategy="relevant")
        history = [
            {"agent": "a1", "round": 0, "output": "A", "reasoning": "initial", "confidence": 0.8},
            {"agent": "a2", "round": 0, "output": "B", "reasoning": "a1 is wrong", "confidence": 0.8},
            {"agent": "a3", "round": 0, "output": "C", "reasoning": "unrelated", "confidence": 0.8},
            {"agent": "a1", "round": 1, "output": "A", "reasoning": "final", "confidence": 0.9},
        ]
        curated = strategy.curate_dialogue_history(history, current_round=2, agent_name="a1")
        assert len(curated) >= 2
        assert any(entry["agent"] == "a1" for entry in curated)
        assert any("a1" in entry["reasoning"].lower() for entry in curated)

    def test_curate_relevant_without_agent_name_falls_back(self):
        """Test 'relevant' strategy falls back to recent when no agent_name."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            strategy = DialogueOrchestrator(context_strategy="relevant", context_window_size=1)
        history = [
            {"agent": "a1", "round": 0, "output": "A", "reasoning": "r1", "confidence": 0.8},
            {"agent": "a1", "round": 1, "output": "A", "reasoning": "r2", "confidence": 0.9},
        ]
        curated = strategy.curate_dialogue_history(history, current_round=2, agent_name=None)
        assert len(curated) == 1
        assert curated[0]["round"] == 1

    def test_curate_empty_history(self):
        """Test curation with empty history."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            strategy = DialogueOrchestrator(context_strategy="recent")
        curated = strategy.curate_dialogue_history([], current_round=0)
        assert curated == []

    def test_context_curation_reduces_size(self):
        """Test that context curation actually reduces history size."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            strategy_full = DialogueOrchestrator(context_strategy="full")
            strategy_recent = DialogueOrchestrator(context_strategy="recent", context_window_size=1)
        history = []
        for round_num in range(5):
            history.append({"agent": "a1", "round": round_num, "output": "A", "reasoning": "r", "confidence": 0.8})
            history.append({"agent": "a2", "round": round_num, "output": "B", "reasoning": "r", "confidence": 0.8})
        curated_full = strategy_full.curate_dialogue_history(history, current_round=5)
        curated_recent = strategy_recent.curate_dialogue_history(history, current_round=5)
        assert len(curated_full) == 10
        assert len(curated_recent) == 2
        assert len(curated_recent) < len(curated_full)


class TestDialogueOrchestratorEdgeCases:
    """Test edge cases and error conditions."""

    def test_single_round_configuration(self):
        """Test dialogue with max_rounds=1."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            strategy = DialogueOrchestrator(max_rounds=1)
        outputs = [
            AgentOutput("agent1", "A", "r1", 0.9, {}),
            AgentOutput("agent2", "A", "r2", 0.8, {}),
        ]
        result = strategy.synthesize(outputs, {})
        assert result.decision == "A"

    def test_high_convergence_threshold(self):
        """Test with very high convergence threshold."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            strategy = DialogueOrchestrator(convergence_threshold=0.99)
        assert strategy.convergence_threshold == 0.99

    def test_low_convergence_threshold(self):
        """Test with very low convergence threshold."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            strategy = DialogueOrchestrator(convergence_threshold=0.1)
        assert strategy.convergence_threshold == 0.1

    def test_min_rounds_greater_than_max_rounds(self):
        """Test that min_rounds > max_rounds is allowed (executor enforces)."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            strategy = DialogueOrchestrator(min_rounds=5, max_rounds=3)
        assert strategy.min_rounds == 5
        assert strategy.max_rounds == 3


class TestDialogueOrchestratorIntegration:
    """Test integration scenarios and realistic use cases."""

    def test_architecture_decision_scenario(self):
        """Test realistic scenario: architecture decision dialogue."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            strategy = DialogueOrchestrator(
                max_rounds=3, convergence_threshold=0.85, cost_budget_usd=10.0,
            )
        outputs = [
            AgentOutput("architect", "Use microservices", "scalability", 0.85, {}),
            AgentOutput("security_engineer", "Use microservices", "reviewed", 0.80, {}),
            AgentOutput("performance_engineer", "Use microservices", "addressed", 0.75, {}),
        ]
        result = strategy.synthesize(outputs, {})
        assert result.decision == "Use microservices"
        assert result.confidence > 0.75
        assert result.votes["Use microservices"] == 3

    def test_cost_tracking_scenario(self):
        """Test realistic scenario with cost tracking."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            strategy = DialogueOrchestrator(cost_budget_usd=5.0)
        outputs = [
            AgentOutput("a1", "A", "r1", 0.9, {"cost_usd": 1.5}),
            AgentOutput("a2", "A", "r2", 0.8, {"cost_usd": 1.5}),
        ]
        result = strategy.synthesize(outputs, {})
        assert result.decision == "A"

    def test_multiple_rounds_data_structure(self):
        """Test building complete dialogue history structure."""
        outputs_r1 = [
            AgentOutput("a1", "A", "initial", 0.75, {}),
            AgentOutput("a2", "B", "initial", 0.75, {}),
        ]
        outputs_r2 = [
            AgentOutput("a1", "A", "still A", 0.80, {}),
            AgentOutput("a2", "A", "changed to A", 0.75, {}),
        ]
        round1 = DialogueRound(round_number=0, agent_outputs=outputs_r1, convergence_score=0.0)
        round2 = DialogueRound(round_number=1, agent_outputs=outputs_r2, convergence_score=1.0)
        history = DialogueHistory(
            rounds=[round1, round2], total_rounds=2, converged=True,
            convergence_round=1, total_cost_usd=2.0,
        )
        assert len(history.rounds) == 2
        assert history.converged is True
        assert history.total_cost_usd == 2.0
        assert history.rounds[0].round_number == 0
        assert history.rounds[1].convergence_score == 1.0
