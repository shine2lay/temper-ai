"""Tests for debate-based collaboration strategy.

Tests multi-round debate with convergence detection, including:
- Single-round debates (immediate convergence)
- Multi-round convergence scenarios
- Max rounds termination
- Convergence calculation
- New insights detection
- Unanimous requirements
- Minimum rounds enforcement
"""

import pytest
from src.strategies.debate import DebateAndSynthesize, DebateRound, DebateHistory
from src.strategies.base import AgentOutput


class TestDebateAndSynthesize:
    """Test suite for DebateAndSynthesize strategy."""

    def test_single_round_unanimous_debate(self):
        """Test debate with unanimous decision (converges immediately)."""
        strategy = DebateAndSynthesize()
        outputs = [
            AgentOutput("a1", "Option A", "reason1", 0.9, {}),
            AgentOutput("a2", "Option A", "reason2", 0.8, {}),
            AgentOutput("a3", "Option A", "reason3", 0.85, {})
        ]

        result = strategy.synthesize(outputs, {"max_rounds": 3})

        assert result.decision == "Option A"
        assert result.metadata["total_rounds"] >= 1
        assert result.metadata["converged"] is True
        assert result.confidence > 0.8  # High confidence for unanimous
        assert result.method == "debate_and_synthesize"

    def test_multi_round_configuration(self):
        """Test debate respects configured rounds."""
        strategy = DebateAndSynthesize()

        outputs = [
            AgentOutput("a1", "Option A", "reason1", 0.9, {}),
            AgentOutput("a2", "Option A", "reason2", 0.8, {}),
            AgentOutput("a3", "Option B", "reason3", 0.7, {})
        ]

        result = strategy.synthesize(outputs, {
            "max_rounds": 3,
            "convergence_threshold": 0.6  # Lower threshold for test
        })

        assert result.decision in ["Option A", "Option B"]
        assert "total_rounds" in result.metadata
        assert result.metadata["total_rounds"] <= 3

    def test_max_rounds_termination(self):
        """Test debate stops at max_rounds without early convergence."""
        strategy = DebateAndSynthesize()
        outputs = [
            AgentOutput("a1", "Option A", "reason", 0.8, {}),
            AgentOutput("a2", "Option B", "reason", 0.8, {}),
            AgentOutput("a3", "Option C", "reason", 0.8, {})
        ]

        # Set min_rounds = max_rounds to force all rounds to execute
        result = strategy.synthesize(outputs, {
            "max_rounds": 2,
            "min_rounds": 2  # Force 2 rounds regardless of convergence
        })

        assert result.metadata["total_rounds"] == 2

    def test_majority_decision_extraction(self):
        """Test that majority decision wins."""
        strategy = DebateAndSynthesize()
        outputs = [
            AgentOutput("a1", "Option A", "reason1", 0.9, {}),
            AgentOutput("a2", "Option A", "reason2", 0.8, {}),
            AgentOutput("a3", "Option B", "reason3", 0.7, {}),
            AgentOutput("a4", "Option C", "reason4", 0.6, {})
        ]

        result = strategy.synthesize(outputs, {"max_rounds": 1})

        assert result.decision == "Option A"  # 2 votes
        assert result.votes["Option A"] == 2
        assert result.votes["Option B"] == 1
        assert result.votes["Option C"] == 1

    def test_convergence_score_all_unchanged(self):
        """Test convergence score calculation - all agents unchanged."""
        strategy = DebateAndSynthesize()

        current = [
            AgentOutput("a1", "A", "r", 0.8, {}),
            AgentOutput("a2", "B", "r", 0.8, {})
        ]
        previous = {"a1": "A", "a2": "B"}

        score = strategy._calculate_convergence(current, previous)
        assert score == 1.0  # 100% unchanged

    def test_convergence_score_half_changed(self):
        """Test convergence score - half changed."""
        strategy = DebateAndSynthesize()

        current = [
            AgentOutput("a1", "A", "r", 0.8, {}),
            AgentOutput("a2", "A", "r", 0.8, {})  # Changed from B to A
        ]
        previous = {"a1": "A", "a2": "B"}

        score = strategy._calculate_convergence(current, previous)
        assert score == 0.5  # 50% unchanged

    def test_convergence_score_first_round(self):
        """Test convergence score for first round (no previous)."""
        strategy = DebateAndSynthesize()

        current = [AgentOutput("a1", "A", "r", 0.8, {})]

        score = strategy._calculate_convergence(current, None)
        assert score == 0.0  # First round, no convergence yet

    def test_new_insights_first_round(self):
        """Test new insights detection - first round always has insights."""
        strategy = DebateAndSynthesize()

        outputs = [AgentOutput("a1", "A", "r", 0.8, {})]
        assert strategy._detect_new_insights(outputs, None) is True

    def test_new_insights_no_change(self):
        """Test new insights detection - no changes means no new insights."""
        strategy = DebateAndSynthesize()

        outputs = [AgentOutput("a1", "A", "r", 0.8, {})]
        previous = {"a1": "A"}

        assert strategy._detect_new_insights(outputs, previous) is False

    def test_new_insights_position_changed(self):
        """Test new insights detection - position change means new insight."""
        strategy = DebateAndSynthesize()

        outputs = [AgentOutput("a1", "B", "r", 0.8, {})]
        previous = {"a1": "A"}

        assert strategy._detect_new_insights(outputs, previous) is True

    def test_decision_distribution(self):
        """Test decision distribution calculation."""
        strategy = DebateAndSynthesize()

        outputs = [
            AgentOutput("a1", "A", "r", 0.8, {}),
            AgentOutput("a2", "A", "r", 0.8, {}),
            AgentOutput("a3", "B", "r", 0.7, {})
        ]

        dist = strategy._get_decision_distribution(outputs)
        assert dist["A"] == 2
        assert dist["B"] == 1

    def test_unanimous_requirement_satisfied(self):
        """Test require_unanimous with unanimous agreement."""
        strategy = DebateAndSynthesize()
        outputs = [
            AgentOutput("a1", "A", "r", 0.9, {}),
            AgentOutput("a2", "A", "r", 0.8, {}),
            AgentOutput("a3", "A", "r", 0.85, {})
        ]

        result = strategy.synthesize(outputs, {
            "require_unanimous": True,
            "max_rounds": 1
        })

        # Should have high confidence for unanimous
        assert result.confidence > 0.8

    def test_unanimous_requirement_not_satisfied(self):
        """Test require_unanimous with dissenter."""
        strategy = DebateAndSynthesize()
        outputs = [
            AgentOutput("a1", "A", "r", 0.9, {}),
            AgentOutput("a2", "A", "r", 0.8, {}),
            AgentOutput("a3", "B", "r", 0.7, {})  # Dissenter
        ]

        result = strategy.synthesize(outputs, {
            "require_unanimous": True,
            "max_rounds": 1
        })

        # Should have lower confidence due to non-unanimous
        assert result.confidence < 0.7

    def test_min_rounds_enforcement(self):
        """Test minimum rounds enforcement."""
        strategy = DebateAndSynthesize()
        outputs = [
            AgentOutput("a1", "A", "r", 0.9, {}),
            AgentOutput("a2", "A", "r", 0.8, {}),
            AgentOutput("a3", "A", "r", 0.85, {})
        ]

        result = strategy.synthesize(outputs, {
            "min_rounds": 2,
            "convergence_threshold": 1.0  # Would converge after round 1
        })

        # Should run at least 2 rounds even though unanimous
        assert result.metadata["total_rounds"] >= 2

    def test_extract_consensus_majority(self):
        """Test consensus extraction with clear majority."""
        strategy = DebateAndSynthesize()

        outputs = [
            AgentOutput("a1", "A", "r", 0.9, {}),
            AgentOutput("a2", "A", "r", 0.8, {}),
            AgentOutput("a3", "B", "r", 0.7, {})
        ]

        history = DebateHistory(
            rounds=[],
            total_rounds=1,
            converged=False,
            convergence_round=-1
        )

        decision, confidence = strategy._extract_consensus(outputs, history, False)

        assert decision == "A"
        assert confidence > 0  # Some confidence

    def test_extract_consensus_convergence_bonus(self):
        """Test that converged debates get confidence boost."""
        strategy = DebateAndSynthesize()

        outputs = [
            AgentOutput("a1", "A", "r", 0.9, {}),
            AgentOutput("a2", "A", "r", 0.8, {})
        ]

        # Converged history
        history_converged = DebateHistory(
            rounds=[],
            total_rounds=2,
            converged=True,
            convergence_round=1
        )

        # Not converged history
        history_not_converged = DebateHistory(
            rounds=[],
            total_rounds=2,
            converged=False,
            convergence_round=-1
        )

        _, confidence_converged = strategy._extract_consensus(
            outputs, history_converged, False
        )
        _, confidence_not_converged = strategy._extract_consensus(
            outputs, history_not_converged, False
        )

        # Converged should have higher confidence
        assert confidence_converged > confidence_not_converged

    def test_build_debate_reasoning(self):
        """Test debate reasoning generation."""
        strategy = DebateAndSynthesize()

        history = DebateHistory(
            rounds=[
                DebateRound(
                    round_number=0,
                    agent_outputs=[],
                    convergence_score=0.5,
                    new_insights=True,
                    metadata={"decision_distribution": {"A": 2, "B": 1}}
                )
            ],
            total_rounds=1,
            converged=False,
            convergence_round=-1
        )

        reasoning = strategy._build_debate_reasoning("A", history, [])

        assert "1 rounds" in reasoning
        assert "decision: 'A'" in reasoning
        assert "Maximum rounds" in reasoning  # Not converged

    def test_build_debate_reasoning_converged(self):
        """Test reasoning generation for converged debate."""
        strategy = DebateAndSynthesize()

        history = DebateHistory(
            rounds=[
                DebateRound(
                    round_number=0,
                    agent_outputs=[],
                    convergence_score=0.5,
                    new_insights=True,
                    metadata={"decision_distribution": {"A": 2, "B": 1}}
                ),
                DebateRound(
                    round_number=1,
                    agent_outputs=[],
                    convergence_score=1.0,
                    new_insights=False,
                    metadata={"decision_distribution": {"A": 3}}
                )
            ],
            total_rounds=2,
            converged=True,
            convergence_round=1
        )

        reasoning = strategy._build_debate_reasoning("A", history, [])

        assert "2 rounds" in reasoning
        assert "Convergence achieved at round 2" in reasoning

    def test_serialize_debate_history(self):
        """Test debate history serialization."""
        strategy = DebateAndSynthesize()

        history = DebateHistory(
            rounds=[
                DebateRound(
                    round_number=0,
                    agent_outputs=[],
                    convergence_score=0.7,
                    new_insights=True,
                    metadata={"decision_distribution": {"A": 2, "B": 1}}
                )
            ],
            total_rounds=1,
            converged=False,
            convergence_round=-1
        )

        serialized = strategy._serialize_debate_history(history)

        assert serialized["total_rounds"] == 1
        assert serialized["converged"] is False
        assert serialized["convergence_round"] == -1
        assert len(serialized["rounds"]) == 1
        assert serialized["rounds"][0]["round_number"] == 0
        assert serialized["rounds"][0]["convergence_score"] == 0.7

    def test_capabilities(self):
        """Test strategy capabilities."""
        strategy = DebateAndSynthesize()
        caps = strategy.get_capabilities()

        assert caps["supports_debate"] is True
        assert caps["supports_convergence"] is True
        assert caps["supports_merit_weighting"] is False  # Not yet implemented
        assert caps["supports_partial_participation"] is True
        assert caps["supports_async"] is False  # Sync only for now
        assert caps["deterministic"] is False  # Depends on agent responses
        assert caps["requires_conflict_resolver"] is True

    def test_get_metadata(self):
        """Test strategy metadata."""
        strategy = DebateAndSynthesize()
        metadata = strategy.get_metadata()

        assert metadata["name"] == "DebateAndSynthesize"
        assert "config_schema" in metadata
        assert "max_rounds" in metadata["config_schema"]
        assert metadata["config_schema"]["max_rounds"]["default"] == 3
        assert metadata["config_schema"]["convergence_threshold"]["default"] == 0.8

    def test_validate_inputs_called(self):
        """Test that input validation is performed."""
        strategy = DebateAndSynthesize()

        # Empty list should raise ValueError
        with pytest.raises(ValueError, match="cannot be empty"):
            strategy.synthesize([], {})

    def test_debate_with_single_agent(self):
        """Test debate with single agent (edge case)."""
        strategy = DebateAndSynthesize()
        outputs = [AgentOutput("a1", "Option A", "reason", 0.9, {})]

        result = strategy.synthesize(outputs, {"max_rounds": 2})

        assert result.decision == "Option A"
        assert result.confidence > 0
        assert result.metadata["total_rounds"] >= 1

    def test_conflict_detection_in_result(self):
        """Test that conflicts are detected and included in result."""
        strategy = DebateAndSynthesize()
        outputs = [
            AgentOutput("a1", "A", "r", 0.9, {}),
            AgentOutput("a2", "B", "r", 0.9, {}),
            AgentOutput("a3", "C", "r", 0.9, {})
        ]

        result = strategy.synthesize(outputs, {"max_rounds": 1})

        # Should detect conflict with 3-way split
        assert len(result.conflicts) > 0

    def test_votes_recorded(self):
        """Test that votes are properly recorded."""
        strategy = DebateAndSynthesize()
        outputs = [
            AgentOutput("a1", "A", "r", 0.9, {}),
            AgentOutput("a2", "A", "r", 0.8, {}),
            AgentOutput("a3", "B", "r", 0.7, {})
        ]

        result = strategy.synthesize(outputs, {"max_rounds": 1})

        assert "A" in result.votes
        assert "B" in result.votes
        assert result.votes["A"] == 2
        assert result.votes["B"] == 1

    def test_debate_history_in_metadata(self):
        """Test that debate history is included in result metadata."""
        strategy = DebateAndSynthesize()
        outputs = [
            AgentOutput("a1", "A", "r", 0.9, {}),
            AgentOutput("a2", "A", "r", 0.8, {})
        ]

        result = strategy.synthesize(outputs, {"max_rounds": 2})

        assert "debate_history" in result.metadata
        assert "rounds" in result.metadata["debate_history"]
        assert result.metadata["total_rounds"] == result.metadata["debate_history"]["total_rounds"]


