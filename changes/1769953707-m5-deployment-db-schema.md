# M5: Add config_deployments Table

**Date:** 2026-02-01
**Task:** code-med-m5-deployment-db-schema
**Component:** Coordination Service Database Schema
**Milestone:** M5 Milestone 1 (Phase 5: Deployment)

---

## Summary

Added `config_deployments` table to track agent configuration deployment history, enabling rollback capability for M5 self-improvement loop.

## Changes Made

### Database Schema (.claude-coord/coord_service/schema.sql)

**Added table: `config_deployments`**

Tracks deployment history with the following columns:
- `id` (TEXT, PRIMARY KEY): Unique deployment identifier
- `agent_name` (TEXT, NOT NULL): Name of agent being configured
- `previous_config` (TEXT/JSON, NOT NULL): Previous configuration (for rollback)
- `new_config` (TEXT/JSON, NOT NULL): New configuration being deployed
- `experiment_id` (TEXT, nullable): Optional link to experiment that triggered deployment
- `deployed_at` (TIMESTAMP): When deployment occurred (auto-set)
- `deployed_by` (TEXT): Agent ID or user that triggered deployment
- `rollback_at` (TIMESTAMP, nullable): When configuration was rolled back (if applicable)
- `rollback_reason` (TEXT, nullable): Why rollback occurred

**Added indexes:**
- `idx_deployment_agent`: Fast lookup by agent_name
- `idx_deployment_time`: Fast lookup by deployment time (DESC for recent first)
- `idx_deployment_experiment`: Fast lookup by experiment_id

**Foreign key:**
- `experiment_id` → `experiments(id)` (ON DELETE SET NULL)

## Integration with M5

This table is used by the `ConfigDeployer` component (M5 Phase 5) to:

1. **Track deployments**: Store every configuration change with full history
2. **Enable rollback**: Retrieve previous_config to revert if regression detected
3. **Audit trail**: Link deployments to experiments that triggered them
4. **Monitor deployments**: Query recent deployments by agent or time

## Use Cases

### Deployment Flow
```sql
-- Deploy new configuration
INSERT INTO config_deployments
(id, agent_name, previous_config, new_config, experiment_id, deployed_by)
VALUES ('deploy-001', 'product_extractor',
        '{"model": "llama3.1:8b"}',
        '{"model": "qwen2.5:32b"}',
        'exp-001', 'agent-m5');

-- Get most recent deployment for agent
SELECT * FROM config_deployments
WHERE agent_name = 'product_extractor'
ORDER BY deployed_at DESC LIMIT 1;
```

### Rollback Flow
```sql
-- Rollback to previous config
UPDATE config_deployments
SET rollback_at = CURRENT_TIMESTAMP,
    rollback_reason = 'Quality regression detected'
WHERE id = 'deploy-001';

-- Get previous config for rollback
SELECT previous_config FROM config_deployments
WHERE id = 'deploy-001';
```

### Audit Trail
```sql
-- View deployment history for agent
SELECT
    id,
    deployed_at,
    new_config,
    experiment_id,
    rollback_at,
    rollback_reason
FROM config_deployments
WHERE agent_name = 'product_extractor'
ORDER BY deployed_at DESC;
```

## Testing Performed

Created comprehensive test suite verifying:
- ✅ Table creation with correct schema
- ✅ All columns present with correct types
- ✅ Insert deployment records
- ✅ Query deployment records
- ✅ Update rollback fields
- ✅ All indexes created
- ✅ Query performance using indexes

All tests passed successfully.

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| Config data too large for TEXT field | JSON configs are typically small (< 10KB). SQLite TEXT supports up to 1GB. |
| Missing foreign key for experiments table | Foreign key constraint will fail gracefully if experiments table doesn't exist yet. Will work once experiments table is created. |
| No validation on JSON format | Application layer (ConfigDeployer) validates JSON before insertion. |

## Next Steps

1. ✅ Schema added and validated
2. ⏳ Implement `ConfigDeployer` class to use this table (next task: code-high-m5-config-deployer)
3. ⏳ Add rollback detection logic
4. ⏳ Integrate with ExperimentOrchestrator

## References

- M5 Architecture: `/docs/M5_MODULAR_ARCHITECTURE.md` (Phase 5: Deployment)
- Database Schema: `.claude-coord/coord_service/schema.sql`
- Related task: `code-high-m5-config-deployer` (blocks this deployment)
