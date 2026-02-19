"""Bridge learned patterns and goal insights to the memory system.

Syncs active patterns from the LearningStore and approved goals from the
GoalStore into procedural memory so that agents can recall best practices
during prompt injection.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from temper_ai.memory.constants import MEMORY_TYPE_PROCEDURAL

logger = logging.getLogger(__name__)

DEFAULT_MIN_CONFIDENCE = 0.7
PROCEDURAL_NAMESPACE = "learned_procedures"
GOALS_NAMESPACE = "goal_insights"
APPROVED_STATUS = "approved"


class LearningToMemoryBridge:
    """Syncs learned patterns and goal insights to the memory system."""

    def __init__(
        self,
        learning_store: Any,
        memory_service: Optional[Any] = None,
    ) -> None:
        self._learning_store = learning_store
        self._memory_service = memory_service

    def _get_memory_service(self) -> Any:
        """Get or lazily create a MemoryService."""
        if self._memory_service is None:
            from temper_ai.memory.service import MemoryService

            self._memory_service = MemoryService(provider_name="in_memory")
        return self._memory_service

    def sync_patterns_to_memory(
        self, min_confidence: float = DEFAULT_MIN_CONFIDENCE,
    ) -> int:
        """Sync active learned patterns to procedural memory.

        Only patterns with ``confidence >= min_confidence`` are synced.
        Deduplication is by ``pattern_id`` in metadata.
        Returns the count of newly synced patterns.
        """
        svc = self._get_memory_service()
        scope = svc.build_scope(namespace=PROCEDURAL_NAMESPACE)
        existing = svc.list_memories(scope, memory_type=MEMORY_TYPE_PROCEDURAL)
        synced_ids = {
            e.metadata.get("pattern_id")
            for e in existing
            if e.metadata.get("pattern_id")
        }

        patterns = self._learning_store.list_patterns(status="active")
        count = 0
        for pattern in patterns:
            if pattern.confidence < min_confidence:
                continue
            if pattern.id in synced_ids:
                continue
            content = self._format_pattern(pattern)
            svc.store_procedural(
                scope,
                content=content,
                metadata={
                    "pattern_id": pattern.id,
                    "pattern_type": pattern.pattern_type,
                    "confidence": pattern.confidence,
                    "source": "learning_bridge",
                },
            )
            count += 1
        return count

    def sync_goals_to_memory(self, goal_store: Any) -> int:
        """Sync approved goals to procedural memory.

        Returns the count of newly synced goals.
        """
        svc = self._get_memory_service()
        scope = svc.build_scope(namespace=GOALS_NAMESPACE)
        existing = svc.list_memories(scope, memory_type=MEMORY_TYPE_PROCEDURAL)
        synced_ids = {
            e.metadata.get("goal_id")
            for e in existing
            if e.metadata.get("goal_id")
        }

        proposals = goal_store.list_proposals(status=APPROVED_STATUS)
        count = 0
        for proposal in proposals:
            if proposal.id in synced_ids:
                continue
            content = self._format_goal(proposal)
            svc.store_procedural(
                scope,
                content=content,
                metadata={
                    "goal_id": proposal.id,
                    "goal_type": proposal.goal_type,
                    "source": "goal_bridge",
                },
            )
            count += 1
        return count

    @staticmethod
    def _format_pattern(pattern: Any) -> str:
        """Format a LearnedPattern as human-readable procedural memory."""
        parts = [f"[{pattern.pattern_type}] {pattern.title}"]
        if pattern.description:
            parts.append(pattern.description)
        if pattern.recommendation:
            parts.append(f"Recommendation: {pattern.recommendation}")
        return " | ".join(parts)

    @staticmethod
    def _format_goal(proposal: Any) -> str:
        """Format a GoalProposalRecord as human-readable procedural memory."""
        parts = [f"[{proposal.goal_type}] {proposal.title}"]
        if proposal.description:
            parts.append(proposal.description)
        actions = getattr(proposal, "proposed_actions", [])
        if actions:
            parts.append("Actions: " + "; ".join(actions))
        return " | ".join(parts)
