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
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import case
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import selectinload
from sqlmodel import col, delete, func, select

from temper_ai.observability.backend import (
    DEFAULT_LIST_LIMIT,
    ErrorFingerprintData,
)
from temper_ai.observability.backend import (
    CollaborationEventData as BackendCollaborationEventData,
)
from temper_ai.observability.backend import (
    SafetyViolationData as BackendSafetyViolationData,
)
from temper_ai.observability.constants import ObservabilityFields
from temper_ai.storage.database import get_session
from temper_ai.storage.database.datetime_utils import ensure_utc
from temper_ai.storage.database.models import (
    AgentExecution,
    CollaborationEvent,
    ErrorFingerprint,
    LLMCall,
    StageExecution,
    ToolExecution,
    WorkflowExecution,
)

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
_FK_ERROR_PATTERNS = (
    "foreign key",
    "foreign_key",
    "violates foreign key constraint",
    "foreign key constraint failed",
)

# Collaboration event ID prefix
_COLLAB_ID_PREFIX = "collab-"

# Backend type identifier
_BACKEND_TYPE_SQL = "sql"

# Default version string for config snapshots
_DEFAULT_VERSION = "1.0"


# ========== Parameter Bundling Dataclasses ==========


@dataclass
class SqlSafetyViolationParams:
    """Bundle parameters for safety violation tracking."""

    workflow_id: str | None
    stage_id: str | None
    agent_id: str | None
    violation_severity: str
    violation_message: str
    policy_name: str
    service_name: str | None = None
    context: dict[str, Any] | None = None
    timestamp: datetime | None = None


@dataclass
class SqlCollaborationEventParams:
    """Bundle parameters for collaboration event tracking."""

    stage_id: str
    event_type: str
    agents_involved: list[str]
    event_data: dict[str, Any] | None = None
    round_number: int | None = None
    resolution_strategy: str | None = None
    outcome: str | None = None
    confidence_score: float | None = None
    extra_metadata: dict[str, Any] | None = None
    timestamp: datetime | None = None


def _ensure_timestamp_utc(timestamp: datetime | None) -> datetime:
    """Ensure timestamp is in UTC timezone."""
    if timestamp is None:
        return datetime.now(UTC)
    result = ensure_utc(timestamp)
    if result is None:
        raise ValueError("Timestamp conversion failed")
    return result


def _build_violation_metadata(
    data: SqlSafetyViolationParams, timestamp_utc: datetime
) -> dict[str, Any]:
    """Build violation metadata dictionary."""
    return {
        "severity": data.violation_severity,
        "policy": data.policy_name,
        "service": data.service_name,
        "message": data.violation_message,
        "context": data.context or {},
        "workflow_id": data.workflow_id,
        "stage_id": data.stage_id,
        "agent_id": data.agent_id,
        "timestamp": timestamp_utc.isoformat(),
    }


def _update_execution_metadata(
    metadata: dict[str, Any], violation_metadata: dict[str, Any]
) -> dict[str, Any]:
    """Update execution metadata with violation info."""
    if _KEY_SAFETY_VIOLATIONS not in metadata:
        metadata[_KEY_SAFETY_VIOLATIONS] = []
    metadata[_KEY_SAFETY_VIOLATIONS].append(violation_metadata)
    metadata[_KEY_HAS_SAFETY_VIOLATIONS] = True
    metadata[_KEY_SAFETY_VIOLATION_COUNT] = len(metadata[_KEY_SAFETY_VIOLATIONS])
    return metadata


def track_safety_violation(data: SqlSafetyViolationParams) -> None:
    """Track safety violation in SQL database.

    Args:
        data: SqlSafetyViolationParams with all violation parameters
    """
    timestamp_utc = _ensure_timestamp_utc(data.timestamp)
    violation_metadata = _build_violation_metadata(data, timestamp_utc)

    with get_session() as session:
        # Update agent execution with violation (if agent context exists)
        if data.agent_id:
            statement = select(AgentExecution).where(AgentExecution.id == data.agent_id)
            agent = session.exec(statement).first()
            if agent:
                metadata = agent.extra_metadata or {}
                agent.extra_metadata = _update_execution_metadata(
                    metadata, violation_metadata
                )

        # Update stage execution with violation (if stage context exists)
        if data.stage_id:
            stage_stmt = select(StageExecution).where(
                StageExecution.id == data.stage_id
            )
            stage = session.exec(stage_stmt).first()
            if stage:
                stage_metadata = stage.extra_metadata or {}
                stage.extra_metadata = _update_execution_metadata(
                    stage_metadata, violation_metadata
                )

        # Update workflow execution with violation (if workflow context exists)
        if data.workflow_id:
            wf_stmt = select(WorkflowExecution).where(
                WorkflowExecution.id == data.workflow_id
            )
            workflow = session.exec(wf_stmt).first()
            if workflow:
                wf_metadata = workflow.extra_metadata or {}
                workflow.extra_metadata = _update_execution_metadata(
                    wf_metadata, violation_metadata
                )

        session.commit()


