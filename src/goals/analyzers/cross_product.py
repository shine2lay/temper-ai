"""Cross-product analyzer — finds insights transferable between product types."""

import logging
from datetime import timedelta
from typing import Any, List, Optional

from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from src.goals._schemas import (
    EffortLevel,
    GoalEvidence,
    GoalProposal,
    GoalRiskLevel,
    GoalType,
    ImpactEstimate,
    RiskAssessment,
)
from src.goals.analyzers.base import BaseAnalyzer
from src.goals.constants import DEFAULT_LOOKBACK_HOURS, MIN_PRODUCT_TYPES_CROSS

logger = logging.getLogger(__name__)

PCT_MULTIPLIER = 100
CROSS_CONFIDENCE = 0.4
EVIDENCE_WORKFLOW_LIMIT = 5
PERFORMANCE_RATIO_THRESHOLD = 1.5
PATTERN_LIST_LIMIT = 50


class CrossProductAnalyzer(BaseAnalyzer):
    """Identifies patterns from one product type applicable to others."""

    def __init__(
        self,
        engine: Optional[Engine] = None,
        learning_store: Optional[object] = None,
    ) -> None:
        self._engine = engine
        self._learning_store = learning_store

    @property
    def analyzer_type(self) -> str:
        """Return analyzer identifier."""
        return "cross_product"

    def analyze(
        self, lookback_hours: int = DEFAULT_LOOKBACK_HOURS
    ) -> List[GoalProposal]:
        """Analyze cross-product patterns and performance differences."""
        if self._engine is None:
            return []

        workflows = self._query_workflows(lookback_hours)
        if not workflows:
            return []

        by_product = _group_by_product(workflows)
        if len(by_product) < MIN_PRODUCT_TYPES_CROSS:
            return []

        stats = _compute_product_stats(by_product)
        proposals = _find_performance_gaps(stats)

        if self._learning_store is not None:
            proposals.extend(_cross_ref_patterns(self._learning_store, by_product))

        return proposals

    def _query_workflows(self, lookback_hours: int) -> list:
        """Query completed workflows with product_type set."""
        from src.storage.database.datetime_utils import utcnow
        from src.storage.database.models import WorkflowExecution

        cutoff = utcnow() - timedelta(hours=lookback_hours)
        with Session(self._engine) as session:
            return list(session.exec(
                select(WorkflowExecution).where(
                    WorkflowExecution.start_time >= cutoff,
                    WorkflowExecution.product_type.is_not(None),  # type: ignore[union-attr]
                    WorkflowExecution.status == "completed",
                )
            ).all())


def _group_by_product(workflows: list) -> dict[str, list]:
    """Group workflows by product_type."""
    by_product: dict[str, list] = {}
    for wf in workflows:
        if wf.product_type:
            by_product.setdefault(wf.product_type, []).append(wf)
    return by_product


def _compute_product_stats(by_product: dict[str, list]) -> dict[str, dict]:
    """Compute avg cost and duration per product type."""
    stats: dict[str, dict] = {}
    for ptype, wfs in by_product.items():
        costs = [wf.total_cost_usd for wf in wfs if wf.total_cost_usd]
        durations = [wf.duration_seconds for wf in wfs if wf.duration_seconds]
        stats[ptype] = {
            "total": len(wfs),
            "avg_cost": sum(costs) / len(costs) if costs else 0,
            "avg_duration": sum(durations) / len(durations) if durations else 0,
            "workflow_ids": [wf.id for wf in wfs[:EVIDENCE_WORKFLOW_LIMIT]],
        }
    return stats


def _find_performance_gaps(stats: dict[str, dict]) -> List[GoalProposal]:
    """Find product types with significantly better performance."""
    proposals: List[GoalProposal] = []
    types = list(stats.keys())

    for i, source in enumerate(types):
        src_dur = stats[source]["avg_duration"]
        if src_dur == 0:
            continue
        for target in types[i + 1:]:
            tgt_dur = stats[target]["avg_duration"]
            if tgt_dur == 0:
                continue
            ratio = tgt_dur / src_dur
            if ratio > PERFORMANCE_RATIO_THRESHOLD:
                improvement = ((tgt_dur - src_dur) / tgt_dur) * PCT_MULTIPLIER
                proposals.append(_make_cross_proposal(
                    source, target, stats[source], stats[target], improvement,
                ))
    return proposals


