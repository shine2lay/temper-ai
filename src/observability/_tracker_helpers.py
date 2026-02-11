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
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from src.constants.durations import MILLISECONDS_PER_SECOND
from src.constants.limits import THRESHOLD_MEDIUM_COUNT
from src.database.datetime_utils import utcnow

logger = logging.getLogger(__name__)


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
            safe_key_result = sanitizer.sanitize_text(str(key), context="config")
            safe_key = safe_key_result.sanitized_text

            # Recursively sanitize value based on type
            if isinstance(value, dict):
                sanitized[safe_key] = sanitize_dict(sanitizer, value, _depth + 1)
            elif isinstance(value, list):
                sanitized_list: List[Any] = [
                    sanitize_dict(sanitizer, item, _depth + 1) if isinstance(item, dict)
                    else sanitizer.sanitize_text(str(item), context="config").sanitized_text
                    if isinstance(item, str)
                    else item
                    for item in value
                ]
                sanitized[safe_key] = sanitized_list
            elif isinstance(value, str):
                result = sanitizer.sanitize_text(value, context="config")
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
    result = sanitizer.sanitize_text(raw_trace, context="stack_trace")
    return str(result.sanitized_text)


def track_llm_call(
    sanitizer: Any,
    backend: Any,
    alert_manager: Any,
    agent_id: str,
    provider: str,
    model: str,
    prompt: str,
    response: str,
    prompt_tokens: int,
    completion_tokens: int,
    latency_ms: int,
    estimated_cost_usd: float,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    status: str = "success",
    error_message: Optional[str] = None,
    event_bus: Any = None,
) -> str:
    """Track LLM call with automatic sanitization.

    Args:
        sanitizer: DataSanitizer instance
        backend: ObservabilityBackend instance
        alert_manager: AlertManager instance (or None)
        agent_id: Parent agent execution ID
        provider: LLM provider
        model: Model name
        prompt: Input prompt (will be sanitized)
        response: LLM response (will be sanitized)
        prompt_tokens: Number of prompt tokens
        completion_tokens: Number of completion tokens
        latency_ms: Latency in milliseconds
        estimated_cost_usd: Estimated cost
        temperature: Temperature setting
        max_tokens: Max tokens setting
        status: Call status
        error_message: Error if failed

    Returns:
        llm_call_id: UUID of the LLM call

    Raises:
        ValueError: If numeric parameters are negative
    """
    # VALIDATION: Validate numeric parameters are non-negative
    if prompt_tokens < 0:
        raise ValueError(f"prompt_tokens must be non-negative, got {prompt_tokens}")
    if completion_tokens < 0:
        raise ValueError(f"completion_tokens must be non-negative, got {completion_tokens}")
    if latency_ms < 0:
        raise ValueError(f"latency_ms must be non-negative, got {latency_ms}")
    if estimated_cost_usd < 0:
        raise ValueError(f"estimated_cost_usd must be non-negative, got {estimated_cost_usd}")

    llm_call_id = str(uuid.uuid4())
    start_time = utcnow()

    # SECURITY: Sanitize prompt and response before storage
    prompt_result = sanitizer.sanitize_text(prompt, context="prompt")
    response_result = sanitizer.sanitize_text(response, context="response")

    # SECURITY: Sanitize error message as well (may contain prompt fragments)
    safe_error_message = None
    if error_message:
        error_result = sanitizer.sanitize_text(error_message, context="error")
        safe_error_message = error_result.sanitized_text

    # Log sanitization activity if redactions were made
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

    # Track LLM call with sanitized content
    backend.track_llm_call(
        llm_call_id=llm_call_id,
        agent_id=agent_id,
        provider=provider,
        model=model,
        prompt=prompt_result.sanitized_text,
        response=response_result.sanitized_text,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        latency_ms=latency_ms,
        estimated_cost_usd=estimated_cost_usd,
        start_time=start_time,
        temperature=temperature,
        max_tokens=max_tokens,
        status=status,
        error_message=safe_error_message,
    )

    # Emit event for real-time consumers
    if event_bus is not None:
        from src.observability.event_bus import ObservabilityEvent

        event_bus.emit(ObservabilityEvent(
            event_type="llm_call",
            timestamp=start_time,
            data={
                "llm_call_id": llm_call_id,
                "agent_id": agent_id,
                "provider": provider,
                "model": model,
                "prompt": prompt_result.sanitized_text,
                "response": response_result.sanitized_text,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "latency_ms": latency_ms,
                "estimated_cost_usd": estimated_cost_usd,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "status": status,
                "error_message": safe_error_message,
            },
            agent_id=agent_id,
        ))

    # Check latency and cost alerts
    if alert_manager:
        if latency_ms > 0:
            alert_manager.check_metric(
                metric_type="latency_p99",
                value=latency_ms,
                context={
                    "agent_id": agent_id,
                    "provider": provider,
                    "model": model,
                    "llm_call_id": llm_call_id
                }
            )

        if estimated_cost_usd > 0:
            alert_manager.check_metric(
                metric_type="cost_usd",
                value=estimated_cost_usd,
                context={
                    "agent_id": agent_id,
                    "provider": provider,
                    "model": model,
                    "llm_call_id": llm_call_id
                }
            )

    return llm_call_id


