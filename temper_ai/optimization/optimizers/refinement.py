"""Refinement optimizer — critique + retry loop."""

from __future__ import annotations

import json
import logging
from typing import Any

from temper_ai.optimization._schemas import EvaluationResult, OptimizationResult
from temper_ai.optimization.engine_constants import DEFAULT_MAX_ITERATIONS
from temper_ai.optimization.protocols import EvaluatorProtocol

logger = logging.getLogger(__name__)


class RefinementOptimizer:
    """Optimizer that iteratively refines output via critique feedback."""

    def __init__(
        self,
        llm: Any | None = None,
        experiment_service: Any | None = None,
    ) -> None:
        self.llm = llm
        self.experiment_service = experiment_service

    def optimize(
        self,
        runner: Any,
        input_data: dict[str, Any],
        evaluator: EvaluatorProtocol,
        config: dict[str, Any],
    ) -> OptimizationResult:
        """Run refinement loop: execute -> evaluate -> critique -> retry."""
        if self.experiment_service:
            return self._run_with_service(runner, input_data, evaluator, config)
        return self._run_without_service(runner, input_data, evaluator, config)

    def _run_without_service(
        self,
        runner: Any,
        input_data: dict[str, Any],
        evaluator: EvaluatorProtocol,
        config: dict[str, Any],
    ) -> OptimizationResult:
        """Run refinement without experiment tracking."""
        max_iterations: int = config.get("max_iterations", DEFAULT_MAX_ITERATIONS)

        best_output = runner.execute(input_data)
        best_eval = evaluator.evaluate(best_output)
        iteration = 0

        if best_eval.passed:
            return OptimizationResult(
                output=best_output,
                score=best_eval.score,
                iterations=iteration,
            )

        for iteration in range(1, max_iterations + 1):
            critique = self._generate_critique(best_output, best_eval)
            refined_input = self._inject_critique(input_data, critique)
            new_output = runner.execute(refined_input)
            new_eval = evaluator.evaluate(new_output)

            if new_eval.score > best_eval.score:
                best_output = new_output
                best_eval = new_eval

            if best_eval.passed:
                break

        return OptimizationResult(
            output=best_output,
            score=best_eval.score,
            iterations=iteration,
            improved=iteration > 0,
            details={"final_passed": best_eval.passed},
        )

    def _run_with_service(
        self,
        runner: Any,
        input_data: dict[str, Any],
        evaluator: EvaluatorProtocol,
        config: dict[str, Any],
    ) -> OptimizationResult:
        """Run refinement WITH experiment tracking."""
        from temper_ai.optimization._experiment_helpers import (
            create_refinement_experiment,
            finalize_experiment,
        )

        max_iterations: int = config.get("max_iterations", DEFAULT_MAX_ITERATIONS)
        evaluator_name = getattr(evaluator, "name", "unknown")
        experiment_id = create_refinement_experiment(
            self.experiment_service, evaluator_name, max_iterations
        )

        best_output, best_eval, iteration = self._run_baseline_tracked(
            runner, input_data, evaluator, experiment_id
        )

        if not best_eval.passed:
            best_output, best_eval, iteration = self._run_iterations_tracked(
                runner,
                input_data,
                evaluator,
                experiment_id,
                best_output,
                best_eval,
                max_iterations,
            )

        experiment_results = finalize_experiment(self.experiment_service, experiment_id)

        return OptimizationResult(
            output=best_output,
            score=best_eval.score,
            iterations=iteration,
            improved=iteration > 0,
            details={"final_passed": best_eval.passed},
            experiment_id=experiment_id,
            experiment_results=experiment_results,
        )

    def _run_baseline_tracked(
        self,
        runner: Any,
        input_data: dict[str, Any],
        evaluator: EvaluatorProtocol,
        experiment_id: str,
    ) -> tuple[dict[str, Any], EvaluationResult, int]:
        """Run and track baseline execution."""
        from temper_ai.optimization._experiment_helpers import (
            create_workflow_id,
            track_run_result,
        )

        workflow_id = create_workflow_id(experiment_id, 0)
        self.experiment_service.assign_variant(workflow_id, experiment_id)  # type: ignore[union-attr]

        output = runner.execute(input_data)
        eval_result = evaluator.evaluate(output)
        track_run_result(self.experiment_service, workflow_id, eval_result.score)

        return output, eval_result, 0

    def _run_iterations_tracked(  # noqa: params
        self,
        runner: Any,
        input_data: dict[str, Any],
        evaluator: EvaluatorProtocol,
        experiment_id: str,
        best_output: dict[str, Any],
        best_eval: EvaluationResult,
        max_iterations: int,
    ) -> tuple[dict[str, Any], EvaluationResult, int]:
        """Run and track refinement iterations."""
        from temper_ai.optimization._experiment_helpers import (
            create_workflow_id,
            track_run_result,
        )

        iteration = 0
        for iteration in range(1, max_iterations + 1):
            workflow_id = create_workflow_id(experiment_id, iteration)
            self.experiment_service.assign_variant(workflow_id, experiment_id)  # type: ignore[union-attr]

            critique = self._generate_critique(best_output, best_eval)
            refined_input = self._inject_critique(input_data, critique)
            new_output = runner.execute(refined_input)
            new_eval = evaluator.evaluate(new_output)

            track_run_result(self.experiment_service, workflow_id, new_eval.score)

            if new_eval.score > best_eval.score:
                best_output = new_output
                best_eval = new_eval

            if best_eval.passed:
                break

        return best_output, best_eval, iteration

    def _generate_critique(
        self, output: dict[str, Any], eval_result: EvaluationResult
    ) -> str:
        """Generate critique of the output using LLM."""
        if not self.llm:
            return f"Score: {eval_result.score}. Please improve."
        try:
            prompt = (
                f"Critique this output (score {eval_result.score}):\n"
                f"{json.dumps(output, indent=2)}\n\n"
                f"Issues: {json.dumps(eval_result.details)}\n\n"
                "Provide specific suggestions for improvement."
            )
            result: str = self.llm.generate(prompt)
            return result
        except (AttributeError, TypeError, RuntimeError):
            return f"Score: {eval_result.score}. Please improve."

    def _inject_critique(
        self, input_data: dict[str, Any], critique: str
    ) -> dict[str, Any]:
        """Inject critique feedback into input data for retry."""
        refined = dict(input_data)
        refined["_optimization_critique"] = critique
        return refined
