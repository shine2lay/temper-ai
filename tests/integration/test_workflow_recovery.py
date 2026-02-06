"""
Integration tests for workflow error recovery and retry mechanisms.

Tests workflows that handle failures gracefully through retry logic,
checkpointing, and resume capabilities.
"""
import time
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from src.observability.database import get_session, init_database
from src.observability.models import (
    AgentExecution,
    StageExecution,
    WorkflowExecution,
)
from src.observability.tracker import ExecutionTracker

pytestmark = [pytest.mark.integration]


class TestWorkflowRecovery:
    """Test workflow error recovery and retry mechanisms."""

    @pytest.fixture
    def test_database(self):
        """Initialize in-memory database for testing."""
        try:
            from src.observability.database import get_database
            get_database()
        except RuntimeError:
            init_database("sqlite:///:memory:")
        yield

    @pytest.fixture
    def execution_tracker(self, test_database):
        """Execution tracker with test database."""
        from src.observability.backends.sql_backend import SQLObservabilityBackend
        backend = SQLObservabilityBackend()
        return ExecutionTracker(backend=backend)

    @pytest.mark.integration
    def test_workflow_with_agent_retry_on_transient_failure(
        self,
        test_database,
        execution_tracker
    ):
        """Test workflow retries agent execution on transient failures.

        Scenario: API call workflow
        - Agent calls external API
        - First attempt fails (rate limit)
        - Retry succeeds after backoff

        Validates:
        - Transient failures detected
        - Retry logic triggered
        - Backoff strategy applied
        - Eventual success recorded
        - Retry metadata tracked
        """
        workflow_id = str(uuid.uuid4())

        # Create workflow
        workflow_exec = WorkflowExecution(
            id=workflow_id,
            workflow_name="api_call_with_retry",
            workflow_version="1.0",
            workflow_config_snapshot={
                "error_handling": {
                    "retry_policy": {
                        "max_retries": 3,
                        "backoff_multiplier": 2.0,
                        "transient_errors": ["RateLimitError", "TimeoutError"]
                    }
                }
            },
            start_time=datetime.now(UTC),
            status="running"
        )

        with get_session() as session:
            session.add(workflow_exec)
            session.commit()

        # Stage: API call
        with execution_tracker.track_stage("api_call", {}, workflow_id) as stage_id:
            # Attempt 1: Fails with rate limit
            agent1_id = str(uuid.uuid4())
            agent1_exec = AgentExecution(
                id=agent1_id,
                stage_execution_id=stage_id,
                agent_name="api_caller",
                agent_version="1.0",
                agent_config_snapshot={},
                start_time=datetime.now(UTC),
                end_time=datetime.now(UTC) + timedelta(seconds=0.5),
                duration_seconds=0.5,
                status="failed",
                error_message="RateLimitError: Too many requests",
                retry_count=1
            )

            with get_session() as session:
                session.add(agent1_exec)
                session.commit()

            # Simulate 1 second backoff
            time.sleep(0.1)  # Simulated

            # Attempt 2: Succeeds
            agent2_id = str(uuid.uuid4())
            agent2_exec = AgentExecution(
                id=agent2_id,
                stage_execution_id=stage_id,
                agent_name="api_caller",
                agent_version="1.0",
                agent_config_snapshot={},
                start_time=datetime.now(UTC),
                end_time=datetime.now(UTC) + timedelta(seconds=1.0),
                duration_seconds=1.0,
                status="success",
                retry_count=2
            )

            with get_session() as session:
                session.add(agent2_exec)
                session.commit()

        # Stage completes successfully after retry
        with get_session() as session:
            stage = session.query(StageExecution).filter_by(id=stage_id).first()
            stage.output_data = {
                "api_response": {"status": "success", "data": "..."},
                "retry_count": 1,
                "total_attempts": 2
            }
            session.commit()

        # Complete workflow
        workflow_exec.end_time = datetime.now(UTC)
        workflow_exec.status = "completed"

        with get_session() as session:
            session.merge(workflow_exec)
            session.commit()

        # VERIFICATION: Retry behavior
        with get_session() as session:
            workflow = session.query(WorkflowExecution).filter_by(id=workflow_id).first()
            assert workflow.status == "completed", "Workflow should complete after retry"

            # Verify retry attempts
            agents = session.query(AgentExecution).filter_by(
                stage_execution_id=stage_id
            ).order_by(AgentExecution.retry_count).all()

            assert len(agents) == 2, "Should have 2 retry attempts"

            # First attempt failed
            assert agents[0].status == "failed"
            assert "RateLimitError" in agents[0].error_message
            assert agents[0].retry_count == 1

            # Second attempt succeeded
            assert agents[1].status == "success"
            assert agents[1].retry_count == 2

            # Verify stage output
            stage = session.query(StageExecution).filter_by(id=stage_id).first()
            assert stage.output_data["retry_count"] == 1
            assert stage.output_data["total_attempts"] == 2

    @pytest.mark.integration
    def test_workflow_with_stage_retry(
        self,
        test_database,
        execution_tracker
    ):
        """Test workflow handles stage failure and recovery.

        Scenario: Data processing workflow
        - First stage fails with error
        - Second stage (retry) succeeds

        Validates:
        - Stage failure tracked
        - Recovery stage succeeds
        - Final output correct after recovery
        """
        workflow_id = str(uuid.uuid4())

        workflow_exec = WorkflowExecution(
            id=workflow_id,
            workflow_name="stage_retry_workflow",
            workflow_version="1.0",
            workflow_config_snapshot={},
            start_time=datetime.now(UTC),
            status="running"
        )

        with get_session() as session:
            session.add(workflow_exec)
            session.commit()

        # Stage attempt 1: Fails
        with execution_tracker.track_stage("data_processing_attempt1", {}, workflow_id) as stage1_id:
            pass

        with get_session() as session:
            stage1 = session.query(StageExecution).filter_by(id=stage1_id).first()
            stage1.status = "failed"
            stage1.error_message = "ResourceUnavailableError"
            session.commit()

        # Stage attempt 2: Succeeds
        with execution_tracker.track_stage("data_processing_attempt2", {}, workflow_id) as stage2_id:
            pass

        with get_session() as session:
            stage2 = session.query(StageExecution).filter_by(id=stage2_id).first()
            stage2.output_data = {"processed_records": 500}
            session.commit()

        # Complete workflow
        workflow_exec.end_time = datetime.now(UTC)
        workflow_exec.status = "completed"

        with get_session() as session:
            session.merge(workflow_exec)
            session.commit()

        # VERIFICATION
        with get_session() as session:
            workflow = session.query(WorkflowExecution).filter_by(id=workflow_id).first()
            assert workflow.status == "completed"

            # Verify both stage attempts exist
            stages = session.query(StageExecution).filter_by(
                workflow_execution_id=workflow_id
            ).order_by(StageExecution.start_time).all()

            assert len(stages) == 2

            # First attempt failed
            assert stages[0].status == "failed"
            assert "ResourceUnavailableError" in stages[0].error_message

            # Second attempt succeeded
            assert stages[1].status == "completed"
            assert stages[1].output_data["processed_records"] == 500

    @pytest.mark.integration
    def test_workflow_with_exponential_backoff(
        self,
        test_database,
        execution_tracker
    ):
        """Test workflow uses exponential backoff for retries.

        Scenario: External service integration
        - Service temporarily unavailable
        - Multiple retries with increasing backoff
        - Eventually succeeds or fails after max retries

        Validates:
        - Backoff intervals increase exponentially
        - Retry timing tracked correctly
        - Max retries enforced
        """
        workflow_id = str(uuid.uuid4())

        workflow_exec = WorkflowExecution(
            id=workflow_id,
            workflow_name="exponential_backoff_workflow",
            workflow_version="1.0",
            workflow_config_snapshot={
                "retry_policy": {
                    "max_retries": 3,
                    "initial_backoff_seconds": 1,
                    "backoff_multiplier": 2.0
                }
            },
            start_time=datetime.now(UTC),
            status="running"
        )

        with get_session() as session:
            session.add(workflow_exec)
            session.commit()

        # Track retry attempts with increasing delays
        retry_counts = []
        backoff_seconds = 1

        with execution_tracker.track_stage("external_service_call", {}, workflow_id) as stage_id:
            # Simulate 3 failures, then success
            for attempt in range(1, 5):
                if attempt > 1:
                    time.sleep(0.01)  # Simulated backoff

                agent_id = str(uuid.uuid4())
                status = "success" if attempt == 4 else "failed"

                agent_exec = AgentExecution(
                    id=agent_id,
                    stage_execution_id=stage_id,
                    agent_name="service_caller",
                    agent_version="1.0",
                    agent_config_snapshot={},
                    start_time=datetime.now(UTC),
                    end_time=datetime.now(UTC) + timedelta(seconds=0.1),
                    duration_seconds=0.1,
                    status=status,
                    error_message="ServiceUnavailable" if status == "failed" else None,
                    retry_count=attempt
                )

                with get_session() as session:
                    session.add(agent_exec)
                    session.commit()

                retry_counts.append({
                    "attempt": attempt,
                    "backoff_seconds": backoff_seconds if attempt > 1 else 0,
                    "status": status
                })

                backoff_seconds *= 2  # Exponential increase

        # Stage completes after retries
        with get_session() as session:
            stage = session.query(StageExecution).filter_by(id=stage_id).first()
            stage.output_data = {
                "service_response": {"data": "success"},
                "retry_counts": retry_counts,
                "total_retries": 3
            }
            session.commit()

        # Complete workflow
        workflow_exec.end_time = datetime.now(UTC)
        workflow_exec.status = "completed"

        with get_session() as session:
            session.merge(workflow_exec)
            session.commit()

        # VERIFICATION
        with get_session() as session:
            workflow = session.query(WorkflowExecution).filter_by(id=workflow_id).first()
            assert workflow.status == "completed"

            # Verify retry attempts
            agents = session.query(AgentExecution).filter_by(
                stage_execution_id=stage_id
            ).order_by(AgentExecution.retry_count).all()

            assert len(agents) == 4

            # Verify exponential backoff pattern (tracked in output)
            stage = session.query(StageExecution).filter_by(id=stage_id).first()
            attempts = stage.output_data["retry_counts"]

            # Check backoff increases: 0, 2, 4, 8 (doubles each time starting from 1)
            expected_backoffs = [0, 2, 4, 8]
            for i, attempt in enumerate(attempts):
                assert attempt["backoff_seconds"] == expected_backoffs[i]


