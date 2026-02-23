"""Tests for state management module-level functions.

Verifies state initialization and init-node creation.
"""

import pytest

from temper_ai.stage.executors.state_keys import StateKeys
from temper_ai.workflow.langgraph_state import LangGraphWorkflowState
from temper_ai.workflow.state_manager import create_init_node, initialize_state


class TestStateInitialization:
    """Test state initialization functions."""

    def test_initialize_state_basic(self):
        """Test basic state initialization."""
        state = initialize_state({"input": "test data"})

        assert isinstance(state, dict)
        assert state["workflow_inputs"]["input"] == "test data"
        assert state[StateKeys.WORKFLOW_ID].startswith("wf-")
        assert state[StateKeys.STAGE_OUTPUTS] == {}

    def test_initialize_state_with_workflow_id(self):
        """Test initialization with custom workflow ID."""
        state = initialize_state({"input": "test"}, workflow_id="wf-custom-123")

        assert state[StateKeys.WORKFLOW_ID] == "wf-custom-123"

    def test_initialize_state_with_tracker(self):
        """Test initialization with tracker."""
        mock_tracker = object()

        state = initialize_state({"input": "test"}, tracker=mock_tracker)

        assert state["tracker"] is mock_tracker

    def test_initialize_state_with_infrastructure(self):
        """Test initialization with all infrastructure components."""
        mock_tracker = object()
        mock_registry = object()
        mock_loader = object()

        state = initialize_state(
            {"input": "test"},
            tracker=mock_tracker,
            tool_registry=mock_registry,
            config_loader=mock_loader,
        )

        assert state["tracker"] is mock_tracker
        assert state["tool_registry"] is mock_registry
        assert state["config_loader"] is mock_loader


class TestInitNode:
    """Test initialization node creation."""

    def test_init_node_sets_stage_outputs_when_none(self):
        """Test init node creates stage_outputs when None."""
        init_node = create_init_node()

        # Create state and force stage_outputs to None (bypassing __post_init__)
        state = LangGraphWorkflowState(input="test")
        state.stage_outputs = None

        result = init_node(state)

        assert "stage_outputs" in result
        assert isinstance(result[StateKeys.STAGE_OUTPUTS], dict)

    def test_init_node_initializes_workflow_id(self):
        """Test init node creates workflow_id if missing."""
        init_node = create_init_node()

        # Create state with empty workflow_id
        state = LangGraphWorkflowState(input="test")
        state.workflow_id = ""

        result = init_node(state)

        assert "workflow_id" in result
        assert result[StateKeys.WORKFLOW_ID].startswith("wf-")

    def test_init_node_preserves_existing_values(self):
        """Test init node doesn't overwrite existing values."""
        init_node = create_init_node()

        # Create state with values already set
        state = LangGraphWorkflowState(
            input="test",
            workflow_id="wf-existing-123",
            stage_outputs={"stage1": "output1"},
        )

        # Run init node — should return empty updates since nothing needs initialization
        result = init_node(state)

        assert "workflow_id" not in result
        assert "stage_outputs" not in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
