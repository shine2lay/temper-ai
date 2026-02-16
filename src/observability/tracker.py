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
    from src.observability.metric_aggregator import AgentOutputParams

from src.shared.core.context import ExecutionContext, current_execution_context
from src.storage.database.datetime_utils import utcnow
from src.observability._tracker_helpers import (
    DecisionTrackingData,
    LLMCallTrackingData,
    ToolCallTrackingData,
    TrackerCollaborationMixin,
    get_stack_trace,
    sanitize_dict,
)
from src.observability._tracker_helpers import (
    build_extra_metadata as _build_extra_metadata,
)
from src.observability._tracker_helpers import (
    handle_agent_error as _handle_agent_error,
)
from src.observability._tracker_helpers import (
    handle_agent_success as _handle_agent_success,
)
from src.observability._tracker_helpers import (
    handle_stage_error as _handle_stage_error,
)
from src.observability._tracker_helpers import (
    handle_stage_success as _handle_stage_success,
)
from src.observability._tracker_helpers import (
    handle_workflow_error as _handle_workflow_error,
)
from src.observability._tracker_helpers import (
    handle_workflow_success as _handle_workflow_success,
)
from src.observability._tracker_helpers import (
    track_agent_start_and_emit as _track_agent_start_and_emit,
)
from src.observability._tracker_helpers import (
    track_decision_outcome as _track_decision_outcome,
)
from src.observability._tracker_helpers import (
    track_llm_call as _track_llm_call,
)
from src.observability._tracker_helpers import (
    track_tool_call as _track_tool_call,
)
from src.observability.backend import ObservabilityBackend
from src.observability.collaboration_tracker import CollaborationEventTracker
from src.observability.constants import ObservabilityFields
from src.observability.decision_tracker import DecisionTracker
from src.observability.event_bus import ObservabilityEvent, ObservabilityEventBus
from src.observability.metric_aggregator import MetricAggregator
from src.observability.sanitization import DataSanitizer, SanitizationConfig
from src.shared.utils.config_helpers import sanitize_config_for_display

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


