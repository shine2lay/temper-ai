"""
State management for M5 Self-Improvement Loop.

Manages loop state persistence, transitions, and crash recovery.
"""
import json
import logging
from datetime import datetime, timezone
from typing import Optional
from pathlib import Path
import sys

# Add coordination DB to path
coord_path = Path(__file__).parent.parent.parent.parent / ".claude-coord"
sys.path.insert(0, str(coord_path))
from coord_service.database import Database

from .models import LoopState, LoopStatus, Phase

logger = logging.getLogger(__name__)


class StateTransitionError(Exception):
    """Raised when an invalid state transition is attempted."""
    pass


class LoopStateManager:
    """
    Manage loop state with database persistence.

    Provides crash recovery by persisting state after each phase transition.
    Validates state transitions and supports pause/resume.
    """

    # Valid phase transitions
    PHASE_TRANSITIONS = {
        Phase.DETECT: {Phase.ANALYZE},
        Phase.ANALYZE: {Phase.STRATEGY},
        Phase.STRATEGY: {Phase.EXPERIMENT},
        Phase.EXPERIMENT: {Phase.DEPLOY},
        Phase.DEPLOY: {Phase.DETECT},  # Loop back for next iteration
    }

    def __init__(self, db: Database):
        """
        Initialize state manager.

        Args:
            db: Coordination database instance
        """
        self.db = db
        self._ensure_schema()

    def _ensure_schema(self):
        """Create m5_loop_state table if not exists."""
        with self.db.transaction() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS m5_loop_state (
                    agent_name TEXT PRIMARY KEY,
                    current_phase TEXT NOT NULL,
                    status TEXT NOT NULL,
                    iteration_number INTEGER DEFAULT 0,
                    phase_data TEXT,
                    last_error TEXT,
                    started_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)

    def get_state(self, agent_name: str) -> Optional[LoopState]:
        """
        Get current loop state for agent.

        Args:
            agent_name: Name of agent

        Returns:
            LoopState if exists, None otherwise
        """
        rows = self.db.query(
            "SELECT * FROM m5_loop_state WHERE agent_name = ?",
            (agent_name,)
        )

        if not rows:
            return None

        row = rows[0]
        return LoopState(
            agent_name=row["agent_name"],
            current_phase=Phase(row["current_phase"]),
            status=LoopStatus(row["status"]),
            iteration_number=row["iteration_number"],
            phase_data=json.loads(row["phase_data"]) if row["phase_data"] else {},
            last_error=row["last_error"],
            started_at=datetime.fromisoformat(row["started_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

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

        with self.db.transaction() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO m5_loop_state
                (agent_name, current_phase, status, iteration_number, phase_data,
                 last_error, started_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    state.agent_name,
                    state.current_phase.value,
                    state.status.value,
                    state.iteration_number,
                    json.dumps(state.phase_data) if state.phase_data else None,
                    state.last_error,
                    state.started_at.isoformat(),
                    state.updated_at.isoformat(),
                ),
            )

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
        with self.db.transaction() as conn:
            conn.execute(
                "DELETE FROM m5_loop_state WHERE agent_name = ?",
                (agent_name,)
            )
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
