"""4-metric scorecard optimizer with portfolio recommendations."""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Tuple

from src.portfolio._schemas import (
    OptimizationAction,
    PortfolioConfig,
    PortfolioRecommendation,
    ProductScorecard,
)
from src.portfolio._tracking import track_portfolio_event
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
from src.portfolio.models import ProductRunRecord
from src.portfolio.store import PortfolioStore
from src.storage.database.datetime_utils import ensure_utc, utcnow

logger = logging.getLogger(__name__)

PCT_MULTIPLIER = 100.0  # noqa: scanner: skip-magic


def _utc_at_or_after(run: ProductRunRecord, cutoff: datetime) -> bool:
    """Check if a run's start time is at or after a cutoff."""
    dt = ensure_utc(run.started_at)
    return dt is not None and dt >= cutoff


def _utc_before(run: ProductRunRecord, cutoff: datetime) -> bool:
    """Check if a run's start time is before a cutoff."""
    dt = ensure_utc(run.started_at)
    return dt is not None and dt < cutoff


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
        track_portfolio_event(
            "optimizer_scorecards",
            {"product_count": len(scorecards), "lookback_hours": lookback_hours},
            "computed",
            impact_metrics={
                sc.product_type: sc.composite_score for sc in scorecards
            },
            tags=["portfolio", "optimizer"],
        )
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
        track_portfolio_event(
            "optimizer_recommendations",
            {"product_count": len(recommendations)},
            "computed",
            impact_metrics={
                r.product_type: r.action.value for r in recommendations
            },
            tags=["portfolio", "optimizer"],
        )
        return recommendations

    def optimize_weights(
        self,
        scorecards: List[ProductScorecard],
    ) -> Dict[str, float]:
        """Suggest new weights proportional to composite scores."""
        total_score = sum(sc.composite_score for sc in scorecards)
        if total_score <= 0:
            count = len(scorecards) if scorecards else 1
            weights = {sc.product_type: 1.0 / count for sc in scorecards}
        else:
            weights = {
                sc.product_type: sc.composite_score / total_score
                for sc in scorecards
            }
        track_portfolio_event(
            "optimizer_weights",
            {"product_count": len(scorecards), "total_score": total_score},
            "computed",
            impact_metrics=weights,
            tags=["portfolio", "optimizer"],
        )
        return weights

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

        period_runs = [r for r in runs if _utc_at_or_after(r, lookback_cutoff)]

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


def _classify_action(sc: ProductScorecard) -> Tuple[OptimizationAction, str]:
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


def _calc_success_rate(runs: List[ProductRunRecord]) -> float:
    """Successful / total, 0.0 if no runs."""
    if not runs:
        return 0.0
    successful = sum(1 for r in runs if r.success)
    return successful / len(runs)


def _calc_cost_efficiency(runs: List[ProductRunRecord]) -> float:
    """success_count / total_cost, normalized 0-1, capped at 1.0."""
    if not runs:
        return 0.0
    successful = sum(1 for r in runs if r.success)
    total_cost = sum(r.cost_usd for r in runs)
    if total_cost <= 0:
        return 0.0
    raw = successful / total_cost
    return min(1.0, raw)


def _calc_trend(runs: List[ProductRunRecord], recent_cutoff: datetime) -> float:
    """recent_success_rate - historical_success_rate."""
    recent = [r for r in runs if _utc_at_or_after(r, recent_cutoff)]
    historical = [r for r in runs if _utc_before(r, recent_cutoff)]
    recent_rate = _calc_success_rate(recent)
    historical_rate = _calc_success_rate(historical)
    return recent_rate - historical_rate


def _calc_utilization(
    runs: List[ProductRunRecord], max_concurrent: int, lookback_hours: int,
) -> float:
    """actual_runs / (max_concurrent * time_factor), capped at 1.0."""
    if max_concurrent <= 0 or lookback_hours <= 0:
        return 0.0
    time_factor = lookback_hours / 24  # intentional: normalize to days
    capacity = max_concurrent * time_factor
    if capacity <= 0:
        return 0.0
    return min(1.0, len(runs) / capacity)
