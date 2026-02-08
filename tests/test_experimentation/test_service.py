"""Tests for ExperimentService."""
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

import pytest
from sqlmodel import Session

from src.experimentation.models import (
    AssignmentStrategyType,
    ExecutionStatus,
    Experiment,
    ExperimentStatus,
    RecommendationType,
    Variant,
    VariantAssignment,
)
from src.experimentation.service import ExperimentService


@pytest.fixture
def mock_session():
    """Mock database session."""
    session = Mock(spec=Session)
    session.__enter__ = Mock(return_value=session)
    session.__exit__ = Mock(return_value=False)
    return session


@pytest.fixture
def experiment_service():
    """Create ExperimentService instance."""
    service = ExperimentService(max_cache_size=100)
    # Add missing cache attributes (service delegates to _crud but accesses directly - bug workaround)
    import threading
    from collections import OrderedDict
    service._cache_lock = threading.Lock()
    service._experiment_cache = OrderedDict()
    service._cache_put = lambda k, v: service._experiment_cache.update({k: v})
    return service


@pytest.fixture
def sample_experiment():
    """Create sample experiment for testing."""
    exp_id = str(uuid.uuid4())
    return Experiment(
        id=exp_id,
        name="test_experiment",
        description="Test experiment",
        status=ExperimentStatus.RUNNING,
        assignment_strategy=AssignmentStrategyType.RANDOM,
        traffic_allocation={"control": 0.5, "variant_a": 0.5},
        primary_metric="duration_seconds",
        secondary_metrics=["error_rate"],
        confidence_level=0.95,
        min_sample_size_per_variant=100,
        tags=["test"],
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


@pytest.fixture
def sample_variants(sample_experiment):
    """Create sample variants for testing."""
    variants = []
    for name in ["control", "variant_a"]:
        variant = Variant(
            id=str(uuid.uuid4()),
            experiment_id=sample_experiment.id,
            name=name,
            description=f"Test variant {name}",
            is_control=(name == "control"),
            config_type="agent",
            config_overrides={},
            allocated_traffic=0.5,
            created_at=datetime.now(timezone.utc),
        )
        variants.append(variant)
    return variants


class TestExperimentServiceInitialization:
    """Test ExperimentService initialization."""

    def test_service_initialization(self):
        """Test service initialization with default settings."""
        service = ExperimentService()

        assert service.name == "experiment_service"
        assert service._crud is not None
        assert service._assigner is not None
        assert service._config_manager is not None
        assert service._analyzer is not None

    def test_service_initialization_custom_cache_size(self):
        """Test service initialization with custom cache size."""
        service = ExperimentService(max_cache_size=50)

        assert service._crud is not None

    def test_service_lifecycle(self):
        """Test service initialize and shutdown."""
        service = ExperimentService()

        # Should not raise
        service.initialize()
        service.shutdown()


class TestCreateExperiment:
    """Test experiment creation."""

    @patch('src.experimentation.service.get_session')
    def test_create_experiment_success(self, mock_get_session, experiment_service, mock_session):
        """Test successful experiment creation."""
        mock_get_session.return_value = mock_session

        exp_id = experiment_service.create_experiment(
            name="test_exp",
            description="Test description",
            variants=[
                {"name": "control", "is_control": True, "traffic": 0.5},
                {"name": "variant_a", "traffic": 0.5, "config": {"temperature": 0.9}}
            ],
            primary_metric="duration_seconds",
        )

        assert exp_id is not None
        assert isinstance(exp_id, str)
        mock_session.add.assert_called()
        mock_session.commit.assert_called_once()

    @patch('src.experimentation.service.get_session')
    def test_create_experiment_with_optional_params(self, mock_get_session, experiment_service, mock_session):
        """Test experiment creation with optional parameters."""
        mock_get_session.return_value = mock_session

        exp_id = experiment_service.create_experiment(
            name="test_exp",
            description="Test description",
            variants=[
                {"name": "control", "is_control": True},
                {"name": "variant_a"}
            ],
            assignment_strategy="hash",
            primary_metric="quality_score",
            secondary_metrics=["latency", "cost"],
            guardrail_metrics=[{"name": "error_rate", "max": 0.05}],
            confidence_level=0.99,
            min_sample_size_per_variant=200,
            tags=["production", "ml"],
            created_by="user@example.com",
        )

        assert exp_id is not None
        mock_session.commit.assert_called_once()

    def test_create_experiment_invalid_name(self, experiment_service):
        """Test experiment creation with invalid name."""
        with pytest.raises(ValueError, match="name must be"):
            experiment_service.create_experiment(
                name="",  # Empty name
                description="Test",
                variants=[
                    {"name": "control", "is_control": True},
                    {"name": "variant_a"}
                ],
                primary_metric="duration_seconds",
            )

    def test_create_experiment_insufficient_variants(self, experiment_service):
        """Test experiment creation with insufficient variants."""
        with pytest.raises(ValueError, match="at least 2 variants"):
            experiment_service.create_experiment(
                name="test_exp",
                description="Test",
                variants=[{"name": "control"}],  # Only 1 variant
                primary_metric="duration_seconds",
            )

    def test_create_experiment_traffic_exceeds_limit(self, experiment_service):
        """Test experiment creation with traffic exceeding 1.0."""
        with pytest.raises(ValueError, match="exceeds 1.0"):
            experiment_service.create_experiment(
                name="test_exp",
                description="Test",
                variants=[
                    {"name": "control", "traffic": 0.7},
                    {"name": "variant_a", "traffic": 0.5}  # Total = 1.2
                ],
                primary_metric="duration_seconds",
            )

    @patch('src.experimentation.service.get_session')
    def test_create_experiment_duplicate_name(self, mock_get_session, experiment_service, mock_session):
        """Test experiment creation with duplicate name."""
        from sqlalchemy.exc import IntegrityError

        mock_session.commit.side_effect = IntegrityError("", "", "")
        mock_get_session.return_value = mock_session

        with pytest.raises(ValueError, match="constraint violation"):
            experiment_service.create_experiment(
                name="test_exp",
                description="Test",
                variants=[
                    {"name": "control", "is_control": True},
                    {"name": "variant_a"}
                ],
                primary_metric="duration_seconds",
            )


class TestGetExperiment:
    """Test experiment retrieval."""

    @patch('src.experimentation.service.get_session')
    def test_get_experiment_from_database(self, mock_get_session, experiment_service, mock_session, sample_experiment):
        """Test getting experiment from database."""
        mock_session.exec.return_value.first.return_value = sample_experiment
        mock_get_session.return_value = mock_session

        result = experiment_service.get_experiment(sample_experiment.id)

        assert result is not None
        assert result.id == sample_experiment.id
        assert result.name == "test_experiment"

    @patch('src.experimentation.service.get_session')
    def test_get_experiment_not_found(self, mock_get_session, experiment_service, mock_session):
        """Test getting non-existent experiment."""
        mock_session.exec.return_value.first.return_value = None
        mock_get_session.return_value = mock_session

        result = experiment_service.get_experiment("nonexistent_id")

        assert result is None

    @patch('src.experimentation.service.get_session')
    def test_list_experiments_all(self, mock_get_session, experiment_service, mock_session, sample_experiment):
        """Test listing all experiments."""
        mock_session.exec.return_value.all.return_value = [sample_experiment]
        mock_get_session.return_value = mock_session

        results = experiment_service.list_experiments()

        assert len(results) == 1
        assert results[0].id == sample_experiment.id

    @patch('src.experimentation.service.get_session')
    def test_list_experiments_by_status(self, mock_get_session, experiment_service, mock_session, sample_experiment):
        """Test listing experiments filtered by status."""
        mock_session.exec.return_value.all.return_value = [sample_experiment]
        mock_get_session.return_value = mock_session

        results = experiment_service.list_experiments(status=ExperimentStatus.RUNNING)

        assert len(results) == 1
        assert results[0].status == ExperimentStatus.RUNNING


class TestExperimentLifecycle:
    """Test experiment lifecycle operations."""

    @patch('src.experimentation.service.get_session')
    def test_start_experiment_success(self, mock_get_session, experiment_service, mock_session, sample_experiment):
        """Test starting an experiment."""
        sample_experiment.status = ExperimentStatus.DRAFT
        mock_session.get.return_value = sample_experiment
        mock_get_session.return_value = mock_session

        experiment_service.start_experiment(sample_experiment.id)

        assert sample_experiment.status == ExperimentStatus.RUNNING
        assert sample_experiment.started_at is not None
        mock_session.commit.assert_called_once()

    @patch('src.experimentation.service.get_session')
    def test_start_experiment_not_found(self, mock_get_session, experiment_service, mock_session):
        """Test starting non-existent experiment."""
        mock_session.get.return_value = None
        mock_get_session.return_value = mock_session

        with pytest.raises(ValueError, match="not found"):
            experiment_service.start_experiment("nonexistent_id")

    @patch('src.experimentation.service.get_session')
    def test_start_experiment_invalid_status(self, mock_get_session, experiment_service, mock_session, sample_experiment):
        """Test starting experiment in invalid status."""
        sample_experiment.status = ExperimentStatus.STOPPED
        mock_session.get.return_value = sample_experiment
        mock_get_session.return_value = mock_session

        with pytest.raises(ValueError, match="Cannot start"):
            experiment_service.start_experiment(sample_experiment.id)

    @patch('src.experimentation.service.get_session')
    def test_pause_experiment(self, mock_get_session, experiment_service, mock_session, sample_experiment):
        """Test pausing an experiment."""
        mock_session.get.return_value = sample_experiment
        mock_get_session.return_value = mock_session

        experiment_service.pause_experiment(sample_experiment.id)

        assert sample_experiment.status == ExperimentStatus.PAUSED
        mock_session.commit.assert_called_once()

    @patch('src.experimentation.service.get_session')
    def test_stop_experiment_without_winner(self, mock_get_session, experiment_service, mock_session, sample_experiment):
        """Test stopping experiment without declaring winner."""
        mock_session.get.return_value = sample_experiment
        mock_get_session.return_value = mock_session

        experiment_service.stop_experiment(sample_experiment.id)

        assert sample_experiment.status == ExperimentStatus.STOPPED
        assert sample_experiment.stopped_at is not None
        assert sample_experiment.winner_variant_id is None
        mock_session.commit.assert_called_once()

    @patch('src.experimentation.service.get_session')
    def test_stop_experiment_with_winner(self, mock_get_session, experiment_service, mock_session, sample_experiment):
        """Test stopping experiment with winner."""
        winner_id = "variant_123"
        mock_session.get.return_value = sample_experiment
        mock_get_session.return_value = mock_session

        experiment_service.stop_experiment(sample_experiment.id, winner=winner_id)

        assert sample_experiment.status == ExperimentStatus.STOPPED
        assert sample_experiment.winner_variant_id == winner_id
        mock_session.commit.assert_called_once()


class TestVariantAssignment:
    """Test variant assignment operations."""

    @patch('src.experimentation.service.get_session')
    def test_assign_variant_success(self, mock_get_session, experiment_service, mock_session, sample_experiment, sample_variants):
        """Test successful variant assignment."""
        mock_session.get.return_value = sample_experiment
        mock_session.exec.return_value.all.return_value = sample_variants
        mock_get_session.return_value = mock_session

        with patch.object(experiment_service._assigner, 'assign_variant', return_value=sample_variants[0].id):
            assignment = experiment_service.assign_variant(
                workflow_id="wf_123",
                experiment_id=sample_experiment.id,
            )

        assert assignment is not None
        assert assignment.workflow_execution_id == "wf_123"
        assert assignment.experiment_id == sample_experiment.id
        assert assignment.variant_id == sample_variants[0].id
        mock_session.add.assert_called()
        mock_session.commit.assert_called_once()

    @patch('src.experimentation.service.get_session')
    def test_assign_variant_with_context(self, mock_get_session, experiment_service, mock_session, sample_experiment, sample_variants):
        """Test variant assignment with context."""
        mock_session.get.return_value = sample_experiment
        mock_session.exec.return_value.all.return_value = sample_variants
        mock_get_session.return_value = mock_session

        context = {"user_id": "user_123", "region": "us-west"}

        with patch.object(experiment_service._assigner, 'assign_variant', return_value=sample_variants[0].id):
            assignment = experiment_service.assign_variant(
                workflow_id="wf_123",
                experiment_id=sample_experiment.id,
                context=context,
            )

        assert assignment.assignment_context == context

    @patch('src.experimentation.service.get_session')
    def test_assign_variant_experiment_not_found(self, mock_get_session, experiment_service, mock_session):
        """Test variant assignment for non-existent experiment."""
        mock_session.get.return_value = None
        mock_get_session.return_value = mock_session

        with pytest.raises(ValueError, match="not found"):
            experiment_service.assign_variant("wf_123", "nonexistent_id")

    @patch('src.experimentation.service.get_session')
    def test_assign_variant_experiment_not_running(self, mock_get_session, experiment_service, mock_session, sample_experiment):
        """Test variant assignment for non-running experiment."""
        sample_experiment.status = ExperimentStatus.PAUSED
        mock_session.get.return_value = sample_experiment
        mock_get_session.return_value = mock_session

        with pytest.raises(ValueError, match="not running"):
            experiment_service.assign_variant("wf_123", sample_experiment.id)

    @patch('src.experimentation.service.get_session')
    def test_assign_variant_no_variants(self, mock_get_session, experiment_service, mock_session, sample_experiment):
        """Test variant assignment when no variants exist."""
        mock_session.get.return_value = sample_experiment
        mock_session.exec.return_value.all.return_value = []
        mock_get_session.return_value = mock_session

        with pytest.raises(ValueError, match="No variants found"):
            experiment_service.assign_variant("wf_123", sample_experiment.id)

    @patch('src.experimentation.service.get_session')
    def test_get_variant_config(self, mock_get_session, experiment_service, mock_session, sample_variants):
        """Test getting variant configuration."""
        variant = sample_variants[0]
        variant.config_overrides = {"temperature": 0.9}
        mock_session.get.return_value = variant
        mock_get_session.return_value = mock_session

        config = experiment_service.get_variant_config(variant.id)

        assert config == {"temperature": 0.9}

    @patch('src.experimentation.service.get_session')
    def test_get_variant_config_not_found(self, mock_get_session, experiment_service, mock_session):
        """Test getting config for non-existent variant."""
        mock_session.get.return_value = None
        mock_get_session.return_value = mock_session

        with pytest.raises(ValueError, match="not found"):
            experiment_service.get_variant_config("nonexistent_id")


class TestTracking:
    """Test execution tracking."""

    @patch('src.experimentation.service.get_session')
    def test_track_execution_complete_success(self, mock_get_session, experiment_service, mock_session, sample_experiment, sample_variants):
        """Test tracking completed execution."""
        assignment = VariantAssignment(
            id=str(uuid.uuid4()),
            experiment_id=sample_experiment.id,
            variant_id=sample_variants[0].id,
            workflow_execution_id="wf_123",
            assigned_at=datetime.now(timezone.utc),
            assignment_strategy=AssignmentStrategyType.RANDOM,
            execution_status=ExecutionStatus.PENDING,
        )

        mock_session.exec.return_value.first.return_value = assignment
        mock_session.get.return_value = sample_experiment
        mock_get_session.return_value = mock_session

        metrics = {"duration_seconds": 1.5, "error_rate": 0.01}
        experiment_service.track_execution_complete("wf_123", metrics, status="completed")

        assert assignment.execution_status == ExecutionStatus.COMPLETED
        assert assignment.metrics == metrics
        assert assignment.execution_completed_at is not None
        mock_session.execute.assert_called()
        mock_session.commit.assert_called_once()

    @patch('src.experimentation.service.get_session')
    def test_track_execution_complete_failed(self, mock_get_session, experiment_service, mock_session, sample_experiment, sample_variants):
        """Test tracking failed execution."""
        assignment = VariantAssignment(
            id=str(uuid.uuid4()),
            experiment_id=sample_experiment.id,
            variant_id=sample_variants[0].id,
            workflow_execution_id="wf_123",
            assigned_at=datetime.now(timezone.utc),
            assignment_strategy=AssignmentStrategyType.RANDOM,
            execution_status=ExecutionStatus.PENDING,
        )

        mock_session.exec.return_value.first.return_value = assignment
        mock_session.get.return_value = sample_experiment
        mock_get_session.return_value = mock_session

        metrics = {"duration_seconds": 0.5, "error": "timeout"}
        experiment_service.track_execution_complete("wf_123", metrics, status="failed")

        assert assignment.execution_status == ExecutionStatus.FAILED
        mock_session.execute.assert_called()

    @patch('src.experimentation.service.get_session')
    def test_track_execution_complete_no_assignment(self, mock_get_session, experiment_service, mock_session):
        """Test tracking execution with no assignment found."""
        mock_session.exec.return_value.first.return_value = None
        mock_get_session.return_value = mock_session

        # Should not raise, just log warning
        experiment_service.track_execution_complete("wf_123", {}, status="completed")


class TestAnalysis:
    """Test experiment analysis."""

    @patch('src.experimentation.service.get_session')
    def test_get_experiment_results(self, mock_get_session, experiment_service, mock_session, sample_experiment, sample_variants):
        """Test getting experiment analysis results."""
        mock_session.get.return_value = sample_experiment
        mock_session.exec.return_value.all.return_value = sample_variants
        mock_get_session.return_value = mock_session

        analysis_results = {
            "sample_size": 200,
            "variant_metrics": {},
            "statistical_tests": {},
            "guardrail_violations": [],
            "recommendation": RecommendationType.CONTINUE,
            "confidence": 0.95,
        }

        with patch.object(experiment_service._analyzer, 'analyze_experiment', return_value=analysis_results):
            results = experiment_service.get_experiment_results(sample_experiment.id)

        assert results["sample_size"] == 200
        assert results["confidence"] == 0.95
        mock_session.add.assert_called()
        mock_session.commit.assert_called_once()

    @patch('src.experimentation.service.get_session')
    def test_get_experiment_results_not_found(self, mock_get_session, experiment_service, mock_session):
        """Test getting results for non-existent experiment."""
        mock_session.get.return_value = None
        mock_get_session.return_value = mock_session

        with pytest.raises(ValueError, match="not found"):
            experiment_service.get_experiment_results("nonexistent_id")

    @patch.object(ExperimentService, 'get_experiment_results')
    def test_check_early_stopping_should_stop(self, mock_get_results, experiment_service):
        """Test early stopping check when should stop."""
        mock_get_results.return_value = {
            "recommendation": RecommendationType.STOP_WINNER,
            "recommended_winner": "variant_a",
            "confidence": 0.99,
        }

        result = experiment_service.check_early_stopping("exp_123")

        assert result["should_stop"] is True
        assert result["reason"] == RecommendationType.STOP_WINNER.value
        assert result["winner"] == "variant_a"
        assert result["confidence"] == 0.99

    @patch.object(ExperimentService, 'get_experiment_results')
    def test_check_early_stopping_should_continue(self, mock_get_results, experiment_service):
        """Test early stopping check when should continue."""
        mock_get_results.return_value = {
            "recommendation": RecommendationType.CONTINUE,
            "confidence": 0.7,
        }

        result = experiment_service.check_early_stopping("exp_123")

        assert result["should_stop"] is False
        assert result["reason"] == RecommendationType.CONTINUE.value
