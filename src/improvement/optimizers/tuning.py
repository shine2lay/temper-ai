"""Tuning optimizer — config search via ExperimentService."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from src.improvement._schemas import OptimizationResult
from src.improvement.constants import DEFAULT_RUNS
from src.improvement.protocols import EvaluatorProtocol

logger = logging.getLogger(__name__)


class TuningOptimizer:
    """Optimizer that searches config space using ExperimentService."""

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
        """Run config variants and select the best via experimentation."""
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
        """Fallback: run each strategy and pick best (no persistence)."""
        strategies: List[Dict[str, Any]] = config.get("strategies", [])
        runs_per_config: int = config.get("runs", DEFAULT_RUNS)

        if not strategies:
            output = runner.execute(input_data)
            result = evaluator.evaluate(output)
            return OptimizationResult(
                output=output, score=result.score
            )

        best_output: Dict[str, Any] = {}
        best_score = -1.0
        strategy_scores: Dict[str, float] = {}

        for strategy in strategies:
            name = strategy.get("name", "unnamed")
            total_score = 0.0
            last_output: Dict[str, Any] = {}

            for _ in range(runs_per_config):
                merged_input = {**input_data, **strategy}
                last_output = runner.execute(merged_input)
                result = evaluator.evaluate(last_output)
                total_score += result.score

            avg_score = total_score / runs_per_config
            strategy_scores[name] = avg_score

            if avg_score > best_score:
                best_score = avg_score
                best_output = last_output

        return OptimizationResult(
            output=best_output,
            score=best_score,
            iterations=len(strategies) * runs_per_config,
            improved=len(strategies) > 1,
            details={"strategy_scores": strategy_scores},
        )

    def _run_with_service(
        self,
        runner: Any,
        input_data: Dict[str, Any],
        evaluator: EvaluatorProtocol,
        config: Dict[str, Any],
    ) -> OptimizationResult:
        """Run via ExperimentService with proper tracking."""
        from src.improvement._experiment_helpers import (
            create_tuning_experiment,
            finalize_experiment,
        )

        strategies: List[Dict[str, Any]] = config.get("strategies", [])
        runs_per_config: int = config.get("runs", DEFAULT_RUNS)

        evaluator_name = getattr(evaluator, "name", "unknown")
        experiment_id = create_tuning_experiment(
            self.experiment_service, evaluator_name,
            strategies, runs_per_config,
        )

        best_output, best_score, run_idx = self._execute_strategy_runs(
            runner, input_data, evaluator, strategies,
            runs_per_config, experiment_id,
        )

        experiment_results = finalize_experiment(
            self.experiment_service, experiment_id
        )

        return OptimizationResult(
            output=best_output,
            score=best_score,
            iterations=run_idx,
            improved=True,
            experiment_id=experiment_id,
            experiment_results=experiment_results,
        )

    def _execute_strategy_runs(
        self,
        runner: Any,
        input_data: Dict[str, Any],
        evaluator: EvaluatorProtocol,
        strategies: List[Dict[str, Any]],
        runs_per_config: int,
        experiment_id: str,
    ) -> tuple:
        """Execute all strategy runs and return (best_output, best_score, run_idx)."""
        from src.improvement._experiment_helpers import (
            create_workflow_id,
            track_run_result,
        )

        best_output: Dict[str, Any] = {}
        best_score = -1.0
        run_idx = 0

        for strategy in strategies:
            for _ in range(runs_per_config):
                workflow_id = create_workflow_id(experiment_id, run_idx)
                self.experiment_service.assign_variant(  # type: ignore[union-attr]
                    workflow_id, experiment_id
                )

                merged_input = {**input_data, **strategy}
                output = runner.execute(merged_input)
                result = evaluator.evaluate(output)

                track_run_result(
                    self.experiment_service, workflow_id, result.score
                )

                if result.score > best_score:
                    best_score = result.score
                    best_output = output

                run_idx += 1

            stopping = self.experiment_service.check_early_stopping(  # type: ignore[union-attr]
                experiment_id
            )
            if stopping.get("should_stop", False):
                logger.info(
                    "Early stopping triggered for experiment %s",
                    experiment_id,
                )
                break

        return best_output, best_score, run_idx
