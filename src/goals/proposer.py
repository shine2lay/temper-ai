"""Goal proposer — orchestrates analyzers, deduplicates, scores, persists."""

import hashlib
import logging
import uuid
from typing import List, Optional

from src.goals._schemas import GoalProposal
from src.goals.analyzers.base import BaseAnalyzer
from src.goals.constants import (
    DEDUP_KEY_LENGTH,
    DEFAULT_EFFORT_SCORE,
    DEFAULT_LOOKBACK_HOURS,
    DEFAULT_RISK_SCORE,
    EFFORT_SCORES,
    RISK_SCORES,
    SCORE_ROUND_DIGITS,
    WEIGHT_CONFIDENCE,
    WEIGHT_EFFORT_INVERSE,
    WEIGHT_IMPACT,
    WEIGHT_RISK_INVERSE,
)
from src.goals.models import GoalProposalRecord
from src.goals.store import GoalStore

logger = logging.getLogger(__name__)

UUID_HEX_LEN = 12
DEDUP_FETCH_LIMIT = 500
PATTERN_MATCH_LIMIT = 10
DEFAULT_SCORE_FALLBACK = 0.5
ACTIVE_STATUSES = {"proposed", "under_review", "approved", "in_progress"}


class GoalProposer:
    """Generates, scores, and persists goal proposals."""

    def __init__(
        self,
        store: GoalStore,
        learning_store: Optional[object] = None,
        analyzers: Optional[List[BaseAnalyzer]] = None,
    ) -> None:
        self._store = store
        self._learning_store = learning_store
        self._analyzers = analyzers or []

    def generate_proposals(
        self, lookback_hours: int = DEFAULT_LOOKBACK_HOURS
    ) -> List[GoalProposalRecord]:
        """Run all analyzers, deduplicate, score, and persist proposals."""
        raw_proposals: List[GoalProposal] = []

        for analyzer in self._analyzers:
            try:
                results = analyzer.analyze(lookback_hours=lookback_hours)
                raw_proposals.extend(results)
                logger.info(
                    "Analyzer '%s' produced %d proposals",
                    analyzer.analyzer_type,
                    len(results),
                )
            except Exception as exc:
                logger.warning(
                    "Analyzer '%s' failed: %s",
                    analyzer.analyzer_type,
                    exc,
                )

        # Deduplicate against existing active proposals
        unique = self._deduplicate(raw_proposals)

        # Score and enrich
        records: List[GoalProposalRecord] = []
        for proposal in unique:
            proposal.priority_score = self._score_proposal(proposal)
            self._enrich_with_patterns(proposal)
            record = self._to_record(proposal)
            self._store.save_proposal(record)
            records.append(record)

        logger.info(
            "Generated %d proposals (%d raw, %d after dedup)",
            len(records),
            len(raw_proposals),
            len(unique),
        )
        return records

    def _deduplicate(
        self, proposals: List[GoalProposal]
    ) -> List[GoalProposal]:
        """Remove proposals that duplicate existing active proposals."""
        existing = self._store.list_proposals(limit=DEDUP_FETCH_LIMIT)
        active_keys = {
            _dedup_key(r.goal_type, r.title)
            for r in existing
            if r.status in ACTIVE_STATUSES
        }

        unique: List[GoalProposal] = []
        seen: set[str] = set()
        for p in proposals:
            key = _dedup_key(p.goal_type.value, p.title)
            if key not in active_keys and key not in seen:
                unique.append(p)
                seen.add(key)

        return unique

    def _score_proposal(self, proposal: GoalProposal) -> float:
        """Calculate priority score using weighted formula."""
        # Average impact confidence
        impacts = proposal.expected_impacts
        avg_confidence = (
            sum(i.confidence for i in impacts) / len(impacts)
            if impacts
            else DEFAULT_SCORE_FALLBACK
        )
        avg_improvement = (
            sum(i.improvement_pct for i in impacts) / len(impacts)
            if impacts
            else 0.0
        )

        # Normalize improvement to 0-1 scale (cap at 100%)
        impact_score = min(avg_improvement / 100.0, 1.0)  # noqa: scanner: skip-magic

        effort_score = EFFORT_SCORES.get(
            proposal.effort_estimate.value, DEFAULT_EFFORT_SCORE
        )
        risk_score = RISK_SCORES.get(
            proposal.risk_assessment.level.value, DEFAULT_RISK_SCORE
        )

        score = (
            WEIGHT_IMPACT * impact_score
            + WEIGHT_CONFIDENCE * avg_confidence
            + WEIGHT_EFFORT_INVERSE * effort_score
            + WEIGHT_RISK_INVERSE * risk_score
        )
        return round(score, SCORE_ROUND_DIGITS)

    def _enrich_with_patterns(self, proposal: GoalProposal) -> None:
        """Cross-reference with learned patterns if available."""
        if self._learning_store is None:
            return

        try:
            from src.learning.store import LearningStore

            if not isinstance(self._learning_store, LearningStore):
                return

            patterns = self._learning_store.list_patterns(
                status="active", limit=PATTERN_MATCH_LIMIT
            )
            for pattern in patterns:
                # Match by overlapping workflow IDs
                if (
                    pattern.source_workflow_ids
                    and proposal.evidence.workflow_ids
                ):
                    overlap = set(pattern.source_workflow_ids) & set(
                        proposal.evidence.workflow_ids
                    )
                    if overlap:
                        proposal.evidence.pattern_ids.append(pattern.id)
        except (ImportError, AttributeError):
            pass

    def _to_record(self, proposal: GoalProposal) -> GoalProposalRecord:
        """Convert a GoalProposal to a GoalProposalRecord."""
        return GoalProposalRecord(
            id=f"gp-{uuid.uuid4().hex[:UUID_HEX_LEN]}",
            goal_type=proposal.goal_type.value,
            title=proposal.title,
            description=proposal.description,
            status="proposed",
            risk_assessment=proposal.risk_assessment.model_dump(),
            effort_estimate=proposal.effort_estimate.value,
            expected_impacts=[
                i.model_dump() for i in proposal.expected_impacts
            ],
            evidence=proposal.evidence.model_dump(),
            source_product_type=proposal.source_product_type,
            applicable_product_types=proposal.applicable_product_types,
            proposed_actions=proposal.proposed_actions,
            priority_score=proposal.priority_score,
        )


def _dedup_key(goal_type: str, title: str) -> str:
    """Generate a deduplication key from goal_type + title."""
    raw = f"{goal_type}:{title}"
    return hashlib.sha256(raw.encode()).hexdigest()[:DEDUP_KEY_LENGTH]
