"""Tests for workflow input passthrough via workflow_inputs field.

Verifies that custom user inputs (e.g., problem_description, technical_context)
survive LangGraph dataclass coercion and reach agents.
"""
import pytest

from src.workflow.domain_state import WorkflowDomainState
from src.stage.executors.state_keys import StateKeys
from src.workflow.langgraph_state import LangGraphWorkflowState
from src.workflow.state_manager import initialize_state


class TestInputPassthrough:
    """Test that custom inputs flow through to agents."""

    def test_custom_inputs_stored_in_workflow_inputs(self):
        """Custom fields passed to from_dict() are stored in workflow_inputs."""
        data = {
            "workflow_id": "wf-test123",
            "problem_description": "Memory leak in production",
            "technical_context": "Python 3.11, asyncio-based service",
            "constraints": "Must not increase latency",
        }
        state = WorkflowDomainState.from_dict(data)

        assert state.workflow_inputs["problem_description"] == "Memory leak in production"
        assert state.workflow_inputs["technical_context"] == "Python 3.11, asyncio-based service"
        assert state.workflow_inputs["constraints"] == "Must not increase latency"

    def test_known_fields_not_duplicated_in_workflow_inputs(self):
        """Known fields (topic, query, etc.) stay in their own attributes."""
        data = {
            "topic": "Python typing",
            "query": "How to use generics?",
            "problem_description": "Complex type",
        }
        state = WorkflowDomainState.from_dict(data)

        assert state.topic == "Python typing"
        assert state.query == "How to use generics?"
        assert "topic" not in state.workflow_inputs
        assert "query" not in state.workflow_inputs
        assert state.workflow_inputs["problem_description"] == "Complex type"

    def test_workflow_inputs_in_to_dict(self):
        """workflow_inputs appears in to_dict() output."""
        state = WorkflowDomainState(
            workflow_inputs={"custom_field": "value"}
        )
        d = state.to_dict()
        assert d["workflow_inputs"] == {"custom_field": "value"}

    def test_workflow_inputs_survives_copy(self):
        """workflow_inputs is deep-copied."""
        state = WorkflowDomainState(
            workflow_inputs={"nested": {"key": "value"}}
        )
        copied = state.copy()

        # Modify original - copy should be independent
        state.workflow_inputs["nested"]["key"] = "changed"
        assert copied.workflow_inputs["nested"]["key"] == "value"

    def test_langgraph_state_inherits_workflow_inputs(self):
        """LangGraphWorkflowState has workflow_inputs via inheritance."""
        state = LangGraphWorkflowState(
            workflow_inputs={"problem_description": "test"}
        )
        assert state.workflow_inputs["problem_description"] == "test"

        d = state.to_dict()
        assert d["workflow_inputs"]["problem_description"] == "test"

    def test_langgraph_coercion_preserves_workflow_inputs(self):
        """Simulates LangGraph coercion: dict → dataclass → dict → agent input."""
        # Step 1: CLI creates state dict with workflow_inputs
        cli_state = {
            "workflow_inputs": {
                "problem_description": "Memory leak",
                "technical_context": "asyncio service",
                "severity": "high",
            },
            "stage_outputs": {},
            "current_stage": "",
            "workflow_id": "wf-test123",
        }

        # Step 2: LangGraph coerces dict to dataclass
        lg_state = LangGraphWorkflowState(**cli_state)

        # Step 3: Node calls to_typed_dict()
        state_dict = lg_state.to_typed_dict()

        # Step 4: Verify workflow_inputs survived
        assert state_dict["workflow_inputs"]["problem_description"] == "Memory leak"
        assert state_dict["workflow_inputs"]["technical_context"] == "asyncio service"
        assert state_dict["workflow_inputs"]["severity"] == "high"

    def test_initialize_state_wraps_inputs(self):
        """initialize_state() stores input_data in workflow_inputs."""
        state = initialize_state(
            input_data={
                "problem_description": "test problem",
                "technical_context": "test context",
            }
        )
        assert state["workflow_inputs"]["problem_description"] == "test problem"
        assert state["workflow_inputs"]["technical_context"] == "test context"

    def test_sequential_helpers_unwrap(self):
        """Sequential executor unwraps workflow_inputs into input_data."""
        state_dict = {
            "workflow_inputs": {
                "problem_description": "test",
                "technical_context": "ctx",
            },
            "stage_outputs": {"stage1": {"output": "result"}},
            "current_stage": "stage1",
        }

        # Simulate the unwrap logic from _sequential_helpers.py
        input_data = {
            **state_dict,
            **state_dict.get("workflow_inputs", {}),
            "stage_outputs": state_dict.get("stage_outputs", {}),
            "current_stage_agents": {},
        }

        assert input_data["problem_description"] == "test"
        assert input_data["technical_context"] == "ctx"
        assert input_data[StateKeys.STAGE_OUTPUTS] == {"stage1": {"output": "result"}}

    def test_parallel_helpers_unwrap(self):
        """Parallel executor unwraps workflow_inputs into input_data."""
        stage_input = {
            "workflow_inputs": {
                "problem_description": "parallel test",
            },
            "stage_outputs": {},
        }

        # Simulate the unwrap logic from _parallel_helpers.py
        input_data = {**stage_input, **stage_input.get("workflow_inputs", {})}

        assert input_data["problem_description"] == "parallel test"

    def test_empty_workflow_inputs_is_safe(self):
        """Empty workflow_inputs does not cause errors."""
        state = WorkflowDomainState()
        assert state.workflow_inputs == {}

        d = state.to_dict()
        assert d["workflow_inputs"] == {}

        copied = state.copy()
        assert copied.workflow_inputs == {}

    def test_merge_preserves_explicit_workflow_inputs(self):
        """from_dict with both explicit workflow_inputs and extra fields merges them."""
        data = {
            "workflow_inputs": {"existing_key": "existing_value"},
            "extra_custom_field": "extra_value",
        }
        state = WorkflowDomainState.from_dict(data)

        assert state.workflow_inputs["existing_key"] == "existing_value"
        assert state.workflow_inputs["extra_custom_field"] == "extra_value"
