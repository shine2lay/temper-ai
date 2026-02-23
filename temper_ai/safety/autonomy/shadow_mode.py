"""Shadow mode for validating autonomy escalation decisions.

Runs non-blocking shadow validation to track agreement between
current and proposed-level decisions without affecting real outcomes.
"""

import logging
from dataclasses import dataclass
from typing import Any

from temper_ai.safety.autonomy.constants import (
    SHADOW_AGREEMENT_THRESHOLD,
    SHADOW_MIN_RUNS,
)
from temper_ai.safety.autonomy.models import AutonomyState
from temper_ai.safety.autonomy.schemas import AutonomyLevel
from temper_ai.safety.autonomy.store import AutonomyStore
from temper_ai.safety.interfaces import SafetyViolation

logger = logging.getLogger(__name__)


@dataclass
class ShadowResult:
    """Result of shadow validation."""

    agrees: bool
    current_decision_requires_approval: bool
    shadow_decision_requires_approval: bool
    shadow_runs: int = 0
    shadow_agreements: int = 0
    agreement_rate: float = 0.0


class ShadowMode:
    """Shadow validation for autonomy level promotion.

    Simulates what the ApprovalRouter would decide at a proposed higher level,
    then compares with the actual decision. Tracks agreement rate over time.

    When agreement rate >= SHADOW_AGREEMENT_THRESHOLD after >= SHADOW_MIN_RUNS,
    the agent is considered ready for promotion.
    """

    def __init__(self, store: AutonomyStore) -> None:
        self._store = store

    def validate_shadow(
        self,
        agent_name: str,
        domain: str,
        violations: list[SafetyViolation] | None,
        current_requires_approval: bool,
        proposed_level: AutonomyLevel,
        approval_router: Any,
    ) -> ShadowResult:
        """Run shadow validation and record agreement.

        Args:
            agent_name: Agent identifier.
            domain: Domain of expertise.
            violations: Violations from current validation.
            current_requires_approval: Whether current level requires approval.
            proposed_level: The level being shadow-tested.
            approval_router: ApprovalRouter instance for simulation.

        Returns:
            ShadowResult with agreement data.
        """
        # Simulate what would happen at the proposed level
        shadow_decision = approval_router.route_action(
            agent_name,
            domain,
            violations,
            proposed_level,
        )
        shadow_requires_approval = shadow_decision.requires_approval

        # Agreement = both decisions are the same
        agrees = current_requires_approval == shadow_requires_approval

        # Update state
        state = self._get_or_create_state(agent_name, domain)
        state.shadow_level = proposed_level.value
        state.shadow_runs += 1
        if agrees:
            state.shadow_agreements += 1
        state.updated_at = _utcnow()
        self._store.save_state(state)

        agreement_rate = (
            state.shadow_agreements / state.shadow_runs
            if state.shadow_runs > 0
            else 0.0
        )

        logger.debug(
            "Shadow validation %s/%s: agrees=%s, rate=%.2f (%d/%d)",
            agent_name,
            domain,
            agrees,
            agreement_rate,
            state.shadow_agreements,
            state.shadow_runs,
        )

        return ShadowResult(
            agrees=agrees,
            current_decision_requires_approval=current_requires_approval,
            shadow_decision_requires_approval=shadow_requires_approval,
            shadow_runs=state.shadow_runs,
            shadow_agreements=state.shadow_agreements,
            agreement_rate=agreement_rate,
        )

    def check_promotion_ready(self, agent_name: str, domain: str) -> bool:
        """Check if shadow validation indicates readiness for promotion.

        Returns True if shadow_runs >= SHADOW_MIN_RUNS AND
        agreement_rate >= SHADOW_AGREEMENT_THRESHOLD.
        """
        state = self._store.get_state(agent_name, domain)
        if state is None:
            return False
        if state.shadow_runs < SHADOW_MIN_RUNS:
            return False
        agreement_rate = (
            state.shadow_agreements / state.shadow_runs
            if state.shadow_runs > 0
            else 0.0
        )
        return agreement_rate >= SHADOW_AGREEMENT_THRESHOLD

    def reset_shadow(self, agent_name: str, domain: str) -> None:
        """Reset shadow tracking counters (e.g., after level change)."""
        state = self._store.get_state(agent_name, domain)
        if state is not None:
            state.shadow_runs = 0
            state.shadow_agreements = 0
            state.shadow_level = None
            state.updated_at = _utcnow()
            self._store.save_state(state)

    def _get_or_create_state(self, agent_name: str, domain: str) -> AutonomyState:
        """Get or create AutonomyState from store."""
        import uuid

        state = self._store.get_state(agent_name, domain)
        if state is None:
            state = AutonomyState(
                id=f"as-{uuid.uuid4().hex[:12]}",  # scanner: skip-magic
                agent_name=agent_name,
                domain=domain,
            )
            self._store.save_state(state)
        return state


def _utcnow():  # type: ignore[no-untyped-def]
    """Lazy import to avoid module-level import overhead."""
    from temper_ai.storage.database.datetime_utils import utcnow

    return utcnow()
