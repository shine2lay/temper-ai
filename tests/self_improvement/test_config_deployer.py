"""
Tests for ConfigDeployer (deployment and rollback).

Test coverage:
- Deploy with valid config
- Deploy with invalid config (missing required fields)
- Rollback after deployment
- Rollback with no history
- Double rollback
- Deployment records stored correctly
- Thread-safety of config updates
"""

import json
import pytest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch

from src.self_improvement.data_models import OptimizationConfig, ConfigDeployment, utcnow
from src.self_improvement.deployment.deployer import ConfigDeployer, generate_id


@pytest.fixture
def mock_db():
    """Create mock database."""
    db = Mock()
    db.transaction = MagicMock()
    db.query = Mock(return_value=[])
    return db


@pytest.fixture
def mock_db_with_transaction():
    """Create mock database with transaction context manager."""
    db = Mock()

    # Mock connection
    conn = Mock()

    # Mock transaction context manager
    transaction_cm = MagicMock()
    transaction_cm.__enter__ = Mock(return_value=conn)
    transaction_cm.__exit__ = Mock(return_value=False)

    db.transaction = Mock(return_value=transaction_cm)
    db.query = Mock(return_value=[])

    return db, conn


@pytest.fixture
def deployer(mock_db):
    """Create deployer instance."""
    return ConfigDeployer(mock_db)


@pytest.fixture
def valid_config():
    """Create valid agent config."""
    return OptimizationConfig(
        agent_name="test_agent",
        inference={"model": "llama3.1:8b", "temperature": 0.7},
        prompt={"template": "You are a helpful assistant"},
    )


@pytest.fixture
def invalid_config():
    """Create invalid config (missing required fields)."""
    config = OptimizationConfig(agent_name="test_agent")
    # Remove required fields
    delattr(config, "inference")
    return config


class TestConfigValidation:
    """Test configuration validation."""

    def test_validate_valid_config(self, deployer, valid_config):
        """Test validation succeeds for valid config."""
        assert deployer._validate_config(valid_config) is True

    def test_validate_invalid_config_missing_inference(self, deployer):
        """Test validation fails when inference is missing."""
        config = OptimizationConfig(agent_name="test", prompt={})
        delattr(config, "inference")
        assert deployer._validate_config(config) is False

    def test_validate_invalid_config_missing_prompt(self, deployer):
        """Test validation fails when prompt is missing."""
        config = OptimizationConfig(agent_name="test", inference={})
        delattr(config, "prompt")
        assert deployer._validate_config(config) is False


class TestDeploy:
    """Test deployment functionality."""

    def test_deploy_with_valid_config(self, mock_db_with_transaction, valid_config):
        """Test deploy with valid config succeeds."""
        db, conn = mock_db_with_transaction
        deployer = ConfigDeployer(db)

        # Mock get_agent_config to return default config
        current_config = OptimizationConfig(agent_name="test_agent")
        db.query.return_value = []  # No previous deployments

        # Deploy new config
        deployer.deploy("test_agent", valid_config, experiment_id="exp-001")

        # Verify transaction was used
        db.transaction.assert_called_once()

        # Verify deployment was stored
        conn.execute.assert_called()
        call_args = conn.execute.call_args_list[0]
        assert "INSERT INTO config_deployments" in call_args[0][0]

        # Verify deployment data
        deployment_data = call_args[0][1]
        assert deployment_data[1] == "test_agent"  # agent_name
        assert deployment_data[4] == "exp-001"  # experiment_id

    def test_deploy_with_invalid_config_raises_error(self, deployer):
        """Test deploy with invalid config raises ValueError."""
        invalid_config = OptimizationConfig(agent_name="test")
        delattr(invalid_config, "inference")

        with pytest.raises(ValueError, match="Invalid config"):
            deployer.deploy("test_agent", invalid_config)

    def test_deploy_stores_previous_config(self, mock_db_with_transaction, valid_config):
        """Test deploy stores previous config for rollback."""
        db, conn = mock_db_with_transaction
        deployer = ConfigDeployer(db)

        # Mock existing deployment
        previous_config = OptimizationConfig(
            agent_name="test_agent",
            inference={"model": "old_model"},
            prompt={"template": "old template"},
        )
        db.query.return_value = [
            {
                "new_config": json.dumps(previous_config.to_dict())
            }
        ]

        # Deploy new config
        deployer.deploy("test_agent", valid_config)

        # Verify previous config was stored
        call_args = conn.execute.call_args_list[0]
        deployment_data = call_args[0][1]
        stored_previous = json.loads(deployment_data[2])  # previous_config
        assert stored_previous["inference"]["model"] == "old_model"


