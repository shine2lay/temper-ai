"""Helper functions extracted from SequentialStageExecutor to reduce class size.

Contains:
- Single agent execution logic
- All-agents sequential run loop
- Error classification and result building

Retry/backoff/failure-policy logic lives in _sequential_retry.py.
"""

import logging
import time
import traceback
import uuid
from dataclasses import dataclass
from typing import Any

from temper_ai.shared.constants.sizes import UUID_HEX_SHORT_LENGTH
from temper_ai.shared.core.circuit_breaker import CircuitBreakerError
from temper_ai.shared.utils.exceptions import (
    BaseError,
    ConfigNotFoundError,
    ConfigValidationError,
    ErrorCode,
    LLMError,
    ToolExecutionError,
    sanitize_error_message,
)
from temper_ai.stage.executors._agent_execution import (
    config_to_tracking_dict,
    load_or_cache_agent,
    resolve_agent_factory,
)
from temper_ai.stage.executors._base_helpers import (
    _save_conversation_turn,
    build_agent_output_params,
    prepare_tracking_input,
)

# Re-export retry helpers for backward compatibility
from temper_ai.stage.executors._sequential_retry import (  # noqa: F401
    _TRANSIENT_ERROR_TYPES,
    MAX_RETRY_BACKOFF_DIVISOR,
    _emit_retry_exhausted,
    _emit_retry_outcome,
    _execute_retry_attempt,
    _handle_agent_failure,
    _handle_retry_policy,
    _process_agent_failure,
    _store_failure_result,
    is_transient_error,
    retry_agent_with_backoff,
)
from temper_ai.stage.executors.state_keys import StateKeys

logger = logging.getLogger(__name__)


@dataclass
class AgentExecutionContext:
    """Bundles common parameters for agent execution in sequential mode."""

    executor: Any  # SequentialStageExecutor instance
    stage_id: str
    stage_name: str
    workflow_id: str
    state: dict[str, Any]
    tracker: Any | None
    config_loader: Any
    agent_factory_cls: Any = None
    context_provider: Any | None = None
    stage_config: Any | None = None


@dataclass
class AgentResultAccumulators:
    """Groups mutable output accumulators passed through the agent execution chain."""

    outputs: dict[str, Any]
    statuses: dict[str, Any]
    metrics: dict[str, Any]


def execute_agent(
    ctx: AgentExecutionContext,
    agent_ref: Any,
    prior_agent_outputs: dict[str, Any] | None = None,
) -> dict[str, Any]:
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
    except (
        CircuitBreakerError,
        BaseError,
        ToolExecutionError,
        LLMError,
        ConfigNotFoundError,
        ConfigValidationError,
        TimeoutError,
        ConnectionError,
        ValueError,
        RuntimeError,
    ) as e:
        duration = time.time() - start_time
        return _build_error_result(agent_name, e, duration)


# Maps stdlib exception class names to error codes for non-framework exceptions
_STDLIB_ERROR_TYPE_MAP: dict[str, str] = {
    "TimeoutError": ErrorCode.SYSTEM_TIMEOUT.value,
    "ConnectionError": ErrorCode.LLM_CONNECTION_ERROR.value,
    "ValueError": ErrorCode.VALIDATION_ERROR.value,
    "RuntimeError": ErrorCode.AGENT_EXECUTION_ERROR.value,
}


def _classify_error(
    agent_name: str,
    e: Exception,
) -> tuple[str, str, str]:
    """Classify an exception into error_type, message, and traceback.

    Also logs the failure at the appropriate level.

    Returns:
        Tuple of (error_type, sanitized_message, sanitized_traceback)
    """
    error_message = sanitize_error_message(str(e))
    error_traceback = sanitize_error_message(traceback.format_exc())

    if isinstance(e, CircuitBreakerError):
        logger.error(
            "Agent %s failed: Circuit breaker OPEN (provider unhealthy). "
            "Subsequent agents using same provider will fast-fail. Error: %s",
            agent_name,
            error_message,
        )
        return ErrorCode.LLM_CONNECTION_ERROR.value, error_message, error_traceback

    if isinstance(e, BaseError):
        logger.warning("Agent %s failed in stage: %s", agent_name, error_message)
        return e.error_code.value, error_message, error_traceback

    error_type = _STDLIB_ERROR_TYPE_MAP.get(
        type(e).__name__,
        ErrorCode.UNKNOWN_ERROR.value,
    )
    logger.warning("Agent %s failed in stage: %s", agent_name, error_message)
    return error_type, error_message, error_traceback


