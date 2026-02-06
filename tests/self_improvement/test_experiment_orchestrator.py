"""Tests for ExperimentOrchestrator."""
import random

import pytest

from src.observability.database import init_database, reset_database
from src.self_improvement.data_models import SIOptimizationConfig
from src.self_improvement.experiment_orchestrator import (
    ExperimentNotCompleteError,
    ExperimentOrchestrator,
    InvalidVariantError,
)


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
    """Create ExperimentOrchestrator instance."""
    return ExperimentOrchestrator(
        session=db_session,
        target_executions_per_variant=50
    )


@pytest.fixture
def control_config():
    """Create control configuration."""
    return SIOptimizationConfig(
        agent_name="test_agent",
        inference={"model": "llama3.1:8b", "temperature": 0.7}
    )


@pytest.fixture
def variant_configs():
    """Create variant configurations."""
    return [
        SIOptimizationConfig(
            agent_name="test_agent",
            inference={"model": "phi3:mini", "temperature": 0.7}
        ),
        SIOptimizationConfig(
            agent_name="test_agent",
            inference={"model": "gemma2:2b", "temperature": 0.7}
        ),
    ]


# ========== Experiment Creation Tests ==========

class TestExperimentCreation:
    """Tests for experiment creation."""

    def test_create_experiment_with_2_variants(
        self, orchestrator, control_config, variant_configs
    ):
        """Verify experiment created with control + 2 variants."""
        experiment = orchestrator.create_experiment(
            agent_name="test_agent",
            control_config=control_config,
            variant_configs=variant_configs,
            proposal_id="proposal-123"
        )

        assert experiment.get_variant_count() == 3
        assert experiment.status == "running"
        assert experiment.agent_name == "test_agent"
        assert experiment.proposal_id == "proposal-123"
        assert len(experiment.variant_configs) == 2

    def test_create_experiment_with_1_variant(
        self, orchestrator, control_config, variant_configs
    ):
        """Verify experiment created with control + 1 variant."""
        experiment = orchestrator.create_experiment(
            agent_name="test_agent",
            control_config=control_config,
            variant_configs=[variant_configs[0]]
        )

        assert experiment.get_variant_count() == 2
        assert experiment.status == "running"

    def test_create_experiment_with_custom_target(
        self, orchestrator, control_config, variant_configs
    ):
        """Verify experiment created with custom target samples."""
        experiment = orchestrator.create_experiment(
            agent_name="test_agent",
            control_config=control_config,
            variant_configs=variant_configs,
            target_executions_per_variant=100
        )

        assert experiment.id is not None

    def test_create_experiment_no_variants_raises(
        self, orchestrator, control_config
    ):
        """Verify creating experiment with no variants raises error."""
        with pytest.raises(ValueError, match="at least one variant"):
            orchestrator.create_experiment(
                agent_name="test_agent",
                control_config=control_config,
                variant_configs=[]
            )

    def test_create_experiment_too_many_variants_raises(
        self, orchestrator, control_config
    ):
        """Verify creating experiment with >3 variants raises error."""
        too_many_variants = [
            SIOptimizationConfig(agent_name="test_agent", inference={"model": f"model-{i}"})
            for i in range(4)
        ]

        with pytest.raises(ValueError, match="Maximum 3 variants"):
            orchestrator.create_experiment(
                agent_name="test_agent",
                control_config=control_config,
                variant_configs=too_many_variants
            )

    def test_create_experiment_mismatched_agent_names_raises(
        self, orchestrator, control_config
    ):
        """Verify mismatched agent names raises error."""
        bad_variant = SIOptimizationConfig(
            agent_name="different_agent",  # Different!
            inference={"model": "phi3:mini"}
        )

        with pytest.raises(ValueError, match="same agent_name"):
            orchestrator.create_experiment(
                agent_name="test_agent",
                control_config=control_config,
                variant_configs=[bad_variant]
            )


# ========== Variant Assignment Tests ==========