class ExecutionTracker(TrackerCollaborationMixin):
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
            from src.observability.backends import SQLObservabilityBackend
            backend = SQLObservabilityBackend()

        self.backend = backend
        self.sanitizer = DataSanitizer(sanitization_config)
        self.metric_registry = metric_registry

        if alert_manager is None:
            from src.observability.alerting import AlertManager
            alert_manager = AlertManager()
        self.alert_manager = alert_manager

        self._event_bus = event_bus

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
        from src.storage.database import get_database, init_database
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
    def track_workflow(self, params: WorkflowTrackingParams) -> Generator[str, None, None]:
        """Track workflow execution.

        Args:
            params: WorkflowTrackingParams with all workflow tracking parameters

        Yields:
            workflow_id: The generated workflow execution ID
        """
        workflow_id = f"wf-{uuid.uuid4()}"
        self.context.workflow_id = workflow_id

        start_time = utcnow()
        sanitized_config = sanitize_config_for_display(params.workflow_config)
        extra_metadata = _build_extra_metadata(
            params.experiment_id, params.variant_id, params.assignment_strategy,
            params.assignment_context, params.custom_metrics
        )

        with self.backend.get_session_context() as session:
            self._session_stack.append(session)

            from src.observability.backend import WorkflowStartData
            self.backend.track_workflow_start(
                workflow_id=workflow_id, workflow_name=params.workflow_name,
                workflow_config=sanitized_config, start_time=start_time,
                data=WorkflowStartData(
                    trigger_type=params.trigger_type, trigger_data=params.trigger_data,
                    optimization_target=params.optimization_target, product_type=params.product_type,
                    environment=params.environment, tags=params.tags,
                    extra_metadata=extra_metadata,
                    cost_attribution_tags=params.cost_attribution_tags,
                )
            )
            self._emit_event(_EVENT_WORKFLOW_START, {
                ObservabilityFields.WORKFLOW_ID: workflow_id,
                "workflow_name": params.workflow_name,
                ObservabilityFields.START_TIME: start_time.isoformat(),
                "environment": params.environment,
                "tags": params.tags,
            })

            try:
                yield workflow_id
                _handle_workflow_success(
                    self.backend, self.alert_manager, self._emit_event, workflow_id,
                )
            except Exception as e:
                _handle_workflow_error(
                    self.backend, self._emit_event, self._get_stack_trace, workflow_id, e,
                )
                raise
            finally:
                self._session_stack.pop()
                self.context.workflow_id = None

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
        self, stage_name: str, stage_config: Dict[str, Any],
        workflow_id: str, input_data: Optional[Dict[str, Any]] = None
    ) -> Generator[str, None, None]:
        """Track stage execution."""
        stage_id = str(uuid.uuid4())
        self.context.stage_id = stage_id

        start_time = utcnow()
        sanitized_config = sanitize_config_for_display(stage_config)

        with self._ensure_session():
            self.backend.track_stage_start(
                stage_id=stage_id, workflow_id=workflow_id, stage_name=stage_name,
                stage_config=sanitized_config, start_time=start_time, input_data=input_data
            )
            self._emit_event(_EVENT_STAGE_START, {
                ObservabilityFields.STAGE_ID: stage_id,
                ObservabilityFields.WORKFLOW_ID: workflow_id,
                "stage_name": stage_name,
                ObservabilityFields.START_TIME: start_time.isoformat(),
            })
            try:
                yield stage_id
                _handle_stage_success(self.backend, self._emit_event, stage_id)
            except Exception as e:
                _handle_stage_error(
                    self.backend, self._emit_event, stage_id, e,
                    workflow_id=self.context.workflow_id,
                    alert_manager=self.alert_manager,
                )
                raise
            finally:
                self.context.stage_id = None

    @contextmanager
    def track_agent(
        self, agent_name: str, agent_config: Dict[str, Any],
        stage_id: str, input_data: Optional[Dict[str, Any]] = None
    ) -> Generator[str, None, None]:
        """Track agent execution."""
        agent_id = str(uuid.uuid4())
        self.context.agent_id = agent_id

        start_time = utcnow()
        sanitized_config = sanitize_config_for_display(agent_config)

        with self._ensure_session():
            from src.observability._tracker_helpers import AgentStartParams
            _track_agent_start_and_emit(
                self.backend, self._emit_event,
                AgentStartParams(
                    agent_id=agent_id, stage_id=stage_id, agent_name=agent_name,
                    sanitized_config=sanitized_config, start_time=start_time, input_data=input_data
                )
            )
            try:
                yield agent_id
                _handle_agent_success(
                    self.backend, self._emit_event, self._collect_agent_metrics, agent_id,
                )
            except Exception as e:
                _handle_agent_error(
                    self.backend, self._emit_event, agent_id, e,
                    workflow_id=self.context.workflow_id,
                    agent_name=agent_name,
                    alert_manager=self.alert_manager,
                )
                raise
            finally:
                self.context.agent_id = None

    def track_llm_call(self, data: LLMCallTrackingData) -> str:
        """Track LLM call with automatic sanitization.

        Args:
            data: LLMCallTrackingData with all LLM call tracking parameters

        Returns:
            LLM call ID
        """
        return _track_llm_call(
            sanitizer=self.sanitizer,
            backend=self.backend,
            alert_manager=self.alert_manager,
            data=data,
            event_bus=self._event_bus,
        )

    def track_tool_call(self, data: ToolCallTrackingData) -> str:
        """Track tool execution.

        Args:
            data: ToolCallTrackingData with all tool call tracking parameters

        Returns:
            Tool execution ID
        """
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
        self._emit_event(_EVENT_AGENT_OUTPUT, {
            ObservabilityFields.AGENT_ID: params.agent_id,
            "confidence_score": params.confidence_score,
            ObservabilityFields.TOTAL_TOKENS: params.total_tokens,
            "estimated_cost_usd": params.estimated_cost_usd,
            "num_llm_calls": params.num_llm_calls,
            "num_tool_calls": params.num_tool_calls,
        })

    def set_stage_output(
        self, stage_id: str, output_data: Dict[str, Any],
        output_lineage: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Set stage output data."""
        self._metric_aggregator.set_stage_output(
            stage_id=stage_id, output_data=output_data, output_lineage=output_lineage,
        )
        self._emit_event(_EVENT_STAGE_OUTPUT, {
            ObservabilityFields.STAGE_ID: stage_id,
        })

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

    # ========== Async Methods ==========

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
    async def atrack_workflow(self, params: WorkflowTrackingParams) -> AsyncGenerator[str, None]:
        """Async version of track_workflow.

        Args:
            params: WorkflowTrackingParams with all workflow tracking parameters

        Yields:
            workflow_id: The generated workflow execution ID
        """
        workflow_id = f"wf-{uuid.uuid4()}"
        self.context.workflow_id = workflow_id
        start_time = utcnow()
        sanitized_config = sanitize_config_for_display(params.workflow_config)
        extra_metadata = _build_extra_metadata(
            params.experiment_id, params.variant_id,
            params.assignment_strategy, params.assignment_context,
            params.custom_metrics,
        )

        async with self.backend.aget_session_context() as session:
            self._session_stack.append(session)
            from src.observability.backend import WorkflowStartData
            await self.backend.atrack_workflow_start(
                workflow_id=workflow_id, workflow_name=params.workflow_name,
                workflow_config=sanitized_config, start_time=start_time,
                data=WorkflowStartData(
                    trigger_type=params.trigger_type,
                    trigger_data=params.trigger_data,
                    optimization_target=params.optimization_target,
                    product_type=params.product_type,
                    environment=params.environment, tags=params.tags,
                    extra_metadata=extra_metadata,
                    cost_attribution_tags=params.cost_attribution_tags,
                ),
            )
            self._emit_event(_EVENT_WORKFLOW_START, {
                ObservabilityFields.WORKFLOW_ID: workflow_id,
                "workflow_name": params.workflow_name,
                ObservabilityFields.START_TIME: start_time.isoformat(),
                "environment": params.environment,
                "tags": params.tags,
            })
            try:
                yield workflow_id
                _handle_workflow_success(
                    self.backend, self.alert_manager,
                    self._emit_event, workflow_id,
                )
            except Exception as e:
                _handle_workflow_error(
                    self.backend, self._emit_event,
                    self._get_stack_trace, workflow_id, e,
                )
                raise
            finally:
                self._session_stack.pop()
                self.context.workflow_id = None

    @_asynccontextmanager
    async def atrack_stage(
        self, stage_name: str, stage_config: Dict[str, Any],
        workflow_id: str, input_data: Optional[Dict[str, Any]] = None,
    ) -> AsyncGenerator[str, None]:
        """Async version of track_stage."""
        stage_id = str(uuid.uuid4())
        self.context.stage_id = stage_id
        start_time = utcnow()
        sanitized_config = sanitize_config_for_display(stage_config)

        async with self._aensure_session():
            await self.backend.atrack_stage_start(
                stage_id=stage_id, workflow_id=workflow_id,
                stage_name=stage_name, stage_config=sanitized_config,
                start_time=start_time, input_data=input_data,
            )
            self._emit_event(_EVENT_STAGE_START, {
                ObservabilityFields.STAGE_ID: stage_id,
                ObservabilityFields.WORKFLOW_ID: workflow_id,
                "stage_name": stage_name,
                ObservabilityFields.START_TIME: start_time.isoformat(),
            })
            try:
                yield stage_id
                _handle_stage_success(
                    self.backend, self._emit_event, stage_id,
                )
            except Exception as e:
                _handle_stage_error(
                    self.backend, self._emit_event, stage_id, e,
                    workflow_id=self.context.workflow_id,
                    alert_manager=self.alert_manager,
                )
                raise
            finally:
                self.context.stage_id = None

    @_asynccontextmanager
    async def atrack_agent(
        self, agent_name: str, agent_config: Dict[str, Any],
        stage_id: str, input_data: Optional[Dict[str, Any]] = None,
    ) -> AsyncGenerator[str, None]:
        """Async version of track_agent."""
        agent_id = str(uuid.uuid4())
        self.context.agent_id = agent_id
        start_time = utcnow()
        sanitized_config = sanitize_config_for_display(agent_config)

        async with self._aensure_session():
            from src.observability._tracker_helpers import AgentStartParams
            _track_agent_start_and_emit(
                self.backend, self._emit_event,
                AgentStartParams(
                    agent_id=agent_id, stage_id=stage_id,
                    agent_name=agent_name,
                    sanitized_config=sanitized_config,
                    start_time=start_time, input_data=input_data,
                ),
            )
            try:
                yield agent_id
                _handle_agent_success(
                    self.backend, self._emit_event,
                    self._collect_agent_metrics, agent_id,
                )
            except Exception as e:
                _handle_agent_error(
                    self.backend, self._emit_event, agent_id, e,
                    workflow_id=self.context.workflow_id,
                    agent_name=agent_name,
                    alert_manager=self.alert_manager,
                )
                raise
            finally:
                self.context.agent_id = None

    async def atrack_llm_call(self, data: LLMCallTrackingData) -> str:
        """Async version of track_llm_call.

        Args:
            data: LLMCallTrackingData with all LLM call tracking parameters

        Returns:
            LLM call ID
        """
        return _track_llm_call(
            sanitizer=self.sanitizer,
            backend=self.backend,
            alert_manager=self.alert_manager,
            data=data,
            event_bus=self._event_bus,
        )

    async def atrack_tool_call(self, data: ToolCallTrackingData) -> str:
        """Async version of track_tool_call.

        Args:
            data: ToolCallTrackingData with all tool call tracking parameters

        Returns:
            Tool execution ID
        """
        return _track_tool_call(
            sanitize_dict_fn=self._sanitize_dict,
            backend=self.backend,
            alert_manager=self.alert_manager,
            data=data,
            event_bus=self._event_bus,
        )

