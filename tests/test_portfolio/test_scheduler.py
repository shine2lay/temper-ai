"""Tests for ResourceScheduler."""

import uuid

import pytest

from temper_ai.portfolio._schemas import PortfolioConfig, ProductDefinition
from temper_ai.portfolio.models import ProductRunRecord
from temper_ai.portfolio.scheduler import ResourceScheduler
from temper_ai.portfolio.store import PortfolioStore

MEMORY_DB = "sqlite:///:memory:"


@pytest.fixture
def store():
    return PortfolioStore(database_url=MEMORY_DB)


@pytest.fixture
def scheduler(store):
    return ResourceScheduler(store=store)


@pytest.fixture
def two_product_portfolio():
    return PortfolioConfig(
        name="test",
        products=[
            ProductDefinition(name="web_app", weight=2.0, max_concurrent=2),
            ProductDefinition(name="api", weight=1.0, max_concurrent=2),
        ],
        max_total_concurrent=8,
    )


@pytest.fixture
def single_product_portfolio():
    return PortfolioConfig(
        name="single",
        products=[
            ProductDefinition(name="web_app", weight=1.0, max_concurrent=2),
        ],
    )


class TestNextProduct:
    def test_next_product_empty_portfolio(self, scheduler):
        empty = PortfolioConfig(name="empty", products=[])
        result = scheduler.next_product(empty)
        assert result is None

    def test_next_product_single(self, scheduler, single_product_portfolio):
        result = scheduler.next_product(single_product_portfolio)
        assert result == "web_app"

    def test_next_product_equal_weights(self, scheduler):
        portfolio = PortfolioConfig(
            name="equal",
            products=[
                ProductDefinition(name="a", weight=1.0, max_concurrent=5),
                ProductDefinition(name="b", weight=1.0, max_concurrent=5),
            ],
        )
        # Both have 0 runs so vtime = 0/1.0 = 0 for both; first wins
        result = scheduler.next_product(portfolio)
        assert result in ("a", "b")

    def test_next_product_weighted(self, scheduler, store, two_product_portfolio):
        # Give api 2 completed runs so its vtime = 2/1.0 = 2.0
        # web_app has 0 runs so vtime = 0/2.0 = 0.0 → selected
        for _ in range(2):
            store.save_product_run(
                ProductRunRecord(
                    id=str(uuid.uuid4()),
                    portfolio_id="p1",
                    product_type="api",
                    workflow_id="wf1",
                    status="completed",
                )
            )
        result = scheduler.next_product(two_product_portfolio)
        assert result == "web_app"

    def test_next_product_all_at_capacity(self, scheduler, store):
        portfolio = PortfolioConfig(
            name="full",
            products=[
                ProductDefinition(name="web_app", weight=1.0, max_concurrent=1),
            ],
        )
        store.save_product_run(
            ProductRunRecord(
                id=str(uuid.uuid4()),
                portfolio_id="p1",
                product_type="web_app",
                workflow_id="wf1",
                status="running",
            )
        )
        result = scheduler.next_product(portfolio)
        assert result is None


class TestCanExecute:
    def test_can_execute_under_limit(self, scheduler, two_product_portfolio):
        assert scheduler.can_execute(two_product_portfolio, "web_app") is True

    def test_can_execute_at_capacity(self, scheduler, store):
        portfolio = PortfolioConfig(
            name="cap",
            products=[
                ProductDefinition(name="web_app", weight=1.0, max_concurrent=1),
            ],
        )
        store.save_product_run(
            ProductRunRecord(
                id=str(uuid.uuid4()),
                portfolio_id="p1",
                product_type="web_app",
                workflow_id="wf1",
                status="running",
            )
        )
        assert scheduler.can_execute(portfolio, "web_app") is False

    def test_can_execute_budget_exceeded(self, scheduler, store):
        portfolio = PortfolioConfig(
            name="budget",
            products=[
                ProductDefinition(
                    name="web_app",
                    weight=1.0,
                    max_concurrent=5,
                    budget_limit_usd=10.0,
                ),
            ],
        )
        store.save_product_run(
            ProductRunRecord(
                id=str(uuid.uuid4()),
                portfolio_id="p1",
                product_type="web_app",
                workflow_id="wf1",
                status="completed",
                cost_usd=10.0,
            )
        )
        assert scheduler.can_execute(portfolio, "web_app") is False

    def test_can_execute_unlimited_budget(self, scheduler, store):
        portfolio = PortfolioConfig(
            name="unlimited",
            products=[
                ProductDefinition(
                    name="web_app",
                    weight=1.0,
                    max_concurrent=5,
                    budget_limit_usd=0.0,
                ),
            ],
        )
        store.save_product_run(
            ProductRunRecord(
                id=str(uuid.uuid4()),
                portfolio_id="p1",
                product_type="web_app",
                workflow_id="wf1",
                status="completed",
                cost_usd=999.0,
            )
        )
        assert scheduler.can_execute(portfolio, "web_app") is True

    def test_total_concurrent_limit(self, scheduler, store):
        portfolio = PortfolioConfig(
            name="total-cap",
            products=[
                ProductDefinition(name="web_app", weight=1.0, max_concurrent=10),
            ],
            max_total_concurrent=1,
        )
        store.save_product_run(
            ProductRunRecord(
                id=str(uuid.uuid4()),
                portfolio_id="p1",
                product_type="web_app",
                workflow_id="wf1",
                status="running",
            )
        )
        assert scheduler.can_execute(portfolio, "web_app") is False