def track_tool_call(
    sanitize_dict_fn: Any,
    backend: Any,
    alert_manager: Any,
    agent_id: str,
    tool_name: str,
    input_params: Dict[str, Any],
    output_data: Dict[str, Any],
    duration_seconds: float,
    status: str = "success",
    error_message: Optional[str] = None,
    safety_checks: Optional[List[str]] = None,
    approval_required: bool = False,
    event_bus: Any = None,
) -> str:
    """Track tool execution.

    Args:
        sanitize_dict_fn: Callable to sanitize dicts
        backend: ObservabilityBackend instance
        alert_manager: AlertManager instance (or None)
        agent_id: Parent agent execution ID
        tool_name: Name of the tool
        input_params: Tool input parameters
        output_data: Tool output data
        duration_seconds: Execution duration
        status: Execution status
        error_message: Error if failed
        safety_checks: Safety checks applied
        approval_required: Whether approval was required

    Returns:
        tool_execution_id: UUID of the tool execution
    """
    tool_execution_id = str(uuid.uuid4())
    start_time = utcnow()

    # SECURITY: Sanitize tool parameters before storage
    sanitized_input = sanitize_dict_fn(input_params)
    sanitized_output = sanitize_dict_fn(output_data)

    backend.track_tool_call(
        tool_execution_id=tool_execution_id,
        agent_id=agent_id,
        tool_name=tool_name,
        input_params=sanitized_input,
        output_data=sanitized_output,
        start_time=start_time,
        duration_seconds=duration_seconds,
        status=status,
        error_message=error_message,
        safety_checks=safety_checks,
        approval_required=approval_required,
    )

    # Emit event for real-time consumers
    if event_bus is not None:
        from src.observability.event_bus import ObservabilityEvent

        event_bus.emit(ObservabilityEvent(
            event_type="tool_call",
            timestamp=start_time,
            data={
                "tool_execution_id": tool_execution_id,
                "agent_id": agent_id,
                "tool_name": tool_name,
                "input_params": sanitized_input,
                "output_data": sanitized_output,
                "duration_seconds": duration_seconds,
                "status": status,
                "error_message": error_message,
                "safety_checks": safety_checks,
                "approval_required": approval_required,
            },
            agent_id=agent_id,
        ))

    # Check tool execution duration alerts
    if alert_manager and duration_seconds > 0:
        duration_ms = duration_seconds * MILLISECONDS_PER_SECOND
        alert_manager.check_metric(
            metric_type="duration",
            value=duration_ms,
            context={
                "agent_id": agent_id,
                "tool_name": tool_name,
                "tool_execution_id": tool_execution_id,
                "status": status
            }
        )

    return tool_execution_id


