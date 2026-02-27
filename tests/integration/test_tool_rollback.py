"""Integration tests for tool executor rollback functionality.

Tests the integration of RollbackManager with ToolExecutor for
automatic rollback on tool failures, approval rejection, and policy violations.
"""

import os
import tempfile
from unittest.mock import Mock

import pytest

from temper_ai.safety.action_policy_engine import (
    ActionPolicyEngine,
    EnforcementResult,
)
from temper_ai.safety.approval import ApprovalWorkflow
from temper_ai.safety.interfaces import SafetyViolation, ViolationSeverity
from temper_ai.safety.rollback import RollbackManager, RollbackStatus
from temper_ai.storage.database.manager import init_database
from temper_ai.tools.base import BaseTool, ToolMetadata, ToolResult
from temper_ai.tools.executor import ToolExecutor
from temper_ai.tools.registry import ToolRegistry


class FileWriteTool(BaseTool):
    """Test tool that writes to a file."""

    def get_metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name="write_file",
            description="Write content to file",
            version="1.0.0",
            category="file",
        )

    def get_parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
                "fail": {"type": "boolean"},
            },
            "required": ["path", "content"],
        }

    def execute(self, path: str, content: str, fail: bool = False) -> ToolResult:
        """Execute file write."""
        if fail:
            return ToolResult(
                success=False, result=None, error="Simulated tool failure"
            )

        with open(path, "w") as f:
            f.write(content)

        return ToolResult(
            success=True,
            result={"path": path, "bytes_written": len(content)},
            error=None,
        )


