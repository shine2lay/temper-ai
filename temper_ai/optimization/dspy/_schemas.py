"""Schemas for DSPy prompt optimization."""

from typing import Any, Literal

from pydantic import BaseModel, Field

from temper_ai.optimization.dspy.constants import (
    DEFAULT_LOOKBACK_HOURS,
    DEFAULT_MAX_DEMOS,
    DEFAULT_MIN_QUALITY_SCORE,
    DEFAULT_MIN_TRAINING_EXAMPLES,
    DEFAULT_NUM_THREADS,
    DEFAULT_OPTIMIZER,
    DEFAULT_PROGRAM_STORE_DIR,
    DEFAULT_TRAINING_METRIC,
)


class PromptOptimizationConfig(BaseModel):
    """Configuration for DSPy prompt optimization on an agent."""

    enabled: bool = False
    optimizer: str = DEFAULT_OPTIMIZER
    module_type: str = "predict"
    input_fields: list[str] = Field(default_factory=list)
    output_fields: list[str] = Field(
        default_factory=lambda: ["output"],
    )
    min_training_examples: int = Field(
        default=DEFAULT_MIN_TRAINING_EXAMPLES,
        gt=0,
    )
    min_quality_score: float = Field(
        default=DEFAULT_MIN_QUALITY_SCORE,
        ge=0.0,
        le=1.0,
    )
    training_metric: str = DEFAULT_TRAINING_METRIC
    lookback_hours: int = Field(default=DEFAULT_LOOKBACK_HOURS, gt=0)
    max_demos: int = Field(default=DEFAULT_MAX_DEMOS, gt=0)
    num_threads: int = Field(default=DEFAULT_NUM_THREADS, gt=0)
    program_store_dir: str = DEFAULT_PROGRAM_STORE_DIR
    auto_compile: bool = False
    optimizer_params: dict[str, Any] | None = None
    metric_params: dict[str, Any] | None = None
    module_params: dict[str, Any] | None = None
    signature_style: Literal["string", "class"] = "string"
    field_descriptions: dict[str, str] | None = None


class TrainingExample(BaseModel):
    """A single training example extracted from execution history."""

    input_text: str
    output_text: str
    metric_score: float = Field(ge=0.0, le=1.0)
    agent_name: str
    prompt_template_hash: str | None = None


class CompilationResult(BaseModel):
    """Result of a DSPy compilation run."""

    program_id: str
    agent_name: str
    optimizer_type: str
    train_score: float | None = None
    val_score: float | None = None
    num_examples: int = 0
    num_demos: int = 0
    program_data: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, str] = Field(default_factory=dict)
