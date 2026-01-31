"""Tests for merit-weighted conflict resolution.

Tests weighted voting based on agent merit scores:
- Equal merit scenarios (equivalent to simple voting)
- High merit disparity (expert vs novice)
- Auto-resolve thresholds
- Escalation thresholds
- Missing merit data handling
- Integration tests
"""

import pytest
from src.strategies.merit_weighted import MeritWeightedResolver, HumanEscalationResolver
from src.strategies.conflict_resolution import AgentMerit, ResolutionContext, Resolution
from src.strategies.base import Conflict, AgentOutput


class TestMeritWeightedResolver:
    """Test suite for MeritWeightedResolver."""

    def test_equal_merit_equal_votes(self):
        """Test with equal merit (equivalent to simple voting)."""
        resolver = MeritWeightedResolver()

        # Two agents, equal merit, different decisions
        merit_a = AgentMerit("a", 0.8, 0.8, 0.8, "intermediate")
        merit_b = AgentMerit("b", 0.8, 0.8, 0.8, "intermediate")

        output_a = AgentOutput("a", "Option A", "reason", 0.9, {})
        output_b = AgentOutput("b", "Option B", "reason", 0.9, {})

        conflict = Conflict(["a", "b"], ["Option A", "Option B"], 0.5, {})
        context = ResolutionContext(
            agent_merits={"a": merit_a, "b": merit_b},
            agent_outputs={"a": output_a, "b": output_b},
            stage_name="test",
            workflow_name="test",
            workflow_config={},
            previous_resolutions=[]
        )

        resolution = resolver.resolve_with_context(conflict, context)

        # Should pick one (tie-break by implementation detail)
        assert resolution.decision in ["Option A", "Option B"]
        assert 0.3 < resolution.confidence < 0.45  # Close vote, low confidence

    def test_high_merit_disparity(self):
        """Test with expert vs novice (merit matters)."""
        resolver = MeritWeightedResolver()

        # Expert (0.9 merit) vs Novice (0.6 merit)
        merit_expert = AgentMerit("expert", 0.9, 0.85, 0.9, "expert")
        merit_novice = AgentMerit("novice", 0.6, 0.65, 0.6, "novice")

        output_expert = AgentOutput("expert", "Option A", "reason", 0.9, {})
        output_novice = AgentOutput("novice", "Option B", "reason", 0.8, {})

        conflict = Conflict(["expert", "novice"], ["Option A", "Option B"], 0.5, {})
        context = ResolutionContext(
            agent_merits={"expert": merit_expert, "novice": merit_novice},
            agent_outputs={"expert": output_expert, "novice": output_novice},
            stage_name="test",
            workflow_name="test",
            workflow_config={},
            previous_resolutions=[]
        )

        resolution = resolver.resolve_with_context(conflict, context)

        # Expert should win
        assert resolution.decision == "Option A"
        assert resolution.confidence > 0.35  # Expert's higher merit (normalized)

    def test_auto_resolve_threshold(self):
        """Test auto-resolve when confidence high."""
        resolver = MeritWeightedResolver({"auto_resolve_threshold": 0.8})  # Lower threshold

        # 3 high-merit agents agree (merit 0.9 * confidence 0.95 = 0.855 per agent)
        merit = AgentMerit("a", 0.95, 0.95, 0.95, "expert")

        outputs = {
            f"a{i}": AgentOutput(f"a{i}", "Option A", "reason", 0.95, {})
            for i in range(3)
        }

        conflict = Conflict(list(outputs.keys()), ["Option A"], 0.0, {})
        context = ResolutionContext(
            agent_merits={k: merit for k in outputs.keys()},
            agent_outputs=outputs,
            stage_name="test",
            workflow_name="test",
            workflow_config={},
            previous_resolutions=[]
        )

        resolution = resolver.resolve_with_context(conflict, context)

        assert resolution.method == "merit_weighted_auto"
        assert resolution.metadata["auto_resolved"] is True
        assert resolution.confidence >= 0.8

    def test_escalation_threshold(self):
        """Test escalation when confidence low."""
        resolver = MeritWeightedResolver({"escalation_threshold": 0.5})

        # 3 agents, all disagree, low confidence
        merits = {
            f"a{i}": AgentMerit(f"a{i}", 0.5, 0.5, 0.5, "novice")
            for i in range(3)
        }

        outputs = {
            "a0": AgentOutput("a0", "Option A", "reason", 0.6, {}),
            "a1": AgentOutput("a1", "Option B", "reason", 0.6, {}),
            "a2": AgentOutput("a2", "Option C", "reason", 0.6, {})
        }

        conflict = Conflict(list(outputs.keys()), ["Option A", "Option B", "Option C"], 0.8, {})
        context = ResolutionContext(
            agent_merits=merits,
            agent_outputs=outputs,
            stage_name="test",
            workflow_name="test",
            workflow_config={},
            previous_resolutions=[]
        )

        resolution = resolver.resolve_with_context(conflict, context)

        assert resolution.confidence < 0.5
        assert resolution.metadata["needs_review"] is True

    def test_missing_merit_handling(self):
        """Test graceful handling of missing merit data."""
        resolver = MeritWeightedResolver()

        # One agent missing merit - should use default (0.5)
        merit_a = AgentMerit("a", 0.8, 0.8, 0.8, "intermediate")

        output_a = AgentOutput("a", "Option A", "reason", 0.9, {})
        output_b = AgentOutput("b", "Option B", "reason", 0.9, {})

        conflict = Conflict(["a", "b"], ["Option A", "Option B"], 0.5, {})
        context = ResolutionContext(
            agent_merits={"a": merit_a},  # Missing "b"
            agent_outputs={"a": output_a, "b": output_b},
            stage_name="test",
            workflow_name="test",
            workflow_config={},
            previous_resolutions=[]
        )

        # Should handle gracefully (use default merit for agent b)
        resolution = resolver.resolve_with_context(conflict, context)
        assert resolution.decision in ["Option A", "Option B"]

    def test_human_escalation_resolver(self):
        """Test human escalation resolver."""
        resolver = HumanEscalationResolver()

        conflict = Conflict(["a", "b"], ["Option A", "Option B"], 0.8, {})
        context = ResolutionContext(
            agent_merits={},
            agent_outputs={},
            stage_name="test",
            workflow_name="test",
            workflow_config={},
            previous_resolutions=[]
        )

        # Should raise RuntimeError
        with pytest.raises(RuntimeError, match="Human escalation required"):
            resolver.resolve_with_context(conflict, context)

    def test_capabilities(self):
        """Test resolver capabilities."""
        resolver = MeritWeightedResolver()
        caps = resolver.get_capabilities()

        assert caps["requires_merit"] is True
        assert caps["requires_human"] is False
        assert caps["deterministic"] is True
        assert caps["supports_merit_weighting"] is True

    def test_metadata(self):
        """Test resolver metadata."""
        resolver = MeritWeightedResolver()
        metadata = resolver.get_metadata()

        assert "config_schema" in metadata
        assert "auto_resolve_threshold" in metadata["config_schema"]
        assert metadata["config_schema"]["auto_resolve_threshold"]["default"] == 0.85

    def test_backward_compatible_resolve(self):
        """Test backward-compatible resolve method (old API)."""
        resolver = MeritWeightedResolver()

        outputs = [
            AgentOutput("a1", "yes", "r1", 0.9, {}),
            AgentOutput("a2", "no", "r2", 0.8, {})
        ]

        conflict = Conflict(["a1", "a2"], ["yes", "no"], 1.0, {})

        result = resolver.resolve(conflict, outputs, {})

        # Should return ResolutionResult
        assert hasattr(result, "decision")
        assert hasattr(result, "success")
        assert hasattr(result, "confidence")
        assert result.decision in ["yes", "no"]

    def test_merit_weighted_three_way_split(self):
        """Test resolution with three-way disagreement."""
        resolver = MeritWeightedResolver()

        # Three agents with different merits
        merit_high = AgentMerit("high", 0.9, 0.9, 0.9, "expert")
        merit_med = AgentMerit("med", 0.7, 0.7, 0.7, "intermediate")
        merit_low = AgentMerit("low", 0.5, 0.5, 0.5, "novice")

        outputs = {
            "high": AgentOutput("high", "Option A", "reason", 0.9, {}),
            "med": AgentOutput("med", "Option B", "reason", 0.8, {}),
            "low": AgentOutput("low", "Option C", "reason", 0.7, {})
        }

        conflict = Conflict(list(outputs.keys()), ["Option A", "Option B", "Option C"], 0.7, {})
        context = ResolutionContext(
            agent_merits={"high": merit_high, "med": merit_med, "low": merit_low},
            agent_outputs=outputs,
            stage_name="test",
            workflow_name="test",
            workflow_config={},
            previous_resolutions=[]
        )

        resolution = resolver.resolve_with_context(conflict, context)

        # High merit agent should win
        assert resolution.decision == "Option A"
        assert "high" in resolution.winning_agents

    def test_merit_weights_configuration(self):
        """Test custom merit weights configuration."""
        # Favor recent performance heavily
        custom_weights = {
            "domain_merit": 0.2,
            "overall_merit": 0.2,
            "recent_performance": 0.6
        }
        resolver = MeritWeightedResolver({"merit_weights": custom_weights})

        # Agent with high recent performance
        merit_recent = AgentMerit("recent", 0.6, 0.6, 0.95, "intermediate")
        # Agent with high domain merit but low recent
        merit_domain = AgentMerit("domain", 0.95, 0.8, 0.6, "expert")

        outputs = {
            "recent": AgentOutput("recent", "Option A", "reason", 0.9, {}),
            "domain": AgentOutput("domain", "Option B", "reason", 0.9, {})
        }

        conflict = Conflict(list(outputs.keys()), ["Option A", "Option B"], 0.5, {})
        context = ResolutionContext(
            agent_merits={"recent": merit_recent, "domain": merit_domain},
            agent_outputs=outputs,
            stage_name="test",
            workflow_name="test",
            workflow_config={},
            previous_resolutions=[]
        )

        resolution = resolver.resolve_with_context(conflict, context)

        # Recent performance agent should win with these weights
        assert resolution.decision == "Option A"

    def test_reasoning_includes_merit_info(self):
        """Test that reasoning includes merit information."""
        resolver = MeritWeightedResolver()

        merit_a = AgentMerit("a", 0.9, 0.85, 0.9, "expert")
        merit_b = AgentMerit("b", 0.6, 0.65, 0.6, "novice")

        outputs = {
            "a": AgentOutput("a", "Option A", "reason", 0.9, {}),
            "b": AgentOutput("b", "Option B", "reason", 0.8, {})
        }

        conflict = Conflict(list(outputs.keys()), ["Option A", "Option B"], 0.5, {})
        context = ResolutionContext(
            agent_merits={"a": merit_a, "b": merit_b},
            agent_outputs=outputs,
            stage_name="test",
            workflow_name="test",
            workflow_config={},
            previous_resolutions=[]
        )

        resolution = resolver.resolve_with_context(conflict, context)

        # Reasoning should mention merit
        assert "merit" in resolution.reasoning.lower()
        assert "a" in resolution.reasoning

    def test_confidence_calculation(self):
        """Test confidence calculation is reasonable."""
        resolver = MeritWeightedResolver()

        # Two agents agree, high merit
        merit = AgentMerit("a", 0.9, 0.9, 0.9, "expert")

        outputs = {
            "a0": AgentOutput("a0", "Option A", "reason", 0.9, {}),
            "a1": AgentOutput("a1", "Option A", "reason", 0.85, {})
        }

        conflict = Conflict(list(outputs.keys()), ["Option A"], 0.0, {})
        context = ResolutionContext(
            agent_merits={k: merit for k in outputs.keys()},
            agent_outputs=outputs,
            stage_name="test",
            workflow_name="test",
            workflow_config={},
            previous_resolutions=[]
        )

        resolution = resolver.resolve_with_context(conflict, context)

        # High agreement + high merit should give high confidence
        assert resolution.confidence > 0.7
        assert resolution.confidence <= 1.0

    def test_missing_agent_merits_raises_error(self):
        """Test that missing agent_merits raises ValueError."""
        resolver = MeritWeightedResolver()

        outputs = {
            "a": AgentOutput("a", "Option A", "reason", 0.9, {})
        }

        conflict = Conflict(["a"], ["Option A"], 0.0, {})
        context = ResolutionContext(
            agent_merits={},  # Empty - should raise error
            agent_outputs=outputs,
            stage_name="test",
            workflow_name="test",
            workflow_config={},
            previous_resolutions=[]
        )

        with pytest.raises(ValueError, match="Context must have agent merits"):
            resolver.resolve_with_context(conflict, context)


