"""Tests for PortfolioOptimizer."""

import uuid
from datetime import timedelta

import pytest

from temper_ai.portfolio._schemas import (
    OptimizationAction,
    PortfolioConfig,
    ProductDefinition,
    ProductScorecard,
)
from temper_ai.portfolio.constants import (
    TREND_OFFSET,
    WEIGHT_COST_EFFICIENCY,
    WEIGHT_SUCCESS_RATE,
    WEIGHT_TREND,
    WEIGHT_UTILIZATION,
)
from temper_ai.portfolio.models import ProductRunRecord
from temper_ai.portfolio.optimizer import PortfolioOptimizer
from temper_ai.portfolio.store import PortfolioStore
from temper_ai.storage.database.datetime_utils import utcnow

MEMORY_DB = "sqlite:///:memory:"


@pytest.fixture
def store():
    return PortfolioStore(database_url=MEMORY_DB)


@pytest.fixture
def optimizer(store):
    return PortfolioOptimizer(store=store)


@pytest.fixture
def portfolio():
    return PortfolioConfig(
        name="test",
        products=[
            ProductDefinition(name="web_app", weight=2.0, max_concurrent=2),
            ProductDefinition(name="api", weight=1.0, max_concurrent=2),
        ],
    )


def _create_runs(store, product_type, count, success_rate, cost, age_hours=0):
    """Insert test runs. age_hours shifts started_at into the past."""
    now = utcnow()
    successful = int(count * success_rate)
    for i in range(count):
        store.save_product_run(
            ProductRunRecord(
                id=str(uuid.uuid4()),
                portfolio_id="p1",
                product_type=product_type,
                workflow_id=f"wf-{i}",
                status="completed",
                cost_usd=cost,
                success=i < successful,
                started_at=now - timedelta(hours=age_hours),
                completed_at=now,
            )
        )


class TestComputeScorecards:
    def test_compute_scorecards_no_runs(self, optimizer, portfolio):
        scorecards = optimizer.compute_scorecards(portfolio)
        assert len(scorecards) == 2
        for sc in scorecards:
            assert sc.success_rate == 0.0
            assert sc.cost_efficiency == 0.0

    def test_compute_scorecards_all_success(self, optimizer, store, portfolio):
        _create_runs(store, "web_app", 10, 1.0, 1.0)
        scorecards = optimizer.compute_scorecards(portfolio)
        web_sc = next(sc for sc in scorecards if sc.product_type == "web_app")
        assert web_sc.success_rate == pytest.approx(1.0)

    def test_compute_scorecards_mixed(self, optimizer, store, portfolio):
        _create_runs(store, "web_app", 10, 0.6, 1.0)
        scorecards = optimizer.compute_scorecards(portfolio)
        web_sc = next(sc for sc in scorecards if sc.product_type == "web_app")
        assert web_sc.success_rate == pytest.approx(0.6)

    def test_compute_scorecards_cost_efficiency(self, optimizer, store, portfolio):
        _create_runs(store, "api", 10, 0.5, 2.0)
        scorecards = optimizer.compute_scorecards(portfolio)
        api_sc = next(sc for sc in scorecards if sc.product_type == "api")
        # 5 successes / 20.0 total cost = 0.25
        assert api_sc.cost_efficiency == pytest.approx(0.25)

    def test_composite_score_weighted_average(self, optimizer, store, portfolio):
        _create_runs(store, "web_app", 10, 1.0, 1.0)
        scorecards = optimizer.compute_scorecards(portfolio)
        web_sc = next(sc for sc in scorecards if sc.product_type == "web_app")
        # Composite = weighted sum of 4 metrics
        expected = (
            WEIGHT_SUCCESS_RATE * web_sc.success_rate
            + WEIGHT_COST_EFFICIENCY * web_sc.cost_efficiency
            + WEIGHT_TREND * max(0.0, min(1.0, web_sc.trend + TREND_OFFSET))
            + WEIGHT_UTILIZATION * web_sc.utilization
        )
        assert web_sc.composite_score == pytest.approx(expected, abs=0.01)

    def test_single_product_scorecard(self, optimizer, store):
        portfolio = PortfolioConfig(
            name="single",
            products=[ProductDefinition(name="web_app", max_concurrent=2)],
        )
        _create_runs(store, "web_app", 5, 0.8, 1.0)
        scorecards = optimizer.compute_scorecards(portfolio)
        assert len(scorecards) == 1
        assert scorecards[0].product_type == "web_app"

    def test_empty_portfolio_scorecards(self, optimizer):
        portfolio = PortfolioConfig(name="empty", products=[])
        scorecards = optimizer.compute_scorecards(portfolio)
        assert scorecards == []


