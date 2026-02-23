"""Sequential agent retry and error handling logic.

Contains:
- Transient error classification
- Exponential backoff retry
- Error handling policy dispatch
- Retry observability events

Extracted from _sequential_helpers.py to reduce file size.
"""

import logging
from typing import TYPE_CHECKING, Any

from temper_ai.observability.resilience_events import (
    RETRY_OUTCOME_EXHAUSTED,
    RETRY_OUTCOME_FAILED,
    RETRY_OUTCOME_SUCCESS,
    RetryEventData,
    emit_retry_event,
)
from temper_ai.shared.constants.durations import SECONDS_PER_MINUTE
from temper_ai.shared.constants.retries import (
    DEFAULT_BACKOFF_MULTIPLIER,
    MIN_BACKOFF_SECONDS,
)
from temper_ai.shared.utils.exceptions import (
    ErrorCode,
)
from temper_ai.stage.executors.state_keys import StateKeys

if TYPE_CHECKING:
    from temper_ai.stage.executors._sequential_helpers import (
        AgentExecutionContext,
        AgentResultAccumulators,
    )

# Agent retry backoff constants
MAX_RETRY_BACKOFF_DIVISOR = (
    2  # Divide max time by this to get max retry delay (e.g., 60s / 2 = 30s max delay)
)

logger = logging.getLogger(__name__)

# Error types classified as transient (worth retrying)
_TRANSIENT_ERROR_TYPES: frozenset[str] = frozenset(
    {
        ErrorCode.LLM_CONNECTION_ERROR.value,
        ErrorCode.LLM_TIMEOUT.value,
        ErrorCode.LLM_RATE_LIMIT.value,
        ErrorCode.SYSTEM_TIMEOUT.value,
        ErrorCode.SYSTEM_RESOURCE_ERROR.value,
        ErrorCode.TOOL_TIMEOUT.value,
        ErrorCode.AGENT_TIMEOUT.value,
        ErrorCode.WORKFLOW_TIMEOUT.value,
    }
)


def is_transient_error(error_type: str) -> bool:
    """Classify an error type as transient (retriable) vs permanent."""
    return error_type in _TRANSIENT_ERROR_TYPES


def _execute_retry_attempt(
    ctx: "AgentExecutionContext",
    agent_ref: Any,
    prior_agent_outputs: dict[str, Any],
    agent_name: str,
    attempt: int,
    max_retries: int,
) -> tuple[dict[str, Any], bool]:
    """Execute a single retry attempt. Returns (result, should_stop)."""
    from temper_ai.stage.executors._sequential_helpers import execute_agent

    last_result = execute_agent(
        ctx=ctx,
        agent_ref=agent_ref,
        prior_agent_outputs=prior_agent_outputs,
    )

    if last_result[StateKeys.STATUS] == "success":
        logger.info(
            "Agent %s succeeded on retry attempt %d/%d in stage %s",
            agent_name,
            attempt,
            max_retries,
            ctx.stage_name,
        )
        last_result[StateKeys.METRICS][StateKeys.RETRIES] = attempt
        return last_result, True

    retry_error_type = last_result[StateKeys.OUTPUT_DATA].get(StateKeys.ERROR_TYPE, "")
    if not is_transient_error(retry_error_type):
        logger.warning(
            "Agent %s retry %d/%d hit permanent error type '%s' in stage %s, "
            "stopping retries: %s",
            agent_name,
            attempt,
            max_retries,
            retry_error_type,
            ctx.stage_name,
            last_result[StateKeys.OUTPUT_DATA].get(StateKeys.ERROR, ""),
        )
        last_result[StateKeys.METRICS][StateKeys.RETRIES] = attempt
        return last_result, True

    return last_result, False


def retry_agent_with_backoff(
    ctx: "AgentExecutionContext",
    agent_ref: Any,
    prior_agent_outputs: dict[str, Any],
    max_retries: int,
    agent_name: str,
) -> dict[str, Any]:
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
    last_result: dict[str, Any] = {}

    for attempt in range(1, max_retries + 1):
        delay = min(
            base_delay * (DEFAULT_BACKOFF_MULTIPLIER ** (attempt - 1)),
            SECONDS_PER_MINUTE / MAX_RETRY_BACKOFF_DIVISOR,
        )
        logger.info(
            "Retrying agent %s in stage %s (attempt %d/%d, backoff %.1fs)",
            agent_name,
            ctx.stage_name,
            attempt,
            max_retries,
            delay,
        )

        if ctx.executor.shutdown_event.wait(
            timeout=delay
        ):  # intentional wait for backoff
            raise KeyboardInterrupt("Executor shutdown requested")

        last_result, should_stop = _execute_retry_attempt(
            ctx,
            agent_ref,
            prior_agent_outputs,
            agent_name,
            attempt,
            max_retries,
        )
        if should_stop:
            _emit_retry_outcome(
                ctx, last_result, agent_name, attempt, max_retries, delay
            )
            return last_result

    logger.warning(
        "Agent %s exhausted all %d retries in stage %s",
        agent_name,
        max_retries,
        ctx.stage_name,
    )
    if last_result:
        last_result[StateKeys.METRICS][StateKeys.RETRIES] = max_retries
    _emit_retry_exhausted(ctx, last_result, agent_name, max_retries)
    return last_result


