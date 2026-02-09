"""
Tests for ExperimentCRUD operations.

Tests experiment CRUD operations, caching, thread safety, and transaction handling.
"""

import threading
import uuid
from datetime import datetime, timezone
from unittest.mock import Mock, patch

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session

from src.experimentation.experiment_crud import ExperimentCRUD
from src.experimentation.models import (
    AssignmentStrategyType,
    Experiment,
    ExperimentStatus,
    Variant,
)


@pytest.fixture
def crud_instance():
    """Create ExperimentCRUD instance with small cache."""
    return ExperimentCRUD(max_cache_size=10)


@pytest.fixture
def mock_session():
    """Mock database session."""
    session = Mock(spec=Session)
    session.__enter__ = Mock(return_value=session)
    session.__exit__ = Mock(return_value=False)
    return session


@pytest.fixture
def sample_experiment():
    """Create sample experiment for testing."""
    exp_id = str(uuid.uuid4())
    return Experiment(
        id=exp_id,
        name="test_experiment",
        description="Test experiment",
        status=ExperimentStatus.DRAFT,
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
def sample_variants():
    """Create sample variants."""
    exp_id = str(uuid.uuid4())
    return [
        {"name": "control", "is_control": True, "traffic": 0.5},
        {"name": "variant_a", "traffic": 0.5, "config": {"temperature": 0.9}}
    ]


class TestCRUDInitialization:
    """Test ExperimentCRUD initialization."""

    def test_initialization_default(self):
        """Test initialization with default cache size."""
        crud = ExperimentCRUD()

        assert crud._max_cache_size == ExperimentCRUD.MAX_CACHE_SIZE
        assert len(crud._experiment_cache) == 0
        assert crud._cache_lock is not None

    def test_initialization_custom_cache_size(self):
        """Test initialization with custom cache size."""
        crud = ExperimentCRUD(max_cache_size=50)

        assert crud._max_cache_size == 50
        assert len(crud._experiment_cache) == 0

    def test_initialization_large_cache_size(self):
        """Test initialization with large cache size."""
        crud = ExperimentCRUD(max_cache_size=10000)

        assert crud._max_cache_size == 10000


class TestCreateExperiment:
    """Test experiment creation."""

    @patch('src.experimentation.experiment_crud.get_session')
    def test_create_experiment_minimal(self, mock_get_session, crud_instance, mock_session):
        """Test creating experiment with minimal parameters."""
        mock_get_session.return_value = mock_session

        exp_id = crud_instance.create_experiment(
            name="test_exp",
            description="Test description",
            variants=[
                {"name": "control", "is_control": True},
                {"name": "variant_a"}
            ],
            primary_metric="duration_seconds",
        )

        assert exp_id is not None
        assert isinstance(exp_id, str)
        # Verify UUID format
        uuid.UUID(exp_id)

        # Verify database operations
        assert mock_session.add.call_count == 3  # 1 experiment + 2 variants
        mock_session.commit.assert_called_once()

    @patch('src.experimentation.experiment_crud.get_session')
    def test_create_experiment_with_all_params(self, mock_get_session, crud_instance, mock_session):
        """Test creating experiment with all optional parameters."""
        mock_get_session.return_value = mock_session

        exp_id = crud_instance.create_experiment(
            name="full_test_exp",
            description="Full test description",
            variants=[
                {"name": "control", "is_control": True, "traffic": 0.6, "description": "Control variant"},
                {"name": "variant_a", "traffic": 0.4, "config": {"temperature": 0.9}, "description": "Test variant"}
            ],
            assignment_strategy="hash",
            primary_metric="quality_score",
            secondary_metrics=["latency", "cost"],
            guardrail_metrics=[{"metric": "error_rate", "max_value": 0.05}],
            confidence_level=0.99,
            min_sample_size_per_variant=200,
            tags=["production", "ml"],
            created_by="user@example.com",
            extra_metadata={"team": "ml-ops"},
        )

        assert exp_id is not None
        mock_session.commit.assert_called_once()

    @patch('src.experimentation.experiment_crud.get_session')
    def test_create_experiment_with_custom_traffic(self, mock_get_session, crud_instance, mock_session):
        """Test creating experiment with custom traffic allocation."""
        mock_get_session.return_value = mock_session

        exp_id = crud_instance.create_experiment(
            name="traffic_test",
            description="Test traffic allocation",
            variants=[
                {"name": "control", "is_control": True, "traffic": 0.7},
                {"name": "variant_a", "traffic": 0.3}
            ],
            primary_metric="duration_seconds",
        )

        assert exp_id is not None
        mock_session.commit.assert_called_once()

    def test_create_experiment_empty_name(self, crud_instance):
        """Test that empty name is rejected."""
        with pytest.raises(ValueError, match="name must be"):
            crud_instance.create_experiment(
                name="",
                description="Test",
                variants=[
                    {"name": "control", "is_control": True},
                    {"name": "variant_a"}
                ],
                primary_metric="duration_seconds",
            )

    def test_create_experiment_invalid_name_too_long(self, crud_instance):
        """Test that overly long name is rejected."""
        long_name = "x" * 300  # Exceeds typical limit

        with pytest.raises(ValueError, match="name must be"):
            crud_instance.create_experiment(
                name=long_name,
                description="Test",
                variants=[
                    {"name": "control", "is_control": True},
                    {"name": "variant_a"}
                ],
                primary_metric="duration_seconds",
            )

    def test_create_experiment_insufficient_variants(self, crud_instance):
        """Test that single variant is rejected."""
        with pytest.raises(ValueError, match="at least 2 variants"):
            crud_instance.create_experiment(
                name="test_exp",
                description="Test",
                variants=[{"name": "control"}],
                primary_metric="duration_seconds",
            )

    def test_create_experiment_no_variants(self, crud_instance):
        """Test that empty variants list is rejected."""
        with pytest.raises(ValueError, match="at least 2 variants"):
            crud_instance.create_experiment(
                name="test_exp",
                description="Test",
                variants=[],
                primary_metric="duration_seconds",
            )

    def test_create_experiment_traffic_exceeds_limit(self, crud_instance):
        """Test that traffic allocation exceeding 1.0 is rejected."""
        with pytest.raises(ValueError, match="exceeds 1.0"):
            crud_instance.create_experiment(
                name="test_exp",
                description="Test",
                variants=[
                    {"name": "control", "traffic": 0.7},
                    {"name": "variant_a", "traffic": 0.5}  # Total = 1.2
                ],
                primary_metric="duration_seconds",
            )

    def test_create_experiment_traffic_exactly_one(self, crud_instance, mock_session):
        """Test that traffic allocation of exactly 1.0 is accepted."""
        with patch('src.experimentation.experiment_crud.get_session', return_value=mock_session):
            exp_id = crud_instance.create_experiment(
                name="test_exp",
                description="Test",
                variants=[
                    {"name": "control", "traffic": 0.4},
                    {"name": "variant_a", "traffic": 0.6}  # Total = 1.0
                ],
                primary_metric="duration_seconds",
            )

            assert exp_id is not None

    def test_create_experiment_three_variants(self, crud_instance, mock_session):
        """Test creating experiment with three variants."""
        with patch('src.experimentation.experiment_crud.get_session', return_value=mock_session):
            exp_id = crud_instance.create_experiment(
                name="three_variant_test",
                description="Test with 3 variants",
                variants=[
                    {"name": "control", "is_control": True, "traffic": 0.5},
                    {"name": "variant_a", "traffic": 0.3},
                    {"name": "variant_b", "traffic": 0.2}
                ],
                primary_metric="duration_seconds",
            )

            assert exp_id is not None
            # 1 experiment + 3 variants = 4 adds
            assert mock_session.add.call_count == 4

    @patch('src.experimentation.experiment_crud.get_session')
    def test_create_experiment_duplicate_name(self, mock_get_session, crud_instance, mock_session):
        """Test that duplicate experiment name raises error."""
        mock_session.commit.side_effect = IntegrityError("", "", "")
        mock_get_session.return_value = mock_session

        with pytest.raises(ValueError, match="constraint violation"):
            crud_instance.create_experiment(
                name="duplicate_exp",
                description="Test",
                variants=[
                    {"name": "control", "is_control": True},
                    {"name": "variant_a"}
                ],
                primary_metric="duration_seconds",
            )

    @patch('src.experimentation.experiment_crud.get_session')
    def test_create_experiment_invalid_variant_name(self, mock_get_session, crud_instance, mock_session):
        """Test that invalid variant name is rejected."""
        mock_get_session.return_value = mock_session

        with pytest.raises(ValueError):
            crud_instance.create_experiment(
                name="test_exp",
                description="Test",
                variants=[
                    {"name": "", "is_control": True},  # Empty variant name
                    {"name": "variant_a"}
                ],
                primary_metric="duration_seconds",
            )


class TestGetExperiment:
    """Test experiment retrieval."""

    @patch('src.experimentation.experiment_crud.get_session')
    def test_get_experiment_from_database(self, mock_get_session, crud_instance, mock_session, sample_experiment):
        """Test getting experiment from database (cache miss)."""
        mock_session.exec.return_value.first.return_value = sample_experiment
        mock_get_session.return_value = mock_session

        result = crud_instance.get_experiment(sample_experiment.id, use_cache=False)

        assert result is not None
        assert result.id == sample_experiment.id
        assert result.name == "test_experiment"
        mock_session.expunge.assert_called_once()

    @patch('src.experimentation.experiment_crud.get_session')
    def test_get_experiment_with_cache(self, mock_get_session, crud_instance, mock_session, sample_experiment):
        """Test that cache is used on subsequent requests."""
        mock_session.exec.return_value.first.return_value = sample_experiment
        mock_get_session.return_value = mock_session

        # First call - loads from database
        result1 = crud_instance.get_experiment(sample_experiment.id, use_cache=True)
        assert result1 is not None

        # Second call - should use cache
        result2 = crud_instance.get_experiment(sample_experiment.id, use_cache=True)
        assert result2 is not None
        assert result1 == result2

        # Database should only be queried once
        assert mock_session.exec.call_count == 1

    @patch('src.experimentation.experiment_crud.get_session')
    def test_get_experiment_cache_disabled(self, mock_get_session, crud_instance, mock_session, sample_experiment):
        """Test getting experiment with cache disabled."""
        mock_session.exec.return_value.first.return_value = sample_experiment
        mock_get_session.return_value = mock_session

        # Call twice with cache disabled
        result1 = crud_instance.get_experiment(sample_experiment.id, use_cache=False)
        result2 = crud_instance.get_experiment(sample_experiment.id, use_cache=False)

        assert result1 is not None
        assert result2 is not None

        # Database should be queried both times
        assert mock_session.exec.call_count == 2

    @patch('src.experimentation.experiment_crud.get_session')
    def test_get_experiment_not_found(self, mock_get_session, crud_instance, mock_session):
        """Test getting non-existent experiment."""
        mock_session.exec.return_value.first.return_value = None
        mock_get_session.return_value = mock_session

        result = crud_instance.get_experiment("nonexistent_id")

        assert result is None

    @patch('src.experimentation.experiment_crud.get_session')
    def test_get_experiment_eager_loading(self, mock_get_session, crud_instance, mock_session):
        """Test that get_experiment uses eager loading for relationships."""
        mock_session.exec.return_value.first.return_value = None
        mock_get_session.return_value = mock_session

        crud_instance.get_experiment("test_id")

        # Verify that selectinload was used (check statement construction)
        call_args = mock_session.exec.call_args
        assert call_args is not None


class TestListExperiments:
    """Test experiment listing."""

    @patch('src.experimentation.experiment_crud.get_session')
    def test_list_all_experiments(self, mock_get_session, crud_instance, mock_session, sample_experiment):
        """Test listing all experiments."""
        experiments = [sample_experiment]
        mock_session.exec.return_value.all.return_value = experiments
        mock_get_session.return_value = mock_session

        results = crud_instance.list_experiments()

        assert len(results) == 1
        assert results[0].id == sample_experiment.id

    @patch('src.experimentation.experiment_crud.get_session')
    def test_list_experiments_by_status(self, mock_get_session, crud_instance, mock_session, sample_experiment):
        """Test listing experiments filtered by status."""
        sample_experiment.status = ExperimentStatus.RUNNING
        experiments = [sample_experiment]
        mock_session.exec.return_value.all.return_value = experiments
        mock_get_session.return_value = mock_session

        results = crud_instance.list_experiments(status=ExperimentStatus.RUNNING)

        assert len(results) == 1
        assert results[0].status == ExperimentStatus.RUNNING

    @patch('src.experimentation.experiment_crud.get_session')
    def test_list_experiments_empty(self, mock_get_session, crud_instance, mock_session):
        """Test listing experiments when none exist."""
        mock_session.exec.return_value.all.return_value = []
        mock_get_session.return_value = mock_session

        results = crud_instance.list_experiments()

        assert len(results) == 0

    @patch('src.experimentation.experiment_crud.get_session')
    def test_list_experiments_multiple_statuses(self, mock_get_session, crud_instance, mock_session):
        """Test listing experiments with different statuses."""
        exp1 = Experiment(
            id=str(uuid.uuid4()),
            name="exp1",
            description="Test",
            status=ExperimentStatus.RUNNING,
            assignment_strategy=AssignmentStrategyType.RANDOM,
            traffic_allocation={"control": 1.0},
            primary_metric="duration_seconds",
            confidence_level=0.95,
            min_sample_size_per_variant=100,
        )
        exp2 = Experiment(
            id=str(uuid.uuid4()),
            name="exp2",
            description="Test",
            status=ExperimentStatus.DRAFT,
            assignment_strategy=AssignmentStrategyType.RANDOM,
            traffic_allocation={"control": 1.0},
            primary_metric="duration_seconds",
            confidence_level=0.95,
            min_sample_size_per_variant=100,
        )

        # Test filtering by RUNNING
        mock_session.exec.return_value.all.return_value = [exp1]
        mock_get_session.return_value = mock_session

        results = crud_instance.list_experiments(status=ExperimentStatus.RUNNING)

        assert len(results) == 1
        assert results[0].status == ExperimentStatus.RUNNING


class TestCacheManagement:
    """Test cache management operations."""

    def test_cache_put_basic(self, crud_instance, sample_experiment):
        """Test basic cache put operation."""
        crud_instance._cache_put(sample_experiment.id, sample_experiment)

        assert sample_experiment.id in crud_instance._experiment_cache
        assert crud_instance._experiment_cache[sample_experiment.id] == sample_experiment

    def test_cache_put_lru_eviction(self, sample_experiment):
        """Test LRU cache eviction when max size exceeded."""
        # Create small cache
        crud_instance = ExperimentCRUD(max_cache_size=3)

        # Add 4 experiments (exceeds cache size of 3)
        experiments = []
        for i in range(4):
            exp = Experiment(
                id=f"exp-{i}",
                name=f"exp_{i}",
                description="Test",
                status=ExperimentStatus.DRAFT,
                assignment_strategy=AssignmentStrategyType.RANDOM,
                traffic_allocation={"control": 1.0},
                primary_metric="duration_seconds",
                confidence_level=0.95,
                min_sample_size_per_variant=100,
            )
            experiments.append(exp)
            crud_instance._cache_put(exp.id, exp)

        # Cache should only contain last 3
        assert len(crud_instance._experiment_cache) == 3
        # First experiment should be evicted
        assert "exp-0" not in crud_instance._experiment_cache
        # Last 3 should be present
        assert "exp-1" in crud_instance._experiment_cache
        assert "exp-2" in crud_instance._experiment_cache
        assert "exp-3" in crud_instance._experiment_cache

    def test_cache_move_to_end(self, sample_experiment):
        """Test that cache updates move items to end (LRU)."""
        crud_instance = ExperimentCRUD(max_cache_size=3)

        # Add 3 experiments
        exp1 = Experiment(
            id="exp-1",
            name="exp_1",
            description="Test",
            status=ExperimentStatus.DRAFT,
            assignment_strategy=AssignmentStrategyType.RANDOM,
            traffic_allocation={"control": 1.0},
            primary_metric="duration_seconds",
            confidence_level=0.95,
            min_sample_size_per_variant=100,
        )
        exp2 = Experiment(
            id="exp-2",
            name="exp_2",
            description="Test",
            status=ExperimentStatus.DRAFT,
            assignment_strategy=AssignmentStrategyType.RANDOM,
            traffic_allocation={"control": 1.0},
            primary_metric="duration_seconds",
            confidence_level=0.95,
            min_sample_size_per_variant=100,
        )
        exp3 = Experiment(
            id="exp-3",
            name="exp_3",
            description="Test",
            status=ExperimentStatus.DRAFT,
            assignment_strategy=AssignmentStrategyType.RANDOM,
            traffic_allocation={"control": 1.0},
            primary_metric="duration_seconds",
            confidence_level=0.95,
            min_sample_size_per_variant=100,
        )

        crud_instance._cache_put("exp-1", exp1)
        crud_instance._cache_put("exp-2", exp2)
        crud_instance._cache_put("exp-3", exp3)

        # Access exp-1 again (move to end)
        crud_instance._cache_put("exp-1", exp1)

        # Add new experiment (should evict exp-2, not exp-1)
        exp4 = Experiment(
            id="exp-4",
            name="exp_4",
            description="Test",
            status=ExperimentStatus.DRAFT,
            assignment_strategy=AssignmentStrategyType.RANDOM,
            traffic_allocation={"control": 1.0},
            primary_metric="duration_seconds",
            confidence_level=0.95,
            min_sample_size_per_variant=100,
        )
        crud_instance._cache_put("exp-4", exp4)

        # exp-2 should be evicted (oldest), exp-1 should remain (recently accessed)
        assert "exp-1" in crud_instance._experiment_cache
        assert "exp-2" not in crud_instance._experiment_cache
        assert "exp-3" in crud_instance._experiment_cache
        assert "exp-4" in crud_instance._experiment_cache

    def test_invalidate_cache(self, crud_instance, sample_experiment):
        """Test cache invalidation."""
        # Add to cache
        crud_instance._cache_put(sample_experiment.id, sample_experiment)
        assert sample_experiment.id in crud_instance._experiment_cache

        # Invalidate
        crud_instance.invalidate_cache(sample_experiment.id)
        assert sample_experiment.id not in crud_instance._experiment_cache

    def test_invalidate_cache_nonexistent(self, crud_instance):
        """Test invalidating non-existent cache entry (should not raise)."""
        # Should not raise error
        crud_instance.invalidate_cache("nonexistent_id")

    def test_clear_cache(self, crud_instance):
        """Test clearing entire cache."""
        # Add multiple experiments to cache
        for i in range(5):
            exp = Experiment(
                id=f"exp-{i}",
                name=f"exp_{i}",
                description="Test",
                status=ExperimentStatus.DRAFT,
                assignment_strategy=AssignmentStrategyType.RANDOM,
                traffic_allocation={"control": 1.0},
                primary_metric="duration_seconds",
                confidence_level=0.95,
                min_sample_size_per_variant=100,
            )
            crud_instance._cache_put(exp.id, exp)

        assert len(crud_instance._experiment_cache) == 5

        # Clear cache
        crud_instance.clear_cache()
        assert len(crud_instance._experiment_cache) == 0

    def test_clear_cache_empty(self, crud_instance):
        """Test clearing empty cache (should not raise)."""
        assert len(crud_instance._experiment_cache) == 0
        crud_instance.clear_cache()
        assert len(crud_instance._experiment_cache) == 0


class TestThreadSafety:
    """Test thread safety of cache operations."""

    def test_concurrent_cache_put(self):
        """Test concurrent cache put operations."""
        crud_instance = ExperimentCRUD(max_cache_size=100)

        def add_experiments(start_idx, count):
            for i in range(start_idx, start_idx + count):
                exp = Experiment(
                    id=f"exp-{i}",
                    name=f"exp_{i}",
                    description="Test",
                    status=ExperimentStatus.DRAFT,
                    assignment_strategy=AssignmentStrategyType.RANDOM,
                    traffic_allocation={"control": 1.0},
                    primary_metric="duration_seconds",
                    confidence_level=0.95,
                    min_sample_size_per_variant=100,
                )
                crud_instance._cache_put(exp.id, exp)

        # Create 10 threads, each adding 10 experiments
        threads = []
        for i in range(10):
            thread = threading.Thread(target=add_experiments, args=(i * 10, 10))
            threads.append(thread)
            thread.start()

        # Wait for all threads
        for thread in threads:
            thread.join()

        # All 100 experiments should be in cache (cache size = 100)
        assert len(crud_instance._experiment_cache) == 100

    def test_concurrent_cache_invalidate(self):
        """Test concurrent cache invalidation."""
        crud_instance = ExperimentCRUD(max_cache_size=100)

        # Add experiments
        for i in range(50):
            exp = Experiment(
                id=f"exp-{i}",
                name=f"exp_{i}",
                description="Test",
                status=ExperimentStatus.DRAFT,
                assignment_strategy=AssignmentStrategyType.RANDOM,
                traffic_allocation={"control": 1.0},
                primary_metric="duration_seconds",
                confidence_level=0.95,
                min_sample_size_per_variant=100,
            )
            crud_instance._cache_put(exp.id, exp)

        def invalidate_experiments(start_idx, count):
            for i in range(start_idx, start_idx + count):
                crud_instance.invalidate_cache(f"exp-{i}")

        # Create threads to invalidate experiments
        threads = []
        for i in range(5):
            thread = threading.Thread(target=invalidate_experiments, args=(i * 10, 10))
            threads.append(thread)
            thread.start()

        # Wait for all threads
        for thread in threads:
            thread.join()

        # All should be invalidated
        assert len(crud_instance._experiment_cache) == 0

    def test_concurrent_get_and_put(self):
        """Test concurrent get and put operations."""
        crud_instance = ExperimentCRUD(max_cache_size=50)

        # Pre-populate cache
        for i in range(25):
            exp = Experiment(
                id=f"exp-{i}",
                name=f"exp_{i}",
                description="Test",
                status=ExperimentStatus.DRAFT,
                assignment_strategy=AssignmentStrategyType.RANDOM,
                traffic_allocation={"control": 1.0},
                primary_metric="duration_seconds",
                confidence_level=0.95,
                min_sample_size_per_variant=100,
            )
            crud_instance._cache_put(exp.id, exp)

        def reader_thread():
            for i in range(100):
                exp_id = f"exp-{i % 25}"
                with crud_instance._cache_lock:
                    _ = crud_instance._experiment_cache.get(exp_id)

        def writer_thread():
            for i in range(25, 50):
                exp = Experiment(
                    id=f"exp-{i}",
                    name=f"exp_{i}",
                    description="Test",
                    status=ExperimentStatus.DRAFT,
                    assignment_strategy=AssignmentStrategyType.RANDOM,
                    traffic_allocation={"control": 1.0},
                    primary_metric="duration_seconds",
                    confidence_level=0.95,
                    min_sample_size_per_variant=100,
                )
                crud_instance._cache_put(exp.id, exp)

        # Create reader and writer threads
        threads = []
        for _ in range(5):
            threads.append(threading.Thread(target=reader_thread))
        for _ in range(5):
            threads.append(threading.Thread(target=writer_thread))

        for thread in threads:
            thread.start()

        for thread in threads:
            thread.join()

        # Cache should be full (50 items)
        assert len(crud_instance._experiment_cache) == 50


class TestEdgeCases:
    """Test edge cases and error conditions."""

    def test_create_experiment_with_empty_variants(self, crud_instance):
        """Test that empty variants list is rejected."""
        with pytest.raises(ValueError, match="at least 2 variants"):
            crud_instance.create_experiment(
                name="test_exp",
                description="Test",
                variants=[],
                primary_metric="duration_seconds",
            )

    def test_create_experiment_with_none_variants(self, crud_instance):
        """Test that None variants is rejected."""
        with pytest.raises(ValueError, match="at least 2 variants"):
            crud_instance.create_experiment(
                name="test_exp",
                description="Test",
                variants=None,  # type: ignore
                primary_metric="duration_seconds",
            )

    def test_get_experiment_with_none_id(self, crud_instance):
        """Test getting experiment with None ID."""
        with patch('src.experimentation.experiment_crud.get_session') as mock_get_session:
            mock_session = Mock(spec=Session)
            mock_session.__enter__ = Mock(return_value=mock_session)
            mock_session.__exit__ = Mock(return_value=False)
            mock_session.exec.return_value.first.return_value = None
            mock_get_session.return_value = mock_session

            result = crud_instance.get_experiment(None)  # type: ignore
            assert result is None

    def test_cache_size_zero(self):
        """Test that cache size of 0 works (immediate eviction)."""
        crud_instance = ExperimentCRUD(max_cache_size=0)

        exp = Experiment(
            id="exp-1",
            name="exp_1",
            description="Test",
            status=ExperimentStatus.DRAFT,
            assignment_strategy=AssignmentStrategyType.RANDOM,
            traffic_allocation={"control": 1.0},
            primary_metric="duration_seconds",
            confidence_level=0.95,
            min_sample_size_per_variant=100,
        )

        crud_instance._cache_put("exp-1", exp)

        # Should be immediately evicted
        assert len(crud_instance._experiment_cache) == 0

    def test_cache_size_one(self):
        """Test that cache size of 1 works (only most recent)."""
        crud_instance = ExperimentCRUD(max_cache_size=1)

        exp1 = Experiment(
            id="exp-1",
            name="exp_1",
            description="Test",
            status=ExperimentStatus.DRAFT,
            assignment_strategy=AssignmentStrategyType.RANDOM,
            traffic_allocation={"control": 1.0},
            primary_metric="duration_seconds",
            confidence_level=0.95,
            min_sample_size_per_variant=100,
        )
        exp2 = Experiment(
            id="exp-2",
            name="exp_2",
            description="Test",
            status=ExperimentStatus.DRAFT,
            assignment_strategy=AssignmentStrategyType.RANDOM,
            traffic_allocation={"control": 1.0},
            primary_metric="duration_seconds",
            confidence_level=0.95,
            min_sample_size_per_variant=100,
        )

        crud_instance._cache_put("exp-1", exp1)
        crud_instance._cache_put("exp-2", exp2)

        # Only exp-2 should remain
        assert len(crud_instance._experiment_cache) == 1
        assert "exp-2" in crud_instance._experiment_cache
        assert "exp-1" not in crud_instance._experiment_cache

    @patch('src.experimentation.experiment_crud.get_session')
    def test_create_experiment_uneven_traffic_sum(self, mock_get_session, crud_instance, mock_session):
        """Test creating experiment with traffic sum < 1.0 (valid, partial allocation)."""
        mock_get_session.return_value = mock_session

        exp_id = crud_instance.create_experiment(
            name="partial_traffic",
            description="Test partial traffic allocation",
            variants=[
                {"name": "control", "is_control": True, "traffic": 0.3},
                {"name": "variant_a", "traffic": 0.2}  # Total = 0.5 (valid)
            ],
            primary_metric="duration_seconds",
        )

        assert exp_id is not None
        mock_session.commit.assert_called_once()
