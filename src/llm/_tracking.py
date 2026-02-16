"""Observer tracking and safety validation for LLMService.

Tracks successful/failed LLM calls via the observer and validates
LLM calls against the policy engine.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from src.llm.constants import FALLBACK_UNKNOWN_VALUE
from src.shared.utils.exceptions import ConfigValidationError, sanitize_error_message

logger = logging.getLogger(__name__)


def track_call(
    observer: Any,
    inference_config: Any,
    prompt: str,
    llm_response: Any,
    cost: float,
) -> None:
    """Track a successful LLM call via the observer."""
    if observer is None:
        return
    observer.track_llm_call(
        provider=inference_config.provider,
        model=inference_config.model,
        prompt=prompt,
        response=llm_response.content,
        prompt_tokens=llm_response.prompt_tokens or 0,
        completion_tokens=llm_response.completion_tokens or 0,
        latency_ms=int(llm_response.latency_ms) if hasattr(llm_response, 'latency_ms') and llm_response.latency_ms else 0,
        estimated_cost_usd=cost,
        temperature=inference_config.temperature,
        max_tokens=inference_config.max_tokens,
        status="success",
    )


def track_failed_call(
    observer: Any,
    inference_config: Any,
    prompt: str,
    error: Exception,
    attempt: int,
    max_attempts: int,
) -> None:
    """Track a failed LLM call via the observer."""
    if observer is None:
        return
    error_msg = sanitize_error_message(str(error))
    observer.track_llm_call(
        provider=inference_config.provider,
        model=inference_config.model,
        prompt=prompt,
        response="",
        prompt_tokens=0,
        completion_tokens=0,
        latency_ms=0,
        estimated_cost_usd=0.0,
        temperature=inference_config.temperature,
        max_tokens=inference_config.max_tokens,
        status="failed",
        error_message=f"[attempt {attempt}/{max_attempts}] {error_msg}",
    )


def track_llm_iteration(
    observer: Any,
    iteration_data: Any,
) -> None:
    """Emit an LLM iteration event via the observer.

    Falls back to logging if the observer does not support the method.

    Args:
        observer: AgentObserver or tracker instance (may be None).
        iteration_data: LLMIterationEventData instance.
    """
    if observer is None:
        return
    track_fn = getattr(observer, "track_llm_iteration", None)
    if track_fn is not None:
        try:
            track_fn(iteration_data)
        except (AttributeError, TypeError, RuntimeError) as exc:
            logger.debug("Failed to emit LLM iteration event: %s", exc)
    else:
        logger.debug(
            "Observer does not support track_llm_iteration; iteration=%s",
            getattr(iteration_data, "iteration_number", "?"),
        )


def validate_safety(
    tool_executor: Any,
    inference_config: Any,
    prompt: str,
) -> Optional[str]:
    """Run safety validation for an LLM call. Returns error message or None."""
    if tool_executor is None:
        return None
    if getattr(tool_executor, 'policy_engine', None) is None:
        return None

    try:
        violation_msg = _validate_with_policy(tool_executor, inference_config, prompt)
        if violation_msg:
            logger.warning("LLM call blocked by safety policy: %s", violation_msg)
            return f"LLM call blocked by safety policy: {violation_msg}"
    except (ConfigValidationError, ValueError, RuntimeError) as e:
        logger.error(
            "LLM call safety validation failed (fail-closed): %s",
            e, exc_info=True,
        )
        return f"Safety validation error (fail-closed): {sanitize_error_message(str(e))}"
    return None


def _validate_with_policy(
    tool_executor: Any,
    inference_config: Any,
    prompt: str,
) -> Optional[str]:
    """Validate LLM call with policy engine. Returns violation message or None."""
    from src.safety.action_policy_engine import PolicyExecutionContext

    policy_context = PolicyExecutionContext(
        agent_id="unknown",
        workflow_id=FALLBACK_UNKNOWN_VALUE,
        stage_id=FALLBACK_UNKNOWN_VALUE,
        action_type="llm_call",
        action_data={"model": inference_config.model},
    )

    validation_result = tool_executor.policy_engine.validate_action_sync(
        action={"type": "llm_call", "model": inference_config.model, "prompt_length": len(prompt)},
        context=policy_context,
    )

    if not validation_result.allowed:
        return "; ".join(v.message for v in validation_result.violations)
    return None
