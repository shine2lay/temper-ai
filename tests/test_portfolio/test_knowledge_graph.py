"""Tests for KnowledgePopulator and KnowledgeQuery."""

import os
import tempfile
import uuid

import pytest
import yaml

from src.portfolio._schemas import KGConceptType, KGRelation, PortfolioConfig, ProductDefinition
from src.portfolio.knowledge_graph import KnowledgePopulator, KnowledgeQuery
from src.portfolio.models import ProductRunRecord
from src.portfolio.store import PortfolioStore

MEMORY_DB = "sqlite:///:memory:"


@pytest.fixture
def store():
    return PortfolioStore(database_url=MEMORY_DB)


@pytest.fixture
def populator(store):
    return KnowledgePopulator(store)


@pytest.fixture
def query(store):
    return KnowledgeQuery(store)


def _make_workflow_yaml(tmpdir, name, stages):
    """Create a temporary workflow YAML with given stage definitions."""
    path = os.path.join(tmpdir, f"{name}.yaml")
    data = {
        "workflow": {
            "stages": stages,
        }
    }
    with open(path, "w") as f:
        yaml.dump(data, f)
    return path


class TestPopulateFromConfig:
    def test_creates_concepts(self, populator, store):
        with tempfile.TemporaryDirectory() as tmpdir:
            wf_path = _make_workflow_yaml(tmpdir, "wf1", [
                {"name": "build", "agents": ["builder_agent"]},
            ])
            portfolio = PortfolioConfig(
                name="test",
                products=[
                    ProductDefinition(name="web_app", workflow_configs=[wf_path]),
                ],
            )
            added = populator.populate_from_config(portfolio)
            assert added >= 1
            product = store.get_concept("web_app")
            assert product is not None
            assert product.concept_type == KGConceptType.PRODUCT.value

    def test_creates_edges(self, populator, store):
        with tempfile.TemporaryDirectory() as tmpdir:
            wf_path = _make_workflow_yaml(tmpdir, "wf1", [
                {"name": "build", "agents": ["builder_agent"]},
            ])
            portfolio = PortfolioConfig(
                name="test",
                products=[
                    ProductDefinition(name="web_app", workflow_configs=[wf_path]),
                ],
            )
            populator.populate_from_config(portfolio)
            product = store.get_concept("web_app")
            edges = store.query_edges(source_id=product.id, relation=KGRelation.USES.value)
            assert len(edges) >= 1

    def test_idempotent(self, populator, store):
        with tempfile.TemporaryDirectory() as tmpdir:
            wf_path = _make_workflow_yaml(tmpdir, "wf1", [
                {"name": "build", "agents": ["builder_agent"]},
            ])
            portfolio = PortfolioConfig(
                name="test",
                products=[
                    ProductDefinition(name="web_app", workflow_configs=[wf_path]),
                ],
            )
            first = populator.populate_from_config(portfolio)
            second = populator.populate_from_config(portfolio)
            assert first > 0
            assert second == 0


class TestPopulateFromRuns:
    def test_creates_outcome_concepts(self, populator, store):
        with tempfile.TemporaryDirectory() as tmpdir:
            wf_path = _make_workflow_yaml(tmpdir, "wf1", [
                {"name": "build", "agents": ["a1"]},
            ])
            portfolio = PortfolioConfig(
                name="test",
                products=[
                    ProductDefinition(name="web_app", workflow_configs=[wf_path]),
                ],
            )
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
            concepts = store.list_concepts(concept_type=KGConceptType.OUTCOME.value)
            assert len(concepts) >= 1

    def test_populate_missing_product_concept(self, populator, store):
        """If product concept doesn't exist, populate_from_runs returns 0."""
        store.save_product_run(ProductRunRecord(
            id=str(uuid.uuid4()),
            portfolio_id="p1",
            product_type="nonexistent",
            workflow_id="wf-1",
        ))
        added = populator.populate_from_runs("nonexistent")
        assert added == 0


