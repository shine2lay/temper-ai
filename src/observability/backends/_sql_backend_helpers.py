"""Helper functions extracted from SQLObservabilityBackend to reduce class size.

Contains:
- Safety violation tracking
- Collaboration event tracking
- Record cleanup (retention)
- Aggregation queries
- Buffer flush logic
- Stats collection
"""
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, cast

from sqlalchemy import case
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlmodel import delete, func, select

from src.database import get_session
from src.database.datetime_utils import ensure_utc
from src.database.models import (
    AgentExecution,
    CollaborationEvent,
    LLMCall,
    StageExecution,
    ToolExecution,
    WorkflowExecution,
)

logger = logging.getLogger(__name__)

# UUID hex string length for collaboration event IDs
UUID_HEX_LENGTH = 12


def track_safety_violation(
    workflow_id: Optional[str],
    stage_id: Optional[str],
    agent_id: Optional[str],
    violation_severity: str,
    violation_message: str,
    policy_name: str,
    service_name: Optional[str] = None,
    context: Optional[Dict[str, Any]] = None,
    timestamp: Optional[datetime] = None,
) -> None:
    """Track safety violation in SQL database."""
    if timestamp is None:
        timestamp = datetime.now(timezone.utc)
    else:
        timestamp = ensure_utc(timestamp)

    # Build metadata
    violation_metadata = {
        "severity": violation_severity,
        "policy": policy_name,
        "service": service_name,
        "message": violation_message,
        "context": context or {},
        "workflow_id": workflow_id,
        "stage_id": stage_id,
        "agent_id": agent_id,
        "timestamp": timestamp.isoformat()
    }

    with get_session() as session:
        # Update agent execution with violation (if agent context exists)
        if agent_id:
            statement = select(AgentExecution).where(AgentExecution.id == agent_id)
            agent = session.exec(statement).first()
            if agent:
                metadata = cast(Dict[str, Any], agent.extra_metadata or {})
                if "safety_violations" not in metadata:
                    metadata["safety_violations"] = []
                metadata["safety_violations"].append(violation_metadata)
                metadata["has_safety_violations"] = True
                metadata["safety_violation_count"] = len(metadata["safety_violations"])
                agent.extra_metadata = metadata

        # Update stage execution with violation (if stage context exists)
        if stage_id:
            stage_stmt = select(StageExecution).where(StageExecution.id == stage_id)
            stage = session.exec(stage_stmt).first()
            if stage:
                stage_metadata = cast(Dict[str, Any], stage.extra_metadata or {})
                if "safety_violations" not in stage_metadata:
                    stage_metadata["safety_violations"] = []
                stage_metadata["safety_violations"].append(violation_metadata)
                stage_metadata["has_safety_violations"] = True
                stage_metadata["safety_violation_count"] = len(stage_metadata["safety_violations"])
                stage.extra_metadata = cast(Any, stage_metadata)

        # Update workflow execution with violation (if workflow context exists)
        if workflow_id:
            wf_stmt = select(WorkflowExecution).where(WorkflowExecution.id == workflow_id)
            workflow = session.exec(wf_stmt).first()
            if workflow:
                wf_metadata = cast(Dict[str, Any], workflow.extra_metadata or {})
                if "safety_violations" not in wf_metadata:
                    wf_metadata["safety_violations"] = []
                wf_metadata["safety_violations"].append(violation_metadata)
                wf_metadata["has_safety_violations"] = True
                wf_metadata["safety_violation_count"] = len(wf_metadata["safety_violations"])
                workflow.extra_metadata = cast(Any, wf_metadata)

        session.commit()


