"""Composable optimization engine for workflow outputs.

Evaluates and improves workflow outputs through configurable pipelines
of evaluators and optimizers.
"""

from src.improvement._schemas import (
    CheckConfig,
    EvaluationResult,
    EvaluatorConfig,
    OptimizationConfig,
    OptimizationResult,
    PipelineStepConfig,
)
from src.improvement.engine import OptimizationEngine
from src.improvement.protocols import EvaluatorProtocol, OptimizerProtocol
from src.improvement.registry import OptimizationRegistry

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
