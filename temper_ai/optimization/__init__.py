"""Unified optimization engine for Temper AI.

Combines:
- Composable optimization pipeline (evaluators + optimizers)
- DSPy prompt optimization (in ``optimization.dspy`` subpackage)
"""
from temper_ai.optimization._schemas import (
    CheckConfig,
    EvaluationResult,
    EvaluatorConfig,
    OptimizationConfig,
    OptimizationResult,
    PipelineStepConfig,
)
from temper_ai.optimization.engine import OptimizationEngine
from temper_ai.optimization.protocols import EvaluatorProtocol, OptimizerProtocol
from temper_ai.optimization.registry import OptimizationRegistry

__all__ = [
    "CheckConfig",
    "EvaluationResult",
    "EvaluatorConfig",
    "EvaluatorProtocol",
    "OptimizationConfig",
    "OptimizationEngine",
    "OptimizationResult",
    "OptimizerProtocol",
    "OptimizationRegistry",
    "PipelineStepConfig",
]
