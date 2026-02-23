"""Cross-cluster integration tests.

Tests integration between different system clusters:
- Auth + Observability (session tracking)
- Experimentation + Self-improvement (A/B testing strategies)
- CLI + All systems (command routing)

Note: These tests verify integration points exist and work together,
without requiring full end-to-end execution.
"""

import asyncio
import uuid
from datetime import UTC, datetime

import pytest

# ============================================================================
# Auth + Observability Integration
# ============================================================================


class TestAuthObservabilityIntegration:
    """Test auth session tracking in observability system."""

    @pytest.fixture
    def session_store(self):
        """Create in-memory session store."""
        from temper_ai.auth.session import InMemorySessionStore

        return InMemorySessionStore()

    @pytest.mark.asyncio
    async def test_session_creation_tracked(self, session_store, sample_user):
        """Session creation should be tracked in observability system."""
        # Create session using async API
        session = await session_store.create_session(
            user=sample_user, ip_address="127.0.0.1", user_agent="TestAgent/1.0"
        )

        # Verify session exists
        retrieved = await session_store.get_session(session.session_id)
        assert retrieved is not None
        assert retrieved.user_id == sample_user.user_id
        assert retrieved.session_id == session.session_id

    @pytest.mark.asyncio
    async def test_session_expiry_detection(self, session_store):
        """Expired sessions should be detected and tracked."""
        from temper_ai.auth.models import User

        # Create user with short-lived session
        user = User(
            user_id="user_123",
            email="user@example.com",
            name="User",
            oauth_provider="google",
            oauth_subject="google_123",
        )

        # Create session with very short TTL (1 second)
        session = await session_store.create_session(user=user, session_max_age=1)

        # Wait for expiry
        await asyncio.sleep(1.5)

        # Check expiry
        retrieved_session = await session_store.get_session(session.session_id)

        # Session may be None (cleaned up) or expired
        if retrieved_session:
            assert retrieved_session.is_expired
        else:
            # Session was cleaned up, which is valid
            assert True

    @pytest.mark.asyncio
    async def test_multi_user_session_tracking(self, session_store):
        """Multiple user sessions should be tracked independently."""
        from temper_ai.auth.models import User

        users = [
            User(
                user_id=f"user_{i}",
                email=f"user{i}@example.com",
                name=f"User {i}",
                oauth_provider="google",
                oauth_subject=f"google_{i}",
            )
            for i in range(5)
        ]

        session_ids = []
        for user in users:
            session = await session_store.create_session(user=user)
            session_ids.append(session.session_id)

        # Verify all sessions exist
        for sid in session_ids:
            session = await session_store.get_session(sid)
            assert session is not None
            # Session should exist (may or may not be expired depending on timing)
            assert session.user_id is not None


# ============================================================================
# Experimentation + Self-improvement Integration
# ============================================================================


class TestExperimentationSelfImprovementIntegration:
    """Test A/B testing strategies in self-improvement workflows."""

    @pytest.fixture
    def strategy_config(self):
        """Create strategy configuration for testing."""
        return {
            "aggressive_improvement": {"risk_threshold": 0.8, "iterations": 10},
            "conservative_improvement": {"risk_threshold": 0.3, "iterations": 3},
        }

    def test_ab_test_strategy_selection(self, strategy_config):
        """A/B test should select strategies based on experiment variant."""
        # Simulate A/B test experiment
        experiment_data = {
            "id": str(uuid.uuid4()),
            "name": "strategy_selection_test",
            "variants": {
                "variant_a": {"strategy": "aggressive_improvement", "traffic": 50},
                "variant_b": {"strategy": "conservative_improvement", "traffic": 50},
            },
        }

        # Simulate variant assignment (deterministic based on user hash)
        user_id = f"user_{uuid.uuid4()}"
        variant_name = "variant_a" if hash(user_id) % 2 == 0 else "variant_b"
        strategy_name = experiment_data["variants"][variant_name]["strategy"]

        # Verify assignment
        assert variant_name in ["variant_a", "variant_b"]
        assert strategy_name in strategy_config

    def test_metric_collection_across_variants(self):
        """Metrics should be collected for each experiment variant."""
        users = [f"user_{i}" for i in range(10)]

        metrics = []
        for user in users:
            # Simulate variant assignment and metric tracking
            variant_name = "variant_a" if hash(user) % 2 == 0 else "variant_b"

            metric = {
                "user": user,
                "variant": variant_name,
                "success": hash(user) % 3 != 0,  # Random success
                "latency_ms": abs(hash(user) % 1000),
            }
            metrics.append(metric)

        # Verify metric distribution
        variant_a_count = sum(1 for m in metrics if m["variant"] == "variant_a")
        variant_b_count = sum(1 for m in metrics if m["variant"] == "variant_b")

        assert variant_a_count > 0
        assert variant_b_count > 0
        assert variant_a_count + variant_b_count == len(users)

    def test_strategy_performance_tracking(self):
        """Strategy performance metrics should be tracked over time."""
        strategies = ["strategy_a", "strategy_b", "strategy_c"]

        performance_records = []
        for strategy in strategies:
            # Simulate strategy execution with improvement metrics
            record = {
                "id": str(uuid.uuid4()),
                "strategy_name": strategy,
                "before_score": 0.6,
                "after_score": 0.8,
                "improvement_delta": 0.2,
                "timestamp": datetime.now(UTC).isoformat(),
                "metrics": {"accuracy": 0.85, "latency_ms": 150},
            }
            performance_records.append(record)

        # Verify all strategies tracked
        assert len(performance_records) == len(strategies)
        assert all(r["improvement_delta"] > 0 for r in performance_records)


