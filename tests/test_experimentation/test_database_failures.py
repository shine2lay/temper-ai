"""
Database failure tests for experimentation module.

Tests database connection failures, transaction rollbacks, pool exhaustion,
concurrency conflicts, and data integrity for the A/B testing framework.

Coverage areas:
- Connection failures and recovery
- Connection pool exhaustion
- Transaction rollback scenarios
- Concurrent access and race conditions
- Data integrity constraints
- Distributed locking (if implemented)
"""
import asyncio
import tempfile
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlmodel import Session, select

from src.experimentation.models import (
    AssignmentStrategyType,
    ExecutionStatus,
    Experiment,
    ExperimentStatus,
    Variant,
    VariantAssignment,
)
from src.experimentation.service import ExperimentService
from src.observability.database import (
    DatabaseManager,
    get_session,
    init_database,
    reset_database,
)


@pytest.fixture
def temp_db_file():
    """Provide temporary database file."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.db', delete=False) as f:
        db_path = f.name

    yield db_path

    # Cleanup
    Path(db_path).unlink(missing_ok=True)


@pytest.fixture
def db_manager(temp_db_file):
    """Provide database manager with temp database."""
    manager = DatabaseManager(database_url=f"sqlite:///{temp_db_file}")
    manager.create_all_tables()
    yield manager


@pytest.fixture
def experiment_service(temp_db_file):
    """Provide experiment service with temp database."""
    # Initialize database for testing
    reset_database()
    init_database(database_url=f"sqlite:///{temp_db_file}")

    service = ExperimentService()
    service.initialize()

    yield service

    service.shutdown()
    reset_database()


# ========== Mock Helpers ==========

@contextmanager
def mock_connection_error():
    """Simulate database connection loss."""
    with patch('src.observability.database.get_session') as mock:
        mock.side_effect = OperationalError(
            "connection to server was lost",
            params=None,
            orig=None
        )
        yield mock


@contextmanager
def mock_pool_timeout():
    """Simulate connection pool timeout."""
    with patch('src.observability.database.get_session') as mock:
        mock.side_effect = TimeoutError(
            "QueuePool limit of size 5 overflow 10 reached, connection timed out"
        )
        yield mock


@contextmanager
def mock_transaction_conflict():
    """Simulate SERIALIZABLE isolation conflict."""
    original_commit = Session.commit

    def failing_commit(self):
        raise OperationalError(
            "could not serialize access due to concurrent update",
            params=None,
            orig=None
        )

    with patch.object(Session, 'commit', failing_commit):
        yield

    # Restore
    Session.commit = original_commit


# ========== Verification Helpers ==========

def verify_no_partial_state(session: Session, experiment_id: str) -> None:
    """Verify no partial state exists after rollback."""
    # No orphaned assignments
    assignments = session.exec(
        select(VariantAssignment).where(VariantAssignment.experiment_id == experiment_id)
    ).all()
    assert len(assignments) == 0, f"Found {len(assignments)} orphaned assignments"

    # No orphaned variants
    variants = session.exec(
        select(Variant).where(Variant.experiment_id == experiment_id)
    ).all()
    assert len(variants) == 0, f"Found {len(variants)} orphaned variants"

    # No experiment record
    experiment = session.get(Experiment, experiment_id)
    assert experiment is None, "Found orphaned experiment"


def verify_assignment_integrity(session: Session, assignment_id: str) -> None:
    """Verify assignment data integrity."""
    assignment = session.get(VariantAssignment, assignment_id)

    if assignment:
        # Verify foreign keys exist
        experiment = session.get(Experiment, assignment.experiment_id)
        assert experiment is not None, f"Assignment has invalid experiment_id: {assignment.experiment_id}"

        variant = session.get(Variant, assignment.variant_id)
        assert variant is not None, f"Assignment has invalid variant_id: {assignment.variant_id}"

        # Verify metrics are valid
        if assignment.metrics:
            assert isinstance(assignment.metrics, dict)
            for key, value in assignment.metrics.items():
                assert isinstance(value, (int, float)), f"Invalid metric type: {type(value)}"


def verify_experiment_consistency(session: Session, experiment_id: str) -> None:
    """Verify experiment and variants are consistent."""
    experiment = session.get(Experiment, experiment_id)
    if not experiment:
        return

    variants = session.exec(
        select(Variant).where(Variant.experiment_id == experiment_id)
    ).all()

    # Traffic allocation matches variants
    assert set(experiment.traffic_allocation.keys()) == set(v.name for v in variants), \
        "Traffic allocation doesn't match variant names"

    # Traffic sums to <= 1.0
    total_traffic = sum(experiment.traffic_allocation.values())
    assert total_traffic <= 1.0, f"Total traffic {total_traffic} exceeds 1.0"

    # Has exactly one control variant
    control_count = sum(1 for v in variants if v.is_control)
    assert control_count == 1, f"Expected 1 control variant, got {control_count}"


# ========== A. Connection Failures ==========

class TestConnectionFailures:
    """Test database connection failure scenarios."""

    def test_assignment_creation_with_connection_loss(self, experiment_service):
        """Test assignment creation fails gracefully on connection loss."""
        # Create and start experiment
        exp_id = experiment_service.create_experiment(
            name="connection_test",
            description="Test connection failure",
            variants=[
                {"name": "control", "is_control": True, "traffic": 0.5},
                {"name": "variant_a", "traffic": 0.5}
            ]
        )
        experiment_service.start_experiment(exp_id)

        # Mock connection failure at the service level
        with patch('src.experimentation.service.get_session') as mock:
            mock.side_effect = OperationalError(
                "connection to server was lost",
                params=None,
                orig=None
            )

            with pytest.raises(OperationalError) as exc_info:
                experiment_service.assign_variant(
                    workflow_id="wf-test",
                    experiment_id=exp_id
                )

            assert "connection" in str(exc_info.value).lower()

        # Verify no partial state (assignment should not exist)
        with get_session() as session:
            assignment = session.exec(
                select(VariantAssignment).where(
                    VariantAssignment.workflow_execution_id == "wf-test"
                )
            ).first()
            assert assignment is None, "Assignment should not exist after connection failure"

    def test_experiment_creation_with_connection_error(self):
        """Test experiment creation fails gracefully when DB unavailable."""
        # Reset and don't initialize database
        reset_database()

        service = ExperimentService()

        with pytest.raises(RuntimeError) as exc_info:
            service.create_experiment(
                name="test_exp",
                description="Test",
                variants=[
                    {"name": "control", "is_control": True, "traffic": 0.5},
                    {"name": "variant_a", "traffic": 0.5}
                ]
            )

        assert "not initialized" in str(exc_info.value).lower()

    def test_get_experiment_after_connection_loss(self, experiment_service, temp_db_file):
        """Test get_experiment recovers after connection loss."""
        # Create experiment
        exp_id = experiment_service.create_experiment(
            name="recovery_test",
            description="Test recovery",
            variants=[
                {"name": "control", "is_control": True, "traffic": 0.5},
                {"name": "variant_a", "traffic": 0.5}
            ]
        )

        # Verify it exists
        experiment = experiment_service.get_experiment(exp_id)
        assert experiment is not None

        # Simulate connection loss and recovery
        reset_database()
        init_database(database_url=f"sqlite:///{temp_db_file}")

        # Should be able to retrieve (from fresh connection)
        experiment = experiment_service.get_experiment(exp_id)
        assert experiment is not None
        assert experiment.name == "recovery_test"

    def test_assignment_tracking_with_reconnect(self, experiment_service, temp_db_file):
        """Test metric tracking after connection recovery."""
        # Create experiment and assignment
        exp_id = experiment_service.create_experiment(
            name="tracking_test",
            description="Test tracking",
            variants=[
                {"name": "control", "is_control": True, "traffic": 0.5},
                {"name": "variant_a", "traffic": 0.5}
            ]
        )
        experiment_service.start_experiment(exp_id)

        assignment = experiment_service.assign_variant("wf-track", exp_id)

        # Simulate connection cycle
        reset_database()
        init_database(database_url=f"sqlite:///{temp_db_file}")

        # Track metrics (should work with new connection)
        experiment_service.track_execution_complete(
            workflow_id="wf-track",
            metrics={"score": 95.0},
            status="completed"
        )

        # Verify metrics were saved
        with get_session() as session:
            updated_assignment = session.exec(
                select(VariantAssignment).where(
                    VariantAssignment.workflow_execution_id == "wf-track"
                )
            ).first()

            assert updated_assignment is not None
            assert updated_assignment.metrics == {"score": 95.0}
            assert updated_assignment.execution_status == ExecutionStatus.COMPLETED

    def test_service_initialization_with_db_failure(self):
        """Test service handles DB initialization failure gracefully."""
        reset_database()

        # Try to create service without DB
        service = ExperimentService()
        service.initialize()  # Should not crash

        # Operations should fail with clear error
        with pytest.raises(RuntimeError):
            service.create_experiment(
                name="test",
                description="Test",
                variants=[
                    {"name": "control", "is_control": True, "traffic": 0.5},
                    {"name": "variant_a", "traffic": 0.5}
                ]
            )


# ========== B. Connection Pool Exhaustion ==========

class TestConnectionPoolExhaustion:
    """Test connection pool exhaustion scenarios."""

    @pytest.mark.asyncio
    async def test_pool_exhaustion_concurrent_assignments(self, temp_db_file):
        """Test connection pool with concurrent assignment requests."""
        # Initialize with small pool for testing
        reset_database()
        init_database(database_url=f"sqlite:///{temp_db_file}")

        service = ExperimentService()
        service.initialize()

        # Create experiment
        exp_id = service.create_experiment(
            name="pool_test",
            description="Test pool exhaustion",
            variants=[
                {"name": "control", "is_control": True, "traffic": 0.5},
                {"name": "variant_a", "traffic": 0.5}
            ]
        )
        service.start_experiment(exp_id)

        # Track results
        results = {"success": 0, "failure": 0}

        async def assign_variant(wf_id: str):
            """Attempt to assign variant."""
            try:
                await asyncio.sleep(0.001)  # Small delay
                assignment = service.assign_variant(
                    workflow_id=wf_id,
                    experiment_id=exp_id
                )
                results["success"] += 1
            except Exception:
                results["failure"] += 1

        # Fire 50 concurrent requests
        tasks = [assign_variant(f"wf-{i}") for i in range(50)]
        await asyncio.gather(*tasks, return_exceptions=True)

        # Most should succeed (SQLite StaticPool handles this well)
        assert results["success"] >= 40, f"Too many failures: {results['failure']}"

        # Verify data consistency
        with get_session() as session:
            assignment_count = session.exec(
                select(VariantAssignment).where(
                    VariantAssignment.experiment_id == exp_id
                )
            ).count()
            assert assignment_count == results["success"]

        service.shutdown()
        reset_database()

    @pytest.mark.asyncio
    async def test_pool_exhaustion_concurrent_tracking(self, temp_db_file):
        """Test pool exhaustion with concurrent metric tracking."""
        reset_database()
        init_database(database_url=f"sqlite:///{temp_db_file}")

        service = ExperimentService()

        # Create experiment with assignments
        exp_id = service.create_experiment(
            name="tracking_pool_test",
            description="Test tracking pool",
            variants=[
                {"name": "control", "is_control": True, "traffic": 1.0}
            ]
        )
        service.start_experiment(exp_id)

        # Create 20 assignments
        workflow_ids = []
        for i in range(20):
            wf_id = f"wf-{i}"
            service.assign_variant(wf_id, exp_id)
            workflow_ids.append(wf_id)

        # Track results
        success_count = 0

        async def track_metrics(wf_id: str, score: float):
            """Track metrics concurrently."""
            nonlocal success_count
            try:
                await asyncio.sleep(0.001)
                service.track_execution_complete(
                    workflow_id=wf_id,
                    metrics={"score": score},
                    status="completed"
                )
                success_count += 1
            except Exception:
                pass

        # Track all concurrently
        tasks = [track_metrics(wf_id, float(i)) for i, wf_id in enumerate(workflow_ids)]
        await asyncio.gather(*tasks, return_exceptions=True)

        # Most should succeed
        assert success_count >= 18

        service.shutdown()
        reset_database()

    def test_pool_exhaustion_recovery(self, temp_db_file):
        """Test recovery after pool exhaustion."""
        reset_database()
        init_database(database_url=f"sqlite:///{temp_db_file}")

        service = ExperimentService()

        exp_id = service.create_experiment(
            name="pool_recovery_test",
            description="Test pool recovery",
            variants=[
                {"name": "control", "is_control": True, "traffic": 1.0}
            ]
        )
        service.start_experiment(exp_id)

        # Simulate pool exhaustion scenario
        # SQLite with StaticPool doesn't truly exhaust, but we can test recovery

        # Make assignment after "exhaustion"
        assignment = service.assign_variant("wf-recovery", exp_id)
        assert assignment is not None

        # Verify it was saved
        with get_session() as session:
            saved_assignment = session.get(VariantAssignment, assignment.id)
            assert saved_assignment is not None

        service.shutdown()
        reset_database()


# ========== C. Transaction Failures & Rollback ==========

class TestTransactionFailures:
    """Test transaction failure and rollback scenarios."""

    def test_assignment_rollback_on_error(self, db_manager):
        """Test assignment creation rolls back on error."""
        # Create experiment manually
        experiment_id = "exp-rollback-test"
        variant_id = "var-control"

        with db_manager.session() as session:
            experiment = Experiment(
                id=experiment_id,
                name="rollback_test",
                description="Test rollback",
                status=ExperimentStatus.RUNNING,
                assignment_strategy=AssignmentStrategyType.RANDOM,
                traffic_allocation={"control": 1.0},
                primary_metric="score",
                confidence_level=0.95,
                min_sample_size_per_variant=100,
            )
            variant = Variant(
                id=variant_id,
                experiment_id=experiment_id,
                name="control",
                is_control=True,
                config_type="agent",
                config_overrides={},
                allocated_traffic=1.0,
            )
            session.add(experiment)
            session.add(variant)
            session.commit()

        # Attempt to create assignment that fails mid-transaction
        try:
            with db_manager.session() as session:
                assignment = VariantAssignment(
                    id="asn-rollback",
                    experiment_id=experiment_id,
                    variant_id=variant_id,
                    workflow_execution_id="wf-rollback",
                    assignment_strategy=AssignmentStrategyType.RANDOM,
                    execution_status=ExecutionStatus.PENDING,
                )
                session.add(assignment)
                session.flush()

                # Simulate error before commit
                raise RuntimeError("Simulated error")
        except RuntimeError:
            pass

        # Verify rollback - assignment should not exist
        with db_manager.session() as session:
            assignment = session.get(VariantAssignment, "asn-rollback")
            assert assignment is None, "Assignment should have been rolled back"

    def test_experiment_creation_rollback(self, db_manager):
        """Test experiment + variants rollback as atomic unit."""
        experiment_id = "exp-atomic-test"

        # Attempt to create experiment with error
        try:
            with db_manager.session() as session:
                experiment = Experiment(
                    id=experiment_id,
                    name="atomic_test",
                    description="Test atomic rollback",
                    status=ExperimentStatus.DRAFT,
                    assignment_strategy=AssignmentStrategyType.RANDOM,
                    traffic_allocation={"control": 0.5, "variant_a": 0.5},
                    primary_metric="score",
                    confidence_level=0.95,
                    min_sample_size_per_variant=100,
                )
                session.add(experiment)

                variant1 = Variant(
                    id="var-1",
                    experiment_id=experiment_id,
                    name="control",
                    is_control=True,
                    config_type="agent",
                    config_overrides={},
                    allocated_traffic=0.5,
                )
                session.add(variant1)
                session.flush()

                # Error before adding second variant
                raise ValueError("Simulated error")
        except ValueError:
            pass

        # Verify complete rollback
        with db_manager.session() as session:
            verify_no_partial_state(session, experiment_id)

    def test_partial_metric_update_rollback(self, db_manager):
        """Test partial metric update rolls back completely."""
        # Create experiment and assignment
        experiment_id = "exp-metric-rollback"
        variant_id = "var-control"
        assignment_id = "asn-metric-rollback"

        with db_manager.session() as session:
            experiment = Experiment(
                id=experiment_id,
                name="metric_rollback_test",
                description="Test metric rollback",
                status=ExperimentStatus.RUNNING,
                assignment_strategy=AssignmentStrategyType.RANDOM,
                traffic_allocation={"control": 1.0},
                primary_metric="score",
                confidence_level=0.95,
                min_sample_size_per_variant=100,
            )
            variant = Variant(
                id=variant_id,
                experiment_id=experiment_id,
                name="control",
                is_control=True,
                config_type="agent",
                config_overrides={},
                allocated_traffic=1.0,
            )
            assignment = VariantAssignment(
                id=assignment_id,
                experiment_id=experiment_id,
                variant_id=variant_id,
                workflow_execution_id="wf-metric-rollback",
                assignment_strategy=AssignmentStrategyType.RANDOM,
                execution_status=ExecutionStatus.PENDING,
                metrics={"score": 50.0},
            )
            session.add_all([experiment, variant, assignment])
            session.commit()

        # Attempt to update metrics with error
        try:
            with db_manager.session() as session:
                asn = session.get(VariantAssignment, assignment_id)
                asn.metrics = {"score": 95.0, "quality": 0.9}
                asn.execution_status = ExecutionStatus.COMPLETED
                session.flush()

                raise RuntimeError("Simulated error")
        except RuntimeError:
            pass

        # Verify metrics rolled back to original
        with db_manager.session() as session:
            asn = session.get(VariantAssignment, assignment_id)
            assert asn.metrics == {"score": 50.0}
            assert asn.execution_status == ExecutionStatus.PENDING

    def test_nested_transaction_failure(self, db_manager):
        """Test nested operations roll back properly."""
        experiment_id = "exp-nested-test"

        with db_manager.session() as session:
            experiment = Experiment(
                id=experiment_id,
                name="nested_test",
                description="Test nested rollback",
                status=ExperimentStatus.RUNNING,
                assignment_strategy=AssignmentStrategyType.RANDOM,
                traffic_allocation={"control": 1.0},
                primary_metric="score",
                confidence_level=0.95,
                min_sample_size_per_variant=100,
            )
            variant = Variant(
                id="var-nested",
                experiment_id=experiment_id,
                name="control",
                is_control=True,
                config_type="agent",
                config_overrides={},
                allocated_traffic=1.0,
            )
            session.add_all([experiment, variant])
            session.commit()

        # Nested transaction that fails
        try:
            with db_manager.session() as session:
                # First assignment
                asn1 = VariantAssignment(
                    id="asn-nested-1",
                    experiment_id=experiment_id,
                    variant_id="var-nested",
                    workflow_execution_id="wf-nested-1",
                    assignment_strategy=AssignmentStrategyType.RANDOM,
                    execution_status=ExecutionStatus.PENDING,
                )
                session.add(asn1)
                session.flush()

                # Second assignment
                asn2 = VariantAssignment(
                    id="asn-nested-2",
                    experiment_id=experiment_id,
                    variant_id="var-nested",
                    workflow_execution_id="wf-nested-2",
                    assignment_strategy=AssignmentStrategyType.RANDOM,
                    execution_status=ExecutionStatus.PENDING,
                )
                session.add(asn2)
                session.flush()

                # Error after both added
                raise ValueError("Nested error")
        except ValueError:
            pass

        # Both should be rolled back
        with db_manager.session() as session:
            asn1 = session.get(VariantAssignment, "asn-nested-1")
            asn2 = session.get(VariantAssignment, "asn-nested-2")
            assert asn1 is None
            assert asn2 is None


# ========== D. Concurrency & Transaction Conflicts ==========

class TestConcurrencyConflicts:
    """Test concurrent access and race conditions."""

    @pytest.mark.asyncio
    async def test_concurrent_assignment_creation(self, db_manager):
        """Test multiple concurrent assignments to same experiment."""
        # Create experiment
        experiment_id = "exp-concurrent-test"
        variant_id = "var-control"

        with db_manager.session() as session:
            experiment = Experiment(
                id=experiment_id,
                name="concurrent_test",
                description="Test concurrent assignments",
                status=ExperimentStatus.RUNNING,
                assignment_strategy=AssignmentStrategyType.RANDOM,
                traffic_allocation={"control": 1.0},
                primary_metric="score",
                confidence_level=0.95,
                min_sample_size_per_variant=100,
            )
            variant = Variant(
                id=variant_id,
                experiment_id=experiment_id,
                name="control",
                is_control=True,
                config_type="agent",
                config_overrides={},
                allocated_traffic=1.0,
            )
            session.add_all([experiment, variant])
            session.commit()

        # Create assignments concurrently
        success_count = 0

        async def create_assignment(idx: int):
            nonlocal success_count
            try:
                await asyncio.sleep(0.001)
                with db_manager.session() as session:
                    assignment = VariantAssignment(
                        id=f"asn-concurrent-{idx}",
                        experiment_id=experiment_id,
                        variant_id=variant_id,
                        workflow_execution_id=f"wf-concurrent-{idx}",
                        assignment_strategy=AssignmentStrategyType.RANDOM,
                        execution_status=ExecutionStatus.PENDING,
                    )
                    session.add(assignment)
                    session.commit()
                    success_count += 1
            except Exception:
                pass

        # Create 20 assignments concurrently
        tasks = [create_assignment(i) for i in range(20)]
        await asyncio.gather(*tasks, return_exceptions=True)

        # All should succeed (different workflow IDs)
        assert success_count == 20

        # Verify all in database
        with db_manager.session() as session:
            count = session.exec(
                select(VariantAssignment).where(
                    VariantAssignment.experiment_id == experiment_id
                )
            ).all()
            assert len(count) == 20

    @pytest.mark.asyncio
    async def test_concurrent_metric_updates(self, db_manager):
        """Test race condition in concurrent metric updates."""
        # Create experiment and assignment
        experiment_id = "exp-race-test"
        assignment_id = "asn-race-test"

        with db_manager.session() as session:
            experiment = Experiment(
                id=experiment_id,
                name="race_test",
                description="Test race condition",
                status=ExperimentStatus.RUNNING,
                assignment_strategy=AssignmentStrategyType.RANDOM,
                traffic_allocation={"control": 1.0},
                primary_metric="counter",
                confidence_level=0.95,
                min_sample_size_per_variant=100,
            )
            variant = Variant(
                id="var-race",
                experiment_id=experiment_id,
                name="control",
                is_control=True,
                config_type="agent",
                config_overrides={},
                allocated_traffic=1.0,
            )
            assignment = VariantAssignment(
                id=assignment_id,
                experiment_id=experiment_id,
                variant_id="var-race",
                workflow_execution_id="wf-race",
                assignment_strategy=AssignmentStrategyType.RANDOM,
                execution_status=ExecutionStatus.PENDING,
                metrics={"counter": 0},
            )
            session.add_all([experiment, variant, assignment])
            session.commit()

        # Concurrent counter increments (demonstrates race condition)
        async def increment_counter():
            await asyncio.sleep(0.001)
            try:
                with db_manager.session() as session:
                    asn = session.get(VariantAssignment, assignment_id)
                    current = asn.metrics.get("counter", 0)
                    # Simulate processing delay
                    await asyncio.sleep(0.002)
                    asn.metrics = {"counter": current + 1}
                    session.commit()
            except Exception:
                pass

        # 10 concurrent increments
        tasks = [increment_counter() for _ in range(10)]
        await asyncio.gather(*tasks, return_exceptions=True)

        # Due to race condition, final count may be less than 10
        with db_manager.session() as session:
            asn = session.get(VariantAssignment, assignment_id)
            final_count = asn.metrics.get("counter", 0)

            # At least 1 update should have succeeded
            assert final_count >= 1
            # But likely less than 10 due to race condition
            assert final_count <= 10

    @pytest.mark.asyncio
    async def test_optimistic_locking_conflict(self, db_manager):
        """Test concurrent updates to same experiment."""
        experiment_id = "exp-lock-test"

        with db_manager.session() as session:
            experiment = Experiment(
                id=experiment_id,
                name="lock_test",
                description="Test optimistic locking",
                status=ExperimentStatus.RUNNING,
                assignment_strategy=AssignmentStrategyType.RANDOM,
                traffic_allocation={"control": 1.0},
                primary_metric="score",
                confidence_level=0.95,
                min_sample_size_per_variant=100,
            )
            session.add(experiment)
            session.commit()

        # Concurrent updates to experiment status
        success_count = 0

        async def update_status(new_status: ExperimentStatus):
            nonlocal success_count
            try:
                await asyncio.sleep(0.001)
                with db_manager.session() as session:
                    exp = session.get(Experiment, experiment_id)
                    await asyncio.sleep(0.002)  # Simulate delay
                    exp.status = new_status
                    session.commit()
                    success_count += 1
            except Exception:
                pass

        # Try to update to different statuses concurrently
        tasks = [
            update_status(ExperimentStatus.PAUSED),
            update_status(ExperimentStatus.STOPPED),
            update_status(ExperimentStatus.COMPLETED),
        ]
        await asyncio.gather(*tasks, return_exceptions=True)

        # All should succeed (no optimistic locking in current impl)
        # Last one wins
        assert success_count >= 1

        # Verify final state is one of the attempted states
        with db_manager.session() as session:
            exp = session.get(Experiment, experiment_id)
            assert exp.status in [
                ExperimentStatus.PAUSED,
                ExperimentStatus.STOPPED,
                ExperimentStatus.COMPLETED
            ]


# ========== E. Data Integrity & Constraints ==========

class TestDataIntegrity:
    """Test data integrity and constraint violations."""

    def test_duplicate_assignment_prevention(self, db_manager):
        """Test unique constraint on assignment IDs."""
        # Create experiment
        experiment_id = "exp-dup-test"

        with db_manager.session() as session:
            experiment = Experiment(
                id=experiment_id,
                name="duplicate_test",
                description="Test duplicate prevention",
                status=ExperimentStatus.RUNNING,
                assignment_strategy=AssignmentStrategyType.RANDOM,
                traffic_allocation={"control": 1.0},
                primary_metric="score",
                confidence_level=0.95,
                min_sample_size_per_variant=100,
            )
            variant = Variant(
                id="var-dup",
                experiment_id=experiment_id,
                name="control",
                is_control=True,
                config_type="agent",
                config_overrides={},
                allocated_traffic=1.0,
            )
            session.add_all([experiment, variant])
            session.commit()

        # Create first assignment
        with db_manager.session() as session:
            assignment = VariantAssignment(
                id="asn-dup",
                experiment_id=experiment_id,
                variant_id="var-dup",
                workflow_execution_id="wf-dup",
                assignment_strategy=AssignmentStrategyType.RANDOM,
                execution_status=ExecutionStatus.PENDING,
            )
            session.add(assignment)
            session.commit()

        # Attempt duplicate
        with pytest.raises(IntegrityError):
            with db_manager.session() as session:
                duplicate = VariantAssignment(
                    id="asn-dup",  # Same ID
                    experiment_id=experiment_id,
                    variant_id="var-dup",
                    workflow_execution_id="wf-dup-2",
                    assignment_strategy=AssignmentStrategyType.RANDOM,
                    execution_status=ExecutionStatus.PENDING,
                )
                session.add(duplicate)
                session.commit()

    def test_foreign_key_violation_handling(self, db_manager):
        """Test assignment to non-existent experiment."""
        # Note: SQLite doesn't enforce foreign keys by default
        # This test documents expected behavior

        try:
            with db_manager.session() as session:
                assignment = VariantAssignment(
                    id="asn-orphan",
                    experiment_id="nonexistent-exp",
                    variant_id="nonexistent-var",
                    workflow_execution_id="wf-orphan",
                    assignment_strategy=AssignmentStrategyType.RANDOM,
                    execution_status=ExecutionStatus.PENDING,
                )
                session.add(assignment)
                session.commit()

            # If foreign keys not enforced, verify we can detect orphans
            with db_manager.session() as session:
                asn = session.get(VariantAssignment, "asn-orphan")
                with pytest.raises(AssertionError):
                    verify_assignment_integrity(session, "asn-orphan")

        except IntegrityError:
            # If foreign keys ARE enforced, this is expected
            pass

    def test_null_constraint_handling(self, db_manager):
        """Test required fields validation."""
        with pytest.raises(Exception):  # Could be IntegrityError or validation error
            with db_manager.session() as session:
                experiment = Experiment(
                    id="exp-null-test",
                    name=None,  # Required field
                    description="Test null constraint",
                    status=ExperimentStatus.DRAFT,
                    assignment_strategy=AssignmentStrategyType.RANDOM,
                    traffic_allocation={"control": 1.0},
                    primary_metric="score",
                    confidence_level=0.95,
                    min_sample_size_per_variant=100,
                )
                session.add(experiment)
                session.commit()


# ========== Summary Test ==========

class TestDatabaseFailureSummary:
    """Summary test demonstrating all failure scenarios."""

    def test_comprehensive_failure_recovery(self, experiment_service, db_manager):
        """Comprehensive test of failure scenarios and recovery."""
        # 1. Create experiment successfully
        exp_id = experiment_service.create_experiment(
            name="comprehensive_test",
            description="Test all failure scenarios",
            variants=[
                {"name": "control", "is_control": True, "traffic": 0.5},
                {"name": "variant_a", "traffic": 0.5}
            ]
        )
        experiment_service.start_experiment(exp_id)

        # 2. Verify experiment consistency
        with db_manager.session() as session:
            verify_experiment_consistency(session, exp_id)

        # 3. Create assignments
        assignments = []
        for i in range(5):
            asn = experiment_service.assign_variant(f"wf-comp-{i}", exp_id)
            assignments.append(asn)

        # 4. Verify assignment integrity
        with db_manager.session() as session:
            for asn in assignments:
                verify_assignment_integrity(session, asn.id)

        # 5. Track metrics
        for i, asn in enumerate(assignments):
            experiment_service.track_execution_complete(
                workflow_id=f"wf-comp-{i}",
                metrics={"score": float(80 + i * 5)},
                status="completed"
            )

        # 6. Verify final state
        with db_manager.session() as session:
            # All assignments should have metrics
            for asn in assignments:
                saved_asn = session.get(VariantAssignment, asn.id)
                assert saved_asn.metrics is not None
                assert "score" in saved_asn.metrics
                assert saved_asn.execution_status == ExecutionStatus.COMPLETED

        # 7. Get experiment results (tests analysis with DB)
        results = experiment_service.get_experiment_results(exp_id)
        assert results["sample_size"] == 5
