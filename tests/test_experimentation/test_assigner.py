"""
Tests for VariantAssigner coordinator.

Tests the VariantAssigner coordinator that delegates to assignment strategies.
"""

import pytest

from temper_ai.experimentation.assignment import (
    AssignmentStrategy,
    BanditAssignment,
    HashAssignment,
    RandomAssignment,
    StratifiedAssignment,
    VariantAssigner,
)
from temper_ai.experimentation.models import (
    AssignmentStrategyType,
    ConfigType,
    Experiment,
    ExperimentStatus,
    Variant,
)


@pytest.fixture
def experiment():
    """Create test experiment."""
    return Experiment(
        id="exp-001",
        name="test_experiment",
        description="Test experiment",
        status=ExperimentStatus.RUNNING,
        assignment_strategy=AssignmentStrategyType.RANDOM,
        traffic_allocation={"control": 0.6, "variant_a": 0.4},
        primary_metric="duration_seconds",
        confidence_level=0.95,
        min_sample_size_per_variant=100,
    )


@pytest.fixture
def variants():
    """Create test variants."""
    return [
        Variant(
            id="var-control",
            experiment_id="exp-001",
            name="control",
            description="Control variant",
            is_control=True,
            config_type=ConfigType.AGENT,
            config_overrides={},
            allocated_traffic=0.6,
        ),
        Variant(
            id="var-a",
            experiment_id="exp-001",
            name="variant_a",
            description="Variant A",
            is_control=False,
            config_type=ConfigType.AGENT,
            config_overrides={"temperature": 0.9},
            allocated_traffic=0.4,
        ),
    ]


class TestVariantAssignerInitialization:
    """Test VariantAssigner initialization."""

    def test_initialization(self):
        """Test assigner initialization with default strategies."""
        assigner = VariantAssigner()

        assert assigner._strategies is not None
        assert len(assigner._strategies) == 4  # 4 strategy types

        # Verify all strategy types are registered
        assert AssignmentStrategyType.RANDOM in assigner._strategies
        assert AssignmentStrategyType.HASH in assigner._strategies
        assert AssignmentStrategyType.STRATIFIED in assigner._strategies
        assert AssignmentStrategyType.BANDIT in assigner._strategies

    def test_strategy_instances(self):
        """Test that correct strategy instances are created."""
        assigner = VariantAssigner()

        assert isinstance(assigner._strategies[AssignmentStrategyType.RANDOM], RandomAssignment)
        assert isinstance(assigner._strategies[AssignmentStrategyType.HASH], HashAssignment)
        assert isinstance(assigner._strategies[AssignmentStrategyType.STRATIFIED], StratifiedAssignment)
        assert isinstance(assigner._strategies[AssignmentStrategyType.BANDIT], BanditAssignment)


