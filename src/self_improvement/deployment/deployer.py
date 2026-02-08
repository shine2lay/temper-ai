"""
Configuration deployment and rollback for M5 self-improvement.

Provides safe deployment of winning configurations with rollback capability
if performance regressions are detected. Integrates with M4 safety stack for
policy validation and approval workflows.
"""

import json
import logging
import time
import uuid
from datetime import datetime
from typing import Any, Optional

from src.constants.durations import MINUTES_PER_HOUR

# Import M4 safety stack
from src.safety.action_policy_engine import ActionPolicyEngine, PolicyExecutionContext
from src.safety.approval import ApprovalWorkflow
from src.self_improvement.data_models import (
    ConfigDeployment,
    SIOptimizationConfig,
    utcnow,
)

logger = logging.getLogger(__name__)

# Deployment ID configuration
DEPLOYMENT_ID_HEX_LENGTH = 12  # Length of hex portion in deployment ID


def generate_id() -> str:
    """Generate unique deployment ID."""
    return f"deploy-{uuid.uuid4().hex[:DEPLOYMENT_ID_HEX_LENGTH]}"


class ConfigDeployer:
    """
    Deploy and rollback agent configurations safely.

    Tracks deployment history in the coordination database to enable
    rollback if performance regressions are detected after deployment.

    Integrates with M4 safety stack:
    - ActionPolicyEngine for policy validation (ConfigChangePolicy)
    - ApprovalWorkflow for high-impact changes requiring human approval

    Thread-safe: Uses database transactions for atomic config updates.
    """

    def __init__(
        self,
        db: Any,
        policy_engine: Optional[ActionPolicyEngine] = None,
        approval_workflow: Optional[ApprovalWorkflow] = None,
        enable_safety_checks: bool = True
    ) -> None:
        """
        Initialize deployer with database connection and safety components.

        Args:
            db: Database instance (coordination service database).
                Database instance for tracking deployment history.
            policy_engine: ActionPolicyEngine for policy validation (optional)
            approval_workflow: ApprovalWorkflow for approval requests (optional)
            enable_safety_checks: Enable safety validation (default: True)
        """
        self.db = db
        self.policy_engine = policy_engine
        self.approval_workflow = approval_workflow
        self.enable_safety_checks = enable_safety_checks

    def deploy(
        self,
        agent_name: str,
        new_config: SIOptimizationConfig,
        experiment_id: Optional[str] = None,
        workflow_id: Optional[str] = None,
        deployed_by: str = "m5_system"
    ) -> None:
        """
        Deploy winning configuration with rollback tracking and safety validation.

        Integrates with M4 safety stack to validate config changes through
        ConfigChangePolicy. High-impact changes require approval before deployment.

        Args:
            agent_name: Name of agent to update
            new_config: New configuration to deploy
            experiment_id: Optional experiment that produced this config
            workflow_id: Optional workflow ID for safety context
            deployed_by: Who is deploying this config (default: m5_system)

        Raises:
            ValueError: If config validation fails or safety checks block deployment
            PermissionError: If approval is required but not granted
        """
        # Validate new config
        if not self._validate_config(new_config):
            raise ValueError("Invalid config: missing required fields")

        # Get current config (for rollback)
        current_config = self.get_agent_config(agent_name)

        # Safety validation through M4 stack (if enabled)
        if self.enable_safety_checks and self.policy_engine:
            enforcement_result = self._validate_through_safety_stack(
                agent_name=agent_name,
                old_config=current_config,
                new_config=new_config,
                workflow_id=workflow_id or "unknown",
                deployed_by=deployed_by
            )

            # Block deployment if critical violations
            if not enforcement_result.allowed:
                violation_msgs = [v.message for v in enforcement_result.violations]
                raise ValueError(
                    f"Config deployment blocked by safety policy: {'; '.join(violation_msgs)}"
                )

            # Request approval for high-impact changes
            if enforcement_result.requires_approval and self.approval_workflow:
                approval_granted = self._request_and_wait_for_approval(
                    agent_name=agent_name,
                    old_config=current_config,
                    new_config=new_config,
                    enforcement_result=enforcement_result,
                    deployed_by=deployed_by
                )

                if not approval_granted:
                    raise PermissionError(
                        f"Config deployment requires approval but was not granted for {agent_name}"
                    )

                logger.info(f"Approval granted for config deployment: {agent_name}")

        # Create deployment record
        deployment = ConfigDeployment(
            id=generate_id(),
            agent_name=agent_name,
            previous_config=current_config,
            new_config=new_config,
            experiment_id=experiment_id,
            deployed_at=utcnow(),
            deployed_by=deployed_by,
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

    def rollback(self, agent_name: str, rollback_reason: str = "Manual rollback") -> None:
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

    def get_agent_config(self, agent_name: str) -> SIOptimizationConfig:
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
            return SIOptimizationConfig.from_dict(config_dict)

        # Return default config if no deployments
        return SIOptimizationConfig(agent_name=agent_name)

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
            previous_config=SIOptimizationConfig.from_dict(json.loads(row["previous_config"])),
            new_config=SIOptimizationConfig.from_dict(json.loads(row["new_config"])),
            experiment_id=row["experiment_id"],
            deployed_at=(
                datetime.fromisoformat(row["deployed_at"])
                if isinstance(row["deployed_at"], str)
                else row["deployed_at"]
            ),
            deployed_by=row["deployed_by"],
            rollback_at=(
                datetime.fromisoformat(row["rollback_at"])
                if isinstance(row["rollback_at"], str)
                else row["rollback_at"]
            ),
            rollback_reason=row["rollback_reason"],
        )

    def _validate_through_safety_stack(
        self,
        agent_name: str,
        old_config: SIOptimizationConfig,
        new_config: SIOptimizationConfig,
        workflow_id: str,
        deployed_by: str
    ) -> Any:
        """
        Validate config change through M4 safety stack.

        Creates a config_change action and validates through ActionPolicyEngine,
        which will run the ConfigChangePolicy.

        Args:
            agent_name: Name of agent being updated
            old_config: Current configuration
            new_config: New configuration to deploy
            workflow_id: Workflow ID for context
            deployed_by: Who is deploying

        Returns:
            EnforcementResult from policy engine

        Raises:
            ValueError: If policy validation fails
        """
        # Create action for policy validation
        action = {
            "action_type": "config_change",
            "agent_name": agent_name,
            "old_config": old_config.to_dict(),
            "new_config": new_config.to_dict(),
            "deployed_by": deployed_by
        }

        # Create execution context
        context = PolicyExecutionContext(
            agent_id=deployed_by,
            workflow_id=workflow_id,
            stage_id="deployment",
            action_type="config_change",
            action_data=action,
            metadata={
                "agent_name": agent_name,
                "deployment_source": "m5_self_improvement"
            }
        )

        # Validate through policy engine (sync)
        enforcement_result = self.policy_engine.validate_action_sync(action, context)  # type: ignore[union-attr]

        return enforcement_result

    def _request_and_wait_for_approval(
        self,
        agent_name: str,
        old_config: SIOptimizationConfig,
        new_config: SIOptimizationConfig,
        enforcement_result: Any,
        deployed_by: str,
        approval_timeout_minutes: int = MINUTES_PER_HOUR
    ) -> bool:
        """
        Request approval and wait for decision.

        Args:
            agent_name: Name of agent
            old_config: Current config
            new_config: New config
            enforcement_result: Result from policy engine
            deployed_by: Who is deploying
            approval_timeout_minutes: How long to wait for approval

        Returns:
            True if approved, False if rejected/timeout
        """
        # Create approval request
        approval_request = self.approval_workflow.request_approval(  # type: ignore[union-attr]
            action={
                "type": "config_deployment",
                "agent_name": agent_name,
                "old_config": old_config.to_dict(),
                "new_config": new_config.to_dict()
            },
            reason=f"Config deployment for {agent_name} requires approval due to high-impact changes",
            requester=deployed_by,
            context={
                "agent_name": agent_name,
                "deployment_source": "m5_self_improvement",
                "deployed_by": deployed_by
            },
            violations=enforcement_result.violations,
            timeout_minutes=approval_timeout_minutes,
            metadata={
                "enforcement_metadata": enforcement_result.metadata,
                "num_violations": len(enforcement_result.violations),
                "critical_violations": enforcement_result.metadata.get("critical_violations", 0),
                "high_violations": enforcement_result.metadata.get("high_violations", 0)
            }
        )

        logger.info(
            f"Approval requested for config deployment: {agent_name} (request_id={approval_request.id})"
        )

        # Wait for approval decision (poll every second)
        start_time = time.time()
        max_wait_seconds = approval_timeout_minutes * 60
        poll_interval = 1.0

        while time.time() - start_time < max_wait_seconds:
            if self.approval_workflow.is_approved(approval_request.id):  # type: ignore[union-attr]
                return True
            if self.approval_workflow.is_rejected(approval_request.id):  # type: ignore[union-attr]
                logger.warning(
                    f"Config deployment rejected for {agent_name}: "
                    f"{approval_request.decision_reason}"
                )
                return False
            time.sleep(poll_interval)  # Intentional blocking: polling for approval decision in sync method

        # Timeout - approval not granted in time
        logger.warning(
            f"Config deployment approval timeout for {agent_name} after {approval_timeout_minutes} minutes"
        )
        return False

    def _validate_config(self, config: SIOptimizationConfig) -> bool:
        """
        Validate config has required fields.

        Args:
            config: Config to validate

        Returns:
            True if valid, False otherwise
        """
        required_fields = ["inference", "prompt"]
        return all(hasattr(config, field) for field in required_fields)

    def _store_deployment(self, conn: Any, deployment: ConfigDeployment) -> None:
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

    def _update_agent_config(self, conn: Any, agent_name: str, config: SIOptimizationConfig) -> None:
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
