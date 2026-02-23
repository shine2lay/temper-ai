"""Tests for portfolio schemas."""

from temper_ai.portfolio._schemas import (
    AllocationStrategy,
    ComponentMatch,
    OptimizationAction,
    PortfolioConfig,
    PortfolioRecommendation,
    ProductDefinition,
    ProductScorecard,
)


class TestAllocationStrategy:
    def test_allocation_strategy_values(self):
        assert AllocationStrategy.EQUAL == "equal"
        assert AllocationStrategy.WEIGHTED == "weighted"
        assert AllocationStrategy.PRIORITY == "priority"
        assert AllocationStrategy.DYNAMIC == "dynamic"
        assert len(AllocationStrategy) == 4


class TestProductDefinition:
    def test_product_definition_defaults(self):
        pd = ProductDefinition(name="test")
        assert pd.name == "test"
        assert pd.weight == 1.0
        assert pd.max_concurrent == 2
        assert pd.budget_limit_usd == 0.0
        assert pd.workflow_configs == []
        assert pd.tags == []


class TestPortfolioConfig:
    def test_portfolio_config_with_products(self):
        products = [
            ProductDefinition(name="web_app", weight=2.0),
            ProductDefinition(name="api", weight=1.0),
        ]
        cfg = PortfolioConfig(name="test-portfolio", products=products)
        assert cfg.name == "test-portfolio"
        assert len(cfg.products) == 2
        assert cfg.products[0].name == "web_app"
        assert cfg.products[1].weight == 1.0

    def test_portfolio_config_default_strategy(self):
        cfg = PortfolioConfig(name="test")
        assert cfg.strategy == AllocationStrategy.WEIGHTED
        assert cfg.total_budget_usd == 0.0
        assert cfg.max_total_concurrent == 8


class TestComponentMatch:
    def test_component_match_creation(self):
        match = ComponentMatch(
            source_stage="web_app/build",
            target_stage="api/build",
            similarity=0.85,
            shared_keys=["name", "timeout"],
            differing_keys=["retries"],
        )
        assert match.source_stage == "web_app/build"
        assert match.target_stage == "api/build"
        assert match.similarity == 0.85
        assert match.shared_keys == ["name", "timeout"]
        assert match.differing_keys == ["retries"]


class TestProductScorecard:
    def test_product_scorecard_creation(self):
        sc = ProductScorecard(
            product_type="web_app",
            success_rate=0.9,
            cost_efficiency=0.7,
            trend=0.1,
            utilization=0.5,
            composite_score=0.65,
        )
        assert sc.product_type == "web_app"
        assert sc.success_rate == 0.9
        assert sc.cost_efficiency == 0.7
        assert sc.trend == 0.1
        assert sc.utilization == 0.5
        assert sc.composite_score == 0.65


class TestOptimizationAction:
    def test_optimization_action_values(self):
        assert OptimizationAction.INVEST == "invest"
        assert OptimizationAction.MAINTAIN == "maintain"
        assert OptimizationAction.REDUCE == "reduce"
        assert OptimizationAction.SUNSET == "sunset"
        assert len(OptimizationAction) == 4


class TestPortfolioRecommendation:
    def test_portfolio_recommendation(self):
        sc = ProductScorecard(
            product_type="api",
            success_rate=0.8,
            cost_efficiency=0.6,
            trend=0.2,
            utilization=0.4,
            composite_score=0.55,
        )
        rec = PortfolioRecommendation(
            product_type="api",
            action=OptimizationAction.MAINTAIN,
            scorecard=sc,
            rationale="Adequate performance",
        )
        assert rec.product_type == "api"
        assert rec.action == OptimizationAction.MAINTAIN
        assert rec.scorecard.success_rate == 0.8
        assert rec.rationale == "Adequate performance"