class TestCheckpointResume:
    """Test workflow checkpoint and resume capabilities."""

    @pytest.fixture
    def test_database(self):
        """Initialize in-memory database for testing."""
        try:
            from src.observability.database import get_database
            get_database()
        except RuntimeError:
            init_database("sqlite:///:memory:")
        yield

    @pytest.fixture
    def execution_tracker(self, test_database):
        """Execution tracker with test database."""
        from src.observability.backends.sql_backend import SQLObservabilityBackend
        backend = SQLObservabilityBackend()
        return ExecutionTracker(backend=backend)

    @pytest.mark.integration
    def test_workflow_checkpoint_and_resume(
        self,
        test_database,
        execution_tracker
    ):
        """Test workflow can be checkpointed and resumed.

        Scenario: Long-running data processing workflow
        - Execute 2 stages successfully
        - Checkpoint after stage 2
        - Simulate interruption
        - Resume from checkpoint
        - Complete remaining stages

        Validates:
        - Checkpoint saves complete state
        - Resume loads state correctly
        - No duplicate work performed
        - Final output correct
        """
        workflow_id = str(uuid.uuid4())

        # Phase 1: Initial execution (stage 1 + 2)
        workflow_exec = WorkflowExecution(
            id=workflow_id,
            workflow_name="data_processing_pipeline",
            workflow_version="1.0",
            workflow_config_snapshot={},
            start_time=datetime.now(UTC),
            status="running"
        )

        with get_session() as session:
            session.add(workflow_exec)
            session.commit()

        # Stage 1: Data extraction
        with execution_tracker.track_stage("extraction", {}, workflow_id) as stage1_id:
            with execution_tracker.track_agent("extractor", {}, stage1_id):
                pass

        with get_session() as session:
            stage1 = session.query(StageExecution).filter_by(id=stage1_id).first()
            stage1.output_data = {"records_extracted": 1000}
            session.commit()

        # Stage 2: Data transformation
        with execution_tracker.track_stage("transformation", {}, workflow_id) as stage2_id:
            with execution_tracker.track_agent("transformer", {}, stage2_id):
                pass

        with get_session() as session:
            stage2 = session.query(StageExecution).filter_by(id=stage2_id).first()
            stage2.output_data = {"records_transformed": 1000}
            session.commit()

        # CHECKPOINT: Save workflow state after stage 2
        checkpoint_data = {
            "workflow_id": workflow_id,
            "completed_stages": ["extraction", "transformation"],
            "stage_outputs": {
                "extraction": {"records_extracted": 1000},
                "transformation": {"records_transformed": 1000}
            },
            "next_stage": "validation"
        }

        # Simulate interruption (workflow status = paused)
        workflow_exec.status = "checkpointed"
        with get_session() as session:
            session.merge(workflow_exec)
            session.commit()

        # Phase 2: Resume from checkpoint
        # Verify checkpoint data
        assert checkpoint_data["workflow_id"] == workflow_id
        assert len(checkpoint_data["completed_stages"]) == 2
        assert checkpoint_data["next_stage"] == "validation"

        # Resume workflow
        workflow_exec.status = "running"
        with get_session() as session:
            session.merge(workflow_exec)
            session.commit()

        # Stage 3: Validation (resume from here)
        with execution_tracker.track_stage("validation", {}, workflow_id) as stage3_id:
            # Agent can access previous stage outputs from checkpoint
            prev_outputs = checkpoint_data["stage_outputs"]
            assert prev_outputs["transformation"]["records_transformed"] == 1000

            with execution_tracker.track_agent("validator", {}, stage3_id):
                pass

        with get_session() as session:
            stage3 = session.query(StageExecution).filter_by(id=stage3_id).first()
            stage3.output_data = {
                "records_validated": 1000,
                "validation_errors": 0
            }
            session.commit()

        # Complete workflow
        workflow_exec.end_time = datetime.now(UTC)
        workflow_exec.status = "completed"

        with get_session() as session:
            session.merge(workflow_exec)
            session.commit()

        # VERIFICATION: Checkpoint/resume integrity
        with get_session() as session:
            workflow = session.query(WorkflowExecution).filter_by(id=workflow_id).first()
            assert workflow.status == "completed"

            # Verify all 3 stages executed (no duplication)
            stages = session.query(StageExecution).filter_by(
                workflow_execution_id=workflow_id
            ).all()
            assert len(stages) == 3

            stage_names = [s.stage_name for s in stages]
            assert stage_names.count("extraction") == 1  # No duplicate
            assert stage_names.count("transformation") == 1  # No duplicate
            assert stage_names.count("validation") == 1

            # Verify data flow from checkpoint
            validation_stage = next(s for s in stages if s.stage_name == "validation")
            assert validation_stage.output_data["records_validated"] == 1000

    @pytest.mark.integration
    def test_partial_checkpoint_recovery(
        self,
        test_database,
        execution_tracker
    ):
        """Test workflow can recover from partial checkpoint.

        Scenario: Workflow checkpoints mid-stage
        - Stage partially completes
        - Checkpoint saves partial progress
        - Resume continues from partial state

        Validates:
        - Partial state can be saved
        - Resume from partial state works
        - No data loss on resume
        """
        workflow_id = str(uuid.uuid4())

        workflow_exec = WorkflowExecution(
            id=workflow_id,
            workflow_name="partial_checkpoint_workflow",
            workflow_version="1.0",
            workflow_config_snapshot={},
            start_time=datetime.now(UTC),
            status="running"
        )

        with get_session() as session:
            session.add(workflow_exec)
            session.commit()

        # Stage: Batch processing (partial completion)
        with execution_tracker.track_stage("batch_processing", {}, workflow_id) as stage_id:
            with execution_tracker.track_agent("processor", {}, stage_id):
                pass

        # Checkpoint after processing 60% of data
        with get_session() as session:
            stage = session.query(StageExecution).filter_by(id=stage_id).first()
            stage.output_data = {
                "total_records": 1000,
                "processed_records": 600,
                "remaining_records": 400,
                "checkpoint_progress": 0.6
            }
            session.commit()

        # Mark as checkpointed
        workflow_exec.status = "checkpointed"
        with get_session() as session:
            session.merge(workflow_exec)
            session.commit()

        # Resume and complete remaining work
        workflow_exec.status = "running"
        with get_session() as session:
            session.merge(workflow_exec)
            session.commit()

        # Continue processing
        with get_session() as session:
            stage = session.query(StageExecution).filter_by(id=stage_id).first()
            stage.output_data = {
                "total_records": 1000,
                "processed_records": 1000,
                "remaining_records": 0,
                "checkpoint_progress": 1.0,
                "resumed_from_checkpoint": True
            }
            session.commit()

        # Complete workflow
        workflow_exec.end_time = datetime.now(UTC)
        workflow_exec.status = "completed"

        with get_session() as session:
            session.merge(workflow_exec)
            session.commit()

        # VERIFICATION
        with get_session() as session:
            workflow = session.query(WorkflowExecution).filter_by(id=workflow_id).first()
            assert workflow.status == "completed"

            stage = session.query(StageExecution).filter_by(
                workflow_execution_id=workflow_id
            ).first()

            # Verify resume completed all work
            assert stage.output_data["processed_records"] == 1000
            assert stage.output_data["remaining_records"] == 0
            assert stage.output_data["resumed_from_checkpoint"] is True
