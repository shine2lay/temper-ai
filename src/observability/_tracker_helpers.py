"""Helper functions extracted from ExecutionTracker to reduce class size.

Contains:
- Sanitization helpers (dict sanitization, stack trace)
- LLM call tracking logic
- Tool call tracking logic
- Decision outcome tracking
- Merit score update
- TrackerCollaborationMixin (collaboration/safety/merit methods)
- Workflow metrics aggregation helper
"""
import logging
import traceback
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from src.shared.constants.durations import MILLISECONDS_PER_SECOND
from src.shared.constants.limits import THRESHOLD_MEDIUM_COUNT
from src.storage.database.datetime_utils import utcnow
from src.observability.constants import ObservabilityFields

logger = logging.getLogger(__name__)

# Sanitization context identifiers
_CTX_CONFIG = "config"
_CTX_PROMPT = "prompt"
_CTX_RESPONSE = "response"
_CTX_ERROR = "error"
_CTX_STACK_TRACE = "stack_trace"

# Metric type identifiers for AlertManager.check_metric()
_METRIC_LATENCY_P99 = "latency_p99"
_METRIC_COST_USD = "cost_usd"
_METRIC_DURATION = "duration"

# Event type identifiers for ObservabilityEventBus
_EVENT_LLM_CALL = "llm_call"
_EVENT_TOOL_CALL = "tool_call"
_EVENT_LLM_STREAM_CHUNK = "llm_stream_chunk"
_EVENT_SAFETY_VIOLATION = "safety_violation"
_EVENT_COLLABORATION = "collaboration_event"


# ========== Parameter Bundling Dataclasses ==========


@dataclass
class LLMCallTrackingData:
    """Bundle parameters for LLM call tracking."""
    agent_id: str
    provider: str
    model: str
    prompt: str
    response: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: int
    estimated_cost_usd: float
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    status: str = "success"
    error_message: Optional[str] = None


@dataclass
class ToolCallTrackingData:
    """Bundle parameters for tool call tracking."""
    agent_id: str
    tool_name: str
    input_params: Dict[str, Any]
    output_data: Dict[str, Any]
    duration_seconds: float
    status: str = "success"
    error_message: Optional[str] = None
    safety_checks: Optional[List[str]] = None
    approval_required: bool = False


@dataclass
class DecisionTrackingData:
    """Bundle parameters for decision outcome tracking."""
    decision_type: str
    decision_data: Dict[str, Any]
    outcome: str
    impact_metrics: Optional[Dict[str, Any]] = None
    lessons_learned: Optional[str] = None
    should_repeat: Optional[bool] = None
    tags: Optional[List[str]] = None
    agent_execution_id: Optional[str] = None
    stage_execution_id: Optional[str] = None
    workflow_execution_id: Optional[str] = None
    validation_method: Optional[str] = None
    validation_timestamp: Optional[datetime] = None
    validation_duration_seconds: Optional[float] = None
    extra_metadata: Optional[Dict[str, Any]] = None


@dataclass
class StreamChunkData:
    """Bundle parameters for stream chunk events."""
    agent_id: str
    content: str
    chunk_type: str = "content"
    done: bool = False
    model: Optional[str] = None
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    workflow_id: Optional[str] = None
    stage_id: Optional[str] = None


@dataclass
class CollaborationEventData:
    """Bundle parameters for collaboration event tracking."""
    event_type: str
    stage_id: Optional[str] = None
    agents_involved: Optional[List[str]] = None
    event_data: Optional[Dict[str, Any]] = None
    round_number: Optional[int] = None
    resolution_strategy: Optional[str] = None
    outcome: Optional[str] = None
    confidence_score: Optional[float] = None
    extra_metadata: Optional[Dict[str, Any]] = None
    stage_name: Optional[str] = None
    agents: Optional[List[str]] = None
    decision: Optional[str] = None
    confidence: Optional[float] = None
    metadata: Optional[Dict[str, Any]] = None