def _create_collaboration_event_record(
    event_id: str, data: SqlCollaborationEventParams, timestamp: datetime
) -> CollaborationEvent:
    """Create a CollaborationEvent ORM object."""
    return CollaborationEvent(
        id=event_id,
        stage_execution_id=data.stage_id,
        event_type=data.event_type,
        timestamp=timestamp,
        round_number=data.round_number,
        agents_involved=data.agents_involved,
        event_data=data.event_data,
        resolution_strategy=data.resolution_strategy,
        outcome=data.outcome,
        confidence_score=data.confidence_score,
        extra_metadata=data.extra_metadata,
    )


def _handle_collaboration_integrity_error(
    e: IntegrityError, event_id: str, data: SqlCollaborationEventParams
) -> None:
    """Handle IntegrityError from collaboration event tracking."""
    # Robust foreign key violation detection (supports multiple databases)
    error_msg = str(e).lower()
    orig_error = str(e.orig).lower() if hasattr(e, "orig") else ""
    is_fk_violation = any(pat in error_msg for pat in _FK_ERROR_PATTERNS) or any(
        pat in orig_error for pat in _FK_ERROR_PATTERNS
    )

    if is_fk_violation:
        logger.warning(
            f"Foreign key violation: stage {data.stage_id} not found for collaboration event {event_id}",
            extra={
                "event_id": event_id,
                "stage_id": data.stage_id,
                "event_type": data.event_type,
            },
        )
    else:
        logger.error(
            f"Database integrity error tracking collaboration event {event_id}: {e}",
            exc_info=True,
            extra={"event_id": event_id, "event_type": data.event_type},
        )


def track_collaboration_event(data: SqlCollaborationEventParams) -> str:
    """Track collaboration event to SQL database.

    Args:
        data: SqlCollaborationEventParams with all event parameters

    Returns:
        str: ID of created collaboration event record
    """
    event_id = f"{_COLLAB_ID_PREFIX}{uuid.uuid4().hex[:UUID_HEX_LENGTH]}"

    # Use current timestamp if not provided
    timestamp = _ensure_timestamp_utc(data.timestamp)

    event = _create_collaboration_event_record(event_id, data, timestamp)

    with get_session() as session:
        try:
            session.add(event)
            session.commit()
            logger.debug(
                f"Tracked collaboration event {event_id}: type={data.event_type}, stage={data.stage_id}"
            )
            return event_id

        except IntegrityError as e:
            session.rollback()
            _handle_collaboration_integrity_error(e, event_id, data)
            return event_id

        except SQLAlchemyError as e:
            session.rollback()
            logger.error(
                f"Database error tracking collaboration event: {e}",
                exc_info=True,
                extra={
                    "event_id": event_id,
                    "event_type": data.event_type,
                    "stage_id": data.stage_id,
                },
            )
            return event_id


def cleanup_old_records(retention_days: int, dry_run: bool = False) -> dict[str, int]:
    """Clean up old observability records based on retention policy.

    Args:
        retention_days: Number of days to retain records
        dry_run: If True, only count records but don't delete

    Returns:
        Dictionary with counts of records deleted/to be deleted
    """
    cutoff_date = datetime.now(UTC) - timedelta(days=retention_days)

    counts = {
        "workflows": 0,
        "stages": 0,
        "agents": 0,
        "llm_calls": 0,
        "tool_executions": 0,
    }

    with get_session() as session:
        # Count workflows to delete
        wf_statement = select(func.count(col(WorkflowExecution.id))).where(
            col(WorkflowExecution.start_time) < cutoff_date
        )
        counts["workflows"] = session.exec(wf_statement).first() or 0

        if not dry_run and counts["workflows"] > 0:
            delete_statement = delete(WorkflowExecution).where(
                col(WorkflowExecution.start_time) < cutoff_date
            )
            session.execute(delete_statement)
            session.commit()
            logger.info(
                f"Deleted {counts['workflows']} workflows older than {retention_days} days"
            )

    return counts


