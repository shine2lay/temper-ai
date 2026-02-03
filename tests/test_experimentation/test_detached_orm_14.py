"""Tests for code-high-detached-orm-14.

Verifies that ExperimentService caches experiments in a detached-safe manner,
preventing DetachedInstanceError when accessing lazy-loaded relationships
(variants, assignments, results) on cached Experiment objects after the
database session has closed.
"""

import os
import uuid
import pytest

# Set TESTING env var before importing service
os.environ['TESTING'] = '1'

from src.experimentation.service import ExperimentService
from src.experimentation.models import ExperimentStatus
from src.observability.database import init_database, reset_database


@pytest.fixture(autouse=True)
def setup_test_db(tmp_path):
    """Initialize a fresh test database for each test."""
    db_path = tmp_path / "test.db"
    init_database(f"sqlite:///{db_path}")
    yield
    reset_database()


@pytest.fixture
def service():
    """Create ExperimentService instance."""
    return ExperimentService()


@pytest.fixture
def experiment_id(service):
    """Create a test experiment and return its ID."""
    unique_name = f"test-detached-{uuid.uuid4().hex[:8]}"
    return service.create_experiment(
        name=unique_name,
        description="Test detached ORM fix",
        variants=[
            {"name": "control", "is_control": True, "traffic": 0.5},
            {"name": "treatment", "traffic": 0.5, "config": {"temperature": 0.9}},
        ],
        primary_metric="duration_seconds",
    )


class TestCachedExperimentAccess:
    """Verify cached experiments don't raise DetachedInstanceError."""

    def test_get_experiment_twice_no_detached_error(self, service, experiment_id):
        """Second get_experiment call should return cached object without error."""
        # First call loads from DB and caches
        exp1 = service.get_experiment(experiment_id)
        assert exp1 is not None

        # Second call returns from cache
        exp2 = service.get_experiment(experiment_id)
        assert exp2 is not None
        assert exp2.id == experiment_id

    def test_cached_experiment_variants_accessible(self, service, experiment_id):
        """Accessing variants on cached experiment should not raise."""
        # Load and cache
        exp = service.get_experiment(experiment_id)
        assert exp is not None

        # Access from cache (session is closed)
        cached_exp = service.get_experiment(experiment_id)

        # This would raise DetachedInstanceError without the fix
        variants = cached_exp.variants
        assert len(variants) == 2

        variant_names = {v.name for v in variants}
        assert "control" in variant_names
        assert "treatment" in variant_names

    def test_cached_experiment_relationships_loaded(self, service, experiment_id):
        """All relationship attributes should be eagerly loaded before caching."""
        exp = service.get_experiment(experiment_id)
        assert exp is not None

        # Access relationships — should not trigger lazy loading
        assert isinstance(exp.variants, list)
        assert isinstance(exp.assignments, list)
        assert isinstance(exp.results, list)

    def test_variant_config_accessible_from_cache(self, service, experiment_id):
        """Variant config should be accessible from cached experiment."""
        exp = service.get_experiment(experiment_id)

        for variant in exp.variants:
            if variant.name == "treatment":
                assert variant.config_overrides == {"temperature": 0.9}
                break
        else:
            pytest.fail("Treatment variant not found in cached experiment")


class TestCacheInvalidation:
    """Verify cache invalidation after lifecycle operations."""

    def test_start_experiment_invalidates_cache(self, service, experiment_id):
        """After start_experiment, cache should be invalidated."""
        # Cache the experiment
        exp = service.get_experiment(experiment_id)
        assert exp.status == ExperimentStatus.DRAFT

        # Start experiment
        service.start_experiment(experiment_id)

        # Get again — should reload from DB with RUNNING status
        exp = service.get_experiment(experiment_id)
        assert exp.status == ExperimentStatus.RUNNING

    def test_pause_experiment_invalidates_cache(self, service, experiment_id):
        """After pause_experiment, cache should be invalidated."""
        service.start_experiment(experiment_id)

        # Cache the running experiment
        exp = service.get_experiment(experiment_id)
        assert exp.status == ExperimentStatus.RUNNING

        # Pause
        service.pause_experiment(experiment_id)

        # Get again — should reload from DB with PAUSED status
        exp = service.get_experiment(experiment_id)
        assert exp.status == ExperimentStatus.PAUSED

    def test_stop_experiment_invalidates_cache(self, service, experiment_id):
        """After stop_experiment, cache should be invalidated."""
        service.start_experiment(experiment_id)

        exp = service.get_experiment(experiment_id)
        assert exp.status == ExperimentStatus.RUNNING

        service.stop_experiment(experiment_id)

        exp = service.get_experiment(experiment_id)
        assert exp.status == ExperimentStatus.STOPPED


class TestEagerLoading:
    """Verify that selectinload is used for relationship loading."""

    def test_variants_eagerly_loaded(self, service, experiment_id):
        """Variants should be loaded during the initial query, not lazy."""
        # Get experiment (triggers DB query with eager loading)
        exp = service.get_experiment(experiment_id)

        # Clear cache to force re-query
        service._experiment_cache.clear()

        # Reload — variants should be available without DetachedInstanceError
        exp = service.get_experiment(experiment_id)
        assert len(exp.variants) == 2

    def test_experiment_expunged_from_session(self, service, experiment_id):
        """Cached experiment should be detached (expunged) from session."""
        from sqlalchemy import inspect

        exp = service.get_experiment(experiment_id)

        # The object should be detached (not in any session)
        insp = inspect(exp)
        assert insp.detached or insp.persistent is False, (
            "Cached experiment should be detached from session"
        )