def sanitize_dict(
    sanitizer: Any,
    data: Dict[str, Any],
    _depth: int = 0,
) -> Dict[str, Any]:
    """Recursively sanitize dictionary values to remove secrets.

    SECURITY: Prevents credential exposure in tool parameters/outputs.
    Uses recursive traversal instead of JSON round-trip to avoid injection attacks.
    OB-09: Depth-limited to prevent RecursionError on deeply nested structures.

    Args:
        sanitizer: DataSanitizer instance
        data: Dictionary to sanitize
        _depth: Current recursion depth (internal)

    Returns:
        Sanitized dictionary with secrets redacted
    """
    # Defensive check - should not be hit given type signature
    if not isinstance(data, dict):
        return {}  # type: ignore[unreachable]

    # OB-09: Prevent RecursionError on deeply nested structures
    if _depth > THRESHOLD_MEDIUM_COUNT:
        return {"__truncated__": "max depth exceeded"}

    sanitized: Dict[str, Any] = {}
    for key, value in data.items():
        try:
            # Sanitize key as well (keys might contain secrets)
            safe_key_result = sanitizer.sanitize_text(str(key), context=_CTX_CONFIG)
            safe_key = safe_key_result.sanitized_text

            # Recursively sanitize value based on type
            if isinstance(value, dict):
                sanitized[safe_key] = sanitize_dict(sanitizer, value, _depth + 1)
            elif isinstance(value, list):
                sanitized_list: List[Any] = [
                    sanitize_dict(sanitizer, item, _depth + 1) if isinstance(item, dict)
                    else sanitizer.sanitize_text(str(item), context=_CTX_CONFIG).sanitized_text
                    if isinstance(item, str)
                    else item
                    for item in value
                ]
                sanitized[safe_key] = sanitized_list
            elif isinstance(value, str):
                result = sanitizer.sanitize_text(value, context=_CTX_CONFIG)
                sanitized[safe_key] = result.sanitized_text
            elif value is None or isinstance(value, (bool, int, float)):
                # Safe primitive types - no sanitization needed
                sanitized[safe_key] = value
            else:
                # Non-serializable object - convert to safe type indicator
                # SECURITY: Log error type but NOT the value
                logger.warning(
                    "Non-serializable object in tool parameters",
                    extra={
                        "value_type": type(value).__name__,
                        "key": safe_key
                    }
                )
                sanitized[safe_key] = f"[SANITIZED:{type(value).__name__}]"
        except Exception as e:
            # SECURITY: Log exception type but NOT the data
            logger.warning(
                "Sanitization error for key",
                extra={
                    "error_type": type(e).__name__,
                    "key_type": type(key).__name__
                }
            )
            sanitized[str(key)] = "[SANITIZATION_ERROR]"

    return sanitized


def get_stack_trace(sanitizer: Any) -> str:
    """Get current exception stack trace, sanitized to remove secrets."""
    raw_trace = traceback.format_exc()
    result = sanitizer.sanitize_text(raw_trace, context=_CTX_STACK_TRACE)
    return str(result.sanitized_text)


def _validate_llm_metrics(data: LLMCallTrackingData) -> None:
    """Validate LLM metric parameters are non-negative."""
    if data.prompt_tokens < 0:
        raise ValueError(f"prompt_tokens must be non-negative, got {data.prompt_tokens}")
    if data.completion_tokens < 0:
        raise ValueError(f"completion_tokens must be non-negative, got {data.completion_tokens}")
    if data.latency_ms < 0:
        raise ValueError(f"latency_ms must be non-negative, got {data.latency_ms}")
    if data.estimated_cost_usd < 0:
        raise ValueError(f"estimated_cost_usd must be non-negative, got {data.estimated_cost_usd}")