def aggregate_workflow_metrics(workflow_id: str) -> dict[str, Any]:
    """Aggregate metrics across all agents in a workflow."""
    with get_session() as session:
        metrics_statement = (
            select(
                func.sum(AgentExecution.num_llm_calls).label("total_llm_calls"),
                func.sum(AgentExecution.num_tool_calls).label("total_tool_calls"),
                func.sum(AgentExecution.total_tokens).label("total_tokens"),
                func.sum(AgentExecution.estimated_cost_usd).label("total_cost_usd"),
            )
            .join(
                StageExecution,
                col(AgentExecution.stage_execution_id) == col(StageExecution.id),
            )
            .where(StageExecution.workflow_execution_id == workflow_id)
        )

        result = session.exec(metrics_statement).first()
        if result:
            return {
                ObservabilityFields.TOTAL_LLM_CALLS: int(result[0] or 0),
                ObservabilityFields.TOTAL_TOOL_CALLS: int(result[1] or 0),
                ObservabilityFields.TOTAL_TOKENS: int(result[2] or 0),
                ObservabilityFields.TOTAL_COST_USD: float(
                    result[_TOTAL_COST_INDEX] or 0.0
                ),
            }
        return {
            ObservabilityFields.TOTAL_LLM_CALLS: 0,
            ObservabilityFields.TOTAL_TOOL_CALLS: 0,
            ObservabilityFields.TOTAL_TOKENS: 0,
            ObservabilityFields.TOTAL_COST_USD: 0.0,
        }


def aggregate_stage_metrics(stage_id: str) -> dict[str, int]:
    """Aggregate agent metrics within a stage."""
    with get_session() as session:
        metrics_statement = select(
            func.count(col(AgentExecution.id)).label("total"),
            func.sum(
                case((col(AgentExecution.status) == _STATUS_COMPLETED, 1), else_=0)
            ).label("succeeded"),
            func.sum(
                case((col(AgentExecution.status) == _STATUS_FAILED, 1), else_=0)
            ).label("failed"),
        ).where(AgentExecution.stage_execution_id == stage_id)

        result = session.exec(metrics_statement).first()
        if result:
            return {
                "num_agents_executed": int(result[0] or 0),
                "num_agents_succeeded": int(result[1] or 0),
                "num_agents_failed": int(result[2] or 0),
            }
        return {
            "num_agents_executed": 0,
            "num_agents_succeeded": 0,
            "num_agents_failed": 0,
        }


# ========== Read Operation Helpers ==========


