"""OpenTelemetry observability backend.

Maps Temper AI tracker calls to OTEL spans and metrics. Requires the
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
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime
from typing import (
    TYPE_CHECKING,
    Any,
)

from temper_ai.observability.backend import (
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
_ATTR_WORKFLOW_ID = "temper_ai.workflow.id"
_ATTR_WORKFLOW_NAME = "temper_ai.workflow.name"
_ATTR_STAGE_ID = "temper_ai.stage.id"
_ATTR_STAGE_NAME = "temper_ai.stage.name"
_ATTR_AGENT_ID = "temper_ai.agent.id"
_ATTR_AGENT_NAME = "temper_ai.agent.name"
_ATTR_PROVIDER = "temper_ai.llm.provider"
_ATTR_MODEL = "temper_ai.llm.model"
_ATTR_TOOL_NAME = "temper_ai.tool.name"
_ATTR_STATUS = "temper_ai.status"
_ATTR_ERROR_MESSAGE = "temper_ai.error.message"
_ATTR_TOKENS_PROMPT = "temper_ai.llm.tokens.prompt"
_ATTR_TOKENS_COMPLETION = "temper_ai.llm.tokens.completion"
_ATTR_LATENCY_MS = "temper_ai.llm.latency_ms"
_ATTR_COST_USD = "temper_ai.cost_usd"
_ATTR_DURATION_S = "temper_ai.duration_seconds"

# Metric name constants
_METRIC_WORKFLOW_COUNT = "temper_ai.workflow.count"
_METRIC_LLM_CALL_COUNT = "temper_ai.llm.call.count"
_METRIC_LLM_LATENCY = "temper_ai.llm.latency"
_METRIC_TOOL_CALL_COUNT = "temper_ai.tool.call.count"
_METRIC_COST_TOTAL = "temper_ai.cost.total"
_METRIC_TOKENS_TOTAL = "temper_ai.tokens.total"
_METRIC_LLM_ITERATION = "temper_ai.llm.iteration"
_METRIC_CACHE_HIT = "temper_ai.cache.hit"
_METRIC_CACHE_MISS = "temper_ai.cache.miss"
_METRIC_RETRY_COUNT = "temper_ai.retry.count"
_METRIC_CB_STATE_CHANGE = "temper_ai.circuit_breaker.state_change"
_METRIC_DIALOGUE_CONVERGENCE = "temper_ai.dialogue.convergence_speed"
_METRIC_STAGE_COST = "temper_ai.stage.cost_usd"
_METRIC_FAILOVER_COUNT = "temper_ai.failover.count"

# Resilience event type prefixes
_RESILIENCE_RETRY = "resilience_retry"
_RESILIENCE_CB = "resilience_circuit_breaker"
_RESILIENCE_FAILOVER = "resilience_failover_provider"

# Dialogue/cost event types
_EVENT_DIALOGUE_METRICS = "dialogue_round_metrics"
_EVENT_QUALITY_GATE_DETAIL = "quality_gate_violation_detail"
_EVENT_COST_SUMMARY = "cost_summary"


# Span lifecycle constants
SPAN_TTL_SECONDS = 3600  # 1 hour
MAX_ACTIVE_SPANS = 10000  # Maximum concurrent spans
CLEANUP_THRESHOLD = 100  # Run cleanup when span count exceeds this


def _otel_safe_value(value: Any) -> Any:
    """Convert value to OTEL-safe attribute type (str, int, float, bool)."""
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _add_event(
    backend: Any,
    entity_id: str,
    event_name: str,
    attributes: dict[str, Any] | None = None,
) -> None:
    """Add a log event to an active span (fire-and-forget)."""
    entry = backend._active_spans.get(entity_id)
    if entry is None:
        return
    span, _, _ = entry
    try:
        clean: dict[str, Any] = {}
        if attributes:
            for k, v in attributes.items():
                if v is not None:
                    clean[k] = _otel_safe_value(v)
        span.add_event(event_name, attributes=clean)
    except Exception:  # noqa: BLE001 — fire-and-forget
        logger.debug("Failed to add event %s to span %s", event_name, entity_id)


def _init_core_metrics(backend: Any, meter: Any) -> None:  # noqa: long
    """Create core workflow/LLM/tool counters and histograms."""
    backend._workflow_counter = meter.create_counter(
        _METRIC_WORKFLOW_COUNT, description="Workflow executions"
    )
    backend._llm_call_counter = meter.create_counter(
        _METRIC_LLM_CALL_COUNT, description="LLM calls"
    )
    backend._tool_call_counter = meter.create_counter(
        _METRIC_TOOL_CALL_COUNT, description="Tool calls"
    )
    backend._llm_latency_histogram = meter.create_histogram(
        _METRIC_LLM_LATENCY, unit="ms", description="LLM call latency"
    )
    backend._cost_counter = meter.create_counter(
        _METRIC_COST_TOTAL, unit="usd", description="Accumulated cost"
    )
    backend._tokens_counter = meter.create_counter(
        _METRIC_TOKENS_TOTAL, description="Accumulated tokens"
    )
    backend._llm_iteration_counter = meter.create_counter(
        _METRIC_LLM_ITERATION, description="LLM loop iterations"
    )


def _init_resilience_metrics(backend: Any, meter: Any) -> None:
    """Create cache, retry, circuit-breaker, and failover counters."""
    backend._cache_hit_counter = meter.create_counter(
        _METRIC_CACHE_HIT, description="Cache hits"
    )
    backend._cache_miss_counter = meter.create_counter(
        _METRIC_CACHE_MISS, description="Cache misses"
    )
    backend._retry_counter = meter.create_counter(
        _METRIC_RETRY_COUNT, description="Agent retry attempts"
    )
    backend._cb_state_change_counter = meter.create_counter(
        _METRIC_CB_STATE_CHANGE, description="Circuit breaker state changes"
    )
    backend._dialogue_convergence_histogram = meter.create_histogram(
        _METRIC_DIALOGUE_CONVERGENCE, description="Dialogue convergence speed per round"
    )
    backend._stage_cost_counter = meter.create_counter(
        _METRIC_STAGE_COST, unit="usd", description="Per-stage cost"
    )
    backend._failover_counter = meter.create_counter(
        _METRIC_FAILOVER_COUNT, description="Provider failover events"
    )


def _init_metrics(backend: Any, meter: Any) -> None:
    """Create all OTEL counters and histograms on the backend."""
    _init_core_metrics(backend, meter)
    _init_resilience_metrics(backend, meter)


def _start_span(
    backend: Any,
    entity_id: str,
    span_name: str,
    attributes: dict[str, Any],
    parent_id: str | None = None,
) -> None:
    """Start a span and register it in the backend's active spans."""
    from opentelemetry import context as otel_context

    parent_ctx = None
    if parent_id and parent_id in backend._active_spans:
        _, parent_ctx, _ = backend._active_spans[parent_id]

    if parent_ctx is not None:
        ctx = otel_context.attach(parent_ctx)  # noqa: F841
    span = backend._tracer.start_span(span_name, attributes=attributes)
    span_ctx = otel_trace.set_span_in_context(span)
    backend._active_spans[entity_id] = (span, span_ctx, time.monotonic())

    # Amortized cleanup
    if len(backend._active_spans) > CLEANUP_THRESHOLD:
        _cleanup_stale_spans(backend, SPAN_TTL_SECONDS, MAX_ACTIVE_SPANS)


