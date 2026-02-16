"""Runtime-checkable protocols for evaluators and optimizers."""

from __future__ import annotations

from typing import Any, Dict, Optional, Protocol, runtime_checkable

from src.improvement._schemas import EvaluationResult, OptimizationResult


@runtime_checkable
class EvaluatorProtocol(Protocol):
    """Protocol for output evaluators."""

    def evaluate(
        self,
        output: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> EvaluationResult:
        """Evaluate a single output and return a result."""
        ...

    def compare(
        self,
        output_a: Dict[str, Any],
        output_b: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> int:
        """Compare two outputs. Returns -1 (A better), 0 (tie), 1 (B better)."""
        ...


@runtime_checkable
class OptimizerProtocol(Protocol):
    """Protocol for output optimizers."""

    def optimize(
        self,
        runner: Any,
        input_data: Dict[str, Any],
        evaluator: EvaluatorProtocol,
        config: Dict[str, Any],
    ) -> OptimizationResult:
        """Run optimization loop and return the best result."""
        ...
