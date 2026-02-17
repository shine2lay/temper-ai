"""History analyzer for lifecycle adaptation.

Queries the observability database for historical stage and workflow metrics
to provide context for lifecycle adaptation rule evaluation.
"""

import logging
from typing import Dict, Optional

from src.lifecycle._schemas import StageMetrics, WorkflowMetrics
from src.lifecycle.constants import COL_RUN_COUNT, DEFAULT_LOOKBACK_HOURS

logger = logging.getLogger(__name__)


class HistoryAnalyzer:
    """Queries observability DB for historical workflow/stage metrics."""

    def __init__(self, db_url: Optional[str] = None) -> None:
        self._db_url = db_url

    def get_stage_metrics(
        self,
        workflow_name: str,
        lookback_hours: int = DEFAULT_LOOKBACK_HOURS,
    ) -> Dict[str, StageMetrics]:
        """Get historical metrics for each stage of a workflow.

        Args:
            workflow_name: Name of the workflow.
            lookback_hours: How many hours of history to analyze.

        Returns:
            Dict mapping stage name to StageMetrics.
        """
        try:
            return self._query_stage_metrics(
                workflow_name, lookback_hours
            )
        except Exception:  # noqa: BLE001 -- history is optional
            logger.warning(
                "Failed to query stage metrics for %s",
                workflow_name,
                exc_info=True,
            )
            return {}

    def get_workflow_metrics(
        self,
        workflow_name: str,
        lookback_hours: int = DEFAULT_LOOKBACK_HOURS,
    ) -> WorkflowMetrics:
        """Get historical metrics for a workflow.

        Args:
            workflow_name: Name of the workflow.
            lookback_hours: How many hours of history to analyze.

        Returns:
            WorkflowMetrics with aggregated stats.
        """
        try:
            return self._query_workflow_metrics(
                workflow_name, lookback_hours
            )
        except Exception:  # noqa: BLE001 -- history is optional
            logger.warning(
                "Failed to query workflow metrics for %s",
                workflow_name,
                exc_info=True,
            )
            return WorkflowMetrics(workflow_name=workflow_name)

    def _query_stage_metrics(
        self,
        workflow_name: str,
        lookback_hours: int,
    ) -> Dict[str, StageMetrics]:
        """Query stage execution data from observability DB."""
        if self._db_url is None:
            return {}

        try:
            from sqlmodel import Session, create_engine, text

            engine = create_engine(self._db_url, echo=False)
            with Session(engine) as session:
                rows = session.execute(
                    text(
                        "SELECT stage_name, "
                        "AVG(duration_seconds) as avg_dur, "
                        "AVG(CASE WHEN status='completed' THEN 1.0 ELSE 0.0 END) as success, "
                        "COUNT(*) as cnt "
                        "FROM stage_executions "
                        "WHERE workflow_name = :wf "
                        "AND started_at > datetime('now', :lookback) "
                        "GROUP BY stage_name"
                    ).bindparams(
                        wf=workflow_name,
                        lookback=f"-{lookback_hours} hours",
                    )
                ).all()

                result: Dict[str, StageMetrics] = {}
                for row in rows:
                    name = row[0]
                    result[name] = StageMetrics(
                        stage_name=name,
                        avg_duration=float(row[1] or 0),
                        success_rate=float(row[2] or 1),
                        run_count=int(row[COL_RUN_COUNT] or 0),
                    )
                return result
        except Exception:  # noqa: BLE001 -- table may not exist
            logger.debug(
                "Stage metrics query failed (table may not exist)",
                exc_info=True,
            )
            return {}

    def _query_workflow_metrics(
        self,
        workflow_name: str,
        lookback_hours: int,
    ) -> WorkflowMetrics:
        """Query workflow execution data from observability DB."""
        if self._db_url is None:
            return WorkflowMetrics(workflow_name=workflow_name)

        try:
            from sqlmodel import Session, create_engine, text

            engine = create_engine(self._db_url, echo=False)
            with Session(engine) as session:
                rows = session.execute(
                    text(
                        "SELECT "
                        "AVG(duration_seconds) as avg_dur, "
                        "AVG(CASE WHEN status='completed' THEN 1.0 ELSE 0.0 END) as success, "
                        "COUNT(*) as cnt "
                        "FROM workflow_executions "
                        "WHERE workflow_name = :wf "
                        "AND started_at > datetime('now', :lookback)"
                    ).bindparams(
                        wf=workflow_name,
                        lookback=f"-{lookback_hours} hours",
                    )
                ).all()

                if rows and rows[0][2]:
                    row = rows[0]
                    return WorkflowMetrics(
                        workflow_name=workflow_name,
                        avg_duration=float(row[0] or 0),
                        success_rate=float(row[1] or 1),
                        run_count=int(row[2] or 0),
                    )
        except Exception:  # noqa: BLE001 -- table may not exist
            logger.debug(
                "Workflow metrics query failed (table may not exist)",
                exc_info=True,
            )

        return WorkflowMetrics(workflow_name=workflow_name)
