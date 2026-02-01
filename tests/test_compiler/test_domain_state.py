"""Tests for domain state and execution context separation (M3.2-05).

This module tests the fundamental separation between:
- WorkflowDomainState: Serializable domain data (checkpointable)
- ExecutionContext: Infrastructure components (recreated on resume)

Critical for checkpoint/resume capability (m3.2-06).
"""
import pytest
import json
from datetime import datetime
from src.compiler.domain_state import (
    WorkflowDomainState,
    ExecutionContext,
    create_initial_domain_state,
    merge_domain_states,
)


class TestWorkflowDomainState:
    """Test WorkflowDomainState - pure serializable domain data."""

    def test_initialization_with_defaults(self):
        """Test domain state creation with default values."""
        state = WorkflowDomainState()

        assert state.stage_outputs == {}
        assert state.current_stage == ""
        assert state.workflow_id.startswith("wf-")
        assert state.version == "1.0"
        assert isinstance(state.created_at, datetime)
        assert state.metadata == {}

    def test_initialization_with_inputs(self):
        """Test domain state creation with workflow inputs."""
        state = WorkflowDomainState(
            workflow_id="wf-test-123",
            input="Analyze market trends",
            topic="Market Analysis",
            depth="comprehensive",
            focus_areas=["technology", "finance"]
        )

        assert state.workflow_id == "wf-test-123"
        assert state.input == "Analyze market trends"
        assert state.topic == "Market Analysis"
        assert state.depth == "comprehensive"
        assert state.focus_areas == ["technology", "finance"]

    def test_workflow_id_auto_prefix(self):
        """Test workflow_id automatically gets 'wf-' prefix."""
        state = WorkflowDomainState(workflow_id="test-123")
        assert state.workflow_id == "wf-test-123"

    def test_focus_areas_list_conversion(self):
        """Test focus_areas converts non-list to list."""
        state = WorkflowDomainState(focus_areas="single-item")
        assert isinstance(state.focus_areas, list)
        assert state.focus_areas == ["single-item"]

    def test_set_stage_output(self):
        """Test setting stage output updates state correctly."""
        state = WorkflowDomainState()
        output_data = {"findings": ["item1", "item2"]}

        state.set_stage_output("research", output_data)

        assert state.stage_outputs["research"] == output_data
        assert state.current_stage == "research"

    def test_get_stage_output(self):
        """Test getting stage output."""
        state = WorkflowDomainState()
        output_data = {"findings": ["item1"]}
        state.set_stage_output("research", output_data)

        assert state.get_stage_output("research") == output_data
        assert state.get_stage_output("nonexistent") is None
        assert state.get_stage_output("nonexistent", "default") == "default"

    def test_has_stage_output(self):
        """Test checking if stage has output."""
        state = WorkflowDomainState()
        state.set_stage_output("research", {"data": "value"})

        assert state.has_stage_output("research") is True
        assert state.has_stage_output("analysis") is False

    def test_get_previous_outputs(self):
        """Test getting all previous stage outputs."""
        state = WorkflowDomainState()
        state.set_stage_output("research", {"data": "research"})
        state.set_stage_output("analysis", {"data": "analysis"})

        outputs = state.get_previous_outputs()

        assert len(outputs) == 2
        assert outputs["research"] == {"data": "research"}
        assert outputs["analysis"] == {"data": "analysis"}

    def test_to_dict_serialization(self):
        """Test domain state serialization to dict."""
        state = WorkflowDomainState(
            workflow_id="wf-test-123",
            input="test input",
            topic="test topic"
        )
        state.set_stage_output("research", {"findings": ["item1"]})

        state_dict = state.to_dict()

        # All fields should be serializable
        assert state_dict["workflow_id"] == "wf-test-123"
        assert state_dict["input"] == "test input"
        assert state_dict["topic"] == "test topic"
        assert state_dict["stage_outputs"] == {"research": {"findings": ["item1"]}}
        assert isinstance(state_dict["created_at"], str)  # datetime serialized

    def test_to_dict_exclude_none(self):
        """Test domain state serialization excluding None values."""
        state = WorkflowDomainState(
            workflow_id="wf-test-123",
            input="test input"
            # topic, depth, etc. are None
        )

        state_dict = state.to_dict(exclude_none=True)

        assert "workflow_id" in state_dict
        assert "input" in state_dict
        assert "topic" not in state_dict
        assert "depth" not in state_dict

    def test_from_dict_deserialization(self):
        """Test domain state deserialization from dict."""
        data = {
            "workflow_id": "wf-test-123",
            "current_stage": "research",
            "stage_outputs": {"research": {"data": "value"}},
            "input": "test input",
            "topic": "test topic",
            "version": "1.0",
            "created_at": "2026-01-27T10:00:00"
        }

        state = WorkflowDomainState.from_dict(data)

        assert state.workflow_id == "wf-test-123"
        assert state.current_stage == "research"
        assert state.stage_outputs == {"research": {"data": "value"}}
        assert state.input == "test input"
        assert state.topic == "test topic"
        assert isinstance(state.created_at, datetime)

    def test_json_serialization_roundtrip(self):
        """Test that domain state can be serialized to JSON and back (checkpoint)."""
        original = WorkflowDomainState(
            workflow_id="wf-checkpoint-test",
            input="test input",
            topic="test topic"
        )
        original.set_stage_output("research", {"findings": ["item1", "item2"]})

        # Serialize to JSON (like saving a checkpoint)
        checkpoint_json = json.dumps(original.to_dict())

        # Deserialize from JSON (like loading a checkpoint)
        checkpoint_data = json.loads(checkpoint_json)
        restored = WorkflowDomainState.from_dict(checkpoint_data)

        # Verify restoration
        assert restored.workflow_id == original.workflow_id
        assert restored.input == original.input
        assert restored.topic == original.topic
        assert restored.stage_outputs == original.stage_outputs

    def test_validate_success(self):
        """Test validation succeeds for valid state."""
        state = WorkflowDomainState(workflow_id="wf-test-123")
        valid, errors = state.validate()

        assert valid is True
        assert len(errors) == 0

    def test_validate_invalid_workflow_id(self):
        """Test validation fails for invalid workflow_id."""
        state = WorkflowDomainState()
        state.workflow_id = ""  # Invalid

        valid, errors = state.validate()

        assert valid is False
        assert len(errors) > 0
        assert any("workflow_id" in str(err) for err in errors)

    def test_copy_creates_independent_state(self):
        """Test copying creates independent domain state."""
        original = WorkflowDomainState(workflow_id="wf-original")
        original.set_stage_output("research", {"data": "original"})

        copy = original.copy()

        # Modify copy
        copy.set_stage_output("analysis", {"data": "copy"})

        # Original should be unchanged
        assert "analysis" not in original.stage_outputs
        assert "analysis" in copy.stage_outputs

    def test_repr(self):
        """Test string representation."""
        state = WorkflowDomainState(workflow_id="wf-test-123")
        state.set_stage_output("research", {"data": "value"})

        repr_str = repr(state)

        assert "WorkflowDomainState" in repr_str
        assert "wf-test-123" in repr_str
        assert "num_stages=1" in repr_str


