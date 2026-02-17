"""4-metric scorecard optimizer with portfolio recommendations."""

import logging
from datetime import timedelta
from typing import Dict, List

from src.portfolio._schemas import (
    OptimizationAction,
    PortfolioConfig,
    PortfolioRecommendation,
    ProductScorecard,
)
from src.portfolio.constants import (
    DEFAULT_LOOKBACK_HOURS,
    RECENT_LOOKBACK_HOURS,
    THRESHOLD_INVEST,
    THRESHOLD_MAINTAIN,
    THRESHOLD_REDUCE,
    TREND_NEGATIVE_THRESHOLD,
    TREND_OFFSET,
    WEIGHT_COST_EFFICIENCY,
    WEIGHT_SUCCESS_RATE,
    WEIGHT_TREND,
    WEIGHT_UTILIZATION,
)
from src.portfolio.store import PortfolioStore
from src.storage.database.datetime_utils import ensure_utc, utcnow

logger = logging.getLogger(__name__)


class PortfolioOptimizer:
    """Computes scorecards and generates portfolio recommendations."""

    def __init__(self, store: PortfolioStore) -> None:
        self.store = store

    def compute_scorecards(
        self,
        portfolio: PortfolioConfig,
        lookback_hours: int = DEFAULT_LOOKBACK_HOURS,
    ) -> List[ProductScorecard]:
        """Compute a 4-metric scorecard for each product."""
        scorecards: List[ProductScorecard] = []
        for product in portfolio.products:
            scorecard = self._compute_product_scorecard(
                product.name,
                product.max_concurrent,
                lookback_hours,
            )
            scorecards.append(scorecard)
        return scorecards

    def recommend(
        self, scorecards: List[ProductScorecard],
    ) -> List[PortfolioRecommendation]:
        """Generate an action recommendation for each product scorecard."""
        recommendations: List[PortfolioRecommendation] = []
        for sc in scorecards:
            action, rationale = _classify_action(sc)
            recommendations.append(
                PortfolioRecommendation(
                    product_type=sc.product_type,
                    action=action,
                    scorecard=sc,
                    rationale=rationale,
                )
            )
        return recommendations

    def optimize_weights(
        self,
        portfolio: PortfolioConfig,
        scorecards: List[ProductScorecard],
    ) -> Dict[str, float]:
        """Suggest new weights proportional to composite scores."""
        total_score = sum(sc.composite_score for sc in scorecards)
        if total_score <= 0:
            count = len(scorecards) if scorecards else 1
            return {sc.product_type: 1.0 / count for sc in scorecards}

        return {
            sc.product_type: sc.composite_score / total_score
            for sc in scorecards
        }

    def _compute_product_scorecard(
        self,
        product_type: str,
        max_concurrent: int,
        lookback_hours: int,
    ) -> ProductScorecard:
        """Build a scorecard for a single product type."""
        runs = self.store.list_product_runs(product_type=product_type)
        now = utcnow()
        lookback_cutoff = now - timedelta(hours=lookback_hours)
        recent_cutoff = now - timedelta(hours=RECENT_LOOKBACK_HOURS)

        period_runs = [
            r for r in runs
            if r.started_at is not None
            and ensure_utc(r.started_at) >= lookback_cutoff
        ]

        success_rate = _calc_success_rate(period_runs)
        cost_efficiency = _calc_cost_efficiency(period_runs)
        trend = _calc_trend(period_runs, recent_cutoff)
        utilization = _calc_utilization(
            period_runs, max_concurrent, lookback_hours,
        )

        trend_clamped = max(0.0, min(1.0, trend + TREND_OFFSET))
        composite = (
            WEIGHT_SUCCESS_RATE * success_rate
            + WEIGHT_COST_EFFICIENCY * cost_efficiency
            + WEIGHT_TREND * trend_clamped
            + WEIGHT_UTILIZATION * utilization
        )

        return ProductScorecard(
            product_type=product_type,
            success_rate=success_rate,
            cost_efficiency=cost_efficiency,
            trend=trend,
            utilization=utilization,
            composite_score=composite,
        )


def _fmt_trend(value: float) -> str:
    """Format trend value with sign."""
    return f"{value:+.2f}"


def _classify_action(sc: ProductScorecard):
    """Determine OptimizationAction and rationale from a scorecard."""
    score = sc.composite_score
    trend = sc.trend
    t = _fmt_trend(trend)

    if score >= THRESHOLD_INVEST and trend > 0:
        return (
            OptimizationAction.INVEST,
            f"High composite ({score:.2f}) with positive trend ({t})",
        )
    if score >= THRESHOLD_MAINTAIN:
        return (
            OptimizationAction.MAINTAIN,
            f"Adequate composite ({score:.2f}), maintain current allocation",
        )
    if score >= THRESHOLD_REDUCE or trend < TREND_NEGATIVE_THRESHOLD:
        return (
            OptimizationAction.REDUCE,
            f"Below target ({score:.2f}) or negative trend ({t})",
        )
    return (
        OptimizationAction.SUNSET,
        f"Low composite ({score:.2f}) with non-positive trend ({t})",
    )


def _calc_success_rate(runs) -> float:
    """Successful / total, 0.0 if no runs."""
    if not runs:
        return 0.0
    successful = sum(1 for r in runs if r.success)
    return successful / len(runs)


def _calc_cost_efficiency(runs) -> float:
    """success_count / total_cost, normalized 0-1, capped at 1.0."""
    if not runs:
        return 0.0
    successful = sum(1 for r in runs if r.success)
    total_cost = sum(r.cost_usd for r in runs)
    if total_cost <= 0:
        return 0.0
    raw = successful / total_cost
    return min(1.0, raw)


def _calc_trend(runs, recent_cutoff) -> float:
    """recent_success_rate - historical_success_rate."""
    recent = [
        r for r in runs
        if r.started_at is not None
        and ensure_utc(r.started_at) >= recent_cutoff
    ]
    historical = [
        r for r in runs
        if r.started_at is not None
        and ensure_utc(r.started_at) < recent_cutoff
    ]
    recent_rate = _calc_success_rate(recent)
    historical_rate = _calc_success_rate(historical)
    return recent_rate - historical_rate


def _calc_utilization(
    runs, max_concurrent: int, lookback_hours: int,
) -> float:
    """actual_runs / (max_concurrent * time_factor), capped at 1.0."""
    if max_concurrent <= 0 or lookback_hours <= 0:
        return 0.0
    time_factor = lookback_hours / 24  # intentional: normalize to days
    capacity = max_concurrent * time_factor
    if capacity <= 0:
        return 0.0
    return min(1.0, len(runs) / capacity)