class TestAgentMerit:
    """Test suite for AgentMerit dataclass."""

    def test_agent_merit_creation(self):
        """Test creating an AgentMerit instance."""
        merit = AgentMerit("agent1", 0.9, 0.85, 0.9, "expert")

        assert merit.agent_name == "agent1"
        assert merit.domain_merit == 0.9
        assert merit.overall_merit == 0.85
        assert merit.recent_performance == 0.9
        assert merit.expertise_level == "expert"

    def test_agent_merit_validation(self):
        """Test AgentMerit validates score ranges."""
        # Out of range domain_merit
        with pytest.raises(ValueError, match="domain_merit must be between 0 and 1"):
            AgentMerit("a", 1.5, 0.8, 0.8, "expert")

        # Out of range overall_merit
        with pytest.raises(ValueError, match="overall_merit must be between 0 and 1"):
            AgentMerit("a", 0.8, -0.1, 0.8, "expert")

        # Out of range recent_performance
        with pytest.raises(ValueError, match="recent_performance must be between 0 and 1"):
            AgentMerit("a", 0.8, 0.8, 2.0, "expert")

    def test_calculate_weight_default(self):
        """Test calculate_weight with default weights."""
        merit = AgentMerit("a", 0.9, 0.8, 0.85, "expert")

        # Default weights: domain 0.4, overall 0.3, recent 0.3
        weight = merit.calculate_weight({})

        expected = 0.9 * 0.4 + 0.8 * 0.3 + 0.85 * 0.3
        assert abs(weight - expected) < 0.001

    def test_calculate_weight_custom(self):
        """Test calculate_weight with custom weights."""
        merit = AgentMerit("a", 0.9, 0.8, 0.85, "expert")

        custom_weights = {
            "domain_merit": 0.5,
            "overall_merit": 0.3,
            "recent_performance": 0.2
        }

        weight = merit.calculate_weight(custom_weights)

        expected = 0.9 * 0.5 + 0.8 * 0.3 + 0.85 * 0.2
        assert abs(weight - expected) < 0.001


