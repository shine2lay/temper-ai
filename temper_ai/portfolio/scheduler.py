"""Weighted Fair Queue resource scheduler for portfolio products."""

import logging
import uuid
from typing import Dict, Optional

from temper_ai.portfolio._schemas import AllocationStatus, PortfolioConfig, ProductDefinition
from temper_ai.portfolio._tracking import track_portfolio_event
from temper_ai.portfolio.models import ProductRunRecord
from temper_ai.portfolio.store import PortfolioStore
from temper_ai.storage.database.datetime_utils import safe_duration_seconds, utcnow

logger = logging.getLogger(__name__)


class ResourceScheduler:
    """Weighted Fair Queue scheduler with budget/concurrency gates."""

    def __init__(self, store: PortfolioStore) -> None:
        self.store = store

    def next_product(
        self, portfolio: PortfolioConfig,
    ) -> Optional[str]:
        """Select next product to execute using WFQ scheduling.

        Filters products under concurrency and budget caps, then picks the
        product with the lowest virtual_time (completed_runs / weight).
        """
        best_product: Optional[str] = None
        best_vtime = float("inf")

        for product in portfolio.products:
            if not self.can_execute(portfolio, product.name):
                continue

            completed = self.store.count_product_runs(product.name)
            weight = product.weight if product.weight > 0 else 1.0
            virtual_time = completed / weight

            if virtual_time < best_vtime:
                best_vtime = virtual_time
                best_product = product.name

        if best_product is not None:
            logger.info(
                "WFQ selected product=%s (vtime=%.3f)",
                best_product,
                best_vtime,
            )
        track_portfolio_event(
            "scheduler_wfq_selection",
            {"portfolio": portfolio.name},
            f"selected:{best_product}" if best_product else "none_eligible",
            impact_metrics={"virtual_time": best_vtime if best_product else None},
            tags=["portfolio", "scheduler"],
        )
        return best_product

    def can_execute(
        self, portfolio: PortfolioConfig, product_type: str,
    ) -> bool:
        """Check concurrency and budget gates for a product."""
        product = _find_product(portfolio, product_type)
        if product is None:
            return False

        active = self.store.count_product_runs(product_type, status="running")
        if active >= product.max_concurrent:
            return False

        if product.budget_limit_usd > 0:
            cost = self.store.get_total_cost(product_type)
            if cost >= product.budget_limit_usd:
                return False

        total_active = sum(
            self.store.count_product_runs(p.name, status="running")
            for p in portfolio.products
        )
        if total_active >= portfolio.max_total_concurrent:
            return False

        return True

    def record_start(
        self,
        product_type: str,
        workflow_id: str,
        portfolio_id: str = "",
    ) -> None:
        """Record the start of a product workflow execution."""
        record = ProductRunRecord(
            id=str(uuid.uuid4()),
            portfolio_id=portfolio_id,
            product_type=product_type,
            workflow_id=workflow_id,
            status="running",
            started_at=utcnow(),
        )
        self.store.save_product_run(record)
        logger.info(
            "Recorded start: product=%s workflow=%s",
            product_type,
            workflow_id,
        )
        track_portfolio_event(
            "scheduler_product_start",
            {"product_type": product_type, "workflow_id": workflow_id,
             "portfolio_id": portfolio_id},
            "started",
            tags=["portfolio", "scheduler"],
        )

    def record_complete(
        self,
        product_type: str,
        workflow_id: str,
        cost_usd: float,
        success: bool,
    ) -> None:
        """Record the completion of a product workflow execution."""
        runs = self.store.list_product_runs(
            product_type=product_type, status="running",
        )
        record = None
        for run in runs:
            if run.workflow_id == workflow_id:
                record = run
                break

        if record is None:
            logger.warning(
                "No running record found: product=%s workflow=%s",
                product_type,
                workflow_id,
            )
            return

        now = utcnow()
        record.status = "completed"
        record.cost_usd = cost_usd
        record.success = success
        record.completed_at = now
        if record.started_at is not None:
            record.duration_s = safe_duration_seconds(
                record.started_at, now, context="product_run",
            )

        self.store.save_product_run(record)
        logger.info(
            "Recorded complete: product=%s workflow=%s success=%s cost=%.4f",
            product_type,
            workflow_id,
            success,
            cost_usd,
        )
        track_portfolio_event(
            "scheduler_product_complete",
            {"product_type": product_type, "workflow_id": workflow_id},
            "success" if success else "failure",
            impact_metrics={
                "cost_usd": cost_usd,
                "duration_s": record.duration_s,
                "success": success,
            },
            tags=["portfolio", "scheduler"],
        )

    def get_allocation_status(
        self, portfolio: PortfolioConfig,
    ) -> Dict[str, AllocationStatus]:
        """Get current allocation status for every product."""
        result: Dict[str, AllocationStatus] = {}

        for product in portfolio.products:
            active = self.store.count_product_runs(product.name, status="running")
            completed = self.store.count_product_runs(product.name)
            budget_used = self.store.get_total_cost(product.name)
            max_c = product.max_concurrent
            utilization = active / max_c if max_c > 0 else 0.0

            result[product.name] = AllocationStatus(
                product_type=product.name,
                active_runs=active,
                completed_runs=completed,
                budget_used_usd=budget_used,
                budget_limit_usd=product.budget_limit_usd,
                utilization=utilization,
            )

        track_portfolio_event(
            "scheduler_allocation_status",
            {"portfolio": portfolio.name, "product_count": len(portfolio.products)},
            "computed",
            impact_metrics={
                name: {"active": s.active_runs, "utilization": s.utilization}
                for name, s in result.items()
            },
            tags=["portfolio", "scheduler"],
        )
        return result


def _find_product(portfolio: PortfolioConfig, name: str) -> Optional[ProductDefinition]:
    """Find a ProductDefinition by name within a portfolio."""
    for product in portfolio.products:
        if product.name == name:
            return product
    return None
