"""Helper functions extracted from SequentialStageExecutor to reduce class size.

Contains:
- Single agent execution logic
- Agent retry with backoff
- All-agents sequential run loop
- Error handling and classification
"""
import logging
import time
import traceback
import uuid
from typing import Any, Dict, Optional, cast

from src.constants.durations import SECONDS_PER_MINUTE
from src.constants.sizes import UUID_HEX_SHORT_LENGTH
from src.constants.retries import (
    DEFAULT_BACKOFF_MULTIPLIER,
    MIN_BACKOFF_SECONDS,
)
from src.core.circuit_breaker import CircuitBreakerError

# Agent retry backoff constants
MAX_RETRY_BACKOFF_DIVISOR = 2  # Divide max time by this to get max retry delay (e.g., 60s / 2 = 30s max delay)
from src.utils.exceptions import (
    BaseError,
    ConfigNotFoundError,
    ConfigValidationError,
    ErrorCode,
    LLMError,
    ToolExecutionError,
    sanitize_error_message,
)

logger = logging.getLogger(__name__)

# Error types classified as transient (worth retrying)
_TRANSIENT_ERROR_TYPES: frozenset[str] = frozenset({
    ErrorCode.LLM_CONNECTION_ERROR.value,
    ErrorCode.LLM_TIMEOUT.value,
    ErrorCode.LLM_RATE_LIMIT.value,
    ErrorCode.SYSTEM_TIMEOUT.value,
    ErrorCode.SYSTEM_RESOURCE_ERROR.value,
    ErrorCode.TOOL_TIMEOUT.value,
    ErrorCode.AGENT_TIMEOUT.value,
    ErrorCode.WORKFLOW_TIMEOUT.value,
})


def is_transient_error(error_type: str) -> bool:
    """Classify an error type as transient (retriable) vs permanent."""
    return error_type in _TRANSIENT_ERROR_TYPES


def execute_agent(
    executor: Any,
    agent_ref: Any,
    stage_id: str,
    stage_name: str,
    workflow_id: str,
    state: Dict[str, Any],
    tracker: Optional[Any],
    config_loader: Any,
    prior_agent_outputs: Optional[Dict[str, Any]] = None,
    agent_factory_cls: Any = None,
) -> Dict[str, Any]:
    """Execute a single agent and return structured result.

    Args:
        executor: The SequentialStageExecutor instance (for _extract_agent_name, _agent_cache)
        agent_ref: Agent reference from stage config
        stage_id: Stage execution ID
        stage_name: Stage name
        workflow_id: Workflow execution ID
        state: Current workflow state
        tracker: ExecutionTracker instance (optional)
        config_loader: ConfigLoader for loading agent configs
        prior_agent_outputs: Outputs from prior agents in the same stage

    Returns:
        Dict with keys: agent_name, output_data, status, metrics
    """
    agent_name = executor._extract_agent_name(agent_ref)
    start_time = time.time()

    try:
        return run_agent(
            executor=executor,
            agent_name=agent_name,
            agent_ref=agent_ref,
            stage_id=stage_id,
            stage_name=stage_name,
            workflow_id=workflow_id,
            state=state,
            tracker=tracker,
            config_loader=config_loader,
            prior_agent_outputs=prior_agent_outputs or {},
            start_time=start_time,
            agent_factory_cls=agent_factory_cls,
        )
    except (KeyboardInterrupt, SystemExit):
        raise
    except (CircuitBreakerError, BaseError, ToolExecutionError, LLMError, ConfigNotFoundError, ConfigValidationError, TimeoutError, ConnectionError, ValueError, RuntimeError) as e:
        duration = time.time() - start_time
        return _build_error_result(agent_name, e, duration)


