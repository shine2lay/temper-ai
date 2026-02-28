"""Helper functions extracted from ParallelStageExecutor to reduce class size.

Contains:
- Agent node creation for parallel execution
- Parallel execution orchestration
- Output collection and metric aggregation

Quality gate logic lives in _parallel_quality_gates.py.
"""

import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from temper_ai.shared.constants.limits import DEFAULT_MIN_ITEMS
from temper_ai.shared.constants.sizes import UUID_HEX_SHORT_LENGTH
from temper_ai.shared.core.context import ExecutionContext
from temper_ai.shared.utils.exceptions import (
    ConfigNotFoundError,
    ConfigValidationError,
    LLMError,
    ToolExecutionError,
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
from temper_ai.stage.executors._parallel_observability import (
    _emit_output_lineage,
    _emit_parallel_cost_summary,
    _emit_synthesis_event,
)

# Re-export quality gate helpers for backward compatibility
from temper_ai.stage.executors._parallel_quality_gates import (  # noqa: F401
    QualityGateFailureParams,
    QualityGateRetryParams,
    _check_inline_quality_gates,
    _check_retry_timeout,
    _extract_result_field,
    _handle_quality_gate_escalate,
    _handle_quality_gate_retry,
    _handle_quality_gate_warn,
    _reset_retry_counter_on_pass,
    handle_quality_gate_failure,
    validate_quality_gates,
)
from temper_ai.stage.executors.state_keys import StateKeys
from temper_ai.workflow.context_provider import ContextResolutionError

logger = logging.getLogger(__name__)


@dataclass
class AgentNodeParams:
    """Parameters for creating agent execution node (bundles 10 params into 1)."""

    agent_name: str
    agent_ref: Any
    stage_name: str
    state: dict[str, Any]
    config_loader: Any
    agent_cache: dict[str, Any]
    agent_factory_cls: Any = None
    tracker: Any | None = None
    stage_id: str | None = None
    tool_executor: Any | None = None


@dataclass
class AgentRunParams:
    """Parameters for running agent with/without tracking (bundles 8 params into 1)."""

    agent: Any
    input_data: dict[str, Any]
    context: Any
    agent_name: str
    agent_config_dict_for_tracking: dict[str, Any]
    tracker: Any | None
    stage_id: str | None
    effective_stage_id: str


def _prepare_agent_input(s: dict[str, Any]) -> dict[str, Any]:
    """Prepare agent input data by unwrapping workflow_inputs and filtering reserved keys.

    If STAGE_INPUT contains a ``_context_resolved`` flag, the context was
    already resolved by a ContextProvider -- skip the unwrap step.
    """
    input_data = s.get(StateKeys.STAGE_INPUT, {})

    # If context was already resolved by ContextProvider, use it directly
    if input_data.get("_context_resolved"):
        result = dict(input_data)
        result.pop("_context_resolved", None)
        return result

    wi = {
        k: v
        for k, v in input_data.get(StateKeys.WORKFLOW_INPUTS, {}).items()
        if k not in StateKeys.RESERVED_UNWRAP_KEYS
    }
    return {**input_data, **wi}


def _build_agent_success_result(
    agent_name: str, response: Any, duration: float
) -> dict[str, Any]:
    """Build success result dict from agent response."""
    agent_data: dict[str, Any] = {
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
        agent_data["script_outputs"] = script_outputs
    return {
        StateKeys.AGENT_OUTPUTS: {agent_name: agent_data},
        StateKeys.AGENT_STATUSES: {agent_name: "success"},
        StateKeys.AGENT_METRICS: {
            agent_name: {
                StateKeys.TOKENS: response.tokens,
                StateKeys.COST_USD: response.estimated_cost_usd,
                StateKeys.DURATION_SECONDS: duration,
                StateKeys.TOOL_CALLS: (
                    len(response.tool_calls) if response.tool_calls else 0
                ),
                StateKeys.RETRIES: 0,
            }
        },
        StateKeys.ERRORS: {},
    }


def _build_agent_error_result(
    agent_name: str, e: Exception, duration: float
) -> dict[str, Any]:
    """Build error result dict from exception."""
    return {
        StateKeys.AGENT_OUTPUTS: {},
        StateKeys.AGENT_STATUSES: {agent_name: "failed"},
        StateKeys.AGENT_METRICS: {
            agent_name: {
                StateKeys.TOKENS: 0,
                StateKeys.COST_USD: 0.0,
                StateKeys.DURATION_SECONDS: duration,
                StateKeys.TOOL_CALLS: 0,
                StateKeys.RETRIES: 0,
            }
        },
        StateKeys.ERRORS: {agent_name: f"{type(e).__name__}: {str(e)}"},
    }


def _execute_agent_with_tracking(
    agent: Any,
    input_data: dict[str, Any],
    context: Any,
    agent_name: str,
    agent_config_dict: dict[str, Any],
    tracker: Any,
    stage_id: str,
) -> Any:
    """Execute agent with tracker context and set output tracking."""
    from temper_ai.shared.utils.config_helpers import sanitize_config_for_display

    agent_config_for_tracking = sanitize_config_for_display(agent_config_dict)
    tracking_input_data = prepare_tracking_input(input_data)

    with tracker.track_agent(
        agent_name=agent_name,
        agent_config=agent_config_for_tracking,
        stage_id=stage_id,
        input_data=tracking_input_data,
    ) as agent_id:
        context.agent_id = agent_id
        input_data[StateKeys.TRACKER] = tracker
        response = agent.execute(input_data, context)

        try:
            tracker.set_agent_output(build_agent_output_params(agent_id, response))
        except Exception:
            logger.warning(
                "Failed to set agent output tracking for %s", agent_name, exc_info=True
            )

    return response


def _create_agent_context(
    state: dict[str, Any],
    stage_name: str,
    agent_name: str,
    effective_stage_id: str,
) -> Any:
    """Create ExecutionContext for an agent node."""
    return ExecutionContext(
        workflow_id=state.get(StateKeys.WORKFLOW_ID, "unknown"),
        stage_id=effective_stage_id,
        agent_id=f"agent-{uuid.uuid4().hex[:UUID_HEX_SHORT_LENGTH]}",
        metadata={
            "stage_name": stage_name,
            "agent_name": agent_name,
            "execution_mode": "parallel",
        },
    )


def _run_agent(params: AgentRunParams) -> Any:
    """Execute agent with or without tracking."""
    if params.tracker and params.stage_id:
        return _execute_agent_with_tracking(
            params.agent,
            params.input_data,
            params.context,
            params.agent_name,
            params.agent_config_dict_for_tracking,
            params.tracker,
            params.effective_stage_id,
        )
    params.input_data.pop(StateKeys.TRACKER, None)
    return params.agent.execute(params.input_data, params.context)


def _dispatch_parallel_evaluation(
    params: AgentNodeParams,
    context: Any,
    input_data: dict[str, Any],
    response: Any,
    agent_config_dict: dict[str, Any],
    duration: float,
) -> None:
    """Dispatch async evaluation for a parallel agent (non-blocking)."""
    dispatcher = params.state.get(StateKeys.EVALUATION_DISPATCHER)
    if dispatcher is None:
        return
    dispatcher.dispatch(
        agent_name=params.agent_name,
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
            "stage_name": params.stage_name,
        },
    )


def _execute_parallel_agent(
    params: AgentNodeParams, s: dict[str, Any]
) -> dict[str, Any]:
    """Core logic for executing a single parallel agent node."""
    from temper_ai.llm.conversation import ConversationHistory, make_history_key

    start_time = time.time()
    agent_factory = resolve_agent_factory(params.agent_factory_cls)
    agent, agent_config, agent_config_dict = load_or_cache_agent(
        params.agent_name, params.config_loader, params.agent_cache, agent_factory
    )
    input_data = _prepare_agent_input(s)

    if params.tool_executor is not None:
        input_data["tool_executor"] = params.tool_executor

    history_key = make_history_key(params.stage_name, params.agent_name)
    histories = params.state.get(StateKeys.CONVERSATION_HISTORIES, {})
    history_data = histories.get(history_key)
    if history_data is not None:
        input_data["_conversation_history"] = ConversationHistory.from_dict(
            history_data
        )

    agent_config_dict_for_tracking = config_to_tracking_dict(
        agent_config, agent_config_dict
    )
    effective_stage_id = (
        params.stage_id
        if params.stage_id
        else f"stage-{uuid.uuid4().hex[:UUID_HEX_SHORT_LENGTH]}"
    )
    context = _create_agent_context(
        params.state, params.stage_name, params.agent_name, effective_stage_id
    )

    run_params = AgentRunParams(
        agent=agent,
        input_data=input_data,
        context=context,
        agent_name=params.agent_name,
        agent_config_dict_for_tracking=agent_config_dict_for_tracking,
        tracker=params.tracker,
        stage_id=params.stage_id,
        effective_stage_id=effective_stage_id,
    )
    response = _run_agent(run_params)
    _save_conversation_turn(params.state, history_key, input_data, response)

    duration = time.time() - start_time
    _dispatch_parallel_evaluation(
        params, context, input_data, response, agent_config_dict, duration
    )
    return _build_agent_success_result(params.agent_name, response, duration)


def create_agent_node(
    params: AgentNodeParams,
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """Create execution node for a single agent in parallel execution."""

    def agent_node(s: dict[str, Any]) -> dict[str, Any]:
        """Execute single agent and store result."""
        try:
            return _execute_parallel_agent(params, s)
        except (
            ConfigNotFoundError,
            ConfigValidationError,
            ValueError,
            TypeError,
            KeyError,
        ) as e:
            logger.info(
                f"Agent {params.agent_name} configuration/validation error: {e}"
            )
            return _build_agent_error_result(params.agent_name, e, time.time())
        except (KeyboardInterrupt, SystemExit):
            raise
        except (RuntimeError, ToolExecutionError, LLMError) as e:
            logger.error(
                f"Unexpected error in agent {params.agent_name}: {type(e).__name__}: {e}",
                exc_info=True,
            )
            return _build_agent_error_result(params.agent_name, e, time.time())

    return agent_node


def build_collect_outputs_node(  # noqa: long
    agents: list,
    stage_config: Any,
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """Build the collection node function for parallel execution."""

    def collect_outputs(s: dict[str, Any]) -> dict[str, Any]:
        """Collect and validate agent outputs, calculate aggregate metrics."""
        stage_dict = stage_config if isinstance(stage_config, dict) else {}
        error_handling = stage_dict.get("error_handling", {})
        min_successful = error_handling.get("min_successful_agents", DEFAULT_MIN_ITEMS)

        agent_statuses = s.get(StateKeys.AGENT_STATUSES, {})
        successful = [
            name for name, status in agent_statuses.items() if status == "success"
        ]

        if len(successful) < min_successful:
            raise RuntimeError(
                f"Only {len(successful)}/{len(agents)} agents succeeded. "
                f"Minimum required: {min_successful}"
            )

        agent_metrics = s.get(StateKeys.AGENT_METRICS, {})
        agent_outputs_dict = s.get(StateKeys.AGENT_OUTPUTS, {})

        total_tokens = 0
        total_cost = 0.0
        max_duration = 0.0
        total_confidence = 0.0
        num_successful = 0

        for agent_name, metrics in agent_metrics.items():
            if agent_statuses.get(agent_name) == "success":
                total_tokens += metrics.get(StateKeys.TOKENS, 0)
                total_cost += metrics.get(StateKeys.COST_USD, 0.0)
                max_duration = max(
                    max_duration, metrics.get(StateKeys.DURATION_SECONDS, 0.0)
                )

                output = agent_outputs_dict.get(agent_name, {})
                total_confidence += output.get(StateKeys.CONFIDENCE, 0.0)
                num_successful += 1

        avg_confidence = (
            total_confidence / num_successful if num_successful > 0 else 0.0
        )

        return {
            StateKeys.AGENT_OUTPUTS: {
                StateKeys.AGGREGATE_METRICS_KEY: {
                    StateKeys.TOTAL_TOKENS: total_tokens,
                    StateKeys.TOTAL_COST_USD: total_cost,
                    StateKeys.TOTAL_DURATION_SECONDS: max_duration,
                    StateKeys.AVG_CONFIDENCE: avg_confidence,
                    StateKeys.NUM_AGENTS: len(agents),
                    StateKeys.NUM_SUCCESSFUL: num_successful,
                    StateKeys.NUM_FAILED: len(agents) - num_successful,
                }
            }
        }

    return collect_outputs


def _empty_parallel_state(stage_input: dict[str, Any]) -> dict[str, Any]:
    """Return an empty parallel state dict with the given stage input."""
    return {
        StateKeys.AGENT_OUTPUTS: {},
        StateKeys.AGENT_STATUSES: {},
        StateKeys.AGENT_METRICS: {},
        StateKeys.ERRORS: {},
        StateKeys.STAGE_INPUT: stage_input,
    }


def _resolve_dynamic_parallel_input(state: dict[str, Any]) -> dict[str, Any] | None:
    """Resolve dynamic inputs for parallel init, returning None if not present."""
    dynamic = state.get(StateKeys.DYNAMIC_INPUTS)
    if dynamic is None:
        return None
    from temper_ai.workflow.context_provider import _INFRASTRUCTURE_KEYS

    resolved: dict[str, Any] = dict(dynamic)
    resolved["_context_resolved"] = True
    for key in _INFRASTRUCTURE_KEYS:
        if key in state:
            resolved[key] = state[key]
    return resolved


def _resolve_context_parallel_input(
    state: dict[str, Any],
    context_provider: Any,
    stage_config: Any,
) -> dict[str, Any] | None:
    """Attempt focused context resolution for parallel init."""
    try:
        resolved = context_provider.resolve(stage_config, state)
        resolved["_context_resolved"] = True
        if "_context_meta" in resolved:
            state["_context_meta"] = resolved["_context_meta"]
        return resolved
    except ContextResolutionError:
        raise  # Let WorkflowExecutor handle required-input failures
    except Exception:  # noqa: BLE001
        logger.warning(
            "Context provider resolution failed for parallel stage, "
            "falling back to full state. Named Jinja variables from "
            "stage inputs may not be available.",
            exc_info=True,
        )
        return None


def build_init_parallel_node(
    state: dict[str, Any],
    context_provider: Any | None = None,
    stage_config: Any | None = None,
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """Build the init node function for parallel execution."""
    # Dynamic inputs override normal resolution
    dynamic_input = _resolve_dynamic_parallel_input(state)
    if dynamic_input is not None:

        def init_parallel_dynamic(s: dict[str, Any]) -> dict[str, Any]:
            """Initialize dynamic parallel execution state."""
            return _empty_parallel_state(dynamic_input)

        return init_parallel_dynamic

    # Try resolving focused context upfront
    resolved_input: dict[str, Any] | None = None
    if context_provider is not None and stage_config is not None:
        resolved_input = _resolve_context_parallel_input(
            state, context_provider, stage_config
        )

    def init_parallel(s: dict[str, Any]) -> dict[str, Any]:
        """Initialize standard parallel execution state."""
        if resolved_input is not None:
            stage_input = resolved_input
        else:
            stage_input = {
                **state,
                StateKeys.STAGE_OUTPUTS: state.get(StateKeys.STAGE_OUTPUTS, {}),
            }
        return _empty_parallel_state(stage_input)

    return init_parallel


def print_parallel_progress(
    parallel_result: dict[str, Any],
    detail_console: Any,
) -> None:
    """Print progress for parallel agents after all complete."""
    agent_statuses = parallel_result.get(StateKeys.AGENT_STATUSES, {})
    agent_metrics_dict = parallel_result.get(StateKeys.AGENT_METRICS, {})
    agent_names = list(agent_statuses.keys())
    for idx, aname in enumerate(agent_names):
        is_last = idx == len(agent_names) - 1
        connector = "\u2514\u2500" if is_last else "\u251c\u2500"
        status = agent_statuses.get(aname, "unknown")
        m = agent_metrics_dict.get(aname, {})
        duration = m.get(StateKeys.DURATION_SECONDS, 0.0)
        tokens = m.get(StateKeys.TOKENS, 0)

        if status == "success":
            detail_console.print(
                f"  {connector} [green]{aname} \u2713[/green] ({duration:.1f}s, {tokens} tokens)"
            )
        else:
            detail_console.print(
                f"  {connector} [red]{aname} \u2717[/red] ({duration:.1f}s)"
            )


def _compute_stage_status(agent_statuses: dict[str, Any]) -> str:
    """Compute stage status from agent results."""
    failed_count = sum(1 for s in agent_statuses.values() if s != "success")
    total_count = len(agent_statuses)
    if failed_count == total_count and total_count > 0:
        return "failed"
    if failed_count > 0:
        return "degraded"
    return "completed"


def update_state_with_results(
    state: dict[str, Any],
    stage_name: str,
    synthesis_result: Any,
    agent_outputs_dict: dict[str, Any],
    parallel_result: dict[str, Any],
    aggregate_metrics: dict[str, Any],
    structured: dict[str, Any] | None = None,
) -> None:
    """Update workflow state with parallel execution results in two-compartment format."""
    agent_statuses = parallel_result.get(StateKeys.AGENT_STATUSES, {})
    stage_status = _compute_stage_status(agent_statuses)
    raw_dict: dict[str, Any] = {
        StateKeys.DECISION: synthesis_result.decision,
        StateKeys.OUTPUT: synthesis_result.decision,
        StateKeys.AGENT_OUTPUTS: agent_outputs_dict,
        StateKeys.AGENT_STATUSES: agent_statuses,
        StateKeys.AGENT_METRICS: parallel_result.get(StateKeys.AGENT_METRICS, {}),
        StateKeys.AGGREGATE_METRICS: aggregate_metrics,
        StateKeys.STAGE_STATUS: stage_status,
        StateKeys.SYNTHESIS: {
            StateKeys.METHOD: synthesis_result.method,
            StateKeys.CONFIDENCE: synthesis_result.confidence,
            StateKeys.VOTES: synthesis_result.votes,
            StateKeys.CONFLICTS: len(synthesis_result.conflicts),
        },
    }

    stage_entry: dict[str, Any] = {
        "structured": structured or {},
        "raw": dict(raw_dict),
        **raw_dict,
    }
    context_meta = state.get("_context_meta")
    if context_meta is not None:
        stage_entry["_context_meta"] = context_meta
    state[StateKeys.STAGE_OUTPUTS][stage_name] = stage_entry
    state[StateKeys.CURRENT_STAGE] = stage_name

    _emit_synthesis_event(
        state,
        stage_name,
        synthesis_result,
        agent_outputs_dict,
        parallel_result,
        aggregate_metrics,
    )
    _emit_output_lineage(
        state, stage_name, agent_outputs_dict, parallel_result, synthesis_result
    )
    _emit_parallel_cost_summary(state, stage_name, parallel_result)
