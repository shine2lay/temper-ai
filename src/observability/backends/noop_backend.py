"""No-op observability backend for testing and demos.

This backend implements the ObservabilityBackend interface but doesn't actually
persist any data. Useful for demos and testing when you don't want database overhead.
"""
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Dict, List, Optional

from src.observability.backend import DEFAULT_LIST_LIMIT, ObservabilityBackend


class NoOpBackend(ObservabilityBackend):
    """Observability backend that discards all data."""

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
        output_data: Dict[str, Any]
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
        reasoning: Optional[str] = None,
        confidence_score: Optional[float] = None,
        total_tokens: Optional[int] = None,
        prompt_tokens: Optional[int] = None,
        completion_tokens: Optional[int] = None,
        estimated_cost_usd: Optional[float] = None,
        num_llm_calls: Optional[int] = None,
        num_tool_calls: Optional[int] = None
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
        """Track LLM call (no-op)."""
        pass

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
        """Track tool call (no-op)."""
        pass

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
        """Track safety violation (no-op)."""
        pass

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
        """Track collaboration event (no-op)."""
        return ""

    # ========== Read Operations ==========

    def get_workflow(self, workflow_id: str) -> Optional[Dict[str, Any]]:
        """Get workflow (no-op)."""
        return None

    def list_workflows(self, limit: int = DEFAULT_LIST_LIMIT, offset: int = 0, status: Optional[str] = None) -> List[Dict[str, Any]]:
        """List workflows (no-op)."""
        return []

    def get_stage(self, stage_id: str) -> Optional[Dict[str, Any]]:
        """Get stage (no-op)."""
        return None

    def get_agent(self, agent_id: str) -> Optional[Dict[str, Any]]:
        """Get agent (no-op)."""
        return None

    def get_llm_call(self, llm_call_id: str) -> Optional[Dict[str, Any]]:
        """Get LLM call (no-op)."""
        return None

    def get_tool_call(self, tool_call_id: str) -> Optional[Dict[str, Any]]:
        """Get tool call (no-op)."""
        return None

    # ========== Context Management ==========

    @contextmanager
    def get_session_context(self) -> Any:
        """Get session context (no-op)."""
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
