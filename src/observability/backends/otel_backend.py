"""OpenTelemetry observability backend.

Maps MAF tracker calls to OTEL spans and metrics. Requires the
``opentelemetry-api`` and ``opentelemetry-sdk`` packages (installed via
``pip install -e '.[otel]'``).

Span hierarchy::

    workflow:{name}  (ROOT)
      ├── stage:{name}
      │   ├── agent:{name}
      │   │   ├── llm:{provider}/{model}
      │   │   └── tool:{name}
"""
import logging
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from src.observability.backend import (
    AgentOutputData,
    CollaborationEventData,
    LLMCallData,
    ObservabilityBackend,
    SafetyViolationData,
    ToolCallData,
    WorkflowStartData,
)

logger = logging.getLogger(__name__)

# OTEL attribute key constants
_ATTR_WORKFLOW_ID = "maf.workflow.id"
_ATTR_WORKFLOW_NAME = "maf.workflow.name"
_ATTR_STAGE_ID = "maf.stage.id"
_ATTR_STAGE_NAME = "maf.stage.name"
_ATTR_AGENT_ID = "maf.agent.id"
_ATTR_AGENT_NAME = "maf.agent.name"
_ATTR_PROVIDER = "maf.llm.provider"
_ATTR_MODEL = "maf.llm.model"
_ATTR_TOOL_NAME = "maf.tool.name"
_ATTR_STATUS = "maf.status"
_ATTR_ERROR_MESSAGE = "maf.error.message"
_ATTR_TOKENS_PROMPT = "maf.llm.tokens.prompt"
_ATTR_TOKENS_COMPLETION = "maf.llm.tokens.completion"
_ATTR_LATENCY_MS = "maf.llm.latency_ms"
_ATTR_COST_USD = "maf.cost_usd"
_ATTR_DURATION_S = "maf.duration_seconds"

# Metric name constants
_METRIC_WORKFLOW_COUNT = "maf.workflow.count"
_METRIC_LLM_CALL_COUNT = "maf.llm.call.count"
_METRIC_LLM_LATENCY = "maf.llm.latency"
_METRIC_TOOL_CALL_COUNT = "maf.tool.call.count"
_METRIC_COST_TOTAL = "maf.cost.total"
_METRIC_TOKENS_TOTAL = "maf.tokens.total"


