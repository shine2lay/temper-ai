"""Tests for portfolio CLI commands."""

import pytest
from unittest.mock import patch, MagicMock

from click.testing import CliRunner
from src.interfaces.cli.portfolio_commands import portfolio_group


@pytest.fixture
def runner():
    return CliRunner()


class TestPortfolioList:
    @patch("src.interfaces.cli.portfolio_commands._get_store")
    @patch("src.interfaces.cli.portfolio_commands._get_loader")
    def test_portfolio_list(self, mock_get_loader, mock_get_store, runner):
        mock_loader = MagicMock()
        mock_loader.list_available.return_value = ["example_portfolio", "prod"]
        mock_get_loader.return_value = mock_loader

        mock_store = MagicMock()
        mock_store.list_portfolios.return_value = []
        mock_get_store.return_value = mock_store

        # Mock loader.load to raise FileNotFoundError for each name,
        # so the list command doesn't try to render product counts
        mock_loader.load.side_effect = FileNotFoundError
        result = runner.invoke(portfolio_group, ["list"])
        assert result.exit_code == 0
        assert "example_portfolio" in result.output


class TestPortfolioShow:
    @patch("src.portfolio.scheduler.ResourceScheduler")
    @patch("src.interfaces.cli.portfolio_commands._get_store")
    @patch("src.interfaces.cli.portfolio_commands._get_loader")
    def test_portfolio_show(self, mock_get_loader, mock_get_store, mock_sched_cls, runner):
        mock_config = MagicMock()
        mock_config.name = "example_portfolio"
        mock_config.description = "Test portfolio"
        mock_config.strategy.value = "weighted"
        mock_config.total_budget_usd = 100.0
        mock_config.max_total_concurrent = 6
        mock_config.products = []
        mock_loader = MagicMock()
        mock_loader.load.return_value = mock_config
        mock_get_loader.return_value = mock_loader

        mock_scheduler = MagicMock()
        mock_scheduler.get_allocation_status.return_value = {}
        mock_sched_cls.return_value = mock_scheduler

        result = runner.invoke(portfolio_group, ["show", "example_portfolio"])
        assert result.exit_code == 0
        assert "example_portfolio" in result.output


class TestPortfolioScorecards:
    @patch("src.portfolio.optimizer.PortfolioOptimizer")
    @patch("src.interfaces.cli.portfolio_commands._get_store")
    @patch("src.interfaces.cli.portfolio_commands._get_loader")
    def test_portfolio_scorecards(self, mock_get_loader, mock_get_store, mock_opt_cls, runner):
        mock_config = MagicMock()
        mock_config.products = []
        mock_loader = MagicMock()
        mock_loader.load.return_value = mock_config
        mock_get_loader.return_value = mock_loader

        mock_optimizer = MagicMock()
        mock_optimizer.compute_scorecards.return_value = []
        mock_opt_cls.return_value = mock_optimizer

        result = runner.invoke(portfolio_group, ["scorecards", "example_portfolio"])
        assert result.exit_code == 0


class TestPortfolioRecommend:
    @patch("src.portfolio.optimizer.PortfolioOptimizer")
    @patch("src.interfaces.cli.portfolio_commands._get_store")
    @patch("src.interfaces.cli.portfolio_commands._get_loader")
    def test_portfolio_recommend(self, mock_get_loader, mock_get_store, mock_opt_cls, runner):
        mock_config = MagicMock()
        mock_config.products = []
        mock_loader = MagicMock()
        mock_loader.load.return_value = mock_config
        mock_get_loader.return_value = mock_loader

        mock_optimizer = MagicMock()
        mock_optimizer.compute_scorecards.return_value = []
        mock_optimizer.recommend.return_value = []
        mock_opt_cls.return_value = mock_optimizer

        result = runner.invoke(portfolio_group, ["recommend", "example_portfolio"])
        assert result.exit_code == 0


class TestPortfolioComponents:
    @patch("src.portfolio.component_analyzer.ComponentAnalyzer")
    @patch("src.interfaces.cli.portfolio_commands._get_store")
    @patch("src.interfaces.cli.portfolio_commands._get_loader")
    def test_portfolio_components(self, mock_get_loader, mock_get_store, mock_analyzer_cls, runner):
        mock_config = MagicMock()
        mock_loader = MagicMock()
        mock_loader.load.return_value = mock_config
        mock_get_loader.return_value = mock_loader

        mock_analyzer = MagicMock()
        mock_analyzer.analyze_portfolio.return_value = []
        mock_analyzer_cls.return_value = mock_analyzer

        result = runner.invoke(portfolio_group, ["components", "example_portfolio"])
        assert result.exit_code == 0


class TestPortfolioGraph:
    @patch("src.portfolio.knowledge_graph.KnowledgeQuery")
    @patch("src.interfaces.cli.portfolio_commands._get_store")
    def test_portfolio_graph_stats(self, mock_get_store, mock_query_cls, runner):
        mock_query = MagicMock()
        mock_query.concept_stats.return_value = {
            "concepts_by_type": {"product": 2},
            "edges_by_relation": {"uses": 3},
        }
        mock_query_cls.return_value = mock_query

        result = runner.invoke(portfolio_group, ["graph", "stats"])
        assert result.exit_code == 0

    @patch("src.portfolio.knowledge_graph.KnowledgeQuery")
    @patch("src.interfaces.cli.portfolio_commands._get_store")
    def test_portfolio_graph_query(self, mock_get_store, mock_query_cls, runner):
        mock_query = MagicMock()
        mock_query.get_related_concepts.return_value = [
            {"name": "build", "concept_type": "stage", "relation": "uses", "depth": 1},
        ]
        mock_query_cls.return_value = mock_query

        result = runner.invoke(portfolio_group, ["graph", "query", "web_app"])
        assert result.exit_code == 0
        assert "build" in result.output


class TestPortfolioRun:
    @patch("src.portfolio.scheduler.ResourceScheduler")
    @patch("src.interfaces.cli.portfolio_commands._get_store")
    @patch("src.interfaces.cli.portfolio_commands._get_loader")
    def test_portfolio_run(self, mock_get_loader, mock_get_store, mock_sched_cls, runner):
        mock_config = MagicMock()
        mock_config.name = "test"
        mock_loader = MagicMock()
        mock_loader.load.return_value = mock_config
        mock_get_loader.return_value = mock_loader

        mock_scheduler = MagicMock()
        mock_scheduler.next_product.return_value = "web_app"
        mock_sched_cls.return_value = mock_scheduler

        result = runner.invoke(portfolio_group, ["run", "test"])
        assert result.exit_code == 0
        assert "web_app" in result.output