def _emit_retry_outcome(
    ctx: "AgentExecutionContext",
    result: dict[str, Any],
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
    ctx: "AgentExecutionContext",
    result: dict[str, Any],
    agent_name: str,
    max_retries: int,
) -> None:
    """Emit a retry-exhausted event after all attempts failed."""
    error_type = (
        result.get(StateKeys.OUTPUT_DATA, {}).get(StateKeys.ERROR_TYPE)
        if result
        else None
    )

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


def _handle_retry_policy(
    agent_name: str,
    agent_result: dict[str, Any],
    error_handling: Any,
    ctx: "AgentExecutionContext",
    agent_ref: Any,
    accum: "AgentResultAccumulators",
) -> tuple[str, dict[str, Any]]:
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
            agent_name,
            error_type,
            ctx.stage_name,
            agent_result[StateKeys.OUTPUT_DATA].get(StateKeys.ERROR, ""),
        )
    else:
        logger.warning(
            "Agent %s failed in stage %s (policy: retry_agent, " "max_retries=0): %s",
            agent_name,
            ctx.stage_name,
            agent_result[StateKeys.OUTPUT_DATA].get(StateKeys.ERROR, ""),
        )
    return "store", agent_result


def _handle_agent_failure(
    agent_name: str,
    agent_result: dict[str, Any],
    error_handling: Any,
    ctx: "AgentExecutionContext",
    agent_ref: Any,
    accum: "AgentResultAccumulators",
) -> tuple[str, dict[str, Any]]:
    """Handle agent failure based on error_handling policy.

    Returns:
        Tuple of (action, result_to_store)
        action: "break" | "continue" | "store"
    """
    policy = error_handling.on_agent_failure

    if policy == "halt_stage":
        logger.warning(
            "Agent %s failed in stage %s (policy: halt_stage), stopping execution: %s",
            agent_name,
            ctx.stage_name,
            agent_result[StateKeys.OUTPUT_DATA].get(StateKeys.ERROR, ""),
        )
        return "break", agent_result

    if policy == "skip_agent":
        logger.warning(
            "Agent %s failed in stage %s (policy: skip_agent), skipping: %s",
            agent_name,
            ctx.stage_name,
            agent_result[StateKeys.OUTPUT_DATA].get(StateKeys.ERROR, ""),
        )
        return "continue", agent_result

    if policy == "retry_agent":
        return _handle_retry_policy(
            agent_name,
            agent_result,
            error_handling,
            ctx,
            agent_ref,
            accum,
        )

    # continue_with_remaining
    logger.warning(
        "Agent %s failed in stage %s (policy: continue_with_remaining), continuing: %s",
        agent_name,
        ctx.stage_name,
        agent_result[StateKeys.OUTPUT_DATA].get(StateKeys.ERROR, ""),
    )
    return "store", agent_result


def _store_failure_result(
    result_to_store: dict[str, Any],
    agent_statuses: dict[str, Any],
    agent_outputs: dict[str, Any],
    agent_metrics: dict[str, Any],
) -> None:
    """Store agent result (from retry or original failure) into output dicts."""
    name = result_to_store[StateKeys.AGENT_NAME]
    if result_to_store[StateKeys.STATUS] == "success":
        agent_statuses[name] = "success"
    else:
        agent_statuses[name] = {
            StateKeys.STATUS: "failed",
            StateKeys.ERROR: result_to_store[StateKeys.OUTPUT_DATA].get(
                StateKeys.ERROR, ""
            ),
            StateKeys.ERROR_TYPE: result_to_store[StateKeys.OUTPUT_DATA].get(
                StateKeys.ERROR_TYPE, ""
            ),
        }
    agent_outputs[name] = result_to_store[StateKeys.OUTPUT_DATA]
    agent_metrics[name] = result_to_store[StateKeys.METRICS]


def _process_agent_failure(
    agent_name: str,
    agent_result: dict[str, Any],
    error_handling: Any,
    ctx: "AgentExecutionContext",
    agent_ref: Any,
    accum: "AgentResultAccumulators",
) -> str | None:
    """Process a failed agent result. Returns 'break'/'continue' or None to store and continue."""
    accum.statuses[agent_name] = {
        StateKeys.STATUS: "failed",
        StateKeys.ERROR: agent_result[StateKeys.OUTPUT_DATA].get(StateKeys.ERROR, ""),
        StateKeys.ERROR_TYPE: agent_result[StateKeys.OUTPUT_DATA].get(
            StateKeys.ERROR_TYPE, ""
        ),
    }

    action, result_to_store = _handle_agent_failure(
        agent_name, agent_result, error_handling, ctx, agent_ref, accum
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
