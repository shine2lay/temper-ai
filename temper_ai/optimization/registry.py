"""Thread-safe evaluator/optimizer registry."""

from __future__ import annotations

import threading
from typing import Any, Dict, Type

from temper_ai.optimization.engine_constants import (
    EVALUATOR_COMPARATIVE,
    EVALUATOR_CRITERIA,
    EVALUATOR_HUMAN,
    EVALUATOR_SCORED,
    OPTIMIZER_PROMPT,
    OPTIMIZER_REFINEMENT,
    OPTIMIZER_SELECTION,
    OPTIMIZER_TUNING,
)
from temper_ai.optimization.evaluators.comparative import ComparativeEvaluator
from temper_ai.optimization.evaluators.criteria import CriteriaEvaluator
from temper_ai.optimization.evaluators.human import HumanEvaluator
from temper_ai.optimization.evaluators.scored import ScoredEvaluator
from temper_ai.optimization.optimizers.prompt import PromptOptimizer
from temper_ai.optimization.optimizers.refinement import RefinementOptimizer
from temper_ai.optimization.optimizers.selection import SelectionOptimizer
from temper_ai.optimization.optimizers.tuning import TuningOptimizer


class OptimizationRegistry:
    """Thread-safe singleton registry for evaluators and optimizers."""

    _instance: OptimizationRegistry | None = None
    _lock = threading.RLock()

    def __init__(self) -> None:
        self._evaluators: Dict[str, Type[Any]] = {}
        self._optimizers: Dict[str, Type[Any]] = {}
        self._register_builtins()

    @classmethod
    def get_instance(cls) -> OptimizationRegistry:
        """Return the singleton registry instance."""
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def _register_builtins(self) -> None:
        """Register built-in evaluators and optimizers."""
        self._evaluators[EVALUATOR_CRITERIA] = CriteriaEvaluator
        self._evaluators[EVALUATOR_COMPARATIVE] = ComparativeEvaluator
        self._evaluators[EVALUATOR_SCORED] = ScoredEvaluator
        self._evaluators[EVALUATOR_HUMAN] = HumanEvaluator

        self._optimizers[OPTIMIZER_REFINEMENT] = RefinementOptimizer
        self._optimizers[OPTIMIZER_SELECTION] = SelectionOptimizer
        self._optimizers[OPTIMIZER_TUNING] = TuningOptimizer
        self._optimizers[OPTIMIZER_PROMPT] = PromptOptimizer

    def get_evaluator_class(self, name: str) -> Type[Any]:
        """Get evaluator class by name."""
        with self._lock:
            if name not in self._evaluators:
                raise KeyError(f"Unknown evaluator: {name}")
            return self._evaluators[name]

    def get_optimizer_class(self, name: str) -> Type[Any]:
        """Get optimizer class by name."""
        with self._lock:
            if name not in self._optimizers:
                raise KeyError(f"Unknown optimizer: {name}")
            return self._optimizers[name]

    def register_evaluator(
        self, name: str, cls: Type[Any]
    ) -> None:
        """Register a custom evaluator class."""
        with self._lock:
            self._evaluators[name] = cls

    def register_optimizer(
        self, name: str, cls: Type[Any]
    ) -> None:
        """Register a custom optimizer class."""
        with self._lock:
            self._optimizers[name] = cls

    @classmethod
    def reset_for_testing(cls) -> None:
        """Reset singleton for test isolation."""
        with cls._lock:
            cls._instance = None
