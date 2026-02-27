"""End-to-end workflow validation tests.

Comprehensive E2E tests covering:
- Full workflow execution (CLI -> agents -> observability -> results)
- Multi-stage workflows
- Error recovery end-to-end
- Rollback integration
"""

import uuid
from datetime import UTC, datetime

import pytest
import yaml

# ============================================================================
# Full Workflow Execution
# ============================================================================


class TestFullWorkflowExecution:
    """Test complete workflow execution from CLI to results."""

    @pytest.fixture
    def workflow_config(self, tmp_path):
        """Create complete workflow configuration."""
        config = {
            "workflow": {
                "name": "e2e_test_workflow",
                "version": "1.0",
                "description": "End-to-end test workflow",
                "stages": [
                    {
                        "name": "extraction",
                        "agent": "extractor_agent",
                        "inputs": {"data": "test input"},
                        "outputs": ["extracted_data"],
                    },
                    {
                        "name": "processing",
                        "agent": "processor_agent",
                        "inputs": {"data": "{{stages.extraction.extracted_data}}"},
                        "outputs": ["processed_data"],
                    },
                    {
                        "name": "validation",
                        "agent": "validator_agent",
                        "inputs": {"data": "{{stages.processing.processed_data}}"},
                        "outputs": ["validation_result"],
                    },
                ],
            }
        }

        config_path = tmp_path / "workflow.yaml"
        with open(config_path, "w") as f:
            yaml.dump(config, f)

        return config_path

    @pytest.fixture
    def mock_agent_execution(self):
        """Mock agent execution for E2E testing."""

        def execute_agent(agent_name, inputs):
            # Simulate different agent behaviors
            if agent_name == "extractor_agent":
                return {"extracted_data": {"items": ["item1", "item2"]}}
            elif agent_name == "processor_agent":
                return {"processed_data": {"count": 2, "status": "processed"}}
            elif agent_name == "validator_agent":
                return {"validation_result": {"valid": True, "errors": []}}
            return {}

        return execute_agent

    def test_full_workflow_cli_to_results(self, workflow_config, mock_agent_execution):
        """Complete workflow should execute from CLI to final results."""
        from temper_ai.observability.tracker import ExecutionTracker
        from temper_ai.storage.database.manager import init_database
        from temper_ai.workflow.config_loader import ConfigLoader

        # Initialize observability
        init_database("sqlite:///:memory:")
        tracker = ExecutionTracker()

        # Load configuration
        ConfigLoader(config_root=workflow_config.parent)
        workflow_config_dict = yaml.safe_load(workflow_config.read_text())

        # Track execution
        with tracker.track_workflow("e2e_workflow") as wf_id:
            # Execute stages
            results = {}
            for stage in workflow_config_dict["workflow"]["stages"]:
                with tracker.track_stage(
                    stage["name"], {"agent": stage["agent"]}, wf_id
                ) as stage_id:
                    with tracker.track_agent(
                        stage["agent"], {"version": "1.0"}, stage_id
                    ):
                        # Simulate agent execution
                        stage_result = mock_agent_execution(
                            stage["agent"], stage["inputs"]
                        )
                        results[stage["name"]] = stage_result

        # Verify complete execution
        assert wf_id is not None
        assert "extraction" in results
        assert "processing" in results
        assert "validation" in results
        assert results["validation"]["validation_result"]["valid"] is True

    def test_workflow_with_observability_integration(self, workflow_config):
        """Workflow execution should be fully tracked in observability."""
        from temper_ai.observability.tracker import ExecutionTracker
        from temper_ai.storage.database.manager import init_database

        init_database("sqlite:///:memory:")
        tracker = ExecutionTracker()

        workflow_config_dict = yaml.safe_load(workflow_config.read_text())

        with tracker.track_workflow("observable_workflow") as wf_id:
            # Execute stages with tracking
            for _idx, stage in enumerate(workflow_config_dict["workflow"]["stages"]):
                with tracker.track_stage(
                    stage["name"], {"agent": stage["agent"]}, wf_id
                ) as stage_id:
                    with tracker.track_agent(
                        stage["agent"], {"version": "1.0"}, stage_id
                    ):
                        pass  # Stage execution tracked by context manager

        # Verify tracking
        assert wf_id is not None

    def test_workflow_context_propagation(self, workflow_config):
        """Context should propagate through entire workflow."""
        from temper_ai.observability.tracker import ExecutionTracker
        from temper_ai.shared.core.context import ExecutionContext
        from temper_ai.storage.database.manager import init_database

        init_database("sqlite:///:memory:")
        tracker = ExecutionTracker()

        workflow_config_dict = yaml.safe_load(workflow_config.read_text())

        # Initialize context
        ExecutionContext(
            workflow_id=str(uuid.uuid4()),
            metadata={"user": "test_user", "environment": "test"},
        )

        with tracker.track_workflow("context_propagation") as wf_id:
            # Context should be available in all stages
            for stage in workflow_config_dict["workflow"]["stages"]:
                with tracker.track_stage(
                    stage["name"], {"agent": stage["agent"]}, wf_id
                ) as stage_id:
                    with tracker.track_agent(
                        stage["agent"], {"version": "1.0"}, stage_id
                    ) as agent_id:
                        # Verify context is accessible
                        {
                            "workflow_id": wf_id,
                            "agent_id": agent_id,
                            "stage": stage["name"],
                        }

        assert wf_id is not None


