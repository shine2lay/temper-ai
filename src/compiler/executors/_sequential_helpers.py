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
from dataclasses import dataclass
from typing import Any, Dict, Optional, cast

from src.compiler.executors.state_keys import StateKeys
from src.constants.durations import SECONDS_PER_MINUTE
from src.constants.retries import (
    DEFAULT_BACKOFF_MULTIPLIER,
    MIN_BACKOFF_SECONDS,
)
from src.constants.sizes import UUID_HEX_SHORT_LENGTH
from src.core.circuit_breaker import CircuitBreakerError
from src.utils.exceptions import (
    BaseError,
    ConfigNotFoundError,
    ConfigValidationError,
    ErrorCode,
    LLMError,
    ToolExecutionError,
    sanitize_error_message,
)

# Agent retry backoff constants
MAX_RETRY_BACKOFF_DIVISOR = 2  # Divide max time by this to get max retry delay (e.g., 60s / 2 = 30s max delay)

logger = logging.getLogger(__name__)


@dataclass
class AgentExecutionContext:
    """Bundles common parameters for agent execution in sequential mode."""
    executor: Any  # SequentialStageExecutor instance
    stage_id: str
    stage_name: str
    workflow_id: str
    state: Dict[str, Any]
    tracker: Optional[Any]
    config_loader: Any
    agent_factory_cls: Any = None

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

