"""Integration tests for portfolio module."""

import os
import tempfile
import uuid

import pytest
import yaml

from src.portfolio._schemas import PortfolioConfig, ProductDefinition
from src.portfolio.component_analyzer import ComponentAnalyzer
from src.portfolio.knowledge_graph import KnowledgePopulator, KnowledgeQuery
from src.portfolio.models import PortfolioRecord, ProductRunRecord
from src.portfolio.optimizer import PortfolioOptimizer
from src.portfolio.scheduler import ResourceScheduler
from src.portfolio.store import PortfolioStore

MEMORY_DB = "sqlite:///:memory:"


@pytest.fixture
def store():
    return PortfolioStore(database_url=MEMORY_DB)


def _make_workflow(tmpdir, name, stages):
    """Create a temporary workflow YAML."""
    path = os.path.join(tmpdir, f"{name}.yaml")
    data = {"workflow": {"stages": stages}}
    with open(path, "w") as f:
        yaml.dump(data, f)
    return path


class TestFullWorkflow:
    def test_full_workflow(self, store):
        """Load portfolio → schedule → record runs → scorecards → recommendations."""
        portfolio = PortfolioConfig(
            name="integration",
            products=[
                ProductDefinition(name="web_app", weight=2.0, max_concurrent=3),
                ProductDefinition(name="api", weight=1.0, max_concurrent=2),
            ],
            max_total_concurrent=8,
        )

        scheduler = ResourceScheduler(store=store)
        optimizer = PortfolioOptimizer(store=store)

        # Schedule and run several products
        for i in range(6):
            product = scheduler.next_product(portfolio)
            assert product is not None
            scheduler.record_start(product, f"wf-{i}", portfolio_id="p1")
            scheduler.record_complete(
                product, f"wf-{i}", cost_usd=0.5, success=i % 3 != 0,
            )

        # Compute scorecards and recommendations
        scorecards = optimizer.compute_scorecards(portfolio)
        assert len(scorecards) == 2

        recommendations = optimizer.recommend(scorecards)
        assert len(recommendations) == 2
        for rec in recommendations:
            assert rec.rationale != ""

    def test_scheduler_with_optimizer(self, store):
        """Run scheduler, compute scores, get weight suggestions."""
        portfolio = PortfolioConfig(
            name="sched-opt",
            products=[
                ProductDefinition(name="web_app", weight=1.0, max_concurrent=5),
                ProductDefinition(name="api", weight=1.0, max_concurrent=5),
            ],
        )
        scheduler = ResourceScheduler(store=store)
        optimizer = PortfolioOptimizer(store=store)

        # Run web_app with high success, api with low success
        for i in range(10):
            scheduler.record_start("web_app", f"wf-wa-{i}")
            scheduler.record_complete("web_app", f"wf-wa-{i}", cost_usd=1.0, success=True)
        for i in range(10):
            scheduler.record_start("api", f"wf-api-{i}")
            scheduler.record_complete("api", f"wf-api-{i}", cost_usd=1.0, success=i < 3)

        scorecards = optimizer.compute_scorecards(portfolio)
        weights = optimizer.optimize_weights(portfolio, scorecards)

        # web_app should get higher weight due to better performance
        assert weights["web_app"] > weights["api"]


class TestKnowledgeGraphLifecycle:
    def test_knowledge_graph_lifecycle(self, store):
        """Populate from config → query → find path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            wf_path = _make_workflow(tmpdir, "wf1", [
                {"name": "build", "agents": ["builder_agent"]},
                {"name": "test", "agents": ["test_agent"]},
            ])
            portfolio = PortfolioConfig(
                name="kg-test",
                products=[
                    ProductDefinition(name="web_app", workflow_configs=[wf_path]),
                ],
            )
            populator = KnowledgePopulator(store)
            query = KnowledgeQuery(store)

            added = populator.populate_from_config(portfolio)
            assert added >= 1

            related = query.get_related_concepts("web_app", depth=2)
            names = {r["name"] for r in related}
            assert "build" in names

            path = query.find_path("web_app", "builder_agent")
            assert path is not None
            assert path[0] == "web_app"
            assert path[-1] == "builder_agent"

    def test_knowledge_query_after_runs(self, store):
        """Populate from runs, query outcomes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            wf_path = _make_workflow(tmpdir, "wf1", [
                {"name": "build", "agents": ["a1"]},
            ])
            portfolio = PortfolioConfig(
                name="run-test",
                products=[
                    ProductDefinition(name="web_app", workflow_configs=[wf_path]),
                ],
            )
            populator = KnowledgePopulator(store)
            query = KnowledgeQuery(store)

            populator.populate_from_config(portfolio)

            store.save_product_run(ProductRunRecord(
                id=str(uuid.uuid4()),
                portfolio_id="p1",
                product_type="web_app",
                workflow_id="wf-1",
                status="completed",
                success=True,
            ))
            added = populator.populate_from_runs("web_app")
            assert added >= 1

            stats = query.concept_stats()
            assert stats["concepts_by_type"].get("outcome", 0) >= 1


