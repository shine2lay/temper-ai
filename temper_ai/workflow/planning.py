"""Workflow planning pass — pre-execution LLM planning (R0.8).

Generates a high-level plan before workflow execution begins, which is
then injected into agent prompts via ``_inject_input_context()``.
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class PlanningConfig(BaseModel):
    """Configuration for workflow planning pass."""

    enabled: bool = False
    provider: Literal["ollama", "vllm", "openai", "anthropic", "custom"] = "openai"
    model: str = "gpt-4o-mini"
    base_url: str | None = None
    api_key_ref: str | None = None
    temperature: float = Field(default=0.3, ge=0.0, le=2.0)  # scanner: skip-magic
    max_tokens: int = Field(default=2048, gt=0)


_PLAN_PROMPT_TEMPLATE = (
    "You are a workflow planner. Given the following workflow description "
    "and stages, produce a concise execution plan.\n\n"
    "Workflow: {workflow_name}\n"
    "Description: {workflow_description}\n"
    "Stages: {stage_names}\n"
    "User Input: {user_input}\n\n"
    "Produce a clear step-by-step plan for executing this workflow."
)


def build_planning_prompt(
    workflow_config: dict[str, Any],
    inputs: dict[str, Any],
) -> str:
    """Build the planning prompt from workflow config and inputs."""
    wf = workflow_config.get("workflow", {})
    stage_names = ", ".join(s.get("name", "?") for s in wf.get("stages", []))
    user_input_str = ", ".join(
        f"{k}: {v}" for k, v in inputs.items() if isinstance(v, (str, int, float, bool))
    )
    return _PLAN_PROMPT_TEMPLATE.format(
        workflow_name=wf.get("name", "unknown"),
        workflow_description=wf.get("description", ""),
        stage_names=stage_names,
        user_input=user_input_str or "(none)",
    )


def generate_workflow_plan(
    workflow_config: dict[str, Any],
    inputs: dict[str, Any],
    planning_config: PlanningConfig,
) -> str | None:
    """Generate a workflow plan using an LLM.

    Returns the plan text, or None if planning fails.
    """
    if not planning_config.enabled:
        return None

    prompt = build_planning_prompt(workflow_config, inputs)

    try:
        from temper_ai.agent.llm import create_llm_provider
        from temper_ai.storage.schemas.agent_config import InferenceConfig

        inference_cfg = InferenceConfig(
            provider=planning_config.provider,
            model=planning_config.model,
            base_url=planning_config.base_url,
            api_key_ref=planning_config.api_key_ref,
        )
        llm = create_llm_provider(inference_cfg)
        response = llm.complete(
            prompt,
            temperature=planning_config.temperature,
            max_tokens=planning_config.max_tokens,
        )
        plan_text = str(response.content).strip()
        logger.info(
            "Workflow plan generated (%d chars)",
            len(plan_text),
        )
        return plan_text
    except (
        ImportError,
        ValueError,
        RuntimeError,
        ConnectionError,
        TimeoutError,
    ) as exc:
        logger.warning("Workflow planning failed: %s", exc)
        return None
