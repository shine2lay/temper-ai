"""
M5 Self-Improvement System Database Models.

This module defines database schema for the M5 self-improvement system,
including custom metrics storage and agent configuration history.
"""
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import JSON, Index
from sqlmodel import Column, Field, SQLModel

from src.database.datetime_utils import utcnow


class CustomMetric(SQLModel, table=True):
    """Storage for custom quality metrics computed by MetricCollectors.

    This table stores metrics that are not automatically tracked by the
    base observability system. Examples include extraction quality scores,
    factual accuracy ratings, code quality metrics, and LLM-as-judge
    evaluations.

    The table is designed to support the M5 self-improvement loop:
    1. MetricCollectors extract metrics from completed executions
    2. Metrics are normalized to [0.0, 1.0] scale
    3. PerformanceAnalyzer aggregates metrics to detect problems
    4. ImprovementStrategy uses patterns to generate better configs

    Schema Design Notes:
    - execution_id links to AgentExecution or WorkflowExecution
    - metric_name identifies which collector produced the metric
    - value is always normalized to [0.0, 1.0] for comparability
    - metric_type classifies collection method (automatic/derived/custom)
    - collector_version enables evolution of metric computation logic
    - metadata stores additional context (e.g., confidence scores, evidence)

    Example Metrics:
    - extraction_quality: 0.95 (95% fields extracted correctly)
    - factual_accuracy: 0.88 (88% facts verified as correct)
    - cost_efficiency: 0.72 (cost normalized by budget)
    - success_rate: 1.0 (execution completed successfully)
    """

    __tablename__ = "custom_metrics"

    # Primary key
    id: Optional[int] = Field(default=None, primary_key=True)

    # Execution reference
    execution_id: str = Field(
        index=True,
        description=(
            "Polymorphic FK - can reference WorkflowExecution.id OR AgentExecution.id. "
            "This intentional design allows metrics to be associated with either workflow-level "
            "or agent-level executions without requiring separate foreign key constraints. "
            "Application code is responsible for maintaining referential integrity."
        )
    )

    # Metric identity
    metric_name: str = Field(
        index=True,
        description="Unique identifier for the metric (e.g., 'extraction_quality')"
    )

    # Metric value (normalized to [0.0, 1.0])
    value: float = Field(
        description="Metric value normalized to 0.0-1.0 scale (0=worst, 1=best)"
    )

    # Classification
    metric_type: str = Field(
        index=True,
        description="Metric collection method: 'automatic', 'derived', or 'custom'"
    )

    # Versioning
    collector_version: str = Field(
        default="1.0",
        description="Version of the MetricCollector that computed this metric"
    )

    # Timing
    collected_at: datetime = Field(
        default_factory=utcnow,
        index=True,
        description="When the metric was computed"
    )

    # Additional context
    extra_metadata: Optional[Dict[str, Any]] = Field(
        default=None,
        sa_column=Column(JSON),
        description="Additional metric context (confidence, evidence, etc.)"
    )

    # Audit trail
    created_at: datetime = Field(
        default_factory=utcnow,
        description="When this record was created"
    )

    __table_args__ = (
        # Composite index for efficient time-series queries
        Index(
            'ix_custom_metrics_execution_collected',
            'execution_id',
            'collected_at'
        ),
        # Composite index for aggregation queries by metric and time
        Index(
            'ix_custom_metrics_metric_collected',
            'metric_name',
            'collected_at'
        ),
        # Composite index for type-based filtering
        Index(
            'ix_custom_metrics_type_collected',
            'metric_type',
            'collected_at'
        ),
    )