def _workflow_to_dict(
    wf: Any, stages: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    """Convert a WorkflowExecution ORM object to a plain dict."""
    return {
        "id": wf.id,
        "workflow_name": wf.workflow_name,
        ObservabilityFields.WORKFLOW_VERSION: wf.workflow_version,
        ObservabilityFields.STATUS: wf.status,
        ObservabilityFields.START_TIME: (
            wf.start_time.isoformat() if wf.start_time else None
        ),
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
        "cost_attribution_tags": wf.cost_attribution_tags,
        "tenant_id": wf.tenant_id,
        "stages": stages or [],
    }


def _stage_to_dict(
    stage: Any,
    agents: list[dict[str, Any]] | None = None,
    collaboration_events: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Convert a StageExecution ORM object to a plain dict."""
    return {
        "id": stage.id,
        "workflow_execution_id": stage.workflow_execution_id,
        "stage_name": stage.stage_name,
        "stage_config_snapshot": stage.stage_config_snapshot,
        ObservabilityFields.STATUS: stage.status,
        ObservabilityFields.START_TIME: (
            stage.start_time.isoformat() if stage.start_time else None
        ),
        ObservabilityFields.END_TIME: (
            stage.end_time.isoformat() if stage.end_time else None
        ),
        ObservabilityFields.DURATION_SECONDS: stage.duration_seconds,
        ObservabilityFields.INPUT_DATA: stage.input_data,
        ObservabilityFields.OUTPUT_DATA: stage.output_data,
        "num_agents_executed": stage.num_agents_executed,
        "num_agents_succeeded": stage.num_agents_succeeded,
        "num_agents_failed": stage.num_agents_failed,
        ObservabilityFields.ERROR_MESSAGE: stage.error_message,
        "output_lineage": stage.output_lineage,
        "tenant_id": stage.tenant_id,
        "agents": agents or [],
        "collaboration_events": collaboration_events or [],
    }


def _agent_to_dict(
    agent: Any,
    llm_calls: list[dict[str, Any]] | None = None,
    tool_calls: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Convert an AgentExecution ORM object to a plain dict."""
    return {
        "id": agent.id,
        "stage_execution_id": agent.stage_execution_id,
        ObservabilityFields.AGENT_NAME: agent.agent_name,
        "agent_config_snapshot": agent.agent_config_snapshot,
        ObservabilityFields.STATUS: agent.status,
        ObservabilityFields.START_TIME: (
            agent.start_time.isoformat() if agent.start_time else None
        ),
        ObservabilityFields.END_TIME: (
            agent.end_time.isoformat() if agent.end_time else None
        ),
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
        "tenant_id": agent.tenant_id,
        "llm_calls": llm_calls or [],
        "tool_calls": tool_calls or [],
    }


def _llm_to_dict(llm: Any) -> dict[str, Any]:
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
        ObservabilityFields.START_TIME: (
            llm.start_time.isoformat() if llm.start_time else None
        ),
        ObservabilityFields.END_TIME: (
            llm.end_time.isoformat() if llm.end_time else None
        ),
        "failover_sequence": llm.failover_sequence,
        "failover_from_provider": llm.failover_from_provider,
        "prompt_template_hash": llm.prompt_template_hash,
        "prompt_template_source": llm.prompt_template_source,
        "tenant_id": llm.tenant_id,
    }


def _tool_to_dict(tool: Any) -> dict[str, Any]:
    """Convert a ToolExecution ORM object to a plain dict."""
    return {
        "id": tool.id,
        "agent_execution_id": tool.agent_execution_id,
        "tool_name": tool.tool_name,
        "input_params": tool.input_params,
        ObservabilityFields.OUTPUT_DATA: tool.output_data,
        ObservabilityFields.START_TIME: (
            tool.start_time.isoformat() if tool.start_time else None
        ),
        ObservabilityFields.END_TIME: (
            tool.end_time.isoformat() if tool.end_time else None
        ),
        ObservabilityFields.DURATION_SECONDS: tool.duration_seconds,
        ObservabilityFields.STATUS: tool.status,
        ObservabilityFields.ERROR_MESSAGE: tool.error_message,
        "safety_checks_applied": tool.safety_checks_applied,
        "approval_required": tool.approval_required,
        "tenant_id": tool.tenant_id,
    }


def _collab_to_dict(event: Any) -> dict[str, Any]:
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
        "tenant_id": event.tenant_id,
    }  # Collab fields are event-specific, not standard ObservabilityFields


def _eager_build_workflow_dict(wf: Any) -> dict[str, Any]:
    """Build workflow dict from eagerly-loaded ORM object.

    Walks pre-loaded relationships (via selectinload) and sorts children
    by start_time/timestamp to match the ordering of the N+1 approach.
    """
    stage_dicts = []
    for stage in sorted(wf.stages, key=lambda s: (s.start_time is None, s.start_time)):
        agent_dicts = []
        for agent in sorted(
            stage.agents, key=lambda a: (a.start_time is None, a.start_time)
        ):
            agent_dicts.append(
                _agent_to_dict(
                    agent,
                    [
                        _llm_to_dict(call)
                        for call in sorted(
                            agent.llm_calls,
                            key=lambda call: (call.start_time is None, call.start_time),
                        )
                    ],
                    [
                        _tool_to_dict(tool)
                        for tool in sorted(
                            agent.tool_executions,
                            key=lambda tool: (tool.start_time is None, tool.start_time),
                        )
                    ],
                )
            )
        collab_dicts = [
            _collab_to_dict(e)
            for e in sorted(
                stage.collaboration_events,
                key=lambda e: (e.timestamp is None, e.timestamp),
            )
        ]
        stage_dicts.append(_stage_to_dict(stage, agent_dicts, collab_dicts))
    return _workflow_to_dict(wf, stage_dicts)


def read_get_workflow(workflow_id: str) -> dict[str, Any] | None:
    """Get workflow execution with full hierarchy using eager loading.

    Uses selectinload to batch-load the entire hierarchy in ~5 queries
    instead of 20-40 individual queries (N+1 elimination).
    """
    with get_session() as session:
        statement = (
            select(WorkflowExecution)
            .where(WorkflowExecution.id == workflow_id)
            .options(
                selectinload(WorkflowExecution.stages).options(  # type: ignore[arg-type]
                    selectinload(StageExecution.agents).options(  # type: ignore[arg-type]
                        selectinload(AgentExecution.llm_calls),  # type: ignore[arg-type]
                        selectinload(AgentExecution.tool_executions),  # type: ignore[arg-type]
                    ),
                    selectinload(StageExecution.collaboration_events),  # type: ignore[arg-type]
                )
            )
        )
        wf = session.exec(statement).first()
        if not wf:
            return None
        return _eager_build_workflow_dict(wf)