def _build_error_result(agent_name: str, e: Exception, duration: float) -> Dict[str, Any]:
    """Build error result dict from an exception."""
    if isinstance(e, CircuitBreakerError):
        error_type = ErrorCode.LLM_CONNECTION_ERROR.value
        error_message = sanitize_error_message(str(e))
        error_traceback = sanitize_error_message(traceback.format_exc())

        logger.error(
            "Agent %s failed: Circuit breaker OPEN (provider unhealthy). "
            "Subsequent agents using same provider will fast-fail. Error: %s",
            agent_name, error_message
        )

    elif isinstance(e, BaseError):
        error_type = e.error_code.value
        error_message = sanitize_error_message(str(e))
        error_traceback = sanitize_error_message(traceback.format_exc())

        logger.warning(
            "Agent %s failed in stage: %s",
            agent_name, error_message
        )

    else:
        error_type_map = {
            "TimeoutError": ErrorCode.SYSTEM_TIMEOUT.value,
            "ConnectionError": ErrorCode.LLM_CONNECTION_ERROR.value,
            "ValueError": ErrorCode.VALIDATION_ERROR.value,
            "RuntimeError": ErrorCode.AGENT_EXECUTION_ERROR.value,
        }
        error_type = error_type_map.get(
            type(e).__name__, ErrorCode.UNKNOWN_ERROR.value
        )

        error_message = sanitize_error_message(str(e))
        error_traceback = sanitize_error_message(traceback.format_exc())

        logger.warning(
            "Agent %s failed in stage: %s",
            agent_name, error_message
        )

    return {
        "agent_name": agent_name,
        "output_data": {
            "output": "",
            "error": error_message,
            "error_type": error_type,
            "traceback": error_traceback,
        },
        "status": "failed",
        "metrics": {
            "tokens": 0,
            "cost_usd": 0.0,
            "duration_seconds": duration,
            "tool_calls": 0,
        },
    }


def run_agent(
    executor: Any,
    agent_name: str,
    agent_ref: Any,
    stage_id: str,
    stage_name: str,
    workflow_id: str,
    state: Dict[str, Any],
    tracker: Optional[Any],
    config_loader: Any,
    prior_agent_outputs: Dict[str, Any],
    start_time: float,
    agent_factory_cls: Any = None,
) -> Dict[str, Any]:
    """Internal: load, execute, and track a single agent.

    Returns:
        Dict with keys: agent_name, output_data, status, metrics
    """
    if agent_factory_cls is not None:
        agent_factory = agent_factory_cls
    else:
        from src.agents.agent_factory import AgentFactory as _AgentFactory
        agent_factory = _AgentFactory
    from src.compiler.schemas import AgentConfig
    from src.core.context import ExecutionContext
    from src.utils.config_helpers import sanitize_config_for_display

    # Load agent config and create agent (with per-workflow caching)
    if agent_name in executor._agent_cache:
        agent = executor._agent_cache[agent_name]
        agent_config_dict = config_loader.load_agent(agent_name)
        agent_config = AgentConfig(**agent_config_dict)
    else:
        agent_config_dict = config_loader.load_agent(agent_name)
        agent_config = AgentConfig(**agent_config_dict)
        agent = agent_factory.create(agent_config)
        executor._agent_cache[agent_name] = agent

    # Prepare input data
    if hasattr(state, 'to_dict'):
        state_dict = state.to_dict(exclude_internal=True)
    else:
        state_dict = dict(state) if hasattr(state, '__iter__') else state

    input_data = {
        **state_dict,
        "stage_outputs": state_dict.get("stage_outputs", {}),
        "current_stage_agents": dict(prior_agent_outputs),
    }

    # Create execution context
    context = ExecutionContext(
        workflow_id=workflow_id,
        stage_id=stage_id,
        agent_id=f"agent-{uuid.uuid4().hex[:UUID_HEX_SHORT_LENGTH]}",
        metadata={
            "stage_name": stage_name,
            "agent_name": agent_name,
        }
    )

    # Prepare serializable config for tracking
    if hasattr(agent_config, 'model_dump'):
        agent_config_dict_for_tracking = agent_config.model_dump()
    elif hasattr(agent_config, 'dict'):
        agent_config_dict_for_tracking = agent_config.dict()
    else:
        agent_config_dict_for_tracking = cast(Dict[str, Any], agent_config)
    agent_config_dict_for_tracking = sanitize_config_for_display(agent_config_dict_for_tracking)

    if tracker:
        # Allowlist of known non-serializable/infrastructure keys
        _non_serializable_keys: frozenset[str] = frozenset({
            'tracker', 'tool_registry', 'config_loader', 'visualizer',
            'show_details', 'detail_console', 'tool_executor',
        })

        tracking_input_data = {
            k: v for k, v in input_data.items()
            if k not in _non_serializable_keys
        }
        tracking_input_data = sanitize_config_for_display(tracking_input_data)

        with tracker.track_agent(
            agent_name=agent_name,
            agent_config=agent_config_dict_for_tracking,
            stage_id=stage_id,
            input_data=tracking_input_data
        ) as agent_id:
            context.agent_id = agent_id

            input_data['tracker'] = tracker

            response = agent.execute(input_data, context)

            tracker.set_agent_output(
                agent_id=agent_id,
                output_data={"output": response.output},
                reasoning=response.reasoning,
                total_tokens=response.tokens,
                estimated_cost_usd=response.estimated_cost_usd,
                num_llm_calls=1 if response.tokens and response.tokens > 0 else 0,
                num_tool_calls=len(response.tool_calls) if response.tool_calls else 0
            )
    else:
        response = agent.execute(input_data, context)

    duration = time.time() - start_time
    return {
        "agent_name": agent_name,
        "output_data": {
            "output": response.output,
            "reasoning": response.reasoning,
            "confidence": response.confidence,
            "tokens": response.tokens,
            "cost_usd": response.estimated_cost_usd,
            "tool_calls": response.tool_calls if response.tool_calls else [],
        },
        "status": "success",
        "metrics": {
            "tokens": response.tokens or 0,
            "cost_usd": response.estimated_cost_usd or 0.0,
            "duration_seconds": duration,
            "tool_calls": len(response.tool_calls) if response.tool_calls else 0,
        },
    }


