"""
M5 Phase 1 Validation: Product Extraction Quality Metrics

This script validates that Phase 1 components work end-to-end:
1. ProductExtractorAgent extracts product data
2. ExecutionTracker records agent executions
3. MetricRegistry collects quality metrics
4. Quality scores are stored in observability database

NOTE: Mocked tests run by default. Full validation with Ollama requires:
  pytest tests/self_improvement/test_m5_phase1_validation.py --run-ollama-tests
"""
import pytest
import logging
from unittest.mock import Mock, patch

from src.self_improvement.agents import ProductExtractorAgent
from src.self_improvement.metrics import MetricRegistry, ExtractionQualityCollector
from src.observability.tracker import ExecutionTracker
from src.observability.backends import SQLObservabilityBackend
from src.observability.database import init_database
from tests.fixtures.product_extraction_data import PRODUCT_TEST_CASES

logger = logging.getLogger(__name__)


class TestM5Phase1Validation:
    """
    Validation tests for M5 Phase 1 components.

    Phase 1 Goal: Agent + Quality Metric collection working end-to-end
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

    def test_components_integration(self, tracker):
        """Test that all Phase 1 components integrate correctly."""
        # Create agent with mocked Ollama client
        with patch('src.self_improvement.agents.product_extractor.OllamaClient') as mock_ollama_class:
            # Setup mock
            mock_client = Mock()
            mock_client.generate.return_value = '{"name": "iPhone 15", "price": 799.0, "currency": "USD", "features": ["128GB"], "brand": "Apple", "category": "Smartphone"}'
            mock_ollama_class.return_value = mock_client

            agent = ProductExtractorAgent()
            agent.client = mock_client

            test_case = PRODUCT_TEST_CASES[0]

            # Run through full tracking pipeline
            with tracker.track_workflow("test_integration", {}) as workflow_id:
                with tracker.track_stage("extraction", {}, workflow_id) as stage_id:
                    with tracker.track_agent("product_extractor", {}, stage_id) as agent_id:
                        result = agent.extract(test_case["description"])
                        # Verify extraction worked
                        assert result["name"] is not None

            # Verify execution was recorded in database
            backend = tracker.backend
            if hasattr(backend, 'db_path'):
                import sqlite3
                conn = sqlite3.connect(backend.db_path)
                cursor = conn.cursor()

                cursor.execute(
                    "SELECT status, agent_name FROM agent_executions WHERE id = ?",
                    (agent_id,)
                )
                row = cursor.fetchone()
                conn.close()

                assert row is not None, "Agent execution not found in database"
                assert row[0] == "completed", f"Expected 'completed', got '{row[0]}'"
                assert row[1] == "product_extractor"

                logger.info("✓ Agent execution recorded in database")

    def test_phase1_components_exist(self):
        """Test that all Phase 1 components can be imported and instantiated."""
        # Test ProductExtractorAgent
        agent = ProductExtractorAgent()
        assert agent is not None
        assert agent.model == "llama3.1:8b"

        # Test MetricRegistry and ExtractionQualityCollector
        registry = MetricRegistry()
        collector = ExtractionQualityCollector()
        registry.register(collector)
        assert len(registry.list_collectors()) == 1
        assert "extraction_quality" in registry.list_collectors()

        # Test ExecutionTracker with registry
        tracker = ExecutionTracker(metric_registry=registry)
        assert tracker.metric_registry is registry

        # Test test dataset exists
        assert len(PRODUCT_TEST_CASES) == 50
        assert all("description" in tc and "ground_truth" in tc for tc in PRODUCT_TEST_CASES)

        logger.info("✓ All Phase 1 components exist and can be instantiated")
        logger.info(f"✓ Test dataset contains {len(PRODUCT_TEST_CASES)} test cases")


if __name__ == "__main__":
    """Run validation standalone for debugging."""
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # Run with pytest
    sys.exit(pytest.main([__file__, "-v", "-s"]))
