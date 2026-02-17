"""Tests for PortfolioStore persistence."""

import uuid

import pytest

from src.portfolio.models import (
    KGConceptRecord,
    KGEdgeRecord,
    PortfolioRecord,
    PortfolioSnapshotRecord,
    ProductRunRecord,
    SharedComponentRecord,
    TechCompatibilityRecord,
)
from src.portfolio.store import PortfolioStore
from src.storage.database.datetime_utils import utcnow

MEMORY_DB = "sqlite:///:memory:"


@pytest.fixture
def store():
    return PortfolioStore(database_url=MEMORY_DB)


class TestPortfolioCRUD:
    def test_save_and_get(self, store):
        record = PortfolioRecord(
            id=str(uuid.uuid4()),
            name="test-portfolio",
            description="A test portfolio",
            config={"strategy": "weighted"},
            enabled=True,
        )
        store.save_portfolio(record)
        result = store.get_portfolio("test-portfolio")
        assert result is not None
        assert result.name == "test-portfolio"
        assert result.description == "A test portfolio"
        assert result.config == {"strategy": "weighted"}

    def test_get_nonexistent(self, store):
        result = store.get_portfolio("does-not-exist")
        assert result is None

    def test_list_portfolios(self, store):
        for i in range(3):
            store.save_portfolio(
                PortfolioRecord(
                    id=str(uuid.uuid4()),
                    name=f"portfolio-{i}",
                    enabled=i < 2,
                )
            )
        result = store.list_portfolios()
        assert len(result) == 3

    def test_list_enabled_only(self, store):
        store.save_portfolio(
            PortfolioRecord(id="1", name="enabled", enabled=True)
        )
        store.save_portfolio(
            PortfolioRecord(id="2", name="disabled", enabled=False)
        )
        result = store.list_portfolios(enabled_only=True)
        assert len(result) == 1
        assert result[0].name == "enabled"

    def test_update_status(self, store):
        store.save_portfolio(
            PortfolioRecord(id="1", name="my-portfolio", enabled=True)
        )
        updated = store.update_portfolio_status("my-portfolio", enabled=False)
        assert updated is True
        record = store.get_portfolio("my-portfolio")
        assert record is not None
        assert record.enabled is False
        assert record.updated_at is not None

        not_found = store.update_portfolio_status("no-such", enabled=True)
        assert not_found is False


class TestProductRunCRUD:
    def test_save_and_list(self, store):
        run = ProductRunRecord(
            id=str(uuid.uuid4()),
            portfolio_id="p1",
            product_type="web_app",
            workflow_id="wf1",
            status="completed",
            cost_usd=1.5,
            success=True,
        )
        store.save_product_run(run)
        runs = store.list_product_runs(product_type="web_app")
        assert len(runs) == 1
        assert runs[0].cost_usd == 1.5

    def test_filter_by_type(self, store):
        for pt in ["web_app", "web_app", "api"]:
            store.save_product_run(
                ProductRunRecord(
                    id=str(uuid.uuid4()),
                    portfolio_id="p1",
                    product_type=pt,
                    workflow_id="wf1",
                )
            )
        assert len(store.list_product_runs(product_type="web_app")) == 2
        assert len(store.list_product_runs(product_type="api")) == 1

    def test_count_runs(self, store):
        for _ in range(5):
            store.save_product_run(
                ProductRunRecord(
                    id=str(uuid.uuid4()),
                    portfolio_id="p1",
                    product_type="api",
                    workflow_id="wf1",
                )
            )
        assert store.count_product_runs("api") == 5
        assert store.count_product_runs("web_app") == 0

    def test_count_active(self, store):
        for i, status in enumerate(["running", "running", "completed"]):
            store.save_product_run(
                ProductRunRecord(
                    id=str(uuid.uuid4()),
                    portfolio_id="p1",
                    product_type="api",
                    workflow_id=f"wf{i}",
                    status=status,
                )
            )
        assert store.count_active_runs("api") == 2

    def test_get_total_cost(self, store):
        for cost in [1.0, 2.5, 0.5]:
            store.save_product_run(
                ProductRunRecord(
                    id=str(uuid.uuid4()),
                    portfolio_id="p1",
                    product_type="web_app",
                    workflow_id="wf1",
                    cost_usd=cost,
                )
            )
        assert store.get_total_cost("web_app") == pytest.approx(4.0)
        assert store.get_total_cost("api") == pytest.approx(0.0)


class TestSharedComponents:
    def test_save_and_list(self, store):
        record = SharedComponentRecord(
            id=str(uuid.uuid4()),
            source_stage="web_app/build",
            target_stage="api/build",
            similarity=0.85,
            shared_keys=["name", "timeout"],
            differing_keys=["retries"],
        )
        store.save_shared_component(record)
        result = store.list_shared_components()
        assert len(result) == 1
        assert result[0].similarity == 0.85

    def test_filter_by_similarity(self, store):
        for sim in [0.3, 0.6, 0.9]:
            store.save_shared_component(
                SharedComponentRecord(
                    id=str(uuid.uuid4()),
                    source_stage="a",
                    target_stage="b",
                    similarity=sim,
                )
            )
        result = store.list_shared_components(min_similarity=0.5)
        assert len(result) == 2
        assert all(r.similarity >= 0.5 for r in result)


class TestKnowledgeGraph:
    def test_save_concept(self, store):
        concept = KGConceptRecord(
            id="c1", name="web_app", concept_type="product"
        )
        store.save_concept(concept)
        result = store.get_concept("web_app")
        assert result is not None
        assert result.concept_type == "product"

    def test_save_edge(self, store):
        store.save_concept(
            KGConceptRecord(id="c1", name="product_a", concept_type="product")
        )
        store.save_concept(
            KGConceptRecord(id="c2", name="stage_a", concept_type="stage")
        )
        edge = KGEdgeRecord(
            id="e1", source_id="c1", target_id="c2", relation="uses"
        )
        store.save_edge(edge)
        edges = store.query_edges(source_id="c1")
        assert len(edges) == 1
        assert edges[0].relation == "uses"

    def test_query_edges_filtered(self, store):
        store.save_edge(
            KGEdgeRecord(id="e1", source_id="s1", target_id="t1", relation="uses")
        )
        store.save_edge(
            KGEdgeRecord(id="e2", source_id="s1", target_id="t2", relation="has_agent")
        )
        uses_edges = store.query_edges(source_id="s1", relation="uses")
        assert len(uses_edges) == 1
        assert uses_edges[0].target_id == "t1"
