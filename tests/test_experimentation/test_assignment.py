"""
Tests for variant assignment strategies.

Tests assignment consistency, traffic allocation accuracy, and edge cases.
"""

from collections import Counter

import pytest

from temper_ai.experimentation.assignment import (
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


class TestRandomAssignment:
    """Test random assignment strategy."""

    def test_random_assignment_basic(self, experiment, variants):
        """Test basic random assignment."""
        strategy = RandomAssignment()

        variant_id = strategy.assign(experiment, variants, "workflow-123")

        assert variant_id in ["var-control", "var-a"]

    def test_random_assignment_distribution(self, experiment, variants):
        """Test that random assignment follows traffic allocation over many trials."""
        strategy = RandomAssignment()

        # Run 10000 trials
        results = []
        for i in range(10000):
            variant_id = strategy.assign(experiment, variants, f"workflow-{i}")
            results.append(variant_id)

        # Count distribution
        counts = Counter(results)
        control_ratio = counts["var-control"] / len(results)
        variant_a_ratio = counts["var-a"] / len(results)

        # Should be close to 60/40 split (within 5% tolerance)
        assert 0.55 <= control_ratio <= 0.65
        assert 0.35 <= variant_a_ratio <= 0.45

    def test_random_assignment_no_consistency(self, experiment, variants):
        """Test that random assignment is NOT consistent (same ID can get different variants)."""
        strategy = RandomAssignment()

        # Assign same workflow ID multiple times
        results = set()
        for _ in range(100):
            variant_id = strategy.assign(experiment, variants, "workflow-same")
            results.add(variant_id)

        # Should see both variants (not deterministic)
        # Note: This test has ~0.4^100 chance of false negative, which is negligible
        assert len(results) == 2  # Both variants should appear across 100 calls

    def test_random_assignment_empty_variants(self, experiment):
        """Test that random assignment fails with no variants."""
        strategy = RandomAssignment()

        with pytest.raises(ValueError, match="No variants available"):
            strategy.assign(experiment, [], "workflow-123")

    def test_random_assignment_invalid_traffic(self, experiment, variants):
        """Test that invalid traffic allocation raises error."""
        strategy = RandomAssignment()

        # Set invalid traffic (sum > 1.0)
        variants[0].allocated_traffic = 0.7
        variants[1].allocated_traffic = 0.5

        with pytest.raises(ValueError, match="Invalid traffic allocation"):
            strategy.assign(experiment, variants, "workflow-123")


class TestHashAssignment:
    """Test hash-based assignment strategy."""

    def test_hash_assignment_basic(self, experiment, variants):
        """Test basic hash assignment."""
        strategy = HashAssignment()

        variant_id = strategy.assign(experiment, variants, "workflow-123")

        assert variant_id in ["var-control", "var-a"]

    def test_hash_assignment_consistency(self, experiment, variants):
        """Test that hash assignment is consistent (same ID → same variant)."""
        strategy = HashAssignment()

        # Assign same workflow ID multiple times
        results = []
        for _ in range(100):
            variant_id = strategy.assign(experiment, variants, "workflow-same")
            results.append(variant_id)

        # All assignments should be identical
        assert len(set(results)) == 1

    def test_hash_assignment_different_ids(self, experiment, variants):
        """Test that different IDs get different variants."""
        strategy = HashAssignment()

        # Assign different workflow IDs
        results = set()
        for i in range(1000):
            variant_id = strategy.assign(experiment, variants, f"workflow-{i}")
            results.add(variant_id)

        # Should see both variants across many different IDs
        assert len(results) == 2

    def test_hash_assignment_distribution(self, experiment, variants):
        """Test that hash assignment follows traffic allocation over many IDs."""
        strategy = HashAssignment()

        # Assign 10000 different workflow IDs
        results = []
        for i in range(10000):
            variant_id = strategy.assign(experiment, variants, f"workflow-{i}")
            results.append(variant_id)

        # Count distribution
        counts = Counter(results)
        control_ratio = counts["var-control"] / len(results)
        variant_a_ratio = counts["var-a"] / len(results)

        # Should be close to 60/40 split (within 5% tolerance)
        assert 0.55 <= control_ratio <= 0.65
        assert 0.35 <= variant_a_ratio <= 0.45

    def test_hash_assignment_with_context_key(self, experiment, variants):
        """Test hash assignment using context hash_key."""
        strategy = HashAssignment()

        # Same hash_key should give same variant
        variant_1 = strategy.assign(
            experiment, variants, "workflow-1", context={"hash_key": "user-123"}
        )
        variant_2 = strategy.assign(
            experiment, variants, "workflow-2", context={"hash_key": "user-123"}
        )

        assert variant_1 == variant_2

    def test_hash_assignment_context_key_consistency(self, experiment, variants):
        """Test that same context hash_key is consistent across calls."""
        strategy = HashAssignment()

        results = []
        for i in range(50):
            variant_id = strategy.assign(
                experiment, variants, f"workflow-{i}", context={"hash_key": "user-same"}
            )
            results.append(variant_id)

        # All should be same variant
        assert len(set(results)) == 1


class TestVariantAssigner:
    """Test VariantAssigner coordinator."""

    def test_assigner_random_strategy(self, experiment, variants):
        """Test assigner with random strategy."""
        experiment.assignment_strategy = AssignmentStrategyType.RANDOM
        assigner = VariantAssigner()

        variant_id = assigner.assign_variant(experiment, variants, "workflow-123")

        assert variant_id in ["var-control", "var-a"]

    def test_assigner_hash_strategy(self, experiment, variants):
        """Test assigner with hash strategy."""
        experiment.assignment_strategy = AssignmentStrategyType.HASH
        assigner = VariantAssigner()

        # Should be consistent
        variant_1 = assigner.assign_variant(experiment, variants, "workflow-same")
        variant_2 = assigner.assign_variant(experiment, variants, "workflow-same")

        assert variant_1 == variant_2

    def test_assigner_with_context(self, experiment, variants):
        """Test assigner with context."""
        experiment.assignment_strategy = AssignmentStrategyType.HASH
        assigner = VariantAssigner()

        variant_id = assigner.assign_variant(
            experiment, variants, "workflow-123", context={"hash_key": "user-456"}
        )

        assert variant_id in ["var-control", "var-a"]

    def test_assigner_unknown_strategy(self, experiment, variants):
        """Test that unknown strategy raises error."""
        # Create invalid strategy type (bypass enum)
        experiment.assignment_strategy = "unknown_strategy"
        assigner = VariantAssigner()

        with pytest.raises(ValueError, match="Unknown assignment strategy"):
            assigner.assign_variant(experiment, variants, "workflow-123")


class TestEdgeCases:
    """Test edge cases and error conditions."""

    def test_single_variant(self, experiment):
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

        strategy = RandomAssignment()
        variant_id = strategy.assign(experiment, variants, "workflow-123")

        assert variant_id == "var-only"

    def test_three_variants(self, experiment):
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

        # Update experiment traffic allocation
        experiment.traffic_allocation = {
            "control": 0.5,
            "variant_a": 0.3,
            "variant_b": 0.2,
        }

        strategy = RandomAssignment()

        # Run many trials
        results = []
        for i in range(10000):
            variant_id = strategy.assign(experiment, variants, f"workflow-{i}")
            results.append(variant_id)

        counts = Counter(results)

        # Check all variants are assigned
        assert len(counts) == 3

        # Check approximate distribution
        assert 0.45 <= counts["var-control"] / len(results) <= 0.55
        assert 0.25 <= counts["var-a"] / len(results) <= 0.35
        assert 0.15 <= counts["var-b"] / len(results) <= 0.25

    def test_uneven_traffic_allocation(self, experiment):
        """Test assignment with very uneven traffic (95/5 split)."""
        variants = [
            Variant(
                id="var-control",
                experiment_id="exp-001",
                name="control",
                description="Control",
                is_control=True,
                config_type=ConfigType.AGENT,
                config_overrides={},
                allocated_traffic=0.95,
            ),
            Variant(
                id="var-a",
                experiment_id="exp-001",
                name="variant_a",
                description="Variant A",
                is_control=False,
                config_type=ConfigType.AGENT,
                config_overrides={},
                allocated_traffic=0.05,
            ),
        ]

        strategy = RandomAssignment()

        # Run many trials
        results = []
        for i in range(10000):
            variant_id = strategy.assign(experiment, variants, f"workflow-{i}")
            results.append(variant_id)

        counts = Counter(results)
        control_ratio = counts["var-control"] / len(results)
        variant_a_ratio = counts["var-a"] / len(results)

        # Should see 95/5 split (within tolerance)
        assert 0.93 <= control_ratio <= 0.97
        assert 0.03 <= variant_a_ratio <= 0.07


class TestStrategyPlaceholders:
    """Test placeholder strategies (future implementation)."""

    def test_stratified_assignment_fallback(self, experiment, variants):
        """Test that stratified assignment falls back to hash."""
        strategy = StratifiedAssignment()

        # Should fall back to hash assignment (consistent)
        variant_1 = strategy.assign(experiment, variants, "workflow-same")
        variant_2 = strategy.assign(experiment, variants, "workflow-same")

        assert variant_1 == variant_2

    def test_bandit_assignment_fallback(self, experiment, variants):
        """Test that bandit assignment falls back to random."""
        strategy = BanditAssignment()

        # Should fall back to random assignment (works but not consistent)
        variant_id = strategy.assign(experiment, variants, "workflow-123")

        assert variant_id in ["var-control", "var-a"]
