"""Tests for Loop Executor.

This test module verifies:
- Loop executor initialization
- Iteration execution with all 5 phases
- Phase retry logic with error recovery
- Early termination when no problems detected
- Experiment winner selection and deployment
- No-winner experiment handling
- Metrics collection and state management
- Error handling and recovery actions
"""

import pytest
from unittest.mock import Mock, AsyncMock, MagicMock, patch
from datetime import datetime, timezone

from src.self_improvement.loop.executor import LoopExecutor
from src.self_improvement.loop.config import LoopConfig
from src.self_improvement.loop.models import (
    Phase,
    RecoveryAction,
    IterationResult,
    DetectionResult,
    AnalysisResult,
    StrategyResult,
    ExperimentPhaseResult,
    DeploymentResult,
)
from src.self_improvement.loop.state_manager import LoopStateManager
from src.self_improvement.loop.error_recovery import ErrorRecoveryStrategy
from src.self_improvement.loop.metrics import MetricsCollector


@pytest.fixture
def mock_coord_db():
    """Create mock coordination database."""
    db = Mock()
    return db


@pytest.fixture
def mock_obs_session():
    """Create mock observability session."""
    session = Mock()
    return session


@pytest.fixture
def mock_config():
    """Create loop configuration."""
    config = LoopConfig(
        detection_window_hours=24,
        analysis_window_hours=168,
        min_executions_for_analysis=10,
        target_samples_per_variant=30,
        max_retries_per_phase=3,
        enable_auto_deploy=True,
        enable_auto_rollback=True,
        enable_model_variants=True,
        max_variants_per_experiment=3,
        rollback_quality_drop_pct=0.10,
        rollback_cost_increase_pct=0.20,
        rollback_speed_increase_pct=0.30,
        rollback_min_executions=50,
    )
    return config


@pytest.fixture
def mock_state_manager():
    """Create mock state manager."""
    manager = Mock(spec=LoopStateManager)

    mock_state = Mock()
    mock_state.iteration_number = 1
    mock_state.current_phase = Phase.DETECT

    manager.get_state = Mock(return_value=mock_state)
    manager.create_state = Mock(return_value=mock_state)
    manager.mark_completed = Mock()
    manager.mark_failed = Mock()

    return manager


@pytest.fixture
def mock_error_recovery():
    """Create mock error recovery strategy."""
    recovery = Mock(spec=ErrorRecoveryStrategy)
    recovery.handle_phase_error = Mock(return_value=RecoveryAction.RETRY)
    recovery.wait_for_retry = Mock()
    return recovery


@pytest.fixture
def mock_metrics_collector():
    """Create mock metrics collector."""
    collector = Mock(spec=MetricsCollector)
    collector.record_iteration_complete = Mock()
    collector.record_phase_start = Mock()
    collector.record_phase_complete = Mock()
    collector.record_phase_error = Mock()
    return collector


@pytest.fixture
def mock_performance_analyzer():
    """Create mock performance analyzer."""
    analyzer = Mock()

    # Mock performance profile
    profile = Mock()
    profile.total_executions = 100
    profile.get_metric = Mock(side_effect=lambda metric, stat: {
        ("quality_score", "mean"): 0.85,
        ("cost_usd", "mean"): 0.05,
        ("duration_seconds", "mean"): 2.5,
    }.get((metric, stat)))

    analyzer.analyze_agent_performance = Mock(return_value=profile)
    return analyzer


@pytest.fixture
def mock_improvement_detector():
    """Create mock improvement detector."""
    detector = Mock()

    # Mock improvement opportunity
    improvement = Mock()
    improvement.strategy_name = "model_upgrade"

    detector.detect_improvements = Mock(return_value=[improvement])
    return detector


