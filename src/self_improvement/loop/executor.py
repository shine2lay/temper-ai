"""
Loop executor for M5 Self-Improvement Loop.

Orchestrates phase execution with error handling and state management.
"""
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from sqlmodel import Session

from src.constants.durations import DAYS_90
from src.constants.limits import THRESHOLD_SMALL_COUNT
from src.constants.probabilities import PROB_HIGH, PROB_MEDIUM, PROB_VERY_HIGH
from src.self_improvement.data_models import StrategyOutcome
from src.self_improvement.deployment.deployer import ConfigDeployer
from src.self_improvement.deployment.rollback_monitor import (
    RegressionThresholds,
    RollbackMonitor,
)
from src.self_improvement.detection.improvement_detector import ImprovementDetector
from src.self_improvement.experiment_orchestrator import ExperimentOrchestrator
from src.self_improvement.pattern_mining import PatternMiner

# Import M5 phase components
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


class LoopExecutor:
    """
    Execute improvement loop iterations with phase orchestration.

    Coordinates all 5 phases of the M5 improvement cycle with error handling,
    retry logic, and state management.
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
        """
        Initialize loop executor with M4 safety stack integration.

        Args:
            coord_db: Coordination database
            obs_session: Observability database session
            config: Loop configuration
            state_manager: State manager instance
            error_recovery: Error recovery strategy
            metrics_collector: Metrics collector
            tracker: Optional ExecutionTracker for decision outcome tracking
            policy_engine: Optional ActionPolicyEngine for safety validation
            approval_workflow: Optional ApprovalWorkflow for high-impact changes
        """
        self.coord_db = coord_db
        self.obs_session = obs_session
        self.config = config
        self.state_manager = state_manager
        self.error_recovery = error_recovery
        self.metrics_collector = metrics_collector
        self.tracker = tracker

        # Initialize phase components
        self.performance_analyzer = PerformanceAnalyzer(obs_session)
        # SI-04: ImprovementDetector expects a Session, not PerformanceAnalyzer
        self.improvement_detector = ImprovementDetector(obs_session)
        self.experiment_orchestrator = ExperimentOrchestrator(
            session=obs_session,
            target_executions_per_variant=config.target_samples_per_variant
        )

        # Initialize ConfigDeployer with M4 safety stack integration
        self.config_deployer = ConfigDeployer(
            db=coord_db,
            policy_engine=policy_engine,
            approval_workflow=approval_workflow,
            enable_safety_checks=config.enable_safety_checks if hasattr(config, 'enable_safety_checks') else True
        )

        # Initialize strategy learning store for tracking outcomes
        self.strategy_learning_store = StrategyLearningStore(coord_db)

        # Initialize pattern miner for discovering recurring patterns
        self.pattern_miner = PatternMiner(self.strategy_learning_store)

        # Initialize rollback monitor with config thresholds
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
        """
        Execute complete improvement iteration.

        Args:
            agent_name: Name of agent
            start_phase: Phase to start from (default: DETECT)

        Returns:
            IterationResult with outcomes from all phases
        """
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
            if len(result.phases_completed) >= 3 or start_phase == Phase.EXPERIMENT:
                result.experiment_result = self._execute_with_retry(
                    agent_name,
                    Phase.EXPERIMENT,
                    lambda name: self._execute_phase_4_experiment(name, result.strategy_result)
                )
                result.phases_completed.append(Phase.EXPERIMENT)

            # Phase 5: Deploy
            if len(result.phases_completed) >= 4 or start_phase == Phase.DEPLOY:
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
        """
        Execute phase with retry logic.

        Args:
            agent_name: Name of agent
            phase: Phase being executed
            phase_func: Function to execute phase

        Returns:
            Phase result

        Raises:
            Exception: If all retries exhausted or permanent error
        """
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
        """
        Execute Phase 1: Problem Detection.

        Args:
            agent_name: Name of agent

        Returns:
            DetectionResult
        """
        logger.info(f"Phase 1 (DETECT): Analyzing {agent_name} for improvements")

        # Use ImprovementDetector to check for improvement opportunities
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
        """
        Execute Phase 2: Performance Analysis.

        Args:
            agent_name: Name of agent

        Returns:
            AnalysisResult
        """
        logger.info(f"Phase 2 (ANALYZE): Analyzing performance for {agent_name}")

        # Analyze current performance
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

        # SI-03: Guard against None quality_score to prevent TypeError on :.3f format
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
        """
        Execute Phase 3: Strategy Generation.

        Mines patterns from experiment history and uses them to inform
        strategy selection and variant generation.

        Args:
            agent_name: Name of agent
            analysis_result: Result from Phase 2

        Returns:
            StrategyResult
        """
        logger.info(f"Phase 3 (STRATEGY): Generating improvement strategies for {agent_name}")

        # Get current config (or create default)
        control_config = self.config_deployer.get_agent_config(agent_name)

        # Mine patterns from experiment history
        # This identifies which strategies have historically worked well
        try:
            patterns = self.pattern_miner.mine_patterns(
                min_support=THRESHOLD_SMALL_COUNT,  # Require at least 5 observations
                min_confidence=PROB_HIGH,  # 70% confidence threshold
                min_win_rate=PROB_MEDIUM,  # Strategy wins at least 50% of time
                min_improvement=0.03,  # At least 3% improvement
                days_back=DAYS_90  # Last 90 days
            )
            logger.info(f"Mined {len(patterns)} patterns from experiment history")

            # Log top patterns for debugging
            for pattern in patterns[:3]:
                logger.info(
                    f"  Pattern: {pattern.evidence['strategy_name']} for "
                    f"{pattern.evidence['problem_type']} "
                    f"(confidence={pattern.confidence:.2f})"
                )
        except Exception as e:
            logger.warning(f"Failed to mine patterns: {e}")
            patterns = []

        # Generate variant configs
        # For MVP, still use model variants but could be extended to use
        # pattern-informed strategy selection
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
        """
        Execute Phase 4: Experimentation.

        Args:
            agent_name: Name of agent
            strategy_result: Result from Phase 3

        Returns:
            ExperimentPhaseResult
        """
        logger.info(f"Phase 4 (EXPERIMENT): Running A/B test for {agent_name}")

        # Create experiment
        experiment = self.experiment_orchestrator.create_experiment(
            agent_name=agent_name,
            control_config=strategy_result.control_config,
            variant_configs=strategy_result.variant_configs,
        )

        logger.info(
            f"Created experiment {experiment.id} with "
            f"{len(strategy_result.variant_configs)} variants for {agent_name}"
        )

        # Wait for experiment completion (or check if complete)
        # For MVP, we assume experiment runs in background and check if complete
        # In production, this would poll or wait for completion

        # Determine winner (force analysis even if not enough samples)
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
                try:
                    self.tracker.track_decision_outcome(
                        decision_type="experiment_selection",
                        decision_data={
                            "agent_name": agent_name,
                            "experiment_id": experiment.id,
                            "control_config": strategy_result.control_config.model_dump() if hasattr(strategy_result.control_config, 'model_dump') else dict(strategy_result.control_config),
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
                        tags=["self_improvement", "experiment", strategy_result.strategy_name],
                        validation_method="statistical_analysis",
                    )
                except Exception as e:
                    logger.warning(f"Failed to track experiment outcome: {e}")

            # Record strategy outcome for learning
            try:
                import uuid

                # Infer problem type from strategy metadata or use generic
                problem_type = strategy_result.strategy_metadata.get("problem_type", "quality_low")

                outcome = StrategyOutcome(
                    id=f"outcome-{uuid.uuid4().hex[:12]}",
                    strategy_name=strategy_result.strategy_name,
                    problem_type=problem_type,
                    agent_name=agent_name,
                    experiment_id=experiment.id,
                    was_winner=True,
                    actual_quality_improvement=winner.quality_improvement / 100.0,  # Convert percentage to fraction
                    actual_speed_improvement=winner.speed_improvement / 100.0,
                    actual_cost_improvement=winner.cost_improvement / 100.0,
                    composite_score=winner.composite_score / 100.0,
                    confidence=winner.confidence,
                    sample_size=self.config.target_samples_per_variant * (len(strategy_result.variant_configs) + 1),  # Variants + control
                    context={
                        "control_config": strategy_result.control_config.to_dict(),
                        "winner_variant_id": winner.variant_id,
                        "statistical_significance": winner.is_statistically_significant,
                    },
                )

                self.strategy_learning_store.record_outcome(outcome)
                logger.info(
                    f"Recorded strategy outcome for {strategy_result.strategy_name}: "
                    f"{winner.quality_improvement:.1f}% quality improvement"
                )
            except Exception as e:
                logger.warning(f"Failed to record strategy outcome: {e}")

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
                try:
                    self.tracker.track_decision_outcome(
                        decision_type="experiment_selection",
                        decision_data={
                            "agent_name": agent_name,
                            "experiment_id": experiment.id,
                            "strategy": strategy_result.strategy_name,
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

            # Record strategy outcome (no improvement) for learning
            try:
                import uuid

                # Infer problem type from strategy metadata or use generic
                problem_type = strategy_result.strategy_metadata.get("problem_type", "quality_low")

                outcome = StrategyOutcome(
                    id=f"outcome-{uuid.uuid4().hex[:12]}",
                    strategy_name=strategy_result.strategy_name,
                    problem_type=problem_type,
                    agent_name=agent_name,
                    experiment_id=experiment.id,
                    was_winner=False,
                    actual_quality_improvement=0.0,  # No improvement
                    actual_speed_improvement=0.0,
                    actual_cost_improvement=0.0,
                    composite_score=0.0,
                    confidence=PROB_VERY_HIGH,  # Moderate confidence that control is best
                    sample_size=self.config.target_samples_per_variant * (len(strategy_result.variant_configs) + 1),
                    context={
                        "control_config": strategy_result.control_config.to_dict(),
                        "reason": "No statistically significant improvement",
                    },
                )

                self.strategy_learning_store.record_outcome(outcome)
                logger.info(
                    f"Recorded no-improvement outcome for {strategy_result.strategy_name}"
                )
            except Exception as e:
                logger.warning(f"Failed to record strategy outcome: {e}")

            return result

    def _execute_phase_5_deploy(
        self,
        agent_name: str,
        experiment_result: ExperimentPhaseResult
    ) -> DeploymentResult:
        """
        Execute Phase 5: Deployment.

        Args:
            agent_name: Name of agent
            experiment_result: Result from Phase 4

        Returns:
            DeploymentResult
        """
        logger.info(f"Phase 5 (DEPLOY): Deploying winner config for {agent_name}")

        if not experiment_result.winner_config:
            raise ValueError("No winner config to deploy")

        # Get previous config for rollback
        previous_config = self.config_deployer.get_agent_config(agent_name)

        # Deploy winner
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
                try:
                    self.tracker.track_decision_outcome(
                        decision_type="config_deployment",
                        decision_data={
                            "agent_name": agent_name,
                            "deployment_id": deployment.id,
                            "experiment_id": experiment_result.experiment_id,
                            "deployed_config": experiment_result.winner_config.model_dump() if hasattr(experiment_result.winner_config, 'model_dump') else dict(experiment_result.winner_config),
                            "previous_config": previous_config.model_dump() if hasattr(previous_config, 'model_dump') else dict(previous_config),
                            "rollback_monitoring_enabled": self.config.enable_auto_rollback,
                        },
                        outcome="success",
                        impact_metrics=experiment_result.metrics_comparison or {},
                        lessons_learned=f"Deployed winning config from experiment {experiment_result.experiment_id}",
                        should_repeat=True,
                        tags=["self_improvement", "deployment", "auto_deploy"],
                        validation_method="rollback_monitor" if self.config.enable_auto_rollback else "manual",
                        validation_timestamp=deployment.deployed_at,
                    )
                except Exception as e:
                    logger.warning(f"Failed to track deployment outcome: {e}")

            return result
        else:
            logger.info(f"Auto-deploy disabled, skipping deployment for {agent_name}")
            raise ValueError("Auto-deploy disabled")
