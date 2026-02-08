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
from src.observability.backend import ObservabilityBackend
from src.observability.collaboration_tracker import CollaborationEventTracker
from src.observability.decision_tracker import DecisionTracker
from src.observability.metric_aggregator import MetricAggregator
from src.observability.sanitization import DataSanitizer, SanitizationConfig
from src.utils.config_helpers import sanitize_config_for_display

logger = logging.getLogger(__name__)


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
        sanitization_config: Optional[SanitizationConfig] = None,
        metric_registry: Optional[Any] = None,
        alert_manager: Optional[Any] = None
    ):
        """
        Initialize execution tracker with sanitization and alerting support.

        Args:
            backend: Observability backend to use. If None, defaults to SQLObservabilityBackend.
            sanitization_config: Configuration for data sanitization. If None, uses secure defaults.
            metric_registry: Optional MetricRegistry for collecting metrics after agent execution.
                            If provided, metrics will be automatically collected and stored for each agent.
            alert_manager: Optional AlertManager for real-time alerting on metric thresholds.
                          If None, creates default AlertManager with built-in rules.
        """
        # Thread-safe: each thread/async-task gets its own ExecutionContext
        # Note: no default= so each thread creates its own via the property getter
        self._context_var: contextvars.ContextVar[ExecutionContext] = contextvars.ContextVar(
            'execution_context'
        )
        # Thread-safe: each thread gets its own session stack
        self._local = threading.local()

        # Use provided backend or default to SQL backend with buffering
        if backend is None:
            from src.observability.backends import SQLObservabilityBackend
            # SQLObservabilityBackend creates a default buffer automatically
            # to reduce N+1 queries (from 2N to N/batch_size)
            backend = SQLObservabilityBackend()

        self.backend = backend

        # Initialize sanitizer with provided or default config
        self.sanitizer = DataSanitizer(sanitization_config)

        # Store metric registry for automatic metric collection
        self.metric_registry = metric_registry

        # Initialize alert manager for real-time alerting
        if alert_manager is None:
            from src.observability.alerting import AlertManager
            alert_manager = AlertManager()
        self.alert_manager = alert_manager

        # Delegate decision tracking and merit score updates to extracted services.
        # DecisionTracker owns a MeritScoreService internally.
        self._decision_tracker = DecisionTracker(sanitize_fn=self._sanitize_dict)

        # Extracted services for metric aggregation and collaboration tracking
        self._metric_aggregator = MetricAggregator(
            backend=self.backend,
            metric_registry=metric_registry,
        )
        self._collaboration_tracker = CollaborationEventTracker(
            backend=self.backend,
            sanitize_fn=self._sanitize_dict,
            get_context=lambda: self.context,
        )

    @staticmethod
    def ensure_database(db_url: str) -> None:
        """Ensure observability database is initialized.

        Idempotent — safe to call multiple times. If the database is
        already initialized, this is a no-op.

        Args:
            db_url: SQLAlchemy database URL (e.g., "sqlite:///path/to/db.sqlite")
        """
        from src.database import get_database, init_database
        try:
            get_database()
        except RuntimeError:
            init_database(db_url)

    @property
    def context(self) -> ExecutionContext:
        """Per-thread/task ExecutionContext (backward-compatible property)."""
        ctx = self._context_var.get(None)
        if ctx is None:
            ctx = ExecutionContext()
            self._context_var.set(ctx)
        return ctx

    @context.setter
    def context(self, value: ExecutionContext) -> None:
        """Set the ExecutionContext for the current thread/task."""
        self._context_var.set(value)

    @property
    def _session_stack(self) -> List[Any]:
        """Per-thread session stack (backward-compatible property)."""
        stack = getattr(self._local, 'session_stack', None)
        if stack is None:
            stack = []
            self._local.session_stack = stack
        return stack

    def _collect_agent_metrics(self, agent_id: str) -> None:
        """Collect metrics for agent execution. Delegates to MetricAggregator."""
        self._metric_aggregator.collect_agent_metrics(agent_id)

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
        workflow_id = f"wf-{uuid.uuid4()}"
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

                # Aggregate and update metrics via backend method
                try:
                    if hasattr(self.backend, 'aggregate_workflow_metrics'):
                        metrics = self.backend.aggregate_workflow_metrics(workflow_id)

                        if metrics:
                            total_cost = metrics.get('total_cost_usd', 0.0)

                            self.backend.update_workflow_metrics(
                                workflow_id=workflow_id,
                                total_llm_calls=metrics.get('total_llm_calls', 0),
                                total_tool_calls=metrics.get('total_tool_calls', 0),
                                total_tokens=metrics.get('total_tokens', 0),
                                total_cost_usd=total_cost
                            )

                            # Check cost alerts
                            if self.alert_manager and total_cost > 0:
                                self.alert_manager.check_metric(
                                    metric_type="cost_usd",
                                    value=total_cost,
                                    context={"workflow_id": workflow_id}
                                )
                except Exception as e:
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

                # Aggregate metrics from child agents via backend method
                try:
                    if hasattr(self.backend, 'aggregate_stage_metrics'):
                        metrics = self.backend.aggregate_stage_metrics(stage_id)
                        self.backend.track_stage_end(
                            stage_id=stage_id,
                            end_time=end_time,
                            status="completed",
                            error_message=None,
                            num_agents_executed=metrics.get('num_agents_executed', 0),
                            num_agents_succeeded=metrics.get('num_agents_succeeded', 0),
                            num_agents_failed=metrics.get('num_agents_failed', 0)
                        )
                    else:
                        self.backend.track_stage_end(
                            stage_id=stage_id,
                            end_time=end_time,
                            status="completed"
                        )
                except Exception as e:
                    logger.warning(
                        f"Failed to aggregate stage metrics for {stage_id}: {e}",
                        exc_info=True
                    )
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

                # Success - mark as completed first, then collect metrics
                end_time = utcnow()

                self.backend.track_agent_end(
                    agent_id=agent_id,
                    end_time=end_time,
                    status="completed"
                )

                # Collect metrics after execution is marked as completed
                # This ensures collectors see the final execution state
                self._collect_agent_metrics(agent_id)

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

                    # Success - mark as completed first, then collect metrics
                    end_time = utcnow()

                    self.backend.track_agent_end(
                        agent_id=agent_id,
                        end_time=end_time,
                        status="completed"
                    )

                    # Collect metrics after execution is marked as completed
                    # This ensures collectors see the final execution state
                    self._collect_agent_metrics(agent_id)

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

        # Check latency and cost alerts
        if self.alert_manager:
            # Check latency
            if latency_ms > 0:
                self.alert_manager.check_metric(
                    metric_type="latency_p99",  # Treat each call as potential p99
                    value=latency_ms,
                    context={
                        "agent_id": agent_id,
                        "provider": provider,
                        "model": model,
                        "llm_call_id": llm_call_id
                    }
                )

            # Check cost
            if estimated_cost_usd > 0:
                self.alert_manager.check_metric(
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

        # Check tool execution duration alerts
        if self.alert_manager and duration_seconds > 0:
            duration_ms = duration_seconds * 1000
            self.alert_manager.check_metric(
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

    def _sanitize_dict(self, data: Dict[str, Any], _depth: int = 0) -> Dict[str, Any]:
        """
        Recursively sanitize dictionary values to remove secrets.

        SECURITY: Prevents credential exposure in tool parameters/outputs.
        Uses recursive traversal instead of JSON round-trip to avoid injection attacks.
        OB-09: Depth-limited to prevent RecursionError on deeply nested structures.

        Args:
            data: Dictionary to sanitize
            _depth: Current recursion depth (internal)

        Returns:
            Sanitized dictionary with secrets redacted
        """
        if not isinstance(data, dict):
            return data

        # OB-09: Prevent RecursionError on deeply nested structures
        if _depth > 20:
            return {"__truncated__": "max depth exceeded"}

        sanitized = {}
        for key, value in data.items():
            try:
                # Sanitize key as well (keys might contain secrets)
                safe_key_result = self.sanitizer.sanitize_text(str(key), context="config")
                safe_key = safe_key_result.sanitized_text

                # Recursively sanitize value based on type
                if isinstance(value, dict):
                    sanitized[safe_key] = self._sanitize_dict(value, _depth + 1)
                elif isinstance(value, list):
                    sanitized[safe_key] = [
                        self._sanitize_dict(item, _depth + 1) if isinstance(item, dict)
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
        """Get current exception stack trace, sanitized to remove secrets."""
        import traceback
        raw_trace = traceback.format_exc()
        return self.sanitizer.sanitize_text(raw_trace, context="stack_trace").sanitized_text

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
        """Set agent output data. Delegates to MetricAggregator."""
        self._metric_aggregator.set_agent_output(
            agent_id=agent_id,
            output_data=output_data,
            reasoning=reasoning,
            confidence_score=confidence_score,
            total_tokens=total_tokens,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            estimated_cost_usd=estimated_cost_usd,
            num_llm_calls=num_llm_calls,
            num_tool_calls=num_tool_calls,
        )

    def set_stage_output(
        self,
        stage_id: str,
        output_data: Dict[str, Any]
    ) -> None:
        """Set stage output data. Delegates to MetricAggregator."""
        self._metric_aggregator.set_stage_output(
            stage_id=stage_id,
            output_data=output_data,
        )

    def track_safety_violation(
        self,
        violation_severity: str,
        violation_message: str,
        policy_name: str,
        service_name: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None
    ) -> None:
        """Track safety violation. Delegates to CollaborationEventTracker."""
        self._collaboration_tracker.track_safety_violation(
            violation_severity=violation_severity,
            violation_message=violation_message,
            policy_name=policy_name,
            service_name=service_name,
            context=context,
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
        """Track collaboration event. Delegates to CollaborationEventTracker."""
        return self._collaboration_tracker.track_collaboration_event(
            event_type=event_type,
            stage_id=stage_id,
            agents_involved=agents_involved,
            event_data=event_data,
            round_number=round_number,
            resolution_strategy=resolution_strategy,
            outcome=outcome,
            confidence_score=confidence_score,
            extra_metadata=extra_metadata,
            stage_name=stage_name,
            agents=agents,
            decision=decision,
            confidence=confidence,
            metadata=metadata,
        )

    def track_decision_outcome(
        self,
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
        extra_metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """Track decision outcome for self-improvement learning loop.

        Delegates to DecisionTracker for persistence and merit score updates,
        while handling session management and execution context lookup.

        Args:
            decision_type: Type of decision
            decision_data: Decision details
            outcome: Decision outcome ("success", "failure", "neutral", "mixed")
            impact_metrics: Measured impact of decision
            lessons_learned: What was learned
            should_repeat: Whether to repeat in similar contexts
            tags: Categorization tags
            agent_execution_id: Related agent execution ID
            stage_execution_id: Related stage execution ID
            workflow_execution_id: Related workflow execution ID
            validation_method: How outcome was validated
            validation_timestamp: When outcome was validated
            validation_duration_seconds: How long validation took
            extra_metadata: Additional metadata

        Returns:
            Decision ID or empty string on failure
        """
        # Fill in execution IDs from context if not provided
        if not workflow_execution_id:
            workflow_execution_id = self.context.workflow_id
        if not stage_execution_id:
            stage_execution_id = self.context.stage_id
        if not agent_execution_id:
            agent_execution_id = self.context.agent_id

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

        if self._session_stack:
            return self._decision_tracker.track(
                session=self._session_stack[-1], **kwargs
            )

        with self.backend.get_session_context() as session:
            return self._decision_tracker.track(session=session, **kwargs)

    def update_agent_merit_score(
        self,
        agent_name: str,
        domain: str,
        decision_outcome: str,
        confidence: Optional[float] = None
    ) -> None:
        """Update agent merit score based on decision outcome.

        Delegates to MeritScoreService (owned by DecisionTracker).

        Args:
            agent_name: Name of the agent
            domain: Domain of expertise
            decision_outcome: Outcome ("success", "failure", "neutral", "mixed")
            confidence: Confidence score (0.0-1.0)
        """
        try:
            if self._session_stack:
                self._decision_tracker._merit_service.update(
                    session=self._session_stack[-1],
                    agent_name=agent_name,
                    domain=domain,
                    decision_outcome=decision_outcome,
                    confidence=confidence,
                )
                # MeritScoreService.update() flushes; commit since we own the session
                self._session_stack[-1].commit()
            else:
                with self.backend.get_session_context() as session:
                    self._decision_tracker._merit_service.update(
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
