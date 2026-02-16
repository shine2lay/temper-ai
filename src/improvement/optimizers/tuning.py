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
        strategies: List[Dict[str, Any]] = config.get("strategies", [])
        runs_per_config: int = config.get("runs", DEFAULT_RUNS)

        if not self.experiment_service:
            return self._run_without_service(
                runner, input_data, evaluator, strategies, runs_per_config
            )

        return self._run_with_service(
            runner, input_data, evaluator, strategies, runs_per_config
        )

    def _run_without_service(
        self,
        runner: Any,
        input_data: Dict[str, Any],
        evaluator: EvaluatorProtocol,
        strategies: List[Dict[str, Any]],
        runs_per_config: int,
    ) -> OptimizationResult:
        """Fallback: run each strategy and pick best (no persistence)."""
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
        strategies: List[Dict[str, Any]],
        runs_per_config: int,
    ) -> OptimizationResult:
        """Run via ExperimentService for tracking and early stopping."""
        if self.experiment_service is None:
            raise RuntimeError("experiment_service is required for _run_with_service")
        experiment = self.experiment_service.create_experiment(
            name="optimization_tuning",
            description="Automated config tuning",
            variants=[{"name": s.get("name", f"v{i}"), "config": s}
                       for i, s in enumerate(strategies)],
        )
        exp_id = experiment.id if hasattr(experiment, "id") else str(experiment)
        self.experiment_service.start_experiment(exp_id)

        best_output: Dict[str, Any] = {}
        best_score = -1.0

        for strategy in strategies:
            for _ in range(runs_per_config):
                merged_input = {**input_data, **strategy}
                output = runner.execute(merged_input)
                result = evaluator.evaluate(output)

                if result.score > best_score:
                    best_score = result.score
                    best_output = output

            stopping = self.experiment_service.check_early_stopping(exp_id)
            if stopping.get("should_stop", False):
                logger.info("Early stopping triggered for experiment %s", exp_id)
                break

        self.experiment_service.stop_experiment(exp_id)

        return OptimizationResult(
            output=best_output,
            score=best_score,
            iterations=len(strategies) * runs_per_config,
            improved=True,
            details={"experiment_id": exp_id},
        )