def _sanitize_llm_content(sanitizer: Any, data: LLMCallTrackingData) -> tuple[Any, Any, Optional[str]]:
    """Sanitize prompt, response, and error message.

    Returns:
        tuple: (prompt_result, response_result, safe_error_message)
    """
    prompt_result = sanitizer.sanitize_text(data.prompt, context=_CTX_PROMPT)
    response_result = sanitizer.sanitize_text(data.response, context=_CTX_RESPONSE)

    safe_error_message = None
    if data.error_message:
        error_result = sanitizer.sanitize_text(data.error_message, context=_CTX_ERROR)
        safe_error_message = error_result.sanitized_text

    return prompt_result, response_result, safe_error_message


def _log_sanitization_activity(
    llm_call_id: str,
    prompt_result: Any,
    response_result: Any
) -> None:
    """Log sanitization activity if redactions were made."""
    if prompt_result.was_sanitized or response_result.was_sanitized:
        logger.info(
            "Sanitized LLM call data before storage",
            extra={
                "llm_call_id": llm_call_id,
                "prompt_redactions": prompt_result.num_redactions,
                "response_redactions": response_result.num_redactions,
                "redaction_types": list(
                    set(prompt_result.to_metadata().get("redaction_types", []) +
                        response_result.to_metadata().get("redaction_types", []))
                )
            }
        )


def _emit_llm_call_event(
    event_bus: Any,
    llm_call_id: str,
    start_time: datetime,
    data: LLMCallTrackingData,
    prompt_result: Any,
    response_result: Any,
    safe_error_message: Optional[str]
) -> None:
    """Emit LLM call event for real-time consumers."""
    if event_bus is None:
        return

    from src.observability.event_bus import ObservabilityEvent

    event_bus.emit(ObservabilityEvent(
        event_type=_EVENT_LLM_CALL,
        timestamp=start_time,
        data={
            "llm_call_id": llm_call_id,
            ObservabilityFields.AGENT_ID: data.agent_id,
            "provider": data.provider,
            "model": data.model,
            "prompt": prompt_result.sanitized_text,
            "response": response_result.sanitized_text,
            "prompt_tokens": data.prompt_tokens,
            "completion_tokens": data.completion_tokens,
            "latency_ms": data.latency_ms,
            "estimated_cost_usd": data.estimated_cost_usd,
            "temperature": data.temperature,
            "max_tokens": data.max_tokens,
            ObservabilityFields.STATUS: data.status,
            ObservabilityFields.ERROR_MESSAGE: safe_error_message,
        },
        agent_id=data.agent_id,
    ))


def _check_llm_alerts(
    alert_manager: Any,
    llm_call_id: str,
    data: LLMCallTrackingData
) -> None:
    """Check latency and cost alerts for LLM call."""
    if not alert_manager:
        return

    if data.latency_ms > 0:
        alert_manager.check_metric(
            metric_type=_METRIC_LATENCY_P99,
            value=data.latency_ms,
            context={
                ObservabilityFields.AGENT_ID: data.agent_id,
                "provider": data.provider,
                "model": data.model,
                "llm_call_id": llm_call_id
            }
        )

    if data.estimated_cost_usd > 0:
        alert_manager.check_metric(
            metric_type=_METRIC_COST_USD,
            value=data.estimated_cost_usd,
            context={
                ObservabilityFields.AGENT_ID: data.agent_id,
                "provider": data.provider,
                "model": data.model,
                "llm_call_id": llm_call_id
            }
        )


