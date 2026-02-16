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
_METRIC_LLM_ITERATION = "maf.llm.iteration"
_METRIC_CACHE_HIT = "maf.cache.hit"
_METRIC_CACHE_MISS = "maf.cache.miss"
_METRIC_RETRY_COUNT = "maf.retry.count"
_METRIC_CB_STATE_CHANGE = "maf.circuit_breaker.state_change"
_METRIC_DIALOGUE_CONVERGENCE = "maf.dialogue.convergence_speed"
_METRIC_STAGE_COST = "maf.stage.cost_usd"

# Resilience event type prefixes
_RESILIENCE_RETRY = "resilience_retry"
_RESILIENCE_CB = "resilience_circuit_breaker"

# Dialogue/cost event types
_EVENT_DIALOGUE_METRICS = "dialogue_round_metrics"
_EVENT_QUALITY_GATE_DETAIL = "quality_gate_violation_detail"
_EVENT_COST_SUMMARY = "cost_summary"


def _init_metrics(backend: Any, meter: Any) -> None:
    """Create all OTEL counters and histograms on the backend."""
    backend._workflow_counter = meter.create_counter(
        _METRIC_WORKFLOW_COUNT, description="Workflow executions",
    )
    backend._llm_call_counter = meter.create_counter(
        _METRIC_LLM_CALL_COUNT, description="LLM calls",
    )
    backend._tool_call_counter = meter.create_counter(
        _METRIC_TOOL_CALL_COUNT, description="Tool calls",
    )
    backend._llm_latency_histogram = meter.create_histogram(
        _METRIC_LLM_LATENCY, unit="ms", description="LLM call latency",
    )
    backend._cost_counter = meter.create_counter(
        _METRIC_COST_TOTAL, unit="usd", description="Accumulated cost",
    )
    backend._tokens_counter = meter.create_counter(
        _METRIC_TOKENS_TOTAL, description="Accumulated tokens",
    )
    backend._llm_iteration_counter = meter.create_counter(
        _METRIC_LLM_ITERATION, description="LLM loop iterations",
    )
    backend._cache_hit_counter = meter.create_counter(
        _METRIC_CACHE_HIT, description="Cache hits",
    )
    backend._cache_miss_counter = meter.create_counter(
        _METRIC_CACHE_MISS, description="Cache misses",
    )
    backend._retry_counter = meter.create_counter(
        _METRIC_RETRY_COUNT, description="Agent retry attempts",
    )
    backend._cb_state_change_counter = meter.create_counter(
        _METRIC_CB_STATE_CHANGE, description="Circuit breaker state changes",
    )
    backend._dialogue_convergence_histogram = meter.create_histogram(
        _METRIC_DIALOGUE_CONVERGENCE,
        description="Dialogue convergence speed per round",
    )
    backend._stage_cost_counter = meter.create_counter(
        _METRIC_STAGE_COST, unit="usd", description="Per-stage cost",
    )


def _start_span(
    backend: Any,
    entity_id: str,
    span_name: str,
    attributes: Dict[str, Any],
    parent_id: Optional[str] = None,
) -> None:
    """Start a span and register it in the backend's active spans."""
    from opentelemetry import context as otel_context

    parent_ctx = None
    if parent_id and parent_id in backend._active_spans:
        _, parent_ctx = backend._active_spans[parent_id]

    if parent_ctx is not None:
        ctx = otel_context.attach(parent_ctx)  # noqa: F841
    span = backend._tracer.start_span(span_name, attributes=attributes)
    span_ctx = otel_trace.set_span_in_context(span)
    backend._active_spans[entity_id] = (span, span_ctx)


def _end_span(
    backend: Any,
    entity_id: str,
    status: str,
    error_message: Optional[str] = None,
) -> None:
    """End and deregister a span from the backend."""
    entry = backend._active_spans.pop(entity_id, None)
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


