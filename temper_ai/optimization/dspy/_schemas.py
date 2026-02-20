"""Schemas for DSPy prompt optimization."""

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from temper_ai.optimization.dspy.constants import (
    DEFAULT_LOOKBACK_HOURS,
    DEFAULT_MAX_DEMOS,
    DEFAULT_MIN_QUALITY_SCORE,
    DEFAULT_MIN_TRAINING_EXAMPLES,
    DEFAULT_NUM_THREADS,
    DEFAULT_OPTIMIZER,
    DEFAULT_PROGRAM_STORE_DIR,
)


class PromptOptimizationConfig(BaseModel):
    """Configuration for DSPy prompt optimization on an agent."""

    enabled: bool = False
    optimizer: Literal["bootstrap", "mipro"] = DEFAULT_OPTIMIZER
    module_type: Literal["predict", "chain_of_thought"] = "predict"
    input_fields: List[str] = Field(default_factory=list)
    output_fields: List[str] = Field(
        default_factory=lambda: ["output"],
    )
    min_training_examples: int = Field(
        default=DEFAULT_MIN_TRAINING_EXAMPLES, gt=0,
    )
    min_quality_score: float = Field(
        default=DEFAULT_MIN_QUALITY_SCORE, ge=0.0, le=1.0,
    )
    training_metric: Optional[str] = None
    lookback_hours: int = Field(default=DEFAULT_LOOKBACK_HOURS, gt=0)
    max_demos: int = Field(default=DEFAULT_MAX_DEMOS, gt=0)
    num_threads: int = Field(default=DEFAULT_NUM_THREADS, gt=0)
    program_store_dir: str = DEFAULT_PROGRAM_STORE_DIR
    auto_compile: bool = False


class TrainingExample(BaseModel):
    """A single training example extracted from execution history."""

    input_text: str
    output_text: str
    metric_score: float = Field(ge=0.0, le=1.0)
    agent_name: str
    prompt_template_hash: Optional[str] = None


class CompilationResult(BaseModel):
    """Result of a DSPy compilation run."""

    program_id: str
    agent_name: str
    optimizer_type: str
    train_score: Optional[float] = None
    val_score: Optional[float] = None
    num_examples: int = 0
    num_demos: int = 0
    program_data: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, str] = Field(default_factory=dict)
