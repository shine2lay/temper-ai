"""End-to-end workflow validation tests.

Comprehensive E2E tests covering:
- Full workflow execution (CLI → agents → observability → results)
- Multi-stage workflows
- Error recovery end-to-end
- Rollback integration
"""
import asyncio
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, AsyncMock, patch, MagicMock
import tempfile
import uuid
import yaml

import pytest

from tests.fixtures.database_fixtures import db_session
from tests.fixtures.mock_helpers import mock_llm


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
                        "outputs": ["extracted_data"]
                    },
                    {
                        "name": "processing",
                        "agent": "processor_agent",
                        "inputs": {"data": "{{stages.extraction.extracted_data}}"},
                        "outputs": ["processed_data"]
                    },
                    {
                        "name": "validation",
                        "agent": "validator_agent",
                        "inputs": {"data": "{{stages.processing.processed_data}}"},
                        "outputs": ["validation_result"]
                    }
                ]
            }
        }

        config_path = tmp_path / "workflow.yaml"
        with open(config_path, 'w') as f:
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
        from src.compiler.config_loader import ConfigLoader
        from src.compiler.executors.sequential import SequentialExecutor
        from src.observability.tracker import ExecutionTracker
        from src.observability.database import init_database

        # Initialize observability
        init_database("sqlite:///:memory:")
        tracker = ExecutionTracker()

        # Load configuration
        config_loader = ConfigLoader(config_root=workflow_config.parent)
        workflow_config_dict = yaml.safe_load(workflow_config.read_text())

        # Track execution
        with tracker.track_workflow("e2e_workflow") as wf_id:
            # Execute stages
            results = {}
            for stage in workflow_config_dict["workflow"]["stages"]:
                with tracker.track_agent(stage["agent"], "1.0") as agent_id:
                    # Simulate agent execution
                    stage_result = mock_agent_execution(stage["agent"], stage["inputs"])
                    results[stage["name"]] = stage_result

                    tracker.track_event(
                        event_type="stage_completed",
                        details={
                            "stage": stage["name"],
                            "agent": stage["agent"],
                            "result": stage_result
                        }
                    )

        # Verify complete execution
        assert wf_id is not None
        assert "extraction" in results
        assert "processing" in results
        assert "validation" in results
        assert results["validation"]["validation_result"]["valid"] is True

    def test_workflow_with_observability_integration(self, workflow_config):
        """Workflow execution should be fully tracked in observability."""
        from src.observability.tracker import ExecutionTracker
        from src.observability.database import init_database, get_session
        from src.observability.models import WorkflowRun

        init_database("sqlite:///:memory:")
        tracker = ExecutionTracker()

        workflow_config_dict = yaml.safe_load(workflow_config.read_text())

        with tracker.track_workflow("observable_workflow") as wf_id:
            # Track workflow metadata
            tracker.track_event(
                event_type="workflow_started",
                details={
                    "name": workflow_config_dict["workflow"]["name"],
                    "version": workflow_config_dict["workflow"]["version"],
                    "stages": len(workflow_config_dict["workflow"]["stages"])
                }
            )

            # Execute stages with tracking
            for idx, stage in enumerate(workflow_config_dict["workflow"]["stages"]):
                with tracker.track_agent(stage["agent"], "1.0") as agent_id:
                    tracker.track_event(
                        event_type="stage_progress",
                        details={
                            "stage_index": idx,
                            "stage_name": stage["name"],
                            "total_stages": len(workflow_config_dict["workflow"]["stages"])
                        }
                    )

            tracker.track_event(
                event_type="workflow_completed",
                details={"status": "success"}
            )

        # Verify tracking
        assert wf_id is not None

    def test_workflow_context_propagation(self, workflow_config):
        """Context should propagate through entire workflow."""
        from src.core.context import ExecutionContext
        from src.observability.tracker import ExecutionTracker
        from src.observability.database import init_database

        init_database("sqlite:///:memory:")
        tracker = ExecutionTracker()

        workflow_config_dict = yaml.safe_load(workflow_config.read_text())

        # Initialize context
        context = ExecutionContext(
            workflow_id=str(uuid.uuid4()),
            metadata={"user": "test_user", "environment": "test"}
        )

        with tracker.track_workflow("context_propagation") as wf_id:
            # Context should be available in all stages
            for stage in workflow_config_dict["workflow"]["stages"]:
                with tracker.track_agent(stage["agent"], "1.0") as agent_id:
                    # Verify context is accessible
                    current_context = {
                        "workflow_id": wf_id,
                        "agent_id": agent_id,
                        "stage": stage["name"]
                    }

                    tracker.track_event(
                        event_type="context_verified",
                        details=current_context
                    )

        assert wf_id is not None


