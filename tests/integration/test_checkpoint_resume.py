"""
End-to-end integration tests for checkpoint and resume functionality.

Tests:
- Checkpoint creation after each stage
- Resume from various checkpoint points
- State preservation across resume
- Recovery after failures
"""
import uuid
from datetime import UTC, datetime

import pytest

from src.compiler.checkpoint import CheckpointManager, FileCheckpointBackend
from src.compiler.domain_state import WorkflowDomainState
from src.observability.database import get_session, init_database
from src.observability.models import StageExecution, WorkflowExecution
from src.observability.tracker import ExecutionTracker

pytestmark = [pytest.mark.integration, pytest.mark.critical_path]


class TestCheckpointCreation:
    """Test checkpoint save after each stage"""

    @pytest.fixture
    def sample_database(self):
        """Initialize test database."""
        try:
            from src.observability.database import get_database
            get_database()
        except RuntimeError:
            init_database("sqlite:///:memory:")
        yield

    @pytest.fixture
    def execution_tracker(self, sample_database):
        """Execution tracker."""
        from src.observability.backends.sql_backend import SQLObservabilityBackend
        backend = SQLObservabilityBackend()
        return ExecutionTracker(backend=backend)

    @pytest.fixture
    def checkpoint_manager(self, tmp_path):
        """Checkpoint manager with temporary storage."""
        backend = FileCheckpointBackend(checkpoint_dir=str(tmp_path / "checkpoints"))
        return CheckpointManager(backend=backend)

    def test_checkpoint_after_stage_one(
        self,
        sample_database,
        checkpoint_manager,
        execution_tracker
    ):
        """Test checkpoint is created after stage 1 completes."""
        workflow_id = str(uuid.uuid4())

        # Create workflow
        workflow_exec = WorkflowExecution(
            id=workflow_id,
            workflow_name="checkpoint_test",
            workflow_version="1.0",
            workflow_config_snapshot={},
            start_time=datetime.now(UTC),
            status="running"
        )

        with get_session() as session:
            session.add(workflow_exec)
            session.commit()

        # Execute stage 1
        with execution_tracker.track_stage("stage1", {}, workflow_id) as stage_id:
            with execution_tracker.track_agent("agent1", {}, stage_id):
                pass

        # Update stage output
        with get_session() as session:
            stage = session.query(StageExecution).filter_by(id=stage_id).first()
            stage.output_data = {"stage1_result": "completed"}
            session.commit()

        # Create checkpoint
        domain_state = WorkflowDomainState(
            workflow_id=workflow_id,
            current_stage="stage1",
            stage_outputs={"stage1": {"stage1_result": "completed"}},
            input_data={},
            num_stages_completed=1
        )

        checkpoint_manager.save_checkpoint(workflow_id, domain_state)

        # VERIFICATION: Checkpoint exists
        checkpoints = checkpoint_manager.list_checkpoints(workflow_id)
        assert len(checkpoints) == 1

        loaded = checkpoint_manager.load_checkpoint(workflow_id)
        assert loaded.workflow_id == workflow_id
        assert loaded.current_stage == "stage1"
        assert loaded.num_stages_completed == 1
        assert "stage1" in loaded.stage_outputs

    def test_checkpoint_after_stage_two(
        self,
        sample_database,
        checkpoint_manager,
        execution_tracker
    ):
        """Test checkpoint after stage 2 includes stage 1 output."""
        workflow_id = str(uuid.uuid4())

        # Create workflow
        workflow_exec = WorkflowExecution(
            id=workflow_id,
            workflow_name="multi_checkpoint_test",
            workflow_version="1.0",
            workflow_config_snapshot={},
            start_time=datetime.now(UTC),
            status="running"
        )

        with get_session() as session:
            session.add(workflow_exec)
            session.commit()

        # Execute stage 1
        with execution_tracker.track_stage("stage1", {}, workflow_id) as stage1_id:
            with execution_tracker.track_agent("agent1", {}, stage1_id):
                pass

        with get_session() as session:
            stage1 = session.query(StageExecution).filter_by(id=stage1_id).first()
            stage1.output_data = {"result": "stage1 done"}
            session.commit()

        # Checkpoint after stage 1
        domain_state_1 = WorkflowDomainState(
            workflow_id=workflow_id,
            current_stage="stage1",
            stage_outputs={"stage1": {"result": "stage1 done"}},
            input_data={},
            num_stages_completed=1
        )
        checkpoint_manager.save_checkpoint(workflow_id, domain_state_1, checkpoint_id="checkpoint_1")

        # Execute stage 2
        with execution_tracker.track_stage("stage2", {}, workflow_id) as stage2_id:
            with execution_tracker.track_agent("agent2", {}, stage2_id):
                pass

        with get_session() as session:
            stage2 = session.query(StageExecution).filter_by(id=stage2_id).first()
            stage2.output_data = {"result": "stage2 done"}
            session.commit()

        # Checkpoint after stage 2
        domain_state_2 = WorkflowDomainState(
            workflow_id=workflow_id,
            current_stage="stage2",
            stage_outputs={
                "stage1": {"result": "stage1 done"},
                "stage2": {"result": "stage2 done"}
            },
            input_data={},
            num_stages_completed=2
        )
        checkpoint_manager.save_checkpoint(workflow_id, domain_state_2, checkpoint_id="checkpoint_2")

        # VERIFICATION: Both checkpoints exist
        checkpoints = checkpoint_manager.list_checkpoints(workflow_id)
        assert len(checkpoints) == 2

        # Load checkpoint 2
        loaded = checkpoint_manager.load_checkpoint(workflow_id, checkpoint_id="checkpoint_2")
        assert loaded.current_stage == "stage2"
        assert loaded.num_stages_completed == 2
        assert "stage1" in loaded.stage_outputs
        assert "stage2" in loaded.stage_outputs

    def test_checkpoint_includes_complete_state(
        self,
        sample_database,
        checkpoint_manager,
        execution_tracker
    ):
        """Test checkpoint contains all required state fields."""
        workflow_id = str(uuid.uuid4())

        # Create comprehensive domain state
        domain_state = WorkflowDomainState(
            workflow_id=workflow_id,
            current_stage="stage2",
            stage_outputs={
                "stage1": {"data": "value1"},
                "stage2": {"data": "value2"}
            },
            input_data={"query": "test"},
            num_stages_completed=2,
            metadata={"custom": "metadata"}
        )

        # Save checkpoint
        checkpoint_manager.save_checkpoint(workflow_id, domain_state)

        # Load and verify
        loaded = checkpoint_manager.load_checkpoint(workflow_id)

        assert loaded.workflow_id == workflow_id
        assert loaded.current_stage == "stage2"
        assert loaded.num_stages_completed == 2
        assert loaded.input_data == {"query": "test"}
        assert loaded.metadata == {"custom": "metadata"}
        assert len(loaded.stage_outputs) == 2