# Reserved keys that must not be overwritten when unwrapping workflow_inputs
_RESERVED_UNWRAP_KEYS: frozenset[str] = frozenset({
    StateKeys.STAGE_OUTPUTS, StateKeys.CURRENT_STAGE, StateKeys.WORKFLOW_ID, StateKeys.TRACKER,
    StateKeys.TOOL_REGISTRY, StateKeys.CONFIG_LOADER, StateKeys.VISUALIZER, StateKeys.SHOW_DETAILS,
    StateKeys.DETAIL_CONSOLE, StateKeys.WORKFLOW_INPUTS, StateKeys.TOOL_EXECUTOR, StateKeys.STREAM_CALLBACK,
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
    ctx = AgentExecutionContext(
        executor=executor,
        stage_id=stage_id,
        stage_name=stage_name,
        workflow_id=workflow_id,
        state=state,
        tracker=tracker,
        config_loader=config_loader,
        agent_factory_cls=agent_factory_cls,
    )
    agent_name = executor._extract_agent_name(agent_ref)
    start_time = time.time()

    try:
        return run_agent(
            ctx=ctx,
            agent_name=agent_name,
            agent_ref=agent_ref,
            prior_agent_outputs=prior_agent_outputs or {},
            start_time=start_time,
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
        StateKeys.AGENT_NAME: agent_name,
        StateKeys.OUTPUT_DATA: {
            StateKeys.OUTPUT: "",
            StateKeys.ERROR: error_message,
            StateKeys.ERROR_TYPE: error_type,
            StateKeys.TRACEBACK: error_traceback,
        },
        StateKeys.STATUS: "failed",
        StateKeys.METRICS: {
            StateKeys.TOKENS: 0,
            StateKeys.COST_USD: 0.0,
            StateKeys.DURATION_SECONDS: duration,
            StateKeys.TOOL_CALLS: 0,
        },
    }


def _load_or_cache_agent(
    ctx: AgentExecutionContext,
    agent_name: str
) -> tuple[Any, Any, Dict[str, Any]]:
    """Load agent from cache or create new one."""
    if ctx.agent_factory_cls is not None:
        agent_factory = ctx.agent_factory_cls
    else:
        from src.agents.agent_factory import AgentFactory as _AgentFactory
        agent_factory = _AgentFactory
    from src.compiler.schemas import AgentConfig

    agent_config_dict = ctx.config_loader.load_agent(agent_name)
    agent_config = AgentConfig(**agent_config_dict)

    if agent_name in ctx.executor._agent_cache:
        agent = ctx.executor._agent_cache[agent_name]
    else:
        agent = agent_factory.create(agent_config)
        ctx.executor._agent_cache[agent_name] = agent

    return agent, agent_config, agent_config_dict


def _prepare_sequential_input(
    ctx: AgentExecutionContext,
    prior_agent_outputs: Dict[str, Any]
) -> Dict[str, Any]:
    """Prepare input data for sequential agent execution."""
    if hasattr(ctx.state, 'to_dict'):
        state_dict = ctx.state.to_dict(exclude_internal=True)
    else:
        state_dict = dict(ctx.state) if hasattr(ctx.state, '__iter__') else ctx.state

    # Unwrap workflow_inputs to top level
    wi = {k: v for k, v in state_dict.get(StateKeys.WORKFLOW_INPUTS, {}).items()
          if k not in _RESERVED_UNWRAP_KEYS}

    return {
        **state_dict,
        **wi,
        StateKeys.STAGE_OUTPUTS: state_dict.get(StateKeys.STAGE_OUTPUTS, {}),
        StateKeys.CURRENT_STAGE_AGENTS: dict(prior_agent_outputs),
    }


def _execute_with_tracker(
    agent: Any,
    input_data: Dict[str, Any],
    context: Any,
    agent_name: str,
    agent_config_dict: Dict[str, Any],
    ctx: AgentExecutionContext
) -> Any:
    """Execute agent with tracker and set output."""
    from src.utils.config_helpers import sanitize_config_for_display

    agent_config_for_tracking = sanitize_config_for_display(agent_config_dict)

    _non_serializable_keys: frozenset[str] = frozenset({
        StateKeys.TRACKER, StateKeys.TOOL_REGISTRY, StateKeys.CONFIG_LOADER, StateKeys.VISUALIZER,
        StateKeys.SHOW_DETAILS, StateKeys.DETAIL_CONSOLE, StateKeys.TOOL_EXECUTOR, StateKeys.STREAM_CALLBACK,
    })

    tracking_input_data = sanitize_config_for_display({
        k: v for k, v in input_data.items()
        if k not in _non_serializable_keys
    })

    if ctx.tracker is None:
        raise ValueError("Tracker required for agent execution tracking")
    with ctx.tracker.track_agent(
        agent_name=agent_name,
        agent_config=agent_config_for_tracking,
        stage_id=ctx.stage_id,
        input_data=tracking_input_data
    ) as agent_id:
        context.agent_id = agent_id
        input_data[StateKeys.TRACKER] = ctx.tracker
        response = agent.execute(input_data, context)

        ctx.tracker.set_agent_output(
            agent_id=agent_id,
            output_data={StateKeys.OUTPUT: response.output},
            reasoning=response.reasoning,
            total_tokens=response.tokens,
            estimated_cost_usd=response.estimated_cost_usd,
            num_llm_calls=1 if response.tokens and response.tokens > 0 else 0,
            num_tool_calls=len(response.tool_calls) if response.tool_calls else 0
        )

    return response


def _sanitize_agent_config_for_tracking(agent_config: Any) -> Dict[str, Any]:
    """Convert agent config to a sanitized dict for tracking."""
    from src.utils.config_helpers import sanitize_config_for_display

    if hasattr(agent_config, 'model_dump'):
        config_dict = agent_config.model_dump()
    elif hasattr(agent_config, 'dict'):
        config_dict = agent_config.dict()
    else:
        config_dict = cast(Dict[str, Any], agent_config)
    return sanitize_config_for_display(config_dict)


def _build_success_result(
    agent_name: str, response: Any, duration: float
) -> Dict[str, Any]:
    """Build success result dict from an agent response."""
    return {
        StateKeys.AGENT_NAME: agent_name,
        StateKeys.OUTPUT_DATA: {
            StateKeys.OUTPUT: response.output,
            StateKeys.REASONING: response.reasoning,
            StateKeys.CONFIDENCE: response.confidence,
            StateKeys.TOKENS: response.tokens,
            StateKeys.COST_USD: response.estimated_cost_usd,
            StateKeys.TOOL_CALLS: response.tool_calls if response.tool_calls else [],
        },
        StateKeys.STATUS: "success",
        StateKeys.METRICS: {
            StateKeys.TOKENS: response.tokens or 0,
            StateKeys.COST_USD: response.estimated_cost_usd or 0.0,
            StateKeys.DURATION_SECONDS: duration,
            StateKeys.TOOL_CALLS: len(response.tool_calls) if response.tool_calls else 0,
        },
    }


def run_agent(
    ctx: AgentExecutionContext,
    agent_name: str,
    agent_ref: Any,
    prior_agent_outputs: Dict[str, Any],
    start_time: float,
) -> Dict[str, Any]:
    """Internal: load, execute, and track a single agent.

    Returns:
        Dict with keys: agent_name, output_data, status, metrics
    """
    from src.core.context import ExecutionContext

    agent, agent_config, agent_config_dict = _load_or_cache_agent(ctx, agent_name)
    input_data = _prepare_sequential_input(ctx, prior_agent_outputs)

    context = ExecutionContext(
        workflow_id=ctx.workflow_id,
        stage_id=ctx.stage_id,
        agent_id=f"agent-{uuid.uuid4().hex[:UUID_HEX_SHORT_LENGTH]}",
        metadata={
            "stage_name": ctx.stage_name,
            "agent_name": agent_name,
        }
    )

    if ctx.tracker:
        agent_config_dict_for_tracking = _sanitize_agent_config_for_tracking(agent_config)
        response = _execute_with_tracker(
            agent, input_data, context, agent_name,
            agent_config_dict_for_tracking, ctx
        )
    else:
        response = agent.execute(input_data, context)

    duration = time.time() - start_time
    return _build_success_result(agent_name, response, duration)


def _execute_retry_attempt(
    ctx: AgentExecutionContext,
    agent_ref: Any,
    prior_agent_outputs: Dict[str, Any],
    agent_name: str,
    attempt: int,
    max_retries: int,
) -> tuple[Dict[str, Any], bool]:
    """Execute a single retry attempt. Returns (result, should_stop)."""
    last_result = execute_agent(
        executor=ctx.executor,
        agent_ref=agent_ref,
        stage_id=ctx.stage_id,
        stage_name=ctx.stage_name,
        workflow_id=ctx.workflow_id,
        state=ctx.state,
        tracker=ctx.tracker,
        config_loader=ctx.config_loader,
        prior_agent_outputs=prior_agent_outputs,
        agent_factory_cls=ctx.agent_factory_cls,
    )

    if last_result[StateKeys.STATUS] == "success":
        logger.info(
            "Agent %s succeeded on retry attempt %d/%d in stage %s",
            agent_name, attempt, max_retries, ctx.stage_name,
        )
        last_result[StateKeys.METRICS][StateKeys.RETRIES] = attempt
        return last_result, True

    retry_error_type = last_result[StateKeys.OUTPUT_DATA].get(StateKeys.ERROR_TYPE, "")
    if not is_transient_error(retry_error_type):
        logger.warning(
            "Agent %s retry %d/%d hit permanent error type '%s' in stage %s, "
            "stopping retries: %s",
            agent_name, attempt, max_retries, retry_error_type, ctx.stage_name,
            last_result[StateKeys.OUTPUT_DATA].get(StateKeys.ERROR, ""),
        )
        last_result[StateKeys.METRICS][StateKeys.RETRIES] = attempt
        return last_result, True

    return last_result, False


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
    ctx = AgentExecutionContext(
        executor=executor, stage_id=stage_id, stage_name=stage_name,
        workflow_id=workflow_id, state=state, tracker=tracker,
        config_loader=config_loader, agent_factory_cls=agent_factory_cls,
    )
    base_delay = MIN_BACKOFF_SECONDS
    last_result: Dict[str, Any] = {}

    for attempt in range(1, max_retries + 1):
        delay = min(
            base_delay * (DEFAULT_BACKOFF_MULTIPLIER ** (attempt - 1)),
            SECONDS_PER_MINUTE / MAX_RETRY_BACKOFF_DIVISOR
        )
        logger.info(
            "Retrying agent %s in stage %s (attempt %d/%d, backoff %.1fs)",
            agent_name, stage_name, attempt, max_retries, delay,
        )

        if executor.shutdown_event.wait(timeout=delay):  # intentional wait for backoff
            raise KeyboardInterrupt("Executor shutdown requested")

        last_result, should_stop = _execute_retry_attempt(
            ctx, agent_ref, prior_agent_outputs, agent_name, attempt, max_retries,
        )
        if should_stop:
            return last_result

    logger.warning(
        "Agent %s exhausted all %d retries in stage %s",
        agent_name, max_retries, stage_name,
    )
    if last_result:
        last_result[StateKeys.METRICS][StateKeys.RETRIES] = max_retries
    return last_result


def _print_agent_progress(
    detail_console: Any,
    agent_name: str,
    agent_result: Dict[str, Any],
    is_last: bool
) -> None:
    """Print real-time progress for a single agent."""
    connector = "└─" if is_last else "├─"
    metrics = agent_result.get(StateKeys.METRICS, {})
    duration = metrics.get(StateKeys.DURATION_SECONDS, 0.0)
    tokens = metrics.get(StateKeys.TOKENS, 0)

    if agent_result[StateKeys.STATUS] == "failed":
        error_type = agent_result.get(StateKeys.OUTPUT_DATA, {}).get(StateKeys.ERROR_TYPE, "error")
        detail_console.print(
            f"  {connector} [red]{agent_name} ✗[/red] ({duration:.1f}s) [{error_type}]"
        )
    else:
        detail_console.print(
            f"  {connector} [green]{agent_name} ✓[/green] ({duration:.1f}s, {tokens} tokens)"
        )


def _handle_retry_policy(
    agent_name: str,
    agent_result: Dict[str, Any],
    error_handling: Any,
    stage_name: str,
    ctx: AgentExecutionContext,
    agent_ref: Any,
    agent_outputs: Dict[str, Any],
) -> tuple[str, Dict[str, Any]]:
    """Handle retry_agent failure policy. Returns (action, result_to_store)."""
    max_retries = error_handling.max_agent_retries
    error_type = agent_result[StateKeys.OUTPUT_DATA].get(StateKeys.ERROR_TYPE, "")

    if is_transient_error(error_type) and max_retries > 0:
        retry_result = retry_agent_with_backoff(
            executor=ctx.executor,
            agent_ref=agent_ref,
            stage_id=ctx.stage_id,
            stage_name=ctx.stage_name,
            workflow_id=ctx.workflow_id,
            state=ctx.state,
            tracker=ctx.tracker,
            config_loader=ctx.config_loader,
            prior_agent_outputs=agent_outputs,
            max_retries=max_retries,
            agent_name=agent_name,
            agent_factory_cls=ctx.agent_factory_cls,
        )
        return "store", retry_result

    if not is_transient_error(error_type):
        logger.warning(
            "Agent %s failed with permanent error type '%s' in stage %s "
            "(policy: retry_agent, not retrying): %s",
            agent_name, error_type, stage_name,
            agent_result[StateKeys.OUTPUT_DATA].get(StateKeys.ERROR, ""),
        )
    else:
        logger.warning(
            "Agent %s failed in stage %s (policy: retry_agent, "
            "max_retries=0): %s",
            agent_name, stage_name,
            agent_result[StateKeys.OUTPUT_DATA].get(StateKeys.ERROR, ""),
        )
    return "store", agent_result


def _handle_agent_failure(
    agent_name: str,
    agent_result: Dict[str, Any],
    error_handling: Any,
    stage_name: str,
    ctx: AgentExecutionContext,
    agent_ref: Any,
    agent_outputs: Dict[str, Any],
    agent_metrics: Dict[str, Any]
) -> tuple[str, Dict[str, Any]]:
    """Handle agent failure based on error_handling policy.

    Returns:
        Tuple of (action, result_to_store)
        action: "break" | "continue" | "store"
    """
    policy = error_handling.on_agent_failure

    if policy == "halt_stage":
        logger.warning(
            "Agent %s failed in stage %s (policy: halt_stage), stopping execution: %s",
            agent_name, stage_name, agent_result[StateKeys.OUTPUT_DATA].get(StateKeys.ERROR, "")
        )
        return "break", agent_result

    if policy == "skip_agent":
        logger.warning(
            "Agent %s failed in stage %s (policy: skip_agent), skipping: %s",
            agent_name, stage_name, agent_result[StateKeys.OUTPUT_DATA].get(StateKeys.ERROR, "")
        )
        return "continue", agent_result

    if policy == "retry_agent":
        return _handle_retry_policy(
            agent_name, agent_result, error_handling, stage_name,
            ctx, agent_ref, agent_outputs,
        )

    # continue_with_remaining
    logger.warning(
        "Agent %s failed in stage %s (policy: continue_with_remaining), continuing: %s",
        agent_name, stage_name, agent_result[StateKeys.OUTPUT_DATA].get(StateKeys.ERROR, "")
    )
    return "store", agent_result


def _store_failure_result(
    result_to_store: Dict[str, Any],
    agent_statuses: Dict[str, Any],
    agent_outputs: Dict[str, Any],
    agent_metrics: Dict[str, Any],
) -> None:
    """Store agent result (from retry or original failure) into output dicts."""
    name = result_to_store[StateKeys.AGENT_NAME]
    if result_to_store[StateKeys.STATUS] == "success":
        agent_statuses[name] = "success"
    else:
        agent_statuses[name] = {
            StateKeys.STATUS: "failed",
            StateKeys.ERROR: result_to_store[StateKeys.OUTPUT_DATA].get(StateKeys.ERROR, ""),
            StateKeys.ERROR_TYPE: result_to_store[StateKeys.OUTPUT_DATA].get(StateKeys.ERROR_TYPE, ""),
        }
    agent_outputs[name] = result_to_store[StateKeys.OUTPUT_DATA]
    agent_metrics[name] = result_to_store[StateKeys.METRICS]


def _process_agent_failure(
    agent_name: str,
    agent_result: Dict[str, Any],
    error_handling: Any,
    stage_name: str,
    ctx: AgentExecutionContext,
    agent_ref: Any,
    agent_outputs: Dict[str, Any],
    agent_statuses: Dict[str, Any],
    agent_metrics: Dict[str, Any],
) -> Optional[str]:
    """Process a failed agent result. Returns 'break'/'continue' or None to store and continue."""
    agent_statuses[agent_name] = {
        StateKeys.STATUS: "failed",
        StateKeys.ERROR: agent_result[StateKeys.OUTPUT_DATA].get(StateKeys.ERROR, ""),
        StateKeys.ERROR_TYPE: agent_result[StateKeys.OUTPUT_DATA].get(StateKeys.ERROR_TYPE, ""),
    }

    action, result_to_store = _handle_agent_failure(
        agent_name, agent_result, error_handling, stage_name,
        ctx, agent_ref, agent_outputs, agent_metrics
    )

    if action == "break":
        agent_outputs[agent_name] = result_to_store[StateKeys.OUTPUT_DATA]
        agent_metrics[agent_name] = result_to_store[StateKeys.METRICS]
        return "break"
    if action == "continue":
        agent_metrics[agent_name] = result_to_store[StateKeys.METRICS]
        return "continue"

    _store_failure_result(result_to_store, agent_statuses, agent_outputs, agent_metrics)
    return None


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
    ctx = AgentExecutionContext(
        executor=executor, stage_id=stage_id, stage_name=stage_name,
        workflow_id=workflow_id, state=state, tracker=tracker,
        config_loader=config_loader, agent_factory_cls=agent_factory_cls,
    )

    agent_outputs: Dict[str, Any] = {}
    agent_statuses: Dict[str, Any] = {}
    agent_metrics: Dict[str, Any] = {}

    show_details = state.get(StateKeys.SHOW_DETAILS, False)
    detail_console = state.get(StateKeys.DETAIL_CONSOLE)
    if show_details and detail_console:
        detail_console.print(f"\n[bold cyan]── Stage: {stage_name} ──[/bold cyan]")

    total_agents = len(agents)
    prior_stages = list(state.get(StateKeys.STAGE_OUTPUTS, {}).keys())
    input_info = f"prior stages: {prior_stages}" if prior_stages else "workflow inputs only"
    logger.info("Stage '%s' starting sequential execution with %d agent(s) (%s)", stage_name, total_agents, input_info)

    for agent_idx, agent_ref in enumerate(agents):
        agent_result = execute_agent(
            executor=executor, agent_ref=agent_ref, stage_id=stage_id,
            stage_name=stage_name, workflow_id=workflow_id, state=state,
            tracker=tracker, config_loader=config_loader,
            prior_agent_outputs=agent_outputs, agent_factory_cls=agent_factory_cls,
        )

        agent_name = agent_result[StateKeys.AGENT_NAME]
        logger.info("Stage '%s' agent '%s' completed (%s)", stage_name, agent_name, agent_result[StateKeys.STATUS])

        if show_details and detail_console:
            is_last = (agent_idx == total_agents - 1)
            _print_agent_progress(detail_console, agent_name, agent_result, is_last)

        if agent_result[StateKeys.STATUS] == "failed":
            loop_action = _process_agent_failure(
                agent_name, agent_result, error_handling, stage_name,
                ctx, agent_ref, agent_outputs, agent_statuses, agent_metrics,
            )
            if loop_action == "break":
                break
            if loop_action == "continue":
                continue
        else:
            agent_statuses[agent_name] = agent_result[StateKeys.STATUS]
            agent_outputs[agent_name] = agent_result[StateKeys.OUTPUT_DATA]
            agent_metrics[agent_name] = agent_result[StateKeys.METRICS]

    return agent_outputs, agent_statuses, agent_metrics
