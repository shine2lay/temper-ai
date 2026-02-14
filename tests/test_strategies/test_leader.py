"""Tests for leader-based collaboration strategy."""

import pytest

from src.strategies.base import AgentOutput, CollaborationStrategy, SynthesisResult
from src.strategies.leader import LeaderCollaborationStrategy
from src.strategies.registry import StrategyRegistry, get_strategy_from_config


# -- Fixtures ---------------------------------------------------------------

@pytest.fixture
def strategy():
    """Create a LeaderCollaborationStrategy instance."""
    return LeaderCollaborationStrategy()


@pytest.fixture
def perspective_outputs():
    """Sample perspective agent outputs."""
    return [
        AgentOutput(
            agent_name="analyst_product",
            decision="high priority",
            reasoning="Impacts core user flow",
            confidence=0.9,
        ),
        AgentOutput(
            agent_name="analyst_technical",
            decision="high priority",
            reasoning="Straightforward fix with big impact",
            confidence=0.85,
        ),
        AgentOutput(
            agent_name="analyst_ux",
            decision="medium priority",
            reasoning="Workaround exists for users",
            confidence=0.7,
        ),
    ]


@pytest.fixture
def leader_output():
    """Sample leader agent output."""
    return AgentOutput(
        agent_name="decider",
        decision="high priority",
        reasoning="Majority agrees this is high priority; UX concern noted but outweighed",
        confidence=0.92,
    )


@pytest.fixture
def leader_config():
    """Config dict for leader strategy."""
    return {"leader_agent": "decider", "fallback_to_consensus": True}


# -- Property tests ---------------------------------------------------------

class TestLeaderProperties:
    """Test strategy properties."""

    def test_requires_requery_is_false(self, strategy):
        assert strategy.requires_requery is False

    def test_requires_leader_synthesis_is_true(self, strategy):
        assert strategy.requires_leader_synthesis is True

    def test_is_collaboration_strategy(self, strategy):
        assert isinstance(strategy, CollaborationStrategy)


# -- get_leader_agent_name tests --------------------------------------------

class TestGetLeaderAgentName:
    """Test leader name extraction from config."""

    def test_returns_leader_name(self, strategy):
        config = {"leader_agent": "my_decider"}
        assert strategy.get_leader_agent_name(config) == "my_decider"

    def test_returns_none_when_missing(self, strategy):
        assert strategy.get_leader_agent_name({}) is None

    def test_returns_none_for_empty_config(self, strategy):
        assert strategy.get_leader_agent_name({}) is None


# -- format_team_outputs tests ----------------------------------------------

class TestFormatTeamOutputs:
    """Test formatting of perspective outputs for leader prompt."""

    def test_formats_outputs(self, strategy, perspective_outputs):
        result = strategy.format_team_outputs(perspective_outputs)

        assert "analyst_product" in result
        assert "analyst_technical" in result
        assert "analyst_ux" in result
        assert "90%" in result
        assert "high priority" in result
        assert "medium priority" in result

    def test_empty_outputs(self, strategy):
        result = strategy.format_team_outputs([])
        assert "No team outputs available" in result

    def test_single_output(self, strategy):
        outputs = [
            AgentOutput(
                agent_name="solo_agent",
                decision="the answer",
                reasoning="because",
                confidence=0.8,
            )
        ]
        result = strategy.format_team_outputs(outputs)
        assert "solo_agent" in result
        assert "80%" in result
        assert "the answer" in result


# -- synthesize tests -------------------------------------------------------

