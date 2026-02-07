"""
Abstract backend interface for observability system.

Defines the contract that all observability backends must implement,
enabling pluggable storage backends (SQL, Prometheus, S3, etc.).
"""
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, ContextManager, Dict, List, Literal, Optional


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
        trigger_type: Optional[str] = None,
        trigger_data: Optional[Dict[str, Any]] = None,
        optimization_target: Optional[str] = None,
        product_type: Optional[str] = None,
        environment: Optional[str] = None,
        tags: Optional[List[str]] = None,
        extra_metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Record workflow execution start.

        Args:
            workflow_id: Unique workflow execution ID
            workflow_name: Name of the workflow
            workflow_config: Full workflow configuration (sanitized)
            start_time: Workflow start timestamp
            trigger_type: How workflow was triggered (manual, cron, event)
            trigger_data: Trigger metadata
            optimization_target: Current optimization target (speed, quality, cost)
            product_type: Type of product being built
            environment: Execution environment (dev, staging, prod)
            tags: Additional tags for filtering
            extra_metadata: Additional metadata (e.g., experiment_id, variant_id)
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
        reasoning: Optional[str] = None,
        confidence_score: Optional[float] = None,
        total_tokens: Optional[int] = None,
        prompt_tokens: Optional[int] = None,
        completion_tokens: Optional[int] = None,
        estimated_cost_usd: Optional[float] = None,
        num_llm_calls: Optional[int] = None,
        num_tool_calls: Optional[int] = None
    ) -> None:
        """
        Set agent output data and metrics.

        Args:
            agent_id: Agent execution ID
            output_data: Agent output data
            reasoning: Agent reasoning text
            confidence_score: Confidence score (0-1)
            total_tokens: Total tokens used
            prompt_tokens: Prompt tokens used
            completion_tokens: Completion tokens used
            estimated_cost_usd: Estimated cost in USD
            num_llm_calls: Number of LLM calls made
            num_tool_calls: Number of tool calls made
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
        prompt: str,
        response: str,
        prompt_tokens: int,
        completion_tokens: int,
        latency_ms: int,
        estimated_cost_usd: float,
        start_time: datetime,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        status: Literal["success", "failed"] = "success",
        error_message: Optional[str] = None
    ) -> None:
        """
        Record LLM call.

        Args:
            llm_call_id: Unique LLM call ID
            agent_id: Parent agent execution ID
            provider: LLM provider (ollama, openai, anthropic)
            model: Model name
            prompt: Input prompt
            response: LLM response
            prompt_tokens: Number of prompt tokens
            completion_tokens: Number of completion tokens
            latency_ms: Latency in milliseconds
            estimated_cost_usd: Estimated cost
            start_time: Call start timestamp
            temperature: Temperature setting
            max_tokens: Max tokens setting
            status: Call status (success, failed)
            error_message: Error if failed
        """
        pass

    # ========== Tool Call Tracking ==========

    @abstractmethod
    def track_tool_call(
        self,
        tool_execution_id: str,
        agent_id: str,
        tool_name: str,
        input_params: Dict[str, Any],
        output_data: Dict[str, Any],
        start_time: datetime,
        duration_seconds: float,
        status: Literal["success", "failed"] = "success",
        error_message: Optional[str] = None,
        safety_checks: Optional[List[str]] = None,
        approval_required: bool = False
    ) -> None:
        """
        Record tool execution.

        Args:
            tool_execution_id: Unique tool execution ID
            agent_id: Parent agent execution ID
            tool_name: Name of the tool
            input_params: Tool input parameters
            output_data: Tool output data
            start_time: Execution start timestamp
            duration_seconds: Execution duration
            status: Execution status (success, failed)
            error_message: Error if failed
            safety_checks: Safety checks applied
            approval_required: Whether approval was required
        """
        pass

    # ========== Safety Tracking ==========

    @abstractmethod
    def track_safety_violation(
        self,
        workflow_id: Optional[str],
        stage_id: Optional[str],
        agent_id: Optional[str],
        violation_severity: Literal["INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL"],
        violation_message: str,
        policy_name: str,
        service_name: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        timestamp: Optional[datetime] = None
    ) -> None:
        """
        Track safety violation.

        Args:
            workflow_id: Workflow execution ID (if in workflow context)
            stage_id: Stage execution ID (if in stage context)
            agent_id: Agent execution ID (if in agent context)
            violation_severity: Severity level (INFO, LOW, MEDIUM, HIGH, CRITICAL)
            violation_message: Detailed violation message
            policy_name: Name of policy that was violated
            service_name: Service that detected the violation
            context: Additional context (action, params, etc.)
            timestamp: Violation timestamp
        """
        pass

    @abstractmethod
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
        Track collaboration event to backend.

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
            str: ID of created collaboration event record
        """
        pass

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
