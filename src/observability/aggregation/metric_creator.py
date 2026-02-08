"""SystemMetric record creation from aggregated query results."""
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from src.observability.aggregation.period import AggregationPeriod


class MetricRecordCreator:
    """Creates SystemMetric records from aggregated data.

    Handles type conversion, conditional creation (if value > 0),
    and tag construction for different metric types.
    """

    def __init__(self, session: Any):
        """Initialize creator with database session.

        Args:
            session: SQLModel/SQLAlchemy session for adding records
        """
        self.session = session

    def create_workflow_metrics(
        self,
        result: Any,
        period: AggregationPeriod,
        timestamp: datetime
    ) -> List[str]:
        """Create metric records for a single workflow's aggregated data.

        Creates up to 4 metrics:
        - workflow_success_rate (ratio)
        - workflow_avg_duration (seconds)
        - workflow_total_cost (usd)
        - workflow_p95_duration (seconds)

        Args:
            result: Query result row with aggregated values
            period: Aggregation period for metadata
            timestamp: Time bucket start

        Returns:
            List of created metric IDs
        """
        workflow_name = result.workflow_name or "unknown"
        total = int(result.total or 0)
        successful = int(result.successful or 0)
        avg_duration = float(result.avg_duration or 0)
        total_cost = float(result.total_cost or 0)
        p95_duration = float(result.p95_duration or 0)

        created = []

        # Success rate metric
        if total > 0:
            success_rate = successful / total
            metric_id = self._create_metric(
                metric_name="workflow_success_rate",
                metric_value=success_rate,
                metric_unit="ratio",
                workflow_name=workflow_name,
                period=period,
                timestamp=timestamp,
                tags={"total": total, "successful": successful}
            )
            created.append(metric_id)

        # Average duration metric
        if avg_duration > 0:
            metric_id = self._create_metric(
                metric_name="workflow_avg_duration",
                metric_value=avg_duration,
                metric_unit="seconds",
                workflow_name=workflow_name,
                period=period,
                timestamp=timestamp,
                tags={"total": total}
            )
            created.append(metric_id)

        # Total cost metric
        if total_cost > 0:
            metric_id = self._create_metric(
                metric_name="workflow_total_cost",
                metric_value=total_cost,
                metric_unit="usd",
                workflow_name=workflow_name,
                period=period,
                timestamp=timestamp,
                tags={"total": total}
            )
            created.append(metric_id)

        # P95 duration metric
        if p95_duration > 0:
            metric_id = self._create_metric(
                metric_name="workflow_p95_duration",
                metric_value=p95_duration,
                metric_unit="seconds",
                workflow_name=workflow_name,
                period=period,
                timestamp=timestamp,
                tags={"total": total}
            )
            created.append(metric_id)

        return created

    def create_agent_metrics(
        self,
        result: Any,
        period: AggregationPeriod,
        timestamp: datetime
    ) -> List[str]:
        """Create metric records for a single agent's aggregated data.

        Creates up to 4 metrics:
        - agent_success_rate (ratio)
        - agent_avg_duration (seconds)
        - agent_total_cost (usd)
        - agent_avg_tokens (tokens)

        Args:
            result: Query result row
            period: Aggregation period
            timestamp: Time bucket start

        Returns:
            List of created metric IDs
        """
        agent_name = result.agent_name or "unknown"
        total = int(result.total or 0)
        successful = int(result.successful or 0)
        avg_duration = float(result.avg_duration or 0)
        total_cost = float(result.total_cost or 0)
        avg_tokens = float(result.avg_tokens or 0)

        created = []

        # Success rate metric
        if total > 0:
            success_rate = successful / total
            metric_id = self._create_metric(
                metric_name="agent_success_rate",
                metric_value=success_rate,
                metric_unit="ratio",
                agent_name=agent_name,
                period=period,
                timestamp=timestamp,
                tags={"total": total, "successful": successful}
            )
            created.append(metric_id)

        # Average duration metric
        if avg_duration > 0:
            metric_id = self._create_metric(
                metric_name="agent_avg_duration",
                metric_value=avg_duration,
                metric_unit="seconds",
                agent_name=agent_name,
                period=period,
                timestamp=timestamp,
                tags={"total": total}
            )
            created.append(metric_id)

        # Total cost metric
        if total_cost > 0:
            metric_id = self._create_metric(
                metric_name="agent_total_cost",
                metric_value=total_cost,
                metric_unit="usd",
                agent_name=agent_name,
                period=period,
                timestamp=timestamp,
                tags={"total": total}
            )
            created.append(metric_id)

        # Average tokens metric
        if avg_tokens > 0:
            metric_id = self._create_metric(
                metric_name="agent_avg_tokens",
                metric_value=avg_tokens,
                metric_unit="tokens",
                agent_name=agent_name,
                period=period,
                timestamp=timestamp,
                tags={"total": total}
            )
            created.append(metric_id)

        return created

    def create_llm_metrics(
        self,
        result: Any,
        period: AggregationPeriod,
        timestamp: datetime
    ) -> List[str]:
        """Create metric records for a single LLM provider/model combination.

        Creates up to 5 metrics:
        - llm_success_rate (ratio)
        - llm_avg_latency (ms)
        - llm_p95_latency (ms)
        - llm_p99_latency (ms)
        - llm_total_cost (usd)

        Args:
            result: Query result row
            period: Aggregation period
            timestamp: Time bucket start

        Returns:
            List of created metric IDs
        """
        provider = result.provider or "unknown"
        model = result.model or "unknown"
        total = int(result.total or 0)
        successful = int(result.successful or 0)
        avg_latency = float(result.avg_latency or 0)
        p95_latency = float(result.p95_latency or 0)
        p99_latency = float(result.p99_latency or 0)
        total_cost = float(result.total_cost or 0)

        created = []

        # Success rate metric
        if total > 0:
            success_rate = successful / total
            metric_id = self._create_metric(
                metric_name="llm_success_rate",
                metric_value=success_rate,
                metric_unit="ratio",
                period=period,
                timestamp=timestamp,
                tags={"provider": provider, "model": model, "total": total}
            )
            created.append(metric_id)

        # Average latency metric
        if avg_latency > 0:
            metric_id = self._create_metric(
                metric_name="llm_avg_latency",
                metric_value=avg_latency,
                metric_unit="ms",
                period=period,
                timestamp=timestamp,
                tags={"provider": provider, "model": model, "total": total}
            )
            created.append(metric_id)

        # P95 latency metric
        if p95_latency > 0:
            metric_id = self._create_metric(
                metric_name="llm_p95_latency",
                metric_value=p95_latency,
                metric_unit="ms",
                period=period,
                timestamp=timestamp,
                tags={"provider": provider, "model": model, "total": total}
            )
            created.append(metric_id)

        # P99 latency metric
        if p99_latency > 0:
            metric_id = self._create_metric(
                metric_name="llm_p99_latency",
                metric_value=p99_latency,
                metric_unit="ms",
                period=period,
                timestamp=timestamp,
                tags={"provider": provider, "model": model, "total": total}
            )
            created.append(metric_id)

        # Total cost metric
        if total_cost > 0:
            metric_id = self._create_metric(
                metric_name="llm_total_cost",
                metric_value=total_cost,
                metric_unit="usd",
                period=period,
                timestamp=timestamp,
                tags={"provider": provider, "model": model, "total": total}
            )
            created.append(metric_id)

        return created

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
        """Create and add SystemMetric record to session.

        NOTE: Does NOT commit - caller must commit transaction.

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
            Created metric ID (format: "metric-{12-char-hex}")
        """
        from src.database.models import SystemMetric

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
