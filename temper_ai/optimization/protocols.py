"""Runtime-checkable protocols for evaluators and optimizers."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from temper_ai.optimization._schemas import EvaluationResult, OptimizationResult


@runtime_checkable
class EvaluatorProtocol(Protocol):
    """Protocol for output evaluators."""

    def evaluate(
        self,
        output: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> EvaluationResult:
        """Evaluate a single output and return a result."""
        ...

    def compare(
        self,
        output_a: dict[str, Any],
        output_b: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> int:
        """Compare two outputs. Returns -1 (A better), 0 (tie), 1 (B better)."""
        ...


@runtime_checkable
class OptimizerProtocol(Protocol):
    """Protocol for output optimizers."""

    def optimize(
        self,
        runner: Any,
        input_data: dict[str, Any],
        evaluator: EvaluatorProtocol,
        config: dict[str, Any],
    ) -> OptimizationResult:
        """Run optimization loop and return the best result."""
        ...
