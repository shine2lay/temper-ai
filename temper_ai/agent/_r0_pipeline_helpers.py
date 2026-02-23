"""R0 pipeline helpers extracted from StandardAgent to stay under 20-method limit.

Free functions that implement reasoning, context management, structured output
validation, and guardrail features for the agent execution pipeline.
"""

from __future__ import annotations

from typing import Any


def apply_reasoning(llm_service: Any, config: Any, prompt: str) -> str:
    """Run a planning pass and inject the plan into the prompt (R0.7)."""
    from temper_ai.agent.reasoning import inject_plan_into_prompt, run_planning_pass

    cfg = config.agent.reasoning
    plan = run_planning_pass(llm_service, prompt, cfg)
    if plan:
        return inject_plan_into_prompt(prompt, plan, cfg.inject_as)
    return prompt


def apply_context_management(config: Any, prompt: str) -> str:
    """Trim the prompt to fit within the model context window (R0.5)."""
    from temper_ai.llm.context_window import DEFAULT_MODEL_CONTEXT, trim_to_budget

    cfg = config.agent.context_management
    max_tokens = cfg.max_context_tokens or DEFAULT_MODEL_CONTEXT
    return trim_to_budget(
        prompt,
        max_tokens,
        cfg.reserved_output_tokens,
        cfg.strategy,
        cfg.token_counter,
    )


def validate_and_retry_output(
    llm_service: Any,
    config: Any,
    result: Any,
    prompt: str,
    kwargs: dict[str, Any],
) -> Any:
    """Validate output against JSON schema, retrying on failure (R0.1)."""
    from temper_ai.llm.output_validation import (
        build_retry_prompt_with_error,
        validate_output_against_schema,
    )

    cfg = config.agent.output_schema
    if cfg is None or cfg.json_schema is None:
        return result

    for _attempt in range(cfg.max_retries):
        valid, error_msg = validate_output_against_schema(
            result.output, cfg.json_schema
        )
        if valid:
            return result
        retry_prompt = build_retry_prompt_with_error(
            prompt,
            result.output,
            error_msg or "",
            cfg.json_schema,
        )
        retry_kwargs = {**kwargs, "prompt": retry_prompt}
        result = llm_service.run(**retry_kwargs)
    return result


async def avalidate_and_retry_output(
    llm_service: Any,
    config: Any,
    result: Any,
    prompt: str,
    kwargs: dict[str, Any],
) -> Any:
    """Async: validate output against JSON schema, retrying on failure (R0.1)."""
    from temper_ai.llm.output_validation import (
        build_retry_prompt_with_error,
        validate_output_against_schema,
    )

    cfg = config.agent.output_schema
    if cfg is None or cfg.json_schema is None:
        return result

    for _attempt in range(cfg.max_retries):
        valid, error_msg = validate_output_against_schema(
            result.output, cfg.json_schema
        )
        if valid:
            return result
        retry_prompt = build_retry_prompt_with_error(
            prompt,
            result.output,
            error_msg or "",
            cfg.json_schema,
        )
        retry_kwargs = {**kwargs, "prompt": retry_prompt}
        result = await llm_service.arun(**retry_kwargs)
    return result


def apply_guardrails(
    llm_service: Any,
    config: Any,
    result: Any,
    prompt: str,
    kwargs: dict[str, Any],
) -> Any:
    """Run guardrail checks and retry with feedback on blocking failures (R0.2)."""
    from temper_ai.agent.guardrails import (
        build_feedback_injection,
        has_blocking_failures,
        run_guardrail_checks,
    )

    cfg = config.agent.output_guardrails
    for _attempt in range(cfg.max_retries):
        results = run_guardrail_checks(result.output, cfg.checks)
        if not has_blocking_failures(results):
            return result
        if cfg.inject_feedback:
            failures = [r for r in results if not r.passed]
            feedback = build_feedback_injection(failures)
            retry_prompt = prompt + "\n\n" + feedback
            retry_kwargs = {**kwargs, "prompt": retry_prompt}
            result = llm_service.run(**retry_kwargs)
        else:
            break
    return result


async def aapply_guardrails(
    llm_service: Any,
    config: Any,
    result: Any,
    prompt: str,
    kwargs: dict[str, Any],
) -> Any:
    """Async: run guardrail checks and retry with feedback (R0.2)."""
    from temper_ai.agent.guardrails import (
        build_feedback_injection,
        has_blocking_failures,
        run_guardrail_checks,
    )

    cfg = config.agent.output_guardrails
    for _attempt in range(cfg.max_retries):
        results = run_guardrail_checks(result.output, cfg.checks)
        if not has_blocking_failures(results):
            return result
        if cfg.inject_feedback:
            failures = [r for r in results if not r.passed]
            feedback = build_feedback_injection(failures)
            retry_prompt = prompt + "\n\n" + feedback
            retry_kwargs = {**kwargs, "prompt": retry_prompt}
            result = await llm_service.arun(**retry_kwargs)
        else:
            break
    return result