class TestVariantAssignment:
    """Tests for variant assignment."""

    def test_assign_variant_deterministic(
        self, orchestrator, control_config, variant_configs
    ):
        """Verify same execution_id always gets same variant."""
        experiment = orchestrator.create_experiment(
            agent_name="test_agent",
            control_config=control_config,
            variant_configs=variant_configs
        )

        # Assign 10 times
        variants = [
            orchestrator.assign_variant(experiment.id, "exec-123").variant_id
            for _ in range(10)
        ]

        # All should be the same
        assert len(set(variants)) == 1

    def test_assign_variant_returns_valid_variant_id(
        self, orchestrator, control_config, variant_configs
    ):
        """Verify assigned variant_id is valid."""
        experiment = orchestrator.create_experiment(
            agent_name="test_agent",
            control_config=control_config,
            variant_configs=variant_configs
        )

        assignment = orchestrator.assign_variant(experiment.id, "exec-456")

        assert assignment.variant_id in ["control", "variant_0", "variant_1"]
        assert assignment.experiment_id == experiment.id
        assert assignment.execution_id == "exec-456"
        assert isinstance(assignment.config, SIOptimizationConfig)

    def test_assign_variant_uniform_distribution(
        self, orchestrator, control_config, variant_configs
    ):
        """Verify variants are uniformly distributed across executions."""
        experiment = orchestrator.create_experiment(
            agent_name="test_agent",
            control_config=control_config,
            variant_configs=variant_configs
        )

        # Assign 300 executions
        variant_counts = {"control": 0, "variant_0": 0, "variant_1": 0}
        for i in range(300):
            assignment = orchestrator.assign_variant(experiment.id, f"exec-{i}")
            variant_counts[assignment.variant_id] += 1

        # Each variant should get roughly 100 assignments (33% each)
        # Allow 20% deviation (80-120 range)
        for variant_id, count in variant_counts.items():
            assert 80 <= count <= 120, f"{variant_id} got {count} assignments"

    def test_assign_variant_experiment_not_found_raises(self, orchestrator):
        """Verify assigning to non-existent experiment raises error."""
        with pytest.raises(ValueError, match="Invalid experiment_id format"):
            orchestrator.assign_variant("nonexistent-exp", "exec-123")

    def test_assign_variant_with_context_hash_key(
        self, orchestrator, control_config, variant_configs
    ):
        """Verify assignment uses context hash_key if provided."""
        experiment = orchestrator.create_experiment(
            agent_name="test_agent",
            control_config=control_config,
            variant_configs=variant_configs
        )

        # Use context with hash_key - should be deterministic
        assignment1 = orchestrator.assign_variant(
            experiment.id,
            "exec-random-1",
            context={"hash_key": "user-123"}
        )
        assignment2 = orchestrator.assign_variant(
            experiment.id,
            "exec-random-2",
            context={"hash_key": "user-123"}
        )

        # Same hash_key should give same variant
        assert assignment1.variant_id == assignment2.variant_id


# ========== Result Recording Tests ==========

class TestResultRecording:
    """Tests for result recording."""

    def test_record_result_success(
        self, orchestrator, control_config, variant_configs
    ):
        """Verify result is successfully recorded."""
        experiment = orchestrator.create_experiment(
            agent_name="test_agent",
            control_config=control_config,
            variant_configs=variant_configs
        )

        assignment = orchestrator.assign_variant(experiment.id, "exec-123")

        # Record result - should not raise
        orchestrator.record_result(
            experiment.id,
            assignment.variant_id,
            "exec-123",
            quality_score=0.85,
            speed_seconds=42.5,
            cost_usd=0.78,
            success=True
        )

        # Verify result stored
        results = orchestrator.get_experiment_results(experiment.id)
        assert len(results) == 1
        assert results[0].variant_id == assignment.variant_id
        assert results[0].quality_score == 0.85

    def test_record_result_invalid_variant_raises(
        self, orchestrator, control_config, variant_configs
    ):
        """Verify invalid variant_id raises error."""
        experiment = orchestrator.create_experiment(
            agent_name="test_agent",
            control_config=control_config,
            variant_configs=variant_configs
        )

        with pytest.raises(ValueError, match="Invalid variant_id format"):
            orchestrator.record_result(
                experiment.id,
                "invalid_variant",  # Invalid!
                "exec-123",
                quality_score=0.85
            )

    def test_record_result_experiment_not_found_raises(self, orchestrator):
        """Verify recording result for non-existent experiment raises error."""
        with pytest.raises(ValueError, match="Invalid experiment_id format"):
            orchestrator.record_result(
                "nonexistent-exp",
                "control",
                "exec-123",
                quality_score=0.85
            )


# ========== Experiment Progress Tests ==========

