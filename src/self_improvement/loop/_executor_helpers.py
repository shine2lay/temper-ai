"""Helper functions extracted from LoopExecutor to reduce class size.

These are internal implementation details - use LoopExecutor's public API.
"""
import logging
import uuid
from typing import Any, List, Optional

from src.constants.probabilities import PROB_VERY_HIGH
from src.self_improvement.constants import (
    FIELD_AGENT_NAME,
    FIELD_CONTROL_CONFIG,
    FIELD_EXPERIMENT_ID,
    MODULE_SELF_IMPROVEMENT,
)
from src.self_improvement.data_models import StrategyOutcome

from .models import (
    AnalysisResult,
    DeploymentResult,
    ExperimentPhaseResult,
    StrategyResult,
)

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


def create_winner_result(
    experiment_id: str,
    winner: Any,
    agent_name: str,
    strategy_result: StrategyResult,
    tracker: Optional[Any],
    strategy_learning_store: Any,
    target_samples_per_variant: int,
) -> ExperimentPhaseResult:
    """Create experiment result for winning variant.

    Args:
        experiment_id: Experiment identifier.
        winner: Winner result object.
        agent_name: Name of agent.
        strategy_result: Strategy result with configs.
        tracker: Optional ExecutionTracker for observability.
        strategy_learning_store: StrategyLearningStore instance.
        target_samples_per_variant: Target samples per variant.

    Returns:
        ExperimentPhaseResult for the winning variant.
    """
    logger.info(
        f"Experiment {experiment_id} has winner: {winner.variant_id} "
        f"(improvement: {winner.quality_improvement:.1f}%, "
        f"confidence: {winner.confidence:.2f})"
    )

    result = ExperimentPhaseResult(
        experiment_id=experiment_id,
        winner_variant_id=winner.variant_id,
        winner_config=winner.winning_config,
        statistical_significance=winner.is_statistically_significant,
        metrics_comparison={
            "quality_improvement": winner.quality_improvement,
            "speed_improvement": winner.speed_improvement,
            "cost_improvement": winner.cost_improvement,
            "composite_score": winner.composite_score,
        },
    )

    if tracker:
        track_winner_experiment_outcome(
            tracker, agent_name, experiment_id, strategy_result, winner,
        )

    record_winner_strategy_outcome(
        strategy_learning_store, strategy_result, agent_name,
        experiment_id, winner, target_samples_per_variant,
    )

    return result


def create_no_winner_result(
    experiment_id: str,
    agent_name: str,
    strategy_result: StrategyResult,
    tracker: Optional[Any],
    strategy_learning_store: Any,
    target_samples_per_variant: int,
) -> ExperimentPhaseResult:
    """Create experiment result when no winner found.

    Args:
        experiment_id: Experiment identifier.
        agent_name: Name of agent.
        strategy_result: Strategy result with configs.
        tracker: Optional ExecutionTracker for observability.
        strategy_learning_store: StrategyLearningStore instance.
        target_samples_per_variant: Target samples per variant.

    Returns:
        ExperimentPhaseResult with no winner.
    """
    logger.info(f"No winner (control best or inconclusive) for {agent_name}")

    result = ExperimentPhaseResult(
        experiment_id=experiment_id,
        winner_variant_id=None,
        winner_config=None,
        statistical_significance=None,
        metrics_comparison=None,
    )

    if tracker:
        track_inconclusive_experiment_outcome(
            tracker, agent_name, experiment_id, strategy_result.strategy_name,
        )

    record_no_winner_strategy_outcome(
        strategy_learning_store, strategy_result, agent_name,
        experiment_id, target_samples_per_variant,
    )

    return result


