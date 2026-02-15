"""Tests for src/utils/config_migrations.py.

Tests configuration schema versioning and migrations.
"""
import pytest

from src.shared.utils.config_migrations import (
    ConfigMigrationRegistry,
    MigrationStep,
    agent_migration_registry,
    ensure_current_version,
    stage_migration_registry,
    workflow_migration_registry,
)


class TestMigrationStep:
    """Test MigrationStep dataclass."""

    def test_valid_migration_step(self):
        """Test creating valid migration step."""
        def migrate_fn(config):
            config["new_field"] = "value"
            return config

        step = MigrationStep(
            from_version="1.0",
            to_version="1.1",
            description="Add new_field",
            migrate_fn=migrate_fn
        )

        assert step.from_version == "1.0"
        assert step.to_version == "1.1"
        assert step.description == "Add new_field"
        assert callable(step.migrate_fn)

    def test_invalid_version_format(self):
        """Test that invalid version format raises ValueError."""
        with pytest.raises(ValueError, match="Invalid version format"):
            MigrationStep(
                from_version="invalid",
                to_version="1.1",
                description="Test",
                migrate_fn=lambda c: c
            )

        with pytest.raises(ValueError, match="Invalid version format"):
            MigrationStep(
                from_version="1.0",
                to_version="not-a-version",
                description="Test",
                migrate_fn=lambda c: c
            )


class TestConfigMigrationRegistry:
    """Test ConfigMigrationRegistry class."""

    def test_initialization(self):
        """Test registry initialization."""
        registry = ConfigMigrationRegistry()
        assert len(registry._migrations) == 0

    def test_register_decorator(self):
        """Test registering migration with decorator."""
        registry = ConfigMigrationRegistry()

        @registry.register("1.0", "1.1", "Add timeout")
        def migrate(config):
            config["timeout"] = 30
            return config

        assert "1.0" in registry._migrations
        assert len(registry._migrations["1.0"]) == 1
        assert registry._migrations["1.0"][0].description == "Add timeout"

    def test_add_migration(self):
        """Test adding migration manually."""
        registry = ConfigMigrationRegistry()

        step = MigrationStep(
            from_version="1.0",
            to_version="1.1",
            description="Test migration",
            migrate_fn=lambda c: c
        )
        registry.add_migration(step)

        assert "1.0" in registry._migrations
        assert len(registry._migrations["1.0"]) == 1

    def test_add_multiple_migrations_sorted(self):
        """Test that migrations are sorted by target version."""
        registry = ConfigMigrationRegistry()

        # Add migrations out of order
        step_1_3 = MigrationStep("1.0", "1.3", "Skip version", lambda c: c)
        step_1_1 = MigrationStep("1.0", "1.1", "First step", lambda c: c)
        step_1_2 = MigrationStep("1.0", "1.2", "Second step", lambda c: c)

        registry.add_migration(step_1_3)
        registry.add_migration(step_1_1)
        registry.add_migration(step_1_2)

        steps = registry._migrations["1.0"]
        assert steps[0].to_version == "1.1"
        assert steps[1].to_version == "1.2"
        assert steps[2].to_version == "1.3"

    def test_get_migration_path_same_version(self):
        """Test migration path when versions are the same."""
        registry = ConfigMigrationRegistry()
        path = registry.get_migration_path("1.0", "1.0")
        assert path == []

    def test_get_migration_path_direct(self):
        """Test direct migration path."""
        registry = ConfigMigrationRegistry()

        @registry.register("1.0", "1.1", "Direct migration")
        def migrate(config):
            return config

        path = registry.get_migration_path("1.0", "1.1")
        assert path is not None
        assert len(path) == 1
        assert path[0].from_version == "1.0"
        assert path[0].to_version == "1.1"

    def test_get_migration_path_chain(self):
        """Test chained migration path."""
        registry = ConfigMigrationRegistry()

        @registry.register("1.0", "1.1", "Step 1")
        def migrate_1(config):
            return config

        @registry.register("1.1", "1.2", "Step 2")
        def migrate_2(config):
            return config

        @registry.register("1.2", "2.0", "Step 3")
        def migrate_3(config):
            return config

        path = registry.get_migration_path("1.0", "2.0")
        assert path is not None
        assert len(path) == 3
        assert path[0].from_version == "1.0"
        assert path[1].from_version == "1.1"
        assert path[2].from_version == "1.2"
        assert path[2].to_version == "2.0"

    def test_get_migration_path_not_found(self):
        """Test when no migration path exists."""
        registry = ConfigMigrationRegistry()

        @registry.register("1.0", "1.1", "Only migration")
        def migrate(config):
            return config

        path = registry.get_migration_path("1.0", "2.0")
        assert path is None

    def test_migrate_no_changes(self):
        """Test migrate when already at target version."""
        registry = ConfigMigrationRegistry()
        config = {"schema_version": "1.0", "name": "test"}

        result = registry.migrate(config, "1.0")
        assert result == config

    def test_migrate_single_step(self):
        """Test single-step migration."""
        registry = ConfigMigrationRegistry()

        @registry.register("1.0", "1.1", "Add timeout")
        def migrate(config):
            config["timeout"] = 30
            return config

        config = {"schema_version": "1.0", "name": "test"}
        result = registry.migrate(config, "1.1")

        assert result["schema_version"] == "1.1"
        assert result["timeout"] == 30
        assert result["name"] == "test"

    def test_migrate_multi_step(self):
        """Test multi-step migration."""
        registry = ConfigMigrationRegistry()

        @registry.register("1.0", "1.1", "Add field_a")
        def migrate_1(config):
            config["field_a"] = "value_a"
            return config

        @registry.register("1.1", "1.2", "Add field_b")
        def migrate_2(config):
            config["field_b"] = "value_b"
            return config

        config = {"schema_version": "1.0", "name": "test"}
        result = registry.migrate(config, "1.2")

        assert result["schema_version"] == "1.2"
        assert result["field_a"] == "value_a"
        assert result["field_b"] == "value_b"

    def test_migrate_missing_schema_version(self):
        """Test migration when config is missing schema_version."""
        registry = ConfigMigrationRegistry()

        config = {"name": "test"}

        with pytest.raises(KeyError, match="schema_version"):
            registry.migrate(config, "1.1")

    def test_migrate_with_source_version(self):
        """Test migration with explicit source version."""
        registry = ConfigMigrationRegistry()

        @registry.register("1.0", "1.1", "Add timeout")
        def migrate(config):
            config["timeout"] = 30
            return config

        config = {"name": "test"}  # No schema_version
        result = registry.migrate(config, "1.1", source_version="1.0")

        assert result["schema_version"] == "1.1"
        assert result["timeout"] == 30

    def test_migrate_no_path(self):
        """Test migration when no path exists."""
        registry = ConfigMigrationRegistry()

        config = {"schema_version": "1.0", "name": "test"}

        with pytest.raises(ValueError, match="No migration path found"):
            registry.migrate(config, "2.0")

    def test_list_migrations_empty(self):
        """Test listing migrations when registry is empty."""
        registry = ConfigMigrationRegistry()
        migrations = registry.list_migrations()
        assert migrations == []

    def test_list_migrations(self):
        """Test listing all migrations."""
        registry = ConfigMigrationRegistry()

        @registry.register("1.0", "1.1", "Migration 1")
        def migrate_1(config):
            return config

        @registry.register("1.1", "1.2", "Migration 2")
        def migrate_2(config):
            return config

        migrations = registry.list_migrations()
        assert len(migrations) == 2
        descriptions = [m.description for m in migrations]
        assert "Migration 1" in descriptions
        assert "Migration 2" in descriptions


