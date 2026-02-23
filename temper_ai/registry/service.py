"""Agent registry service — high-level orchestration of agent lifecycle."""

import logging
import uuid
from typing import Any

from temper_ai.registry._helpers import (
    build_memory_namespace,
    generate_agent_id,
    load_config_from_path,
)
from temper_ai.registry._schemas import (
    AgentRegistryEntry,
    MessageRequest,
    MessageResponse,
)
from temper_ai.registry.constants import STATUS_ACTIVE
from temper_ai.registry.store import AgentRegistryStore
from temper_ai.storage.database.datetime_utils import utcnow

logger = logging.getLogger(__name__)


class AgentRegistryService:
    """Orchestrates agent registration, retrieval, and invocation."""

    def __init__(self, store: AgentRegistryStore | None = None) -> None:
        self._store = store or AgentRegistryStore()

    def register_agent(
        self,
        config_path: str,
        metadata: dict[str, Any] | None = None,
    ) -> AgentRegistryEntry:
        """Load an agent YAML config and persist it in the registry.

        Args:
            config_path: Path to the agent YAML configuration file.
            metadata: Optional extra metadata dict to attach.

        Returns:
            The persisted AgentRegistryEntry.
        """
        config = load_config_from_path(config_path)
        name = config.get("name", "")
        if not name:
            raise ValueError(
                f"Agent config at '{config_path}' must have a 'name' field"
            )

        entry = AgentRegistryEntry(
            id=generate_agent_id(),
            name=name,
            description=config.get("description", ""),
            version=str(config.get("version", "1.0")),
            agent_type=config.get("type", "standard"),
            config_path=config_path,
            config_snapshot=config,
            memory_namespace=build_memory_namespace(name),
            registered_at=utcnow(),
            metadata_json=metadata,
        )
        self._store.register(entry)
        return entry

    def unregister_agent(self, name: str) -> bool:
        """Unregister an agent by name (soft-delete).

        Returns:
            True if found and unregistered, False if not found.
        """
        return self._store.unregister(name)

    def list_agents(self, status: str | None = None) -> list[AgentRegistryEntry]:
        """List registered agents, optionally filtered by status."""
        return self._store.list_all(status_filter=status)

    def get_agent(self, name: str) -> AgentRegistryEntry | None:
        """Retrieve a single agent entry by name."""
        return self._store.get(name)

    def invoke(self, name: str, message: MessageRequest) -> MessageResponse:
        """Invoke a registered agent with a message.

        Loads the agent from the registry, runs it with the provided message,
        and updates invocation tracking.

        Args:
            name: Registered agent name.
            message: The message to send to the agent.

        Returns:
            MessageResponse with the agent's output.

        Raises:
            KeyError: If the agent is not found in the registry.
        """
        entry = self._store.get(name)
        if entry is None:
            raise KeyError(f"Agent '{name}' not found in registry")

        self._store.update_status(name, STATUS_ACTIVE)
        execution_id = uuid.uuid4().hex

        try:
            agent = self._load_agent(entry)
            result = agent.run(message.content)
        finally:
            self._store.update_last_active(name)

        content = result if isinstance(result, str) else str(result)
        return MessageResponse(
            content=content,
            agent_name=name,
            execution_id=execution_id,
        )

    def _load_agent(self, entry: AgentRegistryEntry) -> Any:
        """Instantiate a StandardAgent from a registry entry's config snapshot.

        Uses a lazy import to avoid circular import issues.
        """
        from temper_ai.agent.standard_agent import StandardAgent

        config_snapshot = dict(entry.config_snapshot)
        config_snapshot["memory_namespace"] = entry.memory_namespace

        return StandardAgent(config=config_snapshot)  # type: ignore[arg-type]  # AgentConfig accepts dicts at runtime