def track_collaboration_event(
    stage_id: str,
    event_type: str,
    agents_involved: List[str],
    event_data: Optional[Dict[str, Any]] = None,
    round_number: Optional[int] = None,
    resolution_strategy: Optional[str] = None,
    outcome: Optional[str] = None,
    confidence_score: Optional[float] = None,
    extra_metadata: Optional[Dict[str, Any]] = None,
    timestamp: Optional[datetime] = None,
) -> str:
    """Track collaboration event to SQL database.

    Returns:
        str: ID of created collaboration event record
    """
    # Generate unique event ID
    event_id = f"collab-{uuid.uuid4().hex[:UUID_HEX_LENGTH]}"

    # Use current timestamp if not provided
    if timestamp is None:
        timestamp = datetime.now(timezone.utc)
    else:
        timestamp = ensure_utc(timestamp)

    # Create collaboration event record
    event = CollaborationEvent(
        id=event_id,
        stage_execution_id=stage_id,
        event_type=event_type,
        timestamp=timestamp,
        round_number=round_number,
        agents_involved=agents_involved,
        event_data=event_data,
        resolution_strategy=resolution_strategy,
        outcome=outcome,
        confidence_score=confidence_score,
        extra_metadata=extra_metadata,
    )

    with get_session() as session:
        try:
            session.add(event)
            session.commit()
            logger.debug(
                f"Tracked collaboration event {event_id}: type={event_type}, stage={stage_id}"
            )
            return event_id

        except IntegrityError as e:
            session.rollback()

            # Robust foreign key violation detection (supports multiple databases)
            error_msg = str(e).lower()
            orig_error = str(e.orig).lower() if hasattr(e, 'orig') else ""
            is_fk_violation = (
                'foreign key' in error_msg or
                'foreign_key' in error_msg or
                'violates foreign key constraint' in error_msg or
                'foreign key constraint failed' in error_msg or
                'foreign key' in orig_error
            )

            if is_fk_violation:
                logger.warning(
                    f"Foreign key violation: stage {stage_id} not found for collaboration event {event_id}",
                    extra={"event_id": event_id, "stage_id": stage_id, "event_type": event_type}
                )
            else:
                logger.error(
                    f"Database integrity error tracking collaboration event {event_id}: {e}",
                    exc_info=True,
                    extra={"event_id": event_id, "event_type": event_type}
                )

            return event_id

        except SQLAlchemyError as e:
            session.rollback()
            logger.error(
                f"Database error tracking collaboration event: {e}",
                exc_info=True,
                extra={"event_id": event_id, "event_type": event_type, "stage_id": stage_id}
            )
            return event_id


def cleanup_old_records(retention_days: int, dry_run: bool = False) -> Dict[str, int]:
    """Clean up old observability records based on retention policy.

    Args:
        retention_days: Number of days to retain records
        dry_run: If True, only count records but don't delete

    Returns:
        Dictionary with counts of records deleted/to be deleted
    """
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=retention_days)

    counts = {
        "workflows": 0,
        "stages": 0,
        "agents": 0,
        "llm_calls": 0,
        "tool_executions": 0
    }

    with get_session() as session:
        # Count workflows to delete
        wf_statement = select(func.count(WorkflowExecution.id)).where(  # type: ignore[arg-type]
            WorkflowExecution.start_time < cutoff_date
        )
        counts["workflows"] = session.exec(wf_statement).first() or 0

        if not dry_run and counts["workflows"] > 0:
            delete_statement = delete(WorkflowExecution).where(
                WorkflowExecution.start_time < cutoff_date  # type: ignore[arg-type]
            )
            session.exec(delete_statement)
            session.commit()
            logger.info(
                f"Deleted {counts['workflows']} workflows older than {retention_days} days"
            )

    return counts


def aggregate_workflow_metrics(workflow_id: str) -> Dict[str, Any]:
    """Aggregate metrics across all agents in a workflow."""
    with get_session() as session:
        metrics_statement = select(
            func.sum(AgentExecution.num_llm_calls).label('total_llm_calls'),  # type: ignore[arg-type]
            func.sum(AgentExecution.num_tool_calls).label('total_tool_calls'),  # type: ignore[arg-type]
            func.sum(AgentExecution.total_tokens).label('total_tokens'),  # type: ignore[arg-type]
            func.sum(AgentExecution.estimated_cost_usd).label('total_cost_usd')  # type: ignore[arg-type]
        ).join(
            StageExecution,
            AgentExecution.stage_execution_id == StageExecution.id
        ).where(StageExecution.workflow_execution_id == workflow_id)

        metrics = session.exec(metrics_statement).first()
        if metrics:
            return {
                'total_llm_calls': int(metrics.total_llm_calls or 0),
                'total_tool_calls': int(metrics.total_tool_calls or 0),
                'total_tokens': int(metrics.total_tokens or 0),
                'total_cost_usd': float(metrics.total_cost_usd or 0.0),
            }
        return {
            'total_llm_calls': 0,
            'total_tool_calls': 0,
            'total_tokens': 0,
            'total_cost_usd': 0.0,
        }


def aggregate_stage_metrics(stage_id: str) -> Dict[str, int]:
    """Aggregate agent metrics within a stage."""
    with get_session() as session:
        metrics_statement = select(
            func.count(AgentExecution.id).label('total'),  # type: ignore[arg-type]
            func.sum(case((AgentExecution.status == 'completed', 1), else_=0)).label('succeeded'),  # type: ignore[arg-type]
            func.sum(case((AgentExecution.status == 'failed', 1), else_=0)).label('failed')  # type: ignore[arg-type]
        ).where(AgentExecution.stage_execution_id == stage_id)

        metrics = session.exec(metrics_statement).first()
        if metrics:
            return {
                'num_agents_executed': int(metrics.total or 0),
                'num_agents_succeeded': int(metrics.succeeded or 0),
                'num_agents_failed': int(metrics.failed or 0),
            }
        return {
            'num_agents_executed': 0,
            'num_agents_succeeded': 0,
            'num_agents_failed': 0,
        }


