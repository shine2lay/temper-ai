"""Refinement optimizer — critique + retry loop."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

from src.improvement._schemas import EvaluationResult, OptimizationResult
from src.improvement.constants import DEFAULT_MAX_ITERATIONS
from src.improvement.protocols import EvaluatorProtocol

logger = logging.getLogger(__name__)


class RefinementOptimizer:
    """Optimizer that iteratively refines output via critique feedback."""

    def __init__(self, llm: Optional[Any] = None) -> None:
        self.llm = llm

    def optimize(
        self,
        runner: Any,
        input_data: Dict[str, Any],
        evaluator: EvaluatorProtocol,
        config: Dict[str, Any],
    ) -> OptimizationResult:
        """Run refinement loop: execute -> evaluate -> critique -> retry."""
        max_iterations: int = config.get(
            "max_iterations", DEFAULT_MAX_ITERATIONS
        )

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

    def _generate_critique(
        self, output: Dict[str, Any], eval_result: EvaluationResult
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
        self, input_data: Dict[str, Any], critique: str
    ) -> Dict[str, Any]:
        """Inject critique feedback into input data for retry."""
        refined = dict(input_data)
        refined["_optimization_critique"] = critique
        return refined
