"""
Configuration deployment and rollback for M5 self-improvement.

Provides safe deployment of winning configurations with rollback capability
if performance regressions are detected.
"""

import json
import logging
import uuid
from pathlib import Path
from typing import Optional

from src.self_improvement.data_models import (
    AgentConfig,
    ConfigDeployment,
    utcnow,
)

# Import coordination database
import sys
coord_service_path = Path(__file__).parent.parent.parent.parent / ".claude-coord"
sys.path.insert(0, str(coord_service_path))
from coord_service.database import Database

logger = logging.getLogger(__name__)


def generate_id() -> str:
    """Generate unique deployment ID."""
    return f"deploy-{uuid.uuid4().hex[:12]}"


class ConfigDeployer:
    """
    Deploy and rollback agent configurations safely.

    Tracks deployment history in the coordination database to enable
    rollback if performance regressions are detected after deployment.

    Thread-safe: Uses database transactions for atomic config updates.
    """

    def __init__(self, db: Database):
        """
        Initialize deployer with database connection.

        Args:
            db: Database instance (coordination service database)
        """
        self.db = db

    def deploy(
        self,
        agent_name: str,
        new_config: AgentConfig,
        experiment_id: Optional[str] = None,
    ):
        """
        Deploy winning configuration with rollback tracking.

        Args:
            agent_name: Name of agent to update
            new_config: New configuration to deploy
            experiment_id: Optional experiment that produced this config

        Raises:
            ValueError: If config validation fails
        """
        # Validate new config
        if not self._validate_config(new_config):
            raise ValueError("Invalid config: missing required fields")

        # Get current config (for rollback)
        current_config = self.get_agent_config(agent_name)

        # Create deployment record
        deployment = ConfigDeployment(
            id=generate_id(),
            agent_name=agent_name,
            previous_config=current_config,
            new_config=new_config,
            experiment_id=experiment_id,
            deployed_at=utcnow(),
            deployed_by="m5_system",
        )

        # Store deployment and update config atomically
        with self.db.transaction() as conn:
            # Store deployment record
            self._store_deployment(conn, deployment)

            # Update agent config (atomic operation)
            self._update_agent_config(conn, agent_name, new_config)

        logger.info(
            f"Deployed new config for {agent_name} (deployment_id={deployment.id})"
        )

    def rollback(self, agent_name: str, rollback_reason: str = "Manual rollback"):
        """
        Rollback to previous configuration.

        Args:
            agent_name: Name of agent to rollback
            rollback_reason: Reason for rollback (e.g., "Quality regression")

        Raises:
            ValueError: If no deployment history exists or already rolled back
        """
        # Get last deployment
        last_deployment = self.get_last_deployment(agent_name)
        if not last_deployment:
            raise ValueError(f"No deployment history for {agent_name}")

        if last_deployment.rollback_at:
            raise ValueError(f"Already rolled back at {last_deployment.rollback_at}")

        # Restore previous config and mark as rolled back atomically
        with self.db.transaction() as conn:
            # Restore previous config
            self._update_agent_config(
                conn, agent_name, last_deployment.previous_config
            )

            # Mark as rolled back
            conn.execute(
                """
                UPDATE config_deployments
                SET rollback_at = ?, rollback_reason = ?
                WHERE id = ?
                """,
                (utcnow().isoformat(), rollback_reason, last_deployment.id),
            )

        logger.info(
            f"Rolled back config for {agent_name} (reason: {rollback_reason})"
        )

    def get_agent_config(self, agent_name: str) -> AgentConfig:
        """
        Get current agent configuration.

        Args:
            agent_name: Name of agent

        Returns:
            Current agent configuration (or default if not found)
        """
        # Query most recent deployment
        rows = self.db.query(
            """
            SELECT new_config
            FROM config_deployments
            WHERE agent_name = ? AND rollback_at IS NULL
            ORDER BY deployed_at DESC
            LIMIT 1
            """,
            (agent_name,),
        )

        if rows:
            config_dict = json.loads(rows[0]["new_config"])
            return AgentConfig.from_dict(config_dict)

        # Return default config if no deployments
        return AgentConfig(agent_name=agent_name)

    def get_last_deployment(self, agent_name: str) -> Optional[ConfigDeployment]:
        """
        Get most recent deployment record for agent.

        Args:
            agent_name: Name of agent

        Returns:
            Last deployment record or None if no history
        """
        rows = self.db.query(
            """
            SELECT *
            FROM config_deployments
            WHERE agent_name = ?
            ORDER BY deployed_at DESC
            LIMIT 1
            """,
            (agent_name,),
        )

        if not rows:
            return None

        row = rows[0]
        return ConfigDeployment(
            id=row["id"],
            agent_name=row["agent_name"],
            previous_config=AgentConfig.from_dict(json.loads(row["previous_config"])),
            new_config=AgentConfig.from_dict(json.loads(row["new_config"])),
            experiment_id=row["experiment_id"],
            deployed_at=row["deployed_at"],
            deployed_by=row["deployed_by"],
            rollback_at=row["rollback_at"],
            rollback_reason=row["rollback_reason"],
        )

    def _validate_config(self, config: AgentConfig) -> bool:
        """
        Validate config has required fields.

        Args:
            config: Config to validate

        Returns:
            True if valid, False otherwise
        """
        required_fields = ["inference", "prompt"]
        return all(hasattr(config, field) for field in required_fields)

    def _store_deployment(self, conn, deployment: ConfigDeployment):
        """
        Store deployment record in database.

        Args:
            conn: Database connection (within transaction)
            deployment: Deployment record to store
        """
        conn.execute(
            """
            INSERT INTO config_deployments
            (id, agent_name, previous_config, new_config, experiment_id,
             deployed_at, deployed_by, rollback_at, rollback_reason)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                deployment.id,
                deployment.agent_name,
                json.dumps(deployment.previous_config.to_dict()),
                json.dumps(deployment.new_config.to_dict()),
                deployment.experiment_id,
                deployment.deployed_at.isoformat(),
                deployment.deployed_by,
                None,  # rollback_at (initially None)
                None,  # rollback_reason (initially None)
            ),
        )

    def _update_agent_config(self, conn, agent_name: str, config: AgentConfig):
        """
        Update agent configuration (atomic operation).

        For MVP, this just stores the config in deployments table.
        Future: Could update separate agent_configs table.

        Args:
            conn: Database connection (within transaction)
            agent_name: Name of agent
            config: New configuration
        """
        # For MVP, config is tracked in deployment records
        # Agent retrieves config via get_agent_config() which queries latest deployment
        pass
