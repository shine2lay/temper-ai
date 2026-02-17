"""Experiment tracking helpers for optimizers."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

METRIC_OPTIMIZATION_SCORE = "optimization_score"
STATUS_COMPLETED = "completed"
MIN_SAMPLE_SIZE_SINGLE = 1


def generate_experiment_name(
    optimizer_type: str, evaluator_name: str
) -> str:
    """Generate unique experiment name."""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"{optimizer_type}-{timestamp}-{evaluator_name}"


def create_workflow_id(experiment_id: str, run_index: int) -> str:
    """Generate unique workflow ID for experiment run."""
    return f"opt-{experiment_id}-run-{run_index}"


def create_selection_experiment(
    service: Any,
    evaluator_name: str,
    num_runs: int,
) -> str:
    """Create and start experiment for SelectionOptimizer."""
    variants = [
        {"name": f"run-{i}", "traffic": 1.0 / max(num_runs, 1)}
        for i in range(num_runs)
    ]
    exp_id: str = service.create_experiment(
        name=generate_experiment_name("selection", evaluator_name),
        description=f"Selection optimizer: best of {num_runs} runs",
        variants=variants,
        primary_metric=METRIC_OPTIMIZATION_SCORE,
        min_sample_size_per_variant=MIN_SAMPLE_SIZE_SINGLE,
    )
    service.start_experiment(exp_id)
    return exp_id


def create_refinement_experiment(
    service: Any,
    evaluator_name: str,
    max_iterations: int,
) -> str:
    """Create and start experiment for RefinementOptimizer."""
    variants: List[Dict[str, Any]] = [
        {"name": "baseline", "traffic": 0.5}
    ]
    variants.extend(
        {"name": f"iteration-{i}", "traffic": 0.5 / max(max_iterations, 1)}
        for i in range(1, max_iterations + 1)
    )
    exp_id: str = service.create_experiment(
        name=generate_experiment_name("refinement", evaluator_name),
        description=f"Refinement optimizer: baseline + {max_iterations} iterations",
        variants=variants,
        primary_metric=METRIC_OPTIMIZATION_SCORE,
        min_sample_size_per_variant=MIN_SAMPLE_SIZE_SINGLE,
    )
    service.start_experiment(exp_id)
    return exp_id


def create_tuning_experiment(
    service: Any,
    evaluator_name: str,
    strategies: List[Dict[str, Any]],
    runs_per_config: int,
) -> str:
    """Create and start experiment for TuningOptimizer."""
    variants = [
        {"name": s.get("name", f"strategy-{i}"), "config": s}
        for i, s in enumerate(strategies)
    ]
    exp_id: str = service.create_experiment(
        name=generate_experiment_name("tuning", evaluator_name),
        description=f"Tuning optimizer: {len(strategies)} strategies x {runs_per_config} runs",
        variants=variants,
        primary_metric=METRIC_OPTIMIZATION_SCORE,
    )
    service.start_experiment(exp_id)
    return exp_id


def track_run_result(
    service: Any,
    workflow_id: str,
    score: float,
) -> None:
    """Track optimization run completion with score."""
    service.track_execution_complete(
        workflow_id=workflow_id,
        metrics={METRIC_OPTIMIZATION_SCORE: score},
        status=STATUS_COMPLETED,
    )


def finalize_experiment(
    service: Any,
    experiment_id: str,
) -> Dict[str, Any]:
    """Stop experiment and get results."""
    results: Dict[str, Any] = service.get_experiment_results(experiment_id)
    winner = results.get("recommended_winner")
    service.stop_experiment(experiment_id, winner=winner)
    return results