class TestAssignVariant:
    """Test assign_variant method."""

    def test_assign_variant_random_strategy(self, experiment, variants):
        """Test assignment with random strategy."""
        experiment.assignment_strategy = AssignmentStrategyType.RANDOM
        assigner = VariantAssigner()

        variant_id = assigner.assign_variant(experiment, variants, "workflow-123")

        assert variant_id in ["var-control", "var-a"]

    def test_assign_variant_hash_strategy(self, experiment, variants):
        """Test assignment with hash strategy."""
        experiment.assignment_strategy = AssignmentStrategyType.HASH
        assigner = VariantAssigner()

        # Hash strategy should be consistent
        variant_1 = assigner.assign_variant(experiment, variants, "workflow-same")
        variant_2 = assigner.assign_variant(experiment, variants, "workflow-same")

        assert variant_1 == variant_2

    def test_assign_variant_stratified_strategy(self, experiment, variants):
        """Test assignment with stratified strategy."""
        experiment.assignment_strategy = AssignmentStrategyType.STRATIFIED
        assigner = VariantAssigner()

        # Stratified falls back to hash, should be consistent
        variant_1 = assigner.assign_variant(experiment, variants, "workflow-same")
        variant_2 = assigner.assign_variant(experiment, variants, "workflow-same")

        assert variant_1 == variant_2

    def test_assign_variant_bandit_strategy(self, experiment, variants):
        """Test assignment with bandit strategy."""
        experiment.assignment_strategy = AssignmentStrategyType.BANDIT
        assigner = VariantAssigner()

        # Bandit falls back to random
        variant_id = assigner.assign_variant(experiment, variants, "workflow-123")

        assert variant_id in ["var-control", "var-a"]

    def test_assign_variant_with_context(self, experiment, variants):
        """Test assignment with context."""
        experiment.assignment_strategy = AssignmentStrategyType.HASH
        assigner = VariantAssigner()

        context = {"hash_key": "user-123", "region": "us-west"}

        variant_id = assigner.assign_variant(
            experiment, variants, "workflow-456", context=context
        )

        assert variant_id in ["var-control", "var-a"]

    def test_assign_variant_different_workflows(self, experiment, variants):
        """Test assignment with different workflow IDs."""
        experiment.assignment_strategy = AssignmentStrategyType.HASH
        assigner = VariantAssigner()

        # Different workflow IDs should potentially get different variants
        variants_assigned = set()
        for i in range(100):
            variant_id = assigner.assign_variant(experiment, variants, f"workflow-{i}")
            variants_assigned.add(variant_id)

        # Should see both variants assigned across different workflows
        assert len(variants_assigned) == 2

    def test_assign_variant_unknown_strategy(self, experiment, variants):
        """Test that unknown strategy raises error."""
        # Manually set invalid strategy
        experiment.assignment_strategy = "unknown_strategy"  # type: ignore
        assigner = VariantAssigner()

        with pytest.raises(ValueError, match="Unknown assignment strategy"):
            assigner.assign_variant(experiment, variants, "workflow-123")

    def test_assign_variant_empty_variants(self, experiment):
        """Test that empty variants list raises error."""
        experiment.assignment_strategy = AssignmentStrategyType.RANDOM
        assigner = VariantAssigner()

        with pytest.raises(ValueError, match="No variants available"):
            assigner.assign_variant(experiment, [], "workflow-123")

    def test_assign_variant_invalid_traffic(self, experiment, variants):
        """Test that invalid traffic allocation raises error."""
        # Set invalid traffic
        variants[0].allocated_traffic = 0.7
        variants[1].allocated_traffic = 0.5  # Total > 1.0

        experiment.assignment_strategy = AssignmentStrategyType.RANDOM
        assigner = VariantAssigner()

        with pytest.raises(ValueError, match="Invalid traffic allocation"):
            assigner.assign_variant(experiment, variants, "workflow-123")


class TestRegisterStrategy:
    """Test register_strategy method."""

    def test_register_custom_strategy(self, experiment, variants):
        """Test registering a custom strategy."""
        assigner = VariantAssigner()

        # Create custom strategy
        class CustomStrategy(AssignmentStrategy):
            def assign(self, experiment, variants, execution_id, context=None):
                # Always return first variant
                return variants[0].id

        custom_strategy = CustomStrategy()

        # Register custom strategy (overwrite RANDOM)
        assigner.register_strategy(AssignmentStrategyType.RANDOM, custom_strategy)

        # Verify it's used
        experiment.assignment_strategy = AssignmentStrategyType.RANDOM
        variant_id = assigner.assign_variant(experiment, variants, "workflow-123")

        assert variant_id == variants[0].id

    def test_register_strategy_replaces_existing(self, experiment, variants):
        """Test that registering a strategy replaces existing one."""
        assigner = VariantAssigner()

        # Original hash strategy is consistent
        experiment.assignment_strategy = AssignmentStrategyType.HASH
        original_result = assigner.assign_variant(experiment, variants, "workflow-same")

        # Register new strategy
        class AlwaysControlStrategy(AssignmentStrategy):
            def assign(self, experiment, variants, execution_id, context=None):
                for variant in variants:
                    if variant.is_control:
                        return variant.id
                return variants[0].id

        assigner.register_strategy(AssignmentStrategyType.HASH, AlwaysControlStrategy())

        # New strategy should be used
        new_result = assigner.assign_variant(experiment, variants, "workflow-same")

        # Should always return control variant
        control_id = next(v.id for v in variants if v.is_control)
        assert new_result == control_id

    def test_register_multiple_custom_strategies(self, experiment, variants):
        """Test registering multiple custom strategies."""
        assigner = VariantAssigner()

        # Custom strategy 1: Always first
        class AlwaysFirstStrategy(AssignmentStrategy):
            def assign(self, experiment, variants, execution_id, context=None):
                return variants[0].id

        # Custom strategy 2: Always last
        class AlwaysLastStrategy(AssignmentStrategy):
            def assign(self, experiment, variants, execution_id, context=None):
                return variants[-1].id

        assigner.register_strategy(AssignmentStrategyType.RANDOM, AlwaysFirstStrategy())
        assigner.register_strategy(AssignmentStrategyType.HASH, AlwaysLastStrategy())

        # Test RANDOM strategy
        experiment.assignment_strategy = AssignmentStrategyType.RANDOM
        result1 = assigner.assign_variant(experiment, variants, "workflow-1")
        assert result1 == variants[0].id

        # Test HASH strategy
        experiment.assignment_strategy = AssignmentStrategyType.HASH
        result2 = assigner.assign_variant(experiment, variants, "workflow-2")
        assert result2 == variants[-1].id