class TestDebateRound:
    """Test DebateRound dataclass."""

    def test_debate_round_creation(self):
        """Test creating a debate round."""
        outputs = [AgentOutput("a1", "A", "r", 0.8, {})]

        round_data = DebateRound(
            round_number=0,
            agent_outputs=outputs,
            convergence_score=0.5,
            new_insights=True,
            metadata={"test": "data"}
        )

        assert round_data.round_number == 0
        assert len(round_data.agent_outputs) == 1
        assert round_data.convergence_score == 0.5
        assert round_data.new_insights is True
        assert round_data.metadata["test"] == "data"

    def test_debate_round_default_metadata(self):
        """Test debate round with default metadata."""
        outputs = [AgentOutput("a1", "A", "r", 0.8, {})]

        round_data = DebateRound(
            round_number=0,
            agent_outputs=outputs,
            convergence_score=0.5,
            new_insights=True
        )

        assert round_data.metadata == {}


class TestDebateHistory:
    """Test DebateHistory dataclass."""

    def test_debate_history_creation(self):
        """Test creating debate history."""
        history = DebateHistory(
            rounds=[],
            total_rounds=3,
            converged=True,
            convergence_round=2,
            metadata={"test": "data"}
        )

        assert history.total_rounds == 3
        assert history.converged is True
        assert history.convergence_round == 2
        assert history.metadata["test"] == "data"

    def test_debate_history_default_metadata(self):
        """Test debate history with default metadata."""
        history = DebateHistory(
            rounds=[],
            total_rounds=1,
            converged=False,
            convergence_round=-1
        )

        assert history.metadata == {}
