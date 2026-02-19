"""
Execution tracker for observability.

Tracks workflow, stage, agent, LLM, and tool executions in real-time,
writing to pluggable observability backends (SQL, Prometheus, S3, etc.).
"""

import logging
import uuid
from contextlib import asynccontextmanager as _asynccontextmanager, contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, AsyncGenerator, Dict, Generator, List, Optional

if TYPE_CHECKING:
    from temper_ai.observability.metric_aggregator import AgentOutputParams

from temper_ai.shared.core.context import ExecutionContext, current_execution_context
from temper_ai.storage.database.datetime_utils import utcnow
from temper_ai.observability._tracker_helpers import (
    AgentStartParams,
    DecisionTrackingData,
    LLMCallTrackingData,
    ToolCallTrackingData,
    TrackerCollaborationMixin,
    get_stack_trace,
    sanitize_dict,
)
from temper_ai.observability._tracker_helpers import (
    build_extra_metadata as _build_extra_metadata,
)
from temper_ai.observability._tracker_helpers import (
    handle_agent_error as _handle_agent_error,
)
from temper_ai.observability._tracker_helpers import (
    handle_agent_success as _handle_agent_success,
)
from temper_ai.observability._tracker_helpers import (
    handle_stage_error as _handle_stage_error,
)
from temper_ai.observability._tracker_helpers import (
    build_stage_start_data as _build_stage_start_data,
)
from temper_ai.observability._tracker_helpers import (
    handle_stage_success as _handle_stage_success,
)
from temper_ai.observability._tracker_helpers import (
    handle_workflow_error as _handle_workflow_error,
)
from temper_ai.observability._tracker_helpers import (
    handle_workflow_success as _handle_workflow_success,
)
from temper_ai.observability._tracker_helpers import (
    track_agent_start_and_emit as _track_agent_start_and_emit,
)
from temper_ai.observability._tracker_helpers import (
    track_decision_outcome as _track_decision_outcome,
)
from temper_ai.observability._tracker_helpers import (
    track_llm_call as _track_llm_call,
)
from temper_ai.observability._tracker_helpers import (
    track_tool_call as _track_tool_call,
)
from temper_ai.observability.backend import ObservabilityBackend
from temper_ai.observability.collaboration_tracker import CollaborationEventTracker
from temper_ai.observability.constants import MS_PER_SECOND, ObservabilityFields
from temper_ai.observability.decision_tracker import DecisionTracker
from temper_ai.observability.event_bus import ObservabilityEvent, ObservabilityEventBus
from temper_ai.observability.metric_aggregator import MetricAggregator
from temper_ai.observability.sanitization import DataSanitizer, SanitizationConfig
from temper_ai.shared.utils.config_helpers import sanitize_config_for_display

logger = logging.getLogger(__name__)

# Event type identifiers for the observability event bus
_EVENT_WORKFLOW_START = "workflow_start"
_EVENT_STAGE_START = "stage_start"
_EVENT_AGENT_START = "agent_start"
_EVENT_AGENT_OUTPUT = "agent_output"
_EVENT_STAGE_OUTPUT = "stage_output"


@dataclass
class WorkflowTrackingParams:
    """Parameters for tracking workflow execution."""

    workflow_name: str
    workflow_config: Dict[str, Any]
    trigger_type: Optional[str] = None
    trigger_data: Optional[Dict[str, Any]] = None
    optimization_target: Optional[str] = None
    product_type: Optional[str] = None
    environment: Optional[str] = "development"
    tags: Optional[List[str]] = None
    experiment_id: Optional[str] = None
    variant_id: Optional[str] = None
    assignment_strategy: Optional[str] = None
    assignment_context: Optional[Dict[str, Any]] = None
    custom_metrics: Optional[Dict[str, Any]] = None
    cost_attribution_tags: Optional[Dict[str, str]] = None