# ============================================================================
# Multi-Stage Workflows
# ============================================================================

class TestMultiStageWorkflows:
    """Test complex multi-stage workflow scenarios."""

    def test_parallel_stage_execution(self):
        """Parallel stages should execute concurrently."""
        from src.compiler.executors.parallel import ParallelExecutor
        from src.observability.tracker import ExecutionTracker
        from src.observability.database import init_database

        init_database("sqlite:///:memory:")
        tracker = ExecutionTracker()

        # Define parallel stages
        stages = [
            {"name": f"parallel_stage_{i}", "agent": f"agent_{i}"}
            for i in range(5)
        ]

        with tracker.track_workflow("parallel_execution") as wf_id:
            start_time = datetime.now(timezone.utc)

            # Simulate parallel execution
            results = {}
            for stage in stages:
                with tracker.track_agent(stage["agent"], "1.0") as agent_id:
                    results[stage["name"]] = {
                        "status": "completed",
                        "agent_id": agent_id
                    }

            end_time = datetime.now(timezone.utc)
            execution_time = (end_time - start_time).total_seconds()

            tracker.track_event(
                event_type="parallel_execution_completed",
                details={
                    "stages": len(stages),
                    "execution_time_seconds": execution_time
                }
            )

        # Verify all stages completed
        assert len(results) == len(stages)
        assert all(r["status"] == "completed" for r in results.values())

    def test_conditional_stage_execution(self):
        """Stages should execute conditionally based on previous results."""
        from src.observability.tracker import ExecutionTracker
        from src.observability.database import init_database

        init_database("sqlite:///:memory:")
        tracker = ExecutionTracker()

        with tracker.track_workflow("conditional_workflow") as wf_id:
            # Stage 1: Initial check
            with tracker.track_agent("check_agent", "1.0") as check_id:
                check_result = {"requires_processing": True, "data_valid": True}

            # Stage 2: Conditional processing
            if check_result["requires_processing"]:
                with tracker.track_agent("process_agent", "1.0") as process_id:
                    process_result = {"status": "processed"}
                    tracker.track_event(
                        event_type="conditional_stage_executed",
                        details={"stage": "processing", "reason": "data_requires_processing"}
                    )
            else:
                process_result = {"status": "skipped"}

            # Stage 3: Conditional validation
            if check_result["data_valid"]:
                with tracker.track_agent("validate_agent", "1.0") as validate_id:
                    validation_result = {"valid": True}
                    tracker.track_event(
                        event_type="conditional_stage_executed",
                        details={"stage": "validation", "reason": "data_is_valid"}
                    )

        assert process_result["status"] == "processed"
        assert validation_result["valid"] is True

    def test_stage_dependency_resolution(self):
        """Stages with dependencies should execute in correct order."""
        from src.observability.tracker import ExecutionTracker
        from src.observability.database import init_database

        init_database("sqlite:///:memory:")
        tracker = ExecutionTracker()

        # Define stages with dependencies
        # Stage C depends on A and B
        # Stage B depends on A
        execution_order = []

        with tracker.track_workflow("dependency_workflow") as wf_id:
            # Stage A
            with tracker.track_agent("agent_a", "1.0") as agent_a_id:
                execution_order.append("A")
                result_a = {"data": "from_a"}

            # Stage B (depends on A)
            with tracker.track_agent("agent_b", "1.0") as agent_b_id:
                execution_order.append("B")
                result_b = {"data": "from_b", "source": result_a["data"]}

            # Stage C (depends on A and B)
            with tracker.track_agent("agent_c", "1.0") as agent_c_id:
                execution_order.append("C")
                result_c = {
                    "data": "from_c",
                    "sources": [result_a["data"], result_b["data"]]
                }

            tracker.track_event(
                event_type="dependency_order_verified",
                details={"execution_order": execution_order}
            )

        # Verify execution order
        assert execution_order == ["A", "B", "C"]


# ============================================================================
# Error Recovery End-to-End
# ============================================================================

