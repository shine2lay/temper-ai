"""Tests for StateManager class.

Verifies state initialization, validation, and utility methods.
"""
import pytest

from src.compiler.executors.state_keys import StateKeys
from src.compiler.langgraph_state import LangGraphWorkflowState
from src.compiler.state_manager import StateManager


class TestStateInitialization:
    """Test state initialization methods."""

    def test_initialize_state_basic(self):
        """Test basic state initialization."""
        manager = StateManager()

        state = manager.initialize_state({"input": "test data"})

        assert isinstance(state, dict)
        assert state["workflow_inputs"]["input"] == "test data"
        assert state[StateKeys.WORKFLOW_ID].startswith("wf-")
        assert state[StateKeys.STAGE_OUTPUTS] == {}

    def test_initialize_state_with_workflow_id(self):
        """Test initialization with custom workflow ID."""
        manager = StateManager()

        state = manager.initialize_state(
            {"input": "test"},
            workflow_id="wf-custom-123"
        )

        assert state[StateKeys.WORKFLOW_ID] == "wf-custom-123"

    def test_initialize_state_with_tracker(self):
        """Test initialization with tracker."""
        manager = StateManager()
        mock_tracker = object()

        state = manager.initialize_state(
            {"input": "test"},
            tracker=mock_tracker
        )

        assert state["tracker"] is mock_tracker

    def test_initialize_state_with_infrastructure(self):
        """Test initialization with all infrastructure components."""
        manager = StateManager()
        mock_tracker = object()
        mock_registry = object()
        mock_loader = object()

        state = manager.initialize_state(
            {"input": "test"},
            tracker=mock_tracker,
            tool_registry=mock_registry,
            config_loader=mock_loader
        )

        assert state["tracker"] is mock_tracker
        assert state["tool_registry"] is mock_registry
        assert state["config_loader"] is mock_loader


class TestInitNode:
    """Test initialization node creation."""

    def test_create_init_node(self):
        """Test creating initialization node."""
        manager = StateManager()

        init_node = manager.create_init_node()

        assert callable(init_node)

    def test_init_node_sets_stage_outputs_when_none(self):
        """Test init node creates stage_outputs when None."""
        manager = StateManager()
        init_node = manager.create_init_node()

        # Create state and force stage_outputs to None (bypassing __post_init__)
        state = LangGraphWorkflowState(input="test")
        state.stage_outputs = None

        result = init_node(state)

        assert "stage_outputs" in result
        assert isinstance(result[StateKeys.STAGE_OUTPUTS], dict)

    def test_init_node_initializes_workflow_id(self):
        """Test init node creates workflow_id if missing."""
        manager = StateManager()
        init_node = manager.create_init_node()

        # Create state with empty workflow_id
        state = LangGraphWorkflowState(input="test")
        state.workflow_id = ""

        result = init_node(state)

        assert "workflow_id" in result
        assert result[StateKeys.WORKFLOW_ID].startswith("wf-")

    def test_init_node_preserves_existing_values(self):
        """Test init node doesn't overwrite existing values."""
        manager = StateManager()
        init_node = manager.create_init_node()

        # Create state with values already set
        state = LangGraphWorkflowState(
            input="test",
            workflow_id="wf-existing-123",
            stage_outputs={"stage1": "output1"}
        )

        # Run init node — should return empty updates since nothing needs initialization
        result = init_node(state)

        assert "workflow_id" not in result
        assert "stage_outputs" not in result


class TestStateValidation:
    """Test state validation methods."""

    def test_validate_state_valid(self):
        """Test validation of valid state."""
        manager = StateManager()
        state = manager.initialize_state({"input": "test"})

        valid, errors = manager.validate_state(state)

        assert valid is True
        assert errors == []

    def test_validate_state_missing_stage_outputs(self):
        """Test that validation catches missing stage_outputs."""
        manager = StateManager()
        state = {"input": "test"}  # No stage_outputs

        valid, errors = manager.validate_state(state)

        assert valid is False
        assert "Missing stage_outputs" in errors


