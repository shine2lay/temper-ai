"""Central autonomy state machine manager."""

import logging
import threading
import uuid
from datetime import timedelta
from typing import Optional

from src.storage.database.datetime_utils import utcnow
from src.safety.autonomy.constants import (
    DE_ESCALATION_COOLDOWN_HOURS,
    ESCALATION_COOLDOWN_HOURS,
    TRIGGER_AUTO_DE_ESCALATION,
    TRIGGER_AUTO_ESCALATION,
    TRIGGER_EMERGENCY_STOP,
    TRIGGER_MANUAL,
)
from src.safety.autonomy.models import AutonomyState, AutonomyTransition
from src.safety.autonomy.schemas import AutonomyLevel
from src.safety.autonomy.store import AutonomyStore
from src.safety.autonomy.trust_evaluator import TrustEvaluator

logger = logging.getLogger(__name__)

UUID_HEX_LEN = 12


class AutonomyManager:
    """Central state machine for agent autonomy levels.

    Manages transitions between autonomy levels, enforcing cooldowns,
    max-level caps, and thread-safety.
    """

    def __init__(
        self,
        store: AutonomyStore,
        trust_evaluator: Optional[TrustEvaluator] = None,
        max_level: AutonomyLevel = AutonomyLevel.RISK_GATED,
    ) -> None:
        self._store = store
        self._evaluator = trust_evaluator or TrustEvaluator()
        self._max_level = max_level
        self._lock = threading.Lock()

    def get_level(
        self, agent_name: str, domain: str
    ) -> AutonomyLevel:
        """Get current autonomy level for agent+domain.

        Returns SUPERVISED if no state exists.
        """
        state = self._store.get_state(agent_name, domain)
        if state is None:
            return AutonomyLevel.SUPERVISED
        return AutonomyLevel(state.current_level)

    def evaluate_and_transition(
        self,
        session: object,
        agent_name: str,
        domain: str,
    ) -> Optional[AutonomyTransition]:
        """Evaluate agent trust and transition if appropriate.

        Args:
            session: Database session for merit score lookup.
            agent_name: Agent identifier.
            domain: Domain of expertise.

        Returns:
            AutonomyTransition if a transition occurred, else None.
        """
        with self._lock:
            current_level = self.get_level(agent_name, domain)
            evaluation = self._evaluator.evaluate(
                session, agent_name, domain, current_level
            )

            if evaluation.needs_de_escalation and evaluation.recommended_level is not None:
                return self._de_escalate(
                    agent_name,
                    domain,
                    reason="; ".join(evaluation.reasons),
                    trigger=TRIGGER_AUTO_DE_ESCALATION,
                    merit_snapshot=evaluation.evidence,
                )

            if evaluation.eligible_for_escalation and evaluation.recommended_level is not None:
                return self._escalate(
                    agent_name,
                    domain,
                    reason="; ".join(evaluation.reasons),
                    trigger=TRIGGER_AUTO_ESCALATION,
                    merit_snapshot=evaluation.evidence,
                )

            return None

    def escalate(
        self,
        agent_name: str,
        domain: str,
        reason: str = "manual",
        target_level: Optional[AutonomyLevel] = None,
    ) -> Optional[AutonomyTransition]:
        """Manually escalate an agent's autonomy level."""
        with self._lock:
            return self._escalate(
                agent_name, domain, reason,
                trigger=TRIGGER_MANUAL,
                target_level=target_level,
            )

    def de_escalate(
        self,
        agent_name: str,
        domain: str,
        reason: str = "manual",
    ) -> Optional[AutonomyTransition]:
        """Manually de-escalate an agent's autonomy level."""
        with self._lock:
            return self._de_escalate(
                agent_name, domain, reason, trigger=TRIGGER_MANUAL,
            )

    def force_level(
        self,
        agent_name: str,
        domain: str,
        level: AutonomyLevel,
        reason: str = "forced",
    ) -> AutonomyTransition:
        """Force agent to a specific level (bypasses cooldown)."""
        with self._lock:
            state = self._get_or_create_state(agent_name, domain)
            from_level = state.current_level
            state.current_level = level.value
            state.updated_at = utcnow()
            self._store.save_state(state)

            transition = self._create_transition(
                agent_name, domain, from_level, level.value,
                reason, TRIGGER_EMERGENCY_STOP,
            )
            logger.info(
                "Forced %s/%s to level %s: %s",
                agent_name, domain, level.name, reason,
            )
            return transition

    def _escalate(
        self,
        agent_name: str,
        domain: str,
        reason: str,
        trigger: str,
        merit_snapshot: Optional[dict] = None,
        target_level: Optional[AutonomyLevel] = None,
    ) -> Optional[AutonomyTransition]:
        """Internal escalation logic (must hold lock)."""
        state = self._get_or_create_state(agent_name, domain)
        current = AutonomyLevel(state.current_level)

        # Determine target
        if target_level is not None:
            new_level = target_level
        else:
            new_level = AutonomyLevel(min(current + 1, AutonomyLevel.STRATEGIC))

        # Guard: already at or above target
        if new_level <= current:
            return None

        # Guard: max_level cap
        if new_level > self._max_level:
            logger.info(
                "Escalation blocked: %s > max_level %s",
                new_level.name, self._max_level.name,
            )
            return None

        # Guard: cooldown
        if not self._cooldown_elapsed(state.last_escalation, ESCALATION_COOLDOWN_HOURS):
            logger.info("Escalation cooldown not elapsed for %s/%s", agent_name, domain)
            return None

        # Apply transition
        state.current_level = new_level.value
        state.last_escalation = utcnow()
        state.updated_at = utcnow()
        self._store.save_state(state)

        transition = self._create_transition(
            agent_name, domain, current.value, new_level.value,
            reason, trigger, merit_snapshot,
        )
        logger.info(
            "Escalated %s/%s: %s -> %s (%s)",
            agent_name, domain, current.name, new_level.name, reason,
        )
        return transition

    def _de_escalate(
        self,
        agent_name: str,
        domain: str,
        reason: str,
        trigger: str,
        merit_snapshot: Optional[dict] = None,
    ) -> Optional[AutonomyTransition]:
        """Internal de-escalation logic (must hold lock)."""
        state = self._get_or_create_state(agent_name, domain)
        current = AutonomyLevel(state.current_level)

        if current == AutonomyLevel.SUPERVISED:
            return None

        # Guard: cooldown
        if not self._cooldown_elapsed(state.last_de_escalation, DE_ESCALATION_COOLDOWN_HOURS):
            logger.info("De-escalation cooldown not elapsed for %s/%s", agent_name, domain)
            return None

        new_level = AutonomyLevel(max(0, current - 1))
        state.current_level = new_level.value
        state.last_de_escalation = utcnow()
        state.updated_at = utcnow()
        self._store.save_state(state)

        transition = self._create_transition(
            agent_name, domain, current.value, new_level.value,
            reason, trigger, merit_snapshot,
        )
        logger.info(
            "De-escalated %s/%s: %s -> %s (%s)",
            agent_name, domain, current.name, new_level.name, reason,
        )
        return transition

    def _get_or_create_state(
        self, agent_name: str, domain: str
    ) -> AutonomyState:
        """Get existing state or create new SUPERVISED state."""
        state = self._store.get_state(agent_name, domain)
        if state is None:
            state = AutonomyState(
                id=f"as-{uuid.uuid4().hex[:UUID_HEX_LEN]}",
                agent_name=agent_name,
                domain=domain,
                current_level=AutonomyLevel.SUPERVISED.value,
            )
            self._store.save_state(state)
        return state

    def _cooldown_elapsed(
        self, last_event: Optional[object], hours: int
    ) -> bool:
        """Check if enough time has passed since the last event."""
        if last_event is None:
            return True
        from datetime import datetime, timezone
        if not isinstance(last_event, datetime):
            return True
        now = utcnow()
        # Handle timezone mismatch (SQLite stores naive datetimes)
        if last_event.tzinfo is None and now.tzinfo is not None:
            last_event = last_event.replace(tzinfo=timezone.utc)
        return (now - last_event) >= timedelta(hours=hours)

    def _create_transition(
        self,
        agent_name: str,
        domain: str,
        from_level: int,
        to_level: int,
        reason: str,
        trigger: str,
        merit_snapshot: Optional[dict] = None,
    ) -> AutonomyTransition:
        """Create and persist a transition record."""
        transition = AutonomyTransition(
            id=f"at-{uuid.uuid4().hex[:UUID_HEX_LEN]}",
            agent_name=agent_name,
            domain=domain,
            from_level=from_level,
            to_level=to_level,
            reason=reason,
            trigger=trigger,
            merit_snapshot=merit_snapshot or {},
        )
        self._store.save_transition(transition)
        return transition