def read_list_workflows(
    limit: int = DEFAULT_LIST_LIMIT, offset: int = 0, status: str | None = None
) -> list[dict[str, Any]]:
    """List workflow executions (summary only, no children)."""
    with get_session() as session:
        stmt = select(WorkflowExecution).order_by(
            col(WorkflowExecution.start_time).desc()
        )
        if status:
            stmt = stmt.where(WorkflowExecution.status == status)
        stmt = stmt.offset(offset).limit(limit)
        workflows = session.exec(stmt).all()
        return [_workflow_to_dict(wf) for wf in workflows]


def read_get_stage(stage_id: str) -> dict[str, Any] | None:
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
            .order_by(col(AgentExecution.start_time))
        ).all()

        agent_dicts = []
        for agent in agents:
            llm_calls = session.exec(
                select(LLMCall)
                .where(LLMCall.agent_execution_id == agent.id)
                .order_by(col(LLMCall.start_time))
            ).all()
            tool_calls = session.exec(
                select(ToolExecution)
                .where(ToolExecution.agent_execution_id == agent.id)
                .order_by(col(ToolExecution.start_time))
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
            .order_by(col(CollaborationEvent.timestamp))
        ).all()

        return _stage_to_dict(
            stage,
            agent_dicts,
            [_collab_to_dict(e) for e in collab_events],
        )


def read_get_agent(agent_id: str) -> dict[str, Any] | None:
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
            .order_by(col(LLMCall.start_time))
        ).all()
        tool_calls = session.exec(
            select(ToolExecution)
            .where(ToolExecution.agent_execution_id == agent_id)
            .order_by(col(ToolExecution.start_time))
        ).all()

        return _agent_to_dict(
            agent,
            [_llm_to_dict(llm) for llm in llm_calls],
            [_tool_to_dict(t) for t in tool_calls],
        )


def read_get_llm_call(llm_call_id: str) -> dict[str, Any] | None:
    """Get single LLM call with full prompt/response."""
    with get_session() as session:
        llm = session.exec(select(LLMCall).where(LLMCall.id == llm_call_id)).first()
        if not llm:
            return None
        return _llm_to_dict(llm)


def read_get_tool_call(tool_call_id: str) -> dict[str, Any] | None:
    """Get single tool execution with full params/output."""
    with get_session() as session:
        tool = session.exec(
            select(ToolExecution).where(ToolExecution.id == tool_call_id)
        ).first()
        if not tool:
            return None
        return _tool_to_dict(tool)