def retry_agent_with_backoff(
    executor: Any,
    agent_ref: Any,
    stage_id: str,
    stage_name: str,
    workflow_id: str,
    state: Dict[str, Any],
    tracker: Optional[Any],
    config_loader: Any,
    prior_agent_outputs: Dict[str, Any],
    max_retries: int,
    agent_name: str,
    agent_factory_cls: Any = None,
) -> Dict[str, Any]:
    """Retry a failed agent with exponential backoff.

    Only retries on transient errors. Stops immediately if a
    permanent error is encountered during a retry attempt.

    Returns:
        Dict with keys: agent_name, output_data, status, metrics
    """
    base_delay = MIN_BACKOFF_SECONDS
    last_result: Dict[str, Any] = {}

    for attempt in range(1, max_retries + 1):
        delay = min(base_delay * (DEFAULT_BACKOFF_MULTIPLIER ** (attempt - 1)), SECONDS_PER_MINUTE / MAX_RETRY_BACKOFF_DIVISOR)
        logger.info(
            "Retrying agent %s in stage %s (attempt %d/%d, backoff %.1fs)",
            agent_name, stage_name, attempt, max_retries, delay,
        )
        # H-13: Use shared shutdown event for interruptibility
        if executor.shutdown_event.wait(timeout=delay):
            raise KeyboardInterrupt("Executor shutdown requested")

        last_result = execute_agent(
            executor=executor,
            agent_ref=agent_ref,
            stage_id=stage_id,
            stage_name=stage_name,
            workflow_id=workflow_id,
            state=state,
            tracker=tracker,
            config_loader=config_loader,
            prior_agent_outputs=prior_agent_outputs,
            agent_factory_cls=agent_factory_cls,
        )

        if last_result["status"] == "success":
            logger.info(
                "Agent %s succeeded on retry attempt %d/%d in stage %s",
                agent_name, attempt, max_retries, stage_name,
            )
            last_result["metrics"]["retries"] = attempt
            return last_result

        retry_error_type = last_result["output_data"].get("error_type", "")
        if not is_transient_error(retry_error_type):
            logger.warning(
                "Agent %s retry %d/%d hit permanent error type '%s' in stage %s, "
                "stopping retries: %s",
                agent_name, attempt, max_retries, retry_error_type, stage_name,
                last_result["output_data"].get("error", ""),
            )
            last_result["metrics"]["retries"] = attempt
            return last_result

    # All retries exhausted
    logger.warning(
        "Agent %s exhausted all %d retries in stage %s",
        agent_name, max_retries, stage_name,
    )
    if last_result:
        last_result["metrics"]["retries"] = max_retries
    return last_result


