"""Post-execution orchestrator — coordinates learning, goals, and portfolio after each workflow run."""

import logging
import time
from typing import Any, Dict, Optional

from src.autonomy._schemas import (
    AutonomousLoopConfig,
    PostExecutionReport,
    WorkflowRunContext,
)
from src.autonomy.constants import DEFAULT_LOOKBACK_HOURS, MS_PER_SECOND

logger = logging.getLogger(__name__)


class PostExecutionOrchestrator:
    """Coordinates post-execution analysis across learning, goals, and portfolio subsystems.

    Each subsystem is wrapped in try/except so failures in one
    never crash the overall workflow or other subsystems.
    """

    def __init__(self, config: AutonomousLoopConfig) -> None:
        self._config = config

    def run(self, context: WorkflowRunContext) -> PostExecutionReport:
        """Run all enabled post-execution subsystems and return a report."""
        start = time.monotonic()
        report = PostExecutionReport()

        if not self._config.enabled:
            return report

        logger.info(
            "Autonomous loop starting for workflow %s (%s)",
            context.workflow_name,
            context.workflow_id,
        )

        if self._config.learning_enabled:
            report.learning_result = self._run_learning(context, report)

        if self._config.goals_enabled:
            report.goals_result = self._run_goals(context, report)

        if self._config.portfolio_enabled:
            report.portfolio_result = self._run_portfolio(context, report)

        elapsed_ms = (time.monotonic() - start) * MS_PER_SECOND
        report.duration_ms = round(elapsed_ms, 1)

        error_count = len(report.errors)
        logger.info(
            "Autonomous loop completed in %.1fms (%d errors)",
            report.duration_ms,
            error_count,
        )
        return report

    def _run_learning(
        self, context: WorkflowRunContext, report: PostExecutionReport
    ) -> Optional[Dict[str, Any]]:
        """Run pattern mining and recommendation generation."""
        try:
            from src.learning.orchestrator import MiningOrchestrator
            from src.learning.recommender import RecommendationEngine
            from src.learning.store import LearningStore

            store = LearningStore()
            orchestrator = MiningOrchestrator(store=store)
            mining_run = orchestrator.run_mining(
                lookback_hours=DEFAULT_LOOKBACK_HOURS
            )

            engine = RecommendationEngine(store=store)
            recs = engine.generate_recommendations()

            return {
                "mining_run_id": mining_run.id,
                "patterns_found": mining_run.patterns_found,
                "patterns_new": mining_run.patterns_new,
                "recommendations": len(recs),
                "status": mining_run.status,
            }
        except Exception as exc:  # noqa: BLE001 -- subsystem failures must not crash workflow
            msg = f"Learning subsystem error: {exc}"
            logger.warning(msg)
            report.errors.append(msg)
            return None

    def _run_goals(
        self, context: WorkflowRunContext, report: PostExecutionReport
    ) -> Optional[Dict[str, Any]]:
        """Run goal analysis and proposal generation."""
        try:
            from src.goals.analysis_orchestrator import AnalysisOrchestrator
            from src.goals.store import GoalStore

            store = GoalStore()
            orchestrator = AnalysisOrchestrator(
                store=store, learning_store=None
            )
            analysis_run = orchestrator.run_analysis(
                lookback_hours=DEFAULT_LOOKBACK_HOURS
            )

            return {
                "analysis_run_id": analysis_run.id,
                "proposals_generated": analysis_run.proposals_generated,
                "status": analysis_run.status,
            }
        except Exception as exc:  # noqa: BLE001 -- subsystem failures must not crash workflow
            msg = f"Goals subsystem error: {exc}"
            logger.warning(msg)
            report.errors.append(msg)
            return None

    def _run_portfolio(
        self, context: WorkflowRunContext, report: PostExecutionReport
    ) -> Optional[Dict[str, Any]]:
        """Record portfolio run completion and generate scorecards."""
        try:
            from src.portfolio._schemas import PortfolioConfig
            from src.portfolio.optimizer import PortfolioOptimizer
            from src.portfolio.store import PortfolioStore

            store = PortfolioStore()

            # Only run optimizer if we have a product_type to scope to
            if context.product_type:
                optimizer = PortfolioOptimizer(store=store)
                portfolios = store.list_portfolios()
                # Find portfolio containing this product_type
                target_cfg: Optional[PortfolioConfig] = None
                for p in portfolios:
                    cfg = PortfolioConfig(**p.config) if isinstance(p.config, dict) else p.config
                    if any(prod.name == context.product_type for prod in cfg.products):
                        target_cfg = cfg
                        break
                if target_cfg is None:
                    return {"product_type": context.product_type, "skipped": True}
                scorecards = optimizer.compute_scorecards(target_cfg)
                recommendations = optimizer.recommend(scorecards)
                return {
                    "product_type": context.product_type,
                    "scorecards": len(scorecards),
                    "recommendations": len(recommendations),
                }

            return {"product_type": None, "skipped": True}
        except Exception as exc:  # noqa: BLE001 -- subsystem failures must not crash workflow
            msg = f"Portfolio subsystem error: {exc}"
            logger.warning(msg)
            report.errors.append(msg)
            return None