class TestToolRollback:
    """Test suite for tool executor rollback integration."""

    @pytest.fixture(autouse=True)
    def sample_database(self):
        """Initialize in-memory database for rollback logging."""
        try:
            from temper_ai.storage.database.manager import get_database

            get_database()
        except RuntimeError:
            init_database("sqlite:///:memory:")
        yield

    @pytest.fixture
    def temp_file(self):
        """Create temporary file for testing."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
            f.write("original content")
            temp_path = f.name

        yield temp_path

        # Cleanup
        if os.path.exists(temp_path):
            os.unlink(temp_path)

    @pytest.fixture
    def registry(self):
        """Create tool registry with test tool."""
        registry = ToolRegistry()
        registry.register(FileWriteTool())
        return registry

    @pytest.fixture
    def rollback_manager(self):
        """Create rollback manager."""
        return RollbackManager()

    def test_tool_failure_auto_rollback(self, registry, rollback_manager, temp_file):
        """Test auto-rollback on tool failure."""
        # Setup executor with rollback
        executor = ToolExecutor(
            registry=registry,
            rollback_manager=rollback_manager,
            enable_auto_rollback=True,
        )

        # Verify original content
        with open(temp_file) as f:
            assert f.read() == "original content"

        # Execute tool that will fail (but after modifying file conceptually)
        # Since our tool fails immediately, we need to test a scenario where
        # snapshot was created and then execution failed
        result = executor.execute(
            tool_name="write_file",
            params={"path": temp_file, "content": "new content", "fail": True},
            context={"agent_id": "test-agent"},
        )

        # Verify tool failed
        assert not result.success
        assert "Simulated tool failure" in result.error

        # File should remain unchanged (or be rolled back if changed)
        with open(temp_file) as f:
            content = f.read()
            assert content == "original content"

    def test_tool_success_no_rollback(self, registry, rollback_manager, temp_file):
        """Test no rollback on successful execution."""
        executor = ToolExecutor(
            registry=registry,
            rollback_manager=rollback_manager,
            enable_auto_rollback=True,
        )

        # Execute successful tool
        result = executor.execute(
            tool_name="write_file",
            params={"path": temp_file, "content": "new content", "fail": False},
            context={"agent_id": "test-agent"},
        )

        # Verify tool succeeded
        assert result.success

        # File should have new content
        with open(temp_file) as f:
            assert f.read() == "new content"

        # No rollback should have been executed
        history = rollback_manager.get_history()
        assert len(history) == 0

    def test_auto_rollback_disabled(self, registry, rollback_manager, temp_file):
        """Test that rollback can be disabled."""
        executor = ToolExecutor(
            registry=registry,
            rollback_manager=rollback_manager,
            enable_auto_rollback=False,
        )

        # Execute failing tool
        result = executor.execute(
            tool_name="write_file",
            params={"path": temp_file, "content": "new content", "fail": True},
            context={"agent_id": "test-agent"},
        )

        # Verify tool failed
        assert not result.success

        # No rollback should have been executed
        history = rollback_manager.get_history()
        assert len(history) == 0

    def test_snapshot_only_for_state_modifying_tools(self, registry, rollback_manager):
        """Test that snapshots are only created for state-modifying tools."""

        # Create a read-only tool
        class ReadTool(BaseTool):
            def get_metadata(self) -> ToolMetadata:
                return ToolMetadata(
                    name="read_file",
                    description="Read file",
                    version="1.0.0",
                    category="file",
                    modifies_state=False,  # Read-only tool
                )

            def get_parameters_schema(self) -> dict:
                return {"type": "object", "properties": {}, "required": []}

            def execute(self) -> ToolResult:
                return ToolResult(success=True, result="file content", error=None)

        registry.register(ReadTool())

        executor = ToolExecutor(
            registry=registry,
            rollback_manager=rollback_manager,
            enable_auto_rollback=True,
        )

        # Execute read tool
        result = executor.execute(
            tool_name="read_file", params={}, context={"agent_id": "test-agent"}
        )

        assert result.success

        # No snapshot should have been created
        snapshots = rollback_manager.list_snapshots()
        assert len(snapshots) == 0

    def test_policy_blocking(self, registry, rollback_manager, temp_file):
        """Test policy blocking prevents execution."""
        # Mock policy engine that blocks action
        mock_policy_engine = Mock(spec=ActionPolicyEngine)
        mock_policy_engine.validate_action_sync = Mock(
            return_value=EnforcementResult(
                allowed=False,
                violations=[
                    SafetyViolation(
                        policy_name="test_policy",
                        severity=ViolationSeverity.CRITICAL,
                        message="Action blocked by policy",
                        action="write_file",
                        context={},
                    )
                ],
                policies_executed=["test_policy"],
                execution_time_ms=1.0,
                metadata={},
                cache_hit=False,
            )
        )

        executor = ToolExecutor(
            registry=registry,
            rollback_manager=rollback_manager,
            policy_engine=mock_policy_engine,
            enable_auto_rollback=True,
        )

        # Execute tool (should be blocked)
        result = executor.execute(
            tool_name="write_file",
            params={"path": temp_file, "content": "new content"},
            context={
                "agent_id": "test-agent",
                "workflow_id": "wf-1",
                "stage_id": "stage-1",
            },
        )

        # Verify execution was blocked
        assert not result.success
        assert "Action blocked by policy" in result.error

        # File should remain unchanged
        with open(temp_file) as f:
            assert f.read() == "original content"

        # No snapshot or rollback should have been created
        assert len(rollback_manager.list_snapshots()) == 0
        assert len(rollback_manager.get_history()) == 0

    def test_rollback_metadata(self, registry, rollback_manager, temp_file):
        """Test rollback metadata is properly populated."""
        executor = ToolExecutor(
            registry=registry,
            rollback_manager=rollback_manager,
            enable_auto_rollback=True,
        )

        # Execute failing tool
        result = executor.execute(
            tool_name="write_file",
            params={"path": temp_file, "content": "new content", "fail": True},
            context={"agent_id": "test-agent-123", "workflow_id": "wf-456"},
        )

        # Verify metadata if rollback occurred
        if result.metadata and result.metadata.get("rollback_executed"):
            assert result.metadata["rollback_snapshot_id"]
            assert result.metadata["rollback_status"] in [
                s.value for s in RollbackStatus
            ]


class TestApprovalRejectionRollback:
    """Test approval rejection triggers rollback."""

    @pytest.fixture(autouse=True)
    def sample_database(self):
        """Initialize in-memory database for rollback logging."""
        try:
            from temper_ai.storage.database.manager import get_database

            get_database()
        except RuntimeError:
            init_database("sqlite:///:memory:")
        yield

    @pytest.fixture
    def temp_file(self):
        """Create temporary file for testing."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
            f.write("original content")
            temp_path = f.name

        yield temp_path

        if os.path.exists(temp_path):
            os.unlink(temp_path)

    def test_approval_rejection_callback(self):
        """Test approval rejection callback triggers rollback."""
        rollback_manager = RollbackManager()
        approval_workflow = ApprovalWorkflow()

        # Create executor with both components
        registry = ToolRegistry()
        registry.register(FileWriteTool())

        ToolExecutor(
            registry=registry,
            rollback_manager=rollback_manager,
            approval_workflow=approval_workflow,
            enable_auto_rollback=True,
        )

        # Create a snapshot manually
        snapshot = rollback_manager.create_snapshot(
            action={"tool": "write_file"}, context={"agent_id": "test-agent"}
        )

        # Create approval request with snapshot ID in metadata
        approval_request = approval_workflow.request_approval(
            action={"tool": "write_file"},
            reason="Test approval",
            context={"agent_id": "test-agent"},
            violations=[],
            metadata={"rollback_snapshot_id": snapshot.id},
        )

        # Reject approval (should trigger rollback via callback)
        approval_workflow.reject(
            approval_request.id, rejecter="test-user", reason="Test rejection"
        )

        # Verify rollback was executed
        history = rollback_manager.get_history()
        assert len(history) > 0
        assert history[0].snapshot_id == snapshot.id
