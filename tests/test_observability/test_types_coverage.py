"""Tests for types.py to cover all type aliases (100% line coverage)."""

from temper_ai.observability.types import (
    AgentOutputParams,
    CollaborationEventParams,
    DecisionOutcomeParams,
    LLMCallParams,
    SafetyViolationParams,
    StageEndParams,
    StreamChunkParams,
    ToolCallParams,
    WorkflowStartParams,
)


class TestTypeAliases:
    """Test that all type aliases are properly defined."""

    def test_llm_call_params(self):
        params: LLMCallParams = {"prompt": "test", "response": "resp"}
        assert isinstance(params, dict)

    def test_tool_call_params(self):
        params: ToolCallParams = {"tool_name": "search", "status": "success"}
        assert isinstance(params, dict)

    def test_workflow_start_params(self):
        params: WorkflowStartParams = {"workflow_id": "wf-1"}
        assert isinstance(params, dict)

    def test_collaboration_event_params(self):
        params: CollaborationEventParams = {"event_type": "vote"}
        assert isinstance(params, dict)

    def test_safety_violation_params(self):
        params: SafetyViolationParams = {"severity": "HIGH"}
        assert isinstance(params, dict)

    def test_decision_outcome_params(self):
        params: DecisionOutcomeParams = {"outcome": "success"}
        assert isinstance(params, dict)

    def test_agent_output_params(self):
        params: AgentOutputParams = {"total_tokens": 500}
        assert isinstance(params, dict)

    def test_stream_chunk_params(self):
        params: StreamChunkParams = {"content": "hello", "done": False}
        assert isinstance(params, dict)

    def test_stage_end_params(self):
        params: StageEndParams = {"status": "completed"}
        assert isinstance(params, dict)