class TestExecutionContext:
    """Test ExecutionContext - infrastructure components."""

    def test_initialization_empty(self):
        """Test execution context creation with no components."""
        context = ExecutionContext()

        assert context.tracker is None
        assert context.tool_registry is None
        assert context.config_loader is None
        assert context.visualizer is None

    def test_initialization_with_components(self):
        """Test execution context creation with infrastructure components."""
        # Mock infrastructure components
        mock_tracker = {"type": "tracker"}
        mock_registry = {"type": "registry"}
        mock_loader = {"type": "loader"}

        context = ExecutionContext(
            tracker=mock_tracker,
            tool_registry=mock_registry,
            config_loader=mock_loader
        )

        assert context.tracker == mock_tracker
        assert context.tool_registry == mock_registry
        assert context.config_loader == mock_loader
        assert context.visualizer is None

    def test_context_not_serialized(self):
        """Test that execution context cannot be JSON-serialized (by design)."""
        # Mock non-serializable objects
        class NonSerializable:
            pass

        context = ExecutionContext(
            tracker=NonSerializable(),
            tool_registry=NonSerializable()
        )

        # Attempting to serialize should raise error (this is intentional)
        with pytest.raises((TypeError, AttributeError)):
            json.dumps(context.__dict__)

    def test_repr(self):
        """Test string representation shows available components."""
        context = ExecutionContext(
            tracker={"type": "tracker"},
            tool_registry={"type": "registry"}
        )

        repr_str = repr(context)

        assert "ExecutionContext" in repr_str
        assert "tracker" in repr_str
        assert "tool_registry" in repr_str
        assert "config_loader" not in repr_str  # Not set


