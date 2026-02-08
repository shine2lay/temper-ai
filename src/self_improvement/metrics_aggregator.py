"""
MetricsAggregator for M5 Self-Improvement System.

Handles SQL-based metric aggregation from agent execution database.
Extracted from PerformanceAnalyzer to follow Single Responsibility Principle.

Design Principles:
- SQL aggregation (100x faster than Python loops)
- Pure database concern (no file I/O, no path validation)
- Stateless queries
- Clear error messages
"""

import logging
from datetime import datetime
from typing import Any, Dict, List

from sqlalchemy import and_, case
from sqlmodel import Session, func, select

from src.database.models import AgentExecution

logger = logging.getLogger(__name__)


class MetricsAggregator:
    """
    Aggregates performance metrics from agent execution database.

    Responsibilities:
    - SQL-based metric queries
    - Statistical aggregation (mean, count)
    - Agent name discovery in time windows

    Example:
        >>> aggregator = MetricsAggregator(session)
        >>> metrics = aggregator.aggregate_metrics(
        ...     "my_agent",
        ...     window_start,
        ...     window_end
        ... )
        >>> print(f"Total executions: {metrics['total_executions']}")
    """

    def __init__(self, session: Session):
        """
        Initialize aggregator with database session.

        Args:
            session: SQLModel session for database queries
        """
        self.session = session

    def aggregate_metrics(
        self,
        agent_name: str,
        window_start: datetime,
        window_end: datetime,
        include_failed: bool = False
    ) -> Dict[str, Any]:
        """
        Aggregate built-in metrics from agent_executions table.

        Aggregates:
        - success_rate (mean)
        - duration_seconds (mean)
        - cost_usd (mean)
        - total_tokens (mean)

        Args:
            agent_name: Name of agent to query
            window_start: Start of time window
            window_end: End of time window
            include_failed: Whether to include failed executions

        Returns:
            Dict with metric names as keys, aggregates as values
            Always includes "total_executions" key

        Example:
            >>> metrics = aggregator.aggregate_metrics(
            ...     "code_review_agent",
            ...     datetime(2024, 1, 1),
            ...     datetime(2024, 1, 7)
            ... )
            >>> print(f"Success rate: {metrics['success_rate']['mean']:.2%}")
        """
        # Build query filters
        filters = [
            AgentExecution.agent_name == agent_name,
            AgentExecution.start_time >= window_start,
            AgentExecution.start_time < window_end
        ]

        if not include_failed:
            filters.append(AgentExecution.status == "completed")

        # Aggregate query
        statement = select(
            func.count(AgentExecution.id).label("total"),
            func.sum(
                case((AgentExecution.status == "completed", 1), else_=0)
            ).label("completed"),
            func.avg(AgentExecution.duration_seconds).label("avg_duration"),
            func.avg(AgentExecution.estimated_cost_usd).label("avg_cost"),
            func.avg(AgentExecution.total_tokens).label("avg_tokens"),
        ).where(and_(*filters))

        result = self.session.exec(statement).first()

        if not result or result.total == 0:
            return {"total_executions": 0}

        # Calculate success_rate
        success_rate = result.completed / result.total if result.total > 0 else 0.0

        # Build metrics dict
        metrics = {
            "total_executions": result.total,
            "success_rate": {"mean": success_rate}
        }

        # Add duration metrics (if available)
        if result.avg_duration is not None:
            metrics["duration_seconds"] = {"mean": float(result.avg_duration)}

        # Add cost metrics (if available)
        if result.avg_cost is not None:
            metrics["cost_usd"] = {"mean": float(result.avg_cost)}

        # Add token metrics (if available)
        if result.avg_tokens is not None:
            metrics["total_tokens"] = {"mean": float(result.avg_tokens)}

        logger.debug(
            f"Aggregated metrics: agent={agent_name}, "
            f"executions={metrics['total_executions']}, "
            f"success_rate={success_rate:.2%}"
        )

        return metrics

    def get_agent_names_in_window(
        self,
        window_start: datetime,
        window_end: datetime
    ) -> List[str]:
        """
        Get distinct agent names with executions in time window.

        Args:
            window_start: Start of time window
            window_end: End of time window

        Returns:
            List of distinct agent names

        Example:
            >>> agents = aggregator.get_agent_names_in_window(
            ...     datetime(2024, 1, 1),
            ...     datetime(2024, 1, 7)
            ... )
            >>> print(f"Found {len(agents)} agents")
        """
        statement = select(AgentExecution.agent_name).where(
            and_(
                AgentExecution.start_time >= window_start,
                AgentExecution.start_time < window_end
            )
        ).distinct()

        agent_names = self.session.exec(statement).all()

        logger.debug(
            f"Found {len(agent_names)} agents in window "
            f"({window_start.isoformat()} to {window_end.isoformat()})"
        )

        return list(agent_names)