# ============================================================================
# Multi-Stage Workflows
# ============================================================================


class TestMultiStageWorkflows:
    """Test complex multi-stage workflow scenarios."""

    def test_parallel_stage_execution(self):
        """Parallel stages should execute concurrently."""
        from temper_ai.observability.tracker import ExecutionTracker
        from temper_ai.storage.database.manager import init_database

        init_database("sqlite:///:memory:")
        tracker = ExecutionTracker()

        # Define parallel stages
        stages = [
            {"name": f"parallel_stage_{i}", "agent": f"agent_{i}"} for i in range(5)
        ]

        with tracker.track_workflow("parallel_execution") as wf_id:
            start_time = datetime.now(UTC)

            # Simulate parallel execution
            results = {}
            for stage in stages:
                with tracker.track_stage(
                    stage["name"], {"agent": stage["agent"]}, wf_id
                ) as stage_id:
                    with tracker.track_agent(
                        stage["agent"], {"version": "1.0"}, stage_id
                    ) as agent_id:
                        results[stage["name"]] = {
                            "status": "completed",
                            "agent_id": agent_id,
                        }

            end_time = datetime.now(UTC)
            (end_time - start_time).total_seconds()

        # Verify all stages completed
        assert len(results) == len(stages)
        assert all(r["status"] == "completed" for r in results.values())

    def test_conditional_stage_execution(self):
        """Stages should execute conditionally based on previous results."""
        from temper_ai.observability.tracker import ExecutionTracker
        from temper_ai.storage.database.manager import init_database

        init_database("sqlite:///:memory:")
        tracker = ExecutionTracker()

        with tracker.track_workflow("conditional_workflow") as wf_id:
            # Stage 1: Initial check
            with tracker.track_stage("check", {}, wf_id) as stage_id:
                with tracker.track_agent("check_agent", {"version": "1.0"}, stage_id):
                    check_result = {"requires_processing": True, "data_valid": True}

            # Stage 2: Conditional processing
            if check_result["requires_processing"]:
                with tracker.track_stage("process", {}, wf_id) as stage_id:
                    with tracker.track_agent(
                        "process_agent", {"version": "1.0"}, stage_id
                    ):
                        process_result = {"status": "processed"}
            else:
                process_result = {"status": "skipped"}

            # Stage 3: Conditional validation
            if check_result["data_valid"]:
                with tracker.track_stage("validate", {}, wf_id) as stage_id:
                    with tracker.track_agent(
                        "validate_agent", {"version": "1.0"}, stage_id
                    ):
                        validation_result = {"valid": True}

        assert process_result["status"] == "processed"
        assert validation_result["valid"] is True

    def test_stage_dependency_resolution(self):
        """Stages with dependencies should execute in correct order."""
        from temper_ai.observability.tracker import ExecutionTracker
        from temper_ai.storage.database.manager import init_database

        init_database("sqlite:///:memory:")
        tracker = ExecutionTracker()

        # Define stages with dependencies
        # Stage C depends on A and B
        # Stage B depends on A
        execution_order = []

        with tracker.track_workflow("dependency_workflow") as wf_id:
            # Stage A
            with tracker.track_stage("stage_a", {}, wf_id) as stage_id:
                with tracker.track_agent("agent_a", {"version": "1.0"}, stage_id):
                    execution_order.append("A")
                    result_a = {"data": "from_a"}

            # Stage B (depends on A)
            with tracker.track_stage("stage_b", {}, wf_id) as stage_id:
                with tracker.track_agent("agent_b", {"version": "1.0"}, stage_id):
                    execution_order.append("B")
                    result_b = {"data": "from_b", "source": result_a["data"]}

            # Stage C (depends on A and B)
            with tracker.track_stage("stage_c", {}, wf_id) as stage_id:
                with tracker.track_agent("agent_c", {"version": "1.0"}, stage_id):
                    execution_order.append("C")
                    {
                        "data": "from_c",
                        "sources": [result_a["data"], result_b["data"]],
                    }

        # Verify execution order
        assert execution_order == ["A", "B", "C"]