# Helper functions for backward compatibility
def _resolve_workflow_params(
    workflow_name_or_params: Any = None, workflow_config: Any = None, **kwargs: Any
) -> WorkflowTrackingParams:
    """Resolve workflow tracking parameters from old or new calling conventions."""
    if isinstance(workflow_name_or_params, WorkflowTrackingParams):
        return workflow_name_or_params

    wf_name = (
        workflow_name_or_params
        if workflow_name_or_params is not None
        else kwargs.pop("workflow_name", "")
    )
    wf_config = (
        workflow_config if workflow_config is not None else kwargs.pop("workflow_config", {})
    )
    return WorkflowTrackingParams(workflow_name=wf_name, workflow_config=wf_config, **kwargs)


def _resolve_llm_data(data_or_agent_id: Any = None, **kwargs: Any) -> LLMCallTrackingData:
    """Resolve LLM call tracking data from old or new calling conventions.

    Accepts either a LLMCallTrackingData directly, or keyword arguments
    (provider, model, prompt, response, prompt_tokens, completion_tokens,
    latency_ms, estimated_cost_usd) that are forwarded to the dataclass.
    """
    if isinstance(data_or_agent_id, LLMCallTrackingData):
        return data_or_agent_id

    if data_or_agent_id is not None:
        kwargs.setdefault("agent_id", data_or_agent_id)
    return LLMCallTrackingData(**kwargs)


def _resolve_tool_data(data_or_agent_id: Any = None, **kwargs: Any) -> ToolCallTrackingData:
    """Resolve tool call tracking data from old or new calling conventions.

    Accepts either a ToolCallTrackingData directly, or keyword arguments
    (tool_name, input_params, output_data, duration_seconds) forwarded
    to the dataclass.
    """
    if isinstance(data_or_agent_id, ToolCallTrackingData):
        return data_or_agent_id

    if data_or_agent_id is not None:
        kwargs.setdefault("agent_id", data_or_agent_id)
    return ToolCallTrackingData(**kwargs)


def _record_perf_best_effort(
    perf_tracker: Any,
    operation: str,
    start_time: Any,
    context: Dict[str, Any],
) -> None:
    """Record performance metric. Best-effort: never raises."""
    try:
        latency_ms = (utcnow() - start_time).total_seconds() * MS_PER_SECOND
        perf_tracker.record(operation, latency_ms, context)
    except Exception:  # noqa: BLE001 — perf recording must never break tracking
        logger.debug("Performance recording failed for %s", operation, exc_info=True)


def _start_workflow_tracking(
    backend: Any,
    emit_fn: Any,
    workflow_id: str,
    params: WorkflowTrackingParams,
    start_time: Any,
) -> None:
    """Prepare data and record workflow start with backend + event bus (sync)."""
    sanitized_config, start_data = _prepare_workflow_start(params)
    backend.track_workflow_start(
        workflow_id=workflow_id,
        workflow_name=params.workflow_name,
        workflow_config=sanitized_config,
        start_time=start_time,
        data=start_data,
    )
    emit_fn(_EVENT_WORKFLOW_START, _workflow_start_event_data(workflow_id, params, start_time))


async def _astart_workflow_tracking(
    backend: Any,
    emit_fn: Any,
    workflow_id: str,
    params: WorkflowTrackingParams,
    start_time: Any,
) -> None:
    """Prepare data and record workflow start with backend + event bus (async)."""
    sanitized_config, start_data = _prepare_workflow_start(params)
    await backend.atrack_workflow_start(
        workflow_id=workflow_id,
        workflow_name=params.workflow_name,
        workflow_config=sanitized_config,
        start_time=start_time,
        data=start_data,
    )
    emit_fn(_EVENT_WORKFLOW_START, _workflow_start_event_data(workflow_id, params, start_time))


def _prepare_workflow_start(params: WorkflowTrackingParams) -> tuple:
    """Prepare sanitized config and WorkflowStartData for backend tracking."""
    from temper_ai.observability.backend import WorkflowStartData

    sanitized_config = sanitize_config_for_display(params.workflow_config)
    extra_metadata = _build_extra_metadata(
        params.experiment_id,
        params.variant_id,
        params.assignment_strategy,
        params.assignment_context,
        params.custom_metrics,
    )
    start_data = WorkflowStartData(
        trigger_type=params.trigger_type,
        trigger_data=params.trigger_data,
        optimization_target=params.optimization_target,
        product_type=params.product_type,
        environment=params.environment,
        tags=params.tags,
        extra_metadata=extra_metadata,
        cost_attribution_tags=params.cost_attribution_tags,
    )
    return sanitized_config, start_data