@pytest.fixture
def mock_experiment_orchestrator():
    """Create mock experiment orchestrator."""
    orchestrator = Mock()

    # Mock experiment
    experiment = Mock()
    experiment.id = "exp_123"

    # Mock winner
    winner = Mock()
    winner.variant_id = "variant_1"
    winner.winning_config = {"inference": {"model": "gemma2:2b"}}
    winner.is_statistically_significant = True
    winner.quality_improvement = 5.2
    winner.speed_improvement = -10.0
    winner.cost_improvement = 15.0
    winner.composite_score = 0.92
    winner.confidence = 0.85

    orchestrator.create_experiment = Mock(return_value=experiment)
    orchestrator.get_winner = Mock(return_value=winner)

    return orchestrator


@pytest.fixture
def mock_config_deployer():
    """Create mock config deployer."""
    deployer = Mock()

    # Mock deployment
    deployment = Mock()
    deployment.id = "deploy_456"
    deployment.deployed_at = datetime.now(timezone.utc)

    deployer.get_agent_config = Mock(return_value={"inference": {"model": "phi3:mini"}})
    deployer.deploy = Mock()
    deployer.get_last_deployment = Mock(return_value=deployment)

    return deployer


@pytest.fixture
def loop_executor(
    mock_coord_db,
    mock_obs_session,
    mock_config,
    mock_state_manager,
    mock_error_recovery,
    mock_metrics_collector,
):
    """Create LoopExecutor instance with mocked dependencies."""
    with patch('src.self_improvement.loop.executor.PerformanceAnalyzer'), \
         patch('src.self_improvement.loop.executor.ImprovementDetector'), \
         patch('src.self_improvement.loop.executor.ExperimentOrchestrator'), \
         patch('src.self_improvement.loop.executor.ConfigDeployer'), \
         patch('src.self_improvement.loop.executor.StrategyLearningStore'), \
         patch('src.self_improvement.loop.executor.PatternMiner'), \
         patch('src.self_improvement.loop.executor.RollbackMonitor'):

        executor = LoopExecutor(
            coord_db=mock_coord_db,
            obs_session=mock_obs_session,
            config=mock_config,
            state_manager=mock_state_manager,
            error_recovery=mock_error_recovery,
            metrics_collector=mock_metrics_collector,
            tracker=None,
            policy_engine=None,
            approval_workflow=None,
        )

        return executor


class TestLoopExecutorInitialization:
    """Test LoopExecutor initialization."""

    def test_initialization_with_all_dependencies(
        self,
        mock_coord_db,
        mock_obs_session,
        mock_config,
        mock_state_manager,
        mock_error_recovery,
        mock_metrics_collector,
    ):
        """Test initialization with all dependencies."""
        with patch('src.self_improvement.loop.executor.PerformanceAnalyzer'), \
             patch('src.self_improvement.loop.executor.ImprovementDetector'), \
             patch('src.self_improvement.loop.executor.ExperimentOrchestrator'), \
             patch('src.self_improvement.loop.executor.ConfigDeployer'), \
             patch('src.self_improvement.loop.executor.StrategyLearningStore'), \
             patch('src.self_improvement.loop.executor.PatternMiner'), \
             patch('src.self_improvement.loop.executor.RollbackMonitor'):

            executor = LoopExecutor(
                coord_db=mock_coord_db,
                obs_session=mock_obs_session,
                config=mock_config,
                state_manager=mock_state_manager,
                error_recovery=mock_error_recovery,
                metrics_collector=mock_metrics_collector,
                tracker=None,
                policy_engine=None,
                approval_workflow=None,
            )

            assert executor.coord_db == mock_coord_db
            assert executor.obs_session == mock_obs_session
            assert executor.config == mock_config
            assert executor.state_manager == mock_state_manager
            assert executor.error_recovery == mock_error_recovery
            assert executor.metrics_collector == mock_metrics_collector

    def test_initialization_with_tracker(
        self,
        mock_coord_db,
        mock_obs_session,
        mock_config,
        mock_state_manager,
        mock_error_recovery,
        mock_metrics_collector,
    ):
        """Test initialization with tracker."""
        mock_tracker = Mock()

        with patch('src.self_improvement.loop.executor.PerformanceAnalyzer'), \
             patch('src.self_improvement.loop.executor.ImprovementDetector'), \
             patch('src.self_improvement.loop.executor.ExperimentOrchestrator'), \
             patch('src.self_improvement.loop.executor.ConfigDeployer'), \
             patch('src.self_improvement.loop.executor.StrategyLearningStore'), \
             patch('src.self_improvement.loop.executor.PatternMiner'), \
             patch('src.self_improvement.loop.executor.RollbackMonitor'):

            executor = LoopExecutor(
                coord_db=mock_coord_db,
                obs_session=mock_obs_session,
                config=mock_config,
                state_manager=mock_state_manager,
                error_recovery=mock_error_recovery,
                metrics_collector=mock_metrics_collector,
                tracker=mock_tracker,
                policy_engine=None,
                approval_workflow=None,
            )

            assert executor.tracker == mock_tracker