def run_all_agents(
    executor: Any,
    agents: list,
    stage_id: str,
    stage_name: str,
    workflow_id: str,
    state: Dict[str, Any],
    tracker: Optional[Any],
    config_loader: Any,
    error_handling: Any,
    agent_factory_cls: Any = None,
) -> tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Execute all agents in sequence with configurable error handling.

    Returns:
        Tuple of (agent_outputs, agent_statuses, agent_metrics)
    """
    agent_outputs: Dict[str, Any] = {}
    agent_statuses: Dict[str, Any] = {}
    agent_metrics: Dict[str, Any] = {}

    show_details = state.get("show_details", False)
    detail_console = state.get("detail_console")
    if show_details and detail_console:
        detail_console.print(f"\n[bold cyan]── Stage: {stage_name} ──[/bold cyan]")

    total_agents = len(agents)
    prior_stages = list(state.get("stage_outputs", {}).keys())
    input_info = f"prior stages: {prior_stages}" if prior_stages else "workflow inputs only"
    logger.info("Stage '%s' starting sequential execution with %d agent(s) (%s)", stage_name, total_agents, input_info)
    for agent_idx, agent_ref in enumerate(agents):
        agent_result = execute_agent(
            executor=executor,
            agent_ref=agent_ref,
            stage_id=stage_id,
            stage_name=stage_name,
            workflow_id=workflow_id,
            state=state,
            tracker=tracker,
            config_loader=config_loader,
            prior_agent_outputs=agent_outputs,
            agent_factory_cls=agent_factory_cls,
        )

        agent_name = agent_result["agent_name"]
        logger.info("Stage '%s' agent '%s' completed (%s)", stage_name, agent_name, agent_result["status"])

        # Print real-time progress if show_details enabled
        if show_details and detail_console:
            is_last = (agent_idx == total_agents - 1)
            connector = "└─" if is_last else "├─"
            metrics = agent_result.get("metrics", {})
            duration = metrics.get("duration_seconds", 0.0)
            tokens = metrics.get("tokens", 0)

            if agent_result["status"] == "failed":
                error_type = agent_result.get("output_data", {}).get("error_type", "error")
                detail_console.print(
                    f"  {connector} [red]{agent_name} ✗[/red] ({duration:.1f}s) [{error_type}]"
                )
            else:
                detail_console.print(
                    f"  {connector} [green]{agent_name} ✓[/green] ({duration:.1f}s, {tokens} tokens)"
                )

        # Store status with error details for failed agents
        if agent_result["status"] == "failed":
            agent_statuses[agent_name] = {
                "status": "failed",
                "error": agent_result["output_data"].get("error", ""),
                "error_type": agent_result["output_data"].get("error_type", ""),
            }

            policy = error_handling.on_agent_failure

            if policy == "halt_stage":
                logger.warning(
                    "Agent %s failed in stage %s (policy: halt_stage), stopping execution: %s",
                    agent_name, stage_name, agent_result["output_data"].get("error", "")
                )
                agent_outputs[agent_name] = agent_result["output_data"]
                agent_metrics[agent_name] = agent_result["metrics"]
                break

            elif policy == "skip_agent":
                logger.warning(
                    "Agent %s failed in stage %s (policy: skip_agent), skipping: %s",
                    agent_name, stage_name, agent_result["output_data"].get("error", "")
                )
                agent_metrics[agent_name] = agent_result["metrics"]
                continue

            elif policy == "retry_agent":
                max_retries = error_handling.max_agent_retries
                error_type = agent_result["output_data"].get("error_type", "")

                if is_transient_error(error_type) and max_retries > 0:
                    retry_result = retry_agent_with_backoff(
                        executor=executor,
                        agent_ref=agent_ref,
                        stage_id=stage_id,
                        stage_name=stage_name,
                        workflow_id=workflow_id,
                        state=state,
                        tracker=tracker,
                        config_loader=config_loader,
                        prior_agent_outputs=agent_outputs,
                        max_retries=max_retries,
                        agent_name=agent_name,
                        agent_factory_cls=agent_factory_cls,
                    )
                    agent_name = retry_result["agent_name"]
                    if retry_result["status"] == "success":
                        agent_statuses[agent_name] = retry_result["status"]
                    else:
                        agent_statuses[agent_name] = {
                            "status": "failed",
                            "error": retry_result["output_data"].get("error", ""),
                            "error_type": retry_result["output_data"].get("error_type", ""),
                        }
                    agent_outputs[agent_name] = retry_result["output_data"]
                    agent_metrics[agent_name] = retry_result["metrics"]
                else:
                    if not is_transient_error(error_type):
                        logger.warning(
                            "Agent %s failed with permanent error type '%s' in stage %s "
                            "(policy: retry_agent, not retrying): %s",
                            agent_name, error_type, stage_name,
                            agent_result["output_data"].get("error", ""),
                        )
                    else:
                        logger.warning(
                            "Agent %s failed in stage %s (policy: retry_agent, "
                            "max_retries=0): %s",
                            agent_name, stage_name,
                            agent_result["output_data"].get("error", ""),
                        )
                    agent_outputs[agent_name] = agent_result["output_data"]
                    agent_metrics[agent_name] = agent_result["metrics"]

            elif policy == "continue_with_remaining":
                logger.warning(
                    "Agent %s failed in stage %s (policy: continue_with_remaining), continuing: %s",
                    agent_name, stage_name, agent_result["output_data"].get("error", "")
                )
                agent_outputs[agent_name] = agent_result["output_data"]
                agent_metrics[agent_name] = agent_result["metrics"]

        else:
            # Success
            agent_statuses[agent_name] = agent_result["status"]
            agent_outputs[agent_name] = agent_result["output_data"]
            agent_metrics[agent_name] = agent_result["metrics"]

    return agent_outputs, agent_statuses, agent_metrics
