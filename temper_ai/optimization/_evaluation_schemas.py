"""Per-agent evaluation configuration schemas.

Defines evaluation types (criteria, scored, composite) and
agent-to-evaluation mapping for the optimization pipeline.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from temper_ai.optimization._schemas import CheckConfig


class AgentEvaluationConfig(BaseModel):
    """Per-agent evaluation definition.

    Supports three evaluation types:
    - criteria: pass/fail checks (programmatic + LLM)
    - scored: LLM-as-judge rubric (0-1 score)
    - composite: blend evaluation score with free metrics (cost, latency)
    """

    type: Literal["criteria", "scored", "composite"] = "scored"
    # criteria: pass/fail checks
    checks: list[CheckConfig] = Field(default_factory=list)
    # scored: LLM-as-judge rubric
    rubric: str | None = None
    prompt: str | None = None
    model: str | None = None
    # composite: blend evaluation + free metrics
    weights: dict[str, float] = Field(default_factory=dict)


# Key for fallback evaluations applied to unmapped agents
DEFAULT_EVALUATION_KEY = "_default"


class EvaluationMapping(BaseModel):
    """Maps evaluation names to agent names.

    Attributes:
        evaluations: Named evaluation definitions.
        agent_evaluations: Agent name -> list of evaluation names.
            Use ``_default`` key for evaluations applied to all unmapped agents.
    """

    evaluations: dict[str, AgentEvaluationConfig] = Field(default_factory=dict)
    agent_evaluations: dict[str, list[str]] = Field(default_factory=dict)