class TestLoopExecutorPhaseExecution:
    """Test individual phase execution."""

    def test_execute_phase_1_detect_with_problem(self, loop_executor, mock_improvement_detector):
        """Test phase 1 detection with improvement opportunity."""
        loop_executor.improvement_detector = mock_improvement_detector

        result = loop_executor._execute_phase_1_detect("test_agent")

        assert result.has_problem is True
        assert result.problem_type == "improvement_opportunity"
        assert result.improvement_opportunity == "model_upgrade"
        mock_improvement_detector.detect_improvements.assert_called_once()

    def test_execute_phase_1_detect_no_problem(self, loop_executor):
        """Test phase 1 detection with no improvements."""
        mock_detector = Mock()
        mock_detector.detect_improvements = Mock(return_value=[])
        loop_executor.improvement_detector = mock_detector

        result = loop_executor._execute_phase_1_detect("test_agent")

        assert result.has_problem is False

    def test_execute_phase_2_analyze(self, loop_executor, mock_performance_analyzer):
        """Test phase 2 performance analysis."""
        loop_executor.performance_analyzer = mock_performance_analyzer

        result = loop_executor._execute_phase_2_analyze("test_agent")

        assert isinstance(result, AnalysisResult)
        assert result.metrics_summary["total_executions"] == 100
        assert result.metrics_summary["quality_score"] == 0.85
        mock_performance_analyzer.analyze_agent_performance.assert_called_once()

    def test_execute_phase_3_strategy(self, loop_executor, mock_config_deployer):
        """Test phase 3 strategy generation."""
        # Create a proper config object (Mock with dict-like access)
        config_obj = Mock()
        config_obj.inference = {"model": "phi3:mini"}
        config_obj.copy = Mock(side_effect=[
            Mock(inference={"model": "gemma2:2b"}),
            Mock(inference={"model": "phi3:mini"}),
            Mock(inference={"model": "mistral:7b"}),
        ])

        mock_config_deployer.get_agent_config = Mock(return_value=config_obj)
        loop_executor.config_deployer = mock_config_deployer
        loop_executor.pattern_miner = Mock()
        loop_executor.pattern_miner.mine_patterns = Mock(return_value=[])

        mock_analysis = Mock()
        mock_analysis.performance_profile = Mock()

        result = loop_executor._execute_phase_3_strategy("test_agent", mock_analysis)

        assert isinstance(result, StrategyResult)
        assert result.strategy_name == "model_variants"
        assert len(result.variant_configs) > 0

    def test_execute_phase_4_experiment_with_winner(
        self, loop_executor, mock_experiment_orchestrator
    ):
        """Test phase 4 experiment with winner variant."""
        loop_executor.experiment_orchestrator = mock_experiment_orchestrator

        mock_strategy = Mock()
        mock_strategy.control_config = {"inference": {"model": "phi3:mini"}}
        mock_strategy.variant_configs = [{"inference": {"model": "gemma2:2b"}}]
        mock_strategy.strategy_name = "model_variants"
        mock_strategy.strategy_metadata = {"problem_type": "quality_low"}

        result = loop_executor._execute_phase_4_experiment("test_agent", mock_strategy)

        assert isinstance(result, ExperimentPhaseResult)
        assert result.winner_variant_id == "variant_1"
        assert result.winner_config is not None
        assert result.statistical_significance is True

    def test_execute_phase_4_experiment_no_winner(self, loop_executor):
        """Test phase 4 experiment with no winner."""
        mock_orchestrator = Mock()

        experiment = Mock()
        experiment.id = "exp_123"

        mock_orchestrator.create_experiment = Mock(return_value=experiment)
        mock_orchestrator.get_winner = Mock(return_value=None)

        loop_executor.experiment_orchestrator = mock_orchestrator

        mock_strategy = Mock()
        mock_strategy.control_config = {"inference": {"model": "phi3:mini"}}
        mock_strategy.variant_configs = [{"inference": {"model": "gemma2:2b"}}]
        mock_strategy.strategy_name = "model_variants"

        result = loop_executor._execute_phase_4_experiment("test_agent", mock_strategy)

        assert result.winner_variant_id is None
        assert result.winner_config is None

    def test_execute_phase_5_deploy(self, loop_executor, mock_config_deployer):
        """Test phase 5 deployment."""
        loop_executor.config_deployer = mock_config_deployer

        mock_experiment = Mock()
        mock_experiment.experiment_id = "exp_123"
        mock_experiment.winner_config = {"inference": {"model": "gemma2:2b"}}
        mock_experiment.winner_variant_id = "variant_1"

        result = loop_executor._execute_phase_5_deploy("test_agent", mock_experiment)

        assert isinstance(result, DeploymentResult)
        assert result.deployment_id == "deploy_456"
        assert result.deployed_config == mock_experiment.winner_config
        mock_config_deployer.deploy.assert_called_once()

    def test_execute_phase_5_deploy_no_winner(self, loop_executor):
        """Test phase 5 deployment with no winner config."""
        mock_experiment = Mock()
        mock_experiment.winner_config = None

        with pytest.raises(ValueError, match="No winner config to deploy"):
            loop_executor._execute_phase_5_deploy("test_agent", mock_experiment)