class OTelBackend(ObservabilityBackend):
    """OTEL tracing + metrics backend for MAF.

    Maintains an active-span registry so that ``track_*_start`` and
    ``track_*_end`` calls (which happen in different stack frames) can
    be correlated to the same OTEL span.
    """

    def __init__(self, service_name: str = "maf") -> None:
        try:
            from opentelemetry import metrics as otel_metrics
            from opentelemetry import trace as otel_trace
        except ImportError as exc:
            raise ImportError(
                "opentelemetry-api is required for OTelBackend. "
                "Install with: pip install -e '.[otel]'"
            ) from exc

        self._tracer = otel_trace.get_tracer(service_name)
        meter = otel_metrics.get_meter(service_name)

        # Counters
        self._workflow_counter = meter.create_counter(
            _METRIC_WORKFLOW_COUNT, description="Workflow executions"
        )
        self._llm_call_counter = meter.create_counter(
            _METRIC_LLM_CALL_COUNT, description="LLM calls"
        )
        self._tool_call_counter = meter.create_counter(
            _METRIC_TOOL_CALL_COUNT, description="Tool calls"
        )

        # Histograms
        self._llm_latency_histogram = meter.create_histogram(
            _METRIC_LLM_LATENCY, unit="ms", description="LLM call latency"
        )
        self._cost_counter = meter.create_counter(
            _METRIC_COST_TOTAL, unit="usd", description="Accumulated cost"
        )
        self._tokens_counter = meter.create_counter(
            _METRIC_TOKENS_TOTAL, description="Accumulated tokens"
        )

        # Active span registry: entity_id → (Span, Context)
        self._active_spans: Dict[str, Tuple[Any, Any]] = {}

    # ---- helpers ----

    def _start_span(
        self, entity_id: str, span_name: str, attributes: Dict[str, Any],
        parent_id: Optional[str] = None,
    ) -> None:
        """Start a span and register it."""
        from opentelemetry import context as otel_context

        parent_ctx = None
        if parent_id and parent_id in self._active_spans:
            _, parent_ctx = self._active_spans[parent_id]

        if parent_ctx is not None:
            ctx = otel_context.attach(parent_ctx)  # noqa: F841
        span = self._tracer.start_span(span_name, attributes=attributes)
        span_ctx = otel_trace.set_span_in_context(span)
        self._active_spans[entity_id] = (span, span_ctx)

    def _end_span(
        self, entity_id: str, status: str,
        error_message: Optional[str] = None,
    ) -> None:
        """End and deregister a span."""
        entry = self._active_spans.pop(entity_id, None)
        if entry is None:
            return
        span, _ = entry
        try:
            from opentelemetry.trace import StatusCode

            if status in ("completed", "success"):
                span.set_status(StatusCode.OK)
            else:
                span.set_status(StatusCode.ERROR, description=error_message or status)
                if error_message:
                    span.set_attribute(_ATTR_ERROR_MESSAGE, error_message)
            span.set_attribute(_ATTR_STATUS, status)
            span.end()
        except Exception:  # noqa: BLE001 — fire-and-forget
            logger.debug("Failed to end OTEL span for %s", entity_id, exc_info=True)

    # ========== Workflow Tracking ==========

    def track_workflow_start(
        self,
        workflow_id: str,
        workflow_name: str,
        workflow_config: Dict[str, Any],
        start_time: datetime,
        data: Optional[WorkflowStartData] = None,
    ) -> None:
        attrs: Dict[str, Any] = {
            _ATTR_WORKFLOW_ID: workflow_id,
            _ATTR_WORKFLOW_NAME: workflow_name,
        }
        if data:
            if data.environment:
                attrs["maf.environment"] = data.environment
            if data.product_type:
                attrs["maf.product_type"] = data.product_type
        self._start_span(workflow_id, f"workflow:{workflow_name}", attrs)
        self._workflow_counter.add(1, {_ATTR_WORKFLOW_NAME: workflow_name})

    def track_workflow_end(
        self,
        workflow_id: str,
        end_time: datetime,
        status: str,
        error_message: Optional[str] = None,
        error_stack_trace: Optional[str] = None,
    ) -> None:
        self._end_span(workflow_id, status, error_message)

    def update_workflow_metrics(
        self,
        workflow_id: str,
        total_llm_calls: int,
        total_tool_calls: int,
        total_tokens: int,
        total_cost_usd: float,
    ) -> None:
        entry = self._active_spans.get(workflow_id)
        if entry:
            span, _ = entry
            span.set_attribute("maf.workflow.total_tokens", total_tokens)
            span.set_attribute("maf.workflow.total_cost_usd", total_cost_usd)

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
        self._start_span(
            stage_id, f"stage:{stage_name}",
            {_ATTR_STAGE_ID: stage_id, _ATTR_STAGE_NAME: stage_name,
             _ATTR_WORKFLOW_ID: workflow_id},
            parent_id=workflow_id,
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
        entry = self._active_spans.get(stage_id)
        if entry:
            span, _ = entry
            span.set_attribute("maf.stage.agents_executed", num_agents_executed)
            span.set_attribute("maf.stage.agents_succeeded", num_agents_succeeded)
            span.set_attribute("maf.stage.agents_failed", num_agents_failed)
        self._end_span(stage_id, status, error_message)

    def set_stage_output(self, stage_id: str, output_data: Dict[str, Any]) -> None:
        pass  # Stage output is potentially large — skip in OTEL

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
        self._start_span(
            agent_id, f"agent:{agent_name}",
            {_ATTR_AGENT_ID: agent_id, _ATTR_AGENT_NAME: agent_name,
             _ATTR_STAGE_ID: stage_id},
            parent_id=stage_id,
        )

    def track_agent_end(
        self,
        agent_id: str,
        end_time: datetime,
        status: str,
        error_message: Optional[str] = None,
    ) -> None:
        self._end_span(agent_id, status, error_message)

    def set_agent_output(
        self,
        agent_id: str,
        output_data: Dict[str, Any],
        metrics: Optional[AgentOutputData] = None,
    ) -> None:
        entry = self._active_spans.get(agent_id)
        if entry and metrics:
            span, _ = entry
            if metrics.total_tokens is not None:
                span.set_attribute("maf.agent.total_tokens", metrics.total_tokens)
            if metrics.estimated_cost_usd is not None:
                span.set_attribute("maf.agent.cost_usd", metrics.estimated_cost_usd)
            if metrics.confidence_score is not None:
                span.set_attribute("maf.agent.confidence", metrics.confidence_score)

    # ========== LLM Call Tracking ==========

    def track_llm_call(
        self,
        llm_call_id: str,
        agent_id: str,
        provider: str,
        model: str,
        start_time: datetime,
        data: LLMCallData,
    ) -> None:
        span_name = f"llm:{provider}/{model}"
        attrs: Dict[str, Any] = {
            _ATTR_AGENT_ID: agent_id,
            _ATTR_PROVIDER: provider,
            _ATTR_MODEL: model,
            _ATTR_TOKENS_PROMPT: data.prompt_tokens,
            _ATTR_TOKENS_COMPLETION: data.completion_tokens,
            _ATTR_LATENCY_MS: data.latency_ms,
            _ATTR_COST_USD: data.estimated_cost_usd,
            _ATTR_STATUS: data.status,
        }
        # Leaf span — start and immediately end
        self._start_span(llm_call_id, span_name, attrs, parent_id=agent_id)
        self._end_span(llm_call_id, data.status, data.error_message)

        # Metrics
        self._llm_call_counter.add(1, {_ATTR_PROVIDER: provider, _ATTR_MODEL: model})
        self._llm_latency_histogram.record(
            data.latency_ms, {_ATTR_PROVIDER: provider, _ATTR_MODEL: model}
        )
        total_tokens = data.prompt_tokens + data.completion_tokens
        if total_tokens > 0:
            self._tokens_counter.add(
                total_tokens, {_ATTR_PROVIDER: provider, _ATTR_MODEL: model}
            )
        if data.estimated_cost_usd > 0:
            self._cost_counter.add(
                data.estimated_cost_usd, {_ATTR_PROVIDER: provider, _ATTR_MODEL: model}
            )

    # ========== Tool Call Tracking ==========

    def track_tool_call(
        self,
        tool_execution_id: str,
        agent_id: str,
        tool_name: str,
        start_time: datetime,
        data: ToolCallData,
    ) -> None:
        attrs: Dict[str, Any] = {
            _ATTR_AGENT_ID: agent_id,
            _ATTR_TOOL_NAME: tool_name,
            _ATTR_DURATION_S: data.duration_seconds,
            _ATTR_STATUS: data.status,
        }
        # Leaf span
        self._start_span(tool_execution_id, f"tool:{tool_name}", attrs, parent_id=agent_id)
        self._end_span(tool_execution_id, data.status, data.error_message)

        self._tool_call_counter.add(1, {_ATTR_TOOL_NAME: tool_name})

    # ========== Safety / Collaboration ==========

    def track_safety_violation(
        self,
        violation_severity: str,
        violation_message: str,
        policy_name: str,
        data: Optional[SafetyViolationData] = None,
    ) -> None:
        # Record as a standalone span event on the current span (if any)
        pass  # Safety violations stored in SQL; OTEL just uses spans

    def track_collaboration_event(
        self,
        stage_id: str,
        event_type: str,
        agents_involved: List[str],
        data: Optional[CollaborationEventData] = None,
    ) -> str:
        return ""  # Collaboration tracked in SQL

    # ========== Context / Maintenance ==========

    @contextmanager
    def get_session_context(self) -> Any:
        yield None

    def cleanup_old_records(
        self, retention_days: int, dry_run: bool = False
    ) -> Dict[str, int]:
        return {}  # OTEL has its own retention via exporters

    def get_stats(self) -> Dict[str, Any]:
        return {
            "backend_type": "otel",
            "active_spans": len(self._active_spans),
        }


# Lazy import guard — only imported when OTEL is configured
try:
    from opentelemetry import trace as otel_trace  # noqa: F811
except ImportError:
    otel_trace = None  # type: ignore[assignment]