class TestRollback:
    """Test rollback functionality."""

    def test_rollback_after_deployment(self, mock_db_with_transaction, valid_config):
        """Test rollback restores previous config."""
        db, conn = mock_db_with_transaction
        deployer = ConfigDeployer(db)

        # Mock deployment history
        previous_config = OptimizationConfig(
            agent_name="test_agent",
            inference={"model": "old_model"},
            prompt={"template": "old template"},
        )

        db.query.return_value = [
            {
                "id": "deploy-001",
                "agent_name": "test_agent",
                "previous_config": json.dumps(previous_config.to_dict()),
                "new_config": json.dumps(valid_config.to_dict()),
                "experiment_id": "exp-001",
                "deployed_at": utcnow().isoformat(),
                "deployed_by": "m5_system",
                "rollback_at": None,
                "rollback_reason": None,
            }
        ]

        # Rollback
        deployer.rollback("test_agent", rollback_reason="Quality regression")

        # Verify transaction was used
        db.transaction.assert_called_once()

        # Verify rollback was recorded
        conn.execute.assert_called()
        call_args = conn.execute.call_args_list[0]
        assert "UPDATE config_deployments" in call_args[0][0]
        assert "SET rollback_at" in call_args[0][0]

    def test_rollback_with_no_history_raises_error(self, deployer):
        """Test rollback with no deployment history raises ValueError."""
        deployer.db.query.return_value = []  # No deployments

        with pytest.raises(ValueError, match="No deployment history"):
            deployer.rollback("test_agent")

    def test_double_rollback_raises_error(self, deployer, valid_config):
        """Test rolling back already-rolled-back deployment raises ValueError."""
        # Mock already-rolled-back deployment
        previous_config = OptimizationConfig(agent_name="test_agent")

        deployer.db.query.return_value = [
            {
                "id": "deploy-001",
                "agent_name": "test_agent",
                "previous_config": json.dumps(previous_config.to_dict()),
                "new_config": json.dumps(valid_config.to_dict()),
                "experiment_id": None,
                "deployed_at": utcnow().isoformat(),
                "deployed_by": "m5_system",
                "rollback_at": utcnow().isoformat(),  # Already rolled back
                "rollback_reason": "Previous rollback",
            }
        ]

        with pytest.raises(ValueError, match="Already rolled back"):
            deployer.rollback("test_agent")


class TestDeploymentRecords:
    """Test deployment record storage and retrieval."""

    def test_get_agent_config_returns_latest(self, deployer, valid_config):
        """Test get_agent_config returns most recent non-rolled-back config."""
        deployer.db.query.return_value = [
            {"new_config": json.dumps(valid_config.to_dict())}
        ]

        config = deployer.get_agent_config("test_agent")

        assert config.agent_name == "test_agent"
        assert config.inference == valid_config.inference

    def test_get_agent_config_returns_default_when_no_deployments(self, deployer):
        """Test get_agent_config returns default config when no deployments."""
        deployer.db.query.return_value = []

        config = deployer.get_agent_config("test_agent")

        assert config.agent_name == "test_agent"
        assert isinstance(config, OptimizationConfig)

    def test_get_last_deployment_returns_most_recent(self, deployer, valid_config):
        """Test get_last_deployment returns most recent deployment."""
        previous_config = OptimizationConfig(agent_name="test_agent")

        deployer.db.query.return_value = [
            {
                "id": "deploy-001",
                "agent_name": "test_agent",
                "previous_config": json.dumps(previous_config.to_dict()),
                "new_config": json.dumps(valid_config.to_dict()),
                "experiment_id": "exp-001",
                "deployed_at": utcnow().isoformat(),
                "deployed_by": "m5_system",
                "rollback_at": None,
                "rollback_reason": None,
            }
        ]

        deployment = deployer.get_last_deployment("test_agent")

        assert deployment is not None
        assert deployment.id == "deploy-001"
        assert deployment.agent_name == "test_agent"
        assert deployment.experiment_id == "exp-001"

    def test_get_last_deployment_returns_none_when_no_history(self, deployer):
        """Test get_last_deployment returns None when no deployment history."""
        deployer.db.query.return_value = []

        deployment = deployer.get_last_deployment("test_agent")

        assert deployment is None


class TestThreadSafety:
    """Test thread-safety of config updates."""

    def test_deploy_uses_transaction(self, mock_db_with_transaction, valid_config):
        """Test deploy uses database transaction for atomic updates."""
        db, conn = mock_db_with_transaction
        deployer = ConfigDeployer(db)

        db.query.return_value = []  # No previous deployments

        deployer.deploy("test_agent", valid_config)

        # Verify transaction context manager was used
        db.transaction.assert_called_once()

    def test_rollback_uses_transaction(self, mock_db_with_transaction, valid_config):
        """Test rollback uses database transaction for atomic updates."""
        db, conn = mock_db_with_transaction
        deployer = ConfigDeployer(db)

        # Mock deployment history
        db.query.return_value = [
            {
                "id": "deploy-001",
                "agent_name": "test_agent",
                "previous_config": json.dumps(valid_config.to_dict()),
                "new_config": json.dumps(valid_config.to_dict()),
                "experiment_id": None,
                "deployed_at": utcnow().isoformat(),
                "deployed_by": "m5_system",
                "rollback_at": None,
                "rollback_reason": None,
            }
        ]

        deployer.rollback("test_agent")

        # Verify transaction context manager was used
        db.transaction.assert_called_once()


class TestGenerateId:
    """Test ID generation."""

    def test_generate_id_returns_unique_ids(self):
        """Test generate_id returns unique IDs."""
        id1 = generate_id()
        id2 = generate_id()

        assert id1 != id2
        assert id1.startswith("deploy-")
        assert id2.startswith("deploy-")