class TestStateFactoryFunctions:
    """Test factory functions for creating domain state."""

    def test_create_initial_domain_state(self):
        """Test create_initial_domain_state factory function."""
        state = create_initial_domain_state(
            input="test input",
            topic="test topic",
            depth="comprehensive"
        )

        assert isinstance(state, WorkflowDomainState)
        assert state.input == "test input"
        assert state.topic == "test topic"
        assert state.depth == "comprehensive"

    def test_merge_domain_states(self):
        """Test merge_domain_states merges updates correctly."""
        base_state = WorkflowDomainState(
            workflow_id="wf-test-123",
            input="original input"
        )
        base_state.set_stage_output("research", {"data": "original"})

        updates = {
            "current_stage": "analysis",
            "data": {"new": "data"}
        }

        merged = merge_domain_states(base_state, updates)

        # Base state unchanged
        assert base_state.current_stage == "research"
        assert base_state.data is None

        # Merged state has updates
        assert merged.current_stage == "analysis"
        assert merged.data == {"new": "data"}
        # Original fields preserved
        assert merged.workflow_id == "wf-test-123"
        assert merged.input == "original input"
        assert merged.stage_outputs == {"research": {"data": "original"}}


class TestCheckpoint:
    """Test real-world checkpoint/resume scenarios."""

    def test_checkpoint_save_and_resume(self):
        """Test complete checkpoint save and resume workflow."""
        # Step 1: Create workflow with domain and context
        domain = WorkflowDomainState(
            workflow_id="wf-checkpoint-test",
            input="Analyze market trends",
            topic="Market Analysis"
        )
        domain.set_stage_output("research", {"findings": ["trend1", "trend2"]})
        domain.set_stage_output("analysis", {"insights": ["insight1"]})

        # Mock infrastructure (not checkpointed)
        context = ExecutionContext(
            tracker={"type": "mock_tracker"},
            tool_registry={"type": "mock_registry"}
        )

        # Step 2: Save checkpoint (only domain state)
        checkpoint = domain.to_dict(exclude_none=True)
        checkpoint_json = json.dumps(checkpoint)

        # Step 3: Simulate restart - load checkpoint
        loaded_checkpoint = json.loads(checkpoint_json)
        resumed_domain = WorkflowDomainState.from_dict(loaded_checkpoint)

        # Step 4: Recreate infrastructure (not from checkpoint)
        resumed_context = ExecutionContext(
            tracker={"type": "new_tracker"},
            tool_registry={"type": "new_registry"}
        )

        # Verify: Domain state fully restored
        assert resumed_domain.workflow_id == "wf-checkpoint-test"
        assert resumed_domain.input == "Analyze market trends"
        assert resumed_domain.topic == "Market Analysis"
        assert resumed_domain.stage_outputs == {
            "research": {"findings": ["trend1", "trend2"]},
            "analysis": {"insights": ["insight1"]}
        }

        # Verify: Infrastructure recreated (different instances)
        assert resumed_context.tracker != context.tracker
        assert resumed_context.tracker == {"type": "new_tracker"}

    def test_checkpoint_serialization_excludes_infrastructure(self):
        """Test that checkpoint serialization excludes all infrastructure."""
        domain = WorkflowDomainState(workflow_id="wf-test")

        # Checkpoint should only contain domain fields
        checkpoint = domain.to_dict(exclude_none=True)

        # Verify no infrastructure fields
        assert "tracker" not in checkpoint
        assert "tool_registry" not in checkpoint
        assert "config_loader" not in checkpoint
        assert "visualizer" not in checkpoint

        # Verify domain fields present
        assert "workflow_id" in checkpoint
        assert "stage_outputs" in checkpoint
        assert "version" in checkpoint

    def test_partial_checkpoint_resume(self):
        """Test resuming from checkpoint with partial execution."""
        # Original execution: completed 2/3 stages
        original = WorkflowDomainState(workflow_id="wf-partial")
        original.set_stage_output("stage1", {"result": "completed"})
        original.set_stage_output("stage2", {"result": "completed"})
        # stage3 not yet executed

        # Save checkpoint
        checkpoint = json.dumps(original.to_dict())

        # Resume
        resumed = WorkflowDomainState.from_dict(json.loads(checkpoint))

        # Should have completed stages
        assert resumed.has_stage_output("stage1")
        assert resumed.has_stage_output("stage2")
        assert not resumed.has_stage_output("stage3")

        # Can continue execution
        resumed.set_stage_output("stage3", {"result": "completed"})
        assert resumed.has_stage_output("stage3")
