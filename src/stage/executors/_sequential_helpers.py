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

from src.stage.executors._base_helpers import _truncate_tracking_data
from src.stage.executors.state_keys import StateKeys
from src.shared.constants.durations import SECONDS_PER_MINUTE
from src.shared.constants.retries import (
    DEFAULT_BACKOFF_MULTIPLIER,
    MIN_BACKOFF_SECONDS,
)
from src.shared.constants.sizes import UUID_HEX_SHORT_LENGTH
from src.shared.core.circuit_breaker import CircuitBreakerError
from src.shared.utils.exceptions import (
    BaseError,
    ConfigNotFoundError,
    ConfigValidationError,
    ErrorCode,
    LLMError,
    ToolExecutionError,
    sanitize_error_message,
)
from src.observability.resilience_events import (
    RetryEventData,
    emit_retry_event,
    RETRY_OUTCOME_EXHAUSTED,
    RETRY_OUTCOME_FAILED,
    RETRY_OUTCOME_SUCCESS,
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
    context_provider: Optional[Any] = None
    stage_config: Optional[Any] = None


@dataclass
class AgentResultAccumulators:
    """Groups mutable output accumulators passed through the agent execution chain."""
    outputs: Dict[str, Any]
    statuses: Dict[str, Any]
    metrics: Dict[str, Any]

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
    ctx: AgentExecutionContext,
    agent_ref: Any,
    prior_agent_outputs: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Execute a single agent and return structured result.

    Args:
        ctx: Agent execution context bundle
        agent_ref: Agent reference from stage config
        prior_agent_outputs: Outputs from prior agents in the same stage

    Returns:
        Dict with keys: agent_name, output_data, status, metrics
    """
    agent_name = ctx.executor._extract_agent_name(agent_ref)
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

    # Compute error fingerprint (best-effort)
    fingerprint = None
    try:
        from src.observability.error_fingerprinting import compute_fingerprint
        fingerprint = compute_fingerprint(type(e).__name__, error_type, str(e))
    except Exception:  # noqa: BLE001 — fingerprinting must never disrupt execution
        pass

    output_data: Dict[str, Any] = {
        StateKeys.OUTPUT: "",
        StateKeys.ERROR: error_message,
        StateKeys.ERROR_TYPE: error_type,
        StateKeys.TRACEBACK: error_traceback,
    }
    if fingerprint is not None:
        output_data["error_fingerprint"] = fingerprint

    return {
        StateKeys.AGENT_NAME: agent_name,
        StateKeys.OUTPUT_DATA: output_data,
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
        from src.agent.utils.agent_factory import AgentFactory as _AgentFactory
        agent_factory = _AgentFactory
    from src.storage.schemas.agent_config import AgentConfig

    agent_config_dict = ctx.config_loader.load_agent(agent_name)
    agent_config = AgentConfig(**agent_config_dict)

    if agent_name in ctx.executor._agent_cache:
        agent = ctx.executor._agent_cache[agent_name]
    else:
        agent = agent_factory.create(agent_config)
        ctx.executor._agent_cache[agent_name] = agent

    return agent, agent_config, agent_config_dict


def _build_legacy_input(
    ctx: AgentExecutionContext,
    prior_agent_outputs: Dict[str, Any],
) -> Dict[str, Any]:
    """Build input from full state with workflow_inputs unwrapped (legacy path)."""
    if hasattr(ctx.state, 'to_dict'):
        state_dict = ctx.state.to_dict(exclude_internal=True)
    else:
        state_dict = dict(ctx.state) if hasattr(ctx.state, '__iter__') else ctx.state

    wi = {k: v for k, v in state_dict.get(StateKeys.WORKFLOW_INPUTS, {}).items()
          if k not in _RESERVED_UNWRAP_KEYS}

    return {
        **state_dict,
        **wi,
        StateKeys.STAGE_OUTPUTS: state_dict.get(StateKeys.STAGE_OUTPUTS, {}),
        StateKeys.CURRENT_STAGE_AGENTS: dict(prior_agent_outputs),
    }


def _prepare_sequential_input(
    ctx: AgentExecutionContext,
    prior_agent_outputs: Dict[str, Any],
    context_provider: Optional[Any] = None,
    stage_config: Optional[Any] = None,
) -> Dict[str, Any]:
    """Prepare input data for sequential agent execution.

    When ``context_provider`` and ``stage_config`` are supplied and the
    stage declares inputs with source refs, resolved (focused) context
    is returned instead of the full state.
    """
    # Dynamic inputs override normal resolution
    dynamic = ctx.state.get(StateKeys.DYNAMIC_INPUTS)
    if dynamic is not None:
        from src.workflow.context_provider import _INFRASTRUCTURE_KEYS

        result = dict(dynamic)
        for key in _INFRASTRUCTURE_KEYS:
            if key in ctx.state:
                result[key] = ctx.state[key]
        result[StateKeys.CURRENT_STAGE_AGENTS] = dict(prior_agent_outputs)
        return result

    # Try focused resolution via context_provider
    if context_provider is not None and stage_config is not None:
        try:
            resolved = context_provider.resolve(stage_config, ctx.state)
            if "_context_meta" in resolved:
                ctx.state["_context_meta"] = resolved["_context_meta"]
            resolved[StateKeys.CURRENT_STAGE_AGENTS] = dict(prior_agent_outputs)
            return dict(resolved)
        except Exception:
            logger.debug(
                "Context provider resolution failed for stage '%s', "
                "falling back to full state",
                ctx.stage_name,
                exc_info=True,
            )

    return _build_legacy_input(ctx, prior_agent_outputs)


def _execute_with_tracker(
    agent: Any,
    input_data: Dict[str, Any],
    context: Any,
    agent_name: str,
    agent_config_dict: Dict[str, Any],
    ctx: AgentExecutionContext
) -> Any:
    """Execute agent with tracker and set output."""
    from src.shared.utils.config_helpers import sanitize_config_for_display

    agent_config_for_tracking = sanitize_config_for_display(agent_config_dict)

    _non_serializable_keys: frozenset[str] = frozenset({
        StateKeys.TRACKER, StateKeys.TOOL_REGISTRY, StateKeys.CONFIG_LOADER, StateKeys.VISUALIZER,
        StateKeys.SHOW_DETAILS, StateKeys.DETAIL_CONSOLE, StateKeys.TOOL_EXECUTOR, StateKeys.STREAM_CALLBACK,
    })

    tracking_input_data = sanitize_config_for_display({
        k: v for k, v in input_data.items()
        if k not in _non_serializable_keys
    })
    tracking_input_data = _truncate_tracking_data(tracking_input_data)

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

        from src.observability.metric_aggregator import AgentOutputParams
        ctx.tracker.set_agent_output(AgentOutputParams(
            agent_id=agent_id,
            output_data={StateKeys.OUTPUT: response.output},
            reasoning=response.reasoning,
            total_tokens=response.tokens,
            estimated_cost_usd=response.estimated_cost_usd,
            num_llm_calls=1 if response.tokens and response.tokens > 0 else 0,
            num_tool_calls=len(response.tool_calls) if response.tool_calls else 0,
        ))

    return response


def _sanitize_agent_config_for_tracking(agent_config: Any) -> Dict[str, Any]:
    """Convert agent config to a sanitized dict for tracking."""
    from src.shared.utils.config_helpers import sanitize_config_for_display

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
    from src.shared.core.context import ExecutionContext

    agent, agent_config, agent_config_dict = _load_or_cache_agent(ctx, agent_name)
    input_data = _prepare_sequential_input(
        ctx, prior_agent_outputs,
        context_provider=ctx.context_provider,
        stage_config=ctx.stage_config,
    )

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
        ctx=ctx,
        agent_ref=agent_ref,
        prior_agent_outputs=prior_agent_outputs,
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
    ctx: AgentExecutionContext,
    agent_ref: Any,
    prior_agent_outputs: Dict[str, Any],
    max_retries: int,
    agent_name: str,
) -> Dict[str, Any]:
    """Retry a failed agent with exponential backoff.

    Only retries on transient errors. Stops immediately if a
    permanent error is encountered during a retry attempt.

    Args:
        ctx: Agent execution context bundle
        agent_ref: Agent reference from stage config
        prior_agent_outputs: Outputs from prior agents in the same stage
        max_retries: Maximum number of retry attempts
        agent_name: Name of the agent being retried

    Returns:
        Dict with keys: agent_name, output_data, status, metrics
    """
    base_delay = MIN_BACKOFF_SECONDS
    last_result: Dict[str, Any] = {}

    for attempt in range(1, max_retries + 1):
        delay = min(
            base_delay * (DEFAULT_BACKOFF_MULTIPLIER ** (attempt - 1)),
            SECONDS_PER_MINUTE / MAX_RETRY_BACKOFF_DIVISOR
        )
        logger.info(
            "Retrying agent %s in stage %s (attempt %d/%d, backoff %.1fs)",
            agent_name, ctx.stage_name, attempt, max_retries, delay,
        )

        if ctx.executor.shutdown_event.wait(timeout=delay):  # intentional wait for backoff
            raise KeyboardInterrupt("Executor shutdown requested")

        last_result, should_stop = _execute_retry_attempt(
            ctx, agent_ref, prior_agent_outputs, agent_name, attempt, max_retries,
        )
        if should_stop:
            _emit_retry_outcome(ctx, last_result, agent_name, attempt, max_retries, delay)
            return last_result

    logger.warning(
        "Agent %s exhausted all %d retries in stage %s",
        agent_name, max_retries, ctx.stage_name,
    )
    if last_result:
        last_result[StateKeys.METRICS][StateKeys.RETRIES] = max_retries
    _emit_retry_exhausted(ctx, last_result, agent_name, max_retries)
    return last_result


def _emit_retry_outcome(
    ctx: AgentExecutionContext,
    result: Dict[str, Any],
    agent_name: str,
    attempt: int,
    max_retries: int,
    delay: float,
) -> None:
    """Emit a retry event for a completed attempt (success or permanent error)."""
    status = result.get(StateKeys.STATUS, "")
    error_type = result.get(StateKeys.OUTPUT_DATA, {}).get(StateKeys.ERROR_TYPE)
    outcome = RETRY_OUTCOME_SUCCESS if status == "success" else RETRY_OUTCOME_FAILED

    emit_retry_event(
        tracker=ctx.tracker,
        stage_id=ctx.stage_id,
        event_data=RetryEventData(
            attempt_number=attempt,
            max_retries=max_retries,
            agent_name=agent_name,
            stage_name=ctx.stage_name,
            outcome=outcome,
            error_type=error_type,
            is_transient=is_transient_error(error_type) if error_type else None,
            backoff_delay_seconds=delay,
        ),
    )


def _emit_retry_exhausted(
    ctx: AgentExecutionContext,
    result: Dict[str, Any],
    agent_name: str,
    max_retries: int,
) -> None:
    """Emit a retry-exhausted event after all attempts failed."""
    error_type = result.get(StateKeys.OUTPUT_DATA, {}).get(StateKeys.ERROR_TYPE) if result else None

    emit_retry_event(
        tracker=ctx.tracker,
        stage_id=ctx.stage_id,
        event_data=RetryEventData(
            attempt_number=max_retries,
            max_retries=max_retries,
            agent_name=agent_name,
            stage_name=ctx.stage_name,
            outcome=RETRY_OUTCOME_EXHAUSTED,
            error_type=error_type,
            is_transient=True,
        ),
    )


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
    ctx: AgentExecutionContext,
    agent_ref: Any,
    accum: AgentResultAccumulators,
) -> tuple[str, Dict[str, Any]]:
    """Handle retry_agent failure policy. Returns (action, result_to_store)."""
    max_retries = error_handling.max_agent_retries
    error_type = agent_result[StateKeys.OUTPUT_DATA].get(StateKeys.ERROR_TYPE, "")

    if is_transient_error(error_type) and max_retries > 0:
        retry_result = retry_agent_with_backoff(
            ctx=ctx,
            agent_ref=agent_ref,
            prior_agent_outputs=accum.outputs,
            max_retries=max_retries,
            agent_name=agent_name,
        )
        return "store", retry_result

    if not is_transient_error(error_type):
        logger.warning(
            "Agent %s failed with permanent error type '%s' in stage %s "
            "(policy: retry_agent, not retrying): %s",
            agent_name, error_type, ctx.stage_name,
            agent_result[StateKeys.OUTPUT_DATA].get(StateKeys.ERROR, ""),
        )
    else:
        logger.warning(
            "Agent %s failed in stage %s (policy: retry_agent, "
            "max_retries=0): %s",
            agent_name, ctx.stage_name,
            agent_result[StateKeys.OUTPUT_DATA].get(StateKeys.ERROR, ""),
        )
    return "store", agent_result


def _handle_agent_failure(
    agent_name: str,
    agent_result: Dict[str, Any],
    error_handling: Any,
    ctx: AgentExecutionContext,
    agent_ref: Any,
    accum: AgentResultAccumulators,
) -> tuple[str, Dict[str, Any]]:
    """Handle agent failure based on error_handling policy.

    Args:
        agent_name: Name of the failed agent
        agent_result: Result dictionary from the failed agent
        error_handling: Error handling configuration
        ctx: Agent execution context bundle
        agent_ref: Agent reference from stage config
        accum: Result accumulators (outputs, statuses, metrics)

    Returns:
        Tuple of (action, result_to_store)
        action: "break" | "continue" | "store"
    """
    policy = error_handling.on_agent_failure

    if policy == "halt_stage":
        logger.warning(
            "Agent %s failed in stage %s (policy: halt_stage), stopping execution: %s",
            agent_name, ctx.stage_name, agent_result[StateKeys.OUTPUT_DATA].get(StateKeys.ERROR, "")
        )
        return "break", agent_result

    if policy == "skip_agent":
        logger.warning(
            "Agent %s failed in stage %s (policy: skip_agent), skipping: %s",
            agent_name, ctx.stage_name, agent_result[StateKeys.OUTPUT_DATA].get(StateKeys.ERROR, "")
        )
        return "continue", agent_result

    if policy == "retry_agent":
        return _handle_retry_policy(
            agent_name, agent_result, error_handling,
            ctx, agent_ref, accum,
        )

    # continue_with_remaining
    logger.warning(
        "Agent %s failed in stage %s (policy: continue_with_remaining), continuing: %s",
        agent_name, ctx.stage_name, agent_result[StateKeys.OUTPUT_DATA].get(StateKeys.ERROR, "")
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
    ctx: AgentExecutionContext,
    agent_ref: Any,
    accum: AgentResultAccumulators,
) -> Optional[str]:
    """Process a failed agent result. Returns 'break'/'continue' or None to store and continue.

    Args:
        agent_name: Name of the failed agent
        agent_result: Result dictionary from the failed agent
        error_handling: Error handling configuration
        ctx: Agent execution context bundle
        agent_ref: Agent reference from stage config
        accum: Result accumulators (outputs, statuses, metrics)

    Returns:
        Optional control flow directive: "break", "continue", or None
    """
    accum.statuses[agent_name] = {
        StateKeys.STATUS: "failed",
        StateKeys.ERROR: agent_result[StateKeys.OUTPUT_DATA].get(StateKeys.ERROR, ""),
        StateKeys.ERROR_TYPE: agent_result[StateKeys.OUTPUT_DATA].get(StateKeys.ERROR_TYPE, ""),
    }

    action, result_to_store = _handle_agent_failure(
        agent_name, agent_result, error_handling,
        ctx, agent_ref, accum
    )

    if action == "break":
        accum.outputs[agent_name] = result_to_store[StateKeys.OUTPUT_DATA]
        accum.metrics[agent_name] = result_to_store[StateKeys.METRICS]
        return "break"
    if action == "continue":
        accum.metrics[agent_name] = result_to_store[StateKeys.METRICS]
        return "continue"

    _store_failure_result(result_to_store, accum.statuses, accum.outputs, accum.metrics)
    return None


def run_all_agents(
    ctx: AgentExecutionContext,
    agents: list,
    error_handling: Any,
) -> tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Execute all agents in sequence with configurable error handling.

    Args:
        ctx: Agent execution context bundle
        agents: List of agent references to execute
        error_handling: Error handling configuration

    Returns:
        Tuple of (agent_outputs, agent_statuses, agent_metrics)
    """
    accum = AgentResultAccumulators(
        outputs={},
        statuses={},
        metrics={},
    )

    show_details = ctx.state.get(StateKeys.SHOW_DETAILS, False)
    detail_console = ctx.state.get(StateKeys.DETAIL_CONSOLE)
    if show_details and detail_console:
        detail_console.print(f"\n[bold cyan]── Stage: {ctx.stage_name} ──[/bold cyan]")

    total_agents = len(agents)
    prior_stages = list(ctx.state.get(StateKeys.STAGE_OUTPUTS, {}).keys())
    input_info = f"prior stages: {prior_stages}" if prior_stages else "workflow inputs only"
    logger.info("Stage '%s' starting sequential execution with %d agent(s) (%s)", ctx.stage_name, total_agents, input_info)

    for agent_idx, agent_ref in enumerate(agents):
        agent_result = execute_agent(
            ctx=ctx,
            agent_ref=agent_ref,
            prior_agent_outputs=accum.outputs,
        )

        agent_name = agent_result[StateKeys.AGENT_NAME]
        logger.info("Stage '%s' agent '%s' completed (%s)", ctx.stage_name, agent_name, agent_result[StateKeys.STATUS])

        if show_details and detail_console:
            is_last = (agent_idx == total_agents - 1)
            _print_agent_progress(detail_console, agent_name, agent_result, is_last)

        if agent_result[StateKeys.STATUS] == "failed":
            loop_action = _process_agent_failure(
                agent_name, agent_result, error_handling,
                ctx, agent_ref, accum,
            )
            if loop_action == "break":
                break
            if loop_action == "continue":
                continue
        else:
            accum.statuses[agent_name] = agent_result[StateKeys.STATUS]
            accum.outputs[agent_name] = agent_result[StateKeys.OUTPUT_DATA]
            accum.metrics[agent_name] = agent_result[StateKeys.METRICS]

    _emit_sequential_cost_summary(ctx, accum)
    return accum.outputs, accum.statuses, accum.metrics


def _emit_sequential_cost_summary(
    ctx: AgentExecutionContext,
    accum: AgentResultAccumulators,
) -> None:
    """Emit cost rollup for sequential stage execution."""
    try:
        from src.observability.cost_rollup import (
            compute_stage_cost_summary,
            emit_cost_summary,
        )

        summary = compute_stage_cost_summary(
            ctx.stage_name, accum.metrics, accum.statuses,
        )
        emit_cost_summary(ctx.tracker, ctx.stage_id, summary)
    except Exception:
        logger.debug(
            "Failed to emit cost summary for stage %s",
            ctx.stage_name,
            exc_info=True,
        )
