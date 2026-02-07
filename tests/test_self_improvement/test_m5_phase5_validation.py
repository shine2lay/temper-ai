"""
Comprehensive Phase 5 validation tests for M5 deployment and rollback.

Tests the complete M5 Phase 5 deployment workflow:
1. Deploy winning configuration from experiment
2. Run 50 extractions with realistic metrics
3. Verify improvement is sustained (no regression)
4. Test automatic rollback on regression detection

Validates:
- ConfigDeployer: Safe config deployment with rollback tracking
- RollbackMonitor: Automated regression detection and rollback
- End-to-end M5 self-improvement loop (Phase 1-5)
"""

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

# Add .claude-coord to path for coordination Database
coord_path = Path(__file__).parent.parent.parent / ".claude-coord"
sys.path.insert(0, str(coord_path))
from coord_service.database import Database as CoordDatabase

from src.observability.database import init_database, reset_database
from src.observability.models import AgentExecution
from src.self_improvement.data_models import (
    SIOptimizationConfig,
    utcnow,
)
from src.self_improvement.deployment.deployer import ConfigDeployer
from src.self_improvement.deployment.rollback_monitor import (
    RegressionThresholds,
    RollbackMonitor,
)
from src.self_improvement.performance_analyzer import PerformanceAnalyzer


@pytest.fixture
def coord_db():
    """Create in-memory coordination database."""
    db_instance = CoordDatabase(db_path=":memory:")
    db_instance.initialize()
    return db_instance


@pytest.fixture
def obs_session():
    """Create in-memory observability database session."""
    reset_database()
    db_manager = init_database("sqlite:///:memory:")
    with db_manager.session() as session:
        yield session
    reset_database()


@pytest.fixture
def deployer(coord_db):
    """Create ConfigDeployer instance."""
    return ConfigDeployer(coord_db)


@pytest.fixture
def analyzer(obs_session):
    """Create PerformanceAnalyzer instance."""
    return PerformanceAnalyzer(obs_session)


@pytest.fixture
def monitor(analyzer, deployer):
    """Create RollbackMonitor with test thresholds."""
    thresholds = RegressionThresholds(
        quality_drop_pct=10.0,  # 10% quality drop triggers rollback
        cost_increase_pct=20.0,  # 20% cost increase triggers rollback
        speed_increase_pct=30.0,  # 30% speed increase triggers rollback
        min_executions=20,  # Need 20 executions before checking
    )
    return RollbackMonitor(analyzer, deployer, thresholds)


def create_execution(
    session,
    agent_name: str,
    quality: float,
    cost: float,
    duration: float,
    timestamp: datetime,
):
    """Helper to create execution record in observability database."""
    execution = AgentExecution(
        agent_name=agent_name,
        task_id="task-validation-001",
        user_id="test_user",
        session_id="test_session",
        started_at=timestamp - timedelta(seconds=duration),
        completed_at=timestamp,
        status="completed",
        result_data={"quality_score": quality},
        cost_usd=cost,
        model_name="test-model",
        prompt_tokens=100,
        completion_tokens=50,
        total_tokens=150,
    )
    session.add(execution)
    session.commit()