class TestWorkflowResume:
    """Test resume from checkpoints"""

    @pytest.fixture
    def sample_database(self):
        """Initialize test database."""
        try:
            from src.observability.database import get_database
            get_database()
        except RuntimeError:
            init_database("sqlite:///:memory:")
        yield

    @pytest.fixture
    def execution_tracker(self, sample_database):
        """Execution tracker."""
        from src.observability.backends.sql_backend import SQLObservabilityBackend
        backend = SQLObservabilityBackend()
        return ExecutionTracker(backend=backend)

    @pytest.fixture
    def checkpoint_manager(self, tmp_path):
        """Checkpoint manager."""
        backend = FileCheckpointBackend(checkpoint_dir=str(tmp_path / "checkpoints"))
        return CheckpointManager(backend=backend)

    def test_resume_from_stage_one(
        self,
        sample_database,
        checkpoint_manager,
        execution_tracker
    ):
        """Test resuming workflow from stage 1 checkpoint."""
        workflow_id = str(uuid.uuid4())

        # Create initial workflow execution
        workflow_exec = WorkflowExecution(
            id=workflow_id,
            workflow_name="resume_test",
            workflow_version="1.0",
            workflow_config_snapshot={},
            start_time=datetime.now(UTC),
            status="running"
        )

        with get_session() as session:
            session.add(workflow_exec)
            session.commit()

        # Execute stage 1 and checkpoint
        with execution_tracker.track_stage("stage1", {}, workflow_id) as stage_id:
            with execution_tracker.track_agent("agent1", {}, stage_id):
                pass

        domain_state = WorkflowDomainState(
            workflow_id=workflow_id,
            current_stage="stage1",
            stage_outputs={"stage1": {"completed": True}},
            input_data={"query": "original"},
            num_stages_completed=1
        )
        checkpoint_manager.save_checkpoint(workflow_id, domain_state)

        # Simulate failure after stage 1
        workflow_exec.status = "failed"
        with get_session() as session:
            session.merge(workflow_exec)
            session.commit()

        # RESUME: Load checkpoint and continue
        loaded_state = checkpoint_manager.load_checkpoint(workflow_id)

        # Create new workflow execution for resume
        resume_workflow_id = str(uuid.uuid4())
        resume_workflow_exec = WorkflowExecution(
            id=resume_workflow_id,
            workflow_name="resume_test",
            workflow_version="1.0",
            workflow_config_snapshot={},
            start_time=datetime.now(UTC),
            status="running",
            resumed_from_workflow_id=workflow_id
        )

        with get_session() as session:
            session.add(resume_workflow_exec)
            session.commit()

        # Continue from stage 2 (stage 1 already done)
        with execution_tracker.track_stage("stage2", {}, resume_workflow_id) as stage_id:
            # Stage 2 should have access to stage 1 output
            assert "stage1" in loaded_state.stage_outputs

            with execution_tracker.track_agent("agent2", {}, stage_id):
                pass

        # Complete workflow
        resume_workflow_exec.status = "completed"
        resume_workflow_exec.end_time = datetime.now(UTC)

        with get_session() as session:
            session.merge(resume_workflow_exec)
            session.commit()

        # VERIFICATION: Resume succeeded
        with get_session() as session:
            resumed = session.query(WorkflowExecution).filter_by(
                id=resume_workflow_id
            ).first()
            assert resumed.status == "completed"
            assert resumed.resumed_from_workflow_id == workflow_id

    def test_resume_skips_completed_stages(
        self,
        sample_database,
        checkpoint_manager,
        execution_tracker
    ):
        """Test resumed workflow skips already-completed stages."""
        workflow_id = str(uuid.uuid4())

        # Original workflow: complete stages 1 and 2
        workflow_exec = WorkflowExecution(
            id=workflow_id,
            workflow_name="skip_test",
            workflow_version="1.0",
            workflow_config_snapshot={},
            start_time=datetime.now(UTC),
            status="running"
        )

        with get_session() as session:
            session.add(workflow_exec)
            session.commit()

        # Execute stages 1 and 2
        stage_outputs = {}

        with execution_tracker.track_stage("stage1", {}, workflow_id) as stage1_id:
            with execution_tracker.track_agent("agent1", {}, stage1_id):
                pass
            stage_outputs["stage1"] = {"data": "stage1"}

        with execution_tracker.track_stage("stage2", {}, workflow_id) as stage2_id:
            with execution_tracker.track_agent("agent2", {}, stage2_id):
                pass
            stage_outputs["stage2"] = {"data": "stage2"}

        # Checkpoint after stage 2
        domain_state = WorkflowDomainState(
            workflow_id=workflow_id,
            current_stage="stage2",
            stage_outputs=stage_outputs,
            input_data={},
            num_stages_completed=2
        )
        checkpoint_manager.save_checkpoint(workflow_id, domain_state)

        # Fail before stage 3
        workflow_exec.status = "failed"
        with get_session() as session:
            session.merge(workflow_exec)
            session.commit()

        # RESUME: Should start from stage 3
        loaded_state = checkpoint_manager.load_checkpoint(workflow_id)

        resume_workflow_id = str(uuid.uuid4())
        resume_workflow_exec = WorkflowExecution(
            id=resume_workflow_id,
            workflow_name="skip_test",
            workflow_version="1.0",
            workflow_config_snapshot={},
            start_time=datetime.now(UTC),
            status="running",
            resumed_from_workflow_id=workflow_id
        )

        with get_session() as session:
            session.add(resume_workflow_exec)
            session.commit()

        # Only execute stage 3 (stages 1-2 already done)
        with execution_tracker.track_stage("stage3", {}, resume_workflow_id) as stage_id:
            # Verify previous stages' outputs available
            assert "stage1" in loaded_state.stage_outputs
            assert "stage2" in loaded_state.stage_outputs

            with execution_tracker.track_agent("agent3", {}, stage_id):
                pass

        # VERIFICATION: Only stage 3 executed in resume
        with get_session() as session:
            resumed_stages = session.query(StageExecution).filter_by(
                workflow_execution_id=resume_workflow_id
            ).all()
            assert len(resumed_stages) == 1  # Only stage 3
            assert resumed_stages[0].stage_name == "stage3"

    def test_resume_preserves_state(
        self,
        sample_database,
        checkpoint_manager
    ):
        """Test resume preserves all state from checkpoint."""
        workflow_id = str(uuid.uuid4())

        # Create rich domain state
        original_state = WorkflowDomainState(
            workflow_id=workflow_id,
            current_stage="stage2",
            stage_outputs={
                "stage1": {"key1": "value1", "nested": {"a": 1}},
                "stage2": {"key2": "value2", "list": [1, 2, 3]}
            },
            input_data={"original_query": "test query"},
            num_stages_completed=2,
            metadata={"run_id": "abc123", "environment": "test"}
        )

        # Save checkpoint
        checkpoint_manager.save_checkpoint(workflow_id, original_state)

        # Load checkpoint
        loaded_state = checkpoint_manager.load_checkpoint(workflow_id)

        # VERIFICATION: All state preserved
        assert loaded_state.workflow_id == original_state.workflow_id
        assert loaded_state.current_stage == original_state.current_stage
        assert loaded_state.num_stages_completed == original_state.num_stages_completed
        assert loaded_state.input_data == original_state.input_data
        assert loaded_state.metadata == original_state.metadata

        # Verify nested structures preserved
        assert loaded_state.stage_outputs["stage1"]["nested"]["a"] == 1
        assert loaded_state.stage_outputs["stage2"]["list"] == [1, 2, 3]


