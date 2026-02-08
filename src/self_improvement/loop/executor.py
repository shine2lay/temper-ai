"""Loop executor for M5 Self-Improvement Loop.

See _executor_helpers.py for extracted tracking/recording logic.
"""
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from sqlmodel import Session

from src.constants.durations import DAYS_90
from src.constants.limits import THRESHOLD_SMALL_COUNT
from src.constants.probabilities import PROB_HIGH, PROB_MEDIUM
from src.self_improvement.deployment.deployer import ConfigDeployer
from src.self_improvement.deployment.rollback_monitor import (
    RegressionThresholds,
    RollbackMonitor,
)
from src.self_improvement.detection.improvement_detector import ImprovementDetector
from src.self_improvement.experiment_orchestrator import ExperimentOrchestrator

# Helper functions extracted to reduce class size
from src.self_improvement.loop._executor_helpers import (
    record_no_winner_strategy_outcome as _record_no_winner_outcome,
)
from src.self_improvement.loop._executor_helpers import (
    record_winner_strategy_outcome as _record_winner_outcome,
)
from src.self_improvement.loop._executor_helpers import (
    track_deployment_outcome as _track_deployment_outcome,
)
from src.self_improvement.loop._executor_helpers import (
    track_inconclusive_experiment_outcome as _track_inconclusive_outcome,
)
from src.self_improvement.loop._executor_helpers import (
    track_winner_experiment_outcome as _track_winner_outcome,
)
from src.self_improvement.pattern_mining import PatternMiner
from src.self_improvement.performance_analyzer import PerformanceAnalyzer
from src.self_improvement.strategy_learning import StrategyLearningStore

from .config import LoopConfig
from .error_recovery import ErrorRecoveryStrategy
from .metrics import MetricsCollector
from .models import (
    AnalysisResult,
    DeploymentResult,
    DetectionResult,
    ExperimentPhaseResult,
    IterationResult,
    Phase,
    RecoveryAction,
    StrategyResult,
)
from .state_manager import LoopStateManager

logger = logging.getLogger(__name__)

# Phase completion thresholds
PHASES_BEFORE_EXPERIMENT = 3  # Number of phases completed before experiment phase
PHASES_BEFORE_DEPLOY = 4  # Number of phases completed before deploy phase

# Pattern mining constants
MIN_IMPROVEMENT_THRESHOLD = 0.03  # Minimum 3% improvement for pattern mining
TOP_PATTERNS_LIMIT = 3  # Number of top patterns to log


