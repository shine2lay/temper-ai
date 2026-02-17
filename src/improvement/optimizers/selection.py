"""Selection optimizer — N runs, pick best."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from src.improvement._schemas import OptimizationResult
from src.improvement.constants import DEFAULT_RUNS
from src.improvement.protocols import EvaluatorProtocol

logger = logging.getLogger(__name__)


class SelectionOptimizer:
    """Optimizer that runs N executions and picks the best output."""

    def __init__(
        self, experiment_service: Optional[Any] = None
    ) -> None:
        self.experiment_service = experiment_service

    def optimize(
        self,
        runner: Any,
        input_data: Dict[str, Any],
        evaluator: EvaluatorProtocol,
        config: Dict[str, Any],
    ) -> OptimizationResult:
        """Execute N runs and select the output with the highest score."""
        if self.experiment_service:
            return self._run_with_service(runner, input_data, evaluator, config)
        return self._run_without_service(runner, input_data, evaluator, config)

    def _run_without_service(
        self,
        runner: Any,
        input_data: Dict[str, Any],
        evaluator: EvaluatorProtocol,
        config: Dict[str, Any],
    ) -> OptimizationResult:
        """Run selection without experiment tracking."""
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

    def _run_with_service(
        self,
        runner: Any,
        input_data: Dict[str, Any],
        evaluator: EvaluatorProtocol,
        config: Dict[str, Any],
    ) -> OptimizationResult:
        """Run selection WITH experiment tracking."""
        from src.improvement._experiment_helpers import (
            create_selection_experiment,
            create_workflow_id,
            finalize_experiment,
            track_run_result,
        )

        runs: int = config.get("runs", DEFAULT_RUNS)
        evaluator_name = getattr(evaluator, "name", "unknown")
        experiment_id = create_selection_experiment(
            self.experiment_service, evaluator_name, runs
        )

        best_output: Dict[str, Any] = {}
        best_score = -1.0
        scores = []

        for i in range(runs):
            workflow_id = create_workflow_id(experiment_id, i)
            self.experiment_service.assign_variant(workflow_id, experiment_id)  # type: ignore[union-attr]

            output = runner.execute(input_data)
            result = evaluator.evaluate(output)
            scores.append(result.score)

            track_run_result(self.experiment_service, workflow_id, result.score)

            if result.score > best_score:
                best_output = output
                best_score = result.score

            if result.passed:
                logger.info("Selection: run %d passed, stopping early", i + 1)
                break

        experiment_results = finalize_experiment(
            self.experiment_service, experiment_id
        )

        return OptimizationResult(
            output=best_output,
            score=best_score,
            iterations=len(scores),
            improved=len(scores) > 1,
            details={"scores": scores},
            experiment_id=experiment_id,
            experiment_results=experiment_results,
        )