def track_decision_outcome(
    decision_tracker: Any,
    backend: Any,
    context: Any,
    session_stack: List[Any],
    decision_type: str,
    decision_data: Dict[str, Any],
    outcome: str,
    impact_metrics: Optional[Dict[str, Any]] = None,
    lessons_learned: Optional[str] = None,
    should_repeat: Optional[bool] = None,
    tags: Optional[List[str]] = None,
    agent_execution_id: Optional[str] = None,
    stage_execution_id: Optional[str] = None,
    workflow_execution_id: Optional[str] = None,
    validation_method: Optional[str] = None,
    validation_timestamp: Optional[datetime] = None,
    validation_duration_seconds: Optional[float] = None,
    extra_metadata: Optional[Dict[str, Any]] = None,
) -> str:
    """Track decision outcome for self-improvement learning loop.

    Returns:
        Decision ID or empty string on failure
    """
    # Fill in execution IDs from context if not provided
    if not workflow_execution_id:
        workflow_execution_id = context.workflow_id
    if not stage_execution_id:
        stage_execution_id = context.stage_id
    if not agent_execution_id:
        agent_execution_id = context.agent_id

    kwargs = dict(
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

    result: str
    if session_stack:
        result = str(decision_tracker.track(
            session=session_stack[-1], **kwargs
        ))
    else:
        with backend.get_session_context() as session:
            result = str(decision_tracker.track(session=session, **kwargs))

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
                "agent_name": agent_name,
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
                total_cost = metrics.get('total_cost_usd', 0.0)
                backend.update_workflow_metrics(
                    workflow_id=workflow_id,
                    total_llm_calls=metrics.get('total_llm_calls', 0),
                    total_tool_calls=metrics.get('total_tool_calls', 0),
                    total_tokens=metrics.get('total_tokens', 0),
                    total_cost_usd=total_cost
                )
                if alert_manager and total_cost > 0:
                    alert_manager.check_metric(
                        metric_type="cost_usd", value=total_cost,
                        context={"workflow_id": workflow_id}
                    )
    except Exception as e:
        logger.warning(
            f"Failed to aggregate workflow metrics for {workflow_id}: {e}",
            exc_info=True,
        )


class TrackerCollaborationMixin:
    """Mixin providing collaboration, safety, and merit tracking methods.

    Mixed into ExecutionTracker to reduce god-class method count.
    Expects self._collaboration_tracker, self._decision_tracker,
    self.backend, self._session_stack, self._emit_event().
    """

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
        self._emit_event("safety_violation", {
            "violation_severity": violation_severity,
            "violation_message": violation_message,
            "policy_name": policy_name,
            "service_name": service_name,
        })

    def track_collaboration_event(
        self,
        event_type: str,
        stage_id: Optional[str] = None,
        agents_involved: Optional[List[str]] = None,
        event_data: Optional[Dict[str, Any]] = None,
        round_number: Optional[int] = None,
        resolution_strategy: Optional[str] = None,
        outcome: Optional[str] = None,
        confidence_score: Optional[float] = None,
        extra_metadata: Optional[Dict[str, Any]] = None,
        stage_name: Optional[str] = None,
        agents: Optional[List[str]] = None,
        decision: Optional[str] = None,
        confidence: Optional[float] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Track collaboration event."""
        result = self._collaboration_tracker.track_collaboration_event(
            event_type=event_type, stage_id=stage_id,
            agents_involved=agents_involved, event_data=event_data,
            round_number=round_number, resolution_strategy=resolution_strategy,
            outcome=outcome, confidence_score=confidence_score,
            extra_metadata=extra_metadata, stage_name=stage_name,
            agents=agents, decision=decision, confidence=confidence,
            metadata=metadata,
        )
        self._emit_event("collaboration_event", {
            "event_type": event_type,
            "stage_id": stage_id,
            "agents_involved": agents_involved,
            "outcome": outcome,
            "confidence_score": confidence_score,
        })
        return result

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
