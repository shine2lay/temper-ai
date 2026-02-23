"""FastAPI routes for portfolio management dashboard."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, HTTPException

from temper_ai.portfolio.constants import ERR_PORTFOLIO_NOT_FOUND
from temper_ai.portfolio.store import PortfolioStore

if TYPE_CHECKING:
    from temper_ai.portfolio._schemas import PortfolioConfig

HTTP_404 = 404


def _load_config(name: str) -> PortfolioConfig:
    """Load a portfolio config by name, raising HTTP 404 on failure."""
    from temper_ai.portfolio.loader import PortfolioLoader

    try:
        loader = PortfolioLoader()
        return loader.load(name)
    except FileNotFoundError:
        raise HTTPException(status_code=HTTP_404, detail=ERR_PORTFOLIO_NOT_FOUND)


def create_portfolio_router(store: PortfolioStore) -> APIRouter:
    """Create portfolio management API router."""
    router = APIRouter(prefix="/portfolio", tags=["portfolio"])
    _register_data_routes(router, store)
    _register_analysis_routes(router, store)
    return router


def _register_data_routes(router: APIRouter, store: PortfolioStore) -> None:
    """Register list/status endpoints."""

    @router.get("/list")
    def list_portfolios() -> list[dict[str, Any]]:
        """List all portfolios in the store."""
        records = store.list_portfolios()
        return [
            {
                "name": r.name,
                "description": r.description,
                "enabled": r.enabled,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in records
        ]

    @router.get("/{name}/status")
    def get_status(name: str) -> dict[str, Any]:
        """Get portfolio status with allocation details."""
        from temper_ai.portfolio.scheduler import ResourceScheduler

        record = store.get_portfolio(name)
        if record is None:
            raise HTTPException(status_code=HTTP_404, detail="Portfolio not found")

        cfg = _load_config(name)
        scheduler = ResourceScheduler(store=store)
        alloc_map = scheduler.get_allocation_status(cfg)

        return {
            "name": cfg.name,
            "description": cfg.description,
            "strategy": cfg.strategy.value,
            "products": len(cfg.products),
            "allocations": [a.model_dump() for a in alloc_map.values()],
        }

    @router.get("/knowledge/stats")
    def knowledge_stats() -> dict[str, Any]:
        """Get knowledge graph statistics."""
        from temper_ai.portfolio.knowledge_graph import KnowledgeQuery

        query = KnowledgeQuery(store=store)
        return query.concept_stats()


def _register_analysis_routes(router: APIRouter, store: PortfolioStore) -> None:
    """Register scorecards/recommendations/components endpoints."""

    @router.get("/{name}/scorecards")
    def get_scorecards(name: str) -> list[dict[str, Any]]:
        """Get product scorecards for a portfolio."""
        from temper_ai.portfolio.optimizer import PortfolioOptimizer

        cfg = _load_config(name)
        optimizer = PortfolioOptimizer(store=store)
        cards = optimizer.compute_scorecards(cfg)
        return [c.model_dump() for c in cards]

    @router.get("/{name}/recommendations")
    def get_recommendations(name: str) -> list[dict[str, Any]]:
        """Get invest/sunset recommendations."""
        from temper_ai.portfolio.optimizer import PortfolioOptimizer

        cfg = _load_config(name)
        optimizer = PortfolioOptimizer(store=store)
        cards = optimizer.compute_scorecards(cfg)
        recs = optimizer.recommend(cards)
        return [
            {
                "product_type": r.product_type,
                "action": r.action.value,
                "composite_score": r.scorecard.composite_score,
                "rationale": r.rationale,
                "suggested_weight_delta": r.suggested_weight_delta,
            }
            for r in recs
        ]

    @router.get("/{name}/components")
    def get_components(name: str) -> list[dict[str, Any]]:
        """Get shared component analysis."""
        from temper_ai.portfolio.component_analyzer import ComponentAnalyzer

        cfg = _load_config(name)
        analyzer = ComponentAnalyzer(store=store)
        matches = analyzer.analyze_portfolio(cfg)
        return [m.model_dump() for m in matches]
