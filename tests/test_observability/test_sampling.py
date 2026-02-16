"""Tests for observability sampling strategies."""
import pytest

from src.observability.sampling import (
    AlwaysSample,
    CompositeSampler,
    NeverSample,
    RateSample,
    RuleBasedSample,
    SamplingContext,
    SamplingDecision,
    SamplingStrategy,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def default_context() -> SamplingContext:
    """A minimal sampling context for general tests."""
    return SamplingContext(
        workflow_id="wf-1",
        workflow_name="test_workflow",
        environment="staging",
        tags=["debug", "test"],
    )


# ---------------------------------------------------------------------------
# SamplingContext defaults
# ---------------------------------------------------------------------------

class TestSamplingContext:
    def test_defaults(self) -> None:
        ctx = SamplingContext()
        assert ctx.workflow_id == ""
        assert ctx.workflow_name == ""
        assert ctx.environment == ""
        assert ctx.tags == []
        assert ctx.metadata == {}

    def test_custom_values(self) -> None:
        ctx = SamplingContext(
            workflow_id="abc",
            workflow_name="my_wf",
            environment="prod",
            tags=["a"],
            metadata={"k": "v"},
        )
        assert ctx.workflow_id == "abc"
        assert ctx.metadata == {"k": "v"}


# ---------------------------------------------------------------------------
# SamplingDecision
# ---------------------------------------------------------------------------

class TestSamplingDecision:
    def test_fields(self) -> None:
        d = SamplingDecision(sampled=True, reason="test", strategy_name="s")
        assert d.sampled is True
        assert d.reason == "test"
        assert d.strategy_name == "s"


# ---------------------------------------------------------------------------
# AlwaysSample
# ---------------------------------------------------------------------------

class TestAlwaysSample:
    def test_always_returns_true(self, default_context: SamplingContext) -> None:
        strategy = AlwaysSample()
        decision = strategy.should_sample(default_context)
        assert decision.sampled is True
        assert decision.strategy_name == "always"

    def test_name(self) -> None:
        assert AlwaysSample().name == "always"


# ---------------------------------------------------------------------------
# NeverSample
# ---------------------------------------------------------------------------

class TestNeverSample:
    def test_always_returns_false(self, default_context: SamplingContext) -> None:
        strategy = NeverSample()
        decision = strategy.should_sample(default_context)
        assert decision.sampled is False
        assert decision.strategy_name == "never"

    def test_name(self) -> None:
        assert NeverSample().name == "never"


# ---------------------------------------------------------------------------
# RateSample
# ---------------------------------------------------------------------------

class TestRateSample:
    def test_rate_1_always_samples(self, default_context: SamplingContext) -> None:
        strategy = RateSample(rate=1.0)
        # random.random() is always < 1.0, so rate=1.0 always samples
        decision = strategy.should_sample(default_context)
        assert decision.sampled is True

    def test_rate_0_never_samples(self, default_context: SamplingContext) -> None:
        strategy = RateSample(rate=0.0)
        # random.random() is always >= 0.0, so rate=0.0 never samples
        decision = strategy.should_sample(default_context)
        assert decision.sampled is False

    def test_name_includes_rate(self) -> None:
        strategy = RateSample(rate=0.5)
        assert strategy.name == "rate(0.5)"

    def test_invalid_rate_negative(self) -> None:
        with pytest.raises(ValueError, match="between 0.0 and 1.0"):
            RateSample(rate=-0.1)

    def test_invalid_rate_above_one(self) -> None:
        with pytest.raises(ValueError, match="between 0.0 and 1.0"):
            RateSample(rate=1.1)

    def test_boundary_rates_valid(self) -> None:
        # 0.0 and 1.0 should not raise
        RateSample(rate=0.0)
        RateSample(rate=1.0)
        assert True  # Reached without error


# ---------------------------------------------------------------------------
# RuleBasedSample
# ---------------------------------------------------------------------------

class TestRuleBasedSample:
    def test_name_pattern_matches(self) -> None:
        strategy = RuleBasedSample(name_patterns=[r"^test_"])
        ctx = SamplingContext(workflow_name="test_workflow")
        decision = strategy.should_sample(ctx)
        assert decision.sampled is True
        assert "name matched" in decision.reason

    def test_name_pattern_no_match_uses_default(self) -> None:
        strategy = RuleBasedSample(
            name_patterns=[r"^production_"],
            default_sampled=True,
        )
        ctx = SamplingContext(workflow_name="test_workflow")
        decision = strategy.should_sample(ctx)
        assert decision.sampled is True
        assert "no rule matched" in decision.reason

    def test_tag_whitelist_matches(self) -> None:
        strategy = RuleBasedSample(tag_whitelist=["debug", "critical"])
        ctx = SamplingContext(tags=["debug", "other"])
        decision = strategy.should_sample(ctx)
        assert decision.sampled is True
        assert "tag matched" in decision.reason

    def test_tag_whitelist_no_match(self) -> None:
        strategy = RuleBasedSample(
            tag_whitelist=["critical"],
            default_sampled=False,
        )
        ctx = SamplingContext(tags=["debug"])
        decision = strategy.should_sample(ctx)
        assert decision.sampled is False

    def test_environment_whitelist_matches(self) -> None:
        strategy = RuleBasedSample(environment_whitelist=["production", "staging"])
        ctx = SamplingContext(environment="production")
        decision = strategy.should_sample(ctx)
        assert decision.sampled is True
        assert "environment" in decision.reason

    def test_environment_whitelist_no_match(self) -> None:
        strategy = RuleBasedSample(
            environment_whitelist=["production"],
            default_sampled=False,
        )
        ctx = SamplingContext(environment="dev")
        decision = strategy.should_sample(ctx)
        assert decision.sampled is False

    def test_no_rules_returns_default_false(self) -> None:
        strategy = RuleBasedSample(default_sampled=False)
        ctx = SamplingContext(workflow_name="anything")
        decision = strategy.should_sample(ctx)
        assert decision.sampled is False
        assert "no rule matched" in decision.reason

    def test_name_pattern_has_priority_over_tags(self) -> None:
        """Name patterns are checked first; if matched, tags are skipped."""
        strategy = RuleBasedSample(
            name_patterns=[r"^important"],
            tag_whitelist=["debug"],
        )
        ctx = SamplingContext(
            workflow_name="important_job",
            tags=["debug"],
        )
        decision = strategy.should_sample(ctx)
        assert decision.sampled is True
        assert "name matched" in decision.reason

    def test_name(self) -> None:
        assert RuleBasedSample().name == "rule_based"


# ---------------------------------------------------------------------------
# CompositeSampler
# ---------------------------------------------------------------------------

class TestCompositeSampler:
    def test_or_logic_one_yes(self, default_context: SamplingContext) -> None:
        strategies = [NeverSample(), AlwaysSample()]
        composite = CompositeSampler(strategies=strategies)
        decision = composite.should_sample(default_context)
        assert decision.sampled is True
        assert "matched by always" in decision.reason

    def test_all_no_means_not_sampled(self, default_context: SamplingContext) -> None:
        strategies = [NeverSample(), NeverSample()]
        composite = CompositeSampler(strategies=strategies)
        decision = composite.should_sample(default_context)
        assert decision.sampled is False
        assert "no strategy approved" in decision.reason

    def test_empty_strategies_not_sampled(
        self, default_context: SamplingContext
    ) -> None:
        composite = CompositeSampler(strategies=[])
        decision = composite.should_sample(default_context)
        assert decision.sampled is False

    def test_name(self) -> None:
        assert CompositeSampler(strategies=[]).name == "composite"


# ---------------------------------------------------------------------------
# Protocol compliance
# ---------------------------------------------------------------------------

class TestProtocolCompliance:
    def test_always_sample_is_strategy(self) -> None:
        assert isinstance(AlwaysSample(), SamplingStrategy)

    def test_never_sample_is_strategy(self) -> None:
        assert isinstance(NeverSample(), SamplingStrategy)

    def test_rate_sample_is_strategy(self) -> None:
        assert isinstance(RateSample(rate=0.5), SamplingStrategy)

    def test_rule_based_is_strategy(self) -> None:
        assert isinstance(RuleBasedSample(), SamplingStrategy)

    def test_composite_is_strategy(self) -> None:
        assert isinstance(CompositeSampler(strategies=[]), SamplingStrategy)
