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
from src.observability.backend import (
    AgentOutputData,
    LLMCallData,
    ObservabilityBackend,
    ReadableBackendMixin,
    ToolCallData,
    WorkflowStartData,
)
from src.observability.backends._sql_backend_helpers import (
    _DEFAULT_VERSION,
    _STATUS_COMPLETED,
    _STATUS_FAILED,
    _STATUS_RUNNING,
    SQLDelegatedMethodsMixin,
)
from src.observability.backends._sql_backend_helpers import (
    flush_buffer as _flush_buffer,
)
from src.observability.constants import ObservabilityFields

logger = logging.getLogger(__name__)


class SQLObservabilityBackend(SQLDelegatedMethodsMixin, ObservabilityBackend, ReadableBackendMixin):
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
        start_time: datetime, data: Optional[WorkflowStartData] = None
    ) -> None:
        """Record workflow execution start."""
        d = data or WorkflowStartData()
        workflow_exec = WorkflowExecution(
            id=workflow_id, workflow_name=workflow_name,
            workflow_version=workflow_config.get("workflow", {}).get("version", _DEFAULT_VERSION),
            workflow_config_snapshot=workflow_config,
            trigger_type=d.trigger_type, trigger_data=d.trigger_data,
            status=_STATUS_RUNNING, start_time=ensure_utc(start_time),
            optimization_target=d.optimization_target, product_type=d.product_type,
            environment=d.environment, tags=d.tags, extra_metadata=d.extra_metadata,
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
            stage_version=stage_config.get("stage", {}).get("version", _DEFAULT_VERSION),
            stage_config_snapshot=stage_config,
            status=_STATUS_RUNNING, start_time=ensure_utc(start_time),
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
                        func.sum(case((AgentExecution.status == _STATUS_COMPLETED, 1), else_=0)).label('succeeded'),  # type: ignore[arg-type]
                        func.sum(case((AgentExecution.status == _STATUS_FAILED, 1), else_=0)).label('failed')  # type: ignore[arg-type]
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
            agent_version=agent_config.get("agent", {}).get("version", _DEFAULT_VERSION),
            agent_config_snapshot=agent_config,
            status=_STATUS_RUNNING, start_time=ensure_utc(start_time),
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
        metrics: Optional[AgentOutputData] = None
    ) -> None:
        """Set agent output data and metrics."""
        with get_session() as session:
            statement = select(AgentExecution).where(AgentExecution.id == agent_id)
            agent = session.exec(statement).first()
            if agent:
                agent.output_data = output_data
                if metrics:
                    agent.reasoning = metrics.reasoning
                    agent.confidence_score = metrics.confidence_score
                    if metrics.total_tokens is not None:
                        agent.total_tokens = metrics.total_tokens
                    if metrics.prompt_tokens is not None:
                        agent.prompt_tokens = metrics.prompt_tokens
                    if metrics.completion_tokens is not None:
                        agent.completion_tokens = metrics.completion_tokens
                    if metrics.estimated_cost_usd is not None:
                        agent.estimated_cost_usd = metrics.estimated_cost_usd
                    if metrics.num_llm_calls is not None:
                        agent.num_llm_calls = metrics.num_llm_calls
                    if metrics.num_tool_calls is not None:
                        agent.num_tool_calls = metrics.num_tool_calls
                session.commit()

    # ========== LLM Call Tracking ==========

    def track_llm_call(
        self, llm_call_id: str, agent_id: str, provider: str, model: str,
        start_time: datetime, data: LLMCallData
    ) -> None:
        """Record LLM call."""
        if self._buffer:
            self._buffer.buffer_llm_call(
                llm_call_id=llm_call_id, agent_id=agent_id, provider=provider,
                model=model, prompt=data.prompt, response=data.response,
                prompt_tokens=data.prompt_tokens, completion_tokens=data.completion_tokens,
                latency_ms=data.latency_ms, estimated_cost_usd=data.estimated_cost_usd,
                start_time=start_time, temperature=data.temperature, max_tokens=data.max_tokens,
                status=data.status, error_message=data.error_message
            )
            return

        llm_call = LLMCall(
            id=llm_call_id, agent_execution_id=agent_id,
            provider=provider, model=model, prompt=data.prompt, response=data.response,
            prompt_tokens=data.prompt_tokens, completion_tokens=data.completion_tokens,
            total_tokens=data.prompt_tokens + data.completion_tokens,
            latency_ms=data.latency_ms, estimated_cost_usd=data.estimated_cost_usd,
            temperature=data.temperature, max_tokens=data.max_tokens,
            status=data.status, error_message=data.error_message,
            start_time=ensure_utc(start_time), retry_count=0
        )
        with get_session() as session:
            session.add(llm_call)
            statement = select(AgentExecution).where(AgentExecution.id == agent_id)
            agent = session.exec(statement).first()
            if agent:
                agent.num_llm_calls = (agent.num_llm_calls or 0) + 1
                agent.total_tokens = (agent.total_tokens or 0) + (llm_call.total_tokens or 0)
                agent.prompt_tokens = (agent.prompt_tokens or 0) + data.prompt_tokens
                agent.completion_tokens = (agent.completion_tokens or 0) + data.completion_tokens
                agent.estimated_cost_usd = (agent.estimated_cost_usd or 0.0) + data.estimated_cost_usd
            session.commit()

    # ========== Tool Call Tracking ==========

    def track_tool_call(
        self, tool_execution_id: str, agent_id: str, tool_name: str,
        start_time: datetime, data: ToolCallData
    ) -> None:
        """Record tool execution."""
        if self._buffer:
            self._buffer.buffer_tool_call(
                tool_execution_id=tool_execution_id, agent_id=agent_id,
                tool_name=tool_name, input_params=data.input_params, output_data=data.output_data,
                start_time=start_time, duration_seconds=data.duration_seconds,
                status=data.status, error_message=data.error_message,
                safety_checks=data.safety_checks, approval_required=data.approval_required
            )
            return

        start_time_utc = ensure_utc(start_time)
        if start_time_utc is None:
            raise ValueError("Tool call start_time cannot be None")
        end_time = start_time_utc + timedelta(seconds=data.duration_seconds)
        tool_exec = ToolExecution(
            id=tool_execution_id, agent_execution_id=agent_id,
            tool_name=tool_name, input_params=data.input_params, output_data=data.output_data,
            start_time=start_time_utc, end_time=end_time,
            duration_seconds=data.duration_seconds, status=data.status, error_message=data.error_message,
            safety_checks_applied=data.safety_checks, approval_required=data.approval_required,
            retry_count=0
        )
        with get_session() as session:
            session.add(tool_exec)
            statement = select(AgentExecution).where(AgentExecution.id == agent_id)
            agent = session.exec(statement).first()
            if agent:
                agent.num_tool_calls = (agent.num_tool_calls or 0) + 1
            session.commit()

    # ========== Context Management ==========

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

    def get_run_events(
        self,
        workflow_id: str,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """Query stage and agent execution events for a workflow run.

        Returns a chronological list of event dicts suitable for API responses.
        """
        events: List[Dict[str, Any]] = []
        with get_session() as session:
            # Stage events
            stages = session.exec(
                select(StageExecution)
                .where(StageExecution.workflow_execution_id == workflow_id)
                .order_by(StageExecution.start_time)  # type: ignore[arg-type]
            ).all()
            for s in stages:
                events.append({
                    "id": s.id,
                    "event_type": "stage",
                    "stage": s.stage_name,
                    "agent": None,
                    ObservabilityFields.STATUS: s.status,
                    "timestamp": s.start_time.isoformat() if s.start_time else None,
                })

            # Agent events
            for s in stages:
                agents = session.exec(
                    select(AgentExecution)
                    .where(AgentExecution.stage_execution_id == s.id)
                    .order_by(AgentExecution.start_time)  # type: ignore[arg-type]
                ).all()
                for a in agents:
                    events.append({
                        "id": a.id,
                        "event_type": "agent",
                        "stage": s.stage_name,
                        "agent": a.agent_name,
                        ObservabilityFields.STATUS: a.status,
                        "timestamp": a.start_time.isoformat() if a.start_time else None,
                    })

        # Sort chronologically
        events.sort(key=lambda e: e.get("timestamp") or "")

        # Apply offset and limit
        return events[offset : offset + limit]

    @staticmethod
    def create_indexes() -> None:
        """Create database indexes for common query patterns."""
        logger.info("SQL backend indexes are defined in models.py")

    # track_safety_violation, track_collaboration_event, cleanup_old_records,
    # get_stats, aggregate_workflow_metrics, aggregate_stage_metrics
    # are provided by SQLDelegatedMethodsMixin
