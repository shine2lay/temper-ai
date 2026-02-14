"""Main metric aggregator orchestrator."""
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from src.observability.aggregation.metric_creator import MetricRecordCreator
from src.observability.aggregation.period import AggregationPeriod
from src.observability.aggregation.query_builder import AggregationQueryBuilder
from src.observability.aggregation.time_window import TimeWindowCalculator
from src.observability.constants import LOG_MESSAGE_METRICS_CREATED

logger = logging.getLogger(__name__)


class AggregationOrchestrator:
    """Aggregates raw execution metrics into SystemMetric records.

    Computes rollups from WorkflowExecution, AgentExecution, and LLMCall
    records, including:
    - Success rates
    - Average durations
    - Total costs
    - P50/P95/P99 latencies
    - Total token counts

    Example:
        >>> aggregator = AggregationOrchestrator(obs_session)
        >>> aggregator.aggregate_workflow_metrics(
        ...     period=AggregationPeriod.HOUR,
        ...     start_time=datetime.now(timezone.utc) - timedelta(hours=1)
        ... )
    """

    def __init__(self, session: Any):
        """Initialize metric aggregator.

        Args:
            session: SQLModel/SQLAlchemy session
        """
        self.session = session
        self._metric_creator = MetricRecordCreator(session)

    def aggregate_workflow_metrics(
        self,
        period: AggregationPeriod = AggregationPeriod.HOUR,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None
    ) -> List[str]:
        """Aggregate workflow execution metrics.

        Computes:
        - Total workflows
        - Success rate
        - Average duration
        - Total cost
        - P95 duration

        Args:
            period: Aggregation period granularity
            start_time: Start of time window (default: 1 period ago)
            end_time: End of time window (default: now)

        Returns:
            List of created SystemMetric IDs
        """
        # Default time window
        if start_time is None or end_time is None:
            start_time, end_time = TimeWindowCalculator.get_default_time_window(
                period, end_time
            )

        created_metrics = []

        try:
            # Build and execute query
            query = AggregationQueryBuilder.build_workflow_query(
                start_time, end_time
            )
            results = self.session.exec(query).all()

            # Create metrics for each workflow
            for result in results:
                metrics = self._metric_creator.create_workflow_metrics(
                    result, period, start_time
                )
                created_metrics.extend(metrics)

            self.session.commit()
            logger.info(
                f"Aggregated workflow metrics: {len(results)} workflows, "
                f"{len(created_metrics)}{LOG_MESSAGE_METRICS_CREATED}{period.value}"
            )

        except Exception as e:
            logger.error(f"Failed to aggregate workflow metrics: {e}", exc_info=True)
            self.session.rollback()

        return created_metrics

    def aggregate_agent_metrics(
        self,
        period: AggregationPeriod = AggregationPeriod.HOUR,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None
    ) -> List[str]:
        """Aggregate agent execution metrics.

        Computes:
        - Total executions
        - Success rate
        - Average duration
        - Total cost
        - Average tokens

        Args:
            period: Aggregation period granularity
            start_time: Start of time window (default: 1 period ago)
            end_time: End of time window (default: now)

        Returns:
            List of created SystemMetric IDs
        """
        # Default time window
        if start_time is None or end_time is None:
            start_time, end_time = TimeWindowCalculator.get_default_time_window(
                period, end_time
            )

        created_metrics = []

        try:
            # Build and execute query
            query = AggregationQueryBuilder.build_agent_query(
                start_time, end_time
            )
            results = self.session.exec(query).all()

            # Create metrics for each agent
            for result in results:
                metrics = self._metric_creator.create_agent_metrics(
                    result, period, start_time
                )
                created_metrics.extend(metrics)

            self.session.commit()
            logger.info(
                f"Aggregated agent metrics: {len(results)} agents, "
                f"{len(created_metrics)}{LOG_MESSAGE_METRICS_CREATED}{period.value}"
            )

        except Exception as e:
            logger.error(f"Failed to aggregate agent metrics: {e}", exc_info=True)
            self.session.rollback()

        return created_metrics

    def aggregate_llm_metrics(
        self,
        period: AggregationPeriod = AggregationPeriod.HOUR,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None
    ) -> List[str]:
        """Aggregate LLM call metrics.

        Computes:
        - Total calls
        - Success rate
        - Average latency
        - P95/P99 latency
        - Total cost

        Args:
            period: Aggregation period granularity
            start_time: Start of time window (default: 1 period ago)
            end_time: End of time window (default: now)

        Returns:
            List of created SystemMetric IDs
        """
        # Default time window
        if start_time is None or end_time is None:
            start_time, end_time = TimeWindowCalculator.get_default_time_window(
                period, end_time
            )

        created_metrics = []

        try:
            # Build and execute query
            query = AggregationQueryBuilder.build_llm_query(
                start_time, end_time
            )
            results = self.session.exec(query).all()

            # Create metrics for each provider/model combination
            for result in results:
                metrics = self._metric_creator.create_llm_metrics(
                    result, period, start_time
                )
                created_metrics.extend(metrics)

            self.session.commit()
            logger.info(
                f"Aggregated LLM metrics: {len(results)} provider/model combinations, "
                f"{len(created_metrics)}{LOG_MESSAGE_METRICS_CREATED}{period.value}"
            )

        except Exception as e:
            logger.error(f"Failed to aggregate LLM metrics: {e}", exc_info=True)
            self.session.rollback()

        return created_metrics

    def aggregate_all_metrics(
        self,
        period: AggregationPeriod = AggregationPeriod.HOUR,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None
    ) -> Dict[str, List[str]]:
        """Aggregate all metric types.

        Convenience method that runs all aggregation pipelines.

        Args:
            period: Aggregation period granularity
            start_time: Start of time window (default: 1 period ago)
            end_time: End of time window (default: now)

        Returns:
            Dict mapping metric type to list of created IDs
        """
        results = {
            "workflow": self.aggregate_workflow_metrics(period, start_time, end_time),
            "agent": self.aggregate_agent_metrics(period, start_time, end_time),
            "llm": self.aggregate_llm_metrics(period, start_time, end_time)
        }

        total_metrics = sum(len(ids) for ids in results.values())
        logger.info(
            f"Aggregated all metrics for period {period.value}: "
            f"{total_metrics} total metrics created"
        )

        return results
