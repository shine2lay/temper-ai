"""Tests for portfolio dashboard FastAPI routes."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from temper_ai.portfolio._schemas import (
    AllocationStatus,
    AllocationStrategy,
    ComponentMatch,
    OptimizationAction,
    PortfolioConfig,
    PortfolioRecommendation,
    ProductDefinition,
    ProductScorecard,
)
from temper_ai.portfolio.dashboard_routes import _load_config, create_portfolio_router

# ---------------------------------------------------------------------------
# Helper factories
# ---------------------------------------------------------------------------


def _make_product(name: str = "web_app", weight: float = 1.0) -> ProductDefinition:
    return ProductDefinition(name=name, weight=weight)


def _make_config(name: str = "test-portfolio") -> PortfolioConfig:
    return PortfolioConfig(name=name, products=[_make_product()])


def _make_scorecard(product_type: str = "web_app") -> ProductScorecard:
    return ProductScorecard(
        product_type=product_type,
        success_rate=0.9,
        cost_efficiency=0.8,
        trend=0.1,
        utilization=0.5,
        composite_score=0.72,
    )


def _make_recommendation(product_type: str = "web_app") -> PortfolioRecommendation:
    return PortfolioRecommendation(
        product_type=product_type,
        action=OptimizationAction.MAINTAIN,
        scorecard=_make_scorecard(product_type),
        rationale="Adequate performance",
        suggested_weight_delta=0.0,
    )


def _make_allocation(product_type: str = "web_app") -> AllocationStatus:
    return AllocationStatus(
        product_type=product_type,
        active_runs=1,
        completed_runs=10,
        budget_used_usd=5.0,
        budget_limit_usd=100.0,
        utilization=0.05,
    )


def _make_match() -> ComponentMatch:
    return ComponentMatch(
        source_stage="web_app/build",
        target_stage="api/build",
        similarity=0.85,
        shared_keys=["name"],
        differing_keys=["retries"],
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_store():
    store = MagicMock()
    return store


@pytest.fixture()
def client(mock_store):
    router = create_portfolio_router(mock_store)
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


# ---------------------------------------------------------------------------
# _load_config unit tests
# ---------------------------------------------------------------------------


class TestLoadConfig:
    def test_returns_config_on_success(self):
        cfg = _make_config("my-portfolio")
        with patch("temper_ai.portfolio.loader.PortfolioLoader") as MockLoader:
            MockLoader.return_value.load.return_value = cfg
            result = _load_config("my-portfolio")
        assert result.name == "my-portfolio"

    def test_raises_http_404_on_file_not_found(self):
        from fastapi import HTTPException

        with patch("temper_ai.portfolio.loader.PortfolioLoader") as MockLoader:
            MockLoader.return_value.load.side_effect = FileNotFoundError("not found")
            with pytest.raises(HTTPException) as exc_info:
                _load_config("missing")
        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Router creation tests
# ---------------------------------------------------------------------------


class TestCreatePortfolioRouter:
    def test_router_has_correct_prefix(self, mock_store):
        router = create_portfolio_router(mock_store)
        assert router.prefix == "/portfolio"

    def test_router_has_portfolio_tag(self, mock_store):
        router = create_portfolio_router(mock_store)
        assert "portfolio" in router.tags


# ---------------------------------------------------------------------------
# GET /portfolio/list
# ---------------------------------------------------------------------------


class TestListPortfolios:
    def test_returns_empty_list_when_no_portfolios(self, client, mock_store):
        mock_store.list_portfolios.return_value = []
        resp = client.get("/portfolio/list")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_returns_portfolio_records(self, client, mock_store):
        from datetime import datetime

        from temper_ai.portfolio.models import PortfolioRecord

        record = PortfolioRecord(
            id="p1",
            name="my-portfolio",
            description="A test portfolio",
            enabled=True,
            created_at=datetime(2024, 1, 1, 12, 0, 0),
        )
        mock_store.list_portfolios.return_value = [record]
        resp = client.get("/portfolio/list")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["name"] == "my-portfolio"
        assert data[0]["description"] == "A test portfolio"
        assert data[0]["enabled"] is True

    def test_created_at_isoformat_in_response(self, client, mock_store):
        from datetime import datetime

        from temper_ai.portfolio.models import PortfolioRecord

        record = PortfolioRecord(
            id="p1",
            name="portfolio",
            created_at=datetime(2024, 6, 15, 10, 30, 0),
        )
        mock_store.list_portfolios.return_value = [record]
        resp = client.get("/portfolio/list")
        assert "2024-06-15" in resp.json()[0]["created_at"]

    def test_none_created_at_returns_null(self, client, mock_store):
        from temper_ai.portfolio.models import PortfolioRecord

        record = PortfolioRecord(id="p1", name="portfolio")
        record.created_at = None  # type: ignore[assignment]
        mock_store.list_portfolios.return_value = [record]
        resp = client.get("/portfolio/list")
        assert resp.json()[0]["created_at"] is None


# ---------------------------------------------------------------------------
# GET /portfolio/{name}/status
# ---------------------------------------------------------------------------


class TestGetStatus:
    def test_returns_404_when_portfolio_missing(self, client, mock_store):
        mock_store.get_portfolio.return_value = None
        resp = client.get("/portfolio/missing/status")
        assert resp.status_code == 404

    def test_returns_status_payload(self, client, mock_store):
        cfg = _make_config("test-portfolio")
        alloc = _make_allocation()
        mock_store.get_portfolio.return_value = MagicMock()

        with (
            patch("temper_ai.portfolio.loader.PortfolioLoader") as MockLoader,
            patch("temper_ai.portfolio.scheduler.ResourceScheduler") as MockScheduler,
        ):
            MockLoader.return_value.load.return_value = cfg
            MockScheduler.return_value.get_allocation_status.return_value = {
                "web_app": alloc
            }
            resp = client.get("/portfolio/test-portfolio/status")

        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "test-portfolio"
        assert data["strategy"] == AllocationStrategy.WEIGHTED.value
        assert data["products"] == 1
        assert len(data["allocations"]) == 1


# ---------------------------------------------------------------------------
# GET /portfolio/knowledge/stats
# ---------------------------------------------------------------------------


class TestKnowledgeStats:
    def test_returns_stats_dict(self, client, mock_store):
        expected = {"concepts": 5, "edges": 10}
        with patch("temper_ai.portfolio.knowledge_graph.KnowledgeQuery") as MockQuery:
            MockQuery.return_value.concept_stats.return_value = expected
            resp = client.get("/portfolio/knowledge/stats")

        assert resp.status_code == 200
        assert resp.json() == expected


# ---------------------------------------------------------------------------
# GET /portfolio/{name}/scorecards
# ---------------------------------------------------------------------------


class TestGetScorecards:
    def test_returns_scorecards(self, client, mock_store):
        cfg = _make_config("test-portfolio")
        sc = _make_scorecard()

        with (
            patch("temper_ai.portfolio.loader.PortfolioLoader") as MockLoader,
            patch("temper_ai.portfolio.optimizer.PortfolioOptimizer") as MockOptimizer,
        ):
            MockLoader.return_value.load.return_value = cfg
            MockOptimizer.return_value.compute_scorecards.return_value = [sc]
            resp = client.get("/portfolio/test-portfolio/scorecards")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["product_type"] == "web_app"
        assert data[0]["success_rate"] == 0.9

    def test_returns_404_when_config_missing(self, client, mock_store):
        with patch("temper_ai.portfolio.loader.PortfolioLoader") as MockLoader:
            MockLoader.return_value.load.side_effect = FileNotFoundError
            resp = client.get("/portfolio/missing/scorecards")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /portfolio/{name}/recommendations
# ---------------------------------------------------------------------------


class TestGetRecommendations:
    def test_returns_recommendations(self, client, mock_store):
        cfg = _make_config("test-portfolio")
        sc = _make_scorecard()
        rec = _make_recommendation()

        with (
            patch("temper_ai.portfolio.loader.PortfolioLoader") as MockLoader,
            patch("temper_ai.portfolio.optimizer.PortfolioOptimizer") as MockOptimizer,
        ):
            MockLoader.return_value.load.return_value = cfg
            MockOptimizer.return_value.compute_scorecards.return_value = [sc]
            MockOptimizer.return_value.recommend.return_value = [rec]
            resp = client.get("/portfolio/test-portfolio/recommendations")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["product_type"] == "web_app"
        assert data[0]["action"] == OptimizationAction.MAINTAIN.value
        assert data[0]["rationale"] == "Adequate performance"

    def test_returns_404_when_config_missing(self, client, mock_store):
        with patch("temper_ai.portfolio.loader.PortfolioLoader") as MockLoader:
            MockLoader.return_value.load.side_effect = FileNotFoundError
            resp = client.get("/portfolio/missing/recommendations")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /portfolio/{name}/components
# ---------------------------------------------------------------------------


class TestGetComponents:
    def test_returns_component_matches(self, client, mock_store):
        cfg = _make_config("test-portfolio")
        match = _make_match()

        with (
            patch("temper_ai.portfolio.loader.PortfolioLoader") as MockLoader,
            patch(
                "temper_ai.portfolio.component_analyzer.ComponentAnalyzer"
            ) as MockAnalyzer,
        ):
            MockLoader.return_value.load.return_value = cfg
            MockAnalyzer.return_value.analyze_portfolio.return_value = [match]
            resp = client.get("/portfolio/test-portfolio/components")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["source_stage"] == "web_app/build"
        assert data[0]["similarity"] == 0.85

    def test_returns_empty_list_when_no_components(self, client, mock_store):
        cfg = _make_config("test-portfolio")

        with (
            patch("temper_ai.portfolio.loader.PortfolioLoader") as MockLoader,
            patch(
                "temper_ai.portfolio.component_analyzer.ComponentAnalyzer"
            ) as MockAnalyzer,
        ):
            MockLoader.return_value.load.return_value = cfg
            MockAnalyzer.return_value.analyze_portfolio.return_value = []
            resp = client.get("/portfolio/test-portfolio/components")

        assert resp.status_code == 200
        assert resp.json() == []

    def test_returns_404_when_config_missing(self, client, mock_store):
        with patch("temper_ai.portfolio.loader.PortfolioLoader") as MockLoader:
            MockLoader.return_value.load.side_effect = FileNotFoundError
            resp = client.get("/portfolio/missing/components")
        assert resp.status_code == 404
