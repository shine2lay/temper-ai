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
from typing import Any, Dict, List, Optional

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
from src.observability.backend import DEFAULT_LIST_LIMIT
from src.observability.constants import ObservabilityFields

logger = logging.getLogger(__name__)

# UUID hex string length for collaboration event IDs
UUID_HEX_LENGTH = 12

# Index of total_cost_usd in aggregate_workflow_metrics query result tuple
_TOTAL_COST_INDEX = 3

# Metadata keys for safety violation tracking
_KEY_SAFETY_VIOLATIONS = "safety_violations"
_KEY_HAS_SAFETY_VIOLATIONS = "has_safety_violations"
_KEY_SAFETY_VIOLATION_COUNT = "safety_violation_count"

# Execution status values — aliases from ObservabilityFields for local use
_STATUS_RUNNING = ObservabilityFields.STATUS_RUNNING
_STATUS_COMPLETED = ObservabilityFields.STATUS_COMPLETED
_STATUS_FAILED = ObservabilityFields.STATUS_FAILED

# Foreign key error detection patterns
_FK_ERROR_PATTERNS = ("foreign key", "foreign_key", "violates foreign key constraint", "foreign key constraint failed")

# Collaboration event ID prefix
_COLLAB_ID_PREFIX = "collab-"

# Backend type identifier
_BACKEND_TYPE_SQL = "sql"

# Default version string for config snapshots
_DEFAULT_VERSION = "1.0"


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
    timestamp_utc: datetime
    if timestamp is None:
        timestamp_utc = datetime.now(timezone.utc)
    else:
        result = ensure_utc(timestamp)
        if result is None:
            raise ValueError("Timestamp conversion failed")
        timestamp_utc = result

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
        "timestamp": timestamp_utc.isoformat()
    }

    with get_session() as session:
        # Update agent execution with violation (if agent context exists)
        if agent_id:
            statement = select(AgentExecution).where(AgentExecution.id == agent_id)
            agent = session.exec(statement).first()
            if agent:
                metadata = agent.extra_metadata or {}
                if _KEY_SAFETY_VIOLATIONS not in metadata:
                    metadata[_KEY_SAFETY_VIOLATIONS] = []
                metadata[_KEY_SAFETY_VIOLATIONS].append(violation_metadata)
                metadata[_KEY_HAS_SAFETY_VIOLATIONS] = True
                metadata[_KEY_SAFETY_VIOLATION_COUNT] = len(metadata[_KEY_SAFETY_VIOLATIONS])
                agent.extra_metadata = metadata

        # Update stage execution with violation (if stage context exists)
        if stage_id:
            stage_stmt = select(StageExecution).where(StageExecution.id == stage_id)
            stage = session.exec(stage_stmt).first()
            if stage:
                stage_metadata = stage.extra_metadata or {}
                if _KEY_SAFETY_VIOLATIONS not in stage_metadata:
                    stage_metadata[_KEY_SAFETY_VIOLATIONS] = []
                stage_metadata[_KEY_SAFETY_VIOLATIONS].append(violation_metadata)
                stage_metadata[_KEY_HAS_SAFETY_VIOLATIONS] = True
                stage_metadata[_KEY_SAFETY_VIOLATION_COUNT] = len(stage_metadata[_KEY_SAFETY_VIOLATIONS])
                stage.extra_metadata = stage_metadata

        # Update workflow execution with violation (if workflow context exists)
        if workflow_id:
            wf_stmt = select(WorkflowExecution).where(WorkflowExecution.id == workflow_id)
            workflow = session.exec(wf_stmt).first()
            if workflow:
                wf_metadata = workflow.extra_metadata or {}
                if _KEY_SAFETY_VIOLATIONS not in wf_metadata:
                    wf_metadata[_KEY_SAFETY_VIOLATIONS] = []
                wf_metadata[_KEY_SAFETY_VIOLATIONS].append(violation_metadata)
                wf_metadata[_KEY_HAS_SAFETY_VIOLATIONS] = True
                wf_metadata[_KEY_SAFETY_VIOLATION_COUNT] = len(wf_metadata[_KEY_SAFETY_VIOLATIONS])
                workflow.extra_metadata = wf_metadata

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
    event_id = f"{_COLLAB_ID_PREFIX}{uuid.uuid4().hex[:UUID_HEX_LENGTH]}"

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
                any(pat in error_msg for pat in _FK_ERROR_PATTERNS) or
                any(pat in orig_error for pat in _FK_ERROR_PATTERNS)
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
            func.sum(AgentExecution.num_llm_calls).label('total_llm_calls'),
            func.sum(AgentExecution.num_tool_calls).label('total_tool_calls'),
            func.sum(AgentExecution.total_tokens).label('total_tokens'),
            func.sum(AgentExecution.estimated_cost_usd).label('total_cost_usd')
        ).join(
            StageExecution,
            AgentExecution.stage_execution_id == StageExecution.id  # type: ignore[arg-type]
        ).where(StageExecution.workflow_execution_id == workflow_id)

        result = session.exec(metrics_statement).first()
        if result:
            return {
                ObservabilityFields.TOTAL_LLM_CALLS: int(result[0] or 0),
                ObservabilityFields.TOTAL_TOOL_CALLS: int(result[1] or 0),
                ObservabilityFields.TOTAL_TOKENS: int(result[2] or 0),
                ObservabilityFields.TOTAL_COST_USD: float(result[_TOTAL_COST_INDEX] or 0.0),
            }
        return {
            ObservabilityFields.TOTAL_LLM_CALLS: 0,
            ObservabilityFields.TOTAL_TOOL_CALLS: 0,
            ObservabilityFields.TOTAL_TOKENS: 0,
            ObservabilityFields.TOTAL_COST_USD: 0.0,
        }


