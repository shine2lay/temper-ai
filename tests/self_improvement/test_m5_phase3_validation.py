"""
M5 Phase 3 Validation: Improvement Detection and Strategy Selection

This script validates that Phase 3 components work end-to-end:
1. ImprovementDetector orchestrates problem detection and strategy selection
2. ProblemDetector identifies quality_low problems from performance degradation
3. StrategyRegistry provides applicable strategies
4. OllamaModelSelectionStrategy generates config variants
5. ImprovementProposal links problems to strategies with full context

NOTE: Uses mocked components for fast, deterministic tests.
"""
import pytest
import logging
from unittest.mock import Mock, patch
from datetime import datetime, timezone, timedelta
import tempfile
import shutil
from pathlib import Path

from src.self_improvement.detection import (
    ImprovementDetector,
    ImprovementProposal,
    ProblemDetector,
    ProblemDetectionConfig,
    PerformanceProblem,
    ProblemType,
    ProblemSeverity,
)
from src.self_improvement.performance_analyzer import PerformanceAnalyzer
from src.self_improvement.performance_comparison import compare_profiles
from src.self_improvement.data_models import AgentPerformanceProfile
from src.self_improvement.strategies.registry import StrategyRegistry
from src.self_improvement.strategies.ollama_model_strategy import OllamaModelSelectionStrategy
from src.self_improvement.strategies.strategy import AgentConfig
from src.self_improvement.model_registry import ModelRegistry
from src.observability.database import init_database, get_session
from src.observability.tracker import ExecutionTracker
from src.observability.backends import SQLObservabilityBackend

logger = logging.getLogger(__name__)