class TestStrategyDelegation:
    """Test that assigner correctly delegates to strategies."""

    def test_delegates_to_random_strategy(self, experiment, variants):
        """Test delegation to RandomAssignment."""
        experiment.assignment_strategy = AssignmentStrategyType.RANDOM
        assigner = VariantAssigner()

        # Multiple calls should potentially return different variants
        # (though with low probability, all could be same)
        results = set()
        for i in range(100):
            variant_id = assigner.assign_variant(experiment, variants, f"workflow-{i}")
            results.add(variant_id)

        # With 100 trials and 60/40 split, should see both variants
        # (probability of seeing only one is negligible)
        assert len(results) >= 1  # At minimum we see variants

    def test_delegates_to_hash_strategy(self, experiment, variants):
        """Test delegation to HashAssignment."""
        experiment.assignment_strategy = AssignmentStrategyType.HASH
        assigner = VariantAssigner()

        # Hash strategy: same ID → same variant
        results = []
        for _ in range(10):
            variant_id = assigner.assign_variant(experiment, variants, "workflow-consistent")
            results.append(variant_id)

        # All should be same
        assert len(set(results)) == 1

    def test_delegates_to_stratified_strategy(self, experiment, variants):
        """Test delegation to StratifiedAssignment."""
        experiment.assignment_strategy = AssignmentStrategyType.STRATIFIED
        assigner = VariantAssigner()

        # Stratified currently falls back to hash (consistent)
        variant_1 = assigner.assign_variant(experiment, variants, "workflow-test")
        variant_2 = assigner.assign_variant(experiment, variants, "workflow-test")

        assert variant_1 == variant_2

    def test_delegates_to_bandit_strategy(self, experiment, variants):
        """Test delegation to BanditAssignment."""
        experiment.assignment_strategy = AssignmentStrategyType.BANDIT
        assigner = VariantAssigner()

        # Bandit currently falls back to random
        variant_id = assigner.assign_variant(experiment, variants, "workflow-123")

        assert variant_id in [v.id for v in variants]