class TestStageInput:
    """Test stage input preparation."""

    def test_prepare_stage_input_basic(self):
        """Test basic stage input preparation."""
        manager = StateManager()
        state = manager.initialize_state({"input": "test", "topic": "research"})

        stage_input = manager.prepare_stage_input(state)

        assert isinstance(stage_input, dict)
        assert stage_input["input"] == "test"
        assert stage_input["topic"] == "research"

    def test_prepare_stage_input_excludes_internal(self):
        """Test that internal objects are excluded."""
        manager = StateManager()
        mock_tracker = object()
        state = manager.initialize_state(
            {"input": "test"},
            tracker=mock_tracker
        )

        stage_input = manager.prepare_stage_input(state)

        # Internal objects should be excluded
        assert "tracker" not in stage_input
        assert "tool_registry" not in stage_input
        assert "config_loader" not in stage_input

    def test_prepare_stage_input_includes_previous_outputs(self):
        """Test that previous stage outputs are included by default."""
        manager = StateManager()
        state = manager.initialize_state({"input": "test"})
        state[StateKeys.STAGE_OUTPUTS]["stage1"] = "output1"

        stage_input = manager.prepare_stage_input(state)

        assert "stage_outputs" in stage_input
        assert stage_input[StateKeys.STAGE_OUTPUTS] == {"stage1": "output1"}

    def test_prepare_stage_input_excludes_previous_outputs(self):
        """Test excluding previous stage outputs."""
        manager = StateManager()
        state = manager.initialize_state({"input": "test"})
        state[StateKeys.STAGE_OUTPUTS]["stage1"] = "output1"

        stage_input = manager.prepare_stage_input(
            state,
            include_previous_outputs=False
        )

        assert "stage_outputs" not in stage_input


class TestStageOutput:
    """Test stage output merging."""

    def test_merge_stage_output(self):
        """Test merging stage output into state."""
        manager = StateManager()
        state = manager.initialize_state({"input": "test"})

        updated_state = manager.merge_stage_output(
            state,
            "research",
            {"findings": ["finding1", "finding2"]}
        )

        assert updated_state[StateKeys.STAGE_OUTPUTS]["research"]["findings"] == ["finding1", "finding2"]
        assert updated_state[StateKeys.CURRENT_STAGE] == "research"

    def test_merge_multiple_stage_outputs(self):
        """Test merging multiple stage outputs."""
        manager = StateManager()
        state = manager.initialize_state({"input": "test"})

        state = manager.merge_stage_output(state, "stage1", "output1")
        state = manager.merge_stage_output(state, "stage2", "output2")

        assert state[StateKeys.STAGE_OUTPUTS]["stage1"] == "output1"
        assert state[StateKeys.STAGE_OUTPUTS]["stage2"] == "output2"
        assert state[StateKeys.CURRENT_STAGE] == "stage2"


class TestStateSnapshot:
    """Test state snapshot and restore."""

    def test_get_state_snapshot(self):
        """Test creating state snapshot."""
        manager = StateManager()
        state = manager.initialize_state({"input": "test", "topic": "research"})
        state[StateKeys.STAGE_OUTPUTS]["stage1"] = "output1"

        snapshot = manager.get_state_snapshot(state)

        assert isinstance(snapshot, dict)
        assert snapshot["workflow_inputs"]["input"] == "test"
        assert snapshot["workflow_inputs"]["topic"] == "research"
        assert snapshot[StateKeys.STAGE_OUTPUTS] == {"stage1": "output1"}

    def test_snapshot_excludes_none(self):
        """Test that snapshot excludes None values."""
        manager = StateManager()
        state = manager.initialize_state({"input": "test"})

        snapshot = manager.get_state_snapshot(state)

        # Keys not present in dict won't appear in snapshot
        assert "depth" not in snapshot
        assert "focus_areas" not in snapshot

    def test_snapshot_excludes_internal(self):
        """Test that snapshot excludes internal objects."""
        manager = StateManager()
        mock_tracker = object()
        state = manager.initialize_state(
            {"input": "test"},
            tracker=mock_tracker
        )

        snapshot = manager.get_state_snapshot(state)

        assert "tracker" not in snapshot
        assert "tool_registry" not in snapshot
        assert "config_loader" not in snapshot

    def test_restore_state_from_snapshot(self):
        """Test restoring state from snapshot."""
        manager = StateManager()

        # Create snapshot
        snapshot = {
            "input": "test data",
            "topic": "research",
            "workflow_id": "wf-snapshot-123",
            "stage_outputs": {"stage1": "output1"}
        }

        state = manager.restore_state_from_snapshot(snapshot)

        assert isinstance(state, dict)
        assert state["input"] == "test data"
        assert state["topic"] == "research"
        assert state[StateKeys.WORKFLOW_ID] == "wf-snapshot-123"
        assert state[StateKeys.STAGE_OUTPUTS] == {"stage1": "output1"}

    def test_snapshot_roundtrip(self):
        """Test snapshot and restore roundtrip."""
        manager = StateManager()

        # Create original state
        original_state = manager.initialize_state(
            {"input": "test", "topic": "research"}
        )
        original_state[StateKeys.STAGE_OUTPUTS]["stage1"] = "output1"

        # Create snapshot and restore
        snapshot = manager.get_state_snapshot(original_state)
        restored_state = manager.restore_state_from_snapshot(snapshot)

        # Values should match
        assert restored_state["workflow_inputs"]["input"] == original_state["workflow_inputs"]["input"]
        assert restored_state["workflow_inputs"]["topic"] == original_state["workflow_inputs"]["topic"]
        assert restored_state[StateKeys.STAGE_OUTPUTS] == original_state[StateKeys.STAGE_OUTPUTS]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