def execute_strategy_phase(
    agent_name: str,
    analysis_result: AnalysisResult,
    config_deployer: Any,
    pattern_miner: Any,
    enable_model_variants: bool,
    max_variants_per_experiment: int,
    min_support: int,
    min_confidence: float,
    min_win_rate: float,
    min_improvement: float,
    days_back: int,
    top_patterns_limit: int,
) -> StrategyResult:
    """Execute Phase 3: Strategy Generation.

    Args:
        agent_name: Name of agent to generate strategies for.
        analysis_result: Result from the analysis phase.
        config_deployer: ConfigDeployer instance.
        pattern_miner: PatternMiner instance.
        enable_model_variants: Whether to generate model variant configs.
        max_variants_per_experiment: Max variants to test.
        min_support: Minimum support for pattern mining.
        min_confidence: Minimum confidence for pattern mining.
        min_win_rate: Minimum win rate for pattern mining.
        min_improvement: Minimum improvement threshold for pattern mining.
        days_back: Number of days to look back for patterns.
        top_patterns_limit: Number of top patterns to log.

    Returns:
        StrategyResult with control and variant configs.
    """
    logger.info(f"Phase 3 (STRATEGY): Generating improvement strategies for {agent_name}")

    control_config = config_deployer.get_agent_config(agent_name)

    try:
        patterns = pattern_miner.mine_patterns(
            min_support=min_support,
            min_confidence=min_confidence,
            min_win_rate=min_win_rate,
            min_improvement=min_improvement,
            days_back=days_back,
        )
        logger.info(f"Mined {len(patterns)} patterns from experiment history")

        for pattern in patterns[:top_patterns_limit]:
            logger.info(
                f"  Pattern: {pattern.evidence['strategy_name']} for "
                f"{pattern.evidence['problem_type']} "
                f"(confidence={pattern.confidence:.2f})"
            )
    except Exception as e:
        logger.warning(f"Failed to mine patterns: {e}")
        patterns = []

    variant_configs: List[Any] = []

    if enable_model_variants:
        models_to_test = ["gemma2:2b", "phi3:mini", "mistral:7b"]
        for model in models_to_test[:max_variants_per_experiment]:
            variant = control_config.copy()
            variant.inference["model"] = model
            variant_configs.append(variant)

    logger.info(f"Generated {len(variant_configs)} variant configs for {agent_name}")

    return StrategyResult(
        control_config=control_config,
        variant_configs=variant_configs,
        strategy_name="model_variants",
        strategy_metadata={
            "models_tested": [v.inference["model"] for v in variant_configs],
            "patterns_considered": len(patterns),
            "problem_type": "quality_low",
        },
    )


def execute_deploy_phase(
    agent_name: str,
    experiment_result: ExperimentPhaseResult,
    config_deployer: Any,
    enable_auto_deploy: bool,
    enable_auto_rollback: bool,
    tracker: Optional[Any],
) -> DeploymentResult:
    """Execute Phase 5: Deployment.

    Args:
        agent_name: Name of agent to deploy for.
        experiment_result: Result from the experiment phase.
        config_deployer: ConfigDeployer instance.
        enable_auto_deploy: Whether auto-deploy is enabled.
        enable_auto_rollback: Whether auto-rollback is enabled.
        tracker: Optional ExecutionTracker for observability.

    Returns:
        DeploymentResult with deployment details.

    Raises:
        ValueError: If no winner config or auto-deploy disabled.
        RuntimeError: If deployment record not found after deploy.
    """
    logger.info(f"Phase 5 (DEPLOY): Deploying winner config for {agent_name}")

    if not experiment_result.winner_config:
        raise ValueError("No winner config to deploy")

    previous_config = config_deployer.get_agent_config(agent_name)

    if not enable_auto_deploy:
        logger.info(f"Auto-deploy disabled, skipping deployment for {agent_name}")
        raise ValueError("Auto-deploy disabled")

    config_deployer.deploy(
        agent_name=agent_name,
        new_config=experiment_result.winner_config,
        experiment_id=experiment_result.experiment_id,
    )

    deployment = config_deployer.get_last_deployment(agent_name)

    if deployment is None:
        raise RuntimeError(
            f"Deployment record not found after successful deploy for {agent_name}"
        )

    logger.info(
        f"Deployed config {deployment.id} for {agent_name}. "
        f"Rollback monitoring: {enable_auto_rollback}"
    )

    result = DeploymentResult(
        deployment_id=deployment.id,
        deployed_config=experiment_result.winner_config,
        previous_config=previous_config,
        deployment_timestamp=deployment.deployed_at,
        rollback_monitoring_enabled=enable_auto_rollback,
    )

    if tracker:
        track_deployment_outcome(
            tracker, agent_name, deployment.id, experiment_result,
            previous_config, enable_auto_rollback, deployment.deployed_at,
        )

    return result