class TestRecordLifecycle:
    def test_record_start_creates_run(self, scheduler, store):
        scheduler.record_start("web_app", "wf-123", portfolio_id="p1")
        runs = store.list_product_runs(product_type="web_app")
        assert len(runs) == 1
        assert runs[0].status == "running"
        assert runs[0].workflow_id == "wf-123"

    def test_record_complete_updates_run(self, scheduler, store):
        scheduler.record_start("web_app", "wf-456", portfolio_id="p1")
        scheduler.record_complete("web_app", "wf-456", cost_usd=2.5, success=True)
        runs = store.list_product_runs(product_type="web_app")
        assert len(runs) == 1
        assert runs[0].status == "completed"
        assert runs[0].cost_usd == pytest.approx(2.5)
        assert runs[0].success is True

    def test_record_start_with_portfolio_id(self, scheduler, store):
        scheduler.record_start("api", "wf-789", portfolio_id="my-portfolio")
        runs = store.list_product_runs(product_type="api")
        assert runs[0].portfolio_id == "my-portfolio"

    def test_concurrent_tracking(self, scheduler, store):
        PortfolioConfig(
            name="track",
            products=[
                ProductDefinition(name="web_app", weight=1.0, max_concurrent=5),
            ],
        )
        scheduler.record_start("web_app", "wf-a")
        scheduler.record_start("web_app", "wf-b")
        assert store.count_product_runs("web_app", status="running") == 2

        scheduler.record_complete("web_app", "wf-a", cost_usd=1.0, success=True)
        assert store.count_product_runs("web_app", status="running") == 1


class TestAllocationStatus:
    def test_get_allocation_status(self, scheduler, store, two_product_portfolio):
        scheduler.record_start("web_app", "wf-1", portfolio_id="p1")
        scheduler.record_start("web_app", "wf-2", portfolio_id="p1")
        scheduler.record_complete("web_app", "wf-1", cost_usd=3.0, success=True)

        status = scheduler.get_allocation_status(two_product_portfolio)
        assert "web_app" in status
        assert "api" in status
        web_status = status["web_app"]
        assert web_status.active_runs == 1
        assert web_status.completed_runs == 2
        assert web_status.budget_used_usd == pytest.approx(3.0)

    def test_allocation_utilization(self, scheduler, store):
        portfolio = PortfolioConfig(
            name="util",
            products=[
                ProductDefinition(name="web_app", weight=1.0, max_concurrent=4),
            ],
        )
        scheduler.record_start("web_app", "wf-1")
        scheduler.record_start("web_app", "wf-2")

        status = scheduler.get_allocation_status(portfolio)
        assert status["web_app"].utilization == pytest.approx(0.5)


class TestWFQFairness:
    def test_wfq_fairness(self, scheduler, store, two_product_portfolio):
        """After many rounds, distribution should approximate weight ratio 2:1."""
        selections = {"web_app": 0, "api": 0}
        rounds = 30  # scanner: skip-magic

        for i in range(rounds):
            product = scheduler.next_product(two_product_portfolio)
            assert product is not None
            selections[product] += 1
            scheduler.record_start(product, f"wf-{i}")
            scheduler.record_complete(product, f"wf-{i}", cost_usd=0.1, success=True)

        # web_app (weight=2.0) should get ~2x the runs of api (weight=1.0)
        ratio = selections["web_app"] / max(selections["api"], 1)
        assert ratio == pytest.approx(2.0, abs=0.5)

    def test_budget_enforcement(self, scheduler, store):
        portfolio = PortfolioConfig(
            name="budget-test",
            products=[
                ProductDefinition(
                    name="web_app",
                    weight=1.0,
                    max_concurrent=5,
                    budget_limit_usd=5.0,
                ),
            ],
        )
        for i in range(5):
            scheduler.record_start("web_app", f"wf-{i}")
            scheduler.record_complete(
                "web_app",
                f"wf-{i}",
                cost_usd=1.0,
                success=True,
            )

        # Budget is now 5.0 == limit, should be blocked
        assert scheduler.can_execute(portfolio, "web_app") is False