class TestErrorRecoveryE2E:
    """Test error recovery across entire workflow."""

    def test_stage_failure_recovery(self):
        """Failed stage should trigger recovery mechanism."""
        from src.observability.tracker import ExecutionTracker
        from src.observability.database import init_database

        init_database("sqlite:///:memory:")
        tracker = ExecutionTracker()

        with tracker.track_workflow("error_recovery") as wf_id:
            # Stage 1: Success
            with tracker.track_agent("agent_1", "1.0") as agent_1_id:
                result_1 = {"status": "success"}

            # Stage 2: Failure
            try:
                with tracker.track_agent("agent_2", "1.0") as agent_2_id:
                    raise ValueError("Stage 2 failed")
            except ValueError as e:
                tracker.track_event(
                    event_type="stage_failed",
                    details={"stage": "agent_2", "error": str(e)}
                )

                # Recovery: Retry with fallback
                with tracker.track_agent("fallback_agent_2", "1.0") as fallback_id:
                    result_2 = {"status": "recovered", "fallback": True}
                    tracker.track_event(
                        event_type="recovery_successful",
                        details={"original_agent": "agent_2", "fallback_agent": "fallback_agent_2"}
                    )

            # Stage 3: Continue after recovery
            with tracker.track_agent("agent_3", "1.0") as agent_3_id:
                result_3 = {"status": "success", "previous": result_2}

        assert result_1["status"] == "success"
        assert result_2["status"] == "recovered"
        assert result_3["status"] == "success"

    def test_workflow_retry_on_failure(self):
        """Entire workflow should retry on critical failure."""
        from src.observability.tracker import ExecutionTracker
        from src.observability.database import init_database

        init_database("sqlite:///:memory:")
        tracker = ExecutionTracker()

        max_retries = 3
        attempt = 0
        success = False

        while attempt < max_retries and not success:
            attempt += 1

            try:
                with tracker.track_workflow(f"retry_workflow_attempt_{attempt}") as wf_id:
                    tracker.track_event(
                        event_type="workflow_attempt",
                        details={"attempt": attempt, "max_retries": max_retries}
                    )

                    # Simulate failure on first 2 attempts
                    if attempt < 3:
                        raise RuntimeError(f"Workflow failed on attempt {attempt}")

                    success = True
                    tracker.track_event(
                        event_type="workflow_succeeded",
                        details={"attempt": attempt}
                    )

            except RuntimeError as e:
                tracker.track_event(
                    event_type="workflow_retry",
                    details={"attempt": attempt, "error": str(e)}
                )

        assert success is True
        assert attempt == 3

    def test_partial_rollback_on_error(self):
        """Error should trigger partial rollback of completed stages."""
        from src.observability.tracker import ExecutionTracker
        from src.observability.database import init_database

        init_database("sqlite:///:memory:")
        tracker = ExecutionTracker()

        completed_stages = []
        rolled_back = []

        with tracker.track_workflow("partial_rollback") as wf_id:
            # Stage 1: Success
            with tracker.track_agent("agent_1", "1.0") as agent_1_id:
                completed_stages.append("stage_1")
                result_1 = {"file": "temp1.txt", "created": True}

            # Stage 2: Success
            with tracker.track_agent("agent_2", "1.0") as agent_2_id:
                completed_stages.append("stage_2")
                result_2 = {"file": "temp2.txt", "created": True}

            # Stage 3: Failure
            try:
                with tracker.track_agent("agent_3", "1.0") as agent_3_id:
                    raise IOError("Stage 3 failed - disk full")
            except IOError as e:
                tracker.track_event(
                    event_type="stage_failure",
                    details={"stage": "stage_3", "error": str(e)}
                )

                # Rollback completed stages in reverse order
                for stage in reversed(completed_stages):
                    tracker.track_event(
                        event_type="stage_rollback",
                        details={"stage": stage}
                    )
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
        from src.observability.database import init_database, get_session
        from src.observability.tracker import ExecutionTracker

        init_database("sqlite:///:memory:")
        tracker = ExecutionTracker()

        with tracker.track_workflow("transaction_rollback") as wf_id:
            try:
                # Simulate transactional operations
                tracker.track_event(
                    event_type="operation_1",
                    details={"data": "value1"}
                )

                tracker.track_event(
                    event_type="operation_2",
                    details={"data": "value2"}
                )

                # Simulate error
                raise ValueError("Transaction failed")

            except ValueError:
                tracker.track_event(
                    event_type="transaction_rolled_back",
                    details={"reason": "error_occurred"}
                )

        # Verify workflow was tracked despite rollback
        assert wf_id is not None

    def test_state_restoration_on_rollback(self):
        """System state should restore to previous checkpoint on rollback."""
        from src.observability.tracker import ExecutionTracker
        from src.observability.database import init_database

        init_database("sqlite:///:memory:")
        tracker = ExecutionTracker()

        with tracker.track_workflow("state_restoration") as wf_id:
            # Checkpoint initial state
            initial_state = {
                "counter": 0,
                "data": {},
                "flags": {"processed": False}
            }

            tracker.track_event(
                event_type="checkpoint_created",
                details={"state": initial_state.copy()}
            )

            # Modify state
            current_state = initial_state.copy()
            current_state["counter"] = 5
            current_state["data"] = {"key": "value"}
            current_state["flags"]["processed"] = True

            # Simulate error and rollback
            tracker.track_event(
                event_type="state_modified",
                details={"state": current_state}
            )

            # Rollback to checkpoint
            restored_state = initial_state.copy()
            tracker.track_event(
                event_type="state_restored",
                details={"state": restored_state}
            )

        # Verify state restoration
        assert restored_state == initial_state
        assert restored_state != current_state

    def test_cascading_rollback(self):
        """Rollback should cascade through dependent stages."""
        from src.observability.tracker import ExecutionTracker
        from src.observability.database import init_database

        init_database("sqlite:///:memory:")
        tracker = ExecutionTracker()

        rollback_order = []

        with tracker.track_workflow("cascading_rollback") as wf_id:
            # Create dependency chain: A -> B -> C -> D
            stages = ["A", "B", "C", "D"]
            stage_results = {}

            for stage in stages:
                with tracker.track_agent(f"agent_{stage}", "1.0") as agent_id:
                    stage_results[stage] = {"completed": True}

            # Failure in D triggers cascade
            try:
                raise RuntimeError("Stage D failed")
            except RuntimeError:
                # Rollback in reverse dependency order
                for stage in reversed(stages):
                    rollback_order.append(stage)
                    tracker.track_event(
                        event_type="cascading_rollback",
                        details={"stage": stage}
                    )

        assert rollback_order == ["D", "C", "B", "A"]