def track_llm_call(
    sanitizer: Any,
    backend: Any,
    alert_manager: Any,
    data: LLMCallTrackingData,
    event_bus: Any = None,
) -> str:
    """Track LLM call with automatic sanitization.

    Args:
        sanitizer: DataSanitizer instance
        backend: ObservabilityBackend instance
        alert_manager: AlertManager instance (or None)
        data: LLMCallTrackingData with all tracking parameters
        event_bus: Event bus for real-time events (optional)

    Returns:
        llm_call_id: UUID of the LLM call

    Raises:
        ValueError: If numeric parameters are negative
    """
    _validate_llm_metrics(data)

    llm_call_id = str(uuid.uuid4())
    start_time = utcnow()

    prompt_result, response_result, safe_error_message = _sanitize_llm_content(
        sanitizer, data
    )

    _log_sanitization_activity(llm_call_id, prompt_result, response_result)

    # Track LLM call with sanitized content
    from src.observability.backend import LLMCallData as BackendLLMCallData
    backend.track_llm_call(
        llm_call_id=llm_call_id,
        agent_id=data.agent_id,
        provider=data.provider,
        model=data.model,
        start_time=start_time,
        data=BackendLLMCallData(
            prompt=prompt_result.sanitized_text,
            response=response_result.sanitized_text,
            prompt_tokens=data.prompt_tokens,
            completion_tokens=data.completion_tokens,
            latency_ms=data.latency_ms,
            estimated_cost_usd=data.estimated_cost_usd,
            temperature=data.temperature,
            max_tokens=data.max_tokens,
            status=data.status,  # type: ignore[arg-type]
            error_message=safe_error_message,
        ),
    )

    _emit_llm_call_event(
        event_bus, llm_call_id, start_time, data,
        prompt_result, response_result, safe_error_message
    )

    _check_llm_alerts(alert_manager, llm_call_id, data)

    return llm_call_id


def _emit_tool_call_event(
    event_bus: Any,
    tool_execution_id: str,
    start_time: datetime,
    data: ToolCallTrackingData,
    sanitized_input: Dict[str, Any],
    sanitized_output: Dict[str, Any]
) -> None:
    """Emit tool call event for real-time consumers."""
    if event_bus is None:
        return

    from src.observability.event_bus import ObservabilityEvent

    event_bus.emit(ObservabilityEvent(
        event_type=_EVENT_TOOL_CALL,
        timestamp=start_time,
        data={
            "tool_execution_id": tool_execution_id,
            ObservabilityFields.AGENT_ID: data.agent_id,
            "tool_name": data.tool_name,
            "input_params": sanitized_input,
            ObservabilityFields.OUTPUT_DATA: sanitized_output,
            ObservabilityFields.DURATION_SECONDS: data.duration_seconds,
            ObservabilityFields.STATUS: data.status,
            ObservabilityFields.ERROR_MESSAGE: data.error_message,
            "safety_checks": data.safety_checks,
            "approval_required": data.approval_required,
        },
        agent_id=data.agent_id,
    ))


def _check_tool_duration_alert(
    alert_manager: Any,
    tool_execution_id: str,
    data: ToolCallTrackingData
) -> None:
    """Check tool execution duration alerts."""
    if alert_manager and data.duration_seconds > 0:
        duration_ms = data.duration_seconds * MILLISECONDS_PER_SECOND
        alert_manager.check_metric(
            metric_type=_METRIC_DURATION,
            value=duration_ms,
            context={
                ObservabilityFields.AGENT_ID: data.agent_id,
                "tool_name": data.tool_name,
                "tool_execution_id": tool_execution_id,
                ObservabilityFields.STATUS: data.status
            }
        )


def track_tool_call(
    sanitize_dict_fn: Any,
    backend: Any,
    alert_manager: Any,
    data: ToolCallTrackingData,
    event_bus: Any = None,
) -> str:
    """Track tool execution.

    Args:
        sanitize_dict_fn: Callable to sanitize dicts
        backend: ObservabilityBackend instance
        alert_manager: AlertManager instance (or None)
        data: ToolCallTrackingData with all tracking parameters
        event_bus: Event bus for real-time events (optional)

    Returns:
        tool_execution_id: UUID of the tool execution
    """
    tool_execution_id = str(uuid.uuid4())
    start_time = utcnow()

    # SECURITY: Sanitize tool parameters before storage
    sanitized_input = sanitize_dict_fn(data.input_params)
    sanitized_output = sanitize_dict_fn(data.output_data)

    from src.observability.backend import ToolCallData as BackendToolCallData
    backend.track_tool_call(
        tool_execution_id=tool_execution_id,
        agent_id=data.agent_id,
        tool_name=data.tool_name,
        start_time=start_time,
        data=BackendToolCallData(
            input_params=sanitized_input,
            output_data=sanitized_output,
            duration_seconds=data.duration_seconds,
            status=data.status,  # type: ignore[arg-type]
            error_message=data.error_message,
            safety_checks=data.safety_checks,
            approval_required=data.approval_required,
        ),
    )

    _emit_tool_call_event(
        event_bus, tool_execution_id, start_time, data,
        sanitized_input, sanitized_output
    )

    _check_tool_duration_alert(alert_manager, tool_execution_id, data)

    return tool_execution_id


