"""SystemMetric record creation from aggregated query results."""
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

from temper_ai.observability.aggregation.period import AggregationPeriod

# UUID hex string length for metric IDs
UUID_HEX_LENGTH = 12


@dataclass
class MetricParams:
    """Parameters for creating a metric record."""
    metric_name: str
    metric_value: float
    metric_unit: str
    period: AggregationPeriod
    timestamp: datetime
    workflow_name: Optional[str] = None
    stage_name: Optional[str] = None
    agent_name: Optional[str] = None
    tags: Optional[Dict[str, Any]] = None


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
            created.append(
                self._create_success_rate_metric(
                    workflow_name, success_rate, total, successful, period, timestamp
                )
            )

        # Average duration metric
        if avg_duration > 0:
            created.append(
                self._create_avg_duration_metric(
                    workflow_name, avg_duration, total, period, timestamp
                )
            )

        # Total cost metric
        if total_cost > 0:
            created.append(
                self._create_total_cost_metric(
                    workflow_name, total_cost, total, period, timestamp
                )
            )

        # P95 duration metric
        if p95_duration > 0:
            created.append(
                self._create_p95_duration_metric(
                    workflow_name, p95_duration, total, period, timestamp
                )
            )

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
            params = MetricParams(
                metric_name="agent_success_rate",
                metric_value=success_rate,
                metric_unit="ratio",
                agent_name=agent_name,
                period=period,
                timestamp=timestamp,
                tags={"total": total, "successful": successful}
            )
            created.append(self._create_metric_from_params(params))

        # Average duration, cost, tokens metrics
        created.extend(
            self._create_agent_performance_metrics(
                agent_name, avg_duration, total_cost, avg_tokens, total, period, timestamp
            )
        )

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
        tags = {"provider": provider, "model": model, "total": total}

        # Success rate metric
        if total > 0:
            success_rate = successful / total
            params = MetricParams(
                metric_name="llm_success_rate",
                metric_value=success_rate,
                metric_unit="ratio",
                period=period,
                timestamp=timestamp,
                tags=tags
            )
            created.append(self._create_metric_from_params(params))

        # Latency and cost metrics
        created.extend(
            self._create_llm_performance_metrics(
                avg_latency, p95_latency, p99_latency, total_cost, tags, period, timestamp
            )
        )

        return created

    def _create_metric(  # noqa: params — legacy interface, delegates to MetricParams
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
        """Create and add SystemMetric record to session (legacy interface).

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
        params = MetricParams(
            metric_name=metric_name,
            metric_value=metric_value,
            metric_unit=metric_unit,
            period=period,
            timestamp=timestamp,
            workflow_name=workflow_name,
            stage_name=stage_name,
            agent_name=agent_name,
            tags=tags
        )
        return self._create_metric_from_params(params)

    def _create_metric_from_params(self, params: MetricParams) -> str:
        """Create and add SystemMetric record to session from params dataclass.

        NOTE: Does NOT commit - caller must commit transaction.

        Args:
            params: MetricParams dataclass with all metric properties

        Returns:
            Created metric ID (format: "metric-{12-char-hex}")
        """
        from temper_ai.storage.database.models import SystemMetric

        metric_id = f"metric-{uuid.uuid4().hex[:UUID_HEX_LENGTH]}"

        metric = SystemMetric(
            id=metric_id,
            metric_name=params.metric_name,
            metric_value=params.metric_value,
            metric_unit=params.metric_unit,
            workflow_name=params.workflow_name,
            stage_name=params.stage_name,
            agent_name=params.agent_name,
            timestamp=params.timestamp,
            aggregation_period=params.period.value,
            tags=params.tags or {}
        )

        self.session.add(metric)
        return metric_id

    def _create_success_rate_metric(
        self,
        workflow_name: str,
        success_rate: float,
        total: int,
        successful: int,
        period: AggregationPeriod,
        timestamp: datetime
    ) -> str:
        """Create workflow success rate metric."""
        params = MetricParams(
            metric_name="workflow_success_rate",
            metric_value=success_rate,
            metric_unit="ratio",
            workflow_name=workflow_name,
            period=period,
            timestamp=timestamp,
            tags={"total": total, "successful": successful}
        )
        return self._create_metric_from_params(params)

    def _create_avg_duration_metric(
        self,
        workflow_name: str,
        avg_duration: float,
        total: int,
        period: AggregationPeriod,
        timestamp: datetime
    ) -> str:
        """Create workflow average duration metric."""
        params = MetricParams(
            metric_name="workflow_avg_duration",
            metric_value=avg_duration,
            metric_unit="seconds",
            workflow_name=workflow_name,
            period=period,
            timestamp=timestamp,
            tags={"total": total}
        )
        return self._create_metric_from_params(params)

    def _create_total_cost_metric(
        self,
        workflow_name: str,
        total_cost: float,
        total: int,
        period: AggregationPeriod,
        timestamp: datetime
    ) -> str:
        """Create workflow total cost metric."""
        params = MetricParams(
            metric_name="workflow_total_cost",
            metric_value=total_cost,
            metric_unit="usd",
            workflow_name=workflow_name,
            period=period,
            timestamp=timestamp,
            tags={"total": total}
        )
        return self._create_metric_from_params(params)

    def _create_p95_duration_metric(
        self,
        workflow_name: str,
        p95_duration: float,
        total: int,
        period: AggregationPeriod,
        timestamp: datetime
    ) -> str:
        """Create workflow P95 duration metric."""
        params = MetricParams(
            metric_name="workflow_p95_duration",
            metric_value=p95_duration,
            metric_unit="seconds",
            workflow_name=workflow_name,
            period=period,
            timestamp=timestamp,
            tags={"total": total}
        )
        return self._create_metric_from_params(params)

    def _create_agent_performance_metrics(
        self,
        agent_name: str,
        avg_duration: float,
        total_cost: float,
        avg_tokens: float,
        total: int,
        period: AggregationPeriod,
        timestamp: datetime
    ) -> List[str]:
        """Create agent performance metrics (duration, cost, tokens)."""
        created = []

        if avg_duration > 0:
            params = MetricParams(
                metric_name="agent_avg_duration",
                metric_value=avg_duration,
                metric_unit="seconds",
                agent_name=agent_name,
                period=period,
                timestamp=timestamp,
                tags={"total": total}
            )
            created.append(self._create_metric_from_params(params))

        if total_cost > 0:
            params = MetricParams(
                metric_name="agent_total_cost",
                metric_value=total_cost,
                metric_unit="usd",
                agent_name=agent_name,
                period=period,
                timestamp=timestamp,
                tags={"total": total}
            )
            created.append(self._create_metric_from_params(params))

        if avg_tokens > 0:
            params = MetricParams(
                metric_name="agent_avg_tokens",
                metric_value=avg_tokens,
                metric_unit="tokens",
                agent_name=agent_name,
                period=period,
                timestamp=timestamp,
                tags={"total": total}
            )
            created.append(self._create_metric_from_params(params))

        return created

    def _create_llm_performance_metrics(
        self,
        avg_latency: float,
        p95_latency: float,
        p99_latency: float,
        total_cost: float,
        tags: Dict[str, Any],
        period: AggregationPeriod,
        timestamp: datetime
    ) -> List[str]:
        """Create LLM performance metrics (latencies and cost)."""
        metric_specs = [
            ("llm_avg_latency", avg_latency, "ms"),
            ("llm_p95_latency", p95_latency, "ms"),
            ("llm_p99_latency", p99_latency, "ms"),
            ("llm_total_cost", total_cost, "usd"),
        ]
        created = []
        for name, value, unit in metric_specs:
            if value > 0:
                params = MetricParams(
                    metric_name=name,
                    metric_value=value,
                    metric_unit=unit,
                    period=period,
                    timestamp=timestamp,
                    tags=tags
                )
                created.append(self._create_metric_from_params(params))
        return created
