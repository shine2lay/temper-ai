"""Agent reasoning/planning pass (R0.7).

Performs an extra LLM call before the main execution to generate a
step-by-step plan, which is then injected into the main prompt.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from temper_ai.llm.service import LLMService
    from temper_ai.storage.schemas.agent_config import ReasoningConfig

logger = logging.getLogger(__name__)

_DEFAULT_PLANNING_TEMPLATE = (
    "Given the following task, create a step-by-step plan:\n\n" "{prompt}\n\n" "Plan:"
)

_PLAN_SECTION_START = "\n\n--- Reasoning Plan ---\n"
_PLAN_SECTION_END = "\n--- End Plan ---\n"

_DEFAULT_PLANNING_TEMPERATURE = 0.7


def build_planning_prompt(original_prompt: str, config: ReasoningConfig) -> str:
    """Build the planning prompt from config or default template."""
    if config.planning_prompt:
        return config.planning_prompt.replace("{prompt}", original_prompt)
    return _DEFAULT_PLANNING_TEMPLATE.format(prompt=original_prompt)


def run_planning_pass(
    llm_service: LLMService,
    original_prompt: str,
    config: ReasoningConfig,
) -> str | None:
    """Call LLM with planning prompt and return plan text.

    Returns None on failure so the caller can fall back to the
    original prompt without a plan.
    """
    planning_prompt = build_planning_prompt(original_prompt, config)
    temperature = config.temperature or _DEFAULT_PLANNING_TEMPERATURE
    try:
        response = llm_service.llm.complete(
            planning_prompt,
            max_tokens=config.max_planning_tokens,
            temperature=temperature,
        )
        plan = getattr(response, "content", None) or ""
        return plan.strip() if plan.strip() else None
    except (ValueError, RuntimeError, OSError, TypeError) as exc:
        logger.warning("Reasoning planning pass failed: %s", exc)
        return None


def inject_plan_into_prompt(
    original_prompt: str,
    plan: str,
    inject_as: str,
) -> str:
    """Inject the generated plan into the original prompt."""
    if inject_as == "system_prefix":
        return plan + "\n\n" + original_prompt
    # Default: context_section
    return original_prompt + _PLAN_SECTION_START + plan + _PLAN_SECTION_END