def _fill_execution_ids(
    data: DecisionTrackingData,
    context: Any
) -> DecisionTrackingData:
    """Fill in execution IDs from context if not provided."""
    if not data.workflow_execution_id:
        data.workflow_execution_id = context.workflow_id
    if not data.stage_execution_id:
        data.stage_execution_id = context.stage_id
    if not data.agent_execution_id:
        data.agent_execution_id = context.agent_id
    return data


def track_decision_outcome(
    decision_tracker: Any,
    backend: Any,
    context: Any,
    session_stack: List[Any],
    data: DecisionTrackingData,
) -> str:
    """Track decision outcome for self-improvement learning loop.

    Args:
        decision_tracker: DecisionTracker instance
        backend: ObservabilityBackend instance
        context: Execution context with workflow/stage/agent IDs
        session_stack: Session stack for database transactions
        data: DecisionTrackingData with all tracking parameters

    Returns:
        Decision ID or empty string on failure
    """
    data = _fill_execution_ids(data, context)

    # Convert DecisionTrackingData to DecisionTrackingParams
    from src.observability.decision_tracker import DecisionTrackingParams
    params = DecisionTrackingParams(
        decision_type=data.decision_type,
        decision_data=data.decision_data,
        outcome=data.outcome,
        impact_metrics=data.impact_metrics,
        lessons_learned=data.lessons_learned,
        should_repeat=data.should_repeat,
        tags=data.tags,
        agent_execution_id=data.agent_execution_id,
        stage_execution_id=data.stage_execution_id,
        workflow_execution_id=data.workflow_execution_id,
        validation_method=data.validation_method,
        validation_timestamp=data.validation_timestamp,
        validation_duration_seconds=data.validation_duration_seconds,
        extra_metadata=data.extra_metadata,
    )

    result: str
    if session_stack:
        result = str(decision_tracker.track(
            session=session_stack[-1], params=params
        ))
    else:
        with backend.get_session_context() as session:
            result = str(decision_tracker.track(session=session, params=params))

    return result


def update_agent_merit_score(
    decision_tracker: Any,
    backend: Any,
    session_stack: List[Any],
    agent_name: str,
    domain: str,
    decision_outcome: str,
    confidence: Optional[float] = None,
) -> None:
    """Update agent merit score based on decision outcome.

    Args:
        decision_tracker: DecisionTracker instance (owns MeritScoreService)
        backend: ObservabilityBackend instance
        session_stack: Session stack list
        agent_name: Name of the agent
        domain: Domain of expertise
        decision_outcome: Outcome
        confidence: Confidence score (0.0-1.0)
    """
    try:
        if session_stack:
            decision_tracker._merit_service.update(
                session=session_stack[-1],
                agent_name=agent_name,
                domain=domain,
                decision_outcome=decision_outcome,
                confidence=confidence,
            )
            session_stack[-1].commit()
        else:
            with backend.get_session_context() as session:
                decision_tracker._merit_service.update(
                    session=session,
                    agent_name=agent_name,
                    domain=domain,
                    decision_outcome=decision_outcome,
                    confidence=confidence,
                )
                session.commit()
    except Exception as e:
        logger.error(
            f"Failed to update agent merit score: {e}",
            exc_info=True,
            extra={
                ObservabilityFields.AGENT_NAME: agent_name,
                "domain": domain,
                "outcome": decision_outcome
            }
        )


