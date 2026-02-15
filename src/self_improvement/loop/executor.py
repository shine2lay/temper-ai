"""Loop executor for M5 Self-Improvement Loop.

See _executor_helpers.py for extracted tracking/recording logic.
"""
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from sqlmodel import Session

from src.shared.constants.durations import DAYS_90
from src.shared.constants.limits import THRESHOLD_SMALL_COUNT
from src.shared.constants.probabilities import PROB_HIGH, PROB_MEDIUM
from src.self_improvement.deployment.deployer import ConfigDeployer
from src.self_improvement.deployment.rollback_monitor import (
    RegressionThresholds,
    RollbackMonitor,
)
from src.self_improvement.detection.improvement_detector import ImprovementDetector
from src.self_improvement.experiment_orchestrator import ExperimentOrchestrator
from src.self_improvement.loop._executor_helpers import (
    DeployPhaseParams,
    StrategyPhaseParams,
)

# Helper functions extracted to reduce class size
from src.self_improvement.loop._executor_helpers import (
    create_no_winner_result as _create_no_winner_result,
)
from src.self_improvement.loop._executor_helpers import (
    create_winner_result as _create_winner_result,
)
from src.self_improvement.loop._executor_helpers import (
    execute_deploy_phase as _execute_deploy_phase,
)
from src.self_improvement.loop._executor_helpers import (
    execute_strategy_phase as _execute_strategy_phase,
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

from dataclasses import dataclass


@dataclass
class ExecutorConfig:
    """Configuration for LoopExecutor initialization."""
    coord_db: Any
    obs_session: Session
    config: LoopConfig
    state_manager: LoopStateManager
    error_recovery: ErrorRecoveryStrategy
    metrics_collector: MetricsCollector
    tracker: Optional[Any] = None
    policy_engine: Optional[Any] = None
    approval_workflow: Optional[Any] = None

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

    def __init__(self, config: ExecutorConfig) -> None:
        """Initialize loop executor with configuration."""
        self.coord_db = config.coord_db
        self.obs_session = config.obs_session
        self.config = config.config
        self.state_manager = config.state_manager
        self.error_recovery = config.error_recovery
        self.metrics_collector = config.metrics_collector
        self.tracker = config.tracker

        # Initialize core components
        self._init_analyzers_and_orchestrators()
        self._init_deployer_and_monitor(config.policy_engine, config.approval_workflow)
        self._init_learning_components()

    def _init_analyzers_and_orchestrators(self) -> None:
        """Initialize analyzers and orchestrators."""
        self.performance_analyzer = PerformanceAnalyzer(self.obs_session)
        self.improvement_detector = ImprovementDetector(self.obs_session)
        self.experiment_orchestrator = ExperimentOrchestrator(
            session=self.obs_session,
            target_executions_per_variant=self.config.target_samples_per_variant
        )

    def _init_deployer_and_monitor(
        self,
        policy_engine: Optional[Any],
        approval_workflow: Optional[Any]
    ) -> None:
        """Initialize deployer and rollback monitor."""
        enable_safety = (
            self.config.enable_safety_checks
            if hasattr(self.config, 'enable_safety_checks')
            else True
        )
        self.config_deployer = ConfigDeployer(
            db=self.coord_db,
            policy_engine=policy_engine,
            approval_workflow=approval_workflow,
            enable_safety_checks=enable_safety
        )

        rollback_thresholds = RegressionThresholds(
            quality_drop_pct=self.config.rollback_quality_drop_pct,
            cost_increase_pct=self.config.rollback_cost_increase_pct,
            speed_increase_pct=self.config.rollback_speed_increase_pct,
            min_executions=self.config.rollback_min_executions,
        )
        self.rollback_monitor = RollbackMonitor(
            self.performance_analyzer,
            self.config_deployer,
            rollback_thresholds,
        )

    def _init_learning_components(self) -> None:
        """Initialize learning and pattern mining components."""
        self.strategy_learning_store = StrategyLearningStore(self.coord_db)
        self.pattern_miner = PatternMiner(self.strategy_learning_store)

    def _run_detection_phase(
        self,
        agent_name: str,
        result: IterationResult,
        start_phase: Phase
    ) -> bool:
        """Run detection phase. Returns True if should continue."""
        if start_phase == Phase.DETECT:
            result.detection_result = self._execute_with_retry(
                agent_name, Phase.DETECT, self._execute_phase_1_detect
            )
            if not result.detection_result.has_problem:
                logger.info(f"No problems detected for {agent_name}, skipping iteration")
                result.success = True
                result.phases_completed.append(Phase.DETECT)
                return False
            result.phases_completed.append(Phase.DETECT)
        return True

    def _run_analysis_phase(
        self,
        agent_name: str,
        result: IterationResult,
        start_phase: Phase
    ) -> None:
        """Run analysis phase."""
        if len(result.phases_completed) > 0 or start_phase == Phase.ANALYZE:
            result.analysis_result = self._execute_with_retry(
                agent_name, Phase.ANALYZE, self._execute_phase_2_analyze
            )
            result.phases_completed.append(Phase.ANALYZE)

    def _run_strategy_phase(
        self,
        agent_name: str,
        result: IterationResult,
        start_phase: Phase
    ) -> None:
        """Run strategy generation phase."""
        if len(result.phases_completed) >= 2 or start_phase == Phase.STRATEGY:
            if result.analysis_result is None:
                raise ValueError("Cannot execute strategy phase without analysis result")
            analysis_result = result.analysis_result
            result.strategy_result = self._execute_with_retry(
                agent_name,
                Phase.STRATEGY,
                lambda name: self._execute_phase_3_strategy(name, analysis_result)
            )
            result.phases_completed.append(Phase.STRATEGY)

    def _run_experiment_and_deploy_phases(
        self,
        agent_name: str,
        result: IterationResult,
        start_phase: Phase
    ) -> None:
        """Run experiment and deployment phases."""
        # Phase 4: Experiment
        if len(result.phases_completed) >= PHASES_BEFORE_EXPERIMENT or start_phase == Phase.EXPERIMENT:
            if result.strategy_result is None:
                raise ValueError("Cannot execute experiment phase without strategy result")
            strategy_result = result.strategy_result
            result.experiment_result = self._execute_with_retry(
                agent_name,
                Phase.EXPERIMENT,
                lambda name: self._execute_phase_4_experiment(name, strategy_result)
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
            # Run all phases
            if not self._run_detection_phase(agent_name, result, start_phase):
                return result

            self._run_analysis_phase(agent_name, result, start_phase)
            self._run_strategy_phase(agent_name, result, start_phase)
            self._run_experiment_and_deploy_phases(agent_name, result, start_phase)

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
            result.duration_seconds = (datetime.now(timezone.utc) - start_time).total_seconds()
            self.metrics_collector.record_iteration_complete(agent_name, result)

            if result.success:
                self.state_manager.mark_completed(agent_name)
            else:
                self.state_manager.mark_failed(agent_name, str(result.error))

        return result

    def _execute_with_retry(self, agent_name: str, phase: Phase, phase_func: Any) -> Any:
        """Execute phase with retry logic."""
        attempt = 0
        last_error: Optional[Exception] = None

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
        if last_error is None:
            # This should never happen, but handle it just in case
            last_error = RuntimeError(f"Max retries exhausted for {phase.value} ({agent_name}) with no error captured")
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
        """Execute Phase 3: Strategy Generation (delegates to helper)."""
        params = StrategyPhaseParams(
            agent_name=agent_name,
            analysis_result=analysis_result,
            config_deployer=self.config_deployer,
            pattern_miner=self.pattern_miner,
            enable_model_variants=self.config.enable_model_variants,
            max_variants_per_experiment=self.config.max_variants_per_experiment,
            min_support=THRESHOLD_SMALL_COUNT,
            min_confidence=PROB_HIGH,
            min_win_rate=PROB_MEDIUM,
            min_improvement=MIN_IMPROVEMENT_THRESHOLD,
            days_back=DAYS_90,
            top_patterns_limit=TOP_PATTERNS_LIMIT,
        )
        return _execute_strategy_phase(params)

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
            return _create_winner_result(
                experiment.id, winner, agent_name, strategy_result,
                self.tracker, self.strategy_learning_store,
                self.config.target_samples_per_variant,
            )
        else:
            return _create_no_winner_result(
                experiment.id, agent_name, strategy_result,
                self.tracker, self.strategy_learning_store,
                self.config.target_samples_per_variant,
            )

    def _execute_phase_5_deploy(
        self,
        agent_name: str,
        experiment_result: ExperimentPhaseResult
    ) -> DeploymentResult:
        """Execute Phase 5: Deployment (delegates to helper)."""
        params = DeployPhaseParams(
            agent_name=agent_name,
            experiment_result=experiment_result,
            config_deployer=self.config_deployer,
            enable_auto_deploy=self.config.enable_auto_deploy,
            enable_auto_rollback=self.config.enable_auto_rollback,
            tracker=self.tracker,
        )
        return _execute_deploy_phase(params)
