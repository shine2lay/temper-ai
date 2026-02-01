"""
M5 Phase 2 Validation: Performance Analysis and Baseline Storage

This script validates that Phase 2 components work end-to-end:
1. Run 100 agent executions (reusing Phase 1 infrastructure)
2. PerformanceAnalyzer analyzes agent performance over time window
3. Baseline storage persists performance profile
4. Performance comparison between current and baseline works

NOTE: Mocked tests run by default for speed.
"""
import pytest
import logging
from unittest.mock import Mock, patch
from datetime import datetime, timezone, timedelta
import tempfile
import shutil
from pathlib import Path

from src.self_improvement.agents import ProductExtractorAgent
from src.self_improvement.metrics import MetricRegistry, ExtractionQualityCollector
from src.self_improvement.performance_analyzer import PerformanceAnalyzer
from src.self_improvement.performance_comparison import compare_profiles
from src.observability.tracker import ExecutionTracker
from src.observability.backends import SQLObservabilityBackend
from src.observability.database import init_database, get_session
from tests.fixtures.product_extraction_data import PRODUCT_TEST_CASES

logger = logging.getLogger(__name__)


class TestM5Phase2Validation:
    """
    Validation tests for M5 Phase 2 components.

    Phase 2 Goal: Performance analysis and baseline storage working end-to-end
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
    def metric_registry(self):
        """Create MetricRegistry with ExtractionQualityCollector."""
        registry = MetricRegistry()
        registry.register(ExtractionQualityCollector())
        return registry

    @pytest.fixture
    def tracker(self, metric_registry):
        """Create ExecutionTracker with metric collection enabled."""
        backend = SQLObservabilityBackend()
        tracker = ExecutionTracker(
            backend=backend,
            metric_registry=metric_registry
        )
        return tracker

    def test_phase2_components_exist(self):
        """Verify all Phase 2 components can be imported."""
        # Performance analyzer
        from src.self_improvement.performance_analyzer import PerformanceAnalyzer

        # Performance comparison
        from src.self_improvement.performance_comparison import compare_profiles

        # Data models
        from src.self_improvement.data_models import AgentPerformanceProfile

        # All imports successful
        assert True

    def test_performance_analysis_workflow(self, tracker, temp_baseline_dir):
        """
        Test full Phase 2 workflow:
        1. Run 100 executions
        2. Analyze performance
        3. Store baseline
        4. Compare performance
        """
        # STEP 1: Run 100 mock executions
        with patch('src.self_improvement.agents.product_extractor.OllamaClient') as mock_ollama_class:
            # Setup mock Ollama client
            mock_client = Mock()
            mock_client.generate.return_value = '''
            {
                "name": "Test Product",
                "price": 99.99,
                "currency": "USD",
                "features": ["Feature 1", "Feature 2"],
                "brand": "TestBrand",
                "category": "Electronics"
            }
            '''
            mock_ollama_class.return_value = mock_client

            agent = ProductExtractorAgent()
            agent.client = mock_client

            # Run 100 executions
            execution_ids = []
            for i in range(100):
                test_case = PRODUCT_TEST_CASES[i % len(PRODUCT_TEST_CASES)]

                with tracker.track_workflow(f"test_workflow_{i}", {}) as workflow_id:
                    with tracker.track_stage("extraction", {}, workflow_id) as stage_id:
                        with tracker.track_agent("product_extractor", {}, stage_id) as agent_id:
                            result = agent.extract(test_case["description"])
                            execution_ids.append(agent_id)

                            # Verify extraction worked
                            assert result is not None
                            assert "name" in result

        logger.info(f"Completed {len(execution_ids)} executions")

        # STEP 2: Analyze performance using PerformanceAnalyzer
        with get_session() as session:
            analyzer = PerformanceAnalyzer(
                session=session,
                baseline_storage_path=temp_baseline_dir
            )

            # Analyze recent performance (all 100 executions should be included)
            profile = analyzer.analyze_agent_performance(
                "product_extractor",
                window_hours=1,  # Last 1 hour
                min_executions=10
            )

            # Verify profile was created
            assert profile is not None
            assert profile.agent_name == "product_extractor"
            assert profile.total_executions >= 100

            logger.info(
                f"Analyzed performance: {profile.total_executions} executions, "
                f"success_rate: {profile.get_metric('success_rate', 'mean')}"
            )

            # STEP 3: Store baseline
            stored_profile = analyzer.store_baseline("product_extractor", profile)
            assert stored_profile.profile_id is not None

            logger.info(f"Stored baseline with profile_id: {stored_profile.profile_id}")

            # STEP 4: Retrieve baseline and verify
            retrieved_baseline = analyzer.retrieve_baseline("product_extractor")
            assert retrieved_baseline is not None
            assert retrieved_baseline.agent_name == "product_extractor"
            assert retrieved_baseline.total_executions == profile.total_executions

            # STEP 5: Compare current performance vs baseline
            comparison = compare_profiles(retrieved_baseline, profile)
            assert comparison is not None

            logger.info(f"Performance comparison: {comparison}")

            # Verify comparison results make sense
            # Since we're comparing the same profile, deltas should be near 0
            success_rate_change = comparison.get_metric_change("success_rate", "mean")
            if success_rate_change is not None:
                assert abs(success_rate_change.absolute_change) < 0.01  # Near zero

    def test_baseline_persistence(self, tracker, temp_baseline_dir):
        """Test that baselines persist across analyzer instances."""
        # Run a few executions
        with patch('src.self_improvement.agents.product_extractor.OllamaClient') as mock_ollama_class:
            mock_client = Mock()
            mock_client.generate.return_value = '{"name": "Test", "price": 10.0, "currency": "USD", "features": [], "brand": "Test", "category": "Test"}'
            mock_ollama_class.return_value = mock_client

            agent = ProductExtractorAgent()
            agent.client = mock_client

            for i in range(20):
                with tracker.track_workflow(f"workflow_{i}", {}) as wf_id:
                    with tracker.track_stage("stage", {}, wf_id) as st_id:
                        with tracker.track_agent("test_agent", {}, st_id) as ag_id:
                            agent.extract("Test product")

        # Create analyzer 1 and store baseline
        with get_session() as session:
            analyzer1 = PerformanceAnalyzer(
                session=session,
                baseline_storage_path=temp_baseline_dir
            )

            profile = analyzer1.analyze_agent_performance(
                "test_agent",
                window_hours=1,
                min_executions=5
            )

            analyzer1.store_baseline("test_agent", profile)

        # Create analyzer 2 (new instance) and retrieve baseline
        with get_session() as session:
            analyzer2 = PerformanceAnalyzer(
                session=session,
                baseline_storage_path=temp_baseline_dir
            )

            # Should retrieve baseline stored by analyzer1
            baseline = analyzer2.retrieve_baseline("test_agent")
            assert baseline is not None
            assert baseline.agent_name == "test_agent"

        logger.info("Baseline persistence verified across analyzer instances")

    def test_insufficient_data_handling(self, temp_baseline_dir):
        """Test that analyzer handles insufficient data gracefully."""
        # No executions in database
        with get_session() as session:
            analyzer = PerformanceAnalyzer(
                session=session,
                baseline_storage_path=temp_baseline_dir
            )

            # Should return None when no baseline exists
            baseline = analyzer.get_baseline("nonexistent_agent")
            assert baseline is None

        logger.info("Insufficient data handling verified")