class TestExperimentProgress:
    """Tests for experiment progress tracking."""

    def test_is_complete_insufficient_samples(
        self, orchestrator, control_config, variant_configs
    ):
        """Verify returns False when samples insufficient."""
        experiment = orchestrator.create_experiment(
            agent_name="test_agent",
            control_config=control_config,
            variant_configs=variant_configs,
            target_executions_per_variant=50
        )

        # Record 40/50/50 samples
        for i in range(40):
            orchestrator.record_result(
                experiment.id, "control", f"exec-control-{i}",
                quality_score=0.70
            )
        for i in range(50):
            orchestrator.record_result(
                experiment.id, "variant_0", f"exec-v0-{i}",
                quality_score=0.75
            )
        for i in range(50):
            orchestrator.record_result(
                experiment.id, "variant_1", f"exec-v1-{i}",
                quality_score=0.80
            )

        assert not orchestrator.is_experiment_complete(experiment.id)

    def test_is_complete_all_sufficient(
        self, orchestrator, control_config, variant_configs
    ):
        """Verify returns True when all variants have enough samples."""
        experiment = orchestrator.create_experiment(
            agent_name="test_agent",
            control_config=control_config,
            variant_configs=variant_configs,
            target_executions_per_variant=50
        )

        # Record 50/52/48 samples
        for i in range(50):
            orchestrator.record_result(
                experiment.id, "control", f"exec-control-{i}",
                quality_score=0.70
            )
        for i in range(52):
            orchestrator.record_result(
                experiment.id, "variant_0", f"exec-v0-{i}",
                quality_score=0.75
            )
        for i in range(48):  # Still meets target (>= 50 relaxed to >= 48 for testing)
            orchestrator.record_result(
                experiment.id, "variant_1", f"exec-v1-{i}",
                quality_score=0.80
            )

        # Note: This might fail if >= 50 is strict. Adjust based on implementation.
        # For now, assume 48 < 50 means incomplete
        # Let's record 2 more to meet target
        orchestrator.record_result(
            experiment.id, "variant_1", "exec-v1-48", quality_score=0.80
        )
        orchestrator.record_result(
            experiment.id, "variant_1", "exec-v1-49", quality_score=0.80
        )

        assert orchestrator.is_experiment_complete(experiment.id)

    def test_get_experiment_progress(
        self, orchestrator, control_config, variant_configs
    ):
        """Verify progress tracking shows correct metrics."""
        experiment = orchestrator.create_experiment(
            agent_name="test_agent",
            control_config=control_config,
            variant_configs=variant_configs,
            target_executions_per_variant=50
        )

        # Record 25/30/20 samples
        for i in range(25):
            orchestrator.record_result(
                experiment.id, "control", f"exec-control-{i}", quality_score=0.70
            )
        for i in range(30):
            orchestrator.record_result(
                experiment.id, "variant_0", f"exec-v0-{i}", quality_score=0.75
            )
        for i in range(20):
            orchestrator.record_result(
                experiment.id, "variant_1", f"exec-v1-{i}", quality_score=0.80
            )

        progress = orchestrator.get_experiment_progress(experiment.id)

        assert progress["target_per_variant"] == 50
        assert progress["variants"]["control"]["collected"] == 25
        assert progress["variants"]["variant_0"]["collected"] == 30
        assert progress["variants"]["variant_1"]["collected"] == 20
        assert progress["total_collected"] == 75
        assert progress["total_target"] == 150
        assert progress["is_complete"] is False


# ========== Winner Determination Tests ==========

