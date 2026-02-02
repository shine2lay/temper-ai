"""
Loop executor for M5 Self-Improvement Loop.

Orchestrates phase execution with error handling and state management.
"""
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional
from sqlmodel import Session

from .models import (
    Phase,
    DetectionResult,
    AnalysisResult,
    StrategyResult,
    ExperimentResult,
    DeploymentResult,
    IterationResult,
    RecoveryAction,
)
from .config import LoopConfig
from .state_manager import LoopStateManager
from .error_recovery import ErrorRecoveryStrategy
from .metrics import MetricsCollector

# Import M5 phase components
from src.self_improvement.performance_analyzer import PerformanceAnalyzer
from src.self_improvement.detection.improvement_detector import ImprovementDetector
from src.self_improvement.experiment_orchestrator import ExperimentOrchestrator
from src.self_improvement.deployment.deployer import ConfigDeployer
from src.self_improvement.deployment.rollback_monitor import (
    RollbackMonitor,
    RegressionThresholds,
)
from src.self_improvement.data_models import AgentConfig

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
    ):
        """
        Initialize loop executor.

        Args:
            coord_db: Coordination database
            obs_session: Observability database session
            config: Loop configuration
            state_manager: State manager instance
            error_recovery: Error recovery strategy
            metrics_collector: Metrics collector
        """
        self.coord_db = coord_db
        self.obs_session = obs_session
        self.config = config
        self.state_manager = state_manager
        self.error_recovery = error_recovery
        self.metrics_collector = metrics_collector

        # Initialize phase components
        self.performance_analyzer = PerformanceAnalyzer(obs_session)
        self.improvement_detector = ImprovementDetector(self.performance_analyzer)
        self.experiment_orchestrator = ExperimentOrchestrator(
            session=obs_session,
            target_executions_per_variant=config.target_samples_per_variant
        )
        self.config_deployer = ConfigDeployer(coord_db)

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

        logger.info(
            f"Performance analysis for {agent_name}: "
            f"{profile.total_executions} executions, "
            f"quality={metrics_summary['quality_score']:.3f}"
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

        Args:
            agent_name: Name of agent
            analysis_result: Result from Phase 2

        Returns:
            StrategyResult
        """
        logger.info(f"Phase 3 (STRATEGY): Generating improvement strategies for {agent_name}")

        # Get current config (or create default)
        control_config = self.config_deployer.get_agent_config(agent_name)

        # Generate variant configs (simplified - use model variants for now)
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
            strategy_metadata={"models_tested": [v.inference["model"] for v in variant_configs]},
        )

    def _execute_phase_4_experiment(
        self,
        agent_name: str,
        strategy_result: StrategyResult
    ) -> ExperimentResult:
        """
        Execute Phase 4: Experimentation.

        Args:
            agent_name: Name of agent
            strategy_result: Result from Phase 3

        Returns:
            ExperimentResult
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

        # Analyze results (force analysis even if not enough samples)
        analysis = self.experiment_orchestrator.analyze_experiment(
            experiment_id=experiment.id,
            force=True,  # Force analysis for testing
        )

        winner_variant_id = analysis.get("winner_variant_id")
        winner_config = None

        if winner_variant_id and winner_variant_id != "control":
            # Get winner config
            variant_index = int(winner_variant_id.split("_")[1])
            winner_config = strategy_result.variant_configs[variant_index]
            logger.info(f"Winner: {winner_variant_id} for {agent_name}")
        else:
            logger.info(f"No winner (control best) for {agent_name}")

        return ExperimentResult(
            experiment_id=experiment.id,
            winner_variant_id=winner_variant_id,
            winner_config=winner_config,
            statistical_significance=analysis.get("statistical_significance"),
            metrics_comparison=analysis.get("metrics_comparison"),
        )

    def _execute_phase_5_deploy(
        self,
        agent_name: str,
        experiment_result: ExperimentResult
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

            return DeploymentResult(
                deployment_id=deployment.id,
                deployed_config=experiment_result.winner_config,
                previous_config=previous_config,
                deployment_timestamp=deployment.deployed_at,
                rollback_monitoring_enabled=self.config.enable_auto_rollback,
            )
        else:
            logger.info(f"Auto-deploy disabled, skipping deployment for {agent_name}")
            raise ValueError("Auto-deploy disabled")
