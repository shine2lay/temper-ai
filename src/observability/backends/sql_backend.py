"""
SQL backend for observability system.

Implements observability backend using SQLModel/SQLAlchemy for relational databases.
Supports SQLite (dev/test) and PostgreSQL (production).

Session lifecycle: Each tracking method opens a per-operation session via
``get_session()`` (from ``src.observability.database``). This avoids long-lived
session state and the subtle bugs that come with session-stack / standalone-session
patterns (C-02).
"""
import logging
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlmodel import select

from src.database import get_session
from src.database.datetime_utils import ensure_utc, safe_duration_seconds
from src.database.models import (
    AgentExecution,
    LLMCall,
    StageExecution,
    ToolExecution,
    WorkflowExecution,
)
from src.observability.backend import DEFAULT_LIST_LIMIT, ObservabilityBackend
from src.observability.backends._sql_backend_helpers import (
    aggregate_stage_metrics as _aggregate_stage_metrics,
)
from src.observability.backends._sql_backend_helpers import (
    aggregate_workflow_metrics as _aggregate_workflow_metrics,
)
from src.observability.backends._sql_backend_helpers import (
    cleanup_old_records as _cleanup_old_records,
)
from src.observability.backends._sql_backend_helpers import (
    flush_buffer as _flush_buffer,
)
from src.observability.backends._sql_backend_helpers import (
    get_backend_stats as _get_backend_stats,
)
from src.observability.backends._sql_backend_helpers import (
    read_get_agent as _read_get_agent,
)
from src.observability.backends._sql_backend_helpers import (
    read_get_llm_call as _read_get_llm_call,
)
from src.observability.backends._sql_backend_helpers import (
    read_get_stage as _read_get_stage,
)
from src.observability.backends._sql_backend_helpers import (
    read_get_tool_call as _read_get_tool_call,
)
from src.observability.backends._sql_backend_helpers import (
    read_get_workflow as _read_get_workflow,
)
from src.observability.backends._sql_backend_helpers import (
    read_list_workflows as _read_list_workflows,
)
from src.observability.backends._sql_backend_helpers import (
    track_collaboration_event as _track_collaboration_event,
)
from src.observability.backends._sql_backend_helpers import (
    track_safety_violation as _track_safety_violation,
)

logger = logging.getLogger(__name__)


