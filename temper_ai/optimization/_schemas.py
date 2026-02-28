"""Pydantic models for optimization configuration and results."""

from __future__ import annotations

import dataclasses
from typing import Any, Literal

from pydantic import BaseModel, Field

from temper_ai.optimization.engine_constants import (
    DEFAULT_MAX_ITERATIONS,
    DEFAULT_OPTIMIZATION_TIMEOUT_SECONDS,
    DEFAULT_RUNS,
    MAX_SCORE,
    MIN_SCORE,
)


class CheckConfig(BaseModel):
    """A single check within a criteria evaluator."""

    name: str
    method: Literal["programmatic", "llm"] = "programmatic"
    command: str | None = None
    prompt: str | None = None
    timeout: int = DEFAULT_OPTIMIZATION_TIMEOUT_SECONDS


class EvaluatorConfig(BaseModel):
    """Configuration for an evaluator instance."""

    type: Literal["criteria", "comparative", "scored", "human"] = "criteria"
    checks: list[CheckConfig] = Field(default_factory=list)
    prompt: str | None = None
    rubric: str | None = None
    model: str | None = None


class PipelineStepConfig(BaseModel):
    """A single step in the optimization pipeline."""

    optimizer: Literal["refinement", "selection", "tuning", "prompt"] = "refinement"
    evaluator: str
    max_iterations: int = DEFAULT_MAX_ITERATIONS
    runs: int = DEFAULT_RUNS
    strategies: list[dict[str, Any]] = Field(default_factory=list)
    reads: str | None = None  # evaluation_name this optimizer reads scores from
    agents: list[str] = Field(default_factory=list)  # agents this step targets


class OptimizationConfig(BaseModel):
    """Top-level optimization configuration."""

    evaluators: dict[str, EvaluatorConfig] = Field(default_factory=dict)
    pipeline: list[PipelineStepConfig] = Field(default_factory=list)
    enabled: bool = True

    # Per-agent evaluation definitions.
    # Typed as Dict[str, Any] (not Dict[str, AgentEvaluationConfig]) to avoid
    # circular import: _evaluation_schemas imports CheckConfig from this module.
    # Pydantic validation happens in EvaluationMapping at dispatch-creation time.
    evaluations: dict[str, Any] = Field(default_factory=dict)
    agent_evaluations: dict[str, list[str]] = Field(default_factory=dict)


@dataclasses.dataclass
class EvaluationResult:
    """Result of evaluating a single output."""

    passed: bool
    score: float = MAX_SCORE
    details: dict[str, Any] = dataclasses.field(default_factory=dict)

    def __post_init__(self) -> None:
        self.score = max(MIN_SCORE, min(MAX_SCORE, self.score))


@dataclasses.dataclass
class OptimizationResult:
    """Result of an optimization pipeline run."""

    output: dict[str, Any]
    score: float = MAX_SCORE
    iterations: int = 0
    improved: bool = False
    details: dict[str, Any] = dataclasses.field(default_factory=dict)
    experiment_id: str | None = None
    experiment_results: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        self.score = max(MIN_SCORE, min(MAX_SCORE, self.score))