def aggregate_workflow_metrics_on_success(
    backend: Any,
    alert_manager: Any,
    workflow_id: str,
) -> None:
    """Aggregate and store workflow metrics after successful completion.

    Args:
        backend: ObservabilityBackend instance
        alert_manager: AlertManager instance (or None)
        workflow_id: Workflow execution ID
    """
    try:
        if hasattr(backend, 'aggregate_workflow_metrics'):
            metrics = backend.aggregate_workflow_metrics(workflow_id)
            if metrics:
                total_cost = metrics.get(ObservabilityFields.TOTAL_COST_USD, 0.0)
                backend.update_workflow_metrics(
                    workflow_id=workflow_id,
                    total_llm_calls=metrics.get(ObservabilityFields.TOTAL_LLM_CALLS, 0),
                    total_tool_calls=metrics.get(ObservabilityFields.TOTAL_TOOL_CALLS, 0),
                    total_tokens=metrics.get(ObservabilityFields.TOTAL_TOKENS, 0),
                    total_cost_usd=total_cost
                )
                if alert_manager and total_cost > 0:
                    alert_manager.check_metric(
                        metric_type=_METRIC_COST_USD, value=total_cost,
                        context={ObservabilityFields.WORKFLOW_ID: workflow_id}
                    )
    except Exception as e:
        logger.warning(
            f"Failed to aggregate workflow metrics for {workflow_id}: {e}",
            exc_info=True,
        )


