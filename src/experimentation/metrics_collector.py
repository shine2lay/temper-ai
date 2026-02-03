"""
Experiment metrics collection and analytics.

Integrates A/B testing framework with observability system to:
- Collect experiment metrics from tracked workflow executions
- Aggregate metrics by variant
- Generate experiment analytics reports
"""

import logging
from typing import Dict, List, Any, Optional, Tuple, Generator, ContextManager
from datetime import datetime, timedelta
from sqlmodel import Session, select, func
from sqlalchemy import and_, or_, text

from src.observability.database import get_session
from src.observability.models import (
    WorkflowExecution,
    AgentExecution,
    LLMCall,
    ToolExecution,
)
from src.experimentation.models import (
    Experiment,
    Variant,
    VariantAssignment,
    ExecutionStatus,
)


logger = logging.getLogger(__name__)


class ExperimentMetricsCollector:
    """
    Collects and aggregates experiment metrics from observability database.

    Bridges the A/B testing framework with the observability system by:
    1. Querying workflow executions tagged with experiment_id/variant_id
    2. Extracting metrics from execution records
    3. Aggregating metrics by variant for statistical analysis

    Example:
        >>> collector = ExperimentMetricsCollector()
        >>> assignments = collector.collect_assignments("exp-001")
        >>> metrics = collector.aggregate_metrics_by_variant("exp-001")
    """

    def __init__(self, session: Optional[Session] = None):
        """
        Initialize metrics collector.

        Args:
            session: Optional database session. If None, creates new sessions per query.
        """
        self.session = session
        self._session_provided = session is not None

    def collect_assignments(
        self,
        experiment_id: str,
        status: Optional[str] = None
    ) -> List[VariantAssignment]:
        """
        Collect variant assignments from workflow executions.

        Queries observability database for workflows tagged with experiment_id,
        extracts variant assignments, and computes metrics from execution data.

        Uses json_extract() for database-side filtering to avoid fetching all
        workflows when only a subset belongs to the target experiment.

        Args:
            experiment_id: Experiment ID to query
            status: Optional filter by execution status (completed, failed, etc.)

        Returns:
            List of VariantAssignment objects with metrics populated
        """
        with self._get_session() as session:
            # Use json_extract for database-side filtering (SQLite 3.9+)
            # This avoids fetching all workflows and filtering in Python
            query = select(WorkflowExecution).where(
                text("json_extract(extra_metadata, '$.experiment_id') = :exp_id")
            ).params(exp_id=experiment_id)

            if status:
                query = query.where(WorkflowExecution.status == status)

            workflows = session.exec(query).all()

            assignments = []
            for workflow in workflows:
                metadata = workflow.extra_metadata or {}
                variant_id = metadata.get("variant_id")

                if not variant_id:
                    logger.warning(f"Workflow {workflow.id} has experiment_id but no variant_id")
                    continue

                # Extract metrics from workflow execution
                metrics = self._extract_metrics_from_workflow(workflow)

                # Map workflow status to execution status
                exec_status = self._map_workflow_status(workflow.status)

                # Create assignment record
                assignment = VariantAssignment(
                    id=f"asn-{workflow.id}",
                    experiment_id=experiment_id,
                    variant_id=variant_id,
                    workflow_execution_id=workflow.id,
                    assigned_at=workflow.start_time,
                    assignment_strategy=metadata.get("assignment_strategy", "unknown"),
                    assignment_context=metadata.get("assignment_context"),
                    execution_status=exec_status,
                    execution_started_at=workflow.start_time,
                    execution_completed_at=workflow.end_time,
                    metrics=metrics,
                )

                assignments.append(assignment)

            return assignments

    def _extract_metrics_from_workflow(
        self,
        workflow: WorkflowExecution
    ) -> Dict[str, float]:
        """
        Extract metrics from workflow execution record.

        Args:
            workflow: WorkflowExecution record

        Returns:
            Dictionary of metric name -> value
        """
        metrics = {}

        # Standard execution metrics
        if workflow.duration_seconds is not None:
            metrics["duration_seconds"] = float(workflow.duration_seconds)

        if workflow.total_cost_usd is not None:
            metrics["cost_usd"] = float(workflow.total_cost_usd)

        if workflow.total_tokens is not None:
            metrics["total_tokens"] = float(workflow.total_tokens)

        if workflow.total_llm_calls is not None:
            metrics["llm_calls"] = float(workflow.total_llm_calls)

        if workflow.total_tool_calls is not None:
            metrics["tool_calls"] = float(workflow.total_tool_calls)

        # Extract custom metrics from extra_metadata
        custom_metrics = (workflow.extra_metadata or {}).get("custom_metrics", {})
        for key, value in custom_metrics.items():
            if isinstance(value, (int, float)):
                metrics[key] = float(value)

        # Error rate metric (1.0 if failed, 0.0 if successful)
        metrics["error_rate"] = 1.0 if workflow.status == "failed" else 0.0

        return metrics

    def _map_workflow_status(self, workflow_status: str) -> ExecutionStatus:
        """Map workflow status to execution status enum."""
        status_map = {
            "running": ExecutionStatus.RUNNING,
            "completed": ExecutionStatus.COMPLETED,
            "failed": ExecutionStatus.FAILED,
            "halted": ExecutionStatus.FAILED,
            "timeout": ExecutionStatus.FAILED,
        }
        return status_map.get(workflow_status, ExecutionStatus.PENDING)

    def aggregate_metrics_by_variant(
        self,
        experiment_id: str,
        assignments: Optional[List[VariantAssignment]] = None
    ) -> Dict[str, Dict[str, Any]]:
        """
        Aggregate metrics grouped by variant.

        Args:
            experiment_id: Experiment ID
            assignments: Optional pre-fetched assignments (avoids redundant DB query)

        Returns:
            Dictionary mapping variant_id to aggregated metrics:
            {
                "variant-001": {
                    "count": 100,
                    "successful": 98,
                    "failed": 2,
                    "avg_duration": 45.2,
                    "avg_cost": 0.05,
                    "total_tokens": 150000,
                    ...
                }
            }
        """
        if assignments is None:
            assignments = self.collect_assignments(experiment_id)

        # Group by variant
        variant_data: Dict[str, List[VariantAssignment]] = {}
        for assignment in assignments:
            if assignment.variant_id not in variant_data:
                variant_data[assignment.variant_id] = []
            variant_data[assignment.variant_id].append(assignment)

        # Aggregate metrics per variant
        aggregated = {}
        for variant_id, variant_assignments in variant_data.items():
            aggregated[variant_id] = self._aggregate_assignments(variant_assignments)

        return aggregated

    def _aggregate_assignments(
        self,
        assignments: List[VariantAssignment]
    ) -> Dict[str, Any]:
        """Aggregate metrics from list of assignments."""
        total = len(assignments)
        successful = sum(1 for a in assignments if a.execution_status == ExecutionStatus.COMPLETED)
        failed = sum(1 for a in assignments if a.execution_status == ExecutionStatus.FAILED)

        # Collect all metric names
        all_metric_names: set[str] = set()
        for assignment in assignments:
            if assignment.metrics:
                all_metric_names.update(assignment.metrics.keys())

        # Aggregate each metric
        aggregated = {
            "count": total,
            "successful": successful,
            "failed": failed,
            "success_rate": successful / total if total > 0 else 0.0,
        }

        # For each metric, compute mean and sum
        for metric_name in all_metric_names:
            values = [
                a.metrics[metric_name]
                for a in assignments
                if a.metrics and metric_name in a.metrics
            ]

            if values:
                aggregated[f"avg_{metric_name}"] = sum(values) / len(values)
                aggregated[f"sum_{metric_name}"] = sum(values)
                aggregated[f"min_{metric_name}"] = min(values)
                aggregated[f"max_{metric_name}"] = max(values)

        return aggregated

    def get_experiment_summary(
        self,
        experiment_id: str
    ) -> Dict[str, Any]:
        """
        Generate comprehensive experiment summary.

        Args:
            experiment_id: Experiment ID

        Returns:
            Summary dictionary with overall stats and per-variant breakdowns
        """
        assignments = self.collect_assignments(experiment_id)
        # Pass pre-fetched assignments to avoid redundant DB query
        variant_metrics = self.aggregate_metrics_by_variant(experiment_id, assignments=assignments)

        total_executions = len(assignments)
        completed = sum(1 for a in assignments if a.execution_status == ExecutionStatus.COMPLETED)
        failed = sum(1 for a in assignments if a.execution_status == ExecutionStatus.FAILED)
        running = sum(1 for a in assignments if a.execution_status == ExecutionStatus.RUNNING)

        return {
            "experiment_id": experiment_id,
            "total_executions": total_executions,
            "completed_executions": completed,
            "failed_executions": failed,
            "running_executions": running,
            "completion_rate": completed / total_executions if total_executions > 0 else 0.0,
            "variant_count": len(variant_metrics),
            "variants": variant_metrics,
            "collected_at": datetime.now().isoformat(),
        }

    def query_workflows_by_variant(
        self,
        experiment_id: str,
        variant_id: str,
        limit: Optional[int] = None
    ) -> List[WorkflowExecution]:
        """
        Query workflow executions for specific variant.

        Args:
            experiment_id: Experiment ID
            variant_id: Variant ID
            limit: Optional limit on number of results

        Returns:
            List of WorkflowExecution records
        """
        with self._get_session() as session:
            # Use json_extract for database-side filtering
            query = select(WorkflowExecution).where(
                and_(
                    text("json_extract(extra_metadata, '$.experiment_id') = :exp_id"),
                    text("json_extract(extra_metadata, '$.variant_id') = :var_id"),
                )
            ).params(exp_id=experiment_id, var_id=variant_id)

            if limit:
                query = query.limit(limit)

            return list(session.exec(query).all())

    def get_time_series_metrics(
        self,
        experiment_id: str,
        metric_name: str,
        interval: str = "hour"
    ) -> Dict[str, List[Tuple[datetime, float]]]:
        """
        Get time-series metrics for experiment.

        Args:
            experiment_id: Experiment ID
            metric_name: Metric to track over time
            interval: Time interval (hour, day)

        Returns:
            Dictionary mapping variant_id to list of (timestamp, value) tuples
        """
        assignments = self.collect_assignments(experiment_id, status="completed")

        # Group by variant
        variant_data: Dict[str, List[VariantAssignment]] = {}
        for assignment in assignments:
            if assignment.variant_id not in variant_data:
                variant_data[assignment.variant_id] = []
            variant_data[assignment.variant_id].append(assignment)

        # Build time series for each variant
        time_series = {}
        for variant_id, variant_assignments in variant_data.items():
            # Sort by completion time
            sorted_assignments = sorted(
                variant_assignments,
                key=lambda a: a.execution_completed_at or datetime.min
            )

            # Extract (timestamp, metric_value) pairs
            series = []
            for assignment in sorted_assignments:
                if assignment.execution_completed_at and assignment.metrics:
                    value = assignment.metrics.get(metric_name)
                    if value is not None:
                        series.append((assignment.execution_completed_at, float(value)))

            time_series[variant_id] = series

        return time_series

    def _get_session(self) -> ContextManager[Session]:
        """Get database session (either provided or create new)."""
        if self._session_provided:
            # Return a no-op context manager that yields the provided session
            from contextlib import nullcontext
            assert self.session is not None, "Session must be provided when _session_provided is True"
            return nullcontext(self.session)
        else:
            # Return new session context manager
            return get_session()