class TestTrend:
    def test_trend_positive(self, optimizer, store, portfolio):
        """Recent runs are all successful; older runs are mixed → positive trend."""
        now = utcnow()
        # Old runs (> 7 days ago) — 50% success
        for i in range(10):
            store.save_product_run(
                ProductRunRecord(
                    id=str(uuid.uuid4()),
                    portfolio_id="p1",
                    product_type="web_app",
                    workflow_id=f"old-{i}",
                    status="completed",
                    cost_usd=1.0,
                    success=i < 5,
                    started_at=now - timedelta(hours=200),
                )
            )
        # Recent runs (< 7 days ago) — 100% success
        for i in range(10):
            store.save_product_run(
                ProductRunRecord(
                    id=str(uuid.uuid4()),
                    portfolio_id="p1",
                    product_type="web_app",
                    workflow_id=f"new-{i}",
                    status="completed",
                    cost_usd=1.0,
                    success=True,
                    started_at=now - timedelta(hours=24),
                )
            )
        scorecards = optimizer.compute_scorecards(portfolio)
        web_sc = next(sc for sc in scorecards if sc.product_type == "web_app")
        assert web_sc.trend > 0

    def test_trend_negative(self, optimizer, store, portfolio):
        """Recent runs fail; older runs succeed → negative trend."""
        now = utcnow()
        for i in range(10):
            store.save_product_run(
                ProductRunRecord(
                    id=str(uuid.uuid4()),
                    portfolio_id="p1",
                    product_type="web_app",
                    workflow_id=f"old-{i}",
                    status="completed",
                    cost_usd=1.0,
                    success=True,
                    started_at=now - timedelta(hours=200),
                )
            )
        for i in range(10):
            store.save_product_run(
                ProductRunRecord(
                    id=str(uuid.uuid4()),
                    portfolio_id="p1",
                    product_type="web_app",
                    workflow_id=f"new-{i}",
                    status="completed",
                    cost_usd=1.0,
                    success=False,
                    started_at=now - timedelta(hours=24),
                )
            )
        scorecards = optimizer.compute_scorecards(portfolio)
        web_sc = next(sc for sc in scorecards if sc.product_type == "web_app")
        assert web_sc.trend < 0

    def test_trend_no_recent(self, optimizer, store, portfolio):
        """All runs are old → trend = 0.0 (no recent vs no historical split)."""
        now = utcnow()
        for i in range(10):
            store.save_product_run(
                ProductRunRecord(
                    id=str(uuid.uuid4()),
                    portfolio_id="p1",
                    product_type="web_app",
                    workflow_id=f"old-{i}",
                    status="completed",
                    cost_usd=1.0,
                    success=True,
                    started_at=now - timedelta(hours=200),
                )
            )
        scorecards = optimizer.compute_scorecards(portfolio)
        web_sc = next(sc for sc in scorecards if sc.product_type == "web_app")
        # No recent runs → recent_rate=0, hist_rate=1.0 → trend=-1.0
        assert web_sc.trend < 0


class TestRecommend:
    def test_recommend_invest(self, optimizer):
        sc = ProductScorecard(
            product_type="web_app",
            success_rate=0.9,
            cost_efficiency=0.8,
            trend=0.2,
            utilization=0.6,
            composite_score=0.80,
        )
        recs = optimizer.recommend([sc])
        assert len(recs) == 1
        assert recs[0].action == OptimizationAction.INVEST

    def test_recommend_maintain(self, optimizer):
        sc = ProductScorecard(
            product_type="web_app",
            composite_score=0.60,
            trend=0.0,
        )
        recs = optimizer.recommend([sc])
        assert recs[0].action == OptimizationAction.MAINTAIN

    def test_recommend_reduce(self, optimizer):
        sc = ProductScorecard(
            product_type="web_app",
            composite_score=0.30,
            trend=0.0,
        )
        recs = optimizer.recommend([sc])
        assert recs[0].action == OptimizationAction.REDUCE

    def test_recommend_sunset(self, optimizer):
        sc = ProductScorecard(
            product_type="web_app",
            composite_score=0.10,
            trend=0.0,
        )
        recs = optimizer.recommend([sc])
        assert recs[0].action == OptimizationAction.SUNSET

    def test_recommend_reduce_negative_trend(self, optimizer):
        sc = ProductScorecard(
            product_type="web_app",
            composite_score=0.30,
            trend=-0.2,
        )
        recs = optimizer.recommend([sc])
        assert recs[0].action == OptimizationAction.REDUCE


class TestOptimizeWeights:
    def test_optimize_weights(self, optimizer, portfolio):
        scorecards = [
            ProductScorecard(product_type="web_app", composite_score=0.8),
            ProductScorecard(product_type="api", composite_score=0.2),
        ]
        weights = optimizer.optimize_weights(scorecards)
        assert weights["web_app"] == pytest.approx(0.8)
        assert weights["api"] == pytest.approx(0.2)

    def test_optimize_weights_equal_scores(self, optimizer, portfolio):
        scorecards = [
            ProductScorecard(product_type="web_app", composite_score=0.5),
            ProductScorecard(product_type="api", composite_score=0.5),
        ]
        weights = optimizer.optimize_weights(scorecards)
        assert weights["web_app"] == pytest.approx(0.5)
        assert weights["api"] == pytest.approx(0.5)


class TestUtilization:
    def test_utilization_calculation(self, optimizer, store, portfolio):
        _create_runs(store, "web_app", 5, 1.0, 1.0)
        scorecards = optimizer.compute_scorecards(portfolio)
        web_sc = next(sc for sc in scorecards if sc.product_type == "web_app")
        # utilization = min(1.0, runs / (max_concurrent * hours/24))
        assert 0.0 <= web_sc.utilization <= 1.0