class LoopExecutor:
    """Execute improvement loop iterations with phase orchestration.

    See _executor_helpers.py for extracted tracking/recording logic.
    """

    def __init__(
        self,
        coord_db,
        obs_session: Session,
        config: LoopConfig,
        state_manager: LoopStateManager,
        error_recovery: ErrorRecoveryStrategy,
        metrics_collector: MetricsCollector,
        tracker: Optional[Any] = None,
        policy_engine: Optional[Any] = None,
        approval_workflow: Optional[Any] = None,
    ):
        self.coord_db = coord_db
        self.obs_session = obs_session
        self.config = config
        self.state_manager = state_manager
        self.error_recovery = error_recovery
        self.metrics_collector = metrics_collector
        self.tracker = tracker

        self.performance_analyzer = PerformanceAnalyzer(obs_session)
        self.improvement_detector = ImprovementDetector(obs_session)
        self.experiment_orchestrator = ExperimentOrchestrator(
            session=obs_session,
            target_executions_per_variant=config.target_samples_per_variant
        )

        self.config_deployer = ConfigDeployer(
            db=coord_db,
            policy_engine=policy_engine,
            approval_workflow=approval_workflow,
            enable_safety_checks=config.enable_safety_checks if hasattr(config, 'enable_safety_checks') else True
        )

        self.strategy_learning_store = StrategyLearningStore(coord_db)
        self.pattern_miner = PatternMiner(self.strategy_learning_store)

        rollback_thresholds = RegressionThresholds(
            quality_drop_pct=config.rollback_quality_drop_pct,
            cost_increase_pct=config.rollback_cost_increase_pct,
            speed_increase_pct=config.rollback_speed_increase_pct,
            min_executions=config.rollback_min_executions,
        )
        self.rollback_monitor = RollbackMonitor(
            self.performance_analyzer,
            self.config_deployer,
            rollback_thresholds,
        )

    def execute_iteration(
        self,
        agent_name: str,
        start_phase: Phase = Phase.DETECT,
    ) -> IterationResult:
        """Execute complete improvement iteration."""
        start_time = datetime.now(timezone.utc)
        state = self.state_manager.get_state(agent_name)

        if not state:
            state = self.state_manager.create_state(agent_name)

        result = IterationResult(
            agent_name=agent_name,
            iteration_number=state.iteration_number,
            success=False,
            phases_completed=[],
            timestamp=start_time,
        )

        logger.info(f"Starting iteration {state.iteration_number} for {agent_name}")

        try:
            # Phase 1: Detection
            if start_phase == Phase.DETECT:
                result.detection_result = self._execute_with_retry(
                    agent_name, Phase.DETECT, self._execute_phase_1_detect
                )
                if not result.detection_result.has_problem:
                    logger.info(f"No problems detected for {agent_name}, skipping iteration")
                    result.success = True
                    result.phases_completed.append(Phase.DETECT)
                    return result
                result.phases_completed.append(Phase.DETECT)

            # Phase 2: Analysis
            if len(result.phases_completed) > 0 or start_phase == Phase.ANALYZE:
                result.analysis_result = self._execute_with_retry(
                    agent_name, Phase.ANALYZE, self._execute_phase_2_analyze
                )
                result.phases_completed.append(Phase.ANALYZE)

            # Phase 3: Strategy
            if len(result.phases_completed) >= 2 or start_phase == Phase.STRATEGY:
                result.strategy_result = self._execute_with_retry(
                    agent_name,
                    Phase.STRATEGY,
                    lambda name: self._execute_phase_3_strategy(name, result.analysis_result)
                )
                result.phases_completed.append(Phase.STRATEGY)

            # Phase 4: Experiment
            if len(result.phases_completed) >= PHASES_BEFORE_EXPERIMENT or start_phase == Phase.EXPERIMENT:
                result.experiment_result = self._execute_with_retry(
                    agent_name,
                    Phase.EXPERIMENT,
                    lambda name: self._execute_phase_4_experiment(name, result.strategy_result)
                )
                result.phases_completed.append(Phase.EXPERIMENT)

            # Phase 5: Deploy
            if len(result.phases_completed) >= PHASES_BEFORE_DEPLOY or start_phase == Phase.DEPLOY:
                if result.experiment_result and result.experiment_result.winner_config:
                    result.deployment_result = self._execute_with_retry(
                        agent_name,
                        Phase.DEPLOY,
                        lambda name: self._execute_phase_5_deploy(name, result.experiment_result)
                    )
                    result.phases_completed.append(Phase.DEPLOY)
                else:
                    logger.info(f"No winner from experiment, skipping deployment for {agent_name}")

            result.success = True
            logger.info(
                f"Iteration {state.iteration_number} completed for {agent_name}. "
                f"Phases: {[p.value for p in result.phases_completed]}"
            )

        except Exception as e:
            logger.error(f"Iteration failed for {agent_name}: {e}", exc_info=True)
            result.error = e
            result.success = False

        finally:
            # Calculate duration
            result.duration_seconds = (datetime.now(timezone.utc) - start_time).total_seconds()

            # Record metrics
            self.metrics_collector.record_iteration_complete(agent_name, result)

            # Mark iteration complete
            if result.success:
                self.state_manager.mark_completed(agent_name)
            else:
                self.state_manager.mark_failed(agent_name, str(result.error))

        return result

    def _execute_with_retry(self, agent_name: str, phase: Phase, phase_func):
        """Execute phase with retry logic."""
        attempt = 0
        last_error = None

        while attempt < self.config.max_retries_per_phase:
            attempt += 1

            try:
                self.metrics_collector.record_phase_start(agent_name, phase)
                logger.info(f"Executing {phase.value} for {agent_name} (attempt {attempt})")

                result = phase_func(agent_name)

                self.metrics_collector.record_phase_complete(agent_name, phase)
                logger.info(f"Phase {phase.value} completed for {agent_name}")

                return result

            except Exception as e:
                last_error = e
                self.metrics_collector.record_phase_error(agent_name, phase, e)

                recovery_action = self.error_recovery.handle_phase_error(
                    agent_name, phase, e, attempt
                )

                if recovery_action == RecoveryAction.RETRY:
                    self.error_recovery.wait_for_retry(attempt)
                    continue
                elif recovery_action == RecoveryAction.SKIP:
                    logger.warning(f"Skipping phase {phase.value} for {agent_name}")
                    raise
                elif recovery_action == RecoveryAction.FAIL:
                    logger.error(f"Failing iteration for {agent_name}")
                    raise
                else:
                    raise

        # Max retries exhausted
        logger.error(
            f"Max retries exhausted for {phase.value} ({agent_name}): {last_error}"
        )
        raise last_error

    def _execute_phase_1_detect(self, agent_name: str) -> DetectionResult:
        """Execute Phase 1: Problem Detection."""
        logger.info(f"Phase 1 (DETECT): Analyzing {agent_name} for improvements")

        improvements = self.improvement_detector.detect_improvements(
            agent_name=agent_name,
            window_hours=self.config.detection_window_hours,
        )

        has_problem = len(improvements) > 0

        if has_problem:
            improvement = improvements[0]  # Use first improvement
            logger.info(
                f"Improvement opportunity detected for {agent_name}: {improvement.strategy_name}"
            )
            return DetectionResult(
                has_problem=True,
                problem_type="improvement_opportunity",
                improvement_opportunity=improvement.strategy_name,
                baseline_metrics=None,  # Not available in this API
                current_metrics=None,
            )
        else:
            logger.info(f"No improvement opportunities detected for {agent_name}")
            return DetectionResult(has_problem=False)

    def _execute_phase_2_analyze(self, agent_name: str) -> AnalysisResult:
        """Execute Phase 2: Performance Analysis."""
        logger.info(f"Phase 2 (ANALYZE): Analyzing performance for {agent_name}")

        profile = self.performance_analyzer.analyze_agent_performance(
            agent_name=agent_name,
            window_hours=self.config.analysis_window_hours,
            min_executions=self.config.min_executions_for_analysis,
        )

        metrics_summary = {
            "total_executions": profile.total_executions,
            "quality_score": profile.get_metric("quality_score", "mean"),
            "cost_usd": profile.get_metric("cost_usd", "mean"),
            "duration_seconds": profile.get_metric("duration_seconds", "mean"),
        }

        quality_val = metrics_summary['quality_score']
        quality_str = f"{quality_val:.3f}" if quality_val is not None else "N/A"
        logger.info(
            f"Performance analysis for {agent_name}: "
            f"{profile.total_executions} executions, "
            f"quality={quality_str}"
        )

        return AnalysisResult(
            performance_profile=profile,
            metrics_summary=metrics_summary,
        )

    def _execute_phase_3_strategy(
        self,
        agent_name: str,
        analysis_result: AnalysisResult
    ) -> StrategyResult:
        """Execute Phase 3: Strategy Generation."""
        logger.info(f"Phase 3 (STRATEGY): Generating improvement strategies for {agent_name}")

        control_config = self.config_deployer.get_agent_config(agent_name)

        try:
            patterns = self.pattern_miner.mine_patterns(
                min_support=THRESHOLD_SMALL_COUNT,  # Require at least 5 observations
                min_confidence=PROB_HIGH,  # 70% confidence threshold
                min_win_rate=PROB_MEDIUM,  # Strategy wins at least 50% of time
                min_improvement=MIN_IMPROVEMENT_THRESHOLD,
                days_back=DAYS_90  # Last 90 days
            )
            logger.info(f"Mined {len(patterns)} patterns from experiment history")

            # Log top patterns for debugging
            for pattern in patterns[:TOP_PATTERNS_LIMIT]:
                logger.info(
                    f"  Pattern: {pattern.evidence['strategy_name']} for "
                    f"{pattern.evidence['problem_type']} "
                    f"(confidence={pattern.confidence:.2f})"
                )
        except Exception as e:
            logger.warning(f"Failed to mine patterns: {e}")
            patterns = []

        variant_configs = []

        if self.config.enable_model_variants:
            # Test different models
            models_to_test = ["gemma2:2b", "phi3:mini", "mistral:7b"]
            for model in models_to_test[:self.config.max_variants_per_experiment]:
                variant = control_config.copy()
                variant.inference["model"] = model
                variant_configs.append(variant)

        logger.info(
            f"Generated {len(variant_configs)} variant configs for {agent_name}"
        )

        return StrategyResult(
            control_config=control_config,
            variant_configs=variant_configs,
            strategy_name="model_variants",
            strategy_metadata={
                "models_tested": [v.inference["model"] for v in variant_configs],
                "patterns_considered": len(patterns),
                "problem_type": "quality_low"  # Default for now
            },
        )

    def _execute_phase_4_experiment(
        self,
        agent_name: str,
        strategy_result: StrategyResult
    ) -> ExperimentPhaseResult:
        """Execute Phase 4: Experimentation."""
        logger.info(f"Phase 4 (EXPERIMENT): Running A/B test for {agent_name}")

        experiment = self.experiment_orchestrator.create_experiment(
            agent_name=agent_name,
            control_config=strategy_result.control_config,
            variant_configs=strategy_result.variant_configs,
        )

        logger.info(
            f"Created experiment {experiment.id} with "
            f"{len(strategy_result.variant_configs)} variants for {agent_name}"
        )

        winner = self.experiment_orchestrator.get_winner(
            experiment_id=experiment.id,
            force=True,
        )

        if winner and winner.variant_id != "control":
            logger.info(
                f"Experiment {experiment.id} has winner: {winner.variant_id} "
                f"(improvement: {winner.quality_improvement:.1f}%, "
                f"confidence: {winner.confidence:.2f})"
            )

            result = ExperimentPhaseResult(
                experiment_id=experiment.id,
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

            # Track experiment decision outcome for observability
            if self.tracker:
                _track_winner_outcome(
                    self.tracker, agent_name, experiment.id, strategy_result, winner,
                )

            # Record strategy outcome for learning
            _record_winner_outcome(
                self.strategy_learning_store, strategy_result, agent_name,
                experiment.id, winner, self.config.target_samples_per_variant,
            )

            return result
        else:
            logger.info(f"No winner (control best or inconclusive) for {agent_name}")

            result = ExperimentPhaseResult(
                experiment_id=experiment.id,
                winner_variant_id=None,
                winner_config=None,
                statistical_significance=None,
                metrics_comparison=None,
            )

            # Track inconclusive experiment outcome
            if self.tracker:
                _track_inconclusive_outcome(
                    self.tracker, agent_name, experiment.id, strategy_result.strategy_name,
                )

            # Record strategy outcome (no improvement) for learning
            _record_no_winner_outcome(
                self.strategy_learning_store, strategy_result, agent_name,
                experiment.id, self.config.target_samples_per_variant,
            )

            return result

    def _execute_phase_5_deploy(
        self,
        agent_name: str,
        experiment_result: ExperimentPhaseResult
    ) -> DeploymentResult:
        """Execute Phase 5: Deployment."""
        logger.info(f"Phase 5 (DEPLOY): Deploying winner config for {agent_name}")

        if not experiment_result.winner_config:
            raise ValueError("No winner config to deploy")

        previous_config = self.config_deployer.get_agent_config(agent_name)

        if self.config.enable_auto_deploy:
            self.config_deployer.deploy(
                agent_name=agent_name,
                new_config=experiment_result.winner_config,
                experiment_id=experiment_result.experiment_id,
            )

            deployment = self.config_deployer.get_last_deployment(agent_name)

            logger.info(
                f"Deployed config {deployment.id} for {agent_name}. "
                f"Rollback monitoring: {self.config.enable_auto_rollback}"
            )

            result = DeploymentResult(
                deployment_id=deployment.id,
                deployed_config=experiment_result.winner_config,
                previous_config=previous_config,
                deployment_timestamp=deployment.deployed_at,
                rollback_monitoring_enabled=self.config.enable_auto_rollback,
            )

            # Track deployment decision outcome for observability
            if self.tracker:
                _track_deployment_outcome(
                    self.tracker, agent_name, deployment.id, experiment_result,
                    previous_config, self.config.enable_auto_rollback, deployment.deployed_at,
                )

            return result
        else:
            logger.info(f"Auto-deploy disabled, skipping deployment for {agent_name}")
            raise ValueError("Auto-deploy disabled")
