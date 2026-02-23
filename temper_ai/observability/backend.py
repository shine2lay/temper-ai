"""
Abstract backend interface for observability system.

Defines the contract that all observability backends must implement,
enabling pluggable storage backends (SQL, Prometheus, S3, etc.).
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import (
    TYPE_CHECKING,
    Any,
    ContextManager,
    Literal,
)

DEFAULT_LIST_LIMIT = 50


# ========== Parameter Bundle Dataclasses ==========


@dataclass
class WorkflowStartData:
    """Bundled optional parameters for track_workflow_start."""

    trigger_type: str | None = None
    trigger_data: dict[str, Any] | None = None
    optimization_target: str | None = None
    product_type: str | None = None
    environment: str | None = None
    tags: list[str] | None = None
    extra_metadata: dict[str, Any] | None = None
    cost_attribution_tags: dict[str, str] | None = None


@dataclass
class AgentOutputData:
    """Bundled optional metrics for set_agent_output."""

    reasoning: str | None = None
    confidence_score: float | None = None
    total_tokens: int | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    estimated_cost_usd: float | None = None
    num_llm_calls: int | None = None
    num_tool_calls: int | None = None


@dataclass
class LLMCallData:
    """Bundled LLM call parameters."""

    prompt: str
    response: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: int
    estimated_cost_usd: float
    temperature: float | None = None
    max_tokens: int | None = None
    status: Literal["success", "failed"] = "success"
    error_message: str | None = None
    failover_sequence: list[str] | None = None
    failover_from_provider: str | None = None
    prompt_template_hash: str | None = None
    prompt_template_source: str | None = None


@dataclass
class ToolCallData:
    """Bundled tool call parameters."""

    input_params: dict[str, Any]
    output_data: dict[str, Any]
    duration_seconds: float
    status: Literal["success", "failed"] = "success"
    error_message: str | None = None
    safety_checks: list[str] | None = None
    approval_required: bool = False


@dataclass
class SafetyViolationData:
    """Bundled safety violation parameters."""

    workflow_id: str | None = None
    stage_id: str | None = None
    agent_id: str | None = None
    service_name: str | None = None
    context: dict[str, Any] | None = None
    timestamp: datetime | None = None


@dataclass
class CollaborationEventData:
    """Bundled collaboration event parameters."""

    event_data: dict[str, Any] | None = None
    round_number: int | None = None
    resolution_strategy: str | None = None
    outcome: str | None = None
    confidence_score: float | None = None
    extra_metadata: dict[str, Any] | None = None
    timestamp: datetime | None = None


@dataclass(frozen=True)
class ErrorFingerprintData:
    """Data for recording an error fingerprint."""

    fingerprint: str
    error_type: str
    error_code: str
    classification: str
    normalized_message: str
    sample_message: str
    workflow_id: str | None = None
    agent_name: str | None = None


class ReadableBackendMixin:
    """Mixin providing default read operations for observability data.

    Default implementations return empty results. Override in backends
    that support persistent storage (e.g., SQL).
    """

    def get_workflow(self, workflow_id: str) -> dict[str, Any] | None:
        """Get workflow execution data by ID, or None if not found."""
        return None

    def list_workflows(
        self,
        limit: int = DEFAULT_LIST_LIMIT,
        offset: int = 0,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        """List workflow executions with optional filtering."""
        return []

    def get_stage(self, stage_id: str) -> dict[str, Any] | None:
        """Get stage execution data by ID, or None if not found."""
        return None

    def get_agent(self, agent_id: str) -> dict[str, Any] | None:
        """Get agent execution data by ID, or None if not found."""
        return None

    def get_llm_call(self, llm_call_id: str) -> dict[str, Any] | None:
        """Get LLM call data by ID, or None if not found."""
        return None

    def get_tool_call(self, tool_call_id: str) -> dict[str, Any] | None:
        """Get tool call data by ID, or None if not found."""
        return None


class _AsyncBackendDefaults:
    """Mixin providing default async implementations that delegate to sync.

    All async methods call their sync counterparts via asyncio.to_thread.
    The sync methods (e.g. self.track_workflow_start) are resolved at
    runtime through MRO from ObservabilityBackend.
    """

    if TYPE_CHECKING:
        # Sync methods resolved at runtime from ObservabilityBackend via MRO
        track_workflow_start: Callable[..., None]
        track_workflow_end: Callable[..., None]
        update_workflow_metrics: Callable[..., None]
        track_stage_start: Callable[..., None]
        track_stage_end: Callable[..., None]
        set_stage_output: Callable[..., None]
        track_agent_start: Callable[..., None]
        track_agent_end: Callable[..., None]
        set_agent_output: Callable[..., None]
        track_llm_call: Callable[..., None]
        track_tool_call: Callable[..., None]
        track_safety_violation: Callable[..., None]
        track_collaboration_event: Callable[..., str]
        get_session_context: Callable[..., ContextManager[Any]]

    async def atrack_workflow_start(
        self,
        workflow_id: str,
        workflow_name: str,
        workflow_config: dict[str, Any],
        start_time: datetime,
        data: WorkflowStartData | None = None,
    ) -> None:
        """Async version of track_workflow_start."""
        await asyncio.to_thread(
            self.track_workflow_start,
            workflow_id,
            workflow_name,
            workflow_config,
            start_time,
            data,
        )

    async def atrack_workflow_end(
        self,
        workflow_id: str,
        end_time: datetime,
        status: str,
        error_message: str | None = None,
        error_stack_trace: str | None = None,
    ) -> None:
        """Async version of track_workflow_end."""
        await asyncio.to_thread(
            self.track_workflow_end,
            workflow_id,
            end_time,
            status,
            error_message,
            error_stack_trace,
        )

    async def aupdate_workflow_metrics(
        self,
        workflow_id: str,
        total_llm_calls: int,
        total_tool_calls: int,
        total_tokens: int,
        total_cost_usd: float,
    ) -> None:
        """Async version of update_workflow_metrics."""
        await asyncio.to_thread(
            self.update_workflow_metrics,
            workflow_id,
            total_llm_calls,
            total_tool_calls,
            total_tokens,
            total_cost_usd,
        )

    async def atrack_stage_start(
        self,
        stage_id: str,
        workflow_id: str,
        stage_name: str,
        stage_config: dict[str, Any],
        start_time: datetime,
        input_data: dict[str, Any] | None = None,
    ) -> None:
        """Async version of track_stage_start."""
        await asyncio.to_thread(
            self.track_stage_start,
            stage_id,
            workflow_id,
            stage_name,
            stage_config,
            start_time,
            input_data,
        )

    async def atrack_stage_end(
        self,
        stage_id: str,
        end_time: datetime,
        status: str,
        error_message: str | None = None,
        num_agents_executed: int = 0,
        num_agents_succeeded: int = 0,
        num_agents_failed: int = 0,
    ) -> None:
        """Async version of track_stage_end."""
        await asyncio.to_thread(
            self.track_stage_end,
            stage_id,
            end_time,
            status,
            error_message,
            num_agents_executed,
            num_agents_succeeded,
            num_agents_failed,
        )

    async def aset_stage_output(
        self,
        stage_id: str,
        output_data: dict[str, Any],
        output_lineage: dict[str, Any] | None = None,
    ) -> None:
        """Async version of set_stage_output."""
        await asyncio.to_thread(
            self.set_stage_output,
            stage_id,
            output_data,
            output_lineage,
        )

    async def atrack_agent_start(
        self,
        agent_id: str,
        stage_id: str,
        agent_name: str,
        agent_config: dict[str, Any],
        start_time: datetime,
        input_data: dict[str, Any] | None = None,
    ) -> None:
        """Async version of track_agent_start."""
        await asyncio.to_thread(
            self.track_agent_start,
            agent_id,
            stage_id,
            agent_name,
            agent_config,
            start_time,
            input_data,
        )

    async def atrack_agent_end(
        self,
        agent_id: str,
        end_time: datetime,
        status: str,
        error_message: str | None = None,
    ) -> None:
        """Async version of track_agent_end."""
        await asyncio.to_thread(
            self.track_agent_end,
            agent_id,
            end_time,
            status,
            error_message,
        )

    async def aset_agent_output(
        self,
        agent_id: str,
        output_data: dict[str, Any],
        metrics: AgentOutputData | None = None,
    ) -> None:
        """Async version of set_agent_output."""
        await asyncio.to_thread(
            self.set_agent_output,
            agent_id,
            output_data,
            metrics,
        )

    async def atrack_llm_call(
        self,
        llm_call_id: str,
        agent_id: str,
        provider: str,
        model: str,
        start_time: datetime,
        data: LLMCallData,
    ) -> None:
        """Async version of track_llm_call."""
        await asyncio.to_thread(
            self.track_llm_call,
            llm_call_id,
            agent_id,
            provider,
            model,
            start_time,
            data,
        )

    async def atrack_tool_call(
        self,
        tool_execution_id: str,
        agent_id: str,
        tool_name: str,
        start_time: datetime,
        data: ToolCallData,
    ) -> None:
        """Async version of track_tool_call."""
        await asyncio.to_thread(
            self.track_tool_call,
            tool_execution_id,
            agent_id,
            tool_name,
            start_time,
            data,
        )

    async def atrack_safety_violation(
        self,
        violation_severity: str,
        violation_message: str,
        policy_name: str,
        data: SafetyViolationData | None = None,
    ) -> None:
        """Async version of track_safety_violation."""
        await asyncio.to_thread(
            self.track_safety_violation,
            violation_severity,
            violation_message,
            policy_name,
            data,
        )

    async def atrack_collaboration_event(
        self,
        stage_id: str,
        event_type: str,
        agents_involved: list[str],
        data: CollaborationEventData | None = None,
    ) -> str:
        """Async version of track_collaboration_event."""
        return await asyncio.to_thread(
            self.track_collaboration_event,
            stage_id,
            event_type,
            agents_involved,
            data,
        )

    @asynccontextmanager
    async def aget_session_context(self) -> AsyncIterator[Any]:
        """Async version of get_session_context. Default wraps sync."""
        cm = self.get_session_context()
        session = await asyncio.to_thread(cm.__enter__)
        try:
            yield session
        except Exception as exc:
            await asyncio.to_thread(
                cm.__exit__,
                type(exc),
                exc,
                exc.__traceback__,
            )
            raise
        else:
            await asyncio.to_thread(cm.__exit__, None, None, None)


class ObservabilityBackend(_AsyncBackendDefaults, ABC):
    """
    Abstract backend for observability data storage.

    All observability backends must implement this interface to provide:
    - Workflow/stage/agent execution tracking
    - LLM and tool call recording
    - Safety violation tracking
    - Metrics aggregation

    Backends can be SQL databases, time-series stores (Prometheus),
    object storage (S3), or any other persistence mechanism.

    Design principles:
    - Operations should be idempotent where possible
    - Backends handle their own connection management
    - Session/transaction management is backend-specific
    - Errors should be raised for unrecoverable failures

    Async methods are inherited from _AsyncBackendDefaults; they delegate
    to the sync abstract methods via asyncio.to_thread.
    """

    # ========== Workflow Tracking ==========

    @abstractmethod
    def track_workflow_start(
        self,
        workflow_id: str,
        workflow_name: str,
        workflow_config: dict[str, Any],
        start_time: datetime,
        data: WorkflowStartData | None = None,
        **kwargs: Any,
    ) -> None:
        """
        Record workflow execution start.

        Args:
            workflow_id: Unique workflow execution ID
            workflow_name: Name of the workflow
            workflow_config: Full workflow configuration (sanitized)
            start_time: Workflow start timestamp
            data: Optional workflow start data bundle (trigger info, metadata, etc.)
        """
        pass

    @abstractmethod
    def track_workflow_end(
        self,
        workflow_id: str,
        end_time: datetime,
        status: Literal["completed", "failed", "halted", "timeout"],
        error_message: str | None = None,
        error_stack_trace: str | None = None,
    ) -> None:
        """
        Record workflow execution completion.

        Args:
            workflow_id: Workflow execution ID
            end_time: Workflow end timestamp
            status: Final status (completed, failed, halted, timeout)
            error_message: Error message if failed
            error_stack_trace: Stack trace if failed
        """
        pass

    @abstractmethod
    def update_workflow_metrics(
        self,
        workflow_id: str,
        total_llm_calls: int,
        total_tool_calls: int,
        total_tokens: int,
        total_cost_usd: float,
    ) -> None:
        """
        Update workflow aggregated metrics.

        Args:
            workflow_id: Workflow execution ID
            total_llm_calls: Total number of LLM calls across all agents
            total_tool_calls: Total number of tool calls
            total_tokens: Total tokens consumed
            total_cost_usd: Total estimated cost in USD
        """
        pass

    # ========== Stage Tracking ==========

    @abstractmethod
    def track_stage_start(
        self,
        stage_id: str,
        workflow_id: str,
        stage_name: str,
        stage_config: dict[str, Any],
        start_time: datetime,
        input_data: dict[str, Any] | None = None,
    ) -> None:
        """
        Record stage execution start.

        Args:
            stage_id: Unique stage execution ID
            workflow_id: Parent workflow execution ID
            stage_name: Name of the stage
            stage_config: Stage configuration (sanitized)
            start_time: Stage start timestamp
            input_data: Stage input data
        """
        pass

    @abstractmethod
    def track_stage_end(
        self,
        stage_id: str,
        end_time: datetime,
        status: Literal["completed", "failed"],
        error_message: str | None = None,
        num_agents_executed: int = 0,
        num_agents_succeeded: int = 0,
        num_agents_failed: int = 0,
    ) -> None:
        """
        Record stage execution completion.

        Args:
            stage_id: Stage execution ID
            end_time: Stage end timestamp
            status: Final status (completed, failed)
            error_message: Error message if failed
            num_agents_executed: Number of agents executed in stage
            num_agents_succeeded: Number of agents that succeeded
            num_agents_failed: Number of agents that failed
        """
        pass

    @abstractmethod
    def set_stage_output(
        self,
        stage_id: str,
        output_data: dict[str, Any],
        output_lineage: dict[str, Any] | None = None,
    ) -> None:
        """
        Set stage output data.

        Args:
            stage_id: Stage execution ID
            output_data: Stage output data
            output_lineage: Optional lineage tracking data
        """
        pass

    # ========== Agent Tracking ==========

    @abstractmethod
    def track_agent_start(
        self,
        agent_id: str,
        stage_id: str,
        agent_name: str,
        agent_config: dict[str, Any],
        start_time: datetime,
        input_data: dict[str, Any] | None = None,
    ) -> None:
        """
        Record agent execution start.

        Args:
            agent_id: Unique agent execution ID
            stage_id: Parent stage execution ID
            agent_name: Name of the agent
            agent_config: Agent configuration (sanitized)
            start_time: Agent start timestamp
            input_data: Agent input data
        """
        pass

    @abstractmethod
    def track_agent_end(
        self,
        agent_id: str,
        end_time: datetime,
        status: Literal["completed", "failed"],
        error_message: str | None = None,
    ) -> None:
        """
        Record agent execution completion.

        Args:
            agent_id: Agent execution ID
            end_time: Agent end timestamp
            status: Final status (completed, failed)
            error_message: Error message if failed
        """
        pass

    @abstractmethod
    def set_agent_output(
        self,
        agent_id: str,
        output_data: dict[str, Any] | None = None,
        metrics: AgentOutputData | None = None,
        **kwargs: Any,
    ) -> None:
        """
        Set agent output data and metrics.

        Args:
            agent_id: Agent execution ID
            output_data: Agent output data
            metrics: Optional agent output metrics bundle
        """
        pass

    # ========== LLM Call Tracking ==========

    @abstractmethod
    def track_llm_call(
        self,
        llm_call_id: str,
        agent_id: str,
        provider: str,
        model: str,
        start_time: datetime | None = None,
        data: LLMCallData | None = None,
        **kwargs: Any,
    ) -> None:
        """
        Record LLM call.

        Args:
            llm_call_id: Unique LLM call ID
            agent_id: Parent agent execution ID
            provider: LLM provider (ollama, openai, anthropic)
            model: Model name
            start_time: Call start timestamp
            data: LLM call data bundle (prompt, response, tokens, etc.)
        """
        pass

    # ========== Tool Call Tracking ==========

    @abstractmethod
    def track_tool_call(
        self,
        tool_execution_id: str,
        agent_id: str,
        tool_name: str,
        start_time: datetime | None = None,
        data: ToolCallData | None = None,
        **kwargs: Any,
    ) -> None:
        """
        Record tool execution.

        Args:
            tool_execution_id: Unique tool execution ID
            agent_id: Parent agent execution ID
            tool_name: Name of the tool
            start_time: Execution start timestamp
            data: Tool call data bundle (params, output, duration, etc.)
        """
        pass

    # ========== Safety Tracking ==========

    @abstractmethod
    def track_safety_violation(
        self,
        violation_severity: str,
        violation_message: str,
        policy_name: str,
        data: SafetyViolationData | None = None,
        **kwargs: Any,
    ) -> None:
        """
        Track safety violation.

        Args:
            violation_severity: Severity level (INFO, LOW, MEDIUM, HIGH, CRITICAL)
            violation_message: Detailed violation message
            policy_name: Name of policy that was violated
            data: Optional safety violation data bundle (IDs, context, timestamp)
        """
        pass

    @abstractmethod
    def track_collaboration_event(
        self,
        stage_id: str,
        event_type: str,
        agents_involved: list[str] | None = None,
        data: CollaborationEventData | None = None,
        **kwargs: Any,
    ) -> str:
        """
        Track collaboration event to backend.

        Args:
            stage_id: ID of the stage where collaboration occurred
            event_type: Type of event (vote, conflict, resolution, consensus,
                debate_round, synthesis, quality_gate_failure, adaptive_mode_switch)
            agents_involved: List of agent IDs participating
            data: Optional collaboration event data bundle (round, strategy, outcome, etc.)

        Returns:
            str: ID of created collaboration event record
        """
        pass

    # ========== Error Fingerprinting ==========

    def record_error_fingerprint(self, data: ErrorFingerprintData) -> bool:
        """Record or update an error fingerprint.

        Upserts: if fingerprint exists, increments count and updates last_seen.
        If new, creates record with count=1.

        Args:
            data: ErrorFingerprintData bundle containing fingerprint hash,
                error type/code, classification, messages, and optional context.

        Returns:
            True if this is a newly-seen fingerprint, False if existing.
        """
        return False  # Default no-op

    def get_top_errors(
        self,
        limit: int = 10,
        classification: str | None = None,
        since: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Get top errors by occurrence count.

        Args:
            limit: Max results to return
            classification: Filter by classification
            since: Only errors seen after this time

        Returns:
            List of error fingerprint dicts, ordered by occurrence_count desc.
        """
        return []  # Default no-op

    # ========== Context Management ==========

    @abstractmethod
    def get_session_context(self) -> ContextManager[Any]:
        """
        Get backend-specific session/transaction context manager.

        Returns:
            Context manager for session/transaction management.

        Example (SQL):
            with backend.get_session_context() as session:
                # Operations use this session
                pass

        Example (Prometheus/S3):
            with backend.get_session_context():
                # No-op, returns null context
                pass
        """
        pass

    # ========== Maintenance Operations ==========

    @abstractmethod
    def cleanup_old_records(
        self, retention_days: int, dry_run: bool = False
    ) -> dict[str, int]:
        """
        Clean up old observability records based on retention policy.

        Args:
            retention_days: Number of days to retain records
            dry_run: If True, only count records but don't delete

        Returns:
            Dictionary with counts of records that would be/were deleted:
            {"workflows": 10, "stages": 50, "agents": 200, ...}
        """
        pass

    @abstractmethod
    def get_stats(self) -> dict[str, Any]:
        """
        Get backend statistics and health information.

        Returns:
            Dictionary with backend stats:
            {
                "backend_type": "sql",
                "total_workflows": 1000,
                "total_stages": 5000,
                "total_agents": 10000,
                "storage_size_mb": 512,
                "oldest_record": "2024-01-01T00:00:00Z",
                "newest_record": "2024-03-01T00:00:00Z",
                ...
            }
        """
        pass
