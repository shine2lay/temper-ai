"""Bridge between merit score updates and autonomy evaluation."""

import logging
from typing import Any, Optional

from src.safety.autonomy.constants import EVALUATION_INTERVAL_DECISIONS

logger = logging.getLogger(__name__)


class MeritSafetyBridge:
    """Bridge that triggers autonomy evaluation on merit score updates.

    Rate-limited: only evaluates every N decisions to avoid overhead.
    Uses weak coupling — if autonomy manager is not configured, it's a no-op.
    """

    def __init__(
        self,
        autonomy_manager: Optional[Any] = None,
        evaluation_interval: int = EVALUATION_INTERVAL_DECISIONS,
    ) -> None:
        self._manager = autonomy_manager
        self._interval = evaluation_interval
        self._decision_counters: dict[str, int] = {}

    def on_decision_recorded(
        self,
        session: Any,
        agent_name: str,
        domain: str,
        outcome: str,
    ) -> None:
        """Called after a merit score update to trigger autonomy evaluation.

        Args:
            session: Database session.
            agent_name: Agent identifier.
            domain: Domain of expertise.
            outcome: Decision outcome ("success", "failure", etc.).
        """
        if self._manager is None:
            return

        # Rate limit: evaluate every N decisions per agent+domain
        key = f"{agent_name}:{domain}"
        self._decision_counters[key] = self._decision_counters.get(key, 0) + 1

        if self._decision_counters[key] % self._interval != 0:
            return

        try:
            transition = self._manager.evaluate_and_transition(
                session, agent_name, domain
            )
            if transition is not None:
                logger.info(
                    "Autonomy transition for %s/%s: level %d -> %d (%s)",
                    agent_name, domain,
                    transition.from_level, transition.to_level,
                    transition.reason,
                )
        except (AttributeError, TypeError, ValueError, RuntimeError) as exc:
            logger.warning("Autonomy evaluation failed: %s", exc)