class TestTechCompatibility:
    def test_add_tech_compatibility(self, populator, store):
        populator.add_tech_compatibility("python", "fastapi", score=0.95, notes="Native")
        records = store.get_compatibility("python")
        assert len(records) == 1
        assert records[0].compatibility_score == pytest.approx(0.95)


class TestGetRelatedConcepts:
    def test_returns_related(self, populator, query, store):
        with tempfile.TemporaryDirectory() as tmpdir:
            wf_path = _make_workflow_yaml(tmpdir, "wf1", [
                {"name": "build", "agents": ["builder_agent"]},
            ])
            portfolio = PortfolioConfig(
                name="test",
                products=[
                    ProductDefinition(name="web_app", workflow_configs=[wf_path]),
                ],
            )
            populator.populate_from_config(portfolio)
            related = query.get_related_concepts("web_app")
            assert len(related) >= 1
            assert any(r["name"] == "build" for r in related)

    def test_filtered_by_relation(self, populator, query, store):
        with tempfile.TemporaryDirectory() as tmpdir:
            wf_path = _make_workflow_yaml(tmpdir, "wf1", [
                {"name": "build", "agents": ["builder_agent"]},
            ])
            portfolio = PortfolioConfig(
                name="test",
                products=[
                    ProductDefinition(name="web_app", workflow_configs=[wf_path]),
                ],
            )
            populator.populate_from_config(portfolio)
            related = query.get_related_concepts("web_app", relation=KGRelation.USES.value)
            assert all(r["relation"] == KGRelation.USES.value for r in related)

    def test_depth_traversal(self, populator, query, store):
        """Depth=2 should traverse product→stage→agent."""
        with tempfile.TemporaryDirectory() as tmpdir:
            wf_path = _make_workflow_yaml(tmpdir, "wf1", [
                {"name": "build", "agents": ["builder_agent"]},
            ])
            portfolio = PortfolioConfig(
                name="test",
                products=[
                    ProductDefinition(name="web_app", workflow_configs=[wf_path]),
                ],
            )
            populator.populate_from_config(portfolio)
            related = query.get_related_concepts("web_app", depth=2)
            names = {r["name"] for r in related}
            assert "build" in names
            assert "builder_agent" in names

    def test_empty_graph_query(self, query):
        related = query.get_related_concepts("nonexistent")
        assert related == []


