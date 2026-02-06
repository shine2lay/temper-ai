"""Metric aggregation pipeline for observability.

Aggregates raw execution data into SystemMetric records for trend analysis,
dashboards, and SLO monitoring.
"""
import logging
import uuid
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class AggregationPeriod(str, Enum):
    """Time periods for metric aggregation."""
    MINUTE = "minute"
    HOUR = "hour"
    DAY = "day"


class MetricAggregator:
    """Aggregates raw execution metrics into SystemMetric records.

    Computes rollups from WorkflowExecution, AgentExecution, and LLMCall
    records, including:
    - Success rates
    - Average durations
    - Total costs
    - P50/P95/P99 latencies
    - Total token counts

    Example:
        >>> aggregator = MetricAggregator(obs_session)
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
        from sqlalchemy import case
        from sqlmodel import func, select

        from src.observability.models import WorkflowExecution

        # Default time window
        if end_time is None:
            end_time = datetime.now(timezone.utc)
        if start_time is None:
            start_time = self._get_period_start(end_time, period)

        created_metrics = []

        try:
            # Query workflow metrics
            statement = select(
                WorkflowExecution.workflow_name,
                func.count(WorkflowExecution.id).label('total'),
                func.sum(case((WorkflowExecution.status == 'completed', 1), else_=0)).label('successful'),
                func.avg(WorkflowExecution.duration_seconds).label('avg_duration'),
                func.sum(WorkflowExecution.total_cost_usd).label('total_cost'),
                func.percentile_cont(0.95).within_group(WorkflowExecution.duration_seconds).label('p95_duration')
            ).where(
                WorkflowExecution.start_time >= start_time,
                WorkflowExecution.start_time < end_time
            ).group_by(WorkflowExecution.workflow_name)

            results = self.session.exec(statement).all()

            # Create SystemMetric records for each workflow
            for result in results:
                workflow_name = result.workflow_name or "unknown"
                total = int(result.total or 0)
                successful = int(result.successful or 0)
                avg_duration = float(result.avg_duration or 0)
                total_cost = float(result.total_cost or 0)
                p95_duration = float(result.p95_duration or 0)

                # Success rate metric
                if total > 0:
                    success_rate = successful / total
                    metric_id = self._create_metric(
                        metric_name="workflow_success_rate",
                        metric_value=success_rate,
                        metric_unit="ratio",
                        workflow_name=workflow_name,
                        period=period,
                        timestamp=start_time,
                        tags={"total": total, "successful": successful}
                    )
                    created_metrics.append(metric_id)

                # Average duration metric
                if avg_duration > 0:
                    metric_id = self._create_metric(
                        metric_name="workflow_avg_duration",
                        metric_value=avg_duration,
                        metric_unit="seconds",
                        workflow_name=workflow_name,
                        period=period,
                        timestamp=start_time,
                        tags={"total": total}
                    )
                    created_metrics.append(metric_id)

                # Total cost metric
                if total_cost > 0:
                    metric_id = self._create_metric(
                        metric_name="workflow_total_cost",
                        metric_value=total_cost,
                        metric_unit="usd",
                        workflow_name=workflow_name,
                        period=period,
                        timestamp=start_time,
                        tags={"total": total}
                    )
                    created_metrics.append(metric_id)

                # P95 duration metric
                if p95_duration > 0:
                    metric_id = self._create_metric(
                        metric_name="workflow_p95_duration",
                        metric_value=p95_duration,
                        metric_unit="seconds",
                        workflow_name=workflow_name,
                        period=period,
                        timestamp=start_time,
                        tags={"total": total}
                    )
                    created_metrics.append(metric_id)

            self.session.commit()
            logger.info(
                f"Aggregated workflow metrics: {len(results)} workflows, "
                f"{len(created_metrics)} metrics created for period {period.value}"
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
        from sqlalchemy import case
        from sqlmodel import func, select

        from src.observability.models import AgentExecution

        # Default time window
        if end_time is None:
            end_time = datetime.now(timezone.utc)
        if start_time is None:
            start_time = self._get_period_start(end_time, period)

        created_metrics = []

        try:
            # Query agent metrics
            statement = select(
                AgentExecution.agent_name,
                func.count(AgentExecution.id).label('total'),
                func.sum(case((AgentExecution.status == 'completed', 1), else_=0)).label('successful'),
                func.avg(AgentExecution.duration_seconds).label('avg_duration'),
                func.sum(AgentExecution.estimated_cost_usd).label('total_cost'),
                func.avg(AgentExecution.total_tokens).label('avg_tokens')
            ).where(
                AgentExecution.start_time >= start_time,
                AgentExecution.start_time < end_time
            ).group_by(AgentExecution.agent_name)

            results = self.session.exec(statement).all()

            # Create SystemMetric records for each agent
            for result in results:
                agent_name = result.agent_name or "unknown"
                total = int(result.total or 0)
                successful = int(result.successful or 0)
                avg_duration = float(result.avg_duration or 0)
                total_cost = float(result.total_cost or 0)
                avg_tokens = float(result.avg_tokens or 0)

                # Success rate metric
                if total > 0:
                    success_rate = successful / total
                    metric_id = self._create_metric(
                        metric_name="agent_success_rate",
                        metric_value=success_rate,
                        metric_unit="ratio",
                        agent_name=agent_name,
                        period=period,
                        timestamp=start_time,
                        tags={"total": total, "successful": successful}
                    )
                    created_metrics.append(metric_id)

                # Average duration metric
                if avg_duration > 0:
                    metric_id = self._create_metric(
                        metric_name="agent_avg_duration",
                        metric_value=avg_duration,
                        metric_unit="seconds",
                        agent_name=agent_name,
                        period=period,
                        timestamp=start_time,
                        tags={"total": total}
                    )
                    created_metrics.append(metric_id)

                # Total cost metric
                if total_cost > 0:
                    metric_id = self._create_metric(
                        metric_name="agent_total_cost",
                        metric_value=total_cost,
                        metric_unit="usd",
                        agent_name=agent_name,
                        period=period,
                        timestamp=start_time,
                        tags={"total": total}
                    )
                    created_metrics.append(metric_id)

                # Average tokens metric
                if avg_tokens > 0:
                    metric_id = self._create_metric(
                        metric_name="agent_avg_tokens",
                        metric_value=avg_tokens,
                        metric_unit="tokens",
                        agent_name=agent_name,
                        period=period,
                        timestamp=start_time,
                        tags={"total": total}
                    )
                    created_metrics.append(metric_id)

            self.session.commit()
            logger.info(
                f"Aggregated agent metrics: {len(results)} agents, "
                f"{len(created_metrics)} metrics created for period {period.value}"
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
        from sqlalchemy import case
        from sqlmodel import func, select

        from src.observability.models import LLMCall

        # Default time window
        if end_time is None:
            end_time = datetime.now(timezone.utc)
        if start_time is None:
            start_time = self._get_period_start(end_time, period)

        created_metrics = []

        try:
            # Query LLM metrics by provider/model
            statement = select(
                LLMCall.provider,
                LLMCall.model,
                func.count(LLMCall.id).label('total'),
                func.sum(case((LLMCall.status == 'success', 1), else_=0)).label('successful'),
                func.avg(LLMCall.latency_ms).label('avg_latency'),
                func.percentile_cont(0.95).within_group(LLMCall.latency_ms).label('p95_latency'),
                func.percentile_cont(0.99).within_group(LLMCall.latency_ms).label('p99_latency'),
                func.sum(LLMCall.estimated_cost_usd).label('total_cost')
            ).where(
                LLMCall.start_time >= start_time,
                LLMCall.start_time < end_time
            ).group_by(LLMCall.provider, LLMCall.model)

            results = self.session.exec(statement).all()

            # Create SystemMetric records for each provider/model combination
            for result in results:
                provider = result.provider or "unknown"
                model = result.model or "unknown"
                total = int(result.total or 0)
                successful = int(result.successful or 0)
                avg_latency = float(result.avg_latency or 0)
                p95_latency = float(result.p95_latency or 0)
                p99_latency = float(result.p99_latency or 0)
                total_cost = float(result.total_cost or 0)

                # Success rate metric
                if total > 0:
                    success_rate = successful / total
                    metric_id = self._create_metric(
                        metric_name="llm_success_rate",
                        metric_value=success_rate,
                        metric_unit="ratio",
                        period=period,
                        timestamp=start_time,
                        tags={"provider": provider, "model": model, "total": total}
                    )
                    created_metrics.append(metric_id)

                # Average latency metric
                if avg_latency > 0:
                    metric_id = self._create_metric(
                        metric_name="llm_avg_latency",
                        metric_value=avg_latency,
                        metric_unit="ms",
                        period=period,
                        timestamp=start_time,
                        tags={"provider": provider, "model": model, "total": total}
                    )
                    created_metrics.append(metric_id)

                # P95 latency metric
                if p95_latency > 0:
                    metric_id = self._create_metric(
                        metric_name="llm_p95_latency",
                        metric_value=p95_latency,
                        metric_unit="ms",
                        period=period,
                        timestamp=start_time,
                        tags={"provider": provider, "model": model, "total": total}
                    )
                    created_metrics.append(metric_id)

                # P99 latency metric
                if p99_latency > 0:
                    metric_id = self._create_metric(
                        metric_name="llm_p99_latency",
                        metric_value=p99_latency,
                        metric_unit="ms",
                        period=period,
                        timestamp=start_time,
                        tags={"provider": provider, "model": model, "total": total}
                    )
                    created_metrics.append(metric_id)

                # Total cost metric
                if total_cost > 0:
                    metric_id = self._create_metric(
                        metric_name="llm_total_cost",
                        metric_value=total_cost,
                        metric_unit="usd",
                        period=period,
                        timestamp=start_time,
                        tags={"provider": provider, "model": model, "total": total}
                    )
                    created_metrics.append(metric_id)

            self.session.commit()
            logger.info(
                f"Aggregated LLM metrics: {len(results)} provider/model combinations, "
                f"{len(created_metrics)} metrics created for period {period.value}"
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

    def _create_metric(
        self,
        metric_name: str,
        metric_value: float,
        metric_unit: str,
        period: AggregationPeriod,
        timestamp: datetime,
        workflow_name: Optional[str] = None,
        stage_name: Optional[str] = None,
        agent_name: Optional[str] = None,
        tags: Optional[Dict[str, Any]] = None
    ) -> str:
        """Create SystemMetric record.

        Args:
            metric_name: Name of metric
            metric_value: Numeric value
            metric_unit: Unit (ratio, seconds, usd, tokens, ms)
            period: Aggregation period
            timestamp: Time bucket start
            workflow_name: Optional workflow dimension
            stage_name: Optional stage dimension
            agent_name: Optional agent dimension
            tags: Optional tags dict

        Returns:
            Created metric ID
        """
        from src.observability.models import SystemMetric

        metric_id = f"metric-{uuid.uuid4().hex[:12]}"

        metric = SystemMetric(
            id=metric_id,
            metric_name=metric_name,
            metric_value=metric_value,
            metric_unit=metric_unit,
            workflow_name=workflow_name,
            stage_name=stage_name,
            agent_name=agent_name,
            timestamp=timestamp,
            aggregation_period=period.value,
            tags=tags or {}
        )

        self.session.add(metric)
        return metric_id

    def _get_period_start(self, end_time: datetime, period: AggregationPeriod) -> datetime:
        """Calculate period start time from end time.

        Args:
            end_time: End of period
            period: Aggregation period

        Returns:
            Start of period
        """
        if period == AggregationPeriod.MINUTE:
            return end_time - timedelta(minutes=1)
        elif period == AggregationPeriod.HOUR:
            return end_time - timedelta(hours=1)
        elif period == AggregationPeriod.DAY:
            return end_time - timedelta(days=1)
        else:
            return end_time - timedelta(hours=1)  # Default to 1 hour