class TestPhase5DeploymentValidation:
    """Test complete Phase 5 deployment and monitoring workflow."""

    def test_deploy_winner_config(self, deployer):
        """
        Test deploying winning configuration from experiment.

        Validates:
        - Deploy new config with rollback tracking
        - Store deployment history
        - Update agent config atomically
        """
        # Create baseline config
        baseline_config = SIOptimizationConfig(
            agent_name="code_reviewer",
            inference={"model": "claude-3-5-sonnet-20241022", "temperature": 0.0},
            prompt={"system": "Review code for quality issues."},
        )

        # Create winning config (better model)
        winner_config = SIOptimizationConfig(
            agent_name="code_reviewer",
            inference={"model": "gemma2:2b", "temperature": 0.7},
            prompt={
                "system": "Review code with focus on security and performance."
            },
        )

        # Deploy winner
        deployer.deploy(
            agent_name="code_reviewer",
            new_config=winner_config,
            experiment_id="exp-123",
        )

        # Verify deployment stored
        deployment = deployer.get_last_deployment("code_reviewer")
        assert deployment is not None
        assert deployment.agent_name == "code_reviewer"
        assert deployment.experiment_id == "exp-123"
        assert deployment.new_config.inference["model"] == "gemma2:2b"
        assert deployment.rollback_at is None

        # Verify config updated
        current_config = deployer.get_agent_config("code_reviewer")
        assert current_config.inference["model"] == "gemma2:2b"
        assert current_config.prompt["system"] == "Review code with focus on security and performance."

    def test_run_50_extractions_sustained_improvement(self, obs_session, coord_db, deployer, monitor):
        """
        Test 50 post-deployment extractions with sustained improvement.

        Validates:
        - Create baseline executions (before deployment)
        - Deploy winning config
        - Run 50 extractions with improved metrics
        - Monitor detects NO regression (improvement sustained)
        """
        agent_name = "code_reviewer"
        now = utcnow()

        # 1. Create baseline executions (24 hours before deployment)
        # Baseline: quality=0.7, cost=$0.02, duration=5s
        baseline_start = now - timedelta(hours=48)
        for i in range(30):
            timestamp = baseline_start + timedelta(minutes=i * 2)
            create_execution(
                obs_session, agent_name,
                quality=0.70,  # Baseline quality
                cost=0.02,     # Baseline cost
                duration=5.0,  # Baseline speed
                timestamp=timestamp,
            )

        # 2. Deploy winning config
        winner_config = SIOptimizationConfig(
            agent_name=agent_name,
            inference={"model": "gemma2:2b", "temperature": 0.7},
            prompt={"system": "Improved review prompt"},
        )

        # Deploy 24 hours ago (to have baseline data before deployment)
        deployment_time = now - timedelta(hours=24)
        with coord_db.transaction() as conn:
            deployment_id = "deploy-test-123"
            baseline_config = SIOptimizationConfig(agent_name=agent_name)
            conn.execute(
                """
                INSERT INTO config_deployments
                (id, agent_name, previous_config, new_config, experiment_id,
                 deployed_at, deployed_by, rollback_at, rollback_reason)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    deployment_id,
                    agent_name,
                    json.dumps(baseline_config.to_dict()),
                    json.dumps(winner_config.to_dict()),
                    "exp-winner-123",
                    deployment_time.isoformat(),
                    "m5_system",
                    None,
                    None,
                ),
            )

        # 3. Run 50 post-deployment extractions with improved metrics
        # Winner: quality=0.85 (+21%), cost=$0.015 (-25%), duration=4s (-20%)
        for i in range(50):
            timestamp = deployment_time + timedelta(minutes=i * 10)
            create_execution(
                obs_session, agent_name,
                quality=0.85,   # +21% improvement
                cost=0.015,     # -25% cost reduction
                duration=4.0,   # -20% speed improvement
                timestamp=timestamp,
            )

        # 4. Monitor for regression
        result = monitor.check_for_regression(agent_name, window_hours=24)

        # Verify NO regression detected (improvement sustained)
        assert result["regression_detected"] is False
        assert result["rolled_back"] is False
        assert result["reason"] is None

        # Verify metrics improved
        current_quality = result["current_metrics"].get("quality_score", {}).get("mean", 0)
        baseline_quality = result["baseline_metrics"].get("quality_score", {}).get("mean", 1)
        assert current_quality > baseline_quality  # Quality improved

    def test_automatic_rollback_on_quality_regression(self, obs_session, coord_db, deployer, monitor):
        """
        Test automatic rollback when quality regresses.

        Validates:
        - Deploy config
        - Run extractions with quality regression
        - Monitor detects regression (quality drop > 10%)
        - Automatic rollback triggered
        - Previous config restored
        """
        agent_name = "code_reviewer"
        now = utcnow()

        # 1. Create baseline executions (quality=0.8)
        baseline_start = now - timedelta(hours=48)
        for i in range(30):
            timestamp = baseline_start + timedelta(minutes=i * 2)
            create_execution(
                obs_session, agent_name,
                quality=0.80,
                cost=0.02,
                duration=5.0,
                timestamp=timestamp,
            )

        # 2. Deploy new config (24 hours ago)
        baseline_config = SIOptimizationConfig(
            agent_name=agent_name,
            inference={"model": "claude-3-5-sonnet-20241022"},
            prompt={"system": "Original prompt"},
        )
        new_config = SIOptimizationConfig(
            agent_name=agent_name,
            inference={"model": "bad-model"},
            prompt={"system": "New prompt"},
        )

        deployment_time = now - timedelta(hours=24)
        with coord_db.transaction() as conn:
            deployment_id = "deploy-regression-123"
            conn.execute(
                """
                INSERT INTO config_deployments
                (id, agent_name, previous_config, new_config, experiment_id,
                 deployed_at, deployed_by, rollback_at, rollback_reason)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    deployment_id,
                    agent_name,
                    json.dumps(baseline_config.to_dict()),
                    json.dumps(new_config.to_dict()),
                    "exp-regression-123",
                    deployment_time.isoformat(),
                    "m5_system",
                    None,
                    None,
                ),
            )

        # 3. Run 25 extractions with QUALITY REGRESSION
        # New quality: 0.68 (15% drop from 0.80)
        for i in range(25):
            timestamp = deployment_time + timedelta(minutes=i * 10)
            create_execution(
                obs_session, agent_name,
                quality=0.68,   # 15% quality drop (triggers rollback)
                cost=0.02,
                duration=5.0,
                timestamp=timestamp,
            )

        # 4. Monitor for regression
        result = monitor.check_for_regression(agent_name, window_hours=24)

        # Verify regression detected
        assert result["regression_detected"] is True
        assert result["rolled_back"] is True
        assert "Quality dropped" in result["reason"]
        assert "15.0%" in result["reason"]

        # Verify deployment marked as rolled back
        deployment = deployer.get_last_deployment(agent_name)
        assert deployment.rollback_at is not None
        assert "Quality dropped" in deployment.rollback_reason

        # Verify previous config restored
        current_config = deployer.get_agent_config(agent_name)
        assert current_config.inference["model"] == "claude-3-5-sonnet-20241022"

    def test_automatic_rollback_on_cost_regression(self, obs_session, coord_db, deployer, monitor):
        """
        Test automatic rollback when cost increases beyond threshold.

        Validates:
        - Deploy config
        - Run extractions with cost regression (>20% increase)
        - Monitor detects cost regression
        - Automatic rollback triggered
        """
        agent_name = "code_reviewer"
        now = utcnow()

        # 1. Create baseline executions (cost=$0.02)
        baseline_start = now - timedelta(hours=48)
        for i in range(30):
            timestamp = baseline_start + timedelta(minutes=i * 2)
            create_execution(
                obs_session, agent_name,
                quality=0.80,
                cost=0.02,      # Baseline cost
                duration=5.0,
                timestamp=timestamp,
            )

        # 2. Deploy new config
        baseline_config = SIOptimizationConfig(agent_name=agent_name, inference={"model": "cheap"})
        new_config = SIOptimizationConfig(agent_name=agent_name, inference={"model": "expensive"})

        deployment_time = now - timedelta(hours=24)
        with coord_db.transaction() as conn:
            conn.execute(
                """
                INSERT INTO config_deployments
                (id, agent_name, previous_config, new_config, experiment_id,
                 deployed_at, deployed_by, rollback_at, rollback_reason)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "deploy-cost-123",
                    agent_name,
                    json.dumps(baseline_config.to_dict()),
                    json.dumps(new_config.to_dict()),
                    "exp-cost-123",
                    deployment_time.isoformat(),
                    "m5_system",
                    None,
                    None,
                ),
            )

        # 3. Run 25 extractions with COST REGRESSION
        # New cost: $0.026 (30% increase from $0.02, exceeds 20% threshold)
        for i in range(25):
            timestamp = deployment_time + timedelta(minutes=i * 10)
            create_execution(
                obs_session, agent_name,
                quality=0.80,
                cost=0.026,     # 30% cost increase (triggers rollback)
                duration=5.0,
                timestamp=timestamp,
            )

        # 4. Monitor for regression
        result = monitor.check_for_regression(agent_name, window_hours=24)

        # Verify cost regression detected and rollback triggered
        assert result["regression_detected"] is True
        assert result["rolled_back"] is True
        assert "Cost increased" in result["reason"]
        assert "30.0%" in result["reason"]

    def test_no_rollback_when_insufficient_executions(self, obs_session, coord_db, deployer, monitor):
        """
        Test no rollback when not enough executions collected.

        Validates:
        - Deploy config
        - Run only 15 extractions (< min_executions=20)
        - Monitor skips check (insufficient data)
        - No rollback triggered
        """
        agent_name = "code_reviewer"
        now = utcnow()

        # 1. Create baseline
        baseline_start = now - timedelta(hours=48)
        for i in range(30):
            timestamp = baseline_start + timedelta(minutes=i * 2)
            create_execution(obs_session, agent_name, 0.80, 0.02, 5.0, timestamp)

        # 2. Deploy config
        baseline_config = SIOptimizationConfig(agent_name=agent_name)
        new_config = SIOptimizationConfig(agent_name=agent_name, inference={"model": "new"})

        deployment_time = now - timedelta(hours=24)
        with coord_db.transaction() as conn:
            conn.execute(
                """
                INSERT INTO config_deployments
                (id, agent_name, previous_config, new_config, experiment_id,
                 deployed_at, deployed_by, rollback_at, rollback_reason)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "deploy-insufficient-123",
                    agent_name,
                    json.dumps(baseline_config.to_dict()),
                    json.dumps(new_config.to_dict()),
                    "exp-123",
                    deployment_time.isoformat(),
                    "m5_system",
                    None,
                    None,
                ),
            )

        # 3. Run only 15 extractions (below threshold)
        for i in range(15):
            timestamp = deployment_time + timedelta(minutes=i * 10)
            create_execution(
                obs_session, agent_name,
                quality=0.60,  # Even with bad quality...
                cost=0.02,
                duration=5.0,
                timestamp=timestamp,
            )

        # 4. Monitor skips check due to insufficient data
        result = monitor.check_for_regression(agent_name, window_hours=24)

        assert result["regression_detected"] is False
        assert result["rolled_back"] is False
        assert result["current_metrics"] == {}  # No metrics analyzed


class TestPhase5EdgeCases:
    """Test edge cases and error conditions."""

    def test_rollback_without_deployment_history(self, deployer):
        """Test rollback fails gracefully when no deployment history."""
        with pytest.raises(ValueError, match="No deployment history"):
            deployer.rollback("nonexistent_agent")

    def test_rollback_already_rolled_back(self, coord_db, deployer):
        """Test rollback fails when already rolled back."""
        agent_name = "test_agent"

        # Create and rollback deployment
        config = SIOptimizationConfig(agent_name=agent_name)
        deployer.deploy(agent_name, config)
        deployer.rollback(agent_name, "First rollback")

        # Try to rollback again
        with pytest.raises(ValueError, match="Already rolled back"):
            deployer.rollback(agent_name)

    def test_monitor_no_baseline(self, monitor):
        """Test monitor handles missing baseline gracefully."""
        result = monitor.check_for_regression("agent_without_history")

        assert result["regression_detected"] is False
        assert result["rolled_back"] is False

    def test_deploy_invalid_config(self, deployer):
        """Test deploy rejects invalid config."""
        # Create config missing required fields
        class InvalidConfig:
            agent_name = "test"

        with pytest.raises(ValueError, match="Invalid config"):
            deployer.deploy("test", InvalidConfig())