class TestResolutionContext:
    """Test suite for ResolutionContext dataclass."""

    def test_resolution_context_creation(self):
        """Test creating a ResolutionContext."""
        merit = AgentMerit("a", 0.9, 0.85, 0.9, "expert")
        output = AgentOutput("a", "yes", "reason", 0.9, {})

        context = ResolutionContext(
            agent_merits={"a": merit},
            agent_outputs={"a": output},
            stage_name="research",
            workflow_name="mvp",
            workflow_config={"timeout": 30},
            previous_resolutions=[]
        )

        assert "a" in context.agent_merits
        assert "a" in context.agent_outputs
        assert context.stage_name == "research"
        assert context.workflow_name == "mvp"
        assert context.workflow_config["timeout"] == 30


class TestResolution:
    """Test suite for Resolution dataclass."""

    def test_resolution_creation(self):
        """Test creating a Resolution."""
        resolution = Resolution(
            decision="Option A",
            reasoning="Expert chose A",
            confidence=0.88,
            method="merit_weighted_auto",
            winning_agents=["expert"],
            metadata={"scores": {"A": 0.9}}
        )

        assert resolution.decision == "Option A"
        assert resolution.confidence == 0.88
        assert resolution.method == "merit_weighted_auto"
        assert "expert" in resolution.winning_agents

    def test_resolution_confidence_validation(self):
        """Test Resolution validates confidence range."""
        # Out of range confidence
        with pytest.raises(ValueError, match="Confidence must be between 0 and 1"):
            Resolution(
                decision="A",
                reasoning="reason",
                confidence=1.5,
                method="test",
                winning_agents=[]
            )


