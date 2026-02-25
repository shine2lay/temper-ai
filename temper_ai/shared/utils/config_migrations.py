"""
Configuration migration framework for schema versioning.

Provides utilities for migrating configuration files between schema versions,
enabling backward compatibility and safe schema evolution.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from packaging import version

logger = logging.getLogger(__name__)


@dataclass
class MigrationStep:
    """Single migration step from one version to another.

    Attributes:
        from_version: Source schema version (e.g., "1.0")
        to_version: Target schema version (e.g., "1.1")
        description: Human-readable description of changes
        migrate_fn: Function that transforms config dict
    """

    from_version: str
    to_version: str
    description: str
    migrate_fn: Callable[[dict[str, Any]], dict[str, Any]]

    def __post_init__(self) -> None:
        """Validate version strings."""
        try:
            version.parse(self.from_version)
            version.parse(self.to_version)
        except version.InvalidVersion as e:
            raise ValueError(f"Invalid version format: {e}") from e


class ConfigMigrationRegistry:
    """Registry for configuration migrations.

    Manages migration steps between schema versions and provides
    automatic migration paths.

    Example:
        >>> registry = ConfigMigrationRegistry()
        >>>
        >>> # Register migration
        >>> @registry.register("1.0", "1.1", "Add timeout field")
        ... def migrate_1_0_to_1_1(config):
        ...     config['timeout'] = config.get('timeout', 30)
        ...     return config
        >>>
        >>> # Migrate config
        >>> old_config = {"name": "agent", "schema_version": "1.0"}
        >>> new_config = registry.migrate(old_config, target_version="1.1")
    """

    def __init__(self) -> None:
        """Initialize migration registry."""
        self._migrations: dict[str, list[MigrationStep]] = {}

    def register(
        self, from_version: str, to_version: str, description: str
    ) -> Callable[
        [Callable[[dict[str, Any]], dict[str, Any]]],
        Callable[[dict[str, Any]], dict[str, Any]],
    ]:
        """Decorator to register a migration function.

        Args:
            from_version: Source version
            to_version: Target version
            description: Migration description

        Returns:
            Decorator function

        Example:
            >>> @registry.register("1.0", "1.1", "Add timeout")
            ... def migrate(config):
            ...     config['timeout'] = 30
            ...     return config
        """

        def decorator(
            migrate_fn: Callable[[dict[str, Any]], dict[str, Any]],
        ) -> Callable[[dict[str, Any]], dict[str, Any]]:
            """Migration decorator wrapper."""
            step = MigrationStep(
                from_version=from_version,
                to_version=to_version,
                description=description,
                migrate_fn=migrate_fn,
            )
            self.add_migration(step)
            return migrate_fn

        return decorator

    def add_migration(self, step: MigrationStep) -> None:
        """Add a migration step to the registry.

        Args:
            step: Migration step to add
        """
        key = step.from_version
        if key not in self._migrations:
            self._migrations[key] = []
        self._migrations[key].append(step)

        # Sort by target version
        self._migrations[key].sort(key=lambda s: version.parse(s.to_version))

    def get_migration_path(
        self, from_version: str, to_version: str
    ) -> list[MigrationStep] | None:
        """Find migration path from one version to another.

        Uses breadth-first search to find shortest path.

        Args:
            from_version: Starting version
            to_version: Target version

        Returns:
            List of migration steps, or None if no path exists

        Example:
            >>> # With migrations: 1.0→1.1, 1.1→1.2, 1.2→2.0
            >>> path = registry.get_migration_path("1.0", "2.0")
            >>> # Returns: [step_1_0_to_1_1, step_1_1_to_1_2, step_1_2_to_2_0]
        """
        if from_version == to_version:
            return []

        # BFS to find shortest path
        from collections import deque

        queue: deque[tuple[str, list[MigrationStep]]] = deque([(from_version, [])])
        visited = {from_version}

        while queue:
            current_version, path = queue.popleft()

            # Check if we've reached target
            if current_version == to_version:
                return path

            # Explore neighbors
            if current_version in self._migrations:
                for step in self._migrations[current_version]:
                    if step.to_version not in visited:
                        visited.add(step.to_version)
                        queue.append((step.to_version, path + [step]))

        # No path found
        return None

    def migrate(
        self,
        config: dict[str, Any],
        target_version: str,
        source_version: str | None = None,
    ) -> dict[str, Any]:
        """Migrate configuration to target version.

        Args:
            config: Configuration dictionary
            target_version: Desired schema version
            source_version: Current version (auto-detected if not provided)

        Returns:
            Migrated configuration

        Raises:
            ValueError: If migration path not found or version invalid
            KeyError: If schema_version field missing and not provided

        Example:
            >>> old_config = {"name": "agent", "schema_version": "1.0"}
            >>> new_config = registry.migrate(old_config, "2.0")
            >>> assert new_config["schema_version"] == "2.0"
        """
        # Determine source version
        if source_version is None:
            if "schema_version" not in config:
                raise KeyError(
                    "Config missing 'schema_version' field and source_version not provided"
                )
            source_version = config["schema_version"]

        # Check if migration needed
        if source_version == target_version:
            return config

        # Find migration path
        path = self.get_migration_path(source_version, target_version)
        if path is None:
            raise ValueError(
                f"No migration path found from {source_version} to {target_version}"
            )

        # Apply migrations
        migrated_config = config.copy()
        for step in path:
            logger.info(
                f"Migrating config: {step.from_version} → {step.to_version} "
                f"({step.description})"
            )
            migrated_config = step.migrate_fn(migrated_config)
            migrated_config["schema_version"] = step.to_version

        return migrated_config

    def list_migrations(self) -> list[MigrationStep]:
        """List all registered migrations.

        Returns:
            Flat list of all migration steps
        """
        all_steps = []
        for steps in self._migrations.values():
            all_steps.extend(steps)
        return all_steps


# Global registry for agent config migrations
agent_migration_registry = ConfigMigrationRegistry()

# Global registry for workflow config migrations
workflow_migration_registry = ConfigMigrationRegistry()

# Global registry for stage config migrations
stage_migration_registry = ConfigMigrationRegistry()


def ensure_current_version(
    config: dict[str, Any], config_type: str, current_version: str
) -> dict[str, Any]:
    """Ensure configuration is at current schema version.

    Args:
        config: Configuration dictionary
        config_type: Type of config ("agent", "workflow", "stage")
        current_version: Current/latest schema version

    Returns:
        Migrated configuration at current version

    Example:
        >>> config = load_yaml("agent.yaml")
        >>> config = ensure_current_version(config, "agent", "2.0")
    """
    registry_map = {
        "agent": agent_migration_registry,
        "workflow": workflow_migration_registry,
        "stage": stage_migration_registry,
    }

    if config_type not in registry_map:
        raise ValueError(f"Unknown config type: {config_type}")

    registry = registry_map[config_type]

    # If no schema_version field, assume oldest version (1.0)
    if "schema_version" not in config:
        logger.warning("Config missing schema_version field, assuming 1.0")
        config["schema_version"] = "1.0"

    return registry.migrate(config, current_version)


# Example migrations (to be replaced with actual migrations)


@agent_migration_registry.register("1.0", "1.1", "Add schema_version to metadata")
def _migrate_agent_1_0_to_1_1(config: dict[str, Any]) -> dict[str, Any]:
    """Example migration: Add schema_version field."""
    # Migrations are applied by the framework
    # This is just a placeholder showing structure
    return config


@workflow_migration_registry.register("1.0", "1.1", "Rename 'pipeline' to 'stages'")
def _migrate_workflow_1_0_to_1_1(config: dict[str, Any]) -> dict[str, Any]:
    """Example migration: Rename field."""
    if "pipeline" in config:
        config["stages"] = config.pop("pipeline")
    return config