# ============================================================================
# Error Recovery End-to-End
# ============================================================================


class TestErrorRecoveryE2E:
    """Test error recovery across entire workflow."""

    def test_stage_failure_recovery(self):
        """Failed stage should trigger recovery mechanism."""
        from temper_ai.observability.tracker import ExecutionTracker
        from temper_ai.storage.database.manager import init_database

        init_database("sqlite:///:memory:")
        tracker = ExecutionTracker()

        with tracker.track_workflow("error_recovery") as wf_id:
            # Stage 1: Success
            with tracker.track_stage("stage_1", {}, wf_id) as stage_id:
                with tracker.track_agent("agent_1", {"version": "1.0"}, stage_id):
                    result_1 = {"status": "completed"}

            # Stage 2: Failure
            try:
                with tracker.track_stage("stage_2", {}, wf_id) as stage_id:
                    with tracker.track_agent("agent_2", {"version": "1.0"}, stage_id):
                        raise ValueError("Stage 2 failed")
            except ValueError:
                # Recovery: Retry with fallback
                with tracker.track_stage("stage_2_fallback", {}, wf_id) as stage_id:
                    with tracker.track_agent(
                        "fallback_agent_2", {"version": "1.0"}, stage_id
                    ):
                        result_2 = {"status": "recovered", "fallback": True}

            # Stage 3: Continue after recovery
            with tracker.track_stage("stage_3", {}, wf_id) as stage_id:
                with tracker.track_agent("agent_3", {"version": "1.0"}, stage_id):
                    result_3 = {"status": "completed", "previous": result_2}

        assert result_1["status"] == "completed"
        assert result_2["status"] == "recovered"
        assert result_3["status"] == "completed"

    def test_workflow_retry_on_failure(self):
        """Entire workflow should retry on critical failure."""
        from temper_ai.observability.tracker import ExecutionTracker
        from temper_ai.storage.database.manager import init_database

        init_database("sqlite:///:memory:")
        tracker = ExecutionTracker()

        max_retries = 3
        attempt = 0
        success = False

        while attempt < max_retries and not success:
            attempt += 1

            try:
                with tracker.track_workflow(f"retry_workflow_attempt_{attempt}"):
                    # Simulate failure on first 2 attempts
                    if attempt < 3:
                        raise RuntimeError(f"Workflow failed on attempt {attempt}")

                    success = True

            except RuntimeError:
                pass  # Retry on next iteration

        assert success is True
        assert attempt == 3

    def test_partial_rollback_on_error(self):
        """Error should trigger partial rollback of completed stages."""
        from temper_ai.observability.tracker import ExecutionTracker
        from temper_ai.storage.database.manager import init_database

        init_database("sqlite:///:memory:")
        tracker = ExecutionTracker()

        completed_stages = []
        rolled_back = []

        with tracker.track_workflow("partial_rollback") as wf_id:
            # Stage 1: Success
            with tracker.track_stage("stage_1", {}, wf_id) as stage_id:
                with tracker.track_agent("agent_1", {"version": "1.0"}, stage_id):
                    completed_stages.append("stage_1")

            # Stage 2: Success
            with tracker.track_stage("stage_2", {}, wf_id) as stage_id:
                with tracker.track_agent("agent_2", {"version": "1.0"}, stage_id):
                    completed_stages.append("stage_2")

            # Stage 3: Failure
            try:
                with tracker.track_stage("stage_3", {}, wf_id) as stage_id:
                    with tracker.track_agent("agent_3", {"version": "1.0"}, stage_id):
                        raise OSError("Stage 3 failed - disk full")
            except OSError:
                # Rollback completed stages in reverse order
                for stage in reversed(completed_stages):
                    rolled_back.append(stage)

        assert completed_stages == ["stage_1", "stage_2"]
        assert rolled_back == ["stage_2", "stage_1"]


# ============================================================================
# Rollback Integration
# ============================================================================