def get_backend_stats() -> Dict[str, Any]:
    """Get backend statistics and health information."""
    with get_session() as session:
        total_workflows = session.exec(select(func.count(WorkflowExecution.id))).first() or 0  # type: ignore[arg-type]
        total_stages = session.exec(select(func.count(StageExecution.id))).first() or 0  # type: ignore[arg-type]
        total_agents = session.exec(select(func.count(AgentExecution.id))).first() or 0  # type: ignore[arg-type]
        total_llm_calls = session.exec(select(func.count(LLMCall.id))).first() or 0  # type: ignore[arg-type]
        total_tool_calls = session.exec(select(func.count(ToolExecution.id))).first() or 0  # type: ignore[arg-type]

        oldest_wf = session.exec(
            select(WorkflowExecution.start_time).order_by(WorkflowExecution.start_time).limit(1)  # type: ignore[arg-type]
        ).first()
        newest_wf = session.exec(
            select(WorkflowExecution.start_time).order_by(WorkflowExecution.start_time.desc()).limit(1)  # type: ignore[attr-defined]
        ).first()

        return {
            "backend_type": "sql",
            "total_workflows": total_workflows,
            "total_stages": total_stages,
            "total_agents": total_agents,
            "total_llm_calls": total_llm_calls,
            "total_tool_calls": total_tool_calls,
            "oldest_record": oldest_wf.isoformat() if oldest_wf else None,
            "newest_record": newest_wf.isoformat() if newest_wf else None,
        }


def flush_buffer(
    llm_calls: List[Any],
    tool_calls: List[Any],
    agent_metrics: Dict[str, Any],
) -> None:
    """Flush buffered operations to database.

    Executes batch INSERT and UPDATE operations to reduce N+1 queries.
    """
    with get_session() as session:
        # Batch insert LLM calls
        if llm_calls:
            llm_models = [
                LLMCall(
                    id=call.llm_call_id,
                    agent_execution_id=call.agent_id,
                    provider=call.provider,
                    model=call.model,
                    prompt=call.prompt,
                    response=call.response,
                    prompt_tokens=call.prompt_tokens,
                    completion_tokens=call.completion_tokens,
                    total_tokens=call.prompt_tokens + call.completion_tokens,
                    latency_ms=call.latency_ms,
                    estimated_cost_usd=call.estimated_cost_usd,
                    temperature=call.temperature,
                    max_tokens=call.max_tokens,
                    status=call.status,
                    error_message=call.error_message,
                    start_time=ensure_utc(call.start_time),
                    retry_count=0
                )
                for call in llm_calls
            ]
            session.add_all(llm_models)
            logger.debug(f"Batch inserted {len(llm_models)} LLM calls")

        # Batch insert tool calls
        if tool_calls:
            tool_models = [
                ToolExecution(
                    id=call.tool_execution_id,
                    agent_execution_id=call.agent_id,
                    tool_name=call.tool_name,
                    input_params=call.input_params,
                    output_data=call.output_data,
                    start_time=ensure_utc(call.start_time),
                    end_time=ensure_utc(call.start_time) + timedelta(seconds=call.duration_seconds),
                    duration_seconds=call.duration_seconds,
                    status=call.status,
                    error_message=call.error_message,
                    safety_checks_applied=call.safety_checks,
                    approval_required=call.approval_required,
                    retry_count=0
                )
                for call in tool_calls
            ]
            session.add_all(tool_models)
            logger.debug(f"Batch inserted {len(tool_models)} tool calls")

        # Commit inserts
        session.commit()

        # Batch update agent metrics
        if agent_metrics:
            for agent_id, metrics in agent_metrics.items():
                statement = select(AgentExecution).where(AgentExecution.id == agent_id)
                agent = session.exec(statement).first()
                if agent:
                    agent.num_llm_calls = (agent.num_llm_calls or 0) + metrics.num_llm_calls
                    agent.num_tool_calls = (agent.num_tool_calls or 0) + metrics.num_tool_calls
                    agent.total_tokens = (agent.total_tokens or 0) + metrics.total_tokens
                    agent.prompt_tokens = (agent.prompt_tokens or 0) + metrics.prompt_tokens
                    agent.completion_tokens = (agent.completion_tokens or 0) + metrics.completion_tokens
                    agent.estimated_cost_usd = (agent.estimated_cost_usd or 0) + metrics.estimated_cost_usd
            session.commit()
            logger.debug(f"Batch updated {len(agent_metrics)} agent metrics")
