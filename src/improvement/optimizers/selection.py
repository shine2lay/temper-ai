"""Selection optimizer — N runs, pick best."""

from __future__ import annotations

import logging
from typing import Any, Dict

from src.improvement._schemas import OptimizationResult
from src.improvement.constants import DEFAULT_RUNS
from src.improvement.protocols import EvaluatorProtocol

logger = logging.getLogger(__name__)


class SelectionOptimizer:
    """Optimizer that runs N executions and picks the best output."""

    def optimize(
        self,
        runner: Any,
        input_data: Dict[str, Any],
        evaluator: EvaluatorProtocol,
        config: Dict[str, Any],
    ) -> OptimizationResult:
        """Execute N runs and select the output with the highest score."""
        runs: int = config.get("runs", DEFAULT_RUNS)

        best_output: Dict[str, Any] = {}
        best_score = -1.0
        scores = []

        for i in range(runs):
            output = runner.execute(input_data)
            result = evaluator.evaluate(output)
            scores.append(result.score)

            if result.score > best_score:
                best_output = output
                best_score = result.score

            if result.passed:
                logger.info("Selection: run %d passed, stopping early", i + 1)
                break

        return OptimizationResult(
            output=best_output,
            score=best_score,
            iterations=len(scores),
            improved=len(scores) > 1,
            details={"scores": scores},
        )