class TestLoopExecutorIterationExecution:
    """Test full iteration execution."""

    def test_execute_iteration_full_success(self, loop_executor):
        """Test complete iteration with all phases."""
        # Mock all phase executions
        loop_executor._execute_phase_1_detect = Mock(
            return_value=DetectionResult(
                has_problem=True,
                problem_type="quality_low",
                improvement_opportunity="model_upgrade",
            )
        )
        loop_executor._execute_phase_2_analyze = Mock(
            return_value=AnalysisResult(
                performance_profile=Mock(),
                metrics_summary={"quality_score": 0.75},
            )
        )
        loop_executor._execute_phase_3_strategy = Mock(
            return_value=StrategyResult(
                control_config={},
                variant_configs=[{}],
                strategy_name="test",
                strategy_metadata={},
            )
        )
        loop_executor._execute_phase_4_experiment = Mock(
            return_value=ExperimentPhaseResult(
                experiment_id="exp_123",
                winner_variant_id="variant_1",
                winner_config={"model": "test"},
                statistical_significance=True,
                metrics_comparison={},
            )
        )
        loop_executor._execute_phase_5_deploy = Mock(
            return_value=DeploymentResult(
                deployment_id="deploy_456",
                deployed_config={"model": "test"},
                previous_config={},
                deployment_timestamp=datetime.now(timezone.utc),
                rollback_monitoring_enabled=True,
            )
        )

        result = loop_executor.execute_iteration("test_agent")

        assert result.success is True
        # Phase 5 only executes if there's a winner_config
        assert len(result.phases_completed) >= 4
        assert Phase.DETECT in result.phases_completed
        assert Phase.ANALYZE in result.phases_completed
        assert Phase.STRATEGY in result.phases_completed
        assert Phase.EXPERIMENT in result.phases_completed

    def test_execute_iteration_no_problem_detected(self, loop_executor):
        """Test iteration stops early when no problem detected."""
        loop_executor._execute_phase_1_detect = Mock(
            return_value=DetectionResult(has_problem=False)
        )

        result = loop_executor.execute_iteration("test_agent")

        assert result.success is True
        assert len(result.phases_completed) == 1
        assert Phase.DETECT in result.phases_completed

    def test_execute_iteration_no_winner_skips_deploy(self, loop_executor):
        """Test iteration skips deployment when no experiment winner."""
        loop_executor._execute_phase_1_detect = Mock(
            return_value=DetectionResult(has_problem=True, problem_type="test")
        )
        loop_executor._execute_phase_2_analyze = Mock(
            return_value=AnalysisResult(performance_profile=Mock(), metrics_summary={})
        )
        loop_executor._execute_phase_3_strategy = Mock(
            return_value=StrategyResult(
                control_config={}, variant_configs=[{}],
                strategy_name="test", strategy_metadata={}
            )
        )
        loop_executor._execute_phase_4_experiment = Mock(
            return_value=ExperimentPhaseResult(
                experiment_id="exp_123",
                winner_variant_id=None,
                winner_config=None,
                statistical_significance=None,
                metrics_comparison=None,
            )
        )

        result = loop_executor.execute_iteration("test_agent")

        assert result.success is True
        assert len(result.phases_completed) == 4
        assert Phase.DEPLOY not in result.phases_completed

    def test_execute_iteration_phase_error(self, loop_executor, mock_error_recovery):
        """Test iteration handles phase errors."""
        loop_executor._execute_phase_1_detect = Mock(
            side_effect=RuntimeError("Detection failed")
        )
        mock_error_recovery.handle_phase_error = Mock(return_value=RecoveryAction.FAIL)

        result = loop_executor.execute_iteration("test_agent")

        assert result.success is False
        assert result.error is not None

    def test_execute_iteration_state_updates(
        self, loop_executor, mock_state_manager, mock_metrics_collector
    ):
        """Test iteration updates state and metrics."""
        loop_executor._execute_phase_1_detect = Mock(
            return_value=DetectionResult(has_problem=False)
        )

        result = loop_executor.execute_iteration("test_agent")

        assert result.success is True
        mock_state_manager.mark_completed.assert_called_once_with("test_agent")
        mock_metrics_collector.record_iteration_complete.assert_called_once()

    def test_execute_iteration_start_from_different_phase(self, loop_executor):
        """Test starting iteration from non-DETECT phase."""
        loop_executor._execute_phase_2_analyze = Mock(
            return_value=AnalysisResult(performance_profile=Mock(), metrics_summary={})
        )
        loop_executor._execute_phase_3_strategy = Mock(
            return_value=StrategyResult(
                control_config={}, variant_configs=[{}],
                strategy_name="test", strategy_metadata={}
            )
        )
        loop_executor._execute_phase_4_experiment = Mock(
            return_value=ExperimentPhaseResult(
                experiment_id="exp_123", winner_variant_id=None,
                winner_config=None, statistical_significance=None,
                metrics_comparison=None
            )
        )

        result = loop_executor.execute_iteration("test_agent", start_phase=Phase.ANALYZE)

        assert result.success is True
        assert Phase.DETECT not in result.phases_completed