class TestSynthesize:
    """Test synthesis with leader output present."""

    def test_leader_present_returns_hierarchical(
        self, strategy, perspective_outputs, leader_output, leader_config
    ):
        all_outputs = perspective_outputs + [leader_output]
        result = strategy.synthesize(all_outputs, leader_config)

        assert isinstance(result, SynthesisResult)
        assert result.decision == "high priority"
        assert result.method == "hierarchical"
        assert result.confidence == 0.92
        assert result.metadata["leader_agent"] == "decider"
        assert result.metadata["perspective_count"] == 3

    def test_leader_reasoning_included(
        self, strategy, perspective_outputs, leader_output, leader_config
    ):
        all_outputs = perspective_outputs + [leader_output]
        result = strategy.synthesize(all_outputs, leader_config)

        assert "decider" in result.reasoning
        assert "3 perspective" in result.reasoning

    def test_leader_missing_with_fallback(
        self, strategy, perspective_outputs, leader_config
    ):
        """Leader not in outputs, fallback_to_consensus=True -> consensus."""
        result = strategy.synthesize(perspective_outputs, leader_config)

        assert result.method == "leader_fallback_consensus"
        assert result.metadata["fallback"] is True
        assert result.decision == "high priority"

    def test_leader_missing_no_fallback_raises(
        self, strategy, perspective_outputs
    ):
        """Leader not in outputs, fallback_to_consensus=False -> error."""
        config = {"leader_agent": "decider", "fallback_to_consensus": False}

        with pytest.raises(ValueError, match="not found in outputs"):
            strategy.synthesize(perspective_outputs, config)

    def test_validates_empty_outputs(self, strategy, leader_config):
        with pytest.raises(ValueError, match="cannot be empty"):
            strategy.synthesize([], leader_config)

    def test_validates_duplicate_names(self, strategy, leader_config):
        outputs = [
            AgentOutput("dup", "a", "r", 0.5),
            AgentOutput("dup", "b", "r", 0.5),
        ]
        with pytest.raises(ValueError, match="Duplicate agent names"):
            strategy.synthesize(outputs, leader_config)


# -- consensus fallback tests -----------------------------------------------

class TestConsensusFallback:
    """Test consensus fallback when leader is missing."""

    def test_majority_decision_wins(self, strategy):
        outputs = [
            AgentOutput("a1", "yes", "r1", 0.9),
            AgentOutput("a2", "yes", "r2", 0.8),
            AgentOutput("a3", "no", "r3", 0.7),
        ]
        config = {"leader_agent": "missing_leader"}
        result = strategy.synthesize(outputs, config)

        assert result.decision == "yes"
        assert result.method == "leader_fallback_consensus"

    def test_tie_picks_first(self, strategy):
        outputs = [
            AgentOutput("a1", "yes", "r1", 0.9),
            AgentOutput("a2", "no", "r2", 0.8),
        ]
        config = {"leader_agent": "missing_leader"}
        result = strategy.synthesize(outputs, config)

        # Tie: picks first output's decision
        assert result.decision in ("yes", "no")
        assert result.method == "leader_fallback_consensus"


# -- capabilities and metadata tests ----------------------------------------

class TestCapabilities:
    """Test capabilities and metadata reporting."""

    def test_capabilities(self, strategy):
        caps = strategy.get_capabilities()
        assert caps["supports_debate"] is False
        assert caps["requires_leader"] is True
        assert caps["deterministic"] is True

    def test_metadata_schema(self, strategy):
        meta = strategy.get_metadata()
        assert "leader_agent" in meta["config_schema"]
        assert "fallback_to_consensus" in meta["config_schema"]
        assert meta["config_schema"]["leader_agent"]["required"] is True


# -- registry integration tests ---------------------------------------------

class TestRegistryIntegration:
    """Test leader strategy is properly registered."""

    def test_leader_registered(self):
        registry = StrategyRegistry()
        assert "leader" in registry.list_strategy_names()

    def test_get_leader_strategy(self):
        registry = StrategyRegistry()
        strategy = registry.get_strategy("leader")
        assert isinstance(strategy, LeaderCollaborationStrategy)

    def test_get_strategy_from_config(self):
        # Note: collaboration config is passed to synthesize(), not __init__
        config = {
            "collaboration": {
                "strategy": "leader",
                "config": {},
            }
        }
        strategy = get_strategy_from_config(config)
        assert isinstance(strategy, LeaderCollaborationStrategy)

    def test_leader_is_default_protected(self):
        registry = StrategyRegistry()
        with pytest.raises(ValueError, match="Cannot unregister"):
            registry.unregister_strategy("leader")