class TestM5Phase3Validation:
    """
    Validation tests for M5 Phase 3 components.

    Phase 3 Goal: Problem detection + Strategy selection working end-to-end
    """

    @pytest.fixture(autouse=True)
    def setup_database(self):
        """Initialize in-memory database for testing."""
        # Reset global database before each test
        from src.observability.database import _db_manager, _db_lock
        import src.observability.database as db_module
        with _db_lock:
            db_module._db_manager = None

        db_manager = init_database("sqlite:///:memory:")
        yield db_manager

        # Clean up after test
        with _db_lock:
            db_module._db_manager = None

    @pytest.fixture
    def temp_baseline_dir(self):
        """Create temporary directory for baseline storage."""
        temp_dir = tempfile.mkdtemp()
        yield Path(temp_dir)
        shutil.rmtree(temp_dir)

    @pytest.fixture
    def strategy_registry(self):
        """Create StrategyRegistry with OllamaModelSelectionStrategy."""
        registry = StrategyRegistry()
        model_registry = ModelRegistry()
        strategy = OllamaModelSelectionStrategy(model_registry)
        registry.register(strategy)
        return registry

    def test_phase3_components_exist(self):
        """Verify all Phase 3 components can be imported."""
        # Problem detection
        from src.self_improvement.detection import (
            ImprovementDetector,
            ProblemDetector,
            ImprovementProposal,
        )

        # Strategy components
        from src.self_improvement.strategies.registry import StrategyRegistry
        from src.self_improvement.strategies.ollama_model_strategy import (
            OllamaModelSelectionStrategy,
        )

        # All imports successful
        assert True
        logger.info("✓ All Phase 3 components exist and can be imported")

    def test_improvement_detection_workflow(self, temp_baseline_dir, strategy_registry):
        """
        Test full Phase 3 workflow:
        1. Create baseline and current performance with quality degradation
        2. Run ImprovementDetector
        3. Verify quality_low problem detected
        4. Verify strategy selected
        5. Verify proposals generated
        """
        with get_session() as session:
            # Create analyzer with temp storage
            analyzer = PerformanceAnalyzer(
                session=session,
                baseline_storage_path=temp_baseline_dir,
            )

            # Create mock baseline profile (good quality)
            baseline_end = datetime.now(timezone.utc) - timedelta(days=7)
            baseline_start = baseline_end - timedelta(days=30)

            baseline = AgentPerformanceProfile(
                agent_name="test_agent",
                window_start=baseline_start,
                window_end=baseline_end,
                total_executions=100,
                metrics={
                    "success_rate": {"mean": 0.85},  # Good quality
                    "duration_seconds": {"mean": 10.0},
                    "cost_usd": {"mean": 0.50},
                },
            )

            # Store baseline
            analyzer.store_baseline("test_agent", baseline)

            # Create mock current profile (degraded quality)
            current_end = datetime.now(timezone.utc)
            current_start = current_end - timedelta(days=7)

            current = AgentPerformanceProfile(
                agent_name="test_agent",
                window_start=current_start,
                window_end=current_end,
                total_executions=100,
                metrics={
                    "success_rate": {"mean": 0.68},  # Degraded: 0.85 → 0.68 (-20%)
                    "duration_seconds": {"mean": 10.5},
                    "cost_usd": {"mean": 0.52},
                },
            )

            # Create ImprovementDetector with mocked analyzer
            detector = ImprovementDetector(
                session=session,
                strategy_registry=strategy_registry,
                baseline_storage_path=temp_baseline_dir,
            )

            # Mock analyzer to return our test profiles
            detector.analyzer.get_baseline = Mock(return_value=baseline)
            detector.analyzer.analyze_agent_performance = Mock(return_value=current)

            # Run improvement detection
            proposals = detector.detect_improvements("test_agent", min_executions=50)

            # Verify proposals generated
            assert len(proposals) > 0, "Expected at least one improvement proposal"
            logger.info(f"Generated {len(proposals)} proposals")

            # Verify first proposal
            proposal = proposals[0]
            assert isinstance(proposal, ImprovementProposal)
            assert proposal.agent_name == "test_agent"

            # Verify problem is quality_low
            assert proposal.problem.problem_type == ProblemType.QUALITY_LOW
            logger.info(f"✓ Detected problem: {proposal.problem.get_summary()}")

            # Verify strategy is ollama_model_selection
            assert proposal.strategy_name == "ollama_model_selection"
            logger.info(f"✓ Selected strategy: {proposal.strategy_name}")

            # Verify proposal has priority
            assert proposal.priority in (0, 1, 2, 3)
            logger.info(f"✓ Proposal priority: {proposal.priority}")

            # Verify embedded profiles
            assert proposal.baseline_profile is not None
            assert proposal.current_profile is not None
            assert proposal.baseline_profile.total_executions == 100
            assert proposal.current_profile.total_executions == 100

            logger.info("✓ Phase 3 improvement detection workflow validated")

    def test_strategy_variant_generation(self):
        """Test that OllamaModelSelectionStrategy generates variants."""
        model_registry = ModelRegistry()
        strategy = OllamaModelSelectionStrategy(model_registry)

        # Create current config
        current_config = AgentConfig(
            agent_name="test_agent",
            inference={"model": "phi3:mini"},
            prompt={"template": "Extract product information"},
        )

        # Generate variants
        variants = strategy.generate_variants(current_config, patterns=[])

        # Verify 2-4 variants generated
        assert 2 <= len(variants) <= 4, f"Expected 2-4 variants, got {len(variants)}"
        logger.info(f"✓ Strategy generated {len(variants)} variants")

        # Verify variants have different models
        models = [v.inference.get("model") for v in variants]
        assert len(set(models)) == len(models), "Variants should have unique models"
        logger.info(f"✓ Variants use different models: {models}")

        # Verify strategy metadata added
        for variant in variants:
            assert variant.extra_metadata.get("strategy") == "ollama_model_selection"
            assert "model_size" in variant.extra_metadata
            assert "expected_quality" in variant.extra_metadata

        logger.info("✓ Strategy variant generation validated")

    def test_problem_detector_integration(self, temp_baseline_dir):
        """Test ProblemDetector identifies quality degradation."""
        # Create baseline and current profiles
        baseline_end = datetime.now(timezone.utc) - timedelta(days=7)
        baseline_start = baseline_end - timedelta(days=30)

        baseline = AgentPerformanceProfile(
            agent_name="test_agent",
            window_start=baseline_start,
            window_end=baseline_end,
            total_executions=100,
            metrics={
                "success_rate": {"mean": 0.90},
            },
        )

        current_end = datetime.now(timezone.utc)
        current_start = current_end - timedelta(days=7)

        current = AgentPerformanceProfile(
            agent_name="test_agent",
            window_start=current_start,
            window_end=current_end,
            total_executions=100,
            metrics={
                "success_rate": {"mean": 0.70},  # 22% degradation
            },
        )

        # Compare profiles
        comparison = compare_profiles(baseline, current)

        # Detect problems
        detector = ProblemDetector()
        problems = detector.detect_problems(comparison, min_executions=50)

        # Verify quality problem detected
        assert len(problems) > 0, "Expected at least one problem"
        quality_problems = [p for p in problems if p.problem_type == ProblemType.QUALITY_LOW]
        assert len(quality_problems) > 0, "Expected quality_low problem"

        problem = quality_problems[0]
        assert problem.metric_name == "success_rate"
        assert problem.severity in (ProblemSeverity.MEDIUM, ProblemSeverity.HIGH)

        logger.info(f"✓ ProblemDetector identified: {problem.get_summary()}")

    def test_strategy_applicability(self):
        """Test that OllamaModelSelectionStrategy is applicable to quality problems."""
        model_registry = ModelRegistry()
        strategy = OllamaModelSelectionStrategy(model_registry)

        # Verify strategy is applicable to quality problems
        assert strategy.is_applicable("quality_low"), "Should apply to quality_low"
        assert strategy.is_applicable("cost_high"), "Should apply to cost_high"
        assert strategy.is_applicable("speed_low"), "Should apply to speed_low"

        logger.info("✓ Strategy applicability validated")

    def test_proposal_serialization(self):
        """Test that proposals can be serialized for storage."""
        # Create test profiles
        window_end = datetime.now(timezone.utc)
        window_start = window_end - timedelta(days=7)

        baseline = AgentPerformanceProfile(
            agent_name="test_agent",
            window_start=window_start,
            window_end=window_end,
            total_executions=100,
            metrics={"success_rate": {"mean": 0.85}},
        )

        current = AgentPerformanceProfile(
            agent_name="test_agent",
            window_start=window_start,
            window_end=window_end,
            total_executions=100,
            metrics={"success_rate": {"mean": 0.70}},
        )

        # Create problem
        problem = PerformanceProblem(
            problem_type=ProblemType.QUALITY_LOW,
            severity=ProblemSeverity.MEDIUM,
            agent_name="test_agent",
            metric_name="success_rate",
            baseline_value=0.85,
            current_value=0.70,
            degradation_pct=-0.176,
            threshold_used=0.10,
        )

        # Create proposal
        proposal = ImprovementProposal(
            proposal_id="test-id",
            agent_name="test_agent",
            problem=problem,
            strategy_name="ollama_model_selection",
            estimated_impact=0.15,
            baseline_profile=baseline,
            current_profile=current,
            priority=2,
        )

        # Serialize
        proposal_dict = proposal.to_dict()
        assert isinstance(proposal_dict, dict)
        assert proposal_dict["proposal_id"] == "test-id"
        assert proposal_dict["strategy_name"] == "ollama_model_selection"

        # Deserialize
        restored = ImprovementProposal.from_dict(proposal_dict)
        assert restored.proposal_id == proposal.proposal_id
        assert restored.strategy_name == proposal.strategy_name
        assert restored.problem.problem_type == proposal.problem.problem_type

        logger.info("✓ Proposal serialization validated")


if __name__ == "__main__":
    """Run validation standalone for debugging."""
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # Run with pytest
    sys.exit(pytest.main([__file__, "-v", "-s"]))
