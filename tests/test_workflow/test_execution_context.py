"""Tests for WorkflowExecutionContext TypedDict and WorkflowStateDict alias.

Verifies the TypedDict structure, optional-key semantics (total=False),
and that WorkflowStateDict is the canonical alias for the same type.
"""

import pytest

from temper_ai.workflow.execution_context import (
    WorkflowExecutionContext,
    WorkflowStateDict,
)


class TestWorkflowExecutionContext:
    """Tests for WorkflowExecutionContext TypedDict creation and key access."""

    def test_empty_dict_is_valid(self):
        """All keys are optional (total=False) — an empty dict is a valid context."""
        ctx: WorkflowExecutionContext = {}
        assert ctx == {}

    def test_core_identity_keys(self):
        ctx: WorkflowExecutionContext = {
            "workflow_id": "wf-001",
            "current_stage": "triage",
        }
        assert ctx["workflow_id"] == "wf-001"
        assert ctx["current_stage"] == "triage"

    def test_stage_outputs_key(self):
        ctx: WorkflowExecutionContext = {
            "stage_outputs": {"triage": {"final_decision": "approved"}},
        }
        assert ctx["stage_outputs"]["triage"]["final_decision"] == "approved"

    def test_workflow_inputs_key(self):
        ctx: WorkflowExecutionContext = {
            "workflow_inputs": {"topic": "auth", "depth": "deep"},
        }
        assert ctx["workflow_inputs"]["topic"] == "auth"

    def test_common_input_fields(self):
        ctx: WorkflowExecutionContext = {
            "topic": "security",
            "depth": "deep",
            "focus_areas": ["auth", "encryption"],
            "query": "How to harden the system?",
            "input": "raw input text",
            "context": "background context",
            "data": {"arbitrary": True},
        }
        assert ctx["topic"] == "security"
        assert ctx["focus_areas"] == ["auth", "encryption"]
        assert ctx["data"] == {"arbitrary": True}

    def test_parallel_executor_state_keys(self):
        ctx: WorkflowExecutionContext = {
            "agent_outputs": {"agent1": "result"},
            "agent_statuses": {"agent1": "completed"},
            "agent_metrics": {"agent1": {"latency_ms": 120}},
            "errors": {},
            "stage_input": {"key": "value"},
        }
        assert ctx["agent_outputs"]["agent1"] == "result"
        assert ctx["stage_input"]["key"] == "value"
        assert ctx["errors"] == {}


class TestWorkflowStateDict:
    """Tests for WorkflowStateDict backward-compat alias."""

    def test_alias_is_same_object(self):
        """WorkflowStateDict must be the exact same object as WorkflowExecutionContext."""
        assert WorkflowStateDict is WorkflowExecutionContext

    def test_alias_creates_compatible_dict(self):
        state: WorkflowStateDict = {"workflow_id": "test-123", "current_stage": "init"}
        assert state["workflow_id"] == "test-123"
        assert state["current_stage"] == "init"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