class TestComponentAnalysisLifecycle:
    def test_component_analysis_lifecycle(self, store):
        """Create similar stages → analyze → verify matches."""
        with tempfile.TemporaryDirectory() as tmpdir:
            stage_def = {
                "name": "validate",
                "timeout": 300,
                "retries": 3,
                "error_handling": "retry",
                "agents": ["validator"],
            }
            wf1 = _make_workflow(tmpdir, "wf1", [stage_def])
            # Use the same stages structure for wf2 (ensure YAML not workflow wrapper)
            wf2_path = os.path.join(tmpdir, "wf2.yaml")
            with open(wf1) as f:
                content = f.read()
            with open(wf2_path, "w") as f:
                f.write(content)

            portfolio = PortfolioConfig(
                name="comp-test",
                products=[
                    ProductDefinition(name="web_app", workflow_configs=[wf1]),
                    ProductDefinition(name="api", workflow_configs=[wf2_path]),
                ],
            )
            analyzer = ComponentAnalyzer(store=store)
            matches = analyzer.analyze_portfolio(portfolio)

            stored = store.list_shared_components()
            assert len(stored) == len(matches)


class TestPortfolioStoreRoundTrip:
    def test_save_list_reload(self, store):
        record = PortfolioRecord(
            id=str(uuid.uuid4()),
            name="round-trip",
            description="Test round trip",
            config={"strategy": "weighted", "products": []},
            enabled=True,
        )
        store.save_portfolio(record)

        portfolios = store.list_portfolios()
        assert any(p.name == "round-trip" for p in portfolios)

        reloaded = store.get_portfolio("round-trip")
        assert reloaded is not None
        assert reloaded.config["strategy"] == "weighted"


class TestSchedulerBudgetTracking:
    def test_scheduler_budget_tracking(self, store):
        """Run until budget exceeded."""
        portfolio = PortfolioConfig(
            name="budget-track",
            products=[
                ProductDefinition(
                    name="web_app", weight=1.0, max_concurrent=5,
                    budget_limit_usd=5.0,
                ),
            ],
        )
        scheduler = ResourceScheduler(store=store)

        for i in range(10):
            if not scheduler.can_execute(portfolio, "web_app"):
                break
            scheduler.record_start("web_app", f"wf-{i}")
            scheduler.record_complete(
                "web_app", f"wf-{i}", cost_usd=1.0, success=True,
            )

        # Should have stopped at 5 runs (5 * $1 = $5 budget)
        total_cost = store.get_total_cost("web_app")
        assert total_cost == pytest.approx(5.0)
        assert scheduler.can_execute(portfolio, "web_app") is False


class TestEmptyPortfolioHandling:
    def test_empty_portfolio_handling(self, store):
        """All operations work with empty portfolio."""
        portfolio = PortfolioConfig(name="empty", products=[])

        scheduler = ResourceScheduler(store=store)
        optimizer = PortfolioOptimizer(store=store)
        analyzer = ComponentAnalyzer(store=store)

        assert scheduler.next_product(portfolio) is None
        assert scheduler.get_allocation_status(portfolio) == {}
        assert optimizer.compute_scorecards(portfolio) == []
        assert optimizer.recommend([]) == []
        assert analyzer.analyze_portfolio(portfolio) == []
