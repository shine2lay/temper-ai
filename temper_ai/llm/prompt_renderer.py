"""Renders agent prompts from Jinja2 templates in YAML config.

Design principles (from cross-framework research):
- Developer owns the prompt (12-Factor Agents, Factor 2)
- No hidden injection (anti-pattern: CrewAI's invisible formatting instructions)
- Template variables are explicit — developer places them where they want
- Token budget is a guardrail, not a complex section system
- Matches smolagents (YAML Jinja2), OpenAI SDK (string/callable), Pydantic AI (decorators)
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from jinja2 import BaseLoader, Environment, TemplateSyntaxError, Undefined

logger = logging.getLogger(__name__)


class PromptBudgetError(Exception):
    """Raised when prompt exceeds token budget even after trimming."""


class PromptRenderer:
    """Renders agent prompts into messages lists for LLM providers.

    system_prompt → {"role": "system", ...} (plain string, no templating)
    task_template → {"role": "user", ...}   (Jinja2 with all variables)
    """

    def __init__(
        self,
        token_counter: Callable[[list[dict[str, str]]], int] | None = None,
    ):
        self.env = Environment(loader=BaseLoader(), undefined=Undefined)
        self.token_counter = token_counter

    def render(
        self,
        agent_config: dict[str, Any],
        input_data: dict[str, Any],
        memories: list[str] | None = None,
        strategy_context: str | None = None,
        token_budget: int | None = None,
    ) -> list[dict[str, str]]:
        """Render agent prompt into messages list.

        Available template variables:
        - All keys from input_data (e.g., {{ task }}, {{ code }})
        - {{ memories }} — list of recalled memory strings (empty list if none)
        - {{ other_agents }} — other agents' outputs for multi-agent context

        Returns: [{"role": "system", ...}, {"role": "user", ...}]
        """
        system = agent_config.get("system_prompt", "You are a helpful assistant.")
        task_template = agent_config.get("task_template", "{{ task }}")

        template_vars = {
            **_filter_safe_values(input_data),
            "memories": memories or [],
            "other_agents": strategy_context,
        }

        user_content = self._render_template(task_template, template_vars)
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user_content},
        ]

        if token_budget and self.token_counter:
            messages = self._enforce_budget(
                messages, token_budget, task_template, template_vars, system
            )

        return messages

    def _render_template(
        self, template_str: str, variables: dict[str, Any]
    ) -> str:
        """Render a Jinja2 template string with the given variables."""
        template = self.env.from_string(template_str)
        return template.render(**variables)

    def _enforce_budget(
        self,
        messages: list[dict[str, str]],
        budget: int,
        task_template: str,
        template_vars: dict[str, Any],
        system: str,
    ) -> list[dict[str, str]]:
        """Graceful degradation when prompt exceeds token budget.

        Trimming order (matches what matters least -> most):
        1. Drop memories (supplementary context, agent can work without them)
        2. Truncate input_data values (keep structure, trim long content)
        3. Raise PromptBudgetError (system_prompt + minimal input doesn't fit)
        """
        assert self.token_counter is not None

        token_count = self.token_counter(messages)
        if token_count <= budget:
            return messages

        # Step 1: Re-render without memories
        trimmed_vars = {**template_vars, "memories": []}
        user_content = self._render_template(task_template, trimmed_vars)
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user_content},
        ]
        if self.token_counter(messages) <= budget:
            logger.info("Dropped memories to fit token budget")
            return messages

        # Step 2: Truncate long input values
        for key, value in trimmed_vars.items():
            if isinstance(value, str) and len(value) > 1000:
                trimmed_vars[key] = value[:1000] + "\n... [truncated]"
        user_content = self._render_template(task_template, trimmed_vars)
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user_content},
        ]
        if self.token_counter(messages) <= budget:
            logger.info("Truncated long inputs to fit token budget")
            return messages

        # Step 3: Can't fit
        final_count = self.token_counter(messages)
        raise PromptBudgetError(
            f"Prompt exceeds token budget ({final_count} > {budget}) "
            f"even after trimming memories and truncating inputs. "
            f"Increase token_budget or reduce system_prompt/task_template size."
        )


def validate_prompt_config(
    agent_config: dict[str, Any],
    stage_config: dict[str, Any] | None = None,
) -> tuple[list[str], list[str]]:
    """Cross-check template variables against agent/stage config.

    Returns (warnings, errors).

    Runs at workflow load time — catches problems before anything executes.
    """
    warnings: list[str] = []
    errors: list[str] = []
    agent_name = agent_config.get("name", "<unnamed>")
    template = agent_config.get("task_template", "")

    # Memory validation
    has_memory = agent_config.get("memory", {}).get("enabled", False)
    uses_memories = "memories" in template

    if has_memory and not uses_memories:
        warnings.append(
            f"Agent '{agent_name}' has memory enabled but "
            f"task_template doesn't use '{{{{ memories }}}}' variable. "
            f"Memories will be recalled but not shown to the model."
        )
    if uses_memories and not has_memory:
        errors.append(
            f"Agent '{agent_name}' task_template references "
            f"'{{{{ memories }}}}' but memory is not enabled in config. "
            f"Enable memory or remove the variable from the template."
        )

    # Multi-agent context validation
    stage = stage_config or {}
    is_multi_agent = len(stage.get("agents", [])) > 1
    uses_other_agents = "other_agents" in template

    if is_multi_agent and not uses_other_agents:
        warnings.append(
            f"Agent '{agent_name}' runs in a multi-agent stage but "
            f"task_template doesn't use '{{{{ other_agents }}}}'. "
            f"Other agents' outputs won't be visible to this agent."
        )

    # Template syntax validation
    try:
        env = Environment(loader=BaseLoader())
        env.parse(template)
    except TemplateSyntaxError as e:
        errors.append(
            f"Agent '{agent_name}' task_template has syntax error: {e}"
        )

    return warnings, errors


def _filter_safe_values(data: dict[str, Any]) -> dict[str, Any]:
    """Filter input_data to only safe types for Jinja2 rendering.

    Allows: str, int, float, bool, list, dict, tuple, None
    Rejects: functions, objects, modules — prevents SSTI
    """
    safe_types = (str, int, float, bool, list, dict, tuple, type(None))
    return {k: v for k, v in data.items() if isinstance(v, safe_types)}
