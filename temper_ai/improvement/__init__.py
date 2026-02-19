"""Composable optimization engine for workflow outputs.

Evaluates and improves workflow outputs through configurable pipelines
of evaluators and optimizers.
"""

from temper_ai.improvement._schemas import (
    CheckConfig,
    EvaluationResult,
    EvaluatorConfig,
    OptimizationConfig,
    OptimizationResult,
    PipelineStepConfig,
)
from temper_ai.improvement.engine import OptimizationEngine
from temper_ai.improvement.protocols import EvaluatorProtocol, OptimizerProtocol
from temper_ai.improvement.registry import OptimizationRegistry

__all__ = [
    "CheckConfig",
    "EvaluationResult",
    "EvaluatorConfig",
    "EvaluatorProtocol",
    "OptimizationConfig",
    "OptimizationEngine",
    "OptimizationResult",
    "OptimizerProtocol",
    "PipelineStepConfig",
    "OptimizationRegistry",
]