def build_extra_metadata(
    experiment_id: Optional[str],
    variant_id: Optional[str],
    assignment_strategy: Optional[str],
    assignment_context: Optional[Dict[str, Any]],
    custom_metrics: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Build extra metadata dict from optional experiment tracking params."""
    extra_metadata: Dict[str, Any] = {}
    if experiment_id:
        extra_metadata["experiment_id"] = experiment_id
    if variant_id:
        extra_metadata["variant_id"] = variant_id
    if assignment_strategy:
        extra_metadata["assignment_strategy"] = assignment_strategy
    if assignment_context:
        extra_metadata["assignment_context"] = assignment_context
    if custom_metrics:
        extra_metadata["custom_metrics"] = custom_metrics
    return extra_metadata if extra_metadata else None


@dataclass
class AgentStartParams:
    """Parameters for tracking agent start."""
    agent_id: str
    stage_id: str
    agent_name: str
    sanitized_config: Any
    start_time: datetime
    input_data: Any


def track_agent_start_and_emit(
    backend: Any,
    emit_event_fn: Any,
    params: AgentStartParams,
) -> None:
    """Record agent start in backend and emit event.

    Args:
        backend: Observability backend
        emit_event_fn: Event emission function
        params: AgentStartParams with all agent start parameters
    """
    backend.track_agent_start(
        agent_id=params.agent_id, stage_id=params.stage_id, agent_name=params.agent_name,
        agent_config=params.sanitized_config, start_time=params.start_time, input_data=params.input_data
    )
    emit_event_fn("agent_start", {
        ObservabilityFields.AGENT_ID: params.agent_id,
        ObservabilityFields.STAGE_ID: params.stage_id,
        ObservabilityFields.AGENT_NAME: params.agent_name,
        ObservabilityFields.START_TIME: params.start_time.isoformat(),
    })


def handle_workflow_success(
    backend: Any,
    alert_manager: Any,
    emit_event_fn: Any,
    workflow_id: str,
) -> None:
    """Handle successful workflow completion."""
    end_time = utcnow()
    backend.track_workflow_end(
        workflow_id=workflow_id, end_time=end_time,
        status=ObservabilityFields.STATUS_COMPLETED,
        error_message=None, error_stack_trace=None,
    )
    emit_event_fn("workflow_end", {
        ObservabilityFields.WORKFLOW_ID: workflow_id,
        ObservabilityFields.STATUS: ObservabilityFields.STATUS_COMPLETED,
        ObservabilityFields.END_TIME: end_time.isoformat(),
    })
    aggregate_workflow_metrics_on_success(
        backend=backend, alert_manager=alert_manager, workflow_id=workflow_id,
    )


def handle_workflow_error(
    backend: Any,
    emit_event_fn: Any,
    get_stack_trace_fn: Any,
    workflow_id: str,
    error: Exception,
) -> None:
    """Handle workflow execution error."""
    end_time = utcnow()
    backend.track_workflow_end(
        workflow_id=workflow_id, end_time=end_time,
        status=ObservabilityFields.STATUS_FAILED,
        error_message=str(error), error_stack_trace=get_stack_trace_fn(),
    )
    emit_event_fn("workflow_end", {
        ObservabilityFields.WORKFLOW_ID: workflow_id,
        ObservabilityFields.STATUS: ObservabilityFields.STATUS_FAILED,
        ObservabilityFields.END_TIME: end_time.isoformat(),
        ObservabilityFields.ERROR_MESSAGE: str(error),
    })


def handle_stage_success(
    backend: Any,
    emit_event_fn: Any,
    stage_id: str,
) -> None:
    """Handle successful stage completion."""
    end_time = utcnow()
    try:
        if hasattr(backend, 'aggregate_stage_metrics'):
            metrics = backend.aggregate_stage_metrics(stage_id)
            backend.track_stage_end(
                stage_id=stage_id, end_time=end_time,
                status=ObservabilityFields.STATUS_COMPLETED,
                error_message=None,
                num_agents_executed=metrics.get('num_agents_executed', 0),
                num_agents_succeeded=metrics.get('num_agents_succeeded', 0),
                num_agents_failed=metrics.get('num_agents_failed', 0),
            )
        else:
            backend.track_stage_end(
                stage_id=stage_id, end_time=end_time,
                status=ObservabilityFields.STATUS_COMPLETED,
            )
    except Exception as e:
        logger.warning(
            f"Failed to aggregate stage metrics for {stage_id}: {e}",
            exc_info=True,
        )
        backend.track_stage_end(
            stage_id=stage_id, end_time=end_time,
            status=ObservabilityFields.STATUS_COMPLETED,
        )
    emit_event_fn("stage_end", {
        ObservabilityFields.STAGE_ID: stage_id,
        ObservabilityFields.STATUS: ObservabilityFields.STATUS_COMPLETED,
        ObservabilityFields.END_TIME: end_time.isoformat(),
    })


def handle_stage_error(
    backend: Any,
    emit_event_fn: Any,
    stage_id: str,
    error: Exception,
) -> None:
    """Handle stage execution error."""
    end_time = utcnow()
    backend.track_stage_end(
        stage_id=stage_id, end_time=end_time,
        status=ObservabilityFields.STATUS_FAILED,
        error_message=str(error),
    )
    emit_event_fn("stage_end", {
        ObservabilityFields.STAGE_ID: stage_id,
        ObservabilityFields.STATUS: ObservabilityFields.STATUS_FAILED,
        ObservabilityFields.END_TIME: end_time.isoformat(),
        ObservabilityFields.ERROR_MESSAGE: str(error),
    })


def handle_agent_success(
    backend: Any,
    emit_event_fn: Any,
    collect_metrics_fn: Any,
    agent_id: str,
) -> None:
    """Handle successful agent completion."""
    end_time = utcnow()
    backend.track_agent_end(
        agent_id=agent_id, end_time=end_time,
        status=ObservabilityFields.STATUS_COMPLETED,
    )
    emit_event_fn("agent_end", {
        ObservabilityFields.AGENT_ID: agent_id,
        ObservabilityFields.STATUS: ObservabilityFields.STATUS_COMPLETED,
        ObservabilityFields.END_TIME: end_time.isoformat(),
    })
    collect_metrics_fn(agent_id)


def handle_agent_error(
    backend: Any,
    emit_event_fn: Any,
    agent_id: str,
    error: Exception,
) -> None:
    """Handle agent execution error."""
    end_time = utcnow()
    backend.track_agent_end(
        agent_id=agent_id, end_time=end_time,
        status=ObservabilityFields.STATUS_FAILED,
        error_message=str(error),
    )
    emit_event_fn("agent_end", {
        ObservabilityFields.AGENT_ID: agent_id,
        ObservabilityFields.STATUS: ObservabilityFields.STATUS_FAILED,
        ObservabilityFields.END_TIME: end_time.isoformat(),
        ObservabilityFields.ERROR_MESSAGE: str(error),
    })


def emit_llm_stream_chunk(
    event_bus: Any,
    data: StreamChunkData,
) -> None:
    """Emit an LLM stream chunk event for real-time consumers.

    Best-effort: catches all exceptions silently since streaming events
    must never disrupt execution.

    Args:
        event_bus: Event bus for real-time events
        data: StreamChunkData with all event parameters
    """
    if event_bus is None:
        return
    try:
        from src.observability.event_bus import ObservabilityEvent

        event_bus.emit(ObservabilityEvent(
            event_type=_EVENT_LLM_STREAM_CHUNK,
            timestamp=utcnow(),
            data={
                ObservabilityFields.AGENT_ID: data.agent_id,
                "content": data.content,
                "chunk_type": data.chunk_type,
                "done": data.done,
                "model": data.model,
                "prompt_tokens": data.prompt_tokens,
                "completion_tokens": data.completion_tokens,
            },
            workflow_id=data.workflow_id,
            stage_id=data.stage_id,
            agent_id=data.agent_id,
        ))
    except Exception:  # noqa: BLE001 -- best-effort streaming event
        pass


class TrackerCollaborationMixin:
    """Mixin providing collaboration, safety, and merit tracking methods.

    Mixed into ExecutionTracker to reduce god-class method count.
    Expects self._collaboration_tracker, self._decision_tracker,
    self.backend, self._session_stack, self._emit_event().
    """

    _collaboration_tracker: Any
    _decision_tracker: Any
    backend: Any
    _emit_event: Any

    @property
    def _session_stack(self) -> List[Any]:
        """Session stack for current workflow context (overridden in subclass)."""
        return []

    def track_safety_violation(
        self,
        violation_severity: Literal["INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL"],
        violation_message: str,
        policy_name: str,
        service_name: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Track safety violation."""
        self._collaboration_tracker.track_safety_violation(
            violation_severity=violation_severity,
            violation_message=violation_message,
            policy_name=policy_name,
            service_name=service_name,
            context=context,
        )
        self._emit_event(_EVENT_SAFETY_VIOLATION, {
            "violation_severity": violation_severity,
            "violation_message": violation_message,
            "policy_name": policy_name,
            "service_name": service_name,
        })

    def track_collaboration_event(
        self,
        data: CollaborationEventData,
    ) -> str:
        """Track collaboration event.

        Args:
            data: CollaborationEventData with all event parameters

        Returns:
            Event ID string
        """
        from src.observability.collaboration_tracker import CollaborationEventParams
        params = CollaborationEventParams(
            event_type=data.event_type,
            stage_id=data.stage_id,
            agents_involved=data.agents_involved,
            event_data=data.event_data,
            round_number=data.round_number,
            resolution_strategy=data.resolution_strategy,
            outcome=data.outcome,
            confidence_score=data.confidence_score,
            extra_metadata=data.extra_metadata
        )
        result = self._collaboration_tracker.track_collaboration_event(params=params)
        self._emit_event(_EVENT_COLLABORATION, {
            "event_type": data.event_type,
            ObservabilityFields.STAGE_ID: data.stage_id,
            "agents_involved": data.agents_involved,
            "outcome": data.outcome,
            "confidence_score": data.confidence_score,
        })
        return str(result)

    def update_agent_merit_score(
        self,
        agent_name: str,
        domain: str,
        decision_outcome: str,
        confidence: Optional[float] = None,
    ) -> None:
        """Update agent merit score based on decision outcome."""
        update_agent_merit_score(
            decision_tracker=self._decision_tracker,
            backend=self.backend,
            session_stack=self._session_stack,
            agent_name=agent_name,
            domain=domain,
            decision_outcome=decision_outcome,
            confidence=confidence,
        )