class TestEnsureCurrentVersion:
    """Test ensure_current_version function."""

    def test_ensure_current_version_agent(self):
        """Test ensure_current_version with agent config."""
        config = {"schema_version": "1.0", "name": "test-agent"}
        result = ensure_current_version(config, "agent", "1.1")

        # Should attempt migration (though our registry has only no-op migrations)
        assert result["schema_version"] == "1.1"

    def test_ensure_current_version_workflow(self):
        """Test ensure_current_version with workflow config."""
        config = {"schema_version": "1.0", "name": "test-workflow"}
        result = ensure_current_version(config, "workflow", "1.1")
        assert result["schema_version"] == "1.1"

    def test_ensure_current_version_stage(self):
        """Test ensure_current_version with stage config."""
        # Stage registry may not have a 1.0->1.1 migration, test with same version
        config = {"schema_version": "1.0", "name": "test-stage"}
        result = ensure_current_version(config, "stage", "1.0")
        assert result["schema_version"] == "1.0"

    def test_ensure_current_version_missing_field(self):
        """Test ensure_current_version when schema_version is missing."""
        config = {"name": "test-agent"}
        result = ensure_current_version(config, "agent", "1.1")

        # Should assume 1.0 and migrate
        assert result["schema_version"] == "1.1"

    def test_ensure_current_version_unknown_type(self):
        """Test ensure_current_version with unknown config type."""
        config = {"schema_version": "1.0"}

        with pytest.raises(ValueError, match="Unknown config type"):
            ensure_current_version(config, "unknown", "1.1")


class TestGlobalRegistries:
    """Test global migration registries."""

    def test_agent_migration_registry_exists(self):
        """Test that agent_migration_registry is defined."""
        assert isinstance(agent_migration_registry, ConfigMigrationRegistry)

    def test_workflow_migration_registry_exists(self):
        """Test that workflow_migration_registry is defined."""
        assert isinstance(workflow_migration_registry, ConfigMigrationRegistry)

    def test_stage_migration_registry_exists(self):
        """Test that stage_migration_registry is defined."""
        assert isinstance(stage_migration_registry, ConfigMigrationRegistry)

    def test_agent_migration_1_0_to_1_1_exists(self):
        """Test that default agent migration 1.0->1.1 is registered."""
        migrations = agent_migration_registry.list_migrations()
        agent_migrations_1_0 = [
            m for m in migrations
            if m.from_version == "1.0" and m.to_version == "1.1"
        ]
        assert len(agent_migrations_1_0) >= 1

    def test_workflow_migration_1_0_to_1_1_exists(self):
        """Test that default workflow migration 1.0->1.1 is registered."""
        migrations = workflow_migration_registry.list_migrations()
        workflow_migrations = [
            m for m in migrations
            if m.from_version == "1.0" and m.to_version == "1.1"
        ]
        assert len(workflow_migrations) >= 1
