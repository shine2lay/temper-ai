"""Composite observability backend that fans out to multiple backends.

The primary backend (typically SQL) handles reads and session management.
Secondary backends (OTEL, Prometheus, etc.) are fire-and-forget: failures
are logged but never propagated, ensuring they cannot disrupt execution.
"""
import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, AsyncIterator, ContextManager, Dict, List, Optional

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

logger = logging.getLogger(__name__)


class CompositeBackend(ObservabilityBackend, ReadableBackendMixin):
    """Fans out tracking calls to a primary + N secondary backends.

    - **Primary**: Handles reads, sessions, maintenance. Errors propagate.
    - **Secondary**: Fire-and-forget. Errors are logged at WARNING level.
    """

    def __init__(
        self,
        primary: ObservabilityBackend,
        secondaries: Optional[List[ObservabilityBackend]] = None,
    ) -> None:
        """Initialize with a primary backend and optional secondary backends."""
        self._primary = primary
        self._secondaries: List[ObservabilityBackend] = secondaries or []

    def _fan_out(self, method_name: str, *args: Any, **kwargs: Any) -> None:
        """Call *method_name* on every secondary, swallowing errors."""
        for backend in self._secondaries:
            try:
                getattr(backend, method_name)(*args, **kwargs)
            except Exception:  # noqa: BLE001 — secondary must never crash primary
                logger.warning(
                    "Secondary backend %s.%s failed",
                    type(backend).__name__, method_name,
                    exc_info=True,
                )

    async def _afan_out(self, method_name: str, *args: Any, **kwargs: Any) -> None:
        """Call async *method_name* on every secondary, swallowing errors."""
        if not self._secondaries:
            return
        tasks = []
        for backend in self._secondaries:
            coro = getattr(backend, method_name)(*args, **kwargs)
            tasks.append(coro)
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.warning(
                    "Secondary backend %s.%s failed",
                    type(self._secondaries[i]).__name__, method_name,
                    exc_info=(type(result), result, result.__traceback__),
                )

    # ========== Workflow Tracking ==========

    def track_workflow_start(
        self,
        workflow_id: str,
        workflow_name: str,
        workflow_config: Dict[str, Any],
        start_time: datetime,
        data: Optional[WorkflowStartData] = None,
    ) -> None:
        """Delegate to primary and fan out to secondaries."""
        self._primary.track_workflow_start(
            workflow_id, workflow_name, workflow_config, start_time, data
        )
        self._fan_out(
            "track_workflow_start",
            workflow_id, workflow_name, workflow_config, start_time, data,
        )

    def track_workflow_end(
        self,
        workflow_id: str,
        end_time: datetime,
        status: str,
        error_message: Optional[str] = None,
        error_stack_trace: Optional[str] = None,
    ) -> None:
        """Delegate to primary and fan out to secondaries."""
        self._primary.track_workflow_end(
            workflow_id, end_time, status, error_message, error_stack_trace  # type: ignore[arg-type]
        )
        self._fan_out(
            "track_workflow_end",
            workflow_id, end_time, status, error_message, error_stack_trace,
        )

    def update_workflow_metrics(
        self,
        workflow_id: str,
        total_llm_calls: int,
        total_tool_calls: int,
        total_tokens: int,
        total_cost_usd: float,
    ) -> None:
        """Delegate to primary and fan out to secondaries."""
        self._primary.update_workflow_metrics(
            workflow_id, total_llm_calls, total_tool_calls, total_tokens, total_cost_usd
        )
        self._fan_out(
            "update_workflow_metrics",
            workflow_id, total_llm_calls, total_tool_calls, total_tokens, total_cost_usd,
        )

    # ========== Stage Tracking ==========

    def track_stage_start(
        self,
        stage_id: str,
        workflow_id: str,
        stage_name: str,
        stage_config: Dict[str, Any],
        start_time: datetime,
        input_data: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Delegate to primary and fan out to secondaries."""
        self._primary.track_stage_start(
            stage_id, workflow_id, stage_name, stage_config, start_time, input_data
        )
        self._fan_out(
            "track_stage_start",
            stage_id, workflow_id, stage_name, stage_config, start_time, input_data,
        )

    def track_stage_end(
        self,
        stage_id: str,
        end_time: datetime,
        status: str,
        error_message: Optional[str] = None,
        num_agents_executed: int = 0,
        num_agents_succeeded: int = 0,
        num_agents_failed: int = 0,
    ) -> None:
        """Delegate to primary and fan out to secondaries."""
        self._primary.track_stage_end(
            stage_id, end_time, status, error_message,  # type: ignore[arg-type]
            num_agents_executed, num_agents_succeeded, num_agents_failed,
        )
        self._fan_out(
            "track_stage_end",
            stage_id, end_time, status, error_message,
            num_agents_executed, num_agents_succeeded, num_agents_failed,
        )

    def set_stage_output(
        self, stage_id: str, output_data: Dict[str, Any],
        output_lineage: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Delegate to primary and fan out to secondaries."""
        self._primary.set_stage_output(stage_id, output_data, output_lineage)
        self._fan_out("set_stage_output", stage_id, output_data, output_lineage)

    # ========== Agent Tracking ==========

    def track_agent_start(
        self,
        agent_id: str,
        stage_id: str,
        agent_name: str,
        agent_config: Dict[str, Any],
        start_time: datetime,
        input_data: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Delegate to primary and fan out to secondaries."""
        self._primary.track_agent_start(
            agent_id, stage_id, agent_name, agent_config, start_time, input_data
        )
        self._fan_out(
            "track_agent_start",
            agent_id, stage_id, agent_name, agent_config, start_time, input_data,
        )

    def track_agent_end(
        self,
        agent_id: str,
        end_time: datetime,
        status: str,
        error_message: Optional[str] = None,
    ) -> None:
        """Delegate to primary and fan out to secondaries."""
        self._primary.track_agent_end(agent_id, end_time, status, error_message)  # type: ignore[arg-type]
        self._fan_out("track_agent_end", agent_id, end_time, status, error_message)

    def set_agent_output(
        self,
        agent_id: str,
        output_data: Dict[str, Any],
        metrics: Optional[AgentOutputData] = None,
    ) -> None:
        """Delegate to primary and fan out to secondaries."""
        self._primary.set_agent_output(agent_id, output_data, metrics)
        self._fan_out("set_agent_output", agent_id, output_data, metrics)

    # ========== LLM / Tool Tracking ==========

    def track_llm_call(
        self,
        llm_call_id: str,
        agent_id: str,
        provider: str,
        model: str,
        start_time: datetime,
        data: LLMCallData,
    ) -> None:
        """Delegate to primary and fan out to secondaries."""
        self._primary.track_llm_call(
            llm_call_id, agent_id, provider, model, start_time, data
        )
        self._fan_out(
            "track_llm_call",
            llm_call_id, agent_id, provider, model, start_time, data,
        )

    def track_tool_call(
        self,
        tool_execution_id: str,
        agent_id: str,
        tool_name: str,
        start_time: datetime,
        data: ToolCallData,
    ) -> None:
        """Delegate to primary and fan out to secondaries."""
        self._primary.track_tool_call(
            tool_execution_id, agent_id, tool_name, start_time, data
        )
        self._fan_out(
            "track_tool_call",
            tool_execution_id, agent_id, tool_name, start_time, data,
        )

    # ========== Safety / Collaboration ==========

    def track_safety_violation(
        self,
        violation_severity: str,
        violation_message: str,
        policy_name: str,
        data: Optional[SafetyViolationData] = None,
    ) -> None:
        """Delegate to primary and fan out to secondaries."""
        self._primary.track_safety_violation(
            violation_severity, violation_message, policy_name, data  # type: ignore[arg-type]
        )
        self._fan_out(
            "track_safety_violation",
            violation_severity, violation_message, policy_name, data,
        )

    def track_collaboration_event(
        self,
        stage_id: str,
        event_type: str,
        agents_involved: List[str],
        data: Optional[CollaborationEventData] = None,
    ) -> str:
        """Delegate to primary and fan out to secondaries."""
        result = self._primary.track_collaboration_event(
            stage_id, event_type, agents_involved, data
        )
        self._fan_out(
            "track_collaboration_event",
            stage_id, event_type, agents_involved, data,
        )
        return result

    # ========== Error Fingerprinting ==========

    def record_error_fingerprint(self, data: ErrorFingerprintData) -> bool:
        """Delegate to primary and fan out to secondaries."""
        result = self._primary.record_error_fingerprint(data)
        self._fan_out("record_error_fingerprint", data)
        return result

    def get_top_errors(
        self,
        limit: int = 10,
        classification: Optional[str] = None,
        since: Optional[Any] = None,
    ) -> list:
        """Delegate to primary backend only."""
        return self._primary.get_top_errors(limit, classification, since)

    # ========== Reads, Sessions, Maintenance — primary only ==========

    def get_session_context(self) -> ContextManager[Any]:
        """Delegate session context to primary backend."""
        return self._primary.get_session_context()

    def cleanup_old_records(
        self, retention_days: int, dry_run: bool = False
    ) -> Dict[str, int]:
        """Delegate record cleanup to primary backend."""
        return self._primary.cleanup_old_records(retention_days, dry_run)

    def get_stats(self) -> Dict[str, Any]:
        """Return primary stats augmented with composite metadata."""
        stats = self._primary.get_stats()
        stats["composite"] = True
        stats["num_secondaries"] = len(self._secondaries)
        return stats

    # ========== ReadableBackendMixin — delegate to primary ==========

    def get_workflow(self, workflow_id: str) -> Optional[Dict[str, Any]]:
        """Delegate workflow lookup to primary if it supports reads."""
        if isinstance(self._primary, ReadableBackendMixin):
            return self._primary.get_workflow(workflow_id)
        return None

    def list_workflows(
        self, limit: int = 50, offset: int = 0, status: Optional[str] = None  # noqa: params
    ) -> List[Dict[str, Any]]:
        """Delegate workflow listing to primary if it supports reads."""
        if isinstance(self._primary, ReadableBackendMixin):
            return self._primary.list_workflows(limit, offset, status)
        return []

    # Delegate aggregate helpers to primary if available
    def __getattr__(self, name: str) -> Any:
        """Forward unknown attributes (e.g., aggregate_workflow_metrics) to primary."""
        return getattr(self._primary, name)

    # ========== Async Methods ==========

    async def atrack_workflow_start(
        self, workflow_id: str, workflow_name: str,
        workflow_config: Dict[str, Any], start_time: datetime,
        data: Optional[WorkflowStartData] = None,
    ) -> None:
        """Async: delegate to primary and fan out to secondaries."""
        await self._primary.atrack_workflow_start(workflow_id, workflow_name, workflow_config, start_time, data)
        await self._afan_out("atrack_workflow_start", workflow_id, workflow_name, workflow_config, start_time, data)

    async def atrack_workflow_end(
        self, workflow_id: str, end_time: datetime, status: str,
        error_message: Optional[str] = None, error_stack_trace: Optional[str] = None,
    ) -> None:
        """Async: delegate to primary and fan out to secondaries."""
        await self._primary.atrack_workflow_end(
            workflow_id, end_time, status, error_message, error_stack_trace,
        )
        await self._afan_out("atrack_workflow_end", workflow_id, end_time, status, error_message, error_stack_trace)

    async def aupdate_workflow_metrics(
        self, workflow_id: str, total_llm_calls: int, total_tool_calls: int,
        total_tokens: int, total_cost_usd: float,
    ) -> None:
        """Async: delegate to primary and fan out to secondaries."""
        await self._primary.aupdate_workflow_metrics(workflow_id, total_llm_calls, total_tool_calls, total_tokens, total_cost_usd)
        await self._afan_out("aupdate_workflow_metrics", workflow_id, total_llm_calls, total_tool_calls, total_tokens, total_cost_usd)

    async def atrack_stage_start(
        self, stage_id: str, workflow_id: str, stage_name: str,
        stage_config: Dict[str, Any], start_time: datetime,
        input_data: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Async: delegate to primary and fan out to secondaries."""
        await self._primary.atrack_stage_start(stage_id, workflow_id, stage_name, stage_config, start_time, input_data)
        await self._afan_out("atrack_stage_start", stage_id, workflow_id, stage_name, stage_config, start_time, input_data)

    async def atrack_stage_end(
        self, stage_id: str, end_time: datetime, status: str,
        error_message: Optional[str] = None, num_agents_executed: int = 0,
        num_agents_succeeded: int = 0, num_agents_failed: int = 0,
    ) -> None:
        """Async: delegate to primary and fan out to secondaries."""
        await self._primary.atrack_stage_end(
            stage_id, end_time, status, error_message,
            num_agents_executed, num_agents_succeeded, num_agents_failed,
        )
        await self._afan_out("atrack_stage_end", stage_id, end_time, status, error_message, num_agents_executed, num_agents_succeeded, num_agents_failed)

    async def aset_stage_output(
        self, stage_id: str, output_data: Dict[str, Any],
        output_lineage: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Async: delegate to primary and fan out to secondaries."""
        await self._primary.aset_stage_output(stage_id, output_data, output_lineage)
        await self._afan_out("aset_stage_output", stage_id, output_data, output_lineage)

    async def atrack_agent_start(
        self, agent_id: str, stage_id: str, agent_name: str,
        agent_config: Dict[str, Any], start_time: datetime,
        input_data: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Async: delegate to primary and fan out to secondaries."""
        await self._primary.atrack_agent_start(agent_id, stage_id, agent_name, agent_config, start_time, input_data)
        await self._afan_out("atrack_agent_start", agent_id, stage_id, agent_name, agent_config, start_time, input_data)

    async def atrack_agent_end(
        self, agent_id: str, end_time: datetime, status: str,
        error_message: Optional[str] = None,
    ) -> None:
        """Async: delegate to primary and fan out to secondaries."""
        await self._primary.atrack_agent_end(
            agent_id, end_time, status, error_message,
        )
        await self._afan_out("atrack_agent_end", agent_id, end_time, status, error_message)

    async def aset_agent_output(
        self, agent_id: str, output_data: Dict[str, Any],
        metrics: Optional[AgentOutputData] = None,
    ) -> None:
        """Async: delegate to primary and fan out to secondaries."""
        await self._primary.aset_agent_output(agent_id, output_data, metrics)
        await self._afan_out("aset_agent_output", agent_id, output_data, metrics)

    async def atrack_llm_call(
        self, llm_call_id: str, agent_id: str, provider: str,
        model: str, start_time: datetime, data: LLMCallData,
    ) -> None:
        """Async: delegate to primary and fan out to secondaries."""
        await self._primary.atrack_llm_call(llm_call_id, agent_id, provider, model, start_time, data)
        await self._afan_out("atrack_llm_call", llm_call_id, agent_id, provider, model, start_time, data)

    async def atrack_tool_call(
        self, tool_execution_id: str, agent_id: str, tool_name: str,
        start_time: datetime, data: ToolCallData,
    ) -> None:
        """Async: delegate to primary and fan out to secondaries."""
        await self._primary.atrack_tool_call(tool_execution_id, agent_id, tool_name, start_time, data)
        await self._afan_out("atrack_tool_call", tool_execution_id, agent_id, tool_name, start_time, data)

    async def atrack_safety_violation(
        self, violation_severity: str, violation_message: str,
        policy_name: str, data: Optional[SafetyViolationData] = None,
    ) -> None:
        """Async: delegate to primary and fan out to secondaries."""
        await self._primary.atrack_safety_violation(
            violation_severity, violation_message, policy_name, data,
        )
        await self._afan_out("atrack_safety_violation", violation_severity, violation_message, policy_name, data)

    async def atrack_collaboration_event(
        self, stage_id: str, event_type: str, agents_involved: List[str],
        data: Optional[CollaborationEventData] = None,
    ) -> str:
        """Async: delegate to primary and fan out to secondaries."""
        result = await self._primary.atrack_collaboration_event(stage_id, event_type, agents_involved, data)
        await self._afan_out("atrack_collaboration_event", stage_id, event_type, agents_involved, data)
        return result

    @asynccontextmanager
    async def aget_session_context(self) -> AsyncIterator[Any]:
        """Async session context -- delegates to primary."""
        async with self._primary.aget_session_context() as session:
            yield session