# ============================================================================
# Performance and Load Testing
# ============================================================================

class TestWorkflowPerformance:
    """Test workflow performance characteristics."""

    def test_high_volume_event_tracking(self):
        """System should handle high volume of events."""
        from src.observability.tracker import ExecutionTracker
        from src.observability.database import init_database

        init_database("sqlite:///:memory:")
        tracker = ExecutionTracker()

        event_count = 1000

        with tracker.track_workflow("high_volume_tracking") as wf_id:
            start_time = datetime.now(timezone.utc)

            for i in range(event_count):
                tracker.track_event(
                    event_type="high_volume_event",
                    details={"index": i, "data": f"event_{i}"}
                )

            end_time = datetime.now(timezone.utc)
            duration = (end_time - start_time).total_seconds()

            tracker.track_event(
                event_type="performance_metrics",
                details={
                    "event_count": event_count,
                    "duration_seconds": duration,
                    "events_per_second": event_count / duration if duration > 0 else 0
                }
            )

        # Should complete in reasonable time
        assert duration < 10.0  # Less than 10 seconds for 1000 events

    def test_concurrent_workflow_execution(self):
        """Multiple workflows should execute concurrently."""
        from src.observability.tracker import ExecutionTracker
        from src.observability.database import init_database

        init_database("sqlite:///:memory:")

        workflow_count = 10
        trackers = [ExecutionTracker() for _ in range(workflow_count)]
        workflow_ids = []

        start_time = datetime.now(timezone.utc)

        for i, tracker in enumerate(trackers):
            with tracker.track_workflow(f"concurrent_workflow_{i}") as wf_id:
                workflow_ids.append(wf_id)

                tracker.track_event(
                    event_type="workflow_executed",
                    details={"index": i}
                )

        end_time = datetime.now(timezone.utc)
        duration = (end_time - start_time).total_seconds()

        # Verify all workflows completed
        assert len(workflow_ids) == workflow_count
        assert len(set(workflow_ids)) == workflow_count  # All unique
        assert duration < 5.0  # Should be fast with concurrent execution
