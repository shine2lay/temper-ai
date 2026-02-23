"""Agent registry store — CRUD operations for the agent registry."""

import logging
from collections.abc import Callable, Generator
from contextlib import contextmanager
from typing import Any

from sqlmodel import Session, select

from temper_ai.registry._schemas import AgentRegistryEntry
from temper_ai.registry.constants import STATUS_INACTIVE, VALID_STATUSES
from temper_ai.storage.database.datetime_utils import utcnow
from temper_ai.storage.database.models_registry import AgentRegistryDB

logger = logging.getLogger(__name__)

# Type alias for session factory callables
SessionFactory = Callable[[], Any]


def _entry_from_db(row: AgentRegistryDB) -> AgentRegistryEntry:
    """Convert a DB row to an AgentRegistryEntry schema."""
    return AgentRegistryEntry(
        id=row.id,
        name=row.name,
        description=row.description,
        version=row.version,
        agent_type=row.agent_type,
        config_path=row.config_path,
        config_snapshot=row.config_snapshot or {},
        memory_namespace=row.memory_namespace,
        status=row.status,
        total_invocations=row.total_invocations,
        registered_at=row.registered_at,
        last_active_at=row.last_active_at,
        metadata_json=row.metadata_json,
    )


class AgentRegistryStore:
    """Persists and retrieves agent registration records."""

    def __init__(self, session_factory: SessionFactory | None = None) -> None:
        """Initialise the store.

        Args:
            session_factory: A callable that returns a context-manager-compatible
                session. Defaults to the application ``DatabaseManager`` session.
        """
        self._session_factory = session_factory

    @contextmanager
    def _session(self) -> Generator[Session, None, None]:
        """Yield an active DB session."""
        if self._session_factory is not None:
            with self._session_factory() as session:
                yield session
        else:
            from temper_ai.storage.database.manager import get_session

            with get_session() as session:
                yield session

    def register(self, entry: AgentRegistryEntry) -> str:
        """Persist an agent registry entry and return its ID.

        Args:
            entry: The AgentRegistryEntry to persist.

        Returns:
            The persisted agent ID.
        """
        row = AgentRegistryDB(
            id=entry.id,
            name=entry.name,
            description=entry.description,
            version=entry.version,
            agent_type=entry.agent_type,
            config_path=entry.config_path,
            config_snapshot=entry.config_snapshot,
            memory_namespace=entry.memory_namespace,
            status=entry.status,
            total_invocations=entry.total_invocations,
            registered_at=entry.registered_at,
            last_active_at=entry.last_active_at,
            metadata_json=entry.metadata_json,
        )
        with self._session() as session:
            session.add(row)
        logger.info("Registered agent '%s' with id '%s'", entry.name, entry.id)
        return entry.id

    def unregister(self, name: str) -> bool:
        """Soft-delete an agent by setting its status to inactive.

        Args:
            name: Agent name to unregister.

        Returns:
            True if the agent was found and marked inactive, False otherwise.
        """
        with self._session() as session:
            stmt = select(AgentRegistryDB).where(AgentRegistryDB.name == name)
            row = session.exec(stmt).first()
            if row is None:
                return False
            row.status = STATUS_INACTIVE
            session.add(row)
        return True

    def get(self, name: str) -> AgentRegistryEntry | None:
        """Return an agent entry by name, or None if not found."""
        with self._session() as session:
            stmt = select(AgentRegistryDB).where(AgentRegistryDB.name == name)
            row = session.exec(stmt).first()
            return _entry_from_db(row) if row else None

    def get_by_id(self, agent_id: str) -> AgentRegistryEntry | None:
        """Return an agent entry by ID, or None if not found."""
        with self._session() as session:
            stmt = select(AgentRegistryDB).where(AgentRegistryDB.id == agent_id)
            row = session.exec(stmt).first()
            return _entry_from_db(row) if row else None

    def list_all(self, status_filter: str | None = None) -> list[AgentRegistryEntry]:
        """List all registered agents, optionally filtered by status.

        Args:
            status_filter: If provided, only return agents with this status.

        Returns:
            List of AgentRegistryEntry objects.

        Raises:
            ValueError: If status_filter is not a valid status.
        """
        if status_filter is not None and status_filter not in VALID_STATUSES:
            raise ValueError(
                f"Invalid status_filter '{status_filter}'. "
                f"Must be one of: {', '.join(sorted(VALID_STATUSES))}"
            )
        with self._session() as session:
            stmt = select(AgentRegistryDB)
            if status_filter is not None:
                stmt = stmt.where(AgentRegistryDB.status == status_filter)
            rows = session.exec(stmt).all()
            return [_entry_from_db(r) for r in rows]

    def update_last_active(self, name: str) -> None:
        """Bump last_active_at timestamp and increment total_invocations.

        Args:
            name: Agent name to update.
        """
        with self._session() as session:
            stmt = select(AgentRegistryDB).where(AgentRegistryDB.name == name)
            row = session.exec(stmt).first()
            if row is None:
                logger.warning("update_last_active: agent '%s' not found", name)
                return
            row.last_active_at = utcnow()
            row.total_invocations += 1
            session.add(row)

    def update_status(self, name: str, status: str) -> None:
        """Update the status of an agent.

        Args:
            name: Agent name.
            status: New status string.

        Raises:
            ValueError: If status is not valid.
        """
        if status not in VALID_STATUSES:
            raise ValueError(
                f"Invalid status '{status}'. "
                f"Must be one of: {', '.join(sorted(VALID_STATUSES))}"
            )
        with self._session() as session:
            stmt = select(AgentRegistryDB).where(AgentRegistryDB.name == name)
            row = session.exec(stmt).first()
            if row is None:
                logger.warning("update_status: agent '%s' not found", name)
                return
            row.status = status
            session.add(row)
