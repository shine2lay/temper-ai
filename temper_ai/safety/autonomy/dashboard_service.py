"""Data service for autonomy dashboard endpoints."""

import logging
from typing import Any

from temper_ai.safety.autonomy.store import AutonomyStore

logger = logging.getLogger(__name__)

DEFAULT_TRANSITION_LIMIT = 50


class AutonomyDataService:
    """Provides data for autonomy dashboard routes."""

    def __init__(self, store: AutonomyStore) -> None:
        self.store = store

    def get_status_summary(self) -> dict[str, Any]:
        """Get summary of all agents' autonomy levels."""
        states = self.store.list_states()
        return {
            "total_agents": len(states),
            "agents": [
                {
                    "agent_name": s.agent_name,
                    "domain": s.domain,
                    "current_level": s.current_level,
                    "shadow_level": s.shadow_level,
                    "shadow_runs": s.shadow_runs,
                    "shadow_agreements": s.shadow_agreements,
                    "updated_at": str(s.updated_at) if s.updated_at else None,
                }
                for s in states
            ],
        }

    def get_transitions(
        self,
        agent_name: str | None = None,
        limit: int = DEFAULT_TRANSITION_LIMIT,
    ) -> list[dict[str, Any]]:
        """Get recent transitions."""
        transitions = self.store.list_transitions(
            agent_name=agent_name,
            limit=limit,
        )
        return [
            {
                "id": t.id,
                "agent_name": t.agent_name,
                "domain": t.domain,
                "from_level": t.from_level,
                "to_level": t.to_level,
                "reason": t.reason,
                "trigger": t.trigger,
                "merit_snapshot": t.merit_snapshot,
                "created_at": str(t.created_at) if t.created_at else None,
            }
            for t in transitions
        ]

    def get_budget_overview(self) -> list[dict[str, Any]]:
        """Get budget status across all scopes."""
        from sqlmodel import Session, select

        from temper_ai.safety.autonomy.models import BudgetRecord

        with Session(self.store.engine) as session:
            budgets = list(session.exec(select(BudgetRecord)).all())

        return [
            {
                "scope": b.scope,
                "budget_usd": b.budget_usd,
                "spent_usd": b.spent_usd,
                "remaining_usd": max(0.0, b.budget_usd - b.spent_usd),
                "utilization": b.spent_usd / b.budget_usd if b.budget_usd > 0 else 0.0,
                "action_count": b.action_count,
                "status": b.status,
            }
            for b in budgets
        ]

    def get_emergency_status(self) -> dict[str, Any]:
        """Get current emergency stop state and recent history."""
        from temper_ai.safety.autonomy.emergency_stop import EmergencyStopController

        controller = EmergencyStopController(store=self.store)
        events = self.store.list_emergency_events(limit=10)  # scanner: skip-magic

        return {
            "is_active": controller.is_active(),
            "recent_events": [
                {
                    "id": e.id,
                    "triggered_by": e.triggered_by,
                    "reason": e.reason,
                    "agents_halted": e.agents_halted,
                    "halt_duration_ms": e.halt_duration_ms,
                    "resolved_at": str(e.resolved_at) if e.resolved_at else None,
                    "created_at": str(e.created_at) if e.created_at else None,
                }
                for e in events
            ],
        }