class OTelBackend(ObservabilityBackend):
    """OTEL tracing + metrics backend for MAF.

    Maintains an active-span registry so that ``track_*_start`` and
    ``track_*_end`` calls (which happen in different stack frames) can
    be correlated to the same OTEL span.
    """

    _tracer: Any
    _workflow_counter: Any
    _llm_call_counter: Any
    _tool_call_counter: Any
    _llm_latency_histogram: Any
    _cost_counter: Any
    _tokens_counter: Any
    _llm_iteration_counter: Any
    _cache_hit_counter: Any
    _cache_miss_counter: Any
    _retry_counter: Any
    _cb_state_change_counter: Any
    _dialogue_convergence_histogram: Any
    _stage_cost_counter: Any

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
        _init_metrics(self, meter)

        # Active span registry: entity_id → (Span, Context)
        self._active_spans: Dict[str, Tuple[Any, Any]] = {}

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
        _start_span(self,workflow_id, f"workflow:{workflow_name}", attrs)
        self._workflow_counter.add(1, {_ATTR_WORKFLOW_NAME: workflow_name})

    def track_workflow_end(
        self,
        workflow_id: str,
        end_time: datetime,
        status: str,
        error_message: Optional[str] = None,
        error_stack_trace: Optional[str] = None,
    ) -> None:
        _end_span(self,workflow_id, status, error_message)

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
        _start_span(self,
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
        _end_span(self,stage_id, status, error_message)

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
        _start_span(self,
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
        _end_span(self,agent_id, status, error_message)

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
        _start_span(self,llm_call_id, span_name, attrs, parent_id=agent_id)
        _end_span(self,llm_call_id, data.status, data.error_message)

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
        _start_span(self,tool_execution_id, f"tool:{tool_name}", attrs, parent_id=agent_id)
        _end_span(self,tool_execution_id, data.status, data.error_message)

        self._tool_call_counter.add(1, {_ATTR_TOOL_NAME: tool_name})

    # ========== LLM Iteration / Cache ==========

    def track_llm_iteration(
        self,
        agent_name: str,
        iteration_number: int,
        tool_calls: int = 0,
        tokens: int = 0,
    ) -> None:
        """Record an LLM loop iteration metric."""
        self._llm_iteration_counter.add(
            1, {_ATTR_AGENT_NAME: agent_name, "maf.iteration": iteration_number},
        )
        if tokens > 0:
            self._tokens_counter.add(tokens, {_ATTR_AGENT_NAME: agent_name})

    def track_cache_event(self, event_type: str) -> None:
        """Record a cache hit or miss metric."""
        if event_type == "hit":
            self._cache_hit_counter.add(1)
        elif event_type == "miss":
            self._cache_miss_counter.add(1)

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
        if data is not None and data.event_data is not None:
            _record_event_metrics(self, event_type, data.event_data)
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


def _record_event_metrics(
    backend: Any,
    event_type: str,
    event_data: Dict[str, Any],
) -> None:
    """Record OTEL metrics for collaboration events (module-level)."""
    if event_type == _RESILIENCE_RETRY:
        agent = event_data.get("agent_name", "unknown")
        backend._retry_counter.add(1, {_ATTR_AGENT_NAME: agent})
    elif event_type == _RESILIENCE_CB:
        breaker = event_data.get("breaker_name", "unknown")
        new_state = event_data.get("new_state", "unknown")
        backend._cb_state_change_counter.add(
            1, {"maf.breaker.name": breaker, "maf.breaker.state": new_state},
        )
    elif event_type == _EVENT_DIALOGUE_METRICS:
        speed = event_data.get("convergence_speed")
        if speed is not None:
            stage = event_data.get("stage_name", "unknown")
            backend._dialogue_convergence_histogram.record(
                speed, {_ATTR_STAGE_NAME: stage},
            )
    elif event_type == _EVENT_COST_SUMMARY:
        cost = event_data.get("total_cost_usd", 0.0)
        if cost > 0:
            stage = event_data.get("stage_name", "unknown")
            backend._stage_cost_counter.add(cost, {_ATTR_STAGE_NAME: stage})


# Lazy import guard — only imported when OTEL is configured
try:
    from opentelemetry import trace as otel_trace  # noqa: F811
except ImportError:
    otel_trace = None  # type: ignore[assignment]