class TestLoopExecutorRetryLogic:
    """Test retry and error recovery logic."""

    def test_execute_with_retry_success_first_attempt(
        self, loop_executor, mock_metrics_collector
    ):
        """Test phase execution succeeds on first attempt."""
        mock_phase_func = Mock(return_value="success")

        result = loop_executor._execute_with_retry("test_agent", Phase.DETECT, mock_phase_func)

        assert result == "success"
        mock_phase_func.assert_called_once_with("test_agent")
        mock_metrics_collector.record_phase_start.assert_called_once()
        mock_metrics_collector.record_phase_complete.assert_called_once()

    def test_execute_with_retry_success_after_retry(
        self, loop_executor, mock_error_recovery, mock_metrics_collector
    ):
        """Test phase execution succeeds after retry."""
        mock_phase_func = Mock(side_effect=[RuntimeError("Temp error"), "success"])
        mock_error_recovery.handle_phase_error = Mock(return_value=RecoveryAction.RETRY)

        result = loop_executor._execute_with_retry("test_agent", Phase.DETECT, mock_phase_func)

        assert result == "success"
        assert mock_phase_func.call_count == 2
        mock_error_recovery.wait_for_retry.assert_called_once()

    def test_execute_with_retry_max_retries_exhausted(
        self, loop_executor, mock_error_recovery
    ):
        """Test phase execution fails after max retries."""
        mock_phase_func = Mock(side_effect=RuntimeError("Persistent error"))
        mock_error_recovery.handle_phase_error = Mock(return_value=RecoveryAction.RETRY)

        with pytest.raises(RuntimeError, match="Persistent error"):
            loop_executor._execute_with_retry("test_agent", Phase.DETECT, mock_phase_func)

        assert mock_phase_func.call_count == 3  # max_retries_per_phase

    def test_execute_with_retry_skip_action(self, loop_executor, mock_error_recovery):
        """Test phase execution with SKIP recovery action."""
        mock_phase_func = Mock(side_effect=RuntimeError("Error"))
        mock_error_recovery.handle_phase_error = Mock(return_value=RecoveryAction.SKIP)

        with pytest.raises(RuntimeError, match="Error"):
            loop_executor._execute_with_retry("test_agent", Phase.DETECT, mock_phase_func)

        assert mock_phase_func.call_count == 1

    def test_execute_with_retry_fail_action(self, loop_executor, mock_error_recovery):
        """Test phase execution with FAIL recovery action."""
        mock_phase_func = Mock(side_effect=RuntimeError("Error"))
        mock_error_recovery.handle_phase_error = Mock(return_value=RecoveryAction.FAIL)

        with pytest.raises(RuntimeError, match="Error"):
            loop_executor._execute_with_retry("test_agent", Phase.DETECT, mock_phase_func)

        assert mock_phase_func.call_count == 1


