"""
Execution tracker for observability.

Tracks workflow, stage, agent, LLM, and tool executions in real-time,
writing to pluggable observability backends (SQL, Prometheus, S3, etc.).
"""
import uuid
import logging
from datetime import datetime, timezone
from contextlib import contextmanager
from typing import Optional, Dict, Any, List, Generator
from dataclasses import dataclass

from src.observability.backend import ObservabilityBackend
from src.observability.sanitization import DataSanitizer, SanitizationConfig
from src.utils.config_helpers import sanitize_config_for_display

logger = logging.getLogger(__name__)


def utcnow() -> datetime:
    """Get current UTC time with timezone awareness."""
    return datetime.now(timezone.utc)


@dataclass
class ExecutionContext:
    """Context for current execution."""
    workflow_id: Optional[str] = None
    stage_id: Optional[str] = None
    agent_id: Optional[str] = None


class ExecutionTracker:
    """
    Tracks execution using pluggable observability backends.

    Provides context managers for tracking different execution levels:
    - workflow
    - stage
    - agent
    - LLM call
    - tool call

    Each level automatically:
    - Creates record with status="running"
    - Tracks start/end times
    - Calculates duration
    - Updates metrics
    - Handles errors

    Backend Abstraction:
    - Supports multiple backends (SQL, Prometheus, S3, etc.)
    - Backend-specific optimizations (session reuse, batching, etc.)
    - Defaults to SQLObservabilityBackend for backward compatibility

    Example:
        >>> from src.observability.backends import SQLObservabilityBackend
        >>> backend = SQLObservabilityBackend()
        >>> tracker = ExecutionTracker(backend=backend)
        >>> with tracker.track_workflow("research", config) as workflow_id:
        ...     with tracker.track_stage("analyze", config, workflow_id) as stage_id:
        ...         with tracker.track_agent("researcher", config, stage_id) as agent_id:
        ...             tracker.track_llm_call(agent_id, llm_response)
        ...             tracker.track_tool_call(agent_id, tool_name, params, result)
    """

    def __init__(
        self,
        backend: Optional[ObservabilityBackend] = None,
        sanitization_config: Optional[SanitizationConfig] = None
    ):
        """
        Initialize execution tracker with sanitization support.

        Args:
            backend: Observability backend to use. If None, defaults to SQLObservabilityBackend.
            sanitization_config: Configuration for data sanitization. If None, uses secure defaults.
        """
        self.context = ExecutionContext()

        # Use provided backend or default to SQL backend
        if backend is None:
            from src.observability.backends import SQLObservabilityBackend
            backend = SQLObservabilityBackend()

        self.backend = backend
        self._session_stack: List[Any] = []  # Stack of active sessions for nested contexts

        # Initialize sanitizer with provided or default config
        self.sanitizer = DataSanitizer(sanitization_config)

    @contextmanager
    def track_workflow(
        self,
        workflow_name: str,
        workflow_config: Dict[str, Any],
        trigger_type: Optional[str] = None,
        trigger_data: Optional[Dict[str, Any]] = None,
        optimization_target: Optional[str] = None,
        product_type: Optional[str] = None,
        environment: Optional[str] = "development",
        tags: Optional[List[str]] = None,
        experiment_id: Optional[str] = None,
        variant_id: Optional[str] = None,
        assignment_strategy: Optional[str] = None,
        assignment_context: Optional[Dict[str, Any]] = None,
        custom_metrics: Optional[Dict[str, Any]] = None
    ) -> Generator[str, None, None]:
        """
        Track workflow execution.

        Args:
            workflow_name: Name of the workflow
            workflow_config: Full workflow configuration
            trigger_type: How workflow was triggered (manual, cron, event)
            trigger_data: Trigger metadata
            experiment_id: Optional experiment ID for A/B testing
            variant_id: Optional variant ID for A/B testing
            assignment_strategy: Optional assignment strategy used
            assignment_context: Optional context used for assignment
            custom_metrics: Optional custom metrics to track
            optimization_target: Current optimization target (speed, quality, cost)
            product_type: Type of product being built
            environment: Execution environment (dev, staging, prod)
            tags: Additional tags

        Yields:
            workflow_id: UUID of the workflow execution

        Example:
            >>> with tracker.track_workflow("research", config) as workflow_id:
            ...     # Run workflow stages
            ...     pass
        """
        workflow_id = str(uuid.uuid4())
        self.context.workflow_id = workflow_id

        start_time = utcnow()
        # Sanitize config snapshot to prevent secrets in backend
        sanitized_config = sanitize_config_for_display(workflow_config)

        # Build extra_metadata with experiment info and custom metrics
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

        # Use backend session context (backend handles session management)
        with self.backend.get_session_context() as session:
            # Push session onto stack for child operations to use
            self._session_stack.append(session)

            # Record workflow start via backend
            self.backend.track_workflow_start(
                workflow_id=workflow_id,
                workflow_name=workflow_name,
                workflow_config=sanitized_config,
                start_time=start_time,
                trigger_type=trigger_type,
                trigger_data=trigger_data,
                optimization_target=optimization_target,
                product_type=product_type,
                environment=environment,
                tags=tags,
                extra_metadata=extra_metadata if extra_metadata else None
            )

            try:
                yield workflow_id

                # Success - update final status
                end_time = utcnow()

                self.backend.track_workflow_end(
                    workflow_id=workflow_id,
                    end_time=end_time,
                    status="completed",
                    error_message=None,
                    error_stack_trace=None
                )

                # Aggregate and update metrics (backend handles aggregation logic)
                # Only for SQL backend - other backends handle metrics differently
                try:
                    from sqlmodel import select, func
                    from src.observability.models import AgentExecution, StageExecution

                    if hasattr(session, 'exec') and session is not None:
                        metrics_statement = select(
                            func.sum(AgentExecution.num_llm_calls).label('total_llm_calls'),
                            func.sum(AgentExecution.num_tool_calls).label('total_tool_calls'),
                            func.sum(AgentExecution.total_tokens).label('total_tokens'),
                            func.sum(AgentExecution.estimated_cost_usd).label('total_cost_usd')
                        ).join(
                            StageExecution,
                            AgentExecution.stage_execution_id == StageExecution.id  # type: ignore[arg-type]
                        ).where(StageExecution.workflow_execution_id == workflow_id)

                        metrics = session.exec(metrics_statement).first()

                        if metrics:
                            self.backend.update_workflow_metrics(
                                workflow_id=workflow_id,
                                total_llm_calls=int(metrics.total_llm_calls or 0),
                                total_tool_calls=int(metrics.total_tool_calls or 0),
                                total_tokens=int(metrics.total_tokens or 0),
                                total_cost_usd=float(metrics.total_cost_usd or 0.0)
                            )
                except (ImportError, AttributeError):
                    # Non-SQL backends don't need metric aggregation
                    # Expected when backend doesn't support SQL queries
                    pass
                except Exception as e:
                    # Unexpected error during metric aggregation
                    # Log and continue (don't fail workflow for observability issues)
                    logger.warning(
                        f"Failed to aggregate workflow metrics for {workflow_id}: {e}",
                        exc_info=True
                    )

            except Exception as e:
                # Failure - record error
                end_time = utcnow()

                self.backend.track_workflow_end(
                    workflow_id=workflow_id,
                    end_time=end_time,
                    status="failed",
                    error_message=str(e),
                    error_stack_trace=self._get_stack_trace()
                )
                raise

            finally:
                # Pop session from stack
                self._session_stack.pop()
                self.context.workflow_id = None

    @contextmanager
    def track_stage(
        self,
        stage_name: str,
        stage_config: Dict[str, Any],
        workflow_id: str,
        input_data: Optional[Dict[str, Any]] = None
    ) -> Generator[str, None, None]:
        """
        Track stage execution.

        Args:
            stage_name: Name of the stage
            stage_config: Stage configuration
            workflow_id: Parent workflow ID
            input_data: Stage input data

        Yields:
            stage_id: UUID of the stage execution

        Example:
            >>> with tracker.track_stage("research", config, workflow_id) as stage_id:
            ...     # Run stage agents
            ...     pass
        """
        stage_id = str(uuid.uuid4())
        self.context.stage_id = stage_id

        start_time = utcnow()
        # Sanitize config snapshot to prevent secrets in backend
        sanitized_config = sanitize_config_for_display(stage_config)

        # Reuse parent session if available, otherwise create new one
        if self._session_stack:
            # Use parent workflow's session
            self.backend.track_stage_start(
                stage_id=stage_id,
                workflow_id=workflow_id,
                stage_name=stage_name,
                stage_config=sanitized_config,
                start_time=start_time,
                input_data=input_data
            )

            try:
                yield stage_id

                # Success
                end_time = utcnow()

                # Aggregate metrics from child agents (SQL backend only)
                try:
                    from sqlmodel import select, func
                    from sqlalchemy import case
                    from src.observability.models import AgentExecution

                    session = self._session_stack[-1] if self._session_stack else None
                    if hasattr(session, 'exec') and session is not None:
                        metrics_statement = select(
                            func.count(AgentExecution.id).label('total'),  # type: ignore[arg-type]
                            func.sum(case((AgentExecution.status == 'completed', 1), else_=0)).label('succeeded'),  # type: ignore[arg-type]
                            func.sum(case((AgentExecution.status == 'failed', 1), else_=0)).label('failed')  # type: ignore[arg-type]
                        ).where(AgentExecution.stage_execution_id == stage_id)

                        metrics = session.exec(metrics_statement).first()

                        self.backend.track_stage_end(
                            stage_id=stage_id,
                            end_time=end_time,
                            status="completed",
                            error_message=None,
                            num_agents_executed=int(metrics.total or 0) if metrics else 0,
                            num_agents_succeeded=int(metrics.succeeded or 0) if metrics else 0,
                            num_agents_failed=int(metrics.failed or 0) if metrics else 0
                        )
                    else:
                        self.backend.track_stage_end(
                            stage_id=stage_id,
                            end_time=end_time,
                            status="completed"
                        )
                except (ImportError, AttributeError):
                    # Expected for non-SQL backends (Prometheus, S3, etc.)
                    # - ImportError: sqlmodel/sqlalchemy not available
                    # - AttributeError: session doesn't have 'exec' method
                    self.backend.track_stage_end(
                        stage_id=stage_id,
                        end_time=end_time,
                        status="completed"
                    )
                except Exception as e:
                    # Unexpected error during stage metric aggregation
                    # Log and continue (don't fail stage for observability issues)
                    logger.warning(
                        f"Failed to aggregate stage metrics for {stage_id}: {e}",
                        exc_info=True
                    )
                    # Fallback: complete stage without detailed metrics
                    self.backend.track_stage_end(
                        stage_id=stage_id,
                        end_time=end_time,
                        status="completed"
                    )

            except Exception as e:
                # Failure
                end_time = utcnow()

                self.backend.track_stage_end(
                    stage_id=stage_id,
                    end_time=end_time,
                    status="failed",
                    error_message=str(e)
                )
                raise

            finally:
                self.context.stage_id = None
        else:
            # Standalone stage execution (no parent workflow) - create own session
            with self.backend.get_session_context() as session:
                self._session_stack.append(session)

                self.backend.track_stage_start(
                    stage_id=stage_id,
                    workflow_id=workflow_id,
                    stage_name=stage_name,
                    stage_config=sanitized_config,
                    start_time=start_time,
                    input_data=input_data
                )

                try:
                    yield stage_id

                    # Success
                    end_time = utcnow()
                    self.backend.track_stage_end(
                        stage_id=stage_id,
                        end_time=end_time,
                        status="completed"
                    )

                except Exception as e:
                    # Failure
                    end_time = utcnow()
                    self.backend.track_stage_end(
                        stage_id=stage_id,
                        end_time=end_time,
                        status="failed",
                        error_message=str(e)
                    )
                    raise

                finally:
                    self._session_stack.pop()
                    self.context.stage_id = None

    @contextmanager
    def track_agent(
        self,
        agent_name: str,
        agent_config: Dict[str, Any],
        stage_id: str,
        input_data: Optional[Dict[str, Any]] = None
    ) -> Generator[str, None, None]:
        """
        Track agent execution.

        Args:
            agent_name: Name of the agent
            agent_config: Agent configuration
            stage_id: Parent stage ID
            input_data: Agent input data

        Yields:
            agent_id: UUID of the agent execution

        Example:
            >>> with tracker.track_agent("researcher", config, stage_id) as agent_id:
            ...     # Run agent
            ...     tracker.track_llm_call(agent_id, llm_response)
        """
        agent_id = str(uuid.uuid4())
        self.context.agent_id = agent_id

        start_time = utcnow()
        # Sanitize config snapshot to prevent secrets in backend
        sanitized_config = sanitize_config_for_display(agent_config)

        # Reuse parent session if available, otherwise create new one
        if self._session_stack:
            # Use parent stage's session
            self.backend.track_agent_start(
                agent_id=agent_id,
                stage_id=stage_id,
                agent_name=agent_name,
                agent_config=sanitized_config,
                start_time=start_time,
                input_data=input_data
            )

            try:
                yield agent_id

                # Success
                end_time = utcnow()
                self.backend.track_agent_end(
                    agent_id=agent_id,
                    end_time=end_time,
                    status="completed"
                )

            except Exception as e:
                # Failure
                end_time = utcnow()
                self.backend.track_agent_end(
                    agent_id=agent_id,
                    end_time=end_time,
                    status="failed",
                    error_message=str(e)
                )
                raise

            finally:
                self.context.agent_id = None
        else:
            # Standalone agent execution (no parent stage) - create own session
            with self.backend.get_session_context() as session:
                self._session_stack.append(session)

                self.backend.track_agent_start(
                    agent_id=agent_id,
                    stage_id=stage_id,
                    agent_name=agent_name,
                    agent_config=sanitized_config,
                    start_time=start_time,
                    input_data=input_data
                )

                try:
                    yield agent_id

                    # Success
                    end_time = utcnow()
                    self.backend.track_agent_end(
                        agent_id=agent_id,
                        end_time=end_time,
                        status="completed"
                    )

                except Exception as e:
                    # Failure
                    end_time = utcnow()
                    self.backend.track_agent_end(
                        agent_id=agent_id,
                        end_time=end_time,
                        status="failed",
                        error_message=str(e)
                    )
                    raise

                finally:
                    self._session_stack.pop()
                    self.context.agent_id = None

    def track_llm_call(
        self,
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
        error_message: Optional[str] = None
    ) -> str:
        """
        Track LLM call with automatic sanitization.

        Automatically redacts:
        - Secrets (API keys, tokens, passwords)
        - PII (emails, SSNs, phone numbers)
        - Truncates large payloads

        Args:
            agent_id: Parent agent execution ID
            provider: LLM provider (ollama, openai, anthropic)
            model: Model name
            prompt: Input prompt (will be sanitized before storage)
            response: LLM response (will be sanitized before storage)
            prompt_tokens: Number of prompt tokens
            completion_tokens: Number of completion tokens
            latency_ms: Latency in milliseconds
            estimated_cost_usd: Estimated cost
            temperature: Temperature setting
            max_tokens: Max tokens setting
            status: Call status (success, failed)
            error_message: Error if failed

        Returns:
            llm_call_id: UUID of the LLM call

        Example:
            >>> call_id = tracker.track_llm_call(
            ...     agent_id,
            ...     "ollama",
            ...     "llama3.2:3b",
            ...     "Hello",
            ...     "Hi there!",
            ...     10, 5, 250, 0.001
            ... )

        Raises:
            ValueError: If numeric parameters are negative
        """
        # VALIDATION (code-medi-13): Validate numeric parameters are non-negative
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
        prompt_result = self.sanitizer.sanitize_text(prompt, context="prompt")
        response_result = self.sanitizer.sanitize_text(response, context="response")

        # SECURITY: Sanitize error message as well (may contain prompt fragments)
        safe_error_message = None
        if error_message:
            error_result = self.sanitizer.sanitize_text(error_message, context="error")
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
        self.backend.track_llm_call(
            llm_call_id=llm_call_id,
            agent_id=agent_id,
            provider=provider,
            model=model,
            prompt=prompt_result.sanitized_text,  # Sanitized
            response=response_result.sanitized_text,  # Sanitized
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            latency_ms=latency_ms,
            estimated_cost_usd=estimated_cost_usd,
            start_time=start_time,
            temperature=temperature,
            max_tokens=max_tokens,
            status=status,
            error_message=safe_error_message  # Sanitized
        )

        # NOTE: Sanitization metadata (redaction counts, hashes, etc.) is available
        # via prompt_result.to_metadata() and response_result.to_metadata() but
        # is currently logged only, not stored in the database extra_metadata field.
        # This is sufficient for security purposes - the important thing is that
        # secrets/PII are redacted from the stored prompt/response.

        return llm_call_id

    def track_tool_call(
        self,
        agent_id: str,
        tool_name: str,
        input_params: Dict[str, Any],
        output_data: Dict[str, Any],
        duration_seconds: float,
        status: str = "success",
        error_message: Optional[str] = None,
        safety_checks: Optional[List[str]] = None,
        approval_required: bool = False
    ) -> str:
        """
        Track tool execution.

        Args:
            agent_id: Parent agent execution ID
            tool_name: Name of the tool
            input_params: Tool input parameters
            output_data: Tool output data
            duration_seconds: Execution duration
            status: Execution status (success, failed)
            error_message: Error if failed
            safety_checks: Safety checks applied
            approval_required: Whether approval was required

        Returns:
            tool_execution_id: UUID of the tool execution

        Example:
            >>> tool_id = tracker.track_tool_call(
            ...     agent_id,
            ...     "calculator",
            ...     {"operation": "add", "a": 1, "b": 2},
            ...     {"result": 3},
            ...     0.01
            ... )
        """
        tool_execution_id = str(uuid.uuid4())
        start_time = utcnow()

        # SECURITY: Sanitize tool parameters before storage
        # Tools may receive/return credentials in parameters (e.g., Authorization headers)
        sanitized_input = self._sanitize_dict(input_params)
        sanitized_output = self._sanitize_dict(output_data)

        self.backend.track_tool_call(
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
            approval_required=approval_required
        )

        return tool_execution_id

    def _sanitize_dict(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Recursively sanitize dictionary values to remove secrets.

        SECURITY: Prevents credential exposure in tool parameters/outputs.
        Uses recursive traversal instead of JSON round-trip to avoid injection attacks.

        Args:
            data: Dictionary to sanitize

        Returns:
            Sanitized dictionary with secrets redacted
        """
        if not isinstance(data, dict):
            return data

        sanitized = {}
        for key, value in data.items():
            try:
                # Sanitize key as well (keys might contain secrets)
                safe_key_result = self.sanitizer.sanitize_text(str(key), context="config")
                safe_key = safe_key_result.sanitized_text

                # Recursively sanitize value based on type
                if isinstance(value, dict):
                    sanitized[safe_key] = self._sanitize_dict(value)
                elif isinstance(value, list):
                    sanitized[safe_key] = [
                        self._sanitize_dict(item) if isinstance(item, dict)
                        else self.sanitizer.sanitize_text(str(item), context="config").sanitized_text
                        if isinstance(item, str)
                        else item
                        for item in value
                    ]
                elif isinstance(value, str):
                    result = self.sanitizer.sanitize_text(value, context="config")
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

    def _get_stack_trace(self) -> str:
        """Get current exception stack trace."""
        import traceback
        return traceback.format_exc()

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
        """
        Set agent output data after execution.

        Args:
            agent_id: Agent execution ID
            output_data: Agent output data
            reasoning: Agent reasoning text
            confidence_score: Confidence score (0-1)
            total_tokens: Total tokens used
            prompt_tokens: Prompt tokens used
            completion_tokens: Completion tokens used
            estimated_cost_usd: Estimated cost in USD
            num_llm_calls: Number of LLM calls made
            num_tool_calls: Number of tool calls made
        """
        self.backend.set_agent_output(
            agent_id=agent_id,
            output_data=output_data,
            reasoning=reasoning,
            confidence_score=confidence_score,
            total_tokens=total_tokens,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            estimated_cost_usd=estimated_cost_usd,
            num_llm_calls=num_llm_calls,
            num_tool_calls=num_tool_calls
        )

    def set_stage_output(
        self,
        stage_id: str,
        output_data: Dict[str, Any]
    ) -> None:
        """
        Set stage output data after execution.

        Args:
            stage_id: Stage execution ID
            output_data: Stage output data
        """
        self.backend.set_stage_output(
            stage_id=stage_id,
            output_data=output_data
        )

    def track_safety_violation(
        self,
        violation_severity: str,
        violation_message: str,
        policy_name: str,
        service_name: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Track safety violation for observability and metrics.

        Records safety violations in the execution context for analysis,
        alerting, and policy enforcement monitoring.

        Args:
            violation_severity: Severity level (INFO, LOW, MEDIUM, HIGH, CRITICAL)
            violation_message: Detailed violation message
            policy_name: Name of policy that was violated
            service_name: Service that detected the violation
            context: Additional context (action, params, etc.)

        Example:
            >>> tracker.track_safety_violation(
            ...     violation_severity="HIGH",
            ...     violation_message="Path traversal attempt detected",
            ...     policy_name="PathAccessPolicy",
            ...     service_name="file_system_service",
            ...     context={"path": "/etc/passwd", "action": "read"}
            ... )
        """
        # Get current execution IDs from context
        workflow_id = self.context.workflow_id
        stage_id = self.context.stage_id
        agent_id = self.context.agent_id

        # SECURITY: Sanitize context to prevent sensitive data exposure
        # The context may contain detected secrets or PII that should not be logged
        sanitized_context = self._sanitize_dict(context) if context else None

        self.backend.track_safety_violation(
            workflow_id=workflow_id,
            stage_id=stage_id,
            agent_id=agent_id,
            violation_severity=violation_severity,
            violation_message=violation_message,
            policy_name=policy_name,
            service_name=service_name,
            context=sanitized_context,
            timestamp=utcnow()
        )

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
        # Legacy parameters for backward compatibility with executors
        stage_name: Optional[str] = None,
        agents: Optional[List[str]] = None,
        decision: Optional[str] = None,
        confidence: Optional[float] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Track collaboration event for multi-agent interactions.

        Records collaboration events such as voting, conflicts, resolutions,
        consensus building, and debate rounds for analysis and monitoring.

        Supports both schema-aligned parameters and legacy executor calls for
        backward compatibility.

        Args:
            event_type: Type of event (vote, conflict, resolution, consensus,
                debate_round, synthesis, quality_gate_failure, adaptive_mode_switch)
            stage_id: ID of the stage where collaboration occurred
            agents_involved: List of agent IDs participating
            event_data: Event-specific data (votes, positions, arguments)
            round_number: Round number for multi-round collaborations
            resolution_strategy: Strategy used for conflict resolution
            outcome: Final outcome of the collaboration event
            confidence_score: Confidence score of outcome (0.0-1.0)
            extra_metadata: Additional metadata for custom tracking

            # Legacy parameters (for backward compatibility):
            stage_name: Legacy parameter, maps to stage_id via context lookup
            agents: Legacy parameter, maps to agents_involved
            decision: Legacy parameter, maps to outcome
            confidence: Legacy parameter, maps to confidence_score
            metadata: Legacy parameter, maps to event_data

        Returns:
            str: ID of created collaboration event record (format: "collab-{12-char-hex}"),
                 or empty string if tracking failed (safe to ignore - tracking failures
                 do not break workflow execution)

        Example:
            >>> tracker.track_collaboration_event(
            ...     event_type="consensus",
            ...     stage_id="stage-123",
            ...     agents_involved=["agent-1", "agent-2", "agent-3"],
            ...     event_data={"votes": {"option_a": 2, "option_b": 1}},
            ...     resolution_strategy="consensus",
            ...     outcome="option_a",
            ...     confidence_score=0.85
            ... )
            'collab-456abc789def'
        """
        # Map legacy parameters to new schema
        if stage_name and not stage_id:
            stage_id = self.context.stage_id or stage_name

        if agents and not agents_involved:
            agents_involved = agents

        if decision is not None and not outcome:
            outcome = decision

        if confidence is not None and confidence_score is None:
            confidence_score = confidence

        if metadata and not event_data:
            event_data = metadata

        # Validation: Get stage_id from context if not provided
        if not stage_id:
            stage_id = self.context.stage_id
            if not stage_id:
                logger.warning(
                    "track_collaboration_event called without stage_id context",
                    extra={
                        "event_type": event_type,
                        "has_workflow_context": bool(self.context.workflow_id),
                        "has_stage_context": bool(self.context.stage_id),
                        "has_agent_context": bool(self.context.agent_id)
                    }
                )
                return ""

        # Validation: event_type is required
        if not event_type:
            logger.error(
                "track_collaboration_event called without event_type",
                extra={
                    "stage_id": stage_id,
                    "has_workflow_context": bool(self.context.workflow_id)
                }
            )
            return ""

        # Normalize agents_involved
        if agents_involved is None:
            agents_involved = []

        # Validate confidence_score range
        if confidence_score is not None and not (0.0 <= confidence_score <= 1.0):
            logger.warning(
                f"Invalid confidence_score {confidence_score}, clamping to [0.0, 1.0]",
                extra={"event_type": event_type, "stage_id": stage_id}
            )
            confidence_score = max(0.0, min(1.0, confidence_score))

        # Delegate to backend with error handling
        try:
            return self.backend.track_collaboration_event(
                stage_id=stage_id,
                event_type=event_type,
                agents_involved=agents_involved,
                event_data=event_data,
                round_number=round_number,
                resolution_strategy=resolution_strategy,
                outcome=outcome,
                confidence_score=confidence_score,
                extra_metadata=extra_metadata,
                timestamp=utcnow()
            )
        except Exception as e:
            logger.error(
                f"Failed to track collaboration event: {e}",
                exc_info=True,
                extra={
                    "event_type": event_type,
                    "stage_id": stage_id
                }
            )
            return ""