def _workflow_start_event_data(
    workflow_id: str,
    params: WorkflowTrackingParams,
    start_time: Any,
) -> Dict[str, Any]:
    """Build event data dict for workflow start emission."""
    data: Dict[str, Any] = {
        ObservabilityFields.WORKFLOW_ID: workflow_id,
        "workflow_name": params.workflow_name,
        ObservabilityFields.START_TIME: start_time.isoformat(),
        ObservabilityFields.STATUS: "running",
        "environment": params.environment,
        "tags": params.tags,
    }
    # Include sanitized workflow config so frontend can build DAG edges
    sanitized = sanitize_config_for_display(params.workflow_config)
    if sanitized:
        data["workflow_config"] = sanitized
    return data


def _should_skip_sampling(
    sampling_strategy: Any, workflow_id: str, params: WorkflowTrackingParams
) -> bool:
    """Check if workflow should skip backend tracking based on sampling.

    Returns True if the workflow should be skipped (not sampled).
    """
    if sampling_strategy is None:
        return False
    from temper_ai.observability.sampling import SamplingContext

    ctx = SamplingContext(
        workflow_id=workflow_id,
        workflow_name=params.workflow_name,
        environment=params.environment or "",
        tags=params.tags or [],
    )
    decision = sampling_strategy.should_sample(ctx)
    if not decision.sampled:
        logger.debug("Workflow %s not sampled: %s", workflow_id, decision.reason)
        return True
    return False


