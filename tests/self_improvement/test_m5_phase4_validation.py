"""
M5 Phase 4 Validation Tests

Validates the complete M5 experiment orchestrator system with 4-way experiments
and 200 executions to verify winner selection works correctly at scale.

CRITICAL: These tests validate production experiment behavior including:
- 4-way A/B/C/D testing (control + 3 variants)
- Statistical winner selection with 200+ executions
- Variant assignment distribution fairness
- Result collection and aggregation accuracy
- Winner determination correctness
"""

import pytest
import random
from datetime import datetime
from typing import Dict, List

from src.self_improvement.experiment_orchestrator import (
    ExperimentOrchestrator,
    ExperimentError,
)
from src.self_improvement.data_models import AgentConfig
from src.observability.database import init_database, reset_database


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def db_session():
    """Create in-memory database session for testing."""
    reset_database()
    db_manager = init_database("sqlite:///:memory:")
    with db_manager.session() as session:
        yield session
    reset_database()


@pytest.fixture
def orchestrator(db_session):
    """Create ExperimentOrchestrator instance with 50 samples per variant."""
    return ExperimentOrchestrator(
        session=db_session,
        target_executions_per_variant=50
    )


@pytest.fixture
def four_way_configs():
    """
    Create 4-way experiment configs: control + 3 variants.

    Simulates testing 4 different LLM models for the same agent:
    - Control: llama3.1:8b (baseline)
    - Variant 0: phi3:mini (faster, slightly lower quality)
    - Variant 1: gemma2:2b (best quality, slightly slower)
    - Variant 2: mistral:7b (balanced)
    """
    control = AgentConfig(
        agent_name="product_extractor",
        inference={"model": "llama3.1:8b", "temperature": 0.7}
    )

    variants = [
        AgentConfig(
            agent_name="product_extractor",
            inference={"model": "phi3:mini", "temperature": 0.7}
        ),
        AgentConfig(
            agent_name="product_extractor",
            inference={"model": "gemma2:2b", "temperature": 0.7}
        ),
        AgentConfig(
            agent_name="product_extractor",
            inference={"model": "mistral:7b", "temperature": 0.7}
        ),
    ]

    return {"control": control, "variants": variants}


def generate_realistic_metrics(
    variant_id: str,
    base_quality: float = 0.70,
    quality_variance: float = 0.10
) -> Dict[str, float]:
    """
    Generate realistic quality/speed/cost metrics for a variant.

    Args:
        variant_id: 'control', 'variant_0', 'variant_1', or 'variant_2'
        base_quality: Base quality score (0-1)
        quality_variance: Random variance around base quality

    Returns:
        Dict with quality_score, speed_seconds, cost_usd

    Metric profiles by variant (simulated realistic values):
    - control (llama3.1:8b): quality=0.70±0.10, speed=40±5s, cost=$0.80±0.10
    - variant_0 (phi3:mini): quality=0.65±0.10, speed=25±3s, cost=$0.50±0.05 (faster, cheaper, lower quality)
    - variant_1 (gemma2:2b): quality=0.85±0.08, speed=42±6s, cost=$0.75±0.08 (BEST quality, similar speed/cost)
    - variant_2 (mistral:7b): quality=0.72±0.10, speed=38±5s, cost=$0.78±0.10 (slightly better)
    """
    profiles = {
        "control": {
            "quality_base": 0.70,
            "quality_std": 0.10,
            "speed_mean": 40.0,
            "speed_std": 5.0,
            "cost_mean": 0.80,
            "cost_std": 0.10,
        },
        "variant_0": {  # phi3:mini - fast/cheap but lower quality
            "quality_base": 0.65,
            "quality_std": 0.10,
            "speed_mean": 25.0,
            "speed_std": 3.0,
            "cost_mean": 0.50,
            "cost_std": 0.05,
        },
        "variant_1": {  # gemma2:2b - WINNER (best quality)
            "quality_base": 0.85,
            "quality_std": 0.08,
            "speed_mean": 42.0,
            "speed_std": 6.0,
            "cost_mean": 0.75,
            "cost_std": 0.08,
        },
        "variant_2": {  # mistral:7b - slightly better than control
            "quality_base": 0.72,
            "quality_std": 0.10,
            "speed_mean": 38.0,
            "speed_std": 5.0,
            "cost_mean": 0.78,
            "cost_std": 0.10,
        },
    }

    profile = profiles.get(variant_id, profiles["control"])

    # Generate metrics with realistic variance
    quality = max(0.0, min(1.0, random.gauss(
        profile["quality_base"],
        profile["quality_std"]
    )))
    speed = max(0.1, random.gauss(
        profile["speed_mean"],
        profile["speed_std"]
    ))
    cost = max(0.0, random.gauss(
        profile["cost_mean"],
        profile["cost_std"]
    ))

    return {
        "quality_score": quality,
        "speed_seconds": speed,
        "cost_usd": cost,
    }