class SQLObservabilityBackend(ObservabilityBackend):
    """SQL-based observability backend with per-operation sessions and buffering."""

    def __init__(self, buffer: Any = None) -> None:
        """Initialize SQL backend."""
        from src.observability.buffer import ObservabilityBuffer

        self._buffer: Optional[ObservabilityBuffer]
        if buffer is None:
            from src.observability.constants import (
                DEFAULT_BUFFER_SIZE,
                DEFAULT_BUFFER_TIMEOUT_SECONDS,
            )
            self._buffer = ObservabilityBuffer(
                flush_size=DEFAULT_BUFFER_SIZE,
                flush_interval=DEFAULT_BUFFER_TIMEOUT_SECONDS,
                auto_flush=True
            )
        elif buffer is False:
            self._buffer = None
        else:
            self._buffer = buffer

        if self._buffer:
            self._buffer.set_flush_callback(
                lambda llm, tool, metrics: _flush_buffer(llm, tool, metrics)
            )

    # ========== Workflow Tracking ==========

    def track_workflow_start(
        self, workflow_id: str, workflow_name: str, workflow_config: Dict[str, Any],
        start_time: datetime, trigger_type: Optional[str] = None,
        trigger_data: Optional[Dict[str, Any]] = None,
        optimization_target: Optional[str] = None, product_type: Optional[str] = None,
        environment: Optional[str] = None, tags: Optional[List[str]] = None,
        extra_metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """Record workflow execution start."""
        workflow_exec = WorkflowExecution(
            id=workflow_id, workflow_name=workflow_name,
            workflow_version=workflow_config.get("workflow", {}).get("version", "1.0"),
            workflow_config_snapshot=workflow_config,
            trigger_type=trigger_type, trigger_data=trigger_data,
            status="running", start_time=ensure_utc(start_time),
            optimization_target=optimization_target, product_type=product_type,
            environment=environment, tags=tags, extra_metadata=extra_metadata,
            total_llm_calls=0, total_tool_calls=0, total_tokens=0, total_cost_usd=0.0
        )
        with get_session() as session:
            session.add(workflow_exec)
            session.commit()

    def track_workflow_end(
        self, workflow_id: str, end_time: datetime, status: str,
        error_message: Optional[str] = None, error_stack_trace: Optional[str] = None
    ) -> None:
        """Record workflow execution completion."""
        with get_session() as session:
            statement = select(WorkflowExecution).where(WorkflowExecution.id == workflow_id)
            wf = session.exec(statement).first()
            if wf:
                wf.status = status
                end_time_utc = ensure_utc(end_time)
                if end_time_utc is None:
                    raise ValueError("Workflow end_time cannot be None")
                wf.end_time = end_time_utc
                wf.duration_seconds = safe_duration_seconds(wf.start_time, end_time_utc, context=f"workflow {workflow_id}")
                wf.error_message = error_message
                wf.error_stack_trace = error_stack_trace
                session.commit()

    def update_workflow_metrics(
        self, workflow_id: str, total_llm_calls: int, total_tool_calls: int,
        total_tokens: int, total_cost_usd: float
    ) -> None:
        """Update workflow aggregated metrics."""
        with get_session() as session:
            statement = select(WorkflowExecution).where(WorkflowExecution.id == workflow_id)
            wf = session.exec(statement).first()
            if wf:
                wf.total_llm_calls = total_llm_calls
                wf.total_tool_calls = total_tool_calls
                wf.total_tokens = total_tokens
                wf.total_cost_usd = total_cost_usd
                session.commit()

    # ========== Stage Tracking ==========

    def track_stage_start(
        self, stage_id: str, workflow_id: str, stage_name: str,
        stage_config: Dict[str, Any], start_time: datetime,
        input_data: Optional[Dict[str, Any]] = None
    ) -> None:
        """Record stage execution start."""
        stage_exec = StageExecution(
            id=stage_id, workflow_execution_id=workflow_id,
            stage_name=stage_name,
            stage_version=stage_config.get("stage", {}).get("version", "1.0"),
            stage_config_snapshot=stage_config,
            status="running", start_time=ensure_utc(start_time),
            input_data=input_data,
            num_agents_executed=0, num_agents_succeeded=0, num_agents_failed=0
        )
        with get_session() as session:
            session.add(stage_exec)
            session.commit()

    def track_stage_end(
        self, stage_id: str, end_time: datetime, status: str,
        error_message: Optional[str] = None, num_agents_executed: int = 0,
        num_agents_succeeded: int = 0, num_agents_failed: int = 0
    ) -> None:
        """Record stage execution completion."""
        from sqlalchemy import case
        from sqlmodel import func
        with get_session() as session:
            statement = select(StageExecution).where(StageExecution.id == stage_id)
            st = session.exec(statement).first()
            if st:
                st.status = status
                end_time_utc = ensure_utc(end_time)
                if end_time_utc is None:
                    raise ValueError("Stage end_time cannot be None")
                st.end_time = end_time_utc
                st.duration_seconds = safe_duration_seconds(st.start_time, end_time_utc, context=f"stage {stage_id}")
                st.error_message = error_message

                if num_agents_executed > 0:
                    st.num_agents_executed = num_agents_executed
                    st.num_agents_succeeded = num_agents_succeeded
                    st.num_agents_failed = num_agents_failed
                else:
                    metrics_statement = select(
                        func.count(AgentExecution.id).label('total'),  # type: ignore[arg-type]
                        func.sum(case((AgentExecution.status == 'completed', 1), else_=0)).label('succeeded'),  # type: ignore[arg-type]
                        func.sum(case((AgentExecution.status == 'failed', 1), else_=0)).label('failed')  # type: ignore[arg-type]
                    ).where(AgentExecution.stage_execution_id == stage_id)
                    result = session.exec(metrics_statement).first()
                    if result:
                        st.num_agents_executed = int(result[0] or 0)
                        st.num_agents_succeeded = int(result[1] or 0)
                        st.num_agents_failed = int(result[2] or 0)

                session.commit()

    def set_stage_output(self, stage_id: str, output_data: Dict[str, Any]) -> None:
        """Set stage output data."""
        with get_session() as session:
            statement = select(StageExecution).where(StageExecution.id == stage_id)
            stage = session.exec(statement).first()
            if stage:
                stage.output_data = output_data
                session.commit()

    # ========== Agent Tracking ==========

    def track_agent_start(
        self, agent_id: str, stage_id: str, agent_name: str,
        agent_config: Dict[str, Any], start_time: datetime,
        input_data: Optional[Dict[str, Any]] = None
    ) -> None:
        """Record agent execution start."""
        agent_exec = AgentExecution(
            id=agent_id, stage_execution_id=stage_id,
            agent_name=agent_name,
            agent_version=agent_config.get("agent", {}).get("version", "1.0"),
            agent_config_snapshot=agent_config,
            status="running", start_time=ensure_utc(start_time),
            input_data=input_data,
            retry_count=0, num_llm_calls=0, num_tool_calls=0,
            total_tokens=0, prompt_tokens=0, completion_tokens=0, estimated_cost_usd=0.0
        )
        with get_session() as session:
            session.add(agent_exec)
            session.commit()

    def track_agent_end(
        self, agent_id: str, end_time: datetime, status: str,
        error_message: Optional[str] = None
    ) -> None:
        """Record agent execution completion."""
        with get_session() as session:
            statement = select(AgentExecution).where(AgentExecution.id == agent_id)
            ag = session.exec(statement).first()
            if ag:
                ag.status = status
                end_time_utc = ensure_utc(end_time)
                if end_time_utc is None:
                    raise ValueError("Agent end_time cannot be None")
                ag.end_time = end_time_utc
                ag.duration_seconds = safe_duration_seconds(ag.start_time, end_time_utc, context=f"agent {agent_id}")
                ag.error_message = error_message
                session.commit()

    def set_agent_output(
        self, agent_id: str, output_data: Dict[str, Any],
        reasoning: Optional[str] = None, confidence_score: Optional[float] = None,
        total_tokens: Optional[int] = None, prompt_tokens: Optional[int] = None,
        completion_tokens: Optional[int] = None, estimated_cost_usd: Optional[float] = None,
        num_llm_calls: Optional[int] = None, num_tool_calls: Optional[int] = None
    ) -> None:
        """Set agent output data and metrics."""
        with get_session() as session:
            statement = select(AgentExecution).where(AgentExecution.id == agent_id)
            agent = session.exec(statement).first()
            if agent:
                agent.output_data = output_data
                agent.reasoning = reasoning
                agent.confidence_score = confidence_score
                if total_tokens is not None:
                    agent.total_tokens = total_tokens
                if prompt_tokens is not None:
                    agent.prompt_tokens = prompt_tokens
                if completion_tokens is not None:
                    agent.completion_tokens = completion_tokens
                if estimated_cost_usd is not None:
                    agent.estimated_cost_usd = estimated_cost_usd
                if num_llm_calls is not None:
                    agent.num_llm_calls = num_llm_calls
                if num_tool_calls is not None:
                    agent.num_tool_calls = num_tool_calls
                session.commit()

    # ========== LLM Call Tracking ==========

    def track_llm_call(
        self, llm_call_id: str, agent_id: str, provider: str, model: str,
        prompt: str, response: str, prompt_tokens: int, completion_tokens: int,
        latency_ms: int, estimated_cost_usd: float, start_time: datetime,
        temperature: Optional[float] = None, max_tokens: Optional[int] = None,
        status: str = "success", error_message: Optional[str] = None
    ) -> None:
        """Record LLM call."""
        if self._buffer:
            self._buffer.buffer_llm_call(
                llm_call_id=llm_call_id, agent_id=agent_id, provider=provider,
                model=model, prompt=prompt, response=response,
                prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
                latency_ms=latency_ms, estimated_cost_usd=estimated_cost_usd,
                start_time=start_time, temperature=temperature, max_tokens=max_tokens,
                status=status, error_message=error_message
            )
            return

        llm_call = LLMCall(
            id=llm_call_id, agent_execution_id=agent_id,
            provider=provider, model=model, prompt=prompt, response=response,
            prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            latency_ms=latency_ms, estimated_cost_usd=estimated_cost_usd,
            temperature=temperature, max_tokens=max_tokens,
            status=status, error_message=error_message,
            start_time=ensure_utc(start_time), retry_count=0
        )
        with get_session() as session:
            session.add(llm_call)
            statement = select(AgentExecution).where(AgentExecution.id == agent_id)
            agent = session.exec(statement).first()
            if agent:
                agent.num_llm_calls = (agent.num_llm_calls or 0) + 1
                agent.total_tokens = (agent.total_tokens or 0) + (llm_call.total_tokens or 0)
                agent.prompt_tokens = (agent.prompt_tokens or 0) + prompt_tokens
                agent.completion_tokens = (agent.completion_tokens or 0) + completion_tokens
                agent.estimated_cost_usd = (agent.estimated_cost_usd or 0.0) + estimated_cost_usd
            session.commit()

    # ========== Tool Call Tracking ==========

    def track_tool_call(
        self, tool_execution_id: str, agent_id: str, tool_name: str,
        input_params: Dict[str, Any], output_data: Dict[str, Any],
        start_time: datetime, duration_seconds: float,
        status: str = "success", error_message: Optional[str] = None,
        safety_checks: Optional[List[str]] = None, approval_required: bool = False
    ) -> None:
        """Record tool execution."""
        if self._buffer:
            self._buffer.buffer_tool_call(
                tool_execution_id=tool_execution_id, agent_id=agent_id,
                tool_name=tool_name, input_params=input_params, output_data=output_data,
                start_time=start_time, duration_seconds=duration_seconds,
                status=status, error_message=error_message,
                safety_checks=safety_checks, approval_required=approval_required
            )
            return

        start_time_utc = ensure_utc(start_time)
        if start_time_utc is None:
            raise ValueError("Tool call start_time cannot be None")
        end_time = start_time_utc + timedelta(seconds=duration_seconds)
        tool_exec = ToolExecution(
            id=tool_execution_id, agent_execution_id=agent_id,
            tool_name=tool_name, input_params=input_params, output_data=output_data,
            start_time=start_time_utc, end_time=end_time,
            duration_seconds=duration_seconds, status=status, error_message=error_message,
            safety_checks_applied=safety_checks, approval_required=approval_required,
            retry_count=0
        )
        with get_session() as session:
            session.add(tool_exec)
            statement = select(AgentExecution).where(AgentExecution.id == agent_id)
            agent = session.exec(statement).first()
            if agent:
                agent.num_tool_calls = (agent.num_tool_calls or 0) + 1
            session.commit()

    # ========== Read Operations ==========

    def get_workflow(self, workflow_id: str) -> Optional[Dict[str, Any]]:
        """Get workflow execution with full hierarchy."""
        return _read_get_workflow(workflow_id)

    def list_workflows(self, limit: int = DEFAULT_LIST_LIMIT, offset: int = 0, status: Optional[str] = None) -> List[Dict[str, Any]]:
        """List workflow executions (summary only, no children)."""
        return _read_list_workflows(limit, offset, status)

    def get_stage(self, stage_id: str) -> Optional[Dict[str, Any]]:
        """Get stage with agents and collaboration events."""
        return _read_get_stage(stage_id)

    def get_agent(self, agent_id: str) -> Optional[Dict[str, Any]]:
        """Get agent with LLM calls and tool calls."""
        return _read_get_agent(agent_id)

    def get_llm_call(self, llm_call_id: str) -> Optional[Dict[str, Any]]:
        """Get single LLM call with full prompt/response."""
        return _read_get_llm_call(llm_call_id)

    def get_tool_call(self, tool_call_id: str) -> Optional[Dict[str, Any]]:
        """Get single tool execution with full params/output."""
        return _read_get_tool_call(tool_call_id)

    # ========== Delegated Methods ==========

    @contextmanager
    def get_session_context(self) -> Any:
        """Yield a database session context."""
        with get_session() as session:
            yield session

    def get_agent_execution(self, agent_id: str) -> Optional[AgentExecution]:
        """Fetch a single agent execution record by ID."""
        with get_session() as session:
            statement = select(AgentExecution).where(AgentExecution.id == agent_id)
            agent = session.exec(statement).first()
            if agent:
                session.expunge(agent)
            return agent

    def get_stats(self) -> Dict[str, Any]:
        """Return backend statistics."""
        return _get_backend_stats()

    @staticmethod
    def create_indexes() -> None:
        """Create database indexes for common query patterns."""
        logger.info("SQL backend indexes are defined in models.py")

    # ========== Abstract Method Implementations ==========

    def track_safety_violation(
        self, workflow_id: Optional[str], stage_id: Optional[str], agent_id: Optional[str],
        violation_severity: str, violation_message: str, policy_name: str,
        service_name: Optional[str] = None, context: Optional[Dict[str, Any]] = None,
        timestamp: Optional[datetime] = None
    ) -> None:
        """Track safety violation."""
        _track_safety_violation(
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
        return _track_collaboration_event(
            stage_id, event_type, agents_involved, event_data,
            round_number, resolution_strategy, outcome, confidence_score,
            extra_metadata, timestamp
        )

    def cleanup_old_records(self, retention_days: int, dry_run: bool = False) -> Dict[str, int]:
        """Clean up old records."""
        return _cleanup_old_records(retention_days, dry_run)

    def aggregate_workflow_metrics(self, workflow_id: str) -> Dict[str, Any]:
        """Aggregate workflow metrics."""
        return _aggregate_workflow_metrics(workflow_id)

    def aggregate_stage_metrics(self, stage_id: str) -> Dict[str, int]:
        """Aggregate stage metrics."""
        return _aggregate_stage_metrics(stage_id)


# Note: Methods track_safety_violation, track_collaboration_event, cleanup_old_records,
# aggregate_workflow_metrics, and aggregate_stage_metrics are now defined in the class body
# to satisfy ABC requirements. Previously they were attached dynamically which caused
# instantiation errors in tests.