def get_backend_stats() -> dict[str, Any]:
    """Get backend statistics and health information."""
    with get_session() as session:
        total_workflows = (
            session.exec(select(func.count(col(WorkflowExecution.id)))).first() or 0
        )
        total_stages = (
            session.exec(select(func.count(col(StageExecution.id)))).first() or 0
        )
        total_agents = (
            session.exec(select(func.count(col(AgentExecution.id)))).first() or 0
        )
        total_llm_calls = session.exec(select(func.count(col(LLMCall.id)))).first() or 0
        total_tool_calls = (
            session.exec(select(func.count(col(ToolExecution.id)))).first() or 0
        )

        oldest_wf = session.exec(
            select(WorkflowExecution.start_time)
            .order_by(col(WorkflowExecution.start_time))
            .limit(1)
        ).first()
        newest_wf = session.exec(
            select(WorkflowExecution.start_time)
            .order_by(col(WorkflowExecution.start_time).desc())
            .limit(1)
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


def build_llm_call_record(
    llm_call_id: str,
    agent_id: str,
    provider: str,
    model: str,
    data: Any,
    start_time: Any,
) -> LLMCall:
    """Build a LLMCall ORM record from tracking parameters."""
    return LLMCall(
        id=llm_call_id,
        agent_execution_id=agent_id,
        provider=provider,
        model=model,
        prompt=data.prompt,
        response=data.response,
        prompt_tokens=data.prompt_tokens,
        completion_tokens=data.completion_tokens,
        total_tokens=data.prompt_tokens + data.completion_tokens,
        latency_ms=data.latency_ms,
        estimated_cost_usd=data.estimated_cost_usd,
        temperature=data.temperature,
        max_tokens=data.max_tokens,
        status=data.status,
        error_message=data.error_message,
        start_time=ensure_utc(start_time),
        retry_count=0,
        failover_sequence=data.failover_sequence,
        failover_from_provider=data.failover_from_provider,
        prompt_template_hash=data.prompt_template_hash,
        prompt_template_source=data.prompt_template_source,
    )


def update_agent_llm_metrics(
    session: Any, agent_id: str, data: Any, total_tokens: int
) -> None:
    """Update AgentExecution LLM counters after inserting an LLM call."""
    statement = select(AgentExecution).where(AgentExecution.id == agent_id)
    agent = session.exec(statement).first()
    if agent:
        agent.num_llm_calls = (agent.num_llm_calls or 0) + 1
        agent.total_tokens = (agent.total_tokens or 0) + total_tokens
        agent.prompt_tokens = (agent.prompt_tokens or 0) + data.prompt_tokens
        agent.completion_tokens = (
            agent.completion_tokens or 0
        ) + data.completion_tokens
        agent.estimated_cost_usd = (
            agent.estimated_cost_usd or 0.0
        ) + data.estimated_cost_usd


def build_tool_execution_record(
    tool_execution_id: str,
    agent_id: str,
    tool_name: str,
    data: Any,
    start_time_utc: Any,
) -> ToolExecution:
    """Build a ToolExecution ORM record from tracking parameters."""
    end_time = start_time_utc + timedelta(seconds=data.duration_seconds)
    return ToolExecution(
        id=tool_execution_id,
        agent_execution_id=agent_id,
        tool_name=tool_name,
        input_params=data.input_params,
        output_data=data.output_data,
        start_time=start_time_utc,
        end_time=end_time,
        duration_seconds=data.duration_seconds,
        status=data.status,
        error_message=data.error_message,
        safety_checks_applied=data.safety_checks,
        approval_required=data.approval_required,
        retry_count=0,
    )


def _create_llm_call_models(llm_calls: list[Any]) -> list[LLMCall]:
    """Create LLMCall ORM objects from buffered calls."""
    return [
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
            retry_count=0,
            failover_sequence=getattr(call, "failover_sequence", None),
            failover_from_provider=getattr(call, "failover_from_provider", None),
            prompt_template_hash=getattr(call, "prompt_template_hash", None),
            prompt_template_source=getattr(call, "prompt_template_source", None),
        )
        for call in llm_calls
    ]


def _create_tool_execution_models(tool_calls: list[Any]) -> list[ToolExecution]:
    """Create ToolExecution ORM objects from buffered calls."""
    tool_models = []
    for call in tool_calls:
        start_time_utc = ensure_utc(call.start_time)
        if start_time_utc is None:
            raise ValueError("Tool call start_time cannot be None")
        tool_models.append(
            ToolExecution(
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
                retry_count=0,
            )
        )
    return tool_models


def _batch_update_agent_metrics(session: Any, agent_metrics: dict[str, Any]) -> None:
    """Update agent metrics in batch."""
    for agent_id, metrics in agent_metrics.items():
        statement = select(AgentExecution).where(AgentExecution.id == agent_id)
        agent = session.exec(statement).first()
        if agent:
            agent.num_llm_calls = (agent.num_llm_calls or 0) + metrics.num_llm_calls
            agent.num_tool_calls = (agent.num_tool_calls or 0) + metrics.num_tool_calls
            agent.total_tokens = (agent.total_tokens or 0) + metrics.total_tokens
            agent.prompt_tokens = (agent.prompt_tokens or 0) + metrics.prompt_tokens
            agent.completion_tokens = (
                agent.completion_tokens or 0
            ) + metrics.completion_tokens
            agent.estimated_cost_usd = (
                agent.estimated_cost_usd or 0
            ) + metrics.estimated_cost_usd


def flush_buffer(
    llm_calls: list[Any],
    tool_calls: list[Any],
    agent_metrics: dict[str, Any],
) -> None:
    """Flush buffered operations to database.

    Executes batch INSERT and UPDATE operations to reduce N+1 queries.
    """
    with get_session() as session:
        # Batch insert LLM calls
        if llm_calls:
            llm_models = _create_llm_call_models(llm_calls)
            session.add_all(llm_models)
            logger.debug(f"Batch inserted {len(llm_models)} LLM calls")

        # Batch insert tool calls
        if tool_calls:
            tool_models = _create_tool_execution_models(tool_calls)
            session.add_all(tool_models)
            logger.debug(f"Batch inserted {len(tool_models)} tool calls")

        # Commit inserts
        session.commit()

        # Batch update agent metrics
        if agent_metrics:
            _batch_update_agent_metrics(session, agent_metrics)
            session.commit()
            logger.debug(f"Batch updated {len(agent_metrics)} agent metrics")