class TestWinnerDetermination:
    """Tests for winner analysis and determination."""

    def test_analyze_experiment_determines_winner(
        self, orchestrator, control_config, variant_configs
    ):
        """Verify analysis selects winner based on composite score."""
        experiment = orchestrator.create_experiment(
            agent_name="test_agent",
            control_config=control_config,
            variant_configs=variant_configs,
            target_executions_per_variant=50
        )

        # Seed for reproducibility
        random.seed(42)

        # Simulate results: variant_1 has best quality
        for i in range(50):
            orchestrator.record_result(
                experiment.id, "control", f"exec-control-{i}",
                quality_score=0.70 + random.uniform(-0.02, 0.02),
                speed_seconds=40.0 + random.uniform(-2, 2),
                cost_usd=0.80 + random.uniform(-0.05, 0.05)
            )
        for i in range(50):
            orchestrator.record_result(
                experiment.id, "variant_0", f"exec-v0-{i}",
                quality_score=0.75 + random.uniform(-0.02, 0.02),
                speed_seconds=40.0 + random.uniform(-2, 2),
                cost_usd=0.80 + random.uniform(-0.05, 0.05)
            )
        for i in range(50):
            orchestrator.record_result(
                experiment.id, "variant_1", f"exec-v1-{i}",
                quality_score=0.85 + random.uniform(-0.02, 0.02),  # Best quality
                speed_seconds=40.0 + random.uniform(-2, 2),
                cost_usd=0.80 + random.uniform(-0.05, 0.05)
            )

        winner = orchestrator.get_winner(experiment.id)

        assert winner is not None
        assert winner.variant_id == "variant_1"
        assert winner.quality_improvement > 0
        assert winner.is_statistically_significant

    def test_get_winner_experiment_not_complete_raises(
        self, orchestrator, control_config, variant_configs
    ):
        """Verify getting winner on incomplete experiment raises error."""
        experiment = orchestrator.create_experiment(
            agent_name="test_agent",
            control_config=control_config,
            variant_configs=variant_configs,
            target_executions_per_variant=50
        )

        # Only record 10 samples
        for i in range(10):
            orchestrator.record_result(
                experiment.id, "control", f"exec-control-{i}", quality_score=0.70
            )

        with pytest.raises(ExperimentNotCompleteError):
            orchestrator.get_winner(experiment.id)

    def test_get_winner_force_allows_incomplete(
        self, orchestrator, control_config, variant_configs
    ):
        """Verify force=True allows analyzing incomplete experiment."""
        experiment = orchestrator.create_experiment(
            agent_name="test_agent",
            control_config=control_config,
            variant_configs=variant_configs,
            target_executions_per_variant=50
        )

        # Only record 30 samples per variant
        for i in range(30):
            orchestrator.record_result(
                experiment.id, "control", f"exec-control-{i}",
                quality_score=0.70
            )
            orchestrator.record_result(
                experiment.id, "variant_0", f"exec-v0-{i}",
                quality_score=0.75
            )
            orchestrator.record_result(
                experiment.id, "variant_1", f"exec-v1-{i}",
                quality_score=0.85
            )

        # Should not raise with force=True
        winner = orchestrator.get_winner(experiment.id, force=True)
        # Winner may or may not be found depending on statistical significance


    def test_get_winning_config(
        self, orchestrator, control_config, variant_configs
    ):
        """Verify returns correct config for winner."""
        experiment = orchestrator.create_experiment(
            agent_name="test_agent",
            control_config=control_config,
            variant_configs=variant_configs,
            target_executions_per_variant=50
        )

        random.seed(42)

        # Simulate results with variant_1 as clear winner
        for i in range(50):
            orchestrator.record_result(
                experiment.id, "control", f"exec-control-{i}",
                quality_score=0.70, speed_seconds=40.0, cost_usd=0.80
            )
            orchestrator.record_result(
                experiment.id, "variant_0", f"exec-v0-{i}",
                quality_score=0.75, speed_seconds=40.0, cost_usd=0.80
            )
            orchestrator.record_result(
                experiment.id, "variant_1", f"exec-v1-{i}",
                quality_score=0.85, speed_seconds=40.0, cost_usd=0.80
            )

        winning_config = orchestrator.get_winning_config(experiment.id)

        assert winning_config is not None
        assert winning_config.agent_name == "test_agent"
        # Verify it's variant_1's config (gemma2:2b)
        assert winning_config.inference["model"] == "gemma2:2b"


# ========== Integration Tests ==========