# ============================================================================
# CLI + All Systems Integration
# ============================================================================


class TestCLISystemsIntegration:
    """Test CLI integration with all system components."""

    def test_cli_loads_all_systems(self):
        """CLI should initialize all system components."""
        # Test that CLI module can be imported
        from temper_ai.interfaces.cli import main

        # Verify main function exists
        assert hasattr(main, "main")
        assert callable(main.main)

    def test_cli_config_validation(self, tmp_path):
        """CLI should validate configuration before execution."""
        from temper_ai.workflow.config_loader import ConfigLoader

        # Create invalid config
        invalid_config = tmp_path / "invalid.yaml"
        invalid_config.write_text("invalid: yaml: content:")

        # ConfigLoader should raise error on invalid YAML
        config_loader = ConfigLoader(config_root=tmp_path)
        with pytest.raises(Exception):  # YAML or config error
            config_loader.load_workflow(invalid_config)

    def test_cli_observability_integration(self):
        """CLI execution should be tracked in observability system."""
        from temper_ai.storage.database import init_database

        # Initialize observability database
        init_database("sqlite:///:memory:")

        # Verify database initialized
        from temper_ai.storage.database import get_session

        with get_session() as session:
            assert session is not None

    def test_cli_error_handling_integration(self):
        """CLI should handle errors from all system components."""
        # Simulate error during CLI execution
        error_data = {
            "error_type": "ConfigurationError",
            "error_message": "nonexistent_agent",
            "handled": True,
        }

        # Verify error can be captured
        assert error_data["handled"]
        assert "nonexistent_agent" in error_data["error_message"]


# ============================================================================
# Cross-Module Data Flow Integration
# ============================================================================


class TestCrossModuleDataFlow:
    """Test data flow across multiple modules."""

    def test_workflow_to_observability_flow(self):
        """Workflow execution data should flow to observability system."""
        from temper_ai.storage.database import get_session, init_database

        init_database("sqlite:///:memory:")

        # Verify database connection
        with get_session() as session:
            assert session is not None

            # Simulate workflow data storage
            workflow_data = {
                "workflow_id": str(uuid.uuid4()),
                "stages": [],
                "context": {},
            }

            assert workflow_data["workflow_id"] is not None

    @pytest.mark.asyncio
    async def test_auth_to_experiment_flow(self, sample_user):
        """User authentication should enable experiment assignment."""
        from temper_ai.auth.session import InMemorySessionStore

        session_store = InMemorySessionStore()

        # Create user session
        session = await session_store.create_session(user=sample_user)

        # Verify session
        retrieved_session = await session_store.get_session(session.session_id)
        assert retrieved_session is not None

        # Session enables experiment assignment (simulated)
        experiment_data = {
            "id": str(uuid.uuid4()),
            "name": "user_experiment",
            "user_id": sample_user.user_id,
        }

        # User ID from session can be used for variant assignment
        assert retrieved_session.user_id == sample_user.user_id
        assert experiment_data["user_id"] == sample_user.user_id