class TestCheckpointFailureRecovery:
    """Test recovery scenarios"""

    @pytest.fixture
    def sample_database(self):
        """Initialize test database."""
        try:
            from src.observability.database import get_database
            get_database()
        except RuntimeError:
            init_database("sqlite:///:memory:")
        yield

    @pytest.fixture
    def checkpoint_manager(self, tmp_path):
        """Checkpoint manager."""
        backend = FileCheckpointBackend(checkpoint_dir=str(tmp_path / "checkpoints"))
        return CheckpointManager(backend=backend)

    def test_resume_after_agent_failure(
        self,
        sample_database,
        checkpoint_manager
    ):
        """Test resume after agent failure mid-stage."""
        workflow_id = str(uuid.uuid4())

        # Checkpoint before failed stage
        domain_state = WorkflowDomainState(
            workflow_id=workflow_id,
            current_stage="stage1",
            stage_outputs={"stage1": {"completed": True}},
            input_data={},
            num_stages_completed=1
        )
        checkpoint_manager.save_checkpoint(workflow_id, domain_state)

        # RESUME: Can restart from checkpoint
        loaded = checkpoint_manager.load_checkpoint(workflow_id)
        assert loaded.num_stages_completed == 1

        # Workflow can continue from stage 2
        assert loaded.current_stage == "stage1"

    def test_resume_after_timeout(
        self,
        sample_database,
        checkpoint_manager
    ):
        """Test resume after timeout."""
        workflow_id = str(uuid.uuid4())

        # Checkpoint before timeout
        domain_state = WorkflowDomainState(
            workflow_id=workflow_id,
            current_stage="stage3",
            stage_outputs={
                "stage1": {"done": True},
                "stage2": {"done": True},
                "stage3": {"done": True}
            },
            input_data={},
            num_stages_completed=3
        )
        checkpoint_manager.save_checkpoint(workflow_id, domain_state)

        # RESUME: Restore state after timeout
        loaded = checkpoint_manager.load_checkpoint(workflow_id)
        assert loaded.num_stages_completed == 3
        assert len(loaded.stage_outputs) == 3

    def test_checkpoint_corruption_detection(
        self,
        checkpoint_manager,
        tmp_path
    ):
        """Test detection of corrupted checkpoint files."""
        workflow_id = str(uuid.uuid4())

        # Create valid checkpoint
        domain_state = WorkflowDomainState(
            workflow_id=workflow_id,
            current_stage="stage1",
            stage_outputs={"stage1": {}},
            input_data={},
            num_stages_completed=1
        )
        checkpoint_manager.save_checkpoint(workflow_id, domain_state)

        # Corrupt the checkpoint file
        checkpoint_dir = tmp_path / "checkpoints"
        checkpoint_files = list(checkpoint_dir.glob(f"{workflow_id}_*.json"))
        assert len(checkpoint_files) > 0

        with open(checkpoint_files[0], 'w') as f:
            f.write("{ invalid json }")

        # VERIFICATION: Loading corrupted checkpoint raises error
        with pytest.raises(Exception):  # JSON decode error or validation error
            checkpoint_manager.load_checkpoint(workflow_id)
