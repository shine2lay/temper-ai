# Task Specification: code-high-m5-config-deployer

## Problem Statement

M5 needs to safely deploy winning configurations from experiments with the ability to rollback if regressions are detected. This is the "DEPLOY" component of the M5 loop.

## Acceptance Criteria

- Class `ConfigDeployer` in `src/self_improvement/deployment/deployer.py`
- Method `deploy(agent_name: str, new_config: AgentConfig)`:
  - Stores previous config for rollback
  - Updates agent config in database
  - Records deployment in config_deployments table
  - Agent uses new config on next execution
- Method `rollback(agent_name: str)`:
  - Reverts to previous config
  - Records rollback event
  - Validates previous config exists
- For MVP: 100% immediate deployment (no gradual rollout)
- Thread-safe config updates (atomic operations)
- Validates new config before deploying (schema check)

## Implementation Details

```python
class ConfigDeployer:
    def __init__(self, db):
        self.db = db

    def deploy(
        self,
        agent_name: str,
        new_config: AgentConfig,
        experiment_id: Optional[str] = None
    ):
        """
        Deploy winning configuration.

        Args:
            agent_name: Name of agent to update
            new_config: New configuration to deploy
            experiment_id: Optional experiment that produced this config
        """

        # Validate new config
        if not self._validate_config(new_config):
            raise ValueError("Invalid config")

        # Get current config (for rollback)
        current_config = self.db.get_agent_config(agent_name)

        # Store deployment record
        deployment = ConfigDeployment(
            id=generate_id(),
            agent_name=agent_name,
            previous_config=current_config,
            new_config=new_config,
            experiment_id=experiment_id,
            deployed_at=utcnow(),
            deployed_by="m5_system"
        )
        self.db.store_deployment(deployment)

        # Update agent config (atomic operation)
        self.db.update_agent_config(agent_name, new_config)

        logger.info(f"Deployed new config for {agent_name}")

    def rollback(self, agent_name: str):
        """Rollback to previous configuration."""

        # Get last deployment
        last_deployment = self.db.get_last_deployment(agent_name)
        if not last_deployment:
            raise ValueError(f"No deployment history for {agent_name}")

        if last_deployment.rollback_at:
            raise ValueError(f"Already rolled back")

        # Restore previous config
        self.db.update_agent_config(agent_name, last_deployment.previous_config)

        # Mark as rolled back
        last_deployment.rollback_at = utcnow()
        self.db.update_deployment(last_deployment)

        logger.info(f"Rolled back config for {agent_name}")

    def _validate_config(self, config: AgentConfig) -> bool:
        """Validate config has required fields."""
        required_fields = ["inference", "prompt"]
        return all(hasattr(config, field) for field in required_fields)
```

## Test Strategy

1. Unit tests with mock database
2. Test deploy with valid config (should succeed)
3. Test deploy with invalid config (should raise ValueError)
4. Test rollback after deployment (should restore previous config)
5. Test rollback with no history (should raise ValueError)
6. Test double rollback (should raise ValueError)
7. Verify deployment records stored correctly

## Dependencies

- test-med-m5-phase4-validation
- code-med-m5-deployment-db-schema

## Estimated Effort

4-6 hours (deploy/rollback logic, validation, testing)
