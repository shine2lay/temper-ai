"""
Abstract backend interface for observability system.

Defines the contract that all observability backends must implement,
enabling pluggable storage backends (SQL, Prometheus, S3, etc.).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any, ContextManager, Dict, List, Literal, Optional

DEFAULT_LIST_LIMIT = 50


# ========== Parameter Bundle Dataclasses ==========


@dataclass
class WorkflowStartData:
    """Bundled optional parameters for track_workflow_start."""
    trigger_type: Optional[str] = None
    trigger_data: Optional[Dict[str, Any]] = None
    optimization_target: Optional[str] = None
    product_type: Optional[str] = None
    environment: Optional[str] = None
    tags: Optional[List[str]] = None
    extra_metadata: Optional[Dict[str, Any]] = None


@dataclass
class AgentOutputData:
    """Bundled optional metrics for set_agent_output."""
    reasoning: Optional[str] = None
    confidence_score: Optional[float] = None
    total_tokens: Optional[int] = None
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    estimated_cost_usd: Optional[float] = None
    num_llm_calls: Optional[int] = None
    num_tool_calls: Optional[int] = None


@dataclass
class LLMCallData:
    """Bundled LLM call parameters."""
    prompt: str
    response: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: int
    estimated_cost_usd: float
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    status: Literal["success", "failed"] = "success"
    error_message: Optional[str] = None


@dataclass
class ToolCallData:
    """Bundled tool call parameters."""
    input_params: Dict[str, Any]
    output_data: Dict[str, Any]
    duration_seconds: float
    status: Literal["success", "failed"] = "success"
    error_message: Optional[str] = None
    safety_checks: Optional[List[str]] = None
    approval_required: bool = False


@dataclass
class SafetyViolationData:
    """Bundled safety violation parameters."""
    workflow_id: Optional[str] = None
    stage_id: Optional[str] = None
    agent_id: Optional[str] = None
    service_name: Optional[str] = None
    context: Optional[Dict[str, Any]] = None
    timestamp: Optional[datetime] = None


@dataclass
class CollaborationEventData:
    """Bundled collaboration event parameters."""
    event_data: Optional[Dict[str, Any]] = None
    round_number: Optional[int] = None
    resolution_strategy: Optional[str] = None
    outcome: Optional[str] = None
    confidence_score: Optional[float] = None
    extra_metadata: Optional[Dict[str, Any]] = None
    timestamp: Optional[datetime] = None


class ReadableBackendMixin:
    """Mixin providing default read operations for observability data.

    Default implementations return empty results. Override in backends
    that support persistent storage (e.g., SQL).
    """

    def get_workflow(self, workflow_id: str) -> Optional[Dict[str, Any]]:
        """Get workflow execution data by ID, or None if not found."""
        return None

    def list_workflows(self, limit: int = DEFAULT_LIST_LIMIT, offset: int = 0, status: Optional[str] = None) -> List[Dict[str, Any]]:
        """List workflow executions with optional filtering."""
        return []

    def get_stage(self, stage_id: str) -> Optional[Dict[str, Any]]:
        """Get stage execution data by ID, or None if not found."""
        return None

    def get_agent(self, agent_id: str) -> Optional[Dict[str, Any]]:
        """Get agent execution data by ID, or None if not found."""
        return None

    def get_llm_call(self, llm_call_id: str) -> Optional[Dict[str, Any]]:
        """Get LLM call data by ID, or None if not found."""
        return None

    def get_tool_call(self, tool_call_id: str) -> Optional[Dict[str, Any]]:
        """Get tool call data by ID, or None if not found."""
        return None


class ObservabilityBackend(ABC):
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
    """

    # ========== Workflow Tracking ==========

    @abstractmethod
    def track_workflow_start(
        self,
        workflow_id: str,
        workflow_name: str,
        workflow_config: Dict[str, Any],
        start_time: datetime,
        data: Optional[WorkflowStartData] = None
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
        error_message: Optional[str] = None,
        error_stack_trace: Optional[str] = None
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
        total_cost_usd: float
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
        stage_config: Dict[str, Any],
        start_time: datetime,
        input_data: Optional[Dict[str, Any]] = None
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
        error_message: Optional[str] = None,
        num_agents_executed: int = 0,
        num_agents_succeeded: int = 0,
        num_agents_failed: int = 0
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
        output_data: Dict[str, Any]
    ) -> None:
        """
        Set stage output data.

        Args:
            stage_id: Stage execution ID
            output_data: Stage output data
        """
        pass

    # ========== Agent Tracking ==========

    @abstractmethod
    def track_agent_start(
        self,
        agent_id: str,
        stage_id: str,
        agent_name: str,
        agent_config: Dict[str, Any],
        start_time: datetime,
        input_data: Optional[Dict[str, Any]] = None
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
        error_message: Optional[str] = None
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
        output_data: Dict[str, Any],
        metrics: Optional[AgentOutputData] = None
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
        start_time: datetime,
        data: LLMCallData
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
        start_time: datetime,
        data: ToolCallData
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
        violation_severity: Literal["INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL"],
        violation_message: str,
        policy_name: str,
        data: Optional[SafetyViolationData] = None
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
        agents_involved: List[str],
        data: Optional[CollaborationEventData] = None
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

    def record_error_fingerprint(
        self,
        fingerprint: str,
        error_type: str,
        error_code: str,
        classification: str,
        normalized_message: str,
        sample_message: str,
        workflow_id: Optional[str] = None,
        agent_name: Optional[str] = None,
    ) -> bool:
        """Record or update an error fingerprint.

        Upserts: if fingerprint exists, increments count and updates last_seen.
        If new, creates record with count=1.

        Args:
            fingerprint: 16-char hex fingerprint hash
            error_type: Exception class name
            error_code: Canonical error code
            classification: transient/permanent/safety/unknown
            normalized_message: Deterministic normalized message
            sample_message: One raw example (truncated)
            workflow_id: Optional workflow context
            agent_name: Optional agent context

        Returns:
            True if this is a newly-seen fingerprint, False if existing.
        """
        return False  # Default no-op

    def get_top_errors(
        self,
        limit: int = 10,
        classification: Optional[str] = None,
        since: Optional[datetime] = None,
    ) -> List[Dict[str, Any]]:
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
            Dictionary with counts of records that would be/were deleted:
            {"workflows": 10, "stages": 50, "agents": 200, ...}
        """
        pass

    @abstractmethod
    def get_stats(self) -> Dict[str, Any]:
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