def _end_span(
    backend: Any,
    entity_id: str,
    status: str,
    error_message: str | None = None,
) -> None:
    """End and deregister a span from the backend."""
    entry = backend._active_spans.pop(entity_id, None)
    if entry is None:
        return
    span, _, _ = entry
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


class _OTelAsyncMixin:
    """Mixin containing async method overrides for OTelBackend.

    All async methods delegate to sync counterparts since OTEL operations
    are in-memory and don't require I/O.
    """

    if TYPE_CHECKING:
        # Sync methods resolved at runtime from OTelBackend via MRO
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

    async def atrack_workflow_start(
        self,
        workflow_id: str,
        workflow_name: str,
        workflow_config: dict[str, Any],
        start_time: datetime,
        data: WorkflowStartData | None = None,
    ) -> None:
        """Async override: delegate to sync (in-memory, no I/O)."""
        self.track_workflow_start(
            workflow_id, workflow_name, workflow_config, start_time, data
        )

    async def atrack_workflow_end(
        self,
        workflow_id: str,
        end_time: datetime,
        status: str,
        error_message: str | None = None,
        error_stack_trace: str | None = None,
    ) -> None:
        """Async override: delegate to sync (in-memory, no I/O)."""
        self.track_workflow_end(
            workflow_id, end_time, status, error_message, error_stack_trace
        )

    async def aupdate_workflow_metrics(
        self,
        workflow_id: str,
        total_llm_calls: int,
        total_tool_calls: int,
        total_tokens: int,
        total_cost_usd: float,
    ) -> None:
        """Async override: delegate to sync (in-memory, no I/O)."""
        self.update_workflow_metrics(
            workflow_id, total_llm_calls, total_tool_calls, total_tokens, total_cost_usd
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
        """Async override: delegate to sync (in-memory, no I/O)."""
        self.track_stage_start(
            stage_id, workflow_id, stage_name, stage_config, start_time, input_data
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
        """Async override: delegate to sync (in-memory, no I/O)."""
        self.track_stage_end(
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
        """Async override: delegate to sync (in-memory, no I/O)."""
        self.set_stage_output(stage_id, output_data, output_lineage)

    async def atrack_agent_start(
        self,
        agent_id: str,
        stage_id: str,
        agent_name: str,
        agent_config: dict[str, Any],
        start_time: datetime,
        input_data: dict[str, Any] | None = None,
    ) -> None:
        """Async override: delegate to sync (in-memory, no I/O)."""
        self.track_agent_start(
            agent_id, stage_id, agent_name, agent_config, start_time, input_data
        )

    async def atrack_agent_end(
        self,
        agent_id: str,
        end_time: datetime,
        status: str,
        error_message: str | None = None,
    ) -> None:
        """Async override: delegate to sync (in-memory, no I/O)."""
        self.track_agent_end(agent_id, end_time, status, error_message)

    async def aset_agent_output(
        self,
        agent_id: str,
        output_data: dict[str, Any],
        metrics: AgentOutputData | None = None,
    ) -> None:
        """Async override: delegate to sync (in-memory, no I/O)."""
        self.set_agent_output(agent_id, output_data, metrics)

    async def atrack_llm_call(
        self,
        llm_call_id: str,
        agent_id: str,
        provider: str,
        model: str,
        start_time: datetime,
        data: LLMCallData,
    ) -> None:
        """Async override: delegate to sync (in-memory, no I/O)."""
        self.track_llm_call(llm_call_id, agent_id, provider, model, start_time, data)

    async def atrack_tool_call(
        self,
        tool_execution_id: str,
        agent_id: str,
        tool_name: str,
        start_time: datetime,
        data: ToolCallData,
    ) -> None:
        """Async override: delegate to sync (in-memory, no I/O)."""
        self.track_tool_call(tool_execution_id, agent_id, tool_name, start_time, data)

    async def atrack_safety_violation(
        self,
        violation_severity: str,
        violation_message: str,
        policy_name: str,
        data: SafetyViolationData | None = None,
    ) -> None:
        """Async override: delegate to sync (in-memory, no I/O)."""
        self.track_safety_violation(
            violation_severity, violation_message, policy_name, data
        )

    async def atrack_collaboration_event(
        self,
        stage_id: str,
        event_type: str,
        agents_involved: list[str],
        data: CollaborationEventData | None = None,
    ) -> str:
        """Async override: delegate to sync (in-memory, no I/O)."""
        return self.track_collaboration_event(
            stage_id, event_type, agents_involved, data
        )

    @asynccontextmanager
    async def aget_session_context(self) -> AsyncIterator[Any]:
        """Async session context (in-memory, no I/O)."""
        yield None


class OTelBackend(_OTelAsyncMixin, ObservabilityBackend):
    """OTEL tracing + metrics backend for Temper AI.

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
    _failover_counter: Any

    def __init__(self, service_name: str = "temper-ai") -> None:
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

        # Active span registry: entity_id → (Span, Context, created_at_monotonic)
        self._active_spans: dict[str, tuple[Any, Any, float]] = {}

    # ========== Workflow Tracking ==========

    def track_workflow_start(  # noqa: C901  # noqa: radon
        self,
        workflow_id: str,
        workflow_name: str,
        workflow_config: dict[str, Any],
        start_time: datetime,
        data: WorkflowStartData | None = None,
        **kwargs: Any,
    ) -> None:
        """Record workflow execution start as an OTEL span."""
        if data is None and kwargs:
            data = WorkflowStartData(**kwargs)
        attrs: dict[str, Any] = {
            _ATTR_WORKFLOW_ID: workflow_id,
            _ATTR_WORKFLOW_NAME: workflow_name,
        }
        if data:
            if data.environment:
                attrs["temper_ai.environment"] = data.environment
            if data.product_type:
                attrs["temper_ai.product_type"] = data.product_type
            if data.cost_attribution_tags:
                for key, value in data.cost_attribution_tags.items():
                    attrs[f"temper_ai.cost.tag.{key}"] = value
        _start_span(self, workflow_id, f"workflow:{workflow_name}", attrs)
        self._workflow_counter.add(1, {_ATTR_WORKFLOW_NAME: workflow_name})
        wf_inner = workflow_config.get("workflow", workflow_config)
        stage_count = len(wf_inner.get("stages", []))
        event_attrs: dict[str, Any] = {"stages": stage_count}
        if data:
            if data.environment:
                event_attrs["environment"] = data.environment
            if data.trigger_type:
                event_attrs["trigger"] = data.trigger_type
            if data.tags:
                event_attrs["tags"] = ", ".join(data.tags)
        _add_event(self, workflow_id, "workflow.started", event_attrs)

    def track_workflow_end(
        self,
        workflow_id: str,
        end_time: datetime,
        status: str,
        error_message: str | None = None,
        error_stack_trace: str | None = None,
    ) -> None:
        """Record workflow execution completion and end the span."""
        event_attrs: dict[str, Any] = {"status": status}
        if error_message:
            event_attrs["error"] = error_message[:256]  # noqa
        _add_event(self, workflow_id, f"workflow.{status}", event_attrs)
        _end_span(self, workflow_id, status, error_message)

    def update_workflow_metrics(
        self,
        workflow_id: str,
        total_llm_calls: int,
        total_tool_calls: int,
        total_tokens: int,
        total_cost_usd: float,
    ) -> None:
        """Update aggregated workflow metrics on the active span."""
        entry = self._active_spans.get(workflow_id)
        if entry:
            span, _, _ = entry
            span.set_attribute("temper_ai.workflow.total_tokens", total_tokens)
            span.set_attribute("temper_ai.workflow.total_cost_usd", total_cost_usd)
        _add_event(
            self,
            workflow_id,
            "workflow.metrics",
            {
                "llm_calls": total_llm_calls,
                "tool_calls": total_tool_calls,
                "tokens": total_tokens,
                "cost_usd": total_cost_usd,
            },
        )

    # ========== Stage Tracking ==========

    def track_stage_start(
        self,
        stage_id: str,
        workflow_id: str,
        stage_name: str,
        stage_config: dict[str, Any],
        start_time: datetime,
        input_data: dict[str, Any] | None = None,
    ) -> None:
        """Record stage execution start as a child span of the workflow."""
        _start_span(
            self,
            stage_id,
            f"stage:{stage_name}",
            {
                _ATTR_STAGE_ID: stage_id,
                _ATTR_STAGE_NAME: stage_name,
                _ATTR_WORKFLOW_ID: workflow_id,
            },
            parent_id=workflow_id,
        )
        inner = stage_config.get("stage", stage_config)
        agents = inner.get("agents", [])
        execution = inner.get("execution", {})
        mode = (
            execution.get("agent_mode", "sequential")
            if isinstance(execution, dict)
            else "sequential"
        )
        event_attrs: dict[str, Any] = {
            "agent_count": len(agents),
            "execution_mode": mode,
        }
        if agents:
            event_attrs["agents"] = ", ".join(str(a) for a in agents[:10])
        _add_event(self, stage_id, "stage.started", event_attrs)

    def track_stage_end(
        self,
        stage_id: str,
        end_time: datetime,
        status: str,
        error_message: str | None = None,
        num_agents_executed: int = 0,
        num_agents_succeeded: int = 0,
        num_agents_failed: int = 0,
    ) -> None:
        """Record stage execution completion and end the span."""
        entry = self._active_spans.get(stage_id)
        if entry:
            span, _, _ = entry
            span.set_attribute("temper_ai.stage.agents_executed", num_agents_executed)
            span.set_attribute("temper_ai.stage.agents_succeeded", num_agents_succeeded)
            span.set_attribute("temper_ai.stage.agents_failed", num_agents_failed)
        event_attrs: dict[str, Any] = {
            "agents_executed": num_agents_executed,
            "agents_succeeded": num_agents_succeeded,
            "agents_failed": num_agents_failed,
        }
        if error_message:
            event_attrs["error"] = error_message[:256]  # noqa
        _add_event(self, stage_id, f"stage.{status}", event_attrs)
        _end_span(self, stage_id, status, error_message)

    def set_stage_output(
        self,
        stage_id: str,
        output_data: dict[str, Any],
        output_lineage: dict[str, Any] | None = None,
    ) -> None:
        """Set stage output (no-op; stage output too large for OTEL spans)."""
        pass  # Stage output is potentially large — skip in OTEL

    # ========== Agent Tracking ==========

    def track_agent_start(
        self,
        agent_id: str,
        stage_id: str,
        agent_name: str,
        agent_config: dict[str, Any],
        start_time: datetime,
        input_data: dict[str, Any] | None = None,
    ) -> None:
        """Record agent execution start as a child span of the stage."""
        _start_span(
            self,
            agent_id,
            f"agent:{agent_name}",
            {
                _ATTR_AGENT_ID: agent_id,
                _ATTR_AGENT_NAME: agent_name,
                _ATTR_STAGE_ID: stage_id,
            },
            parent_id=stage_id,
        )
        inner = agent_config.get("agent", agent_config)
        inference = inner.get("inference", {})
        event_attrs: dict[str, Any] = {}
        if inference.get("model"):
            event_attrs["model"] = inference["model"]
        if inference.get("provider"):
            event_attrs["provider"] = inference["provider"]
        if inner.get("type"):
            event_attrs["type"] = inner["type"]
        _add_event(self, agent_id, "agent.started", event_attrs)

    def track_agent_end(
        self,
        agent_id: str,
        end_time: datetime,
        status: str,
        error_message: str | None = None,
    ) -> None:
        """Record agent execution completion and end the span."""
        event_attrs: dict[str, Any] = {"status": status}
        if error_message:
            event_attrs["error"] = error_message[:256]  # noqa
        _add_event(self, agent_id, f"agent.{status}", event_attrs)
        _end_span(self, agent_id, status, error_message)

    def set_agent_output(
        self,
        agent_id: str,
        output_data: dict[str, Any] | None = None,
        metrics: AgentOutputData | None = None,
        **kwargs: Any,
    ) -> None:
        """Set agent output metrics as span attributes and events."""
        entry = self._active_spans.get(agent_id)
        if entry and metrics:
            span, _, _ = entry
            if metrics.total_tokens is not None:
                span.set_attribute("temper_ai.agent.total_tokens", metrics.total_tokens)
            if metrics.estimated_cost_usd is not None:
                span.set_attribute(
                    "temper_ai.agent.cost_usd", metrics.estimated_cost_usd
                )
            if metrics.confidence_score is not None:
                span.set_attribute(
                    "temper_ai.agent.confidence", metrics.confidence_score
                )
            event_attrs: dict[str, Any] = {}
            if metrics.total_tokens is not None:
                event_attrs["tokens"] = metrics.total_tokens
            if metrics.estimated_cost_usd is not None:
                event_attrs["cost_usd"] = metrics.estimated_cost_usd
            if metrics.confidence_score is not None:
                event_attrs["confidence"] = metrics.confidence_score
            if metrics.num_llm_calls is not None:
                event_attrs["llm_calls"] = metrics.num_llm_calls
            _add_event(self, agent_id, "agent.output", event_attrs)

    # ========== LLM Call Tracking ==========

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
        """Record an LLM call as a leaf span with token and cost metrics."""
        if data is None and kwargs:
            data = LLMCallData(**kwargs)
        if data is None:
            return
        span_name = f"llm:{provider}/{model}"
        attrs: dict[str, Any] = {
            _ATTR_AGENT_ID: agent_id,
            _ATTR_PROVIDER: provider,
            _ATTR_MODEL: model,
            _ATTR_TOKENS_PROMPT: data.prompt_tokens,
            _ATTR_TOKENS_COMPLETION: data.completion_tokens,
            _ATTR_LATENCY_MS: data.latency_ms,
            _ATTR_COST_USD: data.estimated_cost_usd,
            _ATTR_STATUS: data.status,
        }
        # Failover tracking
        if data.failover_from_provider:
            attrs["temper_ai.llm.failover_from"] = data.failover_from_provider
        if data.failover_sequence:
            attrs["temper_ai.llm.failover_count"] = len(data.failover_sequence)
        # Prompt versioning
        if data.prompt_template_hash:
            attrs["temper_ai.llm.prompt.template_hash"] = data.prompt_template_hash
        if data.prompt_template_source:
            attrs["temper_ai.llm.prompt.template_source"] = data.prompt_template_source

        # Leaf span — start and immediately end
        _start_span(self, llm_call_id, span_name, attrs, parent_id=agent_id)
        _end_span(self, llm_call_id, data.status, data.error_message)

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
        start_time: datetime | None = None,
        data: ToolCallData | None = None,
        **kwargs: Any,
    ) -> None:
        """Record a tool call as a leaf span with duration metrics."""
        if data is None and kwargs:
            data = ToolCallData(**kwargs)
        if data is None:
            return
        attrs: dict[str, Any] = {
            _ATTR_AGENT_ID: agent_id,
            _ATTR_TOOL_NAME: tool_name,
            _ATTR_DURATION_S: data.duration_seconds,
            _ATTR_STATUS: data.status,
        }
        # Leaf span
        _start_span(
            self, tool_execution_id, f"tool:{tool_name}", attrs, parent_id=agent_id
        )
        _end_span(self, tool_execution_id, data.status, data.error_message)

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
            1,
            {_ATTR_AGENT_NAME: agent_name, "temper_ai.iteration": iteration_number},
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
        data: SafetyViolationData | None = None,
        **kwargs: Any,
    ) -> None:
        """Record a safety violation as a span event on the relevant entity."""
        entity_id = None
        if data:
            entity_id = data.agent_id or data.stage_id or data.workflow_id
        if entity_id:
            _add_event(
                self,
                entity_id,
                "safety.violation",
                {
                    "severity": violation_severity,
                    "policy": policy_name,
                    "message": violation_message[:256],  # noqa
                },
            )

    def track_collaboration_event(
        self,
        stage_id: str,
        event_type: str,
        agents_involved: list[str] | None = None,
        data: CollaborationEventData | None = None,
        **kwargs: Any,
    ) -> str:
        """Record a collaboration event as a span event with metrics."""
        event_attrs: dict[str, Any] = {
            "agents": ", ".join(agents_involved or []),
        }
        if data:
            if data.round_number is not None:
                event_attrs["round"] = data.round_number
            if data.resolution_strategy:
                event_attrs["strategy"] = data.resolution_strategy
            if data.outcome:
                event_attrs["outcome"] = data.outcome
            if data.confidence_score is not None:
                event_attrs["confidence"] = data.confidence_score
        _add_event(self, stage_id, f"collaboration.{event_type}", event_attrs)
        if data is not None and data.event_data is not None:
            _record_event_metrics(self, event_type, data.event_data)
        return ""

    # ========== Context / Maintenance ==========

    @contextmanager
    def get_session_context(self) -> Any:
        """Return a no-op context manager (OTEL has no session concept)."""
        yield None

    def cleanup_old_records(
        self, retention_days: int, dry_run: bool = False
    ) -> dict[str, int]:
        """Return empty dict (OTEL manages retention via exporters)."""
        return {}  # OTEL has its own retention via exporters

    def get_stats(self) -> dict[str, Any]:
        """Return backend statistics including active span count."""
        return {
            "backend_type": "otel",
            "active_spans": len(self._active_spans),
        }


def _cleanup_stale_spans(backend: Any, ttl: float, max_spans: int) -> int:
    """Remove stale spans by TTL and capacity. Returns number cleaned."""
    now = time.monotonic()
    cleaned = 0

    # Phase 1: TTL eviction
    expired = [
        eid
        for eid, (_, _, created) in backend._active_spans.items()
        if now - created > ttl
    ]
    for eid in expired:
        span, _, _ = backend._active_spans.pop(eid)
        try:
            from opentelemetry.trace import StatusCode

            span.set_status(StatusCode.ERROR, description="Span TTL exceeded")
            span.set_attribute(_ATTR_STATUS, "ttl_expired")
            span.end()
        except Exception:  # noqa: BLE001
            pass
        cleaned += 1

    # Phase 2: Capacity eviction (oldest first)
    if len(backend._active_spans) > max_spans:
        sorted_spans = sorted(
            backend._active_spans.items(),
            key=lambda x: x[1][2],
        )
        excess = len(backend._active_spans) - max_spans
        for eid, (span, _, _) in sorted_spans[:excess]:
            del backend._active_spans[eid]
            try:
                from opentelemetry.trace import StatusCode

                span.set_status(
                    StatusCode.ERROR,
                    description="Span capacity exceeded",
                )
                span.end()
            except Exception:  # noqa: BLE001
                pass
            cleaned += 1

    if cleaned > 0:
        logger.info("Cleaned %d stale OTEL spans", cleaned)
    return cleaned


def _record_event_metrics(
    backend: Any,
    event_type: str,
    event_data: dict[str, Any],
) -> None:
    """Record OTEL metrics for collaboration events (module-level)."""
    if event_type == _RESILIENCE_RETRY:
        agent = event_data.get("agent_name", "unknown")
        backend._retry_counter.add(1, {_ATTR_AGENT_NAME: agent})
    elif event_type == _RESILIENCE_CB:
        breaker = event_data.get("breaker_name", "unknown")
        new_state = event_data.get("new_state", "unknown")
        backend._cb_state_change_counter.add(
            1,
            {"temper_ai.breaker.name": breaker, "temper_ai.breaker.state": new_state},
        )
    elif event_type == _EVENT_DIALOGUE_METRICS:
        speed = event_data.get("convergence_speed")
        if speed is not None:
            stage = event_data.get("stage_name", "unknown")
            backend._dialogue_convergence_histogram.record(
                speed,
                {_ATTR_STAGE_NAME: stage},
            )
    elif event_type == _RESILIENCE_FAILOVER:
        from_provider = event_data.get("from_provider", "unknown")
        to_provider = event_data.get("to_provider", "unknown")
        backend._failover_counter.add(
            1,
            {
                "temper_ai.failover.from": from_provider,
                "temper_ai.failover.to": to_provider,
            },
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
