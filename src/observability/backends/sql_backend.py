"""
SQL backend for observability system.

Implements observability backend using SQLModel/SQLAlchemy for relational databases.
Supports SQLite (dev/test) and PostgreSQL (production).
"""
from contextlib import contextmanager
from typing import Optional, Dict, Any, List, ContextManager, cast
from datetime import datetime, timezone, timedelta
import logging
import threading

from sqlmodel import select, func, delete
from sqlalchemy import case, Index

from src.observability.backend import ObservabilityBackend
from src.observability.database import get_session
from src.observability.datetime_utils import safe_duration_seconds, ensure_utc
from src.observability.models import (
    WorkflowExecution,
    StageExecution,
    AgentExecution,
    LLMCall,
    ToolExecution,
    CollaborationEvent,
)

logger = logging.getLogger(__name__)


class SQLObservabilityBackend(ObservabilityBackend):
    """
    SQL-based observability backend.

    Features:
    - Session reuse via session stack (reduces connection overhead)
    - Automatic metrics aggregation using SQL
    - Foreign key constraints for data integrity
    - Indexes on common query patterns
    - Retention policy support
    - Buffering enabled by default for batch operations (reduces N+1 queries)

    Database Session Optimization:
    - Reuses database session within each tracking context
    - Reduces connection overhead from 5-50ms per operation
    - Single session per workflow/stage/agent execution

    Performance Optimizations:
    - Indexed columns: workflow_name, stage_name, agent_name, status
    - Composite indexes for common joins
    - Aggregation queries use SQL instead of Python
    - Buffering: 200 queries → ~2 queries for 100 LLM calls (90% reduction)

    Buffering Mode (Default):
    - Buffer is created automatically with default settings (100 items, 5s timeout)
    - LLM and tool calls are batched to reduce N+1 queries
    - Reduces individual commits to periodic batch commits
    - Automatic flush based on size or time
    - To disable buffering, pass buffer=False explicitly
    """

    def __init__(self, buffer: Any = None) -> None:
        """
        Initialize SQL backend.

        Args:
            buffer: Optional ObservabilityBuffer for batching operations.
                   If None, a default buffer will be created to enable buffered mode.
                   Pass buffer=False to explicitly disable buffering.
        """
        # Thread-safe: each thread gets its own session stack and standalone session
        self._local = threading.local()

        # Create default buffer if none provided (unless explicitly disabled with buffer=False)
        if buffer is None:
            from src.observability.buffer import ObservabilityBuffer
            from src.observability.constants import DEFAULT_BUFFER_SIZE, DEFAULT_BUFFER_TIMEOUT_SECONDS
            self._buffer = ObservabilityBuffer(
                flush_size=DEFAULT_BUFFER_SIZE,
                flush_interval=DEFAULT_BUFFER_TIMEOUT_SECONDS,
                auto_flush=True
            )
        elif buffer is False:
            # Explicitly disabled buffering
            self._buffer = None
        else:
            # Custom buffer provided
            self._buffer = buffer

        # Set up flush callback if buffer enabled
        if self._buffer:
            self._buffer.set_flush_callback(self._flush_buffer)

    @property
    def _session_stack(self) -> List[Any]:
        """Per-thread session stack (backward-compatible property)."""
        stack = getattr(self._local, 'session_stack', None)
        if stack is None:
            stack = []
            self._local.session_stack = stack
        return stack

    @property
    def _standalone_session(self) -> Optional[Any]:
        """Per-thread standalone session (backward-compatible property)."""
        return getattr(self._local, 'standalone_session', None)

    @_standalone_session.setter
    def _standalone_session(self, value: Optional[Any]) -> None:
        self._local.standalone_session = value

    # ========== Workflow Tracking ==========

    def track_workflow_start(
        self,
        workflow_id: str,
        workflow_name: str,
        workflow_config: Dict[str, Any],
        start_time: datetime,
        trigger_type: Optional[str] = None,
        trigger_data: Optional[Dict[str, Any]] = None,
        optimization_target: Optional[str] = None,
        product_type: Optional[str] = None,
        environment: Optional[str] = None,
        tags: Optional[List[str]] = None,
        extra_metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """Record workflow execution start."""
        workflow_exec = WorkflowExecution(
            id=workflow_id,
            workflow_name=workflow_name,
            workflow_version=workflow_config.get("workflow", {}).get("version", "1.0"),
            workflow_config_snapshot=workflow_config,
            trigger_type=trigger_type,
            trigger_data=trigger_data,
            status="running",
            start_time=ensure_utc(start_time),
            optimization_target=optimization_target,
            product_type=product_type,
            environment=environment,
            tags=tags,
            extra_metadata=extra_metadata,
            total_llm_calls=0,
            total_tool_calls=0,
            total_tokens=0,
            total_cost_usd=0.0
        )

        session = self._get_or_create_session()
        session.add(workflow_exec)
        self._commit_and_cleanup(session)

    def track_workflow_end(
        self,
        workflow_id: str,
        end_time: datetime,
        status: str,
        error_message: Optional[str] = None,
        error_stack_trace: Optional[str] = None
    ) -> None:
        """Record workflow execution completion."""
        session = self._get_or_create_session()

        statement = select(WorkflowExecution).where(WorkflowExecution.id == workflow_id)
        wf = session.exec(statement).first()
        if wf:
            wf.status = status
            wf.end_time = ensure_utc(end_time)

            # Use safe duration calculation
            wf.duration_seconds = safe_duration_seconds(
                wf.start_time,
                wf.end_time,
                context=f"workflow {workflow_id}"
            )

            wf.error_message = error_message
            wf.error_stack_trace = error_stack_trace
            self._commit_and_cleanup(session)

    def update_workflow_metrics(
        self,
        workflow_id: str,
        total_llm_calls: int,
        total_tool_calls: int,
        total_tokens: int,
        total_cost_usd: float
    ) -> None:
        """Update workflow aggregated metrics."""
        session = self._get_or_create_session()

        statement = select(WorkflowExecution).where(WorkflowExecution.id == workflow_id)
        wf = session.exec(statement).first()
        if wf:
            wf.total_llm_calls = total_llm_calls
            wf.total_tool_calls = total_tool_calls
            wf.total_tokens = total_tokens
            wf.total_cost_usd = total_cost_usd
            self._commit_and_cleanup(session)

    # ========== Stage Tracking ==========

    def track_stage_start(
        self,
        stage_id: str,
        workflow_id: str,
        stage_name: str,
        stage_config: Dict[str, Any],
        start_time: datetime,
        input_data: Optional[Dict[str, Any]] = None
    ) -> None:
        """Record stage execution start."""
        stage_exec = StageExecution(
            id=stage_id,
            workflow_execution_id=workflow_id,
            stage_name=stage_name,
            stage_version=stage_config.get("stage", {}).get("version", "1.0"),
            stage_config_snapshot=stage_config,
            status="running",
            start_time=ensure_utc(start_time),
            input_data=input_data,
            num_agents_executed=0,
            num_agents_succeeded=0,
            num_agents_failed=0
        )

        session = self._get_or_create_session()
        session.add(stage_exec)
        self._commit_and_cleanup(session)

    def track_stage_end(
        self,
        stage_id: str,
        end_time: datetime,
        status: str,
        error_message: Optional[str] = None,
        num_agents_executed: int = 0,
        num_agents_succeeded: int = 0,
        num_agents_failed: int = 0
    ) -> None:
        """Record stage execution completion."""
        session = self._get_or_create_session()

        statement = select(StageExecution).where(StageExecution.id == stage_id)
        st = session.exec(statement).first()
        if st:
            st.status = status
            st.end_time = ensure_utc(end_time)

            # Use safe duration calculation
            st.duration_seconds = safe_duration_seconds(
                st.start_time,
                st.end_time,
                context=f"stage {stage_id}"
            )

            st.error_message = error_message

            # Use provided metrics or aggregate from child agents
            if num_agents_executed > 0:
                st.num_agents_executed = num_agents_executed
                st.num_agents_succeeded = num_agents_succeeded
                st.num_agents_failed = num_agents_failed
            else:
                # Aggregate from child agents using SQL
                metrics_statement = select(
                    func.count(AgentExecution.id).label('total'),  # type: ignore[arg-type]
                    func.sum(case((AgentExecution.status == 'completed', 1), else_=0)).label('succeeded'),  # type: ignore[arg-type]
                    func.sum(case((AgentExecution.status == 'failed', 1), else_=0)).label('failed')  # type: ignore[arg-type]
                ).where(AgentExecution.stage_execution_id == stage_id)

                metrics = session.exec(metrics_statement).first()
                if metrics:
                    st.num_agents_executed = int(metrics.total or 0)
                    st.num_agents_succeeded = int(metrics.succeeded or 0)
                    st.num_agents_failed = int(metrics.failed or 0)

            self._commit_and_cleanup(session)

    def set_stage_output(
        self,
        stage_id: str,
        output_data: Dict[str, Any]
    ) -> None:
        """Set stage output data."""
        session = self._get_or_create_session()

        statement = select(StageExecution).where(StageExecution.id == stage_id)
        stage = session.exec(statement).first()
        if stage:
            stage.output_data = output_data
            self._commit_and_cleanup(session)

    # ========== Agent Tracking ==========

    def track_agent_start(
        self,
        agent_id: str,
        stage_id: str,
        agent_name: str,
        agent_config: Dict[str, Any],
        start_time: datetime,
        input_data: Optional[Dict[str, Any]] = None
    ) -> None:
        """Record agent execution start."""
        agent_exec = AgentExecution(
            id=agent_id,
            stage_execution_id=stage_id,
            agent_name=agent_name,
            agent_version=agent_config.get("agent", {}).get("version", "1.0"),
            agent_config_snapshot=agent_config,
            status="running",
            start_time=ensure_utc(start_time),
            input_data=input_data,
            retry_count=0,
            num_llm_calls=0,
            num_tool_calls=0,
            total_tokens=0,
            prompt_tokens=0,
            completion_tokens=0,
            estimated_cost_usd=0.0
        )

        session = self._get_or_create_session()
        session.add(agent_exec)
        self._commit_and_cleanup(session)

    def track_agent_end(
        self,
        agent_id: str,
        end_time: datetime,
        status: str,
        error_message: Optional[str] = None
    ) -> None:
        """Record agent execution completion."""
        session = self._get_or_create_session()

        statement = select(AgentExecution).where(AgentExecution.id == agent_id)
        ag = session.exec(statement).first()
        if ag:
            ag.status = status
            ag.end_time = ensure_utc(end_time)

            # Use safe duration calculation
            ag.duration_seconds = safe_duration_seconds(
                ag.start_time,
                ag.end_time,
                context=f"agent {agent_id}"
            )

            ag.error_message = error_message
            self._commit_and_cleanup(session)

    def set_agent_output(
        self,
        agent_id: str,
        output_data: Dict[str, Any],
        reasoning: Optional[str] = None,
        confidence_score: Optional[float] = None,
        total_tokens: Optional[int] = None,
        prompt_tokens: Optional[int] = None,
        completion_tokens: Optional[int] = None,
        estimated_cost_usd: Optional[float] = None,
        num_llm_calls: Optional[int] = None,
        num_tool_calls: Optional[int] = None
    ) -> None:
        """Set agent output data and metrics."""
        session = self._get_or_create_session()

        statement = select(AgentExecution).where(AgentExecution.id == agent_id)
        agent = session.exec(statement).first()
        if agent:
            agent.output_data = output_data
            agent.reasoning = reasoning
            agent.confidence_score = confidence_score

            # Update metrics if provided
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

            self._commit_and_cleanup(session)

    # ========== LLM Call Tracking ==========

    def track_llm_call(
        self,
        llm_call_id: str,
        agent_id: str,
        provider: str,
        model: str,
        prompt: str,
        response: str,
        prompt_tokens: int,
        completion_tokens: int,
        latency_ms: int,
        estimated_cost_usd: float,
        start_time: datetime,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        status: str = "success",
        error_message: Optional[str] = None
    ) -> None:
        """Record LLM call."""
        # Use buffer if available (batched mode)
        if self._buffer:
            self._buffer.buffer_llm_call(
                llm_call_id=llm_call_id,
                agent_id=agent_id,
                provider=provider,
                model=model,
                prompt=prompt,
                response=response,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                latency_ms=latency_ms,
                estimated_cost_usd=estimated_cost_usd,
                start_time=start_time,
                temperature=temperature,
                max_tokens=max_tokens,
                status=status,
                error_message=error_message
            )
            return

        # Unbuffered mode (immediate commit)
        llm_call = LLMCall(
            id=llm_call_id,
            agent_execution_id=agent_id,
            provider=provider,
            model=model,
            prompt=prompt,
            response=response,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            latency_ms=latency_ms,
            estimated_cost_usd=estimated_cost_usd,
            temperature=temperature,
            max_tokens=max_tokens,
            status=status,
            error_message=error_message,
            start_time=ensure_utc(start_time),
            retry_count=0
        )

        session = self._get_or_create_session()
        session.add(llm_call)
        self._commit_and_cleanup(session)

        # Update parent agent metrics
        statement = select(AgentExecution).where(AgentExecution.id == agent_id)
        agent = session.exec(statement).first()
        if agent:
            agent.num_llm_calls = (agent.num_llm_calls or 0) + 1
            agent.total_tokens = (agent.total_tokens or 0) + (llm_call.total_tokens or 0)
            agent.prompt_tokens = (agent.prompt_tokens or 0) + prompt_tokens
            agent.completion_tokens = (agent.completion_tokens or 0) + completion_tokens
            agent.estimated_cost_usd = (agent.estimated_cost_usd or 0.0) + estimated_cost_usd
            self._commit_and_cleanup(session)

    # ========== Tool Call Tracking ==========

    def track_tool_call(
        self,
        tool_execution_id: str,
        agent_id: str,
        tool_name: str,
        input_params: Dict[str, Any],
        output_data: Dict[str, Any],
        start_time: datetime,
        duration_seconds: float,
        status: str = "success",
        error_message: Optional[str] = None,
        safety_checks: Optional[List[str]] = None,
        approval_required: bool = False
    ) -> None:
        """Record tool execution."""
        # Use buffer if available (batched mode)
        if self._buffer:
            self._buffer.buffer_tool_call(
                tool_execution_id=tool_execution_id,
                agent_id=agent_id,
                tool_name=tool_name,
                input_params=input_params,
                output_data=output_data,
                start_time=start_time,
                duration_seconds=duration_seconds,
                status=status,
                error_message=error_message,
                safety_checks=safety_checks,
                approval_required=approval_required
            )
            return

        # Unbuffered mode (immediate commit)
        start_time_utc = ensure_utc(start_time)
        end_time = start_time_utc  # Tool calls record start_time, end is calculated

        tool_exec = ToolExecution(
            id=tool_execution_id,
            agent_execution_id=agent_id,
            tool_name=tool_name,
            input_params=input_params,
            output_data=output_data,
            start_time=start_time_utc,
            end_time=end_time,
            duration_seconds=duration_seconds,
            status=status,
            error_message=error_message,
            safety_checks_applied=safety_checks,
            approval_required=approval_required,
            retry_count=0
        )

        session = self._get_or_create_session()
        session.add(tool_exec)
        self._commit_and_cleanup(session)

        # Update parent agent metrics
        statement = select(AgentExecution).where(AgentExecution.id == agent_id)
        agent = session.exec(statement).first()
        if agent:
            agent.num_tool_calls = (agent.num_tool_calls or 0) + 1
            self._commit_and_cleanup(session)

    # ========== Safety Tracking ==========

    def track_safety_violation(
        self,
        workflow_id: Optional[str],
        stage_id: Optional[str],
        agent_id: Optional[str],
        violation_severity: str,
        violation_message: str,
        policy_name: str,
        service_name: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        timestamp: Optional[datetime] = None
    ) -> None:
        """Track safety violation."""
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

        session = self._get_or_create_session()

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
                self._commit_and_cleanup(session)

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
                self._commit_and_cleanup(session)

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
                self._commit_and_cleanup(session)

    def track_collaboration_event(
        self,
        stage_id: str,
        event_type: str,
        agents_involved: List[str],
        event_data: Optional[Dict[str, Any]] = None,
        round_number: Optional[int] = None,
        resolution_strategy: Optional[str] = None,
        outcome: Optional[str] = None,
        confidence_score: Optional[float] = None,
        extra_metadata: Optional[Dict[str, Any]] = None,
        timestamp: Optional[datetime] = None
    ) -> str:
        """
        Track collaboration event to SQL database.

        Creates a CollaborationEvent record linked to the specified stage execution.
        Uses optimistic insert with foreign key constraint enforcement by the database.

        Args:
            stage_id: ID of the stage where collaboration occurred
            event_type: Type of event (vote, conflict, resolution, consensus,
                debate_round, synthesis, quality_gate_failure, adaptive_mode_switch)
            agents_involved: List of agent IDs participating
            event_data: Event-specific data (votes, positions, arguments)
            round_number: Round number for multi-round collaborations
            resolution_strategy: Strategy used for conflict resolution
            outcome: Final outcome of the collaboration event
            confidence_score: Confidence score of outcome (0.0-1.0)
            extra_metadata: Additional metadata for custom tracking
            timestamp: Event timestamp

        Returns:
            str: ID of created collaboration event record (format: "collab-{12-char-hex}")
        """
        import uuid
        from sqlalchemy.exc import IntegrityError, SQLAlchemyError

        # Generate unique event ID
        event_id = f"collab-{uuid.uuid4().hex[:12]}"

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
            extra_metadata=extra_metadata
        )

        session = self._get_or_create_session()

        try:
            session.add(event)
            self._commit_and_cleanup(session)
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
                'foreign key constraint failed' in error_msg or  # SQLite
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

            # Return event_id anyway - tracking failures shouldn't break workflows
            return event_id

        except SQLAlchemyError as e:
            session.rollback()
            logger.error(
                f"Database error tracking collaboration event: {e}",
                exc_info=True,
                extra={"event_id": event_id, "event_type": event_type, "stage_id": stage_id}
            )
            # Return event_id anyway - tracking failures shouldn't break workflows
            return event_id

    # ========== Context Management ==========

    @contextmanager
    def get_session_context(self) -> Any:
        """
        Get database session context manager.

        Implements session reuse pattern - if a session is already active
        (from parent context), reuses it. Otherwise creates a new session.
        """
        if self._session_stack:
            # Reuse parent session
            yield self._session_stack[-1]
        else:
            # Create new session
            with get_session() as session:
                self._session_stack.append(session)
                try:
                    yield session
                finally:
                    self._session_stack.pop()

    def _get_or_create_session(self) -> Any:
        """
        Get current session or create standalone session.

        IMPORTANT: If this creates a standalone session, caller must ensure
        _cleanup_standalone_session() is called after committing.
        """
        if self._session_stack:
            return self._session_stack[-1]
        else:
            # Create standalone session for operations outside context manager
            # Note: This session must be cleaned up via _cleanup_standalone_session()
            if self._standalone_session is None:
                self._standalone_session = get_session().__enter__()
            return self._standalone_session

    def _cleanup_standalone_session(self) -> None:
        """
        Clean up standalone session if one exists.

        Call this after committing in operations that don't use context manager.
        """
        if self._standalone_session is not None:
            try:
                self._standalone_session.__exit__(None, None, None)
            except Exception:
                # Best effort cleanup - don't propagate exceptions
                pass
            finally:
                self._standalone_session = None

    def _commit_and_cleanup(self, session: Any) -> None:
        """
        Commit session and clean up standalone session if needed.

        Use this instead of session.commit() in tracking methods.
        """
        session.commit()
        # Only cleanup if we're not in a managed context
        if not self._session_stack:
            self._cleanup_standalone_session()

    # ========== Maintenance Operations ==========

    def cleanup_old_records(
        self,
        retention_days: int,
        dry_run: bool = False
    ) -> Dict[str, int]:
        """
        Clean up old observability records based on retention policy.

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
                # Delete cascades to stages, agents, llm_calls, tool_executions due to FK constraints
                delete_statement = delete(WorkflowExecution).where(
                    WorkflowExecution.start_time < cutoff_date  # type: ignore[arg-type]
                )
                session.exec(delete_statement)
                self._commit_and_cleanup(session)
                logger.info(
                    f"Deleted {counts['workflows']} workflows older than {retention_days} days"
                )

        return counts

    def get_stats(self) -> Dict[str, Any]:
        """Get backend statistics and health information."""
        with get_session() as session:
            # Count records
            total_workflows = session.exec(select(func.count(WorkflowExecution.id))).first() or 0  # type: ignore[arg-type]
            total_stages = session.exec(select(func.count(StageExecution.id))).first() or 0  # type: ignore[arg-type]
            total_agents = session.exec(select(func.count(AgentExecution.id))).first() or 0  # type: ignore[arg-type]
            total_llm_calls = session.exec(select(func.count(LLMCall.id))).first() or 0  # type: ignore[arg-type]
            total_tool_calls = session.exec(select(func.count(ToolExecution.id))).first() or 0  # type: ignore[arg-type]

            # Get date range
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

    # ========== Buffering Support ==========

    def _flush_buffer(self, llm_calls: List[Any], tool_calls: List[Any], agent_metrics: Dict[str, Any]) -> None:
        """
        Flush buffered operations to database.

        Executes batch INSERT and UPDATE operations to reduce N+1 queries.

        Args:
            llm_calls: List of BufferedLLMCall objects
            tool_calls: List of BufferedToolCall objects
            agent_metrics: Dict of agent_id -> AgentMetricUpdate

        Performance:
            - Batch INSERT for all LLM calls (1 query instead of N)
            - Batch INSERT for all tool calls (1 query instead of N)
            - Batch UPDATE for agent metrics (1 query per agent instead of N)
            - Total: ~2-4 queries instead of 200+ queries for 100 LLM calls
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
                        end_time=ensure_utc(call.start_time),  # Tool calls use start_time
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
            self._commit_and_cleanup(session)

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
                self._commit_and_cleanup(session)
                logger.debug(f"Batch updated {len(agent_metrics)} agent metrics")

    # ========== Performance Optimizations ==========

    @staticmethod
    def create_indexes() -> None:
        """
        Create database indexes for common query patterns.

        Call this after database initialization to improve query performance.

        Indexes:
        - workflow_executions: (workflow_name, start_time)
        - stage_executions: (stage_name, start_time), (workflow_execution_id, status)
        - agent_executions: (agent_name, start_time), (stage_execution_id, status)
        - llm_calls: (agent_execution_id, start_time), (provider, model)
        - tool_executions: (agent_execution_id, start_time), (tool_name, status)
        """
        # Note: These are defined declaratively in models.py via Field(index=True)
        # This method documents the index strategy and can add composite indexes
        logger.info("SQL backend indexes are defined in models.py")

        # Future: Add composite indexes here if needed
        # Example:
        # Index('idx_workflow_name_time', WorkflowExecution.workflow_name, WorkflowExecution.start_time)
