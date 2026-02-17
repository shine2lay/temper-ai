"""Optimization engine — pipeline orchestrator."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from src.improvement._schemas import (
    EvaluationResult,
    OptimizationConfig,
    OptimizationResult,
    PipelineStepConfig,
)
from src.improvement.registry import OptimizationRegistry

logger = logging.getLogger(__name__)


class OptimizationEngine:
    """Orchestrates an optimization pipeline from config."""

    def __init__(
        self,
        config: OptimizationConfig,
        llm: Optional[Any] = None,
        experiment_service: Optional[Any] = None,
        registry: Optional[OptimizationRegistry] = None,
    ) -> None:
        self.config = config
        self.llm = llm
        self.experiment_service = experiment_service
        self.registry = registry or OptimizationRegistry.get_instance()
        self._evaluator_instances: Dict[str, Any] = {}
        self._build_evaluators()

    def _build_evaluators(self) -> None:
        """Instantiate evaluators from config."""
        for name, eval_config in self.config.evaluators.items():
            cls = self.registry.get_evaluator_class(eval_config.type)
            self._evaluator_instances[name] = cls(
                config=eval_config, llm=self.llm
            )

    def run(
        self,
        runner: Any,
        input_data: Dict[str, Any],
    ) -> OptimizationResult:
        """Execute the optimization pipeline sequentially."""
        if not self.config.enabled or not self.config.pipeline:
            output = runner.execute(input_data)
            return OptimizationResult(output=output)

        current_output: Dict[str, Any] = {}
        total_iterations = 0
        any_improved = False

        for step in self.config.pipeline:
            result = self._run_step(step, runner, input_data)
            current_output = result.output
            total_iterations += result.iterations
            if result.improved:
                any_improved = True
            input_data = current_output

        final_score = self._evaluate_final(current_output)

        return OptimizationResult(
            output=current_output,
            score=final_score,
            iterations=total_iterations,
            improved=any_improved,
        )

    def _run_step(
        self,
        step: PipelineStepConfig,
        runner: Any,
        input_data: Dict[str, Any],
    ) -> OptimizationResult:
        """Execute a single pipeline step."""
        evaluator = self._evaluator_instances.get(step.evaluator)
        if evaluator is None:
            raise KeyError(
                f"Evaluator '{step.evaluator}' not found in config"
            )

        optimizer_cls = self.registry.get_optimizer_class(step.optimizer)
        kwargs = self._build_optimizer_kwargs(optimizer_cls)
        optimizer = optimizer_cls(**kwargs)

        step_config = {
            "max_iterations": step.max_iterations,
            "runs": step.runs,
            "strategies": step.strategies,
        }

        result: OptimizationResult = optimizer.optimize(
            runner, input_data, evaluator, step_config
        )
        return result

    def _build_optimizer_kwargs(
        self, optimizer_cls: Any
    ) -> Dict[str, Any]:
        """Build kwargs for optimizer constructor based on its signature."""
        import inspect

        kwargs: Dict[str, Any] = {}
        sig = inspect.signature(optimizer_cls.__init__)

        if "experiment_service" in sig.parameters:
            kwargs["experiment_service"] = self.experiment_service
        if "llm" in sig.parameters:
            kwargs["llm"] = self.llm

        return kwargs

    def _evaluate_final(
        self, output: Dict[str, Any]
    ) -> float:
        """Evaluate final output with first evaluator if available."""
        if not self._evaluator_instances:
            return 1.0
        first_evaluator = next(iter(self._evaluator_instances.values()))
        result: EvaluationResult = first_evaluator.evaluate(output)
        return result.score