def _compute_error_fingerprint(e: Exception, error_type: str) -> str | None:
    """Compute an error fingerprint (best-effort, never raises)."""
    try:
        from temper_ai.observability.error_fingerprinting import compute_fingerprint

        return compute_fingerprint(type(e).__name__, error_type, str(e))
    except Exception:  # noqa: BLE001 — fingerprinting must never disrupt execution
        return None


def _build_error_result(
    agent_name: str, e: Exception, duration: float
) -> dict[str, Any]:
    """Build error result dict from an exception."""
    error_type, error_message, error_traceback = _classify_error(agent_name, e)
    fingerprint = _compute_error_fingerprint(e, error_type)

    output_data: dict[str, Any] = {
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


def _load_or_cache_agent_seq(
    ctx: AgentExecutionContext,
    agent_name: str,
) -> tuple:
    """Load agent from cache or create via shared loader."""
    agent_factory = resolve_agent_factory(ctx.agent_factory_cls)
    return load_or_cache_agent(
        agent_name,
        ctx.config_loader,
        ctx.executor._agent_cache,
        agent_factory,
    )


def _build_legacy_input(
    ctx: AgentExecutionContext,
    prior_agent_outputs: dict[str, Any],
) -> dict[str, Any]:
    """Build input from full state with workflow_inputs unwrapped (legacy path)."""
    if hasattr(ctx.state, "to_dict"):
        state_dict = ctx.state.to_dict(exclude_internal=True)
    else:
        state_dict = dict(ctx.state) if hasattr(ctx.state, "__iter__") else ctx.state

    wi = {
        k: v
        for k, v in state_dict.get(StateKeys.WORKFLOW_INPUTS, {}).items()
        if k not in StateKeys.RESERVED_UNWRAP_KEYS
    }

    return {
        **state_dict,
        **wi,
        StateKeys.STAGE_OUTPUTS: state_dict.get(StateKeys.STAGE_OUTPUTS, {}),
        StateKeys.CURRENT_STAGE_AGENTS: dict(prior_agent_outputs),
    }


def _prepare_sequential_input(
    ctx: AgentExecutionContext,
    prior_agent_outputs: dict[str, Any],
    context_provider: Any | None = None,
    stage_config: Any | None = None,
) -> dict[str, Any]:
    """Prepare input data for sequential agent execution.

    When ``context_provider`` and ``stage_config`` are supplied and the
    stage declares inputs with source refs, resolved (focused) context
    is returned instead of the full state.
    """
    # Dynamic inputs override normal resolution
    dynamic = ctx.state.get(StateKeys.DYNAMIC_INPUTS)
    if dynamic is not None:
        from temper_ai.workflow.context_provider import _INFRASTRUCTURE_KEYS

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
            logger.warning(
                "Context provider resolution failed for stage '%s', "
                "falling back to full state. Named Jinja variables from "
                "stage inputs may not be available.",
                ctx.stage_name,
                exc_info=True,
            )

    return _build_legacy_input(ctx, prior_agent_outputs)


def _execute_and_track_agent(
    agent: Any,
    input_data: dict[str, Any],
    context: Any,
    agent_name: str,
    agent_config_dict: dict[str, Any],
    ctx: AgentExecutionContext,
) -> Any:
    """Execute agent with tracker and set output."""
    from temper_ai.shared.utils.config_helpers import sanitize_config_for_display

    agent_config_for_tracking = sanitize_config_for_display(agent_config_dict)
    tracking_input_data = prepare_tracking_input(input_data)

    if ctx.tracker is None:
        raise ValueError("Tracker required for agent execution tracking")
    with ctx.tracker.track_agent(
        agent_name=agent_name,
        agent_config=agent_config_for_tracking,
        stage_id=ctx.stage_id,
        input_data=tracking_input_data,
    ) as agent_id:
        context.agent_id = agent_id
        input_data[StateKeys.TRACKER] = ctx.tracker
        response = agent.execute(input_data, context)
        ctx.tracker.set_agent_output(build_agent_output_params(agent_id, response))

    return response


def _build_success_result(
    agent_name: str, response: Any, duration: float
) -> dict[str, Any]:
    """Build success result dict from an agent response."""
    output_data: dict[str, Any] = {
        StateKeys.OUTPUT: response.output,
        StateKeys.REASONING: response.reasoning,
        StateKeys.CONFIDENCE: response.confidence,
        StateKeys.TOKENS: response.tokens,
        StateKeys.COST_USD: response.estimated_cost_usd,
        StateKeys.TOOL_CALLS: response.tool_calls if response.tool_calls else [],
    }
    # Preserve script agent ::output directives for structured extraction
    script_outputs = getattr(response, "metadata", {}).get("outputs")
    if script_outputs:
        output_data["script_outputs"] = script_outputs
    return {
        StateKeys.AGENT_NAME: agent_name,
        StateKeys.OUTPUT_DATA: output_data,
        StateKeys.STATUS: "success",
        StateKeys.METRICS: {
            StateKeys.TOKENS: response.tokens or 0,
            StateKeys.COST_USD: response.estimated_cost_usd or 0.0,
            StateKeys.DURATION_SECONDS: duration,
            StateKeys.TOOL_CALLS: (
                len(response.tool_calls) if response.tool_calls else 0
            ),
        },
    }


def _wire_tool_executor(ctx: AgentExecutionContext, input_data: dict[str, Any]) -> None:
    """Wire tool executor and rate limiter from executor to input data."""
    _tool_exec = getattr(ctx.executor, "tool_executor", None)
    if _tool_exec is None:
        return
    input_data["tool_executor"] = _tool_exec
    wf_rl = ctx.state.get(StateKeys.WORKFLOW_RATE_LIMITER)
    if wf_rl is not None:
        _tool_exec.workflow_rate_limiter = wf_rl


def _dispatch_sequential_evaluation(
    ctx: AgentExecutionContext,
    agent_name: str,
    context: Any,
    input_data: dict[str, Any],
    response: Any,
    agent_config_dict: dict[str, Any],
    duration: float,
) -> None:
    """Dispatch async evaluation for a sequential agent (non-blocking)."""
    dispatcher = ctx.state.get(StateKeys.EVALUATION_DISPATCHER)
    if dispatcher is None:
        return
    dispatcher.dispatch(
        agent_name=agent_name,
        agent_execution_id=context.agent_id,
        input_data=input_data,
        output_data=response.output,
        metrics={
            StateKeys.TOKENS: response.tokens,
            StateKeys.COST_USD: response.estimated_cost_usd,
            StateKeys.DURATION_SECONDS: duration,
        },
        agent_context={
            "prompt": response.metadata.get("_rendered_prompt", ""),
            "reasoning": response.reasoning,
            "tool_calls": response.tool_calls,
            "confidence": response.confidence,
            "model": agent_config_dict.get("agent", {})
            .get("inference", {})
            .get("model", ""),
            "stage_name": ctx.stage_name,
        },
    )


def run_agent(  # noqa: long
    ctx: AgentExecutionContext,
    agent_name: str,
    agent_ref: Any,
    prior_agent_outputs: dict[str, Any],
    start_time: float,
) -> dict[str, Any]:
    """Internal: load, execute, and track a single agent.

    Returns:
        Dict with keys: agent_name, output_data, status, metrics
    """
    from temper_ai.llm.conversation import ConversationHistory, make_history_key
    from temper_ai.shared.core.context import ExecutionContext

    agent, agent_config, agent_config_dict = _load_or_cache_agent_seq(ctx, agent_name)
    input_data = _prepare_sequential_input(
        ctx,
        prior_agent_outputs,
        context_provider=ctx.context_provider,
        stage_config=ctx.stage_config,
    )
    _wire_tool_executor(ctx, input_data)

    history_key = make_history_key(ctx.stage_name, agent_name)
    histories = ctx.state.get(StateKeys.CONVERSATION_HISTORIES, {})
    history_data = histories.get(history_key)
    if history_data is not None:
        input_data["_conversation_history"] = ConversationHistory.from_dict(
            history_data
        )

    context = ExecutionContext(
        workflow_id=ctx.workflow_id,
        stage_id=ctx.stage_id,
        agent_id=f"agent-{uuid.uuid4().hex[:UUID_HEX_SHORT_LENGTH]}",
        metadata={
            "stage_name": ctx.stage_name,
            "agent_name": agent_name,
            "workflow_name": ctx.state.get("workflow_name", ""),
        },
    )

    if ctx.tracker:
        from temper_ai.shared.utils.config_helpers import sanitize_config_for_display

        agent_config_dict_for_tracking = sanitize_config_for_display(
            config_to_tracking_dict(agent_config, agent_config_dict)
        )
        response = _execute_and_track_agent(
            agent, input_data, context, agent_name, agent_config_dict_for_tracking, ctx
        )
    else:
        response = agent.execute(input_data, context)

    duration = time.time() - start_time
    result = _build_success_result(agent_name, response, duration)
    _save_conversation_turn(ctx.state, history_key, input_data, response)
    _dispatch_sequential_evaluation(
        ctx, agent_name, context, input_data, response, agent_config_dict, duration
    )

    return result


def _print_agent_progress(
    detail_console: Any, agent_name: str, agent_result: dict[str, Any], is_last: bool
) -> None:
    """Print real-time progress for a single agent."""
    connector = "\u2514\u2500" if is_last else "\u251c\u2500"
    metrics = agent_result.get(StateKeys.METRICS, {})
    duration = metrics.get(StateKeys.DURATION_SECONDS, 0.0)
    tokens = metrics.get(StateKeys.TOKENS, 0)

    if agent_result[StateKeys.STATUS] == "failed":
        error_type = agent_result.get(StateKeys.OUTPUT_DATA, {}).get(
            StateKeys.ERROR_TYPE, "error"
        )
        detail_console.print(
            f"  {connector} [red]{agent_name} \u2717[/red] ({duration:.1f}s) [{error_type}]"
        )
    else:
        detail_console.print(
            f"  {connector} [green]{agent_name} \u2713[/green] ({duration:.1f}s, {tokens} tokens)"
        )


def _print_sequential_stage_header(ctx: AgentExecutionContext) -> None:
    """Print stage header with index and set stream callback stage context."""
    detail_console = ctx.state.get(StateKeys.DETAIL_CONSOLE)
    if not detail_console:
        return
    stage_index = len(ctx.state.get(StateKeys.STAGE_OUTPUTS, {})) + 1
    total = ctx.state.get(StateKeys.TOTAL_STAGES, "?")
    detail_console.print(
        f"\n[bold cyan]\u27f3 [{stage_index}/{total}] "
        f"Stage: {ctx.stage_name} \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500[/bold cyan]"
    )
    stream_cb = ctx.state.get(StateKeys.STREAM_CALLBACK)
    if stream_cb is not None and hasattr(stream_cb, "_current_stage"):
        stream_cb._current_stage = ctx.stage_name


def run_all_agents(  # noqa: long radon
    ctx: AgentExecutionContext,
    agents: list,
    error_handling: Any,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Execute all agents in sequence with configurable error handling.

    Args:
        ctx: Agent execution context bundle
        agents: List of agent references to execute
        error_handling: Error handling configuration

    Returns:
        Tuple of (agent_outputs, agent_statuses, agent_metrics)
    """
    accum = AgentResultAccumulators(outputs={}, statuses={}, metrics={})

    show_details = ctx.state.get(StateKeys.SHOW_DETAILS, False)
    detail_console = ctx.state.get(StateKeys.DETAIL_CONSOLE)
    if show_details and detail_console:
        _print_sequential_stage_header(ctx)

    total_agents = len(agents)
    prior_stages = list(ctx.state.get(StateKeys.STAGE_OUTPUTS, {}).keys())
    input_info = (
        f"prior stages: {prior_stages}" if prior_stages else "workflow inputs only"
    )
    logger.info(
        "Stage '%s' starting sequential execution with %d agent(s) (%s)",
        ctx.stage_name,
        total_agents,
        input_info,
    )

    for agent_idx, agent_ref in enumerate(agents):
        if show_details and detail_console:
            ref_name = ctx.executor._extract_agent_name(agent_ref)
            detail_console.print(f"  [dim]\u27f3 {ref_name} running...[/dim]")

        agent_result = execute_agent(
            ctx=ctx, agent_ref=agent_ref, prior_agent_outputs=accum.outputs
        )
        agent_name = agent_result[StateKeys.AGENT_NAME]
        logger.info(
            "Stage '%s' agent '%s' completed (%s)",
            ctx.stage_name,
            agent_name,
            agent_result[StateKeys.STATUS],
        )

        if show_details and detail_console:
            _print_agent_progress(
                detail_console, agent_name, agent_result, agent_idx == total_agents - 1
            )

        if agent_result[StateKeys.STATUS] == "failed":
            loop_action = _process_agent_failure(
                agent_name, agent_result, error_handling, ctx, agent_ref, accum
            )
            if loop_action == "break":
                break
            if loop_action == "continue":
                continue
        else:
            accum.statuses[agent_name] = agent_result[StateKeys.STATUS]
            accum.outputs[agent_name] = agent_result[StateKeys.OUTPUT_DATA]
            accum.metrics[agent_name] = agent_result[StateKeys.METRICS]

    if show_details and detail_console:
        detail_console.print("[bold green]  \u2713 Stage complete[/bold green]")

    _emit_sequential_cost_summary(ctx, accum)
    return accum.outputs, accum.statuses, accum.metrics


def _emit_sequential_cost_summary(
    ctx: AgentExecutionContext,
    accum: AgentResultAccumulators,
) -> None:
    """Emit cost rollup for sequential stage execution."""
    try:
        from temper_ai.observability.cost_rollup import (
            compute_stage_cost_summary,
            emit_cost_summary,
        )

        summary = compute_stage_cost_summary(
            ctx.stage_name,
            accum.metrics,
            accum.statuses,
        )
        emit_cost_summary(ctx.tracker, ctx.stage_id, summary)
    except Exception:
        logger.debug(
            "Failed to emit cost summary for stage %s",
            ctx.stage_name,
            exc_info=True,
        )