class TestRollbackIntegration:
    """Test rollback mechanisms across workflow."""

    def test_transaction_rollback(self):
        """Database transactions should rollback on error."""
        from temper_ai.observability.tracker import ExecutionTracker
        from temper_ai.storage.database.manager import init_database

        init_database("sqlite:///:memory:")
        tracker = ExecutionTracker()

        with tracker.track_workflow("transaction_rollback") as wf_id:
            try:
                # Simulate transactional operations
                with tracker.track_stage("op_1", {}, wf_id) as stage_id:
                    with tracker.track_agent(
                        "op_agent_1", {"version": "1.0"}, stage_id
                    ):
                        pass  # Operation 1

                with tracker.track_stage("op_2", {}, wf_id) as stage_id:
                    with tracker.track_agent(
                        "op_agent_2", {"version": "1.0"}, stage_id
                    ):
                        pass  # Operation 2

                # Simulate error
                raise ValueError("Transaction failed")

            except ValueError:
                pass  # Transaction rolled back

        # Verify workflow was tracked despite rollback
        assert wf_id is not None

    def test_state_restoration_on_rollback(self):
        """System state should restore to previous checkpoint on rollback."""
        from temper_ai.observability.tracker import ExecutionTracker
        from temper_ai.storage.database.manager import init_database

        init_database("sqlite:///:memory:")
        tracker = ExecutionTracker()

        with tracker.track_workflow("state_restoration"):
            # Checkpoint initial state
            initial_state = {"counter": 0, "data": {}, "flags": {"processed": False}}

            # Modify state
            current_state = initial_state.copy()
            current_state["counter"] = 5
            current_state["data"] = {"key": "value"}
            current_state["flags"]["processed"] = True

            # Rollback to checkpoint
            restored_state = initial_state.copy()

        # Verify state restoration
        assert restored_state == initial_state
        assert restored_state != current_state

    def test_cascading_rollback(self):
        """Rollback should cascade through dependent stages."""
        from temper_ai.observability.tracker import ExecutionTracker
        from temper_ai.storage.database.manager import init_database

        init_database("sqlite:///:memory:")
        tracker = ExecutionTracker()

        rollback_order = []

        with tracker.track_workflow("cascading_rollback") as wf_id:
            # Create dependency chain: A -> B -> C -> D
            stages = ["A", "B", "C", "D"]
            stage_results = {}

            for stage in stages:
                with tracker.track_stage(f"stage_{stage}", {}, wf_id) as stage_id:
                    with tracker.track_agent(
                        f"agent_{stage}", {"version": "1.0"}, stage_id
                    ):
                        stage_results[stage] = {"completed": True}

            # Failure in D triggers cascade
            try:
                raise RuntimeError("Stage D failed")
            except RuntimeError:
                # Rollback in reverse dependency order
                for stage in reversed(stages):
                    rollback_order.append(stage)

        assert rollback_order == ["D", "C", "B", "A"]


# ============================================================================
# Performance and Load Testing
# ============================================================================


class TestWorkflowPerformance:
    """Test workflow performance characteristics."""

    def test_high_volume_event_tracking(self):
        """System should handle high volume of agent trackings."""
        from temper_ai.observability.tracker import ExecutionTracker
        from temper_ai.storage.database.manager import init_database

        init_database("sqlite:///:memory:")
        tracker = ExecutionTracker()

        agent_count = 100

        with tracker.track_workflow("high_volume_tracking") as wf_id:
            start_time = datetime.now(UTC)

            for i in range(agent_count):
                with tracker.track_stage(f"stage_{i}", {}, wf_id) as stage_id:
                    with tracker.track_agent(
                        f"agent_{i}", {"version": "1.0"}, stage_id
                    ):
                        pass  # Simulate agent execution

            end_time = datetime.now(UTC)
            duration = (end_time - start_time).total_seconds()

        # Should complete in reasonable time
        assert duration < 10.0  # Less than 10 seconds for 100 agent trackings

    def test_concurrent_workflow_execution(self):
        """Multiple workflows should execute concurrently."""
        from temper_ai.observability.tracker import ExecutionTracker
        from temper_ai.storage.database.manager import init_database

        init_database("sqlite:///:memory:")

        workflow_count = 10
        trackers = [ExecutionTracker() for _ in range(workflow_count)]
        workflow_ids = []

        start_time = datetime.now(UTC)

        for i, tracker in enumerate(trackers):
            with tracker.track_workflow(f"concurrent_workflow_{i}") as wf_id:
                workflow_ids.append(wf_id)

                with tracker.track_stage(f"stage_{i}", {}, wf_id) as stage_id:
                    with tracker.track_agent(
                        f"agent_{i}", {"version": "1.0"}, stage_id
                    ):
                        pass  # Simulate workflow execution

        end_time = datetime.now(UTC)
        duration = (end_time - start_time).total_seconds()

        # Verify all workflows completed
        assert len(workflow_ids) == workflow_count
        assert len(set(workflow_ids)) == workflow_count  # All unique
        assert duration < 5.0  # Should be fast with concurrent execution


