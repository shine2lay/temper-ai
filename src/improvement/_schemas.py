"""Pydantic models for optimization configuration and results."""

from __future__ import annotations

import dataclasses
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from src.improvement.constants import (
    DEFAULT_MAX_ITERATIONS,
    DEFAULT_RUNS,
    DEFAULT_TIMEOUT_SECONDS,
    MAX_SCORE,
    MIN_SCORE,
)


class CheckConfig(BaseModel):
    """A single check within a criteria evaluator."""

    name: str
    method: Literal["programmatic", "llm"] = "programmatic"
    command: Optional[str] = None
    prompt: Optional[str] = None
    timeout: int = DEFAULT_TIMEOUT_SECONDS


class EvaluatorConfig(BaseModel):
    """Configuration for an evaluator instance."""

    type: Literal["criteria", "comparative", "scored", "human"] = "criteria"
    checks: List[CheckConfig] = Field(default_factory=list)
    prompt: Optional[str] = None
    rubric: Optional[str] = None
    model: Optional[str] = None


class PipelineStepConfig(BaseModel):
    """A single step in the optimization pipeline."""

    optimizer: Literal[
        "refinement", "selection", "tuning"
    ] = "refinement"
    evaluator: str
    max_iterations: int = DEFAULT_MAX_ITERATIONS
    runs: int = DEFAULT_RUNS
    strategies: List[Dict[str, Any]] = Field(default_factory=list)


class OptimizationConfig(BaseModel):
    """Top-level optimization configuration."""

    evaluators: Dict[str, EvaluatorConfig] = Field(default_factory=dict)
    pipeline: List[PipelineStepConfig] = Field(default_factory=list)
    enabled: bool = True


@dataclasses.dataclass
class EvaluationResult:
    """Result of evaluating a single output."""

    passed: bool
    score: float = MAX_SCORE
    details: Dict[str, Any] = dataclasses.field(default_factory=dict)

    def __post_init__(self) -> None:
        self.score = max(MIN_SCORE, min(MAX_SCORE, self.score))


@dataclasses.dataclass
class OptimizationResult:
    """Result of an optimization pipeline run."""

    output: Dict[str, Any]
    score: float = MAX_SCORE
    iterations: int = 0
    improved: bool = False
    details: Dict[str, Any] = dataclasses.field(default_factory=dict)

    def __post_init__(self) -> None:
        self.score = max(MIN_SCORE, min(MAX_SCORE, self.score))
