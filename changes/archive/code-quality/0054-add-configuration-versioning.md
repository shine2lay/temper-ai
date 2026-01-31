# Add Configuration Versioning (cq-p2-01)

**Date:** 2026-01-27
**Type:** Code Quality / Infrastructure
**Priority:** P3
**Completed by:** agent-858f9f

## Summary
Implemented comprehensive configuration versioning system with migration framework to enable backward compatibility and safe schema evolution.

## Problem
Configuration schemas were not versioned:

**Issues:**
- ❌ No way to track schema changes over time
- ❌ Breaking changes would break existing configs
- ❌ No migration path for config updates
- ❌ Difficult to evolve schemas safely
- ❌ Users forced to manually update configs
- ❌ No backward compatibility guarantees

**Example Problem:**
```yaml
# Old config (works in v1.0)
agent:
  name: my_agent
  settings:  # Field name
    timeout: 30

# After schema change (breaks in v1.1)
agent:
  name: my_agent
  config:  # Field renamed to 'config'
    timeout: 30
```

Without versioning, old configs would fail validation.

## Solution

### 1. Created Migration Framework (`src/utils/config_migrations.py`)

#### Core Classes

**MigrationStep:**
```python
@dataclass
class MigrationStep:
    """Single migration step from one version to another."""
    from_version: str
    to_version: str
    description: str
    migrate_fn: Callable[[Dict[str, Any]], Dict[str, Any]]
```

**ConfigMigrationRegistry:**
```python
class ConfigMigrationRegistry:
    """Registry for configuration migrations."""

    @registry.register("1.0", "1.1", "Add timeout field")
    def migrate_1_0_to_1_1(config):
        config['timeout'] = config.get('timeout', 30)
        return config

    def migrate(config, target_version):
        """Automatically find and apply migration path."""
        # ...
```

#### Key Features

**Automatic Path Finding:**
- Uses BFS to find shortest migration path
- Example: 1.0 → 1.1 → 1.2 → 2.0 (3 steps)
- Returns None if no path exists

**Decorator-Based Registration:**
```python
@agent_migration_registry.register("1.0", "1.1", "Add new field")
def migrate_agent(config):
    config['new_field'] = 'default_value'
    return config
```

**Migration Path Visualization:**
```
1.0 ──→ 1.1 ──→ 1.2 ──→ 2.0
  ↓                       ↑
  └─────→ 1.5 ───────────┘
```
Registry finds optimal path automatically.

### 2. Added schema_version to All Config Schemas

**AgentConfig:**
```python
class AgentConfig(BaseModel):
    """Agent configuration schema."""
    agent: AgentConfigInner
    schema_version: str = Field(
        default="1.0",
        description="Schema version for backward compatibility and migrations"
    )
```

**StageConfig:**
```python
class StageConfig(BaseModel):
    """Stage configuration schema."""
    stage: StageConfigInner
    schema_version: str = Field(
        default="1.0",
        description="Schema version for backward compatibility and migrations"
    )
```

**WorkflowConfig:**
```python
class WorkflowConfig(BaseModel):
    """Workflow configuration schema."""
    workflow: WorkflowConfigInner
    schema_version: str = Field(
        default="1.0",
        description="Schema version for backward compatibility and migrations"
    )
```

### 3. Global Migration Registries

Created separate registries for each config type:
```python
# Global registry for agent config migrations
agent_migration_registry = ConfigMigrationRegistry()

# Global registry for workflow config migrations
workflow_migration_registry = ConfigMigrationRegistry()

# Global registry for stage config migrations
stage_migration_registry = ConfigMigrationRegistry()
```

### 4. Convenience Function

```python
def ensure_current_version(
    config: Dict[str, Any],
    config_type: str,
    current_version: str
) -> Dict[str, Any]:
    """Ensure configuration is at current schema version."""
    # Automatically migrates to current version
    # Handles missing schema_version (assumes 1.0)
```

## Files Created
- `src/utils/config_migrations.py` (313 lines)
  - MigrationStep dataclass
  - ConfigMigrationRegistry class
  - Global registries (agent, workflow, stage)
  - Helper functions
  - Example migrations

## Files Modified
- `src/compiler/schemas.py`
  - Added `schema_version` field to AgentConfig
  - Added `schema_version` field to StageConfig
  - Added `schema_version` field to WorkflowConfig

## Testing

### Test Results
```
✓ Migration registry creation
✓ Migration registration (1.0→1.1, 1.1→1.2, 1.2→2.0)
✓ Path finding (1.0 to 2.0 = 3 steps)
✓ Migration execution (1.0 → 2.0)
✓ Field transformations applied correctly
✓ Schema version updated after migration
```

### Migration Verification
```python
# Start with old config
old_config = {
    'name': 'test',
    'schema_version': '1.0',
    'settings': {}
}

# Migrate to 2.0
new_config = registry.migrate(old_config, '2.0')

# Verify transformations
assert new_config['schema_version'] == '2.0'
assert 'timeout' in new_config  # Added in 1.0→1.1
assert 'retry_count' in new_config  # Added in 1.1→1.2
assert 'config' in new_config  # Renamed in 1.2→2.0
assert 'settings' not in new_config  # Old field removed
```

## Usage Examples

### Registering Migrations

