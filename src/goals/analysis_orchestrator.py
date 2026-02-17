"""Analysis orchestrator — coordinates analyzer runs and records results."""

import logging
import uuid
from typing import List, Optional

from src.goals.analyzers.base import BaseAnalyzer
from src.goals.constants import DEFAULT_LOOKBACK_HOURS
from src.goals.models import AnalysisRun
from src.goals.proposer import GoalProposer
from src.goals.store import GoalStore
from src.storage.database.datetime_utils import utcnow

logger = logging.getLogger(__name__)

UUID_HEX_LEN = 12


class AnalysisOrchestrator:
    """Runs goal analysis and records analysis run metadata."""

    def __init__(
        self,
        store: GoalStore,
        analyzers: Optional[List[BaseAnalyzer]] = None,
        learning_store: Optional[object] = None,
    ) -> None:
        self._store = store
        self._proposer = GoalProposer(
            store=store,
            learning_store=learning_store,
            analyzers=analyzers or [],
        )

    def run_analysis(
        self, lookback_hours: int = DEFAULT_LOOKBACK_HOURS
    ) -> AnalysisRun:
        """Execute a full analysis cycle and record results."""
        run = AnalysisRun(
            id=f"ar-{uuid.uuid4().hex[:UUID_HEX_LEN]}",
            started_at=utcnow(),
            status="running",
        )

        try:
            proposals = self._proposer.generate_proposals(
                lookback_hours=lookback_hours
            )
            run.proposals_generated = len(proposals)
            run.status = "completed"
            run.analyzer_stats = {
                "total_proposals": len(proposals),
                "lookback_hours": lookback_hours,
            }
        except Exception as exc:
            run.status = "failed"
            run.error_message = str(exc)
            logger.warning("Analysis run failed: %s", exc)

        run.completed_at = utcnow()
        self._store.save_analysis_run(run)
        logger.info(
            "Analysis run %s: %s (%d proposals)",
            run.id,
            run.status,
            run.proposals_generated,
        )
        return run
