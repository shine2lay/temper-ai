"""
State management for M5 Self-Improvement Loop.

Manages loop state persistence, transitions, and crash recovery.
Uses SQLModel ORM via the main database infrastructure.
"""
import json
import logging
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional

from sqlalchemy import JSON, DateTime
from sqlmodel import Column, Field, SQLModel, select

from src.observability.database import get_session
from src.observability.datetime_utils import utcnow

from .models import LoopState, LoopStatus, Phase

logger = logging.getLogger(__name__)


class M5LoopStateRecord(SQLModel, table=True):
    """SQLModel for M5 loop state persistence.

    Stores the current state of the self-improvement loop for each agent.
    Used for crash recovery and multi-process coordination.
    """
    __tablename__ = "m5_loop_state"

    agent_name: str = Field(primary_key=True)
    current_phase: str  # Phase enum value
    status: str  # LoopStatus enum value
    iteration_number: int = Field(default=0)
    phase_data: Optional[Dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
    last_error: Optional[str] = None
    started_at: datetime = Field(
        default_factory=utcnow,
        sa_column=Column(DateTime, nullable=False, default=utcnow),
    )
    updated_at: datetime = Field(
        default_factory=utcnow,
        sa_column=Column(DateTime, nullable=False, default=utcnow),
    )


def _record_to_state(record: M5LoopStateRecord) -> LoopState:
    """Convert ORM record to domain LoopState."""
    phase_data = record.phase_data
    if isinstance(phase_data, str):
        phase_data = json.loads(phase_data)
    return LoopState(
        agent_name=record.agent_name,
        current_phase=Phase(record.current_phase),
        status=LoopStatus(record.status),
        iteration_number=record.iteration_number,
        phase_data=phase_data if phase_data else {},
        last_error=record.last_error,
        started_at=record.started_at,
        updated_at=record.updated_at,
    )


class StateTransitionError(Exception):
    """Raised when an invalid state transition is attempted."""
    pass


class LoopStateManager:
    """
    Manage loop state with database persistence.

    Provides crash recovery by persisting state after each phase transition.
    Validates state transitions and supports pause/resume.

    Uses SQLModel ORM with the main database infrastructure (get_session).
    Accepts an optional session_factory for dependency injection (testing).
    """

    # Valid phase transitions
    PHASE_TRANSITIONS = {
        Phase.DETECT: {Phase.ANALYZE},
        Phase.ANALYZE: {Phase.STRATEGY},
        Phase.STRATEGY: {Phase.EXPERIMENT},
        Phase.EXPERIMENT: {Phase.DEPLOY},
        Phase.DEPLOY: {Phase.DETECT},  # Loop back for next iteration
    }

    def __init__(
        self,
        session_factory: Optional[Callable[[], Any]] = None,
    ):
        """
        Initialize state manager.

        Args:
            session_factory: Optional callable returning a context manager
                that yields a Session. Defaults to get_session.
        """
        self._session_factory = session_factory or get_session

    def get_state(self, agent_name: str) -> Optional[LoopState]:
        """
        Get current loop state for agent.

        Args:
            agent_name: Name of agent

        Returns:
            LoopState if exists, None otherwise
        """
        with self._session_factory() as session:
            stmt = select(M5LoopStateRecord).where(
                M5LoopStateRecord.agent_name == agent_name
            )
            record = session.exec(stmt).first()
            if not record:
                return None
            return _record_to_state(record)

    def create_state(self, agent_name: str) -> LoopState:
        """
        Create initial loop state for agent.

        Args:
            agent_name: Name of agent

        Returns:
            New LoopState starting at Phase.DETECT
        """
        now = datetime.now(timezone.utc)
        state = LoopState(
            agent_name=agent_name,
            current_phase=Phase.DETECT,
            status=LoopStatus.RUNNING,
            iteration_number=1,
            started_at=now,
            updated_at=now,
        )

        self.update_state(state)
        logger.info(f"Created initial state for {agent_name}")
        return state

    def update_state(self, state: LoopState) -> None:
        """
        Persist state to database.

        Args:
            state: LoopState to persist
        """
        state.updated_at = datetime.now(timezone.utc)

        with self._session_factory() as session:
            # Check if record exists
            stmt = select(M5LoopStateRecord).where(
                M5LoopStateRecord.agent_name == state.agent_name
            )
            record = session.exec(stmt).first()

            if record:
                record.current_phase = state.current_phase.value
                record.status = state.status.value
                record.iteration_number = state.iteration_number
                record.phase_data = state.phase_data if state.phase_data else None
                record.last_error = state.last_error
                record.started_at = state.started_at
                record.updated_at = state.updated_at
            else:
                record = M5LoopStateRecord(
                    agent_name=state.agent_name,
                    current_phase=state.current_phase.value,
                    status=state.status.value,
                    iteration_number=state.iteration_number,
                    phase_data=state.phase_data if state.phase_data else None,
                    last_error=state.last_error,
                    started_at=state.started_at,
                    updated_at=state.updated_at,
                )
                session.add(record)

            session.commit()

        logger.debug(f"Updated state for {state.agent_name}: {state.current_phase.value}")

    def transition_to_phase(self, agent_name: str, next_phase: Phase) -> LoopState:
        """
        Transition to next phase with validation.

        Args:
            agent_name: Name of agent
            next_phase: Phase to transition to

        Returns:
            Updated LoopState

        Raises:
            StateTransitionError: If transition is invalid
        """
        state = self.get_state(agent_name)
        if not state:
            raise StateTransitionError(f"No state found for {agent_name}")

        # Validate transition
        if not self.can_transition(state.current_phase, next_phase):
            raise StateTransitionError(
                f"Invalid transition from {state.current_phase.value} to {next_phase.value}"
            )

        # Update phase
        state.current_phase = next_phase

        # Increment iteration if looping back to DETECT
        if next_phase == Phase.DETECT and state.iteration_number > 0:
            state.iteration_number += 1
            logger.info(f"Starting iteration {state.iteration_number} for {agent_name}")

        self.update_state(state)
        return state

    def can_transition(self, from_phase: Phase, to_phase: Phase) -> bool:
        """
        Check if phase transition is valid.

        Args:
            from_phase: Current phase
            to_phase: Target phase

        Returns:
            True if transition is valid
        """
        valid_transitions = self.PHASE_TRANSITIONS.get(from_phase, set())
        return to_phase in valid_transitions

    def rollback_phase(self, agent_name: str) -> Phase:
        """
        Rollback to previous phase (not implemented - phases are sequential).

        Args:
            agent_name: Name of agent

        Returns:
            Previous phase

        Raises:
            NotImplementedError: Phase rollback not supported
        """
        raise NotImplementedError("Phase rollback not supported - phases are sequential")

    def pause(self, agent_name: str) -> None:
        """
        Pause loop execution.

        Args:
            agent_name: Name of agent
        """
        state = self.get_state(agent_name)
        if not state:
            raise ValueError(f"No state found for {agent_name}")

        state.status = LoopStatus.PAUSED
        self.update_state(state)
        logger.info(f"Paused loop for {agent_name}")

    def resume(self, agent_name: str) -> None:
        """
        Resume paused loop.

        Args:
            agent_name: Name of agent
        """
        state = self.get_state(agent_name)
        if not state:
            raise ValueError(f"No state found for {agent_name}")

        if state.status != LoopStatus.PAUSED:
            raise ValueError(f"Loop not paused for {agent_name}")

        state.status = LoopStatus.RUNNING
        self.update_state(state)
        logger.info(f"Resumed loop for {agent_name}")

    def mark_failed(self, agent_name: str, error: str) -> None:
        """
        Mark loop as failed.

        Args:
            agent_name: Name of agent
            error: Error message
        """
        state = self.get_state(agent_name)
        if not state:
            raise ValueError(f"No state found for {agent_name}")

        state.status = LoopStatus.FAILED
        state.last_error = error
        self.update_state(state)
        logger.error(f"Loop failed for {agent_name}: {error}")

    def mark_completed(self, agent_name: str) -> None:
        """
        Mark iteration as completed.

        Args:
            agent_name: Name of agent
        """
        state = self.get_state(agent_name)
        if not state:
            raise ValueError(f"No state found for {agent_name}")

        state.status = LoopStatus.COMPLETED
        self.update_state(state)
        logger.info(f"Iteration {state.iteration_number} completed for {agent_name}")

    def reset_state(self, agent_name: str) -> None:
        """
        Reset state (delete from database).

        Args:
            agent_name: Name of agent
        """
        with self._session_factory() as session:
            stmt = select(M5LoopStateRecord).where(
                M5LoopStateRecord.agent_name == agent_name
            )
            record = session.exec(stmt).first()
            if record:
                session.delete(record)
                session.commit()
        logger.info(f"Reset state for {agent_name}")

    def update_phase_data(self, agent_name: str, data: dict) -> None:
        """
        Update phase-specific data.

        Args:
            agent_name: Name of agent
            data: Data to store (merged with existing)
        """
        state = self.get_state(agent_name)
        if not state:
            raise ValueError(f"No state found for {agent_name}")

        state.phase_data.update(data)
        self.update_state(state)
