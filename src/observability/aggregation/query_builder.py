"""SQL query construction for metric aggregation."""
from datetime import datetime
from typing import Any

from sqlalchemy import Select

from src.constants.probabilities import PROB_NEAR_CERTAIN

# Percentiles for latency metrics
PERCENTILE_P99 = 0.99


class AggregationQueryBuilder:
    """Builds SQLAlchemy queries for metric aggregation.

    Constructs SELECT statements with aggregation functions,
    time filtering, and appropriate GROUP BY clauses.
    """

    @staticmethod
    def build_workflow_query(
        start_time: datetime,
        end_time: datetime
    ) -> Select[Any]:
        """Build query for workflow execution metrics.

        Returns query that selects:
        - workflow_name (grouping key)
        - total count
        - successful count
        - avg duration
        - total cost
        - p95 duration

        Args:
            start_time: Start of time window
            end_time: End of time window

        Returns:
            SQLAlchemy Select statement
        """
        from sqlalchemy import case
        from sqlmodel import func, select

        from src.database.models import WorkflowExecution

        # SQLAlchemy/mypy complex expression typing issue - using Any return type
        return select(  # type: ignore
            WorkflowExecution.workflow_name,
            func.count(WorkflowExecution.id).label('total'),  # type: ignore
            func.sum(case((WorkflowExecution.status == 'completed', 1), else_=0)).label('successful'),  # type: ignore
            func.avg(WorkflowExecution.duration_seconds).label('avg_duration'),
            func.sum(WorkflowExecution.total_cost_usd).label('total_cost'),
            func.percentile_cont(PROB_NEAR_CERTAIN).within_group(WorkflowExecution.duration_seconds).label('p95_duration')  # type: ignore
        ).where(
            WorkflowExecution.start_time >= start_time,
            WorkflowExecution.start_time < end_time
        ).group_by(WorkflowExecution.workflow_name)

    @staticmethod
    def build_agent_query(
        start_time: datetime,
        end_time: datetime
    ) -> Select[Any]:
        """Build query for agent execution metrics.

        Returns query that selects:
        - agent_name (grouping key)
        - total count
        - successful count
        - avg duration
        - total cost
        - avg tokens

        Args:
            start_time: Start of time window
            end_time: End of time window

        Returns:
            SQLAlchemy Select statement
        """
        from sqlalchemy import case
        from sqlmodel import func, select

        from src.database.models import AgentExecution

        # SQLAlchemy/mypy complex expression typing issue - using Any return type
        return select(  # type: ignore
            AgentExecution.agent_name,
            func.count(AgentExecution.id).label('total'),  # type: ignore
            func.sum(case((AgentExecution.status == 'completed', 1), else_=0)).label('successful'),  # type: ignore
            func.avg(AgentExecution.duration_seconds).label('avg_duration'),
            func.sum(AgentExecution.estimated_cost_usd).label('total_cost'),
            func.avg(AgentExecution.total_tokens).label('avg_tokens')
        ).where(
            AgentExecution.start_time >= start_time,
            AgentExecution.start_time < end_time
        ).group_by(AgentExecution.agent_name)

    @staticmethod
    def build_llm_query(
        start_time: datetime,
        end_time: datetime
    ) -> Select[Any]:
        """Build query for LLM call metrics.

        Returns query that selects:
        - provider, model (grouping keys)
        - total count
        - successful count
        - avg latency
        - p95/p99 latency
        - total cost

        Args:
            start_time: Start of time window
            end_time: End of time window

        Returns:
            SQLAlchemy Select statement
        """
        from sqlalchemy import case
        from sqlmodel import func, select

        from src.database.models import LLMCall

        # SQLAlchemy/mypy complex expression typing issue - using Any return type
        return select(  # type: ignore
            LLMCall.provider,
            LLMCall.model,
            func.count(LLMCall.id).label('total'),  # type: ignore
            func.sum(case((LLMCall.status == 'success', 1), else_=0)).label('successful'),  # type: ignore
            func.avg(LLMCall.latency_ms).label('avg_latency'),
            func.percentile_cont(PROB_NEAR_CERTAIN).within_group(LLMCall.latency_ms).label('p95_latency'),  # type: ignore
            func.percentile_cont(PERCENTILE_P99).within_group(LLMCall.latency_ms).label('p99_latency'),  # type: ignore
            func.sum(LLMCall.estimated_cost_usd).label('total_cost')
        ).where(
            LLMCall.start_time >= start_time,
            LLMCall.start_time < end_time
        ).group_by(LLMCall.provider, LLMCall.model)
