"""No-op observability backend for testing and demos.

This backend implements the ObservabilityBackend interface but doesn't actually
persist any data. Useful for demos and testing when you don't want database overhead.
"""
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime
from typing import Any, AsyncIterator, Dict, List, Optional

from src.observability.backend import (
    AgentOutputData,
    CollaborationEventData,
    ErrorFingerprintData,
    LLMCallData,
    ObservabilityBackend,
    ReadableBackendMixin,
    SafetyViolationData,
    ToolCallData,
    WorkflowStartData,
)


class NoOpBackend(ObservabilityBackend, ReadableBackendMixin):
    """Observability backend that discards all data."""

    # ========== Workflow Tracking ==========

    def track_workflow_start(
        self,
        workflow_id: str,
        workflow_name: str,
        workflow_config: Dict[str, Any],
        start_time: datetime,
        data: Optional[WorkflowStartData] = None
    ) -> None:
        """Track workflow start (no-op)."""
        pass

    def track_workflow_end(
        self,
        workflow_id: str,
        end_time: datetime,
        status: str,
        error_message: Optional[str] = None,
        error_stack_trace: Optional[str] = None
    ) -> None:
        """Track workflow end (no-op)."""
        pass

    def update_workflow_metrics(
        self,
        workflow_id: str,
        total_llm_calls: int,
        total_tool_calls: int,
        total_tokens: int,
        total_cost_usd: float
    ) -> None:
        """Update workflow metrics (no-op)."""
        pass

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
        """Track stage start (no-op)."""
        pass

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
        """Track stage end (no-op)."""
        pass

    def set_stage_output(
        self,
        stage_id: str,
        output_data: Dict[str, Any],
        output_lineage: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Set stage output (no-op)."""
        pass

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
        """Track agent start (no-op)."""
        pass

    def track_agent_end(
        self,
        agent_id: str,
        end_time: datetime,
        status: str,
        error_message: Optional[str] = None
    ) -> None:
        """Track agent end (no-op)."""
        pass

    def set_agent_output(
        self,
        agent_id: str,
        output_data: Dict[str, Any],
        metrics: Optional[AgentOutputData] = None
    ) -> None:
        """Set agent output (no-op)."""
        pass

    # ========== LLM Call Tracking ==========

    def track_llm_call(
        self,
        llm_call_id: str,
        agent_id: str,
        provider: str,
        model: str,
        start_time: datetime,
        data: LLMCallData
    ) -> None:
        """Track LLM call (no-op)."""
        pass

    # ========== Tool Call Tracking ==========

    def track_tool_call(
        self,
        tool_execution_id: str,
        agent_id: str,
        tool_name: str,
        start_time: datetime,
        data: ToolCallData
    ) -> None:
        """Track tool call (no-op)."""
        pass

    # ========== Safety Tracking ==========

    def track_safety_violation(
        self,
        violation_severity: str,
        violation_message: str,
        policy_name: str,
        data: Optional[SafetyViolationData] = None
    ) -> None:
        """Track safety violation (no-op)."""
        pass

    def track_collaboration_event(
        self,
        stage_id: str,
        event_type: str,
        agents_involved: List[str],
        data: Optional[CollaborationEventData] = None
    ) -> str:
        """Track collaboration event (no-op)."""
        return ""

    # ========== Error Fingerprinting ==========

    def record_error_fingerprint(self, data: ErrorFingerprintData) -> bool:
        """Record error fingerprint (no-op)."""
        return False

    def get_top_errors(
        self,
        limit: int = 10,
        classification: Optional[str] = None,
        since: Optional[Any] = None,
    ) -> list:
        """Get top errors (no-op)."""
        return []

    # ========== Context Management ==========

    @contextmanager
    def get_session_context(self) -> Any:
        """Get session context (no-op)."""
        yield None

    # ========== Async Methods (skip to_thread overhead) ==========

    async def atrack_workflow_start(
        self,
        workflow_id: str,
        workflow_name: str,
        workflow_config: Dict[str, Any],
        start_time: datetime,
        data: Optional[WorkflowStartData] = None,
    ) -> None:
        """Async no-op: skip thread delegation overhead."""
        pass

    async def atrack_workflow_end(
        self,
        workflow_id: str,
        end_time: datetime,
        status: str,
        error_message: Optional[str] = None,
        error_stack_trace: Optional[str] = None,
    ) -> None:
        """Async no-op: skip thread delegation overhead."""
        pass

    async def atrack_stage_start(
        self,
        stage_id: str,
        workflow_id: str,
        stage_name: str,
        stage_config: Dict[str, Any],
        start_time: datetime,
        input_data: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Async no-op: skip thread delegation overhead."""
        pass

    async def atrack_stage_end(
        self,
        stage_id: str,
        end_time: datetime,
        status: str,
        error_message: Optional[str] = None,
        num_agents_executed: int = 0,
        num_agents_succeeded: int = 0,
        num_agents_failed: int = 0,
    ) -> None:
        """Async no-op: skip thread delegation overhead."""
        pass

    async def atrack_agent_start(
        self,
        agent_id: str,
        stage_id: str,
        agent_name: str,
        agent_config: Dict[str, Any],
        start_time: datetime,
        input_data: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Async no-op: skip thread delegation overhead."""
        pass

    async def atrack_agent_end(
        self,
        agent_id: str,
        end_time: datetime,
        status: str,
        error_message: Optional[str] = None,
    ) -> None:
        """Async no-op: skip thread delegation overhead."""
        pass

    async def atrack_llm_call(
        self,
        llm_call_id: str,
        agent_id: str,
        provider: str,
        model: str,
        start_time: datetime,
        data: LLMCallData,
    ) -> None:
        """Async no-op: skip thread delegation overhead."""
        pass

    async def atrack_tool_call(
        self,
        tool_execution_id: str,
        agent_id: str,
        tool_name: str,
        start_time: datetime,
        data: ToolCallData,
    ) -> None:
        """Async no-op: skip thread delegation overhead."""
        pass

    async def aset_agent_output(
        self,
        agent_id: str,
        output_data: Dict[str, Any],
        metrics: Optional[AgentOutputData] = None,
    ) -> None:
        """Async no-op: skip thread delegation overhead."""
        pass

    async def aset_stage_output(
        self,
        stage_id: str,
        output_data: Dict[str, Any],
        output_lineage: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Async no-op: skip thread delegation overhead."""
        pass

    async def aupdate_workflow_metrics(
        self,
        workflow_id: str,
        total_llm_calls: int,
        total_tool_calls: int,
        total_tokens: int,
        total_cost_usd: float,
    ) -> None:
        """Async no-op: skip thread delegation overhead."""
        pass

    async def atrack_collaboration_event(
        self,
        stage_id: str,
        event_type: str,
        agents_involved: List[str],
        data: Optional[CollaborationEventData] = None,
    ) -> str:
        """Async no-op: skip thread delegation overhead."""
        return ""

    async def atrack_safety_violation(
        self,
        violation_severity: str,
        violation_message: str,
        policy_name: str,
        data: Optional[SafetyViolationData] = None,
    ) -> None:
        """Async no-op: skip thread delegation overhead."""
        pass

    @asynccontextmanager
    async def aget_session_context(self) -> AsyncIterator[Any]:
        """Async no-op: skip thread delegation overhead."""
        yield None

    # ========== Maintenance Operations ==========

    def cleanup_old_records(
        self,
        retention_days: int,
        dry_run: bool = False
    ) -> Dict[str, int]:
        """Cleanup old records (no-op)."""
        return {}

    def get_stats(self) -> Dict[str, Any]:
        """Get backend stats."""
        return {"backend_type": "noop"}