class _TrackerAsyncMixin:
    """Mixin providing async tracking methods for ExecutionTracker."""

    if TYPE_CHECKING:
        # Attributes resolved at runtime from ExecutionTracker via MRO
        backend: ObservabilityBackend
        alert_manager: Any
        sanitizer: Any
        _event_bus: Optional[ObservabilityEventBus]
        _sampling_strategy: Any
        _performance_tracker: Any

        @property
        def context(self) -> ExecutionContext:
            """Per-thread/task ExecutionContext."""
            ...

        @property
        def _session_stack(self) -> List[Any]: ...

        def _emit_event(self, event_type: str, data: Dict[str, Any]) -> None: ...
        def _collect_agent_metrics(self, agent_id: str) -> None: ...
        def _get_stack_trace(self) -> str: ...
        def _sanitize_dict(self, data: Dict[str, Any]) -> Dict[str, Any]: ...

    @_asynccontextmanager
    async def _aensure_session(self) -> AsyncGenerator[None, None]:
        """Async version of _ensure_session."""
        if self._session_stack:
            yield
        else:
            async with self.backend.aget_session_context() as session:
                self._session_stack.append(session)
                try:
                    yield
                finally:
                    self._session_stack.pop()

    @_asynccontextmanager
    async def atrack_workflow(
        self, workflow_name_or_params: Any = None, workflow_config: Any = None, **kwargs: Any
    ) -> AsyncGenerator[str, None]:
        """Async version of track_workflow."""
        params = _resolve_workflow_params(workflow_name_or_params, workflow_config, **kwargs)
        workflow_id = f"wf-{uuid.uuid4()}"
        self.context.workflow_id = workflow_id
        start_time = utcnow()

        # Sampling: skip backend tracking if not sampled
        if _should_skip_sampling(self._sampling_strategy, workflow_id, params):
            try:
                yield workflow_id
            finally:
                self.context.workflow_id = None
            return

        async with self.backend.aget_session_context() as session:
            self._session_stack.append(session)
            await _astart_workflow_tracking(
                self.backend,
                self._emit_event,
                workflow_id,
                params,
                start_time,
            )
            try:
                yield workflow_id
                _handle_workflow_success(
                    self.backend,
                    self.alert_manager,
                    self._emit_event,
                    workflow_id,
                )
            except Exception as e:
                _handle_workflow_error(
                    self.backend,
                    self._emit_event,
                    self._get_stack_trace,
                    workflow_id,
                    e,
                )
                raise
            finally:
                self._session_stack.pop()
                self.context.workflow_id = None
                _record_perf_best_effort(
                    self._performance_tracker,
                    "workflow_execution",
                    start_time,
                    {"workflow_id": workflow_id},
                )

    @_asynccontextmanager
    async def atrack_stage(
        self,
        stage_name: str,
        stage_config: Dict[str, Any],
        workflow_id: str,
        input_data: Optional[Dict[str, Any]] = None,
    ) -> AsyncGenerator[str, None]:
        """Async version of track_stage."""
        stage_id = str(uuid.uuid4())
        self.context.stage_id = stage_id
        start_time = utcnow()
        sanitized_config = sanitize_config_for_display(stage_config)

        async with self._aensure_session():
            await self.backend.atrack_stage_start(
                stage_id=stage_id,
                workflow_id=workflow_id,
                stage_name=stage_name,
                stage_config=sanitized_config,
                start_time=start_time,
                input_data=input_data,
            )
            self._emit_event(
                _EVENT_STAGE_START,
                _build_stage_start_data(
                    stage_id, workflow_id, stage_name,
                    sanitized_config, start_time,
                ),
            )
            try:
                yield stage_id
                _handle_stage_success(self.backend, self._emit_event, stage_id)
            except Exception as e:
                _handle_stage_error(
                    self.backend,
                    self._emit_event,
                    stage_id,
                    e,
                    workflow_id=self.context.workflow_id,
                    alert_manager=self.alert_manager,
                )
                raise
            finally:
                self.context.stage_id = None
                _record_perf_best_effort(
                    self._performance_tracker,
                    "stage_execution",
                    start_time,
                    {"stage_id": stage_id},
                )

    @_asynccontextmanager
    async def atrack_agent(
        self,
        agent_name: str,
        agent_config: Dict[str, Any],
        stage_id: str,
        input_data: Optional[Dict[str, Any]] = None,
    ) -> AsyncGenerator[str, None]:
        """Async version of track_agent."""
        self.context.agent_id = agent_id = str(uuid.uuid4())
        start_time = utcnow()
        sanitized_config = sanitize_config_for_display(agent_config)
        async with self._aensure_session():
            _track_agent_start_and_emit(
                self.backend,
                self._emit_event,
                AgentStartParams(
                    agent_id=agent_id,
                    stage_id=stage_id,
                    agent_name=agent_name,
                    sanitized_config=sanitized_config,
                    start_time=start_time,
                    input_data=input_data,
                ),
            )
            try:
                yield agent_id
                _handle_agent_success(
                    self.backend,
                    self._emit_event,
                    self._collect_agent_metrics,
                    agent_id,
                )
            except Exception as e:
                _handle_agent_error(
                    self.backend,
                    self._emit_event,
                    agent_id,
                    e,
                    workflow_id=self.context.workflow_id,
                    agent_name=agent_name,
                    alert_manager=self.alert_manager,
                )
                raise
            finally:
                self.context.agent_id = None
                _record_perf_best_effort(
                    self._performance_tracker,
                    "agent_execution",
                    start_time,
                    {"agent_id": agent_id},
                )

    async def atrack_llm_call(
        self,
        data_or_agent_id: Any = None,
        **kwargs: Any,
    ) -> str:
        """Async version of track_llm_call.

        Args:
            data_or_agent_id: LLMCallTrackingData or agent_id string
            **kwargs: Keyword args forwarded to LLMCallTrackingData
                (provider, model, prompt, response, prompt_tokens,
                completion_tokens, latency_ms, estimated_cost_usd)

        Returns:
            LLM call ID
        """
        data = _resolve_llm_data(data_or_agent_id, **kwargs)
        return _track_llm_call(
            sanitizer=self.sanitizer,
            backend=self.backend,
            alert_manager=self.alert_manager,
            data=data,
            event_bus=self._event_bus,
        )

    async def atrack_tool_call(self, data_or_agent_id: Any = None, **kwargs: Any) -> str:
        """Async version of track_tool_call.

        Args:
            data_or_agent_id: ToolCallTrackingData or agent_id string
            **kwargs: Keyword args forwarded to ToolCallTrackingData
                (tool_name, input_params, output_data, duration_seconds)

        Returns:
            Tool execution ID
        """
        data = _resolve_tool_data(data_or_agent_id, **kwargs)
        return _track_tool_call(
            sanitize_dict_fn=self._sanitize_dict,
            backend=self.backend,
            alert_manager=self.alert_manager,
            data=data,
            event_bus=self._event_bus,
        )