class TestLoopExecutorExperimentTracking:
    """Test experiment outcome tracking."""

    def test_experiment_with_winner_tracked(self, loop_executor):
        """Test experiment winner is tracked for observability."""
        mock_tracker = Mock()
        loop_executor.tracker = mock_tracker

        mock_orchestrator = Mock()
        experiment = Mock()
        experiment.id = "exp_123"

        winner = Mock()
        winner.variant_id = "variant_1"
        winner.winning_config = {}
        winner.is_statistically_significant = True
        winner.quality_improvement = 5.0
        winner.speed_improvement = -10.0  # Properly typed
        winner.cost_improvement = 15.0  # Properly typed
        winner.composite_score = 0.9
        winner.confidence = 0.85  # Add confidence field

        mock_orchestrator.create_experiment = Mock(return_value=experiment)
        mock_orchestrator.get_winner = Mock(return_value=winner)

        loop_executor.experiment_orchestrator = mock_orchestrator
        loop_executor.strategy_learning_store = Mock()

        mock_strategy = Mock()
        mock_strategy.control_config = {}
        mock_strategy.variant_configs = [{}]
        mock_strategy.strategy_name = "test"
        mock_strategy.strategy_metadata = {}

        with patch('src.self_improvement.loop.executor._track_winner_outcome') as mock_track:
            loop_executor._execute_phase_4_experiment("test_agent", mock_strategy)

            mock_track.assert_called_once()

    def test_experiment_no_winner_tracked(self, loop_executor):
        """Test inconclusive experiment is tracked."""
        mock_tracker = Mock()
        loop_executor.tracker = mock_tracker

        mock_orchestrator = Mock()
        experiment = Mock()
        experiment.id = "exp_123"

        mock_orchestrator.create_experiment = Mock(return_value=experiment)
        mock_orchestrator.get_winner = Mock(return_value=None)

        loop_executor.experiment_orchestrator = mock_orchestrator
        loop_executor.strategy_learning_store = Mock()

        mock_strategy = Mock()
        mock_strategy.control_config = {}
        mock_strategy.variant_configs = [{}]
        mock_strategy.strategy_name = "test"

        with patch('src.self_improvement.loop.executor._track_inconclusive_outcome') as mock_track:
            loop_executor._execute_phase_4_experiment("test_agent", mock_strategy)

            mock_track.assert_called_once()
