"""Helper functions extracted from LoopExecutor to reduce class size.

These are internal implementation details - use LoopExecutor's public API.
"""
import logging
import uuid
from typing import Any

from src.constants.probabilities import PROB_VERY_HIGH
from src.self_improvement.constants import (
    FIELD_AGENT_NAME,
    FIELD_CONTROL_CONFIG,
    FIELD_EXPERIMENT_ID,
    MODULE_SELF_IMPROVEMENT,
)
from src.self_improvement.data_models import StrategyOutcome

from .models import ExperimentPhaseResult, StrategyResult

logger = logging.getLogger(__name__)

OUTCOME_ID_UUID_LENGTH = 12


def track_winner_experiment_outcome(
    tracker: Any,
    agent_name: str,
    experiment_id: str,
    strategy_result: StrategyResult,
    winner: Any,
) -> None:
    """Track successful experiment decision outcome for observability.

    Args:
        tracker: ExecutionTracker instance
        agent_name: Name of agent
        experiment_id: Experiment identifier
        strategy_result: Strategy result with configs
        winner: Winner result object
    """
    try:
        tracker.track_decision_outcome(
            decision_type="experiment_selection",
            decision_data={
                FIELD_AGENT_NAME: agent_name,
                FIELD_EXPERIMENT_ID: experiment_id,
                FIELD_CONTROL_CONFIG: strategy_result.control_config.model_dump() if hasattr(strategy_result.control_config, 'model_dump') else dict(strategy_result.control_config),
                "winner_variant_id": winner.variant_id,
                "winner_config": winner.winning_config.model_dump() if hasattr(winner.winning_config, 'model_dump') else dict(winner.winning_config),
                "strategy": strategy_result.strategy_name,
            },
            outcome="success",
            impact_metrics={
                "quality_improvement_pct": winner.quality_improvement,
                "speed_improvement_pct": winner.speed_improvement,
                "cost_improvement_pct": winner.cost_improvement,
                "composite_score": winner.composite_score,
                "statistical_significance": winner.is_statistically_significant,
                "confidence": winner.confidence,
            },
            lessons_learned=f"Variant {winner.variant_id} outperformed control with {winner.quality_improvement:.1f}% quality improvement",
            should_repeat=winner.is_statistically_significant,
            tags=[MODULE_SELF_IMPROVEMENT, "experiment", strategy_result.strategy_name],
            validation_method="statistical_analysis",
        )
    except Exception as e:
        logger.warning(f"Failed to track experiment outcome: {e}")


def track_inconclusive_experiment_outcome(
    tracker: Any,
    agent_name: str,
    experiment_id: str,
    strategy_name: str,
) -> None:
    """Track inconclusive experiment decision outcome.

    Args:
        tracker: ExecutionTracker instance
        agent_name: Name of agent
        experiment_id: Experiment identifier
        strategy_name: Strategy name used
    """
    try:
        tracker.track_decision_outcome(
            decision_type="experiment_selection",
            decision_data={
                "agent_name": agent_name,
                "experiment_id": experiment_id,
                "strategy": strategy_name,
            },
            outcome="neutral",
            impact_metrics={},
            lessons_learned="No statistically significant improvement found - control remains best",
            should_repeat=False,
            tags=["self_improvement", "experiment", "inconclusive"],
            validation_method="statistical_analysis",
        )
    except Exception as e:
        logger.warning(f"Failed to track experiment outcome: {e}")