class ExecutionTracker(_TrackerAsyncMixin, TrackerCollaborationMixin):
    """
    Tracks execution using pluggable observability backends.

    Provides context managers for tracking different execution levels:
    - workflow, stage, agent, LLM call, tool call
    """

    def __init__(
        self,
        backend: Optional[ObservabilityBackend] = None,
        sanitization_config: Optional[SanitizationConfig] = None,
        metric_registry: Optional[Any] = None,
        alert_manager: Optional[Any] = None,
        event_bus: Optional[ObservabilityEventBus] = None,
        sampling_strategy: Optional[Any] = None,
    ):
        """Initialize execution tracker."""
        self._context_var = current_execution_context
        self._session_stack_var: ContextVar[List[Any]] = ContextVar(
            "session_stack", default=None  # type: ignore[arg-type]
        )
        self._sampling_strategy = sampling_strategy

        if backend is None:
            from temper_ai.observability.backends import SQLObservabilityBackend

            backend = SQLObservabilityBackend()

        self.backend = backend
        self.sanitizer = DataSanitizer(sanitization_config)
        self.metric_registry = metric_registry

        if alert_manager is None:
            from temper_ai.observability.alerting import AlertManager

            alert_manager = AlertManager()
        self.alert_manager = alert_manager

        self._event_bus = event_bus

        # Lazy import to avoid cross-domain fan-out
        from temper_ai.observability.performance import get_performance_tracker

        self._performance_tracker = get_performance_tracker()

        self._decision_tracker = DecisionTracker(sanitize_fn=self._sanitize_dict)
        self._metric_aggregator = MetricAggregator(
            backend=self.backend,
            metric_registry=metric_registry,
        )

        # Wrapper for CollaborationEventTracker's expected signature
        def sanitize_dict_optional(data: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
            """Wrapper that sanitizes dict or returns None if data is None."""
            if data is None:
                return None
            return self._sanitize_dict(data)

        self._collaboration_tracker = CollaborationEventTracker(
            backend=self.backend,
            sanitize_fn=sanitize_dict_optional,
            get_context=lambda: self.context,
        )

    @staticmethod
    def ensure_database(db_url: str) -> None:
        """Ensure observability database is initialized."""
        from temper_ai.storage.database import get_database, init_database

        try:
            get_database()
        except RuntimeError:
            init_database(db_url)

    @property
    def context(self) -> ExecutionContext:
        """Per-thread/task ExecutionContext."""
        ctx = self._context_var.get(None)
        if ctx is None:
            ctx = ExecutionContext()
            self._context_var.set(ctx)
        return ctx

    @context.setter
    def context(self, value: ExecutionContext) -> None:
        """Set the current execution context."""
        self._context_var.set(value)

    @property
    def _session_stack(self) -> List[Any]:
        """Per-task/thread session stack (ContextVar-backed)."""
        stack = self._session_stack_var.get(None)
        if stack is None:
            stack = []
            self._session_stack_var.set(stack)
        return stack

    def _collect_agent_metrics(self, agent_id: str) -> None:
        self._metric_aggregator.collect_agent_metrics(agent_id)

    def _emit_event(self, event_type: str, data: Dict[str, Any]) -> None:
        """Emit an event if event bus is configured."""
        if self._event_bus is None:
            return
        event = ObservabilityEvent(
            event_type=event_type,
            timestamp=utcnow(),
            data=data,
            workflow_id=self.context.workflow_id,
            stage_id=self.context.stage_id,
            agent_id=self.context.agent_id,
        )
        self._event_bus.emit(event)

    @contextmanager
    def track_workflow(
        self, workflow_name_or_params: Any = None, workflow_config: Any = None, **kwargs: Any
    ) -> Generator[str, None, None]:
        """Track workflow execution.

        Args:
            workflow_name_or_params: WorkflowTrackingParams or workflow_name string
            workflow_config: Workflow configuration dict
            **kwargs: Additional parameters for WorkflowTrackingParams

        Yields:
            workflow_id: The generated workflow execution ID
        """
        params = _resolve_workflow_params(workflow_name_or_params, workflow_config, **kwargs)
        workflow_id = f"wf-{uuid.uuid4()}"
        self.context.workflow_id = workflow_id

        start_time = utcnow()

        # Sampling: skip backend tracking if not sampled
        if _should_skip_sampling(self._sampling_strategy, workflow_id, params):
            try:
                yield workflow_id
            finally:
                self.context.workflow_id = None
            return

        with self.backend.get_session_context() as session:
            self._session_stack.append(session)
            _start_workflow_tracking(
                self.backend,
                self._emit_event,
                workflow_id,
                params,
                start_time,
            )
            try:
                yield workflow_id
                _handle_workflow_success(
                    self.backend,
                    self.alert_manager,
                    self._emit_event,
                    workflow_id,
                )
            except Exception as e:
                _handle_workflow_error(
                    self.backend,
                    self._emit_event,
                    self._get_stack_trace,
                    workflow_id,
                    e,
                )
                raise
            finally:
                self._session_stack.pop()
                self.context.workflow_id = None
                _record_perf_best_effort(
                    self._performance_tracker,
                    "workflow_execution",
                    start_time,
                    {"workflow_id": workflow_id},
                )

    @contextmanager
    def _ensure_session(self) -> Generator[None, None, None]:
        """Ensure a session is available on the session stack.

        If a parent session already exists, yields immediately.
        Otherwise, opens a new session, pushes it onto the stack,
        and pops it on exit.
        """
        if self._session_stack:
            yield
        else:
            with self.backend.get_session_context() as session:
                self._session_stack.append(session)
                try:
                    yield
                finally:
                    self._session_stack.pop()

    @contextmanager
    def track_stage(
        self,
        stage_name: str,
        stage_config: Dict[str, Any],
        workflow_id: str,
        input_data: Optional[Dict[str, Any]] = None,
    ) -> Generator[str, None, None]:
        """Track stage execution."""
        stage_id = str(uuid.uuid4())
        self.context.stage_id = stage_id
        start_time = utcnow()
        sanitized_config = sanitize_config_for_display(stage_config)

        with self._ensure_session():
            self.backend.track_stage_start(
                stage_id=stage_id,
                workflow_id=workflow_id,
                stage_name=stage_name,
                stage_config=sanitized_config,
                start_time=start_time,
                input_data=input_data,
            )
            self._emit_event(
                _EVENT_STAGE_START,
                _build_stage_start_data(
                    stage_id, workflow_id, stage_name,
                    sanitized_config, start_time,
                ),
            )
            try:
                yield stage_id
                _handle_stage_success(self.backend, self._emit_event, stage_id)
            except Exception as e:
                _handle_stage_error(
                    self.backend,
                    self._emit_event,
                    stage_id,
                    e,
                    workflow_id=self.context.workflow_id,
                    alert_manager=self.alert_manager,
                )
                raise
            finally:
                self.context.stage_id = None
                _record_perf_best_effort(
                    self._performance_tracker,
                    "stage_execution",
                    start_time,
                    {"stage_id": stage_id},
                )

    @contextmanager
    def track_agent(
        self,
        agent_name: str,
        agent_config: Dict[str, Any],
        stage_id: str,
        input_data: Optional[Dict[str, Any]] = None,
    ) -> Generator[str, None, None]:
        """Track agent execution."""
        self.context.agent_id = agent_id = str(uuid.uuid4())
        start_time = utcnow()
        sanitized_config = sanitize_config_for_display(agent_config)
        with self._ensure_session():
            _track_agent_start_and_emit(
                self.backend,
                self._emit_event,
                AgentStartParams(
                    agent_id=agent_id,
                    stage_id=stage_id,
                    agent_name=agent_name,
                    sanitized_config=sanitized_config,
                    start_time=start_time,
                    input_data=input_data,
                ),
            )
            try:
                yield agent_id
                _handle_agent_success(
                    self.backend,
                    self._emit_event,
                    self._collect_agent_metrics,
                    agent_id,
                )
            except Exception as e:
                _handle_agent_error(
                    self.backend,
                    self._emit_event,
                    agent_id,
                    e,
                    workflow_id=self.context.workflow_id,
                    agent_name=agent_name,
                    alert_manager=self.alert_manager,
                )
                raise
            finally:
                self.context.agent_id = None
                _record_perf_best_effort(
                    self._performance_tracker,
                    "agent_execution",
                    start_time,
                    {"agent_id": agent_id},
                )

    def track_llm_call(
        self,
        data_or_agent_id: Any = None,
        **kwargs: Any,
    ) -> str:
        """Track LLM call with automatic sanitization.

        Args:
            data_or_agent_id: LLMCallTrackingData or agent_id string
            **kwargs: Keyword args forwarded to LLMCallTrackingData
                (provider, model, prompt, response, prompt_tokens,
                completion_tokens, latency_ms, estimated_cost_usd)

        Returns:
            LLM call ID
        """
        data = _resolve_llm_data(data_or_agent_id, **kwargs)
        return _track_llm_call(
            sanitizer=self.sanitizer,
            backend=self.backend,
            alert_manager=self.alert_manager,
            data=data,
            event_bus=self._event_bus,
        )

    def track_tool_call(self, data_or_agent_id: Any = None, **kwargs: Any) -> str:
        """Track tool execution.

        Args:
            data_or_agent_id: ToolCallTrackingData or agent_id string
            **kwargs: Keyword args forwarded to ToolCallTrackingData
                (tool_name, input_params, output_data, duration_seconds)

        Returns:
            Tool execution ID
        """
        data = _resolve_tool_data(data_or_agent_id, **kwargs)
        return _track_tool_call(
            sanitize_dict_fn=self._sanitize_dict,
            backend=self.backend,
            alert_manager=self.alert_manager,
            data=data,
            event_bus=self._event_bus,
        )

    def _sanitize_dict(self, data: Dict[str, Any], _depth: int = 0) -> Dict[str, Any]:
        return sanitize_dict(self.sanitizer, data, _depth)

    def _get_stack_trace(self) -> str:
        return get_stack_trace(self.sanitizer)

    def set_agent_output(self, params: "AgentOutputParams") -> None:
        """Set agent output data.

        Args:
            params: AgentOutputParams with all agent output parameters
        """
        self._metric_aggregator.set_agent_output(params)
        self._emit_event(
            _EVENT_AGENT_OUTPUT,
            {
                ObservabilityFields.AGENT_ID: params.agent_id,
                "confidence_score": params.confidence_score,
                ObservabilityFields.TOTAL_TOKENS: params.total_tokens,
                "estimated_cost_usd": params.estimated_cost_usd,
                "num_llm_calls": params.num_llm_calls,
                "num_tool_calls": params.num_tool_calls,
            },
        )

    def set_stage_output(
        self,
        stage_id: str,
        output_data: Dict[str, Any],
        output_lineage: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Set stage output data."""
        self._metric_aggregator.set_stage_output(
            stage_id=stage_id,
            output_data=output_data,
            output_lineage=output_lineage,
        )
        self._emit_event(
            _EVENT_STAGE_OUTPUT,
            {
                ObservabilityFields.STAGE_ID: stage_id,
            },
        )

    def track_decision_outcome(self, data: DecisionTrackingData) -> str:
        """Track decision outcome.

        Args:
            data: DecisionTrackingData with all decision tracking parameters

        Returns:
            Decision ID
        """
        return _track_decision_outcome(
            decision_tracker=self._decision_tracker,
            backend=self.backend,
            context=self.context,
            session_stack=self._session_stack,
            data=data,
        )
