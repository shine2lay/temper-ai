"""
Execution tracker for observability.

Tracks workflow, stage, agent, LLM, and tool executions in real-time,
writing to pluggable observability backends (SQL, Prometheus, S3, etc.).
"""
import contextvars
import logging
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Dict, Generator, List, Optional

from src.core.context import ExecutionContext
from src.database.datetime_utils import utcnow
from src.observability._tracker_helpers import (
    TrackerCollaborationMixin,
    build_extra_metadata as _build_extra_metadata,
    get_stack_trace,
    handle_agent_error as _handle_agent_error,
    handle_agent_success as _handle_agent_success,
    handle_stage_error as _handle_stage_error,
    handle_stage_success as _handle_stage_success,
    handle_workflow_error as _handle_workflow_error,
    handle_workflow_success as _handle_workflow_success,
    track_agent_start_and_emit as _track_agent_start_and_emit,
    sanitize_dict,
    LLMCallTrackingData,
    ToolCallTrackingData,
    DecisionTrackingData,
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
from src.utils.config_helpers import sanitize_config_for_display

logger = logging.getLogger(__name__)

# Event type identifiers for the observability event bus
_EVENT_WORKFLOW_START = "workflow_start"
_EVENT_STAGE_START = "stage_start"
_EVENT_AGENT_START = "agent_start"
_EVENT_AGENT_OUTPUT = "agent_output"
_EVENT_STAGE_OUTPUT = "stage_output"


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
    ):
        """Initialize execution tracker."""
        self._context_var: contextvars.ContextVar[ExecutionContext] = contextvars.ContextVar(
            'execution_context'
        )
        self._local = threading.local()

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
        from src.database import get_database, init_database
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
        """Per-thread session stack."""
        stack = getattr(self._local, 'session_stack', None)
        if stack is None:
            stack = []
            self._local.session_stack = stack
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
        self, workflow_name: str, workflow_config: Dict[str, Any],
        trigger_type: Optional[str] = None, trigger_data: Optional[Dict[str, Any]] = None,
        optimization_target: Optional[str] = None, product_type: Optional[str] = None,
        environment: Optional[str] = "development", tags: Optional[List[str]] = None,
        experiment_id: Optional[str] = None, variant_id: Optional[str] = None,
        assignment_strategy: Optional[str] = None, assignment_context: Optional[Dict[str, Any]] = None,
        custom_metrics: Optional[Dict[str, Any]] = None
    ) -> Generator[str, None, None]:
        """Track workflow execution."""
        workflow_id = f"wf-{uuid.uuid4()}"
        self.context.workflow_id = workflow_id

        start_time = utcnow()
        sanitized_config = sanitize_config_for_display(workflow_config)
        extra_metadata = _build_extra_metadata(
            experiment_id, variant_id, assignment_strategy, assignment_context, custom_metrics
        )

        with self.backend.get_session_context() as session:
            self._session_stack.append(session)

            from src.observability.backend import WorkflowStartData
            self.backend.track_workflow_start(
                workflow_id=workflow_id, workflow_name=workflow_name,
                workflow_config=sanitized_config, start_time=start_time,
                data=WorkflowStartData(
                    trigger_type=trigger_type, trigger_data=trigger_data,
                    optimization_target=optimization_target, product_type=product_type,
                    environment=environment, tags=tags,
                    extra_metadata=extra_metadata
                )
            )
            self._emit_event(_EVENT_WORKFLOW_START, {
                ObservabilityFields.WORKFLOW_ID: workflow_id,
                "workflow_name": workflow_name,
                ObservabilityFields.START_TIME: start_time.isoformat(),
                "environment": environment,
                "tags": tags,
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
    def track_stage(
        self, stage_name: str, stage_config: Dict[str, Any],
        workflow_id: str, input_data: Optional[Dict[str, Any]] = None
    ) -> Generator[str, None, None]:
        """Track stage execution."""
        stage_id = str(uuid.uuid4())
        self.context.stage_id = stage_id

        start_time = utcnow()
        sanitized_config = sanitize_config_for_display(stage_config)

        if self._session_stack:
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
                _handle_stage_error(self.backend, self._emit_event, stage_id, e)
                raise
            finally:
                self.context.stage_id = None
        else:
            with self.backend.get_session_context() as session:
                self._session_stack.append(session)
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
                    _handle_stage_error(self.backend, self._emit_event, stage_id, e)
                    raise
                finally:
                    self._session_stack.pop()
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

        if self._session_stack:
            _track_agent_start_and_emit(
                self.backend, self._emit_event, agent_id, stage_id,
                agent_name, sanitized_config, start_time, input_data
            )
            try:
                yield agent_id
                _handle_agent_success(
                    self.backend, self._emit_event, self._collect_agent_metrics, agent_id,
                )
            except Exception as e:
                _handle_agent_error(self.backend, self._emit_event, agent_id, e)
                raise
            finally:
                self.context.agent_id = None
        else:
            with self.backend.get_session_context() as session:
                self._session_stack.append(session)
                _track_agent_start_and_emit(
                    self.backend, self._emit_event, agent_id, stage_id,
                    agent_name, sanitized_config, start_time, input_data
                )
                try:
                    yield agent_id
                    _handle_agent_success(
                        self.backend, self._emit_event, self._collect_agent_metrics, agent_id,
                    )
                except Exception as e:
                    _handle_agent_error(self.backend, self._emit_event, agent_id, e)
                    raise
                finally:
                    self._session_stack.pop()
                    self.context.agent_id = None

    def track_llm_call(
        self, agent_id: str, provider: str, model: str, prompt: str, response: str,
        prompt_tokens: int, completion_tokens: int, latency_ms: int,
        estimated_cost_usd: float, temperature: Optional[float] = None,
        max_tokens: Optional[int] = None, status: str = "success",
        error_message: Optional[str] = None
    ) -> str:
        """Track LLM call with automatic sanitization."""
        data = LLMCallTrackingData(
            agent_id=agent_id,
            provider=provider,
            model=model,
            prompt=prompt,
            response=response,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            latency_ms=latency_ms,
            estimated_cost_usd=estimated_cost_usd,
            temperature=temperature,
            max_tokens=max_tokens,
            status=status,
            error_message=error_message,
        )
        return _track_llm_call(
            sanitizer=self.sanitizer,
            backend=self.backend,
            alert_manager=self.alert_manager,
            data=data,
            event_bus=self._event_bus,
        )

    def track_tool_call(
        self, agent_id: str, tool_name: str, input_params: Dict[str, Any],
        output_data: Dict[str, Any], duration_seconds: float,
        status: str = "success", error_message: Optional[str] = None,
        safety_checks: Optional[List[str]] = None, approval_required: bool = False
    ) -> str:
        """Track tool execution."""
        data = ToolCallTrackingData(
            agent_id=agent_id,
            tool_name=tool_name,
            input_params=input_params,
            output_data=output_data,
            duration_seconds=duration_seconds,
            status=status,
            error_message=error_message,
            safety_checks=safety_checks,
            approval_required=approval_required,
        )
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

    def set_agent_output(
        self, agent_id: str, output_data: Dict[str, Any],
        reasoning: Optional[str] = None, confidence_score: Optional[float] = None,
        total_tokens: Optional[int] = None, prompt_tokens: Optional[int] = None,
        completion_tokens: Optional[int] = None, estimated_cost_usd: Optional[float] = None,
        num_llm_calls: Optional[int] = None, num_tool_calls: Optional[int] = None
    ) -> None:
        """Set agent output data."""
        from src.observability.metric_aggregator import AgentOutputParams
        params = AgentOutputParams(
            agent_id=agent_id, output_data=output_data, reasoning=reasoning,
            confidence_score=confidence_score, total_tokens=total_tokens,
            prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
            estimated_cost_usd=estimated_cost_usd, num_llm_calls=num_llm_calls,
            num_tool_calls=num_tool_calls,
        )
        self._metric_aggregator.set_agent_output(params)
        self._emit_event(_EVENT_AGENT_OUTPUT, {
            ObservabilityFields.AGENT_ID: agent_id,
            "confidence_score": confidence_score,
            ObservabilityFields.TOTAL_TOKENS: total_tokens,
            "estimated_cost_usd": estimated_cost_usd,
            "num_llm_calls": num_llm_calls,
            "num_tool_calls": num_tool_calls,
        })

    def set_stage_output(self, stage_id: str, output_data: Dict[str, Any]) -> None:
        """Set stage output data."""
        self._metric_aggregator.set_stage_output(stage_id=stage_id, output_data=output_data)
        self._emit_event(_EVENT_STAGE_OUTPUT, {
            ObservabilityFields.STAGE_ID: stage_id,
        })

    def track_decision_outcome(
        self, decision_type: str, decision_data: Dict[str, Any], outcome: str,
        impact_metrics: Optional[Dict[str, Any]] = None,
        lessons_learned: Optional[str] = None, should_repeat: Optional[bool] = None,
        tags: Optional[List[str]] = None, agent_execution_id: Optional[str] = None,
        stage_execution_id: Optional[str] = None,
        workflow_execution_id: Optional[str] = None,
        validation_method: Optional[str] = None,
        validation_timestamp: Optional[datetime] = None,
        validation_duration_seconds: Optional[float] = None,
        extra_metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """Track decision outcome."""
        data = DecisionTrackingData(
            decision_type=decision_type,
            decision_data=decision_data,
            outcome=outcome,
            impact_metrics=impact_metrics,
            lessons_learned=lessons_learned,
            should_repeat=should_repeat,
            tags=tags,
            agent_execution_id=agent_execution_id,
            stage_execution_id=stage_execution_id,
            workflow_execution_id=workflow_execution_id,
            validation_method=validation_method,
            validation_timestamp=validation_timestamp,
            validation_duration_seconds=validation_duration_seconds,
            extra_metadata=extra_metadata,
        )
        return _track_decision_outcome(
            decision_tracker=self._decision_tracker,
            backend=self.backend,
            context=self.context,
            session_stack=self._session_stack,
            data=data,
        )