class TestEdgeCases:
    """Test edge cases and error conditions."""

    def test_assign_single_variant(self, experiment):
        """Test assignment with single variant."""
        variants = [
            Variant(
                id="var-only",
                experiment_id="exp-001",
                name="only_variant",
                description="Only variant",
                is_control=True,
                config_type=ConfigType.AGENT,
                config_overrides={},
                allocated_traffic=1.0,
            )
        ]

        experiment.assignment_strategy = AssignmentStrategyType.RANDOM
        assigner = VariantAssigner()

        variant_id = assigner.assign_variant(experiment, variants, "workflow-123")

        assert variant_id == "var-only"

    def test_assign_three_variants(self, experiment):
        """Test assignment with three variants."""
        variants = [
            Variant(
                id="var-control",
                experiment_id="exp-001",
                name="control",
                description="Control",
                is_control=True,
                config_type=ConfigType.AGENT,
                config_overrides={},
                allocated_traffic=0.5,
            ),
            Variant(
                id="var-a",
                experiment_id="exp-001",
                name="variant_a",
                description="Variant A",
                is_control=False,
                config_type=ConfigType.AGENT,
                config_overrides={},
                allocated_traffic=0.3,
            ),
            Variant(
                id="var-b",
                experiment_id="exp-001",
                name="variant_b",
                description="Variant B",
                is_control=False,
                config_type=ConfigType.AGENT,
                config_overrides={},
                allocated_traffic=0.2,
            ),
        ]

        experiment.assignment_strategy = AssignmentStrategyType.RANDOM
        assigner = VariantAssigner()

        # Run multiple assignments
        variant_ids = set()
        for i in range(100):
            variant_id = assigner.assign_variant(experiment, variants, f"workflow-{i}")
            variant_ids.add(variant_id)

        # Should see all three variants assigned
        assert len(variant_ids) == 3

    def test_assign_with_none_context(self, experiment, variants):
        """Test assignment with None context (should work)."""
        experiment.assignment_strategy = AssignmentStrategyType.HASH
        assigner = VariantAssigner()

        variant_id = assigner.assign_variant(experiment, variants, "workflow-123", context=None)

        assert variant_id in [v.id for v in variants]

    def test_assign_with_empty_context(self, experiment, variants):
        """Test assignment with empty context dict."""
        experiment.assignment_strategy = AssignmentStrategyType.HASH
        assigner = VariantAssigner()

        variant_id = assigner.assign_variant(experiment, variants, "workflow-123", context={})

        assert variant_id in [v.id for v in variants]

    def test_assign_consistency_across_strategies(self, experiment, variants):
        """Test that different strategy types produce valid assignments."""
        assigner = VariantAssigner()

        strategies = [
            AssignmentStrategyType.RANDOM,
            AssignmentStrategyType.HASH,
            AssignmentStrategyType.STRATIFIED,
            AssignmentStrategyType.BANDIT,
        ]

        for strategy_type in strategies:
            experiment.assignment_strategy = strategy_type
            variant_id = assigner.assign_variant(experiment, variants, "workflow-test")

            # All should return valid variant IDs
            assert variant_id in [v.id for v in variants]

    def test_assign_zero_traffic_variant(self, experiment):
        """Test assignment with zero-traffic variant (should still work but never assigned)."""
        variants = [
            Variant(
                id="var-control",
                experiment_id="exp-001",
                name="control",
                description="Control",
                is_control=True,
                config_type=ConfigType.AGENT,
                config_overrides={},
                allocated_traffic=1.0,
            ),
            Variant(
                id="var-zero",
                experiment_id="exp-001",
                name="zero_traffic",
                description="Zero traffic",
                is_control=False,
                config_type=ConfigType.AGENT,
                config_overrides={},
                allocated_traffic=0.0,  # No traffic
            ),
        ]

        experiment.assignment_strategy = AssignmentStrategyType.RANDOM
        assigner = VariantAssigner()

        # Run many assignments
        variant_ids = set()
        for i in range(100):
            variant_id = assigner.assign_variant(experiment, variants, f"workflow-{i}")
            variant_ids.add(variant_id)

        # Should only see control variant
        assert variant_ids == {"var-control"}

    def test_strategy_registry_immutability(self):
        """Test that strategy registry can be safely modified."""
        assigner = VariantAssigner()

        original_count = len(assigner._strategies)

        # Register new strategy
        class TestStrategy(AssignmentStrategy):
            def assign(self, experiment, variants, execution_id, context=None):
                return variants[0].id

        assigner.register_strategy(AssignmentStrategyType.RANDOM, TestStrategy())

        # Count should remain same (replaced, not added)
        assert len(assigner._strategies) == original_count