def _make_cross_proposal(
    source: str, target: str, src_stats: dict, tgt_stats: dict, improvement: float,
) -> GoalProposal:
    """Build a cross-product opportunity proposal."""
    return GoalProposal(
        goal_type=GoalType.CROSS_PRODUCT_OPPORTUNITY,
        title=f"Apply {source} patterns to {target}",
        description=(
            f"Product type '{source}' shows significantly better "
            f"duration than '{target}'. Transferring successful "
            f"patterns could yield {improvement:.0f}% improvement."
        ),
        risk_assessment=RiskAssessment(
            level=GoalRiskLevel.MEDIUM, blast_radius=f"product:{target}", reversible=True,
        ),
        effort_estimate=EffortLevel.MEDIUM,
        expected_impacts=[ImpactEstimate(
            metric_name="avg_duration",
            current_value=tgt_stats["avg_duration"],
            expected_value=src_stats["avg_duration"],
            improvement_pct=improvement, confidence=CROSS_CONFIDENCE,
        )],
        evidence=GoalEvidence(
            workflow_ids=src_stats["workflow_ids"] + tgt_stats["workflow_ids"],
            metrics={"source_duration": src_stats["avg_duration"], "target_duration": tgt_stats["avg_duration"]},
            analysis_summary=f"Cross-product opportunity: {source} -> {target} ({improvement:.0f}% potential)",
        ),
        source_product_type=source,
        applicable_product_types=[target],
        proposed_actions=[
            f"Review '{source}' workflow configuration",
            f"Adapt successful patterns for '{target}'",
            "Run A/B test to validate improvement",
        ],
    )


def _fetch_active_patterns(learning_store: object) -> list:
    """Fetch active patterns from the learning store, or empty list."""
    try:
        from src.learning.store import LearningStore

        if not isinstance(learning_store, LearningStore):
            return []
        return learning_store.list_patterns(status="active", limit=PATTERN_LIST_LIMIT)
    except (ImportError, AttributeError):
        return []


def _cross_ref_patterns(
    learning_store: object, by_product: dict[str, list]
) -> List[GoalProposal]:
    """Cross-reference learned patterns with product types."""
    patterns = _fetch_active_patterns(learning_store)
    if not patterns:
        return []

    product_types = set(by_product.keys())
    product_wf_ids = {pt: {wf.id for wf in wfs} for pt, wfs in by_product.items()}
    proposals: List[GoalProposal] = []

    for pattern in patterns:
        if not pattern.source_workflow_ids:
            continue
        source_types = {
            pt for pt, wf_ids in product_wf_ids.items()
            if set(pattern.source_workflow_ids) & wf_ids
        }
        missing = product_types - source_types
        if source_types and missing:
            proposals.append(_make_pattern_proposal(pattern, source_types, missing, product_types))

    return proposals


def _make_pattern_proposal(
    pattern: Any, source_types: set, missing: set, all_types: set
) -> GoalProposal:
    """Build a proposal for applying a learned pattern to new product types."""
    return GoalProposal(
        goal_type=GoalType.CROSS_PRODUCT_OPPORTUNITY,
        title=f"Apply pattern '{pattern.title}' to {', '.join(sorted(missing))}",
        description=(
            f"Pattern '{pattern.title}' (confidence: {pattern.confidence:.2f}) "
            f"has been validated in {', '.join(sorted(source_types))} "
            f"but not yet applied to {', '.join(sorted(missing))}."
        ),
        risk_assessment=RiskAssessment(
            level=GoalRiskLevel.LOW, blast_radius=f"products:{','.join(sorted(missing))}", reversible=True,
        ),
        effort_estimate=EffortLevel.SMALL,
        expected_impacts=[ImpactEstimate(
            metric_name="pattern_coverage",
            current_value=float(len(source_types)),
            expected_value=float(len(all_types)),
            improvement_pct=float(len(missing)) / float(len(all_types)) * PCT_MULTIPLIER,
            confidence=pattern.confidence,
        )],
        evidence=GoalEvidence(
            pattern_ids=[pattern.id],
            analysis_summary=(
                f"Pattern from {', '.join(sorted(source_types))} "
                f"applicable to {', '.join(sorted(missing))}"
            ),
        ),
        source_product_type=sorted(source_types)[0],
        applicable_product_types=sorted(missing),
        proposed_actions=[f"Review pattern: {pattern.title}", f"Apply to: {', '.join(sorted(missing))}"],
    )