class TestHumanEscalationResolver:
    """Test suite for HumanEscalationResolver."""

    def test_escalation_raises_error(self):
        """Test that escalation always raises RuntimeError."""
        resolver = HumanEscalationResolver()

        conflict = Conflict(["a", "b"], ["yes", "no"], 0.9, {})
        context = ResolutionContext(
            agent_merits={},
            agent_outputs={},
            stage_name="test",
            workflow_name="test",
            workflow_config={},
            previous_resolutions=[]
        )

        with pytest.raises(RuntimeError) as exc_info:
            resolver.resolve_with_context(conflict, context)

        error_msg = str(exc_info.value)
        assert "Human escalation required" in error_msg
        assert "a" in error_msg  # Agent names
        assert "yes" in error_msg  # Decision options

    def test_escalation_capabilities(self):
        """Test escalation resolver capabilities."""
        resolver = HumanEscalationResolver()
        caps = resolver.get_capabilities()

        assert caps["requires_human"] is True
        assert caps["requires_merit"] is False
        assert caps["supports_escalation"] is True

    def test_backward_compatible_resolve(self):
        """Test backward-compatible resolve for escalation."""
        resolver = HumanEscalationResolver()

        conflict = Conflict(["a"], ["yes"], 0.5, {})
        outputs = [AgentOutput("a", "yes", "reason", 0.8, {})]

        with pytest.raises(RuntimeError):
            resolver.resolve(conflict, outputs, {})