def track_deployment_outcome(
    tracker: Any,
    agent_name: str,
    deployment_id: str,
    experiment_result: ExperimentPhaseResult,
    previous_config: Any,
    enable_auto_rollback: bool,
    deployed_at: Any,
) -> None:
    """Track deployment decision outcome for observability.

    Args:
        tracker: ExecutionTracker instance
        agent_name: Name of agent
        deployment_id: Deployment identifier
        experiment_result: Experiment result with configs
        previous_config: Previous agent config
        enable_auto_rollback: Whether rollback monitoring is enabled
        deployed_at: Deployment timestamp
    """
    try:
        tracker.track_decision_outcome(
            decision_type="config_deployment",
            decision_data={
                "agent_name": agent_name,
                "deployment_id": deployment_id,
                "experiment_id": experiment_result.experiment_id,
                "deployed_config": (
                    experiment_result.winner_config.model_dump()
                    if experiment_result.winner_config and hasattr(experiment_result.winner_config, 'model_dump')
                    else dict(experiment_result.winner_config) if experiment_result.winner_config else {}
                ),
                "previous_config": previous_config.model_dump() if hasattr(previous_config, 'model_dump') else dict(previous_config),
                "rollback_monitoring_enabled": enable_auto_rollback,
            },
            outcome="success",
            impact_metrics=experiment_result.metrics_comparison or {},
            lessons_learned=f"Deployed winning config from experiment {experiment_result.experiment_id}",
            should_repeat=True,
            tags=["self_improvement", "deployment", "auto_deploy"],
            validation_method="rollback_monitor" if enable_auto_rollback else "manual",
            validation_timestamp=deployed_at,
        )
    except Exception as e:
        logger.warning(f"Failed to track deployment outcome: {e}")


def record_winner_strategy_outcome(
    strategy_learning_store: Any,
    strategy_result: StrategyResult,
    agent_name: str,
    experiment_id: str,
    winner: Any,
    target_samples_per_variant: int,
) -> None:
    """Record strategy outcome when there is a winner.

    Args:
        strategy_learning_store: StrategyLearningStore instance
        strategy_result: Strategy result with configs
        agent_name: Name of agent
        experiment_id: Experiment identifier
        winner: Winner result object
        target_samples_per_variant: Target samples per variant
    """
    try:
        problem_type = strategy_result.strategy_metadata.get("problem_type", "quality_low")

        outcome = StrategyOutcome(
            id=f"outcome-{uuid.uuid4().hex[:OUTCOME_ID_UUID_LENGTH]}",
            strategy_name=strategy_result.strategy_name,
            problem_type=problem_type,
            agent_name=agent_name,
            experiment_id=experiment_id,
            was_winner=True,
            actual_quality_improvement=winner.quality_improvement / 100.0,
            actual_speed_improvement=winner.speed_improvement / 100.0,
            actual_cost_improvement=winner.cost_improvement / 100.0,
            composite_score=winner.composite_score / 100.0,
            confidence=winner.confidence,
            sample_size=target_samples_per_variant * (len(strategy_result.variant_configs) + 1),
            context={
                "control_config": strategy_result.control_config.to_dict(),
                "winner_variant_id": winner.variant_id,
                "statistical_significance": winner.is_statistically_significant,
            },
        )

        strategy_learning_store.record_outcome(outcome)
        logger.info(
            f"Recorded strategy outcome for {strategy_result.strategy_name}: "
            f"{winner.quality_improvement:.1f}% quality improvement"
        )
    except Exception as e:
        logger.warning(f"Failed to record strategy outcome: {e}")


def record_no_winner_strategy_outcome(
    strategy_learning_store: Any,
    strategy_result: StrategyResult,
    agent_name: str,
    experiment_id: str,
    target_samples_per_variant: int,
) -> None:
    """Record strategy outcome when there is no winner.

    Args:
        strategy_learning_store: StrategyLearningStore instance
        strategy_result: Strategy result with configs
        agent_name: Name of agent
        experiment_id: Experiment identifier
        target_samples_per_variant: Target samples per variant
    """
    try:
        problem_type = strategy_result.strategy_metadata.get("problem_type", "quality_low")

        outcome = StrategyOutcome(
            id=f"outcome-{uuid.uuid4().hex[:OUTCOME_ID_UUID_LENGTH]}",
            strategy_name=strategy_result.strategy_name,
            problem_type=problem_type,
            agent_name=agent_name,
            experiment_id=experiment_id,
            was_winner=False,
            actual_quality_improvement=0.0,
            actual_speed_improvement=0.0,
            actual_cost_improvement=0.0,
            composite_score=0.0,
            confidence=PROB_VERY_HIGH,
            sample_size=target_samples_per_variant * (len(strategy_result.variant_configs) + 1),
            context={
                "control_config": strategy_result.control_config.to_dict(),
                "reason": "No statistically significant improvement",
            },
        )

        strategy_learning_store.record_outcome(outcome)
        logger.info(
            f"Recorded no-improvement outcome for {strategy_result.strategy_name}"
        )
    except Exception as e:
        logger.warning(f"Failed to record strategy outcome: {e}")