# ---------------------------------------------------------------------------
# Mixin: delegates thin-wrapper methods to module-level helpers
# ---------------------------------------------------------------------------

# ============================================================================
# Error Fingerprinting
# ============================================================================

# Maximum recent IDs to store per fingerprint
_MAX_RECENT_IDS = 10


def _update_recent_ids(existing: Any, data: ErrorFingerprintData) -> None:
    """Append workflow/agent IDs to recent lists (capped at _MAX_RECENT_IDS)."""
    if data.workflow_id:
        wf_ids = list(existing.recent_workflow_ids or [])
        if data.workflow_id not in wf_ids:
            wf_ids.append(data.workflow_id)
        existing.recent_workflow_ids = wf_ids[-_MAX_RECENT_IDS:]
    if data.agent_name:
        ag_names = list(existing.recent_agent_names or [])
        if data.agent_name not in ag_names:
            ag_names.append(data.agent_name)
        existing.recent_agent_names = ag_names[-_MAX_RECENT_IDS:]


def record_error_fingerprint(data: ErrorFingerprintData) -> bool:
    """Upsert an error fingerprint record. Returns True if new."""
    from temper_ai.storage.database.datetime_utils import utcnow

    now = utcnow()
    is_new = False

    try:
        with get_session() as session:
            existing = session.get(ErrorFingerprint, data.fingerprint)
            if existing is None:
                is_new = True
                recent_wf = [data.workflow_id] if data.workflow_id else []
                recent_ag = [data.agent_name] if data.agent_name else []
                record = ErrorFingerprint(
                    fingerprint=data.fingerprint,
                    error_type=data.error_type,
                    error_code=data.error_code,
                    classification=data.classification,
                    normalized_message=data.normalized_message,
                    sample_message=data.sample_message,
                    occurrence_count=1,
                    first_seen=now,
                    last_seen=now,
                    recent_workflow_ids=recent_wf,
                    recent_agent_names=recent_ag,
                )
                session.add(record)
            else:
                existing.occurrence_count += 1
                existing.last_seen = now
                existing.sample_message = data.sample_message
                # Re-open if resolved
                if existing.resolved:
                    existing.resolved = False
                    existing.resolved_at = None
                # Update recent lists (capped)
                _update_recent_ids(existing, data)
                session.add(existing)
            session.commit()
    except (IntegrityError, SQLAlchemyError) as e:
        logger.warning("Failed to record error fingerprint %s: %s", data.fingerprint, e)

    return is_new


def get_top_errors(
    limit: int = 10,
    classification: str | None = None,
    since: datetime | None = None,
) -> list[dict[str, Any]]:
    """Get top errors by occurrence count."""
    try:
        with get_session() as session:
            stmt = select(ErrorFingerprint).order_by(
                col(ErrorFingerprint.occurrence_count).desc()
            )
            if classification:
                stmt = stmt.where(ErrorFingerprint.classification == classification)
            if since:
                stmt = stmt.where(ErrorFingerprint.last_seen >= since)
            stmt = stmt.limit(limit)

            results = session.exec(stmt).all()
            return [
                {
                    "fingerprint": r.fingerprint,
                    "error_type": r.error_type,
                    "error_code": r.error_code,
                    "classification": r.classification,
                    "normalized_message": r.normalized_message,
                    "sample_message": r.sample_message,
                    "occurrence_count": r.occurrence_count,
                    "first_seen": r.first_seen.isoformat() if r.first_seen else None,
                    "last_seen": r.last_seen.isoformat() if r.last_seen else None,
                    "resolved": r.resolved,
                }
                for r in results
            ]
    except SQLAlchemyError as e:
        logger.warning("Failed to query top errors: %s", e)
        return []


def fetch_run_events(
    workflow_id: str,
    limit: int = 100,
    offset: int = 0,
) -> list[dict]:
    """Query stage and agent execution events for a workflow run.

    Returns a chronological list of event dicts suitable for API responses.
    """
    events: list[dict] = []
    with get_session() as session:
        stages = session.exec(
            select(StageExecution)
            .where(StageExecution.workflow_execution_id == workflow_id)
            .order_by(StageExecution.start_time)  # type: ignore[arg-type]
        ).all()
        for s in stages:
            events.append(
                {
                    "id": s.id,
                    "event_type": "stage",
                    "stage": s.stage_name,
                    "agent": None,
                    ObservabilityFields.STATUS: s.status,
                    "timestamp": s.start_time.isoformat() if s.start_time else None,
                }
            )
        for s in stages:
            agents = session.exec(
                select(AgentExecution)
                .where(AgentExecution.stage_execution_id == s.id)
                .order_by(AgentExecution.start_time)  # type: ignore[arg-type]
            ).all()
            for a in agents:
                events.append(
                    {
                        "id": a.id,
                        "event_type": "agent",
                        "stage": s.stage_name,
                        "agent": a.agent_name,
                        ObservabilityFields.STATUS: a.status,
                        "timestamp": a.start_time.isoformat() if a.start_time else None,
                    }
                )
    events.sort(key=lambda e: e.get("timestamp") or "")
    return events[offset : offset + limit]