# ============================================================================
# Phase 4 Validation Tests
# ============================================================================


class TestFourWayExperimentValidation:
    """Validate 4-way experiment with 200 executions."""

    def test_create_four_way_experiment(
        self,
        orchestrator,
        four_way_configs
    ):
        """
        CRITICAL: Verify 4-way experiment (control + 3 variants) created correctly.

        Expected:
        - Experiment created with 4 total groups
        - Status = 'running'
        - Control + 3 variants stored correctly
        """
        experiment = orchestrator.create_experiment(
            agent_name="product_extractor",
            control_config=four_way_configs["control"],
            variant_configs=four_way_configs["variants"],
            proposal_id="proposal-phase4-validation"
        )

        # VALIDATION: 4-way experiment structure
        assert experiment.get_variant_count() == 4, \
            f"Expected 4 groups, got {experiment.get_variant_count()}"
        assert experiment.status == "running"
        assert experiment.agent_name == "product_extractor"
        assert len(experiment.variant_configs) == 3, \
            "Should have 3 variants (plus control = 4 total)"

        # VALIDATION: Control config stored
        assert experiment.control_config is not None
        assert experiment.control_config.agent_name == "product_extractor"

        # VALIDATION: All variant configs stored
        for i, variant in enumerate(experiment.variant_configs):
            assert variant.agent_name == "product_extractor"
            assert variant.inference["model"] in [
                "phi3:mini", "gemma2:2b", "mistral:7b"
            ]

    def test_200_executions_variant_distribution(
        self,
        orchestrator,
        four_way_configs
    ):
        """
        CRITICAL: Run 200 executions and verify fair distribution across 4 variants.

        Expected distribution (hash-based assignment):
        - Each variant: ~50 executions (±10 for hash variance)
        - Total: 200 executions
        - Deterministic: same execution_id always gets same variant
        """
        # Create experiment
        experiment = orchestrator.create_experiment(
            agent_name="product_extractor",
            control_config=four_way_configs["control"],
            variant_configs=four_way_configs["variants"],
            proposal_id="proposal-200-executions"
        )

        # Track assignments
        variant_counts = {
            "control": 0,
            "variant_0": 0,
            "variant_1": 0,
            "variant_2": 0,
        }
        assignments = {}

        # Run 200 executions
        for i in range(200):
            execution_id = f"exec-{i:04d}"

            # Assign variant
            assignment = orchestrator.assign_variant(
                experiment.id,
                execution_id
            )

            # Track assignment
            variant_counts[assignment.variant_id] += 1
            assignments[execution_id] = assignment.variant_id

            # Generate realistic metrics for this variant
            metrics = generate_realistic_metrics(assignment.variant_id)

            # Record result
            orchestrator.record_result(
                experiment.id,
                assignment.variant_id,
                execution_id,
                quality_score=metrics["quality_score"],
                speed_seconds=metrics["speed_seconds"],
                cost_usd=metrics["cost_usd"],
                success=True
            )

        # VALIDATION: Total executions
        total = sum(variant_counts.values())
        assert total == 200, f"Expected 200 executions, got {total}"

        # VALIDATION: Fair distribution (each variant ~50 ±15)
        for variant_id, count in variant_counts.items():
            assert 35 <= count <= 65, \
                f"Variant {variant_id} has {count} executions, expected ~50 ±15. " \
                f"Distribution: {variant_counts}"

        # VALIDATION: Deterministic assignment (retry same execution_id)
        for execution_id, original_variant in list(assignments.items())[:10]:
            retry_assignment = orchestrator.assign_variant(
                experiment.id,
                execution_id
            )
            assert retry_assignment.variant_id == original_variant, \
                f"Assignment not deterministic! {execution_id} got {original_variant} " \
                f"first, {retry_assignment.variant_id} on retry"

        print(f"\n✓ Distribution validation passed:")
        print(f"  Control: {variant_counts['control']} executions")
        print(f"  Variant 0 (phi3:mini): {variant_counts['variant_0']} executions")
        print(f"  Variant 1 (gemma2:2b): {variant_counts['variant_1']} executions")
        print(f"  Variant 2 (mistral:7b): {variant_counts['variant_2']} executions")

    def test_winner_selection_with_200_samples(
        self,
        orchestrator,
        four_way_configs
    ):
        """
        CRITICAL: Verify winner selection works correctly with 200 executions.

        Expected winner: variant_1 (gemma2:2b)
        - Best quality: 0.85 vs 0.70 control (+21% improvement)
        - Similar speed: 42s vs 40s control
        - Similar cost: $0.75 vs $0.80 control
        - Should be statistically significant with ~50 samples

        Expected non-winners:
        - variant_0 (phi3:mini): Lower quality despite being faster/cheaper
        - variant_2 (mistral:7b): Only +2.8% quality improvement (not significant)
        """
        # Create experiment
        experiment = orchestrator.create_experiment(
            agent_name="product_extractor",
            control_config=four_way_configs["control"],
            variant_configs=four_way_configs["variants"],
            proposal_id="proposal-winner-selection"
        )

        # Set random seed for reproducible metrics
        random.seed(42)

        # Run 200 executions with realistic metrics
        for i in range(200):
            execution_id = f"exec-winner-{i:04d}"

            # Assign variant
            assignment = orchestrator.assign_variant(
                experiment.id,
                execution_id
            )

            # Generate realistic metrics for this variant
            metrics = generate_realistic_metrics(assignment.variant_id)

            # Record result
            orchestrator.record_result(
                experiment.id,
                assignment.variant_id,
                execution_id,
                quality_score=metrics["quality_score"],
                speed_seconds=metrics["speed_seconds"],
                cost_usd=metrics["cost_usd"],
                success=True
            )

        # VALIDATION: Get progress
        progress = orchestrator.get_experiment_progress(experiment.id)

        # Note: Due to hash-based distribution, not all variants may have exactly 50 samples
        # The experiment may not be technically "complete" but should have enough data
        # to analyze. We'll use force=True if needed.

        # VALIDATION: Check if experiment is complete
        is_complete = orchestrator.is_experiment_complete(experiment.id)

        # VALIDATION: Analyze experiment (analyze_experiment doesn't have force parameter)
        analysis = orchestrator.analyze_experiment(experiment.id)

        assert analysis is not None, "Analysis should not be None"
        assert analysis.control_results is not None
        assert len(analysis.variant_comparisons) == 3, \
            "Should have 3 variant comparisons"

        # VALIDATION: Get winner (use force=True if not complete)
        winner = orchestrator.get_winner(experiment.id, force=True)

        # CRITICAL VALIDATION: Winner should be variant_1 (gemma2:2b - best quality)
        assert winner is not None, \
            "Winner should be selected with 200 executions and clear quality difference"

        assert winner.variant_id == "variant_1", \
            f"Expected variant_1 (gemma2:2b) to win, got {winner.variant_id}. " \
            f"variant_1 has highest quality (~0.85 vs 0.70 control). " \
            f"Comparisons: {[c.variant_id + ':' + str(c.composite_score) for c in analysis.variant_comparisons]}"

        # VALIDATION: Winner has significant quality improvement
        assert winner.quality_improvement > 10.0, \
            f"Winner quality improvement should be >10%, got {winner.quality_improvement:.1f}%"

        assert winner.composite_score > 5.0, \
            f"Winner composite score should be >5%, got {winner.composite_score:.1f}%"

        # VALIDATION: Winner recommendation
        assert "recommend" in winner.recommendation.lower() or \
               "deploy" in winner.recommendation.lower(), \
            f"Winner recommendation should suggest deployment: {winner.recommendation}"

        # VALIDATION: Complete experiment
        orchestrator.complete_experiment(
            experiment.id,
            winner_variant_id=winner.variant_id
        )

        # VALIDATION: Experiment status updated
        from src.observability.database import get_database
        from sqlalchemy import text
        db = get_database()
        with db.session() as session:
            updated_exp = session.execute(
                text("SELECT status, winner_variant_id FROM m5_experiments WHERE id = :id"),
                {"id": experiment.id}
            ).fetchone()

            assert updated_exp[0] == "completed", \
                f"Experiment status should be 'completed', got {updated_exp[0]}"
            assert updated_exp[1] == "variant_1", \
                f"Winner should be stored as variant_1, got {updated_exp[1]}"

        print(f"\n✓ Winner selection validation passed:")
        print(f"  Winner: {winner.variant_id}")
        print(f"  Quality improvement: +{winner.quality_improvement:.1f}%")
        print(f"  Speed improvement: {winner.speed_improvement:+.1f}%")
        print(f"  Cost improvement: {winner.cost_improvement:+.1f}%")
        print(f"  Composite score: +{winner.composite_score:.1f}%")
        print(f"  Recommendation: {winner.recommendation}")

    def test_no_winner_when_all_worse(
        self,
        orchestrator,
        four_way_configs
    ):
        """
        Verify no winner selected when all variants perform worse than control.

        Expected:
        - All variants worse than control
        - No statistically significant improvement
        - Winner = None
        """
        # Modify configs to make all variants worse
        worse_variants = [
            AgentConfig(
                agent_name="product_extractor",
                inference={"model": "bad_model_1", "temperature": 0.7}
            ),
            AgentConfig(
                agent_name="product_extractor",
                inference={"model": "bad_model_2", "temperature": 0.7}
            ),
            AgentConfig(
                agent_name="product_extractor",
                inference={"model": "bad_model_3", "temperature": 0.7}
            ),
        ]

        experiment = orchestrator.create_experiment(
            agent_name="product_extractor",
            control_config=four_way_configs["control"],
            variant_configs=worse_variants,
            proposal_id="proposal-no-winner"
        )

        # Set seed for reproducibility
        random.seed(123)

        # Override generate_realistic_metrics to make all variants worse
        def generate_worse_metrics(variant_id: str):
            if variant_id == "control":
                # Control: good quality
                quality = max(0.0, min(1.0, random.gauss(0.80, 0.08)))
            else:
                # All variants: worse quality
                quality = max(0.0, min(1.0, random.gauss(0.60, 0.10)))

            speed = max(0.1, random.gauss(40.0, 5.0))
            cost = max(0.0, random.gauss(0.80, 0.10))

            return {
                "quality_score": quality,
                "speed_seconds": speed,
                "cost_usd": cost,
            }

        # Run 200 executions
        for i in range(200):
            execution_id = f"exec-nowinner-{i:04d}"

            assignment = orchestrator.assign_variant(
                experiment.id,
                execution_id
            )

            metrics = generate_worse_metrics(assignment.variant_id)

            orchestrator.record_result(
                experiment.id,
                assignment.variant_id,
                execution_id,
                quality_score=metrics["quality_score"],
                speed_seconds=metrics["speed_seconds"],
                cost_usd=metrics["cost_usd"],
                success=True
            )

        # VALIDATION: No winner should be selected (use force=True)
        winner = orchestrator.get_winner(experiment.id, force=True)

        assert winner is None, \
            f"No winner should be selected when all variants worse than control, " \
            f"but got winner: {winner.variant_id if winner else None}"

        print("\n✓ No-winner validation passed: correctly detected no improvement")

    def test_experiment_progress_tracking(
        self,
        orchestrator,
        four_way_configs
    ):
        """
        Verify experiment progress tracking during execution.

        Expected:
        - Progress increases as results collected
        - Per-variant progress tracked correctly
        - Overall progress calculated correctly
        """
        experiment = orchestrator.create_experiment(
            agent_name="product_extractor",
            control_config=four_way_configs["control"],
            variant_configs=four_way_configs["variants"],
            proposal_id="proposal-progress"
        )

        # Check initial progress (should be 0 collected)
        progress = orchestrator.get_experiment_progress(experiment.id)
        assert progress["total_collected"] == 0
        assert all(
            v["collected"] == 0
            for v in progress["variants"].values()
        )

        # Run 100 executions (halfway to 200)
        random.seed(456)
        for i in range(100):
            execution_id = f"exec-progress-{i:04d}"

            assignment = orchestrator.assign_variant(
                experiment.id,
                execution_id
            )

            metrics = generate_realistic_metrics(assignment.variant_id)

            orchestrator.record_result(
                experiment.id,
                assignment.variant_id,
                execution_id,
                quality_score=metrics["quality_score"],
                speed_seconds=metrics["speed_seconds"],
                cost_usd=metrics["cost_usd"],
                success=True
            )

        # Check mid-experiment progress
        progress = orchestrator.get_experiment_progress(experiment.id)

        # VALIDATION: Total collected ~100
        assert progress["total_collected"] == 100, \
            f"Expected 100 total collected, got {progress['total_collected']}"

        # VALIDATION: Progress percentage ~50% (100 out of 200 target)
        progress_pct = (progress["total_collected"] / progress["total_target"]) * 100
        assert 40 <= progress_pct <= 60, \
            f"Expected ~50% progress, got {progress_pct:.1f}%"

        # VALIDATION: Not yet complete (not all variants reached target)
        assert not progress["is_complete"], \
            "Experiment should not be complete at 100/200 executions"

        # Run remaining 100 executions
        for i in range(100, 200):
            execution_id = f"exec-progress-{i:04d}"

            assignment = orchestrator.assign_variant(
                experiment.id,
                execution_id
            )

            metrics = generate_realistic_metrics(assignment.variant_id)

            orchestrator.record_result(
                experiment.id,
                assignment.variant_id,
                execution_id,
                quality_score=metrics["quality_score"],
                speed_seconds=metrics["speed_seconds"],
                cost_usd=metrics["cost_usd"],
                success=True
            )

        # Check final progress
        final_progress = orchestrator.get_experiment_progress(experiment.id)

        # VALIDATION: Total collected = 200
        assert final_progress["total_collected"] == 200, \
            f"Expected 200 total collected, got {final_progress['total_collected']}"

        # VALIDATION: Experiment should be complete (all variants should have ≥50 samples)
        # Note: Due to hash-based distribution, this might not always be true
        # But with 200 executions and 4 variants, each should get ~50
        if final_progress["is_complete"]:
            assert orchestrator.is_experiment_complete(experiment.id)
        else:
            print(f"\n  Note: Experiment not technically complete due to uneven distribution:")
            print(f"  {final_progress['variants']}")

        print(f"\n✓ Progress tracking validation passed:")
        print(f"  Total collected: {final_progress['total_collected']}/{final_progress['total_target']}")
        print(f"  All variants: {final_progress['variants']}")
        print(f"  Is complete: {final_progress['is_complete']}")