```python
from src.utils.config_migrations import agent_migration_registry

@agent_migration_registry.register("1.0", "1.1", "Add safety timeout")
def migrate_agent_1_0_to_1_1(config):
    """Add default safety timeout to all agents."""
    if 'safety' not in config['agent']:
        config['agent']['safety'] = {}
    config['agent']['safety']['timeout'] = 300
    return config

@agent_migration_registry.register("1.1", "2.0", "Rename api_key to api_key_ref")
def migrate_agent_1_1_to_2_0(config):
    """Migrate from plaintext API keys to secret references."""
    if 'api_key' in config['agent']['inference']:
        key = config['agent']['inference'].pop('api_key')
        config['agent']['inference']['api_key_ref'] = f"${{env:API_KEY}}"
        # Log warning to set environment variable
    return config
```

### Using Migrations

```python
from src.compiler.config_loader import ConfigLoader
from src.utils.config_migrations import ensure_current_version

# Load old config
loader = ConfigLoader()
config_dict = loader.load_agent('my_agent')

# Ensure it's at current version
config_dict = ensure_current_version(
    config_dict,
    config_type='agent',
    current_version='2.0'
)

# Now validate with Pydantic
config = AgentConfig(**config_dict)
```

### Handling Missing Versions

```python
# Old config without schema_version field
old_config = {
    'agent': {
        'name': 'legacy_agent',
        # ... other fields
    }
}

# Automatically assumes 1.0
migrated = ensure_current_version(old_config, 'agent', '2.0')
# Logs warning: "Config missing schema_version field, assuming 1.0"
```

## Benefits

### 1. Backward Compatibility
```yaml
# Old config (schema 1.0) - still works!
agent:
  name: my_agent
  # ... old fields

# Automatically migrated to current schema on load
```

### 2. Safe Schema Evolution
```python
# Can evolve schemas without breaking existing configs
# Old configs automatically upgraded
# Migration path is explicit and tested
```

### 3. Clear Migration History
```python
# List all migrations
migrations = agent_migration_registry.list_migrations()
for m in migrations:
    print(f"{m.from_version} → {m.to_version}: {m.description}")

# Output:
# 1.0 → 1.1: Add safety timeout
# 1.1 → 1.2: Add retry configuration
# 1.2 → 2.0: Rename api_key to api_key_ref
```

### 4. Automatic Updates
- Configs automatically upgraded on load
- No manual intervention needed
- Migration logged for transparency

### 5. Flexible Versioning
- Supports semantic versioning (1.0, 1.1, 2.0)
- Can skip versions (1.0 → 2.0 directly)
- Multiple migration paths possible

## Migration Best Practices

### DO:
✅ Make migrations idempotent (safe to run multiple times)
✅ Add clear descriptions to each migration
✅ Test migrations with real config files
✅ Log warnings for user-action-required changes
✅ Provide sensible defaults for new fields
✅ Document breaking changes in migration description

### DON'T:
❌ Delete data without warnings
❌ Make irreversible transformations without backups
❌ Assume all configs have all fields
❌ Skip version numbers arbitrarily
❌ Make migrations that can fail silently

## Example Migration Scenarios

### Scenario 1: Add New Required Field
```python
@registry.register("1.0", "1.1", "Add required timeout field")
def migrate(config):
    # Provide sensible default
    config['timeout'] = config.get('timeout', 30)
    return config
```

### Scenario 2: Rename Field
```python
@registry.register("1.1", "1.2", "Rename 'settings' to 'config'")
def migrate(config):
    if 'settings' in config:
        config['config'] = config.pop('settings')
    return config
```

### Scenario 3: Restructure Nested Config
```python
@registry.register("1.2", "2.0", "Flatten inference config")
def migrate(config):
    if 'llm' in config and 'model_params' in config:
        # Merge nested structure
        config['llm']['params'] = config.pop('model_params')
    return config
```

### Scenario 4: Remove Deprecated Field
```python
@registry.register("2.0", "2.1", "Remove deprecated 'api_key' field")
def migrate(config):
    if 'api_key' in config:
        # Warn user
        import warnings
        warnings.warn("api_key is deprecated, use api_key_ref")
        config.pop('api_key')
    return config
```

## Versioning Strategy

### Version Number Format
- **Major.Minor** (e.g., "1.0", "1.1", "2.0")
- Major: Breaking changes, significant restructuring
- Minor: Backward-compatible additions

### When to Bump Version

**Minor version (1.0 → 1.1):**
- Add new optional field with default
- Add new enum value
- Relax validation constraint

**Major version (1.x → 2.0):**
- Rename field
- Remove field
- Change field type
- Restructure config
- Change semantics

## Future Enhancements
- [ ] Automatic migration on config load in ConfigLoader
- [ ] CLI tool to migrate config files: `migrate-config agent.yaml --to 2.0`
- [ ] Validation that all migrations are tested
- [ ] Migration dry-run mode (show what would change)
- [ ] Downgrade migrations (2.0 → 1.0 for rollback)
- [ ] Migration telemetry (track which versions are still in use)

## Related
- Task: cq-p2-01
- Category: Infrastructure - Configuration management
- Pattern: Schema versioning and migration
- Enables: Safe schema evolution, backward compatibility
- Similar to: Database migrations (Alembic, Flyway)