def aggregate_stage_metrics(stage_id: str) -> Dict[str, int]:
    """Aggregate agent metrics within a stage."""
    with get_session() as session:
        metrics_statement = select(
            func.count(AgentExecution.id).label('total'),  # type: ignore[arg-type]
            func.sum(case((AgentExecution.status == _STATUS_COMPLETED, 1), else_=0)).label('succeeded'),  # type: ignore[arg-type]
            func.sum(case((AgentExecution.status == _STATUS_FAILED, 1), else_=0)).label('failed')  # type: ignore[arg-type]
        ).where(AgentExecution.stage_execution_id == stage_id)

        result = session.exec(metrics_statement).first()
        if result:
            return {
                'num_agents_executed': int(result[0] or 0),
                'num_agents_succeeded': int(result[1] or 0),
                'num_agents_failed': int(result[2] or 0),
            }
        return {
            'num_agents_executed': 0,
            'num_agents_succeeded': 0,
            'num_agents_failed': 0,
        }


# ========== Read Operation Helpers ==========


def _workflow_to_dict(wf: Any, stages: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Convert a WorkflowExecution ORM object to a plain dict."""
    return {
        "id": wf.id,
        "workflow_name": wf.workflow_name,
        ObservabilityFields.WORKFLOW_VERSION: wf.workflow_version,
        ObservabilityFields.STATUS: wf.status,
        ObservabilityFields.START_TIME: wf.start_time.isoformat() if wf.start_time else None,
        ObservabilityFields.END_TIME: wf.end_time.isoformat() if wf.end_time else None,
        ObservabilityFields.DURATION_SECONDS: wf.duration_seconds,
        "trigger_type": wf.trigger_type,
        "environment": wf.environment,
        ObservabilityFields.TOTAL_TOKENS: wf.total_tokens,
        ObservabilityFields.TOTAL_COST_USD: wf.total_cost_usd,
        ObservabilityFields.TOTAL_LLM_CALLS: wf.total_llm_calls,
        ObservabilityFields.TOTAL_TOOL_CALLS: wf.total_tool_calls,
        "tags": wf.tags,
        ObservabilityFields.ERROR_MESSAGE: wf.error_message,
        ObservabilityFields.WORKFLOW_CONFIG: wf.workflow_config_snapshot,
        "extra_metadata": wf.extra_metadata,
        "stages": stages or [],
    }


def _stage_to_dict(
    stage: Any,
    agents: Optional[List[Dict[str, Any]]] = None,
    collaboration_events: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Convert a StageExecution ORM object to a plain dict."""
    return {
        "id": stage.id,
        "workflow_execution_id": stage.workflow_execution_id,
        "stage_name": stage.stage_name,
        "stage_config_snapshot": stage.stage_config_snapshot,
        ObservabilityFields.STATUS: stage.status,
        ObservabilityFields.START_TIME: stage.start_time.isoformat() if stage.start_time else None,
        ObservabilityFields.END_TIME: stage.end_time.isoformat() if stage.end_time else None,
        ObservabilityFields.DURATION_SECONDS: stage.duration_seconds,
        ObservabilityFields.INPUT_DATA: stage.input_data,
        ObservabilityFields.OUTPUT_DATA: stage.output_data,
        "num_agents_executed": stage.num_agents_executed,
        "num_agents_succeeded": stage.num_agents_succeeded,
        "num_agents_failed": stage.num_agents_failed,
        ObservabilityFields.ERROR_MESSAGE: stage.error_message,
        "agents": agents or [],
        "collaboration_events": collaboration_events or [],
    }


def _agent_to_dict(
    agent: Any,
    llm_calls: Optional[List[Dict[str, Any]]] = None,
    tool_calls: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Convert an AgentExecution ORM object to a plain dict."""
    return {
        "id": agent.id,
        "stage_execution_id": agent.stage_execution_id,
        ObservabilityFields.AGENT_NAME: agent.agent_name,
        "agent_config_snapshot": agent.agent_config_snapshot,
        ObservabilityFields.STATUS: agent.status,
        ObservabilityFields.START_TIME: agent.start_time.isoformat() if agent.start_time else None,
        ObservabilityFields.END_TIME: agent.end_time.isoformat() if agent.end_time else None,
        ObservabilityFields.DURATION_SECONDS: agent.duration_seconds,
        "reasoning": agent.reasoning,
        "confidence_score": agent.confidence_score,
        ObservabilityFields.TOTAL_TOKENS: agent.total_tokens,
        "prompt_tokens": agent.prompt_tokens,
        "completion_tokens": agent.completion_tokens,
        "estimated_cost_usd": agent.estimated_cost_usd,
        ObservabilityFields.TOTAL_LLM_CALLS: agent.num_llm_calls,
        ObservabilityFields.TOTAL_TOOL_CALLS: agent.num_tool_calls,
        ObservabilityFields.INPUT_DATA: agent.input_data,
        ObservabilityFields.OUTPUT_DATA: agent.output_data,
        ObservabilityFields.ERROR_MESSAGE: agent.error_message,
        "llm_calls": llm_calls or [],
        "tool_calls": tool_calls or [],
    }


def _llm_to_dict(llm: Any) -> Dict[str, Any]:
    """Convert an LLMCall ORM object to a plain dict."""
    return {
        "id": llm.id,
        "agent_execution_id": llm.agent_execution_id,
        "provider": llm.provider,
        "model": llm.model,
        "prompt": llm.prompt,
        "response": llm.response,
        "prompt_tokens": llm.prompt_tokens,
        "completion_tokens": llm.completion_tokens,
        ObservabilityFields.TOTAL_TOKENS: llm.total_tokens,
        "latency_ms": llm.latency_ms,
        "estimated_cost_usd": llm.estimated_cost_usd,
        "temperature": llm.temperature,
        "max_tokens": llm.max_tokens,
        ObservabilityFields.STATUS: llm.status,
        ObservabilityFields.ERROR_MESSAGE: llm.error_message,
        ObservabilityFields.START_TIME: llm.start_time.isoformat() if llm.start_time else None,
        ObservabilityFields.END_TIME: llm.end_time.isoformat() if llm.end_time else None,
    }


def _tool_to_dict(tool: Any) -> Dict[str, Any]:
    """Convert a ToolExecution ORM object to a plain dict."""
    return {
        "id": tool.id,
        "agent_execution_id": tool.agent_execution_id,
        "tool_name": tool.tool_name,
        "input_params": tool.input_params,
        ObservabilityFields.OUTPUT_DATA: tool.output_data,
        ObservabilityFields.START_TIME: tool.start_time.isoformat() if tool.start_time else None,
        ObservabilityFields.END_TIME: tool.end_time.isoformat() if tool.end_time else None,
        ObservabilityFields.DURATION_SECONDS: tool.duration_seconds,
        ObservabilityFields.STATUS: tool.status,
        ObservabilityFields.ERROR_MESSAGE: tool.error_message,
        "safety_checks_applied": tool.safety_checks_applied,
        "approval_required": tool.approval_required,
    }


def _collab_to_dict(event: Any) -> Dict[str, Any]:
    """Convert a CollaborationEvent ORM object to a plain dict."""
    return {
        "id": event.id,
        "stage_execution_id": event.stage_execution_id,
        "event_type": event.event_type,
        "timestamp": event.timestamp.isoformat() if event.timestamp else None,
        "round_number": event.round_number,
        "agents_involved": event.agents_involved,
        "event_data": event.event_data,
        "resolution_strategy": event.resolution_strategy,
        "outcome": event.outcome,
        "confidence_score": event.confidence_score,
        "extra_metadata": event.extra_metadata,
    }  # Collab fields are event-specific, not standard ObservabilityFields


def read_get_workflow(workflow_id: str) -> Optional[Dict[str, Any]]:
    """Get workflow execution with full hierarchy."""
    with get_session() as session:
        wf = session.exec(
            select(WorkflowExecution).where(WorkflowExecution.id == workflow_id)
        ).first()
        if not wf:
            return None

        stages = session.exec(
            select(StageExecution)
            .where(StageExecution.workflow_execution_id == workflow_id)
            .order_by(StageExecution.start_time)  # type: ignore[arg-type]
        ).all()

        stage_dicts = []
        for stage in stages:
            agents = session.exec(
                select(AgentExecution)
                .where(AgentExecution.stage_execution_id == stage.id)
                .order_by(AgentExecution.start_time)  # type: ignore[arg-type]
            ).all()

            agent_dicts = []
            for agent in agents:
                llm_calls = session.exec(
                    select(LLMCall)
                    .where(LLMCall.agent_execution_id == agent.id)
                    .order_by(LLMCall.start_time)  # type: ignore[arg-type]
                ).all()
                tool_calls = session.exec(
                    select(ToolExecution)
                    .where(ToolExecution.agent_execution_id == agent.id)
                    .order_by(ToolExecution.start_time)  # type: ignore[arg-type]
                ).all()
                agent_dicts.append(
                    _agent_to_dict(
                        agent,
                        [_llm_to_dict(llm) for llm in llm_calls],
                        [_tool_to_dict(t) for t in tool_calls],
                    )
                )

            collab_events = session.exec(
                select(CollaborationEvent)
                .where(CollaborationEvent.stage_execution_id == stage.id)
                .order_by(CollaborationEvent.timestamp)  # type: ignore[arg-type]
            ).all()

            stage_dicts.append(
                _stage_to_dict(
                    stage,
                    agent_dicts,
                    [_collab_to_dict(e) for e in collab_events],
                )
            )

        return _workflow_to_dict(wf, stage_dicts)


def read_list_workflows(
    limit: int = DEFAULT_LIST_LIMIT, offset: int = 0, status: Optional[str] = None
) -> List[Dict[str, Any]]:
    """List workflow executions (summary only, no children)."""
    with get_session() as session:
        stmt = select(WorkflowExecution).order_by(
            WorkflowExecution.start_time.desc()  # type: ignore
        )
        if status:
            stmt = stmt.where(WorkflowExecution.status == status)
        stmt = stmt.offset(offset).limit(limit)
        workflows = session.exec(stmt).all()
        return [_workflow_to_dict(wf) for wf in workflows]


def read_get_stage(stage_id: str) -> Optional[Dict[str, Any]]:
    """Get stage with agents and collaboration events."""
    with get_session() as session:
        stage = session.exec(
            select(StageExecution).where(StageExecution.id == stage_id)
        ).first()
        if not stage:
            return None

        agents = session.exec(
            select(AgentExecution)
            .where(AgentExecution.stage_execution_id == stage_id)
            .order_by(AgentExecution.start_time)  # type: ignore[arg-type]
        ).all()

        agent_dicts = []
        for agent in agents:
            llm_calls = session.exec(
                select(LLMCall)
                .where(LLMCall.agent_execution_id == agent.id)
                .order_by(LLMCall.start_time)  # type: ignore[arg-type]
            ).all()
            tool_calls = session.exec(
                select(ToolExecution)
                .where(ToolExecution.agent_execution_id == agent.id)
                .order_by(ToolExecution.start_time)  # type: ignore[arg-type]
            ).all()
            agent_dicts.append(
                _agent_to_dict(
                    agent,
                    [_llm_to_dict(llm) for llm in llm_calls],
                    [_tool_to_dict(t) for t in tool_calls],
                )
            )

        collab_events = session.exec(
            select(CollaborationEvent)
            .where(CollaborationEvent.stage_execution_id == stage_id)
            .order_by(CollaborationEvent.timestamp)  # type: ignore[arg-type]
        ).all()

        return _stage_to_dict(
            stage,
            agent_dicts,
            [_collab_to_dict(e) for e in collab_events],
        )


def read_get_agent(agent_id: str) -> Optional[Dict[str, Any]]:
    """Get agent with LLM calls and tool calls."""
    with get_session() as session:
        agent = session.exec(
            select(AgentExecution).where(AgentExecution.id == agent_id)
        ).first()
        if not agent:
            return None

        llm_calls = session.exec(
            select(LLMCall)
            .where(LLMCall.agent_execution_id == agent_id)
            .order_by(LLMCall.start_time)  # type: ignore[arg-type]
        ).all()
        tool_calls = session.exec(
            select(ToolExecution)
            .where(ToolExecution.agent_execution_id == agent_id)
            .order_by(ToolExecution.start_time)  # type: ignore[arg-type]
        ).all()

        return _agent_to_dict(
            agent,
            [_llm_to_dict(llm) for llm in llm_calls],
            [_tool_to_dict(t) for t in tool_calls],
        )


def read_get_llm_call(llm_call_id: str) -> Optional[Dict[str, Any]]:
    """Get single LLM call with full prompt/response."""
    with get_session() as session:
        llm = session.exec(
            select(LLMCall).where(LLMCall.id == llm_call_id)
        ).first()
        if not llm:
            return None
        return _llm_to_dict(llm)


def read_get_tool_call(tool_call_id: str) -> Optional[Dict[str, Any]]:
    """Get single tool execution with full params/output."""
    with get_session() as session:
        tool = session.exec(
            select(ToolExecution).where(ToolExecution.id == tool_call_id)
        ).first()
        if not tool:
            return None
        return _tool_to_dict(tool)


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
            "backend_type": _BACKEND_TYPE_SQL,
            "total_workflows": total_workflows,
            "total_stages": total_stages,
            "total_agents": total_agents,
            ObservabilityFields.TOTAL_LLM_CALLS: total_llm_calls,
            ObservabilityFields.TOTAL_TOOL_CALLS: total_tool_calls,
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
            tool_models = []
            for call in tool_calls:
                start_time_utc = ensure_utc(call.start_time)
                if start_time_utc is None:
                    raise ValueError("Tool call start_time cannot be None")
                tool_models.append(ToolExecution(
                    id=call.tool_execution_id,
                    agent_execution_id=call.agent_id,
                    tool_name=call.tool_name,
                    input_params=call.input_params,
                    output_data=call.output_data,
                    start_time=start_time_utc,
                    end_time=start_time_utc + timedelta(seconds=call.duration_seconds),
                    duration_seconds=call.duration_seconds,
                    status=call.status,
                    error_message=call.error_message,
                    safety_checks_applied=call.safety_checks,
                    approval_required=call.approval_required,
                    retry_count=0
                ))
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


# ---------------------------------------------------------------------------
# Mixin: delegates thin-wrapper methods to module-level helpers
# ---------------------------------------------------------------------------

class SQLDelegatedMethodsMixin:
    """Mixin providing read, safety, collaboration, and aggregation methods.

    Reduces SQLObservabilityBackend method count by moving thin wrappers
    into this mixin. All methods delegate to module-level helper functions.
    """

    def get_workflow(self, workflow_id: str) -> Optional[Dict[str, Any]]:
        """Get workflow execution with full hierarchy."""
        return read_get_workflow(workflow_id)

    def list_workflows(self, limit: int = DEFAULT_LIST_LIMIT, offset: int = 0, status: Optional[str] = None) -> List[Dict[str, Any]]:
        """List workflow executions (summary only, no children)."""
        return read_list_workflows(limit, offset, status)

    def get_stage(self, stage_id: str) -> Optional[Dict[str, Any]]:
        """Get stage with agents and collaboration events."""
        return read_get_stage(stage_id)

    def get_agent(self, agent_id: str) -> Optional[Dict[str, Any]]:
        """Get agent with LLM calls and tool calls."""
        return read_get_agent(agent_id)

    def get_llm_call(self, llm_call_id: str) -> Optional[Dict[str, Any]]:
        """Get single LLM call with full prompt/response."""
        return read_get_llm_call(llm_call_id)

    def get_tool_call(self, tool_call_id: str) -> Optional[Dict[str, Any]]:
        """Get single tool execution with full params/output."""
        return read_get_tool_call(tool_call_id)

    def track_safety_violation(
        self, workflow_id: Optional[str], stage_id: Optional[str], agent_id: Optional[str],
        violation_severity: str, violation_message: str, policy_name: str,
        service_name: Optional[str] = None, context: Optional[Dict[str, Any]] = None,
        timestamp: Optional[datetime] = None
    ) -> None:
        """Track safety violation."""
        track_safety_violation(
            workflow_id, stage_id, agent_id, violation_severity,
            violation_message, policy_name, service_name, context, timestamp
        )

    def track_collaboration_event(
        self, stage_id: str, event_type: str, agents_involved: List[str],
        event_data: Optional[Dict[str, Any]] = None, round_number: Optional[int] = None,
        resolution_strategy: Optional[str] = None, outcome: Optional[str] = None,
        confidence_score: Optional[float] = None,
        extra_metadata: Optional[Dict[str, Any]] = None,
        timestamp: Optional[datetime] = None
    ) -> str:
        """Track collaboration event."""
        return track_collaboration_event(
            stage_id, event_type, agents_involved, event_data,
            round_number, resolution_strategy, outcome, confidence_score,
            extra_metadata, timestamp
        )

    def cleanup_old_records(self, retention_days: int, dry_run: bool = False) -> Dict[str, int]:
        """Clean up old records."""
        return cleanup_old_records(retention_days, dry_run)

    def get_stats(self) -> Dict[str, Any]:
        """Return backend statistics."""
        return get_backend_stats()

    def aggregate_workflow_metrics(self, workflow_id: str) -> Dict[str, Any]:
        """Aggregate workflow metrics."""
        return aggregate_workflow_metrics(workflow_id)

    def aggregate_stage_metrics(self, stage_id: str) -> Dict[str, int]:
        """Aggregate stage metrics."""
        return aggregate_stage_metrics(stage_id)
