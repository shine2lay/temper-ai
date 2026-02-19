"""Post-execution orchestrator — coordinates learning, goals, and portfolio after each workflow run."""

import logging
import time
from typing import Any, Dict, List, Optional

from temper_ai.autonomy._schemas import (
    AutonomousLoopConfig,
    PostExecutionReport,
    WorkflowRunContext,
)
from temper_ai.autonomy.constants import (
    DEFAULT_LOOKBACK_HOURS,
    LOOP_TIMEOUT_SECONDS,
    MS_PER_SECOND,
)

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

        if self._budget_exhausted(start, report):
            return report

        if self._config.goals_enabled:
            report.goals_result = self._run_goals(context, report)

        if self._budget_exhausted(start, report):
            return report

        if self._config.auto_apply_learning or self._config.auto_apply_goals:
            report.feedback_result = self._run_feedback(context, report)

        if self._budget_exhausted(start, report):
            return report

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

    def _budget_exhausted(
        self, start: float, report: PostExecutionReport,
    ) -> bool:
        """Return True and finalize report if LOOP_TIMEOUT_SECONDS exceeded."""
        if (time.monotonic() - start) > LOOP_TIMEOUT_SECONDS:
            report.errors.append("Timeout: skipped remaining subsystems")
            elapsed_ms = (time.monotonic() - start) * MS_PER_SECOND
            report.duration_ms = round(elapsed_ms, 1)
            return True
        return False

    def _run_learning(
        self, context: WorkflowRunContext, report: PostExecutionReport
    ) -> Optional[Dict[str, Any]]:
        """Run pattern mining, recommendation generation, and memory sync."""
        try:
            from temper_ai.learning.orchestrator import MiningOrchestrator
            from temper_ai.learning.recommender import RecommendationEngine
            from temper_ai.learning.store import LearningStore

            store = LearningStore()
            orchestrator = MiningOrchestrator(store=store)
            mining_run = orchestrator.run_mining(
                lookback_hours=DEFAULT_LOOKBACK_HOURS
            )

            engine = RecommendationEngine(store=store)
            recs = engine.generate_recommendations()

            # Sync learned patterns to memory system
            self._sync_memory_bridge(store, report)

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

    def _sync_memory_bridge(
        self, store: object, report: PostExecutionReport,
    ) -> None:
        """Sync learned patterns to memory via LearningToMemoryBridge."""
        try:
            from temper_ai.autonomy.memory_bridge import LearningToMemoryBridge

            bridge = LearningToMemoryBridge(learning_store=store)
            synced = bridge.sync_patterns_to_memory()
            report.memory_sync_result = {"patterns_synced": synced}
        except Exception as exc:  # noqa: BLE001
            logger.warning("Memory bridge sync failed: %s", exc)

    def _run_goals(
        self, context: WorkflowRunContext, report: PostExecutionReport
    ) -> Optional[Dict[str, Any]]:
        """Run goal analysis and proposal generation with all analyzers."""
        try:
            from temper_ai.goals.analysis_orchestrator import AnalysisOrchestrator
            from temper_ai.goals.store import GoalStore

            goal_store = GoalStore()

            from temper_ai.learning.store import LearningStore

            learning_store = LearningStore()
            analyzers = self._build_goal_analyzers(learning_store)
            orchestrator = AnalysisOrchestrator(
                store=goal_store, analyzers=analyzers, learning_store=learning_store,
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

    def _build_goal_analyzers(self, learning_store: object) -> list:
        """Build the list of goal analyzers."""
        from temper_ai.goals.analyzers.cost import CostAnalyzer
        from temper_ai.goals.analyzers.cross_product import CrossProductAnalyzer
        from temper_ai.goals.analyzers.performance import PerformanceAnalyzer
        from temper_ai.goals.analyzers.reliability import ReliabilityAnalyzer

        return [
            PerformanceAnalyzer(),
            ReliabilityAnalyzer(),
            CostAnalyzer(),
            CrossProductAnalyzer(learning_store=learning_store),
        ]

    def _run_feedback(
        self, context: WorkflowRunContext, report: PostExecutionReport,
    ) -> Optional[Dict[str, Any]]:
        """Apply learned recommendations and approved goals."""
        try:
            results: Dict[str, Any] = {}
            if self._config.auto_apply_learning:
                results["learning"] = self._apply_learning_feedback()
            if self._config.auto_apply_goals:
                results["goals"] = self._apply_goal_feedback()
            return results if results else None
        except Exception as exc:  # noqa: BLE001
            msg = f"Feedback subsystem error: {exc}"
            logger.warning(msg)
            report.errors.append(msg)
            return None

    def _apply_learning_feedback(self) -> List[Dict[str, Any]]:
        """Apply pending learning recommendations via FeedbackApplier."""
        from temper_ai.autonomy.feedback_applier import FeedbackApplier
        from temper_ai.learning.store import LearningStore

        store = LearningStore()
        applier = FeedbackApplier(
            learning_store=store,
            max_auto_apply=self._config.max_auto_apply_per_run,
        )
        return applier.apply_learning_recommendations(
            min_confidence=self._config.auto_apply_min_confidence,
        )

    def _apply_goal_feedback(self) -> List[Dict[str, Any]]:
        """Apply approved goals via FeedbackApplier."""
        from temper_ai.autonomy.feedback_applier import FeedbackApplier
        from temper_ai.goals.store import GoalStore
        from temper_ai.learning.store import LearningStore

        applier = FeedbackApplier(
            learning_store=LearningStore(),
            goal_store=GoalStore(),
            max_auto_apply=self._config.max_auto_apply_per_run,
        )
        return applier.apply_approved_goals()

    def _run_portfolio(
        self, context: WorkflowRunContext, report: PostExecutionReport
    ) -> Optional[Dict[str, Any]]:
        """Record portfolio run completion and generate scorecards."""
        try:
            from temper_ai.portfolio._schemas import PortfolioConfig
            from temper_ai.portfolio.optimizer import PortfolioOptimizer
            from temper_ai.portfolio.store import PortfolioStore

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