class TestFullWorkflow:
    """Integration tests for complete experiment workflow."""

    def test_full_experiment_workflow(
        self, orchestrator, control_config, variant_configs
    ):
        """Test complete experiment from creation to winner determination."""
        # 1. Create experiment
        experiment = orchestrator.create_experiment(
            agent_name="test_agent",
            control_config=control_config,
            variant_configs=variant_configs,
            target_executions_per_variant=50
        )

        random.seed(42)

        # 2. Simulate 300 executions (approximately 100 per variant due to hashing)
        # This ensures all variants get at least 50 samples
        for i in range(300):
            execution_id = f"exec-{i}"
            assignment = orchestrator.assign_variant(experiment.id, execution_id)

            # Simulate execution with variant_1 performing better
            quality_scores = {
                "control": 0.70,
                "variant_0": 0.75,
                "variant_1": 0.85  # Best
            }
            base_quality = quality_scores[assignment.variant_id]

            orchestrator.record_result(
                experiment.id,
                assignment.variant_id,
                execution_id,
                quality_score=base_quality + random.uniform(-0.02, 0.02),
                speed_seconds=40.0 + random.uniform(-2, 2),
                cost_usd=0.80 + random.uniform(-0.05, 0.05),
                success=True
            )

        # 3. Verify completion (hash-based assignment should distribute roughly equally)
        assert orchestrator.is_experiment_complete(experiment.id)

        # 4. Analyze and verify winner
        winner = orchestrator.get_winner(experiment.id)
        assert winner is not None
        assert winner.variant_id == "variant_1"
        assert winner.quality_improvement > 0

        # 5. Get winning config
        winning_config = orchestrator.get_winning_config(experiment.id)
        assert winning_config is not None
        assert winning_config.inference["model"] == "gemma2:2b"

        # 6. Complete experiment
        orchestrator.complete_experiment(experiment.id, winner.variant_id)

        # Verify experiment marked as completed
        completed_experiment = orchestrator.get_experiment(experiment.id)
        assert completed_experiment.status == "completed"


# ========== Configuration Tests ==========

class TestConfigRetrieval:
    """Tests for variant configuration retrieval."""

    def test_get_variant_config_control(
        self, orchestrator, control_config, variant_configs
    ):
        """Verify returns control config for control variant."""
        experiment = orchestrator.create_experiment(
            agent_name="test_agent",
            control_config=control_config,
            variant_configs=variant_configs
        )

        config = orchestrator.get_variant_config(experiment.id, "control")

        assert config.agent_name == "test_agent"
        assert config.inference["model"] == "llama3.1:8b"

    def test_get_variant_config_variant_0(
        self, orchestrator, control_config, variant_configs
    ):
        """Verify returns correct config for variant_0."""
        experiment = orchestrator.create_experiment(
            agent_name="test_agent",
            control_config=control_config,
            variant_configs=variant_configs
        )

        config = orchestrator.get_variant_config(experiment.id, "variant_0")

        assert config.agent_name == "test_agent"
        assert config.inference["model"] == "phi3:mini"

    def test_get_variant_config_invalid_raises(
        self, orchestrator, control_config, variant_configs
    ):
        """Verify invalid variant_id raises error."""
        experiment = orchestrator.create_experiment(
            agent_name="test_agent",
            control_config=control_config,
            variant_configs=variant_configs
        )

        with pytest.raises(InvalidVariantError, match="Invalid variant_id"):
            orchestrator.get_variant_config(experiment.id, "variant_99")


# ========== Experiment Listing Tests ==========

class TestExperimentListing:
    """Tests for listing experiments."""

    def test_list_active_experiments(
        self, orchestrator, control_config, variant_configs
    ):
        """Verify listing active experiments."""
        # Create 2 experiments
        exp1 = orchestrator.create_experiment(
            agent_name="agent1",
            control_config=control_config,
            variant_configs=[variant_configs[0]]
        )
        exp2 = orchestrator.create_experiment(
            agent_name="agent2",
            control_config=control_config,
            variant_configs=[variant_configs[1]]
        )

        active = orchestrator.list_active_experiments()

        assert len(active) == 2
        exp_ids = [exp.id for exp in active]
        assert exp1.id in exp_ids
        assert exp2.id in exp_ids

    def test_list_active_experiments_filtered_by_agent(
        self, orchestrator, control_config, variant_configs
    ):
        """Verify listing experiments filtered by agent name."""
        # Create experiments for different agents
        exp1 = orchestrator.create_experiment(
            agent_name="agent1",
            control_config=SIOptimizationConfig(agent_name="agent1"),
            variant_configs=[
                SIOptimizationConfig(agent_name="agent1", inference={"model": "phi3:mini"})
            ]
        )
        exp2 = orchestrator.create_experiment(
            agent_name="agent2",
            control_config=SIOptimizationConfig(agent_name="agent2"),
            variant_configs=[
                SIOptimizationConfig(agent_name="agent2", inference={"model": "gemma2:2b"})
            ]
        )

        # List for agent1 only
        agent1_experiments = orchestrator.list_active_experiments(agent_name="agent1")

        assert len(agent1_experiments) == 1
        assert agent1_experiments[0].agent_name == "agent1"