class SQLDelegatedMethodsMixin:
    """Mixin providing read, safety, collaboration, and aggregation methods.

    Reduces SQLObservabilityBackend method count by moving thin wrappers
    into this mixin. All methods delegate to module-level helper functions.
    """

    def get_workflow(self, workflow_id: str) -> dict[str, Any] | None:
        """Get workflow execution with full hierarchy."""
        return read_get_workflow(workflow_id)

    def list_workflows(
        self,
        limit: int = DEFAULT_LIST_LIMIT,
        offset: int = 0,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        """List workflow executions (summary only, no children)."""
        return read_list_workflows(limit, offset, status)

    def get_stage(self, stage_id: str) -> dict[str, Any] | None:
        """Get stage with agents and collaboration events."""
        return read_get_stage(stage_id)

    def get_agent(self, agent_id: str) -> dict[str, Any] | None:
        """Get agent with LLM calls and tool calls."""
        return read_get_agent(agent_id)

    def get_llm_call(self, llm_call_id: str) -> dict[str, Any] | None:
        """Get single LLM call with full prompt/response."""
        return read_get_llm_call(llm_call_id)

    def get_tool_call(self, tool_call_id: str) -> dict[str, Any] | None:
        """Get single tool execution with full params/output."""
        return read_get_tool_call(tool_call_id)

    def track_safety_violation(
        self,
        violation_severity: str,
        violation_message: str,
        policy_name: str,
        data: BackendSafetyViolationData | None = None,
        **kwargs: Any,
    ) -> None:
        """Track safety violation."""
        violation_data = SqlSafetyViolationParams(
            workflow_id=data.workflow_id if data else None,
            stage_id=data.stage_id if data else None,
            agent_id=data.agent_id if data else None,
            violation_severity=violation_severity,
            violation_message=violation_message,
            policy_name=policy_name,
            service_name=data.service_name if data else None,
            context=data.context if data else None,
            timestamp=data.timestamp if data else None,
        )
        track_safety_violation(violation_data)

    def track_collaboration_event(
        self,
        stage_id: str,
        event_type: str,
        agents_involved: list[str] | None = None,
        data: BackendCollaborationEventData | None = None,
        **kwargs: Any,
    ) -> str:
        """Track collaboration event."""
        agents = agents_involved if agents_involved is not None else []
        collab_data = SqlCollaborationEventParams(
            stage_id=stage_id,
            event_type=event_type,
            agents_involved=agents,
            event_data=data.event_data if data else None,
            round_number=data.round_number if data else None,
            resolution_strategy=data.resolution_strategy if data else None,
            outcome=data.outcome if data else None,
            confidence_score=data.confidence_score if data else None,
            extra_metadata=data.extra_metadata if data else None,
            timestamp=data.timestamp if data else None,
        )
        return track_collaboration_event(collab_data)

    def cleanup_old_records(
        self, retention_days: int, dry_run: bool = False
    ) -> dict[str, int]:
        """Clean up old records."""
        return cleanup_old_records(retention_days, dry_run)

    def get_stats(self) -> dict[str, Any]:
        """Return backend statistics."""
        return get_backend_stats()

    def aggregate_workflow_metrics(self, workflow_id: str) -> dict[str, Any]:
        """Aggregate workflow metrics."""
        return aggregate_workflow_metrics(workflow_id)

    def aggregate_stage_metrics(self, stage_id: str) -> dict[str, int]:
        """Aggregate stage metrics."""
        return aggregate_stage_metrics(stage_id)

    def record_error_fingerprint(self, data: ErrorFingerprintData) -> bool:
        """Record error fingerprint (SQL implementation)."""
        return record_error_fingerprint(data)

    def get_top_errors(
        self,
        limit: int = 10,
        classification: str | None = None,
        since: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Get top errors (SQL implementation)."""
        return get_top_errors(limit, classification, since)