class TestFindPath:
    def test_path_exists(self, populator, query, store):
        with tempfile.TemporaryDirectory() as tmpdir:
            wf_path = _make_workflow_yaml(tmpdir, "wf1", [
                {"name": "build", "agents": ["builder_agent"]},
            ])
            portfolio = PortfolioConfig(
                name="test",
                products=[
                    ProductDefinition(name="web_app", workflow_configs=[wf_path]),
                ],
            )
            populator.populate_from_config(portfolio)
            path = query.find_path("web_app", "builder_agent")
            assert path is not None
            assert path[0] == "web_app"
            assert path[-1] == "builder_agent"

    def test_no_path(self, populator, query, store):
        with tempfile.TemporaryDirectory() as tmpdir:
            wf1 = _make_workflow_yaml(tmpdir, "wf1", [
                {"name": "build", "agents": ["a1"]},
            ])
            wf2 = _make_workflow_yaml(tmpdir, "wf2", [
                {"name": "deploy", "agents": ["a2"]},
            ])
            p1 = PortfolioConfig(
                name="p1",
                products=[
                    ProductDefinition(name="prod_a", workflow_configs=[wf1]),
                ],
            )
            p2 = PortfolioConfig(
                name="p2",
                products=[
                    ProductDefinition(name="prod_b", workflow_configs=[wf2]),
                ],
            )
            populator.populate_from_config(p1)
            populator.populate_from_config(p2)
            # prod_a and prod_b are disconnected subgraphs
            path = query.find_path("prod_a", "prod_b")
            assert path is None

    def test_direct_connection(self, populator, query, store):
        with tempfile.TemporaryDirectory() as tmpdir:
            wf_path = _make_workflow_yaml(tmpdir, "wf1", [
                {"name": "build", "agents": []},
            ])
            portfolio = PortfolioConfig(
                name="test",
                products=[
                    ProductDefinition(name="web_app", workflow_configs=[wf_path]),
                ],
            )
            populator.populate_from_config(portfolio)
            path = query.find_path("web_app", "build")
            assert path is not None
            assert len(path) == 2

    def test_bfs_depth_limit(self, populator, query, store):
        """With max_depth=1, cannot reach agent through stage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            wf_path = _make_workflow_yaml(tmpdir, "wf1", [
                {"name": "build", "agents": ["builder_agent"]},
            ])
            portfolio = PortfolioConfig(
                name="test",
                products=[
                    ProductDefinition(name="web_app", workflow_configs=[wf_path]),
                ],
            )
            populator.populate_from_config(portfolio)
            path = query.find_path("web_app", "builder_agent", max_depth=1)
            # max_depth=1 means path can be at most length 2 (source + 1 hop)
            # web_app→build→builder_agent requires 2 hops, so None
            assert path is None

    def test_bidirectional_path(self, populator, query, store):
        """Path finding works in both directions."""
        with tempfile.TemporaryDirectory() as tmpdir:
            wf_path = _make_workflow_yaml(tmpdir, "wf1", [
                {"name": "build", "agents": ["builder_agent"]},
            ])
            portfolio = PortfolioConfig(
                name="test",
                products=[
                    ProductDefinition(name="web_app", workflow_configs=[wf_path]),
                ],
            )
            populator.populate_from_config(portfolio)
            forward = query.find_path("web_app", "build")
            reverse = query.find_path("build", "web_app")
            assert forward is not None
            assert reverse is not None


class TestConceptStats:
    def test_concept_stats(self, populator, query, store):
        with tempfile.TemporaryDirectory() as tmpdir:
            wf_path = _make_workflow_yaml(tmpdir, "wf1", [
                {"name": "build", "agents": ["a1"]},
                {"name": "test", "agents": ["a2"]},
            ])
            portfolio = PortfolioConfig(
                name="test",
                products=[
                    ProductDefinition(name="web_app", workflow_configs=[wf_path]),
                ],
            )
            populator.populate_from_config(portfolio)
            stats = query.concept_stats()
            assert "concepts_by_type" in stats
            assert stats["concepts_by_type"].get("product", 0) >= 1

    def test_concept_stats_edges(self, populator, query, store):
        with tempfile.TemporaryDirectory() as tmpdir:
            wf_path = _make_workflow_yaml(tmpdir, "wf1", [
                {"name": "build", "agents": ["a1"]},
            ])
            portfolio = PortfolioConfig(
                name="test",
                products=[
                    ProductDefinition(name="web_app", workflow_configs=[wf_path]),
                ],
            )
            populator.populate_from_config(portfolio)
            stats = query.concept_stats()
            assert "edges_by_relation" in stats
            assert stats["edges_by_relation"].get("uses", 0) >= 1


class TestPopulateMissingWorkflow:
    def test_populate_missing_workflow(self, populator, store):
        portfolio = PortfolioConfig(
            name="test",
            products=[
                ProductDefinition(
                    name="web_app",
                    workflow_configs=["/nonexistent/workflow.yaml"],
                ),
            ],
        )
        added = populator.populate_from_config(portfolio)
        # Product concept is created, but no stages/agents from missing file
        assert added >= 1
        product = store.get_concept("web_app")
        assert product is not None


class TestGetTechCompatibility:
    def test_get_tech_compatibility(self, populator, query, store):
        populator.add_tech_compatibility("python", "django", score=0.9)
        populator.add_tech_compatibility("python", "flask", score=0.85)
        records = query.get_tech_compatibility("python")
        assert len(records) == 2