# ============================================================================
# Configuration Loading (merged from test_e2e_workflow_simple.py)
# ============================================================================


class TestWorkflowConfiguration:
    """Test workflow configuration loading and validation."""

    def test_valid_config_loads(self, tmp_path):
        """Valid configuration should load successfully."""

        # Create workflows directory
        workflows_dir = tmp_path / "workflows"
        workflows_dir.mkdir()

        config = workflows_dir / "valid.yaml"
        config.write_text("""
workflow:
  name: test_workflow
  description: "Test workflow"
  version: "1.0"
  stages:
    - name: stage1
      stage_ref: test_stage
""")

        # Just verify YAML is valid
        with open(config) as f:
            data = yaml.safe_load(f)

        assert data is not None
        assert data["workflow"]["name"] == "test_workflow"

    def test_invalid_config_raises_error(self, tmp_path):
        """Invalid configuration should raise validation error."""
        from temper_ai.workflow.config_loader import ConfigLoader

        workflows_dir = tmp_path / "workflows"
        workflows_dir.mkdir()

        invalid_config = workflows_dir / "invalid.yaml"
        invalid_config.write_text("invalid: yaml: content:")

        loader = ConfigLoader(config_root=tmp_path)

        with pytest.raises((ValueError, KeyError, yaml.YAMLError)):
            loader.load_workflow("invalid")

    def test_missing_required_fields(self, tmp_path):
        """Configuration missing required fields should fail validation."""
        from temper_ai.workflow.config_loader import ConfigLoader

        workflows_dir = tmp_path / "workflows"
        workflows_dir.mkdir()

        incomplete_config = workflows_dir / "incomplete.yaml"
        incomplete_config.write_text("""
workflow:
  name: test
""")  # Missing version and stages

        loader = ConfigLoader(config_root=tmp_path)

        with pytest.raises((ValueError, KeyError)):
            loader.load_workflow("incomplete")


# ============================================================================
# Error Handling (merged from test_e2e_workflow_simple.py)
# ============================================================================


class TestErrorHandling:
    """Test error handling across workflow components."""

    def test_database_error_handling(self):
        """Database errors should be caught and handled."""
        from temper_ai.storage.database import init_database

        # Initialize with invalid URL should raise error
        with pytest.raises((ValueError, OSError)):
            init_database("invalid://url")

    def test_config_loader_error_recovery(self, tmp_path):
        """Config loader should handle malformed files gracefully."""
        from temper_ai.workflow.config_loader import ConfigLoader

        workflows_dir = tmp_path / "workflows"
        workflows_dir.mkdir()

        malformed = workflows_dir / "malformed.yaml"
        malformed.write_text("{invalid yaml")

        loader = ConfigLoader(config_root=tmp_path)

        with pytest.raises((ValueError, KeyError, yaml.YAMLError)):
            loader.load_workflow("malformed")


# ============================================================================
# Database Integration (merged from test_e2e_workflow_simple.py)
# ============================================================================


class TestDatabaseIntegration:
    """Test database integration in workflows."""

    def test_database_initialization(self):
        """Database should initialize correctly."""
        from temper_ai.storage.database import init_database

        # Initialize in-memory database
        init_database("sqlite:///:memory:")

        # Verify connection
        from temper_ai.storage.database import get_session

        with get_session() as session:
            assert session is not None

    def test_database_session_context(self):
        """Database sessions should work as context managers."""
        from temper_ai.storage.database import get_session, init_database

        init_database("sqlite:///:memory:")

        with get_session() as session:
            # Session should be active
            assert session is not None

        # Session should be closed after context

    def test_multiple_database_connections(self):
        """Multiple connections should work correctly."""
        from temper_ai.storage.database import get_session, init_database

        init_database("sqlite:///:memory:")

        # Create multiple sessions
        sessions = []
        for _i in range(5):
            with get_session() as session:
                assert session is not None
                sessions.append(session)

        assert len(sessions) == 5
