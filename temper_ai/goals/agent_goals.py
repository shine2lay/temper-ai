"""Per-agent goal service for persistent agents (M9)."""

import logging
from typing import Any

logger = logging.getLogger(__name__)

ACTIVE_STATUSES = ("approved", "in_progress")
DEFAULT_GOAL_LIMIT = 10
GOALS_HEADER = "Active Goals:"


class AgentGoalService:
    """Manage goals associated with persistent agents."""

    def __init__(self, goal_store: Any = None) -> None:
        """Initialize with optional GoalStore.

        Args:
            goal_store: GoalStore instance (lazy-loaded if None).
        """
        self._store = goal_store

    def _get_store(self) -> Any:
        """Lazy-load the goal store."""
        if self._store is None:
            from temper_ai.goals.store import GoalStore

            self._store = GoalStore()
        return self._store

    def get_active_goals_for_agent(
        self, agent_id: str, limit: int = DEFAULT_GOAL_LIMIT
    ) -> list[dict[str, Any]]:
        """Get active goals for a specific persistent agent.

        Returns list of goal dicts with id, title, description, status, priority.
        Filters by agent_id using source_product_type field as agent identifier.
        """
        store = self._get_store()
        all_goals: list[Any] = []
        for status in ACTIVE_STATUSES:
            records = store.list_proposals(status=status)
            for rec in records:
                source = getattr(rec, "source_product_type", None)
                if source == agent_id:
                    all_goals.append(rec)

        all_goals.sort(key=lambda g: g.priority_score, reverse=True)
        return [
            {
                "id": getattr(g, "id", ""),
                "title": g.title,
                "description": g.description,
                "status": getattr(g, "status", ""),
                "priority": g.priority_score,
            }
            for g in all_goals[:limit]
        ]

    def propose_agent_goal(self, agent_id: str, goal_data: dict[str, Any]) -> str:
        """Create a goal proposal linked to a persistent agent.

        Returns the proposal ID.
        """
        import uuid

        from temper_ai.goals._schemas import GoalProposal
        from temper_ai.goals.models import GoalProposalRecord

        goal_data["source_product_type"] = agent_id
        proposal = GoalProposal(**goal_data)
        proposal_id = uuid.uuid4().hex
        record = GoalProposalRecord(
            id=proposal_id,
            goal_type=proposal.goal_type.value,
            title=proposal.title,
            description=proposal.description,
            priority_score=proposal.priority_score,
            source_product_type=agent_id,
            status="proposed",
        )
        store = self._get_store()
        store.save_proposal(record)
        return proposal_id

    def format_goals_context(self, agent_id: str, max_chars: int = 1000) -> str:
        """Format active goals as context string for prompt injection."""
        goals = self.get_active_goals_for_agent(agent_id)
        if not goals:
            return ""

        lines = [GOALS_HEADER]
        total = len(GOALS_HEADER)
        for g in goals:
            line = f"- [{g['status']}] {g['title']}: {g['description']}"
            if total + len(line) > max_chars:
                break
            lines.append(line)
            total += len(line)
        return "\n".join(lines)
